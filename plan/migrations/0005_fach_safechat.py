# Von Hand geschrieben am 23.10.2026.
#
# Das Fach einer Buchung zieht seine Auswahl aus tutoring/faecher.py, und dort
# ist der Safe Chat dazugekommen. Aendert nur den Stand des Modells, keine
# Spalte. Die Umbenennung des Index plan_buchun_beginn_idx bleibt wie in 0004
# bewusst draussen (CLAUDE.md, Abschnitt 7).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plan", "0004_fach_musik"),
    ]

    operations = [
        migrations.AlterField(
            model_name="buchung",
            name="fach",
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
    ]
