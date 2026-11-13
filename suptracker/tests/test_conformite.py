"""Sprint Q1 (owner, 2026-11-13): trust and compliance pages and the contact form, through their red team (QC1-QC11). The
browser check runs with `python scripts/redteam_conformite.py --browser`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_conformite as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None) if not r["ok"]]
    assert not failed, failed
