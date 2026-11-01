/* Die Testecke fuer die Musik-KI: Stil uebernehmen, Marken einfuegen,
 * Rechenzeit schaetzen, absenden, Warteschlange abfragen, abspielen, loeschen.
 *
 * Der Browser spricht nur mit unseren Ansichten unter /labor/musik/. Der
 * Spark ist von hier aus gar nicht erreichbar, und das ist Absicht.
 *
 * ComfyUI rechnet seriell. Darum steht bei jedem wartenden Lied die Position
 * und die Restzeit des Dienstes: Eine Seite, die nur "bitte warten" sagt,
 * waehrend zwanzig Minuten Schlange davor stehen, sieht aus wie kaputt.
 */
(function () {
  "use strict";

  var ABFRAGE_MS = 3000;
  var form = document.getElementById("musik-form");
  var liste = document.getElementById("musik-lieder");
  var leer = document.getElementById("musik-leer");
  var tokenFeld = document.querySelector("[name=csrfmiddlewaretoken]");
  var token = tokenFeld ? tokenFeld.value : "";

  function dauerText(s) {
    s = Math.max(0, Math.round(Number(s) || 0));
    if (s < 60) { return s + " s"; }
    var m = Math.floor(s / 60), r = s % 60;
    return m + " min" + (r ? " " + r + " s" : "");
  }

  function senden(adresse, daten) {
    return fetch(adresse, {
      method: "POST",
      body: daten || new FormData(),
      headers: { "X-CSRFToken": token },
      credentials: "same-origin"
    }).then(function (a) {
      if (!a.ok) { throw new Error(String(a.status)); }
      return a.json();
    });
  }

  /* --- Formular ------------------------------------------------------- */
  if (form) {
    var tags = document.getElementById("musik-tags");
    var bpm = document.getElementById("musik-bpm");
    var tonart = document.getElementById("musik-tonart");
    var takt = document.getElementById("musik-takt");
    var text = document.getElementById("musik-text");
    var zeichen = document.getElementById("musik-zeichen");
    var regler = document.getElementById("musik-sekunden");
    var reglerAnzeige = document.getElementById("musik-sekunden-anzeige");
    var schaetzung = document.getElementById("musik-schaetzung");
    var meldung = document.getElementById("musik-meldung");
    var knopf = document.getElementById("musik-senden");

    function stilUebernehmen() {
      var gewaehlt = form.querySelector("input[name=stil]:checked");
      if (!gewaehlt) { return; }
      tags.value = gewaehlt.dataset.tags || "";
      bpm.value = gewaehlt.dataset.bpm || "";
      tonart.value = gewaehlt.dataset.tonart || "";
      if (gewaehlt.dataset.takt) { takt.value = gewaehlt.dataset.takt; }
    }

    function schaetzen() {
      var sek = Number(regler.value);
      reglerAnzeige.textContent = sek;
      var fassung = form.querySelector("input[name=fassung]:checked");
      var jeMinute = fassung ? Number(fassung.dataset.sekundenJeMinute) : 0;
      if (!jeMinute) { schaetzung.textContent = ""; return; }
      schaetzung.textContent = "Geschätzte Rechenzeit: etwa " +
        dauerText(sek / 60 * jeMinute) +
        ", sobald dieses Lied an der Reihe ist.";
    }

    form.addEventListener("change", function (e) {
      if (e.target.name === "stil") { stilUebernehmen(); }
      if (e.target.name === "fassung") { schaetzen(); }
    });
    regler.addEventListener("input", schaetzen);
    text.addEventListener("input", function () { zeichen.textContent = text.value.length; });

    /* Die Marke kommt an den Zeilenanfang, mit eigener Zeile: So erwartet
       ACE-Step die Gliederung, und so liest sie sich auch. */
    form.querySelectorAll("[data-marke]").forEach(function (b) {
      b.addEventListener("click", function () {
        var marke = b.dataset.marke;
        var anfang = text.selectionStart, ende = text.selectionEnd;
        var davor = text.value.slice(0, anfang);
        var vorspann = davor && !/\n\n?$/.test(davor) ? (/\n$/.test(davor) ? "\n" : "\n\n") : "";
        var einfuegen = vorspann + marke + "\n";
        text.value = davor + einfuegen + text.value.slice(ende);
        var stelle = anfang + einfuegen.length;
        text.setSelectionRange(stelle, stelle);
        text.focus();
        zeichen.textContent = text.value.length;
      });
    });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      knopf.disabled = true;
      meldung.textContent = "Wird übergeben …";
      senden(form.action, new FormData(form)).then(function (d) {
        if (!d.ok) { meldung.textContent = d.grund || "Der Musikdienst hat abgelehnt."; return; }
        meldung.textContent = "Angenommen.";
        var li = liedAnlegen(d);
        standZeigen(li, d);
        beobachten(li);
      }).catch(function () {
        meldung.textContent = "Die Anfrage kam nicht durch. Bitte noch einmal versuchen.";
      }).then(function () { knopf.disabled = false; });
    });

    stilUebernehmen();
    schaetzen();
  }

  /* --- Liste der eigenen Lieder --------------------------------------- */
  function liedAnlegen(d) {
    var li = document.createElement("li");
    li.className = "musik-lied";
    li.dataset.auftrag = d.auftrag;
    li.dataset.zustand = d.zustand || "wartet";
    li.dataset.abfrage = d.abfrage;
    li.dataset.loeschen = d.loeschen;
    var kopf = document.createElement("p");
    kopf.className = "musik-lied-kopf";
    var name = document.createElement("strong");
    name.textContent = d.stil || "ohne Stil";
    kopf.appendChild(name);
    kopf.appendChild(document.createTextNode(", " + d.sekunden + " s, " + d.fassung +
      ", abgeschickt " + d.zeit));
    li.appendChild(kopf);
    [["p", "musik-lied-stand"], ["div", "musik-lied-spieler"]].forEach(function (t) {
      var el = document.createElement(t[0]);
      el.className = t[1];
      li.appendChild(el);
    });
    var weg = document.createElement("button");
    weg.type = "button";
    weg.className = "knopf-leise musik-lied-loeschen";
    weg.textContent = "Löschen";
    li.appendChild(weg);
    var m = document.createElement("p");
    m.className = "musik-lied-meldung";
    m.setAttribute("role", "status");
    li.appendChild(m);
    liste.insertBefore(li, liste.firstChild);
    if (leer) { leer.hidden = true; }
    return li;
  }

  function standZeigen(li, d) {
    var stand = li.querySelector(".musik-lied-stand");
    li.dataset.zustand = d.zustand || "";
    if (d.zustand === "wartet") {
      stand.textContent = "Wartet" +
        (d.position != null ? ", Platz " + d.position + " in der Schlange" : "") +
        (d.wartet_noch_s != null ? ", noch etwa " + dauerText(d.wartet_noch_s) : "") + ".";
    } else if (d.zustand === "rechnet") {
      stand.textContent = "Wird gerade gerechnet" +
        (d.wartet_noch_s != null ? ", noch etwa " + dauerText(d.wartet_noch_s) : "") + ".";
    } else if (d.zustand === "fertig") {
      stand.textContent = "Fertig" + (d.dauer_s != null ? ", gerechnet in " + dauerText(d.dauer_s) : "") + ".";
      if (d.datei) { spielerEinsetzen(li, d.datei); }
    } else if (d.zustand === "fehler") {
      stand.textContent = "Fehler: " + (d.fehler || "ohne Angabe des Dienstes") + ".";
    } else {
      stand.textContent = d.zustand || "";
    }
  }

  function spielerEinsetzen(li, adresse) {
    var platz = li.querySelector(".musik-lied-spieler");
    if (platz.querySelector("audio")) { return; }
    var audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = adresse;
    platz.appendChild(audio);
  }

  function beobachten(li) {
    function frage() {
      if (!li.isConnected) { return; }
      fetch(li.dataset.abfrage, { credentials: "same-origin" })
        .then(function (a) { return a.json(); })
        .then(function (d) {
          if (!d.ok) {
            li.querySelector(".musik-lied-stand").textContent = d.grund || "Keine Auskunft.";
            setTimeout(frage, ABFRAGE_MS * 3);
            return;
          }
          standZeigen(li, d);
          if (d.zustand === "wartet" || d.zustand === "rechnet") { setTimeout(frage, ABFRAGE_MS); }
        })
        .catch(function () { setTimeout(frage, ABFRAGE_MS * 3); });
    }
    setTimeout(frage, ABFRAGE_MS);
  }

  liste.addEventListener("click", function (e) {
    var knopf = e.target.closest(".musik-lied-loeschen");
    if (!knopf) { return; }
    var li = knopf.closest(".musik-lied");
    var meldung = li.querySelector(".musik-lied-meldung");
    knopf.disabled = true;
    senden(li.dataset.loeschen).then(function (d) {
      meldung.textContent = d.satz || "";
      /* Nur wenn der Dienst "entfernt" meldet, verschwindet der Spieler.
         Der Satz bleibt stehen, damit man sieht, was mit der Datei ist. */
      if (d.ok) {
        var spieler = li.querySelector(".musik-lied-spieler");
        spieler.textContent = "";
        li.querySelector(".musik-lied-stand").textContent = d.entfernt ? "Gelöscht." : "Nicht mehr am Spark.";
        knopf.remove();
      } else {
        knopf.disabled = false;
      }
    }).catch(function () {
      meldung.textContent = "Die Anfrage kam nicht durch.";
      knopf.disabled = false;
    });
  });

  /* Beim Laden: Was noch nicht fertig ist, weiter beobachten; was fertig
     ist, gleich abfragen, damit der Spieler erscheint. */
  liste.querySelectorAll(".musik-lied").forEach(function (li) {
    var z = li.dataset.zustand;
    if (z === "wartet" || z === "rechnet" || z === "fertig" || !z) { beobachten(li); }
  });
})();
