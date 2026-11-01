from django.db import migrations, models


class Migration(migrations.Migration):
    """Der Trainer schreibt den Zustand ins Ergebnisfeld, und
    'trainer:lernschritt' passte nicht in sechzehn Zeichen."""

    dependencies = [
        ("tutoring", "0013_trainer"),
    ]

    operations = [
        migrations.AlterField(
            model_name="interaction",
            name="outcome",
            field=models.CharField(default="ok", max_length=32),
        ),
    ]
