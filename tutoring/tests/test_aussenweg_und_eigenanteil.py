"""Der Weg nach draussen im Verlauf jeder Betriebsart, und der Eigenanteil.

Thomas (1.11.2026): "Wenn das Frontier-Modell mitarbeitet, ist auch die
Kommunikation zwischen Frontier-Modell und lokaler KI, sprich Spark, sichtbar.
Ist das so? Falls nicht, bau das ein, und zwar in allen Stundentypen. Also
auch bei Musik." Und: "Ich haette gerne einen Prozentsatz, wie viel der
Schueler aufgrund der Hilfe dann geschafft hat ... mit dem Hinweis, dass es
eine grobe Einschaetzung ist."
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import cloud, klassenbild, levels
from tutoring.models import (BETRIEB, FORSCHUNG_VOLL, Hint, Interaction,
                             LearningSession, Participation, Task)

pytestmark = pytest.mark.django_db

AUFGABE = "In einer Schachtel sind 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?"


class _Zug:
    def __init__(self, art=levels.ART_HILFE, level=0, result=""):
        self.art, self.level, self.result = art, level, result


def _hilfe(stufe, result=""):
    return _Zug(levels.ART_HILFE, stufe, result)


# --- Die Faustregel -------------------------------------------------------------

def test_der_eigenanteil_folgt_der_staerksten_hilfe_vor_dem_ergebnis():
    # Richtig im ersten Versuch, vor jeder Hilfe: alles selbst.
    assert klassenbild.eigenanteil([_Zug(levels.ART_AUFTAKT, 0, "richtig")])["anteil"] == 100
    # Eine Nachfrage ist keine Hilfe.
    assert klassenbild.eigenanteil([_Zug(levels.ART_NACHFRAGE, 0, "richtig")])["anteil"] == 100
    assert klassenbild.eigenanteil([_hilfe(1, "richtig")])["anteil"] == 90
    assert klassenbild.eigenanteil([_hilfe(1), _hilfe(2, "richtig")])["anteil"] == 70
    assert klassenbild.eigenanteil([_hilfe(2, "falsch"), _hilfe(2, "richtig")])["anteil"] == 70
    assert klassenbild.eigenanteil([_hilfe(3, "richtig")])["anteil"] == 60
    assert klassenbild.eigenanteil([_hilfe(4, "richtig")])["anteil"] == 40
    # Nach dem Ergebnis zaehlt nichts mehr: Bestaetigung und Nachsatz.
    befund = klassenbild.eigenanteil([_hilfe(2, "richtig"), _Zug(levels.ART_BESTAETIGUNG),
                                      _Zug(levels.ART_NACHSATZ)])
    assert befund["anteil"] == 75 and befund["hoechste"] == 2 and befund["hilfen"] == 1
    assert befund["stand"] == klassenbild.GELOEST
    assert befund["text"] == "etwa 75 % selbst, 25 % durch die Hilfen"


def test_viele_hilfen_kosten_je_fuenf_punkte_bis_zum_boden():
    folge = [_hilfe(1)] * 8 + [_hilfe(2, "richtig")]
    assert klassenbild.eigenanteil(folge)["anteil"] == 35
    folge = [_hilfe(4)] * 20 + [_hilfe(4, "richtig")]
    assert klassenbild.eigenanteil(folge)["anteil"] == klassenbild.ANTEIL_MINDESTENS


def test_die_gezeigte_loesung_ist_null_und_ohne_ergebnis_gibt_es_nichts():
    gezeigt = klassenbild.eigenanteil([_hilfe(2, "falsch"), _hilfe(levels.LOESUNG)])
    assert gezeigt["anteil"] == 0 and gezeigt["stand"] == klassenbild.LOESUNG_GEZEIGT
    assert gezeigt["text"] == "Lösung gezeigt"
    assert klassenbild.eigenanteil([_hilfe(1), _hilfe(2, "falsch")]) is None
    assert klassenbild.eigenanteil([]) is None
    assert klassenbild.eigenanteil_text(100) == "ohne Hilfe gelöst"


def test_das_mittel_und_die_zeile():
    a = klassenbild.eigenanteil([_hilfe(1, "richtig")])        # 90
    b = klassenbild.eigenanteil([_hilfe(3, "richtig")])        # 60
    offen = klassenbild.eigenanteil([_hilfe(2, "falsch")])     # None
    assert klassenbild.eigenanteil_mittel([a, b, offen]) == 75
    assert klassenbild.eigenanteil_mittel([offen]) is None
    assert klassenbild.eigenanteil_zeile([a, b, offen]) == "etwa 75 % selbst, 25 % durch die Hilfen (2 Aufgaben)"
    assert klassenbild.eigenanteil_zeile([a]) == "etwa 90 % selbst, 10 % durch die Hilfen (1 Aufgabe)"
    assert klassenbild.eigenanteil_zeile([offen]) == ""
    assert klassenbild.leere_kachel()["eigenanteil_zeile"] == ""


# --- Durch die Seiten -----------------------------------------------------------

@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


def _stunde(lehrperson, **werte):
    vorgaben = {"title": "Stifte", "teacher": lehrperson, "subject": "mathematik",
                "research_level": FORSCHUNG_VOLL}
    vorgaben.update(werte)
    return LearningSession.objects.create(**vorgaben)


def _kind(stunde, tier="fuchs"):
    return Participation.objects.create(learning_session=stunde, animal=tier, token=f"t-{tier}")


def _verlauf(client, stunde, kind):
    return client.get(reverse("tutoring:lehrperson_verlauf", args=[stunde.code, kind.pk]),
                      secure=True).content.decode()


def _klassenliste(client, stunde):
    return client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]),
                      secure=True).content.decode()


def test_der_verlauf_in_mathematik_zeigt_den_weg_nach_draussen_mit_wortlaut(client, lehrperson):
    stunde = _stunde(lehrperson, cloud_enabled=True)
    kind = _kind(stunde)
    aufgabe = Task.objects.create(
        participation=kind, text=AUFGABE, checked_solution="6 · 8 = 48 Stifte",
        checked_model="gpt-5", checked_sent="[PERS_a1b2] hat 6 Packungen mit je 8 Stiften.",
        checked_received="ERGEBNIS: 48 Stifte",
    )
    Task.objects.filter(pk=aufgabe.pk).update(checked_at=aufgabe.created_at)
    Interaction.aufzeichnen(
        sitzung=stunde, teilnahme=kind, weg=Interaction.CLOUD, modell="gpt-5",
        tokens_ein=300, tokens_aus=50, dauer_ms=4000, kosten_micro=1234,
        leak_check=Interaction.BESTANDEN, entitaeten={"PERS": 1},
        maskiert_ein="[PERS_a1b2] hat 6 Packungen mit je 8 Stiften.",
        maskiert_aus="ERGEBNIS: 48 Stifte", text_aus="6 · 8 = 48 Stifte",
        anweisung=cloud.SYSTEM,
    )
    Hint.objects.create(task=aufgabe, level=2, text="Schau auf die Packungen.",
                        response="6 · 8 = 48", result=Hint.ERGEBNIS_RICHTIG)
    client.force_login(lehrperson)

    seite = _verlauf(client, stunde, kind)

    assert "Der Weg nach draußen" in seite
    assert "1 Anfrage nach draußen für" in seite
    assert "Das ist hinausgegangen" in seite and "[PERS_a1b2] hat 6 Packungen" in seite
    assert "Das kam zurück" in seite and "ERGEBNIS: 48 Stifte" in seite
    assert "Anweisung an die Gegenstelle" in seite
    # Der dritte Schritt: wie der Spark die Loesung bekommen hat, im Wortlaut.
    assert "So hat der Spark sie bekommen" in seite
    assert "NUR FÜR DICH" in seite and "Eine geprüfte Lösung dieser Aufgabe liegt vor" in seite
    # Der Eigenanteil je Aufgabe und im Kopf.
    assert "Eigenanteil, grobe Einschätzung:" in seite
    assert "etwa 75 % selbst, 25 % durch die Hilfen" in seite
    assert "stärkste Hilfe Stufe 2, 1 Stufenhilfe vor dem Ergebnis" in seite
    assert "(1 Aufgabe), grobe Einschätzung" in seite


def test_auf_stufe_eins_stehen_nur_zahlen_aber_der_weg_ist_sichtbar(client, lehrperson):
    stunde = _stunde(lehrperson, cloud_enabled=True, research_level=BETRIEB)
    kind = _kind(stunde)
    Interaction.aufzeichnen(
        sitzung=stunde, teilnahme=kind, weg=Interaction.CLOUD, modell="gpt-5",
        tokens_ein=300, tokens_aus=50, leak_check=Interaction.BESTANDEN,
        maskiert_ein="[PERS_a1b2] hat 6 Packungen.", maskiert_aus="48",
    )
    client.force_login(lehrperson)

    seite = _verlauf(client, stunde, kind)

    assert "1 Anfrage nach draußen für" in seite
    assert "Nur Zahlen" in seite and "[PERS_a1b2]" not in seite


def test_ohne_qualitaetssicherung_sagt_der_verlauf_dass_nichts_hinausging(client, lehrperson):
    stunde = _stunde(lehrperson, cloud_enabled=False)
    kind = _kind(stunde)
    client.force_login(lehrperson)

    seite = _verlauf(client, stunde, kind)

    assert "Der Weg nach draußen" in seite
    assert "Die Qualitätssicherung ist für diese Sitzung aus" in seite
    assert "ist nichts hinausgegangen" in seite


@pytest.mark.parametrize("fach, betriebsart, satz", [
    ("musik", LearningSession.BETRIEB_MUSIK, "In der Musikstunde arbeitet keine externe KI mit"),
    ("deutsch", LearningSession.BETRIEB_TRAINER, "Im Trainer arbeitet keine externe KI mit"),
    ("englisch", LearningSession.BETRIEB_SPRACHE, "Im Sprechcoach arbeitet keine externe KI mit"),
])
def test_in_den_anderen_betriebsarten_steht_dass_keine_externe_ki_mitarbeitet(
        client, lehrperson, fach, betriebsart, satz):
    stunde = _stunde(lehrperson, subject=fach, mode=betriebsart, cloud_enabled=True)
    kind = _kind(stunde)
    client.force_login(lehrperson)

    seite = _verlauf(client, stunde, kind)

    assert "Der Weg nach draußen" in seite
    assert satz in seite and "keinen Weg nach draußen" in seite


def test_die_kachel_traegt_den_eigenanteil_ueber_alle_aufgaben(client, lehrperson):
    stunde = _stunde(lehrperson)
    kind = _kind(stunde)
    erste = Task.objects.create(participation=kind, text=AUFGABE)
    Hint.objects.create(task=erste, level=1, text="h", response="48",
                        result=Hint.ERGEBNIS_RICHTIG)                       # 90
    zweite = Task.objects.create(participation=kind, text="7 + 5")
    Hint.objects.create(task=zweite, level=2, text="h", response="11", result=Hint.ERGEBNIS_FALSCH)
    Hint.objects.create(task=zweite, level=3, text="h", response="12",
                        result=Hint.ERGEBNIS_RICHTIG)                       # 60 - 5 = 55
    offen = Task.objects.create(participation=kind, text="9 - 4")
    Hint.objects.create(task=offen, level=1, text="h", response="weiß nicht", result="offen")
    client.force_login(lehrperson)

    liste = _klassenliste(client, stunde)

    # (90 + 55) / 2 = 72,5, auf fuenf gerundet: 75; zwei Aufgaben mit Ergebnis.
    assert "etwa 75 % selbst, 25 % durch die Hilfen (2 Aufgaben)" in liste
    assert "kachel-anteil" in liste
    assert "Grobe Einschätzung" in liste
