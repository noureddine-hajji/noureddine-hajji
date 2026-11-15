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


RATIOS_SQL = """
        WITH r AS (
            SELECT cod_aff_form, session, fili, nb_voe_pp AS voeux, capa_fin AS places,
                   nb_voe_pp * 1.0 / capa_fin AS par_place
            FROM core.formation_year
            WHERE capa_fin > 0 AND nb_voe_pp IS NOT NULL),
        q AS (
            SELECT session, fili, count(*) AS n_type,
                   quantile_cont(par_place, 0.75) AS p75, quantile_cont(par_place, 0.90) AS p90
            FROM r GROUP BY session, fili)
        SELECT r.*, q.n_type, q.p75, q.p90 FROM r JOIN q USING (session, fili)"""


def ratios(con) -> list[tuple]:
    """Every (formation, campaign) with places: code, campaign, type, vœux, places, ratio, size of its type, p75, p90, class."""
    return [(*r, classe(r[5], r[7], r[8], r[6])) for r in con.execute(RATIOS_SQL).fetchall()]


def build(con) -> dict:
    """mart.tension: only the classed formations (code, campaign, class): the ratio itself is two published counts of
    core.formation_year, read again by the page (the warehouse stays under 95 MB)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    con.execute("CREATE OR REPLACE TABLE mart.tension (cod_aff_form VARCHAR, session SMALLINT, classe VARCHAR)")
    rows = ratios(con)
    kept = [(r[0], r[1], r[9]) for r in rows if r[9]]
    if kept:
        con.executemany("INSERT INTO mart.tension VALUES (?, ?, ?)", kept)
    out = {"aucune": len(rows) - len(kept)}
    for _c, _s, cl in kept:
        out[cl] = out.get(cl, 0) + 1
    return out


def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'mart'
        AND table_name = 'tension'""").fetchone()[0])


def for_formation(con, cod: str, session: int) -> dict | None:
    """The ratio of one formation at the page's campaign, with its counts, the size of its type and its stored class."""
    if not _has(con):
        return None
    r = con.execute("""SELECT nb_voe_pp, capa_fin, fili FROM core.formation_year WHERE cod_aff_form = ? AND session = ?
        AND capa_fin > 0 AND nb_voe_pp IS NOT NULL""", [cod, session]).fetchone()
    if not r:
        return None
    voeux, places, fili = r
    n = con.execute("""SELECT count(*) FROM core.formation_year WHERE session = ? AND fili IS NOT DISTINCT FROM ?
        AND capa_fin > 0 AND nb_voe_pp IS NOT NULL""", [session, fili]).fetchone()[0]
    c = con.execute("SELECT classe FROM mart.tension WHERE cod_aff_form = ? AND session = ?", [cod, session]).fetchone()
    cl = c[0] if c else None
    return {"voeux": voeux, "places": places, "par_place": round(voeux / places, 1), "type": fili, "n_type": n, "classe": cl,
            "libelle": LIBELLE.get(cl), "explication": EXPLICATION.get(cl), "prudence": PRUDENCE}


def compact(con) -> dict:
    """For the lists (search, map, Mes vœux, comparator): the codes of the latest campaign in class "tres" (served with
    the recognition badges by /api/reconnaissance: one shared-cached answer, no parameter)."""
    out = {"libelle": LIBELLE["tres"], "explication": EXPLICATION["tres"], "tres": ""}
    if not _has(con):
        return out
    out["tres"] = ",".join(c for (c,) in con.execute("""SELECT cod_aff_form FROM mart.tension
        WHERE session = (SELECT max(session) FROM core.formation_year) AND classe = 'tres' ORDER BY cod_aff_form""").fetchall())
    return out
