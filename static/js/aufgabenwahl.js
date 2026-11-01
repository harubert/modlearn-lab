/* Die Gespraechsaufgaben beim Anlegen einer Englischstunde, nach Niveau
 * gefiltert.
 *
 * Ohne dieses Skript stehen alle Aufgaben da, jede mit ihren Niveaus, und
 * die Ansicht weist eine unpassende Wahl mit einem Satz zurueck. Mit dem
 * Skript verschwindet, was nicht zum gewaehlten Niveau passt, und ist die
 * gewaehlte Aufgabe darunter, rueckt die Wahl auf die erste passende. Das
 * freie Gespraech passt immer.
 */
(function () {
  "use strict";

  var niveau = document.getElementById("language_level");
  var liste = document.getElementById("aufgabenwahl");
  if (!niveau || !liste) { return; }

  var eintraege = Array.prototype.slice.call(
    liste.querySelectorAll("[data-niveaus]"));

  function filtern() {
    var wert = niveau.value;
    var erste = null;
    var gewaehltSichtbar = false;
    eintraege.forEach(function (eintrag) {
      var passt = (" " + eintrag.getAttribute("data-niveaus") + " ")
        .indexOf(" " + wert + " ") !== -1;
      eintrag.hidden = !passt;
      var knopf = eintrag.querySelector("input[type=radio]");
      if (!knopf) { return; }
      knopf.disabled = !passt;
      if (passt && !erste) { erste = knopf; }
      if (passt && knopf.checked) { gewaehltSichtbar = true; }
    });
    if (!gewaehltSichtbar && erste) { erste.checked = true; }
  }

  niveau.addEventListener("change", filtern);
  filtern();
})();
