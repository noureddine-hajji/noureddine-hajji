"""Sprint R8 (owner, 2026-11-12): accessibility, WCAG 2.1 AA, through its red team (static checks; the browser check runs with --browser)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_a11y as R
    failed = [r for r in R.run(ROOT / "data" / "suptracker.duckdb") if not r["ok"]]
    assert not failed, failed
