"""Loescht verfallene Sitzungen. Gedacht fuer einen Zeitplan.

Die oeffentlichen Seiten raeumen bei jedem Aufruf mit auf. Ruft aber laengere
Zeit niemand die Anwendung auf, bleiben die Daten liegen. Dieser Befehl
schliesst diese Luecke, sobald jemand ihn regelmaessig laufen laesst.
"""

from django.core.management.base import BaseCommand

from tutoring.models import verfallene_aufraeumen


class Command(BaseCommand):
    help = "Loescht Sitzungen ohne Aktivitaet der letzten vier Stunden."

    def handle(self, *args, **optionen):
        anzahl = verfallene_aufraeumen()
        self.stdout.write(f"{anzahl} Objekte aus verfallenen Sitzungen geloescht.")
