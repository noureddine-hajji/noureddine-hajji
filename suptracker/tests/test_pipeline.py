import importlib
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker.crosswalk import EXACT, INFERRED  # noqa: E402
from suptracker.urls import extract_cod_aff_form, is_uai  # noqa: E402
from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

verify = importlib.import_module("verify_ground_truth")


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("wh")
    plan = make_raw(d / "raw")
    db = cached_build(d / "raw", d / "w.duckdb")
    return d, db, plan


@pytest.fixture(scope="session")
def con(built):
    c = duckdb.connect(str(built[1]), read_only=True)
    yield c
    c.close()


def lineage_of(con, session, cod):
    return con.execute("SELECT lineage_id, lineage_confidence FROM core.lineage WHERE session=? AND cod_aff_form=?",
                       [session, cod]).fetchone()


def test_schema_drift_is_resolved(con):
    missing = con.execute("""SELECT session, canonical FROM meta.schema_audit WHERE status = 'missing'
                             AND canonical IN ('acc_tot','acc_term','taux_acces_ens','acc_mention_non_renseignee',
                                               'part_terminale_generale_en_position_admis_pp','cod_aff_form')""").fetchall()
    assert missing == []
    alias = con.execute("""SELECT upstream FROM meta.schema_audit WHERE session=2023 AND canonical='taux_acces_ens'""")
    assert alias.fetchone()[0] == "taux_acces"
    assert con.execute("SELECT count(DISTINCT session) FROM core.formation_year").fetchone()[0] == 4


def test_recoded_formation_is_linked_and_flagged(con, built):
    old, new = built[2]["recoded"]
    a, b = lineage_of(con, 2023, old), lineage_of(con, 2024, new)
    assert a == b and a[1] == INFERRED
    link = con.execute("SELECT link_type FROM core.crosswalk_link WHERE cod_aff_form_from=? AND cod_aff_form_to=?",
                       [old, new]).fetchone()
    assert link[0] == INFERRED


def test_ambiguous_recoding_is_not_linked(con):
    for old, new in (("1010", "9010"), ("1011", "9011")):
        assert lineage_of(con, 2023, old)[0] != lineage_of(con, 2024, new)[0]
    assert con.execute("SELECT count(*) FROM core.crosswalk_audit WHERE cod_aff_form_to IN ('9010','9011')"
                       ).fetchone()[0] >= 2


def test_gap_year_bridged_with_exact_id(con, built):
    cod = built[2]["gap"]
    assert lineage_of(con, 2022, cod) == lineage_of(con, 2025, cod)
    assert lineage_of(con, 2025, cod)[1] == EXACT
    assert con.execute("SELECT count(*) FROM core.lineage WHERE lineage_id = ?",
                       [lineage_of(con, 2025, cod)[0]]).fetchone()[0] == 3


def test_new_formation_has_single_year_lineage(con, built):
    lid = lineage_of(con, 2025, built[2]["new_2025"])[0]
    assert con.execute("SELECT count(*) FROM core.lineage WHERE lineage_id=?", [lid]).fetchone()[0] == 1


def test_subwish_pool_flagged_and_not_summed(con, built):
    flags = con.execute("""SELECT bool_and(subwish_flag), bool_and(subwish_pool_flag), count(DISTINCT subwish_group_id)
                           FROM core.formation_year WHERE session=2025 AND cod_aff_form IN (SELECT unnest(?))""",
                        [built[2]["pool"]]).fetchone()
    assert flags == (True, True, 1)
    assert con.execute("SELECT count(*) FROM core.formation_year WHERE subwish_flag AND fili <> 'Ecole d''Ingénieur'"
                       ).fetchone()[0] == 0


def test_low_n_excluded_from_profile_reference_but_access_rate_kept(con, built):
    rows = dict(con.execute("""SELECT metric, peer_percentile IS NOT NULL FROM mart.peer_rank
                               WHERE session=2025 AND cod_aff_form=?""", [built[2]["low_n"]]).fetchall())
    assert rows["taux_acces_ens"] is True
    assert rows["pct_tb_tbf"] is False and rows["pct_bours"] is False
    assert con.execute("SELECT low_n_flag FROM core.formation_year WHERE session=2025 AND cod_aff_form=?",
                       [built[2]["low_n"]]).fetchone()[0]


def test_geometry_coordinates_parsed(con):
    typ = con.execute("""SELECT column_type FROM meta.raw_columns WHERE dataset='parcoursup_2025'
                         AND column_name='g_olocalisation_des_formations'""").fetchone()[0]
    assert typ.startswith("GEOMETRY")
    lat, lon = con.execute("SELECT lat, lon FROM core.formation_year WHERE session=2025 AND cod_aff_form='1101'").fetchone()
    assert (lat, lon) == (48.85, 2.35)


def test_peer_percentiles_bounded(con):
    lo, hi = con.execute("SELECT min(peer_percentile), max(peer_percentile) FROM mart.peer_rank").fetchone()
    assert 0 <= lo <= hi <= 100


def test_verification_passes_on_consistent_data(built):
    d, db, _ = built
    rep = verify.run(db, d / "raw")
    assert rep["overall"] == "PASS", rep
    total = next(r for r in rep["continuity"] if r["fili"] == "TOTAL")
    assert 0 < total["pct_full_span"] <= 100


def test_app_js_calls_only_defined_helpers():
    # every classic script loaded by index.html shares one global scope
    js = "\n".join((ROOT / "suptracker" / "static" / f).read_text() for f in ("app.js", "stats.js"))
    html = (ROOT / "suptracker" / "static" / "index.html").read_text()
    assert html.index("/static/app.js") < html.index("/static/stats.js")
    defined = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", js))
    defined |= set(re.findall(r"const\s+([A-Za-z_]\w*)\s*=\s*(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>", js))
    called = set(re.findall(r"(?<![.\w])([a-z]\w*(?:Card|Chart|Bars|Bar|Badge)|view[A-Z]\w*)\s*\(", js))
    assert called <= defined, called - defined


@pytest.mark.parametrize("url,expected", [
    ("https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod=6170&typeBac=0", "6170"),
    ("dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?typeBac=0&g_ta_cod=42", "42"),
    ("https://evil.example.com/?g_ta_cod=6170", None),
    ("https://www.parcoursup.fr/", None),
])
def test_fiche_url_regex(url, expected):
    assert extract_cod_aff_form(url) == expected


def test_uai():
    assert is_uai("0751234A") and not is_uai("075123A")


def test_api(built, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SUPTRACKER_DB", str(built[1]))
    from suptracker import api
    api._con.cache_clear()
    c = TestClient(api.app)
    url = "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod=9003"
    r = c.get("/api/search", params={"q": url}).json()
    assert r["mode"] == "cod_aff_form" and r["results"][0]["cod_aff_form"] == "9003"
    assert c.get("/api/search", params={"q": "https://example.com/x"}).status_code == 422
    f = c.get("/api/formation/9003").json()
    assert [h["session"] for h in f["history"]] == [2022, 2023, 2024, 2025]
    assert any(w["code"] == "lineage" for w in f["warnings"])
    fil = c.get("/api/filiere", params={"fil": "Formation d'ingénieur Bac + 5 - bac général", "session": 2025}).json()
    one = c.get("/api/formation/2001").json()["record"]["voe_tot"]
    assert fil["n_formations"] == 4 and fil["voe_tot_dedup_subwish"] == one  # pool counted once, not 4x
    assert c.get("/api/formation/does-not-exist").status_code == 404
    spe = c.get("/api/specialites", params={"session": 2025}).json()
    assert spe["formation_type"] in spe["formation_types"] and spe["rows"]
    assert abs(sum(r["pct_acceptations"] for r in spe["rows"]) - 100) < 0.5
    assert spe["formation_type"] == "Ensemble des bacheliers"   # level 0, the largest
    but = c.get("/api/specialites", params={"session": 2025, "formation_type": "BUT Service"}).json()
    raw25 = pd.read_parquet(built[0] / "raw" / "specialites_2025.parquet")
    lvl1 = raw25[(raw25.niveau_d_agregation == "1") & (raw25.regroupement_de_formations == "BUT Service")]
    assert but["totals"]["n_accepte"] == lvl1.acceptations.sum()   # level-2 detail not double counted
    other = c.get("/api/specialites", params={"session": 2023, "formation_type": "CPGE ECG"}).json()
    assert other["formation_type"] == "CPGE ECG" and all(r["formation_type"] == "CPGE ECG" for r in other["rows"])
    assert c.get("/").status_code == 200
    assert c.get("/api/verification").status_code == 404  # no report written next to this warehouse
    verify.main(["--db", str(built[1]), "--raw-dir", str(built[0] / "raw"),
                 "--out", str(built[1].parent / "verification")])
    v = c.get("/api/verification").json()
    assert v["overall"] == "PASS" and v["identities"]
    assert c.get("/api/continuity").json()["rows"][0]["fili"] == "TOTAL"


def test_no_access_rate_derived_from_offers_over_wishes():
    src = "\n".join(p.read_text() for p in (ROOT / "suptracker").rglob("*.py"))
    src += (ROOT / "suptracker" / "static" / "app.js").read_text()
    assert not re.search(r"prop_tot\s*\)?\s*/\s*\(?\s*(nb_)?voe_(tot|pp)", src)
