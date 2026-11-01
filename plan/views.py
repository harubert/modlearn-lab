"""Die Ansichten des Planungswerkzeugs."""

from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from tutoring import faecher

from . import konzepte
from .messung import spitze_bisher, vergleich
from .models import (
    SCHRITT, TAG_BIS, TAG_VON, Buchung, Nutzerklasse, Profil, belegung,
    freie_obergrenze, ueberlappende,
)

# So viele Tage im Voraus laesst sich planen. Weiter waere Schein: Wer im
# Dezember fuer Maerz bucht, weiss noch nicht, ob er den Termin haelt.
VORAUS_TAGE = 14

# Was bei einem Konzept mit Schuelerzahl voreingestellt wird: eine Klasse.
# Nicht das Hoechstmass wie sonst - sechzig Kinder sind bei einer Lehrperson
# nie der Normalfall, und drei Mal auf Minus druecken ist der Normalfall
# auch nicht.
EINE_KLASSE = 30


def _profil(benutzer):
    """Das Planungsprofil, bei Bedarf mit der zurueckhaltendsten Klasse.

    Wer einen Zugang hat, aber kein Profil, bekommt die engste Klasse und
    nicht gar keine: Eine Seite, die mit einer Ausnahme antwortet, ist
    schlechter als eine, die wenig erlaubt.
    """
    vorhanden = Profil.objects.filter(benutzer=benutzer).select_related("klasse").first()
    if vorhanden is not None:
        return vorhanden
    klasse = Nutzerklasse.objects.order_by("max_plaetze").first()
    if klasse is None:
        return None
    return Profil.objects.create(benutzer=benutzer, klasse=klasse)


def _zeit(text):
    """'10:45' zu Minuten seit Mitternacht, oder None."""
    try:
        stunde, minute = (int(teil) for teil in (text or "").split(":")[:2])
    except (ValueError, TypeError):
        return None
    if not (0 <= stunde < 24 and 0 <= minute < 60):
        return None
    return stunde * 60 + minute


def _uhr(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _vorgabe(von="08:00", bis="08:50", plaetze=0, zweck="",
             konzept=konzepte.STANDARD, fach="", person=""):
    """Was in den Feldern stehen soll, mit der Lage im Balken dazu.

    von_min und dauer_min sind Minuten relativ zu 07:00, also genau das, was
    das CSS erwartet. Gerechnet wird hier und nicht in der Vorlage: Dort
    braeuchte es slice und widthratio und die Annahme, dass die Uhrzeit immer
    zweistellig geschrieben ist.
    """
    a = _zeit(von)
    e = _zeit(bis)
    lage = (a is not None and e is not None and e > a)
    return {
        "von": von, "bis": bis, "plaetze": plaetze, "zweck": zweck,
        "konzept": konzept, "fach": fach, "person": person,
        "von_min": max(a - TAG_VON, 0) if lage else 60,
        "dauer_min": (e - a) if lage else 50,
    }


def _datum(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return timezone.localdate()


def _als_zeitpunkt(tag, minute):
    roh = datetime.combine(tag, datetime.min.time()) + timedelta(minutes=minute)
    return timezone.make_aware(roh)


def _konzept_hoechstens(schluessel, max_jetzt, gesamt):
    """Wie viele Plaetze eine Buchung mit diesem Konzept hoechstens nennt.

    Drei Grenzen, und die engste gilt: was die Klasse erlaubt, was heute
    buchbar ist (max_jetzt fasst beides zusammen), und der Anteil, den das
    Konzept vom Ganzen nimmt. Abgerundet auf den Schritt des Konzepts, denn
    beim Unterricht sind 72 keine gueltige Zahl.
    """
    schritt = konzepte.plaetze_schritt(schluessel)
    hoechst = min(max_jetzt, gesamt * konzepte.anteil(schluessel) // 100)
    return hoechst - hoechst % schritt


def _konzept_fuer_seite(schluessel, max_jetzt, gesamt):
    """Ein Konzept, wie die Vorlage und plan.js es brauchen.

    Die Saetze fuer Beschriftung und Hilfe entstehen hier und nicht in der
    Vorlage, weil plan.js sie beim Wechsel des Konzepts ebenfalls braucht
    und ein Satz nur an einer Stelle stehen soll.
    """
    k = konzepte.konzept(schluessel)
    schuelerzahl = bool(k.get("braucht_schuelerzahl"))
    alleinig = konzepte.ist_alleinig(schluessel)
    schritt = konzepte.plaetze_schritt(schluessel)
    hoechst = _konzept_hoechstens(schluessel, max_jetzt, gesamt)

    if schuelerzahl:
        plaetze_wort = "Schülerinnen und Schüler"
        plaetze_hilfe = (f"In Schritten von {schritt}: Niemand weiß, ob 23 "
                         f"oder 25 kommen, und eine ganze Klasse ist im "
                         f"Schnitt gut ein Platz.")
        vorgabe = min(hoechst, EINE_KLASSE - EINE_KLASSE % schritt)
    elif alleinig:
        plaetze_wort = "Plätze"
        plaetze_hilfe = ("Diese Buchung belegt den Rechner ohnehin ganz. Die "
                         "Zahl dient nur dem Rückblick.")
        vorgabe = hoechst
    else:
        plaetze_wort = "Plätze"
        plaetze_hilfe = "Eine Person, die zur selben Zeit arbeitet, ist ein Platz."
        vorgabe = hoechst

    return {
        "schluessel": schluessel,
        "name": k["name"],
        "symbol": k["symbol"],
        "satz": k["satz"],
        "anteil": konzepte.anteil(schluessel),
        "alleinig": alleinig,
        "umbau": konzepte.braucht_umbau(schluessel),
        "schuelerzahl": schuelerzahl,
        "schritt": schritt,
        "max_plaetze": hoechst,
        "vorgabe_plaetze": max(vorgabe, schritt),
        "plaetze_wort": plaetze_wort,
        "plaetze_hilfe": plaetze_hilfe,
    }


def _konzepte_alle():
    """Alle Konzepte, knapp, fuer plan.js.

    Die Seite einer Lehrperson zeigt nur Unterricht zur Wahl, im Balken
    kann aber eine Modellschulung des Labs liegen. Damit das Skript die
    erklaeren kann, kennt es alle Konzepte - Name, Symbol und ob sie den
    Rechner allein belegen - und nicht nur die waehlbaren.
    """
    return [
        {
            "schluessel": k["schluessel"],
            "name": k["name"],
            "symbol": k["symbol"],
            "alleinig": konzepte.ist_alleinig(k["schluessel"]),
            "umbau": konzepte.braucht_umbau(k["schluessel"]),
        }
        for k in konzepte.KONZEPTE
    ]


@login_required
def tag(request, fehler="", vorgabe=None):
    """Der Tagesplan: was belegt ist, und was noch frei."""
    gewaehlt = _datum(request.GET.get("datum"))
    profil = _profil(request.user)
    gesamt = settings.SPARK_PLAETZE
    # "frei" heisst auf dieser Seite durchgehend "noch buchbar", nicht
    # "technisch noch moeglich". Sonst nennt die Lage am Schieberegler eine
    # Zahl, die das Absenden dann nicht annimmt.
    buchbar = freie_obergrenze(gesamt, profil.klasse if profil else None)

    raster_roh = belegung(gewaehlt)
    raster = [
        {
            "zeit": _uhr(minute),
            "belegt": belegt,
            "frei": max(buchbar - belegt, 0),
            # Der Anteil fuer die Fuellung, bei hundert gedeckelt: Eine
            # alleinige Buchung steht auf der Gesamtkapazitaet, und die ist
            # groesser als das Buchbare.
            "anteil": min(belegt * 100 // buchbar, 100) if buchbar else 0,
            "konzepte": ",".join(laufend),
            "alleinig": any(konzepte.ist_alleinig(k) for k in laufend),
        }
        for minute, belegt, laufend in raster_roh
    ]

    heute = timezone.localdate()
    tage = []
    for versatz in range(VORAUS_TAGE):
        d = heute + timedelta(days=versatz)
        frei = sum(
            SCHRITT for _, belegt, _ in belegung(d) if belegt < buchbar
        )
        tage.append({
            "datum": d.isoformat(),
            "kurz": _kurz(d),
            "ist_heute": d == heute,
            "frei_min": frei,
        })

    buchungen = []
    for b in Buchung.objects.filter(
        abgesagt_am__isnull=True,
        beginn__date=gewaehlt,
    ).select_related("besitzer").order_by("beginn"):
        a = timezone.localtime(b.beginn)
        e = timezone.localtime(b.ende)
        von_minute = a.hour * 60 + a.minute
        buchungen.append({
            "pk": b.pk,
            "beginn_zeit": f"{a:%H:%M}",
            "ende_zeit": f"{e:%H:%M}",
            "von_minute": max(von_minute - TAG_VON, 0),
            "dauer_minuten": b.dauer_minuten,
            "plaetze": b.plaetze,
            "zweck": b.zweck,
            "konzept": b.konzept,
            "konzept_name": b.konzept_name,
            "symbol": b.konzept_symbol,
            "alleinig": b.alleinig,
            "fach_name": b.fach_name,
            "person": b.person,
            "besitzer": b.besitzer.get_full_name() or b.besitzer.username,
            "eigen": b.besitzer_id == request.user.id,
        })

    max_jetzt = min(profil.klasse.max_plaetze, buchbar) if profil else 0
    # Nur die Konzepte, die diese Klasse buchen darf, in der Reihenfolge des
    # Katalogs. Eine Lehrperson sieht eines, das Lab fuenf.
    erlaubt = [
        _konzept_fuer_seite(s, max_jetzt, gesamt)
        for s in (profil.klasse.erlaubte_konzepte() if profil else [])
    ]
    # Vorgewaehlt ist, was zuletzt eingetippt war, sonst das erste erlaubte.
    # Ein Konzept aus einem veralteten Formular, das die Klasse nicht mehr
    # darf, faellt dabei still auf das erste zurueck.
    konzept_wahl = next(
        (k for k in erlaubt if vorgabe and k["schluessel"] == vorgabe["konzept"]),
        erlaubt[0] if erlaubt else None,
    )

    meine = {
        "klasse_name": profil.klasse.name if profil else "ohne Klasse",
        "max_minuten": profil.klasse.max_minuten if profil else 0,
        "max_plaetze": (profil.klasse.max_plaetze if profil else 0),
        # Was die Klasse erlaubt, und was heute davon uebrig ist: Die Klasse
        # "Lab" darf 120 Plaetze, buchbar sind 108. Stuende im Zahlenfeld die
        # Klassengrenze, waere die Voreinstellung jedes Mal zu gross. Das
        # Konzept zieht die Grenze dann noch einmal enger (max_plaetze je
        # Konzept).
        "max_jetzt": max_jetzt,
        "slots_frei_woche": profil.slots_frei_woche(gewaehlt) if profil else 0,
        "darf_buchen": bool(profil and profil.darf_buchen),
        "grund": _grund(profil, gewaehlt),
    }

    if vorgabe is None:
        vorgabe = _vorgabe(
            plaetze=konzept_wahl["vorgabe_plaetze"] if konzept_wahl else 0,
            konzept=konzept_wahl["schluessel"] if konzept_wahl else "",
        )
    elif konzept_wahl is not None:
        vorgabe["konzept"] = konzept_wahl["schluessel"]

    return render(request, "plan/tag.html", {
        "tag": gewaehlt,
        "tage": tage,
        "raster": raster,
        "plaetze_gesamt": gesamt,
        "plaetze_buchbar": buchbar,
        "buchungen": buchungen,
        "meine": meine,
        "konzepte": erlaubt,
        "gewaehlt": konzept_wahl,
        "konzepte_alle": _konzepte_alle(),
        "faecher": faecher.FAECHER,
        "spitze_bisher": spitze_bisher(),
        "fehler": fehler,
        "vorgabe": vorgabe,
    })


def _kurz(d):
    namen = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    return f"{namen[d.weekday()]} {d:%d.%m.}"


def _grund(profil, tag_):
    """Warum jemand gerade nicht buchen kann. Leer heisst: kann."""
    if profil is None:
        return ("Für diesen Zugang ist noch keine Nutzerklasse hinterlegt. "
                "Bitte wenden Sie sich an das Lab.")
    if not profil.darf_buchen:
        return "Dieser Zugang ist zurzeit für Buchungen gesperrt."
    if not profil.klasse.erlaubte_konzepte():
        return ("Für Ihre Nutzerklasse ist zurzeit kein Nutzungskonzept "
                "freigegeben.")
    if profil.slots_frei_woche(tag_) <= 0:
        return (f"Ihr Kontingent von {profil.klasse.max_slots_woche} Buchungen "
                f"in dieser Woche ist aufgebraucht.")
    return ""


@login_required
@require_POST
def buchen(request):
    """Legt eine Buchung an, wenn alles passt.

    Geprueft wird hier und nicht nur im Browser: Die Lagemeldung auf der
    Seite ist eine Hilfe, keine Grenze. Die Reihenfolge der Pruefungen ist
    die Reihenfolge der Antworten, die jemand brauchen kann: erst der
    Zugang, dann die Zeit, dann das Konzept, dann die Plaetze, dann die
    Vertraeglichkeit mit dem, was schon steht, und erst zuletzt die
    Kapazitaet. Eine Modellschulung neben einer Schulklasse scheitert an
    der Vertraeglichkeit, nicht an "null von hundertacht Plaetzen frei" -
    das waere zwar wahr, erklaert aber nichts.
    """
    profil = _profil(request.user)
    gewaehlt = _datum(request.POST.get("datum"))
    von = _zeit(request.POST.get("von"))
    bis = _zeit(request.POST.get("bis"))
    try:
        plaetze = int(request.POST.get("plaetze") or 0)
    except ValueError:
        plaetze = 0
    zweck = (request.POST.get("zweck") or "").strip()[:160]
    konzept = (request.POST.get("konzept") or "").strip().lower()
    fach = (request.POST.get("fach") or "").strip().lower()
    person = (request.POST.get("person") or "").strip()[:120]

    # Was eingetippt war, bleibt stehen, wenn etwas nicht passt: Wer eine
    # Fehlermeldung bekommt und dazu ein leeres Formular, tippt alles neu.
    vorgabe = _vorgabe(
        von=request.POST.get("von") or "08:00",
        bis=request.POST.get("bis") or "08:50",
        plaetze=plaetze, zweck=zweck,
        konzept=konzept, fach=fach, person=person,
    )

    def zurueck(meldung):
        request.GET = request.GET.copy()
        request.GET["datum"] = gewaehlt.isoformat()
        return tag(request, fehler=meldung, vorgabe=vorgabe)

    grund = _grund(profil, gewaehlt)
    if grund:
        return zurueck(grund)

    if von is None or bis is None or bis <= von:
        return zurueck("Bitte geben Sie einen Zeitraum an, dessen Ende nach "
                       "dem Beginn liegt.")
    if von < TAG_VON or bis > TAG_BIS:
        return zurueck(f"Gebucht wird zwischen {TAG_VON // 60}:00 und "
                       f"{TAG_BIS // 60}:00 Uhr.")
    if bis - von > profil.klasse.max_minuten:
        return zurueck(f"Ihre Nutzerklasse erlaubt höchstens "
                       f"{profil.klasse.max_minuten} Minuten je Buchung.")

    # Das Konzept: bekannt, und fuer diese Klasse freigegeben. Die Seite
    # zeigt nur die erlaubten, aber ein Formular laesst sich nachbauen.
    if not konzepte.ist_bekannt(konzept):
        return zurueck("Bitte wählen Sie, wofür Sie den Spark buchen.")
    if not profil.klasse.darf_konzept(konzept):
        return zurueck(f"„{konzepte.name(konzept)}“ ist für Ihre Nutzerklasse "
                       f"nicht freigegeben.")

    # Fach und Person gehoeren zum Unterricht. Bei einem Konzept ohne
    # Schuelerzahl zeigt die Seite die Felder nicht; was trotzdem ankommt,
    # faellt weg, damit kein Fach an einer Modellschulung haengt.
    if konzepte.konzept(konzept).get("braucht_schuelerzahl"):
        if fach and not faecher.ist_bekannt(fach):
            return zurueck("Dieses Fach gibt es hier nicht.")
    else:
        fach = ""
        person = ""

    schritt = konzepte.plaetze_schritt(konzept)
    gesamt = settings.SPARK_PLAETZE
    anteil_grenze = gesamt * konzepte.anteil(konzept) // 100
    if plaetze < 1:
        return zurueck("Bitte geben Sie an, für wie viele Personen Sie buchen.")
    if plaetze > profil.klasse.max_plaetze:
        return zurueck(f"Ihre Nutzerklasse erlaubt höchstens "
                       f"{profil.klasse.max_plaetze} Plätze je Buchung.")
    if plaetze % schritt:
        return zurueck(f"„{konzepte.name(konzept)}“ wird in Schritten von "
                       f"{schritt} gebucht: {schritt}, {2 * schritt}, "
                       f"{3 * schritt} und so weiter.")
    if plaetze > anteil_grenze:
        return zurueck(f"„{konzepte.name(konzept)}“ nimmt höchstens "
                       f"{konzepte.anteil(konzept)} Prozent des Rechners, "
                       f"das sind {anteil_grenze} Plätze.")

    beginn = _als_zeitpunkt(gewaehlt, von)
    ende = _als_zeitpunkt(gewaehlt, bis)

    # Vertraeglichkeit VOR der Kapazitaet: Plaetze addieren sich, Modelle
    # nicht. Jede laufende Buchung im Zeitraum wird einzeln gegen das neue
    # Konzept gehalten; die erste, die nicht dazu passt, nennt die Uhrzeit,
    # ab der es nicht geht.
    for bestehende in ueberlappende(beginn, ende):
        if konzepte.vertraeglich(konzept, bestehende.konzept):
            continue
        a = timezone.localtime(bestehende.beginn)
        konflikt = max(von, a.hour * 60 + a.minute)
        return zurueck(konzepte.grund_unvertraeglich(
            konzept, bestehende.konzept, _uhr(konflikt)
        ))

    # Nicht die ganze Kapazitaet: Ein Zehntel bleibt frei, damit wer nicht
    # gebucht hat trotzdem arbeiten kann. Genau das ist der Unterschied
    # zwischen einer Zusage und einer Sperre.
    grenze = freie_obergrenze(gesamt, profil.klasse)
    for minute, belegt, _ in belegung(gewaehlt, von, bis):
        if belegt + plaetze > grenze:
            return zurueck(
                f"Um {_uhr(minute)} sind nur noch {max(grenze - belegt, 0)} von "
                f"{grenze} buchbaren Plätzen frei. Buchen Sie weniger Plätze "
                f"oder eine andere Zeit."
            )

    Buchung.objects.create(
        besitzer=request.user,
        beginn=beginn,
        ende=ende,
        plaetze=plaetze,
        zweck=zweck,
        konzept=konzept,
        fach=fach,
        person=person,
    )
    return redirect(f"/plan/?datum={gewaehlt.isoformat()}")


@login_required
@require_POST
def absagen(request):
    """Eine eigene Buchung zuruecknehmen.

    Geloescht wird nicht: Fuer den Rueckblick ist eine abgesagte Buchung
    eine Auskunft, naemlich dass geplant und dann doch nicht gebraucht
    wurde.
    """
    gebucht = Buchung.objects.filter(
        pk=request.POST.get("pk"), besitzer=request.user, abgesagt_am__isnull=True
    ).first()
    ziel = timezone.localdate()
    if gebucht is not None:
        ziel = timezone.localtime(gebucht.beginn).date()
        gebucht.abgesagt_am = timezone.now()
        gebucht.save(update_fields=["abgesagt_am"])
    return redirect(f"/plan/?datum={ziel.isoformat()}")


@login_required
def rueckblick(request):
    """Was gebucht war, und was wirklich gebraucht wurde.

    Der Teil, auf den es ankommt. Eine Kapazitaetszahl, die niemand
    nachprueft, ist geraten; diese Seite stellt die Buchung neben die
    gemessene Gleichzeitigkeit und macht aus der Schaetzung eine
    Beobachtung.
    """
    tage = int(request.GET.get("tage") or 14)
    zeilen = vergleich(tage)
    return render(request, "plan/rueckblick.html", {
        "zeilen": zeilen,
        "tage": tage,
        "plaetze_gesamt": settings.SPARK_PLAETZE,
        "spitze_bisher": spitze_bisher(),
        "summe_gebucht": sum(z["gebucht"] for z in zeilen),
        "summe_genutzt": sum(z["spitze"] for z in zeilen),
    })
