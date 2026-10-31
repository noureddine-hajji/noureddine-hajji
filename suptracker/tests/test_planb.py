"""Plan B: same programme elsewhere, more accessible for the profile, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import planb as PB  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("planb")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb")


def test_haversine():
    assert round(PB.haversine_km((48.8566, 2.3522), (45.764, 4.8357))) == 392     # Paris - Lyon
    assert PB.haversine_km(None, (1, 2)) is None and PB.haversine_km((None, 1), (1, 2)) is None


def test_why_better():
    t = {"zone": "ambitieux", "taux_acces_ens": 20.0, "cdf": 0.3, "spos": None}
    assert PB.why_better(t, {"zone": "cible", "uncertain": False, "taux_acces_ens": 25.0, "cdf": 0.2}) == "zone"
    assert PB.why_better(t, {"zone": "cible", "uncertain": True, "taux_acces_ens": 25.0, "cdf": 0.2}) is None
    assert PB.why_better(t, {"zone": "ambitieux", "uncertain": False, "taux_acces_ens": 40.0, "cdf": 0.35}) == "acces"
    assert PB.why_better(t, {"zone": "ambitieux", "uncertain": False, "taux_acces_ens": 40.0, "cdf": 0.2}) is None


def test_plan_b_on_fixture(db):
    c = duckdb.connect(str(db), read_only=True)
    cod = c.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy JOIN core.taxonomy_link t USING (session, cod_aff_form)
                       WHERE fy.session = 2025 ORDER BY fy.taux_acces_ens LIMIT 1""").fetchone()[0]
    r = PB.plan_b(c, cod, serie="bg", dkey="MATHS+SES", mention="ab")
    assert r["status"] in ("ok", "aucune", "deja_accessible", "non_disponible")
    assert all(a["cod_aff_form"] != cod for a in r["alternatives"])
    with pytest.raises(LookupError):
        PB.plan_b(c, "999999", serie="bt", mention="ab")


def test_red_team_on_synthetic(db):
    import redteam_planb as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data(monkeypatch):
    import redteam_planb as R
    monkeypatch.setenv("REDTEAM_PLANB_N", "16")      # CI budget; run the script for the full sample
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
