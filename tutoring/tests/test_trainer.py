"""Pruefungen des Trainers.

Der Trainer ist der Gegenentwurf zur Aufgabenhilfe: Er haelt nichts zurueck,
er erklaert. Was hier geprueft wird, ist deshalb nicht eine Grenze, sondern
eine Fuehrung - und die liegt in der Anwendung, nicht im Modell.

Die drei Pruefungen, auf die es ankommt:
- Bei einem Fehler wechselt die Darstellung, statt dass sich die Erklaerung
  wiederholt.
- Es kommt genau eine Frage je Zug an.
- Der Zustand geht nicht weiter, solange jemand nicht mitkommt, aber er
  bleibt auch nicht ewig stehen.
"""

import pytest
from django.contrib.auth import get_user_model

from tutoring import levels, trainer
from tutoring.models import LearningSession, Participation, TrainerLauf, TrainerZug

pytestmark = pytest.mark.django_db


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


@pytest.fixture
def lauf(lehrperson):
    sitzung = LearningSession.objects.create(
        title="Maßumwandlung", teacher=lehrperson,
        mode=LearningSession.BETRIEB_TRAINER,
    )
    teilnahme = Participation.objects.create(learning_session=sitzung, animal="fuchs")
    return TrainerLauf.objects.create(
        participation=teilnahme, topic="Längenmaße umrechnen"
    )


# --- Die Betriebsart ------------------------------------------------------

def test_die_grundeinstellung_ist_die_aufgabenhilfe(lehrperson):
    sitzung = LearningSession.objects.create(title="Probe", teacher=lehrperson)

    assert sitzung.ist_trainer is False


def test_eine_trainersitzung_erkennt_sich(lauf):
    assert lauf.participation.learning_session.ist_trainer is True


# --- Die Zustandsfolge ----------------------------------------------------

def test_der_lauf_beginnt_beim_thema(lauf):
    assert lauf.zustand == trainer.THEMA


def test_nach_dem_thema_wird_bestaetigt(lauf):
    zustand, _, schleife = trainer.naechster_zustand(lauf, "")

    assert zustand == trainer.BESTAETIGEN
    assert schleife is False


def test_die_einfuehrung_beginnt_gegenstaendlich(lauf):
    """Der leichteste Zugang zuerst, nicht die Formel."""
    lauf.state = trainer.BESTAETIGEN

    zustand, darstellung, _ = trainer.naechster_zustand(lauf, "")

    assert zustand == trainer.EINFUEHRUNG
    assert darstellung == trainer.GEGENSTAENDLICH


def test_wer_mitkommt_geht_eine_darstellungsebene_weiter(lauf):
    lauf.state = trainer.LERNSCHRITT
    lauf.representation = trainer.GEGENSTAENDLICH

    zustand, darstellung, schleife = trainer.naechster_zustand(
        lauf, trainer.VERSTANDEN
    )

    assert zustand == trainer.LERNSCHRITT
    assert darstellung == trainer.BILDLICH
    assert schleife is False


def test_wer_nicht_mitkommt_geht_eine_ebene_zurueck(lauf):
    """Der Kern des Trainers.

    Wer etwas symbolisch nicht versteht, versteht es durch dieselben Symbole
    in anderen Worten auch nicht. Also zurueck ins Bildliche.
    """
    lauf.state = trainer.LERNSCHRITT
    lauf.representation = trainer.SYMBOLISCH

    zustand, darstellung, schleife = trainer.naechster_zustand(lauf, trainer.NICHT)

    assert zustand == trainer.LERNSCHRITT
    assert darstellung == trainer.BILDLICH
    assert schleife is True


def test_unter_dem_gegenstaendlichen_geht_es_nicht_weiter(lauf):
    lauf.state = trainer.LERNSCHRITT
    lauf.representation = trainer.GEGENSTAENDLICH

    _, darstellung, _ = trainer.naechster_zustand(lauf, trainer.NICHT)

    assert darstellung == trainer.GEGENSTAENDLICH


def test_teilweise_bleibt_auf_der_ebene_aber_wiederholt(lauf):
    lauf.state = trainer.LERNSCHRITT
    lauf.representation = trainer.BILDLICH

    zustand, darstellung, schleife = trainer.naechster_zustand(
        lauf, trainer.TEILWEISE
    )

    assert (zustand, darstellung, schleife) == (
        trainer.LERNSCHRITT, trainer.BILDLICH, True
    )


def test_nach_genug_schleifen_geht_es_trotzdem_weiter(lauf):
    """Wer viermal dieselbe Huerde bekommt, hoert auf."""
    lauf.state = trainer.LERNSCHRITT
    lauf.loops = trainer.HOECHSTE_SCHLEIFEN
    lauf.step_no = trainer.SCHRITTE_BIS_PRUEFUNG

    zustand, _, schleife = trainer.naechster_zustand(lauf, trainer.NICHT)

    assert zustand == trainer.PRUEFUNG
    assert schleife is False


def test_nach_genug_schritten_wird_geprueft(lauf):
    lauf.state = trainer.LERNSCHRITT
    lauf.step_no = trainer.SCHRITTE_BIS_PRUEFUNG

    zustand, _, _ = trainer.naechster_zustand(lauf, trainer.VERSTANDEN)

    assert zustand == trainer.PRUEFUNG


def test_ein_fehler_in_der_pruefung_fuehrt_zurueck_in_die_erklaerung(lauf):
    lauf.state = trainer.PRUEFUNG
    lauf.representation = trainer.SYMBOLISCH
    lauf.tasks_given = 2

    zustand, darstellung, schleife = trainer.naechster_zustand(lauf, trainer.NICHT)

    assert zustand == trainer.LERNSCHRITT
    assert darstellung == trainer.BILDLICH
    assert schleife is True


def test_nach_allen_aufgaben_kommt_der_abschluss(lauf):
    lauf.state = trainer.PRUEFUNG
    lauf.tasks_given = trainer.PRUEFAUFGABEN

    zustand, _, _ = trainer.naechster_zustand(lauf, trainer.VERSTANDEN)

    assert zustand == trainer.ABSCHLUSS


# --- Genau eine Frage -----------------------------------------------------

@pytest.mark.parametrize("roh, erwartet", [
    ("Wie viele Zentimeter sind das?", "Wie viele Zentimeter sind das?"),
    ("Wie viele? Und warum? Und wann?", "Wie viele?"),
    ("", ""),
    ("Denk kurz nach", "Denk kurz nach"),
])
def test_es_kommt_genau_eine_frage_an(roh, erwartet):
    """Der haeufigste Fehler von Sprachmodellen als Tutor.

    Die Regel steht im Prompt, und ein Prompt ist eine Bitte. Wer drei Fragen
    bekommt, beantwortet keine.
    """
    assert trainer.eine_frage(roh) == erwartet


# --- Die Antworten des Modells -------------------------------------------

def test_das_urteil_wird_gelesen():
    gelesen = trainer.urteil_lesen(
        '{"urteil": "nicht", "fehlertyp": "Einheiten verwechselt"}'
    )

    assert gelesen == {"urteil": "nicht", "fehlertyp": "Einheiten verwechselt"}


def test_ein_urteil_im_codeblock_wird_auch_gelesen():
    gelesen = trainer.urteil_lesen('```json\n{"urteil": "verstanden"}\n```')

    assert gelesen["urteil"] == "verstanden"


def test_ein_unlesbares_urteil_gilt_als_teilweise():
    """Die Einschaetzung, die am wenigsten Schaden anrichtet."""
    assert trainer.urteil_lesen("keine Ahnung")["urteil"] == trainer.TEILWEISE


def test_ein_erfundenes_urteil_gilt_als_teilweise():
    assert trainer.urteil_lesen('{"urteil": "grossartig"}')["urteil"] == trainer.TEILWEISE


def test_text_und_frage_werden_getrennt():
    gelesen = trainer.antwort_lesen(
        'Hier: {"text": "Ein Meter hat 100 Zentimeter.", '
        '"frage": "Wie viele sind 3 Meter?"}'
    )

    assert gelesen["text"] == "Ein Meter hat 100 Zentimeter."
    assert gelesen["frage"] == "Wie viele sind 3 Meter?"


def test_ohne_json_gilt_alles_als_text():
    """Lieber ein Zug ohne Frage als eine Ausnahme vor Publikum."""
    gelesen = trainer.antwort_lesen("Ein Meter hat 100 Zentimeter.")

    assert gelesen["text"] == "Ein Meter hat 100 Zentimeter."
    assert gelesen["frage"] == ""


# --- Die Prompts ----------------------------------------------------------

def test_der_prompt_nennt_die_verlangte_darstellung():
    anrede = levels.anrede("6-10")

    prompt = trainer.system_prompt(
        trainer.LERNSCHRITT, anrede, darstellung=trainer.GEGENSTAENDLICH
    )

    assert "GEGENSTÄNDLICH" in prompt


def test_bei_einer_schleife_stehen_die_versuchten_zugaenge_im_prompt():
    """Ohne dieses Gedaechtnis wiederholt der Trainer denselben Zugang."""
    anrede = levels.anrede("6-10")

    prompt = trainer.system_prompt(
        trainer.LERNSCHRITT, anrede, darstellung=trainer.BILDLICH,
        schleife=True, versucht=[trainer.SYMBOLISCH],
    )

    assert "symbolisch" in prompt
    assert "Nimm einen anderen" in prompt


def test_der_abschluss_verlangt_keine_frage_mehr():
    anrede = levels.anrede("erwachsen")

    prompt = trainer.system_prompt(trainer.ABSCHLUSS, anrede)

    assert "bleibt LEER" in prompt


def test_die_altersklasse_schlaegt_auf_den_trainer_durch():
    """Trainer und Aufgabenhilfe sprechen dieselbe Sprachebene."""
    klein = trainer.system_prompt(trainer.LERNSCHRITT, levels.anrede("6-10"))
    gross = trainer.system_prompt(trainer.LERNSCHRITT, levels.anrede("erwachsen"))

    assert klein != gross
    assert "Volksschulalter" in klein


# --- Die Zuege ------------------------------------------------------------

def test_ein_zug_haelt_fest_auf_welcher_ebene_erklaert_wurde(lauf):
    """Damit wird der Lernweg auswertbar: Welcher Zugang hat geholfen?"""
    zug = TrainerZug.objects.create(
        run=lauf, role=TrainerZug.TRAINER, text="Nimm ein Meterband.",
        question="Wie lang bist du?", state=trainer.LERNSCHRITT,
        representation=trainer.GEGENSTAENDLICH, verdict=trainer.NICHT,
        error_kind="Einheiten verwechselt",
    )

    assert zug.representation == trainer.GEGENSTAENDLICH
    assert zug.urteil_text == "nicht verstanden"


# --- Das Protokoll --------------------------------------------------------

def test_die_protokollzeile_traegt_den_zustand(lauf):
    """Anlass: Im ersten echten Durchlauf warf jeder Zug eine DataError.

    Das Ergebnisfeld war sechzehn Zeichen lang, "trainer:lernschritt" sind
    neunzehn. Gefunden hat das kein Test, sondern der Browser - weil keine
    Pruefung je eine Protokollzeile des Trainers geschrieben hatte.
    """
    from tutoring.models import Interaction

    sitzung = lauf.participation.learning_session
    zeile = Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=lauf.participation,
        weg=Interaction.LOKAL, modell="qwen3-vl-30b",
        ergebnis=f"trainer:{trainer.LERNSCHRITT}",
    )
    zeile.refresh_from_db()

    assert zeile.outcome == "trainer:lernschritt"


@pytest.mark.parametrize("zustand", [z for z, _ in trainer.ZUSTAENDE])
def test_jeder_zustand_passt_in_die_protokollzeile(lauf, zustand):
    """Damit faellt der naechste zu lange Zustandsname beim Testen auf."""
    from tutoring.models import Interaction

    zeile = Interaction.aufzeichnen(
        sitzung=lauf.participation.learning_session,
        teilnahme=lauf.participation,
        ergebnis=f"trainer:{zustand}",
    )
    zeile.refresh_from_db()

    assert zeile.outcome.endswith(zustand)


def test_bei_einer_schleife_steht_der_eigene_letzte_satz_im_prompt():
    """Anlass: Im ersten vollstaendigen Durchlauf stand dreimal fast
    derselbe Satz vom Meterband mit den hundert Strichen.

    Der Prompt verbietet die Wiederholung ausdruecklich - und ein Prompt ist
    eine Bitte. Der eigene Satz, woertlich zitiert, ist ungleich staerker
    als die Aufforderung, sich nicht zu wiederholen.
    """
    anrede = levels.anrede("10-14")
    letzter = "Ein Meter sind 100 Zentimeter, wie ein Meterband mit 100 Strichen."

    prompt = trainer.system_prompt(
        trainer.LERNSCHRITT, anrede, darstellung=trainer.BILDLICH,
        schleife=True, versucht=[trainer.GEGENSTAENDLICH], letzter=letzter,
    )

    assert letzter in prompt
    assert "verbraucht" in prompt


def test_ohne_schleife_steht_der_letzte_satz_nicht_im_prompt():
    """Sonst vermeidet der Trainer Formulierungen, die gar nicht stoeren."""
    anrede = levels.anrede("10-14")

    prompt = trainer.system_prompt(
        trainer.LERNSCHRITT, anrede, letzter="Ein Meter sind 100 Zentimeter."
    )

    assert "verbraucht" not in prompt


# --- Genau eine Frage, und zwar auf dem Bildschirm -----------------------

def test_eine_frage_im_erklaertext_faellt_weg_wenn_die_frage_dasteht():
    """Anlass: Das Modell fragte am Ende des Erklaertextes UND im Fragefeld.

    Auf dem Bildschirm standen zwei Fragen. Die Regel "genau eine Frage"
    muss fuer das gelten, was ankommt, nicht fuer ein einzelnes Feld.
    """
    text = ("Stell dir 3 Schritte vor. Wenn du jeden Meter umrechnest, "
            "wie viele Schritte hast du dann?")

    gekuerzt = trainer.ohne_frage(text, "Wie viele Zentimeter sind 3 Meter?")

    assert gekuerzt == "Stell dir 3 Schritte vor."
    assert "?" not in gekuerzt


def test_ohne_eigenes_fragefeld_bleibt_die_frage_im_text():
    """Sonst bliebe ein Zug ganz ohne Frage uebrig, und das waere schlimmer."""
    text = "Wie viele Zentimeter hast du?"

    assert trainer.ohne_frage(text, "") == text


def test_ein_text_ohne_frage_bleibt_unangetastet():
    text = "Ein Meter sind 100 Zentimeter."

    assert trainer.ohne_frage(text, "Wie viele sind 3 Meter?") == text


def test_bei_einer_schleife_steht_die_echte_antwort_im_prompt():
    """Anlass: Der Trainer behauptete, das Kind haette etwas verstanden.

    Dreimal stand "Du hast gesagt, dass du weisst, wie viele Zentimeter in
    einem Meter sind" - nachdem das Kind dreimal geschrieben hatte, dass es
    nichts versteht. Ohne den woertlichen Beitrag mischt sich das Modell aus
    dem Verlauf zusammen, was ihm passt.
    """
    prompt = trainer.system_prompt(
        trainer.LERNSCHRITT, levels.anrede("10-14"),
        schleife=True, beitrag="Ich verstehe das nicht",
    )

    assert "Ich verstehe das nicht" in prompt
    assert "Behaupte NICHT" in prompt


# --- Rohes JSON darf nie auf dem Bildschirm landen -----------------------

EIN_OBJEKT = '{"text": "Ein Meter hat 100 Zentimeter.", "frage": "Und 3 Meter?"}'


def test_ein_mehrfach_ausgegebenes_objekt_wird_gelesen():
    """Anlass, und es stand vor einem Kind auf dem Bildschirm.

    Das Modell gab sein Objekt sechsmal hintereinander aus. Das Muster
    griff von der ersten Klammer bis zur letzten, umfasste damit alle sechs,
    war kein gueltiges JSON mehr - und die Notbremse gab den Rohtext aus.
    """
    gelesen = trainer.antwort_lesen(" ".join([EIN_OBJEKT] * 6))

    assert gelesen["text"] == "Ein Meter hat 100 Zentimeter."
    assert gelesen["frage"] == "Und 3 Meter?"


@pytest.mark.parametrize("roh", [
    EIN_OBJEKT,
    " ".join([EIN_OBJEKT] * 6),
    "```json\n" + EIN_OBJEKT + "\n```",
    "Gern! " + EIN_OBJEKT,
    '{"text": "Ein Meter hat 100 Zentimeter.", "frage": ',
    "Ein Meter hat 100 Zentimeter.",
    "{{{",
    "",
])
def test_niemals_geschweifte_klammern_im_trainertext(roh):
    """Die Regel dahinter: Lieber ein Zug ohne Frage als JSON vor Publikum."""
    gelesen = trainer.antwort_lesen(roh)

    assert "{" not in gelesen["text"]
    assert '"text"' not in gelesen["text"]


def test_aus_kaputtem_json_wird_der_text_gerettet():
    roh = '{"text": "Ein Meter hat 100 Zentimeter.", "frage": '

    assert trainer.antwort_lesen(roh)["text"] == "Ein Meter hat 100 Zentimeter."


# =========================================================================
# Der Sprechcoach
# =========================================================================

from tutoring import sprechcoach  # noqa: E402
from tutoring.models import SprachLauf, SprachZug  # noqa: E402


@pytest.fixture
def coachlauf(lehrperson):
    sitzung = LearningSession.objects.create(
        title="English talk", teacher=lehrperson,
        mode=LearningSession.BETRIEB_SPRACHE,
        target_language="en-GB", language_level="A1",
        task_hint="Lieblingstiere",
    )
    teilnahme = Participation.objects.create(
        learning_session=sitzung, animal="fuchs", token="sc1", log_key="scl1"
    )
    return SprachLauf.objects.create(participation=teilnahme)


def test_eine_sprechsitzung_erkennt_sich(coachlauf):
    assert coachlauf.participation.learning_session.ist_sprechcoach is True


def test_thema_sprache_und_niveau_kommen_aus_der_sitzung(coachlauf):
    """Die Lehrperson stellt sie fuer alle ein, nicht je Person."""
    assert coachlauf.thema == "Lieblingstiere"
    assert coachlauf.sprache_code == "en-GB"
    assert coachlauf.sprache_name == "Englisch"
    assert coachlauf.niveau == "A1"


def test_whisper_bekommt_den_kurzen_code():
    """Ohne die richtige Sprache schreibt Whisper englische Saetze als
    deutsche Lautmalerei."""
    assert sprechcoach.whisper_code("en-GB") == "en"
    assert sprechcoach.whisper_code("fr-FR") == "fr"


# --- Die Sprache der Antwort ---------------------------------------------

@pytest.mark.parametrize("text, ziel, erwartet", [
    ("What is your favourite animal?", "en-GB", True),
    ("Das ist ein schönes Tier, nicht wahr?", "en-GB", False),
    ("Quel est ton animal préféré ?", "fr-FR", True),
    ("Ich finde das auch sehr gut und wir haben noch Zeit", "fr-FR", False),
    ("Hello!", "en-GB", True),
    ("", "en-GB", True),
])
def test_die_sprache_der_antwort_wird_geprueft(text, ziel, erwartet):
    """Ein Modell, das auf Englisch antworten soll, rutscht ins Deutsche,
    sobald das Kind deutsch schreibt. Dann ist die Stunde ihren Zweck los."""
    assert sprechcoach.sprache_erkannt(text, ziel) is erwartet


# --- Die Satzlaenge -------------------------------------------------------

def test_auf_a1_sind_acht_woerter_die_grenze():
    """'Sprich einfach' ist eine Bitte. Acht Woerter sind eine Grenze."""
    kurz = "What is your favourite animal?"
    lang = ("I really like elephants because they are very big and they live "
            "in Africa and Asia.")

    assert sprechcoach.zu_lang(kurz, "A1") == []
    assert sprechcoach.zu_lang(lang, "A1")


def test_auf_b2_ist_derselbe_satz_in_ordnung():
    lang = ("I really like elephants because they are very big and they live "
            "in Africa and Asia.")

    assert sprechcoach.zu_lang(lang, "B2") == []


def test_gekuerzt_behaelt_die_kurzen_saetze():
    text = ("I like cats. I really like elephants because they are very big "
            "and they live in Africa and Asia.")

    assert sprechcoach.gekuerzt(text, "A1") == "I like cats."


def test_jede_sprache_hat_einen_notfallsatz():
    """Das Gespraech darf nicht an unserer Pruefung sterben."""
    for code, _ in sprechcoach.SPRACHEN:
        satz = sprechcoach.NOTFALL[code]
        assert satz
        assert sprechcoach.sprache_erkannt(satz, code)
        assert sprechcoach.zu_lang(satz, "A1") == []


# --- Die Antwort des Modells ---------------------------------------------

def test_antwort_uebersetzung_und_korrektur_werden_getrennt():
    roh = ('{"antwort": "I like dogs. What about you?", '
           '"uebersetzung": "Ich mag Hunde. Und du?", '
           '"korrektur": "I like dogs"}')

    gelesen = sprechcoach.antwort_lesen(roh)

    assert gelesen["antwort"] == "I like dogs. What about you?"
    assert gelesen["uebersetzung"] == "Ich mag Hunde. Und du?"
    assert gelesen["korrektur"] == "I like dogs"


@pytest.mark.parametrize("roh", [
    '{"antwort": "Hello!", "uebersetzung": "Hallo!"}',
    '{"antwort": "Hello!"} {"antwort": "Hello!"}',
    '```json\n{"antwort": "Hello!"}\n```',
    "Hello!",
    "{{{",
    "",
])
def test_niemals_geschweifte_klammern_im_coachtext(roh):
    """Derselbe Fehler wie beim Trainer, hier vorbeugend geschlossen."""
    gelesen = sprechcoach.antwort_lesen(roh)

    assert "{" not in gelesen["antwort"]
    assert '"antwort"' not in gelesen["antwort"]


# --- Der Prompt -----------------------------------------------------------

def test_der_prompt_nennt_sprache_niveau_und_thema():
    prompt = sprechcoach.system_prompt(
        "fr-FR", "A2", "Urlaub", levels.anrede("10-14")
    )

    assert "français" in prompt
    assert "ZWÖLF" in prompt
    assert "Urlaub" in prompt


def test_der_erste_zug_begruesst():
    """Wer eine Fremdsprache lernt, soll nicht vor einem leeren Feld sitzen."""
    prompt = sprechcoach.system_prompt(
        "en-GB", "A1", "Tiere", levels.anrede("6-10"), erster_zug=True
    )

    assert "Begrüße kurz" in prompt


def test_der_coach_korrigiert_nicht_wie_ein_lehrer():
    """Wer beim dritten Wort unterbrochen wird, hoert auf zu sprechen."""
    prompt = sprechcoach.system_prompt(
        "en-GB", "A1", "Tiere", levels.anrede("6-10")
    )

    assert "STATT ZU KORRIGIEREN" in prompt


@pytest.mark.parametrize("code", ["A1", "A2", "B1", "B2", "quatsch", ""])
def test_der_niveauname_wirft_nie(code):
    """Anlass: Hier stand dict(NIVEAUS)[0] als Vorgabewert.

    Der Vorgabewert von dict.get wird in Python IMMER ausgewertet, auch wenn
    der Schluessel da ist. Jeder Aufruf warf einen KeyError und nahm die
    ganze Seite mit - auch bei einem voellig gueltigen Niveau.
    """
    assert sprechcoach.niveau_name(code)


@pytest.mark.parametrize("code", ["en-GB", "fr-FR", "xx-YY", ""])
def test_der_sprachname_wirft_nie(code):
    assert sprechcoach.sprache_name(code)
