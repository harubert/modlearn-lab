# Entwicklungsprotokoll der Aufgabenhilfe, Läufe D bis G

Für den Alt-Neu-Vergleich in Paper A (Siegen, Frist 14.11.2026): je Version
Datum, Commit, Änderung in einem Satz und die Kennzahl, die sich dadurch
bewegen sollte. Alle Läufe: dieselben 60 Aufgaben (`aufgaben.json`) und 12
Kinderprofile (`profile.json`), Seed 20261019, höchstens 8 Züge, ohne
geprüfte Lösung, Kind wählt zwischen Versuch und Frage. Die Kennzahlen
stammen aus `ergebnisse/auswertung.md` (Stand nach dem jeweils letzten
Lauf; die Auswertung rechnet alle Läufe mit denselben Mustern nach). D, D2
und D3 sind drei Zwischenstände desselben Tages und liegen in einem Commit;
was dazwischen geändert wurde, steht in
`docs/Mathe-Benchmark und Konfiguration.md`, Abschnitt 9.

## Die Versionen

| Lauf | Datum | Commit | Modell am Spark | Änderung | Zielkennzahl |
|---|---|---|---|---|---|
| D | 19.10.2026 | 934a1e0 | Qwen3-VL-30B-A3B | Erster Lauf nach dem Umbau von Kern und Kinderseite: Ausgangsprüfung je Schulstufe, Diagnose mit Ergebnis und Fehler im Klartext, Hilfe als eigener Zug mit fester Rückfrage. | Lösung verraten unter Stufe 5 (B: 1,8 %), Fehler benannt |
| D2 | 19.10.2026 | 934a1e0 | Qwen3-VL-30B-A3B | Zitatregel der Ausgangsprüfung erweitert (die Rechnung des Kindes in jeder Schreibweise, seine Rechenart in jedem Wort), zweiter Wiederholungszugang ohne „kleinere Zahlen“. | gekürzte Züge (D: 43,5 %) |
| D3 | 19.10.2026 | 934a1e0 | Qwen3-VL-30B-A3B | Die Diagnose rechnet zuerst selbst, „richtig“ gilt nur mit dieser Zahl im Beitrag; Ampelregeln (Rechenfehler nie gelb); wer das Gesuchte nennt, hat Stufe 1 erreicht. | „Das stimmt.“ zu Unrecht (D2: „38 + 27 … also 55“ als richtig), Schleifen auf Stufe 1 |
| E | 30.10.2026 | 1d62359 | Qwen3-VL-30B-A3B | Hilfe nach Diagnose statt nach Leiter: Lage, Absicht, Bedarf und Form je Beitrag; Nachfrage vor der Hilfe; Hilfe tiefer oder höher nach Lage; Bestätigung mit Warum-Frage und Nachsatz; die feste Rückfrage unter der Hilfe entfällt (keine Kettenfragen). | Verstoß im ersten Versuch (D3: 50,8 %), keine Frage (15,8 %), erste Hilfe nach Lage statt immer Stufe 1 |
| E2 | 30.10.2026 | eedf649 | Qwen3-VL-30B-A3B | Drei Regeln gegen das Festhängen: ein zweites „weiß nicht“ nach zwei Hilfen bekommt die nächststärkere Hilfe; Frust führt nicht schwächer; die Frage wird eng, sobald nach zwei Hilfen kein Ansatz da ist. | am Zuglimit abgebrochen (E: 9), schwaches Profil selbst gerechnet (E: 46,7 %) |
| F | 31.10.2026 | d03f018 | Qwen3.6-35B-A3B, ohne Denkphase | Modellwechsel am Spark, Code und Prompts unverändert (Marathon der Siegen-Sitzung: 93 % statt 84 % bei gleicher Latenz). | Latenz der Hilfe, Lösung verraten, Abbrüche am Zuglimit |
| F2 | 31.10.2026 | 2e0ce74 | Qwen3.6-35B-A3B | Prüflauf nach den beiden F-Punkten: Die Schlussfrage wird erzwungen (einmal nachfassen, sonst die Vorlage der Stufe); das Veto gegen „richtig“ greift auch ohne Zahl im Beitrag, das Veto „der eigenen Rechnung glauben“ nur noch bei Zahlenrechnungen; Tausendergruppen sind eine Zahl. | keine Frage (F: 29,5 % aller Züge mit Frage, 39 % der Stufenhilfen), als richtig bestätigt ohne Ergebnis (F: 11, davon 5 durch das Veto) |
| F3 | 31.10.2026 | 6760226 | Qwen3.6-35B-A3B | Zwischenmessung des Endstands: F2 plus die deterministischen Prüfungen (erfundene Zitate, Behauptungen über die Lehrperson, nachgerechnete Rechnungen, Rechenzeichen, Schleifen) und das didaktische Wissen im Prompt (sechs Grundsätze, damals „Prinzipien“ genannt; Fehlvorstellungen je Thema; erst indirekt, dann direkt). | erfundene Zitate und falsch bestätigte Rechnungen in der Rubrik, Lage und Fehler richtig erkannt |
| G | 31.10.2026 | 497a538 | Qwen3.6-35B-A3B | Endstand für den Alt-Neu-Vergleich: F3 plus Thomas' Antworten zu „Didaktik im Prompt“: die erste Hilfe jeder Stufe indirekt auf allen Schulstufen, die Wiederholung direkt, keine Einsetzfragen (Frage 2, eingebaut 31.10. abends); die Didaktik im Diagnoseprompt mit Fachnamen nach der Literaturnotiz aus Siegen, EIS auf allen Stufen, Trichter-Satz im Hilfeprompt (Frage 1, eingebaut 31.10. Nacht); Fehlvorstellungen aus Thomas' Unterricht (Frage 3, offen). | dieselben wie F3; Einsetzfrage % darf gegen D3 (51,1) nicht steigen; Rubrik `bewertung/G.json` |
| G2 | 1.11.2026 | 1378f66 | Qwen3.6-35B-A3B | Thomas' Vorschlag nach G: Ohne Ansatz des Kindes ist der erste Zug auf allen Schulstufen die Nachfrage nach der Schwierigkeit (bis G: Volksschule Stufe 1); die Nachfrage behauptet nichts über das Kind; Zitatprüfung mit Fenster 80 und Arbeitsverben. Zwischenmessung mit einem Fehler: Die Zitatprüfung hielt die Eröffnungsfrage „Was hast du dir schon überlegt?“ für ein erfundenes Zitat und ersetzte sie in 16 von 60 Dialogen (behoben in G3). | kleinste wirksame Hilfe (Rubrik), erfundene Vorgeschichte, Züge bis zum Ergebnis, schwache Volksschulprofile, Zuglimit |
| G3 | 1.11.2026 | 9582939 | Qwen3.6-35B-A3B | Wie G2, mit der Korrektur: Eine Frage ist kein Zitat; die Eröffnung „Was hast du dir schon überlegt?“ bleibt stehen. **Der Lauf, der für Paper A zählt**, solange bis 4.11. nichts mehr von Thomas kommt; Rubrik `bewertung/G3.json`. | dieselben wie G2; Einsetzfrage % gegen D3 (51,1), kleinste wirksame Hilfe (Rubrik), Zuglimit |

## Kennzahlen je Lauf

Dialogebene (60 Dialoge je Lauf): „selbst gerechnet“ ist das alte Maß
(alle Ergebnismuster in einem Beitrag vor der Lösungsstufe); „Ergebnis in
allen Beiträgen“ sieht die Beiträge des Kindes zusammen und zählt damit
auch die zweiteiligen Aufgaben, deren zweiten Teil das Kind in einem
eigenen Beitrag nennt (seit 31.10. in der Auswertung, für alle Läufe
nachgerechnet).

| Lauf | selbst gerechnet % | Ergebnis in allen Beiträgen % | als richtig bestätigt ohne Muster | am Zuglimit | Lösung gezeigt % | Lösung verraten % (Züge) |
|---|---|---|---|---|---|---|
| D | 76,7 | 83,3 | 6 | 7 | 0,0 | 1,4 |
| D2 | 71,7 | 73,3 | 8 | 10 | 3,3 | 0,0 |
| D3 | 76,7 | 85,0 | 7 | 6 | 3,3 | 0,4 |
| E | 73,3 | 80,0 | 7 | 9 | 0,0 | 0,6 |
| E2 | 71,7 | 76,7 | 4 | 12 | 1,7 | 0,0 |
| F | 73,3 | 78,3 | 11 | 3 | 3,3 | 1,0 |
| F2 | 75,0 | 81,7 | 6 | 8 | 1,7 | 1,0 |
| F3 | 76,7 | 80,0 | 5 | 9 | 0,0 | 1,0 |
| G | 76,7 | 80,0 | 3 | 11 | 0,0 | 0,5 |
| G2 | 75,0 | 85,0 | 7 | 8 | 0,0 | 1,0 |
| G3 | 80,0 | 86,7 | 2 | 10 | 0,0 | 1,2 |

Zugebene (Züge, die mit einer Frage enden sollen: Stufenhilfen 1 bis 4,
Nachfrage, Bestätigung):

| Lauf | Züge mit Frage nötig | keine Frage % | genau eine Frage % | Einsetzfrage % | nachgefasst % | Vorlage % | Verstoß 1. Versuch % | gekürzt % | Wörter je Zug | Hilfe Median ms | Diagnose Median ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D | 285 | 20,7 | 70,5 | 54,9 | – | – | 57,5 | 43,5 | 41,4 | 3 905 | 2 218 |
| D2 | 285 | 13,7 | 81,8 | 47,6 | – | – | 50,9 | 33,7 | 42,0 | 3 804 | 2 202 |
| D3 | 258 | 15,1 | 79,5 | 51,1 | – | – | 51,2 | 32,9 | 43,7 | 3 843 | 3 406 |
| E | 292 | 9,2 | 80,5 | 32,8 | – | – | 39,4 | 27,1 | 44,8 | 3 938 | 4 452 |
| E2 | 281 | 8,9 | 85,1 | 34,4 | – | – | 38,4 | 25,3 | 43,4 | 3 890 | 4 438 |
| F | 313 | 29,1 | 70,6 | 43,2 | – | – | 41,2 | 24,9 | 37,4 | 3 391 | 4 437 |
| F2 | 312 | 0,0 | 99,7 | 37,2 | 23,4 | 14,4 | 40,7 | 25,3 | 39,2 | 3 578 | 4 483 |
| F3 | 314 | 0,0 | 100,0 | 31,5 | 33,1 | 21,7 | 40,8 | 26,1 | 38,8 | 3 414 | 4 780 |
| G | 325 | 0,0 | 99,7 | 30,8 | 28,3 | 15,1 | 42,2 | 26,2 | 47,2 | 3 610 | 4 421 |
| G2 | 335 | 0,0 | 100,0 | 29,6 | 25,7 | 13,7 | 44,8 | 26,0 | 46,1 | 3 632 | 4 500 |
| G3 | 347 | 0,0 | 99,7 | 30,8 | 23,3 | 10,4 | 34,9 | 21,9 | 44,5 | 3 750 | 4 484 |

„nachgefasst“: Anteil der Züge, bei denen der Server die Schlussfrage mit
einer zweiten Anfrage holen musste; „Vorlage“: davon die, bei denen auch
die zweite Anfrage keine brauchbare Frage brachte und die feste Frage der
Stufe angehängt wurde. Vor F2 gab es beides nicht. „Einsetzfrage“ (seit
31.10. abends, rückwirkend für alle Läufe gerechnet): Anteil der
Schlussfragen, die nur eine Zahl, ein Wort oder Ja/Nein einsetzen lassen
(`ausgabepruefung.einsetzfrage`; Zech, S. 285 und 288, Trichtermuster).
Thomas' Vorgabe: Er darf von D3 zu G nicht steigen; G liegt bei 30,8 %.

## Rubrik D3 gegen G und G3 (dieselben 20 Dialoge, Bewertung durch Claude)

Mittel von 0 bis 2 je Kriterium, in Klammern die Zahl der bewerteten Züge
(`ergebnisse/bewertung/D3.json`, `G.json`; Skala in `_vorlage.json`). Die
vier letzten Kriterien gibt es erst seit dem Umbau vom 30.10., für D3
sind sie nicht bewertet. Thomas bewertet 8.–10.11. verblindet 30 Züge D3
gegen 30 Züge des Laufs, der zählt (G3), gepaart nach Aufgabe und Profil.

| Kriterium | D3 | G | G3 |
|---|---|---|---|
| fachlich richtig | 1,74 (88) | 1,75 (126) | 1,84 (139) |
| Stufe eingehalten | 1,25 (88) | 1,56 (109) | 1,77 (124) |
| genau eine Frage, kurz, altersgerecht | 1,60 (88) | 1,84 (109) | 1,79 (124) |
| Fehler des Kindes aufgegriffen | 1,71 (17) | 1,87 (15) | 1,35 (20) |
| Diagnose sinnvoll | 1,77 (86) | 1,78 (83) | 1,74 (97) |
| Umgehung abgefangen | 1,50 (6) | 1,93 (27) | 1,96 (24) |
| Hilfe passt zur Lage | – | 1,76 (106) | 1,80 (119) |
| kleinste wirksame Hilfe | – | 1,54 (65) | 1,69 (80) |
| weit begonnen, erst dann verengt | – | 1,80 (102) | 1,90 (115) |
| Bezug auf die letzte Äußerung | – | 1,82 (106) | 1,84 (119) |

Was in G die Punkte kostet (aus den Begründungen): Stufe 1 und die
Eröffnung nennen den Weg oder das Werkzeug (vs10 „3 · 45“, vs17 „immer um
vier größer“, sek01 „gleichnamig“, sek14 Hypotenuse/Katheten, ma10 „dritte
Wurzel“); erfundene Vorgeschichte in der Eröffnung („du hast notiert“,
„du hast berechnet“, sechsmal); Stufe 2 und 3 geben bei Kindern auf dem
Weg den ganzen Plan (ma01, ma15 Stammfunktion und Ablauf); Analogien mit
denselben Zahlen statt eines Impulses (vs02, vs04, sek06); zwei
Modellausfälle (ma12: leere Diagnose der vollständigen Lösung, danach
Zweifel am richtigen Vorzeichen; vs02: „Wie viel Geld bekommst du
zurück?“ aus einer anderen Aufgabe); ma10 beantwortet eine Frage des
Kindes nicht und verrät dann a = 2; die Prompt-Namen „Motivationshilfe“
und „Rückmeldungshilfe“ stehen in ma10 im Text.

Was in G3 die Punkte kostet: „Fehler aufgegriffen“ fällt auf 1,35, weil
das Modell in der Volksschule dreimal selbst falsch rechnet oder liest
(vs10: 200 − 135 = 155 des Kindes bleibt unbenannt, dafür wird das
richtige 3 · 45 = 135 bemängelt; vs17: die richtigen Antworten 4 und 11
gelten als falsch; ma06: das behauptete 80,0 bleibt unbeantwortet) und
ma10 dreimal „verfünffacht“ sagt (4000 : 500 = 8). Stufe eingehalten
steigt auf 1,77, die kleinste wirksame Hilfe auf 1,69: Die Eröffnung
fragt statt zu helfen, Stufe 1 nennt seltener Weg oder Werkzeug (noch:
ma01 Eliminieren, sek11 die Richtung, sek14 Hypotenuse). Rest: sek01
spricht nach dem Veto gegen „5“ (Sechstel) das Ergebnis selbst aus, sek05
wiederholt den Stufe-1-Text als Stufe 3, sek14 bricht einen Satz ab und
bringt eine Preis-Analogie, die zum Abziehen verführt.

## Was die Läufe zeigen (Kurzfassung)

- D bis D3 (ein Tag): Die Durchrutscher unter Stufe 5 fallen von 1,8 % (B)
  auf 0,4 %, der Preis ist die Kürzung jeder dritten Hilfe. Das Veto gegen
  „richtig“ ohne die nachgerechnete Zahl hält die Karte „Das stimmt.“ von
  falschen Ergebnissen fern (D3: 52 Karten, eine zu Unrecht).
- E/E2 (Hilfe nach Diagnose): weniger Verstöße (38 % statt 51 %), weniger
  Kürzungen, mehr Züge mit genau einer Frage (85 %), die erste Hilfe
  richtet sich nach der Lage; selbst gerechnet bleibt gleich (72 bis 77 %
  in allen Läufen), die Gespräche werden länger (6 statt 4,4 Züge).
- F (Modellwechsel): schneller (3,4 statt 3,9 s je Hilfe), knapper (37
  statt 43 Wörter), seltener am Zuglimit (3 statt 12), aber jeder dritte
  Zug ohne Frage und 11 Dialoge „richtig“ ohne Ergebnismuster, davon 5
  durch ein Veto des Servers, das ein richtiges „falsch“ des Modells
  umdrehte (Terme: „7b“ gegen „2a + 7b“).
- F2 (Schlussfrage, Veto): kein Zug ohne Frage (99,7 % genau eine), „richtig
  ohne Muster“ 11 auf 6 (davon 4 Musterlücken, 1 Modellfehler, 1 Veto),
  selbst gerechnet 75,0 %, in allen Beiträgen 81,7 %; acht statt drei
  Dialoge am Zuglimit, weil falsche Bestätigungen die Dialoge nicht mehr
  früh beenden; Hilfe 3,6 s (Nachfassen in 23 % der Züge, 2,7 s).
- F3 (Prüfungen, Didaktik): Dialogmaße im Rauschen (76,7 % / 80,0 %), die
  Prüfungen greifen (5 Zitate, 7 Schleifen), zwei Regeln nachgeschärft
  (Lehrperson nur bei Regeln fürs Kind, Nachrechnen ohne Hochzahlen); Diagnose
  0,3 s langsamer; jede fünfte erste Volksschulhilfe indirekt.
- G (Thomas' Antworten zu Frage 1 und 2): Form als Serverregel (erste Hilfe
  jeder Stufe indirekt, Wiederholung direkt, alle Schulstufen), Denkfragen
  statt Einsetzfragen, Didaktik mit Fachnamen. Dialogmaße wie F3 (76,7 % /
  80,0 %), „richtig ohne Muster“ 3 (alle drei Musterlücken), Einsetzfrage
  30,8 % (D3 51,1), direkt 47 % statt 76 %, Hilfe 3,6 s, Diagnose 4,4 s;
  elf Dialoge am Zuglimit (F3: 9), fünf davon Volksschule. Rubrik gegen D3:
  Stufe 1,25 auf 1,56, Frage 1,60 auf 1,84, Umgehung 1,50 auf 1,93,
  fachlich und Diagnose gleich; Wörter je Zug 47 statt 39, davon der feste
  Umgehungssatz beim umgehenden Profil (63 Wörter), sonst 38 bis 42.
- G2 (erster Zug: Nachfrage nach der Schwierigkeit, alle Schulstufen): selbst
  75,0 %, in allen Beiträgen 85,0 %, Zuglimit 8 (G: 11), „richtig ohne
  Muster“ 7 (sechs Musterlücken, eine falsche Bestätigung: vs01 zählt „7 8 9
  10 11 12 13“), Einsetzfrage 29,6 %. Mit einem Fehler gelaufen: Die
  Zitatprüfung hielt „Was hast du dir schon überlegt?“ für ein Zitat und
  ersetzte die Eröffnung in 16 Dialogen; Fragen sind seither keine Zitate.
  Volksschule schwach: 1 von 5 selbst (G: 3), 3 „ohne Muster“, 1 Zuglimit.
  G3 folgt mit der Korrektur.
- G3 (G2 mit der Zitat-Korrektur; der Lauf, der zählt): selbst 80,0 %, in
  allen Beiträgen 86,7 %, „richtig ohne Muster“ 2 (beide Form), Zuglimit 10
  (schwach 6, umgehend 3, mittel 1), Einsetzfrage 30,8 % (D3 51,1),
  Verstoß im ersten Versuch 34,9 % (tiefster Wert), Vorlage 10,4 %, Hilfe
  3,8 s, Diagnose 4,5 s; die Eröffnung ist in allen 60 Dialogen die Frage
  nach der Schwierigkeit, erste Hilfe danach 33-mal Stufe 1, 18-mal Stufe 2,
  5-mal Stufe 3; direkt 49 %. Rubrik gegen D3: Stufe 1,25 auf 1,77, Frage
  1,60 auf 1,79, Umgehung 1,50 auf 1,96, fachlich 1,74 auf 1,84, Diagnose
  gleich; Fehler aufgegriffen 1,71 auf 1,35 (drei Modellfehler in der
  Volksschule, siehe oben). Schwaches Profil selbst 53 % (G 53 %, D3 53 %),
  umgehend 87 % (G 67 %).

## Was in Thomas' Stichprobe (31.10.) schon erledigt ist

Punkt 4 der Beobachtungen (der feste Auftrag „Was rechnest du, und was
kommt heraus?“ als Doppelfrage unter der Hilfe) betrifft die Leiter bis
D3: Seit E endet jede Hilfe mit ihrer eigenen Frage, und die Seite zeigt
keinen zweiten Arbeitsauftrag mehr. Die Vorlagen der Schlussfrage seit F2
(`levels.SCHLUSSFRAGE_VORLAGE`) sind einzelne Fragen.

## Nach G3: die Fachgrenze (7.11.2026)

Seit dem 7.11. steht auf dem Frageweg der Aufgabenhilfe der Pförtner
(`tutoring/fachgrenze.py`): Eine Rückfrage, die nicht zur Stunde gehört,
bekommt den festen Satz der Anwendung statt einer Antwort des Modells.
Seit dem Abend des 7.11. läuft der Pförtner auch auf dem Versuchsweg,
parallel zur Diagnose: Sagt er nein, zählt der Beitrag nicht als Versuch
und die nächste Nachfrage ist der feste Satz. Für Beiträge zur Stunde
ändert sich nichts an Diagnose und Hilfen; eine Rechnung oder Zahl wird
ihm gar nicht vorgelegt. `lauf.py` baut die Pipeline ohne Pförtner nach;
die simulierten Kinder fragen nichts Fachfremdes. G3 bleibt damit der
Vergleichsstand für Paper A. Ob der Pförtner selbst Peking wie Berlin
behandelt, misst ein eigener Lauf (`benchmark/neutralitaet/`), nicht
dieser Benchmark.
