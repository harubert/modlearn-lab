/* Holt den naechsten Zug des Tutors und schreibt ihn laufend auf die Seite.
 *
 * Bewusst fetch mit POST statt EventSource: Das Anfordern einer Hilfe
 * verbraucht eine Stufe, veraendert also etwas. Ein GET waere dafuer der
 * falsche Weg und ohne CSRF-Schutz.
 *
 * Der eigene Versuch und der naechste Zug sind EIN Vorgang. Wer sein
 * Ergebnis gerade gemeldet hat, will nicht noch einmal auf einen Knopf
 * druecken, um zu erfahren, ob es stimmt. Stimmt es, kommt die Karte "Das
 * stimmt.", und in sie laeuft die Bestaetigung mit der Warum-Frage ein;
 * sonst kommt der naechste Zug von selbst (Benchmark 19.10.2026, Abschnitt
 * 6.3; Hilfe nach Diagnose 30.10.2026).
 *
 * Nicht jeder Zug ist eine Stufe. Der Server sagt mit dem start-Ereignis,
 * was kommt (art): "hilfe" (Stufe 1 bis 5, mit Marke und Punkt im Weg),
 * "nachfrage" (eine Frage vor der Hilfe, das Kind antwortet), "bestaetigung"
 * (nach einem richtigen Ergebnis, Antwort freiwillig), "nachsatz" (die
 * Antwort auf die Begruendung des Kindes, danach kommt nichts mehr). Die
 * Fortschrittspunkte aendern sich nur bei einer Stufe.
 *
 * Vor der Loesung fragt der Server zurueck, statt sie auszugeben, sofern die
 * Lehrperson das so eingestellt hat. Die Pruefung sitzt dort; dieses Skript
 * zeigt die Frage nur an. Nach "Nein, ich probier weiter" bleibt der
 * Verfasser im Versuchsmodus.
 *
 * Barrierefreiheit: Der Text laeuft sichtbar Stueck fuer Stueck ein, wird
 * aber erst am Ende als Ganzes angesagt. Nichts springt: Die Karte, in die
 * der Text einlaeuft, wird am Ende zur fertigen Karte an derselben Stelle.
 */
(function () {
  "use strict";

  var form = document.getElementById("verfasser-form");
  var verlauf = document.getElementById("verlauf");
  var arbeitsplatz = document.getElementById("arbeitsplatz");
  if (!form || !verlauf) { return; }

  var knopf = document.getElementById("hilfe-knopf");
  var tippzeile = document.getElementById("tippzeile");
  var kasten = document.getElementById("neue-hilfe");
  var stufeFeld = document.getElementById("neue-stufe");
  var bezeichnungFeld = document.getElementById("neue-bezeichnung");
  var textFeld = document.getElementById("neue-text");
  var fehlerFeld = document.getElementById("hilfe-fehler");
  var ansage = document.getElementById("ansage");
  var abfrage = document.getElementById("loesungsabfrage");
  var abfrageFrage = document.getElementById("loesungsfrage");
  var abfrageHinweis = document.getElementById("loesungshinweis");
  var jaKnopf = document.getElementById("loesung-ja");
  var neinKnopf = document.getElementById("loesung-nein");
  var senden = document.getElementById("senden");
  var fragen = document.getElementById("fragen");
  var fertigkarte = document.getElementById("fertigkarte");
  var fertigText = document.getElementById("fertig-text");
  var fertigTutor = document.getElementById("fertig-tutor");
  var naechsteAufgabe = document.getElementById("naechste-aufgabe");
  var fertigform = document.getElementById("fertigform");
  var fertigKnopf = document.getElementById("fertig-knopf");
  var neueAufgabeForm = document.getElementById("neue-aufgabe-form");
  var stufenende = document.getElementById("stufenende");
  var erledigtmarke = document.getElementById("erledigtmarke");
  var aufgabenkarte = document.getElementById("aufgabenkarte");
  // Die Adressen stehen am Arbeitsplatz, weil der Tippknopf nach dem Ende
  // der Aufgabe nicht mehr da ist, die Bestaetigung aber noch geholt wird.
  var daten = arbeitsplatz ? arbeitsplatz.dataset : {};
  var hilfeUrl = daten.urlHilfe || (knopf ? knopf.dataset.url : "");
  var nachfrageUrl = daten.urlNachfrageAntwort || (knopf ? knopf.dataset.nachfrageUrl : "");

  var ART_HILFE = "hilfe";
  var ART_NACHFRAGE = "nachfrage";
  var ART_BESTAETIGUNG = "bestaetigung";
  var ART_NACHSATZ = "nachsatz";

  // Wohin der Text des laufenden Stroms geht: in den Kasten oder, bei der
  // Bestaetigung, in die Karte "Das stimmt.".
  var laufendeArt = "";

  // Der Verfasser nach der Bestaetigung: Antworten ist freiwillig, die
  // naechste Aufgabe steht daneben offen. Dieselben Worte wie am Server
  // (views._verfasser), damit die Seite nach einem Neuladen gleich aussieht.
  var VERFASSER_FREIWILLIG = {
    beschriftung: "Deine Antwort, wenn du magst",
    hilfe: "Du kannst antworten oder auf „Nächste Aufgabe“ tippen.",
    platzhalter: "Weil …",
    knopf: "Antworten",
    zweiter: ""
  };

  function amEnde(sanft) {
    if (typeof window.zumChatende === "function") { window.zumChatende(sanft); }
  }

  function csrfWert() {
    var treffer = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[2]) : "";
  }

  function kastenSchliessen() {
    kasten.hidden = true;
    kasten.setAttribute("aria-busy", "false");
    textFeld.textContent = "";
    if (fertigkarte) { fertigkarte.setAttribute("aria-busy", "false"); }
  }

  function fehlerZeigen(meldung) {
    fehlerFeld.textContent = meldung;
    fehlerFeld.hidden = false;
    kastenSchliessen();
    amEnde(true);
  }

  function aufraeumen() {
    fehlerFeld.hidden = true;
    fehlerFeld.textContent = "";
  }

  function tippZeigen(sichtbar) {
    if (!knopf) { return; }
    knopf.disabled = false;
    knopf.removeAttribute("aria-disabled");
    if (tippzeile) { tippzeile.hidden = !sichtbar; }
  }

  function tippSperren() {
    if (!knopf) { return; }
    knopf.disabled = true;
    knopf.setAttribute("aria-disabled", "true");
  }

  function feldFokus() {
    var feld = document.getElementById("text");
    if (feld) { feld.focus({ preventScroll: true }); }
  }

  /* Nur Stufen bewegen die Punkte des Weges. Eine Nachfrage, die
   * Bestaetigung und der Nachsatz sind Zuege, keine Stufen. */
  function fortschrittSetzen(gegeben, naechste) {
    var punkte = document.querySelectorAll(".fortschritt-punkt");
    Array.prototype.forEach.call(punkte, function (punkt) {
      var nr = parseInt(punkt.dataset.stufe, 10);
      if (nr === gegeben) { punkt.classList.add("ist-erledigt"); }
      punkt.classList.toggle("ist-aktuell", nr === naechste);
      if (nr === naechste) {
        punkt.setAttribute("aria-current", "step");
      } else {
        punkt.removeAttribute("aria-current");
      }
    });
  }

  function marke(stufe, bezeichnung) {
    return stufe ? "Tipp " + stufe + " · " + bezeichnung : bezeichnung;
  }

  function karteAnhaengen(klasse, kopfzeile, kopfklasse, inhalt, bild, stufe, markeKlasse) {
    var block = document.createElement("li");
    block.className = klasse;
    if (stufe) { block.dataset.stufe = stufe; }
    if (kopfzeile) {
      var kopf = document.createElement("p");
      kopf.className = kopfklasse;
      if (kopfklasse === "schritt-kopf") {
        var markeFeld = document.createElement("span");
        markeFeld.className = markeKlasse || "schritt-marke";
        markeFeld.textContent = kopfzeile;
        kopf.appendChild(markeFeld);
      } else {
        kopf.textContent = kopfzeile;
      }
      block.appendChild(kopf);
    }
    if (bild) {
      var foto = document.createElement("img");
      foto.className = "aufgabenfoto";
      foto.src = bild;
      foto.alt = "Dein Foto";
      block.appendChild(foto);
    }
    var rumpf = document.createElement("div");
    rumpf.className = "hilfe-text";
    rumpf.textContent = inhalt;
    block.appendChild(rumpf);
    verlauf.appendChild(block);
    amEnde(true);
  }

  function hilfeAnhaengen(stufe, bezeichnung, inhalt) {
    karteAnhaengen("karte-hilfe schritt", marke(stufe, bezeichnung), "schritt-kopf",
      inhalt, "", stufe);
  }

  /* Nachfrage und Nachsatz: Karte des Tutors ohne Stufe, leise Marke. */
  function zugAnhaengen(art, bezeichnung, inhalt) {
    karteAnhaengen("karte-hilfe schritt karte-" + art, bezeichnung, "schritt-kopf",
      inhalt, "", 0, "schritt-marke schritt-marke-leise");
  }

  function versuchAnhaengen(text, bild) {
    karteAnhaengen("karte-kind schritt-versuch", "Dein Versuch", "versuch-kopf", text, bild);
  }

  function begruendungAnhaengen(text, bild) {
    karteAnhaengen("karte-kind schritt-versuch karte-begruendung", "Deine Antwort",
      "versuch-kopf", text, bild);
  }

  function frageAnhaengen(text, bild) {
    karteAnhaengen("karte-kind karte-frage nachfrage-frage", "Deine Frage", "versuch-kopf",
      text, bild);
  }

  function antwortAnhaengen(text) {
    karteAnhaengen("karte-hilfe karte-antwort nachfrage-antwort", "Antwort auf deine Frage",
      "schritt-kopf", text);
  }

  /* Der Kasten, beschriftet nach der Art des Zuges. Eine Stufe traegt ihre
   * Marke und Nummer, Nachfrage und Nachsatz nur ihren Namen; eine Null
   * wird nie als Stufe ausgeschrieben. */
  function kastenZeigen(art, stufe, bezeichnung) {
    kasten.classList.remove("karte-" + ART_NACHFRAGE, "karte-" + ART_NACHSATZ);
    if (art === ART_NACHFRAGE || art === ART_NACHSATZ) {
      kasten.classList.add("karte-" + art);
    }
    stufeFeld.textContent = (art === ART_HILFE && stufe) ? "Stufe " + stufe : "";
    bezeichnungFeld.textContent = art === ART_HILFE ? marke(stufe, bezeichnung) : bezeichnung;
    textFeld.textContent = "";
    kasten.hidden = false;
    kasten.setAttribute("aria-busy", "true");
  }

  /* Die Karte "Das stimmt." ans Ende des Gespraechs und sichtbar. Sie ist
   * ein Glied des Verlaufs: Begruendung und Nachsatz haengen sich danach an. */
  function fertigkarteZeigen() {
    if (!fertigkarte) { return; }
    verlauf.appendChild(fertigkarte);
    fertigkarte.hidden = false;
    // Die Notenleiste (1.11.2026): Die Aufgabe ist jetzt abgeschlossen,
    // das Kind darf der Hilfe eine Note geben.
    var notenleiste = document.getElementById("notenleiste");
    if (notenleiste) { notenleiste.hidden = false; }
  }

  /* Die Bestaetigung laeuft nicht in den Kasten, sondern in die Karte "Das
   * stimmt." ein - unter dem, was das Kind geschrieben hat. */
  function bestaetigungBeginnen() {
    kasten.hidden = true;
    kasten.setAttribute("aria-busy", "false");
    fertigkarteZeigen();
    if (fertigTutor) { fertigTutor.textContent = ""; }
    if (fertigkarte) { fertigkarte.setAttribute("aria-busy", "true"); }
  }

  /* Zerlegt den Strom in SSE-Nachrichten. Ein Haeppchen aus dem Netz endet
   * nicht zwingend an einer Nachrichtengrenze, deshalb der Rest-Puffer. */
  function nachrichtenAus(puffer, verarbeiten) {
    var teile = puffer.split("\n\n");
    var rest = teile.pop();
    teile.forEach(function (block) {
      var name = "";
      var daten = "";
      block.split("\n").forEach(function (zeile) {
        if (zeile.indexOf("event:") === 0) { name = zeile.slice(6).trim(); }
        if (zeile.indexOf("data:") === 0) { daten += zeile.slice(5).trim(); }
      });
      if (name && daten) {
        try { verarbeiten(name, JSON.parse(daten)); } catch (e) { /* unvollstaendig */ }
      }
    });
    return rest;
  }

  function abschliessen(nutzlast, gesammelt) {
    var art = nutzlast.art || ART_HILFE;

    if (nutzlast.nachfrage) {
      // Die Antwort auf eine Frage des Kindes: Es geht dort weiter, wo das
      // Kind stand.
      kastenSchliessen();
      antwortAnhaengen(gesammelt);
      senden.disabled = false;
      if (fragen) { fragen.disabled = false; }
      tippZeigen(!tippzeile || !tippzeile.hidden);
    } else if (art === ART_BESTAETIGUNG) {
      // "Das stimmt." mit der Warum-Frage. Antworten ist freiwillig; die
      // naechste Aufgabe steht auf der Karte offen.
      kastenSchliessen();
      fertigkarteZeigen();
      if (fertigTutor) { fertigTutor.textContent = gesammelt; }
      tippZeigen(false);
      window.verfasserModus("antwort", VERFASSER_FREIWILLIG);
    } else if (art === ART_NACHSATZ) {
      // Die Antwort auf die Begruendung. Danach kommt nichts mehr.
      kastenSchliessen();
      zugAnhaengen(art, nutzlast.bezeichnung, gesammelt);
      tippZeigen(false);
      window.verfasserModus("aufgabe");
    } else if (art === ART_NACHFRAGE) {
      // Die Frage vor der Hilfe: Das Kind antwortet, dann kommt die Hilfe.
      // Die Frage steht auf der Karte; der Verfasser wiederholt sie nicht.
      kastenSchliessen();
      zugAnhaengen(art, nutzlast.bezeichnung, gesammelt);
      window.verfasserModus("antwort", { platzhalter: "Erzähl, wie du gedacht hast …" });
      tippZeigen(true);
      feldFokus();
    } else {
      kastenSchliessen();
      hilfeAnhaengen(nutzlast.stufe, nutzlast.bezeichnung, gesammelt);
      fortschrittSetzen(nutzlast.stufe, null);
      if (nutzlast.wartet) {
        // Die Hilfe endet mit ihrer eigenen Frage; darunter steht kein
        // zweiter Arbeitsauftrag mehr (Zech, S. 289: keine Kettenfragen).
        window.verfasserModus("antwort");
        tippZeigen(true);
        feldFokus();
      } else {
        // Die Loesung: keine Frage mehr. Das Kind kann noch etwas fragen
        // oder zur naechsten Aufgabe gehen.
        window.verfasserModus("nachfrage");
        tippZeigen(false);
        if (fertigKnopf) { fertigKnopf.textContent = "Nächste Aufgabe"; }
        if (stufenende) { stufenende.hidden = true; }
      }
    }

    ansage.textContent = nutzlast.bezeichnung + ": " + gesammelt;
    amEnde(true);
  }

  /* Alle freigegebenen Stufen sind vergeben. Das ist kein Fehler: Der
   * Tippknopf verschwindet, der Hinweis bleibt stehen, und das Kind kann
   * weiter probieren oder fragen. */
  function endeZeigen(meldung) {
    kastenSchliessen();
    tippZeigen(false);
    if (abfrage) { abfrage.hidden = true; }
    if (stufenende) {
      stufenende.textContent = meldung;
      stufenende.hidden = false;
    }
    window.verfasserModus("antwort", {
      beschriftung: "Probier weiter",
      hilfe: "Das waren alle Tipps. Du kannst weiter probieren oder etwas fragen."
    });
    ansage.textContent = meldung;
    amEnde(true);
  }

  /* Nach dem Ende kommt nichts mehr: Die Aufgabe ist fertig und bestaetigt.
   * Kein Fehler, nur den Kasten weg und den Weg zur naechsten Aufgabe. */
  function nichtsMehr() {
    kastenSchliessen();
    tippZeigen(false);
    window.verfasserModus("aufgabe");
  }

  function loesungAbfragen(nutzlast) {
    kastenSchliessen();
    tippZeigen(false);
    abfrageFrage.textContent = nutzlast.frage;
    abfrageHinweis.textContent = nutzlast.hinweis || "";
    abfrage.hidden = false;
    jaKnopf.focus({ preventScroll: true });
    amEnde(true);
  }

  /* Das Ergebnis stimmt: Karte zeigen, Aufgabe als erledigt zeichnen, den
   * Verfasser auf die naechste Aufgabe stellen. Die Bestaetigung mit der
   * Warum-Frage holt der Aufrufer gleich danach; sie laeuft in diese Karte
   * ein und stellt den Verfasser dann auf die freiwillige Antwort. */
  function fertigZeigen(text) {
    kastenSchliessen();
    tippZeigen(false);
    if (abfrage) { abfrage.hidden = true; }
    if (stufenende) { stufenende.hidden = true; }
    if (fertigform) { fertigform.hidden = true; }
    if (neueAufgabeForm) { neueAufgabeForm.hidden = true; }
    if (erledigtmarke) { erledigtmarke.hidden = false; }
    if (aufgabenkarte) { aufgabenkarte.classList.add("ist-erledigt"); }
    fortschrittSetzen(0, null);
    if (fertigText) {
      fertigText.textContent = text;
      fertigText.hidden = !text;
    }
    if (fertigTutor) { fertigTutor.textContent = ""; }
    fertigkarteZeigen();
    window.verfasserModus("aufgabe");
    senden.disabled = false;
    if (fragen) { fragen.disabled = false; }
    ansage.textContent = "Das stimmt. " + text;
    amEnde(true);
    if (naechsteAufgabe) { naechsteAufgabe.focus({ preventScroll: true }); }
  }

  /* Holt einen Zug des Tutors. `erwartet` ist die Art, die die Seite schon
   * kennt, bevor der Server sie ansagt (die Bestaetigung nach einem
   * richtigen Ergebnis, der Nachsatz nach der Begruendung): Dann faengt
   * die richtige Karte an zu warten statt der Kasten. Was der Server mit
   * dem start-Ereignis sagt, gilt. */
  function stromStarten(adresse, koerper, beschriftung, erwartet) {
    aufraeumen();
    tippSperren();
    if (abfrage) { abfrage.hidden = true; }
    laufendeArt = erwartet || "";
    if (laufendeArt === ART_BESTAETIGUNG && fertigkarte) {
      bestaetigungBeginnen();
    } else {
      kastenZeigen(laufendeArt || ART_HILFE, 0, beschriftung || "wird geschrieben …");
    }
    amEnde(true);

    var gesammelt = "";

    return fetch(adresse, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert() },
      credentials: "same-origin",
      body: koerper || null
    }).then(function (antwort) {
      if (!antwort.ok || !antwort.body) { throw new Error("Antwort ohne Strom"); }
      var leser = antwort.body.getReader();
      var entschluessler = new TextDecoder("utf-8");
      var puffer = "";

      function weiter() {
        return leser.read().then(function (ergebnis) {
          if (ergebnis.done) { return; }
          puffer += entschluessler.decode(ergebnis.value, { stream: true });
          puffer = nachrichtenAus(puffer, function (name, nutzlast) {
            if (name === "beitrag") {
              // Der Server hat fuer das Kind festgehalten, dass es einen
              // Tipp gebraucht hat. Die Karte steht da, wie getippt.
              var offen = !kasten.hidden;
              kasten.hidden = true;
              versuchAnhaengen(nutzlast.text, "");
              kasten.hidden = !offen;
            } else if (name === "start") {
              laufendeArt = nutzlast.art || ART_HILFE;
              if (laufendeArt === ART_BESTAETIGUNG && fertigkarte) {
                bestaetigungBeginnen();
              } else {
                kastenZeigen(laufendeArt, nutzlast.stufe, nutzlast.bezeichnung);
              }
            } else if (name === "stueck") {
              gesammelt += nutzlast.text;
              if (laufendeArt === ART_BESTAETIGUNG && fertigTutor) {
                fertigTutor.textContent = gesammelt;
              } else {
                textFeld.textContent = gesammelt;
              }
              amEnde(false);
            } else if (name === "fertig") {
              abschliessen(nutzlast, gesammelt);
            } else if (name === "loesung_bestaetigen") {
              loesungAbfragen(nutzlast);
            } else if (name === "ausgeschoepft") {
              endeZeigen(nutzlast.meldung);
            } else if (name === "ende") {
              nichtsMehr();
            } else if (name === "fehler") {
              fehlerZeigen(nutzlast.meldung);
              tippZeigen(true);
            }
          });
          return weiter();
        });
      }
      return weiter();
    }).catch(function () {
      fehlerZeigen(
        "Die Verbindung hat nicht geklappt. Deine Aufgabe ist nicht verloren – " +
        "probier es gleich noch einmal."
      );
      tippZeigen(true);
    });
  }

  function stufeHolen(mitLoesung) {
    var koerper = null;
    if (mitLoesung) {
      koerper = new FormData();
      koerper.append("loesung", "ja");
    }
    return stromStarten(hilfeUrl, koerper);
  }

  function bestaetigungHolen() {
    return stromStarten(hilfeUrl, null, "", ART_BESTAETIGUNG);
  }

  function nachsatzHolen() {
    return stromStarten(hilfeUrl, null, "Dazu noch", ART_NACHSATZ);
  }

  function frageStreamen(frageId) {
    if (!nachfrageUrl) {
      window.location.reload();
      return null;
    }
    var adresse = nachfrageUrl.replace(/0\/$/, frageId + "/");
    return stromStarten(adresse, null, "Antwort auf deine Frage");
  }

  if (knopf) {
    knopf.addEventListener("click", function () { stufeHolen(false); });
  }

  if (jaKnopf) {
    jaKnopf.addEventListener("click", function () {
      abfrage.hidden = true;
      stufeHolen(true);
    });
  }
  if (neinKnopf) {
    neinKnopf.addEventListener("click", function () {
      abfrage.hidden = true;
      // Der Versuchsmodus bleibt: Der naechste Beitrag laeuft durch die
      // Diagnose, und der Tippknopf fuehrt wieder zur Loesungsabfrage.
      window.verfasserModus("antwort", {
        beschriftung: "Probier weiter",
        hilfe: "Schreib deinen nächsten Versuch auf. Die Lösung kannst du später immer noch holen."
      });
      tippZeigen(true);
      feldFokus();
      amEnde(true);
    });
  }

  /* "Naechste Aufgabe" auf der Karte "Das stimmt.": Der Verfasser nimmt die
   * naechste Aufgabe an, auch wenn die Warum-Frage noch offen ist. */
  if (naechsteAufgabe) {
    naechsteAufgabe.addEventListener("click", function (ereignis) {
      ereignis.preventDefault();
      tippZeigen(false);
      window.verfasserModus("aufgabe");
      var feld = document.getElementById("text");
      feld.focus();
      amEnde(true);
    });
  }

  /* Ein Formular fuer alles. Was passiert, haengt am Zustand und am Knopf. */
  form.addEventListener("submit", function (ereignis) {
    var modus = form.dataset.modus;

    // Aufgabe stellen und ergaenzen laufen gewoehnlich ab, mit Neuladen.
    // Der Verlauf aendert sich dabei so stark, dass ein neuer Aufbau der
    // Seite ehrlicher ist als ein Nachflicken im Dokument. Ausser bei einer
    // Frage: Die geht auch vor der ersten Hilfe ohne Neuladen.
    var inhalt = window.verfasserInhalt();
    var istFrage = inhalt.absicht === "frage" || modus === "nachfrage";
    if ((modus === "aufgabe" || modus === "ergaenzen") && !istFrage) { return; }

    ereignis.preventDefault();
    if (!inhalt.text && !inhalt.bild) {
      fehlerZeigen(istFrage
        ? "Schreib deine Frage auf, sprich sie ein oder fotografiere sie."
        : "Schreib, sprich oder fotografiere kurz, was du probiert hast.");
      return;
    }

    senden.disabled = true;
    if (fragen) { fragen.disabled = true; }
    aufraeumen();

    var adresse = istFrage ? form.dataset.urlNachfrage : form.dataset.urlAntwort;
    var daten = new FormData(form);
    if (istFrage) { daten.set("frage", inhalt.text); }

    fetch(adresse, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert(), "X-Antwort": "json" },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json().catch(function () { return { ok: antwort.ok }; });
    }).then(function (ergebnis) {
      senden.disabled = false;
      if (fragen) { fragen.disabled = false; }
      if (!ergebnis || !ergebnis.ok) {
        fehlerZeigen((ergebnis && ergebnis.meldung) || "Das hat nicht geklappt.");
        return;
      }
      if (istFrage) {
        frageAnhaengen(inhalt.text, inhalt.bild);
        window.verfasserLeeren();
        return frageStreamen(ergebnis.id || ergebnis.frage);
      }
      if (ergebnis.nachsatz) {
        // Die Begruendung auf die Warum-Frage. Sie wird nicht beurteilt;
        // der Tutor antwortet mit einem Nachsatz, danach kommt nichts mehr.
        begruendungAnhaengen(inhalt.text, inhalt.bild);
        window.verfasserLeeren();
        window.verfasserModus("aufgabe");
        return nachsatzHolen();
      }
      versuchAnhaengen(inhalt.text, inhalt.bild);
      window.verfasserLeeren();
      if (ergebnis.fertig) {
        // Das Ergebnis stimmt: die Karte sofort, die Bestaetigung mit der
        // Warum-Frage gleich hinterher, in dieselbe Karte.
        fertigZeigen(inhalt.text);
        return bestaetigungHolen();
      }
      // Der naechste Zug kommt von selbst, ohne weiteren Knopfdruck.
      return stufeHolen(false);
    }).catch(function () {
      senden.disabled = false;
      if (fragen) { fragen.disabled = false; }
      fehlerZeigen("Das ist nicht angekommen. Probier es noch einmal.");
    });
  });

  /* Beim Laden: Die Aufgabe ist fertig, die Bestaetigung steht noch aus
   * (etwa nach einem Neuladen zwischen Ergebnis und Bestaetigung). Sie wird
   * geholt wie mit dem Tippknopf; der Server weiss, was dran ist. */
  if (daten.zugArt === ART_BESTAETIGUNG && daten.abgeschlossen && hilfeUrl) {
    bestaetigungHolen();
  }
})();
