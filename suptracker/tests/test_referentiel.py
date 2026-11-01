"""Sprint 3 foundation: establishment register, Paysage links and successions, B1 on ids,
reliability grades, source register and glossary, and their red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import evidence as E  # noqa: E402
from suptracker import success as SU  # noqa: E402
from synthetic import SUCCESS_TABLE, make_raw, make_success_xlsx  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
SYN_PAYSAGE = {"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"}


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("ref")
    plan = make_raw(d / "raw")
    xlsx = d / "sies_reussite_licence_test.xlsx"
    make_success_xlsx(xlsx)
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None), xlsx, plan


def test_successions_and_2025_fill(syn):
    db, _, plan = syn
    c = duckdb.connect(str(db), read_only=True)
    succ = {o: (n, m) for o, n, m in c.execute("SELECT old_id, new_id, method FROM ref.succession").fetchall()}
    assert succ == {"OLDP1": ("PARIS", "transition"), "LYONX": ("LYON1", "uai")}
    cod, pid = plan["paysage"]["carto"]
    assert c.execute("""SELECT id_resolu, id_source FROM ref.formation_etablissement WHERE session = 2025 AND cod_aff_form = ?""",
                     [cod]).fetchone() == (pid, "cartographie")


def test_grades():
    assert E.grade(50.0, 2000, 2023, "identifiant")[0] == "A"
    assert E.grade(50.0, 2000, 2023, "nom")[0] == "B"
    assert E.grade(50.0, 20, 2023, "identifiant")[0] == "C"
    assert E.grade(None, 2000, 2023, "identifiant")[0] is None


def test_red_team_on_synthetic(syn):
    import redteam_referentiel as R
    db, xlsx, _ = syn
    failed = [r for r in R.run(db, False, xlsx, SUCCESS_TABLE, SYN_PAYSAGE) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_referentiel as R
    failed = [r for r in R.run(REAL_DB, True, SU.source_path(ROOT / "data" / "sources")) if not r["ok"]]
    assert not failed, failed
