"""A2 (offer timing) and A4 (offer options): decoding, search filters, API, red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import search as S  # noqa: E402
from suptracker.harmonize import carto_flags  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("offer")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb")


@pytest.mark.parametrize("app,internat,amg,expect", [
    ("Formations en apprentissage", "", "Enseignement en présentiel",
     {"apprentissage": True, "internat": "non", "distance": "aucune", "amenag_sport": False, "amenag_art": False}),
    ("", "Etablissements avec internat pour filles et garçons",
     "Enseignement partiellement à distance,Formations avec aménagements pour sportifs haut niveau",
     {"apprentissage": False, "internat": "mixte", "distance": "partielle", "amenag_sport": True, "amenag_art": False}),
    ("", "Etablissements avec internat pour garçons", "Enseignement à distance,Formations avec aménagements pour artistes haut niveau",
     {"apprentissage": False, "internat": "garcons", "distance": "totale", "amenag_sport": False, "amenag_art": True}),
    (None, None, None,
     {"apprentissage": None, "internat": None, "distance": None, "amenag_sport": None, "amenag_art": None}),
])
def test_carto_flags(app, internat, amg, expect):
    assert carto_flags(app, internat, amg) == expect


def test_latest_cartographie_session_wins(db):
    c = duckdb.connect(str(db), read_only=True)
    r = c.execute("""SELECT carto_session, internat, amenag_sport FROM core.formation_year
                     WHERE cod_aff_form = '1100' AND session = 2025""").fetchone()
    assert r == (2026, "mixte", True)          # the 2025 listing had no internat


def test_timing_fields_are_harmonised_across_vintages(db):
    c = duckdb.connect(str(db), read_only=True)
    rows = c.execute("""SELECT session, count(pct_acc_debutpp), count(*) FROM core.formation_year GROUP BY 1""").fetchall()
    assert all(n == tot for _, n, tot in rows)  # 2022 has upper-cased columns, still resolved


def test_internat_phrase_becomes_a_filter(db):
    c = duckdb.connect(str(db), read_only=True)
    S._CACHE.clear()
    r = S.search(c, "avec internat", limit=50)
    assert r["total"] >= 1 and all(x["internat"] in ("mixte", "filles", "garcons", "oui") for x in r["results"])
    assert {"type": "option", "value": "internat"} in r["interpretation"]
    assert S.APPRENTICESHIP_NOTE in S.search(c, "bts alternance")["notes"]
    with pytest.raises(ValueError):
        S.search(c, "bts", options=("apprentissage",))


def test_api_options_and_fiche(db, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SUPTRACKER_DB", str(db))
    monkeypatch.setenv("SUPTRACKER_ANALYTICS", "off")
    from suptracker import api
    api._con.cache_clear()
    S._CACHE.clear()
    c = TestClient(api.app)
    assert c.get("/api/search", params={"q": "mpsi", "options": "internat,sport"}).status_code == 200
    assert c.get("/api/search", params={"q": "mpsi", "options": "handicap"}).status_code == 422
    f = c.get("/api/formation/1100").json()
    assert f["record"]["internat"] == "mixte" and f["record"]["pct_acc_debutpp"] is not None
    assert all("pct_acc_finpp" in h for h in f["history"])
    assert "timing" in c.get("/api/meta").json()["methodology"]


def test_red_team_on_synthetic(db):
    import redteam_offer as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_offer as R
    c = duckdb.connect(str(REAL_DB), read_only=True)
    has = c.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_name = 'formation_year' AND column_name = 'pct_acc_debutpp'""").fetchone()[0]
    c.close()
    if not has:
        pytest.skip("warehouse predates the offer columns")
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
