"""Die Seite „Neue Modelle“ fuer das Lab.

Wer sie sehen darf, richtet sich nach der Musik-Testecke: staff oder ein
Planungsprofil der Klasse „Lab“. Lehrpersonen der Uebungsschule brauchen
keine Modellnachrichten, und ein Link, der fuer sie ins Leere fuehrt, waere
nur Rauschen in der Kopfzeile.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.views import _darf_musiklabor as darf_lab

from . import pruefen
from .models import Fund


def _lab(ansicht):
    """Anonym zur Anmeldung, angemeldet ohne Lab-Recht 403."""
    @wraps(ansicht)
    def huelle(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not darf_lab(request.user):
            return HttpResponseForbidden("Die Modellnachrichten sind dem Lab vorbehalten.")
        return ansicht(request, *args, **kwargs)
    return huelle


def _gruppen(funde):
    """Je Quelle und Anbieter eine Gruppe, in der Reihenfolge des juengsten Fundes."""
    gruppen = {}
    for fund in funde:
        gruppe = gruppen.setdefault((fund.quelle, fund.anbieter), {
            "titel": fund.anbieter, "quelle_titel": fund.quelle_titel, "funde": [],
        })
        gruppe["funde"].append(fund)
    return list(gruppen.values())


@_lab
def uebersicht(request):
    alle = request.GET.get("alle") == "1"
    funde = Fund.objects.all()
    if not alle:
        funde = funde.filter(grundbestand=False, gelesen=False)
    funde = list(funde[:400])
    laeufe = pruefen.letzte_laeufe()
    return render(request, "modellwaechter/uebersicht.html", {
        "gruppen": _gruppen(funde),
        "quellen": laeufe,
        "letzter_lauf": max(laeufe, key=lambda l: l.begonnen) if laeufe else None,
        "alle": alle,
        "ungelesen": Fund.objects.filter(grundbestand=False, gelesen=False).count(),
        "mail_moeglich": pruefen.mail_moeglich(),
    })


@_lab
@require_POST
def gelesen(request, pk):
    Fund.objects.filter(pk=pk).update(gelesen=True)
    return redirect("modellwaechter:uebersicht")


@_lab
@require_POST
def alle_gelesen(request):
    Fund.objects.filter(grundbestand=False, gelesen=False).update(gelesen=True)
    return redirect("modellwaechter:uebersicht")
