"""Sprint V2 (owner, 2026-11-15): bac techno and bac pro and apprenticeship merged into the pages (demand per place, the
apprenticeship card and the BTS route comparison), the distance from the student's town, the CAES; red team VP1-VP8."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_voiepro as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
