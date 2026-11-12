"""Sprint R9 (owner, 2026-11-12): searching from the map, through its red team (CR1-CR10) on the real warehouse, plus the
mention groups' truth table (no warehouse needed). The browser check runs with `python scripts/redteam_carterecherche.py --real`."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_mention_groups_truth_table():
    import redteam_carterecherche as R
    from suptracker import carte as CA
    for a, b, same in R.DL_TRUTH:
        assert (CA.groupe_of("Double licence", a) == CA.groupe_of("Double licence", b)) == same, (a, b)
    assert CA.groupe_of("CPES", "Sciences Des Données, Société et Santé") == "Sciences des données"
    assert CA.groupe_of("BTS - BTSA - BTSM", "Comptabilité et gestion") == "Comptabilité et gestion"
    assert sorted(["Études de santé", "Écoles d'ingénieurs", "BUT", "Formation"], key=CA.sort_key) == ["BUT", "Écoles d'ingénieurs", "Études de santé", "Formation"]


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_carterecherche as R
    failed = [r for r in R.run(REAL_DB, real=True, browser=False) if not r["ok"]]
    assert not failed, failed
