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
    out["lycees"] = build_profile_tables(con)
    return out


# What the data says (checked on the real files, 2023-2026):
# * IPS: one row per lycée and school year (rentrée 2023-24 to 2025-26, ~3,650 lycées); numbers are
#   stored as text; the GT-track IPS is empty for vocational lycées (LP); the reference IPS (national
#   and académie) is published per lycée type (LEGT, LPO, LP) and sector (public, private).
# * IVAL (general and technological lycées): one row per lycée and bac session (2012-2025, ~2,300
#   lycées); value added can be negative; the académie label is TRUNCATED ("NORMAIE",
#   "CLERMONT-FERRA"), so the académie always comes from the IPS file.
IVAL_YEARS = 3                     # bac sessions shown (latest first)
IVAL_KEYS = ("presents_total", "taux_reu_total", "va_reu_total", "taux_men_total", "va_men_total",
             "taux_acces_2nde", "va_acces_2nde")
TYPES = {"LEGT": "legt", "LPO": "lpo", "LP": "lp"}
SECTEURS = {"public": "public", "privé sous contrat": "prive"}
# IPS académie labels that have no Parcoursup académie (no higher-education offer listed there)
NO_PARCOURSUP_ACADEMIE = ("ST PIERRE ET MIQUELON", "WALLIS ET FUTUNA")


def fold(s) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def academie_map(con) -> dict:
    """IPS académie label -> Parcoursup académie (acad_mies), by folded equality."""
    psup = {fold(a): a for (a,) in con.execute("SELECT DISTINCT acad_mies FROM core.formation_year WHERE acad_mies IS NOT NULL").fetchall()}
    labels = [a for (a,) in con.execute("SELECT DISTINCT academie FROM ref.lycee_ips_raw WHERE academie IS NOT NULL").fetchall()]
    return {a: psup.get(fold(a)) for a in labels}


def build_profile_tables(con) -> int:
    """ref.lycee (latest school year per lycée, with its IPS references) and ref.lycee_ival (the
    IVAL_YEARS latest bac sessions per lycée). Returns the number of lycées."""
    cols = {r[0] for r in con.execute("DESCRIBE ref.lycee_ips_raw").fetchall()}
    if "rentree_scolaire" not in cols:
        con.execute("""CREATE OR REPLACE TABLE ref.lycee (uai VARCHAR, nom VARCHAR, commune VARCHAR, academie_ips VARCHAR,
            academie VARCHAR, secteur VARCHAR, type VARCHAR, rentree VARCHAR, ips_etab DOUBLE, ips_gt DOUBLE, ips_pro DOUBLE,
            ecart_type DOUBLE, ips_national DOUBLE, ips_academique DOUBLE)""")
        con.execute("""CREATE OR REPLACE TABLE ref.lycee_ival (uai VARCHAR, session INTEGER, presents_total BIGINT,
            taux_reu_total DOUBLE, va_reu_total DOUBLE, taux_men_total DOUBLE, va_men_total DOUBLE, taux_acces_2nde DOUBLE,
            va_acces_2nde DOUBLE)""")
        return 0
    amap = academie_map(con)
    con.execute("CREATE OR REPLACE TEMP TABLE _amap (academie_ips VARCHAR, academie VARCHAR)")
    con.executemany("INSERT INTO _amap VALUES (?, ?)", list(amap.items()))
    ref = lambda level: "CASE " + " ".join(   # noqa: E731 - reference IPS of the lycée's own type and sector
        f"WHEN r.type_de_lycee = '{t}' AND r.secteur = '{s}' THEN ips_{level}_{tk}_{sk}"
        for t, tk in TYPES.items() for s, sk in SECTEURS.items()) + " END"
    con.execute(f"""CREATE OR REPLACE TABLE ref.lycee AS
        -- the lycées open at the latest school year (one row each: checked, no duplicate UAI per year)
        WITH latest AS (SELECT * FROM ref.lycee_ips_raw
                        WHERE rentree_scolaire = (SELECT max(rentree_scolaire) FROM ref.lycee_ips_raw))
        SELECT r.uai, r.nom_de_l_etablissement AS nom, r.nom_de_la_commune AS commune, r.academie AS academie_ips,
               m.academie, r.secteur, r.type_de_lycee AS type, r.rentree_scolaire AS rentree,
               TRY_CAST(r.ips_etab AS DOUBLE) AS ips_etab, TRY_CAST(r.ips_voie_gt AS DOUBLE) AS ips_gt,
               TRY_CAST(r.ips_voie_pro AS DOUBLE) AS ips_pro, TRY_CAST(r.ecart_type_etablissement AS DOUBLE) AS ecart_type,
               {ref('national')} AS ips_national, {ref('academique')} AS ips_academique
        FROM latest r LEFT JOIN _amap m ON m.academie_ips = r.academie""")
    con.execute("DROP TABLE _amap")
    vcols = {r[0] for r in con.execute("DESCRIBE ref.lycee_ival_raw").fetchall()}
    if "annee" in vcols:
        con.execute(f"""CREATE OR REPLACE TABLE ref.lycee_ival AS
            SELECT uai, CAST(year(CAST(annee AS DATE)) AS INTEGER) AS session, {', '.join(IVAL_KEYS)}
            FROM ref.lycee_ival_raw
            -- the IVAL_YEARS latest bac sessions of the file (a lycée closed long ago keeps none)
            WHERE year(CAST(annee AS DATE)) > (SELECT max(year(CAST(annee AS DATE))) FROM ref.lycee_ival_raw) - {IVAL_YEARS}""")
    else:
        con.execute("""CREATE OR REPLACE TABLE ref.lycee_ival (uai VARCHAR, session INTEGER, presents_total BIGINT,
            taux_reu_total DOUBLE, va_reu_total DOUBLE, taux_men_total DOUBLE, va_men_total DOUBLE, taux_acces_2nde DOUBLE,
            va_acces_2nde DOUBLE)""")
    return con.execute("SELECT count(*) FROM ref.lycee").fetchone()[0]
