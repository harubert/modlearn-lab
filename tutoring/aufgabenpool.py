"""Der Aufgabenpool der Lehrperson (Thomas, 1.11.2026).

Thomas: "Die Lehrperson kann selbst Aufgaben in der Sitzung hochladen, und
zwar nachdem sie laeuft. Dann im System den Schuelern zur Verfuegung gestellt,
und die Schueler haben dann auch gleich einen Coach zu jeder Uebung. Beim
Hochladen kann das System gleich pruefen, ob es die Aufgabe selber loesen kann
bzw. das Frontier-Modell dazunehmen."

Hier steht die Pruefung beim Hochladen: Der Spark loest die Aufgabe mit
derselben Anweisung wie die Gegenstelle (cloud.SYSTEM: WEG und ERGEBNIS); ist
die Qualitaetssicherung eingeschaltet, loest die externe KI sie ueber den Weg
aus Abschnitt 3a dazu, und die beiden Endergebnisse werden verglichen. Beide
Aufrufe stehen im Forschungsprotokoll (Interaction). Was dabei herauskommt,
sieht nur die Lehrperson; ein Kind, das die Aufgabe waehlt, bekommt die
gepruefte Loesung still in seine Aufgabe kopiert (Task.checked_*), damit die
Qualitaetssicherung nicht je Kind noch einmal laeuft.
"""

import logging
import time

from django.conf import settings
from django.utils import timezone

from . import ausgabepruefung, cloud, spark
from .models import Interaction

logger = logging.getLogger(__name__)

STATUS_OFFEN = "offen"         # der Spark konnte die Aufgabe nicht loesen
STATUS_SPARK = "spark"         # nur der Spark hat geloest (keine Qualitaetssicherung)
STATUS_GESPERRT = "gesperrt"   # der Spark hat geloest, der Weg nach draussen war zu
STATUS_EINIG = "einig"         # Spark und externe KI nennen dasselbe Ergebnis
STATUS_UNEINIG = "uneinig"     # verschiedene Ergebnisse
STATUS_UNKLAR = "unklar"       # beide haben geloest, kein Zahlenergebnis zum Vergleichen

STATUS_TITEL = {
    STATUS_OFFEN: "Spark konnte nicht lösen",
    STATUS_SPARK: "Spark hat gelöst",
    STATUS_GESPERRT: "Spark hat gelöst, draußen gesperrt",
    STATUS_EINIG: "Spark und externe KI einig",
    STATUS_UNEINIG: "Spark und externe KI uneinig",
    STATUS_UNKLAR: "beide gelöst, nicht vergleichbar",
}

# Die Felder, die ein Kind mit der gewaehlten Aufgabe uebernimmt: die
# gepruefte Loesung und ihr Weg nach draussen, so wie Task.checked_* sie
# traegt (gleiche Namen hier und dort).
GEPRUEFTE_FELDER = (
    "checked_solution", "checked_at", "checked_model", "checked_rewritten",
    "checked_sent", "checked_received", "checked_entities", "checked_tokens_in",
    "checked_tokens_out", "checked_ms", "checked_cost_micro",
)


def ergebnis_kurz(loesung):
    """Die Zeile nach ERGEBNIS:, sonst die letzte Zeile; fuer die Anzeige."""
    text = (loesung or "").strip()
    if not text:
        return ""
    kopf, trenner, rest = text.rpartition("ERGEBNIS:")
    zeile = rest.strip() if trenner else text.splitlines()[-1].strip()
    return zeile[:160]


def pruefen(vorlage, sitzung, verbrauch=None):
    """Loest die Aufgabe am Spark und, wenn eingeschaltet, draussen; setzt den Status.

    Synchron: Die Lehrperson wartet auf der Sitzungsseite einige Sekunden,
    und bekommt dafuer sofort zu sehen, ob das System die Aufgabe kann.
    Ein Ausfall einer Seite ist kein Fehler der Seite: Der Status sagt,
    was fehlt.
    """
    _am_spark_loesen(vorlage, sitzung)
    if sitzung.cloud_enabled and cloud.moeglich():
        _draussen_loesen(vorlage, sitzung, verbrauch)
    vorlage.status = status_fuer(vorlage)
    vorlage.save()
    return vorlage


def _am_spark_loesen(vorlage, sitzung):
    begonnen = time.monotonic()
    messung = {}
    try:
        text, messung = spark.antwort_holen_sync(
            cloud.SYSTEM, vorlage.text, max_tokens=1200, temperatur=0.0
        )
        vorlage.spark_solution = (text or "").strip()
        vorlage.spark_error = ""
        ergebnis = "ok"
    except Exception as fehler:  # noqa: BLE001 - die Seite laeuft weiter
        logger.warning("Aufgabenpool: Spark hat nicht geloest: %s", type(fehler).__name__)
        vorlage.spark_solution = ""
        vorlage.spark_error = type(fehler).__name__[:120]
        ergebnis = "fehler"
    vorlage.spark_ms = int((time.monotonic() - begonnen) * 1000)
    Interaction.aufzeichnen(
        sitzung=sitzung, weg=Interaction.LOKAL,
        modell=(messung or {}).get("modell") or settings.SPARK_MODEL,
        tokens_ein=(messung or {}).get("tokens_ein", 0),
        tokens_aus=(messung or {}).get("tokens_aus", 0),
        dauer_ms=(messung or {}).get("dauer_ms", vorlage.spark_ms),
        ergebnis=ergebnis, fehlerart=vorlage.spark_error,
        text_ein=vorlage.text, text_aus=vorlage.spark_solution, anweisung=cloud.SYSTEM,
    )


def _draussen_loesen(vorlage, sitzung, verbrauch):
    try:
        erg = cloud.geprueft_loesen(vorlage.text, verbrauch)
    except cloud.CloudGesperrt as fehler:
        vorlage.checked_blocked = fehler.grund[:120]
        Interaction.aufzeichnen(
            sitzung=sitzung, weg=Interaction.CLOUD, modell=settings.CLOUD_MODEL,
            ergebnis="gesperrt", fehlerart=fehler.art, leak_check=Interaction.BLOCKIERT,
        )
        return
    except Exception as fehler:  # noqa: BLE001
        logger.warning("Aufgabenpool: externe KI hat nicht geantwortet: %s", type(fehler).__name__)
        vorlage.checked_blocked = "Die externe KI hat nicht geantwortet."
        Interaction.aufzeichnen(
            sitzung=sitzung, weg=Interaction.CLOUD, modell=settings.CLOUD_MODEL,
            ergebnis="fehler", fehlerart=type(fehler).__name__, leak_check=Interaction.BLOCKIERT,
        )
        return
    kosten = cloud.kosten_micro(erg["modell"], erg["tokens_ein"], erg["tokens_aus"])
    vorlage.checked_solution = erg["loesung"]
    vorlage.checked_at = timezone.now()
    vorlage.checked_model = erg["modell"]
    vorlage.checked_rewritten = erg.get("umgeschrieben", "") or ""
    vorlage.checked_sent = erg["maskiert_ein"]
    vorlage.checked_received = erg["maskiert_aus"]
    vorlage.checked_entities = erg["entitaeten"]
    vorlage.checked_tokens_in = erg["tokens_ein"]
    vorlage.checked_tokens_out = erg["tokens_aus"]
    vorlage.checked_ms = erg["dauer_ms"]
    vorlage.checked_cost_micro = kosten
    vorlage.checked_blocked = ""
    Interaction.aufzeichnen(
        sitzung=sitzung, weg=Interaction.CLOUD, modell=erg["modell"],
        tokens_ein=erg["tokens_ein"], tokens_aus=erg["tokens_aus"], dauer_ms=erg["dauer_ms"],
        kosten_micro=kosten, leak_check=Interaction.BESTANDEN, entitaeten=erg["entitaeten"],
        ergebnis="ok", maskiert_ein=erg["maskiert_ein"], maskiert_aus=erg["maskiert_aus"],
        text_aus=erg["loesung"], anweisung=erg.get("anweisung", ""),
    )


def status_fuer(vorlage):
    """Der Status aus den beiden Loesungen: siehe die Konstanten oben."""
    if not vorlage.spark_solution:
        return STATUS_OFFEN
    if vorlage.checked_solution:
        zs = ausgabepruefung.endergebnis_zahlen(vorlage.spark_solution)
        zc = ausgabepruefung.endergebnis_zahlen(vorlage.checked_solution)
        if zs and zc:
            return STATUS_EINIG if zs & zc else STATUS_UNEINIG
        return STATUS_UNKLAR
    if vorlage.checked_blocked:
        return STATUS_GESPERRT
    return STATUS_SPARK


def status_text(vorlage):
    """Ein Satz fuer die Lehrperson, mit den Ergebnissen."""
    s = vorlage.status
    spark_erg = ergebnis_kurz(vorlage.spark_solution)
    cloud_erg = ergebnis_kurz(vorlage.checked_solution)
    if s == STATUS_EINIG:
        return f"Der Spark und die externe KI kommen auf dasselbe Ergebnis: {spark_erg}"
    if s == STATUS_UNEINIG:
        return (f"Der Spark sagt „{spark_erg}“, die externe KI sagt „{cloud_erg}“. "
                "Bitte selbst nachsehen; die Hilfen stützen sich auf die externe KI.")
    if s == STATUS_UNKLAR:
        return (f"Beide haben gelöst (Spark: {spark_erg}; externe KI: {cloud_erg}), "
                "die Ergebnisse lassen sich nicht automatisch vergleichen.")
    if s == STATUS_GESPERRT:
        return (f"Der Spark hat gelöst: {spark_erg}. Der Weg nach draußen war gesperrt: "
                f"{vorlage.checked_blocked}")
    if s == STATUS_SPARK:
        return f"Der Spark hat die Aufgabe gelöst: {spark_erg}. Keine Prüfung von draußen."
    grund = vorlage.spark_error or "keine Lösung"
    zusatz = f" Die externe KI sagt: {cloud_erg}." if cloud_erg else ""
    return f"Der Spark konnte die Aufgabe nicht lösen ({grund}).{zusatz}"


def geprueftes_fuer_task(vorlage):
    """Die Felder, die ein Kind mit der Aufgabe uebernimmt (leer ohne gepruefte Loesung)."""
    if not vorlage.checked_solution:
        return {}
    return {feld: getattr(vorlage, feld) for feld in GEPRUEFTE_FELDER}
