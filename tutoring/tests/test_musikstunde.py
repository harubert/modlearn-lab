"""Die Musikstunde: fuenftes Fach, vierte Betriebsart.

Hier laeuft kein Netz. Der Musikdienst (core.musik._holen), die Einstufung
durch das Sprachmodell (pruefung.einstufen) und das Sprachmodell fuer den
Textvorschlag (musik_views.antwort_holen_sync) werden per monkeypatch
ersetzt. Geprueft wird, was der Server zusagt: Die Lehrperson setzt die
Grenzen, der Server setzt sie durch, ein Kind sieht nur seine eigenen
Lieder, die Lehrperson nur die ihrer Sitzung, und beim Beenden und beim
Verfall wird am Spark geloescht und das Ergebnis ausgewertet.

Seit 19.10.2026 dazu: Stile aus dem Katalog (tutoring/musikstile.py) plus
die Vorlagen des Dienstes, das freie Stilfeld, das serverseitig geprueft und
in die Tags gebaut wird, und der Textvorschlag vom Spark mit Sperre, Zaehler
und Schalter der Lehrperson.

Dazu der Test, dass nirgends mehr ein Emoji steht (Thomas, 12.10.2026).
"""

import logging
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import musik
from plan import broker
from tutoring import musik_views, musikstile, musikstunde, pruefung
from tutoring.models import LearningSession, Lied, Participation, verfallene_aufraeumen
from tutoring.spark import SparkNichtErreichbar

pytestmark = pytest.mark.django_db


# --- Attrappen ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def frisch():
    broker.vergessen()
    cache.clear()
    yield
    broker.vergessen()
    cache.clear()


@pytest.fixture(autouse=True)
def ohne_modell(monkeypatch):
    """Die Ampel ohne Spark: gruen, ausser es steht "Hausaufgaben" drin."""
    def einstufen(text):
        if "Hausaufgaben" in (text or ""):
            return pruefung.ORANGE, "abwertend"
        return pruefung.GRUEN, ""
    monkeypatch.setattr(pruefung, "einstufen", einstufen)


@pytest.fixture
def mit_geheimnis(settings, tmp_path):
    datei = tmp_path / "spark-broker"
    datei.write_text("abc123\n", encoding="utf-8")
    settings.SPARK_BROKER_SECRET_DATEI = str(datei)


class Attrappe:
    def __init__(self):
        self.aufrufe = []
        self.naechste = 0
        self.loeschen = {"entfernt": 2, "datei_entfernt": 2}
        self.loeschen_code = 200
        self.grenzen = {"sekunden_max": 240, "verfall_stunden": 8, "tags_max": 600}


@pytest.fixture
def dienst(monkeypatch, mit_geheimnis):
    """Ein Musikdienst, der antwortet und jedem Auftrag eine neue Kennung gibt."""
    attrappe = Attrappe()

    def holen(pfad, methode="GET", daten=None, frist=10.0, mit_geheimnis=True):
        attrappe.aufrufe.append((methode, pfad, daten))
        if pfad == "/stile":
            return musik.Antwort(True, 200, {"stile": [
                {"name": "pop", "titel": "Pop", "tags": "pop, bright", "bpm": 110,
                 "tonart": "C major", "takt": "4"},
                {"name": "folk", "tags": "folk, acoustic", "bpm": 90},
            ]})
        if pfad == "/grenzen":
            return musik.Antwort(True, 200, attrappe.grenzen)
        if pfad == "/lied":
            attrappe.naechste += 1
            return musik.Antwort(True, 202, {"auftrag": f"lied{attrappe.naechste}",
                                             "zustand": "wartet", "position": 3,
                                             "wartet_noch_s": 40})
        if pfad.startswith("/auftrag/") and methode == "GET":
            return musik.Antwort(True, 200, {"zustand": "fertig", "position": 0,
                                             "wartet_noch_s": 0, "dauer_s": 9})
        if pfad.startswith("/auftraege?") and methode == "DELETE":
            ok = 200 <= attrappe.loeschen_code < 300
            return musik.Antwort(ok, attrappe.loeschen_code, attrappe.loeschen,
                                 "" if ok else "Der Musikdienst antwortet 503.")
        raise AssertionError((methode, pfad))

    monkeypatch.setattr(musik, "_holen", holen)
    return attrappe


class Spark:
    """Das Sprachmodell fuer den Textvorschlag: merkt sich die Prompts."""

    def __init__(self):
        self.aufrufe = []
        self.antwort = ("[Strophe 1]\nWir gehen jeden Tag zur Schule,\n"
                        "mit dem Rad und ohne Stuhle.\n\n"
                        "Refrain:\nSchulweg, Schulweg, du bist fein,\n"
                        "wir gehn nie allein.")
        self.kaputt = False

    def __call__(self, system, text, max_tokens=700):
        self.aufrufe.append((system, text, max_tokens))
        if self.kaputt:
            raise SparkNichtErreichbar("aus")
        return self.antwort, {"modell": "attrappe", "tokens_ein": 1, "tokens_aus": 1,
                              "dauer_ms": 1}


@pytest.fixture
def spark(monkeypatch):
    attrappe = Spark()
    monkeypatch.setattr(musik_views, "antwort_holen_sync", attrappe)
    return attrappe


def _lied_posts(dienst):
    return [a for a in dienst.aufrufe if a[1] == "/lied"]


def _loesch_aufrufe(dienst):
    return [a for a in dienst.aufrufe if a[0] == "DELETE"]


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


@pytest.fixture
def musikstunde_(lehrperson):
    return LearningSession.objects.create(
        title="Musik 3a", teacher=lehrperson, mode=LearningSession.BETRIEB_MUSIK,
        subject="musik", task_hint="Ein Lied über unseren Schulweg",
        song_max_seconds=90, songs_per_child=2, song_language="en",
    )


def _beitreten(client, sitzung, tier="fuchs"):
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": tier}, secure=True)
    return Participation.objects.get(learning_session=sitzung, animal=tier)


@pytest.fixture
def kind(client, musikstunde_):
    return _beitreten(client, musikstunde_)


def _lied(client, **felder):
    daten = {"stil": "pop", "lyrics": "[verse]\nWir gehen jeden Tag zur Schule",
             "sekunden": "60"}
    daten.update(felder)
    return client.post(reverse("tutoring:musik_lied"), daten, secure=True)


def _text(client, **felder):
    daten = {"thema": "unser Schulweg", "sekunden": "60"}
    daten.update(felder)
    return client.post(reverse("tutoring:musik_text"), daten, secure=True)


# --- Anlegen ------------------------------------------------------------------

def test_anlegen_mit_fach_musik_setzt_betriebsart_und_felder(client, lehrperson):
    client.force_login(lehrperson)

    antwort = client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "musik", "title": "Musik 4b", "task_hint": "Unser Schulweg",
        "song_max_seconds": "120", "songs_per_child": "5", "song_language": "en",
        "song_text_help": "ja",
        # Gibt es in der Musikstunde nicht und darf auch nicht hineingeraten.
        "qualitaetssicherung": "ja", "umfang": "loesung",
    }, secure=True)

    assert antwort.status_code == 302
    sitzung = LearningSession.objects.get(title="Musik 4b")
    assert sitzung.mode == LearningSession.BETRIEB_MUSIK
    assert sitzung.ist_musik
    assert sitzung.subject == "musik"
    assert sitzung.task_hint == "Unser Schulweg"
    assert sitzung.song_max_seconds == 120
    assert sitzung.songs_per_child == 5
    assert sitzung.song_language == "en"
    assert sitzung.song_text_help is True
    assert sitzung.cloud_enabled is False
    assert sitzung.fach_symbol == "note"


def test_unbekannte_musikwerte_fallen_auf_die_vorgabe(client, lehrperson):
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "musik", "title": "Musik 4c",
        "song_max_seconds": "240", "songs_per_child": "9", "song_language": "fr",
    }, secure=True)

    sitzung = LearningSession.objects.get(title="Musik 4c")
    assert sitzung.song_max_seconds == 60
    assert sitzung.songs_per_child == 3
    assert sitzung.song_language == "de"
    # Ein Kontrollkaestchen, das im Musikformular fehlt, ist abgewaehlt.
    assert sitzung.song_text_help is False


def test_andere_faecher_nehmen_die_musikfelder_nicht_an(client, lehrperson):
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "mathematik", "title": "Mathe", "schulstufe": "vs",
        "song_max_seconds": "120", "songs_per_child": "5", "song_language": "en",
    }, secure=True)

    sitzung = LearningSession.objects.get(title="Mathe")
    assert sitzung.song_max_seconds == 60
    assert sitzung.songs_per_child == 3
    assert sitzung.song_language == "de"
    # Nicht abgewaehlt, sondern gar nicht gelesen: Es bleibt die Vorgabe.
    assert sitzung.song_text_help is True


def test_die_fachseite_zeigt_musik_mit_erklaerung(client, lehrperson):
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_uebersicht") + "?fach=musik",
                       secure=True).content.decode()

    assert 'name="song_max_seconds"' in seite
    assert 'name="songs_per_child"' in seite
    assert 'name="song_language"' in seite
    assert 'name="song_text_help"' in seite
    assert 'name="qualitaetssicherung"' not in seite
    assert "ACE-Step" in seite and "MIT" in seite
    assert "einige Minuten" in seite
    assert "gelöscht" in seite
    assert "Vorschlag" in seite and "Kinderlied" in seite

    mathe = client.get(reverse("tutoring:lehrperson_uebersicht") + "?fach=mathematik",
                       secure=True).content.decode()
    assert 'name="song_text_help"' not in mathe


# --- Die Seite des Kindes ------------------------------------------------------

def test_kind_landet_auf_der_musikseite(client, kind, musikstunde_):
    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:musik")


def test_musikseite_zeigt_thema_dauern_und_die_zwei_wege(client, kind, dienst):
    seite = client.get(reverse("tutoring:musik"), secure=True).content.decode()

    assert "Ein Lied über unseren Schulweg" in seite
    assert 'id="musik-kind"' in seite
    assert 'value="30"' in seite and 'value="60"' in seite and 'value="90"' in seite
    assert 'name="sekunden" value="120"' not in seite
    assert "js/musik_oeffentlich." in seite
    # Die zwei Wege zum Text, das Thema vorbelegt, das freie Stilfeld.
    assert 'name="textweg"' in seite
    assert 'data-text="' + reverse("tutoring:musik_text") in seite
    assert 'value="Ein Lied über unseren Schulweg"' in seite
    assert 'name="eigener_stil"' in seite and 'maxlength="200"' in seite
    # Die Reihenfolge: Text, Stil, Dauer, Knopf.
    assert seite.index("Dein Text") < seite.index(">Stil<") < seite.index(">Dauer<") \
        < seite.index("Lied machen")


def test_stand_liefert_katalog_in_gruppen_plus_dienst_ohne_dubletten(client, kind, dienst):
    stand = client.get(reverse("tutoring:musik_stand"), secure=True).json()

    assert stand["ok"] is True
    namen = [s["name"] for s in stand["stile"]]
    assert len(namen) >= 26
    assert namen.count("pop") == 1, "die Vorlage pop des Dienstes nicht doppelt"
    assert "folk" in namen and "kinderlied" in namen
    assert namen[-1] == "eigen"
    folk = next(s for s in stand["stile"] if s["name"] == "folk")
    assert folk["gruppe"] == musikstile.DIENST
    assert stand["gruppen"][0] == musikstile.KINDER
    assert stand["gruppen"][-1] == musikstile.EIGENER
    # Tags, Tempo und Tonart bleiben im Server.
    assert "tags" not in stand["stile"][0]
    # Klein, wie der Lyrics-Tokenizer sie kennt.
    assert "[verse]" in stand["marken"]
    assert all(m == m.lower() for m in stand["marken"])


def test_ohne_texthilfe_gibt_es_den_weg_nicht(client, kind, dienst, musikstunde_):
    LearningSession.objects.filter(pk=musikstunde_.pk).update(song_text_help=False)

    seite = client.get(reverse("tutoring:musik"), secure=True).content.decode()

    assert 'name="textweg"' not in seite
    assert "data-text=" not in seite
    assert 'id="musik-kind-text"' in seite


def test_andere_betriebsarten_fuehren_nicht_auf_die_musikseite(client, lehrperson):
    sitzung = LearningSession.objects.create(title="Mathe", teacher=lehrperson)
    _beitreten(client, sitzung)

    antwort = client.get(reverse("tutoring:musik"), secure=True)

    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:chat")


# --- Lieder anlegen -------------------------------------------------------------

def test_lied_anlegen_ruft_den_dienst_mit_dem_kennzeichen_der_sitzung(client, kind, dienst,
                                                                      musikstunde_):
    antwort = _lied(client, sekunden="90", sprache="de", fassung="xl", tags="erfunden")

    assert antwort.status_code == 200, antwort.content
    d = antwort.json()
    assert d["ok"] is True
    assert d["position"] == 3
    assert d["abfrage"] == reverse("tutoring:musik_auftrag", args=["lied1"])

    (_, _, daten), = _lied_posts(dienst)
    assert daten["kennzeichen"] == musikstunde_.log_key
    assert daten["sekunden"] == 90
    # Sprache und Fassung setzt der Server, nicht der Browser.
    assert daten["sprache"] == "en"
    assert daten["fassung"] == "klein"
    # Die Tags kommen aus dem Katalog, englisch, mit der Gesangssprache;
    # "erfunden" aus dem Browser ist nicht darin.
    pop = musikstile.finden(musikstile.katalog(), "pop")
    assert daten["tags"] == pop["tags"] + ", English vocals"
    assert daten["bpm"] == pop["bpm"] and daten["tonart"] == pop["tonart"]
    assert "erfunden" not in daten["tags"]

    lied = Lied.objects.get()
    assert lied.participation == kind
    assert lied.auftrag == "lied1"
    assert lied.sekunden == 90
    assert lied.sprache == "en"
    assert lied.stil == "Pop"
    assert "Schule" in lied.text


def test_vorlage_des_dienstes_bleibt_nutzbar(client, kind, dienst):
    antwort = _lied(client, stil="folk")

    assert antwort.status_code == 200, antwort.content
    (_, _, daten), = _lied_posts(dienst)
    assert daten["tags"] == "folk, acoustic, English vocals"
    assert daten["bpm"] == 90


def test_freier_stil_wird_geprueft_begrenzt_und_angehaengt(client, kind, dienst):
    antwort = _lied(client, eigener_stil="  Piratenlied\nmit   Akkordeon und Möwen ")

    assert antwort.status_code == 200, antwort.content
    (_, _, daten), = _lied_posts(dienst)
    pop = musikstile.finden(musikstile.katalog(), "pop")
    assert daten["tags"] == pop["tags"] + ", Piratenlied mit Akkordeon und Möwen, English vocals"
    assert Lied.objects.get().stil == "Pop + Piratenlied mit Akkordeon und Möwen"


def test_freier_stil_allein(client, kind, dienst):
    antwort = _lied(client, stil="eigen", eigener_stil="Piratenlied mit Akkordeon")

    assert antwort.status_code == 200, antwort.content
    (_, _, daten), = _lied_posts(dienst)
    assert daten["tags"] == "Piratenlied mit Akkordeon, English vocals"
    assert "bpm" not in daten and "tonart" not in daten
    assert Lied.objects.get().stil == "Eigener Stil: Piratenlied mit Akkordeon"


def test_freier_stil_ohne_text_wird_abgelehnt(client, kind, dienst):
    antwort = _lied(client, stil="eigen", eigener_stil="   ")

    assert antwort.status_code == 400
    assert "eigenen Stil" in antwort.json()["grund"]
    assert _lied_posts(dienst) == []


def test_freier_stil_mit_schimpfwort_macht_die_ampel_rot(client, kind, dienst):
    antwort = _lied(client, eigener_stil="Rap für Trottel")

    assert antwort.status_code == 400
    assert "Stilbeschreibung" in antwort.json()["grund"]
    assert _lied_posts(dienst) == []
    assert not Lied.objects.exists()
    kind.refresh_from_db()
    assert kind.worst_flag == pruefung.ROT


def test_freier_stil_geht_mit_in_die_ampel(client, kind, dienst):
    antwort = _lied(client, eigener_stil="Hausaufgaben-Rap")

    assert antwort.status_code == 200
    assert Lied.objects.get().flag == pruefung.ORANGE


def test_freier_stil_wird_auf_tags_max_des_dienstes_begrenzt(client, kind, dienst):
    dienst.grenzen["tags_max"] = 140

    antwort = _lied(client, eigener_stil="z" * 400)

    assert antwort.status_code == 200, antwort.content
    (_, _, daten), = _lied_posts(dienst)
    assert len(daten["tags"]) <= 140
    assert daten["tags"].endswith("English vocals")


def test_ohne_text_keine_gesangssprache(client, kind, dienst):
    antwort = _lied(client, stil="instrumental", lyrics="")

    assert antwort.status_code == 200, antwort.content
    (_, _, daten), = _lied_posts(dienst)
    assert "English vocals" not in daten["tags"]
    assert "lyrics" not in daten


def test_dauer_ueber_der_grenze_der_lehrperson_geht_nicht_hinaus(client, kind, dienst):
    antwort = _lied(client, sekunden="120")

    assert antwort.status_code == 400
    assert "90" in antwort.json()["grund"]
    assert _lied_posts(dienst) == []
    assert not Lied.objects.exists()


def test_grenze_lieder_je_kind(client, kind, dienst):
    assert _lied(client).status_code == 200
    assert _lied(client).status_code == 200

    dritte = _lied(client)

    assert dritte.status_code == 429
    assert "2 Lieder" in dritte.json()["grund"]
    assert len(_lied_posts(dienst)) == 2
    assert kind.lieder.count() == 2


def test_ein_misslungenes_lied_zaehlt_nicht(client, kind, dienst):
    _lied(client)
    _lied(client)
    Lied.objects.filter(auftrag="lied1").update(zustand=Lied.FEHLER)

    assert _lied(client).status_code == 200


@pytest.mark.parametrize("text", [
    "[verse]\nDu bist ein Arschloch",      # deterministischer Boden
    "[chorus]\nsieg heil",                 # Sperrliste der Probierecke
])
def test_schimpfwort_wird_abgelehnt_und_die_ampel_rot(client, kind, dienst, text):
    antwort = _lied(client, lyrics=text)

    assert antwort.status_code == 400
    assert "nicht vertont" in antwort.json()["grund"]
    assert _lied_posts(dienst) == []
    assert not Lied.objects.exists()
    kind.refresh_from_db()
    assert kind.worst_flag == pruefung.ROT


def test_das_modell_faerbt_die_ampel_blockiert_aber_nicht(client, kind, dienst):
    antwort = _lied(client, lyrics="[verse]\nHausaufgaben sind doof")

    assert antwort.status_code == 200
    lied = Lied.objects.get()
    assert lied.flag == pruefung.ORANGE
    assert lied.flag_reason == "abwertend"
    kind.refresh_from_db()
    assert kind.worst_flag == pruefung.ORANGE


def test_stand_und_datei_des_eigenen_liedes(client, kind, dienst, monkeypatch):
    _lied(client)
    monkeypatch.setattr(musik, "datei", lambda kennung: (200, "audio/mpeg", "3", iter([b"mp3"])))

    stand = client.get(reverse("tutoring:musik_auftrag", args=["lied1"]), secure=True).json()
    assert stand["zustand"] == "fertig"
    assert stand["datei"] == reverse("tutoring:musik_datei", args=["lied1"])
    assert Lied.objects.get().zustand == Lied.FERTIG

    datei = client.get(stand["datei"], secure=True)
    assert datei.status_code == 200
    assert b"".join(datei.streaming_content) == b"mp3"

    liste = client.get(reverse("tutoring:musik_liste"), secure=True).content.decode()
    assert "<audio" in liste
    assert "noch 1 von 2" in liste


# --- Der Textvorschlag vom Spark ------------------------------------------------

def test_textvorschlag_kommt_bereinigt_in_der_gesangssprache(client, kind, dienst, spark):
    antwort = _text(client, thema="unser Schulweg im Herbst", sekunden="90")

    assert antwort.status_code == 200, antwort.content
    d = antwort.json()
    assert d["ok"] is True
    assert d["noch"] == musikstunde.TEXTHILFE_HOECHSTENS - 1
    # Marken klein und englisch, auf eigenen Zeilen, "Refrain:" uebersetzt.
    assert d["text"].startswith("[verse]\n")
    assert "\n\n[chorus]\n" in d["text"]
    assert "Strophe" not in d["text"] and "Refrain" not in d["text"]

    (system, frage, _), = spark.aufrufe
    assert "unser Schulweg im Herbst" in frage
    assert "Englisch" in system                       # Gesangssprache der Sitzung
    assert "sechs bis zehn" in system                 # Altersklasse der Sitzung
    assert "sechs Blöcke" in system                   # 90 Sekunden
    assert "[verse]" in system and "[chorus]" in system
    assert "echten Menschen" in system
    assert str(musikstunde.TEXT_MAX) in system
    # Nichts wird dabei vertont oder gespeichert.
    assert _lied_posts(dienst) == []
    assert not Lied.objects.exists()


def test_textvorschlag_ohne_thema_nimmt_das_thema_der_stunde(client, kind, dienst, spark):
    antwort = _text(client, thema="  ")

    assert antwort.status_code == 200, antwort.content
    assert "Ein Lied über unseren Schulweg" in spark.aufrufe[0][1]


def test_textvorschlag_ohne_jedes_thema_fragt_nach(client, kind, dienst, spark, musikstunde_):
    LearningSession.objects.filter(pk=musikstunde_.pk).update(task_hint="")

    antwort = _text(client, thema="")

    assert antwort.status_code == 400
    assert "Worum" in antwort.json()["grund"]
    assert spark.aufrufe == []


def test_textvorschlag_zaehlt_hoechstens_sechs_je_teilnahme(client, kind, dienst, spark):
    for erwartet in range(musikstunde.TEXTHILFE_HOECHSTENS - 1, -1, -1):
        d = _text(client).json()
        assert d["ok"] is True and d["noch"] == erwartet

    siebter = _text(client)

    assert siebter.status_code == 429
    assert siebter.json()["noch"] == 0
    assert len(spark.aufrufe) == musikstunde.TEXTHILFE_HOECHSTENS
    # Ein anderes Kind im selben Browser? Nein: eine andere Teilnahme in einem
    # anderen Browser zaehlt fuer sich.
    anderes = Client()
    _beitreten(anderes, kind.learning_session, tier="biber")
    assert anderes.post(reverse("tutoring:musik_text"),
                        {"thema": "x", "sekunden": "30"}, secure=True).json()["ok"] is True


def test_gesperrter_vorschlag_wird_nicht_gezeigt_und_faerbt_nichts(client, kind, dienst, spark):
    spark.antwort = "[verse]\nDer Lehrer ist ein Trottel"

    antwort = _text(client)

    assert antwort.status_code == 200
    d = antwort.json()
    assert d["ok"] is False
    assert "Trottel" not in antwort.content.decode()
    assert "noch einmal" in d["grund"]
    # Gezaehlt wird trotzdem, die Rechenzeit ist verbraucht ...
    assert d["noch"] == musikstunde.TEXTHILFE_HOECHSTENS - 1
    # ... aber die Ampel bleibt, wie sie war: Das Kind hat nichts getan.
    kind.refresh_from_db()
    assert kind.worst_flag != pruefung.ROT


def test_thema_mit_schimpfwort_wird_abgelehnt_und_die_ampel_rot(client, kind, dienst, spark):
    antwort = _text(client, thema="mein Lehrer ist ein Trottel")

    assert antwort.status_code == 400
    assert spark.aufrufe == []
    kind.refresh_from_db()
    assert kind.worst_flag == pruefung.ROT


def test_textvorschlag_403_wenn_die_lehrperson_ihn_abgeschaltet_hat(client, kind, dienst, spark,
                                                                   musikstunde_):
    LearningSession.objects.filter(pk=musikstunde_.pk).update(song_text_help=False)

    antwort = _text(client)

    assert antwort.status_code == 403
    assert antwort.json()["noch"] == 0
    assert spark.aufrufe == []


def test_textvorschlag_haelt_sich_an_die_dauer_der_lehrperson(client, kind, dienst, spark):
    antwort = _text(client, sekunden="120")

    assert antwort.status_code == 400
    assert spark.aufrufe == []


def test_textvorschlag_ohne_spark_ruhig_und_ungezaehlt(client, kind, dienst, spark):
    spark.kaputt = True

    antwort = _text(client)

    assert antwort.status_code == 503
    assert "Spark" in antwort.json()["grund"]
    spark.kaputt = False
    assert _text(client).json()["noch"] == musikstunde.TEXTHILFE_HOECHSTENS - 1


def test_textvorschlag_ohne_teilnahme_403(client, dienst, spark):
    assert _text(client).status_code == 403


# --- Prompt und Aufraeumen des Vorschlags (ohne Netz) -------------------------

def test_textprompt_nach_dauer_sprache_und_alter():
    system, frage = musikstunde.textprompt("de", "10-14", 30, "der Wald")
    assert "zwei Blöcke" in system and "zehn und vierzehn" in system
    assert "Deutsch" in system and "320 Zeichen" in system
    assert frage.endswith("der Wald")
    system, _ = musikstunde.textprompt("en", "erwachsen", 60, "x")
    assert "vier Blöcke" in system and "Englisch" in system and "560 Zeichen" in system
    system, _ = musikstunde.textprompt("de", "6-10", 120, "x")
    assert "sechs Blöcke" in system and "[bridge]" in system
    assert f"{musikstunde.TEXT_MAX} Zeichen" in system
    # Unbekannte Werte fallen auf das Kuerzeste und die Vorgabe zurueck.
    system, _ = musikstunde.textprompt("fr", "", None, "x")
    assert "zwei Blöcke" in system and "Deutsch" in system
    assert musikstunde.zeichen_grenze(30) == 320
    assert musikstunde.zeichen_grenze(75) == 560
    assert musikstunde.zeichen_grenze(120) == musikstunde.TEXT_MAX


def test_vorschlag_wird_nach_der_dauer_am_blockende_geschnitten(client, kind, dienst, spark):
    block = "[verse]\n" + "\n".join("Zeile %d mit ein paar Wörtern" % i for i in range(4))
    refrain = "[chorus]\n" + "\n".join("Refrainzeile %d, die wir singen" % i for i in range(4))
    spark.antwort = "\n\n".join([block, refrain, block, refrain, block, refrain])

    d = _text(client, sekunden="30").json()

    assert d["ok"] is True
    assert len(d["text"]) <= 320
    # Ganze Bloecke, kein halber Refrain.
    assert d["text"].count("[verse]") == 1 and d["text"].count("[chorus]") == 1
    assert d["text"].endswith("Refrainzeile 3, die wir singen")


MARKEN = ["[intro]", "[verse]", "[pre-chorus]", "[chorus]", "[hook]", "[bridge]",
          "[break]", "[inst]", "[solo]", "[outro]"]


def test_text_bereinigen_uebersetzt_marken_und_raeumt_auf():
    roh = ("<think>Ich ueberlege.</think>\n"
           "Titel: Der Schulweg\n"
           "```\n"
           "**[Strophe 1]**\n"
           "Zeile eins\n"
           "Zeile zwei\n"
           "\n\n\n"
           "Refrain:\n"
           "La la la\n"
           "[Chorus]\n"
           "[x2]\n"
           "Brücke:\n"
           "Kurz\n"
           "## Outro\n"
           "Tschüss\n"
           "```\n")
    text = musikstunde.text_bereinigen(roh, MARKEN)
    assert text == ("[verse]\nZeile eins\nZeile zwei\n\n[chorus]\nLa la la\n\n[chorus]\n\n"
                    "[bridge]\nKurz\n\n[outro]\nTschüss")


def test_text_bereinigen_laesst_gewoehnliche_zeilen_in_ruhe():
    # "Anmerkung:" allein ist eine Ueberschrift und faellt weg; "Achtung: hier"
    # ist eine Liedzeile und bleibt, "Hallo" allein auch.
    roh = "Hallo\nAnmerkung:\nAchtung: hier\nWir singen laut\n[verse]\nnoch was"
    text = musikstunde.text_bereinigen(roh, MARKEN)
    assert text == "Hallo\nAchtung: hier\nWir singen laut\n\n[verse]\nnoch was"
    # Eine Marke, die der Dienst nicht kennt, faellt weg.
    assert musikstunde.text_bereinigen("[verse]\nA\n[bridge]\nB", ["[verse]"]) == "[verse]\nA\nB"


def test_text_bereinigen_kuerzt_an_einem_zeilenende():
    roh = "[verse]\n" + "\n".join("Zeile Nummer %d hier" % i for i in range(200))
    text = musikstunde.text_bereinigen(roh, MARKEN)
    assert len(text) <= musikstunde.TEXT_MAX
    assert text.endswith("hier")
    # Eine kleinere Grenze gilt, eine groessere als TEXT_MAX nicht.
    assert len(musikstunde.text_bereinigen(roh, MARKEN, 100)) <= 100
    assert len(musikstunde.text_bereinigen(roh, MARKEN, 5000)) <= musikstunde.TEXT_MAX
    assert musikstunde.text_bereinigen("", MARKEN) == ""
    assert musikstunde.text_bereinigen(None, MARKEN) == ""


# --- Fremde Lieder ----------------------------------------------------------------

def test_fremde_lieder_gibt_es_nicht(client, kind, dienst, musikstunde_, monkeypatch):
    _lied(client)
    monkeypatch.setattr(musik, "datei", lambda kennung: (200, "audio/mpeg", "3", iter([b"mp3"])))

    anderes = Client()
    _beitreten(anderes, musikstunde_, tier="biber")
    for name in ("tutoring:musik_auftrag", "tutoring:musik_datei"):
        assert anderes.get(reverse(name, args=["lied1"]), secure=True).status_code == 404

    # Ohne Teilnahme ebenso.
    fremd = Client()
    assert fremd.get(reverse("tutoring:musik_datei", args=["lied1"]),
                     secure=True).status_code == 404
    # Und eine Kennung, die keine sein kann, kommt gar nicht bis zum Dienst.
    assert client.get("/musik/auftrag/..%2F..%2Fetc/", secure=True).status_code == 404


def test_eine_andere_lehrperson_hoert_nichts(client, kind, dienst, musikstunde_, monkeypatch):
    _lied(client)
    monkeypatch.setattr(musik, "datei", lambda kennung: (200, "audio/mpeg", "3", iter([b"mp3"])))
    lied = Lied.objects.get()
    andere = get_user_model().objects.create_user(username="andere", password="x")
    zweite = Client()
    zweite.force_login(andere)

    antwort = zweite.get(reverse("tutoring:lehrperson_lied", args=[musikstunde_.code, lied.pk]),
                         secure=True)

    assert antwort.status_code == 404


# --- Die Lehrperson ---------------------------------------------------------------

def test_lehrperson_sieht_die_lieder(client, kind, dienst, musikstunde_, lehrperson,
                                     monkeypatch):
    _lied(client, lyrics="[verse]\nHausaufgaben sind doof")
    _lied(client)
    monkeypatch.setattr(musik, "datei", lambda kennung: (200, "audio/mpeg", "3", iter([b"mp3"])))
    lehrer = Client()
    lehrer.force_login(lehrperson)

    seite = lehrer.get(reverse("tutoring:lehrperson_sitzung", args=[musikstunde_.code]),
                       secure=True).content.decode()
    # Seit 22.10.2026 (Thomas: zu viel Text): Die Lieder der ganzen Klasse
    # stehen eingeklappt auf der Seite, die Texte im Verlauf des Kindes.
    assert "Alle Lieder der Klasse anhören (2)" in seite
    lied = Lied.objects.order_by("pk").first()
    adresse = reverse("tutoring:lehrperson_lied", args=[musikstunde_.code, lied.pk])
    assert adresse in seite
    assert "am Spark" in seite

    liste = lehrer.get(reverse("tutoring:lehrperson_klassenliste", args=[musikstunde_.code]),
                       secure=True)
    zeile = liste.context["zeilen"][0]
    assert zeile["lieder"] == 2
    assert zeile["ampel"] == pruefung.ORANGE
    assert liste.context["lieder_summe"] == 2
    html = liste.content.decode()
    assert "<audio" not in html, "Abspieler in der Liste finge alle 5 s neu an"
    # Die Kachel fuehrt in den Verlauf (Thomas: "In der Musikstunde kann ich
    # nicht in die Chats rein").
    verlauf = reverse("tutoring:lehrperson_verlauf", args=[musikstunde_.code, zeile["teilnahme"].pk])
    assert verlauf in html
    assert "2 Lieder" in html
    assert "Wir gehen jeden Tag zur Schule" in html, "die erste Zeile des letzten Textes"

    chat = lehrer.get(verlauf, secure=True).content.decode()
    assert "Hausaufgaben sind doof" in chat
    assert "Wir gehen jeden Tag zur Schule" in chat
    assert chat.count("<audio") == 2
    assert "hx-trigger" not in chat, "ein ersetzter Abspieler finge von vorn an"

    datei = lehrer.get(adresse, secure=True)
    assert datei.status_code == 200
    assert b"".join(datei.streaming_content) == b"mp3"

    karten = lehrer.get(reverse("tutoring:lehrperson_uebersicht"), secure=True)
    karte = karten.context["offene"][0]
    assert karte["lieder"] == 2


# --- Beenden und Verfall ----------------------------------------------------------

def test_beenden_loescht_am_dienst_mit_dem_kennzeichen(client, kind, dienst, musikstunde_,
                                                       lehrperson, caplog):
    _lied(client)
    lehrer = Client()
    lehrer.force_login(lehrperson)

    with caplog.at_level(logging.ERROR):
        lehrer.post(reverse("tutoring:lehrperson_sitzung_beenden", args=[musikstunde_.code]),
                    secure=True)

    (methode, pfad, _), = _loesch_aufrufe(dienst)
    assert pfad == "/auftraege?kennzeichen=" + musikstunde_.log_key
    assert not Lied.objects.exists()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("antwort, code", [
    ({"entfernt": 2, "datei_entfernt": False}, 200),
    ({"entfernt": 2, "datei_entfernt": 1}, 200),
    ({"entfernt": 2}, 200),
    ({}, 503),
])
def test_beenden_wertet_datei_entfernt_aus_und_schreit(client, kind, dienst, musikstunde_,
                                                       caplog, antwort, code):
    """Ein stiller Fehlschlag beim Datenschutz ist schlimmer als keiner."""
    _lied(client)
    dienst.loeschen = antwort
    dienst.loeschen_code = code

    with caplog.at_level(logging.ERROR, logger="tutoring.musikstunde"):
        musikstunde_.beenden()

    fehler = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(fehler) == 1
    assert "Sitzung %s" % musikstunde_.pk in fehler[0].getMessage()
    # Bei uns wird trotzdem geloescht.
    assert not Lied.objects.exists()
    assert musikstunde_.closed_at is not None


def test_datei_entfernt_als_wahrheitswert_reicht(client, kind, dienst, musikstunde_, caplog):
    _lied(client)
    dienst.loeschen = {"entfernt": True, "datei_entfernt": True}

    with caplog.at_level(logging.ERROR):
        musikstunde_.beenden()

    assert len(_loesch_aufrufe(dienst)) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_ohne_lieder_wird_der_dienst_nicht_gefragt(dienst, musikstunde_):
    musikstunde_.beenden()

    assert _loesch_aufrufe(dienst) == []


def test_verfall_loescht_am_dienst(client, kind, dienst, musikstunde_):
    _lied(client)
    LearningSession.objects.filter(pk=musikstunde_.pk).update(
        idle_timeout_minutes=60,
        last_activity_at=timezone.now() - timedelta(hours=2),
    )

    verfallene_aufraeumen()

    (_, pfad, _), = _loesch_aufrufe(dienst)
    assert pfad == "/auftraege?kennzeichen=" + musikstunde_.log_key
    assert not LearningSession.objects.filter(pk=musikstunde_.pk).exists()
    assert not Lied.objects.exists()


# --- Keine Emojis -------------------------------------------------------------------

def _verboten(text):
    return sorted({
        f"U+{ord(z):04X}" for z in text
        if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF
    })


def test_kein_emoji_in_faechern_konzepten_und_vorlagen():
    """Thomas, 12.10.2026: keine Emojis, unter keinen Umstaenden."""
    basis = Path(settings.BASE_DIR)
    # Die Musikstunde ausserdem ohne Gedankenstrich (U+2014); die Vorlagen von
    # vorher werden nicht nachtraeglich umgeschrieben.
    musik = [basis / "tutoring" / "musikstile.py", basis / "tutoring" / "musikstunde.py",
             basis / "tutoring" / "musik_views.py",
             basis / "static" / "js" / "musik_oeffentlich.js",
             basis / "tutoring" / "templates" / "tutoring" / "musik.html",
             basis / "tutoring" / "templates" / "tutoring" / "_musik_lieder.html"]
    dateien = [basis / "tutoring" / "faecher.py", basis / "plan" / "konzepte.py", *musik]
    dateien += sorted(basis.glob("templates/**/*.html"))
    dateien += sorted(basis.glob("*/templates/**/*.html"))
    assert len(dateien) > 20, "Die Vorlagen wurden nicht gefunden"

    funde = {}
    for datei in dateien:
        inhalt = datei.read_text(encoding="utf-8")
        verboten = _verboten(inhalt)
        if datei in musik and chr(0x2014) in inhalt:
            verboten.append("U+2014 (Gedankenstrich)")
        if verboten:
            funde[str(datei.relative_to(basis))] = verboten
    assert not funde, funde


def test_jedes_fach_und_jedes_konzept_hat_eine_zeichnung():
    from django.template.loader import render_to_string

    from plan import konzepte
    from tutoring import faecher

    for fach in faecher.FAECHER:
        svg = render_to_string("tutoring/_fachsymbol.html", {"symbol": fach["symbol"]})
        assert "<svg" in svg and ("<path" in svg or "<circle" in svg), fach["schluessel"]
        assert 'stroke="currentColor"' in svg and 'fill="none"' in svg
    for konzept in konzepte.KONZEPTE:
        svg = render_to_string("plan/_konzeptsymbol.html", {"symbol": konzept["symbol"]})
        assert "<svg" in svg and ("<path" in svg or "<rect" in svg), konzept["schluessel"]
    assert "<svg" not in render_to_string("tutoring/_fachsymbol.html", {"symbol": ""})


def test_die_fachwahl_zeigt_zeichnungen(client, lehrperson):
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True).content.decode()

    assert seite.count('class="linien-symbol"') == 6
    assert not _verboten(seite)


# --- Der Fortschrittsbalken ----------------------------------------------------

def test_lied_und_stand_tragen_die_erwartung_fuer_den_balken(client, kind, dienst):
    """Thomas (20.10.2026): ein Balken statt "noch etwa so viele Sekunden".

    Der Balken im Browser braucht die Rechenzeit des eigenen Liedes als
    Erfahrungswert (core/musik_zeit.py); sie reist beim Anlegen und bei
    jeder Abfrage mit, und ein fertiges Lied fuehrt den Wert nach.
    """
    from core import musik_zeit

    musik_zeit.vergessen()
    vorher = musik_zeit.erwartung(60, "klein")

    angelegt = _lied(client).json()
    assert angelegt["erwartung_s"] == pytest.approx(vorher, abs=0.05)

    stand = client.get(reverse("tutoring:musik_auftrag", args=["lied1"]), secure=True).json()
    assert stand["zustand"] == "fertig"
    assert stand["erwartung_s"] > 0
    # Die Attrappe meldet 9 s fuer 60 s: knapp unter der Erfahrung (10,1 s),
    # also sinkt der Wert, und nur fuer die kleine Fassung.
    assert musik_zeit.erwartung(60, "klein") < vorher
    assert musik_zeit.erwartung(60, "xl") == pytest.approx(21.5, abs=0.05)
    musik_zeit.vergessen()
