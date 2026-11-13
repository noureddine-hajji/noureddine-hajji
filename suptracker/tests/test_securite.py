"""Sprint Q2 (owner, 2026-11-13): security headers, HEAD, the contact form's cross-site guard, hostile inputs, through
the red team (SE1-SE10) on the synthetic warehouse and on the real one. The browser check runs with
`python scripts/redteam_securite.py --browser`."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import cached_build, make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("securite")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None,
                        onisep_sources={})


def test_red_team_on_synthetic(db):
    import redteam_securite as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_securite as R
    failed = [r for r in R.run(REAL_DB) if not r["ok"]]
    assert not failed, failed
