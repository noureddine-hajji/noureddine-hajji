"""FastAPI service over the DuckDB warehouse + static single-page UI.

    uvicorn suptracker.api:app --reload
"""
from __future__ import annotations

import json
import math
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .crosswalk import EXACT, INFERRED, continuity_report
from .indicators import PEER_METRICS
from .schema import FIELD_BY_NAME, MENTION_FIELDS, SERIES_FIELDS, VOEUX_FIELDS
from .urls import extract_cod_aff_form, is_uai

STATIC = Path(__file__).parent / "static"

METHODOLOGY = {
    "funnel": (
        "Les trois étapes ne se divisent pas entre elles. Les vœux (voe_tot, nb_voe_pp) comptent des "
        "vœux, et non des personnes. Les classés et proposés (nb_cla_pp, prop_tot) comptent des candidats "
        "classés ou ayant reçu une proposition. Les admis (acc_tot) comptent les candidats qui ont "
        "accepté définitivement. Un candidat peut formuler jusqu'à 10 vœux (et des sous-vœux), donc les "
        "ratios entre étapes n'ont pas de sens statistique."),
    "taux_acces_ens": (
        "Indicateur officiel SIES : il est repris tel quel et n'est jamais recalculé. Il mesure la part "
        "des candidats en phase principale dont le rang de classement était au moins égal à celui du "
        "dernier candidat appelé. Il est restreint à la phase principale parce que c'est la seule phase "
        "qui produit un classement unique et complet : les vœux de la phase complémentaire (et des "
        "procédures ultérieures) portent sur des places restantes, avec un vivier et un calendrier "
        "différents. Diviser prop_tot par voe_tot mélangerait ces phases et compterait des vœux au lieu "
        "de candidats."),
    "part_terminale_generale_en_position_admis_pp": (
        "Indicateur officiel SIES (part_acces_gen) : la part des candidats de terminale générale en phase "
        "principale qui étaient en position de recevoir une proposition. Il porte sur la phase "
        "principale uniquement, pour la même raison que le taux d'accès."),
    "subwish": (
        "Vœu multiple ou concours commun : les sous-vœux partagent un même vivier de candidats. Leurs "
        "effectifs de vœux sont publiés à l'identique pour chaque école et ne doivent jamais être "
        "additionnés. Les agrégats ne retiennent donc qu'une seule fois chaque groupe."),
    "low_n": (
        f"Moins de {config.LOW_N_THRESHOLD} admis : les pourcentages de profil (mentions, boursiers, "
        "sexe, origine) sont très instables. La formation est exclue des distributions de référence de "
        "sa filière et aucun percentile ne lui est attribué."),
    "peers": (
        "Les pairs sont les formations de la même filière détaillée (fil_lib_voe_acc) pour la même "
        "session. Le percentile est un rang médian (les ex-æquo partagent la position moyenne). La "
        f"distribution est jugée instable en dessous de {config.MIN_PEERS} pairs."),
    "lineage": (
        f"{EXACT} : même couple (cod_uai, cod_aff_form) d'une campagne à l'autre. {INFERRED} : le code "
        "formation a changé, et le lien a été inféré au sein du même établissement et de la même filière "
        "agrégée, d'après la similarité des libellés (meilleur candidat mutuel, avec une marge minimale). "
        "Les cas ambigus ne sont jamais reliés."),
    "mentions": (
        "La décomposition par mention porte sur les admis néo-bacheliers issus de terminale (acc_term). "
        "Les parts sont celles publiées par SIES (pct_*)."),
}


class WarehouseMissing(RuntimeError):
    pass


def _db_path() -> Path:
    return Path(os.environ.get("SUPTRACKER_DB", config.DB_PATH))


@lru_cache(maxsize=1)  # failures are not cached, so the app picks the warehouse up once it is built
def _con() -> duckdb.DuckDBPyConnection:
    db = _db_path()
    if not db.exists():
        raise WarehouseMissing(f"warehouse {db} not found: run python -m suptracker.build")
    return duckdb.connect(str(db), read_only=True)


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = _con().cursor()
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        out.append({c: (None if isinstance(v, float) and math.isnan(v) else v) for c, v in zip(cols, r)})
    return out


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


app = FastAPI(title="SupTracker SIES", version="1.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(WarehouseMissing)
def _warehouse_missing(_: Request, exc: WarehouseMissing):
    return JSONResponse({"detail": "Entrepôt de données en cours de construction ou absent. "
                         "Réessayez dans quelques minutes."}, status_code=503)


@app.get("/healthz")
def healthz():
    """Liveness: the process is up. `ready` tells whether the warehouse is queryable."""
    return {"status": "ok", "ready": _db_path().exists()}


@app.get("/readyz")
def readyz():
    _con()  # raises WarehouseMissing -> 503 until the build has finished
    return {"status": "ready"}

SUMMARY_COLS = """fy.session, fy.cod_aff_form, fy.cod_uai, fy.g_ea_lib_vx, fy.ville_etab, fy.fili,
  fy.form_lib_voe_acc, fy.fil_lib_voe_acc, fy.lib_for_voe_ins, fy.lib_comp_voe_ins, fy.acc_tot,
  fy.taux_acces_ens, fy.subwish_flag, fy.low_n_flag, l.lineage_id, l.lineage_confidence, l.lineage_years"""


@app.get("/api/meta")
def meta():
    b = {r["key"]: r["value"] for r in rows("SELECT * FROM meta.build")}
    audit = rows("""SELECT session, canonical, upstream, status FROM meta.schema_audit
                    WHERE status IN ('missing', 'missing_file', 'alias', 'keyword') ORDER BY 1, 2""")
    return {
        "years": json.loads(b.get("years", "[]")),
        "built_at": b.get("built_at"),
        "manifest": json.loads(b.get("manifest", "{}")),
        "methodology": METHODOLOGY,
        "fields": {f.name: {"label": f.label, "stage": f.stage} for f in VOEUX_FIELDS},
        "peer_metrics": {k: {"label": v[2], "needs_n": v[1], "higher_is_more_selective": v[3]}
                         for k, v in PEER_METRICS.items()},
        "schema_audit": audit,
        "low_n_threshold": config.LOW_N_THRESHOLD,
    }


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(40, le=200)):
    q = q.strip()
    cod = extract_cod_aff_form(q)
    if cod or q.isdigit():
        where, params, mode = "fy.cod_aff_form = ?", [cod or q], "cod_aff_form"
    elif is_uai(q):
        where, params, mode = "upper(fy.cod_uai) = ?", [q.upper()], "uai"
    else:
        toks = [t for t in fold(q).split() if t]
        where = " AND ".join(["fy.search_text LIKE ?"] * len(toks))
        params, mode = [f"%{t}%" for t in toks], "text"
    if q.lower().startswith(("http", "www.")) and not cod:
        raise HTTPException(422, "URL non reconnue : attendu une fiche parcoursup.fr contenant g_ta_cod=…")
    # One row per lineage, showing its most recent campaign.
    res = rows(f"""
      SELECT * FROM (
        SELECT {SUMMARY_COLS},
          row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) AS rn
        FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
        WHERE l.lineage_id IN (SELECT l2.lineage_id FROM core.formation_year fy
                               JOIN core.lineage l2 USING (session, cod_aff_form) WHERE {where}))
      WHERE rn = 1 ORDER BY session DESC, g_ea_lib_vx, fil_lib_voe_acc LIMIT ?""", params + [limit])
    return {"mode": mode, "resolved_cod_aff_form": cod, "results": res}


def _record(cod: str, session: int | None) -> dict:
    sql = """SELECT fy.*, l.lineage_id, l.lineage_confidence, l.lineage_years
             FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
             WHERE fy.cod_aff_form = ?"""
    params: list = [cod]
    if session:
        sql += " AND fy.session = ?"
        params.append(session)
    r = rows(sql + " ORDER BY fy.session DESC LIMIT 1", params)
    if not r:
        raise HTTPException(404, f"formation {cod} introuvable" + (f" en {session}" if session else ""))
    return r[0]


def _warnings(rec: dict, peers: list[dict] | None = None) -> list[dict]:
    w = []
    if rec["low_n_flag"]:
        w.append({"code": "low_n", "text": f"Effectif admis faible ({rec['acc_tot']}) : profils non "
                  "interprétables, formation exclue des quantiles de profil."})
    if rec["subwish_flag"]:
        w.append({"code": "subwish", "text": "Sous-vœu de vœu multiple / concours commun : les "
                  "effectifs de vœux sont partagés avec d'autres formations, et ne sont pas additionnables."})
    if rec["lineage_confidence"] == INFERRED:
        w.append({"code": "lineage", "text": "Historique reconstitué avec au moins un appariement inféré "
                  "(changement de code formation)."})
    if peers and any(p["unstable"] for p in peers if p["n_peers"]):
        w.append({"code": "peers", "text": f"Moins de {config.MIN_PEERS} formations comparables "
                  "pour certains indicateurs : percentiles instables."})
    return w


def _grouped(rec: dict) -> dict:
    stages: dict[str, dict] = {"candidates": {}, "ranked_offered": {}, "admitted": {}, "indicator": {}}
    for name, f in FIELD_BY_NAME.items():
        if f.stage:
            stages[f.stage][name] = rec.get(name)
    return stages


@app.get("/api/formation/{cod}")
def formation(cod: str, session: int | None = None):
    rec = _record(cod, session)
    peers = rows("""SELECT metric, value, in_reference, peer_percentile, n_peers, p10, p25, p50, p75, p90,
                           unstable FROM mart.peer_rank WHERE session = ? AND cod_aff_form = ?""",
                 [rec["session"], rec["cod_aff_form"]])
    order = list(PEER_METRICS)
    peers.sort(key=lambda p: order.index(p["metric"]))
    return {"record": rec, "stages": _grouped(rec), "peers": peers,
            "history": lineage(rec["lineage_id"])["years"], "warnings": _warnings(rec, peers)}


DECOMP = ("acc_tot", "acc_term", "acc_neobac", "acc_at", *SERIES_FIELDS, *MENTION_FIELDS, "acc_brs",
          "acc_tot_f", "pct_f", "pct_bours", "pct_aca_orig", "pct_etab_orig", "pct_bg", "pct_bt", "pct_bp",
          "pct_tb", "pct_tbf", "taux_acces_ens", "part_terminale_generale_en_position_admis_pp",
          "voe_tot", "nb_voe_pp", "nb_cla_pp", "prop_tot", "capa_fin", "low_n_flag", "subwish_flag")


@app.get("/api/lineage/{lineage_id}")
def lineage(lineage_id: str):
    cols = ", ".join(f"fy.{c}" for c in DECOMP)
    res = rows(f"""SELECT fy.session, fy.cod_aff_form, fy.cod_uai, fy.lib_for_voe_ins, l.link_to_next,
                          l.lineage_confidence, {cols}
                   FROM core.lineage l JOIN core.formation_year fy USING (session, cod_aff_form)
                   WHERE l.lineage_id = ? ORDER BY fy.session""", [lineage_id])
    if not res:
        raise HTTPException(404, "lignée inconnue")
    # Links joining consecutive campaigns of this lineage, with match type and score.
    links = rows("""SELECT k.session_from, k.cod_aff_form_from, k.session_to, k.cod_aff_form_to,
                           k.link_type, k.score
                    FROM core.crosswalk_link k JOIN core.lineage l
                      ON l.session = k.session_from AND l.cod_aff_form = k.cod_aff_form_from
                    WHERE l.lineage_id = ? ORDER BY k.session_from""", [lineage_id])
    present = {r["session"] for r in res}
    return {"lineage_id": lineage_id, "years": res, "links": links,
            "missing_years": [y for y in config.YEARS if y not in present]}


@app.get("/api/compare")
def compare(ids: str, session: int | None = None):
    cods = [c.strip() for c in ids.split(",") if c.strip()][:6]
    out = []
    for c in cods:
        f = formation(c, session)
        out.append({"record": {k: f["record"].get(k) for k in
                               ("session", "cod_aff_form", "g_ea_lib_vx", "ville_etab", "fil_lib_voe_acc",
                                "lib_comp_voe_ins", "lineage_id", "lineage_confidence", "fiche_url",
                                *DECOMP)},
                    "peers": f["peers"], "history": f["history"], "warnings": f["warnings"]})
    return {"formations": out}


@app.get("/api/specialites")
def specialites(session: int | None = None, formation_type: str | None = None):
    session = session or config.LATEST_YEAR
    types = [r["formation_type"] for r in rows(
        "SELECT DISTINCT formation_type FROM core.specialites WHERE session = ? ORDER BY 1", [session])]
    sql = """SELECT session, formation_type, doublette, n_candidats, n_proposition, n_accepte,
               -- unit = distinct candidates (persons), not vœux: a legitimate share, unlike prop_tot over voe_tot
               CASE WHEN n_candidats > 0 THEN round(100.0 * n_proposition / n_candidats, 1) END
                 AS pct_candidats_avec_proposition,
               CASE WHEN n_candidats > 0 THEN round(100.0 * n_accepte / n_candidats, 1) END
                 AS pct_candidats_ayant_accepte
             FROM core.specialites WHERE session = ?"""
    params: list = [session]
    if formation_type:
        sql += " AND formation_type = ?"
        params.append(formation_type)
    return {"session": session, "formation_types": types,
            "rows": rows(sql + " ORDER BY formation_type, n_candidats DESC", params)}


@app.get("/api/filiere")
def filiere(fil: str, session: int | None = None):
    """National track totals. Sub-wishes of one concours commun are counted once."""
    session = session or config.LATEST_YEAR
    r = rows("""
      WITH dedup AS (
        SELECT coalesce(subwish_group_id, cod_aff_form) AS unit, max(voe_tot) AS voe_tot,
               max(nb_voe_pp) AS nb_voe_pp, sum(acc_tot) AS acc_tot, sum(capa_fin) AS capa_fin,
               count(*) AS n_formations, bool_or(subwish_flag) AS has_subwish
        FROM core.formation_year WHERE session = ? AND fil_lib_voe_acc = ? GROUP BY 1)
      SELECT count(*) AS n_units, sum(n_formations) AS n_formations,
             sum(voe_tot) AS voe_tot_dedup_subwish, sum(nb_voe_pp) AS nb_voe_pp_dedup_subwish,
             sum(acc_tot) AS acc_tot, sum(capa_fin) AS capa_fin, sum(has_subwish::INT) AS n_subwish_groups
      FROM dedup""", [session, fil])[0]
    r["note"] = ("Totaux de vœux : chaque groupe de sous-vœux n'est compté qu'une fois. Les vœux ne "
                 "sont pas des candidats uniques : un même candidat apparaît dans plusieurs formations.")
    r["distribution"] = rows("SELECT * FROM mart.peer_distribution WHERE session = ? AND fil_lib_voe_acc = ?",
                             [session, fil])
    return r


@app.get("/api/continuity")
def continuity():
    df = continuity_report(_con().cursor())
    return {"anchor": config.LATEST_YEAR,
            "rows": json.loads(df.to_json(orient="records", force_ascii=False))}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
