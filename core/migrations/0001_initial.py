import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PhKonto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("oid", models.CharField(max_length=64, unique=True,
                                         verbose_name="Entra-Objekt-ID")),
                ("email", models.CharField(blank=True, max_length=254,
                                           verbose_name="E-Mail")),
                ("anmeldename", models.CharField(blank=True, max_length=150,
                                                 verbose_name="Anmeldename")),
                ("name", models.CharField(blank=True, max_length=200,
                                          verbose_name="Name")),
                ("gruppen", models.TextField(blank=True, verbose_name="Gruppen")),
                ("zuletzt_gesehen", models.DateTimeField(
                    default=django.utils.timezone.now,
                    verbose_name="Zuletzt gesehen")),
                ("angelegt_am", models.DateTimeField(auto_now_add=True,
                                                     verbose_name="Angelegt am")),
                ("benutzer", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="phkonto", to=settings.AUTH_USER_MODEL,
                    verbose_name="Benutzer")),
            ],
            options={
                "verbose_name": "PH-Konto",
                "verbose_name_plural": "PH-Konten",
                "ordering": ["-zuletzt_gesehen"],
            },
        ),
    ]
