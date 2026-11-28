"""Doing a formation as an apprentice (sprint V2, owner 2026-11-15): what the student gains and where to look.

Merged with what exists (the apprenticeship offers attached to an initial formation, `carte.offres_par_formation`, and the
Inserjeunes insertion rows of each BTS, `core.inserjeunes_bts`), one block per formation:
  * the offers: the CFA of the latest cartographie that teach the same diploma in the same establishment (as today), and
    whether the SIES formation itself is an apprenticeship one;
  * the national comparison for a BTS: Inserjeunes publishes, per establishment, the employment rate 6 months after leaving
    and the share continuing their studies, for the lycées (voie scolaire) and the CFA (apprentissage). No headcount is
    published, so no national rate can be computed: the block shows the MEDIAN OF THE ESTABLISHMENTS that publish the rate,
    with their number, for each route, always labelled ("médiane des établissements", an estimation), at least
    MIN_ETAB establishments per route, never a single establishment and never a promise;
  * official links, all on La bonne alternance (the State's apprenticeship service, DINUM / ministries of Labour and
    Education): the companies that recruit apprentices, the salary simulator and its guide to the apprentice's pay.
The apprentice pays no tuition (Code du travail, art. L6211-1) and is paid a share of the Smic set by age and year: since PR 18
(owner, 2026-11-28) the OFFICIAL table is quoted as service-public.gouv.fr prints it (aides.r_apprenti: cells verbatim, its
« Vérifié le » date, its own links), never a salary computed for the student.

« Mes vœux en apprentissage » (PR 18, owner 2026-11-28, reversing the 2026-11-08 rule « never Mes vœux »): the student keeps a
SEPARATE list of apprenticeship offers of the latest cartographie (`voeux`): its own counter, its own cap (Parcoursup's « 10 vœux
supplémentaires pour des formations en apprentissage », read from the official calendar by the page), NO zone, NO rate, NO
SIES figure, never counted among the main list's zones and never a safety. Each offer comes back with its Parcoursup page and
the initial formation it is attached to (same establishment, same diploma); a code absent from the latest map says so
(« vérifiez qu'elle existe toujours »), never « fermée ». The list's codes only: no shared cache, no audience event.
"""
from __future__ import annotations

from . import aides as AID
from . import carte
from .insertion import bts_key

MIN_ETAB = 5
LBA_HOST = "https://labonnealternance.apprentissage.beta.gouv.fr/"
LBA_URL = LBA_HOST
SIMULATEUR_URL = LBA_HOST + "salaire-alternant"
GUIDE_URL = LBA_HOST + "guide-alternant/comprendre-la-remuneration"
ROUTES = {"apprentissage": "En apprentissage (CFA)", "lycee": "En voie scolaire (lycée)"}


# One value per ESTABLISHMENT first (Codex): Inserjeunes can publish several diploma codes of the same BTS title at one UAI
# (a renewed diploma, 42 establishments x route on the 2023-2024 file); their published values are reduced to their median,
# so an establishment counts once, in the threshold, in the count shown and in the median.
ETAB_SQL = """INSERT INTO mart.app_insertion
        WITH e AS (
            SELECT cle, source, uai, any_value(annee) AS annee,
                   median(taux_emploi_6) AS emploi, median(taux_poursuite) AS poursuite
            FROM core.inserjeunes_bts WHERE cle IS NOT NULL AND uai IS NOT NULL GROUP BY cle, source, uai)
        SELECT cle, source, any_value(annee), count(*),
               count(emploi), median(emploi), quantile_cont(emploi, 0.25), quantile_cont(emploi, 0.75),
               count(poursuite), median(poursuite)
        FROM e GROUP BY cle, source"""


def build(con) -> int:
    """mart.app_insertion: per BTS key and route, the number of DISTINCT establishments and the median (and quartiles) of
    the published employment rate at 6 months and share continuing, among the establishments that publish each (one value
    per establishment, `ETAB_SQL`). Built after insertion.build (core.inserjeunes_bts)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    con.execute("""CREATE OR REPLACE TABLE mart.app_insertion (cle VARCHAR, voie VARCHAR, annee VARCHAR, n_etab INTEGER,
        n_emploi INTEGER, emploi_med DOUBLE, emploi_q1 DOUBLE, emploi_q3 DOUBLE, n_poursuite INTEGER, poursuite_med DOUBLE)""")
    try:
        n = con.execute("SELECT count(*) FROM core.inserjeunes_bts").fetchone()[0]
    except Exception:  # noqa: BLE001  (a warehouse without Inserjeunes)
        return 0
    if not n:
        return 0
    con.execute(ETAB_SQL)
    return con.execute("SELECT count(*) FROM mart.app_insertion").fetchone()[0]


def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'mart'
        AND table_name = 'app_insertion'""").fetchone()[0])


def national(con, prog: str | None) -> dict | None:
    """The comparison for one BTS title: each route kept only with MIN_ETAB establishments publishing the rate."""
    if not prog or not _has(con):
        return None
    k = bts_key(prog)
    out = {"cle": k, "voies": []}
    for voie, annee, n_etab, n_e, med, q1, q3, n_p, pmed in con.execute("""SELECT voie, annee, n_etab, n_emploi, emploi_med,
            emploi_q1, emploi_q3, n_poursuite, poursuite_med FROM mart.app_insertion WHERE cle = ? ORDER BY voie""", [k]).fetchall():
        if n_e >= MIN_ETAB:
            out["voies"].append({"voie": voie, "libelle": ROUTES.get(voie, voie), "annee": annee, "n_etab": n_etab,
                                 "n_emploi": n_e, "emploi_med": round(med), "emploi_q1": round(q1), "emploi_q3": round(q3),
                                 "n_poursuite": n_p, "poursuite_med": None if pmed is None or n_p < MIN_ETAB else round(pmed)})
    out["voies"].sort(key=lambda v: 0 if v["voie"] == "apprentissage" else 1)
    return out if out["voies"] else None


def for_formation(con, cod: str, session: int) -> dict | None:
    """The apprenticeship block of one formation: its offers (`propose` when it can be done as an apprentice here), the
    national comparison of the routes for a BTS (shown on EVERY BTS page: the same BTS can be prepared as an apprentice
    elsewhere), the official links. None when there is neither an offer nor a comparison."""
    r = con.execute("""SELECT fili, fil_lib_voe_acc, coalesce(apprentissage, false) FROM core.formation_year
        WHERE cod_aff_form = ? AND session = ?""", [cod, session]).fetchone()
    if not r:
        return None
    fili, prog, sies_app = r
    offres = carte.for_formation(con, cod)
    nat = national(con, prog) if fili == "BTS" else None
    if not offres and not sies_app and not nat:
        return None
    return {"propose": bool(offres or sies_app), "offres": offres, "sies_apprentissage": bool(sies_app), "national": nat,
            "liens": {"entreprises": LBA_URL, "salaire": SIMULATEUR_URL, "guide": GUIDE_URL}, "officiel": officiel(con)}


def officiel(con) -> dict | None:
    """PR 18: the official contract sentences and minimum-pay table (aides.r_apprenti), None when the page was not read."""
    A = AID.national(con) or {}
    return A.get("apprenti")


MAX_IDS = 10
OFFER_KEYS = ("cod_aff_form", "etablissement", "formation", "ville", "academie", "lat", "lon", "statut", "diplome", "mention",
              "parcours", "fiche", "session_offre")


def offres(con) -> dict:
    """{code: offer} of EVERY apprenticeship offer of the latest cartographie session (attached or listed apart)."""
    return {a["cod_aff_form"]: a for a in carte.apprentissage(con)}


def voeux(con, ids: list[str]) -> dict:
    """The student's apprenticeship list, in its order: each offer as the map lists it (no figure), with the initial
    formations it is attached to (`rattachee`, their names) or `absente` from the latest map."""
    O = offres(con)
    s = carte._offer_session(con) if O else None
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    noms = {}
    att = sorted({y for c in ids if c in O for y in O[c]["rattachee"]})
    if att:
        q = ",".join("?" * len(att))
        noms = {c: (e, f) for c, e, f in con.execute(f"""SELECT cod_aff_form, any_value(g_ea_lib_vx), any_value(lib_for_voe_ins)
            FROM core.formation_year WHERE session = ? AND cod_aff_form IN ({q}) GROUP BY 1""", [latest, *att]).fetchall()}
    out = []
    for cod in ids:
        a = O.get(cod)
        if not a:
            out.append({"cod_aff_form": cod, "status": "absente"})
            continue
        out.append({**{k: a.get(k) for k in OFFER_KEYS}, "status": "ok",
                    "rattachee": [{"cod_aff_form": y, "etablissement": noms.get(y, (None, None))[0],
                                   "formation": noms.get(y, (None, None))[1]} for y in a["rattachee"]]})
    return {"carte_session": s, "session": latest, "voeux": out, "officiel": officiel(con),
            "liens": {"entreprises": LBA_URL, "salaire": SIMULATEUR_URL, "guide": GUIDE_URL}}


def codes(con) -> str:
    """The formations of the latest campaign that can be done as an apprentice (an attached offer, or an apprenticeship
    formation itself), "cod,cod": the lists show a badge (served by /api/reconnaissance, no parameter)."""
    out = set(carte.offres_par_formation(con))
    out |= {c for (c,) in con.execute("""SELECT cod_aff_form FROM core.formation_year
        WHERE session = (SELECT max(session) FROM core.formation_year) AND coalesce(apprentissage, false)""").fetchall()}
    return ",".join(sorted(out, key=lambda c: (len(c), c)))
