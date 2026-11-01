/* Der Arbeitsplatz als Chat, und die Steuerung des einen Eingabebereichs.
 *
 * Ein Feld, zwei Knoepfe: "Das ist mein Versuch" und "Ich habe eine Frage".
 * Das Kind sagt selbst, was sein Beitrag ist; die Anwendung raet nicht mehr
 * (Benchmark 19.10.2026, Befund 1). Was sich mit dem Zustand aendert, ist
 * die Beschriftung, der Hinweis und wohin abgeschickt wird. Foto und
 * Sprache sind immer daneben.
 */
(function () {
  "use strict";

  var ende = document.getElementById("chatende");
  var form = document.getElementById("verfasser-form");

  /* Scrollt so, dass die neueste Karte ueber dem Verfasser steht. Der
   * Verfasser bleibt unten sichtbar; gescrollt wird deshalb er selbst ans
   * untere Ende, und die letzte Karte landet darueber. */
  function nachUntenScrollen(sanft) {
    var ziel = document.getElementById("verfasser-form") || ende;
    if (!ziel) { return; }
    try {
      ziel.scrollIntoView({ block: "end", behavior: sanft ? "smooth" : "auto" });
    } catch (e) {
      ziel.scrollIntoView(false);
    }
  }

  window.addEventListener("load", function () { nachUntenScrollen(false); });
  nachUntenScrollen(false);
  window.zumChatende = nachUntenScrollen;

  if (!form) { return; }

  var feld = document.getElementById("text");
  var beschriftung = document.getElementById("verfasser-label");
  var hilfe = document.getElementById("verfasser-hilfe");
  var senden = document.getElementById("senden");
  var fragen = document.getElementById("fragen");
  var absicht = document.getElementById("absichtfeld");
  var herkunft = document.getElementById("herkunftfeld");
  var bildfeld = document.getElementById("bildfeld");
  var vorschau = document.getElementById("fotovorschau");
  var fotostand = document.getElementById("fotostand");

  var KNOPF_VERSUCH = form.dataset.knopfVersuch || "Das ist mein Versuch";
  var KNOPF_FRAGE = form.dataset.knopfFrage || "Ich habe eine Frage";

  /* Die Vorlage "ergaenzen" kommt im Ablauf seit 30.10.2026 nicht mehr vor
   * (vor der ersten Hilfe steht der Verfasser im Modus "antwort" mit der
   * Beschriftung "Dein Anfang"); sie bleibt fuer aeltere Seiten stehen. */
  var VORLAGEN = {
    aufgabe: {
      url: form.dataset.urlAufgabe,
      beschriftung: "Deine nächste Aufgabe",
      hilfe: "",
      platzhalter: "Abschreiben, fotografieren oder sprechen …",
      knopf: "Abschicken",
      zweiter: ""
    },
    ergaenzen: {
      url: form.dataset.urlErgaenzen,
      beschriftung: "Noch etwas dazu?",
      hilfe: "Freiwillig. Du kannst auch gleich einen Tipp holen.",
      platzhalter: "Noch etwas dazusagen …",
      knopf: "Dazusagen",
      zweiter: KNOPF_FRAGE
    },
    antwort: {
      url: form.dataset.urlAntwort,
      beschriftung: "Jetzt bist du dran",
      hilfe: "",
      platzhalter: "Schreib, was du probiert hast. Auch „weiß nicht“ ist in Ordnung.",
      knopf: KNOPF_VERSUCH,
      zweiter: KNOPF_FRAGE
    },
    nachfrage: {
      url: form.dataset.urlNachfrage,
      beschriftung: "Noch eine Frage?",
      hilfe: "",
      platzhalter: "Deine Frage …",
      knopf: KNOPF_FRAGE,
      zweiter: ""
    }
  };

  /* Setzt den Eingabebereich auf einen Zustand. Der Text im Feld bleibt
   * stehen: Wer gerade etwas getippt hat, soll es nicht verlieren, nur weil
   * inzwischen eine Hilfe angekommen ist. `zusatz` darf Beschriftung,
   * Hinweis, Platzhalter, Knopf und zweiten Knopf ueberschreiben; ein
   * leerer zweiter Knopf (zweiter: "") blendet ihn aus - so steht nach der
   * Bestaetigung nur "Antworten" da. */
  window.verfasserModus = function (modus, zusatz) {
    var vorlage = VORLAGEN[modus];
    if (!vorlage) { return; }
    zusatz = zusatz || {};
    form.dataset.modus = modus;
    form.action = vorlage.url;
    beschriftung.textContent = zusatz.beschriftung || vorlage.beschriftung;
    senden.textContent = zusatz.knopf || vorlage.knopf;
    feld.placeholder = zusatz.platzhalter || vorlage.platzhalter;
    var text = zusatz.hilfe || vorlage.hilfe;
    hilfe.textContent = text;
    hilfe.hidden = !text;
    var zweiter = Object.prototype.hasOwnProperty.call(zusatz, "zweiter")
      ? zusatz.zweiter : vorlage.zweiter;
    if (fragen) {
      fragen.textContent = zweiter || KNOPF_FRAGE;
      fragen.hidden = !zweiter;
    }
    if (absicht) { absicht.value = "versuch"; }
  };

  window.verfasserLeeren = function () {
    feld.value = "";
    if (bildfeld) { bildfeld.value = ""; }
    if (herkunft) { herkunft.value = "tippen"; }
    if (absicht) { absicht.value = "versuch"; }
    if (vorschau) { vorschau.hidden = true; vorschau.removeAttribute("src"); }
    if (fotostand) { fotostand.hidden = true; fotostand.textContent = ""; }
  };

  window.verfasserInhalt = function () {
    return {
      text: feld.value.trim(),
      bild: bildfeld ? bildfeld.value : "",
      herkunft: herkunft ? herkunft.value : "tippen",
      absicht: absicht ? absicht.value : "versuch"
    };
  };

  /* Welcher Knopf hat abgeschickt? Das versteckte Feld traegt es, damit
   * FormData es mitnimmt; der Knopf selbst zaehlt nur im Weg ohne Skript.
   * In der Fangphase, damit hilfe.js den Wert schon vorfindet. */
  form.addEventListener("submit", function (ereignis) {
    var knopf = ereignis.submitter;
    if (absicht) {
      absicht.value = (knopf && knopf.value === "frage") ? "frage" : "versuch";
    }
  }, true);

  /* Enter schickt ab, Umschalt+Enter macht eine neue Zeile. Am Handy gibt es
   * den Knopf; am PC soll niemand die Maus suchen muessen. */
  feld.addEventListener("keydown", function (ereignis) {
    if (ereignis.key === "Enter" && !ereignis.shiftKey && !ereignis.isComposing) {
      ereignis.preventDefault();
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(senden);
      } else {
        senden.click();
      }
    }
  });

  // "Neue Aufgabe" ist ein Formular: Es schliesst die laufende Aufgabe
  // wirklich ab, statt nur die Beschriftung umzuschalten. Die Seite kommt
  // danach im Zustand "neue Aufgabe" zurueck.
})();
