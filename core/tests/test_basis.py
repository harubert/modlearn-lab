"""Prüfungen des Skeletts: Zustandsprüfung, Startseite, gesetzte Grenzen."""


import pytest
from django.conf import settings
from django.db import connection


def test_healthz_antwortet_ohne_datenbank(client):
    """Die Zustandsprüfung darf die Datenbank nicht berühren.

    Sonst meldet sie bei jeder Datenbankwartung einen Ausfall der Anwendung,
    obwohl die Anwendung Anfragen annimmt.
    """
    # Bewusst unverschluesselt: der Container prueft ueber Loopback ohne TLS.
    # Diese Pruefung haelt zugleich die Ausnahme in SECURE_REDIRECT_EXEMPT fest.
    with connection.execute_wrapper(_keine_abfragen):
        antwort = client.get("/healthz")

    assert antwort.status_code == 200
    assert antwort.content == b"ok\n"


def _keine_abfragen(execute, sql, params, many, context):
    raise AssertionError(f"Unerwartete Datenbankabfrage: {sql}")


@pytest.mark.django_db  # Die Startseite raeumt verfallene Sitzungen mit auf.
def test_startseite_wird_ausgeliefert(client):
    # secure=True, weil SECURE_SSL_REDIRECT im Betrieb alles Unverschluesselte
    # umleitet. Hinter Caddy ist jede echte Anfrage verschluesselt.
    antwort = client.get("/", secure=True)

    assert antwort.status_code == 200
    assert "AI LAB" in antwort.content.decode()


def test_anfragegrenze_entspricht_dem_proxy():
    """Caddy begrenzt auf 20 MB, die App muss dieselbe Grenze selbst halten."""
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == 20 * 1024 * 1024


def test_proxy_kopfzeile_ist_gesetzt():
    """Ohne diese Zeile hält Django jede Anfrage hinter Caddy für unverschlüsselt."""
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_cloud_hilfe_ist_ohne_schluessel_abgeschaltet():
    """Der Schalter darf ohne Zugangsschlüssel nicht senden können."""
    if not settings.CLOUD_API_KEY or not settings.CLOUD_MODEL:
        assert settings.CLOUD_ENABLED is False


def test_datenschutzerklaerung_nennt_foto_und_sprache(client):
    """Die Anwendung speichert Fotos und schickt Aufnahmen zur Erkennung.

    Stand beides nicht drin. Ein Foto aus einem Heft kann einen Namen
    enthalten, und eine Stimme ist ein biometrisches Datum, auch wenn sie
    nicht gespeichert wird.
    """
    seite = client.get("/datenschutz/", secure=True).content.decode()

    assert "Foto" in seite
    assert "Tonaufnahme selbst wird nicht gespeichert" in seite
    assert "fotografiert oder gesprochen" in seite


def test_keine_mehrzeiligen_klammerkommentare_in_vorlagen():
    """Django kennt {# #} nur einzeilig.

    Ueber mehrere Zeilen steht der Kommentar als Text auf der Seite. Auf der
    Trainerseite standen so vier Werkstattnotizen im Bild, eine davon ganz
    oben ueber dem Kopf. Es ist das zweite Mal, dass dieser Fehler auftritt;
    beim ersten Mal hat ihn ein Bildschirmfoto gefunden, kein Test.

    Keine Seite rendert dabei kaputt, deshalb faellt es sonst niemandem auf.
    """
    import re
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[2]
    muster = re.compile(r"\{#((?:[^#]|#(?!\}))*?)#\}", re.DOTALL)

    # Gesucht wird nach dem Muster und nicht nach einer Liste von Ordnern. Die
    # Liste stand hier einmal fest und hat plan/templates nicht mitgeprueft:
    # Eine neue Anwendung waere ungeprueft geblieben, ohne dass es auffaellt.
    ordner = [wurzel / "templates"] + sorted(wurzel.glob("*/templates"))

    befunde = []
    for verzeichnis in ordner:
        for datei in verzeichnis.rglob("*.html"):
            text = datei.read_text(encoding="utf-8")
            for treffer in muster.finditer(text):
                if "\n" in treffer.group(1):
                    zeile = text[:treffer.start()].count("\n") + 1
                    befunde.append(f"{datei.relative_to(wurzel)}:{zeile}")

    assert not befunde, (
        "Mehrzeilige {# #}-Kommentare werden sichtbar. "
        "Nimm {% comment %}: " + ", ".join(befunde)
    )


def test_env_beispiel_nennt_jede_einstellung():
    """Was settings.py aus der Umgebung liest, steht in .env.example.

    Beim Umzug auf einen anderen Server wird die neue .env aus dieser Vorlage
    gebaut. Fehlt dort eine Zeile, faellt das nicht als Fehler auf, sondern
    als eine Betriebsart, die still verschwunden ist: Ohne
    SPARK_AUDIO_BASE_URL ist der Mikrofonknopf einfach weg, und niemand sucht
    in der Umgebung danach. Genau zwoelf Zeilen fehlten, als der Umzug
    angekuendigt wurde.
    """
    import re
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[2]
    quelle = (wurzel / "config" / "settings.py").read_text(encoding="utf-8")
    vorlage = (wurzel / ".env.example").read_text(encoding="utf-8")

    gelesen = set(re.findall(r'env[a-z_]*\(\s*"([A-Z0-9_]+)"', quelle))
    genannt = set(re.findall(r"^([A-Z0-9_]+)=", vorlage, re.MULTILINE))

    assert not gelesen - genannt, (
        "In .env.example fehlen: " + ", ".join(sorted(gelesen - genannt))
    )
