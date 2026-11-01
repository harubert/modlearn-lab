# Von Hand am 19.10.2026, nach dem Muster von makemigrations.
#
# Die Musikstunde bekommt den Textvorschlag vom Spark; die Lehrperson kann
# ihn je Sitzung abschalten. Vorgabe an: Sitzungen von vorher verhalten sich
# so, wie Thomas es bestellt hat (die Kinder duerfen waehlen).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tutoring', '0022_musikstunde'),
    ]

    operations = [
        migrations.AddField(
            model_name='learningsession',
            name='song_text_help',
            field=models.BooleanField(default=True, verbose_name='Die Kinder dürfen sich einen Text vom Spark schreiben lassen'),
        ),
    ]
