"""Der Safe Chat (Thomas, 23.10.2026): der Server hinter der Oberflaeche.

Hier laeuft kein Netz. Die Ampel (pruefung.einstufen), das Modell am Spark
(chat_views.gespraech_holen_sync) und die Gegenstelle (cloud.geprueft_fragen,
cloud.urteil_holen) werden per monkeypatch ersetzt; wo die Kette selbst
geprueft wird, ersetzt ein Klient die Verbindung wie in test_qualitaet.py.

Geprueft wird, was der Server zusagt: Ein roter Beitrag wird nicht
beantwortet; ohne freigegebene und eingerichtete Qualitaetssicherung geht
nichts hinaus; was hinausging, steht mit allen Schritten am Zug und im
Forschungsprotokoll; das Urteil der Gegenstelle wird gesammelt und wirft
nie; und der Schluessel steht in keiner Meldung.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import chat_views, cloud, pruefung, safechat, shield, spark, stundenform
from tutoring.models import ChatZug, Interaction, LearningSession, Participation
from tutoring.spark import SparkNichtErreichbar

pytestmark = pytest.mark.django_db

ANTWORT_SPARK = "Vulkane sind Berge, aus denen Lava kommt."
ANTWORT_AUSSEN = "[PERS_a3f2] kann im Referat mit dem Ätna anfangen."
ANTWORT_KLAR = "Anna kann im Referat mit dem Ätna anfangen."


# --- Attrappen ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def ohne_modell(monkeypatch):
    """Die Ampel ohne Spark: rot, wenn "Trottel" drinsteht, sonst gruen."""
    def einstufen(text):
        if "Trottel" in (text or ""):
            return pruefung.ROT, "Schimpfwort"
        return pruefung.GRUEN, ""
    monkeypatch.setattr(pruefung, "einstufen", einstufen)


class Spark:
    """Das Modell am Spark: merkt sich Anweisung und Verlauf."""

    def __init__(self):
        self.aufrufe = []
        self.antwort = ANTWORT_SPARK
        self.kaputt = False

    def __call__(self, system, nachrichten, max_tokens=700, **_):
        self.aufrufe.append({"system": system, "nachrichten": list(nachrichten),
                             "max_tokens": max_tokens})
        if self.kaputt:
            raise SparkNichtErreichbar()
        return self.antwort, {"modell": "attrappe", "tokens_ein": 30,
                              "tokens_aus": 12, "dauer_ms": 400}


@pytest.fixture
def spark_(monkeypatch):
    attrappe = Spark()
    monkeypatch.setattr(chat_views, "gespraech_holen_sync", attrappe)
    return attrappe


class Gegenstelle:
    """Die Kette nach draussen und das Urteil, ohne Netz."""

    def __init__(self):
        self.fragen = []
        self.urteile = []
        self.sperre = None
        self.urteil = {"urteil": "ohne", "grund": "Keine Person erkennbar.",
                       "tokens_ein": 50, "tokens_aus": 20, "dauer_ms": 300}

    def geprueft_fragen(self, text, verbrauch=None, system=None, max_tokens=800):
        self.fragen.append({"text": text, "verbrauch": verbrauch, "system": system,
                            "max_tokens": max_tokens})
        if self.sperre is not None:
            raise self.sperre
        return {
            "loesung": ANTWORT_KLAR,
            "umgeschrieben": "Ein Kind hält ein Referat über Vulkane.",
            "maskiert_ein": "Ein Kind hält ein Referat über Vulkane. [PERS_a3f2] fragt, womit es anfangen soll.",
            "maskiert_aus": ANTWORT_AUSSEN,
            "entitaeten": {shield.TYP_PERSON: 1},
            "ersetzt": 1,
            "modell": "gpt-probe",
            "tokens_ein": 120,
            "tokens_aus": 40,
            "dauer_ms": 2100,
        }

    def urteil_holen(self, maskiert_ein, maskiert_aus):
        self.urteile.append((maskiert_ein, maskiert_aus))
        return dict(self.urteil)


@pytest.fixture
def gegenstelle(monkeypatch, settings):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "gpt-probe"
    settings.CLOUD_PREISE = {"gpt-probe": {"ein": 1, "aus": 10}}
    attrappe = Gegenstelle()
    monkeypatch.setattr(cloud, "geprueft_fragen", attrappe.geprueft_fragen)
    monkeypatch.setattr(cloud, "urteil_holen", attrappe.urteil_holen)
    return attrappe


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


def _stunde(lehrperson, **werte):
    vorgaben = {
        "title": "Safe Chat 3b", "teacher": lehrperson,
        "mode": LearningSession.BETRIEB_CHAT, "subject": "safechat",
        "task_hint": "Fragen zum Referat über Vulkane", "age_group": "10-14",
    }
    vorgaben.update(werte)
    return LearningSession.objects.create(**vorgaben)


@pytest.fixture
def stunde(lehrperson):
    return _stunde(lehrperson)


@pytest.fixture
def stunde_mit_qs(lehrperson):
    return _stunde(lehrperson, cloud_enabled=True)


def _beitreten(client, sitzung, tier="fuchs"):
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": tier}, secure=True)
    return Participation.objects.get(learning_session=sitzung, animal=tier)


def _zug(client, text, weg="spark"):
    return client.post(reverse("tutoring:safechat_zug"), {"text": text, "weg": weg},
                       secure=True)


def _zuege(teilnahme):
    return list(teilnahme.chatzuege.order_by("created_at", "pk"))


# --- Anlegen und Weiterleitung ---------------------------------------------------

def test_anlegen_mit_fach_safechat_fuehrt_in_die_betriebsart_chat(client, lehrperson, settings):
    settings.CLOUD_ENABLED = True
    client.force_login(lehrperson)

    antwort = client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "safechat", "title": "Chat 4a", "task_hint": "Vulkane",
        "age_group": "10-14", "qualitaetssicherung": "ja",
    }, secure=True)

    assert antwort.status_code == 302
    sitzung = LearningSession.objects.get(title="Chat 4a")
    assert sitzung.mode == LearningSession.BETRIEB_CHAT
    assert sitzung.ist_safechat
    assert sitzung.cloud_enabled is True, "Die Qualitaetssicherung wird im Safe Chat angenommen"
    assert sitzung.task_hint == "Vulkane"
    assert sitzung.age_group == "10-14"
    assert sitzung.fach_symbol == "schild"


def test_ohne_zugang_bleibt_die_qualitaetssicherung_aus(client, lehrperson, settings):
    settings.CLOUD_ENABLED = False
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "safechat", "title": "Chat 4b", "qualitaetssicherung": "ja",
    }, secure=True)

    assert LearningSession.objects.get(title="Chat 4b").cloud_enabled is False


def test_kind_landet_im_safechat(client, stunde):
    _beitreten(client, stunde)

    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:safechat")


def test_die_chatseite_bringt_die_umgebung_mit(client, stunde):
    teilnahme = _beitreten(client, stunde)
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.LERNEND, text="Hallo")
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.KI, text="Hallo zurück")

    antwort = client.get(reverse("tutoring:safechat"), secure=True)

    assert antwort.status_code == 200
    umgebung = antwort.context
    assert [z.text for z in umgebung["zuege"]] == ["Hallo", "Hallo zurück"]
    assert umgebung["zuege"][1].vorher == "Hallo"
    assert umgebung["aussen_moeglich"] is False
    assert umgebung["zug_url"] == reverse("tutoring:safechat_zug")
    assert umgebung["text_max"] == safechat.TEXT_MAX
    assert umgebung["thema"] == "Fragen zum Referat über Vulkane"


def test_ohne_teilnahme_geht_es_zum_start(client):
    assert client.get(reverse("tutoring:safechat"), secure=True)["Location"] == reverse("start")
    assert _zug(client, "Hallo").status_code == 403


def test_eine_andere_betriebsart_kommt_nicht_in_den_safechat(client, lehrperson):
    mathe = LearningSession.objects.create(title="Mathe", teacher=lehrperson, subject="mathematik")
    _beitreten(client, mathe)

    assert client.get(reverse("tutoring:safechat"), secure=True)["Location"] == reverse("tutoring:chat")
    antwort = _zug(client, "Hallo")
    assert antwort.status_code == 403
    assert ChatZug.objects.count() == 0


# --- Der Weg zum Spark -----------------------------------------------------------

def test_weg_spark_legt_zwei_zuege_an_und_schickt_den_verlauf_mit(client, stunde, spark_):
    teilnahme = _beitreten(client, stunde)

    erste = _zug(client, "Was ist ein Vulkan?")
    assert erste.status_code == 200
    daten = erste.json()
    assert daten["ok"] is True
    assert daten["ampel"] == pruefung.GRUEN
    assert daten["weg"] == ChatZug.WEG_SPARK
    assert isinstance(daten["html"], str) and "Was ist ein Vulkan?" in daten["html"]
    assert ANTWORT_SPARK in daten["html"]

    zweite = _zug(client, "Und warum spuckt er Lava?")
    assert zweite.status_code == 200

    zuege = _zuege(teilnahme)
    assert [(z.role, z.weg) for z in zuege] == [
        (ChatZug.LERNEND, ChatZug.WEG_SPARK), (ChatZug.KI, ChatZug.WEG_SPARK),
        (ChatZug.LERNEND, ChatZug.WEG_SPARK), (ChatZug.KI, ChatZug.WEG_SPARK),
    ]
    assert zuege[1].text == ANTWORT_SPARK
    assert zuege[1].hat_protokoll is False

    # Der zweite Aufruf bekommt das ganze Gespraech, als Gespraech.
    assert spark_.aufrufe[1]["nachrichten"] == [
        {"role": "user", "content": "Was ist ein Vulkan?"},
        {"role": "assistant", "content": ANTWORT_SPARK},
        {"role": "user", "content": "Und warum spuckt er Lava?"},
    ]
    system = spark_.aufrufe[1]["system"]
    assert "Fragen zum Referat über Vulkane" in system, "Das Thema steht als Hinweis dabei"
    assert "Hinweis, kein Zwang" in system
    assert "zehn und vierzehn" in system, "Die Altersklasse bestimmt die Anrede"
    assert "Frag nie nach dem Namen" in system

    # Jeder Aufruf ist eine Zeile im Forschungsprotokoll, lokal, ohne Leak-Check.
    zeilen = Interaction.objects.filter(session_key=stunde.log_key)
    assert zeilen.count() == 2
    assert {z.route for z in zeilen} == {Interaction.LOKAL}
    assert {z.outcome for z in zeilen} == {"safechat"}
    assert zeilen.first().raw_input == "Und warum spuckt er Lava?"


def test_der_verlauf_an_den_spark_ist_ein_fenster(client, stunde, spark_):
    teilnahme = _beitreten(client, stunde)
    for n in range(safechat.VERLAUF_FENSTER):
        ChatZug.objects.create(participation=teilnahme, role=ChatZug.LERNEND, text=f"Frage {n}")
        ChatZug.objects.create(participation=teilnahme, role=ChatZug.KI, text=f"Antwort {n}")

    _zug(client, "Die letzte Frage")

    nachrichten = spark_.aufrufe[0]["nachrichten"]
    assert len(nachrichten) <= safechat.VERLAUF_FENSTER
    assert nachrichten[0]["role"] == "user"
    assert nachrichten[-1] == {"role": "user", "content": "Die letzte Frage"}
    assert "Frage 0" not in json.dumps(nachrichten)


def test_rote_ampel_wird_nicht_beantwortet_und_faerbt_die_teilnahme(client, stunde, spark_):
    teilnahme = _beitreten(client, stunde)

    antwort = _zug(client, "Du Trottel")

    assert antwort.status_code == 200
    assert antwort.json()["ampel"] == pruefung.ROT
    zuege = _zuege(teilnahme)
    assert len(zuege) == 2
    assert zuege[0].flag == pruefung.ROT
    assert zuege[0].flag_reason == "Schimpfwort"
    assert zuege[1].ist_ki and zuege[1].text == safechat.NICHT_BEANTWORTET
    assert spark_.aufrufe == [], "Auf Rot wird kein Modell gefragt"
    teilnahme.refresh_from_db()
    assert teilnahme.worst_flag == pruefung.ROT


def test_rote_ampel_geht_auch_nicht_nach_draussen(client, stunde_mit_qs, spark_, gegenstelle):
    teilnahme = _beitreten(client, stunde_mit_qs)

    _zug(client, "Du Trottel", weg="aussen")

    zuege = _zuege(teilnahme)
    assert zuege[1].text == safechat.NICHT_BEANTWORTET
    assert zuege[1].weg == ChatZug.WEG_AUSSEN
    assert zuege[1].hat_protokoll is False
    assert gegenstelle.fragen == []
    assert Interaction.objects.filter(route=Interaction.CLOUD).count() == 0


def test_faellt_der_spark_aus_bleibt_der_beitrag(client, stunde, spark_):
    teilnahme = _beitreten(client, stunde)
    spark_.kaputt = True

    antwort = _zug(client, "Was ist Magma?")

    assert antwort.status_code == 503
    assert antwort.json()["ok"] is False
    assert antwort.json()["grund"] == spark.MELDUNG_NICHT_ERREICHBAR
    zuege = _zuege(teilnahme)
    assert len(zuege) == 1 and zuege[0].text == "Was ist Magma?"


def test_leer_zu_lang_oder_unbekannter_weg_wird_abgewiesen(client, stunde, spark_):
    _beitreten(client, stunde)

    assert _zug(client, "   ").status_code == 400
    assert _zug(client, "x" * (safechat.TEXT_MAX + 1)).status_code == 400
    assert _zug(client, "Hallo", weg="post").status_code == 400
    assert ChatZug.objects.count() == 0
    assert spark_.aufrufe == []


def test_ein_json_rumpf_wird_auch_gelesen(client, stunde, spark_):
    teilnahme = _beitreten(client, stunde)

    antwort = client.post(
        reverse("tutoring:safechat_zug"),
        json.dumps({"text": "Hallo", "weg": "spark"}),
        content_type="application/json", secure=True,
    )

    assert antwort.status_code == 200
    assert _zuege(teilnahme)[0].text == "Hallo"


# --- Der Weg nach draussen -------------------------------------------------------

def test_draussen_bei_abgeschalteter_qualitaetssicherung_403(client, stunde, spark_, settings):
    settings.CLOUD_ENABLED = True
    teilnahme = _beitreten(client, stunde)

    antwort = _zug(client, "Womit fange ich an?", weg="aussen")

    assert antwort.status_code == 403
    assert antwort.json()["grund"] == chat_views.AUSSEN_AUS
    assert _zuege(teilnahme) == [], "Kein Zug ohne Antwort"


def test_draussen_ohne_eingerichteten_zugang_403(client, stunde_mit_qs, spark_, settings):
    settings.CLOUD_ENABLED = False
    _beitreten(client, stunde_mit_qs)

    assert _zug(client, "Womit fange ich an?", weg="aussen").status_code == 403
    assert client.get(reverse("tutoring:safechat"), secure=True).context["aussen_moeglich"] is False


def test_draussen_mit_erfolg_traegt_das_ganze_protokoll(client, stunde_mit_qs, spark_, gegenstelle):
    teilnahme = _beitreten(client, stunde_mit_qs)

    antwort = _zug(client, "Anna fragt, womit sie beim Referat anfangen soll.", weg="aussen")

    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["ok"] is True and daten["weg"] == ChatZug.WEG_AUSSEN
    assert daten["urteil"] == ChatZug.URTEIL_OHNE
    assert isinstance(daten["html"], str)
    assert "Anna fragt, womit sie beim Referat anfangen soll." in daten["html"]

    kind, ki = _zuege(teilnahme)
    assert kind.weg == ChatZug.WEG_AUSSEN
    assert ki.ist_ki and ki.ist_aussen and ki.hat_protokoll
    assert ki.text == ANTWORT_KLAR, "Das Kind sieht den Klartext mit eingesetzten Angaben"
    assert ki.aussen_umgeschrieben == "Ein Kind hält ein Referat über Vulkane."
    assert "[PERS_a3f2]" in ki.aussen_gesendet
    assert ki.aussen_empfangen == ANTWORT_AUSSEN
    assert ki.aussen_entitaeten == {shield.TYP_PERSON: 1}
    assert ki.ersetzt == 1
    assert ki.aussen_modell == "gpt-probe"
    assert ki.aussen_gesperrt == ""
    assert ki.urteil == ChatZug.URTEIL_OHNE
    assert ki.urteil_grund == "Keine Person erkennbar."
    # Die Token des Urteils kommen zu denen der Antwort dazu.
    assert ki.aussen_tokens_in == 120 + 50
    assert ki.aussen_tokens_out == 40 + 20
    assert ki.aussen_ms == 2100 + 300
    assert ki.aussen_cost_micro == 170 * 1 + 60 * 10

    # Die Gegenstelle bekam die Anweisung fuer den Chat, nicht die fuer Mathe,
    # und das Urteil wurde ueber genau das gefragt, was sie gesehen hat.
    frage = gegenstelle.fragen[0]
    assert frage["system"].startswith(cloud.SYSTEM_CHAT)
    assert "zehn und vierzehn" in frage["system"]
    assert set(frage["verbrauch"]) == {"aufrufe_sitzung", "aufrufe_tag", "euro_sitzung", "euro_tag"}
    assert gegenstelle.urteile == [(ki.aussen_gesendet, ki.aussen_empfangen)]

    # Zwei Zeilen im Forschungsprotokoll: der Weg hinaus und das Urteil.
    zeilen = list(Interaction.objects.filter(route=Interaction.CLOUD).order_by("pk"))
    assert [z.outcome for z in zeilen] == ["ok", "urteil:ohne"]
    assert zeilen[0].leak_check == Interaction.BESTANDEN
    assert zeilen[0].entities_replaced == {shield.TYP_PERSON: 1}
    assert zeilen[0].masked_input == ki.aussen_gesendet
    assert zeilen[0].masked_output == ANTWORT_AUSSEN
    assert zeilen[0].raw_output == ANTWORT_KLAR
    assert zeilen[0].cost_micro == 120 * 1 + 40 * 10
    assert zeilen[1].tokens_in == 50 and zeilen[1].cost_micro == 50 + 200


def test_das_urteil_mit_personenbezug_wird_gesammelt(client, stunde_mit_qs, spark_, gegenstelle):
    gegenstelle.urteil = {"urteil": "mit", "grund": "Der Ortsname steht im Klartext.",
                          "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1}
    teilnahme = _beitreten(client, stunde_mit_qs)

    antwort = _zug(client, "Was gibt es in Bregenz zu sehen?", weg="aussen")

    assert antwort.json()["urteil"] == ChatZug.URTEIL_MIT
    ki = _zuege(teilnahme)[1]
    assert ki.urteil == ChatZug.URTEIL_MIT
    assert ki.urteil_text == "Personenbezug gesehen"
    assert ki.urteil_grund == "Der Ortsname steht im Klartext."
    assert Interaction.objects.filter(route=Interaction.CLOUD, outcome="urteil:mit").exists()


def test_bleibt_der_weg_zu_sieht_das_kind_den_grund(client, stunde_mit_qs, spark_, gegenstelle):
    gegenstelle.sperre = cloud.CloudGesperrt(
        "Im Text steht etwas, das nicht hinausgeht: Sozialversicherungsnummer.",
        art="blockierender_fund",
    )
    teilnahme = _beitreten(client, stunde_mit_qs)

    antwort = _zug(client, "Meine Nummer ist 1234 010115, stimmt die?", weg="aussen")

    assert antwort.status_code == 200
    assert antwort.json()["ok"] is True
    kind, ki = _zuege(teilnahme)
    assert ki.ist_aussen and ki.hat_protokoll
    assert ki.aussen_gesperrt == "Im Text steht etwas, das nicht hinausgeht: Sozialversicherungsnummer."
    assert ki.text == safechat.aussen_gesperrt_satz(ki.aussen_gesperrt)
    assert "nicht nach draußen gegangen" in ki.text
    assert "Sozialversicherungsnummer" in ki.text
    assert ki.aussen_gesendet == "" and ki.aussen_empfangen == ""
    assert ki.urteil == "", "Ohne Weg hinaus gibt es kein Urteil"
    assert gegenstelle.urteile == []
    zeile = Interaction.objects.get(route=Interaction.CLOUD)
    assert zeile.outcome == "gesperrt"
    assert zeile.error_kind == "blockierender_fund"
    assert zeile.leak_check == Interaction.BLOCKIERT
    assert zeile.masked_input == "" and zeile.raw_input == ""


def test_ein_langer_sperrgrund_wird_gekuerzt(client, stunde_mit_qs, spark_, gegenstelle):
    gegenstelle.sperre = cloud.CloudGesperrt("x" * 300, art="budget")
    teilnahme = _beitreten(client, stunde_mit_qs)

    _zug(client, "Hallo", weg="aussen")

    assert len(_zuege(teilnahme)[1].aussen_gesperrt) == 120


def test_ein_unerwarteter_fehler_draussen_bricht_den_chat_nicht_ab(client, stunde_mit_qs, spark_, gegenstelle):
    gegenstelle.sperre = RuntimeError("Bearer sk-geheim-123")
    teilnahme = _beitreten(client, stunde_mit_qs)

    antwort = _zug(client, "Hallo", weg="aussen")

    assert antwort.status_code == 200
    ki = _zuege(teilnahme)[1]
    assert ki.aussen_gesperrt == "Die externe KI hat nicht geantwortet."
    assert "sk-geheim" not in ki.text
    assert Interaction.objects.get(route=Interaction.CLOUD).error_kind == "RuntimeError"


def test_das_urteil_zaehlt_gegen_das_budget(client, stunde_mit_qs, spark_, gegenstelle):
    """Zwei Aufrufe je Frage nach draussen, beide gezaehlt."""
    from tutoring.views import cloud_verbrauch

    _beitreten(client, stunde_mit_qs)
    _zug(client, "Hallo", weg="aussen")

    assert cloud_verbrauch(stunde_mit_qs)["aufrufe_sitzung"] == 2


# --- Die Kette und das Urteil, ohne Ansicht --------------------------------------

class _Antwort:
    def __init__(self, daten):
        self.daten = daten

    def raise_for_status(self):
        return None

    def json(self):
        return self.daten


class _Klient:
    """Ein httpx.Client, der sich merkt, was hinausging, und antwortet, was man ihm gibt."""

    def __init__(self, antwort=None, fehler=None):
        self.antwort = antwort
        self.fehler = fehler
        self.anfragen = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, json=None, headers=None):
        self.anfragen.append({"url": url, "json": json, "headers": headers or {}})
        if self.fehler is not None:
            raise self.fehler
        return _Antwort(self.antwort)


@pytest.fixture
def ohne_spark_in_der_kette(monkeypatch):
    """Umformulierung und Namenserkennung ohne Spark."""
    monkeypatch.setattr(shield, "neu_formulieren", lambda text: text)
    monkeypatch.setattr(shield, "namensfunde", lambda text: [])


def _gegenstelle_antwortet(monkeypatch, inhalt, modell="gpt-probe"):
    klient = _Klient({
        "choices": [{"message": {"content": inhalt}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        "model": modell,
    })
    monkeypatch.setattr(cloud.httpx, "Client", lambda **k: klient)
    return klient


def test_geprueft_fragen_nimmt_anweisung_und_tokengrenze(settings, monkeypatch, ohne_spark_in_der_kette):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "gpt-probe"
    klient = _gegenstelle_antwortet(monkeypatch, "Fang mit der Entstehung an.")

    ergebnis = cloud.geprueft_fragen("Womit fange ich an?", system=cloud.SYSTEM_CHAT, max_tokens=800)

    rumpf = klient.anfragen[0]["json"]
    assert rumpf["messages"][0] == {"role": "system", "content": cloud.SYSTEM_CHAT}
    assert rumpf["messages"][1]["content"] == "Womit fange ich an?"
    assert rumpf["max_completion_tokens"] == 800
    assert ergebnis["loesung"] == "Fang mit der Entstehung an."
    assert ergebnis["maskiert_aus"] == "Fang mit der Entstehung an."
    assert ergebnis["entitaeten"] == {} and ergebnis["ersetzt"] == 0
    assert ergebnis["tokens_ein"] == 7 and ergebnis["tokens_aus"] == 3
    assert set(ergebnis) == {"loesung", "anweisung", "umgeschrieben", "maskiert_ein",
                             "maskiert_aus", "entitaeten", "ersetzt", "bild", "modell",
                             "tokens_ein", "tokens_aus", "dauer_ms"}
    assert ergebnis["bild"] is False, "im Safe Chat geht nie ein Bild mit"


def test_geprueft_loesen_verhaelt_sich_wie_bisher(settings, monkeypatch, ohne_spark_in_der_kette):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "gpt-probe"
    klient = _gegenstelle_antwortet(monkeypatch, "WEG: 6 mal 8.\nERGEBNIS: 48 Stifte")

    ergebnis = cloud.geprueft_loesen("6 Packungen mit je 8 Stiften.")

    rumpf = klient.anfragen[0]["json"]
    assert rumpf["messages"][0]["content"] == cloud.SYSTEM
    assert rumpf["max_completion_tokens"] == 2000
    assert ergebnis["loesung"].endswith("48 Stifte")


def test_der_schluessel_steht_in_keiner_fehlermeldung(settings, monkeypatch, caplog,
                                                       ohne_spark_in_der_kette):
    """httpx schreibt in manche Meldungen die ganze Anfrage. Die Art reicht."""
    settings.CLOUD_ENABLED = True
    settings.CLOUD_API_KEY = "sk-geheim-123"
    klient = _Klient(fehler=httpx.ConnectError("Verbindung mit Bearer sk-geheim-123 fehlgeschlagen"))
    monkeypatch.setattr(cloud.httpx, "Client", lambda **k: klient)

    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_fragen("Hallo", system=cloud.SYSTEM_CHAT)
    assert "sk-geheim" not in str(fehler.value)
    assert "sk-geheim" not in fehler.value.grund
    assert fehler.value.art == "ConnectError"

    with pytest.raises(cloud.CloudGesperrt) as fehler:
        cloud.geprueft_loesen("6 mal 8")
    assert "sk-geheim" not in str(fehler.value)

    urteil = cloud.urteil_holen("Hallo", "Hallo zurück")
    assert urteil["urteil"] == "offen"
    assert "sk-geheim" not in urteil["grund"]
    assert "ConnectError" in urteil["grund"]
    assert "sk-geheim" not in caplog.text
    # Der Schluessel stand im Kopf der Anfrage, und nur dort.
    assert klient.anfragen[0]["headers"]["Authorization"] == "Bearer sk-geheim-123"


def test_urteil_holen_liest_die_antwort(settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_MODEL = "gpt-probe"
    klient = _gegenstelle_antwortet(
        monkeypatch, 'Hier: {"personenbezug": false, "begruendung": "Nur Platzhalter."}',
    )

    urteil = cloud.urteil_holen("[PERS_a3f2] fragt nach Vulkanen.", "Vulkane sind Berge.")

    assert urteil == {"urteil": "ohne", "grund": "Nur Platzhalter.",
                      "tokens_ein": 7, "tokens_aus": 3, "dauer_ms": urteil["dauer_ms"],
                      "anweisung": cloud.URTEIL_PROMPT}
    rumpf = klient.anfragen[0]["json"]
    assert rumpf["messages"][0]["content"] == cloud.URTEIL_PROMPT
    assert "[PERS_a3f2] fragt nach Vulkanen." in rumpf["messages"][1]["content"]
    assert "Vulkane sind Berge." in rumpf["messages"][1]["content"]
    assert "Platzhalter in eckigen Klammern" in cloud.URTEIL_PROMPT
    assert "personenbezug" in cloud.URTEIL_PROMPT


def test_urteil_holen_sieht_personenbezug(settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    _gegenstelle_antwortet(monkeypatch, '{"personenbezug": true, "begruendung": "Ein Nachname steht da."}')

    urteil = cloud.urteil_holen("Herr Gruber fragt.", "Antwort")

    assert urteil["urteil"] == "mit"
    assert urteil["grund"] == "Ein Nachname steht da."


@pytest.mark.parametrize("inhalt", [
    "Ich bin mir nicht sicher.",
    '{"personenbezug": "vielleicht"}',
    "{kaputt",
    "",
])
def test_urteil_holen_wirft_nie_bei_unbrauchbarer_antwort(settings, monkeypatch, inhalt):
    settings.CLOUD_ENABLED = True
    _gegenstelle_antwortet(monkeypatch, inhalt)

    urteil = cloud.urteil_holen("a", "b")

    assert urteil["urteil"] == "offen"
    assert urteil["grund"]


def test_urteil_holen_wirft_nie_bei_einem_kaputten_klienten(settings, monkeypatch):
    settings.CLOUD_ENABLED = True

    def kaputt(**k):
        raise RuntimeError("kein Netz")
    monkeypatch.setattr(cloud.httpx, "Client", kaputt)

    urteil = cloud.urteil_holen("a", "b")

    assert urteil["urteil"] == "offen"
    assert "RuntimeError" in urteil["grund"]
    assert urteil["tokens_ein"] == 0


def test_urteil_holen_ohne_zugang_ist_offen(settings):
    settings.CLOUD_ENABLED = False

    assert cloud.urteil_holen("a", "b")["urteil"] == "offen"


def test_system_chat_haengt_die_altersklasse_an():
    volksschule = cloud.system_chat("6-10")
    oberstufe = cloud.system_chat("14-19")

    assert volksschule.startswith(cloud.SYSTEM_CHAT)
    assert "DREI" in volksschule
    assert "VIER" in oberstufe
    assert "frag nicht nach" in cloud.SYSTEM_CHAT
    assert "Frag nie nach Namen" in cloud.SYSTEM_CHAT


# --- Der Spark mit Gespraechsverlauf ----------------------------------------------

def test_gespraech_holen_sync_schickt_den_verlauf(settings, monkeypatch):
    settings.SPARK_MODEL = "spark-probe"
    settings.SPARK_RETRIES = 0
    klient = _Klient({"choices": [{"message": {"content": "Ja."}}],
                      "usage": {"prompt_tokens": 5, "completion_tokens": 1}})
    monkeypatch.setattr(spark.httpx, "Client", lambda **k: klient)
    nachrichten = [{"role": "user", "content": "Hallo"},
                   {"role": "assistant", "content": "Hallo zurück"},
                   {"role": "user", "content": "Alles gut?"}]

    text, messung = spark.gespraech_holen_sync("Sei nett.", nachrichten, max_tokens=99)

    assert text == "Ja."
    assert messung["tokens_ein"] == 5 and messung["modell"] == "spark-probe"
    rumpf = klient.anfragen[0]["json"]
    assert rumpf["messages"] == [{"role": "system", "content": "Sei nett."}, *nachrichten]
    assert rumpf["max_tokens"] == 99
    assert rumpf["stream"] is False


def test_gespraech_holen_sync_meldet_den_ausfall(settings, monkeypatch):
    settings.SPARK_RETRIES = 0
    klient = _Klient(fehler=httpx.ConnectError("weg"))
    monkeypatch.setattr(spark.httpx, "Client", lambda **k: klient)

    with pytest.raises(SparkNichtErreichbar):
        spark.gespraech_holen_sync("Sei nett.", [{"role": "user", "content": "Hallo"}])


# --- safechat.py: ohne Datenbank -------------------------------------------------

def _z(role, text, **mehr):
    felder = {"role": role, "text": text, "aussen_entitaeten": None}
    felder.update(mehr)
    return SimpleNamespace(**felder)


def test_mit_protokoll_setzt_vorher_und_entitaeten_text():
    zuege = [
        _z(ChatZug.LERNEND, "Anna fragt."),
        _z(ChatZug.KI, "Antwort", aussen_entitaeten={"PERS": 2, "ORT": 1}),
        _z(ChatZug.KI, "Noch eine Antwort"),
        _z(ChatZug.LERNEND, "Danke"),
        _z(ChatZug.KI, "Gern", aussen_entitaeten={}),
    ]

    ergebnis = safechat.mit_protokoll(zuege)

    assert ergebnis is not None and len(ergebnis) == 5
    assert ergebnis[1].vorher == "Anna fragt."
    assert ergebnis[1].entitaeten_text == "2 Namen, 1 Ort"
    assert ergebnis[2].vorher == "", "Kein unmittelbar vorangehender Kind-Zug"
    assert ergebnis[4].vorher == "Danke"
    assert ergebnis[4].entitaeten_text == ""
    assert ergebnis[0].vorher == "" and ergebnis[0].entitaeten_text == ""


def test_entitaeten_text_in_worten():
    assert safechat.entitaeten_text({"PERS": 1}) == "1 Name"
    assert safechat.entitaeten_text({"EMAIL": 2, "GEB": 1}) == "2 E-Mail-Adressen, 1 Geburtsdatum"
    assert safechat.entitaeten_text({"PERS": 0}) == ""
    assert safechat.entitaeten_text(None) == ""
    assert safechat.entitaeten_text({"NEU": 3}) == "3 NEU"


def test_nachrichten_fuer_spark_beginnt_beim_kind_und_wechselt_ab():
    zuege = [
        _z(ChatZug.KI, "Begrüßung"),
        _z(ChatZug.LERNEND, "Erste"),
        _z(ChatZug.LERNEND, "Zweite, der Spark war weg"),
        _z(ChatZug.KI, "Antwort"),
        _z(ChatZug.LERNEND, "   "),
        _z(ChatZug.LERNEND, "Dritte"),
    ]

    assert safechat.nachrichten_fuer_spark(zuege) == [
        {"role": "user", "content": "Erste\n\nZweite, der Spark war weg"},
        {"role": "assistant", "content": "Antwort"},
        {"role": "user", "content": "Dritte"},
    ]


def test_nachrichten_fuer_spark_nimmt_die_letzten():
    zuege = [_z(ChatZug.LERNEND, f"Frage {n}") if n % 2 == 0 else _z(ChatZug.KI, f"Antwort {n}")
             for n in range(30)]

    nachrichten = safechat.nachrichten_fuer_spark(zuege, fenster=4)

    assert [n["content"] for n in nachrichten] == ["Frage 26", "Antwort 27", "Frage 28", "Antwort 29"]


def test_system_prompt_je_altersklasse_mit_thema_als_hinweis():
    klein = safechat.system_prompt("6-10", "Vulkane {und} Lava")
    gross = safechat.system_prompt("14-19")

    assert "sechs bis zehn" in klein and "DREI" in klein
    assert "Vulkane {und} Lava" in klein and "kein Zwang" in klein
    assert "vierzehn und neunzehn" in gross and "Thema" not in gross
    for text in (klein, gross):
        assert "Frag nie nach dem Namen" in text
        assert "erwachsene Person" in text


def test_der_sperrsatz_nennt_den_grund():
    satz = safechat.aussen_gesperrt_satz("Heute sind die 300 Abfragen aufgebraucht")

    assert satz.startswith("Deine Frage ist nicht nach draußen gegangen.")
    assert "Heute sind die 300 Abfragen aufgebraucht." in satz
    assert safechat.AUSSEN_GESPERRT_SATZ is safechat.aussen_gesperrt_satz
    assert safechat.NICHT_BEANTWORTET == "Das beantworte ich nicht. Schreib es bitte anders."


# --- Die Lehrperson: Kacheln, Verlauf, Marken, Erklaerung -------------------------

def _gespraech(teilnahme):
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.LERNEND, text="Was ist ein Vulkan?")
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.KI, text=ANTWORT_SPARK)
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.LERNEND,
                           text="Anna fragt, womit sie anfangen soll.\nZweite Zeile", weg=ChatZug.WEG_AUSSEN)
    return ChatZug.objects.create(
        participation=teilnahme, role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN, text=ANTWORT_KLAR,
        aussen_umgeschrieben="Ein Kind fragt.", aussen_gesendet="[PERS_a3f2] fragt.",
        aussen_empfangen=ANTWORT_AUSSEN, aussen_entitaeten={"PERS": 1}, aussen_modell="gpt-probe",
        aussen_tokens_in=170, aussen_tokens_out=60, aussen_ms=2400, aussen_cost_micro=770,
        urteil=ChatZug.URTEIL_OHNE, urteil_grund="Nur ein Platzhalter.",
    )


def test_die_kachel_zaehlt_nachrichten_und_den_weg_nach_draussen(client, lehrperson, stunde_mit_qs):
    teilnahme = Participation.objects.create(learning_session=stunde_mit_qs, animal="fuchs", token="t1")
    _gespraech(teilnahme)
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN,
                           text="nicht gegangen", aussen_gesperrt="Budget aus")
    still = Participation.objects.create(learning_session=stunde_mit_qs, animal="hase", token="t2")
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde_mit_qs.code]),
                         secure=True)

    zeilen = {z["teilnahme"].pk: z for z in antwort.context["zeilen"]}
    kachel = zeilen[teilnahme.pk]
    assert kachel["zeile"] == "2 Nachrichten"
    assert kachel["notiz"] == "1 nach draußen · zuletzt ohne Personenbezug"
    assert kachel["beitrag"] == "Anna fragt, womit sie anfangen soll."
    assert kachel["fertig"] is False
    assert kachel["aktiv"] is True, "Die Zeit folgt den Zuegen"
    leer = zeilen[still.pk]
    assert leer["zeile"] == "" and leer["notiz"] == "" and leer["beitrag"] == ""
    seite = antwort.content.decode()
    assert "2 Nachrichten" in seite
    assert reverse("tutoring:lehrperson_verlauf", args=[stunde_mit_qs.code, teilnahme.pk]) in seite


def test_eine_nachricht_ohne_weg_nach_draussen(client, lehrperson, stunde):
    teilnahme = Participation.objects.create(learning_session=stunde, animal="fuchs", token="t1")
    ChatZug.objects.create(participation=teilnahme, role=ChatZug.LERNEND, text="Hallo")
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]), secure=True)

    kachel = antwort.context["zeilen"][0]
    assert kachel["zeile"] == "1 Nachricht"
    assert kachel["notiz"] == "nichts nach draußen"


def test_der_verlauf_der_lehrperson_traegt_die_zuege_mit_protokoll(client, lehrperson, stunde_mit_qs):
    teilnahme = Participation.objects.create(learning_session=stunde_mit_qs, animal="fuchs", token="t1")
    _gespraech(teilnahme)
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_verlauf", args=[stunde_mit_qs.code, teilnahme.pk]),
                         secure=True)

    assert antwort.status_code == 200
    chatzuege = antwort.context["chatzuege"]
    assert len(chatzuege) == 4
    assert chatzuege[3].vorher.startswith("Anna fragt, womit sie anfangen soll.")
    assert chatzuege[3].entitaeten_text == "1 Name"
    assert chatzuege[1].vorher == "Was ist ein Vulkan?"
    seite = antwort.content.decode()
    assert "Was ist ein Vulkan?" in seite
    assert "[PERS_a3f2] fragt." in seite, "Was hinausging, steht im Verlauf"
    assert ANTWORT_AUSSEN in seite, "Was zurueckkam, steht im Verlauf"
    assert "Nur ein Platzhalter." in seite, "Das Urteil steht im Verlauf"

    teilstueck = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[stunde_mit_qs.code, teilnahme.pk]),
        secure=True, HTTP_HX_REQUEST="true",
    ).content.decode()
    assert "[PERS_a3f2] fragt." in teilstueck


def test_die_marken_nennen_den_weg_nach_draussen(lehrperson, settings):
    settings.CLOUD_ENABLED = True
    mit = _stunde(lehrperson, cloud_enabled=True)
    ohne = _stunde(lehrperson, cloud_enabled=False)

    assert stundenform.marken(mit) == ["10–14 Jahre", "Draußen fragen: ein",
                                       "Thema: Fragen zum Referat über Vulkane"]
    assert "Draußen fragen: aus" in stundenform.marken(ohne)

    settings.CLOUD_ENABLED = False
    assert "Draußen fragen: aus" in stundenform.marken(mit), "Ohne Zugang gibt es den Knopf nicht"


def test_die_sitzungsseite_erklaert_die_kacheln_des_safechat(client, lehrperson, stunde_mit_qs):
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde_mit_qs.code]),
                       secure=True).content.decode()

    assert "Was die Kacheln zeigen" in seite
    assert "nach draußen gegangen" in seite
    assert "Personenbezug" in seite
    assert "Draußen fragen" in seite
    assert "_stufenerklaerung" not in seite and "Motivationshilfe" not in seite


def test_beenden_loescht_die_zuege(client, lehrperson, stunde):
    teilnahme = Participation.objects.create(learning_session=stunde, animal="fuchs", token="t1")
    _gespraech(teilnahme)
    client.force_login(lehrperson)

    client.post(reverse("tutoring:lehrperson_sitzung_beenden", args=[stunde.code]), secure=True)

    assert ChatZug.objects.count() == 0
