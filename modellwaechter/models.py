"""Was der Modellwaechter behaelt: jeden Lauf und jeden Fund.

Ein Fund ist ein Modell oder eine Version, die eine Quelle zum ersten Mal
gezeigt hat. Der erste erfolgreiche Lauf einer Quelle legt den Grundbestand
an: Alles, was es da schon gibt, ist nicht neu und wird nicht gemeldet. Sonst
staenden am ersten Tag dreihundert Modelle in der Meldung, und keines davon
waere eine Nachricht.
"""

from django.db import models


class Lauf(models.Model):
    """Eine Abfrage einer Quelle, mit Ausgang und Zahlen."""

    OK = "ok"
    FEHLER = "fehler"

    begonnen = models.DateTimeField(auto_now_add=True)
    quelle = models.CharField(max_length=40)
    anbieter = models.CharField(max_length=80, blank=True)
    ergebnis = models.CharField(max_length=12, default=OK)
    fehlerart = models.CharField("Fehler, nur die Art", max_length=60, blank=True)
    grundbestand = models.BooleanField(default=False)
    gesehen = models.PositiveIntegerField(default=0)
    neu = models.PositiveIntegerField(default=0)
    dauer_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-begonnen", "-pk")
        verbose_name = "Lauf"
        verbose_name_plural = "Läufe"

    def __str__(self):
        return f"{self.quelle} {self.anbieter} {self.begonnen:%d.%m.%Y %H:%M} {self.ergebnis}"

    @property
    def quelle_titel(self):
        from . import quellen

        return quellen.QUELLEN_TITEL.get(self.quelle, self.quelle)


class Fund(models.Model):
    """Ein Modell oder eine Version, zum ersten Mal gesehen."""

    quelle = models.CharField(max_length=40)
    anbieter = models.CharField(max_length=80)
    kennung = models.CharField(max_length=200)
    name = models.CharField(max_length=200, blank=True)
    adresse = models.URLField(max_length=400, blank=True)
    veroeffentlicht = models.DateTimeField("Datum der Quelle", null=True, blank=True)
    zuerst_gesehen = models.DateTimeField(auto_now_add=True)
    lizenz = models.CharField(max_length=80, blank=True)
    aufgabe = models.CharField(max_length=80, blank=True)
    merkmale = models.JSONField(default=dict, blank=True)
    beschreibung = models.TextField(blank=True)
    grundbestand = models.BooleanField(default=False)
    einordnung = models.TextField("Einordnung vom Spark", blank=True)
    einordnung_modell = models.CharField(max_length=80, blank=True)
    einordnung_am = models.DateTimeField(null=True, blank=True)
    gemeldet_am = models.DateTimeField("Per E-Mail gemeldet", null=True, blank=True)
    gelesen = models.BooleanField(default=False)

    class Meta:
        ordering = ("-zuerst_gesehen", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("quelle", "kennung"), name="fund_je_quelle_und_kennung"),
        ]
        verbose_name = "Fund"
        verbose_name_plural = "Funde"

    def __str__(self):
        return f"{self.quelle}: {self.kennung}"

    @property
    def quelle_titel(self):
        from . import quellen

        return quellen.QUELLEN_TITEL.get(self.quelle, self.quelle)

    @property
    def datum(self):
        """Das Datum der Quelle, sonst der Tag, an dem wir es gesehen haben."""
        return self.veroeffentlicht or self.zuerst_gesehen
