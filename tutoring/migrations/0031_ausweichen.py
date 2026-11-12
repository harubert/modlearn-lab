# Die Fachgrenze (7.11.2026): Im Safe Chat wird eine Antwort des Spark
# zurueckgehalten, wenn sie die Form einer politischen Verweigerung traegt
# (tutoring/fachgrenze.py, ausweichen_erkannt). Der Grund steht am Zug.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tutoring', '0030_aufgabenpool'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatzug',
            name='ausweichen',
            field=models.CharField(blank=True, max_length=120, verbose_name='Antwort zurückgehalten, weil'),
        ),
    ]
