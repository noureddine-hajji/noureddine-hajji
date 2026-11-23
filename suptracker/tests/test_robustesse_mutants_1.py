"""Robustesse per formation, RF8 (the mutation test), part 1/3: a file of its own so the CI shards spread the parts
(2026-11-23: the whole red team in one file took a shard past its 45-minute limit)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_mutants_part_1():
    import redteam_robustesse_formations as R
    db = ROOT / "data" / "suptracker.duckdb"
    failed = [r for r in R.run(db if db.exists() else None, real=db.exists(), checks={"RF8"}, part=(1, 3)) if not r["ok"]]
    assert not failed, failed
