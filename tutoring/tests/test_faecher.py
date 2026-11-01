"""Das Fach als Abzweigung, und die Sprachsperre des Sprechcoachs.

Beides sind reine Funktionen ohne Datenbank. Hier steht, was sie zusagen.
"""

import pytest

from tutoring import faecher, sprechcoach


# --- Die Faecher -----------------------------------------------------------

def test_sechs_faecher_und_jedes_fuehrt_irgendwohin():
    """Keine Schaltflaeche, hinter der nichts steht."""
    assert faecher.SCHLUESSEL == ("mathematik", "deutsch", "englisch",
                                  "sachunterricht", "musik", "safechat")
    for f in faecher.FAECHER:
        assert f["betriebsart"] in (faecher.HILFE, faecher.TRAINER,
                                    faecher.SPRACHE, faecher.MUSIK, faecher.CHAT)
        assert f["symbol"] and f["name"] and f["satz"]


def test_ohne_fach_gibt_es_kein_standardfach():
    """Ein stillschweigend vorausgewaehltes Fach waere die alte Falle."""
    assert faecher.fach("") is None
    assert faecher.fach(None) is None
    assert faecher.fach("turnen") is None
    assert faecher.betriebsart("") == faecher.HILFE, "nur als Rueckfall fuer alte Daten"


def test_das_fach_wird_unempfindlich_gelesen():
    assert faecher.fach("  Mathematik ")["schluessel"] == "mathematik"


@pytest.mark.parametrize("fach, einstellung, erwartet", [
    ("mathematik", faecher.EINSTELLUNG_STUFEN, True),
    ("mathematik", faecher.EINSTELLUNG_NIVEAU, False),
    ("englisch", faecher.EINSTELLUNG_NIVEAU, True),
    ("englisch", faecher.EINSTELLUNG_STUFEN, False),
    ("deutsch", faecher.EINSTELLUNG_THEMA, True),
    ("sachunterricht", faecher.EINSTELLUNG_STUFEN, False),
    # Was jedes Fach bekommt, ohne es aufzuzaehlen.
    ("deutsch", faecher.EINSTELLUNG_ALTER, True),
    ("englisch", faecher.EINSTELLUNG_QUALITAET, True),
    ("sachunterricht", faecher.EINSTELLUNG_PROTOKOLL, True),
    ("mathematik", faecher.EINSTELLUNG_RUHEZEIT, True),
    # Mathematik nach dem Benchmark (19.10.2026): die Schulstufe ersetzt die
    # Altersklasse, die anderen Faecher behalten sie.
    ("mathematik", faecher.EINSTELLUNG_SCHULSTUFE, True),
    ("mathematik", faecher.EINSTELLUNG_ALTER, False),
    ("deutsch", faecher.EINSTELLUNG_SCHULSTUFE, False),
    ("englisch", faecher.EINSTELLUNG_ALTER, True),
    # Die Musikstunde: eigene drei Einstellungen, keine Qualitaetssicherung.
    ("musik", faecher.EINSTELLUNG_LIEDDAUER, True),
    ("musik", faecher.EINSTELLUNG_LIEDER, True),
    ("musik", faecher.EINSTELLUNG_GESANG, True),
    ("musik", faecher.EINSTELLUNG_THEMA, True),
    ("musik", faecher.EINSTELLUNG_QUALITAET, False),
    ("musik", faecher.EINSTELLUNG_STUFEN, False),
    ("mathematik", faecher.EINSTELLUNG_LIEDDAUER, False),
    # Unbekanntes Fach braucht nichts.
    ("turnen", faecher.EINSTELLUNG_ALTER, False),
])
def test_welches_fach_welche_einstellung_braucht(fach, einstellung, erwartet):
    assert faecher.braucht(fach, einstellung) is erwartet


def test_die_betriebsart_folgt_aus_dem_fach():
    assert faecher.betriebsart("mathematik") == faecher.HILFE
    assert faecher.betriebsart("englisch") == faecher.SPRACHE
    assert faecher.betriebsart("deutsch") == faecher.TRAINER
    assert faecher.betriebsart("sachunterricht") == faecher.TRAINER


def test_die_zielsprache_steht_am_fach():
    """Wer Englisch unterrichtet, waehlt nicht noch einmal Englisch."""
    assert faecher.sprache("englisch") == "en-GB"
    assert faecher.sprache("mathematik") == sprechcoach.SPRACHE_STANDARD


# --- Die Sprachsperre ------------------------------------------------------
#
# In welche Richtung sie irren darf: nur in eine. Ein englischer Satz darf
# NIE abgewiesen werden. Ein deutscher darf durchrutschen.

@pytest.mark.parametrize("text", [
    "I have a dog.",
    "Yes.",
    "My favourite animal is the cat because it is soft.",
    "",
    "Hello!",
    "I have a Hund",               # ein Kind, das sich mueht
    "ich like football",           # EIN deutscher Marker genuegt nicht
])
def test_englisches_wird_nie_abgewiesen_ohne_erkennung(text):
    assert sprechcoach.ist_zielsprache(text, "en-GB") is True


@pytest.mark.parametrize("text", [
    "Ich habe einen Hund und eine Katze.",
    "Das ist nicht mein Haus, das ist deins.",
    "Ich weiss es nicht, und du?",
])
def test_klar_deutsches_wird_abgewiesen_ohne_erkennung(text):
    assert sprechcoach.ist_zielsprache(text, "en-GB") is False


def test_whisper_hat_das_letzte_wort_wenn_es_die_zielsprache_meldet():
    """Das Modell hat die Aufnahme gehoert, die Wortliste nur den Text."""
    assert sprechcoach.ist_zielsprache("Ich habe einen Hund.", "en-GB", erkannt="en") is True


def test_whisper_meldet_deutsch_dann_abgewiesen():
    assert sprechcoach.ist_zielsprache("Ich habe einen Hund.", "en-GB", erkannt="de") is False


def test_whisper_irrt_bei_einem_wort_die_marker_retten_es():
    """"Yes." als Deutsch erkannt: kein deutscher Marker, also durchlassen?

    Nein - bei Gleichstand null zu null gilt die Meldung von Whisper. Erst
    wenn englische Marker in der MEHRHEIT sind, ueberstimmen sie Whisper.
    """
    assert sprechcoach.ist_zielsprache("Yes.", "en-GB", erkannt="de") is False
    assert sprechcoach.ist_zielsprache("Yes, I have a dog.", "en-GB", erkannt="de") is True


def test_der_satz_der_sperre_steht_in_der_zielsprache():
    assert sprechcoach.nicht_verstanden("en-GB").startswith("Sorry")
    assert sprechcoach.nicht_verstanden("fr-FR").startswith("Désolé")
    assert sprechcoach.nicht_verstanden("xx-YY") == sprechcoach.NICHT_VERSTANDEN["en-GB"]


# --- Der stille Ausweg -----------------------------------------------------

def test_die_hilfe_ist_deutsch_das_beispiel_englisch():
    roh = '{"erklaerung": "Der Coach fragt, welches Tier du magst.", "beispiel": "I like dogs."}'
    hilfe = sprechcoach.hilfe_lesen(roh, "en-GB", "A1")
    assert hilfe["erklaerung"] == "Der Coach fragt, welches Tier du magst."
    assert hilfe["beispiel"] == "I like dogs."


def test_ein_deutsches_beispiel_wird_verworfen():
    """Ein deutsches Beispiel loest die Aufgabe, statt sie sagbar zu machen."""
    roh = '{"erklaerung": "Sag, welches Tier du magst.", "beispiel": "Ich mag Hunde und ich mag Katzen."}'
    hilfe = sprechcoach.hilfe_lesen(roh, "en-GB", "A1")
    assert hilfe["beispiel"] == ""
    assert hilfe["erklaerung"]


def test_kaputtes_json_ergibt_trotzdem_eine_hilfe():
    hilfe = sprechcoach.hilfe_lesen("{{{", "en-GB", "A1")
    assert "Antworte" in hilfe["erklaerung"]
    assert hilfe["beispiel"] == ""


def test_das_beispiel_haelt_das_niveau():
    lang = "I like dogs and cats and horses and cows and sheep and goats and hens."
    roh = '{"erklaerung": "x", "beispiel": "%s"}' % lang
    hilfe = sprechcoach.hilfe_lesen(roh, "en-GB", "A1")
    assert len(hilfe["beispiel"].split()) <= sprechcoach.WOERTER_JE_SATZ["A1"] + 1
