"""Messung der Bildkette mit synthetischen Testbildern.

Frage: Wie oft laesst die Kette (tutoring/bildkette.py) einen Ausschnitt
durch, wie oft sperrt sie und warum, und vor allem: Bleibt in einem
durchgelassenen Ausschnitt etwas stehen, das nicht hinaus soll?

Die Bilder sind erzeugt, keine Fotos von Kindern. Jedes Bild hat eine
gedruckte Aufgabe und zufaellig dazu: einen Namen in Schreibschrift, ein bis
zwei Zeilen Handschrift (manchmal direkt unter der Aufgabe, manchmal in sie
hinein), ein gezeichnetes Gesicht, ein Logo mit Schulnamen, Schraeglage und
einen Tisch als Hintergrund. Weil die Bilder erzeugt sind, ist bekannt, wo
jedes heikle Element liegt: Fuer jedes gibt es eine Wahrheitsebene (eine
Schwarzweissmaske). Nach dem Lauf wird nicht das Modell gefragt, ob etwas
durchgerutscht ist, sondern gezaehlt: Wie viele Pixel der Wahrheitsebene
liegen im Ausschnitt und sind nicht maskiert? Das ist die Leckmessung, und
sie ist vom Modell unabhaengig.

Dazu, als Mass fuer den Nutzen: Wie viel der gedruckten Aufgabe ist im
Ausschnitt noch da?

Lauf:
    set DJANGO_SETTINGS_MODULE=config.settings  (oder test_settings)
    set DJANGO_SECRET_KEY=x
    set SPARK_BASE_URL=http://127.0.0.1:18000/v1
    python benchmark/bildkette/messung.py --anzahl 24 --seed 20261031 --kennung M1

Braucht Pillow und den Spark. Die Abschrift der Aufgabe holt der Lauf wie
die App (spark.text_aus_bild), denn gegen sie wird der Ausschnitt gehalten.
Ergebnisse unter benchmark/bildkette/ergebnisse/<kennung>/.
"""

import argparse
import base64
import io
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent.parent
sys.path.insert(0, str(WURZEL))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "nur-fuer-die-messung")

import django  # noqa: E402

django.setup()

from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

from tutoring import bildkette, spark  # noqa: E402

FONTS = Path(os.environ.get("MESSUNG_FONTS", "C:/Windows/Fonts"))
DRUCK = ["arial.ttf", "calibri.ttf", "georgia.ttf", "verdana.ttf"]
SCHRIFT = ["Inkfree.ttf", "segoepr.ttf", "BRADHITC.TTF", "segoesc.ttf"]

# Gedruckte Aufgaben: mit und ohne Namen einer Figur. Die mit Namen zeigen,
# wie die Kette mit einem gedruckten Namen umgeht (er ist eine Person fuer
# die Namenserkennung, also sperrt die OCR-Regel, wenn er lesbar bleibt).
AUFGABEN = [
    ("Ein Rechteck ist 12 cm lang und 7 cm breit.", "Berechne Umfang und Flächeninhalt.", False),
    ("Ein Zug fährt 3 Stunden mit 80 km/h.", "Wie weit kommt er?", False),
    ("Berechne: 456 + 278 und 903 − 467.", "Schreibe die Rechnung untereinander.", False),
    ("In einer Schachtel sind 6 Packungen mit je 8 Stiften.", "Wie viele Stifte sind das?", False),
    ("Löse die Gleichung: 3x + 7 = 2x + 15", "Mache die Probe.", False),
    ("Lisa kauft 4 Packungen mit je 12 Buntstiften.", "Wie viele Buntstifte hat sie zusammen?", True),
    ("Herr Maier tankt 45 Liter zu je 1,60 Euro.", "Was zahlt er?", True),
    ("Anna hat 3/4 einer Pizza, Ben hat 2/3.", "Wer hat mehr? Begründe.", True),
]
NAMEN = ["Mia Huber", "Noah K.", "Lena Brunner", "Elias Mayr", "Sara Wolf", "Jonas Berger",
         "Emma Fink", "Luca Egger", "Hannah Moosbrugger", "Paul Rhomberg", "Lea Nussbaumer", "David Bösch"]
HANDSCHRIFTEN = ["4 · 12 = 48", "A = 12 · 7 = 84 cm²", "3 · 80 = 240 km", "456 + 278 = 734",
                 "x = 8", "6 · 8 = 48 Stifte", "Hausübung für Donnerstag", "Das ist leicht!",
                 "u = 2 · (12 + 7) = 38 cm", "45 · 1,6 = 72 €"]
SCHULEN = ["Volksschule Musterdorf", "MS Dornbirn-Markt", "VS Hohenems-Herrenried", "Gymnasium Bregenz"]


def font(name, groesse):
    return ImageFont.truetype(str(FONTS / name), groesse)


class Blatt:
    """Eine Heftseite samt Wahrheitsebenen je Element."""

    def __init__(self, breite, hoehe, grund):
        self.bild = Image.new("RGB", (breite, hoehe), grund)
        self.ebenen = {label: Image.new("1", (breite, hoehe), 0)
                       for label in bildkette.LABELS}

    def text(self, label, xy, inhalt, schrift, farbe):
        ImageDraw.Draw(self.bild).text(xy, inhalt, font=schrift, fill=farbe)
        ImageDraw.Draw(self.ebenen[label]).text(xy, inhalt, font=schrift, fill=1)

    def gesicht(self, x, y, r):
        for ziel, farbe in ((self.bild, (40, 40, 40)), (self.ebenen[bildkette.GESICHT], 1)):
            z = ImageDraw.Draw(ziel)
            z.ellipse([x - r, y - r, x + r, y + r], outline=farbe, width=4)
            for dx in (-r // 2, r // 2):
                z.ellipse([x + dx - 6, y - r // 3 - 6, x + dx + 6, y - r // 3 + 6], fill=farbe)
            z.arc([x - r // 2, y, x + r // 2, y + r // 2], 0, 180, fill=farbe, width=4)

    def logo(self, x, y, schule):
        for ziel, farbe in ((self.bild, (20, 80, 160)), (self.ebenen[bildkette.LOGO], 1)):
            z = ImageDraw.Draw(ziel)
            z.ellipse([x, y, x + 80, y + 80], outline=farbe, width=6)
            z.text((x + 16, y + 20), "VS", font=font("arialbd.ttf", 36), fill=farbe)
            z.text((x + 100, y + 22), schule, font=font("arial.ttf", 36), fill=farbe)

    def drehen(self, grad, tisch):
        """Dreht Bild und Ebenen gleich, auf einem Tisch mit fester Groesse."""
        bild = self.bild.rotate(grad, expand=True, fillcolor=tisch, resample=Image.BICUBIC)
        breite, hoehe = 1200, 1600
        neu = Image.new("RGB", (breite, hoehe), tisch)
        versatz = ((breite - bild.width) // 2, (hoehe - bild.height) // 2)
        neu.paste(bild, versatz)
        self.bild = neu
        for label, ebene in self.ebenen.items():
            gedreht = ebene.rotate(grad, expand=True, fillcolor=0)
            leer = Image.new("1", (breite, hoehe), 0)
            leer.paste(gedreht, versatz)
            self.ebenen[label] = leer


def erzeugen(zufall):
    """Ein Testbild mit zufaelliger Zusammenstellung. Gibt (Blatt, Beschreibung)."""
    aufgabe = zufall.choice(AUFGABEN)
    druck = font(zufall.choice(DRUCK), zufall.choice([34, 38, 42]))
    blatt = Blatt(1000, 1300, zufall.choice([(250, 248, 240), (255, 255, 255), (246, 243, 236)]))
    was = {"aufgabe": aufgabe[0], "aufgabe_mit_name": aufgabe[2]}

    y = 60
    if zufall.random() < 0.5:
        blatt.logo(40, y, zufall.choice(SCHULEN))
        was["logo"] = True
        y += 110
    if zufall.random() < 0.8:
        name = zufall.choice(NAMEN)
        x = zufall.choice([60, 560])
        blatt.text(bildkette.NAME, (x, y), name, font(zufall.choice(SCHRIFT), 44), (30, 60, 150))
        was["name"] = name
        y += 80

    y += 40
    blatt.text(bildkette.GEDRUCKT, (60, y), aufgabe[0], druck, (0, 0, 0))
    y += 55
    blatt.text(bildkette.GEDRUCKT, (60, y), aufgabe[1], druck, (0, 0, 0))
    unterkante = y + 50

    zeilen = zufall.choice([0, 1, 1, 2])
    if zeilen:
        # Direkt darunter, oder ein Stueck in die Aufgabe hinein: so schreiben Kinder.
        y = unterkante + zufall.choice([-25, 10, 40, 120])
        for _ in range(zeilen):
            blatt.text(bildkette.HANDSCHRIFT, (80, y), zufall.choice(HANDSCHRIFTEN),
                       font(zufall.choice(SCHRIFT), zufall.choice([50, 58, 66])), (20, 20, 120))
            y += 90
        was["handschrift"] = zeilen
    if zufall.random() < 0.4:
        blatt.gesicht(zufall.choice([200, 800]), zufall.choice([950, 1150]), zufall.choice([70, 100]))
        was["gesicht"] = True

    grad = zufall.choice([0, 0, 3, -3, 6, -5])
    blatt.drehen(grad, zufall.choice([(120, 118, 115), (90, 70, 50), (200, 200, 200)]))
    was["grad"] = grad
    return blatt, was


def data_url(bild):
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()


def leckmessung(blatt, befund):
    """Zaehlt je Element die Wahrheitspixel, die im Ausschnitt sichtbar blieben.

    Der Ausschnitt ist in Bildkoordinaten die Vereinigung der gedruckten
    Kaestchen plus RAND, die Masken sind die heiklen Kaestchen plus
    MASKENRAND; beides so, wie bildkette.zuschneiden es rechnet.
    """
    breite, hoehe = blatt.bild.size
    gedruckt = [b.box for b in befund.bereiche if b.label == bildkette.GEDRUCKT]
    x1 = max(0, min(b[0] for b in gedruckt) - bildkette.RAND)
    y1 = max(0, min(b[1] for b in gedruckt) - bildkette.RAND)
    x2 = min(breite, max(b[2] for b in gedruckt) + bildkette.RAND)
    y2 = min(hoehe, max(b[3] for b in gedruckt) + bildkette.RAND)
    sichtbar = Image.new("1", (breite, hoehe), 0)
    ImageDraw.Draw(sichtbar).rectangle([x1, y1, x2, y2], fill=1)
    z = ImageDraw.Draw(sichtbar)
    for b in befund.bereiche:
        if b.label in bildkette.HEIKEL:
            bx1, by1, bx2, by2 = b.box
            z.rectangle([bx1 - bildkette.MASKENRAND, by1 - bildkette.MASKENRAND,
                         bx2 + bildkette.MASKENRAND, by2 + bildkette.MASKENRAND], fill=0)

    ergebnis = {}
    for label, ebene in blatt.ebenen.items():
        gesamt = ebene.convert("L").histogram()[255]
        if not gesamt:
            continue
        uebrig = ImageChops.logical_and(ebene, sichtbar).convert("L").histogram()[255]
        ergebnis[label] = {"pixel": gesamt, "sichtbar": uebrig, "anteil": round(uebrig / gesamt, 3)}
    return ergebnis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--anzahl", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--kennung", default="M1")
    parser.add_argument("--leckschwelle", type=float, default=0.02,
                        help="Anteil sichtbarer Wahrheitspixel, ab dem ein Element als Leck zaehlt")
    args = parser.parse_args()

    zufall = random.Random(args.seed)
    ziel = HIER / "ergebnisse" / args.kennung
    ziel.mkdir(parents=True, exist_ok=True)
    zeilen = []

    for nr in range(1, args.anzahl + 1):
        blatt, was = erzeugen(zufall)
        url = data_url(blatt.bild)
        blatt.bild.save(ziel / f"{nr:02d}_original.jpg", quality=85)
        begonnen = time.monotonic()
        abschrift, _ = spark.text_aus_bild(url)
        zeile = {"nr": nr, **was, "abschrift": abschrift[:300]}
        try:
            befund = bildkette.bereinigen(url, abschrift)
        except bildkette.BildGesperrt as fehler:
            zeile.update(ergebnis="blockiert", art=fehler.art, grund=fehler.grund)
            print(f"{nr:02d} blockiert  {fehler.art:20s} {fehler.grund}")
        else:
            (ziel / f"{nr:02d}_ausgehend.jpg").write_bytes(
                base64.b64decode(befund.data_url.split(",", 1)[1]))
            lecks = leckmessung(blatt, befund)
            lecke = [label for label, w in lecks.items()
                     if label in bildkette.HEIKEL and w["anteil"] > args.leckschwelle]
            zeile.update(ergebnis="bestanden", masken=befund.masken, dauer_ms=befund.dauer_ms,
                         tokens=befund.tokens_ein, lecks=lecks, leck=lecke,
                         aufgabe_erhalten=lecks.get(bildkette.GEDRUCKT, {}).get("anteil"))
            print(f"{nr:02d} bestanden  Masken {befund.masken}  Leck: {lecke or 'keines'}  "
                  f"Aufgabe erhalten {zeile['aufgabe_erhalten']}  {befund.dauer_ms} ms")
        zeile["dauer_gesamt_ms"] = int((time.monotonic() - begonnen) * 1000)
        zeilen.append(zeile)

    bestanden = [z for z in zeilen if z["ergebnis"] == "bestanden"]
    blockiert = [z for z in zeilen if z["ergebnis"] == "blockiert"]
    arten = {}
    for z in blockiert:
        arten[z["art"]] = arten.get(z["art"], 0) + 1
    mit_leck = [z for z in bestanden if z["leck"]]
    zusammenfassung = {
        "kennung": args.kennung, "seed": args.seed, "anzahl": len(zeilen),
        "bestanden": len(bestanden), "blockiert": len(blockiert), "blockiert_nach_art": arten,
        "bestanden_mit_leck": len(mit_leck),
        "lecks_nach_element": {
            label: sum(1 for z in mit_leck if label in z["leck"]) for label in bildkette.HEIKEL
        },
        "aufgabe_erhalten_median": statistics.median(
            [z["aufgabe_erhalten"] for z in bestanden if z.get("aufgabe_erhalten") is not None]
        ) if bestanden else None,
        "dauer_kette_median_ms": statistics.median([z["dauer_ms"] for z in bestanden]) if bestanden else None,
        "dauer_gesamt_median_ms": statistics.median([z["dauer_gesamt_ms"] for z in zeilen]),
        "blockiert_wegen_gedrucktem_name": sum(
            1 for z in blockiert if z.get("aufgabe_mit_name") and z["art"] == bildkette.ART_LEAK
        ),
    }
    (ziel / "messung.json").write_text(
        json.dumps({"zusammenfassung": zusammenfassung, "bilder": zeilen}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("=" * 70)
    print(json.dumps(zusammenfassung, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
