import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import analytics as A  # noqa: E402
from suptracker import build as build_mod  # noqa: E402
from synthetic import make_raw  # noqa: E402


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    d = tmp_path_factory.mktemp("analytics")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb")


def test_red_team(warehouse):
    import redteam_analytics as R
    res = R.run(Path(warehouse))
    failed = [r for r in res if not r["ok"]]
    assert not failed, failed
    assert len(res) == 22


@pytest.mark.parametrize("q,expect", [
    ("Prépa HEC Lyon", "prepa hec lyon"),
    ("moi@mail.fr droit", "[email] droit"),
    ("0612345678", "[num]"),
    ("06 12 34 56 78 bts", "[num] bts"),
    ("<script>alert(1)</script>", "script alert 1 script"),
    ("https://parcoursup.fr/x?y=1 iut", "[url] iut"),
])
def test_clean_query(q, expect):
    assert A.clean_query(q) == expect


@pytest.mark.parametrize("ref,src", [
    (None, "direct"), ("www.google.fr", "moteur"), ("dossierappel.parcoursup.fr", "parcoursup"),
    ("ent.ac-versailles.fr", "ent"), ("l.instagram.com", "social"), ("evil.example", "autre"),
    ("<script>", "autre"), ("x" * 500, "autre"),
])
def test_source_of(ref, src):
    assert A.source_of(ref) == src


def test_phases():
    assert A.phase_of(date(2027, 2, 1)) == "Formulation des vœux"
    assert A.phase_of(date(2026, 12, 25)) == "Découverte des formations"
    assert A.phase_of(date(2027, 1, 3)) == "Découverte des formations"     # wraps over new year
    assert A.phase_of(date(2026, 10, 31)) is None


def test_summary_over_days_and_periods(tmp_path, monkeypatch):
    A.reset_store(A.SqliteStore(tmp_path / "c.sqlite"))
    end = date(2027, 2, 14)
    h = lambda i: {"user-agent": "Mozilla/5.0", "x-real-ip": f"10.0.0.{i}"}  # noqa: E731
    try:
        for back, n in ((0, 5), (1, 3), (8, 2)):           # 8 visitors in the 7-day window, 2 before
            monkeypatch.setattr(A, "today", lambda d=end - timedelta(days=back): d)
            for i in range(n):
                A.record("view", {"route": "home", "device": "mobile", "source": "moteur"}, h(i))
                A.record("search", {"q": "droit", "total": 3 if i else 0, "partial": False}, h(i))
            if back == 0:
                A.record("view", {"route": "fiche", "device": "mobile", "source": None, "cod": "42"}, h(0))
                A.record("out", {"cod": "42"}, h(0))
        monkeypatch.setattr(A, "today", lambda: end)
        r = A.summarize(7)
    finally:
        A.reset_store(None)
    assert r["period"] == {"start": "2027-02-08", "end": "2027-02-14", "days": 7,
                           "previous_start": "2027-02-01", "previous_end": "2027-02-07"}
    assert [x["visitors"] for x in r["daily"]][-2:] == [3, 5] and r["daily"][-1]["phase"] == "Formulation des vœux"
    k = {x["name"]: x for x in r["kpis"]}
    assert k["Visiteurs uniques (visiteurs-jours)"]["value"] == 8 and k["Visiteurs uniques (visiteurs-jours)"]["previous"] == 2
    assert k["Recherches sans résultat"]["value"] == pytest.approx(2 / 8)
    assert [s["visitors"] for s in r["funnel"]] == [8, 8, 1, 1]
    assert r["top_queries"] == [{"key": "droit", "visitor_days": 8}]       # per visitor-day, k >= 3
    assert r["sources"]["moteur"] == 8 and r["devices"]["mobile"] == 8


def test_default_store_follows_the_data_volume(tmp_path, monkeypatch):
    for v in ("SUPTRACKER_ANALYTICS_DIR", "VERCEL", "UPSTASH_REDIS_REST_URL", "KV_REST_API_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("suptracker.config.DATA_DIR", tmp_path)
    A.reset_store(None)
    try:
        assert A.store().path == tmp_path / "analytics" / "counters.sqlite"
    finally:
        A.reset_store(None)
