"""Der Sprechcoach: ein Gespraechspartner in der Zielsprache.

Die dritte Betriebsart, und die erste, in der es ums Sprechen geht. Die
Lehrperson gibt Thema, Sprache und Niveau vor; der Spark unterhaelt sich in
dieser Sprache, mit dem Wortschatz des Niveaus.

WAS IHN VON DEN ANDEREN BEIDEN UNTERSCHEIDET

Die Aufgabenhilfe haelt zurueck, der Trainer erklaert - beide arbeiten auf
ein Ergebnis hin. Der Sprechcoach hat kein Ergebnis. Er fuehrt ein Gespraech,
und ein Gespraech ist gelungen, wenn es weitergeht.

Daraus folgt die wichtigste Regel: Er korrigiert nicht wie ein Lehrer,
sondern wiederholt eine Wendung nebenbei richtig. Wer beim dritten Wort
unterbrochen wird, hoert auf zu sprechen.

WAS DIE ANWENDUNG DURCHSETZT, NICHT DER PROMPT

Zwei Dinge, und beide aus demselben Grund wie die Ausgangspruefung der
Aufgabenhilfe: Ein Systemprompt ist eine Bitte.

1. Die Satzlaenge. "Sprich einfach" ist eine Bitte; hoechstens acht Woerter
   je Satz ist eine Grenze. Zu lange Antworten werden ein zweites Mal
   geholt, danach gekuerzt.
2. Die Sprache. Ein Modell, das auf Englisch antworten soll, rutscht ins
   Deutsche, sobald das Kind deutsch schreibt. Dann steht da ein deutscher
   Satz, und die Stunde ist ihren Zweck los.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# --- Die Sprachen ---------------------------------------------------------
#
# Der Code ist BCP-47, weil ihn die Sprachausgabe des Browsers und das
# lang-Attribut genau so brauchen. Whisper bekommt nur den vorderen Teil.

SPRACHEN = (
    ("en-GB", "Englisch"),
    ("fr-FR", "Französisch"),
    ("it-IT", "Italienisch"),
    ("es-ES", "Spanisch"),
)

SPRACHE_STANDARD = "en-GB"

# Wie die Sprache im Prompt heisst. Das Modell antwortet verlaesslicher,
# wenn die Sprache in der Sprache selbst benannt ist.
EIGENNAME = {
    "en-GB": "English",
    "fr-FR": "français",
    "it-IT": "italiano",
    "es-ES": "español",
}


def whisper_code(sprache):
    """Whisper will den zweibuchstabigen Code, nicht die Region."""
    return (sprache or SPRACHE_STANDARD).split("-")[0]


def sprache_name(code):
    return dict(SPRACHEN).get(code, "Englisch")


# --- Die Niveaus ----------------------------------------------------------
#
# Nach dem Gemeinsamen Europaeischen Referenzrahmen. Die Wortzahl je Satz ist
# keine Vorgabe des Referenzrahmens, sondern unsere Uebersetzung davon in
# etwas, das sich pruefen laesst.

NIVEAUS = (
    ("A1", "A1 – erste Wörter"),
    ("A2", "A2 – einfache Sätze"),
    ("B1", "B1 – zusammenhängend sprechen"),
    ("B2", "B2 – frei sprechen"),
)

NIVEAU_STANDARD = "A1"

# Hoechstens so viele Woerter in einem Satz. Darueber wird nachgeschaerft.
WOERTER_JE_SATZ = {"A1": 8, "A2": 12, "B1": 16, "B2": 25}

# Und hoechstens so viele Saetze je Zug: Wer einen Vortrag bekommt,
# antwortet nicht.
SAETZE_JE_ZUG = {"A1": 2, "A2": 3, "B1": 3, "B2": 4}

# Je Niveau: Satzlaenge, Wortschatz, und WIE angeknuepft wird. Aus dem
# Niveauprofil der Recherche (CEFR-Deskriptoren fuer Spoken Interaction).
NIVEAU_ANWEISUNG = {
    "A1": (
        "Allererste Schritte. Nur die häufigsten Wörter. Nur Präsens. "
        "Höchstens ACHT Wörter in einem Satz, EIN Satz plus Frage. Keine "
        "Nebensätze. Das Gegenüber ist ganz auf dich angewiesen: Wiederhole "
        "langsam, formuliere um, frag mit zwei Möglichkeiten (\"A dog or a "
        "cat?\") oder greif ein Wort mit Fragezeichen auf (\"Football?\"), "
        "und erweitere dann sofort (\"Why?\", \"With whom?\"). Themen aus dem "
        "Alltag: Tiere, Essen, Familie, Schule, Spiele. Ein deutsches Wort "
        "nimmst du an, sagst es auf {eigenname} vor und machst weiter."
    ),
    "A2": (
        "Einfache Sätze über Vertrautes. Vergangenheit ist erlaubt, wenn sie "
        "einfach bleibt. Höchstens ZWÖLF Wörter in einem Satz, ein bis zwei "
        "Sätze plus Frage. Du hältst das Gespräch in Gang: Frag nach "
        "Gewohnheiten, Plänen und Erlebnissen (\"What did you do then?\", "
        "\"Tell me more\", \"Why?\"). Ein neues Wort bietest du kurz an und "
        "fragst es später noch einmal ab."
    ),
    "B1": (
        "Zusammenhängendes Sprechen über Vertrautes. Höchstens SECHZEHN "
        "Wörter in einem Satz, zwei Sätze plus Frage. Verlang Meinung und "
        "Begründung (\"What do you think?\", \"Why?\", \"Would you rather "
        "…?\"), sag mit eigenen Worten, was du verstanden hast, und frag, ob "
        "es stimmt. Du darfst eine eigene Meinung als Anstoß geben. Keine "
        "seltenen Wörter, keine Redewendungen, die man nicht erraten kann."
    ),
    "B2": (
        "Flüssiges Gespräch mit normaler Umgangssprache und gängigen "
        "Redewendungen. Du darfst widersprechen, eine Gegenposition "
        "vertreten und Argumente einfordern (\"Is that always true?\", "
        "\"What if …?\"). Dein Beitrag darf argumentieren, bleibt aber kürzer "
        "als der des Gegenübers. Halte die Sätze sprechbar."
    ),
}


def niveau_name(code):
    # Der Vorgabewert wird in Python IMMER ausgewertet, auch wenn der
    # Schluessel da ist. Hier stand dict(NIVEAUS)[0], und das warf bei jedem
    # Aufruf einen KeyError - auch bei einem gueltigen Niveau.
    return dict(NIVEAUS).get(code) or NIVEAUS[0][1]


# --- Der Prompt -----------------------------------------------------------

# Der dritte Zug entscheidet. Aus der Recherche vom 11.10.2026 (docs/
# Gespraechsdidaktik Englisch fuer den Sprechcoach.md): Das Muster "I like X
# too. What ...?" ist Bestaetigung plus Themenwechsel - der klassische
# unproduktive Zug. Lernwirksam ist der Partner, der ANKNUEPFT (expand, why,
# revoice, challenge), Fragen stellt, deren Antwort er nicht kennt, kurz
# bleibt, nachfragt statt zu loben, und ein fehlendes Wort einfuettert.
# Alles, was sich zaehlen laesst, prueft der Server (verstoesse); hier steht
# die Bitte, dort die Grenze.
GRUNDHALTUNG = (
    "Du bist ein Gesprächspartner und sprichst {eigenname} mit "
    "{gegenueber}. Du bist kein Lehrer und kein Prüfer: Du bist jemand, der "
    "sich wirklich für das interessiert, was gesagt wird.\n"
    "Das Thema ist: {thema}\n"
    "\n"
    "{niveau}\n"
    "\n"
    "SO FÜHRST DU DAS GESPRÄCH:\n"
    "1. KNÜPF AN. Dein Zug baut auf dem auf, was gerade gesagt wurde. Greif "
    "ein Wort oder einen Gedanken daraus auf und führ ihn weiter: Bitte um "
    "mehr (\"Tell me more about …\"), um ein Beispiel, um den Grund (\"Why "
    "…?\"), um das Danach (\"What happened then?\"), oder sag mit eigenen "
    "Worten, was du verstanden hast, und frag, ob es stimmt. Wechsle NIE das "
    "Thema, solange das Gegenüber eines hat. Wenn das Gegenüber ein neues "
    "Thema anfängt, geh mit.\n"
    "2. FRAG, WAS DU NICHT WEISST. Keine Prüffragen (\"What colour is "
    "this?\"), sondern echte Fragen nach Erlebnissen, Gewohnheiten, Plänen, "
    "Meinungen. Genau EINE Frage, kurz, am Ende, nie selbst beantwortet, "
    "nie zwei auf einmal.\n"
    "3. BLEIB KURZ. Ein bis zwei kurze Sätze, dann die Frage. Das Gegenüber "
    "soll mehr reden als du.\n"
    "4. SPIEGLE NICHT. Sag nicht \"I like X too\" oder \"Me too\". Reagiere "
    "auf den Inhalt wie ein Mensch: Überraschung, Nachfrage, eine kurze "
    "eigene Erfahrung, ein \"Oh really?\". Lob nur selten und nur konkret - "
    "nie \"Great!\", \"Super!\", \"Well done!\".\n"
    "5. FRAG NACH, STATT ZU KORRIGIEREN. Wenn etwas unklar oder ungenau "
    "war, frag so nach, wie ein Gesprächspartner es täte (\"Wait - today or "
    "yesterday?\", \"Sorry, who did you visit?\"), damit das Gegenüber es "
    "noch einmal sagt. Verwende die richtige Form danach beiläufig in "
    "deiner eigenen Frage. Höchstens ein Punkt pro Zug. Sag nie, dass etwas "
    "falsch war.\n"
    "6. FÜTTER EIN FEHLENDES WORT EIN. Wenn das Gegenüber sucht, ein "
    "deutsches Wort benutzt oder nach einem Wort fragt: Sag das Wort oder "
    "die Wendung kurz vor (\"a ukulele, yes\") und gib das Gespräch sofort "
    "zurück. Keine Erklärung, keine Alternativen.\n"
    "7. Antworte AUSSCHLIESSLICH auf {eigenname}. Kein deutsches Wort im "
    "Antworttext, auch dann nicht, wenn auf Deutsch geantwortet wird.\n"
    "8. Keine Aufzählungen, keine Überschriften, kein Vokabeltraining. Es ist "
    "ein Gespräch.\n"
    "\n"
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form, "
    "ohne Einleitung, ohne Kommentar und ohne Codeblock:\n"
    '{{"antwort": "dein Text auf {eigenname}, mit deiner einen Frage", '
    '"uebersetzung": "derselbe Text auf Deutsch", '
    '"korrektur": "eine bessere Formulierung für den letzten Beitrag, auf '
    '{eigenname}, oder leer"}}\n'
    "Das Feld \"korrektur\" enthält den SATZ DER LERNENDEN PERSON noch "
    "einmal, richtig geschrieben - nicht deinen eigenen Satz. Es bleibt "
    "meistens leer: Füll es nur, wenn wirklich etwas schieflag, und schreib "
    "dann nur die bessere Fassung, ohne Erklärung. Schreib dort NIEMALS "
    "dasselbe wie in \"antwort\"."
)

# Angst- und Stillesignale schalten das Regime um (Regel 10 der Recherche):
# Bei sehr kurzen Beitraegen ueber mehrere Zuege keine Korrektur, keine
# Nachfrage zur Form, leichtere Alternativfragen, zuerst den Inhalt
# bestaetigen. Ausgeloest vom Server, nicht vom Modell.
SCHONMODUS_ZUSATZ = (
    "\n\nDAS GEGENÜBER IST GERADE UNSICHER (sehr kurze Antworten). Deshalb "
    "jetzt: Bestätige zuerst freundlich den Inhalt. Stell eine LEICHTE "
    "Frage, am besten eine mit zwei Möglichkeiten (\"With a friend or "
    "alone?\"). Frag NICHT nach der Form, korrigiere nichts, und lass das "
    "Feld \"korrektur\" leer. Noch kürzer als sonst."
)

SCHAERFUNG_ANKNUEPFEN = (
    "\n\nACHTUNG: Deine letzte Antwort hat das Thema gewechselt, statt an "
    "das Gesagte anzuknüpfen. Greif ein Wort aus dem letzten Beitrag auf und "
    "frag dazu weiter - mehr, warum, ein Beispiel, das Danach."
)

SCHAERFUNG_SPIEGEL = (
    "\n\nACHTUNG: Deine letzte Antwort hat gespiegelt (\"I like … too\") "
    "oder gelobt, statt zu reagieren. Keine Spiegelung, kein Lob. Reagiere "
    "auf den Inhalt und frag dazu weiter."
)

SCHAERFUNG_FRAGE = (
    "\n\nACHTUNG: Deine letzte Antwort hatte nicht genau EINE Frage. Ein "
    "Zug endet mit genau einer Frage - nicht mit keiner, nicht mit zwei."
)

ERSTER_ZUG_ZUSATZ = (
    "Das Gespräch fängt gerade an. Begrüße kurz, sag in einem Satz, worüber "
    "ihr sprecht, und stell deine erste Frage. Nicht mehr."
)

SCHAERFUNG_LAENGE = (
    "\n\nACHTUNG: Deine letzte Antwort war zu lang. Höchstens {woerter} "
    "Wörter in einem Satz und höchstens {saetze} Sätze insgesamt. Schreib sie "
    "kürzer, nicht anders."
)

SCHAERFUNG_SPRACHE = (
    "\n\nACHTUNG: Deine letzte Antwort war nicht auf {eigenname}. Antworte "
    "auf {eigenname}, und zwar vollständig. Nur das Feld \"uebersetzung\" ist "
    "auf Deutsch."
)


# In der Aufgabe fragt das Kind (Regel 11, Szpotowicz 2012). Dort darf der
# Coach ohne Frage enden, aber nie mit zweien.
SCHAERFUNG_HOECHSTENS_EINE = (
    "\n\nACHTUNG: Deine letzte Antwort hatte mehr als eine Frage. Höchstens "
    "EINE Frage, oder keine - in dieser Aufgabe fragt das Gegenüber."
)


def system_prompt(sprache, niveau, thema, anrede, erster_zug=False,
                  schaerfung="", schonmodus=False, phasenanweisung=""):
    """Baut den Systemprompt fuer einen Zug des Sprechcoaches.

    `phasenanweisung` kommt aus sprechablauf.anweisung: Rolle, Ziel und
    Geheimnis der Gespraechsaufgabe, je Phase anders. Ist sie da, ersetzt
    sie den allgemeinen ersten Zug - wie die Aufgabe anfaengt, sagt die
    Phase.
    """
    eigenname = EIGENNAME.get(sprache, "English")
    # Die Niveauanweisung wird VOR dem Einsetzen formatiert: Sie nennt die
    # Sprache selbst ("sagst es auf English vor"), und ein Platzhalter, der
    # erst nach dem Einsetzen kaeme, stuende woertlich im Prompt.
    niveau_text = NIVEAU_ANWEISUNG.get(niveau, NIVEAU_ANWEISUNG["A1"]).format(
        eigenname=eigenname
    )
    teile = [GRUNDHALTUNG.format(
        eigenname=eigenname,
        gegenueber=anrede["gegenueber"],
        thema=thema or "freies Gespräch",
        niveau=niveau_text,
    )]
    if phasenanweisung:
        teile.append(phasenanweisung)
    elif erster_zug:
        teile.append(ERSTER_ZUG_ZUSATZ)
    if schonmodus:
        teile.append(SCHONMODUS_ZUSATZ)
    if schaerfung:
        teile.append(schaerfung)
    return "\n\n".join(teile)


# --- Die Antwort lesen ----------------------------------------------------

_LESER = json.JSONDecoder()


def _objekt(roh):
    """Das ERSTE JSON-Objekt aus der Antwort, oder None.

    Dasselbe wie beim Trainer, und aus demselben Anlass: Ein gieriges Muster
    verband zwei Objekte zu einem unlesbaren Stueck, und die Notbremse gab
    rohes JSON auf den Bildschirm.
    """
    text = (roh or "").strip()
    start = text.find("{")
    while start != -1:
        try:
            daten, _ = _LESER.raw_decode(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        return daten if isinstance(daten, dict) else None
    return None


def brauchbare_korrektur(korrektur, antwort, beitrag=""):
    """Taugt diese Korrektur etwas?

    Im ersten Durchlauf fuellte das Modell das Feld mit seiner EIGENEN
    Antwort. Auf dem Bildschirm stand derselbe Satz dann zweimal, einmal als
    Gespraech und einmal als Korrektur - und wer eine Korrektur sieht, sucht
    seinen Fehler darin.

    Verworfen wird deshalb, was der eigenen Antwort gleicht, und was dem
    Beitrag der lernenden Person Wort fuer Wort gleicht: Dann gab es nichts
    zu korrigieren.
    """
    k = (korrektur or "").strip()
    if not k:
        return ""
    if _vereinfacht(k) == _vereinfacht(antwort):
        return ""
    if _vereinfacht(k) in _vereinfacht(antwort):
        return ""
    if beitrag and _vereinfacht(k) == _vereinfacht(beitrag):
        return ""
    return k


def _vereinfacht(text):
    """Kleinbuchstaben ohne Satzzeichen, fuer den Vergleich."""
    return " ".join(_WORT.findall((text or "").lower()))


def antwort_lesen(roh):
    """Antwort, Uebersetzung und Korrektur."""
    daten = _objekt(roh)
    if daten is not None:
        return {
            "antwort": str(daten.get("antwort", "")).strip(),
            "uebersetzung": str(daten.get("uebersetzung", "")).strip(),
            "korrektur": str(daten.get("korrektur", "")).strip(),
        }

    logger.warning("Coachantwort war kein JSON, Text wird gerettet.")
    text = (roh or "").strip()
    if "{" in text or '"antwort"' in text:
        treffer = re.search(r'"antwort"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
        if treffer:
            try:
                text = json.loads('"' + treffer.group(1) + '"').strip()
            except json.JSONDecodeError:
                text = treffer.group(1).strip()
        else:
            text = ""
    return {"antwort": text, "uebersetzung": "", "korrektur": ""}


# --- Die Pruefung ---------------------------------------------------------
#
# Funktionswoerter, an denen sich die Sprache erkennen laesst. Das ist eine
# Heuristik und kein Sprachenerkenner: Sie entscheidet zwischen fuenf
# bekannten Moeglichkeiten, nicht zwischen allen Sprachen der Welt. Fuer die
# eine Frage, die hier zaehlt - "ist das Deutsch statt der Zielsprache" -
# reicht sie, und sie kostet nichts.

_MARKER = {
    "de": {"der", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit",
           "ich", "du", "wir", "haben", "sind", "auch", "aber", "noch",
           "schon", "sehr", "was", "wie", "für"},
    "en": {"the", "and", "you", "is", "are", "what", "do", "have", "can",
           "that", "with", "for", "your", "it", "this", "they", "about"},
    "fr": {"le", "la", "les", "est", "vous", "que", "de", "et", "un", "une",
           "pour", "avec", "ce", "tu", "des", "dans", "sur", "qui"},
    "it": {"il", "la", "che", "non", "di", "sono", "una", "per", "con",
           "questo", "tu", "come", "cosa", "anche", "molto", "gli"},
    "es": {"el", "la", "que", "de", "y", "es", "no", "un", "una", "por",
           "con", "para", "tu", "como", "muy", "los", "las", "pero"},
}

_WORT = re.compile(r"[\wäöüßàâçéèêëîïôûùüÿñæœáíóúÁÉÍÓÚñ]+", re.UNICODE)


def sprache_erkannt(text, ziel):
    """Ist der Text eher in der Zielsprache oder eher auf Deutsch?

    Gibt True zurueck, wenn die Zielsprache mindestens so viele Marker hat
    wie Deutsch. Bei Gleichstand gilt die Zielsprache: Kurze Saetze haben oft
    gar keinen Marker, und ein Fehlalarm kostet hier einen zweiten Aufruf.
    """
    woerter = [w.lower() for w in _WORT.findall(text or "")]
    if not woerter:
        return True

    ziel_kurz = whisper_code(ziel)
    treffer_ziel = sum(1 for w in woerter if w in _MARKER.get(ziel_kurz, set()))
    treffer_de = sum(1 for w in woerter if w in _MARKER["de"])
    return treffer_ziel >= treffer_de


def saetze(text):
    """Zerlegt in Saetze. Grob, aber fuer die Laengenpruefung genug."""
    roh = re.split(r"(?<=[.!?…])\s+", (text or "").strip())
    return [s for s in roh if s.strip()]


def zu_lang(text, niveau):
    """Welche Saetze sind laenger als das Niveau erlaubt?

    "Sprich einfach" ist eine Bitte. Hoechstens acht Woerter je Satz ist eine
    Grenze, und sie laesst sich zaehlen.
    """
    grenze = WOERTER_JE_SATZ.get(niveau, 8)
    return [s for s in saetze(text) if len(_WORT.findall(s)) > grenze]


# --- Angst- und Stillesignale ---------------------------------------------

# Ab wie vielen Woertern ein Beitrag "kurz" ist, und wie viele kurze Beitraege
# hintereinander den Schonmodus ausloesen. Drei Woerter ueber drei Zuege ist
# die Schwelle aus der Recherche (Shashidhara et al. 2026: 36 Prozent der
# Aeusserungen am ersten Tag hatten hoechstens drei Tokens).
SCHON_WOERTER = 3
SCHON_ZUEGE = 3


def schonmodus_noetig(beitraege):
    """Sind die letzten Beitraege so kurz, dass der Coach schonen soll?

    `beitraege` sind die juengsten Texte der lernenden Person, juengster
    zuerst. Ausgeloest erst ab SCHON_ZUEGE Beitraegen: Ein einzelnes "Yes."
    ist ein Beitrag und kein Signal.
    """
    letzte = [b for b in (beitraege or [])[:SCHON_ZUEGE]]
    if len(letzte) < SCHON_ZUEGE:
        return False
    return all(len(_WORT.findall(b or "")) <= SCHON_WOERTER for b in letzte)


def schaerfung_fuer(gefunden, sprache, niveau):
    """Welche Nachschaerfung passt zu diesen Verstoessen?

    Die Sprache zuerst: Eine deutsche Antwort ist der schlimmste Fall. Dann
    das Anknuepfen, dann Spiegeln und Lob, dann die Frage, zuletzt die
    Laenge - in der Reihenfolge dessen, was das Gespraech am ehesten kostet.
    """
    if "falsche Sprache" in gefunden:
        return SCHAERFUNG_SPRACHE.format(eigenname=EIGENNAME.get(sprache, "English"))
    if "knüpft nicht an" in gefunden:
        return SCHAERFUNG_ANKNUEPFEN
    if "spiegelt" in gefunden or "lobt pauschal" in gefunden:
        return SCHAERFUNG_SPIEGEL
    if "nicht genau eine Frage" in gefunden:
        return SCHAERFUNG_FRAGE
    if "mehr als eine Frage" in gefunden:
        return SCHAERFUNG_HOECHSTENS_EINE
    return SCHAERFUNG_LAENGE.format(
        woerter=WOERTER_JE_SATZ.get(niveau, 8),
        saetze=SAETZE_JE_ZUG.get(niveau, 2),
    )


# --- Der dritte Zug, zaehlbar ---------------------------------------------
#
# Drei Dinge aus der Recherche lassen sich ohne Modell pruefen: ob die
# Antwort spiegelt oder lobt statt zu reagieren, ob sie genau eine Frage
# stellt, und ob sie ueberhaupt an den letzten Beitrag anknuepft. Das Letzte
# ist grob - ein gemeinsames Inhaltswort - aber es faengt genau den Fall, der
# im Protokoll stand: "I like guitar too. What song do you play?" nach einem
# Beitrag ueber eine Ukulele, die der Coach gar nicht aufgegriffen hat.

# Auch nach einem Einwurf ("Oh, I play the guitar as well") ist es Spiegeln.
_SPIEGEL = re.compile(
    r"^\W*(?:(?:oh|ah|well|yes|yeah|wow|cool|hm+|nice|great)[,!\s]+)?"
    r"(?:i\s+(?:like|love|enjoy|play|have|think)\b[^.!?]{0,60}\b(?:too|as\s+well|also)\b"
    r"|me\s+too\b|same\s+here\b|i\s+also\b|moi\s+aussi\b|anch'?io\b|yo\s+tambi[ée]n\b)",
    re.IGNORECASE,
)

_LOB = re.compile(
    r"^\W*(?:great|awesome|amazing|excellent|perfect|wonderful|fantastic|super|"
    r"well\s+done|good\s+job|very\s+good|nice\s+one|bravo|génial|très\s+bien|"
    r"bravissimo|ottimo|perfecto|muy\s+bien|genial)\b",
    re.IGNORECASE,
)

# Woerter, die fuer das Anknuepfen nicht zaehlen: zu haeufig, um etwas zu
# verbinden. Je Sprache nur die groebsten.
_FUELLWOERTER = {
    "the", "and", "you", "your", "are", "is", "was", "were", "have", "has",
    "had", "with", "for", "that", "this", "they", "them", "what", "which",
    "when", "where", "why", "how", "who", "do", "does", "did", "not", "but",
    "very", "much", "many", "some", "any", "there", "here", "about", "like",
    "think", "know", "can", "could", "would", "will", "just", "really",
    "also", "too", "yes", "no", "okay", "ok", "hello", "hi", "thank",
    "thanks", "please", "sorry", "good", "nice", "well", "then", "than",
    "from", "into", "it's", "its", "i'm", "don't", "doesn't", "because",
    "something", "anything", "everything", "thing", "things", "want",
    "name", "tell", "more", "ich", "und", "das", "ist", "nicht", "auch",
}


def _inhaltswoerter(text):
    """Woerter ab vier Buchstaben, die etwas bedeuten koennten."""
    return {
        w.lower() for w in _WORT.findall(text or "")
        if len(w) >= 4 and w.lower() not in _FUELLWOERTER
    }


def _stamm(wort):
    """Ganz grob: Plural-s und -ing/-ed weg, damit "guitar" und "guitars"
    oder "play" und "playing" als dasselbe gelten."""
    for endung in ("ing", "ed", "es", "s"):
        if wort.endswith(endung) and len(wort) - len(endung) >= 4:
            return wort[: -len(endung)]
    return wort


def spiegelt(text):
    """Faengt die Antwort mit "I like X too" / "Me too" an?"""
    return bool(_SPIEGEL.search(text or ""))


def lobt(text):
    """Faengt die Antwort mit pauschalem Lob an?"""
    return bool(_LOB.search(text or ""))


def genau_eine_frage(text):
    return (text or "").count("?") == 1


def anknuepft(text, beitrag):
    """Teilt die Antwort ein Inhaltswort mit dem letzten Beitrag?

    Gilt als erfuellt, wenn der Beitrag selbst keine Inhaltswoerter hat
    ("Yes." laesst sich nicht aufgreifen) - dann darf der Coach ein Thema
    setzen. Grob, aber in die richtige Richtung: Ein Fehlalarm kostet einen
    zweiten Aufruf, ein uebersehener Themenwechsel kostet das Gespraech.
    """
    woerter_beitrag = {_stamm(w) for w in _inhaltswoerter(beitrag)}
    if not woerter_beitrag:
        return True
    woerter_antwort = {_stamm(w) for w in _inhaltswoerter(text)}
    return bool(woerter_beitrag & woerter_antwort)


_FRAGEANFANG = re.compile(
    r"^\W*(?:what|where|when|who|whom|whose|why|how|which|do|does|did|is|are|"
    r"was|were|can|could|would|will|shall|should|have|has|may)\b",
    re.IGNORECASE,
)


def ist_frage(text):
    """Ein Fragezeichen, oder ein Satz, der wie eine englische Frage anfaengt.

    Whisper setzt das Fragezeichen meistens, aber nicht immer; getippt fehlt
    es oft. Der Anfang allein ist fuer Englisch verlaesslich genug.
    """
    t = (text or "").strip()
    return "?" in t or bool(_FRAGEANFANG.match(t))


def verstoesse(text, sprache, niveau, beitrag="", kind_fragt=False):
    """Was stimmt an dieser Antwort nicht? Leere Liste heisst: nichts.

    `beitrag` ist der letzte Beitrag der lernenden Person; ohne ihn entfaellt
    die Pruefung des Anknuepfens (erster Zug).

    `kind_fragt` gilt in der Gespraechsaufgabe (Regel 11): Dort fragt das
    Kind und der Coach antwortet. Ein Zug darf dann ohne Frage enden, aber
    nicht mit zweien; und wer eine Frage beantwortet, knuepft an, auch wenn
    kein Inhaltswort wiederkehrt ("When is the party?" - "On Saturday.").
    """
    gefunden = []
    if not sprache_erkannt(text, sprache):
        gefunden.append("falsche Sprache")
    if zu_lang(text, niveau):
        gefunden.append("zu lange Sätze")
    if len(saetze(text)) > SAETZE_JE_ZUG.get(niveau, 2) + 1:
        gefunden.append("zu viele Sätze")
    if spiegelt(text):
        gefunden.append("spiegelt")
    if lobt(text):
        gefunden.append("lobt pauschal")
    if kind_fragt:
        if (text or "").count("?") > 1:
            gefunden.append("mehr als eine Frage")
    elif not genau_eine_frage(text):
        gefunden.append("nicht genau eine Frage")
    beantwortet = kind_fragt and ist_frage(beitrag)
    if beitrag and not beantwortet and not anknuepft(text, beitrag):
        gefunden.append("knüpft nicht an")
    return gefunden


def gekuerzt(text, niveau):
    """Behaelt die ersten Saetze, die kurz genug sind.

    Lieber eine knappe Antwort als eine, die das Niveau sprengt. Bleibt
    nichts uebrig, entscheidet der Aufrufer.
    """
    grenze = WOERTER_JE_SATZ.get(niveau, 8)
    hoechstens = SAETZE_JE_ZUG.get(niveau, 2)
    behalten = [s for s in saetze(text) if len(_WORT.findall(s)) <= grenze]
    return " ".join(behalten[:hoechstens]).strip()


# Wenn gar nichts uebrig bleibt. In der Zielsprache, kurz, und mit einer
# Frage - damit das Gespraech nicht an unserer Pruefung stirbt.
NOTFALL = {
    "en-GB": "Sorry, I lost my words. What do you think?",
    "fr-FR": "Pardon, j'ai perdu le fil. Et toi ?",
    "it-IT": "Scusa, mi sono perso. E tu?",
    "es-ES": "Perdona, me he perdido. ¿Y tú?",
}


# --- Die Sprachsperre: der Coach versteht nur die Zielsprache -------------
#
# Der Coach TUT, als verstehe er kein Deutsch. Er koennte natuerlich - genau
# darum ist es eine Entscheidung und kein Mangel. In einer Englischstunde ist
# das die aelteste Methode, die es gibt: Wer weiss, dass Deutsch nicht
# weiterhilft, sucht nach dem englischen Wort.
#
# Diese Freundlichkeit hat eine Grenze, und sie liegt beim Kind, das
# feststeckt. Deshalb gibt es den stillen Knopf "Ich komme nicht weiter":
# Der Coach bleibt englisch, die Hilfe daneben ist deutsch. Eine Sperre ohne
# Ausweg ist keine Methode, sondern eine verschlossene Tuer.
#
# IN WELCHE RICHTUNG DIESE PRUEFUNG IRREN DARF
#
# Nur in eine. Ein Kind, das richtig Englisch gesprochen hat und dafuer
# "Sorry, I don't understand" bekommt, lernt die falsche Lektion und hoert
# auf. Ein deutscher Satz, der durchrutscht, kostet dagegen nichts: Der Coach
# antwortet dann eben auf Englisch weiter. Deshalb wird nur abgewiesen, wenn
# es BELEGE fuer eine andere Sprache gibt - nicht, wenn Belege fehlen.

NICHT_VERSTANDEN = {
    "en-GB": "Sorry, I don't understand that. Can you say it in English?",
    "fr-FR": "Désolé, je ne comprends pas. Tu peux le dire en français ?",
    "it-IT": "Scusa, non capisco. Puoi dirlo in italiano?",
    "es-ES": "Perdona, no te entiendo. ¿Puedes decirlo en español?",
}

# Wie viele deutsche Marker es mindestens braucht, wenn Whisper keine Sprache
# gemeldet hat. Einer genuegt nicht: "I have a Hund" ist ein Kind, das sich
# mueht, und kein deutscher Satz.
_MARKER_SCHWELLE = 2


def nicht_verstanden(sprache):
    return NICHT_VERSTANDEN.get(sprache) or NICHT_VERSTANDEN[SPRACHE_STANDARD]


def ist_zielsprache(text, ziel, erkannt=None):
    """Darf dieser Beitrag als Beitrag in der Zielsprache gelten?

    `erkannt` ist der Sprachcode, den Whisper gemeldet hat, oder None - bei
    getipptem Text gibt es keinen.

    Die Reihenfolge ist Absicht:

    1. Kein Text: durchlassen. Eine leere Aufnahme ist kein Deutsch.
    2. Whisper meldet die Zielsprache: durchlassen, ohne Nachprüfung. Das
       Modell hat die Aufnahme gehoert, die Wortliste hier hat nur den Text.
    3. Whisper meldet eine andere Sprache: abweisen, es sei denn die Marker
       der Zielsprache sind in der Mehrheit. Whisper verwechselt bei einem
       einzelnen Wort gern einmal, und "Yes." soll nicht scheitern.
    4. Whisper meldet nichts (getippt): nur abweisen, wenn deutsche Marker
       klar ueberwiegen UND es mindestens zwei sind.
    """
    woerter = [w.lower() for w in _WORT.findall(text or "")]
    if not woerter:
        return True

    ziel_kurz = whisper_code(ziel)
    treffer_ziel = sum(1 for w in woerter if w in _MARKER.get(ziel_kurz, set()))
    treffer_de = sum(1 for w in woerter if w in _MARKER["de"])

    if erkannt:
        if whisper_code(erkannt) == ziel_kurz:
            return True
        return treffer_ziel > treffer_de

    return not (treffer_de > treffer_ziel and treffer_de >= _MARKER_SCHWELLE)


# --- Sinneinheit: klingt die Aeusserung fertig? ---------------------------
#
# Seit dem Gespraechsmodus schickt der Browser von selbst ab, sobald eine
# Pause erkannt ist - kein Knopf mehr. Eine Pause ist aber nicht immer ein
# Ende: Wer in einer Fremdsprache spricht, sagt "I ..." und sucht dann das
# Wort. Darum sieht der Server den abgeschriebenen Text an und sagt dem
# Browser, ob er noch einen Moment warten und die naechste Aeusserung
# anhaengen soll. Das ist Regel 4 der Recherche (Wartezeit garantieren, nie
# vervollstaendigen) in zaehlbarer Form.
#
# IN WELCHE RICHTUNG DIESE PRUEFUNG IRREN DARF: in beide, aber verschieden
# teuer. Ein Satz, der faelschlich als Fragment gilt, kostet zwei Sekunden
# Wartezeit - der Browser schickt ihn danach trotzdem. Ein Fragment, das
# faelschlich als fertig gilt, kostet einen abgehackten Zug und eine Antwort
# auf einen halben Satz. Die Listen duerfen also eher zu lang sein.

# Woerter, auf die ein englischer Satz praktisch nie endet: Konjunktionen,
# Artikel, Praepositionen, Hilfsverben, Subjektpronomen, Verkuerzungen.
# "no", "not", "you", "it", "me" fehlen mit Absicht - "No.", "Why not?",
# "I like you.", "I love it." sind ganze Saetze.
_ABBRUCHWOERTER = {
    "en": {
        "and", "but", "or", "so", "because", "if", "when", "while", "although",
        "though", "than", "that", "which", "who", "where", "as", "then",
        "the", "a", "an", "my", "your", "his", "her", "its", "our", "their",
        "this", "these", "those", "some", "every", "any", "much", "many",
        "very", "really", "more", "most", "also", "only", "just",
        "to", "of", "in", "on", "at", "with", "for", "from", "about", "into",
        "by", "like", "after", "before", "between", "under", "over",
        "through", "near", "until", "during",
        "i", "he", "she", "we", "they",
        "is", "are", "am", "was", "were", "be", "been", "being", "have",
        "has", "had", "do", "does", "did", "can", "could", "will", "would",
        "shall", "should", "may", "might", "must",
        "i'm", "it's", "he's", "she's", "that's", "there's", "we're",
        "they're", "you're", "i've", "we've", "you've", "they've", "i'll",
        "we'll", "you'll", "i'd", "we'd", "you'd", "he'd", "she'd", "they'd",
        "what's", "where's", "who's", "how's", "let's",
        "want", "wants", "love", "need", "favourite", "favorite", "called",
    },
    "fr": {
        "et", "mais", "ou", "parce", "que", "qu'", "le", "la", "les", "un",
        "une", "des", "du", "de", "à", "au", "aux", "avec", "pour", "dans",
        "sur", "je", "j'", "il", "elle", "nous", "ils", "elles", "suis",
        "es", "est", "sommes", "sont", "ai", "as", "a", "avons", "ont",
        "c'est", "j'ai", "mon", "ma", "mes", "ton", "ta", "tes", "très",
    },
    "it": {
        "e", "ma", "o", "perché", "che", "il", "lo", "la", "i", "gli", "le",
        "un", "una", "uno", "di", "a", "da", "in", "con", "su", "per", "io",
        "lui", "lei", "noi", "loro", "sono", "sei", "è", "siamo", "ho",
        "hai", "ha", "abbiamo", "hanno", "mio", "mia", "molto",
    },
    "es": {
        "y", "pero", "o", "porque", "que", "el", "la", "los", "las", "un",
        "una", "unos", "unas", "de", "a", "en", "con", "por", "para", "yo",
        "él", "ella", "nosotros", "ellos", "soy", "eres", "es", "somos",
        "son", "tengo", "tienes", "tiene", "estoy", "está", "mi", "tu", "su",
        "muy",
    },
}

# Laute, die kein Wort sind. Eine Aeusserung nur daraus ist noch keine.
_FUELLLAUTE = {
    "um", "uh", "uhm", "umm", "er", "erm", "eh", "ehm", "em", "hm", "hmm",
    "mm", "mhm", "ah", "oh", "äh", "ähm", "öh", "öhm", "euh", "ehh",
}

# Ein einzelnes Wort, das ein ganzer Beitrag sein kann: Ja, Nein, Gruss,
# Fragewort, Zeitwort, Zahl. "Football." allein steht nicht hier - es wird
# als Fragment gemeldet und nach der kurzen Wartezeit trotzdem geschickt.
_GANZE_WOERTER = {
    "en": {
        "yes", "no", "yeah", "yep", "nope", "okay", "ok", "sure", "maybe",
        "hello", "hi", "hey", "bye", "goodbye", "thanks", "fine", "good",
        "great", "right", "please", "sorry", "pardon", "me", "nothing",
        "nobody", "never", "always", "sometimes", "today", "yesterday",
        "tomorrow", "what", "why", "who", "where", "when", "how", "which",
        "zero", "one", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        "hundred",
    },
    "fr": {"oui", "non", "ouais", "d'accord", "salut", "bonjour", "merci",
           "peut-être", "moi", "rien", "pourquoi", "quoi", "qui", "où",
           "quand", "comment"},
    "it": {"sì", "si", "no", "ciao", "grazie", "forse", "niente", "perché",
           "cosa", "chi", "dove", "quando", "come"},
    "es": {"sí", "si", "no", "vale", "hola", "gracias", "adiós", "quizás",
           "nada", "nadie", "qué", "quién", "dónde", "cuándo", "cómo"},
}

# Woerter mit Apostroph bleiben ganz: "it's" ist ein Abbruchwort, "it" und
# "s" sind keins. _WORT zerlegt sie, darum ein eigenes Muster.
_WORT_GANZ = re.compile(r"[\w'’]+", re.UNICODE)


def _woerter_ganz(text):
    return [w.replace("’", "'").lower().strip("'") for w in _WORT_GANZ.findall(text or "")]


def wirkt_unvollstaendig(text, sprache=None):
    """Sieht diese Aeusserung wie ein abgebrochener Satz aus?

    Deterministisch und ohne Modell. True heisst: Der Browser soll noch bis
    zu zwei Sekunden warten und die naechste Aeusserung anhaengen. Drei
    Gruende:

    1. Das letzte Wort ist eines, auf das kein Satz endet ("and", "the",
       "to", "I", "it's", "because", "with").
    2. Es sind nur Fuelllaute ("um", "ehm") oder gar keine Woerter.
    3. Es ist ein einzelnes Wort, und keines, das allein ein Beitrag sein
       kann (Ja, Nein, Gruss, Fragewort, Zahl).
    """
    code = whisper_code(sprache)
    abbruch = _ABBRUCHWOERTER.get(code, _ABBRUCHWOERTER["en"])
    ganz = _GANZE_WOERTER.get(code, _GANZE_WOERTER["en"])

    woerter = [w for w in _woerter_ganz(text) if w]
    inhalt = [w for w in woerter if w not in _FUELLLAUTE]
    if not inhalt:
        return True
    if len(inhalt) < 2:
        wort = inhalt[0]
        return not (wort in ganz or wort.isdigit())
    return inhalt[-1] in abbruch


# --- Sprachinhalt: wurde ueberhaupt gesprochen? ---------------------------
#
# Whisper erfindet bei Stille und Rauschen ganze Saetze, am liebsten
# Untertitel-Floskeln. Der Browser schickt zwar nur, was ueber dem
# Geraeuschboden lag, aber ein Husten, ein Stuhl, ein Nachbar im Zimmer
# liegen auch darueber. verbose_json liefert je Abschnitt, wie sicher sich
# Whisper war, dass da Sprache ist (no_speech_prob) und wie plausibel der
# Text ist (avg_logprob, compression_ratio). Das sind Whispers eigene
# Schwellen fuer das Weglassen eines Abschnitts.

NO_SPEECH_SCHWELLE = 0.6
LOGPROB_SCHWELLE = -1.0
KOMPRESSION_SCHWELLE = 2.4

# Was Whisper bei Stille gern schreibt. Nur Floskeln, die ein Kind im
# Gespraech nicht sagt - "Thank you." steht nicht hier, das sagt man.
_ERFUNDEN = re.compile(
    r"subtitles?\s+by|untertitel|amara\.org|thanks?\s+(?:you\s+)?for\s+watching|"
    r"please\s+subscribe|like\s+and\s+subscribe|transcribed\s+by|"
    r"copyright|www\.|\.com\b|♪",
    re.IGNORECASE,
)


def _zahl(wert):
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _abschnitt_leer(abschnitt):
    """Whispers eigene Regel: wahrscheinlich keine Sprache UND unplausibler
    Text, oder ein Text, der sich immerzu wiederholt."""
    kein_ton = _zahl(abschnitt.get("no_speech_prob"))
    plausibel = _zahl(abschnitt.get("avg_logprob"))
    kompression = _zahl(abschnitt.get("compression_ratio"))
    if kein_ton is not None and kein_ton > NO_SPEECH_SCHWELLE and (
            plausibel is None or plausibel < LOGPROB_SCHWELLE):
        return True
    if kompression is not None and kompression > KOMPRESSION_SCHWELLE:
        return True
    return False


def hat_sprachinhalt(ergebnis):
    """Steht in dieser Whisper-Antwort etwas, das ein Kind gesagt hat?

    False heisst: kein Zug, der Browser hoert einfach weiter. Geprueft wird
    nur, was da ist - fehlen die Abschnitte oder ihre Felder, entscheidet der
    Text allein. Aus fehlenden Belegen wird nie auf Stille geschlossen: Ein
    Kind, dessen richtigen Satz wir wegwerfen, glaubt, das Geraet hoere
    nicht zu.
    """
    if not isinstance(ergebnis, dict):
        return False
    text = (ergebnis.get("text") or "").strip()
    if not _WORT.findall(text):
        return False
    if _ERFUNDEN.search(text):
        return False
    abschnitte = [a for a in (ergebnis.get("segments") or []) if isinstance(a, dict)]
    beurteilbar = [a for a in abschnitte
                   if any(k in a for k in ("no_speech_prob", "avg_logprob", "compression_ratio"))]
    if beurteilbar and all(_abschnitt_leer(a) for a in beurteilbar):
        return False
    return True


# --- Der stille Ausweg ----------------------------------------------------

HILFE_PROMPT = (
    "Ein Kind lernt {sprache_name} auf Niveau {niveau} und kommt im Gespräch "
    "nicht weiter. Thema: {thema}.\n"
    "Der letzte Satz des Coachs war: {frage}\n\n"
    "Antworte mit genau diesem JSON und nichts daneben:\n"
    '{{"erklaerung": "...", "beispiel": "..."}}\n\n'
    "erklaerung: Ein kurzer deutscher Satz, der sagt, was der Coach gerade "
    "wissen will. Höchstens 15 Wörter, Du-Form, kein Fachwort.\n"
    "beispiel: EIN Satz in {sprache_name}, den das Kind jetzt sagen könnte. "
    "Höchstens {woerter} Wörter, Niveau {niveau}."
)


def hilfe_lesen(roh, sprache, niveau):
    """Liest die Antwort auf HILFE_PROMPT.

    Der deutsche Teil ist hier ausdruecklich erlaubt - das ist der eine Ort
    in dieser Betriebsart, an dem Deutsch die Hilfe ist und nicht der Fehler.
    Das Beispiel muss aber in der Zielsprache stehen, sonst waere der Ausweg
    eine Abkuerzung: Ein deutsches Beispiel loest die Aufgabe, statt sie
    sagbar zu machen.
    """
    objekt = _objekt(roh) or {}
    erklaerung = (objekt.get("erklaerung") or "").strip()
    beispiel = (objekt.get("beispiel") or "").strip()

    if beispiel and not ist_zielsprache(beispiel, sprache):
        beispiel = ""
    if beispiel:
        beispiel = gekuerzt(beispiel, niveau)

    if not erklaerung:
        erklaerung = ("Der Coach hat dich etwas gefragt. Antworte mit einem "
                      "kurzen Satz – einzelne Wörter zählen auch.")
    return {"erklaerung": erklaerung, "beispiel": beispiel}
