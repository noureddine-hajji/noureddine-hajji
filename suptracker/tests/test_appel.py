"""Comprendre l'appel and the vraie sélectivité matrix (prepare the choice of vœux; no rank asked), and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import appel as AP  # noqa: E402
from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_depth_reads_the_whole_list_never_above_100():
    assert AP.depth(740 + 108, 848) == (1.0, True)
    assert AP.depth(900, 848) == (1.0, True)
    assert AP.depth(424, 848) == (0.5, False)
    assert AP.depth(None, 848) == (None, False) and AP.depth(10, 0) == (None, False)


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("appel")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_appel as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        con.execute("SELECT ran_grp1, nb_cla_pp, pct_tbf FROM core.formation_year LIMIT 1")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_appel as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
