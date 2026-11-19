"""The Observatoire page (owner, 2026-11-19): national trends, demand per académie, same-académie admits, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import observatoire as OBS  # noqa: E402
from synthetic import cached_build  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_fold_and_ratio():
    assert OBS.fold("Besançon") == OBS.fold("Besancon") == "besancon"
    assert OBS.fold("Nancy-Metz") == "nancy metz" and OBS.fold(None) == ""
    assert OBS.ratio(355366, 8802) == 40.4 and OBS.ratio(10, 0) is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("observatoire")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_observatoire as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        con.execute("SELECT acc_aca_orig, lat, lon, acad_mies FROM core.formation_year LIMIT 1")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_observatoire as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
