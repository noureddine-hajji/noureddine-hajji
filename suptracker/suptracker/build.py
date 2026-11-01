"""Build the DuckDB warehouse from raw SIES Parquet files.

    python -m suptracker.ingest      # download raw exports
    python -m suptracker.build       # harmonise, link, benchmark
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from . import config, crosswalk, harmonize, indicators, calibration, journey, lycee, passerelles, poursuite, referentiel, success
from .ingest import load_manifest


_SOURCE = object()


def build(raw_dir: Path = config.RAW_DIR, db_path: Path = config.DB_PATH, success_source=_SOURCE,
          poursuite_sources=_SOURCE) -> Path:
    """success_source: the SIES licence success workbook (B1); default data/sources/, None to skip.
    poursuite_sources: {kind: path} of the sprint-6 BUT and master workbooks; default: detected in
    data/sources/, None to skip."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        harmonize.build_formation_year(con, raw_dir)
        harmonize.audit_raw_columns(con, raw_dir)
        harmonize.build_specialites(con, raw_dir)
        harmonize.build_cartographie(con, raw_dir)
        harmonize.attach_fiche(con)
        crosswalk.build_crosswalk(con)
        indicators.build_peers(con)
        journey.build_journey(con)
        referentiel.build_referentiel(con, raw_dir)
        lycee.build_lycees(con, raw_dir)
        passerelles.build_raw(con, raw_dir)
        calibration.build_calibration(con)
        src = success.source_path() if success_source is _SOURCE else success_source
        success.attach(con, src)
        pou = (poursuite.find_sources() if poursuite_sources is _SOURCE else poursuite_sources) or {}
        poursuite.build(con, pou)
        con.execute("CREATE OR REPLACE TABLE meta.build (key VARCHAR, value VARCHAR)")
        con.execute("INSERT INTO meta.build VALUES ('built_at', ?), ('manifest', ?), ('years', ?), ('success_source', ?), ('poursuite_sources', ?)", [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(load_manifest(raw_dir), ensure_ascii=False),
            json.dumps(list(config.YEARS)),
            src.name if src else "",
            json.dumps({k: Path(v).name for k, v in sorted(pou.items())}),
        ])
        con.execute("CHECKPOINT")
    finally:
        con.close()
    tmp.replace(db_path)  # atomic swap: the API never sees a half-built warehouse
    return db_path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    args = ap.parse_args(argv)
    path = build(args.raw_dir, args.db)
    con = duckdb.connect(str(path), read_only=True)
    print(con.execute("SELECT session, count(*) n FROM core.formation_year GROUP BY 1 ORDER BY 1").df())
    print(crosswalk.continuity_report(con)[0])


if __name__ == "__main__":
    main()
