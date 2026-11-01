# Von Hand geschrieben am 13.10.2026.
#
# Das Fach einer Buchung zieht seine Auswahl aus tutoring/faecher.py, und dort
# ist Musik dazugekommen. Dazu zwei Nachzuege, die makemigrations schon vorher
# verlangt hat (Auswahl und Hilfetext seit dem Konzept "kreativ"). Alle drei
# aendern nur den Stand des Modells, keine Spalte.
#
# Bewusst NICHT dabei: die Umbenennung des Index plan_buchun_beginn_idx, die
# makemigrations ebenfalls vorschlaegt (CLAUDE.md, Abschnitt 7). Das waere
# eine echte Aenderung an der Datenbank der Produktion und hat mit der
# Musikstunde nichts zu tun.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plan', '0003_kreativ'),
    ]

    operations = [
        migrations.AlterField(
            model_name='buchung',
            name='fach',
            field=models.CharField(blank=True, choices=[('mathematik', 'Mathematik'), ('deutsch', 'Deutsch'), ('englisch', 'Englisch'), ('sachunterricht', 'Sachunterricht'), ('musik', 'Musik')], max_length=20, verbose_name='Fach'),
        ),
        migrations.AlterField(
            model_name='buchung',
            name='konzept',
            field=models.CharField(choices=[('unterricht', 'Unterricht mit einer Klasse'), ('sichere_verwaltung', 'Sichere Verwaltung'), ('kreativ', 'Bild, Video und Musik'), ('wissensdienst', 'Eigene Unterlagen befragen'), ('modellschulung', 'Ein Modell schulen'), ('entwicklung', 'Entwicklung und Lasttest')], default='unterricht', max_length=30, verbose_name='Nutzungskonzept'),
        ),
        migrations.AlterField(
            model_name='nutzerklasse',
            name='konzepte',
            field=models.CharField(default='unterricht', help_text='Schlüssel mit Komma getrennt: unterricht, sichere_verwaltung, kreativ, wissensdienst, modellschulung, entwicklung', max_length=200, verbose_name='Erlaubte Nutzungskonzepte'),
        ),
    ]
