"""Parcoursup fiches (owner, 2026-11-13): the evaluation grids (weights, criteria and importance) and the expected skills read
on the live fiches, through their red team (GR1-GR9). With the committed warehouse, the harvested grids are checked too."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_grilles as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
