"""Die Note des Kindes fuer die Hilfe (Thomas, 1.11.2026).

"Fuer den Realbetrieb brauchen wir bei jeder Runde an der Aufgabe am Schluss
die Moeglichkeit, die Schueler zu fragen, ob es geholfen hat, wie gut (Note 1
bis 5)." Freiwillig, nur fuer eine eigene abgeschlossene Aufgabe; die
Lehrperson sieht sie je Aufgabe, je Kind und fuer die Klasse.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tutoring import klassenbild, levels
from tutoring.models import Hint, LearningSession, Participation, Task
from tutoring.views import SCHLUESSEL_TEILNAHME

pytestmark = pytest.mark.django_db

AUFGABE = "Lena hat 7 Murmeln. Sie bekommt von Omar noch 5 Murmeln dazu. Wie viele Murmeln hat Lena jetzt?"


@pytest.fixture
def lehrperson(db):
    return get_user_model().objects.create_user(username="l", password="x")


@pytest.fixture
def stunde(lehrperson):
    return LearningSession.objects.create(title="Mathe", teacher=lehrperson, max_level=levels.LOESUNG)


@pytest.fixture
def kind(client, stunde):
    teilnahme = Participation.objects.create(learning_session=stunde, animal="igel", token="t-igel")
    s = client.session
    s[SCHLUESSEL_TEILNAHME] = teilnahme.token
    s.save()
    return teilnahme


def _geloeste_aufgabe(kind, text=AUFGABE):
    aufgabe = Task.objects.create(participation=kind, text=text)
    Hint.objects.create(task=aufgabe, level=1, text="Schau auf die Zahlen.", response="12",
                        result=Hint.ERGEBNIS_RICHTIG)
    aufgabe.abschliessen()
    return aufgabe


def test_die_note_wird_gespeichert_nur_eins_bis_fuenf(kind):
    aufgabe = _geloeste_aufgabe(kind)
    assert aufgabe.benoten("2") is True
    aufgabe.refresh_from_db()
    assert aufgabe.rating == 2 and aufgabe.rated_at is not None
    for kaputt in ("0", "6", "gut", None, ""):
        assert aufgabe.benoten(kaputt) is False
    aufgabe.refresh_from_db()
    assert aufgabe.rating == 2


def test_die_seite_fragt_nach_der_note_sobald_die_aufgabe_fertig_ist(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert 'id="notenleiste"' in seite and "hidden" in seite[seite.index('id="notenleiste"') - 120:seite.index('id="notenleiste"') + 200]

    aufgabe.abschliessen()
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    leiste = seite[seite.index('id="notenleiste"'):seite.index("</section>", seite.index('id="notenleiste"'))]
    assert "hidden" not in leiste.split(">")[0]
    assert "Hat dir die Hilfe geholfen?" in leiste
    assert leiste.count('class="notenknopf"') == 5
    assert reverse("tutoring:aufgabe_benoten") in leiste


def test_die_note_kommt_an_und_die_seite_sagt_danke(client, kind):
    aufgabe = _geloeste_aufgabe(kind)

    antwort = client.post(reverse("tutoring:aufgabe_benoten"),
                          {"aufgabe": aufgabe.pk, "note": "1"}, secure=True)

    assert antwort.status_code == 302
    aufgabe.refresh_from_db()
    assert aufgabe.rating == 1
    seite = client.get(reverse("tutoring:chat"), secure=True).content.decode()
    assert "Deine Note für die Hilfe: <strong>1</strong>" in seite
    assert 'class="notenknopf"' not in seite


def test_per_skript_antwortet_die_note_als_json(client, kind):
    aufgabe = _geloeste_aufgabe(kind)
    antwort = client.post(reverse("tutoring:aufgabe_benoten"), {"note": "4"},
                          secure=True, HTTP_X_ANTWORT="json")
    assert antwort.json() == {"ok": True, "note": 4}
    antwort = client.post(reverse("tutoring:aufgabe_benoten"), {"note": "9"},
                          secure=True, HTTP_X_ANTWORT="json")
    assert antwort.json() == {"ok": False, "note": 4}


def test_eine_laufende_aufgabe_bekommt_keine_note(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)
    client.post(reverse("tutoring:aufgabe_benoten"), {"note": "2"}, secure=True)
    aufgabe.refresh_from_db()
    assert aufgabe.rating is None


def test_ich_bin_fertig_nimmt_die_note_mit(client, kind):
    aufgabe = Task.objects.create(participation=kind, text=AUFGABE)
    client.post(reverse("tutoring:aufgabe_abschliessen"), {"note": "3"}, secure=True)
    aufgabe.refresh_from_db()
    assert aufgabe.ist_abgeschlossen and aufgabe.rating == 3


def test_fremde_aufgaben_lassen_sich_nicht_benoten(client, kind, stunde):
    andere = Participation.objects.create(learning_session=stunde, animal="fuchs", token="t-fuchs")
    fremd = Task.objects.create(participation=andere, text=AUFGABE)
    fremd.abschliessen()
    eigene = _geloeste_aufgabe(kind)
    client.post(reverse("tutoring:aufgabe_benoten"), {"aufgabe": fremd.pk, "note": "1"}, secure=True)
    fremd.refresh_from_db()
    eigene.refresh_from_db()
    assert fremd.rating is None and eigene.rating == 1, "der Schluessel zaehlt nur fuer eigene Aufgaben"


def test_die_lehrperson_sieht_die_noten(client, lehrperson, stunde, kind):
    erste = _geloeste_aufgabe(kind)
    erste.benoten(2)
    zweite = _geloeste_aufgabe(kind, "7 + 5")
    zweite.benoten(1)
    _geloeste_aufgabe(kind, "9 - 4")   # ohne Note
    client.force_login(lehrperson)

    verlauf = client.get(reverse("tutoring:lehrperson_verlauf", args=[stunde.code, kind.pk]),
                         secure=True).content.decode()
    assert "Note des Kindes für die Hilfe:</strong> 2" in verlauf
    assert "Note des Kindes für die Hilfe:</strong> 1" in verlauf
    assert "Note der Hilfe: Ø 1,5 (2 Aufgaben)" in verlauf

    liste = client.get(reverse("tutoring:lehrperson_klassenliste", args=[stunde.code]),
                       secure=True).content.decode()
    assert "Note der Hilfe: Ø 1,5 (2 Aufgaben)" in liste
    assert "Ø 1,5</strong> Note der Kinder (2)" in liste
    assert stunde.zaehler["noten"] == 2 and stunde.zaehler["note_mittel"] == "1,5"


def test_die_notenzeile():
    assert klassenbild.note_zeile([]) == ""
    assert klassenbild.note_zeile([None, 3]) == "Note der Hilfe: Ø 3,0 (1 Aufgabe)"
    assert klassenbild.note_zeile([2, 3, None]) == "Note der Hilfe: Ø 2,5 (2 Aufgaben)"
    assert klassenbild.leere_kachel()["note_zeile"] == ""
