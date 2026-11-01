"""Ein Trainer für alles: die Zustandsfolge und die Prompts dazu.

Der Gegenentwurf zur Aufgabenhilfe. Dort bringt jemand eine Aufgabe mit und
die Anwendung haelt die Loesung zurueck. Hier fehlt ein Thema, und der
Trainer erklaert es - vollstaendig und gern mehrfach. Die einzige
Zurueckhaltung betrifft die Pruefaufgaben: Dort wartet er auf die Antwort,
statt sie vorwegzunehmen.

DREI ENTSCHEIDUNGEN, DIE DEN UNTERSCHIED ZWISCHEN TRAINER UND PLAUDERER
AUSMACHEN:

1. Die Anwendung fuehrt die Zustandsfolge, nicht das Modell. Deshalb zwei
   Aufrufe je Zug: Erst urteilt das Modell ueber die Antwort, kurz und
   billig. Dann entscheidet diese Datei ueber den naechsten Zustand und die
   Darstellungsebene. Erst danach formuliert das Modell.

   In einem einzigen Aufruf laesst sich das nicht haben: Das Urteil ueber
   die eben gegebene Antwort kommt mit der Antwort des Modells zurueck, die
   Entscheidung muesste also vorher fallen. Der Trainer haette eine Runde zu
   spaet gemerkt, dass jemand nicht mitkommt.

2. Genau eine Frage je Zug. Der haeufigste Fehler von Sprachmodellen als
   Tutor ist, drei Fragen auf einmal zu stellen. Wer drei Fragen bekommt,
   beantwortet keine. Die Regel steht im Prompt, und weil ein Prompt eine
   Bitte ist, schneidet eine_frage() die zweite ab.

3. Bei einem Fehler wird die Darstellung gewechselt, nicht die Erklaerung
   wiederholt. Erst gegenstaendlich, dann bildlich, dann symbolisch. Welcher
   Zugang schon versucht wurde, fuehrt der Lauf mit.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# --- Die Zustaende --------------------------------------------------------

THEMA = "thema"
BESTAETIGEN = "bestaetigen"
EINFUEHRUNG = "einfuehrung"
LERNSCHRITT = "lernschritt"
PRUEFUNG = "pruefung"
ABSCHLUSS = "abschluss"

ZUSTAENDE = (
    (THEMA, "Thema nennen"),
    (BESTAETIGEN, "Thema bestätigen"),
    (EINFUEHRUNG, "Einführung"),
    (LERNSCHRITT, "Lernschritt"),
    (PRUEFUNG, "Prüfaufgaben"),
    (ABSCHLUSS, "Abschluss"),
)

ZUSTAND_TEXT = {
    THEMA: "Sag mir, was du lernen möchtest.",
    BESTAETIGEN: "Passt das so?",
    EINFUEHRUNG: "Worum es geht",
    LERNSCHRITT: "Schritt für Schritt",
    PRUEFUNG: "Jetzt du: Aufgaben",
    ABSCHLUSS: "Das hast du geschafft",
}

# --- Die Darstellungsebenen ----------------------------------------------
#
# Nach Bruner: enaktiv, ikonisch, symbolisch. Wer etwas symbolisch nicht
# versteht, versteht es durch dieselben Symbole in anderen Worten auch nicht.
# Der Trainer geht deshalb eine Ebene zurueck, nicht eine Runde weiter.

GEGENSTAENDLICH = "gegenstaendlich"
BILDLICH = "bildlich"
SYMBOLISCH = "symbolisch"

DARSTELLUNGEN = (
    (GEGENSTAENDLICH, "gegenständlich"),
    (BILDLICH, "bildlich"),
    (SYMBOLISCH, "symbolisch"),
)

DARSTELLUNG_ANWEISUNG = {
    GEGENSTAENDLICH: (
        "Erkläre GEGENSTÄNDLICH: an etwas, das man anfassen, sehen oder mit "
        "dem eigenen Körper erfahren kann. Ein Meterband, die eigene "
        "Körpergröße, Schritte auf dem Gang, Wasser in Bechern. Keine "
        "Tabelle, keine Formel."
    ),
    BILDLICH: (
        "Erkläre BILDLICH: mit einer Vorstellung, die man vor sich sieht. "
        "Eine Stellenwerttafel, ein Zahlenstrahl, eine Skizze in Worten, ein "
        "Vergleich. Noch keine Formel."
    ),
    SYMBOLISCH: (
        "Erkläre SYMBOLISCH: mit Zahlen, Zeichen und der Regel selbst. Jetzt "
        "darf die Umrechnungszahl oder die Formel dastehen."
    ),
}

# Wer im Symbolischen scheitert, geht ins Bildliche, dann ins
# Gegenstaendliche. Weiter zurueck geht es nicht.
ZURUECK = {
    SYMBOLISCH: BILDLICH,
    BILDLICH: GEGENSTAENDLICH,
    GEGENSTAENDLICH: GEGENSTAENDLICH,
}

# Und vorwaerts, wenn es sitzt.
VORWAERTS = {
    GEGENSTAENDLICH: BILDLICH,
    BILDLICH: SYMBOLISCH,
    SYMBOLISCH: SYMBOLISCH,
}

# --- Die Urteile ----------------------------------------------------------

VERSTANDEN = "verstanden"
TEILWEISE = "teilweise"
NICHT = "nicht"
URTEILE = (
    (VERSTANDEN, "verstanden"),
    (TEILWEISE, "teilweise"),
    (NICHT, "nicht verstanden"),
)

# Wie viele Lernschritte, bevor geprueft wird, und wie viele Pruefaufgaben.
SCHRITTE_BIS_PRUEFUNG = 4
PRUEFAUFGABEN = 4
# So oft darf dieselbe Sache neu erklaert werden, bevor es weitergeht. Wer
# viermal dieselbe Huerde bekommt, hoert auf.
HOECHSTE_SCHLEIFEN = 3


# --- Der Urteilsprompt ----------------------------------------------------

URTEIL_PROMPT = (
    "Du beurteilst eine einzige Antwort einer lernenden Person auf eine "
    "Frage. Du unterrichtest nicht, du erklärst nichts, und du beantwortest "
    "die Frage nicht.\n"
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form, "
    "ohne Einleitung und ohne Codeblock:\n"
    '{"urteil": "verstanden", "fehlertyp": ""}\n'
    'Das Feld "urteil" ist "verstanden", "teilweise" oder "nicht".\n'
    'Das Feld "fehlertyp" nennt in zwei bis vier Wörtern, woran es gehapert '
    "hat, oder bleibt leer.\n"
    'Urteile ehrlich und streng. Ein freundliches "verstanden" auf eine '
    'falsche Antwort schadet mehr als ein klares "nicht". Eine ausweichende '
    'Antwort wie "weiß nicht" ist "nicht".'
)

URTEIL_FRAGE = (
    "Die Frage lautete:\n{frage}\n\n"
    "Die Antwort der lernenden Person lautet:\n{antwort}"
)


# --- Der Antwortprompt ----------------------------------------------------

GRUNDHALTUNG = (
    "Du bist ein geduldiger Nachhilfelehrer und arbeitest mit {gegenueber}.\n"
    "{sprache}\n"
    "\n"
    "UNUMSTÖSSLICHE REGELN:\n"
    "1. Stelle GENAU EINE Frage. Nicht zwei, nicht drei. Alles, was du "
    "sagst, läuft auf diese eine Frage zu.\n"
    "1a. Die Frage steht AUSSCHLIESSLICH im Feld \"frage\". Im Feld "
    "\"text\" darf kein Fragezeichen vorkommen.\n"
    "2. Fasse dich kurz: höchstens vier Sätze vor der Frage. Ein Absatz, "
    "keine Aufzählung, keine Überschriften.\n"
    "3. Beantworte deine eigene Frage NICHT. Wenn du fragst, wie viele "
    "Zentimeter drei Meter sind, dann darf die Zahl dreihundert in deinem "
    "Text nicht vorkommen - weder als Ziffer noch als Wort.\n"
    "4. Schreibe das Malzeichen als schwebenden Punkt, also 6 · 8, niemals "
    "als x oder *. Das Geteiltzeichen als :.\n"
    "5. Rechne jede Zahl nach, die du nennst.\n"
    "\n"
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form, "
    "ohne Einleitung, ohne Kommentar und ohne Codeblock:\n"
    '{{"text": "dein Text ohne die Frage", "frage": "deine eine Frage"}}'
)

ANWEISUNG = {
    BESTAETIGEN: (
        "Die lernende Person hat ein Thema genannt. Sag in EINEM Satz, was du "
        "verstanden hast, und frag, ob das so passt. Fang noch nicht an zu "
        "erklären. Ist das Thema unklar, frag genauer nach."
    ),
    EINFUEHRUNG: (
        "Gib eine kurze Einführung in das Thema: zwei bis vier Sätze, kein "
        "Vortrag. Sag, worum es geht und wozu man das braucht. Ende mit einer "
        "Frage, die an das anknüpft, was die lernende Person schon weiß."
    ),
    LERNSCHRITT: (
        "Mach EINEN kleinen Lernschritt. Bau auf dem auf, was bisher dastand, "
        "und bring genau eine neue Sache dazu. Ende mit einer Frage, die "
        "zeigt, ob dieser eine Schritt angekommen ist. Sie muss beantwortbar "
        "sein, ohne dass jemand etwas nachschlägt."
    ),
    PRUEFUNG: (
        "Stell jetzt eine Aufgabe zum Thema. Keine Erklärung davor, nur die "
        "Aufgabe. Sie soll etwas schwerer sein als die vorige. Verrate die "
        "Lösung NICHT und rechne sie nicht vor: Hier wartest du auf die "
        "Antwort.\n"
        'Das Feld "text" bleibt leer oder enthält höchstens einen kurzen '
        'Übergangssatz. Die Aufgabe gehört in "frage".'
    ),
    ABSCHLUSS: (
        "Schließ ab. Sag in drei bis vier Sätzen, was sitzt und was noch "
        "nicht, und nenne eine konkrete Sache zum Weiterüben.\n"
        'Das Feld "frage" bleibt LEER: Es ist vorbei, du fragst nichts mehr.'
    ),
}

SCHLEIFE_ZUSATZ = (
    "ACHTUNG: Das war nicht richtig oder nur halb. Erkläre die Sache NEU. "
    "Sag sie NICHT noch einmal mit anderen Worten, sondern wechsle die "
    "Darstellung.\n"
    "{anweisung}\n"
    "Diese Zugänge hast du schon versucht: {versucht}. Nimm einen anderen.\n"
    "Mach den Schritt kleiner als vorher und ende wieder mit genau einer "
    "Frage."
)

# Das allgemeine Verbot allein reicht nicht: Im ersten vollstaendigen
# Durchlauf stand dreimal fast derselbe Satz vom Meterband mit den hundert
# Strichen. Der eigene Satz, woertlich zitiert, ist ungleich staerker als
# die Aufforderung, sich nicht zu wiederholen.
# Und was die lernende Person gerade wirklich gesagt hat. Ohne das mischt
# sich das Modell aus dem Verlauf zusammen, was ihm passt: Im Durchlauf
# stand dreimal "Du hast gesagt, dass du weisst, wie viele Zentimeter in
# einem Meter sind" - nachdem das Kind dreimal geschrieben hatte, dass es
# nichts versteht.
GESAGT_ZUSATZ = (
    "Das hat die lernende Person gerade geantwortet:\n"
    "\"{beitrag}\"\n"
    "Beziehe dich genau darauf. Behaupte NICHT, sie hätte etwas verstanden "
    "oder gesagt, was sie nicht gesagt hat."
)

SCHON_GESAGT_ZUSATZ = (
    "Das hast du zuletzt gesagt:\n\"{letzter}\"\n"
    "Diese Formulierung und dieses Bild sind jetzt verbraucht. Verwende "
    "beides NICHT noch einmal, auch nicht abgewandelt. Nimm ein anderes "
    "Beispiel, ein anderes Bild, einen anderen Einstieg."
)

FEHLER_ZUSATZ = "Woran es zuletzt gehapert hat: {fehlertyp}. Geh genau darauf ein."


def system_prompt(zustand, anrede, darstellung=GEGENSTAENDLICH, schleife=False,
                  versucht=(), fehlertyp="", letzter="", beitrag=""):
    """Baut den Systemprompt fuer genau einen Zug.

    `anrede` ist das Woerterbuch aus levels.anrede(): So sprechen Trainer und
    Aufgabenhilfe dieselbe Sprachebene je Altersklasse.
    """
    teile = [
        GRUNDHALTUNG.format(
            gegenueber=anrede["gegenueber"], sprache=anrede["sprache"]
        ),
        ANWEISUNG.get(zustand, ANWEISUNG[LERNSCHRITT]),
    ]

    if schleife:
        namen = ", ".join(dict(DARSTELLUNGEN).get(v, v) for v in versucht)
        teile.append(SCHLEIFE_ZUSATZ.format(
            anweisung=DARSTELLUNG_ANWEISUNG[darstellung],
            versucht=namen or "noch keiner",
        ))
        if letzter:
            teile.append(SCHON_GESAGT_ZUSATZ.format(letzter=letzter.strip()[:400]))
        if beitrag:
            teile.append(GESAGT_ZUSATZ.format(beitrag=beitrag.strip()[:300]))
    elif zustand in (EINFUEHRUNG, LERNSCHRITT):
        teile.append(DARSTELLUNG_ANWEISUNG[darstellung])

    if fehlertyp:
        teile.append(FEHLER_ZUSATZ.format(fehlertyp=fehlertyp))

    return "\n\n".join(teile)


# --- Die Antworten des Modells lesen -------------------------------------

_LESER = json.JSONDecoder()


def _objekt(roh):
    """Schaelt das ERSTE JSON-Objekt aus der Antwort, oder None.

    Modelle verpacken JSON gern in einen Codeblock oder schreiben einen Satz
    davor. Beides wird weggeschnitten.

    Das erste und nicht das groesstmoegliche: Vorher stand hier ein Muster
    von der ersten Klammer bis zur letzten. Als das Modell sein Objekt
    sechsmal hintereinander ausgab - ein Ausrutscher, der vorkommt - umfasste
    der Treffer alle sechs, war damit kein gueltiges JSON mehr, und die
    Notbremse gab den ganzen Rohtext aus. Auf dem Bildschirm eines Kindes
    stand sechsmal ein JSON-Objekt.

    raw_decode liest genau ein Objekt und sagt, wo es endet. Was danach
    kommt, ist uninteressant.
    """
    text = (roh or "").strip()
    start = text.find("{")
    while start != -1:
        try:
            daten, _ = _LESER.raw_decode(text[start:])
        except json.JSONDecodeError:
            # Diese Klammer war ein Fehlstart, die naechste versuchen.
            start = text.find("{", start + 1)
            continue
        return daten if isinstance(daten, dict) else None
    return None


def _notfalltext(roh):
    """Rettet den Trainertext, wenn das JSON nicht zu lesen war.

    Vor allem: Rohes JSON darf NIE auf dem Bildschirm landen. Lieber ein
    Zug ohne Frage als geschweifte Klammern vor Publikum.
    """
    text = (roh or "").strip()
    if "{" not in text and '"text"' not in text:
        return text
    # Den Wert des ersten text-Feldes herausholen, auch aus kaputtem JSON.
    treffer = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if treffer:
        try:
            return json.loads('"' + treffer.group(1) + '"').strip()
        except json.JSONDecodeError:
            return treffer.group(1).strip()
    logger.warning("Trainerantwort unlesbar, es gab kein JSON und keinen Text.")
    return ""


def urteil_lesen(roh):
    """Liest das Urteil aus einer Urteilsantwort.

    Kommt nichts Lesbares zurueck, gilt "teilweise". Das ist die
    Einschaetzung, die am wenigsten Schaden anrichtet: Sie schiebt niemanden
    weiter, der nicht mitkommt, und haelt niemanden auf, der es verstanden
    hat - beim naechsten Zug wird ohnehin neu geurteilt.
    """
    daten = _objekt(roh)
    if daten is None:
        logger.warning("Urteil war kein JSON, gilt als 'teilweise'.")
        return {"urteil": TEILWEISE, "fehlertyp": ""}

    urteil = str(daten.get("urteil", "")).strip().lower()
    if urteil not in dict(URTEILE):
        urteil = TEILWEISE
    return {
        "urteil": urteil,
        "fehlertyp": str(daten.get("fehlertyp", "")).strip()[:60],
    }


def antwort_lesen(roh):
    """Liest Text und Frage aus der Antwort des Modells.

    Kommt kein JSON zurueck, gilt der ganze Text als Trainertext ohne Frage.
    Lieber ein Zug ohne Frage als eine Ausnahme vor Publikum.
    """
    daten = _objekt(roh)
    if daten is not None:
        return {
            "text": str(daten.get("text", "")).strip(),
            "frage": str(daten.get("frage", "")).strip(),
        }

    logger.warning("Trainerantwort war kein JSON, Text wird gerettet.")
    return {"text": _notfalltext(roh), "frage": ""}


def ohne_frage(text, frage):
    """Schneidet Fragen aus dem Erklaertext, wenn die Frage schon dasteht.

    Anlass: Das Modell stellte seine Frage am Ende des Erklaertextes UND im
    Fragefeld. Auf dem Bildschirm standen dann zwei Fragen, und wer zwei
    Fragen bekommt, beantwortet keine.

    Nur wenn eine Frage im Fragefeld steht: Sonst bliebe ein Zug ohne jede
    Frage uebrig, und das waere schlimmer.
    """
    roh = (text or "").strip()
    if not roh or not (frage or "").strip():
        return roh

    saetze = re.split(r"(?<=[.!?])\s+", roh)
    behalten = [s for s in saetze if not s.rstrip().endswith("?")]
    gekuerzt = " ".join(behalten).strip()
    # Bleibt nichts uebrig, war der ganze Text die Frage. Dann ist das
    # Fragefeld die Frage und der Text entfaellt.
    return gekuerzt


def eine_frage(frage):
    """Kuerzt auf die erste Frage.

    Die Regel steht im Prompt, und ein Prompt ist eine Bitte. Wer zwei Fragen
    stellt, ueberfordert; also faellt die zweite hier weg.
    """
    text = (frage or "").strip()
    if not text:
        return ""
    ende = text.find("?")
    if ende == -1:
        return text
    return text[:ende + 1].strip()


# --- Die Zustandsfolge ----------------------------------------------------

def naechster_zustand(lauf, urteil):
    """Wohin geht es nach diesem Zug?

    Hier fuehrt die Anwendung. Das Modell liefert ein Urteil, entschieden
    wird an dieser Stelle - und zwar mit dem Urteil ueber die Antwort, die
    gerade gekommen ist, nicht mit dem vom letzten Mal.

    Gibt (zustand, darstellung, schleife) zurueck.
    """
    zustand = lauf.zustand
    darstellung = lauf.darstellung

    if zustand == THEMA:
        return BESTAETIGEN, darstellung, False

    if zustand == BESTAETIGEN:
        # Bestaetigt wird durch Antworten. Wer widerspricht, wird vom Trainer
        # selbst zurueckgefragt; der Zustand geht trotzdem weiter, weil die
        # Einfuehrung ohnehin mit einer Frage endet.
        return EINFUEHRUNG, GEGENSTAENDLICH, False

    if zustand == EINFUEHRUNG:
        return LERNSCHRITT, darstellung, urteil == NICHT

    if zustand == LERNSCHRITT:
        if urteil in (NICHT, TEILWEISE) and lauf.schleifen < HOECHSTE_SCHLEIFEN:
            zurueck = ZURUECK[darstellung] if urteil == NICHT else darstellung
            return LERNSCHRITT, zurueck, True
        if lauf.schritt_nr >= SCHRITTE_BIS_PRUEFUNG:
            return PRUEFUNG, darstellung, False
        return LERNSCHRITT, VORWAERTS[darstellung], False

    if zustand == PRUEFUNG:
        if urteil == NICHT and lauf.schleifen < HOECHSTE_SCHLEIFEN:
            # Zurueck in die Erklaerung, dann wird erneut geprueft.
            return LERNSCHRITT, ZURUECK[darstellung], True
        if lauf.aufgaben_gestellt >= PRUEFAUFGABEN:
            return ABSCHLUSS, darstellung, False
        return PRUEFUNG, darstellung, False

    return ABSCHLUSS, darstellung, False
