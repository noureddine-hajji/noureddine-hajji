"""Sprint "Carte": the formations of one filière on a map, coloured by the student's zone, and the red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_leaflet_is_self_hosted_with_its_licence():
    d = ROOT / "suptracker" / "static" / "vendor" / "leaflet"
    assert (d / "leaflet.js").exists() and (d / "leaflet.css").exists() and "BSD" in (d / "LICENSE").read_text()
    assert "leaflet" not in (ROOT / "suptracker" / "static" / "index.html").read_text().lower()


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("carte")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_carte as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        con.execute("SELECT 1 FROM core.taxonomy_link LIMIT 1")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


REAL_OK = REAL_DB.exists() and _ok(REAL_DB)
MUTANT_PARTS = 3          # C8 on real data (12 min) runs in tests/test_carte_mutants_{1,2,3}.py, spread over the CI shards


@pytest.mark.skipif(not REAL_OK, reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_carte as R
    checks = {fn.check_name.split()[0] for fn in R.CHECKS} - {"C8"}
    failed = [r for r in R.run(REAL_DB, real=True, checks=checks) if not r["ok"]]
    assert not failed, failed


def real_mutants(i: int):
    """Part i (1-based) of C8's mutants on the real warehouse."""
    import redteam_carte as R
    res = R.run(REAL_DB, real=True, checks={"C8"}, part=(i - 1, MUTANT_PARTS))
    assert len(res) == 1 and res[0]["ok"], res
