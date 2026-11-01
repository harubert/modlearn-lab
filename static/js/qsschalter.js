/* Der zweite Schalter haengt am ersten.
 *
 * Ohne Qualitaetssicherung gibt es keinen Weg nach draussen, also auch
 * keinen fuer einen Bildausschnitt. Der Server prueft dasselbe noch einmal
 * (views.lehrperson_uebersicht); hier geht es nur darum, dass die
 * Lehrperson keinen Haken setzen kann, der nichts bewirkt.
 */
(function () {
  "use strict";

  var qualitaet = document.getElementById("qualitaetssicherung");
  var bilder = document.getElementById("bilder_pruefen");
  if (!qualitaet || !bilder) { return; }

  function angleichen() {
    bilder.disabled = !qualitaet.checked;
    if (!qualitaet.checked) { bilder.checked = false; }
  }

  qualitaet.addEventListener("change", angleichen);
  angleichen();
})();
