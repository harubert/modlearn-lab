"""Pruefungen der Bildkette (Thomas, 31.10.2026).

Die Lehrperson kann je Sitzung zusaetzlich zur Qualitaetssicherung
freigeben, dass von einem Foto der Aufgabe ein Ausschnitt mit hinausgeht.
Hinaus geht nie das Foto, sondern das, was tutoring/bildkette.py daraus
macht: neu kodiert, maskiert, zugeschnitten, zweimal geprueft. Jeder Zweifel
sperrt. Diese Pruefungen stellen den Spark nach; was er wirklich liefert,
misst benchmark/bildkette/.
"""

import base64
import io
import json

import httpx
import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw

from tutoring import bildkette, cloud, shield, views
from tutoring.models import Interaction, LearningSession, Participation, Task

pytestmark = pytest.mark.django_db


AUFGABE = ("Aufgabe 3. Lisa kauft 4 Packungen mit je 12 Buntstiften. "
           "Wie viele Buntstifte hat sie zusammen?")

# Das Testbild: 800 x 600, ein weisses Feld fuer die gedruckte Aufgabe
# (100..700, 100..250) und ein blaues fuer die Handschrift (100..500,
# 350..450). Die Kaestchen unten sind dieselben Bereiche in Tausendsteln.
GEDRUCKT_PX = (100, 100, 700, 250)
HANDSCHRIFT_PX = (100, 350, 500, 450)
VERORTUNG = [
    {"label": "gedruckte_aufgabe", "bbox_2d": [125, 167, 875, 417]},
    {"label": "handschrift", "bbox_2d": [125, 583, 625, 750]},
]
OHNE_FUNDE = {label: False for label in bildkette.HEIKEL}


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


def _bild(breite=800, hoehe=600):
    bild = Image.new("RGB", (breite, hoehe), (240, 240, 230))
    zeichner = ImageDraw.Draw(bild)
    zeichner.rectangle(GEDRUCKT_PX, fill=(255, 255, 255))
    zeichner.rectangle(HANDSCHRIFT_PX, fill=(30, 60, 150))
    return bild


def _foto(breite=800, hoehe=600, exif=True):
    """Ein JPEG als Data-URL, wahlweise mit Exif wie vom Handy."""
    puffer = io.BytesIO()
    zusatz = {}
    if exif:
        daten = Image.Exif()
        daten[0x010F] = "Musterphone"
        daten[0x0110] = "Modell X"
        zusatz["exif"] = daten.tobytes()
    _bild(breite, hoehe).save(puffer, "JPEG", quality=85, **zusatz)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()


def _dekodiert(data_url):
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


def _spark_nachbau(monkeypatch, verortung=None, pruefung=None, ocr=AUFGABE, namen=(),
                   treffer=()):
    """Spielt den Spark: Verortung, Urteil und OCR, in dieser Reihenfolge.

    ``ocr`` darf eine Liste sein: eine Antwort je OCR-Aufruf, die letzte
    gilt weiter. ``treffer`` ist die Antwort auf die Nachmaskierung.
    Gibt die Liste der Aufrufe zurueck, damit ein Test sehen kann, was die
    Kette gefragt hat und was nicht.
    """
    verortung = VERORTUNG if verortung is None else verortung
    pruefung = OHNE_FUNDE if pruefung is None else pruefung
    ocr_antworten = list(ocr) if isinstance(ocr, list) else [ocr]
    urteile = list(pruefung) if isinstance(pruefung, list) else [pruefung]
    aufrufe = []

    def spark(nachrichten, max_tokens, schema=None, zaehler=None):
        aufrufe.append(schema["name"] if schema else "ocr")
        if zaehler is not None:
            zaehler["ein"] += 100
            zaehler["aus"] += 10
        if schema and schema["name"] == "bereiche":
            return json.dumps({"bereiche": verortung})
        if schema and schema["name"] == "pruefung":
            return json.dumps(urteile.pop(0) if len(urteile) > 1 else urteile[0])
        if schema and schema["name"] == "treffer":
            return json.dumps({"treffer": list(treffer)})
        return ocr_antworten.pop(0) if len(ocr_antworten) > 1 else ocr_antworten[0]

    monkeypatch.setattr(bildkette, "_spark", spark)
    monkeypatch.setattr(shield, "namensfunde", lambda text: list(namen))
    return aufrufe


# --- Schritt 1: laden und neu kodieren ------------------------------------

def test_das_exif_verschwindet_beim_neukodieren():
    """Auch das Exif aus bild.info, das Pillow sonst stillschweigend mitnimmt."""
    bild = bildkette.laden(_foto(exif=True))
    neu = _dekodiert(bildkette.als_data_url(bild))

    assert len(neu.getexif()) == 0
    assert neu.size == (800, 600)


def test_ein_grosses_foto_wird_verkleinert():
    bild = bildkette.laden(_foto(3000, 2000, exif=False))

    assert max(bild.size) == bildkette.LANGE_KANTE


@pytest.mark.parametrize("kaputt", [
    "", "data:text/plain;base64,QUJD", "data:image/jpeg;base64,", "data:image/jpeg;base64,%%%",
    "data:image/jpeg;base64," + base64.b64encode(b"kein bild").decode(),
])
def test_was_kein_bild_ist_sperrt(kaputt):
    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.laden(kaputt)
    assert fehler.value.art == bildkette.ART_UNLESBAR


# --- Schritt 2: die Kaestchen des Modells ---------------------------------

def test_die_kaestchen_werden_in_pixel_uebersetzt():
    bereiche = bildkette.bereiche_aus(VERORTUNG, 800, 600)

    assert [b.label for b in bereiche] == ["gedruckte_aufgabe", "handschrift"]
    x1, y1, x2, y2 = bereiche[0].box
    assert (round(x1), round(y1), round(x2), round(y2)) == (100, 100, 700, 250)


def test_unbrauchbare_eintraege_werden_uebergangen_nicht_geraten():
    eintraege = [
        {"label": "tapete", "bbox_2d": [0, 0, 100, 100]},
        {"label": "name", "bbox_2d": [10, 10, 10, 50]},
        {"label": "name", "bbox_2d": [10, 10, 50]},
        {"label": "name", "bbox_2d": ["a", 10, 50, 50]},
        "unsinn",
        {"label": "gesicht", "bbox_2d": [900, 900, 1500, 1500]},
    ]
    bereiche = bildkette.bereiche_aus(eintraege, 800, 600)

    assert len(bereiche) == 1
    assert bereiche[0].label == "gesicht"
    assert bereiche[0].box == (720.0, 540.0, 800.0, 600.0), "auf das Bild begrenzt"
    assert bildkette.bereiche_aus("nicht einmal eine Liste", 800, 600) == []


# --- Schritt 3: maskieren, dann zuschneiden -------------------------------

def test_die_maske_gewinnt_gegen_den_zuschnitt():
    """Handschrift ueber der Aufgabenzeile: Die Zeile fehlt, nicht die Maske."""
    bild = _bild()
    bereiche = [
        bildkette.Bereich("gedruckte_aufgabe", GEDRUCKT_PX),
        bildkette.Bereich("handschrift", (100, 200, 400, 300)),
    ]
    ausschnitt, masken = bildkette.zuschneiden(bild, bereiche)

    assert masken == {"handschrift": 1, "name": 0, "gesicht": 0, "logo": 0}
    # Der Ausschnitt beginnt RAND Pixel vor dem gedruckten Feld; der Punkt
    # (200, 220) des Bildes liegt in der Ueberlappung und muss schwarz sein.
    rand = bildkette.RAND
    assert ausschnitt.getpixel((200 - 100 + rand, 220 - 100 + rand)) == (0, 0, 0)
    assert ausschnitt.getpixel((600 - 100 + rand, 150 - 100 + rand)) == (255, 255, 255)
    assert ausschnitt.size == (600 + 2 * rand, 150 + 2 * rand)


def test_ohne_gedruckten_bereich_gibt_es_keinen_ausschnitt():
    bereiche = [bildkette.Bereich("handschrift", HANDSCHRIFT_PX)]

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.zuschneiden(_bild(), bereiche)
    assert fehler.value.art == bildkette.ART_KEIN_DRUCK


# --- Die ganze Kette --------------------------------------------------------

def test_die_kette_laeuft_durch(monkeypatch):
    ohne_lisa = AUFGABE.replace("Lisa", "Jemand")
    aufrufe = _spark_nachbau(monkeypatch, ocr=ohne_lisa, namen=[(shield.TYP_PERSON, "Lisa")])

    # Die Namenserkennung meldet Lisa, aber im Ausschnitt steht der Name
    # nicht mehr: nichts nachzumaskieren.
    befund = bildkette.bereinigen(_foto(), AUFGABE)

    assert aufrufe == ["bereiche", "pruefung", "ocr"], "drei Fragen, in dieser Reihenfolge"
    assert befund.data_url.startswith("data:image/jpeg;base64,")
    assert befund.masken["handschrift"] == 1
    assert befund.ocr == ohne_lisa
    assert befund.tokens_ein == 300 and befund.tokens_aus == 30
    ausschnitt = _dekodiert(befund.data_url)
    assert len(ausschnitt.getexif()) == 0
    assert ausschnitt.size == (600 + 2 * bildkette.RAND, 150 + 2 * bildkette.RAND)
    assert ausschnitt.getpixel((5, 5)) != (30, 60, 150), "die Handschrift liegt ausserhalb"


def test_das_urteil_des_modells_sperrt(monkeypatch):
    _spark_nachbau(monkeypatch, pruefung={**OHNE_FUNDE, "gesicht": True})

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_LEAK
    assert "Gesicht" in fehler.value.grund


def test_ein_fehlender_schluessel_im_urteil_zaehlt_als_fund(monkeypatch):
    """Fail-closed: Was das Modell nicht verneint hat, gilt als gesehen."""
    _spark_nachbau(monkeypatch, pruefung={"handschrift": False})

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_LEAK


def test_ein_erkannter_name_in_der_ocr_sperrt(monkeypatch):
    """Zweites Netz: Was die Namenserkennung in der Abschrift fand, darf im
    Ausschnitt nicht lesbar sein. Findet das Modell das Wort zum Maskieren
    nicht, widersprechen sich OCR und Verortung, und der Weg bleibt zu."""
    aufrufe = _spark_nachbau(
        monkeypatch, ocr="Mia  Huber, 3b. " + AUFGABE,
        namen=[(shield.TYP_PERSON, "Mia Huber")], treffer=[],
    )

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE + " Mia Huber")
    assert fehler.value.art == bildkette.ART_LEAK
    assert "ließ sich nicht maskieren" in fehler.value.grund
    assert aufrufe == ["bereiche", "pruefung", "ocr", "treffer"]


def test_ein_gedruckter_name_wird_nachmaskiert(monkeypatch):
    """Lisa kauft vier Packungen: Die Textkette ersetzt Lisa durch einen
    Platzhalter, die Bildkette schwaerzt das Wort und prueft noch einmal."""
    aufrufe = _spark_nachbau(
        monkeypatch,
        ocr=[AUFGABE, "Aufgabe 3. kauft 4 Packungen mit je 12 Buntstiften. Wie viele Buntstifte hat sie zusammen?"],
        namen=[(shield.TYP_PERSON, "Lisa")],
        treffer=[{"wort": "Lisa", "bbox_2d": [100, 300, 180, 420]}],
    )

    befund = bildkette.bereinigen(_foto(), AUFGABE)

    assert aufrufe == ["bereiche", "pruefung", "ocr", "treffer", "pruefung", "ocr"]
    assert befund.masken["name"] == 1, "die Nachmaskierung zaehlt als Name"
    assert "Lisa" not in befund.ocr
    ausschnitt = _dekodiert(befund.data_url)
    # Das Kaestchen (10..18 %, 30..42 % des Ausschnitts) ist schwarz.
    assert ausschnitt.getpixel((int(ausschnitt.width * 0.14), int(ausschnitt.height * 0.36))) == (0, 0, 0)


def test_bleibt_der_name_nach_dem_nachmaskieren_lesbar_ist_der_weg_zu(monkeypatch):
    """Genau ein Versuch, keine Schleife."""
    aufrufe = _spark_nachbau(
        monkeypatch, ocr=AUFGABE,
        namen=[(shield.TYP_PERSON, "Lisa")],
        treffer=[{"wort": "Lisa", "bbox_2d": [100, 300, 180, 420]}],
    )

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_LEAK
    assert fehler.value.woerter == ("Lisa",)
    assert aufrufe.count("treffer") == 1


def test_das_urteil_des_modells_wird_nicht_nachmaskiert(monkeypatch):
    """Nur ein Leck ueber die OCR nennt Woerter; sieht das Modell Handschrift,
    gibt es nichts nachzumaskieren, und der Weg ist sofort zu."""
    aufrufe = _spark_nachbau(monkeypatch, pruefung={**OHNE_FUNDE, "handschrift": True})

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.woerter == ()
    assert "treffer" not in aufrufe


def test_der_gedruckte_name_geht_auch_am_urteil_des_modells_vorbei_nur_maskiert(monkeypatch):
    """Am Spark sagte das Modell zu "Lisa kauft" selbst: Name. Ein lesbarer,
    erkannter Name wird zuerst nachmaskiert; danach muss das Modell den
    Ausschnitt noch einmal freisprechen (so war es in der Probe)."""
    aufrufe = _spark_nachbau(
        monkeypatch,
        pruefung=[{**OHNE_FUNDE, "name": True}, OHNE_FUNDE],
        ocr=[AUFGABE, AUFGABE.replace("Lisa ", "")],
        namen=[(shield.TYP_PERSON, "Lisa")],
        treffer=[{"wort": "Lisa", "bbox_2d": [100, 300, 180, 420]}],
    )

    befund = bildkette.bereinigen(_foto(), AUFGABE)

    assert aufrufe == ["bereiche", "pruefung", "ocr", "treffer", "pruefung", "ocr"]
    assert befund.masken["name"] == 1


def test_bleibt_das_urteil_nach_dem_nachmaskieren_bei_name_ist_der_weg_zu(monkeypatch):
    _spark_nachbau(
        monkeypatch,
        pruefung={**OHNE_FUNDE, "name": True},
        ocr=[AUFGABE, AUFGABE.replace("Lisa ", "")],
        namen=[(shield.TYP_PERSON, "Lisa")],
        treffer=[{"wort": "Lisa", "bbox_2d": [100, 300, 180, 420]}],
    )

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_LEAK
    assert "Name" in fehler.value.grund and fehler.value.woerter == ()


def test_eine_telefonnummer_in_der_ocr_sperrt(monkeypatch):
    _spark_nachbau(monkeypatch, ocr=AUFGABE + " Tel. 0664 1234567")

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_FREMDE_ZAHLEN


def test_ein_ausschnitt_ohne_lesbare_aufgabe_ist_unbrauchbar(monkeypatch):
    _spark_nachbau(monkeypatch, ocr="Aufgabe")

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_UNBRAUCHBAR


def test_nichts_lesbar_ist_auch_unbrauchbar(monkeypatch):
    _spark_nachbau(monkeypatch, ocr="NICHTS")

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_UNBRAUCHBAR


def test_die_textregeln_ohne_zahlen_in_der_abschrift():
    """Eine Aufgabe ohne Zahl (selten) verlangt keine Zahl im Ausschnitt."""
    assert bildkette.pruefen_text("Zeichne ein Quadrat.", "Zeichne ein Quadrat.") is None
    assert bildkette.pruefen_text("", "Zeichne ein Quadrat.") is None


def test_ein_ausfall_am_spark_sperrt(monkeypatch):
    def kaputt(*args, **kwargs):
        raise httpx.ConnectError("weg")

    monkeypatch.setattr(bildkette, "_spark", kaputt)

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_SHIELD_AUS


def test_eine_kaputte_verortung_sperrt(monkeypatch):
    monkeypatch.setattr(bildkette, "_spark", lambda *a, **k: "das ist kein JSON")

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_VERORTUNG


def test_ein_ausfall_der_namenserkennung_sperrt(monkeypatch):
    """Eine Pruefung ohne Namensliste ist keine Pruefung."""
    _spark_nachbau(monkeypatch)

    def kaputt(text):
        raise RuntimeError("Spark weg")

    monkeypatch.setattr(shield, "namensfunde", kaputt)

    with pytest.raises(bildkette.BildGesperrt) as fehler:
        bildkette.bereinigen(_foto(), AUFGABE)
    assert fehler.value.art == bildkette.ART_SHIELD_AUS


def test_die_masken_werden_gezaehlt_nicht_gezeigt():
    assert bildkette.masken_text({"handschrift": 1, "name": 2, "gesicht": 0}) == "1× Handschrift, 2× Name"
    assert bildkette.masken_text({}) == ""


def test_die_verortung_wird_als_json_erzwungen(monkeypatch, settings):
    """Ohne Zwang kamen in der Probe Klammern abhanden."""
    settings.SPARK_BASE_URL = "http://spark.test/v1"
    gesehen = {}

    class Antwort:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"bereiche": []}'}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3}}

    class Client:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            gesehen.update(json)
            return Antwort()

    monkeypatch.setattr(bildkette.httpx, "Client", Client)
    zaehler = {"ein": 0, "aus": 0}
    inhalt = bildkette._spark([{"role": "user", "content": "x"}], 10,
                              schema=bildkette.VERORTEN_SCHEMA, zaehler=zaehler)

    assert inhalt == '{"bereiche": []}'
    assert gesehen["response_format"]["type"] == "json_schema"
    assert gesehen["response_format"]["json_schema"]["name"] == "bereiche"
    assert gesehen["temperature"] == 0.0
    assert zaehler == {"ein": 7, "aus": 3}


# --- Der Weg nach draussen nimmt den Ausschnitt mit ------------------------

def _gegenstelle(monkeypatch):
    gesendet = {}

    def senden(nachrichten, max_tokens):
        gesendet["nachrichten"] = nachrichten
        return ({"choices": [{"message": {"content": "WEG: 4 mal 12.\nERGEBNIS: 48 Buntstifte"}}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "gpt-test"}, 5)

    monkeypatch.setattr(cloud, "_senden", senden)
    monkeypatch.setattr(shield, "neu_formulieren", lambda text: text)
    monkeypatch.setattr(shield, "namensfunde", lambda text: [])
    return gesendet


def test_der_ausschnitt_haengt_am_maskierten_text(settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    gesendet = _gegenstelle(monkeypatch)

    ergebnis = cloud.geprueft_loesen(AUFGABE, bild="data:image/jpeg;base64,QUJD")

    inhalt = gesendet["nachrichten"][1]["content"]
    assert isinstance(inhalt, list)
    assert inhalt[0]["type"] == "text" and cloud.BILD_HINWEIS in inhalt[0]["text"]
    assert inhalt[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}
    assert ergebnis["bild"] is True
    assert cloud.BILD_HINWEIS in ergebnis["maskiert_ein"], "im Verlauf steht, was hinausging"


def test_ohne_ausschnitt_bleibt_der_text_ein_text(settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    gesendet = _gegenstelle(monkeypatch)

    ergebnis = cloud.geprueft_loesen(AUFGABE)

    assert isinstance(gesendet["nachrichten"][1]["content"], str)
    assert ergebnis["bild"] is False
    assert cloud.BILD_HINWEIS not in ergebnis["maskiert_ein"]


# --- Der zweite Schalter ---------------------------------------------------

def test_der_zweite_schalter_ist_aus(lehrperson):
    sitzung = LearningSession.objects.create(title="Probe", teacher=lehrperson)

    assert sitzung.cloud_images_enabled is False


def test_der_zweite_schalter_haengt_am_ersten(client, lehrperson, settings):
    settings.CLOUD_ENABLED = True
    client.force_login(lehrperson)

    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "mathematik", "title": "Ohne QS", "schulstufe": "vs",
        "bilder_pruefen": "ja",
    }, secure=True)
    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "mathematik", "title": "Mit QS", "schulstufe": "vs",
        "qualitaetssicherung": "ja", "bilder_pruefen": "ja",
    }, secure=True)
    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "mathematik", "title": "Nur QS", "schulstufe": "vs",
        "qualitaetssicherung": "ja",
    }, secure=True)

    assert LearningSession.objects.get(title="Ohne QS").cloud_images_enabled is False
    assert LearningSession.objects.get(title="Mit QS").cloud_images_enabled is True
    assert LearningSession.objects.get(title="Nur QS").cloud_images_enabled is False


def test_ohne_zugang_bleibt_auch_der_zweite_schalter_aus(client, lehrperson, settings):
    settings.CLOUD_ENABLED = False
    client.force_login(lehrperson)

    client.post(reverse("tutoring:lehrperson_uebersicht"), {
        "fach": "mathematik", "title": "Kein Zugang", "schulstufe": "vs",
        "qualitaetssicherung": "ja", "bilder_pruefen": "ja",
    }, secure=True)

    sitzung = LearningSession.objects.get(title="Kein Zugang")
    assert sitzung.cloud_enabled is False
    assert sitzung.cloud_images_enabled is False


def test_das_formular_zeigt_den_zweiten_schalter_mit_erklaerung(client, lehrperson, settings):
    settings.CLOUD_ENABLED = True
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_uebersicht"),
                       {"fach": "mathematik"}, secure=True).content.decode()

    assert 'id="bilder_pruefen"' in seite
    assert "zugeschnitten und bereinigt" in seite
    assert "anonymisiert" not in seite.split('id="bilder-hilfe"')[1].split("</p>")[0]
    assert reverse("bildpruefung") in seite
    assert "js/qsschalter." in seite


def test_ohne_zugang_fehlt_der_zweite_schalter(client, lehrperson, settings):
    settings.CLOUD_ENABLED = False
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_uebersicht"),
                       {"fach": "mathematik"}, secure=True).content.decode()

    assert 'id="bilder_pruefen"' not in seite
    assert "js/qsschalter." not in seite


def test_die_erklaerungsseite_sagt_was_nie_hinausgeht(client):
    seite = client.get(reverse("bildpruefung"), secure=True)

    inhalt = seite.content.decode()
    assert seite.status_code == 200
    assert "zugeschnitten und bereinigt" in inhalt
    assert "Lösungsversuch des Kindes" in inhalt
    assert "ohne Metadaten" in inhalt


# --- Die Freigabe je Foto in der Ansicht -----------------------------------

def _stunde(lehrperson, bilder=True, foto=True):
    sitzung = LearningSession.objects.create(
        title="Probe", teacher=lehrperson, cloud_enabled=True,
        cloud_images_enabled=bilder,
    )
    teilnahme = Participation.objects.create(
        learning_session=sitzung, animal="fuchs", token="bk1", log_key="bkl1"
    )
    aufgabe = Task.objects.create(
        participation=teilnahme, text=AUFGABE,
        image_data_url=_foto(exif=False) if foto else "",
    )
    return sitzung, teilnahme, aufgabe


def _befund():
    return bildkette.Bildbefund(
        data_url="data:image/jpeg;base64,QVVT", masken={"handschrift": 1, "name": 1, "gesicht": 0, "logo": 0},
        ocr=AUFGABE, dauer_ms=812, breite=600, hoehe=150, tokens_ein=3000, tokens_aus=90,
    )


LEER = {"aufrufe_sitzung": 0, "aufrufe_tag": 0, "euro_sitzung": 0.0, "euro_tag": 0.0}


def test_ohne_zweiten_schalter_laeuft_keine_bildkette(lehrperson, settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    sitzung, teilnahme, aufgabe = _stunde(lehrperson, bilder=False)
    gerufen = []
    monkeypatch.setattr(bildkette, "bereinigen", lambda *a: gerufen.append(a))

    bild = async_to_sync(views._bild_freigeben)(aufgabe, sitzung, teilnahme, LEER)

    assert bild == "" and gerufen == []
    aufgabe.refresh_from_db()
    assert aufgabe.hat_bildpruefung is False


def test_ohne_foto_laeuft_keine_bildkette(lehrperson, settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    sitzung, teilnahme, aufgabe = _stunde(lehrperson, foto=False)
    monkeypatch.setattr(bildkette, "bereinigen", lambda *a: pytest.fail("nicht rufen"))

    assert async_to_sync(views._bild_freigeben)(aufgabe, sitzung, teilnahme, LEER) == ""


def test_ein_erschoepftes_budget_spart_die_bildkette(lehrperson, settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    settings.CLOUD_AUFRUFE_JE_SITZUNG = 2
    sitzung, teilnahme, aufgabe = _stunde(lehrperson)
    monkeypatch.setattr(bildkette, "bereinigen", lambda *a: pytest.fail("nicht rufen"))

    bild = async_to_sync(views._bild_freigeben)(
        aufgabe, sitzung, teilnahme, {**LEER, "aufrufe_sitzung": 2}
    )

    assert bild == ""


def test_ein_freigegebener_ausschnitt_wird_vermerkt_und_protokolliert(lehrperson, settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    sitzung, teilnahme, aufgabe = _stunde(lehrperson)
    monkeypatch.setattr(bildkette, "bereinigen", lambda data_url, abschrift: _befund())

    bild = async_to_sync(views._bild_freigeben)(aufgabe, sitzung, teilnahme, LEER)

    assert bild == "data:image/jpeg;base64,QVVT"
    aufgabe.refresh_from_db()
    assert aufgabe.bild_bestanden is True
    assert aufgabe.checked_image_sent == bild
    assert aufgabe.checked_image_masks["name"] == 1
    assert aufgabe.checked_image_ms == 812
    assert aufgabe.bild_masken_text == "1× Handschrift, 1× Name"

    zeile = Interaction.objects.get(outcome="bild_bestanden")
    assert zeile.route == Interaction.LOKAL
    assert zeile.leak_check == Interaction.BESTANDEN
    assert zeile.entities_replaced == {"bild_handschrift": 1, "bild_name": 1}
    assert zeile.tokens_in == 3000
    # Im Protokoll steht der Platzhalter wie bei der Abschrift des Fotos,
    # nie ein Bild: keine Data-URL, auf keiner Stufe.
    assert zeile.masked_input in ("", "[Foto]") and zeile.raw_input in ("", "[Foto]")
    assert "data:image" not in zeile.masked_input + zeile.masked_output + zeile.raw_output


def test_ein_gesperrter_bildweg_laesst_den_text_allein_gehen(lehrperson, settings, monkeypatch):
    settings.CLOUD_ENABLED = True
    sitzung, teilnahme, aufgabe = _stunde(lehrperson)

    def gesperrt(data_url, abschrift):
        raise bildkette.BildGesperrt("Die Bildprüfung hat angeschlagen: Gesicht.", art=bildkette.ART_LEAK)

    monkeypatch.setattr(bildkette, "bereinigen", gesperrt)

    bild = async_to_sync(views._bild_freigeben)(aufgabe, sitzung, teilnahme, LEER)

    assert bild == ""
    aufgabe.refresh_from_db()
    assert aufgabe.hat_bildpruefung is True
    assert aufgabe.bild_bestanden is False
    assert aufgabe.checked_image_reason == "Die Bildprüfung hat angeschlagen: Gesicht."
    assert aufgabe.checked_image_sent == ""
    zeile = Interaction.objects.get(outcome="bild_gesperrt")
    assert zeile.error_kind == bildkette.ART_LEAK
    assert zeile.leak_check == Interaction.BLOCKIERT


def test_die_qualitaetssicherung_nimmt_den_ausschnitt_mit(lehrperson, settings, monkeypatch):
    """Der ganze Weg: Bildkette, dann der Aufruf nach draussen mit Bild."""
    settings.CLOUD_ENABLED = True
    sitzung, teilnahme, aufgabe = _stunde(lehrperson)
    monkeypatch.setattr(bildkette, "bereinigen", lambda data_url, abschrift: _befund())
    gesehen = {}

    def loesen(text, verbrauch, bild=None):
        gesehen["bild"] = bild
        return {"loesung": "ERGEBNIS: 48", "umgeschrieben": "", "maskiert_ein": text,
                "maskiert_aus": "ERGEBNIS: 48", "entitaeten": {}, "ersetzt": 0, "bild": bool(bild),
                "modell": "gpt-test", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 2}

    monkeypatch.setattr(cloud, "geprueft_loesen", loesen)

    loesung = async_to_sync(views._qualitaet_sichern)(aufgabe, sitzung, teilnahme)

    assert loesung == "ERGEBNIS: 48"
    assert gesehen["bild"] == "data:image/jpeg;base64,QVVT"
    aufgabe.refresh_from_db()
    assert aufgabe.checked_solution == "ERGEBNIS: 48"
    assert aufgabe.bild_bestanden is True


# --- Der Verlauf zeigt beides nebeneinander ---------------------------------

def _mit_austausch(lehrperson, **bild):
    sitzung, teilnahme, aufgabe = _stunde(lehrperson)
    werte = {
        "checked_at": timezone.now(), "checked_solution": "ERGEBNIS: 48 Buntstifte",
        "checked_model": "gpt-test", "checked_sent": "jemand kauft 4 Packungen",
        "checked_received": "ERGEBNIS: 48 Buntstifte",
    }
    werte.update(bild)
    for feld, wert in werte.items():
        setattr(aufgabe, feld, wert)
    aufgabe.save()
    return sitzung, teilnahme, aufgabe


def test_der_verlauf_zeigt_foto_und_ausschnitt_nebeneinander(client, lehrperson):
    sitzung, teilnahme, _ = _mit_austausch(
        lehrperson, checked_image_check=bildkette.BESTANDEN,
        checked_image_sent="data:image/jpeg;base64,QVVT",
        checked_image_masks={"handschrift": 1, "name": 1}, checked_image_ms=812,
    )
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]), secure=True,
    ).content.decode()

    assert "Der Ausschnitt, der hinausging" in seite
    assert 'src="data:image/jpeg;base64,QVVT"' in seite
    assert "Das Foto des Kindes. Es bleibt im Haus." in seite
    assert "1× Handschrift, 1× Name" in seite
    assert "812 ms" in seite


def test_der_verlauf_nennt_den_grund_wenn_das_foto_blieb(client, lehrperson):
    sitzung, teilnahme, _ = _mit_austausch(
        lehrperson, checked_image_check=bildkette.BLOCKIERT,
        checked_image_reason="Die Bildprüfung hat angeschlagen: Gesicht.",
    )
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]), secure=True,
    ).content.decode()

    assert "Foto nicht hinausgegangen: Die Bildprüfung hat angeschlagen: Gesicht." in seite
    assert "Hinausgegangen ist nur der abgeschriebene Text." in seite
    assert "Der Ausschnitt, der hinausging" not in seite


def test_ohne_bildweg_steht_im_verlauf_nichts_vom_foto(client, lehrperson):
    sitzung, teilnahme, _ = _mit_austausch(lehrperson)
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]), secure=True,
    ).content.decode()

    assert "Foto nicht hinausgegangen" not in seite
    assert "Der Ausschnitt, der hinausging" not in seite


def test_ein_freigegebener_ausschnitt_hinter_gesperrtem_textweg_ging_nicht_hinaus(client, lehrperson):
    sitzung, teilnahme, _ = _mit_austausch(
        lehrperson, checked_at=None, checked_blocked="Der Leak-Check hat angeschlagen: Name.",
        checked_image_check=bildkette.BESTANDEN, checked_image_sent="data:image/jpeg;base64,QVVT",
    )
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, teilnahme.pk]), secure=True,
    ).content.decode()

    assert "war freigegeben, ging aber nicht hinaus" in seite
    assert "Der Weg war danach gesperrt" in seite


def test_der_ausschnitt_stirbt_mit_der_sitzung(lehrperson):
    sitzung, _, aufgabe = _mit_austausch(
        lehrperson, checked_image_check=bildkette.BESTANDEN,
        checked_image_sent="data:image/jpeg;base64,QVVT",
    )

    sitzung.beenden()

    assert not Task.objects.filter(pk=aufgabe.pk).exists()
