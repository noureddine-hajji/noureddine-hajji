"""Travel costs (owner, 2026-11-18): a round trip between the student's town and the formation, computed in the browser from
official open data (SNCF fares and stations, fuel prices); red team TR1-TR8, on crafted files and, when present, real data."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_transports as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
