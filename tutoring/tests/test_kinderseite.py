"""Die Kinderseite nach dem Benchmark (19.10.2026, Abschnitt 6.3).

Ein Bildschirm: die Aufgabe als Karte, das Gespraech als Karten, unten der
Verfasser mit einem Feld und zwei Knoepfen. Das Kind sagt selbst, ob es
fragt oder einen Versuch abgibt. Nach einem Versuch kommt die naechste Hilfe
ohne weiteren Knopfdruck, ein richtiges Ergebnis wird bestaetigt, der
Tippknopf heisst immer gleich, nach "Nein, ich probier weiter" bleibt der
Versuchsmodus, und Stufe 5 wird geprueft, bevor sie das Kind sieht.

Hier laeuft kein Spark: Die Diagnose und der Strom werden ersetzt.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from tutoring import ausgabepruefung, levels, pruefung, views
from tutoring.models import Hint, LearningSession, Participation, Question, Task
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

AUFGABE = "Lena hat 7 Murmeln. Sie bekommt von Omar noch 5 Murmeln dazu. Wie viele Murmeln hat Lena jetzt?"


@pytest.fixture
def stunde(db):
    lehrperson = get_user_model().objects.create_user(username="l", password="x")
    return LearningSession.objects.create(
        title="Mathe", teacher=lehrperson, max_level=levels.LOESUNG,
    )


@pytest.fixture
def kind(client, stunde):
    teilnahme = Participation.objects.create(
        learning_session=stunde, animal="igel", token="t-igel",
    )
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


@pytest.fixture
def strom(monkeypatch):
    """Ein Spark, der je Aufruf den naechsten Text aus der Liste liefert.

    Haelt fest, mit welchem Systemprompt, welcher Anfrage und welcher
    Temperatur gefragt wurde.
    """
    class Gesehen(list):
        texte = None

    gesehen = Gesehen()
    gesehen.texte = []

    async def hilfe_streamen(system, text, bilder=None, max_tokens=500, messung=None,
                             temperatur=0.3):
        gesehen.append({"system": system, "text": text, "temperatur": temperatur})
        if messung is not None:
            messung.update(tokens_ein=1, tokens_aus=1, dauer_ms=1)
        antwort = (gesehen.texte.pop(0) if gesehen.texte
                   else "Schau dir die Angabe noch einmal an. Was steht da?")
        for wort in antwort.split(" "):
            yield wort + " "
    monkeypatch.setattr(views, "hilfe_streamen", hilfe_streamen)
    return gesehen


def _ereignisse(antwort):
    """Liest den SSE-Strom einer (asynchronen) Streamingantwort aus."""
    inhalt = antwort.streaming_content
    if hasattr(inhalt, "__aiter__"):
        async def sammeln():
            return b"".join([stueck async for stueck in inhalt])
        strom = async_to_sync(sammeln)().decode()
    else:
        strom = b"".join(inhalt).decode()
    gefunden = []
    for block in strom.split("\n\n"):
        name, daten = "", ""
        for zeile in block.split("\n"):
            if zeile.startswith("event:"):
                name = zeile[6:].strip()
            if zeile.startswith("data:"):
                daten += zeile[5:].strip()
        if name:
            gefunden.append((name, json.loads(daten) if daten else {}))
    return gefunden


def _hilfe(client, aufgabe, **felder):
    return client.post(reverse("tutoring:hilfe", args=[aufgabe.pk]), felder, secure=True)


# --- Die Seite --------------------------------------------------------------

def test_die_seite_hat_ein_feld_und_zwei_knoepfe(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Lena spielt mit Murmeln.")

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert seite.count('<textarea id="text"') == 1
    assert levels.KNOPF_VERSUCH in seite
    assert levels.KNOPF_FRAGE in seite
    assert 'name="absicht" value="versuch"' in seite
    assert 'name="absicht" value="frage"' in seite
    assert levels.HILFEKNOPF in seite
    assert "Tipp 1 · Worum geht es?" in seite, "die Stufe steht auf der Karte"
    assert "fortschritt-punkt" in seite
    for name in levels.KINDERNAMEN.values():
        assert name in seite
    assert "Zeig mir die Lösung" not in seite, "der Knopf heisst immer gleich"
    assert "Leertaste" not in seite
    for zeichen in seite:
        assert not (ord(zeichen) >= 0x1F000 or 0x2600 <= ord(zeichen) <= 0x27BF), "kein Emoji"


def test_vor_der_ersten_hilfe_kann_man_anfangen_fragen_und_einen_tipp_holen(client, kind):
    """Seit 30.10.2026 (Hilfe nach Diagnose) darf das Kind vor jeder Hilfe
    anfangen: Versuch, Frage und Tipp stehen nebeneinander, und die erste
    Hilfe richtet sich nach dem Anfang. "Noch etwas dazu?" gibt es nicht
    mehr. Kommt als Erstes eine Nachfrage (naechste_stufe 0), sagt nichts
    "Stufe 0"."""
    Task.objects.create(participation=kind, text=AUFGABE)

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert 'data-modus="antwort"' in seite
    assert "Dein Anfang" in seite
    assert 'data-modus="ergaenzen"' not in seite and "Dazusagen" not in seite
    assert levels.KNOPF_VERSUCH in seite
    assert levels.KNOPF_FRAGE in seite
    assert levels.HILFEKNOPF in seite
    assert 'id="tippzeile" >' in seite or 'id="tippzeile">' in seite, "der Tippknopf steht da"
    assert "Stufe 0" not in seite


def test_vor_der_nachfrage_sagt_die_seite_nicht_stufe_null(client, kind, stunde):
    """In der Mittelstufe ist der erste Zug eine Nachfrage: naechste_stufe
    ist 0, kein Punkt des Weges ist aktuell, und der Tippknopf steht."""
    stunde.schulstufe = levels.MITTELSTUFE
    stunde.save(update_fields=["schulstufe"])
    Task.objects.create(participation=kind, text=AUFGABE)

    antwort = client.get(reverse("tutoring:chat"), secure=True)
    seite = antwort.content.decode()

    assert antwort.context["naechste_stufe"] == levels.ERST_FRAGEN
    assert antwort.context["zug_art"] == levels.ART_NACHFRAGE
    assert 'data-zug-art="nachfrage"' in seite
    assert "Stufe 0" not in seite
    assert 'aria-current="step"' not in seite
    assert levels.HILFEKNOPF in seite


# --- Die Karten der Zug-Arten (30.10.2026) ----------------------------------

def test_die_karten_der_zugarten(client, kind):
    """Nachfrage, Bestaetigung, Begruendung und Nachsatz haben eigene Karten:
    die Nachfrage ohne Stufennummer mit leiser Marke, die Bestaetigung als
    Karte "Das stimmt." an ihrer Stelle im Gespraech, die Begruendung als
    Karte des Kindes, der Nachsatz mit "Dazu noch"."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)
    zuege = [
        Hint.objects.create(task=aufgabe, level=0, text="Was hast du schon probiert?",
                            art=levels.ART_NACHFRAGE, response="ich weiß nicht",
                            next_level=1, lage=levels.LAGE_KEIN_ANSATZ),
        Hint.objects.create(task=aufgabe, level=1, text="Lena hat Murmeln und bekommt dazu.",
                            response="7 + 5 = 12", result=Hint.ERGEBNIS_RICHTIG, next_level=5),
    ]
    aufgabe.abschliessen()
    zuege += [
        Hint.objects.create(task=aufgabe, level=1, text="Das stimmt. Warum hast du plus gerechnet?",
                            art=levels.ART_BESTAETIGUNG, response="weil dazu mehr heißt"),
        Hint.objects.create(task=aufgabe, level=1, text="Genau, dazu heißt plus.",
                            art=levels.ART_NACHSATZ),
    ]
    # Getrennte Zeitstempel: Die Uhr unter Windows ist grob genug, dass vier
    # Zuege hintereinander dieselbe Mikrosekunde bekommen, und dann sortiert
    # _gespraech_karten die Antwort hinter den naechsten Zug.
    jetzt = timezone.now()
    for i, zug in enumerate(zuege):
        Hint.objects.filter(pk=zug.pk).update(
            created_at=jetzt + timedelta(seconds=i), responded_at=jetzt + timedelta(seconds=i),
        )

    antwort = client.get(reverse("tutoring:chat"), secure=True)
    seite = antwort.content.decode()

    assert [k["art"] for k in antwort.context["gespraech"]] == [
        "nachfrage", "versuch", "hilfe", "versuch", "bestaetigung", "begruendung", "nachsatz",
    ]
    assert 'class="karte-hilfe schritt karte-nachfrage"' in seite
    assert levels.ART_NAMEN[levels.ART_NACHFRAGE] in seite
    assert "Was hast du schon probiert?" in seite
    assert "Tipp 0" not in seite and "Stufe 0" not in seite
    assert seite.count('id="fertigkarte"') == 1, "die Bestaetigung IST die Karte Das stimmt."
    assert "Das stimmt. Warum hast du plus gerechnet?" in seite
    assert 'class="karte-kind schritt-versuch karte-begruendung"' in seite
    assert "Deine Antwort</p>" in seite
    assert "weil dazu mehr heißt" in seite
    assert 'class="karte-hilfe schritt karte-nachsatz"' in seite
    assert levels.ART_NAMEN[levels.ART_NACHSATZ] in seite
    assert "Genau, dazu heißt plus." in seite
    assert "Nächste Aufgabe" in seite
    # Nach dem Nachsatz kommt nichts mehr: der Verfasser nimmt die naechste Aufgabe.
    assert 'data-zug-art=""' in seite
    assert "Deine nächste Aufgabe" in seite
    assert "Deine Antwort, wenn du magst" not in seite


def test_nach_dem_richtigen_ergebnis_holt_die_seite_die_bestaetigung(client, kind):
    """Zwischen Ergebnis und Bestaetigung neu geladen: Die Karte "Das
    stimmt." steht mit dem Text des Kindes, der Arbeitsplatz sagt hilfe.js,
    dass die Bestaetigung aussteht, und die Adresse dafuer steht da, obwohl
    der Tippknopf nach dem Ende nicht mehr da ist."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2)
    Hint.objects.create(task=aufgabe, level=2, text="…", response="7 + 5 = 12 Murmeln",
                        next_level=5, result=Hint.ERGEBNIS_RICHTIG)
    aufgabe.abschliessen()

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert 'data-zug-art="bestaetigung"' in seite
    assert 'data-abgeschlossen="ja"' in seite
    assert reverse("tutoring:hilfe", args=[aufgabe.pk]) in seite
    assert 'id="hilfe-knopf"' not in seite
    assert 'id="fertigkarte" aria-busy="false"' in seite, "sichtbar"
    assert 'id="fertig-text">7 + 5 = 12 Murmeln</p>' in seite
    assert 'id="fertig-tutor"></div>' in seite, "der Text des Tutors laeuft erst noch ein"


def test_die_offene_warum_frage_hat_einen_freiwilligen_verfasser(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2)
    Hint.objects.create(task=aufgabe, level=2, text="…", response="12",
                        next_level=5, result=Hint.ERGEBNIS_RICHTIG)
    aufgabe.abschliessen()
    Hint.objects.create(task=aufgabe, level=2, text="Das stimmt. Warum plus?",
                        art=levels.ART_BESTAETIGUNG)

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert "Deine Antwort, wenn du magst" in seite
    assert ">Antworten</button>" in seite
    assert "hidden>" + levels.KNOPF_FRAGE + "</button>" in seite, "kein zweiter Knopf"
    assert 'id="hilfe-knopf"' not in seite, "kein Tippknopf mehr"
    assert "Nächste Aufgabe" in seite
    assert seite.count('id="fertigkarte"') == 1
    assert "Das stimmt. Warum plus?" in seite


def test_der_strom_der_bestaetigung_traegt_art_und_freiwillig(client, kind, strom):
    """Der Vertrag, auf den hilfe.js baut: start mit art, fertig mit wartet
    und freiwillig, kein Stufenwechsel."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2)
    Hint.objects.create(task=aufgabe, level=2, text="…", response="7 + 5 = 12",
                        next_level=5, result=Hint.ERGEBNIS_RICHTIG)
    aufgabe.abschliessen()
    strom.texte.append("Das stimmt. Warum hast du plus gerechnet?")

    ereignisse = dict(_ereignisse(_hilfe(client, aufgabe)))

    assert ereignisse["start"]["art"] == levels.ART_BESTAETIGUNG
    assert ereignisse["start"]["stufe"] == 0
    assert ereignisse["fertig"]["art"] == levels.ART_BESTAETIGUNG
    assert ereignisse["fertig"]["wartet"] is True
    assert ereignisse["fertig"]["freiwillig"] is True
    assert ereignisse["fertig"]["bezeichnung"] == levels.ART_NAMEN[levels.ART_BESTAETIGUNG]
    assert aufgabe.hints.last().art == levels.ART_BESTAETIGUNG

    # Danach: ein zweiter Aufruf liefert nichts mehr als "ende".
    strom.texte.append("sollte nicht gebraucht werden")
    Hint.objects.filter(art=levels.ART_BESTAETIGUNG).update(response="weil dazu")
    Hint.objects.create(task=aufgabe, level=2, text="Genau.", art=levels.ART_NACHSATZ)
    namen = [name for name, _ in _ereignisse(_hilfe(client, aufgabe))]
    assert namen == ["ende"]


def test_nach_ausgeschoepften_stufen_bleibt_der_versuch_moeglich(client, kind, stunde):
    """Unter "Nur Tipps" darf ein Kind nach Stufe 3 weiter probieren. Die
    Diagnose sagt dann "richtig" oder schickt zur Rueckmeldung."""
    stunde.max_level = levels.NUR_TIPPS
    stunde.save(update_fields=["max_level"])
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=3,
                                  repeats=levels.HOECHSTE_WIEDERHOLUNGEN)
    Hint.objects.create(task=aufgabe, level=3, text="Was ist gegeben?",
                        response="weiß nicht", next_level=3)

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert aufgabe.stufen_ausgeschoepft
    assert 'data-modus="antwort"' in seite
    assert "Probier weiter" in seite
    assert levels.KNOPF_VERSUCH in seite and levels.KNOPF_FRAGE in seite


def test_die_fertige_aufgabe_zeigt_das_stimmt(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2)
    Hint.objects.create(task=aufgabe, level=2, text="…", response="7 + 5 = 12 Murmeln",
                        next_level=5, result=Hint.ERGEBNIS_RICHTIG)
    aufgabe.abschliessen()

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert "Das stimmt." in seite
    assert 'id="fertigkarte" hidden' not in seite, "die Karte ist sichtbar"
    assert 'id="fertig-text">7 + 5 = 12 Murmeln</p>' in seite
    assert "Nächste Aufgabe" in seite
    assert "Deine nächste Aufgabe" in seite


def test_die_stufenerklaerung_kennt_die_zwei_knoepfe_und_die_diagnose(client, stunde):
    client.force_login(stunde.teacher)
    seite = client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "mathematik"}, secure=True
    ).content.decode()
    assert levels.KNOPF_VERSUCH in seite
    assert levels.KNOPF_FRAGE in seite
    assert "richtig, falsch oder offen" in seite
    assert "Schulstufe" in seite
    # Seit 30.10.2026: gewaehlt, nicht gezaehlt. Der alte Satz ist falsch geworden.
    assert "gewählt, nicht gezählt" in seite
    assert "keine Stufe übersprungen" not in seite
    assert "Warum-Frage" in seite and "erst nach" in seite
    assert "S. 318" in seite, "Zech: Stufung idealtypisch, nicht linear"


# --- Ergaenzen nur vor der ersten Hilfe ------------------------------------

def test_ergaenzen_geht_nur_solange_keine_hilfe_da_ist(client, kind, monkeypatch):
    monkeypatch.setattr(views.pruefung, "einstufen", lambda text: ("gruen", ""))
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)

    client.post(reverse("tutoring:aufgabe_ergaenzen"), {"text": "Es sind Glasmurmeln."}, secure=True)
    aufgabe.refresh_from_db()
    assert "Glasmurmeln" in aufgabe.text

    Hint.objects.create(task=aufgabe, level=1, text="…")
    client.post(reverse("tutoring:aufgabe_ergaenzen"), {"text": "Noch etwas."}, secure=True)
    aufgabe.refresh_from_db()
    assert "Noch etwas." not in aufgabe.text


# --- Versuchsmodus nach "Nein" ----------------------------------------------

def test_nach_nein_bleibt_der_versuch_moeglich(client, kind, monkeypatch):
    """Benchmark, Befund 2: Sechs von sechzig Dialogen endeten im Feld "Noch
    etwas dazu?", drei davon mit der fertigen Loesung im falschen Feld. Die
    letzte Hilfe ist beantwortet, Stufe 5 steht an, das Kind hat Nein
    gesagt, und der naechste Beitrag laeuft durch die Diagnose."""
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=4)
    Hint.objects.create(task=aufgabe, level=4, text="Wie viel ist 7 plus 5?",
                        response="13", next_level=5, result=Hint.ERGEBNIS_FALSCH,
                        error="verzählt")
    assert aufgabe.loesung_steht_an

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert 'data-modus="antwort"' in seite
    assert "Probier weiter" in seite

    monkeypatch.setattr(views.pruefung, "diagnose", lambda *a, **k: pruefung.Diagnose(
        levels.LOESUNG, "fertig", pruefung.RICHTIG, "", pruefung.GRUEN, ""))
    antwort = client.post(
        reverse("tutoring:antwort_geben"), {"antwort": "12 Murmeln"},
        HTTP_X_ANTWORT="json", secure=True,
    )

    assert antwort.json()["fertig"] is True
    hilfe = aufgabe.hints.get()
    assert hilfe.response == "13\n\n12 Murmeln", "angehaengt, nicht ueberschrieben"
    assert hilfe.result == Hint.ERGEBNIS_RICHTIG
    aufgabe.refresh_from_db()
    assert aufgabe.ist_abgeschlossen


def test_nach_der_loesung_gibt_es_keinen_versuch_mehr(client, kind, monkeypatch):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=5)
    Hint.objects.create(task=aufgabe, level=5, text="7 + 5 = 12.")
    monkeypatch.setattr(views.pruefung, "diagnose", lambda *a, **k: pytest.fail("keine Diagnose"))

    antwort = client.post(
        reverse("tutoring:antwort_geben"), {"antwort": "12"},
        HTTP_X_ANTWORT="json", secure=True,
    )
    assert antwort.status_code == 400


# --- Der Tippknopf, waehrend eine Hilfe wartet -----------------------------

def test_der_tippknopf_waehrend_eine_hilfe_wartet_ist_ein_beitrag(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="Lena spielt mit Murmeln.")
    strom.texte.append("Stell dir die Murmeln in zwei Haufen vor. Welcher ist grösser?")

    namen = [name for name, _ in _ereignisse(_hilfe(client, aufgabe))]

    assert namen[:2] == ["beitrag", "start"]
    assert "fehler" not in namen
    hilfe = aufgabe.hints.order_by("created_at").first()
    assert hilfe.response == views.TIPP_STATT_VERSUCH
    assert hilfe.next_level == 1 and hilfe.result == Hint.ERGEBNIS_OFFEN
    assert aufgabe.hints.count() == 2, "dieselbe Stufe noch einmal"
    assert aufgabe.hints.order_by("created_at").last().level == 1
    assert "Diese Stufe gab es schon einmal" in strom[0]["system"]


# --- Wiederholung: je Stufe, mit vorigem Text, anderer Zugang, waermer -----

def test_der_zaehler_beginnt_mit_jeder_stufe_von_vorn(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1,
                                  repeats=2)
    Hint.objects.create(task=aufgabe, level=1, text="…", response="12", next_level=2)

    namen = [name for name, _ in _ereignisse(_hilfe(client, aufgabe))]

    assert "fertig" in namen
    aufgabe.refresh_from_db()
    assert aufgabe.current_level == 2
    assert aufgabe.repeats == 0


def test_die_wiederholung_bekommt_den_vorigen_text_und_einen_zugang(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2)
    Hint.objects.create(task=aufgabe, level=2, text="Dein Ansatz passt noch nicht.",
                        response="weiß nicht", next_level=2)

    _ereignisse(_hilfe(client, aufgabe))

    assert "Dein Ansatz passt noch nicht." in strom[0]["system"]
    assert levels.ZUGAENGE[0] in strom[0]["system"]
    assert strom[0]["temperatur"] == views.TEMPERATUR_WIEDERHOLUNG
    aufgabe.refresh_from_db()
    assert aufgabe.repeats == 1


def test_die_zweite_wiederholung_nimmt_den_anderen_zugang(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=2, repeats=1)
    Hint.objects.create(task=aufgabe, level=2, text="…", response="weiß nicht", next_level=2)

    _ereignisse(_hilfe(client, aufgabe))

    assert levels.ZUGAENGE[1] in strom[0]["system"]


def test_eine_frische_stufe_laeuft_mit_der_normalen_temperatur(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)

    _ereignisse(_hilfe(client, aufgabe))

    assert strom[0]["temperatur"] == views.TEMPERATUR
    assert "Diese Stufe gab es schon einmal" not in strom[0]["system"]


def test_der_hilfeprompt_kennt_die_rueckfragen_und_den_umfang(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=1)
    Hint.objects.create(task=aufgabe, level=1, text="…", response="12", next_level=2)
    Question.objects.create(task=aufgabe, text="Was heißt dazu?", answer="Dazu heißt mehr.")

    _ereignisse(_hilfe(client, aufgabe))

    assert "Rückfrage des Kindes: Was heißt dazu?" in strom[0]["text"]
    assert "Lösung nur auf ausdrückliche Bitte" in strom[0]["system"]


# --- Stufe 5 wird geprueft, bevor das Kind sie sieht ----------------------

def test_stufe_fuenf_wird_gegen_die_gepruefte_loesung_geprueft(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=4,
                                  checked_solution="WEG: 7 + 5.\nERGEBNIS: 12 Murmeln")
    Hint.objects.create(task=aufgabe, level=4, text="…", response="13", next_level=5)
    strom.texte.extend(["7 + 5 = 13. Lena hat 13 Murmeln.", "7 + 5 = 12. Lena hat 12 Murmeln."])

    ereignisse = _ereignisse(_hilfe(client, aufgabe, loesung="ja"))

    text = "".join(d["text"] for name, d in ereignisse if name == "stueck")
    assert "12 Murmeln" in text and "13 Murmeln" not in text
    assert len(strom) == 2
    assert ausgabepruefung.SCHAERFUNG_LOESUNG_ABWEICHUNG.strip() in strom[1]["system"]


def test_eine_passende_loesung_kostet_keinen_zweiten_aufruf(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=4,
                                  checked_solution="WEG: 7 + 5.\nERGEBNIS: 12 Murmeln")
    Hint.objects.create(task=aufgabe, level=4, text="…", response="13", next_level=5)
    strom.texte.append("7 + 5 = 12. Lena hat 12 Murmeln.")

    _ereignisse(_hilfe(client, aufgabe, loesung="ja"))

    assert len(strom) == 1


def test_ohne_gepruefte_loesung_prueft_das_modell_durch_einsetzen(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE, current_level=4)
    Hint.objects.create(task=aufgabe, level=4, text="…", response="13", next_level=5)
    strom.texte.extend(["7 + 5 = 13. Lena hat 13 Murmeln.", "7 + 5 = 12. Lena hat 12 Murmeln."])

    ereignisse = _ereignisse(_hilfe(client, aufgabe, loesung="ja"))

    text = "".join(d["text"] for name, d in ereignisse if name == "stueck")
    assert "12 Murmeln" in text
    assert len(strom) == 2
    assert "Prüfe sie durch Einsetzen" in strom[1]["text"]
    assert "7 + 5 = 13" in strom[1]["text"], "die eigene Loesung geht mit"


def test_unter_stufe_fuenf_gibt_es_keinen_zusaetzlichen_aufruf(client, kind, strom):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE,
                                  checked_solution="WEG: 7 + 5.\nERGEBNIS: 12 Murmeln")
    strom.texte.append("Lena spielt mit Murmeln. Was macht Omar?")

    _ereignisse(_hilfe(client, aufgabe))

    assert len(strom) == 1


# --- Die Skripte ------------------------------------------------------------

def test_die_skripte_kennen_die_kennungen_der_seite():
    """foto.js und sprache.js greifen auf Kennungen zu, die der Verfasser
    tragen muss; hilfe.js auf die der Karten."""
    wurzel = Path(__file__).resolve().parents[2]
    vorlagen = wurzel / "tutoring" / "templates" / "tutoring"
    verfasser = (vorlagen / "_verfasser.html").read_text("utf-8")
    chat = (vorlagen / "chat.html").read_text("utf-8")
    chat += (vorlagen / "_fertigkarte.html").read_text("utf-8")
    for kennung in ("fotoknopf", "fotoeingabe", "bildfeld", "herkunftfeld", "fotostand",
                    "fotovorschau", "sprachknopf", "sprachstand", "absichtfeld", "senden",
                    "fragen"):
        assert f'id="{kennung}"' in verfasser, kennung
    for kennung in ("hilfe-knopf", "neue-hilfe", "neue-text", "neue-bezeichnung", "verlauf",
                    "loesungsabfrage", "loesung-ja", "loesung-nein", "fertigkarte",
                    "fertig-text", "fertig-tutor", "naechste-aufgabe", "stufenende",
                    "tippzeile", "arbeitsplatz"):
        assert f'id="{kennung}"' in chat, kennung
    assert "data-zug-art" in chat and "data-url-hilfe" in chat
    hilfe_js = (wurzel / "static" / "js" / "hilfe.js").read_text("utf-8")
    assert '"absicht"' not in hilfe_js or "absicht" in hilfe_js
    assert 'event: ' not in hilfe_js
    assert "Leertaste" not in hilfe_js


def test_hilfe_js_kennt_die_zugarten_und_das_ende():
    """hilfe.js muss die Arten des Servers und seine Ereignisse kennen: start
    mit art, fertig mit wartet und freiwillig, ende; die Antwort auf die
    Warum-Frage mit nachsatz; die Bestaetigung beim Laden (data-zug-art).
    Die Fortschrittspunkte aendern sich nur bei einer Stufe."""
    wurzel = Path(__file__).resolve().parents[2]
    hilfe_js = (wurzel / "static" / "js" / "hilfe.js").read_text("utf-8")
    chat_js = (wurzel / "static" / "js" / "chat.js").read_text("utf-8")
    for art in (levels.ART_NACHFRAGE, levels.ART_BESTAETIGUNG, levels.ART_NACHSATZ):
        assert f'"{art}"' in hilfe_js, art
    assert levels.ART_AUFTAKT not in hilfe_js, "der Auftakt ist nie eine Karte des Tutors"
    for ereignis in ("start", "stueck", "fertig", "ende", "ausgeschoepft",
                     "loesung_bestaetigen", "fehler", "beitrag"):
        assert f'name === "{ereignis}"' in hilfe_js, ereignis
    assert "nutzlast.wartet" in hilfe_js and "ergebnis.nachsatz" in hilfe_js
    assert "nutzlast.rueckfrage" not in hilfe_js, "die Frage steht auf der Karte, nicht im Verfasser"
    assert "Deine Antwort, wenn du magst" in hilfe_js and '"Antworten"' in hilfe_js
    assert "daten.zugArt" in hilfe_js
    assert "Stufe 0" not in hilfe_js
    # fortschrittSetzen: die Definition, der Zweig der Stufe (Stufe gegeben)
    # und das richtige Ergebnis (nichts mehr aktuell). Sonst nirgends.
    assert hilfe_js.count("fortschrittSetzen(") == 3
    # chat.js nimmt Knopf und zweiten Knopf aus dem Zusatz.
    assert "zusatz.knopf" in chat_js and '"zweiter"' in chat_js
