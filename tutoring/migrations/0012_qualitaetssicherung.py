from django.db import migrations, models


class Migration(migrations.Migration):
    """Nur die Beschriftung: In der Oberflaeche heisst der Schalter
    Qualitaetssicherung, nicht 'externe KI'."""

    dependencies = [
        ("tutoring", "0011_task_checked_solution"),
    ]

    operations = [
        migrations.AlterField(
            model_name="learningsession",
            name="cloud_enabled",
            field=models.BooleanField(default=False, verbose_name="Qualitätssicherung"),
        ),
    ]
