"""Die Ansicht der Sprachausgabe: ein Zug des Coaches als WAV.

Eine Kennung hinein, eine Tondatei heraus. Kein freier Text: Die Stimme
spricht nur, was die Anwendung selbst geschrieben hat (tutoring/stimme.py).
Gebunden an die Teilnahme wie jeder andere Weg der Sitzung; ein Zug einer
fremden Teilnahme ist nicht da (404), nicht verboten.

Jeder Aufruf ist eine Zeile im Forschungsprotokoll, wie Whisper und wie der
Pfoertner: Modell, Dauer, Zeichen. Der Text des Zuges steht ohnehin im
Verlauf; hier steht, dass er gesprochen wurde.
"""

import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from . import stimme
from .models import Interaction, SprachZug
from .spark import SparkNichtErreichbar

logger = logging.getLogger(__name__)


@require_POST
def zug_sprechen(request):
    """Spricht einen Zug des Sprechcoachs in der Zielsprache der Sitzung.

    POST zug=<Kennung>, optional satz=<Nummer>: dann nur dieser Satz des
    Zuges (stimme.saetze), damit die Seite Satz fuer Satz holen und den
    ersten schon spielen kann, waehrend der zweite entsteht. Eine Nummer
    hinter dem letzten Satz bekommt 204: nichts mehr da, kein Fehler.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)
    if not stimme.moeglich():
        return JsonResponse({"ok": False, "meldung": stimme.MELDUNG_AUS}, status=404)

    kennung = (request.POST.get("zug") or "").strip()
    if not kennung.isdigit():
        return JsonResponse({"ok": False, "meldung": "Welcher Zug?"}, status=400)
    zug = (SprachZug.objects.filter(pk=int(kennung), role=SprachZug.COACH,
                                    run__participation=teilnahme)
           .select_related("run").first())
    if zug is None:
        return JsonResponse({"ok": False, "meldung": "Diesen Zug gibt es nicht."}, status=404)

    sitzung = teilnahme.learning_session
    text = zug.text
    satznummer = (request.POST.get("satz") or "").strip()
    if satznummer.isdigit():
        teile = stimme.saetze(text)
        nummer = int(satznummer)
        if nummer >= len(teile):
            # Das Ende des Zuges ist kein Fehler: Die Seite fragt Satz fuer
            # Satz und erfaehrt so, dass keiner mehr kommt, ohne dass die
            # Browserkonsole einen Fehler zeigt.
            return HttpResponse(status=204)
        text = teile[nummer]

    try:
        daten, messung = stimme.sprechen(text, sprache=sitzung.target_language)
    except SparkNichtErreichbar as fehler:
        return JsonResponse({"ok": False, "meldung": fehler.meldung}, status=503)

    if not messung.get("zwischenspeicher"):
        Interaction.aufzeichnen(
            sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
            modell=messung.get("modell", ""), dauer_ms=messung.get("dauer_ms", 0),
            leak_check=Interaction.ENTFAELLT, ergebnis="stimme",
            text_ein=text, text_aus=f"[Audio, {messung.get('bytes', 0)} Bytes]",
        )

    antwort = HttpResponse(daten, content_type="audio/wav")
    antwort["Cache-Control"] = "private, max-age=3600"
    antwort["X-Stimme"] = messung.get("modell", "")
    return antwort


def saetze_zaehlen(request):
    """Wie viele Saetze hat ein Zug? Die Seite fragt das vor dem ersten Satz.

    GET zug=<Kennung>. Dieselbe Bindung an die Teilnahme wie oben.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)
    kennung = (request.GET.get("zug") or "").strip()
    zug = (SprachZug.objects.filter(pk=int(kennung), role=SprachZug.COACH,
                                    run__participation=teilnahme).first()
           if kennung.isdigit() else None)
    if zug is None:
        return JsonResponse({"ok": False, "meldung": "Diesen Zug gibt es nicht."}, status=404)
    teile = stimme.saetze(zug.text)
    return JsonResponse({"ok": True, "saetze": len(teile), "moeglich": stimme.moeglich()})
