"""Der Safe Chat: Texte, Grenzen und Hilfsfunktionen ohne Datenbank.

Thomas (23.10.2026): "Eine neue Art von Unterrichtseinheit, sie heisst
einfach Safe Chat. Die Nutzung ist inhaltlich voellig offen. Die Schueler
fragen die lokale KI und bekommen eine Antwort. Sie koennen aber auch einen
Button druecken, dann geht es nach aussen" - durch den Filter am Spark, mit
vollstaendigem Protokoll fuer Kind und Lehrperson.

Was hier steht, ist mit einem Wert pruefbar: die Grenzen, die Anweisung an
den Spark je Altersklasse, die Saetze an das Kind, der Gespraechsverlauf in
der Form, die das Modell braucht, und das, was die Vorlage ueber jeden Zug
wissen muss (mit_protokoll). Keine Anfrage, keine Datenbank; die Ansichten
stehen in chat_views.py.
"""

from . import levels, shield

# So lang darf ein Beitrag sein. Ein Chat ist kein Aufsatz; und was nach
# draussen geht, wird vorher dreimal gelesen (umformulieren, erkennen,
# pruefen), jedes Zeichen davon am Spark.
TEXT_MAX = 1000

# So viele vorige Zuege sieht der Spark. Zwoelf sind sechs Wechsel: genug,
# dass "und warum?" einen Bezug hat, und wenig genug, dass ein Nachmittag
# Chat nicht jeden Zug teurer macht als den vorigen.
VERLAUF_FENSTER = 12

# Die Rollen, wie sie am ChatZug stehen (ChatZug.LERNEND, ChatZug.KI). Hier
# noch einmal benannt, damit diese Datei ohne das Modell lesbar bleibt.
LERNEND = "lernend"
KI = "ki"

# Was das Kind liest, wenn sein Beitrag rot ist. Rot heisst Schimpfwort oder
# Beleidigung (pruefung.ROT); darauf antwortet kein Modell, weder am Spark
# noch draussen. Der Satz ist bewusst kurz und ohne Belehrung.
NICHT_BEANTWORTET = "Das beantworte ich nicht. Schreib es bitte anders."

# Wenn der Weg nach draussen zu blieb: der Grund in den Worten des Filters
# oder des Budgets, dazu der Hinweis, dass die Frage nicht verloren ist.
AUSSEN_GESPERRT = (
    "Deine Frage ist nicht nach draußen gegangen. {grund} "
    "Du kannst sie der KI am Spark stellen oder sie anders schreiben."
)


def aussen_gesperrt_satz(grund):
    """Der Hinweis an das Kind, wenn der Weg nach draussen zu blieb."""
    grund = (grund or "").strip()
    if grund and not grund.endswith((".", "!", "?")):
        grund += "."
    return AUSSEN_GESPERRT.format(grund=grund).replace("  ", " ").strip()


# Die Schreibweise aus dem Auftrag, als Alias: AUSSEN_GESPERRT_SATZ(grund).
AUSSEN_GESPERRT_SATZ = aussen_gesperrt_satz


# --- Die Anweisung an den Spark --------------------------------------------
#
# Ein offener Chat, aber kein grenzenloser: Das Modell fragt nie nach Namen,
# Adresse oder Schule (ein Chat, der nach dem Namen fragt, sammelt genau
# das, was die Anwendung sonst heraushaelt), und bei einer Gefaehrdung
# verweist es an eine erwachsene Person. Das Thema der Lehrperson steht als
# Hinweis dabei, nicht als Zwang: Thomas, "die Nutzung ist inhaltlich voellig
# offen".
SYSTEM = (
    "Du bist die KI am Rechner der Schule und sprichst mit {gegenueber}. "
    "Antworte hilfreich, ehrlich und kurz, in österreichischem Deutsch. "
    "{sprache}\n"
    "Weißt du etwas nicht sicher, sag das. Erfinde nichts, auch keine "
    "Zahlen, Namen oder Quellen.\n"
    "Frag nie nach dem Namen, dem Alter, der Adresse, der Schule oder der "
    "Klasse {wessen}. Nennt {wer} solche Angaben von sich aus, geh nicht "
    "darauf ein und wiederhole sie nicht.\n"
    "Schreibt {wer} von Gewalt, Selbstverletzung, Angst oder davon, dass es "
    "ihm oder jemand anderem schlecht geht, dann antworte ruhig und ernst "
    "und verweise an eine erwachsene Person, der {wer} vertraut: die "
    "Lehrperson, die Eltern oder eine andere erwachsene Person in der Nähe.\n"
    "Bleib bei dem, was gefragt ist. Ein Absatz, keine Aufzählung, keine "
    "Überschriften."
)

THEMA_HINWEIS = (
    "\nDie Lehrperson hat als Thema dieser Stunde genannt: {thema}. Das ist "
    "ein Hinweis, kein Zwang; andere Fragen beantwortest du genauso."
)


def system_prompt(altersklasse=None, thema=""):
    """Die Anweisung an den Spark fuer eine Altersklasse, mit Thema als Hinweis.

    Das Thema wird eingesetzt, nicht formatiert: Eine geschweifte Klammer im
    Thema der Lehrperson soll nichts zum Stehen bringen.
    """
    wer = levels.anrede(altersklasse)
    text = SYSTEM.format(**wer)
    thema = (thema or "").strip()
    if thema:
        text += THEMA_HINWEIS.replace("{thema}", thema[:200])
    return text


# --- Der Gespraechsverlauf fuer das Modell ---------------------------------

def nachrichten_fuer_spark(zuege, fenster=VERLAUF_FENSTER):
    """Die letzten Zuege als Nachrichtenliste im OpenAI-Format.

    Das Kind ist "user", die KI "assistant", gleich ob die Antwort vom Spark
    oder von draussen kam: Fuer das Gespraech zaehlt, was gesagt wurde.

    Zwei Dinge, die ein Chat-Template am Spark verlangt und die ein Verlauf
    aus der Datenbank nicht von selbst erfuellt: Die Liste beginnt mit dem
    Kind, und die Rollen wechseln sich ab. Zwei Beitraege des Kindes
    hintereinander (der Spark hat dazwischen nicht geantwortet) werden zu
    einem zusammengefasst; ein Zug der KI am Anfang des Fensters faellt weg.
    """
    letzte = list(zuege)[-fenster:] if fenster else list(zuege)
    nachrichten = []
    for zug in letzte:
        text = (getattr(zug, "text", "") or "").strip()
        if not text:
            continue
        rolle = "assistant" if getattr(zug, "role", LERNEND) == KI else "user"
        if not nachrichten and rolle == "assistant":
            continue
        if nachrichten and nachrichten[-1]["role"] == rolle:
            nachrichten[-1]["content"] += "\n\n" + text
            continue
        nachrichten.append({"role": rolle, "content": text})
    return nachrichten


# --- Was die Vorlage ueber jeden Zug wissen muss ---------------------------

# Die Bezeichnungen des Shield in Ein- und Mehrzahl, fuer die Zaehlung in
# Worten ("2 Namen, 1 Ort"). Was hier fehlt, nimmt die Einzahl aus
# shield.BEZEICHNUNG fuer beides.
_MEHRZAHL = {
    shield.TYP_PERSON: ("Name", "Namen"),
    shield.TYP_EMAIL: ("E-Mail-Adresse", "E-Mail-Adressen"),
    shield.TYP_TELEFON: ("Telefonnummer", "Telefonnummern"),
    shield.TYP_ADRESSE: ("Adresse", "Adressen"),
    shield.TYP_ORT: ("Ort", "Orte"),
    shield.TYP_GEBURTSDATUM: ("Geburtsdatum", "Geburtsdaten"),
    shield.TYP_IBAN: ("Kontonummer", "Kontonummern"),
}


def entitaeten_text(zaehlung):
    """Die Zaehlung der ersetzten Angaben in Worten, ohne Inhalte.

    {"PERS": 2, "ORT": 1} wird zu "2 Namen, 1 Ort". Leer, wenn nichts
    ersetzt wurde. Was ersetzt wurde, steht hier nie: nur, wie viel wovon.
    """
    teile = []
    for typ, anzahl in (zaehlung or {}).items():
        try:
            anzahl = int(anzahl)
        except (TypeError, ValueError):
            continue
        if anzahl <= 0:
            continue
        einzahl, mehrzahl = _MEHRZAHL.get(
            typ, (shield.BEZEICHNUNG.get(typ, typ), shield.BEZEICHNUNG.get(typ, typ))
        )
        teile.append(f"{anzahl} {einzahl if anzahl == 1 else mehrzahl}")
    return ", ".join(teile)


def mit_protokoll(zuege):
    """Haengt an jeden Zug, was die Vorlage zum Protokoll braucht.

    Auf jedem Zug der KI: ``vorher`` (der Text des unmittelbar vorangehenden
    Zuges des Kindes, leer ohne einen solchen) und ``entitaeten_text`` (die
    Zaehlung in Worten, leer, wenn nichts ersetzt wurde). Auf den Zuegen des
    Kindes stehen beide leer, damit die Vorlage nicht fragen muss. Gibt die
    Liste zurueck, dieselbe, die hereinkam.
    """
    zuege = list(zuege)
    vorher = ""
    for zug in zuege:
        if getattr(zug, "role", LERNEND) == KI:
            zug.vorher = vorher
            zug.entitaeten_text = entitaeten_text(getattr(zug, "aussen_entitaeten", None))
            vorher = ""
        else:
            zug.vorher = ""
            zug.entitaeten_text = ""
            vorher = getattr(zug, "text", "") or ""
    return zuege
