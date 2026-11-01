"""Pruefungen der Projektseite: oeffentlich, vollstaendig, verlinkt, ohne Em-Dash,
ohne Emoji, ohne Geraetepreis, mit einem Namen nur im Impressum.

Die Seite unter /projekt/ erklaert das ganze Vorhaben. Sie braucht keine
Anmeldung und keine Datenbank. Was sie nennt und wohin sie fuehrt, steht
hier fest, damit ein Umbau der Serie nicht still ein Werkzeug von der Seite
nimmt oder einen Weg dorthin kappt.
"""

import re

import pytest

# Die sechs Werkzeuge der Serie, mit dem Wort, das auf der Seite stehen muss.
WERKZEUGE = (
    "Aufgabenhilfe",
    "Trainer",
    "Sprechcoach",
    "Qualitätssicherung",
    "Platz buchen",
    "PH-Konto",
)

# Wohin die Seite fuehren muss: die drei fachlichen Erklaerungen, die
# Anmeldung und das Buchungswerkzeug.
WEGE = (
    "/stufen/",
    "/trainer-erklaerung/",
    "/sprechcoach-erklaerung/",
    "/anmelden/",
    "/plan/",
)


def _seite(client, pfad="/projekt/"):
    # secure=True wie in test_basis: Hinter Caddy ist jede echte Anfrage
    # verschluesselt, und SECURE_SSL_REDIRECT leitet im Betrieb alles andere um.
    antwort = client.get(pfad, secure=True)
    assert antwort.status_code == 200, pfad
    return antwort.content.decode()


def test_rendert_ohne_anmeldung(client):
    """Kein Login, und kein django_db: Die Seite darf die Datenbank nicht
    brauchen. pytest-django bricht sonst mit "Database access not allowed" ab."""
    seite = _seite(client)

    assert "AI LAB" in seite and "Lernschule" not in seite
    assert "PH Vorarlberg" in seite


def test_nennt_alle_sechs_werkzeuge(client):
    seite = _seite(client)

    for name in WERKZEUGE:
        assert name in seite, name


def test_verlinkt_erklaerungen_anmeldung_und_buchung(client):
    seite = _seite(client)

    for pfad in WEGE:
        assert f'href="{pfad}"' in seite, pfad


@pytest.mark.django_db  # Die Startseite raeumt verfallene Sitzungen auf.
def test_startseite_verlinkt_die_projektseite(client):
    seite = _seite(client, "/")

    assert 'href="/projekt/"' in seite
    assert "Was ist das hier?" in seite


def test_fuss_jeder_seite_verlinkt_die_projektseite(client):
    # Geprueft an einer Seite, die base.html nutzt, selbst nichts zum
    # Projekt sagt und keine Datenbank braucht.
    seite = _seite(client, "/stufen/")

    assert 'href="/projekt/"' in seite
    assert "Über das Projekt" in seite


def test_kein_em_dash_auf_der_seite(client):
    """Schreibweise des Projekts: " – " (U+2013 mit Leerzeichen), nie U+2014."""
    seite = _seite(client)

    # chr() statt des Zeichens selbst: Die Testdatei soll das, was sie
    # verbietet, nicht enthalten.
    assert chr(0x2014) not in seite


def test_kein_emoji_auf_der_seite(client):
    """Vorgabe des Auftraggebers: keine Emoji, unter keinen Umstaenden.
    Geprueft werden die Bloecke ab U+1F000 und die Symbole und Dingbats
    U+2600 bis U+27BF, in denen die alten Emoji stehen."""
    seite = _seite(client)

    verboten = sorted({
        f"U+{ord(z):04X}" for z in seite
        if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF
    })
    assert not verboten, verboten


def test_nennt_keinen_geraetepreis(client):
    seite = _seite(client)

    assert "5.000" not in seite
    assert "5000" not in seite


def test_name_nur_im_impressum(client):
    """Der Name des Verantwortlichen steht im Impressum, nicht im Kopf und
    nicht im Text. Gesucht wird der Abschnitt mit id="impressum" bis zu
    seinem schliessenden </section>."""
    seite = _seite(client)

    treffer = re.search(r'<section[^>]*id="impressum"[^>]*>.*?</section>', seite, re.S)
    assert treffer, "Kein Abschnitt mit id=impressum"
    impressum = treffer.group(0)
    rest = seite[:treffer.start()] + seite[treffer.end():]

    assert "Schroffenegger" in impressum
    assert "Schroffenegger" not in rest
    assert "ModLearn Technology Lab" in impressum


def test_nennt_den_pilotbetrieb_dsgvo_konform(client):
    seite = _seite(client)

    assert "Pilotprojekt" in seite
    assert "DSGVO-konform" in seite


def test_bilder_haben_alt_texte(client):
    seite = _seite(client)

    bilder = re.findall(r'<img[^>]*src="/static/img/projekt/[^"]+"[^>]*>', seite)
    assert bilder, "Die Illustrationen fehlen"
    for bild in bilder:
        alt = re.search(r'alt="([^"]*)"', bild)
        assert alt and len(alt.group(1)) > 20, bild
