"""Der Broker-Baustein: still ohne Geheimnis, tolerant ohne Spark.

Hier laeuft kein Netz. Geprueft wird, was der Baustein zusagt: Fehlt die
Datei, gibt es keinen Broker; antwortet der Broker, zaehlt seine Auskunft;
antwortet er nicht, rechnet die App mit dem letzten bekannten Stand oder der
Umgebung - und nichts davon wirft nach aussen.
"""

import pytest

from plan import broker, konzepte


@pytest.fixture(autouse=True)
def frisch():
    broker.vergessen()
    yield
    broker.vergessen()


@pytest.fixture
def ohne_geheimnis(settings, tmp_path):
    settings.SPARK_BROKER_SECRET_DATEI = str(tmp_path / "fehlt")


@pytest.fixture
def mit_geheimnis(settings, tmp_path):
    datei = tmp_path / "spark-broker"
    datei.write_text("abc123\n", encoding="utf-8")
    settings.SPARK_BROKER_SECRET_DATEI = str(datei)


def test_ohne_datei_gibt_es_keinen_broker(ohne_geheimnis):
    assert broker.geheimnis() is None
    assert broker.moeglich() is False
    assert broker.status() is None


def test_das_geheimnis_wird_getrimmt_und_einmal_gelesen(mit_geheimnis, settings):
    assert broker.geheimnis() == "abc123"
    # Spaetere Aenderung der Datei greift erst nach dem Neustart.
    settings.SPARK_BROKER_SECRET_DATEI = "/gibt/es/nicht"
    assert broker.geheimnis() == "abc123"


def test_eine_fehlende_datei_wird_nicht_gemerkt(settings, tmp_path):
    """Legt Thomas sie nachtraeglich ab, greift sie ohne Neustart."""
    datei = tmp_path / "spark-broker"
    settings.SPARK_BROKER_SECRET_DATEI = str(datei)
    assert broker.geheimnis() is None
    datei.write_text("spaeter", encoding="utf-8")
    assert broker.geheimnis() == "spaeter"


def test_ohne_broker_kommen_dienste_und_profil_aus_der_umgebung(ohne_geheimnis, settings):
    settings.SPARK_GELADENE_MODELLE = "text, gehoer"
    settings.SPARK_PROFIL = "qwen"
    assert broker.geladene_dienste() == frozenset({"text", "gehoer"})
    assert broker.aktuelles_profil() == "qwen"


def test_die_auskunft_des_brokers_zaehlt(mit_geheimnis, monkeypatch):
    antwort = {
        "profil": "kreativ", "zustand": "bereit",
        "dienste": [
            {"name": "gehoer", "port": 8002, "bereit": True},
            {"name": "text", "port": 8000, "bereit": False},
        ],
    }
    monkeypatch.setattr(broker, "_holen", lambda pfad, *a, **k: (200, antwort))

    assert broker.aktuelles_profil() == "kreativ"
    assert broker.geladene_dienste() == frozenset({"gehoer"}), "nur was bereit ist"
    assert konzepte.braucht_umbau("unterricht") is True
    assert konzepte.braucht_umbau("kreativ") is False


def test_die_auskunft_wird_zwischengespeichert(mit_geheimnis, monkeypatch):
    aufrufe = []

    def attrappe(pfad, *a, **k):
        aufrufe.append(pfad)
        return 200, {"profil": "qwen", "zustand": "bereit", "dienste": []}
    monkeypatch.setattr(broker, "_holen", attrappe)

    broker.status()
    broker.status()
    broker.status(frisch=True)

    assert aufrufe == ["/status", "/status"]


def test_waehrend_des_wechsels_zaehlt_das_zielprofil(mit_geheimnis, monkeypatch):
    monkeypatch.setattr(broker, "_holen", lambda *a, **k: (
        200, {"profil": "gptoss", "zustand": "wechselt", "dienste": []}
    ))
    assert broker.aktuelles_profil() == "gptoss"


def test_im_fehlerzustand_gilt_die_umgebung(mit_geheimnis, monkeypatch, settings):
    settings.SPARK_PROFIL = "qwen"
    monkeypatch.setattr(broker, "_holen", lambda *a, **k: (
        200, {"profil": "gptoss", "zustand": "fehler", "fehler": "kaputt", "dienste": []}
    ))
    assert broker.aktuelles_profil() == "qwen"


def test_ein_unerreichbarer_broker_wirft_nicht(mit_geheimnis, monkeypatch, settings):
    def kaputt(*a, **k):
        raise broker.BrokerNichtErreichbar("aus")
    monkeypatch.setattr(broker, "_holen", kaputt)
    settings.SPARK_GELADENE_MODELLE = "text,gehoer"

    assert broker.status() is None
    assert broker.geladene_dienste() == frozenset({"text", "gehoer"})
    assert broker.profile() == []
    angenommen, antwort = broker.aktivieren("qwen", "2026-10-12T10:00:00+02:00")
    assert angenommen is False
    assert "antwortet nicht" in antwort["grund"]


def test_der_letzte_bekannte_stand_ueberlebt_einen_ausfall(mit_geheimnis, monkeypatch):
    """Ein Spark, der gerade neu startet, darf die Buchungsseite nicht leeren."""
    monkeypatch.setattr(broker, "_holen", lambda *a, **k: (
        200, {"profil": "qwen", "zustand": "bereit", "dienste": []}
    ))
    assert broker.status()["profil"] == "qwen"

    def kaputt(*a, **k):
        raise broker.BrokerNichtErreichbar("aus")
    monkeypatch.setattr(broker, "_holen", kaputt)
    assert broker.status(frisch=True)["profil"] == "qwen"


def test_aktivieren_reicht_den_409_durch(mit_geheimnis, monkeypatch):
    """Der Satz des Brokers ist der Satz fuer die Lehrperson."""
    gesehen = {}

    def attrappe(pfad, methode="GET", daten=None, frist=8.0):
        gesehen.update(daten or {})
        return 409, {"grund": "Bis 12:00 Uhr laeuft noch eine Buchung.",
                     "schaltet_ab": ["gehoer"]}
    monkeypatch.setattr(broker, "_holen", attrappe)

    angenommen, antwort = broker.aktivieren("gptoss", "2026-10-12T10:00:00+02:00")

    assert angenommen is False
    assert antwort["schaltet_ab"] == ["gehoer"]
    assert gesehen == {"profil": "gptoss", "bis": "2026-10-12T10:00:00+02:00",
                       "erzwingen": False}


def test_aktivieren_mit_202_vergisst_den_alten_status(mit_geheimnis, monkeypatch):
    antworten = iter([
        (200, {"profil": "qwen", "zustand": "bereit", "dienste": []}),
        (202, {"hinweis": "wechselt"}),
        (200, {"profil": "kreativ", "zustand": "wechselt", "dienste": []}),
    ])
    monkeypatch.setattr(broker, "_holen", lambda *a, **k: next(antworten))

    assert broker.aktuelles_profil() == "qwen"
    angenommen, _ = broker.aktivieren("kreativ", "2026-10-12T10:00:00+02:00", erzwingen=True)
    assert angenommen is True
    assert broker.aktuelles_profil() == "kreativ", "nicht der alte Zwischenstand"
