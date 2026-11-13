"""Konzept B als Systemdiagramm: zwei SVG-Dateien (hell, dunkel) fuer das README.

    python docs/diagramme/konzept_b.py
    python docs/diagramme/konzept_b.py --pruefen VERZEICHNIS   # Laufwege sichtbar

Schreibt docs/diagramme/konzept_b.svg und docs/diagramme/konzept_b_dunkel.svg
aus denselben Koordinaten; nur die Farbtokens unterscheiden sich. Keine
Abhaengigkeiten, kein JavaScript, keine Webfonts: GitHub zeigt SVG als Bild,
und dort laufen nur SMIL-Animationen (animateMotion, animate). Ohne
Animation ist das Bild vollstaendig; die Punkte zeigen nur den Weg, den
die Pfeile ohnehin beschreiben.

Beschriftung Englisch wie das oeffentliche README. Keine Adressen des
Tailnets (die Exportpruefung verbietet sie), nur Ports.

Farben sind die Tokens aus static/css/app.css: PH-Blau als Akzent, und der
Akzent sitzt nur dort, wo Konzept B sich von Konzept A unterscheidet: beim
Pfoertner und beim festen Satz.
"""

import pathlib
import xml.etree.ElementTree as ET

HIER = pathlib.Path(__file__).resolve().parent
W, H = 1200, 900
SCHRIFT = "system-ui, 'Segoe UI', Helvetica, Arial, sans-serif"

HELL = {
    "grund": "#ffffff", "zone": "#f8f9fb", "zone_rand": "#cfd6e0",
    "flaeche": "#ffffff", "rand": "#c7cfdb", "schrift": "#1a2230", "leise": "#545f71",
    "akzent": "#254287", "akzent_stark": "#1b3369", "akzent_leise": "#e7ecf6",
    "gruen": "#1d7a4a", "gelb": "#c08a00", "rot": "#a52a24", "weiss": "#ffffff",
}
DUNKEL = {
    "grund": "#131922", "zone": "#171e29", "zone_rand": "#2d3845",
    "flaeche": "#1b232e", "rand": "#34404f", "schrift": "#e9eef5", "leise": "#a4b0bf",
    "akzent": "#9db6e8", "akzent_stark": "#c3d3f3", "akzent_leise": "#1e2b41",
    "gruen": "#63c58f", "gelb": "#e2b53d", "rot": "#f08079", "weiss": "#131922",
}

WARNUNGEN = []


def breite(text, groesse):
    """Grobe Textbreite in px fuer Systemschriften (Segoe UI, Helvetica)."""
    w = 0.0
    for ch in text:
        if ch in "iljtf.,:;'|!I ":
            w += 0.30
        elif ch in "mwMW":
            w += 0.85
        elif ch.isupper() or ch.isdigit():
            w += 0.62
        else:
            w += 0.55
    return w * groesse


def passt(text, groesse, hoechstens, wo):
    """20 % Reserve, weil Systemschriften unterschiedlich breit laufen."""
    if breite(text, groesse) * 1.2 > hoechstens:
        WARNUNGEN.append(f"{wo}: '{text}' braucht {breite(text, groesse) * 1.2:.0f} px, Platz {hoechstens:.0f}")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Bild:
    def __init__(self, farben):
        self.f = farben
        self.teile = []

    def roh(self, s):
        self.teile.append(s)

    def text(self, x, y, s, groesse=13, farbe="schrift", gewicht="normal", anker="start",
             platz=None, wo="", abstand=None, kursiv=False):
        if platz is not None:
            passt(s, groesse, platz, wo or s[:20])
        extra = f' letter-spacing="{abstand}"' if abstand else ""
        extra += ' font-style="italic"' if kursiv else ""
        self.roh(f'<text x="{x}" y="{y}" font-size="{groesse}" font-weight="{gewicht}" '
                 f'fill="{self.f[farbe]}" text-anchor="{anker}"{extra}>{esc(s)}</text>')

    def zone(self, x, y, w, h, titel, gestrichelt=False):
        strich = ' stroke-dasharray="7 6"' if gestrichelt else ""
        self.roh(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{self.f["zone"]}" '
                 f'stroke="{self.f["zone_rand"]}" stroke-width="1.2"{strich}/>')
        self.text(x + 14, y + 22, titel.upper(), 11.5, "leise", "600", platz=w - 28, wo="Zone", abstand="0.08em")

    def kasten(self, x, y, w, h, titel, zeilen=(), akzent=False, titelgroesse=14, zeilengroesse=12.5,
               gestrichelt=False, zeilen_ab=None):
        fuell = self.f["akzent_leise"] if akzent else self.f["flaeche"]
        rand = self.f["akzent"] if akzent else self.f["rand"]
        dicke = 2 if akzent else 1.2
        strich = ' stroke-dasharray="6 5"' if gestrichelt else ""
        self.roh(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fuell}" '
                 f'stroke="{rand}" stroke-width="{dicke}"{strich}/>')
        farbe_titel = "akzent_stark" if akzent else "schrift"
        self.text(x + 14, y + 22, titel, titelgroesse, farbe_titel, "600", platz=w - 28, wo=titel)
        oben = zeilen_ab if zeilen_ab is not None else y + 44
        for i, z in enumerate(zeilen):
            self.text(x + 14, oben + i * 17, z, zeilengroesse, "schrift" if akzent else "leise",
                      platz=w - 28, wo=titel)

    def ampel(self, x, y):
        for i, farbe in enumerate(("gruen", "gelb", "rot")):
            self.roh(f'<circle cx="{x + i * 14}" cy="{y}" r="5" fill="{self.f[farbe]}"/>')

    def pfeil(self, punkte, beide=False, gestrichelt=False, akzent=False):
        d = "M " + " L ".join(f"{px},{py}" for px, py in punkte)
        farbe = self.f["akzent"] if akzent else self.f["leise"]
        marker = "akzent" if akzent else "neutral"
        strich = ' stroke-dasharray="6 5"' if gestrichelt else ""
        anfang = f' marker-start="url(#pf-{marker})"' if beide else ""
        self.roh(f'<path d="{d}" fill="none" stroke="{farbe}" stroke-width="1.6"{strich} '
                 f'marker-end="url(#pf-{marker})"{anfang}/>')

    def beschriftung(self, x, y, s, platz, anker="middle"):
        self.text(x, y, s, 11.5, "leise", anker=anker, platz=platz, wo="Pfeil")

    def schritt(self, x, y, n):
        self.roh(f'<circle cx="{x}" cy="{y}" r="10" fill="{self.f["akzent"]}" stroke="{self.f["grund"]}" stroke-width="2"/>')
        self.roh(f'<text x="{x}" y="{y + 4}" font-size="11.5" font-weight="700" fill="{self.f["weiss"]}" '
                 f'text-anchor="middle">{n}</text>')

    def punkt(self, pfad, dauer, beginn, farbwechsel=None):
        """Ein wandernder Punkt. farbwechsel = (anteil, farbe): ab dort Akzent."""
        f = self.f
        self.roh(f'<circle r="5" fill="{f["leise"]}" stroke="{f["grund"]}" stroke-width="1.5" opacity="0">')
        self.roh(f'  <animateMotion dur="{dauer}s" begin="{beginn}s" repeatCount="indefinite" path="{pfad}"/>')
        self.roh(f'  <animate attributeName="opacity" dur="{dauer}s" begin="{beginn}s" repeatCount="indefinite" '
                 f'values="0;1;1;0" keyTimes="0;0.04;0.95;1"/>')
        if farbwechsel:
            anteil, farbe = farbwechsel
            self.roh(f'  <animate attributeName="fill" dur="{dauer}s" begin="{beginn}s" repeatCount="indefinite" '
                     f'calcMode="discrete" values="{f["leise"]};{f[farbe]}" keyTimes="0;{anteil}"/>')
        self.roh("</circle>")

    def svg(self):
        f = self.f
        kopf = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="{SCHRIFT}" role="img" aria-labelledby="titel beschreibung">\n'
            '<title id="titel">Concept B: one model writes, a second one judges</title>\n'
            '<desc id="beschreibung">A child on a phone sends a contribution over HTTPS to the web server. '
            'The server runs deterministic checks while a separate gatekeeper model on the model host judges '
            'whether the contribution belongs to the lesson. A no is answered by a fixed sentence written by the '
            'server; yes or unclear goes to the main model, which writes the help, followed by output checks.</desc>\n'
            '<defs>\n'
            f'<marker id="pf-neutral" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" '
            f'markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 z" fill="{f["leise"]}"/></marker>\n'
            f'<marker id="pf-akzent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" '
            f'markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 z" fill="{f["akzent"]}"/></marker>\n'
            '</defs>\n'
            f'<rect width="{W}" height="{H}" rx="16" fill="{f["grund"]}"/>\n'
        )
        return kopf + "\n".join(self.teile) + "\n</svg>\n"


def zeichnen(farben, pruefmodus=False):
    b = Bild(farben)

    # Kopf
    b.text(24, 44, "Concept B: one model writes, a second one judges", 22, "schrift", "600", platz=900)
    b.text(24, 68, "ModLearn Lab · the path of one contribution in a lesson · "
           "the model host is never reachable from the internet", 13, "leise", platz=1100)

    # Zonen
    b.zone(24, 96, 266, 360, "Public internet")
    b.zone(24, 560, 266, 192, "Optional: quality assurance", gestrichelt=True)
    b.zone(330, 96, 400, 656, "Web server · the only machine learners talk to")
    b.zone(770, 96, 406, 656, "Model host · DGX Spark · private network only")

    # Links: Kind, Lehrperson, Frontier-Modell
    b.kasten(40, 140, 234, 98, "Child on a phone",
             ["writes, photographs or", "dictates a task,", "reads the help"])
    b.kasten(40, 290, 234, 134, "Teacher",
             ["starts the lesson, sets the", "help limit and lesson type,", "switches quality assurance",
              "on or off, reads every turn"])
    b.kasten(40, 600, 234, 118, "External frontier model",
             ["optional, OpenAI-compatible,", "gets the task text only:", "rewritten without persons,",
              "masked and leak-checked"], gestrichelt=True)

    # Mitte: Webserver
    b.roh(f'<rect x="346" y="174" width="368" height="30" rx="7" fill="{farben["flaeche"]}" '
          f'stroke="{farben["rand"]}" stroke-width="1.2"/>')
    b.text(530, 194, "Caddy · reverse proxy · HTTPS with TLS", 12, "leise", anker="middle", platz=340)

    b.roh(f'<rect x="346" y="212" width="368" height="386" rx="9" fill="{farben["flaeche"]}" '
          f'stroke="{farben["rand"]}" stroke-width="1.2"/>')
    b.text(362, 234, "Django application", 14, "schrift", "600", platz=200)
    b.text(698, 234, "server-rendered, HTMX, SSE", 11.5, "leise", anker="end", platz=180)

    # Unterkaesten: Titel oben, Text unten, eine freie Spur in der Mitte fuer die Punkte
    b.kasten(362, 262, 336, 64, "Deterministic checks", ["traffic light, bare numbers, quotes"],
             titelgroesse=13, zeilengroesse=12, zeilen_ab=262 + 52)
    b.ampel(600, 282)
    b.kasten(362, 340, 336, 78, "Fixed sentence, written by the server",
             ["when the judge says no: the same sentence", "per subject, no model text at all"],
             akzent=True, titelgroesse=13, zeilengroesse=12, zeilen_ab=340 + 50)
    b.kasten(362, 432, 336, 78, "Output checks",
             ["no solution before the last level,", "no invented quotes, no narrowing question"],
             titelgroesse=13, zeilengroesse=12, zeilen_ab=432 + 50)
    b.kasten(362, 524, 336, 66, "Safe chat",
             ["checks the answer for the form of a political", "refusal, not for its topic"],
             titelgroesse=13, zeilengroesse=12, zeilen_ab=524 + 42)

    b.kasten(346, 612, 120, 72, "PostgreSQL", ["sessions, tasks,", "protocol"], titelgroesse=13, zeilengroesse=12)
    b.kasten(482, 612, 232, 72, "Research protocol, 3 levels",
             ["operation: counts, no text", "masked or full, set per lesson"], titelgroesse=13, zeilengroesse=12)
    b.kasten(346, 698, 368, 46, "Model watch", ["daily check of the model registries"],
             titelgroesse=13, zeilengroesse=12, zeilen_ab=698 + 38)

    # Rechts: Modellrechner
    b.kasten(786, 140, 374, 122, "Qwen3.6-35B-A3B · port 8000",
             ["writes: diagnosis, help levels 1 to 5,", "coach turns; reads text and images",
              "(vLLM, OpenAI-compatible chat API)"])
    b.kasten(786, 300, 374, 144, "Gatekeeper · Ministral 3 8B · port 8004",
             ["judges one question only: does this", "belong to the lesson? Yes, no or unclear.",
              "It never writes a word for the child.", "Unreachable means unclear: the question passes."],
             akzent=True)
    b.kasten(786, 480, 178, 66, "Whisper · port 8002", ["speech recognition"], titelgroesse=13)
    b.kasten(982, 480, 178, 66, "Qwen3-TTS · port 8003", ["server voice"], titelgroesse=13)
    b.text(786, 614, "128 GB unified memory: the writing model and the judge", 12, "leise", platz=374)
    b.text(786, 632, "are loaded side by side. Concept A would let the main", 12, "leise", platz=374)
    b.text(786, 650, "model judge its own lesson boundary; B separates the two.", 12, "leise", platz=374)

    # Pfeile
    b.pfeil([(274, 189), (346, 189)])
    b.beschriftung(310, 181, "HTTPS", 70)
    b.pfeil([(346, 215), (274, 215)])
    b.beschriftung(310, 230, "answer", 70)
    b.pfeil([(274, 350), (346, 350)])
    b.beschriftung(310, 342, "settings", 70)

    b.pfeil([(714, 236), (786, 236)])
    b.beschriftung(750, 228, "request", 70)
    b.pfeil([(786, 252), (714, 252)])
    b.beschriftung(750, 267, "answer", 70)

    b.pfeil([(714, 333), (786, 333)], akzent=True)
    b.beschriftung(750, 325, "question", 70)
    b.pfeil([(786, 405), (714, 405)], akzent=True)
    b.beschriftung(750, 420, "verdict", 70)

    b.pfeil([(714, 513), (786, 513)], beide=True)
    b.beschriftung(750, 505, "audio", 70)
    b.pfeil([(714, 540), (750, 540), (750, 572), (1071, 572), (1071, 548)], beide=True)
    b.beschriftung(910, 586, "speech", 80)

    b.pfeil([(346, 560), (310, 560), (310, 659), (274, 659)], beide=True, gestrichelt=True)

    # Schritte
    # Die Marken sitzen 8 px eingerueckt, damit die Spur der Punkte (x = 352)
    # links daran vorbeikommt.
    b.schritt(40, 140, 1)
    b.schritt(370, 262, 2)
    b.schritt(786, 300, 2)
    b.schritt(370, 340, 3)
    b.schritt(786, 140, 4)
    b.schritt(370, 432, 4)
    b.schritt(40, 290, 5)
    b.schritt(490, 612, 5)

    # Legende
    b.text(24, 792, "What concept B means", 14, "schrift", "600", platz=560)
    legende = [
        "Two models with two jobs. Qwen writes the help; Ministral only judges whether a",
        "contribution belongs to the lesson. A no is answered with a fixed sentence the server",
        "writes, never a model. Yes and unclear go to Qwen; if the judge is unreachable, the",
        "question passes. Ports on the model host: 8000 chat, 8002 speech recognition,",
        "8003 voice, 8004 gatekeeper. Nothing on that machine is reachable from the internet.",
    ]
    for i, z in enumerate(legende):
        b.text(24, 814 + i * 17, z, 12.5, "leise", platz=570, wo="Legende")
    b.text(640, 792, "One contribution, five steps", 14, "schrift", "600", platz=520)
    schritte = [
        "The child's contribution arrives over HTTPS at the web server.",
        "Deterministic checks and the gatekeeper run in parallel.",
        "No: the server answers with the fixed sentence.",
        "Yes or unclear: Qwen writes the help, output checks follow.",
        "The child reads it, the teacher sees every turn, one protocol line per model call.",
    ]
    for i, z in enumerate(schritte):
        b.schritt(650, 810 + i * 17, i + 1)
        b.text(668, 814 + i * 17, z, 12.5, "leise", platz=500, wo="Schritte")

    # Wandernde Punkte. Gemeinsamer Weg bis zum Urteil, dann zwei Wege.
    # Spuren: linke Gasse im Django-Kasten x = 352, rechte Gasse x = 706,
    # freie Querspuren in der Mitte der Unterkaesten (373 fester Satz, 465
    # Ausgabepruefung), im Pfoertner und in Qwen 6 px hinter dem Rand.
    gemeinsam = "M 274,189 L 352,189 L 352,333 L 706,333 L 792,333 L 792,405 L 706,405"
    laenge_gemeinsam = 78 + 144 + 354 + 86 + 72 + 86
    weg_nein = gemeinsam + " L 706,373 L 352,373 L 352,215 L 274,215"
    laenge_nein = laenge_gemeinsam + 32 + 354 + 158 + 78
    weg_ja = gemeinsam + (" L 706,236 L 792,236 L 792,252 L 706,252 L 706,465 L 352,465 L 352,215 L 274,215")
    laenge_ja = laenge_gemeinsam + 169 + 86 + 16 + 86 + 213 + 354 + 250 + 78
    tempo = 150.0  # px je Sekunde: rund 10 s fuer den kurzen, 14 s fuer den langen Weg
    dauer_nein = round(laenge_nein / tempo, 1)
    dauer_ja = round(laenge_ja / tempo, 1)
    if pruefmodus:
        for weg in (weg_nein, weg_ja):
            b.roh(f'<path d="{weg}" fill="none" stroke="#e0007a" stroke-width="1" stroke-dasharray="3 2"/>')
    b.punkt(weg_nein, dauer_nein, 0, farbwechsel=(round(laenge_gemeinsam / laenge_nein, 3), "akzent"))
    b.punkt(weg_ja, dauer_ja, round(dauer_nein / 2, 1))
    return b.svg()


def main():
    """Ohne Argument die zwei Dateien hier; mit --pruefen VERZEICHNIS eine
    Fassung mit sichtbaren Laufwegen dorthin (fuer die Sichtpruefung)."""
    import sys

    pruefmodus = "--pruefen" in sys.argv
    ziel = pathlib.Path(sys.argv[sys.argv.index("--pruefen") + 1]) if pruefmodus else HIER
    ziele = {"konzept_b.svg": HELL, "konzept_b_dunkel.svg": DUNKEL}
    for name, farben in ziele.items():
        WARNUNGEN.clear()
        svg = zeichnen(farben, pruefmodus)
        ET.fromstring(svg.encode("utf-8"))  # wohlgeformt, sonst Abbruch
        pfad = ziel / name
        with open(pfad, "w", encoding="utf-8", newline="\n") as datei:
            datei.write(svg)
        print(f"{pfad.name}: {len(svg) / 1000:.1f} kB")
        for w in WARNUNGEN:
            print("  Platz knapp:", w)


if __name__ == "__main__":
    main()
