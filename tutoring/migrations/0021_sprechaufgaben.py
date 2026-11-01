"""Gesprächsaufgaben und Ablauf des Sprechcoachs.

Die Sitzung trägt die Aufgabe (leer = freies Gespräch, wie bisher), der Lauf
seine Phase, ob das Ziel im ersten und zweiten Durchgang erreicht wurde, und
den Rückblick; jeder Zug die Phase, in der er fiel. Läufe und Züge von vorher
stehen in "aufgabe" – also mitten im Gespräch, wie sie es waren.

Die Abweichung bei trainerzug.source, die makemigrations zusätzlich meldet,
ist älter und gehört nicht hierher.
"""

import django.utils.timezone
from django.db import migrations, models

PHASEN = [
    ("planen", "Planen"),
    ("aufgabe", "Gespräch"),
    ("wechsel", "Gespräch, Rollentausch"),
    ("wiederholung", "Noch einmal"),
    ("rueckblick", "Rückblick"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0020_diagnose"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="speaking_task",
            field=models.CharField(
                blank=True, default="", max_length=40,
                verbose_name="Gesprächsaufgabe",
            ),
        ),
        migrations.AddField(
            model_name="sprachlauf",
            name="phase",
            field=models.CharField(
                choices=PHASEN, default="aufgabe", max_length=12,
                verbose_name="Phase",
            ),
        ),
        migrations.AddField(
            model_name="sprachlauf",
            name="phase_seit",
            field=models.DateTimeField(
                default=django.utils.timezone.now, verbose_name="Phase seit",
            ),
        ),
        migrations.AddField(
            model_name="sprachlauf",
            name="goal_first",
            field=models.BooleanField(
                blank=True, null=True, verbose_name="Ziel im 1. Durchgang",
            ),
        ),
        migrations.AddField(
            model_name="sprachlauf",
            name="goal_second",
            field=models.BooleanField(
                blank=True, null=True, verbose_name="Ziel im 2. Durchgang",
            ),
        ),
        migrations.AddField(
            model_name="sprachlauf",
            name="review",
            field=models.JSONField(blank=True, default=list, verbose_name="Rückblick"),
        ),
        migrations.AddField(
            model_name="sprachzug",
            name="phase",
            field=models.CharField(
                choices=PHASEN, default="aufgabe", max_length=12,
                verbose_name="Phase",
            ),
        ),
    ]
