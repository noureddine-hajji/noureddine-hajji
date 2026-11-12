"""Sprint R7 (owner, 2026-11-12): "Construire ma liste", the five steps of the site, through its red team (no warehouse needed)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_guide as R
    failed = [r for r in R.run(ROOT / "data" / "suptracker.duckdb") if not r["ok"]]
    assert not failed, failed
