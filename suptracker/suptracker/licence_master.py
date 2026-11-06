"""Sprint 16: from the licence to the master, side by side.

On a licence page, every master mention of the licence's university in the same B1 discipline (the sprint-7 link,
MonMaster latest session) gets one row:
  - MonMaster: programmes, vœux (applications summed over programmes) and admits (people), never a ratio of the two;
  - InserSup (sprint 8): the same university's master with the same title, latest national class, salaried employment
    rate at 18 months among the LEAVERS (pooled classes flagged); several parts that year = no figure;
  - Onisep: the national master sheet of the same title ("master mention X"), two explicit spelling rules only
    (STAPS written out, "(MEEF)" dropped); a mention without a sheet says "métiers non documentés";
  - the jobs of that sheet, read through sprints 13-15: the RANGE of the ILO task scores and of θ over every code of
    every job, and COUNTS of jobs per 2030 reading (fixed rule below). Never an average over the jobs, never a single
    score, never a chance of admission or of a job.

A job's 2030 class (fixed rule): every family with a reading says "débutants insuffisants" -> insuffisants; every one
says "débutants nombreux" -> nombreux; anything else (mixed, uncertain) -> incertain; no family read -> non lu.

Landmarks ("repères"), fixed rules, only when two RANGES do not overlap (the licence's own Onisep jobs vs the master's):
  - ia_plus_bas / ia_plus_haut: the master's whole ILO range is below / above the licence's;
  - complementarite_plus_haute / complementarite_plus_basse: same for θ.
Overlapping ranges say nothing.

Per-job axes are computed at build (core.metier_axes) from metiers.detail, so the page never recomputes them.
"""
from __future__ import annotations

import re
import unicodedata

from . import insertion as INS
from . import passerelles as PA
from . import success as SU

# explicit spelling rules between MonMaster mentions and Onisep titles (both already normalised by `key`)
REWRITES = ((r"^staps ", "sciences et techniques des activites physiques et sportives "), (r" meef ", " "))
CLASSES = ("insuffisants", "nombreux", "incertain", "non_lu")
REPERES = ("ia_plus_bas", "ia_plus_haut", "complementarite_plus_haute", "complementarite_plus_basse")


def key(s: str | None) -> str:
    """Accents removed, then every other non-alphanumeric character (curly apostrophe included) is a separator."""
    s = (s or "").replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def rewritten(k: str) -> str:
    k = f"{k} "
    for a, b in REWRITES:
        k = re.sub(a, b, k)
    return k.strip()


def job_class(lectures: list[str | None]) -> str:
    read = [x for x in lectures if x]
    if not read:
        return "non_lu"
    if all(x == "debutants_insuffisants" for x in read):
        return "insuffisants"
    if all(x == "debutants_nombreux" for x in read):
        return "nombreux"
    return "incertain"


# ------------------------------------------------------------------------- build
def build(con) -> dict:
    """core.master_onisep (MonMaster mention -> Onisep master sheet) and core.metier_axes (one row per job)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("CREATE OR REPLACE TABLE core.master_onisep (mention VARCHAR, for_id VARCHAR, regle VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.metier_axes (met_id VARCHAR, n_isco INTEGER, ilo_min DOUBLE, ilo_max DOUBLE,
        theta_min DOUBLE, theta_max DOUBLE, classe_2030 VARCHAR, n_familles_lues INTEGER)""")
    need = ("monmaster", "onisep_formation", "onisep_formation_metier", "onisep_metier")
    have = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    if not set(need) <= have:
        return {"mentions": 0, "metiers": 0}
    return {"mentions": build_link(con), "metiers": build_axes(con)}


def build_link(con) -> int:
    con.execute("DELETE FROM core.master_onisep")
    sheets = {}
    for fid, lib in con.execute("SELECT for_id, libelle FROM core.onisep_formation WHERE type = 'master' ORDER BY for_id").fetchall():
        m = re.match(r"master mention (.*)", lib or "")
        if m:
            sheets.setdefault(key(m.group(1)), fid)
    rows = []
    for (mention,) in con.execute("SELECT DISTINCT mention FROM core.monmaster WHERE mention IS NOT NULL ORDER BY 1").fetchall():
        k = key(mention)
        if k in sheets:
            rows.append((mention, sheets[k], "titre"))
        elif rewritten(k) in sheets:
            rows.append((mention, sheets[rewritten(k)], "orthographe"))
    if rows:
        con.executemany("INSERT INTO core.master_onisep VALUES (?, ?, ?)", rows)
    return len(rows)


def build_axes(con) -> int:
    from . import metiers as MT
    con.execute("DELETE FROM core.metier_axes")
    axes = []
    for (mid,) in con.execute("SELECT met_id FROM core.onisep_metier ORDER BY 1").fetchall():
        d = MT.detail(con, mid)
        ia = d.get("ia") or {}
        lect = [f.get("lecture") for f in (d.get("emploi2030") or []) if not f.get("absent")]
        axes.append((mid, len(ia.get("isco") or []), ia.get("min"), ia.get("max"), ia.get("theta_min"), ia.get("theta_max"),
                     job_class(lect), sum(1 for x in lect if x)))
    if axes:
        con.executemany("INSERT INTO core.metier_axes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", axes)
    return len(axes)


# ------------------------------------------------------------------------- serving
def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = ?",
                            [table]).fetchone()[0])


def jobs_of(con, for_id: str | None) -> dict | None:
    """The jobs of one Onisep sheet with their axes, and the ranges and counts over them (never an average)."""
    if not for_id:
        return None
    rows = con.execute("""SELECT fm.met_id, m.nom, a.ilo_min, a.ilo_max, a.theta_min, a.theta_max, a.classe_2030
                          FROM core.onisep_formation_metier fm JOIN core.onisep_metier m USING (met_id)
                          LEFT JOIN core.metier_axes a USING (met_id) WHERE fm.for_id = ? ORDER BY m.nom, fm.met_id""",
                       [for_id]).fetchall()
    jobs = [dict(zip(("id", "nom", "ilo_min", "ilo_max", "theta_min", "theta_max", "classe_2030"), r)) for r in rows]

    def span(lo, hi):
        a = [j[lo] for j in jobs if j[lo] is not None]
        b = [j[hi] for j in jobs if j[hi] is not None]
        return (min(a), max(b)) if a and b else (None, None)
    ilo, theta = span("ilo_min", "ilo_max"), span("theta_min", "theta_max")
    return {"for_id": for_id, "metiers": jobs, "n_metiers": len(jobs),
            "ilo_min": ilo[0], "ilo_max": ilo[1], "theta_min": theta[0], "theta_max": theta[1],
            "classes_2030": {c: sum(1 for j in jobs if (j["classe_2030"] or "non_lu") == c) for c in CLASSES}}


def reperes(lic: dict | None, mas: dict | None) -> list[str]:
    """Fixed rules, fired only when the two ranges are disjoint."""
    if not lic or not mas:
        return []
    out = []
    if None not in (lic["ilo_min"], lic["ilo_max"], mas["ilo_min"], mas["ilo_max"]):
        if mas["ilo_max"] < lic["ilo_min"]:
            out.append("ia_plus_bas")
        elif mas["ilo_min"] > lic["ilo_max"]:
            out.append("ia_plus_haut")
    if None not in (lic["theta_min"], lic["theta_max"], mas["theta_min"], mas["theta_max"]):
        if mas["theta_min"] > lic["theta_max"]:
            out.append("complementarite_plus_haute")
        elif mas["theta_max"] < lic["theta_min"]:
            out.append("complementarite_plus_basse")
    return out


def _insersup(con, pid: str, disc: str) -> tuple[dict, int | None]:
    """The university's masters in InserSup (latest national class), by normalised title; titles in parts excluded."""
    rows = INS._rows(con, "SELECT * FROM core.insersup WHERE id_paysage = ? AND type_diplome = 'Master LMD'", [pid])
    nat = INS._latest(INS._rows(con, "SELECT * FROM core.insersup WHERE id_paysage = 'all' AND type_diplome = 'Master LMD' AND diplome = 'all'", []))
    year = nat[0]["last_year"] if nat else None
    cur = INS._current(INS._latest([r for r in rows if r["diplome"] != "all" and r["discipline"] == disc]), year)
    by = {}
    for r in cur:
        by.setdefault(key(r["libelle"]), []).append(r)
    return {k: v[0] for k, v in by.items() if len(v) == 1}, year


def for_licence(con, cod: str, fili: str | None, contrat: str | None, paysage: dict | None = None) -> dict | None:
    if fili not in SU.LICENCE_FILI or not (_has(con, "monmaster") and _has(con, "master_onisep") and _has(con, "metier_axes")):
        return None
    link = con.execute("""SELECT etab, discipline, lien FROM core.licence_success_link WHERE cod_aff_form = ?
                          ORDER BY session DESC LIMIT 1""", [cod]).fetchone() if _has(con, "licence_success_link") else None
    etab, disc, lien = link if link else (None, None, None)
    out = {"status": "ok", "etab": etab, "etab_label": SU.UNIVERSITY_LABEL.get(etab, etab) if etab else None,
           "discipline": disc, "discipline_label": SU.DISCIPLINES[disc][1] if disc else None, "lien": lien, "mentions": []}
    pid = (SU.SIES_PAYSAGE if paysage is None else paysage).get(etab) if etab else None
    if contrat != "Public" or pid is None or disc is None:
        out.update(status="non_rattachee", reason="pas de rattachement certain à une université et une discipline")
        return out
    s = PA.latest_session(con)
    out["session"] = int(s)
    lic_for = con.execute("""SELECT for_id FROM core.onisep_link WHERE cod_aff_form = ? AND for_id IS NOT NULL
                             ORDER BY session DESC LIMIT 1""", [cod]).fetchone() if _has(con, "onisep_link") else None
    out["licence"] = jobs_of(con, lic_for[0]) if lic_for else None
    sheet = dict((m, (f, r)) for m, f, r in con.execute("SELECT mention, for_id, regle FROM core.master_onisep").fetchall())
    ins, year = _insersup(con, pid, disc) if _has(con, "insersup") else ({}, None)
    out["annee_insertion"] = year
    for mention, n_off, n_can, n_acc in con.execute(
            """SELECT mention, count(*), sum(n_can), sum(n_accept) FROM core.monmaster WHERE session = ? AND id_paysage = ?
               AND discipline = ? GROUP BY mention ORDER BY sum(n_accept) DESC NULLS LAST, mention""", [s, pid, disc]).fetchall():
        f, regle = sheet.get(mention, (None, None))
        jobs = jobs_of(con, f)
        r = ins.get(key(mention))
        h = INS.SERVED_HORIZON
        out["mentions"].append({
            "mention": mention, "n_offres": n_off, "n_can": n_can, "n_accept": n_acc,
            "onisep": {"for_id": f, "regle": regle} if f else None, "metiers": jobs,
            "insertion": None if r is None else {
                "sortants": r[f"nb_sortants_{h}"], "taux_emploi": r[f"tx_sortants_en_emploi_sal_fr_{h}"],
                "taux_stable": r[f"tx_sortants_en_emploi_stable_{h}"], "promo": r["promo"], "regroupe": bool(r["pooled"])},
            "reperes": reperes(out["licence"], jobs)})
    if not out["mentions"]:
        out.update(status="aucun_master", reason="MonMaster ne publie pas de master de cette discipline pour cette université")
    return out
