"""Machbarkeitsprobe fuer die Bildkette: Kann Qwen3-VL am Spark
(a) den gedruckten Aufgabenbereich und die heiklen Bereiche verorten,
(b) nach Zuschnitt und Maskierung bestaetigen, dass nichts Heikles mehr da ist,
(c) den ausgehenden Ausschnitt per OCR lesen?

Synthetische Testbilder, keine echten Kinderfotos. Nur Inferenz am Spark,
nichts wird dort veraendert.
"""
import base64
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

HIER = Path(__file__).parent
AUS = HIER / "bildkette"
AUS.mkdir(exist_ok=True)
BASIS = "http://127.0.0.1:18000/v1"
MODELL = "qwen3-vl-30b"
FONTS = Path("C:/Windows/Fonts")


def font(name, groesse):
    return ImageFont.truetype(str(FONTS / name), groesse)


def gesicht(z, x, y, r):
    z.ellipse([x - r, y - r, x + r, y + r], outline=(40, 40, 40), width=4)
    z.ellipse([x - r // 2 - 6, y - r // 3 - 6, x - r // 2 + 6, y - r // 3 + 6], fill=(40, 40, 40))
    z.ellipse([x + r // 2 - 6, y - r // 3 - 6, x + r // 2 + 6, y - r // 3 + 6], fill=(40, 40, 40))
    z.arc([x - r // 2, y, x + r // 2, y + r // 2], 0, 180, fill=(40, 40, 40), width=4)


def logo(z, x, y):
    z.ellipse([x, y, x + 90, y + 90], outline=(20, 80, 160), width=6)
    z.text((x + 18, y + 22), "VS", font=font("arialbd.ttf", 40), fill=(20, 80, 160))


def bild_a():
    """Heftseite: Logo, Schulname, Kindername, gedruckte Aufgabe, Handschrift, Gesicht."""
    b = Image.new("RGB", (1200, 1600), (246, 243, 236))
    z = ImageDraw.Draw(b)
    logo(z, 60, 50)
    z.text((170, 70), "Volksschule Musterdorf", font=font("arial.ttf", 44), fill=(20, 80, 160))
    z.text((760, 60), "Mia Huber, 3b", font=font("segoesc.ttf", 46), fill=(30, 60, 150))
    z.rectangle([60, 220, 1140, 560], outline=(120, 120, 120), width=2)
    z.text((90, 250), "Aufgabe 3", font=font("arialbd.ttf", 40), fill=(0, 0, 0))
    z.text((90, 320), "Lisa kauft 4 Packungen mit je 12 Buntstiften.", font=font("arial.ttf", 38), fill=(0, 0, 0))
    z.text((90, 380), "Wie viele Buntstifte hat sie zusammen?", font=font("arial.ttf", 38), fill=(0, 0, 0))
    z.text((90, 460), "Rechne und schreibe einen Antwortsatz.", font=font("arial.ttf", 34), fill=(60, 60, 60))
    z.text((110, 640), "4 · 12 = 48", font=font("Inkfree.ttf", 70), fill=(30, 60, 150))
    z.text((110, 760), "Lisa hat 48 Buntstifte.", font=font("Inkfree.ttf", 60), fill=(30, 60, 150))
    gesicht(z, 980, 1350, 110)
    z.text((80, 1480), "Hausübung für Donnerstag", font=font("segoepr.ttf", 40), fill=(30, 60, 150))
    return b


def bild_b():
    """Arbeitsblatt der Lehrperson als Bildschirmfoto: nur Druck, kein Kind."""
    b = Image.new("RGB", (1200, 900), (255, 255, 255))
    z = ImageDraw.Draw(b)
    z.text((60, 40), "Mathematik 7. Schulstufe – Arbeitsblatt 12", font=font("arialbd.ttf", 36), fill=(0, 0, 0))
    z.text((60, 130), "1) Ein Rechteck hat den Umfang 48 cm. Die Länge ist dreimal so groß", font=font("arial.ttf", 32), fill=(0, 0, 0))
    z.text((60, 180), "   wie die Breite. Berechne Länge und Breite.", font=font("arial.ttf", 32), fill=(0, 0, 0))
    z.text((60, 270), "2) Löse die Gleichung: 3x + 7 = 2x + 15", font=font("arial.ttf", 32), fill=(0, 0, 0))
    z.text((60, 360), "3) Vereinfache: 2(a + 3b) − (a − b)", font=font("arial.ttf", 32), fill=(0, 0, 0))
    z.text((60, 820), "Mittelschule Dornbirn-Schoren", font=font("arial.ttf", 24), fill=(90, 90, 90))
    return b


def bild_c():
    """Handyfoto: schief, grauer Tisch, Handschrift direkt unter der Aufgabe, Name im Rand."""
    seite = Image.new("RGB", (1000, 1300), (250, 248, 240))
    z = ImageDraw.Draw(seite)
    z.text((60, 40), "Noah K.", font=font("BRADHITC.TTF", 48), fill=(20, 20, 120))
    z.text((60, 160), "5. Berechne den Flächeninhalt eines Dreiecks", font=font("calibri.ttf", 40), fill=(0, 0, 0))
    z.text((60, 215), "mit g = 8 cm und h = 5 cm.", font=font("calibri.ttf", 40), fill=(0, 0, 0))
    z.text((80, 300), "A = g · h = 8 · 5 = 40 cm²", font=font("Inkfree.ttf", 56), fill=(20, 20, 120))
    z.text((60, 520), "6. Ein Zug fährt 3 Stunden mit 80 km/h.", font=font("calibri.ttf", 40), fill=(0, 0, 0))
    z.text((60, 575), "Wie weit kommt er?", font=font("calibri.ttf", 40), fill=(0, 0, 0))
    gesicht(z, 820, 1100, 90)
    seite = seite.rotate(5, expand=True, fillcolor=(120, 118, 115))
    tisch = Image.new("RGB", (1200, 1600), (120, 118, 115))
    tisch.paste(seite, ((1200 - seite.width) // 2, (1600 - seite.height) // 2))
    return tisch


def jpeg_mit_exif(bild):
    """Als JPEG mit GPS-Exif speichern, um Schritt 1 (Metadaten) zu pruefen."""
    exif = Image.Exif()
    exif[0x010F] = "Musterphone"
    exif[0x0110] = "Modell X"
    from PIL import TiffImagePlugin
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (TiffImagePlugin.IFDRational(47, 1), TiffImagePlugin.IFDRational(24, 1), TiffImagePlugin.IFDRational(0, 1))
    gps[3] = "E"
    gps[4] = (TiffImagePlugin.IFDRational(9, 1), TiffImagePlugin.IFDRational(44, 1), TiffImagePlugin.IFDRational(0, 1))
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=85, exif=exif.tobytes())
    return puffer.getvalue()


def data_url(daten):
    return "data:image/jpeg;base64," + base64.b64encode(daten).decode()


def fragen(bild_daten, frage, max_tokens=600):
    rumpf = {
        "model": MODELL, "temperature": 0, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url(bild_daten)}},
            {"type": "text", "text": frage},
        ]}],
    }
    t = time.time()
    r = httpx.post(BASIS + "/chat/completions", json=rumpf, timeout=120)
    r.raise_for_status()
    d = r.json()
    return d["choices"][0]["message"]["content"].strip(), round(time.time() - t, 1), d.get("usage", {})


VERORTEN = (
    "Du siehst ein Foto einer Schulbuch- oder Heftseite. Gib als JSON-Liste alle Bereiche an, "
    "jeweils mit \"label\" und \"bbox_2d\" [x1, y1, x2, y2]. Labels: "
    "\"gedruckte_aufgabe\" (gedruckter Aufgabentext, einer je Aufgabe), "
    "\"handschrift\" (alles Handgeschriebene), \"name\" (ein Personenname, gedruckt oder geschrieben), "
    "\"gesicht\" (Gesicht, Foto oder Zeichnung), \"logo\" (Logo, Wappen, Schulname). "
    "Jeder Bereich ist ein eigenes Objekt mit genau einem \"label\" und genau einer \"bbox_2d\"; "
    "ein Bereich kann mehrere Labels haben, dann steht er mehrfach in der Liste. Beispiel: "
    "[{\"label\": \"gedruckte_aufgabe\", \"bbox_2d\": [40, 120, 900, 300]}, "
    "{\"label\": \"handschrift\", \"bbox_2d\": [60, 330, 500, 400]}]. "
    "Nur JSON, kein weiterer Text."
)
PRUEFEN = (
    "Prüfe dieses Bild streng. Antworte nur als JSON mit den Schlüsseln "
    "\"handschrift\", \"name\", \"gesicht\", \"logo\", jeweils true oder false, "
    "und \"begruendung\" in einem kurzen Satz. Schwarze Balken sind Maskierungen und zählen nicht."
)
OCR = "Schreib den gesamten lesbaren Text auf dem Bild wortgetreu ab. Nur den Text."


def boxen_parsen(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return json.loads(text)


def skaliere(box, breite, hoehe, normiert):
    x1, y1, x2, y2 = box
    if normiert:
        return (x1 * breite / 1000, y1 * hoehe / 1000, x2 * breite / 1000, y2 * hoehe / 1000)
    return (x1, y1, x2, y2)


def kette(bild, boxen, normiert):
    """Zuschneiden auf die gedruckten Aufgaben, alles andere schwarz."""
    b = bild.copy()
    z = ImageDraw.Draw(b)
    gedruckt = [skaliere(e["bbox_2d"], b.width, b.height, normiert) for e in boxen if e["label"] == "gedruckte_aufgabe"]
    heikel = [skaliere(e["bbox_2d"], b.width, b.height, normiert) for e in boxen if e["label"] != "gedruckte_aufgabe"]
    for box in heikel:
        z.rectangle([box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6], fill=(0, 0, 0))
    if not gedruckt:
        return None
    x1 = min(g[0] for g in gedruckt); y1 = min(g[1] for g in gedruckt)
    x2 = max(g[2] for g in gedruckt); y2 = max(g[3] for g in gedruckt)
    rand = 12
    return b.crop((max(0, x1 - rand), max(0, y1 - rand), min(b.width, x2 + rand), min(b.height, y2 + rand)))


def neu_kodieren(bild):
    """Schritt 1: neu kodieren ohne Metadaten."""
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=85)
    return puffer.getvalue()


def main():
    normiert = "--pixel" not in sys.argv
    bilder = {"A_heftseite": bild_a(), "B_arbeitsblatt": bild_b(), "C_handyfoto": bild_c()}
    for name, bild in bilder.items():
        print("=" * 70); print(name, bild.size)
        roh = jpeg_mit_exif(bild)
        (AUS / f"{name}_original.jpg").write_bytes(roh)
        exif_vorher = Image.open(io.BytesIO(roh)).getexif()
        print("EXIF vorher:", dict(list(exif_vorher.items())[:3]), "GPS" if 0x8825 in exif_vorher else "kein GPS")

        antwort, dauer, nutzung = fragen(roh, VERORTEN)
        print(f"Verorten ({dauer}s, {nutzung.get('prompt_tokens')} Token ein):")
        print(antwort)
        try:
            boxen = boxen_parsen(antwort)
        except Exception as fehler:
            print("Boxen nicht lesbar:", fehler); continue

        markiert = bild.copy(); z = ImageDraw.Draw(markiert)
        farben = {"gedruckte_aufgabe": (0, 160, 0), "handschrift": (200, 0, 0), "name": (200, 0, 200), "gesicht": (255, 120, 0), "logo": (0, 0, 220)}
        for e in boxen:
            box = skaliere(e["bbox_2d"], bild.width, bild.height, normiert)
            z.rectangle(box, outline=farben.get(e["label"], (0, 0, 0)), width=5)
            z.text((box[0], max(0, box[1] - 30)), e["label"], font=font("arialbd.ttf", 26), fill=farben.get(e["label"], (0, 0, 0)))
        markiert.save(AUS / f"{name}_boxen.png")

        aus = kette(bild, boxen, normiert)
        if aus is None:
            print("Kein gedruckter Bereich erkannt -> blockiert (Spark antwortet)"); continue
        aus_daten = neu_kodieren(aus)
        (AUS / f"{name}_ausgehend.jpg").write_bytes(aus_daten)
        exif_nachher = Image.open(io.BytesIO(aus_daten)).getexif()
        print("EXIF nachher:", len(exif_nachher), "Eintraege;", "Ausschnitt", aus.size)

        pruefung, dauer, _ = fragen(aus_daten, PRUEFEN, 200)
        print(f"Leak-Check Vision ({dauer}s): {pruefung}")
        ocr, dauer, _ = fragen(aus_daten, OCR, 300)
        print(f"OCR ausgehend ({dauer}s):\n{ocr}")
    print("=" * 70)


if __name__ == "__main__":
    main()
