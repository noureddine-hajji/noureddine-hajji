"""Sprint F (owner, 2026-11-15): financing one's studies, the student aids read from the official pages (bourse per échelon,
aide au mérite, aide à la mobilité Parcoursup, fee and CVEC exemptions, Crous meal, housing aid) in the cost tab; red team AI1-AI8."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_aides as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists()) if not r["ok"]]
    assert not failed, failed
