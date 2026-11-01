"""Der Ablauf eines Sprechgesprächs: Planen, Aufgabe, Noch einmal, Rückblick.

WARUM DER SERVER DEN ABLAUF STEUERT

Regel 12 des Berichts (docs/Gesprächsdidaktik Englisch für den
Sprechcoach.md): Die Bedingungen, unter denen gesprochen wird, wirken
stärker als das Thema (Skehan 2016). Planung hebt Flüssigkeit und
Komplexität (Foster & Skehan 1996), Wiederholung derselben Aufgabe hebt
Komplexität und Genauigkeit (Abdi Tabari et al. 2025), bei Kindern
Flüssigkeit und Genauigkeit (Sun & Révész 2021). Der teaching-speaking cycle
nach Goh & Burns ist: Vorbereitung, Sprechaufgabe, Sprachfokus, Wiederholung,
Reflexion.

Ob das Gespräch in die nächste Phase geht, entscheidet deshalb diese Datei
und nicht das Modell. Das Modell bekommt je Phase eine eigene Anweisung; den
Wechsel selbst bekommt es nur mitgeteilt. Ein Systemprompt ist eine Bitte.

DIE PHASEN

PLANEN       Das Kind sieht Ziel und Redemittel, eine Minute „think first".
AUFGABE      Das Kind fragt, der Coach hält sein Geheimnis. Der Server prüft
             nach jedem Beitrag, ob das Ziel erreicht ist.
WECHSEL      Rollentausch (Regel 11): Jetzt fragt der Coach, das Kind
             antwortet. Auf der Seite gehört das noch zum „Gespräch".
WIEDERHOLUNG Dieselbe Aufgabe noch einmal, Coach in leicht anderer Rolle.
RUECKBLICK   Zwei bis drei Punkte, deutsch erklärt, englisch gezeigt, keine
             Note (Regel 6, zweiter Teil).

Das freie Gespräch kennt nur AUFGABE und RUECKBLICK: Es hat kein Ziel, also
weder einen Wechsel nach dem Ziel noch eine Wiederholung desselben Inhalts.

Diese Datei kennt keine Datenbank. Sie bekommt Listen und gibt Entscheidungen
zurück; die Ansicht legt ab. So lässt sich jeder Übergang ohne Sitzung prüfen.
"""

import re

from . import sprechaufgaben, sprechcoach

PLANEN = "planen"
AUFGABE = "aufgabe"
WECHSEL = "wechsel"
WIEDERHOLUNG = "wiederholung"
RUECKBLICK = "rueckblick"

PHASEN = (
    (PLANEN, "Planen"),
    (AUFGABE, "Gespräch"),
    (WECHSEL, "Gespräch, Rollentausch"),
    (WIEDERHOLUNG, "Noch einmal"),
    (RUECKBLICK, "Rückblick"),
)

# Die vier Schritte, die das Kind oben sieht. Der Wechsel ist für das Kind
# Teil des Gesprächs: vier Schritte kann man sich merken, fünf nicht.
SCHRITTE = (
    (PLANEN, "Planen"),
    (AUFGABE, "Gespräch"),
    (WIEDERHOLUNG, "Noch einmal"),
    (RUECKBLICK, "Rückblick"),
)

SCHRITT_VON = {
    PLANEN: 1, AUFGABE: 2, WECHSEL: 2, WIEDERHOLUNG: 3, RUECKBLICK: 4,
}

GESPRAECHSPHASEN = (AUFGABE, WECHSEL, WIEDERHOLUNG)

VOLKSSCHULE = "6-10"


def ist_volksschule(altersklasse):
    return altersklasse == VOLKSSCHULE


# --- Die Längen ------------------------------------------------------------
#
# Regel 12, Niveau: Volksschule drei bis fünf Minuten je Einheit, Sek I zehn
# bis fünfzehn. Gezählt wird in Beiträgen, nicht in Minuten: Ein Kind, das
# lange überlegt, soll deshalb nicht weniger sagen dürfen.

# Planungszeit, die angezeigt wird ("1 Minute, think first").
PLANEN_SEKUNDEN = 60
# Darunter nimmt der Server "Ich bin bereit" nicht an. Die Hälfte: Ein Kind,
# das seine Fragen schon hat, soll nicht absitzen müssen, aber ein Klick
# gleich nach dem Laden ist kein Planen.
PLANEN_MINDESTENS = {VOLKSSCHULE: 20}
PLANEN_MINDESTENS_SONST = 30

# Höchstens so viele Beiträge des Kindes je Durchgang. Danach geht es weiter,
# auch ohne erreichtes Ziel: Ein Gespräch, das nicht endet, ist keine
# Aufgabe mehr, und die Zahl "Ziel nicht erreicht" sagt der Lehrperson mehr
# als ein Kind, das nach zwanzig Zügen aufgibt.
HOECHSTENS_BEITRAEGE = {VOLKSSCHULE: 6}
HOECHSTENS_BEITRAEGE_SONST = 10

# So viele Antworten im Rollentausch.
WECHSEL_ANTWORTEN = {VOLKSSCHULE: 1}
WECHSEL_ANTWORTEN_SONST = 2


def planen_mindestens(altersklasse):
    return PLANEN_MINDESTENS.get(altersklasse, PLANEN_MINDESTENS_SONST)


def hoechstens_beitraege(altersklasse):
    return HOECHSTENS_BEITRAEGE.get(altersklasse, HOECHSTENS_BEITRAEGE_SONST)


def wechsel_antworten(altersklasse):
    return WECHSEL_ANTWORTEN.get(altersklasse, WECHSEL_ANTWORTEN_SONST)


def startphase(aufgabe):
    """Mit einer Aufgabe wird zuerst geplant, das freie Gespräch fängt an."""
    return AUFGABE if sprechaufgaben.ist_frei(aufgabe) else PLANEN


# --- Der Übergang ----------------------------------------------------------

def nach_beitrag(phase, aufgabe, altersklasse, beitraege_der_phase):
    """Wohin geht es nach diesem Beitrag des Kindes?

    `beitraege_der_phase` sind ALLE Texte des Kindes in der laufenden Phase,
    der neue eingeschlossen. Zurück kommt (neue Phase, Ziel erreicht oder
    None). None heißt: In dieser Phase wird kein Ziel geprüft.

    Die Sprachsperre ruft das nicht: Ein deutscher Beitrag kann kein
    englisches Ziel erreichen, und er soll auch nicht den Durchgang
    verkürzen.
    """
    if phase not in GESPRAECHSPHASEN or sprechaufgaben.ist_frei(aufgabe):
        return phase, None

    if phase == WECHSEL:
        if len(beitraege_der_phase) >= wechsel_antworten(altersklasse):
            return WIEDERHOLUNG, None
        return WECHSEL, None

    erreicht = sprechaufgaben.ziel_erreicht(aufgabe, beitraege_der_phase)
    zu_lang = len(beitraege_der_phase) >= hoechstens_beitraege(altersklasse)
    if not (erreicht or zu_lang):
        return phase, None
    naechste = WECHSEL if phase == AUFGABE else RUECKBLICK
    return naechste, erreicht


def gedaechtnis_phasen(phase):
    """Welche Phasen gehören ins Gesprächsgedächtnis des Modells?

    In der Wiederholung nur sie selbst: Der Coach soll dieselbe Aufgabe neu
    spielen und nicht sagen "as I told you before". Im Rollentausch die
    Aufgabe dazu, weil er an das Ergebnis anknüpft.
    """
    if phase == WIEDERHOLUNG:
        return (WIEDERHOLUNG,)
    if phase == WECHSEL:
        return (AUFGABE, WECHSEL)
    return (AUFGABE,)


# --- Was das Modell je Phase bekommt --------------------------------------
#
# Deutsch wie der übrige Prompt, die Rolle und das Geheimnis englisch, weil
# der Coach sie auf Englisch spielt.

_AUFGABE_TEXT = (
    "DIESES GESPRÄCH IST EINE AUFGABE, KEIN SMALLTALK.\n"
    "Deine Rolle: You are {rolle}\n"
    "Das Ziel des Gegenübers: {ziel}\n"
    "DEIN GEHEIMNIS (nur du weißt das, das Gegenüber muss es erfragen):\n"
    "{geheimnis}\n"
    "\n"
    "SO SPIELST DU DIE AUFGABE:\n"
    "- Das Gegenüber fragt, du antwortest. Gib eine Information NUR, wenn "
    "danach gefragt wurde, und nur die, nach der gefragt wurde. Erzähl nie "
    "von selbst alles auf einmal.\n"
    "- Bleib in deiner Rolle. Kein Themenwechsel, kein Smalltalk über "
    "anderes.\n"
    "- Du musst nicht jeden Zug mit einer Frage beenden: Wenn du eine Frage "
    "beantwortet hast, darfst du warten (\"Anything else?\" ist erlaubt, "
    "aber nicht nötig). Höchstens EINE Frage.\n"
    "- Wenn das Gegenüber nicht weiterweiß, hilf mit einem Anfang "
    "(\"You can ask me: What ...?\").\n"
    "{offen}"
)

_OFFEN_TEXT = (
    "- Das Gegenüber hat noch nicht selbst gesagt: {liste}. Wenn es danach "
    "gefragt hat und du geantwortet hast, bitte es, das Ergebnis kurz in "
    "eigenen Worten zu sagen (\"So, what do you know now?\")."
)

_AUFGABE_ERSTER = (
    "Das Gespräch fängt gerade an. Begrüße kurz in deiner Rolle und sag in "
    "einem Satz, wer du bist. Verrate NICHTS aus deinem Geheimnis. Lade das "
    "Gegenüber mit einer kurzen Frage ein, dich zu fragen."
)

_WECHSEL_TEXT = (
    "JETZT TAUSCHT IHR DIE ROLLEN. Das Gegenüber hat die Aufgabe erledigt.\n"
    "Deine Rolle bleibt: You are {rolle}\n"
    "Jetzt fragst du: {wechsel}\n"
    "Genau EINE Frage je Zug. Knüpf an die Antwort an."
)

_WECHSEL_ERSTER = (
    "Das ist der erste Zug nach dem Wechsel. Bestätige in einem kurzen Satz, "
    "was das Gegenüber herausgefunden hat (ohne Lob, ohne \"Great\"), und "
    "stell dann deine erste Frage."
)

_WIEDERHOLUNG_TEXT = (
    "NOCH EINMAL DIESELBE AUFGABE. Das Gegenüber macht sie ein zweites Mal, "
    "weil es beim zweiten Mal flüssiger und genauer spricht.\n"
    "Deine Rolle jetzt: You are {rolle}\n"
    "Das Ziel des Gegenübers: {ziel}\n"
    "DEIN GEHEIMNIS ist dasselbe:\n"
    "{geheimnis}\n"
    "Spiel es genauso: Antworte nur auf das, wonach gefragt wird. Höchstens "
    "EINE Frage.\n"
    "{offen}"
)

_WIEDERHOLUNG_ERSTER = (
    "Die Wiederholung fängt an. Begrüße kurz in deiner NEUEN Rolle und sag "
    "in einem Satz, wer du jetzt bist. Verrate nichts aus dem Geheimnis. Lade "
    "das Gegenüber mit einer kurzen Frage ein, dich zu fragen."
)

# Der Abschied ist fest (Regel 13: Begrüßung, Nachfrage und Abschied sind
# Rituale und wiederholen sich). Darum kein Modellaufruf: Der letzte Satz
# soll immer gleich klingen, und er darf weder loben noch fragen.
ABSCHIED = {
    "en-GB": "Thank you, that was our talk for today. Now let's look back at it.",
}
ABSCHIED_STANDARD = ABSCHIED["en-GB"]


def abschied(sprache):
    return ABSCHIED.get(sprache, ABSCHIED_STANDARD)


def anweisung(phase, aufgabe, offene, erster_zug=False):
    """Die Phasenanweisung für den Systemprompt, oder ein leerer Text.

    `offene` sind die Merkmale, die das Kind in diesem Durchgang noch nicht
    selbst gesagt hat; der Server nennt sie dem Modell, damit es weiß, worauf
    es hinarbeitet. Das freie Gespräch bekommt nichts zusätzlich.
    """
    if sprechaufgaben.ist_frei(aufgabe) or phase not in GESPRAECHSPHASEN:
        return ""

    offen = ""
    if offene:
        offen = _OFFEN_TEXT.format(liste=", ".join(m["was"] for m in offene))

    if phase == AUFGABE:
        text = _AUFGABE_TEXT.format(
            rolle=aufgabe["rolle_coach"], ziel=aufgabe["ziel"],
            geheimnis=aufgabe["geheimnis"], offen=offen,
        )
        zusatz = _AUFGABE_ERSTER
    elif phase == WECHSEL:
        text = _WECHSEL_TEXT.format(
            rolle=aufgabe["rolle_coach"], wechsel=aufgabe["wechsel"],
        )
        zusatz = _WECHSEL_ERSTER
    else:
        text = _WIEDERHOLUNG_TEXT.format(
            rolle=aufgabe["rolle_wiederholung"] or aufgabe["rolle_coach"],
            ziel=aufgabe["ziel"], geheimnis=aufgabe["geheimnis"], offen=offen,
        )
        zusatz = _WIEDERHOLUNG_ERSTER
    if erster_zug:
        text += "\n\n" + zusatz
    return text.strip()


# Was das Kind unter der Phasenanzeige liest, deutsch. Der Server schickt den
# Satz mit jeder Antwort mit, damit die Seite nach einem Wechsel nicht raten
# muss, wo sie steht.
HINWEIS = {
    PLANEN: "Lies dein Ziel und die Wendungen. Überleg dir deine erste Frage.",
    AUFGABE: "Frag den Coach, bis du alles herausgefunden hast.",
    WECHSEL: "Jetzt fragt der Coach dich. Antworte ihm.",
    WIEDERHOLUNG: "Noch einmal dieselbe Aufgabe. Der Coach ist jetzt "
                  "jemand anderer – beim zweiten Mal geht es leichter.",
    RUECKBLICK: "Schau zurück, was gut geklappt hat.",
}
HINWEIS_FREI = "Erzähl und frag – der Coach hört zu."


def phasenhinweis(phase, aufgabe):
    if sprechaufgaben.ist_frei(aufgabe) and phase in GESPRAECHSPHASEN:
        return HINWEIS_FREI
    return HINWEIS.get(phase, "")


def kind_fragt(phase, aufgabe):
    """Fragt in dieser Phase das Kind (und der Coach antwortet)?

    Dann darf ein Coachzug ohne Frage enden, und eine Antwort auf eine Frage
    gilt als Anknüpfen. Im Rollentausch und im freien Gespräch fragt der
    Coach, mit genau einer Frage je Zug, wie bisher.
    """
    return (not sprechaufgaben.ist_frei(aufgabe)
            and phase in (AUFGABE, WIEDERHOLUNG))


def verraet_zu_viel(text, aufgabe, offene, erster_zug=False):
    """Plaudert der Coach sein Geheimnis aus?

    Im ersten Zug darf er nichts davon nennen, später höchstens zwei offene
    Merkmale auf einmal ("Saturday at three" auf "When is the party?" ist
    eine Antwort, alles auf einmal ist ein Vortrag). Gezählt werden nur
    geheime Merkmale: Ein "because" darf er vormachen.
    """
    geheime = [m for m in offene if m["geheim"]]
    if not geheime:
        return False
    genannt = sprechaufgaben.verraet(text, geheime)
    if erster_zug:
        return bool(genannt)
    return len(genannt) > 2


SCHAERFUNG_VERRAET = (
    "\n\nACHTUNG: Deine letzte Antwort hat zu viel aus deinem Geheimnis "
    "verraten. Gib nur die EINE Information, nach der gefragt wurde, oder im "
    "ersten Zug gar keine. Das Gegenüber soll fragen müssen."
)


# --- Messung (Regel 14) ----------------------------------------------------
#
# Die Maße der Literatur: Wörter je Lernerbeitrag (Brock 1986), Anteil
# erweiterter Beiträge (Alexander et al. 2017), lernerinitiierte Fragen
# (Szpotowicz 2012, Shashidhara et al. 2026), Durchhaltedauer. Dazu, was nur
# wir zählen können: wie oft die Sprachsperre griff, ob das Ziel erreicht
# wurde, und der erste gegen den zweiten Durchgang – denn Fortschritt zeigt
# sich über Wiederholungen, nicht innerhalb eines Gesprächs (Skehan).

# Ab hier gilt ein Beitrag als erweitert, wenn er nur einen Satz hat.
ERWEITERT_AB_WOERTERN = 8


def woerter(text):
    return len(sprechcoach._WORT.findall(text or ""))


def ist_erweitert(text):
    """Mehr als ein Satz, oder ein Satz mit mindestens acht Wörtern."""
    return (len(sprechcoach.saetze(text)) > 1
            or woerter(text) >= ERWEITERT_AB_WOERTERN)


# Dieselbe Erkennung wie beim Anknuepfen: eine Stelle, nicht zwei.
ist_frage = sprechcoach.ist_frage


def _durchgang(beitraege):
    """Zahlen für eine Liste von Kinderbeiträgen."""
    anzahl = len(beitraege)
    if not anzahl:
        return {"beitraege": 0, "woerter_je_beitrag": 0.0,
                "anteil_erweitert": 0.0, "fragen": 0, "woerter": 0}
    summe = sum(woerter(b) for b in beitraege)
    return {
        "beitraege": anzahl,
        "woerter": summe,
        "woerter_je_beitrag": summe / anzahl,
        "anteil_erweitert": sum(1 for b in beitraege if ist_erweitert(b)) / anzahl,
        "fragen": sum(1 for b in beitraege if ist_frage(b)),
    }


def messung(zuege):
    """Die Zahlen eines Gesprächs.

    `zuege` sind Wörterbücher oder Objekte mit rolle ("coach"/"lernend"),
    text, phase, nicht_verstanden und zeit (datetime), in zeitlicher
    Reihenfolge. Ein Kinderbeitrag, auf den die Sprachsperre folgte, zählt
    nicht als Beitrag: Er war nicht in der Zielsprache.
    """
    zuege = [_als_wb(z) for z in zuege]
    gesperrt = set()
    for i, z in enumerate(zuege):
        if z["rolle"] == "coach" and z["nicht_verstanden"] and i > 0:
            if zuege[i - 1]["rolle"] == "lernend":
                gesperrt.add(i - 1)

    kind = [(i, z) for i, z in enumerate(zuege)
            if z["rolle"] == "lernend" and i not in gesperrt]
    alle = [z["text"] for _, z in kind]
    erster = [z["text"] for _, z in kind if z["phase"] == AUFGABE]
    zweiter = [z["text"] for _, z in kind if z["phase"] == WIEDERHOLUNG]

    zeiten = [z["zeit"] for z in zuege if z["zeit"] is not None]
    dauer = (max(zeiten) - min(zeiten)).total_seconds() if len(zeiten) > 1 else 0

    gesamt = _durchgang(alle)
    gesamt.update({
        "sperren": sum(1 for z in zuege
                       if z["rolle"] == "coach" and z["nicht_verstanden"]),
        "dauer_sekunden": int(dauer),
        "erster": _durchgang(erster),
        "zweiter": _durchgang(zweiter),
    })
    return gesamt


def _als_wb(z):
    if isinstance(z, dict):
        return {
            "rolle": z.get("rolle"), "text": z.get("text", ""),
            "phase": z.get("phase", AUFGABE),
            "nicht_verstanden": bool(z.get("nicht_verstanden")),
            "zeit": z.get("zeit"), "korrektur": z.get("korrektur", ""),
        }
    return {
        "rolle": z.role, "text": z.text, "phase": z.phase,
        "nicht_verstanden": z.not_understood, "zeit": z.created_at,
        "korrektur": z.correction,
    }


def zahl(wert, stellen=1):
    """Österreichisch: Komma statt Punkt."""
    return f"{wert:.{stellen}f}".replace(".", ",")


def dauer_text(sekunden):
    minuten, rest = divmod(int(sekunden), 60)
    return f"{minuten}:{rest:02d} min"


def zahlenzeile(m, ziel_erster=None, ziel_zweiter=None):
    """Die ruhige Zeile für die Lehrperson. Zahlen, keine Bewertung.

    Bewusst ohne Farben, ohne "gut" und "schlecht": Ein Kind, das im
    zweiten Durchgang weniger Wörter sagt, kann genauer geworden sein
    (Skehan: Trade-off innerhalb einer Aufgabe).
    """
    if not m["beitraege"] and not m["sperren"]:
        return []
    teile = [
        f"{zahl(m['woerter_je_beitrag'])} Wörter je Beitrag",
        f"{round(m['anteil_erweitert'] * 100)} % erweitert",
        f"{m['fragen']} {'Frage' if m['fragen'] == 1 else 'Fragen'}",
        f"{m['sperren']} {'Sperre' if m['sperren'] == 1 else 'Sperren'}",
        dauer_text(m["dauer_sekunden"]),
    ]
    if ziel_erster is not None:
        teile.append("Ziel erreicht" if ziel_erster else "Ziel nicht erreicht")
    if m["zweiter"]["beitraege"]:
        e, z = m["erster"], m["zweiter"]
        teile.append(
            f"1. → 2. Durchgang: {zahl(e['woerter_je_beitrag'])} → "
            f"{zahl(z['woerter_je_beitrag'])} Wörter je Beitrag"
        )
        if ziel_zweiter is not None:
            teile.append("beim 2. Mal Ziel erreicht" if ziel_zweiter
                         else "beim 2. Mal Ziel nicht erreicht")
    return teile


# --- Der Rückblick (Regel 6, zweiter Teil) --------------------------------
#
# Am Ende eine kurze Liste der zwei bis drei wichtigsten Punkte, die auch die
# Lehrperson sieht. Deterministisch gebaut, ohne Modell: aus dem, was das
# Kind gesagt hat, aus den beiläufigen Korrekturen des Coachs und aus den
# Redemitteln. Keine Note, keine Zahl für das Kind.
#
# Volksschule: nur positiv plus EIN Punkt (Lehrplan VS: Korrektheit nicht
# notenrelevant; BIG 2015: „positive Verstärkungen und differenzierende
# Würdigungen").

HOECHSTENS_PUNKTE = 3

GUT = "gut"
BESSER = "besser"


def _benutzt(text, wendung):
    """Steckt die Wendung (ohne Auslassungspunkte) im Text?"""
    kern = re.split(r"\.\.\.|…", wendung)[0]
    kern = sprechaufgaben._normal(kern).strip()
    if len(kern.split()) < 2:
        return False
    return " " + kern + " " in sprechaufgaben._normal(text)


def rueckblick(zuege, aufgabe, altersklasse):
    """Die Punkte für den Rückblick, höchstens drei.

    Jeder Punkt: art ("gut"/"besser"), deutsch (die Erklärung), englisch
    (die Wendung), vorher (was das Kind gesagt hatte, nur bei "besser" und
    nicht in der Volksschule).
    """
    zuege = [_als_wb(z) for z in zuege]
    volksschule = ist_volksschule(altersklasse)

    gesperrt = set()
    for i, z in enumerate(zuege):
        if z["rolle"] == "coach" and z["nicht_verstanden"] and i > 0:
            gesperrt.add(i - 1)
    kind = [z["text"].strip() for i, z in enumerate(zuege)
            if z["rolle"] == "lernend" and i not in gesperrt and z["text"].strip()]

    # Korrekturen: Der Coachzug traegt die bessere Fassung des Beitrags
    # davor. Die juengsten zuerst, jede Fassung nur einmal.
    korrekturen = []
    for i, z in enumerate(zuege):
        if z["rolle"] == "coach" and z.get("korrektur") and i > 0:
            vorher = zuege[i - 1]
            if vorher["rolle"] == "lernend":
                korrekturen.append((vorher["text"].strip(), z["korrektur"].strip()))
    korrekturen.reverse()

    gute = []
    # Zuerst: eine Wendung aus den Redemitteln, die das Kind selbst benutzt
    # hat. Das ist der Punkt, den die Planung vorbereitet hat.
    for wendung in aufgabe.get("redemittel", ()):
        treffer = next((t for t in kind if _benutzt(t, wendung)), None)
        if treffer:
            gute.append({"art": GUT, "englisch": treffer,
                         "deutsch": "Diese Frage hast du gut gestellt:"
                         if ist_frage(treffer) else "Das hast du gut gesagt:"})
            break
    # Dann: der längste Beitrag, der nicht korrigiert wurde.
    korrigiert = {v for v, _ in korrekturen}
    laengste = sorted(
        (t for t in kind if t not in korrigiert and woerter(t) >= 3
         and all(t != g["englisch"] for g in gute)),
        key=woerter, reverse=True,
    )
    if laengste:
        gute.append({"art": GUT, "englisch": laengste[0],
                     "deutsch": "Dein längster Satz:"})

    besser = []
    for vorher, richtig in korrekturen:
        if sprechaufgaben._normal(vorher) == sprechaufgaben._normal(richtig):
            continue
        besser.append({"art": BESSER, "englisch": richtig,
                       "vorher": "" if volksschule else vorher,
                       "deutsch": "So sagt man es:"})
    # Ohne Korrektur: eine Wendung aus den Redemitteln, die noch nicht kam.
    if not besser:
        for wendung in aufgabe.get("redemittel", ()):
            if not any(_benutzt(t, wendung) for t in kind):
                besser.append({"art": BESSER, "englisch": wendung, "vorher": "",
                               "deutsch": "Probier beim nächsten Mal:"})
                break

    if volksschule:
        punkte = gute[:2] + besser[:1]
    else:
        punkte = gute[:1] + besser[:2]
    return punkte[:HOECHSTENS_PUNKTE]


def reflexionsfrage(aufgabe):
    """Die Reflexionsfrage nach Goh & Burns, nur wenn es zwei Durchgänge gab."""
    if sprechaufgaben.ist_frei(aufgabe):
        return ""
    return "Was war beim zweiten Mal leichter?"
