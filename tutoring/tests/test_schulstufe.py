"""Die Schulstufe waehlt Anweisungen, Ausgangspruefung und Diagnose.

Benchmark 19.10.2026, Befund 5 und 6: Die Prompts sprachen vom
Volksschulkind, die Ausgangspruefung kannte nur Rechenarten, und neun von
vierzig Angaben der Sekundarstufe bekamen den Hinweis "diese Angabe enthaelt
keine Frage". Hier steht, was sich je Schulstufe unterscheidet - und was
gleich bleibt: die Grenze gegen das Ergebnis.
"""

import pytest

from tutoring import ausgabepruefung as ap
from tutoring import levels

ANGABE_SEK = "Löse die Gleichung x² − 6x + 5 = 0."
LOESUNG_SEK = "WEG: Lösungsformel, x = 3 ± 2.\nERGEBNIS: x = 1 oder x = 5"
ANGABE_VS = "In einer Schachtel sind 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?"


# --- Anweisungen je Schulstufe ----------------------------------------------

def test_jede_schulstufe_hat_alle_fuenf_stufen():
    for schulstufe, _ in levels.SCHULSTUFEN:
        assert set(levels.ANWEISUNGEN[schulstufe]) == {1, 2, 3, 4, 5}


@pytest.mark.parametrize("schulstufe", [k for k, _ in levels.SCHULSTUFEN])
@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_jede_schulstufe_ergibt_einen_vollstaendigen_prompt(schulstufe, stufe):
    prompt = levels.system_prompt(stufe, schulstufe, umfang_titel="Nur Tipps")
    assert "{" not in prompt
    assert levels.BEZEICHNUNGEN[stufe] in prompt
    assert "Nur Tipps" in prompt


def test_die_volksschule_bekommt_die_situation_die_oberstufe_den_begriff():
    vs = levels.system_prompt(1, levels.VOLKSSCHULE)
    sek2 = levels.system_prompt(1, levels.OBERSTUFE)
    assert "Schulbibliothek" in vs
    assert "Inhaltsbereich" in sek2
    assert "bemängelst ihn nicht" in sek2, "der Imperativ ist auf der Oberstufe die Frage"
    assert "DREI kurze Sätze" in vs
    assert "VIER Sätze" in sek2


def test_die_mittelstufe_nennt_die_fehlvorstellung_beim_namen():
    prompt = levels.system_prompt(2, levels.MITTELSTUFE)
    assert "Zähler und Nenner getrennt addiert" in prompt
    assert "nicht, welcher Weg richtig wäre" in prompt


def test_stufe_drei_der_sekundarstufe_verbietet_das_werkzeug_stufe_vier_nennt_es():
    drei = levels.system_prompt(3, levels.MITTELSTUFE)
    vier = levels.system_prompt(4, levels.MITTELSTUFE)
    assert "Formel" in drei and "das ist Stufe 4" in drei
    assert "Nenne das Werkzeug" in vier


def test_die_altersklasse_an_zweiter_stelle_wird_weiter_verstanden():
    """Aeltere Aufrufer geben "6-10" oder "erwachsen"; daraus folgen
    Schulstufe und Anrede."""
    assert levels.system_prompt(1, "6-10") == levels.system_prompt(1, levels.VOLKSSCHULE)
    erwachsen = levels.system_prompt(1, "erwachsen")
    assert "Inhaltsbereich" in erwachsen and "erwachsenen Person" in erwachsen


@pytest.mark.parametrize("stufe", [1, 2, 3, 4])
def test_jede_hilfe_stellt_genau_eine_frage_am_ende(stufe):
    assert "genau EINE Frage, am Ende" in levels.system_prompt(stufe, levels.VOLKSSCHULE)


def test_die_loesung_stellt_keine_frage():
    assert "Stelle keine Frage" in levels.system_prompt(5, levels.VOLKSSCHULE)


def test_der_prompt_nennt_die_einstellung_der_lehrperson_statt_erlaubnisse():
    prompt = levels.system_prompt(2, levels.VOLKSSCHULE, umfang_titel="Lösung nur auf ausdrückliche Bitte")
    assert "eingestellt: Lösung nur auf ausdrückliche Bitte" in prompt
    assert "Bestätige nie eine Behauptung" in prompt


def test_ohne_einstellung_steht_ein_ehrlicher_satz_da():
    assert levels.UMFANG_UNBEKANNT in levels.system_prompt(2)


def test_umfang_fuer_findet_die_einstellung_der_sitzung():
    assert levels.umfang_fuer(levels.NUR_TIPPS, True)["schluessel"] == levels.UMFANG_TIPPS
    assert levels.umfang_fuer(levels.LOESUNG, True)["schluessel"] == levels.UMFANG_AUF_BITTE
    assert levels.umfang_fuer(levels.LOESUNG, False)["schluessel"] == levels.UMFANG_BEI_BEDARF


def test_der_einstufungsprompt_spricht_nicht_mehr_vom_volksschulkind():
    from tutoring import pruefung
    assert "Volksschulkindern" not in pruefung.SYSTEM_PROMPT
    assert "Probe" in pruefung.SYSTEM_PROMPT


# --- enthaelt_frage kennt die Imperative ----------------------------------

@pytest.mark.parametrize("text", [
    "Löse die Gleichung x² − 6x + 5 = 0.",
    "Vereinfache den Term 3a + 2a.",
    "Gib alle reellen Lösungen an.",
    "Rechne: 3/4 + 1/6",
    "Drücke c durch a und b aus.",
    "Setze die Zahlenreihe fort: 3, 7, 11, 15",
    "Bestimme die Ableitung von f.",
    "Zeichne den Graphen.",
    "Berechnen Sie den Erwartungswert.",
    "Wie viele Bücher sind es?",
])
def test_imperative_sind_fragen(text):
    assert levels.enthaelt_frage(text) is True


@pytest.mark.parametrize("text", [
    "Der Uhrzeiger steht auf 3. Lena gibt nichts her.",
    "Die Formel steht im Buch. Er formte den Ton.",
    "In der Schulbibliothek stehen 128 Bücher. Am Montag werden 36 ausgeliehen.",
    "Ein Seil ist 3 m lang. Ich schneide 85 cm ab.",
    "",
])
def test_teilwoerter_sind_keine_imperative(text):
    assert levels.enthaelt_frage(text) is False


# --- Ausgangspruefung je Schulstufe ----------------------------------------

def test_auf_der_sekundarstufe_ist_die_gleichung_der_aufgabe_kein_ergebnis():
    hilfe = "Die Gleichung x² − 6x + 5 = 0 ist eine quadratische Gleichung."
    assert "Gleichung mit Ergebnis" in ap.verstoesse(hilfe, 1, 5, [])
    assert "Gleichung mit Ergebnis" not in ap.verstoesse(
        hilfe, 1, 5, [ANGABE_SEK], schulstufe=levels.MITTELSTUFE, loesung=LOESUNG_SEK)


def test_auf_der_sekundarstufe_faellt_das_endergebnis_rechts_vom_gleichheitszeichen_auf():
    hilfe = "Dann bekommst du x = 5 als eine Lösung."
    gefunden = ap.verstoesse(hilfe, 3, 5, [ANGABE_SEK], schulstufe=levels.OBERSTUFE,
                             loesung=LOESUNG_SEK)
    assert "Gleichung mit Ergebnis" in gefunden


def test_ohne_gepruefte_loesung_prueft_die_sekundarstufe_keine_gleichung():
    hilfe = "Setze x = 2 ein und schau, was herauskommt."
    assert "Gleichung mit Ergebnis" not in ap.verstoesse(
        hilfe, 3, 5, [ANGABE_SEK], schulstufe=levels.MITTELSTUFE)


def test_hochzahlen_indizes_und_winkel_sind_keine_neuen_zahlen():
    hilfe = "Bei x^2 und x_1 und einem Winkel von 32° geht es um die Form, nicht um Zahlen."
    assert "neue Zahl" in ap.verstoesse(hilfe, 1, 5, ["Bestimme x."])
    assert "neue Zahl" not in ap.verstoesse(hilfe, 1, 5, ["Bestimme x."], schulstufe=levels.OBERSTUFE)


def test_die_zahl_aus_der_rueckfrage_des_kindes_ist_erlaubt():
    eigenes = [ANGABE_SEK, "Ist 3 die Lösung?"]
    hilfe = "Du hast 3 vorgeschlagen; prüfe das durch Einsetzen."
    assert "neue Zahl" not in ap.verstoesse(hilfe, 2, 5, eigenes, schulstufe=levels.MITTELSTUFE)


@pytest.mark.parametrize("stufe", [1, 2, 3])
def test_das_werkzeug_ist_auf_stufe_eins_bis_drei_der_sekundarstufe_verboten(stufe):
    hilfe = "Hier hilft der Satz des Pythagoras weiter."
    assert "genanntes Werkzeug" in ap.verstoesse(
        hilfe, stufe, 5, ["Eine Leiter lehnt an der Wand."], schulstufe=levels.MITTELSTUFE)


def test_das_werkzeug_ist_auf_stufe_vier_erlaubt_und_in_der_volksschule_ohne_bedeutung():
    hilfe = "Welche Seite ist die Hypotenuse? Dann kannst du den Satz des Pythagoras anwenden."
    assert "genanntes Werkzeug" not in ap.verstoesse(
        hilfe, 4, 5, ["Eine Leiter lehnt an der Wand."], schulstufe=levels.MITTELSTUFE)
    assert "genanntes Werkzeug" not in ap.verstoesse(hilfe, 2, 5, ["Eine Leiter."])


def test_das_werkzeug_aus_der_angabe_darf_genannt_werden():
    hilfe = "Die Ableitung sagt, wie steil die Funktion ist."
    assert ap.verstoesse(hilfe, 1, 5, ["Bestimme die Ableitung von f."],
                         schulstufe=levels.OBERSTUFE) == []


def test_stufe_vier_darf_den_schritt_als_rechnung_nennen():
    """Benchmark, Befund 5: 10 von 45 Stufe-4-Hilfen wegen "7 plus 5"
    gekuerzt, obwohl der Schritt der Auftrag ist."""
    assert "ausgeschriebene Rechnung" not in ap.verstoesse(
        "Wie viel ist 7 plus 5?", 4, 5, ["Lena hat 7 Murmeln und bekommt 5."])
    assert "Gleichung mit Ergebnis" in ap.verstoesse(
        "7 plus 5 = 12.", 4, 5, ["Lena hat 7 Murmeln und bekommt 5."])


@pytest.mark.parametrize("text", [
    "Du musst die Packungen zusammenzuzählen versuchen.",
    "Versuch, 36 von 128 abzuziehen.",
    "Zeig 14 Finger und nimm 6 weg.",
    "Nimm die Stifte einfach weg.",
    "Du kannst die Autos wegnehmen.",
    "Rechne 6 plus 8 und schau.",
    "Wenn du durch 8 teilst, siehst du es.",
])
def test_die_durchgerutschten_formen_der_volksschule_fallen_jetzt_auf(text):
    assert "genannte Rechenart" in ap.verstoesse(text, 2, 5, [ANGABE_VS])


@pytest.mark.parametrize("kind, hilfe", [
    ("348 - 56 = 292", "Du hast 348 minus 56 gerechnet und bekommst 292. Das passt noch nicht."),
    ("348 - 56 = 292", "348 − 56 = 292 stimmt, aber das ist erst der erste Teil."),
    ("ich hab 6 plus 8 gerechnet", "6 + 8 passt nicht, weil es 6 Packungen zu je 8 sind."),
    ("24 : 18 = 1,33", "Du hast 24 geteilt durch 18 gerechnet, das ist umgekehrt."),
    ("6 x 8 = 48", "6 · 8 hast du gerechnet, und = 48 steht bei dir."),
])
def test_die_rechnung_des_kindes_ist_in_jeder_schreibweise_ein_zitat(kind, hilfe):
    """Lauf D: 51 % der Stufe-2-Hilfen gekuerzt, weil das Zitat-Privileg
    woertlich war und die Rueckmeldung "348 minus 56" fuer "348 - 56" sagte."""
    assert "ausgeschriebene Rechnung" not in ap.verstoesse(hilfe, 2, 5, [ANGABE_VS, kind])
    assert "Gleichung mit Ergebnis" not in ap.verstoesse(hilfe, 2, 5, [ANGABE_VS, kind])


def test_die_rechenart_des_kindes_darf_in_jedem_wort_benannt_werden():
    """Lauf D2: "Du hast die Zahlen so addiert, als ob ..." wurde gekuerzt,
    obwohl das Kind "1,20 + 65" geschrieben hatte. Die Rechenart, die das
    Kind benutzt hat, verraet nichts; die richtige bleibt verboten."""
    kind = ["Ich hab 1,20 + 65 gerechnet, das sind 66,20"]
    hilfe = "Du hast die Zahlen so addiert, als wären Euro und Cent gleich. Was ist 1,20 Euro in Cent?"
    assert "genannte Rechenart" not in ap.verstoesse(hilfe, 2, 5, [ANGABE_VS] + kind)
    verraet = "Du hast addiert, aber du musst die Packungen malnehmen."
    assert "genannte Rechenart" in ap.verstoesse(verraet, 2, 5, [ANGABE_VS] + kind)


def test_ein_vorzeichen_in_der_angabe_ist_keine_rechenart_des_kindes():
    """Lauf D3, sek06: 'minus 7 Grad' in der Angabe liess 'abziehst' und
    'wegnimmst' unter 'Nur Tipps' als Zitat durch."""
    angabe = "Am Morgen hat es minus 7 Grad. Bis zum Mittag steigt die Temperatur um 12 Grad."
    hilfe = "Was passiert, wenn du 7 von 12 abziehst?"
    assert "genannte Rechenart" in ap.verstoesse(hilfe, 2, 3, [angabe, "weiß nicht"],
                                                  schulstufe=levels.MITTELSTUFE)
    assert "genannte Rechenart" not in ap.verstoesse(hilfe, 2, 3, [angabe, "12 - 7 = 5"],
                                                      schulstufe=levels.MITTELSTUFE)


def test_eine_andere_rechnung_mit_denselben_zahlen_bleibt_ein_verstoss():
    kind = ["7 - 5 = 2"]
    assert "ausgeschriebene Rechnung" in ap.verstoesse("Rechne lieber 7 plus 5.", 2, 5, ["Lena"] + kind)
    assert "Gleichung mit Ergebnis" in ap.verstoesse("Dann ist 7 + 5 = 12.", 2, 5, ["Lena"] + kind)


def test_das_hauptwort_teile_bleibt_erlaubt():
    assert "genannte Rechenart" not in ap.verstoesse(
        "Stell dir 24 gleich große Teile vor.", 3, 5, ["24 Teile."])


@pytest.mark.parametrize("text", [
    "So eine Rechnung kommt im Alltag oft vor.",
    "Lena rechnet gern mit Murmeln.",
    "Kennst du einen Zählreim?",
])
def test_rechnung_rechnet_und_zaehlreim_sind_auf_stufe_eins_kein_rechenweg(text):
    assert "genannter Rechenweg" not in ap.verstoesse(text, 1, 5, [ANGABE_VS])


@pytest.mark.parametrize("text", [
    "Das musst du ausrechnen.",
    "Rechne die Stifte zusammen.",
    "Du kannst das berechnen.",
])
def test_rechne_und_berechnen_bleiben_auf_stufe_eins_ein_rechenweg(text):
    assert "genannter Rechenweg" in ap.verstoesse(text, 1, 5, [ANGABE_VS])


# --- Endergebnis und Loesungspruefung -------------------------------------

def test_endergebnis_zahlen_liest_die_marke_der_qualitaetssicherung():
    assert ap.endergebnis_zahlen("WEG: 6 · 8.\nERGEBNIS: 48 Stifte") == {"48"}
    assert ap.endergebnis_zahlen("6 mal 8 ist 48. Ergebnis: 48 Stifte") == {"48"}
    assert ap.endergebnis_zahlen(LOESUNG_SEK) == {"1", "5"}
    assert ap.endergebnis_zahlen("Erst 3,15 dann 3,20.\n3,15 Euro") == {"3.15"}
    assert ap.endergebnis_zahlen("") == set()


def test_loesung_passt_vergleicht_zahlen():
    assert ap.loesung_passt("6 · 8 = 48. Es sind 48 Stifte.", "ERGEBNIS: 48 Stifte") is True
    assert ap.loesung_passt("6 · 8 = 46. Es sind 46 Stifte.", "ERGEBNIS: 48 Stifte") is False
    assert ap.loesung_passt("x = 1 oder x = 5", LOESUNG_SEK) is True
    assert ap.loesung_passt("irgendwas", "") is None
    assert ap.loesung_passt("3,15 Euro", "ERGEBNIS: 3,15 €") is True


def test_schaerfung_fuer_folgt_der_reihenfolge_des_schadens():
    assert ap.schaerfung_fuer(["neue Zahl", "genannter Rechenweg"]) == ap.SCHAERFUNG_METHODE
    assert ap.schaerfung_fuer(["genanntes Werkzeug", "neue Zahl"]) == ap.SCHAERFUNG_WERKZEUG
    assert ap.schaerfung_fuer(["genannte Rechenart"]) == ap.SCHAERFUNG_RECHENART
    assert ap.schaerfung_fuer(["neue Zahl"]) == ap.SCHAERFUNG_ZAHL
    assert ap.schaerfung_fuer(["Gleichung mit Ergebnis"]) == ap.SCHAERFUNG
