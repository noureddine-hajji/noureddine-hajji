"""Sprint 21, "Je me réoriente ou je reprends mes études": the rule and the red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import reorientation as RO  # noqa: E402
from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_rule():
    b = RO.block({"nb_voe_pp": 100, "prop_tot": 50, "taux_acces_ens": 60, "nb_voe_pp_bg": 60, "prop_tot_bg": 40})
    assert (b["candidats"], b["propositions"], b["acces_estime"]) == (40, 10, 30.0)
    assert RO.block({"nb_voe_pp": 100, "prop_tot": 30, "taux_acces_ens": 60, "nb_voe_pp_bg": 50, "prop_tot_bg": 31})["candidats"] is None
    assert RO.block({"nb_voe_pp": 60, "prop_tot": 50, "taux_acces_ens": 60, "nb_voe_pp_bg": 41, "prop_tot_bg": 40})["acces_estime"] is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("reorientation")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_reorientation as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_reorientation as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
