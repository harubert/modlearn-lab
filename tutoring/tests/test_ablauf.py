"""Pruefungen des Ablaufs: Tierwahl und der eigene Versuch zwischen den Stufen.

Der Versuch zwischen den Stufen ist kein Beiwerk. Bei Zech arbeitet das Kind
zwischen den Hilfen; ohne diesen Schritt hat die Rueckmeldungshilfe nichts,
worauf sie sich beziehen koennte.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

from tutoring import levels, tiere
from tutoring.models import Hint, LearningSession, Participation, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="lehrperson", password="geheim")


@pytest.fixture
def sitzung(lehrperson):
    return LearningSession.objects.create(
        title="Sachrechnen 4a", teacher=lehrperson, max_level=levels.BIS_ZUR_LOESUNG
    )


@pytest.fixture
def kind_im_chat(client, sitzung):
    """Ein beigetretenes Kind mit Tier, ueber den echten Weg."""
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": "fuchs"}, secure=True)
    return Participation.objects.get(learning_session=sitzung)


def _teilnahme(sitzung, tier=""):
    return Participation.objects.create(
        learning_session=sitzung, token=Participation.token_erzeugen(), animal=tier
    )


# --- Das Tier als Kennzeichen ---------------------------------------------

def test_tier_ist_je_sitzung_nur_einmal_zu_haben(sitzung):
    _teilnahme(sitzung, "fuchs")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _teilnahme(sitzung, "fuchs")


def test_dasselbe_tier_in_zwei_sitzungen_ist_erlaubt(sitzung, lehrperson):
    zweite = LearningSession.objects.create(title="4b", teacher=lehrperson)

    _teilnahme(sitzung, "fuchs")
    _teilnahme(zweite, "fuchs")

    assert Participation.objects.filter(animal="fuchs").count() == 2


def test_mehrere_ohne_tier_sind_erlaubt(sitzung):
    """Die Bedingung darf frisch Beigetretene nicht gegeneinander sperren."""
    _teilnahme(sitzung)
    _teilnahme(sitzung)

    assert sitzung.participations.filter(animal="").count() == 2


def test_tier_hat_bild_und_namen(sitzung):
    """Keine Emoji: eigene Grafiken in einheitlichem Stil.

    Emoji sehen auf jedem Geraet anders aus, manche fehlen ganz, und als
    Gestaltung wirken sie beliebig.
    """
    teilnahme = _teilnahme(sitzung, "igel")

    assert teilnahme.tier_bild == "img/tiere/igel.webp"
    assert teilnahme.tier_name == "Igel"
    assert teilnahme.hat_tier is True


def test_jedes_tier_hat_eine_grafik():
    """Ein fehlendes Bild faellt sonst erst im Hoersaal auf."""
    from pathlib import Path as Pfad

    wurzel = Pfad(__file__).resolve().parents[2] / "static"
    for schluessel, _ in tiere.TIERE:
        datei = wurzel / tiere.bild(schluessel)
        assert datei.exists(), f"Grafik fehlt: {schluessel}"


def test_unbekanntes_tier_wird_nicht_angeboten():
    assert tiere.ist_bekannt("fuchs") is True
    assert tiere.ist_bekannt("einhorn") is False


def test_vergebene_tiere_sind_in_der_liste_markiert(sitzung):
    _teilnahme(sitzung, "fuchs")

    liste = tiere.freie(["fuchs"])
    fuchs = next(t for t in liste if t["schluessel"] == "fuchs")
    igel = next(t for t in liste if t["schluessel"] == "igel")

    assert fuchs["vergeben"] is True
    assert igel["vergeben"] is False
    assert len(liste) == len(tiere.TIERE)


# --- Der eigene Versuch zwischen den Stufen -------------------------------

def test_nach_einer_hilfe_wartet_die_aufgabe_auf_den_versuch(sitzung):
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "fuchs"), text="6 mal 8", current_level=1
    )
    Hint.objects.create(task=aufgabe, level=1, text="Du schaffst das.")

    assert aufgabe.offene_hilfe is not None
    assert aufgabe.offene_hilfe.level == 1


def test_mit_versuch_geht_es_weiter(sitzung):
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "fuchs"), text="6 mal 8", current_level=1
    )
    hilfe = Hint.objects.create(task=aufgabe, level=1, text="Du schaffst das.")

    hilfe.response = "Ich habe 6 plus 8 gerechnet."
    hilfe.save(update_fields=["response"])

    assert aufgabe.offene_hilfe is None


def test_nach_der_loesung_wird_kein_versuch_mehr_verlangt(sitzung):
    """Stufe 5 beendet die Aufgabe, danach gibt es nichts mehr anzufordern."""
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "fuchs"), text="6 mal 8", current_level=5
    )
    Hint.objects.create(task=aufgabe, level=5, text="Das Ergebnis ist 48.")

    assert aufgabe.offene_hilfe is None


@pytest.mark.parametrize("stufe", [1, 2, 3, 4])
def test_jede_stufe_vor_der_loesung_hat_einen_arbeitsauftrag(stufe):
    assert levels.braucht_antwort(stufe) is True
    assert levels.rueckfrage(stufe)


def test_die_loesung_hat_keinen_arbeitsauftrag():
    assert levels.braucht_antwort(levels.LOESUNG) is False
    assert levels.rueckfrage(levels.LOESUNG) is None


# --- Herkunft einer Eingabe -----------------------------------------------

def test_herkunft_wird_vermerkt(sitzung):
    from tutoring.models import FOTOGRAFIERT, GESPROCHEN, GETIPPT

    teilnahme = _teilnahme(sitzung, "fuchs")
    getippt = Task.objects.create(participation=teilnahme, text="A")
    fotografiert = Task.objects.create(
        participation=teilnahme, text="B", source=FOTOGRAFIERT,
        image_data_url="data:image/jpeg;base64,xxx",
    )
    gesprochen = Task.objects.create(
        participation=teilnahme, text="C", source=GESPROCHEN
    )

    assert getippt.source == GETIPPT
    assert fotografiert.source == FOTOGRAFIERT
    assert fotografiert.image_data_url
    assert gesprochen.source == GESPROCHEN
    # Die Tonaufnahme wird nicht aufgehoben, nur der erkannte Text.
    assert not hasattr(gesprochen, "audio_data")


def test_loesung_ohne_rueckfrage_ist_einstellbar(lehrperson):
    """Drei Einstellungen: nie, auf Bitte, bei Bedarf."""
    auf_bitte = LearningSession.objects.create(
        title="Auf Bitte", teacher=lehrperson,
        max_level=levels.BIS_ZUR_LOESUNG, ask_before_solution=True,
    )
    bei_bedarf = LearningSession.objects.create(
        title="Bei Bedarf", teacher=lehrperson,
        max_level=levels.BIS_ZUR_LOESUNG, ask_before_solution=False,
    )

    a = Task.objects.create(
        participation=_teilnahme(auf_bitte, "igel"), text="x", current_level=4
    )
    b = Task.objects.create(
        participation=_teilnahme(bei_bedarf, "eule"), text="x", current_level=4
    )

    assert a.loesung_steht_an is True
    assert b.loesung_steht_an is False


def test_nur_tipps_kennt_keine_loesungsabfrage(sitzung, lehrperson):
    nur_tipps = LearningSession.objects.create(
        title="Nur Tipps", teacher=lehrperson, max_level=levels.NUR_TIPPS
    )
    aufgabe = Task.objects.create(
        participation=_teilnahme(nur_tipps, "wolf"), text="x", current_level=3
    )

    assert aufgabe.loesung_steht_an is False
    assert aufgabe.stufen_ausgeschoepft is True


# --- Bereitschaft: erst pruefen, dann vorruecken --------------------------

def test_ohne_erreichtes_ziel_kommt_dieselbe_stufe_noch_einmal(sitzung):
    """Aus einem Probelauf.

    Das Kind schrieb "Ich weiss nicht was ich rechnen soll" und bekam
    trotzdem Stufe 2. Die Rueckmeldungshilfe hat dann nichts, worauf sie sich
    beziehen koennte, und wiederholt Stufe 1 mit anderen Worten. Die Stufen
    werden abgearbeitet, statt zu helfen.
    """
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "fuchs"), text="128 Bücher", current_level=1
    )
    Hint.objects.create(
        task=aufgabe, level=1, text="Worum geht es?",
        response="Ich weiß nicht was ich rechnen soll", goal_reached=False,
    )

    stufe, wiederholung = aufgabe.naechster_schritt()

    assert stufe == 1
    assert wiederholung is True


def test_mit_erreichtem_ziel_geht_es_weiter(sitzung):
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "igel"), text="128 Bücher", current_level=1
    )
    Hint.objects.create(
        task=aufgabe, level=1, text="Worum geht es?",
        response="Man soll wissen wie viele Bücher noch da sind",
        goal_reached=True,
    )

    stufe, wiederholung = aufgabe.naechster_schritt()

    assert stufe == 2
    assert wiederholung is False


def test_nach_zwei_wiederholungen_geht_es_trotzdem_weiter(sitzung):
    """Wer dreimal dieselbe Stufe bekommt, ist nicht besser dran."""
    aufgabe = Task.objects.create(
        participation=_teilnahme(sitzung, "eule"), text="x", current_level=1,
        repeats=levels.HOECHSTE_WIEDERHOLUNGEN,
    )
    Hint.objects.create(task=aufgabe, level=1, text="x", response="nein",
                        goal_reached=False)

    stufe, wiederholung = aufgabe.naechster_schritt()

    assert stufe == 2
    assert wiederholung is False


def test_die_obergrenze_gilt_auch_bei_wiederholungen(lehrperson):
    nur_tipps = LearningSession.objects.create(
        title="Nur Tipps", teacher=lehrperson, max_level=levels.NUR_TIPPS
    )
    aufgabe = Task.objects.create(
        participation=_teilnahme(nur_tipps, "hase"), text="x", current_level=3,
        repeats=levels.HOECHSTE_WIEDERHOLUNGEN,
    )
    Hint.objects.create(task=aufgabe, level=3, text="x", response="nein",
                        goal_reached=False)

    stufe, _ = aufgabe.naechster_schritt()

    assert stufe is None


def test_jede_stufe_vor_der_loesung_hat_ein_ziel():
    """Ohne Ziel laesst sich nicht pruefen, ob wir weiter sind."""
    for stufe in (1, 2, 3, 4):
        assert levels.ziel(stufe)
    assert levels.ziel(levels.LOESUNG) is None


# --- Eine Aufgabe beginnen und abschliessen -------------------------------

def test_das_kind_kann_eine_aufgabe_abschliessen(client, kind_im_chat):
    """Wer die Loesung nach Stufe 2 selbst hat, muss das sagen koennen.

    Ohne diesen Schritt laeuft jede Aufgabe, bis die Stufen aus sind.
    """
    teilnahme = kind_im_chat
    aufgabe = Task.objects.create(participation=teilnahme, text="6 mal 8")

    client.post(reverse("tutoring:aufgabe_abschliessen"), secure=True)

    aufgabe.refresh_from_db()
    assert aufgabe.ist_abgeschlossen


def test_eine_abgeschlossene_aufgabe_bekommt_keine_stufe_mehr(client, kind_im_chat):
    """Die Grenze liegt im Server, nicht im ausgeblendeten Knopf."""
    aufgabe = Task.objects.create(participation=kind_im_chat, text="6 mal 8")
    aufgabe.abschliessen()

    stufe, wiederholung = aufgabe.naechster_schritt()

    assert stufe is None
    assert wiederholung is False


def test_die_naechste_aufgabe_schliesst_die_vorige_ab(client, kind_im_chat):
    """Sonst stuende in der Lehreransicht ein Dutzend Aufgaben ohne Ende."""
    erste = Task.objects.create(participation=kind_im_chat, text="6 mal 8")

    client.post(
        reverse("tutoring:aufgabe_stellen"), {"text": "12 geteilt durch 3"},
        secure=True,
    )

    erste.refresh_from_db()
    assert erste.ist_abgeschlossen
    assert kind_im_chat.tasks.count() == 2


def test_nach_dem_abschliessen_fragt_der_verfasser_nach_der_naechsten_aufgabe(
        client, kind_im_chat):
    aufgabe = Task.objects.create(participation=kind_im_chat, text="6 mal 8")
    aufgabe.abschliessen()

    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert "Deine nächste Aufgabe" in seite
    assert "erledigt" in seite


def test_nach_der_letzten_stufe_kommt_kein_fehler(client, kind_im_chat):
    """Anlass: "ich bleib dann immer in der hoechsten stufe".

    Nach der letzten Stufe gab der Server eine Fehlermeldung, und das Skript
    holte daraufhin den Knopf zurueck -- mit der Beschriftung der ersten
    Stufe. Das Kind sass in einer Sackgasse.
    """
    aufgabe = Task.objects.create(
        participation=kind_im_chat, text="6 mal 8",
        current_level=kind_im_chat.learning_session.max_level,
    )

    antwort = client.post(
        reverse("tutoring:hilfe", args=[aufgabe.pk]), secure=True
    )
    strom = b"".join(antwort.streaming_content).decode()

    assert "event: ausgeschoepft" in strom, strom
    assert "event: fehler" not in strom


def test_eine_offene_wiederholung_gilt_nicht_als_ausgeschoepft(kind_im_chat):
    """Sonst verschwindet der Knopf beim Neuladen, obwohl es weiterginge."""
    sitzung = kind_im_chat.learning_session
    aufgabe = Task.objects.create(
        participation=kind_im_chat, text="6 mal 8", current_level=sitzung.max_level,
    )
    Hint.objects.create(
        task=aufgabe, level=sitzung.max_level, text="Letzte Hilfe",
        response="Ich verstehe es nicht", goal_reached=False,
    )

    assert aufgabe.stufen_ausgeschoepft is False
    assert aufgabe.naechster_schritt() == (sitzung.max_level, True)


def test_die_rueckfrage_haelt_dieselbe_obergrenze(client, kind_im_chat):
    """Anlass, und es war der gefaehrlichste Fund des Tages.

    In einer Sitzung mit "nur Tipps" antwortete die Rueckfrage nach der
    letzten Stufe mit "Die Antwort ist 48" und rechnete danach den Weg vor.
    Die Stufen hielten dicht, die Rueckfrage nicht. Eine Grenze, um die man
    herumtippen kann, ist keine.

    Geprueft wird hier nicht das Modell, sondern dass die Antwort ueberhaupt
    durch die Ausgangspruefung laeuft: mit der Obergrenze der Sitzung als
    Stufe.
    """
    from tutoring import ausgabepruefung

    sitzung = kind_im_chat.learning_session
    sitzung.max_level = levels.NUR_TIPPS
    sitzung.save(update_fields=["max_level"])
    aufgabe = Task.objects.create(
        participation=kind_im_chat,
        text="In einer Schachtel sind 6 Packungen mit je 8 Stiften.",
        current_level=levels.NUR_TIPPS,
    )

    verstoss = ausgabepruefung.verstoesse(
        "Die Antwort ist 48.", sitzung.max_level, sitzung.max_level,
        [aufgabe.text],
    )

    assert verstoss, "Die Loesung muesste bei nur Tipps auffallen"
