"""Konten, die ueber die PH angemeldet werden.

Die PH prueft die Anmeldung zentral (login.ph-vorarlberg.at gegen Microsoft
Entra), Caddy reicht die Person als Kopfzeilen durch. Hier steht nur, was wir
davon behalten, und die Verbindung zum Django-Benutzer, an dem Rechte und
Planungsprofil haengen.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class PhKonto(models.Model):
    """Eine Person aus dem Entra der PH, verbunden mit ihrem Django-Benutzer.

    Die Kennung ist die Entra-Objekt-ID und NICHT die E-Mail: Die E-Mail
    aendert sich bei Heirat, Namenswechsel oder Umzug in eine andere
    Abteilung, die Objekt-ID bleibt. Wer die E-Mail als Schluessel nimmt,
    legt bei der ersten Aenderung ein zweites Konto an und verliert das
    Planungsprofil des ersten.
    """

    benutzer = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="phkonto", verbose_name="Benutzer",
    )
    # Entra-Objekt-IDs sind GUIDs mit 36 Zeichen; etwas Luft fuer den Fall,
    # dass die PH das Format einmal aendert.
    oid = models.CharField("Entra-Objekt-ID", max_length=64, unique=True)
    email = models.CharField("E-Mail", max_length=254, blank=True)
    anmeldename = models.CharField("Anmeldename", max_length=150, blank=True)
    name = models.CharField("Name", max_length=200, blank=True)
    # Mit ";" getrennt, so wie Caddy sie liefert. Sobald die PH die Gruppen-IDs
    # fuer Mitarbeitende und Studierende nennt, laesst sich daran die Freigabe
    # automatisieren; bis dahin ist es ein Blick fuer die Verwaltung.
    gruppen = models.TextField("Gruppen", blank=True)
    zuletzt_gesehen = models.DateTimeField("Zuletzt gesehen", default=timezone.now)
    angelegt_am = models.DateTimeField("Angelegt am", auto_now_add=True)

    class Meta:
        verbose_name = "PH-Konto"
        verbose_name_plural = "PH-Konten"
        ordering = ["-zuletzt_gesehen"]

    def __str__(self):
        return self.name or self.email or self.oid

    def gruppen_liste(self):
        return [g for g in (teil.strip() for teil in self.gruppen.split(";")) if g]
