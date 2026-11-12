"""Sprachausgabe: der Aufruf der Stimme am Spark aus der App (7.11.2026).

Der Dienst steht in ablage/spark-tts (Qwen3-TTS-12Hz-1.7B-CustomVoice,
Apache 2.0; Stimme "Ryan", Thomas 6.11.2026) und spricht die Schnittstelle
von OpenAI: POST {SPARK_TTS_BASE_URL}/audio/speech mit input, voice,
language, response_format; zurueck kommt WAV mit 24 kHz. Derselbe Umgang
wie mit Whisper (spark.transkription): ein Aufruf, eine Datei.

WAS HIER ENTSCHIEDEN IST

- Gesprochen wird nur, was die Anwendung selbst geschrieben hat. Die
  Ansicht (stimme_views) nimmt die Kennung eines Zuges entgegen, nie freien
  Text. Sonst waere die Stimme ein Sprechautomat fuer beliebige Saetze, und
  die Fachgrenze haette eine Hintertuer.
- Fehlt die Adresse, gibt es keine Stimme vom Server, und der Browser liest
  wie bisher selbst (speechSynthesis). Das ist ein Zustand, kein Fehler;
  die Seite zeigt den Knopf dann nur, wenn der Browser eine Stimme hat.
- Die Attrappe (SPARK_TTS_ATTRAPPE=1) erzeugt ohne Netz eine hoerbare
  Tonfolge in der Laenge des Textes. Sie ist fuer die Entwicklung am PC und
  fuer Tests da: Der ganze Weg (Knopf, Anfrage, Abspielen, Protokoll) laesst
  sich bauen und pruefen, bevor die Stimme am Spark laeuft. Im Protokoll
  heisst ihr Modell "attrappe". Steht eine Adresse in den Einstellungen,
  wird sie nie benutzt.
- Ein kleiner Zwischenspeicher je Prozess: "nochmal hoeren" kostet keinen
  zweiten Aufruf, und die Saetze eines Zuges liegen bereit, sobald sie
  einmal gesprochen wurden.

Die Stimme braucht am GB10 rund die dreifache Echtzeit (Hoerprobe 5.11.):
Ein Zug von drei Saetzen dauert also einige Sekunden, bevor der erste Ton
kommt. Darum zerlegt saetze() einen Zug, damit die Ansicht Satz fuer Satz
holen und schon den ersten spielen kann, waehrend der zweite entsteht.
"""

import array
import collections
import io
import logging
import math
import pathlib
import re
import threading
import time
import wave

import httpx
from django.conf import settings

from .spark import SparkNichtErreichbar

logger = logging.getLogger(__name__)

ATTRAPPE = "attrappe"
MAX_ZEICHEN = 1200          # TTS_MAX_ZEICHEN des Dienstes
ABTASTRATE = 24000          # was Qwen3-TTS liefert; die Attrappe gleicht sich an
MELDUNG_AUS = "Die Sprachausgabe ist auf diesem Rechner nicht eingerichtet."
MELDUNG_WEG = ("Die Stimme der Hochschule antwortet gerade nicht. Der Text steht "
               "trotzdem da.")

# BCP-47 (Sitzung, Browser) auf den Namen, den der Dienst erwartet.
SPRACHEN = {"de": "German", "en": "English", "fr": "French", "it": "Italian",
            "es": "Spanish"}

_SATZENDE = re.compile(r"(?<=[.!?…])\s+")
KURZ = 8                    # Zeichen; kuerzere Saetze haengen am Nachbarn
_ZWISCHENSPEICHER = collections.OrderedDict()
_ZWISCHENSPEICHER_GROESSE = 64
_SCHLOSS = threading.Lock()


def moeglich():
    """Gibt es eine Stimme vom Server: Dienst am Spark oder Attrappe?"""
    return bool(getattr(settings, "SPARK_TTS_BASE_URL", "")) or attrappe_an()


def attrappe_an():
    """Die Attrappe gilt nur ohne Adresse: Mit Adresse spricht der Dienst."""
    return (bool(getattr(settings, "SPARK_TTS_ATTRAPPE", False))
            and not getattr(settings, "SPARK_TTS_BASE_URL", ""))


def sprachname(code):
    """"en-GB" -> "English"; Unbekanntes faellt auf Deutsch zurueck."""
    kurz = (code or "de").split("-")[0].lower()
    return SPRACHEN.get(kurz, SPRACHEN["de"])


def saetze(text):
    """Zerlegt einen Zug in Saetze, damit die Ansicht ihn stueckweise holt.

    Grob an Satzzeichen plus Leerraum; sehr kurze Stuecke ("Yes." vor
    "What about you?") haengen am Nachbarn, weil ein Ton von einer halben
    Sekunde mit einer Pause davor und danach wie ein Stottern klingt.
    """
    roh = [s.strip() for s in _SATZENDE.split((text or "").strip()) if s.strip()]
    ergebnis = []
    for stueck in roh:
        if ergebnis and (len(stueck) < KURZ or len(ergebnis[-1]) < KURZ):
            ergebnis[-1] = ergebnis[-1] + " " + stueck
        else:
            ergebnis.append(stueck)
    return ergebnis


def _geheimnis():
    """Das Geheimnis des Brokers, wenn es die Datei gibt; sonst leer.

    Der Dienst kann ein Geheimnis in X-Broker-Secret verlangen
    (TTS_GEHEIMNIS_DATEI) und teilt es dann mit Broker und Musikdienst. Ohne
    Datei ist er offen im Tailnet, wie Whisper, und der Kopf bleibt weg.
    """
    pfad = getattr(settings, "SPARK_BROKER_SECRET_DATEI", "")
    try:
        return pathlib.Path(pfad).read_text(encoding="utf-8").strip() if pfad else ""
    except OSError:
        return ""


def _anfragen(rumpf, adresse):
    """Der eine Aufruf. Getrennt, damit Tests ihn ersetzen koennen."""
    frist = getattr(settings, "SPARK_TTS_TIMEOUT_SECONDS", 60)
    kopf = {}
    geheimnis = _geheimnis()
    if geheimnis:
        kopf["X-Broker-Secret"] = geheimnis
    with httpx.Client(timeout=frist) as client:
        antwort = client.post(f"{adresse}/audio/speech", json=rumpf, headers=kopf)
        antwort.raise_for_status()
        return antwort.content


def sprechen(text, sprache="de-DE", stimme=""):
    """Spricht einen Text. Gibt (wav_bytes, messung) zurueck.

    Wirft SparkNichtErreichbar, wenn keine Stimme eingerichtet ist oder der
    Dienst nicht antwortet; die Ansicht macht daraus eine Meldung, die
    Seite liest dann mit der Browserstimme oder gar nicht. Der Text ist
    nach MAX_ZEICHEN abgeschnitten, wie der Dienst es verlangt.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())[:MAX_ZEICHEN]
    if not text:
        raise SparkNichtErreichbar("Es gibt nichts zu sprechen.")
    if not moeglich():
        raise SparkNichtErreichbar(MELDUNG_AUS)

    stimme = stimme or getattr(settings, "SPARK_TTS_STIMME", "Ryan")
    sprache_name = sprachname(sprache)
    schluessel = (text, stimme, sprache_name, attrappe_an())
    with _SCHLOSS:
        treffer = _ZWISCHENSPEICHER.get(schluessel)
        if treffer is not None:
            _ZWISCHENSPEICHER.move_to_end(schluessel)
            daten, messung = treffer
            return daten, {**messung, "zwischenspeicher": True}

    begonnen = time.monotonic()
    if attrappe_an():
        daten = attrappe(text)
        modell = ATTRAPPE
    else:
        adresse = settings.SPARK_TTS_BASE_URL.rstrip("/")
        rumpf = {"input": text, "voice": stimme, "language": sprache_name,
                 "response_format": "wav", "model": settings.SPARK_TTS_MODEL}
        try:
            daten = _anfragen(rumpf, adresse)
        except (httpx.HTTPError, OSError) as fehler:
            logger.warning("Sprachausgabe fehlgeschlagen: %s", type(fehler).__name__)
            raise SparkNichtErreichbar(MELDUNG_WEG) from fehler
        if not daten or len(daten) < 44 or daten[:4] != b"RIFF":
            logger.warning("Sprachausgabe: keine WAV-Datei bekommen.")
            raise SparkNichtErreichbar(MELDUNG_WEG)
        modell = settings.SPARK_TTS_MODEL
    messung = {
        "modell": modell, "stimme": stimme, "sprache": sprache_name,
        "zeichen": len(text), "bytes": len(daten),
        "dauer_ms": int((time.monotonic() - begonnen) * 1000),
        "zwischenspeicher": False,
    }
    with _SCHLOSS:
        _ZWISCHENSPEICHER[schluessel] = (daten, messung)
        while len(_ZWISCHENSPEICHER) > _ZWISCHENSPEICHER_GROESSE:
            _ZWISCHENSPEICHER.popitem(last=False)
    return daten, messung


def zwischenspeicher_leeren():
    with _SCHLOSS:
        _ZWISCHENSPEICHER.clear()


# --- Die Attrappe -------------------------------------------------------------

def attrappe(text):
    """Eine hoerbare Tonfolge in der Laenge des Textes, als WAV.

    Je Wort ein kurzer, leiser Ton, abwechselnd zwei Hoehen, mit einer
    kleinen Pause; eine laengere Pause am Satzende. Das ist absichtlich
    keine Sprache: Niemand soll die Attrappe fuer die Stimme halten. Sie
    zeigt, dass Anfrage, Abspielen und Zeitablauf stimmen, mehr nicht.
    Hoechstens acht Sekunden, so lang ist kein Zug des Coaches.
    """
    woerter = (text or "").split() or ["."]
    proben = array.array("h")
    hoehen = (392.0, 330.0)   # g und e, ein freundliches Intervall
    for i, wort in enumerate(woerter):
        dauer = min(0.16, 0.05 + 0.02 * len(wort))
        _ton(proben, hoehen[i % 2], dauer)
        _stille(proben, 0.28 if wort[-1:] in ".!?…" else 0.05)
        if len(proben) > ABTASTRATE * 8:
            break
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(ABTASTRATE)
        datei.writeframes(proben.tobytes())
    return puffer.getvalue()


def _ton(proben, frequenz, dauer):
    n = int(ABTASTRATE * dauer)
    for k in range(n):
        # Weiche Flanken: ein Ton, der hart anfaengt, knackt im Lautsprecher.
        huelle = min(1.0, k / (ABTASTRATE * 0.01), (n - k) / (ABTASTRATE * 0.02))
        wert = 0.18 * huelle * math.sin(2 * math.pi * frequenz * k / ABTASTRATE)
        proben.append(int(wert * 32767))


def _stille(proben, dauer):
    proben.extend([0] * int(ABTASTRATE * dauer))
