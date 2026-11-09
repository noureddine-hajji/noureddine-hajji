"""The "vraie sélectivité" matrix (owner's request, 2026-11-09): a low access rate can mean many candidates for the places
or very demanding admissions. Two PUBLISHED figures place each formation of a type of diploma (and mention), latest campaign:
  * x: the official access rate (`taux_acces_ens`), never recomputed;
  * y: the share of its néo-bachelier admits with a mention "Bien" or better (`pct_b + pct_tb + pct_tbf`; the mention shares
    are disjoint and add up to 100 % of the néo-bachelier admits).
A formation with fewer than MIN_ADMITS néo-bachelier admits, or without an access rate, is listed apart ("pas placée").
The quadrant lines are the MEDIANS of the placed formations of the selection (a fixed rule, recomputed for each selection);
the quadrant names describe a position, never a cause, a chance or a promise. Candidates per place (`nb_voe_pp / capa_fin`,
vœux not people) are shown as context only.
"""
from __future__ import annotations

from statistics import median

from . import carte as CA

MIN_ADMITS = 10
QUADRANTS = {  # (access rate at or above the median, share of mentions at or above the median) -> name
    (True, False): "Plus accessible",
    (False, False): "Très demandée",
    (True, True): "Admis souvent mentionnés",
    (False, True): "Très sélective",
}


def quadrant(taux: float, bien: float, med_taux: float, med_bien: float) -> str:
    return QUADRANTS[(taux >= med_taux, bien >= med_bien)]


def points(con, diplome: str, mention: str | None = None) -> dict | None:
    rows = con.execute("""
        SELECT cod_aff_form, g_ea_lib_vx, lib_for_voe_ins, ville_etab, fili, form_lib_voe_acc, fil_lib_voe_acc,
               taux_acces_ens, pct_b, pct_tb, pct_tbf, acc_neobac, nb_voe_pp, capa_fin
        FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
        ORDER BY g_ea_lib_vx, cod_aff_form""").fetchall()
    placed, apart = [], []
    for cod, etab, form, ville, fili, flib, fil, taux, b, tb, tbf, neo, cand, capa in rows:
        d, m = CA.diplome_of(fili, flib, fil, form)
        if d != diplome or (mention and m != mention):
            continue
        x = {"cod_aff_form": cod, "etablissement": etab, "formation": form, "ville": ville, "mention": m,
             "taux_acces_ens": taux, "admis_neobac": neo,
             "candidats_par_place": round(cand / capa, 1) if cand is not None and capa else None}
        if taux is None or neo is None or neo < MIN_ADMITS or b is None or tb is None:
            apart.append(x)
            continue
        x["part_bien_plus"] = round(b + tb + (tbf or 0), 1)
        placed.append(x)
    if not placed and not apart:
        return None
    med_t = median(p["taux_acces_ens"] for p in placed) if placed else None
    med_b = median(p["part_bien_plus"] for p in placed) if placed else None
    for p in placed:
        p["quadrant"] = quadrant(p["taux_acces_ens"], p["part_bien_plus"], med_t, med_b)
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"diplome": diplome, "mention": mention, "session": session, "min_admis": MIN_ADMITS,
            "mediane_taux": med_t, "mediane_bien": med_b, "formations": placed, "non_placees": apart}
