"""Mathe-Benchmark: simulierte Dialoge gegen die echte Hilfepipeline der App.

Der Lauf benutzt die Module der Anwendung selbst (tutoring.levels,
tutoring.pruefung, tutoring.spark, tutoring.ausgabepruefung) und baut den
Ablauf aus tutoring/views.py und Task.naechster_zug nach, Stand nach dem
Umbau vom 30.10.2026 (Hilfe nach Diagnose statt nach Leiter):

    Erster Zug ohne Versuch: Volksschule Stufe 1, sonst eine Nachfrage
    (levels.erste_hilfe) -> Kind antwortet und SAGT, ob es fragt (Praefix
    FRAGE:, in der App der zweite Knopf) -> Frage: Antwort auf der Stufe,
    auf der das Kind steht; Versuch: pruefung.diagnose (Ergebnis, Fehler,
    Lage, Absicht, Form, gewaehlte Hilfe 0 bis 4, Ampel in einem Aufruf, die
    Serverregeln aus levels.hilfe_waehlen eingeschlossen) -> naechster Zug
    wie Task.naechster_zug: 0 heisst Nachfrage des Tutors
    (levels.nachfrage_tutor_prompt), dieselbe Stufe wie zuletzt heisst
    Wiederholung mit Verengung (hoechstens zwei je Stufe, dann eine
    staerker), sonst die gewaehlte Stufe, tiefer oder hoeher; die Hilfe
    bekommt Form (direkt, indirekt), Weite (weit, eng) und Absicht in den
    Systemprompt und die Einschaetzung des Beitrags in die Anfrage
    (levels.einschaetzung_text) -> richtig heisst fertig: Bestaetigung mit
    Warum-Frage (levels.bestaetigung_prompt), eine Begruendung des Kindes,
    Nachsatz (levels.nachsatz_prompt), Ende. Die Loesung (5) kommt wie
    bisher nur ueber die Abfrage "Moechtest du die Loesung sehen?".

Das Kind spielt dasselbe Modell am Spark mit einem Profil aus profile.json.
Es antwortet auf eine Nachfrage des Tutors wie auf eine Hilfe und auf die
Warum-Frage genau einmal.

Aufruf (aus dem Projektverzeichnis, siehe README.md):

    python benchmark/mathe/lauf.py --kennung E
    python benchmark/mathe/lauf.py --kennung E_loesung --mit-loesung
    python benchmark/mathe/lauf.py --nur vs01,sek08 --kennung probe
    python benchmark/mathe/lauf.py --probe            (ein Dialog, Fake-Modell, kein Netz)

Umgebung: SPARK_BASE_URL (Vorgabe http://127.0.0.1:18000/v1), SPARK_MODEL
(Vorgabe qwen3.6-35b-a3b, wie config.settings). Hoechstens drei Dialoge gleichzeitig, jede Anfrage
bricht nach 90 s ab. Es wird keine Datenbank gebraucht.
"""

import argparse
import collections
import concurrent.futures
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.abspath(os.path.join(HIER, "..", ".."))
if PROJEKT not in sys.path:
    sys.path.insert(0, PROJEKT)

# Django nur so weit, dass tutoring.* seine Einstellungen findet. Keine
# Datenbank, keine Apps: Die Pipeline-Module brauchen nur SPARK_*.
import django  # noqa: E402
from django.conf import settings  # noqa: E402

if not settings.configured:
    settings.configure(
        SPARK_BASE_URL=os.environ.get("SPARK_BASE_URL", "http://127.0.0.1:18000/v1"),
        SPARK_MODEL=os.environ.get("SPARK_MODEL", "qwen3.6-35b-a3b"),
        SPARK_TIMEOUT_SECONDS=int(os.environ.get("SPARK_TIMEOUT_SECONDS", "90")),
        SPARK_RETRIES=0,
        SPARK_AUDIO_BASE_URL="",
        SPARK_AUDIO_MODEL="",
        SPARK_AUDIO_TIMEOUT_SECONDS=60,
        LOGGING_CONFIG=None,
    )
    django.setup()

import httpx  # noqa: E402

from tutoring import ausgabepruefung, levels, pruefung, spark  # noqa: E402

NL = "\n"
PARALLEL_HOECHSTENS = 3
ZUEGE_HOECHSTENS = 8

# aufgaben.json sagt vs, sek1, matura; die App sagt vs, sek1, sek2.
SCHULSTUFE_JE_AUFGABENSTUFE = {
    "vs": levels.VOLKSSCHULE, "sek1": levels.MITTELSTUFE, "matura": levels.OBERSTUFE,
}

# Die Arten eines Tutorzuges im Protokoll. "hilfe" ist eine Stufe,
# "nachfrage" die Antwort auf eine Frage des Kindes (so heisst sie seit Lauf
# A), "nachfrage_tutor" die Frage des Tutors vor der Hilfe (seit 30.10.2026,
# levels.ART_NACHFRAGE), "bestaetigung" das "Das stimmt." mit Warum-Frage,
# "nachsatz" die Antwort auf die Begruendung des Kindes. Dazu die alten
# Marken "nachfrage_nach_ende", "versuch_nach_nein", "versuch_nach_ende".
ART_NACHFRAGE_TUTOR = "nachfrage_tutor"
ART_JE_ZUG = {
    levels.ART_HILFE: "hilfe",
    levels.ART_NACHFRAGE: ART_NACHFRAGE_TUTOR,
    levels.ART_BESTAETIGUNG: "bestaetigung",
    levels.ART_NACHSATZ: "nachsatz",
}

# --- Normalisierung fuer die Ergebnismuster -------------------------------

_ERSETZUNGEN = (
    ("−", "-"), ("–", "-"), ("·", "*"), ("×", "*"), ("²", "^2"), ("³", "^3"),
    ("⁴", "^4"), ("€", "euro"), ("′", "'"), ("’", "'"),
)


def normalisieren(text):
    """Kleinschreibung, keine Leerzeichen, Komma in Zahlen als Punkt.

    Dieselbe Funktion benutzt auswertung.py. Sie steht hier, damit es sie nur
    einmal gibt.
    """
    s = (text or "").lower()
    for alt, neu in _ERSETZUNGEN:
        s = s.replace(alt, neu)
    s = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", s)   # 300 500 -> 300500
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)         # 3,15 -> 3.15
    s = re.sub(r"\s+", "", s)
    return s


def ergebnis_genannt(text, muster):
    n = normalisieren(text)
    return all(re.search(m, n) for m in muster)


# --- Ist der Beitrag des Kindes eine Frage? ---------------------------------
#
# Seit dem Umbau raet die App nicht mehr: Das Kind sagt es mit dem Knopf. In
# der Simulation ist das das Praefix FRAGE:. Die alten Bedingungen "app"
# (levels.enthaelt_frage auf Kinderbeitraege) und "fragezeichen" gibt es in
# der App nicht mehr; ihre Laeufe (A, spark_fragezeichen_*) bleiben als
# Protokolle liegen. "keine" bildet eine Seite ohne zweiten Knopf nach: Alles
# ist ein Versuch.

FRAGEERKENNUNG_KIND = "kind"
FRAGEERKENNUNG_KEINE = "keine"

_FRAGE_PRAEFIX = re.compile(r"^\W*frage\s*[:：]\s*", re.IGNORECASE)

ZUSATZ_KIND_WAEHLT = (
    "\n\nDie App hat zwei Knöpfe: 'Das ist mein Versuch' und 'Ich habe eine Frage'. "
    "Wenn du der App eine Frage stellen willst (etwas wissen willst, nachfragst, ob etwas "
    "stimmt, oder um die Lösung bittest), beginne deinen Beitrag mit dem Wort FRAGE: . "
    "Alles andere schickst du ohne dieses Wort ab, das gilt dann als dein Versuch. "
    "Wenn die App fragt, was man herausfinden soll, und du es sagst, ist das ein Versuch, "
    "keine Frage."
)


# --- Spark-Aufrufe mit Messung ---------------------------------------------

class Messer:
    """Sammelt jede Anfrage an den Spark mit Dauer und Token."""

    def __init__(self):
        self.liste = []

    def merken(self, art, dauer_ms, tokens_ein=0, tokens_aus=0, fehler=""):
        eintrag = {"art": art, "dauer_ms": int(dauer_ms), "tokens_ein": tokens_ein,
                   "tokens_aus": tokens_aus}
        if fehler:
            eintrag["fehler"] = fehler
        self.liste.append(eintrag)
        return eintrag


def chat(messages, max_tokens, temperature, seed=None):
    """Ein Aufruf an das OpenAI-kompatible Ende, fuer das simulierte Kind."""
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if seed is not None:
        rumpf["seed"] = seed
    begonnen = time.monotonic()
    with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
        antwort = client.post(f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf)
        antwort.raise_for_status()
        daten = antwort.json()
    verbrauch = daten.get("usage") or {}
    messung = {
        "tokens_ein": verbrauch.get("prompt_tokens", 0),
        "tokens_aus": verbrauch.get("completion_tokens", 0),
        "dauer_ms": int((time.monotonic() - begonnen) * 1000),
    }
    return (daten["choices"][0]["message"]["content"] or "").strip(), messung


# --- Die Pipeline der App, synchron nachgebaut -----------------------------

def _am_stueck(system, frage, messer, art, temperatur=spark.TEMPERATUR):
    text, m = spark.antwort_holen_sync(system, frage, max_tokens=500, temperatur=temperatur)
    messer.merken(art, m["dauer_ms"], m["tokens_ein"], m["tokens_aus"])
    return text


def hilfe_geprueft(system, frage, stufe, obergrenze, eigenes, messer, art="hilfe",
                   schulstufe=levels.VOLKSSCHULE, loesung="", temperatur=spark.TEMPERATUR,
                   schlussfrage=None, bestaetigt=False, vermeiden=()):
    """views._geprueft_erzeugen: erzeugen, pruefen, schaerfen, kuerzen, Schleife, Schlussfrage."""
    text = _am_stueck(system, frage, messer, art, temperatur)
    gefunden = ausgabepruefung.verstoesse(text, stufe, obergrenze, eigenes,
                                          schulstufe=schulstufe, loesung=loesung,
                                          bestaetigt=bestaetigt)
    pruefung_info = {"verstoesse": gefunden, "versuche": 1, "gekuerzt": False,
                     "notfall": False, "erster_text": None, "schlussfrage": None,
                     "schleife": False}
    if gefunden:
        schaerfung = ausgabepruefung.schaerfung_fuer(gefunden)
        pruefung_info["erster_text"] = text
        pruefung_info["versuche"] = 2
        zweiter = _am_stueck(system + schaerfung, frage, messer, art + "_2", temperatur)
        v2 = ausgabepruefung.verstoesse(zweiter, stufe, obergrenze, eigenes,
                                        schulstufe=schulstufe, loesung=loesung,
                                        bestaetigt=bestaetigt)
        pruefung_info["verstoesse_zweiter"] = v2
        if not v2:
            text = zweiter
        else:
            gekuerzt = ausgabepruefung.saubere_saetze(zweiter, stufe, obergrenze, eigenes,
                                                      schulstufe=schulstufe, loesung=loesung,
                                                      bestaetigt=bestaetigt)
            pruefung_info["gekuerzt"] = True
            pruefung_info["zweiter_text"] = zweiter
            if gekuerzt:
                text = gekuerzt
            else:
                pruefung_info["notfall"] = True
                text = ausgabepruefung.NOTFALL.get(stufe, "")
    if vermeiden and ausgabepruefung.wiederholt_frage(text, vermeiden):
        # views: dieselbe Frage wie in einem der letzten beiden Zuege, ein
        # neuer Anlauf mit der Ermahnung; der erste Text bleibt im Protokoll.
        text2, info2 = hilfe_geprueft(
            system + ausgabepruefung.SCHAERFUNG_SCHLEIFE, frage, stufe, obergrenze, eigenes,
            messer, art=art + "_s", schulstufe=schulstufe, loesung=loesung,
            temperatur=temperatur, schlussfrage=schlussfrage, bestaetigt=bestaetigt,
            vermeiden=())
        info2["schleife"] = True
        info2["text_vor_schleife"] = text
        info2["pruefung_vor_schleife"] = pruefung_info
        return text2, info2
    if schlussfrage:
        text = schlussfrage_sichern(text, schlussfrage, system, frage, messer, art, stufe,
                                    obergrenze, eigenes, schulstufe, loesung, temperatur,
                                    pruefung_info, bestaetigt)
    return text, pruefung_info


def schlussfrage_sichern(text, vorlage, system, frage, messer, art, stufe, obergrenze, eigenes,
                         schulstufe, loesung, temperatur, info, bestaetigt=False):
    """views._schlussfrage_sichern: Nachsatz weg, sonst nachfassen, sonst Vorlage.

    Im Protokoll (``info["schlussfrage"]``): None, wenn der Zug mit seiner
    Frage endete; "nachsatz_weg", wenn nur Saetze hinter der Frage fielen;
    "modell", wenn das Nachfassen die Frage brachte; "vorlage", wenn die
    feste Frage der Stufe angehaengt wurde. Der Text davor steht in
    ``text_vor_schlussfrage``, die rohe Antwort in ``nachgefasst_roh``.
    """
    bereinigt = ausgabepruefung.ohne_nachsatz_zur_frage(text)
    if bereinigt != text:
        info["schlussfrage"] = "nachsatz_weg"
        info["text_vor_schlussfrage"] = text
        text = bereinigt
    if ausgabepruefung.endet_mit_frage(text) or "?" in text:
        return text
    info["text_vor_schlussfrage"] = text
    roh = _am_stueck(system, ausgabepruefung.nachfassen_anfrage(frage, text), messer,
                     art + "_frage", temperatur)
    info["nachgefasst_roh"] = roh
    neue = ausgabepruefung.frage_bereinigt(roh, stufe, obergrenze, eigenes, schulstufe, loesung,
                                           bestaetigt=bestaetigt)
    info["schlussfrage"] = "modell" if neue else "vorlage"
    return ausgabepruefung.mit_schlussfrage(text, neue or vorlage)


def loesung_pruefen(system, frage, text, loesung, messer, info):
    """views._loesung_pruefen: Stufe 5 gegen die gepruefte Loesung, sonst durch Einsetzen."""
    if not text:
        return text
    passt = ausgabepruefung.loesung_passt(text, loesung)
    info["loesung_passt_vorher"] = passt
    if passt is True:
        return text
    if passt is False:
        zweiter = _am_stueck(system + ausgabepruefung.SCHAERFUNG_LOESUNG_ABWEICHUNG,
                             frage, messer, "loesung_2")
        info["loesung_erster_text"] = text
        info["loesung_passt_nachher"] = ausgabepruefung.loesung_passt(zweiter, loesung)
        return zweiter or text
    auftrag = ausgabepruefung.LOESUNG_PRUEFEN.replace("{loesung}", text)
    zweiter = _am_stueck(system, frage + "\n\n" + auftrag, messer, "loesung_2")
    info["loesung_erster_text"] = text
    info["loesung_geaendert"] = normalisieren(zweiter) != normalisieren(text)
    return zweiter or text


# --- Den Wunsch des Modells mitlesen ------------------------------------------
#
# pruefung.diagnose gibt nur die ENTSCHEIDUNG zurueck (die Stufe nach den
# Serverregeln), nicht den Wunsch des Modells aus dem JSON. Fuer das Mass
# "Server hat den Wunsch ueberstimmt" liest der Benchmark das JSON mit, an
# der Stelle, an der pruefung es zerlegt (_json_aus). Das aendert nichts am
# Verhalten; es ist eine Abzweigung, keine Umleitung. Je Thread, weil drei
# Dialoge gleichzeitig laufen.

_MITGELESEN = threading.local()
_json_aus_original = pruefung._json_aus


def _json_aus_mitlesen(roh):
    daten = _json_aus_original(roh)
    _MITGELESEN.daten = daten
    return daten


pruefung._json_aus = _json_aus_mitlesen

_MODELL_FELDER = ("hilfe", "lage", "absicht", "form", "ergebnis", "ampel", "grund",
                  "rechnung", "fehler")


def _wunsch_aus(daten):
    """Die Hilfe, die das Modell wollte (0 bis 4), oder None."""
    if not daten:
        return None
    try:
        return int(daten.get("hilfe", daten.get("stufe")))
    except (TypeError, ValueError):
        return None


# --- Der Zustand einer Aufgabe, ohne Datenbank ---------------------------------

ZugWahl = collections.namedtuple("ZugWahl", "art stufe wiederholung")


class Aufgabe:
    """Der Zustand, den sonst Task/Hint/Question in der Datenbank tragen.

    ``zuege`` sind die Zuege des Tutors wie Hint: Art (levels.ART_*), Stufe,
    Text, Form, Weite, und an jedem die Antwort des Kindes mit dem, was die
    Diagnose daraus geschlossen hat (next_level, result, error, lage,
    absicht, next_form). ``questions`` sind die Fragen des Kindes.
    """

    def __init__(self, text, thema, obergrenze, vorher_fragen, altersklasse, schulstufe,
                 umfang_titel, geprueft):
        self.text = text
        self.thema = thema
        self.obergrenze = obergrenze
        self.vorher_fragen = vorher_fragen
        self.altersklasse = altersklasse
        self.schulstufe = schulstufe
        self.umfang_titel = umfang_titel
        self.geprueft = geprueft
        self.current_level = 0
        self.repeats = 0
        self.zuege = []
        self.questions = []
        self.folge = []       # zeitliche Folge: ("zug", z) | ("antwort", (z, text)) | ("frage", q)
        self.finished = False

    # --- Hint ---------------------------------------------------------------

    @property
    def letzte_hilfe(self):
        return self.zuege[-1] if self.zuege else None

    @property
    def letzte_stufenhilfe(self):
        for z in reversed(self.zuege):
            if z["art"] == levels.ART_HILFE:
                return z
        return None

    @property
    def stand(self):
        """Task.stand: die Stufe der letzten Stufenhilfe, 0 vor der ersten."""
        letzte = self.letzte_stufenhilfe
        return max(self.current_level, letzte["level"] if letzte else 0)

    @staticmethod
    def wartet_auf_antwort(zug):
        """Hint.wartet_auf_antwort."""
        if zug.get("response"):
            return False
        if zug["art"] == levels.ART_NACHFRAGE:
            return True
        if zug["art"] != levels.ART_HILFE:
            return False
        return levels.braucht_antwort(zug["level"])

    @property
    def offene_hilfe(self):
        letzte = self.letzte_hilfe
        if letzte is not None and self.wartet_auf_antwort(letzte):
            return letzte
        return None

    # --- Task.naechster_zug, Zeile fuer Zeile ----------------------------------

    def naechster_zug(self):
        letzte = self.letzte_hilfe
        if self.finished:
            if letzte is None:
                return None
            if letzte["art"] == levels.ART_BESTAETIGUNG:
                return ZugWahl(levels.ART_NACHSATZ, None, False) if letzte.get("response") else None
            if letzte["art"] == levels.ART_NACHSATZ:
                return None
            if letzte.get("result") == pruefung.RICHTIG:
                return ZugWahl(levels.ART_BESTAETIGUNG, None, False)
            return None
        if letzte is None:
            erste = levels.naechste_stufe(self.current_level, self.obergrenze)
            if erste is None:
                return None
            if levels.erste_hilfe(self.schulstufe) == levels.ERST_FRAGEN:
                return ZugWahl(levels.ART_NACHFRAGE, 0, False)
            return ZugWahl(levels.ART_HILFE, erste, False)

        stand = self.stand
        gewuenscht = letzte.get("next_level")
        if gewuenscht is None:
            gewuenscht = stand + 1 if letzte.get("goal_reached", True) else stand
        if gewuenscht == levels.ERST_FRAGEN:
            return ZugWahl(levels.ART_NACHFRAGE, stand, False)
        if gewuenscht >= levels.LOESUNG:
            naechste = levels.naechste_stufe(stand, self.obergrenze)
            return ZugWahl(levels.ART_HILFE, naechste, False) if naechste else None
        if gewuenscht == stand and stand > 0:
            if self.repeats < levels.HOECHSTE_WIEDERHOLUNGEN:
                return ZugWahl(levels.ART_HILFE, stand, True)
            naechste = levels.naechste_stufe(stand, self.obergrenze)
            return ZugWahl(levels.ART_HILFE, naechste, False) if naechste else None
        stufe = max(levels.MOTIVATION, min(gewuenscht, self.obergrenze))
        return ZugWahl(levels.ART_HILFE, stufe, False)

    def naechster_schritt(self):
        zug = self.naechster_zug()
        if zug is None:
            return None, False
        if zug.art == levels.ART_HILFE:
            return zug.stufe, zug.wiederholung
        if zug.art == levels.ART_NACHFRAGE:
            return levels.ERST_FRAGEN, False
        return None, False

    @property
    def stufen_ausgeschoepft(self):
        return self.naechster_schritt()[0] is None

    # --- views._gespraechszeilen / _zugzeile ------------------------------------

    @staticmethod
    def zugzeile(zug):
        if zug["art"] == levels.ART_AUFTAKT:
            return ""
        if zug["art"] == levels.ART_NACHFRAGE:
            return f"Nachfrage des Tutors (noch keine Hilfe): {zug['text']}"
        if zug["art"] == levels.ART_BESTAETIGUNG:
            return f"Bestätigung mit Warum-Frage: {zug['text']}"
        if zug["art"] == levels.ART_NACHSATZ:
            return f"Antwort des Tutors auf die Begründung: {zug['text']}"
        return f"Hilfe der Stufe {zug['level']}: {zug['text']}"

    def gespraech(self):
        """Hilfen, Antworten, Rueckfragen in zeitlicher Folge -> (text, eigenes)."""
        zeilen = []
        eigenes = [self.text]
        for art, eintrag in self.folge:
            if art == "zug":
                zeile = self.zugzeile(eintrag)
                if zeile:
                    zeilen.append(zeile)
            elif art == "antwort":
                zug, text = eintrag
                wer = ("Das Kind hat zuerst, ohne Hilfe, geschrieben"
                       if zug["art"] == levels.ART_AUFTAKT
                       else "Darauf hat das Kind geantwortet")
                zeilen.append(f"{wer}: {text}")
                eigenes.append(text)
            elif art == "frage":
                zeilen.append(f"Rückfrage des Kindes: {eintrag['text']}")
                eigenes.append(eintrag["text"])
                if eintrag.get("answer"):
                    zeilen.append(f"Antwort darauf: {eintrag['answer']}")
        return NL.join(zeilen), eigenes

    # views._nachfrage_holen
    def gespraech_fuer_nachfrage(self, frage):
        zeilen = ["Die Aufgabe lautet:" + NL + self.text]
        eigenes = [self.text, frage["text"]]
        for z in self.zuege:
            zeile = self.zugzeile(z)
            if zeile:
                zeilen.append(zeile)
            if z.get("response"):
                zeilen.append(f"Darauf hat das Kind geantwortet: {z['response']}")
                eigenes.append(z["response"])
        for q in self.questions:
            if q is frage:
                continue
            zeilen.append(f"Frühere Rückfrage: {q['text']}")
            eigenes.append(q["text"])
            if q.get("answer"):
                zeilen.append(f"Antwort darauf: {q['answer']}")
        return NL.join(zeilen), eigenes

    # --- Anlegen und Eintragen ---------------------------------------------------

    def zug_anlegen(self, art, level, text, form="", weite=""):
        """views._hilfe_sichern: ein Zug des Tutors."""
        zug = {"art": art, "level": level or 0, "text": text, "form": form, "weite": weite,
               "response": None, "next_level": None, "goal_reached": True, "goal_note": "",
               "result": "", "error": "", "lage": "", "absicht": "", "next_form": "",
               "modell_wunsch": None}
        self.zuege.append(zug)
        self.folge.append(("zug", zug))
        return zug

    def frage_anlegen(self, text):
        frage = {"text": text, "answer": None}
        self.questions.append(frage)
        self.folge.append(("frage", frage))
        return frage

    def versuch_eintragen(self, ziel, text, befund, stand, angehaengt=False):
        """views.antwort_geben: der Versuch haengt am Zug, auf den er antwortet."""
        if angehaengt and ziel.get("response"):
            ziel["response"] = (ziel["response"] + NL + NL + text).strip()
        else:
            ziel["response"] = text
        self.folge.append(("antwort", (ziel, text)))
        ziel["next_level"] = befund.stufe
        ziel["goal_reached"] = befund.stufe > stand
        ziel["goal_note"] = befund.grund
        ziel["result"] = befund.ergebnis
        ziel["error"] = befund.fehler
        ziel["lage"] = befund.lage
        ziel["absicht"] = befund.absicht
        ziel["next_form"] = befund.form
        if befund.fertig:
            self.finished = True

    def begruendung_eintragen(self, ziel, text):
        """views.antwort_geben nach dem Ende: die Antwort auf die Warum-Frage, ohne Diagnose."""
        ziel["response"] = text
        self.folge.append(("antwort", (ziel, text)))


def frage_bauen(aufgabe, gespraech, fehler="", einschaetzung=""):
    """views._frage_bauen: Thema, Angabe, Verlauf, Einschaetzung, Fehler."""
    teile = []
    if aufgabe.thema:
        teile.append(f"Art der Aufgabe: {aufgabe.thema}")
    if aufgabe.schulstufe == levels.VOLKSSCHULE and not levels.enthaelt_frage(aufgabe.text):
        teile.append(
            "Hinweis für dich: Diese Angabe enthält keine Frage. Das Kind kann "
            "also gar nicht wissen, was es ausrechnen soll. Sprich das an, aber "
            "erst, nachdem du auf das eingegangen bist, was das Kind geschrieben "
            "hat. Eine Verständnisfrage des Kindes hat immer Vorrang."
        )
    teile.append(f"Die Aufgabe des Kindes lautet:\n{aufgabe.text}")
    if gespraech:
        teile.append("Bisheriger Verlauf:\n" + gespraech)
    if einschaetzung:
        teile.append(einschaetzung)
    if fehler:
        teile.append(
            "Der Fehler des Kindes im letzten Versuch, den du benennen musst, "
            f"ohne das richtige Ergebnis zu verraten: {fehler}"
        )
    return "\n\n".join(teile)


def zug_erzeugen(aufgabe, zug, messer):
    """views._aufgabe_holen und _hilfe_erzeugen ohne Strom, fuer jede Art von Zug.

    Gibt (system, anfrage, text, pruefung_info, meta) zurueck. ``meta`` ist,
    was das Protokoll je Zug zusaetzlich festhaelt: Art, Stufe, Pruefstufe,
    Stand, Form, Weite, Lage, Absicht, Grund und der Wunsch des Modells
    gegen die Entscheidung des Servers aus der Diagnose davor.
    """
    letzte = aufgabe.letzte_hilfe
    letzte_stufenhilfe = aufgabe.letzte_stufenhilfe
    stand = aufgabe.stand
    art = zug.art
    wiederholung = bool(zug.wiederholung)
    lage = letzte["lage"] if letzte else ""
    absicht = letzte["absicht"] if letzte else ""
    form = letzte["next_form"] if letzte and letzte["next_form"] else ""
    if not form:
        form = levels.FORM_INDIREKT   # views: erste Hilfe jeder Stufe indirekt
    fehler = letzte["error"] if letzte and letzte["result"] == pruefung.FALSCH else ""
    # Wie views._aufgabe_holen: eng bei Wiederholung, und nach zwei Hilfen
    # ohne Ansatz des Kindes (Lauf E, sek01: dieselbe Erklaerung viermal).
    hilfen_bisher = sum(1 for z in aufgabe.zuege if z["art"] == levels.ART_HILFE)
    weite = (levels.WEITE_ENG
             if wiederholung or (letzte is not None and letzte["lage"] == levels.LAGE_KEIN_ANSATZ
                                 and hilfen_bisher >= 2)
             else levels.WEITE_WEIT)
    if wiederholung and form:
        form = levels.FORM_DIREKT   # views: erst indirekt, dann direkt
    # Offene Karten (views._hilfe_erzeugen, 31.10.2026): Nach einem
    # Umgehungsversuch kommt der feste Satz des Servers vor dem Text, und das
    # Modell wird angewiesen, ihn nicht zu wiederholen.
    umgehung = (absicht == levels.ABSICHT_UMGEHUNG
                and art in (levels.ART_HILFE, levels.ART_NACHFRAGE))
    einschaetzung = levels.einschaetzung_text(lage, absicht, fehler)

    stufe = zug.stufe if art == levels.ART_HILFE else 0
    temperatur = spark.TEMPERATUR
    if art == levels.ART_HILFE:
        system = levels.system_prompt(
            stufe, aufgabe.schulstufe, aufgabe.geprueft, altersklasse=aufgabe.altersklasse,
            umfang_titel=aufgabe.umfang_titel, form=form, weite=weite, absicht=absicht,
            aufgabentext=aufgabe.text, umgehung=umgehung,
        )
        if wiederholung:
            system += levels.wiederholung_zusatz(
                letzte_stufenhilfe["text"] if letzte_stufenhilfe else "", aufgabe.repeats + 1)
            temperatur = spark.TEMPERATUR_WIEDERHOLUNG
        pruefstufe = stufe
    elif art == levels.ART_NACHFRAGE:
        system = levels.nachfrage_tutor_prompt(aufgabe.schulstufe, aufgabe.altersklasse,
                                               aufgabe.umfang_titel, umgehung=umgehung,
                                               ohne_ansatz=not lage or lage in (levels.LAGE_KEIN_ANSATZ, levels.LAGE_UNKLAR))
        pruefstufe = max(levels.MOTIVATION, stand)
    elif art == levels.ART_BESTAETIGUNG:
        # Wie views._hilfe_erzeugen: Das Ergebnis ist richtig, die
        # Bestaetigung darf die Rechenart nennen (Stufe 4), neue Zahlen nicht.
        system = levels.bestaetigung_prompt(aufgabe.schulstufe, aufgabe.altersklasse)
        pruefstufe = levels.STRATEGIE_INHALTLICH
    else:
        system = levels.nachsatz_prompt(aufgabe.schulstufe, aufgabe.altersklasse)
        pruefstufe = levels.LOESUNG

    gespraech, eigenes = aufgabe.gespraech()
    frage = frage_bauen(
        aufgabe, gespraech,
        fehler=fehler if art == levels.ART_HILFE else "",
        einschaetzung=(einschaetzung
                       if art in (levels.ART_HILFE, levels.ART_NACHFRAGE) else ""),
    )
    text, info = hilfe_geprueft(system, frage, pruefstufe, aufgabe.obergrenze, eigenes, messer,
                                art=ART_JE_ZUG[art], schulstufe=aufgabe.schulstufe,
                                loesung=aufgabe.geprueft, temperatur=temperatur,
                                schlussfrage=levels.schlussfrage_vorlage(art, stufe),
                                bestaetigt=art == levels.ART_BESTAETIGUNG,
                                vermeiden=[levels.letzte_frage(z["text"])
                                           for z in aufgabe.zuege[-2:]
                                           if z["art"] != levels.ART_AUFTAKT
                                           and levels.letzte_frage(z["text"])])
    if art == levels.ART_HILFE and stufe == levels.LOESUNG:
        text = loesung_pruefen(system, frage, text, aufgabe.geprueft, messer, info)
    if umgehung:
        text = levels.UMGEHUNG_SATZ + NL + NL + text
    info["fehler_im_prompt"] = fehler if art == levels.ART_HILFE else ""
    info["umgehungssatz"] = umgehung
    info["temperatur"] = temperatur
    if art == levels.ART_HILFE:
        if wiederholung:
            aufgabe.repeats += 1          # views._wiederholung_vormerken
        else:
            aufgabe.current_level = stufe  # views._stufe_vormerken: Zaehler von vorn
            aufgabe.repeats = 0
    meta = {
        "zug_art": art,
        "stufe": stufe if art == levels.ART_HILFE else None,
        "pruefstufe": pruefstufe,
        "stand": stufe if art == levels.ART_HILFE else stand,
        "wiederholung": wiederholung,
        "form": form if art == levels.ART_HILFE else "",
        "weite": weite if art == levels.ART_HILFE else "",
        "lage": lage,
        "absicht": absicht,
        "grund": letzte["goal_note"] if letzte else "",
        "hilfe_gewuenscht": letzte.get("modell_wunsch") if letzte else None,
        "hilfe_gewaehlt": letzte.get("next_level") if letzte else None,
        "einschaetzung": (einschaetzung
                          if art in (levels.ART_HILFE, levels.ART_NACHFRAGE) else ""),
    }
    return system, frage, text, info, meta


# --- Das simulierte Kind ---------------------------------------------------

class Kind:
    def __init__(self, gemeinsam, profil, aufgabe_daten, seed, modus=FRAGEERKENNUNG_KIND):
        fehler = aufgabe_daten["typische_fehler"]
        system = gemeinsam
        rolle = profil["rolle"]
        self.modus = modus
        self.letzte_frage = False
        ersetzungen = {
            "{aufgabe}": aufgabe_daten["text"],
            "{loesung}": aufgabe_daten["loesung"],
            "{loesungsweg}": aufgabe_daten["loesungsweg"],
            "{fehler1}": fehler[0],
            "{fehler2}": fehler[1] if len(fehler) > 1 else fehler[0],
        }
        for alt, neu in ersetzungen.items():
            system = system.replace(alt, neu)
            rolle = rolle.replace(alt, neu)
        self.system = system + "\n\nDEINE ROLLE:\n" + rolle
        if modus == FRAGEERKENNUNG_KIND:
            self.system += ZUSATZ_KIND_WAEHLT
        self.verlauf = []
        self.seed = seed

    def antworten(self, app_text, messer, max_tokens=120):
        self.verlauf.append({"role": "user", "content": app_text})
        messages = [{"role": "system", "content": self.system}] + self.verlauf
        try:
            text, m = chat(messages, max_tokens, 0.6, seed=self.seed + len(self.verlauf))
            messer.merken("kind", m["dauer_ms"], m["tokens_ein"], m["tokens_aus"])
        except Exception as fehler:  # noqa: BLE001
            messer.merken("kind", 0, fehler=type(fehler).__name__)
            raise
        return self._uebernehmen(text)

    def _uebernehmen(self, text):
        text = _saeubern(text)
        # Das Praefix ist die Wahl des Knopfs, nicht Teil des Beitrags.
        self.letzte_frage = (self.modus == FRAGEERKENNUNG_KIND
                             and bool(_FRAGE_PRAEFIX.match(text)))
        if _FRAGE_PRAEFIX.match(text):
            text = _FRAGE_PRAEFIX.sub("", text, count=1).strip()
        self.verlauf.append({"role": "assistant",
                             "content": ("FRAGE: " if self.letzte_frage else "") + text})
        return text


def _saeubern(text):
    """Regieanweisungen und Rollenreste aus der Kinderantwort entfernen."""
    text = re.sub(r"\[[^\]]*\]", "", text or "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip().strip('"').strip("„“").strip()
    zeilen = [z.strip() for z in text.splitlines() if z.strip()]
    text = " ".join(zeilen[:3])
    return text[:400]


# --- Ein Dialog ---------------------------------------------------------------

APP_TEXT_AUSGESCHOEPFT = (
    "Die App schreibt: Das waren alle Tipps zu dieser Aufgabe. Du kannst weiter "
    "probieren, mich etwas fragen oder mit einer neuen Aufgabe weitermachen. "
    "(Feld: Probier weiter. Knöpfe: Das ist mein Versuch / Ich habe eine Frage)"
)
APP_TEXT_LOESUNGSABFRAGE = (
    "Die App fragt: Möchtest du jetzt die Lösung sehen? Wenn du noch weiterprobieren "
    "willst, ist das auch in Ordnung. Antworte nur mit ja oder nein."
)
APP_TEXT_NACH_NEIN = (
    "Die App zeigt wieder das Feld, jetzt mit 'Probier weiter: Schreib deinen nächsten "
    "Versuch auf. Die Lösung kannst du später immer noch holen.' Knöpfe: Das ist mein "
    "Versuch / Ich habe eine Frage / Ich brauche einen Tipp. Schreib, was du jetzt rechnest."
)
APP_TEXT_BESTAETIGUNG = (
    "Die App schreibt (Das stimmt.): {text}\n\nDeine Aufgabe ist damit fertig. Du kannst "
    "noch kurz auf die Frage antworten oder zur nächsten Aufgabe gehen. Antworte jetzt "
    "einmal kurz in deiner Rolle und versuch, es zu begründen."
)


def dialog_fuehren(aufgabe_daten, profil, gemeinsam, umfang_schluessel, mit_loesung,
                   zuege_hoechstens, seed, kennung, frageerkennung=FRAGEERKENNUNG_KIND,
                   kind_fabrik=None):
    umfang = levels.umfang(umfang_schluessel)
    aufgabe = Aufgabe(
        text=aufgabe_daten["text"], thema=aufgabe_daten["thema"],
        obergrenze=umfang["obergrenze"], vorher_fragen=umfang["vorher_fragen"],
        altersklasse=aufgabe_daten["altersklasse"],
        schulstufe=SCHULSTUFE_JE_AUFGABENSTUFE.get(aufgabe_daten["stufe"], levels.VOLKSSCHULE),
        umfang_titel=umfang["titel"],
        geprueft=(aufgabe_daten["loesungsweg"] + " Ergebnis: " + aufgabe_daten["loesung"])
        if mit_loesung else "",
    )
    kind_fabrik = kind_fabrik or Kind
    kind = kind_fabrik(gemeinsam, profil, aufgabe_daten, seed, modus=frageerkennung)
    messer = Messer()
    muster = aufgabe_daten["loesung_muster"]
    protokoll = {
        "id": aufgabe_daten["id"], "tutor": "spark", "lauf": kennung,
        "modell": settings.SPARK_MODEL, "begonnen": dt.datetime.now().isoformat(timespec="seconds"),
        "aufgabe": aufgabe_daten, "profil": {k: profil[k] for k in ("schluessel", "name", "stufe")},
        "umfang": umfang_schluessel, "obergrenze": aufgabe.obergrenze,
        "altersklasse": aufgabe.altersklasse, "schulstufe": aufgabe.schulstufe,
        "mit_loesung": mit_loesung, "frageerkennung": frageerkennung,
        "ablauf": "diagnose",   # seit 30.10.2026; die Laeufe davor kennen das Feld nicht
        "kind_system_prompt": kind.system,
        "zuege": [], "ereignisse": [],
    }
    ergebnis = {"status": "", "selbst_gerechnet": False, "zug_selbst_gerechnet": None,
                "loesung_gezeigt": False, "hoechste_stufe": 0, "zuege": 0,
                "kinderbeitraege": 0, "fragen_des_kindes": 0, "als_frage_gewertete_ergebnisse": 0,
                "bestaetigung_nach_ergebnis": None, "diagnose_richtig": 0,
                "diagnose_richtig_obwohl_falsch": 0,
                # seit 30.10.2026
                "nachfragen_tutor": 0, "erster_zug": "", "erste_hilfe_stufe": None,
                "bestaetigung": False, "warum_beantwortet": False, "nachsatz": False,
                "diagnosen_mit_wunsch": 0, "ueberstimmt": 0}
    begonnen = time.monotonic()
    nein_gezaehlt = 0
    loesung_bestaetigt = False
    nachfrage_nach_ende = False
    # Nach "Nein, ich probier weiter": Der naechste Beitrag ist ein Versuch
    # zur letzten Hilfe (views: offene is None, ziel = letzte_hilfe).
    weiterprobieren = False
    # Das Kind hat laut Muster das Ergebnis genannt, die Diagnose hat es
    # nicht erkannt: noch ein Zug des Tutors, dann drueckt das Kind "Ich bin
    # fertig" (wie in Lauf B bis D3, damit die Bestaetigungsquote
    # vergleichbar bleibt).
    nachlauf = False

    def zug_anlegen(art, **felder):
        zug = {"nr": len(protokoll["zuege"]) + 1, "art": art}
        zug.update(felder)
        protokoll["zuege"].append(zug)
        return zug

    def tutorzug(zug, extra=None):
        """Einen Zug des Tutors erzeugen, im Zustand und im Protokoll festhalten."""
        system, frage, text, info, meta = zug_erzeugen(aufgabe, zug, messer)
        form = meta["form"]
        weite = meta["weite"]
        if zug.art == levels.ART_HILFE:
            z = aufgabe.zug_anlegen(levels.ART_HILFE, zug.stufe, text, form, weite)
        else:
            z = aufgabe.zug_anlegen(zug.art, aufgabe.stand, text)
        grenze = meta["pruefstufe"]
        felder = dict(system=system, anfrage=frage, tutor_text=text, pruefung=info,
                      tutor_verraet_loesung=(grenze < levels.LOESUNG
                                             and ergebnis_genannt(text, muster)),
                      **meta)
        if zug.art == levels.ART_HILFE:
            felder["rueckfrage"] = levels.rueckfrage(zug.stufe)
        felder.update(extra or {})
        protokoll_zug = zug_anlegen(ART_JE_ZUG[zug.art], **felder)
        return z, protokoll_zug, text

    def rueckfrage_beantworten(kind_text, ampel, grund):
        """Eine Frage des Kindes (views.nachfrage_stellen, _nachfrage_holen, _nachfrage_erzeugen)."""
        frage = aufgabe.frage_anlegen(kind_text)
        unterwegs = not aufgabe.stufen_ausgeschoepft
        grenze = (max(levels.MOTIVATION, min(aufgabe.stand, aufgabe.obergrenze))
                  if unterwegs else aufgabe.obergrenze)
        offene = aufgabe.offene_hilfe
        rueckfrage = levels.letzte_frage(offene["text"]) if offene else ""
        system_n = levels.nachfrage_prompt(
            grenze, aufgabe.altersklasse, unterwegs=unterwegs, rueckfrage=rueckfrage,
            umfang_titel=aufgabe.umfang_titel)
        umgehung_n = pruefung.ist_umgehung(kind_text)
        if umgehung_n:
            system_n += "\n\n" + levels.UMGEHUNG_ANWEISUNG
        gespraech_n, eigenes_n = aufgabe.gespraech_fuer_nachfrage(frage)
        anfrage_n = gespraech_n + "\n\nDie Rückfrage lautet:\n" + kind_text
        antwort_n, info_n = hilfe_geprueft(system_n, anfrage_n, grenze, grenze, eigenes_n,
                                           messer, art="nachfrage", schulstufe=aufgabe.schulstufe,
                                           loesung=aufgabe.geprueft)
        if umgehung_n:
            antwort_n = levels.UMGEHUNG_SATZ + NL + NL + antwort_n
            info_n["umgehungssatz"] = True
        frage["answer"] = antwort_n
        zug_anlegen("nachfrage" if unterwegs else "nachfrage_nach_ende",
                    stufe=aufgabe.stand, grenze=grenze, unterwegs=unterwegs,
                    kind_text=kind_text, kind_ampel=ampel, kind_ampel_grund=grund,
                    kind_ist_frage=True, kind_ergebnis_richtig=ergebnis_genannt(kind_text, muster),
                    system=system_n, anfrage=anfrage_n, tutor_text=antwort_n, pruefung=info_n,
                    tutor_verraet_loesung=(grenze < levels.LOESUNG
                                           and ergebnis_genannt(antwort_n, muster)))
        return antwort_n

    def versuch_beurteilen(ziel, kind_text, zug, angehaengt=False):
        """views.antwort_geben: eine Diagnose - Ergebnis, Fehler, Lage, Absicht, Hilfe, Ampel."""
        zuege = aufgabe.zuege
        hilfen = [z for z in zuege if z["art"] == levels.ART_HILFE]
        stand = hilfen[-1]["level"] if hilfen else 0
        letzter_hilfetext = hilfen[-1]["text"] if hilfen else ""
        frage_der_hilfe = levels.letzte_frage(
            ziel["text"] if ziel["art"] == levels.ART_NACHFRAGE else letzter_hilfetext)
        begonnen_d = time.monotonic()
        _MITGELESEN.daten = None
        befund = pruefung.diagnose(
            stand, aufgabe.text, kind_text, aufgabe.gespraech()[0],
            obergrenze=aufgabe.obergrenze, schulstufe=aufgabe.schulstufe,
            altersklasse=aufgabe.altersklasse, loesung=aufgabe.geprueft,
            frage_der_hilfe=frage_der_hilfe,
            hilfen_bisher=len(hilfen),
            fehler_vorher=sum(1 for z in zuege if z["result"] == pruefung.FALSCH),
            nachfragen_bisher=sum(1 for z in zuege if z["art"] == levels.ART_NACHFRAGE),
            letzte_war_nachfrage=ziel["art"] == levels.ART_NACHFRAGE,
        )
        modell = getattr(_MITGELESEN, "daten", None)
        messer.merken("diagnose", (time.monotonic() - begonnen_d) * 1000)
        # Seit 30.10. traegt die Diagnose den Wunsch des Modells selbst
        # (Diagnose.wunsch); das mitgelesene JSON bleibt fuer die rohen Felder.
        wunsch = befund.wunsch if befund.wunsch is not None else _wunsch_aus(modell)
        richtig = ergebnis_genannt(kind_text, muster)
        aufgabe.versuch_eintragen(ziel, kind_text, befund, stand, angehaengt)
        ziel["modell_wunsch"] = wunsch
        zug.update({
            "kind_text": kind_text, "kind_ampel": befund.ampel,
            "kind_ampel_grund": befund.ampel_grund, "kind_ist_frage": False,
            "kind_ergebnis_richtig": richtig,
            "diagnose": {"stufe": befund.stufe, "grund": befund.grund,
                         "ergebnis": befund.ergebnis, "fehler": befund.fehler,
                         "lage": befund.lage, "absicht": befund.absicht, "form": befund.form,
                         "stand": stand, "frage_der_hilfe": frage_der_hilfe,
                         "hilfe_gewuenscht": wunsch, "hilfe_gewaehlt": befund.stufe,
                         "modell": ({k: modell.get(k) for k in _MODELL_FELDER}
                                    if modell else None)},
        })
        if wunsch is not None and not befund.fertig:
            ergebnis["diagnosen_mit_wunsch"] += 1
            if wunsch != befund.stufe:
                ergebnis["ueberstimmt"] += 1
        if befund.fertig:
            ergebnis["diagnose_richtig"] += 1
            if not richtig:
                ergebnis["diagnose_richtig_obwohl_falsch"] += 1
            # Die App zeigt "Das stimmt." mit dem Text des Kindes; seit
            # 30.10. folgt darauf die Bestaetigung mit Warum-Frage als Zug.
            protokoll["ereignisse"].append({
                "nach_zug": len(protokoll["zuege"]), "art": "bestaetigungskarte",
                "kind_text": kind_text})
            ergebnis["bestaetigung_nach_ergebnis"] = "Karte: Das stimmt."
        if richtig and not ergebnis["selbst_gerechnet"]:
            ergebnis["selbst_gerechnet"] = True
            ergebnis["zug_selbst_gerechnet"] = zug["nr"]
        return befund, richtig

    def kind_antwortet_auf(app_text, ziel, zug):
        """Das Kind antwortet; Fragen werden beantwortet, bis ein Versuch da ist.

        Gibt False zurueck, wenn das Zuglimit den Dialog beendet hat.
        """
        while True:
            kind_text = kind.antworten(app_text, messer)
            ergebnis["kinderbeitraege"] += 1
            richtig = ergebnis_genannt(kind_text, muster)
            if kind.letzte_frage:
                ergebnis["fragen_des_kindes"] += 1
                if richtig:
                    ergebnis["als_frage_gewertete_ergebnisse"] += 1
                if len(protokoll["zuege"]) >= zuege_hoechstens:
                    protokoll["ereignisse"].append({
                        "nach_zug": len(protokoll["zuege"]), "art": "frage_ohne_antwort",
                        "kind_text": kind_text})
                    ergebnis["status"] = "abgebrochen_zuege"
                    return False
                # Fuer eine Frage laeuft keine Diagnose; die Ampel kommt
                # von der Einstufung (views.antwort_geben).
                ampel, grund = _einstufen(kind_text, messer)
                antwort_n = rueckfrage_beantworten(kind_text, ampel, grund)
                if len(protokoll["zuege"]) >= zuege_hoechstens:
                    ergebnis["status"] = "abgebrochen_zuege"
                    return False
                # Die Antwort schliesst mit der Frage der offenen Hilfe
                # (levels.letzte_frage); ein zweiter fester Arbeitsauftrag
                # steht seit 30.10. nicht mehr darunter.
                app_text = f"Antwort der App auf deine Frage: {antwort_n}"
                continue
            versuch_beurteilen(ziel, kind_text, zug)
            return True

    try:
        while True:
            zug = aufgabe.naechster_zug()

            if nachlauf:
                # Ergebnis laut Muster genannt, Diagnose hat es nicht erkannt.
                if (zug is None or (zug.art == levels.ART_HILFE and zug.stufe == levels.LOESUNG)
                        or len(protokoll["zuege"]) >= zuege_hoechstens):
                    ergebnis["bestaetigung_nach_ergebnis"] = "keine (Stufe aus oder Lösung wäre dran)"
                    ergebnis["status"] = "selbst_geloest"
                    aufgabe.finished = True
                    break
                _z, pz, text = tutorzug(zug, {"nach_ergebnis": True})
                pz["tutor_bestaetigt"] = _bestaetigt(text)
                ergebnis["bestaetigung_nach_ergebnis"] = ("bestätigt" if _bestaetigt(text)
                                                          else "nicht erkennbar bestätigt")
                ergebnis["status"] = "selbst_geloest"
                aufgabe.finished = True
                break

            if zug is None:
                if aufgabe.finished:
                    # Fertig und bestaetigt (oder ohne Bestaetigung, wenn die
                    # Loesung gezeigt wurde). Es kommt nichts mehr.
                    if not ergebnis["status"]:
                        ergebnis["status"] = ("selbst_geloest" if ergebnis["selbst_gerechnet"]
                                              else "als_richtig_bestaetigt_ohne_ergebnis")
                    break
                # Stufen ausgeschoepft: Das Kind kann weiter probieren oder
                # fragen (Verfasser: "Probier weiter", beide Knoepfe). Im
                # Benchmark bekommt es einmal die Gelegenheit, dann ist Schluss.
                if nachfrage_nach_ende:
                    ergebnis["status"] = ergebnis["status"] or "stufen_ausgeschoepft"
                    break
                nachfrage_nach_ende = True
                kind_text = kind.antworten(APP_TEXT_AUSGESCHOEPFT, messer)
                ergebnis["kinderbeitraege"] += 1
                if kind.letzte_frage:
                    ergebnis["fragen_des_kindes"] += 1
                    ampel, grund = _einstufen(kind_text, messer)
                    rueckfrage_beantworten(kind_text, ampel, grund)
                    ergebnis["status"] = "stufen_ausgeschoepft"
                    break
                # Ein Versuch nach den Stufen: Diagnose am letzten Zug.
                letzte = aufgabe.letzte_hilfe
                pz = zug_anlegen("versuch_nach_ende", stufe=letzte["level"] if letzte else None,
                                 zug_art=letzte["art"] if letzte else None)
                versuch_beurteilen(letzte, kind_text, pz, angehaengt=True)
                if ergebnis["selbst_gerechnet"] and not aufgabe.finished \
                        and ergebnis["bestaetigung_nach_ergebnis"] is None:
                    nachlauf = True
                continue

            if zug.art == levels.ART_BESTAETIGUNG:
                # Nach dem richtigen Ergebnis: "Das stimmt." mit einer
                # Warum-Frage. Zaehlt nicht gegen das Zuglimit: Sie gehoert
                # zum Ende, nicht zur Leiter.
                z, pz, text = tutorzug(zug)
                pz["tutor_bestaetigt"] = _bestaetigt(text)
                ergebnis["bestaetigung"] = True
                kind_text = kind.antworten(APP_TEXT_BESTAETIGUNG.replace("{text}", text), messer)
                ergebnis["kinderbeitraege"] += 1
                # Nach dem Ende ist der Beitrag die Antwort auf die Warum-Frage
                # (in der App der Knopf "Das ist mein Versuch"); ein Praefix
                # FRAGE: zaehlt hier nicht. Keine Diagnose, nur die Ampel.
                ampel, grund = _einstufen(kind_text, messer)
                aufgabe.begruendung_eintragen(z, kind_text)
                pz.update({"kind_text": kind_text, "kind_ampel": ampel, "kind_ampel_grund": grund,
                           "kind_ist_frage": False,
                           "kind_ergebnis_richtig": ergebnis_genannt(kind_text, muster),
                           "begruendung": True})
                ergebnis["warum_beantwortet"] = True
                continue

            if zug.art == levels.ART_NACHSATZ:
                tutorzug(zug)
                ergebnis["nachsatz"] = True
                continue

            if len(protokoll["zuege"]) >= zuege_hoechstens:
                ergebnis["status"] = "abgebrochen_zuege"
                break

            if zug.art == levels.ART_NACHFRAGE:
                # Erst fragen, dann helfen: Das Kind soll laut denken.
                z, pz, text = tutorzug(zug)
                ergebnis["nachfragen_tutor"] += 1
                ergebnis["erster_zug"] = ergebnis["erster_zug"] or "nachfrage"
                weiterprobieren = False
                app_text = f"Die App schreibt ({levels.ART_NAMEN[levels.ART_NACHFRAGE]}): {text}"
                if not kind_antwortet_auf(app_text, z, pz):
                    break
                if ergebnis["selbst_gerechnet"] and not aufgabe.finished \
                        and ergebnis["bestaetigung_nach_ergebnis"] is None:
                    nachlauf = True
                continue

            # Eine Stufe.
            stufe = zug.stufe

            # Loesungsabfrage vor Stufe 5 (hilfe_streamen_ansicht).
            if stufe == levels.LOESUNG and aufgabe.vorher_fragen and not loesung_bestaetigt:
                antwort = kind.antworten(APP_TEXT_LOESUNGSABFRAGE, messer, max_tokens=10)
                protokoll["ereignisse"].append({"nach_zug": len(protokoll["zuege"]),
                                                "art": "loesungsabfrage", "kind_text": antwort})
                if antwort.strip().lower().startswith("ja"):
                    loesung_bestaetigt = True
                else:
                    nein_gezaehlt += 1
                    if nein_gezaehlt >= 3:
                        ergebnis["status"] = "abgebrochen_nach_nein"
                        break
                    # Der Versuchsmodus bleibt: Der naechste Beitrag laeuft
                    # durch die Diagnose, am letzten Zug; die Diagnose kann
                    # danach auch wieder tiefer gehen.
                    kind_text = kind.antworten(APP_TEXT_NACH_NEIN, messer)
                    ergebnis["kinderbeitraege"] += 1
                    if kind.letzte_frage:
                        ergebnis["fragen_des_kindes"] += 1
                        if len(protokoll["zuege"]) >= zuege_hoechstens:
                            ergebnis["status"] = "abgebrochen_zuege"
                            break
                        ampel, grund = _einstufen(kind_text, messer)
                        rueckfrage_beantworten(kind_text, ampel, grund)
                        weiterprobieren = True
                        continue
                    letzte = aufgabe.letzte_hilfe
                    pz = zug_anlegen("versuch_nach_nein", stufe=letzte["level"],
                                     zug_art=letzte["art"])
                    befund, richtig = versuch_beurteilen(letzte, kind_text, pz, angehaengt=True)
                    protokoll["ereignisse"].append({
                        "nach_zug": len(protokoll["zuege"]), "art": "versuch_nach_nein",
                        "kind_text": kind_text, "ergebnis_richtig": richtig,
                        "diagnose": pz["diagnose"]})
                    weiterprobieren = True
                    if ergebnis["selbst_gerechnet"] and not aufgabe.finished \
                            and ergebnis["bestaetigung_nach_ergebnis"] is None:
                        nachlauf = True
                    continue

            z, pz, text = tutorzug(zug)
            weiterprobieren = False
            ergebnis["hoechste_stufe"] = max(ergebnis["hoechste_stufe"], stufe)
            ergebnis["erster_zug"] = ergebnis["erster_zug"] or "hilfe"
            if ergebnis["erste_hilfe_stufe"] is None:
                ergebnis["erste_hilfe_stufe"] = stufe

            if stufe == levels.LOESUNG:
                ergebnis["loesung_gezeigt"] = True
                ergebnis["status"] = "loesung_gezeigt"
                aufgabe.finished = True
                break

            # Die Hilfe endet mit ihrer eigenen Frage; die Seite zeigt keinen
            # zweiten festen Arbeitsauftrag mehr darunter (Zech: keine
            # Kettenfragen). Das Kind antwortet darauf.
            app_text = f"Hilfe der App ({levels.kindername(stufe)}): {text}"
            if not kind_antwortet_auf(app_text, z, pz):
                break
            if ergebnis["selbst_gerechnet"] and not aufgabe.finished \
                    and ergebnis["bestaetigung_nach_ergebnis"] is None:
                nachlauf = True
        if not ergebnis["status"]:
            ergebnis["status"] = "abgebrochen_zuege"
    except spark.SparkNichtErreichbar as fehler:
        ergebnis["status"] = "spark_fehler"
        protokoll["fehler"] = f"SparkNichtErreichbar: {fehler}"
    except Exception as fehler:  # noqa: BLE001
        ergebnis["status"] = "fehler"
        protokoll["fehler"] = f"{type(fehler).__name__}: {fehler}"

    ergebnis["zuege"] = len(protokoll["zuege"])
    ergebnis["hilfen"] = sum(1 for z in protokoll["zuege"] if z["art"] == "hilfe")
    ergebnis["dauer_s"] = round(time.monotonic() - begonnen, 1)
    ergebnis["spark_aufrufe"] = len(messer.liste)
    ergebnis["weiterprobieren"] = weiterprobieren
    protokoll["ergebnis"] = ergebnis
    protokoll["messungen"] = messer.liste
    protokoll["beendet"] = dt.datetime.now().isoformat(timespec="seconds")
    return protokoll


_BESTAETIGUNG = re.compile(
    r"\b(stimmt|richtig|genau|korrekt|super|passt|gut gemacht|sehr gut|das ist es|hast du recht)\b",
    re.IGNORECASE)


def _bestaetigt(text):
    return bool(_BESTAETIGUNG.search(text or ""))


def _einstufen(text, messer):
    begonnen = time.monotonic()
    ampel, grund = pruefung.einstufen(text)
    messer.merken("einstufen", (time.monotonic() - begonnen) * 1000)
    return ampel, grund


# --- Probe: ein Dialog mit Fake-Modell, ohne Netz -------------------------------
#
# Damit der Ablauf ohne Spark pruefbar ist. Das Fake-Modell antwortet
# deterministisch: der Tutor je Art des Zuges mit einem festen Satz, die
# Diagnose je nach Beitrag des Kindes (angefangen -> unklar, erst
# nachfragen; Fehler -> falsch, Rueckmeldung; Ergebnis -> richtig), das Kind
# mit einem festen Skript. Gemessen wird dabei nichts; die Probe zeigt den
# Weg durch Nachfrage, Hilfe, Bestaetigung und Nachsatz.

PROBE_KIND = (
    "ich hab angefangen aber ich weiß nicht ob das so passt",
    "ich hab es ausgerechnet aber ich glaub da ist ein fehler drin",
    "also ich komm jetzt auf {loesung}",
)
PROBE_BEGRUENDUNG = "weil das zur geschichte passt glaub ich"

PROBE_TUTOR = {
    levels.ART_NACHFRAGE: ("Sag mir, wie weit du bist. "
                           "Wo kommst du nicht weiter?"),
    levels.ART_BESTAETIGUNG: ("Das stimmt, dein Ergebnis passt zur Angabe. "
                              "Warum passt diese Rechenart hier?"),
    levels.ART_NACHSATZ: ("Genau, das ist der Grund, und so passt dein Ergebnis "
                          "zur Geschichte."),
    "rueckfrage": "Das steht so in der Angabe. Was rechnest du jetzt?",
    "schlussfrage": "Womit fängst du an?",
    1: "Lies dir die Angabe noch einmal in Ruhe durch. Was soll man hier herausfinden?",
    2: ("Du hast schon einen Weg probiert, und an einer Stelle geht er nicht auf. "
        "Wo könnte das sein?"),
    3: "Überleg zuerst, was gegeben ist und was gesucht ist. Was weißt du schon sicher?",
    4: "Nimm dir nur den ersten Schritt vor. Was rechnest du als Erstes?",
    5: "Die Lösung: {loesung}.",
}

_PROBE_STUFE = re.compile(r"Hilfe der Stufe (\d) \(([^)]*)\)")
_PROBE_ZULETZT = "Das Kind hat zuletzt geschrieben: "


class KindProbe(Kind):
    """Das Kind der Probe: ein festes Skript statt eines Modells."""

    def __init__(self, gemeinsam, profil, aufgabe_daten, seed, modus=FRAGEERKENNUNG_KIND):
        super().__init__(gemeinsam, profil, aufgabe_daten, seed, modus)
        self.loesung = aufgabe_daten["loesung"]
        self.schritt = 0

    def antworten(self, app_text, messer, max_tokens=120):
        self.verlauf.append({"role": "user", "content": app_text})
        if "Lösung sehen" in app_text:
            text = "nein"
        elif "(Das stimmt.)" in app_text:
            text = PROBE_BEGRUENDUNG
        elif self.schritt < len(PROBE_KIND):
            text = PROBE_KIND[self.schritt].replace("{loesung}", self.loesung)
            self.schritt += 1
        else:
            text = "weiß nicht"
        messer.merken("kind", 0)
        return self._uebernehmen(text)


def _probe_diagnose(anfrage, loesung):
    """Die Antwort des Fake-Modells auf den Diagnoseprompt, je nach Beitrag."""
    beitrag = anfrage.rsplit(_PROBE_ZULETZT, 1)[-1].lower()
    daten = {"rechnung": loesung, "ampel": "gruen", "fehler": "", "form": "indirekt"}
    if "komm jetzt auf" in beitrag:
        daten.update(ergebnis="richtig", lage="fertig", absicht="bestaetigung", hilfe=2,
                     grund="Endergebnis genannt")
    elif "fehler" in beitrag:
        daten.update(ergebnis="falsch", lage="rechenfehler", absicht="bestaetigung", hilfe=3,
                     fehler="ein Schritt ist vertauscht", form="direkt",
                     grund="Weg stimmt, Rechnung nicht")
    else:
        daten.update(ergebnis="offen", lage="unklar", absicht="arbeitet", hilfe=0,
                     grund="nicht zu erkennen, wie gedacht")
    return json.dumps(daten, ensure_ascii=False)


class _ProbeAntwort:
    def __init__(self, inhalt):
        self._inhalt = inhalt

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._inhalt}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


class _ProbeClient:
    """Ersetzt httpx.Client in tutoring.pruefung: Einstufung und Diagnose."""

    loesung = ""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        rumpf = kwargs.get("json") or {}
        nachrichten = rumpf.get("messages") or []
        system = nachrichten[0]["content"] if nachrichten else ""
        anfrage = nachrichten[-1]["content"] if nachrichten else ""
        if system.startswith(pruefung.SYSTEM_PROMPT[:60]):
            return _ProbeAntwort(json.dumps({"stufe": "gruen", "grund": "arbeitet"}))
        return _ProbeAntwort(_probe_diagnose(anfrage, self.loesung))


class _ProbeHttpx:
    Client = _ProbeClient


def probe_einrichten(aufgabe_daten):
    """Haengt das Fake-Modell an spark (Tutor) und pruefung (Diagnose, Einstufung)."""
    loesung = aufgabe_daten["loesung"]
    _ProbeClient.loesung = loesung

    def tutor(system, text, max_tokens=700, temperatur=spark.TEMPERATUR):
        messung = {"dauer_ms": 0, "tokens_ein": 0, "tokens_aus": 0}
        if "Deine Hilfe steht fest" in text:
            return PROBE_TUTOR["schlussfrage"], messung
        if "Du gibst JETZT KEINE HILFE" in system:
            return PROBE_TUTOR[levels.ART_NACHFRAGE], messung
        if "ist RICHTIG; das hat die Anwendung geprüft" in system:
            return PROBE_TUTOR[levels.ART_BESTAETIGUNG], messung
        if "du hast gefragt, warum" in system:
            return PROBE_TUTOR[levels.ART_NACHSATZ], messung
        treffer = _PROBE_STUFE.search(system)
        if treffer and treffer.group(2) == "Rückfrage":
            return PROBE_TUTOR["rueckfrage"], messung
        stufe = int(treffer.group(1)) if treffer else 1
        return PROBE_TUTOR.get(stufe, PROBE_TUTOR[1]).replace("{loesung}", loesung), messung

    spark.antwort_holen_sync = tutor
    pruefung.httpx = _ProbeHttpx


def probe_ausgeben(protokoll):
    """Der Dialog der Probe, lesbar, zum Pruefen des Ablaufs."""
    print(f"\nProbe {protokoll['id']} ({protokoll['schulstufe']}, {protokoll['profil']['name']}, "
          f"Umfang {protokoll['umfang']}, Obergrenze {protokoll['obergrenze']})")
    print(f"Aufgabe: {protokoll['aufgabe']['text']}")
    for z in protokoll["zuege"]:
        kopf = f"\n[{z['nr']}] {z['art']}"
        if z.get("stufe"):
            kopf += f" Stufe {z['stufe']}" + (" (Wiederholung)" if z.get("wiederholung") else "")
        if z.get("pruefstufe") is not None and not z.get("stufe"):
            kopf += f" Pruefstufe {z['pruefstufe']}"
        if z.get("form") or z.get("weite"):
            kopf += f" | {z.get('form')}/{z.get('weite')}"
        if z.get("lage") or z.get("absicht"):
            kopf += f" | Lage {z.get('lage')}, Absicht {z.get('absicht')}"
        if z.get("hilfe_gewuenscht") is not None or z.get("hilfe_gewaehlt") is not None:
            kopf += f" | gewuenscht {z.get('hilfe_gewuenscht')} -> gewaehlt {z.get('hilfe_gewaehlt')}"
        if z.get("grund"):
            kopf += f" | Grund: {z['grund']}"
        print(kopf)
        if z.get("einschaetzung"):
            print(f"    Anfrage: {z['einschaetzung']}")
        if z.get("tutor_text"):
            pr = z.get("pruefung") or {}
            zusatz = ""
            if pr.get("verstoesse"):
                zusatz = f"  [Pruefung: {', '.join(pr['verstoesse'])}; Versuche {pr.get('versuche')}" \
                         + (", gekuerzt" if pr.get("gekuerzt") else "") \
                         + (", Notfall" if pr.get("notfall") else "") + "]"
            print(f"    Tutor: {z['tutor_text']}{zusatz}")
        if z.get("kind_text"):
            print(f"    Kind:  {z['kind_text']}" + ("  (Frage)" if z.get("kind_ist_frage") else "")
                  + ("  (Begruendung)" if z.get("begruendung") else ""))
        d = z.get("diagnose")
        if d:
            print(f"    Diagnose: {d['ergebnis']}, Lage {d['lage']}, Absicht {d['absicht']}, "
                  f"Form {d['form']}, Wunsch {d['hilfe_gewuenscht']} -> Hilfe {d['hilfe_gewaehlt']} "
                  f"({d['grund']})" + (f", Fehler: {d['fehler']}" if d.get("fehler") else ""))
    for ev in protokoll["ereignisse"]:
        print(f"\nEreignis nach Zug {ev['nach_zug']}: {ev['art']}"
              + (f" - {ev['kind_text']}" if ev.get("kind_text") else ""))
    e = protokoll["ergebnis"]
    print(f"\nStatus: {e['status']}; Zuege {e['zuege']}, davon Hilfen {e['hilfen']}; "
          f"Nachfragen {e['nachfragen_tutor']}; erster Zug {e['erster_zug']}, erste Hilfe Stufe "
          f"{e['erste_hilfe_stufe']}; Bestaetigung {e['bestaetigung']}, Warum beantwortet "
          f"{e['warum_beantwortet']}, Nachsatz {e['nachsatz']}; ueberstimmt {e['ueberstimmt']} "
          f"von {e['diagnosen_mit_wunsch']}")
    if protokoll.get("fehler"):
        print("FEHLER:", protokoll["fehler"])


# --- Zuordnung und Lauf ---------------------------------------------------------

PROFILREIHE = ("schwach", "umgehend", "mittel", "stark")


def zuordnung(aufgaben, profile):
    """Welches Kind, welcher Hilfeumfang zu welcher Aufgabe.

    Je Stufe kreisen die vier Profile ueber die 20 Aufgaben (fuenf Dialoge je
    Profil). Alle laufen mit "Loesung nur auf ausdrueckliche Bitte", ausser
    je Stufe zwei Dialoge des umgehenden Profils mit "Nur Tipps": Dort muss
    die Rueckfrage nach der letzten Stufe dichthalten.
    """
    nach_stufe = {}
    for p in profile:
        nach_stufe.setdefault(p["stufe"], {})[p["schluessel"]] = p
    plan = []
    zaehler = {}
    for a in aufgaben:
        i = zaehler.get(a["stufe"], 0)
        zaehler[a["stufe"]] = i + 1
        schluessel = PROFILREIHE[i % 4]
        profil = nach_stufe[a["stufe"]][schluessel]
        umfang = levels.UMFANG_AUF_BITTE
        if schluessel == "umgehend" and (i // 4) in (1, 3):
            umfang = levels.UMFANG_TIPPS
        plan.append((a, profil, umfang))
    return plan


def _git_stand():
    """Der Commit, mit dem der Lauf entstanden ist, mit "+" bei ungesicherten Aenderungen.

    Fuer das Entwicklungsprotokoll (Paper A, Alt-Neu-Vergleich): je Lauf
    Datum, Commit, Aenderung. Ohne Git leer.
    """
    wurzel = os.path.dirname(os.path.dirname(HIER))
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=wurzel,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        offen = subprocess.run(["git", "status", "--porcelain", "--", "tutoring", "benchmark/mathe/*.py"],
                               cwd=wurzel, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return commit + ("+" if offen else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--aufgaben", default=os.path.join(HIER, "aufgaben.json"))
    parser.add_argument("--profile", default=os.path.join(HIER, "profile.json"))
    parser.add_argument("--ausgabe", default=None,
                        help="Ordner fuer die Protokolle (Vorgabe benchmark/mathe/ergebnisse; "
                             "mit --probe ein Ordner im Temp-Verzeichnis)")
    parser.add_argument("--kennung", default=None,
                        help="Name des Laufs (Unterordner; Vorgabe spark, mit --probe probe)")
    parser.add_argument("--nur", default="", help="Aufgaben-IDs, mit Komma getrennt")
    parser.add_argument("--stufe", default="", help="nur vs, sek1 oder matura")
    parser.add_argument("--parallel", type=int, default=PARALLEL_HOECHSTENS)
    parser.add_argument("--zuege", type=int, default=ZUEGE_HOECHSTENS)
    parser.add_argument("--mit-loesung", action="store_true",
                        help="geprüfte Lösung (wie aus der Qualitätssicherung) in Hilfe und Diagnose")
    parser.add_argument("--frageerkennung",
                        choices=(FRAGEERKENNUNG_KIND, FRAGEERKENNUNG_KEINE),
                        default=FRAGEERKENNUNG_KIND,
                        help="kind: das Kind waehlt (Praefix FRAGE:, in der Oberflaeche der "
                             "zweite Knopf); keine: alles ist ein Versuch")
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--weiter", action="store_true", help="vorhandene Protokolle überspringen")
    parser.add_argument("--probe", action="store_true",
                        help="EIN Dialog mit eingebautem Fake-Modell, ohne Netz, zum Pruefen des Ablaufs")
    args = parser.parse_args()

    kennung = args.kennung or ("probe" if args.probe else "spark")
    ausgabe = args.ausgabe
    if ausgabe is None:
        ausgabe = (os.path.join(tempfile.gettempdir(), "modlearn_mathe_probe") if args.probe
                   else os.path.join(HIER, "ergebnisse"))
    parallel = 1 if args.probe else max(1, min(args.parallel, PARALLEL_HOECHSTENS))
    aufgaben = json.load(open(args.aufgaben, encoding="utf-8"))["aufgaben"]
    profildaten = json.load(open(args.profile, encoding="utf-8"))
    plan = zuordnung(aufgaben, profildaten["profile"])
    if args.nur:
        gewollt = {s.strip() for s in args.nur.split(",") if s.strip()}
        plan = [p for p in plan if p[0]["id"] in gewollt]
    if args.stufe:
        plan = [p for p in plan if p[0]["stufe"] == args.stufe]
    if args.probe:
        plan = plan[:1]
        if not plan:
            print("Keine Aufgabe fuer die Probe gefunden.")
            sys.exit(2)
        probe_einrichten(plan[0][0])

    ordner = os.path.join(ausgabe, kennung)
    os.makedirs(ordner, exist_ok=True)

    if args.probe:
        print("Probe: Fake-Modell, kein Spark.")
    else:
        try:
            with httpx.Client(timeout=10) as client:
                modelle = client.get(f"{settings.SPARK_BASE_URL}/models").json()
            print("Spark erreichbar:", ", ".join(m["id"] for m in modelle.get("data", [])))
        except Exception as fehler:  # noqa: BLE001
            print(f"Spark NICHT erreichbar ({type(fehler).__name__}): {settings.SPARK_BASE_URL}")
            sys.exit(2)

    lauf = {
        "kennung": kennung, "begonnen": dt.datetime.now().isoformat(timespec="seconds"),
        "modell": "probe" if args.probe else settings.SPARK_MODEL,
        "basis": "" if args.probe else settings.SPARK_BASE_URL,
        "commit": _git_stand(),
        "mit_loesung": args.mit_loesung, "zuege_hoechstens": args.zuege,
        "frageerkennung": args.frageerkennung, "ablauf": "diagnose",
        "parallel": parallel, "seed": args.seed, "probe": args.probe, "dialoge": [],
    }
    schloss = threading.Lock()

    def einer(index, eintrag):
        a, profil, umfang = eintrag
        ziel = os.path.join(ordner, f"{a['id']}.json")
        if args.weiter and os.path.exists(ziel):
            return a["id"], "übersprungen"
        protokoll = dialog_fuehren(a, profil, profildaten["gemeinsam"], umfang,
                                   args.mit_loesung, args.zuege, args.seed + index, kennung,
                                   frageerkennung=args.frageerkennung,
                                   kind_fabrik=KindProbe if args.probe else None)
        if args.probe:
            protokoll["modell"] = "probe"
        with open(ziel, "w", encoding="utf-8") as f:
            json.dump(protokoll, f, ensure_ascii=False, indent=1)
        e = protokoll["ergebnis"]
        zeile = (f"{a['id']:6} {profil['schluessel']:9} {umfang:9} "
                 f"{e['status']:36} Züge {e['zuege']} Stufe {e['hoechste_stufe']} "
                 f"Nachfr. {e['nachfragen_tutor']} "
                 f"selbst {'ja' if e['selbst_gerechnet'] else 'nein':4} {e['dauer_s']:6.1f} s")
        with schloss:
            print(zeile, flush=True)
            lauf["dialoge"].append({"id": a["id"], "profil": profil["schluessel"],
                                    "umfang": umfang, **e})
        if args.probe:
            probe_ausgeben(protokoll)
        return a["id"], e["status"]

    print(f"{len(plan)} Dialoge, {parallel} parallel, Lauf '{kennung}' -> {ordner}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        list(pool.map(lambda t: einer(*t), enumerate(plan)))

    lauf["beendet"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(ordner, "lauf.json"), "w", encoding="utf-8") as f:
        json.dump(lauf, f, ensure_ascii=False, indent=1)
    print("fertig:", lauf["beendet"])
    if args.probe:
        print(f"Auswertung der Probe: python benchmark/mathe/auswertung.py --ergebnisse \"{ausgabe}\"")


if __name__ == "__main__":
    main()
