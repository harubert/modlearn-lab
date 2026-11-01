"""Pruefungen der Anmeldung ueber das PH-Konto.

Caddy prueft die Person bei login.ph-vorarlberg.at und reicht sie als
X-Auth-Kopfzeilen durch, zusammen mit einem Geheimnis aus einer Datei. Diese
Pruefungen spielen Caddy nach: dieselben Kopfzeilen, einmal mit und einmal
ohne das richtige Geheimnis. Das Geheimnis selbst steht in keiner Ausgabe.
"""

import secrets
from urllib.parse import urlencode

import pytest
from django.contrib.auth import SESSION_KEY, get_user_model
from django.urls import reverse

from core.models import PhKonto
from plan.models import Nutzerklasse, Profil

pytestmark = pytest.mark.django_db

OID = "7d6a1b2c-0f3e-4a5b-9c8d-112233445566"


@pytest.fixture
def geheimnis(settings, tmp_path):
    """Legt die Geheimnisdatei so an, wie sie am Server eingebunden ist.

    Der Wert ist je Lauf zufaellig und wird nirgends ausgegeben: Eine
    Pruefung, die ihr Geheimnis in einer Fehlermeldung zeigt, uebt genau das
    ein, was die Ansicht nie tun darf. Der Zeilenumbruch am Ende ist Absicht,
    so schreibt 'echo' die Datei; die Anwendung muss ihn abschneiden.
    """
    wert = secrets.token_hex(24)
    datei = tmp_path / "lab-proxy"
    datei.write_text(wert + "\n", encoding="utf-8")
    settings.PH_PROXY_SECRET_DATEI = str(datei)
    return wert


@pytest.fixture
def ohne_geheimnis(settings, tmp_path):
    """Der Zustand eines Servers ohne Einrichtung: Die Datei gibt es nicht."""
    settings.PH_PROXY_SECRET_DATEI = str(tmp_path / "gibt-es-nicht")


def _kopfzeilen(geheimnis, **aenderungen):
    """Was Caddy nach einer gelungenen Anmeldung schickt.

    None als Wert laesst die Kopfzeile ganz weg.
    """
    kopf = {
        "X-Auth-Proxy-Secret": geheimnis,
        "X-Auth-Oid": OID,
        "X-Auth-Upn": "anna.muster@ph-vorarlberg.ac.at",
        "X-Auth-Email": "anna.muster@ph-vorarlberg.ac.at",
        "X-Auth-Anmeldename": "anna.muster",
        "X-Auth-Name": "Anna Muster",
        "X-Auth-Vorname": "Anna",
        "X-Auth-Nachname": "Muster",
        "X-Auth-Groups": "lab-nutzer;studierende",
    }
    for name, wert in aenderungen.items():
        if wert is None:
            kopf.pop(name, None)
        else:
            kopf[name] = wert
    return kopf


def _anmelden(client, kopfzeilen, ziel=None):
    adresse = reverse("ph_anmeldung")
    if ziel is not None:
        adresse += "?" + urlencode({"next": ziel})
    # secure=True wie ueberall: Im Betrieb leitet SECURE_SSL_REDIRECT alles
    # Unverschluesselte um, hinter Caddy ist jede Anfrage verschluesselt.
    return client.get(adresse, headers=kopfzeilen, secure=True)


def _angemeldet_als(client):
    return client.session.get(SESSION_KEY)


# --- Der gute Weg ----------------------------------------------------------

def test_erste_anmeldung_legt_konto_benutzer_und_profil_an(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis))

    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:lehrperson_uebersicht")

    konto = PhKonto.objects.get(oid=OID)
    assert konto.email == "anna.muster@ph-vorarlberg.ac.at"
    assert konto.name == "Anna Muster"
    assert konto.gruppen_liste() == ["lab-nutzer", "studierende"]

    benutzer = konto.benutzer
    assert benutzer.username == "ph-anna.muster"
    assert benutzer.first_name == "Anna"
    assert benutzer.last_name == "Muster"
    assert not benutzer.has_usable_password(), "kein Kennwort, kein Formularweg"
    assert not benutzer.is_staff and not benutzer.is_superuser

    profil = Profil.objects.get(benutzer=benutzer)
    assert profil.klasse.name == "Studierende"

    assert _angemeldet_als(client) == str(benutzer.pk)


def test_zweiter_besuch_legt_nichts_doppelt_an_und_zieht_den_namen_nach(client, geheimnis):
    _anmelden(client, _kopfzeilen(geheimnis))
    benutzer = PhKonto.objects.get(oid=OID).benutzer

    # Dazwischen die Hand-Freigabe der Verwaltung: Lehrperson statt
    # Studierende, dazu Verwaltungsrechte. Beides muss die naechste
    # Anmeldung ueberleben.
    lehrperson = Nutzerklasse.objects.get(name="Lehrperson")
    Profil.objects.filter(benutzer=benutzer).update(klasse=lehrperson)
    get_user_model().objects.filter(pk=benutzer.pk).update(is_staff=True)
    client.logout()

    vorher = (
        PhKonto.objects.count(), get_user_model().objects.count(), Profil.objects.count(),
    )
    antwort = _anmelden(client, _kopfzeilen(
        geheimnis,
        **{
            "X-Auth-Name": "Anna Muster-Neu",
            "X-Auth-Nachname": "Muster-Neu",
            "X-Auth-Email": "anna.muster-neu@ph-vorarlberg.ac.at",
            "X-Auth-Upn": "anna.muster-neu@ph-vorarlberg.ac.at",
            "X-Auth-Anmeldename": "anna.muster-neu",
            "X-Auth-Groups": "lab-nutzer;lehrende",
        },
    ))

    assert antwort.status_code == 302
    nachher = (
        PhKonto.objects.count(), get_user_model().objects.count(), Profil.objects.count(),
    )
    assert nachher == vorher, "nichts doppelt angelegt"

    konto = PhKonto.objects.get(oid=OID)
    assert konto.benutzer_id == benutzer.pk, "die Objekt-ID findet dasselbe Konto"
    assert konto.name == "Anna Muster-Neu"
    assert konto.email == "anna.muster-neu@ph-vorarlberg.ac.at"
    assert konto.gruppen_liste() == ["lab-nutzer", "lehrende"]

    benutzer.refresh_from_db()
    assert benutzer.username == "ph-anna.muster", "der Benutzername bleibt"
    assert benutzer.last_name == "Muster-Neu"
    assert benutzer.is_staff, "Rechte bleiben"
    assert Profil.objects.get(benutzer=benutzer).klasse == lehrperson, "Freigabe bleibt"
    assert _angemeldet_als(client) == str(benutzer.pk)


def test_benutzername_bekommt_bei_kollision_einen_zaehler(client, geheimnis):
    get_user_model().objects.create_user(username="ph-anna.muster", password="x")

    _anmelden(client, _kopfzeilen(geheimnis))

    assert PhKonto.objects.get(oid=OID).benutzer.username == "ph-anna.muster-2"


def test_umlaute_aus_den_kopfzeilen_kommen_richtig_an(client, geheimnis):
    """Django liest Kopfzeilen als ISO-8859-1, Caddy schickt UTF-8.

    Was hier ankommt, ist "MÃ¼ller"; gespeichert werden muss "Müller".
    """
    _anmelden(client, _kopfzeilen(
        geheimnis,
        **{"X-Auth-Name": "Jörg Müller".encode("utf-8").decode("latin-1"),
           "X-Auth-Nachname": "Müller".encode("utf-8").decode("latin-1")},
    ))

    konto = PhKonto.objects.get(oid=OID)
    assert konto.name == "Jörg Müller"
    assert konto.benutzer.last_name == "Müller"


def test_ohne_klasse_studierende_die_zurueckhaltendste(client, geheimnis):
    Nutzerklasse.objects.all().delete()
    Nutzerklasse.objects.create(name="Lehrende", max_plaetze=60)
    Nutzerklasse.objects.create(name="Gast", max_plaetze=3)

    _anmelden(client, _kopfzeilen(geheimnis))

    profil = Profil.objects.get(benutzer__phkonto__oid=OID)
    assert profil.klasse.name == "Gast"


def test_ohne_jede_klasse_gelingt_die_anmeldung_trotzdem(client, geheimnis):
    Nutzerklasse.objects.all().delete()

    antwort = _anmelden(client, _kopfzeilen(geheimnis))

    assert antwort.status_code == 302
    assert not Profil.objects.exists()
    assert _angemeldet_als(client) is not None


# --- Das Ziel nach der Anmeldung -------------------------------------------

def test_next_auf_eigenen_pfad_wird_befolgt(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis), ziel="/plan/")

    assert antwort.status_code == 302
    assert antwort["Location"] == "/plan/"


@pytest.mark.parametrize("ziel", [
    "https://boese.example/",
    "//boese.example/plan/",
    "http:///plan/",
    "plan/",
    "javascript:alert(1)",
    "\\\\boese.example/",
])
def test_next_auf_fremden_host_wird_ignoriert(client, geheimnis, ziel):
    antwort = _anmelden(client, _kopfzeilen(geheimnis), ziel=ziel)

    assert antwort.status_code == 302
    assert antwort["Location"] == reverse("tutoring:lehrperson_uebersicht")


# --- Abgewiesen -------------------------------------------------------------

def test_falsches_geheimnis_wird_abgewiesen(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis, **{
        "X-Auth-Proxy-Secret": secrets.token_hex(24),
    }))

    assert antwort.status_code == 403
    assert not PhKonto.objects.exists()
    assert not get_user_model().objects.filter(username__startswith="ph-").exists()
    assert _angemeldet_als(client) is None


def test_fehlendes_geheimnis_wird_abgewiesen(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis, **{"X-Auth-Proxy-Secret": None}))

    assert antwort.status_code == 403
    assert not PhKonto.objects.exists()
    assert _angemeldet_als(client) is None


def test_fehlende_oid_wird_abgewiesen(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis, **{"X-Auth-Oid": None}))

    assert antwort.status_code == 403
    assert not PhKonto.objects.exists()
    assert _angemeldet_als(client) is None


def test_leere_oid_wird_abgewiesen(client, geheimnis):
    antwort = _anmelden(client, _kopfzeilen(geheimnis, **{"X-Auth-Oid": "   "}))

    assert antwort.status_code == 403
    assert not PhKonto.objects.exists()


def test_abweisung_verraet_nicht_was_gefehlt_hat(client, geheimnis):
    ohne_geheimnis = _anmelden(client, _kopfzeilen(geheimnis, **{"X-Auth-Proxy-Secret": None}))
    ohne_oid = _anmelden(client, _kopfzeilen(geheimnis, **{"X-Auth-Oid": None}))

    assert ohne_geheimnis.status_code == ohne_oid.status_code == 403
    assert ohne_geheimnis.content == ohne_oid.content
    assert geheimnis.encode() not in ohne_geheimnis.content


def test_gesperrter_benutzer_kommt_nicht_herein(client, geheimnis):
    _anmelden(client, _kopfzeilen(geheimnis))
    benutzer = PhKonto.objects.get(oid=OID).benutzer
    get_user_model().objects.filter(pk=benutzer.pk).update(is_active=False)
    client.logout()

    antwort = _anmelden(client, _kopfzeilen(geheimnis))

    assert antwort.status_code == 403
    assert _angemeldet_als(client) is None


def test_nur_get(client, geheimnis):
    antwort = client.post(reverse("ph_anmeldung"), headers=_kopfzeilen(geheimnis), secure=True)

    assert antwort.status_code == 405
    assert not PhKonto.objects.exists()


# --- Ohne Geheimnisdatei ---------------------------------------------------

def test_ohne_datei_antwortet_die_seite_ruhig_und_meldet_niemanden_an(client, ohne_geheimnis):
    # Kopfzeilen wie von Caddy, mit irgendeinem Geheimnis: Ohne Datei gibt
    # es nichts, womit es stimmen koennte, also auch keine Anmeldung.
    antwort = _anmelden(client, _kopfzeilen(secrets.token_hex(24)))

    assert antwort.status_code in (403, 503)
    assert not PhKonto.objects.exists()
    assert _angemeldet_als(client) is None


def test_ohne_datei_fehlt_der_knopf_auf_der_anmeldeseite(client, ohne_geheimnis):
    seite = client.get(reverse("anmelden"), secure=True)

    assert seite.status_code == 200
    assert "Mit PH-Konto anmelden" not in seite.content.decode()
    assert reverse("ph_anmeldung") not in seite.content.decode()


# --- Die Anmeldeseite ------------------------------------------------------

def test_anmeldeseite_zeigt_den_knopf_und_reicht_next_durch(client, geheimnis):
    seite = client.get(reverse("anmelden") + "?next=/plan/", secure=True)
    inhalt = seite.content.decode()

    assert seite.status_code == 200
    assert "Mit PH-Konto anmelden" in inhalt
    assert reverse("ph_anmeldung") + "?next=/plan/" in inhalt
    assert 'name="password"' in inhalt, "das bisherige Formular bleibt"
    assert geheimnis not in inhalt


def test_anmeldeseite_reicht_fremde_ziele_nicht_durch(client, geheimnis):
    seite = client.get(reverse("anmelden") + "?next=https://boese.example/", secure=True)

    assert "boese.example" not in seite.content.decode()
