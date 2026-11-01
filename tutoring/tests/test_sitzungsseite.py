"""Die Sitzungsseite der Lehrperson nach dem 22.10.2026.

Thomas: "In der Musikstunde kann ich nicht in die Chats rein. Dort sollte
natuerlich auch der Chat sichtbar sein. Insgesamt ist das Interface fuer die
Lehrperson fuer eine Session sehr kompliziert." Seitdem: in jeder
Betriebsart dieselbe Kachel je Kind mit dem Weg in den Verlauf, der Verlauf
zeigt in jeder Betriebsart das Gespraech (oder die Lieder), und alles, was
erklaert, steht in Aufklappern.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from tutoring.models import (LearningSession, Participation, SprachLauf,
                             SprachZug, TrainerLauf, TrainerZug)


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _stunde(lehrperson, **werte):
    vorgaben = {"title": "Stunde", "teacher": lehrperson, "subject": "mathematik"}
    vorgaben.update(werte)
    return LearningSession.objects.create(**vorgaben)


def _kind(stunde, tier="fuchs"):
    return Participation.objects.create(learning_session=stunde, animal=tier, token=f"t-{tier}")


# --- Der Verlauf in jeder Betriebsart -------------------------------------------

@pytest.mark.django_db
def test_trainer_verlauf_zeigt_das_gespraech(client, lehrperson):
    stunde = _stunde(lehrperson, subject="deutsch", mode=LearningSession.BETRIEB_TRAINER,
                     task_hint="Nomen")
    kind = _kind(stunde)
    lauf = TrainerLauf.objects.create(participation=kind, topic="Nomen", step_no=2,
                                      tasks_given=3, tasks_right=2)
    TrainerZug.objects.create(run=lauf, role=TrainerZug.TRAINER,
                              text="Ein Nomen ist ein Namenwort.", question="Was ist ein Nomen?")
    TrainerZug.objects.create(run=lauf, role=TrainerZug.LERNEND, text="Der Hund")
    client.force_login(lehrperson)

    liste = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]),
                       secure=True).content.decode()
    verlauf_url = reverse("tutoring:lehrperson_verlauf", args=[stunde.code, kind.pk])
    assert verlauf_url in liste
    assert "Nomen" in liste
    assert "Schritt 2 · 2 von 3 Aufgaben richtig" in liste
    assert "„Der Hund“" in liste

    chat = client.get(verlauf_url, secure=True).content.decode()
    assert "Ein Nomen ist ein Namenwort." in chat
    assert "Was ist ein Nomen?" in chat
    assert "Der Hund" in chat
    assert "hx-trigger" in chat, "der Verlauf laeuft mit"
    assert "1 Thema" in chat


@pytest.mark.django_db
def test_sprechcoach_verlauf_zeigt_gespraech_mit_uebersetzung(client, lehrperson):
    stunde = _stunde(lehrperson, subject="englisch", mode=LearningSession.BETRIEB_SPRACHE,
                     target_language="en-GB", language_level="A2", age_group="10-14",
                     task_hint="My pets")
    kind = _kind(stunde, "eule")
    lauf = SprachLauf.objects.create(participation=kind)
    SprachZug.objects.create(run=lauf, role=SprachZug.COACH, text="What is your pet?",
                             translation="Was ist dein Haustier?")
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text="I have a cat",
                             correction="I have got a cat")
    SprachZug.objects.create(run=lauf, role=SprachZug.COACH, text="Sorry, I don't understand.",
                             not_understood=True)
    client.force_login(lehrperson)

    liste = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]),
                       secure=True).content.decode()
    verlauf_url = reverse("tutoring:lehrperson_verlauf", args=[stunde.code, kind.pk])
    assert verlauf_url in liste
    assert "<table" not in liste
    assert "„I have a cat“" in liste

    chat = client.get(verlauf_url, secure=True).content.decode()
    assert "What is your pet?" in chat
    assert "Was ist dein Haustier?" in chat
    assert "I have a cat" in chat
    assert "I have got a cat" in chat
    assert "hat nicht verstanden" in chat
    assert 'lang="en-GB"' in chat
    assert "1 Gespräch" in chat


@pytest.mark.django_db
def test_kachelzeit_folgt_den_zuegen(client, lehrperson):
    """Vor dem Umbau galt in Trainer und Sprechcoach nur der Beitritt als
    Aktivitaet: Nach fuenf Minuten stand jedes Kind als still, obwohl es
    gerade sprach."""
    stunde = _stunde(lehrperson, subject="englisch", mode=LearningSession.BETRIEB_SPRACHE,
                     target_language="en-GB", language_level="A2", age_group="10-14")
    kind = _kind(stunde, "igel")
    Participation.objects.filter(pk=kind.pk).update(joined_at=timezone.now() - timedelta(minutes=20))
    lauf = SprachLauf.objects.create(participation=kind)
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text="Hello")
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]), secure=True)

    zeile = antwort.context["zeilen"][0]
    assert zeile["aktiv"] is True
    assert zeile["grund"] == ""


# --- Weniger Text auf der Seite ---------------------------------------------------

@pytest.mark.django_db
def test_die_sitzungsseite_erklaert_nur_auf_wunsch(client, lehrperson):
    stunde = _stunde(lehrperson)
    _kind(stunde)
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde.code]),
                       secure=True).content.decode()

    assert 'class="erklaerung-aufklapper"' in seite
    assert "Was die Kacheln zeigen" in seite
    # Der Satz, der vorher ueber jeder Klasse stand, steht jetzt im Aufklapper.
    assert "Jedes Kind wählt beim Beitreten ein Tier" not in seite
    assert "Sitzung beenden und alles löschen" not in seite
    assert "Sitzung beenden</button>" in seite
    assert "Nicht rückgängig zu machen." in seite
    assert 'class="stufenerklaerung"' in seite, "die Stufen bleiben, eingeklappt"
    assert "<table" not in seite


@pytest.mark.django_db
def test_sprechcoach_zahlen_stehen_im_aufklapper(client, lehrperson):
    stunde = _stunde(lehrperson, subject="englisch", mode=LearningSession.BETRIEB_SPRACHE,
                     target_language="en-GB", language_level="A2", age_group="10-14")
    kind = _kind(stunde, "wolf")
    lauf = SprachLauf.objects.create(participation=kind)
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text="I like dogs very much")
    client.force_login(lehrperson)

    liste = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]),
                       secure=True).content.decode()

    assert 'class="mehr-zahlen"' in liste
    assert "Mehr Zahlen zum Gespräch" in liste
    assert "Wörter je Beitrag" in liste.split('class="mehr-zahlen"')[1]


@pytest.mark.django_db
def test_die_erklaerung_beschreibt_die_wahl_statt_der_leiter(client, lehrperson):
    """Seit 30.10.2026 (Hilfe nach Diagnose): Der Aufklapper sagt, dass die
    Hilfe nach einer Einschaetzung je Beitrag gewaehlt wird, nicht der Reihe
    nach gegeben; der alte Satz "keine Stufe uebersprungen" ist weg."""
    stunde = _stunde(lehrperson)
    _kind(stunde)
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde.code]),
                       secure=True).content.decode()

    assert "nicht der Reihe nach gegeben" in seite
    assert "gewählt, nicht gezählt" in seite
    assert "Die Stufen sind keine Leiter." in seite
    assert "keine Stufe übersprungen" not in seite
    assert "erst nach" in seite and "Warum-Frage" in seite
    assert "direkt oder indirekt" in seite
    assert "S. 318" in seite and "S. 290–291" in seite
    assert "Moser Opitz" in seite and "Franke und Ruwisch" in seite
