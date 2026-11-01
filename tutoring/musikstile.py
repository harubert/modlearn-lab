"""Der Stilkatalog der Musikstunde.

WARUM EIN EIGENER KATALOG

Der Musikdienst am Spark (core/musik.py) nennt unter /stile sechs Vorlagen:
Lagerfeuer, Klassenhit, Ballade, Sprechgesang, Marsch, Instrumental. Thomas
(19.10.2026): Es muss viel mehr Stile geben, auch solche, die Kinder kennen
und gerne haben, Kinderlieder und so weiter, und ein freies Feld. Das Modell
dahinter, ACE-Step 1.5, hat keine festen Stile: Die "tags" sind freier Text,
und trainiert wurde es ueberwiegend auf englischen Beschreibungen. Deshalb
steht hier ein Katalog mit englischen Tags und deutschen Namen, in Gruppen,
wie Kinder Musik kennen. Die Vorlagen des Dienstes bleiben daneben nutzbar
(zusammenfuehren); eine Vorlage, die es hier schon gibt, kommt nicht doppelt.

WAS AUS DEM BROWSER KOMMT UND WAS NICHT

Das Kind schickt einen Schluessel, der Server sucht den Stil und baut die
Tags (tags_bauen). Der einzige Text des Kindes, der in die Tags kommt, ist
das freie Feld "Eigener Stil": Er geht vorher durch
musik_oeffentlich.text_erlaubt, wird hier bereinigt (eigen_bereinigen), auf
EIGEN_MAX Zeichen begrenzt und an die Tags des gewaehlten Stils gehaengt,
oder er steht allein, wenn das Kind "Ganz eigener Stil" gewaehlt hat. Die
Summe bleibt unter tags_max des Dienstes. Tempo, Tonart und Takt kommen
immer aus dem Katalog, nie aus dem Browser.

Die Sprache des Gesangs ("German vocals", "English vocals") haengt der
Server an, weil die Lehrperson sie fuer alle eingestellt hat.
"""

import re

# Die Gruppen in der Reihenfolge, in der sie auf der Seite stehen.
KINDER = "Kinderlieder"
POP = "Pop und Charts"
RAP = "Rap und Beats"
ROCK = "Rock"
WELT = "Weltmusik und Tradition"
JAZZ = "Jazz und Klassik"
FESTE = "Feste"
NUR_MUSIK = "Nur Musik"
DIENST = "Weitere Vorlagen vom Spark"
EIGENER = "Eigener Stil"

GRUPPEN = (KINDER, POP, RAP, ROCK, WELT, JAZZ, FESTE, NUR_MUSIK, DIENST, EIGENER)

# Der Schluessel des freien Stils: Das Kind beschreibt ihn selbst.
EIGEN = "eigen"
EIGEN_MAX = 200
# Die Vorgabe des Dienstes (/grenzen, 19.10.2026), falls er sie nicht nennt.
TAGS_MAX = 600

GESANG = {"de": "German vocals", "en": "English vocals"}


def _stil(name, titel, gruppe, beschreibung, tags, bpm=None, tonart="", takt="",
          auch=(), instrumental=False):
    return {
        "name": name, "titel": titel, "gruppe": gruppe,
        "beschreibung": beschreibung, "tags": tags,
        "bpm": bpm, "tonart": tonart, "takt": takt,
        # Weitere Namen, unter denen der Dienst denselben Stil fuehren koennte.
        "auch": tuple(auch), "instrumental": instrumental,
    }


STILE = (
    # --- Kinderlieder ---------------------------------------------------------
    _stil("kinderlied", "Kinderlied, fröhlich", KINDER,
          "Einfach, hell, zum Mitklatschen.",
          "children's song, simple catchy melody, ukulele, glockenspiel, handclaps, "
          "warm friendly vocals, playful, cheerful",
          112, "C major", "4"),
    _stil("schlaflied", "Schlaflied", KINDER,
          "Leise und langsam, zum Einschlafen.",
          "lullaby, soft and slow, gentle fingerpicked guitar, music box, "
          "warm quiet vocals, tender, calm",
          68, "F major", "3"),
    _stil("mitmachlied", "Mitmachlied", KINDER,
          "Zum Hüpfen, Klatschen und Stampfen.",
          "children's action song, upbeat, bouncy rhythm, handclaps and stomps, "
          "call and response, accordion, cheerful vocals, energetic",
          124, "D major", "4"),
    _stil("lagerfeuer", "Lagerfeuer", KINDER,
          "Gitarre, alle singen mit.",
          "campfire song, acoustic guitar strumming, group singalong, "
          "warm and relaxed, folk, harmonica",
          96, "G major", "4"),
    # --- Pop und Charts -------------------------------------------------------
    _stil("pop", "Pop", POP,
          "Eingängig und hell wie im Radio.",
          "upbeat pop, catchy hook, bright synths, punchy drums, clean vocals, "
          "radio friendly, feel-good",
          118, "C major", "4"),
    _stil("dance", "Dance", POP,
          "Schneller Beat zum Tanzen.",
          "dance pop, EDM, four on the floor kick, bright synth lead, big drop, "
          "energetic, euphoric vocals",
          128, "A minor", "4"),
    _stil("disco", "Disco", POP,
          "Glitzerkugel und Bass.",
          "disco, funky bass line, strings, four on the floor, groovy, "
          "1970s dance floor, joyful vocals",
          120, "E minor", "4"),
    _stil("kpop", "K-Pop-artig", POP,
          "Bunt, schnell, Rap und Gesang abwechselnd.",
          "K-pop style, bright and polished, catchy chorus, layered vocals, "
          "rap verse, electronic beat, energetic",
          126, "G major", "4"),
    _stil("schlager", "Schlager", POP,
          "Zum Schunkeln und Mitsingen.",
          "German schlager, sing-along chorus, accordion and synths, steady beat, "
          "cheerful, festive",
          120, "D major", "4"),
    _stil("musical", "Musical", POP,
          "Wie auf der Bühne, mit großem Gefühl.",
          "musical theatre, Broadway style, piano and orchestra, "
          "expressive storytelling vocals, dramatic build-up",
          100, "Eb major", "4"),
    # --- Rap und Beats --------------------------------------------------------
    _stil("rap", "Sprechgesang", RAP,
          "Gereimter Text auf einem Beat.",
          "rap, spoken rhythmic vocals, boom bap drums, clear rhymes, "
          "playful flow, kid-friendly",
          92, "A minor", "4", auch=("sprechgesang",)),
    _stil("hiphop", "Hip-Hop", RAP,
          "Lässiger Beat, Bass und Reime.",
          "hip hop, laid-back groove, deep bass, vinyl scratch, "
          "relaxed rap vocals, old school",
          88, "D minor", "4"),
    _stil("trap", "Trap, leicht", RAP,
          "Schnelle Hi-Hats, tiefer Bass.",
          "light trap beat, rolling hi-hats, 808 bass, melodic rap, "
          "bright synth melody, kid-friendly",
          140, "F minor", "4"),
    # --- Rock -----------------------------------------------------------------
    _stil("rock", "Rock", ROCK,
          "E-Gitarren und Schlagzeug.",
          "rock, electric guitars, driving drums, powerful chorus, anthemic, "
          "energetic vocals",
          130, "E minor", "4"),
    _stil("punk", "Punk", ROCK,
          "Schnell, laut, kurz.",
          "pop punk, fast tempo, distorted guitars, shouted gang vocals, "
          "high energy, short and loud",
          165, "A major", "4"),
    _stil("rocknroll", "Rock 'n' Roll", ROCK,
          "Wie in den Fünfzigern, mit Klavier.",
          "1950s rock and roll, twangy electric guitar, piano, walking bass, "
          "swing feel, upbeat vocals",
          160, "A major", "4"),
    _stil("metal", "Metal, kindertauglich", ROCK,
          "Schwer und laut, aber freundlich.",
          "melodic metal, heavy guitar riffs, double kick drums, epic chorus, "
          "clean powerful vocals, heroic",
          150, "E minor", "4"),
    # --- Weltmusik und Tradition ----------------------------------------------
    _stil("volksmusik", "Volksmusik und Blasmusik", WELT,
          "Tuba, Trompete, Klarinette.",
          "alpine folk music, brass band, tuba, trumpet, clarinet, accordion, "
          "polka feel, cheerful",
          116, "Bb major", "2", auch=("blasmusik",)),
    _stil("reggae", "Reggae", WELT,
          "Entspannt, mit Offbeat.",
          "reggae, offbeat guitar skank, deep bass, relaxed groove, sunny, "
          "laid-back vocals",
          78, "G major", "4"),
    _stil("country", "Country", WELT,
          "Gitarre, Banjo, Geige.",
          "country, acoustic guitar, banjo, fiddle, steady train beat, "
          "warm storytelling vocals",
          108, "D major", "4"),
    _stil("latin", "Latin", WELT,
          "Trommeln und Trompeten, zum Tanzen.",
          "latin pop, congas and bongos, brass stabs, salsa rhythm, "
          "bright and danceable, joyful vocals",
          104, "C major", "4"),
    _stil("samba", "Samba", WELT,
          "Karneval, viele Trommeln.",
          "samba, Brazilian carnival percussion, surdo and tamborim, cavaquinho, "
          "fast and festive, group vocals",
          110, "G major", "2"),
    _stil("irishfolk", "Irish Folk", WELT,
          "Geige, Flöte, Tanzschritt.",
          "Irish folk, fiddle, tin whistle, bodhran, acoustic guitar, lively jig, "
          "pub singalong",
          120, "D major", "6"),
    # --- Jazz und Klassik -----------------------------------------------------
    _stil("jazz", "Jazz", JAZZ,
          "Klavier, Kontrabass, Besen.",
          "jazz, piano trio, upright bass, brushed drums, smooth vocals, "
          "relaxed swing, late night",
          96, "F major", "4"),
    _stil("swing", "Swing", JAZZ,
          "Big Band, Bläser, zum Tanzen.",
          "big band swing, brass section, walking bass, swinging drums, upbeat, "
          "crooner vocals",
          150, "Bb major", "4"),
    _stil("blues", "Blues", JAZZ,
          "Zwölf Takte, Gitarre, Mundharmonika.",
          "blues, twelve bar blues, electric guitar licks, harmonica, "
          "shuffle rhythm, soulful vocals",
          84, "E major", "4"),
    _stil("chor", "Chor", JAZZ,
          "Viele Stimmen, kaum Instrumente.",
          "choir, a cappella, layered choral harmonies, soft piano, "
          "warm and uplifting, children's choir",
          90, "C major", "4"),
    _stil("orchester", "Orchester und Filmmusik", JAZZ,
          "Groß, feierlich, mit Streichern.",
          "cinematic orchestral, strings, french horns, timpani, epic and emotional, "
          "film score, soaring vocals",
          80, "D minor", "4"),
    # --- Feste ----------------------------------------------------------------
    _stil("weihnachten", "Weihnachtslied", FESTE,
          "Glocken, Streicher, festlich.",
          "Christmas song, sleigh bells, warm strings, piano, festive and cozy, "
          "gentle choir, wintery",
          92, "G major", "4"),
    _stil("geburtstag", "Geburtstagslied", FESTE,
          "Fröhlich, mit Konfetti.",
          "birthday party song, cheerful, handclaps, party horns, ukulele, "
          "bright vocals, celebratory",
          120, "C major", "4"),
    _stil("fasching", "Fasching", FESTE,
          "Polonaise, laut und lustig.",
          "carnival party song, polka beat, brass band, whistles, crowd singalong, "
          "silly and loud, festive",
          130, "F major", "2"),
    # --- Nur Musik ------------------------------------------------------------
    _stil("instrumental", "Instrumental", NUR_MUSIK,
          "Nur Musik, ohne Gesang.",
          "instrumental, no vocals, melodic, piano and strings, gentle groove",
          100, "C major", "4", instrumental=True),
)

# Das freie Feld als eigener Eintrag, damit es auf der Seite wie ein Stil
# waehlbar ist. Ohne Tags: Es zaehlt nur, was das Kind beschreibt.
EIGENER_STIL = _stil(EIGEN, "Ganz eigener Stil", EIGENER,
                     "Beschreib ihn im Feld darunter.", "")


def _vergleichbar(text):
    """Nur Buchstaben und Ziffern, klein: "Rock 'n' Roll" und "rocknroll" sind eins."""
    return re.sub(r"[^a-z0-9äöüß]", "", str(text or "").lower())


def _bekannte_namen():
    namen = set()
    for s in STILE:
        namen.add(_vergleichbar(s["name"]))
        namen.add(_vergleichbar(s["titel"]))
        for a in s["auch"]:
            namen.add(_vergleichbar(a))
    return namen


def _ohne_internes(stil):
    return {k: v for k, v in stil.items() if k != "auch"}


def katalog():
    """Der eigene Katalog, ohne den freien Stil, als Liste von Kopien."""
    return [_ohne_internes(s) for s in STILE]


def zusammenfuehren(dienst_stile):
    """Katalog plus die Vorlagen des Dienstes, ohne Dubletten; "eigen" zuletzt.

    Eine Vorlage des Dienstes, deren Name oder Titel im Katalog schon
    vorkommt (auch unter einem Nebennamen), wird nicht noch einmal
    angeboten. Die uebrigen stehen in der Gruppe "Weitere Vorlagen vom
    Spark" mit den Tags, die der Dienst nennt.
    """
    bekannt = _bekannte_namen()
    stile = katalog()
    vergeben = {s["name"] for s in stile}
    for s in dienst_stile or ():
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        titel = str(s.get("titel") or name).strip()
        if not name or name in vergeben or name == EIGEN:
            continue
        if _vergleichbar(name) in bekannt or _vergleichbar(titel) in bekannt:
            continue
        vergeben.add(name)
        stile.append(_ohne_internes(_stil(
            name[:80], titel[:80], DIENST,
            str(s.get("beschreibung") or "")[:200],
            str(s.get("tags") or ""),
            s.get("bpm") if isinstance(s.get("bpm"), int) and not isinstance(s.get("bpm"), bool) else None,
            str(s.get("tonart") or "")[:20],
            str(s.get("takt") or "")[:4],
            instrumental=_vergleichbar(name) == "instrumental",
        )))
    stile.append(_ohne_internes(EIGENER_STIL))
    return stile


def gruppen(stile):
    """Die Gruppennamen in der Reihenfolge von GRUPPEN, nur die vorkommenden."""
    vorhanden = {s["gruppe"] for s in stile}
    reihe = [g for g in GRUPPEN if g in vorhanden]
    reihe += sorted(g for g in vorhanden if g not in GRUPPEN)
    return reihe


def finden(stile, name):
    return next((s for s in stile if s["name"] == name), None)


def eigen_bereinigen(text):
    """Das freie Feld: eine Zeile, ohne Steuerzeichen, hoechstens EIGEN_MAX."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:EIGEN_MAX].strip()


def tags_bauen(stil, eigen, sprache, tags_max=None, mit_gesang=True):
    """Die Tags fuer den Auftrag: Stil, freies Feld, Gesangssprache; begrenzt.

    Die Sprache des Gesangs kommt zuletzt und bleibt beim Kuerzen stehen:
    Wird es zu lang, verliert das freie Feld Zeichen, nicht die Sprache.
    Beim freien Stil allein stehen nur das Feld und die Sprache.
    """
    hoechstens = tags_max if isinstance(tags_max, int) and tags_max > 0 else TAGS_MAX
    schluss = ""
    if mit_gesang and not stil.get("instrumental"):
        schluss = GESANG.get(sprache, "")
    teile = [t for t in (str(stil.get("tags") or "").strip(), eigen_bereinigen(eigen)) if t]
    basis = ", ".join(teile)
    platz = hoechstens - (len(schluss) + 2 if schluss else 0)
    if len(basis) > platz:
        basis = basis[:max(platz, 0)].rstrip(" ,")
    return ", ".join(t for t in (basis, schluss) if t)


def anzeigename(stil, eigen=""):
    """Was bei uns als Stil des Liedes steht (Lied.stil, hoechstens 80 Zeichen)."""
    eigen = eigen_bereinigen(eigen)
    if stil["name"] == EIGEN:
        return f"Eigener Stil: {eigen}"[:80]
    if eigen:
        return f"{stil['titel']} + {eigen}"[:80]
    return stil["titel"][:80]
