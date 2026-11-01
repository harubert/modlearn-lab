"""Wie lange ein Lied braucht: Erfahrungswerte fuer den Fortschrittsbalken.

Thomas (20.10.2026): Bei der Musikerzeugung ist ein Fortschrittsbalken
besser als "noch etwa so und so viele Sekunden", und der Balken soll sich an
Erfahrungs- oder Auslastungswerten orientieren. Der Balken selbst laeuft im
Browser (musik_oeffentlich.js); was er braucht, ist eine Zahl: wie lange das
eigene Lied voraussichtlich rechnet. Die kommt von hier.

ZWEI QUELLEN, EINE ZAHL

1. Erfahrungswerte, gemessen am 20.10.2026 mit zwanzig Liedern auf einmal
   (Fassung klein, 60 Sekunden): Grundlast je Auftrag plus Rechenzeit je
   Musikminute. Die Zahlen stehen in ERFAHRUNG und sind der Anfang.
2. Auslastung: Jedes fertige Lied meldet der Dienst mit `dauer_s`. Daraus
   wird je Fassung ein gleitender Wert nachgefuehrt (merken), damit der
   Balken merkt, wenn der Spark gerade langsamer ist - etwa weil das
   Sprachmodell daneben rechnet. Der Wert lebt im Cache; nach einem Neustart
   gilt wieder die Erfahrung. Das genuegt: Es geht um die Form des Balkens,
   nicht um eine Zusage.

Die Wartezeit bis zum eigenen Lied kennt der Dienst besser als wir
(`wartet_noch_s`, er sieht die Schlange und die Dauern darin); sie wird nur
durchgereicht. Nur wenn sie fehlt, rechnet das Skript Platz mal typischer
Dauer, und dafuer liefert `erwartung` denselben Wert.
"""

from django.core.cache import cache

# Gemessen am 20.10.2026 (benchmark/musik_lasttest_2026-10-20.json: zwanzig
# Lieder zu 60 s, Fassung klein, gleichzeitig abgeschickt, Spark im Profil
# qwen mit geladenem Sprachmodell): ein Lied rechnet 10,1 s, alle zwanzig
# waren nach 139,7 s fertig. Acht der zwanzig kamen in 2,1 s - gleicher Text
# und gleiche Tags treffen den Zwischenspeicher von ComfyUI; in einer Klasse
# mit zwanzig verschiedenen Texten gilt die volle Zeit, also etwa 200 s.
# Der Dienst selbst schaetzt die Schlange mit 9 s je Lied (wartet_noch_s),
# das passt zu 10,1 s abzueglich Grundlast. "xl" nach Angabe des Dienstes
# (/grenzen, sekunden_je_minute 20), nicht selbst gemessen.
ERFAHRUNG = {
    "klein": {"grund_s": 1.5, "je_minute_s": 8.6},
    "xl": {"grund_s": 1.5, "je_minute_s": 20.0},
}
FASSUNG_VORGABE = "klein"

# Wie stark ein neues fertiges Lied den gleitenden Wert bewegt. 0,3 heisst:
# nach drei Liedern ist eine Verlangsamung zu zwei Dritteln angekommen.
GEWICHT = 0.3
SCHLUESSEL = "musik_zeit:{fassung}"
FRIST_S = 6 * 60 * 60


def _erfahrung(fassung):
    return ERFAHRUNG.get(fassung or FASSUNG_VORGABE) or ERFAHRUNG[FASSUNG_VORGABE]


def je_minute(fassung):
    """Die aktuelle Rechenzeit je Musikminute: nachgefuehrt oder Erfahrung."""
    wert = cache.get(SCHLUESSEL.format(fassung=fassung or FASSUNG_VORGABE))
    if isinstance(wert, (int, float)) and wert > 0:
        return float(wert)
    return _erfahrung(fassung)["je_minute_s"]


def erwartung(sekunden, fassung=FASSUNG_VORGABE):
    """Wie lange das Rechnen eines Liedes dieser Laenge voraussichtlich dauert."""
    try:
        sekunden = float(sekunden)
    except (TypeError, ValueError):
        sekunden = 60.0
    if sekunden <= 0:
        sekunden = 60.0
    grund = _erfahrung(fassung)["grund_s"]
    return round(grund + je_minute(fassung) * sekunden / 60.0, 1)


def merken(dauer_s, sekunden, fassung=FASSUNG_VORGABE):
    """Ein fertiges Lied: den gleitenden Wert je Minute nachfuehren.

    Wirft nie und ignoriert Unsinn (fehlende oder negative Werte, Lieder
    unter zehn Sekunden): Ein kaputter Messwert darf den Balken nicht
    fuer alle anderen verbiegen.
    """
    try:
        dauer_s = float(dauer_s)
        sekunden = float(sekunden)
    except (TypeError, ValueError):
        return None
    if dauer_s <= 0 or sekunden < 10:
        return None
    grund = _erfahrung(fassung)["grund_s"]
    gemessen = max(dauer_s - grund, 0.5) * 60.0 / sekunden
    bisher = je_minute(fassung)
    neu = round(bisher + GEWICHT * (gemessen - bisher), 2)
    cache.set(SCHLUESSEL.format(fassung=fassung or FASSUNG_VORGABE), neu, FRIST_S)
    return neu


def vergessen(fassung=None):
    """Fuer Tests: die nachgefuehrten Werte loeschen."""
    for name in ([fassung] if fassung else list(ERFAHRUNG)):
        cache.delete(SCHLUESSEL.format(fassung=name))
