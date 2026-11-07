"""UI lot 1 (audience 16-20 ans, téléphone d'abord): tutoiement, no column names, bottom bar, 44 px touch targets,
folded search filters, the three-door home page; its red team (the browser check runs with --browser)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team_static():
    import redteam_ux as R
    failed = [r for r in R.run(browser=False) if not r["ok"]]
    assert not failed, failed
