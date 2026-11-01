"""Sprint 5: next-campaign "repère" (calibrated ranges, back-tested on a hold-out year) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import calibration as C  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("calibration")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None)


def test_quantile_matches_numpy():
    import numpy as np
    xs = [3.0, -1.0, 7.5, 2.0, 0.0, 11.0]
    for q in (0.1, 0.5, 0.9):
        assert abs(C.quantile(xs, q) - float(np.percentile(xs, 100 * q))) < 1e-12


def test_tables_on_synthetic(db):
    c = duckdb.connect(str(db), read_only=True)
    phases = {p for (p,) in c.execute("SELECT DISTINCT phase FROM mart.calibration_report").fetchall()}
    assert {"holdout", "serving", "predictor"} <= phases
    assert c.execute("SELECT DISTINCT target FROM mart.forecast").fetchall() == [(2026,)]
    assert c.execute("SELECT count(*) FROM mart.forecast WHERE taux_lo > taux_hat OR taux_hi < taux_hat").fetchone()[0] == 0


def _has_tables(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='mart' AND table_name='forecast'").fetchone()[0]
        con.close()
        return bool(n)
    except Exception:  # noqa: BLE001
        return False


def test_red_team_on_synthetic(db):
    import redteam_calibration as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and _has_tables(REAL_DB)), reason="real warehouse without the sprint 5 tables")
def test_red_team_on_real_data():
    import redteam_calibration as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
