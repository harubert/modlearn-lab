"""Adressen der Gesamtanwendung."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    # Der Zugang der Lehrperson laeuft ueber Djangos Auth-System, damit M1
    # spaeter echte Konten daraufsetzen kann, ohne dass etwas neu entsteht.
    # core.views.Anmeldung ist Djangos LoginView plus die Frage, ob der Knopf
    # fuer das PH-Konto gezeigt wird.
    path("anmelden/", core_views.Anmeldung.as_view(), name="anmelden"),
    path("abmelden/", auth_views.LogoutView.as_view(next_page="start"), name="abmelden"),
    # Bewusst nicht unter /admin/: Der Pfad wird im Netz pausenlos
    # abgeklopft, und was keinen bekannten Namen hat, bekommt weniger
    # Besuch. Sicherheit ist das keine, aber es spart Protokollrauschen.
    path("verwaltung/", admin.site.urls),
    path("plan/", include("plan.urls")),
    path("lehrperson/modelle/", include("modellwaechter.urls")),
    path("", include("tutoring.urls")),
    path("", include("core.urls")),
]
