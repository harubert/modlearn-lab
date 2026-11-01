"""Misst, wie viele Namen die Erkennung des Privacy Shield wirklich findet.

Anlass, und er ist ernst: Im Verlauf einer echten Sitzung stand unter
"hinausgegangen" der Satz "Anna Berger kauft 6 Packungen mit je 8 Stiften" -
im Klartext, mit Namen. Die Erkennung hatte nichts gefunden, der Leak-Check
hat nichts gemerkt (er prueft gegen die ERKANNTEN Zeichenketten), und damit
ist ein echter Name an einen Anbieter gegangen.

Eine erste Messung ergab fuenf von neun. Dieser Befehl macht die Messung
wiederholbar, damit jede Aenderung am Prompt belegt statt geglaubt wird.
"""

import json
import re

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

# Texte, wie sie im Unterricht wirklich vorkommen. Zu jedem steht, was
# gefunden werden MUSS.
PROBEN = [
    ("Anna Berger kauft 6 Packungen mit je 8 Stiften. Wie viele Stifte sind das?",
     ["Anna Berger"]),
    ("Anna Berger hat 6 Packungen mit je 8 Stiften gekauft.", ["Anna Berger"]),
    ("Lena kauft 6 Packungen mit je 8 Stiften.", ["Lena"]),
    ("Mein Name ist Lukas Fischer und ich verstehe die Aufgabe nicht.",
     ["Lukas Fischer"]),
    ("Tobias Maier fährt 12 km mit dem Rad.", ["Tobias Maier"]),
    ("Frau Hofer teilt 24 Äpfel auf 6 Kinder auf.", ["Hofer"]),
    ("Ich heiße Sarah und habe 15 Murmeln.", ["Sarah"]),
    ("In der Klasse von Herrn Gruber sind 28 Kinder.", ["Gruber"]),
    ("Paul und Marie teilen sich 36 Bonbons.", ["Paul", "Marie"]),
    ("Emre und Fatma kaufen zusammen 18 Stifte.", ["Emre", "Fatma"]),
    ("Der Schüler Jonas braucht Hilfe bei Aufgabe 3.", ["Jonas"]),
    ("Meine Lehrerin Frau Dr. Wieser hat das erklärt.", ["Wieser"]),
    # Zwei ohne Namen: Was hier gefunden wird, ist ein Fehlalarm.
    ("In einer Schachtel sind 6 Packungen mit je 8 Stiften.", []),
    ("Ein Zug fährt um 9:35 Uhr in Bregenz ab und kommt um 12:20 Uhr an.", []),
]

# Der Prompt, wie er heute im Betrieb steht.
ALT = (
    "Du findest Personennamen in einem deutschen Text. Gib ausschließlich ein "
    "JSON-Array zurück, ohne Einleitung und ohne Kommentar, in dieser Form:\n"
    '[{"text": "Anna Berger", "typ": "PERS"}]\n'
    "Aufgenommen werden nur echte Personennamen, also Vornamen, Nachnamen oder "
    "beides zusammen. Nicht aufgenommen werden: Ortsnamen, Firmennamen, "
    "Schulfächer, Monatsnamen, Wochentage und gewöhnliche Wörter.\n"
    "Kommt kein Name vor, antworte mit einem leeren Array: []"
)

# Der Gegenentwurf. Drei Unterschiede, jeder mit einem Grund:
#
# 1. Kein Beispielname im Prompt, der auch im Text vorkommen koennte. "Anna
#    Berger" stand als Beispiel drin und wurde im Text genau deshalb
#    uebersehen: Das Modell hielt es fuer die Schablone.
# 2. Die Anweisung kippt von Vorsicht auf Vollstaendigkeit. Ein Fehlalarm
#    kostet ein maskiertes Wort, ein uebersehener Name kostet eine
#    Datenschutzverletzung. Die beiden Fehler sind nicht gleich teuer.
# 3. Anreden werden ausdruecklich genannt. "Frau Hofer" und "Herrn Gruber"
#    wurden uebersehen, obwohl gerade Lehrpersonennamen haeufig so
#    dastehen.
NEU = (
    "Du suchst in einem deutschen Text nach allem, was der Name einer Person "
    "sein könnte.\n"
    "\n"
    "Nimm auf: Vornamen, Nachnamen, beides zusammen, und den Namen nach einer "
    "Anrede wie Herr, Frau, Herrn, Dr. oder Prof. Nimm auch Namen auf, die "
    "nicht deutsch klingen.\n"
    "Nimm NICHT auf: Orte, Länder, Firmen, Marken, Schulfächer, Monate, "
    "Wochentage, Wochentagsnamen und gewöhnliche Wörter.\n"
    "\n"
    "IM ZWEIFEL AUFNEHMEN. Ein Wort zu viel zu nennen kostet nichts. Einen "
    "Namen zu übersehen bedeutet, dass er das Haus verlässt.\n"
    "\n"
    "Antworte ausschließlich mit einem JSON-Array, ohne Einleitung, ohne "
    "Kommentar, ohne Codeblock. Jeder Eintrag hat die Form "
    '{"text": "<genau so wie im Text>", "typ": "PERS"}. '
    "Der Wert von \"text\" muss Zeichen für Zeichen im Text vorkommen.\n"
    "Kommt kein Name vor: []"
)

_ARRAY = re.compile(r"\[.*?\]", re.DOTALL)


class Command(BaseCommand):
    help = "Misst die Trefferquote der Namenserkennung."

    def add_arguments(self, parser):
        parser.add_argument("--laeufe", type=int, default=1)

    def handle(self, *args, **optionen):
        laeufe = optionen["laeufe"]
        varianten = (
            ("ALT (im Betrieb)", [ALT]),
            ("NEU", [NEU]),
            ("BEIDE, vereinigt", [ALT, NEU]),
        )
        for name, prompts in varianten:
            self.stdout.write(f"\n===== {name} =====")
            self._messen(prompts, laeufe)

    def _messen(self, prompts, laeufe):
        """Gemessen wird am ausgehenden Text, nicht an der Fundliste.

        Die Frage ist nicht, ob das Modell die Zeichenkette "Anna Berger"
        genannt hat, sondern ob nach dem Maskieren noch ein Name dasteht.
        Zwei Funde "Anna" und "Berger" leisten dasselbe.
        """
        durch = 0
        offen = 0
        fehlalarme = 0

        for text, noetig in PROBEN:
            treffer = set()
            for prompt in prompts:
                for _ in range(laeufe):
                    treffer |= set(self._fragen(prompt, text))

            # So maskieren, wie der Shield es taete: laengste Funde zuerst.
            ausgehend = text
            for fund in sorted(treffer, key=len, reverse=True):
                ausgehend = ausgehend.replace(fund, "[PERS]")

            stehengeblieben = [n for n in noetig if n in ausgehend]
            durch += len(noetig) - len(stehengeblieben)
            offen += len(stehengeblieben)
            if not noetig:
                fehlalarme += len(treffer)

            if stehengeblieben:
                zeichen = "STEHT NOCH"
            elif not noetig and treffer:
                zeichen = "alarm     "
            else:
                zeichen = "maskiert  "
            self.stdout.write(f"  [{zeichen}] {ausgehend[:70]}")

        gesamt = durch + offen
        quote = durch / gesamt * 100 if gesamt else 0
        self.stdout.write(
            f"\n  Maskiert: {durch} von {gesamt} ({quote:.0f} %) · "
            f"stehengeblieben: {offen} · Fehlalarme: {fehlalarme}"
        )

    def _fragen(self, prompt, text):
        rumpf = {
            "model": settings.SPARK_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": 300,
            "temperature": 0.0,
        }
        try:
            with httpx.Client(timeout=settings.SPARK_TIMEOUT_SECONDS) as client:
                antwort = client.post(
                    f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
                )
                antwort.raise_for_status()
                roh = antwort.json()["choices"][0]["message"]["content"] or ""
        except Exception:  # noqa: BLE001 - ein Ausfall zaehlt als kein Fund
            return []

        treffer = _ARRAY.search(roh)
        if not treffer:
            return []
        try:
            eintraege = json.loads(treffer.group(0))
        except json.JSONDecodeError:
            return []
        return [
            str(e.get("text", "")).strip()
            for e in eintraege
            if isinstance(e, dict) and str(e.get("text", "")).strip() in text
        ]
