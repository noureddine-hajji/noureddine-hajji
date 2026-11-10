"""Sprint 14: employment to 2030 (Dares / France Stratégie, "Les métiers en 2030") and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import emploi2030 as E  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
HAVE_SOURCE = E.source_path() is not None


def test_reading_rule():
    assert E.reading(1, 5) == "debutants_insuffisants" and E.reading(-5, -1) == "debutants_nombreux"
    assert E.reading(-1, 2) == "incertain" and E.reading(0, 2) == "incertain" and E.reading(None, 2) is None


def test_empty_build_is_safe():
    con = duckdb.connect(":memory:")
    assert E.build(con, None)["familles"] == 0
    assert E.for_codes(con, [{"rome": "M1805", "fap2009": [{"fap87": "M1Z", "code": "M1Z80", "qualifications": {"codes": [7]}}]}])[0]["absent"]


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("m2030")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)


@pytest.mark.skipif(not HAVE_SOURCE, reason="the Métiers 2030 workbook is not in data/sources")
def test_red_team_on_synthetic(syn):
    import redteam_emploi2030 as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.m2030_famille").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the sprint-14 table")
def test_red_team_on_real_data():
    import redteam_emploi2030 as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
