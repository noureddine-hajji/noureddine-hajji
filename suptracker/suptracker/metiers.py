"""Sprint 12: "Du métier aux formations", the reverse of the formation page's jobs card.

A job (Onisep Idéo fiche métier) is linked to the Onisep diploma sheets that list it; each diploma sheet that
matches a Parcoursup filière (onisep.match: BTS, BUT, licence, IFSI, EFTS) brings the formations of the latest
campaign that prepare it. Everything is the formation card read backwards, so both pages always agree
(red team M3): same sheets, same access flag ("accessible avec ce diplôme" when the job's minimum level is at most
the diploma's level read from its own sheet, "après une poursuite d'études" otherwise).

The list is NATIONAL: an establishment is listed because it prepares the diploma, never because it places its
students in the job. Nothing here is a chance or a promise of a job. Formations are listed in a neutral order
(académie, town, establishment), never by selectivity or "chances".

The job catalogue is sent whole (`/api/metiers` takes no parameter) and searched in the browser: what a student
looks for never reaches the server (as for the lycée, sprint 4).
"""
from __future__ import annotations

import re

from . import onisep as ON
from .search import clean_complement, fold

MET_ID = re.compile(r"^MET\.\d{1,6}$")
ORDER = {"direct": 0, None: 1, "poursuite": 2}


def _has(con) -> bool:
    return ON._has(con, "onisep_metier") and ON._has(con, "onisep_metier_libelle")


def catalogue(con) -> dict:
    """Every job with its search labels and how many diplomas / Parcoursup formations lead to it."""
    if not _has(con):
        return {"fields": [], "rows": []}
    labels = {}
    for mid, lab in con.execute("SELECT met_id, libelle FROM core.onisep_metier_libelle ORDER BY met_id, kind, libelle").fetchall():
        labels.setdefault(mid, []).append(lab)
    counts = dict((m, (d, f)) for m, d, f in con.execute("""
        SELECT fm.met_id, count(DISTINCT fm.for_id), count(DISTINCT l.cod_aff_form)
        FROM core.onisep_formation_metier fm LEFT JOIN core.onisep_link l USING (for_id) GROUP BY 1""").fetchall())
    rows = []
    for mid, nom, lvl in con.execute("SELECT met_id, nom, niveau_acces_min FROM core.onisep_metier ORDER BY nom").fetchall():
        d, f = counts.get(mid, (0, 0))
        rows.append([mid, nom, lvl, d, f, [x for x in labels.get(mid, []) if x != nom]])
    return {"fields": ["id", "nom", "niveau_acces_min", "n_diplomes", "n_formations", "libelles"], "rows": rows}


def detail(con, met_id: str) -> dict | None:
    """One job: its diplomas (by level), the access flag of each, and the Parcoursup formations preparing them."""
    if not MET_ID.match(met_id or "") or not ON._has(con, "onisep_metier"):
        return None
    job = con.execute("SELECT met_id, nom, niveau_acces_min, niveau_rang FROM core.onisep_metier WHERE met_id = ?", [met_id]).fetchone()
    if job is None:
        return None
    mid, nom, lvl, rank = job
    romes = [r for (r,) in con.execute("SELECT rome FROM core.onisep_metier_rome WHERE met_id = ? ORDER BY rome", [mid]).fetchall()] \
        if ON._has(con, "onisep_metier_rome") else []
    sheets = con.execute("""
        SELECT f.for_id, f.libelle, f.type, f.niveau_etudes FROM core.onisep_formation_metier fm
        JOIN core.onisep_formation f USING (for_id) WHERE fm.met_id = ? ORDER BY f.libelle""", [mid]).fetchall()
    fids = [s[0] for s in sheets]
    by_sheet = {}
    if fids:
        q = ", ".join("?" * len(fids))
        for fid, cod, fili, etab, ville, acad, filiere, comp, taux, capa, sel, form in con.execute(f"""
            SELECT l.for_id, l.cod_aff_form, l.fili, fy.g_ea_lib_vx, fy.ville_etab, fy.acad_mies, fy.fil_lib_voe_acc,
                   fy.lib_comp_voe_ins, fy.taux_acces_ens, fy.capa_fin, fy.select_form, fy.form_lib_voe_acc
            FROM core.onisep_link l JOIN core.formation_year fy ON fy.session = l.session AND fy.cod_aff_form = l.cod_aff_form
            WHERE l.for_id IN ({q})
            ORDER BY fy.acad_mies, fy.ville_etab, fy.g_ea_lib_vx, l.cod_aff_form""", fids).fetchall():
            by_sheet.setdefault(fid, {"fili": fili, "rows": []})["rows"].append(
                {"cod_aff_form": cod, "etablissement": etab, "ville": ville, "academie": acad, "filiere": filiere,
                 "complement": clean_complement({"lib_comp_voe_ins": comp, "g_ea_lib_vx": etab, "fili": fili,
                                                 "fil_lib_voe_acc": filiere, "form_lib_voe_acc": form}) or None,
                 "taux_acces_ens": taux, "capa_fin": capa, "selective": sel != "formation non sélective"})
    dips = []
    for fid, lib, typ, niv in sheets:
        p = by_sheet.get(fid)
        # the diploma level as the formation card reads it (ON.sheet_level), so both pages give the same flag
        level = ON.sheet_level([niv], p["fili"] if p else None)
        acces = None if rank is None or level is None else "direct" if rank <= level else "poursuite"
        dips.append({"id": fid, "libelle": lib, "type": typ, "niveau": niv, "niveau_rang": level, "acces": acces,
                     "url": ON.ONISEP_URL.format(kind="formation", id=fid), "parcoursup": p is not None,
                     "formations": p["rows"] if p else []})
    dips.sort(key=lambda d: (d["niveau_rang"] if d["niveau_rang"] is not None else 99, ORDER[d["acces"]], fold(d["libelle"])))
    n_form = len({f["cod_aff_form"] for d in dips for f in d["formations"]})
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"id": mid, "nom": nom, "niveau_acces_min": lvl, "niveau_rang": rank, "romes": romes, "session": latest,
            "url": ON.ONISEP_URL.format(kind="metier", id=mid),
            "status": "ok" if n_form else "hors_parcoursup" if dips else "sans_diplome",
            "n_formations": n_form, "diplomes": dips}
