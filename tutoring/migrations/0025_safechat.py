# Der Safe Chat (Thomas, 23.10.2026): fuenfte Betriebsart, sechstes Fach,
# ein Modell fuer die Zuege samt Protokoll des Weges nach draussen.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0024_schulstufe_diagnose"),
    ]

    operations = [
        migrations.AlterField(
            model_name="learningsession",
            name="mode",
            field=models.CharField(
                choices=[
                    ("hilfe", "Aufgabenhilfe"),
                    ("trainer", "Trainer für alles"),
                    ("sprache", "Sprechcoach"),
                    ("musik", "Musikstunde"),
                    ("chat", "Safe Chat"),
                ],
                default="hilfe",
                max_length=10,
                verbose_name="Betriebsart",
            ),
        ),
        migrations.AlterField(
            model_name="learningsession",
            name="subject",
            field=models.CharField(
                blank=True,
                choices=[
                    ("mathematik", "Mathematik"),
                    ("deutsch", "Deutsch"),
                    ("englisch", "Englisch"),
                    ("sachunterricht", "Sachunterricht"),
                    ("musik", "Musik"),
                    ("safechat", "Safe Chat"),
                ],
                max_length=20,
                verbose_name="Fach",
            ),
        ),
        migrations.CreateModel(
            name="ChatZug",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("lernend", "lernende Person"), ("ki", "KI")], max_length=8, verbose_name="Rolle")),
                ("text", models.TextField(blank=True, verbose_name="Text")),
                ("weg", models.CharField(choices=[("spark", "Spark"), ("aussen", "nach draußen")], default="spark", max_length=8, verbose_name="Weg")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("flag", models.CharField(default="gruen", max_length=12, verbose_name="Einstufung")),
                ("flag_reason", models.CharField(blank=True, max_length=120, verbose_name="Begründung")),
                ("aussen_umgeschrieben", models.TextField(blank=True, verbose_name="Vom Spark umformuliert")),
                ("aussen_gesendet", models.TextField(blank=True, verbose_name="Hinausgegangen, maskiert")),
                ("aussen_empfangen", models.TextField(blank=True, verbose_name="Zurückgekommen, maskiert")),
                ("aussen_entitaeten", models.JSONField(blank=True, default=dict, verbose_name="Ersetzte Angaben")),
                ("aussen_modell", models.CharField(blank=True, max_length=80, verbose_name="Modell")),
                ("aussen_tokens_in", models.PositiveIntegerField(default=0)),
                ("aussen_tokens_out", models.PositiveIntegerField(default=0)),
                ("aussen_ms", models.PositiveIntegerField(default=0, verbose_name="Dauer in Millisekunden")),
                ("aussen_cost_micro", models.PositiveIntegerField(default=0, verbose_name="Kosten in Mikro-Euro")),
                ("aussen_gesperrt", models.CharField(blank=True, max_length=120, verbose_name="Nicht hinausgegangen, weil")),
                ("urteil", models.CharField(blank=True, choices=[("ohne", "ohne Personenbezug"), ("mit", "Personenbezug gesehen"), ("offen", "kein Urteil")], max_length=8, verbose_name="Urteil der Gegenstelle")),
                ("urteil_grund", models.CharField(blank=True, max_length=240, verbose_name="Begründung des Urteils")),
                ("participation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chatzuege", to="tutoring.participation")),
            ],
            options={
                "verbose_name": "Chatzug",
                "verbose_name_plural": "Chatzüge",
                "ordering": ["created_at", "pk"],
            },
        ),
    ]
