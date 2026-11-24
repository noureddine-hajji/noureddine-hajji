"""Audit PR A (owner, 2026-11-24): every workflow that commits to the repository survives a concurrent push (scripts/
git_push_retry.sh, tried on real git repositories), through its red team."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_red_team():
    import redteam_enregistrement as R
    failed = [r for r in R.run() if not r["ok"]]
    assert not failed, failed
