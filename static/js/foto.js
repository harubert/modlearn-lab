/* Foto aufnehmen, den Ausschnitt waehlen, verkleinern, vom Spark ablesen
 * lassen.
 *
 * Die Verkleinerung passiert hier im Browser und ist verbindlich. Gemessen
 * am Spark: ein unveraendertes Handyfoto mit 3024x4032 kostet 10 Sekunden
 * und 11.873 Token, dasselbe Bild mit 1600 px langer Kante 2,1 Sekunden und
 * 1.929 Token, ohne dass die Erkennung schlechter wird. Ausserdem haelt das
 * die 20-MB-Grenze des Proxys ein: Das Bild geht als Data-URL im JSON mit,
 * und Base64 blaeht um ein Drittel auf.
 *
 * Verkleinern, nicht staerker komprimieren: Unscharfe Bilder verlieren
 * Hochzahlen und kleine Ziffern.
 *
 * Vor dem Abschicken waehlt das Kind selbst den Ausschnitt. Auf einem
 * Heftfoto steht fast immer mehr als die eine Aufgabe: die Nachbaraufgabe,
 * der Name auf dem Blatt, der halbe Tisch. Was weggeschnitten ist, geht nie
 * an den Server, und das Modell liest nicht die falsche Zeile ab.
 *
 * Zwei Kantenlaengen, und das mit Absicht: Geschnitten wird aus einer
 * Leinwand mit 2400 px langer Kante, abgeschickt werden hoechstens 1600 px.
 * Wer nur ein Viertel des Bildes waehlt, holt sich so aus der groesseren
 * Vorlage noch genug Punkte fuer die kleinen Ziffern. Die grosse Leinwand
 * bleibt im Browser und wird nach dem Abschicken weggeworfen.
 *
 * Am Server aendert sich dadurch nichts: Er bekommt weiterhin genau eine
 * Data-URL.
 */
(function () {
  "use strict";

  var ARBEITSKANTE = 2400;   // lange Kante der Leinwand, aus der geschnitten wird
  var LANGE_KANTE = 1600;    // lange Kante dessen, was den Server erreicht
  var GUETE = 0.85;
  var MINDESTRAHMEN = 96;    // Anzeigepixel, darunter wird der Rahmen unbedienbar
  var ENGE_GRENZE = 150;     // ab hier werden die Greifecken kleiner gezeichnet
  var TASTENSCHRITT = 8;     // Anzeigepixel je Pfeiltastendruck
  var ZIEHSCHWELLE = 12;     // Anzeigepixel, ab denen ein Tippen ein Ziehen ist

  var knopf = document.getElementById("fotoknopf");
  var eingabe = document.getElementById("fotoeingabe");
  if (!knopf || !eingabe) { return; }

  /* Das Foto wird aufgehoben, damit die Lehrperson sieht, was das Kind
   * vor sich hatte: Die Texterkennung kann danebengelegen haben. */

  var ziel = document.getElementById(knopf.dataset.ziel);
  var versteckt = document.getElementById(knopf.dataset.feld);
  var stand = document.getElementById("fotostand");
  var vorschau = document.getElementById("fotovorschau");

  /* Die Teile des Zuschnitts aus _zuschnitt.html. Fehlt die Vorlage, geht
   * das ganze Bild hinaus wie vorher: Die Fotofunktion darf nicht daran
   * haengen, dass eine zweite Datei eingebunden ist. */
  var schicht = document.getElementById("zuschnitt");
  var buehne = document.getElementById("zuschnitt-buehne");
  var flaeche = document.getElementById("zuschnitt-flaeche");
  var anzeigeLeinwand = document.getElementById("zuschnitt-bild");
  var rahmen = document.getElementById("zuschnitt-rahmen");
  var ansage = document.getElementById("zuschnitt-ansage");
  var knopfFertig = document.getElementById("zuschnitt-fertig");
  var knopfGanz = document.getElementById("zuschnitt-ganz");
  var knopfWeg = document.getElementById("zuschnitt-abbrechen");
  var zuschnittDa = !!(schicht && buehne && flaeche && anzeigeLeinwand &&
                       rahmen && knopfFertig && knopfGanz && knopfWeg);

  var quelle = null;                      // Leinwand mit dem vorbereiteten Foto
  var anzeige = { breite: 0, hoehe: 0 };  // Groesse, in der es zu sehen ist
  var wahl = { x: 0, y: 0, b: 0, h: 0 };  // der Rahmen, in Anzeigepixeln
  var zug = null;                         // laufendes Ziehen mit Finger oder Maus
  var fokusVorher = null;
  var ansageUhr = null;

  function melden(text, istFehler) {
    stand.textContent = text;
    stand.hidden = !text;
    stand.classList.toggle("meldung-fehler", !!istFehler);
  }

  function csrfWert() {
    var treffer = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[2]) : "";
  }

  /* Legt das Foto als Leinwand bereit, verkleinert auf die Arbeitskante.
   * createImageBitmap mit imageOrientation dreht das Bild nach den Angaben
   * der Kamera; ohne das liegen Hochformataufnahmen quer. */
  function vorbereiten(datei) {
    return new Promise(function (fertig, scheitern) {
      function zeichnen(bildquelle, breite, hoehe) {
        var faktor = Math.min(1, ARBEITSKANTE / Math.max(breite, hoehe));
        var leinwand = document.createElement("canvas");
        leinwand.width = Math.max(1, Math.round(breite * faktor));
        leinwand.height = Math.max(1, Math.round(hoehe * faktor));
        var stift = leinwand.getContext("2d");
        stift.drawImage(bildquelle, 0, 0, leinwand.width, leinwand.height);
        fertig(leinwand);
      }

      if (typeof createImageBitmap === "function") {
        createImageBitmap(datei, { imageOrientation: "from-image" })
          .then(function (bild) { zeichnen(bild, bild.width, bild.height); })
          .catch(function () { ueberBild(); });
      } else {
        ueberBild();
      }

      function ueberBild() {
        var leser = new FileReader();
        leser.onload = function () {
          var bild = new Image();
          bild.onload = function () {
            zeichnen(bild, bild.naturalWidth, bild.naturalHeight);
          };
          bild.onerror = function () { scheitern(new Error("Bild unlesbar")); };
          bild.src = leser.result;
        };
        leser.onerror = function () { scheitern(new Error("Datei unlesbar")); };
        leser.readAsDataURL(datei);
      }
    });
  }

  /* Schneidet den gewaehlten Teil aus und verkleinert ihn in einem Zug auf
   * die Kantenlaenge fuer den Server. Zweimal zeichnen wuerde das Bild
   * unnoetig unscharf machen. Die Werte sind Bildpunkte der Arbeitsleinwand,
   * keine Anzeigepixel. */
  function ausschnitt(x, y, breite, hoehe) {
    x = Math.max(0, Math.min(Math.round(x), quelle.width - 1));
    y = Math.max(0, Math.min(Math.round(y), quelle.height - 1));
    breite = Math.max(1, Math.min(Math.round(breite), quelle.width - x));
    hoehe = Math.max(1, Math.min(Math.round(hoehe), quelle.height - y));

    var faktor = Math.min(1, LANGE_KANTE / Math.max(breite, hoehe));
    var leinwand = document.createElement("canvas");
    leinwand.width = Math.max(1, Math.round(breite * faktor));
    leinwand.height = Math.max(1, Math.round(hoehe * faktor));
    var stift = leinwand.getContext("2d");
    stift.drawImage(quelle, x, y, breite, hoehe,
                    0, 0, leinwand.width, leinwand.height);
    return leinwand.toDataURL("image/jpeg", GUETE);
  }

  /* --- Der Zuschnitt ----------------------------------------------------- */

  /* Kleinste Groesse des Rahmens. Kleiner darf er nicht werden, weil sonst
   * die vier Greifecken die ganze Mitte zudecken und das Verschieben
   * unmoeglich wird. Bei einem winzigen Bild gilt dessen Groesse. */
  function mindestmass() {
    return Math.min(MINDESTRAHMEN, anzeige.breite, anzeige.hoehe);
  }

  function begrenzen() {
    var m = mindestmass();
    wahl.b = Math.max(m, Math.min(wahl.b, anzeige.breite));
    wahl.h = Math.max(m, Math.min(wahl.h, anzeige.hoehe));
    wahl.x = Math.max(0, Math.min(wahl.x, anzeige.breite - wahl.b));
    wahl.y = Math.max(0, Math.min(wahl.y, anzeige.hoehe - wahl.h));
  }

  function rahmenZeichnen() {
    rahmen.style.left = Math.round(wahl.x) + "px";
    rahmen.style.top = Math.round(wahl.y) + "px";
    rahmen.style.width = Math.round(wahl.b) + "px";
    rahmen.style.height = Math.round(wahl.h) + "px";
    rahmen.classList.toggle("ist-eng",
      wahl.b < ENGE_GRENZE || wahl.h < ENGE_GRENZE);
  }

  /* Sagt Vorlesewerkzeugen, wo der Rahmen jetzt steht, und zwar in Prozent:
   * Pixel sagen niemandem etwas, der das Bild nicht sieht. Gesammelt, damit
   * nicht jeder Tastendruck eine eigene Meldung wird. */
  function ansagen() {
    if (!ansage || !anzeige.breite || !anzeige.hoehe) { return; }
    if (ansageUhr) { clearTimeout(ansageUhr); }
    ansageUhr = setTimeout(function () {
      ansageUhr = null;
      ansage.textContent = "Rahmen " +
        Math.round(wahl.b / anzeige.breite * 100) + " Prozent breit und " +
        Math.round(wahl.h / anzeige.hoehe * 100) +
        " Prozent hoch, linke obere Ecke bei " +
        Math.round(wahl.x / anzeige.breite * 100) + " und " +
        Math.round(wahl.y / anzeige.hoehe * 100) + " Prozent.";
    }, 350);
  }

  /* Legt fest, wie gross das Foto in der Schicht zu sehen ist. Die Leinwand
   * bekommt zusaetzlich die Punkte des Geraetes, sonst sieht das Foto auf
   * einem scharfen Handybildschirm ausgefranst aus. */
  function buehneVermessen() {
    var platzB = buehne.clientWidth;
    var platzH = buehne.clientHeight;
    /* Sicherheitsnetz: Meldet ein Browser fuer die eben erst sichtbar
     * gewordene Schicht noch keine Groesse, faellt das Foto sonst auf null
     * Pixel zusammen. */
    if (platzB < 40) { platzB = Math.round(window.innerWidth * 0.85); }
    if (platzH < 40) { platzH = Math.round(window.innerHeight * 0.5); }

    /* Kleine Bilder werden fuer die Anzeige vergroessert, damit der Rahmen
     * ueberhaupt zu greifen ist. Geschnitten wird trotzdem aus der Vorlage. */
    var faktor = Math.min(platzB / quelle.width, platzH / quelle.height, 2);
    anzeige.breite = Math.max(1, Math.round(quelle.width * faktor));
    anzeige.hoehe = Math.max(1, Math.round(quelle.height * faktor));

    flaeche.style.width = anzeige.breite + "px";
    flaeche.style.height = anzeige.hoehe + "px";

    var punkte = Math.min(window.devicePixelRatio || 1, 2);
    anzeigeLeinwand.width = Math.max(1, Math.round(anzeige.breite * punkte));
    anzeigeLeinwand.height = Math.max(1, Math.round(anzeige.hoehe * punkte));
    anzeigeLeinwand.getContext("2d").drawImage(
      quelle, 0, 0, anzeigeLeinwand.width, anzeigeLeinwand.height
    );
  }

  /* Der Rahmen startet gross und mittig: Meistens ist das Blatt schon gut
   * getroffen, und es bleibt beim kleinen Nachziehen. */
  function wahlZuruecksetzen() {
    wahl.b = anzeige.breite * 0.86;
    wahl.h = anzeige.hoehe * 0.86;
    wahl.x = (anzeige.breite - wahl.b) / 2;
    wahl.y = (anzeige.hoehe - wahl.h) / 2;
    begrenzen();
  }

  /* Nach dem Drehen des Geraetes ist alles anders gross: Der Rahmen behaelt
   * seinen Anteil am Bild, nicht seine Pixelmasse. */
  function neuVermessen() {
    if (!quelle) { return; }
    var anteil = (anzeige.breite && anzeige.hoehe) ? {
      x: wahl.x / anzeige.breite,
      y: wahl.y / anzeige.hoehe,
      b: wahl.b / anzeige.breite,
      h: wahl.h / anzeige.hoehe
    } : null;

    buehneVermessen();

    if (anteil) {
      wahl.x = anteil.x * anzeige.breite;
      wahl.y = anteil.y * anzeige.hoehe;
      wahl.b = anteil.b * anzeige.breite;
      wahl.h = anteil.h * anzeige.hoehe;
      begrenzen();
    } else {
      wahlZuruecksetzen();
    }
    rahmenZeichnen();
  }

  function zugBewegen(ereignis) {
    if (!zug || ereignis.pointerId !== zug.zeiger) { return; }
    ereignis.preventDefault();

    var dx = ereignis.clientX - zug.startX;
    var dy = ereignis.clientY - zug.startY;
    var a = zug.anfang;

    if (zug.art === "verschieben") {
      wahl.x = a.x + dx;
      wahl.y = a.y + dy;
      wahl.b = a.b;
      wahl.h = a.h;
    } else if (zug.art === "neu") {
      /* Erst ab einer deutlichen Bewegung wird ein neuer Rahmen aufgezogen.
       * Ein kurzes Antippen neben dem Rahmen soll ihn nicht wegnehmen. */
      if (!zug.gezogen && Math.abs(dx) < ZIEHSCHWELLE &&
          Math.abs(dy) < ZIEHSCHWELLE) { return; }
      zug.gezogen = true;
      wahl.x = Math.min(zug.ortX, zug.ortX + dx);
      wahl.y = Math.min(zug.ortY, zug.ortY + dy);
      wahl.b = Math.abs(dx);
      wahl.h = Math.abs(dy);
    } else {
      var m = mindestmass();
      if (zug.art.charAt(0) === "l") {
        var rechts = a.x + a.b;
        wahl.x = Math.max(0, Math.min(a.x + dx, rechts - m));
        wahl.b = rechts - wahl.x;
      } else {
        wahl.x = a.x;
        wahl.b = Math.max(m, Math.min(a.b + dx, anzeige.breite - a.x));
      }
      if (zug.art.charAt(1) === "o") {
        var unten = a.y + a.h;
        wahl.y = Math.max(0, Math.min(a.y + dy, unten - m));
        wahl.h = unten - wahl.y;
      } else {
        wahl.y = a.y;
        wahl.h = Math.max(m, Math.min(a.h + dy, anzeige.hoehe - a.y));
      }
    }

    begrenzen();
    rahmenZeichnen();
  }

  function zugBeenden(ereignis) {
    if (!zug) { return; }
    if (ereignis && ereignis.pointerId !== zug.zeiger) { return; }
    var teil = zug.teil;
    if (ereignis && teil.releasePointerCapture) {
      try { teil.releasePointerCapture(ereignis.pointerId); } catch (e) {}
    }
    teil.removeEventListener("pointermove", zugBewegen);
    teil.removeEventListener("pointerup", zugBeenden);
    teil.removeEventListener("pointercancel", zugBeenden);
    zug = null;
    rahmen.classList.remove("wird-gezogen");
    ansagen();
  }

  /* Ein Ziehen beginnt. setPointerCapture ist der Grund fuer die
   * Pointer-Events: Damit bleibt der Finger an der Ecke, die er angefasst
   * hat, auch wenn er sie unterwegs verlaesst. */
  function zugBeginnen(ereignis, art) {
    if (zug || !quelle) { return; }
    if (typeof ereignis.button === "number" && ereignis.button !== 0) { return; }
    ereignis.preventDefault();

    var teil = ereignis.currentTarget;
    zug = {
      art: art,
      teil: teil,
      zeiger: ereignis.pointerId,
      startX: ereignis.clientX,
      startY: ereignis.clientY,
      anfang: { x: wahl.x, y: wahl.y, b: wahl.b, h: wahl.h },
      gezogen: false,
      ortX: 0,
      ortY: 0
    };
    if (teil.setPointerCapture) {
      try { teil.setPointerCapture(ereignis.pointerId); } catch (e) {}
    }
    teil.addEventListener("pointermove", zugBewegen);
    teil.addEventListener("pointerup", zugBeenden);
    teil.addEventListener("pointercancel", zugBeenden);
    rahmen.classList.add("wird-gezogen");
  }

  /* Waechst und schrumpft um die Mitte, damit der Rahmen beim
   * Groessermachen nicht von der Aufgabe wegwandert. */
  function weiten(um) {
    wahl.x -= um;
    wahl.y -= um;
    wahl.b += um * 2;
    wahl.h += um * 2;
  }

  function aufTaste(ereignis) {
    if (ereignis.altKey || ereignis.ctrlKey || ereignis.metaKey) { return; }
    var taste = ereignis.key;
    var s = TASTENSCHRITT;
    var groesse = ereignis.shiftKey;
    var getan = true;

    if (taste === "ArrowLeft" || taste === "Left") {
      if (groesse) { wahl.b -= s; } else { wahl.x -= s; }
    } else if (taste === "ArrowRight" || taste === "Right") {
      if (groesse) { wahl.b += s; } else { wahl.x += s; }
    } else if (taste === "ArrowUp" || taste === "Up") {
      if (groesse) { wahl.h -= s; } else { wahl.y -= s; }
    } else if (taste === "ArrowDown" || taste === "Down") {
      if (groesse) { wahl.h += s; } else { wahl.y += s; }
    } else if (taste === "+" || taste === "Add") {
      weiten(s);
    } else if (taste === "-" || taste === "Subtract") {
      weiten(-s);
    } else {
      getan = false;
    }

    if (!getan) { return; }
    ereignis.preventDefault();
    begrenzen();
    rahmenZeichnen();
    ansagen();
  }

  /* Der Tastenweg bleibt in der Schicht. Wer hinaustabbt, landet sonst im
   * Formular darunter, das gerade verdeckt ist, und tippt ins Leere. */
  function aufSchichtTaste(ereignis) {
    if (ereignis.key === "Escape" || ereignis.key === "Esc") {
      ereignis.preventDefault();
      abbrechen();
      return;
    }
    if (ereignis.key !== "Tab") { return; }
    var liste = [rahmen, knopfFertig, knopfGanz, knopfWeg];
    var pos = liste.indexOf(document.activeElement);
    var weiter = ereignis.shiftKey ? -1 : 1;
    ereignis.preventDefault();
    liste[pos < 0 ? 0 : (pos + weiter + liste.length) % liste.length].focus();
  }

  /* Ohne static/css/zuschnitt.css waere die Schicht keine Schicht, sondern
   * ein Kasten mitten in der Seite mit einem Rahmen an der falschen Stelle.
   * Das soll kein Kind zu sehen bekommen: Dann geht lieber das ganze Bild
   * hinaus. Wird der Stilbogen nachgetragen, greift der Zuschnitt von
   * selbst, ohne Aenderung hier. */
  function schichtTraegt() {
    if (!window.getComputedStyle) { return true; }
    var stil = window.getComputedStyle(schicht);
    return !!stil && stil.position === "fixed";
  }

  function oeffnen(leinwand) {
    quelle = leinwand;
    fokusVorher = document.activeElement;
    anzeige.breite = 0;
    anzeige.hoehe = 0;
    if (ansage) { ansage.textContent = ""; }
    schicht.hidden = false;
    document.body.classList.add("zuschnitt-offen");
    neuVermessen();
    window.addEventListener("resize", neuVermessen);
    rahmen.focus();
  }

  /* Der Fokus muss die Schicht verlassen, sonst haengt er an etwas, das
   * gerade versteckt wurde, und die naechste Taste geht ins Leere. Waehrend
   * abgeschickt wird, ist der Fotoknopf gesperrt und nimmt keinen Fokus an;
   * dann bekommt ihn das Textfeld, in dem der abgelesene Text gleich
   * erscheint. */
  function fokusZurueck() {
    var koepfe = [fokusVorher, knopf, ziel];
    for (var n = 0; n < koepfe.length; n++) {
      var teil = koepfe[n];
      if (teil && teil.focus && !teil.disabled && !schicht.contains(teil)) {
        teil.focus();
        return;
      }
    }
  }

  function schliessen() {
    zugBeenden(null);
    window.removeEventListener("resize", neuVermessen);
    schicht.hidden = true;
    document.body.classList.remove("zuschnitt-offen");
    /* Die Arbeitsleinwand ist gross. Sie wird nicht mehr gebraucht, sobald
     * die Data-URL steht, und belegt am Handy sonst weiter Speicher. */
    quelle = null;
    fokusZurueck();
    fokusVorher = null;
  }

  /* Erst freigeben, dann schliessen: Ein gesperrter Knopf nimmt keinen Fokus
   * an, und dann landet er nach dem Abbrechen nirgends. */
  function abbrechen() {
    knopf.disabled = false;
    schliessen();
    melden("", false);
  }

  /* --- Abschicken -------------------------------------------------------- */

  function absenden(dataUrl) {
    var kb = Math.round(dataUrl.length * 0.75 / 1024);
    melden("Der Rechner der Schule liest das Foto ab (" + kb + " kB) …", false);
    vorschau.src = dataUrl;
    vorschau.hidden = false;
    if (versteckt) { versteckt.value = dataUrl; }
    var herkunft = document.getElementById("herkunftfeld");
    if (herkunft) { herkunft.value = "foto"; }

    var daten = new FormData();
    daten.append("bild", dataUrl);
    fetch(knopf.dataset.url, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert() },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      /* 413 kommt vom Proxy, nicht von der Anwendung, und hat einen leeren
       * Koerper. Ohne diesen Zweig zeigte das Skript "nicht angekommen",
       * was den Grund verschweigt. Bei verkleinerten Bildern sollte das nie
       * vorkommen; wenn doch, ist die Verkleinerung kaputt und das soll
       * dastehen. */
      if (antwort.status === 413) {
        return { ok: false, meldung: "Das Foto ist zu groß. Probier es mit einem neuen Foto." };
      }
      return antwort.json().catch(function () {
        return { ok: false, meldung: "Der Rechner der Schule hat unverständlich geantwortet." };
      });
    }).then(function (ergebnis) {
      knopf.disabled = false;
      if (!ergebnis || !ergebnis.ok) {
        melden((ergebnis && ergebnis.meldung) || "Das hat nicht geklappt.", true);
        return;
      }
      // Der erkannte Text landet zum Pruefen im Feld, nicht direkt in der
      // Aufgabe. Eine Texterkennung, die man nicht berichtigen kann, ist
      // bei handschriftlichen Zahlen ein Aergernis.
      if (ziel) {
        ziel.value = ergebnis.text;
        ziel.focus();
      }
      melden("Abgelesen. Schau bitte nach, ob alles stimmt, und ändere es sonst.", false);
      if (typeof window.zumChatende === "function") { window.zumChatende(true); }
    }).catch(function () {
      knopf.disabled = false;
      melden("Das Foto ist nicht angekommen. Probier es noch einmal.", true);
    });
  }

  /* --- Verdrahtung ------------------------------------------------------- */

  if (zuschnittDa) {
    rahmen.addEventListener("keydown", aufTaste);
    schicht.addEventListener("keydown", aufSchichtTaste);

    rahmen.addEventListener("pointerdown", function (ereignis) {
      // Die Greifecken melden sich selbst; ihr Ziehen darf nicht zum
      // Verschieben des ganzen Rahmens werden.
      if (ereignis.target !== rahmen) { return; }
      zugBeginnen(ereignis, "verschieben");
    });

    var ecken = rahmen.querySelectorAll(".zuschnitt-griff");
    for (var i = 0; i < ecken.length; i++) {
      (function (ecke) {
        ecke.addEventListener("pointerdown", function (ereignis) {
          zugBeginnen(ereignis, ecke.dataset.ecke);
        });
      })(ecken[i]);
    }

    /* Neben dem Rahmen laesst sich auf dem Foto ein neuer aufziehen. Das ist
     * der Griff, den die meisten von selbst probieren. */
    flaeche.addEventListener("pointerdown", function (ereignis) {
      if (rahmen.contains(ereignis.target)) { return; }
      var kasten = flaeche.getBoundingClientRect();
      zugBeginnen(ereignis, "neu");
      if (zug) {
        zug.ortX = ereignis.clientX - kasten.left;
        zug.ortY = ereignis.clientY - kasten.top;
      }
    });

    knopfFertig.addEventListener("click", function () {
      if (!quelle) { return; }
      var breit = quelle.width / anzeige.breite;
      var hoch = quelle.height / anzeige.hoehe;
      var bild = ausschnitt(wahl.x * breit, wahl.y * hoch,
                            wahl.b * breit, wahl.h * hoch);
      schliessen();
      absenden(bild);
    });

    knopfGanz.addEventListener("click", function () {
      if (!quelle) { return; }
      var bild = ausschnitt(0, 0, quelle.width, quelle.height);
      schliessen();
      absenden(bild);
    });

    knopfWeg.addEventListener("click", abbrechen);
  }

  knopf.addEventListener("click", function () { eingabe.click(); });

  eingabe.addEventListener("change", function () {
    var datei = eingabe.files && eingabe.files[0];
    if (!datei) { return; }
    /* Gleich leeren: Wer den Zuschnitt abbricht, soll dasselbe Foto noch
     * einmal waehlen koennen. Sonst meldet der Browser keine Aenderung mehr.
     * Die Datei selbst ist schon in der Hand. */
    eingabe.value = "";

    knopf.disabled = true;
    melden("Das Foto wird vorbereitet …", false);

    vorbereiten(datei).then(function (leinwand) {
      if (!zuschnittDa || !schichtTraegt()) {
        quelle = leinwand;
        var ganz = ausschnitt(0, 0, leinwand.width, leinwand.height);
        quelle = null;
        absenden(ganz);
        return;
      }
      melden("", false);
      oeffnen(leinwand);
    }).catch(function () {
      knopf.disabled = false;
      melden("Das Foto ließ sich nicht öffnen. Probier es noch einmal.", true);
    });
  });
})();
