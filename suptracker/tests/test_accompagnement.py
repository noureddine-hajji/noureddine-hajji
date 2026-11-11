"""Sprint 22, accompaniment: the official calendar and the red team."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import calendrier as CAL  # noqa: E402
from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_calendar_rules():
    t = "JEUDI 17 DÉCEMBRE 2026 — Ouverture de la carte des formations 2027"
    assert CAL.parse(t)["carte"]["debut"].isoformat() == "2026-12-17" and CAL.parse(t)["carte"]["jour_ok"]
    assert not CAL.parse(t.replace("JEUDI", "SAMEDI"))["carte"]["jour_ok"]           # a wrong weekday is flagged
    assert CAL.parse("→ E ntre le vendredi 4 juin et le lundi 7 juin 2027 inclus : classez vos vœux en attente")["classement"]["fin"].isoformat() == "2027-06-07"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("accompagnement")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_accompagnement as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_accompagnement as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
