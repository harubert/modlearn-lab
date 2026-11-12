"""Die Ansichten des Safe Chat.

Eigene Datei wie bei Trainer, Sprechcoach und Musikstunde: Beitritt,
Tierwahl, Verfall und Beenden liegen in views.py und gelten unveraendert,
der Rest hat mit der Aufgabenhilfe nichts gemeinsam.

Thomas (23.10.2026): Die Kinder fragen die KI am Spark und bekommen eine
Antwort; mit einem zweiten Knopf geht die Frage nach draussen, aber nur
durch den Filter am Spark, und jeder Schritt dieses Weges steht fuer Kind
und Lehrperson im Chat. Dazu fragt die Anwendung die Gegenstelle nach jeder
Antwort, ob sie in der Anfrage einen Personenbezug gesehen hat, und zeigt
das Urteil.

Was hier im Server entschieden wird und nicht in einem Prompt: dass ein
roter Beitrag (Schimpfwort) nicht beantwortet wird, dass ohne eingerichtete
und freigegebene Qualitaetssicherung nichts hinausgeht, dass vor dem Senden
die ganze Kette laeuft (cloud.geprueft_fragen), und dass jeder Aufruf nach
draussen eine Zeile im Forschungsprotokoll bekommt.

Synchron wie der Trainer: Ein Zug ist eine abgeschlossene Sache mit einem
Protokoll daran.
"""

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import cloud, fachgrenze, pruefung, safechat
from .models import ChatZug, Interaction
from .spark import SparkNichtErreichbar, gespraech_holen_sync

logger = logging.getLogger(__name__)

# Das Teilstueck, das Zuege samt Protokoll rendert; dieselbe Vorlage auf der
# Seite des Kindes und im Verlauf der Lehrperson.
TEILSTUECK = "tutoring/_safechat_zuege.html"

SITZUNG_BEENDET = ("Die Sitzung ist beendet. Alles, was du eingegeben hast, "
                   "ist geloescht.")
KEIN_SAFECHAT = "Hier gibt es keinen Safe Chat."
NICHTS_GESCHRIEBEN = "Schreib zuerst etwas."
ZU_LANG = f"Höchstens {safechat.TEXT_MAX} Zeichen auf einmal."
WEG_UNBEKANNT = "Unbekannter Weg."
AUSSEN_AUS = "In dieser Stunde geht nichts nach draußen."
# Wenn das Modell am Spark mit einer leeren Antwort kommt. Eine leere Blase
# waere schlimmer als eine belanglose: Das Kind wuesste nicht, ob es dran ist.
ANTWORT_LEER = "Da ist mir gerade etwas durcheinandergekommen. Frag bitte noch einmal."


def _nein(grund, status=400, **mehr):
    return JsonResponse({"ok": False, "grund": grund, **mehr}, status=status)


def aussen_moeglich(sitzung):
    """Darf in dieser Stunde etwas hinausgehen?

    Beides muss gelten: Die Lehrperson hat die Qualitaetssicherung
    angehakt, und ein Zugang ist eingerichtet. Ein Knopf, hinter dem nichts
    steht, waere eine Zusage, die niemand einhaelt.
    """
    return bool(sitzung.cloud_enabled and cloud.moeglich())


def _umgebung(teilnahme):
    sitzung = teilnahme.learning_session
    zuege = safechat.mit_protokoll(
        list(teilnahme.chatzuege.order_by("created_at", "pk"))
    )
    return {
        "sitzung": sitzung,
        "teilnahme": teilnahme,
        "zuege": zuege,
        "aussen_moeglich": aussen_moeglich(sitzung),
        "zug_url": reverse("tutoring:safechat_zug"),
        "text_max": safechat.TEXT_MAX,
        "thema": sitzung.task_hint,
    }


def chatseite(request):
    """Der Arbeitsplatz des Kindes im Safe Chat."""
    from .views import SCHLUESSEL_TEILNAHME, _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        request.session.pop(SCHLUESSEL_TEILNAHME, None)
        return render(request, "core/start.html", {"fehler": SITZUNG_BEENDET})
    if not sitzung.ist_safechat:
        return redirect("tutoring:chat")
    if not teilnahme.hat_tier:
        return redirect("tutoring:tier_waehlen")

    return render(request, "tutoring/safechat.html", _umgebung(teilnahme))


def _felder(request):
    """Text und Weg, aus dem Formular oder aus einem JSON-Rumpf.

    Das Skript darf schicken, wie es will; der Server liest beides. Was
    nicht lesbar ist, gilt als leer und wird unten abgewiesen.
    """
    if request.content_type == "application/json":
        try:
            daten = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            daten = {}
        if not isinstance(daten, dict):
            daten = {}
    else:
        daten = request.POST
    text = str(daten.get("text") or "").strip()
    weg = str(daten.get("weg") or "").strip().lower()
    return text, weg


@require_POST
def chat_zug(request):
    """Ein Beitrag des Kindes und die Antwort darauf.

    Die Reihenfolge ist wichtig: erst die Ampel, dann der Beitrag in die
    Datenbank, dann die Antwort. Faellt der Spark aus, ist der Beitrag
    trotzdem da und die Seite zeigt ihn beim naechsten Laden.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return _nein("Keine Sitzung.", 403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return _nein("Die Sitzung ist beendet.")
    if not sitzung.ist_safechat or not teilnahme.hat_tier:
        return _nein(KEIN_SAFECHAT, 403)

    text, weg = _felder(request)
    if not text:
        return _nein(NICHTS_GESCHRIEBEN)
    if len(text) > safechat.TEXT_MAX:
        return _nein(ZU_LANG)
    if weg not in (ChatZug.WEG_SPARK, ChatZug.WEG_AUSSEN):
        return _nein(WEG_UNBEKANNT)
    # Vor dem Anlegen geprueft, nicht danach: Ein Beitrag, der gar nicht
    # beantwortet werden kann, soll nicht als Zug ohne Antwort stehen.
    if weg == ChatZug.WEG_AUSSEN and not aussen_moeglich(sitzung):
        return _nein(AUSSEN_AUS, 403)

    # --- Der Beitrag des Kindes, mit Ampel ------------------------------
    ampel, grund = pruefung.einstufen(text)
    kind = ChatZug.objects.create(
        participation=teilnahme, role=ChatZug.LERNEND, text=text, weg=weg,
        flag=ampel, flag_reason=grund,
    )
    teilnahme.einstufung_merken(ampel)
    sitzung.beruehren()

    # --- Die Antwort --------------------------------------------------
    if ampel == pruefung.ROT:
        # Schimpfwort oder Beleidigung: kein Aufruf, nirgendwohin. Der Weg
        # bleibt am Zug stehen, damit die Lehrperson sieht, was das Kind
        # wollte.
        ki = ChatZug.objects.create(
            participation=teilnahme, role=ChatZug.KI,
            text=safechat.NICHT_BEANTWORTET, weg=weg,
        )
    elif weg == ChatZug.WEG_SPARK:
        try:
            ki = _am_spark(sitzung, teilnahme, text)
        except SparkNichtErreichbar as fehler:
            return _nein(fehler.meldung, 503, ampel=ampel)
    else:
        ki = _nach_draussen(sitzung, teilnahme, text)

    return JsonResponse({
        "ok": True,
        "ampel": ampel,
        "weg": ki.weg,
        "urteil": ki.urteil,
        "ausweichen": bool(getattr(ki, "ausweichen", "")),
        "html": render_to_string(TEILSTUECK, {
            "zuege": safechat.mit_protokoll([kind, ki]),
            "sitzung": sitzung,
            "teilnahme": teilnahme,
        }, request=request),
    })


def _am_spark(sitzung, teilnahme, text):
    """Die Antwort vom Spark, mit den letzten Zuegen als Gespraech."""
    system = safechat.system_prompt(sitzung.age_group, sitzung.task_hint)
    # Die LETZTEN Zuege, den eben angelegten eingeschlossen; dann in die
    # richtige Reihenfolge gedreht.
    letzte = list(
        teilnahme.chatzuege.order_by("-created_at", "-pk")[:safechat.VERLAUF_FENSTER]
    )
    nachrichten = safechat.nachrichten_fuer_spark(reversed(letzte))

    antwort, messung = gespraech_holen_sync(system, nachrichten)
    antwort = (antwort or "").strip() or ANTWORT_LEER

    # Die Form der Verweigerung (fachgrenze, 7.11.2026): Traegt die Antwort
    # die Form einer politischen Verweigerung, liest das Kind den festen
    # Satz; der Wortlaut des Modells steht nur im Forschungsprotokoll. Nicht
    # das Thema wird geprueft, die Form - fuer Peking wie fuer jedes andere.
    grund = fachgrenze.ausweichen_erkannt(antwort)
    fuer_kind = antwort
    if grund:
        logger.info("Safe Chat: Antwort zurueckgehalten (%s).", grund)
        fuer_kind = safechat.ausweichen_satz(aussen_moeglich(sitzung), sitzung.age_group)

    ki = ChatZug.objects.create(
        participation=teilnahme, role=ChatZug.KI, text=fuer_kind,
        weg=ChatZug.WEG_SPARK, ausweichen=grund,
    )
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=messung.get("modell", ""),
        tokens_ein=messung.get("tokens_ein", 0),
        tokens_aus=messung.get("tokens_aus", 0),
        dauer_ms=messung.get("dauer_ms", 0),
        leak_check=Interaction.ENTFAELLT,
        ergebnis="safechat:ausgewichen" if grund else "safechat",
        text_ein=text, text_aus=antwort,
    )
    return ki


def _nach_draussen(sitzung, teilnahme, text):
    """Der Weg nach draussen, mit Protokoll am Zug und im Forschungsprotokoll.

    Dieselbe Kette wie die Qualitaetssicherung (cloud.geprueft_fragen),
    mit der Anweisung fuer den Chat. Bleibt der Weg zu, bekommt das Kind
    den Grund als Antwort, und der Zug traegt ihn; nichts ist hinausgegangen.
    Ging es hinaus, folgt die zweite Frage an die Gegenstelle: ob sie einen
    Personenbezug gesehen hat. Ihre Token kommen zu denen des Zuges dazu,
    denn beide Aufrufe gehoeren zu derselben Frage des Kindes.
    """
    from .views import cloud_verbrauch

    verbrauch = cloud_verbrauch(sitzung)
    try:
        ergebnis = cloud.geprueft_fragen(
            text, verbrauch, system=cloud.system_chat(sitzung.age_group),
        )
    except cloud.CloudGesperrt as fehler:
        logger.warning("Safe Chat: Weg nach draussen zu: %s", fehler.art)
        return _gesperrt(sitzung, teilnahme, fehler.grund, "gesperrt", fehler.art)
    except Exception as fehler:  # noqa: BLE001 - der Chat laeuft weiter
        logger.warning("Safe Chat: Weg nach draussen gescheitert: %s",
                       type(fehler).__name__)
        return _gesperrt(sitzung, teilnahme, "Die externe KI hat nicht geantwortet.",
                         "fehler", type(fehler).__name__)

    kosten = cloud.kosten_micro(
        ergebnis["modell"], ergebnis["tokens_ein"], ergebnis["tokens_aus"]
    )
    ki = ChatZug.objects.create(
        participation=teilnahme, role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN,
        text=ergebnis["loesung"],
        aussen_umgeschrieben=ergebnis.get("umgeschrieben", ""),
        aussen_gesendet=ergebnis["maskiert_ein"],
        aussen_empfangen=ergebnis["maskiert_aus"],
        aussen_entitaeten=ergebnis["entitaeten"],
        aussen_modell=ergebnis["modell"],
        aussen_tokens_in=ergebnis["tokens_ein"],
        aussen_tokens_out=ergebnis["tokens_aus"],
        aussen_ms=ergebnis["dauer_ms"],
        aussen_cost_micro=kosten,
    )
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.CLOUD,
        modell=ergebnis["modell"],
        tokens_ein=ergebnis["tokens_ein"], tokens_aus=ergebnis["tokens_aus"],
        dauer_ms=ergebnis["dauer_ms"], kosten_micro=kosten,
        leak_check=Interaction.BESTANDEN, entitaeten=ergebnis["entitaeten"],
        ergebnis="ok",
        maskiert_ein=ergebnis["maskiert_ein"], maskiert_aus=ergebnis["maskiert_aus"],
        text_aus=ergebnis["loesung"], anweisung=ergebnis.get("anweisung", ""),
    )

    # --- Die zweite Frage: Hat die Gegenstelle Personenbezug gesehen? ---
    urteil = cloud.urteil_holen(ergebnis["maskiert_ein"], ergebnis["maskiert_aus"])
    ki.urteil = urteil["urteil"]
    ki.urteil_grund = (urteil.get("grund") or "")[:240]
    ki.aussen_tokens_in += urteil.get("tokens_ein", 0)
    ki.aussen_tokens_out += urteil.get("tokens_aus", 0)
    ki.aussen_ms += urteil.get("dauer_ms", 0)
    ki.aussen_cost_micro = cloud.kosten_micro(
        ergebnis["modell"], ki.aussen_tokens_in, ki.aussen_tokens_out
    )
    ki.save(update_fields=[
        "urteil", "urteil_grund", "aussen_tokens_in", "aussen_tokens_out",
        "aussen_ms", "aussen_cost_micro",
    ])
    # Auch das Urteil ist ein Aufruf nach draussen und zaehlt gegen das
    # Budget. Hinausgegangen ist dabei nichts Neues: dieselbe maskierte
    # Anfrage und die Antwort darauf.
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.CLOUD,
        modell=ergebnis["modell"],
        tokens_ein=urteil.get("tokens_ein", 0), tokens_aus=urteil.get("tokens_aus", 0),
        dauer_ms=urteil.get("dauer_ms", 0),
        kosten_micro=cloud.kosten_micro(
            ergebnis["modell"], urteil.get("tokens_ein", 0), urteil.get("tokens_aus", 0)
        ),
        leak_check=Interaction.BESTANDEN, ergebnis=f"urteil:{urteil['urteil']}",
        maskiert_ein=ergebnis["maskiert_ein"], maskiert_aus=urteil.get("grund", ""),
        text_aus=urteil.get("grund", ""), anweisung=urteil.get("anweisung", ""),
    )
    return ki


def _gesperrt(sitzung, teilnahme, grund, ergebnis, fehlerart):
    """Der Zug, wenn nichts hinausgegangen ist, samt Protokollzeile."""
    ki = ChatZug.objects.create(
        participation=teilnahme, role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN,
        text=safechat.aussen_gesperrt_satz(grund),
        aussen_gesperrt=(grund or "")[:120],
    )
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.CLOUD,
        modell=settings.CLOUD_MODEL, ergebnis=ergebnis, fehlerart=fehlerart[:60],
        leak_check=Interaction.BLOCKIERT,
    )
    return ki
