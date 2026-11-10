"""Sprint 8 follow-up: the jobs card (Onisep Idéo, jobs a diploma leads to) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import onisep as ON  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("onisep")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    assert ON.find_sources(d / "sources") == src            # recognised by content; the CSV is ignored
    db = cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None,
                         onisep_sources=src)
    return db, src


def test_key_and_levels():
    assert ON.key("Comptabilité et gestion") == ON.key("comptabilite gestion")
    assert ON.level_rank("bac + 5") == 5 and ON.level_rank("bac + 2") == 2 and ON.level_rank("bac ou équivalent") == 0
    assert ON.level_rank("CAP ou équivalent") == -1 and ON.level_rank("niveau inconnu") is None


def test_links_and_block(syn):
    db, _ = syn
    c = duckdb.connect(str(db), read_only=True)
    rules = {}
    for prog, fid, rule in c.execute("SELECT programme, for_id, regle FROM core.onisep_link").fetchall():
        rules.setdefault(prog, [set(), rule])[0].update({fid} if fid else set())
    assert rules["Comptabilité et gestion"] == [{"FOR.1"}, "bts_titre"]
    assert rules["Systèmes numériques"] == [{"FOR.2", "FOR.3"}, "bts_options"]
    assert rules["Gestion des entreprises et des administrations"] == [{"FOR.4"}, "but_specialite"]
    assert rules["Droit"] == [{"FOR.5"}, "licence_mention"]                       # never the licence professionnelle
    assert rules["Génie mécanique et productique"][1] == "but_sans_fiche"
    cod = c.execute("SELECT cod_aff_form FROM core.onisep_link WHERE for_id = 'FOR.1' LIMIT 1").fetchone()[0]
    b = ON.for_formation(c, cod)
    acc = {j["id"]: j["acces"] for j in b["metiers"]}
    assert acc == {"MET.1": "direct", "MET.2": "poursuite", "MET.5": "direct"}
    assert [j["acces"] for j in b["metiers"]] == sorted(acc.values())          # direct first
    cpge = c.execute("SELECT cod_aff_form FROM core.onisep_link WHERE fili = 'CPGE' LIMIT 1").fetchone()[0]
    assert ON.for_formation(c, cpge) is None
    gmp = c.execute("SELECT cod_aff_form FROM core.onisep_link WHERE regle = 'but_sans_fiche' LIMIT 1").fetchone()[0]
    assert ON.for_formation(c, gmp)["status"] == "sans_fiche"


def test_red_team_on_synthetic(syn):
    import redteam_onisep as R
    db, src = syn
    failed = [r for r in R.run(db, sources=src) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.onisep_formation").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse without the Onisep tables")
def test_red_team_on_real_data():
    import redteam_onisep as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed


def test_build_without_the_jobs_file(tmp_path, syn):
    """Codex finding: with the formations sheet alone, the build must go on (jobs listed, access level unknown)."""
    db, src = syn
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year AS SELECT * FROM src.core.formation_year")
    out = ON.build(con, {"formations": src["formations"]})
    assert out["metiers"] == 0 and out["links"] > 0
    cod = con.execute("SELECT cod_aff_form FROM core.onisep_link WHERE for_id = 'FOR.1' LIMIT 1").fetchone()[0]
    b = ON.for_formation(con, cod)
    assert {j["id"] for j in b["metiers"]} == {"MET.1", "MET.2", "MET.5"} and all(j["acces"] is None for j in b["metiers"])
    assert {j["nom"] for j in b["metiers"]} >= {"comptable"}                  # names from the formations sheet
    assert ON.build(con, {})["formations"] == 0
