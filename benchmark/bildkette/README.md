# Bildkette: Probe und Messung

Anlass: Thomas' Entscheidung vom 31.10.2026 (zweiter Schalter für die
Lehrperson, Auftrag vom 31.10.2026 aus dem Austausch mit den Partnern in
Siegen, nicht im Repo).
Gebaut ist die Kette in `tutoring/bildkette.py`, beschrieben in
`docs/Bildweiterleitung.md`. Hier liegt, womit sie geprüft wurde. Alle
Bilder sind erzeugt, keine Fotos von Kindern.

## 1 Machbarkeitsprobe (`probe.py`, vor dem Bau)

Frage: Kann das Vision-Modell am Spark (Qwen3-VL-30B) ein Foto einer
Heftseite so zerlegen, dass nur die gedruckte Aufgabe als Ausschnitt
hinausginge, ohne Handschrift, Namen, Gesichter, Logos und Metadaten?

`probe.py` erzeugt drei Bilder (A Heftseite mit Logo, Schulname,
Kindername, gedruckter Aufgabe, Handschrift, gezeichnetem Gesicht; B
Arbeitsblatt der Lehrperson, nur Druck; C schiefes Handyfoto mit
Handschrift direkt unter der Aufgabe), speichert sie als JPEG mit Exif-GPS
und fragt den Spark über den Tunnel (`http://127.0.0.1:18000/v1`), ohne
die App: verorten (JSON-Liste `{"label", "bbox_2d"}`, Koordinaten 0 bis
1000), neu kodieren, maskieren, zuschneiden, Vision-Frage am Ausgehenden,
OCR des Ausgehenden. Braucht Pillow und httpx.

| Bild | Verortung | Ausgehend | Leak-Check | OCR |
|---|---|---|---|---|
| A | alle fünf Bereiche richtig | nur gedruckte Aufgabe | 4× false | vollständig |
| B | vier Aufgabenblöcke, Schulname als „name“ | JSON kaputt (fehlende Klammern); im ersten Lauf sauber | 4× false | vollständig |
| C | alle Bereiche richtig | Maske über der Handschrift schneidet in die Aufgabenzeile | 4× false | vollständig, „a = 8“ statt „g = 8“ |

Dauer: Verorten 4 bis 14 s (1.200 bis 2.200 Token ein), Prüfung 1,8 s, OCR
1,5 s. Exif nach dem Neukodieren: 0 Einträge. Folgerungen, alle gebaut:
JSON-Schema erzwingen; zweites, deterministisches Netz (Zahlenfolge der
OCR gegen die Abschrift, erkannte Entitäten dürfen nicht vorkommen); Masken
gewinnen gegen den Zuschnitt; Pixelarbeit in der Web-App, am Spark nur
Inferenz. Dateien: `*_original.jpg`, `*_boxen.png`, `*_ausgehend.jpg`,
`probe1.log`, `probe2.log`.

## 2 Messung (`messung.py`, mit der echten Kette)

```
set DJANGO_SETTINGS_MODULE=config.settings   (oder test_settings)
set DJANGO_SECRET_KEY=x
set SPARK_BASE_URL=http://127.0.0.1:18000/v1
python benchmark/bildkette/messung.py --anzahl 24 --seed 20261031 --kennung M1
```

Je Bild eine erzeugte Heftseite (1000 × 1300 auf einem Tisch 1200 × 1600):
gedruckte Aufgabe aus acht Vorlagen, drei davon mit Figurennamen (Lisa,
Herr Maier, Anna und Ben); zufällig dazu ein Kindername in Schreibschrift
(80 %), null bis zwei Zeilen Handschrift, manchmal 25 px in die Aufgabe
hinein (so schreiben Kinder), ein gezeichnetes Gesicht (40 %), ein Logo mit
Schulnamen (50 %), Schräglage 0 bis 6 Grad, drei Papier- und drei
Tischfarben. Die Abschrift holt der Lauf wie die App
(`spark.text_aus_bild`), dann läuft `bildkette.bereinigen`.

**Leckmessung, vom Modell unabhängig:** Jedes heikle Element wird beim
Erzeugen zusätzlich auf eine eigene Wahrheitsebene gezeichnet (Schwarzweiß,
mitgedreht). Nach dem Lauf wird gezählt, wie viele Pixel der Ebene im
Ausschnitt liegen und nicht unter einer Maske: über 2 % der Pixel eines
Elements zählt als Leck. Für die gedruckte Aufgabe wird umgekehrt gezählt,
wie viel davon erhalten ist.

Ausgabe je Lauf unter `ergebnisse/<kennung>/`: `NN_original.jpg`,
`NN_ausgehend.jpg` (nur bei bestanden), `messung.json` mit Zusammenfassung
und einer Zeile je Bild (Zusammenstellung, Abschrift, Ergebnis oder Art
der Sperre, Masken, Lecks je Element, Anteil erhaltener Aufgabe, Dauer).

### Ergebnis M1 (31.10.2026, Seed 20261031, 24 Bilder)

| Maß | M1 |
|---|---|
| bestanden / blockiert | 19 / 5 |
| blockiert nach Art | 5× `bild_leak`, alle bei gedrucktem Figurennamen (2× OCR-Regel, 3× Urteil „Name“) |
| ohne gedruckten Namen | 17 von 17 bestanden |
| mit gedrucktem Namen | 2 von 7 bestanden, 1 davon über die Nachmaskierung (Bild 08, „Herr Maier“ geschwärzt) |
| Lecks unter den 19 | 0; sichtbarer Anteil je Element 0,0 |
| gedruckte Aufgabe erhalten | Median 1,0; Bilder 05, 06, 07 mit 0,72 bis 0,82 (Handschrift in der Aufgabenzeile, Maske gewinnt) |
| Dauer Kette | Median 7,7 s, 5,0 bis 12,7 s; gesamt mit Abschrift Median 10,2 s |

Vollständig in `ergebnisse/M1/messung.json`. Einordnung in
`docs/Bildweiterleitung.md` Abschnitt 4 und 5.
