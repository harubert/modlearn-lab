"""Die Gegenprobe der Neutralitaetsprobe und die Zeit des Pfoertners.

Anlass (Siegen, 12.11.2026, Paper A): Stufe B mit einem zweiten Modell als
Pfoertner braucht drei Zahlen: wie oft fester Satz bei den heiklen Paaren,
wie viele Fehlsperren bei echten Fachfragen, und was der Pfoertner je
Anfrage kostet, Stufe A gegen Stufe B. gegenprobe.json traegt die
Fachfragen, --gegenprobe fragt nur den Pfoertner, und das Urteil traegt
seit heute seine eigene Dauer.
"""

import importlib.util
import pathlib

import pytest

PROJEKT = pathlib.Path(__file__).resolve().parents[2]
ORDNER = PROJEKT / "benchmark" / "neutralitaet"

# Das Abbild fuer den Server laesst benchmark/ weg (.dockerignore: Messlaeufe
# gehoeren ins Repo, nicht ins Abbild). Dort gibt es fuer diese Tests nichts
# zu laden; der erste Rollout mit ihnen (14.11.2026) scheiterte genau daran.
if not (ORDNER / "probe.py").exists():
    pytest.skip("benchmark/neutralitaet liegt nicht im Abbild", allow_module_level=True)


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("neutralitaet_probe_gegen", ORDNER / "probe.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _pf(dauer_ms=None, modell="ministral-3-8b", zur_stunde="nein"):
    return {"zur_stunde": zur_stunde, "grund": "anderes Wissensgebiet", "modell_gefragt": True,
            "modell": modell, "dauer_ms": dauer_ms, "roh": "", "ende": "", "lesbar": None}


def _zeile(nr, stelle, seite, pfoertner, messung=None, einordnung="satz"):
    return {"kennung": "T", "nr": nr, "stelle": stelle, "seite": seite, "frage": "?", "antwort": "x",
            "einordnung": einordnung, "verweigerung": "", "pfoertner": pfoertner,
            "messung": messung or {}, "dauer_s": 1.0, "fehler": ""}


def test_die_gegenprobe_hat_zehn_fachfragen_je_pfoertner_stelle(probe):
    fragen = probe.gegenprobe_laden()

    assert len(fragen) == 20
    assert {f["stelle"] for f in fragen} == set(probe.GEGENPROBE_STELLEN) == {"mathe", "sachunterricht"}
    assert len({f["nr"] for f in fragen}) == 20
    assert all(f["frage"].strip().endswith("?") for f in fragen)
    nur_mathe = probe.gegenprobe_laden(["mathe"])
    assert len(nur_mathe) == 10 and all(f["stelle"] == "mathe" for f in nur_mathe)


def test_das_urteil_traegt_modell_und_dauer_des_pfoertners(probe):
    urteil = probe.fachgrenze.Urteil("nein", "anderes Wissensgebiet",
                                     {"modell": "ministral-3-8b", "dauer_ms": 180, "tokens_ein": 400},
                                     modell_gefragt=True)

    assert probe._urteil(urteil) == _pf(180)


def test_die_gegenprobe_zaehlt_fehlsperren_je_stelle_und_den_median(probe):
    zeilen = [
        {"stelle": "mathe", "nr": 1, "fehlsperre": False, "fehler": "", "pfoertner": _pf(100, zur_stunde="ja")},
        {"stelle": "mathe", "nr": 2, "fehlsperre": True, "fehler": "", "pfoertner": _pf(300)},
        {"stelle": "sachunterricht", "nr": 11, "fehlsperre": False, "fehler": "", "pfoertner": _pf(200, zur_stunde="ja")},
        {"stelle": "sachunterricht", "nr": 12, "fehlsperre": False, "fehler": "RuntimeError", "pfoertner": None},
    ]
    a = probe.gegenprobe_auswerten(zeilen)

    assert a["fragen"] == 4 and a["fehlsperren"] == 1 and a["fehler"] == 1
    assert a["je_stelle"]["mathe"] == {"fragen": 2, "fehlsperren": 1, "fehler": 0, "gesperrt": [2]}
    assert a["je_stelle"]["sachunterricht"]["fehler"] == 1 and a["je_stelle"]["sachunterricht"]["gesperrt"] == []
    assert a["pfoertner_dauer_median_ms"] == 200 and a["pfoertner_modell"] == "ministral-3-8b"


def test_die_auswertung_nennt_den_median_des_pfoertners_auch_fuer_n1_zeilen(probe):
    zeilen = [
        _zeile(1, "mathe", "china", _pf(150)),
        _zeile(1, "mathe", "vergleich", _pf(250)),
        # Zeilen wie in N1: der Pfoertner ohne eigene Dauer, die Messung der Zeile ist seine.
        _zeile(2, "mathe", "china", {"zur_stunde": "nein", "grund": "", "modell_gefragt": True},
               {"modell": "qwen3.6-35b-a3b", "dauer_ms": 500}),
        _zeile(2, "mathe", "vergleich", {"zur_stunde": "nein", "grund": "", "modell_gefragt": True},
               {"modell": "qwen3.6-35b-a3b", "dauer_ms": 700}),
        # Ohne Pfoertner (roh): zaehlt nicht.
        _zeile(1, "roh", "china", None, {"modell": "qwen3.6-35b-a3b", "dauer_ms": 9000}, einordnung="beantwortet"),
    ]
    a = probe.auswerten(zeilen, ["mathe", "roh"])

    assert a["pfoertner_anzahl"] == {"mathe": 4}
    assert a["pfoertner_dauer_median_ms"] == {"mathe": 375}
    assert a["pfoertner_modell"] == "ministral-3-8b"
    md = probe.als_markdown("T", a, "qwen3.6-35b-a3b", ["mathe", "roh"], zeilen)
    assert "Pförtner ministral-3-8b, Median je Anfrage: mathe 375 ms (n = 4)." in md


def test_ohne_pfoertner_steht_kein_median_im_bericht(probe):
    zeilen = [_zeile(1, "roh", "china", None, {"dauer_ms": 100}, einordnung="beantwortet")]
    a = probe.auswerten(zeilen, ["roh"])

    assert a["pfoertner_anzahl"] == {} and a["pfoertner_modell"] == ""
    assert "Median je Anfrage" not in probe.als_markdown("T", a, "m", ["roh"], zeilen)


def test_mit_der_attrappe_laeuft_die_gegenprobe_ohne_netz(probe, tmp_path, capsys):
    attrappe = probe.Attrappe()
    vorher = probe.fachgrenze._anfragen
    probe.fachgrenze._anfragen = attrappe.pfoertner
    try:
        with open(tmp_path / "g.jsonl", "w", encoding="utf-8") as protokoll:
            zeilen = probe.gegenprobe_lauf("T", probe.gegenprobe_laden(["mathe"])[:2], protokoll)
    finally:
        probe.fachgrenze._anfragen = vorher

    # Die Attrappe sagt immer nein: Fuer die Gegenprobe ist das zweimal Fehlsperre.
    assert len(zeilen) == 2 and all(z["fehlsperre"] and not z["fehler"] for z in zeilen)
    assert all(z["pfoertner"]["zur_stunde"] == "nein" for z in zeilen)
    assert (tmp_path / "g.jsonl").read_text(encoding="utf-8").count("\n") == 2
    assert "FEHLSPERRE" in capsys.readouterr().out
    assert probe.gegenprobe_auswerten(zeilen)["fehlsperren"] == 2
