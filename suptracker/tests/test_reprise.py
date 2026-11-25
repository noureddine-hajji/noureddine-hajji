"""Audit PR 6 (owner, 2026-11-24): the reorientation journey, completed (the estimate on the search cards outside terminale, the
public services that help an adult, the hero's link, shorter sentences), through its red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("reprise")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_reprise as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_reprise as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=True) if not r["ok"]]
    assert not failed, failed
