"""Qui sont les admis ? (néo-bacheliers and other admits, owner 2026-11-10): the rule and the red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import admis as ADM  # noqa: E402
from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_rule():
    assert ADM.autres_majoritaires(28, 6, 22)                 # BUT Science des données, Carcassonne, 2025
    assert not ADM.autres_majoritaires(10, 5, 5)              # a tie is not a majority
    assert not ADM.autres_majoritaires(9, 2, 7)               # fewer than 10 admits
    assert not ADM.autres_majoritaires(12, 3, 8)              # the counts miss the total
    assert ADM.repartition({"acc_tot": 0, "acc_neobac": 0, "acc_at": 0}) is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("admis")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_admis as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_admis as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
