"""Die Testecke fuer die Musik-KI: Zugang, ruhige Fehler, Durchreichen.

Hier laeuft kein Netz. Der Baustein core.musik wird per monkeypatch ersetzt;
geprueft wird, was die Ansichten zusagen: wer hinein darf, dass ohne
Geheimnis oder ohne Dienst eine Meldung statt eines 500 kommt, dass der
Rumpf an den Dienst stimmt, und dass nur eigene Auftraege erreichbar sind.
"""

import pytest
from django.contrib.auth import get_user_model

from core import musik
from plan import broker
from plan.models import Nutzerklasse, Profil

SEITE = "/labor/musik/"


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


@pytest.fixture
def ohne_netz(monkeypatch):
    """Jeder Aufruf, der doch ins Netz will, faellt hier auf."""
    def kein_netz(*a, **k):
        raise AssertionError("Unerwarteter Netzaufruf")
    monkeypatch.setattr(musik.httpx, "Client", kein_netz)


@pytest.fixture
def staff(db, client):
    person = get_user_model().objects.create_user(
        username="betreuung", password="x", is_staff=True
    )
    client.force_login(person)
    return person


class Attrappe:
    def __init__(self):
        self.aufrufe = []
        self.loeschantwort = {"entfernt": True, "datei_entfernt": True}


@pytest.fixture
def dienst(monkeypatch, mit_geheimnis):
    """Ein Musikdienst, der antwortet. Merkt sich, was er bekommt."""
    attrappe = Attrappe()

    def holen(pfad, methode="GET", daten=None, frist=10.0, mit_geheimnis=True):
        attrappe.aufrufe.append((methode, pfad, daten))
        if pfad == "/gesundheit":
            return musik.Antwort(True, 200, {"ok": True})
        if pfad == "/stile":
            return musik.Antwort(True, 200, {"stile": [
                {"name": "pop", "tags": "pop, bright", "bpm": 110, "tonart": "C major"},
            ]})
        if pfad == "/grenzen":
            return musik.Antwort(True, 200, {
                "sekunden_vorgabe": 60, "sekunden_max": 240, "text_max": 4000,
                "tags_max": 600, "verfall_stunden": 8,
                "fassungen": {"xl": {"sekunden_je_minute": 20},
                              "klein": {"sekunden_je_minute": 9}},
            })
        if pfad == "/lied":
            return musik.Antwort(True, 202, {"auftrag": "a1b2", "zustand": "wartet",
                                             "position": 3, "wartet_noch_s": 120})
        if pfad.startswith("/auftrag/") and methode == "GET":
            return musik.Antwort(True, 200, {"zustand": "fertig", "position": 0,
                                             "wartet_noch_s": 0, "dauer_s": 21})
        if pfad.startswith("/auftrag/") and methode == "DELETE":
            return musik.Antwort(True, 200, attrappe.loeschantwort)
        raise AssertionError(pfad)

    monkeypatch.setattr(musik, "_holen", holen)
    return attrappe


def _anlegen(client):
    return client.post(SEITE + "lied/", {
        "stil": "pop", "tags": "pop, bright", "lyrics": "[Strophe]\nLa la",
        "sekunden": "90", "bpm": "110", "tonart": "C major", "takt": "4/4",
        "sprache": "de", "fassung": "klein",
    }, secure=True)


# --- Zugang ---------------------------------------------------------------

@pytest.mark.django_db
def test_anonym_wird_zur_anmeldung_geschickt(client):
    antwort = client.get(SEITE, secure=True)
    assert antwort.status_code == 302
    assert "/anmelden/" in antwort["Location"]


@pytest.mark.django_db
def test_gewoehnliche_lehrperson_bekommt_403(client):
    person = get_user_model().objects.create_user(username="lehrerin", password="x")
    klasse, _ = Nutzerklasse.objects.get_or_create(name="Schule")
    Profil.objects.create(benutzer=person, klasse=klasse)
    client.force_login(person)
    assert client.get(SEITE, secure=True).status_code == 403
    assert client.post(SEITE + "lied/", {}, secure=True).status_code == 403


@pytest.mark.django_db
def test_benutzer_ohne_profil_bekommt_403(client):
    client.force_login(get_user_model().objects.create_user(username="x", password="x"))
    assert client.get(SEITE, secure=True).status_code == 403


def test_staff_kommt_hinein(staff, client, dienst):
    antwort = client.get(SEITE, secure=True)
    assert antwort.status_code == 200
    assert "Lied rechnen lassen" in antwort.content.decode()


@pytest.mark.django_db
def test_lab_profil_kommt_hinein(client, dienst):
    person = get_user_model().objects.create_user(username="lab", password="x")
    klasse, _ = Nutzerklasse.objects.get_or_create(name="Lab")
    Profil.objects.create(benutzer=person, klasse=klasse)
    client.force_login(person)
    assert client.get(SEITE, secure=True).status_code == 200


# --- Ruhige Fehler ----------------------------------------------------------

def test_ohne_geheimnisdatei_ruhige_meldung(staff, client, ohne_geheimnis, monkeypatch, settings):
    # Die Gesundheit geht ohne Geheimnis; hier antwortet sie nicht.
    import httpx

    class KeinNetz:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            raise httpx.ConnectError("weg")

    monkeypatch.setattr(musik.httpx, "Client", KeinNetz)
    antwort = client.get(SEITE, secure=True)
    seite = antwort.content.decode()
    assert antwort.status_code == 200
    assert "Die Geheimnisdatei " + settings.SPARK_BROKER_SECRET_DATEI + " fehlt" in seite
    assert "antwortet nicht" in seite
    assert 'id="musik-form"' not in seite


def test_dienst_antwortet_nicht_ruhige_meldung(staff, client, mit_geheimnis, monkeypatch):
    import httpx

    class KeinNetz:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            raise httpx.ConnectTimeout("weg")

    monkeypatch.setattr(musik.httpx, "Client", KeinNetz)
    antwort = client.get(SEITE, secure=True)
    assert antwort.status_code == 200
    assert "Er antwortet nicht" in antwort.content.decode()


def test_absenden_ohne_geheimnis_ist_kein_500(staff, client, ohne_geheimnis, ohne_netz):
    antwort = _anlegen(client)
    assert antwort.status_code == 200
    assert antwort.json()["ok"] is False
    assert "Geheimnisdatei" in antwort.json()["grund"]


# --- Absenden, abfragen, abspielen, loeschen -------------------------------

def test_absenden_ruft_den_dienst_mit_richtigem_rumpf(staff, client, dienst):
    antwort = _anlegen(client)
    assert antwort.status_code == 200
    assert antwort.json()["ok"] is True
    assert antwort.json()["position"] == 3

    methode, pfad, daten = [a for a in dienst.aufrufe if a[1] == "/lied"][0]
    assert methode == "POST"
    assert daten == {
        "tags": "pop, bright", "lyrics": "[Strophe]\nLa la", "sekunden": 90,
        "bpm": 110, "tonart": "C major", "takt": "4/4", "sprache": "de",
        "fassung": "klein", "kennzeichen": musik.kennzeichen(staff),
    }
    # Kein Klartextname im Kennzeichen.
    assert daten["kennzeichen"].startswith("labor-")
    assert "betreuung" not in daten["kennzeichen"]
    assert len(daten["kennzeichen"]) <= 128
    assert client.session["musik_lieder"][0]["auftrag"] == "a1b2"


def test_absage_des_dienstes_kommt_als_grund_an(staff, client, monkeypatch, mit_geheimnis):
    monkeypatch.setattr(musik, "_holen", lambda *a, **k: musik.Antwort(
        False, 400, {"grund": "Liedtext zu lang."}, "Liedtext zu lang."))
    antwort = _anlegen(client)
    assert antwort.json() == {"ok": False, "grund": "Liedtext zu lang."}
    assert "musik_lieder" not in client.session


def test_abfrage_liefert_stand_und_dateiadresse(staff, client, dienst):
    _anlegen(client)
    antwort = client.get(SEITE + "auftrag/a1b2/", secure=True).json()
    assert antwort["zustand"] == "fertig"
    assert antwort["datei"] == "/labor/musik/datei/a1b2/"
    assert client.session["musik_lieder"][0]["zustand"] == "fertig"


def test_datei_wird_durchgestreamt(staff, client, dienst, monkeypatch):
    _anlegen(client)
    gefragt = []

    def datei(kennung):
        gefragt.append(kennung)
        return 200, "audio/mpeg", "6", iter([b"ID", b"3MP3"])

    monkeypatch.setattr(musik, "datei", datei)
    antwort = client.get(SEITE + "datei/a1b2/", secure=True)
    assert antwort.status_code == 200
    assert antwort.streaming
    assert antwort["Content-Type"] == "audio/mpeg"
    assert b"".join(antwort.streaming_content) == b"ID3MP3"
    assert gefragt == ["a1b2"]


def test_datei_ohne_dienst_ist_503_nicht_500(staff, client, dienst, monkeypatch):
    _anlegen(client)
    monkeypatch.setattr(musik, "datei", lambda kennung: None)
    assert client.get(SEITE + "datei/a1b2/", secure=True).status_code == 503


@pytest.mark.parametrize("meldung, erwartet", [
    ({"entfernt": True, "datei_entfernt": True}, "Auftrag und Datei sind am Spark gelöscht."),
    ({"entfernt": True, "datei_entfernt": False}, "datei_entfernt: false"),
    ({"entfernt": True}, "kein datei_entfernt"),
])
def test_loeschen_wertet_datei_entfernt_aus(staff, client, dienst, meldung, erwartet):
    _anlegen(client)
    dienst.loeschantwort = meldung
    antwort = client.post(SEITE + "loeschen/a1b2/", secure=True).json()
    assert erwartet in antwort["satz"]
    assert antwort["datei_entfernt"] == meldung.get("datei_entfernt")
    assert ("DELETE", "/auftrag/a1b2", None) in dienst.aufrufe
    assert client.session["musik_lieder"] == []


def test_nicht_entfernt_bleibt_in_der_liste(staff, client, dienst):
    _anlegen(client)
    dienst.loeschantwort = {"entfernt": False, "datei_entfernt": False}
    antwort = client.post(SEITE + "loeschen/a1b2/", secure=True).json()
    assert antwort["ok"] is False
    assert client.session["musik_lieder"][0]["auftrag"] == "a1b2"


# --- Nur eigene Auftraege ----------------------------------------------------

def test_fremde_auftraege_sind_nicht_erreichbar(staff, client, dienst):
    _anlegen(client)
    for weg in ("auftrag/fremd1/", "datei/fremd1/"):
        assert client.get(SEITE + weg, secure=True).status_code == 404
    assert client.post(SEITE + "loeschen/fremd1/", secure=True).status_code == 404
    # Der Dienst wurde fuer die fremde Kennung nie gefragt.
    assert not [a for a in dienst.aufrufe if "fremd1" in a[1]]


def test_andere_sitzung_sieht_den_auftrag_nicht(staff, client, dienst):
    from django.test import Client

    _anlegen(client)
    zweite = Client()
    zweite.force_login(staff)
    assert zweite.get(SEITE + "auftrag/a1b2/", secure=True).status_code == 404


def test_kennung_mit_pfadzeichen_wird_abgewiesen(staff, client, dienst):
    assert client.get(SEITE + "auftrag/..%2Fgrenzen/", secure=True).status_code == 404


# --- Der Baustein selbst, mit einer httpx-Attrappe statt des Spark ---------

def _mit_transport(monkeypatch, behandeln):
    import httpx

    echter = httpx.Client

    def client(*a, **k):
        return echter(*a, transport=httpx.MockTransport(behandeln), **k)

    monkeypatch.setattr(musik.httpx, "Client", client)


def test_baustein_schickt_das_geheimnis_und_wertet_400_aus(mit_geheimnis, monkeypatch):
    import httpx

    gesehen = []

    def behandeln(anfrage):
        gesehen.append(anfrage)
        return httpx.Response(400, json={"grund": "sekunden über 240"})

    _mit_transport(monkeypatch, behandeln)
    antwort = musik.lied_anlegen({"sekunden": 999})
    assert antwort.ok is False
    assert antwort.code == 400
    assert antwort.satz == "sekunden über 240"
    assert gesehen[0].headers["X-Broker-Secret"] == "abc123"
    assert str(gesehen[0].url).endswith(":8011/lied")


def test_gesundheit_geht_ohne_geheimnis(ohne_geheimnis, monkeypatch):
    import httpx

    gesehen = []

    def behandeln(anfrage):
        gesehen.append(anfrage)
        return httpx.Response(200, json={"ok": True})

    _mit_transport(monkeypatch, behandeln)
    assert musik.gesundheit().ok is True
    assert "X-Broker-Secret" not in gesehen[0].headers


def test_datei_streamt_blockweise_und_schliesst(mit_geheimnis, monkeypatch):
    import httpx

    def behandeln(anfrage):
        assert anfrage.headers["X-Broker-Secret"] == "abc123"
        return httpx.Response(200, content=b"ID3" + b"x" * 200_000,
                              headers={"content-type": "audio/mpeg"})

    _mit_transport(monkeypatch, behandeln)
    code, art, laenge, stuecke = musik.datei("a1b2")
    assert (code, art) == (200, "audio/mpeg")
    assert len(b"".join(stuecke)) == 200_003


def test_fassungen_als_liste_oder_woerterbuch():
    als_liste = musik.fassungen({"fassungen": [
        {"name": "klein", "sekunden_je_minute": 9}, {"name": "xl", "sekunden_je_minute": 20}]})
    als_wb = musik.fassungen({"fassungen": {"klein": 9, "xl": 20}})
    erwartet = [{"name": "xl", "sekunden_je_minute": 20}, {"name": "klein", "sekunden_je_minute": 9}]
    assert als_liste == erwartet
    assert als_wb == erwartet
