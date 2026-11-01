# Bildweiterleitung (Thomas, 31.10.2026): der zweite Schalter je Sitzung und
# die Felder, in denen die Aufgabe festhaelt, was von einem Foto hinausging.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0027_protokoll_anweisung"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="cloud_images_enabled",
            field=models.BooleanField(
                default=False, verbose_name="Fotos der Aufgabe prüfen lassen"
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_image_check",
            field=models.CharField(blank=True, max_length=12, verbose_name="Bildprüfung"),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_image_reason",
            field=models.CharField(
                blank=True, max_length=120, verbose_name="Bildprüfung, Grund"
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_image_sent",
            field=models.TextField(blank=True, verbose_name="Hinausgegangener Ausschnitt"),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_image_masks",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Maskierungen je Typ"
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_image_ms",
            field=models.PositiveIntegerField(
                default=0, verbose_name="Bildprüfung, Dauer in Millisekunden"
            ),
        ),
    ]
