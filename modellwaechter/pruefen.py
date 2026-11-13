"""Der Durchlauf: Quellen abfragen, Neues festhalten, einordnen, melden.

Gedacht fuer einen Zeitplan am Server (manage.py modelle_pruefen, einmal
am Tag). Eine Quelle, die nicht antwortet, bekommt einen Lauf mit Fehlerart
und haelt die anderen nicht auf. Der Schluessel des OpenAI-Kontos steht in
keinem Lauf, keinem Fund und keiner Meldung.
"""

import logging
import time

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from tutoring.spark import SparkNichtErreichbar

from . import einordnung, quellen
from .models import Fund, Lauf

logger = logging.getLogger(__name__)


def aufgaben():
    """Welche Quellen gefragt werden, aus den Einstellungen: (quelle, anbieter, holen)."""
    liste = []
    for autor in settings.MODELLWAECHTER_HF_AUTOREN:
        liste.append((quellen.HUGGINGFACE, autor,
                      lambda client, a=autor: quellen.huggingface(client, a)))
    if settings.MODELLWAECHTER_OPENROUTER:
        liste.append((quellen.OPENROUTER, "alle", quellen.openrouter))
    for repo in settings.MODELLWAECHTER_GITHUB_REPOS:
        liste.append((quellen.GITHUB, repo,
                      lambda client, r=repo: quellen.github_releases(client, r)))
    if settings.MODELLWAECHTER_OPENAI_KONTO and settings.CLOUD_API_KEY:
        liste.append((quellen.OPENAI, "konto",
                      lambda client: quellen.openai_konto(
                          client, settings.CLOUD_BASE_URL, settings.CLOUD_API_KEY)))
    return liste


def client_bauen():
    return httpx.Client(
        timeout=settings.MODELLWAECHTER_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "modlearn-modellwaechter"},
    )


def _gewuenscht(nur, quelle, anbieter):
    return not nur or quelle in nur or f"{quelle}:{anbieter}" in nur


def _festhalten(eintraege, grundbestand):
    """Legt an, was es noch nicht gibt. Gibt die neu angelegten Funde zurueck."""
    neue = []
    for e in eintraege:
        fund, angelegt = Fund.objects.get_or_create(
            quelle=e["quelle"], kennung=e["kennung"],
            defaults={
                "anbieter": e["anbieter"], "name": e["name"], "adresse": e["adresse"],
                "veroeffentlicht": e["veroeffentlicht"], "lizenz": e["lizenz"],
                "aufgabe": e["aufgabe"], "merkmale": e["merkmale"],
                "beschreibung": e["beschreibung"], "grundbestand": grundbestand,
            },
        )
        if angelegt:
            neue.append(fund)
    return neue


def durchlauf(client=None, nur=None):
    """Fragt die Quellen und legt Laeufe und Funde an. Gibt (neue, laeufe) zurueck.

    Der erste erfolgreiche Lauf einer Quelle ist der Grundbestand; seine
    Funde zaehlen nicht als neu. ``nur`` schraenkt auf Quellen ein, etwa
    {"huggingface"} oder {"huggingface:Qwen", "github"}.
    """
    eigener = client is None
    client = client or client_bauen()
    neue, laeufe = [], []
    try:
        for quelle, anbieter, holen in aufgaben():
            if not _gewuenscht(nur, quelle, anbieter):
                continue
            begonnen = time.monotonic()
            lauf = Lauf(quelle=quelle, anbieter=anbieter)
            try:
                eintraege = holen(client)
            except quellen.QuelleGescheitert as fehler:
                lauf.ergebnis = Lauf.FEHLER
                lauf.fehlerart = fehler.art[:60]
                logger.warning("Modellwächter: %s %s ohne Antwort (%s)", quelle, anbieter, fehler.art)
            else:
                erster = not Lauf.objects.filter(
                    quelle=quelle, anbieter=anbieter, ergebnis=Lauf.OK).exists()
                frische = _festhalten(eintraege, grundbestand=erster)
                lauf.gesehen = len(eintraege)
                lauf.grundbestand = erster
                lauf.neu = 0 if erster else len(frische)
                if not erster:
                    neue.extend(frische)
            lauf.dauer_ms = int((time.monotonic() - begonnen) * 1000)
            lauf.save()
            laeufe.append(lauf)
    finally:
        if eigener:
            client.close()
    return neue, laeufe


def einordnen(funde, hoechstens=None, client=None):
    """Laesst den Spark die neuesten Funde einordnen. Gibt die Anzahl zurueck.

    Hoert nach dem ersten Ausfall des Spark auf: Zehn Anlaeufe in die Frist
    waeren zehn Minuten fuer nichts.
    """
    if hoechstens is None:
        hoechstens = settings.MODELLWAECHTER_EINORDNUNGEN_JE_LAUF
    offen = [f for f in funde if not f.einordnung][:hoechstens]
    if not offen:
        return 0
    eigener = client is None
    client = client or client_bauen()
    anzahl = 0
    try:
        for fund in offen:
            try:
                if einordnung.einordnen(fund, client):
                    anzahl += 1
            except SparkNichtErreichbar:
                logger.warning("Modellwächter: Spark nicht erreichbar, Einordnung bleibt leer")
                break
    finally:
        if eigener:
            client.close()
    return anzahl


# --- Die Meldung ---------------------------------------------------------------

def mail_moeglich():
    """E-Mail braucht einen Mailserver, einen Absender und Empfaenger; sonst steht die Meldung nur auf der Seite."""
    return bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL
                and settings.MODELLWAECHTER_EMPFAENGER)


def _datum(fund):
    return fund.datum.strftime("%d.%m.%Y") if fund.datum else "ohne Datum"


def bericht_text(funde):
    """Die Meldung als Text, je Quelle und Anbieter ein Block."""
    gruppen = {}
    for fund in funde:
        gruppen.setdefault((fund.quelle_titel, fund.anbieter), []).append(fund)
    zeilen = [f"Neue Modelle und Versionen: {len(funde)}", ""]
    for (titel, anbieter), liste in gruppen.items():
        zeilen.append(f"{titel}, {anbieter}")
        for fund in liste:
            zusatz = ", ".join(t for t in (fund.lizenz, fund.aufgabe) if t)
            zeilen.append(f"- {fund.kennung} ({_datum(fund)}{', ' + zusatz if zusatz else ''})")
            if fund.adresse:
                zeilen.append(f"  {fund.adresse}")
            if fund.einordnung:
                zeilen.append(f"  {fund.einordnung}")
                zeilen.append(f"  (zusammengefasst von {fund.einordnung_modell or 'einem Modell am Spark'})")
        zeilen.append("")
    zeilen.append("Diese Meldung schreibt der Modellwächter der ModLearn-Anwendung. "
                  "Die Liste steht auch unter /lehrperson/modelle/.")
    return "\n".join(zeilen)


def melden(funde):
    """Schickt die Meldung, wenn E-Mail eingerichtet ist. True, wenn sie hinausging."""
    if not funde or not mail_moeglich():
        return False
    try:
        send_mail(
            f"ModLearn: {len(funde)} neue Modelle oder Versionen",
            bericht_text(funde),
            settings.DEFAULT_FROM_EMAIL,
            settings.MODELLWAECHTER_EMPFAENGER,
            fail_silently=False,
        )
    except Exception as fehler:  # noqa: BLE001 - der Lauf ist wichtiger als die Mail
        logger.warning("Modellwächter: E-Mail nicht verschickt (%s)", type(fehler).__name__)
        return False
    Fund.objects.filter(pk__in=[f.pk for f in funde]).update(gemeldet_am=timezone.now())
    return True


def letzte_laeufe():
    """Je Quelle und Anbieter der juengste Lauf, neueste zuerst; ohne DISTINCT ON, damit es auch in SQLite geht."""
    gesehen = {}
    for lauf in Lauf.objects.order_by("-begonnen", "-pk")[:600]:
        gesehen.setdefault((lauf.quelle, lauf.anbieter), lauf)
    return list(gesehen.values())
