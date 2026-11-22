"""The ground-truth verification against a doctored SIES export or a doctored warehouse (moved out of test_pipeline.py on
2026-11-22: its three full builds in a row made it a 40-minute file, past CI's 45-minute shard limit). Each warehouse comes
from synthetic.cached_build, so a raw export is built once per run and every test mutates its OWN copy."""
import importlib
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from synthetic import cached_build, make_raw  # noqa: E402

verify = importlib.import_module("verify_ground_truth")


@pytest.fixture(scope="module")
def upstream_raw(tmp_path_factory):
    """The synthetic export where SIES itself does not add up: one more bac général admit for 1100 in 2024."""
    raw = tmp_path_factory.mktemp("upstream") / "raw"
    make_raw(raw)
    p = raw / "parcoursup_2024.parquet"
    df = pd.read_parquet(p)
    df.loc[df.cod_aff_form == "1100", "acc_bg"] += 1   # SIES export itself does not add up
    df.to_parquet(p, index=False)
    return raw


def test_upstream_inconsistency_is_flagged_not_failed(upstream_raw, tmp_path):
    db = cached_build(upstream_raw, tmp_path / "w.duckdb")
    rep = verify.run(db, upstream_raw)
    series = next(r for r in rep["identities"] if r["check"] == "series_eq_acc_neobac" and r["session"] == 2024)
    assert series["status"] == "upstream_inconsistency" and series["sample_violators"] == ["1100"]
    assert rep["overall"] == "PASS"
    c = duckdb.connect(str(db), read_only=True)
    assert c.execute("""SELECT series_sum_mismatch FROM core.formation_year
                        WHERE session=2024 AND cod_aff_form='1100'""").fetchone()[0] is True
    c.close()


def test_changed_discrepancy_on_upstream_violator_fails(upstream_raw, tmp_path):
    db = cached_build(upstream_raw, tmp_path / "w.duckdb")      # its own copy: the updates below never reach another test
    c = duckdb.connect(str(db))
    c.execute("UPDATE core.formation_year SET acc_bg = acc_bg + 2 WHERE session=2024 AND cod_aff_form='1100'")
    c.close()
    series = lambda rep: next(r for r in rep["identities"]  # noqa: E731
                              if r["check"] == "series_eq_acc_neobac" and r["session"] == 2024)
    assert series(verify.run(db, upstream_raw))["status"] == "fail"     # same key, different discrepancy
    c = duckdb.connect(str(db))
    c.execute("UPDATE core.formation_year SET acc_bg = acc_bg - 3 WHERE session=2024 AND cod_aff_form='1100'")
    c.close()
    assert series(verify.run(db, upstream_raw))["status"] == "fail"     # pipeline silently "repaired" SIES


def test_verification_catches_pipeline_errors(tmp_path):
    raw = tmp_path / "raw"
    make_raw(raw)
    db = cached_build(raw, tmp_path / "w.duckdb")               # the shared synthetic warehouse, copied
    # corrupt the warehouse only: it no longer reproduces the upstream file
    c = duckdb.connect(str(db))
    c.execute("UPDATE core.formation_year SET acc_bg = acc_bg + 1 WHERE session=2024 AND cod_aff_form='1100'")
    c.execute("UPDATE core.formation_year SET taux_acces_ens = taux_acces_ens + 1 WHERE session=2023 AND cod_aff_form='1101'")
    c.close()
    rep = verify.run(db, raw)
    assert rep["overall"] == "FAIL"
    series = next(r for r in rep["identities"] if r["check"] == "series_eq_acc_neobac" and r["session"] == 2024)
    assert series["status"] == "fail" and series["sample_violators"] == ["1100"]
    taux = next(r for r in rep["taux_raw"] if r["session"] == 2023)
    assert taux["sample_mismatch"] == ["1101"]
    assert verify.main(["--db", str(db), "--raw-dir", str(raw), "--out", str(tmp_path / "v"), "--strict"]) == 1
