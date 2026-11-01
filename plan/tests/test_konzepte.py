"""Nutzungskonzepte: Plaetze addieren sich, Modelle nicht.

Reine Funktionen. Hier steht, welche Paare zusammengehen und welche nicht,
und warum die Antwort nicht in Plaetzen steckt.
"""

import pytest

from plan import konzepte


def test_sechs_konzepte_und_unterricht_ist_der_standard():
    assert konzepte.STANDARD == "unterricht"
    assert set(konzepte.SCHLUESSEL) == {
        "unterricht", "sichere_verwaltung", "kreativ", "wissensdienst",
        "modellschulung", "entwicklung",
    }


def test_ohne_broker_kommt_geladen_aus_der_umgebung(settings, tmp_path):
    """Nur das Beobachtete, nichts Zugesagtes - solange niemand nachsehen kann."""
    from plan import broker

    settings.SPARK_BROKER_SECRET_DATEI = str(tmp_path / "gibt-es-nicht")
    broker.vergessen()

    assert konzepte.geladen() == frozenset({konzepte.TEXT, konzepte.GEHOER})
    assert konzepte.aktuelles_profil() == "qwen"


@pytest.mark.parametrize("schluessel, erwartet", [
    ("unterricht", False),
    ("sichere_verwaltung", False),
    ("entwicklung", False),
    ("kreativ", True),             # anderes Profil als das geladene
    ("wissensdienst", True),       # Nachschlagemodell liegt nicht im Speicher
    ("modellschulung", True),
])
def test_wer_den_rechner_umbaut(schluessel, erwartet):
    assert konzepte.braucht_umbau(schluessel) is erwartet


@pytest.mark.parametrize("schluessel, erwartet", [
    ("unterricht", False),
    ("sichere_verwaltung", False),
    ("kreativ", True),             # 100 Prozent und anderes Profil
    ("wissensdienst", True),       # Umbau
    ("modellschulung", True),      # Umbau und 100 Prozent
    ("entwicklung", True),         # 100 Prozent, kein Umbau
])
def test_wer_den_rechner_allein_belegt(schluessel, erwartet):
    assert konzepte.ist_alleinig(schluessel) is erwartet


def test_jedes_konzept_nennt_sein_profil_oder_ehrlich_keines():
    assert konzepte.profil("unterricht") == "qwen"
    assert konzepte.profil("kreativ") == "kreativ"
    assert konzepte.profil("wissensdienst") is None, "kein Profil laedt ein Nachschlagemodell"
    assert konzepte.profil("erfunden") is None


def test_unterricht_neben_unterricht_ist_der_normalfall():
    assert konzepte.vertraeglich("unterricht", "unterricht") is True


def test_unterricht_neben_sicherer_verwaltung_geht():
    """Beide kommen ohne Umbau aus; dann entscheidet die Kapazitaet."""
    assert konzepte.vertraeglich("unterricht", "sichere_verwaltung") is True
    assert konzepte.vertraeglich("sichere_verwaltung", "unterricht") is True


@pytest.mark.parametrize("einer, anderer", [
    ("unterricht", "wissensdienst"),
    ("wissensdienst", "unterricht"),
    ("unterricht", "modellschulung"),
    ("sichere_verwaltung", "modellschulung"),
    ("unterricht", "entwicklung"),
    ("unterricht", "kreativ"),                # anderes Profil: Qwen waere weg
    ("kreativ", "sichere_verwaltung"),
    ("wissensdienst", "wissensdienst"),       # alleinig auch gegen sich selbst
    ("modellschulung", "modellschulung"),
    ("kreativ", "kreativ"),
])
def test_was_nicht_zusammengeht(einer, anderer):
    assert konzepte.vertraeglich(einer, anderer) is False


def test_unbekanntes_konzept_geht_mit_nichts_zusammen():
    assert konzepte.vertraeglich("unterricht", "erfunden") is False
    assert konzepte.vertraeglich("erfunden", "erfunden") is False


def test_der_grund_nennt_den_umbau_und_die_zeit():
    satz = konzepte.grund_unvertraeglich("wissensdienst", "unterricht", "10:15")
    assert "geladen" in satz and "10:15" in satz
    assert "Unterricht mit einer Klasse" in satz

    satz = konzepte.grund_unvertraeglich("unterricht", "wissensdienst", "10:15")
    assert "umgebaut" in satz and "10:15" in satz

    satz = konzepte.grund_unvertraeglich("unterricht", "entwicklung", "08:00")
    assert "ganz" in satz and "08:00" in satz


def test_wenn_das_nachschlagemodell_geladen_ist_wird_der_wissensdienst_zahm(monkeypatch):
    """Was der Broker als geladen meldet, entscheidet - nicht der Code."""
    monkeypatch.setattr(
        konzepte, "geladen",
        lambda: frozenset({konzepte.TEXT, konzepte.GEHOER, konzepte.EINBETTUNG}),
    )
    assert konzepte.braucht_umbau("wissensdienst") is False
    assert konzepte.vertraeglich("unterricht", "wissensdienst") is True


def test_wenn_kreativ_geladen_ist_braucht_unterricht_den_umbau(monkeypatch):
    """Das Profil entscheidet mit: Unterricht neben entladenem Qwen geht nicht."""
    monkeypatch.setattr(konzepte, "aktuelles_profil", lambda: "kreativ")
    monkeypatch.setattr(konzepte, "geladen", lambda: frozenset({konzepte.GEHOER}))
    assert konzepte.braucht_umbau("unterricht") is True
    assert konzepte.braucht_umbau("kreativ") is False


def test_sichere_verwaltung_darf_nie_nach_draussen():
    """Das ist der Zweck und keine Einstellung."""
    assert konzepte.cloud_erlaubt("sichere_verwaltung") is False
    assert konzepte.cloud_erlaubt("wissensdienst") is False
    assert konzepte.cloud_erlaubt("unterricht") is True
    assert konzepte.cloud_erlaubt("erfunden") is False


def test_unterricht_zaehlt_in_zehnerschritten():
    assert konzepte.plaetze_schritt("unterricht") == 10
    assert konzepte.plaetze_schritt("sichere_verwaltung") == 1
    assert konzepte.plaetze_schritt("erfunden") == 1


def test_anteile_sind_plausibel():
    for k in konzepte.KONZEPTE:
        assert 0 < k["anteil"] <= 100, k["schluessel"]
    assert konzepte.anteil("modellschulung") == 100
    assert konzepte.anteil("erfunden") == 0
