"""Préparer son projet motivé: the jury's points (crafted texts, the real warehouse when present), and the red team."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import projet as PJ  # noqa: E402
from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_points_are_verbatim_and_ordered_by_importance():
    t = {"criteres": [{"champ": "A", "critere": "Notes", "elements": "Bulletins", "importance": "Essentiel"},
                      {"champ": "B", "critere": "Motivation", "elements": "Lettre de motivation", "importance": "Important"},
                      {"champ": "C", "critere": "Projet", "elements": "Projet de formation motivé", "importance": "Essentiel"}],
         "eliminatoires": "Moyenne < 8\nPas de projet motivé", "conseils": " Lisez les attendus. "}
    r = PJ.checklist(t)
    assert [p["critere"] for p in r["points"]] == ["Projet", "Motivation"]
    assert r["autres_criteres"] == 1 and r["eliminatoires"] == ["Pas de projet motivé"] and r["conseils"] == "Lisez les attendus."
    assert PJ.checklist({"criteres": []}) is None and PJ.checklist(None) is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("projet")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_projet as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    """The real warehouse, built with the similar formations' projet counts (mart.semblable_jury carries 'projet')."""
    try:
        con = duckdb.connect(str(path), read_only=True)
        row = con.execute("SELECT data FROM mart.semblable_jury LIMIT 1").fetchone()
        con.close()
        return bool(row) and "projet" in json.loads(row[0])
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available or not rebuilt yet")
def test_red_team_on_real_data():
    import redteam_projet as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
