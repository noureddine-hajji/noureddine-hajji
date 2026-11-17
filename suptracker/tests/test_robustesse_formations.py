"""Robustesse 2035 per formation (owner, 2026-11-17): outlets, skills (RNCP x ROME 4.0), insertion, a repère within the filière;
red team RF1-RF8."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_robustesse_formations as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
