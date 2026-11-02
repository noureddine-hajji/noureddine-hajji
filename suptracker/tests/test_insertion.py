"""Sprint 8 insertion: BTS (Inserjeunes, per establishment) and the university's masters / BUT (InserSup), and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import insertion as I  # noqa: E402
from suptracker import poursuite as PO  # noqa: E402
from suptracker import success as SU  # noqa: E402
from synthetic import INSERTION_PAYSAGE, SUCCESS_TABLE, make_insertion_raw, make_raw, make_success_xlsx  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
TRUTH = {"1116": "ok", "1117": "options", "1102": "etablissement_absent", "1123": "non_publie", "1124": "non_trouve", "1130": "ok"}


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("insertion")
    make_raw(d / "raw")
    make_insertion_raw(d / "raw")
    make_success_xlsx(d / "b1.xlsx")
    db = build_mod.build(d / "raw", d / "w.duckdb", success_source=d / "b1.xlsx", poursuite_sources=None)
    con = duckdb.connect(str(db))
    SU.attach(con, d / "b1.xlsx", SUCCESS_TABLE, paysage_table={"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"})
    con.execute("""CREATE OR REPLACE TABLE core.but_success_link AS SELECT 2025 AS session, '1101' AS cod_aff_form,
                   'UNIVERSITE EXEMPLE PARIS (CITE)' AS etab, 'gestion des entreprises et des administrations' AS specialite,
                   'Gestion des entreprises et des administrations' AS programme, 'identifiant' AS lien, 'PARIS' AS id_paysage
                   UNION ALL SELECT 2025, '1199', 'UNIVERSITE EXEMPLE PARIS (CITE)', 'statistique et informatique decisionnelle',
                   'Science des données', 'identifiant', 'PARIS'""")
    con.close()
    return db


def test_keys_and_parsing():
    assert I.bts_key("Fluide, énergie, domotique - option B froid et conditionnement d'air") == I.bts_key("fluides energies domotique option b froid et conditionnement d air")
    assert I.bts_key("Management en hôtellerie restauration - 1ère année commune") == "management hotellerie restauration"
    assert I._num("nd") == (None, "nd") and I._num("72.5") == (72.5, None) and I.promo_years("2023,2024") == (2023, 2024)


def test_blocks(syn):
    import redteam_insertion as R
    c = R.Ctx(syn, paysage=INSERTION_PAYSAGE, truth_links=TRUTH)
    b = I.for_bts(c.con, "1117", "BTS")
    assert b["status"] == "options" and len(b["rows"]) == 2
    assert I.for_bts(c.con, "1102", "BTS")["rows"] == [] and I.for_bts(c.con, "1102", "Licence") is None
    cod = c.q("SELECT cod_aff_form FROM core.licence_success_link WHERE etab = 'UNIVERSITE EXEMPLE PARIS (CITE)' AND discipline = 'droit'")[0][0]
    m = I.for_licence(c.con, cod, "Licence", "Public", paysage=INSERTION_PAYSAGE)
    assert [x["libelle"] for x in m["masters"]] == ["DROIT PRIVE", "DROIT PUBLIC"] and m["masters"][0]["promo"] == "2024"
    assert m["masters"][1]["tx_sortants_en_emploi_sal_fr_18"] is None and m["masters"][1]["masked"]["tx_sortants_en_emploi_sal_fr_18"] == "nd"
    assert m["total"]["tx_sortants_en_emploi_sal_fr_18"] == 68.0 and m["france"]["id_paysage"] == "all"
    assert m["total"]["etablissement"] == "0751234A" and m["en_parties"] == ["DROIT DES AFFAIRES"] and m["anciens"] == 2   # former UAI never served
    u = I.for_but(c.con, "UNIVERSITE EXEMPLE PARIS (CITE)", PO._key("Gestion des entreprises et des administrations"), paysage=INSERTION_PAYSAGE)
    assert u["specialite"]["diplome"] == "B1" and u["france_specialite"]["id_paysage"] == "all"
    sd = I.for_but(c.con, "UNIVERSITE EXEMPLE PARIS (CITE)", "statistique et informatique decisionnelle", paysage=INSERTION_PAYSAGE)
    assert sd["specialite"]["diplome"] == "B2" and sd["france_specialite"]["diplome"] == "B2"     # InserSup spelling aliased


def test_red_team_on_synthetic(syn):
    import redteam_insertion as R
    failed = [r for r in R.run(syn, paysage=INSERTION_PAYSAGE, truth_links=TRUTH) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_insertion as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
