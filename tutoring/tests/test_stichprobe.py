"""Deterministische Pruefungen aus Thomas' Stichprobe (31.10.2026).

36 Tutorzuege aus D3 und dem Claude-Vergleich, von Thomas bewertet; die
Siegen-Sitzung hat daraus Vorschlaege gebuendelt: erfundene Zitate ("Du hast
gesagt, dass 14 Autos da sind", bevor das Kind etwas schrieb), Behauptungen
ueber die Lehrperson, nachgerechnete Rechnungen des Kindes (60 statt 70 als
richtig bestaetigt), das Rechenzeichen in der Bestaetigung ("72 · 9" nach
"72 minus 9") und Schleifen (dreimal dieselbe Frage).
"""
import asyncio

import pytest

from tutoring import ausgabepruefung as ap
from tutoring import levels, pruefung, views

PARKPLATZ = "Auf dem Parkplatz stehen 14 Autos. 6 fahren weg. Wie viele Autos stehen noch da?"


# --- Erfundene Zitate ---------------------------------------------------------

def test_vor_dem_ersten_beitrag_ist_jedes_zitat_erfunden():
    assert "erfundenes Zitat" in ap.verstoesse(
        "Du hast gesagt, dass 14 Autos da sind. Was passiert mit den 6?", 1, 5, [PARKPLATZ])


def test_ein_zitat_gilt_wenn_das_kind_es_geschrieben_hat():
    eigenes = [PARKPLATZ, "da stehen 14 autos und 6 fahren weg"]
    assert ap.verstoesse("Du hast gesagt, dass 14 Autos da sind. Was passiert mit den 6?",
                         1, 5, eigenes) == []
    assert ap.verstoesse("Du hast richtig erkannt, dass 6 wegfahren.", 1, 5, eigenes) == []


def test_ein_zitat_das_nirgends_steht_faellt_auf():
    eigenes = [PARKPLATZ, "ich weiß nicht"]
    assert "erfundenes Zitat" in ap.verstoesse(
        "Du hast richtig erkannt, dass es ein rechtwinkliges Dreieck ist.", 2, 5, eigenes)
    assert "erfundenes Zitat" in ap.verstoesse(
        "Du hast schon gesagt, dass Anna drei Stücke abgeschnitten hat.", 2, 5, eigenes)


def test_die_rechenart_des_kindes_ist_als_zitat_gedeckt():
    assert ap.verstoesse("Du hast addiert.", 2, 5, [PARKPLATZ, "14 + 6 = 20"]) == []
    assert ap.verstoesse("Du hast 14 + 6 gerechnet.", 2, 5, [PARKPLATZ, "14 + 6 = 20"]) == []


def test_ein_satz_ueber_das_befinden_ist_kein_erfundenes_zitat():
    """Lauf F3, vs10: "ich geb auf" hat kein Inhaltswort; der Tutor darf darauf eingehen."""
    assert ap.verstoesse("Du hast gesagt, dass du aufgibst, aber wir bleiben dran.",
                         1, 5, [PARKPLATZ, "ich geb auf"]) == []
    assert "erfundenes Zitat" in ap.verstoesse(
        "Du hast gesagt, dass 14 Autos da sind.", 1, 5, [PARKPLATZ, "ich geb auf"])


def test_du_hast_ohne_zitatverb_ist_kein_zitat():
    assert ap.verstoesse("Du hast 14 Autos, und 6 fahren weg.", 1, 5, [PARKPLATZ]) == []


def test_die_kuerzung_nimmt_das_erfundene_zitat_heraus():
    text = "Du hast gesagt, dass 14 Autos da sind. Schau auf die Autos, die wegfahren. Was bleibt?"
    assert ap.saubere_saetze(text, 1, 5, [PARKPLATZ]) == (
        "Schau auf die Autos, die wegfahren. Was bleibt?")


# --- Behauptungen ueber die Lehrperson -----------------------------------------

def test_eine_behauptung_ueber_die_lehrperson_faellt_auf():
    assert "Behauptung über die Lehrperson" in ap.verstoesse(
        "Die Lehrerin hat gesagt, du darfst die Lösung nur bekommen, wenn du fragst.",
        1, 5, [PARKPLATZ])
    assert "Behauptung über die Lehrperson" in ap.verstoesse(
        "Deine Lehrerin hat gesagt, du musst erst dreimal fragen.", 2, 5, [PARKPLATZ])


def test_die_einstellung_der_lehrperson_darf_genannt_werden():
    assert ap.verstoesse("Deine Lehrperson hat für diese Stunde nur Tipps eingestellt.",
                         1, 5, [PARKPLATZ]) == []
    assert ap.verstoesse("Die Einstellung der Lehrerin erlaubt hier keine Lösung.",
                         1, 5, [PARKPLATZ]) == []
    # Lauf F3: Umschreibungen der Einstellung sind erlaubt, eine Lehrerin in
    # der Angabe ist eine Figur der Aufgabe.
    assert ap.verstoesse("Ich kann keine Lösung nennen, da die Lehrperson dies untersagt hat.",
                         1, 5, [PARKPLATZ]) == []
    assert ap.verstoesse("Die Lehrerin hat gesagt, dass ich dir keine Lösungen sage, sondern nur Tipps gebe.",
                         1, 5, [PARKPLATZ]) == []
    assert ap.verstoesse("Jetzt weißt du, dass die Lehrerin 200 Euro hat.", 1, 5,
                         ["Die Lehrerin hat 200 Euro und kauft 6 Bälle um 24 Euro."]) == []


def test_die_schaerfungen_passen_zum_verstoss():
    assert ap.schaerfung_fuer(["erfundenes Zitat"]) is ap.SCHAERFUNG_ZITAT
    assert ap.schaerfung_fuer(["Behauptung über die Lehrperson"]) is ap.SCHAERFUNG_LEHRPERSON
    assert ap.schaerfung_fuer(["anderes Rechenzeichen als beim Kind"]) is ap.SCHAERFUNG_RECHENZEICHEN
    assert ap.schaerfung_fuer(["genannter Rechenweg", "erfundenes Zitat"]) is ap.SCHAERFUNG_METHODE


# --- Das Rechenzeichen in der Bestaetigung ------------------------------------

def test_in_der_bestaetigung_passt_das_rechenzeichen_zur_rechnung_des_kindes():
    eigenes = ["Im Bus sind 72 Kinder, 9 steigen aus.", "72 - 9 = 63"]
    text = "Richtig, 72 - 9 = 63. Wie viel wäre 72 · 9?"
    assert "anderes Rechenzeichen als beim Kind" in ap.verstoesse(text, 4, 5, eigenes,
                                                                   bestaetigt=True)
    assert ap.verstoesse("Richtig, 72 minus 9. Warum passt minus hier?", 4, 5, eigenes,
                         bestaetigt=True) == []


def test_in_einer_hilfe_darf_stufe_vier_die_andere_rechenart_nennen():
    eigenes = ["Im Bus sind 72 Kinder, 9 steigen aus.", "72 + 9 = 81"]
    assert ap.verstoesse("Was ist 72 - 9?", 4, 5, eigenes) == []


# --- Die Rechnung des Kindes nachrechnen ---------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("7 + 5 = 11", [("7 + 5", "11", "12")]),
    ("7 + 5 = 12", []),
    ("Also 7 + 5 = 11.", [("7 + 5", "11", "12")]),
    ("60 : 7 = 8,57", []),
    ("60 : 7 = 8", []),
    ("60 : 7 = 9,5", [("60 : 7", "9.5", "etwa 8,57")]),
    ("1/2 + 1/3 = 5/6", []),
    ("1/2 + 1/3 = 2/5", [("1/2 + 1/3", "2/5", "etwa 0,83")]),
    ("2 + 3 · 4 = 14", []),
    ("2 + 3 · 4 = 20", [("2 + 3 · 4", "20", "14")]),
    ("x + 5 = 12", []),
    ("7 + 5 = 12 + 3 = 15", []),
    ("5 + 8 + 12 + 15 + 20 + 7 + 3 = 60", [("5 + 8 + 12 + 15 + 20 + 7 + 3", "60", "70")]),
    ("5 + 8 + 12 + 15 + 20 = 60", []),
    ("3 mal 5 = 15 und 15 plus 7 = 23", [("15 plus 7", "23", "22")]),
    ("18 : 24 = 0,75", []),
    # Lauf F3, ma15: "2^3 + 2 = 10" wurde als "3 + 2 ist nicht 10" gemeldet.
    ("Stammfunktion ist x^3 + x. Dann setze ich 2 ein: 2^3 + 2 = 10", []),
    ("2² + 1 = 5", []),
    ("3x + 7 = 22", []),
    ("f(2) = 8 + 2 = 10", []),
])
def test_falsche_rechnungen(text, erwartet):
    assert [tuple(f) for f in ap.falsche_rechnungen(text)] == erwartet


def _modell(monkeypatch, inhalt):
    class Antwort:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": inhalt}}]}

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **k): return Antwort()

    monkeypatch.setattr(pruefung.httpx, "Client", Client)


def test_eine_falsche_rechnung_als_schluss_ist_falsch_was_immer_das_modell_sagt(monkeypatch):
    """Zug 29 der Stichprobe: Summe 60 statt 70 als richtig bestaetigt."""
    _modell(monkeypatch, '{"rechnung": "70 : 7 = 10", "ergebnis": "richtig", "stufe": 5, "ampel": "gruen", "lage": "fertig"}')
    befund = pruefung.diagnose(2, "Mittelwert von 5, 8, 12, 15, 20, 7 und 3?",
                               "5 + 8 + 12 + 15 + 20 + 7 + 3 = 60")
    assert befund.ergebnis == pruefung.FALSCH and befund.fertig is False
    assert befund.fehler == "5 + 8 + 12 + 15 + 20 + 7 + 3 ist nicht 60, sondern 70"
    assert befund.lage == levels.LAGE_RECHENFEHLER
    assert befund.stufe == levels.RUECKMELDUNG
    assert "nachgerechnet" in befund.grund


def test_eine_korrigierte_rechnung_bleibt_richtig(monkeypatch):
    _modell(monkeypatch, '{"rechnung": "7 + 5 = 12", "ergebnis": "richtig", "stufe": 5, "ampel": "gruen", "lage": "fertig"}')
    befund = pruefung.diagnose(2, "Lena hat 7 Murmeln und bekommt 5 dazu.", "7 + 5 = 11, nein 12")
    assert befund.ergebnis == pruefung.RICHTIG


def test_das_modell_darf_den_fehler_selbst_benennen(monkeypatch):
    _modell(monkeypatch, '{"rechnung": "7 + 5 = 12", "ergebnis": "falsch", "fehler": "verzählt", "stufe": 2, "ampel": "gruen", "lage": "rechenfehler"}')
    befund = pruefung.diagnose(1, "Lena hat 7 Murmeln und bekommt 5 dazu.", "7 + 5 = 11")
    assert befund.ergebnis == pruefung.FALSCH and befund.fehler == "verzählt"


# --- Schleifen --------------------------------------------------------------

def test_dieselbe_frage_wird_erkannt():
    assert ap.wiederholt_frage("Schau hin. Was soll man hier herausfinden?",
                               ["Was soll man hier herausfinden?"])
    assert ap.wiederholt_frage("Was ist der gemeinsame Nenner von 2 und 3?",
                               ["Lies nach. Was ist der gemeinsame Nenner von 2 und 3?"])
    assert not ap.wiederholt_frage("Was rechnest du jetzt?", ["Was soll man hier herausfinden?"])
    assert not ap.wiederholt_frage("Probier es.", ["Was rechnest du jetzt?"])


class _Modell:
    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.anfragen = []

    async def __call__(self, system, frage, messung, *a, **k):
        self.anfragen.append((system, frage))
        return self.antworten.pop(0) if len(self.antworten) > 1 else self.antworten[0]


def test_dieselbe_frage_bekommt_einen_zweiten_anlauf(monkeypatch):
    modell = _Modell("Lies die Angabe. Was soll man hier herausfinden?",
                     "Es geht um Autos, die wegfahren. Wie viele waren am Anfang da?")
    monkeypatch.setattr(views, "_am_stueck", modell)
    text = asyncio.run(views._geprueft_erzeugen(
        "SYSTEM", "ANFRAGE", {}, 1, levels.LOESUNG, eigenes=[PARKPLATZ],
        schlussfrage="Was soll man hier herausfinden?",
        vermeiden=["Was soll man hier herausfinden?"],
    ))
    assert text == "Es geht um Autos, die wegfahren. Wie viele waren am Anfang da?"
    assert len(modell.anfragen) == 2
    assert modell.anfragen[1][0].endswith(ap.SCHAERFUNG_SCHLEIFE)


def test_bleibt_es_dieselbe_frage_bleibt_sie(monkeypatch):
    modell = _Modell("Lies die Angabe. Was soll man hier herausfinden?")
    monkeypatch.setattr(views, "_am_stueck", modell)
    text = asyncio.run(views._geprueft_erzeugen(
        "SYSTEM", "ANFRAGE", {}, 1, levels.LOESUNG, eigenes=[PARKPLATZ],
        schlussfrage="Was soll man hier herausfinden?",
        vermeiden=["Was soll man hier herausfinden?"],
    ))
    assert text == "Lies die Angabe. Was soll man hier herausfinden?"
    assert len(modell.anfragen) == 2, "ein zweiter Anlauf, kein dritter"


def test_erfundene_vorgeschichte_in_der_eroeffnung():
    """Lauf G: sechs Eroeffnungen erfanden, was das Kind getan hat ("du hast
    notiert", "du hast berechnet"); das Fenster von 40 Zeichen war zu kurz,
    "abgeschrieben" fehlte als Verb. Ohne Beitrag ist jedes Zitat erfunden."""
    aufgabe = "Lea hat bei einem Test 18 von 24 Punkten erreicht. Wie viel Prozent sind das?"
    assert ap.zitat_erfunden(
        "Du hast die Punkte von Lea und die Gesamtpunktzahl notiert.", [aufgabe])
    assert ap.zitat_erfunden(
        "Du hast die Werte für das arithmetische Mittel und den Median berechnet.", [aufgabe])
    assert ap.zitat_erfunden("Du hast die Aufgabe gut abgeschrieben.", [aufgabe])
    assert not ap.zitat_erfunden("Du hast die fünf Noten von Max vor dir.", [aufgabe])
    assert not ap.zitat_erfunden(
        "Du hast 18 und 24 richtig notiert.", [aufgabe, "ich nehme 18 und 24"])
    # Eine Frage ist kein Zitat (Lauf G2: die Eroeffnung war 16-mal gestrichen).
    assert not ap.zitat_erfunden("Was hast du dir dazu schon überlegt?", [aufgabe])
    assert not ap.zitat_erfunden("Hast du dir schon überlegt, wo du anfängst?", [aufgabe])
    assert not ap.verstoesse("Es geht um Lea und ihre Punkte. Was hast du dir schon überlegt?",
                             0, 5, [aufgabe])
