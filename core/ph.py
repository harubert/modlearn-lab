"""Das Geheimnis zwischen Caddy und dieser Anwendung.

Caddy prueft die Anmeldung bei login.ph-vorarlberg.at (SAML gegen Microsoft
Entra) und schickt die angemeldete Person als X-Auth-Kopfzeilen weiter. Von
aussen entfernt Caddy jede X-Auth-Kopfzeile, faelschen geht also nicht.
Trotzdem wird das Geheimnis geprueft: Ein Caddy, der einmal falsch
konfiguriert ist, oder ein zweiter Weg zum Container (lokales Netz, ein
Nachbar-Container, der Port 8090 am Loopback) darf keine Person anmelden
koennen. Ein Systemprompt ist eine Bitte, eine Caddy-Regel auch; die Grenze
wird hier erzwungen.

Das Geheimnis kommt aus einer DATEI, nie aus der Umgebung: Umgebungsvariablen
stehen in 'docker inspect', in Djangos Fehlerseite bei DEBUG und in jedem
Kindprozess. Eine nur lesend eingebundene Datei steht nirgends. Der Inhalt
wird nie protokolliert und nie in eine Antwort geschrieben.
"""

import logging
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

# Gelesen wird einmal je Prozess. Der Schluessel ist der Pfad, damit die
# Pruefungen verschiedene Dateien einsetzen koennen, ohne hier aufzuraeumen.
_gelesen = {}
_gemeldet = set()


def proxy_geheimnis():
    """Das Geheimnis als Bytes, oder None, wenn der Weg abgeschaltet ist.

    Fehlt die Datei oder ist sie leer, gibt es kein Geheimnis und damit keine
    Anmeldung ueber das PH-Konto. Das ist kein Fehler, sondern der Zustand auf
    jedem Rechner ohne Caddy davor, etwa dem Entwicklungsrechner. Eine fehlende
    Datei wird deshalb nicht gemerkt: Legt die Serverbetreuung sie nachtraeglich
    an, greift sie beim naechsten Aufruf, ohne Neustart. Ein gelesenes
    Geheimnis bleibt bis zum Neustart; wer es tauscht, startet den Container neu.
    """
    pfad = str(getattr(settings, "PH_PROXY_SECRET_DATEI", "") or "")
    if not pfad:
        return None
    if pfad in _gelesen:
        return _gelesen[pfad]

    try:
        inhalt = Path(pfad).read_bytes().strip()
    except OSError:
        _einmal_melden(pfad, "fehlt oder ist nicht lesbar")
        return None
    if not inhalt:
        _einmal_melden(pfad, "ist leer")
        return None

    _gelesen[pfad] = inhalt
    log.info("Anmeldung ueber das PH-Konto eingeschaltet (Geheimnis aus %s).", pfad)
    return inhalt


def anmeldung_moeglich():
    """Ob die Anmeldeseite den Knopf fuer das PH-Konto zeigen soll."""
    return proxy_geheimnis() is not None


def _einmal_melden(pfad, grund):
    # Jede Anmeldeseite fragt nach; ohne diese Bremse stuende die Meldung
    # bei jedem Seitenaufruf im Protokoll. Der Pfad darf ins Protokoll, der
    # Inhalt nie.
    if pfad in _gemeldet:
        return
    _gemeldet.add(pfad)
    log.info(
        "Anmeldung ueber das PH-Konto ist abgeschaltet: %s %s.", pfad, grund
    )
