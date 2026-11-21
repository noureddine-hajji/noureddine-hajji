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

from . import staging, handicap, immersion, aides, apprentissage, jpo, transports, robustesse, robustesse_formation, precomp, bmo, config, cereq, reconnaissance, tension, vie, doublettes, parcours, rapports, ia_exposition, crosswalk, licence_master, emploi2030, grilles, harmonize, indicators, calibration, insertion, journey, lycee, nomenclatures, onisep, passerelles, poursuite, prevision, referentiel, search, semblables, success
from .ingest import load_manifest


_SOURCE = object()


def build(raw_dir: Path = config.RAW_DIR, db_path: Path = config.DB_PATH, success_source=_SOURCE,
          poursuite_sources=_SOURCE, cereq_source=_SOURCE,
          onisep_sources=_SOURCE, nomen_sources=_SOURCE, m2030_source=_SOURCE, bmo_source=_SOURCE, ia_sources=_SOURCE) -> Path:
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
        doublettes.build(con)
        rapports.build(con, textes=rapports.textes_path(db_path))
        semblables.build(con, rapports.textes_path(db_path))
        grilles.build(con, textes=rapports.textes_path(db_path))
        handicap.build(con)                # sprint 4: disability support and a student ambassador, as the fiche prints them
        immersion.build(con)               # sprint 4: what the fiche's own texts say of immersions and mini-stages
        reconnaissance.build(con)          # sprint V1: the State label printed on each live fiche, one badge
        vie.build(con, raw_dir, textes=rapports.textes_path(db_path))   # V1: rents, Crous, OVE items, fees; V2: communes (beside)
        aides.build(con)                   # sprint F: student aids read from the official pages (data/aides)
        jpo.build(con, textes=rapports.textes_path(db_path))   # open days (data/jpo, data/fiches): beside the warehouse
        transports.build(con, textes=rapports.textes_path(db_path))   # owner 2026-11-18: fares, stations, fuel (beside)
        tension.build(con)                 # sprint V2: vœux per place of each formation, placed among its type
        referentiel.build_referentiel(con, raw_dir)
        lycee.build_lycees(con, raw_dir)
        calibration.build_calibration(con)
        prevision.build(con)
        src = success.source_path() if success_source is _SOURCE else success_source
        success.attach(con, src)
        passerelles.build(con, raw_dir, reo_source=src)
        insertion.build(con, raw_dir)
        apprentissage.build(con)           # sprint V2: BTS apprentices vs voie scolaire, AFTER core.inserjeunes_bts (Codex)
        onisep.build(con, onisep.find_sources() if onisep_sources is _SOURCE else onisep_sources)
        parcours.build(con, onisep.find_sources() if onisep_sources is _SOURCE else onisep_sources)
        cereq.build(con, cereq.source_path() if cereq_source is _SOURCE else cereq_source)
        nomenclatures.build(con, nomenclatures.find_sources() if nomen_sources is _SOURCE else nomen_sources)
        emploi2030.build(con, emploi2030.source_path() if m2030_source is _SOURCE else m2030_source)
        bmo.build(con, bmo.source_path() if bmo_source is _SOURCE else bmo_source)
        ia_exposition.build(con, ia_exposition.sources() if ia_sources is _SOURCE else ia_sources)
        details = {}                                     # metiers.detail per job, read once for both steps (CI time)
        licence_master.build(con, details)
        robustesse.build(con, textes=rapports.textes_path(db_path), details=details)   # robustesse 2035 per job (owner's PRD), beside the warehouse
        # robustesse 2035 per formation (owner, 2026-11-17): outlets, skills (RNCP x ROME 4.0), insertion, after the jobs
        robustesse_formation.build(con, textes=rapports.textes_path(db_path),
                                   sources=onisep.find_sources() if onisep_sources is _SOURCE else onisep_sources)
        pou = (poursuite.find_sources() if poursuite_sources is _SOURCE else poursuite_sources) or {}
        poursuite.build(con, pou)
        search.persist(con)            # the search index, stored once: the first search of an instance no longer builds it
        # sprint Vitesse: the map layer and the lists' badges compressed once (brotli), beside the warehouse, keyed by digest
        precomp.build(con, rapports.textes_path(db_path), precomp.bodies(con))
        con.execute("CREATE OR REPLACE TABLE meta.build (key VARCHAR, value VARCHAR)")
        con.execute("INSERT INTO meta.build VALUES ('built_at', ?), ('manifest', ?), ('years', ?), ('success_source', ?), ('poursuite_sources', ?)", [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            json.dumps(load_manifest(raw_dir), ensure_ascii=False),
            json.dumps(list(config.YEARS)),
            src.name if src else "",
            json.dumps({k: Path(v).name for k, v in sorted(pou.items())}),
        ])
        # sprint 3 (owner 2026-11-21): the raw staging rows only the red teams re-read go beside the warehouse (95 MB budget)
        staging.move(con, db_path)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    staging.compact(tmp)   # a dropped table leaves its blocks in the file: copied into a fresh one (3 s, 16+ MB less)
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
