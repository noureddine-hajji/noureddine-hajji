"""Évolution de la cohorte (owner, 2026-11-22): coloured charts, the student's mention and pair year by year, through their red
team. The browser check (EV9) runs in the nightly browser job (scripts/browser_nightly.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_colour_helpers():
    import redteam_evolution as R
    assert round(R.contrast("#ffffff", "#000000"), 1) == 21.0
    assert R.de("#d0475f", "#4f7a28", "deut") < 20 < R.de("#d0475f", "#4f7a28")      # red and green merge for a deuteranope
    assert R.combined(100, 80) >= 90 > R.combined(90, 80)


def test_literals_reader():
    import redteam_evolution as R
    assert R.literals('a(`x ${b ? `y` : "z"} w.`); "q"') == ["y", "z", "x  x  w.", "q"]


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("evolution")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_evolution as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_evolution as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
