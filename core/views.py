"""Startseite, Rechtstexte, Zustandsprüfung und die Anmeldung."""

import hmac
import re

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from plan.models import Nutzerklasse, Profil
from tutoring.models import verfallene_aufraeumen

from . import ph
from .models import PhKonto

# Der Stand der Rechtstexte ist bewusst fest eingetragen und kein Tagesdatum:
# Eine Erklaerung, deren Datum sich jeden Tag von selbst weiterschiebt, sagt
# nichts darueber aus, wann sie zuletzt geprueft wurde.
STAND_RECHTSTEXTE = "1. November 2026"


def start(request):
    """Öffentliche Startseite mit dem Beitrittsformular."""
    verfallene_aufraeumen()
    return render(request, "core/start.html")


def stufen(request):
    """Fachliche Erklaerung der gestuften Hilfen samt Literatur."""
    return render(request, "core/stufen.html")


def bildpruefung(request):
    """Was passiert, wenn die Lehrperson Fotos der Aufgabe pruefen laesst.

    Die Seite hinter "Mehr erfahren" am zweiten Schalter der
    Qualitaetssicherung (31.10.2026): die Kette, ihre Grenzen, und was nie
    hinausgeht.
    """
    return render(request, "core/bildpruefung.html")


def trainer_erklaerung(request):
    """Was der Trainer macht, und wann eine Lehrperson ihn statt der
    Aufgabenhilfe nimmt."""
    return render(request, "core/trainer_erklaerung.html")


def datenschutz(request):
    # Die Protokollstufe ist eine feste Einstellung des Servers (1.11.2026);
    # die Seite sagt, welche gerade gilt, statt von einer Wahl zu reden.
    return render(request, "core/datenschutz.html", {
        "stand": STAND_RECHTSTEXTE,
        "protokollstufe": settings.PROTOKOLLSTUFE,
    })


def barrierefreiheit(request):
    return render(request, "core/barrierefreiheit.html", {"stand": STAND_RECHTSTEXTE})


def healthz(request):
    """Zustandsprüfung für den Container und für die Prüfung von aussen.

    Bewusst ohne Datenbankabfrage: die Prüfung soll sagen, ob die Anwendung
    Anfragen annimmt, und nicht bei jeder Datenbankwartung Alarm schlagen.
    """
    return HttpResponse("ok\n", content_type="text/plain; charset=utf-8")


# --- Anmeldung -------------------------------------------------------------

class Anmeldung(LoginView):
    """Das Anmeldeformular, ergaenzt um den Knopf fuer das PH-Konto.

    Der Knopf steht nur da, wenn das Geheimnis zwischen Caddy und der
    Anwendung vorhanden ist. Ein Knopf, der auf eine Seite "nicht
    eingerichtet" fuehrt, waere auf dem Entwicklungsrechner und auf jedem
    Server ohne Caddy davor eine Sackgasse.
    """

    def get_context_data(self, **kwargs):
        kontext = super().get_context_data(**kwargs)
        kontext["ph_anmeldung_moeglich"] = ph.anmeldung_moeglich()
        return kontext


# Welche Nutzerklasse ein neues PH-Konto bekommt. Vorgabe der Serverbetreuung:
# Standard Studierende, Freigabe von Hand fuer Lehrpersonen. Ob jemand
# Lehrperson ist, kommt derzeit nicht verlaesslich mit; aus der E-Mail-Domaene
# wird es NICHT geraten, denn eine Lehrperson mit Studierendenrechten kann sich
# melden, umgekehrt merkt es niemand.
STANDARDKLASSE = "Studierende"

# Djangos UnicodeUsernameValidator erlaubt Buchstaben, Ziffern und . @ + - _;
# alles andere faellt aus dem Anmeldenamen heraus.
_UNERLAUBT_IM_BENUTZERNAMEN = re.compile(r"[^\w.@+-]")


@require_GET
def ph_anmeldung(request):
    """Nimmt eine von Caddy geprüfte Person entgegen und meldet sie an.

    Dieser Weg ist die EINZIGE Stelle, die X-Auth-Kopfzeilen liest. Caddy
    entfernt sie an der Aussenkante und setzt sie nur auf dieser Route neu,
    zusammen mit dem Geheimnis aus der Datei; ohne gueltiges Geheimnis gilt
    keine davon.
    """
    geheimnis = ph.proxy_geheimnis()
    if geheimnis is None:
        # Ruhig und ohne 500: Es fehlt nichts an der Anwendung, es fehlt die
        # Einrichtung auf diesem Server.
        return render(request, "core/ph_anmeldung_aus.html", status=503)

    # Konstantzeitig: Ein Vergleich, der beim ersten falschen Zeichen
    # abbricht, verraet ueber die Antwortzeit Zeichen fuer Zeichen das
    # Geheimnis. Verglichen wird in Bytes, so wie die Datei gelesen wurde.
    empfangen = request.headers.get("X-Auth-Proxy-Secret", "")
    if not hmac.compare_digest(empfangen.encode("latin-1", "replace"), geheimnis):
        return _abgelehnt()

    # Die Objekt-ID ist die Kennung der Person. Nicht die E-Mail: die aendert
    # sich bei Heirat, Namenswechsel oder Abteilungswechsel, die ID nicht.
    oid = _kopfzeile(request, "X-Auth-Oid")
    if not oid:
        return _abgelehnt()

    person = {
        "email": _kopfzeile(request, "X-Auth-Email") or _kopfzeile(request, "X-Auth-Upn"),
        "anmeldename": _kopfzeile(request, "X-Auth-Anmeldename"),
        "vorname": _kopfzeile(request, "X-Auth-Vorname"),
        "nachname": _kopfzeile(request, "X-Auth-Nachname"),
        "name": _kopfzeile(request, "X-Auth-Name"),
        "gruppen": _kopfzeile(request, "X-Auth-Groups"),
    }
    if not person["name"]:
        person["name"] = f"{person['vorname']} {person['nachname']}".strip()

    konto = _konto_abgleichen(oid, person)
    if not konto.benutzer.is_active:
        # Gesperrt wird in der Verwaltung am Benutzer. Die PH weiss davon
        # nichts und wuerde die Person jedes Mal wieder hereinlassen.
        return _abgelehnt()
    _profil_sicherstellen(konto.benutzer)

    # Das Backend steht ausdruecklich dabei: Es gab keine Kennwortpruefung,
    # also hat kein Backend die Person "authentifiziert". Django braucht den
    # Namen trotzdem, um die Sitzung zu beschriften.
    login(request, konto.benutzer, backend="django.contrib.auth.backends.ModelBackend")
    return redirect(_ziel(request))


def _abgelehnt():
    # Dieselbe Antwort fuer jedes Scheitern. Wer erfaehrt, ob das Geheimnis
    # oder die Kennung gefehlt hat, weiss schon zu viel ueber den Aufbau.
    return HttpResponseForbidden(
        "Die Anmeldung wurde nicht angenommen.\n",
        content_type="text/plain; charset=utf-8",
    )


def _kopfzeile(request, name):
    """Liest eine Kopfzeile und stellt Umlaute richtig.

    HTTP-Kopfzeilen sind Bytes. Django macht daraus Text nach ISO-8859-1, wie
    es WSGI und ASGI vorschreiben; Caddy schickt die Namen aus dem Entra aber
    als UTF-8. Aus "Müller" wird so "MÃ¼ller". Der Umweg ueber die
    urspruenglichen Bytes macht das rueckgaengig. Faellt die Deutung als UTF-8
    durch, war der Wert schon richtig.
    """
    wert = request.headers.get(name, "")
    try:
        wert = wert.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return wert.strip()


def _konto_abgleichen(oid, person):
    """Findet das Konto zur Objekt-ID oder legt es samt Benutzer an.

    Bei jedem Besuch werden E-Mail, Name, Gruppen und Zeitpunkt nachgezogen,
    denn die PH ist fuer diese Angaben die Wahrheit. NIE nachgezogen werden
    Benutzername und Rechte: Der Benutzername haengt an Buchungen und
    Sitzungen, die Rechte (is_staff, is_superuser, Nutzerklasse) vergibt die
    Verwaltung von Hand, und eine Anmeldung darf sie nicht zuruecksetzen.
    """
    konto = PhKonto.objects.select_related("benutzer").filter(oid=oid).first()
    if konto is None:
        try:
            with transaction.atomic():
                konto = _konto_anlegen(oid, person)
        except IntegrityError:
            # Zwei Anfragen derselben Person im selben Augenblick (Doppelklick,
            # zwei Tabs): Die zweite findet das Konto, das die erste angelegt hat.
            konto = PhKonto.objects.select_related("benutzer").get(oid=oid)

    konto.email = person["email"][:254]
    konto.anmeldename = person["anmeldename"][:150]
    konto.name = person["name"][:200]
    konto.gruppen = person["gruppen"]
    konto.zuletzt_gesehen = timezone.now()
    konto.save()

    # Der Seitenkopf zeigt get_full_name; der soll den heutigen Namen zeigen.
    # update_fields, damit ganz sicher nichts anderes am Benutzer mitgeht.
    benutzer = konto.benutzer
    benutzer.first_name = person["vorname"][:150]
    benutzer.last_name = person["nachname"][:150]
    benutzer.email = person["email"][:254]
    benutzer.save(update_fields=["first_name", "last_name", "email"])
    return konto


def _konto_anlegen(oid, person):
    Benutzer = get_user_model()
    benutzer = Benutzer(
        username=_freier_benutzername(person),
        first_name=person["vorname"][:150],
        last_name=person["nachname"][:150],
        email=person["email"][:254],
    )
    # Es gibt kein Kennwort. Der Weg ueber das Formular bleibt diesem Konto
    # verschlossen, auch fuer jemanden, der die Datenbank liest.
    benutzer.set_unusable_password()
    benutzer.save()
    return PhKonto.objects.create(benutzer=benutzer, oid=oid)


def _freier_benutzername(person):
    """"ph-" + Anmeldename, bei Kollision mit Zaehler.

    Das "ph-" davor haelt die PH-Konten von den Zugaengen aus plan_zugang
    getrennt: Ein Anmeldename "thomas" im Entra darf nie auf den von Hand
    angelegten Verwaltungszugang "thomas" fallen.
    """
    roh = person["anmeldename"] or person["email"].split("@")[0]
    basis = _UNERLAUBT_IM_BENUTZERNAMEN.sub("", roh).lower()[:120] or "konto"
    basis = "ph-" + basis

    Benutzer = get_user_model()
    kandidat = basis
    zaehler = 1
    while Benutzer.objects.filter(username__iexact=kandidat).exists():
        zaehler += 1
        kandidat = f"{basis}-{zaehler}"
    return kandidat


def _profil_sicherstellen(benutzer):
    """Ein neues PH-Konto bekommt ein Planungsprofil als Studierende.

    Nur wenn noch keines da ist: Ein bestehendes Profil ist die
    Hand-Freigabe der Verwaltung und wird von einer Anmeldung nicht
    angeruehrt. Fehlt die Klasse "Studierende", nimmt die zurueckhaltendste,
    so wie plan_zugang es auch haelt. Ohne jede Klasse gibt es kein Profil;
    die Anmeldung scheitert daran nicht.
    """
    if Profil.objects.filter(benutzer=benutzer).exists():
        return
    klasse = (
        Nutzerklasse.objects.filter(name__iexact=STANDARDKLASSE).first()
        or Nutzerklasse.objects.order_by("max_plaetze", "name").first()
    )
    if klasse is None:
        return
    Profil.objects.create(benutzer=benutzer, klasse=klasse)


def _ziel(request):
    """Wohin nach der Anmeldung: ?next=, aber nur auf diese Seite.

    Ohne erlaubte Hosts laesst url_has_allowed_host_and_scheme genau die
    relativen Pfade durch: keine fremde Domaene, kein "//boese.example" (das
    der Browser als Host liest), kein anderes Schema. Dazu die Pruefung auf
    den fuehrenden Schraegstrich, damit auch "plan/" nicht relativ zu
    /anmelden/ph-online/ landet.
    """
    ziel = request.GET.get("next", "")
    if (
        ziel.startswith("/")
        and not ziel.startswith("//")
        and url_has_allowed_host_and_scheme(ziel, allowed_hosts=None)
    ):
        return ziel
    return reverse("tutoring:lehrperson_uebersicht")


def sprechcoach_erklaerung(request):
    """Was der Sprechcoach in einem Gespraech tut, und worauf das beruht.

    Die Kurzfassung der Recherche vom Oktober 2026
    (docs/Gespraechsdidaktik Englisch fuer den Sprechcoach.md).

    Die Liste der Gespraechsaufgaben kommt aus tutoring/sprechaufgaben.py
    und nicht aus der Vorlage: Eine neue Aufgabe steht dann von selbst auch
    hier.
    """
    from tutoring import sprechablauf, sprechaufgaben

    return render(request, "core/sprechcoach_erklaerung.html", {
        "sprechaufgaben": sprechaufgaben.AUFGABEN,
        "erweitert_ab": sprechablauf.ERWEITERT_AB_WOERTERN,
    })


def projekt(request):
    """Die oeffentliche Seite ueber das ganze Vorhaben.

    Fuer Lehrpersonen, Kolleginnen an der PH, Erasmus-Partner und
    Schulleitungen: was das AI LAB ist, welche Werkzeuge es gibt, wie sie
    gebaut sind und warum so. Ohne Anmeldung und ohne Datenbankabfrage.

    Die Startseite bleibt die Seite der Kinder mit dem Code; diese Seite steht
    daneben. Die fachlichen Erklaerungen (Stufen, Trainer, Sprechcoach)
    ersetzt sie nicht, sie verlinkt sie.

    Ganz unten steht die Musik-KI zum Ausprobieren. Die Seite fragt dafuer
    den Musikdienst nicht: Ein Spark, der nicht antwortet, darf die
    Landing Page nicht aufhalten. Sie nennt nur, was ohne Netz schon
    feststeht (Geheimnis fehlt, Dienst zuletzt stumm); Stile und Marken holt
    das Skript danach.
    """
    from . import musik_oeffentlich

    return render(request, "core/projekt.html", {
        "musik_hinweis": musik_oeffentlich.hinweis_ohne_netz(),
        "musik_text_max": musik_oeffentlich.TEXT_MAX,
    })


# --- Testecke fuer die Musik-KI am Spark ------------------------------------
# Nur ueber die Adresse /labor/musik/ erreichbar, bewusst ohne Link im Kopf:
# Es ist eine Werkbank fuer das Lab, kein Angebot an Lehrpersonen. Wird daraus
# ein Fach, bekommt es eine eigene Oberflaeche samt Privacy Shield fuer den
# Liedtext.

from functools import wraps  # noqa: E402

from django.contrib.auth.views import redirect_to_login  # noqa: E402
from django.http import Http404, JsonResponse, StreamingHttpResponse  # noqa: E402
from django.views.decorators.http import require_POST  # noqa: E402

from . import musik  # noqa: E402

# Die eigenen Auftraege stehen in der Django-Session, nirgends sonst. Das ist
# zugleich die Zugriffsregel: Abfragen, abspielen und loeschen darf nur, wer
# den Auftrag in dieser Sitzung angelegt hat.
MUSIK_SITZUNGSSCHLUESSEL = "musik_lieder"
MUSIK_HOECHSTENS = 30


def _darf_musiklabor(benutzer):
    """staff, oder ein nicht gesperrtes Planungsprofil der Klasse "Lab"."""
    if benutzer.is_staff:
        return True
    try:
        profil = benutzer.planprofil
    except Profil.DoesNotExist:
        return False
    return profil.darf_buchen and profil.klasse.name == "Lab"


def _musiklabor(ansicht):
    """Anonym zur Anmeldung, angemeldet ohne Lab-Recht 403."""
    @wraps(ansicht)
    def huelle(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _darf_musiklabor(request.user):
            return HttpResponseForbidden("Die Musik-Testecke ist dem Lab vorbehalten.")
        return ansicht(request, *args, **kwargs)
    return huelle


def _eigene_lieder(request):
    lieder = request.session.get(MUSIK_SITZUNGSSCHLUESSEL)
    return lieder if isinstance(lieder, list) else []


def _eigenes_lied(request, kennung):
    """Der Eintrag aus der Session, sonst 404, auch fuer fremde Kennungen.

    404 statt 403: Ob es einen fremden Auftrag dieser Kennung gibt, geht
    niemanden etwas an.
    """
    if not musik.KENNUNG.match(kennung):
        raise Http404
    for lied in _eigene_lieder(request):
        if lied.get("auftrag") == kennung:
            return lied
    raise Http404


def _lied_merken(request, kennung, **felder):
    lieder = [l for l in _eigene_lieder(request) if l.get("auftrag") != kennung]
    lieder.insert(0, {**felder, "auftrag": kennung})
    request.session[MUSIK_SITZUNGSSCHLUESSEL] = lieder[:MUSIK_HOECHSTENS]


def _lied_aktualisieren(request, kennung, **felder):
    """Wie _lied_merken, aber an derselben Stelle der Liste."""
    request.session[MUSIK_SITZUNGSSCHLUESSEL] = [
        {**l, **felder} if l.get("auftrag") == kennung else l
        for l in _eigene_lieder(request)
    ]


def _lied_vergessen(request, kennung):
    request.session[MUSIK_SITZUNGSSCHLUESSEL] = [
        l for l in _eigene_lieder(request) if l.get("auftrag") != kennung
    ]


def _ganzzahl(wert, vorgabe=None):
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return vorgabe


@_musiklabor
def musik_labor(request):
    """Die Seite: Verbindung, Stile, Formular, die eigenen Lieder."""
    gesund = musik.gesundheit()
    stil_liste, stil_antwort = musik.stile()
    grenzen = musik.grenzen() if stil_antwort.ok else stil_antwort
    # Verbunden heisst: Geheimnis da, und der Dienst nennt Stile und Grenzen.
    # Die Gesundheit allein reicht nicht, die geht ohne Geheimnis.
    hinderung = stil_antwort.satz or grenzen.satz
    g = grenzen.inhalt if grenzen.ok else {}
    werte = {
        "sekunden_vorgabe": _ganzzahl(g.get("sekunden_vorgabe"), 60),
        "sekunden_max": _ganzzahl(g.get("sekunden_max"), 240),
        "text_max": _ganzzahl(g.get("text_max"), 4000),
        "tags_max": _ganzzahl(g.get("tags_max"), 600),
        "verfall_stunden": g.get("verfall_stunden"),
        "fassungen": musik.fassungen(g),
        "marken": musik.marken(stil_liste, g),
        # Takt und Sprache als Auswahl aus dem Dienst: Der Knoten kennt nur
        # "2","3","4","6" - ein freies Feld mit "4/4" waere jedes Mal ein 400.
        "takte": [str(t) for t in (g.get("takte") or ["2", "3", "4", "6"])],
        "sprachen": [str(s) for s in (g.get("sprachen") or ["de", "en"])],
        "marken_hinweis": g.get("marken_hinweis") or "",
    }
    return render(request, "core/musik_labor.html", {
        "gesund": gesund,
        "hinderung": hinderung,
        "stile": stil_liste,
        "grenzen": werte,
        "lieder": _eigene_lieder(request),
    })


@_musiklabor
@require_POST
def musik_absenden(request):
    """POST /lied am Dienst. Antwortet JSON fuer das Skript der Seite."""
    p = request.POST
    stil = p.get("stil", "").strip()[:80]
    jetzt = timezone.localtime().strftime("%H:%M")
    daten = {
        "tags": p.get("tags", "").strip(),
        "lyrics": p.get("lyrics", ""),
        "sekunden": _ganzzahl(p.get("sekunden"), 60),
        "bpm": _ganzzahl(p.get("bpm")),
        "tonart": p.get("tonart", "").strip(),
        "takt": p.get("takt", "").strip(),
        "sprache": p.get("sprache", "").strip(),
        "fassung": p.get("fassung", "xl").strip(),
        "kennzeichen": musik.kennzeichen(request.user),
    }
    # Leere Angaben weglassen, damit der Dienst seine eigenen Vorgaben nimmt,
    # statt an einem leeren Feld zu scheitern. Die Grenzen prueft der Dienst;
    # sein `grund` ist der bessere Satz als eine Doppelpruefung hier.
    daten = {k: v for k, v in daten.items() if v not in ("", None)}
    antwort = musik.lied_anlegen(daten)
    if not antwort.ok:
        return JsonResponse({"ok": False, "grund": antwort.satz})
    kennung = str(antwort.inhalt.get("auftrag", ""))
    if not musik.KENNUNG.match(kennung):
        return JsonResponse({"ok": False,
                             "grund": "Der Musikdienst hat keine brauchbare Auftragskennung geliefert."})
    eintrag = {
        "stil": stil, "sekunden": daten.get("sekunden"),
        "fassung": daten.get("fassung"), "zeit": jetzt,
        "zustand": antwort.inhalt.get("zustand") or "wartet",
    }
    _lied_merken(request, kennung, **eintrag)
    return JsonResponse({
        "ok": True, "auftrag": kennung, **eintrag,
        "position": antwort.inhalt.get("position"),
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        "abfrage": reverse("musik_auftrag", args=[kennung]),
        "loeschen": reverse("musik_loeschen", args=[kennung]),
    })


@_musiklabor
def musik_auftrag(request, kennung):
    """Stand eines eigenen Auftrags, vom Dienst erfragt."""
    lied = _eigenes_lied(request, kennung)
    antwort = musik.auftrag(kennung)
    if not antwort.ok:
        return JsonResponse({"ok": False, "grund": antwort.satz, "code": antwort.code})
    zustand = antwort.inhalt.get("zustand")
    if zustand and zustand != lied.get("zustand"):
        _lied_aktualisieren(request, kennung, zustand=zustand)
    return JsonResponse({
        "ok": True,
        "zustand": zustand,
        "position": antwort.inhalt.get("position"),
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        "dauer_s": antwort.inhalt.get("dauer_s"),
        "fehler": antwort.inhalt.get("fehler"),
        "datei": reverse("musik_datei", args=[kennung]) if zustand == "fertig" else "",
    })


@_musiklabor
def musik_datei(request, kennung):
    """Die MP3, vom Spark durchgereicht. Der Browser sieht den Spark nie."""
    _eigenes_lied(request, kennung)
    ergebnis = musik.datei(kennung)
    if ergebnis is None:
        return HttpResponse(musik.antwortet_nicht_satz(), status=503,
                            content_type="text/plain; charset=utf-8")
    code, art, laenge, stuecke = ergebnis
    if code != 200:
        return HttpResponse("Die Datei liegt am Musikdienst nicht vor.", status=404,
                            content_type="text/plain; charset=utf-8")
    antwort = StreamingHttpResponse(stuecke, content_type=art or "audio/mpeg")
    if laenge:
        antwort["Content-Length"] = laenge
    antwort["Content-Disposition"] = f'inline; filename="lied-{kennung}.mp3"'
    antwort["Cache-Control"] = "private, no-store"
    return antwort


@_musiklabor
@require_POST
def musik_loeschen(request, kennung):
    """DELETE am Dienst. `datei_entfernt` wird gemeldet, nicht angenommen.

    Laut CLAUDE.md (12.10.): auswerten, nicht annehmen. Ein Loeschknopf, der
    "geloescht" sagt, weil der Aufruf durchging, waere genau der stille
    Fehlschlag beim Datenschutz, den der Dienst selbst schon einmal hatte.
    """
    _eigenes_lied(request, kennung)
    antwort = musik.entfernen(kennung)
    if antwort.code == 404:
        # Nach verfall_stunden raeumt der Dienst selbst ab. Dann ist am Spark
        # nichts mehr, und der Eintrag hier waere nur noch eine Leiche.
        _lied_vergessen(request, kennung)
        return JsonResponse({
            "ok": True, "entfernt": False, "datei_entfernt": None,
            "satz": "Der Musikdienst kennt diesen Auftrag nicht mehr (verfallen oder schon gelöscht).",
        })
    if not antwort.ok:
        return JsonResponse({"ok": False, "satz": antwort.satz})
    entfernt = antwort.inhalt.get("entfernt") is True
    datei_entfernt = antwort.inhalt.get("datei_entfernt")
    if entfernt:
        _lied_vergessen(request, kennung)
    if not entfernt:
        satz = "Der Musikdienst meldet den Auftrag nicht als entfernt. Er bleibt in der Liste."
    elif datei_entfernt is True:
        satz = "Auftrag und Datei sind am Spark gelöscht."
    elif datei_entfernt is False:
        satz = ("Der Auftrag ist gelöscht, die Datei meldet der Dienst aber nicht als "
                "entfernt (datei_entfernt: false).")
    else:
        satz = ("Der Auftrag ist gelöscht; ob die Datei weg ist, sagt der Dienst nicht "
                "(kein datei_entfernt in der Antwort).")
    return JsonResponse({"ok": entfernt, "entfernt": entfernt,
                         "datei_entfernt": datei_entfernt, "satz": satz})
