"""Sprint 13: the job reference (ROME -> FAP-2021 / FAP-2009 -> ISCO-08) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import metiers as MT  # noqa: E402
from suptracker import nomenclatures as NM  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
HAVE_SOURCES = all(k in NM.find_sources() for k in NM.FILES)


def test_sas_formats(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text('value  $FAP9RSQ\n"A1101","A1102"   =\t"A0Z43"\n Other = "ZZZZZ";\nrun;\n'
                 'value  $FAP9RAQ\n"A13010","A13011" = "A2Z70"\n"A13019" = "A2Z90"\n Other = "ZZZZZ";\nrun;\n', encoding="latin-1")
    rows = NM.read_rome_fap2009(p)
    assert ("A1101", 7, "A0Z43") in rows and ("A1102", 0, "A0Z43") in rows and len([r for r in rows if r[0] == "A1101"]) == 10
    assert ("A1301", 0, "A2Z70") in rows and ("A1301", 9, "A2Z90") in rows and not [r for r in rows if r[0] == "A1301" and r[1] == 5]


def test_precision_and_fold():
    assert NM.precision("2512", {"2512"}) == 4 and NM.precision("2100", {"2512"}) == 2 and NM.precision("2130", set()) == 3
    assert NM.fold("  Développeuse   d’applications ") == "developpeuse d'applications"


def test_empty_build_is_safe():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA core")
    assert NM.build(con, {})["rome"] == 0
    assert NM.for_romes(con, ["M1805"])[0]["connu"] is False and NM.for_romes(con, ["A15", None]) == []


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("nomen")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)


@pytest.mark.skipif(not HAVE_SOURCES, reason="the Dares / Insee files are not in data/sources")
def test_job_page_codes(syn):
    c = duckdb.connect(str(syn), read_only=True)
    d = MT.detail(c, "MET.3")                      # two ROME codes: M1801 and I1401
    assert [x["rome"] for x in d["codes"]] == ["I1401", "M1801"] and all(x["connu"] and x["fap2021"] for x in d["codes"])
    for x in d["codes"]:
        assert sorted(q for e in x["fap2021"] for q in e["qualifications"]["codes"]) == list(range(10))


@pytest.mark.skipif(not HAVE_SOURCES, reason="the Dares / Insee files are not in data/sources")
def test_red_team_on_synthetic(syn):
    import redteam_nomenclatures as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.nomen_rome_isco").fetchone()[0]
        con.execute("SELECT count(*) FROM core.nomen_metier_rome_titre").fetchone()   # name links (sprint 13 follow-up)
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the sprint-13 tables")
def test_red_team_on_real_data():
    import redteam_nomenclatures as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
