/* Der Sammler des Sprechcoaches: laeuft im Klangfaden des Browsers.
 *
 * Ein AudioWorklet bekommt den Ton in Haeppchen von 128 Proben, also alle
 * acht Millisekunden bei 16 kHz. So oft eine Nachricht an die Seite zu
 * schicken waere Verschwendung: Fuer die Pausenerkennung genuegen Bloecke
 * von rund 50 Millisekunden, und der Pegel wird ohnehin erst in der Seite
 * gerechnet. Also wird hier nur gesammelt und in Bloecken weitergereicht.
 *
 * Eigene Datei und nicht im Hauptskript, weil ein Worklet nur als Modul von
 * einer Adresse geladen werden kann. Hier darf class stehen: Browser, die
 * AudioWorklet koennen, koennen auch das. Das Hauptskript (sprechcoach.js)
 * bleibt bei var, weil es auch dort laufen muss, wo dieses Modul fehlt --
 * dann nimmt es den alten ScriptProcessor.
 *
 * `sampleRate` ist im Worklet eine Konstante der Laufzeit, keine eigene.
 */
class SprechcoachSammler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.stuecke = [];
    this.gesammelt = 0;
    this.ziel = Math.max(128, Math.round(sampleRate * 0.05));
  }

  process(eingaenge) {
    const eingang = eingaenge[0];
    if (!eingang || !eingang[0] || !eingang[0].length) { return true; }
    const kanal = eingang[0];
    this.stuecke.push(new Float32Array(kanal));
    this.gesammelt += kanal.length;

    if (this.gesammelt >= this.ziel) {
      const block = new Float32Array(this.gesammelt);
      let pos = 0;
      for (const stueck of this.stuecke) {
        block.set(stueck, pos);
        pos += stueck.length;
      }
      this.stuecke = [];
      this.gesammelt = 0;
      /* Der Puffer wandert mit (zweites Argument), statt kopiert zu werden. */
      this.port.postMessage(block, [block.buffer]);
    }
    return true;
  }
}

registerProcessor("sprechcoach-sammler", SprechcoachSammler);
