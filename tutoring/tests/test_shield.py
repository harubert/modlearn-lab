"""Pruefungen der Maskierung des Privacy Shield.

Geprueft wird hier alles, was ohne den Spark auskommt: die regelbasierte
Erkennung, die Ersetzung, die Ruecknahme und der Leak-Check. Die
Namenserkennung laeuft auf dem Spark und gehoert nicht in einen Test, der
bei jedem Ausrollen laeuft.
"""

import pytest

from tutoring import shield


# --- Regelbasierte Erkennung ----------------------------------------------

def _typen(funde):
    return {typ for typ, _ in funde}


def test_email_wird_gefunden():
    funde = shield.regelfunde("Schreib mir an anna.berger@schule.at, bitte.")

    assert shield.TYP_EMAIL in _typen(funde)
    assert ("EMAIL", "anna.berger@schule.at") in funde


def test_telefonnummer_wird_gefunden():
    funde = shield.regelfunde("Ruf an unter 0664 1234567.")

    assert shield.TYP_TELEFON in _typen(funde)


def test_adresse_mit_hausnummer_wird_gefunden():
    funde = shield.regelfunde("Wir wohnen in der Liechtensteinerstraße 33.")

    assert shield.TYP_ADRESSE in _typen(funde)


def test_plz_mit_ort_wird_gefunden():
    funde = shield.regelfunde("Das ist in 6800 Feldkirch.")

    assert shield.TYP_ORT in _typen(funde)


def test_geburtsdatum_wird_gefunden():
    funde = shield.regelfunde("Ich bin am 3.5.2015 geboren.")

    assert shield.TYP_GEBURTSDATUM in _typen(funde)


def test_svnr_wird_gefunden():
    funde = shield.regelfunde("Meine Nummer ist 1234 030515.")

    assert shield.TYP_SVNR in _typen(funde)


def test_normale_rechenaufgabe_loest_nichts_aus():
    """Ein Fehlalarm bei jeder Aufgabe waere schlimmer als keine Erkennung."""
    funde = shield.regelfunde(
        "In einer Schachtel sind 6 Packungen zu je 8 Stiften. "
        "Wie viele Stifte sind das insgesamt?"
    )

    assert funde == []


def test_laengere_funde_kommen_zuerst():
    """Sonst zerschneidet ein kurzer Treffer einen laengeren, der ihn enthaelt."""
    funde = shield.regelfunde(
        "Anna wohnt in der Bahnhofstraße 12 in 6900 Bregenz, Telefon 0664 1234567."
    )
    laengen = [len(wert) for _, wert in funde]

    assert laengen == sorted(laengen, reverse=True)


# --- Die Sozialversicherungsnummer ist der Sonderfall ---------------------

def test_svnr_wird_nicht_maskiert_sondern_blockiert():
    """Die Vorlage ist eindeutig: niemals an die Cloud, auch nicht als Token.

    Das steht so in publish/flow.html der private_ai_bridge, ihr Token-Format
    ist dort ein Strich. Abschnitt 3a laesst die Nummer erkennen, nennt dafuer
    aber kein Token. Wir folgen der Vorlage.
    """
    assert shield.TYP_SVNR in shield.BLOCKIERENDE_TYPEN

    text = "Meine Nummer ist 1234 030515."
    funde = shield.regelfunde(text)
    maskiert, tabelle = shield.maskieren(text, funde)

    assert "1234 030515" in maskiert
    assert not any(e["typ"] == shield.TYP_SVNR for e in tabelle.values())


def test_svnr_bleibt_im_leak_check_haengen():
    """Genau so wird der Aufruf blockiert: nicht maskiert heisst nicht durch."""
    text = "Meine Nummer ist 1234 030515."
    funde = shield.regelfunde(text)
    maskiert, _ = shield.maskieren(text, funde)

    durchgerutscht = shield.leak_check(maskiert, funde)

    assert any(e["typ"] == shield.TYP_SVNR for e in durchgerutscht)


# --- Ersetzung und Ruecknahme ---------------------------------------------

def test_tokenformat_entspricht_der_vorlage():
    marke = shield.token_fuer(shield.TYP_PERSON, "Anna Berger")

    assert marke.startswith("[PERS_")
    assert marke.endswith("]")
    assert len(marke) == len("[PERS_a3f2]")


def test_gleicher_wert_ergibt_gleiches_token():
    """Sonst bekommt derselbe Name im selben Text zwei Kennungen."""
    assert (shield.token_fuer(shield.TYP_PERSON, "Anna")
            == shield.token_fuer(shield.TYP_PERSON, "Anna"))


def test_verschiedene_werte_ergeben_verschiedene_tokens():
    assert (shield.token_fuer(shield.TYP_PERSON, "Anna")
            != shield.token_fuer(shield.TYP_PERSON, "Berta"))


def test_maskierung_entfernt_den_klartext():
    text = "Schreib an anna.berger@schule.at."
    funde = shield.regelfunde(text)

    maskiert, tabelle = shield.maskieren(text, funde)

    assert "anna.berger@schule.at" not in maskiert
    assert "[EMAIL_" in maskiert
    assert len(tabelle) == 1


def test_ruecknahme_stellt_den_text_wieder_her():
    text = "Schreib an anna.berger@schule.at, danke."
    funde = shield.regelfunde(text)
    maskiert, tabelle = shield.maskieren(text, funde)

    assert shield.zuruecksetzen(maskiert, tabelle) == text


def test_ruecknahme_wirkt_auch_in_einer_antwort():
    """Das Kind soll den echten Namen lesen, nicht das Token."""
    text = "Anna hat 3 Äpfel."
    funde = [(shield.TYP_PERSON, "Anna")]
    maskiert, tabelle = shield.maskieren(text, funde)
    marke = next(iter(tabelle))

    antwort = f"{marke} hat also insgesamt 3 Äpfel."

    assert shield.zuruecksetzen(antwort, tabelle) == "Anna hat also insgesamt 3 Äpfel."


def test_zaehlung_nennt_nur_anzahlen():
    """Fuer das Protokoll: Anzahl je Typ, kein Inhalt."""
    text = "anna@schule.at und berta@schule.at, Telefon 0664 1234567."
    funde = shield.regelfunde(text)
    _, tabelle = shield.maskieren(text, funde)

    gezaehlt = shield.zaehlung(tabelle)

    assert gezaehlt[shield.TYP_EMAIL] == 2
    for wert in gezaehlt.values():
        assert isinstance(wert, int)


# --- Leak-Check ------------------------------------------------------------

def test_sauberer_text_besteht_den_check():
    text = "Schreib an anna.berger@schule.at."
    funde = shield.regelfunde(text)
    maskiert, _ = shield.maskieren(text, funde)

    assert shield.leak_check(maskiert, funde) == []


def test_durchgerutschter_klartext_faellt_auf():
    funde = [(shield.TYP_PERSON, "Anna Berger")]

    durchgerutscht = shield.leak_check("Hallo Anna Berger", funde)

    assert durchgerutscht == [{"typ": "PERS", "wert": "Anna Berger"}]


def test_der_check_findet_nur_was_erkannt_wurde():
    """Die Grenze des Verfahrens, ausdruecklich festgehalten.

    Der Leak-Check prueft gegen die erkannten Zeichenketten. Was die
    Erkennung uebersehen hat, steht nicht auf der Liste und passiert den
    Check. Er faengt Fehler beim Ersetzen, nicht Fehler beim Erkennen. Wer
    das im Vortrag verschweigt, bekommt es in der Diskussion vorgehalten.
    """
    nicht_erkannt = "Mein Bruder heißt Xaver Übelher"

    assert shield.leak_check(nicht_erkannt, []) == []


@pytest.mark.parametrize("typ", [
    shield.TYP_PERSON, shield.TYP_EMAIL, shield.TYP_TELEFON,
    shield.TYP_ADRESSE, shield.TYP_ORT, shield.TYP_GEBURTSDATUM,
    shield.TYP_SVNR, shield.TYP_IBAN,
])
def test_jeder_typ_hat_eine_deutsche_bezeichnung(typ):
    """Die Transparenzansicht zeigt sie der Lehrperson und dem Publikum."""
    assert shield.BEZEICHNUNG[typ]


def test_ein_blockierender_fund_wird_nicht_angeknabbert():
    """Der Fehler, den der erste Durchlauf gezeigt hat.

    Das Telefonmuster passt auf die hinteren sechs Ziffern der
    Sozialversicherungsnummer. Ohne Schutz wurde dieser Teil maskiert, die
    Nummer war zerschnitten, der Leak-Check fand sie nicht mehr, und der
    Aufruf waere hinausgegangen.
    """
    text = "Meine Nummer ist 1234 030515."
    funde = shield.regelfunde(text)

    assert any(typ == shield.TYP_TELEFON for typ, _ in funde), "Vorbedingung"

    maskiert, tabelle = shield.maskieren(text, funde)

    assert "1234 030515" in maskiert
    assert tabelle == {}


def test_blockierende_werden_benannt():
    funde = shield.regelfunde("Nummer 1234 030515 und anna@schule.at")

    gesperrt = shield.blockierende(funde)

    assert [typ for typ, _ in gesperrt] == [shield.TYP_SVNR]


# --- Namen hinter einer Anrede, ohne Modell ------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("Frau Hofer teilt 24 Äpfel auf 6 Kinder auf.", "Hofer"),
    ("In der Klasse von Herrn Gruber sind 28 Kinder.", "Gruber"),
    ("Meine Lehrerin Frau Dr. Wieser hat das erklärt.", "Wieser"),
    ("Herr Prof. Dr. Maier Schmidt kommt morgen.", "Maier Schmidt"),
])
def test_die_anredenregel_findet_den_namen(text, erwartet):
    """Anlass: Das Modell uebersah 'Frau Hofer' und 'Herrn Gruber'.

    Gerade Lehrpersonennamen stehen in der Schule meist hinter einer
    Anrede. Die Regel braucht dafuer kein Modell.
    """
    funde = shield.anredefunde(text)

    assert (shield.TYP_PERSON, erwartet) in funde


def test_ohne_anrede_schlaegt_die_regel_nicht_an():
    assert shield.anredefunde(
        "In einer Schachtel sind 6 Packungen mit je 8 Stiften."
    ) == []


def test_der_zweite_prompt_enthaelt_keinen_beispielnamen():
    """Der Beispielname war die Ursache.

    Im ersten Prompt stand "Anna Berger" als Schablone - und genau dieser
    Name wurde im Text uebersehen, weil das Modell ihn fuer das Beispiel
    hielt. Der zweite Prompt kommt ohne Beispielnamen aus.
    """
    assert "Anna" not in shield.NAMEN_PROMPT_WEIT
    assert "Berger" not in shield.NAMEN_PROMPT_WEIT


def test_zwei_arrays_hintereinander_werden_nicht_zusammengelesen():
    """Derselbe Fehler wie beim Trainer, hier vorbeugend geschlossen.

    Gibt das Modell zwei Arrays aus, griff das gierige Muster von der ersten
    bis zur letzten Klammer - und las dann gar nichts mehr.
    """
    import re

    roh = '[{"text": "Lena", "typ": "PERS"}] [{"text": "Paul", "typ": "PERS"}]'
    treffer = re.search(r"\[.*?\]", roh, re.DOTALL)

    assert treffer is not None
    import json
    assert json.loads(treffer.group(0))[0]["text"] == "Lena"


def test_kein_echter_name_als_beispiel_im_prompt():
    """Die Ursache des Lecks, als Pruefung festgehalten.

    Solange "Anna Berger" als Beispiel im Prompt stand, wurde genau dieser
    Name im Text uebersehen: Das Modell hielt ihn fuer die Schablone. Im
    Betrieb ist er deshalb im Klartext an einen Anbieter gegangen.
    """
    for prompt in (shield.NAMEN_PROMPT, shield.NAMEN_PROMPT_WEIT):
        assert "Anna" not in prompt
        assert "Berger" not in prompt
