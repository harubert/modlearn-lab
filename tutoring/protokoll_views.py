"""Die Protokollansicht der Lehrperson (Abschnitt 3b; Thomas, 31.10.2026).

Thomas: "Wenn es zum Frontiermodell weitergeht, moechte ich die Kommunikation
zwischen der lokalen KI und dem Frontiermodell auch einsehen koennen. Die
muss natuerlich auch auf dem Server gespeichert bleiben."

Die Zeilen sind die Interaction-Eintraege: eine je Anfrage an ein
Sprachmodell, die Analyseeinheit. Sie haengen ueber den pseudonymen log_key
an der Sitzung und ueberleben ihr Ende; die Bruecke zum Tier stirbt mit der
Teilnahme. Was eine Zeile an Text traegt, hat die Protokollstufe beim
Schreiben entschieden (Interaction.aufzeichnen); hier wird nur gezeigt und
exportiert (JSON und CSV, je Sitzung, mit dem gesetzten Filter).
"""

import csv
import io
import json

from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import PROTOKOLLSTUFEN, Interaction, LearningSession

# Die Spalten des Exports: alle Felder der Zeile, in der Reihenfolge des
# Modells. Die Kennungen sind pseudonym und fuehren zu keiner Person.
FELDER_EXPORT = (
    "id", "created_at", "session_key", "participant_key", "research_level",
    "route", "model_name", "level_requested", "level_granted", "tokens_in",
    "tokens_out", "duration_ms", "cost_micro", "leak_check",
    "entities_replaced", "outcome", "error_kind", "diagnosis", "instruction",
    "masked_input", "masked_output", "raw_input", "raw_output",
)


@login_required
def lehrperson_protokolle(request):
    """Alle Sitzungen der Lehrperson, offen und beendet, mit der Zahl der Zeilen."""
    sitzungen = list(
        LearningSession.objects.filter(teacher=request.user).order_by("-created_at", "-pk")
    )
    zaehler = {}
    if sitzungen:
        for schluessel, weg, n in (
            Interaction.objects.filter(session_key__in=[s.log_key for s in sitzungen])
            .values("session_key", "route").annotate(n=models.Count("pk"))
            .values_list("session_key", "route", "n")
        ):
            zaehler.setdefault(schluessel, {})[weg] = n
    zeilen = [{
        "sitzung": s,
        "lokal": zaehler.get(s.log_key, {}).get(Interaction.LOKAL, 0),
        "cloud": zaehler.get(s.log_key, {}).get(Interaction.CLOUD, 0),
    } for s in sitzungen]
    return render(request, "tutoring/lehrperson_protokolle.html", {"zeilen": zeilen})


@login_required
def lehrperson_protokoll(request, code):
    """Die Zeitleiste einer Sitzung, eine Zeile je Anfrage, aufklappbar.

    Filter wie in Abschnitt 3b: nur ein Weg, nur blockierte Aufrufe, nur
    eine Stufe, nur eine Teilnehmerkennung. ``export=json`` oder ``csv``
    liefert dieselben Zeilen als Datei.
    """
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    zeilen = Interaction.objects.filter(session_key=sitzung.log_key).order_by("created_at", "pk")
    weg = request.GET.get("weg", "")
    if weg in (Interaction.LOKAL, Interaction.CLOUD):
        zeilen = zeilen.filter(route=weg)
    nur = request.GET.get("nur", "")
    if nur == "blockiert":
        zeilen = zeilen.filter(leak_check=Interaction.BLOCKIERT)
    stufe = request.GET.get("stufe", "")
    if stufe.isdigit():
        zeilen = zeilen.filter(level_requested=int(stufe))
    kennung = request.GET.get("kennung", "")[:43]
    if kennung:
        zeilen = zeilen.filter(participant_key=kennung)
    zeilen = list(zeilen)

    export = request.GET.get("export", "")
    if export == "json":
        return _als_json(sitzung, zeilen)
    if export == "csv":
        return _als_csv(sitzung, zeilen)

    abfrage = request.GET.copy()
    abfrage.pop("export", None)
    return render(request, "tutoring/lehrperson_protokoll.html", {
        "sitzung": sitzung,
        "zeilen": zeilen,
        "summe": {
            "anzahl": len(zeilen),
            "cloud": sum(1 for z in zeilen if z.ist_cloud),
            "blockiert": sum(1 for z in zeilen if z.leak_check == Interaction.BLOCKIERT),
            "tokens_in": sum(z.tokens_in for z in zeilen),
            "tokens_out": sum(z.tokens_out for z in zeilen),
            "kosten_euro": sum(z.cost_micro for z in zeilen) / 1_000_000,
            "dauer_s": sum(z.duration_ms for z in zeilen) / 1000,
        },
        "kennungen": sorted({z.participant_key for z in zeilen if z.participant_key}),
        "filter": {"weg": weg, "nur": nur, "stufe": stufe, "kennung": kennung},
        "stufen_text": dict(PROTOKOLLSTUFEN).get(sitzung.research_level, ""),
        "abfrage": abfrage.urlencode(),
    })


def _zeile_als_dict(zeile):
    daten = {feld: getattr(zeile, feld) for feld in FELDER_EXPORT}
    daten["created_at"] = zeile.created_at.isoformat()
    return daten


def _als_json(sitzung, zeilen):
    antwort = HttpResponse(
        json.dumps([_zeile_als_dict(z) for z in zeilen], ensure_ascii=False, indent=1),
        content_type="application/json; charset=utf-8",
    )
    antwort["Content-Disposition"] = f'attachment; filename="protokoll_{sitzung.code}.json"'
    return antwort


def _als_csv(sitzung, zeilen):
    """Eine Zeile je Anfrage; Woerterbuecher (Entitaeten, Diagnose) als JSON."""
    puffer = io.StringIO()
    schreiber = csv.writer(puffer)
    schreiber.writerow(FELDER_EXPORT)
    for zeile in zeilen:
        daten = _zeile_als_dict(zeile)
        schreiber.writerow([
            json.dumps(wert, ensure_ascii=False) if isinstance(wert, (dict, list))
            else ("" if wert is None else wert)
            for wert in (daten[feld] for feld in FELDER_EXPORT)
        ])
    antwort = HttpResponse(puffer.getvalue(), content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = f'attachment; filename="protokoll_{sitzung.code}.csv"'
    return antwort
