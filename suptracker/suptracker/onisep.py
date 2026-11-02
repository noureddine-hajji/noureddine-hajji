"""Sprint 8 follow-up: the jobs (métiers) a formation leads to, from Onisep's Idéo open data (ODbL).

Step 1: the raw files are staged for the data check (no Onisep dataset carries a Parcoursup code, so the
link to a Parcoursup formation is designed after the real fields and labels are checked)."""
from __future__ import annotations

from pathlib import Path

from . import config

XML_SAMPLE = 300
RAW = ("onisep_formations", "onisep_metiers", "onisep_fiches_formations", "onisep_fiches_metiers")


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """ref.<key> for each Onisep file as published (text). Kept as is when a raw file is absent."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    out = {}
    for key in RAW:
        path = Path(raw_dir) / f"{key}.parquet"
        if not path.exists():
            con.execute(f"CREATE TABLE IF NOT EXISTS ref.{key} (_absent BOOLEAN)")
            out[key] = None
            continue
        # the XML sheets can weigh tens of MB: for the data check, every record's tag and the first records' XML only
        sample = f"SELECT *, row_number() OVER () AS _n FROM read_parquet('{path}')"
        keep = f"SELECT * EXCLUDE (_n) REPLACE (CASE WHEN _n <= {XML_SAMPLE} THEN xml END AS xml) FROM ({sample})" if key.startswith("onisep_fiches") \
            else f"SELECT * FROM read_parquet('{path}')"
        con.execute(f"CREATE OR REPLACE TABLE ref.{key} AS {keep}")
        out[key] = con.execute(f"SELECT count(*) FROM ref.{key}").fetchone()[0]
    return out


def build(con, raw_dir: Path = config.RAW_DIR) -> dict:
    return {"raw": build_raw(con, raw_dir)}
