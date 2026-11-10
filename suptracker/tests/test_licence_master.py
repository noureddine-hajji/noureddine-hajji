"""Sprint 16: from the licence to the master, side by side, and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import licence_master as LM  # noqa: E402
from synthetic import (INSERTION_PAYSAGE, SUCCESS_TABLE, make_insertion_raw, make_monmaster_raw, make_onisep_zips,  # noqa: E402
                       make_raw, make_success_xlsx)
from synthetic import cached_build  # noqa: E402
from suptracker import success as SU  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"
PAYSAGE = {**INSERTION_PAYSAGE, "UNIVERSITE EXEMPLE NORD": "NORD1"}


def test_title_key():
    assert LM.key("DROIT DE LA PROPRIÉTÉ INTELLECTUELLE, DU NUMÉRIQUE ET DE L’ESPACE") == \
        LM.key("droit de la propriété intellectuelle, du numérique et de l'espace")
    assert LM.key("Œuvres") == "oeuvres" and LM.key("STAPS:Management du sport") == "staps management du sport"
    assert LM.rewritten(LM.key("STAPS:ACTIVITE PHYSIQUE ADAPTEE ET SANTE")) == \
        LM.key("sciences et techniques des activités physiques et sportives  : activité physique adaptée et santé")
    assert LM.rewritten(LM.key("METIERS DE L'ENSEIGNEMENT, DE L'EDUCATION ET DE LA FORMATION (MEEF), PRATIQUES ET INGENIERIE DE LA FORMATION")) == \
        LM.key("métiers de l'enseignement, de l'éducation et de la formation - pratiques et ingénierie de la formation")


def test_job_class_rule():
    assert LM.job_class([]) == LM.job_class([None]) == "non_lu"
    assert LM.job_class(["debutants_insuffisants", None, "debutants_insuffisants"]) == "insuffisants"
    assert LM.job_class(["debutants_nombreux"]) == "nombreux"
    assert LM.job_class(["debutants_insuffisants", "debutants_nombreux"]) == "incertain"
    assert LM.job_class(["incertain", "debutants_insuffisants"]) == "incertain"


def test_landmarks_only_on_disjoint_ranges():
    lic = {"ilo_min": 0.4, "ilo_max": 0.6, "theta_min": 0.5, "theta_max": 0.6}
    assert LM.reperes(lic, {"ilo_min": 0.1, "ilo_max": 0.39, "theta_min": 0.61, "theta_max": 0.7}) == ["ia_plus_bas", "complementarite_plus_haute"]
    assert LM.reperes(lic, {"ilo_min": 0.1, "ilo_max": 0.4, "theta_min": 0.6, "theta_max": 0.7}) == []      # touching = overlap
    assert LM.reperes(lic, {"ilo_min": 0.61, "ilo_max": 0.7, "theta_min": 0.1, "theta_max": 0.49}) == ["ia_plus_haut", "complementarite_plus_basse"]
    assert LM.reperes(None, {"ilo_min": 0.1, "ilo_max": 0.2, "theta_min": None, "theta_max": None}) == []


def test_empty_build_is_safe():
    con = duckdb.connect(":memory:")
    assert LM.build(con) == {"mentions": 0, "metiers": 0}
    assert LM.for_licence(con, "1", "L1", "Public") is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("lm")
    make_raw(d / "raw")
    make_monmaster_raw(d / "raw")
    make_insertion_raw(d / "raw")
    make_success_xlsx(d / "b1.xlsx")
    src = make_onisep_zips(d / "sources")
    db = cached_build(d / "raw", d / "w.duckdb", success_source=d / "b1.xlsx", poursuite_sources=None, cereq_source=None,
                         onisep_sources=src)
    con = duckdb.connect(str(db))
    SU.attach(con, d / "b1.xlsx", SUCCESS_TABLE, paysage_table={"PARIS": "UNIVERSITE EXEMPLE PARIS (CITE)"})
    con.close()
    return db


def test_red_team_on_synthetic(syn):
    import redteam_licence_master as R
    failed = [r for r in R.run(syn, paysage=PAYSAGE) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.metier_axes").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the sprint 16 tables")
def test_red_team_on_real_data():
    import redteam_licence_master as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
