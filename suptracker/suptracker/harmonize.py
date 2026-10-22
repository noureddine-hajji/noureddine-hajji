"""Raw SIES Parquet -> unified DuckDB analytical schema.

Tables produced
  core.formation_year   one row per (session, cod_aff_form), canonical columns + flags
  core.specialites      specialty-doublette outcomes, long format
  core.cartographie     latest fiche URL / coordinates per cod_aff_form
  meta.schema_audit     which upstream column fed each canonical field, per vintage
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import config
from .schema import VOEUX_FIELDS, Field, norm, resolve, resolve_by_keywords

FICHE_TEMPLATE = (
    "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation"
    "?g_ta_cod={cod}&typeBac=0&originePc=0"
)

# Labels identifying concours communs whose sub-wishes share one applicant pool.
SUBWISH_LABEL_RE = r"\bconcours\b|puissance alpha|\bgeipi\b|\bconcours avenir\b|\badvance\b|\bsesame\b"


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


ID_FIELDS = {"cod_uai", "cod_aff_form", "dep"}


def _text(col: str, is_id: bool = False) -> str:
    v = f"CAST({q(col)} AS VARCHAR)"
    if is_id:  # ids exported as floats ("6170.0") must match their text form
        v = f"regexp_replace({v}, '\\.0$', '')"
    return f"NULLIF(TRIM({v}), '')"


def _num(col: str) -> str:
    return f"TRY_CAST(REPLACE(TRIM(CAST({q(col)} AS VARCHAR)), ',', '.') AS DOUBLE)"


def cast_expr(f: Field, col: str | None) -> list[str]:
    if f.dtype == "GEO":
        if col is None:
            return ["NULL::DOUBLE AS lat", "NULL::DOUBLE AS lon"]
        g = f"CAST({q(col)} AS VARCHAR)"
        return [geo_expr(g, "lat") + " AS lat", geo_expr(g, "lon") + " AS lon"]
    if col is None:
        return [f"NULL::{f.dtype} AS {f.name}"]
    if f.dtype == "VARCHAR":
        return [f"{_text(col, f.name in ID_FIELDS)} AS {f.name}"]
    if f.dtype == "BIGINT":
        return [f"TRY_CAST(ROUND({_num(col)}) AS BIGINT) AS {f.name}"]
    return [f"{_num(col)} AS {f.name}"]


def geo_expr(g: str, part: str) -> str:
    """Parse ODS geo_point_2d whether it arrives as 'lat, lon' text or a {lon, lat} struct."""
    keyed = f"regexp_extract({g}, '''?{part}''?\\s*[:=]\\s*(-?[0-9.]+)', 1)"
    positional = (
        f"regexp_extract({g}, '(-?[0-9.]+)\\s*,', 1)" if part == "lat"
        else f"regexp_extract({g}, ',\\s*(-?[0-9.]+)', 1)"
    )
    return (f"TRY_CAST(CASE WHEN {g} ILIKE '%{part}%' THEN {keyed} "
            f"ELSE {positional} END AS DOUBLE)")


def columns_of(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
    return [(r[0], r[1]) for r in rows]


def build_formation_year(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS core; CREATE SCHEMA IF NOT EXISTS meta;")
    con.execute("""CREATE OR REPLACE TABLE meta.schema_audit (
        session BIGINT, canonical VARCHAR, upstream VARCHAR, status VARCHAR)""")
    selects = []
    for year in config.YEARS:
        path = raw_dir / f"parcoursup_{year}.parquet"
        if not path.exists():
            con.execute("INSERT INTO meta.schema_audit VALUES (?, '*', NULL, 'missing_file')", [year])
            continue
        cols = [c for c, _ in columns_of(con, path)]
        mapping = resolve(VOEUX_FIELDS, cols)
        exprs = []
        for f in VOEUX_FIELDS:
            src = mapping[f.name]
            status = "missing" if src is None else ("exact" if norm(src) == f.name else "alias")
            con.execute("INSERT INTO meta.schema_audit VALUES (?, ?, ?, ?)", [year, f.name, src, status])
            if f.name == "session":
                # Trust the registry year; keep the upstream value only to audit it.
                exprs.append(f"{year}::BIGINT AS session")
                exprs.append(
                    (f"TRY_CAST({_num(src)} AS BIGINT)" if src else "NULL::BIGINT") + " AS session_upstream")
                continue
            exprs.extend(cast_expr(f, src))
        mapped = set(v for v in mapping.values() if v)
        for c in cols:
            if c not in mapped:
                con.execute("INSERT INTO meta.schema_audit VALUES (?, NULL, ?, 'unmapped_upstream')", [year, c])
        selects.append(f"SELECT {', '.join(exprs)} FROM read_parquet('{path}')")
    if not selects:
        raise RuntimeError(f"no Parcoursup vintages found in {raw_dir}")

    con.execute("CREATE OR REPLACE TABLE core._stack AS " + " UNION ALL BY NAME ".join(selects))
    dup = con.execute("""SELECT count(*) FROM (SELECT session, cod_aff_form FROM core._stack
                         GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    if dup:
        raise RuntimeError(f"{dup} duplicated (session, cod_aff_form) keys in raw data")

    con.execute(f"""
    CREATE OR REPLACE TABLE core.formation_year AS
    WITH base AS (
      SELECT *,
        strip_accents(lower(concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma))) AS _lbl
      FROM core._stack WHERE cod_aff_form IS NOT NULL
    ),
    pools AS (   -- identical candidate counts on 4 independent fields across >=3 programmes
      SELECT session, fili, voe_tot, voe_tot_f, nb_voe_pp, nb_voe_pc,
             md5(concat_ws('|', session, fili, voe_tot, voe_tot_f, nb_voe_pp, nb_voe_pc)) AS pool_id
      FROM base WHERE voe_tot >= 100
      GROUP BY ALL HAVING count(DISTINCT cod_aff_form) >= 3
    )
    SELECT b.* EXCLUDE (_lbl),
      regexp_matches(b._lbl, '{SUBWISH_LABEL_RE}') AS subwish_label_flag,
      p.pool_id IS NOT NULL AS subwish_pool_flag,
      (regexp_matches(b._lbl, '{SUBWISH_LABEL_RE}') OR p.pool_id IS NOT NULL) AS subwish_flag,
      CASE WHEN p.pool_id IS NOT NULL THEN p.pool_id
           WHEN regexp_matches(b._lbl, '{SUBWISH_LABEL_RE}')
             THEN md5(concat_ws('|', b.session, b.fili, b.voe_tot, b.nb_voe_pp))
      END AS subwish_group_id,
      coalesce(b.acc_tot < {config.LOW_N_THRESHOLD}, TRUE) AS low_n_flag,
      -- SIES breakdowns are published on néo-bacheliers; a few upstream rows do not add up
      coalesce(b.acc_bg + b.acc_bt + b.acc_bp <> b.acc_neobac, FALSE) AS series_sum_mismatch,
      coalesce(b.acc_sansmention + b.acc_ab + b.acc_b + b.acc_tb + b.acc_tbf + b.acc_mention_non_renseignee
               <> b.acc_neobac, FALSE) AS mention_sum_mismatch,
      strip_accents(lower(concat_ws(' ', b.g_ea_lib_vx, b.ville_etab, b.cod_uai, b.form_lib_voe_acc,
                                    b.fil_lib_voe_acc, b.lib_for_voe_ins, b.lib_comp_voe_ins))) AS search_text
    FROM base b
    LEFT JOIN pools p USING (session, fili, voe_tot, voe_tot_f, nb_voe_pp, nb_voe_pc)
    """)
    con.execute("DROP TABLE core._stack")


SPE_RULES = {
    "year": [("annee",), ("session",)],
    "formation_type": [("regroupement",), ("formation",), ("filiere",)],
    "doublette": [("doublette",), ("enseignement", "specialite"), ("specialite",)],
}
SPE_COUNT_RULES = {
    "n_candidats": [("confirm",), ("candidat", "voeu")],
    "n_proposition": [("propos",), ("recu",)],  # SIES: propositions_d_admissions
    "n_accepte": [("accept",), ("admis",)],
}


def audit_raw_columns(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    """meta.raw_columns: every upstream column and its physical type, per raw file."""
    con.execute("CREATE OR REPLACE TABLE meta.raw_columns (dataset VARCHAR, column_name VARCHAR, column_type VARCHAR)")
    for path in sorted(raw_dir.glob("*.parquet")):
        for col, typ in columns_of(con, path):
            con.execute("INSERT INTO meta.raw_columns VALUES (?, ?, ?)", [path.stem, col, typ])


def build_specialites(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    parts = []
    for key in ("specialites_2021_2024", "specialites_2025"):
        path = raw_dir / f"{key}.parquet"
        if not path.exists():
            con.execute("INSERT INTO meta.schema_audit VALUES (NULL, ?, NULL, 'missing_file')", [key])
            continue
        cols = columns_of(con, path)
        text_cols = [c for c, t in cols if t == "VARCHAR"]
        num_cols = [c for c, t in cols if t != "VARCHAR"]
        m = resolve_by_keywords(text_cols + [c for c in num_cols if "annee" in c.lower()
                                              or "session" in c.lower()], SPE_RULES)
        m.update(resolve_by_keywords([c for c in num_cols if c != m.get("year")], SPE_COUNT_RULES))
        for canon, src in m.items():
            con.execute("INSERT INTO meta.schema_audit VALUES (NULL, ?, ?, ?)",
                        [f"{key}.{canon}", src, "missing" if src is None else "keyword"])
        sel = [
            (f"TRY_CAST({_num(m['year'])} AS BIGINT)" if m["year"] else "NULL::BIGINT") + " AS session",
            (_text(m["formation_type"]) if m["formation_type"] else "NULL") + " AS formation_type",
            (_text(m["doublette"]) if m["doublette"] else "NULL") + " AS doublette",
        ] + [
            (f"TRY_CAST(ROUND({_num(m[c])}) AS BIGINT)" if m[c] else "NULL::BIGINT") + f" AS {c}"
            for c in SPE_COUNT_RULES
        ]
        parts.append(f"SELECT {', '.join(sel)}, '{key}' AS source FROM read_parquet('{path}')")
    if parts:
        con.execute(
            "CREATE OR REPLACE TABLE core.specialites AS SELECT * FROM ("
            + " UNION ALL ".join(parts) + f") WHERE session IN {tuple(config.YEARS)}")
    else:
        con.execute("""CREATE OR REPLACE TABLE core.specialites (session BIGINT, formation_type VARCHAR,
            doublette VARCHAR, n_candidats BIGINT, n_proposition BIGINT, n_accepte BIGINT, source VARCHAR)""")


CARTO_RULES = {
    "cod_aff_form": [("gta",), ("g_ta_cod",), ("cod_aff_form",)],
    "fiche_url": [("fiche",), ("lien",), ("url",)],
    "geo": [("gps",), ("geo",), ("coord",)],
    "year": [("annee",), ("session",)],
}


def build_cartographie(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    path = raw_dir / "cartographie.parquet"
    if not path.exists():
        con.execute("INSERT INTO meta.schema_audit VALUES (NULL, 'cartographie', NULL, 'missing_file')")
        con.execute("""CREATE OR REPLACE TABLE core.cartographie
                       (cod_aff_form VARCHAR, fiche_url VARCHAR, lat DOUBLE, lon DOUBLE)""")
        return
    cols = [c for c, _ in columns_of(con, path)]
    m = resolve_by_keywords(cols, CARTO_RULES)
    for canon, src in m.items():
        con.execute("INSERT INTO meta.schema_audit VALUES (NULL, ?, ?, ?)",
                    [f"cartographie.{canon}", src, "missing" if src is None else "keyword"])
    if not m["cod_aff_form"]:
        raise RuntimeError("cartographie: no formation id column (gta / g_ta_cod) found")
    g = f"CAST({q(m['geo'])} AS VARCHAR)" if m["geo"] else "NULL"
    order = _num(m["year"]) + " DESC NULLS LAST" if m["year"] else "1"
    con.execute(f"""
    CREATE OR REPLACE TABLE core.cartographie AS
    SELECT cod_aff_form, fiche_url, lat, lon FROM (
      SELECT {_text(m['cod_aff_form'], True)} AS cod_aff_form,
             {(_text(m['fiche_url']) if m['fiche_url'] else 'NULL')} AS fiche_url,
             {geo_expr(g, 'lat') if m['geo'] else 'NULL::DOUBLE'} AS lat,
             {geo_expr(g, 'lon') if m['geo'] else 'NULL::DOUBLE'} AS lon,
             row_number() OVER (PARTITION BY {_text(m['cod_aff_form'], True)} ORDER BY {order}) AS rn
      FROM read_parquet('{path}')) WHERE rn = 1 AND cod_aff_form IS NOT NULL
    """)


def attach_fiche(con: duckdb.DuckDBPyConnection) -> None:
    """Resolve the live fiche URL: cartographie > lien_form_psup > canonical g_ta_cod template."""
    tmpl = FICHE_TEMPLATE.replace("{cod}", "' || fy.cod_aff_form || '")
    con.execute(f"""
    CREATE OR REPLACE TABLE core.formation_year AS
    SELECT fy.* EXCLUDE (lat, lon),
      coalesce(fy.lat, c.lat) AS lat, coalesce(fy.lon, c.lon) AS lon,
      coalesce(c.fiche_url, fy.lien_form_psup, '{tmpl}') AS fiche_url,
      CASE WHEN c.fiche_url IS NOT NULL THEN 'cartographie'
           WHEN fy.lien_form_psup IS NOT NULL THEN 'lien_form_psup' ELSE 'template' END AS fiche_url_source
    FROM core.formation_year fy LEFT JOIN core.cartographie c USING (cod_aff_form)
    """)
