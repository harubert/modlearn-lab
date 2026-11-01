"""Test settings: SQLite in memory instead of PostgreSQL, no static-files manifest.

    DJANGO_SECRET_KEY=x python -m pytest --ds=config.settings_test

Everything else is the production configuration from settings.py.
"""

from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# No manifest: there is no collectstatic in a test run. Tests therefore check
# script names without the hashed suffix.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
