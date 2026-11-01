"""Die Ansichten der Musikstunde.

Eigene Datei wie beim Trainer und beim Sprechcoach: Die Betriebsarten teilen
Beitritt, Tierwahl, Verfall und Beenden (tutoring/views.py), sonst wenig.

Was von der oeffentlichen Probierecke auf /projekt/ kommt und nicht noch
einmal geschrieben ist: die Vorlagen des Dienstes und die Marken samt
Zwischenspeicher (musik_oeffentlich.stand_holen), die Wortpruefung
(musik_oeffentlich.text_erlaubt, also der deterministische Boden der
Aufgabenhilfe plus die Sperrliste), das Durchreichen der MP3
(musik_oeffentlich.datei_antwort) und das Skript im Browser
(musik_oeffentlich.js).

Was hier anders ist als dort, und warum:

- Die Grenzen setzt die Lehrperson (Hoechstdauer, Lieder je Kind, Sprache
  des Gesangs, Textvorschlag ja oder nein) und nicht eine Konstante. Der
  Server setzt sie durch; die Seite zeigt nur, was erlaubt ist.
- Die Stile kommen aus dem eigenen Katalog (tutoring/musikstile.py) plus den
  Vorlagen des Dienstes, in Gruppen, dazu ein freies Feld. Die Tags baut
  der Server; aus dem Browser kommen ein Schluessel und hoechstens 200
  Zeichen Stilbeschreibung, die geprueft werden wie ein Liedtext.
- Die Lieder haengen an der Teilnahme (Modell Lied) statt an einem Keks,
  damit die Lehrperson sie sieht und damit sie mit der Sitzung sterben.
- Das Kennzeichen am Dienst ist der log_key der Sitzung, damit Beenden und
  Verfall alle Lieder einer Stunde mit einem Aufruf loeschen koennen.
- Zusaetzlich zur Sperre stuft das Sprachmodell den Text ein
  (pruefung.einstufen), wie bei einer Aufgabe. Das blockiert nichts, es
  faerbt die Ampel der Lehrperson.
- Der Textvorschlag (text): Das Sprachmodell am Spark schreibt zu einem
  Thema einen Liedtext in das Feld des Kindes. Der Vorschlag wird geprueft
  wie ein Liedtext, aber ohne Ampel, weil das Kind nichts getan hat; was
  gesperrt ist, sieht niemand. Vertont wird erst, was das Kind abschickt.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core import musik, musik_oeffentlich, musik_zeit

from . import musikstile, musikstunde, pruefung
from .models import LearningSession, Lied, Participation
from .spark import SparkNichtErreichbar, antwort_holen_sync

logger = logging.getLogger(__name__)

NICHT_VERBUNDEN = musik_oeffentlich.NICHT_VERBUNDEN
TEXT_ABGELEHNT = musik_oeffentlich.TEXT_ABGELEHNT
STIL_FEHLT = musik_oeffentlich.STIL_FEHLT
TEXT_ZU_LANG = f"Der Liedtext darf höchstens {musikstunde.TEXT_MAX} Zeichen lang sein."
NICHT_MEHR_DA = ("Dieses Lied ist am Spark nicht mehr da. Lieder werden mit dem Ende "
                 "der Stunde gelöscht.")
NICHT_GELUNGEN = "Das Lied konnte nicht erzeugt werden."
STIL_ABGELEHNT = ("In der Stilbeschreibung steht ein Wort, das hier nicht verwendet "
                  "wird. Bitte anders formulieren.")
EIGEN_FEHLT = ("Beschreib deinen eigenen Stil im Feld darunter, oder wähl einen Stil "
               "aus der Liste.")
TEXTHILFE_AUS = "In dieser Stunde schreibt ihr die Texte selbst."
THEMA_FEHLT = "Worum soll das Lied gehen? Schreib ein paar Wörter dazu."
ZU_VIELE_VORSCHLAEGE = (f"Du hast schon {musikstunde.TEXTHILFE_HOECHSTENS} Vorschläge "
                        "bekommen. Den nächsten Text schreibst du selbst.")
SPARK_SCHWEIGT = ("Der Spark antwortet gerade nicht. Probier es in einer Minute noch "
                  "einmal, oder schreib den Text selbst.")
VORSCHLAG_NICHTS = ("Der Vorschlag ist nichts geworden. Probier es noch einmal, "
                    "vielleicht mit anderen Wörtern, oder schreib den Text selbst.")

# Diese Zustaende zaehlen nicht gegen die Grenze "Lieder je Kind": Ein
# Lied, das der Spark nicht hinbekommen hat, soll kein Kind einen Versuch
# kosten.
ZAEHLT_NICHT = (Lied.FEHLER,)


def _nein(satz, status=400, **mehr):
    return JsonResponse({"ok": False, "grund": satz, **mehr}, status=status)


def _ganzzahl(wert):
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return None


def _einzeilig(wert, hoechstens):
    """Eine Zeile aus einem Formularfeld, ohne Steuerzeichen, begrenzt."""
    return musikstile.eigen_bereinigen(wert)[:hoechstens].strip()


def _teilnahme(request):
    """Die Teilnahme dieses Browsers, wenn sie in einer offenen Musikstunde ist.

    Gibt (teilnahme, grund) zurueck; grund ist ein Satz fuer die Absage.
    """
    from .views import _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return None, "Keine Sitzung."
    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        return None, "Die Sitzung ist beendet."
    if not sitzung.ist_musik or not teilnahme.hat_tier:
        return None, "Hier gibt es keine Musikstunde."
    return teilnahme, ""


def _eigenes_lied(request, kennung):
    """Nur ein Lied der eigenen Teilnahme, sonst 404 - auch fuer fremde."""
    if not musik.KENNUNG.match(kennung):
        raise Http404
    teilnahme, _ = _teilnahme(request)
    if teilnahme is None:
        raise Http404
    lied = Lied.objects.filter(participation=teilnahme, auftrag=kennung).first()
    if lied is None:
        raise Http404
    return lied


def _gezaehlt(teilnahme):
    return teilnahme.lieder.exclude(zustand__in=ZAEHLT_NICHT).count()


def _adressen(lied):
    return {
        "abfrage": reverse("tutoring:musik_auftrag", args=[lied.auftrag]),
        "datei": reverse("tutoring:musik_datei", args=[lied.auftrag]),
    }


def _liste_umgebung(teilnahme):
    sitzung = teilnahme.learning_session
    lieder = list(teilnahme.lieder.order_by("-angelegt_am", "-pk"))
    gezaehlt = sum(1 for l in lieder if l.zustand not in ZAEHLT_NICHT)
    return {
        "lieder": [{"lied": l, **_adressen(l)} for l in lieder],
        "noch": max(sitzung.songs_per_child - gezaehlt, 0),
        "hoechstens": sitzung.songs_per_child,
    }


def _stile(werte):
    """Katalog plus Vorlagen des Dienstes, wie sie die Seite und /lied sehen."""
    return musikstile.zusammenfuehren(werte.get("stile") or [])


# --- Die Seite des Kindes ---------------------------------------------------

def musikseite(request):
    """Der Arbeitsplatz des Kindes in der Musikstunde."""
    from .views import SCHLUESSEL_TEILNAHME, _teilnahme_holen

    teilnahme = _teilnahme_holen(request)
    if teilnahme is None:
        return redirect("start")

    sitzung = teilnahme.learning_session
    if not sitzung.ist_offen:
        request.session.pop(SCHLUESSEL_TEILNAHME, None)
        return render(request, "core/start.html", {
            "fehler": "Die Sitzung ist beendet. Alles, was du eingegeben hast, ist geloescht.",
        })
    if not sitzung.ist_musik:
        return redirect("tutoring:chat")
    if not teilnahme.hat_tier:
        return redirect("tutoring:tier_waehlen")

    dauern = musikstunde.erlaubte_dauern(sitzung.song_max_seconds)
    hoechst = dauern[-1]
    return render(request, "tutoring/musik.html", {
        "sitzung": sitzung,
        "teilnahme": teilnahme,
        # Die Masslinie wie auf /projekt/: Die laengste erlaubte Dauer ist
        # die volle Strecke.
        "dauern": [{"sekunden": d, "anteil": round(d * 100 / hoechst)} for d in dauern],
        # Vorgewaehlt ist die kuerzeste Dauer: Sie rechnet am schnellsten,
        # und in der Schlange warten alle anderen mit.
        "vorgabe_dauer": dauern[0],
        "text_max": musikstunde.TEXT_MAX,
        "gesang": dict(musikstunde.GESANGSSPRACHEN).get(sitzung.song_language, ""),
        # Der Textvorschlag: nur, wenn die Lehrperson ihn erlaubt hat. Das
        # Thema der Stunde ist vorbelegt, das Kind darf es aendern.
        "texthilfe": sitzung.song_text_help,
        "thema_vorgabe": sitzung.task_hint,
        "thema_max": musikstunde.THEMA_MAX,
        "vorschlaege": musikstunde.TEXTHILFE_HOECHSTENS,
        "eigen_max": musikstile.EIGEN_MAX,
        # Steht schon ohne Netz fest, dass nichts geht, steht gleich der Satz
        # da. Gefragt wird der Dienst erst vom Skript, damit die Seite nie
        # auf den Spark wartet.
        "hinweis": musik_oeffentlich.hinweis_ohne_netz(),
        **_liste_umgebung(teilnahme),
    })


@require_GET
def liste(request):
    """Nur die Liste der eigenen Lieder, damit das Skript sie nachladen kann."""
    teilnahme, _ = _teilnahme(request)
    if teilnahme is None:
        raise Http404
    return render(request, "tutoring/_musik_lieder.html", _liste_umgebung(teilnahme))


@require_GET
def stand(request):
    """Stile in Gruppen, Marken und das juengste laufende eigene Lied, fuer das Skript."""
    teilnahme, grund = _teilnahme(request)
    if teilnahme is None:
        return JsonResponse({"ok": False, "satz": grund}, status=403)
    werte = musik_oeffentlich.stand_holen()
    if not werte.get("ok"):
        return JsonResponse({"ok": False, "satz": NICHT_VERBUNDEN})
    stile = _stile(werte)
    letztes = teilnahme.lieder.filter(
        zustand__in=(Lied.WARTET, Lied.RECHNET)
    ).order_by("-angelegt_am", "-pk").first()
    return JsonResponse({
        "ok": True,
        # Tags, Tempo und Tonart bleiben im Server.
        "stile": [{k: s[k] for k in ("name", "titel", "beschreibung", "gruppe")}
                  for s in stile],
        "gruppen": musikstile.gruppen(stile),
        "marken": werte["marken"],
        "letztes": ({"auftrag": letztes.auftrag, **_adressen(letztes)}
                    if letztes else None),
    })


@require_POST
def lied(request):
    """Ein Lied anlegen. Jede Grenze wird hier geprueft, bevor der Spark etwas sieht."""
    teilnahme, grund = _teilnahme(request)
    if teilnahme is None:
        return _nein(grund, 403)
    sitzung = teilnahme.learning_session
    p = request.POST

    erlaubt = musikstunde.erlaubte_dauern(sitzung.song_max_seconds)
    sekunden = _ganzzahl(p.get("sekunden"))
    if sekunden not in erlaubt:
        return _nein(f"Die Dauer ist in dieser Stunde höchstens {erlaubt[-1]} Sekunden.")

    text = (p.get("lyrics") or "").replace("\r\n", "\n").strip()
    if len(text) > musikstunde.TEXT_MAX:
        return _nein(TEXT_ZU_LANG)
    if not musik_oeffentlich.text_erlaubt(text):
        # Nicht vertont und nicht gespeichert, aber die Lehrperson soll es
        # sehen: Die Ampel dieses Tieres wird rot, wie bei einem
        # Schimpfwort in einer Aufgabe.
        teilnahme.einstufung_merken(pruefung.ROT)
        sitzung.beruehren()
        return _nein(TEXT_ABGELEHNT)

    werte = musik_oeffentlich.stand_holen()
    if not werte.get("ok"):
        return _nein(NICHT_VERBUNDEN, 503)
    # Tags, Tempo und Tonart kommen aus dem Katalog im Server, nicht aus
    # dem Browser: Sonst waere das Tag-Feld ein zweiter, ungepruefter
    # Liedtext. Das freie Feld ist der einzige Text des Kindes in den Tags,
    # und der wird geprueft wie der Liedtext.
    stil = musikstile.finden(_stile(werte), p.get("stil", ""))
    if stil is None:
        return _nein(STIL_FEHLT)
    eigen = musikstile.eigen_bereinigen(p.get("eigener_stil"))
    if stil["name"] == musikstile.EIGEN and not eigen:
        return _nein(EIGEN_FEHLT)
    if eigen and not musik_oeffentlich.text_erlaubt(eigen):
        teilnahme.einstufung_merken(pruefung.ROT)
        sitzung.beruehren()
        return _nein(STIL_ABGELEHNT)
    tags = musikstile.tags_bauen(stil, eigen, sitzung.song_language,
                                 werte.get("tags_max"), mit_gesang=bool(text))

    # Die Ampel fuer die Lehrperson, ueber alles, was das Kind geschrieben
    # hat. Vor der Sperre unten, weil sie bis zu einige Sekunden dauert und
    # waehrenddessen keine Zeile gesperrt sein soll.
    ampel, ampel_grund = pruefung.einstufen(
        text + (f"\n(Stil: {eigen})" if eigen else ""))

    # Die Grenze je Kind unter einer Zeilensperre auf der Teilnahme: Ein
    # doppelter Fingertipp schickt zwei Anfragen, und beide saehen sonst
    # "noch eines frei". Auf PostgreSQL wartet die zweite, bis die erste
    # ihr Lied eingetragen hat.
    with transaction.atomic():
        Participation.objects.select_for_update().filter(pk=teilnahme.pk).first()
        if _gezaehlt(teilnahme) >= sitzung.songs_per_child:
            anzahl = sitzung.songs_per_child
            return _nein(
                f"Du hast schon {anzahl} Lied{'er' if anzahl != 1 else ''} gemacht. "
                "Mehr gehen in dieser Stunde nicht.", 429,
            )
        daten = {
            "tags": tags,
            "lyrics": text,
            "sekunden": sekunden,
            "bpm": stil["bpm"],
            "tonart": stil["tonart"],
            "takt": stil["takt"],
            "sprache": sitzung.song_language,
            "fassung": musikstunde.FASSUNG,
            "kennzeichen": sitzung.log_key,
        }
        daten = {k: v for k, v in daten.items() if v not in ("", None)}
        antwort = musik.lied_anlegen(daten)
        if not antwort.ok:
            if antwort.code == 400 and antwort.satz:
                return _nein(antwort.satz)
            return _nein(NICHT_VERBUNDEN, 503)
        kennung = str(antwort.inhalt.get("auftrag", ""))
        if not musik.KENNUNG.match(kennung):
            return _nein(NICHT_VERBUNDEN, 503)
        zustand = antwort.inhalt.get("zustand") or Lied.WARTET
        neu = Lied.objects.create(
            participation=teilnahme, auftrag=kennung,
            stil=musikstile.anzeigename(stil, eigen),
            text=text, sekunden=sekunden, sprache=sitzung.song_language,
            zustand=zustand if zustand in dict(Lied.ZUSTAENDE) else Lied.WARTET,
            flag=ampel, flag_reason=ampel_grund,
        )

    teilnahme.einstufung_merken(ampel)
    sitzung.beruehren()
    return JsonResponse({
        "ok": True,
        "auftrag": kennung,
        "zustand": neu.zustand,
        "position": _ganzzahl(antwort.inhalt.get("position")),
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        "erwartung_s": musik_zeit.erwartung(sekunden, musikstunde.FASSUNG),
        **_adressen(neu),
    })


@require_POST
def text(request):
    """Ein Textvorschlag vom Spark fuer das Textfeld des Kindes.

    Was hier geprueft wird, bevor das Sprachmodell etwas sieht: die
    Erlaubnis der Lehrperson (sonst 403), die Dauer (sie bestimmt die
    Laenge), das Thema (durch text_erlaubt, mit roter Ampel wie ein
    Liedtext, denn das hat das Kind geschrieben) und der Zaehler je
    Teilnahme in der Browsersitzung. Was das Modell liefert, wird bereinigt
    und noch einmal durch text_erlaubt geschickt: Ein gesperrter Vorschlag
    wird nicht gezeigt, ohne Ampel, weil das Kind daran nichts getan hat.
    """
    teilnahme, grund = _teilnahme(request)
    if teilnahme is None:
        return _nein(grund, 403)
    sitzung = teilnahme.learning_session
    if not sitzung.song_text_help:
        return _nein(TEXTHILFE_AUS, 403, noch=0)
    p = request.POST

    erlaubt = musikstunde.erlaubte_dauern(sitzung.song_max_seconds)
    sekunden = _ganzzahl(p.get("sekunden"))
    if sekunden not in erlaubt:
        return _nein(f"Die Dauer ist in dieser Stunde höchstens {erlaubt[-1]} Sekunden.")

    thema = _einzeilig(p.get("thema"), musikstunde.THEMA_MAX) or (sitzung.task_hint or "").strip()
    if not thema:
        return _nein(THEMA_FEHLT)
    if not musik_oeffentlich.text_erlaubt(thema):
        teilnahme.einstufung_merken(pruefung.ROT)
        sitzung.beruehren()
        return _nein(TEXT_ABGELEHNT)

    zaehler = request.session.get(musikstunde.TEXTHILFE_SITZUNGSSCHLUESSEL)
    if not isinstance(zaehler, dict):
        zaehler = {}
    schluessel = str(teilnahme.pk)
    bisher = zaehler.get(schluessel, 0)
    if not isinstance(bisher, int) or bisher >= musikstunde.TEXTHILFE_HOECHSTENS:
        return _nein(ZU_VIELE_VORSCHLAEGE, 429, noch=0)

    system, frage = musikstunde.textprompt(
        sitzung.song_language, sitzung.age_group, sekunden, thema)
    try:
        roh, _ = antwort_holen_sync(system, frage, max_tokens=600)
    except SparkNichtErreichbar:
        logger.warning("Musikstunde: Spark fuer den Textvorschlag nicht erreichbar.")
        return _nein(SPARK_SCHWEIGT, 503)

    # Gezaehlt wird jeder Aufruf, der am Spark angekommen ist, auch einer,
    # dessen Ergebnis unten verworfen wird: Die Rechenzeit ist verbraucht.
    zaehler[schluessel] = bisher + 1
    request.session[musikstunde.TEXTHILFE_SITZUNGSSCHLUESSEL] = zaehler
    noch = musikstunde.TEXTHILFE_HOECHSTENS - zaehler[schluessel]
    sitzung.beruehren()

    werte = musik_oeffentlich.stand_holen()
    marken = werte["marken"] if werte.get("ok") else [m.lower() for m in musik.MARKEN_VORGABE]
    vorschlag = musikstunde.text_bereinigen(roh, marken, musikstunde.zeichen_grenze(sekunden))
    if not vorschlag or not musik_oeffentlich.text_erlaubt(vorschlag):
        # Kein Fehler des Kindes: ruhiger Satz, Zaehler zaehlt, keine Ampel.
        return _nein(VORSCHLAG_NICHTS, 200, noch=noch)
    return JsonResponse({"ok": True, "text": vorschlag, "noch": noch})


@require_GET
def auftrag(request, kennung):
    """Stand eines eigenen Liedes: Warteposition, Restzeit, fertig."""
    lied_ = _eigenes_lied(request, kennung)
    antwort = musik.auftrag(kennung)
    if antwort.code == 404:
        _zustand_merken(lied_, Lied.WEG)
        return JsonResponse({"ok": False, "weg": True, "grund": NICHT_MEHR_DA})
    if not antwort.ok:
        return JsonResponse({"ok": False, "grund": NICHT_VERBUNDEN})
    zustand = antwort.inhalt.get("zustand")
    if zustand in dict(Lied.ZUSTAENDE):
        _zustand_merken(lied_, zustand)
    # Fuer den Fortschrittsbalken: die Erwartung fuer dieses Lied, und aus
    # jedem fertigen Lied der neue Erfahrungswert (core/musik_zeit.py).
    if zustand == Lied.FERTIG:
        musik_zeit.merken(antwort.inhalt.get("dauer_s"), lied_.sekunden, musikstunde.FASSUNG)
    return JsonResponse({
        "ok": True,
        "zustand": zustand,
        "position": _ganzzahl(antwort.inhalt.get("position")),
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        "erwartung_s": musik_zeit.erwartung(lied_.sekunden, musikstunde.FASSUNG),
        "dauer_s": antwort.inhalt.get("dauer_s"),
        # Die Meldung des Dienstes kann technisch sein und Teile des Auftrags
        # nennen; das Kind bekommt einen eigenen Satz.
        "fehler": NICHT_GELUNGEN if zustand == Lied.FEHLER else "",
        "datei": _adressen(lied_)["datei"] if zustand == Lied.FERTIG else "",
    })


def _zustand_merken(lied_, zustand):
    if lied_.zustand != zustand:
        lied_.zustand = zustand
        Lied.objects.filter(pk=lied_.pk).update(zustand=zustand)


@require_GET
def datei(request, kennung):
    """Die MP3 eines eigenen Liedes, vom Spark durchgereicht."""
    _eigenes_lied(request, kennung)
    return musik_oeffentlich.datei_antwort(kennung, NICHT_MEHR_DA)


# --- Fuer die Lehrperson ----------------------------------------------------

@login_required
@require_GET
def lehrperson_datei(request, code, lied_id):
    """Die MP3 eines Liedes, nur fuer die Lehrperson DIESER Sitzung.

    Die Pruefung laeuft ueber die Sitzung und die Lehrperson, nicht ueber
    die Kennung am Dienst: Eine Lehrperson soll mit einer erratenen oder
    weitergegebenen Kennung kein Lied einer anderen Klasse hoeren koennen.
    """
    sitzung = get_object_or_404(LearningSession, code=code, teacher=request.user)
    lied_ = get_object_or_404(Lied, pk=lied_id, participation__learning_session=sitzung)
    if not musik.KENNUNG.match(lied_.auftrag):
        raise Http404
    return musik_oeffentlich.datei_antwort(lied_.auftrag, NICHT_MEHR_DA)
