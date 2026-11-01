"""Die Musik-KI zum Ausprobieren, ganz unten auf /projekt/, ohne Anmeldung.

Der Auftraggeber will die Seite teilen koennen: "einfach rein". Damit steht
ein Rechenauftrag am Spark jedem offen, der die Adresse kennt, unter einer
Adresse der PH. Deshalb liegen hier die Schutzgelaender, alle im Server und
keines im Skript (CLAUDE.md: ein Systemprompt ist eine Bitte, und ein
Skript im Browser ist erst recht eine):

1. Hoechstens LIEDER_JE_SITZUNG Lieder je Sitzung und LIEDER_JE_ADRESSE je
   IP-Adresse in der Stunde. Die Adresse wird nur als HMAC gemerkt.
2. Steht die Schlange am Spark schon lang, wird nichts Neues angenommen.
3. Der Liedtext geht durch den deterministischen Boden der Aufgabenhilfe
   und durch eine kurze Sperrliste. Ein Modellaufruf waere hier mehr
   Rechenzeit am Spark fuer jeden Besucher, und ein Boden ohne Modell
   kann nicht ausfallen.
4. Das Kennzeichen am Dienst ist ein HMAC der Sitzung, nie die Sitzung.
5. Jedes Lied wird nach einer Stunde geloescht (der Dienst selbst raeumt
   nach 8 Stunden ab, das ist nur das Netz darunter).
6. Fehlt das Geheimnis oder schweigt der Dienst, steht ein ruhiger Satz da,
   und die Landing Page wartet nie auf den Spark: Sie selbst fragt ihn gar
   nicht, das Skript holt Stile und Marken danach ueber stand().

Die Zaehler liegen im Django-Cache. settings.py setzt keinen, also gilt der
LocMem-Standard je Prozess: Bei zwei Uvicorn-Arbeitern kann eine Grenze im
unguenstigsten Fall doppelt so weit reichen. Fuer eine Probierecke reicht
das; wird es mehr, gehoert ein gemeinsamer Cache (Redis, Datenbank) in die
Einstellungen, und hier aendert sich nichts.
"""

import hashlib
import hmac
import logging
import re
import time

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from plan.broker import geheimnis
from tutoring import pruefung

from . import musik, musik_zeit

logger = logging.getLogger(__name__)

# --- Grenzen -----------------------------------------------------------------
LIEDER_JE_SITZUNG = 3
LIEDER_JE_ADRESSE = 6
FENSTER_S = 3600
# Nach dieser Zeit loescht die App ein oeffentliches Lied am Dienst.
LEBENSDAUER_S = 3600
# Was der Dienst nach verfall_stunden selbst loescht, braucht kein DELETE mehr.
VERFALL_DIENST_S = 8 * 3600
# Mehr als so viele vor einem in der Schlange: kein neuer oeffentlicher Auftrag.
SCHLANGE_HOECHSTENS = 5
# So lange gilt eine gemeldete lange Schlange, ohne neu zu fragen. Sonst
# wuerde jeder Klick einen Auftrag anlegen und gleich wieder zurueckziehen.
SCHLANGE_SPERRE_S = 120
TEXT_MAX = 400
DAUERN = (30, 60)
SPRACHEN = ("de", "en")
# Immer die kleine Fassung: etwa 9 statt 20 Sekunden Rechenzeit je
# Musikminute, damit eine Probe die Lehrpersonen im Labor nicht aufhaelt.
FASSUNG = "klein"
STILE_HOECHSTENS = 6
# Stile und Grenzen: kurze Frist, langer Zwischenspeicher. Ein Fehlschlag
# wird nur kurz gemerkt, damit ein wieder erreichbarer Dienst bald auftaucht.
STAND_FRIST_S = 2.0
STAND_GUELTIG_S = 600
STAND_FEHLER_S = 60
# Aufraeumen kostet je Lied einen Aufruf am Spark. Hoechstens so viele je
# Anfrage, mit kurzer Frist, damit kein Besucher die Altlast anderer abwartet.
AUFRAEUMEN_JE_AUFRUF = 3
AUFRAEUMEN_FRIST_S = 2.0
# Das Verzeichnis aller oeffentlichen Lieder (Kennung -> Zeit) hat eine
# Obergrenze, falls der Dienst lange nicht erreichbar ist und nichts abgeht.
REGISTER_HOECHSTENS = 500

SITZUNGSSCHLUESSEL = "musik_oeffentlich"
STAND_SCHLUESSEL = "musik_oe:stand"
SCHLANGE_SCHLUESSEL = "musik_oe:schlange_voll"
REGISTER_SCHLUESSEL = "musik_oe:register"

# --- Saetze --------------------------------------------------------------------
NICHT_VERBUNDEN = "Die Musik-KI ist gerade nicht verbunden."
SCHLANGE_VOLL = "Gerade sind viele Lieder in Arbeit – bitte in ein paar Minuten noch einmal."
ZU_VIELE_SITZUNG = ("Aus diesem Browser sind in der letzten Stunde schon drei Lieder "
                    "gekommen. Bitte etwas später noch einmal.")
ZU_VIELE_ADRESSE = ("Aus diesem Netz sind in der letzten Stunde schon sechs Lieder "
                    "gekommen. Bitte etwas später noch einmal.")
TEXT_ABGELEHNT = ("Im Liedtext steht ein Wort, das hier nicht vertont wird. "
                  "Bitte den Text anders formulieren.")
TEXT_ZU_LANG = f"Der Liedtext darf hier höchstens {TEXT_MAX} Zeichen lang sein."
DAUER_FALSCH = "Die Dauer ist hier 30 oder 60 Sekunden."
SPRACHE_FALSCH = "Die Sprache ist Deutsch oder Englisch."
STIL_FEHLT = "Bitte einen der Stile wählen."
NICHT_MEHR_DA = "Dieses Lied ist nicht mehr da. Lieder werden nach einer Stunde gelöscht."

# Hass und Sexuelles, deutsch und englisch. Kurz und eindeutig wie die
# Schimpfwoerter in tutoring/pruefung.py: Eine lange Liste faengt vor allem
# harmlose Lieder ab ("dick" ist im Deutschen kein Schimpfwort). Was hier
# fehlt und trotzdem durchgeht, steht hoechstens eine Stunde am Spark und
# ist nur in der Sitzung abspielbar, die es geschrieben hat.
_SPERRLISTE = (
    # Hass
    r"heil\s+hitler", r"sieg\s+heil", r"\bnigg", r"\bneger", r"kanake",
    r"schwuchtel", r"\bfaggot", r"\bkike\b", r"\bretard", r"untermensch",
    r"vergas", r"ausl(ä|ae)nder\s+raus", r"white\s+power", r"gas\s+the\b",
    # Sexuelles
    r"\bsex", r"\bporn", r"\bfuck", r"vergewaltig", r"\brape[ds]?\b",
    r"blowjob", r"\bnudes?\b", r"\bwhore", r"\bhure\b", r"\bslut",
    r"\bcunt", r"\bpussy", r"\bpenis", r"\bvagina", r"\btitten",
    r"\bboobs?\b", r"\bdildo", r"\bcum\b",
)
_SPERRMUSTER = re.compile("|".join(_SPERRLISTE), re.IGNORECASE)


def text_erlaubt(text):
    """Kein Schimpfwort (Boden der Aufgabenhilfe) und nichts aus der Sperrliste."""
    if pruefung.deterministischer_boden(text) is not None:
        return False
    return not _SPERRMUSTER.search(text or "")


# --- Kleine Helfer -------------------------------------------------------------

def _hmac(wert, laenge=24):
    """Mit dem SECRET_KEY verschluesselt, nicht bloss gehasht: IP-Adressen
    sind eine kleine, durchprobierbare Menge."""
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), str(wert).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:laenge]


def _ip(request):
    """Erster Eintrag von X-Forwarded-For, sonst REMOTE_ADDR.

    Caddy setzt X-Forwarded-For selbst und uebernimmt den Kopf eines
    Besuchers nicht, solange keine trusted_proxies eingetragen sind; der
    erste Eintrag ist also der Besucher.
    """
    weiter = request.META.get("HTTP_X_FORWARDED_FOR", "")
    erste = weiter.split(",")[0].strip()
    return erste or request.META.get("REMOTE_ADDR", "") or "unbekannt"


def _ganzzahl(wert):
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return None


def _nein(satz, status=400):
    return JsonResponse({"ok": False, "grund": satz}, status=status)


def _zeitstempel(schluessel):
    jetzt = time.time()
    return [t for t in (cache.get(schluessel) or []) if jetzt - t < FENSTER_S]


def _voll(schluessel, hoechstens):
    return len(_zeitstempel(schluessel)) >= hoechstens


def _zaehlen(schluessel):
    stempel = _zeitstempel(schluessel)
    stempel.append(time.time())
    cache.set(schluessel, stempel, FENSTER_S)


def kennzeichen(sitzungsschluessel):
    """"oeffentlich-" und ein HMAC der Sitzung. Damit kann der Dienst die
    Auftraege einer Sitzung zusammenfassen, ohne die Sitzung zu kennen."""
    return "oeffentlich-" + _hmac(sitzungsschluessel)


# --- Eigene Lieder in der Sitzung ---------------------------------------------

def _eigene(request):
    """Die Lieder dieser Sitzung, die juenger als LEBENSDAUER_S sind.

    Nur lesen: Eine Sitzung ohne Keks wird dabei nicht angelegt und nicht
    aus der Datenbank geholt.
    """
    lieder = request.session.get(SITZUNGSSCHLUESSEL)
    if not isinstance(lieder, list):
        return []
    grenze = time.time() - LEBENSDAUER_S
    return [l for l in lieder if isinstance(l, dict) and (l.get("angelegt") or 0) > grenze]


def _eigenes(request, kennung):
    """Nur eigene Lieder, sonst 404, auch fuer fremde und abgelaufene."""
    if not musik.KENNUNG.match(kennung):
        raise Http404
    for lied in _eigene(request):
        if lied.get("auftrag") == kennung:
            return lied
    raise Http404


# --- Aufraeumen nach einer Stunde -------------------------------------------

def _registrieren(kennung):
    register = cache.get(REGISTER_SCHLUESSEL) or {}
    register[kennung] = time.time()
    if len(register) > REGISTER_HOECHSTENS:
        aelteste = sorted(register, key=register.get)[:len(register) - REGISTER_HOECHSTENS]
        for k in aelteste:
            register.pop(k, None)
    cache.set(REGISTER_SCHLUESSEL, register, None)


def altlieder_aufraeumen():
    """Oeffentliche Lieder, die aelter als eine Stunde sind, am Dienst loeschen.

    Ueber alle Sitzungen, nicht nur die eigene: Wer nach dem Ausprobieren
    nie wiederkommt, dessen Lied soll trotzdem nach einer Stunde weg sein.
    Laeuft bei jedem Abruf von stand() und bei jedem neuen Auftrag. Das
    Verzeichnis liegt im Cache; zwei gleichzeitige Anfragen koennen dasselbe
    Lied zweimal loeschen wollen, das zweite DELETE bekommt dann ein 404.
    """
    register = cache.get(REGISTER_SCHLUESSEL) or {}
    if not register:
        return
    jetzt = time.time()
    faellig = sorted((t, k) for k, t in register.items() if jetzt - t > LEBENSDAUER_S)
    if not faellig:
        return
    for t, k in faellig:
        if jetzt - t > VERFALL_DIENST_S:
            register.pop(k, None)
    for t, k in [(t, k) for t, k in faellig if k in register][:AUFRAEUMEN_JE_AUFRUF]:
        antwort = musik.entfernen(k, frist=AUFRAEUMEN_FRIST_S)
        if antwort.code == 404:
            register.pop(k, None)
        elif antwort.ok and antwort.inhalt.get("entfernt") is True:
            register.pop(k, None)
            if antwort.inhalt.get("datei_entfernt") is not True:
                # Auswerten, nicht annehmen (CLAUDE.md, 12.10.): laut ins
                # Journal, nach 8 Stunden raeumt der Dienst die Datei selbst.
                logger.warning("Musik oeffentlich: Auftrag geloescht, Datei nicht gemeldet "
                               "(datei_entfernt=%r).", antwort.inhalt.get("datei_entfernt"))
        else:
            # Der Dienst schweigt oder lehnt ab: beim naechsten Mal wieder,
            # und jetzt nicht weiter warten.
            logger.warning("Musik oeffentlich: Aufraeumen nicht moeglich (%s).",
                           antwort.code or "keine Antwort")
            break
    cache.set(REGISTER_SCHLUESSEL, register, None)


# --- Stile und Marken ---------------------------------------------------------

def stand_holen():
    """Stile und Marken aus dem Zwischenspeicher, sonst vom Dienst (2 s Frist).

    Oeffentlich, weil die Musikstunde (tutoring/musik_views.py) dieselben
    Stile und Marken braucht und denselben Zwischenspeicher nutzen soll:
    Zwei Stellen, die /stile fragen, waeren zwei Stellen, an denen ein
    stummer Dienst Besucher aufhaelt.
    """
    stand = cache.get(STAND_SCHLUESSEL)
    if stand is not None:
        return stand
    if not geheimnis() or not settings.MUSIK_URL:
        # Nicht merken: Legt Thomas die Datei ab, gilt sie beim naechsten Aufruf.
        return {"ok": False}
    stil_liste, antwort = musik.stile(frist=STAND_FRIST_S)
    grenzen = musik.grenzen(frist=STAND_FRIST_S) if antwort.ok else antwort
    stile = []
    for s in stil_liste:
        name = str(s.get("name") or "").strip()
        if name and len(stile) < STILE_HOECHSTENS:
            stile.append({
                "name": name[:80],
                "titel": str(s.get("titel") or name)[:80],
                "beschreibung": str(s.get("beschreibung") or "")[:200],
                "tags": str(s.get("tags") or ""),
                "bpm": _ganzzahl(s.get("bpm")),
                "tonart": str(s.get("tonart") or ""),
                "takt": str(s.get("takt") or ""),
            })
    if not antwort.ok or not grenzen.ok or not stile:
        stand = {"ok": False}
        cache.set(STAND_SCHLUESSEL, stand, STAND_FEHLER_S)
        return stand
    # Klein, wie der Lyrics-Tokenizer sie kennt; "[Verse]" waere Liedtext.
    marken = [m.lower() for m in musik.marken(stil_liste, grenzen.inhalt)]
    # tags_max braucht nur die Musikstunde (freies Stilfeld, tutoring/
    # musikstile.py); hier steht es, weil hier /grenzen gelesen wird.
    stand = {"ok": True, "stile": stile, "marken": marken,
             "tags_max": _ganzzahl(grenzen.inhalt.get("tags_max"))}
    cache.set(STAND_SCHLUESSEL, stand, STAND_GUELTIG_S)
    return stand


def hinweis_ohne_netz():
    """Fuer die Landing Page: der Satz, falls schon ohne Netz klar ist, dass
    nichts geht. Liest nur die Geheimnisdatei und den Zwischenspeicher, fragt
    nie den Dienst; ein leerer Satz heisst, das Skript fragt nach."""
    if not geheimnis() or not settings.MUSIK_URL:
        return NICHT_VERBUNDEN
    stand = cache.get(STAND_SCHLUESSEL)
    if stand is not None and not stand.get("ok"):
        return NICHT_VERBUNDEN
    return ""


def _adressen(kennung):
    return {
        "abfrage": reverse("musik_oe_auftrag", args=[kennung]),
        "datei": reverse("musik_oe_datei", args=[kennung]),
    }


# --- Ansichten ------------------------------------------------------------------

@require_GET
def stand(request):
    """Stile, Marken und das juengste eigene Lied, fuer das Skript der Seite."""
    altlieder_aufraeumen()
    werte = stand_holen()
    if not werte.get("ok"):
        return JsonResponse({"ok": False, "satz": NICHT_VERBUNDEN})
    eigene = _eigene(request)
    letztes = None
    if eigene:
        letztes = {"auftrag": eigene[0]["auftrag"], **_adressen(eigene[0]["auftrag"])}
    return JsonResponse({
        "ok": True,
        "stile": [{k: s[k] for k in ("name", "titel", "beschreibung")} for s in werte["stile"]],
        "marken": werte["marken"],
        "letztes": letztes,
    })


@require_POST
def lied(request):
    """Ein Lied anlegen. Jede Grenze wird hier geprueft, bevor der Spark etwas sieht."""
    altlieder_aufraeumen()
    p = request.POST

    sekunden = _ganzzahl(p.get("sekunden"))
    if sekunden not in DAUERN:
        return _nein(DAUER_FALSCH)
    sprache = p.get("sprache", "").strip()
    if sprache not in SPRACHEN:
        return _nein(SPRACHE_FALSCH)
    text = p.get("lyrics", "").replace("\r\n", "\n").strip()
    if len(text) > TEXT_MAX:
        return _nein(TEXT_ZU_LANG)
    if not text_erlaubt(text):
        return _nein(TEXT_ABGELEHNT)

    werte = stand_holen()
    if not werte.get("ok"):
        return _nein(NICHT_VERBUNDEN, 503)
    # Tags, Tempo und Tonart kommen aus der Stilvorlage im Server, nicht
    # aus dem Browser: Sonst waere das Tag-Feld ein zweiter, ungepruefter
    # Liedtext.
    stil = next((s for s in werte["stile"] if s["name"] == p.get("stil", "")), None)
    if stil is None:
        return _nein(STIL_FEHLT)

    if cache.get(SCHLANGE_SCHLUESSEL):
        return _nein(SCHLANGE_VOLL, 503)

    if not request.session.session_key:
        request.session.save()
    sitzung = request.session.session_key
    zaehler_sitzung = "musik_oe:s:" + _hmac(sitzung)
    zaehler_adresse = "musik_oe:a:" + _hmac(_ip(request))
    if _voll(zaehler_sitzung, LIEDER_JE_SITZUNG):
        return _nein(ZU_VIELE_SITZUNG, 429)
    if _voll(zaehler_adresse, LIEDER_JE_ADRESSE):
        return _nein(ZU_VIELE_ADRESSE, 429)

    daten = {
        "tags": stil["tags"],
        "lyrics": text,
        "sekunden": sekunden,
        "bpm": stil["bpm"],
        "tonart": stil["tonart"],
        "takt": stil["takt"],
        "sprache": sprache,
        "fassung": FASSUNG,
        "kennzeichen": kennzeichen(sitzung),
    }
    daten = {k: v for k, v in daten.items() if v not in ("", None)}
    antwort = musik.lied_anlegen(daten)
    if not antwort.ok:
        # Ein 400 traegt einen Grund, der auf der Seite stehen kann; alles
        # andere (Geheimnis, Netz, 5xx) ist fuer Besucher dasselbe.
        if antwort.code == 400 and antwort.satz:
            return _nein(antwort.satz)
        return _nein(NICHT_VERBUNDEN, 503)
    kennung = str(antwort.inhalt.get("auftrag", ""))
    if not musik.KENNUNG.match(kennung):
        return _nein(NICHT_VERBUNDEN, 503)

    position = _ganzzahl(antwort.inhalt.get("position"))
    if position is not None and position > SCHLANGE_HOECHSTENS:
        # Der Dienst nennt die Schlange erst mit dem Auftrag. Zu lang: den
        # Auftrag gleich zurueckziehen und eine Weile niemanden mehr hinein.
        cache.set(SCHLANGE_SCHLUESSEL, True, SCHLANGE_SPERRE_S)
        musik.entfernen(kennung, frist=AUFRAEUMEN_FRIST_S)
        return _nein(SCHLANGE_VOLL, 503)

    _zaehlen(zaehler_sitzung)
    _zaehlen(zaehler_adresse)
    _registrieren(kennung)
    eigene = [l for l in _eigene(request) if l.get("auftrag") != kennung]
    eigene.insert(0, {"auftrag": kennung, "angelegt": time.time()})
    request.session[SITZUNGSSCHLUESSEL] = eigene[:LIEDER_JE_SITZUNG * 2]

    return JsonResponse({
        "ok": True,
        "auftrag": kennung,
        "zustand": antwort.inhalt.get("zustand") or "wartet",
        "position": position,
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        # Fuer den Fortschrittsbalken: wie lange das eigene Lied rechnet.
        "erwartung_s": musik_zeit.erwartung(sekunden, FASSUNG),
        **_adressen(kennung),
    })


@require_GET
def auftrag(request, kennung):
    """Stand eines eigenen Liedes: Warteposition, Restzeit, fertig."""
    _eigenes(request, kennung)
    antwort = musik.auftrag(kennung)
    if antwort.code == 404:
        return JsonResponse({"ok": False, "weg": True, "grund": NICHT_MEHR_DA})
    if not antwort.ok:
        return JsonResponse({"ok": False, "grund": NICHT_VERBUNDEN})
    zustand = antwort.inhalt.get("zustand")
    position = _ganzzahl(antwort.inhalt.get("position"))
    if zustand == "wartet" and position is not None and position > SCHLANGE_HOECHSTENS:
        cache.set(SCHLANGE_SCHLUESSEL, True, SCHLANGE_SPERRE_S)
    # Der Dienst nennt zum Auftrag Laenge und Fassung; daraus die Erwartung
    # fuer den Balken, und aus jedem fertigen Lied der neue Erfahrungswert.
    sekunden = antwort.inhalt.get("sekunden")
    fassung = antwort.inhalt.get("fassung") or FASSUNG
    if zustand == "fertig":
        musik_zeit.merken(antwort.inhalt.get("dauer_s"), sekunden, fassung)
    return JsonResponse({
        "ok": True,
        "zustand": zustand,
        "position": position,
        "wartet_noch_s": antwort.inhalt.get("wartet_noch_s"),
        "erwartung_s": musik_zeit.erwartung(sekunden, fassung),
        "dauer_s": antwort.inhalt.get("dauer_s"),
        # Die Fehlermeldung des Dienstes kann technisch sein und Teile des
        # Auftrags nennen; Besucher bekommen einen eigenen Satz.
        "fehler": "Das Lied konnte nicht erzeugt werden." if zustand == "fehler" else "",
        "datei": reverse("musik_oe_datei", args=[kennung]) if zustand == "fertig" else "",
    })


@require_GET
def datei(request, kennung):
    """Die MP3 eines eigenen Liedes, vom Spark durchgereicht."""
    _eigenes(request, kennung)
    return datei_antwort(kennung)


def datei_antwort(kennung, nicht_mehr_da=NICHT_MEHR_DA):
    """Die MP3 als Antwort, vom Spark durchgereicht, oder ein ruhiger Satz.

    Ohne Pruefung, wem das Lied gehoert: Das hat der Aufrufer vorher zu
    erledigen. Die Musikstunde nutzt dieselbe Stelle fuer Kind und
    Lehrperson, jeweils nach der eigenen Pruefung.
    """
    ergebnis = musik.datei(kennung)
    if ergebnis is None:
        return HttpResponse(NICHT_VERBUNDEN, status=503, content_type="text/plain; charset=utf-8")
    code, art, laenge, stuecke = ergebnis
    if code != 200:
        return HttpResponse(nicht_mehr_da, status=404, content_type="text/plain; charset=utf-8")
    antwort = StreamingHttpResponse(stuecke, content_type=art or "audio/mpeg")
    if laenge:
        antwort["Content-Length"] = laenge
    antwort["Content-Disposition"] = "inline"
    antwort["Cache-Control"] = "private, no-store"
    return antwort
