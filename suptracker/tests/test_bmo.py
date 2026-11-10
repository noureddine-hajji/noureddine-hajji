"""Sprint 14 follow-up: BMO 2026 short-term hiring context and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import bmo as B  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_share_bounds():
    s, lo, hi = B.share_bounds(50, 100, 2, 3)        # 50 difficult of 100; 2 masked difficult cells, 3 masked project cells
    assert s == 0.5 and lo == 50 / 112 and hi == 58 / 100
    assert B.share_bounds(0, 0, 0, 0) == (None, None, None) and B.share_bounds(99, 100, 5, 0)[2] == 1.0


def test_empty_build_is_safe():
    con = duckdb.connect(":memory:")
    assert B.build(con, None)["codes"] == 0
    assert B.for_codes(con, []) is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("bmo")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)


@pytest.mark.skipif(B.source_path() is None, reason="the BMO workbook is not in data/sources")
def test_red_team_on_synthetic(syn):
    import redteam_bmo as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.bmo_metier").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the BMO table")
def test_red_team_on_real_data():
    import redteam_bmo as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
