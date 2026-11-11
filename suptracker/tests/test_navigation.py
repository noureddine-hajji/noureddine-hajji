"""Sprint R1 (owner, 2026-11-11): the journey menus and the explained "Mon profil" page, through their red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_red_team_static():
    import redteam_navigation as R
    failed = [r for r in R.run(browser=False) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="no warehouse")
def test_red_team_browser():
    # U6 skips itself when node or Playwright is missing; with them, the profile flow and the menus run in a real browser
    import redteam_navigation as R
    res = {r["check"][:2]: r for r in R.run(browser=True)}
    assert res["U6"]["ok"], res["U6"]
