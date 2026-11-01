"""Die Protokollansicht der Lehrperson (Abschnitt 3b; Thomas, 31.10.2026).

Thomas: "Wenn es zum Frontiermodell weitergeht, moechte ich die Kommunikation
zwischen der lokalen KI und dem Frontiermodell auch einsehen koennen. Die
muss natuerlich auch auf dem Server gespeichert bleiben." Eine Zeile je
Anfrage, aufklappbar, mit Anweisung, Ausgehendem und Antwort; Filter und
Export; und sie bleibt, wenn die Sitzung beendet ist.
"""

import csv
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import cloud, views
from tutoring.models import (BETRIEB, FORSCHUNG_VOLL, Interaction,
                             LearningSession, Participation)

pytestmark = pytest.mark.django_db


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _stunde(lehrperson, **werte):
    vorgaben = {"title": "Brüche", "teacher": lehrperson, "subject": "mathematik",
                "research_level": FORSCHUNG_VOLL}
    vorgaben.update(werte)
    return LearningSession.objects.create(**vorgaben)


def _kind(stunde, tier="fuchs"):
    return Participation.objects.create(learning_session=stunde, animal=tier, token=f"t-{tier}")


def _zeilen(stunde, kind):
    """Drei Anfragen: eine am Spark, eine nach draussen, eine blockiert."""
    Interaction.aufzeichnen(
        sitzung=stunde, teilnahme=kind, weg=Interaction.LOKAL, modell="qwen",
        stufe_angefordert=2, stufe_gewaehrt=2, tokens_ein=100, tokens_aus=20,
        dauer_ms=800, text_ein="Die Aufgabe des Kindes lautet: Lena kauft 6 Packungen",
        text_aus="Worum geht es?", diagnose={"lage": "kein_ansatz", "absicht": "tipp"},
    )
    Interaction.aufzeichnen(
        sitzung=stunde, teilnahme=kind, weg=Interaction.CLOUD, modell="gpt-5",
        tokens_ein=300, tokens_aus=50, dauer_ms=4000, kosten_micro=1234,
        leak_check=Interaction.BESTANDEN, entitaeten={"PERS": 1},
        maskiert_ein="[PERS_a1b2] kauft 6 Packungen mit je 8 Stiften.",
        maskiert_aus="WEG: 6 · 8\nERGEBNIS: 48 Stifte",
        text_aus="Lena: 6 · 8 = 48 Stifte", anweisung=cloud.SYSTEM,
    )
    Interaction.aufzeichnen(
        sitzung=stunde, teilnahme=kind, weg=Interaction.CLOUD, modell="gpt-5",
        ergebnis="gesperrt", fehlerart="blockierender_fund",
        leak_check=Interaction.BLOCKIERT,
    )


def _seite(client, stunde, **abfrage):
    return client.get(reverse("tutoring:lehrperson_protokoll", args=[stunde.code]),
                      abfrage, secure=True)


# --- Die Liste ----------------------------------------------------------------

def test_die_liste_nennt_offene_und_beendete_sitzungen(client, lehrperson):
    offen = _stunde(lehrperson, title="Offen")
    _zeilen(offen, _kind(offen))
    beendet = _stunde(lehrperson, title="Vorbei")
    _zeilen(beendet, _kind(beendet, "maus"))
    beendet.beenden()
    fremd = _stunde(get_user_model().objects.create_user(username="f", password="x"),
                    title="Fremd")
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_protokolle"), secure=True)

    assert antwort.status_code == 200
    zeilen = {z["sitzung"].title: z for z in antwort.context["zeilen"]}
    assert set(zeilen) == {"Offen", "Vorbei"}
    assert zeilen["Vorbei"]["lokal"] == 1 and zeilen["Vorbei"]["cloud"] == 2
    seite = antwort.content.decode()
    assert "1 am Spark, 2 nach draußen" in seite
    assert "beendet" in seite and "offen" in seite
    assert fremd.title not in seite
    assert reverse("tutoring:lehrperson_protokoll", args=[beendet.code]) in seite
    assert 'href="' + reverse("tutoring:lehrperson_protokolle") + '"' in seite, "der Weg im Kopf"


# --- Die Zeitleiste einer Sitzung ------------------------------------------------

def test_das_protokoll_zeigt_die_kommunikation_mit_der_gegenstelle(client, lehrperson):
    stunde = _stunde(lehrperson)
    _zeilen(stunde, _kind(stunde))
    client.force_login(lehrperson)

    antwort = _seite(client, stunde)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "3 Anfragen, davon 2 nach draußen, 1 blockiert" in seite
    assert "Anweisung an die Gegenstelle" in seite
    assert cloud.SYSTEM.split("\n")[0][:40] in seite
    assert "Das ist hinausgegangen" in seite and "[PERS_a1b2] kauft 6 Packungen" in seite
    assert "Das kam zurück" in seite and "ERGEBNIS: 48 Stifte" in seite
    assert "Daraus wurde lokal, mit eingesetzten Werten" in seite
    assert "Lena: 6 · 8 = 48 Stifte" in seite
    assert "1× Name" in seite
    assert "Nichts hinausgegangen: blockierender_fund" in seite
    assert "Anfrage an den Spark" in seite and "Lena kauft 6 Packungen" in seite
    assert "lage kein_ansatz, absicht tipp" in seite
    assert "0,00123" in seite, "die Kosten der Zeile nach draussen"
    assert reverse("tutoring:lehrperson_sitzung", args=[stunde.code]) in seite


def test_das_protokoll_bleibt_nach_dem_ende_der_sitzung(client, lehrperson):
    stunde = _stunde(lehrperson)
    _zeilen(stunde, _kind(stunde))
    stunde.beenden()
    assert not Participation.objects.exists()
    client.force_login(lehrperson)

    antwort = _seite(client, stunde)

    assert antwort.status_code == 200
    assert len(antwort.context["zeilen"]) == 3
    seite = antwort.content.decode()
    assert "beendet" in seite
    assert "[PERS_a1b2] kauft 6 Packungen" in seite
    assert reverse("tutoring:lehrperson_sitzung", args=[stunde.code]) not in seite


def test_die_filter(client, lehrperson):
    stunde = _stunde(lehrperson)
    kind = _kind(stunde)
    _zeilen(stunde, kind)
    client.force_login(lehrperson)

    assert len(_seite(client, stunde, weg="cloud").context["zeilen"]) == 2
    assert len(_seite(client, stunde, weg="lokal").context["zeilen"]) == 1
    assert len(_seite(client, stunde, nur="blockiert").context["zeilen"]) == 1
    assert len(_seite(client, stunde, stufe="2").context["zeilen"]) == 1
    assert len(_seite(client, stunde, stufe="5").context["zeilen"]) == 0
    assert len(_seite(client, stunde, kennung=kind.log_key).context["zeilen"]) == 3
    assert len(_seite(client, stunde, kennung="x" * 43).context["zeilen"]) == 0
    seite = _seite(client, stunde, weg="cloud").content.decode()
    assert "?weg=cloud&amp;export=json" in seite


def test_der_export_als_json_und_csv(client, lehrperson):
    stunde = _stunde(lehrperson)
    _zeilen(stunde, _kind(stunde))
    client.force_login(lehrperson)

    als_json = _seite(client, stunde, export="json")
    assert als_json["Content-Type"].startswith("application/json")
    assert f'protokoll_{stunde.code}.json' in als_json["Content-Disposition"]
    daten = json.loads(als_json.content.decode())
    assert len(daten) == 3
    draussen = [z for z in daten if z["route"] == "cloud" and z["leak_check"] == "bestanden"][0]
    assert draussen["instruction"] == cloud.SYSTEM
    assert draussen["masked_input"].startswith("[PERS_a1b2]")
    assert draussen["raw_output"] == "Lena: 6 · 8 = 48 Stifte"
    assert draussen["entities_replaced"] == {"PERS": 1}

    als_csv = _seite(client, stunde, export="csv")
    assert als_csv["Content-Type"].startswith("text/csv")
    zeilen = list(csv.reader(io.StringIO(als_csv.content.decode())))
    assert zeilen[0][:3] == ["id", "created_at", "session_key"]
    assert len(zeilen) == 4
    kopf = dict(zip(zeilen[0], zeilen[2]))
    assert json.loads(kopf["entities_replaced"]) == {"PERS": 1}

    gefiltert = json.loads(_seite(client, stunde, weg="lokal", export="json").content.decode())
    assert len(gefiltert) == 1 and gefiltert[0]["diagnosis"] == {"lage": "kein_ansatz", "absicht": "tipp"}


def test_fremde_lehrperson_sieht_nichts(client, lehrperson):
    stunde = _stunde(lehrperson)
    _zeilen(stunde, _kind(stunde))
    client.force_login(get_user_model().objects.create_user(username="f", password="x"))
    assert _seite(client, stunde).status_code == 404
    client.logout()
    assert _seite(client, stunde).status_code == 302


def test_auf_stufe_eins_stehen_nur_zahlen_aber_die_anweisung(client, lehrperson):
    stunde = _stunde(lehrperson, research_level=BETRIEB)
    _zeilen(stunde, _kind(stunde))
    client.force_login(lehrperson)

    seite = _seite(client, stunde).content.decode()

    assert "Nur Zahlen" in seite
    assert "[PERS_a1b2]" not in seite and "Lena" not in seite
    assert "Anweisung an die Gegenstelle" in seite
    zeile = Interaction.objects.get(leak_check=Interaction.BESTANDEN)
    assert zeile.instruction == cloud.SYSTEM and zeile.masked_input == ""


def test_die_qualitaetssicherung_schreibt_die_anweisung_mit(lehrperson):
    stunde = _stunde(lehrperson)
    kind = _kind(stunde)
    views._qs_aufzeichnen.__wrapped__(stunde, kind, {
        "modell": "gpt-5", "tokens_ein": 10, "tokens_aus": 5, "dauer_ms": 900,
        "entitaeten": {}, "maskiert_ein": "6 · 8", "maskiert_aus": "48",
        "loesung": "48", "anweisung": cloud.SYSTEM,
    })
    zeile = Interaction.objects.get()
    assert zeile.instruction == cloud.SYSTEM
    assert zeile.ist_cloud and zeile.weg_text == "externe KI"
    assert zeile.leak_text == "Leak-Check bestanden"
    assert zeile.entitaeten_text == "" and zeile.inhalte_aufgezeichnet


def test_die_sitzungsseite_fuehrt_ins_protokoll(client, lehrperson):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)
    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde.code]),
                       secure=True).content.decode()
    assert reverse("tutoring:lehrperson_protokoll", args=[stunde.code]) in seite
    assert "Protokoll der Anfragen" in seite
