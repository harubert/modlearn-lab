"""Misst, was passiert, wenn viele gleichzeitig eine Hilfe holen.

Anlass: In einem Hoersaal scannen dreissig Leute denselben QR-Code und
druecken kurz darauf alle auf denselben Knopf. Der Spark ist ein Rechner,
kein Rechenzentrum. Bevor das vor Publikum passiert, sollte jemand wissen,
wie lange die dreissigste Antwort braucht.

Gemessen wird der Weg, der im Betrieb zaehlt: dieselbe Anfrage, die eine
Hilfestufe ausloest, mit demselben Systemprompt und derselben Laenge.
"""

import statistics
import threading
import time

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

from tutoring import levels

AUFGABE = (
    "Die Aufgabe lautet:\n"
    "In einer Schachtel sind 6 Packungen mit je 8 Stiften. "
    "Wie viele Stifte sind das?"
)


class Command(BaseCommand):
    help = "Misst die Antwortzeit bei gleichzeitigen Anfragen."

    def add_arguments(self, parser):
        parser.add_argument("--gleichzeitig", type=int, default=10)
        parser.add_argument("--stufe", type=int, default=1)

    def handle(self, *args, **optionen):
        anzahl = optionen["gleichzeitig"]
        system = levels.system_prompt(optionen["stufe"], levels.ALTERSKLASSE_STANDARD)

        ergebnisse = []
        sperre = threading.Lock()

        def einer(nr):
            begonnen = time.monotonic()
            fehler = ""
            zeichen = 0
            try:
                zeichen = len(self._anfragen(system))
            except Exception as f:  # noqa: BLE001 - jeder Ausfall zaehlt gleich
                fehler = f"{type(f).__name__}: {f}"[:80]
            dauer = time.monotonic() - begonnen
            with sperre:
                ergebnisse.append({"nr": nr, "s": dauer, "zeichen": zeichen,
                                   "fehler": fehler})

        self.stdout.write(f"{anzahl} Anfragen gleichzeitig, Stufe {optionen['stufe']} ...")
        begonnen = time.monotonic()
        faeden = [threading.Thread(target=einer, args=(i + 1,)) for i in range(anzahl)]
        for f in faeden:
            f.start()
        for f in faeden:
            f.join()
        gesamt = time.monotonic() - begonnen

        ergebnisse.sort(key=lambda e: e["s"])
        zeiten = [e["s"] for e in ergebnisse if not e["fehler"]]
        ausfaelle = [e for e in ergebnisse if e["fehler"]]

        for e in ergebnisse:
            zustand = e["fehler"] or f"{e['zeichen']} Zeichen"
            self.stdout.write(f"  {e['s']:6.1f}s  {zustand}")

        self.stdout.write("")
        if zeiten:
            self.stdout.write(
                f"  schnellste {min(zeiten):.1f}s | Mitte {statistics.median(zeiten):.1f}s "
                f"| langsamste {max(zeiten):.1f}s"
            )
        self.stdout.write(f"  alle fertig nach {gesamt:.1f}s, Ausfaelle: {len(ausfaelle)}")

    def _anfragen(self, system):
        rumpf = {
            "model": settings.SPARK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": AUFGABE},
            ],
            "max_tokens": 400,
            "temperature": 0.3,
        }
        with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
            antwort = client.post(
                f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
            )
            antwort.raise_for_status()
            daten = antwort.json()
        return (daten["choices"][0]["message"]["content"] or "").strip()
