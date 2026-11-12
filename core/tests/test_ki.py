"""Die Seite "Welche KI hier arbeitet" (Thomas, 7.11.2026).

Vier Teile in fester Reihenfolge (Fakten, Zweck, Massnahme, Einordnung), die
Modellnamen aus den Einstellungen, die Zahlen aus der Neutralitaetsprobe oder
der ehrliche Satz, dass sie noch ausstehen.
"""

import json

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_die_seite_nennt_das_modell_und_seinen_hersteller(client, settings):
    settings.SPARK_MODEL = "qwen3.6-35b-a3b"
    settings.CLOUD_ENABLED = False
    settings.PFOERTNER_MODEL = ""
    seite = client.get(reverse("ki"), secure=True)
    text = seite.content.decode()

    assert seite.status_code == 200
    assert "Welche KI hier arbeitet" in text
    assert "qwen3.6-35b-a3b" in text and "Alibaba" in text and "China" in text
    assert text.index("1. Die Fakten") < text.index("2. Darum geht es hier nicht") \
        < text.index("3. Was wir tun") < text.index("4. Einordnung")
    assert "zweites Modell für dieses\n    Urteil ist vorgesehen" in text or "ist vorgesehen" in text
    assert "nicht eingerichtet" in text


def test_ein_zweites_modell_und_die_qualitaetssicherung_erscheinen_mit_namen(client, settings):
    settings.PFOERTNER_MODEL = "ministral-3-8b"
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "gpt-6.1-sol"
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "ministral-3-8b" in text and "Mistral AI" in text
    assert "gpt-6.1-sol" in text and "OpenAI" in text


def test_ohne_zahlen_sagt_die_seite_dass_die_pruefung_aussteht(client, settings, tmp_path):
    settings.NEUTRALITAET_ERGEBNIS = tmp_path / "gibt_es_nicht.json"
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "sobald sie gelaufen ist" in text
    assert "Letzte Prüfung" not in text


def test_mit_zahlen_zeigt_die_seite_die_tabelle(client, settings, tmp_path):
    datei = tmp_path / "ergebnis.json"
    datei.write_text(json.dumps({
        "datum": "2026-11-08", "modell": "qwen3.6-35b-a3b", "paare": 12,
        "stellen": {
            "roh": {"china": {"beantwortet": 7, "verweigert": 5}, "vergleich": {"beantwortet": 12}},
            "mathe": {"china": {"satz": 12}, "vergleich": {"satz": 12}},
        },
    }), encoding="utf-8")
    settings.NEUTRALITAET_ERGEBNIS = datei
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "Letzte Prüfung: 2026-11-08" in text
    assert "Das Modell ohne Anweisung" in text and "Mathematikstunde" in text
    assert "Sachunterricht" not in text.split("<tbody>")[1].split("</tbody>")[0]
    assert "sobald sie gelaufen ist" not in text


def test_mit_urteilen_zeigt_die_seite_auch_den_inhalt_und_wer_geurteilt_hat(client, settings, tmp_path):
    datei = tmp_path / "ergebnis.json"
    datei.write_text(json.dumps({
        "datum": "2026-11-07", "modell": "qwen3.6-35b-a3b", "paare": 12,
        "stellen": {
            "roh": {"china": {"beantwortet": 12}, "vergleich": {"beantwortet": 12}},
            "safechat": {"china": {"beantwortet": 9, "verweigert": 3}, "vergleich": {"beantwortet": 12}},
        },
        "gleichbehandelt": {"roh": "12 von 12", "safechat": "9 von 12"},
        "urteil": {
            "roh": {"china": {"sachlich": 5, "einseitig": 7}, "vergleich": {"sachlich": 12}},
            "safechat": {"china": {"sachlich": 9, "verweigert": 3}, "vergleich": {"sachlich": 12}},
        },
        "gleich_beurteilt": {"roh": "5 von 12", "safechat": "9 von 12"},
        "beurteilt_von": "Claude Fable 5.1 (Anthropic, USA), ein zweites Sprachmodell",
        "urteil_datum": "2026-11-09",
    }), encoding="utf-8")
    settings.NEUTRALITAET_ERGEBNIS = datei
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "Der Inhalt, beurteilt" in text
    assert "Claude Fable 5.1 (Anthropic, USA)" in text and "2026-11-09" in text
    assert "5 von 12" in text and "9 von 12" in text
    zweite = text.split("Der Inhalt, beurteilt")[1]
    assert "<td>7</td>" in zweite and "einseitig" in zweite
    assert "Auch dieses Urteil hat eine Prägung" in text


def test_ohne_urheber_erscheint_kein_urteil(client, settings, tmp_path):
    datei = tmp_path / "ergebnis.json"
    datei.write_text(json.dumps({
        "datum": "2026-11-07", "modell": "qwen3.6-35b-a3b", "paare": 12,
        "stellen": {"roh": {"china": {"beantwortet": 12}, "vergleich": {"beantwortet": 12}}},
        "urteil": {"roh": {"china": {"einseitig": 7, "sachlich": 5}, "vergleich": {"sachlich": 12}}},
    }), encoding="utf-8")
    settings.NEUTRALITAET_ERGEBNIS = datei
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "Letzte Prüfung: 2026-11-07" in text
    assert "Der Inhalt, beurteilt" not in text


def test_eine_kaputte_datei_heisst_keine_zahlen(client, settings, tmp_path):
    datei = tmp_path / "ergebnis.json"
    datei.write_text("{kaputt", encoding="utf-8")
    settings.NEUTRALITAET_ERGEBNIS = datei
    text = client.get(reverse("ki"), secure=True).content.decode()

    assert "sobald sie gelaufen ist" in text


def test_der_fuss_fuehrt_zur_seite(client):
    start = client.get("/", secure=True).content.decode()
    assert f'href="{reverse("ki")}"' in start
    assert "Welche KI hier arbeitet" in start
