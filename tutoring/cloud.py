"""Der Weg nach draussen, und was ihn absichert.

Aus Sicht der Lehrperson heisst diese Funktion Qualitaetssicherung: Bei
schwierigen Aufgaben holt sie eine zweite, staerkere Einschaetzung dazu. Der
Privacy Shield ist der Mechanismus dahinter, nicht der Name des Knopfes.

Die Kette, nach Abschnitt 3a und der Vorlage private_ai_bridge:

1. Der Spark schreibt die Aufgabe neu, ohne jede Person. Geprueft wird
   deterministisch: Die Zahlenfolge muss dieselbe bleiben.
2. Auf dem neuen Text laeuft die alte Kette als zweites Netz: erkennen,
   maskieren, Leak-Check. Erst dann geht er an das Frontier-Modell.
3. Dessen Antwort wird lokal zurueckgeschrieben, also die Platzhalter wieder
   durch die echten Werte ersetzt.
4. Die geprueften Loesung bleibt INTERN. Sie wird dem Kind nicht gezeigt,
   sondern stuetzt die Stufenhilfen: Damit faellt sofort auf, wenn jemand
   addiert statt multipliziert, und zwar auf Stufe 2 und nicht erst am Ende.

Punkt 4 ist der Grund, warum die Stufenlogik unberuehrt bleibt. Das Kind
bekommt weiterhin genau die Stufe, die die Lehrperson freigegeben hat, und
die Ausgangspruefung laeuft unveraendert darueber. Eine Loesung, die das
Modell kennt, ist keine Loesung, die das Kind sieht.

Gesperrt wird der Weg, wenn:
- kein Schluessel eingerichtet ist,
- die Namenserkennung des Spark nicht gelaufen ist (eine Maskierung, deren
  Erkennung ausgefallen ist, ist keine Maskierung),
- ein blockierender Fund im Text steht, etwa eine Sozialversicherungsnummer,
- der Leak-Check eine erkannte Originalzeichenkette im ausgehenden Text
  findet.

Bilder: Bis zum 31.10.2026 ging nie eines hinaus. Seit Thomas' Entscheidung
vom 31.10.2026 darf ein Ausschnitt mit, wenn die Lehrperson das je Sitzung
freigegeben hat UND die Bildkette (bildkette.py) ihn durchgelassen hat:
nur die gedruckte Aufgabe, neu kodiert, ohne Metadaten, Handschrift, Namen,
Gesichter, Logos. Das Foto selbst geht nie hinaus, der Loesungsversuch des
Kindes auch nicht. Diese Datei bekommt den fertigen Ausschnitt als Data-URL
(``bild``) und haengt ihn an den maskierten Text; geprueft wird er
vorher, nicht hier. Der Teilnahmeschluessel geht nie hinaus.

Seit 23.10.2026 nutzt der Safe Chat dieselbe Kette (geprueft_fragen) mit
einer anderen Anweisung an die Gegenstelle, und er stellt ihr danach eine
zweite Frage (urteil_holen): ob die Anfrage, die sie gesehen hat, aus ihrer
Sicht Personenbezug hatte. Das Urteil ist eine Diagnose, keine Grenze.
"""

import json
import logging
import re
import time

import httpx
from django.conf import settings

from . import shield

logger = logging.getLogger(__name__)


class CloudGesperrt(Exception):
    """Der Weg nach draussen ist zu, und zwar aus einem benannten Grund."""

    def __init__(self, grund, art="gesperrt"):
        super().__init__(grund)
        self.grund = grund
        self.art = art


SYSTEM = (
    "Du löst eine Schulaufgabe aus dem Mathematikunterricht. Rechne "
    "sorgfältig und Schritt für Schritt.\n"
    "Im Text können Platzhalter in eckigen Klammern stehen, etwa "
    "[PERS_a3f2]. Das sind ersetzte Angaben. Übernimm sie unverändert und "
    "frag nicht nach, was dahintersteckt.\n"
    "Antworte in genau zwei Abschnitten:\n"
    "WEG: der Rechenweg in ein bis drei Sätzen.\n"
    "ERGEBNIS: das Ergebnis mit Einheit, in einer Zeile."
)

# Die Anweisung fuer die Gegenstelle im Safe Chat (Thomas, 23.10.2026). Sie
# ist allgemein gehalten; die Altersklasse haengt system_chat() an. Die
# Platzhalter sind dieselben wie bei der Qualitaetssicherung, und die Bitte,
# nicht nachzufragen, ist dieselbe: Eine Gegenstelle, die "wer ist
# [PERS_a3f2]?" fragt, lockt genau die Angabe heraus, die der Filter
# zurueckgehalten hat.
SYSTEM_CHAT = (
    "Du beantwortest Fragen von Kindern und Jugendlichen aus dem Unterricht "
    "an einer Schule in Österreich. Antworte auf Deutsch, hilfreich, ehrlich "
    "und kurz. Weißt du etwas nicht sicher, sag das; erfinde nichts.\n"
    "Im Text können Platzhalter in eckigen Klammern stehen, etwa "
    "[PERS_a3f2] oder [ORT_19c4]. Das sind ersetzte Angaben. Übernimm sie "
    "unverändert, frag nicht nach, was dahintersteckt, und rate nicht.\n"
    "Frag nie nach Namen, Adresse, Schule, Klasse, Alter oder Wohnort. "
    "Stehen solche Angaben im Text, verwende sie nicht und wiederhole sie "
    "nicht.\n"
    "Schreibt jemand von Gewalt, Selbstverletzung oder davon, dass es ihm "
    "schlecht geht, antworte ruhig und ernst und verweise an eine erwachsene "
    "Person in der Nähe, etwa die Lehrperson."
)


def system_chat(altersklasse=None):
    """SYSTEM_CHAT, ergaenzt um die Sprachebene der Altersklasse.

    Die Saetze kommen aus levels.anrede, damit die Gegenstelle dieselbe
    Grenze bekommt wie der Spark: drei kurze Saetze fuer die Volksschule,
    vier fuer alle anderen, Du statt Sie.
    """
    from . import levels

    wer = levels.anrede(altersklasse)
    return (SYSTEM_CHAT + "\n"
            + f"Du sprichst mit {wer['gegenueber']}. {wer['sprache']}")


# Die zweite Frage an die Gegenstelle, nach jeder Antwort im Safe Chat: Hat
# sie in der Anfrage etwas gesehen, das eine Person erkennbar macht? Das ist
# keine Grenze (die Grenze ist der Filter vor dem Senden), sondern eine
# Diagnose, die gesammelt und gezeigt wird: Was die Gegenstelle selbst sagt,
# ist eine zweite Meinung zum eigenen Filter.
URTEIL_PROMPT = (
    "Du hast eben eine Anfrage beantwortet. Prüfe jetzt nur die Anfrage, "
    "nicht deine Antwort: Enthielt sie Angaben, die eine bestimmte Person "
    "erkennbar machen (Name, Adresse, Telefonnummer, E-Mail-Adresse, "
    "Geburtsdatum, Kontonummer, Schule plus Klasse oder Ähnliches)?\n"
    "Platzhalter in eckigen Klammern wie [PERS_a3f2] sind bereits ersetzte "
    "Angaben; sie zählen NICHT als Personenbezug. Es geht darum, ob "
    "DARÜBER HINAUS noch etwas dasteht, das eine Person erkennbar macht.\n"
    "Antworte nur mit JSON in genau dieser Form, ohne Codeblock:\n"
    '{"personenbezug": true oder false, "begruendung": "ein Satz"}'
)

URTEIL_FRAGE = "Die Anfrage war:\n{anfrage}\n\nDeine Antwort darauf war:\n{antwort}"


def moeglich():
    """Ist der Weg ueberhaupt eingerichtet?"""
    return bool(settings.CLOUD_ENABLED)


def budget_pruefen(verbrauch):
    """Ist das Budget erschoepft? Gibt einen Grund zurueck oder None.

    Der Aufrufer reicht die Zahlen herein, damit dieses Modul keine
    Datenbank kennt: Es soll auch ohne Django pruefbar bleiben.
    """
    if verbrauch["aufrufe_sitzung"] >= settings.CLOUD_AUFRUFE_JE_SITZUNG:
        return (f"Für diese Sitzung sind die "
                f"{settings.CLOUD_AUFRUFE_JE_SITZUNG} Abfragen aufgebraucht.")
    if verbrauch["aufrufe_tag"] >= settings.CLOUD_AUFRUFE_JE_TAG:
        return (f"Heute sind die {settings.CLOUD_AUFRUFE_JE_TAG} Abfragen "
                f"aufgebraucht.")
    if verbrauch["euro_sitzung"] >= settings.BUDGET_JE_SITZUNG_EURO > 0:
        return (f"Das Guthaben dieser Sitzung von "
                f"{settings.BUDGET_JE_SITZUNG_EURO:.2f} Euro ist aufgebraucht.")
    if verbrauch["euro_tag"] >= settings.BUDGET_JE_TAG_EURO > 0:
        return (f"Das Tagesguthaben von {settings.BUDGET_JE_TAG_EURO:.2f} "
                f"Euro ist aufgebraucht.")
    return None


def geprueft_loesen(aufgabentext, verbrauch=None, bild=None):
    """Laesst die Aufgabe draussen loesen und gibt die Loesung zurueck.

    Gibt ein Woerterbuch mit der Loesung im Klartext, dem maskierten Ein- und
    Ausgang, der Zaehlung der ersetzten Entitaeten und der Messung zurueck.
    Bei jedem Grund, der den Weg sperrt, fliegt CloudGesperrt.

    Seit dem Safe Chat (23.10.2026) ist das die Kette aus geprueft_fragen mit
    der Anweisung fuer Mathematikaufgaben. ``bild`` ist, falls gegeben, der
    von der Bildkette freigegebene Ausschnitt als Data-URL (31.10.2026).
    """
    return geprueft_fragen(aufgabentext, verbrauch, system=SYSTEM, max_tokens=2000,
                           bild=bild)


# Der Satz, der dem maskierten Text angehaengt wird, wenn ein Ausschnitt
# mitgeht. Er steht auch im Verlauf unter "Das ist hinausgegangen", denn er
# ist hinausgegangen.
BILD_HINWEIS = (
    "Dazu ein Bildausschnitt: die gedruckte Aufgabe, zugeschnitten und "
    "bereinigt. Lies Zahlen und Zeichen im Zweifel vom Bild ab."
)


def geprueft_fragen(text, verbrauch=None, system=None, max_tokens=800, bild=None):
    """Schickt einen Text durch die ganze Kette nach draussen.

    Die fuenf Schritte aus dem Kopf dieser Datei: Der Spark formuliert ohne
    Personen um, Regel- und Namenserkennung auf dem Ergebnis, Maskieren,
    Leak-Check, Senden, lokal zuruecksetzen. ``system`` ist die Anweisung
    an die Gegenstelle (ohne Angabe die fuer Mathematikaufgaben).

    ``bild`` ist ein Ausschnitt als Data-URL, den die Bildkette schon
    freigegeben hat. Er wird hier nicht mehr geprueft, nur angehaengt; die
    Pruefung ist Sache von bildkette.bereinigen, und wer hier ein
    ungeprueftes Bild hereinreicht, hat die Kette umgangen.

    Gibt dasselbe Woerterbuch wie geprueft_loesen zurueck; "loesung" ist die
    Antwort im Klartext, also mit den lokal wieder eingesetzten Angaben,
    "bild" sagt, ob ein Ausschnitt mitging.
    Bei jedem Grund, der den Weg sperrt, fliegt CloudGesperrt.
    """
    if not moeglich():
        raise CloudGesperrt("Es ist kein Zugang zur externen KI eingerichtet.",
                            art="nicht_eingerichtet")

    text = (text or "").strip()
    if not text:
        raise CloudGesperrt("Es gibt keinen Text.", art="leer")

    if verbrauch is not None:
        grund = budget_pruefen(verbrauch)
        if grund:
            raise CloudGesperrt(grund, art="budget")

    # --- Schritt 1: der Spark schreibt die Aufgabe ohne Personen neu -----
    #
    # Der Unterschied zum blossen Maskieren ist grundsaetzlich. Eine
    # Erkennung, die Spannen im Text sucht, muss jeden Namen finden; sie war
    # an vierzehn Saetzen aus dem Unterricht bei 93 Prozent, und der
    # uebersehene Name ging im Klartext hinaus. Eine Umformulierung muss
    # nichts finden: Sie schreibt einen Text, in dem keine Person vorkommt.
    # Gemessen an denselben Saetzen: 14 von 14, keine Zahl veraendert.
    #
    # Geht die Umformulierung schief, bleibt der alte Weg. Er ist schlechter,
    # aber er ist da.
    umgeschrieben = ""
    try:
        umgeschrieben = shield.neu_formulieren(text)
    except shield.UmschreibenGescheitert as fehler:
        logger.warning("Umformulierung verworfen: %s", fehler)
    except Exception as fehler:  # noqa: BLE001 - der Spark ist die Grenze
        raise CloudGesperrt(
            "Die Anonymisierung am Spark ist nicht gelaufen.",
            art="shield_aus",
        ) from fehler

    # Ab hier arbeitet die alte Kette auf dem umgeschriebenen Text weiter.
    # Zwei Netze mit verschiedenen Maschen: Was die Umformulierung stehen
    # laesst, wird weiterhin gesucht, maskiert und geprueft.
    text = umgeschrieben or text

    # --- Schritt 2: erkennen, was trotzdem noch dasteht ------------------
    funde = shield.regelfunde(text)
    try:
        funde += shield.namensfunde(text)
    except Exception as fehler:  # noqa: BLE001 - jeder Ausfall sperrt gleich
        # Absichtlich hart: Eine Maskierung, deren Erkennung nicht gelaufen
        # ist, ist keine Maskierung. Lieber keine Qualitaetssicherung als
        # eine ungeprueft hinausgeschickte Zeile.
        raise CloudGesperrt(
            "Die Anonymisierung am Spark ist nicht gelaufen.",
            art="shield_aus",
        ) from fehler

    gesperrt = shield.blockierende(funde)
    if gesperrt:
        namen = ", ".join(shield.BEZEICHNUNG.get(typ, typ) for typ, _ in gesperrt)
        raise CloudGesperrt(
            f"Im Text steht etwas, das nicht hinausgeht: {namen}.",
            art="blockierender_fund",
        )

    maskiert, tabelle = shield.maskieren(text, funde)

    # --- Schritt 3: Leak-Check vor dem Aufruf ----------------------------
    durchgerutscht = shield.leak_check(maskiert, funde)
    if durchgerutscht:
        arten = ", ".join(shield.BEZEICHNUNG.get(e["typ"], e["typ"])
                          for e in durchgerutscht)
        raise CloudGesperrt(
            f"Der Leak-Check hat angeschlagen: {arten}.",
            art="leak",
        )

    # --- Schritt 4: hinaus -----------------------------------------------
    inhalt = maskiert
    if bild:
        maskiert = maskiert + "\n\n" + BILD_HINWEIS
        inhalt = [
            {"type": "text", "text": maskiert},
            {"type": "image_url", "image_url": {"url": bild}},
        ]
    daten, dauer_ms = _senden(
        [
            {"role": "system", "content": system or SYSTEM},
            {"role": "user", "content": inhalt},
        ],
        max_tokens,
    )
    roh = _inhalt(daten)
    if roh is None:
        raise CloudGesperrt("Die Antwort war unbrauchbar.", art="antwort_leer")

    # --- Schritt 5: lokal zurueckschreiben -------------------------------
    klartext = shield.zuruecksetzen(roh, tabelle)
    # Bewusst nicht 'verbrauch': So heisst schon der Parameter mit den
    # Budgetzahlen, und zwei Dinge unter einem Namen sind eine Falle.
    messung = daten.get("usage") or {}

    return {
        "loesung": klartext,
        # Die Anweisung an die Gegenstelle, fuer das Protokoll (Thomas,
        # 31.10.2026: die Kommunikation mit dem Frontier-Modell einsehbar).
        "anweisung": system or SYSTEM,
        "umgeschrieben": umgeschrieben,
        "maskiert_ein": maskiert,
        "maskiert_aus": roh,
        "entitaeten": shield.zaehlung(tabelle),
        "ersetzt": len(tabelle),
        "bild": bool(bild),
        "modell": daten.get("model") or settings.CLOUD_MODEL,
        "tokens_ein": messung.get("prompt_tokens", 0),
        "tokens_aus": messung.get("completion_tokens", 0),
        "dauer_ms": dauer_ms,
    }


def _senden(nachrichten, max_tokens):
    """Ein Aufruf an die Gegenstelle. Gibt (daten, dauer_ms) zurueck.

    Die einzige Stelle, an der der Schluessel in die Hand genommen wird. Er
    steht im Kopf der Anfrage und sonst nirgends: nicht in der Ausnahme,
    nicht im Log. Bei jedem Netzfehler fliegt CloudGesperrt mit der ART des
    Fehlers, nicht mit seinem Text, denn httpx schreibt in manche Meldungen
    die ganze Anfrage hinein.
    """
    begonnen = time.monotonic()
    rumpf = {
        "model": settings.CLOUD_MODEL,
        "messages": nachrichten,
        "max_completion_tokens": max_tokens,
    }
    try:
        with httpx.Client(timeout=settings.CLOUD_TIMEOUT_SECONDS) as client:
            antwort = client.post(
                f"{settings.CLOUD_BASE_URL}/chat/completions",
                json=rumpf,
                headers={"Authorization": f"Bearer {settings.CLOUD_API_KEY}"},
            )
            antwort.raise_for_status()
            daten = antwort.json()
    except (httpx.HTTPError, ValueError) as fehler:
        # Der Schluessel darf in keiner Meldung landen, deshalb nur die Art.
        raise CloudGesperrt(
            "Die externe KI hat nicht geantwortet.",
            art=type(fehler).__name__,
        ) from fehler
    if not isinstance(daten, dict):
        raise CloudGesperrt("Die Antwort war unbrauchbar.", art="antwort_leer")
    return daten, int((time.monotonic() - begonnen) * 1000)


def _inhalt(daten):
    """Der Text der ersten Wahl, oder None, wenn die Antwort keine hat."""
    try:
        return (daten["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return None


# Die drei Urteile, wie sie am Chatzug stehen (ChatZug.URTEIL_*). Hier noch
# einmal benannt, damit diese Datei ohne das Modell lesbar bleibt.
URTEIL_OHNE = "ohne"
URTEIL_MIT = "mit"
URTEIL_OFFEN = "offen"

_URTEIL_JSON = re.compile(r"\{.*\}", re.DOTALL)


def urteil_holen(maskiert_ein, maskiert_aus):
    """Fragt die Gegenstelle, ob die eben gesehene Anfrage Personenbezug hatte.

    Genau die Anfrage und die Antwort, die sie gerade gesehen hat, also die
    maskierten Fassungen; Klartext geht auch hier nicht hinaus. Gibt ein
    Woerterbuch zurueck: "urteil" (ohne, mit, offen), "grund" in den Worten
    der Gegenstelle, dazu Token und Dauer fuer das Protokoll.

    Wirft nie. Jeder Fehler (Netz, kein Zugang, kaputtes JSON) ergibt
    "offen" mit einem Grund: Die Diagnose ist eine Zugabe, und ein Chat darf
    nicht an ihr scheitern. Der Schluessel steht in keiner Meldung und in
    keinem Log; was geloggt wird, ist die Art des Fehlers.
    """
    leer = {"tokens_ein": 0, "tokens_aus": 0, "dauer_ms": 0}
    if not moeglich():
        return {"urteil": URTEIL_OFFEN,
                "grund": "Kein Zugang zur Gegenstelle eingerichtet.", **leer}

    frage = URTEIL_FRAGE.format(
        anfrage=(maskiert_ein or "").strip()[:6000],
        antwort=(maskiert_aus or "").strip()[:6000],
    )
    try:
        daten, dauer_ms = _senden(
            [
                {"role": "system", "content": URTEIL_PROMPT},
                {"role": "user", "content": frage},
            ],
            200,
        )
    except CloudGesperrt as fehler:
        logger.warning("Kein Urteil der Gegenstelle: %s", fehler.art)
        return {"urteil": URTEIL_OFFEN,
                "grund": f"Die Gegenstelle hat nicht geantwortet ({fehler.art}).",
                **leer}
    except Exception as fehler:  # noqa: BLE001 - wirft nie, siehe oben
        logger.warning("Kein Urteil der Gegenstelle: %s", type(fehler).__name__)
        return {"urteil": URTEIL_OFFEN,
                "grund": f"Die Gegenstelle hat nicht geantwortet ({type(fehler).__name__}).",
                **leer}

    messung = daten.get("usage") or {}
    zahlen = {
        "tokens_ein": messung.get("prompt_tokens", 0),
        "tokens_aus": messung.get("completion_tokens", 0),
        "dauer_ms": dauer_ms,
        "anweisung": URTEIL_PROMPT,
    }
    roh = _inhalt(daten) or ""
    treffer = _URTEIL_JSON.search(roh)
    gelesen = None
    if treffer:
        try:
            gelesen = json.loads(treffer.group(0))
        except json.JSONDecodeError:
            gelesen = None
    if not isinstance(gelesen, dict) or not isinstance(gelesen.get("personenbezug"), bool):
        logger.warning("Urteil der Gegenstelle unverstaendlich, bleibt offen.")
        return {"urteil": URTEIL_OFFEN,
                "grund": "Die Antwort der Gegenstelle war nicht lesbar.", **zahlen}

    grund = str(gelesen.get("begruendung") or "").strip()[:240]
    return {
        "urteil": URTEIL_MIT if gelesen["personenbezug"] else URTEIL_OHNE,
        "grund": grund,
        **zahlen,
    }


def kosten_micro(modell, tokens_ein, tokens_aus):
    """Kosten in Millionstel Euro, sofern Preise hinterlegt sind.

    Ohne hinterlegte Preise wird nichts geschaetzt. Eine erfundene Zahl in
    einer Abrechnung ist schlimmer als gar keine.
    """
    tabelle = settings.CLOUD_PREISE or {}
    # Die Antwort nennt den genauen Stand, etwa "gpt-5-2025-08-07". Die
    # Preistabelle kennt meist nur "gpt-5". Deshalb erst genau, dann der
    # eingestellte Name, dann der laengste passende Praefix.
    preise = tabelle.get(modell) or tabelle.get(settings.CLOUD_MODEL)
    if not preise:
        passend = [n for n in tabelle if modell.startswith(n)]
        if passend:
            preise = tabelle[max(passend, key=len)]
    if not preise:
        return 0
    ein = float(preise.get("ein", 0)) * tokens_ein
    aus = float(preise.get("aus", 0)) * tokens_aus
    return int(ein + aus)
