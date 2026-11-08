"""Sprint "Carte": the formations of one filière type on a map (latest campaign).

The neutral layer (no profile) comes from here: code, names, place, coordinates, status, selectivity, boarding and the
official access rate. The zones (sécurité / cible / ambitieux) are NEVER computed here: with a profile the page asks
/api/journey/stage2, the same rows as "Mon parcours", Plan B and "Mes vœux". The visitor's position is never sent: the
"around a town" filter runs in the browser.
"""
from __future__ import annotations

from . import planb as PB

FIELDS = ["cod_aff_form", "etablissement", "formation", "ville", "academie", "lat", "lon", "contrat_etab", "select_form",
          "internat", "taux_acces_ens", "fil_lib_voe_acc"]


def types(con) -> list[dict]:
    """The filière types a map can show, with their number of formations in the latest campaign."""
    return [{"type_key": k, "label": l, "n": n} for k, l, n in con.execute("""
        SELECT r.spe_type_key, any_value(r.spe_type), count(DISTINCT t.cod_aff_form)
        FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        WHERE t.session = (SELECT max(session) FROM core.formation_year)
        GROUP BY 1 ORDER BY 3 DESC, 2""").fetchall()]


def formations(con, type_key: str) -> dict | None:
    rows = con.execute("""
        WITH s AS (SELECT max(session) AS s FROM core.formation_year)
        SELECT f.cod_aff_form, f.g_ea_lib_vx, f.lib_for_voe_ins, f.ville_etab, f.acad_mies, f.lat, f.lon, f.contrat_etab,
               f.select_form, c.internat, f.taux_acces_ens, f.fil_lib_voe_acc
        FROM core.formation_year f, s
        JOIN core.taxonomy_link t ON t.cod_aff_form = f.cod_aff_form AND t.session = f.session
        JOIN core.taxonomy_rule r USING (rule_id)
        LEFT JOIN core.cartographie c ON c.cod_aff_form = f.cod_aff_form
        WHERE f.session = s.s AND r.spe_type_key = ?
        ORDER BY f.g_ea_lib_vx, f.cod_aff_form""", [type_key]).fetchall()
    if not rows:
        return None
    out = [dict(zip(FIELDS, r)) for r in rows]
    for x in out:
        x["payant"] = x["contrat_etab"] in PB.PAID_CONTRACTS        # Plan B's rule: shown only on request, flagged
    label = con.execute("SELECT any_value(spe_type) FROM core.taxonomy_rule WHERE spe_type_key = ?", [type_key]).fetchone()[0]
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"type_key": type_key, "label": label, "session": session, "formations": out}
