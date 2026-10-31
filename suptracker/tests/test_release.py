"""Release guards: what is deployed is what was built, and no feature silently disappears."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATIC = ROOT / "suptracker" / "static"

# every shipped feature and the front-end entry point that renders it: removing one fails CI
FEATURE_ENTRY_POINTS = {
    "search": ("app.js", "function viewSearch"),
    "analytics": ("stats.js", "async function viewStats"),
    "feedback": ("app.js", "function feedbackBox"),
    "offer_timing": ("app.js", "function timingCard"),
    "offer_options": ("app.js", "function offerCard"),
    "bg_mention_bounds": ("app.js", "function bgCell"),
    "series_journey": ("app.js", "function stage1SeriesMatrix"),
    "plan_b": ("app.js", "async function loadPlanB"),
    "plan_b_parcours": ("app.js", "data-planb="),
}


def test_every_feature_is_still_shipped():
    missing = [f for f, (file, needle) in FEATURE_ENTRY_POINTS.items() if needle not in (STATIC / file).read_text()]
    assert not missing, missing


def test_every_feature_is_wired():
    js = (STATIC / "app.js").read_text()
    assert "loadPlanB(r.cod_aff_form)" in js and "${timingCard(r, d.history)}" in js and "${offerCard(r)}" in js
    assert 'if (a === "stats") return await viewStats(b)' in js
    assert '<script src="/static/stats.js"></script>' in (STATIC / "index.html").read_text()


def test_page_versions_its_assets_and_is_not_cached(monkeypatch):
    monkeypatch.setenv("SUPTRACKER_ANALYTICS", "off")
    from fastapi.testclient import TestClient

    from suptracker import api
    c = TestClient(api.app)
    r = c.get("/")
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
    assert refs and all("?v=" in u for u in refs), refs
    assert r.headers["cache-control"] == "no-cache"
    v = c.get("/api/version")
    assert v.headers["cache-control"] == "no-store"
    body = v.json()
    assert set(body["features"]) >= {"plan_b", "series_journey", "offer_timing", "analytics"}
    assert all(f"?v={body['assets']}" in u for u in refs)


def test_commit_comes_from_the_platform(monkeypatch):
    from suptracker import api
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abcdef1234567")
    assert api._commit() == "abcdef1"
