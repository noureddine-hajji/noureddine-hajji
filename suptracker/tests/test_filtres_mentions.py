"""Lighter mention filter (owner, 2026-11-21): professional titles by NSF domain, options and BPJEPS mentions grouped, acronym
prefixes out of group names, a double licence under each of its disciplines, through its red team (real warehouse when present)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_filtres_mentions as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db, real=db.exists()) if not r["ok"]]
    assert not failed, failed
