"""Sprint 15 (first part): how exposed a job's tasks are to generative AI, ILO 2025, plus France Travail's tag.

ILO, Gmyrek, Berg et al. (2025), "Generative AI and Jobs: A Refined Global Index of Occupational Exposure", Working
Paper 140 (CC BY 4.0), file `Final_Scores_ISCO08_Gmyrek_et_al_2025.xlsx` committed by the owner: 3,265 ISCO-08 tasks
of 427 unit groups, each scored 0-1 (share of the task generative AI could perform), and per group the PUBLISHED mean
(`mean_score_2025`, rounded to 2 decimals), standard deviation and exposure gradient (`potential25`: not exposed,
minimal exposure, exposed gradient 1 to 4). The published values are served as they are; the red team re-derives
the means from the tasks (one upstream inconsistency: 7126, flagged there).

How it reaches a job: the job's ISCO-08 codes (sprint 13, through job titles) -> the ILO unit groups. A job usually
has several codes: each is shown with its gradient and the count of job titles behind it; the page gives the RANGE
of the published means, never an average, never a composite with anything else (sprint 14's figures stay apart).

France Travail's ROME 4.0 tag "Transition numérique" (Oui / Non / not assessed) is shown per ROME sheet as a fact.

The human-complementarity axis (θ, IMF method rebuilt from O*NET) needs an official O*NET-SOC 2019 -> SOC 2010
crosswalk to reach ISCO-08: not in data/sources yet, so it is not served.

A technical potential of the TASKS, not a forecast of job losses nor a personal risk.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config

ILO_GLOB = "Final_Scores_ISCO08_Gmyrek*.xlsx"
TAGS_GLOB = "*fiches-rome*tag*.xlsx"
GRADIENTS = {"Not Exposed": 0, "Minimal Exposure": 1, "Exposed: Gradient 1": 2, "Exposed: Gradient 2": 3,
             "Exposed: Gradient 3": 4, "Exposed: Gradient 4": 5}


def _one(glob: str, data_dir: Path | None = None) -> Path | None:
    files = sorted((data_dir or config.DATA_DIR / "sources").glob(glob))
    return files[-1] if files else None


def sources(data_dir: Path | None = None) -> dict:
    return {k: p for k, p in (("ilo", _one(ILO_GLOB, data_dir)), ("tags", _one(TAGS_GLOB, data_dir))) if p}


def read_ilo(path: Path):
    """One row per ISCO-08 unit group: published mean, sd and gradient, task count, mean re-computed from the tasks."""
    import pandas as pd
    d = pd.read_excel(path, dtype={"ISCO_08": str})
    d["isco"] = d["ISCO_08"].str.strip().str.zfill(4)
    for c in ("score_2025", "mean_score_2025", "SD_2025"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    g = d.groupby("isco").agg(intitule=("Title", "first"), moyenne=("mean_score_2025", "first"), ecart_type=("SD_2025", "first"),
                              gradient=("potential25", "first"), n_taches=("score_2025", "count"),
                              moyenne_taches=("score_2025", "mean")).reset_index()
    g["rang"] = g["gradient"].map(GRADIENTS)
    return g[["isco", "intitule", "moyenne", "ecart_type", "gradient", "rang", "n_taches", "moyenne_taches"]]


def read_tags(path: Path):
    import pandas as pd
    t = pd.read_excel(path, sheet_name="Tag des fiches ROME", dtype=str)
    t = t[t["Code ROME"].fillna("").str.fullmatch(r"[A-N]\d{4}")]
    v = t["Transition Numérique"].fillna("").str.strip()
    return pd.DataFrame({"rome": t["Code ROME"], "transition_numerique": v.where(v.isin(["Oui", "Non"]), None)})


def build(con, srcs: dict | None = None) -> dict:
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.ia_oit_isco (isco VARCHAR, intitule VARCHAR, moyenne DOUBLE, ecart_type DOUBLE,
        gradient VARCHAR, rang INTEGER, n_taches INTEGER, moyenne_taches DOUBLE)""")
    con.execute("CREATE OR REPLACE TABLE core.ia_rome_tag (rome VARCHAR, transition_numerique VARCHAR)")
    s = sources() if srcs is None else srcs
    out = {}
    for key, table, reader in (("ilo", "core.ia_oit_isco", read_ilo), ("tags", "core.ia_rome_tag", read_tags)):
        if key in s:
            frame = reader(Path(s[key]))
            con.register("_ia", frame)
            con.execute(f"INSERT INTO {table} SELECT * FROM _ia")
            con.unregister("_ia")
            out[key] = len(frame)
    return out


# ------------------------------------------------------------------------- serving
def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = ?",
                            [table]).fetchone()[0])


def for_codes(con, codes: list[dict]) -> dict | None:
    """The job's ISCO codes with the ILO exposure of their tasks, and the ROME sheets' digital-transition tag."""
    if not codes or not _has(con, "ia_oit_isco"):
        return None
    isco = {}
    for c in codes:
        for i in c.get("isco", []):
            if i["precision"] != 4:
                continue
            e = isco.setdefault(i["code"], {"code": i["code"], "libelle_fr": i.get("libelle"), "n_intitules": 0,
                                            "origine": set()})
            e["n_intitules"] = max(e["n_intitules"], i["n_intitules"])
            e["origine"].add(c.get("origine", "onisep"))
    rows = {}
    if isco:
        q = ", ".join("?" * len(isco))
        for r in con.execute(f"SELECT isco, moyenne, ecart_type, gradient, rang, n_taches FROM core.ia_oit_isco WHERE isco IN ({q})",
                             list(isco)).fetchall():
            rows[r[0]] = r
    out = []
    for code, e in isco.items():
        r = rows.get(code)
        out.append({"code": code, "libelle": e["libelle_fr"], "n_intitules": e["n_intitules"], "origine": sorted(e["origine"]),
                    "score": r[1] if r else None, "ecart_type": r[2] if r else None, "gradient": r[3] if r else None,
                    "rang": r[4] if r else None, "n_taches": r[5] if r else None})
    out.sort(key=lambda x: (x["score"] is None, -x["n_intitules"], -(x["score"] or 0), x["code"]))   # main codes first
    scores = [x["score"] for x in out if x["score"] is not None]
    tags = []
    if _has(con, "ia_rome_tag"):
        romes = [c["rome"] for c in codes if c.get("connu")]
        if romes:
            q = ", ".join("?" * len(romes))
            got = dict(con.execute(f"SELECT rome, transition_numerique FROM core.ia_rome_tag WHERE rome IN ({q})", romes).fetchall())
            tags = [{"rome": r, "transition_numerique": got.get(r)} for r in romes]
    if not out and not tags:
        return None
    return {"isco": out, "min": min(scores) if scores else None, "max": max(scores) if scores else None,
            "sans_score": [x["code"] for x in out if x["score"] is None], "tags": tags}
