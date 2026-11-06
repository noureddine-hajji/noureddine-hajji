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

Human complementarity θ (sprint 15, second part), IMF method (Pizzinelli et al. 2023, WP/23/216) rebuilt from O*NET 31.0
per the owner's guide: 11 Work Context elements on the CX scale (1-5 -> 0-100, Degree of Automation reversed), 5 dimension
means plus the Job Zone (20 x zone), θ = mean of the 6 dimensions / 100. O*NET 31.0 merged zones 1 and 2 (code 2), so this
is an ADAPTED estimate ("theta_onet31_adapte"), never the IMF 2023 score; the outdoor element is the guide's proxy
4.C.2.a.1.c; an occupation with a suppressed (Recommend Suppress = Y) or missing element gets no θ. θ reaches ISCO-08 only
through official tables: O*NET-SOC 2019 -> SOC 2018 (O*NET), SOC 2018 -> SOC 2010 (BLS), SOC 2010 -> ISCO-08 (BLS); an
ISCO code shows the RANGE of θ over its US occupations and their count, never an average. C-AIOE is not computed: the
Felten AIOE appendix is centred-reduced (negative values), which the IMF correction cannot take as it is.

A technical potential of the TASKS, not a forecast of job losses nor a personal risk.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config

ILO_GLOB = "Final_Scores_ISCO08_Gmyrek*.xlsx"
TAGS_GLOB = "*fiches-rome*tag*.xlsx"
WC_GLOB, JZ_GLOB = "work_context.csv", "job_zones.csv"
ONET_SOC_GLOB, SOC_1018_GLOB, SOC_ISCO_GLOB = "2019_to_SOC_Crosswalk.xlsx", "soc_2010_to_2018_crosswalk.xlsx", "ISCO_SOC_Crosswalk.xls"
# the IMF's 11 Work Context elements by dimension (owner's guide, section 4); "AU" (Degree of Automation) is reversed
THETA_ELEMENTS = {"communication": ("4.C.1.a.2.l", "4.C.1.a.2.c"), "responsabilite": ("4.C.1.c.2", "4.C.1.c.1"),
                  "physique": ("4.C.2.a.1.c", "4.C.2.a.3"), "criticite": ("4.C.3.a.1", "4.C.3.a.4", "4.C.3.a.2.b"),
                  "non_routine": ("4.C.3.b.2", "4.C.3.b.8")}
REVERSED = "4.C.3.b.2"
GRADIENTS = {"Not Exposed": 0, "Minimal Exposure": 1, "Exposed: Gradient 1": 2, "Exposed: Gradient 2": 3,
             "Exposed: Gradient 3": 4, "Exposed: Gradient 4": 5}


def _one(glob: str, data_dir: Path | None = None) -> Path | None:
    files = sorted((data_dir or config.DATA_DIR / "sources").glob(glob))
    return files[-1] if files else None


def sources(data_dir: Path | None = None) -> dict:
    globs = (("ilo", ILO_GLOB), ("tags", TAGS_GLOB), ("wc", WC_GLOB), ("jz", JZ_GLOB), ("onet_soc", ONET_SOC_GLOB),
             ("soc_1018", SOC_1018_GLOB), ("soc_isco", SOC_ISCO_GLOB))
    return {k: p for k, p in ((k, _one(g, data_dir)) for k, g in globs) if p}


THETA_KEYS = ("wc", "jz", "onet_soc", "soc_1018", "soc_isco")


def read_theta(wc_path: Path, jz_path: Path):
    """θ per O*NET-SOC 2019 occupation: the 5 Work Context dimensions and the skills dimension, all 0-100."""
    import pandas as pd
    wanted = [e for els in THETA_ELEMENTS.values() for e in els]
    wc = pd.read_csv(wc_path, dtype=str, usecols=["O*NET-SOC Code", "Title", "Element ID", "Scale ID", "Data Value",
                                                    "Recommend Suppress", "Not Relevant"])
    wc = wc[wc["Element ID"].isin(wanted) & (wc["Scale ID"] == "CX")]
    bad = wc[(wc["Recommend Suppress"] == "Y") | (wc["Not Relevant"] == "Y")]["O*NET-SOC Code"].unique()
    x = 25 * (pd.to_numeric(wc["Data Value"]) - 1)                        # CX 1-5 -> 0-100
    x = x.where(wc["Element ID"] != REVERSED, 100 - x)                     # the automation already there counts against
    piv = wc.assign(x=x).pivot_table(index="O*NET-SOC Code", columns="Element ID", values="x", aggfunc="first")
    out = pd.DataFrame(index=piv.index)
    for dim, els in THETA_ELEMENTS.items():
        out[dim] = piv.reindex(columns=list(els)).mean(axis=1, skipna=False)
    jz = pd.read_csv(jz_path, dtype=str).set_index("O*NET-SOC Code")
    out["job_zone"] = pd.to_numeric(jz["Job Zone"]).reindex(out.index)
    out["competences"] = 20 * out["job_zone"]
    dims = list(THETA_ELEMENTS) + ["competences"]
    out["theta"] = out[dims].mean(axis=1, skipna=False) / 100
    out["titre"] = wc.groupby("O*NET-SOC Code")["Title"].first().reindex(out.index)
    out = out[~out.index.isin(bad)].dropna(subset=["theta"])
    return out.reset_index().rename(columns={"O*NET-SOC Code": "onet"})[["onet", "titre", *dims, "job_zone", "theta"]]


def read_chain(onet_soc: Path, soc_1018: Path, soc_isco: Path):
    """O*NET-SOC 2019 -> SOC 2018 -> SOC 2010 -> ISCO-08, official tables only, every many-to-many link kept."""
    import openpyxl
    import pandas as pd
    import xlrd

    def rows(path, skip, cols):
        ws = openpyxl.load_workbook(str(path), read_only=True, data_only=True).worksheets[0]
        return [tuple(str(r[i]).strip() for i in cols) for r in list(ws.iter_rows(values_only=True))[skip:] if all(r[i] for i in cols)]
    a = pd.DataFrame(rows(onet_soc, 4, (0, 2)), columns=["onet", "soc2018"])
    b = pd.DataFrame(rows(soc_1018, 9, (2, 0)), columns=["soc2018", "soc2010"])
    sh = xlrd.open_workbook(str(soc_isco)).sheet_by_name("2010 SOC to ISCO-08")
    c = pd.DataFrame([(str(v[0]).strip(), str(v[3]).strip()) for v in (sh.row_values(i) for i in range(7, sh.nrows)) if v[0] and v[3]],
                     columns=["soc2010", "isco"])
    c = c[c["isco"].str.fullmatch(r"\d{4}")]
    return a.merge(b, on="soc2018").merge(c, on="soc2010").drop_duplicates()


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
    con.execute("""CREATE OR REPLACE TABLE core.ia_theta_onet (onet VARCHAR, titre VARCHAR, communication DOUBLE, responsabilite DOUBLE,
        physique DOUBLE, criticite DOUBLE, non_routine DOUBLE, competences DOUBLE, job_zone INTEGER, theta DOUBLE)""")
    con.execute("CREATE OR REPLACE TABLE core.ia_theta_lien (onet VARCHAR, soc2018 VARCHAR, soc2010 VARCHAR, isco VARCHAR)")
    s = sources() if srcs is None else srcs
    out = {}
    if all(k in s for k in THETA_KEYS):
        th = read_theta(Path(s["wc"]), Path(s["jz"]))
        ch = read_chain(*(Path(s[k]) for k in ("onet_soc", "soc_1018", "soc_isco")))
        ch = ch[ch["onet"].isin(th["onet"])][["onet", "soc2018", "soc2010", "isco"]]
        for table, frame in (("core.ia_theta_onet", th), ("core.ia_theta_lien", ch)):
            con.register("_ia", frame)
            con.execute(f"INSERT INTO {table} SELECT * FROM _ia")
            con.unregister("_ia")
        out["theta"], out["liens"] = len(th), len(ch)
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
    theta = {}
    if isco and _has(con, "ia_theta_lien"):
        q = ", ".join("?" * len(isco))
        for code, lo, hi, n in con.execute(f"""SELECT l.isco, min(t.theta), max(t.theta), count(DISTINCT t.onet)
                FROM (SELECT DISTINCT isco, onet FROM core.ia_theta_lien) l JOIN core.ia_theta_onet t USING (onet)
                WHERE l.isco IN ({q}) GROUP BY l.isco""", list(isco)).fetchall():
            theta[code] = (lo, hi, n)
    out = []
    for code, e in isco.items():
        r, th = rows.get(code), theta.get(code)
        out.append({"code": code, "libelle": e["libelle_fr"], "n_intitules": e["n_intitules"], "origine": sorted(e["origine"]),
                    "score": r[1] if r else None, "ecart_type": r[2] if r else None, "gradient": r[3] if r else None,
                    "rang": r[4] if r else None, "n_taches": r[5] if r else None,
                    "theta_min": th[0] if th else None, "theta_max": th[1] if th else None, "n_onet": th[2] if th else 0})
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
    lows = [x["theta_min"] for x in out if x["theta_min"] is not None]
    highs = [x["theta_max"] for x in out if x["theta_max"] is not None]
    return {"isco": out, "min": min(scores) if scores else None, "max": max(scores) if scores else None,
            "sans_score": [x["code"] for x in out if x["score"] is None], "tags": tags,
            "theta_min": min(lows) if lows else None, "theta_max": max(highs) if highs else None,
            "sans_theta": [x["code"] for x in out if x["theta_min"] is None]}
