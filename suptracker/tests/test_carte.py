"""Sprint "Carte": the formations of one filière on a map, coloured by the student's zone, and the red team."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import build as build_mod  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_base_map_is_self_hosted_and_small():
    g = json.loads((ROOT / "suptracker" / "static" / "geo" / "france.json").read_text())
    assert [a["id"] for a in g["areas"]] == ["metro", "971", "972", "973", "974", "976"]
    assert sum(len(a["departements"]) for a in g["areas"]) == 101
    assert (ROOT / "suptracker" / "static" / "geo" / "france.json").stat().st_size < 300_000


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("carte")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


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


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_carte as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
