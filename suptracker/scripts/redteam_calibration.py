"""Red team of sprint 5: the next-campaign "repère" (calibrated ranges, back-tested, never a probability).

    python scripts/redteam_calibration.py [--db data/suptracker.duckdb] [--real]

The hold-out back-test is re-implemented independently (numpy, its own strata), the served ranges
and the zone stability are re-derived, the API and the page are checked, and a mutation test
seeds bugs (leakage of the hold-out year, wrong quantiles, predictor chosen on the hold-out,
unclipped ranges, a same-year "persistence", hard-coded coverage...) that must each be caught.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import calibration as C  # noqa: E402
from suptracker import journey as J  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
LEVEL_REF, CALIB_REF, HOLDOUT_REF = 0.80, (2023, 2024), 2025     # the red team's own copy of the method


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool, sample: int | None = None):
        self.db, self.real = db, real
        con = duckdb.connect(str(db), read_only=True)
        self.data = C.load(con)
        keys = sorted(self.data, key=lambda k: hashlib.blake2b(str(k).encode(), digest_size=6).hexdigest())
        self.small = {k: self.data[k] for k in keys[: sample or 2500]}          # for the mutation runs
        self.report = con.execute("SELECT * FROM mart.calibration_report").df() if self._has(con, "calibration_report") else None
        self.forecast = con.execute("SELECT * FROM mart.forecast").df() if self._has(con, "forecast") else None
        self.persist = con.execute("SELECT * FROM mart.zone_persistence").fetchall() if self._has(con, "zone_persistence") else []
        con.close()

    @staticmethod
    def _has(con, t):
        return bool(con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_schema='mart' AND table_name='{t}'").fetchone()[0])


# ---------------------------------------------------------------- independent re-implementation
def ref_cdf(counts_list, m):
    ladder = list(J.MENTIONS)
    upto = ladder[: ladder.index(m) + 1]
    known = sum(sum(c[x] for x in ladder) for c in counts_list)
    cum = sum(sum(c[x] for x in upto) for c in counts_list)
    return (cum / known if known else None), known


def ref_bucket(n):
    return 0 if n < 30 else 1 if n < 100 else 2


def ref_errors(data, target, predictor):
    te, ce = [], []
    for years in data.values():
        if target not in years:
            continue
        hist = [s for s in sorted(years) if s < target]             # strictly before the target
        th = [years[s]["taux"] for s in hist if years[s]["taux"] is not None]
        y = years[target]
        if th and y["taux"] is not None:
            p = {"derniere": th[-1], "moyenne_2": float(np.mean(th[-2:])), "moyenne": float(np.mean(th))}[predictor]
            te.append(((y["selective"], min(len(th), 3)), y["taux"] - p))
        if hist:
            for m in J.MENTIONS[:4]:
                pr, kn = ref_cdf([years[s]["counts"] for s in hist], m)
                ob, _ = ref_cdf([y["counts"]], m)
                if pr is not None and ob is not None:
                    ce.append((ref_bucket(kn), ob - pr))
    return te, ce


def ref_coverage(data, predictor, level=LEVEL_REF):
    lo_q, hi_q = 100 * (1 - level) / 2, 100 * (1 - (1 - level) / 2)
    out = {}
    for metric, idx in (("taux", 0), ("cdf", 1)):
        cal = []
        for t in CALIB_REF:
            cal += ref_errors(data, t, predictor)[idx]
        by = defaultdict(list)
        for k, e in cal:
            by[k].append(e)
        pooled = [e for _, e in cal]
        rng = {k: (np.percentile(v, lo_q), np.percentile(v, hi_q)) for k, v in by.items() if len(v) >= 30}
        allr = (np.percentile(pooled, lo_q), np.percentile(pooled, hi_q))
        hold = ref_errors(data, HOLDOUT_REF, predictor)[idx]
        inside = [rng.get(k, allr)[0] <= e <= rng.get(k, allr)[1] for k, e in hold]
        out[metric] = (len(hold), float(np.mean(inside)) if inside else None)
    return out


def ref_predictor(data):
    mae = {}
    for p in ("derniere", "moyenne_2", "moyenne"):
        te, _ = ref_errors(data, CALIB_REF[-1], p)
        mae[p] = float(np.mean([abs(e) for _, e in te]))
    best = min(mae.values())
    return [p for p in ("derniere", "moyenne_2", "moyenne") if abs(mae[p] - best) < 1e-12][0], mae


# ---------------------------------------------------------------- checks
@check("K1 the hold-out coverage is re-derived independently and equals the published one")
def k1(c: Ctx):
    pred, _ = ref_predictor(c.data)
    ref = ref_coverage(c.data, pred)
    pub = {r.metric: (r.n, r.coverage) for r in c.report.itertuples() if r.phase == "holdout" and r.stratum == "*"}
    diff = {m: (ref[m], pub.get(m)) for m in ref if pub.get(m) is None or ref[m][0] != pub[m][0] or abs(ref[m][1] - pub[m][1]) > 1e-9}
    sane = all(0.6 <= pub[m][1] <= 0.95 for m in pub) if c.real else True
    return not diff and sane and len(pub) == 2, f"published {pub}; independent {ref}; differ {diff}"


@check("K2 the access-rate predictor is chosen on the calibration year only, never on the hold-out")
def k2(c: Ctx):
    pred, mae = ref_predictor(c.data)
    used = set(c.report.predictor.dropna())
    rows = c.report[c.report.phase == "predictor"]
    on_cal = set(rows.target) == {CALIB_REF[-1]}
    return used == {pred} and on_cal, f"chosen {used}, independent choice {pred} (MAE on {CALIB_REF[-1]}: {mae}); predictor rows target {set(rows.target)}"


@check("K3 served ranges: inside bounds, contain the point, width = the stratum's error range, only current formations")
def k3(c: Ctx):
    f, rep = c.forecast, c.report
    latest = max(s for y in c.data.values() for s in y)
    serv = {(r.metric, r.stratum): (r.q_lo, r.q_hi) for r in rep.itertuples() if r.phase == "serving"}
    bad = []
    t = f.dropna(subset=["taux_hat"])
    bad += list(t[(t.taux_lo < -1e-9) | (t.taux_hi > 100 + 1e-9) | (t.taux_lo > t.taux_hat + 1e-9) | (t.taux_hi < t.taux_hat - 1e-9)].cod_aff_form[:3])
    d = f.dropna(subset=["cdf_hat"])
    bad += list(d[(d.cdf_lo < -1e-9) | (d.cdf_hi > 1 + 1e-9) | (d.cdf_lo > d.cdf_hat + 1e-9) | (d.cdf_hi < d.cdf_hat - 1e-9)].cod_aff_form[:3])
    width = []
    for r in t.itertuples():
        qlo, qhi = serv[("taux", r.taux_stratum)]
        if r.taux_hat + qlo >= 0 and r.taux_hat + qhi <= 100 and abs((r.taux_hi - r.taux_lo) - (qhi - qlo)) > 1e-6:
            width.append(r.cod_aff_form)
    targets = set(f.target)
    current = {y[latest]["cod"] for y in c.data.values() if latest in y}
    stray = set(f.cod_aff_form) - current
    return not bad and not width and targets == {latest + 1} and not stray, f"out of bounds {bad}; wrong width {width[:3]}; targets {targets}; formations not in {latest} {list(stray)[:3]}"


@check("K4 the point forecast of the share pools every past campaign's counts (as Mon parcours does)")
def k4(c: Ctx):
    f = c.forecast.set_index(["lineage_id", "mention"])
    bad, n = [], 0
    for lid in list(c.small)[:800]:
        years = c.data[lid]
        for m in J.MENTIONS[:4]:
            if (lid, m) not in f.index:
                continue
            want, _ = ref_cdf([years[s]["counts"] for s in sorted(years)], m)
            got = f.loc[(lid, m), "cdf_hat"]
            n += 1
            if (want is None) != (got is None or got != got) or (want is not None and abs(want - got) > 1e-9):
                bad.append((lid, m))
    return not bad and n > 0, f"{n} forecasts checked, {len(bad)} differ {bad[:2]}"


def ref_zone(years, sessions, m, taux):
    """Independent re-derivation of the bac-général zone stage 2 shows: pooled mention share,
    per-campaign series bounds summed, Wilson at each end, all-series share clipped into the bounds."""
    if taux is None:
        return None
    rows = [years[s] for s in sessions]
    p, n = ref_cdf([r["counts"] for r in rows], m)
    if not n:
        return None
    neo = sum(r["neobac"] or 0 for r in rows)
    if neo and sum(r["margins"]["acc_bg"] or 0 for r in rows) / neo < 0.05:
        return None
    lo, hi = J.wilson(p * n, n)
    k_lo = k_hi = g = 0
    for r in rows:
        b = J.series_cdf_bounds("bg", m, r["margins"])
        if b is not None:
            k_lo, k_hi, g = k_lo + b[0], k_hi + b[1], g + r["margins"]["acc_bg"]
    if g >= 10:
        p = min(max(p, k_lo / g), k_hi / g)
        lo, hi = J.wilson(k_lo, g)[0], J.wilson(k_hi, g)[1]
    return J.classify_zone(taux, p, lo, hi)


def ref_persistence(data):
    out = defaultdict(lambda: [0, 0])
    for t in (2024, 2025):
        for years in data.values():
            if t not in years or t - 1 not in years:
                continue
            hist = [s for s in sorted(years) if s < t]
            for m in J.MENTIONS[:4]:
                z = ref_zone(years, hist, m, years[t - 1]["taux"])
                if z is None or z["zone"] not in ("securite", "cible", "ambitieux", "hors_profil"):
                    continue
                o = ref_zone(years, [t], m, years[t]["taux"])
                if o is None:
                    continue
                k = (z["zone"], bool(z["uncertain"]))
                out[k][0] += 1
                out[k][1] += o["zone"] == z["zone"]
    return {k: (n, cc / n) for k, (n, cc) in out.items()}


@check("K5 zone stability re-derived independently (bac-général reading): next campaign alone, never the same year")
def k5(c: Ctx):
    ref = ref_persistence(c.small)
    got = C.zone_persistence(c.small)
    diff = {k: (ref.get(k), got.get(k)) for k in set(ref) | set(got) if ref.get(k) is None or got.get(k) is None
            or ref[k][0] != got[k][0] or abs(ref[k][1] - got[k][1]) > 1e-9}
    pub = {(z, u): r for z, u, n, r in c.persist}
    sure_lt_unsure = all(pub[(z, False)] > pub[(z, True)] for z in ("securite", "cible", "ambitieux") if (z, False) in pub and (z, True) in pub) if c.real else True
    return not diff and sure_lt_unsure, f"differ {list(diff.items())[:2]}; published {pub}; uncertain zones less stable {sure_lt_unsure}"


@check("K6 the API attaches the forecast of the student's mention and the stability of the row's own zone")
def k6(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    t = con.execute("""SELECT r.spe_type_key FROM core.taxonomy_link l JOIN core.taxonomy_rule r USING (rule_id)
        WHERE l.session = (SELECT max(session) FROM core.formation_year) GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""").fetchone()[0]
    res = J.stage2(con, "MATHS+SES", "b", t)
    C.attach(con, res, "b")
    f = c.forecast[c.forecast.mention == "b"].set_index("cod_aff_form")
    pub = {(z, u): r for z, u, n, r in c.persist}
    bad, n = [], 0
    for x in res["formations"]:
        r = x.get("repere")
        if x["zone"] not in C.ZONES_WITH_REPERE:
            bad += [x["cod_aff_form"]] if r else []
            continue
        if r is None:
            continue
        n += 1
        row = f.loc[x["cod_aff_form"]]
        if abs(r["taux_lo"] - row.taux_lo) > 1e-9 or abs(r["cdf_hi"] - row.cdf_hi) > 1e-9 or r["zone_confirmed"] != pub.get((x["zone"], bool(x["uncertain"]))):
            bad.append(x["cod_aff_form"])
    head = res.get("calibration") or {}
    con.close()
    return n > 0 and not bad and head.get("target") is not None, f"{n} rows checked on '{t}', {len(bad)} wrong {bad[:3]}; header {head}"


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 5: the next-campaign")
    blk = js[i: js.index("function mathsExpertesNote", i)]
    dyn = "c[m].coverage" in blk and not re.search(r"\d\d ?% des taux d'accès", blk)
    esc_t = "${esc(cal.target)}" in blk and "${esc(cal.holdout)}" in blk and "Repère ${esc(s2.calibration.target)}" in js
    words = "pas des chances d'admission" in blk and "testées sur" in blk and "(tous bacs)" in blk
    shown = re.sub(r"(?m)^\s*//.*$", "", blk)          # what the page can print, comments excluded
    promise = re.findall(r"probabilit|chances? d['’]être admis|tu seras admis", shown, re.I)
    gated = 'serie === "bg" && r.zone_confirmed != null' in blk and 'serie === "bg" && r.cdf_lo != null' in blk
    ok = dyn and esc_t and words and not promise and gated
    return ok, f"coverage read from the API {dyn}; target escaped {esc_t}; wording {words}; promises {promise}; series-gated {gated}"


@check("K7 the page reads the coverage from the data, says it is not a chance, and gates what is series-specific")
def k7(c: Ctx):
    from suptracker import glossary as G
    from suptracker.api import METHODOLOGY
    ok, detail = ui(APP_JS.read_text())
    m = METHODOLOGY.get("repere", "")
    meth = all(w in m for w in ("80 %", "testée sur 2025", "pas des chances", "mentions des candidats")) and "repere" in G.GLOSSARY
    return ok and meth, f"{detail}; methodology and glossary {meth}"


# ---------------------------------------------------------------- mutation test
UI_MUTANTS = [
    ("hard-coded coverage", "${cv(\"taux\")} des taux d'accès", "77 % des taux d'accès"),
    ("zone stability shown to bac techno and pro", 'serie === "bg" && r.zone_confirmed != null', "r.zone_confirmed != null"),
    ("target unescaped", "${esc(cal.target)}", "${cal.target}"),
    ("promise wording", "Ce ne sont pas des chances d'admission.", "Ta probabilité d'admission."),
]


@check("K8 mutation test: leakage, wrong quantiles, predictor on the hold-out, unclipped ranges, same-year or all-series stability and UI bugs are caught")
def k8(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"errors": C.errors, "qlo": C.Q_LO, "qhi": C.Q_HI, "choose": C.choose_predictor, "persist": C.zone_persistence,
             "zone_of": C.zone_of}
    pred, _ = ref_predictor(c.small)
    ref = ref_coverage(c.small, pred)

    def leak(data, target, predictor):           # the hold-out year leaks into its own history
        te, ce = [], []
        for lid, years in data.items():
            if target not in years:
                continue
            hist = sorted(years)
            th = [years[s]["taux"] for s in hist if years[s]["taux"] is not None]
            y = years[target]
            if th and y["taux"] is not None:
                te.append((C.taux_stratum(y["selective"], len(th)), y["taux"] - C.taux_point(th, predictor)))
            for m in C.MENTIONS:
                p, kn = C.cdf_of([years[s]["counts"] for s in hist], m)
                o, _ = C.cdf_of([y["counts"]], m)
                if p is not None and o is not None:
                    ce.append((C.size_bucket(kn), m, o - p))
        return te, ce

    def choose_on_holdout(data):
        mae = {p: float(np.mean([abs(e[-1]) for e in saved["errors"](data, C.HOLDOUT, p)[0]])) for p in C.PREDICTORS}
        return max(mae, key=mae.get), mae        # a different pick than the calibration one

    def same_year(data, targets=(2024, 2025)):
        out = saved["persist"](data, targets)
        return {k: (n, 1.0) for k, (n, r) in out.items()}

    def all_series(years, sessions, m, taux):     # Codex finding: the all-series reading, not the page's
        if taux is None:
            return None
        p, n = C.cdf_of([years[x]["counts"] for x in sessions], m)
        if p is None:
            return None
        return J.classify_zone(taux, p, *J.wilson(p * n, n))

    def coverage_of(bt):
        return {m: bt["coverage"][m]["*"][1] for m in ("taux", "cdf")}

    data_mutants = [
        ("hold-out year leaks into its history", lambda: setattr(C, "errors", leak), "coverage"),
        ("90 % quantiles announced as 80 %", lambda: (setattr(C, "Q_LO", 0.05), setattr(C, "Q_HI", 0.95)), "coverage"),
        ("predictor chosen on the hold-out", lambda: setattr(C, "choose_predictor", choose_on_holdout), "predictor"),
        ("stability measured on the same year", lambda: setattr(C, "zone_persistence", same_year), "persistence"),
        ("stability measured on the all-series zone", lambda: setattr(C, "zone_of", all_series), "displayed"),
    ]
    for name, apply, what in data_mutants:
        try:
            apply()
            if what == "coverage":
                p, _ = C.choose_predictor(c.small)
                got = coverage_of(C.backtest(c.small, p))
                caught = any(abs(got[m] - ref[m][1]) > 1e-9 for m in got)
            elif what == "displayed":
                caught = not k9(c)[0]
            elif what == "predictor":
                caught = C.choose_predictor(c.small)[0] != ref_predictor(c.small)[0]
            else:
                rp = ref_persistence(c.small)
                got = C.zone_persistence(c.small)
                caught = any(abs(got[k][1] - rp[k][1]) > 1e-9 for k in rp if k in got)
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            C.errors, C.Q_LO, C.Q_HI, C.choose_predictor, C.zone_persistence = (saved["errors"], saved["qlo"], saved["qhi"],
                                                                                 saved["choose"], saved["persist"])
            C.zone_of = saved["zone_of"]
        if not caught:
            missed.append(name)
    # unclipped ranges: K3's bound check must reject a served table with a negative lower bound
    f0 = c.forecast
    try:
        mut = f0.copy()
        i = mut.taux_hat.idxmin()
        mut.loc[i, "taux_lo"] = mut.loc[i, "taux_hat"] - 30
        c.forecast = mut
        if k3(c)[0]:
            missed.append("unclipped range")
    finally:
        c.forecast = f0
    n = len(UI_MUTANTS) + len(data_mutants) + 1
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


@check("K9 the stability is measured on the zone the page shows (bac-général reading of stage 2)")
def k9(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    types = [r[0] for r in con.execute("""SELECT r.spe_type_key FROM core.taxonomy_link l JOIN core.taxonomy_rule r USING (rule_id)
        WHERE l.session = (SELECT max(session) FROM core.formation_year) GROUP BY 1 ORDER BY count(*) DESC LIMIT 3""").fetchall()]
    latest = max(s for y in c.data.values() for s in y)
    by_cod = {y[latest]["cod"]: y for y in c.data.values() if latest in y}
    bad, n = [], 0
    for t in types:
        for m in ("sansmention", "b"):
            for x in J.stage2(con, "MATHS+SES", m, t)["formations"]:
                if x["zone"] not in C.ZONES_WITH_REPERE:
                    continue
                years = by_cod[x["cod_aff_form"]]
                z = C.zone_of(years, sorted(years), m, years[latest]["taux"])
                n += 1
                if z is None or (z["zone"], z["uncertain"]) != (x["zone"], x["uncertain"]):
                    bad.append((x["cod_aff_form"], m, x["zone"], z and z["zone"]))
    con.close()
    return n > 0 and not bad, f"{n} displayed zones re-read by the back-test classifier, {len(bad)} differ {bad[:3]}"


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
