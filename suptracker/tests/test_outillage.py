"""Lot 1, PR 9 (owner, 2026-11-26): Node programs through a file (nodefile.py) and the blast radius of a diff (blast.py),
through their red team."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_outillage as R
    failed = [r for r in R.run() if not r["ok"]]
    assert not failed, failed
