"""Sprint 8: professional insertion after a diploma.

Two official sources, checked on the real data before the design:

* Inserjeunes (Education ministry, DEPP): per establishment (UAI) and fine formation, the BTS
  included, pooled over two exit years ("cumul 2023-2024"). The share continuing their studies,
  the share employed 6 months after leaving and the other situations partition the final-year
  students (exact on every published row). The employment rates at 6, 12 and 24 months are
  among the LEAVERS (those who did not continue): taux_emploi_6 = part_emploi / (100 - poursuite).
  Small cohorts are masked (the rates far more often than the shares). Lycées (voie scolaire) and
  apprenticeship centres (CFA) are two datasets.
  A Parcoursup BTS is matched to the rows of ITS establishment (same UAI) and of the same BTS
  (normalised label: accents, small words, plural, "1re année commune"). When Parcoursup groups
  options that Inserjeunes publishes separately, each option is shown with its own rates, never
  averaged. Renamed or new BTS (CIEL, Banque, Biologie médicale...) have no exit cohort under
  their new name yet: they get no figure rather than the old diploma's.
* InserSup (higher-education ministry, SIES): graduates, per establishment (Paysage id) and per
  DIPLOMA (a master mention, a BUT specialty), plus the total per diploma type; SIES publishes no
  discipline aggregate per university. Rates are among the graduates who LEFT their studies
  ("sortants"): salaried employment in France, stable employment, median salary (often masked
  "nd"). Fewer than 20 leavers: two graduating classes are pooled (flag "*"). The 18-month horizon
  is the latest one published for every recent class.

The ministries' rates are stored and shown as published, never recomputed or averaged.
"""
from __future__ import annotations

from pathlib import Path

from . import config

RAW = ("insersup", "inserjeunes_lycee", "inserjeunes_cfa")


# the full sources are ~130 MB together: only a profile and the rows a page can use are staged


def build_raw(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """ref.insertion_profile (one row per source x column: type, nulls, distinct values, the most
    frequent values) and ref.<key> (the rows a page can use, KEEP). The full sources would push the
    committed warehouse over GitHub's 100 MB file limit. Kept as is when the raw files are absent."""
    import json
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    con.execute("""CREATE TABLE IF NOT EXISTS ref.insertion_profile (source VARCHAR, n_rows BIGINT, col VARCHAR,
        type VARCHAR, n_null BIGINT, n_distinct BIGINT, top VARCHAR)""")
    out = {}
    for key in RAW:
        path = Path(raw_dir) / f"{key}.parquet"
        if not path.exists():
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
        con.execute(f"DROP TABLE IF EXISTS ref.{key}_sample")
        con.execute(f"CREATE OR REPLACE TABLE ref.{key} AS SELECT * FROM {src} WHERE {KEEP[key]}")
        out[key] = n
    return out


# The rows the feature can use (the rest would only be breakdowns a student page never shows)
KEEP = {
    # graduates, every gender / nationality / regime, aggregated over diplomas and sectors (per
    # establishment x diploma type x discipline, national rows included)
    "insersup": """obtention_diplome = 'diplômé' AND genre = 'ensemble' AND nationalite = 'ensemble'
                   AND regime_inscription = 'ensemble'
                   AND (diplome = 'all' OR type_diplome_long IN ('Master LMD', 'Master MEEF',
                        'Bachelor universitaire de technologie', 'Licence professionnelle'))""",
    "inserjeunes_lycee": "type_diplome = 'BTS'",
    "inserjeunes_cfa": "type_diplome = 'BTS'",
}


# ------------------------------------------------------------------------- normalisation
import json as _json
import re as _re

from . import evidence as E
from . import passerelles as PA
from . import poursuite as PO
from . import success as SU
from .success import fold

STOP = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "aux", "au"}
HORIZONS = (6, 12, 18, 24, 30)
SERVED_HORIZON = 18


def bts_key(label: str | None) -> str:
    """BTS label -> comparable key (accents, small words, plurals, 'option'/'opt', common first year)."""
    s = fold(label)
    s = _re.sub(r"1ere annee commune|a referentiel commun europeen", " ", s)
    s = _re.sub(r"\bopt\b\.?", "option", s)
    words = [w for w in _re.findall(r"[a-z0-9]+", s) if w not in STOP]
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)


def _num(v):
    """'nd' (masked), '' or None -> (None, reason); numbers -> (float, None)."""
    if v is None:
        return None, "absent"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (None, "absent") if v != v else (float(v), None)
    t = str(v).strip()
    if t.lower() == "nd":
        return None, "nd"
    try:
        return float(t.replace(",", ".")), None
    except ValueError:
        return None, "texte"


def promo_years(promo: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in _re.findall(r"\d{4}", promo or ""))


# ------------------------------------------------------------------------- warehouse
IJ_COLS = ("source", "annee", "uai", "libelle", "type_diplome", "libelle_formation", "code", "cle", "part_poursuite", "part_emploi_6",
           "part_autres", "taux_poursuite", "taux_emploi_6", "taux_emploi_12", "taux_emploi_18", "taux_emploi_24")
IS_METRICS = ("nb_sortants", "nb_poursuivants", "nb_sortants_en_emploi_sal_fr", "tx_sortants_en_emploi_sal_fr",
              "tx_sortants_en_emploi_stable", "salaire_q1", "salaire_q2", "salaire_q3")


def build(con, raw_dir: Path = config.RAW_DIR) -> dict:
    """ref.insertion_profile and staged rows (build_raw), then core.inserjeunes_bts (latest pooled
    years), core.insersup (one row per establishment x diploma x graduating class) and
    core.bts_insertion_link (Parcoursup BTS -> Inserjeunes rows)."""
    out = {"raw": build_raw(con, raw_dir)}
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute(f"""CREATE OR REPLACE TABLE core.inserjeunes_bts ({", ".join(f"{c} {'DOUBLE' if c.startswith(('part_', 'taux_')) else 'VARCHAR'}" for c in IJ_COLS)},
        masked VARCHAR)""")
    rows = []
    # one row per establishment x formation CODE: a BTS can be published under two codes at one UAI
    for src, tag, code in (("inserjeunes_lycee", "lycee", "code_formation_mefstat11"), ("inserjeunes_cfa", "apprentissage", "code_formation_apprentissage")):
        cols = {r[0] for r in con.execute(f"DESCRIBE ref.{src}").fetchall()}
        if "taux_emploi_6_mois" not in cols:
            continue
        latest = con.execute(f"SELECT max(annee) FROM ref.{src}").fetchone()[0]
        for r in con.execute(f"""SELECT annee, uai, libelle, type_diplome, libelle_formation, CAST({code} AS VARCHAR), part_en_poursuite_d_etudes,
                part_en_emploi_6_mois_apres_la_sortie, part_des_autres_situations, taux_poursuite_etudes, taux_emploi_6_mois,
                taux_emploi_12_mois, taux_emploi_18_mois, taux_emploi_24_mois FROM ref.{src} WHERE annee = ?""", [latest]).fetchall():
            vals, masked = [], {}
            for k, v in zip(IJ_COLS[8:], r[6:]):
                x, why = _num(v)
                vals.append(x)
                if why:
                    masked[k] = why
            rows.append([tag, r[0], r[1], r[2], r[3], r[4], r[5], bts_key(r[4]), *vals, _json.dumps(masked, sort_keys=True)])
    if rows:
        con.executemany(f"INSERT INTO core.inserjeunes_bts VALUES ({', '.join('?' * (len(IJ_COLS) + 1))})", rows)
    out["inserjeunes_bts"] = len(rows)
    # one row per Paysage id x diploma x establishment (UAI) x sector x class: a Paysage id can cover several
    # UAIs, and a diploma attached to two sectors is published once per sector with its own figures
    con.execute(f"""CREATE OR REPLACE TABLE core.insersup (id_paysage VARCHAR, uo_lib VARCHAR, type_diplome VARCHAR, diplome VARCHAR,
        libelle VARCHAR, etablissement VARCHAR, sectdis_lib VARCHAR, discipli_lib VARCHAR, discipline VARCHAR, promo VARCHAR,
        last_year INTEGER, pooled BOOLEAN,
        {", ".join(f"{m}_{h} DOUBLE" for m in IS_METRICS for h in HORIZONS)}, masked VARCHAR)""")
    cols = {r[0] for r in con.execute("DESCRIBE ref.insersup").fetchall()}
    if "promo" in cols:
        # set-based: 'nd' -> NULL with its reason, numbers cast; discipline map applied per distinct label
        con.execute("CREATE OR REPLACE TEMP TABLE _disc (discipli_lib VARCHAR, discipline VARCHAR)")
        con.executemany("INSERT INTO _disc VALUES (?, ?)", [(d, PA.MASTER_DISCIPLINE.get(fold(d))) for (d,) in
                        con.execute("SELECT DISTINCT discipli_lib FROM ref.insersup WHERE discipli_lib IS NOT NULL").fetchall()])
        metric = lambda c: (f"TRY_CAST(replace(CAST(r.{c} AS VARCHAR), ',', '.') AS DOUBLE)" if c in cols else "NULL")
        masks = " , ".join(f"CASE WHEN lower(trim(CAST({m}_{h} AS VARCHAR))) = 'nd' THEN '\"{m}_{h}\": \"nd\"' END"
                           for m in IS_METRICS for h in HORIZONS if f"{m}_{h}" in cols)
        con.execute(f"""INSERT INTO core.insersup
            SELECT coalesce(r.id_paysage_actuel, r.id_paysage), coalesce(r.uo_lib_actuel, r.uo_lib), r.type_diplome_long, r.diplome,
                   r.libelle_diplome, r.etablissement, r.sectdis_lib, r.discipli_lib,
                   CASE WHEN r.type_diplome_long = 'Master MEEF' THEN 'meef' ELSE d.discipline END,
                   r.promo, CAST(list_max(regexp_extract_all(r.promo, '[0-9]{{4}}')) AS INTEGER),
                   len(regexp_extract_all(r.promo, '[0-9]{{4}}')) > 1,
                   {", ".join(metric(f"{m}_{h}") for m in IS_METRICS for h in HORIZONS)},
                   '{{' || concat_ws(', ', {masks}) || '}}'
            FROM ref.insersup r LEFT JOIN _disc d USING (discipli_lib)""")
    out["insersup"] = con.execute("SELECT count(*) FROM core.insersup").fetchone()[0]
    out["bts_links"] = build_bts_links(con)
    return out


def build_bts_links(con) -> int:
    """core.bts_insertion_link: each Parcoursup BTS of the latest campaign -> the Inserjeunes rows of
    its establishment and BTS (exact key, or the options of that BTS); status explains a missing link."""
    con.execute("""CREATE OR REPLACE TABLE core.bts_insertion_link (session INTEGER, cod_aff_form VARCHAR, uai VARCHAR,
        programme VARCHAR, cle VARCHAR, status VARCHAR, ij_source VARCHAR, ij_libelle VARCHAR)""")
    if not con.execute("SELECT count(*) FROM core.inserjeunes_bts").fetchone()[0]:
        return 0
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    ij = {}
    for src, uai, lib, cle in con.execute("SELECT DISTINCT source, uai, libelle_formation, cle FROM core.inserjeunes_bts").fetchall():
        ij.setdefault(uai, []).append((src, lib, cle))
    known = {c for v in ij.values() for _, _, c in v}
    links = []
    for cod, uai, prog in con.execute("""SELECT cod_aff_form, cod_uai, fil_lib_voe_acc FROM core.formation_year
                                         WHERE session = ? AND fili = 'BTS'""", [latest]).fetchall():
        k = bts_key(prog)
        rows = ij.get(uai)
        if not rows:
            links.append([latest, cod, uai, prog, k, "etablissement_absent", None, None])
            continue
        exact = [(s, l) for s, l, c in rows if c == k]
        opts = [(s, l) for s, l, c in rows if c.startswith(k + " option")]
        hits, status = (exact, "ok") if exact else (opts, "options") if opts else ([], "non_publie" if k in known else "non_trouve")
        if not hits:
            links.append([latest, cod, uai, prog, k, status, None, None])
        for s, l in hits:
            links.append([latest, cod, uai, prog, k, status, s, l])
    con.executemany("INSERT INTO core.bts_insertion_link VALUES (?, ?, ?, ?, ?, ?, ?, ?)", links)
    return len({x[1] for x in links if x[6]})


# ------------------------------------------------------------------------- serving
def _ready(con, table) -> bool:
    try:
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0
    except Exception:  # noqa: BLE001 - warehouse built before sprint 8
        return False


def _rows(con, sql, args):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        d["masked"] = _json.loads(d.get("masked") or "{}")
        out.append(d)
    return out


def for_bts(con, cod: str, fili: str | None) -> dict | None:
    """Inserjeunes block of a BTS page: the rows of this establishment and BTS (each option apart)."""
    if fili != "BTS" or not _ready(con, "core.bts_insertion_link"):
        return None
    links = con.execute("""SELECT status, ij_source, ij_libelle, uai FROM core.bts_insertion_link WHERE cod_aff_form = ?
                           ORDER BY session DESC""", [cod]).fetchall()
    if not links:
        return None
    status = links[0][0]
    out = {"status": status, "rows": [], "annee": None}
    for _, src, lib, uai in links:
        if src is None:
            continue
        for r in _rows(con, "SELECT * FROM core.inserjeunes_bts WHERE source = ? AND uai = ? AND libelle_formation = ?", [src, uai, lib]):
            # Inserjeunes publishes no headcount: no reliability grade (it rests on the number of people);
            # small cohorts are masked by the producer, and the page says so
            r["voie"] = "apprentissage" if src == "apprentissage" else "voie scolaire"
            out["rows"].append(r)
            out["annee"] = r["annee"]
    reasons = {"etablissement_absent": "cet établissement ne figure pas dans Inserjeunes pour les BTS",
               "non_publie": "Inserjeunes ne publie pas ce BTS pour cet établissement",
               "non_trouve": "pas de chiffres Inserjeunes sous ce nom de BTS (BTS rénové ou nouveau : pas encore de sortants)"}
    if not out["rows"]:
        out["reason"] = reasons.get(status, "non publié")
    return out


def _latest(rows):
    """For each diploma, the row of its most recent graduating class with an 18-month figure."""
    best = {}
    for r in rows:
        if r[f"nb_sortants_{SERVED_HORIZON}"] is None and r["masked"].get(f"nb_sortants_{SERVED_HORIZON}") is None:
            continue
        k = (r["id_paysage"], r["diplome"], r["libelle"], r["etablissement"], r["sectdis_lib"])
        if k not in best or (r["last_year"] or 0) > (best[k]["last_year"] or 0):
            best[k] = r
    return list(best.values())


def _grade(r, lien):
    return E.maillon("emploi_18_mois", r[f"tx_sortants_en_emploi_sal_fr_{SERVED_HORIZON}"], granularite="universite_x_discipline",
                     population="diplômés sortis des études", cohorte=r["last_year"],
                     effectif=r[f"nb_sortants_{SERVED_HORIZON}"], source="InserSup (SIES)", lien=lien or "nom",
                     avertissement="taux parmi les diplômés qui ont quitté les études")


def for_licence(con, cod: str, fili: str | None, contrat: str | None, paysage: dict | None = None) -> dict | None:
    """InserSup block of a licence page: insertion after the university's masters in this discipline."""
    if fili not in SU.LICENCE_FILI or not _ready(con, "core.insersup"):
        return None
    try:
        link = con.execute("""SELECT etab, discipline, lien FROM core.licence_success_link WHERE cod_aff_form = ?
                              ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    except Exception:  # noqa: BLE001
        link = None
    etab, disc, lien = link if link else (None, None, None)
    out = {"status": "ok", "etab": etab, "etab_label": SU.UNIVERSITY_LABEL.get(etab, etab) if etab else None, "discipline": disc,
           "discipline_label": SU.DISCIPLINES[disc][1] if disc else None, "masters": [], "total": None, "france": None}
    if contrat != "Public" or etab is None or disc is None:
        out.update(status="non_rattachee", reason="pas de rattachement certain à une université et une discipline")
        return out
    pid = (SU.SIES_PAYSAGE if paysage is None else paysage).get(etab)
    rows = _rows(con, "SELECT * FROM core.insersup WHERE id_paysage = ? AND type_diplome = 'Master LMD'", [pid]) if pid else []
    ms = sorted(_latest([r for r in rows if r["diplome"] != "all" and r["discipline"] == disc]),
                key=lambda r: (-(r[f"nb_sortants_{SERVED_HORIZON}"] or 0), r["libelle"] or ""))
    for r in ms:
        r["maillon"] = _grade(r, lien)
    out["masters"] = ms
    tot = _latest([r for r in rows if r["diplome"] == "all"])
    out["total"] = tot[0] if tot else None
    nat = _latest(_rows(con, "SELECT * FROM core.insersup WHERE id_paysage = 'all' AND type_diplome = 'Master LMD' AND diplome = 'all'", []))
    out["france"] = nat[0] if nat else None
    if not ms:
        out.update(status="non_publie", reason="InserSup ne publie pas de master de cette discipline pour cette université")
    return out


def for_but(con, etab: str | None, specialite: str | None, lien: str | None = None, paysage: dict | None = None) -> dict | None:
    """InserSup block of a BUT page: the BUT specialty at the university, its total, France."""
    if not _ready(con, "core.insersup"):
        return None
    pid = (SU.SIES_PAYSAGE if paysage is None else paysage).get(etab) if etab else None
    rows = _rows(con, "SELECT * FROM core.insersup WHERE type_diplome = 'Bachelor universitaire de technologie' AND id_paysage IN (?, 'all')",
                 [pid or "-"])
    def pick(pid_, spe):
        c = [r for r in rows if r["id_paysage"] == pid_ and ((spe is None and r["diplome"] == "all")
             or (spe is not None and r["diplome"] != "all" and PO._key(r["libelle"]) == spe))]
        c = _latest(c)
        return c[0] if len(c) == 1 else None    # published in several parts (sites, sectors): no single figure
    out = {"specialite": pick(pid, specialite) if pid and specialite else None, "total": pick(pid, None) if pid else None,
           "france_specialite": pick("all", specialite) if specialite else None, "france": pick("all", None)}
    for k in ("specialite", "total"):
        if out[k]:
            out[k]["maillon"] = _grade(out[k], lien)
    return out
