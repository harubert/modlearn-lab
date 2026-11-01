import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def klassen_anlegen(apps, schema_editor):
    """Drei Klassen zum Anfangen.

    Die Zahlen sind ein erster Vorschlag und keine Erkenntnis. Der Rueckblick
    zeigt nach ein paar Wochen, ob sie passen; dann werden sie im Admin
    geaendert und nicht im Code.
    """
    Nutzerklasse = apps.get_model("plan", "Nutzerklasse")
    Nutzerklasse.objects.bulk_create([
        Nutzerklasse(
            name="Lehrperson",
            beschreibung="Unterricht mit einer Klasse",
            max_minuten=240, max_slots_woche=20, max_plaetze=60,
        ),
        Nutzerklasse(
            name="Studierende",
            beschreibung="Eigene Projekte, Programmieren, Seminararbeiten",
            max_minuten=120, max_slots_woche=6, max_plaetze=5,
        ),
        Nutzerklasse(
            name="Lab",
            beschreibung="Entwicklung und Lasttests, kaum begrenzt",
            max_minuten=600, max_slots_woche=100, max_plaetze=120,
            darf_voll_belegen=True,
        ),
    ])


def klassen_entfernen(apps, schema_editor):
    apps.get_model("plan", "Nutzerklasse").objects.all().delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Nutzerklasse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True, verbose_name="Name")),
                ("beschreibung", models.CharField(blank=True, max_length=200,
                                                  verbose_name="Wofür")),
                ("max_minuten", models.PositiveIntegerField(
                    default=120, verbose_name="Längste Buchung in Minuten")),
                ("max_slots_woche", models.PositiveIntegerField(
                    default=5, verbose_name="Buchungen je Woche")),
                ("max_plaetze", models.PositiveIntegerField(
                    default=30, verbose_name="Plätze je Buchung")),
                ("darf_voll_belegen", models.BooleanField(
                    default=False, verbose_name="Darf die Maschine ganz belegen")),
            ],
            options={
                "verbose_name": "Nutzerklasse",
                "verbose_name_plural": "Nutzerklassen",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Profil",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("einrichtung", models.CharField(blank=True, max_length=120,
                                                 verbose_name="Einrichtung")),
                ("gesperrt_am", models.DateTimeField(blank=True, null=True,
                                                     verbose_name="Gesperrt am")),
                ("benutzer", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="planprofil", to=settings.AUTH_USER_MODEL)),
                ("klasse", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="profile", to="plan.nutzerklasse")),
            ],
            options={
                "verbose_name": "Planungsprofil",
                "verbose_name_plural": "Planungsprofile",
            },
        ),
        migrations.CreateModel(
            name="Buchung",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("beginn", models.DateTimeField(verbose_name="Beginn")),
                ("ende", models.DateTimeField(verbose_name="Ende")),
                ("plaetze", models.PositiveIntegerField(default=1, verbose_name="Plätze")),
                ("zweck", models.CharField(blank=True, max_length=160, verbose_name="Wofür")),
                ("angelegt_am", models.DateTimeField(auto_now_add=True)),
                ("abgesagt_am", models.DateTimeField(blank=True, null=True,
                                                     verbose_name="Abgesagt am")),
                ("besitzer", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="buchungen", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Buchung",
                "verbose_name_plural": "Buchungen",
                "ordering": ["beginn"],
            },
        ),
        migrations.AddIndex(
            model_name="buchung",
            index=models.Index(fields=["beginn", "ende"], name="plan_buchun_beginn_idx"),
        ),
        migrations.RunPython(klassen_anlegen, klassen_entfernen),
    ]
