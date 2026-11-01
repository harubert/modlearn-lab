"""Privacy Shield: Maskierung vor dem Weg nach draussen.

Nach Abschnitt 3a, Vorlage ist Thomas' eigene Veroeffentlichung
private_ai_bridge. Uebernommen ist das Konzept, nicht der Code: Dort ist ein
lokales Gemma der Waechter vor Claude Code auf einem Einzelrechner, hier ist
der Spark die lokale Zone und diese Anwendung ruft ihn auf.

Die Kette:
1. Regelbasierte Erkennung, deterministisch, ohne KI.
2. Namenserkennung durch den Spark.
3. Ersetzung durch Tokens im Format der Vorlage.
4. Leak-Check als eigener Schritt. Ohne bestandenen Check kein Cloud-Aufruf.

Die Zuordnungstabelle Klartext zu Token lebt nur in der Sitzung und stirbt
mit ihr. Bliebe sie, waere die Pseudonymisierung umkehrbar und die ganze
Konstruktion wertlos.
"""

import hashlib
import json
import logging
import re

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# --- Klassifizierung L1 bis L4 aus publish/flow.html der Vorlage ----------
#
# Wichtig und in Abschnitt 3a nicht ausgeschrieben: Die Vorlage behandelt die
# Sozialversicherungsnummer anders als alles andere. Sie ist L1 mit der
# Behandlung "Niemals an Cloud, auch nicht pseudonymisiert", und ihr
# Token-Format ist ein Strich. Eine SVNr wird also nicht maskiert, sie
# blockiert den Aufruf.

TYP_PERSON = "PERS"
TYP_EMAIL = "EMAIL"
TYP_TELEFON = "TEL"
TYP_ADRESSE = "ADDR"
TYP_ORT = "ORT"
TYP_GEBURTSDATUM = "GEB"
TYP_SVNR = "SVNR"
TYP_IBAN = "IBAN"

BEZEICHNUNG = {
    TYP_PERSON: "Name",
    TYP_EMAIL: "E-Mail-Adresse",
    TYP_TELEFON: "Telefonnummer",
    TYP_ADRESSE: "Adresse",
    TYP_ORT: "Postleitzahl und Ort",
    TYP_GEBURTSDATUM: "Geburtsdatum",
    TYP_SVNR: "Sozialversicherungsnummer",
    TYP_IBAN: "Kontonummer",
}

# Typen, die den Aufruf blockieren statt maskiert zu werden.
BLOCKIERENDE_TYPEN = {TYP_SVNR}


# --- Stufe 1: regelbasiert, ohne KI --------------------------------------
#
# Die oesterreichische Sozialversicherungsnummer ist zehnstellig: vier
# Ziffern laufende Nummer samt Pruefziffer, dann sechs Ziffern Geburtsdatum.
_MUSTER = (
    (TYP_EMAIL, re.compile(r"\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b")),
    (TYP_SVNR, re.compile(r"\b\d{4}\s?\d{2}\d{2}\d{2}\b")),
    (TYP_TELEFON, re.compile(
        r"(?:\+43|0043|0)\s?\d{2,4}[\s/-]?\d{3,}[\s/-]?\d{0,}\b"
    )),
    (TYP_GEBURTSDATUM, re.compile(
        r"\b\d{1,2}\.\s?\d{1,2}\.\s?(?:19|20)\d{2}\b"
    )),
    (TYP_ORT, re.compile(r"\b\d{4}\s+[A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+)*")),
    (TYP_ADRESSE, re.compile(
        r"\b[A-ZÄÖÜ][a-zäöüß]+(?:stra(?:ß|ss)e|gasse|weg|platz|allee)\s+\d+[a-zA-Z]?\b"
    )),
)

# IBAN hat ein eigenes Muster, es soll nicht mit der Telefonnummer kollidieren.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\b")


def regelfunde(text):
    """Findet alles, was sich ohne KI sicher erkennen laesst.

    Gibt eine Liste von (typ, zeichenkette) zurueck, laengste Treffer zuerst.
    Die Reihenfolge ist wichtig: Eine Adresse enthaelt oft eine Zahl, die
    fuer sich genommen wie etwas anderes aussieht.
    """
    funde = []
    for typ, muster in _MUSTER:
        for treffer in muster.findall(text or ""):
            wert = treffer.strip()
            if wert:
                funde.append((typ, wert))
    for treffer in _IBAN.findall(text or ""):
        funde.append((TYP_IBAN, treffer.strip()))
    # Laengere Funde zuerst ersetzen, sonst zerschneidet ein kurzer Treffer
    # einen laengeren, in dem er steckt.
    funde.sort(key=lambda paar: len(paar[1]), reverse=True)
    return funde


# --- Stufe 2: Namenserkennung durch den Spark ----------------------------

NAMEN_PROMPT = (
    "Du findest Personennamen in einem deutschen Text. Gib ausschließlich ein "
    "JSON-Array zurück, ohne Einleitung und ohne Kommentar, in dieser Form:\n"
    # Bewusst kein echter Name als Beispiel. Solange hier "Anna Berger"
    # stand, wurde genau dieser Name im Text uebersehen: Das Modell hielt
    # ihn fuer die Schablone. Im Betrieb ist er deshalb an OpenAI gegangen.
    '[{"text": "Vorname Nachname", "typ": "PERS"}]\n'
    "Aufgenommen werden nur echte Personennamen, also Vornamen, Nachnamen oder "
    "beides zusammen. Nicht aufgenommen werden: Ortsnamen, Firmennamen, "
    "Schulfächer, Monatsnamen, Wochentage und gewöhnliche Wörter.\n"
    "Kommt kein Name vor, antworte mit einem leeren Array: []"
)


# Der zweite Prompt. Drei Unterschiede zum ersten, jeder mit einem Grund:
#
# 1. Kein Beispielname, der auch im Text stehen koennte. "Anna Berger" stand
#    oben als Beispiel - und wurde im Text genau deshalb uebersehen: Das
#    Modell hielt den Namen fuer die Schablone.
# 2. Die Haltung kippt von Vorsicht auf Vollstaendigkeit. Ein Fehlalarm
#    kostet ein maskiertes Wort, ein uebersehener Name kostet eine
#    Datenschutzverletzung. Die beiden Fehler sind nicht gleich teuer.
# 3. Anreden ausdruecklich genannt. "Frau Hofer" und "Herrn Gruber" wurden
#    uebersehen, obwohl Lehrpersonennamen meist so dastehen.
NAMEN_PROMPT_WEIT = (
    "Du suchst in einem deutschen Text nach allem, was der Name einer Person "
    "sein könnte.\n"
    "\n"
    "Nimm auf: Vornamen, Nachnamen, beides zusammen, und den Namen nach einer "
    "Anrede wie Herr, Frau, Herrn, Dr. oder Prof. Nimm auch Namen auf, die "
    "nicht deutsch klingen.\n"
    "Nimm NICHT auf: Orte, Länder, Firmen, Marken, Schulfächer, Monate, "
    "Wochentage und gewöhnliche Wörter.\n"
    "\n"
    "IM ZWEIFEL AUFNEHMEN. Ein Wort zu viel zu nennen kostet nichts. Einen "
    "Namen zu übersehen bedeutet, dass er das Haus verlässt.\n"
    "\n"
    "Antworte ausschließlich mit einem JSON-Array, ohne Einleitung, ohne "
    "Kommentar, ohne Codeblock. Jeder Eintrag hat die Form "
    '{"text": "<genau so wie im Text>", "typ": "PERS"}. '
    "Der Wert von \"text\" muss Zeichen für Zeichen im Text vorkommen.\n"
    "Kommt kein Name vor: []"
)

# Eine Anrede, gefolgt von einem grossgeschriebenen Wort. Das ist
# deterministisch und braucht kein Modell: Wer "Frau Hofer" schreibt, meint
# eine Person. Titel duerfen dazwischenstehen.
_ANREDE = re.compile(
    r"\b(?:Herr|Herrn|Frau|Fräulein)\s+"
    r"(?:(?:Dr|Prof|Mag|Dipl)\.?(?:-Ing\.?)?\s+)*"
    r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)"
)


def anredefunde(text):
    """Namen hinter einer Anrede, ohne Modell.

    "Frau Hofer teilt 24 Aepfel auf" wurde vom Modell uebersehen. Diese Regel
    ist eng genug, dass sie kaum falsch anschlaegt, und sie faengt genau den
    Fall, der in der Schule am haeufigsten vorkommt: den Namen einer
    Lehrperson.
    """
    funde = []
    for treffer in _ANREDE.finditer(text or ""):
        wert = treffer.group(1).strip()
        if wert:
            funde.append((TYP_PERSON, wert))
    return funde


def namensfunde(text):
    """Fragt den Spark zweimal nach Personennamen und nimmt beide Antworten.

    Zwei Prompts, die sich an verschiedenen Stellen irren. Gemessen an
    vierzehn Saetzen aus dem Unterricht: einzeln 71 und 79 Prozent,
    zusammen 86 - ohne einen einzigen Fehlalarm.

    Dazu die feste Regel fuer Anreden, die kein Modell braucht.

    Faellt der Spark aus, fliegt die Ausnahme weiter. Der Aufrufer muss das
    als Grund werten, den Cloud-Weg zu sperren: Eine Maskierung, deren
    Erkennung nicht gelaufen ist, ist keine Maskierung.
    """
    gefunden = {}
    for prompt in (NAMEN_PROMPT, NAMEN_PROMPT_WEIT):
        for typ, wert in _einmal_fragen(prompt, text):
            gefunden[wert] = typ
    for typ, wert in anredefunde(text):
        gefunden[wert] = typ

    funde = [(typ, wert) for wert, typ in gefunden.items()]
    funde.sort(key=lambda paar: len(paar[1]), reverse=True)
    return funde


def _einmal_fragen(prompt, text):
    """Ein Durchgang mit einem Prompt."""
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": (text or "")[:4000]},
        ],
        "max_tokens": 300,
        "temperature": 0.0,
    }

    with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
        antwort = client.post(
            f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
        )
        antwort.raise_for_status()
        roh = antwort.json()["choices"][0]["message"]["content"] or ""

    treffer = re.search(r"\[.*?\]", roh, re.DOTALL)
    if not treffer:
        return []
    try:
        eintraege = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        logger.warning("Namensliste unverstaendlich, gilt als leer.")
        return []

    funde = []
    for eintrag in eintraege:
        if not isinstance(eintrag, dict):
            continue
        wert = str(eintrag.get("text", "")).strip()
        # Nur was wirklich im Text steht. Ein Modell, das Namen erfindet,
        # darf keine Ersetzung ausloesen.
        if wert and wert in text:
            funde.append((TYP_PERSON, wert))
    return funde


# --- Stufe 2b: Umformulieren statt Bearbeiten ----------------------------

UMSCHREIB_PROMPT = (
    "Gib die folgende Schulaufgabe neu wieder, ohne jede Person.\n"
    "Ersetze Namen durch eine Rolle: ein Kind, eine Lehrerin, jemand. Lass "
    "Ortsnamen, Schulnamen und Adressen weg.\n"
    "ÄNDERE KEINE ZAHL und lass keine Zahl weg. Behalte alle Einheiten.\n"
    "Antworte nur mit der neuen Aufgabe, ohne Einleitung und ohne Kommentar."
)

_ZAHLEN = re.compile(r"\d+")


class UmschreibenGescheitert(Exception):
    """Die Umformulierung hat die Aufgabe veraendert."""


def zahlenfolge(text):
    """Alle Zahlen in ihrer Reihenfolge.

    Der Vergleich ist bewusst streng: gleiche Zahlen, gleiche Reihenfolge.
    Ein Modell, das aus 6 Packungen 8 macht, liefert eine falsche Loesung -
    und die stuende danach im Systemprompt der Stufenhilfen.
    """
    return _ZAHLEN.findall(text or "")


def neu_formulieren(text):
    """Laesst den Spark die Aufgabe ohne Personen neu schreiben.

    Gibt den neuen Text zurueck. Veraendert die Umformulierung die
    Zahlenfolge, fliegt UmschreibenGescheitert: Dann geht die urspruengliche
    Aufgabe den alten Weg ueber Erkennen und Maskieren.
    """
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": [
            {"role": "system", "content": UMSCHREIB_PROMPT},
            {"role": "user", "content": (text or "")[:4000]},
        ],
        "max_tokens": 400,
        "temperature": 0.0,
    }

    with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
        antwort = client.post(
            f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
        )
        antwort.raise_for_status()
        neu = (antwort.json()["choices"][0]["message"]["content"] or "").strip()

    if not neu:
        raise UmschreibenGescheitert("Die Umformulierung war leer.")
    if zahlenfolge(neu) != zahlenfolge(text):
        raise UmschreibenGescheitert(
            "Die Umformulierung hat die Zahlen verändert."
        )
    return neu


# --- Stufe 3: Ersetzung durch Tokens -------------------------------------

def token_fuer(typ, wert):
    """Baut ein Token im Format der Vorlage, etwa [PERS_a3f2].

    Der Anhang ist aus dem Wert abgeleitet, damit derselbe Name im selben
    Text immer dasselbe Token bekommt. Er ist gekuerzt und damit nicht
    umkehrbar; die Zuordnung steht ausschliesslich in der Sitzungstabelle.
    """
    kurz = hashlib.sha256(wert.encode("utf-8")).hexdigest()[:4]
    return f"[{typ}_{kurz}]"


def blockierende(funde):
    """Funde, die den Cloud-Weg sperren, statt maskiert zu werden."""
    return [(typ, wert) for typ, wert in funde if typ in BLOCKIERENDE_TYPEN]


def maskieren(text, funde):
    """Ersetzt alle Funde durch Tokens.

    Gibt den maskierten Text und die Zuordnungstabelle zurueck. Die Tabelle
    gehoert in die Sitzung und stirbt mit ihr.

    Was in einem blockierenden Fund steckt, wird nicht angeruehrt. Sonst
    frisst ein kuerzeres Muster ein Stueck aus der Sozialversicherungsnummer
    heraus: Das Telefonmuster passt auf deren hintere sechs Ziffern. Die
    Nummer waere dann angeknabbert, der Leak-Check faende sie nicht mehr und
    der Aufruf ginge hinaus.
    """
    maskiert = text or ""
    tabelle = {}
    gesperrt = [wert for _, wert in blockierende(funde)]

    for typ, wert in funde:
        if typ in BLOCKIERENDE_TYPEN:
            continue
        if any(wert in sperre for sperre in gesperrt):
            continue
        if wert not in maskiert:
            continue
        marke = token_fuer(typ, wert)
        maskiert = maskiert.replace(wert, marke)
        tabelle[marke] = {"typ": typ, "wert": wert}
    return maskiert, tabelle


def zuruecksetzen(text, tabelle):
    """Macht die Maskierung rueckgaengig, bevor das Kind die Antwort sieht."""
    zurueck = text or ""
    for marke, eintrag in tabelle.items():
        zurueck = zurueck.replace(marke, eintrag["wert"])
    return zurueck


# --- Stufe 4: Leak-Check --------------------------------------------------

def leak_check(ausgehend, funde):
    """Steht noch eine erkannte Originalzeichenkette im ausgehenden Text?

    Wichtig zu wissen, und im Vortrag auch so zu sagen: Dieser Check prueft
    gegen die ERKANNTEN Zeichenketten. Was die Erkennung uebersehen hat,
    steht nicht auf der Liste und passiert den Check. Er faengt Fehler beim
    Ersetzen, nicht Fehler beim Erkennen. Zwei Netze, kein Beweis.
    """
    durchgerutscht = []
    for typ, wert in funde:
        if wert and wert in (ausgehend or ""):
            durchgerutscht.append({"typ": typ, "wert": wert})
    return durchgerutscht


def zaehlung(tabelle):
    """Anzahl ersetzter Entitaeten je Typ, fuer das Protokoll ohne Inhalte."""
    gezaehlt = {}
    for eintrag in tabelle.values():
        gezaehlt[eintrag["typ"]] = gezaehlt.get(eintrag["typ"], 0) + 1
    return gezaehlt
