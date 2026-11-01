"""Pruefungen der Stufenlogik nach Zech.

Das ist der Teil, der den Vortrag traegt: Die Obergrenze der Lehrperson muss
halten, auch wenn das Modell etwas anderes moechte oder ein Kind mehrfach
tippt. Die Logik liegt deshalb in der Anwendung und wird hier festgenagelt.
"""

import pytest

from tutoring import levels


# --- Der normale Weg durch die Stufen -------------------------------------

@pytest.mark.parametrize("erreicht, erwartet", [(0, 1), (1, 2), (2, 3)])
def test_stufen_steigen_einzeln_bei_nur_tipps(erreicht, erwartet):
    assert levels.naechste_stufe(erreicht, levels.NUR_TIPPS) == erwartet


@pytest.mark.parametrize("erreicht, erwartet", [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)])
def test_stufen_steigen_einzeln_bis_zur_loesung(erreicht, erwartet):
    assert levels.naechste_stufe(erreicht, levels.BIS_ZUR_LOESUNG) == erwartet


def test_keine_stufe_wird_uebersprungen():
    """Aus Stufe 1 darf nie Stufe 3 werden, auch nicht bei hoher Obergrenze."""
    assert levels.naechste_stufe(1, levels.BIS_ZUR_LOESUNG) == 2


# --- Die Obergrenze, der eigentliche Punkt --------------------------------

def test_nur_tipps_endet_bei_stufe_drei():
    """Der Kern der Zusage an die Lehrperson: bei 'nur Tipps' keine Loesung."""
    assert levels.naechste_stufe(3, levels.NUR_TIPPS) is None


def test_bis_zur_loesung_endet_bei_stufe_fuenf():
    assert levels.naechste_stufe(5, levels.BIS_ZUR_LOESUNG) is None


@pytest.mark.parametrize("erreicht", [4, 5, 9])
def test_obergrenze_haelt_auch_bei_zu_hohem_stand(erreicht):
    """Steht in der Datenbank ein zu hoher Wert, wird trotzdem nichts ausgegeben.

    Das ist die Absicherung gegen einen Fehler an anderer Stelle: Die
    Obergrenze darf nicht davon abhaengen, dass der gespeicherte Stand stimmt.
    """
    assert levels.naechste_stufe(erreicht, levels.NUR_TIPPS) is None


@pytest.mark.parametrize("stufe, obergrenze, erlaubt", [
    (1, levels.NUR_TIPPS, True),
    (3, levels.NUR_TIPPS, True),
    (4, levels.NUR_TIPPS, False),
    (5, levels.NUR_TIPPS, False),
    (5, levels.BIS_ZUR_LOESUNG, True),
    (0, levels.BIS_ZUR_LOESUNG, False),
])
def test_ist_erlaubt(stufe, obergrenze, erlaubt):
    assert levels.ist_erlaubt(stufe, obergrenze) is erlaubt


# --- Der System-Prompt erzwingt genau eine Stufe --------------------------

@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_system_prompt_nennt_die_stufe_und_ihre_anweisung(stufe):
    prompt = levels.system_prompt(stufe)

    assert levels.BEZEICHNUNGEN[stufe] in prompt
    # Die Anweisungen tragen Platzhalter fuer die Anrede, die von der
    # Altersklasse abhaengt. Verglichen wird deshalb die eingesetzte Fassung.
    eingesetzt = levels.ANWEISUNGEN[levels.VOLKSSCHULE][stufe].format(
        **levels.anrede(levels.ALTERSKLASSE_STANDARD)
    )
    assert eingesetzt in prompt
    assert f"Stufe {stufe}" in prompt
    # Geprueft wird die Zusage, nicht ihr Wortlaut: Der Prompt darf
    # umformuliert werden, solange er weiterhin genau eine Stufe erzwingt.
    assert "mehrere Stufen" in prompt


@pytest.mark.parametrize("stufe", [1, 2, 3, 4])
def test_prompt_unterhalb_der_loesung_verbietet_das_ergebnis(stufe):
    """Jede Stufe unter fuenf sagt ausdruecklich, was sie nicht tun darf.

    Ohne diese Verneinung rutscht das Modell verlaesslich eine Stufe zu weit.
    """
    prompt = levels.system_prompt(stufe)

    assert "VERBOTEN" in prompt
    assert "rgebnis" in prompt, "Die Stufe sagt nicht, dass kein Ergebnis kommt"


def test_nur_stufe_fuenf_darf_vorrechnen():
    assert "Rechne die Aufgabe Schritt für Schritt vor" in levels.system_prompt(5)
    for stufe in (1, 2, 3, 4):
        assert "Schritt für Schritt vor" not in levels.system_prompt(stufe)


def test_prompt_haelt_auch_gegen_bitten_des_kindes():
    """Ein Kind, das nach der Loesung fragt, darf die Stufe nicht aushebeln."""
    assert "wenn das Kind darum bittet" in levels.system_prompt(2)


@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_jede_stufe_hoert_zuerst_zu(stufe):
    """Aus einem Probelauf: Das Kind fragte, was eine Schulbibliothek ist,
    und bekam zur Antwort, darum gehe es hier nicht. Jede Stufe muss zuerst
    auf den Beitrag des Kindes eingehen, erst danach kommt ihre eigene Arbeit.
    """
    prompt = levels.system_prompt(stufe)

    assert "ZUERST" in prompt
    assert "Verständnisfrage" in prompt
    assert "Einwand" in prompt


def test_keine_unwahren_aufmunterungen():
    """"Du bist schon nah dran" bei einem Kind, das noch nichts gerechnet hat."""
    assert "nah dran" in levels.system_prompt(1)


def test_motivationshilfe_darf_die_sache_erklaeren():
    """Motivation ohne Gegenstand wird zur Floskel."""
    anweisung = levels.ANWEISUNGEN[levels.VOLKSSCHULE][levels.MOTIVATION]

    assert "Erkläre Wörter" in anweisung
    assert "keine Frage" in anweisung
    assert "VERBOTEN: rechnen" in anweisung


def test_rueckfrage_nach_stufe_eins_nimmt_stufe_drei_nicht_vorweg():
    """Nach gegeben und gesucht zu fragen ist die Arbeit von Stufe 3."""
    frage = levels.rueckfrage(levels.MOTIVATION)

    assert "gegeben" not in frage
    assert "gesucht" not in frage


@pytest.mark.parametrize("stufe", [0, 6, -1, None])
def test_unbekannte_stufe_wird_abgewiesen(stufe):
    with pytest.raises(ValueError):
        levels.system_prompt(stufe)


def test_jede_stufe_hat_eine_knopfbeschriftung():
    """Sonst steht im Handy ein leerer Knopf."""
    for stufe in levels.BEZEICHNUNGEN:
        assert levels.KNOPFBESCHRIFTUNG.get(stufe)


def test_stufen_zwei_und_drei_nennen_die_gesuchte_groesse_nicht():
    """Aus dem zweiten Probelauf.

    Die Aufgabe enthielt keine Frage. Beide Stufen erfanden sie daraufhin und
    sagten dem Kind, was zu berechnen sei. Das ist die Arbeit von Stufe 4,
    und es nimmt dem Kind genau den Schritt ab, um den es in Stufe 3 geht.
    """
    for stufe in (levels.RUECKMELDUNG, levels.STRATEGIE_ALLGEMEIN):
        anweisung = levels.ANWEISUNGEN[levels.VOLKSSCHULE][stufe]
        assert "gesucht" in anweisung or "gesuchte Größe" in anweisung


def test_fehlende_frage_wird_in_stufe_eins_benannt():
    """Ein Kind, das die Luecke bemerkt, denkt richtig und soll das hoeren."""
    assert "SAGE DAS in jedem Fall" in levels.ANWEISUNGEN[levels.VOLKSSCHULE][levels.MOTIVATION]


@pytest.mark.parametrize("text, erwartet", [
    ("Wie viele Bücher sind es?", True),
    ("Berechne den Rest.", True),
    ("Wie viel ist 7 mal 8", True),
    ("In der Schulbibliothek stehen 128 Bücher. Am Montag werden 36 ausgeliehen.", False),
    ("Ein Seil ist 3 m lang. Ich schneide 85 cm ab.", False),
    ("", False),
])
def test_fehlende_frage_wird_erkannt(text, erwartet):
    """Die Feststellung gehoert in die Anwendung.

    Die Anweisung im Prompt, eine fehlende Frage anzusprechen, hat das Modell
    zweimal ueberlesen. Eine Tatsache in der Anfrage ueberliest es nicht.
    """
    assert levels.enthaelt_frage(text) is erwartet


def test_keine_unwahren_behauptungen_ueber_das_kind():
    """"Du hast schon alles richtig verstanden" an ein Kind, das nichts schrieb."""
    for stufe in (1, 2, 3, 4, 5):
        assert "Behaupte nie" in levels.system_prompt(stufe)


# --- Altersklassen ---------------------------------------------------------

@pytest.mark.parametrize("klasse", [k for k, _ in levels.ALTERSKLASSEN])
def test_jede_altersklasse_ergibt_einen_vollstaendigen_prompt(klasse):
    """Ein fehlender Platzhalter faellt sonst erst im Hoersaal auf."""
    for stufe in (1, 2, 3, 4, 5):
        prompt = levels.system_prompt(stufe, klasse)
        assert "{" not in prompt
        assert levels.BEZEICHNUNGEN[stufe] in prompt


def test_erwachsene_werden_nicht_wie_kinder_angesprochen():
    """Fuer den Vortrag: Das Publikum ist keine vierte Klasse."""
    prompt = levels.system_prompt(1, "erwachsen")

    assert "erwachsenen Person" in prompt
    assert "auf keinen Fall kindlich" in prompt


def test_unbekannte_altersklasse_faellt_auf_die_juengste_zurueck():
    """Die zurueckhaltendste Sprachebene ist die sichere Auslegung."""
    assert levels.anrede("gibt-es-nicht") == levels.anrede(levels.ALTERSKLASSE_STANDARD)


def test_stufenerklaerung_deckt_alle_stufen_ab():
    """Sonst fehlt der Lehrperson ausgerechnet die Stufe, die sie einstellt."""
    erklaert = {e["stufe"] for e in levels.erklaerung_fuer_lehrperson()}

    assert erklaert == set(levels.BEZEICHNUNGEN)
    for e in levels.erklaerung_fuer_lehrperson():
        assert e["tut"] and e["nicht"] and e["danach"]


def test_stufe_drei_darf_keine_rechnung_hinschreiben():
    """Aus dem Browserdurchlauf vom Donnerstag.

    Stufe 3 antwortete "Versuch mal, das so zu schreiben: 128 - 36 = ?
    Dann: ? + 19 = ?" und in einem zweiten Lauf "5 mal 8 ist 40, und dann
    noch einmal 8 dazu". Das ist der Rechenweg samt Zwischenergebnis, also
    Stufe 4 und teilweise Stufe 5.
    """
    anweisung = levels.ANWEISUNGEN[levels.VOLKSSCHULE][levels.STRATEGIE_ALLGEMEIN]

    assert "KEINE Zahl" in anweisung
    assert "Zwischenergebnis" in anweisung
    assert "aehnliches Beispiel" in anweisung


def test_stufe_vier_hilft_auch_dem_blockierten_kind():
    """Bei "ich kann das nicht" wiederholte Stufe 4 wortwoertlich Stufe 3."""
    assert "gehe nicht" in levels.ANWEISUNGEN[levels.VOLKSSCHULE][levels.STRATEGIE_INHALTLICH]


@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_keine_wortwoertlichen_wiederholungen(stufe):
    assert "Wiederhole nicht" in levels.system_prompt(stufe)


def test_stufe_zwei_rechnet_nach():
    """Aus Thomas' Durchlauf: Er hatte addiert statt multipliziert.

    Keine Stufe hat es bemerkt. Die Ampel und die Bereitschaftspruefung
    bewerten die Mathematik bewusst nicht - ein Rechenfehler ist ein gueltiger
    Versuch. Aber die Rueckmeldungshilfe muss ihn benennen, dafuer ist sie da.
    Die Spark-Seite hat nachgemessen: 18 von 18 Aufgaben loest das Modell
    richtig. Es lag also nicht am Modell, sondern am Prompt.
    """
    anweisung = levels.ANWEISUNGEN[levels.VOLKSSCHULE][levels.RUECKMELDUNG]

    assert "RECHNE DEN ANSATZ" in anweisung
    assert "addiert statt" in anweisung
    assert "nicht, welche die richtige" in anweisung


@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_keine_stufe_rechnet_mit_falschen_zahlen_weiter(stufe):
    prompt = levels.system_prompt(stufe)

    assert "Rechne jede Zahl nach" in prompt
    assert "wandert durch die ganze Aufgabe" in prompt


@pytest.mark.parametrize("stufe", [1, 2, 3, 4, 5])
def test_antworten_bleiben_kurz(stufe):
    """Aus einem Durchlauf: Stufe 3 antwortete mit fuenfzehn Zeilen samt
    Aufzaehlung und Tabelle. Fuer ein achtjaehriges Kind ist das keine Hilfe,
    sondern eine Wand.
    """
    prompt = levels.system_prompt(stufe)

    assert "keine Aufzaehlung" in prompt
    assert "Ein Gedanke genuegt" in prompt


def test_volksschule_bekommt_drei_saetze():
    assert "DREI kurze Sätze" in levels.system_prompt(1, "6-10")
