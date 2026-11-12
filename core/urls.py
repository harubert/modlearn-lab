"""Adressen der Grundlagen: Startseite, Rechtstexte, Zustandsprüfung."""

from django.urls import path

from . import musik_oeffentlich, views

urlpatterns = [
    path("", views.start, name="start"),
    path("stufen/", views.stufen, name="stufen"),
    path("bildpruefung/", views.bildpruefung, name="bildpruefung"),
    path("trainer-erklaerung/", views.trainer_erklaerung, name="trainer_erklaerung"),
    path("sprechcoach-erklaerung/", views.sprechcoach_erklaerung, name="sprechcoach_erklaerung"),
    path("projekt/", views.projekt, name="projekt"),
    path("ki/", views.ki, name="ki"),
    path("datenschutz/", views.datenschutz, name="datenschutz"),
    path("barrierefreiheit/", views.barrierefreiheit, name="barrierefreiheit"),
    path("healthz", views.healthz, name="healthz"),
    # Genau dieser Pfad steht in der Caddy-Route mit forward_auth. Wer ihn
    # aendert, aendert ihn auch dort, sonst kommen die Kopfzeilen nicht an.
    path("anmelden/ph-online/", views.ph_anmeldung, name="ph_anmeldung"),
]

# Die Testecke fuer die Musik-KI. Bewusst nirgends verlinkt; wer sie braucht,
# bekommt die Adresse.
urlpatterns += [
    path("labor/musik/", views.musik_labor, name="musik_labor"),
    path("labor/musik/lied/", views.musik_absenden, name="musik_absenden"),
    path("labor/musik/auftrag/<str:kennung>/", views.musik_auftrag, name="musik_auftrag"),
    path("labor/musik/datei/<str:kennung>/", views.musik_datei, name="musik_datei"),
    path("labor/musik/loeschen/<str:kennung>/", views.musik_loeschen, name="musik_loeschen"),
]

# Die Musik-KI zum Ausprobieren, ganz unten auf /projekt/, ohne Anmeldung.
# Unter /projekt/, weil sie zu dieser Seite gehoert und nur von dort kommt.
urlpatterns += [
    path("projekt/musik/stand/", musik_oeffentlich.stand, name="musik_oe_stand"),
    path("projekt/musik/lied/", musik_oeffentlich.lied, name="musik_oe_lied"),
    path("projekt/musik/auftrag/<str:kennung>/", musik_oeffentlich.auftrag, name="musik_oe_auftrag"),
    path("projekt/musik/datei/<str:kennung>/", musik_oeffentlich.datei, name="musik_oe_datei"),
]
