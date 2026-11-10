"""Similar formations' reports (doublettes and jury expectations where the own report lacks them) and the profile bar."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import semblables as SB  # noqa: E402
from suptracker import build as build_mod  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


def test_field_mapping_reads_wrapped_labels():
    assert SB.champ_of("Résultat académique") == "resultats"
    assert SB.champ_of("Compétences académiques, acquis méthodologiques, savoir- faire") == "competences"
    assert SB.champ_of("Engagements, activités et centres d’ intérêt, réalisations péri ou extra-") == "engagements"
    assert SB.champ_of("formation, cohérence du projet") == "motivation"
    assert SB.champ_of("Bulletins") is None


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    d = tmp_path_factory.mktemp("semblables")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb", success_source=None, poursuite_sources=None, cereq_source=None)


def test_red_team_on_synthetic(syn):
    import redteam_semblables as R
    failed = [r for r in R.run(syn) if not r["ok"]]
    assert not failed, failed


def _ok(path):
    try:
        con = duckdb.connect(str(path), read_only=True)
        con.execute("SELECT count(*) FROM mart.semblable_dbl")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not (REAL_DB.exists() and _ok(REAL_DB)), reason="real warehouse not available")
def test_red_team_on_real_data():
    import redteam_semblables as R
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
