"""Das Konzept "kreativ" fuer das Lab.

Die Spark-Betreuung hat am 11.10.2026 ein drittes Profil eingerichtet:
"kreativ" entlaedt das Sprachmodell und gibt den Speicher an ComfyUI - fuer
grosse Bild-, Video- und Musiklaeufe. Das Lab darf es buchen; wer es sonst
braucht, bekommt es im Admin an seiner Nutzerklasse.

Nur anfuegen, nie ueberschreiben: Was Thomas im Admin inzwischen an der
Klasse geaendert hat, bleibt stehen.
"""

from django.db import migrations


def kreativ_fuer_das_lab(apps, schema_editor):
    Nutzerklasse = apps.get_model("plan", "Nutzerklasse")
    for klasse in Nutzerklasse.objects.filter(name="Lab"):
        vorhanden = [t.strip() for t in (klasse.konzepte or "").split(",") if t.strip()]
        if "kreativ" not in vorhanden:
            vorhanden.append("kreativ")
            klasse.konzepte = ",".join(vorhanden)
            klasse.save(update_fields=["konzepte"])


def kreativ_wieder_weg(apps, schema_editor):
    Nutzerklasse = apps.get_model("plan", "Nutzerklasse")
    for klasse in Nutzerklasse.objects.filter(name="Lab"):
        vorhanden = [t.strip() for t in (klasse.konzepte or "").split(",")
                     if t.strip() and t.strip() != "kreativ"]
        klasse.konzepte = ",".join(vorhanden)
        klasse.save(update_fields=["konzepte"])


class Migration(migrations.Migration):

    dependencies = [
        ("plan", "0002_nutzungskonzepte"),
    ]

    operations = [
        migrations.RunPython(kreativ_fuer_das_lab, kreativ_wieder_weg),
    ]
