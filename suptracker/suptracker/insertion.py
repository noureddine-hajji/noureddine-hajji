"""Sprint 8: professional insertion after a diploma.

Stage 1 (data reconnaissance): InserSup (SIES: university diplomas) and Inserjeunes (DEPP: BTS
and other vocational diplomas in lycées and in apprenticeship centres) are copied as is into
ref.<key>_raw, so their grain, units, masking and keys can be checked on real data before the
feature is designed.
"""
from __future__ import annotations

from pathlib import Path

from . import config

RAW = ("insersup", "inserjeunes_lycee", "inserjeunes_cfa")


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """ref.<key>_raw for each source; kept as is when the raw file is absent (development copy)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    out = {}
    for key in RAW:
        path = Path(raw_dir) / f"{key}.parquet"
        if path.exists():
            con.execute(f"CREATE OR REPLACE TABLE ref.{key}_raw AS SELECT * FROM read_parquet('{path}')")
        else:
            con.execute(f"CREATE TABLE IF NOT EXISTS ref.{key}_raw (_absent BOOLEAN)")
        out[key] = con.execute(f"SELECT count(*) FROM ref.{key}_raw").fetchone()[0]
    return out
