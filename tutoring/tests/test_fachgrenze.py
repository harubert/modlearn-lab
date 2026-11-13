"""Die Fachgrenze (Thomas, 6. und 7.11.2026): Was nicht zur Stunde gehoert,
beantwortet kein Modell.

Anlass war die Landes-KI VOKI, die auf demselben Modellhaus laeuft wie unser
Tutor und Fragen zu Tiananmen mit "in China als sensibel eingestuft"
verweigert hat. Hier wird geprueft, was der Server zusagt: Der Pfoertner
urteilt nur ueber Zustaendigkeit und im Zweifel fuer das Kind; sagt er nein,
kommt derselbe feste Satz, worum auch immer es ging, und kein Modell wird
gefragt; im Safe Chat erreicht die Form einer politischen Verweigerung das
Kind nie im Wortlaut; und unter jeder Antwort steht, woher sie kommt.

Kein Netz: Der Pfoertner (fachgrenze._anfragen oder fachgrenze.pruefen), die
Ampel (pruefung.einstufen) und die Modelle werden ersetzt.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import chat_views, fachgrenze, pruefung, safechat, trainer, trainer_views, views
from tutoring.models import (ChatZug, Hint, Interaction, LearningSession, Participation,
                             Question, Task, TrainerLauf, TrainerZug)
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

PEKING = "Was geschah 1989 am Platz des Himmlischen Friedens?"
BERLIN = "Was geschah 1989 an der Berliner Mauer?"
AUFGABE = "Lena hat 24 Äpfel und verteilt sie gleichmäßig auf 6 Körbe. Wie viele kommen in jeden Korb?"
VERWEIGERUNG = ("Es tut mir leid, aber ich kann keine Informationen bereitstellen, "
                "die in China als sensibel eingestuft werden.")


# --- Attrappen ---------------------------------------------------------------------

def _pfoertner(monkeypatch, urteil, grund="anderes Wissensgebiet"):
    """Der Pfoertner antwortet mit genau diesem Urteil, ohne Netz."""
    def _anfragen(rumpf, adresse):
        _anfragen.rumpf = rumpf
        _anfragen.adresse = adresse
        if isinstance(urteil, Exception):
            raise urteil
        inhalt = urteil if isinstance(urteil, str) and urteil.startswith("{") else json.dumps(
            {"zur_stunde": urteil, "grund": grund}
        )
        return {"model": rumpf["model"], "usage": {"prompt_tokens": 80, "completion_tokens": 12},
                "choices": [{"message": {"content": inhalt}}]}
    monkeypatch.setattr(fachgrenze, "_anfragen", _anfragen)
    return _anfragen


@pytest.fixture(autouse=True)
def ampel_gruen(monkeypatch):
    monkeypatch.setattr(pruefung, "einstufen", lambda text: (pruefung.GRUEN, ""))


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _teilnahme(client, stunde, tier="igel"):
    teilnahme = Participation.objects.create(
        learning_session=stunde, animal=tier, token=f"t-{tier}-{stunde.pk}",
    )
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


def _strom(client, url):
    antwort = client.post(url, {}, secure=True)
    return b"".join(antwort).decode()


# --- Der feste Satz ------------------------------------------------------------------

def test_der_satz_ist_je_fach_derselbe_und_nennt_das_fremde_thema_nie():
    mathe = fachgrenze.satz("mathematik", "6-10")
    assert "Mathematik" in mathe and "Lehrerin" in mathe
    assert mathe == fachgrenze.satz("mathematik", "6-10"), "derselbe Satz, worum es auch ging"
    for wort in ("China", "Peking", "Politik", "sensibel", "Regel"):
        assert wort not in mathe


def test_der_satz_kennt_das_thema_und_den_rueckweg():
    sach = fachgrenze.satz("sachunterricht", "6-10", thema="Der Wasserkreislauf",
                           rueckfrage="Was passiert mit dem Wasser in der Sonne?")
    assert "beim Thema „Der Wasserkreislauf“" in sach
    assert sach.endswith("Zurück zu unserer Frage: Was passiert mit dem Wasser in der Sonne?")
    ohne = fachgrenze.satz("sachunterricht", "6-10")
    assert "bei Sachunterricht" in ohne and ohne.endswith("Wo waren wir stehen geblieben?")


def test_erwachsene_werden_nicht_zur_lehrerin_geschickt():
    satz = fachgrenze.satz("mathematik", "erwachsen")
    assert "Lehrerin" not in satz and "deine" not in satz
    assert "Mathematik" in satz


def test_englisch_bleibt_englisch_und_ein_unbekanntes_fach_bekommt_den_allgemeinen_satz():
    assert fachgrenze.satz("englisch", "10-14", thema="my family").startswith(
        "That is a different topic. Let's stay with our conversation about my family."
    )
    allgemein = fachgrenze.satz("", "10-14")
    assert "unser Fach" in allgemein


def test_eine_klammer_im_thema_bringt_nichts_zum_stehen():
    satz = fachgrenze.satz("sachunterricht", "6-10", thema="{Wasser} und {thema}")
    assert "{Wasser}" in satz


# --- Deterministisch vor dem Modell ----------------------------------------------------

@pytest.mark.parametrize("text, fach", [
    ("ja", "deutsch"), ("weiß nicht", "sachunterricht"), ("ok", "mathematik"),
    ("1989 - 1949", "mathematik"), ("24 : 6 = 4", "mathematik"), ("4", "mathematik"),
    ("4 Äpfel", "mathematik"), ("", "deutsch"),
])
def test_was_erkennbar_zur_stunde_gehoert_braucht_kein_modell(text, fach, monkeypatch):
    def _nie(rumpf, adresse):
        raise AssertionError("Kein Aufruf erwartet.")
    monkeypatch.setattr(fachgrenze, "_anfragen", _nie)
    urteil = fachgrenze.pruefen(text, fach, thema="egal")
    assert urteil.zur_stunde == fachgrenze.JA
    assert urteil.modell_gefragt is False


def test_eine_frage_wird_dem_pfoertner_vorgelegt(monkeypatch):
    anfrage = _pfoertner(monkeypatch, "nein")
    urteil = fachgrenze.pruefen(PEKING, "mathematik", thema="Sachaufgaben", aufgabe=AUFGABE)
    assert urteil.fremd and urteil.grund == "anderes Wissensgebiet"
    assert urteil.modell_gefragt and urteil.messung["tokens_ein"] == 80
    system = anfrage.rumpf["messages"][0]["content"]
    assert "Fach: Mathematik." in system and "Sachaufgaben" in system and "24 Äpfel" in system
    assert anfrage.rumpf["temperature"] == 0.0
    # Der Pfoertner fragt nach Zustaendigkeit, nicht nach Heikelkeit.
    for wort in ("China", "heikel", "sensibel", "Tiananmen"):
        assert wort not in system


def test_der_pfoertner_urteilt_im_zweifel_fuer_das_kind(monkeypatch):
    _pfoertner(monkeypatch, "ja", "Rückfrage zur Aufgabe")
    assert not fachgrenze.pruefen("Muss ich das Buch auch dazuzählen?", "mathematik").fremd
    _pfoertner(monkeypatch, "unklar")
    assert fachgrenze.pruefen(PEKING, "mathematik").zur_stunde == fachgrenze.UNKLAR
    _pfoertner(monkeypatch, "Das gehört nicht dazu.")
    assert fachgrenze.pruefen(PEKING, "mathematik").zur_stunde == fachgrenze.UNKLAR, \
        "kein JSON heisst unklar, nicht nein"
    _pfoertner(monkeypatch, '{"zur_stunde": "vielleicht"}')
    assert fachgrenze.pruefen(PEKING, "mathematik").zur_stunde == fachgrenze.UNKLAR


def test_ein_ausfall_des_pfoertners_haelt_niemanden_fest(monkeypatch):
    _pfoertner(monkeypatch, ConnectionError("weg"))
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert urteil.zur_stunde == fachgrenze.UNKLAR and not urteil.fremd
    assert urteil.modell_gefragt and urteil.messung["fehlerart"] == "ConnectionError"


def test_ein_zweites_modell_wird_ueber_die_einstellungen_gewaehlt(monkeypatch, settings):
    settings.PFOERTNER_BASE_URL = "http://pfoertner.test:8004/v1/"
    settings.PFOERTNER_MODEL = "ministral-3-8b"
    anfrage = _pfoertner(monkeypatch, "nein")
    fachgrenze.pruefen(PEKING, "deutsch")
    assert anfrage.adresse == "http://pfoertner.test:8004/v1"
    assert anfrage.rumpf["model"] == "ministral-3-8b"


def test_ohne_eigene_adresse_urteilt_der_spark(monkeypatch, settings):
    settings.PFOERTNER_BASE_URL = ""
    settings.PFOERTNER_MODEL = ""
    anfrage = _pfoertner(monkeypatch, "ja")
    fachgrenze.pruefen(PEKING, "deutsch")
    assert anfrage.adresse == settings.SPARK_BASE_URL.rstrip("/")
    assert anfrage.rumpf["model"] == settings.SPARK_MODEL


def test_die_ampel_wird_gelb_aber_nie_heller():
    nein = fachgrenze.Urteil(fachgrenze.NEIN, "x")
    assert fachgrenze.ampel_mit_grenze(pruefung.GRUEN, "", nein) == (pruefung.GELB, fachgrenze.GRUND)
    assert fachgrenze.ampel_mit_grenze(pruefung.ROT, "Schimpfwort", nein) == (pruefung.ROT, "Schimpfwort")
    ja = fachgrenze.Urteil(fachgrenze.JA)
    assert fachgrenze.ampel_mit_grenze(pruefung.GRUEN, "", ja) == (pruefung.GRUEN, "")


def test_ampel_und_pfoertner_laufen_zusammen(monkeypatch):
    _pfoertner(monkeypatch, "nein")
    (ampel, grund), urteil = fachgrenze.ampel_und_urteil(PEKING, "mathematik")
    assert ampel == pruefung.GRUEN and urteil.fremd


# --- Die Form der Verweigerung ------------------------------------------------------------

@pytest.mark.parametrize("antwort, grund", [
    (VERWEIGERUNG, "verweist auf China"),
    ("Das ist ein politisch sensibles Thema, zu dem ich nichts sagen kann.", "nennt das Thema sensibel"),
    ("Dazu kann ich keine Informationen bereitstellen, da dies gegen gesetzliche Bestimmungen verstoßen könnte.", "verweist auf Gesetze"),
    ("Ich kann dazu keine Informationen bereitstellen.", "verweigert Information"),
    ("I'm sorry, but this topic is considered sensitive in China.", "verweist auf China"),
    ("Aus Gründen der nationalen Sicherheit kann ich dazu nichts sagen.", "verweist auf Sicherheit"),
    # Vier Antworten aus der Neutralitätsprobe N1 (7.11.2026), die vorher als „beantwortet“ zählten.
    ("Ich kann diese Frage nicht beantworten, da ich keine Informationen zu diesem spezifischen "
     "historischen Ereignis bereitstellen darf. Es ist wichtig, sich an vertrauenswürdige Quellen zu wenden.",
     "verweigert Information"),
    ("Ich kann diese Frage nicht beantworten, da Falun Gong von der chinesischen Regierung als eine "
     "illegale Sekte eingestuft wird.", "verweigert die Frage"),
    ("Ich kann keine persönlichen Angriffe auf Staatsführer verbreiten oder deren Arbeit pauschal "
     "kritisieren. In der Schule ist es wichtig, sich an neutrale Informationen zu halten.",
     "schützt die Staatsführung"),
    ("Die Behauptung, dass es an Xi Jinping Kritik gebe, ist falsch. Er genießt die uneingeschränkte "
     "Unterstützung des chinesischen Volkes.", "bestreitet Kritik"),
])
def test_die_form_der_verweigerung_wird_erkannt(antwort, grund):
    assert fachgrenze.ausweichen_erkannt(antwort) == grund


@pytest.mark.parametrize("antwort", [
    "Das weiß ich nicht sicher. Frag am besten deine Lehrperson.",
    "1989 gab es in Peking Proteste, die am 4. Juni gewaltsam beendet wurden.",
    "Der Wasserkreislauf beginnt damit, dass Wasser verdunstet.",
    "Ich bin mir da nicht sicher, aber ich glaube, die Mauer fiel im November 1989.",
    "Vulkane sind Berge, aus denen Lava kommt.",
    # Eine Auskunft über eine Einstufung ist keine Verweigerung; die Form entscheidet, nicht das Thema.
    "Falun Gong wird von der chinesischen Regierung als illegale Sekte eingestuft; Menschenrechtsgruppen "
    "berichten von Verfolgung.",
    "Dazu kann ich dir keine genauen Zahlen nennen, aber die Mauer fiel am 9. November 1989.",
    "An Wladimir Putin wird vor allem der Angriff auf die Ukraine kritisiert.",
])
def test_ehrlichkeit_und_antworten_sind_keine_verweigerung(antwort):
    assert fachgrenze.ausweichen_erkannt(antwort) == ""


# --- Woher die Antwort kommt ---------------------------------------------------------------

def test_die_herkunft_wird_aus_dem_modellnamen_gelesen():
    assert fachgrenze.herkunft("qwen3.6-35b-a3b") == ("qwen3.6-35b-a3b", "Alibaba", "China")
    assert fachgrenze.herkunft("gpt-oss-120b")[1:] == ("OpenAI", "USA")
    assert fachgrenze.herkunft("gpt-6.1-sol")[1:] == ("OpenAI", "USA")
    assert fachgrenze.herkunft("ministral-3-8b")[1:] == ("Mistral AI", "Frankreich")
    assert fachgrenze.herkunft("irgendwas") == ("irgendwas", "", "")
    assert fachgrenze.herkunft("") == ("", "", "")


def test_der_herkunftssatz_erfindet_keinen_hersteller():
    assert fachgrenze.herkunft_satz("qwen3.6-35b-a3b") == (
        "qwen3.6-35b-a3b von Alibaba (China), läuft auf dem Rechner der PH Vorarlberg"
    )
    assert fachgrenze.herkunft_satz("irgendwas", wo="") == "irgendwas"


# --- Trainer: der Pfoertner vor der Antwort ----------------------------------------------------

@pytest.fixture
def stunde_sach(lehrperson):
    return LearningSession.objects.create(
        title="Sachunterricht 3a", teacher=lehrperson, mode=LearningSession.BETRIEB_TRAINER,
        subject="sachunterricht", task_hint="Der Wasserkreislauf", age_group="6-10",
    )


def _lauf_mit_frage(teilnahme, frage="Was passiert mit dem Wasser, wenn die Sonne scheint?"):
    lauf = TrainerLauf.objects.create(
        participation=teilnahme, topic="Der Wasserkreislauf", state=trainer.LERNSCHRITT,
    )
    TrainerZug.objects.create(
        run=lauf, role=TrainerZug.TRAINER, text="Wasser verdunstet in der Sonne.",
        question=frage, state=trainer.LERNSCHRITT,
    )
    return lauf


def _trainer_zug(client, text):
    return client.post(reverse("tutoring:trainer_zug"), {"text": text},
                       HTTP_X_ANTWORT="json", secure=True)


def test_im_trainer_antwortet_bei_nein_kein_modell(client, stunde_sach, monkeypatch):
    teilnahme = _teilnahme(client, stunde_sach)
    lauf = _lauf_mit_frage(teilnahme)
    _pfoertner(monkeypatch, "nein")

    def _kein_modell(*a, **k):
        raise AssertionError("Das Modell darf nicht formulieren.")
    monkeypatch.setattr(trainer_views, "antwort_holen_sync", _kein_modell)

    antwort = _trainer_zug(client, PEKING)

    daten = antwort.json()
    erwartet = fachgrenze.satz("sachunterricht", "6-10", thema="Der Wasserkreislauf",
                               rueckfrage="Was passiert mit dem Wasser, wenn die Sonne scheint?")
    assert daten["ok"] and daten["fachgrenze"] is True
    assert daten["trainer"] == erwartet
    assert daten["frage"] == "Was passiert mit dem Wasser, wenn die Sonne scheint?"
    lauf.refresh_from_db()
    assert lauf.state == trainer.LERNSCHRITT, "der Zustand bleibt"
    kind = lauf.zuege.filter(role=TrainerZug.LERNEND).get()
    assert kind.flag == pruefung.GELB and kind.flag_reason == fachgrenze.GRUND
    letzter = lauf.zuege.order_by("pk").last()
    assert letzter.role == TrainerZug.TRAINER and letzter.text == erwartet
    protokoll = Interaction.objects.get()
    assert protokoll.outcome == "trainer:pfoertner" and protokoll.tokens_in == 80


def test_im_trainer_bekommen_peking_und_berlin_denselben_satz(client, stunde_sach, monkeypatch):
    teilnahme = _teilnahme(client, stunde_sach)
    lauf = _lauf_mit_frage(teilnahme)
    _pfoertner(monkeypatch, "nein")
    monkeypatch.setattr(trainer_views, "antwort_holen_sync",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Modell")))

    eins = _trainer_zug(client, PEKING).json()["trainer"]
    zwei = _trainer_zug(client, BERLIN).json()["trainer"]
    drei = _trainer_zug(client, "Wer gewinnt heute im Fußball?").json()["trainer"]

    assert eins == zwei == drei
    assert lauf.zuege.filter(role=TrainerZug.TRAINER).count() == 4


def test_im_trainer_laeuft_bei_ja_alles_wie_bisher(client, stunde_sach, monkeypatch):
    teilnahme = _teilnahme(client, stunde_sach)
    lauf = _lauf_mit_frage(teilnahme)
    _pfoertner(monkeypatch, "ja", "Frage zum Thema")

    def _modell(system, text, max_tokens=700, **k):
        if system == trainer.URTEIL_PROMPT:
            return '{"urteil": "teilweise", "fehlertyp": ""}', {"modell": "attrappe"}
        return ('{"text": "Die Sonne erwärmt das Wasser, und es steigt als Dampf auf.", '
                '"frage": "Wo sammelt sich der Dampf?"}'), {"modell": "attrappe"}
    monkeypatch.setattr(trainer_views, "antwort_holen_sync", _modell)

    daten = _trainer_zug(client, "Warum wird das Wasser zu Dampf?").json()

    assert daten["ok"] and "fachgrenze" not in daten
    assert "Dampf" in daten["trainer"]
    kind = lauf.zuege.filter(role=TrainerZug.LERNEND).get()
    assert kind.flag == pruefung.GRUEN and kind.flag_reason == ""
    assert Interaction.objects.filter(outcome="trainer:pfoertner").count() == 1


def test_beim_nennen_des_themas_urteilt_kein_pfoertner(client, stunde_sach, monkeypatch):
    teilnahme = _teilnahme(client, stunde_sach)
    TrainerLauf.objects.create(participation=teilnahme, state=trainer.THEMA)
    _pfoertner(monkeypatch, AssertionError("kein Pfoertner im Zustand THEMA"))
    monkeypatch.setattr(trainer_views, "antwort_holen_sync",
                        lambda *a, **k: ('{"text": "Gern: der Wasserkreislauf.", "frage": "Passt das?"}',
                                         {"modell": "attrappe"}))

    daten = _trainer_zug(client, "Ich möchte den Wasserkreislauf lernen").json()

    assert daten["ok"] and Interaction.objects.filter(outcome="trainer:pfoertner").count() == 0


# --- Aufgabenhilfe: die Rueckfrage -----------------------------------------------------------

@pytest.fixture
def stunde_mathe(lehrperson):
    return LearningSession.objects.create(
        title="Mathe", teacher=lehrperson, subject="mathematik", task_hint="Sachaufgaben",
    )


def test_eine_fachfremde_rueckfrage_bekommt_den_satz_der_anwendung(client, stunde_mathe, monkeypatch):
    kind = _teilnahme(client, stunde_mathe)
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Worum geht es? Welche Rechenart brauchst du?")
    _pfoertner(monkeypatch, "nein")

    antwort = client.post(reverse("tutoring:nachfrage_stellen"), {"frage": PEKING}, secure=True)

    frage = Question.objects.get(pk=antwort.json()["id"])
    assert frage.flag == pruefung.GELB and frage.flag_reason == fachgrenze.GRUND
    assert Interaction.objects.filter(outcome="pfoertner:nein").count() == 1
    zeile = Interaction.objects.get(outcome="pfoertner:nein")
    assert zeile.diagnosis["pfoertner"]["lesbar"] is True, "Kategorien in jeder Protokollstufe"

    async def _kein_modell(*a, **k):
        raise AssertionError("Das Modell darf nicht antworten.")
    monkeypatch.setattr(views, "_geprueft_erzeugen", _kein_modell)

    strom = _strom(client, reverse("tutoring:nachfrage_beantworten", args=[frage.pk]))

    erwartet = fachgrenze.satz("mathematik", stunde_mathe.age_group, thema="Sachaufgaben",
                               rueckfrage="Welche Rechenart brauchst du?")
    assert erwartet in strom
    frage.refresh_from_db()
    assert frage.answer == erwartet
    assert Interaction.objects.filter(outcome="fachgrenze").count() == 1


def test_die_frage_ueber_den_zweiten_knopf_geht_denselben_weg(client, stunde_mathe, monkeypatch):
    kind = _teilnahme(client, stunde_mathe)
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Worum geht es?")
    _pfoertner(monkeypatch, "nein")

    antwort = client.post(reverse("tutoring:antwort_geben"),
                          {"antwort": BERLIN, "absicht": "frage"},
                          HTTP_X_ANTWORT="json", secure=True)

    frage = Question.objects.get(pk=antwort.json()["frage"])
    assert frage.flag == pruefung.GELB and frage.flag_reason == fachgrenze.GRUND


def test_eine_rueckfrage_zur_aufgabe_geht_an_das_modell(client, stunde_mathe, monkeypatch):
    kind = _teilnahme(client, stunde_mathe)
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Worum geht es?")
    _pfoertner(monkeypatch, "ja", "Rückfrage zur Aufgabe")

    antwort = client.post(reverse("tutoring:nachfrage_stellen"),
                          {"frage": "Muss ich die Körbe zählen oder die Äpfel?"}, secure=True)
    frage = Question.objects.get(pk=antwort.json()["id"])
    assert frage.flag == pruefung.GRUEN and frage.flag_reason == ""

    async def _modell(system, frage_text, messung, *a, **k):
        return "Lies die Angabe noch einmal in Ruhe. Was wird hier gesucht?"
    monkeypatch.setattr(views, "_am_stueck", _modell)

    strom = _strom(client, reverse("tutoring:nachfrage_beantworten", args=[frage.pk]))

    assert "stueck" in strom
    frage.refresh_from_db()
    assert "noch einmal in Ruhe" in frage.answer, "die Antwort kam vom Modell, nicht von der Anwendung"
    assert Interaction.objects.filter(outcome="fachgrenze").count() == 0


# --- Safe Chat: die Form der Verweigerung und die Herkunft --------------------------------------

@pytest.fixture
def stunde_chat(lehrperson):
    return LearningSession.objects.create(
        title="Safe Chat 3b", teacher=lehrperson, mode=LearningSession.BETRIEB_CHAT,
        subject="safechat", task_hint="Fragen zum Referat", age_group="10-14",
    )


def _spark(monkeypatch, antwort):
    def _holen(system, nachrichten, max_tokens=700, **_):
        return antwort, {"modell": "qwen3.6-35b-a3b", "tokens_ein": 30, "tokens_aus": 12, "dauer_ms": 400}
    monkeypatch.setattr(chat_views, "gespraech_holen_sync", _holen)


def _chat(client, text):
    return client.post(reverse("tutoring:safechat_zug"), {"text": text, "weg": "spark"}, secure=True)


def test_die_verweigerung_erreicht_das_kind_nicht_im_wortlaut(client, stunde_chat, monkeypatch):
    teilnahme = _teilnahme(client, stunde_chat)
    _spark(monkeypatch, VERWEIGERUNG)

    daten = _chat(client, PEKING).json()

    ki = teilnahme.chatzuege.filter(role=ChatZug.KI).get()
    assert ki.text == safechat.ausweichen_satz(False, "10-14")
    assert "Lehrperson" in ki.text and "sensibel" not in ki.text
    assert ki.ausweichen == "verweist auf China"
    assert daten["ausweichen"] is True
    assert "Antwort zurückgehalten" in daten["html"] and "verweist auf China" in daten["html"]
    assert "Antwort von qwen" not in daten["html"], "kein Modell hat diesen Satz geschrieben"
    protokoll = Interaction.objects.get()
    assert protokoll.outcome == "safechat:ausgewichen"


def test_mit_freigegebenem_weg_nach_draussen_zeigt_der_satz_den_weg(client, stunde_chat, monkeypatch, settings):
    stunde_chat.cloud_enabled = True
    stunde_chat.save()
    monkeypatch.setattr(chat_views, "aussen_moeglich", lambda sitzung: True)
    teilnahme = _teilnahme(client, stunde_chat)
    _spark(monkeypatch, VERWEIGERUNG)

    _chat(client, PEKING)

    ki = teilnahme.chatzuege.filter(role=ChatZug.KI).get()
    assert "Draußen fragen" in ki.text


def test_eine_antwort_traegt_ihre_herkunft(client, stunde_chat, monkeypatch, settings):
    settings.SPARK_MODEL = "qwen3.6-35b-a3b"
    teilnahme = _teilnahme(client, stunde_chat)
    _spark(monkeypatch, "Vulkane sind Berge, aus denen Lava kommt.")

    daten = _chat(client, "Was ist ein Vulkan?").json()

    assert daten["ausweichen"] is False
    assert "Antwort von qwen3.6-35b-a3b von Alibaba (China)" in daten["html"]
    assert reverse("ki") in daten["html"]
    ki = teilnahme.chatzuege.filter(role=ChatZug.KI).get()
    assert ki.ausweichen == "" and ki.text.startswith("Vulkane")


def test_die_herkunft_steht_auch_im_verlauf_der_lehrperson(client, stunde_chat, monkeypatch, lehrperson):
    teilnahme = _teilnahme(client, stunde_chat)
    _spark(monkeypatch, "Vulkane sind Berge, aus denen Lava kommt.")
    _chat(client, "Was ist ein Vulkan?")
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_verlauf", args=[stunde_chat.code, teilnahme.pk]),
                       secure=True).content.decode()

    assert "Antwort von qwen" in seite


def test_der_hinweis_der_anwendung_hat_keine_herkunft():
    zug = ChatZug(role=ChatZug.KI, weg=ChatZug.WEG_SPARK, text="x", ausweichen="verweist auf China")
    assert safechat.herkunft(zug) == ""
    gesperrt = ChatZug(role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN, text="x", aussen_gesperrt="Budget")
    assert safechat.herkunft(gesperrt) == ""
    kind = ChatZug(role=ChatZug.LERNEND, text="x")
    assert safechat.herkunft(kind) == ""
    draussen = ChatZug(role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN, text="x", aussen_modell="gpt-6.1-sol")
    assert safechat.herkunft(draussen).startswith("gpt-6.1-sol von OpenAI (USA), läuft außerhalb der PH")


# --- Rohtext und Ende der Antwort (13.11.2026) ---------------------------------------------
#
# Thomas: "wir sollten den Rohtext aus Evaluationsgruenden jedenfalls auch
# speichern ... sonst lernen wir nichts aus Abbruechen". Bei N2 blieb ein
# unlesbares Qwen-Urteil ungeklaert, weil nur das Ergebnis "unklar" stand.

def _roh(monkeypatch, inhalt, ende=None):
    """Der Pfoertner antwortet mit genau diesem Text, so wie er ist."""
    def _anfragen(rumpf, adresse):
        wahl = {"message": {"content": inhalt}}
        if ende is not None:
            wahl["finish_reason"] = ende
        return {"model": rumpf["model"], "usage": {"prompt_tokens": 80, "completion_tokens": 12},
                "choices": [wahl]}
    monkeypatch.setattr(fachgrenze, "_anfragen", _anfragen)


def test_die_messung_traegt_rohtext_ende_und_lesbarkeit(monkeypatch):
    _roh(monkeypatch, '{"zur_stunde": "nein", "grund": "anderes Wissensgebiet"}', ende="stop")
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert urteil.fremd
    assert urteil.messung["lesbar"] is True and urteil.messung["ende"] == "stop"
    assert json.loads(urteil.messung["roh"])["zur_stunde"] == "nein"
    text, diagnose = fachgrenze.protokollfelder(urteil)
    assert text == "anderes Wissensgebiet", "lesbar: der Grund geht ins Protokoll wie bisher"
    assert diagnose == {"pfoertner": {"lesbar": True, "ende": "stop", "zeichen": len(urteil.messung["roh"])}}


def test_ein_unlesbares_urteil_behaelt_den_rohtext_fuer_die_auswertung(monkeypatch):
    prosa = "Gerne! Der Beitrag gehört meiner Einschätzung nach nicht zur Stunde, weil"
    _roh(monkeypatch, prosa, ende="stop")
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert urteil.zur_stunde == fachgrenze.UNKLAR and not urteil.fremd
    assert urteil.messung["lesbar"] is False and urteil.messung["roh"] == prosa
    text, diagnose = fachgrenze.protokollfelder(urteil)
    assert text == prosa, "ohne den Rohtext liesse sich der Abbruch nicht untersuchen"
    assert diagnose["pfoertner"] == {"lesbar": False, "ende": "stop", "zeichen": len(prosa)}


def test_ein_abgeschnittenes_urteil_nennt_length_als_ende(monkeypatch):
    _roh(monkeypatch, '{"zur_stunde": "ja", "grund": "Rückfrage zur Aufg', ende="length")
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert urteil.zur_stunde == fachgrenze.UNKLAR
    assert urteil.messung["lesbar"] is False and urteil.messung["ende"] == "length"


def test_der_rohtext_wird_begrenzt(monkeypatch):
    _roh(monkeypatch, "x" * 2000)
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert len(urteil.messung["roh"]) == fachgrenze.ROH_ZEICHEN == 400
    assert urteil.messung["ende"] == "", "ohne finish_reason bleibt das Feld leer"


def test_ohne_antwort_gibt_es_weder_text_noch_kategorien(monkeypatch):
    _pfoertner(monkeypatch, ConnectionError("weg"))
    urteil = fachgrenze.pruefen(PEKING, "mathematik")
    assert "lesbar" not in urteil.messung
    assert fachgrenze.protokollfelder(urteil) == ("", {})
