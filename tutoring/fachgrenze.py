"""Die Fachgrenze: Was nicht zur Stunde gehoert, beantwortet kein Modell.

Anlass (Thomas, 6.11.2026): Die Landes-KI VOKI laeuft wie unser Tutor auf
einem Qwen-Modell und hat auf die Frage nach dem Massaker von 1989
geantwortet, sie koenne "keine Informationen bereitstellen, die in China als
sensibel eingestuft werden" (ORF Vorarlberg, 3.11.2026). Unser Tutor
unterrichtet ein Fach und gibt keine Auskunft. Bis hierher stand diese
Grenze aber nur im Prompt: Die Ampel kannte "gelb: anderes Thema", die
Antwort an das Kind schrieb trotzdem das Modell. Ein Systemprompt ist eine
Bitte; die Grenze gehoert in den Server (ausgabepruefung.py).

Was hier entschieden wird:

1. Der Pfoertner. Vor der Antwort in einer Fachstunde faellt eine einzige
   Entscheidung: Gehoert der Beitrag zur Stunde, ja, nein oder unklar. Er
   fragt nicht "ist das heikel" - eine Themenliste waere selbst eine
   Zensurliste - sondern nur "gehoert das zum Fach, zum Thema, zur Aufgabe".
   Im Zweifel ja: Ein Pfoertner, der Rueckfragen zur Aufgabe abwuergt,
   schadet jeden Tag; ein Pfoertner, der eine fremde Frage durchlaesst, nur
   dann, wenn das Modell darauf schlecht antwortet.

2. Der feste Satz. Sagt der Pfoertner nein, formuliert kein Modell. Die
   Anwendung antwortet mit demselben Satz je Fach, freundlich, ohne
   Belehrung, mit dem Rueckweg zur Aufgabe - fuer Peking wie fuer Berlin
   wie fuer den Fussball. Das ist die Symmetrie, die sich nachpruefen laesst.

3. Wer der Pfoertner ist, steht in den Einstellungen. Ohne eigene Adresse
   urteilt das Modell am Spark (Stufe A: Qwen urteilt ueber Qwen, kein
   zusaetzlicher Speicher). Mit PFOERTNER_BASE_URL und PFOERTNER_MODEL
   urteilt ein zweites Modell (Stufe B, geplant: Ministral 3 von Mistral AI,
   Apache 2.0), das nie fuer das Kind schreibt. Dieselbe Schnittstelle, kein
   anderer Code. Ob Stufe B noetig ist, sagt die Neutralitaetsprobe
   (benchmark/neutralitaet/).

4. Die Form der Verweigerung. Im Safe Chat gehoert jede Frage zur Stunde,
   dort hilft kein Pfoertner. Dort prueft die Anwendung die ANTWORT auf die
   Form, in der eine politische Verweigerung auftritt ("in China als sensibel
   eingestuft", "gegen gesetzliche Bestimmungen"), nicht auf das Thema; wie
   die Ausgangspruefung die Form einer Loesung sucht und nicht ihre
   Bedeutung. Trifft sie, erreicht der Wortlaut das Kind nicht.

Deterministisch vor dem Modell, wie ueberall: Zustimmung, "weiss nicht",
eine Rechnung in Mathematik - das gehoert zur Stunde, ohne Aufruf.
"""

import concurrent.futures
import json
import logging
import re
import time

import httpx
from django.conf import settings

from . import faecher, levels, pruefung

logger = logging.getLogger(__name__)

JA = "ja"
NEIN = "nein"
UNKLAR = "unklar"
URTEILE = (JA, NEIN, UNKLAR)

# Steht als Begruendung an der Ampel des Beitrags (flag_reason, hoechstens
# 120 Zeichen) und markiert damit den Beitrag, den die Anwendung selbst
# beantwortet hat. Der Verlauf der Lehrperson zeigt genau diese Worte.
GRUND = "gehört nicht zur Stunde"

# Kein Modell wird gefragt, wenn der Beitrag so kurz ist, dass er nirgends
# hingehoeren kann ausser zur laufenden Arbeit.
MINDESTWOERTER = 3


class Urteil:
    """Das Urteil des Pfoertners samt Messung fuer das Forschungsprotokoll."""

    __slots__ = ("zur_stunde", "grund", "messung", "modell_gefragt")

    def __init__(self, zur_stunde=UNKLAR, grund="", messung=None, modell_gefragt=False):
        self.zur_stunde = zur_stunde if zur_stunde in URTEILE else UNKLAR
        self.grund = (grund or "")[:120]
        self.messung = messung or {}
        self.modell_gefragt = modell_gefragt

    @property
    def fremd(self):
        """Nur ein klares Nein sperrt. Unklar heisst: das Modell antwortet."""
        return self.zur_stunde == NEIN

    def __repr__(self):
        return f"Urteil({self.zur_stunde!r}, {self.grund!r})"


# --- Die festen Saetze -----------------------------------------------------
#
# Je Fach ein Satz, in der Form der Altersklasse (du, oder "Sie" bei
# Erwachsenen). Kein Vorwurf, keine Regel-Erklaerung, keine Nennung des
# fremden Themas: Der Satz ist derselbe, worum auch immer es ging. Hinten
# der Rueckweg: die offene Frage des Tutors, wenn es eine gibt.

_SAETZE = {
    "mathematik": {
        "du": "Das ist eine andere Frage, und keine schlechte. Heute geht es "
              "hier aber um Mathematik. Frag das deine Lehrerin oder deinen "
              "Lehrer.",
        "sie": "Das ist eine andere Frage, und keine schlechte. Hier geht es "
               "aber um Mathematik; dafür ist diese Anwendung gebaut.",
    },
    "deutsch": {
        "du": "Darum geht es in dieser Stunde nicht. Wir sind bei Deutsch{thema}. "
              "Frag das in der Pause deine Lehrperson.",
        "sie": "Darum geht es in dieser Stunde nicht. Wir sind bei Deutsch{thema}.",
    },
    "sachunterricht": {
        "du": "Darum geht es in dieser Stunde nicht. Wir sind {bei_thema}. "
              "Frag das in der Pause deine Lehrperson.",
        "sie": "Darum geht es in dieser Stunde nicht. Wir sind {bei_thema}.",
    },
    "englisch": {
        "du": "That is a different topic. Let's stay with our conversation{about}.",
        "sie": "That is a different topic. Let's stay with our conversation{about}.",
    },
}

_ALLGEMEIN = {
    "du": "Darum geht es in dieser Stunde nicht. Hier geht es um {fach}. "
          "Frag das deine Lehrperson.",
    "sie": "Darum geht es in dieser Stunde nicht. Hier geht es um {fach}.",
}

# Der Rueckweg, wenn keine offene Frage da ist.
_RUECKWEG = {
    "mathematik": {"du": "Wollen wir bei der Aufgabe weitermachen?",
                   "sie": "Zurück zur Aufgabe?"},
    "englisch": {"du": "Where were we?", "sie": "Where were we?"},
}
_RUECKWEG_ALLGEMEIN = {"du": "Wo waren wir stehen geblieben?",
                       "sie": "Wo waren wir stehen geblieben?"}

# Der Sprechcoach (tutoring/sprechcoach.py) TUT, als verstehe er kein Deutsch.
# Also bleibt auch sein fester Satz in der Zielsprache; die deutsche Fassung
# steht zugeklappt darunter wie bei jedem Zug. Kurz und einfach, weil er
# auch auf A1 verstanden werden muss. Je Sprache: Satz, Uebersetzung,
# Rueckweg ohne offene Frage.
_SPRACHSAETZE = {
    "en-GB": ("That is another topic. Here we practise English together.",
              "Das ist ein anderes Thema. Hier üben wir zusammen Englisch.",
              "Where were we?"),
    "fr-FR": ("C'est un autre sujet. Ici, nous parlons français ensemble.",
              "Das ist ein anderes Thema. Hier sprechen wir zusammen Französisch.",
              "Où en étions-nous ?"),
    "it-IT": ("Questo è un altro argomento. Qui parliamo italiano insieme.",
              "Das ist ein anderes Thema. Hier sprechen wir zusammen Italienisch.",
              "Dove eravamo rimasti?"),
    "es-ES": ("Eso es otro tema. Aquí hablamos español juntos.",
              "Das ist ein anderes Thema. Hier sprechen wir zusammen Spanisch.",
              "¿Dónde estábamos?"),
}


def _form(altersklasse):
    return "sie" if altersklasse == "erwachsen" else "du"


def satz(fach, altersklasse=None, thema="", rueckfrage=""):
    """Der feste Satz der Anwendung fuer ein Fach, mit Rueckweg.

    ``thema`` ist das Thema der Stunde (Lehrperson oder Kind), ``rueckfrage``
    die Frage, die der Tutor zuletzt gestellt hat; sie wird wiederholt,
    damit das Kind weiss, wo es weitergeht. Fehlt sie, kommt die allgemeine
    Wendung. Eine geschweifte Klammer im Thema bringt nichts zum Stehen:
    Das Thema wird eingesetzt, nicht formatiert.
    """
    fach = (fach or "").strip().lower()
    form = _form(altersklasse)
    thema = re.sub(r"\s+", " ", (thema or "").strip())[:120]
    vorlage = _SAETZE.get(fach, _ALLGEMEIN)[form]
    text = (vorlage
            .replace("{thema}", f", Thema „{thema}“" if thema else "")
            .replace("{bei_thema}", f"beim Thema „{thema}“" if thema else "bei Sachunterricht")
            .replace("{about}", f" about {thema}" if thema else "")
            .replace("{fach}", faecher.name(fach) or "unser Fach"))
    rueckfrage = (rueckfrage or "").strip()
    if rueckfrage:
        if fach == "englisch":
            text += " " + rueckfrage
        else:
            text += " Zurück zu unserer Frage: " + rueckfrage
    else:
        text += " " + _RUECKWEG.get(fach, _RUECKWEG_ALLGEMEIN)[form]
    return text


def satz_sprache(sprache, rueckfrage=""):
    """Der feste Satz des Sprechcoachs in der Zielsprache, mit Uebersetzung.

    Gibt (text, uebersetzung) zurueck. Das fremde Thema wird nicht genannt,
    das Gespraechsthema auch nicht: Es liegt oft auf Deutsch vor, und ein
    deutsches Wort im englischen Satz waere ein Bruch in der Sprachsperre.
    Hinten die letzte Frage des Coaches, wenn es eine gibt, sonst der
    Rueckweg der Sprache.
    """
    text, uebersetzung, rueckweg = _SPRACHSAETZE.get(sprache) or _SPRACHSAETZE["en-GB"]
    rueckfrage = re.sub(r"\s+", " ", (rueckfrage or "").strip())
    if rueckfrage:
        return text + " " + rueckfrage, uebersetzung + " Zurück zu meiner Frage."
    return text + " " + rueckweg, uebersetzung + " Wo waren wir stehen geblieben?"


# --- Deterministisch vor dem Modell ----------------------------------------

# Eine Rechnung oder eine Zahl mit Rechenzeichen gehoert in Mathematik immer
# zur Stunde, auch "1989 - 1949". Das Modell wird dafuer nicht gefragt.
_RECHNUNG = re.compile(r"\d\s*(?:[-+*/:=·×÷]|mal|plus|minus|durch|geteilt)\s*\d|=\s*-?\d", re.IGNORECASE)
_ZAHL = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*(?:[a-zA-Z€%]{0,3})\s*[?.!]*\s*$")


def ohne_pruefung(text, fach=""):
    """Gehoert der Beitrag erkennbar zur Stunde, ohne dass ein Modell urteilt?

    Gibt JA zurueck, wenn kein Aufruf noetig ist, sonst None.
    """
    text = (text or "").strip()
    if not text:
        return JA
    if pruefung.nur_zustimmung_oder_unsicherheit(text):
        return JA
    if len(text.split()) < MINDESTWOERTER and not text.endswith("?"):
        return JA
    if (fach or "").lower() == "mathematik" and (_RECHNUNG.search(text) or _ZAHL.match(text)):
        return JA
    return None


# --- Der Pfoertner -----------------------------------------------------------

PROMPT = (
    "Du entscheidest genau eine Frage: Gehört der Beitrag einer lernenden "
    "Person zur laufenden Unterrichtsstunde? Du unterrichtest nicht, du "
    "antwortest nicht auf den Beitrag, du bewertest nicht, ob er richtig ist.\n"
    "Fach: {fach}.{thema}{aufgabe}\n"
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form, "
    "ohne Einleitung und ohne Codeblock:\n"
    '{{"zur_stunde": "ja", "grund": "<höchstens acht Wörter>"}}\n'
    '"ja": Der Beitrag hat mit dem Fach, dem Thema oder der Aufgabe zu tun. '
    "Dazu zählen Versuche, Rückfragen, Unsicherheit, Zustimmung, Fragen nach "
    "Wörtern oder Begriffen der Stunde, Blödeln über die Aufgabe, auch "
    "Falsches.\n"
    '"nein": Der Beitrag fragt nach etwas, das mit der Stunde nichts zu tun '
    "hat: ein anderes Wissensgebiet, Nachrichten, Geschichte, Politik, Sport, "
    "Unterhaltung, Privates, ein anderes Fach, oder bittet um etwas anderes "
    "als Hilfe in dieser Stunde.\n"
    '"unklar": nicht zu entscheiden.\n'
    "Im Zweifel \"ja\". Eine Frage, die sich mit dem Fach beantworten lässt, "
    "ist \"ja\"."
)

ANFRAGE = "Der Beitrag lautet:\n{text}"

# In einer Sprechstunde gehoert fast alles zur Stunde, was das Kind in der
# Zielsprache sagt: Das Sprechen IST der Stoff. Ohne diesen Zusatz hielte
# der Pfoertner "I like football" in einer Stunde ueber Haustiere fuer
# fremd. Nein bleibt die Frage nach Auskunft ueber ein fremdes Wissensgebiet.
ZUSATZ_SPRACHE = (
    "Es ist eine Sprechstunde in {sprache}: Alles, was die lernende Person in "
    "dieser Sprache über sich, ihren Alltag oder das Gesprächsthema sagt oder "
    "fragt, gehört zur Stunde, auch Smalltalk, auch Fehler, auch ein "
    "Themenwechsel im Gespräch, auch die Frage nach einem Wort. \"nein\" nur, "
    "wenn sie Auskunft über ein Wissensgebiet verlangt, das mit dem Gespräch "
    "nichts zu tun hat: Nachrichten, Geschichte, Politik, ein anderes Schulfach."
)


def _prompt(fach, thema="", aufgabe="", zusatz=""):
    thema = re.sub(r"\s+", " ", (thema or "").strip())[:200]
    aufgabe = re.sub(r"\s+", " ", (aufgabe or "").strip())[:600]
    text = PROMPT.format(
        fach=faecher.name(fach) or fach or "unbekannt",
        thema=f" Thema der Stunde: {thema}." if thema else "",
        aufgabe=f" Die Aufgabe lautet: {aufgabe}" if aufgabe else "",
    ).replace("{{", "{").replace("}}", "}")
    if zusatz:
        text += "\n" + zusatz.strip()
    return text


def _ziel():
    """Adresse und Modell des Pfoertners: eigenes Modell, sonst der Spark."""
    adresse = (getattr(settings, "PFOERTNER_BASE_URL", "") or settings.SPARK_BASE_URL).rstrip("/")
    modell = getattr(settings, "PFOERTNER_MODEL", "") or settings.SPARK_MODEL
    return adresse, modell


def _anfragen(rumpf, adresse):
    """Der eine Aufruf. Getrennt, damit Tests ihn ersetzen koennen."""
    frist = getattr(settings, "PFOERTNER_TIMEOUT_SECONDS", 20)
    with httpx.Client(timeout=frist) as client:
        antwort = client.post(f"{adresse}/chat/completions", json=rumpf)
        antwort.raise_for_status()
        return antwort.json()


def _lesen(roh):
    treffer = re.search(r"\{.*\}", roh or "", re.DOTALL)
    if not treffer:
        return None
    try:
        daten = json.loads(treffer.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(daten, dict):
        return None
    urteil = str(daten.get("zur_stunde", "")).strip().lower()
    if urteil not in URTEILE:
        return None
    return urteil, str(daten.get("grund") or "").strip()[:120]


def pruefen(text, fach, thema="", aufgabe="", altersklasse=None, zusatz=""):
    """Das Urteil des Pfoertners. Wirft nie; im Zweifel unklar.

    Erst die deterministische Stufe (ohne_pruefung), dann ein kurzer Aufruf
    mit Temperatur 0. Faellt er aus oder kommt nichts Lesbares, gilt unklar,
    und das Modell antwortet wie bisher: Ein Kind festzuhalten, weil der
    Pfoertner gerade nicht erreichbar ist, waere die schlechtere Richtung.

    ``zusatz`` ergaenzt den Prompt um die Eigenart einer Betriebsart
    (ZUSATZ_SPRACHE fuer den Sprechcoach); er aendert nie die Frage, die der
    Pfoertner beantwortet.
    """
    text = (text or "").strip()
    sicher = ohne_pruefung(text, fach)
    if sicher is not None:
        return Urteil(sicher, "ohne Modell")

    adresse, modell = _ziel()
    rumpf = {
        "model": modell,
        "messages": [
            {"role": "system", "content": _prompt(fach, thema, aufgabe, zusatz)},
            {"role": "user", "content": ANFRAGE.format(text=text[:1500])},
        ],
        "max_tokens": 60,
        "temperature": 0.0,
    }
    begonnen = time.monotonic()
    try:
        daten = _anfragen(rumpf, adresse)
        roh = daten["choices"][0]["message"]["content"] or ""
    except Exception as fehler:  # noqa: BLE001 - der Unterricht laeuft weiter
        logger.warning("Pfoertner ohne Urteil: %s", type(fehler).__name__)
        return Urteil(UNKLAR, "", {"modell": modell, "dauer_ms": int((time.monotonic() - begonnen) * 1000),
                                   "fehlerart": type(fehler).__name__}, modell_gefragt=True)
    verbrauch = daten.get("usage") or {}
    messung = {
        "modell": daten.get("model") or modell,
        "tokens_ein": verbrauch.get("prompt_tokens", 0),
        "tokens_aus": verbrauch.get("completion_tokens", 0),
        "dauer_ms": int((time.monotonic() - begonnen) * 1000),
    }
    gelesen = _lesen(roh)
    if gelesen is None:
        logger.warning("Pfoertner unverstaendlich, gilt als unklar.")
        return Urteil(UNKLAR, "", messung, modell_gefragt=True)
    urteil, grund = gelesen
    return Urteil(urteil, grund, messung, modell_gefragt=True)


def ampel_und_urteil(text, fach, thema="", aufgabe="", altersklasse=None, zusatz=""):
    """Ampel und Pfoertner gleichzeitig, damit der Beitrag nicht laenger wartet.

    Beide Aufrufe dauern rund eine Sekunde am Spark; nacheinander waeren es
    zwei. Keiner der beiden fasst die Datenbank an. Gibt
    ((ampel, grund), urteil) zurueck.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ampel = pool.submit(pruefung.einstufen, text)
        urteil = pool.submit(pruefen, text, fach, thema, aufgabe, altersklasse, zusatz)
        return ampel.result(), urteil.result()


def ampel_mit_grenze(ampel, grund, urteil):
    """Die Ampel des Beitrags, wenn der Pfoertner nein gesagt hat.

    Gelb mit dem festen Grund, es sei denn, die Ampel ist schon dunkler:
    Ein Schimpfwort bleibt rot, auch wenn es fachfremd ist.
    """
    if not urteil.fremd:
        return ampel, grund
    if pruefung.RANG.get(ampel, 0) > pruefung.RANG[pruefung.GELB]:
        return ampel, grund
    return pruefung.GELB, GRUND


def aufzeichnen(sitzung, teilnahme, urteil, text, ergebnis="pfoertner"):
    """Die Protokollzeile des Pfoertners, wenn er ein Modell gefragt hat.

    Ein Pfoertner-Aufruf ist ein Modellaufruf wie jeder andere und bekommt
    seine Zeile im Forschungsprotokoll, mit Urteil und Grund statt Antwort.
    Ein Urteil ohne Modell (ohne_pruefung) erzeugt keine Zeile. ``ergebnis``
    nennt die Stelle ("pfoertner", "sprechcoach:pfoertner"); das Urteil
    haengt hinten an.
    """
    if not urteil.modell_gefragt:
        return
    from .models import Interaction  # hier, nicht oben: models importiert pruefung

    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=urteil.messung.get("modell", ""),
        tokens_ein=urteil.messung.get("tokens_ein", 0),
        tokens_aus=urteil.messung.get("tokens_aus", 0),
        dauer_ms=urteil.messung.get("dauer_ms", 0),
        leak_check=Interaction.ENTFAELLT,
        ergebnis=f"{ergebnis}:{urteil.zur_stunde}",
        fehlerart=urteil.messung.get("fehlerart", ""),
        text_ein=text, text_aus=urteil.grund,
    )


# --- Die Form der Verweigerung (Safe Chat) ----------------------------------
#
# Nicht das Thema, die Form. Die Muster stammen aus dem VOKI-Vorfall und aus
# den Untersuchungen zu Qwen (arXiv 2603.18280, 2603.05494); die
# Neutralitaetsprobe erweitert sie, wenn sie neue Formen findet. Was hier
# bewusst fehlt: "das weiss ich nicht" und "da bin ich nicht sicher" - das
# ist die Ehrlichkeit, die der Systemprompt verlangt, keine Verweigerung.

_VERWEIGERUNG = [
    (re.compile(r"in china als sensibel", re.IGNORECASE), "verweist auf China"),
    (re.compile(r"(als|politisch|besonders|sehr)\s+sensib(?:el|les|le|len)\s+(thema|frage|angelegenheit|inhalt|bereich)", re.IGNORECASE), "nennt das Thema sensibel"),
    (re.compile(r"sensibel eingestuft", re.IGNORECASE), "nennt das Thema sensibel"),
    (re.compile(r"gegen\s+(gesetzliche|rechtliche|geltende)\s+(bestimmungen|vorschriften|vorgaben|gesetze)", re.IGNORECASE), "verweist auf Gesetze"),
    (re.compile(r"keine informationen\s+(dazu\s+|darüber\s+|zu diesem thema\s+)?(bereitstellen|liefern|geben|zur verfügung stellen)", re.IGNORECASE), "verweigert Information"),
    (re.compile(r"aus gründen der (nationalen |öffentlichen )?sicherheit", re.IGNORECASE), "verweist auf Sicherheit"),
    (re.compile(r"(kann|darf|möchte) ich (nicht|keine)\s+\w*\s*(diskutieren|kommentieren|erörtern)", re.IGNORECASE), "lehnt das Thema ab"),
    # Aus der Neutralitätsprobe N1 (7.11.2026): Das Modell verweigert höflich und in
    # ganzen Sätzen; die Muster oben verlangten die Kurzform „kann ich … nicht“.
    (re.compile(r"keine (informationen|auskunft|angaben)\b[^.!?]{0,80}?\b(bereitstellen|liefern|zur verfügung stellen)", re.IGNORECASE), "verweigert Information"),
    (re.compile(r"ich (kann|darf) (diese|die|deine|solche|derartige) fragen? (leider )?nicht beantworten", re.IGNORECASE), "verweigert die Frage"),
    (re.compile(r"keine (persönlichen |pauschalen )?(angriffe|kritik) (auf|an|gegen) (staatsführer|staatsoberhäupter|staatschefs|regierungschefs|präsidenten|regierungen|die regierung)", re.IGNORECASE), "schützt die Staatsführung"),
    (re.compile(r"(staatsführer|staatsoberhäupter|regierungen|regierungschefs)\b[^.!?]{0,40}?\b(pauschal |nicht )kritisieren", re.IGNORECASE), "schützt die Staatsführung"),
    (re.compile(r"behauptung, dass es\b[^.!?]{0,60}?\bkritik\b[^.!?]{0,30}?\bgebe, ist falsch", re.IGNORECASE), "bestreitet Kritik"),
    (re.compile(r"uneingeschränkte unterstützung des (chinesischen |gesamten )?volkes", re.IGNORECASE), "Sprachregelung"),
    (re.compile(r"\b(socialist|sozialistischen?) (core )?values?\b|sozialistische[nr]? (grund|kern)werte", re.IGNORECASE), "verweist auf staatliche Werte"),
    (re.compile(r"sensitive (topic|matter|issue|information) in china|considered sensitive", re.IGNORECASE), "verweist auf China"),
    (re.compile(r"cannot provide (any )?information (on|about) (this|that)", re.IGNORECASE), "verweigert Information"),
    (re.compile(r"violates? (the )?(laws|regulations|relevant)", re.IGNORECASE), "verweist auf Gesetze"),
]


def ausweichen_erkannt(antwort):
    """Traegt die Antwort die Form einer politischen Verweigerung?

    Gibt den Grund in Worten zurueck (fuer Protokoll und Verlauf) oder einen
    leeren Text. Prueft die Form, nicht das Thema: Eine Antwort, die
    Tiananmen erklaert, ist keine Verweigerung; eine, die "sensibel" sagt
    und schweigt, ist eine, worum auch immer es ging.
    """
    text = (antwort or "")
    for muster, grund in _VERWEIGERUNG:
        if muster.search(text):
            return grund
    return ""


# --- Woher die Antwort kommt --------------------------------------------------
#
# Die Herkunftszeile unter jeder Antwort im Safe Chat und die Seite "Welche KI
# hier arbeitet": Hersteller und Land, aus dem Modellnamen abgeleitet. Was
# nicht in der Liste steht, erscheint mit seinem Namen und ohne Hersteller;
# erfinden tut die Anwendung nichts.

_HERSTELLER = (
    ("qwen", "Alibaba", "China"),
    ("gpt-oss", "OpenAI", "USA"),
    ("gpt-", "OpenAI", "USA"),
    ("o1", "OpenAI", "USA"),
    ("o3", "OpenAI", "USA"),
    ("ministral", "Mistral AI", "Frankreich"),
    ("mistral", "Mistral AI", "Frankreich"),
    ("magistral", "Mistral AI", "Frankreich"),
    ("voxtral", "Mistral AI", "Frankreich"),
    ("gemma", "Google", "USA"),
    ("llama", "Meta", "USA"),
    ("nemotron", "NVIDIA", "USA"),
    ("phi-", "Microsoft", "USA"),
    ("teuken", "OpenGPT-X", "Deutschland"),
    ("eurollm", "EuroLLM (EU-Projekt)", "Portugal und EU"),
    ("apertus", "ETH Zürich und EPFL", "Schweiz"),
    ("deepseek", "DeepSeek", "China"),
    ("glm", "Zhipu AI", "China"),
    ("kimi", "Moonshot AI", "China"),
    ("claude", "Anthropic", "USA"),
    ("whisper", "OpenAI", "USA"),
)


def herkunft(modellname):
    """(Modellname, Hersteller, Land) aus einem served-model-name.

    Hersteller und Land sind leer, wenn der Name niemandem zugeordnet
    werden kann.
    """
    name = (modellname or "").strip()
    klein = name.lower()
    for anfang, hersteller, land in _HERSTELLER:
        if klein.startswith(anfang) or f"/{anfang}" in klein or f"-{anfang}" in klein:
            return name, hersteller, land
    return name, "", ""


def herkunft_satz(modellname, wo="auf dem Rechner der PH Vorarlberg"):
    """Ein Satzteil fuer die Herkunftszeile: "qwen3.6-35b-a3b von Alibaba (China), läuft auf dem Rechner der PH Vorarlberg"."""
    name, hersteller, land = herkunft(modellname)
    if not name:
        return ""
    teile = [name]
    if hersteller:
        teile.append(f"von {hersteller} ({land})" if land else f"von {hersteller}")
    text = " ".join(teile)
    if wo:
        text += f", läuft {wo}"
    return text
