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


def oracle_job(d: dict, aug: dict, ced: dict) -> dict:
    """The PRD's formulas, written again."""
    codes = [c for c in ((d.get("ia") or {}).get("isco") or []) if re.fullmatch(r"\d{4}", c.get("code") or "")]
    W = sum(c.get("n_intitules") or 1 for c in codes)
    def mean(pairs):
        s = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / s if s else None
    exp = mean([(c["score"], (c.get("n_intitules") or 1) / W) for c in codes if c.get("score") is not None])
    au = mean([(aug[c["code"]][0], (c.get("n_intitules") or 1) / W) for c in codes if c["code"] in aug])
    cr = mean([(ced[c["code"][:2]], (c.get("n_intitules") or 1) / W) for c in codes if c["code"][:2] in ced])
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
        sc = {"S1": (0.35 * ia(min(1, exp * 1.25), au * 0.8) + 0.25 * dem(M)) / 0.6,
              "S2": (0.35 * ia(exp, au) + 0.25 * dem(M)) / 0.6,
              "S3": (0.35 * ia(exp, au) + 0.25 * dem(M3)) / 0.6}
    return {"exp": exp, "aug": au, "scen": {k: round(v, 1) for k, v in sc.items()}, "C": C, "M": M, "T": T}


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


@check("RB3 per job: an independent implementation of the PRD formulas equals the module on crafted jobs")
def rb3(c: Ctx):
    R = c.R()
    bad = []
    for name, d in crafted().items():
        got = R.job(d, AUG, CED)
        exp = oracle_job(d, AUG, {k: v["postes"] for k, v in CED.items()})
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
    names = ("ROB_REGIME", "ROB_SCEN", "ROB_CONF", "robNum", "robustesseTile", "robustesseCard")
    if not all(top(c.js, n) for n in names):
        return False, "a renderer is missing from app.js"
    R = c.R()
    full = R.job(crafted()["full"], AUG, CED)
    full = json.loads(json.dumps(full))
    full["isco"][0]["libelle"] = HOSTILE
    full["model_version"] = HOSTILE
    full["sources_detail"] = [{"id": "oit", "libelle": "OIT " + HOSTILE, "annee": 2025}]
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
    s = full["score"]
    if '<span class="estim">' not in cf or f">{round(s['median'])}<" not in cf.replace(" ", "") and str(round(s["median"])) not in cf:
        bad.append("the median is not shown as an estimation")
    if f"{round(s['min'])}" not in cf or f"{round(s['max'])}" not in cf:
        bad.append("the range between the scenarios is not shown")
    for w in ("fraîcheur", "liens observés", "accord des sources", "couverture", "D'où vient ce chiffre", "Version du modèle", "OIT &lt;img"):
        if w not in cf:
            bad.append(f"card lacks « {w} »")
    if "Données insuffisantes" not in cn or re.search(r"/ 100", cn) or "données insuffisantes" not in tn:
        bad.append("insufficient data still shows a number")
    if c0 or t0:
        bad.append("output without data")
    return not bad, f"differences {bad[:4]}"


@check("RB6 plumbing: build beside the warehouse, API, job page tile and card, sources, README, CLAUDE.md, tests and durations")
def rb6(c: Ctx):
    bad = []
    if "robustesse.build(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build")
    if 'd["robustesse"] = ROB.for_metier(' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("API")
    if "${robustesseTile(d.robustesse)}" not in c.js or '["avenir", "Avenir du métier", `${robustesseCard(d.robustesse)}' not in c.js:
        bad.append("job page")
    from suptracker import sources as SRC
    st = {s["key"]: s["status"] for s in SRC.SOURCES if "robustesse_2035" in s.get("feeds", ()) and s["status"] == "en_ligne"}
    if st != {"cedefop_skills_forecast_2026": "en_ligne", "anthropic_aei": "en_ligne"}:
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
    aug = {r[0]: (r[1], r[2], r[3]) for r in src.execute("SELECT isco, augmentation, n_onet, niveau FROM r35_isco").fetchall()}
    stored = {m: json.loads(d) for m, d in src.execute("SELECT met_id, data FROM r35_metier").fetchall()}
    rng = random.Random(7)
    for mid in rng.sample(sorted(stored), min(80, len(stored))):
        d = MT.detail(con, mid)
        o = oracle_job(d, aug, {k: v[1] for k, v in ced.items()})
        s = stored[mid]
        if s["scenarios"] is not None and s["scenarios"] != o["scen"]:
            bad.append(f"{mid}: {s['scenarios']} != {o['scen']}")
    scored = [s for s in stored.values() if s["score"]]
    # stability: the PRD weights (35 / 25) moved by 10 points each way, order of the scored jobs (Spearman)
    base, plus, minus = [], [], []
    for s in scored:
        k = s["composantes"]
        base.append((0.35 * k["ia"] + 0.25 * k["demande"]) / 0.6)
        plus.append((0.45 * k["ia"] + 0.15 * k["demande"]) / 0.6)
        minus.append((0.25 * k["ia"] + 0.35 * k["demande"]) / 0.6)
    rho = (round(spearman(base, plus), 3), round(spearman(base, minus), 3)) if base else None
    return not bad, (f"{len(scored)}/{len(stored)} jobs scored; {sum(1 for v in ced.values() if v[2] == 'UE27')} groups with the "
                     f"EU-27 growth; Spearman at ±10 points: {rho}; differences {bad[:3]}")


SOURCE_MUTANTS = [
    ("rob", "break threshold loosened", "BREAK_JUMP, BREAK_GAP = 0.25, 0.30", "BREAK_JUMP, BREAK_GAP = 0.25, 3.0", "RB1"),
    ("rob", "French growth kept for a broken group", "growth = g_eu if use_eu else g_fr", "growth = g_fr", "RB1"),
    ("rob", "replacement from the EU", 'replacement = sum((rep.get(("France", code))', 'replacement = sum((rep.get(("EU27", code))', "RB1"),
    ("rob", "other month read", 'AEI_MONTH = "2026-05-01"', 'AEI_MONTH = "2026-04-01"', "RB2"),
    ("rob", "augmentation over all usage", "out[soc] = a / (a + b)", "out[soc] = a / 100", "RB2"),
    ("rob", "no major-group fallback", '            out[isco] = (statistics.fmean(majors), 0, "grand_groupe")', "            pass", "RB2"),
    ("rob", "exposure x augmentation", "return 100.0 * (1.0 - exp * (1.0 - aug))", "return 100.0 * (1.0 - exp * aug)", "RB4"),
    ("rob", "S1 softer", "exp, aug = min(1.0, exp * S1_EXP), aug * S1_AUG", "exp, aug = exp, aug", "RB3"),
    ("rob", "demand weights swapped", "W_CED, W_M2030, W_BMO = 0.5, 0.3, 0.2", "W_CED, W_M2030, W_BMO = 0.3, 0.5, 0.2", "RB3"),
    ("rob", "other fixed bounds", '"ced": (-0.10, 0.90)', '"ced": (-0.10, 1.90)', "RB3"),
    ("rob", "median replaced by the worst case", '"median": statistics.median(vals)', '"median": min(vals)', "RB3"),
    ("rob", "confidence = mean", "conf = min(comps.values())", "conf = statistics.fmean(comps.values())", "RB3"),
    ("rob", "score shown at low confidence", "shown = len(vals) == 3 and conf >= CONF_LOW", "shown = len(vals) == 3", "RB3"),
    ("rob", "name links counted as observed", "observed += w * (1.0 if onisep else 0.5)", "observed += w * (1.0 if True else 0.5)", "RB3"),
    ("rob", "badge threshold", "max(vals) - min(vals) > BADGE_SPREAD", "max(vals) - min(vals) > 50", "RB3"),
    ("js", "label unescaped", '<li>${esc(x.libelle)}</li>', '<li>${x.libelle}</li>', "RB5"),
    ("js", "no estimation label", '${estimTag("médiane des trois scénarios")}', "", "RB5"),
    ("js", "no confidence detail", "fraîcheur des sources ${fmt2(k.fraicheur)}", "${fmt2(k.fraicheur)}", "RB5"),
    ("js", "number with insufficient data", '`<p class="muted">Données insuffisantes pour une estimation sûre : nous préférons ne pas afficher de chiffre.</p>`',
     '`<p>0 / 100</p>`', "RB5"),
]


@check("RB8 mutation test: every seeded bug is caught")
def rb8(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:5] if not fn(c)[0]]
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
