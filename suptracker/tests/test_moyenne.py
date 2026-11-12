"""Sprint R5 (owner, 2026-11-12): the continuous average inside the mention band, through its red team."""
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
    from suptracker import journey as J
    assert [J.band_of(g) for g in (8, 9.9, 10, 12, 14, 16, 18, 20)] == ["sansmention"] * 3 + ["ab", "b", "tb", "tbf", "tbf"]
    assert J.within(None, "ab") == 1.0 and J.within(12, "ab") == 0.0 and abs(J.within(13, "ab") - 0.5) < 1e-12
    assert J.resolve_mention("rattrapage", None) == ("sansmention", 10.0)
    with pytest.raises(ValueError):
        J.resolve_mention("b", 12.4)


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("moyenne")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_moyenne as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_moyenne as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=True) if not r["ok"]]
    assert not failed, failed
