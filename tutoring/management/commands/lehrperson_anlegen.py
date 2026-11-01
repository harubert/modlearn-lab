"""Legt den Zugang der Lehrperson aus der Umgebung an oder aktualisiert ihn.

Laeuft bei jedem Start des Containers. Ohne gesetztes Kennwort passiert
nichts, dann gibt es schlicht keinen Zugang – das ist besser als ein Konto
mit einem vorhersehbaren Kennwort auf einem oeffentlich erreichbaren Server.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Legt den Zugang der Lehrperson aus TEACHER_USERNAME und TEACHER_PASSWORD an."

    def handle(self, *args, **optionen):
        benutzername = settings.TEACHER_USERNAME
        kennwort = settings.TEACHER_PASSWORD

        if not kennwort:
            self.stdout.write(
                "TEACHER_PASSWORD ist nicht gesetzt, es wird kein Zugang angelegt."
            )
            return

        Benutzer = get_user_model()
        benutzer, neu = Benutzer.objects.get_or_create(username=benutzername)
        benutzer.set_password(kennwort)
        benutzer.is_staff = False
        benutzer.is_superuser = False
        benutzer.save()

        zustand = "angelegt" if neu else "aktualisiert"
        self.stdout.write(f"Zugang der Lehrperson '{benutzername}' {zustand}.")
