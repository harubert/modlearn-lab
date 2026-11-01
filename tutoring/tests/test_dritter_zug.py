"""Der dritte Zug: anknuepfen statt spiegeln.

Aus Thomas' Dialog vom 11.10.2026 (Sitzung 593641): sechs Zuege, fuenf davon
"I like X too. What ...?" - Bestaetigung plus Themenwechsel, und nie das
Wort aufgegriffen, das das Gegenueber gerade gesucht hatte. Die Recherche
(docs/Gespraechsdidaktik Englisch fuer den Sprechcoach.md) sagt, was
stattdessen wirkt, und das hier ist der zaehlbare Teil davon.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import levels, sprechcoach, sprechcoach_views
from tutoring.models import LearningSession, Participation, SprachLauf, SprachZug
from tutoring.views import SCHLUESSEL_TEILNAHME


# --- Spiegeln und Loben ----------------------------------------------------

@pytest.mark.parametrize("text", [
    "I like guitar too. What song do you play?",
    "I like classical and rock music too. Why do you think they are the same?",
    "Me too! What else do you like?",
    "I also love dogs. Do you have one?",
    "Oh, I play the guitar as well. Which songs?",
    "Moi aussi, j'aime les chiens. Et toi ?",
])
def test_spiegeln_wird_erkannt(text):
    assert sprechcoach.spiegelt(text) is True


@pytest.mark.parametrize("text", [
    "A ukulele, yes. How long have you played it?",
    "Oh really? Why both?",
    "Wait - today or yesterday?",
    "So you play rock on a small guitar. What does it sound like?",
    "That sounds loud! Who taught you?",
])
def test_reagieren_ist_kein_spiegeln(text):
    assert sprechcoach.spiegelt(text) is False


@pytest.mark.parametrize("text", [
    "Great! What else?",
    "Well done. And then?",
    "Super, what happened next?",
    "Awesome! Why?",
])
def test_pauschales_lob_wird_erkannt(text):
    assert sprechcoach.lobt(text) is True


def test_konkretes_lob_mitten_im_satz_ist_erlaubt():
    """Lob ist nicht verboten - nur das pauschale am Anfang."""
    assert sprechcoach.lobt("You used 'yesterday' - nice. What did you do?") is False


# --- Genau eine Frage ------------------------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("What do you like?", True),
    ("I play too. What song? Which band?", False),
    ("That sounds fun.", False),
    ("", False),
])
def test_genau_eine_frage(text, erwartet):
    assert sprechcoach.genau_eine_frage(text) is erwartet


# --- Anknuepfen ------------------------------------------------------------

def test_thomas_ukulele_wurde_nicht_aufgegriffen():
    """Der Beitrag, der im Protokoll stand - und die Antwort darauf."""
    beitrag = ("Can you tell me, I'm looking for a word. It's a very small "
               "guitar. In German it's Ukulele. Do you know the word?")
    assert sprechcoach.anknuepft("I know the word, it is ukulele. Do you play ukulele too?",
                                 beitrag) is True
    assert sprechcoach.anknuepft("What is your favourite food?", beitrag) is False


def test_anknuepfen_ueber_den_wortstamm():
    assert sprechcoach.anknuepft("Which songs do you play?",
                                 "I play guitar and I know three song.") is True
    assert sprechcoach.anknuepft("Who is playing with you?",
                                 "I played football yesterday.") is True


def test_ein_leerer_beitrag_laesst_sich_nicht_aufgreifen():
    """Nach "Yes." darf der Coach ein Thema setzen."""
    assert sprechcoach.anknuepft("Do you have a pet?", "Yes.") is True
    assert sprechcoach.anknuepft("Do you have a pet?", "") is True


def test_fuellwoerter_zaehlen_nicht_als_anknuepfen():
    """"I like it very much" und "What do you like?" teilen nur Fuellwoerter."""
    assert sprechcoach.anknuepft("What do you like about school?",
                                 "I like it very much") is True, \
        "ohne Inhaltswort im Beitrag gilt es als erfuellt"
    assert sprechcoach.anknuepft("What do you like about school?",
                                 "I like my brother very much") is False


# --- verstoesse mit Beitrag -------------------------------------------------

def test_verstoesse_nennen_spiegeln_lob_frage_und_anknuepfen():
    gefunden = sprechcoach.verstoesse(
        "Great! I like guitar too. What song? Which band?", "en-GB", "B2",
        beitrag="My favourite animal is the elephant.",
    )
    assert "spiegelt" in gefunden, "auch nach einem Lob-Einwurf ist es Spiegeln"
    assert "lobt pauschal" in gefunden
    assert "nicht genau eine Frage" in gefunden
    assert "knüpft nicht an" in gefunden


def test_ein_guter_zug_hat_keine_verstoesse():
    gefunden = sprechcoach.verstoesse(
        "A ukulele, yes. How long have you played it?", "en-GB", "A2",
        beitrag="It's a very small guitar. In German it's Ukulele.",
    )
    assert gefunden == []


def test_ohne_beitrag_entfaellt_das_anknuepfen():
    assert "knüpft nicht an" not in sprechcoach.verstoesse(
        "Hello! What do you like?", "en-GB", "A1"
    )


# --- Schonmodus und Nachschaerfung ------------------------------------------

def test_drei_sehr_kurze_beitraege_loesen_den_schonmodus_aus():
    assert sprechcoach.schonmodus_noetig(["Yes.", "No", "I think"]) is True
    assert sprechcoach.schonmodus_noetig(["Yes.", "I like dogs and cats.", "No"]) is False
    assert sprechcoach.schonmodus_noetig(["Yes.", "No"]) is False, "zwei sind kein Signal"
    assert sprechcoach.schonmodus_noetig([]) is False


def test_die_nachschaerfung_folgt_der_reihenfolge_des_schadens():
    assert "English" in sprechcoach.schaerfung_fuer(["falsche Sprache", "spiegelt"], "en-GB", "A1")
    assert sprechcoach.schaerfung_fuer(["knüpft nicht an", "spiegelt"], "en-GB", "A1") \
        == sprechcoach.SCHAERFUNG_ANKNUEPFEN
    assert sprechcoach.schaerfung_fuer(["lobt pauschal"], "en-GB", "A1") \
        == sprechcoach.SCHAERFUNG_SPIEGEL
    assert sprechcoach.schaerfung_fuer(["nicht genau eine Frage"], "en-GB", "A1") \
        == sprechcoach.SCHAERFUNG_FRAGE
    assert "ZWÖLF" not in sprechcoach.schaerfung_fuer(["zu lange Sätze"], "en-GB", "A1")
    assert "8" in sprechcoach.schaerfung_fuer(["zu lange Sätze"], "en-GB", "A1")


def test_der_prompt_kennt_schonmodus_und_setzt_die_sprache_ins_niveau():
    anrede = levels.anrede("6-10")
    normal = sprechcoach.system_prompt("en-GB", "A1", "pets", anrede)
    schonend = sprechcoach.system_prompt("en-GB", "A1", "pets", anrede, schonmodus=True)

    assert "{eigenname}" not in normal, "der Platzhalter im Niveau wird eingesetzt"
    assert "sagst es auf English vor" in normal
    assert "KNÜPF AN" in normal and "SPIEGLE NICHT" in normal
    assert "UNSICHER" not in normal
    assert "UNSICHER" in schonend and "korrigiere nichts" in schonend


# --- Durch die Ansicht ------------------------------------------------------

pytestmark_db = pytest.mark.django_db


@pytest.fixture
def englischstunde(db):
    lehrperson = get_user_model().objects.create_user(username="l", password="x")
    return LearningSession.objects.create(
        title="Englisch", teacher=lehrperson, mode=LearningSession.BETRIEB_SPRACHE,
        subject="englisch", target_language="en-GB", language_level="A2",
        task_hint="music",
    )


@pytest.fixture
def kind(client, englischstunde):
    teilnahme = Participation.objects.create(
        learning_session=englischstunde, animal="fuchs", token="t-fuchs",
    )
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.mark.django_db
def test_ein_spiegelnder_zug_wird_ein_zweites_mal_geholt(client, kind, monkeypatch):
    """Erster Versuch spiegelt, zweiter knuepft an - der zweite gewinnt."""
    gesehen = []
    antworten = iter([
        '{"antwort": "I like guitar too. What song do you play?", "uebersetzung": "x", "korrektur": ""}',
        '{"antwort": "A small guitar, yes. How does a ukulele sound?", "uebersetzung": "x", "korrektur": ""}',
    ])

    def attrappe(system, frage, max_tokens=500):
        gesehen.append(system)
        return next(antworten), {"modell": "p", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1}
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)

    antwort = client.post(
        reverse("tutoring:sprechcoach_zug"),
        {"text": "It's a very small guitar. In German it's Ukulele.", "erkannt": "en"},
        HTTP_X_ANTWORT="json", secure=True,
    )

    assert antwort.json()["coach"].startswith("A small guitar")
    assert len(gesehen) == 2
    assert sprechcoach.SCHAERFUNG_SPIEGEL.strip() in gesehen[1] or \
        sprechcoach.SCHAERFUNG_ANKNUEPFEN.strip() in gesehen[1]


@pytest.mark.django_db
def test_im_schonmodus_gibt_es_keine_korrektur(client, kind, monkeypatch):
    lauf = SprachLauf.objects.create(participation=kind)
    for text in ("Yes.", "No", "Dog"):
        SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text=text)
        SprachZug.objects.create(run=lauf, role=SprachZug.COACH, text="Oh? Which one?")
    gesehen = []

    def attrappe(system, frage, max_tokens=500):
        gesehen.append(system)
        return ('{"antwort": "A brown dog or a black dog?", "uebersetzung": "x", '
                '"korrektur": "I have a dog."}',
                {"modell": "p", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1})
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)

    antwort = client.post(
        reverse("tutoring:sprechcoach_zug"), {"text": "Dog", "erkannt": "en"},
        HTTP_X_ANTWORT="json", secure=True,
    )

    daten = antwort.json()
    assert daten["korrektur"] == "", "im Schonmodus wird nicht korrigiert"
    assert "UNSICHER" in gesehen[0]


@pytest.mark.django_db
def test_die_erklaerung_fuer_lehrpersonen_steht_und_ist_verlinkt(client, englischstunde):
    client.force_login(englischstunde.teacher)

    seite = client.get(reverse("sprechcoach_erklaerung"), secure=True)
    assert seite.status_code == 200
    assert "anknüpft statt zu spiegeln" in seite.content.decode()

    formular = client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "englisch"}, secure=True
    ).content.decode()
    assert reverse("sprechcoach_erklaerung") in formular
