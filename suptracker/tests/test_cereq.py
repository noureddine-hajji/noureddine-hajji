"""Sprint 8 follow-up: the Céreq card (does the job match the training?) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import cereq as CQ  # noqa: E402
from suptracker import success as SU  # noqa: E402
from synthetic import SUCCESS_TABLE, make_cereq_xlsx, make_insertion_raw, make_raw, make_success_xlsx  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("cereq")
    make_raw(d / "raw")
    make_insertion_raw(d / "raw")
    make_success_xlsx(d / "b1.xlsx")
    make_cereq_xlsx(d / "cereq.xlsx")
    db = cached_build(d / "raw", d / "w.duckdb", success_source=d / "b1.xlsx", poursuite_sources=None, cereq_source=d / "cereq.xlsx")
    con = duckdb.connect(str(db))
    SU.attach(con, d / "b1.xlsx", SUCCESS_TABLE, paysage_table={"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"})
    # real diploma codes for the synthetic BTS (the insertion fixture uses placeholders): comptabilité = NSF 314 (tertiary),
    # systèmes numériques = NSF 201 (industrial), in both formats (MEFSTAT11 for lycées, CFD for apprenticeship)
    con.execute("""UPDATE core.inserjeunes_bts SET code = CASE
        WHEN libelle_formation LIKE 'comptabilite%' AND source = 'apprentissage' THEN '32031408'
        WHEN libelle_formation LIKE 'comptabilite%' THEN '32221031408'
        WHEN libelle_formation LIKE 'systemes numeriques%' THEN '32221020101'
        ELSE code END""")
    CQ.build(con, d / "cereq.xlsx")
    con.close()
    return db, d / "cereq.xlsx"


def test_nsf_and_rules():
    assert CQ.nsf_of("32221031213") == 312 and CQ.nsf_of("32031212") == 312 and CQ.nsf_of("3") is None
    assert CQ.nsf_side(255) == "industrielle" and CQ.nsf_side(345) == "tertiaire" and CQ.nsf_side(133) is None
    assert CQ.group_of("BUT", "Génie civil", None, None)[0] is None
    assert CQ.group_of("Licence", "Droit", "droit", None)[:2] == (442, 512)
    assert CQ.group_of("CPGE", "MPSI", None, None)[0] == 523 and CQ.group_of("CPGE", "Lettres", None, None)[0] is None


def test_links_and_block(syn):
    db, _ = syn
    c = duckdb.connect(str(db), read_only=True)
    rules = dict(c.execute("SELECT programme, regle FROM core.cereq_link WHERE fili = 'BTS'").fetchall())
    assert any(v == "bts_tertiaire" for k, v in rules.items() if "Comptabilit" in k)
    assert any(v == "bts_industrielle" for k, v in rules.items() if "Systèmes numériques" in k)    # matched through its options
    cod = c.execute("SELECT cod_aff_form FROM core.cereq_link WHERE code = 442 LIMIT 1").fetchone()
    if cod:
        b = CQ.for_formation(c, cod[0])
        assert b["suite"]["code"] == 512 and b["ensemble"]["code"] == 100 and b["groupe"]["valeurs"]["a3ans"]["competence_ok"] is not None
        assert b["groupe"]["valeurs"]["a6ans"]["competence_ok"] is None        # published at 3 years only
    but = c.execute("SELECT cod_aff_form FROM core.cereq_link WHERE fili = 'BUT' LIMIT 1").fetchone()[0]
    assert CQ.for_formation(c, but)["status"] == "sans_correspondance"


def test_red_team_on_synthetic(syn):
    import redteam_cereq as R
    db, src = syn
    failed = [r for r in R.run(db, source=src) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.cereq_diplome").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the Céreq tables")
def test_red_team_on_real_data():
    import redteam_cereq as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
