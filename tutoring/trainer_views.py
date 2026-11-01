"""Die Ansichten des Trainers.

Bewusst eine eigene Datei: views.py traegt schon die Aufgabenhilfe, und die
beiden Funktionen haben ausser Beitritt und Tierwahl wenig gemeinsam.

Bewusst auch synchron und ohne Streaming. Ein Zug des Trainers ist eine
abgeschlossene Sache mit einem Urteil daran; ihn Stueck fuer Stueck
auszugeben haette den Vorteil des schnelleren ersten Zeichens und den
Nachteil, dass der Zustandswechsel erst hinterher feststeht. Die Anwendung
fuehrt hier, nicht die Anzeige.
"""

import logging

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import levels, pruefung, trainer
from .models import TrainerLauf, TrainerZug
from .spark import SparkNichtErreichbar, antwort_holen_sync, sprache_moeglich

logger = logging.getLogger(__name__)

MAX_EINGABE = 2000


def _lauf_holen(teilnahme, anlegen=True):
    """Der laufende Lauf dieser Teilnahme, sonst ein neuer."""
    lauf = teilnahme.trainerlaeufe.order_by("created_at").last()
    if lauf is not None and lauf.finished_at is None:
        return lauf
    if not anlegen:
        return lauf
    return TrainerLauf.objects.create(participation=teilnahme)


def _verlauf_text(lauf, hoechstens=16):
    """Der bisherige Gespraechsverlauf als Text fuer das Modell."""
    zeilen = []
    if lauf.topic:
        zeilen.append(f"Das Thema lautet: {lauf.topic}")
    # Die LETZTEN Zuege, nicht die ersten: In einem langen Lauf saehe das
    # Modell sonst nur den Anfang und wuesste nichts vom aktuellen Schritt.
    letzte = list(lauf.zuege.order_by("-created_at", "-pk")[:hoechstens])
    for zug in reversed(letzte):
        if zug.role == TrainerZug.TRAINER:
            stueck = zug.text
            if zug.question:
                stueck = (stueck + " " + zug.question).strip()
            zeilen.append(f"Trainer: {stueck}")
        else:
            zeilen.append(f"Lernende Person: {zug.text}")
    return "\n".join(zeilen)


def _umgebung(teilnahme, lauf):
    sitzung = teilnahme.learning_session
    return {
        "sitzung": sitzung,
        "teilnahme": teilnahme,
        "lauf": lauf,
        "zuege": list(lauf.zuege.order_by("created_at", "pk")),
        "sprache_moeglich": sprache_moeglich(),
        "zustand_text": trainer.ZUSTAND_TEXT.get(lauf.state, ""),
    }


def trainerseite(request):
    """Der Arbeitsplatz der lernenden Person im Trainer."""
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
    if not sitzung.ist_trainer:
        return redirect("tutoring:chat")
    if not teilnahme.hat_tier:
        return redirect("tutoring:tier_waehlen")

    lauf = _lauf_holen(teilnahme)
    return render(request, "tutoring/trainer.html", _umgebung(teilnahme, lauf))


def _abweisen(request, meldung, status=400):
    """Antwortet so, wie gefragt wurde: JSON auf JSON, sonst die Seite.

    Ohne diese Unterscheidung stand bei abgeschaltetem JavaScript nackter
    JSON-Text auf dem Bildschirm.
    """
    if request.headers.get("X-Antwort") == "json":
        return JsonResponse({"ok": False, "meldung": meldung}, status=status)

    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")
    lauf = _lauf_holen(teilnahme)
    umgebung = _umgebung(teilnahme, lauf)
    umgebung["fehler"] = meldung
    return render(request, "tutoring/trainer.html", umgebung, status=status)


@require_POST
def trainer_zug(request):
    """Ein Zug: Eingabe entgegennehmen, Antwort holen, Zustand fortschreiben.

    Die Reihenfolge ist wichtig. Erst wird der Beitrag gespeichert, dann
    gefragt, dann entschieden. Faellt der Spark zwischendurch aus, ist der
    Beitrag trotzdem da.
    """
    from .views import _foto_aus, _herkunft_aus, _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return _abweisen(request, "Die Sitzung ist beendet.")

    lauf = _lauf_holen(teilnahme)
    if lauf.finished_at is not None:
        return _abweisen(request, "Dieses Thema ist abgeschlossen. "
                                  "Du kannst ein neues beginnen.")

    text = (request.POST.get("text") or "").strip()[:MAX_EINGABE]
    foto = _foto_aus(request)
    if not text and not foto and lauf.zuege.exists():
        return _abweisen(request, "Schreib oder sprich bitte etwas.")

    # --- Der Beitrag der lernenden Person --------------------------------
    if text or foto:
        ampel, grund = pruefung.einstufen(text)
        TrainerZug.objects.create(
            run=lauf, role=TrainerZug.LERNEND, text=text, image_data_url=foto,
            source=_herkunft_aus(request, foto), state=lauf.state,
            flag=ampel, flag_reason=grund,
        )
        teilnahme.einstufung_merken(ampel)
        if lauf.state == trainer.THEMA and not lauf.topic:
            lauf.topic = text[:300]

    sitzung.beruehren()
    vorheriger_zustand = lauf.state

    # --- Erst das Urteil ueber die eben gegebene Antwort -----------------
    #
    # Getrennter, kurzer Aufruf. In einem einzigen Aufruf kaeme das Urteil
    # mit der Antwort zurueck, die Entscheidung muesste also vorher fallen -
    # der Trainer haette eine Runde zu spaet gemerkt, dass jemand nicht
    # mitkommt.
    urteil = {"urteil": "", "fehlertyp": ""}
    offene_frage = _offene_frage(lauf)
    if text and offene_frage:
        try:
            roh_urteil, messung_urteil = antwort_holen_sync(
                trainer.URTEIL_PROMPT,
                trainer.URTEIL_FRAGE.format(frage=offene_frage, antwort=text),
                max_tokens=120,
            )
            urteil = trainer.urteil_lesen(roh_urteil)
            _aufzeichnen(sitzung, teilnahme, "urteil", messung_urteil,
                         offene_frage, roh_urteil)
        except SparkNichtErreichbar:
            # Ohne Urteil geht es weiter, als waere es halb verstanden. Ein
            # Ausfall des Modells darf den Lauf nicht abbrechen.
            logger.warning("Kein Urteil, Spark nicht erreichbar.")
            urteil = {"urteil": trainer.TEILWEISE, "fehlertyp": ""}

    # --- Dann entscheidet die Anwendung ----------------------------------
    zustand, darstellung, schleife = trainer.naechster_zustand(
        lauf, urteil["urteil"]
    )

    anrede = levels.anrede(sitzung.age_group)
    system = trainer.system_prompt(
        zustand, anrede, darstellung=darstellung, schleife=schleife,
        versucht=lauf.versucht, fehlertyp=urteil["fehlertyp"],
        letzter=_letzte_erklaerung(lauf) if schleife else "",
        beitrag=text if schleife else "",
    )

    # --- Und erst dann formuliert das Modell -----------------------------
    try:
        roh, messung = antwort_holen_sync(system, _verlauf_text(lauf))
    except SparkNichtErreichbar as fehler:
        return JsonResponse({"ok": False, "meldung": fehler.meldung}, status=503)

    antwort = trainer.antwort_lesen(roh)
    frage = trainer.eine_frage(antwort["frage"])
    erklaerung = trainer.ohne_frage(antwort["text"], frage)
    if not erklaerung and not frage:
        # Ein leerer Zug waere schlimmer als ein belangloser: Das Kind saehe
        # eine leere Blase und wuesste nicht, ob es dran ist.
        erklaerung = "Da ist mir gerade etwas durcheinandergekommen."
        frage = "Sag mir bitte noch einmal, wo du stehst."

    # --- Fortschreiben ---------------------------------------------------
    # Eine richtig geloeste Pruefaufgabe zaehlt dort, wo sie gestellt wurde,
    # also im Zustand VOR diesem Zug.
    if (vorheriger_zustand == trainer.PRUEFUNG
            and urteil["urteil"] == trainer.VERSTANDEN):
        lauf.tasks_right += 1

    lauf.state = zustand
    lauf.representation = darstellung
    if darstellung not in lauf.tried:
        lauf.tried = list(lauf.tried) + [darstellung]
    lauf.loops = lauf.loops + 1 if schleife else 0
    if zustand == trainer.LERNSCHRITT and not schleife:
        lauf.step_no += 1
    if zustand == trainer.PRUEFUNG:
        lauf.tasks_given += 1
    if zustand == trainer.ABSCHLUSS:
        lauf.finished_at = timezone.now()
    lauf.save()

    TrainerZug.objects.create(
        run=lauf, role=TrainerZug.TRAINER, text=erklaerung, question=frage,
        state=zustand, representation=darstellung,
        verdict=urteil["urteil"], error_kind=urteil["fehlertyp"],
    )

    _aufzeichnen(sitzung, teilnahme, zustand, messung, system, roh)

    if request.headers.get("X-Antwort") != "json":
        return redirect("tutoring:trainer")

    return JsonResponse({
        "ok": True,
        "zustand": zustand,
        "zustand_text": trainer.ZUSTAND_TEXT.get(zustand, ""),
        "trainer": erklaerung,
        "frage": frage,
        "urteil": urteil["urteil"],
        "fortschritt": {
            "schritt": lauf.step_no,
            "aufgaben_gestellt": lauf.tasks_given,
            "aufgaben_richtig": lauf.tasks_right,
        },
        "fertig": lauf.finished_at is not None,
    })


def _letzte_erklaerung(lauf):
    """Was der Trainer zuletzt erklaert hat, woertlich.

    Damit der naechste Anlauf nicht denselben Satz noch einmal bringt. Ein
    allgemeines Verbot reicht dafuer nicht.
    """
    letzter = lauf.zuege.filter(role=TrainerZug.TRAINER).exclude(
        text=""
    ).order_by("created_at", "pk").last()
    if letzter is None:
        return ""
    return (letzter.text + " " + letzter.question).strip()


def _offene_frage(lauf):
    """Die Frage, auf die gerade geantwortet wurde.

    Ohne sie kann das Modell nicht urteilen: Eine Antwort allein sagt nicht,
    ob sie richtig ist.
    """
    letzter = lauf.zuege.filter(role=TrainerZug.TRAINER).exclude(
        question=""
    ).order_by("created_at", "pk").last()
    return letzter.question if letzter else ""


def _aufzeichnen(sitzung, teilnahme, zustand, messung, frage, antwort):
    """Eine Anfragezeile je Zug, nach denselben drei Protokollstufen."""
    from .models import Interaction

    Interaction.aufzeichnen(
        sitzung=sitzung,
        teilnahme=teilnahme,
        weg=Interaction.LOKAL,
        modell=messung.get("modell", ""),
        tokens_ein=messung.get("tokens_ein", 0),
        tokens_aus=messung.get("tokens_aus", 0),
        dauer_ms=messung.get("dauer_ms", 0),
        ergebnis=f"trainer:{zustand}",
        text_ein=frage,
        text_aus=antwort,
    )


@require_POST
def trainer_neu(request):
    """Ein neues Thema beginnen. Der alte Lauf wird abgeschlossen."""
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    lauf = _lauf_holen(teilnahme, anlegen=False)
    if lauf is not None and lauf.finished_at is None:
        lauf.finished_at = timezone.now()
        lauf.save(update_fields=["finished_at"])
    teilnahme.learning_session.beruehren()
    return redirect("tutoring:trainer")
