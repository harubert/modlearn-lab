# Datenschutz: Einordnung für Spark, Lab-Plattform und Klassenmodus

Stand 16.09.2026 · Anlass: Annahmen von Thomas am 16.09. und der geplante Beitrag bei der Rheticus-Tagung. Keine Rechtsberatung. Der schnellste verbindliche Schritt ist die Datenschutzbeauftragte bzw. der Datenschutzbeauftragte der PH.

## 1 Was stimmt

- **Eigener Server statt Cloud ist der größte Gewinn.** Keine Übermittlung an einen Anbieter, keine Drittstaatenfrage, keine Auftragsverarbeitung mit einem US-Konzern. Das räumt die schwierigsten Punkte weg.
- **Sobald der Spark in der PH steht, ist er PH-Infrastruktur.** Für die Nutzung durch Studierende und Mitarbeitende der PH ist die Rechtslage einfach: Die PH ist Verantwortliche und handelt im Rahmen ihrer gesetzlichen Aufgaben.
- **Hosting in Österreich oder Deutschland** für die Plattform ist richtig gewählt.

## 2 Was so nicht stimmt

**„ISO-zertifiziert, also datenschutzkonform."** ISO 27001 ist ein Sicherheitsstandard, keine Rechtsgrundlage. Für jeden Hoster braucht es einen Auftragsverarbeitungsvertrag nach Artikel 28 DSGVO. Den bieten World4You und HostEurope an, er muss aber abgeschlossen und abgelegt sein.

**„Die Praxisschule ist Teil der PH."** Das ist sie datenschutzrechtlich nicht. Eine Schule hat einen eigenen Schulerhalter und ist eigene Verantwortliche. Dass heute schon E-Mails mit personenbezogenen Daten hin und her gehen, macht daraus keine Einheit. Es zeigt eher, dass auch diese bestehende Praxis eine Grundlage braucht.

**„Schulische Infrastruktur, also passt es."** Der Ort der Verarbeitung ist nur ein Teil. Es braucht zusätzlich eine Rechtsgrundlage, eine Zweckbindung, Information der Betroffenen, ein Löschkonzept und einen Eintrag im Verarbeitungsverzeichnis.

## 3 Der elegante Weg: gar keine personenbezogenen Daten

Wenn im Klassenmodus keine personenbezogenen Daten verarbeitet werden, entfällt der größte Teil der Diskussion. Dafür ist die Architektur auszulegen:

- Kinder bekommen **keine Konten**, sondern einen Sitzungscode von der Lehrperson.
- **Keine Namen**, keine Klassenlisten, keine Anmeldedaten von Kindern.
- **Keine Speicherung** der Eingaben über die Stunde hinaus. Nach dem Ende der Sitzung ist alles gelöscht.
- **Filter vor dem Modell**, der Namen und andere Personenangaben aus freien Texten entfernt, bevor sie verarbeitet werden. Kinder schreiben so etwas, ohne nachzudenken.
- **Protokolle ohne Inhalte**: nur Zeitpunkt, Sitzung, Anzahl Anfragen, keine Texte.
- Serverprotokolle mit IP-Adressen auf das Nötige beschränken und kurz aufbewahren.

Bleibt es dabei, ist die Verarbeitung im Regelfall nicht personenbezogen. Das ist der stärkste Punkt gegenüber jedem Cloud-Dienst und zugleich der Kern des Vortrags.

## 4 Was trotzdem zu tun ist

| Was | Wer | Wann |
|---|---|---|
| Datenschutzbeauftragte der PH einbinden, Vorhaben vorstellen | Thomas | vor dem ersten Schuleinsatz |
| Eintrag im Verarbeitungsverzeichnis der PH für Lab-Plattform und Klassenmodus | PH | vor Echtbetrieb |
| **Auftragsverarbeitungsvertrag mit dem Hoster (gesetzt, Entscheidung Thomas 16.09.)** | Thomas | vor Echtbetrieb |
| **Mustervertrag zur Auftragsverarbeitung für teilnehmende Schulen vorbereiten**, damit jede Schule nur unterschreiben muss | Thomas mit DSB | vor dem ersten Schuleinsatz |
| Information für Lehrpersonen und Eltern, eine Seite, verständlich | Thomas | vor dem ersten Schuleinsatz |
| Kurze Vereinbarung mit jeder teilnehmenden Schule: was passiert, was nicht gespeichert wird, wer wofür zuständig ist | Thomas | je Schule |
| Prüfung, ob eine Datenschutz-Folgenabschätzung nötig ist | DSB der PH | vor dem ersten Schuleinsatz |
| Technische Maßnahmen dokumentieren: Zugriff nur über Tailscale, keine offenen Ports, Verschlüsselung, Backups | Claude | laufend |

Zur Folgenabschätzung: Daten von Kindern gelten als besonders schutzwürdig, und neue Technik in einem Bildungskontext ist ein typischer Anlass. Wenn wirklich keine personenbezogenen Daten verarbeitet werden, entfällt sie. Diese Einschätzung sollte die oder der DSB schriftlich bestätigen, dann steht sie.

## 5 Rollen, wenn doch Daten anfallen

Sollte sich später zeigen, dass personenbezogene Daten verarbeitet werden, ist die saubere Konstruktion:

- Die **Schule ist Verantwortliche** für die Daten ihrer Schüler:innen.
- Die **PH ist Auftragsverarbeiterin** und verarbeitet nur nach Weisung der Schule.
- Dafür genügt ein kurzer Auftragsverarbeitungsvertrag nach Artikel 28, den die Schulen unterschreiben.

Die Alternative, gemeinsame Verantwortlichkeit nach Artikel 26, ist aufwendiger und hier nicht nötig.

## 6 Formulierungen für die Bühne

**Nicht sagen:** „ChatGPT im Unterricht ist verboten." Das ist zu grob und angreifbar.

**Sagen:** „Die Nutzungsbedingungen der gängigen Dienste verlangen in der Regel ein Mindestalter und bei Minderjährigen die Zustimmung der Eltern. Für den Unterricht bräuchte es zusätzlich eine Rechtsgrundlage und einen Vertrag mit dem Anbieter. Beides fehlt in der Praxis meistens. Wer die Klasse mit dem eigenen Konto arbeiten lässt, bewegt sich in einem Graubereich, den die Schule verantwortet."

**Und die eigene Position dazu:** „Unser Weg räumt die Frage weg, statt sie zu verwalten: keine Konten für Kinder, keine Speicherung, keine Cloud."

**Nicht sagen:** „datenschutzkonform" oder „rechtssicher", solange Verarbeitungsverzeichnis, Vereinbarung mit den Schulen und die Rückmeldung der oder des DSB fehlen. „Datensparsam" und „lokal" sind richtig und tragen.

## 7 Nachtrag 31.10.2026: Das Protokoll der Anfragen bleibt und ist einsehbar

Thomas: „Wenn es zum Frontiermodell weitergeht, möchte ich die Kommunikation zwischen der lokalen KI und dem Frontiermodell auch einsehen können. Die muss natürlich auch auf dem Server gespeichert bleiben."

**Was dazu gilt.** Das Forschungsprotokoll (`Interaction`, Abschnitt 3b der CLAUDE.md) hat jede Anfrage an ein Sprachmodell schon bisher festgehalten, je nach Protokollstufe mit oder ohne Text, und es überlebt die Sitzung: Die Zeilen hängen über einen pseudonymen Schlüssel an der Sitzung, die Zuordnung zu einem Tier stirbt mit der Teilnahme. Neu ist, dass die Lehrperson es sieht, und dass die Anweisung an die Gegenstelle mitgeschrieben wird.

**Gebaut:**

- **Die Anweisung an die Gegenstelle** (der Systemprompt der Qualitätssicherung, des Safe Chat und des Urteils) steht jetzt in jeder Zeile des Weges nach draußen (`Interaction.instruction`, Migration 0027), auf jeder Protokollstufe. Das ist eigener Text der Anwendung, kein Inhalt eines Kindes; Stufe 1 („nur Metadaten, keine Inhalte") bleibt damit, was sie ist.
- **Die Protokollansicht** (`/lehrperson/protokolle/` und `/lehrperson/sitzung/<code>/protokoll/`, `protokoll_views.py`): alle Sitzungen der Lehrperson, offen und beendet, mit der Zahl der Anfragen am Spark und nach draußen; je Sitzung die Zeitleiste, eine Zeile je Anfrage, aufklappbar. Beim Weg nach draußen die ganze Kommunikation: Anweisung, das Ausgehende (maskiert, exakt so, wie es das Internet gesehen hat), die Antwort, und was lokal daraus wurde (mit eingesetzten Werten, nur auf Stufe 3). Dazu Modell, Stufe, Dauer, Token, Kosten, Leak-Check, ersetzte Angaben je Typ und die Kategorien der Diagnose. Filter wie in 3b: nur ein Weg, nur blockierte Aufrufe, nur eine Stufe, nur eine Kennung. Export der gefilterten Zeilen als JSON und CSV.
- **Verlinkt** im Kopf jeder Seite („Protokolle") und auf der Sitzungsseite („Protokoll der Anfragen an die Sprachmodelle").

**Was auf welcher Stufe zu sehen ist.** Stufe 1: nur Zahlen und die Anweisung, die Zeile sagt „Nur Zahlen". Stufe 2: zusätzlich das Maskierte, hinaus und zurück. Stufe 3: zusätzlich der Originaltext der Anfrage und die lokal zurückgeschriebene Antwort. Die Stufe steht an jeder Zeile, weil sie je Teilnahme verschieden sein kann (Zustimmung).

**Für die Datenschutzseite.** `/datenschutz/` sagt jetzt unter „Was die Lehrperson sieht", dass das Protokoll der Anfragen nach dem Ende der Sitzung in der gewählten Stufe bleibt, ohne Zuordnung zu einem Tier. Der Satz „Es wird kein Dienst eines externen Anbieters aufgerufen" weiter oben ist davon unberührt und seit der Qualitätssicherung nur mit Schalter aus richtig; Thomas formuliert ihn.

## 8 Nachtrag 31.10.2026: Bildausschnitte an das externe Modell (Entscheidung Thomas, noch nicht ausgerollt)

Was sich ändert: Bisher ging an das externe Modell (Qualitätssicherung, seit 23.09., nur wenn die Lehrperson sie einschaltet) ausschließlich Text, den der Spark vorher ohne Personen neu formuliert, erkannt, maskiert und geprüft hat. Neu kann die Lehrperson je Sitzung zusätzlich freigeben, dass von einem Foto der Aufgabe ein **Ausschnitt** mitgeht: nur die gedruckte Aufgabe, neu kodiert ohne Metadaten, Handschrift, Namen, Gesichter und Logos geschwärzt, danach ein zweites Mal geprüft (Modell und deterministische Regeln). Im Zweifel geht nichts hinaus. Das Foto selbst und der Lösungsversuch des Kindes gehen nie hinaus. Technik: `docs/Bildweiterleitung.md`, Erklärung für Lehrpersonen unter `/bildpruefung/`.

Einordnung, keine Rechtsberatung:

- Abschnitt 3 („gar keine personenbezogenen Daten") bleibt das Ziel und ist für den Text weiter so gebaut. Beim Bild ist der Anspruch bescheidener: Die Kette entfernt, was sie findet, und sie wird mit Testbildern gemessen (`benchmark/bildkette/`). Ein übersehenes Element wäre ein Personenbezug beim externen Anbieter. Deshalb Wortwahl **zugeschnitten und bereinigt**, nicht „anonymisiert", und deshalb die Freigabe je Sitzung durch die Lehrperson mit Erklärung und Transparenzansicht.
- Für die DSB: Die Verarbeitung durch den externen Anbieter (OpenAI, API ohne Training laut dessen Bedingungen, Auftragsverarbeitung zu prüfen) besteht seit der Qualitätssicherung; neu ist die Datenart Bildausschnitt. Zu klären: ob der Auftragsverarbeitungsvertrag mit dem Anbieter das abdeckt, ob die Einführung in das Verarbeitungsverzeichnis gehört, und ob die Information für Lehrpersonen und Eltern (Abschnitt 4) den Bildweg nennt.
- Die öffentliche Datenschutzseite (`/datenschutz/`) sagt derzeit „Es wird kein Dienst eines externen Anbieters aufgerufen". Das stimmt nur, solange die Lehrperson die Qualitätssicherung aus lässt, und zwar schon seit dem 23.09. Der Satz braucht eine Formulierung von Thomas, unabhängig vom Bildweg.
- Der Satz in Abschnitt 6 („keine Cloud") gilt für den Normalbetrieb weiter: beide Schalter sind in jeder neuen Stunde aus.

Vor dem ersten Einsatz mit Kindern: Messung mit echten Heftfotos (keine Kinderfotos), Vorlage bei der DSB durch Thomas, Freigabe durch ihn. Bis dahin verlässt kein Bild die Einrichtung; Paper A (Siegen, Stand 31.10.) beschreibt das richtig.

## 8 Nachtrag 1.11.2026: Die Protokollstufe ist fest eingestellt

Thomas (über die Siegen-Sitzung, 1.11.2026): Die Auswahl der Protokollstufe verschwindet aus dem Lehrpersonen-Formular. Spark und Server stehen im Haus, genutzt wird das Lab von der Übungsschule und der PH, also faktisch ein Schulserver wie Moodle; die Wahl verkomplizierte den Ablauf, und die Lehrpersonen verstanden sie nicht. Es gilt **Stufe 3**: Die Originaltexte der Kinder werden aufgezeichnet. Für Forschungszwecke werden die Texte vor der Auswertung anonymisiert.

Umgesetzt:

- `settings.PROTOKOLLSTUFE` (Umgebungsvariable `PROTOKOLLSTUFE`, Vorgabe 3) ist die Stufe jeder neuen Sitzung; `PROTOKOLLSTUFE_WAEHLBAR=1` holt die Auswahl ins Formular zurück. Wird das Lab für externe Schulen geöffnet, lässt sich so die Wahl wieder anbieten oder mit `PROTOKOLLSTUFE=1` fest nur Zahlen speichern. Beides ist Konfiguration, kein Umbau.
- Das Formular zeigt die feste Stufe als Satz („Aufzeichnung: Forschung vollständig: zusätzlich der Originaltext – für diesen Server fest eingestellt. Für die Forschung werden die Texte vor der Auswertung anonymisiert; welches Kind einen Beitrag geschrieben hat, wird mit der Sitzung gelöscht.“).
- `/datenschutz/` nennt die fest eingestellte Stufe und die Anonymisierung vor der Auswertung; Stand der Rechtstexte 1. November 2026.
- Der Satz aus §7, die Stufe könne je Teilnahme verschieden sein, gilt nur noch für Erwachsene: Wer vor dem Beitritt die Zustimmung zu Stufe 3 verweigert, wird weiter nach Stufe 1 aufgezeichnet (`Participation.protokollstufe`); Kinder werden nicht gefragt, für sie gilt die feste Stufe.
- Paper A sagt dazu: „texts are kept in a pseudonymous research log and anonymised before analysis; for other schools, logging can be reduced to counts.“ Das entspricht der Umsetzung.
