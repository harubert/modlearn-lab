"""Nutzungskonzepte: Jede Buchung sagt, wofuer sie ist.

Plaetze addieren sich, Modelle nicht. Eine Buchung, die ein Modell braucht,
das nicht im Speicher liegt, baut den Rechner um und ist damit alleinig.
Das laesst sich nicht in Plaetzen ausdruecken, also traegt die Buchung ihr
Konzept (plan/konzepte.py), und die Nutzerklasse sagt, welche Konzepte sie
buchen darf.

Bestehende Buchungen bekommen "unterricht": Bis hierher gab es nur die
Lernschule, also war jede Buchung Unterricht. Das ist keine Vermutung,
sondern der einzige Weg, der damals offenstand.
"""

from django.db import migrations, models


# Die Schluessel stehen hier wortwoertlich und werden nicht aus
# plan/konzepte.py gelesen: Eine Migration beschreibt den Stand von heute.
# Kommt spaeter ein Konzept dazu, bekommt es das Lab im Admin, nicht hier.
ALLE = "unterricht,sichere_verwaltung,wissensdienst,modellschulung,entwicklung"


def konzepte_setzen(apps, schema_editor):
    """Lehrperson und Studierende buchen Unterricht, das Lab darf alles."""
    Nutzerklasse = apps.get_model("plan", "Nutzerklasse")
    Nutzerklasse.objects.filter(name="Lehrperson").update(konzepte="unterricht")
    Nutzerklasse.objects.filter(name="Studierende").update(konzepte="unterricht")
    Nutzerklasse.objects.filter(name="Lab").update(konzepte=ALLE)


def konzepte_zuruecksetzen(apps, schema_editor):
    """Rueckwaerts gibt es nichts zu tun: Die Felder fallen mit weg."""


class Migration(migrations.Migration):

    dependencies = [
        ("plan", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="nutzerklasse",
            name="konzepte",
            field=models.CharField(
                default="unterricht",
                help_text="Schlüssel mit Komma getrennt: unterricht, "
                          "sichere_verwaltung, wissensdienst, modellschulung, "
                          "entwicklung",
                max_length=200,
                verbose_name="Erlaubte Nutzungskonzepte",
            ),
        ),
        migrations.AddField(
            model_name="buchung",
            name="konzept",
            field=models.CharField(
                choices=[
                    ("unterricht", "Unterricht mit einer Klasse"),
                    ("sichere_verwaltung", "Sichere Verwaltung"),
                    ("wissensdienst", "Eigene Unterlagen befragen"),
                    ("modellschulung", "Ein Modell schulen"),
                    ("entwicklung", "Entwicklung und Lasttest"),
                ],
                default="unterricht",
                max_length=30,
                verbose_name="Nutzungskonzept",
            ),
        ),
        migrations.AddField(
            model_name="buchung",
            name="fach",
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
        migrations.AddField(
            model_name="buchung",
            name="person",
            field=models.CharField(
                blank=True, max_length=120, verbose_name="Für wen",
            ),
        ),
        migrations.RunPython(konzepte_setzen, konzepte_zuruecksetzen),
    ]
