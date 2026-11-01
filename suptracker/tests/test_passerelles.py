"""Sprint 7 gateways: reorientation after L1 (B1 workbook) and the university's masters (MonMaster), and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import passerelles as PA  # noqa: E402
from suptracker import success as SU  # noqa: E402
from synthetic import (PASSERELLES_PAYSAGE, REO_SYN_ALIASES, SUCCESS_TABLE, make_monmaster_raw, make_raw,  # noqa: E402
                       make_success_xlsx)

REAL_DB = ROOT / "data" / "suptracker.duckdb"
REAL_XLSX = SU.source_path(ROOT / "data" / "sources")
B1_PAYSAGE = {"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"}


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("passerelles")
    make_raw(d / "raw")
    make_monmaster_raw(d / "raw")
    plan = make_success_xlsx(d / "b1.xlsx")
    db = build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None)
    return db, d / "b1.xlsx", d / "raw", plan


def _kw(raw):
    return {"raw_dir": raw, "aliases": REO_SYN_ALIASES, "paysage": PASSERELLES_PAYSAGE, "b1_table": SUCCESS_TABLE, "b1_paysage": B1_PAYSAGE}


def test_reorientation_sheet_parsed_by_block_with_masks(syn):
    _, xlsx, _, plan = syn
    rows = PA.parse_reorientation(xlsx, REO_SYN_ALIASES)
    etabs = {r["etab"] for r in rows}
    assert "UNIVERSITE EXEMPLE NORD" in etabs and "UNIVERSITE EXEMPLE NORD (SITE)" not in etabs and "Etudiants" not in etabs
    staps = [r for r in rows if r["etab"] == "UNIVERSITE EXEMPLE PARIS (CITE)" and r["discipline"] == "staps"][0]
    assert staps["taux_reorientation"] is None and staps["masked"]["taux_reorientation"] == "ns"
    droit = [r for r in rows if r["etab"] == "UNIVERSITE EXEMPLE PARIS (CITE)" and r["discipline"] == "droit"][0]
    assert droit["n_hors_univ"] + droit["n_univ"] == droit["n_reorientation"]


def test_discipline_map_keeps_meef_and_mixed_out():
    assert PA.master_discipline("Sciences humaines et sociales", "M.E.E.F.") == "meef"
    assert PA.master_discipline("Sciences humaines et sociales", "SHS") == "alsh"
    assert PA.master_discipline("Pluridisciplinaire droit, sciences économiques, AES", "Economie, gestion et AES") is None


def test_blocks_for_a_licence_and_a_but(syn):
    import redteam_passerelles as R
    db, xlsx, raw, _ = syn
    c = R.Ctx(db, xlsx, **_kw(raw))
    cod = c.q("SELECT cod_aff_form FROM core.licence_success_link WHERE etab = 'UNIVERSITE EXEMPLE PARIS (CITE)' AND discipline = 'droit'")[0][0]
    b = PA.for_licence(c.con, cod, "Licence", "Public", paysage=PASSERELLES_PAYSAGE)
    assert b["status"] == "ok" and b["reorientation"]["taux_reorientation"] == 12.0
    assert b["masters"]["n_accept"] == 100 and b["masters"]["n_offres"] == 2 and b["meef"]["n_accept"] == 50
    assert b["masters_france"]["n_accept"] == 130                       # Paris 100 + Nord 30; MEEF and mixed excluded
    assert PA.for_licence(c.con, cod, "BUT", "Public") is None
    u = PA.for_but(c.con, "UNIVERSITE EXEMPLE PARIS (CITE)", paysage=PASSERELLES_PAYSAGE)
    assert u["universite"]["n_accept_but3"] == 6 and u["france"]["n_accept_but3"] == 6


def test_red_team_on_synthetic(syn):
    import redteam_passerelles as R
    db, xlsx, raw, _ = syn
    failed = [r for r in R.run(db, xlsx, **_kw(raw)) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and REAL_XLSX), reason="real warehouse or SIES workbook not present")
def test_red_team_on_real_data():
    import redteam_passerelles as R
    failed = [r for r in R.run(REAL_DB, REAL_XLSX, real=True) if not r["ok"]]
    assert not failed, failed
