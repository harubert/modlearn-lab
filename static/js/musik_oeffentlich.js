/* Die Musik-KI zum Ausprobieren, ganz unten auf /projekt/, und die
 * Musikstunde der Kinder unter /musik/.
 *
 * Ein Skript fuer beide Seiten, damit sie gleich funktionieren und ein
 * Fehler nur an einer Stelle behoben werden muss. Welche Seite es ist, sagt
 * das Formular mit seiner id: "musik-oe" auf /projekt/, "musik-kind" in der
 * Musikstunde. Alle anderen Teile tragen dieselbe id mit einem Anhang
 * ("-stile", "-text", ...). Was eine Seite nicht hat, gibt es dort nicht:
 * Die Musikstunde hat zusaetzlich eine Liste der eigenen Lieder
 * (data-liste), Stile in Gruppen (der Stand liefert "gruppen") und, wenn
 * die Lehrperson es erlaubt hat, den Textvorschlag vom Spark (data-text,
 * die zwei Wege "selbst" und "spark"). Die Probierecke hat nichts davon und
 * laeuft wie bisher.
 *
 * Die Seite selbst fragt den Musikdienst nicht, damit ein stummer Spark sie
 * nicht aufhaelt. Dieses Skript holt danach Stile und Marken (stand), baut
 * daraus die Auswahlkarten und Markenknoepfe und zeigt erst dann das
 * Formular. Nach dem Absenden fragt es wie die Testecke alle drei Sekunden
 * nach Warteposition und Restzeit und setzt am Ende den Abspieler ein.
 *
 * Gesprochen wird nur mit unseren Ansichten unter /projekt/musik/ und
 * /musik/. Jede Grenze prueft der Server; was hier steht (Zeichenzahl,
 * ausgegraute Knoepfe), ist nur Bequemlichkeit.
 */
(function () {
  "use strict";

  var ABFRAGE_MS = 3000;
  var NICHT_VERBUNDEN = "Die Musik-KI ist gerade nicht verbunden.";
  var NICHT_DURCH = "Die Anfrage kam nicht durch. Bitte noch einmal versuchen.";

  var form = document.getElementById("musik-oe") || document.getElementById("musik-kind");
  if (!form) { return; }
  function teil(name) { return document.getElementById(form.id + "-" + name); }
  var laden = teil("laden");
  var stileFeld = teil("stile");
  var markenFeld = teil("marken");
  var text = teil("text");
  var zeichen = teil("zeichen");
  var knopf = teil("senden");
  var meldung = teil("meldung");
  var ergebnis = teil("ergebnis");
  var standText = teil("stand");
  var spieler = teil("spieler");
  var liste = teil("liste");
  /* Nur in der Musikstunde, und nur wenn die Lehrperson es erlaubt hat. */
  var sparkTeil = teil("spark");
  var thema = teil("thema");
  var vorschlagKnopf = teil("vorschlag");
  var vorschlagMeldung = teil("vorschlag-meldung");
  var wege = form.querySelectorAll("[name=textweg]");
  var tokenFeld = form.querySelector("[name=csrfmiddlewaretoken]");
  var token = tokenFeld ? tokenFeld.value : "";
  var beobachtet = null;
  var letzterVorschlag = "";

  function dauerText(s) {
    s = Math.max(0, Math.round(Number(s) || 0));
    if (s < 60) { return s + " s"; }
    var m = Math.floor(s / 60), r = s % 60;
    return m + " min" + (r ? " " + r + " s" : "");
  }

  function zweistellig(n) { return n < 10 ? "0" + n : String(n); }

  /* Nur in der Musikstunde: die Liste der eigenen Lieder neu holen, nach
     dem Annehmen (Zaehler "noch ... Lieder") und wenn ein Lied fertig ist
     (dann steht es dort mit Abspieler). Scheitert das, bleibt die alte
     Liste stehen; beim naechsten Laden stimmt sie wieder. */
  function listeNeu() {
    if (!liste || !form.dataset.liste) { return; }
    fetch(form.dataset.liste, { credentials: "same-origin" })
      .then(function (a) { return a.ok ? a.text() : null; })
      .then(function (html) { if (html !== null) { liste.innerHTML = html; } })
      .catch(function () {});
  }

  /* --- Stile und Marken ------------------------------------------------ */
  function stilKarte(stil, i) {
    var karte = document.createElement("label");
    karte.className = "projekt-stil";
    var wahl = document.createElement("input");
    wahl.type = "radio";
    wahl.name = "stil";
    wahl.value = stil.name;
    wahl.required = true;
    if (i === 0) { wahl.checked = true; }
    var nummer = document.createElement("span");
    nummer.className = "projekt-stil-nummer";
    nummer.textContent = "S" + zweistellig(i + 1);
    var name = document.createElement("span");
    name.className = "projekt-stil-name";
    name.textContent = stil.titel || stil.name;
    karte.appendChild(wahl);
    karte.appendChild(nummer);
    karte.appendChild(name);
    if (stil.beschreibung) {
      var b = document.createElement("span");
      b.className = "projekt-stil-text";
      b.textContent = stil.beschreibung;
      karte.appendChild(b);
    }
    return karte;
  }

  /* Ohne Gruppen (Probierecke) kommen die Karten flach in das Feld, das
     selbst das Raster ist. Mit Gruppen (Musikstunde) bekommt jede Gruppe
     eine Ueberschrift und ein eigenes Raster; die Nummern laufen durch. */
  function stileEinsetzen(d) {
    if (!d.gruppen || !d.gruppen.length) {
      d.stile.forEach(function (s, i) { stileFeld.appendChild(stilKarte(s, i)); });
      return;
    }
    var i = 0;
    d.gruppen.forEach(function (gruppe) {
      var eigene = d.stile.filter(function (s) { return s.gruppe === gruppe; });
      if (!eigene.length) { return; }
      var block = document.createElement("div");
      block.className = "musik-stilblock";
      var kopf = document.createElement("p");
      kopf.className = "musik-stilgruppe";
      kopf.textContent = gruppe;
      block.appendChild(kopf);
      var raster = document.createElement("div");
      raster.className = "projekt-stile";
      eigene.forEach(function (s) { raster.appendChild(stilKarte(s, i)); i += 1; });
      block.appendChild(raster);
      stileFeld.appendChild(block);
    });
  }

  function markenKnopf(marke) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "projekt-marken-knopf";
    b.textContent = marke;
    /* Die Marke kommt an den Zeilenanfang, mit eigener Zeile: So erwartet
       ACE-Step die Gliederung, und so liest sie sich auch. */
    b.addEventListener("click", function () {
      var anfang = text.selectionStart, ende = text.selectionEnd;
      var davor = text.value.slice(0, anfang);
      var vorspann = davor && !/\n\n?$/.test(davor) ? (/\n$/.test(davor) ? "\n" : "\n\n") : "";
      var einfuegen = vorspann + marke + "\n";
      var neu = davor + einfuegen + text.value.slice(ende);
      if (neu.length > text.maxLength) { return; }
      text.value = neu;
      var stelle = anfang + einfuegen.length;
      text.setSelectionRange(stelle, stelle);
      text.focus();
      zaehlen();
    });
    return b;
  }

  function zaehlen() { zeichen.textContent = text.value.length; }

  function nichtVerbunden(satz) {
    form.hidden = true;
    laden.textContent = satz || NICHT_VERBUNDEN;
    laden.hidden = false;
  }

  function standLaden() {
    laden.hidden = false;
    fetch(form.dataset.stand, { credentials: "same-origin" })
      .then(function (a) { return a.json(); })
      .then(function (d) {
        if (!d.ok || !d.stile || !d.stile.length) { nichtVerbunden(d.satz); return; }
        stileEinsetzen(d);
        (d.marken || []).forEach(function (m) { markenFeld.appendChild(markenKnopf(m)); });
        laden.hidden = true;
        form.hidden = false;
        /* Nach einem Neuladen: das juengste eigene Lied weiter verfolgen. */
        if (d.letztes) { beobachten(d.letztes.abfrage); }
      })
      .catch(function () { nichtVerbunden(); });
  }

  /* --- Der Textvorschlag vom Spark (nur Musikstunde) ------------------- */
  function wegZeigen() {
    if (!sparkTeil) { return; }
    var spark = false;
    wege.forEach(function (w) { if (w.checked && w.value === "spark") { spark = true; } });
    sparkTeil.hidden = !spark;
    if (spark && thema) { thema.focus(); }
  }

  function nochSatz(noch) {
    if (noch == null) { return ""; }
    if (noch === 0) { return " Das war der letzte Vorschlag."; }
    return " Noch " + noch + " Vorschl" + (noch === 1 ? "ag" : "äge") + " möglich.";
  }

  function vorschlagHolen() {
    if (!form.dataset.text) { return; }
    /* Eigenes Getipptes geht nicht ungefragt verloren; ein alter
       Vorschlag, der noch unveraendert dasteht, schon. */
    if (text.value.trim() && text.value !== letzterVorschlag &&
        !window.confirm("Dein Text im Feld wird durch den Vorschlag ersetzt. Weiter?")) {
      return;
    }
    var daten = new FormData();
    daten.append("thema", thema ? thema.value : "");
    var dauer = form.querySelector("[name=sekunden]:checked");
    daten.append("sekunden", dauer ? dauer.value : "");
    vorschlagKnopf.disabled = true;
    vorschlagMeldung.textContent = "Der Spark schreibt …";
    fetch(form.dataset.text, {
      method: "POST",
      body: daten,
      headers: { "X-CSRFToken": token },
      credentials: "same-origin"
    }).then(function (a) {
      return a.json();
    }).then(function (d) {
      if (!d.ok) {
        vorschlagMeldung.textContent = (d.grund || NICHT_DURCH) + nochSatz(d.noch);
        /* Bei 0 bleibt der Knopf aus: Grenze erreicht oder abgeschaltet. */
        vorschlagKnopf.disabled = d.noch === 0;
        return;
      }
      text.value = d.text;
      letzterVorschlag = d.text;
      zaehlen();
      vorschlagMeldung.textContent = "Vorschlag eingesetzt. Du kannst ihn ändern." + nochSatz(d.noch);
      vorschlagKnopf.disabled = d.noch === 0;
      text.focus();
    }).catch(function () {
      vorschlagMeldung.textContent = NICHT_DURCH;
      vorschlagKnopf.disabled = false;
    });
  }

  /* --- Stand eines Liedes ---------------------------------------------- */
  function standZeigen(d) {
    ergebnis.hidden = false;
    if (d.zustand === "wartet") {
      var vor = Number(d.position);
      standText.textContent = !(vor > 0) ? "Gleich dran." :
        "Noch " + vor + (vor === 1 ? " Lied" : " Lieder") + " vor dir.";
      balkenZeigen(d);
    } else if (d.zustand === "rechnet") {
      standText.textContent = "Wird gerade erzeugt.";
      balkenZeigen(d);
    } else if (d.zustand === "fertig") {
      standText.textContent = "Fertig" + (d.dauer_s != null ? ", erzeugt in " + dauerText(d.dauer_s) : "") + ".";
      balkenFertig();
      if (d.datei) { abspielerEinsetzen(d.datei); }
      listeNeu();
    } else if (d.zustand === "fehler") {
      standText.textContent = d.fehler || "Das Lied konnte nicht erzeugt werden.";
      balkenWeg();
    } else {
      standText.textContent = "Wird übergeben …";
      balkenZeigen(d);
    }
  }

  /* --- Der Fortschrittsbalken ------------------------------------------
     Thomas (20.10.2026): lieber ein Balken als "noch etwa so und so viele
     Sekunden". Der Balken rechnet mit Zeit, nicht mit Zustaenden: Beim
     Anlegen schaetzt er, wann das Lied fertig ist, und laeuft gleichmaessig
     dorthin. Jede Abfrage schaetzt neu. Die Schaetzung besteht aus zwei
     Teilen: bis das eigene Lied an der Reihe ist (wartet_noch_s vom Dienst,
     der die Schlange kennt, sonst Platz mal typischer Dauer) und das eigene
     Rechnen (erwartung_s vom Server, ein Erfahrungswert je Fassung und
     Dauer, nachgefuehrt mit jedem fertigen Lied).

     Der Balken geht nie zurueck. Wird die Schaetzung spaeter, bleibt er
     stehen, bis die Zeit ihn einholt; wird sie frueher, springt er vor.
     Ueber 97 % kommt er erst, wenn das Lied wirklich fertig ist: Ein voller
     Balken, der nicht fertig ist, ist eine Luege. */
  var balken = null;
  var BALKEN_TAKT_MS = 250;
  var BALKEN_DECKEL = 0.97;

  function balkenElement() {
    var vorhanden = ergebnis.querySelector(".musik-balken");
    if (vorhanden) { return vorhanden; }
    var b = document.createElement("div");
    b.className = "musik-balken";
    b.setAttribute("role", "progressbar");
    b.setAttribute("aria-label", "Fortschritt des Liedes");
    b.setAttribute("aria-valuemin", "0");
    b.setAttribute("aria-valuemax", "100");
    b.setAttribute("aria-valuenow", "0");
    var f = document.createElement("span");
    f.className = "musik-balken-fuellung";
    b.appendChild(f);
    ergebnis.insertBefore(b, standText);
    return b;
  }

  /* Wann ist das Lied voraussichtlich fertig (Zeitstempel in ms)? */
  function balkenSchaetzung(d, jetzt) {
    var eigene = Number(d.erwartung_s);
    if (!(eigene > 0)) { eigene = 12; }
    if (d.zustand === "rechnet") {
      if (!balken.rechnetSeit) { balken.rechnetSeit = jetzt; }
      var rest = eigene - (jetzt - balken.rechnetSeit) / 1000;
      return jetzt + Math.max(rest, 2) * 1000;
    }
    var bisStart = Number(d.wartet_noch_s);
    if (!(bisStart >= 0)) { bisStart = Math.max(Number(d.position) || 0, 0) * eigene; }
    return jetzt + (bisStart + eigene) * 1000;
  }

  function balkenZeichnen() {
    if (!balken) { return; }
    var jetzt = Date.now();
    var anteil = (jetzt - balken.seit) / Math.max(balken.ende - balken.seit, 1000);
    anteil = Math.min(Math.max(anteil, 0), BALKEN_DECKEL);
    if (anteil > balken.gezeigt) { balken.gezeigt = anteil; }
    balken.fuellung.style.width = (balken.gezeigt * 100).toFixed(1) + "%";
    balken.element.setAttribute("aria-valuenow", String(Math.round(balken.gezeigt * 100)));
    /* Laenger als gedacht: sagen, statt bei 97 % zu schweigen. */
    balken.element.classList.toggle("ist-spaet", jetzt > balken.ende + 8000);
  }

  function balkenZeigen(d) {
    var jetzt = Date.now();
    if (!balken) {
      var element = balkenElement();
      balken = {
        element: element,
        fuellung: element.querySelector(".musik-balken-fuellung"),
        seit: jetzt, ende: jetzt, gezeigt: 0, rechnetSeit: null,
        uhr: setInterval(balkenZeichnen, BALKEN_TAKT_MS)
      };
      element.classList.remove("ist-fertig", "ist-spaet");
      element.hidden = false;
    }
    balken.ende = balkenSchaetzung(d, jetzt);
    balkenZeichnen();
  }

  function balkenFertig() {
    if (!balken) { return; }
    clearInterval(balken.uhr);
    balken.gezeigt = 1;
    balken.fuellung.style.width = "100%";
    balken.element.setAttribute("aria-valuenow", "100");
    balken.element.classList.add("ist-fertig");
    balken.element.classList.remove("ist-spaet");
    balken = null;
  }

  function balkenWeg() {
    var element = ergebnis.querySelector(".musik-balken");
    if (balken) { clearInterval(balken.uhr); balken = null; }
    if (element) {
      element.hidden = true;
      element.classList.remove("ist-fertig", "ist-spaet");
      element.querySelector(".musik-balken-fuellung").style.width = "0%";
      element.setAttribute("aria-valuenow", "0");
    }
  }

  function abspielerEinsetzen(adresse) {
    if (spieler.querySelector("audio")) { return; }
    var audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = adresse;
    spieler.appendChild(audio);
  }

  function laeuft(zustand) { return zustand === "wartet" || zustand === "rechnet" || !zustand; }

  function beobachten(adresse) {
    beobachtet = adresse;
    knopf.disabled = true;
    function frage() {
      if (beobachtet !== adresse) { return; }
      fetch(adresse, { credentials: "same-origin" })
        .then(function (a) {
          if (a.status === 404) { return { ok: false, weg: true }; }
          return a.json();
        })
        .then(function (d) {
          if (!d.ok) {
            if (d.weg) {
              ergebnis.hidden = false;
              standText.textContent = d.grund || "Dieses Lied ist nicht mehr da.";
              spieler.textContent = "";
              balkenWeg();
              knopf.disabled = false;
              return;
            }
            standText.textContent = d.grund || NICHT_VERBUNDEN;
            setTimeout(frage, ABFRAGE_MS * 3);
            return;
          }
          standZeigen(d);
          if (laeuft(d.zustand)) { setTimeout(frage, ABFRAGE_MS); }
          else { knopf.disabled = false; }
        })
        .catch(function () { setTimeout(frage, ABFRAGE_MS * 3); });
    }
    frage();
  }

  /* --- Absenden -------------------------------------------------------- */
  text.addEventListener("input", zaehlen);
  wege.forEach(function (w) { w.addEventListener("change", wegZeigen); });
  if (vorschlagKnopf) { vorschlagKnopf.addEventListener("click", vorschlagHolen); }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    knopf.disabled = true;
    meldung.textContent = "Wird übergeben …";
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-CSRFToken": token },
      credentials: "same-origin"
    }).then(function (a) {
      /* Auch eine Absage (400, 429, 503) kommt mit einem Satz zurueck. */
      return a.json();
    }).then(function (d) {
      if (!d.ok) {
        meldung.textContent = d.grund || "Das hat nicht geklappt. Bitte noch einmal versuchen.";
        knopf.disabled = false;
        return;
      }
      meldung.textContent = "Angenommen.";
      spieler.textContent = "";
      /* Ein neues Lied, ein neuer Balken: Der alte darf nicht bei 100 %
         stehen bleiben, waehrend das neue erst in die Schlange kommt. */
      balkenWeg();
      listeNeu();
      standZeigen(d);
      beobachten(d.abfrage);
    }).catch(function () {
      meldung.textContent = NICHT_DURCH;
      knopf.disabled = false;
    });
  });

  zaehlen();
  wegZeigen();
  standLaden();
})();
