#!/usr/bin/env python
"""Verwaltungswerkzeug von Django."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Für die Arbeit ausserhalb des Containers: .env laden, falls vorhanden.
load_dotenv(Path(__file__).resolve().parent / ".env")


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
