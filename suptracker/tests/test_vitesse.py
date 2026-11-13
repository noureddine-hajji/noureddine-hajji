"""Sprint Q3 (owner, 2026-11-13): speed of the map without changing one figure, through its red team (VT1-VT8) on the synthetic
warehouse and on the real one. The emulated-phone budget runs with `python scripts/redteam_vitesse.py --browser`."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("vitesse")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None,
                        onisep_sources={})


def test_red_team_on_synthetic(db):
    import redteam_vitesse as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_vitesse as R
    # the emulated-phone budget (VT6) is timing: it runs with --browser, not on shared CI runners
    checks = {fn.check_name.split()[0] for fn in R.CHECKS} - {"VT6"}
    failed = [r for r in R.run(REAL_DB, real=True, checks=checks) if not r["ok"]]
    assert not failed, failed
