"""Sprint Q5 (owner, 2026-11-13): the home's one main action, the formation page on a phone (sticky tabs) and the screen-reader
reading, through their red team (MB1-MB8). The browser checks run on the committed warehouse when it is present."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_mobile as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
