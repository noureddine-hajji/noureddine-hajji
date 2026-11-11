"""Sprint 20: bac techno and bac pro, "votre ligne" in a formation's public report, and its red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import voies as VO  # noqa: E402
from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_rules():
    assert VO.voie_key("bt", "Msgn/ Mercatique & Droit et Economie") == "stmg_merc"
    assert VO.voie_key("bt", "Autres doublettes", True) is None
    assert VO.bp_key("Bac pro Maintenance des matériels opt. a : agricoles") == VO.bp_key("Maintenance des matériels option a: agricoles")
    assert VO.bp_key("Accompagnement soins et services à la personne") != VO.bp_key(
        "Accompagnement, soins et services à la personne option b : « en structure »")


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("voies")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_voies as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_voies as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
