"""Journées portes ouvertes (owner, 2026-11-16): the establishment's open days of the season (1 September - 1 May) from Onisep,
checked on the establishment's own site, else a period from past seasons (« aux alentours de mi-janvier »); red team J1-J10."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_jpo as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
