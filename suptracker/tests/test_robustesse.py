"""Robustesse 2035 per job (owner's PRD, 2026-11-16): an estimation of the model on each job page, the median of three scenarios
with the range, its components, its confidence and its sources; red team RB1-RB8."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_robustesse as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
