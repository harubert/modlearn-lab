"""Pruefungen der Ausgangspruefung.

Anlass: Bei "6 Packungen zu je 8 Stiften" antwortete Stufe 1 mit
"Probier's mal mit dem Zaehlen: 8, 16, 24, 32, 40, 48." Das ist die Loesung,
auf der ersten Stufe, obwohl der Systemprompt sie ausdruecklich verbietet.
Ein Systemprompt ist eine Bitte, keine Grenze.
"""

import pytest

from tutoring import ausgabepruefung as ap


@pytest.mark.parametrize("text", [
    "Probier's mal mit dem Zählen: 8, 16, 24, 32, 40, 48.",
    "Du rechnest 6 · 8 = 48.",
    "Das ergibt = 48 Stifte.",
    "Nimm 128 minus 36 und schau, was herauskommt.",
    "Zähl einfach 8, 16, 24, 32 weiter.",
])
def test_verbotene_formen_fallen_auf(text):
    assert ap.verstoesse(text, 1, 5)


AUFGABE = "In einer Schachtel sind 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?"


@pytest.mark.parametrize("text", [
    "Schau dir die Angabe noch einmal in Ruhe an.",
    "Was ist gegeben, was ist gesucht?",
    "Du hast 6 Packungen, und in jeder sind 8 Stifte.",
    "Eine Schulbibliothek ist ein Raum in der Schule.",
    "Das ist ein guter Einwand, hier steht wirklich keine Frage.",
])
def test_harmlose_hilfen_kommen_durch(text):
    assert ap.verstoesse(text, 1, 5, [AUFGABE]) == []


def test_die_nennung_zweier_zahlen_allein_ist_erlaubt():
    """Sonst duerfte Stufe 1 die Angabe nicht einmal wiedergeben."""
    assert ap.verstoesse(
        "Es gibt 6 Packungen und in jeder Packung sind 8 Stifte.", 1, 5, [AUFGABE]
    ) == []


# --- Keine neuen Zahlen unterhalb der Loesungsstufe -----------------------

def test_eine_zahl_die_nirgends_steht_ist_das_ergebnis():
    """Anlass: Die Rueckfrage antwortete bei "nur Tipps" mit "Die Antwort ist 48."

    Kein Rechenzeichen, keine Gleichung, und trotzdem genau das, was die
    Lehrperson ausgeschlossen hatte. Die einfachste Regel, die das faengt:
    Eine Hilfe darf die gegebenen Zahlen wiederholen, aber keine neue
    hervorbringen.
    """
    assert "neue Zahl" in ap.verstoesse("Die Antwort ist 48.", 3, 3, [AUFGABE])


def test_die_summe_in_einzelschritten_faellt_ebenfalls_auf():
    hilfe = "Das ist wie 8 + 8 + 8 + 8 + 8 + 8. Das ergibt 48."

    assert ap.verstoesse(hilfe, 3, 3, [AUFGABE])


def test_die_zahl_des_kindes_darf_aufgegriffen_werden():
    kind = ["Ich hab 6 plus 8 gerechnet, das sind 14 Stifte"]
    hilfe = "Die 14, die du hast, ist die Summe der beiden Zahlen."

    assert ap.verstoesse(hilfe, 2, 5, [AUFGABE] + kind) == []


def test_auf_der_loesungsstufe_sind_neue_zahlen_erlaubt():
    """Stufe 5 rechnet vor, das ist ihre Aufgabe."""
    assert ap.verstoesse("6 · 8 = 48. Es sind also 48 Stifte.", 5, 5, [AUFGABE]) == []


def test_stufe_fuenf_darf_vorrechnen():
    assert ap.verstoesse("6 · 8 = 48. Es sind also 48 Stifte.", 5, 5) == []


def test_bei_nur_tipps_bleibt_auch_stufe_drei_geprueft():
    """Die letzte erlaubte Stufe ist hier 3, und die darf nicht rechnen."""
    assert ap.verstoesse("Rechne 6 · 8.", 3, 3)


def test_gekuerzt_wird_satzweise():
    text = ("Schau dir die Angabe an. Du rechnest 6 · 8 = 48. "
            "Was ist gegeben, was ist gesucht?")

    sauber = ap.saubere_saetze(text, 1, 5)

    assert "48" not in sauber
    assert "Schau dir die Angabe an." in sauber
    assert "Was ist gegeben" in sauber


def test_jede_stufe_hat_einen_notfallsatz():
    """Bleibt nach dem Kuerzen nichts uebrig, darf die Seite nicht leer sein."""
    for stufe in (1, 2, 3, 4):
        assert ap.NOTFALL[stufe]
        assert ap.verstoesse(ap.NOTFALL[stufe], stufe, 5) == []


def test_der_eigene_falsche_ansatz_darf_zitiert_werden():
    """Sonst schneidet die Pruefung genau den Satz weg, um den es geht.

    Die Rueckmeldungshilfe muss sagen duerfen, dass "6 plus 8" hier nicht
    passt. Das sieht wie eine Rechnung aus, ist aber ein Zitat.
    """
    # Wie ueberall: zuerst die Angabe, dann die Beitraege des Kindes. Ohne
    # die Angabe davor waere "du hast ... gerechnet" ein Zitat vor dem ersten
    # Beitrag, also erfunden (Stichprobe 31.10.2026).
    kind = [AUFGABE, "Ich rechne 6 plus 8, das sind 14 Stifte"]
    hilfe = "Du hast 6 plus 8 gerechnet, aber das passt hier nicht."

    assert ap.verstoesse(hilfe, 2, 5, kind) == []


def test_eine_neue_rechnung_faellt_trotzdem_auf():
    """Der Freibrief gilt nur fuer das, was das Kind selbst geschrieben hat."""
    kind = ["Ich rechne 6 plus 8, das sind 14 Stifte"]
    hilfe = "Du hast 6 plus 8 gerechnet. Richtig wäre 6 · 8."

    assert ap.verstoesse(hilfe, 2, 5, kind)


# --- Stufe 1 darf keine Methode nennen ------------------------------------

@pytest.mark.parametrize("text", [
    "Das ist eine Aufgabe, bei der du zählen musst.",
    "Probier es ruhig mit dem Zählen.",
    "Das musst du ausrechnen.",
    "Du kannst die Packungen zusammenzählen.",
    "Hier hilft das Einmaleins.",
])
def test_stufe_eins_nennt_keinen_rechenweg(text):
    """Anlass: Stufe 1 antwortete mit "Probier es ruhig mit dem Zählen."

    Der Systemprompt verbietet das seit dem ersten Tag. Er ist eben eine
    Bitte; die Grenze gehoert in den Server.
    """
    assert "genannter Rechenweg" in ap.verstoesse(text, 1, 5)


@pytest.mark.parametrize("text", [
    "Erzähl mir, was du schon verstanden hast.",
    "Eine Schulbibliothek ist ein Raum in der Schule.",
    "Du hast 6 Packungen, und in jeder sind 8 Stifte.",
    "Was steht da alles drin, und was möchte jemand wohl wissen?",
])
def test_stufe_eins_darf_die_situation_erklaeren(text):
    assert ap.verstoesse(text, 1, 5, [AUFGABE]) == []


def test_ab_stufe_zwei_darf_die_rechenart_benannt_werden():
    """Sonst koennte die Rueckmeldungshilfe den Fehler nicht benennen.

    Der Freibrief gilt aber nur fuer das Wort, das das Kind selbst benutzt
    hat. Ohne seinen Beitrag waere "addiert" ein Hinweis auf die Rechenart.
    """
    kind = [AUFGABE, "Ich hab addiert"]
    hilfe = "Du hast addiert, aber die Rechenart passt hier nicht."

    assert ap.verstoesse(hilfe, 2, 5, kind) == []


def test_der_notfallsatz_von_stufe_eins_haelt_der_eigenen_pruefung_stand():
    assert ap.verstoesse(ap.NOTFALL[1], 1, 5) == []


@pytest.mark.parametrize("text", [
    "Es sind nicht nur 6 und 8 zusammen, sondern 6 mal so viele Stifte.",
    "In jeder Packung sind 8 Stifte, und das 6 mal.",
])
def test_die_rechenart_in_worten_faellt_auf_stufe_eins_auch_auf(text):
    """Anlass: Genau diese Formulierung stand im Betrieb auf Stufe 1.

    Ein Rechenweg bleibt einer, auch wenn kein Rechenzeichen dasteht.
    """
    assert "genannter Rechenweg" in ap.verstoesse(text, 1, 5)


def test_noch_einmal_und_manchmal_sind_keine_rechenwege():
    for text in ("Probier es noch einmal.", "Manchmal hilft eine Skizze.",
                 "Erzähl mir, was du verstanden hast."):
        assert ap.verstoesse(text, 1, 5) == [], text


# --- Stufe 2 und 3 nennen die richtige Rechenart nicht --------------------

@pytest.mark.parametrize("stufe", [2, 3])
def test_die_richtige_rechenart_wird_nicht_genannt(stufe):
    """Anlass: Stufe 2 schrieb "sondern die Packungen malnehmen musst".

    Und zwar, bevor das Kind einen Ansatz hatte. Die eigene Anweisung dieser
    Stufe sagt woertlich: nicht, welche die richtige waere.
    """
    hilfe = "Du musst nicht addieren, sondern malnehmen."

    assert "genannte Rechenart" in ap.verstoesse(hilfe, stufe, 5, [AUFGABE])


def test_der_eigene_ansatz_darf_weiter_benannt_werden():
    """Sonst kann Stufe 2 den Fehler nicht mehr ansprechen."""
    kind = ["Ich hab addiert, 6 plus 8 sind 14"]

    assert ap.verstoesse(
        "Du hast addiert, aber das passt hier nicht.", 2, 5, [AUFGABE] + kind
    ) == []


def test_stufe_drei_darf_die_falsche_rechnung_zitieren():
    kind = ["Ich hab 6 plus 8 gerechnet, das sind 14 Stifte"]
    hilfe = "6 plus 8 ist nicht die richtige Rechnung, weil du nur eine Packung ansiehst."

    assert ap.verstoesse(hilfe, 3, 5, [AUFGABE] + kind) == []


def test_die_rechenart_des_kindes_darf_benannt_werden_die_richtige_nicht():
    """Seit dem Benchmark (19.10.2026, Lauf D2) gilt der Freibrief fuer die
    Rechenart, nicht fuer das Wort: Das Kind schrieb "plus", also darf die
    Hilfe sagen, dass es zusammengezaehlt hat. Das verraet nichts, das Kind
    hat es getan. Vorher war der Freibrief woertlich, und die Rueckmeldung
    "Du hast die Zahlen so addiert, als ob ..." wurde gekuerzt, obwohl sie
    genau den Fehler benannte, den Stufe 2 benennen soll. Die Rechenart, die
    das Kind NICHT benutzt hat, bleibt verboten: Sie ist die richtige.
    """
    kind = ["Ich hab 6 plus 8 gerechnet"]
    hilfe = "Du darfst die Packungen und die Stifte nicht zusammenzählen."
    verraet = "Du darfst nicht zusammenzählen, du musst malnehmen."

    assert "genannte Rechenart" not in ap.verstoesse(hilfe, 3, 5, [AUFGABE] + kind)
    assert "genannte Rechenart" in ap.verstoesse(verraet, 3, 5, [AUFGABE] + kind)


def test_stufe_vier_darf_die_rechenart_nennen():
    """Dort ist die inhaltlich-strategische Hilfe an der Reihe."""
    assert ap.verstoesse("Jetzt kannst du multiplizieren.", 4, 5, [AUFGABE]) == []


@pytest.mark.parametrize("text", [
    "Was passiert, wenn du die 8 Stifte mit der Anzahl der Packungen mal nimmst?",
    "Du musst die Stifte malnehmen.",
    "Hast du sie schon mal genommen?",
])
def test_auch_die_gebeugten_formen_fallen_auf(text):
    """Anlass: "mal nimmst" kam durch, weil das Muster nur den Infinitiv kannte.

    Eine Grenze, die von der Beugung abhaengt, ist keine.
    """
    assert "genannte Rechenart" in ap.verstoesse(text, 2, 5, [AUFGABE])


@pytest.mark.parametrize("text", [
    "Du hast die Packungen nicht richtig zusammengezählt.",
    "Du hast die Zahlen einfach dazugezählt.",
])
def test_das_partizip_trennbarer_verben_zaehlt_mit(text):
    """Trennbare Verben schieben im Partizip ein "ge" ein.

    "zusammengezaehlt" ist dasselbe Wort wie "zusammenzaehlen" und rutschte
    trotzdem durch. Ein Verbot, das an der Zeitform scheitert, ist keins.
    """
    assert "genannte Rechenart" in ap.verstoesse(text, 3, 5, [AUFGABE])
