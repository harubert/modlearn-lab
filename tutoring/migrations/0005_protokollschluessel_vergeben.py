"""Fuellt die Protokollschluessel und macht sie erst danach eindeutig.

In einem Zug angelegt, waeren alle bestehenden Zeilen mit dem leeren Wert
befuellt worden und haetten sich gegenseitig blockiert. Deshalb der Umweg:
Spalte anlegen, Werte setzen, dann die Eindeutigkeit fordern.
"""

import secrets

from django.db import migrations, models


def schluessel_vergeben(apps, schema_editor):
    for name in ("LearningSession", "Participation"):
        modell = apps.get_model("tutoring", name)
        for zeile in modell.objects.filter(log_key="").only("pk"):
            modell.objects.filter(pk=zeile.pk).update(log_key=secrets.token_urlsafe(32))


def schluessel_leeren(apps, schema_editor):
    """Rueckwaerts: die Schluessel wieder entfernen."""
    for name in ("LearningSession", "Participation"):
        apps.get_model("tutoring", name).objects.update(log_key="")


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0004_interaction_learningsession_log_key_and_more"),
    ]

    operations = [
        migrations.RunPython(schluessel_vergeben, schluessel_leeren),
        migrations.AlterField(
            model_name="learningsession",
            name="log_key",
            field=models.CharField(blank=True, db_index=True, max_length=43, unique=True),
        ),
        migrations.AlterField(
            model_name="participation",
            name="log_key",
            field=models.CharField(blank=True, db_index=True, max_length=43, unique=True),
        ),
    ]
