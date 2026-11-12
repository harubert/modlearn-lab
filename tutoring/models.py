"""Datenmodell der Aufgabenhilfe.

Leitgedanke: Teilnehmende haben kein Konto und keinen Namen. Was waehrend
einer Sitzung entsteht, haengt an der Sitzung und stirbt mit ihr.

Die Lehrperson sieht die Verlaeufe ihrer Sitzung, geordnet nach dem Tier,
das sich ein Kind gewaehlt hat. Das ist eine bewusste Entscheidung: Wer
begleiten soll, muss sehen, woran ein Kind haengt. Ein Name steht trotzdem
nirgends, und mit dem Ende der Sitzung ist alles geloescht.
"""

import dataclasses
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import (faecher, levels, musikstunde, pruefung, sprechablauf,
               sprechaufgaben, sprechcoach, tiere, trainer)

# Eine Sitzung bleibt offen, bis die Lehrperson sie beendet. Das ist die
# Grundeinstellung, weil ein Code, der mitten in der Stunde stirbt, schlimmer
# ist als einer, der zu lange gilt. Wer den Verfall will, stellt ihn beim
# Anlegen ein.
VERFALL_WAHLEN = (
    ("", "bleibt offen, bis ich sie beende"),
    ("60", "verfällt nach 1 Stunde ohne Aktivität"),
    ("240", "verfällt nach 4 Stunden ohne Aktivität"),
    ("720", "verfällt nach 12 Stunden ohne Aktivität"),
)

VERFALL_MINUTEN = {60, 240, 720}

# Wie ist eine Eingabe zustande gekommen? Fuer die Auswertung im Lab ist das
# eine eigene Frage: Ob Kinder lieber tippen, fotografieren oder sprechen,
# laesst sich nachher nicht mehr rekonstruieren.
GETIPPT = "tippen"
FOTOGRAFIERT = "foto"
GESPROCHEN = "sprache"
VORGEGEBEN = "lehrperson"   # aus dem Aufgabenpool der Lehrperson (1.11.2026)

HERKUNFT = (
    (VORGEGEBEN, "von der Lehrperson"),
    (GETIPPT, "getippt"),
    (FOTOGRAFIERT, "fotografiert"),
    (GESPROCHEN, "gesprochen"),
)

# Das Foto wird aufgehoben, die Tonaufnahme nicht. Das Bild zeigt der
# Lehrperson, was das Kind vor sich hatte, und die Texterkennung kann
# danebengelegen haben. Bei Sprache ist der erkannte Text das Ergebnis; die
# Aufnahme selbst ist eine Stimme und damit das heikelste, was hier anfallen
# koennte. Sie wird nie gespeichert.

# Protokollstufen nach Abschnitt 3b. Die Lehrperson waehlt beim Anlegen.
BETRIEB = 1
FORSCHUNG_MASKIERT = 2
FORSCHUNG_VOLL = 3

PROTOKOLLSTUFEN = (
    (BETRIEB, "Betrieb: nur Metadaten, keine Inhalte"),
    (FORSCHUNG_MASKIERT, "Forschung: zusätzlich der maskierte Text"),
    (FORSCHUNG_VOLL, "Forschung vollständig: zusätzlich der Originaltext"),
)


def code_erzeugen():
    """Sechsstellige Ziffernfolge, fuehrende Null ausgeschlossen.

    Ziffern, weil die Lehrperson den Code im Hoersaal vorliest und Ziffern
    ueber eine Leinwand und durch einen Raum eindeutiger sind als Buchstaben.
    """
    return str(secrets.randbelow(900000) + 100000)


class LearningSessionQuerySet(models.QuerySet):
    def verfallene(self):
        """Sitzungen, deren eingestellte Frist abgelaufen ist.

        Sitzungen ohne Frist sind nie dabei. Die Frist haengt an der einzelnen
        Sitzung, deshalb wird in Python verglichen statt in der Abfrage: Die
        Vorauswahl in der Datenbank laesst ohnehin nur die wenigen Sitzungen
        uebrig, fuer die ueberhaupt eine Frist eingestellt ist.
        """
        jetzt = timezone.now()
        faellig = [
            sitzung.pk
            for sitzung in self.filter(
                idle_timeout_minutes__isnull=False, closed_at__isnull=True
            ).only("pk", "last_activity_at", "idle_timeout_minutes")
            if sitzung.last_activity_at
            + timedelta(minutes=sitzung.idle_timeout_minutes) < jetzt
        ]
        return self.filter(pk__in=faellig)


class LearningSession(models.Model):
    """Eine Unterrichtsstunde mit Code."""

    code = models.CharField("Sitzungscode", max_length=6, unique=True, db_index=True)
    # Der sechsstellige Code steht auf der Leinwand und ist damit oeffentlich.
    # Im Forschungsprotokoll steht deshalb dieser zweite, nicht sichtbare
    # Schluessel: Das Protokoll ueberlebt die Sitzung, der Code nicht.
    log_key = models.CharField(max_length=43, unique=True, db_index=True, blank=True)
    title = models.CharField("Titel", max_length=120)
    research_level = models.PositiveSmallIntegerField(
        "Protokollstufe", choices=PROTOKOLLSTUFEN, default=FORSCHUNG_VOLL
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_sessions"
    )
    max_level = models.PositiveSmallIntegerField(
        "Hilfe-Obergrenze", choices=levels.OBERGRENZEN, default=levels.NUR_TIPPS
    )
    # Ob vor der Loesung zurueckgefragt wird. Bei "nur Tipps" ohne Bedeutung.
    ask_before_solution = models.BooleanField(
        "Vor der Lösung nachfragen", default=True
    )
    age_group = models.CharField(
        "Altersklasse", max_length=12, choices=levels.ALTERSKLASSEN,
        default=levels.ALTERSKLASSE_STANDARD,
    )
    # Die Schulstufe loest in Mathematik die Altersklasse ab (Benchmark vom
    # 19.10.2026, docs/Mathe-Benchmark und Konfiguration.md, Abschnitt 6.2):
    # Die Altersklasse hat nur die Anrede veraendert, die Fehler lagen in
    # Anweisungen und Pruefung, die sie nicht erreicht hat. Die Schulstufe
    # waehlt Anweisungen, Pruefung und Diagnose; age_group wird aus ihr
    # abgeleitet (levels.altersklasse_fuer) und bleibt fuer die anderen Faecher.
    schulstufe = models.CharField(
        "Schulstufe", max_length=5, choices=levels.SCHULSTUFEN,
        default=levels.SCHULSTUFE_STANDARD,
    )
    # Zwei Betriebsarten derselben Sitzung. Die Aufgabenhilfe haelt zurueck,
    # der Trainer erklaert. Beitritt, Tierwahl, Klassenliste, Verfall und
    # Beenden gelten fuer beide unveraendert; eine zweite Sitzungsart waere
    # eine zweite Stelle, an der man das Loeschen vergessen kann.
    BETRIEB_HILFE = "hilfe"
    BETRIEB_TRAINER = "trainer"
    BETRIEB_SPRACHE = "sprache"
    BETRIEB_MUSIK = "musik"
    # Der Safe Chat (Thomas, 23.10.2026): inhaltlich offen, Antwort vom
    # Spark, auf Knopfdruck nach draussen durch den Filter, mit Protokoll.
    BETRIEB_CHAT = "chat"
    BETRIEBSARTEN = (
        (BETRIEB_HILFE, "Aufgabenhilfe"),
        (BETRIEB_TRAINER, "Trainer für alles"),
        (BETRIEB_SPRACHE, "Sprechcoach"),
        (BETRIEB_MUSIK, "Musikstunde"),
        (BETRIEB_CHAT, "Safe Chat"),
    )
    mode = models.CharField(
        "Betriebsart", max_length=10, choices=BETRIEBSARTEN,
        default=BETRIEB_HILFE,
    )
    # Das Fach ist die Abzweigung beim Anlegen, die Betriebsart folgt daraus.
    # Beides steht da und nicht nur eines: Die Betriebsart braucht die
    # Anwendung zum Arbeiten, das Fach braucht der Mensch zum Wiederfinden.
    # "Deutsch" und "Sachunterricht" fuehren in dieselbe Betriebsart und sind
    # in der Uebersicht trotzdem zweierlei.
    #
    # Leer bei allen Sitzungen von vor der Umstellung. Die Uebersicht muss das
    # aushalten, deshalb kein Standardwert, der etwas behauptet.
    subject = models.CharField(
        "Fach", max_length=20, choices=faecher.AUSWAHL, blank=True,
    )
    # Nur fuer den Sprechcoach. Der Code ist BCP-47, weil ihn die
    # Sprachausgabe des Browsers und das lang-Attribut genau so brauchen.
    target_language = models.CharField(
        "Zielsprache", max_length=8, choices=sprechcoach.SPRACHEN,
        default=sprechcoach.SPRACHE_STANDARD,
    )
    language_level = models.CharField(
        "Niveau", max_length=4, choices=sprechcoach.NIVEAUS,
        default=sprechcoach.NIVEAU_STANDARD,
    )
    # Die Gespraechsaufgabe des Sprechcoachs (tutoring/sprechaufgaben.py).
    # Leer heisst freies Gespraech: so verhalten sich alle Sitzungen von vor
    # den Aufgaben, und so bleibt es fuer Sprachen ohne Aufgabenliste.
    # Regel 11 des Berichts: Aufgabe mit Ziel und Informationsluecke statt
    # Smalltalk (Bibauw et al. 2022: system-guided d = 0,97, open-ended n.s.).
    speaking_task = models.CharField(
        "Gesprächsaufgabe", max_length=40, blank=True, default="",
    )
    # Nur fuer die Musikstunde (tutoring/musikstunde.py). An der Sitzung und
    # nicht je Kind, weil die Lehrperson sie fuer die ganze Klasse setzt und
    # der Server sie bei jedem Lied durchsetzt.
    song_max_seconds = models.PositiveSmallIntegerField(
        "Höchstdauer je Lied", choices=musikstunde.HOECHSTDAUERN,
        default=musikstunde.HOECHSTDAUER_STANDARD,
    )
    songs_per_child = models.PositiveSmallIntegerField(
        "Lieder je Kind", default=musikstunde.LIEDER_STANDARD,
    )
    song_language = models.CharField(
        "Sprache des Gesangs", max_length=2, choices=musikstunde.GESANGSSPRACHEN,
        default=musikstunde.GESANG_STANDARD,
    )
    # Ob die Kinder sich einen Liedtext vom Sprachmodell schreiben lassen
    # duerfen (tutoring/musik_views.text). Aus heisst: kein Knopf auf der
    # Seite, und der Endpunkt antwortet 403.
    song_text_help = models.BooleanField(
        "Die Kinder dürfen sich einen Text vom Spark schreiben lassen", default=True,
    )
    task_hint = models.CharField(
        "Hinweis zur Aufgabenart", max_length=200, blank=True,
        help_text="Optional, zum Beispiel: schriftliche Multiplikation, Sachaufgaben zu Längen.",
    )
    # In der Oberflaeche heisst das Qualitaetssicherung, und das ist keine
    # Beschoenigung, sondern die Funktion: Die Lehrperson holt bei schweren
    # Aufgaben eine zweite, staerkere Einschaetzung dazu. Der Privacy Shield
    # ist der Mechanismus dahinter, nicht der Name des Knopfes.
    #
    # Grundeinstellung aus: ohne ausdrueckliche Freigabe verlaesst nichts die
    # Infrastruktur der PH.
    cloud_enabled = models.BooleanField("Qualitätssicherung", default=False)
    # Der zweite Schalter (Thomas, 31.10.2026): Darf von einem Foto der
    # Aufgabe ein zugeschnittener, bereinigter Ausschnitt mit hinausgehen?
    # Nur zusammen mit der Qualitaetssicherung, Standard aus, und auch dann
    # geht nur hinaus, was die Bildkette (bildkette.py) durchgelassen hat.
    cloud_images_enabled = models.BooleanField(
        "Fotos der Aufgabe prüfen lassen", default=False
    )

    # Leer heisst: bleibt offen, bis die Lehrperson sie beendet.
    idle_timeout_minutes = models.PositiveIntegerField(
        "Verfall nach Minuten ohne Aktivität", null=True, blank=True, default=None
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    objects = LearningSessionQuerySet.as_manager()

    class Meta:
        verbose_name = "Sitzung"
        verbose_name_plural = "Sitzungen"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} – {self.title}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._freien_code_finden()
        if not self.log_key:
            self.log_key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @staticmethod
    def _freien_code_finden():
        for _ in range(50):
            code = code_erzeugen()
            if not LearningSession.objects.filter(code=code).exists():
                return code
        raise RuntimeError("Kein freier Sitzungscode gefunden.")

    @property
    def ist_offen(self):
        if self.closed_at is not None:
            return False
        if self.verfaellt_um is None:
            return True
        return timezone.now() < self.verfaellt_um

    @property
    def ist_hilfe(self):
        """Die Aufgabenhilfe (Mathematik): die Betriebsart mit Aufgaben und Stufen."""
        return self.mode == self.BETRIEB_HILFE

    @property
    def ist_trainer(self):
        return self.mode == self.BETRIEB_TRAINER

    @property
    def ist_sprechcoach(self):
        return self.mode == self.BETRIEB_SPRACHE

    @property
    def ist_musik(self):
        return self.mode == self.BETRIEB_MUSIK

    @property
    def ist_safechat(self):
        return self.mode == self.BETRIEB_CHAT

    @property
    def sprechaufgabe(self):
        """Die Gespraechsaufgabe als Eintrag, nie None: sonst das freie."""
        return sprechaufgaben.aufgabe(self.speaking_task, self.target_language)

    @property
    def ist_volksschule(self):
        return sprechablauf.ist_volksschule(self.age_group)

    @property
    def altersklasse_kurz(self):
        return levels.ALTERSKLASSEN_KURZ.get(
            self.age_group, self.get_age_group_display()
        )

    @property
    def fach_name(self):
        """Der Fachname, oder die Betriebsart als Rueckfallebene.

        Sitzungen von vor der Fachumstellung haben kein Fach. Dort ist die
        Betriebsart das Ehrlichste, was sich sagen laesst - "Aufgabenhilfe"
        und nicht ein erfundenes "Mathematik".
        """
        return faecher.name(self.subject) or self.get_mode_display()

    @property
    def fach_symbol(self):
        """Das Symbol, oder ein leerer Text. Nie ein Platzhaltersymbol.

        Ein Fragezeichen neben einer alten Sitzung sieht nach einem Fehler
        aus, und es ist keiner: Das Fach gab es damals noch nicht.
        """
        return faecher.symbol(self.subject)

    @property
    def verfaellt_um(self):
        """Zeitpunkt des Verfalls, oder None wenn die Sitzung offen bleibt."""
        if self.idle_timeout_minutes is None:
            return None
        return self.last_activity_at + timedelta(minutes=self.idle_timeout_minutes)

    @property
    def zustimmung_noetig(self):
        """Wird vor dem Beitritt um Zustimmung gefragt?

        Nur bei Erwachsenen. Minderjaehrige koennen in eine
        Forschungsverarbeitung rechtlich nicht selbst einwilligen; das
        entscheiden Schule und Erziehungsberechtigte ausserhalb dieser
        Anwendung. Ein Zustimmungsbildschirm fuer Kinder waere deshalb nicht
        nur ueberfluessiger Text, sondern eine falsche Auskunft.
        """
        return (self.research_level == FORSCHUNG_VOLL
                and self.age_group == "erwachsen")

    @property
    def verfall_beschreibung(self):
        if self.idle_timeout_minutes is None:
            return "bleibt offen, bis du sie beendest"
        stunden = self.idle_timeout_minutes / 60
        zahl = int(stunden) if stunden == int(stunden) else stunden
        einheit = "Stunde" if zahl == 1 else "Stunden"
        return f"verfällt nach {zahl} {einheit} ohne Aktivität"

    def beruehren(self):
        """Haelt die Sitzung am Leben, ohne das ganze Objekt zu schreiben."""
        self.last_activity_at = timezone.now()
        LearningSession.objects.filter(pk=self.pk).update(last_activity_at=self.last_activity_at)

    def beenden(self):
        """Beendet die Sitzung und loescht alles, was darin entstanden ist.

        Die Zaehler bleiben nicht erhalten: 'Sitzung beenden loescht alles'
        ist eine Zusage an die Kinder, keine Aufraeumfunktion.

        In der Musikstunde liegen die Lieder auch am Spark. Die werden
        zuerst dort geloescht, dann hier; scheitert es am Spark, wird hier
        trotzdem geloescht und der Fehlschlag laut protokolliert
        (musikstunde.am_dienst_loeschen).
        """
        self.lieder_am_dienst_loeschen()
        self.participations.all().delete()
        self.closed_at = timezone.now()
        self.save(update_fields=["closed_at"])

    def lieder_am_dienst_loeschen(self):
        """Die Lieder dieser Sitzung am Musikdienst loeschen, falls es welche gibt.

        Nur wenn bei uns ein Lied steht: Eine Zeile entsteht erst, wenn der
        Dienst den Auftrag angenommen hat, ohne Zeile ist am Spark also nichts.
        So kostet das Beenden von zwanzig leeren Probestunden keinen einzigen
        Aufruf an einen Dienst, der vielleicht gerade schweigt.
        """
        if not self.ist_musik:
            return None
        if not Lied.objects.filter(participation__learning_session=self).exists():
            return None
        return musikstunde.am_dienst_loeschen(self)

    # --- Zaehler fuer die Lehrperson, ohne jeden Inhalt --------------------
    @property
    def zaehler(self):
        teilnahmen = self.participations.all()
        aufgaben = Task.objects.filter(participation__learning_session=self)
        erreicht = teilnahmen.aggregate(models.Max("max_level_reached"))["max_level_reached__max"]
        return {
            "beigetreten": teilnahmen.count(),
            "aufgaben": aufgaben.count(),
            "hoechste_stufe": erreicht or 0,
            "hilfen": Hint.objects.filter(task__participation__learning_session=self).count(),
            # Die Noten der Kinder fuer die Hilfe (1.11.2026), als Mittel.
            **_noten_zaehler(aufgaben),
        }


def _noten_zaehler(aufgaben):
    """{"noten": Anzahl, "note_mittel": "2,1" oder ""} ueber die benoteten Aufgaben."""
    werte = list(aufgaben.filter(rating__isnull=False).values_list("rating", flat=True))
    if not werte:
        return {"noten": 0, "note_mittel": ""}
    return {"noten": len(werte),
            "note_mittel": f"{sum(werte) / len(werte):.1f}".replace(".", ",")}


def verfallene_aufraeumen():
    """Loescht alles, was seit mehr als vier Stunden ohne Aktivitaet ist.

    Wird von den oeffentlichen Einstiegsseiten aufgerufen, nicht nur von der
    Seite der Lehrperson: sonst liegen die Aufgaben der Kinder so lange in der
    Datenbank, bis sich das naechste Mal jemand anmeldet. Bewusst in den
    gewoehnlichen Ansichten und nicht in einer Middleware, weil eine
    synchrone Middleware vor der Streamingansicht das Streaming ausbremst.
    """
    verfallene = LearningSession.objects.verfallene()
    # Die Musikstunden zuerst am Spark leeren. Ein delete() auf der Abfrage
    # ruft keine Methode der einzelnen Sitzung auf; ohne diese Schleife
    # blieben die Lieder einer verfallenen Stunde acht Stunden am Spark.
    for sitzung in verfallene.filter(mode=LearningSession.BETRIEB_MUSIK):
        sitzung.lieder_am_dienst_loeschen()
    anzahl, _ = verfallene.delete()
    return anzahl


class Participation(models.Model):
    """Ein Browser in einer Sitzung. Bewusst keine Person.

    Der Merker ist ein Zufallswert im Cookie der Django-Sitzung. Er dient
    allein dazu, denselben Browser wiederzuerkennen, wenn die Seite neu
    geladen wird. Er ist kein Konto, kein Name und keine Kennung eines Kindes.

    Das Tier ist die sichtbare Unterscheidung innerhalb einer Sitzung. Es
    steht fuer kein Kind, sondern fuer einen Platz in dieser einen Stunde,
    und ist mit dem Ende der Sitzung weg. Wer im Raum sitzt, kann es
    natuerlich zuordnen; genau dafuer ist es da.
    """

    learning_session = models.ForeignKey(
        LearningSession, on_delete=models.CASCADE, related_name="participations"
    )
    token = models.CharField(max_length=43, unique=True, db_index=True)
    # Der Schluessel oben ist ein Ausweis: Wer ihn hat, ist in der Sitzung.
    # Er darf nie in ein Protokoll geraten, das exportiert wird. Deshalb
    # dieser zweite, rein pseudonyme Schluessel fuer die Forschung.
    log_key = models.CharField(max_length=43, unique=True, db_index=True, blank=True)
    animal = models.CharField("Tier", max_length=20, blank=True)
    # Nur fuer Protokollstufe 3. Wer ablehnt, nimmt trotzdem teil und wird
    # nach Stufe 1 protokolliert. Eine Zustimmung, deren Ablehnung den
    # Zugang kostet, ist keine Zustimmung.
    consent_given = models.BooleanField("Zustimmung zur Forschung", default=False)
    consent_asked = models.BooleanField("Zustimmung abgefragt", default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    max_level_reached = models.PositiveSmallIntegerField(default=0)
    # Die schlimmste Einstufung, die in dieser Teilnahme vorgekommen ist.
    # Mitgefuehrt, damit die Klassenliste der Lehrperson ohne Nachrechnen
    # ueber alle Beitraege auskommt.
    worst_flag = models.CharField(
        "Auffaelligkeit", max_length=12, default=pruefung.GRUEN
    )

    class Meta:
        verbose_name = "Teilnahme"
        verbose_name_plural = "Teilnahmen"
        ordering = ["joined_at"]
        constraints = [
            # Ein Tier ist innerhalb einer Sitzung nur einmal zu haben. Die
            # Bedingung laesst noch nicht gewaehlte Teilnahmen aussen vor,
            # sonst koennte immer nur eine ohne Tier bestehen.
            models.UniqueConstraint(
                fields=["learning_session", "animal"],
                condition=~models.Q(animal=""),
                name="tier_je_sitzung_nur_einmal",
            )
        ]

    def __str__(self):
        return f"{self.tier_name} in {self.learning_session.code}"

    def save(self, *args, **kwargs):
        if not self.log_key:
            self.log_key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @staticmethod
    def token_erzeugen():
        return secrets.token_urlsafe(32)

    @property
    def protokollstufe(self):
        """Die Stufe, die fuer diese Teilnahme tatsaechlich gilt.

        Stufe 3 gilt nur mit Zustimmung. Ohne sie faellt die Teilnahme auf
        Stufe 1 zurueck, nicht auf Stufe 2: Wer dem Vollprotokoll nicht
        zustimmt, hat auch dem maskierten nicht zugestimmt.
        """
        sitzung = self.learning_session
        # Herabgestuft wird nur, wo tatsaechlich gefragt wurde, also bei
        # Erwachsenen. Bei Kindern entscheiden Schule und
        # Erziehungsberechtigte ausserhalb der Anwendung; die Einstellung der
        # Lehrperson gilt dann unveraendert.
        if sitzung.zustimmung_noetig and not self.consent_given:
            return BETRIEB
        return sitzung.research_level

    @property
    def tier_bild(self):
        """Pfad der Grafik, relativ zum statischen Verzeichnis."""
        return tiere.bild(self.animal)

    @property
    def tier_name(self):
        return tiere.name(self.animal)

    @property
    def hat_tier(self):
        """Ob ueberhaupt ein Bild ausgeliefert werden kann.

        Nicht bool(self.animal): Entscheidend ist, ob der Wert zu einem
        BEKANNTEN Tier gehoert. Steht dort etwas anderes - der Anzeigename
        statt des Schluessels, ein spaeter umbenanntes Tier, ein Eingriff in
        der Datenbank - dann gibt tiere.bild() einen leeren Pfad zurueck,
        {% static "" %} wirft ValueError und nimmt die ganze Seite mit.

        Genau so entstand der HTTP 500 auf Sitzung 777859, damals durch ein
        fehlendes Tier. Die Vorlage fing danach den leeren Wert ab, den
        unbekannten aber nicht - und bei der Pruefung nach dem Umzug hat
        "Biber" statt "biber" denselben 500 wieder ausgeloest.
        """
        return tiere.ist_bekannt(self.animal)

    @property
    def ampel_beschreibung(self):
        return pruefung.BESCHREIBUNG.get(self.worst_flag, "unbekannt")

    def einstufung_merken(self, stufe):
        """Haelt die schlimmste Einstufung dieser Teilnahme fest."""
        schlimmer = pruefung.schlimmeres(self.worst_flag, stufe)
        if schlimmer != self.worst_flag:
            self.worst_flag = schlimmer
            Participation.objects.filter(pk=self.pk).update(worst_flag=schlimmer)


class Task(models.Model):
    """Eine Aufgabe, die ein Kind eingegeben hat.

    Der Text liegt in der Datenbank und nicht im Arbeitsspeicher, weil ein
    Ausfall des Sprachmodells oder ein Neustart der Anwendung die laufende
    Sitzung der Kinder nicht loeschen darf. Geloescht wird beim Beenden der
    Sitzung und beim Verfall.
    """

    participation = models.ForeignKey(
        Participation, on_delete=models.CASCADE, related_name="tasks"
    )
    text = models.TextField("Aufgabentext", blank=True)
    # Das Foto liegt als Data-URL in der Datenbank und nicht als Datei auf
    # der Platte. Damit stirbt es zwangslaeufig mit der Sitzung, ohne dass
    # sich jemand ans Aufraeumen erinnern muss. Abschnitt 3b verlangt genau
    # das: Bilder ueberleben die Sitzung ausnahmslos nicht.
    image_data_url = models.TextField("Foto", blank=True)
    source = models.CharField(
        "Herkunft", max_length=10, choices=HERKUNFT, default=GETIPPT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    current_level = models.PositiveSmallIntegerField("Erreichte Stufe", default=0)
    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)
    # Wie oft schon dieselbe Stufe wiederholt wurde. Nach zwei Versuchen geht
    # es weiter, auch wenn das Ziel nicht erreicht ist: Wer dreimal dieselbe
    # Stufe bekommt, ist nicht besser dran als wer zu schnell weitergereicht
    # wird.
    repeats = models.PositiveSmallIntegerField("Wiederholungen", default=0)
    # Wann das Kind gesagt hat, dass es fertig ist. Ohne diesen Punkt laeuft
    # eine Aufgabe einfach weiter, bis die Stufen aus sind; wer die Loesung
    # nach Stufe 2 selbst gefunden hat, hat dann keine Moeglichkeit, das zu
    # sagen, und die naechste Aufgabe schiebt die alte kommentarlos weg.
    finished_at = models.DateTimeField("Abgeschlossen", null=True, blank=True)
    # Aus dem Aufgabenpool der Lehrperson (1.11.2026): Welche Aufgabe des
    # Pools das Kind hier bearbeitet; leer bei einer eigenen Aufgabe. Wird
    # die Poolaufgabe entfernt, bleibt die Bearbeitung mit ihrem Text.
    vorlage = models.ForeignKey(
        "SessionTask", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="bearbeitungen", verbose_name="Aufgabe der Lehrperson",
    )
    # Die Note des Kindes fuer die Hilfe (Thomas, 1.11.2026: "bei jeder Runde
    # an der Aufgabe am Schluss die Moeglichkeit, die Schueler zu fragen, ob
    # es geholfen hat, wie gut, Note 1 bis 5"). Freiwillig, wie in der
    # Schule: 1 sehr gut, 5 nicht genuegend. None heisst keine Note.
    rating = models.PositiveSmallIntegerField("Note des Kindes", null=True, blank=True)
    rated_at = models.DateTimeField("Benotet am", null=True, blank=True)
    # Die Loesung, die die Qualitaetssicherung geliefert hat. Sie wird dem
    # Kind NIE gezeigt. Sie steht im Systemprompt der Stufenhilfen, damit
    # ein falscher Ansatz sofort auffaellt und nicht erst am Ende.
    #
    # Sie liegt hier und nicht im Arbeitsspeicher, damit sie je Aufgabe nur
    # einmal geholt wird. Mit der Sitzung wird sie geloescht wie alles
    # andere auch.
    checked_solution = models.TextField("Geprüfte Lösung", blank=True)
    checked_at = models.DateTimeField("Geprüft am", null=True, blank=True)
    # Was dabei wirklich ausgetauscht wurde. Es steht hier und nicht nur im
    # Forschungsprotokoll, weil dieses absichtlich keine Bruecke zur Person
    # hat: Fuer die Auswertung eines einzelnen Lernwegs war der Austausch
    # damit unsichtbar. Hier stirbt er mit der Sitzung wie alles andere.
    checked_model = models.CharField("Modell", max_length=80, blank=True)
    checked_rewritten = models.TextField("Neu formuliert", blank=True)
    checked_sent = models.TextField("Hinausgegangen, maskiert", blank=True)
    checked_received = models.TextField("Zurückgekommen, maskiert", blank=True)
    checked_entities = models.JSONField("Ersetzte Angaben", default=dict, blank=True)
    checked_tokens_in = models.PositiveIntegerField(default=0)
    checked_tokens_out = models.PositiveIntegerField(default=0)
    checked_ms = models.PositiveIntegerField("Dauer in Millisekunden", default=0)
    checked_cost_micro = models.PositiveIntegerField("Kosten in Mikro-Euro", default=0)
    # Leer heisst: gelaufen. Sonst steht hier, warum nicht.
    checked_blocked = models.CharField("Nicht gelaufen, weil", max_length=120, blank=True)
    # Der Bildweg (bildkette.py), falls die Lehrperson ihn freigegeben hat
    # und ein Foto da war. Der Ausschnitt liegt wie das Foto als Data-URL in
    # der Datenbank und stirbt mit der Sitzung; er ist da, damit die
    # Lehrperson im Verlauf nebeneinander sieht, was das Kind fotografiert
    # hat und was davon hinausging. Leer bei checked_image_check heisst:
    # kein Bildweg (Schalter aus oder kein Foto).
    checked_image_check = models.CharField("Bildprüfung", max_length=12, blank=True)
    checked_image_reason = models.CharField("Bildprüfung, Grund", max_length=120, blank=True)
    checked_image_sent = models.TextField("Hinausgegangener Ausschnitt", blank=True)
    checked_image_masks = models.JSONField("Maskierungen je Typ", default=dict, blank=True)
    checked_image_ms = models.PositiveIntegerField(
        "Bildprüfung, Dauer in Millisekunden", default=0
    )

    class Meta:
        verbose_name = "Aufgabe"
        verbose_name_plural = "Aufgaben"
        ordering = ["created_at"]

    def __str__(self):
        return f"Aufgabe {self.pk}"

    @property
    def obergrenze(self):
        return self.participation.learning_session.max_level

    def naechste_stufe(self):
        return levels.naechste_stufe(self.current_level, self.obergrenze)

    @property
    def loesung_steht_an(self):
        """Waere die naechste Stufe die Loesung, und wird vorher gefragt?"""
        if self.naechste_stufe() != levels.LOESUNG:
            return False
        return self.participation.learning_session.ask_before_solution

    @property
    def stufen_ausgeschoepft(self):
        """Alle freigegebenen Stufen sind vergeben, ab hier nur noch Rueckfragen.

        Gefragt wird ueber naechster_schritt und nicht ueber naechste_stufe:
        Eine offene Wiederholung ist eine Stufe, die noch kommt. Sonst
        verschwindet der Knopf beim Neuladen, obwohl die Anwendung sehr wohl
        noch einmal dieselbe Stufe geben wuerde.
        """
        return self.naechster_schritt()[0] is None

    @property
    def ist_abgeschlossen(self):
        return self.finished_at is not None

    @property
    def hat_qualitaetssicherung(self):
        """Gab es einen Austausch nach draussen, gelungen oder nicht?"""
        return bool(self.checked_at or self.checked_blocked)

    @property
    def checked_kosten_euro(self):
        return self.checked_cost_micro / 1_000_000

    @property
    def hat_bildpruefung(self):
        """Ist die Bildkette fuer diese Aufgabe gelaufen, gleich wie sie ausging?"""
        return bool(self.checked_image_check)

    @property
    def bild_bestanden(self):
        from . import bildkette

        return self.checked_image_check == bildkette.BESTANDEN

    @property
    def bild_masken_text(self):
        from . import bildkette

        return bildkette.masken_text(self.checked_image_masks)

    @property
    def checked_ersetzt(self):
        """Ersetzte Angaben als lesbare Aufzaehlung, ohne die Werte selbst."""
        from . import shield

        teile = [
            f"{anzahl}\u00d7 {shield.BEZEICHNUNG.get(typ, typ)}"
            for typ, anzahl in sorted((self.checked_entities or {}).items())
        ]
        return ", ".join(teile)

    @property
    def eigenanteil(self):
        """Die grobe Einschaetzung, was das Kind selbst geschafft hat (klassenbild)."""
        from . import klassenbild

        return klassenbild.eigenanteil(self.hints.all())

    @property
    def geprueftes_wissen_text(self):
        """Der Abschnitt, mit dem der Spark die gepruefte Loesung bekommen hat.

        Thomas (1.11.2026): Die Kommunikation zwischen Frontier-Modell und
        Spark soll sichtbar sein. Hinaus und zurueck zeigen die Felder
        checked_*; das hier ist der dritte Schritt, der Wortlaut im
        Systemprompt jeder Stufenhilfe (levels.geprueftes_wissen).
        """
        if not self.checked_solution:
            return ""
        return levels.geprueftes_wissen(
            self.checked_solution, self.participation.learning_session.age_group
        ).strip()

    def abschliessen(self):
        if self.finished_at is None:
            self.finished_at = timezone.now()
            self.save(update_fields=["finished_at"])

    NOTEN = (1, 2, 3, 4, 5)

    def benoten(self, note):
        """Die Note des Kindes, 1 bis 5; alles andere wird nicht gespeichert."""
        try:
            note = int(note)
        except (TypeError, ValueError):
            return False
        if note not in self.NOTEN:
            return False
        self.rating = note
        self.rated_at = timezone.now()
        self.save(update_fields=["rating", "rated_at"])
        return True

    @property
    def letzte_hilfe(self):
        # Mit dem Schluessel als zweitem Kriterium: Zwei Hilfen aus derselben
        # Mikrosekunde (Tests, Importe) sind sonst in zufaelliger Reihenfolge,
        # und "die letzte" war im Test die erste.
        return self.hints.order_by("created_at", "pk").last()

    @property
    def offene_hilfe(self):
        """Die letzte Hilfe, wenn sie noch auf eine Antwort wartet."""
        letzte = self.letzte_hilfe
        if letzte is not None and letzte.wartet_auf_antwort:
            return letzte
        return None

    @property
    def letzte_stufenhilfe(self):
        """Die letzte Hilfe, die eine Stufe war (keine Nachfrage, kein Auftakt)."""
        return (self.hints.filter(art=levels.ART_HILFE)
                .order_by("created_at", "pk").last())

    @property
    def stand(self):
        """Die Stufe, auf der das Kind steht: die der letzten Stufenhilfe.

        current_level wird beim Holen einer Hilfe gesetzt und stimmt dann
        mit ihr ueberein; liegt er hoeher (Daten von vor der Umstellung),
        gilt er. 0, solange es keine Hilfe gab.
        """
        letzte = self.letzte_stufenhilfe
        return max(self.current_level, letzte.level if letzte else 0)

    def naechster_zug(self):
        """Welcher Zug des Tutors kommt als Naechstes?

        Gibt einen ``Zug`` zurueck (Art, Stufe, Wiederholung) oder None, wenn
        nichts mehr kommt: alle freigegebenen Stufen vergeben, oder die
        Aufgabe ist fertig und bestaetigt.

        HILFE NACH DIAGNOSE STATT NACH LEITER (30.10.2026, Thomas: "Wenn das
        KI-System so schlau ist, muss es jeweils diagnostizieren: wo der
        Schueler steht, was er will, was er braucht."). Die letzte Antwort
        des Kindes traegt, was die Diagnose daraus geschlossen hat
        (next_level): 0 heisst erst nachfragen, 1 bis 4 die gewaehlte Hilfe,
        tiefer oder hoeher als zuletzt, wie die Lage es verlangt. Die Regeln
        darueber stehen in levels.hilfe_waehlen; hier bleiben die, die den
        Zaehler der Aufgabe brauchen: dieselbe Stufe hoechstens
        HOECHSTE_WIEDERHOLUNGEN Mal, dann eine staerker (bis zur Obergrenze,
        die immer gilt), und nach dem Ende die Bestaetigung mit Warum-Frage.
        """
        letzte = self.letzte_hilfe
        if self.ist_abgeschlossen:
            # Nach einem richtigen Ergebnis einmal die Bestaetigung mit der
            # Warum-Frage, nach der Antwort darauf einmal der Nachsatz.
            if letzte is None:
                return None
            if letzte.art == levels.ART_BESTAETIGUNG:
                return Zug(levels.ART_NACHSATZ) if letzte.response else None
            if letzte.art == levels.ART_NACHSATZ:
                return None
            if letzte.result == Hint.ERGEBNIS_RICHTIG:
                return Zug(levels.ART_BESTAETIGUNG)
            return None
        schulstufe = self.participation.learning_session.schulstufe
        if letzte is None:
            # Der erste Zug, ohne Versuch des Kindes: die Frage nach der
            # Schwierigkeit (levels.erste_hilfe; Thomas, 1.11.2026), ausser
            # die Stufen sind schon ausgeschoepft (Aufgabe ohne Zuege am
            # Limit): dann gibt es keinen Zug mehr.
            erste = levels.naechste_stufe(self.current_level, self.obergrenze)
            if erste is None:
                return None
            if levels.erste_hilfe(schulstufe) == levels.ERST_FRAGEN:
                return Zug(levels.ART_NACHFRAGE, 0)
            return Zug(levels.ART_HILFE, erste)

        stand = self.stand
        gewuenscht = letzte.next_level
        if gewuenscht is None:
            # Antworten von vor der Umstellung auf die Diagnose: die alte Regel.
            gewuenscht = stand + 1 if letzte.goal_reached else stand
        if gewuenscht == levels.ERST_FRAGEN:
            return Zug(levels.ART_NACHFRAGE, stand)
        if gewuenscht == stand and stand > 0:
            if self.repeats < levels.HOECHSTE_WIEDERHOLUNGEN:
                return Zug(levels.ART_HILFE, stand, True)
            # Genug wiederholt: eine staerker, auch wenn das Ziel nicht
            # erreicht ist. Ein Kind, das dreimal dieselbe Stufe bekommt,
            # ist nicht besser dran.
            naechste = levels.naechste_stufe(stand, self.obergrenze)
            return Zug(levels.ART_HILFE, naechste) if naechste else None
        if gewuenscht >= levels.LOESUNG or gewuenscht > self.obergrenze:
            # Die Loesung kommt nie aus der Diagnose, und ueber die
            # Obergrenze der Lehrperson geht es nie: Beides heisst "eine
            # weiter", und das laeuft, wenn die Loesung dran ist, ueber die
            # Abfrage davor; ist nichts mehr frei, ist der Weg zu Ende.
            naechste = levels.naechste_stufe(stand, self.obergrenze)
            return Zug(levels.ART_HILFE, naechste) if naechste else None
        # Gewaehlt, nicht gezaehlt: tiefer oder hoeher, wie die Diagnose sagt.
        # Die Obergrenze der Lehrperson gilt auch hier.
        stufe = max(levels.MOTIVATION, min(gewuenscht, self.obergrenze))
        return Zug(levels.ART_HILFE, stufe)

    def naechster_schritt(self):
        """Welche Stufe kommt, und ist es eine Wiederholung?

        Gibt (stufe, wiederholung) zurueck; (ERST_FRAGEN, False) vor einer
        Nachfrage des Tutors, (None, False) wenn keine Stufe mehr kommt.
        Die Entscheidung faellt in naechster_zug; dieser Wrapper bleibt fuer
        Aufrufer, die nur die Stufe brauchen.
        """
        zug = self.naechster_zug()
        if zug is None:
            return None, False
        if zug.art == levels.ART_HILFE:
            return zug.stufe, zug.wiederholung
        if zug.art == levels.ART_NACHFRAGE:
            return levels.ERST_FRAGEN, False
        return None, False


@dataclasses.dataclass(frozen=True)
class Zug:
    """Der naechste Zug des Tutors: Art, Stufe (nur bei einer Hilfe), Wiederholung."""

    art: str
    stufe: int | None = None
    wiederholung: bool = False

    @property
    def ist_hilfe(self):
        return self.art == levels.ART_HILFE


class Hint(models.Model):
    """Eine ausgegebene Hilfe einer bestimmten Stufe.

    Die Antwort des Kindes haengt an der Hilfe, auf die sie folgt. Erst wenn
    sie da ist, gibt es die naechste Stufe: Bei Zech arbeitet das Kind
    zwischen den Stufen, sonst wird aus den gestuften Hilfen eine Folge von
    Ansagen, die man wegklickt.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="hints")
    level = models.PositiveSmallIntegerField("Stufe")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Seit 30.10.2026 ist nicht jeder Zug des Tutors eine Stufe: eine
    # Nachfrage vor der Hilfe, der Auftakt (ein erster Versuch des Kindes
    # ohne Hilfe davor, der Text bleibt leer), die Bestaetigung mit der
    # Warum-Frage, der Nachsatz darauf. Die Stufe ist dann 0 oder die, auf
    # der das Kind gerade steht; die Stufenpunkte zaehlen nur ART_HILFE.
    ARTEN = tuple((art, levels.ART_BEZEICHNUNGEN.get(art, "Hilfe")) for art in levels.ARTEN)
    art = models.CharField("Art des Zuges", max_length=12, choices=ARTEN,
                           default=levels.ART_HILFE)
    # Wie diese Hilfe gegeben wurde (Zech, S. 316-318 und S. 288): direkt
    # oder indirekt, weit oder eng. Aus der Diagnose des Beitrags davor.
    form = models.CharField("Form", max_length=10, blank=True)
    weite = models.CharField("Weite", max_length=6, blank=True)
    response = models.TextField("Antwort des Kindes", blank=True)
    response_image_data_url = models.TextField("Foto zur Antwort", blank=True)
    response_source = models.CharField(
        "Herkunft der Antwort", max_length=10, choices=HERKUNFT, default=GETIPPT
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    response_flag = models.CharField(
        "Einstufung der Antwort", max_length=12, default=pruefung.GRUEN
    )
    response_flag_reason = models.CharField("Begründung", max_length=120, blank=True)
    # Hat der Beitrag das Ziel dieser Stufe erreicht? Ist er das nicht, kommt
    # dieselbe Stufe noch einmal mit einem anderen Zugang, statt vorzuruecken.
    goal_reached = models.BooleanField("Ziel der Stufe erreicht", default=True)
    goal_note = models.CharField("Begründung dazu", max_length=120, blank=True)
    # Die Diagnose: welche Stufe das Kind als NAECHSTES braucht, aus dem
    # ganzen Gespraech geschlossen - hoeher, dieselbe oder tiefer. None bei
    # Hilfen von vor der Umstellung; dann gilt goal_reached allein.
    next_level = models.PositiveSmallIntegerField(
        "Nächste Stufe laut Diagnose", null=True, blank=True
    )
    # Was die Diagnose ueber den Beitrag sagt (Benchmark 19.10.2026,
    # Aenderung 3): Hat das Kind das Endergebnis richtig genannt, ist etwas
    # falsch, oder weder noch? Bei "falsch" steht der Fehler im Klartext
    # ("Zaehler und Nenner getrennt addiert") - fuer die Rueckmeldung an das
    # Kind und fuer die Diagnosezeile der Lehrperson. Leer bei Hilfen von vor
    # der Umstellung.
    ERGEBNIS_RICHTIG = "richtig"
    ERGEBNIS_FALSCH = "falsch"
    ERGEBNIS_OFFEN = "offen"
    ERGEBNISSE = (
        (ERGEBNIS_RICHTIG, "richtig"),
        (ERGEBNIS_FALSCH, "falsch"),
        (ERGEBNIS_OFFEN, "offen"),
    )
    result = models.CharField(
        "Ergebnis laut Diagnose", max_length=8, choices=ERGEBNISSE, blank=True
    )
    error = models.CharField("Fehler im Klartext", max_length=120, blank=True)
    # Die Einschaetzung des Beitrags (30.10.2026, Hilfe nach Diagnose): wo
    # das Kind steht, was es will, und in welcher Form die naechste Hilfe
    # kommen soll. Kategorien aus levels.LAGEN, ABSICHTEN, FORMEN; leer bei
    # Beitraegen von vor der Umstellung.
    lage = models.CharField("Lage laut Diagnose", max_length=16, blank=True)
    absicht = models.CharField("Absicht laut Diagnose", max_length=16, blank=True)
    next_form = models.CharField("Form der nächsten Hilfe", max_length=10, blank=True)

    class Meta:
        verbose_name = "Hilfe"
        verbose_name_plural = "Hilfen"
        # Zeitlich, nicht nach Stufe: Seit die Hilfe gewaehlt wird, kann
        # Stufe 1 nach Stufe 3 kommen, und der Verlauf soll das so zeigen.
        ordering = ["created_at", "pk"]

    def __str__(self):
        if self.art != levels.ART_HILFE:
            return f"{self.get_art_display()} zu Aufgabe {self.task_id}"
        return f"Stufe {self.level} zu Aufgabe {self.task_id}"

    @property
    def ist_hilfe(self):
        """Eine Stufe nach Zech, keine Nachfrage, kein Auftakt, keine Bestaetigung."""
        return self.art == levels.ART_HILFE

    @property
    def bezeichnung(self):
        """Die Fachbezeichnung, fuer die Lehrperson."""
        if self.art != levels.ART_HILFE:
            return levels.ART_BEZEICHNUNGEN.get(self.art, "Zug")
        return levels.BEZEICHNUNGEN.get(self.level, "Hilfe")

    @property
    def kindername(self):
        """Wie der Zug fuer das Kind heisst."""
        if self.art != levels.ART_HILFE:
            return levels.ART_NAMEN.get(self.art, "")
        return levels.kindername(self.level)

    @property
    def rueckfrage(self):
        return levels.rueckfrage(self.level) if self.art == levels.ART_HILFE else None

    @property
    def lage_text(self):
        return levels.LAGEN.get(self.lage, "")

    @property
    def absicht_text(self):
        return levels.ABSICHTEN.get(self.absicht, "")

    @property
    def wartet_auf_antwort(self):
        """Blockiert dieser Zug gerade den naechsten?

        Eine Stufe unter der Loesung wartet auf den Versuch, eine Nachfrage
        auf die Antwort. Der Auftakt hat seine Antwort schon, die
        Bestaetigung fragt freiwillig, der Nachsatz fragt nichts.
        """
        if self.response:
            return False
        if self.art == levels.ART_NACHFRAGE:
            return True
        if self.art != levels.ART_HILFE:
            return False
        return levels.braucht_antwort(self.level)


class Interaction(models.Model):
    """Eine einzelne Anfrage an ein Sprachmodell. Die Analyseeinheit.

    Bewusst ohne Fremdschluessel auf die Sitzung: Das Forschungsprotokoll
    ueberlebt die Sitzung, die Bruecke zu den Personen nicht. Gespeichert
    sind nur die pseudonymen Schluessel, und die sterben mit der Sitzung
    ebenso wie die Zuordnung Tier zu Schluessel und die Token-Tabelle.

    Welche Felder befuellt werden, entscheidet die Protokollstufe. Die Regel
    steht hier und nicht bei den Aufrufern: Sonst landet frueher oder spaeter
    Klartext in einer Zeile, die nur Metadaten enthalten darf.
    """

    LOKAL = "lokal"
    CLOUD = "cloud"
    WEGE = ((LOKAL, "lokal am Spark"), (CLOUD, "externe KI"))

    BESTANDEN = "bestanden"
    BLOCKIERT = "blockiert"
    ENTFAELLT = "entfaellt"
    LEAK_PRUEFUNGEN = (
        (BESTANDEN, "Leak-Check bestanden"),
        (BLOCKIERT, "Cloud-Aufruf blockiert"),
        (ENTFAELLT, "kein Leak-Check nötig"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Pseudonyme Schluessel, keine Fremdschluessel. Siehe Klassenbeschreibung.
    session_key = models.CharField(max_length=43, db_index=True)
    participant_key = models.CharField(max_length=43, db_index=True, blank=True)
    # Auf welcher Stufe diese Zeile entstanden ist. Ohne diese Angabe weiss
    # spaeter niemand, ob ein leeres Inhaltsfeld Ablehnung oder Fehler war.
    research_level = models.PositiveSmallIntegerField(default=BETRIEB)

    route = models.CharField("Weg", max_length=8, choices=WEGE, default=LOKAL)
    model_name = models.CharField("Modell", max_length=80, blank=True)
    level_requested = models.PositiveSmallIntegerField(null=True, blank=True)
    level_granted = models.PositiveSmallIntegerField(null=True, blank=True)

    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    # In Millionstel Euro, damit nichts gerundet wird und keine Gleitkommazahl
    # in die Abrechnung geraet.
    cost_micro = models.PositiveIntegerField("Kosten in Mikro-Euro", default=0)

    leak_check = models.CharField(max_length=12, choices=LEAK_PRUEFUNGEN, default=ENTFAELLT)
    entities_replaced = models.JSONField("Ersetzte Entitäten je Typ", default=dict, blank=True)
    # Die Diagnose, die zu dieser Hilfe gefuehrt hat, nur als Kategorien
    # (lage, absicht, hilfe, form, ergebnis): Stufe 1 des Protokolls, keine
    # Inhalte. So laesst sich spaeter auswerten, welche Lage welche Hilfe
    # bekommen hat (Thomas, 30.10.2026).
    diagnosis = models.JSONField("Diagnose, nur Kategorien", default=dict, blank=True)

    # 32 und nicht 16: Der Trainer schreibt hier den Zustand mit hinein,
    # und "trainer:lernschritt" sind neunzehn Zeichen. Das hat im Betrieb
    # eine DataError geworfen - mitten im ersten Durchlauf.
    outcome = models.CharField(max_length=32, default="ok")
    error_kind = models.CharField(max_length=60, blank=True)

    # Ab Stufe 2.
    masked_input = models.TextField(blank=True)
    masked_output = models.TextField(blank=True)
    # Nur Stufe 3.
    raw_input = models.TextField(blank=True)
    raw_output = models.TextField(blank=True)
    # Die Anweisung an die Gegenstelle (Systemprompt) bei jedem Weg nach
    # draussen, auf jeder Protokollstufe: Das ist eigener Text der Anwendung,
    # kein Inhalt des Kindes. Thomas (31.10.2026): Die Kommunikation
    # zwischen lokaler KI und Frontier-Modell muss einsehbar sein und am
    # Server bleiben; die Anweisung ist ihr erster Teil, das Maskierte und
    # die Antwort sind der zweite (masked_input, masked_output).
    instruction = models.TextField("Anweisung an das Modell", blank=True)

    class Meta:
        verbose_name = "Anfrage"
        verbose_name_plural = "Anfragen"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d.%m. %H:%M:%S} {self.route} Stufe {self.level_granted}"

    @classmethod
    def aufzeichnen(cls, *, sitzung, teilnahme=None, stufe_angefordert=None,
                    stufe_gewaehrt=None, weg=LOKAL, modell="", tokens_ein=0,
                    tokens_aus=0, dauer_ms=0, kosten_micro=0, leak_check=ENTFAELLT,
                    entitaeten=None, ergebnis="ok", fehlerart="",
                    text_ein="", text_aus="", maskiert_ein="", maskiert_aus="",
                    diagnose=None, anweisung=""):
        """Schreibt eine Anfragezeile nach den Regeln der Protokollstufe."""
        protokollstufe = teilnahme.protokollstufe if teilnahme else sitzung.research_level

        zeile = cls(
            session_key=sitzung.log_key,
            participant_key=teilnahme.log_key if teilnahme else "",
            research_level=protokollstufe,
            route=weg,
            model_name=modell,
            level_requested=stufe_angefordert,
            level_granted=stufe_gewaehrt,
            tokens_in=tokens_ein,
            tokens_out=tokens_aus,
            duration_ms=dauer_ms,
            cost_micro=kosten_micro,
            leak_check=leak_check,
            entities_replaced=entitaeten or {},
            outcome=ergebnis,
            error_kind=fehlerart,
            diagnosis=diagnose or {},
            instruction=anweisung or "",
        )

        # Ab hier die Stufenregel. Hoehere Stufen schliessen die niedrigeren
        # ein, niedrigere lassen die Felder leer.
        if protokollstufe >= FORSCHUNG_MASKIERT:
            zeile.masked_input = maskiert_ein or text_ein
            zeile.masked_output = maskiert_aus or text_aus
        if protokollstufe >= FORSCHUNG_VOLL:
            zeile.raw_input = text_ein
            zeile.raw_output = text_aus

        zeile.save()
        return zeile

    @property
    def kosten_euro(self):
        return self.cost_micro / 1_000_000

    @property
    def dauer_sekunden(self):
        return self.duration_ms / 1000

    # --- Fuer die Protokollansicht der Lehrperson (31.10.2026) ------------

    @property
    def ist_cloud(self):
        return self.route == self.CLOUD

    @property
    def weg_text(self):
        return dict(self.WEGE).get(self.route, self.route)

    @property
    def leak_text(self):
        return dict(self.LEAK_PRUEFUNGEN).get(self.leak_check, self.leak_check)

    @property
    def entitaeten_text(self):
        """Ersetzte Angaben als lesbare Aufzaehlung, ohne die Werte selbst."""
        from . import shield

        return ", ".join(
            f"{anzahl}× {shield.BEZEICHNUNG.get(typ, typ)}"
            for typ, anzahl in sorted((self.entities_replaced or {}).items())
        )

    @property
    def diagnose_text(self):
        """Die Kategorien der Diagnose in einer Zeile, leer ohne Diagnose."""
        return ", ".join(
            f"{schluessel} {wert}" for schluessel, wert in (self.diagnosis or {}).items()
            if wert not in (None, "")
        )

    @property
    def inhalte_aufgezeichnet(self):
        """Ob diese Zeile ueberhaupt Text tragen darf (Stufe 2 oder 3)."""
        return self.research_level >= FORSCHUNG_MASKIERT


class TrainerLauf(models.Model):
    """Ein Thema, das jemand mit dem Trainer durcharbeitet.

    Der Zustand liegt hier und nicht im Gespraechsverlauf. Ein Modell, das
    seinen eigenen Fortschritt beurteilt, lobt sich durch; die Anwendung
    entscheidet, was als Naechstes kommt.
    """

    participation = models.ForeignKey(
        Participation, on_delete=models.CASCADE, related_name="trainerlaeufe"
    )
    topic = models.CharField("Thema", max_length=300, blank=True)
    state = models.CharField(
        "Zustand", max_length=16, choices=trainer.ZUSTAENDE,
        default=trainer.THEMA,
    )
    # Auf welcher Darstellungsebene zuletzt erklaert wurde, und welche schon
    # versucht wurden. Ohne dieses Gedaechtnis wiederholt der Trainer beim
    # zweiten Anlauf denselben Zugang, und genau das hilft nicht.
    representation = models.CharField(
        "Darstellung", max_length=16, choices=trainer.DARSTELLUNGEN,
        default=trainer.GEGENSTAENDLICH,
    )
    tried = models.JSONField("Versuchte Zugänge", default=list, blank=True)

    step_no = models.PositiveSmallIntegerField("Lernschritt", default=0)
    loops = models.PositiveSmallIntegerField("Schleifen", default=0)
    tasks_given = models.PositiveSmallIntegerField("Aufgaben gestellt", default=0)
    tasks_right = models.PositiveSmallIntegerField("Aufgaben richtig", default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField("Abgeschlossen", null=True, blank=True)

    class Meta:
        verbose_name = "Trainerlauf"
        verbose_name_plural = "Trainerläufe"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.topic or 'ohne Thema'} ({self.get_state_display()})"

    # Deutsche Namen fuer die Vorlage, englische Spalten fuer die Datenbank.
    @property
    def thema(self):
        return self.topic

    @property
    def zustand(self):
        return self.state

    @property
    def darstellung(self):
        return self.representation

    @property
    def versucht(self):
        return self.tried or []

    @property
    def schritt_nr(self):
        return self.step_no

    @property
    def schleifen(self):
        return self.loops

    @property
    def aufgaben_gestellt(self):
        return self.tasks_given

    @property
    def aufgaben_richtig(self):
        return self.tasks_right

    @property
    def ist_fertig(self):
        return self.finished_at is not None

    @property
    def zustand_text(self):
        return trainer.ZUSTAND_TEXT.get(self.state, "")


class TrainerZug(models.Model):
    """Ein einzelner Zug: was der Trainer sagt oder was geantwortet wird.

    Das Urteil steht bei dem Zug, auf den es sich bezieht. Damit wird der
    Lernweg auswertbar: Wo ist jemand haengengeblieben, welcher Zugang hat
    schliesslich geholfen.
    """

    TRAINER = "trainer"
    LERNEND = "lernend"
    ROLLEN = ((TRAINER, "Trainer"), (LERNEND, "lernende Person"))

    run = models.ForeignKey(
        TrainerLauf, on_delete=models.CASCADE, related_name="zuege"
    )
    role = models.CharField("Rolle", max_length=8, choices=ROLLEN)
    text = models.TextField("Text", blank=True)
    question = models.TextField("Die eine Frage", blank=True)
    image_data_url = models.TextField("Foto", blank=True)
    source = models.CharField(
        "Herkunft", max_length=10, choices=HERKUNFT, default=GETIPPT
    )

    state = models.CharField("Zustand", max_length=16, blank=True)
    representation = models.CharField("Darstellung", max_length=16, blank=True)
    verdict = models.CharField(
        "Urteil", max_length=12, choices=trainer.URTEILE, blank=True
    )
    error_kind = models.CharField("Fehlertyp", max_length=60, blank=True)

    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Trainerzug"
        verbose_name_plural = "Trainerzüge"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.text[:40]}"

    @property
    def rolle(self):
        return self.role

    @property
    def frage(self):
        return self.question

    @property
    def urteil(self):
        return self.verdict

    @property
    def urteil_text(self):
        return dict(trainer.URTEILE).get(self.verdict, "")


class SprachLauf(models.Model):
    """Ein Gespraech in der Zielsprache.

    Seit den Gespraechsaufgaben hat es einen Ablauf: Planen, Aufgabe,
    Rollentausch, Wiederholung, Rueckblick (tutoring/sprechablauf.py). Die
    Phase steht HIER und wird nur vom Server gesetzt - das Modell erfaehrt
    sie, es entscheidet sie nicht (Regel 12 des Berichts; ein Systemprompt
    ist eine Bitte).
    """

    participation = models.ForeignKey(
        Participation, on_delete=models.CASCADE, related_name="sprachlaeufe"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField("Beendet", null=True, blank=True)
    # Laeufe von vor den Aufgaben stehen mitten im Gespraech: "aufgabe".
    phase = models.CharField(
        "Phase", max_length=12, choices=sprechablauf.PHASEN,
        default=sprechablauf.AUFGABE,
    )
    phase_seit = models.DateTimeField("Phase seit", default=timezone.now)
    # Ob das Ziel im ersten und im zweiten Durchgang erreicht wurde. None
    # heisst: nicht geprueft (freies Gespraech, oder der Durchgang lief nicht).
    goal_first = models.BooleanField("Ziel im 1. Durchgang", null=True, blank=True)
    goal_second = models.BooleanField("Ziel im 2. Durchgang", null=True, blank=True)
    # Die zwei bis drei Punkte am Ende, einmal gebaut und dann fest, damit
    # Kind und Lehrperson dasselbe sehen (Regel 6, zweiter Teil).
    review = models.JSONField("Rückblick", default=list, blank=True)

    class Meta:
        verbose_name = "Sprechgespräch"
        verbose_name_plural = "Sprechgespräche"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sprache_name} ({self.zuege.count()} Beiträge)"

    # Thema, Sprache und Niveau stehen an der Sitzung: Die Lehrperson stellt
    # sie fuer alle ein, nicht je Person.
    @property
    def thema(self):
        return self.participation.learning_session.task_hint

    @property
    def sprache(self):
        return self.participation.learning_session.target_language

    @property
    def sprache_code(self):
        return self.sprache

    @property
    def sprache_name(self):
        return sprechcoach.sprache_name(self.sprache)

    @property
    def niveau(self):
        return self.participation.learning_session.language_level

    @property
    def niveau_name(self):
        return sprechcoach.niveau_name(self.niveau)

    @property
    def zuege_anzahl(self):
        return self.zuege.count()

    @property
    def aufgabe(self):
        return self.participation.learning_session.sprechaufgabe

    @property
    def schritt(self):
        """1 bis 4: Planen, Gespraech, Noch einmal, Rueckblick."""
        return sprechablauf.SCHRITT_VON.get(self.phase, 2)

    @property
    def ist_planen(self):
        return self.phase == sprechablauf.PLANEN

    @property
    def ist_rueckblick(self):
        return self.phase == sprechablauf.RUECKBLICK

    def phase_setzen(self, neu, **felder):
        """Die eine Stelle, an der die Phase wechselt."""
        self.phase = neu
        self.phase_seit = timezone.now()
        for name, wert in felder.items():
            setattr(self, name, wert)
        self.save(update_fields=["phase", "phase_seit", *felder])

    @property
    def ist_fertig(self):
        return self.finished_at is not None


class SprachZug(models.Model):
    """Ein Beitrag im Gespraech.

    Die Uebersetzung steht beim Zug und nicht in einer eigenen Tabelle: Sie
    gehoert zu genau diesem Satz und stirbt mit ihm.
    """

    COACH = "coach"
    LERNEND = "lernend"
    ROLLEN = ((COACH, "Sprechcoach"), (LERNEND, "lernende Person"))

    run = models.ForeignKey(
        SprachLauf, on_delete=models.CASCADE, related_name="zuege"
    )
    role = models.CharField("Rolle", max_length=8, choices=ROLLEN)
    text = models.TextField("Text in der Zielsprache", blank=True)
    translation = models.TextField("Auf Deutsch", blank=True)
    correction = models.TextField("Beiläufige Korrektur", blank=True)
    source = models.CharField(
        "Herkunft", max_length=10, choices=HERKUNFT, default=GETIPPT
    )
    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)
    # Der Coach TUT, als verstehe er kein Deutsch. Dieser Zug ist die Antwort
    # "Sorry, I don't understand" - kein Fehler, ein Gespraechsbeitrag. Das
    # Feld steht hier, damit die Seite ihn ruhig zeigen und den stillen
    # Ausweg einblenden kann, und damit im Rueckblick zaehlbar ist, wie oft
    # ein Kind an der Sperre haengen blieb.
    not_understood = models.BooleanField("Nicht verstanden", default=False)
    # In welcher Phase der Zug fiel. Daran haengt der Vergleich erster gegen
    # zweiter Durchgang (Regel 14: Wirkung ueber Wiederholungen beurteilen).
    phase = models.CharField(
        "Phase", max_length=12, choices=sprechablauf.PHASEN,
        default=sprechablauf.AUFGABE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Gesprächsbeitrag"
        verbose_name_plural = "Gesprächsbeiträge"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.text[:40]}"

    @property
    def rolle(self):
        return self.role

    @property
    def nicht_verstanden(self):
        return self.not_understood

    @property
    def ist_coach(self):
        return self.role == self.COACH

    @property
    def uebersetzung(self):
        return self.translation

    @property
    def korrektur(self):
        return self.correction


class Question(models.Model):
    """Eine freie Rueckfrage, nachdem die Stufen ausgeschoepft sind.

    Das Gespraech endet nicht mit der letzten freigegebenen Stufe. Ein Kind
    darf weiter fragen, was ein Wort bedeutet oder warum etwas so ist. Die
    Obergrenze der Lehrperson gilt dabei unveraendert weiter, sonst waere die
    Rueckfrage der Schleichweg um genau diese Einstellung.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField("Frage des Kindes")
    image_data_url = models.TextField("Foto", blank=True)
    source = models.CharField(
        "Herkunft", max_length=10, choices=HERKUNFT, default=GETIPPT
    )
    answer = models.TextField("Antwort", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)

    class Meta:
        verbose_name = "Rückfrage"
        verbose_name_plural = "Rückfragen"
        ordering = ["created_at"]

    def __str__(self):
        return f"Rückfrage zu Aufgabe {self.task_id}"


class Lied(models.Model):
    """Ein Lied aus der Musikstunde.

    Hier steht der Liedtext, am Spark Auftrag und MP3. Die Zeile haengt an
    der Teilnahme und stirbt mit ihr; was am Spark liegt, loescht
    LearningSession.lieder_am_dienst_loeschen beim Beenden und beim Verfall.

    Die Ampel steht beim Lied wie bei einer Aufgabe: Was der deterministische
    Boden oder die Sperrliste trifft, kommt gar nicht erst hierher; was das
    Modell auffaellig findet, wird trotzdem vertont und der Lehrperson
    gezeigt. Sie entscheidet, nicht die Anwendung.
    """

    WARTET = "wartet"
    RECHNET = "rechnet"
    FERTIG = "fertig"
    FEHLER = "fehler"
    WEG = "weg"
    ZUSTAENDE = (
        (WARTET, "wartet"),
        (RECHNET, "wird erzeugt"),
        (FERTIG, "fertig"),
        (FEHLER, "nicht gelungen"),
        (WEG, "am Spark nicht mehr da"),
    )

    participation = models.ForeignKey(
        Participation, on_delete=models.CASCADE, related_name="lieder"
    )
    auftrag = models.CharField("Auftrag am Musikdienst", max_length=64, db_index=True)
    stil = models.CharField("Stil", max_length=80)
    text = models.TextField("Liedtext", blank=True)
    sekunden = models.PositiveSmallIntegerField("Dauer in Sekunden")
    sprache = models.CharField("Sprache des Gesangs", max_length=2)
    zustand = models.CharField("Zustand", max_length=12, choices=ZUSTAENDE, default=WARTET)
    angelegt_am = models.DateTimeField(auto_now_add=True)
    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)

    class Meta:
        verbose_name = "Lied"
        verbose_name_plural = "Lieder"
        ordering = ["angelegt_am", "pk"]

    def __str__(self):
        return f"Lied {self.auftrag} ({self.get_zustand_display()})"

    @property
    def laeuft(self):
        return self.zustand in (self.WARTET, self.RECHNET)

    @property
    def ist_fertig(self):
        return self.zustand == self.FERTIG

    @property
    def ampel_beschreibung(self):
        return pruefung.BESCHREIBUNG.get(self.flag, "unbekannt")


class ChatZug(models.Model):
    """Ein Beitrag im Safe Chat: vom Kind oder von der KI.

    Thomas (23.10.2026): ein inhaltlich offener Chat mit der KI am Spark;
    auf Knopfdruck geht eine Frage nach draussen, aber nur durch den Filter
    am Spark (dieselbe Kette wie die Qualitaetssicherung: umformulieren,
    erkennen, maskieren, Leak-Check, senden, lokal zurueckschreiben), und
    das ganze Protokoll ist fuer Kind und Lehrperson sichtbar: was das Kind
    geschrieben hat, was der Spark daraus gemacht hat, was hinausging, was
    zurueckkam, was daraus wurde - und ob die Gegenstelle selbst meint,
    dass kein Personenbezug dabei war.

    Ein Zug je Beitrag. Der Zug des Kindes traegt die Ampel; der Zug der KI
    traegt den Weg (Spark oder draussen) und, wenn es hinausging, das
    Protokoll. Stirbt mit der Teilnahme, wie alles andere.
    """

    LERNEND = "lernend"
    KI = "ki"
    ROLLEN = ((LERNEND, "lernende Person"), (KI, "KI"))

    WEG_SPARK = "spark"
    WEG_AUSSEN = "aussen"
    WEGE = ((WEG_SPARK, "Spark"), (WEG_AUSSEN, "nach draußen"))

    # Das Urteil der Gegenstelle ueber die eigene Anfrage: Hat sie etwas
    # gesehen, das eine Person erkennbar macht? "offen" heisst: nicht
    # gefragt oder keine brauchbare Antwort.
    URTEIL_OHNE = "ohne"
    URTEIL_MIT = "mit"
    URTEIL_OFFEN = "offen"
    URTEILE = (
        (URTEIL_OHNE, "ohne Personenbezug"),
        (URTEIL_MIT, "Personenbezug gesehen"),
        (URTEIL_OFFEN, "kein Urteil"),
    )

    participation = models.ForeignKey(
        Participation, on_delete=models.CASCADE, related_name="chatzuege"
    )
    role = models.CharField("Rolle", max_length=8, choices=ROLLEN)
    # Was das Kind sieht: sein Beitrag, oder die Antwort im Klartext (mit
    # lokal wieder eingesetzten Angaben).
    text = models.TextField("Text", blank=True)
    weg = models.CharField("Weg", max_length=8, choices=WEGE, default=WEG_SPARK)
    created_at = models.DateTimeField(auto_now_add=True)
    # Die Ampel, nur am Zug des Kindes.
    flag = models.CharField("Einstufung", max_length=12, default=pruefung.GRUEN)
    flag_reason = models.CharField("Begründung", max_length=120, blank=True)

    # --- Das Protokoll des Weges nach draussen (nur KI-Zug, weg=aussen) ---
    # Schritt 1: der Spark schreibt den Beitrag ohne Personen neu.
    aussen_umgeschrieben = models.TextField("Vom Spark umformuliert", blank=True)
    # Schritt 2 und 3: erkannt, maskiert, Leak-Check - so ging es hinaus.
    aussen_gesendet = models.TextField("Hinausgegangen, maskiert", blank=True)
    # Schritt 4: so kam es zurueck, noch mit Platzhaltern.
    aussen_empfangen = models.TextField("Zurückgekommen, maskiert", blank=True)
    # Zaehlung der ersetzten Angaben je Art, etwa {"PERS": 2}.
    aussen_entitaeten = models.JSONField("Ersetzte Angaben", default=dict, blank=True)
    aussen_modell = models.CharField("Modell", max_length=80, blank=True)
    aussen_tokens_in = models.PositiveIntegerField(default=0)
    aussen_tokens_out = models.PositiveIntegerField(default=0)
    aussen_ms = models.PositiveIntegerField("Dauer in Millisekunden", default=0)
    aussen_cost_micro = models.PositiveIntegerField("Kosten in Mikro-Euro", default=0)
    # Blieb der Weg zu (Filter, Budget, Netz), steht hier warum; der Text
    # des Zuges ist dann der Hinweis an das Kind.
    aussen_gesperrt = models.CharField("Nicht hinausgegangen, weil", max_length=120, blank=True)
    # Die Antwort des Spark trug die Form einer politischen Verweigerung
    # (fachgrenze.ausweichen_erkannt, 7.11.2026): Das Kind hat den festen
    # Satz gelesen, der Wortlaut des Modells steht nur im Forschungsprotokoll.
    # Hier der Grund in Worten, leer, wenn die Antwort durchging.
    ausweichen = models.CharField("Antwort zurückgehalten, weil", max_length=120, blank=True)
    # Das Urteil der Gegenstelle, mit Begruendung in ihren Worten.
    urteil = models.CharField("Urteil der Gegenstelle", max_length=8, choices=URTEILE, blank=True)
    urteil_grund = models.CharField("Begründung des Urteils", max_length=240, blank=True)

    class Meta:
        verbose_name = "Chatzug"
        verbose_name_plural = "Chatzüge"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()} ({self.get_weg_display()}): {self.text[:40]}"

    @property
    def ist_ki(self):
        return self.role == self.KI

    @property
    def ist_aussen(self):
        return self.weg == self.WEG_AUSSEN

    @property
    def hat_protokoll(self):
        """Gibt es etwas aufzuklappen: hinausgegangen oder gesperrt?"""
        return self.ist_ki and self.ist_aussen and bool(self.aussen_gesendet or self.aussen_gesperrt)

    @property
    def ersetzt(self):
        """Wie viele Angaben der Filter ersetzt hat, ueber alle Arten."""
        return sum(int(n) for n in (self.aussen_entitaeten or {}).values())

    @property
    def ampel_beschreibung(self):
        return pruefung.BESCHREIBUNG.get(self.flag, "unbekannt")

    @property
    def urteil_text(self):
        return dict(self.URTEILE).get(self.urteil, "")


class SessionTask(models.Model):
    """Eine Aufgabe, die die Lehrperson in die laufende Sitzung stellt.

    Thomas (1.11.2026): "Die Lehrperson kann selbst Aufgaben in der Sitzung
    hochladen, und zwar nachdem sie laeuft. Dann im System den Schuelern zur
    Verfuegung gestellt, und die Schueler haben dann auch gleich einen Coach
    zu jeder Uebung. Beim Hochladen kann das System gleich pruefen, ob es die
    Aufgabe selber loesen kann bzw. das Frontier-Modell dazunehmen."

    Der Text (getippt oder vom Foto abgeschrieben), die Loesung des Spark und,
    mit Qualitaetssicherung, die gepruefte Loesung von draussen (dieselben
    Felder wie Task.checked_*, damit ein Kind sie mit der Aufgabe uebernimmt).
    Der Status sagt der Lehrperson auf einen Blick, ob das System die Aufgabe
    kann (tutoring/aufgabenpool.py). Stirbt mit der Sitzung.
    """

    session = models.ForeignKey(
        LearningSession, on_delete=models.CASCADE, related_name="aufgabenpool"
    )
    text = models.TextField("Aufgabentext")
    image_data_url = models.TextField("Foto", blank=True)
    position = models.PositiveSmallIntegerField("Nummer", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    aktiv = models.BooleanField("für die Kinder sichtbar", default=True)

    spark_solution = models.TextField("Lösung des Spark", blank=True)
    spark_error = models.CharField("Spark-Fehler", max_length=120, blank=True)
    spark_ms = models.PositiveIntegerField("Dauer am Spark in Millisekunden", default=0)

    checked_solution = models.TextField("Geprüfte Lösung", blank=True)
    checked_at = models.DateTimeField("Geprüft am", null=True, blank=True)
    checked_model = models.CharField("Modell", max_length=80, blank=True)
    checked_rewritten = models.TextField("Neu formuliert", blank=True)
    checked_sent = models.TextField("Hinausgegangen, maskiert", blank=True)
    checked_received = models.TextField("Zurückgekommen, maskiert", blank=True)
    checked_entities = models.JSONField("Ersetzte Angaben", default=dict, blank=True)
    checked_tokens_in = models.PositiveIntegerField(default=0)
    checked_tokens_out = models.PositiveIntegerField(default=0)
    checked_ms = models.PositiveIntegerField("Dauer in Millisekunden", default=0)
    checked_cost_micro = models.PositiveIntegerField("Kosten in Mikro-Euro", default=0)
    checked_blocked = models.CharField("Nicht gelaufen, weil", max_length=120, blank=True)

    status = models.CharField("Prüfung", max_length=12, default="offen")

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return f"Aufgabe {self.position} in {self.session.code}"

    @property
    def status_titel(self):
        from . import aufgabenpool

        return aufgabenpool.STATUS_TITEL.get(self.status, self.status)

    @property
    def status_text(self):
        from . import aufgabenpool

        return aufgabenpool.status_text(self)

    @property
    def ist_einig(self):
        from . import aufgabenpool

        return self.status == aufgabenpool.STATUS_EINIG

    @property
    def checked_kosten_euro(self):
        return self.checked_cost_micro / 1_000_000
