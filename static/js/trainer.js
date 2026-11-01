/* Der Trainer fuer alles: ein Gespraech in kleinen Schritten.
 *
 * Anders als die Aufgabenhilfe haelt der Trainer nichts zurueck. Er erklaert,
 * fragt nach jedem Schritt genau eines, prueft am Ende und erklaert bei einem
 * Fehler noch einmal anders. Diese Seite zeigt das Gespraech, schickt die
 * Antwort ab und liest vor, was der Trainer sagt.
 *
 * Ein Formular, eine Adresse, ein Zustand. Der Zustand liegt im Server; hier
 * steht nur, wie das Eingabefeld dazu beschriftet ist.
 *
 * Ohne dieses Skript bleibt die Seite bedienbar: Das Formular ist ein
 * gewoehnliches POST-Formular, und die Ansicht liefert die Seite neu. Darum
 * wird hier nichts umgebaut, was das Formular zum Arbeiten braucht.
 *
 * Kein Aufbauwerkzeug, keine Bibliothek, nichts aus dem Netz.
 */
(function () {
  "use strict";

  var form = document.getElementById("trainer-form");
  var verlauf = document.getElementById("trainer-verlauf");
  var feld = document.getElementById("text");
  var senden = document.getElementById("senden");
  var beschriftung = document.getElementById("trainer-label");
  var feldhilfe = document.getElementById("trainer-hilfe");
  var stand = document.getElementById("trainer-stand");
  var fortschritt = document.getElementById("trainer-fortschritt");
  var themafeld = document.getElementById("trainer-thema");
  var denkt = document.getElementById("trainer-denkt");
  var fehlerfeld = document.getElementById("trainer-fehler");
  var fertigfeld = document.getElementById("trainer-fertig");
  var ansage = document.getElementById("trainer-ansage");
  var vorlesenKnopf = document.getElementById("vorlesen");
  var werkzeuge = document.getElementById("trainer-werkzeuge");

  /* --- Kleinigkeiten, die mehrere Teile brauchen ------------------------- */

  function ruhigGewuenscht() {
    return !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* Springt zum Eingabefeld, nicht ans Seitenende: Dort steht die Frage, auf
   * die geantwortet wird, direkt darueber. Bei prefers-reduced-motion wird
   * gesprungen statt geglitten -- sanftes Scrollen ist auch Bewegung. */
  function zumEingabefeld(sanft) {
    // Am Ende des Laufs ist das Formular weg. Dann ist der letzte Zug das
    // Ziel, sonst wuerde auf ein verborgenes Element gescrollt.
    var ziel = (form && !form.hidden) ? form : null;
    if (!ziel && verlauf) { ziel = verlauf.lastElementChild; }
    if (!ziel) { ziel = form || feld; }
    if (!ziel) { return; }
    try {
      ziel.scrollIntoView({
        block: "center",
        behavior: (sanft && !ruhigGewuenscht()) ? "smooth" : "auto"
      });
    } catch (e) {
      ziel.scrollIntoView(false);
    }
  }

  /* sprache.js ruft das, nachdem der gesprochene Text im Feld steht. Der
   * Name stammt aus dem Chat; er bleibt, damit sprache.js unangetastet
   * bleibt. */
  window.zumChatende = zumEingabefeld;

  function csrfWert() {
    var treffer = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[2]) : "";
  }

  /* Erst leeren, dann setzen. Steht derselbe Satz noch im Bereich, meldet ein
   * Vorlesewerkzeug nichts, weil sich nichts geaendert hat. */
  function ansagen(text) {
    if (!ansage || !text) { return; }
    ansage.textContent = "";
    window.setTimeout(function () { ansage.textContent = text; }, 60);
  }

  /* --- Sprachausgabe ----------------------------------------------------- */

  var SPEICHER = "modlearn-trainer-vorlesen";
  var LESEGRENZE = 180;   // Zeichen je Aeusserung, siehe inStuecke()
  var LESETEMPO = 0.95;   // etwas langsamer als normal, fuer Mitdenken

  var stimme = null;
  var vorlesenAn = false;
  var wunschGeklaert = false;   // true, sobald der gemerkte Wunsch gilt

  function wunschLesen() {
    try {
      return window.localStorage.getItem(SPEICHER) === "ja";
    } catch (e) {
      // Privater Modus oder gesperrte Seitendaten. Dann eben nicht gemerkt.
      return false;
    }
  }

  function wunschMerken(an) {
    try {
      window.localStorage.setItem(SPEICHER, an ? "ja" : "nein");
    } catch (e) { /* siehe wunschLesen */ }
  }

  /* Eine deutsche Systemstimme. Oesterreichisch zuerst, danach eine Stimme,
   * die im Geraet selbst rechnet: Die schickt die Saetze nirgendwohin, und das
   * ist genau das Versprechen dieser Anwendung. */
  function deutscheStimme() {
    if (!window.speechSynthesis || !window.speechSynthesis.getVoices) { return null; }
    var liste = window.speechSynthesis.getVoices() || [];
    var gefunden = null;
    for (var i = 0; i < liste.length; i++) {
      var kandidat = liste[i];
      var sprache = String(kandidat.lang || "").toLowerCase().replace("_", "-");
      if (sprache.indexOf("de") !== 0) { continue; }
      if (sprache === "de-at") { return kandidat; }
      if (!gefunden) {
        gefunden = kandidat;
      } else if (kandidat.localService && !gefunden.localService) {
        gefunden = kandidat;
      }
    }
    return gefunden;
  }

  function knopfZeichnen() {
    if (!vorlesenKnopf) { return; }
    vorlesenKnopf.hidden = !stimme;
    vorlesenKnopf.setAttribute("aria-pressed", vorlesenAn ? "true" : "false");
    vorlesenKnopf.classList.toggle("ist-an", vorlesenAn);
    var wort = vorlesenKnopf.querySelector(".werkzeug-wort");
    if (wort) { wort.textContent = vorlesenAn ? "Vorlesen an" : "Vorlesen"; }
  }

  function vorlesenAbbrechen() {
    if (!window.speechSynthesis) { return; }
    try { window.speechSynthesis.cancel(); } catch (e) { /* nichts zu stoppen */ }
  }

  /* Lange Texte werden in Stuecke zerlegt und der Reihe nach gesprochen.
   * Manche Browser schneiden eine einzelne lange Aeusserung nach wenigen
   * Sekunden ab; kurze Stuecke hintereinander kommen zuverlaessig durch.
   * Geschnitten wird an einem Satzende, sonst an einem Leerzeichen -- mitten
   * im Wort abzubrechen klingt wie ein Fehler. */
  function inStuecke(text) {
    var rest = String(text).replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
    var satzende = ".!?;:";
    var stuecke = [];
    while (rest.length > LESEGRENZE) {
      var schnitt = -1;
      for (var i = LESEGRENZE - 1; i > 40; i--) {
        if (satzende.indexOf(rest.charAt(i)) >= 0) { schnitt = i + 1; break; }
      }
      if (schnitt < 0) { schnitt = rest.lastIndexOf(" ", LESEGRENZE); }
      if (schnitt <= 0) { schnitt = LESEGRENZE; }
      stuecke.push(rest.slice(0, schnitt).replace(/^\s+|\s+$/g, ""));
      rest = rest.slice(schnitt).replace(/^\s+/, "");
    }
    if (rest) { stuecke.push(rest); }
    return stuecke;
  }

  /* Vorgelesen wird nur, was der Trainer sagt. Die eigene Antwort kennt man
   * schon, und sie noch einmal zu hoeren haelt bloss auf. Die eine Frage
   * gehoert dazu: Wer sich vorlesen laesst, braucht genau sie, um antworten
   * zu koennen. */
  function vorlesen(text, frage) {
    vorlesenAbbrechen();
    if (!vorlesenAn || !stimme || !window.SpeechSynthesisUtterance) { return; }
    var satz = String(text || "");
    if (frage) { satz = satz ? satz + " " + frage : String(frage); }
    if (!satz.replace(/\s+/g, "")) { return; }
    var stuecke = inStuecke(satz);
    for (var i = 0; i < stuecke.length; i++) {
      try {
        var rede = new window.SpeechSynthesisUtterance(stuecke[i]);
        rede.voice = stimme;
        rede.lang = stimme.lang || "de-DE";
        rede.rate = LESETEMPO;
        window.speechSynthesis.speak(rede);
      } catch (e) {
        return;   // Kein Grund, es mit den restlichen Stuecken zu versuchen.
      }
    }
  }

  /* Der letzte Zug des Trainers, aus dem Dokument gelesen. So braucht das
   * Vorlesen keinen zweiten Speicher neben der Seite, und es funktioniert
   * auch nach einem gewoehnlichen Neuladen. */
  function letzterTrainerzug() {
    if (!verlauf) { return null; }
    var liste = verlauf.querySelectorAll("li.zug-trainer");
    if (!liste.length) { return null; }
    var zug = liste[liste.length - 1];
    var text = zug.querySelector(".zug-text");
    var frage = zug.querySelector(".zug-frage-text");
    return {
      text: text ? text.textContent : "",
      frage: frage ? frage.textContent : ""
    };
  }

  /* Die Stimmenliste kommt in vielen Browsern erst nach dem Laden, manchmal
   * erst beim zweiten Anlauf. Darum wird hier mehrfach nachgesehen; ohne
   * deutsche Stimme bleibt der Umschalter verborgen und der Text genuegt. */
  function stimmeSuchen() {
    stimme = deutscheStimme();
    if (stimme && !wunschGeklaert) {
      wunschGeklaert = true;
      vorlesenAn = wunschLesen();
      /* Wer das Vorlesen eingeschaltet gelassen hat, will beim Weiterlernen
       * nicht erst zweimal tippen muessen, um den offenen Schritt zu hoeren.
       * Blockt der Browser das Sprechen ohne Handbewegung, passiert einfach
       * nichts, und der Umschalter hilft weiter. */
      if (vorlesenAn) {
        var letzter = letzterTrainerzug();
        if (letzter) { vorlesen(letzter.text, letzter.frage); }
      }
    }
    if (!stimme) { vorlesenAn = false; }
    knopfZeichnen();
  }

  if (window.speechSynthesis && window.SpeechSynthesisUtterance) {
    stimmeSuchen();
    if (!stimme) {
      if (typeof window.speechSynthesis.addEventListener === "function") {
        window.speechSynthesis.addEventListener("voiceschanged", stimmeSuchen);
      } else {
        window.speechSynthesis.onvoiceschanged = stimmeSuchen;
      }
    }
  } else if (vorlesenKnopf) {
    vorlesenKnopf.hidden = true;
  }

  if (vorlesenKnopf) {
    vorlesenKnopf.addEventListener("click", function () {
      vorlesenAn = !vorlesenAn;
      wunschMerken(vorlesenAn);
      knopfZeichnen();
      if (!vorlesenAn) {
        vorlesenAbbrechen();
        ansagen("Vorlesen ist aus.");
        return;
      }
      /* Der Klick ist die Handbewegung, die manche Browser fuer das erste
       * Sprechen verlangen. Also wird gleich der offene Schritt gelesen: So
       * hoert man sofort, worum es geht, und nicht erst beim naechsten Mal. */
      var letzter = letzterTrainerzug();
      if (letzter) { vorlesen(letzter.text, letzter.frage); }
      ansagen("Vorlesen ist an.");
    });
  }

  /* Der Sprechen-Knopf startet verborgen: Auf einem Geraet ohne Mikrofonzugang
   * -- oder ohne JavaScript -- waere er ein Knopf, der nichts tut. sprache.js
   * bleibt dabei unangetastet, es braucht nur diesen einen Knopf. */
  if (werkzeuge && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    werkzeuge.hidden = false;
  }

  if (!form) { return; }

  /* --- Wie das Eingabefeld zum Zustand passt ----------------------------- */

  /* Dieselben Worte wie in trainer.html. Die Seite darf nach dem ersten Zug
   * nicht anders klingen als beim Laden; wer hier etwas aendert, aendert es
   * dort mit. */
  var VORLAGEN = {
    thema: {
      beschriftung: "Was möchtest du lernen?",
      hilfe: "Zum Beispiel: „Ich möchte etwas zur Maßumwandlung und zu Längenmaßen lernen.“",
      platzhalter: "Ich möchte etwas über … lernen",
      knopf: "Los geht's"
    },
    bestaetigen: {
      beschriftung: "Passt das so?",
      hilfe: "",
      platzhalter: "Ja, das passt …",
      knopf: "Antworten"
    },
    einfuehrung: {
      beschriftung: "Deine Antwort",
      hilfe: "",
      platzhalter: "Schreib deine Antwort …",
      knopf: "Antworten"
    },
    lernschritt: {
      beschriftung: "Deine Antwort",
      hilfe: "",
      platzhalter: "Schreib deine Antwort …",
      knopf: "Antworten"
    },
    pruefung: {
      beschriftung: "Deine Lösung",
      hilfe: "",
      platzhalter: "Schreib, wie du gerechnet hast …",
      knopf: "Antworten"
    },
    abschluss: {
      beschriftung: "Möchtest du noch etwas fragen?",
      hilfe: "",
      platzhalter: "Deine Frage …",
      knopf: "Fragen"
    }
  };

  var URTEILE = {
    verstanden: "richtig",
    teilweise: "fast",
    nicht: "noch nicht"
  };

  /* Kommt ein Zustand an, den diese Seite noch nicht kennt, gilt die neutrale
   * Beschriftung. Stehen zu lassen, was vom vorigen Zustand noch dasteht,
   * waere schlimmer: Dann fragt das Feld nach einer Loesung, obwohl der
   * Trainer etwas anderes wissen will. */
  function zustandSetzen(name) {
    var vorlage = VORLAGEN[name] || VORLAGEN.lernschritt;
    form.setAttribute("data-zustand", name || "");
    if (beschriftung) { beschriftung.textContent = vorlage.beschriftung; }
    if (feldhilfe) {
      feldhilfe.textContent = vorlage.hilfe;
      feldhilfe.hidden = !vorlage.hilfe;
    }
    if (feld) { feld.placeholder = vorlage.platzhalter; }
    if (senden) { senden.textContent = vorlage.knopf; }
  }

  /* --- Fehler und Fertigmeldung ------------------------------------------ */

  function fehlerZeigen(meldung) {
    if (!fehlerfeld) { return; }
    fehlerfeld.textContent = meldung;
    fehlerfeld.hidden = false;
  }

  function fehlerVerbergen() {
    if (!fehlerfeld) { return; }
    fehlerfeld.hidden = true;
    fehlerfeld.textContent = "";
  }

  /* Am Ende geht das Feld weg und der Schlusssatz kommt. Die Ansicht nimmt
   * nach dem letzten Zug keinen weiteren mehr an; ein Feld, das dann noch
   * dasteht, antwortet auf jeden Satz mit einer Fehlermeldung. */
  function fertigSetzen(fertig) {
    if (fertigfeld) { fertigfeld.hidden = !fertig; }
    form.hidden = !!fertig;
  }

  /* --- Der ruhige Wartezustand ------------------------------------------- */

  function denktZeigen(an) {
    if (denkt) { denkt.hidden = !an; }
    if (senden) { senden.disabled = !!an; }
    if (verlauf) { verlauf.setAttribute("aria-busy", an ? "true" : "false"); }
  }

  /* --- Der Verlauf ------------------------------------------------------- */

  function zugAnhaengen(rolle, text, frage, urteil) {
    if (!verlauf) { return null; }

    var eintrag = document.createElement("li");
    eintrag.className = "zug zug-" + rolle;

    var kopf = document.createElement("p");
    kopf.className = "zug-kopf";
    var wer = document.createElement("span");
    wer.className = "zug-wer";
    wer.textContent = (rolle === "trainer") ? "Trainer" : "Du";
    kopf.appendChild(wer);
    if (urteil && URTEILE[urteil]) {
      var marke = document.createElement("span");
      marke.className = "urteil urteil-" + urteil;
      marke.textContent = URTEILE[urteil];
      kopf.appendChild(marke);
    }
    eintrag.appendChild(kopf);

    // textContent, nicht innerHTML: Was aus dem Netz kommt, wird hier nie
    // als Auszeichnung gelesen.
    var rumpf = document.createElement("div");
    rumpf.className = "zug-text";
    rumpf.textContent = text || "";
    eintrag.appendChild(rumpf);

    if (frage) {
      var kasten = document.createElement("p");
      kasten.className = "zug-frage";
      var fragemarke = document.createElement("span");
      fragemarke.className = "zug-frage-marke";
      fragemarke.textContent = "Antworte darauf";
      var fragetext = document.createElement("span");
      fragetext.className = "zug-frage-text";
      fragetext.textContent = frage;
      kasten.appendChild(fragemarke);
      kasten.appendChild(fragetext);
      eintrag.appendChild(kasten);
    }

    verlauf.appendChild(eintrag);
    return eintrag;
  }

  /* Gleicher Satzbau wie in trainer.html. */
  function fortschrittSchreiben(werte) {
    if (!fortschritt || !werte) { return; }
    var gestellt = werte.aufgaben_gestellt || 0;
    var satz = "Schritt " + (werte.schritt || 1) + " · ";
    satz += gestellt
      ? (werte.aufgaben_richtig || 0) + " von " + gestellt + " Aufgaben richtig"
      : "noch keine Aufgabe zum Prüfen";
    fortschritt.textContent = satz;
  }

  /* --- Absenden ---------------------------------------------------------- */

  function zugUebernehmen(ergebnis, eigenerText) {
    var vorher = form.getAttribute("data-zustand");
    var zustand = ergebnis.zustand || vorher;

    if (stand && ergebnis.zustand_text) { stand.textContent = ergebnis.zustand_text; }

    /* Das Thema steht nicht in der Antwort, und der erste eigene Satz ist
     * genau der Wunsch. Ohne diese Zeile blieb die Kopfzeile bis zum
     * naechsten Laden leer. */
    if (themafeld && vorher === "thema" && zustand !== "thema" && eigenerText) {
      themafeld.textContent = "Dein Thema: " + eigenerText;
      themafeld.hidden = false;
    }

    zugAnhaengen("trainer", ergebnis.trainer || "", ergebnis.frage || "",
                 ergebnis.urteil || "");
    fortschrittSchreiben(ergebnis.fortschritt);
    zustandSetzen(zustand);
    fertigSetzen(!!ergebnis.fertig);

    var gesagt = ergebnis.zustand_text ? ergebnis.zustand_text + " " : "";
    gesagt += (ergebnis.trainer || "");
    if (ergebnis.frage) { gesagt += " " + ergebnis.frage; }
    ansagen(gesagt);

    vorlesen(ergebnis.trainer || "", ergebnis.frage || "");

    /* Nur scrollen, nicht in das Feld springen: Auf dem Handy schiebt die
     * Bildschirmtastatur sonst genau die Frage aus dem Bild, die gerade
     * beantwortet werden soll. Der Fokus bleibt auf dem Knopf daneben. */
    zumEingabefeld(true);
  }

  function absenden(text) {
    // Vor dem Leeren einsammeln: FormData liest die Felder, wie sie stehen.
    var daten = new window.FormData(form);

    fehlerVerbergen();
    var eigener = zugAnhaengen("lernend", text, "", "");
    if (feld) { feld.value = ""; }
    var herkunft = document.getElementById("herkunftfeld");
    if (herkunft) { herkunft.value = "tippen"; }
    denktZeigen(true);
    ansagen("Der Trainer denkt nach.");
    zumEingabefeld(true);

    /* Nichts ist verloren: Kommt die Antwort nicht an, wandert der eigene
     * Satz zurueck ins Feld und der Zug aus dem Verlauf. Alles andere waere
     * eine Behauptung, die die Seite nicht halten kann. */
    function zuruecknehmen(meldung) {
      denktZeigen(false);
      if (eigener && eigener.parentNode) { eigener.parentNode.removeChild(eigener); }
      if (feld && !feld.value) { feld.value = text; }
      fehlerZeigen(meldung);
      ansagen(meldung);
      if (feld) {
        try { feld.focus(); } catch (e) { /* aeltere Browser */ }
      }
    }

    window.fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert(), "X-Antwort": "json" },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json().catch(function () { return null; });
    }).then(function (ergebnis) {
      if (!ergebnis || !ergebnis.ok) {
        zuruecknehmen((ergebnis && ergebnis.meldung) ||
          "Das hat nicht geklappt. Probier es noch einmal.");
        return;
      }
      denktZeigen(false);
      zugUebernehmen(ergebnis, text);
    }).catch(function () {
      zuruecknehmen("Die Verbindung hat nicht geklappt. Dein Satz steht wieder " +
        "im Feld – probier es gleich noch einmal.");
    });
  }

  form.addEventListener("submit", function (ereignis) {
    /* Ohne fetch bleibt es ein gewoehnliches Formular. Erst hier wird
     * abgebrochen, nicht vorher: Sonst stuende die Seite auf einem Geraet ohne
     * fetch mit einem Knopf da, der nichts mehr tut. */
    if (!window.fetch || !window.FormData) { return; }

    var text = feld ? feld.value.replace(/^\s+|\s+$/g, "") : "";
    ereignis.preventDefault();

    if (!text) {
      fehlerZeigen(form.getAttribute("data-zustand") === "thema"
        ? "Schreib auf, was du lernen möchtest, oder sprich es ein."
        : "Schreib deine Antwort auf oder sprich sie ein.");
      if (feld) {
        try { feld.focus(); } catch (e) { /* aeltere Browser */ }
      }
      return;
    }

    absenden(text);
  });

  // Beim Laden steht der offene Schritt unmittelbar ueber dem Feld.
  zumEingabefeld(false);
  window.addEventListener("load", function () { zumEingabefeld(false); });
})();
