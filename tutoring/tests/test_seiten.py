"""Prueft, dass die Seiten tatsaechlich rendern.

Anlass: Eine Teilvorlage fehlte, weil ein Schreibvorgang auf halbem Weg
abgebrochen war. Alle 90 Tests liefen gruen durch, das Ausrollen meldete
Erfolg, und die Chatseite antwortete im Betrieb mit HTTP 500. Kein Test
hatte je eine Seite gerendert.

Diese Pruefungen sind absichtlich flach. Sie stellen keine Fachfrage,
sondern eine einzige: Faellt die Seite um?
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import levels
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
def kind(client, sitzung):
    """Ein beigetretenes Kind mit Tier, ueber den echten Weg."""
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": "fuchs"}, secure=True)
    return Participation.objects.get(learning_session=sitzung)


# --- Oeffentliche Seiten ---------------------------------------------------

@pytest.mark.parametrize("name", [
    "start", "stufen", "datenschutz", "barrierefreiheit", "anmelden",
])
def test_oeffentliche_seiten_rendern(client, name):
    antwort = client.get(reverse(name), secure=True)

    assert antwort.status_code == 200
    assert antwort.content


# --- Der Weg des Kindes ----------------------------------------------------

def test_tierwahl_rendert(client, sitzung):
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)

    antwort = client.get(reverse("tutoring:tier_waehlen"), secure=True)

    assert antwort.status_code == 200
    assert "Fuchs" in antwort.content.decode()


def test_chat_ohne_aufgabe_rendert(client, kind):
    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "fotoknopf" in seite, "Die Eingabehilfen fehlen"
    assert "verfasser-form" in seite, "Der Eingabebereich fehlt"
    assert kind.tier_name in seite


def test_chat_mit_aufgabe_und_hilfe_rendert(client, kind):
    aufgabe = Task.objects.create(
        participation=kind, text="6 mal 8", current_level=1
    )
    Hint.objects.create(task=aufgabe, level=1, text="Du schaffst das.")

    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "schritt-kopf" in seite, "Die Schritte fehlen"
    assert "fortschritt" in seite, "Die Fortschrittsanzeige fehlt"


def test_chat_nach_der_loesung_zeigt_nachfrage(client, kind):
    """Nach der Loesung gibt es keinen Versuch mehr, nur noch Fragen und die
    naechste Aufgabe. Vorher hiess der Zustand "Stufen ausgeschoepft"; seit
    dem Benchmark (19.10.2026) kann das Kind nach ausgeschoepften Stufen
    weiter probieren, und nur die gezeigte Loesung beendet den Versuchsweg."""
    aufgabe = Task.objects.create(participation=kind, text="6 mal 8", current_level=5)
    Hint.objects.create(task=aufgabe, level=5, text="6 · 8 = 48.")

    antwort = client.get(reverse("tutoring:chat"), secure=True)
    seite = antwort.content.decode()

    assert 'data-modus="nachfrage"' in seite
    assert "Noch eine Frage" in seite
    assert "Nächste Aufgabe" in seite


def test_zustimmung_nur_bei_erwachsenen(client, lehrperson):
    """Kinder werden nicht gefragt.

    Minderjaehrige koennen in eine Forschungsverarbeitung rechtlich nicht
    selbst einwilligen. Ein Zustimmungsbildschirm fuer Kinder waere nicht nur
    ueberfluessiger Text, sondern eine falsche Auskunft.
    """
    from tutoring.models import FORSCHUNG_VOLL

    fuer_kinder = LearningSession.objects.create(
        title="Vierte Klasse", teacher=lehrperson,
        research_level=FORSCHUNG_VOLL, age_group="6-10",
    )
    assert fuer_kinder.zustimmung_noetig is False

    fuer_erwachsene = LearningSession.objects.create(
        title="Fortbildung", teacher=lehrperson,
        research_level=FORSCHUNG_VOLL, age_group="erwachsen",
    )
    assert fuer_erwachsene.zustimmung_noetig is True

    client.get("/", secure=True)
    client.post(
        reverse("tutoring:beitreten"), {"code": fuer_erwachsene.code}, secure=True
    )
    antwort = client.get(reverse("tutoring:zustimmung"), secure=True)

    assert antwort.status_code == 200
    assert "Ablehnen hat keinen Nachteil" in antwort.content.decode()


def test_kind_kommt_ohne_zustimmung_direkt_zur_tierwahl(client, lehrperson):
    from tutoring.models import FORSCHUNG_VOLL

    sitzung = LearningSession.objects.create(
        title="Vierte Klasse", teacher=lehrperson,
        research_level=FORSCHUNG_VOLL, age_group="6-10",
    )
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sitzung.code}, secure=True)

    antwort = client.get(reverse("tutoring:chat"), secure=True, follow=True)

    assert reverse("tutoring:tier_waehlen") in antwort.redirect_chain[-1][0]


# --- Die Seiten der Lehrperson --------------------------------------------

def test_uebersicht_zeigt_zuerst_nur_die_faecher(client, lehrperson, sitzung):
    """Ohne Fach ist nichts anderes zu sehen - das ist die Vorgabe.

    Vorher standen acht Bloecke gleichzeitig da, zwei davon mit der
    Aufschrift, fuer wen sie nicht gelten. "Da kennt sich niemand aus."
    """
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    for fach in ("mathematik", "deutsch", "englisch", "sachunterricht"):
        assert f"?fach={fach}" in seite, f"Die Schaltflaeche fuer {fach} fehlt"
    assert "age_group" not in seite, "Vor der Fachwahl darf keine Einstellung da sein"
    assert 'name="mode"' not in seite, "Die Betriebsart wird nicht mehr gewaehlt"


def test_mathematik_zeigt_schulstufe_und_umfang_aber_kein_niveau(client, lehrperson, sitzung):
    """Seit dem Benchmark (19.10.2026) ersetzt die Schulstufe die Altersklasse
    im Mathe-Formular; der Umfang hat zwei Antworten, Lernen und Ueben."""
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "mathematik"}, secure=True
    )

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert 'name="schulstufe"' in seite, "Die Schulstufe fehlt"
    assert "age_group" not in seite, "Die Altersklasse hat in Mathematik nichts mehr verloren"
    assert "auf_bitte" in seite and 'value="tipps"' in seite, "Lernen und Ueben fehlen"
    assert "erklaerungsliste" in seite, "Die Stufenerklaerung fehlt"
    assert 'name="language_level"' not in seite, "Niveau gehoert nicht in Mathematik"
    assert 'name="fach"' in seite and 'value="mathematik"' in seite


def test_englisch_zeigt_niveau_aber_keine_stufen(client, lehrperson, sitzung):
    """Und keine Sprachauswahl: Wer Englisch unterrichtet, waehlt nicht Englisch."""
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "englisch"}, secure=True
    ).content.decode()

    assert 'name="language_level"' in seite
    assert 'name="umfang"' not in seite, "Stufen gehoeren nicht in Englisch"
    assert 'name="target_language"' not in seite


def test_ein_unbekanntes_fach_fuehrt_zur_fachwahl(client, lehrperson, sitzung):
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_uebersicht"), {"fach": "turnen"}, secure=True
    ).content.decode()

    assert "?fach=mathematik" in seite
    assert "age_group" not in seite


def test_uebersicht_zeigt_die_sitzung_als_karte(client, lehrperson, sitzung, kind):
    """Die Uebersicht ist das, was Freitag auf der Leinwand steht.

    Sie muss ohne Suchen hergeben: welcher Code, welcher Titel, wie viele
    sind dabei.
    """
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_uebersicht"), secure=True
    ).content.decode()

    assert sitzung.code in seite, "Der Code fehlt"
    assert "Sachrechnen 4a" in seite, "Der Titel fehlt"
    assert "1</span> dabei" in seite, "Die Zahl der Beigetretenen fehlt"
    assert "6–10 Jahre" in seite, "Die Altersklasse fehlt"


def test_nur_die_zuletzt_benutzten_sitzungen_stehen_als_karte(client, lehrperson):
    """Im Browsertest standen 47 Karten uebereinander, fast alle Probelaeufe.

    Die eine Sitzung, um die es geht, war darin nicht zu finden.
    """
    from tutoring.views import KARTEN_HOECHSTENS

    for i in range(KARTEN_HOECHSTENS + 3):
        LearningSession.objects.create(title=f"Lauf {i}", teacher=lehrperson)
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True)

    assert len(antwort.context["sitzungen"]) == KARTEN_HOECHSTENS
    assert len(antwort.context["weitere"]) == 3


def test_die_neueste_sitzung_steht_oben(client, lehrperson):
    LearningSession.objects.create(title="Alt", teacher=lehrperson)
    neu = LearningSession.objects.create(title="Neu", teacher=lehrperson)
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_uebersicht"), secure=True)

    assert antwort.context["sitzungen"][0]["sitzung"] == neu


def test_eine_sitzung_laesst_sich_von_der_uebersicht_beenden(client, lehrperson, sitzung, kind):
    """Sonst muss die Lehrperson jede Sitzung einzeln aufschlagen."""
    client.force_login(lehrperson)

    client.post(
        reverse("tutoring:lehrperson_sitzung_beenden", args=[sitzung.code]),
        secure=True,
    )

    sitzung.refresh_from_db()
    assert sitzung.closed_at is not None


def test_leere_sitzungen_lassen_sich_gemeinsam_beenden(client, lehrperson, sitzung, kind):
    """Die Sitzung mit Beitritt bleibt dabei stehen."""
    leer = LearningSession.objects.create(title="Probelauf", teacher=lehrperson)
    client.force_login(lehrperson)

    client.post(reverse("tutoring:lehrperson_leere_beenden"), secure=True)

    leer.refresh_from_db()
    sitzung.refresh_from_db()
    assert leer.closed_at is not None, "Die leere Sitzung laeuft noch"
    assert sitzung.closed_at is None, "Die bearbeitete Sitzung wurde mitbeendet"


def test_fremde_leere_sitzungen_bleiben_unberuehrt(client, lehrperson):
    """Das Aufraeumen darf nur die eigenen Sitzungen treffen."""
    andere = get_user_model().objects.create_user(username="andere", password="geheim")
    fremd = LearningSession.objects.create(title="Fremd", teacher=andere)
    client.force_login(lehrperson)

    client.post(reverse("tutoring:lehrperson_leere_beenden"), secure=True)

    fremd.refresh_from_db()
    assert fremd.closed_at is None


def test_kopfzeile_nennt_die_angemeldete_lehrperson(client, lehrperson, sitzung):
    """"Log-In-Informationen rechts oben mit dem eigenen Namen." """
    client.force_login(lehrperson)

    seite = client.get(
        reverse("tutoring:lehrperson_uebersicht"), secure=True
    ).content.decode()

    assert "lehrperson" in seite, "Der Name der Lehrperson fehlt oben"
    assert "Abmelden" in seite, "Der Weg zum Abmelden fehlt oben"


def test_sitzungsseite_rendert(client, lehrperson, sitzung):
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200
    assert sitzung.code in antwort.content.decode()


def test_klassenliste_rendert(client, lehrperson, sitzung, kind):
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_klassenliste", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200
    assert kind.tier_name in antwort.content.decode()


def test_verlauf_rendert(client, lehrperson, sitzung, kind):
    Task.objects.create(participation=kind, text="Eine Aufgabe")
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, kind.pk]),
        secure=True,
    )

    assert antwort.status_code == 200
    assert "Eine Aufgabe" in antwort.content.decode()


def test_qr_code_wird_ausgeliefert(client, lehrperson, sitzung):
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:qr_code", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200
    assert antwort["Content-Type"] == "image/svg+xml"
    assert b"<svg" in antwort.content


# --- Der Weg zur Anmeldung -------------------------------------------------

def test_startseite_zeigt_den_weg_zur_anmeldung(client):
    """Er stand nur klein im Fuss und war damit nicht zu finden."""
    antwort = client.get(reverse("start"), secure=True)
    seite = antwort.content.decode()

    assert reverse("anmelden") in seite
    assert "Sie sind Lehrperson" in seite


def test_kopfzeile_fuehrt_zur_anmeldung(client):
    seite = client.get(reverse("stufen"), secure=True).content.decode()

    assert "Für Lehrpersonen" in seite


def test_angemeldete_lehrperson_sieht_ihre_sitzungen_in_der_kopfzeile(client, lehrperson):
    """Geprueft wird der Weg, nicht die Beschriftung."""
    client.force_login(lehrperson)

    seite = client.get(reverse("start"), secure=True).content.decode()

    assert reverse("tutoring:lehrperson_uebersicht") in seite


def test_das_kind_sieht_den_weg_zur_anmeldung_nicht(client, kind):
    """Im Chat steht oben rechts das Tier, nicht die Lehreranmeldung."""
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert "Für Lehrpersonen" not in seite
    assert kind.tier_name in seite


def test_werkzeugknoepfe_haben_immer_einen_namen(client, kind):
    """Am schmalen Handy verschwindet das Wort optisch, nicht im Dokument.

    Mit display:none haette der Knopf gar keinen Namen mehr, und ein
    Vorlesewerkzeug meldete nur "Schaltflaeche".
    """
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()

    assert ">Foto<" in seite.replace("\n", "").replace("  ", "")
    assert "werkzeug-wort" in seite


def test_hilfe_endpunkt_antwortet(client, kind):
    """Der Endpunkt lief in einen SynchronousOnlyOperation.

    Die Entscheidung ueber die naechste Stufe fragt die Datenbank, und im
    asynchronen Teil der Streamingansicht ist das nicht erlaubt. Der Fehler
    war an keinem Test zu sehen, weil kein Test den Endpunkt aufrief.
    """
    aufgabe = Task.objects.create(participation=kind, text="6 mal 8")

    antwort = client.post(
        reverse("tutoring:hilfe", args=[aufgabe.pk]), secure=True
    )

    assert antwort.status_code == 200
    assert antwort["Content-Type"].startswith("text/event-stream")


def test_bereitschaftsseite_rendert(client, lehrperson, monkeypatch):
    """Die Frage, die man fuenf Minuten vor dem Vortrag stellt.

    Geprueft wird die Seite, nicht der Spark: Ein Test, der ein Netz
    braucht, faellt irgendwann aus Gruenden aus, die nichts mit dem Code zu
    tun haben.
    """
    from tutoring import bereitschaft

    monkeypatch.setattr(bereitschaft, "pruefen", lambda: [
        {"name": "Sprachmodell am Spark", "wozu": "Schreibt die Hilfen.",
         "wo": "http://beispiel", "ok": True, "auskunft": "bereit", "ms": 420},
        {"name": "Spracherkennung am Spark", "wozu": "Nimmt Aufgaben auf.",
         "wo": "http://beispiel", "ok": False, "auskunft": "Zeitüberschreitung",
         "ms": 30000},
    ])
    client.force_login(lehrperson)

    antwort = client.get(reverse("tutoring:lehrperson_bereitschaft"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "420" in seite
    assert "Zeitüberschreitung" in seite
    assert antwort.context["alles_gut"] is False


def test_die_bereitschaftsseite_ist_nicht_oeffentlich(client):
    """Sie kostet zwei echte Aufrufe an den Spark."""
    antwort = client.get(reverse("tutoring:lehrperson_bereitschaft"), secure=True)

    assert antwort.status_code == 302
    assert "anmelden" in antwort["Location"]


# --- Die Seiten des Trainers ----------------------------------------------

@pytest.fixture
def trainersitzung(lehrperson):
    return LearningSession.objects.create(
        title="Maßumwandlung", teacher=lehrperson,
        mode=LearningSession.BETRIEB_TRAINER,
    )


def test_die_trainererklaerung_rendert(client):
    antwort = client.get(reverse("trainer_erklaerung"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "Trainer" in seite


def test_die_trainerseite_rendert(client, trainersitzung):
    """Anlass fuer diese flachen Pruefungen war eine fehlende Teilvorlage."""
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": trainersitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": "fuchs"}, secure=True)

    antwort = client.get(reverse("tutoring:trainer"), secure=True)

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "trainer-form" in seite


def test_eine_trainersitzung_fuehrt_nicht_in_die_aufgabenhilfe(client, trainersitzung):
    """Ein Beitritt landet ueber den Chat im Trainer, nicht im Aufgabenfeld."""
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": trainersitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": "fuchs"}, secure=True)

    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 302
    assert reverse("tutoring:trainer") in antwort["Location"]


def test_eine_aufgabensitzung_fuehrt_nicht_in_den_trainer(client, sitzung, kind):
    antwort = client.get(reverse("tutoring:trainer"), secure=True)

    assert antwort.status_code == 302
    assert reverse("tutoring:chat") in antwort["Location"]


def test_die_betriebsart_folgt_aus_dem_fach(client, lehrperson):
    """Deutsch und Sachunterricht fuehren in den Trainer, ohne dass jemand
    "Trainer" waehlt."""
    from tutoring.models import LearningSession

    client.force_login(lehrperson)

    antwort = client.post(
        reverse("tutoring:lehrperson_uebersicht"),
        {"fach": "deutsch", "title": "Deutsch 2a", "task_hint": "Wörtliche Rede"},
        secure=True,
    )

    assert antwort.status_code == 302
    sitzung = LearningSession.objects.get(title="Deutsch 2a")
    assert sitzung.subject == "deutsch"
    assert sitzung.mode == LearningSession.BETRIEB_TRAINER
    assert sitzung.task_hint == "Wörtliche Rede"


def test_ohne_fach_wird_nichts_angelegt(client, lehrperson):
    """Ein nachgebautes Formular ohne Fach landet bei der Fachwahl."""
    from tutoring.models import LearningSession

    client.force_login(lehrperson)
    vorher = LearningSession.objects.count()

    antwort = client.post(
        reverse("tutoring:lehrperson_uebersicht"),
        {"title": "Ohne Fach", "mode": "hilfe"},
        secure=True,
    )

    assert antwort.status_code == 200
    assert LearningSession.objects.count() == vorher
    assert "?fach=mathematik" in antwort.content.decode()


def test_eine_stufenobergrenze_kommt_nicht_in_eine_englischstunde(client, lehrperson):
    """Was die Seite nicht zeigt, nimmt die Ansicht auch nicht an."""
    from tutoring import levels
    from tutoring.models import LearningSession

    client.force_login(lehrperson)

    client.post(
        reverse("tutoring:lehrperson_uebersicht"),
        {"fach": "englisch", "title": "Englisch 4b", "umfang": "loesung",
         "language_level": "B1"},
        secure=True,
    )

    sitzung = LearningSession.objects.get(title="Englisch 4b")
    assert sitzung.max_level == levels.NUR_TIPPS, "der Umfang wurde ignoriert"
    assert sitzung.language_level == "B1"


def test_die_klassenliste_haelt_eine_teilnahme_ohne_tier_aus(client, lehrperson, sitzung):
    """Anlass aus dem Betrieb, und es war teuer.

    Von 28 Beigetretenen hatte einer den QR-Code gescannt und die Tierwahl
    wieder verlassen. Fuer ihn ist tier_bild leer, und {% static "" %} wirft
    unter ManifestStaticFilesStorage einen ValueError. Die Sitzungsseite mit
    den siebzehn Aufgaben der anderen war damit nicht mehr zu oeffnen -
    wegen einer Person, die nichts getan hat.
    """
    Participation.objects.create(
        learning_session=sitzung, animal="fuchs", token="a", log_key="la"
    )
    Participation.objects.create(
        learning_session=sitzung, animal="", token="b", log_key="lb"
    )
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200
    seite = antwort.content.decode()
    assert "kein Tier gewählt" in seite
    assert "Fuchs" in seite


def test_auch_die_nachgeholte_klassenliste_haelt_das_aus(client, lehrperson, sitzung):
    """Sie wird alle fuenf Sekunden geholt: der Fehler kam im Takt."""
    Participation.objects.create(
        learning_session=sitzung, animal="", token="c", log_key="lc"
    )
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_klassenliste", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200


def test_der_verlauf_einer_teilnahme_ohne_tier_rendert(client, lehrperson, sitzung):
    ohne = Participation.objects.create(
        learning_session=sitzung, animal="", token="d", log_key="ld"
    )
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_verlauf", args=[sitzung.code, ohne.pk]),
        secure=True,
    )

    assert antwort.status_code == 200


# --- Die Seiten des Sprechcoaches ----------------------------------------

@pytest.fixture
def sprechsitzung(lehrperson):
    return LearningSession.objects.create(
        title="English talk", teacher=lehrperson,
        mode=LearningSession.BETRIEB_SPRACHE,
        target_language="en-GB", language_level="A1",
    )


def test_eine_sprechsitzung_fuehrt_nicht_in_die_aufgabenhilfe(client, sprechsitzung):
    client.get("/", secure=True)
    client.post(reverse("tutoring:beitreten"), {"code": sprechsitzung.code}, secure=True)
    client.post(reverse("tutoring:tier_waehlen"), {"tier": "fuchs"}, secure=True)

    antwort = client.get(reverse("tutoring:chat"), secure=True)

    assert antwort.status_code == 302
    assert reverse("tutoring:sprechcoach") in antwort["Location"]


def test_eine_aufgabensitzung_fuehrt_nicht_in_den_sprechcoach(client, sitzung, kind):
    antwort = client.get(reverse("tutoring:sprechcoach"), secure=True)

    assert antwort.status_code == 302
    assert reverse("tutoring:chat") in antwort["Location"]


def test_englisch_legt_einen_sprechcoach_an(client, lehrperson):
    """Die Zielsprache steht am Fach, nicht in einem Auswahlfeld."""
    from tutoring.models import LearningSession

    client.force_login(lehrperson)

    antwort = client.post(
        reverse("tutoring:lehrperson_uebersicht"),
        {"fach": "englisch", "title": "Englisch 3b", "language_level": "A2",
         "task_hint": "pets"},
        secure=True,
    )

    assert antwort.status_code == 302
    sitzung = LearningSession.objects.get(title="Englisch 3b")
    assert sitzung.mode == LearningSession.BETRIEB_SPRACHE
    assert sitzung.subject == "englisch"
    assert sitzung.target_language == "en-GB"
    assert sitzung.language_level == "A2"
    assert sitzung.fach_name == "Englisch"
    # Der Name einer Linienzeichnung, kein Emoji (Thomas, 12.10.2026).
    assert sitzung.fach_symbol == "sprechblase"


def test_alte_sitzungen_ohne_fach_haben_trotzdem_einen_namen(sitzung):
    """Nichts Erfundenes: die Betriebsart ist das Ehrlichste."""
    sitzung.subject = ""
    assert sitzung.fach_name == "Aufgabenhilfe"
    assert sitzung.fach_symbol == ""


def test_ein_unbekanntes_tier_nimmt_die_seite_nicht_mit(client, lehrperson, sitzung):
    """Der Nachschlag zum 500 auf Sitzung 777859.

    Damals war das Feld LEER, und die Vorlage faengt das seither ab. Ein
    unbekannter WERT lief aber weiter in {% static "" %}: hat_tier war
    bool("Biber") und damit wahr, tier_bild aber leer. Aufgefallen bei der
    Pruefung nach dem Umzug auf den PH-Server, wo in Testdaten der
    Anzeigename statt des Schluessels stand - derselbe HTTP 500, nur ueber
    einen anderen Weg.

    Solche Werte entstehen nicht nur durch Tippfehler: ein umbenanntes Tier
    oder ein Eingriff in der Datenbank genuegt.
    """
    Participation.objects.create(
        learning_session=sitzung, animal="Biber", token="d", log_key="ld"
    )
    Participation.objects.create(
        learning_session=sitzung, animal="einhorn", token="e", log_key="le"
    )
    client.force_login(lehrperson)

    antwort = client.get(
        reverse("tutoring:lehrperson_sitzung", args=[sitzung.code]), secure=True
    )

    assert antwort.status_code == 200
    assert "kein Tier gewählt" in antwort.content.decode()


def test_hat_tier_fragt_nach_dem_bekannten_tier(sitzung):
    """hat_tier und tier_bild duerfen sich nie widersprechen."""
    for wert, erwartet in (
        ("biber", True), ("", False), ("Biber", False), ("einhorn", False),
    ):
        teilnahme = Participation(learning_session=sitzung, animal=wert)
        assert teilnahme.hat_tier is erwartet, wert
        # Das ist die Bedingung, auf die es ankommt: Ein wahres hat_tier ohne
        # Bild ist genau der ValueError.
        assert teilnahme.hat_tier == bool(teilnahme.tier_bild), wert


# --- Die oeffentliche Erklaerung der Stufen -------------------------------

def test_die_stufenseite_erklaert_die_wahl_der_hilfe(client):
    """Seit 30.10.2026: Die Stufen sind Vokabular und Obergrenze, die Hilfe
    wird nach einer Einschaetzung je Beitrag gewaehlt. Belege mit
    Seitenzahlen; der Satz von der Reihenfolge ist weg."""
    seite = client.get(reverse("stufen"), secure=True).content.decode()

    assert "gewählt, nicht gezählt" in seite
    assert "Was die Anwendung immer entscheidet" in seite
    assert "Es wird keine Stufe übersprungen" not in seite
    assert "nach vier Stufen mit jeweils eigenem Beitrag" not in seite
    for beleg in ("S. 318", "S. 315", "S. 316–318", "S. 321", "S. 288", "S. 289",
                  "S. 290–291", "S. 350", "S. 376–377", "S. 505–506", "S. 95–96"):
        assert beleg in seite, beleg
    for name in ("Kaiser", "Borromeo Ferri", "Moser Opitz", "Nührenbörger", "Franke", "Ruwisch"):
        assert name in seite, name
    assert "Warum-Frage" in seite and "fragt\n  nach" in seite.replace("\r", "")
    for zeichen in seite:
        assert not (ord(zeichen) >= 0x1F000 or 0x2600 <= ord(zeichen) <= 0x27BF), "kein Emoji"
