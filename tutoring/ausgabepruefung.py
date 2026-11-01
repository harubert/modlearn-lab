"""Prueft die Antwort des Modells, bevor sie das Kind sieht.

Anlass, und er ist ernst: Bei der Aufgabe "6 Packungen zu je 8 Stiften"
antwortete Stufe 1 mit "Probier's mal mit dem Zaehlen: 8, 16, 24, 32, 40,
48." Das ist die Loesung, auf der ersten Stufe, obwohl der Systemprompt sie
ausdruecklich verbietet.

Damit ist belegt, was die Anwendung ohnehin annimmt: Ein Systemprompt ist
eine Bitte, keine Grenze. Die Grenze gehoert in den Server.

Die Pruefung ist bewusst deterministisch und kostet keinen zusaetzlichen
Aufruf. Sie sucht nicht nach Bedeutung, sondern nach den Formen, in denen
eine Loesung auftritt: eine Gleichung mit Ergebnis, eine ausgeschriebene
Rechnung, eine Zaehlreihe.
"""

import logging
import collections
import re

from . import levels

logger = logging.getLogger(__name__)

# Eine Gleichung mit Ergebnis: "6 · 8 = 48", aber auch "= 48". Die zweite
# Fassung greift die Zahl rechts heraus: Auf der Sekundarstufe zaehlt nur
# eine Gleichung, deren rechte Seite das Endergebnis der geprueften Loesung
# ist (Benchmark 19.10.2026, Befund 5: "x² − 6x + 5 = 0" ist die Aufgabe,
# kein Ergebnis).
_GLEICHUNG = re.compile(r"=\s*-?\d")
_GLEICHUNG_RECHTS = re.compile(r"=\s*(-?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)")

# Eine ausgeschriebene Rechnung mit zwei Zahlen.
_RECHNUNG = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:·|\*|×|x\b|\+|:|÷|mal|geteilt durch|durch|plus|"
    r"minus|weniger)\s*\d+(?:[.,]\d+)?",
    re.IGNORECASE,
)

# Das Minuszeichen nur mit Leerzeichen ringsum: "6-10 Jahre" ist keine
# Rechnung, "128 - 36" schon.
_ABZUG = re.compile(r"\d+(?:[.,]\d+)?\s+[-−–]\s+\d+(?:[.,]\d+)?")

# Eine Zaehlreihe: mindestens vier Zahlen in gleichem Abstand.
_ZAHLENREIHE = re.compile(r"\b\d+(?:\s*,\s*\d+){3,}")


# Woerter, die einen Rechenweg benennen. Nur auf Stufe 1 verboten: Dort soll
# das Kind die Situation verstehen, nicht erfahren, was zu tun ist.
#
# Anlass: Auf "6 Packungen zu je 8 Stiften" antwortete Stufe 1 mit "Das ist
# eine Aufgabe, bei der du zaehlen musst, wie viele Stifte in allen Packungen
# zusammen sind" und "Probier es ruhig mit dem Zaehlen". Der Systemprompt
# verbietet genau das seit dem ersten Tag. Er ist eben eine Bitte.
# Nur die Umlautform: "bezahlen" und "Zahlen" sind keine Rechenwege, und
# auf Stufe 1 darf stehen, dass in der Angabe zwei Zahlen vorkommen.
# "6 mal so viele Stifte" ist auch dann ein Rechenweg, wenn kein Rechenzeichen
# dasteht. Auf Stufe 1 stand genau das im Betrieb.
# "erzaehlen" ist ausgenommen: "Erzaehl mir, was du verstanden hast" ist auf
# Stufe 1 genau richtig. "gezaehlt" und "abzaehlen" sind es nicht, deshalb
# die Vorsilben im Muster.
# Seit dem Benchmark (19.10.2026, Befund 5) nicht mehr darin: "Rechnung",
# "rechnet", "Zaehlreim". Die Rubrik gab fuenf Stufe-1-Hilfen, die nur diese
# Woerter enthielten ("so eine Rechnung kommt im Alltag vor"), die volle
# Punktzahl; die Pruefung hatte sie gekuerzt. Was bleibt: rechne, rechnen,
# berechnen, ausrechnen, nachrechnen.
_METHODE = re.compile(
    r"(?:(?<!er)z(?:ä|ae)hl(?!reim)\w*|\b(?:be|aus|nach|zusammen|um)?rechne(?:n|st)?\b|"
    r"multipli\w*|mal\s*(?:ge)?n(?:imm|ehm|omm)\w*|"
    r"mal rechnen|mal so viel\w*|\d+\s*mal\b|"
    r"addier\w*|subtrahier\w*|ab(?:ge)?z(?:ieh|og)\w*|"
    r"divid\w*|geteilt|einmaleins|rechenweg|rechenart|"
    r"plus rechnen|minus rechnen)",
    re.IGNORECASE,
)


# Die Rechenart beim Namen genannt. Auf Stufe 2 und 3 verboten, auf Stufe 4
# erlaubt: Dort ist die inhaltlich-strategische Hilfe an der Reihe, und die
# darf sagen, worum es geht.
#
# Anlass: Stufe 2 schrieb "Denk daran, dass du nicht addieren musst, sondern
# die Packungen mit den Stiften malnehmen musst" - und zwar bevor das Kind
# ueberhaupt einen Ansatz hatte. Die eigene Anweisung fuer diese Stufe sagt
# woertlich: nicht, welche die richtige waere.
#
# Absichtlich nur die formalen Namen. "plus", "zusammenzaehlen", "Rechnung"
# bleiben erlaubt, sonst koennte Stufe 3 den Fehler des Kindes nicht mehr
# benennen: "6 plus 8 ist nicht die richtige Rechnung" muss durchgehen.
_OPERATION = re.compile(
    r"(?:mal\s*(?:ge)?n(?:imm|ehm|omm)\w*|mal rechnen|mal so viel\w*|\d+\s*mal\b|"
    r"multipli\w*|divid\w*|geteilt|addier\w*|subtrahier\w*|"
    # Dieselben Rechenarten in Kindersprache. Ohne sie half das Verbot
    # wenig: Stufe 2 schrieb "Du musst jetzt die 6 Packungen mit je 8
    # Stiften zusammenzaehlen" und wies damit genauso den Weg.
    # Seit dem Benchmark (Befund 5) auch mit "zu" ("zusammenzuzaehlen"),
    # abziehen, wegnehmen, "nimm 6 weg", plus und minus als Wort: Die
    # Rubrik gab 20 von 67 Stufe-1- und 27 von 89 Stufe-2-Hilfen null
    # Punkte, und keine dieser Formen stand im Muster.
    r"zusammen(?:ge|zu)?z(?:ä|ae)hl\w*|"
    r"dazu(?:ge|zu)?z(?:ä|ae)hl\w*|"
    r"zusammen(?:ge|zu)?rechn\w*|aufeinanderlegen|"
    r"ab(?:ge|zu)?zieh\w*|ab(?:ge)?zog\w*|"
    r"weg(?:ge|zu)?n(?:imm|ehm|omm)\w*|\bn(?:imm|ehm|ahm)\w*\s+[^.!?]{0,24}?\bweg\b|"
    r"\bplus\b|\bminus\b)",
    re.IGNORECASE,
)

# "teilen" nur klein geschrieben: Gross ist es das Hauptwort ("in gleich
# grossen Teilen"), und das darf Stufe 1 bis 3 sagen. Der Imperativ am
# Satzanfang ("Teile 24 durch 8") faellt ueber _RECHNUNG auf ("24 durch 8").
_OPERATION_KLEIN = re.compile(r"\b(?:teilst|teilen|teile|teilt)\b")

# Die Werkzeuge der Sekundarstufe. Auf Stufe 1 bis 3 verboten, auf Stufe 4
# an der Reihe: Dort ist "welche Regel, welcher Satz" der Auftrag. Fuer die
# Volksschule ohne Bedeutung; dort heissen die Werkzeuge Rechenarten und
# stehen in _OPERATION. Benchmark 19.10.2026, Befund 5: "Satz des Pythagoras"
# stand in sek14 schon auf Stufe 1 und 2, "Skalarprodukt" und
# "Binomialverteilung" ebenso, und kein Muster kannte sie.
_WERKZEUG = re.compile(
    r"(?:pythagoras|skalarprodukt|binomial\w*|lösungsformel|loesungsformel|"
    r"pq-formel|abc-formel|mitternachtsformel|stammfunktion|ableitung\w*|"
    r"ableiten|integral\w*|integrieren|gemeinsame[nrs]?\s+nenner|hauptnenner|"
    r"dreisatz|prozentformel|grundwert|differenzenquotient|differentialquotient|"
    r"tangens|sinus|kosinus|cosinus|\btan\b|\bsin\b|\bcos\b|"
    r"vieta|quadratische\s+ergänzung|substitution|einsetzungsverfahren|"
    r"gleichsetzungsverfahren|additionsverfahren|eliminationsverfahren|"
    r"erwartungswert|standardabweichung|varianz|normalverteilung|"
    r"kreuzprodukt|vektorprodukt|determinante|logarithm\w*|"
    r"kehrwert|erweitern|kürzen|kuerzen|ausmultiplizieren|ausklammern|"
    r"faktorisieren|umformen|äquivalenzumformung)",
    re.IGNORECASE,
)

# Zahlen, die auf der Sekundarstufe keine Ergebnisse sind: Hochzahlen,
# Indizes, Winkelmasse, Nummern von Gleichungen und Schritten.
_KEIN_ERGEBNIS = re.compile(
    r"(?:\^\s*\{?-?\d+\}?|_\s*\{?\d+\}?|\bhoch\s+\d+|\d+(?:[.,]\d+)?\s*°|"
    r"\d+(?:[.,]\d+)?\s*grad\b|\b(?:gleichung|schritt|zeile|teil|punkt|"
    r"aufgabe|stufe|klasse)\s+\d+|\b(?:i|ii|iii|iv)\))",
    re.IGNORECASE,
)


def endergebnis_zahlen(loesung):
    """Die Zahlen des Endergebnisses einer geprueften Loesung.

    Die Qualitaetssicherung liefert "WEG: ... ERGEBNIS: 48 Stifte"; der
    Benchmark haengt " Ergebnis: ..." an den Loesungsweg. Gesucht wird der
    Teil nach der letzten Marke, sonst die letzte Zeile. Ohne Zahl darin:
    leer, und dann prueft die Gleichungsregel auf der Sekundarstufe gar
    nicht, weil sie nichts haette, wogegen.
    """
    text = (loesung or "").strip()
    if not text:
        return set()
    teile = re.split(r"(?i)\bergebnis\s*:", text)
    schluss = teile[-1] if len(teile) > 1 else text.strip().splitlines()[-1]
    return _zahlen_normiert(schluss)


# Eine Zahl, ein Bruch oder eine Zahl mit Tausendergruppen ("300 500", auch
# mit geschuetztem Leerzeichen). Lauf F (31.10.2026), vs14: "300 000" war 300
# und 0, und 0 war dann die "letzte Zahl" beider Texte.
_ZAHL_ODER_BRUCH = re.compile(
    r"-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?(?!\d)|-?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?"
)


def _zahl_normiert(roh):
    """Eine Zahl oder ein Bruch, Komma wie Punkt, ohne fuehrende Nullen, ohne Leerzeichen."""
    roh = re.sub(r"[ \u00a0\u202f]", "", roh)
    if "/" in roh:
        zaehler, nenner = roh.split("/", 1)
        return _zahl_normiert(zaehler) + "/" + _zahl_normiert(nenner)
    wert = roh.replace(",", ".").lstrip("0") or "0"
    if wert.startswith("-"):
        wert = "-" + (wert[1:].lstrip("0") or "0")
    if "." in wert:
        wert = wert.rstrip("0").rstrip(".") or "0"
    return wert


def _zahlen_normiert(text):
    """Zahlen und Brueche eines Textes, normiert.

    Ein Bruch zaehlt als eine Zahl: "5/6" ist "5/6", nicht 5 und 6. Sonst
    gilt "6" als das Ergebnis von 1/2 + 1/3 (Lauf D3, sek01: der gemeinsame
    Nenner wurde als richtiges Endergebnis quittiert).
    """
    return {_zahl_normiert(roh) for roh in _ZAHL_ODER_BRUCH.findall(text or "")}


def _zahlen(text):
    """Alle Zahlen in einem Text, als Zeichenketten ohne fuehrende Nullen."""
    return {z.lstrip("0") or "0" for z in re.findall(r"\d+", text or "")}


def _neue_zahlen(text, eigenes, schulstufe=levels.VOLKSSCHULE):
    """Zahlen, die weder in der Aufgabe noch beim Kind vorkommen.

    Die schaerfste und zugleich einfachste Regel: Unterhalb der Loesungsstufe
    darf eine Hilfe die gegebenen Zahlen wiederholen, aber keine neue
    hervorbringen. Ein Zwischenergebnis ist eine neue Zahl, das Ergebnis auch.

    Anlass: Nach der letzten Stufe hat die Rueckfrage in einer Sitzung mit
    "nur Tipps" geantwortet: "Die Antwort ist 48." Kein Rechenzeichen, keine
    Gleichung - und trotzdem genau das, was die Lehrperson ausgeschlossen
    hatte.

    Auf der Sekundarstufe zaehlen Hochzahlen, Indizes und Winkelmasse nicht:
    "x²", "x_1", "32°" sind Schreibweisen, keine Ergebnisse (Befund 5).
    Was das Kind in Versuchen und Rueckfragen genannt hat, steht in
    ``eigenes`` und ist erlaubt, sonst darf eine Rueckmeldung die Zahl des
    Kindes nicht einmal zitieren.
    """
    erlaubt = set()
    for stueck in eigenes or []:
        erlaubt |= _zahlen(stueck)
    if schulstufe != levels.VOLKSSCHULE:
        text = _KEIN_ERGEBNIS.sub(" ", text or "")
    # Kleine Zahlen in Worten und Ordnungszahlen sind kein Ergebnis: "in zwei
    # Schritten", "der 1. Teil". Ziffern bis 10 bleiben trotzdem geprueft,
    # weil gerade sie oft das Ergebnis sind.
    return sorted(_zahlen(text) - erlaubt)


def _gleichung_mit_endergebnis(text, loesung):
    """Steht rechts von einem Gleichheitszeichen das Endergebnis der Loesung?"""
    ziel = endergebnis_zahlen(loesung)
    if not ziel:
        return False
    for roh in _GLEICHUNG_RECHTS.findall(text or ""):
        if _zahlen_normiert(roh) & ziel:
            return True
    return False


def _ist_reihe(text):
    """Vier oder mehr Zahlen mit gleichem Abstand, also vorgezaehlt."""
    for treffer in _ZAHLENREIHE.findall(text):
        zahlen = [int(z) for z in re.findall(r"\d+", treffer)]
        if len(zahlen) < 4:
            continue
        abstaende = {zahlen[i + 1] - zahlen[i] for i in range(len(zahlen) - 1)}
        if len(abstaende) == 1 and abstaende.pop() != 0:
            return True
    return False


# Dieselbe Rechnung in jeder Schreibweise. Das Kind schreibt "348 - 56 = 292",
# die Rueckmeldung sagt "348 minus 56" - das ist dasselbe Zitat. Vor Lauf D2
# des Benchmarks war das Zitat-Privileg woertlich, und die Pruefung schnitt
# gerade die Saetze weg, in denen der Fehler benannt wurde (Lauf D: 51 % der
# Stufe-2-Hilfen gekuerzt).
_OPERATOR_KLASSEN = {
    "mal": ("·", "*", "×", "x", "mal"),
    "geteilt": (":", "÷", "geteilt durch", "durch"),
    "plus": ("+", "plus"),
    "minus": ("-", "−", "–", "minus", "weniger"),
}
_OPERATOR_KLASSE = {
    schreibweise: klasse
    for klasse, schreibweisen in _OPERATOR_KLASSEN.items()
    for schreibweise in schreibweisen
}
_KIND_RECHNUNG = re.compile(
    r"(-?\d+(?:[.,]\d+)?)\s*(·|\*|×|x\b|\+|:|÷|geteilt durch|durch|mal|plus|minus|"
    r"weniger|-|−|–)\s*(-?\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_KIND_ERGEBNIS = re.compile(r"=\s*(-?\d+(?:[.,]\d+)?)")

# Die Rechenart, die das Kind benutzt hat, darf die Hilfe beim Namen nennen,
# in jedem Wort: Wer "7 + 5" geschrieben hat, dem darf die Rueckmeldung
# sagen, dass er addiert hat. Das verraet nichts, das Kind hat es getan.
# Verboten bleibt die Rechenart, die das Kind NICHT benutzt hat - die
# richtige. Benchmark 19.10.2026, Lauf D2: 27 von 36 gekuerzten Stufe-2-
# Hilfen fielen an "addiert", "weggenommen", "zusammenrechnest", und fast
# immer beschrieben sie den Versuch des Kindes, um den Fehler zu benennen.
_RECHENART_WOERTER = {
    "plus": re.compile(
        r"(?:addier\w*|zusammen(?:ge|zu)?z(?:ä|ae)hl\w*|dazu(?:ge|zu)?z(?:ä|ae)hl\w*|"
        r"zusammen(?:ge|zu)?rechn\w*|\bplus\b)", re.IGNORECASE),
    "minus": re.compile(
        r"(?:subtrahier\w*|ab(?:ge|zu)?zieh\w*|ab(?:ge)?zog\w*|weg(?:ge|zu)?n(?:imm|ehm|omm)\w*|"
        r"\bn(?:imm|ehm|ahm)\w*\s+[^.!?]{0,24}?\bweg\b|\bminus\b|\bweniger\b)", re.IGNORECASE),
    "mal": re.compile(
        r"(?:multipli\w*|mal\s*(?:ge)?n(?:imm|ehm|omm)\w*|mal rechnen|mal so viel\w*|"
        r"\d+\s*mal\b)", re.IGNORECASE),
    "geteilt": re.compile(
        r"(?:divid\w*|geteilt|\bteil(?:st|en|e|t)\b)", re.IGNORECASE),
}


def _rechenarten_des_kindes(eigenes):
    """Welche Rechenarten hat das Kind selbst verwendet, als Zeichen oder Wort?"""
    klassen = set()
    for stueck in eigenes or []:
        for _, op, _ in _KIND_RECHNUNG.findall(stueck or ""):
            klasse = _OPERATOR_KLASSE.get(op.lower())
            if klasse:
                klassen.add(klasse)
        for klasse, muster in _RECHENART_WOERTER.items():
            if muster.search(stueck or ""):
                klassen.add(klasse)
    return klassen


def _zitierte_rechnungen(eigenes):
    """Muster fuer jede Rechnung und jedes Ergebnis des Kindes, in jeder Schreibweise."""
    muster = []
    for stueck in eigenes or []:
        for a, op, b in _KIND_RECHNUNG.findall(stueck or ""):
            klasse = _OPERATOR_KLASSE.get(op.lower())
            if not klasse:
                continue
            schreibweisen = "|".join(re.escape(s) for s in _OPERATOR_KLASSEN[klasse])
            # Hinter der Zahl darf keine weitere Ziffer stehen, auch nicht
            # nach Komma oder Punkt ("= 480", "= 48,5"). Ein Satzpunkt ist
            # keine Ziffer: "Richtig, 6 · 8 = 48." ist das Zitat des Kindes.
            # Bis 30.10.2026 stand hier (?![\d.,]), und genau dieser Satz
            # wurde als "Gleichung mit Ergebnis" gekuerzt.
            muster.append(re.compile(
                rf"(?<![\d.,]){re.escape(a)}\s*(?:{schreibweisen})\s*{re.escape(b)}(?!\d|[.,]\d)",
                re.IGNORECASE,
            ))
        for ergebnis in _KIND_ERGEBNIS.findall(stueck or ""):
            muster.append(re.compile(rf"=\s*{re.escape(ergebnis)}(?!\d|[.,]\d)"))
    # Das erste Stueck ist die Angabe. Sie ist keine Quelle fuer Rechenarten
    # des Kindes: "minus 7 Grad" ist ein Vorzeichen, keine Rechnung, und in
    # Lauf D3 (sek06) machte es "abziehen" und "wegnehmen" unter "Nur Tipps"
    # zum Zitat.
    for klasse in _rechenarten_des_kindes(list(eigenes or [])[1:]):
        muster.append(_RECHENART_WOERTER[klasse])
    return muster


def _ohne_zitate(text, eigenes):
    """Entfernt, was das Kind selbst geschrieben hat.

    Die Rueckmeldungshilfe muss den Fehler benennen duerfen: "6 plus 8 ist
    hier nicht richtig" sieht wie eine Rechnung aus, ist aber ein Zitat. Ohne
    diese Ausnahme schneidet die Pruefung genau den Satz weg, um den es geht.
    Eine Rechnung des Kindes zaehlt in jeder Schreibweise als Zitat, sein
    Ergebnis ebenso ("= 292"); eine andere Rechnung mit denselben Zahlen
    nicht.
    """
    sauber = text or ""
    for muster in _zitierte_rechnungen(eigenes):
        sauber = muster.sub(" ", sauber)
    for stueck in eigenes or []:
        for muster in (_RECHNUNG, _ABZUG, _ZAHLENREIHE, _METHODE, _OPERATION,
                       _OPERATION_KLEIN, _WERKZEUG):
            for treffer in muster.findall(stueck or ""):
                if treffer:
                    sauber = sauber.replace(treffer, " ")
    return sauber


def verstoesse(text, stufe, hoechste_erlaubte, eigenes=None,
               schulstufe=levels.VOLKSSCHULE, loesung="", bestaetigt=False):
    """Welche verbotenen Formen stehen in diesem Text?

    Ab der letzten erlaubten Stufe, also dort wo die Loesung ohnehin kommen
    darf, wird nicht mehr geprueft. Stufe 5 rechnet vor, das ist ihre
    Aufgabe.

    Was das Kind selbst geschrieben hat, zaehlt nicht als Verstoss: Der
    eigene falsche Ansatz darf zitiert werden, sonst laesst sich der Fehler
    nicht benennen.

    Seit dem Benchmark (19.10.2026, Befund 5) prueft sie je Schulstufe: Fuer
    die Volksschule wie bisher, mit den nachgetragenen Formen. Fuer
    Mittelstufe und Oberstufe trifft "Gleichung mit Ergebnis" nur eine
    Gleichung, deren rechte Seite das Endergebnis der geprueften ``loesung``
    ist (ohne Loesung gar nicht), "neue Zahl" uebergeht Hochzahlen, Indizes
    und Winkel, und die Werkzeugliste (Pythagoras, Ableitung, Dreisatz ...)
    gilt auf Stufe 1 bis 3. Auf Stufe 4 ist "ausgeschriebene Rechnung" fuer
    alle Schulstufen aufgehoben: "Wie viel ist 7 plus 5?" ist dort der
    Auftrag, nicht der Verstoss; das Ergebnis selbst faengt "Gleichung mit
    Ergebnis" und "neue Zahl" weiter ab.

    Seit 31.10.2026 (Thomas' Stichprobe) dazu, auf jeder Stufe unter der
    Loesung: ein Zitat des Kindes, das in keinem seiner Beitraege steht
    ("erfundenes Zitat"), und eine Behauptung ueber die Lehrperson, die
    nicht ihre Einstellung nennt. Mit ``bestaetigt`` (die Bestaetigung nach
    einem richtigen Ergebnis) auch eine Rechnung mit den Zahlen des Kindes,
    aber einem anderen Rechenzeichen.
    """
    if stufe >= hoechste_erlaubte and hoechste_erlaubte >= 5:
        return []
    if stufe >= 5:
        return []

    roh = text
    text = _ohne_zitate(text, eigenes)
    sekundar = schulstufe in (levels.MITTELSTUFE, levels.OBERSTUFE)
    gefunden = []
    if sekundar:
        if _gleichung_mit_endergebnis(text, loesung):
            gefunden.append("Gleichung mit Ergebnis")
    elif _GLEICHUNG.search(text):
        gefunden.append("Gleichung mit Ergebnis")
    if stufe != 4 and (_RECHNUNG.search(text) or _ABZUG.search(text)):
        gefunden.append("ausgeschriebene Rechnung")
    if _neue_zahlen(roh, eigenes, schulstufe):
        gefunden.append("neue Zahl")
    if _ist_reihe(text):
        gefunden.append("vorgezählte Zahlenreihe")
    # Stufe 1 darf die Situation erklaeren, aber nicht sagen, was zu tun ist.
    if stufe == 1 and _METHODE.search(text):
        gefunden.append("genannter Rechenweg")
    # Stufe 2 und 3 duerfen sagen, dass die Rechenart nicht passt, aber nicht,
    # welche passen wuerde. Was das Kind selbst genannt hat, ist ein Zitat.
    if stufe in (2, 3) and (_OPERATION.search(text) or _OPERATION_KLEIN.search(text)):
        gefunden.append("genannte Rechenart")
    # Das Werkzeug der Sekundarstufe ist auf Stufe 4 an der Reihe, vorher nicht.
    if sekundar and stufe in (1, 2, 3) and _WERKZEUG.search(text):
        gefunden.append("genanntes Werkzeug")
    saetze = [s for s in _SATZENDE.split(roh or "") if s.strip()]
    if any(zitat_erfunden(s, eigenes) for s in saetze):
        gefunden.append("erfundenes Zitat")
    if any(behauptung_ueber_lehrperson(s, eigenes) for s in saetze):
        gefunden.append("Behauptung über die Lehrperson")
    if bestaetigt and anderes_rechenzeichen(roh, eigenes):
        gefunden.append("anderes Rechenzeichen als beim Kind")
    return gefunden


def saubere_saetze(text, stufe, hoechste_erlaubte, eigenes=None,
                   schulstufe=levels.VOLKSSCHULE, loesung="", bestaetigt=False):
    """Entfernt die Saetze, die eine verbotene Form enthalten.

    Lieber eine kuerzere Hilfe als eine, die die Loesung verraet. Bleibt
    nichts uebrig, entscheidet der Aufrufer.
    """
    saetze = re.split(r"(?<=[.!?])\s+", text or "")
    behalten = [
        satz for satz in saetze
        if not verstoesse(satz, stufe, hoechste_erlaubte, eigenes, schulstufe, loesung,
                          bestaetigt=bestaetigt)
    ]
    return " ".join(behalten).strip()


def schaerfung_fuer(gefunden):
    """Die Ermahnung, die zum schwersten Verstoss passt.

    Wer einen Rechenweg genannt hat, dem hilft es nichts, wenn man ihm das
    Rechnen verbietet. Die Reihenfolge ist die des Schadens.
    """
    if "genannter Rechenweg" in gefunden:
        return SCHAERFUNG_METHODE
    if "genanntes Werkzeug" in gefunden:
        return SCHAERFUNG_WERKZEUG
    if "erfundenes Zitat" in gefunden:
        return SCHAERFUNG_ZITAT
    if "Behauptung über die Lehrperson" in gefunden:
        return SCHAERFUNG_LEHRPERSON
    if "anderes Rechenzeichen als beim Kind" in gefunden:
        return SCHAERFUNG_RECHENZEICHEN
    if "genannte Rechenart" in gefunden:
        return SCHAERFUNG_RECHENART
    if "neue Zahl" in gefunden:
        return SCHAERFUNG_ZAHL
    return SCHAERFUNG


def loesung_passt(text, loesung):
    """Nennt die Stufe-5-Hilfe das Endergebnis der geprueften Loesung?

    None, wenn es nichts zu vergleichen gibt (keine Loesung oder keine Zahl
    im Ergebnis); True oder False sonst. Verglichen werden Zahlen, nicht
    Woerter: "12 Murmeln" und "zwoelf" waeren verschieden, und das ist der
    Preis dafuer, dass die Pruefung keinen Aufruf kostet.
    """
    ziel = endergebnis_zahlen(loesung)
    if not ziel:
        return None
    return bool(_zahlen_normiert(text) & ziel)


SCHAERFUNG_RECHENART = (
    "\n\nACHTUNG: Dein letzter Versuch hat die Rechenart beim Namen genannt "
    "– malnehmen, multiplizieren, addieren oder Ähnliches. Genau das ist auf "
    "dieser Stufe verboten. Du darfst sagen, DASS der Ansatz des Kindes nicht "
    "trägt und an welcher Stelle es nicht aufgeht. Welche Rechenart die "
    "richtige wäre, sagst du nicht. Schreibe die Hilfe noch einmal."
)

SCHAERFUNG_ZAHL = (
    "\n\nACHTUNG: Dein letzter Versuch enthielt eine Zahl, die weder in der "
    "Aufgabe noch in dem steht, was das Kind geschrieben hat. Das ist ein "
    "Zwischenergebnis oder das Ergebnis, und beides ist hier verboten. "
    "Schreibe die Hilfe noch einmal und verwende AUSSCHLIESSLICH die Zahlen, "
    "die schon dastehen."
)

SCHAERFUNG_METHODE = (
    "\n\nACHTUNG: Dein letzter Versuch hat gesagt, WAS zu tun ist – zählen, "
    "rechnen, malnehmen oder Ähnliches. Auf dieser Stufe ist das verboten. "
    "Schreibe die Hilfe noch einmal und erkläre nur die Situation: worum es "
    "geht, was die Wörter bedeuten, wer so etwas wissen möchte. Kein Wort "
    "darüber, was gerechnet oder gezählt werden soll."
)

SCHAERFUNG = (
    "\n\nACHTUNG: Dein letzter Versuch enthielt eine Rechnung oder ein "
    "Ergebnis. Das ist auf dieser Stufe verboten. Schreibe die Hilfe noch "
    "einmal, OHNE jede Zahl aus der Aufgabe miteinander zu verrechnen, ohne "
    "Gleichung, ohne Zwischenergebnis und ohne vorgezählte Zahlenreihe wie "
    "\"8, 16, 24\"."
)

SCHAERFUNG_WERKZEUG = (
    "\n\nACHTUNG: Dein letzter Versuch hat das Werkzeug beim Namen genannt – "
    "einen Satz, eine Formel, ein Verfahren. Das ist auf dieser Stufe "
    "verboten; es ist die Arbeit von Stufe 4. Schreibe die Hilfe noch einmal "
    "und sag nur, worum es geht oder welche Denkweise hilft, ohne Satz, "
    "Formel oder Verfahren zu nennen."
)

SCHAERFUNG_ZITAT = (
    "\n\nACHTUNG: Dein letzter Versuch hat dem Kind etwas in den Mund gelegt, "
    "das es nicht geschrieben hat (\"du hast gesagt\", \"du hast erkannt\"). "
    "Schreibe die Hilfe noch einmal und beziehe dich nur auf das, was das Kind "
    "wirklich geschrieben hat. Hat es noch nichts geschrieben, gibt es nichts "
    "zu zitieren."
)

SCHAERFUNG_LEHRPERSON = (
    "\n\nACHTUNG: Dein letzter Versuch hat etwas über die Lehrperson behauptet. "
    "Du weißt von ihr nur, was sie für diese Stunde eingestellt hat; sonst "
    "sagst du nichts über sie. Schreibe die Hilfe noch einmal ohne diese "
    "Behauptung."
)

SCHAERFUNG_RECHENZEICHEN = (
    "\n\nACHTUNG: Dein letzter Versuch hat eine Rechnung mit einem anderen "
    "Rechenzeichen genannt als das Kind. Sein Ergebnis ist geprüft richtig; "
    "bleib bei seiner Rechnung, genau so, wie es sie geschrieben hat."
)

SCHAERFUNG_SCHLEIFE = (
    "\n\nACHTUNG: Diese Frage hast du schon gestellt, und das Kind ist damit "
    "nicht weitergekommen. Stell eine ANDERE Frage: einen kleineren Schritt "
    "oder einen anderen Zugang, mit den Worten und Zahlen, die das Kind "
    "zuletzt geschrieben hat."
)

# Die Pruefung der Loesung, bevor sie das Kind sieht (Benchmark 19.10.2026,
# Aenderung 8: Stufe 5 war mit 1,56 die fachlich schwaechste Stufe).
SCHAERFUNG_LOESUNG_ABWEICHUNG = (
    "\n\nACHTUNG: Dein Ergebnis weicht von der geprüften Lösung ab, die oben "
    "unter NUR FÜR DICH steht. Rechne noch einmal, Schritt für Schritt, und "
    "nenne am Ende das Ergebnis, das sich daraus ergibt."
)

LOESUNG_PRUEFEN = (
    "Hier ist deine Lösung:\n\"{loesung}\"\n\n"
    "Prüfe sie durch Einsetzen oder Rückrechnen. Stimmt sie, gib sie "
    "unverändert wieder. Stimmt sie nicht, schreib die berichtigte Lösung in "
    "derselben Form: Schritt für Schritt, jeder Schritt ein Satz, am Ende "
    "das Ergebnis mit Einheit. Gib nur die Lösung aus, keinen Kommentar zur "
    "Prüfung."
)

NOTFALL = {
    1: ("Schau dir die Angabe noch einmal in Ruhe an. Was steht da alles drin, "
        "und was möchte jemand wohl wissen?"),
    2: ("Erzähl mir, wie du auf deinen Ansatz gekommen bist. Dann schauen wir "
        "gemeinsam, ob er trägt."),
    3: ("Frag dich: Was ist gegeben, und was ist gesucht? Manchmal hilft eine "
        "Skizze."),
    4: ("Überleg, welcher Schritt jetzt als Nächstes dran ist. Was musst du "
        "zuerst herausfinden?"),
}


# --- Die Schlussfrage ---------------------------------------------------------
#
# Zech, S. 289: Die Hilfe endet mit der Frage, die das Kind weiterbringt. Der
# Systemprompt bittet darum (levels.FRAGEREGEL); Lauf F (31.10.2026, Qwen3.6)
# hat gezeigt, was eine Bitte wert ist: 91 von 313 Zuegen ohne Frage, 48
# davon, weil die Kuerzung den Satz mit der Frage entfernt hatte. Seit Lauf G
# wird die Frage erzwungen: Endet der Zug ohne Fragezeichen, fasst der Server
# einmal nach (eine kurze Anfrage: nur die eine Frage), prueft sie wie die
# Hilfe und haengt sie an; taugt sie nicht, kommt die Vorlage der Stufe
# (levels.schlussfrage_vorlage).

# Lauf F2 (31.10.2026): Von 73 Nachfass-Antworten waren 30 keine Frage,
# sondern Anweisungen ("Prüfe, wie ..."). Deshalb: ein Fragewort am Anfang,
# ein Fragezeichen am Ende, sonst nichts.
NACHFASSEN_FRAGE = (
    "\n\nDeine Hilfe steht fest und bleibt, wie sie ist. Sie endet aber ohne "
    "Frage. Antworte jetzt mit GENAU EINEM Satz: der Frage, mit der die "
    "Arbeit an der Aufgabe weitergeht. Der Satz beginnt mit einem Fragewort "
    "(Was, Wie, Welche, Warum, Wo, Woran, Wozu) und endet mit einem "
    "Fragezeichen. Sie lässt dem Kind etwas zu überlegen und fragt nicht "
    "nur eine Zahl oder ein Wort ab. Keine Anweisung (\"Prüfe ...\", "
    "\"Überlege ...\"), keine Einleitung, keine Wiederholung der Hilfe. Es "
    "gilt weiter alles, was oben für diese Hilfe gilt.\n\nDeine Hilfe:\n{text}"
)

FRAGE_HOECHSTENS_WOERTER = 25

_SATZENDE = re.compile(r"(?<=[.!?])\s+")
_FRAGE_VORSPANN = re.compile(r"^\W*(?:schluss)?frage\s*:\s*", re.IGNORECASE)
_ANFUEHRUNG = "\"'„“‚‘»«()*"


def nachfassen_anfrage(frage, text):
    """Die Anfrage, mit der der Server die fehlende Schlussfrage holt.

    Die urspruengliche Anfrage, dazu die fertige Hilfe und die Bitte um die
    eine Frage. Der Systemprompt bleibt derselbe, damit dieselben Regeln
    gelten.
    """
    return frage + NACHFASSEN_FRAGE.format(text=(text or "").strip())


def endet_mit_frage(text):
    """Endet der Text mit einem Fragezeichen? Anfuehrungszeichen dahinter zaehlen nicht."""
    return (text or "").strip().rstrip(_ANFUEHRUNG).rstrip().endswith("?")


def ohne_nachsatz_zur_frage(text):
    """Steht die Frage im Text, aber nicht am Ende, fallen bis zu zwei Saetze dahinter weg.

    "Wie viele sind es? Probier es aus. Du schaffst das." wird zu "Wie viele
    sind es?". Folgen mehr als zwei Saetze, bleibt der Text, wie er ist:
    Dann war die Frage nicht der Schluss, sondern der Anfang, und der Rest
    ist die Hilfe. Ohne Frage bleibt er ebenfalls.
    """
    saetze = [s for s in _SATZENDE.split((text or "").strip()) if s]
    fragen = [i for i, s in enumerate(saetze) if s.rstrip(_ANFUEHRUNG).endswith("?")]
    if not fragen or fragen[-1] == len(saetze) - 1:
        return text
    if len(saetze) - 1 - fragen[-1] <= 2:
        return " ".join(saetze[:fragen[-1] + 1])
    return text


def frage_bereinigt(roh, stufe, hoechste_erlaubte, eigenes=None,
                    schulstufe=levels.VOLKSSCHULE, loesung="", bestaetigt=False):
    """Die eine Frage aus der Antwort auf das Nachfassen, oder leer.

    Genommen wird der eine Satz mit Fragezeichen; ein Vorspann wie "Frage:"
    und Anfuehrungszeichen fallen weg. Leer, wenn keine oder mehr als eine
    Frage drinsteht, wenn sie laenger als FRAGE_HOECHSTENS_WOERTER ist oder
    wenn sie auf der Stufe verstoesst (dieselbe Pruefung wie die Hilfe).
    """
    text = _FRAGE_VORSPANN.sub("", (roh or "").strip()).strip().strip(_ANFUEHRUNG).strip()
    saetze = [s.strip() for s in _SATZENDE.split(text) if s.strip()]
    fragen = [s.strip(_ANFUEHRUNG).strip() for s in saetze if s.rstrip(_ANFUEHRUNG).endswith("?")]
    if len(fragen) != 1:
        return ""
    frage = fragen[0]
    if len(frage.split()) > FRAGE_HOECHSTENS_WOERTER:
        return ""
    if verstoesse(frage, stufe, hoechste_erlaubte, eigenes, schulstufe, loesung,
                  bestaetigt=bestaetigt):
        return ""
    return frage


def mit_schlussfrage(text, frage):
    """Haengt die Schlussfrage an den Text."""
    text = (text or "").strip()
    return f"{text} {frage}".strip() if text else frage


# --- Erfundene Zitate, Behauptungen ueber die Lehrperson, Rechenzeichen ------
#
# Thomas' Stichprobe (31.10.2026): "Du hast gesagt, dass 14 Autos da sind",
# bevor das Kind ein Wort geschrieben hatte; "Du hast richtig erkannt, dass
# ... ein rechtwinkliges Dreieck", was das Kind nie sagte; "Die Lehrperson hat
# gesagt, dass du die Aufgabe nur loesen darfst, wenn du fragst", was in
# keiner Einstellung steht; und nach "72 minus 9" die Frage "Wie viel ist
# 72 · 9?". Das Modell darf nur zitieren, was das Kind geschrieben hat, ueber
# die Lehrperson nur sagen, was sie eingestellt hat, und eine geprueft
# richtige Rechnung nicht mit einem anderen Zeichen wiederholen.

# Lauf G: "Du hast die Punkte von Lea und die Gesamtpunktzahl notiert" (44
# Zeichen zwischen "du hast" und dem Verb) rutschte durch das Fenster von
# 40; "abgeschrieben", "berechnet ... bestimmt" fehlten als Verben.
_ZITAT_VERBEN = (
    "gesagt|geschrieben|erkannt|gemeint|herausgefunden|festgestellt|bemerkt|genannt|"
    "erwähnt|angegeben|notiert|gezeigt|vorgeschlagen|überlegt|gefragt|angemerkt|"
    "beschrieben|erklärt|begründet|gerechnet|berechnet|ausgerechnet|abgeschrieben|"
    "aufgeschrieben|aufgestellt|bestimmt|gebildet|eingesetzt|gelöst|gezeichnet|"
    "hergeleitet|sortiert|umgewandelt|addiert|subtrahiert|multipliziert|dividiert|"
    "geteilt|zusammengezählt|abgezogen|gezählt"
)
_ZITAT = re.compile(
    rf"\b(?:du hast|hast du|wie du)\b[^.!?]{{0,80}}?\b({_ZITAT_VERBEN})\b",
    re.IGNORECASE,
)
_WORT = re.compile(r"[a-zäöüß]{4,}", re.IGNORECASE)
# Funktionswoerter und die Zitatverben selbst: kein Inhalt, den man pruefen koennte.
_KEIN_INHALT = frozenset("""
    dass dann jetzt noch schon aber auch nicht wenn weil oder sind wird habe hast
    hatte sein eine einen einem einer eines dies diese dieser dieses hier dort dabei
    damit dafür denn doch ganz genau gerade immer mehr nach nämlich oben sehr sich
    über unter viel viele vielleicht vorher wieder zuerst richtig falsch also dein
    deine deinem deinen deiner mein meine ihre ihren welche welcher welches kann
    kannst muss musst soll sollst will willst darf darfst haben hattest warst bist
    werden wurde würde ergibt sagen schreiben erkennen gesagt geschrieben erkannt
    gemeint herausgefunden festgestellt bemerkt genannt erwähnt angegeben notiert
    gezeigt vorgeschlagen überlegt gefragt angemerkt beschrieben erklärt begründet
    gerechnet berechnet ausgerechnet schon bereits selbst ganz gut super prima
    abgeschrieben aufgeschrieben aufgestellt bestimmt gebildet eingesetzt gelöst
    gezeichnet hergeleitet sortiert umgewandelt addiert subtrahiert multipliziert
    dividiert geteilt zusammengezählt abgezogen gezählt
    zuletzt vorhin eben nämlich etwas nichts alles beide beiden damals dieses
    aufgibst aufgeben aufgegeben weiterweißt weiterweisst weiterkommst verstehst
    verstanden unsicher schwierig schwer ahnung keine mehr weiter nicht
""".split())


def _inhaltsstaemme(text):
    """Zahlen und Woerter ab vier Buchstaben, als grobe Staemme (die ersten fuenf Zeichen)."""
    staemme = set(_zahlen(text))
    for wort in _WORT.findall(text or ""):
        wort = wort.lower()
        if wort in _KEIN_INHALT:
            continue
        staemme.add(wort[:5] if len(wort) > 5 else wort)
    return staemme


_TEILSATZ = re.compile(r"\s*[,;:]\s*|\s+(?=(?:aber|doch|sondern|und dann|also)\b)", re.IGNORECASE)
_NEBENSATZ = re.compile(r"^(?:dass|wie|was|welche\w*|ob|wo|warum|wieso|weshalb)\b", re.IGNORECASE)


def _zitatteil(satz):
    """Der Teil des Satzes, der das Zitat traegt: der Teilsatz mit "du hast ..."
    und ein folgender Nebensatz ("dass ..."). Was danach kommt ("aber wir
    bleiben dran"), ist die Stimme des Tutors, kein Zitat."""
    teile = [t for t in _TEILSATZ.split(satz or "") if t and t.strip()]
    for i, teil in enumerate(teile):
        if _ZITAT.search(teil) or (i + 1 < len(teile) and _ZITAT.search(teil + ", " + teile[i + 1])):
            genommen = [teil]
            if i + 1 < len(teile) and (_NEBENSATZ.search(teile[i + 1].strip())
                                       or not _ZITAT.search(teil)):
                genommen.append(teile[i + 1])
            return " ".join(genommen)
    return satz or ""


def zitat_erfunden(satz, eigenes):
    """Legt der Satz dem Kind etwas in den Mund, das in keinem Beitrag steht?

    ``eigenes`` wie ueberall: zuerst die Angabe, dann die Beitraege des Kindes.
    Vor dem ersten Beitrag ist jedes Zitat erfunden; danach gilt es als
    gedeckt, sobald eine Zahl oder ein Inhaltswort des Satzes in einem
    Beitrag vorkommt. Das ist grob, faengt aber die Faelle der Stichprobe.
    Ein Satz ueber das Befinden des Kindes ("du hast gesagt, dass du
    aufgibst") hat keinen pruefbaren Inhalt und gilt (Lauf F3, vs10: das
    Kind hatte "ich geb auf" geschrieben).
    """
    if not _ZITAT.search(satz or ""):
        return False
    # Eine Frage behauptet nichts: "Was hast du dir schon ueberlegt?" ist die
    # Eroeffnung nach Thomas (1.11.2026), kein Zitat. Lauf G2 hatte sie
    # 16-mal als erfunden gestrichen.
    if (satz or "").strip().rstrip(_ANFUEHRUNG).rstrip().endswith("?"):
        return False
    beitraege = [b for b in list(eigenes or [])[1:] if (b or "").strip()]
    if not beitraege:
        return True
    inhalt = _inhaltsstaemme(_zitatteil(satz))
    if not inhalt:
        return False
    gedeckt = set()
    for beitrag in beitraege:
        gedeckt |= _inhaltsstaemme(beitrag)
    if inhalt & gedeckt:
        return False
    # "Du hast addiert" ist gedeckt, wenn das Kind ein Plus geschrieben hat:
    # Die Rechenart in jedem Wort zaehlt wie das Zeichen.
    klassen = _rechenarten_des_kindes(beitraege)
    return not any(klasse in klassen and muster.search(satz)
                   for klasse, muster in _RECHENART_WOERTER.items())


_LEHRPERSON = re.compile(r"\b(?:lehrer(?:in|innen)?|lehrperson(?:en)?|lehrkraft|lehrkräfte)\b",
                         re.IGNORECASE)
# Was das Modell ueber die Lehrperson sagen darf: ihre Einstellung, in
# jeder Formulierung (Lauf F3: "nur Tipps erlaubt", "untersagt", "Vorgabe").
_EINSTELLUNG = re.compile(r"eingestellt|einstellung|freigegeben|freigeschaltet|festgelegt|"
                          r"ausgewählt|gewählt|vorgabe|vorgegeben|untersagt|erlaubt|"
                          r"\btipps?\b|\bstufen?\b", re.IGNORECASE)
# Was es nicht darf: der Lehrperson eine Regel fuer das Kind in den Mund
# legen ("du darfst die Loesung nur bekommen, wenn du fragst").
_KINDERRECHT = re.compile(r"\bdu\s+(?:darfst|sollst|musst|kannst|bekommst|dürftest|solltest|"
                          r"müsstest)\b|\bdu die (?:lösung|aufgabe)\b|\bnur\s+\w+\s+darfst\b",
                          re.IGNORECASE)


def behauptung_ueber_lehrperson(satz, eigenes=None):
    """Legt der Satz der Lehrperson eine Regel fuer das Kind in den Mund?

    Erlaubt ist, ihre Einstellung zu nennen, in jeder Formulierung. Kommt
    eine Lehrerin in der Angabe selbst vor ("die Lehrerin hat 200 Euro"),
    ist sie eine Figur der Aufgabe, und der Satz wird nicht geprueft.
    """
    angabe = (list(eigenes or []) or [""])[0] or ""
    if _LEHRPERSON.search(angabe):
        return False
    satz = satz or ""
    if not _LEHRPERSON.search(satz) or _EINSTELLUNG.search(satz):
        return False
    return bool(_KINDERRECHT.search(satz))


def anderes_rechenzeichen(text, eigenes):
    """Nennt der Text eine Rechnung mit den Zahlen des Kindes, aber einem anderen Zeichen?

    Nur fuer die Bestaetigung sinnvoll: Dort ist die Rechnung des Kindes als
    richtig geprueft, und "72 · 9" nach "72 minus 9" ist Unfug (Zug 34 der
    Stichprobe). In einer Rueckmeldung dagegen darf Stufe 4 die richtige
    Rechenart nennen, wenn die des Kindes falsch war.
    """
    kind = {}
    for stueck in list(eigenes or [])[1:]:
        for a, op, b in _KIND_RECHNUNG.findall(stueck or ""):
            klasse = _OPERATOR_KLASSE.get(op.lower())
            if klasse:
                kind.setdefault((_zahl_normiert(a), _zahl_normiert(b)), set()).add(klasse)
    if not kind:
        return False
    for a, op, b in _KIND_RECHNUNG.findall(text or ""):
        klasse = _OPERATOR_KLASSE.get(op.lower())
        klassen = kind.get((_zahl_normiert(a), _zahl_normiert(b)))
        if klasse and klassen and klasse not in klassen:
            return True
    return False


# --- Die Rechnung des Kindes nachrechnen ---------------------------------------
#
# Zug 29 der Stichprobe: Das Kind rechnet die Summe 60 statt 70, der Tutor
# bestaetigt. Was sich deterministisch nachrechnen laesst (Zahlen, Brueche,
# die vier Grundrechenarten, Punkt vor Strich), wird nachgerechnet; die
# Diagnose darf ein Ergebnis, das so nicht stimmt, nicht "richtig" nennen.

_ZAHLTOKEN = r"-?\d+(?:[.,]\d+)?(?:/\d+)?"
_OPTOKEN = r"[+\-−–·*×:÷]|x(?=\s*\d)|plus|minus|mal|geteilt durch|durch"
# Vor der Kette darf keine Ziffer, kein Hochzeichen und kein Buchstabe stehen:
# "2^3 + 2 = 10" ist keine Kette "3 + 2" (Lauf F3, ma15: als Rechenfehler
# gemeldet), "x2 + 3 = 7" keine Kette "2 + 3". Hinter dem Ergebnis ebenso.
_RECHENKETTE = re.compile(
    rf"(?<![\d.,/^a-zA-Z_²³])({_ZAHLTOKEN}(?:\s*(?:{_OPTOKEN})\s*{_ZAHLTOKEN})+)\s*=\s*({_ZAHLTOKEN})"
    rf"(?!\d|[.,/]\d|\^|²|³|[a-zA-Z]|\s*(?:{_OPTOKEN})\s*\d)",
    re.IGNORECASE,
)
_KETTENTEIL = re.compile(rf"({_ZAHLTOKEN})|({_OPTOKEN})", re.IGNORECASE)

FalscheRechnung = collections.namedtuple("FalscheRechnung", "ausdruck genannt wahr")


def _bruch(roh):
    from fractions import Fraction
    roh = roh.replace(",", ".")
    if "/" in roh:
        zaehler, nenner = roh.split("/", 1)
        if Fraction(nenner) == 0:
            raise ZeroDivisionError
        return Fraction(zaehler) / Fraction(nenner)
    return Fraction(roh)


def _rechnen(ausdruck):
    """Wert einer Kette aus Zahlen und Grundrechenarten, Punkt vor Strich; None, wenn unklar."""
    teile = [t for t in _KETTENTEIL.findall(ausdruck) if t[0] or t[1]]
    zahlen = [t[0] for t in teile if t[0]]
    ops = [_OPERATOR_KLASSE.get(t[1].lower()) for t in teile if t[1]]
    if len(zahlen) != len(ops) + 1 or any(op is None for op in ops):
        return None
    try:
        werte = [_bruch(z) for z in zahlen]
        # Punkt vor Strich: erst mal und geteilt, von links nach rechts.
        w, o = [werte[0]], []
        for op, wert in zip(ops, werte[1:]):
            if op == "mal":
                w[-1] = w[-1] * wert
            elif op == "geteilt":
                w[-1] = w[-1] / wert
            else:
                w.append(wert)
                o.append(op)
        ergebnis = w[0]
        for op, wert in zip(o, w[1:]):
            ergebnis = ergebnis + wert if op == "plus" else ergebnis - wert
        return ergebnis
    except (ValueError, ZeroDivisionError, ArithmeticError):
        return None


def _als_text(wert):
    """70, 0,75 oder "etwa 8,57": so, wie es in einer Rueckmeldung stehen kann."""
    from fractions import Fraction
    if wert.denominator == 1:
        return str(wert.numerator)
    gerundet = f"{float(wert):.2f}".rstrip("0").rstrip(".")
    vorsatz = "" if Fraction(gerundet) == wert else "etwa "
    return vorsatz + gerundet.replace(".", ",")


def falsche_rechnungen(text):
    """Die Rechnungen des Kindes, deren genanntes Ergebnis nicht stimmt.

    Je Fund (Ausdruck, genanntes Ergebnis normiert, wahres Ergebnis als
    Text). Gerundet oder abgeschnitten gilt als richtig: "60 : 7 = 8,57" und
    "60 : 7 = 8" stimmen, "60 : 7 = 9,5" nicht. Was sich nicht sicher lesen
    laesst (Variablen, Hochzahlen, Ketten wie "7 + 5 = 12 + 3 = 15"), wird
    nicht beurteilt.
    """
    from fractions import Fraction
    funde = []
    for ausdruck, genannt in _RECHENKETTE.findall(text or ""):
        if re.search(r"[\^²³]|[a-zA-Z]\d|\d[a-zA-Z]", ausdruck):
            continue
        wahr = _rechnen(ausdruck)
        if wahr is None:
            continue
        try:
            wert = _bruch(genannt)
        except (ValueError, ZeroDivisionError):
            continue
        stellen = len(genannt.replace(",", ".").split(".")[1]) if "." in genannt.replace(",", ".") else 0
        # Gerundet oder abgeschnitten ist richtig, aber nur, wenn das wahre
        # Ergebnis keine ganze Zahl ist: "7 + 5 = 11" ist falsch.
        toleranz = (Fraction(1, 10 ** stellen)
                    if "/" not in genannt and wahr.denominator != 1 else Fraction(0))
        if abs(wahr - wert) <= toleranz:
            continue
        funde.append(FalscheRechnung(re.sub(r"\s+", " ", ausdruck.strip()),
                                     _zahl_normiert(genannt), _als_text(wahr)))
    return funde


def wiederholt_frage(text, fruehere):
    """Stellt der Text (fast) dieselbe Frage wie eine der frueheren?

    Zug 14 der Stichprobe: dreimal dieselbe Frage auf dieselbe Antwort.
    Gleich heisst: dieselben Woerter ab drei Buchstaben zu mindestens drei
    Vierteln (Jaccard), oder woertlich gleich.
    """
    frage = levels.letzte_frage(text)
    if not frage:
        return False
    neu = _frageworte(frage)
    for alt in fruehere or []:
        alt = (alt or "").strip()
        if not alt:
            continue
        if alt.lower() == frage.lower():
            return True
        worte = _frageworte(alt)
        if neu and worte and len(neu & worte) / len(neu | worte) >= 0.75:
            return True
    return False


def _frageworte(frage):
    return {w.lower() for w in re.findall(r"[a-zäöüß0-9]{3,}", frage or "", re.IGNORECASE)}


# --- Trichter-Indikator (Zech, Kap. 10.2, S. 285 und 288) -------------------
#
# Das reine Frage-Antwort-Spiel engt den Denkhorizont ein (S. 285; in der
# Literatur das "Trichtermuster" nach Bauersfeld). Zechs Negativbeispiel
# (S. 288): "Was fuer Winkel haben wir im Rechteck?" - "Rechte!". Eine
# Einsetzfrage laesst nur eine Zahl, ein Wort oder Ja/Nein einsetzen.
# Thomas (31.10.2026): Der Anteil solcher Folgefragen darf von D3 zu G nicht
# steigen. Das hier ist ein Indikator fuer die Auswertung, keine Pruefung:
# Er greift nirgends ein.
_EINSETZ_VORSPANN = re.compile(r"^(?:und|also|dann|jetzt|na|nun|so|gut)[,:]?\s+", re.IGNORECASE)
# Ein Vorsatz vor dem Fragewort ("Wenn du 18 Kinder aufteilst, wie viele
# Gruppen ...?", "Schau auf die Differenz: was ist ...?") zaehlt nicht;
# genommen wird der Teil ab dem letzten Fragewort nach Komma oder Strich.
_EINSETZ_FRAGEWORT = (
    r"wie|was|welche\w*|wo|warum|wieso|weshalb|woran|wozu|womit|wann"
    r"|ist|sind|hast|hat|kannst|könntest|koenntest|stimmt|passt|weißt|weisst|musst|darfst"
)
_EINSETZ_VORSATZ = re.compile(rf"[,;:–-]\s+(?=(?:{_EINSETZ_FRAGEWORT})\b)", re.IGNORECASE)
_ZAHLWORT = (
    r"ergebnis|summe|differenz|produkt|quotient|rest|werte?|umfang|fläche|flaeche|volumen"
    r"|preis|antwort|lösung|loesung|hälfte|haelfte|doppelte|dreifache|anzahl|länge|laenge"
    r"|breite|höhe|hoehe|gewicht|dauer|zeit|strecke|geschwindigkeit|temperatur|note"
    r"|durchschnitt|mittelwert|prozentsatz|anteil|betrag|wahrscheinlichkeit|zahl|zahlen"
)
_EINSETZ_ZAHL = re.compile(
    rf"^(?:wie ?viele?\b"
    rf"|wie (?:groß|gross|lang|hoch|breit|schwer|weit|alt|teuer|schnell|tief|dick|oft)\b"
    rf"|was (?:ergibt|bleibt|kostet|wiegt|misst)\b"
    rf"|was kommt\b.*\b(?:heraus|raus)\b"
    rf"|wie lautet (?:das|der|die|den)\s+(?:{_ZAHLWORT})\b"
    rf"|welche[rsn]? (?:\w+ )?(?:{_ZAHLWORT})\b"
    rf"|was (?:ist|sind|wäre|waere|macht|gibt|wird)\s+(?:\d|(?:das|die|der|den|dem)\s+(?:\w+ )?(?:{_ZAHLWORT})\b))",
    re.IGNORECASE,
)
_EINSETZ_WORT = re.compile(
    r"^(?:wie (?:heißt|heisst|nennt man)\b|was f(?:ü|ue)r\b"
    r"|welche[rsn]? (?:rechenart|rechenzeichen|operation|einheit|form|figur|seite|zeichen)\b)",
    re.IGNORECASE,
)
_EINSETZ_JANEIN = re.compile(
    r"^(?:ist|sind|war|hast|hat|habt|kannst|kann|könntest|koenntest|könnte|koennte"
    r"|passt|stimmt|brauchst|braucht|weißt|weisst|musst|muss|darfst|darf|geht|gibt es"
    r"|soll|sollst|willst|möchtest|moechtest|bist|wäre|waere|würde|wuerde|würdest"
    r"|wuerdest|reicht|fehlt|klappt|hilft|magst|schaffst|bleibt|siehst|erkennst"
    r"|findest|glaubst|meinst|denkst)\b",
    re.IGNORECASE,
)
_EINGEBETTETE_FRAGE = re.compile(
    r",\s*(?:wo|wie|was|welche\w*|warum|wieso|weshalb|woran|wozu|womit|wann)\b",
    re.IGNORECASE,
)


def einsetzfrage(frage):
    """Laesst die Frage nur eine Zahl, ein Wort oder Ja/Nein einsetzen?

    "zahl" ("Wie viele sind es?", "Was ergibt 6 · 8?"), "wort" ("Welche
    Rechenart passt?", "Was fuer Winkel hat ein Rechteck?"), "janein"
    ("Stimmt das?"), sonst leer. Eine Ja-Nein-Frage mit eingebetteter Frage
    ("Siehst du, warum das nicht aufgehen kann?") ist offen. Grob, aber in
    beide Richtungen gleich grob, damit D3 und G vergleichbar sind.
    """
    frage = (frage or "").strip().strip(_ANFUEHRUNG).strip()
    if not frage.endswith("?"):
        return ""
    frage = _EINSETZ_VORSPANN.sub("", frage)
    vorsaetze = list(_EINSETZ_VORSATZ.finditer(frage))
    if vorsaetze:
        frage = frage[vorsaetze[-1].end():]
    if _EINSETZ_ZAHL.search(frage):
        return "zahl"
    if _EINSETZ_WORT.search(frage):
        return "wort"
    if _EINSETZ_JANEIN.search(frage) and not _EINGEBETTETE_FRAGE.search(frage):
        return "janein"
    return ""
