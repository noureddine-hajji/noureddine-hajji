"""B4: Mon parcours for bac technologique / professionnel students, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import journey as J  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("series")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb")


@pytest.mark.parametrize("label,want", [
    ("Tous les candidats sauf les Bac technologiques et Bac professionnels", (True, False, False)),
    ("Bacheliers technologiques toutes séries", (False, True, False)),
    ("Voie d'accès générale", (True, True, True)),
    ("STI2D", (False, None, False)),
])
def test_groups(label, want):
    assert tuple(J.group_applies(label, None, None, s) for s in J.SERIES) == want


def test_stage1_and_stage2_for_techno(db):
    c = duckdb.connect(str(db), read_only=True)
    s1 = J.stage1_series(c, "bt")
    assert s1["filieres"] and 0 < s1["coverage"] <= 1
    t = s1["filieres"][0]["type_key"]
    s2 = J.stage2(c, None, "ab", t, serie="bt")
    assert s2["serie"] == "bt" and s2["doublette"] is None
    for f in s2["formations"]:
        assert f["bg"] is None and f["serie"] == "bt"
        if f["rate_fragile"]:
            assert f["zone"] in ("indetermine", "non_ouvert")
    with pytest.raises(ValueError):
        J.stage2(c, None, "ab", t, serie="stmg")


def test_red_team_on_synthetic(db):
    import redteam_series as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_series as R
    c = duckdb.connect(str(REAL_DB), read_only=True)
    has = c.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_name = 'formation_year' AND column_name = 'prop_tot_bt'""").fetchone()[0]
    c.close()
    if not has:
        pytest.skip("warehouse predates the series counts")
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
