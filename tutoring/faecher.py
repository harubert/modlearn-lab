"""Die Fächer, aus denen die Lehrperson als Erstes eines wählt.

WARUM DAS FACH VORNE STEHT

Vorher stand alles auf einer Seite: acht Blöcke, darunter einer mit der
Aufschrift „Nur für den Sprechcoach" und einer mit „Gilt nur für die
Aufgabenhilfe". Das Formular hat der Lehrperson also mitgeteilt, welche
Hälfte sie überlesen soll. Wer zum ersten Mal davorsitzt, kann nicht wissen,
was „Betriebsart" bedeutet, und muss es auch nicht wissen: Niemand unterrichtet
eine Betriebsart. Unterrichtet wird ein Fach.

Deshalb ist das Fach jetzt die Abzweigung. Es bestimmt, welche Betriebsart
läuft und welche Einstellungen überhaupt erscheinen. Die Betriebsart wird
nicht mehr gewählt, sie folgt.

WIE EIN FACH DAZUKOMMT

Eine Zeile in FAECHER. Dort steht, was das Fach an Einstellungen braucht;
die Seite richtet sich danach, und die Ansicht nimmt nur diese Felder an.
Was ein Fach nicht braucht, kann über das Formular auch nicht hineingeraten.

Bewusst keine Schaltfläche für ein Fach, hinter dem nichts steht: Zehn Fächer
anzubieten und acht davon in denselben allgemeinen Trainer zu schicken, wäre
ein Versprechen, das die Anwendung nicht hält.
"""

from . import sprechcoach

# Die Betriebsarten, auf die ein Fach führt. Dieselben Werte wie in
# LearningSession.mode - hier nur noch einmal benannt, damit diese Datei ohne
# das Modell lesbar ist.
HILFE = "hilfe"
TRAINER = "trainer"
SPRACHE = "sprache"
MUSIK = "musik"
CHAT = "chat"

# Die Einstellungen, die ein Fach brauchen kann. Jeder Schlüssel schaltet in
# der Vorlage einen Block ein und in der Ansicht die Annahme eines Feldes.
EINSTELLUNG_SCHULSTUFE = "schulstufe"  # Fuer wen ist die Stunde? (Mathematik)
EINSTELLUNG_STUFEN = "stufen"          # Was bekommen die Kinder: Lernen oder Ueben?
EINSTELLUNG_NIVEAU = "niveau"          # A1 bis B2
EINSTELLUNG_THEMA = "thema"            # Worum geht es in dieser Stunde?
EINSTELLUNG_AUFGABE = "aufgabe"        # Gesprächsaufgabe (sprechaufgaben.py)
EINSTELLUNG_ALTER = "alter"            # Altersklasse
EINSTELLUNG_PROTOKOLL = "protokoll"    # Forschungsstufe
EINSTELLUNG_QUALITAET = "qualitaet"    # Qualitätssicherung
EINSTELLUNG_RUHEZEIT = "ruhezeit"      # Verfall bei Stille
EINSTELLUNG_LIEDDAUER = "lieddauer"    # Hoechstdauer je Lied (Musik)
EINSTELLUNG_LIEDER = "lieder"          # Lieder je Kind (Musik)
EINSTELLUNG_GESANG = "gesang"          # Sprache des Gesangs (Musik)
EINSTELLUNG_TEXTHILFE = "texthilfe"    # Textvorschlag vom Spark (Musik)

# Was jedes Fach bekommt, ohne es aufzuzählen: Alter, Protokollstufe und
# Ruhezeit gelten in jedem Fach, die Qualitätssicherung ebenfalls.
IMMER = (
    EINSTELLUNG_ALTER,
    EINSTELLUNG_QUALITAET,
    EINSTELLUNG_PROTOKOLL,
    EINSTELLUNG_RUHEZEIT,
)

# Das Symbol ist der Name einer Linienzeichnung in
# tutoring/templates/tutoring/_fachsymbol.html, kein Zeichen. Bis 12.10.2026
# standen hier Emojis; Thomas: keine Emojis, unter keinen Umstaenden. Eine
# Zeichnung in currentColor sieht ausserdem auf jedem Geraet gleich aus, ein
# Emoji je nach Hersteller anders (die Flagge erscheint unter Windows als
# zwei Buchstaben "GB").

FAECHER = (
    {
        "schluessel": "mathematik",
        "name": "Mathematik",
        "symbol": "rechnen",
        "satz": "Die Kinder tippen oder fotografieren eine Aufgabe und "
                "bekommen gestufte Hilfen – nie die Lösung zuerst.",
        "betriebsart": HILFE,
        # Drei Fragen, sonst nichts (Benchmark vom 19.10.2026, Abschnitt 6.2):
        # Fuer wen ist die Stunde, was bekommen die Kinder, worum geht es.
        # Die Schulstufe ersetzt die Altersklasse, weil sie Anweisungen,
        # Pruefung und Diagnose steuert und nicht nur die Anrede; die
        # Altersklasse wird aus ihr abgeleitet (levels.altersklasse_fuer).
        "einstellungen": (EINSTELLUNG_SCHULSTUFE, EINSTELLUNG_STUFEN,
                          EINSTELLUNG_THEMA),
        "ohne": (EINSTELLUNG_ALTER,),
        "thema_beispiel": "Sachaufgaben mit Geld",
        # Die dritte Frage, in den Worten des Berichts. Die anderen Faecher
        # behalten die allgemeine Beschriftung aus der Vorlage.
        "thema_frage": "Worum geht es heute?",
        "thema_hilfe": "Hilft der Anwendung, den Fehler eines Kindes zu erkennen.",
        # Steht unter dem Satz, sobald das Fach gewaehlt ist: was die Kinder
        # sehen und was die Lehrperson im Klassenbild davon hat.
        "erklaerung": (
            "Das Kind hat zwei Knöpfe: „Das ist mein Versuch“ und „Ich habe "
            "eine Frage“. Nach jedem Versuch prüft die Anwendung selbst, ob "
            "das Ergebnis stimmt. Stimmt es, wird es bestätigt; sonst kommt "
            "die nächste Hilfe von selbst, und die Diagnose nennt den Fehler "
            "im Klartext, etwa „Zähler und Nenner getrennt addiert“. Genau "
            "diese Zeile sehen Sie im Klassenbild unter jedem Kind."
        ),
    },
    {
        "schluessel": "deutsch",
        "name": "Deutsch",
        "symbol": "buch",
        "satz": "Der Trainer erklärt ein Thema in kleinen Schritten und "
                "stellt immer genau eine Frage.",
        "betriebsart": TRAINER,
        "einstellungen": (EINSTELLUNG_THEMA,),
        "thema_beispiel": "Wörtliche Rede und ihre Zeichen",
    },
    {
        "schluessel": "englisch",
        "name": "Englisch",
        "symbol": "sprechblase",
        "satz": "Ein Gespräch auf Englisch. Die Kinder sprechen, der Coach "
                "antwortet – und versteht nur Englisch.",
        "betriebsart": SPRACHE,
        "sprache": "en-GB",
        "einstellungen": (EINSTELLUNG_NIVEAU, EINSTELLUNG_AUFGABE, EINSTELLUNG_THEMA),
        "thema_beispiel": "My family and my pets",
    },
    {
        "schluessel": "sachunterricht",
        "name": "Sachunterricht",
        "symbol": "globus",
        "satz": "Der Trainer erklärt ein Thema in kleinen Schritten und "
                "stellt immer genau eine Frage.",
        "betriebsart": TRAINER,
        "einstellungen": (EINSTELLUNG_THEMA,),
        "thema_beispiel": "Der Wasserkreislauf",
    },
    {
        "schluessel": "musik",
        "name": "Musik",
        "symbol": "note",
        "satz": "Die Kinder schreiben einen Liedtext zum Thema der Stunde oder "
                "lassen sich einen vorschlagen, wählen einen Stil, und der "
                "Spark macht daraus ein Lied.",
        "betriebsart": MUSIK,
        "einstellungen": (EINSTELLUNG_THEMA, EINSTELLUNG_LIEDDAUER,
                          EINSTELLUNG_LIEDER, EINSTELLUNG_GESANG,
                          EINSTELLUNG_TEXTHILFE),
        # Die Qualitaetssicherung prueft Loesungswege. In einer Musikstunde
        # gibt es keinen, und die Liedtexte sollen den Spark nicht verlassen:
        # Ein Haken, hinter dem nichts Sinnvolles steht, waere eine Zusage,
        # die niemand einhaelt.
        "ohne": (EINSTELLUNG_QUALITAET,),
        "thema_beispiel": "Ein Lied über unseren Schulweg",
        # Steht unter dem Satz, sobald das Fach gewaehlt ist. Die Lehrperson
        # soll vor dem Anlegen wissen, wohin die Texte gehen, wann sie weg
        # sind und warum ein Lied auf sich warten laesst.
        "erklaerung": (
            "Die Kinder schreiben zum Thema der Stunde einen Liedtext selbst "
            "oder lassen sich vom Sprachmodell am Spark einen Vorschlag "
            "schreiben, den sie ändern können (abschaltbar). Dann wählen sie "
            "einen Stil aus über dreißig, von Kinderlied und Schlaflied über "
            "Pop, Rap und Rock bis Blasmusik und Filmmusik, oder beschreiben "
            "einen eigenen, und bekommen ein Lied bis zur eingestellten Dauer. "
            "Gerechnet wird mit ACE-Step 1.5 (Lizenz MIT) auf dem Spark der "
            "PH: Die Liedtexte bleiben dort und gehen nicht hinaus, eine "
            "Qualitätssicherung gibt es in diesem Fach nicht. Mit dem Ende der "
            "Sitzung werden alle Lieder gelöscht, bei uns und am Spark. Der "
            "Spark rechnet ein Lied nach dem anderen: Schicken 25 Kinder "
            "zugleich ab, warten die letzten einige Minuten, und jedes Kind "
            "sieht, an welcher Stelle sein Lied steht."
        ),
    },
    {
        # Thomas (23.10.2026): "Diese Art heisst einfach Safe Chat." Inhaltlich
        # offen, Antwort vom Spark; ein Knopf schickt eine Frage nach draussen,
        # aber nur durch den Filter am Spark, und jeder Schritt dieses Weges
        # steht fuer Kind und Lehrperson sichtbar im Chat.
        "schluessel": "safechat",
        "name": "Safe Chat",
        "symbol": "schild",
        "satz": "Ein offener Chat mit der KI am Spark. Auf Wunsch geht eine "
                "Frage nach draußen – durch den Filter, mit vollem Protokoll.",
        "betriebsart": CHAT,
        "einstellungen": (EINSTELLUNG_THEMA,),
        "thema_beispiel": "Fragen zum Referat über Vulkane",
        "thema_frage": "Worum darf es gehen?",
        "thema_hilfe": "Freiwillig. Der Chat ist offen; das Thema steht nur als Hinweis über dem Gespräch.",
        "erklaerung": (
            "Die Kinder schreiben, was sie wollen, und bekommen eine Antwort "
            "vom Sprachmodell am Spark. Jeder Beitrag bekommt eine Ampel; "
            "Beleidigungen werden nicht beantwortet. Mit dem zweiten Knopf "
            "„Draußen fragen“ geht ein Beitrag an OpenAI – vorher schreibt der "
            "Spark ihn ohne Personen neu, erkennt und ersetzt, was trotzdem "
            "dasteht, und prüft, dass nichts durchrutscht. Kind und "
            "Lehrperson sehen zu jedem solchen Beitrag das ganze Protokoll: "
            "den eigenen Text, die Umformulierung, was hinausging, was "
            "zurückkam, was daraus wurde, und das Urteil der Gegenstelle, ob "
            "sie einen Personenbezug gesehen hat. Ohne eingerichteten "
            "Zugang (Qualitätssicherung) gibt es den zweiten Knopf nicht."
        ),
    },
)

NACH_SCHLUESSEL = {f["schluessel"]: f for f in FAECHER}

SCHLUESSEL = tuple(f["schluessel"] for f in FAECHER)

# Fuer das Feld in der Datenbank.
AUSWAHL = tuple((f["schluessel"], f["name"]) for f in FAECHER)


def fach(schluessel):
    """Das Fach, oder None. Kein Standardfach.

    Ohne Fach wird nichts angezeigt - das ist die Vorgabe und nicht ein
    Mangel. Ein stillschweigend vorausgewaehltes Fach waere genau die alte
    Falle: Die Lehrperson legt eine Mathematikstunde an, ohne es zu merken.
    """
    return NACH_SCHLUESSEL.get((schluessel or "").strip().lower())


def ist_bekannt(schluessel):
    return fach(schluessel) is not None


def braucht(schluessel, einstellung):
    """Gehoert diese Einstellung in dieses Fach?

    Die eine Stelle, an der Vorlage und Ansicht sich einig sein muessen. Ein
    Feld, das die Seite nicht zeigt, darf die Ansicht nicht annehmen: Sonst
    schickt ein Formular aus dem Browser doch wieder eine Stufenobergrenze
    in eine Englischstunde.
    """
    gefunden = fach(schluessel)
    if gefunden is None:
        return False
    # "ohne" nimmt etwas aus IMMER heraus. Selten, deshalb keine eigene Liste
    # je Fach fuer alles: Vier von fuenf Faechern wollen genau IMMER.
    if einstellung in gefunden.get("ohne", ()):
        return False
    return einstellung in gefunden["einstellungen"] or einstellung in IMMER


def betriebsart(schluessel):
    gefunden = fach(schluessel)
    return gefunden["betriebsart"] if gefunden else HILFE


def sprache(schluessel):
    """Die Zielsprache des Fachs, oder der Standard.

    Steht beim Fach und nicht in einem Auswahlfeld: Wer Englisch unterrichtet,
    soll nicht noch die Sprache angeben muessen. Ein zweites Sprachfach ist
    eine Zeile in FAECHER, keine neue Einstellung.
    """
    gefunden = fach(schluessel)
    return (gefunden or {}).get("sprache") or sprechcoach.SPRACHE_STANDARD


def name(schluessel):
    gefunden = fach(schluessel)
    return gefunden["name"] if gefunden else ""


def symbol(schluessel):
    """Der Name der Linienzeichnung (_fachsymbol.html), oder leer."""
    gefunden = fach(schluessel)
    return gefunden["symbol"] if gefunden else ""
