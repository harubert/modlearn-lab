"""Die Lehrpersonenseite nach dem Benchmark (19.10.2026).

Bildschirm 1: eine Karte mit drei Fragen und einem Knopf. Drei Beruehrungen
(Fach, Schulstufe, Start), und zwischen Fachwahl und Start ist nichts anderes
Pflicht. Bildschirm 2: Code, Titel mit Stift, die Entscheidungen als Marken.
Hier steht, was die Seite zusagt - geprueft am gerenderten HTML.
"""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from tutoring import faecher, levels, stundenform
from tutoring.models import LearningSession

pytestmark = pytest.mark.django_db

WURZEL = Path(__file__).resolve().parents[2]


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


def _mathe_formular(client, lehrperson):
    client.force_login(lehrperson)
    return client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "mathematik"}, secure=True
    ).content.decode()


def _anlegen(client, lehrperson, **felder):
    client.force_login(lehrperson)
    daten = {"fach": "mathematik", "schulstufe": "sek2"}
    daten.update(felder)
    return client.post(reverse("tutoring:lehrperson_uebersicht"), daten, secure=True)


# --- Bildschirm 1: die drei Fragen ------------------------------------------

def test_das_mathe_formular_stellt_drei_fragen_und_sonst_nichts(client, lehrperson):
    seite = _mathe_formular(client, lehrperson)

    assert "Für wen ist die Stunde?" in seite
    assert "Was bekommen die Kinder?" in seite
    assert "Worum geht es heute?" in seite
    assert seite.count('name="schulstufe"') == 3, "drei Karten: Volksschule, Mittelstufe, Oberstufe"
    for name in ("Volksschule", "Mittelstufe", "Oberstufe"):
        assert name in seite
    assert "5. bis 8." in seite and "bis Matura" in seite
    # Der graue Satz unter jeder Karte, alle drei, keiner wechselt.
    assert "Rechenarten statt Fachwörter" in seite
    assert "Fachwörter werden erklärt" in seite
    assert "Grundkompetenz, nicht die Rechenart" in seite
    # Lernen und Ueben, Lernen vorgewaehlt; "bei Bedarf" gibt es nicht mehr.
    assert seite.count('name="umfang"') == 2
    assert re.search(r'name="umfang" value="auf_bitte"\s+checked', seite), "Lernen ist vorgewaehlt"
    assert "bei_bedarf" not in seite
    assert "Fünf Stufen bis zur Lösung" in seite and "Nur Tipps, Stufe 1 bis 3" in seite
    assert 'placeholder="Sachaufgaben mit Geld"' in seite
    assert "Hilft der Anwendung, den Fehler eines Kindes zu erkennen." in seite
    assert "Stunde starten" in seite
    # Kein Altersklassen-Block, aber die Erklaerung der Stufen, eingeklappt.
    assert 'name="age_group"' not in seite
    assert '<details class="stufenerklaerung">' in seite


def test_die_schulstufe_hat_keine_vorauswahl(client, lehrperson):
    seite = _mathe_formular(client, lehrperson)
    for schluessel in ("vs", "sek1", "sek2"):
        assert not re.search(
            r'name="schulstufe" value="%s" required\s+checked' % schluessel, seite
        ), "keine Vorauswahl: die Lehrperson entscheidet"


def test_zwischen_fachwahl_und_start_ist_nur_die_schulstufe_pflicht(client, lehrperson):
    """Drei Beruehrungen: Fach, Schulstufe, Start. Alles andere hat eine Vorgabe."""
    seite = _mathe_formular(client, lehrperson)
    formular = seite[seite.index('id="stundenform"'):seite.index("</form>", seite.index('id="stundenform"'))]

    pflicht = re.findall(r'<input[^>]*\srequired[^>]*>', formular)
    assert len(pflicht) == 3, pflicht
    assert all('name="schulstufe"' in p for p in pflicht), "nur die Schulstufe ist Pflicht"
    assert "<select" not in formular[:formular.index("weitere-einstellungen")], \
        "zwischen Fachwahl und Start kein Auswahlfeld"


def test_die_weiteren_einstellungen_sind_eingeklappt_und_vollstaendig(client, lehrperson):
    seite = _mathe_formular(client, lehrperson)
    anfang = seite.index('<details class="weitere-einstellungen"')
    block = seite[anfang:seite.index("</details>", anfang)]

    assert "open" not in block[:block.index(">")], "eingeklappt"
    assert "Weitere Einstellungen" in block
    assert 'name="title"' in block
    # Die Protokollstufe ist seit 1.11.2026 fest am Server; kein Auswahlfeld.
    assert 'name="research_level"' not in block
    assert "fest eingestellt" in block and "Forschung vollständig" in block
    assert 'name="idle_timeout"' in block
    # Die Qualitaetssicherung bleibt ein bewusster Haken je Stunde, auch wenn
    # kein Zugang hinterlegt ist, steht sie als Block da.
    assert "Qualitätssicherung" in block
    # Und der Titel ist kein Pflichtfeld.
    assert "required" not in block[block.index('name="title"') - 200:block.index('name="title"') + 200]


def test_in_jedem_fach_sind_die_weiteren_einstellungen_eingeklappt(client, lehrperson):
    client.force_login(lehrperson)
    for fach in ("deutsch", "englisch", "musik"):
        seite = client.get(reverse("tutoring:lehrperson_uebersicht"), {"fach": fach},
                           secure=True).content.decode()
        assert '<details class="weitere-einstellungen"' in seite, fach
        assert 'name="schulstufe"' not in seite, f"{fach} hat keine Schulstufe"
        assert 'name="age_group"' in seite, f"{fach} behaelt die Altersklasse"
        assert "Stunde starten" in seite


def test_ohne_schulstufe_bleibt_die_frage_stehen_und_nichts_wird_angelegt(client, lehrperson):
    """Der Server prueft, nicht nur der Browser. Der Fehler steht an der
    Frage, das Getippte bleibt, und der erste Knopf hat den Fokus."""
    vorher = LearningSession.objects.count()

    antwort = _anlegen(client, lehrperson, schulstufe="", task_hint="Brüche",
                       umfang="tipps")

    assert antwort.status_code == 200
    assert LearningSession.objects.count() == vorher
    seite = antwort.content.decode()
    assert 'id="schulstufe-fehler"' in seite
    assert "Bitte wähl, für wen die Stunde ist" in seite
    assert 'value="mathematik"' in seite, "das Fach bleibt gewaehlt"
    assert 'value="Brüche"' in seite, "das Thema bleibt stehen"
    assert re.search(r'name="umfang" value="tipps"\s+checked', seite), "die Wahl bleibt"
    assert "autofocus" in seite
    assert "meldung-fehler" not in seite, "kein Sprung an den Seitenanfang"


def test_eine_unbekannte_schulstufe_zaehlt_wie_keine(client, lehrperson):
    antwort = _anlegen(client, lehrperson, schulstufe="uni")
    assert antwort.status_code == 200
    assert not LearningSession.objects.exists()


def test_drei_beruehrungen_legen_eine_stunde_an(client, lehrperson):
    """Fach, Schulstufe, Start. Kein Titel, kein Thema, keine weitere Wahl."""
    antwort = _anlegen(client, lehrperson, schulstufe="sek1")

    assert antwort.status_code == 302
    sitzung = LearningSession.objects.get()
    assert sitzung.subject == "mathematik"
    assert sitzung.schulstufe == "sek1"
    assert sitzung.age_group == "10-14", "die Altersklasse folgt aus der Schulstufe"
    assert sitzung.max_level == levels.LOESUNG and sitzung.ask_before_solution is True, \
        "Lernen ist die Vorgabe"
    assert sitzung.title.startswith("Mathematik, "), sitzung.title
    assert antwort["Location"] == reverse("tutoring:lehrperson_sitzung", args=[sitzung.code])


@pytest.mark.parametrize("schulstufe, altersklasse", [
    ("vs", "6-10"), ("sek1", "10-14"), ("sek2", "14-19"),
])
def test_die_altersklasse_folgt_der_schulstufe(client, lehrperson, schulstufe, altersklasse):
    _anlegen(client, lehrperson, schulstufe=schulstufe, age_group="erwachsen")
    sitzung = LearningSession.objects.get()
    assert sitzung.schulstufe == schulstufe
    assert sitzung.age_group == altersklasse, "age_group aus dem Formular wird in Mathe nicht gelesen"


@pytest.mark.parametrize("altersklasse, schulstufe", [
    ("6-10", "vs"), ("10-14", "sek1"), ("14-19", "sek2"), ("erwachsen", "sek2"),
])
def test_die_anderen_faecher_leiten_die_schulstufe_aus_der_altersklasse_ab(
    client, lehrperson, altersklasse, schulstufe
):
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "deutsch", "age_group": altersklasse, "schulstufe": "vs"},
                secure=True)
    sitzung = LearningSession.objects.get()
    assert sitzung.age_group == altersklasse
    assert sitzung.schulstufe == schulstufe, "schulstufe aus dem Formular wird in Deutsch nicht gelesen"


def test_ueben_heisst_nur_tipps(client, lehrperson):
    _anlegen(client, lehrperson, umfang="tipps")
    sitzung = LearningSession.objects.get()
    assert sitzung.max_level == levels.NUR_TIPPS


def test_loesung_bei_bedarf_wird_in_mathe_nicht_angenommen(client, lehrperson):
    """Bastani et al.: die Loesung ohne Rueckfrage schadet. Ein nachgebautes
    Formular bekommt Lernen, nicht die Loesung ohne Frage."""
    _anlegen(client, lehrperson, umfang="bei_bedarf")
    sitzung = LearningSession.objects.get()
    assert sitzung.max_level == levels.LOESUNG
    assert sitzung.ask_before_solution is True


def test_der_titel_wird_vorbelegt_und_bleibt_wenn_getippt(client, lehrperson):
    _anlegen(client, lehrperson, title="")
    vorbelegt = LearningSession.objects.get()
    assert re.fullmatch(r"Mathematik, (Mo|Di|Mi|Do|Fr|Sa|So) \d{1,2}\. \d{1,2}\., \d{2}:\d{2}",
                        vorbelegt.title), vorbelegt.title

    _anlegen(client, lehrperson, title="4a, Brüche")
    assert LearningSession.objects.filter(title="4a, Brüche").exists()


def test_der_titelvorschlag_rechnet_in_wiener_ortszeit():
    um = datetime(2026, 10, 19, 8, 5, tzinfo=ZoneInfo("UTC"))  # 10:05 in Wien
    assert stundenform.titel_vorschlag("Mathematik", um) == "Mathematik, Mo 19. 10., 10:05"
    um = datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo("Europe/Vienna"))
    assert stundenform.titel_vorschlag("Deutsch", um) == "Deutsch, Do 5. 3., 14:30"
    assert stundenform.titel_vorschlag("", um).startswith("Sitzung, ")


def test_die_schulstufen_der_karten_sind_die_aus_levels():
    assert [s["schluessel"] for s in stundenform.SCHULSTUFEN] == [s for s, _ in levels.SCHULSTUFEN]
    for karte in stundenform.SCHULSTUFEN:
        assert levels.schulstufe_name(karte["schluessel"]).startswith(karte["name"])
    assert stundenform.schulstufe_kurz("sek2") == "Oberstufe"
    assert stundenform.schulstufe_kurz("uni") == ""


def test_lernen_und_ueben_sind_die_zwei_umfaenge_aus_levels():
    assert stundenform.umfang("auf_bitte")["obergrenze"] == levels.LOESUNG
    assert stundenform.umfang("tipps")["obergrenze"] == levels.NUR_TIPPS
    assert stundenform.umfang("bei_bedarf")["vorher_fragen"] is True
    assert stundenform.umfang("")["schluessel"] == stundenform.LERNEN
    assert faecher.braucht("mathematik", faecher.EINSTELLUNG_SCHULSTUFE)


# --- Die Marken ---------------------------------------------------------------

def test_die_karte_der_uebersicht_zeigt_schulstufe_umfang_und_thema(client, lehrperson):
    _anlegen(client, lehrperson, schulstufe="sek2", umfang="auf_bitte", task_hint="Ableitungen")
    _anlegen(client, lehrperson, fach="deutsch", age_group="10-14", task_hint="Wörtliche Rede")

    seite = client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True).content.decode()

    assert "Oberstufe" in seite and "Lernen" in seite
    assert "Thema: Ableitungen" in seite
    assert "14–19 Jahre" not in seite, "in Mathe steht die Schulstufe statt der Altersklasse"
    assert "10–14 Jahre" in seite, "Deutsch behaelt die Altersklasse"
    assert "Thema: Wörtliche Rede" in seite


def test_marken_in_worten(lehrperson):
    mathe = LearningSession.objects.create(
        title="M", teacher=lehrperson, subject="mathematik", schulstufe="sek1",
        max_level=levels.NUR_TIPPS, task_hint="Brüche",
    )
    assert stundenform.marken(mathe) == ["Mittelstufe", "Üben", "Thema: Brüche"]

    alt = LearningSession.objects.create(
        title="A", teacher=lehrperson, subject="", max_level=levels.LOESUNG,
        ask_before_solution=False, age_group="erwachsen",
    )
    assert stundenform.marken(alt) == ["Erwachsene", "Lösung bei Bedarf"]

    deutsch = LearningSession.objects.create(
        title="D", teacher=lehrperson, subject="deutsch", mode="trainer", age_group="6-10",
    )
    assert stundenform.marken(deutsch) == ["6–10 Jahre"]


# --- Bildschirm 2: Code, Titel mit Stift, Marken -------------------------------

def test_die_sitzungsseite_zeigt_code_titel_stift_und_marken(client, lehrperson):
    _anlegen(client, lehrperson, schulstufe="sek2", task_hint="Ableitungen", title="7b")
    sitzung = LearningSession.objects.get()

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]),
                       secure=True).content.decode()

    assert sitzung.code[:3] in seite and reverse("tutoring:qr_code", args=[sitzung.code]) in seite
    assert "<h1 class=\"sitzung-titel\">7b</h1>" in seite
    assert "Titel ändern" in seite
    assert reverse("tutoring:lehrperson_titel", args=[sitzung.code]) in seite
    kopf = seite[:seite.index('id="klasse-titel"')]
    assert "Oberstufe" in kopf and "Lernen" in kopf and "Thema: Ableitungen" in kopf
    assert "Die Klasse" in seite


def test_den_titel_aendert_nur_die_lehrperson_dieser_sitzung(client, lehrperson):
    _anlegen(client, lehrperson, title="Alt")
    sitzung = LearningSession.objects.get()
    adresse = reverse("tutoring:lehrperson_titel", args=[sitzung.code])

    antwort = client.post(adresse, {"title": "  Neu  "}, secure=True)
    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:lehrperson_sitzung", args=[sitzung.code])
    sitzung.refresh_from_db()
    assert sitzung.title == "Neu"

    client.post(adresse, {"title": ""}, secure=True)
    sitzung.refresh_from_db()
    assert sitzung.title == "Neu", "leer heisst: bleibt"

    assert client.get(adresse, secure=True).status_code == 405

    andere = Client()
    andere.force_login(get_user_model().objects.create_user(username="andere", password="x"))
    assert andere.post(adresse, {"title": "Fremd"}, secure=True).status_code == 404
    sitzung.refresh_from_db()
    assert sitzung.title == "Neu"


# --- Stil: keine Emojis, keine mehrzeiligen Kommentare ---------------------------

GEAENDERT = [
    "tutoring/templates/tutoring/lehrperson_uebersicht.html",
    "tutoring/templates/tutoring/lehrperson_sitzung.html",
    "tutoring/templates/tutoring/_klassenliste.html",
    "tutoring/templates/tutoring/_stufenpunkte.html",
    "tutoring/templates/tutoring/_verlauf.html",
    "tutoring/stundenform.py",
    "tutoring/klassenbild.py",
    "tutoring/faecher.py",
    "static/css/app.css",
]


def _emojis(text):
    return [z for z in text if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF]


@pytest.mark.parametrize("pfad", GEAENDERT)
def test_keine_emojis_und_keine_mehrzeiligen_kurzkommentare(pfad):
    text = (WURZEL / pfad).read_text(encoding="utf-8")
    assert not _emojis(text), pfad
    for zeile in text.splitlines():
        # Ein {# ... #} muss in derselben Zeile enden, sonst steht er auf der Seite.
        assert zeile.count("{#") == zeile.count("#}"), (pfad, zeile)


def test_die_gerenderten_seiten_sind_frei_von_emojis(client, lehrperson):
    _anlegen(client, lehrperson, schulstufe="vs", task_hint="Geld")
    sitzung = LearningSession.objects.get()
    for adresse in (
        reverse("tutoring:lehrperson_uebersicht") + "?fach=mathematik",
        reverse("tutoring:lehrperson_uebersicht"),
        reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]),
        reverse("tutoring:lehrperson_klassenliste", args=[sitzung.code]),
    ):
        seite = client.get(adresse, secure=True).content.decode()
        assert not _emojis(seite), adresse
        assert "{#" not in seite and "{%" not in seite, adresse


# --- Die feste Protokollstufe (1.11.2026) -------------------------------------

def test_die_protokollstufe_kommt_vom_server_nicht_vom_formular(client, lehrperson, settings):
    """Thomas (1.11.2026): Die Wahl verschwindet aus dem Formular; Stufe 3 gilt
    fest, umschaltbar in der Konfiguration. Ein mitgeschickter Wert zaehlt
    nicht, solange die Wahl nicht freigeschaltet ist."""
    from tutoring.models import LearningSession
    settings.PROTOKOLLSTUFE = 3
    settings.PROTOKOLLSTUFE_WAEHLBAR = False
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "mathematik", "schulstufe": "vs", "max_level": "5",
                 "research_level": "1"}, secure=True)
    assert LearningSession.objects.latest("pk").research_level == 3

    settings.PROTOKOLLSTUFE = 1
    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "mathematik", "schulstufe": "vs", "max_level": "5"}, secure=True)
    assert LearningSession.objects.latest("pk").research_level == 1
    seite = client.get(reverse("tutoring:lehrperson_uebersicht"), {"fach": "mathematik"},
                       secure=True).content.decode()
    assert "Betrieb: nur Metadaten" in seite and 'name="research_level"' not in seite


def test_mit_dem_schalter_kommt_die_wahl_zurueck(client, lehrperson, settings):
    from tutoring.models import LearningSession
    settings.PROTOKOLLSTUFE = 3
    settings.PROTOKOLLSTUFE_WAEHLBAR = True
    client.force_login(lehrperson)
    seite = client.get(reverse("tutoring:lehrperson_uebersicht"), {"fach": "mathematik"},
                       secure=True).content.decode()
    assert 'name="research_level"' in seite and "Was wird für die Forschung aufgezeichnet?" in seite
    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "mathematik", "schulstufe": "vs", "max_level": "5",
                 "research_level": "2"}, secure=True)
    assert LearningSession.objects.latest("pk").research_level == 2
