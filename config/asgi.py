"""ASGI-Einstieg. Das Streaming der Modellantworten braucht ASGI, nicht WSGI."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
