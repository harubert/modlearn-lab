from django.db import migrations, models


class Migration(migrations.Migration):
    """Der Austausch mit der externen KI gehoert in den Gespraechsverlauf.

    Er stand bisher nur im Forschungsprotokoll, und das hat absichtlich keine
    Bruecke zur Person.
    """

    dependencies = [
        ("tutoring", "0014_outcome_laenger"),
    ]

    operations = [
        migrations.AddField(
            model_name="task", name="checked_model",
            field=models.CharField(blank=True, max_length=80, verbose_name="Modell"),
        ),
        migrations.AddField(
            model_name="task", name="checked_sent",
            field=models.TextField(blank=True, verbose_name="Hinausgegangen, maskiert"),
        ),
        migrations.AddField(
            model_name="task", name="checked_received",
            field=models.TextField(blank=True, verbose_name="Zurückgekommen, maskiert"),
        ),
        migrations.AddField(
            model_name="task", name="checked_entities",
            field=models.JSONField(blank=True, default=dict, verbose_name="Ersetzte Angaben"),
        ),
        migrations.AddField(
            model_name="task", name="checked_tokens_in",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task", name="checked_tokens_out",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task", name="checked_ms",
            field=models.PositiveIntegerField(default=0, verbose_name="Dauer in Millisekunden"),
        ),
        migrations.AddField(
            model_name="task", name="checked_cost_micro",
            field=models.PositiveIntegerField(default=0, verbose_name="Kosten in Mikro-Euro"),
        ),
        migrations.AddField(
            model_name="task", name="checked_blocked",
            field=models.CharField(blank=True, max_length=120, verbose_name="Nicht gelaufen, weil"),
        ),
    ]
