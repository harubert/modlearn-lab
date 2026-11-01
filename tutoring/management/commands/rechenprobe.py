"""Laesst den Spark zehn Textaufgaben mehrfach loesen.

Anlass: In einem Durchlauf hat ein Kind durchgehend addiert statt
multipliziert, und die Hilfe hat es erst am Schluss gemerkt. Bevor daraus
eine Aenderung am Prompt wird, muss die Frage davor beantwortet sein: Rechnet
das Modell ueberhaupt verlaesslich?

Die Aufgaben decken die Bandbreite ab, um die es Freitag geht: Volksschule
bis Unterstufe, vom Einmaleins bis zu Prozent und Verhaeltnis. Jede laeuft
mehrfach, weil ein einzelner Treffer nichts beweist; erst die Streuung ueber
vier Laeufe sagt etwas.

Die Bewertung macht dieser Befehl absichtlich nicht selbst. Er sammelt die
Antworten und schreibt sie heraus; wer sie liest, entscheidet.
"""

import json
import re
import time

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

# Jede Aufgabe mit der Loesung, die herauskommen muss, und einem Muster, das
# sie in einem Fliesstext findet. Das Muster ist nur eine Vorsortierung: Was
# es nicht findet, wird von Hand angesehen.
AUFGABEN = [
    {
        "nr": 1,
        "stufe": "Volksschule, 3. Klasse",
        "text": "In einer Schachtel sind 6 Packungen mit je 8 Stiften. "
                "Wie viele Stifte sind das?",
        "loesung": "48",
        "muster": r"\b48\b",
    },
    {
        "nr": 2,
        "stufe": "Volksschule, 3. Klasse",
        "text": "Ein Seil ist 12 Meter lang. Es wird in Stücke zu je 3 Meter "
                "geschnitten. Wie viele Stücke bekommt man?",
        "loesung": "4",
        "muster": r"\b4\b",
    },
    {
        "nr": 3,
        "stufe": "Volksschule, 4. Klasse",
        "text": "In der Schulbibliothek stehen 128 Bücher. Am Montag werden 36 "
                "ausgeliehen, am Dienstag werden 19 zurückgebracht. Wie viele "
                "Bücher stehen dann im Regal?",
        "loesung": "111",
        "muster": r"\b111\b",
    },
    {
        "nr": 4,
        "stufe": "Volksschule, 4. Klasse",
        "text": "Ein Kinoticket kostet 7,50 Euro. Eine Gruppe von 14 Kindern "
                "geht ins Kino. Wie viel zahlen sie zusammen?",
        "loesung": "105 Euro",
        "muster": r"\b105\b",
    },
    {
        "nr": 5,
        "stufe": "Unterstufe, 1. Klasse",
        "text": "Ein Zug fährt um 9:35 Uhr ab und kommt um 12:20 Uhr an. "
                "Wie lange dauert die Fahrt?",
        "loesung": "2 Stunden 45 Minuten",
        "muster": r"2\s*(?:h|Stunden?).{0,20}45|165\s*Minuten",
    },
    {
        "nr": 6,
        "stufe": "Unterstufe, 2. Klasse",
        "text": "Ein Rechteck ist 14 cm lang und 9 cm breit. Wie groß ist der "
                "Umfang, wie groß der Flächeninhalt?",
        "loesung": "Umfang 46 cm, Fläche 126 cm²",
        "muster": r"\b46\b.*\b126\b|\b126\b.*\b46\b",
    },
    {
        "nr": 7,
        "stufe": "Unterstufe, 2. Klasse",
        "text": "Drei Viertel einer Klasse mit 24 Kindern fahren mit dem Rad "
                "zur Schule. Wie viele Kinder sind das, und wie viele kommen "
                "anders zur Schule?",
        "loesung": "18 mit dem Rad, 6 anders",
        "muster": r"\b18\b.*\b6\b|\b6\b.*\b18\b",
    },
    {
        "nr": 8,
        "stufe": "Unterstufe, 3. Klasse",
        "text": "Ein Pullover kostet 60 Euro und wird um 15 Prozent reduziert. "
                "Wie viel kostet er jetzt?",
        "loesung": "51 Euro",
        "muster": r"\b51\b",
    },
    {
        "nr": 9,
        "stufe": "Unterstufe, 3. Klasse",
        "text": "In einer Klasse sind 28 Kinder. Mädchen und Buben stehen im "
                "Verhältnis 3 zu 4. Wie viele Mädchen sind in der Klasse?",
        "loesung": "12 Mädchen (und 16 Buben)",
        "muster": r"\b12\b",
    },
    {
        "nr": 10,
        "stufe": "Unterstufe, 4. Klasse",
        "text": "Ein Wasserhahn füllt einen Behälter mit 180 Litern in 12 "
                "Minuten. Wie lange braucht er für 300 Liter?",
        "loesung": "20 Minuten",
        "muster": r"\b20\b",
    },
]

SYSTEM = (
    "Du löst Textaufgaben aus der Schule. Rechne sorgfältig und Schritt für "
    "Schritt. Schreibe zum Schluss eine Zeile, die genau so beginnt:\n"
    "ERGEBNIS: <das Ergebnis mit Einheit>"
)

_ERGEBNIS = re.compile(r"ERGEBNIS:\s*(.+)", re.IGNORECASE)


class Command(BaseCommand):
    help = "Laesst den Spark zehn Textaufgaben mehrfach loesen."

    def add_arguments(self, parser):
        parser.add_argument("--laeufe", type=int, default=4)
        parser.add_argument("--temperatur", type=float, default=0.3)
        parser.add_argument("--json", dest="als_json", default="")

    def handle(self, *args, **optionen):
        laeufe = optionen["laeufe"]
        alles = []

        for aufgabe in AUFGABEN:
            treffer = 0
            zeilen = []
            for lauf in range(laeufe):
                begonnen = time.monotonic()
                try:
                    antwort = self._loesen(aufgabe["text"], optionen["temperatur"])
                except Exception as fehler:  # noqa: BLE001 - hier zaehlt jeder Ausfall
                    antwort = f"<Ausfall: {type(fehler).__name__}: {fehler}>"
                dauer = time.monotonic() - begonnen

                gefunden = _ERGEBNIS.search(antwort)
                ergebnis = gefunden.group(1).strip() if gefunden else "<keine ERGEBNIS-Zeile>"
                passt = bool(re.search(aufgabe["muster"], ergebnis))
                if passt:
                    treffer += 1
                zeilen.append({
                    "lauf": lauf + 1, "ergebnis": ergebnis, "passt": passt,
                    "sekunden": round(dauer, 1), "voll": antwort,
                })

            alles.append({**aufgabe, "treffer": treffer, "laeufe": laeufe, "zeilen": zeilen})
            self.stdout.write(
                f"\n--- Aufgabe {aufgabe['nr']} ({aufgabe['stufe']}) "
                f"– erwartet: {aufgabe['loesung']} – {treffer}/{laeufe}"
            )
            self.stdout.write(f"    {aufgabe['text']}")
            for z in zeilen:
                zeichen = "ja " if z["passt"] else "NEIN"
                self.stdout.write(
                    f"    [{zeichen}] {z['sekunden']:>5.1f}s  {z['ergebnis'][:110]}"
                )

        gesamt = sum(a["treffer"] for a in alles)
        moeglich = len(AUFGABEN) * laeufe
        self.stdout.write(f"\n==== {gesamt}/{moeglich} nach Muster richtig ====")
        for a in alles:
            if a["treffer"] < a["laeufe"]:
                self.stdout.write(f"  Aufgabe {a['nr']}: {a['treffer']}/{a['laeufe']}")

        if optionen["als_json"]:
            with open(optionen["als_json"], "w", encoding="utf-8") as datei:
                json.dump(alles, datei, ensure_ascii=False, indent=1)
            self.stdout.write(f"Vollständige Antworten in {optionen['als_json']}")

    def _loesen(self, text, temperatur):
        rumpf = {
            "model": settings.SPARK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": text},
            ],
            "max_tokens": 1200,
            "temperature": temperatur,
        }
        with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
            antwort = client.post(
                f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
            )
            antwort.raise_for_status()
            daten = antwort.json()
        return (daten["choices"][0]["message"]["content"] or "").strip()
