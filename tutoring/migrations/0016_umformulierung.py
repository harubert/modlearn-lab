from django.db import migrations, models


class Migration(migrations.Migration):
    """Was der Spark vor dem Senden neu formuliert hat."""

    dependencies = [
        ("tutoring", "0015_qs_im_verlauf"),
    ]

    operations = [
        migrations.AddField(
            model_name="task", name="checked_rewritten",
            field=models.TextField(blank=True, verbose_name="Neu formuliert"),
        ),
    ]
