"""« Mes vœux en apprentissage » and the apprentice's contract and minimum pay quoted from service-public.gouv.fr (owner,
2026-11-28, PR 18); through its red team.

AV1, AV2, AV5-AV8 read the saved official page, app.js and the docs; AV3 runs on crafted offers (no warehouse is built). AV3 and
AV4 also run on the committed warehouse when it is there (60 real offers, the route)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_red_team():
    import redteam_apprentissage_voeux as R
    failed = [r for r in R.run(None) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not available")
def test_red_team_real():
    import redteam_apprentissage_voeux as R
    failed = [r for r in R.run(REAL_DB, real=True, checks={"AV3", "AV4"}) if not r["ok"]]
    assert not failed, failed
