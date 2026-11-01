"""Die Sprachsperre und der stille Ausweg, durch die Ansichten hindurch.

Der Coach TUT, als verstehe er kein Deutsch. Hier steht, dass er das ohne
das Modell tut, dass der deutsche Beitrag trotzdem im Verlauf bleibt, und
dass der Ausweg eine Auskunft ist und kein Zug.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import sprechcoach_views
from tutoring.models import LearningSession, Participation, SprachLauf, SprachZug
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db


@pytest.fixture
def englischstunde(db):
    lehrperson = get_user_model().objects.create_user(username="l", password="x")
    return LearningSession.objects.create(
        title="Englisch 3b", teacher=lehrperson,
        mode=LearningSession.BETRIEB_SPRACHE, subject="englisch",
        target_language="en-GB", language_level="A1", task_hint="pets",
    )


@pytest.fixture
def kind(client, englischstunde):
    teilnahme = Participation.objects.create(
        learning_session=englischstunde, animal="biber", token="t1",
    )
    sitzung = client.session
    sitzung[SCHLUESSEL_TEILNAHME] = teilnahme.token
    sitzung.save()
    return teilnahme


@pytest.fixture
def modell_gerufen(monkeypatch):
    """Zaehlt die Aufrufe des Modells und antwortet brav auf Englisch."""
    aufrufe = []

    def attrappe(system, frage, max_tokens=500):
        aufrufe.append(frage)
        return (
            json.dumps({"antwort": "What is your pet's name?",
                        "uebersetzung": "Wie heißt dein Haustier?",
                        "korrektur": ""}),
            {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1},
        )

    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)
    return aufrufe


def _zug(client, text, erkannt=""):
    return client.post(
        reverse("tutoring:sprechcoach_zug"),
        {"text": text, "erkannt": erkannt, "herkunft": "tippen"},
        HTTP_X_ANTWORT="json", secure=True,
    )


def test_deutsch_bekommt_die_sperre_ohne_das_modell(client, kind, modell_gerufen):
    antwort = _zug(client, "Ich habe einen Hund und eine Katze.")

    daten = antwort.json()
    assert antwort.status_code == 200
    assert daten["nicht_verstanden"] is True
    assert daten["coach"].startswith("Sorry")
    assert modell_gerufen == [], "die Sperre fragt das Modell nicht"

    coach = SprachZug.objects.filter(role=SprachZug.COACH).get()
    assert coach.not_understood is True
    assert SprachZug.objects.filter(role=SprachZug.LERNEND, text__startswith="Ich habe").exists(), \
        "der deutsche Beitrag bleibt im Verlauf - er ist wirklich gefallen"


def test_englisch_geht_zum_modell(client, kind, modell_gerufen):
    antwort = _zug(client, "I have a dog.", erkannt="en")

    daten = antwort.json()
    assert daten["nicht_verstanden"] is False
    assert daten["coach"] == "What is your pet's name?"
    assert len(modell_gerufen) == 1


def test_whisper_sagt_englisch_dann_zaehlt_das(client, kind, monkeypatch):
    """Das Modell hat die Aufnahme gehoert, die Wortliste nur den Text.

    Der Coach greift das deutsche Wort auf und hebt es ins Englische - das
    ist Regel 6 (einfuettern), und so knuepft die Antwort auch zaehlbar an.
    """
    aufrufe = []

    def attrappe(system, frage, max_tokens=500):
        aufrufe.append(frage)
        return (
            json.dumps({"antwort": "A Hund, yes: a dog. What is your dog's name?",
                        "uebersetzung": "x", "korrektur": ""}),
            {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1},
        )
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)

    antwort = _zug(client, "Ich habe einen Hund.", erkannt="en")

    assert antwort.json()["nicht_verstanden"] is False
    assert len(aufrufe) == 1


def test_die_sperre_gelangt_nicht_ins_gedaechtnis(client, kind, modell_gerufen):
    """Sonst lernt das Modell, "Sorry" von sich aus zu sagen."""
    _zug(client, "Ich habe einen Hund und eine Katze.")
    _zug(client, "I have a dog.", erkannt="en")

    lauf = SprachLauf.objects.get()
    gedaechtnis = sprechcoach_views._verlauf_text(lauf)
    assert "Sorry" not in gedaechtnis
    assert "Ich habe einen Hund" in gedaechtnis
    assert "I have a dog" in gedaechtnis


def test_der_ausweg_ist_deutsch_und_kein_zug(client, kind, monkeypatch):
    def attrappe(system, frage, max_tokens=200):
        return (
            json.dumps({"erklaerung": "Der Coach fragt, wie dein Haustier heißt.",
                        "beispiel": "My dog is called Max."}),
            {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1},
        )
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)
    vorher = SprachZug.objects.count()

    antwort = client.post(
        reverse("tutoring:sprechcoach_hilfe"), HTTP_X_ANTWORT="json", secure=True
    )

    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["erklaerung"].startswith("Der Coach fragt")
    assert daten["beispiel"] == "My dog is called Max."
    assert SprachZug.objects.count() == vorher, "eine Auskunft, kein Beitrag"


def test_der_ausweg_haelt_auch_ohne_spark(client, kind, monkeypatch):
    from tutoring.spark import SparkNichtErreichbar

    def kaputt(*a, **k):
        raise SparkNichtErreichbar("aus")
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", kaputt)

    antwort = client.post(
        reverse("tutoring:sprechcoach_hilfe"), HTTP_X_ANTWORT="json", secure=True
    )

    daten = antwort.json()
    assert antwort.status_code == 200
    assert daten["ok"] is True
    assert "Antworte" in daten["erklaerung"]


def test_der_ausweg_geht_auch_ohne_javascript(client, kind, monkeypatch):
    """Ohne X-Antwort kommt die Seite zurueck, mit der Hilfe darin - kein JSON."""
    def attrappe(system, frage, max_tokens=200):
        return (
            json.dumps({"erklaerung": "Sag, welches Tier du magst.",
                        "beispiel": "I like cats."}),
            {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1},
        )
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)

    antwort = client.post(reverse("tutoring:sprechcoach_hilfe"), secure=True)

    assert antwort.status_code == 200
    assert antwort["Content-Type"].startswith("text/html")
    assert antwort.context["hilfe"]["beispiel"] == "I like cats."
    seite = antwort.content.decode()
    assert "Sag, welches Tier du magst." in seite, "die Hilfe steht auf der Seite"
    assert "I like cats." in seite
    assert 'id="coach-hilfe" hidden' not in seite, "der Kasten ist aufgedeckt"


def test_der_ausweg_braucht_eine_sitzung(client):
    antwort = client.post(
        reverse("tutoring:sprechcoach_hilfe"), HTTP_X_ANTWORT="json", secure=True
    )
    assert antwort.status_code == 403


def test_whisper_meldet_die_sprache_an_den_browser(client, kind, monkeypatch):
    """Beim Sprechcoach ohne erzwungene Sprache, und das Ergebnis geht mit."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from tutoring import views

    gesehen = {}

    def attrappe(daten, dateiname, sprache):
        gesehen["sprache"] = sprache
        return "Ich habe einen Hund.", "de"
    monkeypatch.setattr(views, "text_und_sprache", attrappe)
    monkeypatch.setattr(views.settings, "SPARK_AUDIO_BASE_URL", "http://probe")

    antwort = client.post(
        reverse("tutoring:sprache_erkennen"),
        {"aufnahme": SimpleUploadedFile("a.wav", b"RIFF....")},
        secure=True,
    )

    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["erkannt"] == "de"
    assert gesehen["sprache"] is None, "Whisper bestimmt die Sprache selbst"


def test_in_der_aufgabenhilfe_bleibt_deutsch_erzwungen(client, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from tutoring import views

    lehrperson = get_user_model().objects.create_user(username="m", password="x")
    mathe = LearningSession.objects.create(title="Mathe", teacher=lehrperson)
    teilnahme = Participation.objects.create(learning_session=mathe, animal="igel", token="t2")
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()

    gesehen = {}

    def attrappe(daten, dateiname, sprache):
        gesehen["sprache"] = sprache
        return "Drei mal vier.", "de"
    monkeypatch.setattr(views, "text_und_sprache", attrappe)
    monkeypatch.setattr(views.settings, "SPARK_AUDIO_BASE_URL", "http://probe")

    client.post(
        reverse("tutoring:sprache_erkennen"),
        {"aufnahme": SimpleUploadedFile("a.wav", b"RIFF....")},
        secure=True,
    )

    assert gesehen["sprache"] == "de"
