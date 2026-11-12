"""Die Fachgrenze im Sprechcoach und auf dem Versuchsweg der Aufgabenhilfe
(Thomas, 7.11.2026: "make it so" zum Vorschlag, die beiden offenen Wege
nachzuziehen).

Sprechcoach: Der Pfoertner urteilt nur fuer Beitraege in der Zielsprache und
mit dem Zusatz, dass in einer Sprechstunde fast alles zur Stunde gehoert.
Sagt er nein, antwortet der Coach mit dem festen Satz in der Zielsprache,
kein Modell wird gefragt, die Phase bleibt, die letzte Frage des Coaches ist
der Rueckweg.

Versuchsweg: Diagnose und Pfoertner laufen zusammen. Eine Rechnung braucht
keinen Pfoertner. Sagt er nein, zaehlt der Beitrag nicht als Versuch, und
der naechste Zug ist die Nachfrage mit dem festen Satz des Fachs, vom Server
geschrieben, nicht vom Modell.

Kein Netz: Pfoertner, Ampel, Diagnose und Modell werden ersetzt.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import fachgrenze, levels, pruefung, sprechcoach_views, views
from tutoring.models import (Hint, Interaction, LearningSession, Participation,
                             SprachZug, Task, Zug)
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

PEKING_EN = "What happened on Tiananmen Square in 1989?"
PEKING_DE = "Was geschah 1989 am Platz des Himmlischen Friedens?"
AUFGABE = "Lena kauft 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?"


# --- Attrappen ---------------------------------------------------------------------

def _pfoertner(monkeypatch, urteil, grund="anderes Wissensgebiet"):
    def _anfragen(rumpf, adresse):
        _anfragen.aufrufe.append(rumpf)
        if isinstance(urteil, Exception):
            raise urteil
        return {"model": rumpf["model"], "usage": {"prompt_tokens": 80, "completion_tokens": 12},
                "choices": [{"message": {"content": json.dumps({"zur_stunde": urteil, "grund": grund})}}]}
    _anfragen.aufrufe = []
    monkeypatch.setattr(fachgrenze, "_anfragen", _anfragen)
    return _anfragen


@pytest.fixture(autouse=True)
def ampel_gruen(monkeypatch):
    monkeypatch.setattr(pruefung, "einstufen", lambda text: (pruefung.GRUEN, ""))


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _anmelden(client, teilnahme):
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()


# --- Sprechcoach -------------------------------------------------------------------

@pytest.fixture
def englischstunde(lehrperson):
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
    _anmelden(client, teilnahme)
    return teilnahme


@pytest.fixture
def coach_modell(monkeypatch):
    """Der Coach antwortet brav auf Englisch; die Aufrufe werden gezaehlt."""
    aufrufe = []

    def attrappe(system, frage, max_tokens=500):
        aufrufe.append(frage)
        return (json.dumps({"antwort": "What is your pet's name?",
                            "uebersetzung": "Wie heißt dein Haustier?", "korrektur": ""}),
                {"modell": "probe", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1})
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)
    return aufrufe


def _coachzug(client, text, erkannt="en"):
    return client.post(reverse("tutoring:sprechcoach_zug"),
                       {"text": text, "erkannt": erkannt, "herkunft": "tippen"},
                       HTTP_X_ANTWORT="json", secure=True)


def test_der_coach_antwortet_auf_eine_fremde_frage_mit_dem_festen_satz(client, kind, coach_modell, monkeypatch):
    lauf = sprechcoach_views._lauf_holen(kind)
    SprachZug.objects.create(run=lauf, role=SprachZug.COACH,
                             text="Hello! Do you have a pet? What is its name?", phase=lauf.phase)
    anfrage = _pfoertner(monkeypatch, "nein")

    antwort = _coachzug(client, PEKING_EN)

    daten = antwort.json()
    assert antwort.status_code == 200 and daten["fachgrenze"] is True
    assert daten["coach"] == "That is another topic. Here we practise English together. What is its name?"
    assert daten["uebersetzung"].startswith("Das ist ein anderes Thema.")
    assert daten["nicht_verstanden"] is False
    assert coach_modell == [], "kein Modell formuliert die Antwort"
    assert daten["zug"] == SprachZug.objects.filter(role=SprachZug.COACH).last().pk

    beitrag = SprachZug.objects.get(role=SprachZug.LERNEND)
    assert beitrag.flag == pruefung.GELB and beitrag.flag_reason == fachgrenze.GRUND
    lauf.refresh_from_db()
    assert lauf.phase == beitrag.phase, "die Phase bleibt"

    # Der Pfoertner kennt die Stunde und ihre Eigenart, nicht das heikle Thema.
    system = anfrage.aufrufe[0]["messages"][0]["content"]
    assert "Fach: Englisch." in system and "pets" in system
    assert "Sprechstunde in Englisch" in system
    for wort in ("China", "Tiananmen", "heikel"):
        assert wort not in system
    assert Interaction.objects.filter(outcome="sprechcoach:pfoertner:nein").count() == 1


def test_ein_ja_des_pfoertners_laesst_den_coach_antworten(client, kind, coach_modell, monkeypatch):
    _pfoertner(monkeypatch, "ja", "Smalltalk gehört dazu")
    daten = _coachzug(client, "I like football more than pets.").json()
    assert daten["fachgrenze"] is False
    assert daten["coach"] == "What is your pet's name?"
    assert coach_modell, "das Modell wurde gefragt"


def test_ein_ausfall_des_pfoertners_haelt_das_gespraech_nicht_an(client, kind, coach_modell):
    # conftest: der Pfoertner ist ohne Netz, also unklar.
    daten = _coachzug(client, PEKING_EN).json()
    assert daten["fachgrenze"] is False and coach_modell


def test_deutsch_bekommt_die_sperre_und_der_pfoertner_wird_nicht_gefragt(client, kind, coach_modell, monkeypatch):
    anfrage = _pfoertner(monkeypatch, "nein")
    daten = _coachzug(client, PEKING_DE, erkannt="de").json()
    assert daten["nicht_verstanden"] is True and daten["fachgrenze"] is False
    assert anfrage.aufrufe == [] and coach_modell == []


def test_der_feste_satz_gibt_es_in_vier_sprachen_und_ohne_rueckfrage():
    en, en_de = fachgrenze.satz_sprache("en-GB")
    assert en == "That is another topic. Here we practise English together. Where were we?"
    assert en_de.endswith("Wo waren wir stehen geblieben?")
    fr, _ = fachgrenze.satz_sprache("fr-FR", rueckfrage="Tu as un animal ?")
    assert fr.startswith("C'est un autre sujet.") and fr.endswith("Tu as un animal ?")
    assert fachgrenze.satz_sprache("it-IT")[0].startswith("Questo è un altro argomento.")
    assert fachgrenze.satz_sprache("es-ES")[0].startswith("Eso es otro tema.")
    assert fachgrenze.satz_sprache("xx")[0] == en, "Unbekanntes faellt auf Englisch zurueck"
    for wort in ("China", "Peking", "politic"):
        assert wort.lower() not in en.lower()


def test_ohne_frage_des_coaches_kommt_der_rueckweg_der_sprache(client, kind, coach_modell, monkeypatch):
    _pfoertner(monkeypatch, "nein")
    daten = _coachzug(client, PEKING_EN).json()
    assert daten["coach"].endswith("Where were we?")


# --- Versuchsweg der Aufgabenhilfe --------------------------------------------------

@pytest.fixture
def mathestunde(lehrperson):
    return LearningSession.objects.create(
        title="Mathe", teacher=lehrperson, max_level=levels.LOESUNG, task_hint="Sachaufgaben",
    )


@pytest.fixture
def schuelerin(client, mathestunde):
    teilnahme = Participation.objects.create(
        learning_session=mathestunde, animal="igel", token="t-igel",
    )
    _anmelden(client, teilnahme)
    return teilnahme


@pytest.fixture
def diagnose(monkeypatch):
    """Die Diagnose haelt jeden Versuch fuer falsch und will Stufe 2."""
    gesehen = []

    def _diagnose(stufe, aufgabentext, beitrag, verlauf="", obergrenze=None, **mehr):
        gesehen.append(beitrag)
        return pruefung.Diagnose(2, "falsche Rechenart", pruefung.FALSCH,
                                 "addiert statt multipliziert", pruefung.GRUEN, "",
                                 levels.LAGE_ANSATZ_FALSCH, levels.ABSICHT_BESTAETIGUNG,
                                 levels.FORM_DIREKT)
    monkeypatch.setattr(views.pruefung, "diagnose", _diagnose)
    return gesehen


def _versuch(client, text):
    return client.post(reverse("tutoring:antwort_geben"), {"antwort": text},
                       HTTP_X_ANTWORT="json", secure=True)


def _strom(client, url):
    antwort = client.post(url, {}, secure=True)
    return b"".join(antwort).decode()


def test_ein_fremder_versuch_zaehlt_nicht_und_bekommt_den_festen_satz(client, schuelerin, diagnose, monkeypatch):
    aufgabe = Task.objects.create(participation=schuelerin, text=AUFGABE)
    _pfoertner(monkeypatch, "nein")

    antwort = _versuch(client, PEKING_DE)

    assert antwort.json() == {"ok": True, "ergebnis": "offen", "fertig": False, "fachgrenze": True}
    assert diagnose == [PEKING_DE], "die Diagnose lief mit, ihr Urteil zaehlt nur fuer das Protokoll"
    auftakt = aufgabe.hints.get()
    assert auftakt.response == PEKING_DE
    assert auftakt.response_flag == pruefung.GELB
    assert auftakt.response_flag_reason == fachgrenze.GRUND
    assert auftakt.result == Hint.ERGEBNIS_OFFEN and auftakt.error == ""
    assert auftakt.next_level == levels.ERST_FRAGEN and auftakt.goal_note == fachgrenze.GRUND
    assert auftakt.lage == levels.LAGE_ANSATZ_FALSCH, "die Diagnose bleibt im Protokoll"
    assert aufgabe.naechster_zug() == Zug(levels.ART_NACHFRAGE, 0)
    daten = views._aufgabe_holen.__wrapped__(aufgabe.pk, schuelerin.pk)
    assert daten["fachgrenze"] is True
    assert Interaction.objects.filter(outcome="pfoertner:nein").count() == 1

    # Der naechste Zug: der feste Satz, kein Modell.
    async def _nie(*args, **kwargs):
        raise AssertionError("Kein Modell erwartet.")
    monkeypatch.setattr(views, "_geprueft_erzeugen", _nie)
    strom = _strom(client, reverse("tutoring:hilfe", args=[aufgabe.pk]))
    assert "Heute geht es hier aber um Mathematik" in strom
    assert '"art": "nachfrage"' in strom and '"wartet": true' in strom
    nachfrage = aufgabe.hints.order_by("-created_at", "-pk").first()
    assert nachfrage.art == levels.ART_NACHFRAGE
    assert nachfrage.text.startswith("Das ist eine andere Frage, und keine schlechte.")
    assert nachfrage.text.endswith("Wollen wir bei der Aufgabe weitermachen?")
    assert aufgabe.offene_hilfe == nachfrage, "das Kind antwortet darauf wie auf jede Nachfrage"
    assert Interaction.objects.filter(outcome="fachgrenze").count() == 1
    daten = views._aufgabe_holen.__wrapped__(aufgabe.pk, schuelerin.pk)
    assert daten["fachgrenze"] is False, "der Satz steht, der Marker ist verbraucht"


def test_der_rueckweg_ist_die_letzte_frage_des_tutors(client, schuelerin, diagnose, monkeypatch):
    aufgabe = Task.objects.create(participation=schuelerin, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Lies die Aufgabe noch einmal. Was ist gegeben?")
    _pfoertner(monkeypatch, "nein")

    _versuch(client, PEKING_DE)
    strom = _strom(client, reverse("tutoring:hilfe", args=[aufgabe.pk]))

    assert "Zurück zu unserer Frage: Was ist gegeben?" in strom


def test_eine_rechnung_braucht_keinen_pfoertner(client, schuelerin, diagnose, monkeypatch):
    aufgabe = Task.objects.create(participation=schuelerin, text=AUFGABE)
    anfrage = _pfoertner(monkeypatch, "nein")

    antwort = _versuch(client, "6 + 8 = 14")

    assert antwort.json() == {"ok": True, "ergebnis": "falsch", "fertig": False}
    assert anfrage.aufrufe == [], "Zahlen und Rechenzeichen gehoeren immer zur Stunde"
    assert aufgabe.naechster_zug() == Zug(levels.ART_HILFE, 2)


def test_ein_ja_oder_ein_ausfall_aendert_am_versuch_nichts(client, schuelerin, diagnose, monkeypatch):
    aufgabe = Task.objects.create(participation=schuelerin, text=AUFGABE)
    _pfoertner(monkeypatch, "ja", "Versuch zur Aufgabe")
    assert _versuch(client, "Ich würde die Packungen zusammenzählen").json()["ergebnis"] == "falsch"
    assert aufgabe.hints.get().goal_note == "falsche Rechenart"

    _pfoertner(monkeypatch, ConnectionError("weg"))
    daten = _versuch(client, "Vielleicht doch mal nehmen?").json()
    assert daten["ergebnis"] == "falsch" and "fachgrenze" not in daten
    assert Interaction.objects.filter(outcome="pfoertner:unklar").count() == 1
