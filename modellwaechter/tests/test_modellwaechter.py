"""Der Modellwaechter: Quellen, Grundbestand, Meldung, Einordnung, Seite.

Kein Netz: Der HTTP-Client ist eine Attrappe mit einer Tabelle, der Spark
ist ersetzt. Die Pruefungen, die zaehlen: Der erste Lauf meldet nichts
(Grundbestand), der zweite genau das Neue; eine stumme Quelle haelt die
anderen nicht auf; der Schluessel des OpenAI-Kontos steht nirgends.
"""

import io
import json

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from modellwaechter import einordnung, pruefen, quellen
from modellwaechter.models import Fund, Lauf
from tutoring import spark

pytestmark = pytest.mark.django_db

SCHLUESSEL = "sk-geheim-nur-im-test-123"

HF_QWEN = [
    {"id": "Qwen/Qwen3.6-35B-A3B", "createdAt": "2026-04-16T08:00:00.000Z",
     "lastModified": "2026-11-01T00:00:00.000Z", "pipeline_tag": "image-text-to-text",
     "tags": ["license:apache-2.0", "vllm", "safetensors"], "library_name": "transformers",
     "downloads": 12345, "likes": 300},
]
HF_QWEN_NEU = HF_QWEN + [
    {"id": "Qwen/Qwen3.8-27B-FP8", "createdAt": "2026-11-07T10:12:33.000Z",
     "pipeline_tag": "image-text-to-text", "tags": ["license:apache-2.0"]},
]
OPENROUTER = {"data": [
    {"id": "openai/gpt-5", "name": "OpenAI: GPT-5", "created": 1754600000,
     "description": "Das Flaggschiff.", "context_length": 400000,
     "architecture": {"modality": "text+image->text", "input_modalities": ["text", "image"]},
     "pricing": {"prompt": "0.00000125", "completion": "0.00001"}},
]}
GITHUB = [
    {"tag_name": "v0.20.0", "name": "v0.20.0", "published_at": "2026-11-05T18:00:00Z",
     "html_url": "https://github.com/vllm-project/vllm/releases/tag/v0.20.0",
     "prerelease": False, "draft": False, "body": "Unterstützt jetzt Qwen3.8."},
]
OPENAI = {"data": [{"id": "gpt-5.6", "object": "model", "created": 1760000000, "owned_by": "openai"}]}
MODELLKARTE = "---\nlicense: apache-2.0\nlanguage: [en, de]\n---\n# Qwen3.8-27B\n27 Milliarden Parameter, Bild und Text."


class Antwort:
    def __init__(self, daten, status=200):
        self.daten, self.status = daten, status

    def raise_for_status(self):
        if self.status >= 400:
            anfrage = httpx.Request("GET", "https://attrappe")
            raise httpx.HTTPStatusError("Fehler", request=anfrage, response=httpx.Response(self.status))

    def json(self):
        if isinstance(self.daten, str):
            raise ValueError("kein JSON")
        return self.daten

    @property
    def text(self):
        return self.daten if isinstance(self.daten, str) else json.dumps(self.daten)


class Attrappe:
    """Ein httpx.Client, der aus einer Tabelle antwortet (Muster in der Adresse -> Daten)."""

    def __init__(self, tabelle):
        self.tabelle = tabelle
        self.aufrufe = []

    def get(self, adresse, headers=None):
        self.aufrufe.append((adresse, dict(headers or {})))
        for muster, daten in self.tabelle.items():
            if muster in adresse:
                if isinstance(daten, Antwort):
                    return daten
                return Antwort(daten)
        raise httpx.ConnectError("keine Attrappe für " + adresse)

    def close(self):
        pass


def tabelle(hf=HF_QWEN, **mehr):
    t = {"api/models?author=Qwen": hf, "openrouter.ai": OPENROUTER,
         "api.github.com": GITHUB, "api.openai.com/v1/models": OPENAI}
    t.update(mehr)
    return t


@pytest.fixture
def einstellungen(settings):
    settings.MODELLWAECHTER_HF_AUTOREN = ["Qwen"]
    settings.MODELLWAECHTER_GITHUB_REPOS = ["vllm-project/vllm"]
    settings.MODELLWAECHTER_OPENROUTER = True
    settings.MODELLWAECHTER_OPENAI_KONTO = True
    settings.MODELLWAECHTER_EINORDNUNGEN_JE_LAUF = 10
    settings.CLOUD_BASE_URL = "https://api.openai.com/v1"
    settings.CLOUD_API_KEY = SCHLUESSEL
    settings.EMAIL_HOST = ""
    settings.DEFAULT_FROM_EMAIL = ""
    settings.MODELLWAECHTER_EMPFAENGER = []
    return settings


# --- Die Quellen ---------------------------------------------------------------

def test_hugging_face_liefert_kennung_lizenz_aufgabe_und_datum():
    eintraege = quellen.huggingface(Attrappe(tabelle()), "Qwen")

    assert len(eintraege) == 1
    e = eintraege[0]
    assert e["kennung"] == "Qwen/Qwen3.6-35B-A3B"
    assert e["lizenz"] == "apache-2.0"
    assert e["aufgabe"] == "image-text-to-text"
    assert e["adresse"] == "https://huggingface.co/Qwen/Qwen3.6-35B-A3B"
    assert e["veroeffentlicht"].year == 2026 and e["veroeffentlicht"].month == 4
    assert "license:apache-2.0" not in e["merkmale"]["tags"] and "vllm" in e["merkmale"]["tags"]


def test_openrouter_nennt_anbieter_eingaenge_und_preis_je_million():
    e = quellen.openrouter(Attrappe(tabelle()))[0]

    assert e["anbieter"] == "openai" and e["kennung"] == "openai/gpt-5"
    assert e["merkmale"]["eingaenge"] == ["text", "image"]
    assert e["merkmale"]["usd_je_million_ein"] == 1.25
    assert e["beschreibung"] == "Das Flaggschiff."
    assert e["veroeffentlicht"].year == 2025


def test_github_nimmt_nur_adressen_von_github():
    fremd = [dict(GITHUB[0], html_url="https://boese.example/klick")]
    e = quellen.github_releases(Attrappe({"api.github.com": fremd}), "vllm-project/vllm")[0]

    assert e["adresse"] == "https://github.com/vllm-project/vllm/releases/tag/v0.20.0"
    assert e["beschreibung"] == "Unterstützt jetzt Qwen3.8."


def test_das_openai_konto_schickt_den_schluessel_nur_im_kopf():
    client = Attrappe(tabelle())
    eintraege = quellen.openai_konto(client, "https://api.openai.com/v1", SCHLUESSEL)

    assert eintraege[0]["kennung"] == "gpt-5.6"
    adresse, kopf = client.aufrufe[0]
    assert SCHLUESSEL not in adresse and kopf["Authorization"] == f"Bearer {SCHLUESSEL}"


def test_eine_quelle_ohne_antwort_wirft_die_art_und_nicht_den_text():
    with pytest.raises(quellen.QuelleGescheitert) as fehler:
        quellen.openrouter(Attrappe({}))
    assert fehler.value.art == "ConnectError"

    with pytest.raises(quellen.QuelleGescheitert) as fehler:
        quellen.huggingface(Attrappe({"api/models": Antwort({"error": "zu"}, 429)}), "Qwen")
    assert fehler.value.art == "HTTPStatusError"


def test_fremder_text_wird_gekuerzt_und_falsche_typen_uebergangen():
    kaputt = [{"id": 42}, "kein Woerterbuch", {"id": "Qwen/x" * 100, "tags": "keine Liste", "createdAt": "gestern"}]
    eintraege = quellen.huggingface(Attrappe({"api/models": kaputt}), "Qwen")

    assert len(eintraege) == 1
    assert len(eintraege[0]["kennung"]) == 200
    assert eintraege[0]["veroeffentlicht"] is None and eintraege[0]["lizenz"] == ""


# --- Der Durchlauf -------------------------------------------------------------

def test_der_erste_lauf_ist_der_grundbestand_und_meldet_nichts(einstellungen):
    neue, laeufe = pruefen.durchlauf(client=Attrappe(tabelle()))

    assert neue == []
    assert len(laeufe) == 4 and all(l.ergebnis == Lauf.OK and l.grundbestand for l in laeufe)
    assert Fund.objects.count() == 4 and not Fund.objects.filter(grundbestand=False).exists()


def test_der_zweite_lauf_findet_genau_das_neue_modell(einstellungen):
    pruefen.durchlauf(client=Attrappe(tabelle()))
    neue, laeufe = pruefen.durchlauf(client=Attrappe(tabelle(hf=HF_QWEN_NEU)))

    assert [f.kennung for f in neue] == ["Qwen/Qwen3.8-27B-FP8"]
    assert neue[0].grundbestand is False and neue[0].lizenz == "apache-2.0"
    hf = next(l for l in laeufe if l.quelle == quellen.HUGGINGFACE)
    assert hf.neu == 1 and hf.gesehen == 2 and not hf.grundbestand
    assert sum(l.neu for l in laeufe) == 1
    # Ein dritter Lauf mit denselben Daten findet nichts mehr.
    assert pruefen.durchlauf(client=Attrappe(tabelle(hf=HF_QWEN_NEU)))[0] == []


def test_eine_stumme_quelle_haelt_die_anderen_nicht_auf(einstellungen):
    t = tabelle()
    del t["openrouter.ai"]
    neue, laeufe = pruefen.durchlauf(client=Attrappe(t))

    je_quelle = {l.quelle: l for l in laeufe}
    assert je_quelle[quellen.OPENROUTER].ergebnis == Lauf.FEHLER
    assert je_quelle[quellen.OPENROUTER].fehlerart == "ConnectError"
    assert all(l.ergebnis == Lauf.OK for q, l in je_quelle.items() if q != quellen.OPENROUTER)
    # Beim naechsten Mal ist OpenRouter zum ersten Mal da: dann Grundbestand, nichts Neues.
    neue, laeufe = pruefen.durchlauf(client=Attrappe(tabelle()))
    assert neue == [] and next(l for l in laeufe if l.quelle == quellen.OPENROUTER).grundbestand


def test_nur_schraenkt_auf_quellen_ein(einstellungen):
    neue, laeufe = pruefen.durchlauf(client=Attrappe(tabelle()), nur={"huggingface:Qwen", "github"})

    assert sorted(l.quelle for l in laeufe) == ["github", "huggingface"]


def test_der_schluessel_steht_in_keinem_lauf_fund_oder_protokoll(einstellungen, caplog):
    t = tabelle(**{"api.openai.com/v1/models": Antwort({"error": "unauthorized"}, 401)})
    with caplog.at_level("WARNING"):
        pruefen.durchlauf(client=Attrappe(t))
        pruefen.durchlauf(client=Attrappe(tabelle()))

    gespeichert = " ".join(
        str(w) for l in Lauf.objects.all() for w in (l.quelle, l.anbieter, l.fehlerart)
    ) + " ".join(
        str(w) for f in Fund.objects.all()
        for w in (f.kennung, f.name, f.adresse, f.beschreibung, json.dumps(f.merkmale))
    )
    assert SCHLUESSEL not in gespeichert
    assert SCHLUESSEL not in caplog.text
    assert Lauf.objects.filter(quelle=quellen.OPENAI, ergebnis=Lauf.FEHLER, fehlerart="HTTPStatusError").exists()


# --- Die Meldung ---------------------------------------------------------------

def _neue(einstellungen):
    pruefen.durchlauf(client=Attrappe(tabelle()))
    return pruefen.durchlauf(client=Attrappe(tabelle(hf=HF_QWEN_NEU)))[0]


def test_ohne_mailserver_geht_keine_mail_hinaus(einstellungen):
    neue = _neue(einstellungen)

    assert pruefen.mail_moeglich() is False
    assert pruefen.melden(neue) is False
    assert mail.outbox == [] and neue[0].gemeldet_am is None


def test_mit_mailserver_geht_der_bericht_an_die_empfaenger(einstellungen):
    einstellungen.EMAIL_HOST = "smtp.example.org"
    einstellungen.DEFAULT_FROM_EMAIL = "lab@example.org"
    einstellungen.MODELLWAECHTER_EMPFAENGER = ["eine@example.org", "zwei@example.org"]
    neue = _neue(einstellungen)
    neue[0].einordnung = "Ein dichtes Modell mit 27 Milliarden Parametern."
    neue[0].einordnung_modell = "qwen3.6-35b-a3b"
    neue[0].save()

    assert pruefen.melden(neue) is True
    assert len(mail.outbox) == 1
    nachricht = mail.outbox[0]
    assert nachricht.to == ["eine@example.org", "zwei@example.org"]
    assert "1 neue Modelle" in nachricht.subject
    assert "Qwen/Qwen3.8-27B-FP8" in nachricht.body and "07.11.2026" in nachricht.body
    assert "27 Milliarden" in nachricht.body and "zusammengefasst von qwen3.6-35b-a3b" in nachricht.body
    assert Fund.objects.get(pk=neue[0].pk).gemeldet_am is not None


def test_der_bericht_ohne_funde_wird_nicht_verschickt(einstellungen):
    einstellungen.EMAIL_HOST = "smtp.example.org"
    einstellungen.DEFAULT_FROM_EMAIL = "lab@example.org"
    einstellungen.MODELLWAECHTER_EMPFAENGER = ["eine@example.org"]

    assert pruefen.melden([]) is False and mail.outbox == []


# --- Die Einordnung ------------------------------------------------------------

def test_die_einordnung_liest_die_modellkarte_und_nennt_das_modell(einstellungen, monkeypatch):
    gesehen = {}

    def spark_attrappe(system, text, max_tokens=700, temperatur=0.0):
        gesehen["system"], gesehen["text"] = system, text
        return "Qwen3.8-27B ist ein Sprachmodell mit Bild. 27 Milliarden Parameter, Apache 2.0.", \
            {"modell": "qwen3.6-35b-a3b", "tokens_ein": 900, "tokens_aus": 40, "dauer_ms": 1200}

    monkeypatch.setattr(spark, "antwort_holen_sync", spark_attrappe)
    neue = _neue(einstellungen)
    client = Attrappe(tabelle(**{"Qwen/Qwen3.8-27B-FP8/raw/main/README.md": MODELLKARTE}))

    assert pruefen.einordnen(neue, client=client) == 1
    fund = Fund.objects.get(kennung="Qwen/Qwen3.8-27B-FP8")
    assert fund.einordnung.startswith("Qwen3.8-27B ist ein Sprachmodell")
    assert fund.einordnung_modell == "qwen3.6-35b-a3b" and fund.einordnung_am is not None
    assert "27 Milliarden Parameter" in gesehen["text"] and "Kennung: Qwen/Qwen3.8-27B-FP8" in gesehen["text"]
    assert "nicht an dich" in gesehen["system"]


def test_ohne_spark_bleibt_die_einordnung_leer_und_der_lauf_steht(einstellungen, monkeypatch):
    def ausgefallen(*args, **kwargs):
        raise spark.SparkNichtErreichbar()

    monkeypatch.setattr(spark, "antwort_holen_sync", ausgefallen)
    neue = _neue(einstellungen)
    client = Attrappe(tabelle(**{"raw/main/README.md": MODELLKARTE}))

    assert pruefen.einordnen(neue, client=client) == 0
    assert Fund.objects.get(kennung="Qwen/Qwen3.8-27B-FP8").einordnung == ""


def test_ohne_modellkarte_wird_der_spark_nicht_gefragt(einstellungen, monkeypatch):
    gefragt = []
    monkeypatch.setattr(spark, "antwort_holen_sync", lambda *a, **k: gefragt.append(1) or ("x", {}))
    neue = _neue(einstellungen)

    assert pruefen.einordnen(neue, client=Attrappe({})) == 0
    assert gefragt == []


def test_der_quelltext_fuer_openrouter_ist_die_beschreibung(einstellungen):
    fund = Fund(quelle=quellen.OPENROUTER, kennung="openai/gpt-5", beschreibung="Das Flaggschiff.")

    assert einordnung.quelltext(fund, Attrappe({})) == "Das Flaggschiff."


# --- Der Befehl ----------------------------------------------------------------

def test_der_befehl_berichtet_grundbestand_und_dann_das_neue(einstellungen, monkeypatch):
    daten = {"hf": HF_QWEN}
    monkeypatch.setattr(pruefen, "client_bauen", lambda: Attrappe(tabelle(hf=daten["hf"])))

    aus = io.StringIO()
    call_command("modelle_pruefen", "--ohne-einordnung", "--ohne-mail", stdout=aus)
    assert "Grundbestand" in aus.getvalue() and "0 neu" in aus.getvalue()

    daten["hf"] = HF_QWEN_NEU
    aus = io.StringIO()
    call_command("modelle_pruefen", "--ohne-einordnung", stdout=aus)
    text = aus.getvalue()
    assert "huggingface Qwen: 2 gesehen, 1 neu" in text
    assert "1 neu, 0 eingeordnet, keine E-Mail (nicht eingerichtet)." in text


def test_der_befehl_mit_nur_fragt_nur_diese_quelle(einstellungen, monkeypatch):
    monkeypatch.setattr(pruefen, "client_bauen", lambda: Attrappe(tabelle()))
    call_command("modelle_pruefen", "--nur", "github", "--ohne-einordnung", stdout=io.StringIO())

    assert list(Lauf.objects.values_list("quelle", flat=True)) == ["github"]


# --- Die Seite -----------------------------------------------------------------

@pytest.fixture
def lab(db):
    return get_user_model().objects.create_user(username="lab", password="geheim", is_staff=True)


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


def test_die_seite_verlangt_anmeldung_und_lab_recht(client, lehrperson):
    adresse = reverse("modellwaechter:uebersicht")
    antwort = client.get(adresse, secure=True)
    assert antwort.status_code == 302 and "anmelden" in antwort["Location"]

    client.force_login(lehrperson)
    assert client.get(adresse, secure=True).status_code == 403


def test_die_seite_zeigt_neues_und_auf_wunsch_den_grundbestand(client, lab, einstellungen):
    neue = _neue(einstellungen)
    neue[0].einordnung = "Drei Sätze vom Spark."
    neue[0].einordnung_modell = "qwen3.6-35b-a3b"
    neue[0].save()
    client.force_login(lab)

    seite = client.get(reverse("modellwaechter:uebersicht"), secure=True)
    text = seite.content.decode()
    assert seite.status_code == 200
    assert "Qwen/Qwen3.8-27B-FP8" in text and "Drei Sätze vom Spark." in text
    assert "Zusammengefasst von qwen3.6-35b-a3b" in text
    assert "Qwen/Qwen3.6-35B-A3B" not in text
    assert "E-Mail ist nicht eingerichtet" in text
    # Die Quellentabelle zeigt je Quelle den juengsten Lauf: nach dem zweiten
    # Durchlauf ist keiner mehr der Grundbestand.
    assert "Die Quellen" in text and "in Ordnung" in text and "Grundbestand angelegt" not in text

    alles = client.get(reverse("modellwaechter:uebersicht") + "?alle=1", secure=True).content.decode()
    assert "Qwen/Qwen3.6-35B-A3B" in alles and "openai/gpt-5" in alles and "Grundbestand" in alles


def test_nach_dem_ersten_lauf_sagt_die_quellentabelle_grundbestand(client, lab, einstellungen):
    pruefen.durchlauf(client=Attrappe(tabelle()))
    client.force_login(lab)

    text = client.get(reverse("modellwaechter:uebersicht"), secure=True).content.decode()
    assert "Grundbestand angelegt" in text and "Nichts Neues seit dem letzten Blick" in text


def test_gelesen_nimmt_den_fund_von_der_seite(client, lab, einstellungen):
    neue = _neue(einstellungen)
    client.force_login(lab)

    antwort = client.post(reverse("modellwaechter:gelesen", args=[neue[0].pk]), secure=True)
    assert antwort.status_code == 302
    assert Fund.objects.get(pk=neue[0].pk).gelesen is True
    text = client.get(reverse("modellwaechter:uebersicht"), secure=True).content.decode()
    assert "Qwen/Qwen3.8-27B-FP8" not in text and "Nichts Neues seit dem letzten Blick" in text


def test_alle_gelesen_leert_die_liste_aber_nicht_den_grundbestand(client, lab, einstellungen):
    _neue(einstellungen)
    client.force_login(lab)

    client.post(reverse("modellwaechter:alle_gelesen"), secure=True)
    assert not Fund.objects.filter(grundbestand=False, gelesen=False).exists()
    assert Fund.objects.filter(grundbestand=True, gelesen=False).count() == 4


def test_die_kopfzeile_zeigt_den_weg_nur_dem_lab(client, lab, lehrperson):
    client.force_login(lehrperson)
    assert "Modelle</a>" not in client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True).content.decode()

    client.force_login(lab)
    assert "Modelle</a>" in client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True).content.decode()
