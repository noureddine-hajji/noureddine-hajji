"""Sprint 6 "success beyond licence": BUT per university, master per university x discipline, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import poursuite as P  # noqa: E402
from synthetic import (POURSUITE_ALIASES, POURSUITE_PAYSAGE, POURSUITE_RULES, SUCCESS_TABLE,  # noqa: E402
                       make_poursuite_xlsx, make_raw, make_success_xlsx)

REAL_DB = ROOT / "data" / "suptracker.duckdb"
REAL_SOURCES = P.find_sources(ROOT / "data" / "sources")
B1_PAYSAGE = {"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"}


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("poursuite")
    make_raw(d / "raw")
    plan = make_poursuite_xlsx(d / "src")
    make_success_xlsx(d / "b1.xlsx")
    db = build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None)
    return db, plan, d / "b1.xlsx"


def _ctx_kw(b1):
    return {"aliases": POURSUITE_ALIASES, "paysage": POURSUITE_PAYSAGE, "rules": POURSUITE_RULES,
            "b1": (b1, SUCCESS_TABLE, B1_PAYSAGE),
            # synthetic truth tables: the lycée with no id and no rule stays unlinked, the rule links Marseille
            # Lille's id names a school with no BUT row: the site override links it to Nord (cf. IUT de Nîmes)
            "overrides": {r"^ecole d'ingenieurs exemple lille": "UNIVERSITE EXEMPLE NORD"},
            "but_truth": {"Lycée Exemple Bordeaux": None, "Lycée Exemple Marseille": "UNIVERSITE EXEMPLE NORD",
                          "École d'ingénieurs Exemple Lille": "UNIVERSITE EXEMPLE NORD",
                          "Université Exemple Paris": "UNIVERSITE EXEMPLE PARIS (CITE)"},
            "spe_truth": {"Génie mécanique et productique": "genie mecanique et productique",
                          "Gestion des entreprises et des administrations": "gestion des entreprises et des administrations"}}


def test_workbooks_are_recognised_by_content(syn, tmp_path):
    _, plan, b1 = syn
    assert {k: P.detect(v) for k, v in plan["sources"].items()} == {k: k for k in plan["sources"]}
    assert P.detect(b1) is None                     # the B1 licence workbook is not a sprint-6 one


def test_parsers_keep_masks_blocks_and_national_rows(syn):
    _, plan, _ = syn
    but = P.parse_but_etab(plan["but_etab"], POURSUITE_ALIASES)
    nat = [r for r in but if r["kind"] == "reussite3" and r["etab"] == P.NATIONAL][0]
    assert nat["etab_row"] == "Inscriptions principales" and nat["inscrits"] == plan["but"]["n"]
    assert {r["etab"] for r in but} == {P.NATIONAL, "UNIVERSITE EXEMPLE PARIS (CITE)", "UNIVERSITE EXEMPLE LYON", "UNIVERSITE EXEMPLE NORD"}
    nord = [r for r in but if r["etab"] == "UNIVERSITE EXEMPLE NORD" and r["kind"] == "reussite3"][0]
    assert nord["taux"] is None and nord["masked"]["taux"] == "ns"
    master = P.parse_master_etab(plan["master_etab"], POURSUITE_ALIASES)
    paris = [r for r in master if r["etab"] == "UNIVERSITE EXEMPLE PARIS (CITE)"]
    assert {r["block_row"] for r in paris} == {"UNIVERSITE EXEMPLE PARIS (EPE)"} and {r["etab_row"] for r in paris} >= {"UNIVERSITE EXEMPLE PARIS"}
    droit = [r for r in paris if r["kind"] == "passage_m2" and r["discipline"] == "droit"][0]
    assert droit["taux"] == 80.0 and abs(sum(droit[k] for k in P.DEVENIR_M2) - 100) < 0.2


def test_specialty_and_alias_rules():
    known = {"statistique et informatique decisionnelle", "genie biologique", "carrieres sociales"}
    assert P.specialty_of("Science des données", known) == "statistique et informatique decisionnelle"
    assert P.specialty_of("Génie biologique parcours agronomie", known) == "genie biologique"
    assert P.specialty_of("Informatique", known) is None
    assert P.canonical("UNIVERSITE  BREST") == "UNIVERSITE  BREST" and P.canonical("UNIVERSITE LYON 2") == "UNIVERSITE LYON 2 (LUMIERE)"


def test_blocks_for_formations(syn):
    import redteam_poursuite as R
    db, plan, b1 = syn
    c = R.Ctx(db, plan["sources"], **_ctx_kw(b1))
    b = P.but_for_formation(c.con, "1100", "BUT", "Public")
    assert b["status"] == "ok" and b["kinds"]["reussite3"]["taux"] == 60.0 and b["lien"] == "identifiant"
    assert b["national"]["reussite3"]["etab_row"] == "Inscriptions principales"
    assert b["specialite"]["code"] == "genie mecanique et productique"
    assert P.but_for_formation(c.con, "1128", "BUT", "Public")["kinds"]["reussite3"]["maillon"]["fiabilite"] is None   # masked
    assert P.but_for_formation(c.con, "1114", "BUT", "Public")["status"] == "non_rattachee"
    assert P.but_for_formation(c.con, "1100", "Licence", "Public") is None
    cod = c.q("SELECT cod_aff_form FROM core.licence_success_link WHERE etab = 'UNIVERSITE EXEMPLE PARIS (CITE)' AND discipline = 'droit'")[0][0]
    m = P.master_for_formation(c.con, cod, "Licence", "Public")
    assert m["status"] == "ok" and m["kinds"]["passage_m2"]["taux"] == 80.0 and m["discipline"] == "droit"
    assert any(r["dim"] == "bac" and r["code"] == "bg" for r in m["chaine"])


def test_red_team_on_synthetic(syn):
    import redteam_poursuite as R
    db, plan, b1 = syn
    failed = [r for r in R.run(db, plan["sources"], **_ctx_kw(b1)) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and len(REAL_SOURCES) == 5), reason="real warehouse or SIES workbooks not present")
def test_red_team_on_real_data():
    import redteam_poursuite as R
    failed = [r for r in R.run(REAL_DB, REAL_SOURCES, real=True) if not r["ok"]]
    assert not failed, failed
