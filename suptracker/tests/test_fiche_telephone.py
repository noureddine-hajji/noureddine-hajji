"""Audit PR 5 (owner, 2026-11-24): a shorter formation page on a phone (the jobs first in « Emploi », links that land on their
card, « Compléter ma liste » under its alert, « i » buttons tappable on 44 px), through its red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_red_team_static():
    import redteam_fiche_telephone as R
    failed = [r for r in R.run(REAL_DB) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_fiche_telephone as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=True) if not r["ok"]]
    assert not failed, failed
