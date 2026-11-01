"""Buchungen auf dem Spark.

WAS HIER RESERVIERT WIRD, UND WAS NICHT

Nicht die Maschine, sondern ein Anteil davon. Der Unterschied ist nicht
Wortklauberei, sondern folgt aus der Messung:

- Im Betrieb lag die hoechste tatsaechliche Gleichzeitigkeit bei DREI,
  ueber zehn Tage, einschliesslich einer Vorfuehrung mit 28 Leuten im Raum.
- Der Lasttest zeigte 50 gleichzeitige Anfragen in 6,4 Sekunden, ohne einen
  einzigen Ausfall.

Der Grund ist Arithmetik: Eine Anfrage dauert rund vier Sekunden, ein Kind
holt sich vielleicht alle siebzig Sekunden einen Tipp. Eine ganze Klasse ist
im Schnitt also gut ein Platz, mit Spitzen, wenn alle gleichzeitig druecken.
Wer "den Spark" von 13 bis 14 Uhr bucht, sperrt alle anderen aus und nutzt
dabei etwa sechs Prozent der Maschine.

Eine Buchung ist deshalb eine ZUSAGE und keine Sperre. Sie sagt: "Zu dieser
Zeit ist Platz fuer meine Klasse." Wer nicht gebucht hat, darf trotzdem
arbeiten, solange Plaetze frei sind.

ZWEI GRUENDE, UEBERHAUPT ZU BUCHEN

Zusage: Eine Stunde mit 25 Kindern darf nicht davon abhaengen, ob zufaellig
jemand einen Dauerlauf startet.

Fairness: Damit niemand einen Workshop fuer zweihundert Leute plant, der mit
drei Klassen kollidiert.

WOFUER GEBUCHT WIRD, STEHT SEIT DEN NUTZUNGSKONZEPTEN DABEI

Plaetze addieren sich, Modelle nicht. Zwei Klassen im Unterricht teilen den
Rechner; eine Buchung, die ein Modell braucht, das nicht im Speicher liegt,
baut ihn um und ist damit fuer ihren Zeitraum ALLEINIG. Deshalb traegt jede
Buchung ihr Konzept (plan/konzepte.py), und belegung() weist eine alleinige
Buchung als voll aus - egal, wie viele Plaetze sie fuer sich selbst nennt.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from tutoring import faecher

# Als `katalog`, weil die Nutzerklasse ein Feld `konzepte` hat und der
# Modulname im Klassenrumpf sonst von diesem Feld verdeckt wuerde.
from . import konzepte as katalog


class Nutzerklasse(models.Model):
    """Was eine Gruppe von Buchenden darf.

    Die Grenzen stehen hier und nicht im Code, weil sie sich aendern werden:
    Nach dem ersten Semester weiss man mehr als heute.
    """

    name = models.CharField("Name", max_length=60, unique=True)
    beschreibung = models.CharField("Wofür", max_length=200, blank=True)

    max_minuten = models.PositiveIntegerField(
        "Längste Buchung in Minuten", default=120
    )
    max_slots_woche = models.PositiveIntegerField(
        "Buchungen je Woche", default=5
    )
    max_plaetze = models.PositiveIntegerField(
        "Plätze je Buchung", default=30
    )
    # Wer das darf, kann bis zur vollen Kapazitaet buchen und damit andere
    # tatsaechlich aussperren. Das ist die Ausnahme, nicht die Regel.
    darf_voll_belegen = models.BooleanField(
        "Darf die Maschine ganz belegen", default=False
    )
    # Welche Nutzungskonzepte diese Klasse buchen darf, als Schluessel aus
    # plan/konzepte.py mit Komma getrennt. Eine Lehrperson bucht Unterricht;
    # wer den Rechner umbauen darf (Wissensdienst, Modellschulung), steht
    # hier ausdruecklich. Bewusst ein Textfeld und keine eigene Tabelle: Es
    # sind fuenf Schluessel, und sie aendern sich im Admin, nicht im Code.
    konzepte = models.CharField(
        "Erlaubte Nutzungskonzepte", max_length=200,
        default=katalog.STANDARD,
        help_text="Schlüssel mit Komma getrennt: "
                  + ", ".join(katalog.SCHLUESSEL),
    )

    class Meta:
        verbose_name = "Nutzerklasse"
        verbose_name_plural = "Nutzerklassen"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def erlaubte_konzepte(self):
        """Die Schluessel, die diese Klasse buchen darf, in der Reihenfolge
        von konzepte.KONZEPTE.

        Unbekannte Schluessel fallen stillschweigend weg: Ein Tippfehler im
        Admin soll eine Lehrperson nicht aussperren, sondern hoechstens ein
        Konzept weniger zeigen.
        """
        genannt = {
            teil.strip().lower()
            for teil in (self.konzepte or "").split(",")
            if teil.strip()
        }
        return [s for s in katalog.SCHLUESSEL if s in genannt]

    def darf_konzept(self, schluessel):
        return (schluessel or "").strip().lower() in self.erlaubte_konzepte()


class Profil(models.Model):
    """Verbindet einen Zugang mit seiner Nutzerklasse."""

    benutzer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="planprofil",
    )
    klasse = models.ForeignKey(
        Nutzerklasse, on_delete=models.PROTECT, related_name="profile"
    )
    einrichtung = models.CharField("Einrichtung", max_length=120, blank=True)
    gesperrt_am = models.DateTimeField("Gesperrt am", null=True, blank=True)

    class Meta:
        verbose_name = "Planungsprofil"
        verbose_name_plural = "Planungsprofile"

    def __str__(self):
        return f"{self.benutzer} ({self.klasse})"

    @property
    def darf_buchen(self):
        return self.gesperrt_am is None

    def slots_diese_woche(self, bezug=None):
        """Wie viele Buchungen in der laufenden Woche schon stehen.

        Gezaehlt wird die Woche der BUCHUNG, nicht die des Anlegens: Wer am
        Freitag fuer die naechste Woche plant, verbraucht sein Kontingent
        dort und nicht hier.
        """
        bezug = bezug or timezone.localdate()
        montag = bezug - timedelta(days=bezug.weekday())
        sonntag = montag + timedelta(days=7)
        return Buchung.objects.filter(
            besitzer=self.benutzer, abgesagt_am__isnull=True,
            beginn__date__gte=montag, beginn__date__lt=sonntag,
        ).count()

    def slots_frei_woche(self, bezug=None):
        offen = self.klasse.max_slots_woche - self.slots_diese_woche(bezug)
        return max(offen, 0)


class Buchung(models.Model):
    """Eine Zusage: so viele Plaetze, von wann bis wann."""

    besitzer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="buchungen",
    )
    beginn = models.DateTimeField("Beginn")
    ende = models.DateTimeField("Ende")
    plaetze = models.PositiveIntegerField("Plätze", default=1)
    zweck = models.CharField("Wofür", max_length=160, blank=True)
    # Wofuer der Spark in dieser Zeit gebraucht wird. Das entscheidet, ob
    # andere daneben arbeiten koennen; siehe plan/konzepte.py.
    konzept = models.CharField(
        "Nutzungskonzept", max_length=30, choices=katalog.AUSWAHL,
        default=katalog.STANDARD,
    )
    # Fach und Person sind Auskunft fuer die anderen und den Rueckblick,
    # keine Pruefgrundlage. Beide duerfen leer bleiben.
    fach = models.CharField(
        "Fach", max_length=20, choices=faecher.AUSWAHL, blank=True,
    )
    person = models.CharField("Für wen", max_length=120, blank=True)

    angelegt_am = models.DateTimeField(auto_now_add=True)
    abgesagt_am = models.DateTimeField("Abgesagt am", null=True, blank=True)

    class Meta:
        verbose_name = "Buchung"
        verbose_name_plural = "Buchungen"
        ordering = ["beginn"]
        indexes = [models.Index(fields=["beginn", "ende"])]

    def __str__(self):
        return (f"{self.beginn:%d.%m. %H:%M}–{self.ende:%H:%M} "
                f"{self.plaetze} Plätze ({self.besitzer})")

    @property
    def laeuft(self):
        return self.abgesagt_am is None

    @property
    def dauer_minuten(self):
        return int((self.ende - self.beginn).total_seconds() // 60)

    @property
    def alleinig(self):
        """Belegt diese Buchung den Rechner allein?"""
        return katalog.ist_alleinig(self.konzept)

    @property
    def konzept_name(self):
        return katalog.name(self.konzept)

    @property
    def konzept_symbol(self):
        return katalog.symbol(self.konzept)

    @property
    def fach_name(self):
        return faecher.name(self.fach)

    def clean(self):
        if self.ende <= self.beginn:
            raise ValidationError("Das Ende liegt vor dem Beginn.")


def belegung(tag, von_minute=None, bis_minute=None):
    """Was an diesem Tag je Viertelstunde laeuft.

    Gibt eine Liste von (minute_ab_mitternacht, plaetze, konzepte) zurueck,
    in Viertelstundenschritten. `konzepte` ist das Tupel der Schluessel, die
    in dieser Viertelstunde gebucht sind, jeder einmal und in der Reihenfolge
    des Beginns - damit die Seite erklaeren kann, WAS da laeuft, und nicht
    nur, wie viel.

    Eine alleinige Buchung (sie baut den Rechner um oder nimmt ihn ganz)
    zaehlt als VOLL: Die Plaetze stehen auf der Gesamtkapazitaet, egal wie
    viele sie fuer sich selbst nennt. Daneben geht nichts, und genau das
    soll der Balken zeigen.

    Gerechnet wird ueber alle laufenden Buchungen des Tages, nicht je
    Buchung einzeln: Dreissig Buchungen mal achtundvierzig Viertelstunden
    waeren sonst vierzehnhundert Abfragen.
    """
    von_minute = SCHRITT * (von_minute // SCHRITT) if von_minute else TAG_VON
    bis_minute = bis_minute or TAG_BIS
    gesamt = settings.SPARK_PLAETZE

    beginn_tag = timezone.make_aware(
        timezone.datetime.combine(tag, timezone.datetime.min.time())
    )
    laufende = Buchung.objects.filter(
        abgesagt_am__isnull=True,
        beginn__lt=beginn_tag + timedelta(days=1),
        ende__gt=beginn_tag,
    ).order_by("beginn")

    spannen = []
    for b in laufende:
        a = timezone.localtime(b.beginn)
        e = timezone.localtime(b.ende)
        spannen.append((
            a.hour * 60 + a.minute, e.hour * 60 + e.minute,
            b.plaetze, b.konzept, b.alleinig,
        ))

    raster = []
    for minute in range(von_minute, bis_minute, SCHRITT):
        belegt = 0
        voll = False
        laufend = []
        for a, e, p, k, allein in spannen:
            if not (a <= minute < e):
                continue
            belegt += p
            voll = voll or allein
            if k not in laufend:
                laufend.append(k)
        if voll:
            belegt = max(belegt, gesamt)
        raster.append((minute, belegt, tuple(laufend)))
    return raster


def ueberlappende(beginn, ende):
    """Die laufenden Buchungen, die diesen Zeitraum beruehren, nach Beginn.

    Fuer die Vertraeglichkeitspruefung beim Buchen: Dort zaehlt nicht die
    Summe der Plaetze, sondern jede einzelne Buchung mit ihrem Konzept.
    """
    return Buchung.objects.filter(
        abgesagt_am__isnull=True, beginn__lt=ende, ende__gt=beginn,
    ).order_by("beginn")


# Der sichtbare Tag. Ausserhalb wird nicht gebucht: Eine Zusage fuer drei Uhr
# nachts waere keine, weil dann niemand da ist, der sie einhaelt.
TAG_VON = 7 * 60
TAG_BIS = 19 * 60
SCHRITT = 15

# Ein Zehntel bleibt frei. Das ist die Zahl, die aus "eine Buchung ist eine
# Zusage und keine Sperre" folgt: Wer nicht gebucht hat, soll trotzdem
# arbeiten koennen, und das geht nur, wenn nie alles vergeben ist. Nur eine
# Klasse mit darf_voll_belegen kommt daran - fuer den Lasttest, der die
# Maschine absichtlich bis an den Rand fuellt.
RESERVE_TEILER = 10


def freie_obergrenze(gesamt, klasse=None):
    """Wie viele Plaetze eine Buchung hoechstens belegen darf."""
    if klasse is not None and klasse.darf_voll_belegen:
        return gesamt
    return max(gesamt - gesamt // RESERVE_TEILER, 1)
