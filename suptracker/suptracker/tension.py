"""Formations under pressure: how many vœux a formation received for each of its places (owner, 2026-11-15).

The "vœux par place" of a formation and a campaign = the vœux it received in the main phase (`nb_voe_pp`, the candidates
who listed it) / its places (`capa_fin`). Both are PUBLISHED counts; the ratio is computed here, so the page labels it.
It measures DEMAND, not difficulty: a candidate makes up to 10 vœux, most of the candidates listed go elsewhere, and
the official access rate says how many received a proposal. The page always shows the ratio with its two counts and
never as a chance.

Position: the ratio is placed among the formations of the SAME type (`fili`) and campaign that publish places:
  * "tres": at or above the 90th percentile of its type ("Forte demande" in the lists),
  * "forte": at or above the 75th percentile (said on the formation page only),
  * none otherwise. A type with fewer than 20 formations gets no position (too few to compare).
Fixed rule, one function (`classe`), the page reads the class the build stored; zero or missing places = no ratio.
"""
from __future__ import annotations

MIN_TYPE = 20
SEUILS = (("tres", 0.90), ("forte", 0.75))
LIBELLE = {"tres": "Forte demande", "forte": "Demande élevée"}
EXPLICATION = {
    "tres": "Parmi les 10 % des formations de ce type qui reçoivent le plus de vœux par place.",
    "forte": "Parmi les 25 % des formations de ce type qui reçoivent le plus de vœux par place.",
}
PRUDENCE = ("Beaucoup de vœux par place ne veut pas dire peu de chances : chaque candidat fait plusieurs vœux et la plupart "
            "partent ailleurs. Le taux d'accès dit combien de candidats ont reçu une proposition.")


def classe(par_place: float | None, p75: float | None, p90: float | None, n_type: int) -> str | None:
    """The class of one ratio among its type (the fixed rule)."""
    if par_place is None or p75 is None or p90 is None or n_type < MIN_TYPE:
        return None
    if par_place >= p90:
        return "tres"
    if par_place >= p75:
        return "forte"
    return None


def build(con) -> dict:
    """mart.tension: one row per (formation, campaign) with places: vœux, places, ratio, type, its size and percentiles,
    the class."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    rows = con.execute("""
        WITH r AS (
            SELECT cod_aff_form, session, fili, nb_voe_pp AS voeux, capa_fin AS places,
                   nb_voe_pp * 1.0 / capa_fin AS par_place
            FROM core.formation_year
            WHERE capa_fin > 0 AND nb_voe_pp IS NOT NULL),
        q AS (
            SELECT session, fili, count(*) AS n_type,
                   quantile_cont(par_place, 0.75) AS p75, quantile_cont(par_place, 0.90) AS p90
            FROM r GROUP BY session, fili)
        SELECT r.*, q.n_type, q.p75, q.p90 FROM r JOIN q USING (session, fili)""").fetchall()
    import pandas as pd
    df = pd.DataFrame(rows, columns=["cod_aff_form", "session", "fili", "voeux", "places", "par_place", "n_type", "p75", "p90"])
    df["classe"] = [classe(pp, a, b, n) for pp, a, b, n in zip(df["par_place"], df["p75"], df["p90"], df["n_type"])]
    con.register("tension_df", df)
    con.execute("""CREATE OR REPLACE TABLE mart.tension AS SELECT cod_aff_form, session, fili, CAST(voeux AS INTEGER) AS voeux,
        CAST(places AS INTEGER) AS places, CAST(par_place AS DOUBLE) AS par_place, CAST(n_type AS INTEGER) AS n_type,
        CAST(p75 AS DOUBLE) AS p75, CAST(p90 AS DOUBLE) AS p90, CAST(classe AS VARCHAR) AS classe FROM tension_df""")
    con.unregister("tension_df")
    out = dict(con.execute("SELECT coalesce(classe, 'aucune'), count(*) FROM mart.tension GROUP BY 1").fetchall())
    return out


def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'mart'
        AND table_name = 'tension'""").fetchone()[0])


def for_formation(con, cod: str, session: int) -> dict | None:
    """The ratio of one formation at the page's campaign, with its counts, its type and its class."""
    if not _has(con):
        return None
    r = con.execute("""SELECT voeux, places, par_place, fili, n_type, classe FROM mart.tension
        WHERE cod_aff_form = ? AND session = ?""", [cod, session]).fetchone()
    if not r:
        return None
    voeux, places, pp, fili, n, cl = r
    return {"voeux": voeux, "places": places, "par_place": round(pp, 1), "type": fili, "n_type": n, "classe": cl,
            "libelle": LIBELLE.get(cl), "explication": EXPLICATION.get(cl), "prudence": PRUDENCE}


def compact(con) -> dict:
    """For the lists (search, map, Mes vœux, comparator): the codes of the latest campaign in class "tres" (served with
    the recognition badges by /api/reconnaissance: one shared-cached answer, no parameter)."""
    out = {"libelle": LIBELLE["tres"], "explication": EXPLICATION["tres"], "tres": ""}
    if not _has(con):
        return out
    out["tres"] = ",".join(c for (c,) in con.execute("""SELECT cod_aff_form FROM mart.tension
        WHERE session = (SELECT max(session) FROM mart.tension) AND classe = 'tres' ORDER BY cod_aff_form""").fetchall())
    return out
