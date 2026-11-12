"""Gemeinsame Vorkehrungen fuer alle Tests.

Der Pfoertner (tutoring/fachgrenze.py, 7.11.2026) fragt sonst ein Modell am
Spark, ob ein Beitrag zur Stunde gehoert. Im Test gibt es kein Netz; ohne
diese Vorkehrung bliebe jeder Aufruf bis zur Frist haengen. Deshalb kommt
hier kein Urteil zustande ("unklar"), und die Anwendung verhaelt sich wie
vor der Fachgrenze: Das Modell antwortet. Tests, die den Pfoertner selbst
pruefen, ersetzen fachgrenze.pruefen oder fachgrenze._anfragen.
"""

import pytest


@pytest.fixture(autouse=True)
def pfoertner_ohne_netz(monkeypatch):
    from tutoring import fachgrenze

    def _kein_netz(rumpf, adresse):
        raise RuntimeError("Im Test gibt es keinen Pfoertner am Netz.")

    monkeypatch.setattr(fachgrenze, "_anfragen", _kein_netz)
