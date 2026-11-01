"""Der Aufgabenpool der Lehrperson (Thomas, 1.11.2026).

"Die Lehrperson kann selbst Aufgaben in der Sitzung hochladen, und zwar
nachdem sie laeuft. Dann im System den Schuelern zur Verfuegung gestellt, und
die Schueler haben dann auch gleich einen Coach zu jeder Uebung. Beim
Hochladen kann das System gleich pruefen, ob es die Aufgabe selber loesen
kann bzw. das Frontier-Modell dazunehmen."

Hier laeuft kein Spark und keine Gegenstelle: beide werden ersetzt.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from tutoring import aufgabenpool, cloud, spark
from tutoring.models import (VORGEGEBEN, Interaction, LearningSession,
                             Participation, SessionTask, Task)
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

AUFGABE = "Lena hat 7 Murmeln. Sie bekommt von Omar noch 5 Murmeln dazu. Wie viele Murmeln hat Lena jetzt?"
SPARK_LOESUNG = "WEG: 7 Murmeln und 5 Murmeln zusammenzählen.\nERGEBNIS: 12 Murmeln"
CLOUD_LOESUNG = "WEG: 7 + 5 = 12.\nERGEBNIS: 12 Murmeln"


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _stunde(lehrperson, **werte):
    vorgaben = {"title": "Mathe", "teacher": lehrperson, "subject": "mathematik"}
    vorgaben.update(werte)
    return LearningSession.objects.create(**vorgaben)


def _kind(client, stunde, tier="igel"):
    teilnahme = Participation.objects.create(learning_session=stunde, animal=tier, token=f"t-{tier}")
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.fixture
def spark_loest(monkeypatch):
    gesehen = []

    def antwort_holen_sync(system, text, max_tokens=700, temperatur=0.3):
        gesehen.append({"system": system, "text": text, "temperatur": temperatur})
        return SPARK_LOESUNG, {"modell": "qwen", "tokens_ein": 50, "tokens_aus": 20, "dauer_ms": 900}
    monkeypatch.setattr(spark, "antwort_holen_sync", antwort_holen_sync)
    return gesehen


def _cloud(monkeypatch, loesung=CLOUD_LOESUNG, sperre=None):
    monkeypatch.setattr(cloud, "moeglich", lambda: True)

    def geprueft_loesen(text, verbrauch=None, bild=None):
        if sperre:
            raise cloud.CloudGesperrt("Das Budget dieser Sitzung ist aufgebraucht.", sperre)
        return {"loesung": loesung, "modell": "gpt-test", "maskiert_ein": "[PERS_1] hat 7 Murmeln",
                "maskiert_aus": loesung, "entitaeten": {"PERS": 2}, "tokens_ein": 300,
                "tokens_aus": 40, "dauer_ms": 4000, "umgeschrieben": "", "anweisung": cloud.SYSTEM}
    monkeypatch.setattr(cloud, "geprueft_loesen", geprueft_loesen)


def _hinzufuegen(client, stunde, **felder):
    return client.post(reverse("tutoring:lehrperson_aufgabe_hinzufuegen", args=[stunde.code]),
                       felder, secure=True)


# --- Die Vorpruefung ----------------------------------------------------------------

def test_die_lehrperson_stellt_eine_aufgabe_ein_und_der_spark_loest_sie(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)

    antwort = _hinzufuegen(client, stunde, text=AUFGABE)

    assert antwort.status_code == 302 and "#aufgabenpool" in antwort["Location"]
    vorlage = SessionTask.objects.get()
    assert vorlage.text == AUFGABE and vorlage.position == 1 and vorlage.aktiv
    assert vorlage.spark_solution == SPARK_LOESUNG
    assert vorlage.status == aufgabenpool.STATUS_SPARK
    assert "12 Murmeln" in vorlage.status_text and "Keine Prüfung von draußen" in vorlage.status_text
    assert spark_loest[0]["system"] == cloud.SYSTEM and spark_loest[0]["temperatur"] == 0.0
    # Der Aufruf steht im Forschungsprotokoll.
    zeile = Interaction.objects.get()
    assert zeile.route == Interaction.LOKAL and zeile.tokens_in == 50

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde.code]), secure=True).content.decode()
    assert "Aufgaben für die Klasse" in seite and "Aufgabe 1" in seite
    assert "Spark hat gelöst" in seite and SPARK_LOESUNG.split("\n")[0] in seite
    assert "0 Kinder dran, 0 fertig" in seite


def test_mit_qualitaetssicherung_prueft_die_externe_ki_mit(client, lehrperson, spark_loest, monkeypatch):
    stunde = _stunde(lehrperson, cloud_enabled=True)
    _cloud(monkeypatch)
    client.force_login(lehrperson)

    _hinzufuegen(client, stunde, text=AUFGABE)

    vorlage = SessionTask.objects.get()
    assert vorlage.status == aufgabenpool.STATUS_EINIG
    assert vorlage.checked_solution == CLOUD_LOESUNG and vorlage.checked_model == "gpt-test"
    assert vorlage.checked_at is not None and vorlage.checked_entities == {"PERS": 2}
    assert "dasselbe Ergebnis: 12 Murmeln" in vorlage.status_text
    assert Interaction.objects.filter(route=Interaction.CLOUD, leak_check=Interaction.BESTANDEN).count() == 1


def test_uneinig_gesperrt_und_offen(client, lehrperson, spark_loest, monkeypatch):
    stunde = _stunde(lehrperson, cloud_enabled=True)
    client.force_login(lehrperson)

    _cloud(monkeypatch, loesung="WEG: 7 − 5.\nERGEBNIS: 2 Murmeln")
    _hinzufuegen(client, stunde, text=AUFGABE)
    erste = SessionTask.objects.get(position=1)
    assert erste.status == aufgabenpool.STATUS_UNEINIG
    assert "„12 Murmeln“" in erste.status_text and "„2 Murmeln“" in erste.status_text

    _cloud(monkeypatch, sperre="budget")
    _hinzufuegen(client, stunde, text="Zweite Aufgabe: 3 + 4")
    zweite = SessionTask.objects.get(position=2)
    assert zweite.status == aufgabenpool.STATUS_GESPERRT
    assert "Budget" in zweite.checked_blocked and "gesperrt" in zweite.status_text

    def kaputt(*a, **k):
        raise spark.SparkNichtErreichbar("aus")
    monkeypatch.setattr(spark, "antwort_holen_sync", kaputt)
    _cloud(monkeypatch)
    _hinzufuegen(client, stunde, text="Dritte Aufgabe: 9 − 4")
    dritte = SessionTask.objects.get(position=3)
    assert dritte.status == aufgabenpool.STATUS_OFFEN
    assert "konnte die Aufgabe nicht lösen" in dritte.status_text and "externe KI sagt: 12 Murmeln" in dritte.status_text


def test_ein_foto_wird_vom_spark_abgeschrieben(client, lehrperson, spark_loest, monkeypatch):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)
    monkeypatch.setattr(spark, "text_aus_bild", lambda data_url: (AUFGABE, {}))
    bild = SimpleUploadedFile("aufgabe.jpg", b"\xff\xd8\xff\xe0 kein echtes Bild", content_type="image/jpeg")

    _hinzufuegen(client, stunde, foto=bild)

    vorlage = SessionTask.objects.get()
    assert vorlage.text == AUFGABE and vorlage.image_data_url.startswith("data:image/jpeg;base64,")


def test_ohne_text_und_ohne_lesbares_foto_gibt_es_eine_meldung(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)
    antwort = _hinzufuegen(client, stunde, text="   ")
    assert "fehler=aufgabe" in antwort["Location"]
    assert SessionTask.objects.count() == 0
    seite = client.get(antwort["Location"], secure=True).content.decode()
    assert "Die Aufgabe ist leer" in seite


def test_nur_die_eigene_mathe_sitzung(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    fremde = get_user_model().objects.create_user(username="f", password="x")
    client.force_login(fremde)
    assert _hinzufuegen(client, stunde, text=AUFGABE).status_code == 404
    client.force_login(lehrperson)
    musik = _stunde(lehrperson, subject="musik", mode=LearningSession.BETRIEB_MUSIK)
    _hinzufuegen(client, musik, text=AUFGABE)
    assert SessionTask.objects.count() == 0
    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[musik.code]), secure=True).content.decode()
    assert "Aufgaben für die Klasse" not in seite


def test_entfernen_laesst_begonnene_bearbeitungen_stehen(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)
    _hinzufuegen(client, stunde, text=AUFGABE)
    vorlage = SessionTask.objects.get()
    kind = Participation.objects.create(learning_session=stunde, animal="fuchs", token="t-f")
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, vorlage=vorlage, source=VORGEGEBEN)

    client.post(reverse("tutoring:lehrperson_aufgabe_entfernen", args=[stunde.code, vorlage.pk]), secure=True)

    assert SessionTask.objects.count() == 0
    aufgabe.refresh_from_db()
    assert aufgabe.vorlage is None and aufgabe.text == AUFGABE


# --- Die Kinderseite -------------------------------------------------------------------

def test_das_kind_sieht_den_pool_und_waehlt_eine_aufgabe(client, lehrperson, spark_loest, monkeypatch):
    stunde = _stunde(lehrperson, cloud_enabled=True)
    _cloud(monkeypatch)
    client.force_login(lehrperson)
    _hinzufuegen(client, stunde, text=AUFGABE)
    _hinzufuegen(client, stunde, text="Auf dem Parkplatz stehen 14 Autos. 6 fahren weg. Wie viele bleiben?")
    client.logout()
    kind = _kind(client, stunde)

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert "Aufgaben von deiner Lehrperson" in seite
    assert seite.count("Diese Aufgabe üben") == 2
    assert "12 Murmeln" not in seite, "die Loesungen der Pruefung sieht kein Kind"

    erste = SessionTask.objects.get(position=1)
    antwort = client.post(reverse("tutoring:aufgabe_waehlen"), {"vorlage": erste.pk}, secure=True)

    assert antwort.status_code == 302
    aufgabe = kind.tasks.get()
    assert aufgabe.text == AUFGABE and aufgabe.vorlage == erste and aufgabe.source == VORGEGEBEN
    # Die gepruefte Loesung geht still mit: kein zweiter Weg nach draussen je Kind.
    assert aufgabe.checked_solution == CLOUD_LOESUNG and aufgabe.checked_model == "gpt-test"
    assert aufgabe.hat_qualitaetssicherung
    # Solange die Aufgabe laeuft, steht die Wahl nicht im Weg.
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert "Aufgaben von deiner Lehrperson" not in seite
    assert "von der Lehrperson" in seite or AUFGABE[:30] in seite

    aufgabe.abschliessen()
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert "Noch einmal üben" in seite and "Diese Aufgabe üben" in seite
    assert seite.count("erledigt") >= 1

    # Die Lehrperson sieht, dass ein Kind dran war.
    client.logout()
    client.force_login(lehrperson)
    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[stunde.code]), secure=True).content.decode()
    assert "1 Kind dran, 1 fertig" in seite


def test_eine_fremde_oder_entfernte_vorlage_gibt_keine_aufgabe(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    andere = _stunde(lehrperson)
    fremd = SessionTask.objects.create(session=andere, text="x", position=1)
    inaktiv = SessionTask.objects.create(session=stunde, text="y", position=1, aktiv=False)
    kind = _kind(client, stunde)
    client.post(reverse("tutoring:aufgabe_waehlen"), {"vorlage": fremd.pk}, secure=True)
    client.post(reverse("tutoring:aufgabe_waehlen"), {"vorlage": inaktiv.pk}, secure=True)
    client.post(reverse("tutoring:aufgabe_waehlen"), {"vorlage": "kaputt"}, secure=True)
    assert kind.tasks.count() == 0


def test_die_wahl_schliesst_eine_laufende_eigene_aufgabe_ab(client, lehrperson, spark_loest):
    stunde = _stunde(lehrperson)
    client.force_login(lehrperson)
    _hinzufuegen(client, stunde, text=AUFGABE)
    client.logout()
    kind = _kind(client, stunde)
    eigene = Task.objects.create(participation=kind, text="3 + 4")

    client.post(reverse("tutoring:aufgabe_waehlen"), {"vorlage": SessionTask.objects.get().pk}, secure=True)

    eigene.refresh_from_db()
    assert eigene.ist_abgeschlossen and kind.tasks.count() == 2


def test_der_status_aus_den_loesungen():
    v = SessionTask(text="x", spark_solution="", checked_solution="")
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_OFFEN
    v.spark_solution = "ERGEBNIS: 12"
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_SPARK
    v.checked_blocked = "Budget"
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_GESPERRT
    v.checked_solution = "ERGEBNIS: 12 Murmeln"
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_EINIG
    v.checked_solution = "ERGEBNIS: 2"
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_UNEINIG
    v.spark_solution = "ERGEBNIS: Zeichne eine Gerade."
    v.checked_solution = "ERGEBNIS: eine Gerade durch A"
    assert aufgabenpool.status_fuer(v) == aufgabenpool.STATUS_UNKLAR
    assert aufgabenpool.ergebnis_kurz("WEG: a\nERGEBNIS: 12 Murmeln") == "12 Murmeln"
    assert aufgabenpool.ergebnis_kurz("nur eine Zeile") == "nur eine Zeile"
