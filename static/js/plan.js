/* Die Tagesplanung auf dem Spark: Schieberegler, Plus und Minus, und vor
 * allem die Lagemeldung.
 *
 * Alles hier ist eine Zugabe. Die Seite funktioniert ohne dieses Skript:
 * Der Balken ist vom Server gezeichnet, die Konzepte sind gewoehnliche
 * Auswahlknoepfe, die Zeiten stehen in zwei gewoehnlichen Zeitfeldern, und
 * geprueft wird beim Absenden ohnehin noch einmal. Die Regler und die
 * Plus-Minus-Knoepfe stehen im HTML deshalb auf hidden; sie werden erst hier
 * eingeblendet. Ein Regler, der nichts tut, ist schlimmer als keiner.
 *
 * Die eigentliche Aufgabe ist die Lagemeldung. Wer einen Zeitraum waehlt,
 * will eine einzige Auskunft: Passt meine Klasse da noch hinein? Die Antwort
 * steckt schon in der Seite - in jeder Viertelstundenzelle des Rasters steht,
 * wie viele Plaetze dort frei sind und welche Konzepte dort laufen. Dieses
 * Skript liest sie aus dem DOM und rechnet im Browser; es fragt den Server
 * nicht.
 *
 * Seit den Nutzungskonzepten hat die Frage zwei Teile. Plaetze addieren
 * sich, Modelle nicht: Zwei Klassen im Unterricht teilen den Rechner, eine
 * Modellschulung belegt ihn allein. Die Lage prueft darum zuerst, ob das
 * gewaehlte Konzept neben dem laufen KANN, was schon gebucht ist, und erst
 * dann, ob die Plaetze reichen. Die Saetze dazu entsprechen denen in
 * plan/konzepte.py; was zaehlt, ist der Satz des Servers.
 *
 * Gerechnet wird durchgaengig in Minuten seit Mitternacht. Die Regler tragen
 * diese Minuten unmittelbar als Wert (420 ist 07:00, 1140 ist 19:00), damit
 * nirgends umgerechnet werden muss.
 */
(function () {
  "use strict";

  /* Diese drei Werte sind Vorgabe und werden gleich aus dem gezeichneten
     Raster nachgezogen: Was auf dem Schirm steht, ist die Wahrheit, nicht eine
     Zahl in diesem Skript. */
  var RASTER_VON = 420;    /* 07:00 */
  var RASTER_BIS = 1140;   /* 19:00 */
  var SCHRITT = 15;

  var form = document.getElementById("plan-form");
  var balken = document.getElementById("plan-balken");
  if (!balken) { return; }

  /* --- Zeit in Minuten und zurueck -------------------------------------- */

  function minuten(text) {
    if (!text) { return null; }
    var teile = String(text).split(":");
    if (teile.length < 2) { return null; }
    var stunde = parseInt(teile[0], 10);
    var minute = parseInt(teile[1], 10);
    if (isNaN(stunde) || isNaN(minute)) { return null; }
    return stunde * 60 + minute;
  }

  function zweistellig(zahl) { return (zahl < 10 ? "0" : "") + zahl; }

  function uhrzeit(gesamt) {
    return zweistellig(Math.floor(gesamt / 60)) + ":" + zweistellig(gesamt % 60);
  }

  function plaetzeWort(anzahl) {
    return anzahl + (anzahl === 1 ? " Platz" : " Plätze");
  }

  /* --- Die Konzepte kennen ---------------------------------------------- */

  /* Alle Konzepte, nicht nur die waehlbaren: Im Balken kann eine
     Modellschulung des Labs liegen, und die Lage soll sagen koennen, was das
     ist. Die Vorlage legt sie mit json_script ab. */
  var KONZEPTE = {};
  (function () {
    var knoten = document.getElementById("plan-konzepte-daten");
    var liste, i;
    if (!knoten) { return; }
    try { liste = JSON.parse(knoten.textContent); } catch (fehler) { return; }
    for (i = 0; i < liste.length; i++) {
      if (liste[i] && liste[i].schluessel) { KONZEPTE[liste[i].schluessel] = liste[i]; }
    }
  })();

  function istAlleinig(schluessel) {
    return !!(KONZEPTE[schluessel] && KONZEPTE[schluessel].alleinig);
  }

  function brauchtUmbau(schluessel) {
    return !!(KONZEPTE[schluessel] && KONZEPTE[schluessel].umbau);
  }

  function konzeptName(schluessel) {
    return KONZEPTE[schluessel] ? KONZEPTE[schluessel].name : schluessel;
  }

  /* Dieselbe Regel wie konzepte.vertraeglich: Dasselbe Konzept zweimal geht,
     es sei denn, es belegt den Rechner allein; zwei verschiedene gehen, wenn
     keines von beiden allein belegt. */
  function vertraeglich(einer, anderer) {
    if (!KONZEPTE[einer] || !KONZEPTE[anderer]) { return false; }
    if (einer === anderer) { return !istAlleinig(einer); }
    if (istAlleinig(einer) || istAlleinig(anderer)) { return false; }
    return true;
  }

  /* Dieselben Saetze wie konzepte.grund_unvertraeglich. Ein Konzept, das
     allein belegt, ohne umzubauen, nimmt den ganzen Anteil - das ist der
     dritte Fall. */
  function grundUnvertraeglich(neuer, bestehender, zeit) {
    if (brauchtUmbau(neuer)) {
      return "„" + konzeptName(neuer) + "“ braucht ein Modell, das erst geladen " +
        "werden muss. In dieser Zeit kann sonst nichts laufen, und um " + zeit +
        " ist „" + konzeptName(bestehender) + "“ gebucht.";
    }
    if (brauchtUmbau(bestehender)) {
      return "Um " + zeit + " ist „" + konzeptName(bestehender) + "“ gebucht. " +
        "Dafür wird der Rechner umgebaut, deshalb geht daneben nichts.";
    }
    if (istAlleinig(bestehender)) {
      return "Um " + zeit + " ist „" + konzeptName(bestehender) + "“ gebucht " +
        "und belegt den Rechner ganz.";
    }
    return "„" + konzeptName(neuer) + "“ belegt den Rechner ganz, und um " + zeit +
      " ist schon „" + konzeptName(bestehender) + "“ gebucht.";
  }

  /* --- Das Raster aus der Seite lesen ----------------------------------- */

  /* Jede Zelle traegt ihre Uhrzeit, ihre freien Plaetze und die Konzepte,
     die in ihr laufen, als data-Attribute. Das erspart einen zweiten
     Datenweg: Was gezeichnet ist, ist auch das, womit gerechnet wird. */
  var zellen = [];
  (function () {
    var knoten = balken.querySelectorAll(".plan-zelle");
    var schritt = parseInt(balken.getAttribute("data-schritt"), 10);
    var i, zeit, frei, roh, konzepte;
    if (!isNaN(schritt) && schritt > 0) { SCHRITT = schritt; }
    for (i = 0; i < knoten.length; i++) {
      zeit = minuten(knoten[i].getAttribute("data-zeit"));
      frei = parseInt(knoten[i].getAttribute("data-frei"), 10);
      if (zeit === null || isNaN(frei)) { continue; }
      roh = knoten[i].getAttribute("data-konzepte") || "";
      konzepte = roh ? roh.split(",") : [];
      zellen.push({ zeit: zeit, frei: frei, konzepte: konzepte });
    }
    if (zellen.length) {
      RASTER_VON = zellen[0].zeit;
      RASTER_BIS = zellen[zellen.length - 1].zeit + SCHRITT;
    }
  })();

  /* Eine Buchung von 10:00 bis 10:50 beruehrt die Viertelstunden 10:00, 10:15,
     10:30 und 10:45: Die letzte ist nur teilweise belegt, aber ein Platz laesst
     sich nicht halb vergeben. Frei ist darum, was in der engsten dieser
     Viertelstunden noch frei ist. */
  function freiImZeitraum(von, bis) {
    var engste = null;
    var i;
    for (i = 0; i < zellen.length; i++) {
      if (zellen[i].zeit >= von && zellen[i].zeit < bis) {
        if (engste === null || zellen[i].frei < engste) { engste = zellen[i].frei; }
      }
    }
    return engste;
  }

  /* Die erste Viertelstunde im Zeitraum, in der etwas laeuft, das sich mit
     dem gewaehlten Konzept nicht vertraegt - oder null. Das ist die Frage,
     die es vor den Konzepten nicht gab: Auch bei zwei belegten Plaetzen von
     hundertzwanzig kann die Antwort "nein" sein. */
  function konfliktImZeitraum(von, bis, konzept) {
    var i, j;
    for (i = 0; i < zellen.length; i++) {
      if (zellen[i].zeit < von || zellen[i].zeit >= bis) { continue; }
      for (j = 0; j < zellen[i].konzepte.length; j++) {
        if (!vertraeglich(konzept, zellen[i].konzepte[j])) {
          return { zeit: zellen[i].zeit, konzept: zellen[i].konzepte[j] };
        }
      }
    }
    return null;
  }

  /* --- Ueberschneidende Buchungen auf Spuren verteilen ------------------ */

  /* Zwei Buchungen zur selben Zeit sind kein Fehler, sondern der Normalfall
     dieses Werkzeugs: Reserviert wird ein Anteil, nicht die Maschine. Damit
     sie sich im Balken nicht verdecken, bekommt jede Kette sich
     ueberschneidender Bloecke so viele Spuren, wie sie braucht.
     An das CSS gehen nur zwei Zahlen: die Spur und 1 geteilt durch die Zahl
     der Spuren. Das Teilen hier und nicht im calc() zu machen, haelt die
     CSS-Regel auf einer Multiplikation, die jeder Browser kann. */
  function gruppeVerteilen(gruppe) {
    if (!gruppe.length) { return; }
    var enden = [];
    var i, spur, breite;
    for (i = 0; i < gruppe.length; i++) {
      spur = 0;
      while (spur < enden.length && enden[spur] > gruppe[i].von) { spur++; }
      enden[spur] = gruppe[i].bis;
      gruppe[i].spur = spur;
    }
    breite = (1 / enden.length).toFixed(4);
    for (i = 0; i < gruppe.length; i++) {
      gruppe[i].knoten.style.setProperty("--spur", String(gruppe[i].spur));
      gruppe[i].knoten.style.setProperty("--spurbreite", breite);
    }
  }

  (function spurenVerteilen() {
    var knoten = balken.querySelectorAll(".plan-block");
    var liste = [];
    var i, von, bis;
    for (i = 0; i < knoten.length; i++) {
      von = minuten(knoten[i].getAttribute("data-von"));
      bis = minuten(knoten[i].getAttribute("data-bis"));
      if (von === null || bis === null || bis <= von) { continue; }
      liste.push({ knoten: knoten[i], von: von, bis: bis });
    }
    liste.sort(function (a, b) { return a.von - b.von; });

    var gruppe = [];
    var gruppeEnde = -1;
    for (i = 0; i < liste.length; i++) {
      /* Eine neue Kette beginnt, sobald ein Block spaeter anfaengt, als alles
         Vorherige endet. Nur innerhalb einer Kette teilen sich die Bloecke die
         Breite, sonst wuerden alle Bloecke des Tages schmal. */
      if (gruppe.length && liste[i].von >= gruppeEnde) {
        gruppeVerteilen(gruppe);
        gruppe = [];
        gruppeEnde = -1;
      }
      gruppe.push(liste[i]);
      if (liste[i].bis > gruppeEnde) { gruppeEnde = liste[i].bis; }
    }
    gruppeVerteilen(gruppe);
  })();

  /* Ohne Formular ist hier Schluss: Wer nicht buchen darf, sieht nur den
     Balken, und der ist jetzt fertig. */
  if (!form) { return; }

  /* --- Die Teile des Formulars ----------------------------------------- */

  var reglerfeld = document.getElementById("plan-regler");
  var vonRegler = document.getElementById("von");
  var bisRegler = document.getElementById("bis");
  var vonZeit = document.getElementById("von-zeit");
  var bisZeit = document.getElementById("bis-zeit");
  var plaetzeFeld = document.getElementById("plaetze");
  var plaetzeWortKnoten = document.getElementById("plaetze-wort");
  var plaetzeHilfe = document.getElementById("plaetze-hilfe");
  var weniger = document.getElementById("plaetze-weniger");
  var mehr = document.getElementById("plaetze-mehr");
  var deutung = document.getElementById("plaetze-deutung");
  var unterricht = document.getElementById("plan-unterricht");
  var alleinigHinweis = document.getElementById("plan-alleinig");
  var lage = document.getElementById("plan-lage");
  var wahl = document.getElementById("plan-wahl");
  var senden = document.getElementById("senden");
  var konzeptKnoepfe = form.querySelectorAll('input[name="konzept"]');

  if (!vonZeit || !bisZeit || !plaetzeFeld) { return; }

  function zahlAus(knoten, name, ersatz) {
    var wert = parseInt(knoten.getAttribute(name), 10);
    return isNaN(wert) ? ersatz : wert;
  }

  var maxMinuten = zahlAus(form, "data-max-minuten", RASTER_BIS - RASTER_VON);
  var maxPlaetze = zahlAus(form, "data-max-plaetze", 1);
  var plaetzeGesamt = zahlAus(form, "data-plaetze-gesamt", 0);
  var gesperrt = false;

  /* Was das gewaehlte Konzept fuer das Zahlenfeld bedeutet. Die Werte
     kommen aus den data-Attributen des gewaehlten Knopfs und werden bei
     jedem Wechsel neu gesetzt. */
  var konzept = {
    schluessel: "",
    name: "",
    schritt: 1,
    max: maxPlaetze,
    vorgabe: maxPlaetze,
    alleinig: false,
    schuelerzahl: false
  };

  /* --- Was eine Zahl von Plaetzen bedeutet ----------------------------- */

  /* Eine nackte Zahl sagt niemandem, ob er zu viel oder zu wenig nimmt.
     Die Uebersetzung tut es. Beim Unterricht zaehlt das Feld Kinder, nicht
     Plaetze, und eine Klasse hat um die dreissig. */
  function deutungText(anzahl) {
    var satz;
    if (konzept.schuelerzahl) {
      if (anzahl <= 10) { satz = anzahl + " Schülerinnen und Schüler – eine Lerngruppe"; }
      else if (anzahl <= 30) { satz = anzahl + " Schülerinnen und Schüler – eine Klasse"; }
      else if (anzahl <= 60) { satz = anzahl + " Schülerinnen und Schüler – zwei Klassen"; }
      else { satz = anzahl + " Schülerinnen und Schüler – mehrere Klassen"; }
    } else if (anzahl <= 1) { satz = "ein Platz – Sie allein"; }
    else if (anzahl === 2) { satz = "zwei Plätze – Sie und eine weitere Person"; }
    else if (anzahl <= 6) { satz = anzahl + " Plätze – eine Kleingruppe"; }
    else if (anzahl <= 14) { satz = anzahl + " Plätze – eine Lerngruppe"; }
    else if (anzahl <= 20) { satz = anzahl + " Plätze – eine halbe Klasse"; }
    else if (anzahl <= 30) { satz = anzahl + " Plätze – eine ganze Klasse"; }
    else { satz = anzahl + " Plätze – mehr als eine Klasse"; }
    if (konzept.max > 0) {
      satz += " (höchstens " + konzept.max + ")";
    }
    return satz;
  }

  /* --- Die Lage ------------------------------------------------------- */

  function sperren(an) {
    gesperrt = an;
    if (senden) { senden.disabled = an; }
    if (lage) {
      if (an) { lage.className = "plan-lage ist-eng"; }
      else { lage.className = "plan-lage"; }
    }
  }

  function lageSchreiben(von, bis, anzahl) {
    if (!lage) { return; }
    var dauer = bis - von;
    var kopf;
    var frei;
    var konflikt;

    if (von === null || bis === null) {
      lage.textContent = "Bitte geben Sie Beginn und Ende an.";
      sperren(true);
      return;
    }
    if (dauer <= 0) {
      lage.textContent = "Das Ende muss nach dem Beginn liegen.";
      sperren(true);
      return;
    }

    kopf = uhrzeit(von) + " bis " + uhrzeit(bis) + ", " + dauer + " Minuten. ";

    if (von < RASTER_VON || bis > RASTER_BIS) {
      lage.textContent = kopf + "Gebucht werden kann nur zwischen " +
        uhrzeit(RASTER_VON) + " und " + uhrzeit(RASTER_BIS) + " Uhr.";
      sperren(true);
      return;
    }
    if (dauer > maxMinuten) {
      lage.textContent = kopf + "Eine Buchung darf bei Ihnen höchstens " +
        maxMinuten + " Minuten dauern.";
      sperren(true);
      return;
    }
    if (isNaN(anzahl) || anzahl < 1) {
      lage.textContent = kopf + "Bitte geben Sie an, wie viele Plätze Sie brauchen.";
      sperren(true);
      return;
    }
    if (konzept.schritt > 1 && anzahl % konzept.schritt !== 0) {
      lage.textContent = kopf + "„" + konzept.name + "“ wird in Schritten von " +
        konzept.schritt + " gebucht: " + konzept.schritt + ", " +
        (2 * konzept.schritt) + ", " + (3 * konzept.schritt) + " und so weiter.";
      sperren(true);
      return;
    }
    if (anzahl > konzept.max) {
      lage.textContent = kopf + "Für „" + konzept.name + "“ sind bei Ihnen höchstens " +
        konzept.max + " auf einmal möglich.";
      sperren(true);
      return;
    }

    /* Erst die Vertraeglichkeit, dann die Plaetze: Eine Modellschulung
       neben einer Schulklasse scheitert nicht an "null Plaetze frei",
       sondern daran, dass der Rechner umgebaut wuerde. */
    konflikt = konfliktImZeitraum(von, bis, konzept.schluessel);
    if (konflikt) {
      lage.textContent = kopf +
        grundUnvertraeglich(konzept.schluessel, konflikt.konzept, uhrzeit(konflikt.zeit));
      sperren(true);
      return;
    }

    if (konzept.alleinig) {
      /* Kein Konflikt heisst hier: Es laeuft nichts. Die Plaetze zu zaehlen
         waere sinnlos, es werden ohnehin alle. */
      lage.textContent = kopf + "In diesem Zeitraum läuft nichts. „" + konzept.name +
        "“ belegt den Rechner ganz – niemand sonst kann dann buchen oder arbeiten.";
      sperren(false);
      return;
    }

    frei = freiImZeitraum(von, bis);
    if (frei === null) {
      lage.textContent = kopf + "Für diesen Zeitraum liegt keine Auskunft vor.";
      sperren(true);
      return;
    }
    if (frei < anzahl) {
      lage.textContent = kopf + "Hier sind nur noch " + frei + " von " +
        plaetzeGesamt + " Plätzen frei, Sie brauchen " + anzahl +
        ". Wählen Sie eine andere Zeit oder weniger Plätze.";
      sperren(true);
      return;
    }

    /* Der zweite Satz ist der wichtige: Er sagt, dass die Buchung niemanden
       aussperrt. */
    lage.textContent = kopf + "In diesem Zeitraum sind noch " + frei + " von " +
      plaetzeGesamt + " Plätzen frei. Ihre " + plaetzeWort(anzahl) +
      " passen; danach bleiben " + (frei - anzahl) + " für andere.";
    sperren(false);
  }

  /* --- Anzeige nachziehen --------------------------------------------- */

  function reglerText(regler) {
    if (!regler) { return; }
    var wert = parseInt(regler.value, 10);
    if (isNaN(wert)) { return; }
    regler.setAttribute("aria-valuetext", uhrzeit(wert) + " Uhr");
  }

  function wahlZeichnen(von, bis) {
    if (!wahl) { return; }
    if (von === null || bis === null || bis <= von) {
      wahl.hidden = true;
      return;
    }
    wahl.hidden = false;
    /* Die Vorlage und das CSS rechnen in Minuten ab 07:00. */
    wahl.style.setProperty("--von-min", String(Math.max(0, von - RASTER_VON)));
    wahl.style.setProperty("--dauer-min", String(bis - von));
  }

  function aktualisieren() {
    /* Die Zeitfelder sind die Wahrheit, denn nur sie werden gesendet. Der
       Regler springt ein, wenn ein Feld leer ist. */
    var von = minuten(vonZeit.value);
    var bis = minuten(bisZeit.value);
    if (von === null && vonRegler) { von = parseInt(vonRegler.value, 10); }
    if (bis === null && bisRegler) { bis = parseInt(bisRegler.value, 10); }
    /* Ein halb getipptes Zeitfeld liefert nichts Brauchbares; daraus wird
       wieder "keine Angabe", sonst stuende "NaN:NaN" in der Lagemeldung. */
    if (isNaN(von)) { von = null; }
    if (isNaN(bis)) { bis = null; }
    var anzahl = parseInt(plaetzeFeld.value, 10);

    reglerText(vonRegler);
    reglerText(bisRegler);
    if (deutung && !isNaN(anzahl)) { deutung.textContent = deutungText(anzahl); }
    wahlZeichnen(von, bis);
    lageSchreiben(von, bis, anzahl);
  }

  /* --- Das Konzept ---------------------------------------------------- */

  function gewaehlterKnopf() {
    var i;
    for (i = 0; i < konzeptKnoepfe.length; i++) {
      if (konzeptKnoepfe[i].checked) { return konzeptKnoepfe[i]; }
    }
    return konzeptKnoepfe.length ? konzeptKnoepfe[0] : null;
  }

  /* Auf einen gueltigen Wert bringen: ein Vielfaches des Schritts zwischen
     dem Schritt und dem Hoechstmass. 25 wird beim Unterricht zu 30 - wer
     fuenfundzwanzig Kinder hat, braucht die naechsten zehn, nicht die
     vorigen. */
  function einrasten(anzahl) {
    var schritt = konzept.schritt || 1;
    var wert = Math.ceil(anzahl / schritt) * schritt;
    return Math.max(schritt, Math.min(konzept.max, wert));
  }

  /* Alles, was am Formular vom Konzept abhaengt, in einem Zug: das
     Zahlenfeld (Schritt, Grenzen, Beschriftung, Hilfe), der Block mit Fach
     und Person, der Hinweis "belegt den Rechner ganz", der Knopf, und die
     Markierung der Karten. `neu` heisst: Die Lehrperson hat gerade
     gewechselt, dann bekommt das Feld die Voreinstellung des Konzepts. Beim
     Laden bleibt stehen, was der Server eingetragen hat - nach einer
     abgewiesenen Buchung ist das die eigene Eingabe. */
  function konzeptAnwenden(knoten, neu) {
    var i, label, eigenes;
    if (!knoten) { return; }
    konzept.schluessel = knoten.value;
    konzept.name = knoten.getAttribute("data-name") || konzeptName(knoten.value);
    konzept.schritt = zahlAus(knoten, "data-schritt", 1);
    konzept.max = zahlAus(knoten, "data-max", maxPlaetze);
    konzept.vorgabe = zahlAus(knoten, "data-vorgabe", konzept.max);
    konzept.alleinig = knoten.getAttribute("data-alleinig") === "1";
    konzept.schuelerzahl = knoten.getAttribute("data-schuelerzahl") === "1";

    plaetzeFeld.step = String(konzept.schritt);
    plaetzeFeld.min = String(konzept.schritt);
    plaetzeFeld.max = String(konzept.max);
    if (plaetzeWortKnoten) {
      plaetzeWortKnoten.textContent = knoten.getAttribute("data-plaetze-wort") || "Plätze";
    }
    if (plaetzeHilfe) {
      plaetzeHilfe.textContent = knoten.getAttribute("data-plaetze-hilfe") || "";
    }
    if (weniger) { weniger.setAttribute("aria-label", konzept.schritt + " weniger"); }
    if (mehr) { mehr.setAttribute("aria-label", konzept.schritt + " mehr"); }
    if (unterricht) { unterricht.hidden = !konzept.schuelerzahl; }
    if (alleinigHinweis) {
      /* Ohne Symbol: Das war ein Emoji, und die Symbole sind jetzt
         Zeichnungen in der Vorlage, die das Skript nicht nachbaut. Der Satz
         sagt ohnehin, worum es geht. */
      alleinigHinweis.hidden = !konzept.alleinig;
    }
    if (senden) {
      senden.textContent = konzept.alleinig ? "Rechner reservieren" : "Plätze reservieren";
    }

    for (i = 0; i < konzeptKnoepfe.length; i++) {
      label = konzeptKnoepfe[i].parentNode;
      eigenes = konzeptKnoepfe[i] === knoten;
      if (label && label.classList) { label.classList.toggle("ist-gewaehlt", eigenes); }
    }

    /* Beim Laden bleibt der Wert, wie er ist - auch ein abgewiesener wie
       25. Die Lage sagt dann, was daran nicht passt, und der naechste Druck
       auf Plus oder Minus rastet ein. Ein Feld, das sich beim Laden still
       umschreibt, widerspraeche der Fehlermeldung darueber. */
    if (neu) {
      plaetzeFeld.value = String(einrasten(konzept.vorgabe));
    }
    aktualisieren();
  }

  (function () {
    var i;
    for (i = 0; i < konzeptKnoepfe.length; i++) {
      konzeptKnoepfe[i].addEventListener("change", function (ereignis) {
        if (ereignis.target.checked) { konzeptAnwenden(ereignis.target, true); }
      });
    }
  })();

  /* --- Die Regler ----------------------------------------------------- */

  /* Der Beginn wird auf das Viertel davor gelegt, das Ende auf das danach: So
     zeigt der Regler nie eine kuerzere Spanne, als in den Feldern steht. */
  function abwaerts(wert) { return Math.floor(wert / SCHRITT) * SCHRITT; }
  function aufwaerts(wert) { return Math.ceil(wert / SCHRITT) * SCHRITT; }

  function begrenzen(wert, unten, oben) {
    return Math.max(unten, Math.min(oben, wert));
  }

  /* Wer den einen Regler ueber den anderen schiebt, schiebt den anderen mit;
     eine Viertelstunde bleibt immer dazwischen, denn eine Buchung von null
     Minuten gibt es nicht. */
  function ausRegler(welcher) {
    if (!vonRegler || !bisRegler) { return; }
    var von = parseInt(vonRegler.value, 10);
    var bis = parseInt(bisRegler.value, 10);
    var geschoben = false;
    if (isNaN(von) || isNaN(bis)) { return; }

    if (welcher === "von" && bis <= von) {
      bis = begrenzen(von + SCHRITT, RASTER_VON + SCHRITT, RASTER_BIS);
      von = Math.min(von, bis - SCHRITT);
      geschoben = true;
    } else if (welcher === "bis" && von >= bis) {
      von = begrenzen(bis - SCHRITT, RASTER_VON, RASTER_BIS - SCHRITT);
      bis = Math.max(bis, von + SCHRITT);
      geschoben = true;
    }
    if (geschoben) {
      vonRegler.value = String(von);
      bisRegler.value = String(bis);
    }

    /* Nur das Feld des bewegten Reglers wird geschrieben. Wer den Beginn
       schiebt, soll nicht nebenbei ein genaues Ende von 10:50 verlieren, denn
       der Regler kennt nur Viertelstunden. Beim Mitschieben geht es nicht
       anders, dann ist das Mitschieben ja die Absicht. */
    if (welcher === "von" || geschoben) { vonZeit.value = uhrzeit(von); }
    if (welcher === "bis" || geschoben) { bisZeit.value = uhrzeit(bis); }
    aktualisieren();
  }

  /* Umgekehrt zieht ein Zeitfeld den Regler nur nach, ohne zurueckzuschreiben:
     Eine Unterrichtsstunde endet um 10:50, und wuerde das Feld auf das
     naechste Viertel gerundet, waere die genaue Eingabe sofort wieder weg. */
  function ausZeit() {
    var von = minuten(vonZeit.value);
    var bis = minuten(bisZeit.value);
    if (vonRegler && von !== null) {
      vonRegler.value = String(begrenzen(abwaerts(von), RASTER_VON, RASTER_BIS - SCHRITT));
    }
    if (bisRegler && bis !== null) {
      bisRegler.value = String(begrenzen(aufwaerts(bis), RASTER_VON + SCHRITT, RASTER_BIS));
    }
    aktualisieren();
  }

  if (vonRegler && bisRegler && reglerfeld) {
    reglerfeld.hidden = false;
    vonRegler.addEventListener("input", function () { ausRegler("von"); });
    vonRegler.addEventListener("change", function () { ausRegler("von"); });
    bisRegler.addEventListener("input", function () { ausRegler("bis"); });
    bisRegler.addEventListener("change", function () { ausRegler("bis"); });
    /* Die Regler auf die Werte der Zeitfelder stellen, bevor jemand sie
       anfasst. */
    ausZeit();
  }

  vonZeit.addEventListener("input", ausZeit);
  vonZeit.addEventListener("change", ausZeit);
  bisZeit.addEventListener("input", ausZeit);
  bisZeit.addEventListener("change", ausZeit);

  /* --- Plaetze -------------------------------------------------------- */

  function plaetzeSetzen(anzahl) {
    plaetzeFeld.value = String(einrasten(anzahl));
    aktualisieren();
  }

  /* Plus und Minus springen um den Schritt des Konzepts: beim Unterricht um
     zehn, sonst um eins. Von einem getippten Zwischenwert aus geht es auf
     das naechste Vielfache in der gewuenschten Richtung: 25 und Plus ist 30,
     25 und Minus ist 20. */
  if (weniger && mehr) {
    weniger.hidden = false;
    mehr.hidden = false;
    weniger.addEventListener("click", function () {
      var jetzt = parseInt(plaetzeFeld.value, 10) || konzept.schritt;
      plaetzeSetzen(Math.ceil(jetzt / konzept.schritt) * konzept.schritt - konzept.schritt);
    });
    mehr.addEventListener("click", function () {
      var jetzt = parseInt(plaetzeFeld.value, 10) || 0;
      plaetzeSetzen(Math.floor(jetzt / konzept.schritt) * konzept.schritt + konzept.schritt);
    });
  }

  plaetzeFeld.addEventListener("input", aktualisieren);
  plaetzeFeld.addEventListener("change", aktualisieren);

  /* --- Absenden ------------------------------------------------------- */

  /* Der Knopf ist gesperrt, aber die Eingabetaste in einem Textfeld kaeme
     daran vorbei. Der Server prueft ohnehin noch einmal; dies hier erspart
     nur den Weg hin und zurueck. */
  form.addEventListener("submit", function (ereignis) {
    if (gesperrt) {
      ereignis.preventDefault();
      if (lage && lage.scrollIntoView) { lage.scrollIntoView(); }
    }
  });

  /* Das Konzept zuerst, denn es setzt Schritt und Grenzen des Zahlenfelds;
     danach rechnet aktualisieren() mit den richtigen Werten. */
  konzeptAnwenden(gewaehlterKnopf(), false);
})();
