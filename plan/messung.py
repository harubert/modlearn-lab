"""Was wirklich gleichzeitig lief, aus dem Forschungsprotokoll gerechnet.

Der Teil, auf den es ankommt. Eine Kapazitaetszahl, die niemand nachprueft,
ist geraten. Hier steht die Buchung neben der gemessenen Gleichzeitigkeit,
und aus der Schaetzung wird eine Beobachtung.

Gerechnet wird aus den Anfragezeilen: Jede traegt den Zeitpunkt und die
Dauer, eine Anfrage lief also von (Zeitpunkt minus Dauer) bis Zeitpunkt. Wer
diese Spannen uebereinanderlegt, sieht die echte Gleichzeitigkeit.

Was dabei NICHT herauskommt, und das gehoert dazugesagt: die Zahl der
Personen. Fuenfundzwanzig Kinder erzeugen im Schnitt gut EINE gleichzeitige
Anfrage, weil eine Anfrage vier Sekunden dauert und niemand pausenlos
drueckt. Die Messung zeigt die Last, nicht den Andrang.
"""

from datetime import timedelta

from django.utils import timezone

from . import konzepte
from .models import Buchung


def _spannen(von, bis):
    """Die Laufzeiten aller Anfragen im Zeitraum."""
    from tutoring.models import Interaction

    zeilen = Interaction.objects.filter(
        created_at__gte=von, created_at__lt=bis, duration_ms__gt=0
    ).values_list("created_at", "duration_ms")
    return [(ende - timedelta(milliseconds=dauer), ende) for ende, dauer in zeilen]


def hoechste_gleichzeitigkeit(spannen):
    """Wie viele Anfragen liefen zur selben Zeit, hoechstens?

    Ein Durchlauf ueber alle Anfangs- und Endpunkte. Das ist genauer als
    Zaehlen je Minute: Zwanzig Anfragen in einer Minute koennen nacheinander
    gelaufen sein.
    """
    punkte = []
    for anfang, ende in spannen:
        punkte.append((anfang, 1))
        punkte.append((ende, -1))
    punkte.sort()

    jetzt = hoechste = 0
    for _, richtung in punkte:
        jetzt += richtung
        hoechste = max(hoechste, jetzt)
    return hoechste


def spitze_bisher(tage=30):
    """Die hoechste Gleichzeitigkeit der letzten Wochen.

    Steht auf der Planungsseite, damit niemand glaubt, er muesse die
    Maschine fuer sich allein buchen.
    """
    bis = timezone.now()
    return hoechste_gleichzeitigkeit(_spannen(bis - timedelta(days=tage), bis))


def vergleich(tage=14):
    """Je Tag: was gebucht war, und was wirklich lief."""
    heute = timezone.localdate()
    zeilen = []

    for versatz in range(tage):
        tag = heute - timedelta(days=versatz)
        beginn = timezone.make_aware(
            timezone.datetime.combine(tag, timezone.datetime.min.time())
        )
        ende = beginn + timedelta(days=1)

        gebucht = 0
        # Das Konzept der groessten Buchung des Tages: Ob 120 Plaetze eine
        # Modellschulung waren oder vier Klassen, macht fuer die Deutung der
        # gemessenen Spitze einen Unterschied.
        konzept = ""
        for b in Buchung.objects.filter(
            abgesagt_am__isnull=True, beginn__gte=beginn, beginn__lt=ende
        ):
            if b.plaetze > gebucht:
                gebucht = b.plaetze
                konzept = b.konzept

        spannen = _spannen(beginn, ende)
        spitze = hoechste_gleichzeitigkeit(spannen)

        if gebucht or spannen:
            zeilen.append({
                "tag": tag,
                "gebucht": gebucht,
                "konzept": konzept,
                "konzept_name": konzepte.name(konzept),
                "konzept_symbol": konzepte.symbol(konzept),
                "spitze": spitze,
                "anfragen": len(spannen),
                # Wie weit die Buchung daneben lag. Keine Note, eine Auskunft:
                # Wer immer zu hoch bucht, nimmt anderen Platz weg, der nie
                # gebraucht wurde.
                "ueberschaetzt": max(gebucht - spitze, 0),
            })
    return zeilen
