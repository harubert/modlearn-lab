# Bildweiterleitung: der zweite Schalter und die Bildkette

Stand 31.10.2026, Zweig `bildweiterleitung` (ab `main` f222a4c). Nicht auf
`main`, nicht ausgerollt.

## 1 Auftrag

Thomas, 31.10.2026, über die Siegen-Sitzung: „Lehrperson wählt ob
Frontier-Modell oder nicht (gibt es jetzt schon) und kann außerdem wählen,
ob ein Bild weitergeleitet wird oder nicht. Mit Erklärung.“ Und: „sag ai
lab, er soll das bauen.“ Vollständiger Auftrag:
Auftrag vom 31.10.2026 aus dem Austausch mit den Partnern in Siegen (nicht im Repo),
unsere Antwort mit den Abweichungen daneben.

Das hebt die Regel aus CLAUDE.md 3a („Bilder gehen nie in die Cloud“,
nicht verhandelbar) auf. Die CLAUDE.md ist in diesem Zweig **nicht**
geändert: Die Regel steht dort als Thomas' Entscheidung vom 21.09., und
die Aufhebung trägt er selbst ein oder sagt sie direkt. Vorschlag für den
neuen Wortlaut unter 7.

Warum es lohnt (Paper A, 126 amtliche Items, Bildaufgaben): App-Modell
65 %, GPT-5 78 %, GPT-6.1 97 %. Die Qualitätssicherung bekam bisher nur die
Abschrift des Fotos; bei Skizzen, Brüchen, Hochzahlen geht dabei genau das
verloren, woran das Frontier-Modell besser wäre.

## 2 Was gebaut ist

**Der Schalter.** In der Stunde der Lehrperson (Mathematik), unter
„Qualitätssicherung einschalten“: „Auch Fotos der Aufgabe prüfen lassen
(zugeschnitten und bereinigt)“. Nur anklickbar, wenn die Qualitätssicherung
an ist (`static/js/qsschalter.js`), am Server noch einmal verundet
(`views.lehrperson_uebersicht`), Standard aus, je Sitzung gespeichert
(`LearningSession.cloud_images_enabled`, Migration 0028). Daneben die
Erklärung in der Wortwahl des Auftrags („zugeschnitten und bereinigt“, nicht
„anonymisiert“) und der Link „Mehr erfahren“ auf `/bildpruefung/`
(`core/templates/core/bildpruefung.html`): Kette, Grenzen, was nie
hinausgeht, was die Lehrperson tun kann.

**Die Bildkette** (`tutoring/bildkette.py`), fail-closed, in dieser Folge:

1. Laden und neu kodieren (Pillow, neue Abhängigkeit): Ausrichtung aus dem
   Exif anwenden, dann Exif samt GPS weg, RGB, lange Kante höchstens 1600 px,
   frisches Bild ohne `info` (Pillow nähme ein Exif aus `bild.info` sonst
   stillschweigend mit).
2. Verorten: Qwen3-VL am Spark, Antwort durch ein JSON-Schema erzwungen
   (vLLM `response_format`), Kästchen 0 bis 1000 für gedruckte_aufgabe,
   handschrift, name, gesicht, logo. Unbrauchbare Einträge werden
   übergangen, nicht geraten.
3. Maskieren, dann zuschneiden: alles Heikle schwarz (plus 6 px Rand),
   danach Zuschnitt auf die Vereinigung der gedruckten Aufgaben (plus 12 px).
   Masken gewinnen gegen den Zuschnitt. Ohne gedruckten Bereich: gesperrt.
4. Prüfen, zweites Netz: (a) Frage an das Modell, ob auf dem Ausschnitt noch
   Handschrift, Name, Gesicht, Logo zu sehen ist (JSON-Schema, fehlender
   Schlüssel zählt als gesehen); (b) OCR des Ausschnitts, deterministisch
   gegen die Abschrift der App (`Task.text`): kein Regel- oder Namensfund
   der Abschrift lesbar (`shield.regelfunde`, `shield.namensfunde`, wie in
   der Textkette; fällt die Namenserkennung aus, ist der Weg zu), keine
   Zahl, die in der Abschrift nicht steht, mindestens eine Zahl der Aufgabe
   lesbar.
5. Nachmaskieren, genau einmal: Ist ein erkannter Name noch lesbar (Lisa
   kauft vier Packungen), zeigt das Modell, wo das Wort steht, die Stelle
   wird schwarz, und Schritt 4 läuft vollständig noch einmal. Das ist das
   Gegenstück zum Platzhalter der Textkette. Was danach noch beanstandet
   wird, sperrt.
6. Ergebnis: Ausschnitt als Data-URL, Masken je Typ, Dauer, Token. Der
   Ausschnitt geht in `cloud.geprueft_loesen(..., bild=...)` als
   `image_url` neben dem maskierten Text mit, mit dem Satz „Dazu ein
   Bildausschnitt: die gedruckte Aufgabe, zugeschnitten und bereinigt“, der
   auch im Verlauf unter „Das ist hinausgegangen“ steht.

**Was nie hinausgeht:** das Foto selbst, der Lösungsversuch des Kindes (als
Bild maskiert, als Text schickte die Qualitätssicherung ihn noch nie), ein
Ausschnitt, bei dem irgendein Schritt zweifelt. Scheitert die Kette, läuft
die Qualitätssicherung wie vor dem 31.10. nur mit der Abschrift.

**Wann sie läuft:** einmal je Aufgabe, vor dem ersten Zug, zusammen mit der
Qualitätssicherung (`views._bild_freigeben`), nur wenn beide Schalter an
sind, ein Foto da ist und der Weg offen ist (Zugang, Budget). Im Safe Chat
geht nie ein Bild mit (`ergebnis["bild"] is False`, Test).

**Transparenz und Protokoll.** Im Verlauf der Lehrperson, im Block der
Qualitätssicherung (`_qs_bild.html`): links das Foto des Kindes („bleibt im
Haus“), rechts der Ausschnitt, der hinausging, mit Masken je Typ und Dauer;
bei Sperre der Grund; war der Ausschnitt freigegeben und der Textweg
danach gesperrt, steht das so da. An der Aufgabe: `checked_image_check`,
`_reason`, `_sent`, `_masks`, `_ms`; der Ausschnitt stirbt mit der Sitzung
wie das Foto (Test). Im Forschungsprotokoll eine eigene Zeile je Prüfung,
Weg lokal, `bild_bestanden` oder `bild_gesperrt` mit Art, Masken je Typ als
Zählung, Token der Spark-Aufrufe; kein Bildinhalt auf keiner Stufe.

**Tests:** `tutoring/tests/test_bildkette.py`, 49 Prüfungen (Kette mit
nachgespieltem Spark, Nachmaskierung, Wege nach draußen, Schalter, Formular,
Verlauf, Protokoll, Erklärungsseite). Gesamt 1212 grün.

## 3 Proben am Spark (synthetische Bilder, 31.10.)

`benchmark/bildkette/probe.py` (erste Probe, ohne die App) und die echte
Kette mit der echten Abschrift (`spark.text_aus_bild`), drei Bilder: A
Heftseite (Logo, Schulname, Kindername in Schreibschrift, gedruckte Aufgabe
mit „Lisa“, Handschrift, gezeichnetes Gesicht), B Arbeitsblatt der
Lehrperson (nur Druck), C schiefes Handyfoto mit Handschrift direkt unter
der Aufgabe.

| Bild | Verortung | Ergebnis der Kette | Dauer |
|---|---|---|---|
| A | alle fünf Arten richtig verortet (Gesicht und Fußzeile einmal als „logo“, egal: maskiert ist maskiert) | bestanden, Ausschnitt nur die gedruckte Aufgabe; in einem Lauf sperrte die OCR-Regel wegen „Lisa“, mit Nachmaskierung bestanden (3 Namensmasken, davon eine daneben auf „Auf“ von „Aufgabe“) | 8,2 s, mit Nachmaskierung 12,5 s |
| B | vier Aufgabenblöcke, Schulname als „logo“ | bestanden, OCR vollständig | 8,6 s |
| C | Aufgaben, Handschrift, Name, Gesicht richtig | bestanden; Handschrift unter der Aufgabe maskiert, Aufgabe lesbar; OCR las „a = 8“ statt „g = 8“ | 8,3 s |

Beobachtungen: Ohne JSON-Schema kamen in 1 von 3 Antworten Klammern
abhanden; mit Schema nie. Mit Schema neigt das Modell dazu, alle Arten zu
„finden“ (Gesicht und Logo einmal als Kästchen über das ganze Bild); der
Prompt sagt deshalb ausdrücklich, dass fehlende Arten wegbleiben und die
leere Liste erlaubt ist. Das Urteil des Modells schwankt zwischen Läufen
bei gleichem Bild (Name ja/nein für „Lisa kauft“), deshalb entscheidet
nicht ein Urteil allein. Die Namenserkennung der Abschrift übersieht
„Lisa“ manchmal, wie in der Textkette (86 % gemessen); dann greift das
Urteil des Modells oder nichts, und „Lisa“ geht als Pixel hinaus. Das ist
die Grenze, die auf der Erklärungsseite steht.

## 4 Messung M1

`benchmark/bildkette/messung.py --anzahl 24 --seed 20261031 --kennung M1`:
24 erzeugte Heftseiten mit zufälligem Namen in Schreibschrift, null bis
zwei Zeilen Handschrift (auch in die Aufgabe hinein), Gesicht, Logo mit
Schulnamen, Schräglage, Tisch. Für jedes heikle Element gibt es eine
Wahrheitsebene; nach dem Lauf wird gezählt, wie viele Pixel davon im
Ausschnitt sichtbar blieben (Leckmessung, vom Modell unabhängig), und wie
viel der gedruckten Aufgabe erhalten ist. Rohdaten unter
`benchmark/bildkette/ergebnisse/M1/` (`messung.json`, Originale, Ausgehendes).

| Maß | M1 |
|---|---|
| Bilder | 24 (7 mit gedrucktem Figurennamen, 17 ohne) |
| bestanden | 19 (alle 17 ohne gedruckten Namen; 2 von 7 mit, davon 1 über die Nachmaskierung) |
| blockiert | 5, alle `bild_leak`, alle mit gedrucktem Figurennamen (2× OCR-Regel, 3× Urteil des Modells „Name“) |
| Lecks in den 19 durchgelassenen Ausschnitten | 0; sichtbarer Anteil jedes heiklen Elements 0,0 (Handschrift in 14 Bildern, Kindername 14, Gesicht 8, Logo 10) |
| gedruckte Aufgabe erhalten | Median 100 %; 3 Bilder mit 72 bis 82 %, dort lag Handschrift in der Aufgabenzeile und die Maske gewann |
| Dauer der Kette | Median 7,7 s (5,0 bis 12,7 s), dazu 2,5 s Abschrift; Median 2.550 Token ein |

Lesart: Nichts Heikles kam durch, weil die Kette im Zweifel sperrt und
weil die Masken vor dem Zuschnitt liegen. Der Preis ist die Nutzbarkeit:
Aufgaben mit gedrucktem Figurennamen gehen meist nicht als Bild hinaus
(5 von 7), und bei Handschrift in der Aufgabenzeile fehlt ein Stück
Aufgabe im Bild (der Text hat sie vollständig; das Bild ist Zugabe). Die
Bilder sind sauber gesetzt, kontrastreich und gerade bis 6 Grad schief;
echte Heftfotos sind schwerer, deshalb Punkt 2 unter 6.

## 5 Grenzen, offen gesagt

- Die Verortung ist Modellarbeit. Ein Gesicht, das das Modell nicht sieht,
  geht als Pixel hinaus, wenn es innerhalb der gedruckten Aufgabe liegt
  (außerhalb schneidet der Zuschnitt es weg). Ein eigener Gesichtsdetektor
  (OpenCV im Web-Container) ist nachrüstbar; erst messen.
- OCR und Urteil kommen vom selben Modell wie die Verortung. Unabhängig
  sind nur die deterministischen Regeln (Entitäten, Zahlenfolge).
- Gedruckte Figurennamen werden nur nachmaskiert, wenn die Namenserkennung
  sie in der Abschrift findet. Übersieht sie den Namen, bleibt er lesbar.
- Die Nachmaskierung kann Treffer daneben setzen (Probe A: „Auf“ statt
  nur „Lisa“). Für den Datenschutz harmlos, für die Lesbarkeit nicht.
- Zeit: etwa 8 bis 13 s je Bildaufgabe zusätzlich vor dem ersten Zug, einmal
  je Aufgabe. Fünf bis sieben Spark-Aufrufe (Verorten, Urteil, OCR, zwei
  Namensfragen, bei Nachmaskierung drei mehr).
- Pillow ist eine neue Abhängigkeit (`requirements.txt`); das Abbild wird
  beim nächsten `sh deploy.sh` neu gebaut.
- Die öffentliche Datenschutzseite (`core/templates/core/datenschutz.html`)
  sagt bis heute „Es wird kein Dienst eines externen Anbieters aufgerufen“.
  Das stimmt seit der Qualitätssicherung (23.09.) nur noch mit Schalter aus
  und braucht unabhängig von diesem Zweig Thomas' Formulierung.

## 6 Was vor dem Einsatz mit Kindern fehlt

1. Thomas bestätigt die Aufhebung von 3a direkt (nicht nur relayt) und
   entscheidet den Merge (Zech-Zweig `hilfe-nach-diagnose` hat ebenfalls
   eine Migration 0026; wer als Zweiter kommt, wird 0028 (so geschehen: Zech-Umbau 0026, Protokoll 0027) und hängt sich an
   den anderen).
2. Messung mit echten Heftfotos (Thomas' eigene, keine Kinderfotos), gleiche
   Leckmessung von Hand: Was blieb sichtbar?
3. `docs/Datenschutz_Einordnung.md` Abschnitt 7 der DSB vorlegen (Thomas).
4. Ausrollen, Abbild neu bauen, Migration 0028, dann auf dem Gerät: Stunde
   mit beiden Schaltern, Foto einer Aufgabe mit Namen, Verlauf prüfen.

## 7 Vorschlag für CLAUDE.md 3a (trägt Thomas ein)

Statt „Bilder gehen nie in die Cloud. …“:

> **Bilder gehen nur mit doppelter Freigabe hinaus:** Die Lehrperson hat je
> Sitzung zusätzlich zur Qualitätssicherung „Fotos der Aufgabe prüfen
> lassen“ gesetzt (Standard aus), und die Bildkette (`tutoring/bildkette.py`)
> hat den Ausschnitt durchgelassen: nur die gedruckte Aufgabe, neu kodiert,
> ohne Metadaten, Handschrift, Namen, Gesichter, Logos, zweimal geprüft,
> fail-closed. Das Foto selbst und der Lösungsversuch des Kindes gehen nie
> hinaus. Scheitert die Kette, antwortet die Qualitätssicherung wie bisher
> auf die Abschrift. Entscheidung Thomas 31.10.2026.

## 8 Nachtrag 31.10.2026: Der Nutzen, gemessen (N1)

Thomas wollte vor der Entscheidung über Regel 3a den Nutzen sehen. Messung in `benchmark/bildnutzen/` (README dort): die 38 amtlichen Aufgaben mit Abbildung aus dem Siegen-Marathon, die sich gegen den Lösungsschlüssel bewerten lassen, je als gedruckte Seite gesetzt und durch die Kette der App geschickt. Gegenstelle gpt-6.1-sol, Spark Qwen3.6-35B-A3B.

| | nur Abschrift (heute) | Abschrift + Ausschnitt (zweiter Schalter) | amtlicher Text ohne Bild |
|---|---|---|---|
| richtig von 38 | 12 | **29** | 11 |

Der Ausschnitt macht aus 12 richtigen Lösungen 29; nie wird eine Aufgabe durch das Bild falsch. Der amtliche Text ohne Abbildung ist so schlecht wie die Abschrift: Es fehlt die Abbildung, nicht die Abschrift. Acht Ausschnitte hat die Kette gesperrt (viermal die Regel „fremde Zahlen", die bei Grafiken mit Achsen zu streng ist; zweimal zu Recht wegen Namen und Ort), dann lief die Qualitätssicherung wie heute mit dem Text. Kosten je Bildaufgabe rund 0,2 Cent mehr, Dauer rund 10 s mehr (Bildkette).

Was das für 3a heißt: Bei Aufgaben mit Abbildung (im Marathon 50 von 126 amtlichen Aufgaben) ist die Qualitätssicherung ohne Bild weitgehend wertlos; mit dem bereinigten Ausschnitt löst sie drei von vier. Der Preis ist, dass ein Ausschnitt der gedruckten Aufgabe das Haus verlässt, nie das Foto. Die Entscheidung bleibt bei Thomas; der Vorschlag für den Wortlaut steht in Abschnitt 7. Eine Folgeänderung, die sich aus N1 ergibt: die Regel „fremde Zahlen" für Grafiken lockern (Zahlen, die als Achsenbeschriftung oder Skala im Ausschnitt stehen), gemessen gegen M1, damit die Handschrift-Sperre nicht leidet.
