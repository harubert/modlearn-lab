"""Adressen des Modellwaechters, unter /lehrperson/modelle/."""

from django.urls import path

from . import views

app_name = "modellwaechter"

urlpatterns = [
    path("", views.uebersicht, name="uebersicht"),
    path("gelesen/", views.alle_gelesen, name="alle_gelesen"),
    path("gelesen/<int:pk>/", views.gelesen, name="gelesen"),
]
