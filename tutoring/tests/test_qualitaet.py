"""Pruefungen der Qualitaetssicherung.

Aus Sicht der Lehrperson ist das eine zweite, staerkere Einschaetzung bei
schwierigen Aufgaben. Technisch ist es der Weg aus Abschnitt 3a: Der Spark
anonymisiert, ein Frontier-Modell loest, die Platzhalter werden lokal wieder
eingesetzt.

Die wichtigste Pruefung hier ist die letzte: Die gepruefte Loesung darf beim
Kind nicht ankommen. Sie steht im Systemprompt, und ein Systemprompt ist eine
Bitte. Die Grenze bleibt die Ausgangspruefung.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import ausgabepruefung, cloud, levels, shield
from tutoring.models import LearningSession, Participation, Task

pytestmark = pytest.mark.django_db


AUFGABE = "In einer Schachtel sind 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?"
LOESUNG = "WEG: Sechs Packungen zu je acht Stiften.\nERGEBNIS: 48 Stifte"


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


# --- Der Schalter ---------------------------------------------------------

def test_die_grundeinstellung_ist_aus(lehrperson):
    """Ohne ausdrueckliche Freigabe verlaesst nichts die Hochschule."""
    sitzung = LearningSession.objects.create(title="Probe", teacher=lehrperson)

    assert sitzung.cloud_enabled is False


def test_ohne_zugang_bleibt_der_weg_zu(settings):
    settings.CLOUD_ENABLED = False

    assert cloud.moeglich() is False
    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_loesen(AUFGABE)
    assert fehler.value.art == "nicht_eingerichtet"


# --- Der Shield vor dem Weg nach draussen --------------------------------

def test_eine_svnr_sperrt_den_weg(settings, monkeypatch):
    """Sie wird nicht maskiert, sie blockiert. So steht es in der Vorlage."""
    settings.CLOUD_ENABLED = True
    # Ohne diese Zeile ging der Test an den echten Spark (Umformulierung) und
    # war gruen, solange der Tunnel stand; in der oeffentlichen Kopie fiel das auf.
    monkeypatch.setattr(shield, "neu_formulieren", lambda text: text)
    monkeypatch.setattr(shield, "namensfunde", lambda text: [])

    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_loesen("Anna hat die Nummer 1234 010115 und 6 Packungen.")

    assert fehler.value.art == "blockierender_fund"


def test_ein_ausfall_der_namenserkennung_sperrt_den_weg(settings, monkeypatch):
    """Eine Maskierung, deren Erkennung nicht gelaufen ist, ist keine."""
    settings.CLOUD_ENABLED = True

    def kaputt(text):
        raise RuntimeError("Spark weg")

    monkeypatch.setattr(shield, "namensfunde", kaputt)

    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_loesen(AUFGABE)

    assert fehler.value.art == "shield_aus"


def test_der_name_geht_nicht_hinaus(settings, monkeypatch):
    """Was hinausgeht, ist maskiert; was zurueckkommt, ist wieder Klartext."""
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "probe"
    monkeypatch.setattr(shield, "namensfunde",
                        lambda text: [(shield.TYP_PERSON, "Anna Berger")])

    hinausgegangen = {}

    class Antwort:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            # Das Modell antwortet mit dem Platzhalter, wie es soll.
            marke = hinausgegangen["text"]
            token = marke.split()[0] if marke.startswith("[") else "[PERS_?]"
            return {
                "choices": [{"message": {"content": f"{token} rechnet 48."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "probe",
            }

    class Klient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        @staticmethod
        def post(url, json=None, headers=None):
            hinausgegangen["text"] = json["messages"][1]["content"]
            hinausgegangen["kopf"] = headers or {}
            return Antwort()

    monkeypatch.setattr(cloud.httpx, "Client", lambda **k: Klient())

    ergebnis = cloud.geprueft_loesen("Anna Berger hat 6 Packungen mit je 8 Stiften.")

    assert "Anna Berger" not in hinausgegangen["text"], "Der Name ist hinausgegangen"
    assert "[PERS_" in hinausgegangen["text"]
    assert "Anna Berger" in ergebnis["loesung"], "Der Name kam nicht zurück"
    assert ergebnis["entitaeten"] == {shield.TYP_PERSON: 1}


# --- Die gepruefte Loesung im Prompt -------------------------------------

def test_die_gepruefte_loesung_steht_im_systemprompt():
    prompt = levels.system_prompt(levels.RUECKMELDUNG, "6-10", LOESUNG)

    assert "48 Stifte" in prompt
    assert "NICHT wiedergeben" in prompt


def test_ohne_qualitaetssicherung_aendert_sich_der_prompt_nicht():
    ohne = levels.system_prompt(levels.RUECKMELDUNG, "6-10")
    mit_leer = levels.system_prompt(levels.RUECKMELDUNG, "6-10", "")

    assert ohne == mit_leer


def test_eine_geschweifte_klammer_in_der_loesung_bringt_nichts_zum_stehen():
    """Die Loesung wird eingesetzt, nicht formatiert."""
    prompt = levels.system_prompt(levels.RUECKMELDUNG, "6-10", "ERGEBNIS: {48}")

    assert "{48}" in prompt


# --- Und die Pruefung, um die es geht ------------------------------------

@pytest.mark.parametrize("stufe", [1, 2, 3, 4])
def test_die_gepruefte_loesung_kaeme_beim_kind_nicht_durch(stufe):
    """Der Systemprompt kennt sie jetzt. Das ist genau der gefaehrliche Teil.

    Ein Modell, das die Loesung kennt, plaudert sie irgendwann aus. Die
    Grenze ist deshalb nicht der Prompt, sondern die Ausgangspruefung: Eine
    Zahl, die weder in der Aufgabe noch beim Kind steht, kommt nicht durch.
    """
    verstoss = ausgabepruefung.verstoesse(
        "Es sind 48 Stifte.", stufe, 5, [AUFGABE]
    )

    assert "neue Zahl" in verstoss


def test_bei_nur_tipps_gilt_das_auch_fuer_die_rueckfrage():
    """Der Weg, auf dem es im Betrieb durchgerutscht ist."""
    verstoss = ausgabepruefung.verstoesse(
        "Die Antwort ist 48.", levels.NUR_TIPPS, levels.NUR_TIPPS, [AUFGABE]
    )

    assert verstoss


def test_die_loesung_wird_je_aufgabe_nur_einmal_geholt(lehrperson):
    """Sie kostet einen Aufruf nach draussen und aendert sich nicht."""
    sitzung = LearningSession.objects.create(
        title="Probe", teacher=lehrperson, cloud_enabled=True
    )
    teilnahme = Participation.objects.create(learning_session=sitzung, animal="fuchs")
    aufgabe = Task.objects.create(participation=teilnahme, text=AUFGABE)

    assert aufgabe.checked_solution == ""
    aufgabe.checked_solution = LOESUNG
    aufgabe.save(update_fields=["checked_solution"])
    aufgabe.refresh_from_db()

    assert aufgabe.checked_solution == LOESUNG


# --- Der Budgetwaechter ---------------------------------------------------

def _verbrauch(**werte):
    leer = {"aufrufe_sitzung": 0, "aufrufe_tag": 0,
            "euro_sitzung": 0.0, "euro_tag": 0.0}
    leer.update(werte)
    return leer


def test_ohne_verbrauch_ist_das_budget_offen():
    assert cloud.budget_pruefen(_verbrauch()) is None


def test_die_aufrufe_je_sitzung_sind_begrenzt(settings):
    settings.CLOUD_AUFRUFE_JE_SITZUNG = 3

    grund = cloud.budget_pruefen(_verbrauch(aufrufe_sitzung=3))

    assert grund and "Sitzung" in grund


def test_die_aufrufe_je_tag_sind_begrenzt(settings):
    settings.CLOUD_AUFRUFE_JE_TAG = 5

    assert cloud.budget_pruefen(_verbrauch(aufrufe_tag=5))


def test_der_waechter_greift_auch_ohne_hinterlegte_preise(settings):
    """Der eigentliche Grund fuer die Zaehlung der Aufrufe.

    Die Euro-Grenze ist nur so gut wie die Preistabelle, und die war fuer
    das eingestellte Modell gar nicht hinterlegt. Ein Waechter, der nur bei
    bekannten Preisen greift, ist bei unbekannten Preisen keiner.
    """
    settings.CLOUD_PREISE = {}
    settings.CLOUD_AUFRUFE_JE_SITZUNG = 2

    assert cloud.kosten_micro("gpt-5-2025-08-07", 1000, 1000) == 0
    assert cloud.budget_pruefen(_verbrauch(aufrufe_sitzung=2))


def test_der_preis_wird_auch_ueber_den_praefix_gefunden(settings):
    """Die Antwort nennt "gpt-5-2025-08-07", die Tabelle kennt "gpt-5"."""
    settings.CLOUD_PREISE = {"gpt-5": {"ein": 1, "aus": 10}}
    settings.CLOUD_MODEL = "gpt-5"

    assert cloud.kosten_micro("gpt-5-2025-08-07", 100, 10) == 200


def test_ein_erschoepftes_budget_sperrt_den_aufruf(settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_AUFRUFE_JE_SITZUNG = 1

    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_loesen(AUFGABE, _verbrauch(aufrufe_sitzung=1))

    assert fehler.value.art == "budget"


# --- Der Austausch im Gespraechsverlauf ----------------------------------

def _aufgabe_mit_austausch(lehrperson, **zusatz):
    sitzung = LearningSession.objects.create(
        title="Probe", teacher=lehrperson, cloud_enabled=True
    )
    teilnahme = Participation.objects.create(
        learning_session=sitzung, animal="fuchs", token="qs1", log_key="qsl1"
    )
    werte = {
        "checked_solution": LOESUNG,
        "checked_model": "gpt-5-2025-08-07",
        "checked_sent": "[PERS_a3f2] hat 6 Packungen mit je 8 Stiften.",
        "checked_received": "ERGEBNIS: 48 Stifte",
        "checked_entities": {"PERS": 1},
        "checked_tokens_in": 144,
        "checked_tokens_out": 176,
        "checked_ms": 3072,
        "checked_cost_micro": 1940,
    }
    werte.update(zusatz)
    from django.utils import timezone
    if "checked_blocked" not in zusatz:
        werte["checked_at"] = timezone.now()
    return sitzung, teilnahme, Task.objects.create(
        participation=teilnahme, text=AUFGABE, **werte
    )


def test_der_austausch_steht_im_verlauf(client, lehrperson):
    """Anlass: Er stand nur im Forschungsprotokoll.

    Und das hat absichtlich keine Bruecke zur Person. Fuer die Auswertung
    eines einzelnen Lernwegs war der Austausch damit unsichtbar: Man sah die
    Hilfen, aber nicht, worauf sie sich stuetzten.
    """
    sitzung, teilnahme, _ = _aufgabe_mit_austausch(lehrperson)
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]),
        secure=True,
    ).content.decode()

    assert "[PERS_a3f2]" in seite, "Was hinausging, fehlt"
    assert "ERGEBNIS: 48 Stifte" in seite, "Was zurueckkam, fehlt"
    assert "gpt-5-2025-08-07" in seite
    assert "144" in seite and "176" in seite, "Die Token fehlen"


def test_der_austausch_ist_eingeklappt(client, lehrperson):
    """Aufgeschlagen waere er laenger als das Gespraech selbst."""
    sitzung, teilnahme, _ = _aufgabe_mit_austausch(lehrperson)
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]),
        secure=True,
    ).content.decode()

    assert "<details class=\"qsblock" in seite
    assert "qsblock\" open" not in seite


def test_ein_gesperrter_weg_steht_auch_da(client, lehrperson):
    """Ein leeres Feld liesse offen, ob die Sicherung aus war oder scheiterte."""
    sitzung, teilnahme, _ = _aufgabe_mit_austausch(
        lehrperson, checked_blocked="Im Text steht eine Sozialversicherungsnummer.",
        checked_solution="", checked_sent="", checked_received="",
    )
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]),
        secure=True,
    ).content.decode()

    assert "nicht gelaufen" in seite
    assert "Sozialversicherungsnummer" in seite
    assert "nichts hinausgegangen" in seite


def test_ohne_qualitaetssicherung_steht_dort_nichts(client, lehrperson):
    """Der Verlauf einer gewoehnlichen Sitzung bleibt unveraendert."""
    sitzung = LearningSession.objects.create(title="Ohne", teacher=lehrperson)
    teilnahme = Participation.objects.create(
        learning_session=sitzung, animal="hase", token="qs2", log_key="qsl2"
    )
    Task.objects.create(participation=teilnahme, text=AUFGABE)
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]),
        secure=True,
    ).content.decode()

    assert "qsblock" not in seite


def test_die_ersetzten_angaben_werden_gezaehlt_nicht_genannt(lehrperson):
    """Im Verlauf steht, WAS ersetzt wurde, nicht der Klartext dazu."""
    _, _, aufgabe = _aufgabe_mit_austausch(lehrperson)

    assert aufgabe.checked_ersetzt == "1× Name"


# --- Umformulieren statt bearbeiten --------------------------------------

def test_die_zahlenfolge_wird_streng_verglichen():
    """Ein Modell, das beim Umformulieren aus 6 Packungen 8 macht, liefert
    eine falsche Loesung - und die stuende danach im Systemprompt."""
    assert shield.zahlenfolge("6 Packungen mit je 8 Stiften") == ["6", "8"]
    assert shield.zahlenfolge("8 Packungen mit je 6 Stiften") == ["8", "6"]
    assert shield.zahlenfolge("6 Packungen") != shield.zahlenfolge("6 Packungen mit 8")


def test_eine_veraenderte_zahlenfolge_wird_verworfen(settings, monkeypatch):
    """Lieber der alte Weg als eine falsche Aufgabe."""
    class Antwort:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"choices": [{"message": {
                "content": "Ein Kind kauft 8 Packungen mit je 6 Stiften."
            }}]}

    class Klient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        @staticmethod
        def post(url, json=None):
            return Antwort()

    monkeypatch.setattr(shield.httpx, "Client", lambda **k: Klient())

    with pytest.raises(shield.UmschreibenGescheitert):
        shield.neu_formulieren("Ein Kind kauft 6 Packungen mit je 8 Stiften.")


def test_eine_leere_umformulierung_wird_verworfen(monkeypatch):
    class Antwort:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "   "}}]}

    class Klient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        @staticmethod
        def post(url, json=None):
            return Antwort()

    monkeypatch.setattr(shield.httpx, "Client", lambda **k: Klient())

    with pytest.raises(shield.UmschreibenGescheitert):
        shield.neu_formulieren("Ein Kind kauft 6 Packungen.")


def test_der_umschreibprompt_verbietet_zahlenaenderungen():
    assert "ÄNDERE KEINE ZAHL" in shield.UMSCHREIB_PROMPT
