"""Sprint "Rapports publics": each formation's own public report (archived PDF), parsed, checked against SIES, and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import rapports as RP  # noqa: E402
from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
PROBE = ROOT / "data" / "rapports" / "probe" / "pdf"


@pytest.mark.skipif(not (PROBE / "wayback_31899_20260525031407.pdf").exists(), reason="probe PDF not committed")
def test_parser_reads_a_known_report():
    import rapports_parse as P
    r = P.parse((PROBE / "wayback_31899_20260525031407.pdf").read_bytes())
    assert r["session"] == 2025 and r["codes"] == ["31899"]
    bg = [(d["doublette"], d["confirmes"], d["en_position"]) for d in r["doublettes"] if d["bac"] == "Baccalauréat Général"]
    assert bg[-1] == ("Autres doublettes", 200, 160) and len(bg) == 3
    assert r["eds"]["pris_en_compte"] == "Non" and r["criteres"]      # this DEUST says it does not use them
    assert "Signature" not in (r["conseils"] + r["modalites"])


def test_empty_harvest_is_safe(tmp_path):
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, nb_voe_pp INTEGER, ran_grp1 INTEGER, ran_grp2 INTEGER, ran_grp3 INTEGER)")
    assert RP.build(con, tmp_path) == {"rapports": 0}
    assert RP.for_formation(con, "1") is None and RP.pick(None, "A+B") is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("rp")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_rapports as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        con.execute("SELECT 1 FROM core.formation_year LIMIT 1")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_rapports as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed


def test_insert_one_arrow_table_equals_executemany():
    """rapports._insert (2026-11-26): the rows go in as one Arrow table (executemany took 6 of the synthetic build's 12 minutes);
    the table must equal executemany's row for row, NULLs, booleans and accents included, and a column pyarrow cannot type
    (mixed values) falls back to executemany with the same result."""
    import duckdb

    from suptracker import rapports as RP

    cases = [
        ("a VARCHAR, b INTEGER, c BOOLEAN, d DOUBLE", [("é", 1, True, 1.5), (None, None, None, None), ("x'y", -3, False, 0.0)]),
        ("a VARCHAR, b INTEGER", [("1", 2), ("2", "3")]),          # a mixed column: the row-by-row path
        ("a INTEGER, b VARCHAR", [(1, "z")] * 3),
    ]
    for cols, rows in cases:
        fast, slow = duckdb.connect(), duckdb.connect()
        for c in (fast, slow):
            c.execute(f"CREATE TABLE t ({cols})")
        n = cols.count(",") + 1
        sql = "INSERT INTO t VALUES (" + ", ".join("?" * n) + ")"
        RP._insert(fast, sql, rows)
        slow.executemany(sql, rows)
        assert fast.execute("SELECT * FROM t").fetchall() == slow.execute("SELECT * FROM t").fetchall(), cols
        assert fast.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = '_rows_insert'").fetchone()[0] == 0
    RP._insert(duckdb.connect(), "INSERT INTO nowhere VALUES (?)", [])      # no row: nothing done, no error
