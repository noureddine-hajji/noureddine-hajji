"""FastAPI service over the DuckDB warehouse + static single-page UI.

    uvicorn suptracker.api:app --reload
"""
from __future__ import annotations

import hmac
import json
import math
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import duckdb
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import analytics as A
from . import config
from . import journey as J
from . import planb as PB
from . import search as S
from . import success as SU
from . import glossary as G
from . import evidence as EV
from . import calibration as CAL
from . import sources as SRC
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
        "Indicateur officiel SIES (part_acces_gen) : parmi les candidats de terminale en position de recevoir "
        "une proposition en phase principale, la part de ceux qui viennent de terminale générale. C'est une "
        "composition, pas une chance d'accès : avec les parts techno et pro, elle fait 100 % (vérifié sur "
        "99,9 % des formations 2025). 100 % en CPGE scientifique veut dire que les candidats appelés étaient tous "
        "en terminale générale, pas que tous les candidats de terminale générale ont été appelés."),
    "serie_offer": (
        "SIES ne publie pas de taux d'accès par série du bac. L'accès estimé pour votre série part du taux "
        "d'accès officiel de la formation (tous candidats) et l'ajuste selon la réussite de votre série : il est "
        "multiplié par le rapport entre le taux de proposition de votre série (candidats de votre série ayant reçu "
        "une proposition, toutes phases, rapportés aux candidats de votre série) et celui de l'ensemble des "
        "candidats, puis plafonné à 100 %. C'est une estimation : elle suppose que l'écart entre séries est le "
        "même pour l'accès que pour les propositions. Le taux de proposition de votre série et le taux d'accès "
        "officiel sont affichés à côté. En dessous de 20 candidats de votre série, le taux est jugé fragile. "
        "SIES ne distingue pas les "
        "séries technologiques entre elles (STMG, STI2D, ST2S…) ni les spécialités du bac professionnel : "
        "« bac technologique » les regroupe toutes."),
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
    "journey_stage1": (
        "Étape 1, au niveau national : données SIES « enseignements de spécialité », dont l'unité est le "
        "candidat (et non le vœu). Taux de proposition : candidats de la doublette ayant reçu au moins une "
        "proposition dans la filière, rapportés aux candidats de la doublette ayant formulé au moins un vœu "
        "dans cette filière. Indice de représentation : part de la doublette parmi les admis de la filière, "
        "divisée par sa part parmi l'ensemble des admis bacheliers généraux. Part de destination : part des "
        "admis de la doublette qui ont accepté cette filière. Les années 2022–2025 sont cumulées. On ne somme "
        "jamais entre filières, et seuls les niveaux d'agrégation 0–1 de l'export 2025 sont lus."),
    "journey_gate": (
        "Filières de prédilection : la doublette représente au moins 2 % des admis, son indice de "
        "représentation est d'au moins 1,5, et son taux de proposition est au moins égal à celui de "
        "l'ensemble des candidats de la filière. Filières atypiques : la doublette représente moins de 2 % "
        "des admis bacheliers généraux. Les autres filières sont accessibles. En dessous de 100 candidats "
        "cumulés, l'effectif est jugé insuffisant."),
    "journey_cdf": (
        "Part des admis ayant au plus votre mention : parmi les admis néo-bacheliers de la formation dont "
        "la mention est connue, la part qui a une mention inférieure ou égale à la vôtre, cumulée sur la "
        "lignée 2022–2025. L'intervalle est un intervalle de Wilson à 95 %. SIES publie les mentions "
        "pour tous les néo-bacheliers (général, technologique et professionnel), sans croisement avec la "
        "série : la part de bacheliers généraux est donc affichée à côté. Ce n'est pas une probabilité "
        "d'admission individuelle : c'est la composition d'une cohorte d'admis."),
    "journey_bg": (
        "Vous êtes situé parmi les admis de votre série du bac seulement (général, technologique ou "
        "professionnel). Les explications ci-dessous valent pour chaque série. SIES ne publie pas "
        "la répartition des mentions par série du bac, seulement le nombre d'admis de chaque série ayant une "
        "mention, et la répartition des mentions toutes séries confondues. La part des bacheliers généraux "
        "admis avec votre mention ou moins n'est donc connue qu'à un encadrement près : un encadrement exact, "
        "car toute répartition compatible avec les chiffres publiés donne une valeur dans cet intervalle, et "
        "les deux bornes sont atteintes par l'une d'elles. Quand la formation n'admet que des bacheliers "
        "généraux, l'encadrement se réduit à une valeur exacte. La marge affichée ajoute l'incertitude "
        "d'échantillonnage (Wilson à 95 %) à chaque borne. Pour la zone, la part toutes séries est ramenée "
        "dans l'encadrement (la valeur la plus proche compatible avec les données), et la formation est "
        "marquée incertaine si une valeur de la marge la placerait dans une autre zone. En dessous de 10 "
        "admis bac général cumulés, ou si les chiffres publiés se contredisent, la part toutes séries est "
        "affichée à la place."),
    "planb": (
        "Plan B : les formations de la même filière détaillée (même intitulé de programme), placées pour votre "
        "profil avec la méthode de « Mon parcours ». Une formation est proposée si elle est dans une zone plus "
        "favorable que la formation visée (et pas incertaine), ou dans une zone au moins égale avec un accès "
        "supérieur d'au moins 15 points sans position de mention moins bonne. Sont écartées : les formations "
        "fermées à votre série, les lectures fragiles (moins de 20 candidats de votre série, moins de 10 admis), "
        "les écoles du même concours commun (même vivier de candidats) et, par défaut, les établissements privés "
        "hors contrat ou d'enseignement supérieur privé, qui peuvent demander des frais de scolarité élevés. Au "
        "plus 2 propositions par établissement ; ordre : votre académie, puis la distance à la formation visée. "
        "Ce sont des parts d'admis des années passées, pas des chances d'admission."),
    "journey_zones": (
        "Hors-profil : moins de 2 % des admis ont votre mention ou moins. Ambitieux : taux d'accès "
        "inférieur à 30 %, ou votre mention se situe dans les 15 % inférieurs de la cohorte admise. "
        "Sécurité : taux d'accès d'au moins 70 % et au moins la moitié des admis avec votre mention ou "
        "moins. Cible : tous les autres cas. Une formation est marquée « incertaine » quand une valeur "
        "comprise dans l'intervalle à 95 % la placerait dans une autre zone."),
    "journey_groups": (
        "Groupe d'appel : le groupe de classement Parcoursup (lib_grp1 à 3) qui s'applique à un bachelier "
        "général, avec le rang du dernier candidat appelé dans ce groupe. Dans les données SIES 2022–2025, "
        "aucun groupe n'est découpé par enseignement de spécialité ; les groupes portent sur la série du "
        "bac, le sexe, le campus ou la voie CEP. Le rang du dernier appelé n'est pas une probabilité : la "
        "taille du groupe n'est pas publiée."),
    "timing": (
        "Indicateurs officiels SIES repris tels quels (pct_acc_debutpp, pct_acc_datebac, pct_acc_finpp) : part "
        "des admis ayant reçu leur proposition d'admission à l'ouverture de la phase principale, avant les "
        "résultats du baccalauréat, puis avant la fin de la phase principale. Les trois parts sont cumulées : "
        "chacune inclut la précédente. Le dénominateur est l'ensemble des admis de la formation, phase "
        "complémentaire comprise (vérifié sur toutes les lignes 2022–2025) : le reste correspond aux admis "
        "après la phase principale. Ce sont des parts d'admis, et non des chances d'admission : elles disent "
        "quand les futurs admis ont reçu leur proposition, au fil des désistements."),
    "offer": (
        "Options issues de la cartographie des formations Parcoursup (dernière session publiée) : internat de "
        "l'établissement, formation en apprentissage, enseignement à distance (total ou partiel), aménagements "
        "pour sportifs ou artistes de haut niveau. Elles décrivent l'offre actuelle, pas une campagne passée. "
        "L'apprentissage est aussi lu dans l'intitulé SIES. Les aménagements pour les candidats en situation de "
        "handicap ne figurent pas dans ces données : chaque fiche Parcoursup indique le référent handicap."),
    "success": (
        "Réussite en licence : chiffres publiés par le SIES (ministère de l'Enseignement supérieur) pour "
        "l'ensemble des néo-bacheliers inscrits en première année de licence d'une université dans une grande "
        "discipline (droit ; économie-AES ; arts, lettres, langues et sciences humaines ; sciences-santé ; "
        "STAPS). Ils ne portent pas sur cette seule licence, et ne sont pas publiés formation par formation. "
        "Trois cohortes : le devenir un an après l'entrée en L1 (passage en L2, redoublement, réorientation, "
        "sortie de l'enseignement supérieur), la licence obtenue en 3 ans, et en 3 ou 4 ans. Les taux sont "
        "repris tels quels. Le taux attendu (« simulé » par le SIES) est celui qu'on observerait si les inscrits "
        "réussissaient comme la moyenne nationale des étudiants de même profil ; l'écart (« valeur ajoutée ») "
        "se lit avec prudence et ne classe pas les universités. La référence nationale porte sur la même "
        "discipline. Les petits effectifs sont masqués par le SIES (« ns ») ou signalés ici en dessous de 100 "
        "inscrits. Ce sont des résultats de cohortes passées, pas des chances de réussite."),
    "fiabilite": (
        "Fiabilité d'un chiffre, notée par des règles fixes, les mêmes partout sur le site. A (solide) : au moins 100 "
        "personnes, une cohorte de 3 ans au plus, un rattachement par l'identifiant officiel de l'établissement "
        "(Paysage). B (à nuancer) : moins de 100 personnes, une cohorte plus ancienne, ou un rattachement fait par le "
        "nom de l'établissement. C (fragile) : moins de 30 personnes. Un chiffre masqué par le producteur n'a ni note ni "
        "valeur. La fiabilité ne dit pas si le chiffre est bon ou mauvais pour vous : elle dit à quel point il est "
        "solide. Chaque étape du parcours décrit une population différente : les chiffres ne se multiplient pas entre eux."),
    "lycee": (
        "Ton lycée, en contexte. L'indice de position sociale (IPS, ministère de l'Éducation nationale) résume le milieu "
        "social des élèves d'un lycée : plus il est élevé, plus il est favorisé en moyenne. Il est comparé aux lycées du même "
        "type (général et technologique, polyvalent, professionnel) et du même secteur (public, privé sous contrat), dans "
        "l'académie et en France. La valeur ajoutée (IVAL) compare les résultats du lycée au bac (réussite, mentions, accès "
        "de la seconde au bac) à ceux qu'on attendrait vu le profil de ses élèves. Ce sont des indicateurs du lycée, pas de "
        "toi. Aucune donnée publique ne relie les admissions Parcoursup au lycée d'origine : ton lycée ne modifie donc pas ton "
        "positionnement. Une seule exception est publiée : quand une formation (BTS, CPGE) se trouve dans ton lycée, la part "
        "de ses admis qui venaient de ce même lycée. Ton lycée reste dans ton navigateur : il n'est jamais envoyé au site."),
    "repere": (
        "Repère pour la prochaine campagne : deux fourchettes et une stabilité, calculées sur les campagnes 2022 à 2025. "
        "Fourchette du taux d'accès officiel et fourchette de la part d'admis ayant ta mention ou moins (tous bacs confondus), "
        "à 80 % : la méthode a été réglée sur 2023 et 2024, puis testée sur 2025 sans l'avoir vue ; la part des vraies "
        "valeurs 2025 tombées dans leur fourchette est affichée telle quelle. Les fourchettes sont plus larges pour les "
        "petites formations et pour celles qui ont peu d'historique. La stabilité dit dans combien de cas comparables la zone "
        "(sécurité, cible, ambitieux, hors profil) a été confirmée l'année suivante ; elle est mesurée avec la même lecture "
        "que la zone affichée pour le bac général (part des admis bac général encadrée par les chiffres publiés). Ce ne sont pas des chances d'admission : "
        "les données publiques ne donnent pas les mentions des candidats, seulement celles des admis."),
    "mentions": (
        "Les décompositions par série et par mention portent sur les admis néo-bacheliers (acc_neobac), "
        "le dénominateur que SIES utilise effectivement : sur les exports 2022–2025, les séries s'additionnent "
        "exactement à acc_neobac, et non à acc_term. Les parts affichées sont celles publiées par SIES (pct_*). "
        "Quelques lignes de l'export SIES lui-même ne s'additionnent pas ; elles sont signalées."),
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


@app.middleware("http")
async def _count_server_errors(request: Request, call_next):
    try:
        resp = await call_next(request)
    except Exception:
        A.record_server_error()
        raise
    if resp.status_code >= 500:
        A.record_server_error()
    return resp


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
  fy.taux_acces_ens, fy.subwish_flag, fy.low_n_flag, l.lineage_id, l.lineage_confidence, l.lineage_years,
  fy.carto_session, fy.apprentissage, fy.internat, fy.distance, fy.amenag_sport, fy.amenag_art"""


def _warm_search_index():
    """Build the search index in the background as soon as the app loads (it takes ~2 s on a
    cold serverless start), so the student's first search does not pay for it."""
    import threading

    def run():
        try:
            S.get_index(_con().cursor())
        except Exception:  # noqa: BLE001 - warming is best effort; search builds on demand anyway
            pass
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/meta")
def meta():
    _warm_search_index()
    b = {r["key"]: r["value"] for r in rows("SELECT * FROM meta.build")}
    audit = rows("""SELECT session, canonical, upstream, status FROM meta.schema_audit
                    WHERE status IN ('missing', 'missing_file', 'alias', 'keyword') ORDER BY 1, 2""")
    return {
        "years": json.loads(b.get("years", "[]")),
        "built_at": b.get("built_at"),
        "manifest": json.loads(b.get("manifest", "{}")),
        "methodology": METHODOLOGY,
        "glossary": G.as_list(),
        "sources": SRC.public_view(),
        "fields": {f.name: {"label": f.label, "stage": f.stage} for f in VOEUX_FIELDS},
        "peer_metrics": {k: {"label": v[2], "needs_n": v[1], "higher_is_more_selective": v[3]}
                         for k, v in PEER_METRICS.items()},
        "schema_audit": audit,
        "low_n_threshold": config.LOW_N_THRESHOLD,
    }


@app.get("/api/search")
def search(request: Request, bg: BackgroundTasks,
           q: str = Query(..., min_length=1, max_length=2000), fili: str | None = None,
           academie: str | None = None, selective: bool | None = None, near: str | None = None,
           options: str | None = Query(None, max_length=200, description="comma-separated: " + ",".join(S.OPTIONS)),
           offset: int = Query(0, ge=0, le=20_000), limit: int = Query(40, ge=1, le=200)):
    """Student search: acronyms, places, typos, notes and facets (see suptracker/search.py).
    A pasted parcoursup.fr fiche URL or a bare formation code goes straight to that formation."""
    q = q.strip()
    cod = extract_cod_aff_form(q)
    if q.lower().startswith(("http", "www.")) and not cod:
        raise HTTPException(422, "URL non reconnue : attendu une fiche parcoursup.fr contenant g_ta_cod=…")
    if cod or (q.isdigit() and len(q) <= 9):
        res = rows(f"""
          SELECT * EXCLUDE (rn) FROM (
            SELECT {SUMMARY_COLS}, fy.acad_mies,
              row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) AS rn
            FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
            WHERE l.lineage_id IN (SELECT l2.lineage_id FROM core.lineage l2 WHERE l2.cod_aff_form = ?))
          WHERE rn = 1""", [cod or q])
        return {"mode": "cod_aff_form", "resolved_cod_aff_form": cod or q, "query": q, "results": res,
                "total": len(res), "offset": 0, "limit": limit, "interpretation": [], "notes": [],
                "partial": False, "facets": {}}
    opts = tuple(o for o in (options or "").split(",") if o)
    try:
        res = S.search(_con().cursor(), q, fili=fili, academie=academie, selective=selective, near=near,
                       options=opts, offset=offset, limit=limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if offset == 0:   # pagination is not a new search
        refined = any(v is not None and v != "" for v in (fili, academie, selective, options))  # near = profile
        bg.add_task(A.record, "refine" if refined else "search",
                    {"q": A.clean_query(q), "total": res["total"], "partial": bool(res.get("partial"))},
                    _hdrs(request))
    return res


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
    if rec.get("series_sum_mismatch") or rec.get("mention_sum_mismatch"):
        w.append({"code": "sies_identity", "text": "Incohérence dans l'export SIES : la décomposition par "
                  + ("série" if rec.get("series_sum_mismatch") else "mention")
                  + " ne s'additionne pas exactement aux admis néo-bacheliers. Données reprises telles quelles."})
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
            "history": lineage(rec["lineage_id"])["years"], "warnings": _warnings(rec, peers),
            "success": SU.for_formation(_con().cursor(), rec["cod_aff_form"], rec.get("fili"), rec.get("contrat_etab"))}


OFFER = ("carto_session", "apprentissage", "internat", "distance", "amenag_sport", "amenag_art")
DECOMP = ("series_sum_mismatch", "mention_sum_mismatch", "acc_tot", "acc_term", "acc_neobac", "acc_at", *SERIES_FIELDS, *MENTION_FIELDS, "acc_brs",
          "acc_tot_f", "pct_f", "pct_bours", "pct_aca_orig", "pct_etab_orig", "pct_bg", "pct_bt", "pct_bp",
          "pct_tb", "pct_tbf", "taux_acces_ens", "part_terminale_generale_en_position_admis_pp",
          "voe_tot", "nb_voe_pp", "nb_cla_pp", "prop_tot", "capa_fin", "low_n_flag", "subwish_flag",
          "acc_pp", "acc_pc", "pct_acc_debutpp", "pct_acc_datebac", "pct_acc_finpp", "acc_internat")


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
                                *DECOMP, *OFFER)},
                    "peers": f["peers"], "history": f["history"], "warnings": f["warnings"]})
    return {"formations": out}


@app.get("/api/specialites")
def specialites(session: int | None = None, formation_type: str | None = None):
    """Admission profile by Terminale specialty doublette, for one type of formation.

    The SIES specialty exports publish admission proposals and acceptances per
    (type of formation, doublette), with no candidate counts. So the matrix shows
    each doublette's share of the type's accepted students. It is a composition of
    one stage (acceptances), never a rate across stages.

    The 2025 export stacks three aggregation levels (0 = all bacheliers, 1 = a group of
    formations, 2 = its detailed formations, which repeat the level-1 totals). Only
    levels 0-1 are read, so no acceptance is counted twice. 2021-2024 have one level.
    """
    level = "coalesce(aggregation_level, '1') IN ('0', '1')"
    session = session or config.LATEST_YEAR
    types = [r["formation_type"] for r in rows(
        f"""SELECT formation_type FROM core.specialites WHERE session = ? AND formation_type IS NOT NULL
           AND {level} GROUP BY 1 ORDER BY sum(n_accepte) DESC NULLS LAST, 1""", [session])]
    ftype = formation_type if formation_type in types else (types[0] if types else None)
    res = rows(f"""
      SELECT session, formation_type, doublette, n_candidats, n_proposition, n_accepte,
        round(100.0 * n_accepte / nullif(sum(n_accepte) OVER (), 0), 1) AS pct_acceptations,
        round(100.0 * n_proposition / nullif(sum(n_proposition) OVER (), 0), 1) AS pct_propositions
      FROM core.specialites WHERE session = ? AND formation_type = ? AND {level}
      ORDER BY n_accepte DESC NULLS LAST, doublette""", [session, ftype])
    return {"session": session, "formation_type": ftype, "formation_types": types, "rows": res,
            "totals": {"n_accepte": sum(r["n_accepte"] or 0 for r in res),
                       "n_proposition": sum(r["n_proposition"] or 0 for r in res)}}


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


@app.get("/api/verification")
def verification():
    """Latest ground-truth verification report written by scripts/verify_ground_truth.py."""
    path = _db_path().parent / "verification" / "verification.json"
    if not path.exists():
        raise HTTPException(404, "aucun rapport de vérification publié")
    rep = json.loads(path.read_text())
    return {k: rep.get(k) for k in ("generated_at", "overall", "n_failed_checks", "identities", "taux_raw",
                                    "taux_live", "structure")}


def _journey_ready():
    try:
        rows("SELECT 1 FROM mart.spe_filiere LIMIT 1")
        rows("SELECT 1 FROM core.taxonomy_link LIMIT 1")
    except duckdb.CatalogException:
        raise HTTPException(503, "Couche « parcours » absente de cet entrepôt : relancer python -m suptracker.build")


def _dkey(spe1: str, spe2: str) -> str:
    a, b = spe1.upper(), spe2.upper()
    if a not in J.SPECIALTIES or b not in J.SPECIALTIES or a == b:
        raise HTTPException(422, "Choisir deux enseignements de spécialité distincts")
    return J.doublette_key(a, b)


@app.get("/api/journey/persona")
def journey_persona():
    """Latest persona calibration report written by scripts/verify_persona.py."""
    path = _db_path().parent / "verification" / "persona.json"
    if not path.exists():
        raise HTTPException(404, "aucun rapport de calibration publié")
    return json.loads(path.read_text())


@app.get("/api/journey/vocab")
def journey_vocab():
    _journey_ready()
    nat = rows("""SELECT doublette_key, sum(voeux) AS candidates, sum(acceptations) AS accepted
                  FROM mart.spe_filiere WHERE type_key = ? GROUP BY 1 ORDER BY 3 DESC""", [J.NATIONAL_TYPE])
    acads = [r["acad_mies"] for r in rows("""SELECT DISTINCT acad_mies FROM core.formation_year
               WHERE session = (SELECT max(session) FROM core.formation_year) AND acad_mies IS NOT NULL ORDER BY 1""")]
    return {"specialties": [{"code": k, "label": v, "short": J.SPECIALTY_SHORT[k]} for k, v in J.SPECIALTIES.items()],
            "mentions": [{"code": m, "label": J.MENTION_LABEL[m]} for m in J.MENTIONS[:4]],
            "series": [{"code": k, "label": v} for k, v in J.SERIES_LABEL.items()],
            "academies": acads, "doublettes": nat, "zone_rules": J.ZONE_RULES, "gate_rules": J.GATE_RULES}


@app.get("/api/journey/stage1")
def journey_stage1(request: Request, bg: BackgroundTasks, spe1: str | None = None, spe2: str | None = None,
                   serie: str = Query("bg", pattern="^(bg|bt|bp)$")):
    _journey_ready()
    if serie != "bg":                    # B4: no specialties for bac technologique / professionnel
        res = J.stage1_series(_con().cursor(), serie)
        bg.add_task(A.record, "journey", {"stage": "stage1"}, _hdrs(request))
        return res
    if not spe1 or not spe2:
        raise HTTPException(422, "Choisir deux enseignements de spécialité distincts")
    res = J.stage1(_con().cursor(), _dkey(spe1, spe2))
    if not res["national"] or not res["national"]["candidates"]:
        raise HTTPException(404, "Doublette absente des données SIES 2022–2025")
    bg.add_task(A.record, "journey", {"stage": "stage1"}, _hdrs(request))
    return res


@app.get("/api/journey/stage2")
def journey_stage2(mention: str, type: str, request: Request, bg: BackgroundTasks,
                   spe1: str | None = None, spe2: str | None = None,
                   serie: str = Query("bg", pattern="^(bg|bt|bp)$"),
                   academie: str | None = None, sex: str | None = Query(None, pattern="^[FM]$")):
    _journey_ready()
    if serie == "bg" and (not spe1 or not spe2):
        raise HTTPException(422, "Choisir deux enseignements de spécialité distincts")
    dkey = _dkey(spe1, spe2) if serie == "bg" else None
    try:
        res = J.stage2(_con().cursor(), dkey, mention, type, academie, sex, serie=serie)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    CAL.attach(_con().cursor(), res, mention)
    bg.add_task(A.record, "journey", {"stage": "stage2"}, _hdrs(request))
    return res


LYCEE_FIELDS = ("uai", "nom", "commune", "academie", "academie_ips", "type", "secteur", "ips_etab", "ips_gt",
                "ips_national", "ips_academique", "rentree")
IVAL_FIELDS = ("session", "presents_total", "taux_reu_total", "va_reu_total", "taux_men_total", "va_men_total",
               "taux_acces_2nde", "va_acces_2nde")


@app.get("/api/lycees")
def lycees():
    """Sprint 4: every lycée with its context (IPS, IVAL), sent whole so the student's choice of
    lycée never reaches the server: the page searches and reads it locally. No parameter on purpose."""
    try:
        rows = _con().cursor().execute(f"SELECT {', '.join(LYCEE_FIELDS)} FROM ref.lycee ORDER BY uai").fetchall()
        ival = _con().cursor().execute(f"SELECT uai, {', '.join(IVAL_FIELDS)} FROM ref.lycee_ival ORDER BY uai, session DESC").fetchall()
    except duckdb.Error:   # warehouse built before sprint 4
        rows, ival = [], []
    by = {}
    for r in ival:
        v = dict(zip(IVAL_FIELDS, r[1:]))
        # same fixed rules as every other figure (evidence.grade): headcount, session age, official id (UAI)
        g, _ = EV.grade(v["taux_reu_total"], v["presents_total"], v["session"], "identifiant")
        by.setdefault(r[0], []).append([*r[1:], g])
    body = {"fields": LYCEE_FIELDS, "rows": [list(r) for r in rows], "ival_fields": (*IVAL_FIELDS, "fiabilite"), "ival": by}
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/planb/{cod}")
def planb(cod: str, mention: str = Query("ab", pattern="^(sansmention|ab|b|tb)$"),
          serie: str = Query("bg", pattern="^(bg|bt|bp)$"), spe1: str | None = None, spe2: str | None = None,
          academie: str | None = Query(None, max_length=80), include_paid: bool = False):
    """Plan B: the same programme elsewhere, more accessible for the student's profile."""
    _journey_ready()
    if not cod.isdigit() or len(cod) > 9:
        raise HTTPException(422, "code formation invalide")
    if serie == "bg" and (not spe1 or not spe2):
        raise HTTPException(422, "Choisir deux enseignements de spécialité distincts")
    dkey = _dkey(spe1, spe2) if serie == "bg" else None
    try:
        return PB.plan_b(_con().cursor(), cod, serie=serie, dkey=dkey, mention=mention, academie=academie or None,
                         include_paid=include_paid)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@app.get("/api/continuity")
def continuity():
    return {"anchor": config.LATEST_YEAR, "rows": continuity_report(_con().cursor())}


# ---------------------------------------------------------------- audience measurement
def _hdrs(request: Request) -> dict:
    """Request headers plus the socket peer, the IP fallback when no proxy header is set
    (direct uvicorn, Docker without a proxy). Always overwritten, so a client cannot forge it."""
    h = dict(request.headers)
    h[A.PEER_KEY] = request.client.host if request.client else ""
    return h


@app.post("/api/e", status_code=204)
async def event(request: Request, bg: BackgroundTasks):
    """Beacon from the front-end (see suptracker/analytics.py for what is, and is not, kept)."""
    if int(request.headers.get("content-length") or 0) > A.MAX_BODY:
        raise HTTPException(413, "payload too large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > A.MAX_BODY:
            raise HTTPException(413, "payload too large")
    try:
        t, props = A.validate_client_event(json.loads(body or b"null"))
    except (ValueError, A.Rejected):
        A.record_invalid(_hdrs(request))
        raise HTTPException(422, "invalid event") from None
    bg.add_task(A.record, t, props, _hdrs(request))
    return Response(status_code=204)


def _fiche_labels(cods: list[str]) -> dict:
    try:
        rs = rows("""SELECT cod_aff_form, g_ea_lib_vx, fil_lib_voe_acc, ville_etab FROM core.formation_year
                     WHERE cod_aff_form IN (SELECT unnest(?)) QUALIFY row_number() OVER
                     (PARTITION BY cod_aff_form ORDER BY session DESC) = 1""", [cods])
    except Exception:  # noqa: BLE001 - the dashboard still works without the warehouse
        return {}
    return {r["cod_aff_form"]: {"etablissement": r["g_ea_lib_vx"], "filiere": r["fil_lib_voe_acc"],
                                "ville": r["ville_etab"]} for r in rs}


@app.get("/api/stats")
def stats(request: Request, days: int = Query(30, ge=7, le=180)):
    """Audience dashboard data. Requires `Authorization: Bearer $SUPTRACKER_STATS_TOKEN`."""
    token = os.environ.get("SUPTRACKER_STATS_TOKEN", "")
    if len(token) < 16:
        raise HTTPException(503, "Tableau de bord désactivé : définissez SUPTRACKER_STATS_TOKEN "
                                 "(au moins 16 caractères) dans les variables d'environnement.")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "Jeton invalide")
    try:
        data = A.summarize(days, labels=_fiche_labels)
    except Exception as exc:  # noqa: BLE001 - e.g. the analytics store is unreachable
        raise HTTPException(502, f"Stockage des mesures injoignable : {type(exc).__name__}") from None
    return JSONResponse(data, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


FEATURES = ["search", "analytics", "offer_timing", "offer_options", "bg_mention_bounds", "series_journey", "plan_b", "plan_b_parcours", "licence_success", "glossary", "reliability", "lycee_profile", "repere"]


@lru_cache(maxsize=1)
def _asset_version() -> str:
    """Fingerprint of the front-end files: it changes with every release, so a browser never keeps
    an old app.js after a deployment (the cause of 'features disappeared' after an update)."""
    import hashlib
    h = hashlib.sha256()
    for name in ("app.js", "stats.js", "style.css", "index.html"):
        h.update((STATIC / name).read_bytes())
    return h.hexdigest()[:12]


def _commit() -> str | None:
    """The deployed commit (Vercel sets VERCEL_GIT_COMMIT_SHA; Docker can pass SUPTRACKER_COMMIT)."""
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("SUPTRACKER_COMMIT")
    return sha[:7] if sha else None


@app.get("/api/version")
def version():
    """What is live: commit, branch, front-end fingerprint and features. Never cached."""
    return JSONResponse({"commit": _commit(), "branch": os.environ.get("VERCEL_GIT_COMMIT_REF"),
                         "environment": os.environ.get("VERCEL_ENV"), "assets": _asset_version(),
                         "features": FEATURES}, headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    v = _asset_version()
    html = (STATIC / "index.html").read_text()
    for name in ("app.js", "stats.js", "style.css"):
        html = html.replace(f'"/static/{name}"', f'"/static/{name}?v={v}"')
    label = _commit() or v
    html = html.replace("<!--version-->", f'<span class="muted">version {label}</span>')
    # the page itself must never be cached: it is what points to the current asset fingerprint
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})
