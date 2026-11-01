"""Ist alles bereit? Die Frage, die man fuenf Minuten vor dem Vortrag stellt.

Die Zustandspruefung unter /healthz sagt nur, ob die Anwendung Anfragen
annimmt. Sie sagt bewusst nichts ueber die Datenbank und nichts ueber den
Spark: Eine Pruefung, die bei jeder Wartung Alarm schlaegt, wird irgendwann
ignoriert.

Vor einem Vortrag ist die Frage aber genau umgekehrt. Dann will jemand
wissen, ob das Sprachmodell antwortet, wie schnell, und ob die
Spracherkennung laeuft. Diese Pruefung kostet zwei echte Aufrufe und steht
deshalb hinter der Anmeldung.
"""

import logging
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Kurz genug, dass niemand wartet, lang genug, dass ein kaltes Modell nicht
# faelschlich als tot gilt.
FRIST = 30.0


def _messen(aufgabe):
    """Fuehrt eine Pruefung aus und misst, wie lange sie gedauert hat."""
    begonnen = time.monotonic()
    try:
        auskunft = aufgabe()
        return {
            "ok": True, "auskunft": auskunft,
            "ms": round((time.monotonic() - begonnen) * 1000),
        }
    except Exception as fehler:  # noqa: BLE001 - hier zaehlt jeder Ausfall gleich
        return {
            "ok": False,
            "auskunft": f"{type(fehler).__name__}: {fehler}"[:160],
            "ms": round((time.monotonic() - begonnen) * 1000),
        }


def _spark():
    rumpf = {
        "model": settings.SPARK_MODEL,
        "messages": [
            {"role": "system", "content": "Antworte mit genau einem Wort."},
            {"role": "user", "content": "Sag bereit."},
        ],
        "max_tokens": 8,
        "temperature": 0.0,
    }
    with httpx.Client(timeout=FRIST) as client:
        antwort = client.post(
            f"{settings.SPARK_BASE_URL}/chat/completions", json=rumpf
        )
        antwort.raise_for_status()
        daten = antwort.json()
    return (daten["choices"][0]["message"]["content"] or "").strip()[:60]


def _whisper():
    if not settings.SPARK_AUDIO_BASE_URL:
        raise RuntimeError("Nicht eingerichtet (SPARK_AUDIO_BASE_URL fehlt)")
    # Eine Sekunde Stille als WAV, 16 kHz mono. Sie wird wirklich erkannt;
    # ein blosser Verbindungsaufbau wuerde nicht zeigen, ob das Modell
    # geladen ist.
    stille = _wav_stille(sekunden=1)
    with httpx.Client(timeout=FRIST) as client:
        antwort = client.post(
            f"{settings.SPARK_AUDIO_BASE_URL}/audio/transcriptions",
            files={"file": ("probe.wav", stille, "audio/wav")},
            data={"model": settings.SPARK_AUDIO_MODEL, "language": "de",
                  "response_format": "json"},
        )
        antwort.raise_for_status()
    return "Erkennung antwortet"


def _wav_stille(sekunden=1, rate=16000):
    """Baut eine stille WAV-Datei ohne weitere Abhaengigkeiten."""
    import struct

    proben = rate * sekunden
    daten = b"\x00\x00" * proben
    kopf = b"RIFF" + struct.pack("<I", 36 + len(daten)) + b"WAVEfmt "
    kopf += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    kopf += b"data" + struct.pack("<I", len(daten))
    return kopf + daten


def pruefen():
    """Alle Pruefungen, in der Reihenfolge, in der sie im Vortrag zaehlen."""
    return [
        {
            "name": "Sprachmodell am Spark",
            "wozu": "Schreibt die Hilfen. Ohne das geht nichts.",
            "wo": settings.SPARK_BASE_URL,
            **_messen(_spark),
        },
        {
            "name": "Spracherkennung am Spark",
            "wozu": "Nimmt gesprochene Aufgaben auf. Ohne das bleibt Tippen.",
            "wo": settings.SPARK_AUDIO_BASE_URL or "nicht eingerichtet",
            **_messen(_whisper),
        },
    ]
