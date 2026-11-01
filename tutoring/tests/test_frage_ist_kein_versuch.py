"""Eine Frage ist kein Versuch, und "ok" ist keiner.

Anlass aus dem Betrieb, Sitzung 927013 vom 11.10.2026: Vier Beitraege in zwei
Minuten, davon zwei Fragen und eine Absichtserklaerung - und vier Stufen.
"Es kann nicht jede Frage einfach zur naechsten Stufe schalten."
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import levels, pruefung, views
from tutoring.models import Hint, LearningSession, Participation, Question, Task
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

AUFGABE = ("Lena kauft Rucksack 48,90, Flasche 12,50 und Pennal 9,80. "
           "Wie viel zahlt sie? Sie hat 100 Euro.")


@pytest.fixture
def stunde(db):
    lehrperson = get_user_model().objects.create_user(username="l", password="x")
    return LearningSession.objects.create(
        title="Mathe 4a", teacher=lehrperson, max_level=levels.LOESUNG,
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


@pytest.fixture
def nach_stufe_eins(kind):
    """Eine Aufgabe, zu der die erste Hilfe gegeben wurde und auf einen
    Versuch wartet."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Worum geht es hier?")
    return aufgabe


@pytest.fixture
def ohne_modell(monkeypatch):
    """Einstufung und Diagnose ohne Spark: gruen, und eine Stufe weiter."""
    monkeypatch.setattr(views.pruefung, "einstufen", lambda text: ("gruen", ""))
    aufrufe = []

    def diagnose(stufe, aufgabentext, beitrag, verlauf="", obergrenze=None, **mehr):
        aufrufe.append(beitrag)
        return pruefung.Diagnose(stufe + 1, "Ansatz da.")
    monkeypatch.setattr(views.pruefung, "diagnose", diagnose)
    return aufrufe


def _versuch(client, text):
    return client.post(
        reverse("tutoring:antwort_geben"), {"antwort": text},
        HTTP_X_ANTWORT="json", secure=True,
    )


def _frage(client, text):
    """Der zweite Knopf: Das Kind sagt selbst, dass es fragt."""
    return client.post(
        reverse("tutoring:antwort_geben"), {"antwort": text, "absicht": "frage"},
        HTTP_X_ANTWORT="json", secure=True,
    )


# --- Die Ansicht ----------------------------------------------------------

def test_eine_frage_wird_zur_rueckfrage_und_rueckt_nicht_vor(client, nach_stufe_eins, ohne_modell):
    antwort = _frage(client, "Muss ich das Buch auch dazuzählen?")

    daten = antwort.json()
    assert daten["ok"] is True
    assert "frage" in daten, "die Ansicht meldet eine Rueckfrage, keinen Versuch"

    frage = Question.objects.get(pk=daten["frage"])
    assert frage.task == nach_stufe_eins
    hilfe = nach_stufe_eins.hints.get()
    assert hilfe.response == "", "die Hilfe wartet weiter auf einen Versuch"
    assert ohne_modell == [], "die Diagnose wurde gar nicht gefragt"
    nach_stufe_eins.refresh_from_db()
    assert nach_stufe_eins.current_level == 1


def test_thomas_zweite_frage_rueckt_auch_nicht_vor(client, nach_stufe_eins, ohne_modell):
    """Der Beitrag, der im Betrieb als 'Umgehungsversuch' galt."""
    antwort = _frage(client, "Aber oben heißt es ja, sie will alles kaufen. "
                             "Woher sollte ich wissen, dass sie das Buch nicht dazu nimmt?")

    assert "frage" in antwort.json()
    assert nach_stufe_eins.hints.get().response == ""


def test_ein_versuch_wird_weiterhin_als_versuch_behandelt(client, nach_stufe_eins, ohne_modell):
    antwort = _versuch(client, "Ich zähle die drei Dinge zusammen: 48,90 + 12,50 + 9,80.")

    daten = antwort.json()
    assert daten["ok"] is True
    assert "frage" not in daten
    hilfe = nach_stufe_eins.hints.get()
    assert hilfe.response.startswith("Ich zähle")
    assert hilfe.goal_reached is True
    assert ohne_modell == ["Ich zähle die drei Dinge zusammen: 48,90 + 12,50 + 9,80."]


def test_ein_versuch_mit_fragezeichen_bleibt_ein_versuch(client, nach_stufe_eins, ohne_modell):
    """Benchmark 19.10.2026, Befund 1: 11 von 18 Beitraegen mit Fragezeichen
    waren Versuche mit angehaengter Frage. Die Anwendung raet nicht mehr;
    was das Kind als Versuch abschickt, wird als Versuch beurteilt."""
    antwort = _versuch(client, "Die Antwort auf die Frage ist 71,20. Ist das richtig?")

    daten = antwort.json()
    assert "frage" not in daten
    assert ohne_modell == ["Die Antwort auf die Frage ist 71,20. Ist das richtig?"]
    assert Question.objects.count() == 0


def test_ohne_absicht_gilt_der_beitrag_als_versuch(client, nach_stufe_eins, ohne_modell):
    """Aeltere Seiten kennen den zweiten Knopf nicht."""
    antwort = client.post(
        reverse("tutoring:antwort_geben"), {"antwort": "Wie viel kostet alles zusammen?"},
        HTTP_X_ANTWORT="json", secure=True,
    )
    assert "frage" not in antwort.json()
    assert len(ohne_modell) == 1


def test_eine_rueckfrage_geht_auf_jeder_stufe(client, nach_stufe_eins, monkeypatch):
    """Frueher: 'Dafuer ist es noch zu frueh.' Jetzt ist eine Frage eine Frage."""
    monkeypatch.setattr(views.pruefung, "einstufen", lambda text: ("gruen", ""))

    antwort = client.post(
        reverse("tutoring:nachfrage_stellen"), {"frage": "Was heißt Pennal?"},
        secure=True,
    )

    assert antwort.status_code == 200
    assert antwort.json()["ok"] is True
    assert Question.objects.filter(task=nach_stufe_eins, text="Was heißt Pennal?").exists()


def test_die_antwort_auf_eine_frage_ist_an_die_laufende_stufe_gebunden(nach_stufe_eins):
    """Nicht an die Obergrenze der Sitzung: Stufe 1 bleibt Stufe 1."""
    frage = Question.objects.create(task=nach_stufe_eins, text="Muss ich das Buch dazuzählen?")

    daten = views._nachfrage_holen.__wrapped__(frage.pk, nach_stufe_eins.participation_id)

    _, _, _, _, grenze, unterwegs, rueckfrage = daten
    assert grenze == 1
    assert unterwegs is True
    # Der Arbeitsauftrag ist die Frage, die die Hilfe wirklich gestellt hat,
    # nicht mehr der feste Satz der Stufe (Zech, S. 289: keine Kettenfragen).
    assert rueckfrage == "Worum geht es hier?"


def test_nach_der_letzten_stufe_gilt_die_obergrenze(nach_stufe_eins):
    nach_stufe_eins.current_level = levels.LOESUNG
    nach_stufe_eins.save(update_fields=["current_level"])
    hilfe = nach_stufe_eins.hints.get()
    hilfe.response = "48,90 + 12,50 + 9,80 = 71,20"
    hilfe.save(update_fields=["response"])
    frage = Question.objects.create(task=nach_stufe_eins, text="Warum 71,20?")

    daten = views._nachfrage_holen.__wrapped__(frage.pk, nach_stufe_eins.participation_id)

    _, _, _, _, grenze, unterwegs, _ = daten
    assert grenze == levels.LOESUNG
    assert unterwegs is False


# --- Der Pruefer ----------------------------------------------------------

@pytest.mark.parametrize("beitrag", [
    "Muss ich das Buch auch dazuzählen?",
    "Wie viel kostet alles zusammen?",
    "ok",
    "Ja.",
    "ich weiß nicht",
    "Keine Ahnung!",
    "hm",
])
def test_frage_und_leere_beitraege_erreichen_kein_ziel_ohne_modell(beitrag, monkeypatch):
    def nie(*a, **k):
        raise AssertionError("das Modell darf hier nicht gefragt werden")
    monkeypatch.setattr(pruefung.httpx, "Client", nie)

    erreicht, notiz = pruefung.bereit_fuer_naechste(1, AUFGABE, beitrag)

    assert erreicht is False
    assert notiz


@pytest.mark.parametrize("beitrag", [
    "Ich zähle alles zusammen.",
    "48,90 + 12,50 + 9,80",
    "Sie kauft nur die drei Dinge, also addiere ich die.",
])
def test_ein_echter_beitrag_geht_zum_modell(beitrag, monkeypatch):
    gefragt = []

    class Antwort:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '{"erreicht": true, "grund": "x"}'}}]}

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **k):
            gefragt.append(k["json"]["messages"][1]["content"])
            return Antwort()
    monkeypatch.setattr(pruefung.httpx, "Client", Client)

    erreicht, _ = pruefung.bereit_fuer_naechste(2, AUFGABE, beitrag)

    assert erreicht is True
    assert len(gefragt) == 1


def test_der_bereitschaftsprompt_nennt_die_ausnahmen():
    prompt = levels.bereitschaft_prompt(2)
    assert "nur eine Frage" in prompt
    assert "NICHT erreicht" in prompt
    assert "Im Zweifel" in prompt


def test_der_rueckfrageprompt_unterwegs_nennt_stufe_und_arbeitsauftrag():
    prompt = levels.nachfrage_prompt(1, unterwegs=True, rueckfrage=levels.rueckfrage(1))
    assert "steht auf Stufe 1" in prompt
    assert levels.rueckfrage(1) in prompt
    assert "VERBOTEN" in prompt, "die Grenze der Stufe gilt auch fuer die Antwort"


def test_die_orange_kategorie_klingt_nicht_wie_ein_urteil():
    assert "Umgehungsversuch" not in pruefung.BESCHREIBUNG[pruefung.ORANGE]
    assert "bitte ansehen" in pruefung.BESCHREIBUNG[pruefung.ORANGE]
    assert "Rückfrage ZUR AUFGABE" in pruefung.SYSTEM_PROMPT
