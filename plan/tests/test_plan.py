"""Pruefungen des Planungswerkzeugs.

Worum es geht: Gebucht wird nicht die Maschine, sondern ein Anteil davon.
Eine Buchung ist eine Zusage und keine Sperre - solange Plaetze frei sind,
darf jeder arbeiten.

Seit den Nutzungskonzepten mit einer Ausnahme: Plaetze addieren sich,
Modelle nicht. Eine Buchung, die den Rechner umbaut oder ganz nimmt, ist
alleinig, und daneben geht nichts - egal wie viele Plaetze frei waeren.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from plan import konzepte
from plan.messung import hoechste_gleichzeitigkeit
from plan.models import Buchung, Nutzerklasse, Profil, belegung

pytestmark = pytest.mark.django_db


@pytest.fixture
def klasse(db):
    # Die Probeklasse darf auch die zwei Konzepte, die den Rechner umbauen:
    # Sonst liesse sich die Vertraeglichkeit nicht pruefen. "entwicklung"
    # bekommt sie bewusst nicht, damit ein Test zeigen kann, dass die Seite
    # nur Erlaubtes anbietet.
    return Nutzerklasse.objects.create(
        name="Probe", max_minuten=120, max_slots_woche=3, max_plaetze=30,
        konzepte="unterricht,wissensdienst,modellschulung",
    )


@pytest.fixture
def lehrerin(klasse):
    person = get_user_model().objects.create_user(
        username="lehrerin", password="geheim"
    )
    Profil.objects.create(benutzer=person, klasse=klasse)
    return person


def _morgen(stunde, minute=0):
    tag = timezone.localdate() + timedelta(days=1)
    roh = timezone.datetime.combine(tag, timezone.datetime.min.time())
    return timezone.make_aware(roh) + timedelta(hours=stunde, minutes=minute)


def _raster(tag):
    """Minute zu vergebenen Plaetzen, ohne die Konzepte."""
    return {minute: belegt for minute, belegt, _ in belegung(tag)}


def _buchen(client, person, von="08:00", bis="08:50", plaetze=20, tage=1,
            konzept="unterricht", fach="", wer=""):
    """Zwanzig Plaetze Unterricht: ein Vielfaches von zehn, unter der
    Klassengrenze von dreissig und unter den sechzig Prozent, die der
    Unterricht vom Ganzen nehmen darf."""
    client.force_login(person)
    tag = (timezone.localdate() + timedelta(days=tage)).isoformat()
    return client.post(reverse("plan:buchen"), {
        "datum": tag, "von": von, "bis": bis,
        "plaetze": plaetze, "zweck": "Mathe 4a",
        "konzept": konzept, "fach": fach, "person": wer,
    }, secure=True)


# --- Die Belegung ---------------------------------------------------------

def test_eine_buchung_belegt_nur_ihren_zeitraum(lehrerin):
    tag = timezone.localdate() + timedelta(days=1)
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10), ende=_morgen(11), plaetze=25
    )

    raster = _raster(tag)

    assert raster[9 * 60 + 45] == 0, "vorher ist frei"
    assert raster[10 * 60] == 25
    assert raster[10 * 60 + 45] == 25
    assert raster[11 * 60] == 0, "nach dem Ende ist wieder frei"


def test_zwei_buchungen_addieren_sich(lehrerin):
    """Der Kern: Der Rechner wird geteilt, nicht vergeben."""
    tag = timezone.localdate() + timedelta(days=1)
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10), ende=_morgen(11), plaetze=25
    )
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10, 30), ende=_morgen(11, 30), plaetze=10
    )

    raster = _raster(tag)

    assert raster[10 * 60] == 25
    assert raster[10 * 60 + 30] == 35, "beide zusammen"
    assert raster[11 * 60 + 15] == 10


def test_eine_abgesagte_buchung_belegt_nichts(lehrerin):
    tag = timezone.localdate() + timedelta(days=1)
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10), ende=_morgen(11), plaetze=25,
        abgesagt_am=timezone.now(),
    )

    assert _raster(tag)[10 * 60] == 0


# --- Die Grenzen der Nutzerklasse ----------------------------------------

def test_eine_buchung_im_rahmen_geht_durch(client, lehrerin):
    antwort = _buchen(client, lehrerin)

    assert antwort.status_code == 302
    assert Buchung.objects.filter(besitzer=lehrerin).count() == 1


def test_zu_lang_wird_abgelehnt(client, lehrerin):
    """Die Klasse erlaubt 120 Minuten."""
    antwort = _buchen(client, lehrerin, von="08:00", bis="11:00")

    assert antwort.status_code == 200
    assert "höchstens 120 Minuten" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_zu_viele_plaetze_werden_abgelehnt(client, lehrerin):
    antwort = _buchen(client, lehrerin, plaetze=99)

    assert "höchstens 30 Plätze" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_das_wochenkontingent_greift(client, lehrerin):
    """Drei sind erlaubt, die vierte nicht."""
    for stunde in (8, 9, 10):
        _buchen(client, lehrerin, von=f"{stunde:02d}:00", bis=f"{stunde:02d}:50")

    antwort = _buchen(client, lehrerin, von="11:00", bis="11:50")

    assert "Kontingent" in antwort.content.decode()
    assert Buchung.objects.count() == 3


def test_ein_gesperrter_zugang_bucht_nicht(client, lehrerin):
    profil = lehrerin.planprofil
    profil.gesperrt_am = timezone.now()
    profil.save(update_fields=["gesperrt_am"])

    antwort = _buchen(client, lehrerin)

    assert "gesperrt" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_ausserhalb_des_tages_wird_abgelehnt(client, lehrerin):
    antwort = _buchen(client, lehrerin, von="05:00", bis="05:50")

    assert "zwischen 7:00" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_das_ende_muss_nach_dem_beginn_liegen(client, lehrerin):
    antwort = _buchen(client, lehrerin, von="10:00", bis="09:00")

    assert "Ende nach" in antwort.content.decode()
    assert not Buchung.objects.exists()


# --- Die Kapazitaet -------------------------------------------------------

def test_ueber_die_kapazitaet_hinaus_geht_nicht(client, lehrerin, settings):
    """Von 30 Plätzen sind 27 buchbar, ein Zehntel bleibt frei.

    In Zehnerschritten, weil Unterricht so gebucht wird: Zwei Klassen zu
    zehn stehen, die dritte braeuchte dreissig von siebenundzwanzig.
    """
    settings.SPARK_PLAETZE = 30
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=10)
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=10)

    antwort = _buchen(client, lehrerin, von="10:30", bis="11:00", plaetze=10)

    assert "nur noch 7 von 27" in antwort.content.decode()
    assert Buchung.objects.count() == 2


def test_daneben_passt_es_weiterhin(client, lehrerin, settings):
    """Eine Buchung ist eine Zusage, keine Sperre."""
    settings.SPARK_PLAETZE = 30
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=10)

    antwort = _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=10)

    assert antwort.status_code == 302
    assert Buchung.objects.count() == 2


def test_ein_zehntel_bleibt_unbuchbar(client, lehrerin, klasse, settings):
    """Wer nicht gebucht hat, soll trotzdem arbeiten koennen.

    Mit dem Konzept "entwicklung", denn nur ein Konzept mit vollem Anteil
    kommt ueberhaupt bis an das Zehntel heran - der Unterricht nimmt
    hoechstens sechzig Prozent und scheitert frueher.
    """
    settings.SPARK_PLAETZE = 30
    klasse.max_plaetze = 30
    klasse.konzepte = "entwicklung"
    klasse.save(update_fields=["max_plaetze", "konzepte"])

    antwort = _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=28,
                      konzept="entwicklung")

    assert "nur noch 27 von 27" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_eine_klasse_darf_die_maschine_ganz_belegen(client, lehrerin, klasse, settings):
    """Die Ausnahme fuer den Lasttest, der absichtlich bis an den Rand fuellt."""
    settings.SPARK_PLAETZE = 30
    klasse.max_plaetze = 30
    klasse.darf_voll_belegen = True
    klasse.konzepte = "entwicklung"
    klasse.save(update_fields=["max_plaetze", "darf_voll_belegen", "konzepte"])

    antwort = _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=30,
                      konzept="entwicklung")

    assert antwort.status_code == 302
    assert Buchung.objects.get().plaetze == 30


def test_der_balken_rechnet_mit_den_buchbaren_plaetzen(client, lehrerin, settings):
    """Sonst nennt die Lage am Regler eine Zahl, die das Absenden ablehnt."""
    settings.SPARK_PLAETZE = 30
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:tag"), secure=True)

    assert antwort.context["plaetze_gesamt"] == 30
    assert antwort.context["plaetze_buchbar"] == 27
    assert antwort.context["raster"][0]["frei"] == 27


# --- Absagen --------------------------------------------------------------

def test_eine_eigene_buchung_laesst_sich_absagen(client, lehrerin):
    _buchen(client, lehrerin)
    gebucht = Buchung.objects.get()

    client.post(reverse("plan:absagen"), {"pk": gebucht.pk}, secure=True)

    gebucht.refresh_from_db()
    assert gebucht.abgesagt_am is not None
    assert Buchung.objects.count() == 1, "abgesagt, nicht geloescht"


def test_fremde_buchungen_lassen_sich_nicht_absagen(client, lehrerin, klasse):
    _buchen(client, lehrerin)
    gebucht = Buchung.objects.get()
    andere = get_user_model().objects.create_user(username="andere", password="x")
    Profil.objects.create(benutzer=andere, klasse=klasse)

    client.force_login(andere)
    client.post(reverse("plan:absagen"), {"pk": gebucht.pk}, secure=True)

    gebucht.refresh_from_db()
    assert gebucht.abgesagt_am is None


# --- Die Messung ----------------------------------------------------------

def test_gleichzeitigkeit_zaehlt_ueberlappung_nicht_anfragen():
    """Zwanzig Anfragen in einer Minute koennen nacheinander gelaufen sein."""
    jetzt = timezone.now()
    nacheinander = [
        (jetzt, jetzt + timedelta(seconds=4)),
        (jetzt + timedelta(seconds=5), jetzt + timedelta(seconds=9)),
        (jetzt + timedelta(seconds=10), jetzt + timedelta(seconds=14)),
    ]

    assert hoechste_gleichzeitigkeit(nacheinander) == 1


def test_echte_ueberlappung_wird_gezaehlt():
    jetzt = timezone.now()
    gleichzeitig = [
        (jetzt, jetzt + timedelta(seconds=6)),
        (jetzt + timedelta(seconds=1), jetzt + timedelta(seconds=7)),
        (jetzt + timedelta(seconds=2), jetzt + timedelta(seconds=3)),
    ]

    assert hoechste_gleichzeitigkeit(gleichzeitig) == 3


def test_ohne_anfragen_ist_die_spitze_null():
    assert hoechste_gleichzeitigkeit([]) == 0


# --- Die Seiten -----------------------------------------------------------

def test_der_tagesplan_rendert(client, lehrerin):
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:tag"), secure=True)

    assert antwort.status_code == 200
    assert antwort.context["plaetze_gesamt"] > 0
    assert len(antwort.context["raster"]) == 48, "sieben bis neunzehn Uhr"


def test_der_rueckblick_rendert(client, lehrerin):
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:rueckblick"), secure=True)

    assert antwort.status_code == 200


def test_der_plan_ist_nicht_oeffentlich(client):
    antwort = client.get(reverse("plan:tag"), secure=True)

    assert antwort.status_code == 302
    assert "anmelden" in antwort["Location"]


# --- Was nach einer Absage im Formular steht ------------------------------

def test_eine_abgewiesene_buchung_behaelt_die_eingabe(client, lehrerin):
    """Wer eine Fehlermeldung bekommt, soll nicht alles neu tippen."""
    client.force_login(lehrerin)
    tag_ = (timezone.localdate() + timedelta(days=1)).isoformat()

    antwort = client.post(reverse("plan:buchen"), {
        "datum": tag_, "von": "08:00", "bis": "11:00",
        "plaetze": 22, "zweck": "Deutsch 2b, Lesen",
    }, secure=True)

    vorgabe = antwort.context["vorgabe"]
    assert vorgabe["von"] == "08:00"
    assert vorgabe["bis"] == "11:00"
    assert vorgabe["plaetze"] == 22
    assert vorgabe["zweck"] == "Deutsch 2b, Lesen"
    assert "Deutsch 2b, Lesen" in antwort.content.decode()


def test_die_vorgabe_kennt_ihre_lage_im_balken(client, lehrerin):
    """von_min und dauer_min sind Minuten ab 07:00 - das erwartet das CSS."""
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:tag"), secure=True)

    vorgabe = antwort.context["vorgabe"]
    assert vorgabe["von_min"] == 60, "08:00 ist 60 Minuten nach 07:00"
    assert vorgabe["dauer_min"] == 50


def test_ohne_kontingent_steht_kein_formular_da(client, lehrerin):
    """Ein Formular, das jedes Mal dasselbe absagt, ist schlechter als keines."""
    for stunde in (8, 9, 10):
        _buchen(client, lehrerin, von=f"{stunde:02d}:00", bis=f"{stunde:02d}:50")

    client.force_login(lehrerin)
    seite = client.get(
        reverse("plan:tag"),
        {"datum": (timezone.localdate() + timedelta(days=1)).isoformat()},
        secure=True,
    ).content.decode()

    assert 'id="plan-form"' not in seite
    assert "Kontingent" in seite


# --- Schaetzung gegen Messung --------------------------------------------

def test_der_rueckblick_stellt_buchung_neben_messung(lehrerin):
    """Der Teil, auf den es ankommt: war die Schaetzung richtig?"""
    from tutoring.models import Interaction

    from plan.messung import vergleich

    heute = timezone.localdate()
    roh = timezone.datetime.combine(heute, timezone.datetime.min.time())
    Buchung.objects.create(
        besitzer=lehrerin,
        beginn=timezone.make_aware(roh) + timedelta(hours=10),
        ende=timezone.make_aware(roh) + timedelta(hours=11),
        plaetze=25,
    )
    # Drei Anfragen von je einer Minute, im selben Augenblick angelegt: Sie
    # ueberlappen sich also sicher.
    for nummer in range(3):
        Interaction.objects.create(
            session_key=f"s{nummer}", duration_ms=60_000
        )

    heutige = next(z for z in vergleich(2) if z["tag"] == heute)

    assert heutige["gebucht"] == 25
    assert heutige["spitze"] == 3
    assert heutige["anfragen"] == 3
    assert heutige["ueberschaetzt"] == 22, "22 Plätze waren zugesagt und leer"


# --- Der Befehl fuer die Zugaenge -----------------------------------------

def test_der_befehl_legt_einen_zugang_mit_klasse_an(klasse):
    from io import StringIO

    from django.core.management import call_command

    aus = StringIO()
    call_command("plan_zugang", "neue", klasse="Probe", kennwort="sehrgeheim1",
                 stdout=aus)

    person = get_user_model().objects.get(username="neue")
    assert person.planprofil.klasse == klasse
    assert person.check_password("sehrgeheim1")
    assert "Probe" in aus.getvalue()


def test_der_befehl_wechselt_die_klasse_ohne_kennwort(klasse, lehrerin):
    from io import StringIO

    from django.core.management import call_command

    gross = Nutzerklasse.objects.create(name="Lab gross", max_plaetze=120)

    call_command("plan_zugang", "lehrerin", klasse="lab gross", stdout=StringIO())

    lehrerin.planprofil.refresh_from_db()
    assert lehrerin.planprofil.klasse == gross


def test_der_befehl_schuetzt_das_umgebungskonto(settings, klasse):
    """lehrperson_anlegen setzt is_superuser bei jedem Start zurueck."""
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    settings.TEACHER_USERNAME = "lehrperson"
    get_user_model().objects.create_user(username="lehrperson", password="x")

    with pytest.raises(CommandError, match="eigenes Konto"):
        call_command("plan_zugang", "lehrperson", verwaltung=True, stdout=StringIO())

    assert not get_user_model().objects.get(username="lehrperson").is_superuser


def test_der_befehl_lehnt_eine_unbekannte_klasse_ab(klasse, lehrerin):
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="Vorhanden"):
        call_command("plan_zugang", "lehrerin", klasse="Erfunden", stdout=StringIO())


def test_das_zahlenfeld_haengt_an_der_engsten_grenze(
    client, lehrerin, klasse, settings
):
    """Lab darf 120, buchbar sind 108, der Unterricht nimmt 60 Prozent.

    Das Hoechstmass des Konzepts ist die engste der drei Grenzen, auf den
    Zehnerschritt abgerundet: 72 wird zu 70. Voreingestellt wird beim
    Unterricht aber eine Klasse, nicht das Hoechstmass - sechzig Kinder
    sind nie der Normalfall.
    """
    settings.SPARK_PLAETZE = 120
    klasse.max_plaetze = 120
    klasse.save(update_fields=["max_plaetze"])
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:tag"), secure=True)

    assert antwort.context["meine"]["max_plaetze"] == 120, "was die Klasse erlaubt"
    assert antwort.context["meine"]["max_jetzt"] == 108, "was davon buchbar ist"
    assert antwort.context["gewaehlt"]["schluessel"] == "unterricht"
    assert antwort.context["gewaehlt"]["max_plaetze"] == 70, "60 Prozent, auf Zehner"
    assert antwort.context["vorgabe"]["plaetze"] == 30, "eine Klasse"


# --- Die Nutzungskonzepte ------------------------------------------------
#
# Plaetze addieren sich, Modelle nicht. Was hier geprueft wird, ist die
# Frage, die es vor den Konzepten nicht gab: Koennen zwei Buchungen
# ueberhaupt nebeneinander laufen?

def test_unterricht_neben_unterricht_geht(client, lehrerin):
    """Der Normalfall: Zwei Klassen teilen den Rechner."""
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=20)

    antwort = _buchen(client, lehrerin, von="10:30", bis="11:20", plaetze=20)

    assert antwort.status_code == 302
    assert Buchung.objects.count() == 2


def test_wissensdienst_neben_unterricht_geht_nicht(client, lehrerin):
    """Der Wissensdienst braucht ein Modell, das nicht im Speicher liegt.

    Zwei Plaetze von hundertacht waeren frei - und trotzdem nein, mit
    einem Satz, der sagt, warum.
    """
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=20)

    antwort = _buchen(client, lehrerin, von="10:30", bis="11:20", plaetze=2,
                      konzept="wissensdienst")

    seite = antwort.content.decode()
    assert antwort.status_code == 200
    assert "erst geladen werden" in seite, "der Grund steht auf der Seite"
    assert "um 10:30" in seite, "die Uhrzeit des ersten Konflikts"
    assert "Unterricht mit einer Klasse" in seite
    assert Buchung.objects.count() == 1


def test_unterricht_neben_wissensdienst_geht_auch_nicht(client, lehrerin):
    """Die andere Richtung: Der Umbau steht schon, die Klasse kommt dazu."""
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=1,
            konzept="wissensdienst")

    antwort = _buchen(client, lehrerin, von="10:30", bis="11:20", plaetze=20)

    seite = antwort.content.decode()
    assert "Dafür wird der Rechner umgebaut" in seite
    assert "Um 10:30" in seite
    assert Buchung.objects.count() == 1


def test_modellschulung_neben_allem_nicht(client, lehrerin, klasse):
    """Die Schulung belegt die GPU: nicht neben Unterricht, nicht neben
    einer zweiten Schulung, und nichts neben ihr."""
    klasse.max_slots_woche = 10
    klasse.save(update_fields=["max_slots_woche"])
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=20)

    neben_unterricht = _buchen(client, lehrerin, von="10:00", bis="10:50",
                               plaetze=1, konzept="modellschulung")
    assert neben_unterricht.status_code == 200
    assert Buchung.objects.count() == 1

    allein = _buchen(client, lehrerin, von="12:00", bis="12:50", plaetze=1,
                     konzept="modellschulung")
    assert allein.status_code == 302, "ohne Nachbarn geht es"

    zweite = _buchen(client, lehrerin, von="12:00", bis="12:50", plaetze=1,
                     konzept="modellschulung")
    assert zweite.status_code == 200, "auch nicht zweimal dasselbe"

    klasse_dazu = _buchen(client, lehrerin, von="12:30", bis="13:20", plaetze=10)
    assert klasse_dazu.status_code == 200
    assert "Ein Modell schulen" in klasse_dazu.content.decode()
    assert Buchung.objects.count() == 2


def test_die_vertraeglichkeit_kommt_vor_der_kapazitaet(client, lehrerin, settings):
    """Neben einer Modellschulung sind null Plaetze frei - aber das ist
    nicht die Auskunft, die jemand braucht."""
    settings.SPARK_PLAETZE = 120
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=1,
            konzept="modellschulung")

    antwort = _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=10)

    seite = antwort.content.decode()
    assert "nur noch 0 von" not in seite
    assert "umgebaut" in seite


def test_plaetze_25_beim_unterricht_abgelehnt_30_angenommen(client, lehrerin):
    """Unterricht wird in Zehnerschritten gebucht."""
    abgelehnt = _buchen(client, lehrerin, plaetze=25)

    assert abgelehnt.status_code == 200
    assert "Schritten von 10" in abgelehnt.content.decode()
    assert not Buchung.objects.exists()

    angenommen = _buchen(client, lehrerin, plaetze=30)

    assert angenommen.status_code == 302
    assert Buchung.objects.get().plaetze == 30


def test_der_anteil_des_konzepts_deckelt_die_plaetze(client, lehrerin, klasse, settings):
    """Unterricht nimmt hoechstens 60 Prozent: von 120 sind das 72."""
    settings.SPARK_PLAETZE = 120
    klasse.max_plaetze = 120
    klasse.save(update_fields=["max_plaetze"])

    antwort = _buchen(client, lehrerin, plaetze=80)

    assert "60 Prozent" in antwort.content.decode()
    assert "72 Plätze" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_ein_konzept_ausserhalb_der_nutzerklasse_wird_abgelehnt(client, lehrerin):
    """Die Probeklasse darf "entwicklung" nicht - die Seite zeigt es nicht,
    und ein nachgebautes Formular kommt damit auch nicht durch."""
    antwort = _buchen(client, lehrerin, plaetze=5, konzept="entwicklung")

    assert "nicht freigegeben" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_ein_unbekanntes_konzept_wird_abgelehnt(client, lehrerin):
    antwort = _buchen(client, lehrerin, konzept="zauberei")

    assert antwort.status_code == 200
    assert not Buchung.objects.exists()


def test_eine_alleinige_buchung_macht_die_belegung_voll(lehrerin, settings):
    """Ein Platz Modellschulung zaehlt wie alle: Der Balken zeigt voll."""
    settings.SPARK_PLAETZE = 120
    tag = timezone.localdate() + timedelta(days=1)
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10), ende=_morgen(11), plaetze=1,
        konzept="modellschulung",
    )

    raster = {minute: (belegt, laufend) for minute, belegt, laufend in belegung(tag)}

    assert raster[10 * 60] == (120, ("modellschulung",))
    assert raster[10 * 60 + 45][0] == 120
    assert raster[11 * 60] == (0, ()), "danach ist wieder frei"


def test_die_belegung_nennt_die_laufenden_konzepte(lehrerin):
    """Jedes Konzept einmal, in der Reihenfolge des Beginns."""
    tag = timezone.localdate() + timedelta(days=1)
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10), ende=_morgen(11), plaetze=20,
        konzept="unterricht",
    )
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10, 30), ende=_morgen(11, 30), plaetze=10,
        konzept="unterricht",
    )
    Buchung.objects.create(
        besitzer=lehrerin, beginn=_morgen(10, 45), ende=_morgen(11), plaetze=3,
        konzept="sichere_verwaltung",
    )

    raster = {minute: laufend for minute, _, laufend in belegung(tag)}

    assert raster[10 * 60] == ("unterricht",)
    assert raster[10 * 60 + 30] == ("unterricht",), "zweimal Unterricht ist einmal"
    assert raster[10 * 60 + 45] == ("unterricht", "sichere_verwaltung")


def test_die_seite_zeigt_nur_erlaubte_konzepte(client, lehrerin):
    client.force_login(lehrerin)

    antwort = client.get(reverse("plan:tag"), secure=True)

    gezeigt = [k["schluessel"] for k in antwort.context["konzepte"]]
    assert gezeigt == ["unterricht", "wissensdienst", "modellschulung"]
    seite = antwort.content.decode()
    assert 'value="entwicklung"' not in seite
    assert 'value="sichere_verwaltung"' not in seite
    assert 'value="unterricht"' in seite


def test_die_nutzerklasse_liest_ihre_konzepte_nachsichtig(klasse):
    """Leerzeichen, Grossschreibung und ein Tippfehler im Admin sperren
    niemanden aus - nur das Unbekannte faellt weg."""
    klasse.konzepte = " Unterricht , modellschulung,zauberei"

    assert klasse.erlaubte_konzepte() == ["unterricht", "modellschulung"]
    assert klasse.darf_konzept("modellschulung")
    assert not klasse.darf_konzept("zauberei")


def test_ohne_erlaubtes_konzept_steht_kein_formular_da(client, lehrerin, klasse):
    klasse.konzepte = ""
    klasse.save(update_fields=["konzepte"])
    client.force_login(lehrerin)

    seite = client.get(reverse("plan:tag"), secure=True).content.decode()

    assert 'id="plan-form"' not in seite
    assert "kein Nutzungskonzept" in seite


def test_der_unterricht_speichert_fach_und_person(client, lehrerin):
    antwort = _buchen(client, lehrerin, fach="mathematik", wer="Frau Berger, 4a")

    assert antwort.status_code == 302
    gebucht = Buchung.objects.get()
    assert gebucht.konzept == "unterricht"
    assert gebucht.fach == "mathematik"
    assert gebucht.person == "Frau Berger, 4a"
    assert gebucht.fach_name == "Mathematik"


def test_ein_konzept_ohne_schuelerzahl_verwirft_fach_und_person(client, lehrerin):
    """Die Seite zeigt die Felder dort nicht; was trotzdem ankommt, faellt
    weg, damit kein Fach an einer Modellschulung haengt."""
    antwort = _buchen(client, lehrerin, plaetze=1, konzept="modellschulung",
                      fach="deutsch", wer="jemand")

    assert antwort.status_code == 302
    gebucht = Buchung.objects.get()
    assert gebucht.fach == ""
    assert gebucht.person == ""


def test_ein_unbekanntes_fach_wird_abgelehnt(client, lehrerin):
    antwort = _buchen(client, lehrerin, fach="astrologie")

    assert "Fach gibt es hier nicht" in antwort.content.decode()
    assert not Buchung.objects.exists()


def test_eine_abgewiesene_buchung_behaelt_ihr_konzept(client, lehrerin):
    antwort = _buchen(client, lehrerin, von="08:00", bis="11:00", plaetze=1,
                      konzept="wissensdienst", wer="x")

    assert antwort.context["vorgabe"]["konzept"] == "wissensdienst"
    assert antwort.context["gewaehlt"]["schluessel"] == "wissensdienst"


def test_die_bestehenden_buchungen_tragen_das_konzept_in_die_seite(client, lehrerin):
    """Balken, Liste und Raster nennen das Konzept - mit Symbol."""
    _buchen(client, lehrerin, von="10:00", bis="10:50", plaetze=1,
            konzept="modellschulung")
    client.force_login(lehrerin)

    antwort = client.get(
        reverse("plan:tag"),
        {"datum": (timezone.localdate() + timedelta(days=1)).isoformat()},
        secure=True,
    )

    seite = antwort.content.decode()
    eintrag = antwort.context["buchungen"][0]
    assert eintrag["alleinig"]
    assert eintrag["konzept_name"] == "Ein Modell schulen"
    assert eintrag["symbol"] == konzepte.symbol("modellschulung")
    assert "plan-block ist-eigen ist-alleinig" in seite
    assert 'data-konzepte="modellschulung"' in seite
    zelle = next(r for r in antwort.context["raster"] if r["zeit"] == "10:15")
    assert zelle["alleinig"] and zelle["frei"] == 0 and zelle["anteil"] == 100


def test_der_rueckblick_nennt_das_konzept_der_groessten_buchung(lehrerin):
    from plan.messung import vergleich

    heute = timezone.localdate()
    roh = timezone.make_aware(
        timezone.datetime.combine(heute, timezone.datetime.min.time())
    )
    Buchung.objects.create(
        besitzer=lehrerin, beginn=roh + timedelta(hours=9),
        ende=roh + timedelta(hours=10), plaetze=5, konzept="sichere_verwaltung",
    )
    Buchung.objects.create(
        besitzer=lehrerin, beginn=roh + timedelta(hours=10),
        ende=roh + timedelta(hours=11), plaetze=30, konzept="unterricht",
    )

    heutige = next(z for z in vergleich(2) if z["tag"] == heute)

    assert heutige["gebucht"] == 30
    assert heutige["konzept"] == "unterricht"
    assert heutige["konzept_name"] == "Unterricht mit einer Klasse"


def test_die_vertraeglichkeit_im_katalog():
    """Die Regel selbst, ohne Datenbank: dasselbe Konzept zweimal geht,
    ausser es ist alleinig; und alleinig geht mit nichts."""
    assert konzepte.vertraeglich("unterricht", "unterricht")
    assert konzepte.vertraeglich("unterricht", "sichere_verwaltung")
    assert not konzepte.vertraeglich("unterricht", "wissensdienst")
    assert not konzepte.vertraeglich("modellschulung", "modellschulung")
    assert not konzepte.vertraeglich("entwicklung", "unterricht")
    assert not konzepte.vertraeglich("unterricht", "zauberei")
