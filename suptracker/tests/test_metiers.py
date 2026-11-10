"""Sprint 12: "Du métier aux formations" (the jobs card read backwards) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import metiers as MT  # noqa: E402
from suptracker import onisep as ON  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("metiers")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    db = cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)
    return db, src


def test_sheet_level():
    assert ON.sheet_level(["bac + 3"], "BTS") == 3                 # a 3-year BTS (orthoprothésiste)
    assert ON.sheet_level([None], "BTS") == 2 and ON.sheet_level(["bac + 2", "bac + 3"]) == 2


def test_job_page(syn):
    db, _ = syn
    c = duckdb.connect(str(db), read_only=True)
    assert sorted(r for (r,) in c.execute("SELECT rome FROM core.onisep_metier_rome WHERE met_id = 'MET.3'").fetchall()) == ["I1401", "M1801"]
    assert ("gestionnaire de paie",) in c.execute("SELECT libelle FROM core.onisep_metier_libelle WHERE met_id = 'MET.1'").fetchall()
    d = MT.detail(c, "MET.2")                                       # expert-comptable: bac+5, reached after a BTS or a BUT
    assert d["status"] == "ok" and {x["acces"] for x in d["diplomes"]} == {"poursuite"}
    d = MT.detail(c, "MET.1")                                       # comptable: bac+2, accessible with the BTS
    assert any(x["acces"] == "direct" and x["formations"] for x in d["diplomes"])
    assert MT.detail(c, "MET.999") is None and MT.detail(c, "1 OR 1=1") is None
    cat = MT.catalogue(c)
    assert len(cat["rows"]) == c.execute("SELECT count(*) FROM core.onisep_metier").fetchone()[0]


def test_red_team_on_synthetic(syn):
    import redteam_metiers as R
    db, src = syn
    failed = [r for r in R.run(db, sources=src) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.onisep_metier_libelle").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the sprint-12 Onisep tables")
def test_red_team_on_real_data():
    import redteam_metiers as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
