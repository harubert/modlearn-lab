/* Der Safe Chat: ein offenes Gespraech am Spark, auf Knopfdruck nach draussen.
 *
 * Zwei Aufgaben, und beide laufen auch ohne die andere:
 *
 * 1. Der Knopf "Alles aufklappen" oeffnet jedes Protokoll (details mit
 *    data-protokoll) auf einmal und merkt sich den Zustand. Neu angehaengte
 *    Protokolle folgen ihm. Im Verlauf der Lehrperson wird das Teilstueck
 *    alle fuenf Sekunden per htmx ersetzt; darum merkt sich das Skript vor
 *    jedem Tausch, welche Protokolle offen waren, und oeffnet sie danach
 *    wieder. Der Knopf liegt mit im getauschten Bereich und wird deshalb
 *    ueber das Dokument bedient, nicht ueber eine festgehaltene Referenz.
 *
 * 2. Das Formular des Kindes: Text und Weg (spark oder aussen) per fetch
 *    abschicken, waehrenddessen beide Knoepfe aus und eine Statuszeile,
 *    dann die zwei neuen Zuege unten anhaengen. Auf der Seite der
 *    Lehrperson gibt es kein Formular; dann endet das Skript nach Teil 1.
 *
 * Ohne dieses Skript bleibt die Seite bedienbar: Das Formular ist ein
 * gewoehnliches POST-Formular. Kein Aufbauwerkzeug, keine Bibliothek,
 * nichts aus dem Netz.
 */
(function () {
  "use strict";

  var liste = document.getElementById("chatzuege");
  var form = document.getElementById("safechat-form");
  var feld = document.getElementById("text");
  var status = document.getElementById("safechat-status");

  /* --- Kleinigkeiten ----------------------------------------------------- */

  function ruhigGewuenscht() {
    return !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* Von einem Element aufwaerts bis zu dem mit dieser Kennung, oder null.
   * Ein eigener Gang statt closest(), damit auch aeltere Browser mitkommen. */
  function hinaufBisKennung(element, kennung) {
    var knoten = element;
    while (knoten && knoten !== document) {
      if (knoten.id === kennung) { return knoten; }
      knoten = knoten.parentNode;
    }
    return null;
  }

  function hinaufBisKnopf(element, wurzel) {
    var knoten = element;
    while (knoten && knoten !== wurzel && knoten !== document) {
      if (knoten.tagName === "BUTTON" && knoten.type === "submit") { return knoten; }
      knoten = knoten.parentNode;
    }
    return null;
  }

  /* --- Teil 1: Alles aufklappen ------------------------------------------ */

  var alleOffen = false;       // der gemerkte Zustand des Knopfes
  var offeneKennungen = [];    // vor einem htmx-Tausch: welche Protokolle offen waren

  function protokolle(wurzel) {
    return (wurzel || document).querySelectorAll("details[data-protokoll]");
  }

  /* Der Knopf wird jedes Mal neu gesucht: Im Verlauf der Lehrperson ist er
   * nach jedem Tausch ein anderes Element. */
  function knopfZeichnen() {
    var knopf = document.getElementById("protokoll-alle");
    if (!knopf) { return; }
    knopf.hidden = protokolle().length === 0;
    knopf.textContent = alleOffen ? "Alles zuklappen" : "Alles aufklappen";
    knopf.setAttribute("aria-pressed", alleOffen ? "true" : "false");
  }

  function alleSetzen(offen, wurzel) {
    var alle = protokolle(wurzel);
    for (var i = 0; i < alle.length; i++) { alle[i].open = offen; }
  }

  document.addEventListener("click", function (ereignis) {
    if (!hinaufBisKennung(ereignis.target, "protokoll-alle")) { return; }
    alleOffen = !alleOffen;
    alleSetzen(alleOffen);
    knopfZeichnen();
  });

  /* htmx (Verlauf der Lehrperson): Vor dem Tausch merken, was offen ist;
   * danach wieder oeffnen. Ohne das klappte alle fuenf Sekunden alles zu. */
  document.addEventListener("htmx:beforeSwap", function () {
    offeneKennungen = [];
    var alle = protokolle();
    for (var i = 0; i < alle.length; i++) {
      if (alle[i].open && alle[i].id) { offeneKennungen.push(alle[i].id); }
    }
  });

  document.addEventListener("htmx:afterSwap", function (ereignis) {
    var ziel = (ereignis.detail && ereignis.detail.target) || ereignis.target;
    if (alleOffen) {
      alleSetzen(true, ziel);
    } else {
      for (var i = 0; i < offeneKennungen.length; i++) {
        var einzelnes = document.getElementById(offeneKennungen[i]);
        if (einzelnes) { einzelnes.open = true; }
      }
    }
    knopfZeichnen();
  });

  knopfZeichnen();

  /* --- Teil 2: das Formular des Kindes ----------------------------------- */

  if (!form || !liste || !feld) { return; }

  var fragenKnopf = document.getElementById("fragen");
  var draussenKnopf = document.getElementById("draussen");
  var gedrueckt = null;   // der zuletzt geklickte Absendeknopf, falls submitter fehlt

  function csrfWert() {
    var eingabe = form.querySelector("input[name='csrfmiddlewaretoken']");
    return eingabe ? eingabe.value : "";
  }

  /* Erst leeren, dann setzen: Steht derselbe Satz noch da, meldet ein
   * Vorlesewerkzeug nichts, weil sich nichts geaendert hat. */
  function statusSetzen(text, istFehler, wartet) {
    if (!status) { return; }
    status.textContent = "";
    status.classList.toggle("ist-fehler", !!istFehler);
    status.classList.toggle("ist-wartend", !!wartet);
    if (text) {
      window.setTimeout(function () { status.textContent = text; }, 40);
    }
  }

  function wartenSetzen(an) {
    if (fragenKnopf) { fragenKnopf.disabled = !!an; }
    if (draussenKnopf) { draussenKnopf.disabled = !!an; }
    liste.setAttribute("aria-busy", an ? "true" : "false");
  }

  /* Zum ersten der neuen Zuege, also zur eigenen Frage: Darunter beginnt die
   * Antwort, und bei einer langen Antwort ist der Anfang das Richtige. */
  function zumZug(element) {
    if (!element) { return; }
    try {
      element.scrollIntoView({
        block: "start",
        behavior: ruhigGewuenscht() ? "auto" : "smooth"
      });
    } catch (e) {
      element.scrollIntoView(true);
    }
  }

  function fokusZurueck() {
    try { feld.focus({ preventScroll: true }); } catch (e) {
      try { feld.focus(); } catch (e2) { /* aeltere Browser */ }
    }
  }

  function abschicken(weg) {
    var text = feld.value.replace(/^\s+|\s+$/g, "");
    if (!text) {
      statusSetzen("Schreib zuerst, was du wissen willst.", true, false);
      fokusZurueck();
      return;
    }
    if (weg !== "aussen") { weg = "spark"; }

    var daten = new window.FormData();
    daten.append("csrfmiddlewaretoken", csrfWert());
    daten.append("text", text);
    daten.append("weg", weg);

    statusSetzen(weg === "aussen"
      ? "Geht durch den Filter nach draußen …"
      : "Der Spark denkt nach …", false, true);
    wartenSetzen(true);
    var vorher = liste.children.length;

    window.fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert() },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json().catch(function () { return null; });
    }).then(function (ergebnis) {
      wartenSetzen(false);
      if (!ergebnis || !ergebnis.ok || !ergebnis.html) {
        /* Der Text bleibt im Feld: Nichts ist verloren. */
        statusSetzen((ergebnis && ergebnis.grund) ||
          "Das hat nicht geklappt. Probier es noch einmal.", true, false);
        fokusZurueck();
        return;
      }
      statusSetzen("", false, false);
      // Das HTML kommt vom eigenen Server, aus derselben Vorlage wie die
      // Seite selbst; der Text des Kindes ist darin schon maskiert.
      liste.insertAdjacentHTML("beforeend", ergebnis.html);
      feld.value = "";

      // Neue Protokolle folgen dem gemerkten Zustand.
      var neue = liste.children;
      for (var i = vorher; i < neue.length; i++) {
        if (alleOffen) { alleSetzen(true, neue[i]); }
      }
      knopfZeichnen();

      zumZug(neue[vorher]);
      fokusZurueck();
    }).catch(function () {
      wartenSetzen(false);
      statusSetzen("Die Verbindung hat nicht geklappt. Dein Text steht noch im " +
        "Feld – probier es gleich noch einmal.", true, false);
      fokusZurueck();
    });
  }

  form.addEventListener("click", function (ereignis) {
    var knopf = hinaufBisKnopf(ereignis.target, form);
    if (knopf) { gedrueckt = knopf; }
  });

  form.addEventListener("submit", function (ereignis) {
    /* Ohne fetch bleibt es ein gewoehnliches Formular. */
    if (!window.fetch || !window.FormData) { return; }
    ereignis.preventDefault();
    var knopf = ereignis.submitter || gedrueckt || fragenKnopf;
    gedrueckt = null;
    abschicken(knopf ? knopf.value : "spark");
  });

  /* Enter schickt ab (ueber den Hauptknopf, also am Spark), Umschalt+Enter
   * macht eine neue Zeile. Nach draussen geht es nur ueber den Knopf: Dieser
   * Weg soll eine bewusste Entscheidung sein. */
  feld.addEventListener("keydown", function (ereignis) {
    if (ereignis.key !== "Enter" || ereignis.shiftKey) { return; }
    if (ereignis.altKey || ereignis.ctrlKey || ereignis.metaKey) { return; }
    if (ereignis.isComposing) { return; }
    if (!window.fetch || !window.FormData) { return; }
    ereignis.preventDefault();
    if (fragenKnopf && fragenKnopf.disabled) { return; }
    abschicken("spark");
  });
})();
