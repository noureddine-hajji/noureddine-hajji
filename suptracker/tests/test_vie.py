"""Étudier là-bas (sprint V1, owner 2026-11-15): the State-label badge read on each live fiche and the cost of a year of study
(local rent and Crous, national OVE items, the fiche's fees); red team V1-V9."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_vie as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
