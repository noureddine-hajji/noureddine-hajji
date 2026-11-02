"""Sprint 9, B5: the CROUS residences near a formation (step 1: the raw source is staged for the data check)."""
from __future__ import annotations

from pathlib import Path

from . import config


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> int | None:
    """ref.crous_logement: the CNOUS residences as published (a few hundred rows). Kept as is when the raw file is absent."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    path = Path(raw_dir) / "crous_logement.parquet"
    if not path.exists():
        con.execute("CREATE TABLE IF NOT EXISTS ref.crous_logement (_absent BOOLEAN)")
        return None
    con.execute(f"CREATE OR REPLACE TABLE ref.crous_logement AS SELECT * FROM read_parquet('{path}')")
    return con.execute("SELECT count(*) FROM ref.crous_logement").fetchone()[0]


def build(con, raw_dir: Path = config.RAW_DIR) -> dict:
    return {"raw": build_raw(con, raw_dir)}
