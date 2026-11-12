"""Die Stimme vom Server (tutoring/stimme.py, 7.11.2026): Vorbereitung des
Einbaus mit Attrappe, bevor Qwen3-TTS am Spark laeuft.

Gesprochen wird nur, was die Anwendung geschrieben hat (ein Zug nach
Kennung), die Attrappe liefert ohne Netz eine Tondatei, der Dienst wird in
der Form von OpenAI angesprochen, ein Ausfall ist eine Meldung und kein
Fehler, und die Seite erfaehrt die Adresse nur, wenn es eine Stimme gibt.
"""

import io
import pathlib
import wave

import httpx
import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import stimme
from tutoring.models import Interaction, LearningSession, Participation, SprachLauf, SprachZug
from tutoring.spark import SparkNichtErreichbar
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

JS = pathlib.Path(django_settings.BASE_DIR) / "static" / "js" / "sprechcoach.js"


@pytest.fixture(autouse=True)
def leerer_zwischenspeicher():
    stimme.zwischenspeicher_leeren()
    yield
    stimme.zwischenspeicher_leeren()


@pytest.fixture
def attrappe(settings):
    settings.SPARK_TTS_BASE_URL = ""
    settings.SPARK_TTS_ATTRAPPE = True


@pytest.fixture
def keine_stimme(settings):
    settings.SPARK_TTS_BASE_URL = ""
    settings.SPARK_TTS_ATTRAPPE = False


def _wav(daten):
    with wave.open(io.BytesIO(daten), "rb") as datei:
        return datei.getnchannels(), datei.getframerate(), datei.getnframes()


# --- Das Modul ------------------------------------------------------------------

def test_saetze_zerlegen_und_sehr_kurze_haengen_am_nachbarn():
    assert stimme.saetze("Hello! How are you? I am fine. What about you?") == [
        "Hello! How are you?", "I am fine.", "What about you?",
    ]
    assert stimme.saetze("  ") == []
    assert stimme.saetze("Yes.") == ["Yes."]


def test_die_attrappe_liefert_eine_wav_datei_in_der_laenge_des_textes(attrappe):
    kurz, messung = stimme.sprechen("Hello there.", sprache="en-GB")
    lang, _ = stimme.sprechen("One two three four five six seven eight nine ten.", sprache="en-GB")
    kanaele, rate, kurz_n = _wav(kurz)
    assert (kanaele, rate) == (1, stimme.ABTASTRATE)
    assert _wav(lang)[2] > kurz_n
    assert messung["modell"] == stimme.ATTRAPPE and messung["sprache"] == "English"
    assert messung["stimme"] == "Ryan" and messung["zwischenspeicher"] is False


def test_der_zwischenspeicher_spart_den_zweiten_aufruf(attrappe):
    erst, m1 = stimme.sprechen("Where were we?", sprache="en-GB")
    zweit, m2 = stimme.sprechen("Where were we?", sprache="en-GB")
    assert erst == zweit and m1["zwischenspeicher"] is False and m2["zwischenspeicher"] is True


def test_ohne_adresse_und_ohne_attrappe_gibt_es_keine_stimme(keine_stimme):
    assert stimme.moeglich() is False
    with pytest.raises(SparkNichtErreichbar) as fehler:
        stimme.sprechen("Hallo")
    assert fehler.value.meldung == stimme.MELDUNG_AUS


def test_der_dienst_wird_in_der_form_von_openai_gerufen(settings, monkeypatch):
    settings.SPARK_TTS_BASE_URL = "http://spark.test:8003/v1/"
    settings.SPARK_TTS_ATTRAPPE = True   # mit Adresse wirkungslos
    gesehen = {}

    def _anfragen(rumpf, adresse):
        gesehen.update(rumpf=rumpf, adresse=adresse)
        return stimme.attrappe("x")
    monkeypatch.setattr(stimme, "_anfragen", _anfragen)

    daten, messung = stimme.sprechen("Bonjour !   Ça va ?", sprache="fr-FR")

    assert gesehen["adresse"] == "http://spark.test:8003/v1"
    assert gesehen["rumpf"] == {"input": "Bonjour ! Ça va ?", "voice": "Ryan", "language": "French",
                                "response_format": "wav", "model": settings.SPARK_TTS_MODEL}
    assert messung["modell"] == settings.SPARK_TTS_MODEL and daten[:4] == b"RIFF"
    assert stimme.attrappe_an() is False


def test_ein_ausfall_des_dienstes_ist_eine_meldung(settings, monkeypatch):
    settings.SPARK_TTS_BASE_URL = "http://spark.test:8003/v1"

    def _weg(rumpf, adresse):
        raise httpx.ConnectError("weg")
    monkeypatch.setattr(stimme, "_anfragen", _weg)
    with pytest.raises(SparkNichtErreichbar) as fehler:
        stimme.sprechen("Hallo")
    assert fehler.value.meldung == stimme.MELDUNG_WEG

    monkeypatch.setattr(stimme, "_anfragen", lambda rumpf, adresse: b"<html>Fehler</html>")
    with pytest.raises(SparkNichtErreichbar):
        stimme.sprechen("Hallo noch einmal")


def test_sprachnamen():
    assert stimme.sprachname("en-GB") == "English"
    assert stimme.sprachname("de") == "German"
    assert stimme.sprachname("") == "German"
    assert stimme.sprachname("xx-YY") == "German"


# --- Die Ansicht ------------------------------------------------------------------

@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


@pytest.fixture
def englischstunde(lehrperson):
    return LearningSession.objects.create(
        title="Englisch 3b", teacher=lehrperson, mode=LearningSession.BETRIEB_SPRACHE,
        subject="englisch", target_language="en-GB", language_level="A1", task_hint="pets",
    )


@pytest.fixture
def kind(client, englischstunde):
    teilnahme = Participation.objects.create(learning_session=englischstunde, animal="biber", token="t1")
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.fixture
def coachzug(kind):
    lauf = SprachLauf.objects.create(participation=kind)
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text="I have a dog.")
    return SprachZug.objects.create(run=lauf, role=SprachZug.COACH,
                                    text="Nice! What is your dog's name? How old is it?")


def _ton(client, **felder):
    return client.post(reverse("tutoring:stimme_zug"), felder, secure=True)


def test_ein_zug_des_coaches_kommt_als_ton_zurueck_und_steht_im_protokoll(client, kind, coachzug, attrappe):
    antwort = _ton(client, zug=coachzug.pk)

    assert antwort.status_code == 200
    assert antwort["Content-Type"] == "audio/wav"
    assert antwort["X-Stimme"] == stimme.ATTRAPPE
    assert _wav(antwort.content)[1] == stimme.ABTASTRATE
    zeile = Interaction.objects.get(outcome="stimme")
    assert zeile.model_name == stimme.ATTRAPPE and zeile.route == Interaction.LOKAL

    # Noch einmal derselbe Zug: aus dem Zwischenspeicher, keine zweite Zeile.
    assert _ton(client, zug=coachzug.pk).status_code == 200
    assert Interaction.objects.filter(outcome="stimme").count() == 1


def test_satz_fuer_satz(client, kind, coachzug, attrappe):
    # "Nice!" ist zu kurz fuer einen eigenen Ton und haengt am naechsten Satz.
    erster = _ton(client, zug=coachzug.pk, satz=0)
    zweiter = _ton(client, zug=coachzug.pk, satz=1)
    assert erster.status_code == 200 and zweiter.status_code == 200
    assert _ton(client, zug=coachzug.pk, satz=2).status_code == 204, "das Ende ist kein Fehler"
    zeilen = list(Interaction.objects.filter(outcome="stimme").order_by("pk"))
    assert len(zeilen) == 2
    auskunft = client.get(reverse("tutoring:stimme_saetze"), {"zug": coachzug.pk}, secure=True).json()
    assert auskunft == {"ok": True, "saetze": 2, "moeglich": True}


def test_nur_eigene_coach_zuege_und_nie_freier_text(client, kind, coachzug, attrappe, lehrperson):
    assert _ton(client, text="Sag irgendwas.").status_code == 400
    eigener = SprachZug.objects.get(role=SprachZug.LERNEND)
    assert _ton(client, zug=eigener.pk).status_code == 404, "nur Zuege des Coaches"

    andere = LearningSession.objects.create(title="Fremd", teacher=lehrperson,
                                            mode=LearningSession.BETRIEB_SPRACHE, subject="englisch")
    fremde = Participation.objects.create(learning_session=andere, animal="igel", token="t2")
    fremder_lauf = SprachLauf.objects.create(participation=fremde)
    fremder = SprachZug.objects.create(run=fremder_lauf, role=SprachZug.COACH, text="Hello.")
    assert _ton(client, zug=fremder.pk).status_code == 404

    client.logout()
    s = client.session
    s.flush()
    assert _ton(client, zug=coachzug.pk).status_code == 403


def test_ohne_stimme_antwortet_der_weg_mit_404_und_die_seite_bleibt_beim_browser(client, kind, coachzug, keine_stimme):
    assert _ton(client, zug=coachzug.pk).status_code == 404
    seite = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()
    assert 'data-stimme=""' in seite


def test_die_seite_nennt_die_adresse_und_die_kennungen(client, kind, coachzug, attrappe):
    seite = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()
    assert f'data-stimme="{reverse("tutoring:stimme_zug")}"' in seite
    assert f'data-zug="{coachzug.pk}"' in seite
    assert "Stimme der Hochschule" in seite


def test_das_skript_kennt_die_serverstimme_und_den_rueckfall():
    quelle = JS.read_text(encoding="utf-8")
    for marke in ("data-stimme", "serverStimmeAn", "satzSpielen", "tonHolen",
                  "serverWeiterlesen", "Stimme der Hochschule", "sprechenAb(satz, 0, meine, einmal)"):
        assert marke in quelle, marke
    assert quelle.count("coachSpricht(letzterCoachsatz(), true)") == 0, \
        "jeder Aufruf gibt die Kennung des Zuges mit"
