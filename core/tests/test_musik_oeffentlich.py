"""Die Musik-KI zum Ausprobieren auf /projekt/: ohne Anmeldung, mit Grenzen.

Hier laeuft kein Netz. Der Baustein core.musik wird per monkeypatch ersetzt;
geprueft werden die Schutzgelaender, die der Server zusagt: Anzahl je
Sitzung und je Adresse, die Sperre bei langer Schlange, die Wortpruefung,
nur eigene Auftraege, ruhige Saetze statt 500, und dass die Landing Page
den Dienst beim Laden gar nicht fragt.
"""

import time

import pytest
from django.core.cache import cache

from core import musik, musik_oeffentlich
from plan import broker

SEITE = "/projekt/"
BASIS = "/projekt/musik/"


@pytest.fixture(autouse=True)
def frisch():
    broker.vergessen()
    cache.clear()
    yield
    broker.vergessen()
    cache.clear()


@pytest.fixture
def ohne_geheimnis(settings, tmp_path):
    settings.SPARK_BROKER_SECRET_DATEI = str(tmp_path / "fehlt")


@pytest.fixture
def mit_geheimnis(settings, tmp_path):
    datei = tmp_path / "spark-broker"
    datei.write_text("abc123\n", encoding="utf-8")
    settings.SPARK_BROKER_SECRET_DATEI = str(datei)


class Attrappe:
    def __init__(self):
        self.aufrufe = []
        self.position = 2
        self.naechste = 0


@pytest.fixture
def dienst(monkeypatch, mit_geheimnis):
    """Ein Musikdienst, der antwortet und jedem Auftrag eine neue Kennung gibt."""
    attrappe = Attrappe()

    def holen(pfad, methode="GET", daten=None, frist=10.0, mit_geheimnis=True):
        attrappe.aufrufe.append((methode, pfad, daten, frist))
        if pfad == "/stile":
            return musik.Antwort(True, 200, {"stile": [
                {"name": "pop", "titel": "Pop", "tags": "pop, bright", "bpm": 110,
                 "tonart": "C major", "takt": "4"},
                {"name": "folk", "tags": "folk, acoustic", "bpm": 90},
                {"name": "rock", "tags": "rock"},
            ]})
        if pfad == "/grenzen":
            return musik.Antwort(True, 200, {"sekunden_max": 240, "verfall_stunden": 8})
        if pfad == "/lied":
            attrappe.naechste += 1
            return musik.Antwort(True, 202, {"auftrag": f"auf{attrappe.naechste}",
                                             "zustand": "wartet",
                                             "position": attrappe.position,
                                             "wartet_noch_s": 60})
        if pfad.startswith("/auftrag/") and methode == "GET":
            return musik.Antwort(True, 200, {"zustand": "fertig", "position": 0,
                                             "wartet_noch_s": 0, "dauer_s": 9})
        if pfad.startswith("/auftrag/") and methode == "DELETE":
            return musik.Antwort(True, 200, {"entfernt": True, "datei_entfernt": True})
        raise AssertionError(pfad)

    monkeypatch.setattr(musik, "_holen", holen)
    return attrappe


def _lied(client, ip="10.0.0.1", **felder):
    daten = {"stil": "pop", "lyrics": "[verse]\nDie Sonne scheint", "sekunden": "30",
             "sprache": "de"}
    daten.update(felder)
    return client.post(BASIS + "lied/", daten, secure=True, HTTP_X_FORWARDED_FOR=ip)


def _lieder_posts(dienst):
    return [a for a in dienst.aufrufe if a[1] == "/lied"]


# --- Ohne Anmeldung -----------------------------------------------------------

@pytest.mark.django_db
def test_ohne_anmeldung_erreichbar(client, dienst):
    seite = client.get(SEITE, secure=True).content.decode()
    assert 'id="ausprobieren"' in seite
    assert "Ein Lied in einer Minute" in seite
    assert "js/musik_oeffentlich." in seite, "mit Manifest heisst die Datei musik_oeffentlich.<hash>.js"
    assert "nach einer Stunde gelöscht" in seite
    assert "<noscript>" in seite

    stand = client.get(BASIS + "stand/", secure=True)
    assert stand.status_code == 200
    d = stand.json()
    assert d["ok"] is True
    assert [s["name"] for s in d["stile"]] == ["pop", "folk", "rock"]
    assert "[verse]" in d["marken"] and "[chorus]" in d["marken"]
    # Tags und Tempo bleiben im Server.
    assert "tags" not in d["stile"][0]

    antwort = _lied(client)
    assert antwort.status_code == 200, antwort.content
    assert antwort.json()["ok"] is True
    assert "/projekt/musik/auftrag/" in antwort.json()["abfrage"]


@pytest.mark.django_db
def test_rumpf_an_den_dienst(client, dienst):
    _lied(client, sekunden="60", sprache="en", tags="frei erfunden", fassung="xl")
    (_, _, daten, _), = _lieder_posts(dienst)
    assert daten["sekunden"] == 60
    assert daten["sprache"] == "en"
    assert daten["fassung"] == "klein"
    # Tags kommen aus der Stilvorlage, nicht aus dem Browser.
    assert daten["tags"] == "pop, bright"
    assert daten["bpm"] == 110
    assert daten["kennzeichen"].startswith("oeffentlich-")
    wert = daten["kennzeichen"][len("oeffentlich-"):]
    assert len(wert) == 24 and all(z in "0123456789abcdef" for z in wert)
    assert client.session.session_key not in daten["kennzeichen"]


@pytest.mark.django_db
def test_stile_und_grenzen_mit_kurzer_frist_und_zwischengespeichert(client, dienst):
    client.get(BASIS + "stand/", secure=True)
    client.get(BASIS + "stand/", secure=True)
    abrufe = [a for a in dienst.aufrufe if a[1] in ("/stile", "/grenzen")]
    assert len(abrufe) == 2
    assert all(a[3] <= 2.0 for a in abrufe)


# --- Grenzen ------------------------------------------------------------------

@pytest.mark.django_db
def test_hoechstens_drei_je_sitzung(client, dienst):
    for i in range(3):
        # Je eine andere Adresse, damit nur die Sitzungsgrenze greift.
        assert _lied(client, ip=f"10.0.1.{i}").json()["ok"] is True
    antwort = _lied(client, ip="10.0.1.99")
    assert antwort.status_code == 429
    assert "drei Lieder" in antwort.json()["grund"]
    assert len(_lieder_posts(dienst)) == 3


@pytest.mark.django_db
def test_hoechstens_sechs_je_adresse(dienst):
    from django.test import Client

    for _ in range(6):
        # Neue Sitzung je Lied, gleiche Adresse.
        assert _lied(Client(), ip="203.0.113.7, 10.0.0.1").json()["ok"] is True
    antwort = _lied(Client(), ip="203.0.113.7")
    assert antwort.status_code == 429
    assert "sechs Lieder" in antwort.json()["grund"]
    # Eine andere Adresse geht weiter.
    assert _lied(Client(), ip="198.51.100.1").json()["ok"] is True


@pytest.mark.django_db
def test_adresse_nur_als_hmac_gemerkt(client, dienst):
    _lied(client, ip="203.0.113.7")
    schluessel = list(cache._cache.keys())
    assert schluessel
    assert not any("203.0.113.7" in str(k) for k in schluessel)


@pytest.mark.django_db
def test_grenzen_vergehen_nach_einer_stunde(client, dienst, monkeypatch):
    for i in range(3):
        _lied(client, ip=f"10.0.2.{i}")
    jetzt = time.time()
    monkeypatch.setattr(musik_oeffentlich.time, "time", lambda: jetzt + 3601)
    assert _lied(client, ip="10.0.2.9").json()["ok"] is True


@pytest.mark.django_db
def test_lange_schlange_nimmt_nichts_an(client, dienst):
    dienst.position = 6
    antwort = _lied(client)
    assert antwort.status_code == 503
    assert "viele Lieder in Arbeit" in antwort.json()["grund"]
    # Der zu spaet angelegte Auftrag wird gleich zurueckgezogen ...
    assert ("DELETE", "/auftrag/auf1") in [(a[0], a[1]) for a in dienst.aufrufe]
    # ... und eine Weile geht kein neuer Auftrag an den Dienst.
    dienst.position = 1
    assert _lied(client).status_code == 503
    assert len(_lieder_posts(dienst)) == 1
    # Abgelehnte Versuche zaehlen nicht gegen die Grenze je Sitzung.
    cache.delete(musik_oeffentlich.SCHLANGE_SCHLUESSEL)
    assert _lied(client).json()["ok"] is True


@pytest.mark.django_db
def test_fuenf_in_der_schlange_geht_noch(client, dienst):
    dienst.position = 5
    assert _lied(client).json()["ok"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("text", [
    "[verse]\nDu bist ein Arschloch",
    "[chorus]\nso ein Trottel",
    "[verse]\nlet's have sex tonight",
    "[verse]\nAusländer raus",
    "[verse]\nHEIL HITLER",
])
def test_schimpfwort_und_sperrliste_abgelehnt(client, dienst, text):
    antwort = _lied(client, lyrics=text)
    assert antwort.status_code == 400
    assert "anders formulieren" in antwort.json()["grund"]
    assert not _lieder_posts(dienst)


@pytest.mark.django_db
def test_harmloser_text_geht(client, dienst):
    text = "[verse]\nDer Hund ist dick und rund\n[chorus]\nSechs Enten im Teich"
    assert _lied(client, lyrics=text).json()["ok"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("sekunden", ["90", "240", "61", "10", "abc"])
def test_dauer_ueber_60_oder_frei_abgelehnt(client, dienst, sekunden):
    antwort = _lied(client, sekunden=sekunden)
    assert antwort.status_code == 400
    assert not _lieder_posts(dienst)


@pytest.mark.django_db
def test_text_ueber_400_zeichen_abgelehnt(client, dienst):
    antwort = _lied(client, lyrics="la " * 140)
    assert antwort.status_code == 400
    assert not _lieder_posts(dienst)


@pytest.mark.django_db
def test_unbekannter_stil_und_sprache_abgelehnt(client, dienst):
    assert _lied(client, stil="techno").status_code == 400
    assert _lied(client, sprache="fr").status_code == 400
    assert not _lieder_posts(dienst)


# --- Nur eigene Auftraege -----------------------------------------------------

@pytest.mark.django_db
def test_eigener_auftrag_abfragbar(client, dienst):
    d = _lied(client).json()
    stand = client.get(d["abfrage"], secure=True).json()
    assert stand["zustand"] == "fertig"
    assert stand["datei"] == "/projekt/musik/datei/auf1/"


@pytest.mark.django_db
def test_fremde_auftraege_404(client, dienst, monkeypatch):
    from django.test import Client

    d = _lied(client).json()
    fremd = Client()
    assert fremd.get(d["abfrage"], secure=True).status_code == 404
    monkeypatch.setattr(musik, "datei", lambda k: (_ for _ in ()).throw(AssertionError(k)))
    assert fremd.get(d["datei"], secure=True).status_code == 404
    assert client.get(BASIS + "auftrag/gibtsnicht/", secure=True).status_code == 404
    assert client.get(BASIS + "auftrag/..%2Fx/", secure=True).status_code == 404


@pytest.mark.django_db
def test_datei_wird_durchgereicht(client, dienst, monkeypatch):
    d = _lied(client).json()
    monkeypatch.setattr(musik, "datei", lambda k: (200, "audio/mpeg", "3", iter([b"abc"])))
    antwort = client.get(d["datei"], secure=True)
    assert antwort.status_code == 200
    assert b"".join(antwort.streaming_content) == b"abc"
    assert antwort["Cache-Control"] == "private, no-store"


@pytest.mark.django_db
def test_nach_einer_stunde_geloescht(client, dienst, monkeypatch):
    d = _lied(client).json()
    jetzt = time.time()
    monkeypatch.setattr(musik_oeffentlich.time, "time", lambda: jetzt + 3601)
    # Der naechste Aufruf (hier: die Seite holt den Stand) raeumt auf ...
    client.get(BASIS + "stand/", secure=True)
    assert ("DELETE", "/auftrag/auf1") in [(a[0], a[1]) for a in dienst.aufrufe]
    assert not cache.get(musik_oeffentlich.REGISTER_SCHLUESSEL)
    # ... und das Lied ist auch fuer die eigene Sitzung weg.
    assert client.get(d["abfrage"], secure=True).status_code == 404


@pytest.mark.django_db
def test_aufraeumen_auch_fuer_fremde_sitzungen(dienst, monkeypatch):
    from django.test import Client

    _lied(Client(), ip="10.0.3.1")
    jetzt = time.time()
    monkeypatch.setattr(musik_oeffentlich.time, "time", lambda: jetzt + 3601)
    Client().get(BASIS + "stand/", secure=True)
    assert ("DELETE", "/auftrag/auf1") in [(a[0], a[1]) for a in dienst.aufrufe]


# --- Ruhige Fehler, die Landing Page wartet nie -----------------------------

def test_geheimnis_fehlt_seite_200_mit_hinweis(client, ohne_geheimnis, monkeypatch):
    def kein_netz(*a, **k):
        raise AssertionError("Unerwarteter Netzaufruf")
    monkeypatch.setattr(musik.httpx, "Client", kein_netz)

    antwort = client.get(SEITE, secure=True)
    seite = antwort.content.decode()
    assert antwort.status_code == 200
    assert "Die Musik-KI ist gerade nicht verbunden." in seite
    assert 'id="musik-oe"' not in seite
    # Der Rest der Seite steht unveraendert.
    assert 'id="impressum"' in seite and "Die Serie" in seite


@pytest.mark.django_db
def test_geheimnis_fehlt_stand_und_lied_ruhig(client, ohne_geheimnis):
    assert client.get(BASIS + "stand/", secure=True).json() == {
        "ok": False, "satz": "Die Musik-KI ist gerade nicht verbunden."}
    antwort = _lied(client)
    assert antwort.status_code == 503
    assert antwort.json()["grund"] == "Die Musik-KI ist gerade nicht verbunden."


@pytest.mark.django_db
def test_dienst_antwortet_nicht_kein_500(client, mit_geheimnis, monkeypatch):
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
    stand = client.get(BASIS + "stand/", secure=True)
    assert stand.status_code == 200 and stand.json()["ok"] is False
    # Danach weiss die Seite es ohne Netz und sagt es gleich.
    seite = client.get(SEITE, secure=True).content.decode()
    assert "Die Musik-KI ist gerade nicht verbunden." in seite
    assert _lied(client).status_code == 503


def test_landing_page_ruft_den_dienst_nicht(client, mit_geheimnis, monkeypatch):
    """Mit Geheimnis und ohne Zwischenspeicher: Die Seite fragt trotzdem
    nicht, sondern ueberlaesst das dem Skript. Jeder Aufruf faellt auf."""
    def kein_aufruf(*a, **k):
        raise AssertionError("Die Landing Page hat den Musikdienst gefragt")
    monkeypatch.setattr(musik, "_holen", kein_aufruf)
    monkeypatch.setattr(musik, "datei", kein_aufruf)
    monkeypatch.setattr(musik.httpx, "Client", kein_aufruf)

    antwort = client.get(SEITE, secure=True)
    seite = antwort.content.decode()
    assert antwort.status_code == 200
    assert 'id="musik-oe"' in seite
    assert 'data-stand="/projekt/musik/stand/"' in seite


def test_kein_emoji_im_abschnitt_und_skript(client, mit_geheimnis):
    from pathlib import Path

    from django.conf import settings

    seite = client.get(SEITE, secure=True).content.decode()
    skript = (Path(settings.BASE_DIR) / "static/js/musik_oeffentlich.js").read_text(encoding="utf-8")
    modul = Path(musik_oeffentlich.__file__).read_text(encoding="utf-8")
    for quelle in (seite, skript, modul):
        verboten = sorted({
            f"U+{ord(z):04X}" for z in quelle
            if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF
        })
        assert not verboten, verboten
        assert chr(0x2014) not in quelle


def test_ankerlink_zum_teilen(client, mit_geheimnis):
    seite = client.get(SEITE, secure=True).content.decode()
    assert 'id="ausprobieren"' in seite
    assert 'href="#ausprobieren"' in seite
    # Ganz unten: nach allen anderen Abschnitten, vor dem Impressum.
    assert seite.index('id="mitmachen"') < seite.index('id="ausprobieren"') < seite.index('id="impressum"')


# --- Der Fortschrittsbalken ----------------------------------------------------

@pytest.mark.django_db
def test_lied_und_stand_tragen_die_erwartung_fuer_den_balken(client, dienst):
    """Der Balken (musik_oeffentlich.js) braucht die Rechenzeit des eigenen
    Liedes als Erfahrungswert; sie reist beim Anlegen und bei jeder Abfrage
    mit. Die Attrappe nennt zum fertigen Auftrag keine Laenge, also wird
    hier nichts nachgefuehrt - und nichts darf dabei kaputtgehen."""
    from pathlib import Path

    from django.conf import settings

    from core import musik_zeit

    musik_zeit.vergessen()
    angelegt = _lied(client).json()
    assert angelegt["erwartung_s"] == pytest.approx(musik_zeit.erwartung(30, "klein"), abs=0.05)

    stand = client.get(angelegt["abfrage"], secure=True).json()
    assert stand["zustand"] == "fertig"
    assert stand["erwartung_s"] == pytest.approx(musik_zeit.erwartung(60, "klein"), abs=0.05)
    assert musik_zeit.erwartung(60, "klein") == pytest.approx(10.1, abs=0.05)
    # Der alte Satz als Code (", noch etwa " + dauerText(...)) ist weg; im
    # Kommentar darf er als Zitat von Thomas stehen bleiben.
    skript = (Path(settings.BASE_DIR) / "static/js/musik_oeffentlich.js").read_text(encoding="utf-8")
    assert '", noch etwa "' not in skript
    assert "musik-balken" in skript
