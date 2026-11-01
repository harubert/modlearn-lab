"""PH-Konten in der Verwaltung.

Hier schaltet die Verwaltung Lehrpersonen frei: Jedes neue PH-Konto bekommt
ein Planungsprofil der Klasse "Studierende" (Vorgabe der Serverbetreuung:
Standard Studierende, Freigabe von Hand fuer Lehrpersonen). Die Freigabe ist
das Umstellen der Nutzerklasse am Profil; der Link in der Liste fuehrt genau
dorthin. Mehr Oberflaeche braucht es nicht.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import PhKonto


@admin.register(PhKonto)
class PhKontoAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "zuletzt_gesehen", "planungsprofil", "oid")
    search_fields = ("name", "email", "anmeldename", "oid", "benutzer__username")
    ordering = ("-zuletzt_gesehen",)
    date_hierarchy = "zuletzt_gesehen"
    fields = (
        "name", "email", "anmeldename", "oid", "benutzer", "planungsprofil",
        "gruppen", "zuletzt_gesehen", "angelegt_am",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        # Das Profil haengt am Benutzer, nicht am Konto. Ohne select_related
        # waeren das zwei Abfragen je Zeile der Liste.
        return super().get_queryset(request).select_related(
            "benutzer", "benutzer__planprofil__klasse"
        )

    def has_add_permission(self, request):
        # Konten entstehen nur durch eine echte Anmeldung ueber die PH. Ein
        # von Hand eingetragenes Konto mit abgetippter Objekt-ID waere eines,
        # das beim ersten echten Besuch nicht gefunden wird.
        return False

    def has_change_permission(self, request, obj=None):
        # Alles hier kommt von der PH und wird bei jedem Besuch nachgezogen;
        # eine Aenderung von Hand waere beim naechsten Besuch wieder weg.
        # Geaendert wird am Profil (Nutzerklasse) und am Benutzer (Sperre).
        return False

    @admin.display(description="Planungsprofil")
    def planungsprofil(self, konto):
        profil = getattr(konto.benutzer, "planprofil", None)
        if profil is None:
            adresse = reverse("admin:plan_profil_add") + f"?benutzer={konto.benutzer_id}"
            return format_html('<a href="{}">kein Profil – anlegen</a>', adresse)
        adresse = reverse("admin:plan_profil_change", args=[profil.pk])
        zusatz = " (gesperrt)" if profil.gesperrt_am else ""
        return format_html('<a href="{}">{}</a>{}', adresse, profil.klasse.name, zusatz)
