"""What the Parcoursup fiches write about specialties (owner, 2026-11-14): quoted sentences, required groups read by fixed rules
measured against hand-read sentences, the pair checked in the browser; red team EX1-EX8. With the committed warehouse, the
served groups are checked too."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_exigences as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
