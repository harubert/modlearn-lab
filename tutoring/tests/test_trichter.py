"""Der Trichter-Indikator (Zech, Kap. 10.2, S. 285 und 288).

Thomas (31.10.2026, zu "Didaktik im Prompt" Frage 2): Die erste Hilfe jeder
Stufe ist auf allen Schulstufen indirekt, eine weite Denkfrage oder ein
Impuls; die Wiederholung derselben Stufe ist direkt, aber auch sie wird keine
Einsetzfrage. Gemessen wird der Anteil der Schlussfragen, die nur eine Zahl,
ein Wort oder Ja/Nein einsetzen lassen; er darf von D3 zu G nicht steigen.
"""
import pytest

from tutoring import ausgabepruefung, levels


@pytest.mark.parametrize("frage, erwartet", [
    # eine Zahl
    ("Wie viele Packungen brauchst du?", "zahl"),
    ("Wieviel kostet das zusammen?", "zahl"),
    ("Was ergibt 6 · 8?", "zahl"),
    ("Was ist 48 : 6?", "zahl"),
    ("Was ist die Hälfte von 10?", "zahl"),
    ("Was kommt bei 6 · 8 heraus?", "zahl"),
    ("Was kommt heraus?", "zahl"),
    ("Wie lang ist die Seite?", "zahl"),
    ("Welche Zahl steht dann im Ergebnis?", "zahl"),
    ("Und was ergibt das?", "zahl"),
    ("Was bleibt übrig?", "zahl"),
    ("Welchen Wert erhältst du, wenn du x = 1 einsetzt?", "zahl"),
    ("Welche Wahrscheinlichkeit ergibt sich für den zweiten Zug?", "zahl"),
    ("Welche zwei Zahlen erfüllen beide Bedingungen?", "zahl"),
    ("Welche Zahlen aus der Aufgabe brauchst du?", "zahl"),
    ("Wie lautet das Ergebnis?", "zahl"),
    ("Wenn du 18 Kinder in Gruppen zu je 3 aufteilst, wie viele Gruppen sind das?", "zahl"),
    ("Schau auf die beiden Zahlen: was ist die Differenz?", "zahl"),
    ("Was ist die größte Note, die Max hat?", "zahl"),
    ("Lisa fährt um 7:50 weg und kommt um 8:35 an; wie viele Minuten vergehen dazwischen?", "zahl"),
    # ein Wort
    ("Welche Rechenart passt hier?", "wort"),
    ("Was für Winkel hat ein Rechteck?", "wort"),
    ("Wie heißt die Form?", "wort"),
    # Ja oder Nein
    ("Stimmt das?", "janein"),
    ("Hast du die 8 schon dazugezählt?", "janein"),
    ("Passt plus hier?", "janein"),
    ("Kannst du das mit einer Zeichnung prüfen?", "janein"),
    # offen: Denkfragen, Impulse, eingebettete Fragen
    ("Siehst du, warum das nicht aufgehen kann?", ""),
    ("Weißt du, was die Aufgabe eigentlich wissen will?", ""),
    ("Was rechnest du jetzt?", ""),
    ("Warum passt dein Ergebnis zur Aufgabe?", ""),
    ("Wie hast du angefangen?", ""),
    ("Woran erkennst du, dass es eine Minusaufgabe ist?", ""),
    ("Was soll man hier herausfinden?", ""),
    ("Was ist gegeben, und was ist gesucht?", ""),
    ("Was ist mit den 3 Kindern, die noch dazukommen?", ""),
    ("Wie könntest du das prüfen?", ""),
    ("Was fällt dir an den beiden Zahlen auf?", ""),
    ("Wie lautet die Gleichung, die beide Angaben verbindet?", ""),
    ("Welche Rechnung musst du jetzt machen?", ""),
    ("Welche Regel hilft dir, den Term zu vereinfachen?", ""),
    ("Wie berechnest du das Volumen eines Quaders?", ""),
    # keine Frage
    ("Probier es aus.", ""),
    ("", ""),
    (None, ""),
])
def test_einsetzfragen_lassen_nur_eine_zahl_ein_wort_oder_ja_nein_zu(frage, erwartet):
    assert ausgabepruefung.einsetzfrage(frage) == erwartet


def test_anfuehrungszeichen_und_vorspann_stoeren_nicht():
    assert ausgabepruefung.einsetzfrage("„Wie viele sind es?“") == "zahl"
    assert ausgabepruefung.einsetzfrage("Also, stimmt das so?") == "janein"


def test_keine_vorlage_ist_eine_einsetzfrage():
    """Die festen Fragen des Servers duerfen den Indikator nicht treiben:
    "Was kommt heraus?" (bis 31.10.2026 die Vorlage der Stufe 3) war eine."""
    for frage in list(levels.SCHLUSSFRAGE_VORLAGE.values()) + list(levels.SCHLUSSFRAGE_VORLAGE_ZUG.values()):
        assert ausgabepruefung.einsetzfrage(frage) == "", frage


def test_die_formsaetze_sagen_denkfrage_und_keine_einsetzfrage():
    assert "Denkfrage" in levels.FORM_SATZ[levels.FORM_INDIREKT]
    assert "ein Wort oder eine Zahl" in levels.FORM_SATZ[levels.FORM_DIREKT]
    assert "Wie viele" not in ausgabepruefung.NACHFASSEN_FRAGE
