/* Schalter, der das Kennwort sichtbar macht.
 *
 * Der Knopf steht im HTML auf hidden und wird erst hier eingeblendet: Ohne
 * JavaScript koennte er nichts tun, und ein Knopf, der nichts tut, ist
 * schlimmer als keiner.
 *
 * Er ist ein Schalter mit Zustand (aria-pressed), kein blosses Symbol. So
 * meldet ein Vorlesewerkzeug, ob das Kennwort gerade sichtbar ist.
 */
(function () {
  "use strict";

  var knopf = document.getElementById("augenknopf");
  var feld = document.getElementById("id_password");
  if (!knopf || !feld) { return; }

  var offen = knopf.querySelector(".auge-offen");
  var zu = knopf.querySelector(".auge-zu");
  var text = document.getElementById("augen-text");

  knopf.hidden = false;

  knopf.addEventListener("click", function () {
    var sichtbar = feld.type === "text";

    feld.type = sichtbar ? "password" : "text";
    knopf.setAttribute("aria-pressed", sichtbar ? "false" : "true");
    offen.hidden = !sichtbar;
    zu.hidden = sichtbar;
    text.textContent = sichtbar ? "Kennwort anzeigen" : "Kennwort verbergen";

    // Die Schreibmarke ans Ende, sonst springt sie in manchen Browsern
    // beim Wechsel des Feldtyps an den Anfang.
    var laenge = feld.value.length;
    feld.focus();
    try { feld.setSelectionRange(laenge, laenge); } catch (e) { /* egal */ }
  });
})();
