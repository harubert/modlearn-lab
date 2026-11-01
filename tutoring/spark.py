"""Zugriff auf das Sprachmodell am Spark.

Der Spark haengt bis zum Umzug an die PH am WLAN und kann ein bis zwei
Minuten weg sein. Deshalb: Zeitlimit, genau ein Wiederholungsversuch und
eine Meldung, die ein Kind versteht, statt eines Abbruchs.
"""

import json
import logging
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Was das Kind liest, wenn der Spark nicht antwortet. Kein Stacktrace,
# keine Adresse, kein Fehlercode.
MELDUNG_NICHT_ERREICHBAR = (
    "Der Rechner der Schule antwortet gerade nicht. Deine Aufgabe ist nicht "
    "verloren – probier es in einer Minute noch einmal."
)


class SparkNichtErreichbar(Exception):
    """Der Spark war nicht erreichbar oder hat zu lange gebraucht."""

    def __init__(self, meldung=MELDUNG_NICHT_ERREICHBAR):
        super().__init__(meldung)
        self.meldung = meldung


def _nachrichten(system, text, bilder=None):
    """Baut die Nachrichtenliste im OpenAI-Format.

    Bilder gehen als Data-URL mit, hoechstens vier je Anfrage. Verkleinert
    wird im Browser vor dem Senden, nicht hier.
    """
    inhalt = []
    if bilder:
        for data_url in bilder[:4]:
            inhalt.append({"type": "image_url", "image_url": {"url": data_url}})
    inhalt.append({"type": "text", "text": text})
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": inhalt},
    ]


# Die Temperatur der Hilfen. 0,3 ist der Betrieb; Wiederholungen derselben
# Stufe laufen seit dem Benchmark (19.10.2026, Aenderung 6) mit 0,6, damit
# der zweite Anlauf nicht der erste mit anderen Worten ist.
TEMPERATUR = 0.3
TEMPERATUR_WIEDERHOLUNG = 0.6


def _rumpf(system, text, bilder, max_tokens, streamen, temperatur=TEMPERATUR):
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": _nachrichten(system, text, bilder),
        "max_tokens": max_tokens,
        "temperature": temperatur,
        "stream": streamen,
    }
    if streamen:
        # Ohne diese Bitte liefert vLLM im Strom keine Tokenzahlen, und das
        # Forschungsprotokoll haette bei jeder Zeile eine Luecke.
        rumpf["stream_options"] = {"include_usage": True}
    return rumpf


async def hilfe_streamen(system, text, bilder=None, max_tokens=500, messung=None,
                         temperatur=TEMPERATUR):
    """Liefert die Antwort des Modells stueckweise.

    Der Wiederholungsversuch greift nur, solange noch nichts ausgeliefert
    wurde. Ist das erste Stueck beim Kind angekommen, waere ein zweiter
    Anlauf eine doppelte Antwort und keine Rettung.

    In ``messung`` traegt die Funktion Tokenzahlen und Dauer ein, falls ein
    Woerterbuch uebergeben wird. Das Protokoll aus Abschnitt 3b braucht diese
    Angaben je Anfrage. ``temperatur`` ist nur fuer Wiederholungen anders.
    """
    beginn = time.monotonic()
    rumpf = _rumpf(system, text, bilder, max_tokens, streamen=True, temperatur=temperatur)
    versuche = settings.SPARK_RETRIES + 1
    etwas_geliefert = False

    for versuch in range(1, versuche + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
                async with client.stream(
                    "POST", f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
                ) as antwort:
                    antwort.raise_for_status()
                    async for zeile in antwort.aiter_lines():
                        stueck, verbrauch = _aus_zeile(zeile)
                        if verbrauch and messung is not None:
                            messung["tokens_ein"] = verbrauch.get("prompt_tokens", 0)
                            messung["tokens_aus"] = verbrauch.get("completion_tokens", 0)
                        if stueck:
                            etwas_geliefert = True
                            yield stueck
            if messung is not None:
                messung["dauer_ms"] = int((time.monotonic() - beginn) * 1000)
            return
        except (httpx.HTTPError, json.JSONDecodeError) as fehler:
            if etwas_geliefert:
                # Mittendrin abgerissen: lieber ein kurzer Hinweis als eine
                # zweite, widerspruechliche Antwort.
                logger.warning("Spark-Abbruch mitten im Strom: %s", type(fehler).__name__)
                yield "\n\n(Die Verbindung ist abgerissen. Fordere die Hilfe bitte noch einmal an.)"
                return
            if versuch >= versuche:
                logger.warning("Spark nach %s Versuchen nicht erreichbar: %s",
                               versuch, type(fehler).__name__)
                raise SparkNichtErreichbar from fehler
            logger.info("Spark-Versuch %s fehlgeschlagen, neuer Anlauf", versuch)


def _aus_zeile(zeile):
    """Zieht Textzuwachs und Verbrauchsangaben aus einer SSE-Zeile von vLLM.

    Die letzte Zeile vor [DONE] traegt die Tokenzahlen und hat keine Wahlen
    mehr. Beides kommt deshalb aus derselben Auswertung.
    """
    if not zeile or not zeile.startswith("data:"):
        return "", None
    nutzlast = zeile[len("data:"):].strip()
    if not nutzlast or nutzlast == "[DONE]":
        return "", None
    try:
        daten = json.loads(nutzlast)
    except json.JSONDecodeError:
        return "", None
    verbrauch = daten.get("usage")
    wahlen = daten.get("choices") or []
    if not wahlen:
        return "", verbrauch
    return (wahlen[0].get("delta", {}).get("content") or ""), verbrauch


async def antwort_holen(system, text, bilder=None, max_tokens=500):
    """Holt eine vollstaendige Antwort auf einmal.

    Wird fuer die Namenserkennung des Privacy Shield gebraucht, die eine
    JSON-Antwort am Stueck braucht und nichts anzuzeigen hat.
    """
    rumpf = _rumpf(system, text, bilder, max_tokens, streamen=False)
    versuche = settings.SPARK_RETRIES + 1

    for versuch in range(1, versuche + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
                antwort = await client.post(
                    f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
                )
                antwort.raise_for_status()
                daten = antwort.json()
            return daten["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as fehler:
            if versuch >= versuche:
                logger.warning("Spark nach %s Versuchen ohne Antwort: %s",
                               versuch, type(fehler).__name__)
                raise SparkNichtErreichbar from fehler


def antwort_holen_sync(system, text, max_tokens=700, temperatur=TEMPERATUR):
    """Dasselbe wie antwort_holen, aber synchron und mit Messung.

    Der Trainer ist eine synchrone Ansicht: Ein Zug ist eine abgeschlossene
    Sache mit einem Urteil daran, und der Zustandswechsel steht erst fest,
    wenn die ganze Antwort da ist. Stueckweise auszugeben braechte hier
    nichts ausser einem frueheren ersten Zeichen.

    Gibt (text, messung) zurueck. Die Messung ist das, was ins Protokoll
    gehoert: Modell, Token, Dauer.
    """
    rumpf = _rumpf(system, text, None, max_tokens, streamen=False, temperatur=temperatur)
    return _abholen(rumpf)


def gespraech_holen_sync(system, nachrichten, max_tokens=700, temperatur=TEMPERATUR):
    """Wie antwort_holen_sync, aber mit einem ganzen Gespraechsverlauf.

    ``nachrichten`` ist eine Liste im OpenAI-Format, also Woerterbuecher mit
    "role" (user oder assistant) und "content"; die Anweisung kommt davor.
    Der Safe Chat (23.10.2026) braucht das: Dort gibt es keine Aufgabe, auf
    die sich jeder Zug bezieht, sondern nur das Gespraech selbst, und das
    Modell soll es als Gespraech sehen und nicht als Text mit Rollennamen.

    Gibt (text, messung) zurueck, dieselbe Fehlerbehandlung wie
    antwort_holen_sync: SparkNichtErreichbar nach dem letzten Versuch.
    """
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": [{"role": "system", "content": system}, *nachrichten],
        "max_tokens": max_tokens,
        "temperature": temperatur,
        "stream": False,
    }
    return _abholen(rumpf)


def _abholen(rumpf):
    """Ein synchroner Aufruf mit Wiederholung und Messung."""
    versuche = settings.SPARK_RETRIES + 1
    begonnen = time.monotonic()

    for versuch in range(1, versuche + 1):
        try:
            with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
                antwort = client.post(
                    f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
                )
                antwort.raise_for_status()
                daten = antwort.json()
            verbrauch = daten.get("usage") or {}
            messung = {
                "modell": daten.get("model") or settings.SPARK_MODEL,
                "tokens_ein": verbrauch.get("prompt_tokens", 0),
                "tokens_aus": verbrauch.get("completion_tokens", 0),
                "dauer_ms": int((time.monotonic() - begonnen) * 1000),
            }
            return daten["choices"][0]["message"]["content"] or "", messung
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as fehler:
            if versuch >= versuche:
                logger.warning("Spark nach %s Versuchen ohne Antwort: %s",
                               versuch, type(fehler).__name__)
                raise SparkNichtErreichbar from fehler


# --- Texterkennung aus einem Foto ----------------------------------------

ABSCHREIB_PROMPT = (
    "Auf dem Bild steht eine Rechenaufgabe, oft aus einem Schulbuch oder einem "
    "Heft, manchmal mit einem Lösungsversuch von Hand.\n"
    "Schreib ab, was dort steht. Gib ausschließlich den abgeschriebenen Text "
    "zurück, ohne Einleitung, ohne Kommentar und ohne eigene Lösung.\n"
    "Behalte Zahlen, Einheiten, Brüche und Hochzahlen genau so bei, wie sie "
    "dastehen. Behalte auch Rechtschreibfehler bei, korrigiere nichts.\n"
    "Ist eine Stelle nicht lesbar, schreib dafür [unleserlich].\n"
    "Steht auf dem Bild keine Aufgabe, antworte mit genau dem Wort: KEINE_AUFGABE"
)

MELDUNG_BILD_UNKLAR = (
    "Auf dem Foto ist keine Aufgabe zu erkennen. Probier es noch einmal mit "
    "mehr Licht, und halte das Blatt gerade."
)


def text_aus_bild(data_url):
    """Liest den Aufgabentext von einem Foto ab.

    Synchron, weil die Ansicht, die das Foto entgegennimmt, synchron ist.
    Das Bild wird einmal gelesen und danach als Text weiterverarbeitet: Ein
    Foto bei jeder Hilfestufe mitzuschicken kostet je Anfrage rund 1.900
    Token und acht Sekunden, der abgeschriebene Text kostet fast nichts.
    """
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": [
            {"role": "system", "content": ABSCHREIB_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": "Schreib den Text auf dem Bild ab."},
                ],
            },
        ],
        "max_tokens": 600,
        "temperature": 0.0,
    }

    try:
        with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
            antwort = client.post(
                f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
            )
            antwort.raise_for_status()
            daten = antwort.json()
    except (httpx.HTTPError, ValueError) as fehler:
        logger.warning("Texterkennung fehlgeschlagen: %s", type(fehler).__name__)
        raise SparkNichtErreichbar from fehler

    try:
        text = (daten["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError):
        raise SparkNichtErreichbar

    verbrauch = daten.get("usage") or {}
    if text == "KEINE_AUFGABE" or not text:
        return "", verbrauch
    return text, verbrauch


# --- Spracherkennung ------------------------------------------------------

MELDUNG_SPRACHE_AUS = (
    "Sprechen geht gerade nicht. Tipp deine Aufgabe bitte ein oder "
    "fotografiere sie."
)

MELDUNG_NICHTS_VERSTANDEN = (
    "Da war nichts zu hören. Sprich bitte etwas lauter und näher am Gerät."
)


def sprache_moeglich():
    return bool(settings.SPARK_AUDIO_BASE_URL)


def text_aus_sprache(daten, dateiname="aufnahme.wav", sprache="de"):
    """Schickt eine Aufnahme an Whisper am Spark und gibt den Text zurueck."""
    text, _ = text_und_sprache(daten, dateiname, sprache)
    return text


def text_und_sprache(daten, dateiname="aufnahme.wav", sprache="de"):
    """Wie text_aus_sprache, gibt aber auch die erkannte Sprache zurueck.

    Gibt (text, erkannte_sprache) zurueck. Die Sprache ist "", wenn der
    Dienst keine gemeldet hat - daraus darf der Aufrufer nicht schliessen,
    dass es die falsche war. Alles Weitere steht bei transkription().
    """
    ergebnis = transkription(daten, dateiname, sprache)
    return ((ergebnis.get("text") or "").strip(),
            (ergebnis.get("language") or "").strip())


def transkription(daten, dateiname="aufnahme.wav", sprache="de"):
    """Schickt eine Aufnahme an Whisper und gibt die ganze Antwort zurueck.

    Erwartet WAV mit 16 kHz in mono. Der Browser erzeugt das selbst: Am Spark
    fehlt ffmpeg, und was ein Handy von sich aus liefert, waere dort nicht
    lesbar.

    `sprache=None` laesst Whisper die Sprache selbst bestimmen. Genau das
    braucht der Sprechcoach: Er muss wissen, OB ein Kind englisch gesprochen
    hat, und das kann er nicht erfahren, wenn er Whisper vorher sagt, es sei
    Englisch. Mit erzwungener Sprache schreibt Whisper einen deutschen Satz
    als englische Lautmalerei - der Text sieht dann englisch aus und ist
    keiner.

    Fuer alles andere bleibt die Sprache erzwungen, und zwar aus demselben
    Satz von hinten: Ohne "de" schreibt Whisper eine deutsche Textaufgabe als
    englische Lautmalerei, und das ist in der Aufgabenhilfe der Unterschied
    zwischen einer Aufgabe und Unsinn.

    Zurueck kommt das Woerterbuch von verbose_json: "text", "language" und
    "segments" mit no_speech_prob und avg_logprob je Abschnitt. Der
    Sprechcoach liest daraus, ob ueberhaupt gesprochen wurde - Whisper
    erfindet bei Stille ganze Saetze, und die Felder je Abschnitt sind der
    einzige Hinweis darauf. Fehlt etwas, fehlt es; der Aufrufer darf daraus
    nichts schliessen. Die Aufnahme selbst wird nirgends abgelegt.
    """
    if not sprache_moeglich():
        raise SparkNichtErreichbar(MELDUNG_SPRACHE_AUS)

    felder = {
        "model": settings.SPARK_AUDIO_MODEL,
        # verbose_json und nicht json: nur dort steht das Feld "language".
        "response_format": "verbose_json",
    }
    if sprache:
        felder["language"] = sprache

    try:
        with httpx.Client(timeout=settings.SPARK_AUDIO_TIMEOUT_SECONDS) as client:
            antwort = client.post(
                f"{settings.SPARK_AUDIO_BASE_URL}/audio/transcriptions",
                files={"file": (dateiname, daten, "audio/wav")},
                data=felder,
            )
            antwort.raise_for_status()
            ergebnis = antwort.json()
    except (httpx.HTTPError, ValueError) as fehler:
        logger.warning("Spracherkennung fehlgeschlagen: %s", type(fehler).__name__)
        raise SparkNichtErreichbar from fehler

    if not isinstance(ergebnis, dict):
        return {}
    return ergebnis
