# Didaktisches Wissen im Diagnose- und Hilfeprompt

Entwurf vom 31.10.2026 zum Gegenlesen durch Thomas, nach seiner Bewertung
der 36 Tutorzüge (Siegen, Stichprobe). Alles hier ist in eigenen Worten
formuliert, keine Buchpassagen. Was in den Prompt geht, steht wörtlich in
Abschnitt 3 und 4; der Rest erklärt, warum und wo.

## 1 Was Thomas wollte

Aus der Stichprobe (Beobachtungen, gebündelt von der Siegen-Sitzung):

1. Das didaktische Wissen (im Entwurf zuerst „Prinzipien“ genannt, siehe
   Abschnitt 8) als Wissen der Diagnose, knapp und in eigenen Worten;
   daran hängend ein Katalog typischer Fehlvorstellungen je Thema.
2. Stufe 1 klärt Begriffe und den Sinn der Aufgabe, erklärt kein Verfahren.
3. Bei Textaufgaben öfter „mach eine Zeichnung“ als Tipp.
4. Genau eine Frage (erledigt, siehe `benchmark/mathe/ENTWICKLUNG.md`).
5. Innerhalb einer Stufe erst indirekt („Ja. Weißt du, wie es weitergeht?“),
   dann direkt.
6. Unplausibles Ergebnis (133 %): zuerst die Vorstellung ansprechen, dann
   die Operation.
7. Deterministische Prüfungen (gebaut am 31.10., Commit 986f56e).

## 2 Wo es hingeht

| Punkt | Ort | Art |
|---|---|---|
| Didaktik (zwei didaktische Prinzipien, Grundvorstellungen, Prüf- und Problemlösestrategien, Prinzip der minimalen Hilfe) | Diagnoseprompt (`levels.DIDAKTIK_DIAGNOSE`), vor der Beurteilung des Beitrags | Text, immer |
| Fehlvorstellungen | Diagnoseprompt und Hilfeprompt der Stufen 2 bis 4, nur die Themen, die zur Aufgabe passen (`levels.fehlvorstellungen_fuer(aufgabentext)`, Stichwörter in der Angabe) | Text, je Aufgabe höchstens drei Themen |
| Stufe 1 ohne Verfahren | schon Regel: die Ausgangsprüfung kürzt jeden Rechenweg auf Stufe 1 (`genannter Rechenweg`); dazu ein Satz im Hilfeprompt | Regel plus Text |
| Zeichnung als Tipp | Hilfeprompt Stufe 3 (`levels.DIDAKTIK_HILFE`) | Text |
| erst indirekt, dann direkt | Server: die erste Hilfe jeder Stufe indirekt, die Wiederholung derselben Stufe direkt, auf allen Schulstufen (Thomas, 31.10. abends, Abschnitt 8; bis dahin war die Volksschule immer direkt nach Zech, S. 350, und der Entwurf schlug „indirekt nur auf tragendem Weg“ vor). | Regel (`pruefung.diagnose`, `views._hilfe_erzeugen`) |
| Plausibilität zuerst | Diagnoseprompt (FEHLER: die Vorstellung vor der Operation) und Hilfeprompt (Rückmeldung fragt zuerst, ob das Ergebnis zur Situation passen kann) | Text |

Der Prompt bleibt eine Bitte. Was sich erzwingen lässt, steht als Regel im
Server (Abschnitt 2, letzte Spalte); der Text hilft dem Modell, die Regel
zu verstehen, und trägt die Fälle, die keine Regel fängt.

## 3 Die Didaktik, wie sie im Diagnoseprompt steht

Wortlaut seit 31.10. spät (Thomas' Antwort zu Frage 1 und die Gliederung
der Siegen-Sitzung mit geprüften Quellen, Abschnitt 8). Die Fachnamen sind
die der deutschsprachigen Mathematikdidaktik; „didaktisches Prinzip“ steht
nur über den beiden, die eines sind.

> DIDAKTIK, womit du beurteilst:
> Didaktische Prinzipien
> - EIS-Prinzip (Darstellungswechsel, auf allen Stufen): Ein Sachverhalt
>   soll handelnd, bildlich und symbolisch verfügbar sein, in beide
>   Richtungen. Wer in Zeichen festhängt, kommt oft über eine Handlung oder
>   ein Bild weiter, auch in der Oberstufe.
> - Operatives Prinzip: Was passiert mit dem Ergebnis, wenn sich eine Zahl
>   oder ein Teil der Situation ändert? Die Umkehrung ist zugleich eine
>   Probe.
> Grundvorstellungen (fachdidaktisches Konzept)
> - Ein Fehler steckt oft in einer fehlenden Grundvorstellung (was plus,
>   mal, ein Bruch, ein Prozent bedeuten), nicht im Rechnen. Benenne zuerst
>   die Vorstellung, dann die Operation.
> Prüf- und Problemlösestrategien
> - Validieren: Das Ergebnis muss zur Situation der Aufgabe passen, nicht
>   nur zur Rechnung („Kann das sein?“). Unplausible Ergebnisse (mehr als
>   100 % bei einem Teil vom Ganzen, ein Rest größer als der Teiler, ein
>   Preis nach dem Rabatt höher als davor, eine negative Anzahl) zuerst so
>   ansprechen.
> - Heurismen als Tipp: eine Skizze oder Tabelle machen, eine
>   Nachbaraufgabe oder kleinere Zahlen probieren.
> Lernhilfe: Prinzip der minimalen Hilfe
> - Gib die kleinste Hilfe, die nach deiner Diagnose weiterbringt.
>   Innerhalb einer Stufe zuerst indirekt, dann direkt. Was das Kind selbst
>   finden kann, bleibt seine Arbeit.

Was gegenüber dem Entwurf anders ist: „Plausibilität zuerst“ und „die
Geschichte der Aufgabe als Prüfstein“ waren derselbe Schritt (Validieren
im Modellierungskreislauf, Rückschau nach Pólya) und sind zusammengelegt;
„Nachbaraufgabe“ und „kleinere Zahlen“ sind Heurismen, keine Teile des
operativen Prinzips; die minimale Hilfe ist ein Prinzip der Lernhilfe
(Aebli; bei Zech „Prinzip der kleinsten Hilfe“, S. 315–318, 324). Die
Form (erst indirekt, dann direkt) setzt die Anwendung; der Satz steht
hier als Wissen.

Dazu im Abschnitt FEHLER des Diagnoseprompts: „Steckt hinter dem Fehler
eine der typischen Fehlvorstellungen unten, nenne sie so.“

## 4 Der Hilfeprompt

Für alle Stufen unter der Lösung (Wortlaut seit 31.10. spät):

> DIDAKTIK: Stufe 1 klärt Wörter, Situation und Sinn der Aufgabe, nie ein
> Verfahren. Ein Tipp der Stufe 3 darf auf jeder Schulstufe eine Handlung
> oder ein Bild sein („leg es mit Dingen“, „mach dir eine Zeichnung oder
> Tabelle“; EIS-Prinzip, auch in der Oberstufe). Kann ein Ergebnis zur
> Situation nicht passen, frag zuerst, ob es passen kann, nicht nach der
> Rechenart (Validieren). Indirekt heißt: zurückhaltend in der Form,
> konkret im Inhalt, ein weiter Impuls wie „Leg es mit Plättchen“ oder
> „Kann das sein?“, keine Kette immer engerer Fragen. Würde deine Frage nur
> noch ein Wort oder eine Zahl abfragen, ist das der Trichter: Gib
> stattdessen einen konkreten Impuls (Handlung, Bild) und lass das Kind den
> Schritt erklären.

Dazu je Hilfe der Satz zur Form (`levels.FORM_SATZ`): indirekt als weite
Denkfrage oder Impuls, keine enge Wissensfrage; direkt zeigt die Stelle,
lässt aber etwas zu überlegen, keine Einsetzfrage. Die Verengung
(Wiederholung derselben Stufe: Form direkt, Weite eng) gibt es je Stufe
nur einmal, weil dieselbe Stufe höchstens zweimal kommt; das ist unser
eigener Schnitt, nicht aus der Literatur.

Für die Stufen 2 bis 4 dazu die passenden Fehlvorstellungen (Abschnitt 5)
als „Woran Kinder bei solchen Aufgaben oft scheitern“, damit die
Rückmeldung den Fehler an der Stelle benennen kann, ohne die Lösung zu
nennen.

## 5 Katalog typischer Fehlvorstellungen

Je Thema die Stichwörter, an denen die Anwendung das Thema in der Angabe
erkennt, und die Fehlvorstellungen in der Form, in der sie das Modell
bekommt. Quelle: die typischen Fehler aus `benchmark/mathe/aufgaben.json`
(60 Aufgaben, 19.10.2026) und die üblichen Befunde der Fachdidaktik, in
eigenen Worten.

| Thema | Stichwörter | Typische Fehlvorstellungen |
|---|---|---|
| Plus und Minus (Volksschule) | dazu, weg, mehr, weniger, zusammen, übrig, bleiben, Unterschied, älter, jünger | Zählfehler: die Startzahl wird mitgezählt (7 + 5 = 11). Übertrag beim Zehnerübergang vergessen oder Ziffern getrennt gerechnet. Rechenart nach einem Signalwort gewählt („dazu“ heißt plus, „weg“ heißt minus), nicht nach der Situation. Vergleichsaufgaben („um wie viel älter“) als Zusammenfassen gelesen. |
| Mal und Geteilt (Volksschule) | je, jede, pro, mal, Packung, Gruppe, verteilen, aufteilen, Reihe, doppelt, halb, Rest | Zusammenzählen statt Malnehmen (6 + 4 statt 6 · 4). Minus oder Mal statt Geteilt. Verteilen und Aufteilen verwechselt (die Anzahl je Gruppe als Ergebnis wiederholt). Beim Teilen mit Rest: Rest größer als der Teiler, oder der Rest wird ohne Grund aufgerundet. Null beim Malnehmen mit Zehnerzahlen vergessen (6 · 150 = 90). Übertrag beim schriftlichen Multiplizieren. |
| Größen: Geld, Zeit, Länge, Gewicht | Euro, Cent, Minuten, Uhr, Stunden, Meter, cm, kg, Gramm, Liter | Einheiten gemischt (1,20 + 65 = 66,20, Cent als Euro). Uhrzeiten wie Dezimalzahlen gerechnet (16:45 + 1:30 = 17:75). Einheiten nicht umgerechnet (2 m minus 45 cm). Nur einen von mehreren Posten verrechnet. |
| Stellenwert, große Zahlen | Million, tausend, Zahlen mit Tausendergruppen | Stellenwert beim Übergang (299 500 + 1 000 = 299 1500). Nullen abgezählt statt gerechnet (1 000 000 − 10 000 = 999 000). |
| Umfang, Fläche, Volumen | Umfang, Fläche, Flächeninhalt, Volumen, Rauminhalt, Quader, Rechteck, m², m³ | Umfang und Fläche verwechselt. Nur zwei oder drei Seiten addiert. Die Einheit m statt m² (die Zahl stimmt, die Vorstellung von Fläche nicht). Beim Volumen nur zwei Maße multipliziert oder addiert statt multipliziert. |
| Brüche | Bruch, Zähler, Nenner, Viertel, Drittel, Fünftel, Hälfte, Schreibweise a/b | Zähler und Nenner getrennt addiert (1/2 + 1/3 = 2/5). Ein Bruch als zwei ganze Zahlen gelesen. Größenvergleich nach dem Nenner (1/5 größer als 1/3, weil 5 größer als 3). Bruchteil einer Menge: Zähler und Nenner vertauscht, oder der zweite Schritt vergessen. |
| Dezimalzahlen | Komma, Dezimalzahl, Zahlen mit Komma | Stellen aneinandergehängt (3,6 + 0,45 = 3,105). „Länger ist größer“ (0,45 größer als 0,6). Komma beim Teilen verschoben. Rechtsbündig statt kommagerecht untereinander. |
| Prozent | Prozent, %, Rabatt, Zins, Erhöhung, Senkung | Prozent als Euro abgezogen (80 − 25). Teil und Ganzes vertauscht (24 : 18 statt 18 : 24, also 133 % für einen Teil vom Ganzen). Differenz als Prozent (24 − 18 = 6 %). Erhöhung und Senkung heben sich auf, weil die Bezugsgröße wechselt. |
| Proportionalität | kostet, kosten, je, pro, Arbeiter, Tage, gleichmäßig, Verhältnis, Schlussrechnung | Additiv statt multiplikativ gedacht („3 kg mehr, also 3 Euro mehr“). Nicht auf die Einheit zurückgerechnet. Indirekte Proportionalität wie direkte gerechnet (weniger Arbeiter, weniger Tage). |
| Negative Zahlen | negativ, Temperatur, Grad, Schulden, minus vor einer Zahl | Beträge addiert statt Richtung beachtet (−7 und 12 Grad als 19). Vorzeichenregel: minus mal minus als minus. Beim Verrechnen fällt das Vorzeichen eines Summanden weg. |
| Terme und Gleichungen | Gleichung, löse, Term, vereinfache, Variable, x | Beim Umstellen das Vorzeichen nicht gewechselt. Nur auf einer Seite geteilt. Ungleichartige Terme zusammengeworfen (3a + 5b = 8ab). Die Variable „verschwindet“ (3a − a = 3). x-Terme addiert statt subtrahiert. |
| Pythagoras, Dreiecke | Pythagoras, rechtwinklig, Hypotenuse, Kathete, Diagonale, Leiter, Wand | Seiten einfach addiert oder abgezogen statt der Quadrate. Kathete wie Hypotenuse berechnet (Summe statt Differenz der Quadrate). Wurzel vergessen oder vor dem Quadrieren gezogen. |
| Statistik | Mittelwert, Durchschnitt, Median, Modus, Spannweite, Kennzahl, Ausreißer | Summe nicht durch die Anzahl geteilt, oder durch die falsche Anzahl. Median aus der unsortierten Liste, oder als Mittel der Randwerte. Bei einem Ausreißer „ändern sich beide Kennzahlen“. |
| Funktionen | Funktion, f(x), Steigung, Nullstelle, Scheitel, Graph, linear, quadratisch | Nullstelle mit f(0) verwechselt. Der y-Wert eines Punkts als Achsenabschnitt genommen. Scheitel bei −b statt −b/(2a). Vorzeichen in der Lösungsformel; nur eine Lösung angegeben. Fixkosten vergessen oder Rollen vertauscht. |
| Wachstum und Zerfall | exponentiell, Wachstum, Zerfall, Halbwertszeit, Verdopplung, Zinseszins, Bakterien | Linear gedacht (gleiche Zuwächse je Schritt). Die Zeit aus der Angabe mit der Verdopplungszeit verwechselt. Auf ganze Halbwertszeiten gerundet. |
| Ableiten und Integrieren | Ableitung, ableiten, f′, Integral, Stammfunktion, Änderungsrate, Extremstelle, Maximum, Minimum, momentan | Abgeleitet statt integriert und umgekehrt. Konstante bleibt beim Ableiten stehen; Exponent nicht verringert. Maximum und Minimum vertauscht. Die negative Lösung der Ableitung vergessen. Mittlere Änderungsrate ohne Division durch die Zeitspanne. |
| Vektoren, Trigonometrie | Vektor, Skalarprodukt, orthogonal, sin, cos, tan, Winkel | Länge als Summe der Komponenten. Skalarprodukt gleich 1 statt 0 gesetzt. sin und tan vertauscht, Gegen- und Ankathete vertauscht. Bogenmaß statt Grad. |
| Wahrscheinlichkeit | Wahrscheinlichkeit, Würfel, ziehen, Kugel, Zurücklegen, Binomial, Erwartungswert, Einsatz | Bei „und“ addiert statt multipliziert. Mit statt ohne Zurücklegen (Nenner nicht verringert). Binomialkoeffizient oder Gegenwahrscheinlichkeit vergessen. Einsatz beim Erwartungswert vergessen. |
| Mehrschrittige Sachaufgaben | mehrere Zahlen und mehrere Sätze in der Angabe, „dann“, „danach“, „insgesamt“, „noch“ | Nur ein Schritt gerechnet, der zweite vergessen. Alle Zahlen in einer Rechenart verrechnet, weil ein Wort („kommen dazu“) die Geschichte überstrahlt. „Halb so viele“ als „um zwei weniger“ gelesen. |

Die Anwendung wählt die Themen nach der Zahl der Treffer in der Angabe,
höchstens drei. Trifft nichts, bekommt das Modell nur die Didaktik.

## 6 Was zu messen ist

Lauf gegen F2 (gleiche Bedingungen): „Fehler benannt“ und „Diagnose
richtig“ in der Rubrik; die Lage „ansatz_falsch“ mit Fehlvorstellung im
Klartext; Stufe-1-Hilfen ohne Rechenweg (schon jetzt 0 Durchrutscher);
Zeichnung als Tipp auf Stufe 3 (Anteil der Stufe-3-Hilfen mit „Zeichnung“,
„Skizze“ oder „leg“); erste Hilfe indirekt (Anteil), Wiederholung direkt.
Kosten: der Diagnoseprompt wächst um etwa 250 Tokens, der Hilfeprompt um
etwa 150; die Latenz der Diagnose (F: 4,4 s Median) ist zu prüfen.

Dazu seit 31.10. abends (Thomas' Vorschlag zu Frage 2): der Anteil der
Schlussfragen, die nur eine Zahl, ein Wort oder Ja/Nein einsetzen lassen
(Trichter-Indikator, `ausgabepruefung.einsetzfrage`; Zech S. 285 und 288).
Er darf von D3 (51,1 %) zu G nicht steigen; F3 liegt bei 31,5 %.

## 7 Offene Fragen an Thomas

1. Stimmt die Form der Prinzipien (Abschnitt 3)? Fehlt eines, ist eines zu
   viel?
2. Volksschule und „erst indirekt“: Zech sagt, bei Jüngeren stärker
   ansetzen. Vorschlag: indirekt nur, wenn das Kind auf einem tragenden Weg
   ist (Lage „weg_offen“ oder „rechenfehler“), sonst direkt wie bisher.
3. Der Katalog ist aus den 60 Benchmark-Aufgaben und dem Üblichen gebaut.
   Welche Fehlvorstellungen aus deinem Unterricht fehlen?

## 8 Antworten (31.10.2026, abends, über die Siegen-Sitzung)

Frage 2 ist endgültig beantwortet, Frage 1 vorläufig, Frage 3 noch nicht.

**Frage 2, Volksschule:** Auch in der Volksschule wird erst indirekt
geholfen (fragend-entwickelnder Unterricht). Der Vorschlag „indirekt nur
bei tragendem Weg, sonst direkt“ ist vom Tisch. Auf allen Schulstufen gilt:
Die erste Hilfe jeder Stufe ist indirekt, die Wiederholung derselben Stufe
ist direkt. Begründung bei Zech, Kap. 10.2, S. 284–291: Der Schüler soll
durch die Frage nicht unnötig viel Hilfe bekommen; weit beginnen, erst bei
Schwierigkeiten verengen, nie so eng, dass nichts mehr zu überlegen bleibt
(S. 288, Negativbeispiel „Was für Winkel haben wir im Rechteck?“ –
„Rechte!“); das reine Frage-Antwort-Spiel engt den Denkhorizont ein
(S. 285; Trichtermuster nach Bauersfeld); keine Kettenfragen (S. 289); aus
einer Antwort das Gute herausstellen, nachfragen, abwarten (S. 290);
Denkfragen statt Wissensfragen, Fragen, die auf die anschauliche
Verständnisgrundlage zurückführen (S. 290 f.). Umgesetzt am 31.10. abends:
Form als Serverregel, die indirekte erste Hilfe als weite Denkfrage oder
Impuls, auch die direkte Hilfe keine Einsetzfrage, Trichter-Indikator in
der Auswertung (Einzelheiten in `docs/Hilfen nach Diagnose.md` §10).

**Frage 1, Prinzipien (vorläufig):** Inhaltlich bleibt alles. Aber
„didaktisches Prinzip“ ist in der deutschsprachigen Mathematikdidaktik ein
feststehender Begriff mit kanonischen Prinzipien (EIS nach Bruner,
operatives Prinzip; Zech Kap. 4.2, S. 114–124). „Plausibilität zuerst“ und
Ähnliches sind wertvoll, aber keine didaktischen Prinzipien. Daraus folgt:
(a) Der Abschnitt heißt nicht pauschal „didaktische Prinzipien“; echte
Prinzipien bekommen den Fachnamen, der Rest eine andere Überschrift, etwa
Grundvorstellungen, Prüf- und Problemlösestrategien oder Validieren.
(b) EIS gilt ausdrücklich auf allen Stufen, nicht nur in Volksschule und
Sekundarstufe I: In der Oberstufe erklärt ein Draht, der sich zwischen
zwei Fingerspitzen dreht und einen Rotationskörper zeigt, ein Integral
für Volumen oder Fläche oft besser als durchgerechnete Beispiele; bei
Verständnisproblemen also auch in der Matura zurück zum Bild und zur
Handlung. Die Gliederung mit geprüften Quellen kam am 31.10. spät aus
Siegen (`Siegen_STEM-Edu-AI_2027/A_tutor/literatur/didaktische_prinzipien.md`,
Quellen daneben); Abschnitt 3 und 4 zeigen den neuen Wortlaut, eingebaut in
derselben Nacht. Thomas liest die HTML-Fassung der Gliederung parallel;
ändert er etwas, wird nachgezogen. Dazu aus der Notiz: Fragend-entwickelnd
ist eine Unterrichtsform, kein Prinzip (der Prinzipname wäre das
sokratische Prinzip); die starre Abfolge „erst enaktiv, dann ikonisch,
dann symbolisch“ gilt als Verengung von Bruner.

**Frage 3, fehlende Fehlvorstellungen:** noch keine Antwort.

Lauf G fährt mit diesem Stand (Siegen: sobald Frage 1 und 2 drin sind);
ausgerollt wird nichts ohne Thomas' Wort.

## 9 Nachtrag 1.11.2026: Thomas' Vorschlag nach Lauf G

Thomas (über Siegen, kein fertiger Auftrag): Der Tutor soll am Anfang
fragen, wo die Schwierigkeiten sind, statt mit „Hilfe 1“ zu beginnen, weil
dort der Eindruck des Schülers fehlt. Gebaut als Serverregel (der erste
Zug ohne Ansatz ist auf allen Schulstufen die Nachfrage, die nichts über
das Kind behauptet; `docs/Hilfen nach Diagnose.md` §12) und in G2 gemessen.
Das ist der Punkt, an dem Zech S. 350 (Volksschule stärker ansetzen) und
S. 290 (nachfragen, abwarten) gegeneinander stehen; die Messung entscheidet.
