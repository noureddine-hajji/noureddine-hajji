"""« Après le 1er juin » (owner, 2026-11-28, PR 19): what Parcoursup's answers mean, read from official pages, and the
complementary phase; through its red team.

AJ1, AJ4-AJ8 read the fetched calendar, app.js and the docs; AJ2 and AJ3 run on crafted rows (no warehouse is built), and on the
committed warehouse when it is there (the measured repeat, the routes)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_red_team():
    import redteam_apresjuin as R
    failed = [r for r in R.run(None) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_real():
    import redteam_apresjuin as R
    failed = [r for r in R.run(REAL_DB, real=True, checks={"AJ2", "AJ3"}) if not r["ok"]]
    assert not failed, failed
