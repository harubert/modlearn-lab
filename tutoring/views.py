"""Ansichten der Aufgabenhilfe.

Zwei Wege liegen hier nebeneinander: die Lehrperson mit Anmeldung, Klassen-
liste und Verlaeufen, die Teilnehmenden ohne Konto und nur mit Sitzungscode.
Der Schluessel im Cookie der Django-Sitzung ist ein Zufallswert zur
Wiedererkennung des Browsers, keine Kennung eines Kindes. Sichtbar
unterschieden werden Teilnehmende ueber ein Tier, das sie selbst waehlen.
"""

import asyncio
import concurrent.futures
import dataclasses
import io
import json
import logging
from datetime import timedelta

import segno
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.http import (Http404, HttpResponse, HttpResponseForbidden,
                         HttpResponseNotAllowed, JsonResponse,
                         StreamingHttpResponse)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import (aufgabenpool, ausgabepruefung, spark, bereitschaft, bildkette, cloud, faecher, fachgrenze,
               klassenbild, levels, musikstunde, pruefung, safechat,
               sprechaufgaben, sprechcoach, stundenform, tiere)
from .models import (FORSCHUNG_VOLL, FOTOGRAFIERT, GETIPPT, HERKUNFT, VORGEGEBEN, SessionTask,
                     PROTOKOLLSTUFEN,
                     VERFALL_MINUTEN, VERFALL_WAHLEN, ChatZug, Hint, Interaction,
                     LearningSession, Lied, Participation, Question,
                     SprachLauf, SprachZug, Task, TrainerLauf, TrainerZug,
                     verfallene_aufraeumen)
from .spark import (MELDUNG_BILD_UNKLAR, MELDUNG_NICHT_ERREICHBAR,
                    MELDUNG_NICHTS_VERSTANDEN, TEMPERATUR,
                    TEMPERATUR_WIEDERHOLUNG, SparkNichtErreichbar,
                    hilfe_streamen, sprache_moeglich, text_aus_bild,
                    text_und_sprache)

logger = logging.getLogger(__name__)

SCHLUESSEL_TEILNAHME = "teilnahme_token"
MAX_AUFGABENLAENGE = 2000

# Wer sich innerhalb dieser Spanne zuletzt geruehrt hat, gilt als aktiv.
ARBEITET_GERADE = timedelta(seconds=90)

# So viele Sitzungen stehen als Karte. Was darueber liegt, steht als Liste:
# Sechs Karten passen auf einen Handybildschirm, fuenfzig sind ein Haufen.
KARTEN_HOECHSTENS = 6
NL = chr(10)


# ---------------------------------------------------------------- Lehrperson

@login_required
def lehrperson_uebersicht(request):
    """Sitzungen der angemeldeten Lehrperson, dazu das Anlegeformular."""
    verfallene_aufraeumen()

    if request.method == "POST":
        gewaehltes_fach = (request.POST.get("fach") or "").strip().lower()

        # Ohne Fach wird nichts angelegt. Der Weg dorthin fuehrt ueber die
        # Fachwahl, und wer ohne Fach abschickt, hat ein Formular von Hand
        # gebaut - dann ist die Fachwahl die richtige Antwort und nicht eine
        # stillschweigend angelegte Mathematikstunde.
        if not faecher.ist_bekannt(gewaehltes_fach):
            return render(request, "tutoring/lehrperson_uebersicht.html",
                          _uebersicht(request.user))

        titel = (request.POST.get("title") or "").strip()

        # Jede Einstellung wird nur angenommen, wenn das Fach sie braucht.
        # Das ist der Kern der Umstellung: Die Seite zeigt nur die passenden
        # Felder, und die Ansicht nimmt auch nur die passenden Felder an.
        # Sonst schickt ein nachgebautes Formular doch eine Stufenobergrenze
        # in eine Englischstunde, und niemand sieht es.
        def hat(einstellung):
            return faecher.braucht(gewaehltes_fach, einstellung)

        # Lernen oder Ueben (stundenform.py). "Loesung bei Bedarf" nimmt das
        # Mathe-Formular seit dem Benchmark nicht mehr an: Was es schickt,
        # wird Lernen. Ohne Stufen gilt die zurueckhaltendste Einstellung.
        if hat(faecher.EINSTELLUNG_STUFEN):
            gewaehlt = stundenform.umfang((request.POST.get("umfang") or "").strip())
        else:
            gewaehlt = levels.umfang("")
        obergrenze = gewaehlt["obergrenze"]
        vorher_fragen = gewaehlt["vorher_fragen"]

        hinweis = ((request.POST.get("task_hint") or "").strip()[:200]
                   if hat(faecher.EINSTELLUNG_THEMA) else "")

        # Leer oder unbekannt heisst: bleibt offen. Das ist die sichere
        # Auslegung, ein zu frueh gestorbener Code ist das groessere Aergernis.
        roh = (request.POST.get("idle_timeout") or "").strip()
        frist = int(roh) if roh.isdigit() and int(roh) in VERFALL_MINUTEN else None

        # Die Protokollstufe ist seit 1.11.2026 eine feste Einstellung des
        # Servers (settings.PROTOKOLLSTUFE); nur mit PROTOKOLLSTUFE_WAEHLBAR
        # liest das Formular sie noch. Unbekanntes faellt auf die feste
        # Stufe zurueck.
        protokollstufe = feste_protokollstufe()
        if settings.PROTOKOLLSTUFE_WAEHLBAR:
            try:
                protokollstufe = int(request.POST.get("research_level", protokollstufe))
            except (TypeError, ValueError):
                protokollstufe = feste_protokollstufe()
            if protokollstufe not in dict(PROTOKOLLSTUFEN):
                protokollstufe = feste_protokollstufe()

        # Die Zielsprache steht am Fach und nicht in einem Auswahlfeld: Wer
        # Englisch unterrichtet, soll nicht noch "Englisch" auswaehlen muessen.
        zielsprache = faecher.sprache(gewaehltes_fach)
        niveau = (request.POST.get("language_level") or "").strip()
        if not hat(faecher.EINSTELLUNG_NIVEAU) or niveau not in dict(sprechcoach.NIVEAUS):
            niveau = sprechcoach.NIVEAU_STANDARD

        # Die Gespraechsaufgabe (Regel 11 des Berichts: Aufgabe mit Ziel und
        # Informationsluecke statt Smalltalk). Leer oder unbekannt heisst
        # freies Gespraech, das alte Verhalten. Eine Aufgabe, die nicht zum
        # Niveau passt, wird nicht still ersetzt, sondern zurueckgegeben: Die
        # Lehrperson hat etwas gewaehlt, und sie soll wissen, dass es nicht
        # gilt. Ohne JavaScript stehen alle Aufgaben da, also kann das
        # vorkommen.
        sprechaufgabe = ""
        if hat(faecher.EINSTELLUNG_AUFGABE):
            sprechaufgabe = (request.POST.get("speaking_task") or "").strip()
            if sprechaufgabe not in sprechaufgaben.auswahl():
                sprechaufgabe = ""
            elif (sprechaufgabe != sprechaufgaben.FREI
                  and not sprechaufgaben.passt(sprechaufgabe, niveau)):
                return render(
                    request, "tutoring/lehrperson_uebersicht.html",
                    _uebersicht(
                        request.user, fach=gewaehltes_fach,
                        fehler=("Die Aufgabe „{}“ passt nicht zum Niveau {}. "
                                "Bitte wähl eine andere oder das freie "
                                "Gespräch.").format(
                            sprechaufgaben.aufgabe(sprechaufgabe)["titel"], niveau),
                        titel=titel, thema=hinweis,
                    ),
                )

        # Die Qualitaetssicherung geht nur an, wenn ein Zugang eingerichtet
        # ist. Ein Haken, hinter dem nichts steht, waere eine Zusage, die
        # niemand einhaelt.
        qualitaet = (bool(request.POST.get("qualitaetssicherung")) and cloud.moeglich()
                     and hat(faecher.EINSTELLUNG_QUALITAET))
        # Der zweite Schalter (Thomas, 31.10.2026) haengt am ersten: Ohne
        # Qualitaetssicherung gibt es keinen Weg nach draussen, also auch
        # keinen fuer einen Bildausschnitt. Ob ein einzelnes Foto dann
        # wirklich hinausgeht, entscheidet je Foto die Bildkette.
        bilder = qualitaet and bool(request.POST.get("bilder_pruefen"))

        # Die Betriebsart wird nicht mehr gewaehlt, sie folgt aus dem Fach.
        betriebsart = faecher.betriebsart(gewaehltes_fach)

        # Fuer wen ist die Stunde? In Mathematik die Schulstufe, und sie ist
        # Pflicht: keine Vorauswahl, weil eine stillschweigend angelegte
        # Volksschulstunde vor einer Oberstufe genau der Fehler waere, den
        # der Benchmark (Befund 6) gezeigt hat. Die Altersklasse folgt aus
        # ihr. In den anderen Faechern bleibt die Altersklasse, und die
        # Schulstufe folgt aus ihr - so haengt alles, was heute an age_group
        # haengt (Anrede, Satzgrenze), in beiden Richtungen zusammen.
        schulstufe = (request.POST.get("schulstufe") or "").strip()
        if hat(faecher.EINSTELLUNG_SCHULSTUFE):
            if not stundenform.schulstufe_bekannt(schulstufe):
                # Die Frage bleibt an ihrem Platz, mit dem Fehler daneben;
                # der Rest des Formulars bleibt, wie er getippt war.
                return render(
                    request, "tutoring/lehrperson_uebersicht.html",
                    _uebersicht(request.user, fach=gewaehltes_fach,
                                fehler_feld="schulstufe",
                                umfang=gewaehlt["schluessel"],
                                titel=titel, thema=hinweis),
                )
            altersklasse = levels.altersklasse_fuer(schulstufe)
        else:
            altersklasse = (request.POST.get("age_group") or "").strip()
            if altersklasse not in dict(levels.ALTERSKLASSEN):
                altersklasse = levels.ALTERSKLASSE_STANDARD
            schulstufe = levels.schulstufe_fuer(altersklasse)

        # Die Musikstunde. Unbekanntes oder Fehlendes faellt auf die Vorgabe
        # zurueck, und was das Fach nicht braucht, wird gar nicht gelesen.
        lieddauer = musikstunde.HOECHSTDAUER_STANDARD
        if hat(faecher.EINSTELLUNG_LIEDDAUER):
            roh = (request.POST.get("song_max_seconds") or "").strip()
            if roh.isdigit() and int(roh) in musikstunde.DAUERN:
                lieddauer = int(roh)
        lieder = musikstunde.LIEDER_STANDARD
        if hat(faecher.EINSTELLUNG_LIEDER):
            roh = (request.POST.get("songs_per_child") or "").strip()
            if roh.isdigit() and int(roh) in musikstunde.LIEDER_WAHL:
                lieder = int(roh)
        gesang = musikstunde.GESANG_STANDARD
        if hat(faecher.EINSTELLUNG_GESANG):
            roh = (request.POST.get("song_language") or "").strip()
            if roh in dict(musikstunde.GESANGSSPRACHEN):
                gesang = roh
        # Ein Kontrollkaestchen: Fehlt es im Formular der Musikstunde, hat die
        # Lehrperson es abgewaehlt. In jedem anderen Fach bleibt die Vorgabe.
        texthilfe = True
        if hat(faecher.EINSTELLUNG_TEXTHILFE):
            texthilfe = bool(request.POST.get("song_text_help"))

        if not titel:
            # Kein Pflichtfeld mehr (Bericht 5.3: keine didaktische Evidenz
            # je Stunde). Vorbelegt mit Fach, Tag und Uhrzeit; auf der
            # Sitzungsseite mit dem Stift aenderbar.
            titel = stundenform.titel_vorschlag(faecher.name(gewaehltes_fach))

        sitzung = LearningSession.objects.create(
            title=titel[:120], task_hint=hinweis, max_level=obergrenze,
            idle_timeout_minutes=frist, research_level=protokollstufe,
            age_group=altersklasse, schulstufe=schulstufe,
            ask_before_solution=vorher_fragen,
            cloud_enabled=qualitaet, cloud_images_enabled=bilder,
            mode=betriebsart, subject=gewaehltes_fach,
            target_language=zielsprache, language_level=niveau,
            speaking_task=sprechaufgabe, song_max_seconds=lieddauer,
            songs_per_child=lieder, song_language=gesang, song_text_help=texthilfe,
            teacher=request.user,
        )
        return redirect("tutoring:lehrperson_sitzung", code=sitzung.code)

    return render(request, "tutoring/lehrperson_uebersicht.html",
                  _uebersicht(request.user, fach=request.GET.get("fach")))


def _sitzungen_von(benutzer):
    """Offene Sitzungen mit allem, was die Uebersicht anzeigt.

    Die Zahlen kommen aus zwei Sammelabfragen und nicht je Zeile: Eine
    Lehrperson kann ueber den Tag ein Dutzend Sitzungen offen haben.
    """
    sitzungen = list(
        LearningSession.objects.filter(teacher=benutzer, closed_at__isnull=True)
    )
    if not sitzungen:
        return []

    schluessel = [s.pk for s in sitzungen]
    teilnahmen = dict(
        Participation.objects.filter(learning_session_id__in=schluessel)
        .values("learning_session").annotate(n=models.Count("pk"))
        .values_list("learning_session", "n")
    )
    aufgaben = dict(
        Task.objects.filter(participation__learning_session_id__in=schluessel)
        .values("participation__learning_session")
        .annotate(n=models.Count("pk"))
        .values_list("participation__learning_session", "n")
    )
    zuletzt = dict(
        Task.objects.filter(participation__learning_session_id__in=schluessel)
        .values("participation__learning_session")
        .annotate(m=Max("created_at"))
        .values_list("participation__learning_session", "m")
    )
    # In der Musikstunde gibt es keine Aufgaben, sondern Lieder. Dieselbe
    # Art Sammelabfrage, damit die Karte nicht "0 Aufgaben" sagt, wo zwanzig
    # Lieder entstanden sind.
    lieder, lieder_zuletzt = {}, {}
    for sitzung_pk, anzahl, letzte in (
        Lied.objects.filter(participation__learning_session_id__in=schluessel)
        .values("participation__learning_session")
        .annotate(n=models.Count("pk"), m=Max("angelegt_am"))
        .values_list("participation__learning_session", "n", "m")
    ):
        lieder[sitzung_pk] = anzahl
        lieder_zuletzt[sitzung_pk] = letzte

    jetzt = timezone.now()
    zeilen = []
    for s in sitzungen:
        letzte = zuletzt.get(s.pk) or lieder_zuletzt.get(s.pk) or s.created_at
        fach = faecher.fach(s.subject)
        zeilen.append({
            "sitzung": s,
            "fach": fach,
            "beigetreten": teilnahmen.get(s.pk, 0),
            "aufgaben": aufgaben.get(s.pk, 0),
            "lieder": lieder.get(s.pk, 0),
            "zuletzt": letzte,
            "laeuft": jetzt - letzte < ARBEITET_GERADE,
            # Die Entscheidungen der Lehrperson in denselben Worten wie auf
            # der Sitzungsseite: bei Mathematik "Oberstufe · Lernen · Thema:
            # ...", in den anderen Faechern die Altersklasse.
            "marken": stundenform.marken(s),
        })
    # Das Neueste zuerst: Wer diese Seite oeffnet, will meistens in die
    # Sitzung, an der er gerade arbeitet.
    # Bei gleichem Zeitpunkt entscheidet die hoehere Nummer. Zwei Sitzungen,
    # in derselben Mikrosekunde angelegt, standen sonst in Anlegereihenfolge -
    # und der Test "die neueste steht oben" fiel auf schnellen Rechnern um.
    zeilen.sort(key=lambda z: (z["zuletzt"], z["sitzung"].pk), reverse=True)
    return zeilen


def _uebersicht(benutzer, fach=None, **zusatz):
    """Die Umgebung der Uebersichtsseite.

    Nur die zuletzt benutzten Sitzungen stehen als Karte, der Rest als
    schmale Liste. Im Browsertest standen 47 Karten uebereinander, fast alle
    aus Probelaeufen; die eine Sitzung, um die es ging, war darin nicht zu
    finden.

    `fach` entscheidet, ob die Seite den ersten oder den zweiten Schritt
    zeigt. Ohne Fach sind nur die Fachschaltflaechen zu sehen - das ist der
    Kern der Umstellung und kein Sonderfall: Vorher standen acht Bloecke
    gleichzeitig da, zwei davon mit der Aufschrift, fuer wen sie nicht
    gelten.
    """
    zeilen = _sitzungen_von(benutzer)
    gewaehltes = faecher.fach(fach)

    # Ein Nachschlagewerk und keine Funktion: In einer Django-Vorlage laesst
    # sich keine Funktion mit zwei Argumenten rufen.
    braucht = {
        einstellung: faecher.braucht(fach, einstellung)
        for einstellung in (
            faecher.EINSTELLUNG_SCHULSTUFE,
            faecher.EINSTELLUNG_STUFEN, faecher.EINSTELLUNG_NIVEAU,
            faecher.EINSTELLUNG_THEMA, faecher.EINSTELLUNG_ALTER,
            faecher.EINSTELLUNG_AUFGABE,
            faecher.EINSTELLUNG_PROTOKOLL, faecher.EINSTELLUNG_QUALITAET,
            faecher.EINSTELLUNG_RUHEZEIT, faecher.EINSTELLUNG_LIEDDAUER,
            faecher.EINSTELLUNG_LIEDER, faecher.EINSTELLUNG_GESANG,
            faecher.EINSTELLUNG_TEXTHILFE,
        )
    }

    return {
        # "offene" ist der Name, den die Vorlage benutzt; "sitzungen" bleibt
        # daneben, weil Tests und der Verlauf ihn kennen.
        "offene": zeilen[:KARTEN_HOECHSTENS],
        "sitzungen": zeilen[:KARTEN_HOECHSTENS],
        "weitere": zeilen[KARTEN_HOECHSTENS:],
        "leere_anzahl": sum(1 for z in zeilen if not z["beigetreten"]),
        "faecher": faecher.FAECHER,
        "fach": gewaehltes,
        "braucht": braucht,
        # Die drei Fragen des Mathe-Formulars (stundenform.py). Die Schulstufe
        # hat keine Vorauswahl, der Umfang steht auf Lernen; ein Fehler haelt
        # die getroffene Wahl fest (zusatz ueberschreibt).
        "schulstufen": stundenform.SCHULSTUFEN,
        "schulstufe": "",
        "umfang_karten": stundenform.UMFANG_KARTEN,
        "umfang": stundenform.UMFANG_VORGABE,
        "fehler_feld": "",
        "titel_vorschlag": stundenform.titel_vorschlag(
            gewaehltes["name"] if gewaehltes else ""
        ),
        "verfall_wahlen": VERFALL_WAHLEN,
        "ruhezeiten": VERFALL_WAHLEN,
        "protokollstufen": PROTOKOLLSTUFEN,
        "protokoll_waehlbar": settings.PROTOKOLLSTUFE_WAEHLBAR,
        "protokollstufe_fest": dict(PROTOKOLLSTUFEN).get(feste_protokollstufe(), ""),
        "altersklassen": levels.ALTERSKLASSEN,
        "stufenerklaerung": levels.erklaerung_fuer_lehrperson(),
        "niveaus": sprechcoach.NIVEAUS,
        "sprechaufgaben": sprechaufgaben.AUFGABEN,
        "freies_gespraech": sprechaufgaben.FREIES_GESPRAECH,
        "qualitaet_moeglich": cloud.moeglich(),
        "qualitaet_modell": settings.CLOUD_MODEL,
        "lieddauern": musikstunde.HOECHSTDAUERN,
        "lieddauer_vorgabe": musikstunde.HOECHSTDAUER_STANDARD,
        "lieder_wahl": musikstunde.LIEDER_WAHL,
        "lieder_vorgabe": musikstunde.LIEDER_STANDARD,
        "gesangssprachen": musikstunde.GESANGSSPRACHEN,
        "gesang_vorgabe": musikstunde.GESANG_STANDARD,
        "texthilfe_hoechstens": musikstunde.TEXTHILFE_HOECHSTENS,
        **zusatz,
    }


@login_required
def lehrperson_sitzung(request, code):
    """Die Seite fuer die Leinwand: Code, QR-Code, Klassenliste."""
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    # Die Lieder stehen auf der Seite und nicht in der Klassenliste: Die wird
    # alle fuenf Sekunden ersetzt, und ein Abspieler darin finge jedes Mal
    # von vorn an.
    lieder = []
    if sitzung.ist_musik:
        lieder = list(
            Lied.objects.filter(participation__learning_session=sitzung)
            .select_related("participation")
            .order_by("participation__joined_at", "angelegt_am", "pk")
        )
    # Der Aufgabenpool (1.11.2026) mit der Zahl der Kinder je Aufgabe.
    pool = []
    if sitzung.ist_hilfe:
        pool = list(
            sitzung.aufgabenpool.annotate(
                n=models.Count("bearbeitungen", distinct=True),
                fertig=models.Count("bearbeitungen",
                                    filter=models.Q(bearbeitungen__finished_at__isnull=False),
                                    distinct=True),
            )
        )
    return render(request, "tutoring/lehrperson_sitzung.html", {
        "sitzung": sitzung,
        "aufgabenpool": pool,
        "pool_fehler": request.GET.get("fehler", ""),
        "beitritts_url": _beitritts_url(request, sitzung.code),
        "stufenerklaerung": levels.erklaerung_fuer_lehrperson(),
        "lieder": lieder,
        # Die Entscheidungen der Lehrperson als Marken unter dem Titel, in
        # denselben Worten wie auf der Karte der Uebersicht.
        "marken": stundenform.marken(sitzung),
        **_klassenliste(sitzung),
    })


@login_required
def lehrperson_klassenliste(request, code):
    """Nur die Tabelle, htmx holt sie alle paar Sekunden nach."""
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    return render(request, "tutoring/_klassenliste.html", {
        "sitzung": sitzung, **_klassenliste(sitzung),
    })




def feste_protokollstufe():
    """Die Protokollstufe des Servers (settings.PROTOKOLLSTUFE), sonst Stufe 3."""
    stufe = settings.PROTOKOLLSTUFE
    return stufe if stufe in dict(PROTOKOLLSTUFEN) else FORSCHUNG_VOLL


def _kacheln(sitzung):
    """Je Teilnahme, was die Kachel des Klassenbilds ueber die aktuelle
    Aufgabe zeigt: erste Zeile, Stufenpunkte, letzter Beitrag, Diagnose.

    Die aktuelle Aufgabe ist die juengste. Drei Sammelabfragen fuer die
    ganze Klasse: Aufgaben, deren Hilfen, deren Rueckfragen. Die Fotos
    (image_data_url) werden nicht geladen - eine Data-URL je Kind alle fuenf
    Sekunden waere der groesste Posten der ganzen Seite.
    """
    aktuelle, alle = {}, {}
    for aufgabe in (
        Task.objects.filter(participation__learning_session=sitzung)
        .order_by("participation_id", "-created_at", "-pk")
        .only("participation", "text", "source", "created_at", "finished_at",
              "repeats", "current_level", "rating")
    ):
        aktuelle.setdefault(aufgabe.participation_id, aufgabe)
        # Alle Aufgaben des Kindes, fuer den Eigenanteil ueber die Sitzung.
        alle.setdefault(aufgabe.participation_id, []).append(aufgabe)
    if not aktuelle:
        return {}

    schluessel = [a.pk for liste in alle.values() for a in liste]
    hilfen = {}
    for hilfe in (
        Hint.objects.filter(task_id__in=schluessel)
        .order_by("created_at", "pk")
        .only("task", "level", "art", "created_at", "response", "responded_at",
              "result", "error", "next_level", "goal_note", "lage", "absicht",
              "next_form")
    ):
        hilfen.setdefault(hilfe.task_id, []).append(hilfe)
    fragen = {}
    for frage in (
        Question.objects.filter(task_id__in=schluessel)
        .order_by("created_at", "pk")
        .only("task", "text", "created_at")
    ):
        fragen[frage.task_id] = frage

    kacheln = {}
    for teilnahme_pk, aufgabe in aktuelle.items():
        folge = hilfen.get(aufgabe.pk, [])
        # Nur Stufen zaehlen fuer die Punkte; Nachfrage, Auftakt und
        # Bestaetigung sind Zuege, keine Stufen.
        stufenfolge = [h.level for h in folge if h.art == levels.ART_HILFE]
        beantwortet = [h for h in folge if h.response]
        letzte_antwort = beantwortet[-1] if beantwortet else None
        letzte_frage = fragen.get(aufgabe.pk)

        # Der letzte Beitrag des Kindes: der Versuch oder die Frage, je
        # nachdem, was spaeter kam. Bei gleichem Zeitstempel (die Uhr unter
        # Windows ist grob) gilt die Frage, denn sie wurde spaeter angelegt.
        beitrag = ""
        if letzte_antwort is not None and (
            letzte_frage is None
            or (letzte_antwort.responded_at or letzte_antwort.created_at)
            > letzte_frage.created_at
        ):
            beitrag = klassenbild.erste_zeile(letzte_antwort.response)
        elif letzte_frage is not None:
            beitrag = klassenbild.erste_zeile(letzte_frage.text)

        aufgabe_zeile = klassenbild.erste_zeile(aufgabe.text)
        if not aufgabe_zeile and aufgabe.source == FOTOGRAFIERT:
            aufgabe_zeile = "Foto einer Aufgabe"
        fertig = aufgabe.finished_at is not None
        punkte = klassenbild.stufenpunkte(stufenfolge, sitzung.max_level)
        # Der Eigenanteil (Thomas, 1.11.2026): ueber alle Aufgaben des
        # Kindes, die ein Ergebnis haben; eine grobe Einschaetzung.
        einschaetzungen = [klassenbild.eigenanteil(hilfen.get(a.pk, []))
                           for a in alle.get(teilnahme_pk, [])]
        kacheln[teilnahme_pk] = {
            "eigenanteil_zeile": klassenbild.eigenanteil_zeile(einschaetzungen),
            "note_zeile": klassenbild.note_zeile(
                [a.rating for a in alle.get(teilnahme_pk, [])]),
            "aufgabe_zeile": aufgabe_zeile,
            "aufgabe_fertig": fertig,
            "punkte": punkte,
            "breite": klassenbild.breite(punkte),
            "beitrag": beitrag,
            "diagnose": klassenbild.diagnose(letzte_antwort),
            # Eine abgeschlossene Aufgabe braucht keinen Blick mehr wegen
            # einer dreimal gegebenen Stufe.
            "dreimal": (not fertig
                        and klassenbild.dreimal_dieselbe(stufenfolge, aufgabe.repeats)),
            "stufe_zuletzt": stufenfolge[-1] if stufenfolge else 0,
        }
    return kacheln


# Die Kachel eines Kindes, das in Trainer, Sprechcoach oder Musikstunde noch
# nichts getan hat. Dieselben Schluessel wie _kacheln_andere, damit die
# Vorlage nicht fragen muss.
LEERE_KACHEL_ANDERE = {
    "zeile": "", "notiz": "", "beitrag": "", "fertig": False,
    "dreimal": False, "stufe_zuletzt": 0,
}


def _liedzeile(text):
    """Die erste gesungene Zeile eines Liedtexts, ohne die Marken.

    Ein Liedtext beginnt fast immer mit "[verse]"; das ist keine Zeile, die
    der Lehrperson etwas sagt.
    """
    ohne_marken = "\n".join(
        zeile for zeile in (text or "").splitlines()
        if not (zeile.strip().startswith("[") and zeile.strip().endswith("]"))
    )
    return klassenbild.erste_zeile(ohne_marken)


def _kacheln_andere(sitzung):
    """Je Teilnahme die Kachel in Trainer, Sprechcoach und Musikstunde.

    Dieselbe Kachel wie in der Aufgabenhilfe (Bericht vom 19.10.2026), mit
    dem, was die Betriebsart hergibt: eine Zeile oben (Thema, Phase, Zahl
    der Lieder), eine Notiz (Schritt und Aufgaben; Stil und Stand des
    letzten Liedes) und der letzte Beitrag des Kindes. Thomas (22.10.2026):
    In jeder Betriebsart muss die Lehrperson in den Chat des Kindes kommen -
    also traegt jede Kachel den Weg in den Verlauf und zeigt, was das Kind
    zuletzt getan hat. Sammelabfragen wie in _kacheln: Die Liste wird alle
    fuenf Sekunden nachgeholt.
    """
    kacheln = {}
    if sitzung.ist_trainer:
        laeufe = {}
        for lauf in (
            TrainerLauf.objects.filter(participation__learning_session=sitzung)
            .order_by("participation_id", "-created_at", "-pk")
            .only("participation", "topic", "step_no", "tasks_given",
                  "tasks_right", "finished_at")
        ):
            laeufe.setdefault(lauf.participation_id, lauf)
        letzte = {}
        for zug in (
            TrainerZug.objects.filter(run_id__in=[l.pk for l in laeufe.values()],
                                      role=TrainerZug.LERNEND)
            .order_by("created_at", "pk").only("run", "text")
        ):
            letzte[zug.run_id] = zug
        for pk, lauf in laeufe.items():
            notiz = f"Schritt {lauf.step_no}"
            if lauf.tasks_given:
                notiz += f" · {lauf.tasks_right} von {lauf.tasks_given} Aufgaben richtig"
            zug = letzte.get(lauf.pk)
            kacheln[pk] = {
                "zeile": (klassenbild.erste_zeile(lauf.topic)
                          or klassenbild.erste_zeile(sitzung.task_hint)),
                "notiz": notiz,
                "beitrag": klassenbild.erste_zeile(zug.text) if zug else "",
                "fertig": lauf.finished_at is not None,
            }
    elif sitzung.ist_sprechcoach:
        laeufe = {}
        for lauf in (
            SprachLauf.objects.filter(participation__learning_session=sitzung)
            .order_by("participation_id", "-created_at", "-pk")
            .only("participation", "phase", "finished_at")
        ):
            laeufe.setdefault(lauf.participation_id, lauf)
        letzte = {}
        for zug in (
            SprachZug.objects.filter(run_id__in=[l.pk for l in laeufe.values()],
                                     role=SprachZug.LERNEND)
            .order_by("created_at", "pk").only("run", "text")
        ):
            letzte[zug.run_id] = zug
        for pk, lauf in laeufe.items():
            zug = letzte.get(lauf.pk)
            kacheln[pk] = {
                "zeile": lauf.get_phase_display(),
                # Die Zahlen zum Gespraech kommen aus zahlen_der_klasse und
                # werden in _klassenliste als Notiz eingesetzt.
                "notiz": "",
                "beitrag": klassenbild.erste_zeile(zug.text) if zug else "",
                "fertig": lauf.finished_at is not None,
            }
    elif sitzung.ist_musik:
        anzahl = dict(
            Lied.objects.filter(participation__learning_session=sitzung)
            .values("participation").annotate(n=models.Count("pk"))
            .values_list("participation", "n")
        )
        letzte = {}
        for lied in (
            Lied.objects.filter(participation__learning_session=sitzung)
            .order_by("participation_id", "-angelegt_am", "-pk")
            .only("participation", "stil", "sekunden", "zustand", "text")
        ):
            letzte.setdefault(lied.participation_id, lied)
        for pk, lied in letzte.items():
            n = anzahl.get(pk, 0)
            kacheln[pk] = {
                "zeile": f"{n} Lied" if n == 1 else f"{n} Lieder",
                "notiz": f"{lied.stil} · {lied.sekunden} s · {lied.get_zustand_display()}",
                "beitrag": _liedzeile(lied.text),
                "fertig": False,
            }
    elif sitzung.ist_safechat:
        # Im Safe Chat: wie viele Nachrichten das Kind geschrieben hat, wie
        # viele davon wirklich hinausgegangen sind, das letzte Urteil der
        # Gegenstelle in Worten, und der letzte Beitrag. Vier Sammelabfragen
        # fuer die ganze Klasse, keine je Kind.
        alle = ChatZug.objects.filter(participation__learning_session=sitzung)
        anzahl = dict(
            alle.filter(role=ChatZug.LERNEND)
            .values("participation").annotate(n=models.Count("pk"))
            .values_list("participation", "n")
        )
        draussen = dict(
            alle.filter(role=ChatZug.KI, weg=ChatZug.WEG_AUSSEN)
            .exclude(aussen_gesendet="")
            .values("participation").annotate(n=models.Count("pk"))
            .values_list("participation", "n")
        )
        letzte = {}
        for zug in (
            alle.filter(role=ChatZug.LERNEND)
            .order_by("participation_id", "-created_at", "-pk")
            .only("participation", "text")
        ):
            letzte.setdefault(zug.participation_id, zug)
        urteile = {}
        for zug in (
            alle.filter(role=ChatZug.KI).exclude(urteil="")
            .order_by("participation_id", "-created_at", "-pk")
            .only("participation", "urteil")
        ):
            urteile.setdefault(zug.participation_id, zug)
        for pk, zug in letzte.items():
            n = anzahl.get(pk, 0)
            k = draussen.get(pk, 0)
            notiz = ("nichts nach draußen" if k == 0
                     else f"{k} nach draußen")
            urteil = urteile.get(pk)
            if urteil is not None:
                notiz += f" · zuletzt {urteil.urteil_text}"
            kacheln[pk] = {
                "zeile": f"{n} Nachricht" if n == 1 else f"{n} Nachrichten",
                "notiz": notiz,
                "beitrag": klassenbild.erste_zeile(zug.text),
                "fertig": False,
            }
    for kachel in kacheln.values():
        kachel.setdefault("dreimal", False)
        kachel.setdefault("stufe_zuletzt", 0)
    return kacheln


def _klassenliste(sitzung):
    """Eine Zeile je Teilnahme, dazu die Gesamtzahlen.

    Was frueher nur als Summe dastand, steht jetzt je Tier. Die Ampel zeigt
    die schlimmste Einstufung, die bei diesem Tier vorgekommen ist.

    In der Aufgabenhilfe ist jede Zeile eine Kachel des Klassenbilds
    (klassenbild.py, Bericht vom 19.10.2026): Aufgabe, Stufenpunkte, letzter
    Beitrag, Diagnose - und die Zeilen stehen nach Aufmerksamkeitsbedarf,
    nicht nach Beitrittszeit. Sprechcoach, Musikstunde und Trainer behalten
    ihre Reihenfolge und ihre Tabelle.

    Die Zeitpunkte kommen aus Sammelabfragen und nicht je Zeile: Die Liste
    wird alle fuenf Sekunden nachgeholt, und dreissig Kinder mal sieben
    Abfragen waere Verschwendung.
    """
    aufgaben = dict(
        Task.objects.filter(participation__learning_session=sitzung)
        .values("participation").annotate(anzahl=models.Count("pk"), letzte=Max("created_at"))
        .values_list("participation", "letzte")
    )
    anzahl_aufgaben = dict(
        Task.objects.filter(participation__learning_session=sitzung)
        .values("participation").annotate(anzahl=models.Count("pk"))
        .values_list("participation", "anzahl")
    )
    anzahl_hilfen = dict(
        Hint.objects.filter(task__participation__learning_session=sitzung)
        .values("task__participation").annotate(anzahl=models.Count("pk"))
        .values_list("task__participation", "anzahl")
    )
    letzte_hilfe = dict(
        Hint.objects.filter(task__participation__learning_session=sitzung)
        .values("task__participation")
        .annotate(letzte=Max(models.functions.Coalesce("responded_at", "created_at")))
        .values_list("task__participation", "letzte")
    )
    # Umgehungsversuche je Kind (offene Karten, 31.10.2026): die Beitraege,
    # die die Diagnose als "umgehung" eingestuft hat, ueber alle Aufgaben
    # der Sitzung. Die Lehrperson bekommt die Zahl als Marke auf der Kachel.
    umgehungen = dict(
        Hint.objects.filter(task__participation__learning_session=sitzung,
                            absicht=levels.ABSICHT_UMGEHUNG)
        .values("task__participation").annotate(anzahl=models.Count("pk"))
        .values_list("task__participation", "anzahl")
    )

    # Beim Sprechcoach gibt es keine Aufgaben und Hilfen, sondern Gespraeche.
    # Die Zahlen dazu (Regel 14 des Berichts) kommen in einem Zug fuer die
    # ganze Klasse.
    sprech = None
    if sitzung.ist_sprechcoach:
        from .sprechcoach_views import zahlen_der_klasse
        sprech = zahlen_der_klasse(sitzung)

    # In der Musikstunde die Zahl der Lieder je Tier. Die Ampel ist dieselbe
    # wie sonst: Die Einstufung jedes Liedtextes geht in worst_flag ein.
    lieder_je, lieder_zuletzt = {}, {}
    if sitzung.ist_musik:
        for teilnahme_pk, anzahl, letzte in (
            Lied.objects.filter(participation__learning_session=sitzung)
            .values("participation")
            .annotate(n=models.Count("pk"), m=Max("angelegt_am"))
            .values_list("participation", "n", "m")
        ):
            lieder_je[teilnahme_pk] = anzahl
            lieder_zuletzt[teilnahme_pk] = letzte

    # Im Safe Chat die Zahlen der Klasse fuer die Zahlenzeile: Nachrichten
    # der Kinder und davon nach draussen.
    chat_summe = aussen_summe = 0
    if sitzung.ist_safechat:
        kinderzuege = ChatZug.objects.filter(
            participation__learning_session=sitzung, role=ChatZug.LERNEND
        )
        chat_summe = kinderzuege.count()
        aussen_summe = kinderzuege.filter(weg=ChatZug.WEG_AUSSEN).count()

    # Das Klassenbild in jeder Betriebsart (Thomas, 22.10.2026): in der
    # Aufgabenhilfe mit Stufenpunkten und Diagnose, sonst mit dem, was die
    # Betriebsart hergibt (_kacheln_andere). Jede Kachel fuehrt in den
    # Verlauf des Kindes.
    ist_hilfe = sitzung.mode == LearningSession.BETRIEB_HILFE
    kacheln = _kacheln(sitzung) if ist_hilfe else _kacheln_andere(sitzung)

    # Wann das Kind zuletzt etwas getan hat: In Trainer und Sprechcoach sind
    # das die Zuege, nicht Aufgaben und Hilfen. Ohne diese Quelle stand dort
    # jedes Kind nach fuenf Minuten als still, obwohl es gerade sprach.
    zuege_zuletzt = {}
    if sitzung.ist_trainer:
        zuege_zuletzt = dict(
            TrainerZug.objects.filter(run__participation__learning_session=sitzung)
            .values("run__participation").annotate(m=Max("created_at"))
            .values_list("run__participation", "m")
        )
    elif sitzung.ist_sprechcoach:
        zuege_zuletzt = dict(
            SprachZug.objects.filter(run__participation__learning_session=sitzung)
            .values("run__participation").annotate(m=Max("created_at"))
            .values_list("run__participation", "m")
        )
    elif sitzung.ist_safechat:
        zuege_zuletzt = dict(
            ChatZug.objects.filter(participation__learning_session=sitzung)
            .values("participation").annotate(m=Max("created_at"))
            .values_list("participation", "m")
        )

    jetzt = timezone.now()
    zeilen = []
    for teilnahme in sitzung.participations.all():
        zeitpunkte = [teilnahme.joined_at]
        for quelle in (aufgaben, letzte_hilfe, lieder_zuletzt, zuege_zuletzt):
            wert = quelle.get(teilnahme.pk)
            if wert:
                zeitpunkte.append(wert)
        zuletzt = max(zeitpunkte)
        kachel = kacheln.get(teilnahme.pk) or (
            klassenbild.leere_kachel(sitzung.max_level) if ist_hilfe
            else dict(LEERE_KACHEL_ANDERE)
        )
        still = jetzt - zuletzt >= klassenbild.STILL_NACH
        rang, grund = klassenbild.einordnung(
            teilnahme.worst_flag, kachel["dreimal"], still,
            stufe=kachel["stufe_zuletzt"],
            stille_minuten=int((jetzt - zuletzt).total_seconds() // 60),
            umgehungen=umgehungen.get(teilnahme.pk, 0),
        )
        zeilen.append({
            "teilnahme": teilnahme,
            "umgehungen": umgehungen.get(teilnahme.pk, 0),
            "aufgaben": anzahl_aufgaben.get(teilnahme.pk, 0),
            "hilfen": anzahl_hilfen.get(teilnahme.pk, 0),
            "stufe": teilnahme.max_level_reached,
            "ampel": teilnahme.worst_flag,
            "ampel_text": teilnahme.ampel_beschreibung,
            "ampel_kurz": klassenbild.AMPEL_KURZ.get(
                teilnahme.worst_flag, teilnahme.ampel_beschreibung
            ),
            "zuletzt": zuletzt,
            "aktiv": jetzt - zuletzt < ARBEITET_GERADE,
            "still": still,
            "rang": rang,
            "grund": grund,
            "sprech": (sprech or {}).get("je_teilnahme", {}).get(teilnahme.pk),
            "lieder": lieder_je.get(teilnahme.pk, 0),
            **kachel,
        })
        # Die drei Zeilen, die jede Kachel hat, in jeder Betriebsart: Was
        # das Kind tut, eine Notiz dazu, sein letzter Beitrag. In der
        # Aufgabenhilfe heissen sie Aufgabe und Diagnose; beim Sprechcoach
        # ist die Notiz die Zahlenzeile aus zahlen_der_klasse.
        z = zeilen[-1]
        z.setdefault("zeile", z.get("aufgabe_zeile", ""))
        z.setdefault("notiz", z.get("diagnose", ""))
        z.setdefault("fertig", z.get("aufgabe_fertig", False))
        if z["sprech"] and z["sprech"].get("zahlen") and not z["notiz"]:
            z["notiz"] = " · ".join(str(t) for t in z["sprech"]["zahlen"])
    # Wer einen Blick braucht, steht oben: Ampel, dann dreimal dieselbe
    # Stufe, dann fuenf Minuten Stille, dann der Rest nach Aktivitaet. In
    # jeder Betriebsart, damit die Seite ueberall gleich zu lesen ist.
    zeilen.sort(key=klassenbild.sortierschluessel)
    return {
        "sprech_summe": (sprech or {}).get("summe"),
        "lieder_summe": sum(lieder_je.values()),
        "chat_summe": chat_summe,
        "aussen_summe": aussen_summe,
        "zeilen": zeilen,
        "zaehler": sitzung.zaehler,
        "auffaellige": [z for z in zeilen if z["ampel"] != pruefung.GRUEN],
        "aktive": [z for z in zeilen if z["aktiv"]],
    }


@login_required
def lehrperson_verlauf(request, code, teilnahme_id):
    """Der vollstaendige Verlauf eines Tieres."""
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    teilnahme = get_object_or_404(
        Participation, pk=teilnahme_id, learning_session=sitzung
    )
    aufgaben = list(
        teilnahme.tasks.select_related("participation__learning_session")
        .prefetch_related("hints").order_by("created_at")
    )
    # Jede Betriebsart hat ihren Verlauf (Thomas, 22.10.2026: "In der
    # Musikstunde kann ich nicht in die Chats rein"): Trainer- und
    # Sprechgespraeche als Zuege, in der Musikstunde die Lieder mit Text und
    # Abspieler. _verlauf.html verzweigt nach der Betriebsart.
    laeufe, sprachlaeufe, lieder, chatzuege = [], [], [], []
    if sitzung.ist_trainer:
        laeufe = teilnahme.trainerlaeufe.prefetch_related("zuege").order_by("created_at")
    elif sitzung.ist_sprechcoach:
        sprachlaeufe = teilnahme.sprachlaeufe.prefetch_related("zuege").order_by("created_at")
    elif sitzung.ist_musik:
        lieder = teilnahme.lieder.order_by("angelegt_am", "pk")
    elif sitzung.ist_safechat:
        # Dieselben Zuege mit demselben Protokoll, das das Kind sieht
        # (Thomas, 23.10.2026: "fuer alle einsichtbar").
        chatzuege = safechat.mit_protokoll(
            list(teilnahme.chatzuege.order_by("created_at", "pk"))
        )
    # Der Weg nach draussen, in jeder Betriebsart (Thomas, 1.11.2026: "Wenn
    # das Frontier-Modell mitarbeitet, ist auch die Kommunikation zwischen
    # Frontier-Modell und lokaler KI sichtbar"): die Anfragen nach draussen
    # fuer dieses Kind aus dem Protokoll, oder der Satz, dass es keinen gibt.
    aussenzuege = list(
        Interaction.objects.filter(
            session_key=sitzung.log_key, participant_key=teilnahme.log_key,
            route=Interaction.CLOUD,
        ).order_by("created_at", "pk")
    )
    anteil_zeile = note_zeile = ""
    if sitzung.mode == LearningSession.BETRIEB_HILFE:
        anteil_zeile = klassenbild.eigenanteil_zeile([a.eigenanteil for a in aufgaben])
        note_zeile = klassenbild.note_zeile([a.rating for a in aufgaben])
    vorlage = ("tutoring/_verlauf.html" if request.headers.get("HX-Request")
               else "tutoring/lehrperson_verlauf.html")
    return render(request, vorlage, {
        "sitzung": sitzung, "teilnahme": teilnahme, "aufgaben": aufgaben,
        "laeufe": laeufe, "sprachlaeufe": sprachlaeufe, "lieder": lieder,
        "chatzuege": chatzuege,
        "aussenzuege": aussenzuege,
        "aussenweg": _aussenweg(sitzung, teilnahme, aussenzuege),
        "anteil_zeile": anteil_zeile,
        "note_zeile": note_zeile,
    })


# Wo keine externe KI mitarbeitet, sagt der Verlauf das in einem Satz, statt
# eine leere Liste zu zeigen. Trainer und Sprechcoach rufen nie nach
# draussen, auch wenn die Qualitaetssicherung im Formular angehakt ist;
# die Musikstunde kennt den Haken nicht (faecher.py).
OHNE_AUSSENWEG = {
    LearningSession.BETRIEB_TRAINER: (
        "Im Trainer arbeitet keine externe KI mit. Das Gespräch bleibt am "
        "Spark; es gibt keinen Weg nach draußen."
    ),
    LearningSession.BETRIEB_SPRACHE: (
        "Im Sprechcoach arbeitet keine externe KI mit. Aufnahmen, Text und "
        "Antworten bleiben am Spark; es gibt keinen Weg nach draußen."
    ),
    LearningSession.BETRIEB_MUSIK: (
        "In der Musikstunde arbeitet keine externe KI mit. Liedtexte, "
        "Vorschläge und Lieder bleiben am Spark; es gibt keinen Weg nach "
        "draußen."
    ),
}


def _aussenweg(sitzung, teilnahme, aussenzuege):
    """Der Satz ueber dem Weg nach draussen im Verlauf, und ob es ihn gibt."""
    satz = OHNE_AUSSENWEG.get(sitzung.mode)
    if satz:
        return {"moeglich": False, "satz": satz}
    tier = teilnahme.tier_name
    schalter = "Draußen fragen" if sitzung.ist_safechat else "Die Qualitätssicherung"
    if aussenzuege:
        n = len(aussenzuege)
        satz = (f"{n} Anfrage{'n' if n != 1 else ''} nach draußen für {tier}. Jede "
                "steht hier mit dem, was der Spark hinausgeschickt hat und was "
                "zurückkam, soweit die Protokollstufe den Wortlaut trägt; ")
        satz += ("im Chat steht derselbe Weg Schritt für Schritt."
                 if sitzung.ist_safechat else
                 "bei der Aufgabe steht dazu, wie der Spark die Antwort bekommen hat.")
    elif sitzung.cloud_enabled and cloud.moeglich():
        satz = f"{schalter} ist ein, aber für {tier} ist bisher nichts hinausgegangen."
    else:
        satz = f"{schalter} ist für diese Sitzung aus: Für {tier} ist nichts hinausgegangen."
    return {"moeglich": True, "satz": satz}


@login_required
@require_POST
def lehrperson_aufgabe_hinzufuegen(request, code):
    """Die Lehrperson stellt eine Aufgabe in die laufende Sitzung (1.11.2026).

    Text oder Foto; vom Foto schreibt der Spark den Text ab. Dann die
    Vorpruefung (aufgabenpool.pruefen): Der Spark loest, mit
    Qualitaetssicherung auch die externe KI, der Status sagt, ob beide
    einig sind. Die Seite wartet dafuer einige Sekunden.
    """
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    zurueck = reverse("tutoring:lehrperson_sitzung", args=[sitzung.code])
    if not sitzung.ist_hilfe or not sitzung.ist_offen:
        return redirect(zurueck)
    text = (request.POST.get("text") or "").strip()[:MAX_AUFGABENLAENGE]
    foto = _foto_hochgeladen(request)
    if foto and not text:
        try:
            text = (spark.text_aus_bild(foto)[0] or "").strip()[:MAX_AUFGABENLAENGE]
        except Exception as fehler:  # noqa: BLE001 - dann bleibt der Text leer
            logger.warning("Aufgabenpool: Abschrift fehlgeschlagen: %s", type(fehler).__name__)
            text = ""
    if not text:
        return redirect(zurueck + "?fehler=aufgabe#aufgabenpool")
    vorlage = SessionTask.objects.create(
        session=sitzung, text=text, image_data_url=foto,
        position=sitzung.aufgabenpool.count() + 1,
    )
    aufgabenpool.pruefen(vorlage, sitzung, verbrauch=cloud_verbrauch(sitzung))
    sitzung.beruehren()
    return redirect(zurueck + "#aufgabenpool")


@login_required
@require_POST
def lehrperson_aufgabe_entfernen(request, code, pk):
    """Nimmt eine Aufgabe aus dem Pool; begonnene Bearbeitungen behalten ihren Text."""
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    SessionTask.objects.filter(session=sitzung, pk=pk).delete()
    return redirect(reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]) + "#aufgabenpool")


def _foto_hochgeladen(request):
    """Ein hochgeladenes Bild als Data-URL, sonst leer (hoechstens 8 MB)."""
    import base64

    datei = request.FILES.get("foto")
    if not datei or not (datei.content_type or "").startswith("image/"):
        return ""
    if datei.size > 8 * 1024 * 1024:
        return ""
    roh = base64.b64encode(datei.read()).decode("ascii")
    return f"data:{datei.content_type};base64,{roh}"


@login_required
@require_POST
def lehrperson_sitzung_beenden(request, code):
    """Beenden loescht alles, was in der Sitzung entstanden ist."""
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    sitzung.beenden()
    return redirect("tutoring:lehrperson_uebersicht")


@login_required
@require_POST
def lehrperson_titel(request, code):
    """Der Titel, hinterher geaendert: der Stift neben dem Titel.

    Der Titel ist beim Anlegen kein Pflichtfeld mehr, sondern vorbelegt;
    wer ihn aendern will, tut das hier. Nur die Lehrperson dieser Sitzung,
    sonst 404 wie ueberall auf diesen Seiten. Leer heisst: bleibt, wie er
    war - ein Titel kann nicht verschwinden.
    """
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    titel = (request.POST.get("title") or "").strip()[:120]
    if titel and titel != sitzung.title:
        sitzung.title = titel
        sitzung.save(update_fields=["title"])
    return redirect("tutoring:lehrperson_sitzung", code=sitzung.code)


@login_required
def lehrperson_bereitschaft(request):
    """Antwortet der Spark, und wie schnell?

    Die Frage, die man fuenf Minuten vor dem Vortrag stellt. Sie kostet zwei
    echte Aufrufe und steht deshalb hinter der Anmeldung.
    """
    pruefungen = bereitschaft.pruefen()
    return render(request, "tutoring/bereitschaft.html", {
        "pruefungen": pruefungen,
        "alles_gut": all(p["ok"] for p in pruefungen),
        "jetzt": timezone.now(),
    })


@login_required
@require_POST
def lehrperson_leere_beenden(request):
    """Beendet alle Sitzungen, in die niemand beigetreten ist.

    Nach einem Vormittag Vorbereitung stehen zwei Dutzend Codes offen, in
    denen nichts steht. Sie einzeln zu beenden ist Arbeit ohne Sinn; und weil
    niemand beigetreten ist, kann dabei auch nichts verlorengehen.
    """
    # Erst die Liste, dann das Beenden: Der Filter laeuft sonst gegen Daten,
    # die sich unter ihm veraendern.
    leer = list(LearningSession.objects.filter(
        teacher=request.user, closed_at__isnull=True, participations__isnull=True
    ))
    for sitzung in leer:
        sitzung.beenden()
    return redirect("tutoring:lehrperson_uebersicht")


def qr_code(request, code):
    """QR-Code zur Beitrittsadresse, als SVG und damit beliebig gross."""
    url = _beitritts_url(request, code)
    puffer = io.BytesIO()
    segno.make(url, error="m").save(puffer, kind="svg", scale=8, border=2, dark="#11212b")
    antwort = HttpResponse(puffer.getvalue(), content_type="image/svg+xml")
    antwort["Cache-Control"] = "no-store"
    return antwort


def _beitritts_url(request, code):
    return request.build_absolute_uri(
        reverse("tutoring:beitreten_mit_code", kwargs={"code": code})
    )


# -------------------------------------------------------------- Teilnehmende

def beitreten(request, code=None):
    """Beitritt per Code. Ohne Konto, ohne Namen, ohne Anmeldung."""
    verfallene_aufraeumen()

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()

    if not code:
        return render(request, "core/start.html", {"fehler": "Bitte gib den Code ein."})

    sitzung = LearningSession.objects.filter(code=code).first()
    if sitzung is None or not sitzung.ist_offen:
        return render(request, "core/start.html", {
            "code": code,
            "fehler": "Diesen Code gibt es nicht oder die Sitzung ist schon vorbei.",
        })

    teilnahme = _teilnahme_holen(request, sitzung)
    if teilnahme is None:
        teilnahme = Participation.objects.create(
            learning_session=sitzung, token=Participation.token_erzeugen()
        )
        request.session[SCHLUESSEL_TEILNAHME] = teilnahme.token
    sitzung.beruehren()
    return redirect("tutoring:chat")


def zustimmung(request):
    """Fragt die Zustimmung zur vollstaendigen Forschungsaufzeichnung.

    Ablehnen kostet den Zugang nicht. Wer ablehnt, nimmt an der Stunde
    genauso teil und wird nur nach Stufe 1 protokolliert, also ohne jeden
    Inhalt. Eine Zustimmung, deren Ablehnung den Zugang kostet, ist keine
    Zustimmung, sondern eine Drohung.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return redirect("tutoring:chat")
    if not sitzung.zustimmung_noetig or teilnahme.consent_asked:
        return redirect("tutoring:chat")

    if request.method == "POST":
        teilnahme.consent_given = request.POST.get("zustimmung") == "ja"
        teilnahme.consent_asked = True
        teilnahme.save(update_fields=["consent_given", "consent_asked"])
        return redirect("tutoring:chat")

    return render(request, "tutoring/zustimmung.html", {"sitzung": sitzung})


def tier_waehlen(request):
    """Das Kind waehlt sein Tier fuer diese Sitzung."""
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or teilnahme.hat_tier:
        return redirect("tutoring:chat")

    fehler = None
    if request.method == "POST":
        gewaehlt = (request.POST.get("tier") or "").strip()
        if not tiere.ist_bekannt(gewaehlt):
            fehler = "Bitte wähle ein Tier aus."
        else:
            try:
                with transaction.atomic():
                    teilnahme.animal = gewaehlt
                    teilnahme.save(update_fields=["animal"])
            except IntegrityError:
                # Zwei Kinder haben im selben Augenblick getippt. Die
                # Bedingung in der Datenbank entscheidet, nicht die Anzeige.
                teilnahme.refresh_from_db()
                fehler = (
                    f"Den {tiere.name(gewaehlt)} hat gerade jemand anderer genommen. "
                    "Such dir bitte ein anderes Tier aus."
                )
            else:
                return redirect("tutoring:chat")

    return render(request, "tutoring/tier_waehlen.html", {
        "sitzung": sitzung,
        "tierliste": tiere.freie(_vergebene_tiere(sitzung)),
        "fehler": fehler,
    })


def _vergebene_tiere(sitzung):
    return sitzung.participations.exclude(animal="").values_list("animal", flat=True)


def _teilnahme_holen(request, sitzung=None):
    token = request.session.get(SCHLUESSEL_TEILNAHME)
    if not token:
        return None
    abfrage = Participation.objects.select_related("learning_session").filter(token=token)
    if sitzung is not None:
        abfrage = abfrage.filter(learning_session=sitzung)
    return abfrage.first()


def chat(request):
    """Der Arbeitsplatz des Kindes: Aufgabe eingeben, Hilfen anfordern."""
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        request.session.pop(SCHLUESSEL_TEILNAHME, None)
        return render(request, "core/start.html", {
            "fehler": "Die Sitzung ist beendet. Alles, was du eingegeben hast, ist geloescht.",
        })
    # Die Zustimmung wird nur Erwachsene gefragt. Minderjaehrige koennen in
    # eine Forschungsverarbeitung rechtlich gar nicht selbst einwilligen; das
    # entscheiden Schule und Erziehungsberechtigte ausserhalb dieser
    # Anwendung. Ein Zustimmungsbildschirm fuer Kinder waere deshalb nicht
    # nur ueberfluessiger Text, sondern eine falsche Auskunft.
    if sitzung.zustimmung_noetig and not teilnahme.consent_asked:
        return redirect("tutoring:zustimmung")
    if not teilnahme.hat_tier:
        return redirect("tutoring:tier_waehlen")
    if sitzung.ist_trainer:
        return redirect("tutoring:trainer")
    if sitzung.ist_sprechcoach:
        return redirect("tutoring:sprechcoach")
    if sitzung.ist_musik:
        return redirect("tutoring:musik")
    if sitzung.ist_safechat:
        return redirect("tutoring:safechat")

    aufgabe = teilnahme.tasks.prefetch_related("hints").last()
    return render(request, "tutoring/chat.html", _chat_umgebung(teilnahme, aufgabe))


def _stufenliste(sitzung, aufgabe, naechste=None):
    """Der Weg durch die Stufen: fuenf Punkte mit den Kindernamen.

    Ein Kind soll sehen, wo es steht und was noch kommt. Ohne das wirkt die
    Folge von Hilfen beliebig, und man weiss nie, ob gleich Schluss ist.
    Seit der Diagnose ist der Weg keine Leiter: "aktuell" ist die Stufe, die
    als Naechstes kommt, und die kann unter der hoechsten gegebenen liegen.
    """
    gegeben = ({hilfe.level for hilfe in aufgabe.hints.all() if hilfe.ist_hilfe}
               if aufgabe else set())
    return [
        {
            "nr": nr,
            "name": levels.kindername(nr),
            "erledigt": nr in gegeben,
            "aktuell": nr == naechste,
        }
        for nr in range(1, sitzung.max_level + 1)
    ]


# Was das Kind geschrieben hat, wenn es waehrend einer wartenden Hilfe den
# Tippknopf drueckt. Ehrlich festgehalten statt mit einer Fehlermeldung
# abgewiesen: Der Knopf ist das, was ein Kind drueckt, das nicht weiterweiss.
TIPP_STATT_VERSUCH = "Ich brauche einen Tipp."


def _verfasser(aufgabe, offene):
    """Beschriftung, Ziel und Knoepfe des einen Eingabebereichs.

    Seit dem Benchmark (19.10.2026, Aenderung 1 und 7) hat der Verfasser ein
    Feld und zwei Knoepfe: "Das ist mein Versuch" und "Ich habe eine Frage".
    Das Kind sagt selbst, was sein Beitrag ist; die Anwendung raet nicht
    mehr. Den Modus "ergaenzen" gibt es nur, solange keine Hilfe gegeben
    wurde, und nach "Nein, ich probier weiter" bleibt es beim Versuch: Sechs
    von sechzig Dialogen endeten vorher im Feld "Noch etwas dazu?", drei
    davon mit der fertigen Loesung im falschen Feld.
    """
    aufgabe_modus = {
        "modus": "aufgabe",
        "adresse": reverse("tutoring:aufgabe_stellen"),
        "beschriftung": "Deine Aufgabe",
        "hilfe": "",
        "platzhalter": "Abschreiben, fotografieren oder sprechen …",
        "knopf": "Abschicken",
        "zweiter": "",
    }
    if aufgabe is None:
        return aufgabe_modus
    letzte = aufgabe.letzte_hilfe
    if aufgabe.ist_abgeschlossen:
        if (letzte is not None and letzte.art == levels.ART_BESTAETIGUNG
                and not letzte.response):
            # Die Warum-Frage der Bestaetigung (Zech, S. 290-291). Antworten
            # ist freiwillig; die naechste Aufgabe steht daneben offen.
            return {
                "modus": "antwort",
                "adresse": reverse("tutoring:antwort_geben"),
                "beschriftung": "Deine Antwort, wenn du magst",
                "hilfe": "Du kannst antworten oder auf „Nächste Aufgabe“ tippen.",
                "platzhalter": "Weil …",
                "knopf": "Antworten",
                "zweiter": "",
            }
        return {**aufgabe_modus, "beschriftung": "Deine nächste Aufgabe"}
    if letzte is None:
        # Vor der ersten Hilfe (30.10.2026): Das Kind darf anfangen, und die
        # erste Hilfe richtet sich nach seinem Anfang. Vorher stand hier
        # "Noch etwas dazu?", und die erste Hilfe war immer Stufe 1.
        return {
            "modus": "antwort",
            "adresse": reverse("tutoring:antwort_geben"),
            "beschriftung": "Dein Anfang",
            "hilfe": (
                "Schreib, wie du anfangen würdest oder was du schon weißt. "
                "Du kannst auch gleich einen Tipp holen."
            ),
            "platzhalter": "Ich würde zuerst …",
            "knopf": levels.KNOPF_VERSUCH,
            "zweiter": levels.KNOPF_FRAGE,
        }
    if letzte.ist_hilfe and letzte.level >= levels.LOESUNG:
        return {
            "modus": "nachfrage",
            "adresse": reverse("tutoring:nachfrage_stellen"),
            "beschriftung": "Noch eine Frage?",
            "hilfe": "",
            "platzhalter": "Deine Frage …",
            "knopf": levels.KNOPF_FRAGE,
            "zweiter": "",
        }
    if offene is not None:
        # Die Frage steht auf der Karte der Hilfe oder Nachfrage; hier kein
        # zweiter fester Arbeitsauftrag mehr (Zech, S. 289: keine
        # Kettenfragen).
        return {
            "modus": "antwort",
            "adresse": reverse("tutoring:antwort_geben"),
            "beschriftung": "Jetzt bist du dran",
            "hilfe": "",
            "platzhalter": (
                "Erzähl, wie du gedacht hast …"
                if offene.art == levels.ART_NACHFRAGE
                else "Schreib, was du probiert hast. Auch „weiß nicht“ ist in Ordnung."
            ),
            "knopf": levels.KNOPF_VERSUCH,
            "zweiter": levels.KNOPF_FRAGE,
        }
    # Die letzte Hilfe ist beantwortet, und das Kind probiert weiter: nach
    # "Nein, ich probier weiter" vor der Loesung, oder nachdem die Stufen
    # aus sind. Der naechste Beitrag laeuft wieder durch die Diagnose.
    return {
        "modus": "antwort",
        "adresse": reverse("tutoring:antwort_geben"),
        "beschriftung": "Probier weiter",
        "hilfe": (
            "Das waren alle Tipps zu dieser Aufgabe. Du kannst weiter probieren "
            "oder etwas fragen."
            if aufgabe.stufen_ausgeschoepft else "Schreib deinen nächsten Versuch auf."
        ),
        "platzhalter": "Was hast du probiert?",
        "knopf": levels.KNOPF_VERSUCH,
        "zweiter": levels.KNOPF_FRAGE,
    }


def _letzter_absatz(text, hoechstens=140):
    """Der letzte Absatz eines Beitrags, fuer die Karte "Das stimmt."."""
    absaetze = [a.strip() for a in (text or "").split(NL) if a.strip()]
    letzter = absaetze[-1] if absaetze else ""
    if len(letzter) > hoechstens:
        letzter = letzter[:hoechstens - 1].rstrip() + "…"
    return letzter


def _gespraech_karten(aufgabe):
    """Das Gespraech als Karten in zeitlicher Folge.

    Hilfen und Antworten auf Fragen links, Beitraege des Kindes rechts. Die
    Hilfen tragen die Stufe als Marke; das Kind liest sie hinterher auf der
    Karte, nicht vorher auf dem Knopf.
    """
    karten = []
    for hilfe in aufgabe.hints.all():
        # Der Auftakt ist ein leerer Zug: Nur der Versuch des Kindes steht
        # da. Nachfrage, Bestaetigung und Nachsatz tragen ihre Art als
        # Karte, die Vorlage beschriftet sie anders als eine Stufe.
        if hilfe.art != levels.ART_AUFTAKT:
            karten.append((hilfe.created_at, 0, hilfe.pk, 0, {
                "art": "hilfe" if hilfe.ist_hilfe else hilfe.art, "hilfe": hilfe,
            }))
        if hilfe.response or hilfe.response_image_data_url:
            karten.append((hilfe.responded_at or hilfe.created_at, 1, hilfe.pk, 1, {
                "art": ("begruendung" if hilfe.art == levels.ART_BESTAETIGUNG
                        else "versuch"),
                "text": hilfe.response,
                "bild": hilfe.response_image_data_url, "hilfe": hilfe,
            }))
    for frage in aufgabe.questions.all():
        karten.append((frage.created_at, 0, frage.pk, 2, {"art": "frage", "frage": frage}))
        if frage.answer:
            karten.append((frage.created_at, 1, frage.pk, 3,
                           {"art": "antwort", "text": frage.answer}))
    # Zeit, dann Schluessel, dann Antwort nach Beitrag: wie in
    # _gespraechszeilen, damit eine Antwort aus derselben Mikrosekunde wie
    # der naechste Zug vor diesem steht.
    karten.sort(key=lambda eintrag: (eintrag[0], eintrag[2], eintrag[1], eintrag[3]))
    return [eintrag[4] for eintrag in karten]


def _umfang_titel(sitzung):
    """Der Titel der Einstellung, die die Lehrperson fuer die Stunde gewaehlt hat."""
    return levels.umfang_fuer(sitzung.max_level, sitzung.ask_before_solution)["titel"]


def _aufgabenwahl(teilnahme, aufgabe, abgeschlossen):
    """Die Aufgaben des Pools fuer die Kinderseite, mit erledigt und laufend."""
    sitzung = teilnahme.learning_session
    if not sitzung.ist_hilfe:
        return []
    vorlagen = list(sitzung.aufgabenpool.filter(aktiv=True))
    if not vorlagen:
        return []
    erledigt = set(
        teilnahme.tasks.filter(vorlage__isnull=False, finished_at__isnull=False)
        .values_list("vorlage_id", flat=True)
    )
    laufend = aufgabe.vorlage_id if aufgabe is not None and not abgeschlossen else None
    return [{"vorlage": v, "erledigt": v.pk in erledigt, "laufend": v.pk == laufend}
            for v in vorlagen]


def _chat_umgebung(teilnahme, aufgabe):
    sitzung = teilnahme.learning_session
    offene = aufgabe.offene_hilfe if aufgabe else None
    zug = aufgabe.naechster_zug() if aufgabe else None
    naechste = None
    if zug is not None and zug.ist_hilfe:
        naechste = zug.stufe
    elif zug is not None and zug.art == levels.ART_NACHFRAGE:
        naechste = levels.ERST_FRAGEN
    if offene is not None and offene.art == levels.ART_NACHFRAGE:
        # Waehrend eine Nachfrage auf die Antwort wartet, ist offen, welche
        # Hilfe danach kommt; kein Punkt des Weges ist "aktuell".
        naechste = None
    letzte = aufgabe.letzte_hilfe if aufgabe else None
    abgeschlossen = aufgabe is not None and aufgabe.ist_abgeschlossen
    # Die Karte "Das stimmt.": Die Diagnose hat das Ergebnis des Kindes als
    # richtig erkannt. Sie zeigt nur, was das Kind selbst geschrieben hat,
    # nie einen Text des Modells: Ein Modell, das sich irrt, duerfte sonst
    # hier die Loesung verraten.
    fertig_karte = None
    if abgeschlossen and letzte is not None and letzte.result == Hint.ERGEBNIS_RICHTIG:
        fertig_karte = {"text": _letzter_absatz(letzte.response)}
    return {
        "stufenliste": _stufenliste(sitzung, aufgabe, naechste),
        "erreichte_stufe": aufgabe.current_level if aufgabe else 0,
        "sitzung": sitzung,
        "teilnahme": teilnahme,
        "aufgabe": aufgabe,
        "gespraech": _gespraech_karten(aufgabe) if aufgabe else [],
        "naechste_stufe": naechste,
        "naechste_bezeichnung": levels.BEZEICHNUNGEN.get(naechste),
        # Welcher Zug als Naechstes kommt (hilfe, nachfrage, bestaetigung,
        # nachsatz oder leer): Die Seite holt eine faellige Bestaetigung von
        # selbst, und der Tippknopf weiss, ob eine Frage statt einer Hilfe
        # kommt.
        "zug_art": zug.art if zug else "",
        "hilfeknopf": levels.HILFEKNOPF,
        "obergrenze_erreicht": aufgabe is not None and not abgeschlossen and zug is None,
        "abgeschlossen": abgeschlossen,
        "fertig_karte": fertig_karte,
        # Der Aufgabenpool der Lehrperson (1.11.2026): zur Wahl, sobald keine
        # Aufgabe laeuft; erledigte sind markiert.
        "pool": _aufgabenwahl(teilnahme, aufgabe, abgeschlossen),
        "pool_offen": aufgabe is None or abgeschlossen,
        # Die Notenleiste (1.11.2026): sichtbar, sobald die Aufgabe
        # abgeschlossen ist; hilfe.js zeigt sie auch ohne Neuladen, wenn das
        # Ergebnis gerade als richtig erkannt wurde.
        "note_offen": aufgabe is not None and abgeschlossen and not aufgabe.rating,
        # Wie vielte Aufgabe ist das? Das Kind soll sehen, dass die vorige
        # nicht verschwunden ist, sondern abgehakt.
        "aufgabennummer": (
            teilnahme.tasks.filter(created_at__lte=aufgabe.created_at).count()
            if aufgabe else 0
        ),
        "offene_hilfe": offene,
        # Der Tippknopf steht, solange die Aufgabe laeuft und noch eine Stufe
        # kommen kann. Wartet eine Hilfe auf den Versuch, steht er trotzdem:
        # Wer ihn dann drueckt, sagt damit "ich brauche einen Tipp", und das
        # wird als Beitrag festgehalten statt mit einem Fehler abgewiesen.
        "tipp_moeglich": (
            aufgabe is not None and not abgeschlossen
            and (naechste is not None or offene is not None)
        ),
        "sprache_moeglich": sprache_moeglich(),
        "loesung_steht_an": aufgabe.loesung_steht_an if aufgabe else False,
        "stufen_ausgeschoepft": aufgabe.stufen_ausgeschoepft if aufgabe else False,
        "loesung_gezeigt": letzte is not None and letzte.level >= levels.LOESUNG,
        "nachfragen": list(aufgabe.questions.all()) if aufgabe else [],
        "verfasser": _verfasser(aufgabe, offene),
        "schulstufe": sitzung.schulstufe,
        "knopf_versuch": levels.KNOPF_VERSUCH,
        "knopf_frage": levels.KNOPF_FRAGE,
    }


@require_POST
def aufgabe_stellen(request):
    """Nimmt eine getippte Aufgabe entgegen und legt sie an."""
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or not teilnahme.hat_tier:
        return redirect("tutoring:chat")

    text = (request.POST.get("text") or "").strip()[:MAX_AUFGABENLAENGE]
    if not text:
        umgebung = _chat_umgebung(teilnahme, teilnahme.tasks.last())
        umgebung["fehler"] = "Schreib zuerst deine Aufgabe auf."
        return render(request, "tutoring/chat.html", umgebung)

    # Eine noch offene Aufgabe gilt mit der naechsten als erledigt. Sonst
    # stuende in der Lehreransicht ein Dutzend Aufgaben ohne Ende.
    laufende = teilnahme.tasks.last()
    if laufende is not None and not laufende.ist_abgeschlossen:
        laufende.abschliessen()

    foto = _foto_aus(request)
    stufe, grund = pruefung.einstufen(text)
    Task.objects.create(
        participation=teilnahme, text=text, image_data_url=foto,
        source=_herkunft_aus(request, foto), flag=stufe, flag_reason=grund,
    )
    teilnahme.einstufung_merken(stufe)
    sitzung.beruehren()
    return redirect("tutoring:chat")


@require_POST
def aufgabe_waehlen(request):
    """Das Kind nimmt eine Aufgabe aus dem Pool der Lehrperson (1.11.2026).

    Wie aufgabe_stellen, nur kommen Text und Foto aus der Vorlage, die
    Herkunft ist die Lehrperson, und die gepruefte Loesung der Vorpruefung
    geht still mit, damit die Qualitaetssicherung nicht je Kind noch
    einmal laeuft.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")
    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen or not teilnahme.hat_tier:
        return redirect("tutoring:chat")
    schluessel = (request.POST.get("vorlage") or "").strip()
    vorlage = (sitzung.aufgabenpool.filter(pk=int(schluessel), aktiv=True).first()
               if schluessel.isdigit() else None)
    if vorlage is None:
        return redirect("tutoring:chat")
    laufende = teilnahme.tasks.last()
    if laufende is not None and not laufende.ist_abgeschlossen:
        laufende.abschliessen()
    Task.objects.create(
        participation=teilnahme, text=vorlage.text, image_data_url=vorlage.image_data_url,
        source=VORGEGEBEN, flag=pruefung.GRUEN, vorlage=vorlage,
        **aufgabenpool.geprueftes_fuer_task(vorlage),
    )
    teilnahme.einstufung_merken(pruefung.GRUEN)
    sitzung.beruehren()
    return redirect("tutoring:chat")


@require_POST
def aufgabe_abschliessen(request):
    """Das Kind sagt, dass es mit dieser Aufgabe fertig ist.

    Ohne diesen Schritt laeuft eine Aufgabe, bis die Stufen aus sind. Wer die
    Loesung nach Stufe 2 selbst gefunden hat, kann das dann nirgends sagen,
    und die naechste Aufgabe schiebt die alte kommentarlos aus dem Bild.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    aufgabe = teilnahme.tasks.last()
    if aufgabe is not None:
        aufgabe.abschliessen()
        # Eine Note darf mit dem Fertigmelden kommen (Thomas, 1.11.2026).
        aufgabe.benoten(request.POST.get("note"))
        teilnahme.learning_session.beruehren()
    return redirect("tutoring:chat")


@require_POST
def aufgabe_benoten(request):
    """Die Note des Kindes fuer die Hilfe, 1 bis 5 (Thomas, 1.11.2026).

    Freiwillig und nur fuer eine eigene, abgeschlossene Aufgabe: die
    letzte, oder die mit dem mitgeschickten Schluessel. Ohne gueltige Note
    passiert nichts. Antwortet als JSON, wenn die Seite es per Skript
    schickt (X-Antwort: json), sonst mit dem Weg zurueck auf die Seite.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")
    aufgabe = teilnahme.tasks.last()
    schluessel = (request.POST.get("aufgabe") or "").strip()
    if schluessel.isdigit():
        aufgabe = teilnahme.tasks.filter(pk=int(schluessel)).first() or aufgabe
    gespeichert = False
    if aufgabe is not None and aufgabe.ist_abgeschlossen:
        gespeichert = aufgabe.benoten(request.POST.get("note"))
        if gespeichert:
            teilnahme.learning_session.beruehren()
    if request.headers.get("X-Antwort") == "json":
        return JsonResponse({"ok": gespeichert,
                             "note": aufgabe.rating if aufgabe is not None else None})
    return redirect("tutoring:chat")


@require_POST
def bild_erkennen(request):
    """Nimmt ein Foto entgegen und gibt den abgelesenen Text zurueck.

    Das Bild wird einmal gelesen, danach arbeitet die Anwendung mit Text
    weiter. Ein Foto bei jeder Hilfestufe mitzuschicken kostet rund 1.900
    Token und acht Sekunden je Anfrage; der abgeschriebene Text kostet fast
    nichts. Ausserdem kann das Kind den erkannten Text noch berichtigen,
    bevor es ihn abschickt.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    data_url = (request.POST.get("bild") or "").strip()
    if not data_url.startswith("data:image/"):
        return JsonResponse(
            {"ok": False, "meldung": "Das war kein Bild."}, status=400
        )

    try:
        text, verbrauch = text_aus_bild(data_url)
    except SparkNichtErreichbar as fehler:
        return JsonResponse({"ok": False, "meldung": fehler.meldung}, status=503)

    sitzung = teilnahme.learning_session
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=settings.SPARK_MODEL,
        tokens_ein=verbrauch.get("prompt_tokens", 0),
        tokens_aus=verbrauch.get("completion_tokens", 0),
        ergebnis="ok" if text else "kein_text",
        text_ein="[Foto]", text_aus=text,
    )

    if not text:
        return JsonResponse({"ok": False, "meldung": MELDUNG_BILD_UNKLAR}, status=200)
    return JsonResponse({"ok": True, "text": text})


@require_POST
def sprache_erkennen(request):
    """Nimmt eine Aufnahme entgegen und gibt den gesprochenen Text zurueck."""
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    aufnahme = request.FILES.get("aufnahme")
    if aufnahme is None:
        return JsonResponse(
            {"ok": False, "meldung": "Es ist keine Aufnahme angekommen."}, status=400
        )

    # Beim Sprechcoach bestimmt Whisper die Sprache SELBST. Der Coach muss
    # wissen, ob ein Kind englisch gesprochen hat, und das kann er nicht
    # erfahren, wenn er Whisper vorher sagt, es sei Englisch: Dann wird ein
    # deutscher Satz zu englischer Lautmalerei, und der Text sieht englisch
    # aus, ohne es zu sein. Ueberall sonst bleibt Deutsch erzwungen - aus
    # demselben Satz von hinten.
    sitzung = teilnahme.learning_session
    sprache = None if sitzung.ist_sprechcoach else "de"

    try:
        text, erkannt = text_und_sprache(
            aufnahme.read(), aufnahme.name or "aufnahme.wav", sprache
        )
    except SparkNichtErreichbar as fehler:
        return JsonResponse({"ok": False, "meldung": fehler.meldung}, status=503)

    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=settings.SPARK_AUDIO_MODEL,
        ergebnis="ok" if text else "kein_text",
        text_ein="[Aufnahme]", text_aus=text,
    )

    if not text:
        return JsonResponse(
            {"ok": False, "meldung": MELDUNG_NICHTS_VERSTANDEN}, status=200
        )
    # "erkannt" reicht der Browser beim Absenden des Beitrags zurueck. Die
    # Sperre im Coach-Zug entscheidet damit und nicht hier: Hier wird nur
    # gehoert, dort wird geantwortet.
    return JsonResponse({"ok": True, "text": text, "erkannt": erkannt})


def _foto_aus(request):
    """Die Data-URL aus dem Formular, wenn es wirklich ein Bild ist."""
    roh = (request.POST.get("bild") or "").strip()
    return roh if roh.startswith("data:image/") else ""


def _herkunft_aus(request, foto):
    """Wie ist die Eingabe zustande gekommen?

    Das Skript meldet es mit. Ein Foto schlaegt die Meldung, denn wer
    fotografiert und den erkannten Text danach berichtigt, hat trotzdem
    fotografiert.
    """
    if foto:
        return FOTOGRAFIERT
    gemeldet = (request.POST.get("herkunft") or "").strip()
    return gemeldet if gemeldet in dict(HERKUNFT) else GETIPPT


@require_POST
def aufgabe_ergaenzen(request):
    """Haengt etwas an die laufende Aufgabe an.

    Wer seine Aufgabe eingesprochen hat, will oft noch etwas dazusagen,
    bevor die erste Hilfe kommt. Ohne diesen Weg bliebe nur, sofort einen
    Tipp zu holen oder eine neue Aufgabe zu beginnen.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    aufgabe = teilnahme.tasks.last()
    if not sitzung.ist_offen or aufgabe is None:
        return redirect("tutoring:chat")
    # Nur, solange noch keine Hilfe gegeben wurde. Danach ist jeder Beitrag
    # ein Versuch oder eine Frage; eine Ergaenzung der Angabe, die die
    # Hilfen schon gelesen haben, waere ein Beitrag, der nirgends ankommt
    # (Benchmark 19.10.2026, Aenderung 7).
    if aufgabe.ist_abgeschlossen or aufgabe.hints.exists():
        return redirect("tutoring:chat")

    text = (request.POST.get("text") or "").strip()[:MAX_AUFGABENLAENGE]
    foto = _foto_aus(request)
    if not text and not foto:
        return redirect("tutoring:chat")

    stufe, grund = pruefung.einstufen(text)
    felder = ["text", "flag", "flag_reason"]
    if text:
        aufgabe.text = (aufgabe.text + NL + text).strip()
    if foto and not aufgabe.image_data_url:
        aufgabe.image_data_url = foto
        aufgabe.source = FOTOGRAFIERT
        felder += ["image_data_url", "source"]
    aufgabe.flag = pruefung.schlimmeres(aufgabe.flag, stufe)
    if grund:
        aufgabe.flag_reason = grund
    aufgabe.save(update_fields=felder)
    teilnahme.einstufung_merken(stufe)
    sitzung.beruehren()
    return redirect("tutoring:chat")


def _gespraechszeilen(aufgabe):
    """Das bisherige Gespraech als Zeilen, in zeitlicher Folge.

    Hilfen, die Antworten des Kindes, seine Rueckfragen und die Antworten
    darauf, so wie sie gefallen sind. Dieselben Zeilen bekommen die Diagnose
    und der Hilfeprompt: Die Diagnose soll aus dem GANZEN Gespraech
    schliessen, und die Hilfe soll eine Rueckfrage des Kindes kennen, wenn
    sie darauf antwortet. Vorher sah der Hilfeprompt die Rueckfragen nicht
    (Benchmark 19.10.2026, Abschnitt 2.1).

    Gibt (zeilen, eigenes) zurueck: ``eigenes`` ist alles, was das Kind
    selbst geschrieben hat, und nur das ist fuer die Ausgangspruefung ein
    Freibrief. Wuerde man den ganzen Verlauf nehmen, waere eine Zahl, die
    einmal durchgerutscht ist, ab da fuer immer erlaubt.
    """
    eintraege = []
    eigenes = [aufgabe.text]
    for hilfe in aufgabe.hints.order_by("created_at", "pk"):
        zeile = _zugzeile(hilfe)
        if zeile:
            eintraege.append((hilfe.created_at, 0, hilfe.pk, 0, zeile))
        if hilfe.response:
            wer = ("Das Kind hat zuerst, ohne Hilfe, geschrieben"
                   if hilfe.art == levels.ART_AUFTAKT
                   else "Darauf hat das Kind geantwortet")
            eintraege.append((hilfe.responded_at or hilfe.created_at, 1, hilfe.pk, 1,
                              f"{wer}: {hilfe.response}"))
            eigenes.append(hilfe.response)
    for frage in aufgabe.questions.order_by("created_at", "pk"):
        eintraege.append((frage.created_at, 0, frage.pk, 2,
                          f"Rückfrage des Kindes: {frage.text}"))
        eigenes.append(frage.text)
        if frage.answer:
            eintraege.append((frage.created_at, 1, frage.pk, 3,
                              f"Antwort darauf: {frage.answer}"))
    # Zeit, dann Schluessel, dann Antwort nach Beitrag: Zwei Zuege aus
    # derselben Mikrosekunde (Windows-Uhr, Tests) bleiben in der Reihenfolge
    # des Anlegens, und die Antwort auf den aelteren Zug steht vor dem
    # juengeren Zug, nicht dahinter.
    eintraege.sort(key=lambda eintrag: (eintrag[0], eintrag[2], eintrag[1], eintrag[3]))
    return [eintrag[4] for eintrag in eintraege], eigenes


def _zugzeile(hilfe):
    """Ein Zug des Tutors als Zeile des Verlaufs; leer fuer den Auftakt."""
    if hilfe.art == levels.ART_AUFTAKT:
        return ""
    if hilfe.art == levels.ART_NACHFRAGE:
        return f"Nachfrage des Tutors (noch keine Hilfe): {hilfe.text}"
    if hilfe.art == levels.ART_BESTAETIGUNG:
        return f"Bestätigung mit Warum-Frage: {hilfe.text}"
    if hilfe.art == levels.ART_NACHSATZ:
        return f"Antwort des Tutors auf die Begründung: {hilfe.text}"
    return f"Hilfe der Stufe {hilfe.level}: {hilfe.text}"


def _gespraech_bisher(aufgabe):
    """Die bisherigen Hilfen, Antworten und Rueckfragen, fuer die Diagnose."""
    return NL.join(_gespraechszeilen(aufgabe)[0])


def _antwort_abgelehnt(request, teilnahme, aufgabe, per_skript, meldung):
    """Ein Beitrag, der nicht angenommen werden kann: als JSON oder als Seite."""
    if per_skript:
        return JsonResponse({"ok": False, "meldung": meldung}, status=400)
    umgebung = _chat_umgebung(teilnahme, aufgabe)
    umgebung["fehler"] = meldung
    return render(request, "tutoring/chat.html", umgebung)


@require_POST
def antwort_geben(request):
    """Nimmt entgegen, was das Kind nach einer Hilfe geschrieben hat.

    Das Kind sagt mit dem Knopf, was es ist: ein Versuch oder eine Frage
    (Feld ``absicht``). Fehlt die Angabe, gilt der Beitrag als Versuch;
    aeltere Seiten kennen den zweiten Knopf nicht. Vorher riet die Anwendung
    mit levels.enthaelt_frage, und die Antwort auf "Was soll man hier
    herausfinden?" ("wie viele Murmeln Lena jetzt hat") galt als Frage: 245
    von 363 Beitraegen, 35 von 60 Dialogen acht Zuege lang auf Stufe 1
    (Benchmark 19.10.2026, Befund 1). Ein Versuch mit angehaengter Frage
    ("12? ist das richtig?") ist ein Versuch; die Frage steht im Verlauf und
    damit im Hilfeprompt.

    Eine Frage wird auf derselben Stufe beantwortet, die Hilfe wartet weiter
    auf einen Versuch. Ein Versuch laeuft durch die Diagnose: Ergebnis,
    Fehler, naechste Stufe und Ampel in einem Aufruf. Ist das Ergebnis
    richtig, ist die Aufgabe fertig, und die Seite zeigt "Das stimmt." statt
    einer weiteren Hilfe.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return redirect("tutoring:chat")

    # Das Skript schickt den Versuch und holt gleich danach die naechste
    # Stufe. Ohne diesen Weg muesste das Kind nach dem Abschicken noch einmal
    # auf einen Knopf druecken, obwohl es gerade sein Ergebnis gemeldet hat.
    per_skript = request.headers.get("X-Antwort") == "json"

    aufgabe = teilnahme.tasks.last()
    if aufgabe is None:
        return _antwort_abgelehnt(
            request, teilnahme, aufgabe, per_skript, "Schreib zuerst deine Aufgabe auf."
        )

    absicht = (request.POST.get("absicht") or levels.ABSICHT_VERSUCH).strip().lower()
    if absicht not in (levels.ABSICHT_VERSUCH, levels.ABSICHT_FRAGE):
        absicht = levels.ABSICHT_VERSUCH

    text = (request.POST.get("antwort") or request.POST.get("text")
            or "").strip()[:MAX_AUFGABENLAENGE]
    if not text:
        return _antwort_abgelehnt(
            request, teilnahme, aufgabe, per_skript,
            "Schreib deine Frage auf." if absicht == levels.ABSICHT_FRAGE
            else "Schreib kurz auf, was du probiert oder herausgefunden hast.",
        )
    foto = _foto_aus(request)

    if aufgabe.ist_abgeschlossen:
        # Nach dem Ende gibt es genau einen Beitrag, der kein Versuch mehr
        # ist: die Antwort auf die Warum-Frage der Bestaetigung (Zech, S.
        # 290-291). Sie ist freiwillig, wird nicht diagnostiziert und
        # bekommt einen Nachsatz. Alles andere ist eine neue Aufgabe.
        letzte = aufgabe.letzte_hilfe
        if (absicht == levels.ABSICHT_VERSUCH and letzte is not None
                and letzte.art == levels.ART_BESTAETIGUNG and not letzte.response):
            stufe, grund = pruefung.einstufen(text)
            letzte.response = text
            letzte.response_image_data_url = foto
            letzte.response_source = _herkunft_aus(request, foto)
            letzte.responded_at = timezone.now()
            letzte.response_flag = stufe
            letzte.response_flag_reason = grund
            letzte.save(update_fields=[
                "response", "response_image_data_url", "response_source",
                "responded_at", "response_flag", "response_flag_reason",
            ])
            teilnahme.einstufung_merken(stufe)
            sitzung.beruehren()
            if per_skript:
                return JsonResponse({"ok": True, "fertig": True, "nachsatz": True})
            return redirect("tutoring:chat")
        if absicht == levels.ABSICHT_VERSUCH:
            return _antwort_abgelehnt(
                request, teilnahme, aufgabe, per_skript,
                "Diese Aufgabe ist fertig. Schreib deine nächste Aufgabe auf.",
            )

    if absicht == levels.ABSICHT_FRAGE:
        # Eine Frage ist kein Versuch. Das Kind hat es gesagt, nicht die
        # Anwendung geraten. Die Ampel kommt hier weiter von der Einstufung:
        # Fuer eine Frage laeuft keine Diagnose, aber der Pfoertner
        # (fachgrenze, 7.11.2026).
        frage = _frage_anlegen(request, sitzung, teilnahme, aufgabe, text, foto)
        if per_skript:
            return JsonResponse({"ok": True, "frage": frage.pk})
        return redirect("tutoring:chat")

    # Ein Versuch haengt an dem Zug des Tutors, auf den er antwortet: an dem
    # offenen (Hilfe oder Nachfrage), oder, nach "Nein, ich probier weiter"
    # und nach ausgeschoepften Stufen, an dem letzten. Vor dem ersten Zug
    # gibt es den Auftakt (30.10.2026): Das Kind darf anfangen, bevor es
    # eine Hilfe gab, und die erste Hilfe richtet sich nach diesem Versuch
    # statt immer Stufe 1 zu sein. Der Auftakt ist ein leerer Zug, damit der
    # Versuch dort haengt, wo alle anderen haengen.
    offene = aufgabe.offene_hilfe
    ziel = offene or aufgabe.letzte_hilfe
    if ziel is None:
        ziel = Hint.objects.create(
            task=aufgabe, level=0, text="", art=levels.ART_AUFTAKT,
        )
        offene = ziel
    if ziel.ist_hilfe and ziel.level >= levels.LOESUNG:
        return _antwort_abgelehnt(
            request, teilnahme, aufgabe, per_skript,
            "Die Lösung ist schon da. Du kannst noch etwas dazu fragen.",
        )

    # Hilfe nach Diagnose statt nach Leiter: Die Pruefung sagt, wo das Kind
    # steht, was es will und welche Hilfe es als Naechstes braucht - aus
    # dem ganzen Gespraech, nicht nur aus diesem Beitrag. Erst nachfragen,
    # dieselbe Hilfe enger, eine tiefere oder eine staerkere; die Regeln
    # darueber stehen in levels.hilfe_waehlen, der Zaehler in
    # Task.naechster_zug. Dazu: ob das Ergebnis richtig ist, welcher Fehler
    # es war, und die Ampel, alles aus einem Aufruf.
    zuege = list(aufgabe.hints.all())
    hilfen = [z for z in zuege if z.ist_hilfe]
    stand = hilfen[-1].level if hilfen else 0
    letzter_hilfetext = hilfen[-1].text if hilfen else ""
    frage_der_hilfe = levels.letzte_frage(
        ziel.text if ziel.art == levels.ART_NACHFRAGE else letzter_hilfetext
    )
    # Die Fachgrenze (7.11.2026) auch auf dem Versuchsweg: Neben der Diagnose
    # urteilt der Pfoertner, ob der Beitrag zur Stunde gehoert. Eine Rechnung
    # oder eine Zahl gehoert immer dazu, ohne Aufruf (fachgrenze.ohne_pruefung);
    # fuer alles andere laufen Diagnose und Pfoertner gleichzeitig, damit der
    # Versuch nicht laenger wartet. Keiner der beiden fasst die Datenbank an.
    gespraech_bisher = _gespraech_bisher(aufgabe)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        diagnose_laeuft = pool.submit(
            pruefung.diagnose,
            stand, aufgabe.text, text, gespraech_bisher,
            obergrenze=aufgabe.obergrenze, schulstufe=sitzung.schulstufe,
            altersklasse=sitzung.age_group, loesung=aufgabe.checked_solution,
            frage_der_hilfe=frage_der_hilfe,
            hilfen_bisher=len(hilfen),
            fehler_vorher=sum(1 for z in zuege if z.result == Hint.ERGEBNIS_FALSCH),
            nachfragen_bisher=sum(1 for z in zuege if z.art == levels.ART_NACHFRAGE),
            letzte_war_nachfrage=ziel.art == levels.ART_NACHFRAGE,
        )
        pfoertner_laeuft = pool.submit(
            fachgrenze.pruefen, text, sitzung.subject or "mathematik",
            thema=sitzung.task_hint, aufgabe=aufgabe.text,
            altersklasse=sitzung.age_group,
        )
        befund = diagnose_laeuft.result()
        urteil = pfoertner_laeuft.result()
    fachgrenze.aufzeichnen(sitzung, teilnahme, urteil, text)
    if urteil.fremd:
        # Der Beitrag gehoert nicht zur Stunde. Er bleibt als Beitrag stehen
        # (die Lehrperson sieht ihn gelb mit dem festen Grund), zaehlt aber
        # nicht als Versuch: kein Ergebnis, kein Fehler, keine Stufe. Der
        # naechste Zug ist die Nachfrage mit dem festen Satz des Fachs; kein
        # Modell formuliert sie (_hilfe_erzeugen). Lage und Absicht der
        # Diagnose bleiben fuer das Protokoll erhalten.
        ampel, ampel_grund = fachgrenze.ampel_mit_grenze(befund.ampel, befund.ampel_grund, urteil)
        befund = dataclasses.replace(
            befund, stufe=levels.ERST_FRAGEN, grund=fachgrenze.GRUND,
            ergebnis=pruefung.OFFEN, fehler="", ampel=ampel, ampel_grund=ampel_grund,
            form="",
        )
    if offene is None:
        # Ein weiterer Versuch zur selben Hilfe. Angehaengt, nicht
        # ueberschrieben: Die Lehrperson soll beide sehen.
        ziel.response = (ziel.response + NL + NL + text).strip()
    else:
        ziel.response = text
    if foto:
        ziel.response_image_data_url = foto
    ziel.response_source = _herkunft_aus(request, foto)
    ziel.responded_at = timezone.now()
    ziel.response_flag = befund.ampel
    ziel.response_flag_reason = befund.ampel_grund
    ziel.next_level = befund.stufe
    ziel.goal_reached = befund.stufe > stand
    ziel.goal_note = befund.grund
    ziel.result = befund.ergebnis
    ziel.error = befund.fehler
    ziel.lage = befund.lage
    ziel.absicht = befund.absicht
    ziel.next_form = befund.form
    ziel.save(update_fields=[
        "response", "response_image_data_url", "response_source",
        "responded_at", "response_flag", "response_flag_reason",
        "goal_reached", "goal_note", "next_level", "result", "error",
        "lage", "absicht", "next_form",
    ])
    if befund.fertig:
        # Das Ergebnis stimmt. Die Aufgabe ist fertig, ohne dass das Kind
        # "Ich bin fertig" druecken oder die Loesung ansehen muss (Befund 2:
        # drei Loesungen vorgerechnet, obwohl das Kind sie hatte).
        aufgabe.abschliessen()
    teilnahme.einstufung_merken(befund.ampel)
    sitzung.beruehren()
    if per_skript:
        return JsonResponse({
            "ok": True, "ergebnis": befund.ergebnis, "fertig": befund.fertig,
            **({"fachgrenze": True} if urteil.fremd else {}),
        })
    return redirect("tutoring:chat")


def _frage_anlegen(request, sitzung, teilnahme, aufgabe, text, foto):
    """Legt eine Rueckfrage an: Ampel und Pfoertner gleichzeitig.

    Die Fachgrenze (7.11.2026): Sagt der Pfoertner nein, traegt die Frage gelb
    mit dem festen Grund, und _nachfrage_erzeugen antwortet mit dem Satz der
    Anwendung statt mit dem Modell. Der Pfoertner selbst ist ein Modellaufruf
    und bekommt seine Zeile im Forschungsprotokoll.
    """
    (stufe, grund), urteil = fachgrenze.ampel_und_urteil(
        text, sitzung.subject or "mathematik", thema=sitzung.task_hint,
        aufgabe=aufgabe.text, altersklasse=sitzung.age_group,
    )
    stufe, grund = fachgrenze.ampel_mit_grenze(stufe, grund, urteil)
    frage = Question.objects.create(
        task=aufgabe, text=text, image_data_url=foto,
        source=_herkunft_aus(request, foto), flag=stufe, flag_reason=grund,
    )
    teilnahme.einstufung_merken(stufe)
    if urteil.modell_gefragt:
        Interaction.aufzeichnen(
            sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
            modell=urteil.messung.get("modell", ""),
            tokens_ein=urteil.messung.get("tokens_ein", 0),
            tokens_aus=urteil.messung.get("tokens_aus", 0),
            dauer_ms=urteil.messung.get("dauer_ms", 0),
            leak_check=Interaction.ENTFAELLT,
            ergebnis=f"pfoertner:{urteil.zur_stunde}",
            fehlerart=urteil.messung.get("fehlerart", ""),
            text_ein=text, text_aus=urteil.grund,
        )
    sitzung.beruehren()
    return frage


@require_POST
def nachfrage_stellen(request):
    """Nimmt eine freie Rueckfrage entgegen - auf jeder Stufe.

    Frueher nur, nachdem die Stufen aus waren. Das hatte eine Folge, die
    niemand wollte: Ein Kind, das mitten in der Leiter etwas fragen wollte,
    hatte dafuer keinen Weg ausser dem Versuchsfeld - und dort zaehlte die
    Frage als Versuch und rueckte die Stufe vor. Jetzt ist eine Frage
    jederzeit eine Frage, und die Antwort ist an die laufende Stufe gebunden.
    """
    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "meldung": "Keine Sitzung."}, status=403)

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return JsonResponse(
            {"ok": False, "meldung": "Die Sitzung ist beendet."}, status=400
        )

    aufgabe = teilnahme.tasks.last()
    if aufgabe is None:
        return JsonResponse(
            {"ok": False, "meldung": "Stell zuerst eine Aufgabe."}, status=400
        )

    text = (request.POST.get("frage") or request.POST.get("text")
            or "").strip()[:MAX_AUFGABENLAENGE]
    if not text:
        return JsonResponse(
            {"ok": False, "meldung": "Schreib deine Frage bitte auf."}, status=400
        )

    foto = _foto_aus(request)
    frage = _frage_anlegen(request, sitzung, teilnahme, aufgabe, text, foto)
    return JsonResponse({"ok": True, "id": frage.pk})


async def nachfrage_beantworten(request, frage_id):
    """Beantwortet eine Rueckfrage, gebunden an dieselbe Obergrenze."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    teilnahme = await sync_to_async(_teilnahme_holen)(request)
    if teilnahme is None:
        return HttpResponseForbidden("Keine Sitzung.")

    daten = await _nachfrage_holen(frage_id, teilnahme.pk)
    if daten is None:
        raise Http404
    frage, sitzung, gespraech, eigenes, grenze, unterwegs, rueckfrage = daten

    if not sitzung.ist_offen:
        return _fehlerstrom("Die Sitzung ist beendet.")

    antwort = StreamingHttpResponse(
        _nachfrage_erzeugen(frage, sitzung, teilnahme, gespraech, eigenes,
                            grenze, unterwegs, rueckfrage),
        content_type="text/event-stream",
    )
    antwort["Cache-Control"] = "no-cache"
    antwort["X-Accel-Buffering"] = "no"
    return antwort


async def _nachfrage_erzeugen(frage, sitzung, teilnahme, gespraech, eigenes=None,
                              grenze=None, unterwegs=False, rueckfrage=""):
    """Antwortet auf eine Rueckfrage, ohne die Grenze zu ueberschreiten.

    Die Antwort laeuft durch dieselbe Ausgangspruefung wie eine Hilfe, mit
    der Grenze als Stufe - mitten in der Leiter die Stufe, auf der das Kind
    gerade steht, danach die Obergrenze der Sitzung. Das ist der Punkt, an
    dem die Konstruktion sonst auseinanderfaellt: Im Browsertest hat die
    Rueckfrage in einer Sitzung mit "nur Tipps" geantwortet "Die Antwort ist
    48" und danach den Rechenweg vorgerechnet. Die Stufen hielten dicht, die
    Rueckfrage nicht - und eine Grenze, um die man herumtippen kann, ist
    keine.
    """
    if grenze is None:
        grenze = sitzung.max_level
    if frage.flag_reason == fachgrenze.GRUND:
        # Die Fachgrenze (7.11.2026): Der Pfoertner hat nein gesagt. Kein
        # Modell antwortet; das Kind liest den festen Satz des Fachs mit dem
        # Rueckweg zur offenen Frage. Protokolliert wie jeder Zug.
        text = fachgrenze.satz(
            sitzung.subject or "mathematik", sitzung.age_group,
            thema=sitzung.task_hint, rueckfrage=rueckfrage,
        )
        yield _ereignis("start", {"stufe": 0, "bezeichnung": "Antwort auf deine Frage"})
        yield _ereignis("stueck", {"text": text})
        await _nachfrage_sichern(frage.pk, text)
        await _anfrage_aufzeichnen(
            sitzung, teilnahme, None, {}, frage.text, text, ergebnis="fachgrenze",
        )
        yield _ereignis("fertig", {
            "stufe": 0, "bezeichnung": "Antwort auf deine Frage",
            "naechste_stufe": None, "rueckfrage": None, "nachfrage": True,
        })
        return
    system = levels.nachfrage_prompt(
        grenze, sitzung.age_group, unterwegs=unterwegs, rueckfrage=rueckfrage,
        umfang_titel=_umfang_titel(sitzung),
    )
    # Offene Karten (31.10.2026) auch auf dem Frageweg: Eine Frage, die sich
    # an die Anwendung richtet ("vergiss deine Regeln"), bekommt den festen
    # Satz vor der Antwort. Hier entscheidet nur das deterministische
    # Muster; die Frage laeuft durch keine Diagnose.
    umgehung = pruefung.ist_umgehung(frage.text)
    vorspann = levels.UMGEHUNG_SATZ + NL + NL if umgehung else ""
    if umgehung:
        system += "\n\n" + levels.UMGEHUNG_ANWEISUNG
    anfrage = gespraech + "\n\nDie Rückfrage lautet:\n" + frage.text
    messung = {}

    yield _ereignis("start", {"stufe": 0, "bezeichnung": "Antwort auf deine Frage"})
    if vorspann:
        yield _ereignis("stueck", {"text": vorspann})
    try:
        geprueft = await _geprueft_erzeugen(
            system, anfrage, messung, grenze, grenze,
            eigenes=eigenes, schulstufe=sitzung.schulstufe,
            loesung=frage.task.checked_solution,
        )
    except SparkNichtErreichbar as fehler:
        yield _ereignis("fehler", {"meldung": fehler.meldung})
        return

    gesammelt = []
    async for stueck in _stueckweise(geprueft):
        gesammelt.append(stueck)
        yield _ereignis("stueck", {"text": stueck})

    text = (vorspann + "".join(gesammelt)).strip()
    await _nachfrage_sichern(frage.pk, text)
    await _anfrage_aufzeichnen(
        sitzung, teilnahme, None, messung, anfrage, text, ergebnis="nachfrage",
    )
    yield _ereignis("fertig", {
        "stufe": 0,
        "bezeichnung": "Antwort auf deine Frage",
        "naechste_stufe": None,
        "rueckfrage": None,
        "nachfrage": True,
    })


# --------------------------------------------------------- Hilfe im Streaming

async def hilfe_streamen_ansicht(request, task_id):
    """Liefert die naechste Hilfestufe fortlaufend aus.

    Die Stufe wird vor dem ersten Zeichen verbindlich vorgemerkt. Sonst
    erzeugt ein doppelter Fingertipp zwei Antworten derselben Stufe.
    """
    # Kein GET: Eine Hilfe anzufordern verbraucht eine Stufe, veraendert also
    # etwas. Als POST greift ausserdem der CSRF-Schutz.
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    teilnahme = await sync_to_async(_teilnahme_holen)(request)
    if teilnahme is None:
        return HttpResponseForbidden("Keine Sitzung.")

    daten = await _aufgabe_holen(task_id, teilnahme.pk)
    if daten is None:
        raise Http404

    if not daten["sitzung"].ist_offen:
        return _fehlerstrom("Die Sitzung ist beendet.")

    beitrag = None
    if daten["wartet"]:
        # Der Tippknopf, waehrend eine Hilfe auf den Versuch wartet: Das IST
        # die Antwort des Kindes, und sie ist ehrlich. Sie wird als Beitrag
        # festgehalten (kein Versuch, die Stufe bleibt), und dann geht es
        # weiter wie nach jedem Beitrag. Vorher stand hier eine
        # Fehlermeldung, und das Kind sass vor einem Knopf, der nichts tat.
        await _tipp_vermerken(daten["offene_id"])
        beitrag = TIPP_STATT_VERSUCH
        daten = await _aufgabe_holen(task_id, teilnahme.pk)
        if daten is None:
            raise Http404

    aufgabe = daten["aufgabe"]
    sitzung = daten["sitzung"]
    zug = daten["zug"]
    wiederholung = daten["wiederholung"]

    if zug is None:
        if aufgabe.ist_abgeschlossen:
            # Fertig und bestaetigt: Es kommt nichts mehr, und das ist kein
            # Fehler. Die Seite blendet den Kasten aus.
            return _ereignisstrom("ende", {})
        # Kein Fehler, sondern das Ende des Weges. Vorher stand hier eine
        # Fehlermeldung, und das Skript holte danach den Knopf zurueck --
        # mit der alten Beschriftung. Wer die letzte Stufe beantwortet
        # hatte, sass in einer Sackgasse und blieb, wie es der Auftraggeber
        # beschrieben hat, "immer in der hoechsten Stufe".
        return _ereignisstrom("ausgeschoepft", {
            "meldung": (
                "Das waren alle Tipps zu dieser Aufgabe. Du kannst mich noch "
                "etwas fragen, oder du machst mit einer neuen Aufgabe weiter."
            ),
        })

    stufe = zug.stufe if zug.ist_hilfe else 0

    # Vor der Loesung wird ausdruecklich gefragt. Die Pruefung steht hier und
    # nicht nur in der Oberflaeche: Ein Knopf, den man umgehen kann, indem man
    # die Anfrage selbst schickt, waere keine Rueckfrage, sondern Zierde.
    if zug.ist_hilfe and stufe == levels.LOESUNG and request.POST.get("loesung") != "ja":
        return _ereignisstrom("loesung_bestaetigen", {
            "frage": "Möchtest du jetzt die Lösung sehen?",
            "hinweis": (
                "Wenn du noch weiterprobieren willst, ist das auch in Ordnung. "
                "Du kannst die Lösung später immer noch holen."
            ),
        })

    # Die Qualitaetssicherung laeuft einmal je Aufgabe, vor dem ersten Zug.
    # Sie kostet einen Aufruf nach draussen; ihn bei jeder Stufe zu
    # wiederholen waere Geldverbrennen ohne Nutzen, die Aufgabe aendert sich
    # ja nicht. Nach dem Ende braucht sie niemand mehr.
    if sitzung.cloud_enabled and not daten["geprueft"] and not aufgabe.ist_abgeschlossen:
        daten["geprueft"] = await _qualitaet_sichern(aufgabe, sitzung, teilnahme)

    if zug.ist_hilfe:
        if wiederholung:
            # Kein Vorruecken: dieselbe Stufe noch einmal, enger.
            vorgemerkt = await _wiederholung_vormerken(aufgabe.pk, aufgabe.repeats)
        else:
            vorgemerkt = await _stufe_vormerken(aufgabe.pk, aufgabe.current_level, stufe)
        if not vorgemerkt:
            return _fehlerstrom("Diese Hilfe wird schon geholt.")
    # Nachfrage, Bestaetigung und Nachsatz verbrauchen keine Stufe und haben
    # keinen Zaehler; der Knopf ist waehrend des Stroms gesperrt.

    antwort = StreamingHttpResponse(
        _hilfe_erzeugen(aufgabe, sitzung, zug, teilnahme, daten,
                        wiederholung, beitrag=beitrag),
        content_type="text/event-stream",
    )
    antwort["Cache-Control"] = "no-cache"
    antwort["X-Accel-Buffering"] = "no"
    return antwort


async def _hilfe_erzeugen(aufgabe, sitzung, zug, teilnahme, daten,
                          wiederholung=False, beitrag=None):
    """Erzeugt die SSE-Ereignisse fuer einen Zug des Tutors.

    ``zug`` sagt, was kommt: eine Hilfestufe, die Nachfrage vor der Hilfe,
    die Bestaetigung mit Warum-Frage oder der Nachsatz darauf (30.10.2026,
    Hilfe nach Diagnose). ``daten`` ist, was _aufgabe_holen eingesammelt
    hat: Verlauf, eigene Texte des Kindes, gepruefte Loesung, der vorige
    Hilfetext (fuer eine Wiederholung), der Fehler aus der letzten Diagnose
    (fuer die Rueckmeldung), Lage, Absicht, Form und Weite. ``beitrag`` ist
    ein Beitrag, den der Server gerade erst fuer das Kind festgehalten hat
    (Tippknopf statt Versuch); die Seite soll ihn anzeigen.

    Jeder Zug laeuft durch die Ausgangspruefung: eine Hilfe mit ihrer
    Stufe, Nachfrage und Bestaetigung mit der Stufe, auf der das Kind
    steht (sie duerfen nicht mehr verraten als die letzte Hilfe), der
    Nachsatz frei, denn die Aufgabe ist geloest und der Weg des Kindes
    bekannt.

    Der abschliessende Block faengt auch den Fall ab, dass das Kind die Seite
    mitten im Strom schliesst oder das Netz abbricht. Dann laeuft weder das
    Sichern noch die Ruecknahme von selbst, und die Stufe waere verbraucht,
    ohne dass eine Hilfe gespeichert ist. Am Handy im Hoersaal ist das kein
    Sonderfall.
    """
    if zug.art == levels.ART_NACHFRAGE and daten.get("fachgrenze"):
        # Die Fachgrenze (7.11.2026): Der letzte Beitrag gehoerte nicht zur
        # Stunde. Kein Modell formuliert; die Nachfrage ist der feste Satz
        # des Fachs mit dem Rueckweg zur letzten Frage des Tutors.
        # Gespeichert und protokolliert wie jede Nachfrage, damit der
        # Verlauf der Lehrperson genau das zeigt, was das Kind gelesen hat.
        text = fachgrenze.satz(
            sitzung.subject or "mathematik", sitzung.age_group,
            thema=sitzung.task_hint, rueckfrage=daten.get("rueckweg") or "",
        )
        bezeichnung = levels.ART_NAMEN[levels.ART_NACHFRAGE]
        yield _ereignis("start", {"stufe": 0, "bezeichnung": bezeichnung, "art": zug.art})
        yield _ereignis("stueck", {"text": text})
        await _hilfe_sichern(aufgabe.pk, teilnahme.pk, daten.get("stand", 0), text,
                             sitzung.pk, art=levels.ART_NACHFRAGE)
        await _anfrage_aufzeichnen(
            sitzung, teilnahme, None, {}, daten["gespraech"], text,
            ergebnis="fachgrenze", diagnose=daten.get("kategorien"),
        )
        yield _ereignis("fertig", {
            "stufe": 0, "bezeichnung": bezeichnung, "art": zug.art,
            "naechste_stufe": None, "naechste_beschriftung": levels.HILFEKNOPF,
            "rueckfrage": None, "wartet": True, "freiwillig": False,
        })
        return

    geprueft = daten.get("geprueft", "")
    art = zug.art
    stufe = zug.stufe if zug.ist_hilfe else 0
    stand = daten.get("stand", 0)
    temperatur = TEMPERATUR
    form = daten.get("form", "")
    weite = daten.get("weite", "")
    if wiederholung and form:
        # Innerhalb einer Stufe erst indirekt, dann direkt (Thomas'
        # Stichprobe, 31.10.2026): Die Wiederholung zeigt die Stelle.
        form = levels.FORM_DIREKT
    # Offene Karten bei einem Umgehungsversuch (Thomas, 31.10.2026): Der
    # feste Satz kommt vom Server, vor dem Text des Modells, und wird mit
    # dem Zug gespeichert, damit die Lehrperson im Verlauf genau das liest,
    # was das Kind gelesen hat. Das Modell bekommt dazu die Anweisung, ihn
    # nicht zu wiederholen (UMGEHUNG_ANWEISUNG). Nur vor einer Hilfe oder
    # einer Nachfrage; Bestaetigung und Nachsatz folgen auf ein richtiges
    # Ergebnis, da gibt es nichts zu umgehen.
    umgehung = (bool(daten.get("umgehung"))
                and art in (levels.ART_HILFE, levels.ART_NACHFRAGE))
    vorspann = levels.UMGEHUNG_SATZ + NL + NL if umgehung else ""
    if art == levels.ART_HILFE:
        system = levels.system_prompt(
            stufe, sitzung.schulstufe, geprueft, altersklasse=sitzung.age_group,
            umfang_titel=_umfang_titel(sitzung), form=form, weite=weite,
            absicht=daten.get("absicht"), umgehung=umgehung,
            aufgabentext=aufgabe.text,
        )
        if wiederholung:
            # Der vorige Text geht mit, der Zugang wechselt mit dem Zaehler,
            # die Frage wird enger, und die Temperatur steigt: Sonst ist der
            # zweite Anlauf der erste mit anderen Worten (Befund 4: 32
            # Wiederholungen, 2 wortgleich).
            system += levels.wiederholung_zusatz(daten.get("letzter_text", ""),
                                                 aufgabe.repeats + 1)
            temperatur = TEMPERATUR_WIEDERHOLUNG
        pruefstufe = stufe
        bezeichnung = levels.kindername(stufe)
    elif art == levels.ART_NACHFRAGE:
        # Ohne Ansatz des Kindes (erster Zug, "weiss nicht", Lage unklar)
        # fragt die Nachfrage nach der Schwierigkeit und behauptet nichts
        # ueber das, was das Kind getan hat (Thomas, 1.11.2026).
        lage = daten.get("lage") or ""
        system = levels.nachfrage_tutor_prompt(
            sitzung.schulstufe, sitzung.age_group, _umfang_titel(sitzung),
            umgehung=umgehung,
            ohne_ansatz=not lage or lage in (levels.LAGE_KEIN_ANSATZ, levels.LAGE_UNKLAR),
        )
        pruefstufe = max(levels.MOTIVATION, stand)
        bezeichnung = levels.ART_NAMEN[art]
    elif art == levels.ART_BESTAETIGUNG:
        # Das Ergebnis ist richtig und der Weg des Kindes bekannt: Die
        # Bestaetigung darf die Rechenart beim Namen nennen (Stufe 4), aber
        # keine neue Zahl und keine Gleichung mit einem anderen Ergebnis.
        system = levels.bestaetigung_prompt(sitzung.schulstufe, sitzung.age_group)
        pruefstufe = levels.STRATEGIE_INHALTLICH
        bezeichnung = levels.ART_NAMEN[art]
    else:
        system = levels.nachsatz_prompt(sitzung.schulstufe, sitzung.age_group)
        pruefstufe = levels.LOESUNG
        bezeichnung = levels.ART_NAMEN.get(art, "")
    frage = _frage_bauen(
        aufgabe, sitzung, daten["gespraech"],
        fehler=daten.get("fehler", "") if art == levels.ART_HILFE else "",
        einschaetzung=(daten.get("einschaetzung", "")
                       if art in (levels.ART_HILFE, levels.ART_NACHFRAGE) else ""),
    )
    vorher = aufgabe.current_level
    gesammelt = []
    erledigt = False
    messung = {}
    gespeicherte_stufe = stufe if art == levels.ART_HILFE else stand
    sichern_mit = {"art": art}
    if art == levels.ART_HILFE:
        sichern_mit.update(form=form, weite=weite)

    async def zuruecknehmen():
        # Die Stufe zuruecknehmen: ohne Hilfe darf sie nicht verbraucht sein.
        if art == levels.ART_HILFE and not wiederholung:
            await _stufe_zuruecknehmen(aufgabe.pk, stufe, vorher)

    try:
        if beitrag:
            yield _ereignis("beitrag", {"text": beitrag})
        # Zuerst den Zug ansagen, dann erst der Text: so weiss das Kind
        # sofort, was kommt, auch wenn das Modell kurz braucht.
        yield _ereignis("start", {
            "stufe": stufe, "bezeichnung": bezeichnung, "art": art,
        })
        if vorspann:
            # Sofort, noch bevor das Modell antwortet: Der Satz haengt an
            # keinem Modell.
            yield _ereignis("stueck", {"text": vorspann})

        try:
            # Erst vollstaendig erzeugen und pruefen, dann ausgeben. Ein
            # Systemprompt ist eine Bitte, keine Grenze: Stufe 1 hat in einem
            # Durchlauf "8, 16, 24, 32, 40, 48" geschrieben und damit die
            # Loesung verraten. Was einmal gestreamt ist, laesst sich nicht
            # zuruecknehmen.
            text_geprueft = await _geprueft_erzeugen(
                system, frage, messung, pruefstufe, sitzung.max_level,
                eigenes=daten["eigenes"], schulstufe=sitzung.schulstufe,
                loesung=geprueft, temperatur=temperatur,
                schlussfrage=levels.schlussfrage_vorlage(art, stufe),
                bestaetigt=art == levels.ART_BESTAETIGUNG,
                vermeiden=daten.get("letzte_fragen") or (),
            )
            if art == levels.ART_HILFE and stufe == levels.LOESUNG:
                text_geprueft = await _loesung_pruefen(
                    system, frage, text_geprueft, geprueft, messung,
                )
            async for stueck in _stueckweise(text_geprueft):
                gesammelt.append(stueck)
                yield _ereignis("stueck", {"text": stueck})
        except SparkNichtErreichbar as fehler:
            await zuruecknehmen()
            await _anfrage_aufzeichnen(
                sitzung, teilnahme, stufe or None, messung, frage, "",
                ergebnis="fehler", fehlerart="Spark nicht erreichbar",
            )
            erledigt = True
            yield _ereignis("fehler", {"meldung": fehler.meldung})
            return

        text = "".join(gesammelt).strip()
        if not text:
            await zuruecknehmen()
            erledigt = True
            yield _ereignis("fehler", {"meldung": MELDUNG_NICHT_ERREICHBAR})
            return

        text = vorspann + text
        await _hilfe_sichern(aufgabe.pk, teilnahme.pk, gespeicherte_stufe, text,
                             sitzung.pk, **sichern_mit)
        await _anfrage_aufzeichnen(
            sitzung, teilnahme, stufe or None, messung, frage, text,
            ergebnis="ok" if art == levels.ART_HILFE else art,
            diagnose=daten.get("kategorien"),
        )
        erledigt = True
        if art == levels.ART_HILFE:
            naechste = levels.naechste_stufe(stufe, sitzung.max_level)
            yield _ereignis("fertig", {
                "stufe": stufe,
                "bezeichnung": bezeichnung,
                "art": art,
                "naechste_stufe": naechste,
                "naechste_beschriftung": levels.HILFEKNOPF,
                "rueckfrage": levels.rueckfrage(stufe),
                # Die Hilfe endet mit ihrer eigenen Frage; die Seite zeigt
                # keinen zweiten festen Arbeitsauftrag mehr darunter (Zech,
                # S. 289: keine Kettenfragen). Sie wartet auf den Versuch.
                "wartet": stufe != levels.LOESUNG,
            })
        else:
            yield _ereignis("fertig", {
                "stufe": 0,
                "bezeichnung": bezeichnung,
                "art": art,
                "naechste_stufe": None,
                "naechste_beschriftung": levels.HILFEKNOPF,
                "rueckfrage": None,
                # Nachfrage: das Kind antwortet, dann kommt die Hilfe.
                # Bestaetigung: antworten ist freiwillig, die naechste
                # Aufgabe steht offen. Nachsatz: nichts mehr.
                "wartet": art in (levels.ART_NACHFRAGE, levels.ART_BESTAETIGUNG),
                "freiwillig": art == levels.ART_BESTAETIGUNG,
            })
    finally:
        if not erledigt:
            angefangen = "".join(gesammelt).strip()
            if angefangen:
                # Das Kind hat den Text gesehen, also gilt der Zug als
                # gegeben und gehoert in den Verlauf.
                await _hilfe_sichern(aufgabe.pk, teilnahme.pk, gespeicherte_stufe,
                                     vorspann + angefangen, sitzung.pk, **sichern_mit)
            else:
                await zuruecknehmen()
            # Auch ein Abbruch ist eine Verarbeitung und gehoert ins
            # Protokoll. Sonst fehlt in der Forschung ausgerechnet der Fall,
            # in dem etwas schiefgegangen ist, und die Auswertung zaehlt
            # weniger Anfragen, als tatsaechlich an das Modell gingen.
            await _anfrage_aufzeichnen(
                sitzung, teilnahme, stufe, messung, frage, angefangen,
                ergebnis="abgebrochen",
                fehlerart="Verbindung zum Browser abgerissen",
            )


async def _am_stueck(system, frage, messung, temperatur=TEMPERATUR):
    """Holt eine Antwort des Modells vollstaendig, bevor sie geprueft wird."""
    stuecke = []
    async for stueck in hilfe_streamen(system, frage, messung=messung,
                                       temperatur=temperatur):
        stuecke.append(stueck)
    return "".join(stuecke).strip()


async def _geprueft_erzeugen(system, frage, messung, stufe, obergrenze,
                             eigenes=None, schulstufe=levels.VOLKSSCHULE,
                             loesung="", temperatur=TEMPERATUR, schlussfrage=None,
                             bestaetigt=False, vermeiden=()):
    """Erzeugt eine Hilfe und laesst nichts durch, was die Stufe verbietet.

    Ein Versuch, dann ein geschaerfter zweiter. Haelt auch der nicht, werden
    die betroffenen Saetze entfernt; bleibt nichts uebrig, kommt ein
    neutraler Satz. Lieber eine duennere Hilfe als eine, die die Loesung
    ausplaudert. Die Pruefung kennt die Schulstufe und die gepruefte
    Loesung: Auf der Sekundarstufe ist eine Gleichung nur dann ein Verstoss,
    wenn rechts das Endergebnis steht.

    ``schlussfrage`` ist die Vorlage fuer einen Zug, der mit einer Frage
    enden muss (levels.schlussfrage_vorlage): Endet der Text ohne
    Fragezeichen, wird einmal nachgefasst, sonst die Vorlage angehaengt.
    None heisst: keine Frage verlangt (Loesung, Nachsatz, Antwort auf eine
    Frage des Kindes). ``bestaetigt`` sagt der Pruefung, dass das Ergebnis
    des Kindes geprueft richtig ist (dann darf keine Rechnung mit anderem
    Rechenzeichen stehen). ``vermeiden`` sind die Fragen der letzten Zuege:
    Stellt der Text eine davon noch einmal, gibt es einen zweiten Anlauf
    mit der Ermahnung, anders zu fragen (Thomas' Stichprobe, 31.10.2026).
    """
    text = await _am_stueck(system, frage, messung, temperatur)

    gefunden = ausgabepruefung.verstoesse(
        text, stufe, obergrenze, eigenes, schulstufe=schulstufe, loesung=loesung,
        bestaetigt=bestaetigt,
    )
    if gefunden:
        logger.warning("Stufe %s: %s, zweiter Versuch", stufe, ", ".join(gefunden))
        # Die Ermahnung muss zum Verstoss passen: Wer einen Rechenweg genannt
        # hat, hilft nichts, wenn man ihm das Rechnen verbietet.
        schaerfung = ausgabepruefung.schaerfung_fuer(gefunden)
        zweiter = await _am_stueck(system + schaerfung, frage, messung, temperatur)
        if not ausgabepruefung.verstoesse(
            zweiter, stufe, obergrenze, eigenes, schulstufe=schulstufe, loesung=loesung,
            bestaetigt=bestaetigt,
        ):
            text = zweiter
        else:
            logger.warning("Stufe %s: auch der zweite Versuch verstoesst", stufe)
            gekuerzt = ausgabepruefung.saubere_saetze(
                zweiter, stufe, obergrenze, eigenes, schulstufe=schulstufe, loesung=loesung,
                bestaetigt=bestaetigt,
            )
            text = gekuerzt or ausgabepruefung.NOTFALL.get(stufe, "")
    if vermeiden and ausgabepruefung.wiederholt_frage(text, vermeiden):
        logger.info("Stufe %s: dieselbe Frage wie zuvor, neuer Anlauf", stufe)
        return await _geprueft_erzeugen(
            system + ausgabepruefung.SCHAERFUNG_SCHLEIFE, frage, messung, stufe, obergrenze,
            eigenes=eigenes, schulstufe=schulstufe, loesung=loesung, temperatur=temperatur,
            schlussfrage=schlussfrage, bestaetigt=bestaetigt, vermeiden=(),
        )
    if schlussfrage:
        text = await _schlussfrage_sichern(
            text, schlussfrage, system, frage, messung, stufe, obergrenze,
            eigenes, schulstufe, loesung, temperatur, bestaetigt,
        )
    return text


async def _schlussfrage_sichern(text, vorlage, system, frage, messung, stufe, obergrenze,
                                eigenes, schulstufe, loesung, temperatur, bestaetigt=False):
    """Sorgt dafuer, dass der Zug mit seiner Frage endet (Zech, S. 289).

    Ein Systemprompt ist eine Bitte: In Lauf F (31.10.2026) endete jeder
    dritte Zug ohne Frage, meist weil die Kuerzung den Fragesatz entfernt
    hatte. Steht die Frage im Text, aber nicht am Ende, faellt der kurze
    Nachsatz weg. Fehlt sie, holt der Server sie mit einer zweiten, kurzen
    Anfrage und prueft sie wie die Hilfe; taugt sie nicht, kommt die Vorlage
    der Stufe. Die Frage gehoert zum Text: Die Diagnose liest sie als
    "Frage der Hilfe" mit.
    """
    text = ausgabepruefung.ohne_nachsatz_zur_frage(text)
    if ausgabepruefung.endet_mit_frage(text) or "?" in text:
        return text
    logger.info("Stufe %s: Zug ohne Frage, nachgefasst", stufe)
    roh = await _am_stueck(system, ausgabepruefung.nachfassen_anfrage(frage, text),
                           messung, temperatur)
    neue = ausgabepruefung.frage_bereinigt(roh, stufe, obergrenze, eigenes, schulstufe, loesung,
                                           bestaetigt=bestaetigt)
    if not neue:
        logger.info("Stufe %s: Nachfassen ohne brauchbare Frage, Vorlage", stufe)
        neue = vorlage
    return ausgabepruefung.mit_schlussfrage(text, neue)


async def _loesung_pruefen(system, frage, text, loesung, messung):
    """Prueft die Loesung (Stufe 5), bevor das Kind sie sieht.

    Mit gepruefter Loesung aus der Qualitaetssicherung: Steht ihr
    Endergebnis nicht im Text, wird die Loesung einmal neu erzeugt, mit dem
    Hinweis auf die Abweichung. Ohne gepruefte Loesung: ein zweiter Aufruf,
    der die eigene Loesung durch Einsetzen prueft und sie berichtigt oder
    unveraendert wiedergibt. Beides kostet einen Aufruf, und beides nur auf
    Stufe 5, die selten ist (9 von 292 Zuegen in Lauf B) und fachlich die
    schwaechste war (1,56 von 2; "10 · 1 + 35 · 1 = 45"). Auf allen anderen
    Stufen gibt es keinen zusaetzlichen Aufruf (Benchmark 19.10.2026,
    Aenderung 8).
    """
    if not text:
        return text
    passt = ausgabepruefung.loesung_passt(text, loesung)
    if passt is True:
        return text
    if passt is False:
        logger.warning("Stufe 5 weicht von der geprueften Loesung ab, neuer Anlauf")
        zweiter = await _am_stueck(
            system + ausgabepruefung.SCHAERFUNG_LOESUNG_ABWEICHUNG, frage, messung,
        )
        if zweiter and not ausgabepruefung.loesung_passt(zweiter, loesung):
            logger.warning("Stufe 5 weicht auch im zweiten Anlauf ab")
        return zweiter or text
    auftrag = ausgabepruefung.LOESUNG_PRUEFEN.replace("{loesung}", text)
    zweiter = await _am_stueck(system, frage + "\n\n" + auftrag, messung)
    return zweiter or text


async def _stueckweise(text, haeppchen=3, pause=0.03):
    """Gibt einen fertigen Text so aus, wie er entstanden waere.

    Das Schreiben bleibt sichtbar, obwohl der Text vorher geprueft wurde.
    Die Pause ist an dem gemessen, was der Spark liefert: rund 20
    Millisekunden zwischen zwei Stuecken.
    """
    worte = (text or "").split(" ")
    for i in range(0, len(worte), haeppchen):
        stueck = " ".join(worte[i:i + haeppchen])
        if i + haeppchen < len(worte):
            stueck += " "
        yield stueck
        await asyncio.sleep(pause)


def _frage_bauen(aufgabe, sitzung, gespraech, fehler="", einschaetzung=""):
    """Die Anfrage an das Modell: Thema, Angabe, Verlauf, Einschaetzung, Fehler."""
    teile = []
    if sitzung.task_hint:
        teile.append(f"Art der Aufgabe: {sitzung.task_hint}")
    if sitzung.schulstufe == levels.VOLKSSCHULE and not levels.enthaelt_frage(aufgabe.text):
        # Als Tatsache in der Anfrage, nicht als Bedingung im Prompt: Die
        # Anweisung "sag es, wenn keine Frage dasteht" hat das Modell
        # zweimal ueberlesen, diese Zeile nicht. Nur fuer die Volksschule:
        # Auf der Sekundarstufe ist der Imperativ die Norm (Befund 6).
        teile.append(
            "Hinweis für dich: Diese Angabe enthält keine Frage. Das Kind kann "
            "also gar nicht wissen, was es ausrechnen soll. Sprich das an, aber "
            "erst, nachdem du auf das eingegangen bist, was das Kind geschrieben "
            "hat. Eine Verständnisfrage des Kindes hat immer Vorrang."
        )
    teile.append(f"Die Aufgabe des Kindes lautet:\n{aufgabe.text}")
    if gespraech:
        teile.append("Bisheriger Verlauf:\n" + gespraech)
    if einschaetzung:
        # Lage und Absicht aus der Diagnose (30.10.2026), als Tatsache ueber
        # dieses Gespraech. Die Form der Hilfe steht im Systemprompt.
        teile.append(einschaetzung)
    if fehler:
        # Aus der Diagnose, damit die Rueckmeldung den Fehler nicht erst
        # suchen muss und die Kuerzung der Ausgangspruefung ihn nicht
        # wegschneidet (Befund 3: 12 von 49 Fehlern uebersehen).
        teile.append(
            "Der Fehler des Kindes im letzten Versuch, den du benennen musst, "
            f"ohne das richtige Ergebnis zu verraten: {fehler}"
        )
    return "\n\n".join(teile)


def _ereignis(name, nutzlast):
    """Baut eine SSE-Nachricht. JSON, damit Zeilenumbrueche nichts zerreissen."""
    return f"event: {name}\ndata: {json.dumps(nutzlast, ensure_ascii=False)}\n\n"


def _fehlerstrom(meldung):
    return _ereignisstrom("fehler", {"meldung": meldung})


def _ereignisstrom(name, nutzlast):
    """Ein einzelnes Ereignis, ohne dass etwas gestreamt wird."""
    antwort = StreamingHttpResponse(
        iter([_ereignis(name, nutzlast)]), content_type="text/event-stream"
    )
    antwort["Cache-Control"] = "no-cache"
    return antwort


@sync_to_async
def _aufgabe_holen(task_id, teilnahme_id):
    """Holt Aufgabe, Sitzung und bisherigen Verlauf in einem Zug.

    Alles, was die Streamingansicht spaeter braucht, wird hier eingesammelt:
    im asynchronen Teil darf kein Zugriff mehr in die Datenbank rutschen.
    """
    aufgabe = (Task.objects.select_related("participation__learning_session")
               .filter(pk=task_id, participation_id=teilnahme_id).first())
    if aufgabe is None:
        return None
    sitzung = aufgabe.participation.learning_session

    zeilen, eigenes = _gespraechszeilen(aufgabe)
    letzte = aufgabe.letzte_hilfe
    letzte_stufenhilfe = aufgabe.letzte_stufenhilfe
    offene = aufgabe.offene_hilfe
    # Auch die Entscheidung ueber den naechsten Zug faellt hier:
    # Sie fragt die Datenbank, und im asynchronen Teil ist das
    # nicht erlaubt.
    zug = aufgabe.naechster_zug()
    wiederholung = bool(zug and zug.wiederholung)
    # Die Einschaetzung des letzten Beitrags, aus der die Hilfe ihre Form
    # nimmt (30.10.2026): Lage und Absicht als Satz in die Anfrage, Form und
    # Weite als Anweisung in den Systemprompt. Eine Wiederholung fragt
    # enger (Zech, S. 288).
    lage = letzte.lage if letzte else ""
    absicht = letzte.absicht if letzte else ""
    form = letzte.next_form if letzte and letzte.next_form else ""
    if not form:
        # Die erste Hilfe jeder Stufe ist indirekt, auf allen Schulstufen
        # (Thomas, 31.10.2026); die Wiederholung macht _hilfe_erzeugen direkt.
        form = levels.FORM_INDIREKT
    fehler = letzte.error if letzte and letzte.result == Hint.ERGEBNIS_FALSCH else ""
    return {
        "aufgabe": aufgabe,
        "sitzung": sitzung,
        "gespraech": NL.join(zeilen),
        "eigenes": eigenes,
        "wartet": offene is not None,
        "offene_id": offene.pk if offene else None,
        "zug": zug,
        "stufe": zug.stufe if zug and zug.ist_hilfe else None,
        "wiederholung": wiederholung,
        "stand": aufgabe.stand,
        "geprueft": aufgabe.checked_solution,
        # Fuer eine Wiederholung: was zuletzt dastand, damit das Modell es
        # nicht noch einmal sagt.
        "letzter_text": letzte_stufenhilfe.text if letzte_stufenhilfe else "",
        # Die Fragen der letzten beiden Zuege: Dieselbe Frage ein drittes Mal
        # ist eine Schleife (Thomas' Stichprobe, 31.10.2026, Zug 14).
        "letzte_fragen": [
            levels.letzte_frage(h.text)
            for h in aufgabe.hints.exclude(art=levels.ART_AUFTAKT)
                                  .order_by("-created_at", "-pk")[:2]
            if levels.letzte_frage(h.text)
        ],
        # Aus der Diagnose des letzten Versuchs, wenn er falsch war.
        "fehler": fehler,
        "lage": lage,
        "absicht": absicht,
        # Offene Karten (31.10.2026): War der letzte Beitrag ein
        # Umgehungsversuch, sagt der Server dem Kind vor dem naechsten Zug
        # den festen Satz dazu (levels.UMGEHUNG_SATZ).
        "umgehung": bool(letzte is not None
                         and letzte.absicht == levels.ABSICHT_UMGEHUNG),
        # Die Fachgrenze (7.11.2026): Der letzte Beitrag gehoerte nicht zur
        # Stunde (goal_note traegt den festen Grund), und der naechste Zug ist
        # die Nachfrage. Dann schreibt _hilfe_erzeugen den festen Satz des
        # Fachs statt das Modell zu fragen; der Rueckweg ist die letzte Frage
        # des Tutors.
        "fachgrenze": bool(letzte is not None and letzte.goal_note == fachgrenze.GRUND
                           and zug is not None and zug.art == levels.ART_NACHFRAGE),
        "rueckweg": levels.letzte_frage(letzte.text) if letzte is not None else "",
        "form": form,
        # Eng nicht nur bei derselben Stufe: Auch wer nach zwei Hilfen noch
        # keinen Ansatz hat, braucht die engere Frage (Zech, S. 288). Lauf E,
        # sek01: dieselbe Pizza-Erklaerung viermal, auf zwei Stufen.
        "weite": (levels.WEITE_ENG
                  if wiederholung or (letzte is not None
                                      and letzte.lage == levels.LAGE_KEIN_ANSATZ
                                      and aufgabe.hints.filter(art=levels.ART_HILFE).count() >= 2)
                  else levels.WEITE_WEIT),
        "einschaetzung": levels.einschaetzung_text(lage, absicht, fehler),
        # Die Diagnose als Kategorien fuer das Protokoll der Anfrage.
        "kategorien": ({
            "lage": lage, "absicht": absicht, "form": form,
            "hilfe": zug.stufe if zug and zug.ist_hilfe else (
                levels.ERST_FRAGEN if zug and zug.art == levels.ART_NACHFRAGE else None),
            "ergebnis": letzte.result if letzte else "",
        } if letzte else {}),
    }


@sync_to_async
def _anfrage_aufzeichnen(sitzung, teilnahme, stufe, messung, frage, antwort,
                         ergebnis="ok", fehlerart="", diagnose=None):
    """Schreibt die Protokollzeile fuer eine Anfrage an den Spark.

    Der lokale Weg braucht keinen Leak-Check: Es geht nichts hinaus. Die
    Maskierung kommt mit dem Privacy Shield und wird dann hier eingehaengt.
    ``diagnose`` sind die Kategorien der Einschaetzung, die zu diesem Zug
    gefuehrt hat (Lage, Absicht, Hilfe, Form), ohne Inhalte.
    """
    Interaction.aufzeichnen(
        sitzung=sitzung,
        teilnahme=teilnahme,
        stufe_angefordert=stufe,
        stufe_gewaehrt=stufe if ergebnis == "ok" else None,
        diagnose=diagnose,
        weg=Interaction.LOKAL,
        modell=settings.SPARK_MODEL,
        tokens_ein=messung.get("tokens_ein", 0),
        tokens_aus=messung.get("tokens_aus", 0),
        dauer_ms=messung.get("dauer_ms", 0),
        kosten_micro=0,  # Der Spark kostet kein Geld, nur Rechenzeit.
        leak_check=Interaction.ENTFAELLT,
        ergebnis=ergebnis,
        fehlerart=fehlerart,
        text_ein=frage,
        text_aus=antwort,
    )


@sync_to_async
def _nachfrage_holen(frage_id, teilnahme_id):
    """Holt Frage, Sitzung und den bisherigen Verlauf in einem Zug."""
    frage = (Question.objects
             .select_related("task__participation__learning_session")
             .filter(pk=frage_id, task__participation_id=teilnahme_id).first())
    if frage is None:
        return None
    aufgabe = frage.task
    sitzung = aufgabe.participation.learning_session

    zeilen = ["Die Aufgabe lautet:" + NL + aufgabe.text]
    # Getrennt: was das Kind selbst geschrieben hat. Nur das darf die
    # Ausgangspruefung als Zitat durchgehen lassen.
    eigenes = [aufgabe.text, frage.text]
    for hilfe in aufgabe.hints.order_by("created_at", "pk"):
        zeile = _zugzeile(hilfe)
        if zeile:
            zeilen.append(zeile)
        if hilfe.response:
            zeilen.append(f"Darauf hat das Kind geantwortet: {hilfe.response}")
            eigenes.append(hilfe.response)
    for frueher in aufgabe.questions.exclude(pk=frage.pk).order_by("created_at"):
        zeilen.append(f"Frühere Rückfrage: {frueher.text}")
        eigenes.append(frueher.text)
        if frueher.answer:
            zeilen.append(f"Antwort darauf: {frueher.answer}")

    # Die Grenze der Antwort ist die STUFE, auf der das Kind gerade steht -
    # nicht die Obergrenze der Sitzung. Wer nach der ersten Hilfe fragt,
    # "muss ich das Buch dazuzaehlen?", bekommt eine Antwort auf Stufe 1 und
    # nicht eine, die schon den Rechenweg kennt. Erst wenn die Stufen aus
    # sind, gilt die Obergrenze der Lehrperson. Hier gerechnet und nicht im
    # Strom: Der Strom ist asynchron und darf die Datenbank nicht anfassen.
    unterwegs = not aufgabe.stufen_ausgeschoepft
    grenze = (max(levels.MOTIVATION, min(aufgabe.stand, sitzung.max_level))
              if unterwegs else sitzung.max_level)
    offene = aufgabe.offene_hilfe
    # Der Arbeitsauftrag, mit dem die Antwort schliesst: die Frage, die die
    # offene Hilfe oder Nachfrage wirklich gestellt hat, nicht mehr der
    # feste Satz der Stufe (Zech, S. 289: keine Kettenfragen).
    rueckfrage = levels.letzte_frage(offene.text) if offene else ""
    return frage, sitzung, NL.join(zeilen), eigenes, grenze, unterwegs, rueckfrage


@sync_to_async
def _nachfrage_sichern(frage_id, text):
    Question.objects.filter(pk=frage_id).update(answer=text)


@sync_to_async
def _stufe_vormerken(task_id, erwartet, neue_stufe):
    """Setzt die Stufe nur, wenn sie noch auf dem erwarteten Wert steht.

    Mit dem Stufenwechsel beginnt der Wiederholungszaehler von vorn:
    ``repeats`` zaehlt je Stufe, nicht je Aufgabe. Vorher zaehlte er je
    Aufgabe, und ein Kind, das Stufe 1 zweimal gebraucht hatte, bekam Stufe
    3 kein zweites Mal (Benchmark 19.10.2026, Aenderung 6).
    """
    betroffen = Task.objects.filter(pk=task_id, current_level=erwartet).update(
        current_level=neue_stufe, repeats=0
    )
    return betroffen == 1


@sync_to_async
def _tipp_vermerken(hint_id):
    """Haelt fest, dass das Kind statt eines Versuchs um einen Tipp gebeten hat.

    Kein Versuch, die Stufe bleibt (dieselbe noch einmal, anderer Zugang),
    kein Aufruf an das Modell: Das ist dieselbe deterministische Regel wie
    fuer "weiss nicht".
    """
    # Dieselbe Stufe noch einmal, enger; waehrend einer Nachfrage vor der
    # ersten Hilfe (Stufe 0) die erste Hilfe, sonst fragte der Tutor ein
    # zweites Mal, obwohl das Kind gerade um einen Tipp gebeten hat.
    hilfe = Hint.objects.filter(pk=hint_id, response="").first()
    if hilfe is None:
        return
    Hint.objects.filter(pk=hint_id).update(
        response=TIPP_STATT_VERSUCH, responded_at=timezone.now(),
        next_level=max(hilfe.level, levels.MOTIVATION), goal_reached=False,
        goal_note="Um einen Tipp gebeten, kein Versuch.",
        result=Hint.ERGEBNIS_OFFEN, error="",
        lage=levels.LAGE_KEIN_ANSATZ, absicht=levels.ABSICHT_TIPP,
    )


async def _qualitaet_sichern(aufgabe, sitzung, teilnahme):
    """Holt einmal je Aufgabe eine geprüfte Lösung von draussen.

    Der Weg ist der aus Abschnitt 3a: Der Spark anonymisiert, das
    Frontier-Modell loest, die Platzhalter werden lokal wieder eingesetzt.
    Das Ergebnis sieht das Kind nicht; es steht im Systemprompt der
    Stufenhilfen, damit ein falscher Ansatz sofort auffaellt.

    Faellt der Weg aus, geht es ohne ihn weiter. Die Qualitaetssicherung ist
    eine Zugabe, keine Voraussetzung: Eine Sitzung darf nicht daran
    scheitern, dass ein fremder Dienst gerade nicht mag.

    Seit 31.10.2026 kann ein Ausschnitt des Fotos mitgehen, wenn die
    Lehrperson das freigegeben hat und die Bildkette ihn durchlaesst
    (_bild_freigeben). Scheitert die Bildkette, laeuft der Text allein, wie
    vorher.
    """
    verbrauch = await _cloud_verbrauch(sitzung)
    bild = await _bild_freigeben(aufgabe, sitzung, teilnahme, verbrauch)
    try:
        ergebnis = await sync_to_async(cloud.geprueft_loesen)(
            aufgabe.text, verbrauch, bild=bild or None
        )
    except cloud.CloudGesperrt as fehler:
        logger.warning("Qualitätssicherung nicht gelaufen: %s", fehler.art)
        await _qs_aufzeichnen(sitzung, teilnahme, None, ergebnis="gesperrt",
                              fehlerart=fehler.art)
        await _qs_vermerken(aufgabe.pk, fehler.grund)
        return ""
    except Exception as fehler:  # noqa: BLE001 - die Sitzung laeuft weiter
        logger.warning("Qualitätssicherung gescheitert: %s", type(fehler).__name__)
        await _qs_aufzeichnen(sitzung, teilnahme, None, ergebnis="fehler",
                              fehlerart=type(fehler).__name__)
        await _qs_vermerken(aufgabe.pk, "Die externe KI hat nicht geantwortet.")
        return ""

    await _geprueftes_sichern(aufgabe.pk, ergebnis)
    await _qs_aufzeichnen(sitzung, teilnahme, ergebnis)
    return ergebnis["loesung"]


async def _bild_freigeben(aufgabe, sitzung, teilnahme, verbrauch):
    """Der Bildweg, falls freigegeben. Gibt den Ausschnitt als Data-URL oder "".

    Laeuft nur, wenn drei Dinge zusammenkommen: Die Lehrperson hat beide
    Schalter gesetzt, die Aufgabe hat ein Foto, und der Weg nach draussen
    ist ueberhaupt offen (Zugang, Budget). Eine Bildpruefung fuer einen
    Aufruf, der gleich am Budget scheitert, waere acht Sekunden fuer nichts.

    Scheitert die Kette, bleibt es beim Text: Die Aufgabe traegt den Grund
    (Verlauf), das Protokoll die Art, und die Qualitaetssicherung laeuft
    weiter wie vor dem 31.10.2026.
    """
    if not (sitzung.cloud_enabled and sitzung.cloud_images_enabled
            and aufgabe.image_data_url):
        return ""
    if not cloud.moeglich() or cloud.budget_pruefen(verbrauch):
        return ""
    try:
        befund = await sync_to_async(bildkette.bereinigen)(
            aufgabe.image_data_url, aufgabe.text
        )
    except bildkette.BildGesperrt as fehler:
        logger.warning("Bildweg gesperrt: %s", fehler.art)
        await _bild_vermerken(aufgabe.pk, bildkette.BLOCKIERT, fehler.grund)
        await _bild_aufzeichnen(sitzung, teilnahme, None, fehlerart=fehler.art)
        return ""
    await _bild_vermerken(aufgabe.pk, bildkette.BESTANDEN, "", befund)
    await _bild_aufzeichnen(sitzung, teilnahme, befund)
    return befund.data_url


@sync_to_async
def _bild_vermerken(task_id, pruefung_ergebnis, grund, befund=None):
    """Haelt an der Aufgabe fest, wie die Bildkette ausging.

    Der Ausschnitt steht mit dabei, damit die Lehrperson ihn im Verlauf
    neben dem Foto sieht. Er stirbt mit der Sitzung wie das Foto.
    """
    felder = {
        "checked_image_check": pruefung_ergebnis,
        "checked_image_reason": grund[:120],
    }
    if befund is not None:
        felder.update(
            checked_image_sent=befund.data_url,
            checked_image_masks=befund.masken,
            checked_image_ms=befund.dauer_ms,
        )
    Task.objects.filter(pk=task_id).update(**felder)


@sync_to_async
def _bild_aufzeichnen(sitzung, teilnahme, befund, fehlerart=""):
    """Die Protokollzeile der Bildpruefung.

    Ein lokaler Weg, denn die Pruefung laeuft am Spark; was danach
    hinausging, steht in der Zeile des Cloud-Aufrufs. Inhalt steht keiner
    darin, auf keiner Protokollstufe: Bildinhalte gehoeren nicht ins
    Forschungsprotokoll (Abschnitt 3b), nur die Zaehlung der Masken je Typ.
    """
    if befund is None:
        Interaction.aufzeichnen(
            sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
            modell=settings.SPARK_MODEL, ergebnis="bild_gesperrt",
            fehlerart=fehlerart, leak_check=Interaction.BLOCKIERT,
            text_ein="[Foto]",
        )
        return
    Interaction.aufzeichnen(
        sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.LOKAL,
        modell=settings.SPARK_MODEL,
        tokens_ein=befund.tokens_ein, tokens_aus=befund.tokens_aus,
        dauer_ms=befund.dauer_ms, leak_check=Interaction.BESTANDEN,
        entitaeten={f"bild_{typ}": anzahl for typ, anzahl in befund.masken.items() if anzahl},
        ergebnis="bild_bestanden", text_ein="[Foto]", text_aus="[Bildausschnitt]",
    )


def cloud_verbrauch(sitzung):
    """Was hat der Weg nach draussen bisher gekostet?

    Gezaehlt wird beides: Aufrufe und Euro. Die Euro sind nur so gut wie die
    hinterlegten Preise, und die sind haeufig gar nicht hinterlegt. Die
    Aufrufe stimmen immer.

    Gezaehlt wird ueber den pseudonymen Sitzungsschluessel, nicht ueber einen
    Fremdschluessel: Das Protokoll ueberlebt die Sitzung, die Bruecke zu den
    Personen nicht.

    Synchron, weil der Safe Chat (chat_views.py) synchron ist; die
    Streamingansicht der Aufgabenhilfe nimmt die Huelle darunter.
    """
    heute = timezone.now().date()
    cloudzeilen = Interaction.objects.filter(route=Interaction.CLOUD)
    dieser = cloudzeilen.filter(session_key=sitzung.log_key)
    tag = cloudzeilen.filter(created_at__date=heute)
    return {
        "aufrufe_sitzung": dieser.count(),
        "aufrufe_tag": tag.count(),
        "euro_sitzung": (dieser.aggregate(s=models.Sum("cost_micro"))["s"] or 0) / 1_000_000,
        "euro_tag": (tag.aggregate(s=models.Sum("cost_micro"))["s"] or 0) / 1_000_000,
    }


_cloud_verbrauch = sync_to_async(cloud_verbrauch)


@sync_to_async
def _geprueftes_sichern(task_id, ergebnis):
    """Haelt fest, was ausgetauscht wurde - nicht nur das Ergebnis.

    Die Lehrperson soll im Verlauf nachlesen koennen, was das Haus verlassen
    hat und was zurueckkam. Ohne das ist die Qualitaetssicherung eine
    Blackbox mitten im Lernweg.
    """
    Task.objects.filter(pk=task_id).update(
        checked_solution=ergebnis["loesung"],
        checked_at=timezone.now(),
        checked_model=ergebnis["modell"],
        checked_rewritten=ergebnis.get("umgeschrieben", ""),
        checked_sent=ergebnis["maskiert_ein"],
        checked_received=ergebnis["maskiert_aus"],
        checked_entities=ergebnis["entitaeten"],
        checked_tokens_in=ergebnis["tokens_ein"],
        checked_tokens_out=ergebnis["tokens_aus"],
        checked_ms=ergebnis["dauer_ms"],
        checked_cost_micro=cloud.kosten_micro(
            ergebnis["modell"], ergebnis["tokens_ein"], ergebnis["tokens_aus"]
        ),
        checked_blocked="",
    )


@sync_to_async
def _qs_vermerken(task_id, grund):
    """Haelt fest, dass und warum der Weg nach draussen zu blieb.

    Ein leeres Feld liesse offen, ob die Qualitaetssicherung aus war oder
    gescheitert ist. Das ist fuer die Auswertung ein Unterschied.
    """
    Task.objects.filter(pk=task_id).update(checked_blocked=grund[:120])


@sync_to_async
def _qs_aufzeichnen(sitzung, teilnahme, ergebnis, ergebnis_art="ok", fehlerart=""):
    """Schreibt die Protokollzeile fuer den Weg nach draussen.

    Hier ist der Leak-Check nicht 'entfaellt' wie beim lokalen Weg: Er ist
    wirklich gelaufen, und das soll im Protokoll stehen.
    """
    if ergebnis is None:
        Interaction.aufzeichnen(
            sitzung=sitzung, teilnahme=teilnahme, weg=Interaction.CLOUD,
            modell=settings.CLOUD_MODEL, ergebnis=ergebnis_art,
            fehlerart=fehlerart, leak_check=Interaction.BLOCKIERT,
        )
        return
    Interaction.aufzeichnen(
        sitzung=sitzung,
        teilnahme=teilnahme,
        weg=Interaction.CLOUD,
        modell=ergebnis["modell"],
        tokens_ein=ergebnis["tokens_ein"],
        tokens_aus=ergebnis["tokens_aus"],
        dauer_ms=ergebnis["dauer_ms"],
        kosten_micro=cloud.kosten_micro(
            ergebnis["modell"], ergebnis["tokens_ein"], ergebnis["tokens_aus"]
        ),
        leak_check=Interaction.BESTANDEN,
        entitaeten=ergebnis["entitaeten"],
        ergebnis="ok",
        maskiert_ein=ergebnis["maskiert_ein"],
        maskiert_aus=ergebnis["maskiert_aus"],
        text_aus=ergebnis["loesung"],
        anweisung=ergebnis.get("anweisung", ""),
    )


@sync_to_async
def _wiederholung_vormerken(task_id, erwartet):
    """Zaehlt die Wiederholung hoch, ohne die Stufe zu veraendern."""
    betroffen = Task.objects.filter(pk=task_id, repeats=erwartet).update(
        repeats=erwartet + 1
    )
    return betroffen == 1


@sync_to_async
def _stufe_zuruecknehmen(task_id, vorgemerkt, vorher):
    Task.objects.filter(pk=task_id, current_level=vorgemerkt).update(current_level=vorher)


@sync_to_async
def _hilfe_sichern(task_id, teilnahme_id, stufe, text, sitzung_id,
                   art=levels.ART_HILFE, form="", weite=""):
    """Haelt einen Zug des Tutors fest.

    Nur eine Stufe (ART_HILFE) zaehlt fuer die hoechste erreichte Stufe
    der Teilnahme; Nachfrage, Bestaetigung und Nachsatz tragen die Stufe
    nur als Stand mit.
    """
    with transaction.atomic():
        Hint.objects.create(task_id=task_id, level=stufe or 0, text=text, art=art,
                            form=form or "", weite=weite or "")
        if art == levels.ART_HILFE:
            Participation.objects.filter(
                pk=teilnahme_id, max_level_reached__lt=stufe,
            ).update(max_level_reached=stufe)
    LearningSession.objects.filter(pk=sitzung_id).update(last_activity_at=timezone.now())
