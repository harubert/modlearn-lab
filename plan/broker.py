"""Der Modell-Broker am Spark: welches Profil laeuft, und Umschalten.

Der Broker ist ein kleiner Dienst am Spark (Port 8010, nur im Tailnet), den
die Spark-Betreuung am 11.10.2026 aufgesetzt hat. Er ist die EINE Stelle, die
weiss, was im Speicher liegt. Vorher stand das in einer Umgebungsvariablen -
also in einer Behauptung, die niemand nachprueft.

Was dieser Baustein zusagt, und was nicht:

- status() liefert die letzte Auskunft des Brokers, hoechstens STATUS_FRIST
  Sekunden alt, oder None. None heisst: nicht erreichbar, kein Geheimnis, oder
  Unsinn geantwortet. Der Aufrufer faellt dann auf die Umgebung zurueck.
- Nichts hier wirft nach aussen. Eine Buchungsseite, die nicht laedt, weil der
  Spark gerade neu startet, waere schlimmer als eine, die mit dem letzten
  bekannten Stand rechnet.
- Das Geheimnis wird aus einer Datei gelesen, nie aus der Umgebung, nie
  geloggt, einmal je Prozess. Fehlt die Datei, gibt es keinen Broker - und
  zwar still: Der Knopf "Rechner umschalten" ist dann einfach nicht da.
"""

import json
import logging
import threading
import time
from pathlib import Path

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Wie lange eine Statusauskunft gilt. Zehn Sekunden: Ein Profilwechsel dauert
# ein bis vier Minuten, und die Buchungsseite fragt bei jedem Aufruf.
STATUS_FRIST = 10

# Die Dienste, die der Broker nennt, tragen dieselben Schluessel wie die
# Konzepte: text, gehoer, stimme, einbettung, schulung. Abgestimmt mit der
# Spark-Betreuung am 11.10.2026 - die App vergleicht Zeichenketten.

_sperre = threading.Lock()
_geheimnis = None
_geheimnis_gelesen = False
_status = {"zeit": 0.0, "wert": None}


class BrokerNichtErreichbar(Exception):
    pass


def geheimnis():
    """Das gemeinsame Geheimnis, oder None.

    Einmal je Prozess gelesen. Eine fehlende Datei wird NICHT gemerkt: Legt
    Thomas sie nachtraeglich ab, greift sie beim naechsten Aufruf ohne
    Neustart. Ein gelesener Wert bleibt bis zum Neustart.
    """
    global _geheimnis, _geheimnis_gelesen
    if _geheimnis_gelesen:
        return _geheimnis
    pfad = Path(settings.SPARK_BROKER_SECRET_DATEI)
    try:
        wert = pfad.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not wert:
        return None
    with _sperre:
        _geheimnis = wert
        _geheimnis_gelesen = True
    logger.info("Modell-Broker: Geheimnis aus %s gelesen.", pfad)
    return _geheimnis


def moeglich():
    """Gibt es einen Broker, mit dem sich reden laesst?"""
    return bool(settings.SPARK_BROKER_URL and geheimnis())


def _holen(pfad, methode="GET", daten=None, frist=8.0):
    if not moeglich():
        raise BrokerNichtErreichbar("kein Broker eingerichtet")
    adresse = settings.SPARK_BROKER_URL.rstrip("/") + pfad
    try:
        with httpx.Client(timeout=frist) as client:
            antwort = client.request(
                methode, adresse,
                headers={"X-Broker-Secret": geheimnis()},
                json=daten,
            )
        inhalt = antwort.json() if antwort.content else {}
    except (httpx.HTTPError, ValueError) as fehler:
        logger.warning("Modell-Broker: %s nicht erreichbar (%s).",
                       pfad, type(fehler).__name__)
        raise BrokerNichtErreichbar(pfad) from fehler
    if not isinstance(inhalt, dict):
        raise BrokerNichtErreichbar(pfad)
    return antwort.status_code, inhalt


def status(frisch=False):
    """Die Auskunft des Brokers, oder None.

    Zwischengespeichert fuer STATUS_FRIST Sekunden. `frisch=True` erzwingt
    eine neue Abfrage - beim Warten auf "bereit" nach einem Wechsel.
    """
    jetzt = time.monotonic()
    if not frisch and _status["wert"] is not None \
            and jetzt - _status["zeit"] < STATUS_FRIST:
        return _status["wert"]
    try:
        code, inhalt = _holen("/status")
    except BrokerNichtErreichbar:
        return _status["wert"] if _status["wert"] is not None else None
    if code != 200 or "profil" not in inhalt:
        return None
    with _sperre:
        _status["zeit"] = jetzt
        _status["wert"] = inhalt
    return inhalt


def aktuelles_profil():
    """Das geladene Profil - vom Broker, sonst aus der Umgebung.

    Die Umgebung ist die Rueckfallebene, nicht die Wahrheit: SPARK_PROFIL
    sagt, womit die App rechnen soll, solange niemand nachsehen kann.
    """
    auskunft = status()
    if auskunft and auskunft.get("zustand") in ("bereit", "wechselt"):
        return auskunft.get("profil") or settings.SPARK_PROFIL
    return settings.SPARK_PROFIL


def geladene_dienste():
    """Welche Dienste gerade antworten - vom Broker, sonst aus der Umgebung."""
    auskunft = status()
    if auskunft and isinstance(auskunft.get("dienste"), list):
        return frozenset(
            d.get("name") for d in auskunft["dienste"]
            if isinstance(d, dict) and d.get("bereit") and d.get("name")
        )
    return frozenset(
        teil.strip() for teil in settings.SPARK_GELADENE_MODELLE.split(",")
        if teil.strip()
    )


def profile():
    """Die Profiltabelle des Brokers: Liste von Dicts, oder leer."""
    try:
        code, inhalt = _holen("/modelle")
    except BrokerNichtErreichbar:
        return []
    if code != 200:
        return []
    liste = inhalt.get("profile")
    return liste if isinstance(liste, list) else []


def aktivieren(profil, bis, erzwingen=False):
    """Ein Profil anfordern.

    Gibt (angenommen, antwort) zurueck. 202 und 200 sind angenommen; 409 ist
    der Fall, den die Lehrperson sehen soll - mit dem Satz des Brokers, was
    gerade noch laeuft und was ein Wechsel abschalten wuerde. Erst nach ihrer
    Bestaetigung kommt derselbe Aufruf mit erzwingen=True.
    """
    daten = {"profil": profil, "bis": bis, "erzwingen": bool(erzwingen)}
    try:
        code, inhalt = _holen("/aktivieren", "POST", daten, frist=15.0)
    except BrokerNichtErreichbar:
        return False, {"grund": "Der Modell-Broker am Spark antwortet nicht."}
    with _sperre:
        # Nach einem Wechselauftrag ist der alte Status wertlos.
        _status["wert"] = None
    if code in (200, 202):
        return True, inhalt
    return False, inhalt if inhalt else {"grund": f"Broker antwortet {code}."}


def vergessen():
    """Nur fuer Tests: Zwischenspeicher und Geheimnis zuruecksetzen."""
    global _geheimnis, _geheimnis_gelesen
    with _sperre:
        _geheimnis = None
        _geheimnis_gelesen = False
        _status["zeit"] = 0.0
        _status["wert"] = None
