"""The evolution page's context, year by year (owner, 2026-11-22: « lance les 6 propositions »).

Everything here is computed from PUBLISHED SIES counts of each campaign of a lineage (one row per campaign, each with its
own code and its own filière), never a chance:

  * `filiere`: the formations of the SAME `fil_lib_voe_acc` (diploma and mention, Plan B's notion of « the same formation
    elsewhere ») that campaign: how many publish an official access rate, and its quartiles (P25, median, P75). Fewer than
    MIN_FILIERE formations = no band (too few to compare).
  * `demande`: vœux par place (`nb_voe_pp` / `capa_fin`, tension.py's ratio) of the formation, and among the formations of its
    TYPE (`fili`, tension.py's grouping) that campaign: the median and the 90th percentile (« Forte demande » from there).
    Zero or missing places = no ratio; a type under tension.MIN_TYPE formations = no reference.
  * `appel`: how far the list was called (appel.py's depth: the SUM of the calling groups' last-called ranks / the ranked
    candidates, capped: « toute la liste » at or beyond the ranked count, never above 100 %).
The offer timing needs no context: the lineage rows carry the three published cumulative shares (the page leaves zero-admit
rows out). The next-campaign range of the access rate is prevision.py's (sprint 5 range), read from /api/formation.
"""
from __future__ import annotations

from . import appel as AP
from . import tension as TS

MIN_FILIERE = 20
PRUDENCE = TS.PRUDENCE          # the demand card's caution, the formation page's own words


def _quantiles(con, session: int, col: str, where: str, params: list) -> tuple:
    return con.execute(f"""SELECT count({col}), quantile_cont({col}, 0.25), quantile_cont({col}, 0.5), quantile_cont({col}, 0.75),
                                  quantile_cont({col}, 0.9)
                           FROM core.formation_year WHERE session = ? AND {where}""", [session, *params]).fetchone()


def contexte(con, years: list[dict]) -> list[dict]:
    """One entry per campaign of the lineage (its own code): the filière's access-rate quartiles, the demand and the call depth."""
    out = []
    for y in years:
        s, cod = y["session"], y["cod_aff_form"]
        row = con.execute(f"""SELECT fil_lib_voe_acc, fili, nb_voe_pp, capa_fin, nb_cla_pp,
                                     {", ".join(f"ran_grp{g}" for g in AP.GROUPS)}
                              FROM core.formation_year WHERE session = ? AND cod_aff_form = ?""", [s, cod]).fetchone()
        if not row:
            continue
        fil, fili, voeux, places, ranked, *ranks = row
        n, q1, med, q3, _ = _quantiles(con, s, "taux_acces_ens", "fil_lib_voe_acc = ? AND taux_acces_ens IS NOT NULL", [fil])
        filiere = {"libelle": fil, "n": n, "p25": q1, "p50": med, "p75": q3} if n >= MIN_FILIERE else {"libelle": fil, "n": n}
        ratio = voeux / places if places and voeux is not None else None
        nt, _, tmed, _, t90 = _quantiles(con, s, "nb_voe_pp * 1.0 / capa_fin", "fili = ? AND capa_fin > 0 AND nb_voe_pp IS NOT NULL", [fili])
        demande = {"voeux": voeux, "places": places, "par_place": ratio, "n_type": nt,
                   "type_p50": tmed if nt >= TS.MIN_TYPE else None, "type_p90": t90 if nt >= TS.MIN_TYPE else None}
        given = [r for r in ranks if r is not None]
        d, whole = AP.depth(sum(given), ranked) if given else (None, False)
        appel = {"classes": ranked, "groupes": len(given), "rang_total": sum(given) if given else None,
                 "profondeur": None if d is None else round(100 * d, 1), "toute_la_liste": whole}
        out.append({"session": s, "cod_aff_form": cod, "filiere": filiere, "demande": demande, "appel": appel})
    return out
