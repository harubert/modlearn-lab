import django.db.models.deletion
from django.db import migrations, models

import tutoring.sprechcoach


class Migration(migrations.Migration):
    """Der Sprechcoach als dritte Betriebsart."""

    dependencies = [
        ("tutoring", "0016_umformulierung"),
    ]

    operations = [
        migrations.AlterField(
            model_name="learningsession", name="mode",
            field=models.CharField(
                choices=[("hilfe", "Aufgabenhilfe"), ("trainer", "Trainer für alles"),
                         ("sprache", "Sprechcoach")],
                default="hilfe", max_length=10, verbose_name="Betriebsart"),
        ),
        migrations.AddField(
            model_name="learningsession", name="target_language",
            field=models.CharField(
                choices=tutoring.sprechcoach.SPRACHEN, default="en-GB",
                max_length=8, verbose_name="Zielsprache"),
        ),
        migrations.AddField(
            model_name="learningsession", name="language_level",
            field=models.CharField(
                choices=tutoring.sprechcoach.NIVEAUS, default="A1",
                max_length=4, verbose_name="Niveau"),
        ),
        migrations.CreateModel(
            name="SprachLauf",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True,
                                                     verbose_name="Beendet")),
                ("participation", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sprachlaeufe", to="tutoring.participation")),
            ],
            options={
                "verbose_name": "Sprechgespräch",
                "verbose_name_plural": "Sprechgespräche",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="SprachZug",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("role", models.CharField(
                    choices=[("coach", "Sprechcoach"), ("lernend", "lernende Person")],
                    max_length=8, verbose_name="Rolle")),
                ("text", models.TextField(blank=True, verbose_name="Text in der Zielsprache")),
                ("translation", models.TextField(blank=True, verbose_name="Auf Deutsch")),
                ("correction", models.TextField(blank=True, verbose_name="Beiläufige Korrektur")),
                ("source", models.CharField(
                    choices=[("tippen", "getippt"), ("foto", "fotografiert"),
                             ("sprache", "gesprochen")],
                    default="tippen", max_length=10, verbose_name="Herkunft")),
                ("flag", models.CharField(default="gruen", max_length=12,
                                          verbose_name="Einstufung")),
                ("flag_reason", models.CharField(blank=True, max_length=120,
                                                 verbose_name="Begründung")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="zuege", to="tutoring.sprachlauf")),
            ],
            options={
                "verbose_name": "Gesprächsbeitrag",
                "verbose_name_plural": "Gesprächsbeiträge",
                "ordering": ["created_at", "pk"],
            },
        ),
    ]
