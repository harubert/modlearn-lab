"""Gesprächsaufgaben, Ablauf, Rückblick und Messung des Sprechcoachs.

Regeln 11, 12, 6 (zweiter Teil) und 14 aus docs/Gesprächsdidaktik Englisch
für den Sprechcoach.md. Was hier steht, entscheidet der Server und nicht das
Modell: ob eine Aufgabe zum Niveau passt, wann das Ziel erreicht ist, wann
die Phase wechselt, was im Rückblick steht und welche Zahlen die Lehrperson
sieht.
"""

import json
import pathlib
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from tutoring import sprechablauf, sprechaufgaben, sprechcoach, sprechcoach_views
from tutoring.models import LearningSession, Participation, SprachLauf, SprachZug
from tutoring.views import SCHLUESSEL_TEILNAHME

NIVEAUS = tuple(code for code, _ in sprechcoach.NIVEAUS)
GEBURTSTAG = sprechaufgaben.aufgabe("geburtstag")


# --- Die Aufgabenliste -----------------------------------------------------

def test_mindestens_acht_aufgaben_und_das_freie_gespraech():
    assert len(sprechaufgaben.AUFGABEN) >= 8
    assert sprechaufgaben.FREI in sprechaufgaben.auswahl()
    schluessel = [a["schluessel"] for a in sprechaufgaben.AUFGABEN]
    assert len(schluessel) == len(set(schluessel)), "kein Schluessel doppelt"


@pytest.mark.parametrize("aufgabe", sprechaufgaben.AUFGABEN,
                         ids=lambda a: a["schluessel"])
def test_jede_aufgabe_ist_vollstaendig(aufgabe):
    for feld in ("schluessel", "titel", "ziel", "ziel_deutsch", "rolle_coach",
                 "rolle_wiederholung", "geheimnis", "wechsel"):
        assert aufgabe[feld].strip(), f"{feld} fehlt"
    assert aufgabe["niveaus"] and set(aufgabe["niveaus"]) <= set(NIVEAUS)
    assert 3 <= len(aufgabe["redemittel"]) <= 5, "drei bis fuenf Redemittel"
    assert 2 <= len(aufgabe["abschluss_pruefung"]) <= 3
    assert aufgabe["rolle_wiederholung"] != aufgabe["rolle_coach"], \
        "die Wiederholung braucht eine leicht andere Rolle"
    for merkmal in aufgabe["abschluss_pruefung"]:
        assert merkmal["woerter"], merkmal["was"]
        for wort in merkmal["woerter"]:
            assert wort == wort.lower().strip(), "Schluesselwoerter klein"
    # Jede Aufgabe hat mindestens ein Geheimnis: sonst keine Informationsluecke.
    assert any(m["geheim"] for m in aufgabe["abschluss_pruefung"])


def test_jedes_niveau_hat_aufgaben():
    for niveau in NIVEAUS:
        assert sprechaufgaben.fuer_niveau(niveau), niveau


def test_die_liste_ist_nach_niveau_gefiltert():
    for niveau in NIVEAUS:
        for a in sprechaufgaben.fuer_niveau(niveau):
            assert niveau in a["niveaus"]
    a1 = {a["schluessel"] for a in sprechaufgaben.fuer_niveau("A1")}
    b2 = {a["schluessel"] for a in sprechaufgaben.fuer_niveau("B2")}
    assert "tierarzt" in a1 and "tierarzt" not in b2
    assert "handyregel" in b2 and "handyregel" not in a1
    assert sprechaufgaben.passt("geburtstag", "A2") is True
    assert sprechaufgaben.passt("geburtstag", "B2") is False
    assert sprechaufgaben.passt("gibtsnicht", "A1") is False


def test_leer_unbekannt_und_fremde_sprache_heissen_freies_gespraech():
    for wert in ("", None, "gibtsnicht"):
        assert sprechaufgaben.ist_frei(sprechaufgaben.aufgabe(wert))
    assert sprechaufgaben.ist_frei(sprechaufgaben.aufgabe("geburtstag", "fr-FR")), \
        "Redemittel und Schluesselwoerter sind englisch"


# --- Der Abschluss ---------------------------------------------------------

def test_das_ziel_ist_erreicht_wenn_das_kind_alles_gesagt_hat():
    assert sprechaufgaben.ziel_erreicht(
        GEBURTSTAG, ["When is the party?", "OK, Saturday at three at the pool."]
    ) is True


def test_gehoert_ist_nicht_gesagt():
    """Nur was das Kind sagt, zaehlt - Fragen allein erreichen das Ziel nicht."""
    assert sprechaufgaben.ziel_erreicht(
        GEBURTSTAG, ["When is the party?", "What time?", "Where is it?"]
    ) is False
    offen = sprechaufgaben.offene_merkmale(GEBURTSTAG, ["Saturday? Cool."])
    assert [m["was"] for m in offen] == ["Uhrzeit", "Ort"]


def test_ganze_woerter_und_ziffern():
    tierarzt = sprechaufgaben.aufgabe("tierarzt")
    alter = [m for m in tierarzt["abschluss_pruefung"] if m["was"] == "Alter"][0]
    assert sprechaufgaben.merkmal_erfuellt(alter, ["It is 2 years old."])
    assert sprechaufgaben.merkmal_erfuellt(alter, ["Two."])
    assert not sprechaufgaben.merkmal_erfuellt(alter, ["It is twelve."]), \
        "two steckt in twelve, zaehlt aber nicht"
    geschenk = sprechaufgaben.aufgabe("geschenk")
    grund = [m for m in geschenk["abschluss_pruefung"] if m["was"] == "Begründung"][0]
    assert sprechaufgaben.merkmal_erfuellt(grund, ["That’s why we buy a plant."]), \
        "der typografische Apostroph von Whisper"


def test_das_freie_gespraech_hat_kein_ziel():
    frei = sprechaufgaben.FREIES_GESPRAECH
    assert sprechaufgaben.ziel_erreicht(frei, ["Saturday at three at the pool"]) is False


# --- Der Uebergang, ohne Datenbank ----------------------------------------

def test_aufgabe_geht_nach_dem_ziel_in_den_rollentausch():
    neu, erreicht = sprechablauf.nach_beitrag(
        sprechablauf.AUFGABE, GEBURTSTAG, "10-14",
        ["When?", "Saturday at three, at the pool."],
    )
    assert (neu, erreicht) == (sprechablauf.WECHSEL, True)


def test_ohne_ziel_bleibt_die_phase():
    neu, erreicht = sprechablauf.nach_beitrag(
        sprechablauf.AUFGABE, GEBURTSTAG, "10-14", ["When is the party?"],
    )
    assert (neu, erreicht) == (sprechablauf.AUFGABE, None)


def test_nach_der_hoechstzahl_geht_es_trotzdem_weiter():
    """Volksschule kuerzer: sechs Beitraege, sonst zehn."""
    sechs = ["Hello?"] * 6
    assert sprechablauf.nach_beitrag(
        sprechablauf.AUFGABE, GEBURTSTAG, "6-10", sechs
    ) == (sprechablauf.WECHSEL, False)
    assert sprechablauf.nach_beitrag(
        sprechablauf.AUFGABE, GEBURTSTAG, "10-14", sechs
    ) == (sprechablauf.AUFGABE, None)


def test_rollentausch_dann_wiederholung_dann_rueckblick():
    assert sprechablauf.nach_beitrag(
        sprechablauf.WECHSEL, GEBURTSTAG, "10-14", ["In May."]
    )[0] == sprechablauf.WECHSEL
    assert sprechablauf.nach_beitrag(
        sprechablauf.WECHSEL, GEBURTSTAG, "10-14", ["In May.", "Pizza."]
    )[0] == sprechablauf.WIEDERHOLUNG
    assert sprechablauf.nach_beitrag(
        sprechablauf.WECHSEL, GEBURTSTAG, "6-10", ["In May."]
    )[0] == sprechablauf.WIEDERHOLUNG, "Volksschule: eine Antwort genuegt"
    assert sprechablauf.nach_beitrag(
        sprechablauf.WIEDERHOLUNG, GEBURTSTAG, "10-14",
        ["Saturday, three, swimming pool."],
    ) == (sprechablauf.RUECKBLICK, True)


def test_das_freie_gespraech_wechselt_nie_von_selbst():
    frei = sprechaufgaben.FREIES_GESPRAECH
    assert sprechablauf.startphase(frei) == sprechablauf.AUFGABE
    assert sprechablauf.startphase(GEBURTSTAG) == sprechablauf.PLANEN
    assert sprechablauf.nach_beitrag(
        sprechablauf.AUFGABE, frei, "6-10", ["x"] * 30
    ) == (sprechablauf.AUFGABE, None)


def test_jede_phase_hat_ihre_eigene_anweisung():
    offene = GEBURTSTAG["abschluss_pruefung"]
    aufgabe = sprechablauf.anweisung(sprechablauf.AUFGABE, GEBURTSTAG, offene, True)
    wechsel = sprechablauf.anweisung(sprechablauf.WECHSEL, GEBURTSTAG, [], True)
    wieder = sprechablauf.anweisung(sprechablauf.WIEDERHOLUNG, GEBURTSTAG, offene, True)

    assert GEBURTSTAG["geheimnis"] in aufgabe and "Verrate NICHTS" in aufgabe
    assert GEBURTSTAG["rolle_coach"] in aufgabe
    assert "Uhrzeit" in aufgabe, "der Server nennt die offenen Merkmale"
    assert "TAUSCHT" in wechsel and GEBURTSTAG["wechsel"] in wechsel
    assert GEBURTSTAG["rolle_wiederholung"] in wieder
    assert GEBURTSTAG["geheimnis"] in wieder, "dasselbe Geheimnis: dieselbe Aufgabe"
    assert sprechablauf.anweisung(
        sprechablauf.AUFGABE, sprechaufgaben.FREIES_GESPRAECH, [], True) == ""


def test_das_geheimnis_darf_nicht_ausgeplaudert_werden():
    offene = GEBURTSTAG["abschluss_pruefung"]
    assert sprechablauf.verraet_zu_viel(
        "Hi! My party is on Saturday. Do you want to come?", GEBURTSTAG, offene,
        erster_zug=True) is True
    assert sprechablauf.verraet_zu_viel(
        "Hi, I'm Tom. What do you want to know?", GEBURTSTAG, offene,
        erster_zug=True) is False
    assert sprechablauf.verraet_zu_viel(
        "On Saturday at three.", GEBURTSTAG, offene) is False, "zwei auf eine Frage"
    assert sprechablauf.verraet_zu_viel(
        "Saturday at three at the pool.", GEBURTSTAG, offene) is True


def test_in_der_aufgabe_darf_der_coach_ohne_frage_antworten():
    gut = sprechcoach.verstoesse("On Saturday.", "en-GB", "A1",
                                 beitrag="When is the party?", kind_fragt=True)
    assert gut == [], "eine Antwort auf eine Frage knuepft an"
    zwei = sprechcoach.verstoesse("Saturday. Why? Who asks?", "en-GB", "A1",
                                  beitrag="When is the party?", kind_fragt=True)
    assert "mehr als eine Frage" in zwei
    assert sprechcoach.schaerfung_fuer(zwei, "en-GB", "A1") == \
        sprechcoach.SCHAERFUNG_HOECHSTENS_EINE
    sonst = sprechcoach.verstoesse("On Saturday.", "en-GB", "A1",
                                   beitrag="When is the party?")
    assert "nicht genau eine Frage" in sonst, "ausserhalb der Aufgabe wie bisher"


# --- Messung (Regel 14) ----------------------------------------------------

def _zug(rolle, text, phase=sprechablauf.AUFGABE, sekunde=0, nv=False, korrektur=""):
    return {"rolle": rolle, "text": text, "phase": phase, "nicht_verstanden": nv,
            "zeit": timezone.now().replace(microsecond=0) + timedelta(seconds=sekunde),
            "korrektur": korrektur}


def test_die_messwerte_stimmen():
    zuege = [
        _zug("coach", "Hi, I'm Tom. What do you want to know?", sekunde=0),
        _zug("lernend", "When is the party?", sekunde=10),                  # 4, Frage
        _zug("coach", "On Saturday.", sekunde=12),
        _zug("lernend", "Ich weiss nicht.", sekunde=20),                    # gesperrt
        _zug("coach", "Sorry, I don't understand that.", sekunde=21, nv=True),
        _zug("lernend", "Saturday. And what time is it, please tell me?",   # 9, 2 Saetze
             sekunde=40),
        _zug("coach", "At three.", sekunde=41),
        _zug("lernend", "OK", phase=sprechablauf.WIEDERHOLUNG, sekunde=100),  # 1
        _zug("lernend", "Where is the party, on Saturday at three o'clock?",  # 10
             phase=sprechablauf.WIEDERHOLUNG, sekunde=130),
    ]
    m = sprechablauf.messung(zuege)

    assert m["beitraege"] == 4, "der gesperrte deutsche Beitrag zaehlt nicht"
    assert m["woerter"] == 4 + 9 + 1 + 10, "o'clock sind zwei Woerter"
    assert m["woerter_je_beitrag"] == pytest.approx(24 / 4)
    assert m["anteil_erweitert"] == pytest.approx(2 / 4)
    assert m["fragen"] == 3
    assert m["sperren"] == 1
    assert m["dauer_sekunden"] == 130
    assert m["erster"]["beitraege"] == 2
    assert m["erster"]["woerter_je_beitrag"] == pytest.approx(13 / 2)
    assert m["zweiter"]["beitraege"] == 2
    assert m["zweiter"]["woerter_je_beitrag"] == pytest.approx(11 / 2)


def test_erweitert_heisst_mehr_als_ein_satz_oder_acht_woerter():
    assert sprechablauf.ist_erweitert("I like it. It is fun.") is True
    assert sprechablauf.ist_erweitert("I went to the pool with my big brother") is True
    assert sprechablauf.ist_erweitert("I went to the pool") is False


def test_die_zahlenzeile_ist_ruhig_und_oesterreichisch():
    m = sprechablauf.messung([
        _zug("lernend", "When is the party?", sekunde=0),
        _zug("lernend", "Saturday at three.", phase=sprechablauf.WIEDERHOLUNG,
             sekunde=75),
    ])
    zeile = sprechablauf.zahlenzeile(m, True, False)
    assert "3,5 Wörter je Beitrag" in zeile
    assert "1:15 min" in zeile
    assert "Ziel erreicht" in zeile
    assert any("1. → 2. Durchgang: 4,0 → 3,0" in t for t in zeile)
    assert "beim 2. Mal Ziel nicht erreicht" in zeile
    assert sprechablauf.zahlenzeile(sprechablauf.messung([])) == []


# --- Der Rueckblick (Regel 6, zweiter Teil) --------------------------------

def _gespraech_mit_korrekturen():
    return [
        _zug("coach", "Hi! What do you want to know?"),
        _zug("lernend", "When is the party?"),
        _zug("coach", "On Saturday.", korrektur=""),
        _zug("lernend", "What time it is the party?"),
        _zug("coach", "At three. Anything else?", korrektur="What time is the party?"),
        _zug("lernend", "Where it is?"),
        _zug("coach", "At the pool.", korrektur="Where is it?"),
        _zug("lernend", "So the party is on Saturday at three at the pool."),
    ]


def test_der_rueckblick_hat_hoechstens_drei_punkte():
    punkte = sprechablauf.rueckblick(_gespraech_mit_korrekturen(), GEBURTSTAG, "10-14")
    assert 1 <= len(punkte) <= 3
    arten = [p["art"] for p in punkte]
    assert arten.count("gut") == 1 and arten.count("besser") == 2
    besser = [p for p in punkte if p["art"] == "besser"]
    assert besser[0]["englisch"] == "Where is it?", "die juengste zuerst"
    assert besser[0]["vorher"] == "Where it is?", "mit der Form des Kindes daneben"
    assert all(p["deutsch"] and p["englisch"] for p in punkte), \
        "deutsch erklaert, englisch gezeigt"


def test_in_der_volksschule_nur_gelungenes_und_ein_punkt():
    punkte = sprechablauf.rueckblick(_gespraech_mit_korrekturen(), GEBURTSTAG, "6-10")
    assert len(punkte) <= 3
    besser = [p for p in punkte if p["art"] == "besser"]
    assert len(besser) == 1
    assert besser[0]["vorher"] == "", "ohne den Satz des Kindes daneben"
    assert punkte[0]["art"] == "gut", "zuerst das Gelungene"


def test_ohne_korrektur_kommt_eine_wendung_aus_den_redemitteln():
    punkte = sprechablauf.rueckblick([
        _zug("lernend", "When is the party?"),
        _zug("coach", "On Saturday."),
    ], GEBURTSTAG, "10-14")
    besser = [p for p in punkte if p["art"] == "besser"]
    assert besser and besser[0]["englisch"] in GEBURTSTAG["redemittel"]
    assert besser[0]["englisch"] != "When is the party?", "die kam ja schon"


def test_ein_gesperrter_beitrag_kommt_nicht_in_den_rueckblick():
    punkte = sprechablauf.rueckblick([
        _zug("lernend", "Ich weiss nicht, wann die Party ist, sag es mir."),
        _zug("coach", "Sorry, I don't understand that.", nv=True),
    ], GEBURTSTAG, "10-14")
    assert all("Party ist" not in p["englisch"] for p in punkte)


# --- Durch die Ansichten -------------------------------------------------

@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lp", password="x")


def _stunde(lehrperson, aufgabe="geburtstag", niveau="A1", alter="10-14"):
    return LearningSession.objects.create(
        title="Englisch 2a", teacher=lehrperson, mode=LearningSession.BETRIEB_SPRACHE,
        subject="englisch", target_language="en-GB", language_level=niveau,
        speaking_task=aufgabe, age_group=alter,
    )


def _beitreten(client, sitzung, token="t-otter"):
    teilnahme = Participation.objects.create(
        learning_session=sitzung, animal="fuchs", token=token,
    )
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.fixture
def modell(monkeypatch):
    """Merkt sich jeden Systemprompt und antwortet unverfaenglich."""
    gesehen = []

    def attrappe(system, frage, max_tokens=500):
        gesehen.append(system)
        return (json.dumps({"antwort": "Hi, I'm Tom. What do you want to know?",
                            "uebersetzung": "x", "korrektur": ""}),
                {"modell": "p", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1})
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)
    return gesehen


def _sag(client, text):
    return client.post(reverse("tutoring:sprechcoach_zug"),
                       {"text": text, "erkannt": "en"},
                       HTTP_X_ANTWORT="json", secure=True).json()


def _planen_vorbei(lauf, sekunden=120):
    SprachLauf.objects.filter(pk=lauf.pk).update(
        phase_seit=timezone.now() - timedelta(seconds=sekunden))


@pytest.mark.django_db
def test_mit_aufgabe_wird_zuerst_geplant_ohne_modell(client, lehrperson, modell):
    _beitreten(client, _stunde(lehrperson))

    seite = client.get(reverse("tutoring:sprechcoach"), secure=True)

    inhalt = seite.content.decode()
    assert SprachLauf.objects.get().phase == sprechablauf.PLANEN
    assert modell == [], "beim Planen spricht der Coach noch nicht"
    assert "Think first" in inhalt and GEBURTSTAG["ziel"] in inhalt
    for wendung in GEBURTSTAG["redemittel"]:
        assert wendung in inhalt
    assert "sprechcoach.js" not in inhalt, "kein Mikrofon beim Planen"
    assert _sag(client, "When is the party?")["ok"] is False, \
        "ein Beitrag waehrend des Planens wird nicht angenommen"


@pytest.mark.django_db
def test_zu_frueh_bereit_bleibt_planen(client, lehrperson, modell):
    _beitreten(client, _stunde(lehrperson))
    client.get(reverse("tutoring:sprechcoach"), secure=True)

    antwort = client.post(reverse("tutoring:sprechcoach_weiter"), secure=True)

    assert SprachLauf.objects.get().phase == sprechablauf.PLANEN
    assert "Noch ein paar Sekunden" in antwort.content.decode()


@pytest.mark.django_db
def test_der_ganze_ablauf_wird_im_server_gesteuert(client, lehrperson, modell):
    sitzung = _stunde(lehrperson)
    _beitreten(client, sitzung)
    client.get(reverse("tutoring:sprechcoach"), secure=True)
    lauf = SprachLauf.objects.get()
    _planen_vorbei(lauf)

    client.post(reverse("tutoring:sprechcoach_weiter"), secure=True)
    seite = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()
    lauf.refresh_from_db()
    assert lauf.phase == sprechablauf.AUFGABE
    assert GEBURTSTAG["geheimnis"] in modell[0], "der erste Zug kennt das Geheimnis"
    assert "Verrate NICHTS" in modell[0]
    assert "Your goal" in seite and GEBURTSTAG["ziel"] in seite

    # Fragen allein erreichen das Ziel nicht.
    daten = _sag(client, "When is the party?")
    assert daten["phase"] == sprechablauf.AUFGABE and not daten["phase_gewechselt"]

    # Das Kind sagt das Ergebnis: Rollentausch.
    daten = _sag(client, "So the party is on Saturday at three at the pool.")
    lauf.refresh_from_db()
    assert daten["phase"] == sprechablauf.WECHSEL and daten["phase_gewechselt"]
    assert daten["schritt"] == 2, "der Rollentausch gehoert zum Gespraech"
    assert lauf.goal_first is True
    assert "TAUSCHT" in modell[-1]

    _sag(client, "My birthday is in May.")
    daten = _sag(client, "I like pizza and games.")
    lauf.refresh_from_db()
    assert daten["phase"] == sprechablauf.WIEDERHOLUNG and daten["schritt"] == 3
    letzter = modell[-1]
    assert GEBURTSTAG["rolle_wiederholung"] in letzter, "leicht andere Rolle"
    assert GEBURTSTAG["geheimnis"] in letzter, "dieselbe Aufgabe"

    # Das Gedaechtnis der Wiederholung kennt den ersten Durchgang nicht.
    gedaechtnis = sprechcoach_views._verlauf_text(
        lauf, sprechablauf.gedaechtnis_phasen(sprechablauf.WIEDERHOLUNG))
    assert "So the party is on Saturday" not in gedaechtnis

    aufrufe = len(modell)
    daten = _sag(client, "Saturday, three o'clock, swimming pool. Thanks!")
    lauf.refresh_from_db()
    assert lauf.phase == sprechablauf.RUECKBLICK
    assert lauf.goal_second is True
    assert daten["fertig"] is True and daten["neu_laden"] is True
    assert daten["coach"] == sprechablauf.abschied("en-GB")
    assert len(modell) == aufrufe, "der Abschied ist fest und fragt das Modell nicht"
    assert 1 <= len(lauf.review) <= 3

    seite = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()
    assert "Rückblick" in seite and "keine Note" in seite
    assert "Was war beim zweiten Mal leichter?" in seite
    assert _sag(client, "Hello?")["ok"] is False, "nach dem Rueckblick kein Beitrag"


@pytest.mark.django_db
def test_ein_verraeter_wird_ein_zweites_mal_geholt(client, lehrperson, monkeypatch):
    antworten = iter([
        '{"antwort": "Hi! My party is on Saturday at three. Can you come?", "uebersetzung": "x", "korrektur": ""}',
        '{"antwort": "Hi, I am Tom. What do you want to know?", "uebersetzung": "x", "korrektur": ""}',
    ])
    gesehen = []

    def attrappe(system, frage, max_tokens=500):
        gesehen.append(system)
        return next(antworten), {"modell": "p", "tokens_ein": 1, "tokens_aus": 1, "dauer_ms": 1}
    monkeypatch.setattr(sprechcoach_views, "antwort_holen_sync", attrappe)

    sitzung = _stunde(lehrperson)
    teilnahme = _beitreten(client, sitzung)
    SprachLauf.objects.create(participation=teilnahme, phase=sprechablauf.AUFGABE)

    client.get(reverse("tutoring:sprechcoach"), secure=True)

    assert len(gesehen) == 2
    assert sprechablauf.SCHAERFUNG_VERRAET.strip() in gesehen[1]
    assert SprachZug.objects.get().text.startswith("Hi, I am Tom")


@pytest.mark.django_db
def test_aufhoeren_fuehrt_in_den_rueckblick(client, lehrperson, modell):
    sitzung = _stunde(lehrperson)
    teilnahme = _beitreten(client, sitzung)
    SprachLauf.objects.create(participation=teilnahme, phase=sprechablauf.AUFGABE)
    client.get(reverse("tutoring:sprechcoach"), secure=True)
    _sag(client, "When is the party?")

    client.post(reverse("tutoring:sprechcoach_weiter"), secure=True)

    lauf = SprachLauf.objects.get()
    assert lauf.phase == sprechablauf.RUECKBLICK
    assert lauf.goal_first is False


@pytest.mark.django_db
def test_das_freie_gespraech_faengt_gleich_an(client, lehrperson, modell):
    _beitreten(client, _stunde(lehrperson, aufgabe="frei"))

    seite = client.get(reverse("tutoring:sprechcoach"), secure=True).content.decode()

    assert SprachLauf.objects.get().phase == sprechablauf.AUFGABE
    assert len(modell) == 1 and "GEHEIMNIS" not in modell[0]
    assert "Your goal" not in seite
    assert "Gespräch beenden" in seite


# --- Die Lehrperson -------------------------------------------------------

@pytest.mark.django_db
def test_die_aufgabe_wird_beim_anlegen_gewaehlt(client, lehrperson):
    client.force_login(lehrperson)

    formular = client.get(reverse("tutoring:lehrperson_uebersicht"),
                          {"fach": "englisch"}, secure=True).content.decode()
    for a in sprechaufgaben.AUFGABEN:
        assert f'value="{a["schluessel"]}"' in formular
    assert 'data-niveaus="A1 A2"' in formular, "das Skript filtert danach"
    assert "Aufgabe und kein Plaudern" in formular, "die Seite sagt, warum"

    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "englisch", "title": "Englisch 3c", "language_level": "A2",
                 "speaking_task": "weg"}, secure=True)
    assert LearningSession.objects.get(title="Englisch 3c").speaking_task == "weg"


@pytest.mark.django_db
def test_eine_unpassende_aufgabe_wird_zurueckgegeben(client, lehrperson):
    client.force_login(lehrperson)

    antwort = client.post(reverse("tutoring:lehrperson_uebersicht"),
                          {"fach": "englisch", "title": "Englisch 1a",
                           "language_level": "A1", "speaking_task": "handyregel"},
                          secure=True)

    assert antwort.status_code == 200
    assert "passt nicht zum Niveau A1" in antwort.content.decode()
    assert not LearningSession.objects.filter(title="Englisch 1a").exists()


@pytest.mark.django_db
def test_in_mathematik_gibt_es_keine_gespraechsaufgabe(client, lehrperson):
    client.force_login(lehrperson)
    client.post(reverse("tutoring:lehrperson_uebersicht"),
                {"fach": "mathematik", "title": "Mathe 2b", "schulstufe": "vs",
                 "speaking_task": "weg"},
                secure=True)
    assert LearningSession.objects.get(title="Mathe 2b").speaking_task == ""


def _gespraech_ablegen(teilnahme):
    lauf = SprachLauf.objects.create(participation=teilnahme,
                                     phase=sprechablauf.WIEDERHOLUNG, goal_first=True)
    SprachZug.objects.create(run=lauf, role=SprachZug.COACH, text="Hi! What do you want to know?")
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND, text="When is the party?")
    SprachZug.objects.create(run=lauf, role=SprachZug.LERNEND,
                             text="Saturday at three at the pool.",
                             phase=sprechablauf.WIEDERHOLUNG)
    return lauf


@pytest.mark.django_db
def test_die_lehrperson_sieht_die_zahlen_je_kind(client, lehrperson):
    sitzung = _stunde(lehrperson)
    _gespraech_ablegen(_beitreten(client, sitzung))
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]),
                       secure=True).content.decode()

    assert "Wörter je Beitrag" in seite
    assert "1. → 2. Durchgang: 4,0 → 6,0 Wörter je Beitrag" in seite
    assert "Ziel erreicht" in seite
    assert "Aufgaben gestellt" not in seite, "keine Mathematikzahlen im Englisch"


@pytest.mark.django_db
def test_in_der_volksschule_nur_die_klassensumme(client, lehrperson):
    sitzung = _stunde(lehrperson, alter="6-10")
    _gespraech_ablegen(_beitreten(client, sitzung))
    client.force_login(lehrperson)

    seite = client.get(reverse("tutoring:lehrperson_klassenliste", args=[sitzung.code]),
                       secure=True).content.decode()

    # Seit 22.10.2026 ist die Klasse eine Kachel je Kind; die Zahlen je Kind
    # stuenden in der Notizzeile der Kachel, und die bleibt hier leer.
    assert 'class="kachel-diagnose"></p>' in seite, "keine Zahlen je Kind"
    assert "Wörter je Beitrag" not in seite.split('class="klassenbild"')[1], "keine Zahlen je Kind"
    assert "Beiträge" in seite, "aber die Summe der Klasse"
    assert "1 von 1" in seite


@pytest.mark.django_db
def test_die_erklaerung_nennt_aufgaben_ablauf_und_messung(client):
    seite = client.get(reverse("sprechcoach_erklaerung"), secure=True).content.decode()
    for a in sprechaufgaben.AUFGABEN:
        assert a["titel"] in seite
    assert 'id="aufgaben"' in seite and 'id="messung"' in seite
    assert "d = 0,97" in seite and "Sun &amp; Révész" in seite


# --- Keine Emojis, nirgends ------------------------------------------------

GEAENDERT = [
    "tutoring/templates/tutoring/sprechcoach.html",
    "tutoring/templates/tutoring/_sprech_phasen.html",
    "tutoring/templates/tutoring/_sprech_planen.html",
    "tutoring/templates/tutoring/_sprech_rueckblick.html",
    "tutoring/templates/tutoring/_klassenliste.html",
    "tutoring/templates/tutoring/lehrperson_sitzung.html",
    "tutoring/templates/tutoring/lehrperson_uebersicht.html",
    "core/templates/core/sprechcoach_erklaerung.html",
    "static/js/sprechcoach.js",
    "static/js/aufgabenwahl.js",
    "static/css/sprechcoach.css",
    "tutoring/sprechaufgaben.py",
    "tutoring/sprechablauf.py",
]


def _emojis(text):
    return [z for z in text if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF]


@pytest.mark.parametrize("pfad", GEAENDERT)
def test_keine_emojis_in_den_dateien(pfad):
    text = (pathlib.Path(settings.BASE_DIR) / pfad).read_text(encoding="utf-8")
    assert _emojis(text) == []


def test_keine_emojis_in_den_aufgabentexten():
    for a in sprechaufgaben.AUFGABEN:
        assert _emojis(json.dumps(a, ensure_ascii=False)) == [], a["schluessel"]


@pytest.mark.django_db
def test_keine_emojis_auf_der_seite_des_kindes(client, lehrperson, modell):
    """Gerendert, in allen drei Ansichten: Planen, Gespraech, Rueckblick."""
    _beitreten(client, _stunde(lehrperson, alter="6-10"))
    url = reverse("tutoring:sprechcoach")
    planen = client.get(url, secure=True).content.decode()
    lauf = SprachLauf.objects.get()
    lauf.phase_setzen(sprechablauf.AUFGABE)
    gespraech = client.get(url, secure=True).content.decode()
    lauf.phase_setzen(sprechablauf.RUECKBLICK, review=[
        {"art": "gut", "deutsch": "Das hast du gut gesagt:", "englisch": "When is it?"},
        {"art": "besser", "deutsch": "So sagt man es:", "englisch": "Where is it?",
         "vorher": ""},
    ])
    rueckblick = client.get(url, secure=True).content.decode()

    for seite in (planen, gespraech, rueckblick):
        assert _emojis(seite) == []
    assert "rueckblick-zeichen" in rueckblick, "Symbole als Inline-SVG"
