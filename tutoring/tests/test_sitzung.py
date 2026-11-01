"""Pruefungen der Sitzungslogik.

Zwei Zusagen stehen hier auf dem Pruefstand: Beenden loescht wirklich alles,
und die Lehrperson bekommt Zaehler statt Inhalte.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from tutoring import levels
from tutoring.models import (Hint, LearningSession, Participation, Task,
                             code_erzeugen, verfallene_aufraeumen)

# Vier Stunden, eine der Wahlmoeglichkeiten beim Anlegen.
VIER_STUNDEN = 240

pytestmark = pytest.mark.django_db


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


@pytest.fixture
def sitzung(lehrperson):
    return LearningSession.objects.create(
        title="Sachrechnen 4a", teacher=lehrperson, max_level=levels.NUR_TIPPS
    )


def _teilnahme(sitzung):
    return Participation.objects.create(
        learning_session=sitzung, token=Participation.token_erzeugen()
    )


# --- Der Sitzungscode ------------------------------------------------------

def test_code_ist_sechsstellig_und_beginnt_nicht_mit_null():
    """Die Lehrperson liest den Code im Hoersaal vor, er muss eindeutig sein."""
    for _ in range(200):
        code = code_erzeugen()
        assert len(code) == 6
        assert code.isdigit()
        assert code[0] != "0"


def test_code_wird_beim_anlegen_vergeben(sitzung):
    assert len(sitzung.code) == 6


def test_codes_sind_verschieden(lehrperson):
    codes = {
        LearningSession.objects.create(title=f"S{i}", teacher=lehrperson).code
        for i in range(25)
    }
    assert len(codes) == 25


# --- Verfall ist eine Einstellung, keine Voreinstellung -------------------

def test_sitzung_bleibt_ohne_frist_offen(sitzung):
    """Die Grundeinstellung: der Code stirbt nicht von selbst.

    Ein Code, der mitten in der Stunde ablaeuft, stoert den Unterricht mehr
    als einer, der zu lange gilt. Wer den Verfall will, stellt ihn ein.
    """
    assert sitzung.idle_timeout_minutes is None
    assert sitzung.verfaellt_um is None
    assert sitzung.ist_offen is True


def test_sitzung_ohne_frist_bleibt_auch_nach_tagen_offen(sitzung):
    LearningSession.objects.filter(pk=sitzung.pk).update(
        last_activity_at=timezone.now() - timedelta(days=9)
    )
    sitzung.refresh_from_db()

    assert sitzung.ist_offen is True


def test_sitzung_mit_frist_verfaellt(lehrperson):
    sitzung = LearningSession.objects.create(
        title="Mit Frist", teacher=lehrperson, idle_timeout_minutes=VIER_STUNDEN
    )
    LearningSession.objects.filter(pk=sitzung.pk).update(
        last_activity_at=timezone.now() - timedelta(minutes=VIER_STUNDEN + 1)
    )
    sitzung.refresh_from_db()

    assert sitzung.ist_offen is False


def test_frist_laeuft_ab_der_letzten_aktivitaet(lehrperson):
    sitzung = LearningSession.objects.create(
        title="Mit Frist", teacher=lehrperson, idle_timeout_minutes=60
    )
    LearningSession.objects.filter(pk=sitzung.pk).update(
        last_activity_at=timezone.now() - timedelta(minutes=55)
    )
    sitzung.refresh_from_db()
    assert sitzung.ist_offen is True

    sitzung.beruehren()
    sitzung.refresh_from_db()

    assert sitzung.ist_offen is True
    assert sitzung.verfaellt_um > timezone.now() + timedelta(minutes=58)


def test_verfallene_findet_nur_sitzungen_mit_frist(sitzung, lehrperson):
    """Der wichtigste Fall: ohne Frist darf nichts aufgeraeumt werden."""
    mit_frist = LearningSession.objects.create(
        title="Mit Frist", teacher=lehrperson, idle_timeout_minutes=VIER_STUNDEN
    )
    LearningSession.objects.filter(pk__in=[mit_frist.pk, sitzung.pk]).update(
        last_activity_at=timezone.now() - timedelta(days=3)
    )

    verfallen = list(LearningSession.objects.verfallene())

    assert mit_frist in verfallen
    assert sitzung not in verfallen


def test_beschreibung_der_frist(lehrperson):
    ohne = LearningSession.objects.create(title="Ohne", teacher=lehrperson)
    eine = LearningSession.objects.create(
        title="Eine", teacher=lehrperson, idle_timeout_minutes=60
    )
    vier = LearningSession.objects.create(
        title="Vier", teacher=lehrperson, idle_timeout_minutes=VIER_STUNDEN
    )

    assert ohne.verfall_beschreibung == "bleibt offen, bis du sie beendest"
    assert eine.verfall_beschreibung == "verfällt nach 1 Stunde ohne Aktivität"
    assert vier.verfall_beschreibung == "verfällt nach 4 Stunden ohne Aktivität"


# --- Beenden loescht alles -------------------------------------------------

def test_beenden_loescht_aufgaben_und_hilfen(sitzung):
    """'Sitzung beenden loescht alles' ist eine Zusage an die Kinder."""
    teilnahme = _teilnahme(sitzung)
    aufgabe = Task.objects.create(participation=teilnahme, text="Wie viel sind 7 mal 8?")
    Hint.objects.create(task=aufgabe, level=1, text="Du schaffst das.")

    sitzung.beenden()

    assert Participation.objects.filter(learning_session=sitzung).count() == 0
    assert Task.objects.count() == 0
    assert Hint.objects.count() == 0
    assert sitzung.ist_offen is False


def test_beenden_setzt_die_zaehler_zurueck(sitzung):
    teilnahme = _teilnahme(sitzung)
    Task.objects.create(participation=teilnahme, text="Eine Aufgabe")

    sitzung.beenden()

    assert sitzung.zaehler["beigetreten"] == 0
    assert sitzung.zaehler["aufgaben"] == 0


def test_loeschen_der_sitzung_nimmt_alles_mit(sitzung):
    """Der Verfall loescht die Sitzung, daran muss der Rest haengen."""
    teilnahme = _teilnahme(sitzung)
    aufgabe = Task.objects.create(participation=teilnahme, text="Aufgabe")
    Hint.objects.create(task=aufgabe, level=1, text="Hilfe")

    sitzung.delete()

    assert Task.objects.count() == 0
    assert Hint.objects.count() == 0


# --- Zaehler ohne Inhalte --------------------------------------------------

def test_zaehler_zaehlen_richtig(sitzung):
    erste = _teilnahme(sitzung)
    zweite = _teilnahme(sitzung)
    aufgabe = Task.objects.create(participation=erste, text="Aufgabe A")
    Task.objects.create(participation=zweite, text="Aufgabe B")
    Hint.objects.create(task=aufgabe, level=1, text="Anstoss")
    Hint.objects.create(task=aufgabe, level=2, text="Rueckmeldung")
    Participation.objects.filter(pk=erste.pk).update(max_level_reached=2)

    zaehler = sitzung.zaehler

    assert zaehler["beigetreten"] == 2
    assert zaehler["aufgaben"] == 2
    assert zaehler["hilfen"] == 2
    assert zaehler["hoechste_stufe"] == 2


def test_zaehler_enthalten_keine_inhalte(sitzung):
    """Die Lehrperson darf Anzahlen sehen, keine Aufgabentexte."""
    teilnahme = _teilnahme(sitzung)
    aufgabe = Task.objects.create(participation=teilnahme, text="Geheime Aufgabe")
    Hint.objects.create(task=aufgabe, level=1, text="Geheime Hilfe")

    inhalt = " ".join(str(wert) for wert in sitzung.zaehler.values())

    assert "Geheime" not in inhalt
    # Seit 1.11.2026 dazu die Noten der Kinder, als Anzahl und Mittel.
    assert set(sitzung.zaehler) == {"beigetreten", "aufgaben", "hilfen", "hoechste_stufe",
                                    "noten", "note_mittel"}


# --- Die Aufgabe kennt die Obergrenze ihrer Sitzung ------------------------

def test_aufgabe_folgt_der_obergrenze_der_sitzung(sitzung):
    teilnahme = _teilnahme(sitzung)
    aufgabe = Task.objects.create(participation=teilnahme, text="Aufgabe", current_level=3)

    assert aufgabe.obergrenze == levels.NUR_TIPPS
    assert aufgabe.naechste_stufe() is None


def test_aufgabe_geht_bei_freigegebener_loesung_weiter(lehrperson):
    sitzung = LearningSession.objects.create(
        title="Mit Loesung", teacher=lehrperson, max_level=levels.BIS_ZUR_LOESUNG
    )
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung), text="Aufgabe", current_level=3
    )

    assert aufgabe.naechste_stufe() == 4


# --- Teilnahme ist kein Konto ---------------------------------------------

def test_teilnahme_traegt_keinen_namen(sitzung):
    """Der Merker ist Zufall, kein Name und keine Kennung eines Kindes."""
    teilnahme = _teilnahme(sitzung)
    felder = {feld.name for feld in Participation._meta.get_fields()}

    assert "name" not in felder
    assert "user" not in felder
    assert len(teilnahme.token) >= 32


def test_merker_sind_verschieden():
    assert Participation.token_erzeugen() != Participation.token_erzeugen()


# --- Aufraeumen der verfallenen Sitzungen ---------------------------------

def test_aufraeumen_loescht_verfallene_samt_inhalten(sitzung, lehrperson):
    alt = LearningSession.objects.create(
        title="Alt", teacher=lehrperson, idle_timeout_minutes=VIER_STUNDEN
    )
    teilnahme = Participation.objects.create(
        learning_session=alt, token=Participation.token_erzeugen()
    )
    aufgabe = Task.objects.create(participation=teilnahme, text="Alte Aufgabe")
    Hint.objects.create(task=aufgabe, level=1, text="Alte Hilfe")
    LearningSession.objects.filter(pk=alt.pk).update(
        last_activity_at=timezone.now() - timedelta(minutes=VIER_STUNDEN + 1)
    )

    verfallene_aufraeumen()

    assert not LearningSession.objects.filter(pk=alt.pk).exists()
    assert Task.objects.count() == 0
    assert Hint.objects.count() == 0
    assert LearningSession.objects.filter(pk=sitzung.pk).exists()


def test_aufraeumen_laesst_sitzungen_ohne_frist_in_ruhe(sitzung):
    """Sonst verschwaende die Aufraeumfunktion genau das, was offen bleiben soll."""
    teilnahme = Participation.objects.create(
        learning_session=sitzung, token=Participation.token_erzeugen()
    )
    Task.objects.create(participation=teilnahme, text="Laufende Aufgabe")
    LearningSession.objects.filter(pk=sitzung.pk).update(
        last_activity_at=timezone.now() - timedelta(days=30)
    )

    verfallene_aufraeumen()

    assert LearningSession.objects.filter(pk=sitzung.pk).exists()
    assert Task.objects.count() == 1


def test_startseite_raeumt_mit_auf(client, lehrperson):
    """Sonst liegen die Aufgaben, bis sich zufaellig eine Lehrperson anmeldet."""
    alt = LearningSession.objects.create(
        title="Alt", teacher=lehrperson, idle_timeout_minutes=VIER_STUNDEN
    )
    LearningSession.objects.filter(pk=alt.pk).update(
        last_activity_at=timezone.now() - timedelta(minutes=VIER_STUNDEN + 1)
    )

    client.get("/", secure=True)

    assert not LearningSession.objects.filter(pk=alt.pk).exists()
