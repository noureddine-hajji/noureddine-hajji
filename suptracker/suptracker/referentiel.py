"""Establishment register (sprint 3): the key that links every source to a Parcoursup formation.

SIES publishes, on every Parcoursup campaign 2022-2025, the Paysage identifier of the formation's
parent establishment (a UFR or an antenna carries its university's id) and of its component. The
MESR register "Principaux établissements d'enseignement supérieur" gives, for each Paysage id, the
official name, UAI (and former UAIs), type, sector and académie. Sources keyed by establishment
(SIES success tables, InserSup, MonMaster...) are linked through this id, not through names.
"""
from __future__ import annotations

from pathlib import Path

from . import config

REF_COLUMNS = {   # register column -> ref.etablissement column
    "etablissement_id_paysage": "id_paysage", "uai": "uai", "anciens_codes_uai": "anciens_codes_uai",
    "uo_lib": "nom", "nom_court": "nom_court", "sigle": "sigle", "type_d_etablissement": "type",
    "typologie_d_universites_et_assimiles": "typologie", "secteur_d_etablissement": "secteur",
    "aca_nom": "academie", "com_nom": "commune", "siren": "siren", "universites_fusionnees": "universites_fusionnees",
    "etablissement_experimental": "etablissement_experimental", "uo_lib_officiel": "nom_officiel",
}


def build_referentiel(con, raw_dir: Path = config.RAW_DIR) -> int:
    """ref.etablissement (the register) and ref.formation_etablissement (formation -> Paysage ids,
    and whether the parent is in the register). Returns the number of register rows (0 if absent)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    path = Path(raw_dir) / "etablissements.parquet"
    cols = {}
    if path.exists():
        have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        cols = {k: v for k, v in REF_COLUMNS.items() if k in have}
    if "etablissement_id_paysage" in cols:
        sel = ", ".join(f"CAST({k} AS VARCHAR) AS {v}" for k, v in cols.items())
        missing = ", ".join(f"CAST(NULL AS VARCHAR) AS {v}" for k, v in REF_COLUMNS.items() if k not in cols)
        con.execute(f"""CREATE OR REPLACE TABLE ref.etablissement AS
                        SELECT {sel}{', ' + missing if missing else ''} FROM read_parquet('{path}')
                        WHERE etablissement_id_paysage IS NOT NULL""")
    else:
        con.execute(f"""CREATE OR REPLACE TABLE ref.etablissement ({', '.join(f'{v} VARCHAR' for v in REF_COLUMNS.values())})""")
    con.execute("""CREATE OR REPLACE TABLE ref.formation_etablissement AS
        SELECT fy.session, fy.cod_aff_form, fy.cod_uai, fy.g_ea_lib_vx,
               nullif(trim(fy.etablissement_id_paysage), '') AS etablissement_id_paysage,
               nullif(trim(fy.composante_id_paysage), '') AS composante_id_paysage,
               e.id_paysage IS NOT NULL AS in_register
        FROM core.formation_year fy
        LEFT JOIN ref.etablissement e ON e.id_paysage = nullif(trim(fy.etablissement_id_paysage), '')""")
    return con.execute("SELECT count(*) FROM ref.etablissement").fetchone()[0]
