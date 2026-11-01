"""Die drei Fragen beim Anlegen einer Mathematikstunde, und was daraus wird.

Benchmark vom 19.10.2026 (docs/Mathe-Benchmark und Konfiguration.md,
Abschnitte 5.3, 6.2 und 6.3): Von allem, was die Lehrperson einstellen
konnte, hat nur die Obergrenze der Hilfen messbar etwas veraendert. Die
Altersklasse hat die Anrede veraendert und sonst nichts; die Fehler, die sie
beheben muesste, liegen in Anweisungen und Pruefung, die sie nie erreicht
hat. Deshalb stellt das Mathe-Formular genau drei Fragen:

  Fuer wen ist die Stunde?     Volksschule, Mittelstufe, Oberstufe (Pflicht)
  Was bekommen die Kinder?     Lernen (vorgewaehlt) oder Ueben
  Worum geht es heute?         ein Stichwort, freiwillig

Alles Weitere (Titel, Protokollstufe, Qualitaetssicherung, Ruhezeit) bleibt
in der Anwendung, aber eingeklappt und vorbelegt, in jedem Fach. Diese Datei
haelt die Texte und Zuordnungen dazu, damit views.py und die Vorlage sie
nicht jede fuer sich aufzaehlen. Keine Datenbank, keine Anfrage: alles hier
ist mit einem Wert pruefbar.
"""

from zoneinfo import ZoneInfo

from django.utils import timezone

from . import cloud, faecher, klassenbild, levels

# --- Frage 1: Fuer wen ist die Stunde? -------------------------------------
#
# Der Satz unter jeder Karte sagt, was die Wahl veraendert (Bericht 6.3).
# Alle drei stehen immer da, keiner wechselt: Verschwaenden nach der Wahl
# zwei der Saetze, rutschte am Handy alles darunter nach oben. "Nichts
# springt" wiegt schwerer als ein Satz, der wechselt.

SCHULSTUFEN = (
    {
        "schluessel": levels.VOLKSSCHULE,
        "name": "Volksschule",
        "zusatz": "",
        "satz": ("Die Hilfen sprechen mit Du, höchstens drei Sätze, "
                 "Rechenarten statt Fachwörter."),
    },
    {
        "schluessel": levels.MITTELSTUFE,
        "name": "Mittelstufe",
        "zusatz": "5. bis 8.",
        "satz": ("Die Hilfen sprechen mit Du, höchstens vier Sätze, "
                 "Fachwörter werden erklärt."),
    },
    {
        "schluessel": levels.OBERSTUFE,
        "name": "Oberstufe",
        "zusatz": "bis Matura",
        "satz": ("Die Hilfen sprechen mit Du, höchstens vier Sätze; sie "
                 "nennen die Grundkompetenz, nicht die Rechenart."),
    },
)

_SCHULSTUFE = {s["schluessel"]: s for s in SCHULSTUFEN}


def schulstufe_bekannt(schluessel):
    return schluessel in _SCHULSTUFE


def schulstufe_kurz(schluessel):
    """Der kurze Name fuer eine Marke ("Oberstufe"), oder leer."""
    eintrag = _SCHULSTUFE.get(schluessel)
    return eintrag["name"] if eintrag else ""


# --- Frage 2: Was bekommen die Kinder? -------------------------------------
#
# Zwei Antworten statt drei. "Loesung bei Bedarf" (die Loesung ohne
# Rueckfrage) entfaellt im Mathe-Formular: Bastani et al. 2025 zeigen, dass
# die ungeschuetzte Loesung schadet, und die Rueckfrage vor der Loesung ist
# seither fest. Die Einstellung bleibt in levels.py fuer alte Sitzungen.

LERNEN = levels.UMFANG_AUF_BITTE
UEBEN = levels.UMFANG_TIPPS
UMFANG_VORGABE = LERNEN

UMFANG_KARTEN = (
    {
        "schluessel": LERNEN,
        "name": "Lernen",
        "satz": ("Fünf Stufen bis zur Lösung. Die Lösung kommt erst, wenn "
                 "das Kind darum bittet, und erst nach Stufe 4."),
        # Fuenf Punkte, der letzte hohl: Die Loesung ist da, aber nicht
        # selbstverstaendlich.
        "punkte": klassenbild.punkte_zeichnen(
            [klassenbild.GEGEBEN] * 4 + [klassenbild.OFFEN]
        ),
    },
    {
        "schluessel": UEBEN,
        "name": "Üben",
        "satz": ("Nur Tipps, Stufe 1 bis 3. Keine Lösung, auch nicht auf "
                 "Nachfrage. Für Phasen, in denen Sie danebensitzen."),
        "punkte": klassenbild.punkte_zeichnen([klassenbild.GEGEBEN] * 3),
    },
)

for _karte in UMFANG_KARTEN:
    _karte["breite"] = klassenbild.breite(_karte["punkte"])

_UMFANG = {k["schluessel"]: k for k in UMFANG_KARTEN}


def umfang(schluessel):
    """Lernen oder Ueben. Alles andere ist Lernen, die Vorgabe.

    Ein nachgebautes Formular, das "bei_bedarf" schickt, bekommt nicht die
    Loesung ohne Rueckfrage, sondern das, was die Seite vorgewaehlt hatte.
    """
    if schluessel not in _UMFANG:
        schluessel = UMFANG_VORGABE
    return levels.umfang(schluessel)


def umfang_name(sitzung):
    """Wie die Obergrenze einer Sitzung auf einer Marke heisst."""
    if sitzung.max_level == levels.NUR_TIPPS:
        return "Üben"
    if sitzung.ask_before_solution:
        return "Lernen"
    # Nur noch bei Sitzungen von vor dem 19.10.2026.
    return "Lösung bei Bedarf"


# --- Die Marken: die Entscheidungen der Lehrperson in Kurzform -------------

def marken(sitzung):
    """Die Entscheidungen als kurze Marken, in der Reihenfolge der Fragen.

    Dieselbe Liste steht auf der Sitzungskarte der Uebersicht und ueber dem
    Klassenbild: Was die Lehrperson gewaehlt hat, soll sie an beiden Stellen
    in denselben Worten wiederfinden ("Oberstufe · Lernen · Thema: Brüche").
    """
    teile = []
    if sitzung.ist_sprechcoach:
        teile += [
            f"Niveau {sitzung.language_level}",
            sitzung.sprechaufgabe["titel"],
            sitzung.altersklasse_kurz,
        ]
    elif sitzung.ist_musik:
        teile += [
            f"Lieder bis {sitzung.song_max_seconds} s",
            f"{sitzung.songs_per_child} je Kind",
            f"gesungen auf {sitzung.get_song_language_display()}",
            sitzung.altersklasse_kurz,
        ]
    elif faecher.braucht(sitzung.subject, faecher.EINSTELLUNG_SCHULSTUFE):
        teile += [
            schulstufe_kurz(sitzung.schulstufe) or sitzung.altersklasse_kurz,
            umfang_name(sitzung),
        ]
    else:
        teile.append(sitzung.altersklasse_kurz)
        # Sitzungen von vor der Fachumstellung haben kein Fach. Der Umfang
        # ist dann das Einzige, was sich ueber sie sagen laesst.
        if faecher.fach(sitzung.subject) is None:
            teile.append(umfang_name(sitzung))
    if sitzung.ist_safechat:
        # Im Safe Chat heisst die Qualitaetssicherung fuer das Kind "Draussen
        # fragen". Ob der Knopf da ist, entscheiden Haken UND Zugang; die
        # Marke sagt, was die Kinder tatsaechlich sehen.
        teile.append(
            "Draußen fragen: ein"
            if sitzung.cloud_enabled and cloud.moeglich() else "Draußen fragen: aus"
        )
    if sitzung.task_hint:
        teile.append("Thema: " + sitzung.task_hint)
    return teile


# --- Der Titel, wenn die Lehrperson keinen tippt ---------------------------

WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
ORTSZEIT = ZoneInfo("Europe/Vienna")


def titel_vorschlag(fachname, jetzt=None):
    """"Mathematik, Mo 19. 10., 10:05": Fach, Wochentag, Datum und Uhrzeit.

    Der Titel war ein Pflichtfeld ohne didaktische Evidenz (Bericht 5.3).
    Jetzt ist er vorbelegt und hinterher auf der Sitzungsseite aenderbar.
    Oesterreichisches Datum ohne fuehrende Nullen, Ortszeit Wien, auch wenn
    der Server einmal woanders steht.
    """
    jetzt = timezone.localtime(jetzt, ORTSZEIT)
    return "{}, {} {}. {}., {:%H:%M}".format(
        fachname or "Sitzung", WOCHENTAGE[jetzt.weekday()],
        jetzt.day, jetzt.month, jetzt,
    )
