"""Einstellungen der ModLearn-Aufgabenhilfe.

Alles Umgebungsabhängige kommt aus der Umgebung, nichts davon steht im Code.
Vorlage der Variablen: .env.example
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None, *, required=False):
    """Liest eine Umgebungsvariable, leere Werte gelten als nicht gesetzt."""
    value = os.environ.get(name, "").strip() or default
    if required and not value:
        raise ImproperlyConfigured(f"Umgebungsvariable {name} fehlt.")
    return value


def env_bool(name, default=False):
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "ja"}


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

# Im Entwicklungsbetrieb darf ein Wegwerfschlüssel einspringen, im Betrieb nie.
SECRET_KEY = env("DJANGO_SECRET_KEY", "unsicher-nur-fuer-die-entwicklung" if DEBUG else None,
                 required=not DEBUG)

# 127.0.0.1 ist für die Containerprüfung nötig, sie ruft /healthz über Loopback auf.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") + ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Der Admin kommt mit dem Planungswerkzeug dazu: Zugaenge und
    # Nutzerklassen legt eine Person im Lab an, nicht dreissig Lehrpersonen.
    # Eine eigene Oberflaeche dafuer waere Arbeit ohne Nutzen.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "tutoring",
    "plan",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# Der Zugang der Lehrperson laeuft ueber Djangos Auth-System.
LOGIN_URL = "anmelden"
LOGIN_REDIRECT_URL = "tutoring:lehrperson_uebersicht"
LOGOUT_REDIRECT_URL = "start"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "modlearn"),
        "USER": env("POSTGRES_USER", "modlearn"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "de-at"
TIME_ZONE = "Europe/Vienna"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Proxy, Transportsicherheit -------------------------------------------
# Caddy terminiert TLS und setzt X-Forwarded-Proto. Ohne diese Zeile hält
# Django jede Anfrage für unverschlüsselt und leitet endlos um.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
# /healthz prüft der Administrator und der Container über Loopback ohne TLS.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --- Grenzen ---------------------------------------------------------------
# Caddy begrenzt den Anfragekörper auf 20 MB, die App muss dieselbe Grenze
# selbst durchsetzen. Bilder kommen als Data-URL im JSON-Körper an, deshalb
# greift hier DATA_UPLOAD_MAX_MEMORY_SIZE und nicht die Datei-Grenze.
MAX_REQUEST_BYTES = 20 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_REQUEST_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_REQUEST_BYTES

# --- Zugang der Lehrperson -------------------------------------------------
# Ein einziges Konto fuer den Vortrag, angelegt aus der Umgebung. Bewusst
# ueber Djangos Auth-System und nicht ueber eine eigene Abfrage, damit M1
# spaeter echte Konten und Rollen darauf setzen kann.
TEACHER_USERNAME = env("TEACHER_USERNAME", "lehrperson")
TEACHER_PASSWORD = env("TEACHER_PASSWORD", "")

# --- Anmeldung ueber die PH (login.ph-vorarlberg.at, Microsoft Entra) ------
# Kein SAML und kein OIDC in Django: Caddy fragt per forward_auth bei der PH
# nach und reicht die angemeldete Person als X-Auth-Kopfzeilen durch. Damit
# diese Kopfzeilen etwas gelten, legt Caddy ein Geheimnis dazu, das nur Caddy
# und dieser Container kennen. Es steht in einer DATEI und nicht in der
# Umgebung: Umgebungsvariablen landen in 'docker inspect', in Fehlerseiten und
# in Kindprozessen, eine nur lesend eingebundene Datei nicht. Gelesen wird sie
# einmal je Prozess (core/ph.py). Fehlt sie, ist der Weg ueber das PH-Konto
# abgeschaltet und der Knopf auf der Anmeldeseite verschwindet.
PH_PROXY_SECRET_DATEI = env("PH_PROXY_SECRET_DATEI", "/run/geheim/lab-proxy")

# --- Sprachmodell auf dem Spark -------------------------------------------
SPARK_BASE_URL = env("SPARK_BASE_URL", "http://127.0.0.1:8000/v1")
# Seit 31.10.2026 serviert Port 8000 Qwen3.6-35B-A3B ohne Denkphase (Thomas,
# nach dem Modellvergleich der Siegen-Sitzung: 93 statt 84 Prozent bei
# gleicher Latenz). Der Name ist der served-model-name des vLLM-Containers.
SPARK_MODEL = env("SPARK_MODEL", "qwen3.6-35b-a3b")
SPARK_TIMEOUT_SECONDS = int(env("SPARK_TIMEOUT_SECONDS", "60"))
SPARK_RETRIES = int(env("SPARK_RETRIES", "1"))

# --- Spracherkennung am Spark ---------------------------------------------
# Fehlt die Adresse, ist der Mikrofonknopf sichtbar abgeschaltet statt kaputt.
# Derselbe Umgang wie beim Cloud-Schalter.
SPARK_AUDIO_BASE_URL = env("SPARK_AUDIO_BASE_URL", "")
SPARK_AUDIO_MODEL = env("SPARK_AUDIO_MODEL", "whisper-large-v3")
SPARK_AUDIO_TIMEOUT_SECONDS = int(env("SPARK_AUDIO_TIMEOUT_SECONDS", "60"))
SPRACHEINGABE_MOEGLICH = bool(SPARK_AUDIO_BASE_URL)

# --- Zuschaltbare Cloud-Hilfe (Privacy Shield, Abschnitt 3a) ---------------
# Fehlt der Schlüssel, bleibt der Schalter sichtbar, sendet aber nichts.
CLOUD_BASE_URL = env("CLOUD_BASE_URL", "https://api.openai.com/v1")
CLOUD_MODEL = env("CLOUD_MODEL", "")
CLOUD_API_KEY = env("CLOUD_API_KEY", "")
CLOUD_PROVIDER = env("CLOUD_PROVIDER", "openai")
CLOUD_ENABLED = bool(CLOUD_API_KEY and CLOUD_MODEL)
# Eigene Frist: Der Weg nach draussen geht ueber das Internet und hat
# andere Zeiten als der Spark im eigenen Netz.
CLOUD_TIMEOUT_SECONDS = float(env("CLOUD_TIMEOUT_SECONDS", "45"))

# Die Protokollstufe (CLAUDE.md 3b) ist seit 1.11.2026 eine feste Einstellung
# des Servers, keine Wahl im Formular (Thomas: Spark und Server stehen im
# Haus, genutzt wird das Lab nur von Uebungsschule und PH, die Wahl
# verkomplizierte den Ablauf). Stufe 3: die Originaltexte; fuer die
# Forschung werden sie vor der Auswertung anonymisiert. Fuer externe
# Schulen laesst sich PROTOKOLLSTUFE=1 setzen (nur Zahlen) oder die Wahl mit
# PROTOKOLLSTUFE_WAEHLBAR=1 wieder ins Formular holen.
PROTOKOLLSTUFE = int(env("PROTOKOLLSTUFE", "3"))
PROTOKOLLSTUFE_WAEHLBAR = env_bool("PROTOKOLLSTUFE_WAEHLBAR", False)

# --- Wie viele Plaetze hat der Spark? --------------------------------------
#
# Ein Platz ist eine Person, die zur selben Zeit arbeitet - nicht eine
# gleichzeitige Anfrage. Der Unterschied ist gross: Eine Anfrage dauert rund
# vier Sekunden, und niemand drueckt pausenlos. Fuenfundzwanzig Kinder
# erzeugen im Schnitt gut EINE gleichzeitige Anfrage.
#
# Gemessen ist Folgendes:
#   - 50 gleichzeitige Anfragen, langsamste Antwort 6,4 s, null Ausfaelle.
#   - Im Betrieb ueber zehn Tage lag die hoechste echte Gleichzeitigkeit
#     bei DREI, einschliesslich einer Vorfuehrung mit 28 Leuten im Raum.
#
# Daraus die Zahl unten: Nimmt man an, dass im schlimmsten Fall ein Drittel
# einer gebuchten Gruppe gleichzeitig drueckt, traegt die gemessene Kapazitaet
# rund 150 Personen. Hier steht bewusst weniger, weil ueber 50 gleichzeitige
# Anfragen hinaus nichts gemessen ist und eine Zahl jenseits der Messung
# geraten waere.
#
# Der Rueckblick unter /plan/rueckblick/ stellt Buchung und gemessene Spitze
# nebeneinander. Diese Zahl gehoert korrigiert, sobald er etwas anderes sagt.
SPARK_PLAETZE = int(env("SPARK_PLAETZE", "120"))

# Welche Modelle ohne Umbau gleichzeitig im Speicher liegen, mit Komma
# getrennt. Beobachtet am 04.10.2026: Port 8000 liefert qwen3-vl-30b, Port
# 8002 whisper-large-v3 - also ein grosses und ein kleines Modell nebeneinander.
#
# Wie viel daneben noch frei ist, ist NICHT gemessen. Deshalb steht hier nur
# das Beobachtete. Jede Buchung, deren Nutzungskonzept mehr braucht, belegt
# den Spark allein; das ist die vorsichtige Richtung. Siehe plan/konzepte.py.
SPARK_GELADENE_MODELLE = env("SPARK_GELADENE_MODELLE", "text,gehoer")

# --- Preise und Budgetwaechter (Abschnitt 3b) ------------------------------
# Preise in Euro je einer Million Token, getrennt nach Ein- und Ausgang.
# Bewusst aus der Umgebung: Preise aendern sich, der Code nicht.
# Format: {"modellname": {"ein": 0.25, "aus": 2.00}}
import json as _json  # noqa: E402

_preise_roh = env("CLOUD_PREISE", "")
try:
    CLOUD_PREISE = _json.loads(_preise_roh) if _preise_roh else {}
except ValueError:
    CLOUD_PREISE = {}

# Harte Obergrenzen. Erreicht heisst: der Cloud-Weg ist gesperrt und das
# steht sichtbar da, statt still weiter Geld auszugeben.
BUDGET_JE_SITZUNG_EURO = float(env("BUDGET_JE_SITZUNG_EURO", "1.00"))
BUDGET_JE_TAG_EURO = float(env("BUDGET_JE_TAG_EURO", "3.00"))

# Zusaetzlich eine Zaehlung der Aufrufe. Sie wirkt auch dann, wenn keine
# Preise hinterlegt sind - und das ist der Normalfall, weil Preise sich
# haeufiger aendern als diese Datei. Ein Waechter, der nur bei bekannten
# Preisen greift, ist bei unbekannten Preisen gar keiner.
CLOUD_AUFRUFE_JE_SITZUNG = int(env("CLOUD_AUFRUFE_JE_SITZUNG", "60"))
CLOUD_AUFRUFE_JE_TAG = int(env("CLOUD_AUFRUFE_JE_TAG", "300"))

# --- Protokollierung -------------------------------------------------------
# Keine Inhalte in Protokollen. Der Zugriffs-Protokollant von uvicorn ist
# ausgeschaltet, weil Sitzungscodes in Adressen stehen.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"knapp": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "knapp"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

# --- Der Modell-Broker am Spark ----------------------------------------------
# Port 8010, nur im Tailnet. Er ist die eine Stelle, die weiss, was im
# Speicher liegt; SPARK_GELADENE_MODELLE und SPARK_PROFIL sind nur die
# Rueckfallebene, solange kein Geheimnis liegt oder der Broker nicht antwortet.
# Das Geheimnis kommt aus einer Datei, nie aus der Umgebung - wie bei der
# PH-Anmeldung. Fehlt sie, gibt es keinen Broker, und zwar still.
SPARK_BROKER_URL = env("SPARK_BROKER_URL", "http://127.0.0.1:8010")
SPARK_BROKER_SECRET_DATEI = env("SPARK_BROKER_SECRET_DATEI", "/run/geheim/spark-broker")
SPARK_PROFIL = env("SPARK_PROFIL", "qwen")

# --- Der Musikdienst am Spark ------------------------------------------------
# Port 8011, nur im Tailnet: ACE-Step 1.5 hinter ComfyUI, von der
# Spark-Betreuung am 12.10.2026 aufgesetzt. Dasselbe Geheimnis wie beim
# Broker (SPARK_BROKER_SECRET_DATEI), deshalb keine eigene Datei. Der Browser
# spricht den Dienst nie an; die Testecke unter /labor/musik/ reicht durch.
MUSIK_URL = env("MUSIK_URL", "http://127.0.0.1:8011")
