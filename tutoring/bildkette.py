"""Die Bildkette: was von einem Foto hinausgehen darf, und wie das geprueft wird.

Bis zum 31.10.2026 galt ohne Ausnahme: Bilder gehen nie in die Cloud. Seit
Thomas' Entscheidung vom 31.10.2026 darf ein Foto den Weg nach draussen
nehmen, wenn zwei Dinge zusammenkommen: Die Lehrperson hat es fuer die
Sitzung freigegeben (LearningSession.cloud_images_enabled, Standard aus, nur
zusammen mit der Qualitaetssicherung), und diese Kette ist ohne Beanstandung
durchgelaufen. Hinaus geht dann nicht das Foto, sondern ein Ausschnitt: die
gedruckte Aufgabe, neu kodiert, ohne Metadaten, ohne Handschrift, ohne
Namen, Gesichter oder Logos.

Die Kette ist fail-closed. Jeder Zweifel, jeder Ausfall am Spark, jeder
Parsefehler sperrt den Bildweg; dann laeuft die Qualitaetssicherung wie
bisher nur mit dem abgeschriebenen Text, und die Lehrperson liest im
Verlauf, warum. Der Loesungsversuch des Kindes geht nie hinaus: nicht als
Bild (er wird maskiert) und nicht als Text (die Qualitaetssicherung schickt
nur die Aufgabe).

Die Schritte:

1. Laden und neu kodieren (Pillow): Exif samt GPS weg, RGB, lange Kante
   hoechstens 1600 px. Die App verkleinert schon im Browser, aber der Server
   verlaesst sich darauf nicht.
2. Verorten (Vision-Modell am Spark, Antwort durch ein JSON-Schema
   erzwungen): gedruckte Aufgabe, Handschrift, Name, Gesicht, Logo, als
   Kaestchen mit Koordinaten von 0 bis 1000.
3. Maskieren und zuschneiden (Pillow): alles Heikle schwarz, danach der
   Zuschnitt auf die Vereinigung der gedruckten Aufgaben. Masken gewinnen
   gegen den Zuschnitt: Liegt Handschrift ueber der Aufgabenzeile, ist die
   Zeile weg, nicht die Maske. Ohne gedruckten Bereich: gesperrt.
4. Pruefen, als zweites Netz mit anderen Maschen: erst die Frage an das
   Vision-Modell, ob auf dem Ausschnitt noch Handschrift, Name, Gesicht oder
   Logo zu sehen ist; dann die OCR des Ausschnitts, deterministisch gegen
   die Abschrift der Aufgabe gehalten: keine erkannte Entitaet (Regel- und
   Namensfunde wie in der Textkette), keine Zahl, die in der Abschrift nicht
   vorkommt, und mindestens eine Zahl der Aufgabe lesbar.
5. Das Ergebnis: der Ausschnitt als Data-URL, die Zaehlung der Masken je
   Typ, die Dauer. Nichts davon ueberlebt die Sitzung.

Gemessen wurde die Kette zuerst mit synthetischen Bildern
(benchmark/bildkette/). Was sie nicht kann, steht auf der Seite fuer
Lehrpersonen (core:bildpruefung): Sie erkennt, was ein Modell erkennt, und
sie sperrt im Zweifel.
"""

import base64
import binascii
import io
import json
import logging
import time
from dataclasses import dataclass, field

import httpx
from django.conf import settings
from PIL import Image, ImageDraw, ImageOps

from . import shield

logger = logging.getLogger(__name__)

# Dieselbe lange Kante wie im Browser (static/js/foto.js): mehr Pixel
# bringen dem Vision-Modell nichts und kosten Token.
LANGE_KANTE = 1600
GUETE = 85
# Luft um die gedruckte Aufgabe, und wie weit eine Maske ueber ihr Kaestchen
# hinausreicht. Die Kaestchen des Modells sitzen eng, ein Unterlaengen-Rand
# soll nicht stehen bleiben.
RAND = 12
MASKENRAND = 6

GEDRUCKT = "gedruckte_aufgabe"
HANDSCHRIFT = "handschrift"
NAME = "name"
GESICHT = "gesicht"
LOGO = "logo"
HEIKEL = (HANDSCHRIFT, NAME, GESICHT, LOGO)
LABELS = (GEDRUCKT,) + HEIKEL
BEZEICHNUNG = {
    HANDSCHRIFT: "Handschrift",
    NAME: "Name",
    GESICHT: "Gesicht",
    LOGO: "Logo oder Schulname",
}

# Die Arten, mit denen BildGesperrt den Grund benennt. Im Verlauf und im
# Protokoll steht die Art, nicht nur der Satz, damit sich zaehlen laesst,
# woran der Bildweg scheitert.
ART_UNLESBAR = "bild_unlesbar"
ART_SHIELD_AUS = "bild_shield_aus"
ART_VERORTUNG = "bild_verortung"
ART_KEIN_DRUCK = "bild_kein_druck"
ART_LEAK = "bild_leak"
ART_FREMDE_ZAHLEN = "bild_fremde_zahlen"
ART_UNBRAUCHBAR = "bild_unbrauchbar"

BESTANDEN = "bestanden"
BLOCKIERT = "blockiert"


class BildGesperrt(Exception):
    """Der Bildweg ist zu, aus einem benannten Grund.

    ``woerter`` nennt bei einem Leck ueber die OCR die erkannten Werte, die
    im Ausschnitt noch lesbar waren; bereinigen() versucht damit genau
    einmal, sie nachzumaskieren.
    """

    def __init__(self, grund, art="gesperrt", woerter=()):
        super().__init__(grund)
        self.grund = grund
        self.art = art
        self.woerter = tuple(woerter)


@dataclass
class Bereich:
    """Ein Kaestchen auf dem Bild, in Pixeln des geladenen Bildes."""

    label: str
    box: tuple  # (x1, y1, x2, y2)


@dataclass
class Bildbefund:
    """Was die Kette liefert, wenn sie durchgelaufen ist."""

    data_url: str
    masken: dict
    ocr: str
    dauer_ms: int
    breite: int
    hoehe: int
    bereiche: list = field(default_factory=list)
    tokens_ein: int = 0
    tokens_aus: int = 0


# --- Die Fragen an das Vision-Modell ----------------------------------------

VERORTEN_SYSTEM = (
    "Du siehst das Foto einer Heft- oder Buchseite aus dem Mathematikunterricht. "
    "Finde darauf Bereiche und gib sie als JSON zurück, in der Form "
    '{"bereiche": [{"label": "...", "bbox_2d": [x1, y1, x2, y2]}]}. '
    "Die Koordinaten sind auf 0 bis 1000 normiert, bezogen auf Breite und Höhe "
    "des Bildes.\n"
    "Labels:\n"
    "gedruckte_aufgabe: gedruckter Aufgabentext samt gedruckten Abbildungen, "
    "ein Bereich je Aufgabe.\n"
    "handschrift: alles, was von Hand geschrieben oder gezeichnet ist.\n"
    "name: ein Personenname, gedruckt oder geschrieben.\n"
    "gesicht: ein Gesicht, als Foto oder als Zeichnung.\n"
    "logo: ein Logo, ein Wappen oder ein Schulname.\n"
    "Nimm nur Bereiche auf, die wirklich zu sehen sind. Eine Art, die fehlt, "
    "lässt du weg; die leere Liste ist erlaubt. Ein Bereich, der das ganze "
    "Bild umfasst, ist nur richtig, wenn das Bild tatsächlich nur daraus besteht."
)
VERORTEN_FRAGE = "Verorte die Bereiche auf diesem Bild."
VERORTEN_SCHEMA = {
    "name": "bereiche",
    "schema": {
        "type": "object",
        "properties": {
            "bereiche": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": list(LABELS)},
                        "bbox_2d": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                    "required": ["label", "bbox_2d"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["bereiche"],
        "additionalProperties": False,
    },
}

PRUEFEN_FRAGE = (
    "Prüfe dieses Bild streng. Ist darauf Handschrift, ein Personenname, ein "
    "Gesicht oder ein Logo beziehungsweise Schulname zu sehen? Schwarze Flächen "
    "sind Maskierungen und zählen nicht. Antworte nur als JSON mit den vier "
    "Schlüsseln handschrift, name, gesicht, logo, jeweils true oder false."
)
PRUEFEN_SCHEMA = {
    "name": "pruefung",
    "schema": {
        "type": "object",
        "properties": {label: {"type": "boolean"} for label in HEIKEL},
        "required": list(HEIKEL),
        "additionalProperties": False,
    },
}

OCR_FRAGE = (
    "Schreib den gesamten lesbaren Text auf diesem Bild wortgetreu ab. Nur den "
    "Text, ohne Einleitung und ohne Kommentar. Ist nichts lesbar, antworte mit "
    "genau dem Wort: NICHTS"
)

# Ein gedruckter Name in der Aufgabe (Lisa kauft vier Packungen) ist fuer die
# Namenserkennung eine Person, und die Textkette ersetzt ihn durch einen
# Platzhalter. Im Bild wird er nachmaskiert: Das Modell zeigt, wo das Wort
# steht, die Stelle wird schwarz, und die ganze Pruefung laeuft noch einmal.
NACHMASKIEREN_FRAGE = (
    "Auf diesem Bild kommen diese Wörter vor: {woerter}. Gib für JEDES Vorkommen "
    "jedes dieser Wörter ein Kästchen an, Koordinaten 0 bis 1000 bezogen auf "
    "Breite und Höhe, in der Form "
    '{{"treffer": [{{"wort": "...", "bbox_2d": [x1, y1, x2, y2]}}]}}. '
    "Kommt ein Wort nicht vor, lass es weg."
)
NACHMASKIEREN_SCHEMA = {
    "name": "treffer",
    "schema": {
        "type": "object",
        "properties": {
            "treffer": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "wort": {"type": "string"},
                        "bbox_2d": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                    "required": ["wort", "bbox_2d"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["treffer"],
        "additionalProperties": False,
    },
}


# --- Die Kette ---------------------------------------------------------------

def bereinigen(data_url, abschrift):
    """Macht aus dem Foto den Ausschnitt, der hinausgehen darf.

    ``abschrift`` ist der Text, den der Spark vom Foto abgelesen hat
    (Task.text). Gegen ihn wird der Ausschnitt am Ende gehalten.

    Gibt einen Bildbefund zurueck. Bei jedem Grund, der den Bildweg sperrt,
    fliegt BildGesperrt; alles andere, was am Spark oder beim Lesen
    schiefgeht, wird zu BildGesperrt mit der Art bild_shield_aus. Eine
    Bildpruefung, die nicht gelaufen ist, ist keine Bildpruefung.
    """
    begonnen = time.monotonic()
    zaehler = {"ein": 0, "aus": 0}
    bild = laden(data_url)
    try:
        bereiche = _verorten(bild, zaehler)
        ausschnitt, masken = zuschneiden(bild, bereiche)
        funde = _funde(abschrift)
        try:
            ocr = _pruefen(ausschnitt, abschrift, funde, zaehler)
        except BildGesperrt as fehler:
            if fehler.art != ART_LEAK or not fehler.woerter:
                raise
            # Genau ein Versuch, nicht eine Schleife: Was danach noch lesbar
            # ist, sperrt den Weg.
            ausschnitt, nachgezogen = _nachmaskieren(ausschnitt, fehler.woerter, zaehler)
            masken[NAME] += nachgezogen
            ocr = _pruefen(ausschnitt, abschrift, funde, zaehler)
    except BildGesperrt:
        raise
    except Exception as fehler:  # noqa: BLE001 - jeder Ausfall sperrt gleich
        logger.warning("Bildprüfung nicht gelaufen: %s", type(fehler).__name__)
        raise BildGesperrt(
            "Die Bildprüfung am Spark ist nicht gelaufen.", art=ART_SHIELD_AUS
        ) from fehler

    return Bildbefund(
        data_url=als_data_url(ausschnitt),
        masken=masken,
        ocr=ocr,
        dauer_ms=int((time.monotonic() - begonnen) * 1000),
        breite=ausschnitt.width,
        hoehe=ausschnitt.height,
        bereiche=bereiche,
        tokens_ein=zaehler["ein"],
        tokens_aus=zaehler["aus"],
    )


def laden(data_url):
    """Schritt 1: dekodieren, ausrichten, verkleinern, von Metadaten trennen.

    Die Ausrichtung aus dem Exif wird angewandt, BEVOR es weggeworfen wird;
    sonst stimmen die Kaestchen des Modells nicht mit den Pixeln ueberein.
    Das Ergebnis ist ein frisches Bild ohne info-Woerterbuch: Pillow wuerde
    beim Speichern ein Exif aus bild.info sonst stillschweigend mitnehmen.
    """
    kopf, _, rumpf = (data_url or "").partition(",")
    if not kopf.startswith("data:image/") or ";base64" not in kopf or not rumpf:
        raise BildGesperrt("Das Foto ließ sich nicht lesen.", art=ART_UNLESBAR)
    try:
        roh = base64.b64decode(rumpf, validate=True)
        bild = Image.open(io.BytesIO(roh))
        bild.load()
        bild = ImageOps.exif_transpose(bild)
    except (binascii.Error, ValueError, OSError, Image.DecompressionBombError) as fehler:
        raise BildGesperrt("Das Foto ließ sich nicht lesen.", art=ART_UNLESBAR) from fehler

    bild = bild.convert("RGB")
    bild.thumbnail((LANGE_KANTE, LANGE_KANTE))
    sauber = Image.new("RGB", bild.size)
    sauber.paste(bild)
    return sauber


def als_data_url(bild):
    """Neu kodiertes JPEG ohne Metadaten, als Data-URL."""
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=GUETE)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode("ascii")


def _verorten(bild, zaehler):
    """Schritt 2: Das Vision-Modell benennt die Bereiche."""
    inhalt = _spark(
        [{"role": "system", "content": VERORTEN_SYSTEM},
         _nutzer(bild, VERORTEN_FRAGE)],
        max_tokens=700, schema=VERORTEN_SCHEMA, zaehler=zaehler,
    )
    try:
        eintraege = json.loads(inhalt)["bereiche"]
    except (ValueError, KeyError, TypeError) as fehler:
        raise BildGesperrt(
            "Die Bildprüfung hat keine brauchbare Verortung geliefert.",
            art=ART_VERORTUNG,
        ) from fehler
    return bereiche_aus(eintraege, bild.width, bild.height)


def bereiche_aus(eintraege, breite, hoehe):
    """Die Kaestchen des Modells (0 bis 1000) in Pixel des Bildes.

    Unbrauchbare Eintraege werden uebergangen, nicht geraten: ein Label, das
    es nicht gibt, ein Kaestchen ohne Flaeche.
    """
    bereiche = []
    if not isinstance(eintraege, list):
        return bereiche
    for eintrag in eintraege:
        if not isinstance(eintrag, dict):
            continue
        label = eintrag.get("label")
        box = eintrag.get("bbox_2d")
        if label not in LABELS or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = (max(0, min(1000, int(wert))) for wert in box)
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        bereiche.append(Bereich(label, (
            x1 * breite / 1000, y1 * hoehe / 1000,
            x2 * breite / 1000, y2 * hoehe / 1000,
        )))
    return bereiche


def zuschneiden(bild, bereiche):
    """Schritt 3: maskieren, dann zuschneiden. Gibt (Ausschnitt, Masken) zurueck.

    Die Masken werden auf das ganze Bild gelegt, bevor geschnitten wird.
    Dadurch gewinnt die Maske, wo sie die gedruckte Aufgabe ueberlappt: Ein
    Stueck fehlende Aufgabe wird spaeter als unbrauchbar erkannt, ein Stueck
    Handschrift draussen wuerde niemand mehr zurueckholen.
    """
    masken = {label: 0 for label in HEIKEL}
    arbeit = bild.copy()
    zeichner = ImageDraw.Draw(arbeit)
    for bereich in bereiche:
        if bereich.label in HEIKEL:
            x1, y1, x2, y2 = bereich.box
            zeichner.rectangle(
                [max(0, x1 - MASKENRAND), max(0, y1 - MASKENRAND),
                 min(bild.width, x2 + MASKENRAND), min(bild.height, y2 + MASKENRAND)],
                fill=(0, 0, 0),
            )
            masken[bereich.label] += 1

    gedruckt = [bereich.box for bereich in bereiche if bereich.label == GEDRUCKT]
    if not gedruckt:
        raise BildGesperrt(
            "Auf dem Foto ist kein gedruckter Aufgabenbereich zu finden.",
            art=ART_KEIN_DRUCK,
        )
    x1 = max(0, min(box[0] for box in gedruckt) - RAND)
    y1 = max(0, min(box[1] for box in gedruckt) - RAND)
    x2 = min(bild.width, max(box[2] for box in gedruckt) + RAND)
    y2 = min(bild.height, max(box[3] for box in gedruckt) + RAND)
    return arbeit.crop((int(x1), int(y1), int(x2), int(y2))), masken


def _nachmaskieren(ausschnitt, woerter, zaehler):
    """Schwaerzt jedes Vorkommen der Woerter, die die OCR noch lesen konnte.

    Gibt (neuer Ausschnitt, Anzahl der Masken) zurueck. Findet das Modell
    kein Vorkommen, obwohl die OCR eines gelesen hat, ist der Weg zu: Die
    beiden widersprechen sich, und im Zweifel bleibt das Bild im Haus.
    """
    inhalt = _spark(
        [_nutzer(ausschnitt, NACHMASKIEREN_FRAGE.format(
            woerter=", ".join(f"„{wort}“" for wort in woerter)))],
        max_tokens=300, schema=NACHMASKIEREN_SCHEMA, zaehler=zaehler,
    )
    try:
        treffer = json.loads(inhalt)["treffer"]
    except (ValueError, KeyError, TypeError) as fehler:
        raise BildGesperrt(
            "Die Bildprüfung hat keine brauchbare Verortung geliefert.",
            art=ART_VERORTUNG,
        ) from fehler
    bereiche = bereiche_aus(
        [{"label": NAME, "bbox_2d": eintrag.get("bbox_2d")}
         for eintrag in treffer if isinstance(eintrag, dict)],
        ausschnitt.width, ausschnitt.height,
    )
    if not bereiche:
        raise BildGesperrt(
            "Im Ausschnitt steht noch etwas Erkanntes, und es ließ sich nicht maskieren.",
            art=ART_LEAK,
        )
    neu = ausschnitt.copy()
    zeichner = ImageDraw.Draw(neu)
    for bereich in bereiche:
        x1, y1, x2, y2 = bereich.box
        zeichner.rectangle(
            [max(0, x1 - MASKENRAND), max(0, y1 - MASKENRAND),
             min(neu.width, x2 + MASKENRAND), min(neu.height, y2 + MASKENRAND)],
            fill=(0, 0, 0),
        )
    return neu, len(bereiche)


def _pruefen(ausschnitt, abschrift, funde, zaehler):
    """Schritt 4: zweites Netz. Gibt die OCR des Ausschnitts zurueck."""
    # Die Frage an das Modell: Was sieht es auf dem, was hinausginge?
    inhalt = _spark(
        [_nutzer(ausschnitt, PRUEFEN_FRAGE)],
        max_tokens=120, schema=PRUEFEN_SCHEMA, zaehler=zaehler,
    )
    try:
        urteil = json.loads(inhalt)
    except ValueError as fehler:
        raise BildGesperrt(
            "Die Bildprüfung hat kein brauchbares Urteil geliefert.", art=ART_VERORTUNG
        ) from fehler
    gefunden = [BEZEICHNUNG[label] for label in HEIKEL if urteil.get(label) is not False]

    # Deterministisch: die OCR des Ausschnitts gegen die Abschrift.
    ocr = _spark([_nutzer(ausschnitt, OCR_FRAGE)], max_tokens=400, zaehler=zaehler)
    if ocr == "NICHTS":
        ocr = ""
    befund = pruefen_text(ocr, abschrift, funde=funde)

    # Reihenfolge der Spruchkoerper: Ein lesbarer, erkannter Name geht vor,
    # denn nur er laesst sich nachmaskieren (bereinigen). Dann das Urteil
    # des Modells, dann die uebrigen Textregeln. Durch kommt nur, was alle
    # drei nicht beanstanden.
    if befund is not None and befund.woerter:
        raise befund
    if gefunden:
        raise BildGesperrt(
            "Die Bildprüfung hat angeschlagen: " + ", ".join(gefunden) + ".",
            art=ART_LEAK,
        )
    if befund is not None:
        raise befund
    return ocr


def _funde(abschrift):
    """Regel- und Namensfunde der Abschrift, wie in der Textkette.

    Faellt die Namenserkennung aus, fliegt die Ausnahme weiter und
    bereinigen() macht daraus bild_shield_aus: Eine Pruefung ohne
    Namensliste ist keine Pruefung.
    """
    return shield.regelfunde(abschrift) + shield.namensfunde(abschrift)


def pruefen_text(ocr, abschrift, funde=()):
    """Die deterministischen Regeln auf der OCR. Gibt BildGesperrt oder None.

    Eigenstaendig, damit die Messung sie ohne Spark pruefen kann.
    """
    flach = " ".join((ocr or "").split()).lower()
    lesbar = []
    typen = []
    for typ, wert in funde:
        gesucht = " ".join(str(wert).split()).lower()
        if len(gesucht) >= 2 and gesucht in flach:
            lesbar.append(str(wert))
            if shield.BEZEICHNUNG.get(typ, typ) not in typen:
                typen.append(shield.BEZEICHNUNG.get(typ, typ))
    if lesbar:
        return BildGesperrt(
            "Im Ausschnitt steht noch etwas Erkanntes: " + ", ".join(typen) + ".",
            art=ART_LEAK, woerter=lesbar,
        )

    erlaubt = set(shield.zahlenfolge(abschrift))
    zahlen = shield.zahlenfolge(ocr)
    fremde = [zahl for zahl in zahlen if zahl not in erlaubt]
    if fremde:
        return BildGesperrt(
            "Im Ausschnitt stehen Zahlen, die nicht zur abgeschriebenen Aufgabe gehören.",
            art=ART_FREMDE_ZAHLEN,
        )
    if erlaubt and not (set(zahlen) & erlaubt):
        return BildGesperrt(
            "Der Ausschnitt zeigt die Aufgabe nicht mehr lesbar.", art=ART_UNBRAUCHBAR
        )
    return None


# --- Der Spark ---------------------------------------------------------------

def _nutzer(bild, frage):
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": als_data_url(bild)}},
            {"type": "text", "text": frage},
        ],
    }


def _spark(nachrichten, max_tokens, schema=None, zaehler=None):
    """Ein Aufruf an das Vision-Modell. Gibt den Text der Antwort zurueck.

    Mit ``schema`` wird die Antwort als JSON erzwungen (vLLM, response_format
    json_schema). Ohne Zwang kamen in der Probe Klammern abhanden, und ein
    Parsefehler ist kein Grund zu raten.
    """
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": nachrichten,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    if schema:
        rumpf["response_format"] = {"type": "json_schema", "json_schema": schema}
    with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
        antwort = client.post(f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf)
        antwort.raise_for_status()
        daten = antwort.json()
    inhalt = (daten["choices"][0]["message"]["content"] or "").strip()
    if zaehler is not None:
        nutzung = daten.get("usage") or {}
        zaehler["ein"] += int(nutzung.get("prompt_tokens") or 0)
        zaehler["aus"] += int(nutzung.get("completion_tokens") or 0)
    return inhalt


def masken_text(masken):
    """Die Masken als lesbare Aufzaehlung, etwa '1× Handschrift, 1× Name'.

    In der Reihenfolge von HEIKEL, nicht in der des Woerterbuchs: PostgreSQL
    legt JSON-Felder als JSONB ab und ordnet die Schluessel dabei um (erst
    nach Laenge, dann alphabetisch). Beim Ausrollen am 31.10.2026 sind zwei
    Tests daran gescheitert, die am SQLite der Entwicklung durchliefen.
    """
    masken = masken or {}
    reihenfolge = list(HEIKEL) + sorted(label for label in masken if label not in HEIKEL)
    teile = [
        f"{masken[label]}× {BEZEICHNUNG.get(label, label)}"
        for label in reihenfolge if masken.get(label)
    ]
    return ", ".join(teile)
