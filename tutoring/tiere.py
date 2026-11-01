"""Die Tiere, mit denen sich Teilnehmende in einer Sitzung unterscheiden.

Ein Kind waehlt beim Beitreten ein Tier. Innerhalb einer Sitzung ist jedes
Tier nur einmal zu haben. Damit kann die Lehrperson die Verlaeufe
auseinanderhalten, ohne dass irgendwo ein Name steht.

Gespeichert wird der Schluessel, nicht das Bild: So bleibt die Angabe in der
Datenbank lesbar und von der Darstellung unabhaengig. Jedes Tier hat einen
deutschen Namen, denn ein Bild allein ist fuer ein Vorlesewerkzeug nichts.

Die Bilder sind eigens erzeugte Knetfiguren in einem einheitlichen Stil,
keine Emoji. Emoji sehen auf jedem Geraet anders aus, manche fehlen ganz,
und als Gestaltung wirken sie beliebig.
"""

TIERE = (
    ("fuchs", "Fuchs"),
    ("igel", "Igel"),
    ("eule", "Eule"),
    ("hase", "Hase"),
    ("baer", "Bär"),
    ("dachs", "Dachs"),
    ("biber", "Biber"),
    ("eichhoernchen", "Eichhörnchen"),
    ("reh", "Reh"),
    ("wolf", "Wolf"),
    ("maus", "Maus"),
    ("hamster", "Hamster"),
    ("katze", "Katze"),
    ("hund", "Hund"),
    ("pferd", "Pferd"),
    ("kuh", "Kuh"),
    ("schwein", "Schwein"),
    ("schaf", "Schaf"),
    ("ziege", "Ziege"),
    ("huhn", "Huhn"),
    ("ente", "Ente"),
    ("schwan", "Schwan"),
    ("adler", "Adler"),
    ("biene", "Biene"),
    ("schmetterling", "Schmetterling"),
    ("marienkaefer", "Marienkäfer"),
    ("schildkroete", "Schildkröte"),
    ("frosch", "Frosch"),
    ("delfin", "Delfin"),
    ("wal", "Wal"),
    ("krake", "Krake"),
    ("pinguin", "Pinguin"),
    ("giraffe", "Giraffe"),
    ("zebra", "Zebra"),
    ("kaenguru", "Känguru"),
    ("papagei", "Papagei"),
)

# Nachschlagewerk fuer die Anzeige.
NACH_SCHLUESSEL = {schluessel: name for schluessel, name in TIERE}

SCHLUESSEL = tuple(schluessel for schluessel, _ in TIERE)


def ist_bekannt(schluessel):
    return schluessel in NACH_SCHLUESSEL


def bild(schluessel):
    """Pfad der Grafik, relativ zum statischen Verzeichnis."""
    if schluessel not in NACH_SCHLUESSEL:
        return ""
    return f"img/tiere/{schluessel}.webp"


def name(schluessel):
    return NACH_SCHLUESSEL.get(schluessel, "unbekannt")


def freie(vergebene):
    """Alle Tiere mit der Angabe, ob sie in dieser Sitzung noch zu haben sind."""
    vergeben = set(vergebene)
    return [
        {
            "schluessel": schluessel,
            "bild": bild(schluessel),
            "name": name_,
            "vergeben": schluessel in vergeben,
        }
        for schluessel, name_ in TIERE
    ]
