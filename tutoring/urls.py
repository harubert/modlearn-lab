"""Adressen der Aufgabenhilfe.

Die Beitrittsadresse ist bewusst kurz und enthaelt den Code, damit der
QR-Code auf der Leinwand direkt in die Sitzung fuehrt und niemand tippen muss.
"""

from django.urls import path

from . import (chat_views, musik_views, protokoll_views, sprechcoach_views,
               trainer_views, views)

app_name = "tutoring"

urlpatterns = [
    # Lehrperson
    path("lehrperson/", views.lehrperson_uebersicht, name="lehrperson_uebersicht"),
    path("lehrperson/bereit/", views.lehrperson_bereitschaft,
         name="lehrperson_bereitschaft"),
    path("lehrperson/leere-beenden/", views.lehrperson_leere_beenden,
         name="lehrperson_leere_beenden"),
    path("lehrperson/sitzung/<str:code>/", views.lehrperson_sitzung,
         name="lehrperson_sitzung"),
    path("lehrperson/sitzung/<str:code>/klasse/", views.lehrperson_klassenliste,
         name="lehrperson_klassenliste"),
    path("lehrperson/sitzung/<str:code>/verlauf/<int:teilnahme_id>/",
         views.lehrperson_verlauf, name="lehrperson_verlauf"),
    path("lehrperson/sitzung/<str:code>/beenden/", views.lehrperson_sitzung_beenden,
         name="lehrperson_sitzung_beenden"),
    path("lehrperson/sitzung/<str:code>/titel/", views.lehrperson_titel, name="lehrperson_titel"),
    path("lehrperson/sitzung/<str:code>/aufgabe/", views.lehrperson_aufgabe_hinzufuegen,
         name="lehrperson_aufgabe_hinzufuegen"),
    path("lehrperson/sitzung/<str:code>/aufgabe/<int:pk>/entfernen/",
         views.lehrperson_aufgabe_entfernen, name="lehrperson_aufgabe_entfernen"),
    # Das Protokoll der Anfragen (Abschnitt 3b; Thomas, 31.10.2026): je
    # Sitzung, auch nach ihrem Ende, mit Export als JSON und CSV.
    path("lehrperson/protokolle/", protokoll_views.lehrperson_protokolle,
         name="lehrperson_protokolle"),
    path("lehrperson/sitzung/<str:code>/protokoll/", protokoll_views.lehrperson_protokoll,
         name="lehrperson_protokoll"),
    # Ein Lied der Musikstunde, nur fuer die Lehrperson dieser Sitzung.
    path("lehrperson/sitzung/<str:code>/lied/<int:lied_id>/",
         musik_views.lehrperson_datei, name="lehrperson_lied"),
    path("qr/<str:code>.svg", views.qr_code, name="qr_code"),

    # Teilnehmende
    path("beitreten/", views.beitreten, name="beitreten"),
    path("beitreten/<str:code>/", views.beitreten, name="beitreten_mit_code"),
    path("sitzung/zustimmung/", views.zustimmung, name="zustimmung"),
    path("sitzung/tier/", views.tier_waehlen, name="tier_waehlen"),
    path("sitzung/", views.chat, name="chat"),
    path("sitzung/aufgabe/", views.aufgabe_stellen, name="aufgabe_stellen"),
    path("sitzung/ergaenzen/", views.aufgabe_ergaenzen, name="aufgabe_ergaenzen"),
    path("sitzung/fertig/", views.aufgabe_abschliessen, name="aufgabe_abschliessen"),
    path("sitzung/note/", views.aufgabe_benoten, name="aufgabe_benoten"),
    path("sitzung/uebung/", views.aufgabe_waehlen, name="aufgabe_waehlen"),
    path("sitzung/antwort/", views.antwort_geben, name="antwort_geben"),
    path("sitzung/bild/", views.bild_erkennen, name="bild_erkennen"),
    path("sitzung/sprache/", views.sprache_erkennen, name="sprache_erkennen"),
    path("sitzung/hilfe/<int:task_id>/", views.hilfe_streamen_ansicht, name="hilfe"),
    path("sitzung/nachfrage/", views.nachfrage_stellen, name="nachfrage_stellen"),

    # Der Trainer, zweite Betriebsart derselben Sitzung.
    path("trainer/", trainer_views.trainerseite, name="trainer"),
    path("trainer/zug/", trainer_views.trainer_zug, name="trainer_zug"),
    path("trainer/neu/", trainer_views.trainer_neu, name="trainer_neu"),

    # Der Sprechcoach, dritte Betriebsart.
    path("sprechcoach/", sprechcoach_views.coachseite, name="sprechcoach"),
    path("sprechcoach/zug/", sprechcoach_views.coach_zug, name="sprechcoach_zug"),
    # Eine Aeusserung abschreiben: Text, erkannte Sprache, und ob sie fertig
    # klingt. Eigener Weg neben sitzung/sprache/, das die Aufgabenhilfe nutzt.
    path("sprechcoach/hoeren/", sprechcoach_views.coach_hoeren, name="sprechcoach_hoeren"),
    path("sprechcoach/neu/", sprechcoach_views.coach_neu, name="sprechcoach_neu"),
    # Der naechste Schritt auf Wunsch: "Ich bin bereit" nach dem Planen,
    # "Ich höre hier auf" aus dem Gespraech in den Rueckblick.
    path("sprechcoach/weiter/", sprechcoach_views.coach_weiter, name="sprechcoach_weiter"),
    # Der stille Ausweg "Ich komme nicht weiter": deutsche Erklaerung plus ein
    # Beispielsatz in der Zielsprache. Kein Zug, nur eine Auskunft.
    path("sprechcoach/hilfe/", sprechcoach_views.coach_hilfe, name="sprechcoach_hilfe"),
    # Die Musikstunde, vierte Betriebsart. Dieselben vier Wege wie die
    # Probierecke auf /projekt/musik/, aber an die Teilnahme gebunden.
    path("musik/", musik_views.musikseite, name="musik"),
    path("musik/stand/", musik_views.stand, name="musik_stand"),
    path("musik/lieder/", musik_views.liste, name="musik_liste"),
    path("musik/lied/", musik_views.lied, name="musik_lied"),
    # Der Textvorschlag vom Spark, nur wenn die Lehrperson ihn erlaubt hat.
    path("musik/text/", musik_views.text, name="musik_text"),
    path("musik/auftrag/<str:kennung>/", musik_views.auftrag, name="musik_auftrag"),
    path("musik/datei/<str:kennung>/", musik_views.datei, name="musik_datei"),
    # Der Safe Chat, fuenfte Betriebsart (Thomas, 23.10.2026): die Seite des
    # Kindes und der eine Endpunkt fuer einen Zug, am Spark oder draussen.
    path("safechat/", chat_views.chatseite, name="safechat"),
    path("safechat/zug/", chat_views.chat_zug, name="safechat_zug"),
    path("sitzung/nachfrage/<int:frage_id>/", views.nachfrage_beantworten,
         name="nachfrage_beantworten"),
]
