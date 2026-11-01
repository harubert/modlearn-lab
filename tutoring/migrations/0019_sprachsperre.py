"""Der Sprechcoach tut, als verstehe er kein Deutsch.

Ein Zug, der die Sperre ausloest, ist ein Gespraechsbeitrag und kein Fehler;
er bekommt deshalb ein Feld am Zug und keine Fehlerzeile im Protokoll.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0018_fach"),
    ]

    operations = [
        migrations.AddField(
            model_name="sprachzug",
            name="not_understood",
            field=models.BooleanField(default=False, verbose_name="Nicht verstanden"),
        ),
    ]
