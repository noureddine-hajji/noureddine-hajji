"""« Transférer sur mon autre appareil » and the teacher kit (owner, 2026-11-27, PR 17); through its red team.

TF1-TF6, TF8 and TF9 read app.js, the vendored QR encoder and the docs only: no warehouse is built. TF7 (browser) runs on the
real warehouse, nightly (it skips without node or Playwright)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_red_team():
    import redteam_transfert as R
    failed = [r for r in R.run(REAL_DB) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_browser():
    import redteam_transfert as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=True, checks={"TF7"}) if not r["ok"]]
    assert not failed, failed
