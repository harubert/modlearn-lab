/* Aufnehmen, was gesprochen wird, und vom Spark abschreiben lassen.
 *
 * Der Browser erzeugt die Datei selbst als WAV mit 16 kHz in mono. Das ist
 * kein Selbstzweck: Am Spark fehlt ffmpeg, und was ein Handy von sich aus
 * aufnimmt (meist 44,1 oder 48 kHz in Opus) waere dort nicht lesbar.
 *
 * Zwei Vorsichtsmassnahmen gegen bekannte Eigenheiten von Whisper:
 * Aufnahmen unter einer halben Sekunde werden verworfen, und bei Stille
 * wird gar nichts erst abgeschickt. Whisper erfindet bei Stille gern ganze
 * Saetze, typischerweise Untertitel-Floskeln.
 *
 * Die Spracherkennung laeuft auf dem Rechner der Hochschule. Die
 * Spracherkennung des Browsers waere der bequeme Weg, schickt die Aufnahme
 * aber an Google oder Apple, und das waere das Gegenteil dessen, was diese
 * Anwendung verspricht.
 *
 * Dazu die sichtbare Seite: die Tafel aus _aufnahme.html mit Pegel, Dauer
 * und drei Knoepfen. Sie ist keine Zierde. Ein Kind, das nicht sieht, dass
 * etwas ankommt, spricht leiser und zoegernder und bricht ab, weil es die
 * Aufnahme fuer kaputt haelt; der Pegel ist die Antwort auf die Frage, ob
 * das Geraet ueberhaupt zuhoert. Pause ist der Ausweg fuer alle, die mitten
 * im Satz nachdenken muessen, ohne das schon Gesagte zu verlieren.
 *
 * Die Tafel darf fehlen: Ohne sie bleibt die Bedienung ueber den einen Knopf
 * "Sprechen" vollstaendig brauchbar. Am Endpunkt aendert sich nichts, es
 * geht dasselbe WAV an dieselbe Stelle.
 */
(function () {
  "use strict";

  var ABTASTRATE = 16000;
  var MINDESTDAUER = 0.5;     // Sekunden
  var STILLE_SCHWELLE = 0.01; // mittlerer Pegel, unter dem nichts gesendet wird
  var HOECHSTDAUER = 60;      // Sekunden, danach stoppt die Aufnahme selbst
  var WARNUNG_AB = 10;        // so viele Sekunden vor Schluss wird gewarnt

  var BALKEN = 12;            // Saeulen im Pegel
  var BALKEN_GRUND = 8;       // Ruhehoehe in Prozent, damit nichts verschwindet
  var RAHMEN_MS = 50;         // 20 Bilder je Sekunde genuegen fuer ruhige Balken
  var RAHMEN_RUHIG_MS = 400;  // bei prefers-reduced-motion nur alle 0,4 Sekunden

  var AUS = "aus", LAEUFT = "laeuft", PAUSE = "pause";

  var knopf = document.getElementById("sprachknopf");
  if (!knopf) { return; }

  var ziel = document.getElementById(knopf.dataset.ziel);
  var stand = document.getElementById("sprachstand");

  var tafel = document.getElementById("aufnahme");
  var satzfeld = document.getElementById("aufnahme-satz");
  var zeitfeld = document.getElementById("aufnahme-zeit");
  var grenzfeld = document.getElementById("aufnahme-grenze");
  var hinweisfeld = document.getElementById("aufnahme-hinweis");
  var pegelfeld = document.getElementById("aufnahme-pegel");
  var ruhefuellung = document.getElementById("aufnahme-ruhe-fuellung");
  var ruhewert = document.getElementById("aufnahme-ruhe-wert");
  var knopfAuf = document.getElementById("aufnahme-start");
  var wortAuf = document.getElementById("aufnahme-start-wort");
  var knopfPause = document.getElementById("aufnahme-pause");
  var knopfStopp = document.getElementById("aufnahme-stopp");

  var wenigBewegung = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : null;

  var kontext = null;
  var strom = null;
  var quelle = null;
  var verarbeiter = null;
  var analysator = null;
  var stummer = null;
  var stuecke = [];
  var probenzahl = 0;
  var zustand = AUS;
  var uhr = null;             // Wecker fuer die Hoechstdauer
  var takt = null;            // Sekundenzeiger
  var bild = null;            // laufendes requestAnimationFrame
  var grenzeAngesagt = false;

  var balken = [];
  var hoehen = [];
  var grenzen = null;
  var frequenzdaten = null;
  var zeitdaten = null;
  var letzteMessung = 0;
  var letzteAnzeige = 0;
  var ruhigWert = 0;

  function melden(text, istFehler) {
    if (!stand) { return; }
    stand.textContent = text;
    stand.hidden = !text;
    stand.classList.toggle("meldung-fehler", !!istFehler);
  }

  function csrfWert() {
    var treffer = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[2]) : "";
  }

  /* 16-bit-PCM in einem WAV-Kopf. Whisper liest das ohne Umwege. */
  function alsWav(proben, rate) {
    var puffer = new ArrayBuffer(44 + proben.length * 2);
    var sicht = new DataView(puffer);

    function text(pos, wert) {
      for (var i = 0; i < wert.length; i++) {
        sicht.setUint8(pos + i, wert.charCodeAt(i));
      }
    }

    text(0, "RIFF");
    sicht.setUint32(4, 36 + proben.length * 2, true);
    text(8, "WAVE");
    text(12, "fmt ");
    sicht.setUint32(16, 16, true);          // Laenge des Formatblocks
    sicht.setUint16(20, 1, true);           // PCM
    sicht.setUint16(22, 1, true);           // ein Kanal
    sicht.setUint32(24, rate, true);
    sicht.setUint32(28, rate * 2, true);    // Bytes je Sekunde
    sicht.setUint16(32, 2, true);           // Bytes je Probe
    sicht.setUint16(34, 16, true);          // Bits je Probe
    text(36, "data");
    sicht.setUint32(40, proben.length * 2, true);

    var pos = 44;
    for (var i = 0; i < proben.length; i++) {
      var wert = Math.max(-1, Math.min(1, proben[i]));
      sicht.setInt16(pos, wert < 0 ? wert * 0x8000 : wert * 0x7fff, true);
      pos += 2;
    }
    return new Blob([sicht], { type: "audio/wav" });
  }

  function zusammenfuegen(liste) {
    var gesamt = liste.reduce(function (summe, s) { return summe + s.length; }, 0);
    var alles = new Float32Array(gesamt);
    var pos = 0;
    liste.forEach(function (s) { alles.set(s, pos); pos += s.length; });
    return alles;
  }

  function mittlererPegel(proben) {
    var summe = 0;
    for (var i = 0; i < proben.length; i++) { summe += proben[i] * proben[i]; }
    return Math.sqrt(summe / (proben.length || 1));
  }

  /* --- Dauer ------------------------------------------------------------ */

  function abtastrate() {
    return kontext ? kontext.sampleRate : ABTASTRATE;
  }

  /* Gezaehlt wird, was wirklich aufgenommen wurde, nicht die Zeit an der
   * Wand. Wer zwischendurch pausiert, soll die Pause nicht von seiner
   * Minute abgezogen bekommen. */
  function aufgenommeneSekunden() {
    return probenzahl / abtastrate();
  }

  function mmss(sekunden) {
    var ganz = Math.max(0, Math.floor(sekunden));
    var minuten = Math.floor(ganz / 60);
    var rest = ganz % 60;
    return (minuten < 10 ? "0" + minuten : minuten) + ":" +
           (rest < 10 ? "0" + rest : rest);
  }

  function ticken() {
    var gelaufen = aufgenommeneSekunden();
    if (zeitfeld) {
      var text = mmss(gelaufen);
      if (zeitfeld.textContent !== text) { zeitfeld.textContent = text; }
    }

    var rest = HOECHSTDAUER - gelaufen;
    if (rest <= WARNUNG_AB) {
      if (tafel) { tafel.classList.add("warnt"); }
      if (hinweisfeld) {
        var satz = "Noch " + Math.max(0, Math.ceil(rest)) + " Sekunden.";
        if (hinweisfeld.textContent !== satz) { hinweisfeld.textContent = satz; }
        hinweisfeld.hidden = false;
      }
      /* Nur einmal ansagen. Ein Vorlesewerkzeug, das jede Sekunde
       * dazwischenredet, uebertoent das Kind. */
      if (!grenzeAngesagt) {
        grenzeAngesagt = true;
        melden("Noch " + WARNUNG_AB + " Sekunden, dann ist die Aufnahme zu Ende.", false);
      }
    }

    if (gelaufen >= HOECHSTDAUER) { beenden(); }
  }

  function taktStarten() {
    if (takt) { clearInterval(takt); }
    takt = setInterval(ticken, 250);
    ticken();
  }

  /* Der Wecker ist nur die Rueckfallebene. Liegt das Blatt im Hintergrund,
   * bremst der Browser den Takt aus, und ohne den Wecker liefe die Aufnahme
   * ueber die Hoechstdauer hinaus. Eine Sekunde Zuschlag, damit im Normalfall
   * der Takt zuerst greift und die Anzeige auf der Grenze stehen bleibt. */
  function weckerStellen() {
    if (uhr) { clearTimeout(uhr); }
    var rest = HOECHSTDAUER - aufgenommeneSekunden();
    uhr = setTimeout(beenden, Math.max(500, (rest + 1) * 1000));
  }

  /* --- Pegel ------------------------------------------------------------ */

  /* Die Saeulen entstehen hier und nicht in der Vorlage: Ohne Skript koennte
   * sich nichts bewegen, und zwoelf leere Spans waeren in der Vorlage nur
   * Laerm. */
  function balkenAnlegen() {
    for (var i = 0; i < BALKEN; i++) {
      hoehen.push(0);
      if (!pegelfeld) { continue; }
      var saeule = document.createElement("span");
      saeule.className = "aufnahme-balken";
      saeule.style.height = BALKEN_GRUND + "%";
      pegelfeld.appendChild(saeule);
      balken.push(saeule);
    }
  }

  function ruhigGewuenscht() {
    return !!(wenigBewegung && wenigBewegung.matches);
  }

  /* Die Grenzen der Baender, einmal gerechnet. Nach oben werden sie immer
   * breiter: Die Stimme hat ihre Energie unten, gleich breite Baender
   * liessen die rechte Haelfte der Anzeige fast immer leer stehen. */
  function baenderRechnen() {
    var faecher = analysator.frequencyBinCount;
    var hertzJeFach = abtastrate() / analysator.fftSize;
    var unten = 1;
    var oben = Math.min(faecher - 1,
                        Math.max(BALKEN + 1, Math.round(4000 / hertzJeFach)));
    var liste = [unten];
    for (var i = 1; i <= BALKEN; i++) {
      var marke = Math.round(unten * Math.pow(oben / unten, i / BALKEN));
      if (marke <= liste[i - 1]) { marke = liste[i - 1] + 1; }
      liste.push(Math.min(marke, faecher));
    }
    return liste;
  }

  function messen(ruhig) {
    var i;
    if (ruhig) {
      /* Fuer die ruhige Anzeige genuegt ein Gesamtwert. Gemessen wird
       * trotzdem oft und angezeigt selten: Ein einzelner Blick auf 64
       * Millisekunden waere ein Zufallstreffer. */
      analysator.getByteTimeDomainData(zeitdaten);
      var summe = 0;
      for (i = 0; i < zeitdaten.length; i++) {
        var abstand = (zeitdaten[i] - 128) / 128;
        summe += abstand * abstand;
      }
      var laut = Math.min(1, Math.sqrt(summe / zeitdaten.length) * 4);
      ruhigWert = ruhigWert * 0.7 + laut * 0.3;
      return;
    }

    analysator.getByteFrequencyData(frequenzdaten);
    for (i = 0; i < BALKEN; i++) {
      var von = grenzen[i];
      var bis = Math.max(von + 1, grenzen[i + 1]);
      var teil = 0;
      for (var j = von; j < bis; j++) { teil += frequenzdaten[j]; }
      var hoehe = Math.min(1, (teil / (bis - von)) / 255 * 1.25);
      /* Schnell hinauf, langsam herunter. Ohne dieses Nachlaufen zittert die
       * Anzeige bei jedem Zischlaut, und ruhig soll sie sein. */
      hoehen[i] = Math.max(hoehe, hoehen[i] * 0.82);
    }
  }

  function anzeigen(ruhig) {
    var i;
    if (ruhig) {
      /* In Fuenferschritten: Eine Zahl, die um ein Prozent springt, ist
       * genau das Zappeln, das hier nicht sein soll. */
      var prozent = Math.round(ruhigWert * 20) * 5;
      if (ruhefuellung) { ruhefuellung.style.width = Math.max(3, prozent) + "%"; }
      if (ruhewert && ruhewert.textContent !== prozent + " %") {
        ruhewert.textContent = prozent + " %";
      }
      return;
    }
    for (i = 0; i < balken.length; i++) {
      balken[i].style.height =
        (BALKEN_GRUND + Math.round(hoehen[i] * (100 - BALKEN_GRUND))) + "%";
    }
  }

  function pegelFlachlegen() {
    for (var i = 0; i < balken.length; i++) {
      hoehen[i] = 0;
      balken[i].style.height = BALKEN_GRUND + "%";
    }
    ruhigWert = 0;
    if (ruhefuellung) { ruhefuellung.style.width = "3%"; }
    if (ruhewert) { ruhewert.textContent = "0 %"; }
  }

  function pegelRahmen(zeit) {
    if (zustand !== LAEUFT || !analysator) { bild = null; return; }
    bild = window.requestAnimationFrame(pegelRahmen);

    var ruhig = ruhigGewuenscht();
    if (zeit - letzteMessung >= RAHMEN_MS) {
      letzteMessung = zeit;
      messen(ruhig);
    }
    if (zeit - letzteAnzeige >= (ruhig ? RAHMEN_RUHIG_MS : RAHMEN_MS)) {
      letzteAnzeige = zeit;
      anzeigen(ruhig);
    }
  }

  function pegelStarten() {
    if (!analysator || !window.requestAnimationFrame) { return; }
    if (!balken.length && !ruhefuellung) { return; }   // nichts zu zeigen
    letzteMessung = 0;
    letzteAnzeige = 0;
    bild = window.requestAnimationFrame(pegelRahmen);
  }

  function pegelStoppen() {
    if (bild && window.cancelAnimationFrame) { window.cancelAnimationFrame(bild); }
    bild = null;
    pegelFlachlegen();
  }

  /* --- Anzeige ---------------------------------------------------------- */

  function grenzeSchreiben() {
    if (grenzfeld) { grenzfeld.textContent = mmss(HOECHSTDAUER); }
  }

  function tafelZeigen() {
    if (!tafel) { return; }
    tafel.hidden = (zustand === AUS);
    tafel.classList.toggle("pausiert", zustand === PAUSE);
    if (satzfeld) {
      satzfeld.textContent = (zustand === PAUSE)
        ? "Pause. Ich höre gerade nicht zu."
        : "Ich höre zu.";
    }
  }

  function knoepfeZeigen() {
    var nimmtAuf = (zustand === LAEUFT);
    if (knopfAuf) {
      knopfAuf.disabled = nimmtAuf;
      knopfAuf.classList.toggle("laeuft-gerade", nimmtAuf);
      /* Das sichtbare Wort steht im Namen. Ein aria-label ohne das sichtbare
       * Wort laesst eine Sprachsteuerung ins Leere greifen. */
      knopfAuf.setAttribute("aria-label",
        nimmtAuf ? "Läuft, die Aufnahme ist an" : "Weiter aufnehmen");
      if (wortAuf) { wortAuf.textContent = nimmtAuf ? "Läuft" : "Weiter"; }
    }
    if (knopfPause) { knopfPause.disabled = !nimmtAuf; }
    if (knopfStopp) { knopfStopp.disabled = (zustand === AUS); }
  }

  /* Ein Knopf, der unter dem Finger abgeschaltet wird, nimmt den Fokus mit
   * ins Nichts: Wer mit der Tastatur arbeitet, faengt danach wieder am
   * Seitenanfang an. Darum wandert der Fokus auf den Knopf, der jetzt an der
   * Reihe ist. */
  function fokusNachziehen(vorher) {
    if (zustand === AUS) { return; }   // die Tafel ist zu, beenden() uebernimmt
    if (!vorher || !vorher.disabled) { return; }
    if (vorher !== knopfAuf && vorher !== knopfPause && vorher !== knopfStopp) { return; }
    var reihe = [knopfPause, knopfAuf, knopfStopp];
    for (var i = 0; i < reihe.length; i++) {
      if (reihe[i] && !reihe[i].disabled) {
        try { reihe[i].focus(); } catch (e) { /* aeltere Browser */ }
        return;
      }
    }
  }

  function umschalten(neu) {
    var vorher = document.activeElement;
    zustand = neu;
    tafelZeigen();
    knoepfeZeigen();
    fokusNachziehen(vorher);
  }

  function imFokus() {
    var jetzt = document.activeElement;
    return !!(tafel && jetzt && tafel.contains(jetzt));
  }

  function fokusAuf(element) {
    if (!element) { return; }
    try { element.focus(); } catch (e) { /* aeltere Browser */ }
  }

  /* --- Aufnahme --------------------------------------------------------- */

  function spurenSchalten(an) {
    if (!strom) { return; }
    try {
      strom.getTracks().forEach(function (spur) { spur.enabled = !!an; });
    } catch (e) { /* aeltere Browser kennen enabled nicht */ }
  }

  function aufraeumen() {
    if (uhr) { clearTimeout(uhr); uhr = null; }
    if (takt) { clearInterval(takt); takt = null; }
    pegelStoppen();
    if (verarbeiter) { verarbeiter.disconnect(); verarbeiter = null; }
    if (analysator) { analysator.disconnect(); analysator = null; }
    if (stummer) { stummer.disconnect(); stummer = null; }
    if (quelle) { quelle.disconnect(); quelle = null; }
    if (strom) {
      strom.getTracks().forEach(function (spur) { spur.stop() ; });
      strom = null;
    }
    if (kontext && kontext.state !== "closed") { kontext.close(); }
    kontext = null;
    umschalten(AUS);
    knopf.disabled = false;
    knopf.setAttribute("aria-pressed", "false");
    knopf.classList.remove("nimmt-auf");
    if (tafel) { tafel.classList.remove("warnt"); }
    if (hinweisfeld) { hinweisfeld.hidden = true; hinweisfeld.textContent = ""; }
    if (zeitfeld) { zeitfeld.textContent = mmss(0); }
  }

  function starten() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      melden("Dieses Gerät lässt kein Aufnehmen zu. Tipp die Aufgabe bitte ein.", true);
      return;
    }
    knopf.disabled = true;
    melden("Das Mikrofon wird gefragt …", false);

    navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    }).then(function (erhalten) {
      strom = erhalten;
      try {
        kontext = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: ABTASTRATE
        });
      } catch (e) {
        kontext = new (window.AudioContext || window.webkitAudioContext)();
      }
      stuecke = [];
      probenzahl = 0;
      grenzeAngesagt = false;
      quelle = kontext.createMediaStreamSource(strom);
      verarbeiter = kontext.createScriptProcessor(4096, 1, 1);
      verarbeiter.onaudioprocess = function (ereignis) {
        if (zustand !== LAEUFT) { return; }
        var stueck = new Float32Array(ereignis.inputBuffer.getChannelData(0));
        stuecke.push(stueck);
        probenzahl += stueck.length;
      };
      quelle.connect(verarbeiter);
      verarbeiter.connect(kontext.destination);

      /* Der Analysator haengt am selben Strom wie die Aufnahme. Ein zweites
       * getUserMedia waere ein zweites Mikrofon: eine zweite Erlaubnisfrage
       * und auf manchen Geraeten ein Fehler, weil das Mikrofon belegt ist. */
      analysator = kontext.createAnalyser();
      analysator.fftSize = 1024;
      analysator.smoothingTimeConstant = 0.75;
      analysator.minDecibels = -85;   // hebt den Boden an, damit Raumrauschen
      analysator.maxDecibels = -25;   // die Anzeige nicht dauernd fuellt
      quelle.connect(analysator);

      /* Ein Ausgang mit Verstaerkung null. Manche Browser rechnen nur, was
       * bis zum Lautsprecher durchverbunden ist, und der Analysator bliebe
       * sonst stumm. Null, damit die eigene Stimme nicht zurueckkommt. */
      stummer = kontext.createGain();
      stummer.gain.value = 0;
      analysator.connect(stummer);
      stummer.connect(kontext.destination);

      frequenzdaten = new Uint8Array(analysator.frequencyBinCount);
      zeitdaten = new Uint8Array(analysator.fftSize);
      grenzen = baenderRechnen();

      knopf.setAttribute("aria-pressed", "true");
      knopf.classList.add("nimmt-auf");
      /* Der Knopf "Sprechen" bleibt abgeschaltet, solange die Tafel offen
       * ist: Sonst stehen zwei Bedienungen fuer dieselbe Aufnahme da. Ohne
       * Tafel bleibt er bedienbar und beendet die Aufnahme wie bisher. */
      if (!tafel) { knopf.disabled = false; }

      umschalten(LAEUFT);
      pegelStarten();
      taktStarten();
      weckerStellen();
      melden(tafel
        ? "Sprich jetzt. Mit Fertig schickst du es ab."
        : "Sprich jetzt. Zum Beenden noch einmal tippen.", false);

      if (tafel) {
        fokusAuf(tafel);
        /* Die Tafel macht den Eingabebereich hoeher. Ohne das Nachruecken
         * schiebt sie das Textfeld unter den Bildschirmrand. */
        if (typeof window.zumChatende === "function") { window.zumChatende(false); }
      }
    }).catch(function () {
      melden(
        "Ohne Erlaubnis für das Mikrofon geht es nicht. Tipp die Aufgabe bitte ein.",
        true
      );
      aufraeumen();
    });
  }

  /* Pause heisst wirklich Pause: Die Spuren werden stillgelegt, und
   * gesammelt wird ohnehin nur im Zustand LAEUFT. Was in der Pause gesagt
   * wird, ist also nicht Teil der Aufnahme. */
  function pausieren() {
    if (zustand !== LAEUFT) { return; }
    if (uhr) { clearTimeout(uhr); uhr = null; }
    umschalten(PAUSE);
    spurenSchalten(false);
    pegelStoppen();
    melden("Pause. Mit Weiter geht es weiter.", false);
  }

  function fortsetzen() {
    if (zustand !== PAUSE) { return; }
    spurenSchalten(true);
    umschalten(LAEUFT);
    pegelStarten();
    weckerStellen();
    melden("Ich höre wieder zu.", false);
  }

  function beenden() {
    if (zustand === AUS) { return; }
    var rate = abtastrate();
    var warDrin = imFokus();
    zustand = AUS;
    var proben = zusammenfuegen(stuecke);
    aufraeumen();

    var dauer = proben.length / rate;
    if (dauer < MINDESTDAUER) {
      melden("Das war zu kurz. Sprich bitte noch einmal, etwas länger.", true);
      if (warDrin) { fokusAuf(knopf); }
      return;
    }
    if (mittlererPegel(proben) < STILLE_SCHWELLE) {
      // Nicht abschicken: Whisper erfindet bei Stille ganze Saetze.
      melden("Da war nichts zu hören. Sprich bitte lauter und näher am Gerät.", true);
      if (warDrin) { fokusAuf(knopf); }
      return;
    }

    melden("Der Rechner der Schule hört zu …", false);
    knopf.disabled = true;
    /* Der Fokus lag in der Tafel, und die ist jetzt zu. Das Textfeld ist der
     * richtige Platz: Dort kommt der Text an und wird nachgelesen. */
    if (warDrin) { fokusAuf(ziel); }

    var daten = new FormData();
    daten.append("aufnahme", alsWav(proben, rate), "aufnahme.wav");

    fetch(knopf.dataset.url, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert() },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json();
    }).then(function (ergebnis) {
      knopf.disabled = false;
      if (!ergebnis || !ergebnis.ok) {
        melden((ergebnis && ergebnis.meldung) || "Das hat nicht geklappt.", true);
        return;
      }
      if (ziel) {
        ziel.value = ziel.value ? ziel.value + " " + ergebnis.text : ergebnis.text;
        ziel.focus();
      }
      /* Vermerkt, dass gesprochen wurde. Die Aufnahme selbst wird nicht
       * gespeichert: Sie ist eine Stimme und damit das heikelste, was hier
       * anfallen koennte. Der erkannte Text ist das Ergebnis. */
      var herkunft = document.getElementById("herkunftfeld");
      if (herkunft && herkunft.value !== "foto") { herkunft.value = "sprache"; }
      melden("Aufgeschrieben. Schau bitte nach, ob alles stimmt.", false);
      if (typeof window.zumChatende === "function") { window.zumChatende(true); }
    }).catch(function () {
      knopf.disabled = false;
      melden("Die Aufnahme ist nicht angekommen. Probier es noch einmal.", true);
    });
  }

  /* --- Bedienung -------------------------------------------------------- */

  balkenAnlegen();
  grenzeSchreiben();
  tafelZeigen();
  knoepfeZeigen();

  knopf.addEventListener("click", function () {
    if (zustand === AUS) { starten(); } else { beenden(); }
  });

  if (knopfAuf) {
    knopfAuf.addEventListener("click", function () {
      if (zustand === PAUSE) { fortsetzen(); } else if (zustand === AUS) { starten(); }
    });
  }
  if (knopfPause) { knopfPause.addEventListener("click", pausieren); }
  if (knopfStopp) { knopfStopp.addEventListener("click", beenden); }
})();
