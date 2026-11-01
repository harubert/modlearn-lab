"""Das Fach als Abzweigung beim Anlegen einer Sitzung.

Bewusst ohne Datenwanderung: Bestehende Sitzungen behalten ein leeres Fach.
Man KOENNTE aus der Betriebsart eines ableiten - "hilfe" ist meistens
Mathematik gewesen - aber eben nur meistens. Ein erfundenes Fach in einem
Forschungsprotokoll ist schlimmer als ein leeres Feld, und die Uebersicht
haelt das leere Feld aus (siehe LearningSession.fach_name).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0017_sprechcoach"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningsession",
            name="subject",
            field=models.CharField(
                blank=True,
                choices=[
                    ("mathematik", "Mathematik"),
                    ("deutsch", "Deutsch"),
                    ("englisch", "Englisch"),
                    ("sachunterricht", "Sachunterricht"),
                ],
                max_length=20,
                verbose_name="Fach",
            ),
        ),
    ]
