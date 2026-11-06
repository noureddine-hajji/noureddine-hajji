"""Sprint 15 (first part): ILO 2025 generative-AI exposure of a job's tasks, France Travail's tag, and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import ia_exposition as IA  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
HAVE = set(IA.sources()) == {"ilo", "tags"}


def test_empty_build_is_safe():
    con = duckdb.connect(":memory:")
    assert IA.build(con, {}) == {}
    assert IA.for_codes(con, []) is None
    assert con.execute("SELECT count(*) FROM core.ia_oit_isco").fetchone()[0] == 0


def test_range_never_an_average():
    con = duckdb.connect(":memory:")
    IA.build(con, {})
    con.execute("INSERT INTO core.ia_oit_isco VALUES ('2512','x',0.53,0.1,'Exposed: Gradient 3',4,8,0.53),"
                "('2513','y',0.6,0.1,'Exposed: Gradient 4',5,8,0.6)")
    codes = [{"rome": "M1805", "connu": True, "isco": [
        {"code": "2512", "precision": 4, "n_intitules": 3, "libelle": "a"},
        {"code": "2513", "precision": 4, "n_intitules": 9, "libelle": "b"},
        {"code": "21", "precision": 2, "n_intitules": 2, "libelle": "c"},
        {"code": "0210", "precision": 4, "n_intitules": 1, "libelle": "d"}]}]
    out = IA.for_codes(con, codes)
    assert [i["code"] for i in out["isco"]] == ["2513", "2512", "0210"]
    assert (out["min"], out["max"], out["sans_score"]) == (0.53, 0.6, ["0210"])
    assert out["tags"] == [{"rome": "M1805", "transition_numerique": None}]


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("ia")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)


@pytest.mark.skipif(not HAVE, reason="the ILO workbook or the ROME tags are not in data/sources")
def test_red_team_on_synthetic(syn):
    import redteam_ia as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.ia_oit_isco").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (HAVE and REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the ILO table")
def test_red_team_on_real_data():
    import redteam_ia as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
