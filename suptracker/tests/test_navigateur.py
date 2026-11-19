"""The nightly browser checks (owner, 2026-11-19): their runner and their workflow, through their red team (BN1-BN5).
The browser checks themselves run every night in .github/workflows/suptracker-browser.yml, not here (no browser in CI)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_navigateur as R
    failed = [r for r in R.run() if not r["ok"]]
    assert not failed, failed
