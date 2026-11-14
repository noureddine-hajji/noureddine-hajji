"""From each job to its first formations on Parcoursup (owner, 2026-11-14): routes through Onisep's continuations and the
official family rules, coverage >= 80 %, entries ranked by places; red team PA1-PA8 (built on a copy of the warehouse)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_parcours as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
