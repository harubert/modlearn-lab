"""Die Musikstunde: Grenzen, die die Lehrperson setzt, und das Aufraeumen am Dienst.

Die vierte Betriebsart, das fuenfte Fach. Die Kinder schreiben einen Liedtext zum Thema der
Stunde, waehlen einen Stil, und der Musikdienst am Spark (core/musik.py,
ACE-Step 1.5, MIT-Lizenz) macht daraus ein Lied. Beitritt, Tierwahl, Verfall
und Beenden sind dieselben wie in den anderen Betriebsarten; was hier steht,
ist nur das, was die Musik anders braucht.

WAS MIT DER SITZUNG STIRBT

Die Lieder liegen an zwei Stellen: die Zeile `Lied` bei uns (mit dem
Liedtext) und Auftrag samt MP3 am Spark. Die Zeile stirbt mit der Teilnahme,
wie alles andere. Am Spark muss jemand loeschen, und das ist
`am_dienst_loeschen`: ein DELETE /auftraege?kennzeichen=<log_key> beim
Beenden und beim Verfall. Das Ergebnis wird ausgewertet und nicht angenommen
(CLAUDE.md, 12.10.2026): Meldet der Dienst die Dateien nicht als entfernt
oder antwortet er gar nicht, steht das laut im Log. Ein stiller Fehlschlag
beim Datenschutz ist schlimmer als keine Massnahme. Das Netz darunter ist
der Verfall am Dienst selbst nach acht Stunden.

Das Kennzeichen ist der log_key der Sitzung: ein Zufallswert, der nichts
ueber Kinder oder Lehrperson verraet, und mit dem der Dienst alle Auftraege
einer Stunde auf einmal findet.

DER TEXTVORSCHLAG VOM SPARK (19.10.2026)

Thomas: Die Kinder sollen den Text entweder selbst schreiben oder vom
Sprachmodell zu einem Thema schreiben lassen. Der Vorschlag kommt in das
Textfeld und bleibt dort aenderbar; vertont wird erst, was das Kind
abschickt, mit allen Pruefungen von vorher. Was hier steht, ist der Prompt
(textprompt) und das Aufraeumen der Antwort (text_bereinigen): Das Modell
schreibt gern "[Strophe 1]" oder "Refrain:", der Lyrics-Tokenizer von
ACE-Step kennt aber nur "[verse]" und "[chorus]", klein und englisch; alles
andere wuerde mitgesungen. Die Grenze von TEXTHILFE_HOECHSTENS Vorschlaegen
je Teilnahme setzt die Ansicht durch, nicht die Seite.
"""

import logging
import re

from . import levels

logger = logging.getLogger(__name__)

# Hoechstdauer je Lied, die die Lehrperson waehlt. Die Kinder koennen in
# Schritten von 30 Sekunden bis dorthin gehen. Mehr als zwei Minuten sind in
# einer Stunde mit 25 Kindern nicht zu verantworten: Der Spark rechnet
# seriell, und jede Musikminute kostet in der kleinen Fassung etwa neun
# Sekunden Rechenzeit, auf die alle anderen warten.
DAUERN = (30, 60, 90, 120)
HOECHSTDAUERN = (
    (30, "30 Sekunden"),
    (60, "1 Minute"),
    (90, "1,5 Minuten"),
    (120, "2 Minuten"),
)
HOECHSTDAUER_STANDARD = 60

# Lieder je Kind. Die Grenze prueft der Server, nicht die Seite.
LIEDER_WAHL = (1, 2, 3, 4, 5)
LIEDER_STANDARD = 3

# Die Sprache des Gesangs stellt die Lehrperson fuer alle ein, wie die
# Zielsprache beim Sprechcoach: Wer eine Englischstunde mit Musik haelt,
# will nicht, dass die Haelfte deutsch singt.
GESANGSSPRACHEN = (
    ("de", "Deutsch"),
    ("en", "Englisch"),
)
GESANG_STANDARD = "de"

# Laenger als in der oeffentlichen Probierecke (400): Ein Lied von zwei
# Minuten hat zwei Strophen und einen Refrain, die in 400 Zeichen nicht
# passen.
TEXT_MAX = 800

# Immer die kleine Fassung: etwa 9 statt 20 Sekunden Rechenzeit je
# Musikminute. Bei einer ganzen Klasse ist das der Unterschied zwischen
# einigen und zwanzig Minuten Wartezeit.
FASSUNG = "klein"

# Der Textvorschlag vom Spark. Hoechstens so viele je Teilnahme, gezaehlt in
# der Browsersitzung (kein eigenes Modell fuer einen Zaehler): Jeder
# Vorschlag ist ein Aufruf am Sprachmodell, waehrend 25 andere Kinder darauf
# warten, und wer sechsmal wuerfelt, soll den siebten Text selbst schreiben.
TEXTHILFE_HOECHSTENS = 6
THEMA_MAX = 200
TEXTHILFE_SITZUNGSSCHLUESSEL = "musik_textvorschlaege"


def erlaubte_dauern(hoechstdauer):
    """Die Dauern, die ein Kind waehlen kann, bis zur Grenze der Lehrperson."""
    return [d for d in DAUERN if d <= (hoechstdauer or HOECHSTDAUER_STANDARD)]


# --- Der Textvorschlag --------------------------------------------------------

_SPRACHE = {
    "de": "auf Deutsch",
    "en": "auf Englisch (der ganze Text, auch der Refrain)",
}

# Der Aufbau nach der gewaehlten Dauer, als Bloecke durchnummeriert: Mit
# "eine Strophe, dann der Refrain" schrieb das Modell am 19.10. fuer 30
# Sekunden drei Strophen und drei Refrains. Vier kurze Zeilen je Block,
# damit 120 Sekunden mit drei Strophen in TEXT_MAX Zeichen passen.
_AUFBAU = {
    30: ("genau zwei Blöcke: 1. [verse] mit vier Zeilen, 2. [chorus] mit vier "
         "Zeilen."),
    60: ("genau vier Blöcke: 1. [verse] mit vier Zeilen, 2. [chorus] mit vier "
         "Zeilen, 3. [verse] mit vier neuen Zeilen, 4. [chorus] mit denselben vier "
         "Zeilen wie in 2."),
    90: ("genau sechs Blöcke: 1. [verse] mit vier Zeilen, 2. [chorus] mit vier "
         "Zeilen, 3. [verse] mit vier neuen Zeilen, 4. [bridge] mit zwei Zeilen, "
         "5. [verse] mit vier neuen Zeilen, 6. [chorus] mit denselben vier Zeilen "
         "wie in 2."),
}
_AUFBAU[120] = _AUFBAU[90]

# Zeichen je Dauer: Was das Modell bekommt und wo bereinigt geschnitten wird.
# Mehr Text als Musik heisst bei ACE-Step: schneller gesungen oder abgebrochen.
_ZEICHEN = {30: 320, 60: 560, 90: TEXT_MAX, 120: TEXT_MAX}


def _passende_dauer(sekunden):
    passende = [d for d in sorted(_AUFBAU) if d <= (sekunden or 0)]
    return passende[-1] if passende else min(_AUFBAU)


def zeichen_grenze(sekunden):
    """Hoechstens so viele Zeichen fuer einen Vorschlag zu dieser Dauer."""
    return _ZEICHEN[_passende_dauer(sekunden)]


def textprompt(sprache, altersklasse, sekunden, thema):
    """System-Anweisung und Frage fuer spark.antwort_holen_sync.

    Kindgerecht nach der Altersklasse der Sitzung (levels.ALTERSKLASSEN), in
    der Gesangssprache, ohne Namen echter Menschen, mit den Marken klein und
    englisch auf eigenen Zeilen, Laenge nach der Dauer. Das Thema ist das
    einzige, was vom Kind kommt; es ist vorher durch text_erlaubt gegangen.
    """
    wer = levels.anrede(altersklasse)["gegenueber"]
    dauer = _passende_dauer(sekunden)
    system = (
        "Du schreibst Liedtexte für eine Musikstunde in der Schule. Eine Musik-KI "
        "singt den Text danach.\n"
        f"Der Text ist für {wer} und wird {_SPRACHE.get(sprache, _SPRACHE['de'])} "
        "geschrieben.\n\n"
        "Regeln:\n"
        f"- Das Lied hat {_AUFBAU[dauer]} Nach dem letzten Block ist das Lied zu "
        "Ende; keine weiteren Blöcke.\n"
        "- Jede Marke steht allein auf einer eigenen Zeile und wird genau so "
        "geschrieben, klein und englisch: [verse], [chorus], [bridge]. Keine anderen "
        "Marken, keine Nummern dahinter, keine Überschriften wie „Strophe 1“.\n"
        "- Kurze Zeilen mit höchstens acht Wörtern und einfache Wörter, die man gut "
        "singen kann. Die Zeilen reimen sich paarweise.\n"
        "- Freundlich und kindgerecht: nichts Grausames, nichts Gruseliges, keine "
        "Schimpfwörter, niemand wird verspottet.\n"
        "- Keine Namen von echten Menschen, keine Marken, keine Produkte.\n"
        f"- Höchstens {_ZEICHEN[dauer]} Zeichen insgesamt.\n"
        "- Gib nur den Liedtext aus: keinen Titel, keine Überschrift, keine "
        "Erklärung, keine Anführungszeichen, keine Akkorde, keine Anmerkungen."
    )
    frage = f"Worum das Lied geht: {thema}"
    return system, frage


# Was das Modell als Marke schreibt, und was der Tokenizer daraus braucht.
_MARKEN_UEBERSETZT = {
    "verse": "verse", "vers": "verse", "strophe": "verse",
    "chorus": "chorus", "refrain": "chorus",
    "pre-chorus": "pre-chorus", "prechorus": "pre-chorus", "vorrefrain": "pre-chorus",
    "bridge": "bridge", "bruecke": "bridge", "brücke": "bridge",
    "intro": "intro", "vorspiel": "intro", "einleitung": "intro",
    "outro": "outro", "nachspiel": "outro", "schluss": "outro",
    "hook": "hook", "break": "break", "solo": "solo",
    "inst": "inst", "instrumental": "inst",
}
_DENKEN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_ZAUN = re.compile(r"^\s*```.*$", re.MULTILINE)
# "[Verse 1]", "**[Refrain]**", "[chorus]:"
_MARKE_IN_KLAMMERN = re.compile(r"^[\s*_#>]*\[\s*([^\]]{1,30})\s*\][\s*_#:.]*$")
# "Strophe 1:", "Refrain:", "## Chorus"
_MARKE_ALS_UEBERSCHRIFT = re.compile(
    r"^[\s*_#>]*([A-Za-zÄÖÜäöüß\-]{3,20})\s*(\d{1,2})?\s*(:|$)[\s*_#]*$")
_TITELZEILE = re.compile(r"^[\s*_#>]*(titel|title|lied|song)\s*:", re.IGNORECASE)
_BETONT = re.compile(r"[*_]{1,3}(.+?)[*_]{1,3}")


def _marke(wort, marken):
    wort = re.sub(r"[\d\s:._\-]+$", "", str(wort or "").strip().lower())
    ziel = _MARKEN_UEBERSETZT.get(wort)
    if ziel and f"[{ziel}]" in marken:
        return f"[{ziel}]"
    return None


def text_bereinigen(roh, marken, hoechstens=TEXT_MAX):
    """Aus der Antwort des Modells ein Liedtext, den ACE-Step versteht.

    Nachdenken in <think>, Codezaeune und Titelzeilen fallen weg. Marken in
    jeder Schreibweise ("[Strophe 1]", "Refrain:", "**[Chorus]**") werden zu
    den Marken, die der Dienst kennt, klein und englisch; was in eckigen
    Klammern steht und keine Marke ist, faellt weg, damit es nicht
    mitgesungen wird. Vor jeder Marke steht eine Leerzeile, hoechstens eine.
    Gekuerzt wird auf `hoechstens` (nie mehr als TEXT_MAX), und zwar an einem
    Blockende, wenn danach noch mehr als die Haelfte steht, sonst an einem
    Zeilenende: Ein halber Refrain ist schlechter als keiner.
    """
    hoechstens = min(int(hoechstens or TEXT_MAX), TEXT_MAX)
    marken = [str(m).lower() for m in (marken or ())]
    text = _DENKEN.sub("", str(roh or ""))
    text = _ZAUN.sub("", text).replace("\r\n", "\n")
    zeilen = []
    for zeile in text.split("\n"):
        zeile = zeile.strip()
        if not zeile:
            if zeilen and zeilen[-1] != "":
                zeilen.append("")
            continue
        if _TITELZEILE.match(zeile):
            continue
        in_klammern = _MARKE_IN_KLAMMERN.match(zeile)
        if in_klammern:
            marke = _marke(in_klammern.group(1), marken)
            if marke:
                zeilen.append(marke)
            continue
        ueberschrift = _MARKE_ALS_UEBERSCHRIFT.match(zeile)
        if ueberschrift:
            marke = _marke(ueberschrift.group(1), marken)
            if marke:
                zeilen.append(marke)
                continue
            if ueberschrift.group(3) == ":":
                # Eine Ueberschrift, die keine Marke ist ("Anmerkung:").
                continue
        zeilen.append(_BETONT.sub(r"\1", zeile).strip("\"“”„"))
    fertig = []
    for zeile in zeilen:
        if zeile in marken and fertig and fertig[-1] != "":
            fertig.append("")
        fertig.append(zeile)
    text = "\n".join(fertig).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > hoechstens:
        text = text[:hoechstens]
        blockende = text.rfind("\n\n")
        if blockende > hoechstens // 2:
            text = text[:blockende]
        elif "\n" in text:
            text = text.rsplit("\n", 1)[0]
    return text.strip()


def _alles_entfernt(inhalt):
    """Hat der Dienst die Dateien als entfernt gemeldet?

    Die Schnittstelle nennt `{entfernt, datei_entfernt}`, ohne festzulegen,
    ob das bei mehreren Auftraegen Wahrheitswerte oder Zahlen sind. Beides
    wird gelesen; alles andere (fehlt, False, weniger Dateien als Auftraege)
    gilt als nicht entfernt.
    """
    datei = inhalt.get("datei_entfernt")
    if datei is True:
        return True
    entfernt = inhalt.get("entfernt")
    if isinstance(datei, bool) or not isinstance(datei, int):
        return False
    if isinstance(entfernt, bool) or not isinstance(entfernt, int):
        return False
    return datei >= entfernt


def am_dienst_loeschen(sitzung):
    """Alle Auftraege dieser Sitzung am Spark loeschen. Gibt True bei Erfolg.

    Wirft nie: Das Beenden einer Sitzung darf nicht daran scheitern, dass der
    Spark gerade schweigt - die Daten bei uns werden trotzdem geloescht. Aber
    jeder Fehlschlag steht als Fehler im Log, mit der Nummer der Sitzung und
    ohne Kennzeichen, damit jemand nachsehen kann.
    """
    from core import musik

    antwort = musik.auftraege_entfernen(sitzung.log_key)
    if antwort.code == 404:
        # Nichts mehr da: verfallen oder schon geloescht. Das ist das Ziel.
        return True
    if not antwort.ok:
        logger.error(
            "Musikstunde: Lieder der Sitzung %s am Musikdienst NICHT geloescht "
            "(%s). Der Dienst raeumt sie erst nach seinem Verfall selbst ab.",
            sitzung.pk, antwort.code or antwort.satz or "keine Antwort",
        )
        return False
    if not _alles_entfernt(antwort.inhalt):
        logger.error(
            "Musikstunde: Sitzung %s, Auftraege entfernt (%r), Dateien aber "
            "nicht gemeldet (datei_entfernt=%r). Die MP3 liegen womoeglich "
            "noch am Spark.",
            sitzung.pk, antwort.inhalt.get("entfernt"),
            antwort.inhalt.get("datei_entfernt"),
        )
        return False
    return True
