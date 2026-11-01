"""Nutzen der Bildweiterleitung: Messung N1 (Thomas, 31.10.2026).

Thomas: "Für diese Entscheidung hätte ich gerne einige Beispiele ausprobiert.
Erst wenn wir den möglichen Nutzen kennen, können wir über die Notwendigkeit
diskutieren, ob wir die Bilder brauchen oder nicht." Und: "mach 2, die Prüfung
mit den vorhandenen Bildern."

Frage: Was bringt es der Qualitätssicherung, wenn neben der Abschrift des
Spark auch der bereinigte Ausschnitt hinausgeht? Gemessen an den amtlichen
Aufgaben mit Abbildung aus dem Siegen-Marathon (iKMPLUS 4 und 8, Matura),
soweit sie automatisch gegen den Lösungsschlüssel bewertbar sind.

Drei Bedingungen je Aufgabe, jeweils dieselbe Kette wie in der App
(cloud.geprueft_fragen: umformulieren, erkennen, maskieren, Leak-Check,
senden, zurücksetzen):

  A  Abschrift des Spark (spark.text_aus_bild), nur Text
     = die App ohne den zweiten Schalter
  B  Abschrift plus bereinigter Ausschnitt (bildkette.bereinigen)
     = die App mit beiden Schaltern; sperrt die Bildkette, gilt A
  C  der amtliche Aufgabentext, nur Text
     = Referenz: wie gut wäre die Qualitätssicherung mit perfekter Abschrift

Bewertet mit dem Scorer des Marathons (score.bewerte, Antwortzeile
"ANTWORT: …"); die Formatvorgabe je Aufgabe kommt aus prompts.format_anweisung,
in allen drei Bedingungen gleich.

Läuft lokal: der Spark über den Tunnel (SPARK_BASE_URL), OpenAI mit dem
Schlüssel aus einer Datei (--schluesseldatei), die nie ausgegeben wird.
Kosten grob ein Euro mit gpt-6.1-sol. Schreibt ergebnisse/<kennung>/messung.json
nach jeder Aufgabe (ein Abbruch verliert nichts; ein zweiter Lauf mit
derselben Kennung macht nur die fehlenden Aufgaben).

    set DJANGO_SETTINGS_MODULE=test_settings  (oder config.settings)
    set DJANGO_SECRET_KEY=x
    set SPARK_BASE_URL=http://127.0.0.1:18000/v1
    set SPARK_MODEL=qwen3.6-35b-a3b
    python benchmark/bildnutzen/messung.py --kennung N1 \
        --schluesseldatei "/pfad/zur/schluesseldatei.txt" \
        --marathon "/pfad/zum/marathon/benchmark"
"""

import argparse
import base64
import json
import os
import statistics
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent.parent


def _umgebung(args):
    """Setzt die Umgebung, bevor Django die Einstellungen liest."""
    # Wie der Marathon: utf-8-sig (die Datei hat eine Byte-Order-Marke), die
    # erste Zeile mit "sk-". Ein Zeichen zu viel im Kopf der Anfrage heisst
    # LocalProtocolError, ohne dass der Schluessel irgendwo auftaucht.
    schluessel = ""
    for zeile in Path(args.schluesseldatei).read_text(encoding="utf-8-sig").splitlines():
        if zeile.strip().startswith("sk-"):
            schluessel = zeile.strip()
            break
    if not schluessel:
        sys.exit("Kein Schlüssel in der Schlüsseldatei.")
    os.environ["CLOUD_API_KEY"] = schluessel
    os.environ.setdefault("CLOUD_BASE_URL", "https://api.openai.com/v1")
    os.environ["CLOUD_MODEL"] = args.modell
    os.environ.setdefault("CLOUD_TIMEOUT_SECONDS", "180")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_settings")
    os.environ.setdefault("DJANGO_SECRET_KEY", "messung")
    os.environ.setdefault("SPARK_TIMEOUT_SECONDS", "180")
    sys.path.insert(0, str(WURZEL))
    sys.path.insert(0, str(Path(args.marathon)))


# Die Bilder des Marathons sind nur die Abbildungen; der Aufgabentext steht
# daneben als Text. Ein Kind fotografiert aber die ganze gedruckte Aufgabe.
# Deshalb wird je Aufgabe eine Seite gesetzt: Text, Abbildung an der Stelle
# des Platzhalters, Antwortmoeglichkeiten darunter. Die Seite ist das "Foto".
_LATEX = (
    (r"\\alpha", "α"), (r"\\beta", "β"), (r"\\gamma", "γ"), (r"\\pi", "π"),
    (r"\\cdot", "·"), (r"\\le", "≤"), (r"\\ge", "≥"), (r"\\neq", "≠"),
    (r"\\sqrt", "√"), (r"\\infty", "∞"), (r"\\Delta", "Δ"), (r"\\%", "%"),
    (r"\\mathrm\{([^}]*)\}", r"\1"), (r"\\text\{([^}]*)\}", r"\1"),
    (r"\\vec\{([^}]*)\}", r"\1→"), (r"\\overline\{([^}]*)\}", r"\1"),
    (r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)"), (r"\\,", " "), (r"\\;", " "),
    (r"\\(sin|cos|tan|log|ln)", r"\1"), (r"\$", ""), (r"\\\\", "\n"),
)


def _druckfassung(text):
    import re
    for muster, ersatz in _LATEX:
        text = re.sub(muster, ersatz, text)
    return text.replace("\\", "")


def _seite(item, marathon, ablage=None):
    """Setzt die Aufgabe als gedruckte Seite und gibt sie als Data-URL (JPEG)."""
    import io
    import textwrap

    from PIL import Image, ImageDraw, ImageFont

    import prompts  # noqa: E402

    breite, rand = 1240, 70
    schrift = ImageFont.truetype(os.environ.get("MESSUNG_FONT", "C:/Windows/Fonts/arial.ttf"), 30)
    zeilenhoehe = 42
    text = _druckfassung(item["prompt_text"])
    # Der Platzhalter kann eine Beschreibung tragen ("[Abbildung: Bleistift
    # ueber einem Lineal ...]"); die darf nicht auf die Seite, sie wuerde
    # verraten, was nur das Bild zeigt.
    treffer = prompts.PLATZHALTER.search(text)
    if treffer:
        vor, nach = text[:treffer.start()], text[treffer.end():]
    else:
        vor, nach = text, ""
    optionen = _druckfassung(prompts._optionen_text(item) or "")
    bild = Image.open(marathon.parent.parent / "aufgaben" / item["image_path"]).convert("RGB")
    if bild.width > breite - 2 * rand:
        f = (breite - 2 * rand) / bild.width
        bild = bild.resize((int(bild.width * f), int(bild.height * f)))

    def zeilen(block):
        aus = []
        for absatz in block.strip().splitlines():
            aus += textwrap.wrap(absatz, 68, replace_whitespace=False) or [""]
        return aus

    bloecke = [zeilen(vor), None, zeilen(nach), zeilen(optionen) if optionen else []]
    hoehe = rand * 2 + sum(len(b) * zeilenhoehe + 20 for b in bloecke if b) + bild.height + 30
    seite = Image.new("RGB", (breite, hoehe), (252, 252, 250))
    zeichnen = ImageDraw.Draw(seite)
    y = rand
    for block in bloecke:
        if block is None:
            seite.paste(bild, (rand, y))
            y += bild.height + 30
            continue
        for zeile in block:
            zeichnen.text((rand, y), zeile, fill=(20, 20, 20), font=schrift)
            y += zeilenhoehe
        y += 20
    puffer = io.BytesIO()
    seite.save(puffer, "JPEG", quality=85)
    if ablage is not None:
        (ablage / f"{item['id']}_seite.jpg").write_bytes(puffer.getvalue())
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode("ascii")


def _system(cloud):
    return (cloud.SYSTEM + "\n\nSchreibe als allerletzte Zeile genau eine Zeile, die "
            "mit \"ANTWORT:\" beginnt, im verlangten Format. Nach dieser Zeile folgt "
            "nichts mehr.")


def _hinaus(cloud, text, system, bild=None):
    """Ein Aufruf der Kette; gibt (antwort, zahlen, sperre)."""
    begonnen = time.monotonic()
    try:
        erg = cloud.geprueft_fragen(text, None, system=system, max_tokens=2000, bild=bild)
    except cloud.CloudGesperrt as fehler:
        return "", {"dauer_s": round(time.monotonic() - begonnen, 1)}, fehler.art
    return erg["loesung"], {
        "dauer_s": round(time.monotonic() - begonnen, 1),
        "tokens_ein": erg["tokens_ein"], "tokens_aus": erg["tokens_aus"],
        "modell": erg["modell"], "umgeschrieben": bool(erg.get("umgeschrieben")),
        "ersetzt": erg.get("ersetzt", 0),
    }, ""


def _eine(item, args, module):
    spark, bildkette, cloud, prompts, score = module
    data_url = _seite(item, Path(args.marathon), args.ordner if args.ausschnitte else None)
    schluessel = item.get("answer_key") or {}
    auto = bool(item.get("auto_scorable")) and bool(schluessel)
    zeile = {"id": item["id"], "level": item["level"], "format": item.get("format"),
             "typ": schluessel.get("type", ""), "auto": auto}
    system = _system(cloud)
    # Ohne Schluessel (Konstruktionsaufgaben, Thomas 1.11.2026: "alle
    # Bildaufgaben, nicht nur die 38") gibt es keine Formatvorgabe aus dem
    # Marathon; die Antwort wird aufgehoben und von Hand beurteilt.
    if auto:
        formatvorgabe = "Antwortformat: " + prompts.format_anweisung(item)
    else:
        formatvorgabe = ("Antwortformat: Beschreibe die Lösung in wenigen Sätzen, "
                         "bei einer Konstruktion die Schritte.")

    begonnen = time.monotonic()
    abschrift, verbrauch = spark.text_aus_bild(data_url)
    zeile["abschrift"] = abschrift
    zeile["abschrift_s"] = round(time.monotonic() - begonnen, 1)
    zeile["abschrift_tokens_aus"] = (verbrauch or {}).get("completion_tokens", 0)
    text_a = (abschrift or "(keine Abschrift)") + "\n\n" + formatvorgabe

    # A: nur die Abschrift.
    antwort, zahlen, sperre = _hinaus(cloud, text_a, system)
    zeile["A"] = {"antwort": antwort, "sperre": sperre, **zahlen}

    # B: Abschrift plus Ausschnitt. Sperrt die Bildkette, bleibt es bei A.
    begonnen = time.monotonic()
    try:
        befund = bildkette.bereinigen(data_url, abschrift)
    except bildkette.BildGesperrt as fehler:
        zeile["bild"] = {"gesperrt": fehler.art, "grund": fehler.grund,
                         "dauer_s": round(time.monotonic() - begonnen, 1)}
        zeile["B"] = {**zeile["A"], "wie_a": True}
    else:
        zeile["bild"] = {"gesperrt": "", "masken": befund.masken, "dauer_ms": befund.dauer_ms,
                         "breite": befund.breite, "hoehe": befund.hoehe,
                         "tokens_ein": befund.tokens_ein, "tokens_aus": befund.tokens_aus}
        antwort, zahlen, sperre = _hinaus(cloud, text_a, system, bild=befund.data_url)
        zeile["B"] = {"antwort": antwort, "sperre": sperre, **zahlen}
        if args.ausschnitte:
            roh = befund.data_url.split(",", 1)[1]
            (args.ordner / f"{item['id']}_ausschnitt.jpg").write_bytes(base64.b64decode(roh))

    # C: der amtliche Text, mit Optionen und Formatvorgabe wie im Marathon.
    if auto:
        text_c = prompts.prompt_text(item)
    else:
        text_c = _druckfassung(item["prompt_text"]) + "\n\n" + formatvorgabe
    antwort, zahlen, sperre = _hinaus(cloud, text_c, system)
    zeile["C"] = {"antwort": antwort, "sperre": sperre, **zahlen}

    for bedingung in ("A", "B", "C"):
        if auto:
            korrekt, antwortzeile = score.bewerte(item, zeile[bedingung]["antwort"])
            zeile[bedingung]["korrekt"] = bool(korrekt)
        else:
            korrekt, antwortzeile = None, ""
            zeile[bedingung]["korrekt"] = None
        zeile[bedingung]["antwortzeile"] = antwortzeile
    return zeile


def _zusammenfassung(zeilen):
    def anteil(teil, bedingung):
        # Nur die Aufgaben mit Schluessel zaehlen in die Quote.
        teil = [z for z in teil if z.get("auto", True)]
        n = len(teil)
        k = sum(1 for z in teil if z[bedingung]["korrekt"])
        return f"{k}/{n}" if n else "–"
    gruppen = {"alle": zeilen}
    for z in zeilen:
        gruppen.setdefault(z["level"], []).append(z)
    tabelle = {g: {b: anteil(t, b) for b in ("A", "B", "C")} for g, t in gruppen.items()}
    gesperrt = [z["id"] for z in zeilen if z["bild"]["gesperrt"]]
    return {
        "anzahl": len(zeilen),
        "korrekt": tabelle,
        "b_besser_als_a": [z["id"] for z in zeilen if z["B"]["korrekt"] and not z["A"]["korrekt"]],
        "a_besser_als_b": [z["id"] for z in zeilen if z["A"]["korrekt"] and not z["B"]["korrekt"]],
        "bild_gesperrt": gesperrt,
        "bild_gesperrt_grund": {z["id"]: z["bild"]["gesperrt"] for z in zeilen if z["bild"]["gesperrt"]},
        "ohne_schluessel": [z["id"] for z in zeilen if not z.get("auto", True)],
        "masken_gesamt": sum(sum((z["bild"].get("masken") or {}).values())
                             if isinstance(z["bild"].get("masken"), dict) else 0
                             for z in zeilen),
        "qs_gesperrt": {b: [z["id"] for z in zeilen if z[b]["sperre"]] for b in ("A", "B", "C")},
        "dauer_s_median": {
            "abschrift": statistics.median(z["abschrift_s"] for z in zeilen),
            "bildkette": statistics.median(
                z["bild"].get("dauer_ms", 0) / 1000 for z in zeilen if not z["bild"]["gesperrt"]
            ) if len(gesperrt) < len(zeilen) else None,
            **{b: statistics.median(z[b]["dauer_s"] for z in zeilen) for b in ("A", "B", "C")},
        },
        "tokens_ein_median": {
            b: statistics.median(z[b].get("tokens_ein", 0) for z in zeilen) for b in ("A", "B", "C")
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kennung", default="N1")
    ap.add_argument("--schluesseldatei", required=True, help="Datei mit dem OpenAI-Schlüssel")
    ap.add_argument("--marathon", required=True, help="Ordner A_tutor/benchmark der Siegen-Sitzung")
    ap.add_argument("--modell", default="gpt-6.1-sol")
    ap.add_argument("--nur", nargs="*", default=None, help="nur diese Aufgaben-Kennungen")
    ap.add_argument("--anzahl", type=int, default=0, help="höchstens so viele Aufgaben (0 = alle)")
    ap.add_argument("--ausschnitte", action="store_true", help="die Ausschnitte als JPEG ablegen")
    ap.add_argument("--alle", action="store_true",
                    help="auch die Bildaufgaben ohne bewertbaren Schlüssel (nicht bewertet)")
    args = ap.parse_args()
    _umgebung(args)

    import django
    django.setup()
    from tutoring import bildkette, cloud, spark  # noqa: E402
    import prompts  # noqa: E402  (Siegen-Marathon)
    import score  # noqa: E402

    items = [i for i in prompts.lade_items(nur_auto=not args.alle) if i.get("needs_image")]
    if args.nur:
        items = [i for i in items if i["id"] in set(args.nur)]
    if args.anzahl:
        items = items[:args.anzahl]

    args.ordner = HIER / "ergebnisse" / args.kennung
    args.ordner.mkdir(parents=True, exist_ok=True)
    datei = args.ordner / "messung.json"
    stand = json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {"zeilen": []}
    fertig = {z["id"] for z in stand["zeilen"]}
    print(f"{len(items)} Aufgaben mit Bild, {len(fertig)} schon da, Modell {args.modell}, "
          f"Spark {os.environ.get('SPARK_MODEL', '?')}", flush=True)

    for nr, item in enumerate(items, 1):
        if item["id"] in fertig:
            continue
        begonnen = time.monotonic()
        try:
            zeile = _eine(item, args, (spark, bildkette, cloud, prompts, score))
        except Exception as fehler:  # noqa: BLE001 - eine Aufgabe darf den Lauf nicht beenden
            print(f"{nr:2d} {item['id']}: FEHLER {type(fehler).__name__}: {fehler}", flush=True)
            continue
        zeile["dauer_s"] = round(time.monotonic() - begonnen, 1)
        stand["zeilen"].append(zeile)
        stand["zusammenfassung"] = _zusammenfassung(stand["zeilen"])
        stand["modell"] = args.modell
        stand["spark_modell"] = os.environ.get("SPARK_MODEL", "")
        datei.write_text(json.dumps(stand, ensure_ascii=False, indent=1), encoding="utf-8")
        def marke(b):
            k = zeile[b]["korrekt"]
            return "?" if k is None else ("+" if k else "-")
        print(f"{nr:2d} {item['id']:16s} A {marke('A')}  B {marke('B')}  C {marke('C')}  "
              f"Bild {zeile['bild']['gesperrt'] or 'ok'}  {zeile['dauer_s']} s", flush=True)

    print(json.dumps(stand.get("zusammenfassung", {}), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
