"""Sprint 7: gateways and reorientations.

Stage 1 (data reconnaissance): the MonMaster open data (SIES portal, 2023 and 2024-2025 exports)
is copied as is into ref.monmaster_raw, with the dataset it came from, so its fields, units and
coverage can be checked on real data before the feature is designed.
"""
from __future__ import annotations

from pathlib import Path

from . import config

MONMASTER = ("monmaster_2024_2025", "monmaster_2023")


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> int:
    """ref.monmaster_raw: every MonMaster row as published (union by column name); empty when absent."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    paths = [(k, Path(raw_dir) / f"{k}.parquet") for k in MONMASTER]
    paths = [(k, p) for k, p in paths if p.exists()]
    if not paths:
        con.execute("CREATE OR REPLACE TABLE ref.monmaster_raw (_source VARCHAR)")
        return 0
    union = " UNION ALL BY NAME ".join(f"SELECT '{k}' AS _source, * FROM read_parquet('{p}')" for k, p in paths)
    con.execute(f"CREATE OR REPLACE TABLE ref.monmaster_raw AS {union}")
    return con.execute("SELECT count(*) FROM ref.monmaster_raw").fetchone()[0]
