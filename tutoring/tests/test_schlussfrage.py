"""Die Schlussfrage wird erzwungen, nicht erbeten (Zech, S. 289).

Lauf F (31.10.2026, Qwen3.6): 91 von 313 Zuegen ohne Frage, 48 davon, weil
die Kuerzung den Fragesatz entfernt hatte. Seit Lauf G fasst der Server
einmal nach, prueft die Frage wie die Hilfe und haengt sonst die Vorlage der
Stufe an.
"""
import asyncio
import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import ausgabepruefung, levels, views
from tutoring.models import LearningSession, Participation, Task
from tutoring.views import SCHLUESSEL_TEILNAHME

AUFGABE = ("Lena hat 7 Murmeln. Sie bekommt von Omar noch 5 Murmeln dazu. "
           "Wie viele Murmeln hat sie jetzt?")
EIGENES = [AUFGABE]
VORLAGE_1 = "Was soll man hier herausfinden?"


# --- Die reinen Pruefungen ---------------------------------------------------

def test_endet_mit_frage():
    assert ausgabepruefung.endet_mit_frage("Wie viele Murmeln hat Lena jetzt?")
    assert ausgabepruefung.endet_mit_frage('Schau hin: "Wie viele sind es?"')
    assert not ausgabepruefung.endet_mit_frage("Wie viele sind es? Probier es.")
    assert not ausgabepruefung.endet_mit_frage("Probier es.")
    assert not ausgabepruefung.endet_mit_frage("")


def test_der_nachsatz_hinter_der_frage_faellt_weg():
    text = "Schau auf die Murmeln. Wie viele sind es? Probier es aus. Du schaffst das."
    assert ausgabepruefung.ohne_nachsatz_zur_frage(text) == (
        "Schau auf die Murmeln. Wie viele sind es?")
    lang = "Wie viele sind es? Erst. Dann. Danach. Zuletzt."
    assert ausgabepruefung.ohne_nachsatz_zur_frage(lang) == lang, \
        "mehr als zwei Saetze: die Frage war der Anfang, nicht der Schluss"
    assert ausgabepruefung.ohne_nachsatz_zur_frage("Probier es aus.") == "Probier es aus."
    assert ausgabepruefung.ohne_nachsatz_zur_frage("Wie viele?") == "Wie viele?"


@pytest.mark.parametrize("roh, erwartet", [
    ('Frage: "Was soll man hier herausfinden?"', "Was soll man hier herausfinden?"),
    ("Lies die Angabe noch einmal. Was ist gesucht?", "Was ist gesucht?"),
    ("Was rechnest du? Und was kommt heraus?", ""),
    ("Probier es einfach aus.", ""),
    ("", ""),
])
def test_die_frage_aus_dem_nachfassen(roh, erwartet):
    assert ausgabepruefung.frage_bereinigt(roh, 1, levels.LOESUNG, EIGENES) == erwartet


def test_eine_frage_die_verstoesst_oder_zu_lang_ist_taugt_nicht():
    assert ausgabepruefung.frage_bereinigt("Wie viel ist 7 + 5?", 1, levels.LOESUNG, EIGENES) == ""
    assert ausgabepruefung.frage_bereinigt(
        "Wie viel ist 7 + 5?", 4, levels.LOESUNG, EIGENES) == "Wie viel ist 7 + 5?"
    zu_lang = "Was " + "denkst du, wenn du " * 10 + "nachrechnest?"
    assert ausgabepruefung.frage_bereinigt(zu_lang, 1, levels.LOESUNG, EIGENES) == ""


def test_die_vorlage_je_zug():
    assert levels.schlussfrage_vorlage(levels.ART_HILFE, 2) == "Was rechnest du jetzt?"
    assert levels.schlussfrage_vorlage(levels.ART_HILFE, levels.LOESUNG) is None
    assert levels.schlussfrage_vorlage(levels.ART_NACHSATZ) is None
    assert levels.schlussfrage_vorlage(levels.ART_AUFTAKT) is None
    assert levels.schlussfrage_vorlage(levels.ART_NACHFRAGE) == "Wo kommst du nicht weiter?"
    assert levels.schlussfrage_vorlage(levels.ART_BESTAETIGUNG).endswith("?")
    for stufe in (1, 2, 3, 4):
        frage = levels.schlussfrage_vorlage(levels.ART_HILFE, stufe)
        assert frage.count("?") == 1 and frage.endswith("?")
        assert not ausgabepruefung.verstoesse(frage, stufe, levels.LOESUNG, EIGENES)


# --- Der Weg durch die Erzeugung --------------------------------------------

class _Modell:
    """Antwortet der Reihe nach (die letzte Antwort immer wieder) und merkt sich die Anfragen."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.anfragen = []

    async def __call__(self, system, frage, messung, *a, **k):
        self.anfragen.append((system, frage))
        return self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]


def _erzeugen(monkeypatch, modell, stufe=1, schlussfrage=VORLAGE_1):
    monkeypatch.setattr(views, "_am_stueck", modell)
    return asyncio.run(views._geprueft_erzeugen(
        "SYSTEM", "ANFRAGE", {}, stufe, levels.LOESUNG, eigenes=EIGENES,
        schlussfrage=schlussfrage,
    ))


def test_ohne_frage_wird_nachgefasst(monkeypatch):
    modell = _Modell("Lena hat Murmeln und bekommt welche dazu.",
                     "Wie viele Murmeln hat Lena jetzt?")
    text = _erzeugen(monkeypatch, modell)
    assert text == "Lena hat Murmeln und bekommt welche dazu. Wie viele Murmeln hat Lena jetzt?"
    assert len(modell.anfragen) == 2
    system, frage = modell.anfragen[1]
    assert system == "SYSTEM", "dieselben Regeln wie fuer die Hilfe"
    assert frage.startswith("ANFRAGE") and "Deine Hilfe:" in frage
    assert "Lena hat Murmeln und bekommt welche dazu." in frage


def test_taugt_die_frage_nicht_kommt_die_vorlage(monkeypatch):
    modell = _Modell("Lena hat Murmeln und bekommt welche dazu.", "Wie viel ist 7 + 5?")
    assert _erzeugen(monkeypatch, modell) == (
        "Lena hat Murmeln und bekommt welche dazu. " + VORLAGE_1)
    # Auch beim Nachfassen keine Frage: die Vorlage.
    modell = _Modell("Lena hat Murmeln und bekommt welche dazu.")
    assert _erzeugen(monkeypatch, modell).endswith(VORLAGE_1)
    assert len(modell.anfragen) == 2


def test_mit_frage_am_ende_wird_nicht_nachgefasst(monkeypatch):
    modell = _Modell("Lena hat Murmeln. Wie viele hat sie jetzt?")
    assert _erzeugen(monkeypatch, modell) == "Lena hat Murmeln. Wie viele hat sie jetzt?"
    assert len(modell.anfragen) == 1


def test_der_nachsatz_hinter_der_frage_faellt_ohne_anfrage_weg(monkeypatch):
    modell = _Modell("Wie viele hat sie jetzt? Probier es aus.")
    assert _erzeugen(monkeypatch, modell) == "Wie viele hat sie jetzt?"
    assert len(modell.anfragen) == 1


def test_ohne_vorlage_bleibt_der_text_wie_er_ist(monkeypatch):
    modell = _Modell("Die Lösung: 7 + 5 = 12 Murmeln.")
    assert _erzeugen(monkeypatch, modell, stufe=levels.LOESUNG, schlussfrage=None) == (
        "Die Lösung: 7 + 5 = 12 Murmeln.")
    assert len(modell.anfragen) == 1


def test_auch_die_gekuerzte_hilfe_endet_mit_frage(monkeypatch):
    """Lauf F: 48 von 91 Zuegen ohne Frage, weil die Kuerzung den Fragesatz entfernt hatte."""
    modell = _Modell(
        "Lena hat 7 Murmeln. Wie viel ist 7 + 5?",
        "Lena hat 7 Murmeln. Rechne 7 + 5, was ist das?",
        "Was soll Lena herausfinden?",
    )
    assert _erzeugen(monkeypatch, modell) == "Lena hat 7 Murmeln. Was soll Lena herausfinden?"
    assert len(modell.anfragen) == 3


# --- Durch die Seite: die gespeicherte Hilfe endet mit der Frage ------------

@pytest.fixture
def stunde(db):
    lehrperson = get_user_model().objects.create_user(username="l", password="x")
    return LearningSession.objects.create(
        title="Mathe", teacher=lehrperson, max_level=levels.LOESUNG,
    )


@pytest.fixture
def kind(client, stunde):
    teilnahme = Participation.objects.create(
        learning_session=stunde, animal="igel", token="t-igel",
    )
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.mark.django_db
def test_die_gespeicherte_hilfe_endet_mit_der_frage(client, kind, monkeypatch):
    """Der erste Zug ist seit 1.11.2026 die Nachfrage; ihre Vorlage fragt
    nach der Schwierigkeit."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)
    modell = _Modell("Lena hat Murmeln und bekommt von Omar welche dazu.")
    monkeypatch.setattr(views, "_am_stueck", modell)
    vorlage = levels.schlussfrage_vorlage(levels.ART_NACHFRAGE)

    antwort = client.post(reverse("tutoring:hilfe", args=[aufgabe.pk]), {}, secure=True)
    strom = b"".join(antwort).decode()

    assert '"art": "nachfrage"' in strom
    stuecke = "".join(json.loads(zeile[len("data: "):])["text"]
                      for zeile in strom.split("\n")
                      if zeile.startswith('data: {"text"'))
    assert stuecke.endswith(vorlage)
    hilfe = aufgabe.hints.get()
    assert hilfe.text == "Lena hat Murmeln und bekommt von Omar welche dazu. " + vorlage
    assert levels.letzte_frage(hilfe.text) == vorlage
    assert len(modell.anfragen) == 2
