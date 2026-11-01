import django.db.models.deletion
from django.db import migrations, models

import tutoring.pruefung
import tutoring.trainer


class Migration(migrations.Migration):
    """Der Trainer als zweite Betriebsart derselben Sitzung."""

    dependencies = [
        ("tutoring", "0012_qualitaetssicherung"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="mode",
            field=models.CharField(
                choices=[("hilfe", "Aufgabenhilfe"), ("trainer", "Trainer für alles")],
                default="hilfe", max_length=10, verbose_name="Betriebsart",
            ),
        ),
        migrations.CreateModel(
            name="TrainerLauf",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("topic", models.CharField(blank=True, max_length=300, verbose_name="Thema")),
                ("state", models.CharField(
                    choices=tutoring.trainer.ZUSTAENDE, default="thema",
                    max_length=16, verbose_name="Zustand")),
                ("representation", models.CharField(
                    choices=tutoring.trainer.DARSTELLUNGEN, default="gegenstaendlich",
                    max_length=16, verbose_name="Darstellung")),
                ("tried", models.JSONField(blank=True, default=list,
                                           verbose_name="Versuchte Zugänge")),
                ("step_no", models.PositiveSmallIntegerField(default=0, verbose_name="Lernschritt")),
                ("loops", models.PositiveSmallIntegerField(default=0, verbose_name="Schleifen")),
                ("tasks_given", models.PositiveSmallIntegerField(default=0, verbose_name="Aufgaben gestellt")),
                ("tasks_right", models.PositiveSmallIntegerField(default=0, verbose_name="Aufgaben richtig")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="Abgeschlossen")),
                ("participation", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="trainerlaeufe", to="tutoring.participation")),
            ],
            options={
                "verbose_name": "Trainerlauf",
                "verbose_name_plural": "Trainerläufe",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="TrainerZug",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("role", models.CharField(
                    choices=[("trainer", "Trainer"), ("lernend", "lernende Person")],
                    max_length=8, verbose_name="Rolle")),
                ("text", models.TextField(blank=True, verbose_name="Text")),
                ("question", models.TextField(blank=True, verbose_name="Die eine Frage")),
                ("image_data_url", models.TextField(blank=True, verbose_name="Foto")),
                ("source", models.CharField(
                    choices=[("tippen", "getippt"), ("foto", "fotografiert"),
                             ("sprache", "gesprochen")],
                    default="getippt", max_length=10, verbose_name="Herkunft")),
                ("state", models.CharField(blank=True, max_length=16, verbose_name="Zustand")),
                ("representation", models.CharField(blank=True, max_length=16, verbose_name="Darstellung")),
                ("verdict", models.CharField(
                    blank=True, choices=tutoring.trainer.URTEILE,
                    max_length=12, verbose_name="Urteil")),
                ("error_kind", models.CharField(blank=True, max_length=60, verbose_name="Fehlertyp")),
                ("flag", models.CharField(default="gruen", max_length=12, verbose_name="Einstufung")),
                ("flag_reason", models.CharField(blank=True, max_length=120, verbose_name="Begründung")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("run", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="zuege", to="tutoring.trainerlauf")),
            ],
            options={
                "verbose_name": "Trainerzug",
                "verbose_name_plural": "Trainerzüge",
                "ordering": ["created_at", "pk"],
            },
        ),
    ]
