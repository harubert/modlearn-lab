# Mathe-Benchmark für die Aufgabenhilfe

Misst die echte Hilfepipeline der Anwendung (`tutoring/levels.py`,
`tutoring/pruefung.py`, `tutoring/ausgabepruefung.py`, `tutoring/spark.py`,
Ablauf aus `tutoring/views.py` und `Task.naechster_zug`) mit 60 eigenen
Aufgaben und simulierten Kindern am Spark. Der Bericht dazu liegt unter
`docs/Mathe-Benchmark und Konfiguration.md` (Stand 19.10.2026, Abschnitt 9:
Nachmessung nach dem Umbau). Seit 30.10.2026 baut der Lauf den Ablauf
„Hilfe nach Diagnose statt nach Leiter" nach; ein Lauf damit steht noch aus
(Spark am 30.10. abgeschaltet), `D3` ist der Vergleich.

## Einmal laufen lassen

Voraussetzung: der Spark ist OpenAI-kompatibel erreichbar (am Entwicklungs-PC
über den SSH-Tunnel `http://127.0.0.1:18000/v1`), und die Python-Umgebung des
Projekts hat `django` und `httpx` (nichts weiter, keine Datenbank).

    cd modlearn-lab
    set SPARK_BASE_URL=http://127.0.0.1:18000/v1
    set SPARK_MODEL=qwen3.6-35b-a3b
    python benchmark\mathe\lauf.py --kennung mein_lauf
    python benchmark\mathe\auswertung.py

Der erste Befehl führt alle 60 Dialoge (höchstens drei gleichzeitig, jede
Anfrage bricht nach 90 s ab) und schreibt je Dialog eine JSON-Datei nach
`benchmark/mathe/ergebnisse/mein_lauf/`. Der zweite schreibt
`ergebnisse/auswertung.md` und `ergebnisse/auswertung.json` mit allen
Kennzahlen je Lauf, Schulstufe, Profil, Hilfeumfang, Zech-Stufe und Art des
Tutorzuges sowie der Latenz je Aufrufart. Ein Lauf dauert am Spark etwa 20
bis 45 Minuten.

Nach einer Prompt-Änderung in `levels.py`, `pruefung.py` oder
`ausgabepruefung.py` denselben Befehl mit einer neuen Kennung wiederholen;
die Auswertung stellt die Läufe nebeneinander. Die automatischen Maße
(Verstöße, Kürzungen, Fragen je Hilfe, Länge, selbst gerechnet, Lösung
verraten, Diagnoserichtung und -ergebnis, Nachfragen, Sprünge, Lage und
Absicht, Form und Weite, Bestätigung, Überstimmung, Latenz) sind sofort
vergleichbar; die Rubrik (`ergebnisse/bewertung/`) muss für einen neuen Lauf
neu bewertet werden.

### Ohne Spark: die Probe

    python benchmark\mathe\lauf.py --probe
    python benchmark\mathe\lauf.py --probe --nur sek01

`--probe` führt EINEN Dialog (die erste Aufgabe des Plans, mit `--nur` oder
`--stufe` eine andere) mit einem eingebauten Fake-Modell: Der Tutor
antwortet je Art des Zuges mit einem festen Satz, die Diagnose je nach
Beitrag des Kindes (angefangen, aber unklar: erst nachfragen; Fehler:
Rückmeldung; Ergebnis: richtig), das Kind mit einem festen Skript. Kein
Netz, keine Messung; das Protokoll landet im Temp-Verzeichnis
(`%TEMP%\modlearn_mathe_probe\probe\`), der Dialog wird lesbar ausgegeben,
und die Auswertung läuft darüber mit
`auswertung.py --ergebnisse %TEMP%\modlearn_mathe_probe`. Die Probe prüft
den Ablauf (Nachfrage, Hilfe, Wiederholung, Bestätigung mit Warum-Frage,
Nachsatz, Lösungsabfrage) und die Protokollfelder, nicht die Qualität der
Hilfen.

### Vergleichslauf gegen D3

`D3` (19.10.2026, 60 Dialoge, Seed 20261019, acht Züge, Kind wählt, ohne
Lösung) ist der letzte Lauf mit der Leiter. Der Vergleichslauf mit dem
neuen Ablauf nimmt dieselben Vorgaben; sie sind die Standardwerte:

    python benchmark\mathe\lauf.py --kennung E --seed 20261019
    python benchmark\mathe\auswertung.py

Gleicher Seed heißt gleiche Startwerte für das simulierte Kind je Dialog;
weil die Hilfen anders ausfallen, laufen die Gespräche trotzdem
auseinander. Die Rubrik für den neuen Lauf (`bewertung/E.json`) wird nach
`bewertung/_vorlage.json` angelegt, am besten für dieselben 20 Dialoge, die
in `bewertung/D3.json` bewertet sind.

## Was der Lauf seit dem Umbau vom 30.10.2026 nachbaut

Thomas (30.10.2026): Die Zech-Stufen sollen nicht mehr mechanisch als Leiter
gegeben werden, sondern nach einer Diagnose je Beitrag: wo das Kind steht
(Lage), was es will (Absicht), was es braucht (Bedarf: Hilfe 0 bis 4, Form
direkt oder indirekt). `lauf.py` importiert die Module der Anwendung und
folgt `views.antwort_geben`, `views._hilfe_erzeugen` und
`Task.naechster_zug` (Letzteres ohne Datenbank nachgebaut, in
`lauf.Aufgabe.naechster_zug`):

- Erster Zug ohne Versuch: Volksschule Stufe 1, Mittel- und Oberstufe eine
  Nachfrage (`levels.erste_hilfe`). Der Auftakt (ein Versuch des Kindes vor
  jeder Hilfe) wird nicht nachgebaut: Die Profile erwarten, dass die App
  beginnt, und so bleibt der Lauf mit `D3` vergleichbar.
- Ein Versuch läuft durch `pruefung.diagnose` mit dem Stand (Stufe der
  letzten Stufenhilfe), der Frage der letzten Hilfe
  (`levels.letzte_frage`), `hilfen_bisher`, `fehler_vorher`,
  `nachfragen_bisher` und `letzte_war_nachfrage`. Zurück kommen Ergebnis,
  Fehler, Lage, Absicht, Form und die GEWÄHLTE Hilfe (0 bis 4, 5 bei
  „richtig"), die Serverregeln aus `levels.hilfe_waehlen` eingeschlossen.
  Den Wunsch des Modells aus dem JSON liest der Lauf an der Stelle mit, an
  der `pruefung` es zerlegt (`_json_aus`), ohne etwas zu verändern; so
  lässt sich zählen, wie oft der Server ihn überstimmt hat.
- Der nächste Zug nach denselben Regeln wie `Task.naechster_zug`: 0 heißt
  Nachfrage des Tutors (`levels.nachfrage_tutor_prompt`, Ausgangsprüfung mit
  der Stufe, auf der das Kind steht, mindestens 1); dieselbe Stufe wie
  zuletzt heißt Wiederholung mit Verengung (`levels.wiederholung_zusatz`,
  Weite `eng`, Temperatur 0,6, höchstens zwei je Stufe, dann eine stärker);
  sonst die gewählte Stufe, tiefer oder höher, bis zur Obergrenze der
  Lehrperson.
- Die Hilfe bekommt Form, Weite und Absicht in den Systemprompt
  (`levels.system_prompt(..., form=, weite=, absicht=)`) und die
  Einschätzung des Beitrags als Zeile in die Anfrage
  (`levels.einschaetzung_text`), bei „falsch" dazu den Fehler.
- „richtig" beendet die Aufgabe: Ereignis `bestaetigungskarte`, dann der
  Zug `bestaetigung` (`levels.bestaetigung_prompt`: „Das stimmt." mit einer
  Warum-Frage, Ausgangsprüfung mit dem Stand), darauf antwortet das Kind
  genau einmal (ein kurzer Begründungsversuch in seiner Rolle, nur
  eingestuft, nicht diagnostiziert), dann der Zug `nachsatz`
  (`levels.nachsatz_prompt`, Prüfung mit Stufe 5), dann ist Schluss.
  Bestätigung und Nachsatz zählen nicht gegen `--zuege`.
- Das Kind antwortet auf eine Nachfrage des Tutors wie auf eine Hilfe
  (Profile unverändert). Es sieht den Hilfetext ohne den festen
  Arbeitsauftrag der Stufe darunter, wie die Seite seit 30.10.: Die Hilfe
  endet mit ihrer eigenen Frage. Eine Frage des Kindes (Präfix `FRAGE:`)
  wird wie bisher auf der Stufe beantwortet, auf der es steht, mit der
  Frage der offenen Hilfe als Abschluss.
- Unverändert: Anweisungen und Ausgangsprüfung je Schulstufe, die
  Lösungsabfrage vor Stufe 5 (nach „Nein" bleibt der Versuchsmodus, und
  die Diagnose darf danach auch wieder tiefer gehen), ausgeschöpfte Stufen
  (einmal die Gelegenheit zu fragen oder weiterzuprobieren), und der
  Nachlauf, wenn das Kind laut Muster das Ergebnis genannt hat, die
  Diagnose es aber nicht erkannt hat (noch ein Zug, dann „Ich bin fertig";
  Feld `nach_ergebnis`).

Die Läufe A bis C sind mit der ersten Fassung von `lauf.py` entstanden, D
bis D3 mit der Fassung vom 19.10.2026 (Git-Geschichte); ihre Protokolle
bleiben unverändert liegen und werden von `auswertung.py` weiter gelesen.
Die Maße zur Hilfe nach Diagnose ergeben für sie die Leiter: keine
Nachfrage, erste Hilfe Stufe 1, keine Form.

## Schalter

| Schalter | Bedeutung |
|---|---|
| `--kennung NAME` | Unterordner für die Protokolle (Vorgabe `spark`, mit `--probe` `probe`) |
| `--probe` | ein Dialog mit eingebautem Fake-Modell, kein Netz, Ausgabe im Temp-Verzeichnis (siehe oben) |
| `--frageerkennung kind` | Vorgabe: das Kind wählt selbst (Präfix `FRAGE:` im Beitrag ist eine Frage, alles andere ein Versuch) |
| `--frageerkennung keine` | eine Seite ohne zweiten Knopf: jeder Beitrag ist ein Versuch |
| `--mit-loesung` | die Musterlösung wird wie eine geprüfte Lösung der Qualitätssicherung in Hilfe, Diagnose, Ausgangsprüfung und Stufe-5-Prüfung gegeben |
| `--nur vs01,sek08` | nur diese Aufgaben |
| `--stufe vs` | nur eine Schulstufe (`vs`, `sek1`, `matura`) |
| `--zuege 8` | Züge je Dialog (Stufenhilfen, Nachfragen des Tutors und Antworten auf Fragen des Kindes; Bestätigung und Nachsatz kommen dazu) |
| `--weiter` | vorhandene Protokolle im Zielordner überspringen |
| `--seed N` | Startwert für das simulierte Kind (Vorgabe 20261019, wie D3) |
| `--ausgabe ORDNER` | Ordner für die Protokolle (Vorgabe `benchmark/mathe/ergebnisse`) |

## Dateien

- `aufgaben.json`: 60 Aufgaben (20 Volksschule, 20 Sekundarstufe I, 20
  Matura) mit Lösung, Lösungsweg, typischen Fehlvorstellungen und
  Erkennungsmustern für das Ergebnis (reguläre Ausdrücke auf dem
  normalisierten Text, siehe `lauf.normalisieren`). Alle Lösungen sind mit
  sympy beziehungsweise `Fraction` nachgerechnet.
- `profile.json`: zwölf simulierte Kinder (schwach, umgehend, mittel, stark,
  je Schulstufe) als Systemprompt für das Kind-Modell. Die Zuordnung zu den
  Aufgaben steht in `lauf.zuordnung`: Die Profile kreisen über die Aufgaben,
  alle Dialoge laufen mit „Lösung nur auf ausdrückliche Bitte", außer je
  Schulstufe zwei Dialoge des umgehenden Profils mit „Nur Tipps".
- `lauf.py`: der Lauf.
- `auswertung.py`: die Auswertung. Liest zusätzlich
  `ergebnisse/bewertung/<lauf>[.teil].json` (Rubrik von Hand, 0 bis 2 Punkte
  je Kriterium und Zug, mit Begründung; mehrere Dateien je Lauf sind erlaubt;
  Dateien mit Unterstrich am Anfang sind Vorlagen) und
  `ergebnisse/claude/*.json` (die Vergleichsdialoge, in denen die
  Tutorantworten von Claude stammen, auf denselben Kinderzügen). Ordner
  unter `ergebnisse/`, deren Name mit einem Unterstrich beginnt, liest sie
  nur mit `--lauf`.
- `zusammenfuehren.py`: setzt `ergebnisse/claude/claude_zuege.json` in die
  Vergleichsprotokolle ein und protokolliert, was die Ausgangsprüfung der App
  in diesen Texten gefunden hätte.
- `ergebnisse/bewertung/_vorlage.json`: der Kopf für eine neue Bewertung
  mit der Skala aller zehn Kriterien.
- `ergebnisse/`: die Protokolle. Jede Datei enthält je Zug den vollständigen
  Systemprompt, die Anfrage, die Antwort, die Ausgangsprüfung (erster
  Versuch, Schärfung, Kürzung, Notfalltext, Temperatur, Fehler im Prompt),
  den Beitrag des Kindes, die Ampel und die Diagnose, dazu alle Messungen
  (Dauer und Token je Anfrage).
  Läufe des Berichts: `spark_ist` (A), `spark_kind` (B),
  `spark_kind_loesung` (C), `claude`, und die Nachmessung nach dem Umbau in
  drei Läufen `D`, `D2`, `D3` (Bericht, Abschnitt 9; `D3` ist der Stand des
  Codes vom 19.10., `bewertung/D3.json` die Rubrik dazu); abgebrochene
  Zwischenläufe `spark_fragezeichen_nur_weg` und `spark_fragezeichen_abbruch`.

Alle Kinder sind Simulation. Es sind keine Daten echter Kinder enthalten.

## Was das Protokoll festhält

- `ablauf`: `diagnose` seit 30.10.2026; die Läufe davor kennen das Feld
  nicht.
- `ergebnis.status`: `selbst_geloest`, `loesung_gezeigt`,
  `stufen_ausgeschoepft`, `abgebrochen_zuege`, `abgebrochen_nach_nein`,
  `als_richtig_bestaetigt_ohne_ergebnis` (die Diagnose sagte „richtig", die
  Ergebnismuster nicht), `spark_fehler`; aus den alten Läufen auch
  `selbst_geloest_ohne_rueckmeldung`.
- `ergebnis.selbst_gerechnet` und `zug_selbst_gerechnet`: Hat das Kind das
  Ergebnis vor Stufe 5 selbst genannt, und nach wie vielen Zügen? Die
  Auswertung rechnet das mit den aktuellen Mustern aus `aufgaben.json`
  nachträglich neu.
- `ergebnis.diagnose_richtig`, `diagnose_richtig_obwohl_falsch`: wie oft die
  Diagnose „richtig" gesagt hat, und wie oft gegen die Ergebnismuster.
- `ergebnis` seit 30.10.: `hilfen` (Stufenhilfen), `nachfragen_tutor`,
  `erster_zug` (`hilfe` oder `nachfrage`), `erste_hilfe_stufe`,
  `bestaetigung`, `warum_beantwortet`, `nachsatz`, `diagnosen_mit_wunsch`
  und `ueberstimmt` (Diagnosen, in denen der Server anders entschieden hat
  als das Modell wollte; „richtig" zählt nicht mit).
- `zuege[].art`: `hilfe` (eine Stufe), `nachfrage` (Antwort auf eine Frage
  des Kindes, so seit Lauf A), `nachfrage_nach_ende`, `versuch_nach_nein`,
  `versuch_nach_ende`; seit 30.10. `nachfrage_tutor` (die Frage des Tutors
  vor der Hilfe), `bestaetigung` (Das stimmt. mit Warum-Frage; in den
  Läufen A bis C eine Hilfe nach dem Ergebnis) und `nachsatz`.
- `zuege[]` je Tutorzug seit 30.10.: `zug_art` (`levels.ART_*`), `stufe`
  (nur bei einer Stufenhilfe, sonst `null`), `pruefstufe` (die Stufe, mit
  der die Ausgangsprüfung lief), `stand`, `wiederholung`, `form`
  (`direkt`, `indirekt`; nur Stufenhilfen), `weite` (`weit`, `eng`; nur
  Stufenhilfen), `lage`, `absicht`, `grund`, `hilfe_gewuenscht` (Wunsch des
  Modells aus dem JSON, 0 bis 4, oder `null`), `hilfe_gewaehlt`
  (Entscheidung des Servers aus der Diagnose) und `einschaetzung` (die
  Zeile in der Anfrage). Alle beziehen sich auf die Diagnose des Beitrags
  DAVOR, die diesen Zug geformt hat; beim ersten Zug sind sie leer.
- `zuege[].diagnose`: Stufe, Grund, Ergebnis und Fehler aus
  `pruefung.diagnose`; seit 30.10. dazu `lage`, `absicht`, `form`, `stand`,
  `frage_der_hilfe`, `hilfe_gewuenscht`, `hilfe_gewaehlt` und `modell` (die
  rohen Kategorien aus dem JSON des Modells). Die Diagnose steht an dem
  Zug, auf den das Kind geantwortet hat.
- `zuege[].begruendung`: `true` am Zug `bestaetigung`, wenn `kind_text` die
  Antwort auf die Warum-Frage ist (kein Versuch, keine Diagnose).
- `zuege[].nach_ergebnis`: der eine Zug des Nachlaufs, wenn das Kind das
  Ergebnis laut Muster genannt hat und die Diagnose es nicht erkannt hat.
- `zuege[].pruefung`: was die Ausgangsprüfung gefunden hat, dazu
  `fehler_im_prompt`, `temperatur` und bei Stufe 5 `loesung_passt_vorher`,
  `loesung_passt_nachher` oder `loesung_geaendert`.
- `ereignisse[]`: Lösungsabfrage (ja/nein), Versuche nach einem „Nein",
  die Karte „Das stimmt." (`bestaetigungskarte`).
- `messungen`: Dauer in ms je Anfrage (`hilfe`, `hilfe_2`, `loesung_2`,
  `nachfrage`, `nachfrage_tutor`, `bestaetigung`, `nachsatz`, jeweils mit
  `_2` für den zweiten Versuch; `diagnose`, `einstufen` für Fragen und die
  Begründung, `kind`).

## Was die Auswertung misst

Wie bisher je Lauf, Schulstufe, Profil und Hilfeumfang: Status, selbst
gerechnet, Züge bis zum Ziel, danach bestätigt, Lösung gezeigt, Lösung
verraten, Verstöße der Ausgangsprüfung, Kürzungen, Fragen je Hilfe, Länge,
Diagnoserichtung (gemessen am Stand des Kindes) und -ergebnis, Ampel,
Latenz. Neu die Spalte „Stufenhilfen je Dialog" neben „Züge je Dialog",
weil Nachfrage, Bestätigung und Nachsatz jetzt eigene Züge sind.

Abschnitt „Hilfe nach Diagnose (seit 30.10.2026)", je Lauf, Schulstufe und
Profil, alle Läufe nebeneinander (`D3` zeigt die Leiter):

- Nachfragen des Tutors je Dialog und Anteil der Dialoge mit Nachfrage;
  Anteil der Dialoge, die mit einer Nachfrage beginnen.
- Stufe der ersten Hilfe (Verteilung 1 bis 4).
- Sprünge um mehr als eine Stufe zwischen zwei Stufenhilfen, hoch und
  runter, dazu Rückschritte überhaupt (jede tiefere Stufe als zuletzt).
- Anteil direkt (Form) und eng (Weite) über die Stufenhilfen.
- Anteil Dialoge mit Bestätigung mit Warum-Frage, mit beantworteter
  Warum-Frage und mit Nachsatz.
- Überstimmt: Anteil der Diagnosen (mit Wunsch, ohne „richtig"), in denen
  die gewählte Hilfe vom Wunsch des Modells abweicht, mit den Gründen aus
  `levels.hilfe_waehlen` als eigener Tabelle.
- Verteilung von Lage und Absicht über alle diagnostizierten Beiträge (auch
  die Versuche nach „Nein" und nach den Stufen).

Dazu eine Tabelle je Art des Tutorzuges (Verstöße, Kürzungen, genau eine
Frage, Länge): Nachfrage und Bestätigung sollen genau eine Frage stellen,
der Nachsatz keine. Die Durchrutscher-Tabelle misst Nachfrage und
Bestätigung an ihrer Prüfstufe. `auswertung.json` trägt dieselben Maße
unter `diagnose`, je `lauf`, `lauf/stufe` und `lauf/profil`.

## Rubrik (bewertung/*.json)

Je Tutorzug zehn Kriterien mit 0 bis 2 Punkten und Begründung; `null`, wenn
ein Kriterium auf den Zug nicht anwendbar ist. Die genaue Skala steht in
`bewertung/_vorlage.json` (diesen Kopf in jede neue Bewertung übernehmen)
und für die ersten sechs im Bericht, Abschnitt 2.5.

Seit Lauf A: `fachlich` (richtig), `stufe` (Stufe eingehalten), `frage`
(genau eine Frage, kurz, altersgerecht), `fehler` (Fehler des Kindes
aufgegriffen; nur wenn einer offen war), `diagnose` (nur nach einem
Versuch), `umgehung` (nur nach einem Umgehungsversuch).

Seit 30.10.2026 (Hilfe nach Diagnose):

- `passung`: Passt die Hilfe zur Lage des Kindes, war die Diagnose richtig?
  0 Lage verkannt (Rückmeldung ohne Versuch, Motivation statt Rückmeldung
  bei einem Fehler, Nachfrage bei klarer Lage); 1 Lage grob richtig, Hilfe
  geht an der Stelle vorbei; 2 Lage richtig erkannt, Hilfe setzt dort an.
  `null` beim ersten Zug ohne Beitrag.
- `minimal`: War es die kleinste Hilfe, die vermutlich weiterbringt? 0
  deutlich zu stark (Schritt oder Weg genannt, wo ein Hinweis gereicht
  hätte) oder deutlich zu schwach (das Kind hatte diese Hilfe schon und kam
  nicht weiter); 1 eine Stufe daneben, vertretbar; 2 eine stärkere Hilfe
  wäre nicht nötig gewesen, eine schwächere nicht genug. `null` beim ersten
  Zug ohne Beitrag.
- `weite`: Weit begonnen, erst bei Stagnation verengt? 0 gleich eng
  gefragt, obwohl das Kind nicht festgefahren war, oder weit geblieben,
  obwohl die weite Frage schon zweimal nicht gereicht hat; 1 Weite passt
  ungefähr; 2 die erste Hilfe einer Kategorie lässt Raum, die Wiederholung
  fragt nach genau einer Stelle. `null` beim Nachsatz.
- `bezug`: Geht der Zug auf die letzte Äußerung des Kindes ein, mit dessen
  Worten und Zahlen? 0 kein Bezug (Floskel, generischer Tipp, an der Frage
  des Kindes vorbei); 1 nur allgemein („du hast etwas probiert"); 2 greift
  konkret auf, was das Kind zuletzt geschrieben hat. `null` beim ersten Zug
  ohne Beitrag.
