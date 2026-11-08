"""Sprint 17: indexable pages (/formation, /metier, sitemap, robots), the SupCompass name, and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import seo as SEO  # noqa: E402
from synthetic import make_onisep_zips, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_json_ld_cannot_close_the_script():
    s = SEO.json_ld({"name": "</script><script>alert(1)</script> & co"})
    assert "</" not in s and "<" not in s and "&" not in s


def test_base_url_prefers_the_production_domain(monkeypatch):
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "supcompass.fr")
    assert SEO.base_url("evil.example") == "https://supcompass.fr"
    monkeypatch.delenv("VERCEL_PROJECT_PRODUCTION_URL")
    assert SEO.base_url("a.test:8765") == "https://a.test:8765"
    assert SEO.base_url('x"><script>') == "https://localhost"


def test_preview_is_never_indexed(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert SEO.robots("https://x") == "User-agent: *\nDisallow: /\n"
    assert 'content="noindex, follow"' in SEO.head_tags("t", "d", "https://x/", True, None)


def test_french_figures():
    assert SEO.num(1094) == "1 094" and SEO.pct(43.0) == "43 %" and SEO.pct(47.5) == "47,5 %" and SEO.pct(None) == "—"


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("seo")
    make_raw(d / "raw")
    src = make_onisep_zips(d / "sources")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None, onisep_sources=src)


def test_red_team_on_synthetic(syn):
    import redteam_seo as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.onisep_metier").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse absent")
def test_red_team_on_real_data():
    import redteam_seo as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
