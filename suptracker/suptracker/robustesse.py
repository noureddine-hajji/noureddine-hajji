"""Robustesse 2035 (owner's PRD, 2026-11-16): for each JOB first (owner: « métiers d'abord »), how well its skills may keep
their value on the labour market between 2030 and 2035, as an ESTIMATION OF THE MODEL, never a forecast for a person, a
promise or a chance.

The owner lifted, for this feature only, the rule « never one composite score » (2026-11-16), with guardrails: the score
is labelled « estimation du modèle », its components are always shown, the MEDIAN of the three scenarios is shown with the
range between the worst and the best one under it, and every figure says where it comes from (source, date, model version).

Per ISCO-08 unit group c of the job (sprint 13's codes, weighted by their count of distinct titles):
  Exp_c  OIT 2025 (WP 140) mean task exposure, 0-1, as published. (The OECD 2026 measure, when the owner uploads it, will
         be crossed with it: a gap > 0.15 lowers the confidence.)
  Aug_c  Anthropic Economic Index (May 2026, Claude.ai, global): augmentation / (augmentation + automation) of the O*NET
         occupations linked to c by official tables (O*NET -> SOC -> BLS ISCO-08); none of them published = the mean of
         their SOC major groups, flagged.
  Sub = Exp x (1 - Aug); IA = 100 x (1 - Sub). Exposure is not replacement: a job where AI mostly helps keeps a high IA.
Demand (per scenario s):
  Ced    Cedefop Skills Forecast 2026, France, ISCO 2 digits: positions to fill 2024-2035 (growth 2023-2035 + replacement
         demand) / employment 2023. The French series carry the 2021 labour-force-survey break: owner's rule (2026-11-16),
         the GROWTH is the EU-27 one when the group moved by more than 25 % between 2020 and 2021 or when its 2023-2035 growth
         differs from the EU-27 one by more than 30 points (« moyenne européenne », confidence lower); replacement stays French.
  M2030  Les métiers en 2030 (Dares / France Stratégie 2022): positions to fill 2019-2030 / employment 2019 of the job's
         families; scenario S3 adds the official low-carbon variant (its imbalance minus the reference one).
  T      BMO 2026: share of hiring projects employers judge difficult (floors, as sprint 14 reads them).
  Dem = 0.5 Ced + 0.3 M2030 + 0.2 T, each brought to 0-100 between FIXED bounds (never min-max: versions stay comparable).
Job score R_s = (0.35 IA_s + 0.25 Dem_s) / 0.60 (the PRD's formation weights of these two terms, the formation adding
insertion and diversity). Scenarios: S1 AI accelerated (Exp x the OECD « +1 cognitive level » ratio of the job, else x 1.25,
capped at 1; Aug x 0.8: owner, 2026-11-17), S2 central, S3 fast transition
(M2030 low-carbon variant). Shown: the median of the three, then min-max; « dépend du scénario » when max - min > 15.
Confidence = the LOWEST of four components (freshness weighted by each source's weight, observed links, agreement of the sources:
the two demand sources and the OIT / OECD RANKS of the job (owner, 2026-11-17: the OECD measure is another notion on another
scale, uncorrelated with the OIT one, so it never enters the exposure), coverage); < 0.4 =
« données insuffisantes », no score.
"""
from __future__ import annotations

import io
import json
import statistics
import zipfile
from pathlib import Path

MODEL_VERSION = "2027.1"
DIR = Path(__file__).resolve().parent.parent / "data" / "sources"
CEDEFOP_ZIP = "cedefopskillsforecast2026.zip"
OECD_XLSX = "OECD AI Capability Gap Index_public data.xlsx"
# owner, 2026-11-17: the OECD measure is another notion on another scale (uncorrelated with the OIT one): the score keeps the
# OIT exposure, the two are compared by RANK: a gap of more than RANK_GAP lowers the agreement linearly, down to RANK_FLOOR
# (reached at a gap of RANK_GAP + 1 - RANK_FLOOR). The floor is the value of an unknown agreement: the two measures are
# uncorrelated by construction (other notion, other scale), so a disagreement lowers the confidence but alone never hides a score.
RANK_GAP, RANK_FLOOR = 0.15, 0.5
AEI_ZIP = "data_documentation_claude_ai.zip"
AEI_FILE = "aei_claude_ai_2026-06-26.csv"
AEI_MONTH = "2026-05-01"

# the PRD's default weights (owner: keep them, measure their stability)
W_IA, W_DEM = 0.35, 0.25
W_CED, W_M2030, W_BMO = 0.5, 0.3, 0.2
# fixed bounds -> 0..100 (measured spread 2026-11-17: Cedefop -11..87 %, M2030 5..55 %, BMO 6..84 %)
BOUNDS = {"ced": (-0.10, 0.90), "m2030": (0.0, 0.60), "bmo": (0.0, 1.0)}
# owner's rule for the Cedefop 2021 break
BREAK_JUMP, BREAK_GAP = 0.25, 0.30
S1_EXP, S1_AUG = 1.25, 0.8
BADGE_SPREAD = 15
CONF_HIGH, CONF_LOW = 0.7, 0.4
# publication year of each source, for the freshness component (1 the year of the model, minus 1/8 per year of age)
SOURCE_YEAR = {"oit": 2025, "aei": 2026, "cedefop": 2026, "m2030": 2022, "bmo": 2026, "ocde": 2026}
MODEL_YEAR = 2026
SOURCES = {
    "oit": "OIT, Working Paper 140 (2025) : exposition des tâches à l'IA générative",
    "aei": "Anthropic Economic Index (mai 2026) : usage observé, augmentation ou automatisation",
    "cedefop": "Cedefop, Skills Forecast 2026 (France, ISCO à 2 chiffres)",
    "m2030": "Dares / France Stratégie, Les métiers en 2030 (2022)",
    "bmo": "France Travail, Besoins en main-d'œuvre 2026",
    "ocde": "OCDE (2026), mesure d'exposition à l'IA (écart de capacités) et son scénario « +1 niveau cognitif »",
}
REGIMES = ("peu_expose", "surtout_augmente", "surtout_substituable", "mixte")


def norm(x: float | None, key: str) -> float | None:
    if x is None:
        return None
    lo, hi = BOUNDS[key]
    return max(0.0, min(100.0, 100.0 * (x - lo) / (hi - lo)))


def regime(exp: float | None, aug: float | None) -> str | None:
    """PRD 6.5, on the job's weighted means."""
    if exp is None or aug is None:
        return None
    if exp < 0.40:
        return "peu_expose"
    if aug >= 0.60:
        return "surtout_augmente"
    if aug < 0.40:
        return "surtout_substituable"
    return "mixte"


def ia_score(exp: float, aug: float, scenario: str = "S2", ratio: float | None = None) -> float:
    """S1: the exposure grows as the OECD « +1 cognitive level » scenario says for this job (`ratio` = scenario / current),
    else by the PRD's fixed S1_EXP; the augmentation share x S1_AUG (owner, 2026-11-17)."""
    if scenario == "S1":
        exp, aug = min(1.0, exp * (ratio if ratio is not None else S1_EXP)), aug * S1_AUG
    return 100.0 * (1.0 - exp * (1.0 - aug))


def level(c: float | None) -> str:
    return "faible" if c is None or c < CONF_LOW else "haute" if c >= CONF_HIGH else "moyenne"


# --------------------------------------------------------------------------------------------------------------- Cedefop
def read_cedefop(path: Path) -> dict:
    """{isco2: {...}} for France with the owner's break rule applied."""
    import openpyxl

    def load(z, name):
        ws = openpyxl.load_workbook(io.BytesIO(z.read(name)), read_only=True, data_only=True)["Data"]
        rows = list(ws.iter_rows(values_only=True))
        head = rows[0]
        return {(r[0], str(r[2])): dict(zip(head[3:], r[3:])) for r in rows[1:] if r[0] in ("France", "EU27")}
    with zipfile.ZipFile(path) as z:
        emp = load(z, "Employment_occupation_detail.xlsx")
        rep = load(z, "Replacement_demand_occupation_detail.xlsx")
    out = {}
    for (country, code), v in emp.items():
        if country != "France" or code == "Total" or not v.get(2023):
            continue
        eu = emp.get(("EU27", code)) or {}
        g_fr = v[2035] / v[2023] - 1
        g_eu = eu[2035] / eu[2023] - 1 if eu.get(2023) else None
        jump = abs(v[2021] / v[2020] - 1) if v.get(2020) else None
        use_eu = g_eu is not None and ((jump is None or jump > BREAK_JUMP) or abs(g_fr - g_eu) > BREAK_GAP)
        growth = g_eu if use_eu else g_fr
        replacement = sum((rep.get(("France", code)) or {}).get(y) or 0 for y in range(2024, 2036)) / v[2023]
        out[code] = {"isco2": code, "croissance_fr": g_fr, "croissance_ue": g_eu, "saut_2021": jump,
                     "croissance": growth, "source_croissance": "UE27" if use_eu else "France",
                     "remplacement": replacement, "postes": growth + replacement}
    return out


# ------------------------------------------------------------------------------------------------------------------- AEI
def read_aei(path: Path) -> dict:
    """{soc: aug share 0-1}: O*NET occupations (level 0, « 11-1011.00 ») and SOC major groups (level 1, « 11 »)."""
    import csv
    vals: dict = {}
    with zipfile.ZipFile(path) as z, z.open(AEI_FILE) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
            if (r["geo_id"] != "GLOBAL" or r["category_name"] != "soc_occupation" or r["date_start"] != AEI_MONTH
                    or r["metric_id"] not in ("collaboration_bucket_augmentation_pct", "collaboration_bucket_automation_pct")):
                continue
            vals.setdefault(r["node_external_id"], {})[r["metric_id"]] = float(r["value"])
    out = {}
    for soc, v in vals.items():
        a, b = v.get("collaboration_bucket_augmentation_pct"), v.get("collaboration_bucket_automation_pct")
        if a is not None and b is not None and a + b > 0:
            out[soc] = a / (a + b)
    return out


def isco_aug(con, aei: dict) -> dict:
    """{isco4: (aug, n_onet_read, 'detail' | 'grand_groupe')} through the official O*NET -> ISCO-08 links (sprint 15)."""
    links: dict = {}
    for onet, isco in con.execute("SELECT DISTINCT onet, isco FROM core.ia_theta_lien").fetchall():
        links.setdefault(isco, set()).add(onet)
    out = {}
    for isco, onets in links.items():
        detail = [aei[o] for o in sorted(onets) if o in aei]
        if detail:
            out[isco] = (statistics.fmean(detail), len(detail), "detail")
            continue
        majors = [aei[m] for m in sorted({o[:2] for o in onets}) if m in aei]
        if majors:
            out[isco] = (statistics.fmean(majors), 0, "grand_groupe")
    return out


# ------------------------------------------------------------------------------------------------------------------- OECD
def read_oecd(path: Path) -> dict:
    """{O*NET code: (reversed normalised gap now, the same in the « +1 cognitive » scenario)}: higher = more exposed."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def sheet(name):
        rows = list(wb[name].iter_rows(values_only=True))
        head = [str(x or "") for x in rows[2]]
        i_code, i_val = head.index("OCC_Code"), head.index("AI Capability Gap Index_Rev. norm.")
        return {r[i_code]: float(r[i_val]) for r in rows[3:] if r and isinstance(r[i_code], str)
                and re_onet(r[i_code]) and isinstance(r[i_val], (int, float))}
    now, scen = sheet("Data"), sheet("Scenario")
    return {k: (v, scen.get(k)) for k, v in now.items()}


def re_onet(code: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{2}-\d{4}\.\d{2}", code))


def isco_oecd(con, oecd: dict) -> dict:
    """{isco4: {oecd, oecd_s1, ratio, rang_oit, rang_oecd}}: the OECD values averaged over the O*NET occupations linked to the
    code by the official tables; ranks (0-1) among the ISCO codes that have both the OIT and the OECD measure."""
    links: dict = {}
    for onet, isco in con.execute("SELECT DISTINCT onet, isco FROM core.ia_theta_lien").fetchall():
        links.setdefault(isco, set()).add(onet)
    ilo = dict(con.execute("SELECT isco, moyenne FROM core.ia_oit_isco WHERE moyenne IS NOT NULL").fetchall())
    out = {}
    for isco, onets in links.items():
        vals = [oecd[o] for o in sorted(onets) if o in oecd]
        if not vals:
            continue
        base = statistics.fmean(v[0] for v in vals)
        sc = [v[1] for v in vals if v[1] is not None]
        s1 = statistics.fmean(sc) if len(sc) == len(vals) else None
        out[isco] = {"oecd": base, "oecd_s1": s1, "ratio": (s1 / base) if s1 is not None and base > 0 else None}
    both = sorted(k for k in out if k in ilo)

    def ranks(values: dict) -> dict:
        order = sorted(both, key=lambda k: values[k])
        n = len(order)
        r, i = {}, 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in order[i:j + 1]:
                r[k] = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
            i = j + 1
        return r
    r_ilo, r_oecd = ranks(ilo), ranks({k: out[k]["oecd"] for k in both})
    for k in both:
        out[k]["rang_oit"], out[k]["rang_oecd"] = r_ilo[k], r_oecd[k]
    return out


def rank_agreement(gap: float | None) -> float | None:
    """1 up to RANK_GAP, then 1 point less per point of gap, never under RANK_FLOOR."""
    if gap is None:
        return None
    return max(RANK_FLOOR, min(1.0, 1 - (gap - RANK_GAP)))


# ----------------------------------------------------------------------------------------------------------- per job
def _wmean(pairs: list[tuple[float, float]]) -> float | None:
    tot = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tot if tot else None


def job(d: dict, aug: dict, ced: dict, oecd: dict | None = None) -> dict:
    """One job's block from metiers.detail's answer `d`, the ISCO augmentation, Cedefop and OECD tables."""
    oecd = oecd or {}
    codes = (d.get("ia") or {}).get("isco") or []
    weights = {c["code"]: (c.get("n_intitules") or 1) for c in codes if len(c.get("code") or "") == 4 and c["code"].isdigit()}
    tot_w = sum(weights.values())
    exp_p, aug_p, ced_p, lignes = [], [], [], []
    rk_oit, rk_oecd, ratio_p, oecd_p = [], [], [], []
    observed = 0.0
    for c in codes:
        code = c.get("code")
        if code not in weights:
            continue
        w = weights[code] / tot_w
        a = aug.get(code)
        cd = ced.get(code[:2])
        oe = oecd.get(code)
        if oe:
            oecd_p.append((oe["oecd"], w))
            if oe.get("ratio") is not None:
                ratio_p.append((oe["ratio"], w))
            if oe.get("rang_oit") is not None:
                rk_oit.append((oe["rang_oit"], w))
                rk_oecd.append((oe["rang_oecd"], w))
        if c.get("score") is not None:
            exp_p.append((c["score"], w))
        if a:
            aug_p.append((a[0], w))
        if cd:
            ced_p.append((cd["postes"], w))
        onisep = "onisep" in (c.get("origine") or [])
        observed += w * (1.0 if onisep else 0.5) * (1.0 if a and a[2] == "detail" else 0.75)
        lignes.append({"isco": code, "libelle": c.get("libelle"), "poids": round(w, 4), "exposition": c.get("score"),
                       "augmentation": round(a[0], 4) if a else None, "augmentation_niveau": a[2] if a else None,
                       "cedefop_isco2": code[:2], "cedefop_postes": round(cd["postes"], 4) if cd else None,
                       "cedefop_croissance_source": cd["source_croissance"] if cd else None, "lien": "onisep" if onisep else "nom",
                       "ocde": round(oe["oecd"], 4) if oe else None})
    exp, augm, ced_rate = _wmean(exp_p), _wmean(aug_p), _wmean(ced_p)
    ratio, oecd_v = _wmean(ratio_p), _wmean(oecd_p)
    r_oit, r_oecd = _wmean(rk_oit), _wmean(rk_oecd)
    rank_gap = abs(r_oit - r_oecd) if r_oit is not None and r_oecd is not None else None
    fams = [f for f in (d.get("emploi2030") or []) if not f.get("absent") and (f.get("milliers") or {}).get("emploi_2019")]
    m_central, m_low = [], []
    for f in fams:
        m = f["milliers"]
        base = m["postes"] / m["emploi_2019"]
        m_central.append(base)
        if m.get("deseq_bas_carbone") is not None and m.get("deseq_ref") is not None:
            m_low.append(base + (m["deseq_bas_carbone"] - m["deseq_ref"]) / m["emploi_2019"])
    m2030 = statistics.fmean(m_central) if m_central else None
    m2030_low = statistics.fmean(m_low) if len(m_low) == len(m_central) and m_low else m2030
    bmo_f = [f for f in ((d.get("bmo") or {}).get("familles") or []) if not f.get("absent") and f.get("projets")]
    t = (sum(f["part_difficile"] * f["projets"] for f in bmo_f) / sum(f["projets"] for f in bmo_f)) if bmo_f else None

    terms = {"ced": norm(ced_rate, "ced"), "m2030": norm(m2030, "m2030"), "m2030_s3": norm(m2030_low, "m2030"),
             "bmo": norm(t, "bmo")}

    def dem(scenario):
        parts = [(terms["ced"], W_CED), (terms["m2030_s3" if scenario == "S3" else "m2030"], W_M2030), (terms["bmo"], W_BMO)]
        parts = [(v, w) for v, w in parts if v is not None]
        return _wmean(parts) if parts else None

    scen = {}
    for s in ("S1", "S2", "S3"):
        ia = ia_score(exp, augm, s, ratio) if exp is not None and augm is not None else None
        de = dem(s)
        if ia is None or de is None:
            scen[s] = None
            continue
        scen[s] = round((W_IA * ia + W_DEM * de) / (W_IA + W_DEM), 1)
    vals = [v for v in scen.values() if v is not None]
    # confidence: four components, the lowest one is kept
    used = [k for k, v in (("oit", exp), ("aei", augm), ("cedefop", ced_rate), ("m2030", m2030), ("bmo", t), ("ocde", oecd_v))
            if v is not None]
    # freshness: each source's age weighted by its weight in the score (the oldest source alone would cap every job)
    fw = {"oit": W_IA / 2, "aei": W_IA / 2, "cedefop": W_DEM * W_CED, "m2030": W_DEM * W_M2030, "bmo": W_DEM * W_BMO}
    fresh = _wmean([(max(0.0, 1 - (MODEL_YEAR - SOURCE_YEAR[k]) / 8), fw[k]) for k in used if k in fw]) or 0.0
    accord_dem = (max(0.0, 1 - abs(terms["ced"] - terms["m2030"]) / 50) if terms["ced"] is not None and terms["m2030"] is not None
                  else 0.5)
    accord_ia = rank_agreement(rank_gap)
    # agreement of the sources: the two demand sources, and the OIT and OECD ranks (owner, 2026-11-17); the lower one is kept
    accord = min(accord_dem, accord_ia) if accord_ia is not None else accord_dem
    cover = ((W_IA if exp is not None and augm is not None else 0)
             + W_DEM * sum(w for k, w in (("ced", W_CED), ("m2030", W_M2030), ("bmo", W_BMO)) if terms[k] is not None)) / (W_IA + W_DEM)
    comps = {"fraicheur": round(fresh, 3), "donnees_observees": round(observed, 3) if lignes else 0.0,
             "accord_sources": round(accord, 3), "couverture": round(cover, 3)}
    conf = min(comps.values())
    shown = len(vals) == 3 and conf >= CONF_LOW
    return {
        "model_version": MODEL_VERSION,
        "score": {"median": statistics.median(vals), "min": min(vals), "max": max(vals),
                  "dependance_scenario": max(vals) - min(vals) > BADGE_SPREAD} if shown else None,
        "scenarios": scen if shown else None,
        "composantes": {"exposition": round(exp, 4) if exp is not None else None,
                        "augmentation": round(augm, 4) if augm is not None else None,
                        "ia": round(ia_score(exp, augm), 1) if exp is not None and augm is not None else None,
                        "demande": round(dem("S2"), 1) if dem("S2") is not None else None,
                        "cedefop": round(terms["ced"], 1) if terms["ced"] is not None else None,
                        "cedefop_taux": round(ced_rate, 4) if ced_rate is not None else None,
                        "m2030": round(terms["m2030"], 1) if terms["m2030"] is not None else None,
                        "m2030_taux": round(m2030, 4) if m2030 is not None else None,
                        "m2030_bas_carbone_taux": round(m2030_low, 4) if m2030_low is not None else None,
                        "tension": round(terms["bmo"], 1) if terms["bmo"] is not None else None},
        "regime_ia": regime(exp, augm),
        "ocde": {"exposition": round(oecd_v, 4) if oecd_v is not None else None,
                 "rang_oit": round(r_oit, 3) if r_oit is not None else None,
                 "rang_ocde": round(r_oecd, 3) if r_oecd is not None else None,
                 "ecart_rang": round(rank_gap, 3) if rank_gap is not None else None,
                 "accord": round(accord_ia, 3) if accord_ia is not None else None,
                 "ratio_s1": round(ratio, 4) if ratio is not None else None},
        "confiance": {"niveau": level(conf), "valeur": round(conf, 3), **comps},
        "isco": lignes,
        "sources": [k for k in SOURCES if k in used],
    }


# ------------------------------------------------------------------------------------------------------------------ build
def build(con, d: Path = DIR, textes: Path | None = None) -> dict:
    """r35_cedefop, r35_isco and r35_metier (one JSON per job), beside the warehouse when the file exists (95 MB budget)."""
    from . import metiers as MT
    have = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    ced = read_cedefop(d / CEDEFOP_ZIP) if (d / CEDEFOP_ZIP).exists() else {}
    aei = read_aei(d / AEI_ZIP) if (d / AEI_ZIP).exists() else {}
    aug = isco_aug(con, aei) if "ia_theta_lien" in have else {}
    oe = read_oecd(d / OECD_XLSX) if (d / OECD_XLSX).exists() else {}
    oecd = isco_oecd(con, oe) if oe and {"ia_theta_lien", "ia_oit_isco"} <= have else {}
    jobs = []
    if "onisep_metier" in have:
        for (mid,) in con.execute("SELECT met_id FROM core.onisep_metier ORDER BY 1").fetchall():
            jobs.append((mid, json.dumps(job(MT.detail(con, mid), aug, ced, oecd), ensure_ascii=False, sort_keys=True)))
    crows = [[k, v["croissance_fr"], v["croissance_ue"], v["saut_2021"], v["croissance"], v["source_croissance"],
              v["remplacement"], v["postes"]] for k, v in sorted(ced.items())]
    irows = [[k, *(aug[k] if k in aug else (None, None, None)), *((oecd[k].get(x) for x in ("oecd", "oecd_s1", "ratio", "rang_oit", "rang_oecd"))
              if k in oecd else (None,) * 5)] for k in sorted(set(aug) | set(oecd))]

    def write(c, p):
        c.execute(f"""CREATE OR REPLACE TABLE {p}r35_cedefop (isco2 VARCHAR, croissance_fr DOUBLE, croissance_ue DOUBLE,
                      saut_2021 DOUBLE, croissance DOUBLE, source_croissance VARCHAR, remplacement DOUBLE, postes DOUBLE)""")
        if crows:
            c.executemany(f"INSERT INTO {p}r35_cedefop VALUES (?, ?, ?, ?, ?, ?, ?, ?)", crows)
        c.execute(f"""CREATE OR REPLACE TABLE {p}r35_isco (isco VARCHAR, augmentation DOUBLE, n_onet INTEGER, niveau VARCHAR,
                      ocde DOUBLE, ocde_s1 DOUBLE, ratio_s1 DOUBLE, rang_oit DOUBLE, rang_ocde DOUBLE)""")
        if irows:
            c.executemany(f"INSERT INTO {p}r35_isco VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", irows)
        c.execute(f"CREATE OR REPLACE TABLE {p}r35_metier (met_id VARCHAR, data VARCHAR)")
        if jobs:
            c.executemany(f"INSERT INTO {p}r35_metier VALUES (?, ?)", jobs)

    if textes is None or not Path(textes).exists():
        write(con, "core.")
    else:
        import duckdb
        from . import rapports as RP
        for t in ("r35_cedefop", "r35_isco", "r35_metier"):
            con.execute(f"DROP TABLE IF EXISTS core.{t}")
        RP._texts_con.cache_clear()
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    shown = sum(1 for _, j in jobs if json.loads(j)["score"])
    return {"cedefop_groupes": len(crows), "cedefop_ue": sum(1 for r in crows if r[5] == "UE27"),
            "isco_aug": len(aug), "isco_ocde": len(oecd),
            "metiers": len(jobs), "metiers_score": shown}


def _src(con):
    try:
        con.execute("SELECT 1 FROM core.r35_metier LIMIT 0")
        return con, "core."
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import rapports as RP
        db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
        f = RP.textes_path(Path(db[0])) if db and db[0] else None
        if f is None or not f.exists():
            return None, None
        c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
        c.execute("SELECT 1 FROM r35_metier LIMIT 0")
        return c, ""
    except Exception:  # noqa: BLE001
        return None, None


def for_metier(con, met_id: str) -> dict | None:
    c, p = _src(con)
    if c is None:
        return None
    r = c.execute(f"SELECT data FROM {p}r35_metier WHERE met_id = ?", [met_id]).fetchone()
    if not r:
        return None
    out = json.loads(r[0])
    out["sources_detail"] = [{"id": k, "libelle": SOURCES[k], "annee": SOURCE_YEAR[k]} for k in out.get("sources", [])]
    return out
