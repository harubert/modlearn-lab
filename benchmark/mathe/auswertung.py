"""Auswertung der Benchmark-Protokolle unter benchmark/mathe/ergebnisse/.

Zwei Schichten:

1. Automatisch, aus den Protokollen allein (wiederholbar nach jeder
   Prompt-Aenderung): Status der Dialoge, selbst gerechnet, Zuege bis zum
   Ziel, Loesung verraten (Ergebnismuster in einer Hilfe unter Stufe 5),
   Verstoesse der Ausgangspruefung (erster Versuch, zweiter Versuch,
   gekuerzt, Notfalltext), Fragen je Hilfe, Satzlaenge, Diagnoserichtung,
   Ampel, Latenz je Aufrufart. Seit 30.10.2026 (Hilfe nach Diagnose statt
   nach Leiter) dazu: Nachfragen des Tutors, Spruenge um mehr als eine
   Stufe, Verteilung von Lage und Absicht, direkt/indirekt, weit/eng, Stufe
   der ersten Hilfe, Bestaetigung mit Warum-Frage und ihre Beantwortung,
   und wie oft der Server den Wunsch des Modells ueberstimmt hat.
2. Von Hand, aus bewertung/<lauf>.json (Rubrik je Tutorzug, 0 bis 2 Punkte je
   Kriterium, mit Begruendung). Fehlt die Datei, entfaellt die Schicht.

Aufruf:
    python benchmark/mathe/auswertung.py                 (alle Laeufe)
    python benchmark/mathe/auswertung.py --lauf spark1   (ein Lauf)

Schreibt ergebnisse/auswertung.md und ergebnisse/auswertung.json.
"""

import argparse
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.abspath(os.path.join(HIER, "..", ".."))
if PROJEKT not in sys.path:
    sys.path.insert(0, PROJEKT)
if HIER not in sys.path:
    sys.path.insert(0, HIER)

from lauf import ergebnis_genannt  # noqa: E402  (konfiguriert Django mit)
from tutoring import ausgabepruefung, levels  # noqa: E402


def ergebnis_in_beitraegen(beitraege, muster):
    """Steht jedes Muster in irgendeinem Beitrag des Kindes?

    Die Muster zweiteiliger Aufgaben verlangen beide Teile in EINEM Beitrag;
    wer "x = 3" und dann "y = 1" schreibt, hat gerechnet, zaehlt aber nicht
    als "selbst gerechnet" (D3: sechs von sieben "ohne Muster", F: fuenf von
    elf). Dieses Mass sieht alle Beitraege zusammen. Ziffernfolgen mit
    Leerzeichen ("8 9 10 11 12") werden vorher getrennt, damit "12" nicht in
    "89101112" verschwindet; Tausendergruppen ("300 500") bleiben zusammen,
    wie in lauf.normalisieren.
    """
    texte = []
    for t in beitraege:
        t = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", t or "")
        t = re.sub(r"(?<=\d)\s+(?=\d)", ";", t)
        texte.append(t)
    return bool(texte) and all(any(ergebnis_genannt(t, [m]) for t in texte) for m in muster)

# Die Rubrik: sechs Kriterien seit Lauf A, vier seit dem Umbau vom
# 30.10.2026 (Hilfe nach Diagnose). Die Skala steht in README.md und in
# bewertung/_vorlage.json. Aeltere Bewertungen kennen die vier neuen nicht;
# dort bleibt die Spalte leer.
KRITERIEN_ALT = ("fachlich", "stufe", "frage", "fehler", "diagnose", "umgehung")
KRITERIEN_NEU = ("passung", "minimal", "weite", "bezug")
KRITERIEN = KRITERIEN_ALT + KRITERIEN_NEU
KRITERIEN_NAMEN = {
    "fachlich": "fachlich richtig",
    "stufe": "Stufe eingehalten",
    "frage": "genau eine Frage, kurz, altersgerecht",
    "fehler": "Fehler des Kindes aufgegriffen",
    "diagnose": "Diagnose sinnvoll",
    "umgehung": "Umgehung abgefangen",
    "passung": "Hilfe passt zur Lage",
    "minimal": "kleinste wirksame Hilfe",
    "weite": "weit begonnen, erst dann verengt",
    "bezug": "Bezug auf die letzte Äußerung",
}
STUFEN_NAMEN = {"vs": "Volksschule", "sek1": "Sekundarstufe I", "matura": "Matura"}
SATZENDE = re.compile(r"(?<=[.!?])\s+")

# Tutorzuege, die genau eine Frage stellen sollen: eine Stufe, die Nachfrage
# des Tutors vor der Hilfe und die Bestaetigung mit Warum-Frage. Der
# Nachsatz fragt nichts, die Antwort auf eine Frage des Kindes hoechstens.
ARTEN_MIT_FRAGE = ("hilfe", "bestaetigung", "nachfrage_tutor")
LAGEN = tuple(levels.LAGEN)
ABSICHTEN = tuple(levels.ABSICHTEN)


# --- Laden ----------------------------------------------------------------

def protokolle_laden(ordner, lauf=None):
    dialoge = []
    for pfad in sorted(glob.glob(os.path.join(ordner, "*", "*.json"))):
        name = os.path.basename(pfad)
        kennung = os.path.basename(os.path.dirname(pfad))
        if name == "lauf.json" or kennung == "bewertung":
            continue
        if lauf and kennung != lauf:
            continue
        # Ordner mit Unterstrich sind Proben; sie zaehlen nur, wenn sie
        # ausdruecklich verlangt sind.
        if kennung.startswith("_") and lauf != kennung:
            continue
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
        if "id" not in d or "zuege" not in d:
            continue  # claude_zuege.json und Aehnliches
        # Der Ordner benennt den Lauf, nicht das Feld im Protokoll: Ein
        # abgebrochener Lauf wird umbenannt und soll dann auch so heissen.
        d["lauf"] = kennung
        d.setdefault("tutor", "spark")
        dialoge.append(d)
    return dialoge


def bewertungen_laden(ordner):
    """bewertung/<lauf>.json -> {(lauf, id): {...}}"""
    alle = {}
    for pfad in sorted(glob.glob(os.path.join(ordner, "bewertung", "*.json"))):
        name = os.path.basename(pfad)
        if name.startswith("_"):
            continue  # _vorlage.json: die Skala, keine Bewertung
        # spark_kind.vs.json, spark_kind.sek1.json ... gehoeren zu "spark_kind".
        lauf = name.split(".")[0]
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        for did, eintrag in daten.items():
            if did.startswith("_"):
                continue
            alle[(lauf, did)] = eintrag
    return alle


# --- Masse je Zug ----------------------------------------------------------------

def _grenze(z):
    """Die Stufe, an der ein Tutorzug zu messen ist.

    Eine Stufenhilfe an ihrer Stufe; Nachfrage und Bestaetigung (seit
    30.10.2026 ohne Stufe) an der Pruefstufe, mit der die Ausgangspruefung
    gelaufen ist (die Stufe, auf der das Kind steht). Ohne beides gilt die
    Loesung, also keine Grenze.
    """
    return z.get("stufe") or z.get("pruefstufe") or levels.LOESUNG


def zug_masse(d, z):
    """Automatische Masse fuer einen Tutorzug."""
    text = z.get("tutor_text") or ""
    pr = z.get("pruefung") or {}
    stufe = z.get("stufe")
    saetze = [s for s in SATZENDE.split(text.strip()) if s.strip()]
    altersklasse = d.get("altersklasse", "6-10")
    satzgrenze = 3 if altersklasse == "6-10" else 4
    diag = z.get("diagnose") or {}
    richtung = None
    # Die Richtung der Diagnose, gemessen an der Stufe, auf der das Kind
    # steht: bei einer Stufenhilfe ihre Stufe, bei einer Nachfrage der Stand.
    bezug = stufe if stufe else z.get("stand")
    if diag.get("stufe") is not None and bezug:
        richtung = ("höher" if diag["stufe"] > bezug else
                    "gleich" if diag["stufe"] == bezug else "tiefer")
    gewuenscht = diag.get("hilfe_gewuenscht")
    gewaehlt = diag.get("hilfe_gewaehlt", diag.get("stufe"))
    ueberstimmt = None
    if gewuenscht is not None and diag.get("ergebnis") != "richtig":
        ueberstimmt = gewuenscht != gewaehlt
    masse = {
        "fragen": text.count("?"),
        # Trichter-Indikator (Thomas, 31.10.2026; Zech, S. 285 und 288): laesst
        # die Schlussfrage nur eine Zahl, ein Wort oder Ja/Nein einsetzen?
        "einsetzfrage": ausgabepruefung.einsetzfrage(levels.letzte_frage(text)),
        "saetze": len(saetze),
        "woerter": len(text.split()),
        "zu_lang": len(saetze) > satzgrenze,
        "verstoss_erster": bool(pr.get("verstoesse")),
        "verstoesse_erster": pr.get("verstoesse") or [],
        "zweiter_versuch": pr.get("versuche", 1) == 2,
        "gekuerzt": bool(pr.get("gekuerzt")),
        "notfall": bool(pr.get("notfall")),
        # Seit Lauf G: None, "nachsatz_weg", "modell" oder "vorlage".
        "schlussfrage": pr.get("schlussfrage"),
        # Seit Lauf G: dieselbe Frage wie zuvor, zweiter Anlauf.
        "schleife": bool(pr.get("schleife")),
        "verraet_loesung": bool(z.get("tutor_verraet_loesung")),
        "diagnose_richtung": richtung,
        # Seit Lauf D: richtig, falsch, offen und der Fehler im Klartext.
        "diagnose_ergebnis": diag.get("ergebnis"),
        "diagnose_fehler": diag.get("fehler") or "",
        "kind_ampel": z.get("kind_ampel"),
        "kind_ist_frage": z.get("kind_ist_frage"),
        "kind_ergebnis_richtig": z.get("kind_ergebnis_richtig"),
        # Seit 30.10.2026 (Hilfe nach Diagnose): was diesen Zug geformt hat ...
        "zug_art": z.get("zug_art"),
        "pruefstufe": z.get("pruefstufe"),
        "stand": z.get("stand"),
        "form": z.get("form") or "",
        "weite": z.get("weite") or "",
        "lage": z.get("lage") or "",
        "absicht": z.get("absicht") or "",
        "grund": z.get("grund") or "",
        "hilfe_gewuenscht": z.get("hilfe_gewuenscht"),
        "hilfe_gewaehlt": z.get("hilfe_gewaehlt"),
        # ... und was die Diagnose des Beitrags darauf gesagt hat.
        "diag_lage": diag.get("lage") or "",
        "diag_absicht": diag.get("absicht") or "",
        "diag_form": diag.get("form") or "",
        "diag_gewuenscht": gewuenscht,
        "diag_gewaehlt": gewaehlt,
        "diag_grund": diag.get("grund") or "",
        "ueberstimmt": ueberstimmt,
        "nach_ergebnis": bool(z.get("nach_ergebnis")),
        "warum_beantwortet": bool(z.get("begruendung") and z.get("kind_text")),
    }
    # Rechenart auf Stufe 2/3 oder Rechenweg auf Stufe 1 im ENDTEXT (nach
    # Pruefung): das waere ein Durchrutscher der Ausgangspruefung.
    eigenes = [d["aufgabe"]["text"]] + [
        zz.get("kind_text") for zz in d["zuege"] if zz.get("kind_text")]
    # Seit Lauf D prueft die App je Schulstufe und mit der geprueften
    # Loesung; die Laeufe davor kennen das Feld nicht und werden wie bisher
    # (Volksschule) gemessen.
    loesung = ""
    if d.get("mit_loesung"):
        loesung = d["aufgabe"]["loesungsweg"] + " Ergebnis: " + d["aufgabe"]["loesung"]
    grenze = stufe or z.get("pruefstufe")
    masse["verstoss_endtext"] = ausgabepruefung.verstoesse(
        text, grenze, d.get("obergrenze", 5), eigenes,
        schulstufe=d.get("schulstufe", levels.VOLKSSCHULE), loesung=loesung,
    ) if grenze else []
    return masse


# --- Aggregation ----------------------------------------------------------------

def mittel(werte):
    werte = [w for w in werte if w is not None]
    return round(statistics.mean(werte), 2) if werte else None


def anteil(werte):
    werte = [w for w in werte if w is not None]
    return round(100 * sum(1 for w in werte if w) / len(werte), 1) if werte else None


def perzentil(werte, p):
    werte = sorted(w for w in werte if w is not None)
    if not werte:
        return None
    k = max(0, min(len(werte) - 1, int(round(p / 100 * (len(werte) - 1)))))
    return werte[k]


def _aufgaben_muster():
    pfad = os.path.join(HIER, "aufgaben.json")
    if not os.path.exists(pfad):
        return {}
    with open(pfad, encoding="utf-8") as f:
        return {a["id"]: a["loesung_muster"] for a in json.load(f)["aufgaben"]}


AUFGABEN_MUSTER = _aufgaben_muster()


def nachtraeglich(d, muster):
    """Selbst gerechnet, in welchem Zug, Bestaetigung danach, Loesung trotzdem gezeigt.

    Ein Kinderbeitrag zaehlt, wenn er vor der ersten Hilfe der Stufe 5 liegt
    und alle Ergebnismuster enthaelt. Ergaenzungen nach einem "Nein" bei der
    Loesungsabfrage zaehlen mit (Ereignis ergaenzung_statt_versuch).
    """
    zuege = d.get("zuege", [])
    ereignisse = d.get("ereignisse", [])
    erste_loesung = next((z["nr"] for z in zuege if z.get("art") == "hilfe"
                          and z.get("stufe") == levels.LOESUNG), None)
    zug_selbst = None
    for z in zuege:
        if erste_loesung and z["nr"] >= erste_loesung:
            break
        if z.get("begruendung"):
            continue  # die Antwort auf die Warum-Frage ist kein Versuch
        if z.get("kind_text") and not z.get("kind_ist_frage") \
                and ergebnis_genannt(z["kind_text"], muster):
            zug_selbst = z["nr"]
            break
    if zug_selbst is None:
        for ev in ereignisse:
            if ev.get("art") in ("ergaenzung_statt_versuch", "versuch_nach_nein") \
                    and ergebnis_genannt(ev.get("kind_text"), muster):
                if not erste_loesung or ev["nach_zug"] < erste_loesung:
                    zug_selbst = ev["nach_zug"]
                    break
    if zug_selbst is None:
        return False, None, None, False
    # Seit dem Umbau (Lauf D) bestaetigt die App ein richtiges Ergebnis selbst,
    # mit der Karte "Das stimmt.", ohne Tutorzug; seit 30.10.2026 folgt auf
    # die Karte die Bestaetigung mit Warum-Frage als Zug. Das Ereignis zaehlt
    # als Bestaetigung, wenn es direkt nach dem Zug mit dem Ergebnis kommt.
    karte = any(ev.get("art") == "bestaetigungskarte" and ev.get("nach_zug") == zug_selbst
                for ev in ereignisse)
    danach = [z for z in zuege if z["nr"] > zug_selbst and z.get("tutor_text")]
    if karte:
        bestaetigung = "bestätigt"
    elif not danach:
        bestaetigung = "keine Antwort mehr"
    elif _BESTAETIGUNG.search(danach[0]["tutor_text"]):
        bestaetigung = "bestätigt"
    else:
        bestaetigung = "nicht bestätigt"
    loesung_trotzdem = bool(erste_loesung) and erste_loesung > zug_selbst
    return True, zug_selbst, bestaetigung, loesung_trotzdem


_BESTAETIGUNG = re.compile(
    r"\b(stimmt|richtig|genau|korrekt|super|passt|gut gemacht|sehr gut|das ist es|hast du recht)\b",
    re.IGNORECASE)


def _diagnose_zaehlung(zuege):
    """Lage, Absicht und Ueberstimmung ueber ALLE Beitraege mit Diagnose eines Dialogs.

    Auch die Versuche nach "Nein" und nach den Stufen tragen eine Diagnose,
    ohne eigenen Tutortext; sie gehoeren in die Verteilung.
    """
    lagen = Counter()
    absichten = Counter()
    gruende = Counter()
    mit_wunsch = 0
    ueberstimmt = 0
    for z in zuege:
        diag = z.get("diagnose") or {}
        if not diag:
            continue
        if diag.get("lage"):
            lagen[diag["lage"]] += 1
        if diag.get("absicht"):
            absichten[diag["absicht"]] += 1
        gewuenscht = diag.get("hilfe_gewuenscht")
        if gewuenscht is None or diag.get("ergebnis") == "richtig":
            continue
        mit_wunsch += 1
        if gewuenscht != diag.get("hilfe_gewaehlt", diag.get("stufe")):
            ueberstimmt += 1
            gruende[diag.get("grund") or "(ohne Grund)"] += 1
    return dict(lagen), dict(absichten), dict(gruende), mit_wunsch, ueberstimmt


def auswerten(dialoge, bewertungen):
    zeilen_dialog = []
    zeilen_zug = []
    latenz = defaultdict(list)
    tokens = defaultdict(lambda: {"ein": [], "aus": []})

    for d in dialoge:
        e = d.get("ergebnis", {})
        bew = bewertungen.get((d["lauf"], d["id"]), {})
        stufe_s = d["aufgabe"]["stufe"]
        profil = d["profil"]["schluessel"]
        zuege = d.get("zuege", [])
        tutorzuege = [z for z in zuege if z.get("tutor_text")]
        # Nachtraeglich mit den aktuellen Mustern aus aufgaben.json, nicht mit
        # denen, die zur Laufzeit im Protokoll standen: Die Muster sind nach
        # Lauf A und B verbessert worden ("Also 65." zaehlte nicht, weil der
        # Satzpunkt wie ein Dezimalpunkt behandelt wurde). Die Zuege nach dem
        # ersten richtigen Ergebnis bleiben im Protokoll - so verhaelt sich
        # auch die App, die ein richtiges Ergebnis nicht erkennt.
        muster = AUFGABEN_MUSTER.get(d["id"], d["aufgabe"]["loesung_muster"])
        selbst, zug_selbst, bestaetigung, loesung_trotzdem = nachtraeglich(d, muster)
        if "selbst_gerechnet" in bew:
            selbst = bew["selbst_gerechnet"]
        in_beitraegen = ergebnis_in_beitraegen([z.get("kind_text") or "" for z in zuege], muster)
        # Seit 30.10.2026: die Folge der Stufen, die Nachfragen, die
        # Bestaetigung mit Warum-Frage.
        hilfen_z = [z for z in tutorzuege if z.get("art") == "hilfe" and z.get("stufe")]
        folge = [z["stufe"] for z in hilfen_z]
        schritte = [b - a for a, b in zip(folge, folge[1:])]
        erster = tutorzuege[0] if tutorzuege else None
        lagen, absichten, gruende, mit_wunsch, ueberstimmt = _diagnose_zaehlung(zuege)
        zeilen_dialog.append({
            "lauf": d["lauf"], "tutor": d["tutor"], "id": d["id"], "stufe": stufe_s,
            "profil": profil, "umfang": d.get("umfang"), "mit_loesung": d.get("mit_loesung", False),
            "ablauf_diagnose": d.get("ablauf") == "diagnose",
            "status": e.get("status"), "selbst_gerechnet": selbst,
            "ergebnis_in_beitraegen": in_beitraegen,
            "zug_selbst_gerechnet": zug_selbst,
            "loesung_gezeigt": e.get("loesung_gezeigt"),
            "loesung_gezeigt_trotz_ergebnis": loesung_trotzdem, "zuege": len(tutorzuege),
            "hilfen": len(hilfen_z),
            "hoechste_stufe": e.get("hoechste_stufe"), "fragen_des_kindes": e.get("fragen_des_kindes"),
            "als_frage_gewertete_ergebnisse": e.get("als_frage_gewertete_ergebnisse"),
            "bestaetigung": bestaetigung,
            "dauer_s": e.get("dauer_s"), "spark_aufrufe": e.get("spark_aufrufe"),
            "verraet_loesung": any(
                _grenze(z) < levels.LOESUNG
                and (zug_selbst is None or z["nr"] <= zug_selbst)
                and ergebnis_genannt(z.get("tutor_text", ""), muster)
                for z in tutorzuege),
            "orange_oder_rot": sum(1 for z in zuege if z.get("kind_ampel") in ("orange", "rot")),
            "kinderbeitraege": e.get("kinderbeitraege"),
            "bewertet": bool(bew.get("zuege")),
            "notiz": bew.get("notiz", ""),
            # Hilfe nach Diagnose (30.10.2026)
            "nachfragen_tutor": sum(1 for z in tutorzuege if z.get("art") == "nachfrage_tutor"),
            "erster_zug": (("nachfrage" if erster.get("art") == "nachfrage_tutor" else "hilfe")
                           if erster else None),
            "erste_hilfe_stufe": folge[0] if folge else None,
            "stufenfolge": folge,
            "spruenge_hoch": sum(1 for s in schritte if s >= 2),
            "spruenge_runter": sum(1 for s in schritte if s <= -2),
            "rueckschritte": sum(1 for s in schritte if s < 0),
            "mit_bestaetigung": any(z.get("art") == "bestaetigung" for z in tutorzuege),
            "warum_beantwortet": any(z.get("art") == "bestaetigung" and z.get("begruendung")
                                     and z.get("kind_text") for z in tutorzuege),
            "mit_nachsatz": any(z.get("art") == "nachsatz" for z in tutorzuege),
            "lagen": lagen, "absichten": absichten,
            "mit_wunsch_n": mit_wunsch, "ueberstimmt_n": ueberstimmt,
            "ueberstimmt_gruende": gruende,
        })
        for z in tutorzuege:
            m = zug_masse(d, z)
            # Loesung verraten: nachtraeglich mit den aktuellen Mustern, und
            # nur, solange das Kind das Ergebnis noch nicht selbst genannt
            # hat. Eine Bestaetigung ("65 stimmt") verraet nichts.
            m["verraet_loesung"] = bool(
                _grenze(z) < levels.LOESUNG
                and (zug_selbst is None or z["nr"] <= zug_selbst)
                and ergebnis_genannt(z.get("tutor_text", ""), muster)
            )
            punkte = (bew.get("zuege") or {}).get(str(z["nr"]), {})
            zeile = {
                "lauf": d["lauf"], "tutor": d["tutor"], "id": d["id"], "nr": z["nr"],
                "stufe": stufe_s, "profil": profil, "umfang": d.get("umfang"),
                "mit_loesung": d.get("mit_loesung", False),
                "art": z["art"], "zech": z.get("stufe"),
                "wiederholung": z.get("wiederholung", False), **m,
            }
            for k in KRITERIEN:
                zeile["p_" + k] = punkte.get(k)
            zeile["begruendung"] = punkte.get("begruendung", "")
            zeilen_zug.append(zeile)
        for mess in d.get("messungen", []):
            if mess.get("fehler"):
                continue
            art = mess["art"].replace("_2", "")
            latenz[(d["lauf"], art)].append(mess["dauer_ms"])
            tokens[(d["lauf"], art)]["ein"].append(mess.get("tokens_ein", 0))
            tokens[(d["lauf"], art)]["aus"].append(mess.get("tokens_aus", 0))

    return zeilen_dialog, zeilen_zug, latenz, tokens


def gruppen(zeilen, schluessel):
    g = defaultdict(list)
    for z in zeilen:
        g[tuple(z.get(k) for k in schluessel)].append(z)
    return dict(sorted(g.items(), key=lambda kv: [str(x) for x in kv[0]]))


def dialog_kennzahlen(zeilen):
    n = len(zeilen)
    selbst = [z for z in zeilen if z["selbst_gerechnet"]]
    return {
        "dialoge": n,
        "selbst_gerechnet_%": anteil([z["selbst_gerechnet"] for z in zeilen]),
        "ergebnis_in_beitraegen_%": anteil([z.get("ergebnis_in_beitraegen") for z in zeilen]),
        "zuege_bis_ziel": mittel([z["zug_selbst_gerechnet"] for z in selbst]),
        "bestaetigt_%": anteil([z["bestaetigung"] == "bestätigt" for z in selbst
                                if z["bestaetigung"] != "keine Antwort mehr"]),
        "loesung_trotz_ergebnis": sum(1 for z in zeilen if z.get("loesung_gezeigt_trotz_ergebnis")),
        "loesung_gezeigt_%": anteil([z["loesung_gezeigt"] for z in zeilen]),
        "zuege_mittel": mittel([z["zuege"] for z in zeilen]),
        "hilfen_mittel": mittel([z["hilfen"] for z in zeilen]),
        "verraet_loesung_%": anteil([z["verraet_loesung"] for z in zeilen]),
        "fragen_des_kindes": sum(z.get("fragen_des_kindes") or 0 for z in zeilen),
        "ergebnis_als_frage": sum(z.get("als_frage_gewertete_ergebnisse") or 0 for z in zeilen),
        "dauer_s_mittel": mittel([z["dauer_s"] for z in zeilen]),
    }


def einsetz_anteil(zeilen):
    """Anteil der Zuege mit Frage, deren Schlussfrage eine Einsetzfrage ist."""
    return anteil([bool(z.get("einsetzfrage")) for z in zeilen if z["fragen"]])


def zug_kennzahlen(zeilen):
    hilfen = [z for z in zeilen if z["art"] in ARTEN_MIT_FRAGE]
    mit_diag = [z for z in zeilen if z["diagnose_richtung"]]
    k = {
        "zuege": len(zeilen),
        "verstoss_erster_%": anteil([z["verstoss_erster"] for z in hilfen]),
        "zweiter_versuch_%": anteil([z["zweiter_versuch"] for z in hilfen]),
        "gekuerzt_%": anteil([z["gekuerzt"] for z in hilfen]),
        "notfall_%": anteil([z["notfall"] for z in hilfen]),
        "verraet_loesung_%": anteil([z["verraet_loesung"] for z in zeilen]),
        "genau_eine_frage_%": anteil([z["fragen"] == 1 for z in hilfen]),
        "keine_frage_%": anteil([z["fragen"] == 0 for z in hilfen]),
        "einsetzfrage_%": einsetz_anteil(hilfen),
        # Seit Lauf G (Schlussfrage erzwungen): wie oft der Server nachfassen
        # musste, und wie oft die Vorlage statt der Frage des Modells kam.
        "nachgefasst_%": anteil([z.get("schlussfrage") in ("modell", "vorlage") for z in hilfen]),
        "vorlage_%": anteil([z.get("schlussfrage") == "vorlage" for z in hilfen]),
        "schleife_%": anteil([z.get("schleife") for z in hilfen]),
        "zu_lang_%": anteil([z["zu_lang"] for z in zeilen]),
        "saetze_mittel": mittel([z["saetze"] for z in zeilen]),
        "woerter_mittel": mittel([z["woerter"] for z in zeilen]),
        "diag_hoeher_%": anteil([z["diagnose_richtung"] == "höher" for z in mit_diag]),
        "diag_gleich_%": anteil([z["diagnose_richtung"] == "gleich" for z in mit_diag]),
        "diag_tiefer_%": anteil([z["diagnose_richtung"] == "tiefer" for z in mit_diag]),
    }
    # Die Diagnose mit Ergebnis (Lauf D): wie oft richtig, falsch, offen, und
    # wie oft "richtig" gegen die Ergebnismuster bzw. "falsch" trotz Muster.
    mit_ergebnis = [z for z in zeilen if z.get("diagnose_ergebnis")]
    k["diagnosen"] = len(mit_ergebnis)
    for erg in ("richtig", "falsch", "offen"):
        k[f"diag_{erg}_n"] = sum(1 for z in mit_ergebnis if z["diagnose_ergebnis"] == erg)
    k["diag_richtig_obwohl_muster_nein"] = sum(
        1 for z in mit_ergebnis
        if z["diagnose_ergebnis"] == "richtig" and not z.get("kind_ergebnis_richtig"))
    k["diag_nicht_richtig_obwohl_muster_ja"] = sum(
        1 for z in mit_ergebnis
        if z["diagnose_ergebnis"] != "richtig" and z.get("kind_ergebnis_richtig"))
    k["diag_fehler_benannt_n"] = sum(
        1 for z in mit_ergebnis if z["diagnose_ergebnis"] == "falsch" and z["diagnose_fehler"])
    for krit in KRITERIEN:
        werte = [z["p_" + krit] for z in zeilen if z.get("p_" + krit) is not None]
        k["r_" + krit] = (round(statistics.mean(werte), 2), len(werte)) if werte else None
    return k


def diagnose_kennzahlen(dial, zug):
    """Die Masse zur Hilfe nach Diagnose (30.10.2026), je Gruppe von Dialogen.

    Fuer Laeufe vor dem Umbau ergeben sie die Leiter: keine Nachfrage,
    erste Hilfe immer Stufe 1, keine Spruenge, keine Form. So bleibt D3 der
    Vergleich.
    """
    hilfen = [z for z in zug if z["art"] == "hilfe"]
    mit_form = [z for z in hilfen if z.get("form")]
    mit_weite = [z for z in hilfen if z.get("weite")]
    erste = Counter(d["erste_hilfe_stufe"] for d in dial if d.get("erste_hilfe_stufe"))
    lagen = Counter()
    absichten = Counter()
    gruende = Counter()
    for d in dial:
        lagen.update(d.get("lagen") or {})
        absichten.update(d.get("absichten") or {})
        gruende.update(d.get("ueberstimmt_gruende") or {})
    mit_wunsch = sum(d.get("mit_wunsch_n") or 0 for d in dial)
    ueberstimmt = sum(d.get("ueberstimmt_n") or 0 for d in dial)
    return {
        "dialoge": len(dial),
        "hilfen_je_dialog": mittel([d["hilfen"] for d in dial]),
        "nachfragen_je_dialog": mittel([d["nachfragen_tutor"] for d in dial]),
        "mit_nachfrage_%": anteil([d["nachfragen_tutor"] > 0 for d in dial]),
        "erster_zug_nachfrage_%": anteil([d["erster_zug"] == "nachfrage"
                                          for d in dial if d.get("erster_zug")]),
        "erste_hilfe": {s: erste.get(s, 0) for s in range(1, 5)},
        "spruenge_hoch": sum(d["spruenge_hoch"] for d in dial),
        "spruenge_runter": sum(d["spruenge_runter"] for d in dial),
        "rueckschritte": sum(d["rueckschritte"] for d in dial),
        "direkt_%": anteil([z["form"] == levels.FORM_DIREKT for z in mit_form]),
        "eng_%": anteil([z["weite"] == levels.WEITE_ENG for z in mit_weite]),
        "mit_bestaetigung_%": anteil([d["mit_bestaetigung"] for d in dial]),
        "warum_beantwortet_%": anteil([d["warum_beantwortet"] for d in dial]),
        "mit_nachsatz_%": anteil([d["mit_nachsatz"] for d in dial]),
        "diagnosen_mit_wunsch": mit_wunsch,
        "ueberstimmt": ueberstimmt,
        "ueberstimmt_%": round(100 * ueberstimmt / mit_wunsch, 1) if mit_wunsch else None,
        "lagen": {lage: lagen.get(lage, 0) for lage in LAGEN},
        "absichten": {a: absichten.get(a, 0) for a in ABSICHTEN},
        "ueberstimmt_gruende": dict(gruende.most_common()),
    }


# --- Markdown ------------------------------------------------------------------

def tabelle(kopf, zeilen):
    aus = ["| " + " | ".join(kopf) + " |", "|" + "|".join("---" for _ in kopf) + "|"]
    for z in zeilen:
        aus.append("| " + " | ".join("–" if v is None else str(v) for v in z) + " |")
    return "\n".join(aus)


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, tuple):
        return f"{v[0]:.2f} (n={v[1]})".replace(".", ",")
    if isinstance(v, float):
        return f"{v:.1f}".replace(".", ",")
    return str(v)


def bericht(zeilen_dialog, zeilen_zug, latenz, tokens):
    teile = ["# Auswertung Mathe-Benchmark", ""]
    laeufe = sorted({z["lauf"] for z in zeilen_dialog})
    teile.append(f"Läufe: {', '.join(laeufe)}; Dialoge: {len(zeilen_dialog)}; "
                 f"Tutorzüge: {len(zeilen_zug)}; bewertete Dialoge: "
                 f"{sum(1 for z in zeilen_dialog if z['bewertet'])}")
    teile.append("")

    def block(titel, schluessel, dial, zug):
        teile.append(f"## {titel}")
        teile.append("")
        zeilen = []
        for k, zs in gruppen(dial, schluessel).items():
            dk = dialog_kennzahlen(zs)
            zeilen.append(list(k) + [dk["dialoge"], fmt(dk["selbst_gerechnet_%"]),
                                     fmt(dk["ergebnis_in_beitraegen_%"]),
                                     fmt(dk["zuege_bis_ziel"]), fmt(dk["bestaetigt_%"]),
                                     fmt(dk["loesung_gezeigt_%"]), dk["loesung_trotz_ergebnis"],
                                     fmt(dk["zuege_mittel"]), fmt(dk["hilfen_mittel"]),
                                     fmt(dk["verraet_loesung_%"]),
                                     dk["fragen_des_kindes"], dk["ergebnis_als_frage"]])
        teile.append(tabelle(list(schluessel) + ["Dialoge", "selbst gerechnet %",
                                                  "Ergebnis in allen Beiträgen %", "Züge bis Ziel",
                                                  "danach bestätigt %", "Lösung gezeigt %",
                                                  "Lösung gezeigt trotz Ergebnis", "Züge je Dialog",
                                                  "Stufenhilfen je Dialog",
                                                  "Lösung verraten %", "Fragen des Kindes",
                                                  "Ergebnis als Frage gewertet"], zeilen))
        teile.append("")
        zeilen = []
        for k, zs in gruppen(zug, schluessel).items():
            zk = zug_kennzahlen(zs)
            zeilen.append(list(k) + [zk["zuege"], fmt(zk["verstoss_erster_%"]),
                                     fmt(zk["gekuerzt_%"]), fmt(zk["notfall_%"]),
                                     fmt(zk["verraet_loesung_%"]), fmt(zk["genau_eine_frage_%"]),
                                     fmt(zk["keine_frage_%"]), fmt(zk["einsetzfrage_%"]),
                                     fmt(zk["zu_lang_%"]),
                                     fmt(zk["woerter_mittel"]), fmt(zk["diag_hoeher_%"]),
                                     fmt(zk["diag_gleich_%"]), fmt(zk["diag_tiefer_%"])])
        teile.append(tabelle(list(schluessel) + ["Züge", "Verstoß 1. Versuch %", "gekürzt %",
                                                  "Notfalltext %", "Lösung verraten %",
                                                  "genau eine Frage %", "keine Frage %",
                                                  "Einsetzfrage %",
                                                  "zu lang %", "Wörter", "Diagnose höher %",
                                                  "gleich %", "tiefer %"], zeilen))
        teile.append("")
        bewertet = [z for z in zug if any(z.get("p_" + k) is not None for k in KRITERIEN)]
        if bewertet:
            zeilen = []
            for k, zs in gruppen(bewertet, schluessel).items():
                zk = zug_kennzahlen(zs)
                zeilen.append(list(k) + [fmt(zk["r_" + krit]) for krit in KRITERIEN])
            teile.append("Rubrik (0 bis 2 Punkte je Kriterium, Mittel und Anzahl bewerteter Züge; "
                         "die vier letzten Kriterien gibt es seit 30.10.2026):")
            teile.append("")
            teile.append(tabelle(list(schluessel) + [KRITERIEN_NAMEN[k] for k in KRITERIEN], zeilen))
            teile.append("")

    block("Je Lauf und Tutor", ("lauf", "tutor"), zeilen_dialog, zeilen_zug)
    block("Je Schulstufe", ("lauf", "stufe"), zeilen_dialog, zeilen_zug)
    block("Je Profil", ("lauf", "profil"), zeilen_dialog, zeilen_zug)
    block("Je Hilfeumfang", ("lauf", "umfang"), zeilen_dialog, zeilen_zug)

    teile.append("## Hilfe nach Diagnose (seit 30.10.2026)")
    teile.append("")
    teile.append("Nachfragen des Tutors vor der Hilfe, Stufe der ersten Hilfe, Sprünge um mehr "
                 "als eine Stufe zwischen zwei Stufenhilfen (hoch, runter) und Rückschritte "
                 "überhaupt, Form (direkt) und Weite (eng) der Stufenhilfen, Bestätigung mit "
                 "Warum-Frage und ihre Beantwortung, und wie oft der Server den Wunsch des "
                 "Modells (Hilfe 0 bis 4 aus dem JSON) überstimmt hat. Läufe vor dem Umbau "
                 "zeigen die Leiter: keine Nachfrage, erste Hilfe Stufe 1, keine Form; D3 "
                 "bleibt der Vergleich.")
    teile.append("")

    def diagnose_block(titel, schluessel):
        teile.append(f"### {titel}")
        teile.append("")
        zeilen = []
        for k, zs in gruppen(zeilen_dialog, schluessel).items():
            zuege = [z for z in zeilen_zug if all(z.get(s) == v for s, v in zip(schluessel, k))]
            dk = diagnose_kennzahlen(zs, zuege)
            ueber = (f"{fmt(dk['ueberstimmt_%'])} ({dk['ueberstimmt']}/{dk['diagnosen_mit_wunsch']})"
                     if dk["diagnosen_mit_wunsch"] else "–")
            zeilen.append(list(k) + [
                dk["dialoge"], fmt(dk["hilfen_je_dialog"]), fmt(dk["nachfragen_je_dialog"]),
                fmt(dk["mit_nachfrage_%"]), fmt(dk["erster_zug_nachfrage_%"]),
                dk["erste_hilfe"][1], dk["erste_hilfe"][2], dk["erste_hilfe"][3], dk["erste_hilfe"][4],
                dk["spruenge_hoch"], dk["spruenge_runter"], dk["rueckschritte"],
                fmt(dk["direkt_%"]), fmt(dk["eng_%"]),
                fmt(dk["mit_bestaetigung_%"]), fmt(dk["warum_beantwortet_%"]), ueber,
            ])
        teile.append(tabelle(list(schluessel) + [
            "Dialoge", "Stufenhilfen je Dialog", "Nachfragen je Dialog", "mit Nachfrage %",
            "erster Zug Nachfrage %", "erste Hilfe 1", "erste Hilfe 2", "erste Hilfe 3",
            "erste Hilfe 4", "Sprünge hoch", "Sprünge runter", "Rückschritte", "direkt %",
            "eng %", "Bestätigung mit Warum-Frage %", "Warum beantwortet %",
            "überstimmt % (n)"], zeilen))
        teile.append("")

    diagnose_block("Je Lauf und Tutor", ("lauf", "tutor"))
    diagnose_block("Je Schulstufe", ("lauf", "stufe"))
    diagnose_block("Je Profil", ("lauf", "profil"))

    def verteilung_block(titel, feld, kategorien, namen):
        teile.append(f"### {titel}")
        teile.append("")
        zeilen = []
        for k, zs in gruppen(zeilen_dialog, ("lauf", "stufe")).items():
            dk = diagnose_kennzahlen(zs, [])
            werte = dk[feld]
            if not any(werte.values()):
                continue
            zeilen.append(list(k) + [werte[c] for c in kategorien])
        teile.append(tabelle(["Lauf", "Schulstufe"] + [namen[c] for c in kategorien], zeilen)
                     if zeilen else "keine (nur Läufe vor dem Umbau)")
        teile.append("")

    verteilung_block("Lage je diagnostiziertem Beitrag", "lagen", LAGEN, levels.LAGEN)
    verteilung_block("Absicht je diagnostiziertem Beitrag", "absichten", ABSICHTEN,
                     levels.ABSICHTEN)

    teile.append("### Gründe, aus denen der Server den Wunsch des Modells überstimmt hat")
    teile.append("")
    zeilen = []
    for k, zs in gruppen(zeilen_dialog, ("lauf",)).items():
        dk = diagnose_kennzahlen(zs, [])
        for grund, n in dk["ueberstimmt_gruende"].items():
            zeilen.append([k[0], grund, n])
    teile.append(tabelle(["Lauf", "Grund (aus der Diagnose)", "Anzahl"], zeilen)
                 if zeilen else "keine")
    teile.append("")

    teile.append("## Diagnose mit Ergebnis (seit Lauf D)")
    teile.append("")
    zeilen = []
    for k, zs in gruppen(zeilen_zug, ("lauf", "stufe")).items():
        zk = zug_kennzahlen(zs)
        if not zk["diagnosen"]:
            continue
        zeilen.append(list(k) + [zk["diagnosen"], zk["diag_richtig_n"], zk["diag_falsch_n"],
                                 zk["diag_offen_n"], zk["diag_richtig_obwohl_muster_nein"],
                                 zk["diag_nicht_richtig_obwohl_muster_ja"],
                                 zk["diag_fehler_benannt_n"]])
    teile.append(tabelle(["Lauf", "Schulstufe", "Diagnosen", "richtig", "falsch", "offen",
                          "richtig ohne Muster", "Muster ohne richtig", "Fehler benannt"],
                         zeilen) if zeilen else "keine")
    teile.append("")

    teile.append("## Je Zech-Stufe (Tutorzüge)")
    teile.append("")
    zeilen = []
    for k, zs in gruppen([z for z in zeilen_zug if z["zech"]], ("lauf", "zech")).items():
        zk = zug_kennzahlen(zs)
        zeilen.append(list(k) + [zk["zuege"], fmt(zk["verstoss_erster_%"]), fmt(zk["gekuerzt_%"]),
                                 fmt(zk["notfall_%"]), fmt(zk["verraet_loesung_%"]),
                                 fmt(zk["genau_eine_frage_%"]), fmt(zk["zu_lang_%"]),
                                 fmt(zk["woerter_mittel"])]
                      + [fmt(zk["r_" + krit]) for krit in KRITERIEN])
    teile.append(tabelle(["Lauf", "Zech-Stufe", "Züge", "Verstoß 1. Versuch %", "gekürzt %",
                          "Notfalltext %", "Lösung verraten %", "genau eine Frage %", "zu lang %",
                          "Wörter"] + [KRITERIEN_NAMEN[k] for k in KRITERIEN], zeilen))
    teile.append("")

    teile.append("## Je Art des Tutorzuges (seit 30.10.2026)")
    teile.append("")
    zeilen = []
    for k, zs in gruppen(zeilen_zug, ("lauf", "art")).items():
        zk = zug_kennzahlen(zs)
        zeilen.append(list(k) + [zk["zuege"], fmt(anteil([z["verstoss_erster"] for z in zs])),
                                 fmt(anteil([z["gekuerzt"] for z in zs])),
                                 fmt(zk["verraet_loesung_%"]),
                                 fmt(anteil([z["fragen"] == 1 for z in zs])),
                                 fmt(anteil([z["fragen"] == 0 for z in zs])),
                                 fmt(einsetz_anteil(zs)),
                                 fmt(anteil([z.get("schlussfrage") in ("modell", "vorlage")
                                             for z in zs])),
                                 fmt(anteil([z.get("schlussfrage") == "vorlage" for z in zs])),
                                 fmt(anteil([z.get("schleife") for z in zs])),
                                 fmt(zk["zu_lang_%"]), fmt(zk["woerter_mittel"])])
    teile.append(tabelle(["Lauf", "Art", "Züge", "Verstoß 1. Versuch %", "gekürzt %",
                          "Lösung verraten %", "genau eine Frage %", "keine Frage %",
                          "Einsetzfrage %", "nachgefasst %", "Vorlage %", "Schleife %",
                          "zu lang %",
                          "Wörter"], zeilen))
    teile.append("")

    teile.append("## Status der Dialoge")
    teile.append("")
    zeilen = []
    for k, zs in gruppen(zeilen_dialog, ("lauf", "status")).items():
        zeilen.append(list(k) + [len(zs), ", ".join(z["id"] for z in zs)])
    teile.append(tabelle(["Lauf", "Status", "Anzahl", "Dialoge"], zeilen))
    teile.append("")

    teile.append("## Verstöße der Ausgangsprüfung (erster Versuch), nach Art")
    teile.append("")
    zaehler = defaultdict(int)
    for z in zeilen_zug:
        for v in z["verstoesse_erster"]:
            zaehler[(z["lauf"], z["zech"], v)] += 1
    zeilen = [[k[0], k[1], k[2], n] for k, n in sorted(zaehler.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0, kv[0][2]))]
    teile.append(tabelle(["Lauf", "Zech-Stufe", "Verstoß", "Anzahl"], zeilen))
    teile.append("")

    teile.append("## Durchrutscher: verbotene Form im Endtext (nach Prüfung)")
    teile.append("")
    # In den Zeilen heisst "stufe" die Schulstufe; die Zech-Stufe ist "zech",
    # die Pruefstufe der Zuege ohne Stufe "pruefstufe".
    zeilen = [[z["lauf"], z["id"], z["nr"],
               z["zech"] or f"({z['art']}, Prüfstufe {z['pruefstufe']})",
               ", ".join(z["verstoss_endtext"])]
              for z in zeilen_zug
              if z["verstoss_endtext"]
              and (z["zech"] or z["pruefstufe"] or levels.LOESUNG) < levels.LOESUNG]
    teile.append(tabelle(["Lauf", "Dialog", "Zug", "Zech-Stufe", "Form"], zeilen) if zeilen else "keine")
    teile.append("")

    teile.append("## Ampel (Einstufung der Kinderbeiträge)")
    teile.append("")
    zaehler = defaultdict(int)
    for z in zeilen_zug:
        if z["kind_ampel"]:
            zaehler[(z["lauf"], z["profil"], z["kind_ampel"])] += 1
    zeilen = [[k[0], k[1], k[2], n] for k, n in sorted(zaehler.items())]
    teile.append(tabelle(["Lauf", "Profil", "Ampel", "Anzahl"], zeilen))
    teile.append("")

    teile.append("## Latenz der Spark-Anfragen (ms)")
    teile.append("")
    zeilen = []
    for (lauf, art), werte in sorted(latenz.items()):
        t = tokens[(lauf, art)]
        zeilen.append([lauf, art, len(werte), int(statistics.median(werte)), perzentil(werte, 90),
                       int(statistics.mean(werte)), max(werte),
                       int(statistics.mean(t["ein"])) if t["ein"] else None,
                       int(statistics.mean(t["aus"])) if t["aus"] else None])
    teile.append(tabelle(["Lauf", "Art", "n", "Median", "p90", "Mittel", "Max",
                          "Token ein (Mittel)", "Token aus (Mittel)"], zeilen))
    teile.append("")
    return "\n".join(teile)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ergebnisse", default=os.path.join(HIER, "ergebnisse"))
    parser.add_argument("--lauf", default="", help="nur dieser Lauf")
    parser.add_argument("--still", action="store_true", help="nichts ausgeben, nur schreiben")
    args = parser.parse_args()

    dialoge = protokolle_laden(args.ergebnisse, args.lauf or None)
    if not dialoge:
        print("Keine Protokolle gefunden unter", args.ergebnisse)
        sys.exit(1)
    bewertungen = bewertungen_laden(args.ergebnisse)
    zd, zz, latenz, tokens = auswerten(dialoge, bewertungen)
    text = bericht(zd, zz, latenz, tokens)

    # Die Masse zur Hilfe nach Diagnose auch als JSON, je Lauf, Schulstufe, Profil.
    diagnose = {}
    for schluessel in (("lauf",), ("lauf", "stufe"), ("lauf", "profil")):
        for k, zs in gruppen(zd, schluessel).items():
            zuege = [z for z in zz if all(z.get(s) == v for s, v in zip(schluessel, k))]
            diagnose["/".join(str(x) for x in k)] = diagnose_kennzahlen(zs, zuege)

    with open(os.path.join(args.ergebnisse, "auswertung.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(args.ergebnisse, "auswertung.json"), "w", encoding="utf-8") as f:
        json.dump({"dialoge": zd, "zuege": zz, "diagnose": diagnose,
                   "latenz": {f"{k[0]}/{k[1]}": v for k, v in latenz.items()}},
                  f, ensure_ascii=False, indent=1)
    if not args.still:
        print(text)


if __name__ == "__main__":
    main()
