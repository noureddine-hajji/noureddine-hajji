"""Sprint Q4 (owner, 2026-11-13): plain language and human help, through their red team (LA1-LA8). The browser check runs
with `python scripts/redteam_langage.py --browser`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_langage as R
    failed = [r for r in R.run() if not r["ok"]]
    assert not failed, failed
