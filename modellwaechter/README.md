# Modellwächter

Fragt einmal am Tag die Register nach neuen KI-Modellen und Versionen, hält
fest, was neu ist, lässt das Modell am Spark die Modellkarte in drei Sätzen
zusammenfassen und meldet das Ergebnis: auf der Seite
`/lehrperson/modelle/` (für staff und Lab-Profile) und, sobald ein
Mailserver eingetragen ist, per E-Mail.

Anlass (Thomas, 12.11.2026): „regelmäßig prüft, was für neue Modelle es
gibt, und uns darauf hinweist ... am Server automatisch“.

## Die Quellen

Kein Scraping; alle vier antworten per JSON.

| Quelle | Was | Einstellung |
|---|---|---|
| Hugging Face | die Modelle je Hersteller, zuletzt geänderte zuerst; Lizenz und Aufgabe aus den Tags | `MODELLWAECHTER_HF_AUTOREN` (Hersteller mit Komma) |
| OpenRouter | alle großen Anbieter mit Datum, Eingängen und Preis; die Sammelquelle für Frontier-Modelle, auch Anthropic und Google | `MODELLWAECHTER_OPENROUTER` |
| GitHub-Releases | die Versionen von vLLM: Ein neues Modell nützt erst, wenn vLLM es fährt | `MODELLWAECHTER_GITHUB_REPOS` |
| OpenAI-Konto | die Modelle, die unser Schlüssel nutzen darf: die Kandidaten für `CLOUD_MODEL` | `MODELLWAECHTER_OPENAI_KONTO`, braucht `CLOUD_API_KEY` |

Der erste erfolgreiche Lauf einer Quelle legt den **Grundbestand** an;
alles, was es da schon gibt, zählt nicht als neu. Danach ist neu, was die
Quelle zum ersten Mal zeigt (Kennung je Quelle). Eine Quelle ohne Antwort
bekommt einen Lauf mit der Fehlerart und hält die anderen nicht auf.

Der Schlüssel des OpenAI-Kontos steht nur im Kopf der Anfrage; in Läufen,
Funden, Meldungen und Protokollen steht er nie.

## Die Einordnung

Das Finden ist deterministisch. Der Spark hilft beim Lesen: Für die neuesten
Funde (höchstens `MODELLWAECHTER_EINORDNUNGEN_JE_LAUF`, Vorgabe 10) holt der
Wächter die Modellkarte (Hugging Face) oder die Beschreibung der Quelle und
lässt das Modell am Spark in drei Sätzen sagen, was das ist, wie groß, unter
welcher Lizenz, mit welchen Eingängen, und ob es nach diesen Angaben auf ein
Gerät mit 128 GB passt. Die Seite nennt dazu das Modell, das den Text
geschrieben hat; es ist eine Zusammenfassung fremden Textes, kein Urteil.
Fällt der Spark aus, bleibt die Einordnung leer, der Fund steht trotzdem da.

## Der Befehl

    python manage.py modelle_pruefen
    python manage.py modelle_pruefen --nur huggingface:Qwen,github
    python manage.py modelle_pruefen --ohne-einordnung --ohne-mail
    python manage.py modelle_pruefen --einordnen 3

## Der Zeitplan am Server

Ein systemd-Timer auf dem Rechner, der die Container fährt; der Befehl läuft
im laufenden Web-Container, der die `.env` und den Schlüssel schon hat.

`/etc/systemd/system/modlearn-modelle.service`:

    [Unit]
    Description=ModLearn: neue KI-Modelle pruefen
    After=docker.service
    Requires=docker.service

    [Service]
    Type=oneshot
    User=modlearn
    WorkingDirectory=/pfad/zur/anwendung    # das Verzeichnis mit docker-compose.yml
    ExecStart=/usr/bin/docker compose exec -T web python manage.py modelle_pruefen

`/etc/systemd/system/modlearn-modelle.timer`:

    [Unit]
    Description=ModLearn: neue KI-Modelle pruefen, taeglich

    [Timer]
    OnCalendar=*-*-* 06:30
    RandomizedDelaySec=15min
    Persistent=true

    [Install]
    WantedBy=timers.target

Dann `systemctl daemon-reload && systemctl enable --now modlearn-modelle.timer`;
Probe mit `systemctl start modlearn-modelle.service && journalctl -u modlearn-modelle -n 30`.

## E-Mail

Django schickt mit `send_mail`, sobald in der `.env` ein Mailserver steht:

    EMAIL_HOST=smtp.example.org
    EMAIL_PORT=587
    EMAIL_HOST_USER=
    EMAIL_HOST_PASSWORD=
    EMAIL_USE_TLS=1
    DEFAULT_FROM_EMAIL=lab@example.org
    MODELLWAECHTER_EMPFAENGER=eine@example.org,zwei@example.org

Ohne `EMAIL_HOST`, Absender oder Empfänger geht nichts hinaus, und die Seite
sagt das. Eine Meldung je Lauf mit allem Neuen, keine Mail ohne Neues.
