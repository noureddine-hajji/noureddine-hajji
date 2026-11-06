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
HAVE = set(IA.sources()) >= {"ilo", "tags", *IA.THETA_KEYS}


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


def test_theta_on_the_guide_example(tmp_path):
    """The owner's guide, section 5.5 (fictitious): theta = (70 + 80 + 50 + 70 + 65 + 80) / 600 = 0.6917."""
    x = {"4.C.1.a.2.l": 80, "4.C.1.a.2.c": 60, "4.C.1.c.2": 70, "4.C.1.c.1": 90, "4.C.2.a.1.c": 40, "4.C.2.a.3": 60,
         "4.C.3.a.1": 80, "4.C.3.a.4": 60, "4.C.3.a.2.b": 70, "4.C.3.b.2": 60, "4.C.3.b.8": 90}
    head = "O*NET-SOC Code,Title,Element ID,Element Name,Scale ID,Scale Name,Category,Data Value,N,Standard Error," \
           "Lower CI Bound,Upper CI Bound,Recommend Suppress,Not Relevant,Date,Domain Source\n"
    rows = [f"11-1111.00,Ex,{e},n,CX,s,,{v / 25 + 1},,,,,N,,,\n" for e, v in x.items()]
    rows += [f"11-1111.00,Ex,{e},n,CXP,s,1,99,,,,,N,,,\n" for e in x]                 # response shares: never the score
    rows += [f"22-2222.00,Sup,{e},n,CX,s,,3,,,,,{'Y' if e == '4.C.3.a.1' else 'N'},,,\n" for e in x]   # suppressed: no theta
    (tmp_path / "wc.csv").write_text(head + "".join(rows))
    (tmp_path / "jz.csv").write_text("O*NET-SOC Code,Title,Job Zone,Date,Domain Source\n11-1111.00,Ex,4,,\n22-2222.00,Sup,3,,\n")
    th = IA.read_theta(tmp_path / "wc.csv", tmp_path / "jz.csv")
    assert th["onet"].tolist() == ["11-1111.00"]
    r = th.iloc[0]
    assert [r.communication, r.responsabilite, r.physique, r.criticite, r.non_routine, r.competences] == [70, 80, 50, 70, 65, 80]
    assert abs(r.theta - 415 / 600) < 1e-12


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
        n = min(con.execute(f"SELECT count(*) FROM core.{t}").fetchone()[0] for t in ("ia_oit_isco", "ia_theta_onet"))
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (HAVE and REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the ILO or theta tables")
def test_red_team_on_real_data():
    import redteam_ia as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
