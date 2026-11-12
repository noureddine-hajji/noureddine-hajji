"""Sprint R3 (owner, 2026-11-12): the advanced filters shared by the search and the map, through their red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_bands():
    from suptracker import filtres as FI
    assert [FI.band(x, FI.CAPACITE) for x in (None, 0, 19, 20, 49, 50, 99, 100)] == [None, "moins20", "moins20", "20a49", "20a49", "50a99", "50a99", "100plus"]
    assert [FI.band(x, FI.TAUX) for x in (29.9, 30, 59.9, 60, 89.9, 90, 100)] == ["moins30", "30a59", "30a59", "60a89", "60a89", "90plus", "90plus"]
    with pytest.raises(ValueError):
        FI.parse("nope", "taux")


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("filtres")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_filtres as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_filtres as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=True) if not r["ok"]]
    assert not failed, failed
