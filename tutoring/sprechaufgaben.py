"""Gesprächsaufgaben für den Sprechcoach: ein Ziel und eine Informationslücke.

WARUM AUFGABEN UND NICHT „LASS UNS ÜBER X REDEN"

Regel 11 des Berichts (docs/Gesprächsdidaktik Englisch für den
Sprechcoach.md) hat die stärkste Evidenz des ganzen Briefs: Geführte,
zielorientierte Dialoge erreichen d = 0,97, aufgabenorientierte 0,50, freies
Plaudern ist nicht signifikant (Bibauw et al. 2022). Zwei-Wege-Aufgaben mit
einem konvergenten Ergebnis erzeugen mehr Bedeutungsaushandlung als
Meinungsaustausch (Pica et al. 1993). Und nur die Hälfte der Zehnjährigen
kann nach vier Jahren Englisch Fragen stellen (Szpotowicz 2012) – also muss
das Kind fragen, nicht nur antworten.

Deshalb hat jede Aufgabe:

- ein ZIEL, das am Ende herausgefunden oder vereinbart sein muss,
- ein GEHEIMNIS, das nur der Coach kennt und das Kind erfragen muss (die
  Informationslücke),
- einen WECHSEL, in dem der Coach fragt und das Kind antwortet (Regel 11:
  „mindestens eine Phase kehrt die Rollen um"),
- eine zweite ROLLE für die Wiederholung (Regel 12: dieselbe Aufgabe mit
  demselben Inhalt, Coach in leicht anderer Rolle; Bygate 2018, Sun & Révész
  2021),
- REDEMITTEL als Stütze für die Planungsminute (Regel 12, „think first"),
- und eine ABSCHLUSSPRÜFUNG, die der Server ohne Modell auswertet.

WIE DER ABSCHLUSS GEPRÜFT WIRD

Deterministisch, über Schlüsselwörter: Jede Aufgabe hat zwei bis drei
Merkmale, und jedes Merkmal ist erfüllt, sobald das Kind EINES seiner Wörter
selbst gesagt hat. Das Kind muss das Ergebnis also aussprechen, nicht bloß
gehört haben – das ist der konvergente Ausgang, und es ist zählbar. Ein
Systemprompt ist eine Bitte; ob das Ziel erreicht ist, entscheidet der Server.

Merkmale mit `geheim=True` gehören zum Geheimnis des Coachs. Der Server prüft
auch, dass der Coach sie nicht unaufgefordert ausplaudert (siehe
sprechablauf.verraet_zu_viel). Merkmale ohne Geheimnis sind etwa eine
Begründung („because") – die soll der Coach ruhig selbst vormachen.

WIE EINE AUFGABE DAZUKOMMT

Ein Eintrag in AUFGABEN. Die Texte für das Kind und das Modell sind
englisch, die für die Lehrperson deutsch. Schlüsselwörter klein und so, wie
Whisper sie schreibt: Ziffern UND Zahlwörter.
"""

import re

from . import sprechcoach

FREI = "frei"

_WORT_MIT_APOSTROPH = re.compile(r"[\w']+", re.UNICODE)

# Die Dialogtypen nach dem E8-Format (IQS): ein kurzes Alltagsgespräch und
# ein längeres Meinungsgespräch.
KURZ = "kurz"
LANG = "lang"


def _merkmal(was, woerter, geheim=True):
    return {"was": was, "woerter": tuple(woerter), "geheim": geheim}


AUFGABEN = (
    {
        "schluessel": "tierarzt",
        "titel": "Beim Tierarzt: ein Tier kennenlernen",
        "niveaus": ("A1",),
        "typ": KURZ,
        "fuer": "Volksschule, 1. Klasse Sek I",
        "ziel": "Find out: What animal is it? What is its name? How old is it?",
        "ziel_deutsch": "Finde heraus: Was für ein Tier ist es, wie heißt es, "
                        "und wie alt ist es?",
        "rolle_coach": "a friendly vet. An animal is in your clinic today.",
        "rolle_wiederholung": "the vet's helper at the front desk of the clinic.",
        "geheimnis": "The animal is a rabbit. Its name is Hoppy. It is two "
                     "years old. It is white and it likes carrots.",
        "wechsel": "Now you ask the child about a pet: their own pet, or a pet "
                   "they would like. Ask for the name, then the age or colour.",
        "redemittel": ("What animal is it?", "What's its name?",
                       "How old is it?", "What colour is it?"),
        "abschluss_pruefung": (
            _merkmal("Tier", ("rabbit", "bunny")),
            _merkmal("Name", ("hoppy",)),
            _merkmal("Alter", ("two", "2")),
        ),
    },
    {
        "schluessel": "jausenstand",
        "titel": "Am Jausenstand einkaufen",
        "niveaus": ("A1",),
        "typ": KURZ,
        "fuer": "Volksschule, 1. Klasse Sek I",
        "ziel": "Buy something to eat and something to drink. "
                "Find out how much it is.",
        "ziel_deutsch": "Kauf etwas zu essen und etwas zu trinken, und finde "
                        "heraus, was es kostet.",
        "rolle_coach": "the seller at the school snack stand.",
        "rolle_wiederholung": "the seller at a snack stand at the swimming pool.",
        "geheimnis": "You sell: apples (50 cents), sandwiches (2 euros), "
                     "muffins (1 euro), apple juice (1 euro), water (50 cents). "
                     "There is no pizza today.",
        "wechsel": "Now you are the customer and the child is the seller. "
                   "Ask the child what they have and how much it is.",
        "redemittel": ("Can I have ..., please?", "Do you have ...?",
                       "How much is it?", "Here you are. Thank you!"),
        "abschluss_pruefung": (
            _merkmal("Essen", ("apple", "apples", "sandwich", "sandwiches",
                               "muffin", "muffins")),
            _merkmal("Getränk", ("juice", "water")),
            _merkmal("Preis", ("euro", "euros", "cent", "cents")),
        ),
    },
    {
        "schluessel": "geburtstag",
        "titel": "Eine Einladung zum Geburtstag",
        "niveaus": ("A1", "A2"),
        "typ": KURZ,
        "fuer": "Volksschule, Sek I",
        "ziel": "Find out: When is the party? What time? Where is it?",
        "ziel_deutsch": "Finde heraus: An welchem Tag ist die Feier, um wie "
                        "viel Uhr, und wo?",
        "rolle_coach": "a friend from another class. You invite the child to "
                       "your birthday party.",
        "rolle_wiederholung": "the friend's older brother or sister, who calls "
                              "to tell the child about the party.",
        "geheimnis": "The party is on Saturday. It starts at three o'clock. "
                     "It is at the swimming pool. The child should bring a "
                     "towel.",
        "wechsel": "Now you ask the child about their own birthday: when it "
                   "is and what they like to do on their birthday.",
        "redemittel": ("When is the party?", "What time is it?",
                       "Where is it?", "Can I bring ...?"),
        "abschluss_pruefung": (
            _merkmal("Tag", ("saturday",)),
            _merkmal("Uhrzeit", ("three", "3")),
            _merkmal("Ort", ("pool", "swimming")),
        ),
    },
    {
        "schluessel": "weg",
        "titel": "Nach dem Weg fragen",
        "niveaus": ("A2",),
        "typ": KURZ,
        "fuer": "Sek I (E8 Short Dialogue)",
        "ziel": "Find out how to get to the museum and how long it takes.",
        "ziel_deutsch": "Finde heraus, wie du zum Museum kommst und wie lange "
                        "es dauert.",
        "rolle_coach": "a person in the street in a small English town. You "
                       "know the way to the museum.",
        "rolle_wiederholung": "a bus driver at the bus stop who knows the way "
                              "to the museum.",
        "geheimnis": "Go straight on, then turn left at the bank. The museum "
                     "is next to the park. It takes ten minutes on foot. "
                     "Bus number 12 is faster.",
        "wechsel": "Now you are new in the child's town. Ask the child how "
                   "to get from their school to a shop or the station.",
        "redemittel": ("Excuse me, how do I get to ...?", "Is it far?",
                       "Do I turn left or right?", "How long does it take?"),
        "abschluss_pruefung": (
            _merkmal("Richtung", ("left",)),
            _merkmal("Orientierung", ("park", "bank")),
            _merkmal("Dauer", ("ten", "10", "twelve", "12")),
        ),
    },
    {
        "schluessel": "wochenende",
        "titel": "Was war am Wochenende?",
        "niveaus": ("A2",),
        "typ": KURZ,
        "fuer": "Sek I",
        "ziel": "Find out: Where did Sam go last weekend? Who was there? "
                "What was it like?",
        "ziel_deutsch": "Finde heraus, wo Sam am Wochenende war, wer dabei "
                        "war und wie es war.",
        "rolle_coach": "Sam, an exchange student from England. You had an "
                       "exciting weekend.",
        "rolle_wiederholung": "Sam's sister Lucy, who was not there but knows "
                              "everything about Sam's weekend.",
        "geheimnis": "Last Saturday Sam went to a concert in Vienna. Sam went "
                     "with a cousin. It was very loud but great. After the "
                     "concert they ate pizza and took the last train home.",
        "wechsel": "Now you ask the child about their last weekend: where "
                   "they were, who was with them, what it was like.",
        "redemittel": ("Where did you go?", "Who was with you?",
                       "What was it like?", "What did you do then?"),
        "abschluss_pruefung": (
            _merkmal("Wo", ("concert", "vienna")),
            _merkmal("Wer", ("cousin",)),
            _merkmal("Wie", ("loud",)),
        ),
    },
    {
        "schluessel": "treffen",
        "titel": "Ein Treffen vereinbaren",
        "niveaus": ("A2", "B1"),
        "typ": KURZ,
        "fuer": "Sek I, 4. Klasse (E8 Short Dialogue)",
        "ziel": "Agree on a day, a time and something to do together this week.",
        "ziel_deutsch": "Vereinbart einen Tag, eine Uhrzeit und etwas, das "
                        "ihr gemeinsam unternehmt.",
        "rolle_coach": "a friend who wants to meet this week but is very busy.",
        "rolle_wiederholung": "the same friend, a week later, with the same "
                              "busy week.",
        "geheimnis": "Monday: football training. Tuesday: dentist. Wednesday: "
                     "free after four o'clock. Thursday: visiting grandma. "
                     "You would like to go to the cinema or the skate park. "
                     "Say no to every other day, and give the reason.",
        "wechsel": "Now you suggest a plan for the weekend, and the child must "
                   "say if they can come. Ask what they are doing on Saturday.",
        "redemittel": ("Are you free on ...?", "How about ...?",
                       "Sorry, I can't. I have ...", "Let's meet at ..."),
        "abschluss_pruefung": (
            _merkmal("Tag", ("wednesday",)),
            _merkmal("Uhrzeit", ("four", "five", "six", "4", "5", "6")),
            _merkmal("Unternehmung", ("cinema", "film", "movie", "skate",
                                      "skatepark", "skating")),
        ),
    },
    {
        "schluessel": "geschenk",
        "titel": "Ein Abschiedsgeschenk aussuchen",
        "niveaus": ("B1",),
        "typ": LANG,
        "fuer": "4. Klasse Sek I, Oberstufe Beginn",
        "ziel": "Agree on a present for Ms Brown, and give a reason. "
                "Find out how much you can spend.",
        "ziel_deutsch": "Einigt euch auf ein Geschenk für Ms Brown, mit "
                        "Begründung, und findet heraus, wie viel es kosten darf.",
        "rolle_coach": "a classmate. Your English teacher Ms Brown is leaving, "
                       "and you collect money for a present.",
        "rolle_wiederholung": "the class representative of the parallel class, "
                              "who also wants to buy a present for Ms Brown.",
        "geheimnis": "Ms Brown loves her garden and drinks a lot of tea. She "
                     "does not eat chocolate. The class has thirty euros. You "
                     "first suggest a book, but you can be convinced.",
        "wechsel": "Now you ask the child: what was the best present they ever "
                   "got, and why.",
        "redemittel": ("What does she like?", "How about ...? She loves ...",
                       "I think ... is better, because ...",
                       "How much can we spend?"),
        "abschluss_pruefung": (
            _merkmal("Geschenk", ("plant", "plants", "flower", "flowers",
                                  "tea", "garden", "seeds", "mug", "cup")),
            _merkmal("Begründung", ("because", "since", "so she", "that's why"),
                     geheim=False),
            _merkmal("Betrag", ("thirty", "30")),
        ),
    },
    {
        "schluessel": "klassenfahrt",
        "titel": "Wohin geht die Projektwoche?",
        "niveaus": ("B1", "B2"),
        "typ": LANG,
        "fuer": "Oberstufe (E8 Long Dialogue, Reifeprüfung)",
        "ziel": "Decide together where the project week goes: London or the "
                "lake camp. Give at least one reason and talk about the cost.",
        "ziel_deutsch": "Entscheidet gemeinsam, ob die Projektwoche nach "
                        "London oder ins Seecamp geht – mit Begründung und mit "
                        "Blick auf die Kosten.",
        "rolle_coach": "the class representative of the partner class. You "
                       "would prefer London, but you can be convinced.",
        "rolle_wiederholung": "the class teacher of the partner class, who "
                              "has the same information and prefers the camp.",
        "geheimnis": "London costs 380 euros, the lake camp in Carinthia costs "
                     "180 euros. Six students in your class cannot pay more "
                     "than 200 euros. The camp has sports and no wifi. You "
                     "cannot swim very well, and you do not like to say it.",
        "wechsel": "Now you ask the child about the best trip they have ever "
                   "made, and push for a reason: why was it so good?",
        "redemittel": ("What do you think about ...?",
                       "On the one hand ..., on the other hand ...",
                       "That's a good point, but ...",
                       "Can we agree on ...?", "How much does it cost?"),
        "abschluss_pruefung": (
            _merkmal("Entscheidung", ("london", "camp", "lake", "carinthia"),
                     geheim=False),
            _merkmal("Begründung", ("because", "since", "that's why",
                                    "so that"), geheim=False),
            _merkmal("Kosten", ("380", "180", "200", "afford", "expensive",
                                "cheaper", "cheap")),
        ),
    },
    {
        "schluessel": "handyregel",
        "titel": "Eine Handyregel für die Schule aushandeln",
        "niveaus": ("B2",),
        "typ": LANG,
        "fuer": "Oberstufe (Reifeprüfung, Interessenkonflikt)",
        "ziel": "Negotiate a mobile phone rule for your school that both "
                "sides can accept. Use the survey results.",
        "ziel_deutsch": "Handelt eine Handyregel aus, die beide Seiten "
                        "annehmen können, und nutzt dabei die Ergebnisse der "
                        "Umfrage.",
        "rolle_coach": "a teacher on the school committee. You want a strict "
                       "rule: no phones at school at all.",
        "rolle_wiederholung": "a parent on the school committee who is worried "
                              "about phones but open to a compromise.",
        "geheimnis": "A survey says: 62 percent of the students want to use "
                     "phones in the breaks. Teachers complain about noise in "
                     "the corridors. Parents fear cyberbullying. You would "
                     "accept phones in the lunch break, only in the yard.",
        "wechsel": "Now you ask the child how they use their phone on a normal "
                   "school day, and challenge one of their answers.",
        "redemittel": ("I see your point, but ...",
                       "What if we ...?", "The survey shows that ...",
                       "Would you accept ...?", "Let's agree on ..."),
        "abschluss_pruefung": (
            _merkmal("Umfrage", ("62", "sixty", "survey", "majority")),
            _merkmal("Gegenargument", ("however", "on the other hand",
                                       "although", "but"), geheim=False),
            _merkmal("Kompromiss", ("lunch", "yard", "compromise", "agree",
                                    "only in")),
        ),
    },
)

# Das bisherige Verhalten: Gespräch zum Thema der Lehrperson, ohne Ziel und
# ohne Wiederholung. Bleibt wählbar, weil eine Lehrperson manchmal genau das
# will – aber es ist nicht mehr die Vorgabe. Die Erklärung dazu steht beim
# Anlegen (Bibauw et al. 2022: open-ended nicht signifikant).
FREIES_GESPRAECH = {
    "schluessel": FREI,
    "titel": "Freies Gespräch zum Thema",
    "niveaus": tuple(code for code, _ in sprechcoach.NIVEAUS),
    "typ": "",
    "fuer": "alle",
    "ziel": "",
    "ziel_deutsch": "",
    "rolle_coach": "",
    "rolle_wiederholung": "",
    "geheimnis": "",
    "wechsel": "",
    "redemittel": (),
    "abschluss_pruefung": (),
}

NACH_SCHLUESSEL = {a["schluessel"]: a for a in AUFGABEN}
NACH_SCHLUESSEL[FREI] = FREIES_GESPRAECH

# Aufgaben gibt es nur auf Englisch: Redemittel und Schlüsselwörter sind
# englisch. Eine Sitzung in einer anderen Sprache bekommt das freie Gespräch.
AUFGABEN_SPRACHE = "en-GB"


def aufgabe(schluessel, sprache=AUFGABEN_SPRACHE):
    """Die Aufgabe zu diesem Schlüssel, oder das freie Gespräch.

    Leer und unbekannt heißt: freies Gespräch. Das ist das alte Verhalten,
    und Sitzungen von vor den Aufgaben haben ein leeres Feld.
    """
    if sprache != AUFGABEN_SPRACHE:
        return FREIES_GESPRAECH
    return NACH_SCHLUESSEL.get((schluessel or "").strip(), FREIES_GESPRAECH)


def ist_frei(eintrag):
    return eintrag["schluessel"] == FREI


def fuer_niveau(niveau):
    """Die Aufgaben, die zu diesem Niveau passen, ohne das freie Gespräch."""
    return [a for a in AUFGABEN if niveau in a["niveaus"]]


def passt(schluessel, niveau):
    """Darf diese Aufgabe auf diesem Niveau gewählt werden?"""
    gefunden = NACH_SCHLUESSEL.get(schluessel)
    return gefunden is not None and niveau in gefunden["niveaus"]


def auswahl():
    """Alle wählbaren Schlüssel, für die Prüfung in der Ansicht."""
    return tuple(NACH_SCHLUESSEL)


# --- Der Abschluss --------------------------------------------------------

def _normal(text):
    """Klein, ohne Satzzeichen, mit Leerzeichen außen herum.

    Damit "two" in "I am two." gefunden wird, aber nicht in "twelve", und
    mehrteilige Wendungen wie "on the other hand" als Ganzes.
    """
    # Der Apostroph gehört zum Wort, damit "that's" eines bleibt. Whisper
    # schreibt manchmal den typografischen.
    woerter = _WORT_MIT_APOSTROPH.findall((text or "").lower().replace("’", "'"))
    return " " + " ".join(woerter) + " "


def _enthaelt(normal, wort):
    return " " + wort + " " in normal


def merkmal_erfuellt(merkmal, texte):
    """Hat das Kind in einem dieser Texte eines der Wörter gesagt?"""
    for text in texte:
        normal = _normal(text)
        if any(_enthaelt(normal, w) for w in merkmal["woerter"]):
            return True
    return False


def offene_merkmale(eintrag, texte):
    """Die Merkmale, die das Kind noch nicht selbst gesagt hat."""
    return [m for m in eintrag["abschluss_pruefung"]
            if not merkmal_erfuellt(m, texte)]


def ziel_erreicht(eintrag, texte):
    """Ist das Ziel erreicht? Nur über das, was das Kind gesagt hat.

    Das freie Gespräch hat kein Ziel und ist deshalb nie „erreicht" – es
    endet, wenn das Kind es beendet.
    """
    if ist_frei(eintrag) or not eintrag["abschluss_pruefung"]:
        return False
    return not offene_merkmale(eintrag, texte)


def verraet(text, merkmale):
    """Welche dieser Merkmale nennt der Text?"""
    normal = _normal(text)
    return [m for m in merkmale
            if any(_enthaelt(normal, w) for w in m["woerter"])]
