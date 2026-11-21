"""Sprint 3 (owner, 2026-11-21): « Solidité avant le pic », through its red team (real warehouse when present)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_solidite as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db, real=db.exists()) if not r["ok"]]
    assert not failed, failed
