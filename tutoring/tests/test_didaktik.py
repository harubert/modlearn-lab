"""Didaktisches Wissen im Prompt (Thomas' Stichprobe, 31.10.2026).

Die Didaktik (EIS-Prinzip, operatives Prinzip, Grundvorstellungen, Validieren,
Heurismen, Prinzip der minimalen Hilfe; Fachnamen nach Thomas und der
Literaturnotiz aus Siegen, 31.10.2026) steht in jedem Diagnoseprompt, die
Fehlvorstellungen nur
fuer die Themen, deren Stichwoerter in der Angabe stehen. Entwurf und
Katalog: docs/Didaktik im Prompt.md.
"""
from tutoring import levels

PROZENT = "Eine Jacke kostet 80 Euro. Im Ausverkauf gibt es 25 % Rabatt. Was kostet sie jetzt?"
BRUCH = "Rechne: 1/2 + 1/3"
MURMELN = "Lena hat 7 Murmeln. Sie bekommt von Omar noch 5 Murmeln dazu. Wie viele Murmeln hat sie jetzt?"


def test_die_themen_kommen_aus_der_angabe():
    themen = [t for t, _ in levels.fehlvorstellungen_fuer(PROZENT)]
    assert themen[0] == "Prozent"
    assert "Größen: Geld, Zeit, Länge, Gewicht" in themen
    assert [t for t, _ in levels.fehlvorstellungen_fuer(BRUCH)] == ["Brüche"]
    assert [t for t, _ in levels.fehlvorstellungen_fuer(MURMELN)][0] == "Plus und Minus"
    assert levels.fehlvorstellungen_fuer("Welche Figur ist das?") == []
    assert len(levels.fehlvorstellungen_fuer(
        "Ein Rechteck mit 12 m und 8 m, je Packung 3 Stück, 25 % Rabatt, 1/2 davon, "
        "dann die Ableitung der Funktion.")) == 3


def test_ein_malzeichen_x_ist_kein_term():
    assert "Terme und Gleichungen" not in [
        t for t, _ in levels.fehlvorstellungen_fuer("Rechne 6 x 8.")]
    assert "Terme und Gleichungen" in [
        t for t, _ in levels.fehlvorstellungen_fuer("Löse: 3x + 7 = 22")]


def test_der_diagnoseprompt_traegt_die_didaktik_und_fehlvorstellungen():
    prompt = levels.diagnose_prompt(2, aufgabentext=PROZENT)
    assert "DIDAKTIK" in prompt
    for begriff in ("EIS-Prinzip", "Operatives Prinzip", "Grundvorstellung", "Validieren",
                    "Heurismen", "Prinzip der minimalen Hilfe"):
        assert begriff in prompt, begriff
    assert "Plausibilität zuerst" not in prompt, "kein Prinzip, sondern Validieren"
    assert "TYPISCHE FEHLVORSTELLUNGEN" in prompt and "Teil und Ganzes vertauscht" in prompt
    assert "nenne sie so" in prompt
    ohne = levels.diagnose_prompt(2, aufgabentext="Welche Figur ist das?")
    assert "DIDAKTIK" in ohne and "TYPISCHE FEHLVORSTELLUNGEN" not in ohne


def test_der_hilfeprompt_traegt_die_fehlvorstellungen_ab_stufe_zwei():
    eins = levels.system_prompt(1, levels.MITTELSTUFE, aufgabentext=PROZENT)
    assert "DIDAKTIK" in eins and "Zeichnung" in eins
    assert "auch in der Oberstufe" in eins and "ein Wort oder eine Zahl" in eins
    assert "Teil und Ganzes vertauscht" not in eins, "Stufe 1 klaert Begriffe, keine Fehler"
    zwei = levels.system_prompt(2, levels.MITTELSTUFE, aufgabentext=PROZENT)
    assert "Teil und Ganzes vertauscht" in zwei
    assert "nicht das richtige Ergebnis" in zwei
    fuenf = levels.system_prompt(5, levels.MITTELSTUFE, aufgabentext=PROZENT)
    assert "DIDAKTIK" not in fuenf


def test_jedes_thema_hat_stichwoerter_und_einen_text():
    for thema, muster, satz in levels.FEHLVORSTELLUNGEN:
        assert thema and muster and len(satz) > 40
        assert "\n" not in satz
