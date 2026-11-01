# Nutzen der Bildweiterleitung: Messung N1

Anlass: Thomas, 31.10.2026. Vor der Entscheidung über Regel 3a („Bilder gehen
nie in die Cloud“) will er Beispiele sehen: „Erst wenn wir den möglichen Nutzen
kennen, können wir über die Notwendigkeit diskutieren, ob wir die Bilder
brauchen oder nicht.“ Dann: „mach 2, die Prüfung mit den vorhandenen Bildern.“

## Frage

Was bringt es der Qualitätssicherung, wenn neben der Abschrift des Spark auch
der bereinigte Ausschnitt an das externe Modell geht?

## Material

Die amtlichen Aufgaben des Siegen-Marathons (iKMPLUS 4 und 8, Matura; Ordner
`Siegen_STEM-Edu-AI_2027/aufgaben`), davon die 38 mit Abbildung, die sich
automatisch gegen den Lösungsschlüssel bewerten lassen (12 weitere sind
Konstruktionsaufgaben ohne bewertbaren Schlüssel). Die Bilder des Marathons
sind nur die Abbildungen; ein Kind fotografiert aber die ganze gedruckte
Aufgabe. Deshalb setzt `messung.py` je Aufgabe eine Seite: Text, Abbildung an
der Stelle des Platzhalters, Antwortmöglichkeiten darunter (Arial 30 px, 1240
px breit, JPEG). Diese Seite ist das „Foto“.

## Drei Bedingungen, dieselbe Kette wie in der App

`cloud.geprueft_fragen`: umformulieren ohne Personen, erkennen, maskieren,
Leak-Check, senden, zurücksetzen. Gegenstelle gpt-6.1-sol, Spark wie in der
App (Abschrift mit `spark.text_aus_bild`, Ausschnitt mit `bildkette.bereinigen`).

| | Was hinausgeht | Entspricht |
|---|---|---|
| A | die Abschrift des Spark von der Seite, nur Text | App mit Qualitätssicherung, ohne zweiten Schalter |
| B | Abschrift plus bereinigter Ausschnitt | App mit beiden Schaltern; sperrt die Bildkette, gilt A |
| C | der amtliche Aufgabentext, nur Text | Referenz: perfekte Abschrift, aber keine Abbildung |

Alle drei bekommen dieselbe Formatvorgabe für die Antwortzeile
(`prompts.format_anweisung` des Marathons); bewertet wird mit dessen Scorer
(`score.bewerte`), also mit denselben Regeln wie im Paper.

## Aufruf

```
set DJANGO_SETTINGS_MODULE=test_settings
set DJANGO_SECRET_KEY=x
set SPARK_BASE_URL=http://127.0.0.1:18000/v1
set SPARK_MODEL=qwen3.6-35b-a3b
python benchmark/bildnutzen/messung.py --kennung N1 --ausschnitte ^
    --schluesseldatei <Datei mit dem OpenAI-Schlüssel> ^
    --marathon <...>/Siegen_STEM-Edu-AI_2027/A_tutor/benchmark
```

Der Schlüssel wird aus der Datei gelesen und nie ausgegeben. Ergebnis unter
`ergebnisse/<kennung>/messung.json` (eine Zeile je Aufgabe mit Abschrift,
Antworten, Bewertung, Masken, Dauern), mit `--ausschnitte` dazu je Aufgabe
die gesetzte Seite und der Ausschnitt, der hinausging.

## Ergebnis N1 (31.10.2026, 38 Aufgaben, gpt-6.1-sol, Spark Qwen3.6-35B-A3B)

| | A Abschrift | B Abschrift + Ausschnitt | C amtlicher Text |
|---|---|---|---|
| alle (38) | 12 | **29** | 11 |
| Matura (20) | 6 | 15 | 5 |
| iKMPLUS 8 (10) | 5 | 8 | 5 |
| iKMPLUS 4 (8) | 1 | 6 | 1 |

- B ist in 17 Aufgaben richtig, in denen A falsch ist; umgekehrt nie.
- Die Bildkette hat 30 von 38 Ausschnitten freigegeben; davon löst B 28.
  Die zwei übrigen (MAT-2024-HT-05, -10) sagt gpt-6.1 ehrlich „nicht
  bestimmbar": sechs Geraden bzw. ein Graph im Ausschnitt reichten ihm nicht.
- 8 gesperrt, dann gilt A: 4× `bild_fremde_zahlen` (die Abbildung trägt
  Zahlen, die in der Abschrift nicht stehen, etwa Achsenbeschriftungen; die
  Regel ist für Heftfotos mit Handschrift gebaut und trifft hier den
  Normalfall einer Grafik), 2× `bild_leak` (IKM-PRIM-25 Namen an Säulen,
  IKM-SEK-14 Postleitzahl und Ort in der Angabe: beides richtig gesperrt),
  1× keine Verortung, 1× Ausschnitt unlesbar.
- C (perfekter Text, keine Abbildung) ist so schlecht wie A: Nicht die
  Abschrift fehlt, die Abbildung fehlt. Ohne Bild kann die
  Qualitätssicherung bei diesen Aufgaben nicht helfen, egal wie gut das
  Modell ist.
- Dauer je Aufgabe (alle drei Bedingungen) Median 46 s; Abschrift 3,9 s,
  Bildkette 10,1 s, jeder Weg nach draußen rund 11 s (davon zwei
  Spark-Aufrufe für Umformulierung und Namenserkennung). Token hinaus:
  Median 310 (A) gegen 1 409 (B), der Ausschnitt kostet rund 1 100 Token,
  also 0,2 Cent je Aufgabe bei gpt-6.1-sol.
- Masken in 30 Ausschnitten: 6 insgesamt. Die Seiten sind gesetzt, nicht
  fotografiert: kein Kindername, keine Handschrift; die Kette hatte hier
  wenig zu schwärzen. Was sie bei echten Heftfotos leistet, steht in
  `benchmark/bildkette/README.md` (M1).

Dateien: `ergebnisse/N1/messung.json`, je Aufgabe `<id>_seite.jpg` (die
gesetzte Seite, das „Foto") und `<id>_ausschnitt.jpg` (was hinausging).

## Ergebnis N2 (1.11.2026, alle 50 Bildaufgaben, gpt-6.1-sol, Spark Qwen3.6-35B-A3B)

Thomas (über Siegen, 1.11.): Bilder dürfen hinaus, wenn die Lehrperson das beim
Start der Sitzung wählt; er wünscht den Probelauf mit allen Bildaufgaben, nicht
nur den 38 mit Schlüssel. `messung.py --alle` fährt deshalb auch die 12
Konstruktions- und offenen Aufgaben ohne Schlüssel durch dieselbe Kette; ihre
Antworten sind nicht automatisch bewertet, sondern von Claude gegen Aufgabe und
Abbildung beurteilt (unten). Stand: Commit 1378f66 plus `--alle`; die App-Kette
unverändert.

### Die 38 mit Schlüssel (Scorer des Marathons, wie N1)

| | A Abschrift | B Abschrift + Ausschnitt | C amtlicher Text |
|---|---|---|---|
| alle (38) | 12 | **29** | 10 |
| Matura (20) | 6 | 16 | 4 |
| iKMPLUS 8 (10) | 5 | 7 | 5 |
| iKMPLUS 4 (8) | 1 | 6 | 1 |

Dasselbe Bild wie N1 (12 / 29 / 11): B ist in 17 Aufgaben richtig, in denen A
falsch ist, umgekehrt nie. Von den 29 freigegebenen Ausschnitten mit Schlüssel
löst B 28; die eine Ausnahme ist MAT-2024-HT-05 (sechs Geraden, „nicht
bestimmbar“).

### Die 12 ohne Schlüssel (Beurteilung von Hand: Antwort richtig und konkret genug für eine geprüfte Lösung)

| | A | B | C |
|---|---|---|---|
| ohne Schlüssel (12) | 9 | **12** | 8 |

- Acht der zwölf brauchen die Abbildung nicht (Punkt im Koordinatensystem aus
  einer Geradengleichung, Histogrammhöhen aus einer Tabelle, Einheitskreis,
  Skizze einer Polynomfunktion, Hustensaftflasche, Winkel im Rechteck, Kreis-
  gegen Säulendiagramm, Zahlenstrahl): Alle drei Bedingungen lösen sie.
- Vier brauchen sie. MAT-2026-HT-04 (Kräftesumme auf dem Gitter): B zeichnet
  „zwei Kästchen nach links, ein Kästchen nach unten“ – gegen die Abbildung
  geprüft richtig (F_N = (−2 | 4), F_G = (0 | −5)); A und C nennen nur die
  Richtung „hangabwärts“. IKM-PRIM-01 (Spiegelbild): B beschreibt die Figur
  Kästchen für Kästchen richtig (4 rechts, 1 runter, 2 links, 4 runter, 2
  rechts, 1 runter, 4 links); A und C können ohne Bild nichts zeichnen und
  sagen das. MAT-2024-HT-15 (Tangente mit Steigung 5 am v-Graphen): B liest
  t₁ ≈ 4 s ab, gegen den Graphen geprüft plausibel (Steigung bei t = 4 etwa
  5 m/s²); A und C sagen „ohne Abbildung nicht ablesbar“. MAT-2026-HT-19
  (Säule ergänzen): die Bildkette sperrt (unlesbar), B gilt wie A; beide
  rechnen aus der Abschrift 48 : 0,6 · 0,25 = 20 richtig, C hat die Werte
  nicht.
- Zusammen über alle 50: A 21, B **41**, C 18.

### Bildkette: 37 freigegeben, 13 gesperrt

| Grund | Anzahl | Aufgaben |
|---|---|---|
| `bild_fremde_zahlen` (Zahlen im Ausschnitt, die nicht in der Abschrift stehen) | 8 | MAT-2026-HT-18, MAT-2025-HT-12, MAT-2025-HT-20, MAT-2024-HT-07, IKM-SEK-02, IKM-SEK-07, IKM-SEK-14, IKM-PRIM-13 |
| `bild_leak` (ein Name im Ausschnitt erkannt) | 3 | IKM-SEK-19, IKM-SEK-27, IKM-PRIM-25 |
| `bild_unbrauchbar` (Ausschnitt nicht mehr lesbar) | 2 | MAT-2026-HT-19, IKM-SEK-25 |

Je Stufe: iKMPLUS 4 8 von 10 frei, iKMPLUS 8 7 von 13, Matura 22 von 27. Die
acht Sperren wegen fremder Zahlen sind wie in N1 Achsenbeschriftungen und
Werte in Grafiken, die die Abschrift nicht hat: Die Regel ist für Heftfotos
mit Handschrift gebaut und trifft hier den Normalfall einer Grafik; von diesen
acht löst B dann (als A) nur eine (IKM-SEK-14). Die drei Namenssperren sind
richtig: Säulen mit Vornamen (IKM-PRIM-25), Namen in Diagrammen (IKM-SEK-19,
-27). IKM-SEK-14 (Postleitzahl und Ort) war in N1 ein Leak, in N2 eine
Zahlensperre: Die Namenserkennung des Spark ist nicht deterministisch, die
Sperre hielt beide Male.

### Lecks und Masken

- Kein einziger Textweg wurde vom Leak-Check blockiert (A, B, C: 0 von 150).
- Masken in den 37 freigegebenen Ausschnitten: 3 (MAT-2024-HT-12 eine
  Handschrift-Maske, IKM-PRIM-20 und -23 je ein Name). Die Seiten sind gesetzt,
  nicht fotografiert: kein Kindername, keine Handschrift, kein Gesicht; was
  die Kette bei echten Heftfotos leistet, steht in `benchmark/bildkette/README.md`
  (M1). Ein Leck, also ein Name, ein Gesicht oder Handschrift im Ausschnitt,
  der hinausging, ist in den 37 Ausschnitten (`<id>_ausschnitt.jpg`) nicht zu
  sehen; drei Namen hat die Kette vorher gesperrt.

### Latenz und Kosten

- Je Aufgabe (Abschrift, Bildkette, drei Wege hinaus) Median 45 s, längste
  108 s (IKM-SEK-19). Abschrift 3,8 s, Bildkette 9,0 s, jeder Weg hinaus
  rund 11 s (A 11,0, B 10,9, C 10,9: der Ausschnitt kostet keine Zeit).
- Token hinaus: Median 299 (A) gegen 1 187 (B), der Ausschnitt also rund 890
  Token, etwa 0,2 Cent je Aufgabe bei gpt-6.1-sol.
- Für die App heißt das: Die Qualitätssicherung mit Bild dauert vom Foto bis
  zur geprüften Lösung rund 24 s (Abschrift, Bildkette, ein Weg hinaus), ohne
  Bild rund 15 s; beides läuft im Hintergrund, bevor die erste Hilfe kommt.

Dateien: `ergebnisse/N2/messung.json`, je Aufgabe `<id>_seite.jpg` und, wo
freigegeben, `<id>_ausschnitt.jpg`.
