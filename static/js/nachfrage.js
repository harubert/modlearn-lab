/* Fragt vor einem Schritt nach, der nichts zurueckgibt.
 *
 * Auf der Uebersicht liegt neben jeder Sitzung ein Knopf, der sie beendet
 * und damit alles loescht, was die Kinder geschrieben haben. Die Knoepfe
 * liegen dicht beieinander; ein Fehlgriff waere nicht zu heilen.
 *
 * Ohne dieses Skript bleibt die Seite benutzbar, die Frage entfaellt nur.
 */
(function () {
  "use strict";

  document.addEventListener("submit", function (ereignis) {
    var formular = ereignis.target.closest("[data-nachfrage]");
    if (!formular) { return; }
    if (!window.confirm(formular.dataset.nachfrage)) {
      ereignis.preventDefault();
    }
  });
})();
