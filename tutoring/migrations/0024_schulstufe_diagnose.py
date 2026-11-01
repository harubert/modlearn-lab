# Benchmark vom 19.10.2026 (docs/Mathe-Benchmark und Konfiguration.md):
# Die Schulstufe loest in Mathematik die Altersklasse ab, und die Diagnose
# sagt je Beitrag, ob das Ergebnis richtig, falsch oder offen ist, und
# welcher Fehler es war. Alle drei Felder haben Vorgaben, bestehende Zeilen
# bleiben lesbar.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0023_musik_texthilfe"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="schulstufe",
            field=models.CharField(
                choices=[
                    ("vs", "Volksschule"),
                    ("sek1", "Mittelstufe (5. bis 8.)"),
                    ("sek2", "Oberstufe (bis Matura)"),
                ],
                default="vs",
                max_length=5,
                verbose_name="Schulstufe",
            ),
        ),
        migrations.AddField(
            model_name="hint",
            name="result",
            field=models.CharField(
                blank=True,
                choices=[("richtig", "richtig"), ("falsch", "falsch"), ("offen", "offen")],
                max_length=8,
                verbose_name="Ergebnis laut Diagnose",
            ),
        ),
        migrations.AddField(
            model_name="hint",
            name="error",
            field=models.CharField(
                blank=True, max_length=120, verbose_name="Fehler im Klartext"
            ),
        ),
    ]
