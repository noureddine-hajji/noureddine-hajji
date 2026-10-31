"""A3: bac-général position of a mention (partial identification) and its red team."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import journey as J  # noqa: E402
from synthetic import make_raw  # noqa: E402

REAL_DB = ROOT / "data" / "suptracker.duckdb"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("mentions")
    make_raw(d / "raw")
    return build_mod.build(d / "raw", d / "w.duckdb")


def test_worked_example():
    # 50 bac général (30 with a mention), 10 bac techno (4 with a mention); all-series ladder:
    # 24 sans, 14 AB, 10 B, 8 TB, 2 TBF, 2 unknown
    c = {"acc_bg": 50, "acc_bg_mention": 30, "acc_bt_mention": 4, "acc_bp_mention": 0, "acc_sansmention": 24,
         "acc_ab": 14, "acc_b": 10, "acc_tb": 8, "acc_tbf": 2, "acc_mention_non_renseignee": 2}
    # sans mention: p = 20 BG without a mention, of which up to 2 may be unknown -> [18, 20]
    assert J.bg_cdf_bounds("sansmention", c) == (18, 20)
    # AB: BG with AB in [max(0, 14-4, 30-20), min(14, 30)] = [10, 14]
    assert J.bg_cdf_bounds("ab", c) == (28, 34)


def test_stage2_carries_the_bg_view(db):
    c = duckdb.connect(str(db), read_only=True)
    r = J.stage2(c, "MATHS+SES", "ab", "cpge ecg")
    with_bg = [f for f in r["formations"] if f["bg"]]
    assert with_bg
    for f in with_bg:
        lo, hi = f["bg"]["bounds"]
        assert lo <= f["bg"]["cdf_used"] <= hi and f["bg"]["ci"][0] <= lo and hi <= f["bg"]["ci"][1]


def test_red_team_on_synthetic(db):
    import redteam_mentions as R
    failed = [r for r in R.run(db) if not r["ok"]]
    assert not failed, failed


@pytest.mark.skipif(not REAL_DB.exists(), reason="real warehouse not present")
def test_red_team_on_real_data():
    import redteam_mentions as R
    c = duckdb.connect(str(REAL_DB), read_only=True)
    has = c.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_name = 'formation_year' AND column_name = 'acc_bg_mention'""").fetchone()[0]
    c.close()
    if not has:
        pytest.skip("warehouse predates acc_bg_mention")
    failed = [r for r in R.run(REAL_DB, real=True) if not r["ok"]]
    assert not failed, failed
