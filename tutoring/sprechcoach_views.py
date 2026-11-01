"""Die Ansichten des Sprechcoaches.

Eigene Datei aus demselben Grund wie beim Trainer: Die drei Betriebsarten
teilen den Beitritt und die Tierwahl, sonst wenig.

Synchron und ohne Streaming, auch im Gespraechsmodus. Geprueft wurde, ob die
Antwort satzweise per Server-Sent Events gehen koennte, damit die
Sprachausgabe mit dem ersten Satz beginnt: Sie kann nicht. Die
deterministischen Pruefungen (sprechcoach.verstoesse, verraet_zu_viel)
brauchen den ganzen Zug - genau eine Frage, Satzzahl, Anknuepfen, das
Geheimnis der Aufgabe - und holen bei einem Verstoss einen ZWEITEN Zug, der
den ersten ersetzt. Ein Satz, der schon vorgelesen wurde und dann
zurueckgenommen wird, waere fuer ein Kind schlimmer als eine Sekunde
Warten. Dazu kommt, dass das Modell JSON liefert und der Text erst nach dem
Lesen des Objekts sicher ist.

HOEREN UND ANTWORTEN SIND ZWEI ENDPUNKTE

coach_hoeren schreibt eine Aeusserung ab und sagt, ob sie fertig klingt;
coach_zug nimmt den Beitrag und antwortet. Getrennt, weil der Browser
zwischen beiden entscheidet: Ein Fragment wartet auf seine Fortsetzung,
Stille wird gar nicht erst zum Zug.

DER ABLAUF STEHT HIER, NICHT IM MODELL

Seit den Gespraechsaufgaben (tutoring/sprechaufgaben.py) hat ein Gespraech
Phasen: Planen, Aufgabe, Rollentausch, Wiederholung, Rueckblick
(tutoring/sprechablauf.py). Nach jedem Beitrag des Kindes entscheidet diese
Datei, ob das Ziel erreicht ist und die Phase wechselt - ueber das, was das
Kind gesagt hat, deterministisch. Das Modell bekommt die Phase mitgeteilt und
spielt sie; ob es weitergeht, entscheidet es nicht. Ein Systemprompt ist
eine Bitte.
"""

import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import levels, pruefung, sprechablauf, sprechaufgaben, sprechcoach
from .models import SprachLauf, SprachZug
from .spark import (SparkNichtErreichbar, antwort_holen_sync, sprache_moeglich,
                    transkription)

logger = logging.getLogger(__name__)

MAX_EINGABE = 2000
# So viele Beitraege gehen ins Gespraechsgedaechtnis. Ein Gespraech lebt vom
# Zusammenhang, aber nicht vom ganzen Nachmittag.
GEDAECHTNIS = 14

# Was die Pruefung meldet, wenn der Coach sein Geheimnis ausplaudert.
VERRAET = "verrät zu viel"


def _lauf_holen(teilnahme, anlegen=True):
    lauf = teilnahme.sprachlaeufe.order_by("created_at").last()
    if lauf is not None and lauf.finished_at is None:
        return lauf
    if not anlegen:
        return lauf
    # Mit einer Aufgabe wird zuerst geplant (Regel 12, "think first"), das
    # freie Gespraech faengt gleich an - wie vor den Aufgaben.
    aufgabe = teilnahme.learning_session.sprechaufgabe
    return SprachLauf.objects.create(
        participation=teilnahme, phase=sprechablauf.startphase(aufgabe),
    )


def _verlauf_text(lauf, phasen=None):
    """Das Gespraechsgedaechtnis fuer den Prompt.

    Ohne die Zuege der Sprachsperre: "Sorry, I don't understand" stammt
    nicht vom Modell, und wer es ihm als eigene Antwort vorlegt, bringt ihm
    bei, es von sich aus zu sagen. Der deutsche Beitrag des Kindes dagegen
    bleibt drin - er ist wirklich gefallen.

    `phasen` schraenkt auf diese Phasen ein: In der Wiederholung soll der
    Coach die Aufgabe neu spielen und nicht "as I told you" sagen.
    """
    zeilen = []
    zuege = lauf.zuege.filter(not_understood=False)
    if phasen:
        zuege = zuege.filter(phase__in=phasen)
    letzte = list(zuege.order_by("-created_at", "-pk")[:GEDAECHTNIS])
    for zug in reversed(letzte):
        wer = "Du" if zug.role == SprachZug.COACH else "Lernende Person"
        zeilen.append(f"{wer}: {zug.text}")
    return "\n".join(zeilen)


def _umgebung(teilnahme, lauf):
    from django.urls import reverse

    sitzung = teilnahme.learning_session
    aufgabe = sitzung.sprechaufgabe
    frei = sprechaufgaben.ist_frei(aufgabe)
    return {
        "sitzung": sitzung,
        "teilnahme": teilnahme,
        "lauf": lauf,
        "zuege": list(lauf.zuege.order_by("created_at", "pk")),
        "sprache_moeglich": sprache_moeglich(),
        "spracheingabe_moeglich": sprache_moeglich(),
        # Beim Sprachenlernen ist Hoeren der Zweck, nicht die Zugabe.
        "vorlesen_an": True,
        # Der stille Ausweg "Ich komme nicht weiter".
        "hilfe_url": reverse("tutoring:sprechcoach_hilfe"),
        # Wohin der Browser eine Aeusserung schickt. Eigener Endpunkt neben
        # views.sprache_erkennen: Der Sprechcoach braucht mehr als den Text.
        "hoeren_url": reverse("tutoring:sprechcoach_hoeren"),
        # Der Ablauf (Regel 11 und 12). Die Seite zeigt, was der Server
        # entschieden hat; sie entscheidet nichts selbst.
        "aufgabe": aufgabe,
        "ist_frei": frei,
        "schritte": _schritte(lauf, frei),
        "phasenhinweis": sprechablauf.phasenhinweis(lauf.phase, aufgabe),
        "planen_sekunden": sprechablauf.PLANEN_SEKUNDEN,
        "volksschule": sitzung.ist_volksschule,
        # Die Reflexionsfrage nach Goh & Burns gibt es nur, wenn es einen
        # zweiten Durchgang gab - sonst gibt es nichts zu vergleichen.
        "reflexionsfrage": (
            sprechablauf.reflexionsfrage(aufgabe)
            if lauf.zuege.filter(phase=sprechablauf.WIEDERHOLUNG).exists() else ""
        ),
        "weiter_url": reverse("tutoring:sprechcoach_weiter"),
        "neu_url": reverse("tutoring:sprechcoach_neu"),
    }


def _schritte(lauf, frei):
    """Die Phasenanzeige: vier Schritte, beim freien Gespraech zwei."""
    jetzt = lauf.schritt
    schritte = []
    for phase, name in sprechablauf.SCHRITTE:
        if frei and phase in (sprechablauf.PLANEN, sprechablauf.WIEDERHOLUNG):
            continue
        nr = sprechablauf.SCHRITT_VON[phase]
        schritte.append({"phase": phase, "name": name, "nr": nr,
                         "jetzt": nr == jetzt, "vorbei": nr < jetzt})
    return schritte


def coachseite(request):
    """Der Arbeitsplatz der lernenden Person im Sprechcoach."""
    from .views import SCHLUESSEL_TEILNAHME, _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        request.session.pop(SCHLUESSEL_TEILNAHME, None)
        return render(request, "core/start.html", {
            "fehler": "Die Sitzung ist beendet. Alles, was du eingegeben hast, ist geloescht.",
        })
    if not sitzung.ist_sprechcoach:
        return redirect("tutoring:chat")
    if not teilnahme.hat_tier:
        return redirect("tutoring:tier_waehlen")

    lauf = _lauf_holen(teilnahme)
    # Der Coach faengt an. Wer eine Fremdsprache lernt, soll nicht vor einem
    # leeren Feld sitzen und sich den ersten Satz selbst ausdenken muessen.
    # In der Planungsphase noch nicht: Da wird gedacht, nicht gesprochen.
    if (lauf.phase in sprechablauf.GESPRAECHSPHASEN
            and not lauf.zuege.filter(phase=lauf.phase).exists()):
        _coachzug(sitzung, teilnahme, lauf, erster_zug=True)

    return render(request, "tutoring/sprechcoach.html", _umgebung(teilnahme, lauf))


@require_POST
def coach_hoeren(request):
    """Eine Aeusserung des Kindes abschreiben, und sagen, ob sie fertig klingt.

    Eigener Endpunkt neben views.sprache_erkennen (das auch die Aufgabenhilfe
    nutzt), weil der Sprechcoach mehr wissen muss als den Text:

    - ob ueberhaupt gesprochen wurde (sprechcoach.hat_sprachinhalt, aus den
      Abschnitten von verbose_json). Wenn nicht: "stille", kein Zug, der
      Browser hoert einfach weiter.
    - ob die Aeusserung wie ein abgebrochener Satz aussieht
      (sprechcoach.wirkt_unvollstaendig). Wenn ja: "fragment", der Browser
      wartet kurz und haengt die naechste Aeusserung an.

    Whisper bestimmt die Sprache selbst (sprache=None), aus demselben Grund
    wie bisher: Der Coach muss wissen, OB in der Zielsprache gesprochen
    wurde. "erkannt" reicht der Browser beim Zug zurueck.

    Die Aufnahme wird gelesen, an Whisper gereicht und verworfen. Sie wird
    nirgends abgelegt und steht in keinem Log - das sagt die
    Datenschutzerklaerung zu.
    """
    from .models import Interaction
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or not sitzung.ist_sprechcoach:
        return JsonResponse({"ok": False, "meldung": "Die Sitzung ist beendet."}, status=400)

    aufnahme = request.FILES.get("aufnahme")
    if aufnahme is None:
        return JsonResponse(
            {"ok": False, "meldung": "Es ist keine Aufnahme angekommen."}, status=400
        )

    try:
        ergebnis = transkription(aufnahme.read(), aufnahme.name or "aufnahme.wav", None)
    except SparkNichtErreichbar as fehler:
        return JsonResponse({"ok": False, "meldung": fehler.meldung}, status=503)

    text = (ergebnis.get("text") or "").strip()
    erkannt = (ergebnis.get("language") or "").strip()
    gehoert = sprechcoach.hat_sprachinhalt(ergebnis)
    fragment = gehoert and sprechcoach.wirkt_unvollstaendig(text, sitzung.target_language)

    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=settings.SPARK_AUDIO_MODEL,
        ergebnis="fragment" if fragment else ("ok" if gehoert else "kein_text"),
        text_ein="[Aufnahme]", text_aus=text if gehoert else "",
    )

    if not gehoert:
        return JsonResponse({"ok": True, "stille": True, "text": ""})
    return JsonResponse({
        "ok": True, "stille": False, "text": text, "erkannt": erkannt,
        "fragment": fragment,
    })


@require_POST
def coach_zug(request):
    """Ein Beitrag der lernenden Person, dann die Antwort des Coaches."""
    from .views import _herkunft_aus, _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return _abweisen(request, "Keine Sitzung.", 403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return _abweisen(request, "Die Sitzung ist beendet.")

    lauf = _lauf_holen(teilnahme)
    if lauf.finished_at is not None or lauf.ist_rueckblick:
        return _abweisen(request, "Dieses Gespräch ist beendet.")
    if lauf.ist_planen:
        return _abweisen(request, "Zuerst kurz planen, dann geht es los.")

    text = (request.POST.get("text") or "").strip()[:MAX_EINGABE]
    if not text:
        return _abweisen(request, "Sag oder schreib bitte etwas.")

    phase_vorher = lauf.phase
    ampel, grund = pruefung.einstufen(text)
    SprachZug.objects.create(
        run=lauf, role=SprachZug.LERNEND, text=text,
        source=_herkunft_aus(request, ""), flag=ampel, flag_reason=grund,
        phase=phase_vorher,
    )
    teilnahme.einstufung_merken(ampel)
    sitzung.beruehren()

    # Die Sprachsperre. Der Coach TUT, als verstehe er kein Deutsch: Spricht
    # ein Kind deutsch, antwortet er in der Zielsprache, dass er es nicht
    # versteht - ohne das Modell zu fragen. Das ist eine Entscheidung und
    # kein Fehler; deshalb ein gewoehnlicher Coach-Zug und keine Abweisung.
    #
    # "erkannt" ist, was Whisper beim Hoeren gemeldet hat; der Browser reicht
    # es durch. Bei getipptem Text fehlt es, dann entscheidet die Wortliste
    # allein und irrt im Zweifel zugunsten des Kindes.
    erkannt = (request.POST.get("erkannt") or "").strip()
    if not sprechcoach.ist_zielsprache(text, sitzung.target_language, erkannt):
        zug = SprachZug.objects.create(
            run=lauf, role=SprachZug.COACH,
            text=sprechcoach.nicht_verstanden(sitzung.target_language),
            not_understood=True, phase=phase_vorher,
        )
    else:
        # Der Server entscheidet ueber die Phase, nicht das Modell.
        neu = _phase_nach_beitrag(sitzung, lauf)
        if neu == sprechablauf.RUECKBLICK:
            zug = _abschied(sitzung, lauf)
        else:
            zug = _coachzug(sitzung, teilnahme, lauf,
                            erster_zug=(neu != phase_vorher))
            if zug is None:
                return _abweisen(
                    request, "Der Sprechcoach antwortet gerade nicht. Probier es gleich noch einmal.", 503
                )

    if request.headers.get("X-Antwort") != "json":
        return redirect("tutoring:sprechcoach")

    return JsonResponse({
        "ok": True,
        "coach": zug.text,
        "uebersetzung": zug.translation,
        "korrektur": zug.correction,
        "nicht_verstanden": zug.not_understood,
        "zuege": lauf.zuege.count(),
        # Im Rueckblick nimmt die Ansicht keinen Beitrag mehr an. Das Skript
        # spricht den Abschied und laedt dann die Seite mit dem Rueckblick.
        "fertig": lauf.finished_at is not None or lauf.ist_rueckblick,
        "neu_laden": lauf.ist_rueckblick,
        "phase": lauf.phase,
        "phase_gewechselt": lauf.phase != phase_vorher,
        "schritt": lauf.schritt,
        "phasenhinweis": sprechablauf.phasenhinweis(lauf.phase, sitzung.sprechaufgabe),
    })


def _phase_nach_beitrag(sitzung, lauf):
    """Prueft nach einem Beitrag, ob die Phase wechselt, und setzt sie.

    Gezaehlt wird, was das Kind IN DIESER PHASE gesagt hat: Das Ziel der
    Wiederholung muss in der Wiederholung erreicht werden, nicht schon beim
    ersten Mal.
    """
    aufgabe = sitzung.sprechaufgabe
    beitraege = list(
        lauf.zuege.filter(role=SprachZug.LERNEND, phase=lauf.phase)
        .order_by("created_at", "pk").values_list("text", flat=True)
    )
    vorher = lauf.phase
    neu, erreicht = sprechablauf.nach_beitrag(
        vorher, aufgabe, sitzung.age_group, beitraege,
    )
    if neu == vorher:
        return neu

    felder = {}
    if vorher == sprechablauf.AUFGABE:
        felder["goal_first"] = bool(erreicht)
    elif vorher == sprechablauf.WIEDERHOLUNG:
        felder["goal_second"] = bool(erreicht)
    lauf.phase_setzen(neu, **felder)
    if neu == sprechablauf.RUECKBLICK:
        _rueckblick_ablegen(sitzung, lauf)
    return neu


def _rueckblick_ablegen(sitzung, lauf):
    """Baut die zwei bis drei Punkte einmal und legt sie fest ab."""
    zuege = list(lauf.zuege.order_by("created_at", "pk"))
    lauf.review = sprechablauf.rueckblick(
        zuege, sitzung.sprechaufgabe, sitzung.age_group,
    )
    lauf.save(update_fields=["review"])


def _abschied(sitzung, lauf):
    """Der feste letzte Satz (Regel 13: Abschied als Ritual), ohne Modell."""
    return SprachZug.objects.create(
        run=lauf, role=SprachZug.COACH,
        text=sprechablauf.abschied(sitzung.target_language),
        phase=sprechablauf.RUECKBLICK,
    )


def _coachzug(sitzung, teilnahme, lauf, erster_zug=False):
    """Holt die Antwort des Coaches, geprueft, und legt sie ab.

    Geprueft wird, und das steht hier und nicht im Prompt: Antwortet der
    Coach in der Zielsprache, haelt er die Satzlaenge des Niveaus ein,
    knuepft er an, spiegelt oder lobt er, stellt er die richtige Zahl
    Fragen - und in der Aufgabe: verraet er sein Geheimnis zu frueh. Ein
    Systemprompt ist eine Bitte.
    """
    anrede = levels.anrede(sitzung.age_group)
    sprache = sitzung.target_language
    niveau = sitzung.language_level
    aufgabe = sitzung.sprechaufgabe
    frei = sprechaufgaben.ist_frei(aufgabe)
    phase = lauf.phase

    # Die letzten Beitraege der lernenden Person: der juengste fuer das
    # Anknuepfen, die letzten drei fuer den Schonmodus. Sehr kurze Antworten
    # ueber mehrere Zuege sind ein Angstsignal (Sheen 2008, BIG 2015) - dann
    # keine Korrektur, leichtere Fragen, zuerst den Inhalt bestaetigen.
    letzte_beitraege = list(
        lauf.zuege.filter(role=SprachZug.LERNEND)
        .order_by("-created_at", "-pk")[:3]
    )
    letzter_beitrag = letzte_beitraege[0] if letzte_beitraege else None
    beitrag = letzter_beitrag.text if letzter_beitrag else ""
    # Die Wiederholung faengt neu an: Ihr erster Zug knuepft nicht an den
    # letzten Satz des Rollentauschs an, sondern begruesst in neuer Rolle.
    if erster_zug and phase == sprechablauf.WIEDERHOLUNG:
        beitrag = ""
    schonmodus = sprechcoach.schonmodus_noetig([z.text for z in letzte_beitraege])

    # Was das Kind in diesem Durchgang noch nicht selbst gesagt hat. Der
    # Server nennt es dem Modell, damit es weiss, worauf es hinarbeitet - und
    # prueft damit, ob der Coach zu viel verraet.
    offene = []
    if phase in (sprechablauf.AUFGABE, sprechablauf.WIEDERHOLUNG) and not frei:
        texte = lauf.zuege.filter(
            role=SprachZug.LERNEND, phase=phase
        ).values_list("text", flat=True)
        offene = sprechaufgaben.offene_merkmale(aufgabe, list(texte))
    anweisung = sprechablauf.anweisung(phase, aufgabe, offene, erster_zug)
    kind_fragt = sprechablauf.kind_fragt(phase, aufgabe)
    thema = sitzung.task_hint if frei else aufgabe["ziel"]

    def pruefen(text):
        gefunden = sprechcoach.verstoesse(
            text, sprache, niveau, beitrag, kind_fragt=kind_fragt,
        )
        if not frei and sprechablauf.verraet_zu_viel(text, aufgabe, offene, erster_zug):
            gefunden.append(VERRAET)
        return gefunden

    system = sprechcoach.system_prompt(
        sprache, niveau, thema, anrede, erster_zug=erster_zug,
        schonmodus=schonmodus, phasenanweisung=anweisung,
    )
    frage = (_verlauf_text(lauf, None if frei else sprechablauf.gedaechtnis_phasen(phase))
             or "Das Gespräch beginnt.")

    try:
        roh, messung = antwort_holen_sync(system, frage, max_tokens=500)
    except SparkNichtErreichbar:
        logger.warning("Sprechcoach: Spark nicht erreichbar.")
        return None

    antwort = sprechcoach.antwort_lesen(roh)
    gefunden = pruefen(antwort["antwort"])

    if gefunden:
        logger.warning("Sprechcoach: %s, zweiter Versuch", ", ".join(gefunden))
        schaerfung = _schaerfung(gefunden, sprache, niveau)
        system2 = sprechcoach.system_prompt(
            sprache, niveau, thema, anrede,
            erster_zug=erster_zug, schaerfung=schaerfung, schonmodus=schonmodus,
            phasenanweisung=anweisung,
        )
        try:
            roh, messung = antwort_holen_sync(system2, frage, max_tokens=500)
            zweiter = sprechcoach.antwort_lesen(roh)
            if not pruefen(zweiter["antwort"]):
                antwort = zweiter
            else:
                # Lieber eine knappe Antwort als eine, die das Niveau sprengt.
                # Was nach dem zweiten Versuch noch spiegelt oder nicht
                # anknuepft, bleibt stehen: Ein dritter Aufruf kostet das
                # Kind drei Sekunden mehr Stille, und die Zahl zeigt der
                # Lehrperson im Rueckblick, wo das Modell nicht folgt.
                antwort = zweiter
                antwort["antwort"] = sprechcoach.gekuerzt(
                    zweiter["antwort"], niveau
                ) or sprechcoach.NOTFALL.get(sprache, "")
        except SparkNichtErreichbar:
            antwort["antwort"] = sprechcoach.gekuerzt(antwort["antwort"], niveau)

    if not antwort["antwort"]:
        antwort["antwort"] = sprechcoach.NOTFALL.get(sprache, "")

    # Das Modell fuellte das Korrekturfeld mit seiner eigenen Antwort. Dann
    # stand derselbe Satz zweimal da - und wer eine Korrektur sieht, sucht
    # seinen Fehler darin. Im Schonmodus gibt es gar keine Korrektur.
    korrektur = "" if schonmodus else sprechcoach.brauchbare_korrektur(
        antwort["korrektur"], antwort["antwort"], beitrag,
    )

    zug = SprachZug.objects.create(
        run=lauf, role=SprachZug.COACH, text=antwort["antwort"],
        translation=antwort["uebersetzung"], correction=korrektur,
        phase=phase,
    )
    _aufzeichnen(sitzung, teilnahme, messung, system, roh)
    return zug


def _schaerfung(gefunden, sprache, niveau):
    """Die Nachschaerfung: die Sprache zuerst, dann das Geheimnis, dann der
    Rest in der Reihenfolge von sprechcoach.schaerfung_fuer."""
    andere = [g for g in gefunden if g != VERRAET]
    if VERRAET in gefunden and "falsche Sprache" not in andere:
        return sprechablauf.SCHAERFUNG_VERRAET
    return sprechcoach.schaerfung_fuer(andere, sprache, niveau)


def _abweisen(request, meldung, status=400):
    """Antwortet so, wie gefragt wurde: JSON auf JSON, sonst die Seite."""
    if request.headers.get("X-Antwort") == "json":
        return JsonResponse({"ok": False, "meldung": meldung}, status=status)

    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")
    lauf = _lauf_holen(teilnahme)
    umgebung = _umgebung(teilnahme, lauf)
    umgebung["fehler"] = meldung
    return render(request, "tutoring/sprechcoach.html", umgebung, status=status)


def _aufzeichnen(sitzung, teilnahme, messung, frage, antwort):
    from .models import Interaction

    Interaction.aufzeichnen(
        sitzung=sitzung,
        teilnahme=teilnahme,
        weg=Interaction.LOKAL,
        modell=messung.get("modell", ""),
        tokens_ein=messung.get("tokens_ein", 0),
        tokens_aus=messung.get("tokens_aus", 0),
        dauer_ms=messung.get("dauer_ms", 0),
        ergebnis="sprechcoach",
        text_ein=frage,
        text_aus=antwort,
    )


@require_POST
def coach_weiter(request):
    """Der naechste Schritt auf Wunsch des Kindes.

    Aus dem Planen: "Ich bin bereit" - aber erst nach der Mindestzeit, denn
    ein Klick gleich nach dem Laden ist kein Planen (Regel 12, "think
    first"). Aus dem Gespraech: "Ich höre hier auf" fuehrt in den
    Rueckblick, mit "Ziel nicht erreicht" fuer den laufenden Durchgang. Ein
    Kind darf aufhoeren; die Lehrperson sieht es an der Zahl, nicht an
    einem Vermerk.

    Gewoehnliches Formular, kein JSON: Beides fuehrt auf eine andere
    Ansicht der Seite.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")
    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or not sitzung.ist_sprechcoach:
        return redirect("tutoring:sprechcoach")

    lauf = _lauf_holen(teilnahme)
    if lauf.ist_planen:
        gewartet = (timezone.now() - lauf.phase_seit).total_seconds()
        if gewartet < sprechablauf.planen_mindestens(sitzung.age_group):
            umgebung = _umgebung(teilnahme, lauf)
            umgebung["planen_noch"] = True
            return render(request, "tutoring/sprechcoach.html", umgebung)
        lauf.phase_setzen(sprechablauf.AUFGABE)
    elif lauf.phase in sprechablauf.GESPRAECHSPHASEN:
        felder = {}
        if not sprechaufgaben.ist_frei(sitzung.sprechaufgabe):
            if lauf.phase == sprechablauf.AUFGABE:
                felder["goal_first"] = False
            elif lauf.phase == sprechablauf.WIEDERHOLUNG:
                felder["goal_second"] = False
        lauf.phase_setzen(sprechablauf.RUECKBLICK, **felder)
        _rueckblick_ablegen(sitzung, lauf)
    sitzung.beruehren()
    return redirect("tutoring:sprechcoach")


@require_POST
def coach_neu(request):
    """Ein neues Gespraech beginnen."""
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    lauf = _lauf_holen(teilnahme, anlegen=False)
    if lauf is not None and lauf.finished_at is None:
        lauf.finished_at = timezone.now()
        lauf.save(update_fields=["finished_at"])
    teilnahme.learning_session.beruehren()
    return redirect("tutoring:sprechcoach")


@require_POST
def coach_hilfe(request):
    """Der stille Ausweg: "Ich komme nicht weiter".

    Der Coach bleibt in der Zielsprache, die Hilfe daneben ist deutsch - ein
    Satz, was der Coach gerade wissen will, und ein Beispielsatz in der
    Zielsprache. Eine Sperre ohne Ausweg ist keine Methode, sondern eine
    verschlossene Tuer.

    Nur JSON: Der Knopf steht auf der Gespraechsseite und holt die Hilfe
    nach, ohne dass das Gespraech selbst weitergeht. Deshalb entsteht auch
    kein Zug - die Hilfe ist kein Beitrag.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or not sitzung.ist_sprechcoach:
        return JsonResponse({"ok": False, "meldung": "Die Sitzung ist beendet."}, status=400)

    lauf = _lauf_holen(teilnahme, anlegen=False)
    letzte_frage = ""
    if lauf is not None:
        letzter = (lauf.zuege.filter(role=SprachZug.COACH, not_understood=False)
                   .order_by("created_at", "pk").last())
        letzte_frage = letzter.text if letzter else ""

    sprache = sitzung.target_language
    niveau = sitzung.language_level
    aufgabe = sitzung.sprechaufgabe
    # In einer Aufgabe ist das Ziel das Thema: Die Hilfe soll sagen, was das
    # Kind jetzt fragen koennte, nicht worueber man allgemein redet.
    thema = (sitzung.task_hint or "ein freies Gespräch"
             if sprechaufgaben.ist_frei(aufgabe) else aufgabe["ziel"])
    prompt = sprechcoach.HILFE_PROMPT.format(
        sprache_name=sprechcoach.EIGENNAME.get(sprache, "English"),
        niveau=niveau,
        thema=thema,
        frage=letzte_frage or "(noch keine Frage)",
        woerter=sprechcoach.WOERTER_JE_SATZ.get(niveau, 8),
    )

    try:
        roh, messung = antwort_holen_sync(
            "Du hilfst einem Kind beim Sprachenlernen. Antworte nur mit JSON.",
            prompt, max_tokens=200,
        )
        hilfe = sprechcoach.hilfe_lesen(roh, sprache, niveau)
        _aufzeichnen(sitzung, teilnahme, messung, prompt, roh)
    except SparkNichtErreichbar:
        hilfe = {
            "erklaerung": "Der Coach hat dich etwas gefragt. Antworte mit einem "
                          "kurzen Satz – einzelne Wörter zählen auch.",
            "beispiel": "",
        }
    sitzung.beruehren()

    # Ohne JavaScript ist der Knopf ein gewoehnliches Formular. Dann kommt
    # die Seite zurueck, mit der Hilfe darin - und nicht nacktes JSON.
    if request.headers.get("X-Antwort") != "json":
        umgebung = _umgebung(teilnahme, lauf or _lauf_holen(teilnahme))
        umgebung["hilfe"] = hilfe
        return render(request, "tutoring/sprechcoach.html", umgebung)

    return JsonResponse({"ok": True, **hilfe})


# --- Fuer die Lehrperson: die Zahlen je Kind (Regel 14) -------------------

def zahlen_der_klasse(sitzung):
    """Die Zahlenzeilen je Teilnahme und die Klassensumme.

    Zwei Abfragen fuer die ganze Klasse, nicht je Kind: Die Klassenliste
    wird alle fuenf Sekunden nachgeholt.

    Je Kind zaehlt sein juengstes Gespraech - das, an dem es gerade ist oder
    zuletzt war. Die Klassensumme zaehlt alle Gespraeche.

    In der Volksschule gibt es keine Zahlen je Kind, nur die Summe (Regel 14:
    "Volksschule nur Beobachtungsdaten, keine Niveauzuordnung pro Kind";
    BMBWF-Infoblatt: keine muendlichen Pruefungen). Die Rueckblickpunkte
    stehen trotzdem da: Sie sind keine Zahl, und Regel 6 will sie fuer Kind
    und Lehrperson.
    """
    laeufe = list(
        SprachLauf.objects.filter(participation__learning_session=sitzung)
        .order_by("created_at", "pk")
    )
    zuege_je_lauf = {}
    for zug in (SprachZug.objects.filter(run__in=laeufe)
                .order_by("created_at", "pk")):
        zuege_je_lauf.setdefault(zug.run_id, []).append(zug)

    juengster = {}
    for lauf in laeufe:
        juengster[lauf.participation_id] = lauf

    phasenname = dict(sprechablauf.PHASEN)
    je_teilnahme = {}
    for teilnahme_id, lauf in juengster.items():
        m = sprechablauf.messung(zuege_je_lauf.get(lauf.pk, []))
        je_teilnahme[teilnahme_id] = {
            "phase": phasenname.get(lauf.phase, ""),
            "zahlen": ([] if sitzung.ist_volksschule else
                       sprechablauf.zahlenzeile(m, lauf.goal_first, lauf.goal_second)),
            "rueckblick": lauf.review or [],
        }

    summe = {"beitraege": 0, "woerter": 0, "fragen": 0, "sperren": 0,
             "gespraeche": 0, "mit_ziel": 0, "ziel_erreicht": 0}
    for lauf in laeufe:
        zuege = zuege_je_lauf.get(lauf.pk, [])
        if not zuege:
            continue
        m = sprechablauf.messung(zuege)
        summe["gespraeche"] += 1
        summe["beitraege"] += m["beitraege"]
        summe["woerter"] += m["woerter"]
        summe["fragen"] += m["fragen"]
        summe["sperren"] += m["sperren"]
        if lauf.goal_first is not None:
            summe["mit_ziel"] += 1
            summe["ziel_erreicht"] += 1 if lauf.goal_first else 0
    summe["woerter_je_beitrag"] = sprechablauf.zahl(
        summe["woerter"] / summe["beitraege"] if summe["beitraege"] else 0
    )
    return {"je_teilnahme": je_teilnahme, "summe": summe}
