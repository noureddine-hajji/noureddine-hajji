import importlib
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import search as S  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


# ---------------------------------------------------------------- normalisation (no data)
@pytest.mark.parametrize("a,b", [
    ("Médecine", "medecine"), ("I.U.T de Toulouse", "iut de toulouse"), ("St Étienne", "saint etienne"),
    ("ＬＹＯＮ", "lyon"), ("aix-en-provence", "aix en provence"), ("l'iut", "l iut"),
])
def test_fold(a, b):
    assert S.fold(a) == b


def test_stem_plural_and_feminine():
    assert S.stem("infirmieres") == "infirmier" and S.stem("infirmiere") == "infirmier"
    assert S.stem("licences") == "licence" and S.stem("process") == "process"


def test_phrases_handle_plurals_and_acronyms():
    assert S._apply_phrases("ecoles d ingenieurs") == "t_eing"
    assert S._apply_phrases("prepa hec lyon") == "t_ecg lyon"
    assert S._apply_phrases("bts ndrc") == "t_bts t_ndrc"
    assert S._apply_phrases("sciences po") == "t_scpo"


def test_clean_complement_drops_repetitions():
    d = {"lib_comp_voe_ins": "Université X - Licence - Portail Droit", "g_ea_lib_vx": "Université X",
         "fili": "Licence", "fil_lib_voe_acc": "Droit", "form_lib_voe_acc": "Licence - Droit-économie-gestion"}
    assert S.clean_complement(d) == "Portail Droit"


# ---------------------------------------------------------------- engine on the synthetic warehouse
@pytest.fixture(scope="module")
def con(tmp_path_factory):
    d = tmp_path_factory.mktemp("search")
    make_raw(d / "raw")
    db = build_mod.build(d / "raw", d / "w.duckdb")
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


def test_acronym_and_place(con):
    r = S.search(con, "MPSI Marseille")
    assert r["total"] >= 1 and all(x["fil_lib_voe_acc"] == "MPSI" for x in r["results"])
    assert {i["type"] for i in r["interpretation"]} >= {"lieu", "sigle"}


def test_typo_and_prefix(con):
    assert S.search(con, "comptabilte")["total"] >= 1          # one typo
    assert S.search(con, "mathemat")["total"] >= 1             # prefix


def test_health_note(con):
    r = S.search(con, "médecine")
    assert r["notes"] and r["total"] == 0 or r["notes"]       # fixture has no PASS: the note still explains


def test_index_is_built_once_per_warehouse(con):
    S._CACHE.clear()
    a = S.get_index(con.cursor())
    b = S.get_index(con.cursor())          # a new cursor per request, as in the API
    assert a is b and len(S._CACHE) == 1


@pytest.mark.parametrize("q", ["", " ", "%", "' OR 1=1 --", "<script>alert(1)</script>", "x" * 5000, "de la", "🙂"])
def test_hostile_inputs_are_inert(con, q):
    r = S.search(con, q)
    assert r["total"] == 0 and r["results"] == [] and len(r["query"]) <= S.MAX_QUERY_CHARS


def test_facets_are_disjunctive_and_exact(con):
    r = S.search(con, "licence", fili="Licence")
    for a in r["facets"]["academie"]:
        assert S.search(con, "licence", fili="Licence", academie=a["value"])["total"] == a["count"]


def test_pagination_and_determinism(con):
    full = [x["cod_aff_form"] for x in S.search(con, "licence", limit=10)["results"]]
    p1 = [x["cod_aff_form"] for x in S.search(con, "licence", limit=5)["results"]]
    p2 = [x["cod_aff_form"] for x in S.search(con, "licence", offset=5, limit=5)["results"]]
    assert p1 + p2 == full and not set(p1) & set(p2)


def test_api_search(con, monkeypatch, tmp_path_factory):
    from fastapi.testclient import TestClient

    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()[0]
    monkeypatch.setenv("SUPTRACKER_DB", db)
    from suptracker import api
    api._con.cache_clear()
    c = TestClient(api.app)
    r = c.get("/api/search", params={"q": "MPSI", "limit": 2}).json()
    assert r["mode"] == "text" and r["total"] >= 1 and set(r) >= {"facets", "interpretation", "notes", "partial"}
    assert c.get("/api/search", params={"q": "https://evil.example/?g_ta_cod=1"}).status_code == 422
    assert c.get("/api/search", params={"q": "x", "limit": 500}).status_code == 422


# ---------------------------------------------------------------- quality gate on the real warehouse
@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_search_quality_gate_on_real_data():
    E = importlib.import_module("eval_search")
    H = importlib.import_module("holdout_search")
    H2 = importlib.import_module("holdout2_search")
    R = importlib.import_module("redteam_search")
    real = duckdb.connect(str(REAL_DB), read_only=True)
    gold = list(E.GOLD)
    try:
        for name, qs, floor in (("gold", gold, 100.0), ("holdout1", H.HOLDOUT, 95.0), ("holdout2", H2.HOLDOUT2, 95.0)):
            E.GOLD[:] = qs
            rep = E.evaluate(real, E.new_search)
            assert rep["pass_rate"] >= floor and rep["zero_results"] == 0, \
                (name, [q for q in rep["queries"] if not q["pass"]])
    finally:
        E.GOLD[:] = gold
    failed = [r for r in R.run(real, n_load=300) if not r["ok"]]
    assert not failed, failed
