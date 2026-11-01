#!/bin/sh
# Startet die Anwendung: warten, wandern, dann der Webserver.
set -e

# Beim Neustart des Servers haelt Docker die Reihenfolge aus depends_on NICHT
# ein, die gilt nur fuer "docker compose up". Die Anwendung kann also vor der
# Datenbank hochkommen. Ohne dieses Warten scheitert die Wanderung, der
# Container faellt um und wird neu gestartet, bis es zufaellig passt. Das
# funktioniert zwar, sieht aber im Protokoll wie ein Ausfall aus.
echo "Warte auf die Datenbank ..."
python - <<'PY'
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connections
from django.db.utils import OperationalError

FRIST = 120
ABSTAND = 2

for verstrichen in range(0, FRIST, ABSTAND):
    try:
        connections["default"].cursor().close()
    except OperationalError:
        time.sleep(ABSTAND)
    else:
        print(f"Datenbank nach {verstrichen} s erreichbar.")
        sys.exit(0)

print(f"Datenbank auch nach {FRIST} s nicht erreichbar.", file=sys.stderr)
sys.exit(1)
PY

echo "Datenbankwanderungen werden angewendet ..."
python manage.py migrate --noinput

echo "Zugang der Lehrperson wird abgeglichen ..."
python manage.py lehrperson_anlegen

# Der Zugriffs-Protokollant bleibt aus: Sitzungscodes stehen in den Adressen,
# und Protokolle ohne Inhalte sind eine Vorgabe des Projekts.
exec uvicorn config.asgi:application \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-2}" \
    --no-access-log \
    --timeout-keep-alive 65 \
    --proxy-headers \
    --forwarded-allow-ips '*'
