"""Der Stilkatalog der Musikstunde (tutoring/musikstile.py).

Ohne Datenbank und ohne Netz. Geprueft wird, was der Katalog zusagt: genug
Stile in Gruppen, die Kinder kennen, englische Tags ohne Emojis, das
Zusammenfuehren mit den Vorlagen des Dienstes ohne Dubletten, und dass das
freie Feld bereinigt, begrenzt und hinter die Tags gehaengt wird, die
Gesangssprache zuletzt.
"""

from pathlib import Path

from tutoring import musikstile


def _verboten(text):
    return sorted({
        f"U+{ord(z):04X}" for z in text
        if ord(z) >= 0x1F000 or 0x2600 <= ord(z) <= 0x27BF
    })


def _pop():
    return musikstile.finden(musikstile.katalog(), "pop")


# --- Der Katalog -------------------------------------------------------------

def test_katalog_hat_mindestens_24_stile_in_gruppen():
    stile = musikstile.katalog()
    assert len(stile) >= 24
    namen = [s["name"] for s in stile]
    assert len(namen) == len(set(namen)), "Schluessel doppelt"
    for erwartet in ("kinderlied", "schlaflied", "mitmachlied", "lagerfeuer", "pop",
                     "rap", "rock", "reggae", "jazz", "weihnachten", "geburtstag",
                     "instrumental"):
        assert erwartet in namen, erwartet
    gruppen = musikstile.gruppen(stile)
    assert gruppen[0] == musikstile.KINDER
    assert musikstile.NUR_MUSIK in gruppen
    assert len(gruppen) >= 8
    # Jede Gruppe hat wenigstens einen Stil, jeder Stil eine bekannte Gruppe.
    assert all(s["gruppe"] in musikstile.GRUPPEN for s in stile)
    assert musikstile.EIGEN not in namen


def test_tags_englisch_vollstaendig_und_ohne_emoji():
    for s in musikstile.katalog():
        assert s["tags"] and s["titel"] and s["beschreibung"], s["name"]
        # Englisch heisst hier: nur ASCII, keine Umlaute im Tag-Text.
        assert s["tags"].isascii(), s["name"]
        assert s["takt"] in ("2", "3", "4", "6"), s["name"]
        assert 40 <= s["bpm"] <= 200, s["name"]
        assert s["tonart"], s["name"]
        assert not _verboten(s["titel"] + s["beschreibung"] + s["tags"]), s["name"]
        assert chr(0x2014) not in s["titel"] + s["beschreibung"], s["name"]
    assert musikstile.finden(musikstile.katalog(), "instrumental")["instrumental"] is True
    quelle = Path(musikstile.__file__).read_text(encoding="utf-8")
    assert not _verboten(quelle)
    assert chr(0x2014) not in quelle


# --- Zusammenfuehren mit dem Dienst -------------------------------------------

def test_zusammenfuehren_ohne_dubletten_und_eigen_zuletzt():
    dienst = [
        # Gleicher Schluessel wie im Katalog: nicht doppelt, Katalog gewinnt.
        {"name": "lagerfeuer", "titel": "Lagerfeuer", "tags": "Lagerfeuer deutsch", "bpm": 90},
        # Anderer Schluessel, gleicher Titel (Nebenname im Katalog).
        {"name": "sprechgesang", "titel": "Sprechgesang", "tags": "deutscher Rap"},
        # Schreibweise anders, trotzdem derselbe Stil.
        {"name": "rock-n-roll", "titel": "Rock 'n' Roll", "tags": "fifties"},
        # Neu: bleibt als Vorlage vom Dienst nutzbar, mit seinen Tags.
        {"name": "klassenhit", "titel": "Klassenhit", "tags": "froehlicher Pop",
         "bpm": 120, "tonart": "C major", "takt": "4", "beschreibung": "Pop fuer die Klasse"},
        {"name": "marsch", "titel": "Marsch / Blasmusik", "tags": "Marsch"},
        # Unbrauchbar: ohne Namen, kein Woerterbuch, "eigen" ist reserviert.
        {"name": "", "tags": "x"}, "unsinn", {"name": "eigen", "tags": "y"},
    ]
    stile = musikstile.zusammenfuehren(dienst)
    namen = [s["name"] for s in stile]

    assert namen.count("lagerfeuer") == 1
    assert musikstile.finden(stile, "lagerfeuer")["tags"].startswith("campfire")
    assert "sprechgesang" not in namen and namen.count("rap") == 1
    assert "rock-n-roll" not in namen
    assert "klassenhit" in namen and "marsch" in namen
    klassenhit = musikstile.finden(stile, "klassenhit")
    assert klassenhit["gruppe"] == musikstile.DIENST
    assert klassenhit["tags"] == "froehlicher Pop"
    assert klassenhit["bpm"] == 120 and klassenhit["takt"] == "4"
    assert namen[-1] == musikstile.EIGEN
    assert namen.count(musikstile.EIGEN) == 1
    assert musikstile.gruppen(stile)[-2:] == [musikstile.DIENST, musikstile.EIGENER]
    assert all("auch" not in s for s in stile)


def test_zusammenfuehren_ohne_dienst():
    for leer in ([], None):
        stile = musikstile.zusammenfuehren(leer)
        assert len(stile) == len(musikstile.katalog()) + 1
        assert stile[-1]["name"] == musikstile.EIGEN
        assert musikstile.DIENST not in musikstile.gruppen(stile)


# --- Tags bauen ----------------------------------------------------------------

def test_tags_bauen_haengt_freies_feld_und_gesang_an():
    pop = _pop()
    assert musikstile.tags_bauen(pop, "", "de") == pop["tags"] + ", German vocals"
    assert musikstile.tags_bauen(pop, "", "en") == pop["tags"] + ", English vocals"
    assert (musikstile.tags_bauen(pop, "  Piratenlied\nmit   Akkordeon ", "en")
            == pop["tags"] + ", Piratenlied mit Akkordeon, English vocals")
    # Ohne Liedtext wird nicht gesungen, also keine Gesangssprache.
    assert musikstile.tags_bauen(pop, "", "de", mit_gesang=False) == pop["tags"]
    inst = musikstile.finden(musikstile.katalog(), "instrumental")
    assert "German vocals" not in musikstile.tags_bauen(inst, "", "de")


def test_eigener_stil_allein():
    eigen = musikstile.finden(musikstile.zusammenfuehren([]), musikstile.EIGEN)
    assert musikstile.tags_bauen(eigen, "Piratenlied mit Möwen", "de") == \
        "Piratenlied mit Möwen, German vocals"
    assert eigen["bpm"] is None and eigen["tonart"] == "" and eigen["takt"] == ""


def test_tags_bauen_begrenzt_und_behaelt_die_sprache():
    tags = musikstile.tags_bauen(_pop(), "x" * 500, "de", tags_max=120)
    assert len(tags) <= 120
    assert tags.endswith(", German vocals")
    # Ohne Angabe gilt die Vorgabe des Dienstes; Unsinn ebenso.
    for grenze in (None, 0, -5, "600"):
        lang = musikstile.tags_bauen(_pop(), "y" * 500, "de", tags_max=grenze)
        assert len(lang) <= musikstile.TAGS_MAX


def test_eigen_bereinigen():
    assert musikstile.eigen_bereinigen("a\x00b\tc\r\nd") == "a b c d"
    assert len(musikstile.eigen_bereinigen("a" * 300)) == musikstile.EIGEN_MAX
    assert musikstile.eigen_bereinigen(None) == ""
    assert musikstile.eigen_bereinigen("   ") == ""


def test_anzeigename():
    pop = _pop()
    eigen = musikstile.finden(musikstile.zusammenfuehren([]), musikstile.EIGEN)
    assert musikstile.anzeigename(pop) == "Pop"
    assert musikstile.anzeigename(pop, "mit Möwen") == "Pop + mit Möwen"
    assert musikstile.anzeigename(eigen, "Piratenlied") == "Eigener Stil: Piratenlied"
    assert len(musikstile.anzeigename(eigen, "z" * 200)) == 80
