"""Sprint 14: employment in a job's families to 2030 (Dares / France Stratégie, "Les métiers en 2030", 2022).

What the workbook publishes, checked on the real file (Annexe 4, tableaux de synthèse A and B):
* per FAP-2009 family at the 87 level (79 families listed): employment in 2019, then over 2019-2030 net job
  creations [1], end-of-career departures [2], positions to fill [1+2], young entrants [3], and the potential
  imbalance [1+2-3] in the reference scenario and in 4 variants (pre-crisis, Covid+, low-carbon, Covid+ low-carbon);
  table B is table A divided by 2019 employment (both identities hold on every row: red team E1);
* six families are only published inside their domain: D0Z + D3Z (domain D) and F0Z..F3Z (domain F). Their group
  is the domain minus its published families, a CALCULATED figure (flagged) that adds up on every column; K0Z
  (craftsmen) is mixed with elected officials and clergy in "Autres": no figure.

How it reaches a job: the job's ROME codes (sprint 13) -> FAP-2009 families -> their 87-group. When the family
depends on the qualification of the post, every family is shown; none is picked. Nothing beyond 2030: no official
projection per job exists for 2035, so none is invented. A projection under stated assumptions, never a forecast,
a promise or a chance.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config

SOURCE_GLOB = "Les métiers en 2030*.xlsx"
SHEET_A = "Annexe 4 -Tableau de synthèse A"
SHEET_B = "Annexe 4 -Tableau de synthèse B"
FAP87 = re.compile(r"^[A-Z]\d[A-Z]$")
# columns of tables A and B after the code, label and dominant qualification
COLS = ("emploi_2019", "creations", "departs", "postes", "debutants", "deseq_ref", "deseq_precrise", "deseq_covid",
        "deseq_bas_carbone", "deseq_covid_bas_carbone", "mobilites")
SCENARIOS = {"deseq_ref": "Référence", "deseq_precrise": "Pré-crise", "deseq_covid": "Covid+",
             "deseq_bas_carbone": "Bas-carbone", "deseq_covid_bas_carbone": "Covid+ et bas-carbone"}
# families the workbook only publishes inside their domain: published together, calculated (domain minus the rest)
GROUPS = {"D": ("D0Z", "D3Z"), "F": ("F0Z", "F1Z", "F2Z", "F3Z")}
ABSENT = {"K0Z": "le classeur range les artisans avec les élus et les religieux (« Autres ») : pas de chiffre propre"}


def source_path(data_dir: Path | None = None) -> Path | None:
    files = sorted((data_dir or config.DATA_DIR / "sources").glob(SOURCE_GLOB))
    return files[-1] if files else None


def _num(x):
    return float(x) if isinstance(x, (int, float)) else None


def read_workbook(path: Path) -> list[dict]:
    """One row per published family and per calculated group, values in thousands as published (table A), shares
    of 2019 employment from table B (published), computed for the calculated groups."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    a = [r for r in wb[SHEET_A].iter_rows(values_only=True)]
    b = {str(r[1]).strip(): r for r in wb[SHEET_B].iter_rows(values_only=True) if r[1] and FAP87.match(str(r[1]).strip())}
    out, domain, members = [], None, {}
    for r in a:
        lab = str(r[1]).strip() if r[1] else ""
        if lab.startswith("Ensemble du domaine"):
            domain = lab.split("domaine", 1)[1].strip()[:1]
            members[domain] = {"row": r, "families": []}
        elif lab.startswith("Autres") or lab == "Ensemble":
            domain = None
        elif FAP87.match(lab):
            vals = [_num(x) for x in r[4:15]]
            shares = [_num(x) for x in b[lab][5:15]] if lab in b else [None] * 10
            out.append({"fap87": lab, "libelle": str(r[2]).strip(), "qualification": str(r[3] or "").strip() or None,
                        **dict(zip(COLS, vals)), **{f"part_{c}": s for c, s in zip(COLS[1:], shares)},
                        "calcule": False, "membres": lab})
            if domain:
                members[domain]["families"].append(vals)
    for dom, codes in GROUPS.items():
        if dom not in members:
            continue
        d = [_num(x) for x in members[dom]["row"][4:15]]
        rest = [round(d[i] - sum(f[i] for f in members[dom]["families"]), 9) if d[i] is not None else None for i in range(len(COLS))]
        emp = rest[0]
        out.append({"fap87": "+".join(codes), "libelle": f"familles regroupées du domaine {dom}",
                    "qualification": None, **dict(zip(COLS, rest)),
                    **{f"part_{c}": (rest[i + 1] / emp if emp and rest[i + 1] is not None else None) for i, c in enumerate(COLS[1:])},
                    "calcule": True, "membres": ",".join(codes)})
    return out


def build(con, path: Path | None = None) -> dict:
    """core.m2030_famille; without the workbook the table exists and stays empty."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    cols = ", ".join(f"{c} DOUBLE" for c in COLS) + ", " + ", ".join(f"part_{c} DOUBLE" for c in COLS[1:])
    con.execute(f"""CREATE OR REPLACE TABLE core.m2030_famille (fap87 VARCHAR, libelle VARCHAR, qualification VARCHAR, {cols},
        calcule BOOLEAN, membres VARCHAR)""")
    if path is None or not Path(path).exists():
        return {"familles": 0}
    rows = read_workbook(Path(path))
    names = ["fap87", "libelle", "qualification", *COLS, *[f"part_{c}" for c in COLS[1:]], "calcule", "membres"]
    import pandas as pd
    con.register("_m2030", pd.DataFrame([[r[n] for n in names] for r in rows], columns=names))
    con.execute("INSERT INTO core.m2030_famille SELECT * FROM _m2030")
    con.unregister("_m2030")
    return {"familles": len(rows), "calculees": sum(r["calcule"] for r in rows)}


# ------------------------------------------------------------------------- serving
def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                               AND table_name = 'm2030_famille'""").fetchone()[0])


def reading(lo, hi) -> str | None:
    """Fixed rule on the scenario range of the imbalance (positions to fill minus young entrants)."""
    if lo is None or hi is None:
        return None
    if lo > 0:
        return "debutants_insuffisants"
    if hi < 0:
        return "debutants_nombreux"
    return "incertain"


def for_codes(con, codes: list[dict]) -> list[dict]:
    """The job's families with their 2019-2030 figures. `codes` is sprint 13's answer (one entry per ROME code)."""
    if not codes or not _has(con):
        return []
    rows = {r[0]: r for r in con.execute("SELECT * FROM core.m2030_famille").fetchall()}
    names = [d[0] for d in con.execute("SELECT * FROM core.m2030_famille LIMIT 0").description]
    group_of = {m: r[0] for r in rows.values() if r[names.index("calcule")] for m in r[names.index("membres")].split(",")}
    fams = {}
    for c in codes:
        for f in c.get("fap2009", []):
            key = group_of.get(f["fap87"], f["fap87"])
            e = fams.setdefault(key, {"fap87": key, "rome": [], "origine": set(), "q": set(), "familles_2009": []})
            if c["rome"] not in e["rome"]:
                e["rome"].append(c["rome"])
            e["origine"].add(c.get("origine", "onisep"))
            e["q"] |= set(f["qualifications"]["codes"])
            e["familles_2009"].append({"code": f["code"], "libelle": f.get("libelle")})
    out = []
    for key, e in sorted(fams.items()):
        base = {"fap87": key, "rome": e["rome"], "origine": sorted(e["origine"]),
                "toutes_qualifications": len(e["q"]) == 10, "familles_2009": e["familles_2009"]}
        if key in ABSENT or key not in rows:
            out.append({**base, "absent": True, "raison": ABSENT.get(key, "famille absente du classeur")})
            continue
        r = dict(zip(names, rows[key]))
        if r["calcule"]:
            labs = dict(con.execute("SELECT code, libelle FROM core.nomen_fap2009 WHERE code IN (SELECT unnest(?))", [r["membres"].split(",")]).fetchall()) \
                if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'nomen_fap2009'").fetchone()[0] else {}
            r["libelle"] = " ; ".join(labs.get(m, m) for m in r["membres"].split(","))
        scen = {SCENARIOS[c]: r[c] for c in SCENARIOS}
        vals = [v for v in scen.values() if v is not None]
        lo, hi = (min(vals), max(vals)) if vals else (None, None)
        out.append({**base, "absent": False, "libelle": r["libelle"], "qualification_dominante": r["qualification"],
                    "calcule": bool(r["calcule"]), "membres": r["membres"].split(","),
                    "milliers": {c: r[c] for c in COLS}, "parts": {c: r[f"part_{c}"] for c in COLS[1:]},
                    "desequilibre": {"reference": r["deseq_ref"], "min": lo, "max": hi, "scenarios": scen},
                    "lecture": reading(lo, hi)})
    return out
