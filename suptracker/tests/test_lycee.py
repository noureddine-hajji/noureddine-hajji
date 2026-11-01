"""Sprint 4 lycée profile (IPS, IVAL, académie, same-lycée share, privacy) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("lycee")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None)


def test_latest_year_references_and_academie(db):
    c = duckdb.connect(str(db), read_only=True)
    rows = {u: (a, r, nat) for u, a, r, nat in c.execute("SELECT uai, academie, rentree, ips_national FROM ref.lycee").fetchall()}
    assert rows["0131234E"] == ("Aix-Marseille", "2025-2026", 130.0)     # private LEGT reference
    assert rows["9750001A"][0] is None                                     # no Parcoursup académie
    assert {s for (s,) in c.execute("SELECT DISTINCT session FROM ref.lycee_ival").fetchall()} == {2023, 2024, 2025}


def _has_lycees(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'ref' AND table_name = 'lycee'").fetchone()[0]
        con.close()
        return bool(n)
    except Exception:  # noqa: BLE001
        return False


def test_red_team_on_synthetic(db):
    import redteam_lycee as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and _has_lycees(REAL_DB)), reason="real warehouse without the sprint 4 tables")
def test_red_team_on_real_data():
    import redteam_lycee as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
