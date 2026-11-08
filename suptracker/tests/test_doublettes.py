"""Sprint "Doublettes": proposal rates by doublette (group, national) and by bac route (formation), and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import doublettes as DB  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def _mart(rows):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA mart")
    con.execute("""CREATE TABLE mart.spe_filiere (session BIGINT, type_key VARCHAR, type_label VARCHAR, doublette_key VARCHAR,
                   candidats BIGINT, propositions BIGINT, acceptations BIGINT)""")
    con.executemany("INSERT INTO mart.spe_filiere VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    DB.build(con)
    return con


def test_rare_bucket_and_pick():
    rows = [(s, "g", "G", "A+B", 100, 80, 50) for s in (2024, 2025)] + [(s, "g", "G", "C+D", 9, 3, 1) for s in (2024, 2025)] \
        + [(2025, "g", "G", "E+F", 2, 2, 2)]
    g = DB.for_group(_mart(rows), "g")
    rare = {d["key"]: d["rare"] for d in g["doublettes"]}
    assert rare == {"A+B": False, "C+D": True, "E+F": True}                      # 18 and 2 candidates < 20
    assert (g["autres"]["candidats"], g["autres"]["n_doublettes"], g["autres"]["taux"]) == (20, 2, 40.0)
    assert DB.pick(g, "A+B")["source"] == "doublette" and DB.pick(g, "A+B")["taux"] == 80.0
    assert DB.pick(g, "C+D")["source"] == "autres" and DB.pick(g, "C+D")["estimation"] is True
    assert DB.pick(g, "Z+Z")["source"] == "autres" and DB.pick(g, None) is None


def test_exactly_twenty_is_not_rare():
    g = DB.for_group(_mart([(s, "g", "G", "A+B", 5, 1, 1) for s in (2022, 2023, 2024, 2025)]), "g")
    assert g["doublettes"][0]["rare"] is False


def test_counting_break_campaigns_are_left_out():
    # the Licence L.AS pattern: candidates x2.8 in 2023-2024, proposals flat
    rows = [(2022, "las", "L.AS", "A+B", 96307, 53522, 14963), (2023, "las", "L.AS", "A+B", 272454, 55246, 15640),
            (2024, "las", "L.AS", "A+B", 262625, 56058, 15770), (2025, "las", "L.AS", "A+B", 103979, 53442, 15695),
            # a small group that grows: not judged (proposals under 2 000)
            (2022, "small", "S", "A+B", 706, 183, 90), (2025, "small", "S", "A+B", 1521, 155, 80)]
    con = _mart(rows)
    assert con.execute("SELECT type_key, session FROM mart.spe_break ORDER BY 1, 2").fetchall() == [("las", 2023), ("las", 2024)]
    g = DB.for_group(con, "las")
    assert g["campagnes_ecartees"] == [2023, 2024] and [t["session"] for t in g["tous"]["trend"]] == [2022, 2025]
    assert g["tous"]["candidats"] == 96307 + 103979


def test_empty_warehouse_is_safe():
    con = duckdb.connect(":memory:")
    assert DB.build(con) == 0 and DB.for_group(con, "x") is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("dbl")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_doublettes as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM mart.spe_group").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse without the doublettes tables")
def test_red_team_on_real_data():
    import redteam_doublettes as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
