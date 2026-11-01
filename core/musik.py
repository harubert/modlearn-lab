"""Der Musikdienst am Spark: Stile, Grenzen, Auftraege, Dateien.

Der Dienst (Port 8011, nur im Tailnet) ist eine Schicht ueber ComfyUI und
ACE-Step 1.5, die die Spark-Betreuung am 12.10.2026 aufgesetzt hat. Die App
ist der einzige Weg dorthin: Der Browser erreicht den Spark nie, er sieht nur
unsere Ansichten unter /labor/musik/.

Was dieser Baustein zusagt:

- Nichts hier wirft nach aussen. Jede Abfrage liefert entweder die Antwort
  des Dienstes oder ein Ergebnis mit einem Satz, den man einer Lehrperson
  zeigen kann. Eine Testecke, die mit 500 abbricht, testet nichts.
- Das Geheimnis kommt aus derselben Datei wie beim Broker und wird dort
  gelesen (plan.broker.geheimnis). Zwei Leser derselben Datei waeren zwei
  Stellen, an denen sich das Verhalten bei fehlender Datei auseinanderlebt.
- /gesundheit geht ohne Geheimnis. Damit laesst sich auch ohne Datei sagen,
  ob der Dienst ueberhaupt antwortet - die zwei Fehler sehen fuer die
  Lehrperson gleich aus, haben aber verschiedene Zustaendige.
"""

import hashlib
import hmac
import logging
import re
from urllib.parse import urlencode

import httpx
from django.conf import settings

from plan.broker import geheimnis

logger = logging.getLogger(__name__)

# Auftragskennungen kommen vom Dienst und landen in unseren Adressen. Mehr
# als diese Zeichen braucht keine Kennung, und so kann keine einen Pfad
# zusammensetzen ("../datei").
KENNUNG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Wenn der Dienst keine Marken fuer den Liedtext nennt. Die Schnittstelle sagt
# dazu bisher nichts; ACE-Step selbst ist mit englischen Marken ([verse],
# [chorus]) trainiert. Sobald /grenzen oder /stile "marken" liefert, gilt das.
# Gemessen von der Spark-Betreuung (12.10.2026): die added_tokens des Lyrics-
# Tokenizers. Kleinschreibung zaehlt (kein Normalisierer): "[Verse]" waere
# gewoehnlicher Text, "[Strophe]" wuerde mitgesungen.
MARKEN_VORGABE = ["[intro]", "[verse]", "[pre-chorus]", "[chorus]", "[hook]",
                  "[bridge]", "[break]", "[inst]", "[solo]", "[outro]"]


class Antwort:
    """Ergebnis einer Abfrage: ok, Statuscode, Inhalt, und ein Satz.

    `satz` ist nur gesetzt, wenn etwas nicht geklappt hat, und ist so
    formuliert, dass er unveraendert auf der Seite stehen kann.
    """

    def __init__(self, ok, code=0, inhalt=None, satz=""):
        self.ok = ok
        self.code = code
        self.inhalt = inhalt if isinstance(inhalt, dict) else {}
        self.satz = satz


def _adresse(pfad):
    return settings.MUSIK_URL.rstrip("/") + pfad


def geheimnis_fehlt_satz():
    return ("Der Musikdienst ist noch nicht verbunden: Die Geheimnisdatei "
            f"{settings.SPARK_BROKER_SECRET_DATEI} fehlt.")


def antwortet_nicht_satz():
    return "Der Musikdienst ist noch nicht verbunden: Er antwortet nicht."


def _holen(pfad, methode="GET", daten=None, frist=10.0, mit_geheimnis=True):
    kopf = {}
    if mit_geheimnis:
        wert = geheimnis()
        if not wert:
            return Antwort(False, satz=geheimnis_fehlt_satz())
        kopf["X-Broker-Secret"] = wert
    if not settings.MUSIK_URL:
        return Antwort(False, satz="Für den Musikdienst ist keine Adresse eingetragen.")
    try:
        with httpx.Client(timeout=frist) as client:
            antwort = client.request(methode, _adresse(pfad), headers=kopf, json=daten)
        inhalt = antwort.json() if antwort.content else {}
    except (httpx.HTTPError, ValueError) as fehler:
        # Pfad und Fehlerart ja, Inhalt nie: Im Rumpf steht ein Liedtext.
        logger.warning("Musikdienst: %s %s nicht erreichbar (%s).",
                       methode, pfad, type(fehler).__name__)
        return Antwort(False, satz=antwortet_nicht_satz())
    if antwort.status_code == 401 or antwort.status_code == 403:
        return Antwort(False, antwort.status_code, inhalt,
                       "Der Musikdienst lehnt unser Geheimnis ab.")
    if not isinstance(inhalt, dict):
        return Antwort(False, antwort.status_code,
                       satz="Der Musikdienst hat unverständlich geantwortet.")
    ok = 200 <= antwort.status_code < 300
    satz = ""
    if not ok:
        satz = str(inhalt.get("grund") or f"Der Musikdienst antwortet {antwort.status_code}.")
    return Antwort(ok, antwort.status_code, inhalt, satz)


def gesundheit():
    """Antwortet der Dienst? Ohne Geheimnis, kurze Frist."""
    return _holen("/gesundheit", frist=4.0, mit_geheimnis=False)


def stile(frist=10.0):
    """Die Stilvorlagen als Liste von Dicts, oder leer.

    `frist` ist fuer die oeffentliche Ecke kuerzer: Dort darf ein Dienst, der
    nicht antwortet, keinen Besucher lange warten lassen.
    """
    antwort = _holen("/stile", frist=frist)
    if not antwort.ok:
        return [], antwort
    # Der Dienst darf die Liste nackt oder unter "stile" liefern; die
    # Beschreibung sagt "sechs Stilvorlagen", nicht in welcher Huelle.
    liste = antwort.inhalt.get("stile", antwort.inhalt)
    if isinstance(liste, dict):
        liste = [dict(wert, name=wert.get("name", schluessel))
                 for schluessel, wert in liste.items() if isinstance(wert, dict)]
    if not isinstance(liste, list):
        liste = []
    return [s for s in liste if isinstance(s, dict)], antwort


def grenzen(frist=10.0):
    return _holen("/grenzen", frist=frist)


def lied_anlegen(daten):
    """POST /lied. Erwartet 202; 400 traegt einen `grund`."""
    return _holen("/lied", "POST", daten, frist=15.0)


def auftrag(kennung):
    return _holen(f"/auftrag/{kennung}")


def entfernen(kennung, frist=10.0):
    return _holen(f"/auftrag/{kennung}", "DELETE", frist=frist)


def auftraege_entfernen(kennzeichen, frist=10.0):
    """DELETE /auftraege?kennzeichen=... - alle Auftraege eines Kennzeichens.

    Fuer die Musikstunde: Beim Beenden und beim Verfall gehen alle Lieder
    einer Sitzung auf einmal. Die Antwort `{entfernt, datei_entfernt}` wertet
    der Aufrufer aus (tutoring.musikstunde); hier wird nichts angenommen.
    """
    return _holen("/auftraege?" + urlencode({"kennzeichen": kennzeichen}),
                  "DELETE", frist=frist)


def datei(kennung):
    """Die MP3 als Strom: (code, inhaltsart, laenge, stueckweise) oder None.

    Der Client bleibt offen, bis der letzte Block durch ist, und schliesst
    sich danach selbst. Ein Lied von vier Minuten sind einige Megabyte; die
    ganz in den Speicher zu holen, waere spaeter mit einer ganzen Klasse unnoetig.
    """
    wert = geheimnis()
    if not wert or not settings.MUSIK_URL:
        return None
    client = httpx.Client(timeout=30.0)
    try:
        anfrage = client.build_request(
            "GET", _adresse(f"/datei/{kennung}"), headers={"X-Broker-Secret": wert}
        )
        antwort = client.send(anfrage, stream=True)
    except httpx.HTTPError as fehler:
        client.close()
        logger.warning("Musikdienst: Datei nicht erreichbar (%s).", type(fehler).__name__)
        return None
    if antwort.status_code != 200:
        code = antwort.status_code
        antwort.close()
        client.close()
        return code, "", None, None

    def stueckweise():
        try:
            yield from antwort.iter_bytes(64 * 1024)
        except httpx.HTTPError as fehler:
            # Der Kopf ist schon raus; mehr als abbrechen geht nicht mehr.
            logger.warning("Musikdienst: Datei abgerissen (%s).", type(fehler).__name__)
        finally:
            antwort.close()
            client.close()

    return (200, antwort.headers.get("content-type", "audio/mpeg"),
            antwort.headers.get("content-length"), stueckweise())


def kennzeichen(benutzer):
    """"labor-" und ein Hash des Benutzernamens, nie der Name selbst.

    Mit dem SECRET_KEY verschluesselt (HMAC), nicht bloss gehasht: Die
    Benutzernamen der Lehrpersonen sind eine kleine, erratbare Menge, ein
    blanker SHA-256 liesse sich in Sekunden zurueckrechnen.
    """
    wert = hmac.new(settings.SECRET_KEY.encode("utf-8"),
                    benutzer.get_username().encode("utf-8"),
                    hashlib.sha256).hexdigest()[:24]
    return "labor-" + wert


def fassungen(grenzen_inhalt):
    """Die Fassungen als Liste [{name, sekunden_je_minute}], xl zuerst.

    /grenzen nennt sie mit `sekunden_je_minute`, die Huelle (Liste oder
    Woerterbuch je Name) ist nicht festgeschrieben. Hier wird sie einmal
    eingeebnet, damit Vorlage und Skript nur eine Form kennen.
    """
    roh = grenzen_inhalt.get("fassungen") or {}
    liste = []
    if isinstance(roh, dict):
        for name, wert in roh.items():
            if isinstance(wert, dict):
                liste.append({"name": str(name), **wert})
            elif isinstance(wert, (int, float)):
                liste.append({"name": str(name), "sekunden_je_minute": wert})
    elif isinstance(roh, list):
        liste = [dict(f) for f in roh if isinstance(f, dict) and f.get("name")]
    if not liste:
        # Die Werte aus der Ankuendigung vom 12.10., damit die Schaetzung
        # nicht verschwindet, nur weil /grenzen sie anders verpackt.
        liste = [{"name": "xl", "sekunden_je_minute": 20},
                 {"name": "klein", "sekunden_je_minute": 9}]
    liste.sort(key=lambda f: (f["name"] != "xl", f["name"]))
    return liste


def marken(stil_liste, grenzen_inhalt):
    """Die Liedtext-Marken, die der Dienst nennt, sonst MARKEN_VORGABE."""
    for quelle in [grenzen_inhalt, *stil_liste]:
        werte = quelle.get("marken") if isinstance(quelle, dict) else None
        if isinstance(werte, list) and werte:
            return [str(w) for w in werte]
    return list(MARKEN_VORGABE)
