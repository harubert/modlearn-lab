"""Die Verwaltung der Zugaenge und Klassen.

Bewusst ueber den Django-Admin und nicht ueber eine eigene Oberflaeche:
Zugaenge anlegen macht eine Person im Lab, nicht dreissig Lehrpersonen. Eine
eigene Seite dafuer waere Arbeit ohne Nutzen.
"""

from django.contrib import admin

from .models import Buchung, Nutzerklasse, Profil


@admin.register(Nutzerklasse)
class NutzerklasseAdmin(admin.ModelAdmin):
    # `konzepte` steht in der Liste, weil es die Frage beantwortet, die
    # hier am oeftesten gestellt wird: Wer darf den Rechner umbauen?
    list_display = ("name", "max_minuten", "max_slots_woche", "max_plaetze",
                    "darf_voll_belegen", "konzepte")
    search_fields = ("name", "beschreibung")


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ("benutzer", "klasse", "einrichtung", "gesperrt_am")
    list_filter = ("klasse", "einrichtung")
    search_fields = ("benutzer__username", "benutzer__first_name",
                     "benutzer__last_name", "einrichtung")
    autocomplete_fields = ()
    raw_id_fields = ("benutzer",)


@admin.register(Buchung)
class BuchungAdmin(admin.ModelAdmin):
    list_display = ("beginn", "ende", "konzept", "plaetze", "fach", "person",
                    "besitzer", "zweck", "abgesagt_am")
    list_filter = ("konzept", "fach", "besitzer")
    date_hierarchy = "beginn"
    raw_id_fields = ("besitzer",)
