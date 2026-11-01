"""B1 "Réussite en licence": SIES success after L1 per university x discipline, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import success as SU  # noqa: E402
from synthetic import SUCCESS_TABLE, make_raw, make_success_xlsx  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
REAL_XLSX = SU.source_path(ROOT / "data" / "sources")


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("success")
    make_raw(d / "raw")
    xlsx = d / "sies_reussite_licence_test.xlsx"
    plan = make_success_xlsx(xlsx)
    db = build_mod.build(d / "raw", d / "w.duckdb", success_source=None)
    return db, xlsx, plan


def test_parse_groups_short_names_and_keeps_masks(syn):
    _, xlsx, _ = syn
    rows = SU.parse_workbook(xlsx)
    etabs = {r["etab"] for r in rows}
    assert "UNIVERSITE EXEMPLE PARIS" not in etabs and "UNIVERSITE EXEMPLE PARIS (CITE)" in etabs
    assert "Etudiants" not in etabs and SU.NATIONAL in etabs
    staps = [r for r in rows if r["kind"] == "reussite3" and r["discipline"] == "staps" and r["etab"] != SU.NATIONAL][0]
    assert staps["taux"] is None and staps["masked"]["taux"] == "ns"
    droit = [r for r in rows if r["kind"] == "passage" and r["discipline"] == "droit" and r["etab"] == "UNIVERSITE EXEMPLE NORD"][0]
    assert droit["taux"] == 50.0 and droit["va"] == 5.0


def test_university_and_discipline_rules():
    assert SU.university_of("Université de Montpellier, Antenne de Perpignan")[0] == "UNIVERSITE MONTPELLIER"
    assert SU.university_of("Université Paris-Saclay, Campus d’Evry")[0] is None
    assert SU.discipline_of("Psychologie") == "alsh" and SU.discipline_of("Droit, Economie") is None


def test_block_for_a_formation(syn):
    db, xlsx, _ = syn
    con = duckdb.connect()
    src = duckdb.connect(str(db), read_only=True)
    forms = src.execute("""SELECT session, cod_aff_form, g_ea_lib_vx, fil_lib_voe_acc, fili, contrat_etab FROM core.formation_year
                           WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, g_ea_lib_vx VARCHAR, fil_lib_voe_acc VARCHAR, fili VARCHAR, contrat_etab VARCHAR)")
    con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?)", forms)
    assert SU.attach(con, xlsx, SUCCESS_TABLE) > 0
    cod = next(f[1] for f in forms if f[2] == "Université Exemple Paris" and f[3] == "Droit")
    b = SU.for_formation(con, cod, "Licence", "Public")
    assert b["status"] == "ok" and b["discipline"] == "droit" and b["kinds"]["passage"]["taux"] == 50.0
    assert b["national"]["passage"]["etab"] == SU.NATIONAL and b["national"]["passage"]["discipline"] == "droit"
    assert SU.for_formation(con, cod, "BTS", "Public") is None
    assert SU.for_formation(con, cod, "Licence", "Privé enseignement supérieur")["status"] == "hors_champ"


def test_red_team_on_synthetic(syn):
    import redteam_success as R
    db, xlsx, _ = syn
    failed = [r for r in R.run(db, xlsx, SUCCESS_TABLE) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not (REAL_DB.exists() and REAL_XLSX), reason="real warehouse or SIES workbook not present")
def test_red_team_on_real_data():
    import redteam_success as R
    failed = [r for r in R.run(REAL_DB, REAL_XLSX, None, real=True) if not r["ok"]]
    assert not failed, failed
