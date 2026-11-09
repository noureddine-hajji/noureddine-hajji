"""How far each formation called its list, and when its offers came (owner's request, 2026-11-09: help students PREPARE
their choice of vœux; they have no rank yet, so nothing here asks for one).

Published counts only (SIES):
  * per calling group, the rank of the last candidate who received an offer in the main phase (`ran_grp1..3`, label
    `lib_grp1..3`);
  * the candidates who confirmed the vœu (`nb_voe_pp`) and those the jury RANKED (`nb_cla_pp`), all groups together.
The calling groups split the candidates without overlap, so the SUM of the groups' last-called ranks is the number of
ranked candidates who were called in the main phase (data check, 2025: the sum equals the ranked count for 5 646 formations
and exceeds it for 1 of 14 191; in 2022-2024 about one in ten exceed it). The "profondeur d'appel" is min(1, sum / ranked):
a sum at or beyond the ranked count reads "toute la liste", never a share above 100 %. It describes past campaigns, never a
chance; the student has no rank yet, and none is asked.

Offer timing by type of diploma: the medians, over the formations of the type, of the three PUBLISHED cumulative shares
(`pct_acc_debutpp` <= `pct_acc_datebac` <= `pct_acc_finpp`), zero-admit rows left out (they carry 0 % shares).
"""
from __future__ import annotations

from statistics import median

from . import carte as CA

GROUPS = (1, 2, 3)


def depth(rank, ranked) -> tuple[float | None, bool]:
    """(share of the ranked candidates called, whole list called) for a single-group formation."""
    if rank is None or not ranked:
        return None, False
    if rank >= ranked:
        return 1.0, True
    return rank / ranked, False


def for_formation(con, cod: str) -> list[dict]:
    """One row per campaign: candidates, ranked, groups with their last-called rank, and the depth when it is defined."""
    rows = con.execute(f"""SELECT session, nb_voe_pp, nb_cla_pp, capa_fin, {", ".join(f"lib_grp{g}, ran_grp{g}" for g in GROUPS)}
                           FROM core.formation_year WHERE cod_aff_form = ? ORDER BY session""", [cod]).fetchall()
    out = []
    for s, cand, ranked, capa, *grp in rows:
        groups = [{"label": grp[2 * i], "rang": grp[2 * i + 1]} for i in range(len(GROUPS)) if grp[2 * i + 1] is not None]
        single = len(groups) == 1
        d, whole = depth(sum(g["rang"] for g in groups), ranked) if groups else (None, False)
        out.append({"session": s, "candidats": cand, "classes": ranked, "places": capa, "groupes": groups,
                    "un_groupe": single, "profondeur": None if d is None else round(100 * d, 1), "toute_la_liste": whole})
    return out


def by_type(con) -> dict:
    """Per type of diploma (the map's types), latest campaign: medians of the depth (formations with a ranked count) and of the
    three offer-timing shares (formations with admits)."""
    rows = con.execute(f"""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins, nb_cla_pp, acc_tot,
               pct_acc_debutpp, pct_acc_datebac, pct_acc_finpp, {", ".join(f"ran_grp{g}" for g in GROUPS)}
        FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    acc: dict = {}
    for fili, form, fil, lib, ranked, admits, t0, t1, t2, *ranks in rows:
        x = acc.setdefault(CA.diplome_of(fili, form, fil, lib)[0], {"n": 0, "depths": [], "whole": 0, "t": ([], [], [])})
        x["n"] += 1
        given = [r for r in ranks if r is not None]
        if given:
            d, whole = depth(sum(given), ranked)
            if d is not None:
                x["depths"].append(d)
                x["whole"] += whole
        if admits and all(v is not None for v in (t0, t1, t2)):
            for lst, v in zip(x["t"], (t0, t1, t2)):
                lst.append(v)
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    types = []
    for label, x in sorted(acc.items(), key=lambda kv: -kv[1]["n"]):
        n1 = len(x["depths"])
        types.append({"diplome": label, "n": x["n"], "n_profondeur": n1,
                      "profondeur_mediane": round(100 * median(x["depths"]), 1) if n1 else None,
                      "part_toute_la_liste": round(100 * x["whole"] / n1, 1) if n1 else None,
                      "n_calendrier": len(x["t"][0]),
                      "calendrier": [round(median(v), 1) if v else None for v in x["t"]]})
    return {"session": session, "types": types}
