"""Red team, robustesse 2035 per job (owner's PRD, 2026-11-16): an ESTIMATION of the model on each job page.

  RB1 Cedefop: an INDEPENDENT reading of the zip (own code) gives, per ISCO 2-digit group, the French positions to fill 2024-2035
      with the owner's break rule (EU-27 growth when the 2020-2021 jump > 25 % or the gap with the EU-27 growth > 30 points;
      replacement always French); the module's reading equals it on a fixture zip and on the real one.
  RB2 Anthropic Economic Index: augmentation share = augmentation / (augmentation + automation) of the O*NET occupations linked
      to the ISCO code, else the mean of their SOC major groups, flagged; re-derived independently (fixture and real zip).
  RB3 per job: an independent implementation of the PRD formulas (weighted exposure and augmentation, IA, fixed bounds, demand
      0.5/0.3/0.2, R = (0.35 IA + 0.25 Dem) / 0.6, three scenarios, median, min, max, badge > 15, confidence = the lowest of four
      components, levels, « données insuffisantes » below 0.4 or without the three scenarios) equals the module on crafted jobs.
  RB4 PRD invariants: exposure is not replacement (same exposure, more augmentation = a better IA score); S1 never above S2 on
      IA; fixed bounds (a job's normalised terms do not depend on the others); reachability never enters (the module reads no
      Parcoursup admission field); missing terms lower the coverage, never a typed fallback value.
  RB5 page (node): robustesseCard / robustesseTile escape every stored string, say « estimation », the median and the range,
      the confidence and its four components, the sources and the model version; « données insuffisantes » with no number;
      vouvoiement, no alarming word, never a chance or a promise.
  RB6 plumbing: build (beside the warehouse), API, the job page (tile + card first in « Avenir du métier »), source register
      (Cedefop and AEI en ligne), README, CLAUDE.md, tests and durations.
  RB7 real (--real): the stored tables equal the independent readings, 80 jobs re-derived from metiers.detail, coverage printed;
      stability of the order of the scored jobs when the two weights move by 10 points (Spearman, measured, printed).
  RB8 mutation test.
  RB9 OECD (owner, 2026-11-17): an independent reading of the workbook (Data and « +1 cognitive » Scenario sheets, reversed
      normalised gap 1 - total / 23), averaged over the O*NET occupations linked to each ISCO code; RANKS (ties averaged, 0-1)
      among the codes with both the OIT and the OECD measure; the job's rank gap lowers the agreement beyond 15 points (floor 0.5,
      never hides a score alone); S1's exposure x the OECD scenario ratio, else x 1.25; the OECD never enters the exposure.
  RB11 repère (owner, 2026-11-17): the scores form a tight bell, so the page leads with the job's place among the SCORED jobs
      (top / bottom 20 % of the medians, cut points re-derived independently) and three plain facts; the score is only in
      « Détail du calcul »; no repère without a score.
  RB10 ESCO (owner, 2026-11-17): the green-skill share per ISCO-08 4-digit group is re-derived as the mean of ESCO's own
      occupation rows (fixture and real zip; the occupations' shares re-counted from their skills are printed as a diagnostic);
      per job the title-weighted mean, beside the national median; a CONTROL only: score, scenarios and confidence are the same
      with or without it; the card says it does not enter the score.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str):
    m = types.ModuleType(name)
    m.__file__, m.__package__ = str(path), "suptracker"
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {"rob": (ROOT / "suptracker" / "robustesse.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def R(self):
        import suptracker  # noqa: F401
        return load(ROOT / "suptracker" / "robustesse.py", "suptracker.robustesse_rt", self.src["rob"])


# ------------------------------------------------------------------------------------------------------------- fixtures
YEARS = list(range(2015, 2036))


def series(start, g2021=0.0, slope=0.0):
    """Employment by year: flat, a jump in 2021, then a linear trend."""
    out, v = {}, start
    for y in YEARS:
        if y == 2021:
            v = v * (1 + g2021)
        elif y > 2021:
            v = v * (1 + slope)
        out[y] = round(v)
    return out


FIX_EMP = {  # (country, isco2) -> series
    ("France", "21"): series(1000, 0.05, 0.02), ("EU27", "21"): series(20000, 0.02, 0.015),     # no break: French growth
    ("France", "13"): series(900, -0.35, 0.06), ("EU27", "13"): series(15000, -0.05, 0.02),     # 2021 jump: EU growth
    ("France", "12"): series(600, -0.09, -0.06), ("EU27", "12"): series(12000, 0.03, -0.005),   # gap > 30 points: EU growth
    ("France", "Total"): series(10000), ("EU27", "Total"): series(200000),
}
FIX_REP = {("France", k): {y: 30 for y in YEARS} for k in ("21", "13", "12", "Total")}


def fixture_cedefop(path: Path):
    import openpyxl

    def book(rows):
        wb = openpyxl.Workbook()
        wb.active.title = "Info_sheet"
        ws = wb.create_sheet("Data")
        ws.append(["Country", "Occupation", "isco_2d_code", *YEARS])
        for (c, k), v in rows.items():
            ws.append([c, f"occ {k}", int(k) if k.isdigit() else k, *[v[y] for y in YEARS]])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Employment_occupation_detail.xlsx", book(FIX_EMP))
        z.writestr("Replacement_demand_occupation_detail.xlsx", book(FIX_REP))


FIX_AEI = [  # geo, category, level, month, metric, value, node id
    ("GLOBAL", "soc_occupation", "0", "2026-05-01", "collaboration_bucket_augmentation_pct", "30", "15-1252.00"),   # buckets do
    ("GLOBAL", "soc_occupation", "0", "2026-05-01", "collaboration_bucket_automation_pct", "20", "15-1252.00"),     # not sum to 100
    ("GLOBAL", "soc_occupation", "0", "2026-05-01", "collaboration_bucket_augmentation_pct", "10", "15-1253.00"),
    ("GLOBAL", "soc_occupation", "0", "2026-05-01", "collaboration_bucket_automation_pct", "40", "15-1253.00"),
    ("GLOBAL", "soc_occupation", "1", "2026-05-01", "collaboration_bucket_augmentation_pct", "45", "43"),
    ("GLOBAL", "soc_occupation", "1", "2026-05-01", "collaboration_bucket_automation_pct", "55", "43"),
    ("FRA", "soc_occupation", "0", "2026-05-01", "collaboration_bucket_augmentation_pct", "99", "43-9061.00"),   # not global
    ("GLOBAL", "soc_occupation", "0", "2026-04-01", "collaboration_bucket_augmentation_pct", "99", "43-9061.00"),  # April
]
FIX_LINKS = [("15-1252.00", "2512"), ("15-1253.00", "2512"), ("43-9061.00", "4110"), ("99-9999.00", "9999")]


def fixture_aei(path: Path):
    head = "date_start,date_end,geo_id,geo_level,category_name,hierarchy_level,metric_id,value,node_name,node_external_id\n"
    body = "".join(f"{m},x,{g},global,{c},{lv},{k},{v},n,{node}\n" for g, c, lv, m, k, v, node in FIX_AEI)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("aei_claude_ai_2026-06-26.csv", head + body)


# ------------------------------------------------------------------------------------------------------------ oracles
def oracle_cedefop(path: Path) -> dict:
    import openpyxl
    with zipfile.ZipFile(path) as z:
        def rows(name):
            ws = openpyxl.load_workbook(io.BytesIO(z.read(name)), read_only=True)["Data"]
            it = list(ws.iter_rows(values_only=True))
            years = it[0][3:]
            return {(r[0], str(r[2])): dict(zip(years, r[3:])) for r in it[1:]}
        e, r = rows("Employment_occupation_detail.xlsx"), rows("Replacement_demand_occupation_detail.xlsx")
    out = {}
    for (country, k), v in e.items():
        if country != "France" or not k.isdigit() or not v[2023]:
            continue
        fr = v[2035] / v[2023] - 1
        eu_s = e[("EU27", k)]
        eu = eu_s[2035] / eu_s[2023] - 1
        jumped = abs(v[2021] / v[2020] - 1) > 0.25
        g = eu if (jumped or abs(fr - eu) > 0.30) else fr
        rep = sum(r[("France", k)][y] for y in range(2024, 2036)) / v[2023]
        out[k] = (g + rep, "UE27" if g is eu and (jumped or abs(fr - eu) > 0.30) else "France")
    return out


def oracle_aug(aei_rows: list, links: list) -> dict:
    vals = {}
    for g, c, lv, m, k, v, node in aei_rows:
        if g == "GLOBAL" and c == "soc_occupation" and m == "2026-05-01":
            vals.setdefault(node, {})[k] = float(v)
    share = {n: d["collaboration_bucket_augmentation_pct"] / (d["collaboration_bucket_augmentation_pct"]
             + d["collaboration_bucket_automation_pct"]) for n, d in vals.items()
             if "collaboration_bucket_augmentation_pct" in d and "collaboration_bucket_automation_pct" in d}
    by = {}
    for onet, isco in links:
        by.setdefault(isco, []).append(onet)
    out = {}
    for isco, onets in by.items():
        det = [share[o] for o in onets if o in share]
        if det:
            out[isco] = (sum(det) / len(det), "detail")
        else:
            maj = [share[m] for m in {o[:2] for o in onets} if m in share]
            if maj:
                out[isco] = (sum(maj) / len(maj), "grand_groupe")
    return out


def oracle_job(d: dict, aug: dict, ced: dict, oecd: dict | None = None) -> dict:
    """The PRD's formulas, written again (with the owner's OECD rules, 2026-11-17)."""
    oecd = oecd or {}
    codes = [c for c in ((d.get("ia") or {}).get("isco") or []) if re.fullmatch(r"\d{4}", c.get("code") or "")]
    W = sum(c.get("n_intitules") or 1 for c in codes)
    def mean(pairs):
        s = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / s if s else None
    exp = mean([(c["score"], (c.get("n_intitules") or 1) / W) for c in codes if c.get("score") is not None])
    au = mean([(aug[c["code"]][0], (c.get("n_intitules") or 1) / W) for c in codes if c["code"] in aug])
    cr = mean([(ced[c["code"][:2]], (c.get("n_intitules") or 1) / W) for c in codes if c["code"][:2] in ced])
    ratio = mean([(oecd[c["code"]]["ratio"], (c.get("n_intitules") or 1) / W) for c in codes
                  if c["code"] in oecd and oecd[c["code"]].get("ratio") is not None])
    rk = [(oecd[c["code"]], (c.get("n_intitules") or 1) / W) for c in codes if oecd.get(c["code"], {}).get("rang_oit") is not None]
    gap = abs(mean([(o["rang_oit"], w) for o, w in rk]) - mean([(o["rang_oecd"], w) for o, w in rk])) if rk else None
    clip = lambda x, lo, hi: None if x is None else min(100, max(0, (x - lo) / (hi - lo) * 100))  # noqa: E731
    fam = [f["milliers"] for f in (d.get("emploi2030") or []) if not f.get("absent") and (f.get("milliers") or {}).get("emploi_2019")]
    m = statistics.fmean([x["postes"] / x["emploi_2019"] for x in fam]) if fam else None
    m3 = statistics.fmean([(x["postes"] + x["deseq_bas_carbone"] - x["deseq_ref"]) / x["emploi_2019"] for x in fam]) if fam else None
    bf = [f for f in ((d.get("bmo") or {}).get("familles") or []) if not f.get("absent") and f.get("projets")]
    t = sum(f["part_difficile"] * f["projets"] for f in bf) / sum(f["projets"] for f in bf) if bf else None
    C, M, M3, T = clip(cr, -0.1, 0.9), clip(m, 0, 0.6), clip(m3, 0, 0.6), clip(t, 0, 1)
    def dem(mm):
        p = [(v, w) for v, w in ((C, 0.5), (mm, 0.3), (T, 0.2)) if v is not None]
        return mean(p) if p else None
    def ia(e, a):
        return 100 * (1 - e * (1 - a))
    sc = {}
    if exp is not None and au is not None and dem(M) is not None:
        sc = {"S1": (0.35 * ia(min(1, exp * (1.25 if ratio is None else ratio)), au * 0.8) + 0.25 * dem(M)) / 0.6,
              "S2": (0.35 * ia(exp, au) + 0.25 * dem(M)) / 0.6,
              "S3": (0.35 * ia(exp, au) + 0.25 * dem(M3)) / 0.6}
    acc = 1 - abs(C - M) / 50 if C is not None and M is not None else 0.5
    acc = max(0.0, acc)
    if gap is not None:
        acc = min(acc, 1.0 if gap <= 0.15 else max(0.5, 1 - (gap - 0.15)))
    return {"exp": exp, "aug": au, "scen": {k: round(v, 1) for k, v in sc.items()}, "C": C, "M": M, "T": T,
            "accord": acc, "gap": gap}


def fixture_oecd(path: Path, rows: list):
    """rows = (O*NET code, baseline total gap, scenario total gap or None): the workbook's layout (3 heading rows + a units row)."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "README"
    for name, i in (("Data", 1), ("Scenario", 2)):
        ws = wb.create_sheet(name)
        ws.append(["OCCUPATION IDENTIFIERS", None, "AI CAPABILITY GAP INDEX", None])
        ws.append(["Occupation Code (O*NET-SOC Code)", "Occupation Title", "AI Capability Gap Index (Reversed, norm.)", "Total"])
        ws.append(["OCC_Code", "OCC_Title", "AI Capability Gap Index_Rev. norm.", "AI Capability Gap Index_Total"])
        ws.append(["—", "—", "Numeric 0-1 (higher = more exposed)", "Numeric >0"])
        for r in rows:
            if r[i] is not None:
                ws.append([r[0], "t", 1 - r[i] / 23, r[i]])
        ws.append(["Note: a footer line", None, None, None])
    wb.save(path)


def oracle_oecd(path: Path, links: list, ilo: dict) -> dict:
    """Own reading: the total gap column -> 1 - total / 23 (the codebook's definition), mean per ISCO code, ranks with ties."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def read(name):
        out = {}
        for r in wb[name].iter_rows(values_only=True):
            if r and isinstance(r[0], str) and re.fullmatch(r"\d\d-\d{4}\.\d\d", r[0]) and isinstance(r[3], (int, float)):
                out[r[0]] = 1 - r[3] / 23
        return out
    base, scen = read("Data"), read("Scenario")
    by = {}
    for onet, isco in links:
        by.setdefault(isco, set()).add(onet)
    out = {}
    for isco, onets in by.items():
        b = [base[o] for o in onets if o in base]
        if not b:
            continue
        sc = [scen[o] for o in onets if o in base and o in scen]
        o = {"oecd": sum(b) / len(b), "ratio": None}
        if len(sc) == len(b) and o["oecd"] > 0:
            o["ratio"] = (sum(sc) / len(sc)) / o["oecd"]
        out[isco] = o
    both = [k for k in out if k in ilo]

    def rank(vals):
        r = {}
        for k in both:
            below = sum(1 for j in both if vals[j] < vals[k])
            equal = sum(1 for j in both if vals[j] == vals[k])
            r[k] = (below + (equal - 1) / 2) / (len(both) - 1) if len(both) > 1 else 0.5
        return r
    ri, ro = rank(ilo), rank({k: out[k]["oecd"] for k in both})
    for k in both:
        out[k]["rang_oit"], out[k]["rang_oecd"] = ri[k], ro[k]
    return out


# --------------------------------------------------------------------------------------------------------------- checks
@check("RB1 Cedefop: an independent reading with the owner's 2021-break rule equals the module (fixture and real zip)")
def rb1(c: Ctx):
    R = c.R()
    tmp = Path(tempfile.mkdtemp())
    try:
        fixture_cedefop(tmp / "c.zip")
        got = R.read_cedefop(tmp / "c.zip")
        exp = oracle_cedefop(tmp / "c.zip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [k for k in exp if k not in got or abs(got[k]["postes"] - exp[k][0]) > 1e-9 or got[k]["source_croissance"] != exp[k][1]]
    if {k: v[1] for k, v in exp.items()} != {"21": "France", "13": "UE27", "12": "UE27"}:
        bad.append(f"fixture rule {exp}")
    if "Total" in got:
        bad.append("the Total row is a group")
    real = ROOT / "data" / "sources" / R.CEDEFOP_ZIP
    n_eu = None
    if c.real and real.exists():
        g2, e2 = R.read_cedefop(real), oracle_cedefop(real)
        bad += [f"real {k}" for k in e2 if k not in g2 or abs(g2[k]["postes"] - e2[k][0]) > 1e-9 or g2[k]["source_croissance"] != e2[k][1]]
        n_eu = sum(1 for v in e2.values() if v[1] == "UE27")
    return not bad, f"differences {bad[:4]}; real groups with the EU-27 growth: {n_eu}"


@check("RB2 AEI: augmentation / (augmentation + automation), linked O*NET occupations, else SOC major groups (flagged)")
def rb2(c: Ctx):
    R = c.R()
    import duckdb
    tmp = Path(tempfile.mkdtemp())
    try:
        fixture_aei(tmp / "a.zip")
        aei = R.read_aei(tmp / "a.zip")
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core")
        con.execute("CREATE TABLE core.ia_theta_lien (onet VARCHAR, soc2018 VARCHAR, soc2010 VARCHAR, isco VARCHAR)")
        con.executemany("INSERT INTO core.ia_theta_lien VALUES (?, '', '', ?)", FIX_LINKS)
        got = R.isco_aug(con, aei)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    exp = oracle_aug(FIX_AEI, FIX_LINKS)
    bad = [k for k in set(exp) | set(got) if k not in got or k not in exp or abs(got[k][0] - exp[k][0]) > 1e-9 or got[k][2] != exp[k][1]]
    if not (abs(got["2512"][0] - 0.4) < 1e-9 and got["4110"][2] == "grand_groupe" and "9999" not in got):
        bad.append(f"fixture values {got}")
    return not bad, f"differences {bad[:4]}"


def crafted():
    """Crafted jobs: weights, missing parts, BMO and Métiers 2030 families, a low-carbon variant."""
    fam = lambda e, p, ref, low: {"absent": False, "milliers": {"emploi_2019": e, "postes": p, "deseq_ref": ref, "deseq_bas_carbone": low}}  # noqa: E731
    bmo = lambda *rows: {"familles": [{"absent": False, "projets": p, "part_difficile": d} for p, d in rows]}  # noqa: E731
    return {
        "full": {"ia": {"isco": [{"code": "2512", "n_intitules": 3, "score": 0.6, "origine": ["onisep"]},
                                 {"code": "1330", "n_intitules": 1, "score": 0.4, "origine": ["nom"]}]},
                 "emploi2030": [fam(100, 40, -5, -2), fam(50, 10, 1, 1)], "bmo": bmo((1000, 0.5), (500, 0.2))},
        "no_aug": {"ia": {"isco": [{"code": "9999", "n_intitules": 2, "score": 0.3, "origine": ["onisep"]}]},
                   "emploi2030": [fam(100, 30, 0, 0)], "bmo": bmo((100, 0.4))},
        "no_demand": {"ia": {"isco": [{"code": "2512", "n_intitules": 1, "score": 0.5, "origine": ["onisep"]}]},
                      "emploi2030": [], "bmo": None},
        # the two demand sources disagree completely: confidence 0, no score
        "disagree": {"ia": {"isco": [{"code": "2512", "n_intitules": 1, "score": 0.5, "origine": ["onisep"]}]},
                     "emploi2030": [fam(100, 0, 0, 0)], "bmo": None},
        # a strong AI scenario and a strong low-carbon effect: the scenarios spread by more than 15 points
        "spread": {"ia": {"isco": [{"code": "3333", "n_intitules": 1, "score": 0.8, "origine": ["onisep"]}]},
                   "emploi2030": [fam(100, 10, 0, 50)], "bmo": None},
        "partial_demand": {"ia": {"isco": [{"code": "2512", "n_intitules": 1, "score": 0.5, "origine": ["onisep"]}]},
                           "emploi2030": [{"absent": True}], "bmo": bmo((10, 0.9))},
    }


AUG = {"2512": (0.4, 2, "detail"), "1330": (0.7, 0, "grand_groupe"), "3333": (0.5, 1, "detail")}
CED = {"25": {"postes": 0.5, "source_croissance": "France"}, "13": {"postes": 0.2, "source_croissance": "UE27"},
       "33": {"postes": 0.3, "source_croissance": "France"},
       "99": {"postes": 0.1, "source_croissance": "France"}}
OECD = {"2512": {"oecd": 0.6, "oecd_s1": 0.72, "ratio": 1.2, "rang_oit": 0.9, "rang_oecd": 0.3},
        "1330": {"oecd": 0.5, "oecd_s1": None, "ratio": None, "rang_oit": 0.4, "rang_oecd": 0.45},
        "3333": {"oecd": 0.7, "oecd_s1": 0.7, "ratio": 1.0, "rang_oit": 0.5, "rang_oecd": 0.55},
        "9999": {"oecd": 0.2, "oecd_s1": 0.3, "ratio": 1.5}}                       # no OIT score: no rank


@check("RB3 per job: an independent implementation of the PRD formulas equals the module on crafted jobs")
def rb3(c: Ctx):
    R = c.R()
    bad = []
    for (name, d), oe in [(x, o) for x in crafted().items() for o in (None, OECD)]:
        got = R.job(d, AUG, CED, oe)
        exp = oracle_job(d, AUG, {k: v["postes"] for k, v in CED.items()}, oe)
        name = f"{name}{' +OCDE' if oe else ''}"
        if abs(got["confiance"]["accord_sources"] - round(exp["accord"], 3)) > 1e-9:
            bad.append(f"{name}: agreement {got['confiance']['accord_sources']} != {exp['accord']:.3f}")
        if exp["scen"]:
            vals = list(exp["scen"].values())
            if got["scenarios"] is None and got["confiance"]["valeur"] >= 0.4:
                bad.append(f"{name}: no score with a confidence of {got['confiance']['valeur']}")
            if got["scenarios"] is not None:
                if got["scenarios"] != exp["scen"]:
                    bad.append(f"{name}: scenarios {got['scenarios']} != {exp['scen']}")
                s = got["score"]
                if (s["median"], s["min"], s["max"]) != (statistics.median(vals), min(vals), max(vals)) \
                        or s["dependance_scenario"] != (max(vals) - min(vals) > 15):
                    bad.append(f"{name}: score {s}")
        elif got["score"] is not None:
            bad.append(f"{name}: a score without the three scenarios")
        k = got["confiance"]
        comps = [k["fraicheur"], k["donnees_observees"], k["accord_sources"], k["couverture"]]
        if abs(k["valeur"] - min(comps)) > 1e-9 or k["niveau"] != ("faible" if min(comps) < 0.4 else "haute" if min(comps) >= 0.7 else "moyenne"):
            bad.append(f"{name}: confidence {k}")
        if got["score"] is not None and k["valeur"] < 0.4:
            bad.append(f"{name}: a score shown under 0.4")
    if R.job(crafted()["disagree"], AUG, CED)["score"] is not None:
        bad.append("a score shown although the demand sources disagree completely (confidence 0)")
    sp = R.job(crafted()["spread"], AUG, CED)["score"]
    if not sp or not sp["dependance_scenario"]:
        bad.append(f"the spread job is not « dépend du scénario »: {sp}")
    full = R.job(crafted()["full"], AUG, CED)
    if full["isco"][1]["lien"] != "nom" or abs(full["confiance"]["donnees_observees"] - (0.75 * 1 + 0.25 * 0.5 * 0.75)) > 1e-3:
        bad.append(f"observed links {full['confiance']['donnees_observees']}")
    if R.job(crafted()["no_demand"], AUG, {})["score"] is not None:
        bad.append("a job without any demand term has a score")
    far = R.job(crafted()["spread"], AUG, CED, {"3333": {"oecd": 0.1, "ratio": 1.0, "rang_oit": 1.0, "rang_ocde": 0.0, "rang_oecd": 0.0}})
    if far["score"] is None or far["confiance"]["accord_sources"] < 0.5 - 1e-9:
        bad.append(f"a rank disagreement alone hides the score: {far['confiance']}")
    if R.job(crafted()["full"], AUG, CED, OECD)["composantes"] != R.job(crafted()["full"], AUG, CED)["composantes"]:
        bad.append("the OECD measure enters the exposure or a component of the score")
    near = R.job(crafted()["full"], AUG, CED, {"2512": dict(OECD["2512"], rang_oecd=0.8), "1330": OECD["1330"]})
    if near["confiance"]["accord_sources"] != R.job(crafted()["full"], AUG, CED)["confiance"]["accord_sources"]:
        bad.append("a rank gap of at most 15 points lowers the agreement")
    return not bad, f"differences {bad[:4]}"


@check("RB4 PRD invariants: exposure is not replacement, S1 <= S2 on IA, fixed bounds, no reachability, no typed fallback")
def rb4(c: Ctx):
    R = c.R()
    bad = []
    for e in (0.3, 0.5, 0.8, 1.0):
        if not R.ia_score(e, 0.8) > R.ia_score(e, 0.2):
            bad.append(f"exposure {e}: more augmentation is not better")
        for a in (0.0, 0.4, 0.9):
            if R.ia_score(e, a, "S1") > R.ia_score(e, a, "S2") + 1e-9:
                bad.append(f"S1 above S2 at {e}, {a}")
    for key, (lo, hi) in R.BOUNDS.items():
        if R.norm(lo, key) != 0 or R.norm(hi, key) != 100 or R.norm(hi * 10 + 1, key) != 100:
            bad.append(f"bounds {key}")
    a = R.job(crafted()["full"], AUG, CED)
    ced2 = dict(CED, **{"77": {"postes": 50.0, "source_croissance": "France"}})            # an extreme other group
    b = R.job(crafted()["full"], AUG, ced2)
    if a["composantes"] != b["composantes"]:
        bad.append("a job's terms depend on another group (min-max scaling)")
    if re.search(r"formation_year|taux_acces|acc_tot|nb_voe|capa_fin", c.src["rob"]):
        bad.append("the module reads a Parcoursup admission field (reachability must stay apart)")
    pd_ = R.job(crafted()["partial_demand"], AUG, CED)
    if pd_["confiance"]["couverture"] >= 1 or pd_["composantes"]["m2030"] is not None:
        bad.append("a missing term is filled instead of lowering the coverage")
    for e, a_, want in ((0.2, 0.9, "peu_expose"), (0.5, 0.7, "surtout_augmente"), (0.5, 0.2, "surtout_substituable"), (0.5, 0.5, "mixte")):
        if R.regime(e, a_) != want:
            bad.append(f"regime {e} {a_}")
    return not bad, f"differences {bad[:4]}"


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("(") == part.count(")") and part.rstrip().endswith(";"):
                return part
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    import subprocess
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


STUB = """const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt2 = (x) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const estimTag = (d) => `<span class="estim">estimation</span> ${d || ""}`;
"""


@check("RB5 page: escaped, estimation, median and range, confidence with its components, sources and version, no alarm word")
def rb5(c: Ctx):
    names = ("ROB_REGIME", "ROB_SCEN", "ROB_CONF", "robNum", "ROB_REPERE", "robFaits", "robustesseTile", "robustesseCard")
    if not all(top(c.js, n) for n in names):
        return False, "a renderer is missing from app.js"
    R = c.R()
    full = R.job(crafted()["full"], AUG, CED, {"2512": dict(OECD["2512"]), "1330": dict(OECD["2512"])}, {"2512": 0.25, "1330": 0.0})
    full = json.loads(json.dumps(full))
    full["isco"][0]["libelle"] = HOSTILE
    full["model_version"] = HOSTILE
    full["sources_detail"] = [{"id": "oit", "libelle": "OIT " + HOSTILE, "annee": 2025}]
    full["repere"] = {"niveau": "haut", "seuil_bas": 67.2, "seuil_haut": 73.3, "part": 0.2, "n_metiers": 876}
    none = R.job(crafted()["no_demand"], AUG, {})
    prog = STUB + "\n".join(top(c.js, n) for n in names) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([robustesseCard(D.f), robustesseTile(D.f), robustesseCard(D.n), robustesseTile(D.n), robustesseCard(null), robustesseTile(null)]));"""
    out = node(prog, {"f": full, "n": none})
    if out is None:
        return True, "node absent: not run"
    cf, tf, cn, tn, c0, t0 = out
    bad = []
    for i, h in enumerate((cf, tf, cn, tn)):
        txt = re.sub(r"<[^>]+>", " ", h)
        if "<img" in h:
            bad.append(f"output {i}: unescaped")
        if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt, re.I):
            bad.append(f"output {i}: tutoiement")
        if re.search(r"(?i)condamn|menac|danger|disparaî|chance|garanti|probabilit|feu rouge", txt):
            bad.append(f"output {i}: an alarming word, a chance or a promise")
    s, k = full["score"], full["composantes"]
    half = lambda x: int(x + 0.5)  # noqa: E731  (toLocaleString rounds half away from zero)
    lead, _, detail = cf.partition("<summary>Détail du calcul</summary>")
    # owner, 2026-11-17: the repère and three plain facts lead; the score is only in « Détail du calcul »
    if "Parmi les 20 % de métiers les plus robustes" not in lead or '<span class="estim">' not in lead:
        bad.append("the repère does not lead the card as an estimation")
    if re.search(r"sur 100|/ 100|Score", lead):
        bad.append("the score is shown before « Détail du calcul »")
    for fact in (f"environ {half(k['cedefop_taux'] * 100)} postes à pourvoir pour 100 emplois actuels",
                 f"dans {half(k['augmentation'] * 10)} usages sur 10", f"{half(k['tension'] / 10)} recrutements sur 10"):
        if fact not in lead:
            bad.append(f"fact missing or wrong: « {fact} »")
    if f"<strong>{round(s['median'])}</strong> sur 100" not in detail or f"<strong>{round(s['min'])}</strong>" not in detail \
            or f"<strong>{round(s['max'])}</strong>" not in detail:
        bad.append("the score and its range are not in « Détail du calcul »")
    if "73 ou plus" not in detail or "67 ou moins" not in detail or "876 métiers" not in detail:
        bad.append("the repère's cut points are not said")
    if "Parmi les 20 % de métiers les plus robustes" not in tf or re.search(r"/ 100|\d+ sur 100", tf):
        bad.append("the summary tile shows the score instead of the repère")
    if "Selon l'OIT, ce métier est plus exposé à l'IA que 90 % des métiers mesurés. Selon l'OCDE, plus exposé que 30 %" not in cf:
        bad.append("the OIT / OECD ranks are not shown side by side")
    if "selon ESCO (Commission européenne), 18,8 % des compétences de ce métier sont « vertes » (médiane de tous les métiers : 12,5 %). Ce chiffre n'entre pas dans le score." not in cf:
        bad.append("the ESCO control is not shown, or not said to stay out of the score")
    if "ESCO" in cn:
        bad.append("an ESCO line without a share")
    if "Selon l'OCDE" in cn:
        bad.append("an OECD line without ranks")
    for w in ("fraîcheur", "liens observés", "accord des sources", "couverture", "D'où vient ce chiffre", "Version du modèle", "OIT &lt;img",
              "« +1 niveau cognitif » de l'OCDE"):
        if w not in cf:
            bad.append(f"card lacks « {w} »")
    if "Données insuffisantes" not in cn or re.search(r"/ 100|sur 100|Parmi les|Dans la moyenne|Score :", cn.partition("<summary>Détail du calcul</summary>")[0]) \
            or re.search(r"Score :|Repère :", cn) or "données insuffisantes" not in tn:
        bad.append("insufficient data still shows a number")
    if c0 or t0:
        bad.append("output without data")
    return not bad, f"differences {bad[:4]}"


@check("RB6 plumbing: build beside the warehouse, API, job page tile and card, sources, README, CLAUDE.md, tests and durations")
def rb6(c: Ctx):
    bad = []
    if "robustesse.build(con, textes=rapports.textes_path(db_path), details=details)" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build")
    if 'd["robustesse"] = ROB.for_metier(' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("API")
    if "${robustesseTile(d.robustesse)}" not in c.js or '["avenir", "Avenir du métier", `${robustesseCard(d.robustesse)}' not in c.js:
        bad.append("job page")
    from suptracker import sources as SRC
    st = {s["key"]: s["status"] for s in SRC.SOURCES if "robustesse_2035" in s.get("feeds", ()) and s["status"] == "en_ligne"}
    if st != {"cedefop_skills_forecast_2026": "en_ligne", "anthropic_aei": "en_ligne", "oecd_ai_exposure_2026": "en_ligne",
              "esco_v121_fr": "en_ligne"}:
        bad.append(f"sources {st}")
    if "## Robustesse 2035" not in (ROOT / "README.md").read_text():
        bad.append("README")
    if "Robustesse 2035" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    if "tests/test_robustesse.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()) \
            or not (ROOT / "tests" / "test_robustesse.py").exists():
        bad.append("tests / durations")
    return not bad, f"missing {bad}"


def spearman(a: list, b: list) -> float:
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 1.0


@check("RB7 real: stored tables = independent readings, 80 jobs re-derived, coverage, order stability at ±10 weight points")
def rb7(c: Ctx):
    if not c.real or c.db is None:
        return True, "skipped (no --real)"
    R = c.R()
    import duckdb
    from suptracker import metiers as MT
    con = duckdb.connect(str(c.db), read_only=True)
    src, p = R._src(con)
    if src is None:
        return False, "no r35 tables: rebuild the warehouse"
    if p == "core.":
        return False, "the robustesse tables are in the warehouse, not beside it (95 MB budget)"
    bad = []
    ced = {r[0]: r for r in src.execute("SELECT isco2, postes, source_croissance FROM r35_cedefop").fetchall()}
    exp = oracle_cedefop(ROOT / "data" / "sources" / R.CEDEFOP_ZIP)
    bad += [f"cedefop {k}" for k in exp if k not in ced or abs(ced[k][1] - exp[k][0]) > 1e-9 or ced[k][2] != exp[k][1]]
    rows = src.execute("SELECT isco, augmentation, n_onet, niveau, ocde, ratio_s1, rang_oit, rang_ocde FROM r35_isco").fetchall()
    aug = {r[0]: (r[1], r[2], r[3]) for r in rows if r[1] is not None}
    oecd = {r[0]: {"oecd": r[4], "ratio": r[5], "rang_oit": r[6], "rang_oecd": r[7]} for r in rows if r[4] is not None}
    xl = ROOT / "data" / "sources" / R.OECD_XLSX
    if xl.exists():
        links = con.execute("SELECT DISTINCT onet, isco FROM core.ia_theta_lien").fetchall()
        ilo = dict(con.execute("SELECT isco, moyenne FROM core.ia_oit_isco WHERE moyenne IS NOT NULL").fetchall())
        eo = oracle_oecd(xl, links, ilo)
        for k in set(eo) | set(oecd):
            a, b = eo.get(k), oecd.get(k)
            if not a or not b or abs(a["oecd"] - b["oecd"]) > 1e-6 or (a["ratio"] is None) != (b["ratio"] is None) \
                    or (a["ratio"] is not None and abs(a["ratio"] - b["ratio"]) > 1e-6) \
                    or (a.get("rang_oit") is None) != (b["rang_oit"] is None) \
                    or (b["rang_oit"] is not None and max(abs(a["rang_oit"] - b["rang_oit"]), abs(a["rang_oecd"] - b["rang_oecd"])) > 1e-9):
                bad.append(f"ocde {k}")
    else:
        bad.append("the OECD workbook is missing")
    stored = {m: json.loads(d) for m, d in src.execute("SELECT met_id, data FROM r35_metier").fetchall()}
    rng = random.Random(7)
    for mid in rng.sample(sorted(stored), min(80, len(stored))):
        d = MT.detail(con, mid)
        o = oracle_job(d, aug, {k: v[1] for k, v in ced.items()}, oecd)
        s = stored[mid]
        if s["scenarios"] is not None and s["scenarios"] != o["scen"]:
            bad.append(f"{mid}: {s['scenarios']} != {o['scen']}")
        if abs(s["confiance"]["accord_sources"] - round(o["accord"], 3)) > 1e-9:
            bad.append(f"{mid}: agreement {s['confiance']['accord_sources']} != {o['accord']:.3f}")
    scored = [s for s in stored.values() if s["score"]]
    # stability: the PRD weights (35 / 25) moved by 10 points each way, order of the scored jobs (Spearman)
    base, plus, minus = [], [], []
    for s in scored:
        k = s["composantes"]
        base.append((0.35 * k["ia"] + 0.25 * k["demande"]) / 0.6)
        plus.append((0.45 * k["ia"] + 0.15 * k["demande"]) / 0.6)
        minus.append((0.25 * k["ia"] + 0.35 * k["demande"]) / 0.6)
    rho = (round(spearman(base, plus), 3), round(spearman(base, minus), 3)) if base else None
    esco_jobs = sum(1 for s in stored.values() if (s.get("esco") or {}).get("part_verte") is not None)
    if not esco_jobs:
        bad.append("no job carries the ESCO control: rebuild the warehouse")
    gaps = [s["ocde"]["ecart_rang"] for s in stored.values() if (s.get("ocde") or {}).get("ecart_rang") is not None]
    lv = {x: sum(1 for s in stored.values() if s["confiance"]["niveau"] == x) for x in ("haute", "moyenne", "faible")}
    return not bad, (f"{len(scored)}/{len(stored)} jobs scored; {sum(1 for v in ced.values() if v[2] == 'UE27')} groups with the "
                     f"EU-27 growth; Spearman at ±10 points: {rho}; OIT/OECD rank gap > 15 points for {sum(g > 0.15 for g in gaps)}"
                     f"/{len(gaps)} jobs; ESCO green share for {esco_jobs} jobs; confidence {lv}; differences {bad[:3]}")


SOURCE_MUTANTS = [
    ("rob", "break threshold loosened", "BREAK_JUMP, BREAK_GAP = 0.25, 0.30", "BREAK_JUMP, BREAK_GAP = 0.25, 3.0", "RB1"),
    ("rob", "French growth kept for a broken group", "growth = g_eu if use_eu else g_fr", "growth = g_fr", "RB1"),
    ("rob", "replacement from the EU", 'replacement = sum((rep.get(("France", code))', 'replacement = sum((rep.get(("EU27", code))', "RB1"),
    ("rob", "other month read", 'AEI_MONTH = "2026-05-01"', 'AEI_MONTH = "2026-04-01"', "RB2"),
    ("rob", "augmentation over all usage", "out[soc] = a / (a + b)", "out[soc] = a / 100", "RB2"),
    ("rob", "no major-group fallback", '            out[isco] = (statistics.fmean(majors), 0, "grand_groupe")', "            pass", "RB2"),
    ("rob", "exposure x augmentation", "return 100.0 * (1.0 - exp * (1.0 - aug))", "return 100.0 * (1.0 - exp * aug)", "RB4"),
    ("rob", "S1 softer", "exp, aug = min(1.0, exp * (ratio if ratio is not None else S1_EXP)), aug * S1_AUG", "exp, aug = exp, aug", "RB3"),
    ("rob", "demand weights swapped", "W_CED, W_M2030, W_BMO = 0.5, 0.3, 0.2", "W_CED, W_M2030, W_BMO = 0.3, 0.5, 0.2", "RB3"),
    ("rob", "other fixed bounds", '"ced": (-0.10, 0.90)', '"ced": (-0.10, 1.90)', "RB3"),
    ("rob", "median replaced by the worst case", '"median": statistics.median(vals)', '"median": min(vals)', "RB3"),
    ("rob", "confidence = mean", "conf = min(comps.values())", "conf = statistics.fmean(comps.values())", "RB3"),
    ("rob", "score shown at low confidence", "shown = len(vals) == 3 and conf >= CONF_LOW", "shown = len(vals) == 3", "RB3"),
    ("rob", "name links counted as observed", "observed += w * (1.0 if onisep else 0.5)", "observed += w * (1.0 if True else 0.5)", "RB3"),
    ("rob", "badge threshold", "max(vals) - min(vals) > BADGE_SPREAD", "max(vals) - min(vals) > 50", "RB3"),
    ("rob", "S1 ignores the OECD scenario", "exp * (ratio if ratio is not None else S1_EXP)", "exp * S1_EXP", "RB3"),
    ("rob", "rank gap threshold", "RANK_GAP, RANK_FLOOR = 0.15, 0.5", "RANK_GAP, RANK_FLOOR = 0.30, 0.5", "RB3"),
    ("rob", "no floor: a rank gap hides scores", "RANK_GAP, RANK_FLOOR = 0.15, 0.5", "RANK_GAP, RANK_FLOOR = 0.15, 0.0", "RB3"),
    ("rob", "rank gap ignored", "accord = min(accord_dem, accord_ia) if accord_ia is not None else accord_dem", "accord = accord_dem", "RB3"),
    ("rob", "OECD exposure mixed into the exposure", "        if c.get(\"score\") is not None:\n            exp_p.append((c[\"score\"], w))",
     "        if c.get(\"score\") is not None:\n            exp_p.append(((c[\"score\"] + oe[\"oecd\"]) / 2 if oe else c[\"score\"], w))", "RB3"),
    ("rob", "OECD column misread", 'head.index("AI Capability Gap Index_Rev. norm.")', 'head.index("AI Capability Gap Index_Total")', "RB9"),
    ("rob", "baseline read from the scenario sheet", 'now, scen = sheet("Data"), sheet("Scenario")', 'now, scen = sheet("Scenario"), sheet("Scenario")', "RB9"),
    ("rob", "ties not averaged", "while j + 1 < n and values[order[j + 1]] == values[order[i]]:", "while False:", "RB9"),
    ("rob", "ranks over every OECD code", "both = sorted(k for k in out if k in ilo)", "both = sorted(k for k in out if k in ilo or True)", "RB9"),
    ("rob", "partial scenario averaged", "s1 = statistics.fmean(sc) if len(sc) == len(vals) else None", "s1 = statistics.fmean(sc) if sc else None", "RB9"),
    ("js", "no OECD comparison", "${conf}${ocde}${esco}</details>", "${conf}${esco}</details>", "RB5"),
    ("rob", "repère tails of 10 %", "REPERE_SHARE = 0.20", "REPERE_SHARE = 0.10", "RB11"),
    ("rob", "repère levels swapped", 'return "haut" if median >= hi else "bas" if median <= lo else "moyen"',
     'return "bas" if median >= hi else "haut" if median <= lo else "moyen"', "RB11"),
    ("rob", "repère given without a score", '        if d["score"] and cuts:', '        if cuts:', "RB11"),
    ("js", "score leads the card", "${head}${phrase}<details class=\"more-card\"><summary>Détail du calcul</summary>${score}",
     "${score}${head}${phrase}<details class=\"more-card\"><summary>Détail du calcul</summary>", "RB5"),
    ("js", "fact on the wrong scale", "${robNum(c.tension / 10)} recrutements sur 10", "${robNum(c.tension)} recrutements sur 10", "RB5"),
    ("js", "tile shows the score", '`<span class="text">${esc(ROB_REPERE[q.niveau] || "")}</span>`', '`${robNum(r.score.median)} / 100`', "RB5"),
    ("js", "no ESCO control", "${conf}${ocde}${esco}</details>", "${conf}${ocde}</details>", "RB5"),
    ("rob", "ESCO rows of every level read", 'r.get("conceptType") == "ISCO level 4" and len(r.get("code") or "") == 4 and r["code"].isdigit()',
     "True", "RB10"),
    ("rob", "ESCO enters the confidence", "accord = min(accord_dem, accord_ia) if accord_ia is not None else accord_dem",
     "accord = min(accord_dem, accord_ia) if accord_ia is not None else accord_dem\n    accord = min(accord, vert if vert is not None else 1)", "RB10"),
    ("rob", "ESCO share not weighted", "            esco_p.append((esco[code], w))", "            esco_p.append((esco[code], 1.0))", "RB10"),
    ("js", "label unescaped", '<li>${esc(x.libelle)}</li>', '<li>${x.libelle}</li>', "RB5"),
    ("js", "no estimation label", '${estimTag("place du métier parmi ceux que le modèle peut estimer")}', "", "RB5"),
    ("js", "no confidence detail", "fraîcheur des sources ${fmt2(k.fraicheur)}", "${fmt2(k.fraicheur)}", "RB5"),
    ("js", "number with insufficient data", '`<p class="muted">Données insuffisantes pour une estimation sûre : nous préférons ne pas situer ce métier.</p>`',
     '`<p>Dans la moyenne des métiers</p>`', "RB5"),
]


FIX_OECD = [("15-1252.00", 4.6, 2.3), ("15-1253.00", 9.2, 6.9), ("43-9061.00", 11.5, None), ("11-1011.00", 4.6, 4.6),
            ("29-1141.00", 13.8, 9.2), ("99-9999.00", 0.0, 0.0),
            ("43-9071.00", 6.9, 4.6)]                                  # 4110: one of its two occupations has no scenario
FIX_OECD_LINKS = FIX_LINKS + [("11-1011.00", "1120"), ("29-1141.00", "2221"), ("43-9061.00", "4110"), ("43-9071.00", "4110")]
FIX_ILO = {"2512": 0.6, "4110": 0.6, "1120": 0.2, "2221": 0.3}          # 9999: no OIT score, no rank


@check("RB9 OECD: own reading of the workbook, mean per ISCO code, ranks with ties, scenario ratio, never in the exposure")
def rb9(c: Ctx):
    R = c.R()
    import duckdb
    tmp = Path(tempfile.mkdtemp())
    try:
        fixture_oecd(tmp / "o.xlsx", FIX_OECD)
        raw = R.read_oecd(tmp / "o.xlsx")
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core")
        con.execute("CREATE TABLE core.ia_theta_lien (onet VARCHAR, soc2018 VARCHAR, soc2010 VARCHAR, isco VARCHAR)")
        con.executemany("INSERT INTO core.ia_theta_lien VALUES (?, '', '', ?)", sorted(set(FIX_OECD_LINKS)))
        con.execute("CREATE TABLE core.ia_oit_isco (isco VARCHAR, moyenne DOUBLE)")
        con.executemany("INSERT INTO core.ia_oit_isco VALUES (?, ?)", list(FIX_ILO.items()) + [("9999", None)])
        got = R.isco_oecd(con, raw)
        exp = oracle_oecd(tmp / "o.xlsx", sorted(set(FIX_OECD_LINKS)), FIX_ILO)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = []
    for k in set(exp) | set(got):
        a, b = exp.get(k), got.get(k)
        if not a or not b or abs(a["oecd"] - b["oecd"]) > 1e-9 or (a["ratio"] is None) != (b["ratio"] is None) \
                or (a["ratio"] is not None and abs(a["ratio"] - b["ratio"]) > 1e-9) \
                or (a.get("rang_oit") is None) != (b.get("rang_oit") is None) \
                or (a.get("rang_oit") is not None and (abs(a["rang_oit"] - b["rang_oit"]) > 1e-9 or abs(a["rang_oecd"] - b["rang_oecd"]) > 1e-9)):
            bad.append(f"{k}: {b} != {a}")
    # fixture expectations: 4110's scenario is missing -> no ratio; 2512 and 4110 tie on the OIT score -> same rank
    if got.get("4110", {}).get("ratio") is not None or "rang_oit" in got.get("9999", {}) \
            or abs(got["2512"]["rang_oit"] - got["4110"]["rang_oit"]) > 1e-12:
        bad.append(f"fixture rules {got}")
    if R.rank_agreement(0.15) != 1 or abs(R.rank_agreement(0.35) - 0.8) > 1e-9 or R.rank_agreement(1.0) != 0.5 or R.rank_agreement(None) is not None:
        bad.append("rank agreement rule")
    if re.search(r"oe\[\"oecd\"\][^\n]*exp_p|exp_p[^\n]*oe\[", c.src["rob"]):
        bad.append("the OECD exposure enters the exposure")
    real = ROOT / "data" / "sources" / R.OECD_XLSX
    n = None
    if real.exists():
        rr = R.read_oecd(real)
        n = len(rr)
        import openpyxl
        wb = openpyxl.load_workbook(real, read_only=True, data_only=True)
        tot = {r[0]: 1 - r[3] / 23 for r in wb["Data"].iter_rows(values_only=True)
               if r and isinstance(r[0], str) and re.fullmatch(r"\d\d-\d{4}\.\d\d", r[0]) and isinstance(r[3], (int, float))}
        diff = [k for k in tot if k not in rr or abs(rr[k][0] - tot[k]) > 1e-6]
        if diff or n != 879:
            bad.append(f"real workbook: {n} occupations, reversed index != 1 - total / 23 for {diff[:3]}")
    return not bad, f"differences {bad[:4]}; real occupations read: {n}"


FIX_ESCO = [("ISCO level 4", "2512", "0.25"), ("ISCO level 4", "1330", "0.0"), ("ISCO level 3", "251", "0.9"),
            ("ISCO level 4", "3333", "0.5"), ("Occupation", "2512.1", "0.2"), ("Occupation", "2512.2", "0.3"),
            ("Occupation", "1330.1", "0.0"), ("Occupation", "3333.4", "0.5")]


def fixture_esco(path: Path):
    body = "conceptType,conceptUri,code,preferredLabel,greenShare\n" + "".join(f"{t},u{i},{c},l,{v}\n" for i, (t, c, v) in enumerate(FIX_ESCO))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("greenShareOcc_fr.csv", body)
        z.writestr("occupations_fr.csv", "conceptType\n")


def oracle_esco(path: Path) -> dict:
    """Own reading: the mean of the OCCUPATION rows per 4-digit prefix of their code."""
    import csv
    by = {}
    with zipfile.ZipFile(path) as z:
        for r in csv.DictReader(io.TextIOWrapper(z.open("greenShareOcc_fr.csv"), encoding="utf-8")):
            if r["conceptType"] == "Occupation":
                by.setdefault(r["code"][:4], []).append(float(r["greenShare"]))
    return {k: sum(v) / len(v) for k, v in by.items()}


@check("RB10 ESCO: green share per ISCO group re-derived from the occupation rows, weighted per job, control only")
def rb10(c: Ctx):
    R = c.R()
    tmp = Path(tempfile.mkdtemp())
    try:
        fixture_esco(tmp / "e.zip")
        got, exp = R.read_esco(tmp / "e.zip"), oracle_esco(tmp / "e.zip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [k for k in set(got) | set(exp) if k not in got or k not in exp or abs(got[k] - exp[k]) > 1e-9]
    if "251" in got:
        bad.append("an ISCO level 3 row read")
    d = crafted()["full"]
    a, b = R.job(d, AUG, CED, OECD), R.job(d, AUG, CED, OECD, got)
    for key in ("score", "scenarios", "composantes", "confiance", "ocde"):
        if a[key] != b[key]:
            bad.append(f"ESCO changes « {key} »")
    want = (0.25 * 3 + 0.0 * 1) / 4
    e = b.get("esco") or {}
    if e.get("part_verte") is None or abs(e["part_verte"] - round(want, 4)) > 1e-9 or e.get("n_codes") != 2 \
            or abs(e.get("mediane", -1) - statistics.median(got.values())) > 1e-4:
        bad.append(f"job ESCO block {e}")
    if (a.get("esco") or {}).get("part_verte") is not None:
        bad.append("a green share without ESCO")
    real = ROOT / "data" / "sources" / R.ESCO_ZIP
    info = None
    if real.exists():
        g2, e2 = R.read_esco(real), oracle_esco(real)
        diff = [k for k in set(g2) | set(e2) if k not in g2 or k not in e2 or abs(g2[k] - e2[k]) > 1e-9]
        if diff or len(g2) < 400:
            bad.append(f"real zip: {len(g2)} groups, differences {sorted(diff)[:4]}")
        if c.real:
            import csv
            with zipfile.ZipFile(real) as z:
                rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8"))  # noqa: E731
                occ = {r["conceptUri"]: float(r["greenShare"]) for r in rd("greenShareOcc_fr.csv") if r["conceptType"] == "Occupation"}
                green = {r["conceptUri"] for r in rd("greenSkillsCollection_fr.csv")}
                tot, gr = {}, {}
                for r in rd("occupationSkillRelations_fr.csv"):
                    o = r["occupationUri"]
                    tot[o] = tot.get(o, 0) + 1
                    gr[o] = gr.get(o, 0) + (r["skillUri"] in green)
            same = sum(1 for o, v in occ.items() if tot.get(o) and abs(gr[o] / tot[o] - v) < 1e-9)
            info = f"{len(g2)} groups; occupations whose published share = green skills / skills: {same}/{len(occ)}"
        else:
            info = f"{len(g2)} groups"
    return not bad, f"differences {bad[:4]}; real: {info}"


def oracle_cuts(medians: list) -> tuple:
    """Own quantiles (inclusive, linear): position (n - 1) * q in the sorted list."""
    v = sorted(medians)
    def q(p):
        x = (len(v) - 1) * p
        i = int(x)
        return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (x - i)
    return q(0.2), q(0.8)


@check("RB11 repère: the top and bottom 20 % of the scored jobs, cut points re-derived, levels per job, none without a score")
def rb11(c: Ctx):
    R = c.R()
    bad = []
    rng = random.Random(11)
    meds = [round(rng.gauss(70, 4.5), 1) for _ in range(500)] + [70.0] * 20
    jobs = [(f"M{i}", json.dumps({"score": {"median": m}})) for i, m in enumerate(meds)] + [("X", json.dumps({"score": None}))]
    out, cuts = R.with_repere(jobs)
    lo, hi = oracle_cuts(meds)
    if cuts is None or abs(cuts[0] - lo) > 1e-9 or abs(cuts[1] - hi) > 1e-9:
        bad.append(f"cut points {cuts} != {(lo, hi)}")
    lv = {m: json.loads(j)["repere"] for m, j in out}
    for (m, j), med in zip(jobs, meds):
        want = "haut" if med >= hi else "bas" if med <= lo else "moyen"
        if (lv[m] or {}).get("niveau") != want:
            bad.append(f"{m} {med}: {lv[m]} != {want}")
            break
    if lv["X"] is not None:
        bad.append("a repère without a score")
    share = {x: sum(1 for v in lv.values() if v and v["niveau"] == x) / len(meds) for x in ("haut", "bas")}
    if not all(0.17 <= v <= 0.25 for v in share.values()):
        bad.append(f"tails {share}")
    if R.with_repere([("A", json.dumps({"score": {"median": 70}}))])[1] is not None:
        bad.append("a repère from fewer than 5 scored jobs")
    real = None
    if c.real and c.db is not None:
        import duckdb
        con = duckdb.connect(str(c.db), read_only=True)
        src, p = R._src(con)
        if src is not None:
            stored = [json.loads(d) for _, d in src.execute(f"SELECT met_id, data FROM {p}r35_metier").fetchall()]
            sm = [d["score"]["median"] for d in stored if d["score"]]
            lo2, hi2 = oracle_cuts(sm)
            wrong = sum(1 for d in stored if d["score"] and (d.get("repere") or {}).get("niveau")
                        != ("haut" if d["score"]["median"] >= hi2 else "bas" if d["score"]["median"] <= lo2 else "moyen"))
            if wrong or any(d.get("repere") for d in stored if not d["score"]):
                bad.append(f"real: {wrong} stored levels differ")
            real = {x: sum(1 for d in stored if (d.get("repere") or {}).get("niveau") == x) for x in ("haut", "moyen", "bas")}
            real["seuils"] = (round(lo2, 1), round(hi2, 1))
    return not bad, f"differences {bad[:4]}; real {real}"


@check("RB8 mutation test: every seeded bug is caught")
def rb8(c: Ctx):
    targets = {m[4] for m in SOURCE_MUTANTS}
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        if kind == "js":
            m.js = src.replace(old, new, 1)
        else:
            m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(SOURCE_MUTANTS)} caught; missed {missed}"


def run(db: Path | None = None, real: bool = False) -> list[dict]:
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real)
    out = []
    for fn in CHECKS:
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
