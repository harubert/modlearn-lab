/* Der Sprechcoach: ein Gespraech, keine Formularseite.
 *
 * Die erste Vorgabe des Nutzers war die Funktaste: "Wenn ich kurz
 * unterbreche, mache ich Pause, beende mit Leertaste." Die zweite hat sie
 * abgeloest (Thomas, 19.10.2026): "Der muss mehr so sein wie der Sprachmodus
 * von ChatGPT. Es wird gesprochen, der Stream bleibt immer offen, das
 * System hat eine Sprechpause oder sinnvollerweise eine Sinneinheit
 * erkannt, und die Antwort kommt vom Spark automatisch, ohne einen Button zu
 * druecken."
 *
 * Daraus folgen die Regeln, die diese Datei tragen:
 *
 * 1. EIN TIPP, DANN KEIN KNOPF MEHR. Browser geben Mikrofon, Klangraum und
 *    Stimme erst nach einer Beruehrung her (iOS immer, Chrome fuer den
 *    Klangraum). Also faengt das Gespraech mit einem Tipp an. Danach
 *    bleibt das Mikrofon die ganze Sitzung offen -- ein Strom, ein
 *    Klangraum --, auch waehrend der Coach spricht. Beenden und "Ich komme
 *    nicht weiter" bleiben Knoepfe, denn das sind keine Gespraechszuege.
 *
 * 2. DIE PAUSE IST DAS ENDE, ABER NICHT JEDE PAUSE GLEICH. Wer in einer
 *    fremden Sprache spricht, holt Luft, sucht ein Wort, setzt neu an.
 *    Darum ist die Pause, die eine Aeusserung beendet, nicht fest: 900
 *    Millisekunden im Normalfall, 1,5 Sekunden, solange erst kurz
 *    gesprochen wurde ("I ..." darf nicht sofort weg). Wie das gemessen
 *    wird, steht bei SPRECH_SCHWELLE und bei pauseFuer().
 *
 * 3. DIE SINNEINHEIT ENTSCHEIDET DER SERVER. Nach dem Abschreiben sagt er,
 *    ob die Aeusserung wie ein abgebrochener Satz aussieht ("and", "the",
 *    "because", nur "ehm"). Dann wartet diese Seite noch bis zu zwei
 *    Sekunden und haengt die naechste Aeusserung an. Nach dem zweiten
 *    Stueck wird auf jeden Fall gesendet. Und wenn Whisper gar keinen
 *    Sprachinhalt gehoert hat, gibt es keinen Zug -- es wird einfach
 *    weitergehoert.
 *
 * 4. DAS KIND DARF UNTERBRECHEN. Spricht es, waehrend der Coach vorliest,
 *    bricht die Sprachausgabe ab und die Aeusserung zaehlt. Weil der
 *    Lautsprecher dabei das Mikrofon treffen kann, gilt waehrend des
 *    Vorlesens eine hoehere Schwelle und ein laengerer Anlauf, und was
 *    abgeschrieben wurde, wird mit dem gerade vorgelesenen Satz verglichen:
 *    Hohe Wortueberlappung heisst Echo, und ein Echo wird verworfen.
 *
 * 5. DREI ZUSTAENDE, GROSS: "Ich hoere zu" (ein Ring, der mit dem Pegel
 *    atmet), "Ich denke nach", "Ich spreche". Kein Text-Chat-Bild; der
 *    Verlauf bleibt als Mitschrift darunter.
 *
 * 6. DIE ANTWORT WIRD GESPROCHEN, von selbst. Abschalten bleibt moeglich
 *    (25 Geraete in einem Zimmer), die Stimmenwahl bleibt erreichbar.
 *
 * 7. TIPPEN BLEIBT, ALS RUECKFALLEBENE. Ohne Mikrofon, mit verweigertem
 *    Mikrofon, in einem lauten Zimmer. Solange getippt wird, hoert das
 *    Geraet nicht zu. Die Leertaste bleibt als Abkuerzung ("jetzt
 *    schicken"), ist aber nirgends noetig und steht nirgends angeschrieben.
 *
 * Dazu der stille Ausweg "Ich komme nicht weiter": Der Coach TUT, als
 * verstehe er kein Deutsch, und das ist eine Lehrmethode. Darum ist sein
 * "Sorry, I don't understand that" hier KEIN Fehler -- kein Rot, kein
 * Warndreieck, sondern ein gewoehnlicher Zug mit einer deutschen Fussnote.
 *
 * sprache.js wird auf dieser Seite nicht geladen; Chat und Trainer benutzen
 * es weiter. Uebernommen ist das Brauchbare daraus: die WAV-Erzeugung mit
 * 16 kHz in mono (am Spark fehlt ffmpeg) und die ruhige Fassung fuer
 * prefers-reduced-motion.
 *
 * Ohne dieses Skript bleibt die Seite bedienbar: Das Formular unter "oder
 * tippen" steht offen da und ist ein gewoehnliches POST-Formular, der
 * Ausweg ebenso. Darum wird hier nichts umgebaut, was die beiden Formulare
 * zum Arbeiten brauchen.
 *
 * Der Ton wird im Browser gemessen und als WAV verschickt; gespeichert wird
 * er nirgends, weder hier noch am Server. Kein Aufbauwerkzeug, keine
 * Bibliothek, nichts aus dem Netz.
 */
(function () {
  "use strict";

  var SVGRAUM = "http://www.w3.org/2000/svg";

  /* --- Masse und Schwellen ----------------------------------------------- */

  var ABTASTRATE = 16000;     // Whisper am Spark liest 16 kHz mono

  /* WIE EINE AEUSSERUNG ANFAENGT UND AUFHOERT
   *
   * Gemessen wird der Effektivwert (RMS) jedes Blocks von rund 50
   * Millisekunden. Zwei Schwellen statt einer, damit die Entscheidung an der
   * Grenze nicht hin und her springt (Hysterese):
   *
   *   ueber SPRECH_SCHWELLE  -> es wird gesprochen
   *   unter STILL_SCHWELLE   -> es ist still
   *   dazwischen             -> es bleibt, wie es war
   *
   * Eine Aeusserung BEGINNT, wenn ANLAUF_MS lang ununterbrochen gesprochen
   * wird; ein Tuerknall ist kuerzer. Sie ENDET, wenn so lange still ist, wie
   * pauseFuer() fuer sie verlangt: PAUSE_MS im Normalfall, PAUSE_LANG_MS,
   * solange erst wenig gesprochen wurde oder die Aeusserung gerade erst
   * angefangen hat. Und sie endet spaetestens nach HOECHSTDAUER_MS -- lieber
   * abschicken als 25 Sekunden Gesprochenes verlieren.
   *
   * Der Geraeuschboden wandert mit: In einem lauten Zimmer liegt er hoeher,
   * und dann darf die Schwelle nicht bei 0,02 kleben. Er faellt sofort auf
   * jeden leiseren Block und kriecht nur langsam hinauf, damit eine laute
   * Stimme ihn nicht mitzieht. Nach oben ist er begrenzt: Sonst wuerde in
   * einem wirklich lauten Zimmer gar keine Stimme mehr erkannt. Waehrend
   * der Coach spricht, steht der Boden still -- sonst zoege der eigene
   * Lautsprecher ihn hinauf.
   */
  var SPRECH_SCHWELLE = 0.02;
  var STILL_SCHWELLE = 0.012;
  var BODEN_GRENZE = 0.06;    // hoeher klettert die Schwelle nicht
  var BODEN_FAKTOR = 3;       // Stimme gilt ab dem Dreifachen des Bodens

  var ANLAUF_MS = 150;        // so lange laut, dann faengt eine Aeusserung an
  var ANLAUF_ECHO_MS = 300;   // waehrend der Coach spricht: laenger
  var PAUSE_MS = 900;         // so lange still, dann ist sie zu Ende
  var PAUSE_LANG_MS = 1500;   // ... ausser es wurde erst kurz gesprochen
  var KURZ_GESPROCHEN_MS = 1000;  // "kurz" heisst: weniger als eine Sekunde Stimme
  var ANFANG_MS = 2500;       // ... oder die Aeusserung ist juenger als das
  var HOECHSTDAUER_MS = 25000;
  var MINDEST_STIMME_MS = 200;    // darunter war es ein Geraeusch, kein Wort
  var MINDESTDAUER_MS = 400;      // darunter verwirft Whisper ohnehin
  var VORLAUF_MS = 350;       // was vor dem Anlaut mitgenommen wird

  var FRAGMENT_WARTE_MS = 2000;   // so lange wartet ein halber Satz auf den Rest
  var NACHSATZ_WARTE_MS = 300;    // so lange ein ganzer Satz, dem noch etwas folgte
  var ERINNERUNG_MS = 15000;  // so lange Stille, dann wird die Frage wiederholt

  /* Echo: Waehrend des Vorlesens trifft der Lautsprecher das Mikrofon. Die
   * Schwelle liegt dann um ECHO_FAKTOR hoeher, und nach jedem erkannten Echo
   * noch einmal hoeher -- das Geraet lernt, wie laut es sich selbst hoert. */
  var ECHO_FAKTOR = 2.5;
  var ECHO_FAKTOR_HOECHSTENS = 6;
  var ECHO_UEBERLAPPUNG = 0.6;    // Anteil der Woerter, die im Vorgelesenen stehen
  var ECHO_NACHLAUF_MS = 400;     // so lange gilt der Schutz noch nach dem Vorlesen

  var RAHMEN_MS = 50;         // 20 Bilder je Sekunde genuegen fuer den Ring
  var RAHMEN_RUHIG_MS = 400;  // bei prefers-reduced-motion nur alle 0,4 Sekunden

  var LESEGRENZE = 180;       // Zeichen je Aeusserung, siehe inStuecke()
  var LESETEMPO = 0.9;        // langsamer als Muttersprache: Es ist eine fremde

  /* --- Was auf der Seite steht ------------------------------------------- */

  var verlauf = document.getElementById("coach-verlauf");
  var stand = document.getElementById("coach-stand");
  var ansage = document.getElementById("coach-ansage");
  var fehlerfeld = document.getElementById("coach-fehler");
  var fertigfeld = document.getElementById("coach-fertig");
  var steuerung = document.querySelector(".coach-steuerung");

  var tafel = document.getElementById("coach-tafel");
  var ring = document.getElementById("coach-ring");
  var zustandswort = document.getElementById("coach-zustand-wort");
  var zustandszusatz = document.getElementById("coach-zustand-zusatz");
  var tafelhinweis = document.getElementById("coach-tafelhinweis");
  var funk = document.getElementById("coach-funk");
  var funkwort = document.getElementById("coach-funk-wort");

  var ruhigfeld = document.getElementById("coach-pegel-ruhig");
  var ruhefuellung = document.getElementById("coach-ruhefuellung");
  var ruhewert = document.getElementById("coach-ruhewert");

  var tonknopf = document.getElementById("coach-ton");
  var tonwort = document.getElementById("coach-ton-wort");
  var stimmwahl = document.getElementById("coach-stimmwahl");
  var stimmenfeld = document.getElementById("stimme");
  var stummzeile = document.getElementById("coach-stumm");

  var auswegform = document.getElementById("coach-ausweg-form");
  var ausweg = document.getElementById("coach-ausweg");
  var hilfekasten = document.getElementById("coach-hilfe");
  var hilfetext = document.getElementById("coach-hilfe-text");
  var hilfebeispiel = document.getElementById("coach-hilfe-beispiel");
  var hilfesatz = document.getElementById("coach-hilfe-satz");
  var hilfehoeren = document.getElementById("coach-hilfe-hoeren");
  var hilfezu = document.getElementById("coach-hilfe-zu");

  var tippen = document.getElementById("coach-tippen");
  var form = document.getElementById("coach-form");
  var feld = document.getElementById("text");
  var senden = document.getElementById("senden");

  /* Die Zielsprache haengt am Verlauf, nicht am Formular: Der Verlauf steht
   * immer da, das Formular ist am Ende des Gespraechs verborgen. */
  var SPRACHE = (verlauf && verlauf.getAttribute("data-sprache")) || "";
  var SPRACHNAME = (verlauf && verlauf.getAttribute("data-sprachname")) || "";

  /* Fehlt die Adresse der Spracherkennung, kann der Rechner der Schule
   * gerade nicht abschreiben. Dann wird auch kein Mikrofon gefragt: Ein
   * Ring, der zuhoert, ohne dass jemand mitschreibt, waere eine Luege. */
  var HOEREN_URL = (tafel && tafel.getAttribute("data-erkennen")) || "";
  var WORKLET_URL = (tafel && tafel.getAttribute("data-worklet")) || "";
  var MIKRO_MOEGLICH = !!(HOEREN_URL && navigator.mediaDevices &&
    navigator.mediaDevices.getUserMedia && window.fetch && window.FormData &&
    (window.AudioContext || window.webkitAudioContext));

  /* --- Kleinigkeiten, die mehrere Teile brauchen ------------------------- */

  function ruhigGewuenscht() {
    return !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function csrfWert() {
    var treffer = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    return treffer ? decodeURIComponent(treffer[2]) : "";
  }

  function leeren(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function fokusAuf(element) {
    if (!element) { return; }
    try { element.focus(); } catch (e) { /* aeltere Browser */ }
  }

  function getrimmt(text) {
    return String(text || "").replace(/^\s+|\s+$/g, "");
  }

  /* Rollt einen Kasten ins Bild, nicht das Seitenende: Die Steuerung klebt
   * unten, und block: center laesst den Satz darueber stehen. Bei
   * prefers-reduced-motion wird gesprungen statt geglitten -- sanftes
   * Scrollen ist auch Bewegung. */
  function insBild(element, sanft) {
    if (!element) { return; }
    try {
      element.scrollIntoView({
        block: "center",
        behavior: (sanft && !ruhigGewuenscht()) ? "smooth" : "auto"
      });
    } catch (e) {
      element.scrollIntoView(false);
    }
  }

  function letzterZug() {
    return verlauf ? verlauf.lastElementChild : null;
  }

  /* Erst leeren, dann setzen. Steht derselbe Satz noch im Bereich, meldet
   * ein Vorlesewerkzeug nichts, weil sich nichts geaendert hat.
   *
   * Der fremdsprachige Teil kommt in ein eigenes span mit lang. Ohne das
   * liest ein deutsches Vorlesewerkzeug den englischen Satz deutsch -- genau
   * der Fehler, den die Seite im Verlauf sorgsam vermeidet. */
  function ansagen(deutsch, fremd) {
    if (!ansage) { return; }
    leeren(ansage);
    window.setTimeout(function () {
      if (deutsch) { ansage.appendChild(document.createTextNode(deutsch + " ")); }
      if (fremd) {
        var teil = document.createElement("span");
        if (SPRACHE) { teil.setAttribute("lang", SPRACHE); }
        teil.textContent = fremd;
        ansage.appendChild(teil);
      }
    }, 60);
  }

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

  /* Der leise Hinweis in der Tafel. Hier steht, was gerade schiefgegangen
   * ist, wenn es ein neuer Anlauf richtet -- "nichts gehoert", "ich warte
   * noch". Der rote Kasten bleibt den Faellen, in denen etwas verloren
   * waere. */
  function hinweisZeigen(text) {
    if (!tafelhinweis) { return; }
    tafelhinweis.textContent = text || "";
    tafelhinweis.hidden = !text;
  }

  /* --- Der Zustandsanzeiger ---------------------------------------------- */

  var LAGEN = {
    start: {
      wort: "Tipp einmal, dann geht es los",
      zusatz: function () {
        return "Dieser Browser gibt Mikrofon und Stimme erst nach einer " +
          "Berührung her. Danach brauchst du keinen Knopf mehr.";
      },
      funk: "Gespräch starten",
      funkAn: true
    },
    hoert: {
      wort: "Ich höre zu",
      zusatz: function () {
        return "Sprich einfach – auf " + (SPRACHNAME || "der Zielsprache") +
          ". Wenn du eine Pause machst, antwortet der Coach.";
      },
      funk: "",
      funkAn: false
    },
    denkt: {
      wort: "Ich denke nach",
      zusatz: function () { return "Einen Moment – der Rechner der Schule überlegt."; },
      funk: "",
      funkAn: false
    },
    spricht: {
      wort: "Ich spreche",
      zusatz: function () {
        return "Du darfst mich unterbrechen – sprich einfach los.";
      },
      funk: "",
      funkAn: false
    },
    tippt: {
      wort: "Du tippst",
      zusatz: function () {
        return "Ich höre gerade nicht zu. Klapp „oder tippen“ wieder zu, dann " +
          "geht es gesprochen weiter.";
      },
      funk: "",
      funkAn: false
    },
    weg: {
      wort: "Angehalten",
      zusatz: function () {
        return "Das Fenster war weg, darum habe ich das Mikrofon stillgelegt. " +
          "Tipp, dann höre ich wieder zu.";
      },
      funk: "Weiter zuhören",
      funkAn: true
    },
    aus: {
      wort: "Tipp deine Antwort",
      zusatz: function () {
        return "Dieses Gerät nimmt gerade nicht auf. Getippt zählt genauso – " +
          "der Coach merkt keinen Unterschied.";
      },
      funk: "Mikrofon noch einmal versuchen",
      funkAn: true
    },
    fertig: {
      wort: "Das Gespräch ist zu Ende",
      zusatz: function () { return ""; },
      funk: "",
      funkAn: false
    }
  };

  var lage = "aus";

  function hoertZu() {
    return lage === "hoert" || lage === "denkt" || lage === "spricht";
  }

  function lageSetzen(neu) {
    if (!LAGEN[neu]) { return; }
    if (lage === "spricht" && neu !== "spricht") {
      /* Der Lautsprecher ist gerade verstummt. Was die Hysterese noch fuer
       * laut haelt, ist sein Nachhall, nicht das Kind. */
      echoBis = Date.now() + ECHO_NACHLAUF_MS;
      laut = false;
      lautMs = 0;
    }
    lage = neu;
    var eintrag = LAGEN[neu];
    if (tafel) { tafel.setAttribute("data-lage", neu); }
    if (zustandswort) { zustandswort.textContent = eintrag.wort; }
    if (zustandszusatz) {
      var zusatz = eintrag.zusatz();
      zustandszusatz.textContent = zusatz;
      zustandszusatz.hidden = !zusatz;
    }
    /* Der grosse Knopf gibt es nur dort, wo eine Beruehrung noetig ist: am
     * Anfang, nach dem Hintergrund, nach einem verweigerten Mikrofon. Im
     * Gespraech selbst steht kein Knopf -- das war die Vorgabe. */
    if (funk) {
      funk.hidden = !MIKRO_MOEGLICH || !eintrag.funkAn;
      funk.disabled = !eintrag.funkAn;
      if (funkwort) { funkwort.textContent = eintrag.funk; }
    }
    /* Das Mikrofon ist offen, solange das Gespraech laeuft -- auch waehrend
     * der Coach spricht, denn das Kind darf ihn unterbrechen. Nur beim
     * Tippen, im Hintergrund und am Ende werden die Spuren stillgelegt. */
    spurenSchalten(hoertZu());
    if (ruhigfeld) { ruhigfeld.hidden = (neu !== "hoert"); }
    if (verlauf) {
      verlauf.setAttribute("aria-busy", neu === "denkt" ? "true" : "false");
    }
    if (!hoertZu()) { ringFlachlegen(); }
  }

  /* Gleicher Satzbau wie in sprechcoach.html. Die Seite darf nach dem ersten
   * Zug nicht anders klingen als beim Laden; wer hier etwas aendert, aendert
   * es dort mit. */
  function standSchreiben(anzahl) {
    if (!stand) { return; }
    var zahl = Number(anzahl);
    if (!isFinite(zahl) || zahl < 0) { return; }
    if (zahl === 0) { stand.textContent = "Das Gespräch fängt gerade an"; }
    else if (zahl === 1) { stand.textContent = "1 Beitrag im Gespräch"; }
    else { stand.textContent = zahl + " Beiträge im Gespräch"; }
  }

  /* Am Ende gehen Steuerung und Formular weg und der Schlusssatz kommt. Die
   * Ansicht nimmt nach dem letzten Zug keinen weiteren mehr an; ein
   * Mikrofon, das dann noch zuhoert, sammelt Saetze fuer niemanden. */
  function fertigSetzen() {
    aufraeumen();
    lageSetzen("fertig");
    if (fertigfeld) { fertigfeld.hidden = false; }
    if (steuerung) { steuerung.hidden = true; }
    if (tippen) { tippen.hidden = true; }
  }

  /* --- Sprachausgabe ----------------------------------------------------- */

  /* Der Wunsch wird je Sprache gemerkt. Wer Franzoesisch hoeren will, muss
   * das nicht abschalten, weil er es im Englischkurs abgeschaltet hatte. */
  var SCHLUESSEL_TON = "modlearn-sprechcoach-vorlesen" + (SPRACHE ? "-" + SPRACHE : "");
  var SCHLUESSEL_STIMME = "modlearn-sprechcoach-stimme" + (SPRACHE ? "-" + SPRACHE : "");

  var stimme = null;
  var vorlesenAn = true;
  var wunschGeklaert = false;
  var hinweisErlaubt = false;   // siehe stimmensucheAbschliessen()
  var sprechNummer = 0;

  /* Was gerade vorgelesen wird, fuer den Echo-Abgleich und fuer das
   * Fortsetzen nach einem Echo. leseStelle ist das letzte Wortende, das der
   * Browser gemeldet hat (onboundary); nicht jeder meldet eines. */
  var vorgelesen = "";
  var leseStelle = 0;
  var leseFortgesetzt = false;
  var leseDanach = null;

  function merkenLesen(schluessel) {
    try {
      return window.localStorage.getItem(schluessel);
    } catch (e) {
      return null;   // privater Modus oder gesperrte Seitendaten
    }
  }

  function merkenSchreiben(schluessel, wert) {
    try {
      window.localStorage.setItem(schluessel, wert);
    } catch (e) { /* siehe merkenLesen */ }
  }

  /* Der Standard kommt aus der Vorlage (vorlesen_an) und ist beim
   * Sprechcoach "an". Das ist keine Kleinigkeit: Die Sprachausgabe ist hier
   * der Kern, nicht die Zugabe. */
  function standardwunsch() {
    if (!tonknopf) { return true; }
    return tonknopf.getAttribute("data-standard") !== "aus";
  }

  function wunschLesen() {
    var gemerkt = merkenLesen(SCHLUESSEL_TON);
    if (gemerkt === "ja") { return true; }
    if (gemerkt === "nein") { return false; }
    return standardwunsch();
  }

  /* Alle Stimmen der Zielsprache, die genau passenden zuerst: en-GB ist
   * nicht en-US (andere Aussprache, und die Lehrperson hat sie
   * ausgewaehlt). */
  function stimmenDerSprache() {
    if (!SPRACHE) { return []; }
    if (!window.speechSynthesis || !window.speechSynthesis.getVoices) { return []; }
    var liste = window.speechSynthesis.getVoices() || [];
    var gesucht = SPRACHE.toLowerCase().replace("_", "-");
    var hauptteil = gesucht.split("-")[0];
    var genau = [];
    var verwandt = [];
    for (var i = 0; i < liste.length; i++) {
      var code = String(liste[i].lang || "").toLowerCase().replace("_", "-");
      if (code.split("-")[0] !== hauptteil) { continue; }
      if (code === gesucht) { genau.push(liste[i]); } else { verwandt.push(liste[i]); }
    }
    return genau.concat(verwandt);
  }

  /* Die Voreinstellung bleibt eine Stimme, die im Geraet rechnet: Das
   * Versprechen der Anwendung ist, dass nichts hinausgeht. Sie ist aber nur
   * eine Voreinstellung -- wem sie zu blechern klingt, der waehlt eine
   * andere. Eine feste Bevorzugung hat auf Windows genau die alten
   * SAPI-Stimmen gezogen. */
  function zielStimme() {
    var liste = stimmenDerSprache();
    if (!liste.length) { return null; }

    var gemerkt = merkenLesen(SCHLUESSEL_STIMME);
    if (gemerkt) {
      for (var i = 0; i < liste.length; i++) {
        if (liste[i].voiceURI === gemerkt || liste[i].name === gemerkt) {
          return liste[i];
        }
      }
    }
    for (var j = 0; j < liste.length; j++) {
      if (liste[j].localService) { return liste[j]; }
    }
    return liste[0];
  }

  /* Die Liste baut das Skript, weil nur der Browser weiss, was da ist. Unter
   * zwei Stimmen gibt es nichts zu waehlen, dann bleibt der Aufklapper weg. */
  function stimmenlisteFuellen() {
    if (!stimmenfeld || !stimmwahl) { return; }
    var liste = stimmenDerSprache();
    if (liste.length < 2) { stimmwahl.hidden = true; return; }

    leeren(stimmenfeld);
    for (var i = 0; i < liste.length; i++) {
      var eintrag = document.createElement("option");
      eintrag.value = liste[i].voiceURI || liste[i].name;
      eintrag.textContent = liste[i].name
        + (liste[i].localService ? " – auf dem Gerät" : " – über das Netz");
      if (stimme && (liste[i].voiceURI === stimme.voiceURI
                     || liste[i].name === stimme.name)) {
        eintrag.selected = true;
      }
      stimmenfeld.appendChild(eintrag);
    }
    stimmwahl.hidden = false;
  }

  function tonknopfZeichnen() {
    if (stummzeile) { stummzeile.hidden = !!stimme || !hinweisErlaubt; }
    if (!tonknopf) { return; }
    /* Ohne Stimme geht der Schalter weg. Ein Knopf, der bloss schweigt,
     * waere schlimmer als kein Knopf -- und die Zeile darueber sagt dann,
     * woran man ist. */
    tonknopf.hidden = !stimme;
    tonknopf.setAttribute("aria-pressed", vorlesenAn ? "true" : "false");
    tonknopf.classList.toggle("ist-an", vorlesenAn);
    if (tonwort) { tonwort.textContent = vorlesenAn ? "Vorlesen an" : "Vorlesen aus"; }
  }

  function vorlesenAbbrechen() {
    sprechNummer++;
    vorgelesen = "";
    leseDanach = null;
    if (!window.speechSynthesis) { return; }
    try { window.speechSynthesis.cancel(); } catch (e) { /* nichts zu stoppen */ }
  }

  /* Lange Texte werden in Stuecke zerlegt und der Reihe nach gesprochen.
   * Manche Browser schneiden eine einzelne lange Aeusserung nach wenigen
   * Sekunden ab; kurze Stuecke hintereinander kommen zuverlaessig durch.
   * Geschnitten wird an einem Satzende, sonst an einem Leerzeichen -- mitten
   * im Wort abzubrechen klingt in einer fremden Sprache wie ein neues Wort. */
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

  /* Gesprochen wird, was der Coach sagt. Jeder Aufruf bricht das vorige
   * Vorlesen ab: Zwei Saetze uebereinander sind in einer fremden Sprache
   * nicht mehr zu entwirren.
   *
   * `danach` laeuft, wenn der Coach fertig ist -- oder wenn das Kind ihn
   * unterbrochen hat; dann laeuft es nicht, denn dann uebernimmt die
   * Aeusserung des Kindes. Das Mikrofon bleibt waehrenddessen offen; wie
   * Echo von Unterbrechung unterschieden wird, steht bei blockVerarbeiten.
   *
   * erzwingen = true kommt von "nochmal hoeren" und vom Beispielsatz: Diese
   * Knoepfe sprechen auch dann, wenn der Schalter aus ist -- ein Tippen
   * darauf ist eine ausdrueckliche Bitte. */
  function sprechen(text, erzwingen, danach) {
    vorlesenAbbrechen();
    var meine = sprechNummer;
    var satz = getrimmt(text);

    function einmal() {
      if (meine !== sprechNummer) { return; }   // ein neuer Satz hat uebernommen
      sprechNummer++;
      vorgelesen = "";
      leseDanach = null;
      if (danach) { danach(); }
    }

    if (!stimme || !window.SpeechSynthesisUtterance || !satz ||
        (!vorlesenAn && !erzwingen)) {
      einmal();
      return;
    }

    vorgelesen = satz;
    leseStelle = 0;
    leseFortgesetzt = false;
    leseDanach = danach || null;
    sprechenAb(satz, 0, meine, einmal);
  }

  /* Spricht `satz` ab Zeichen `ab`. Getrennt von sprechen(), damit nach
   * einem Echo an der gemerkten Stelle weitergelesen werden kann, statt von
   * vorn. */
  function sprechenAb(satz, ab, meine, einmal) {
    var rest = satz.slice(ab);
    var stuecke = inStuecke(rest);
    var versatz = ab;
    for (var i = 0; i < stuecke.length; i++) {
      try {
        var rede = new window.SpeechSynthesisUtterance(stuecke[i]);
        rede.voice = stimme;
        rede.lang = stimme.lang || SPRACHE;
        rede.rate = LESETEMPO;
        rede.onboundary = (function (anfang) {
          return function (ereignis) {
            if (meine !== sprechNummer) { return; }
            if (ereignis && typeof ereignis.charIndex === "number") {
              leseStelle = anfang + ereignis.charIndex;
            }
          };
        }(versatz));
        if (i === stuecke.length - 1) {
          rede.onend = einmal;
          rede.onerror = einmal;
        }
        window.speechSynthesis.speak(rede);
      } catch (e) {
        einmal();   // Kein Grund, es mit den restlichen Stuecken zu versuchen.
        return;
      }
      versatz += stuecke[i].length + 1;
    }

    /* Rueckfallebene: Manche Browser melden onend nie, und dann wuerde nie
     * wieder zugehoert. Grosszuegig geschaetzt, lieber zu spaet als mitten
     * in den Satz des Coaches hinein. */
    window.setTimeout(einmal, 1500 + rest.length * 90);
  }

  /* Nach einem Echo: Der Coach war unterbrochen, aber nicht vom Kind,
   * sondern von sich selbst. Dann liest er weiter, wo er war -- einmal.
   * Ein zweites Mal nicht: Wer sich immer wieder selbst hoert, wiederholt
   * sich sonst in einer Schleife, und dann ist Weiterhoeren das kleinere
   * Uebel. */
  function vorlesenFortsetzen(satz, stelle, danach) {
    if (!satz || leseFortgesetzt || !stimme || !window.SpeechSynthesisUtterance ||
        !vorlesenAn || !hoertZu()) {
      if (danach) { danach(); }
      return;
    }
    leseFortgesetzt = true;
    vorlesenAbbrechen();
    var meine = sprechNummer;
    /* Zurueck zum Anfang des angefangenen Satzes, nicht mitten hinein. */
    var anfang = Math.max(satz.lastIndexOf(". ", stelle), satz.lastIndexOf("? ", stelle),
                          satz.lastIndexOf("! ", stelle));
    anfang = anfang >= 0 ? anfang + 2 : 0;

    function einmal() {
      if (meine !== sprechNummer) { return; }
      sprechNummer++;
      vorgelesen = "";
      leseDanach = null;
      if (danach) { danach(); }
    }

    vorgelesen = satz;
    leseStelle = anfang;
    leseDanach = danach || null;
    lageSetzen("spricht");
    sprechenAb(satz, anfang, meine, einmal);
  }

  /* --- Der Knopf "nochmal hoeren" ---------------------------------------- */

  function svgTeil(name, eigenschaften) {
    var teil = document.createElementNS(SVGRAUM, name);
    for (var schluessel in eigenschaften) {
      if (Object.prototype.hasOwnProperty.call(eigenschaften, schluessel)) {
        teil.setAttribute(schluessel, eigenschaften[schluessel]);
      }
    }
    return teil;
  }

  function hoerzeichen() {
    var svg = svgTeil("svg", {
      "class": "zug-hoeren-zeichen",
      viewBox: "0 0 24 24",
      "aria-hidden": "true",
      focusable: "false"
    });
    svg.appendChild(svgTeil("path", {
      d: "M4 9.5h3L11 6v12l-4-3.5H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "1.7",
      "stroke-linejoin": "round"
    }));
    svg.appendChild(svgTeil("path", {
      d: "M15 9a4 4 0 0 1 0 6M17.8 6.2a8 8 0 0 1 0 11.6",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "1.7",
      "stroke-linecap": "round"
    }));
    return svg;
  }

  /* Der Knopf wird nur hier gebaut und nicht in der Vorlage. Zwei Gruende:
   * Ohne Stimme hat er keinen Zweck und soll nicht dastehen, und so steht
   * seine Beschriftung an genau einer Stelle statt an zwei, die auseinander
   * laufen koennen. */
  function hoerenKnopfSetzen(eintrag) {
    if (!stimme || !eintrag) { return; }
    if (eintrag.querySelector(".zug-hoeren")) { return; }
    var fuss = eintrag.querySelector(".zug-fuss");
    if (!fuss) {
      fuss = document.createElement("div");
      fuss.className = "zug-fuss";
      eintrag.appendChild(fuss);
    }
    var knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "werkzeug zug-hoeren";
    knopf.appendChild(hoerzeichen());
    var wort = document.createElement("span");
    wort.className = "zug-hoeren-wort";
    wort.textContent = "nochmal hören";
    knopf.appendChild(wort);
    /* Der sichtbare Text steht im Namen des Knopfes. Ein aria-label ohne das
     * sichtbare Wort liesse eine Sprachsteuerung ins Leere greifen. */
    knopf.setAttribute("aria-label", "Diesen Satz nochmal hören");
    knopf.addEventListener("click", function () {
      var text = eintrag.querySelector(".zug-text");
      coachSpricht(text ? text.textContent : "", true);
    });
    fuss.insertBefore(knopf, fuss.firstChild);
    return knopf;
  }

  function hoerenKnoepfeSetzen() {
    if (!verlauf || !stimme) { return; }
    var liste = verlauf.querySelectorAll("li.zug-coach");
    for (var i = 0; i < liste.length; i++) { hoerenKnopfSetzen(liste[i]); }
  }

  /* Der letzte Zug des Coaches, aus dem Dokument gelesen. So braucht das
   * Vorlesen keinen zweiten Speicher neben der Seite, und es funktioniert
   * auch nach einem gewoehnlichen Neuladen. */
  function letzterCoachsatz() {
    if (!verlauf) { return null; }
    var liste = verlauf.querySelectorAll("li.zug-coach");
    if (!liste.length) { return null; }
    var text = liste[liste.length - 1].querySelector(".zug-text");
    return text ? text.textContent : null;
  }

  function letzterZugIstVomCoach() {
    var zug = letzterZug();
    return !!(zug && zug.classList && zug.classList.contains("zug-coach"));
  }

  /* Die Stimmenliste kommt in vielen Browsern erst nach dem Laden, manchmal
   * erst beim zweiten Anlauf. Darum wird hier mehrfach nachgesehen; ohne
   * Stimme in der Zielsprache bleibt der Schalter verborgen, die
   * Hinweiszeile kommt, und der Text genuegt. */
  function stimmeSuchen() {
    stimme = zielStimme();
    if (stimme && !wunschGeklaert) {
      wunschGeklaert = true;
      vorlesenAn = wunschLesen();
    }
    if (stimme) { hoerenKnoepfeSetzen(); } else { vorlesenAn = false; }
    tonknopfZeichnen();
    stimmenlisteFuellen();
  }

  /* Von hier an gilt: Was jetzt keine Stimme hat, bekommt keine mehr. Die
   * Hinweiszeile "keine Stimme fuer diese Sprache" darf erst dann kommen --
   * sonst blitzt sie beim Laden auf und widerruft sich selbst. */
  function stimmensucheAbschliessen() {
    hinweisErlaubt = true;
    stimmeSuchen();
  }

  if (window.speechSynthesis && window.SpeechSynthesisUtterance) {
    stimmeSuchen();
    if (!stimme) {
      if (typeof window.speechSynthesis.addEventListener === "function") {
        window.speechSynthesis.addEventListener("voiceschanged", stimmensucheAbschliessen);
      } else {
        window.speechSynthesis.onvoiceschanged = stimmensucheAbschliessen;
      }
      window.setTimeout(stimmensucheAbschliessen, 2000);
    }
  } else {
    stimme = null;
    vorlesenAn = false;
    hinweisErlaubt = true;
    tonknopfZeichnen();
  }

  /* iOS (und Chrome auf Android in manchen Faellen) spricht erst, wenn
   * einmal in einer Beruehrung gesprochen wurde. Ein leerer Satz in der
   * Beruehrung schaltet die Stimme frei; danach darf das Skript von selbst
   * sprechen. Das steht im Starttipp -- der einzigen Beruehrung, die das
   * Gespraech noch hat. */
  function stimmeFreischalten() {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) { return; }
    if (window.speechSynthesis.speaking) { return; }
    try {
      var leer = new window.SpeechSynthesisUtterance(" ");
      leer.volume = 0;
      window.speechSynthesis.speak(leer);
    } catch (e) { /* dann eben nicht */ }
  }

  if (stimmenfeld) {
    stimmenfeld.addEventListener("change", function () {
      var liste = stimmenDerSprache();
      for (var i = 0; i < liste.length; i++) {
        var kennung = liste[i].voiceURI || liste[i].name;
        if (kennung === stimmenfeld.value) {
          stimme = liste[i];
          merkenSchreiben(SCHLUESSEL_STIMME, kennung);
          break;
        }
      }
      /* Gleich vorlesen: Man waehlt eine Stimme, um sie zu hoeren. Ohne
       * diese Probe muesste man erst einen Zug abwarten, um zu merken, dass
       * die neue auch nicht besser klingt. */
      coachSpricht(letzterCoachsatz(), true);
    });
  }

  if (tonknopf) {
    tonknopf.addEventListener("click", function () {
      vorlesenAn = !vorlesenAn;
      merkenSchreiben(SCHLUESSEL_TON, vorlesenAn ? "ja" : "nein");
      tonknopfZeichnen();
      if (!vorlesenAn) {
        vorlesenAbbrechen();
        ansagen("Vorlesen ist aus.", "");
        weiterHoeren();
        return;
      }
      /* Der Klick ist die Handbewegung, die manche Browser fuer das erste
       * Sprechen verlangen. Also wird gleich der offene Satz gelesen: So
       * hoert man sofort etwas und nicht erst beim naechsten Zug. */
      ansagen("Vorlesen ist an.", "");
      coachSpricht(letzterCoachsatz(), false);
    });
  }

  /* Der eine Weg, auf dem der Coach spricht: Lage setzen, sprechen, danach
   * wieder zuhoeren. Waehrenddessen bleibt das Mikrofon offen -- das Kind
   * darf unterbrechen. */
  function coachSpricht(text, erzwingen) {
    if (lage === "fertig" || lage === "tippt" || abschlussLaeuft) {
      sprechen(text, erzwingen, null);
      return;
    }
    if (hoertZu()) { lageSetzen("spricht"); }
    sprechen(text, erzwingen, weiterHoeren);
  }

  /* --- Der Verlauf ------------------------------------------------------- */

  /* Baut genau die Struktur, die sprechcoach.html rendert. Weicht das eine
   * vom anderen ab, sieht die Seite nach dem ersten Zug anders aus als nach
   * einem Neuladen.
   *
   * Durchweg textContent, nie innerHTML: Was aus dem Netz kommt, wird hier
   * nie als Auszeichnung gelesen. */
  function zugAnhaengen(istCoach, text, uebersetzung, korrektur, nichtVerstanden) {
    if (!verlauf) { return null; }

    var eintrag = document.createElement("li");
    eintrag.className = "zug " + (istCoach ? "zug-coach" : "zug-lernend")
      + (nichtVerstanden ? " zug-nachfrage" : "");

    var kopf = document.createElement("p");
    kopf.className = "zug-kopf";
    var wer = document.createElement("span");
    wer.className = "zug-wer";
    wer.textContent = istCoach ? "Coach" : "Du";
    kopf.appendChild(wer);
    if (SPRACHNAME) {
      var marke = document.createElement("span");
      marke.className = "zug-sprachmarke";
      marke.textContent = SPRACHNAME;
      kopf.appendChild(marke);
    }
    eintrag.appendChild(kopf);

    var rumpf = document.createElement("div");
    rumpf.className = "zug-text";
    if (SPRACHE) { rumpf.setAttribute("lang", SPRACHE); }
    rumpf.textContent = text || "";
    eintrag.appendChild(rumpf);

    /* Die deutsche Fussnote zur Sprachsperre. Gleicher Wortlaut wie in der
     * Vorlage, damit die Seite nach einem Neuladen nicht anders klingt. */
    if (nichtVerstanden) {
      var fussnote = document.createElement("p");
      fussnote.className = "zug-nachfrage-hinweis";
      fussnote.textContent = "Der Coach versteht nur "
        + (SPRACHNAME || "die Zielsprache") + " – das ist Absicht. Sag es "
        + "noch einmal auf " + (SPRACHNAME || "der Zielsprache")
        + "; wenn dir das Wort fehlt, hilft dir „Ich komme nicht weiter“.";
      eintrag.appendChild(fussnote);
    }

    var fuss = document.createElement("div");
    fuss.className = "zug-fuss";
    if (uebersetzung) {
      /* Zugeklappt, wie in der Vorlage: Wer die Uebersetzung sofort sieht,
       * liest sie statt zuzuhoeren. */
      var kasten = document.createElement("details");
      kasten.className = "zug-uebersetzung";
      var titel = document.createElement("summary");
      titel.textContent = "Auf Deutsch";
      var deutsch = document.createElement("p");
      deutsch.className = "zug-uebersetzung-text";
      deutsch.textContent = uebersetzung;
      kasten.appendChild(titel);
      kasten.appendChild(deutsch);
      fuss.appendChild(kasten);
    }
    eintrag.appendChild(fuss);

    if (korrektur) {
      var zeile = document.createElement("p");
      zeile.className = "zug-korrektur";
      var hinweis = document.createElement("span");
      hinweis.className = "korrektur-marke";
      hinweis.textContent = "So sagt man es";
      var richtig = document.createElement("span");
      richtig.className = "korrektur-text";
      if (SPRACHE) { richtig.setAttribute("lang", SPRACHE); }
      richtig.textContent = korrektur;
      zeile.appendChild(hinweis);
      zeile.appendChild(richtig);
      eintrag.appendChild(zeile);
    }

    verlauf.appendChild(eintrag);
    if (istCoach) { hoerenKnopfSetzen(eintrag); }
    return eintrag;
  }

  /* Der eigene Beitrag steht schon im Verlauf, waehrend er noch waechst:
   * Ein halber Satz, auf dessen Rest gewartet wird, ist sichtbar und mit
   * "…" markiert. So sieht das Kind, dass es gehoert wurde, bevor der
   * Coach antwortet. */
  var offenerZug = null;

  function eigenenZugZeigen(text, offen) {
    if (!offenerZug) {
      offenerZug = zugAnhaengen(false, text, "", "", false);
    } else {
      var rumpf = offenerZug.querySelector(".zug-text");
      if (rumpf) { rumpf.textContent = text; }
    }
    if (offenerZug) {
      offenerZug.classList.toggle("zug-offen", !!offen);
      insBild(offenerZug, true);
    }
    return offenerZug;
  }

  function eigenenZugAbschliessen() {
    var zug = offenerZug;
    offenerZug = null;
    if (zug) { zug.classList.remove("zug-offen"); }
    return zug;
  }

  /* --- Die Aufnahme ------------------------------------------------------ */

  var kontext = null;
  var strom = null;
  var quelle = null;
  var verarbeiter = null;
  var stummer = null;
  var startetGerade = false;
  var mikroVerweigert = false;   // Erlaubnis abgelehnt oder kein Mikrofon da

  /* Der Geraeuschboden startet dort, wo er die Schwelle genau auf
   * SPRECH_SCHWELLE stellt. Mit einem hohen Startwert laege die Schwelle in
   * den ersten Sekunden an ihrer Obergrenze, und ein leise sprechendes Kind
   * waere genau beim ersten Satz nicht zu hoeren. */
  var BODEN_START = SPRECH_SCHWELLE / BODEN_FAKTOR;
  var boden = BODEN_START;
  var echoFaktor = ECHO_FAKTOR;
  var echoBis = 0;            // bis dahin gilt der Echo-Schutz nach dem Vorlesen
  var abschlussLaeuft = false;   // der letzte Satz: keine Unterbrechung mehr
  var abschlussDanach = null;
  var ungelesen = "";         // eine Antwort, die im Hintergrund ankam

  var laut = false;           // Hysterese: ueber der Schwelle, bis unter die andere
  var lautMs = 0;             // so lange ununterbrochen laut (vor einer Aeusserung)
  var vorlauf = [];           // die letzten Bloecke vor dem naechsten Wort
  var vorlaufMs = 0;
  var aeusserung = null;      // die laufende Aeusserung, siehe aeusserungBeginnen

  var warteschlange = [];     // fertige Aeusserungen, die noch abzuschreiben sind
  var hoerenUnterwegs = false;
  var zugUnterwegs = false;
  var offenesFragment = null; // {text, erkannt, warten}: wartet auf seinen Rest
  var fragmentTakt = null;
  var nachtrag = [];          // was das Kind sagte, waehrend der Coach ueberlegte
  var nachtragErkannt = "";
  var stilleSeit = 0;         // fuer die Erinnerung nach langer Stille
  var erinnert = false;

  var takt = null;
  var letzteAnzeige = 0;
  var ringWert = 0;
  var ruhigWert = 0;

  function abtastrate() {
    return kontext ? kontext.sampleRate : ABTASTRATE;
  }

  function rms(proben) {
    var summe = 0;
    for (var i = 0; i < proben.length; i++) { summe += proben[i] * proben[i]; }
    return Math.sqrt(summe / (proben.length || 1));
  }

  function zusammenfuegen(liste) {
    var gesamt = 0;
    var i;
    for (i = 0; i < liste.length; i++) { gesamt += liste[i].length; }
    var alles = new Float32Array(gesamt);
    var pos = 0;
    for (i = 0; i < liste.length; i++) { alles.set(liste[i], pos); pos += liste[i].length; }
    return alles;
  }

  /* Auf 16 kHz herunter, wenn der Klangraum eine andere Rate hergibt (iOS
   * bleibt gern bei 48 kHz). Whisper will 16 kHz, und eine Aufnahme mit
   * dreifacher Rate waere dreimal so gross. Bei ganzzahligem Verhaeltnis
   * wird gemittelt, sonst zwischen zwei Proben geradlinig gerechnet --
   * fuer Sprache reicht beides. */
  function auf16k(proben, rate) {
    if (rate === ABTASTRATE || !proben.length) { return proben; }
    var faktor = rate / ABTASTRATE;
    var laenge = Math.floor(proben.length / faktor);
    var neu = new Float32Array(laenge);
    var i;
    if (Math.abs(faktor - Math.round(faktor)) < 1e-6) {
      var n = Math.round(faktor);
      for (i = 0; i < laenge; i++) {
        var summe = 0;
        for (var j = 0; j < n; j++) { summe += proben[i * n + j]; }
        neu[i] = summe / n;
      }
      return neu;
    }
    for (i = 0; i < laenge; i++) {
      var stelle = i * faktor;
      var links = Math.floor(stelle);
      var rechts = Math.min(proben.length - 1, links + 1);
      var anteil = stelle - links;
      neu[i] = proben[links] * (1 - anteil) + proben[rechts] * anteil;
    }
    return neu;
  }

  /* 16-bit-PCM in einem WAV-Kopf, uebernommen aus sprache.js. Kein
   * Selbstzweck: Am Spark fehlt ffmpeg, und was ein Handy von sich aus
   * aufnimmt (meist 44,1 oder 48 kHz in Opus) waere dort nicht lesbar. */
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

  /* --- Der Ring ---------------------------------------------------------- */

  /* Der Ring atmet mit dem Pegel: Eine Zahl zwischen 0 und 1 geht als
   * CSS-Variable an die Tafel, den Rest macht sprechcoach.css. Schnell
   * hinauf, langsam herunter -- ohne das Nachlaufen zittert er bei jedem
   * Zischlaut, und ruhig soll er sein. Bei prefers-reduced-motion steht
   * statt des Rings ein Balken mit Zahl, in Fuenferschritten. */
  function ringAnzeigen(pegel, jetzt) {
    var ruhig = ruhigGewuenscht();
    var ziel = Math.max(0, Math.min(1, (pegel - stillSchwelle()) / 0.1));
    ringWert = ziel > ringWert ? ziel : ringWert * 0.85;
    ruhigWert = ruhigWert * 0.7 + Math.min(1, pegel * 6) * 0.3;
    if (jetzt - letzteAnzeige < (ruhig ? RAHMEN_RUHIG_MS : RAHMEN_MS)) { return; }
    letzteAnzeige = jetzt;
    if (ruhig) {
      var prozent = Math.round(ruhigWert * 20) * 5;
      if (ruhefuellung) { ruhefuellung.style.width = Math.max(3, prozent) + "%"; }
      if (ruhewert && ruhewert.textContent !== prozent + " %") {
        ruhewert.textContent = prozent + " %";
      }
      return;
    }
    if (ring) { ring.style.setProperty("--pegel", ringWert.toFixed(3)); }
  }

  function ringFlachlegen() {
    ringWert = 0;
    ruhigWert = 0;
    if (ring) { ring.style.setProperty("--pegel", "0"); }
    if (ruhefuellung) { ruhefuellung.style.width = "3%"; }
    if (ruhewert) { ruhewert.textContent = "0 %"; }
  }

  /* --- Zuhoeren: Anfang, Ende, Pause ------------------------------------- */

  /* Der Geraeuschboden faellt sofort auf jeden leiseren Block und steigt nur
   * langsam. So liegt er nach wenigen Sekunden beim Rauschen des Zimmers und
   * nicht bei der Stimme.
   *
   * IN WELCHE RICHTUNG DIESE SCHAETZUNG IRREN DARF: Haelt sie Zimmerlaerm
   * fuer eine Stimme, endet die Aeusserung spaeter oder erst an der
   * Hoechstdauer -- das kostet Wartezeit. Haelt sie umgekehrt eine leise
   * Stimme fuer Stille, wird mitten im Satz abgeschickt, und das Kind
   * glaubt, das Geraet hoere nicht zu. Darum steigt der Boden langsam und
   * faellt sofort, und darum ist die Pause bei kurzen Aeusserungen laenger. */
  function bodenNachziehen(pegel) {
    if (pegel < boden) { boden = pegel; }
    else { boden = boden * 0.99 + pegel * 0.01; }
  }

  function sprechSchwelle() {
    return Math.min(BODEN_GRENZE, Math.max(SPRECH_SCHWELLE, boden * BODEN_FAKTOR));
  }

  function stillSchwelle() {
    return Math.min(BODEN_GRENZE, Math.max(STILL_SCHWELLE, boden * 2));
  }

  /* Die Pause, die DIESE Aeusserung beendet. Nicht fest: Wer erst "I ..."
   * gesagt hat, bekommt 1,5 Sekunden, nicht 0,9 -- sonst ist das Wort, das
   * gerade gesucht wird, schon weg. Dasselbe in den ersten zweieinhalb
   * Sekunden einer Aeusserung, weil Anfaenge stockend sind. */
  function pauseFuer(a, jetzt) {
    if (a.stimmeMs < KURZ_GESPROCHEN_MS) { return PAUSE_LANG_MS; }
    if (jetzt - a.beginn < ANFANG_MS) { return PAUSE_LANG_MS; }
    return PAUSE_MS;
  }

  function aeusserungBeginnen(jetzt) {
    aeusserung = {
      stuecke: vorlauf.slice(),
      proben: 0,
      beginn: jetzt,
      letzteStimme: jetzt,
      stimmeMs: lautMs,
      /* Wobei sie anfing: Danach richtet sich, was mit ihrem Text
       * geschieht (siehe hoerenErgebnis). Unterbricht sie den Coach, wird
       * gemerkt, was er sagte und wo er war -- fuer den Echo-Abgleich und
       * fuer das Weiterlesen. Lief gerade ein Zug, hat der Coach sie noch
       * nicht gehoert; dann wird sie zum Nachtrag. */
      lage: lage,
      waehrendZug: zugUnterwegs,
      vorgelesen: lage === "spricht" ? vorgelesen : "",
      stelle: leseStelle
    };
    for (var i = 0; i < vorlauf.length; i++) { aeusserung.proben += vorlauf[i].length; }
    vorlauf = [];
    vorlaufMs = 0;
    lautMs = 0;
    erinnert = false;
    stilleSeit = 0;

    /* Ein halber Satz wartete auf seinen Rest -- hier kommt er. */
    if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }

    if (lage === "spricht") {
      /* Das Kind unterbricht. Die Stimme des Coaches verstummt sofort; ob
       * es wirklich das Kind war und nicht der eigene Lautsprecher, zeigt
       * sich erst am abgeschriebenen Text. */
      vorlesenAbbrechen();
      lageSetzen("hoert");
    }
    hinweisZeigen("");
  }

  /* Ende einer Aeusserung. Was zu kurz war, war ein Geraeusch und wird
   * verworfen -- ohne Meldung, denn das Kind hat ja nichts gesagt. */
  function aeusserungBeenden() {
    var a = aeusserung;
    aeusserung = null;
    laut = false;
    lautMs = 0;
    if (!a) { fortsetzen(); return; }
    var dauerMs = a.proben / abtastrate() * 1000;
    if (a.stimmeMs < MINDEST_STIMME_MS || dauerMs < MINDESTDAUER_MS) {
      if (a.lage === "spricht" && a.vorgelesen) {
        /* Der Coach wurde fuer ein Geraeusch unterbrochen. Weiterlesen. */
        vorlesenFortsetzen(a.vorgelesen, a.stelle, weiterHoeren);
        return;
      }
      fortsetzen();
      return;
    }
    warteschlange.push({
      proben: zusammenfuegen(a.stuecke),
      lage: a.lage,
      waehrendZug: a.waehrendZug,
      vorgelesen: a.vorgelesen,
      stelle: a.stelle
    });
    naechsteAbschreiben();
  }

  /* Ein Block Ton aus dem Mikrofon, rund 50 Millisekunden. Hier wird
   * entschieden, ob gerade gesprochen wird, ob eine Aeusserung anfaengt oder
   * aufhoert -- und ob das Kind den Coach unterbricht. */
  function blockVerarbeiten(proben) {
    if (!hoertZu() || abschlussLaeuft) { return; }
    var jetzt = Date.now();
    var dauer = proben.length / abtastrate() * 1000;
    var pegel = rms(proben);
    var coachSprichtGerade = (lage === "spricht");
    /* Der Echo-Schutz gilt, solange der Coach spricht, und noch einen
     * Augenblick danach: Der letzte Laut aus dem Lautsprecher darf nicht
     * als erstes Wort des Kindes anfangen. */
    var echoSchutz = coachSprichtGerade || jetzt < echoBis;

    /* Waehrend der Coach spricht, steht der Boden: Der eigene Lautsprecher
     * soll ihn nicht hochziehen. Und die Schwellen liegen hoeher, denn
     * was jetzt ankommt, ist zum Teil der Coach selbst. */
    if (!echoSchutz) { bodenNachziehen(pegel); }
    var faktor = echoSchutz ? echoFaktor : 1;
    if (pegel >= sprechSchwelle() * faktor) { laut = true; }
    else if (pegel < stillSchwelle() * faktor) { laut = false; }

    ringAnzeigen(pegel, jetzt);

    if (!aeusserung) {
      vorlauf.push(proben);
      vorlaufMs += dauer;
      while (vorlauf.length > 1 && vorlaufMs > VORLAUF_MS + ANLAUF_ECHO_MS) {
        vorlaufMs -= vorlauf[0].length / abtastrate() * 1000;
        vorlauf.shift();
      }
      if (laut) { lautMs += dauer; } else { lautMs = 0; }
      /* Eine Aeusserung faengt in jeder der drei Lagen an: im Zuhoeren
       * sowieso, waehrend des Abschreibens (das Kind spricht weiter, der
       * Rest wird angehaengt), waehrend der Coach spricht (Unterbrechung)
       * und waehrend er ueberlegt (dann wird sie zum Nachtrag, siehe
       * hoerenErgebnis). Nichts, was gesagt wurde, faellt unter den Tisch. */
      if (lautMs >= (echoSchutz ? ANLAUF_ECHO_MS : ANLAUF_MS)) {
        aeusserungBeginnen(jetzt);
      }
      return;
    }

    aeusserung.stuecke.push(proben);
    aeusserung.proben += proben.length;
    if (laut) {
      aeusserung.letzteStimme = jetzt;
      aeusserung.stimmeMs += dauer;
    }
    var alter = jetzt - aeusserung.beginn;
    if (alter >= HOECHSTDAUER_MS) {
      hinweisZeigen("Das war lang – ich schicke es jetzt ab.");
      aeusserungBeenden();
      return;
    }
    if (!laut && (jetzt - aeusserung.letzteStimme) >= pauseFuer(aeusserung, jetzt)) {
      aeusserungBeenden();
    }
  }

  /* Der Sekundenzeiger, viermal je Sekunde. Er sorgt dafuer, dass lange
   * Stille nicht ins Leere laeuft: Nach ERINNERUNG_MS wiederholt der Coach
   * seine Frage einmal (Regel 4 der Recherche: nachhelfen durch langsame
   * Wiederholung, nie durch Themenwechsel), und der Ausweg wird genannt. */
  function ticken() {
    if (lage !== "hoert" || aeusserung || offenesFragment || hoerenUnterwegs) {
      stilleSeit = 0;
      return;
    }
    if (!stilleSeit) { stilleSeit = Date.now(); return; }
    if (erinnert || (Date.now() - stilleSeit) < ERINNERUNG_MS) { return; }
    erinnert = true;
    hinweisZeigen("Ich höre zu. Sag einfach, was dir einfällt – oder tipp auf " +
      "„Ich komme nicht weiter“.");
    var satz = letzterCoachsatz();
    if (satz && letzterZugIstVomCoach() && vorlesenAn && stimme) {
      coachSpricht(satz, false);
    }
  }

  function taktStarten() {
    if (takt) { return; }
    takt = window.setInterval(ticken, 250);
  }

  function spurenSchalten(an) {
    if (!strom) { return; }
    try {
      strom.getTracks().forEach(function (spur) { spur.enabled = !!an; });
    } catch (e) { /* aeltere Browser kennen enabled nicht */ }
  }

  function aufraeumen() {
    if (takt) { window.clearInterval(takt); takt = null; }
    if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }
    ringFlachlegen();
    if (verarbeiter) {
      try {
        if (verarbeiter.port) { verarbeiter.port.onmessage = null; }
        verarbeiter.onaudioprocess = null;
        verarbeiter.disconnect();
      } catch (e) { /* schon getrennt */ }
      verarbeiter = null;
    }
    if (stummer) { try { stummer.disconnect(); } catch (e) { /* schon zu */ } stummer = null; }
    if (quelle) { try { quelle.disconnect(); } catch (e) { /* schon zu */ } quelle = null; }
    if (strom) {
      strom.getTracks().forEach(function (spur) { spur.stop(); });
      strom = null;
    }
    if (kontext && kontext.state !== "closed") {
      try { kontext.close(); } catch (e) { /* schon zu */ }
    }
    kontext = null;
    aeusserung = null;
    vorlauf = [];
    vorlaufMs = 0;
    warteschlange = [];
    offenesFragment = null;
    nachtrag = [];
  }

  /* Das Mikrofon verweigert, keines da, belegt. Das ist kein Fehler der
   * lernenden Person, also kein roter Kasten -- der Weg ueber die Tastatur
   * wird einfach aufgeklappt, und der Knopf bietet einen neuen Versuch. */
  function ohneMikrofon(meldung) {
    startetGerade = false;
    mikroVerweigert = true;
    aufraeumen();
    lageSetzen("aus");
    hinweisZeigen(meldung || "Ohne Mikrofon geht es gesprochen nicht. Tipp deine " +
      "Antwort – das zählt genauso.");
    if (tippen) { tippen.open = true; }
  }

  /* Haengt die Verarbeitung an den Strom: AudioWorklet, wenn der Browser
   * ihn hat (eigener Faden, keine Aussetzer beim Scrollen), sonst der alte
   * ScriptProcessor. Beide liefern dieselben Bloecke an blockVerarbeiten. */
  function leitungLegen(erhalten) {
    strom = erhalten;
    quelle = kontext.createMediaStreamSource(strom);

    /* Ein Ausgang mit Verstaerkung null. Manche Browser rechnen nur, was
     * bis zum Lautsprecher durchverbunden ist. Null, damit die eigene
     * Stimme nicht zurueckkommt. */
    stummer = kontext.createGain();
    stummer.gain.value = 0;
    stummer.connect(kontext.destination);

    function mitScriptProcessor() {
      if (!kontext.createScriptProcessor) { return false; }
      var groesse = abtastrate() > 24000 ? 2048 : 1024;   // etwa 50 ms
      try {
        verarbeiter = kontext.createScriptProcessor(groesse, 1, 1);
      } catch (e) {
        return false;
      }
      verarbeiter.onaudioprocess = function (ereignis) {
        blockVerarbeiten(new Float32Array(ereignis.inputBuffer.getChannelData(0)));
      };
      quelle.connect(verarbeiter);
      verarbeiter.connect(stummer);
      return true;
    }

    function fertig() {
      startetGerade = false;
      if (lage === "fertig") { aufraeumen(); return; }
      boden = BODEN_START;
      laut = false;
      lautMs = 0;
      vorlauf = [];
      vorlaufMs = 0;
      taktStarten();
      hinweisZeigen("");
      if (tippen && tippen.open) {
        /* Wer "oder tippen" offen hat, will tippen. Das Mikrofon steht
         * bereit, sobald der Kasten zugeht. */
        lageSetzen("tippt");
        return;
      }
      lageSetzen("hoert");
      ansagen("Ich höre zu. Sprich einfach.", "");
      /* Der Coach hat die letzte Frage gestellt, aber noch nie laut: Beim
       * Laden fehlte die Beruehrung. Jetzt ist sie da. */
      if (letzterZugIstVomCoach()) { coachSpricht(letzterCoachsatz(), false); }
    }

    function ohneLeitung() {
      ohneMikrofon("Dieser Browser kann den Ton nicht messen. Tipp deine " +
        "Antwort – das zählt genauso.");
    }

    if (WORKLET_URL && kontext.audioWorklet && window.AudioWorkletNode) {
      kontext.audioWorklet.addModule(WORKLET_URL).then(function () {
        if (!kontext || !quelle) { return; }
        try {
          verarbeiter = new window.AudioWorkletNode(kontext, "sprechcoach-sammler", {
            numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1
          });
        } catch (e) {
          if (!mitScriptProcessor()) { ohneLeitung(); return; }
          fertig();
          return;
        }
        verarbeiter.port.onmessage = function (ereignis) {
          if (ereignis.data && ereignis.data.length) { blockVerarbeiten(ereignis.data); }
        };
        quelle.connect(verarbeiter);
        verarbeiter.connect(stummer);
        fertig();
      }).catch(function () {
        if (!kontext || !quelle) { return; }
        if (!mitScriptProcessor()) { ohneLeitung(); return; }
        fertig();
      });
      return;
    }
    if (!mitScriptProcessor()) { ohneLeitung(); return; }
    fertig();
  }

  /* Der Starttipp. Alles, was eine Beruehrung braucht, passiert HIER und
   * nicht erst, wenn das Mikrofon antwortet: Klangraum anlegen und
   * aufwecken, Stimme freischalten. getUserMedia selbst darf danach
   * kommen -- die Erlaubnisfrage ist ohnehin eine eigene Beruehrung. */
  function gespraechStarten() {
    if (!MIKRO_MOEGLICH || startetGerade || strom || lage === "fertig") { return; }
    startetGerade = true;
    fehlerVerbergen();
    stimmeFreischalten();

    try {
      kontext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: ABTASTRATE
      });
    } catch (e) {
      try {
        kontext = new (window.AudioContext || window.webkitAudioContext)();
      } catch (e2) {
        ohneMikrofon();
        return;
      }
    }
    if (kontext.state === "suspended" && kontext.resume) {
      try {
        var geweckt = kontext.resume();
        if (geweckt && geweckt.then) { geweckt.then(null, function () { /* spaeter */ }); }
      } catch (e) { /* dann eben nicht */ }
    }
    hinweisZeigen("Das Mikrofon wird gefragt …");

    navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,   // der Coach spricht ueber denselben Lautsprecher
        noiseSuppression: true,
        autoGainControl: true     // Kinder sprechen leise
      }
    }).then(function (erhalten) {
      if (lage === "fertig" || !kontext) {
        /* Das Gespraech war schon zu Ende, als die Erlaubnis kam. */
        erhalten.getTracks().forEach(function (spur) { spur.stop(); });
        startetGerade = false;
        return;
      }
      leitungLegen(erhalten);
    }).catch(function () {
      ohneMikrofon();
    });
  }

  /* Zurueck ins Zuhoeren. Der eine Weg, auf dem nach jeder Antwort des
   * Coaches und nach jedem Nebenweg wieder zugehoert wird.
   *
   * `hinweis` wird am Ende gesetzt und nicht vorher: Wer hier einen Satz
   * mitgibt, will ihn im neuen Zustand lesen, und das Zuruecksetzen wischt
   * die Tafel sonst gerade wieder leer. */
  function weiterHoeren(hinweis) {
    if (lage === "fertig") { return; }
    if (tippen && tippen.open) {
      lageSetzen("tippt");
      hinweisZeigen(hinweis || "");
      return;
    }
    if (!MIKRO_MOEGLICH) {
      lageSetzen("aus");
      hinweisZeigen(hinweis || "");
      return;
    }
    if (!strom) {
      /* Wer das Mikrofon abgelehnt hat, bekommt nicht "Tipp einmal, dann
       * geht es los" vorgesetzt: Das waere ein Versprechen, das der Browser
       * nicht mehr einloest. */
      lageSetzen(mikroVerweigert ? "aus" : "start");
      hinweisZeigen(hinweis || "");
      return;
    }
    if (document.hidden) {
      lageSetzen("weg");
      return;
    }
    if (kontext && kontext.state !== "running") {
      /* Der Klangraum schlaeft ("suspended", auf iOS auch "interrupted").
       * Am Rechner weckt ihn ein Aufruf, auf iOS nur eine Beruehrung --
       * dann bleibt "Weiter zuhoeren" stehen. */
      try {
        var geweckt = kontext.resume();
        if (geweckt && geweckt.then) {
          geweckt.then(function () {
            if (lage === "weg" && !document.hidden) { weiterHoeren(hinweis); }
          }, function () { /* iOS: erst der Knopf */ });
        }
      } catch (e) { /* dann eben der Knopf */ }
      if (kontext.state !== "running") {
        lageSetzen("weg");
        return;
      }
    }
    /* Was das Kind sagte, waehrend der Coach ueberlegte, geht jetzt als
     * naechster Beitrag -- nichts davon ist verloren. */
    if (nachtrag.length && !zugUnterwegs) {
      eigenenZugZeigen(nachtrag.join(" "), false);
      zugAbschicken("", "");
      return;
    }
    stilleSeit = 0;
    lageSetzen("hoert");
    hinweisZeigen(hinweis || "");
    if (ungelesen) {
      /* Die Antwort kam, als das Fenster weg war. Jetzt wird sie gelesen. */
      var satz = ungelesen;
      ungelesen = "";
      coachSpricht(satz, false);
      return;
    }
    fortsetzen();
  }

  function zuhoerenAnhalten() {
    if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }
    aeusserung = null;
    laut = false;
    lautMs = 0;
    vorlauf = [];
    vorlaufMs = 0;
    spurenSchalten(false);
    ringFlachlegen();
  }

  /* --- Abschreiben, Sinneinheit, Echo ------------------------------------ */

  /* Was haengt noch? Nach jedem Ende einer Aeusserung und nach jedem
   * Ergebnis vom Server wird hier geprueft, ob ein halber Satz noch auf
   * seinen Rest wartet -- und ob die Wartezeit laeuft. */
  function fortsetzen() {
    if (lage === "fertig" || lage === "tippt" || lage === "weg" || lage === "aus") { return; }
    if (hoerenUnterwegs || aeusserung) { return; }
    if (warteschlange.length) { naechsteAbschreiben(); return; }
    if (offenesFragment) {
      /* Gewartet wird im Zuhoeren, nicht im Nachdenken: Der Ring soll
       * zeigen, dass der Rest jetzt willkommen ist. */
      if (lage === "denkt") { lageSetzen("hoert"); }
      if (!fragmentTakt) {
        fragmentTakt = window.setTimeout(fragmentAbschicken, offenesFragment.warten);
      }
      return;
    }
    if (zugUnterwegs) { return; }
    if (lage === "denkt") { lageSetzen("hoert"); }
  }

  /* Die Wartezeit ist um, der Rest kam nicht. Der halbe Satz geht so, wie er
   * ist -- der Coach fragt dann eben nach. */
  function fragmentAbschicken() {
    fragmentTakt = null;
    var f = offenesFragment;
    offenesFragment = null;
    if (!f) { return; }
    if (zugUnterwegs) {
      /* Inzwischen laeuft ein Zug (getippt, oder ein Nachtrag). Der halbe
       * Satz geht danach, als Erstes. */
      nachtrag.unshift(f.text);
      nachtragErkannt = nachtragErkannt || f.erkannt;
      return;
    }
    eigenenZugZeigen(f.text, false);
    zugAbschicken(f.text, f.erkannt);
  }

  /* Klingt das Abgeschriebene wie das, was der Lautsprecher gerade sagte?
   * Gezaehlt wird, welcher Anteil der gehoerten Woerter im vorgelesenen
   * Satz vorkommt. Unter drei Woertern wird nicht entschieden: Ein "Yes"
   * steht in jedem zweiten Coachsatz, und ein echtes "Yes" des Kindes darf
   * nicht als Echo sterben. */
  function woerterVon(text) {
    var liste = String(text || "").toLowerCase().match(/[\wäöüßàâçéèêëîïôûùÿñæœáíóú'’]+/g) || [];
    var ergebnis = {};
    for (var i = 0; i < liste.length; i++) { ergebnis[liste[i].replace("’", "'")] = true; }
    return ergebnis;
  }

  function istEcho(text, vorgelesener) {
    if (!vorgelesener) { return false; }
    var gehoert = String(text || "").toLowerCase().match(/[\wäöüßàâçéèêëîïôûùÿñæœáíóú'’]+/g) || [];
    if (gehoert.length < 3) { return false; }
    var coachwoerter = woerterVon(vorgelesener);
    var treffer = 0;
    for (var i = 0; i < gehoert.length; i++) {
      if (coachwoerter[gehoert[i].replace("’", "'")]) { treffer++; }
    }
    return treffer / gehoert.length >= ECHO_UEBERLAPPUNG;
  }

  function naechsteAbschreiben() {
    if (hoerenUnterwegs) { return; }
    if (!warteschlange.length) { fortsetzen(); return; }
    var eintrag = warteschlange.shift();
    hoerenUnterwegs = true;
    if (lage === "hoert") {
      lageSetzen("denkt");
      ansagen("Der Rechner der Schule schreibt mit.", "");
    }

    var rate = abtastrate();
    var proben = auf16k(eintrag.proben, rate);
    eintrag.proben = null;   // die Aufnahme lebt nur bis zum Abschicken
    var daten = new window.FormData();
    daten.append("aufnahme", alsWav(proben, ABTASTRATE), "aufnahme.wav");
    /* Keine Zielsprache im Gepaeck, und das ist Absicht: Whisper bestimmt
     * die Sprache selbst, sonst koennte die Sprachsperre nicht wissen, OB
     * ein Kind in der Zielsprache gesprochen hat. */

    window.fetch(HOEREN_URL, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert() },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json().catch(function () { return null; });
    }).then(function (ergebnis) {
      hoerenUnterwegs = false;
      hoerenErgebnis(eintrag, ergebnis);
    }).catch(function () {
      hoerenUnterwegs = false;
      hoerenErgebnis(eintrag, null);
    });
  }

  /* Was der Server ueber eine Aeusserung sagt, und was daraus folgt. Drei
   * Herkuenfte, drei Wege:
   *
   *   hoert    -> Fragment? warten. Sonst: Zug. Spricht das Kind gerade
   *               weiter, wird auch ein ganzer Satz noch kurz zurueckgehalten
   *               und der Rest angehaengt (Regel 4: Lernende reden oft noch
   *               weiter).
   *   spricht  -> Echo? verwerfen und weiterlesen. Sonst: Unterbrechung, Zug.
   *   denkt    -> der Coach ueberlegt gerade; der Text wartet als Nachtrag.
   */
  function hoerenErgebnis(eintrag, ergebnis) {
    if (!ergebnis || !ergebnis.ok) {
      /* Nicht angekommen oder nicht lesbar: ein neuer Anlauf, kein roter
       * Kasten. Ein halber Satz, der wartet, geht dann eben allein. */
      if (eintrag.lage === "spricht" && eintrag.vorgelesen) {
        vorlesenFortsetzen(eintrag.vorgelesen, eintrag.stelle, weiterHoeren);
        return;
      }
      hinweisZeigen((ergebnis && ergebnis.meldung) ||
        "Das ist nicht angekommen. Sag es bitte noch einmal.");
      if (offenesFragment) { offenesFragment.warten = NACHSATZ_WARTE_MS; }
      naechsteAbschreiben();
      return;
    }

    if (ergebnis.stille) {
      /* Kein Sprachinhalt: kein Zug. Einfach weiterhoeren. */
      if (eintrag.lage === "spricht" && eintrag.vorgelesen) {
        vorlesenFortsetzen(eintrag.vorgelesen, eintrag.stelle, weiterHoeren);
        return;
      }
      if (offenesFragment) { offenesFragment.warten = NACHSATZ_WARTE_MS; }
      naechsteAbschreiben();
      return;
    }

    var text = getrimmt(ergebnis.text);
    var erkannt = ergebnis.erkannt || "";

    if (!hoertZu()) {
      /* Inzwischen wird getippt, das Fenster ist weg oder das Gespraech
       * ist aus. Nichts geht verloren: ins Feld, in den Nachtrag, oder --
       * am Ende -- nirgendwohin, denn dann nimmt niemand mehr etwas an. */
      if (lage === "tippt" && feld && !feld.value) { feld.value = text; }
      else if (lage === "weg" && nachtrag.length < 2) {
        nachtrag.push(text);
        nachtragErkannt = nachtragErkannt || erkannt;
      }
      naechsteAbschreiben();
      return;
    }

    if (eintrag.lage === "spricht") {
      if (istEcho(text, eintrag.vorgelesen)) {
        /* Der Lautsprecher hat sich selbst unterbrochen. Beim naechsten Mal
         * muss es lauter sein, und der Coach liest weiter. */
        echoFaktor = Math.min(ECHO_FAKTOR_HOECHSTENS, echoFaktor * 1.5);
        vorlesenFortsetzen(eintrag.vorgelesen, eintrag.stelle, weiterHoeren);
        return;
      }
      /* Eine echte Unterbrechung. Was der Coach noch sagen wollte, bleibt
       * im Verlauf lesbar; gesprochen wird jetzt die Antwort darauf. */
    }

    if (eintrag.waehrendZug || zugUnterwegs) {
      /* Der Coach hat das noch nicht gehoert: Er ueberlegte gerade. Es
       * kommt als naechster Beitrag, sobald er fertig gesprochen hat. */
      if (nachtrag.length < 2) {
        nachtrag.push(text);
        nachtragErkannt = nachtragErkannt || erkannt;
        hinweisZeigen("Ich habe dich gehört – das kommt gleich dran.");
      }
      naechsteAbschreiben();
      return;
    }

    if (offenesFragment) {
      /* Der Rest ist da. Beides zusammen ist ein Zug, egal wie der Rest
       * klingt -- nach dem zweiten Stueck wird auf jeden Fall gesendet. */
      text = offenesFragment.text + " " + text;
      erkannt = offenesFragment.erkannt || erkannt;
      offenesFragment = null;
      if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }
      eigenenZugZeigen(text, false);
      zugAbschicken(text, erkannt);
      return;
    }

    var kindSprichtWeiter = !!(aeusserung || warteschlange.length);
    if (ergebnis.fragment || kindSprichtWeiter) {
      offenesFragment = {
        text: text,
        erkannt: erkannt,
        warten: ergebnis.fragment ? FRAGMENT_WARTE_MS : NACHSATZ_WARTE_MS
      };
      eigenenZugZeigen(text, true);
      if (lage === "denkt" && !kindSprichtWeiter) { lageSetzen("hoert"); }
      hinweisZeigen(ergebnis.fragment ? "Ich warte noch kurz – sprich einfach weiter." : "");
      naechsteAbschreiben();
      return;
    }

    eigenenZugZeigen(text, false);
    zugAbschicken(text, erkannt);
  }

  /* --- Der Ablauf ---------------------------------------------------------
   *
   * Ob das Gespraech in die naechste Phase geht, entscheidet der Server
   * (Regel 12 des Berichts; ein Systemprompt ist eine Bitte, und eine Seite
   * erst recht). Hier wird nur nachgezogen, was er gemeldet hat: welcher
   * Schritt gerade gilt und der deutsche Satz darunter. Innerhalb des
   * Gespraechs laedt die Seite dafuer nicht neu - sonst muesste das Kind auf
   * manchen Geraeten das Mikrofon noch einmal freigeben. */

  var phasenliste = document.getElementById("coach-phasen");
  var phasenhinweis = document.getElementById("coach-phasenhinweis");

  function phaseZeigen(ergebnis) {
    if (phasenhinweis && ergebnis.phasenhinweis) {
      phasenhinweis.textContent = ergebnis.phasenhinweis;
    }
    if (!phasenliste || !ergebnis.schritt) { return; }
    var jetzt = Number(ergebnis.schritt);
    Array.prototype.forEach.call(phasenliste.children, function (punkt) {
      var nr = Number(punkt.getAttribute("data-nr"));
      punkt.classList.toggle("ist-jetzt", nr === jetzt);
      punkt.classList.toggle("ist-vorbei", nr < jetzt);
      if (nr === jetzt) { punkt.setAttribute("aria-current", "step"); }
      else { punkt.removeAttribute("aria-current"); }
    });
    if (ergebnis.phase_gewechselt && ergebnis.phasenhinweis) {
      ansagen(ergebnis.phasenhinweis, "");
    }
  }

  /* --- Der Zug ----------------------------------------------------------- */

  function zugUebernehmen(ergebnis) {
    if (senden) { senden.disabled = false; }
    var eintrag = zugAnhaengen(true, ergebnis.coach || "",
      ergebnis.uebersetzung || "", ergebnis.korrektur || "",
      !!ergebnis.nicht_verstanden);
    standSchreiben(ergebnis.zuege);
    phaseZeigen(ergebnis);

    /* Hat der Coach nicht verstanden, tritt der Ausweg einen Schritt vor.
     * Versteht er wieder, zieht er sich zurueck: Ein Knopf, der dauerhaft
     * leuchtet, ist bald wieder unsichtbar. */
    if (ausweg) {
      ausweg.classList.toggle("ist-naeher", !!ergebnis.nicht_verstanden);
    }

    /* Der deutsche Teil nennt nur, wer spricht; der fremdsprachige Satz
     * reist in seinem eigenen lang-span. Die Uebersetzung bleibt draussen:
     * Sie ist zugeklappt, weil sie nicht gleich mitgelesen werden soll. */
    ansagen("Der Coach sagt:", ergebnis.coach || "");
    insBild(eintrag, true);

    if (ergebnis.fertig) {
      /* Erst sprechen, dann abschliessen: Der Schlusssatz soll noch zu
       * hoeren sein. Kommt danach der Rueckblick, ist er eine eigene
       * Ansicht der Seite - die holt das Neuladen, nachdem das Mikrofon zu
       * ist. Unterbrechen laesst sich dieser eine Satz nicht: Es gibt
       * keinen Zug mehr, den eine Unterbrechung ausloesen koennte. */
      abschlussLaeuft = true;
      abschlussDanach = function () {
        abschlussDanach = null;
        fertigSetzen();
        if (ergebnis.neu_laden) { window.location.reload(); }
      };
      if (hoertZu()) { lageSetzen("spricht"); }
      sprechen(ergebnis.coach || "", false, abschlussDanach);
      return;
    }

    if (lage === "weg") {
      /* Im Hintergrund wird nicht vorgelesen. Der Satz steht im Verlauf
       * und wird nachgelesen, sobald das Fenster wieder da ist. */
      ungelesen = ergebnis.coach || "";
      return;
    }
    coachSpricht(ergebnis.coach || "", false);
  }

  /* Ein Beitrag geht an die Ansicht. `erkannt` ist der Sprachcode, den
   * Whisper gemeldet hat; die Ansicht braucht ihn fuer die Sprachsperre --
   * nur mit ihm darf sie einen Beitrag abweisen, denn die Wortliste allein
   * verwechselt ein einzelnes "Yes." zu leicht. */
  function zugSenden(text, herkunft, erkannt, zurueck) {
    if (!form) { return; }
    var daten = new window.FormData();
    daten.append("text", text);
    daten.append("herkunft", herkunft);
    if (SPRACHE) { daten.append("sprache", SPRACHE); }
    if (erkannt) { daten.append("erkannt", erkannt); }

    zugUnterwegs = true;
    if (hoertZu()) { lageSetzen("denkt"); }
    ansagen("Der Coach überlegt.", "");

    window.fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrfWert(), "X-Antwort": "json" },
      credentials: "same-origin",
      body: daten
    }).then(function (antwort) {
      return antwort.json().catch(function () { return null; });
    }).then(function (ergebnis) {
      zugUnterwegs = false;
      if (!ergebnis || !ergebnis.ok) {
        zurueck((ergebnis && ergebnis.meldung) ||
          "Das hat nicht geklappt. Probier es noch einmal.");
        return;
      }
      fehlerVerbergen();
      zugUebernehmen(ergebnis);
    }).catch(function () {
      zugUnterwegs = false;
      zurueck("Die Verbindung hat nicht geklappt. Probier es gleich noch einmal.");
    });
  }

  /* Der gesprochene Beitrag geht ab -- von selbst, ohne Knopf. Es gibt
   * bewusst keinen Zwischenschritt zum Nachlesen: Die Vorgabe lautet "die
   * Antwort kommt automatisch". Wer nachlesen und berichtigen will, tippt. */
  function zugAbschicken(text, erkannt) {
    var eigener = eigenenZugAbschliessen();
    erinnert = false;
    if (offenesFragment) {
      /* Ein halber Satz, der noch wartete, gehoert dazu -- er fiel zuerst. */
      text = getrimmt(offenesFragment.text + " " + text);
      erkannt = offenesFragment.erkannt || erkannt;
      offenesFragment = null;
      if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }
    }
    if (nachtrag.length) {
      /* Der Nachtrag kommt zuerst: Er wurde zuerst gesagt. */
      text = getrimmt(nachtrag.join(" ") + " " + text);
      erkannt = nachtragErkannt || erkannt;
      nachtrag = [];
      nachtragErkannt = "";
      if (eigener) {
        var rumpf = eigener.querySelector(".zug-text");
        if (rumpf) { rumpf.textContent = text; }
      }
    }
    if (!text) { weiterHoeren(); return; }
    zugSenden(text, "sprache", erkannt, function (meldung) {
      /* Die Aufnahme ist weg -- sie wird nicht aufbewahrt, sie ist das
       * Heikelste, was hier anfallen koennte. Also wandert der erkannte
       * Text ins Textfeld, damit nichts verloren ist, und der Zug aus
       * dem Verlauf. */
      if (eigener && eigener.parentNode) {
        eigener.parentNode.removeChild(eigener);
      }
      if (feld && !feld.value) { feld.value = text; }
      fehlerZeigen(meldung + " Dein Satz steht unter „oder tippen“ im Feld.");
      weiterHoeren();
    });
  }

  /* --- Der stille Ausweg ------------------------------------------------- */

  function hilfeVerbergen() {
    if (hilfekasten) { hilfekasten.hidden = true; }
  }

  function hilfeZeigen(erklaerung, beispiel) {
    if (!hilfekasten) { return; }
    if (hilfetext) { hilfetext.textContent = erklaerung || ""; }
    if (hilfebeispiel) { hilfebeispiel.hidden = !beispiel; }
    if (hilfesatz) { hilfesatz.textContent = beispiel || ""; }
    if (hilfehoeren) { hilfehoeren.hidden = !(beispiel && stimme); }
    hilfekasten.hidden = false;
    insBild(hilfekasten, true);
    ansagen(erklaerung || "", beispiel || "");

    /* Den Beispielsatz gleich vorsprechen: Wer nicht weiterweiss, braucht
     * nicht nur den Satz, sondern seinen Klang. */
    if (beispiel) { coachSpricht(beispiel, true); }
  }

  if (auswegform) {
    auswegform.addEventListener("submit", function (ereignis) {
      /* Ohne fetch bleibt es ein gewoehnliches Formular an hilfe_url. */
      if (!window.fetch || !window.FormData) { return; }
      ereignis.preventDefault();
      if (ausweg) { ausweg.disabled = true; }
      hilfeVerbergen();
      /* Der Ausweg ist kein Zug: Was gerade halb gesagt war, bleibt stehen
       * und wird nicht abgeschickt. */
      if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }

      window.fetch(auswegform.action, {
        method: "POST",
        headers: { "X-CSRFToken": csrfWert(), "X-Antwort": "json" },
        credentials: "same-origin",
        body: new window.FormData()
      }).then(function (antwort) {
        return antwort.json().catch(function () { return null; });
      }).then(function (ergebnis) {
        if (ausweg) { ausweg.disabled = false; }
        if (!ergebnis || !ergebnis.ok) {
          /* Auch hier kein roter Kasten: Der Ausweg ist der letzte Halt,
           * und eine Fehlermeldung daran waere die falsche Nachricht. Der
           * Satz sagt, was jetzt hilft. */
          hilfeZeigen((ergebnis && ergebnis.meldung) ||
            "Die Hilfe kommt gerade nicht. Sag einfach einzelne Wörter – " +
            "das genügt dem Coach.", "");
          return;
        }
        hilfeZeigen(ergebnis.erklaerung || "", ergebnis.beispiel || "");
      }).catch(function () {
        if (ausweg) { ausweg.disabled = false; }
        hilfeZeigen("Die Hilfe kommt gerade nicht. Sag einfach einzelne " +
          "Wörter – das genügt dem Coach.", "");
      });
    });
  }

  if (hilfehoeren) {
    hilfehoeren.addEventListener("click", function () {
      coachSpricht(hilfesatz ? hilfesatz.textContent : "", true);
    });
  }

  if (hilfezu) {
    hilfezu.addEventListener("click", function () {
      hilfeVerbergen();
      if (ausweg) { ausweg.classList.remove("ist-naeher"); }
      weiterHoeren();
    });
  }

  /* --- Die Bedienung ----------------------------------------------------- */

  /* Ein Feld, ein Knopf, ein Aufklapper: Dort bedeutet die Leertaste etwas
   * anderes, und die Abkuerzung darf ihr nicht dazwischenfahren. */
  function istBedienelement(element) {
    if (!element || !element.tagName) { return false; }
    var name = element.tagName.toUpperCase();
    if (name === "INPUT" || name === "TEXTAREA" || name === "SELECT" ||
        name === "BUTTON" || name === "SUMMARY" || name === "A" ||
        name === "OPTION" || name === "DETAILS") {
      return true;
    }
    return !!element.isContentEditable;
  }

  /* Die Leertaste als Abkuerzung, nirgends angeschrieben und nirgends
   * noetig: Waehrend gesprochen wird, schickt sie sofort ab, statt die
   * Pause abzuwarten; waehrend der Coach spricht, bringt sie ihn zum
   * Schweigen. Sonst bleibt sie, was sie immer war: ein Bildschirm weiter. */
  document.addEventListener("keydown", function (ereignis) {
    var istLeertaste = (ereignis.code === "Space" || ereignis.key === " " ||
      ereignis.keyCode === 32);
    if (!istLeertaste || ereignis.repeat) { return; }
    if (ereignis.ctrlKey || ereignis.altKey || ereignis.metaKey || ereignis.shiftKey) {
      return;
    }
    if (istBedienelement(ereignis.target) || istBedienelement(document.activeElement)) {
      return;
    }
    if (lage === "hoert" && aeusserung) {
      ereignis.preventDefault();
      aeusserungBeenden();
      return;
    }
    if (lage === "hoert" && offenesFragment && !hoerenUnterwegs) {
      ereignis.preventDefault();
      if (fragmentTakt) { window.clearTimeout(fragmentTakt); fragmentTakt = null; }
      fragmentAbschicken();
      return;
    }
    if (lage === "spricht") {
      ereignis.preventDefault();
      vorlesenAbbrechen();
      if (abschlussDanach) { abschlussDanach(); return; }
      weiterHoeren();
    }
  });

  if (funk) {
    funk.addEventListener("click", function () {
      /* Der Knopf heisst "Gespraech starten", "Weiter zuhoeren" oder
       * "Mikrofon noch einmal versuchen" -- und der Klick ist zugleich die
       * Beruehrung, die der Browser fuer Mikrofon, Klangraum und Stimme
       * verlangt. Steht der Strom schon, fehlt nur diese Beruehrung; ein
       * zweites getUserMedia waere eine zweite Erlaubnisfrage. */
      if (strom) {
        stimmeFreischalten();
        if (kontext && kontext.state !== "running" && kontext.resume) {
          try {
            var geweckt = kontext.resume();
            if (geweckt && geweckt.then) {
              geweckt.then(function () { if (lage === "weg") { weiterHoeren(); } },
                           function () { /* bleibt bei "weg" */ });
            }
          } catch (e) { /* dann eben nicht */ }
        }
        weiterHoeren();
        return;
      }
      mikroVerweigert = false;
      gespraechStarten();
    });
  }

  /* Solange getippt wird, hoert das Geraet nicht zu: Ein Mikrofon, das
   * mitlaeuft, waehrend jemand tippt, nimmt das halbe Zimmer auf. Und die
   * Leertaste gehoert dann dem Textfeld. */
  if (tippen) {
    tippen.addEventListener("toggle", function () {
      if (tippen.open) {
        if (lage === "fertig" || abschlussLaeuft) { return; }
        vorlesenAbbrechen();
        zuhoerenAnhalten();
        /* Ein halber Satz, der noch wartete, wandert ins Feld: Dort kann er
         * zu Ende geschrieben werden, und nichts ist verloren. */
        if (offenesFragment) {
          var rest = offenesFragment;
          offenesFragment = null;
          var zug = eigenenZugAbschliessen();
          if (zug && zug.parentNode) { zug.parentNode.removeChild(zug); }
          if (feld && !feld.value) { feld.value = rest.text; }
        }
        lageSetzen("tippt");
      } else if (lage === "tippt") {
        /* Nur, wenn wirklich getippt wurde: Das Skript klappt den Kasten
         * auch selbst zu, und das Ereignis kommt verspaetet -- dann darf es
         * nicht in ein laufendes Vorlesen hineinfahren. */
        weiterHoeren();
      }
    });
  }

  /* Liegt das Blatt im Hintergrund, wird nicht aufgenommen. Die Spuren
   * werden stillgelegt und nicht beendet: Ein beendeter Strom braucht eine
   * neue Erlaubnisfrage, und die kommt im Hintergrund nicht durch. */
  var warAmHoeren = false;
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (abschlussLaeuft) { return; }
      warAmHoeren = hoertZu();
      if (warAmHoeren) {
        /* Was gerade vorgelesen wurde, wird nachgelesen, wenn das Fenster
         * wieder da ist. Erst die Lage setzen, dann anhalten: lageSetzen
         * schaltet die Spuren mit. */
        if (lage === "spricht" && vorgelesen) { ungelesen = vorgelesen; }
        lageSetzen("weg");
        zuhoerenAnhalten();
      }
      vorlesenAbbrechen();
      return;
    }
    if (warAmHoeren) {
      warAmHoeren = false;
      /* Schlaeft der Klangraum (iOS weckt ihn nur in einer Beruehrung),
       * bleibt weiterHoeren bei "weg" stehen, und der Knopf ist der Weg. */
      weiterHoeren();
    }
  });

  if (form) {
    form.addEventListener("submit", function (ereignis) {
      /* Ohne fetch bleibt es ein gewoehnliches Formular. Erst hier wird
       * abgebrochen, nicht vorher: Sonst stuende die Seite auf einem Geraet
       * ohne fetch mit einem Knopf da, der nichts mehr tut. */
      if (!window.fetch || !window.FormData) { return; }
      ereignis.preventDefault();

      var text = feld ? feld.value.replace(/^\s+|\s+$/g, "") : "";
      if (!text) {
        fehlerZeigen("Sag etwas oder schreib etwas – auch ein einzelnes Wort genügt.");
        fokusAuf(feld);
        return;
      }

      fehlerVerbergen();
      if (feld) { feld.value = ""; }
      if (senden) { senden.disabled = true; }
      var eigener = zugAnhaengen(false, text, "", "", false);
      insBild(eigener, true);

      zugSenden(text, "tippen", "", function (meldung) {
        /* Nichts ist verloren: Kommt die Antwort nicht an, wandert der Satz
         * zurueck ins Feld und der Zug aus dem Verlauf. Alles andere waere
         * eine Behauptung, die die Seite nicht halten kann. */
        if (senden) { senden.disabled = false; }
        if (eigener && eigener.parentNode) {
          eigener.parentNode.removeChild(eigener);
        }
        if (feld && !feld.value) { feld.value = text; }
        fehlerZeigen(meldung);
        fokusAuf(feld);
        lageSetzen("tippt");
      });
    });
  }

  /* --- Der Start --------------------------------------------------------- */

  if (fertigfeld && !fertigfeld.hidden) {
    /* Die Ansicht hat das Gespraech schon geschlossen. */
    fertigSetzen();
  } else if (MIKRO_MOEGLICH) {
    /* Das Tippen steht in der Vorlage offen, damit es ohne JavaScript da
     * ist. Jetzt ist JavaScript da und das Sprechen der Hauptweg, also
     * klappt es zu -- gleich hier und nicht erst nach dem Tipp, sonst
     * springt die Seite zweimal. Das Mikrofon wird NICHT von selbst
     * gefragt: Erst der Tipp bringt die Beruehrung, die Klangraum und Stimme
     * ohnehin brauchen. Eine Erlaubnisfrage beim Laden, bevor jemand weiss,
     * worum es geht, wird abgelehnt. */
    if (tippen) { tippen.open = false; }
    lageSetzen("start");
  } else {
    lageSetzen("aus");
    if (tippen) { tippen.open = true; }
  }

  /* Beim Laden steht der offene Satz des Coaches ueber der Steuerung. Ziel
   * und Redemittel stehen darueber - insBild zielt auf den letzten Zug, also
   * bleibt das Gespraech im Blick, nicht die Aufgabenkarte. */
  insBild(letzterZug(), false);
  window.addEventListener("load", function () { insBild(letzterZug(), false); });
})();
