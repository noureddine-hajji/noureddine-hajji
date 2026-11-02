"""Sprint 8: professional insertion after a diploma.

Stage 1 (data reconnaissance): InserSup (SIES: university diplomas) and Inserjeunes (DEPP: BTS
and other vocational diplomas in lycées and in apprenticeship centres) are profiled column by
column, with a reproducible sample, so their grain, units, masking and keys can be checked on
real data before the feature is designed.
"""
from __future__ import annotations

from pathlib import Path

from . import config

RAW = ("insersup", "inserjeunes_lycee", "inserjeunes_cfa")


SAMPLE_ROWS = 3000      # the full sources are ~130 MB together: only a profile and a sample are staged


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """ref.insertion_profile (one row per source x column: type, nulls, distinct values, the most
    frequent values) and ref.<key>_sample (a reproducible sample). The full sources would push the
    committed warehouse over GitHub's 100 MB file limit. Kept as is when the raw files are absent."""
    import json
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    con.execute("""CREATE TABLE IF NOT EXISTS ref.insertion_profile (source VARCHAR, n_rows BIGINT, col VARCHAR,
        type VARCHAR, n_null BIGINT, n_distinct BIGINT, top VARCHAR)""")
    out = {}
    for key in RAW:
        path = Path(raw_dir) / f"{key}.parquet"
        if not path.exists():
            con.execute(f"CREATE TABLE IF NOT EXISTS ref.{key}_sample (_absent BOOLEAN)")
            con.execute(f"CREATE TABLE IF NOT EXISTS ref.{key} (_absent BOOLEAN)")
            out[key] = None
            continue
        src = f"read_parquet('{path}')"
        n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        con.execute("DELETE FROM ref.insertion_profile WHERE source = ?", [key])
        for col, typ, *_ in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall():
            q = f'"{col}"'
            nn, nd = con.execute(f"SELECT count(*) - count({q}), approx_count_distinct({q}) FROM {src}").fetchone()
            top = con.execute(f"SELECT CAST({q} AS VARCHAR), count(*) c FROM {src} GROUP BY 1 ORDER BY c DESC LIMIT 25").fetchall()
            con.execute("INSERT INTO ref.insertion_profile VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [key, n, col, typ, nn, nd, json.dumps(top, ensure_ascii=False)])
        con.execute(f"CREATE OR REPLACE TABLE ref.{key}_sample AS SELECT * FROM {src} USING SAMPLE reservoir({SAMPLE_ROWS} ROWS) REPEATABLE (42)")
        con.execute(f"CREATE OR REPLACE TABLE ref.{key} AS SELECT * FROM {src} WHERE {KEEP[key]}")
        out[key] = n
    return out


# The rows the feature can use (the rest would only be breakdowns a student page never shows)
KEEP = {
    # graduates, every gender / nationality / regime, aggregated over diplomas and sectors (per
    # establishment x diploma type x discipline, national rows included)
    "insersup": """obtention_diplome = 'diplômé' AND genre = 'ensemble' AND nationalite = 'ensemble'
                   AND regime_inscription = 'ensemble' AND diplome = 'all' AND sectdis = 'all'""",
    "inserjeunes_lycee": "type_diplome = 'BTS'",
    "inserjeunes_cfa": "type_diplome = 'BTS'",
}
