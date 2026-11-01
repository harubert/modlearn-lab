"""Setzt die Tutorzuege von Claude in die Vergleichsprotokolle ein.

ergebnisse/claude/claude_zuege.json enthaelt je Dialog und Zug den Text und
die Diagnose von Claude; die Protokolle ergebnisse/claude/<id>.json tragen die
Kinderzuege und die Stufenfolge aus dem Spark-Lauf. Dieses Skript fuellt die
Tutorfelder, prueft jeden Text mit derselben Ausgangspruefung wie die App
(ausgabepruefung.verstoesse) und setzt tutor_verraet_loesung mit denselben
Ergebnismustern.

    python benchmark/mathe/zusammenfuehren.py
"""

import glob
import json
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

from lauf import ergebnis_genannt  # noqa: E402
from tutoring import ausgabepruefung, levels  # noqa: E402

ORDNER = os.path.join(HIER, "ergebnisse", "claude")


def main():
    with open(os.path.join(ORDNER, "claude_zuege.json"), encoding="utf-8") as f:
        zuege = json.load(f)
    with open(os.path.join(HIER, "aufgaben.json"), encoding="utf-8") as f:
        muster = {a["id"]: a["loesung_muster"] for a in json.load(f)["aufgaben"]}

    for pfad in sorted(glob.glob(os.path.join(ORDNER, "*.json"))):
        if os.path.basename(pfad).startswith("claude_zuege"):
            continue
        with open(pfad, encoding="utf-8") as f:
            d = json.load(f)
        meine = zuege.get(d["id"])
        if not meine:
            print("keine Zuege fuer", d["id"])
            continue
        eigenes = [d["aufgabe"]["text"]]
        for z in d["zuege"]:
            nr = str(z["nr"])
            if nr not in meine:
                print(d["id"], "Zug", nr, "fehlt")
                continue
            z["tutor_text"] = meine[nr]["tutor_text"]
            stufe = z.get("grenze") or z.get("stufe") or 5
            z["pruefung"] = {
                "verstoesse": ausgabepruefung.verstoesse(
                    z["tutor_text"], stufe, d["obergrenze"], eigenes),
                "versuche": 1, "gekuerzt": False, "notfall": False,
                "hinweis": "Pruefung nur protokolliert, Text nicht veraendert",
            }
            z["tutor_verraet_loesung"] = (stufe < levels.LOESUNG
                                          and ergebnis_genannt(z["tutor_text"], muster[d["id"]]))
            if "diagnose" in meine[nr]:
                z["diagnose"] = meine[nr]["diagnose"]
            elif "diagnose" in z and z["diagnose"].get("stufe") is None:
                z.pop("diagnose")
            if z.get("kind_text"):
                eigenes.append(z["kind_text"])
        d["tutor"] = "claude"
        d["lauf"] = "claude"
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("eingesetzt:", d["id"], len(meine), "Zuege")


if __name__ == "__main__":
    main()
