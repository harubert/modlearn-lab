"""Pruefungen der Einstufung von Beitraegen.

Geprueft wird hier alles, was ohne das Sprachmodell auskommt: die
deterministische Untergrenze, die Rangfolge der Farben und das Auslesen der
Modellantwort. Der Aufruf des Spark selbst gehoert nicht in einen Test, der
bei jedem Ausrollen laeuft.
"""

import pytest

from tutoring import pruefung


# --- Die deterministische Untergrenze -------------------------------------

@pytest.mark.parametrize("text", [
    "du bist ein Arschloch",
    "So ein TROTTEL",
    "der lehrer ist ein depp",
])
def test_eindeutige_schimpfwoerter_sind_rot(text):
    assert pruefung.deterministischer_boden(text) == pruefung.ROT


@pytest.mark.parametrize("text", [
    "Ich habe 6 plus 8 gerechnet",
    "ich weiß nicht weiter",
    "Das ist schwer",
    "Die Schachtel hat 6 Packungen",
    "",
])
def test_normale_beitraege_loesen_nichts_aus(text):
    assert pruefung.deterministischer_boden(text) is None


def test_die_untergrenze_gilt_auch_ohne_modell(monkeypatch):
    """Faellt der Spark aus, bleibt ein Schimpfwort trotzdem rot."""
    def kein_spark(*args, **kwargs):
        raise OSError("kein Netz")

    monkeypatch.setattr(pruefung.httpx, "Client", kein_spark)

    stufe, _ = pruefung.einstufen("du Trottel")

    assert stufe == pruefung.ROT


def test_ohne_modell_und_ohne_fund_bleibt_es_ungeprueft(monkeypatch):
    """Nicht stillschweigend gruen: die Lehrperson soll den Unterschied sehen."""
    def kein_spark(*args, **kwargs):
        raise OSError("kein Netz")

    monkeypatch.setattr(pruefung.httpx, "Client", kein_spark)

    stufe, _ = pruefung.einstufen("Ich habe 6 plus 8 gerechnet")

    assert stufe == pruefung.UNGEPRUEFT


def test_leerer_beitrag_ist_gruen():
    assert pruefung.einstufen("")[0] == pruefung.GRUEN


# --- Die Rangfolge ---------------------------------------------------------

def test_schlimmeres_gewinnt():
    assert pruefung.schlimmeres(pruefung.GRUEN, pruefung.ROT) == pruefung.ROT
    assert pruefung.schlimmeres(pruefung.ORANGE, pruefung.GELB) == pruefung.ORANGE
    assert pruefung.schlimmeres(pruefung.ROT, pruefung.ORANGE) == pruefung.ROT
    assert pruefung.schlimmeres(pruefung.GRUEN, pruefung.GRUEN) == pruefung.GRUEN


def test_ungeprueft_verdraengt_nichts():
    """Eine misslungene Pruefung darf eine bekannte Auffaelligkeit nicht loeschen."""
    assert pruefung.schlimmeres(pruefung.ROT, pruefung.UNGEPRUEFT) == pruefung.ROT
    assert pruefung.schlimmeres(pruefung.GELB, pruefung.UNGEPRUEFT) == pruefung.GELB


def test_jede_farbe_hat_eine_beschreibung():
    for farbe in pruefung.GUELTIG:
        assert pruefung.BESCHREIBUNG[farbe]


# --- Auslesen der Modellantwort -------------------------------------------

def test_saubere_antwort_wird_gelesen():
    stufe, grund = pruefung._einstufung_aus_antwort(
        '{"stufe": "orange", "grund": "will die Grenze umgehen"}'
    )

    assert stufe == pruefung.ORANGE
    assert grund == "will die Grenze umgehen"


def test_antwort_mit_beiwerk_wird_gelesen():
    """Modelle stellen gern einen Satz vor das JSON."""
    stufe, _ = pruefung._einstufung_aus_antwort(
        'Hier die Einschaetzung:\n{"stufe": "gelb", "grund": "Buchstabensalat"}\nPasst das?'
    )

    assert stufe == pruefung.GELB


@pytest.mark.parametrize("roh", [
    "",
    "keine Ahnung",
    '{"stufe": "lila", "grund": "x"}',
    '{"grund": "ohne Stufe"}',
    "{kaputtes json",
])
def test_unbrauchbare_antworten_werden_abgewiesen(roh):
    stufe, _ = pruefung._einstufung_aus_antwort(roh)

    assert stufe is None
