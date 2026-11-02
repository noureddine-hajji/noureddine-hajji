"""n+1 forecast (prevision): calibrated ranges of every published indicator with a history, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import prevision as PV  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("prevision")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None)


def test_bounds_and_errors():
    assert PV.bounds("effectif", 10.0, 0.0, 0.0) == (10.0, 10.0)        # an exact integer stays put
    lo, hi = PV.bounds("effectif", 100.0, -0.1, 0.1)
    assert (lo, hi) == (90, 111) and lo == int(lo)                   # 101 e^-0.1 - 1 = 90.4, 101 e^0.1 - 1 = 110.6
    assert PV.bounds("taux", 95.0, -5.0, 9.0) == (90.0, 100.0)            # rates clipped to [0, 100]
    assert abs(PV.error("effectif", 21, 10) - 0.6931471805599453) < 1e-12 and PV.error("taux", 30, 25) == 5


def test_tables_and_page_block(db):
    c = duckdb.connect(str(db), read_only=True)
    assert c.execute("SELECT DISTINCT target FROM mart.prevision").fetchall() == [(2026,)]
    assert c.execute("SELECT count(*) FROM mart.prevision WHERE lo > hi OR n_hist < 2").fetchone()[0] == 0
    cod = c.execute("SELECT cod_aff_form FROM mart.prevision WHERE indicator = 'acc_tot' LIMIT 1").fetchone()[0]
    b = PV.for_formation(c, cod, 2025)
    assert b["target"] == 2026 and any(i["indicator"] == "acc_tot" for i in b["indicators"])
    assert PV.for_formation(c, cod, 2024) is None                     # a past campaign's page gets no forecast


def _has_tables(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='mart' AND table_name='prevision'").fetchone()[0]
        con.close()
        return bool(n)
    except Exception:  # noqa: BLE001
        return False


def test_red_team_on_synthetic(db):
    import redteam_prevision as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and _has_tables(REAL_DB)), reason="real warehouse without the forecast tables")
def test_red_team_on_real_data():
    import redteam_prevision as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
