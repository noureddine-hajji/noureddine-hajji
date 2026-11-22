"""Neo Brutalism design (owner, 2026-11-22): the design red team. Static checks and their mutation test run everywhere; the
browser measurement (DE8) runs in the nightly browser job (scripts/browser_nightly.py)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_contrast_and_combined_score():
    import redteam_design as R
    assert round(R.contrast("#ffffff", "#000000"), 1) == 21.0
    assert R.combined(100, 82) >= 90 > R.combined(100, 74)


def test_shadow_blur_reader():
    import redteam_design as R
    assert R.shadow_blur("4px 4px 0 var(--edge)") == []
    assert R.shadow_blur("inset 0 0 0 2px var(--ink)") == []
    assert R.shadow_blur("0 6px 18px var(--edge)")


def test_red_team_static():
    import redteam_design as R
    failed = [r for r in R.run(REAL_DB) if not r["ok"]]
    assert not failed, failed
