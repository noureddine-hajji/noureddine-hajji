"""Establishment register (sprint 3): the key that links every source to a Parcoursup formation.

What the data says (checked on the 2022-2025 warehouse):

* SIES publishes on each campaign the Paysage id of a formation's parent establishment (a UFR or an
  antenna carries its university's id) and of its component. It is filled for ~96-98 % of public
  licences, BUT and PASS in 2022-2024, rarely for lycée formations (BTS, CPGE: 15-25 %), and it is
  EMPTY in the 2025 export. The cartographie (current listing) and the same formation's previous
  campaign fill 2025, and the source of every id is kept.
* The MESR register "Principaux établissements d'enseignement supérieur" (245 rows) knows only the
  current id of an establishment. Merged or renamed universities (Bourgogne -> Bourgogne Europe,
  Franche-Comté -> Marie et Louis Pasteur...) appear in older campaigns under their former id. The
  data itself gives the succession, two ways: (a) the same formation moves from the old id to the
  new one the next campaign; (b) the old id's formations are listed under a UAI that the register
  gives (as current or former UAI) to one establishment. A succession is kept only when the
  evidence is near-unanimous (SUCCESSION_SHARE, SUCCESSION_MIN) and lands in the register; mergers
  of 2025, absent from the empty 2025 ids, are found by (b).
"""
from __future__ import annotations

from pathlib import Path

from . import config

SUCCESSION_SHARE = 0.8   # share of an old id's evidence (moves or UAI votes) that must point to one register id
SUCCESSION_MIN = 5       # and at least this many formations
REF_COLUMNS = {   # register column -> ref.etablissement column
    "etablissement_id_paysage": "id_paysage", "uai": "uai", "anciens_codes_uai": "anciens_codes_uai",
    "uo_lib": "nom", "nom_court": "nom_court", "sigle": "sigle", "type_d_etablissement": "type",
    "typologie_d_universites_et_assimiles": "typologie", "secteur_d_etablissement": "secteur",
    "aca_nom": "academie", "com_nom": "commune", "siren": "siren", "universites_fusionnees": "universites_fusionnees",
    "etablissement_experimental": "etablissement_experimental", "uo_lib_officiel": "nom_officiel",
}


def build_register(con, raw_dir: Path = config.RAW_DIR) -> int:
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    path = Path(raw_dir) / "etablissements.parquet"
    cols = {}
    if path.exists():
        have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        cols = {k: v for k, v in REF_COLUMNS.items() if k in have}
    if "etablissement_id_paysage" in cols:
        sel = [f"CAST({k} AS VARCHAR) AS {v}" for k, v in cols.items()]
        sel += [f"CAST(NULL AS VARCHAR) AS {v}" for k, v in REF_COLUMNS.items() if k not in cols]
        con.execute(f"""CREATE OR REPLACE TABLE ref.etablissement AS SELECT {', '.join(sel)}
                        FROM read_parquet('{path}') WHERE etablissement_id_paysage IS NOT NULL""")
    else:
        con.execute(f"CREATE OR REPLACE TABLE ref.etablissement ({', '.join(f'{v} VARCHAR' for v in REF_COLUMNS.values())})")
    return con.execute("SELECT count(*) FROM ref.etablissement").fetchone()[0]


def build_links(con) -> None:
    """ref.succession and ref.formation_etablissement (every formation and campaign -> resolved id)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    has_carto = con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
        AND table_name = 'cartographie' AND column_name = 'etablissement_id_paysage'""").fetchone()[0]
    carto = ("SELECT cod_aff_form, etablissement_id_paysage AS id_carto, composante_id_paysage AS comp_carto FROM core.cartographie"
             if has_carto else "SELECT NULL::VARCHAR AS cod_aff_form, NULL::VARCHAR AS id_carto, NULL::VARCHAR AS comp_carto WHERE false")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _fe AS
        WITH base AS (
          SELECT session, cod_aff_form, cod_uai, g_ea_lib_vx,
                 nullif(trim(etablissement_id_paysage), '') AS id_sies, nullif(trim(composante_id_paysage), '') AS comp_sies
          FROM core.formation_year),
        withprev AS (
          SELECT *, last_value(id_sies IGNORE NULLS) OVER (PARTITION BY cod_aff_form ORDER BY session
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS id_prev
          FROM base)
        SELECT w.*, c.id_carto, c.comp_carto,
               coalesce(w.id_sies, c.id_carto, w.id_prev) AS id_raw,
               CASE WHEN w.id_sies IS NOT NULL THEN 'parcoursup' WHEN c.id_carto IS NOT NULL THEN 'cartographie'
                    WHEN w.id_prev IS NOT NULL THEN 'campagne_precedente' END AS id_source,
               coalesce(w.comp_sies, c.comp_carto) AS composante_id_paysage
        FROM withprev w LEFT JOIN ({carto}) c ON c.cod_aff_form = w.cod_aff_form""")
    # every UAI the register knows for an establishment: its current one and its former ones. A former
    # UAI shared by two establishments (a split university: Antilles-Guyane) names neither: dropped.
    con.execute("""CREATE OR REPLACE TEMP TABLE _uai AS
        WITH all_uai AS (
          SELECT id_paysage, trim(uai) AS uai FROM ref.etablissement WHERE coalesce(uai, '') <> ''
          UNION ALL
          SELECT id_paysage, trim(unnest(string_split(anciens_codes_uai, ';'))) AS uai
          FROM ref.etablissement WHERE coalesce(anciens_codes_uai, '') <> '')
        SELECT DISTINCT id_paysage, uai FROM all_uai
        WHERE uai IN (SELECT uai FROM all_uai GROUP BY uai HAVING count(DISTINCT id_paysage) = 1)""")
    con.execute(f"""CREATE OR REPLACE TABLE ref.succession AS
        WITH outside AS (SELECT * FROM _fe WHERE id_raw IS NOT NULL
                           AND id_raw NOT IN (SELECT id_paysage FROM ref.etablissement)),
        -- (a) the same formation moves from the old id to a register id the next campaign
        steps AS (
          SELECT a.id_sies AS old_id, b.id_sies AS new_id, count(*) AS n
          FROM _fe a JOIN _fe b ON b.cod_aff_form = a.cod_aff_form AND b.session = a.session + 1
          WHERE a.id_sies IS NOT NULL AND b.id_sies IS NOT NULL AND a.id_sies <> b.id_sies
            AND a.id_sies NOT IN (SELECT id_paysage FROM ref.etablissement)
          GROUP BY 1, 2),
        -- (b) the old id's formations are listed under a UAI the register gives (current or former)
        --     to one establishment
        votes AS (
          SELECT o.id_raw AS old_id, u.id_paysage AS new_id, count(DISTINCT o.cod_aff_form) AS n
          FROM outside o JOIN _uai u ON u.uai = o.cod_uai GROUP BY 1, 2),
        cand AS (SELECT old_id, new_id, n, 'transition' AS method FROM steps
                 UNION ALL SELECT old_id, new_id, n, 'uai' AS method FROM votes),
        tot AS (SELECT old_id, method, sum(n) AS n_old FROM cand GROUP BY 1, 2),
        ranked AS (
          SELECT c.*, t.n_old, c.n / t.n_old AS share,
                 row_number() OVER (PARTITION BY c.old_id ORDER BY c.method = 'transition' DESC, c.n DESC) AS rk
          FROM cand c JOIN tot t USING (old_id, method)
          WHERE c.new_id IN (SELECT id_paysage FROM ref.etablissement)
            AND c.n / t.n_old >= {SUCCESSION_SHARE} AND c.n >= {SUCCESSION_MIN})
        SELECT old_id, new_id, method, n, n_old, share FROM ranked WHERE rk = 1""")
    con.execute("""CREATE OR REPLACE TABLE ref.formation_etablissement AS
        SELECT f.session, f.cod_aff_form, f.cod_uai, f.g_ea_lib_vx, f.id_sies, f.id_carto, f.id_prev,
               f.id_raw AS etablissement_id_paysage, f.id_source, f.composante_id_paysage,
               CASE WHEN e.id_paysage IS NOT NULL THEN f.id_raw ELSE s.new_id END AS id_resolu,
               CASE WHEN f.id_raw IS NULL THEN 'absent' WHEN e.id_paysage IS NOT NULL THEN 'direct'
                    WHEN s.new_id IS NOT NULL THEN 'successeur' ELSE 'hors_registre' END AS resolution
        FROM _fe f
        LEFT JOIN ref.etablissement e ON e.id_paysage = f.id_raw
        LEFT JOIN ref.succession s ON s.old_id = f.id_raw""")
    con.execute("DROP TABLE _fe")
    con.execute("DROP TABLE _uai")


def build_referentiel(con, raw_dir: Path = config.RAW_DIR) -> int:
    n = build_register(con, raw_dir)
    build_links(con)
    return n
