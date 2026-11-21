"""Raw staging tables kept BESIDE the warehouse, never in it (sprint 3 « Solidité avant le pic », owner 2026-11-21).

Six staging tables hold source rows exactly as published, so the red teams can re-derive what the build stores from them:
MonMaster, InserSup, Inserjeunes (lycées and CFA), IPS and IVAL. The site never reads them once the warehouse is built. In
the warehouse they took 16 MB of its 95 MB budget (GitHub refuses a file over 100 MB), leaving 1 MB of room before the next
SIES campaign. So at the end of the build they are moved into `sources_brutes.duckdb` beside the warehouse:
  * the same table names (`ref.<name>`), the same rows;
  * committed by the data workflow, kept out of the Vercel bundle (.vercelignore: the site never opens it);
  * read back through `relation()`: the warehouse's own table when it is there (a build in progress, an older warehouse),
    else the side file attached read-only.
"""
from __future__ import annotations

from pathlib import Path

BRUT_FILE = "sources_brutes.duckdb"
TABLES = ("monmaster_raw", "insersup", "inserjeunes_lycee", "inserjeunes_cfa", "lycee_ips_raw", "lycee_ival_raw")
ALIAS = "brut"


def path(db_path: Path) -> Path:
    return Path(db_path).with_name(BRUT_FILE)


def _has(con, schema_sql: str, name: str) -> bool:
    return bool(con.execute(f"SELECT count(*) FROM duckdb_tables() WHERE {schema_sql} AND schema_name = 'ref' AND table_name = ?",
                            [name]).fetchone()[0])


def move(con, db_path: Path) -> dict:
    """Write every staging table of the warehouse being built into a fresh side file, then drop it from the warehouse.
    Returns {table: rows}. The side file is written beside, then swapped in (never half written)."""
    final = path(db_path)
    tmp = final.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    here = [t for t in TABLES if _has(con, "database_name = current_database()", t)]
    out = {}
    con.execute(f"ATTACH '{tmp}' AS {ALIAS}_new")
    try:
        con.execute(f"CREATE SCHEMA {ALIAS}_new.ref")
        for t in here:
            con.execute(f"CREATE TABLE {ALIAS}_new.ref.{t} AS SELECT * FROM ref.{t}")
            out[t] = con.execute(f"SELECT count(*) FROM {ALIAS}_new.ref.{t}").fetchone()[0]
    finally:
        con.execute(f"DETACH {ALIAS}_new")
    for t in here:
        con.execute(f"DROP TABLE ref.{t}")
    tmp.replace(final)
    return out


def relation(con, name: str) -> str | None:
    """The SQL name of a staging table for a connection on a warehouse: `ref.<name>` when the warehouse holds it, else
    `brut.ref.<name>` from the side file (attached read-only, once), else None (no such table anywhere)."""
    if name not in TABLES:
        raise ValueError(f"not a staging table: {name}")
    if _has(con, "database_name = current_database()", name):
        return f"ref.{name}"
    attached = con.execute("SELECT count(*) FROM duckdb_databases() WHERE database_name = ?", [ALIAS]).fetchone()[0]
    if not attached:
        db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
        f = path(Path(db[0])) if db and db[0] else None
        if f is None or not f.exists():
            return None
        con.execute(f"ATTACH '{f}' AS {ALIAS} (READ_ONLY)")
    return f"{ALIAS}.ref.{name}" if _has(con, f"database_name = '{ALIAS}'", name) else None


def compact(db_file: Path) -> None:
    """Copy a finished warehouse into a fresh file and put it in its place. DuckDB never shrinks a file: the blocks of every
    table dropped during the build (staging, intermediate tables) stay in it. COPY FROM DATABASE writes only what is there."""
    import duckdb
    db_file = Path(db_file)
    fresh = db_file.with_name(db_file.name + ".compact")
    fresh.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{db_file}' AS src (READ_ONLY)")
        con.execute(f"ATTACH '{fresh}' AS dst")
        con.execute("COPY FROM DATABASE src TO dst")
    finally:
        con.close()
    fresh.replace(db_file)
