"""Legt einen Planungszugang an oder ordnet ihn einer anderen Klasse zu.

Warum ein Befehl und nicht nur das Formular unter /verwaltung/: Den ersten
Zugang mit Verwaltungsrechten kann man dort nicht anlegen, weil man dafuer
schon einen braeuchte. Danach ist der Befehl der kuerzere Weg fuer eine
Handvoll Zugaenge auf einmal.

    python manage.py plan_zugang thomas --klasse Lab --verwaltung
    python manage.py plan_zugang ak --klasse Studierende --kennwort '...'
    python manage.py plan_zugang --liste

Ein Zugang OHNE Profil darf trotzdem buchen: Die Ansicht legt dann die
zurueckhaltendste Klasse an. Lieber wenig erlaubt als eine Seite, die mit
einer Ausnahme antwortet.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from plan.models import Nutzerklasse, Profil


class Command(BaseCommand):
    help = "Legt einen Planungszugang an oder aendert seine Nutzerklasse."

    def add_arguments(self, parser):
        parser.add_argument("benutzername", nargs="?", default="")
        parser.add_argument("--klasse", default="", help="Name der Nutzerklasse")
        parser.add_argument("--kennwort", default="", help="Neues Kennwort")
        parser.add_argument("--einrichtung", default="", help="Schule oder Institut")
        parser.add_argument(
            "--verwaltung", action="store_true",
            help="Darf unter /verwaltung/ Zugaenge anlegen",
        )
        parser.add_argument(
            "--sperren", action="store_true", help="Keine neuen Buchungen mehr",
        )
        parser.add_argument(
            "--entsperren", action="store_true", help="Sperre aufheben",
        )
        parser.add_argument(
            "--liste", action="store_true", help="Nur zeigen, nichts aendern",
        )

    def handle(self, *args, **o):
        if o["liste"] or not o["benutzername"]:
            return self._liste()

        Benutzer = get_user_model()
        name = o["benutzername"]

        if o["verwaltung"] and name == settings.TEACHER_USERNAME:
            # lehrperson_anlegen setzt is_superuser bei JEDEM Containerstart
            # auf False. Verwaltungsrechte an diesem Konto waeren beim
            # naechsten Neustart wieder weg, ohne dass jemand merkt, warum.
            raise CommandError(
                f"'{name}' wird aus der Umgebung verwaltet und bei jedem Start "
                f"zurueckgesetzt. Verwaltungsrechte gehoeren auf ein eigenes Konto."
            )

        benutzer, neu = Benutzer.objects.get_or_create(username=name)
        if neu and not o["kennwort"]:
            raise CommandError(
                f"'{name}' gibt es noch nicht. Fuer einen neuen Zugang braucht "
                f"es --kennwort."
            )
        if o["kennwort"]:
            benutzer.set_password(o["kennwort"])
        if o["verwaltung"]:
            benutzer.is_staff = True
            benutzer.is_superuser = True
        benutzer.save()

        profil = Profil.objects.filter(benutzer=benutzer).first()
        if o["klasse"]:
            klasse = Nutzerklasse.objects.filter(name__iexact=o["klasse"]).first()
            if klasse is None:
                vorhanden = ", ".join(
                    Nutzerklasse.objects.values_list("name", flat=True)
                )
                raise CommandError(
                    f"Die Klasse '{o['klasse']}' gibt es nicht. Vorhanden: {vorhanden}."
                )
        elif profil is not None:
            klasse = profil.klasse
        else:
            klasse = Nutzerklasse.objects.order_by("max_plaetze").first()
            if klasse is None:
                raise CommandError("Es ist keine Nutzerklasse angelegt.")

        if profil is None:
            profil = Profil(benutzer=benutzer)
        profil.klasse = klasse
        if o["einrichtung"]:
            profil.einrichtung = o["einrichtung"]
        if o["sperren"]:
            from django.utils import timezone
            profil.gesperrt_am = timezone.now()
        if o["entsperren"]:
            profil.gesperrt_am = None
        profil.save()

        self.stdout.write(
            f"{'Angelegt' if neu else 'Aktualisiert'}: {name} "
            f"als {klasse.name} "
            f"({klasse.max_plaetze} Plätze, {klasse.max_minuten} Minuten, "
            f"{klasse.max_slots_woche} Buchungen je Woche)"
            + (", Verwaltung" if benutzer.is_superuser else "")
            + (", gesperrt" if not profil.darf_buchen else "")
        )

    def _liste(self):
        self.stdout.write("Nutzerklassen:")
        for k in Nutzerklasse.objects.all():
            self.stdout.write(
                f"  {k.name:<14} {k.max_plaetze:>4} Plätze  "
                f"{k.max_minuten:>4} Minuten  {k.max_slots_woche:>3} je Woche"
                + ("  darf voll belegen" if k.darf_voll_belegen else "")
            )

        self.stdout.write("\nZugänge:")
        for b in get_user_model().objects.order_by("username"):
            profil = Profil.objects.filter(benutzer=b).select_related("klasse").first()
            klasse = profil.klasse.name if profil else "ohne Profil"
            self.stdout.write(
                f"  {b.username:<16} {klasse:<14}"
                + ("  Verwaltung" if b.is_superuser else "")
                + ("  gesperrt" if profil and not profil.darf_buchen else "")
            )
