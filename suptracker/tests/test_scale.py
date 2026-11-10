"""Sprint 10 (scale): cache policy, lighter "Mon parcours" answers, audience count from the page, CI and monitor."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import cache as CACHE  # noqa: E402
from suptracker import journey as J  # noqa: E402
from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("scale")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None,
                           onisep_sources={})


def test_header_rules():
    h = lambda path, st=200, v=None, m="GET": CACHE.header(m, path, v, st, "abc")  # noqa: E731
    assert h("/api/formation/12") == CACHE.PUBLIC and h("/api/formation/12", 404) == "no-store"
    assert h("/api/search") == h("/api/voeux") == h("/api/e", m="POST") == h("/api/nope") == "no-store"
    assert h("/static/app.js", v="abc") == CACHE.IMMUTABLE and h("/static/app.js", v="old") == h("/static/app.js") == CACHE.SHORT
    assert h("/") is None and h("/api/lycees") is None


def test_guarded_rounding_never_changes_the_printed_number():
    assert J._round(0.7444999439278813) == 0.7444999439278813        # 74.4 % stays 74.4 %
    assert J._round(0.123456789) == 0.123457
    assert J._round({"a": [0.5, 1.0000004]}) == {"a": [0.5, 1.0]}


def test_red_team_on_synthetic(db):
    import redteam_scale as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


def _has(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        n = con.execute("SELECT count(*) FROM core.taxonomy_link").fetchone()[0]
        con.close()
        return n > 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _has(REAL_DB)), reason="real warehouse absent")
def test_red_team_on_real_data():
    import redteam_scale as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
