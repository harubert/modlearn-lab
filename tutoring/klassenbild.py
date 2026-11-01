"""Das Klassenbild: eine Kachel je Kind, nach Aufmerksamkeitsbedarf sortiert.

Bericht vom 19.10.2026, Abschnitt 6.3, Bildschirm 2 der Lehrperson. Vorher
stand die Klasse als Tabelle da: Aufgaben, Hilfen, Stufe, zuletzt aktiv,
Ampel. Das waren Zahlen ueber das Kind, nicht das, was das Kind gerade tut.
Jetzt zeigt jede Kachel die Aufgabe, den Weg durch die Stufen, den letzten
Beitrag und die Diagnose dazu - und die Kacheln, die einen Blick brauchen,
stehen oben und sind gerahmt.

Drei Zustaende heben eine Kachel nach oben, in dieser Reihenfolge:

  1. Ampel orange oder rot (ein Beitrag, der nicht zur Aufgabe gehoert),
  2. dreimal dieselbe Stufe (Task.repeats oder die letzten drei Hilfen),
  3. seit fuenf Minuten kein Beitrag.

Hier stehen die reinen Rechnungen ohne Datenbank: Was aus einer Stufenfolge
wird, was die Diagnosezeile sagt, welchen Rang eine Kachel bekommt. Die
Abfragen dazu macht views._klassenliste.
"""

from datetime import timedelta

from . import levels, pruefung

# Wann ein Kind als still gilt. Fuenf Minuten sind im Unterricht lang genug,
# dass niemand mehr nachdenkt, und kurz genug, dass es sich lohnt, hinzugehen.
STILL_NACH = timedelta(minutes=5)

# Wie viele Zeichen von Aufgabe und Beitrag auf die Kachel passen. Eine
# Zeile; wer mehr wissen will, tippt auf die Kachel und bekommt den Verlauf.
ZEILE_HOECHSTENS = 80

# Dasselbe wie Hint.ERGEBNIS_RICHTIG, hier noch einmal benannt, damit diese
# Datei ohne das Modell lesbar bleibt (ein Test prueft die Gleichheit).
RICHTIG = "richtig"

# --- Die fuenf Stufenpunkte ------------------------------------------------
#
# gefuellt = gegeben, Ring = wiederholt, Pfeil = zurueck (Bericht 6.3). Dazu
# zwei Zustaende, die der Bericht nicht nennt, die das Bild aber braucht:
# offen (noch nicht gegeben) und gesperrt (ueber der Obergrenze der
# Lehrperson, bei "Ueben" also Stufe 4 und 5).

GEGEBEN = "gegeben"
WIEDERHOLT = "wiederholt"
ZURUECK = "zurueck"
OFFEN = "offen"
GESPERRT = "gesperrt"

WORT = {
    GEGEBEN: "gegeben",
    WIEDERHOLT: "wiederholt",
    ZURUECK: "zurück",
    OFFEN: "offen",
    GESPERRT: "nicht freigegeben",
}

# Masse der Zeichnung (_stufenpunkte.html): Abstand der Punkte und Rand.
# Die Vorlage rechnet nicht, deshalb steht die x-Lage schon hier.
PUNKT_ABSTAND = 20
PUNKT_RAND = 10


def punkte_zeichnen(zustaende):
    """Die Punkte fuer die Vorlage: Stufe, Zustand, Wort und x-Lage."""
    return [
        {
            "stufe": i + 1,
            "zustand": zustand,
            "wort": WORT[zustand],
            "x": PUNKT_RAND + i * PUNKT_ABSTAND,
        }
        for i, zustand in enumerate(zustaende)
    ]


def breite(punkte):
    """Die Breite der Zeichnung fuer so viele Punkte."""
    if not punkte:
        return PUNKT_RAND * 2
    return PUNKT_RAND * 2 + PUNKT_ABSTAND * (len(punkte) - 1)


def stufenpunkte(stufenfolge, obergrenze=levels.LOESUNG):
    """Die fuenf Punkte zu einer Folge gegebener Stufen.

    `stufenfolge` sind die Stufen der Hilfen in der Reihenfolge, in der das
    Kind sie bekommen hat. Eine Stufe unter der vorigen ist ein Schritt
    zurueck; eine, die schon einmal da war, eine Wiederholung.
    """
    zustaende = [
        OFFEN if stufe <= obergrenze else GESPERRT
        for stufe in range(1, levels.LOESUNG + 1)
    ]
    vorige = 0
    for stufe in stufenfolge:
        if not 1 <= stufe <= levels.LOESUNG:
            continue
        i = stufe - 1
        if stufe < vorige:
            zustaende[i] = ZURUECK
        elif zustaende[i] in (GEGEBEN, WIEDERHOLT, ZURUECK):
            zustaende[i] = WIEDERHOLT
        else:
            zustaende[i] = GEGEBEN
        vorige = stufe
    return punkte_zeichnen(zustaende)


def leere_kachel(obergrenze=levels.LOESUNG):
    """Die Kachel eines Kindes, das noch keine Aufgabe gestellt hat."""
    punkte = stufenpunkte([], obergrenze)
    return {
        "aufgabe_zeile": "",
        "aufgabe_fertig": False,
        "punkte": punkte,
        "breite": breite(punkte),
        "beitrag": "",
        "diagnose": "",
        "dreimal": False,
        "stufe_zuletzt": 0,
        "eigenanteil_zeile": "",
        "note_zeile": "",
    }


def dreimal_dieselbe(stufenfolge, wiederholungen=0):
    """Hat das Kind dreimal hintereinander dieselbe Stufe bekommen?

    Zwei Wege zu derselben Antwort: der Zaehler der Aufgabe (Task.repeats,
    zwei Wiederholungen heisst dreimal dieselbe) oder die letzten drei
    Hilfen. Der zweite faengt Daten von vor dem Zaehler.
    """
    if wiederholungen >= levels.HOECHSTE_WIEDERHOLUNGEN:
        return True
    folge = list(stufenfolge)
    return len(folge) >= 3 and folge[-1] == folge[-2] == folge[-3]


# --- Eine Zeile Text -------------------------------------------------------

def erste_zeile(text, hoechstens=ZEILE_HOECHSTENS):
    """Die erste nicht leere Zeile, auf eine Kachelzeile gekuerzt."""
    for zeile in (text or "").splitlines():
        zeile = " ".join(zeile.split())
        if zeile:
            if len(zeile) <= hoechstens:
                return zeile
            return zeile[:hoechstens - 1].rstrip() + "…"
    return ""


# --- Die Diagnosezeile -----------------------------------------------------

def _geladen(hilfe, feld):
    """Der Wert eines Feldes, oder leer, wenn die Abfrage es nicht geladen hat.

    views._kacheln holt die Hilfen der ganzen Klasse mit only(); ein Feld,
    das dort fehlt, wuerde beim Zugriff je Kind eine eigene Abfrage kosten,
    alle fuenf Sekunden. Lieber die Zeile ohne dieses Wort.
    """
    verschoben = getattr(hilfe, "get_deferred_fields", None)
    if verschoben is not None and feld in verschoben():
        return ""
    return getattr(hilfe, feld, "") or ""


def diagnose(hilfe):
    """Was die Anwendung aus dem Beitrag geschlossen hat, in einer Zeile.

    "Das stimmt." bei richtigem Ergebnis. Sonst zuerst der Befund: die Lage
    in Worten (levels.LAGEN) und der Fehler im Klartext (Hint.error), etwa
    "falscher Ansatz: Zähler und Nenner getrennt addiert"; fehlen beide, die
    Begruendung der Wahl (Hint.goal_note). Dann die Wahl: "danach Stufe 2,
    direkt" oder "danach: erst nachfragen" (next_level 0, die Nachfrage vor
    der Hilfe). Leer, solange kein Beitrag da ist.

    Seit 30.10.2026 wird die Hilfe gewaehlt, nicht gezaehlt; die Stufe steht
    deshalb neutral da, ohne "weiter" oder "zurueck".
    """
    if hilfe is None or not hilfe.response:
        return ""
    if hilfe.result == RICHTIG:
        return "Das stimmt."
    if _geladen(hilfe, "art") == levels.ART_BESTAETIGUNG:
        # Der letzte Beitrag ist die Antwort auf die Warum-Frage. Sie wird
        # nicht beurteilt; die Bestaetigung gibt es nur nach einem richtigen
        # Ergebnis, also bleibt die Zeile bei dem, was gilt.
        return "Das stimmt."
    lage = levels.LAGEN.get(_geladen(hilfe, "lage"), "")
    fehler = hilfe.error or ""
    befund = ": ".join(teil for teil in (lage, fehler) if teil)
    if _geladen(hilfe, "absicht") == levels.ABSICHT_UMGEHUNG:
        # Offene Karten (31.10.2026): Die Lehrperson soll den Versuch, die
        # Hilfe zu umgehen, als Diagnose lesen, nicht nur "kein Ansatz".
        befund = levels.ABSICHTEN[levels.ABSICHT_UMGEHUNG]
    if not befund:
        befund = hilfe.goal_note or ""
    danach = ""
    if hilfe.next_level is not None and hilfe.next_level == levels.ERST_FRAGEN:
        danach = "danach: erst nachfragen"
    elif hilfe.next_level:
        danach = f"danach Stufe {hilfe.next_level}"
        form = levels.FORMEN.get(_geladen(hilfe, "next_form"), "")
        if form:
            danach += f", {form}"
    return " – ".join(teil for teil in (befund, danach) if teil)


# --- Rang und Grund --------------------------------------------------------

AUFFAELLIG = 0
DREIMAL = 1
STILL = 2
RUHIG = 3

# Die Ampel neben dem Punkt, in zwei Worten. pruefung.BESCHREIBUNG ist der
# ganze Satz fuer den Verlauf; auf der Kachel ist dafuer kein Platz.
AMPEL_KURZ = {
    pruefung.GRUEN: "alles nach Plan",
    pruefung.GELB: "unsinnige Eingabe",
    pruefung.ORANGE: "bitte ansehen",
    pruefung.ROT: "Schimpfwort",
    pruefung.UNGEPRUEFT: "nicht geprüft",
}


def einordnung(ampel, dreimal, still, stufe=0, stille_minuten=0, umgehungen=0):
    """(Rang, Grund): ob eine Kachel oben steht, und warum.

    Der Grund steht sichtbar in der Kachel. Ein Rahmen ohne Wort waere eine
    Farbe, die man deuten muss. ``umgehungen`` zaehlt die Umgehungsversuche
    des Kindes in dieser Sitzung (offene Karten, 31.10.2026): Dann sagt der
    Grund, was es anzusehen gibt.
    """
    if ampel in (pruefung.ORANGE, pruefung.ROT):
        if umgehungen and ampel == pruefung.ORANGE:
            return AUFFAELLIG, "Umgehungsversuch, Beitrag ansehen"
        return AUFFAELLIG, "Beitrag ansehen"
    if dreimal:
        return DREIMAL, f"dreimal Stufe {stufe}" if stufe else "dreimal dieselbe Stufe"
    if still:
        return STILL, f"seit {stille_minuten} Minuten kein Beitrag"
    return RUHIG, ""


def sortierschluessel(zeile):
    """Zuerst der Rang, innerhalb des Rangs die zuletzt Aktiven oben."""
    return (zeile["rang"], -zeile["zuletzt"].timestamp())


# --- Eigenanteil: was das Kind selbst geschafft hat (grobe Einschaetzung) ----
#
# Thomas (1.11.2026): "Ich haette gerne einen Prozentsatz, wie viel der
# Schueler aufgrund der Hilfe dann geschafft hat ... mit dem Hinweis, dass es
# eine grobe Einschaetzung ist." Die Rechnung ist eine Faustregel ueber die
# Hilfestufen nach Zech, kein Messwert: Je staerker die staerkste Hilfe vor
# dem richtigen Ergebnis, desto weniger war es das Kind allein; jede weitere
# Stufenhilfe vor dem Ergebnis kostet fuenf Punkte; die gezeigte Loesung ist
# null. Nachfrage, Auftakt, Bestaetigung und Nachsatz sind keine Hilfen und
# zaehlen nicht. Ohne Ergebnis gibt es keine Zahl.

ANTEIL_JE_STUFE = {0: 100, 1: 90, 2: 75, 3: 60, 4: 40}
ABZUG_JE_WEITERER_HILFE = 5
ANTEIL_MINDESTENS = 10
GELOEST = "geloest"
LOESUNG_GEZEIGT = "gezeigt"


def eigenanteil(hilfen):
    """Die grobe Einschaetzung fuer eine Aufgabe, oder None ohne Ergebnis.

    ``hilfen`` sind die Zuege der Aufgabe in ihrer Reihenfolge (Hint oder
    etwas mit art, level und result). Gibt ein Woerterbuch: ``anteil`` (0
    bis 100, was das Kind selbst geschafft hat), ``hoechste`` (die staerkste
    Stufe vor dem Ergebnis), ``hilfen`` (Stufenhilfen vor dem Ergebnis),
    ``stand`` (GELOEST oder LOESUNG_GEZEIGT) und ``text``.
    """
    stufen_davor = []
    for zug in list(hilfen or []):
        art = getattr(zug, "art", "") or levels.ART_HILFE
        stufe = getattr(zug, "level", 0) or 0
        ist_stufe = art == levels.ART_HILFE and levels.MOTIVATION <= stufe < levels.LOESUNG
        if ist_stufe:
            stufen_davor.append(stufe)
        if getattr(zug, "result", "") == RICHTIG:
            hoechste = max(stufen_davor, default=0)
            anteil = (ANTEIL_JE_STUFE[hoechste]
                      - ABZUG_JE_WEITERER_HILFE * max(0, len(stufen_davor) - 1))
            anteil = max(ANTEIL_MINDESTENS, anteil)
            return {"anteil": anteil, "hoechste": hoechste, "hilfen": len(stufen_davor),
                    "stand": GELOEST, "text": eigenanteil_text(anteil)}
        if art == levels.ART_HILFE and stufe >= levels.LOESUNG:
            return {"anteil": 0, "hoechste": levels.LOESUNG, "hilfen": len(stufen_davor),
                    "stand": LOESUNG_GEZEIGT, "text": eigenanteil_text(0)}
    return None


def eigenanteil_text(anteil):
    """"etwa 75 % selbst, 25 % durch die Hilfen"; die Raender in Worten."""
    if anteil >= 100:
        return "ohne Hilfe gelöst"
    if anteil <= 0:
        return "Lösung gezeigt"
    return f"etwa {anteil} % selbst, {100 - anteil} % durch die Hilfen"


def eigenanteil_mittel(einschaetzungen):
    """Das Mittel der Anteile, auf fuenf gerundet; None ohne Einschaetzung."""
    werte = [e["anteil"] for e in einschaetzungen if e]
    if not werte:
        return None
    # Kaufmaennisch, nicht wie round(): 72,5 wird 75, nicht 70.
    return int(sum(werte) / len(werte) / 5.0 + 0.5) * 5


def eigenanteil_zeile(einschaetzungen):
    """Die Zeile fuer Kachel und Verlaufskopf, leer ohne Einschaetzung."""
    werte = [e for e in einschaetzungen if e]
    mittel = eigenanteil_mittel(werte)
    if mittel is None:
        return ""
    n = len(werte)
    return f"{eigenanteil_text(mittel)} ({n} Aufgabe{'n' if n != 1 else ''})"


# --- Die Note des Kindes (Thomas, 1.11.2026) ---------------------------------

def note_zeile(noten):
    """"Note der Hilfe: Ø 2,0 (3 Aufgaben)", leer ohne Note; fuer Kachel und Verlaufskopf."""
    werte = [int(n) for n in noten if n]
    if not werte:
        return ""
    mittel = f"{sum(werte) / len(werte):.1f}".replace(".", ",")
    n = len(werte)
    return f"Note der Hilfe: Ø {mittel} ({n} Aufgabe{'n' if n != 1 else ''})"
