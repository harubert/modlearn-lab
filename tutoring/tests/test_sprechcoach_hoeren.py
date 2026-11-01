"""Der Gespraechsmodus des Sprechcoaches: hoeren, Sinneinheit, Stille.

Seit dem 19.10.2026 schickt der Browser von selbst ab, sobald eine Pause
erkannt ist - kein Knopf mehr. Was der Server dazu beitraegt, steht hier:
ob eine Aeusserung wie ein abgebrochener Satz aussieht (dann wartet der
Browser kurz weiter), und ob ueberhaupt gesprochen wurde (sonst gibt es
keinen Zug). Beides deterministisch, beides ohne Modell.
"""

import json
import pathlib
import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tutoring import sprechcoach, sprechcoach_views
from tutoring.models import Interaction, LearningSession, Participation, SprachZug
from tutoring.spark import SparkNichtErreichbar
from tutoring.views import SCHLUESSEL_TEILNAHME


# --- Die Sinneinheit --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I",
    "I want to",
    "and",
    "I like the",
    "because",
    "It's",
    "My favourite",
    "I have a dog and",
    "We went to the",
    "um",
    "Ehm, ehm.",
    "",
    "   ",
    "Football",          # ein Wort, kein Ja/Nein: kurz warten, dann trotzdem
    "She is",
    "I think that",
])
def test_ein_abgebrochener_satz_wird_erkannt(text):
    assert sprechcoach.wirkt_unvollstaendig(text, "en-GB") is True


@pytest.mark.parametrize("text", [
    "Yes.",
    "No",
    "Yeah!",
    "Okay.",
    "Hello!",
    "Why?",
    "Seven.",
    "7",
    "Yesterday.",
    "I have a dog.",
    "I like dogs and cats.",
    "My dog is called Max.",
    "What is your name?",
    "I don't know.",
    "I don't.",            # eine verneinte Antwort ist eine ganze
    "I like it.",
    "Me too.",
    "With my brother.",
    "Um, I have a cat.",      # Fuelllaute stoeren nicht
    "I play football, ehm.",  # ... auch nicht am Ende
])
def test_ein_ganzer_satz_wird_nicht_zurueckgehalten(text):
    assert sprechcoach.wirkt_unvollstaendig(text, "en-GB") is False


def test_die_listen_gelten_je_sprache():
    assert sprechcoach.wirkt_unvollstaendig("Je voudrais un", "fr-FR") is True
    assert sprechcoach.wirkt_unvollstaendig("Oui.", "fr-FR") is False
    assert sprechcoach.wirkt_unvollstaendig("Ho un cane e", "it-IT") is True
    assert sprechcoach.wirkt_unvollstaendig("Tengo un perro y", "es-ES") is True
    # Unbekannte Sprache: die englischen Listen, nicht gar keine.
    assert sprechcoach.wirkt_unvollstaendig("I want to", "xx") is True


def test_der_apostroph_bleibt_im_wort():
    """"it's" ist ein Abbruchwort; zerlegt in "it" und "s" waere es keins."""
    assert sprechcoach.wirkt_unvollstaendig("I think it's", "en-GB") is True
    assert sprechcoach.wirkt_unvollstaendig("I think it’s", "en-GB") is True


# --- Der Sprachinhalt -------------------------------------------------------

def test_ohne_text_kein_inhalt():
    assert sprechcoach.hat_sprachinhalt({"text": ""}) is False
    assert sprechcoach.hat_sprachinhalt({"text": " ... "}) is False
    assert sprechcoach.hat_sprachinhalt(None) is False
    assert sprechcoach.hat_sprachinhalt("Hello") is False


def test_text_ohne_abschnitte_zaehlt():
    """Aus fehlenden Belegen wird nie auf Stille geschlossen."""
    assert sprechcoach.hat_sprachinhalt({"text": "Hello"}) is True
    assert sprechcoach.hat_sprachinhalt({"text": "Hello", "segments": []}) is True
    assert sprechcoach.hat_sprachinhalt(
        {"text": "Hello", "segments": [{"text": "Hello", "start": 0, "end": 1}]}
    ) is True


def test_whispers_eigene_regel_erkennt_stille():
    """no_speech_prob ueber 0,6 UND avg_logprob unter -1: kein Abschnitt."""
    erfunden = {"text": "Thank you.", "segments": [
        {"no_speech_prob": 0.93, "avg_logprob": -1.6},
    ]}
    assert sprechcoach.hat_sprachinhalt(erfunden) is False

    # Sicherer Text trotz hoher Stillewahrscheinlichkeit bleibt (so haelt es
    # Whisper selbst).
    sicher = {"text": "Thank you.", "segments": [
        {"no_speech_prob": 0.93, "avg_logprob": -0.3},
    ]}
    assert sprechcoach.hat_sprachinhalt(sicher) is True

    # Ein brauchbarer Abschnitt genuegt.
    gemischt = {"text": "Hm. I have a dog.", "segments": [
        {"no_speech_prob": 0.93, "avg_logprob": -1.6},
        {"no_speech_prob": 0.05, "avg_logprob": -0.4},
    ]}
    assert sprechcoach.hat_sprachinhalt(gemischt) is True


def test_sich_wiederholender_text_ist_keiner():
    schleife = {"text": "the the the the the the", "segments": [
        {"no_speech_prob": 0.1, "avg_logprob": -0.5, "compression_ratio": 3.1},
    ]}
    assert sprechcoach.hat_sprachinhalt(schleife) is False


@pytest.mark.parametrize("text", [
    "Thanks for watching!",
    "Subtitles by the Amara.org community",
    "Untertitel im Auftrag des ZDF",
    "Please subscribe to my channel",
])
def test_untertitel_floskeln_sind_kein_inhalt(text):
    assert sprechcoach.hat_sprachinhalt({"text": text}) is False


def test_thank_you_allein_ist_inhalt():
    """Das sagt man im Gespraech - nur die Abschnitte duerfen es kippen."""
    assert sprechcoach.hat_sprachinhalt({"text": "Thank you."}) is True


# --- Der Endpunkt -----------------------------------------------------------

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
def whisper(monkeypatch):
    """Ersetzt Whisper. Antwortet, was der Test hineinlegt, und merkt sich,
    welche Sprache verlangt wurde."""
    zustand = {"antwort": {"text": "I have a dog.", "language": "en"}, "gesehen": []}

    def attrappe(daten, dateiname, sprache):
        zustand["gesehen"].append({"sprache": sprache, "bytes": len(daten),
                                   "dateiname": dateiname})
        if isinstance(zustand["antwort"], Exception):
            raise zustand["antwort"]
        return zustand["antwort"]

    monkeypatch.setattr(sprechcoach_views, "transkription", attrappe)
    return zustand


def _hoeren(client):
    return client.post(
        reverse("tutoring:sprechcoach_hoeren"),
        {"aufnahme": SimpleUploadedFile("aufnahme.wav", b"RIFF....WAVEfmt ")},
        secure=True,
    )


@pytest.mark.django_db
def test_ein_ganzer_satz_kommt_als_beitrag_zurueck(client, kind, whisper):
    antwort = _hoeren(client)

    daten = antwort.json()
    assert antwort.status_code == 200
    assert daten["ok"] is True
    assert daten["stille"] is False
    assert daten["fragment"] is False
    assert daten["text"] == "I have a dog."
    assert daten["erkannt"] == "en"
    assert whisper["gesehen"][0]["sprache"] is None, "Whisper bestimmt die Sprache selbst"
    assert SprachZug.objects.count() == 0, "hoeren ist kein Zug"


@pytest.mark.django_db
def test_ein_halber_satz_wird_als_fragment_gemeldet(client, kind, whisper):
    whisper["antwort"] = {"text": "I want to", "language": "en", "segments": [
        {"no_speech_prob": 0.02, "avg_logprob": -0.4},
    ]}

    daten = _hoeren(client).json()

    assert daten["ok"] is True
    assert daten["fragment"] is True
    assert daten["text"] == "I want to"
    assert SprachZug.objects.count() == 0
    assert Interaction.objects.filter(outcome="fragment").exists()


@pytest.mark.django_db
def test_stille_ist_kein_zug(client, kind, whisper):
    """Whisper erfindet bei Stille Saetze. Die Abschnitte verraten es."""
    whisper["antwort"] = {"text": "Thank you.", "language": "en", "segments": [
        {"no_speech_prob": 0.97, "avg_logprob": -1.9},
    ]}

    daten = _hoeren(client).json()

    assert daten["ok"] is True
    assert daten["stille"] is True
    assert daten["text"] == ""
    assert "fragment" not in daten
    assert SprachZug.objects.count() == 0
    zeile = Interaction.objects.get()
    assert zeile.outcome == "kein_text"


@pytest.mark.django_db
def test_die_aufnahme_wird_nirgends_abgelegt(client, kind, whisper):
    """Was ins Protokoll geht, ist der Text - nie der Ton."""
    _hoeren(client)

    zeile = Interaction.objects.get()
    assert zeile.outcome == "ok"
    assert "RIFF" not in (zeile.masked_input or "")
    assert "RIFF" not in (zeile.masked_output or "")
    assert whisper["gesehen"][0]["bytes"] > 0


@pytest.mark.django_db
def test_ohne_spark_eine_meldung_und_kein_zug(client, kind, whisper):
    whisper["antwort"] = SparkNichtErreichbar("aus")

    antwort = _hoeren(client)

    assert antwort.status_code == 503
    assert antwort.json()["ok"] is False
    assert SprachZug.objects.count() == 0


@pytest.mark.django_db
def test_hoeren_braucht_sitzung_und_aufnahme(client, kind, whisper):
    ohne_aufnahme = client.post(reverse("tutoring:sprechcoach_hoeren"), secure=True)
    assert ohne_aufnahme.status_code == 400

    client.session.flush()
    client.cookies.clear()
    ohne_sitzung = _hoeren(client)
    assert ohne_sitzung.status_code == 403


@pytest.mark.django_db
def test_hoeren_gibt_es_nur_im_sprechcoach(client, whisper):
    """Die Aufgabenhilfe hat ihren eigenen Weg (sitzung/sprache/), der bleibt."""
    lehrperson = get_user_model().objects.create_user(username="m", password="x")
    mathe = LearningSession.objects.create(title="Mathe", teacher=lehrperson)
    teilnahme = Participation.objects.create(learning_session=mathe, animal="igel", token="t2")
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()

    antwort = _hoeren(client)

    assert antwort.status_code == 400
    assert whisper["gesehen"] == [], "Whisper wird gar nicht erst gefragt"


# --- Die Seite --------------------------------------------------------------

@pytest.fixture
def modell(monkeypatch):
    def attrappe(system, frage, max_tokens=500):
        return (json.dumps({"antwort": "Hi! Do you have a pet?",
                            "uebersetzung": "Hallo! Hast du ein Haustier?",
                            "korrektur": ""}),
                {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1})
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)


@pytest.fixture
def mikrofon_moeglich(monkeypatch):
    monkeypatch.setattr(sprechcoach_views, "sprache_moeglich", lambda: True)


JS_PFAD = pathlib.Path(settings.BASE_DIR) / "static" / "js" / "sprechcoach.js"
WORKLET_PFAD = pathlib.Path(settings.BASE_DIR) / "static" / "js" / "sprechcoach_worklet.js"


@pytest.mark.django_db
def test_die_gespraechsseite_traegt_ring_und_hoeradresse(client, kind, modell, mikrofon_moeglich):
    seite = client.get(reverse("tutoring:sprechcoach"), secure=True)

    assert seite.status_code == 200
    html = seite.content.decode()
    assert 'id="coach-ring"' in html
    assert 'data-erkennen="' + reverse("tutoring:sprechcoach_hoeren") + '"' in html
    assert "sprechcoach_worklet" in html, "die Adresse des Sammlers reist mit"
    assert "Leertaste" not in html, "keine Taste ist noetig, also steht keine da"
    assert 'id="coach-funk"' in html, "der eine Tipp am Anfang bleibt"
    assert "Gespräch starten" in html
    assert 'id="coach-pegel"' not in html, "die Saeulen sind durch den Ring ersetzt"
    # Ohne Endung: Im Abbild haengt WhiteNoise den Manifest-Hash an
    # ("sprechcoach.39297220a456.js"), und genau daran ist das Deployment am
    # 19.10.2026 einmal gescheitert.
    assert "js/sprechcoach." in html


@pytest.mark.django_db
def test_ohne_spracherkennung_bleibt_das_tippen_der_weg(client, kind, modell, monkeypatch):
    monkeypatch.setattr(sprechcoach_views, "sprache_moeglich", lambda: False)

    html = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()

    assert 'id="coach-ring"' not in html
    assert "data-erkennen" not in html
    assert 'id="coach-form"' in html
    assert "oder tippen" in html


@pytest.mark.django_db
def test_jede_kennung_die_das_skript_sucht_steht_auf_der_seite(client, kind, modell, mikrofon_moeglich):
    """Das Skript faengt fehlende Elemente ab, aber ein Tippfehler in einer
    Kennung faellt sonst nie auf. Vorlage und Skript muessen zusammenpassen."""
    html = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()
    skript = JS_PFAD.read_text(encoding="utf-8")
    kennungen = set(re.findall(r'getElementById\("([^"]+)"\)', skript))

    assert kennungen, "das Skript sucht seine Elemente ueber Kennungen"
    fehlend = sorted(k for k in kennungen if f'id="{k}"' not in html)
    assert fehlend == []


def test_das_skript_ist_eine_iife_ohne_emojis():
    skript = JS_PFAD.read_text(encoding="utf-8")
    sammler = WORKLET_PFAD.read_text(encoding="utf-8")
    assert skript.lstrip().startswith("/*")
    assert "(function () {" in skript and skript.rstrip().endswith("})();")
    for text in (skript, sammler):
        assert [z for z in text if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF] == []
    assert 'registerProcessor("sprechcoach-sammler"' in sammler
    assert '"sprechcoach-sammler"' in skript, "derselbe Name in beiden Dateien"


def test_die_zahlen_des_gespraechsmodus_stehen_im_skript():
    """Die Masse aus dem Auftrag, als Zahlen nachpruefbar."""
    skript = JS_PFAD.read_text(encoding="utf-8")
    assert "var ANLAUF_MS = 150;" in skript
    assert "var PAUSE_MS = 900;" in skript
    assert "var PAUSE_LANG_MS = 1500;" in skript
    assert "var HOECHSTDAUER_MS = 25000;" in skript
    assert "var FRAGMENT_WARTE_MS = 2000;" in skript
    assert "var ANLAUF_ECHO_MS = 300;" in skript
    assert "echoCancellation: true" in skript
    assert "speechSynthesis.cancel()" in skript
