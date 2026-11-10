"""Sprint 11: "Mes vœux" (the list read for the current profile) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import voeux as VX  # noqa: E402
from synthetic import make_raw  # noqa: E402
from synthetic import cached_build  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("voeux")
    make_raw(d / "raw")
    return cached_build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None,
                           onisep_sources={})


def test_clean_ids():
    assert VX.clean_ids([" 12", "12", "", "7"]) == ["12", "7"]
    for bad in (["1 OR 1=1"], ["12a"], [str(i) for i in range(11)]):
        with pytest.raises(ValueError):
            VX.clean_ids(bad)


def test_reading_rules():
    v = lambda z, u=False, s="ok": {"zone": z, "uncertain": u, "status": s}  # noqa: E731
    codes = lambda vs: [m["code"] for m in VX.read_list(vs)["messages"]]  # noqa: E731
    assert codes([]) == []
    assert codes([v("securite", True), v("cible")]) == ["aucune_securite"]               # an uncertain safety is not sure
    assert codes([v("securite"), v("cible"), v("ambitieux")]) == ["equilibree"]
    assert codes([v("securite"), v("ambitieux")]) == ["aucune_cible"]                   # half is not "more than half"
    assert "majorite_ambitieuse" in codes([v("securite"), v("ambitieux"), v("hors_profil")])
    assert "non_ouvert" in codes([v("securite"), v("cible"), v("non_ouvert")])
    assert "non_situe" in codes([v("securite"), v("cible"), v(None, s="absente")])


def test_red_team_on_synthetic(db):
    import redteam_voeux as R
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
    import redteam_voeux as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
