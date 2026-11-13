"""Fragt die Modellregister nach Neuem, laesst es einordnen und meldet es.

Gedacht fuer einen Zeitplan am Server, einmal am Tag (systemd-Timer, siehe
modellwaechter/README.md). Von Hand:

  python manage.py modelle_pruefen
  python manage.py modelle_pruefen --nur huggingface:Qwen,github
  python manage.py modelle_pruefen --ohne-einordnung --ohne-mail
"""

from django.core.management.base import BaseCommand

from modellwaechter import pruefen


class Command(BaseCommand):
    help = "Fragt Hugging Face, OpenRouter, GitHub und das OpenAI-Konto nach neuen Modellen."

    def add_arguments(self, parser):
        parser.add_argument("--nur", default="",
                            help="Quellen, mit Komma: huggingface, huggingface:Qwen, openrouter, github, openai")
        parser.add_argument("--ohne-einordnung", action="store_true",
                            help="keine Zusammenfassung durch den Spark")
        parser.add_argument("--ohne-mail", action="store_true", help="keine E-Mail, nur die Seite")
        parser.add_argument("--einordnen", type=int, default=None,
                            help="höchstens so viele Funde einordnen lassen")

    def handle(self, *args, **optionen):
        nur = {t.strip() for t in optionen["nur"].split(",") if t.strip()} or None
        neue, laeufe = pruefen.durchlauf(nur=nur)
        for lauf in laeufe:
            if lauf.ergebnis == lauf.OK:
                stand = "Grundbestand" if lauf.grundbestand else f"{lauf.neu} neu"
                self.stdout.write(f"{lauf.quelle} {lauf.anbieter}: {lauf.gesehen} gesehen, {stand}, {lauf.dauer_ms} ms")
            else:
                self.stdout.write(f"{lauf.quelle} {lauf.anbieter}: ohne Antwort ({lauf.fehlerart})")
        eingeordnet = 0
        if neue and not optionen["ohne_einordnung"]:
            eingeordnet = pruefen.einordnen(neue, optionen["einordnen"])
        gemeldet = False
        if neue and not optionen["ohne_mail"]:
            gemeldet = pruefen.melden(neue)
        self.stdout.write(
            f"{len(neue)} neu, {eingeordnet} eingeordnet, "
            + ("E-Mail verschickt." if gemeldet else
               "keine E-Mail" + ("" if pruefen.mail_moeglich() else " (nicht eingerichtet)") + ".")
        )
