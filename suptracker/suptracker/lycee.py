"""Sprint 4, lycée profile: social position index (IPS) and value added (IVAL) of lycées.

Both come from the Education ministry's open-data portal and are keyed by the lycée's UAI. They
describe the student's lycée as CONTEXT: no open dataset crosses Parcoursup admissions with the
lycée of origin, so nothing here changes a positioning.
"""
from __future__ import annotations

from pathlib import Path

from . import config

RAW = {"ips": "ips_lycees", "ival": "ival_lycees_gt"}


def build_lycees(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """Stage the raw lycée tables (ref.lycee_ips_raw, ref.lycee_ival_raw); empty when absent."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    out = {}
    for key, name in RAW.items():
        path = Path(raw_dir) / f"{name}.parquet"
        if path.exists():
            con.execute(f"CREATE OR REPLACE TABLE ref.lycee_{key}_raw AS SELECT * FROM read_parquet('{path}')")
        else:
            con.execute(f"CREATE OR REPLACE TABLE ref.lycee_{key}_raw (uai VARCHAR)")
        out[key] = con.execute(f"SELECT count(*) FROM ref.lycee_{key}_raw").fetchone()[0]
    return out
