"""Diagnose statt Leiter.

Die letzte Hilfe traegt, welche Stufe das Kind als Naechstes braucht - aus
dem ganzen Gespraech geschlossen, hoeher, dieselbe oder tiefer. Hilfen von
vorher behalten None; fuer sie gilt goal_reached allein, wie bisher.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0019_sprachsperre"),
    ]

    operations = [
        migrations.AddField(
            model_name="hint",
            name="next_level",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Nächste Stufe laut Diagnose"
            ),
        ),
    ]
