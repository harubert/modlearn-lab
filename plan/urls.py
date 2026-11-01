"""Adressen des Planungswerkzeugs."""

from django.urls import path

from . import views

app_name = "plan"

urlpatterns = [
    path("", views.tag, name="tag"),
    path("buchen/", views.buchen, name="buchen"),
    path("absagen/", views.absagen, name="absagen"),
    path("rueckblick/", views.rueckblick, name="rueckblick"),
]
