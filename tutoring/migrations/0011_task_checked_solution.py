from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tutoring", "0010_task_finished_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="checked_solution",
            field=models.TextField(blank=True, verbose_name="Geprüfte Lösung"),
        ),
        migrations.AddField(
            model_name="task",
            name="checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Geprüft am"),
        ),
    ]
