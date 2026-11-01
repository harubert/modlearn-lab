"""Die Erfahrungswerte fuer den Fortschrittsbalken (core/musik_zeit.py)."""

import pytest

from core import musik_zeit


@pytest.fixture(autouse=True)
def _frisch():
    musik_zeit.vergessen()
    yield
    musik_zeit.vergessen()


def test_erwartung_rechnet_grundlast_plus_minuten():
    """60 s in der kleinen Fassung: 1,5 s Grundlast + 8,6 s je Minute (gemessen 20.10.2026)."""
    assert musik_zeit.erwartung(60, "klein") == pytest.approx(10.1, abs=0.05)
    assert musik_zeit.erwartung(120, "klein") == pytest.approx(18.7, abs=0.05)
    assert musik_zeit.erwartung(30, "klein") == pytest.approx(5.8, abs=0.05)


def test_unbekannte_fassung_und_unsinn_fallen_auf_die_vorgabe():
    assert musik_zeit.erwartung(60, "gibtesnicht") == musik_zeit.erwartung(60, "klein")
    assert musik_zeit.erwartung("x", "klein") == musik_zeit.erwartung(60, "klein")
    assert musik_zeit.erwartung(None) == musik_zeit.erwartung(60, "klein")
    assert musik_zeit.erwartung(-5) == musik_zeit.erwartung(60, "klein")


def test_merken_zieht_die_erwartung_nach():
    """Der Spark ist langsamer als gewohnt: Nach drei Liedern zu je 20 s ist
    die Erwartung zu zwei Dritteln dort angekommen."""
    vorher = musik_zeit.erwartung(60, "klein")
    for _ in range(3):
        musik_zeit.merken(20.0, 60, "klein")
    nachher = musik_zeit.erwartung(60, "klein")
    assert nachher > vorher
    # 20 s - 1,5 s Grundlast = 18,5 s je Minute; EMA mit 0,3 dreimal:
    # 8,6 -> 11,57 -> 13,65 -> 15,1 je Minute -> 16,6 s fuer 60 s.
    assert nachher == pytest.approx(16.6, abs=0.2)


def test_merken_ignoriert_unsinn():
    vorher = musik_zeit.erwartung(60, "klein")
    assert musik_zeit.merken(None, 60) is None
    assert musik_zeit.merken("x", 60) is None
    assert musik_zeit.merken(-3, 60) is None
    assert musik_zeit.merken(10.0, 5) is None, "unter zehn Sekunden Lied ist kein Messwert"
    assert musik_zeit.erwartung(60, "klein") == vorher


def test_fassungen_lernen_getrennt():
    musik_zeit.merken(40.0, 60, "klein")
    assert musik_zeit.erwartung(60, "xl") == pytest.approx(21.5, abs=0.05)


def test_vergessen_setzt_auf_die_erfahrung_zurueck():
    musik_zeit.merken(40.0, 60, "klein")
    musik_zeit.vergessen("klein")
    assert musik_zeit.erwartung(60, "klein") == pytest.approx(10.1, abs=0.05)
