"""Nutzungskonzepte: wofür der Spark in einem Zeitraum gebucht wird.

WARUM EINE BUCHUNG WISSEN MUSS, WOFÜR SIE IST

Bisher stand in einer Buchung nur, wie viele Plätze jemand braucht. Das
genügt, solange alle dasselbe tun. Es genügt nicht mehr, sobald eine Buchung
den Rechner UMBAUT.

Der Spark hat Speicher für begrenzt viele Modelle. Die Regel im Projekt heißt
seit dem ersten Tag „ein Antwortmodell": Qwen schreibt; ein zweites Sprachmodell
läuft nur als Pförtner nebenher (Stufe B, :8004) und ersetzt es nie.
Daraus folgt der Satz, auf dem diese Datei steht:

    PLÄTZE ADDIEREN SICH, MODELLE NICHT.

Zwei Klassen, die beide die Unterrichtshilfe benutzen, teilen den Rechner –
25 Kinder sind im Schnitt gut ein Platz, gemessen über zehn Tage lag die
höchste echte Gleichzeitigkeit bei drei. Zwei Buchungen dagegen, von denen
eine ein anderes Modell braucht, teilen nichts: Die zweite kann erst
anfangen, wenn die erste aufgehört hat und der Speicher neu geladen ist. Das
ist keine Kapazitätsfrage, sondern eine Frage der Verträglichkeit, und sie
lässt sich nicht in Plätzen ausdrücken.

Deshalb trägt jedes Konzept, welche Modelle es braucht. Was in GELADEN steht,
ist ohne Umbau da; alles andere macht die Buchung für ihren Zeitraum
alleinig. Eine Buchung, die den Rechner umbaut und das nicht sagt, nimmt
einer Schulklasse mitten in der Stunde das Modell weg.

WAS EIN KONZEPT SONST FESTLEGT

Den Anteil, den es höchstens vom Ganzen nimmt, und ob der Weg nach draußen
erlaubt ist. Das zweite ist keine Einstellung, sondern bei manchen Konzepten
der Zweck: „Sichere Verwaltung" heißt, dass personenbezogene Daten den
Rechner nicht verlassen. Ein Haken, mit dem sich die Qualitätssicherung
dazuschalten lässt, wäre dort genau die Tür, die zugemauert sein soll.
"""

from django.conf import settings

# --- Die Modelle, um die es geht -----------------------------------------
#
# Schlüssel und nicht Dateinamen: Was unter "text" läuft, hat schon zweimal
# gewechselt, und die Konzepte sollen davon nichts merken.

TEXT = "text"                  # seit 31.10.2026 Qwen3.6-35B-A3B, versteht auch Bilder
GEHOER = "gehoer"              # whisper-large-v3, Spracherkennung
STIMME = "stimme"              # noch nicht da, Port 8003 vorgesehen
EINBETTUNG = "einbettung"      # für Nachschlagen in eigenen Unterlagen
SCHULUNG = "schulung"          # Feinschliff eines Modells, belegt die GPU

# Die Profile des Brokers. Ein Profil ist das, was der Spark auf einmal
# laden kann; der Wechsel dauert ein bis vier Minuten und passiert nur an
# Slotgrenzen. Stand 11.10.2026 laut Spark-Betreuung:
#   qwen     text (:8000) + gehoer (:8002)     ~120 s
#   kreativ  gehoer (:8002), schaltet text ab  ~60 s  - voller Speicher fuer
#            ComfyUI (Bild, Video, Musik)
PROFIL_QWEN = "qwen"
# Das Profil gptoss (gpt-oss-120b allein, ~240 s) gibt es seit 13.11.2026 nicht
# mehr: 103 GB passten neben dem Pfoertner nicht mehr in den Speicher, und ein
# Wechsel haette den Pfoertner gestoppt. Kein Konzept hat es je gewaehlt.
PROFIL_KREATIV = "kreativ"


def geladen():
    """Was gerade ohne Umbau im Speicher liegt.

    Vom Broker am Spark, wenn er erreichbar ist - er ist die eine Stelle,
    die es weiss. Sonst aus der Umgebung (SPARK_GELADENE_MODELLE), und die
    nennt nur das Beobachtete: Am 04.10.2026 lieferte Port 8000 qwen3-vl-30b
    und Port 8002 whisper-large-v3. Was dort nicht steht, macht die
    betreffenden Buchungen alleinig. Im Zweifel ist das die richtige
    Richtung: Eine Buchung zu viel alleinig zu machen kostet einen Termin,
    eine zu wenig nimmt einer Schulklasse mitten in der Stunde das Modell.
    """
    from . import broker

    return broker.geladene_dienste()


def aktuelles_profil():
    from . import broker

    return broker.aktuelles_profil()

MODELL_NAME = {
    TEXT: "Sprachmodell",
    GEHOER: "Spracherkennung",
    STIMME: "Sprachausgabe",
    EINBETTUNG: "Nachschlagemodell",
    SCHULUNG: "Modellschulung",
}


# --- Die Konzepte ---------------------------------------------------------
#
# "symbol" ist der Name einer Linienzeichnung in
# plan/templates/plan/_konzeptsymbol.html, kein Zeichen: keine Emojis, unter
# keinen Umstaenden (Thomas, 12.10.2026).

KONZEPTE = (
    {
        "schluessel": "unterricht",
        "name": "Unterricht mit einer Klasse",
        "symbol": "tafel",
        "satz": "Das AI LAB im Unterricht: Aufgabenhilfe, Trainer, Sprechcoach. "
                "Mehrere Klassen gleichzeitig sind kein Problem.",
        "anteil": 60,
        "profil": PROFIL_QWEN,
        "modelle": frozenset({TEXT, GEHOER}),
        "cloud_erlaubt": True,
        # Der Normalfall. Plätze in Zehnerschritten, weil niemand weiss, ob
        # 23 oder 25 Kinder kommen, und die Genauigkeit nichts bringt: Eine
        # Klasse ist im Schnitt gut EIN Platz.
        "plaetze_schritt": 10,
        "braucht_schuelerzahl": True,
    },
    {
        "schluessel": "sichere_verwaltung",
        "name": "Sichere Verwaltung",
        "symbol": "schloss",
        "satz": "Personenbezogene Daten bearbeiten, ohne dass sie den Rechner "
                "verlassen. Kein Weg nach draußen, auch nicht zuschaltbar.",
        "anteil": 30,
        "profil": PROFIL_QWEN,
        "modelle": frozenset({TEXT}),
        # Das ist der Zweck und keine Einstellung: Hier gibt es die
        # Qualitaetssicherung nicht. Ein Schalter, der sie dazuschaltet, waere
        # genau die Tuer, die zugemauert sein soll - und ein Versehen genuegt,
        # damit ein Personalakt bei einem Anbieter in den USA liegt.
        "cloud_erlaubt": False,
        "plaetze_schritt": 1,
        "braucht_schuelerzahl": False,
    },
    {
        "schluessel": "kreativ",
        "name": "Bild, Video und Musik",
        "symbol": "pinsel",
        "satz": "Grosse Bild-, Video- und Musikläufe in ComfyUI. Braucht den "
                "ganzen Speicher, das Sprachmodell wird dafür entladen.",
        "anteil": 100,
        # Kein Sprachmodell, sondern dessen Abwesenheit: Das Profil "kreativ"
        # entlaedt Qwen, damit die Bild- und Videomodelle Platz haben. Die
        # Kleinen (ein Bild, ein kurzer Clip) laufen auch neben dem
        # Unterricht - dafuer bucht man nichts. Das hier ist fuer die Grossen.
        "profil": PROFIL_KREATIV,
        "modelle": frozenset({GEHOER}),
        "cloud_erlaubt": False,
        "plaetze_schritt": 1,
        "braucht_schuelerzahl": False,
    },
    {
        "schluessel": "wissensdienst",
        "name": "Eigene Unterlagen befragen",
        "symbol": "buecher",
        "satz": "Anleitungen und Erlässe in den Rechner legen, danach kann "
                "jeder dazu Fragen stellen. Braucht ein zweites Modell.",
        "anteil": 40,
        # Noch kein Profil am Spark, das ein Nachschlagemodell laedt. Die
        # Buchung ist deshalb alleinig, und das Vorheizen kann nichts
        # vorbereiten - die Seite sagt das dazu.
        "profil": None,
        # Das Nachschlagemodell liegt NICHT im Speicher. Diese Buchung baut
        # den Rechner also um und ist damit alleinig - das ist die Folge, die
        # sich nicht wegverhandeln laesst, und der Grund, warum das Konzept
        # in der Buchung stehen muss.
        "modelle": frozenset({TEXT, EINBETTUNG}),
        "cloud_erlaubt": False,
        "plaetze_schritt": 1,
        "braucht_schuelerzahl": False,
    },
    {
        "schluessel": "modellschulung",
        "name": "Ein Modell schulen",
        "symbol": "werkzeug",
        "satz": "Feinschliff mit eigenen Daten. Belegt den Rechner ganz, "
                "deshalb am besten ausserhalb der Unterrichtszeit.",
        "anteil": 100,
        "profil": None,
        "modelle": frozenset({SCHULUNG}),
        "cloud_erlaubt": False,
        "plaetze_schritt": 1,
        "braucht_schuelerzahl": False,
    },
    {
        "schluessel": "entwicklung",
        "name": "Entwicklung und Lasttest",
        "symbol": "kolben",
        "satz": "Das Lab. Darf absichtlich bis an den Rand füllen, damit "
                "gemessen ist, wo der Rand liegt.",
        "anteil": 100,
        "profil": PROFIL_QWEN,
        "modelle": frozenset({TEXT, GEHOER}),
        "cloud_erlaubt": True,
        "plaetze_schritt": 1,
        "braucht_schuelerzahl": False,
    },
)

NACH_SCHLUESSEL = {k["schluessel"]: k for k in KONZEPTE}

SCHLUESSEL = tuple(k["schluessel"] for k in KONZEPTE)

AUSWAHL = tuple((k["schluessel"], k["name"]) for k in KONZEPTE)

STANDARD = "unterricht"


def konzept(schluessel):
    """Das Konzept, oder None."""
    return NACH_SCHLUESSEL.get((schluessel or "").strip().lower())


def ist_bekannt(schluessel):
    return konzept(schluessel) is not None


def name(schluessel):
    gefunden = konzept(schluessel)
    return gefunden["name"] if gefunden else ""


def symbol(schluessel):
    """Der Name der Linienzeichnung (_konzeptsymbol.html), oder leer."""
    gefunden = konzept(schluessel)
    return gefunden["symbol"] if gefunden else ""


def anteil(schluessel):
    """Welchen Anteil am Ganzen dieses Konzept hoechstens nimmt, in Prozent."""
    gefunden = konzept(schluessel)
    return gefunden["anteil"] if gefunden else 0


def plaetze_schritt(schluessel):
    gefunden = konzept(schluessel)
    return (gefunden or {}).get("plaetze_schritt") or 1


def cloud_erlaubt(schluessel):
    """Darf in diesem Konzept die Qualitaetssicherung ueberhaupt an?

    Nicht "ist sie an", sondern "darf sie". Bei der sicheren Verwaltung ist
    die Antwort nein, und daran kann die Lehrperson nichts aendern.
    """
    gefunden = konzept(schluessel)
    return bool(gefunden and gefunden["cloud_erlaubt"])


def modelle(schluessel):
    gefunden = konzept(schluessel)
    return (gefunden or {}).get("modelle") or frozenset()


def profil(schluessel):
    """Das Brokerprofil, das dieses Konzept braucht, oder None.

    None heisst: Kein Profil am Spark laedt, was dieses Konzept braucht. Die
    Buchung geht trotzdem - alleinig -, aber das Vorheizen kann nichts
    vorbereiten, und die Seite sagt das dazu.
    """
    gefunden = konzept(schluessel)
    return (gefunden or {}).get("profil")


def braucht_umbau(schluessel):
    """Muss der Spark fuer dieses Konzept umgebaut werden?

    Wahr, sobald das Konzept ein Modell braucht, das nicht ohnehin im
    Speicher liegt - und, seit es den Broker gibt, auch dann, wenn es ein
    anderes Profil braucht als das geladene. Eine solche Buchung kann nicht
    neben einer anderen laufen - nicht weil die Plaetze knapp waeren, sondern
    weil der Speicher in der Zwischenzeit etwas anderes enthaelt.
    """
    if modelle(schluessel) - geladen():
        return True
    gewuenscht = profil(schluessel)
    return bool(gewuenscht) and gewuenscht != aktuelles_profil()


def ist_alleinig(schluessel):
    """Belegt dieses Konzept den Rechner allein?

    Zwei Gruende, und beide zaehlen: Es braucht den ganzen Anteil, oder es
    baut den Rechner um.
    """
    return anteil(schluessel) >= 100 or braucht_umbau(schluessel)


def vertraeglich(einer, anderer):
    """Koennen diese zwei Konzepte im selben Zeitraum laufen?

    Die Frage, die es vor den Nutzungskonzepten nicht gab. Vorher liess sich
    alles in Plaetzen beantworten: Was zusammen unter die Obergrenze passt,
    passt. Jetzt gibt es Paare, die auch bei zwei belegten Plaetzen von
    hundertzwanzig nicht zusammengehen.
    """
    if not (ist_bekannt(einer) and ist_bekannt(anderer)):
        return False
    if einer == anderer:
        # Dasselbe Konzept zweimal ist der Normalfall - zwei Klassen im
        # Unterricht - es sei denn, es belegt den Rechner ohnehin allein.
        return not ist_alleinig(einer)
    if ist_alleinig(einer) or ist_alleinig(anderer):
        return False
    # Beide kommen ohne Umbau aus, also liegen beide Modellmengen im
    # Speicher. Dann entscheidet wieder die Kapazitaet, und die rechnet die
    # Belegung aus.
    return True


def grund_unvertraeglich(neuer, bestehender, zeit):
    """Ein Satz, der erklaert, warum zwei Buchungen nicht zusammengehen.

    Fuer die Lehrperson vor der Seite, nicht fuers Protokoll. "Nicht
    vertraeglich" ist keine Auskunft; "dafuer muss der Rechner umgebaut
    werden" ist eine. `zeit` ist die Uhrzeit als Text, etwa "10:15".
    """
    if braucht_umbau(neuer):
        return (f"„{name(neuer)}“ braucht ein Modell, das erst geladen werden "
                f"muss. In dieser Zeit kann sonst nichts laufen, und um "
                f"{zeit} ist „{name(bestehender)}“ gebucht.")
    if braucht_umbau(bestehender):
        return (f"Um {zeit} ist „{name(bestehender)}“ gebucht. Dafür wird "
                f"der Rechner umgebaut, deshalb geht daneben nichts.")
    if anteil(bestehender) >= 100:
        return (f"Um {zeit} ist „{name(bestehender)}“ gebucht und belegt "
                f"den Rechner ganz.")
    return (f"„{name(neuer)}“ belegt den Rechner ganz, und um {zeit} ist "
            f"schon „{name(bestehender)}“ gebucht.")
