"""Red team of the n+1 forecast (prevision): calibrated ranges of every published indicator with a history.

    python scripts/redteam_prevision.py [--db data/suptracker.duckdb] [--real]

The method is re-implemented independently (its own SQL loader, numpy quantiles, its own strata and
bounds): the predictor choice, the hold-out coverage and every served range are re-derived and compared
with the warehouse. The access rate must be sprint 5's range. The API and the page are checked, and a
mutation test seeds bugs (hold-out leakage, predictor chosen on the hold-out, zero-admit shares kept,
unclipped rates, additive count ranges, one campaign of history served, a past campaign forecast, a
re-forecast access rate, UI wording and escaping...) that must each be caught.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import calibration as CAL  # noqa: E402
from suptracker import prevision as PV  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
# the red team's own copy of the method
REF_LEVEL, REF_CALIB, REF_HOLDOUT, REF_MIN_HIST, REF_MIN_STRATUM, REF_FRAGILE = 0.80, 2024, 2025, 2, 30, 0.75
REF_PRED = ("derniere", "moyenne_2", "moyenne")
REF_COUNTS = {"acc_tot", "capa_fin", "voe_tot", "nb_voe_pp", "nb_cla_pp", "prop_tot", "acc_bg", "acc_bt", "acc_bp", "acc_brs"}
REF_RATES = {"part_terminale_generale_en_position_admis_pp", "part_terminale_techno_en_position_admis_pp",
             "part_terminale_pro_en_position_admis_pp", "pct_bg", "pct_bt", "pct_bp", "pct_bours", "pct_f", "pct_neobac",
             "pct_aca_orig", "pct_etab_orig", "pct_sansmention", "pct_ab", "pct_b", "pct_tb", "pct_tbf",
             "pct_acc_debutpp", "pct_acc_datebac", "pct_acc_finpp"}
TOL = 1e-6


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def ref_load(con, cols):
    """Independent loader: zero-admit campaigns carry 0 % admits' shares by convention, so pct_* are dropped there."""
    rows = con.execute(f"""SELECT l.lineage_id, f.session, f.cod_aff_form, f.acc_tot, {', '.join('f.' + c for c in cols)}
                           FROM core.formation_year f JOIN core.lineage l ON l.session = f.session AND l.cod_aff_form = f.cod_aff_form""").fetchall()
    out = defaultdict(dict)
    for lid, s, cod, n, *v in rows:
        d = {c: (None if (c.startswith("pct_") and not n) else x) for c, x in zip(cols, v)}
        d["_cod"], d["_n"] = cod, n
        out[lid][s] = d
    return dict(out)


class Ctx:
    def __init__(self, db: Path, real: bool, sample: int = 3000):
        self.db, self.real = db, real
        con = duckdb.connect(str(db), read_only=True)
        self.cols = sorted(REF_COUNTS | REF_RATES)
        self.ref = ref_load(con, self.cols + ["taux_acces_ens"])
        # edge lineages injected for the mutation runs, whatever the fixture holds: a formation whose latest campaign
        # has no admit (its admits' shares are 0 % by convention), and one that stopped before the latest campaign
        self.raw = PV.raw_rows(con)
        self.latest = max(r[1] for r in self.raw)
        self.inject = self._edges()
        self.mod = PV.from_rows(self.raw + self.inject)          # the module's own shaping, for the mutation runs
        self.ref_small_extra = self._ref_of(self.inject)
        keys = sorted(self.ref, key=lambda k: hashlib.blake2b(str(k).encode(), digest_size=6).hexdigest())
        self.small_keys = set(keys[:sample])
        has = lambda t: bool(con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_schema='mart' AND table_name='{t}'").fetchone()[0])
        self.stored = con.execute("SELECT * FROM mart.prevision").df() if has("prevision") else None
        self.report = con.execute("SELECT * FROM mart.prevision_report").df() if has("prevision_report") else None
        self.sprint5 = con.execute("""SELECT DISTINCT cod_aff_form, taux_hat, taux_lo, taux_hi, n_hist FROM mart.forecast
                                      WHERE taux_hat IS NOT NULL""").fetchall() if has("forecast") else []
        self.cal = con.execute("""SELECT coverage, n FROM mart.calibration_report WHERE phase = 'holdout' AND metric = 'taux'
                                  AND stratum = '*'""").fetchall() if has("calibration_report") else []
        con.close()

    def _edges(self):
        names = [x for x, _, _ in PV.INDICATORS]
        def row(lid, s, n, share):
            v = [(share if x.startswith("pct_") else 40.0) if PV.KIND[x] == "taux" else float(n + 5 * (s % 3)) for x in names]
            return (lid, s, f"{lid}-{s}", n, *v)
        L = self.latest
        zero = [row("RT_ZERO", s, n, sh) for s, n, sh in ((L - 3, 20, 55.0), (L - 2, 25, 60.0), (L - 1, 22, 58.0), (L, 0, 0.0))]
        gone = [row("RT_GONE", s, 30, 50.0) for s in (L - 3, L - 2, L - 1)]
        return zero + gone

    def _ref_of(self, raw):
        """The red team's own shaping of injected raw rows (same convention as ref_load)."""
        names = [x for x, _, _ in PV.INDICATORS]
        out = defaultdict(dict)
        for lid, s, cod, n, *v in raw:
            d = {c: (None if (c.startswith("pct_") and not n) else x) for c, x in zip(names, v)}
            d["_cod"], d["_n"] = cod, n
            out[lid][s] = d
        return dict(out)


# ---------------------------------------------------------------- independent re-implementation
def ref_point(h, p):
    return {"derniere": h[-1], "moyenne_2": float(np.mean(h[-2:])), "moyenne": float(np.mean(h))}[p]


def ref_stratum(n_last, k):
    size = 0 if (n_last or 0) < 30 else 1 if n_last < 100 else 2
    return (size, min(k, 3))


def ref_err(col, obs, hat):
    return math.log1p(obs) - math.log1p(max(hat, 0.0)) if col in REF_COUNTS else obs - hat


def ref_errors(data, col, target, p):
    out = []
    for years in data.values():
        if target not in years or years[target][col] is None:
            continue
        past = [s for s in sorted(years) if s < target]
        vals = [years[s][col] for s in past if years[s][col] is not None]
        if len(vals) < REF_MIN_HIST:
            continue
        out.append((ref_stratum(years[past[-1]]["_n"], len(vals)), ref_err(col, years[target][col], ref_point(vals, p))))
    return out


def ref_ranges(errs, level=REF_LEVEL):
    by = defaultdict(list)
    for st, e in errs:
        by[st].append(e)
        by["*"].append(e)
    q = ((1 - level) / 2 * 100, (1 + level) / 2 * 100)
    return {k: (float(np.percentile(v, q[0])), float(np.percentile(v, q[1])), len(v)) for k, v in by.items()}


def ref_pick(rr, st):
    return rr[st][:2] if st in rr and rr[st][2] >= REF_MIN_STRATUM else rr["*"][:2]


def ref_predictor(data, col):
    mae = {p: (lambda es: sum(abs(e) for _, e in es) / len(es) if es else float("inf"))(ref_errors(data, col, REF_CALIB, p)) for p in REF_PRED}
    return min(REF_PRED, key=lambda p: (mae[p], REF_PRED.index(p)))


def ref_report(data, col):
    p = ref_predictor(data, col)
    rr = ref_ranges(ref_errors(data, col, REF_CALIB, p))
    ho = ref_errors(data, col, REF_HOLDOUT, p)
    if not ho or "*" not in rr:
        return p, 0, None
    inside = sum(1 for st, e in ho if ref_pick(rr, st)[0] - 1e-9 <= e <= ref_pick(rr, st)[1] + 1e-9)   # a value on the bound is inside
    return p, len(ho), inside / len(ho)


def ref_bounds(col, hat, lo, hi):
    if col in REF_COUNTS:
        # whole people / vœux, outward-rounded; a 1e-9 guard so that an exact integer is not pushed out by float noise
        return max(0, math.floor(math.expm1(math.log1p(hat) + lo) + 1e-9)), max(0, math.ceil(math.expm1(math.log1p(hat) + hi) - 1e-9))
    return max(0.0, hat + lo), min(100.0, hat + hi)


def ref_serve(data, col, latest):
    p = ref_predictor(data, col)
    rr = ref_ranges(ref_errors(data, col, REF_CALIB, p) + ref_errors(data, col, REF_HOLDOUT, p))
    out = {}
    if "*" not in rr:
        return out
    for lid, years in data.items():
        if latest not in years or years[latest][col] is None:
            continue
        past = sorted(years)
        vals = [years[s][col] for s in past if years[s][col] is not None]
        if len(vals) < REF_MIN_HIST:
            continue
        hat = ref_point(vals, p)
        lo, hi = ref_pick(rr, ref_stratum(years[latest]["_n"], len(vals)))
        out[(lid, col)] = (hat, *ref_bounds(col, hat, lo, hi), years[latest][col], len(vals))
    return out


def close(a, b, tol=TOL):
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b)))


def compare_serving(got: dict, want: dict) -> list:
    """got/want: {(lineage, col): (hat, lo, hi, last, n_hist)}."""
    bad = [("missing", k) for k in want if k not in got] + [("extra", k) for k in got if k not in want]
    for k in set(got) & set(want):
        if not all(close(a, b) for a, b in zip(got[k], want[k])):
            bad.append(("value", k, got[k], want[k]))
    return bad


def module_serving(c: Ctx, keys=None):
    """Run the module's compute() (as patched) on the module loader's data, restricted to `keys`."""
    data = {k: v for k, v in c.mod.items() if keys is None or k in keys or k in c.ref_small_extra}
    rows, rep = PV.compute(data, c.latest)
    got = {(r[1], r[3]): (r[6], r[7], r[8], r[5], r[10]) for r in rows}
    return got, {r[0]: (r[2], r[5], r[6]) for r in rep}


def ref_all(c: Ctx, keys=None):
    data = {k: v for k, v in c.ref.items() if keys is None or k in keys}
    if keys is not None:
        data.update(c.ref_small_extra)
    want, rep = {}, {}
    for col in c.cols:
        want.update(ref_serve(data, col, c.latest))
        rep[col] = ref_report(data, col)
    return want, rep


# ---------------------------------------------------------------- checks
@check("P1 hold-out: the predictor (chosen on 2024 only) and the 2025 coverage of every indicator are re-derived and equal the report")
def p1(c: Ctx):
    if c.report is None:
        return False, "no mart.prevision_report"
    rep = {r.indicator: r for r in c.report.itertuples()}
    bad, shown = [], []
    for col in c.cols:
        p, n, cov = ref_report(c.ref, col)
        r = rep.get(col)
        if r is None or r.predictor != p or int(r.n) != n or not close(None if r.coverage != r.coverage else r.coverage, cov):
            bad.append((col, None if r is None else (r.predictor, r.n, r.coverage), (p, n, cov)))
        shown.append(f"{col[:22]} {cov if cov is None else round(cov, 3)}")
    return not bad, f"{len(c.cols)} indicators, {len(bad)} differ {bad[:2]}; " + ", ".join(shown[:4])


@check("P2 served ranges: every current formation x indicator re-derived (hat, bounds, last value, campaigns); counts are whole numbers, rates within [0, 100]")
def p2(c: Ctx):
    if c.stored is None:
        return False, "no mart.prevision"
    st = c.stored[c.stored.indicator != "taux_acces_ens"]
    got = {(r.lineage_id, r.indicator): (r.hat, r.lo, r.hi, r.last_value, r.n_hist) for r in st.itertuples()}
    want, _ = ref_all(c)
    bad = compare_serving(got, want)
    shape = []
    for r in st.itertuples():
        if r.indicator in REF_COUNTS and (r.lo != int(r.lo) or r.hi != int(r.hi) or r.lo < 0):
            shape.append(("count", r.cod_aff_form, r.indicator))
        if r.indicator in REF_RATES and not 0 <= r.lo <= r.hi <= 100:
            shape.append(("rate", r.cod_aff_form, r.indicator))
        if not r.lo <= r.hi or r.target != c.latest + 1 or r.last_session != c.latest or r.n_hist < REF_MIN_HIST:
            shape.append(("shape", r.cod_aff_form, r.indicator))
    return not bad and not shape and len(got) > 0, f"{len(got)} rows, {len(bad)} differ {bad[:2]}; shape {len(shape)} {shape[:2]}"


@check("P3 zero-admit campaigns: no admits' share (pct_*) is forecast from, or for, a campaign with no admit")
def p3(c: Ctx):
    if c.stored is None:
        return False, "no mart.prevision"
    zero = {years[c.latest]["_cod"] for years in c.ref.values() if c.latest in years and not years[c.latest]["_n"]}
    bad = c.stored[(c.stored.indicator.str.startswith("pct_")) & (c.stored.cod_aff_form.isin(zero))]
    return bad.empty, f"{len(zero)} current zero-admit formations, {len(bad)} admits' shares forecast for them"


@check("P4 the access rate is sprint 5's range (Mon parcours and the formation page agree), with its hold-out coverage")
def p4(c: Ctx):
    if c.stored is None:
        return False, "no mart.prevision"
    t = c.stored[c.stored.indicator == "taux_acces_ens"]
    s5 = {cod: (h, lo, hi) for cod, h, lo, hi, n in c.sprint5 if n >= REF_MIN_HIST}
    got = {r.cod_aff_form: (r.hat, r.lo, r.hi) for r in t.itertuples()}
    cur = {years[c.latest]["_cod"] for years in c.ref.values() if c.latest in years and years[c.latest]["taux_acces_ens"] is not None}
    want = {k: v for k, v in s5.items() if k in cur}
    bad = [k for k in set(got) | set(want) if k not in got or k not in want or not all(close(a, b) for a, b in zip(got[k], want[k]))]
    rep = c.report[c.report.indicator == "taux_acces_ens"] if c.report is not None else None
    cov_ok = bool(c.cal) and rep is not None and len(rep) == 1 and close(float(rep.coverage.iloc[0]), c.cal[0][0])
    return not bad and cov_ok and len(got) > 0, f"{len(got)} access-rate ranges, {len(bad)} differ from sprint 5 {bad[:2]}; coverage as sprint 5 {cov_ok}"


@check("P5 API: only on the latest campaign's page, indicators in order, fragile = coverage below 75 %, nothing for a past campaign")
def p5(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    cods = sorted(set(c.stored.cod_aff_form))[:: max(1, len(set(c.stored.cod_aff_form)) // 300)] if c.stored is not None else []
    order = [x for x, _, _ in PV.INDICATORS]
    bad = []
    for cod in cods:
        b = PV.for_formation(con, cod, c.latest)
        if not b or b["target"] != c.latest + 1 or b["level"] != REF_LEVEL:
            bad.append((cod, "missing"))
            continue
        ks = [i["indicator"] for i in b["indicators"]]
        if ks != sorted(ks, key=order.index) or len(ks) != len(set(ks)):
            bad.append((cod, "order"))
        for i in b["indicators"]:
            if i["fragile"] != (i["coverage"] is not None and i["coverage"] < REF_FRAGILE):
                bad.append((cod, i["indicator"], "fragile"))
        if PV.for_formation(con, cod, c.latest - 1) is not None:
            bad.append((cod, "past campaign"))
    con.close()
    return not bad and len(cods) > 0, f"{len(cods)} pages, {len(bad)} wrong {bad[:3]}"


def fn_body(js, name):
    i = js.index(name)
    j = min(k for k in (js.find("\nfunction ", i + 1), js.find("\nconst ", i + 1), js.find("\n// ----", i + 1)) if k > 0)
    return js[i:j]


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Prévision n+1")
    blk = js[i: js.index("// ---- Sprint 8: insertion", i)]
    safe = ("esc(", "pvVal(", "pvRange(", "pvCov(", "fmt(", "tip(", "block(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", blk)
           if re.search(r"\b(?:label|title|p\.target|p\.holdout|p\.last_session|p\.calibration)\b", m) and not m.lstrip().startswith(safe)]
    card = fn_body(js, "function previsionCard(")
    words = all(w in card for w in ("pas des chiffres officiels", "jamais des chances d'admission", "calculée séparément", "sans l'avoir vue"))
    words = words and "moins fiable" in fn_body(js, "function pvLine(")
    hard = re.findall(r"\b(?:76|77|70|80)[,.]?\d*\s*(?:%|\\u00a0%)", blk)          # a coverage or level typed in by hand
    code = re.sub(r"(?m)^\s*//.*$", "", blk)                                   # wording is checked on the code, not comments
    chance = re.findall(r"(?i)probabilit|vos chances|tes chances|chance d'être", code)
    wired = all(s in js for s in ("${previsionCard(d.prevision)}", 'pvLine(d.prevision, "taux_acces_ens")',
                                  'pvLine(d.prevision, "part_terminale_generale_en_position_admis_pp")', 'pvLine(d.prevision, "acc_tot")'))
    ok = not raw and words and not hard and not chance and wired
    return ok, f"unescaped {raw[:3]}; wording {words}; hard-coded figures {hard[:2]}; chance wording {chance[:2]}; wired {wired}"


@check("P6 page: three headline lines and the card are wired, stored strings escaped, coverage read from the data, never a chance")
def p6(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("card not wired", "${previsionCard(d.prevision)}", ""),
    ("admits headline line not wired", 'pvLine(d.prevision, "acc_tot")', '""'),
    ("unescaped indicator label", "<td>${esc(label(i.indicator))}</td>", "<td>${label(i.indicator)}</td>"),
    ("coverage hard-coded", "(objectif ${fmt(100 * p.level, 0)}\\u00a0%)", "(objectif 80\\u00a0%)"),
    ("not-official caveat dropped", "Ce sont des estimations, pas des chiffres officiels, et jamais des chances d'admission. ", ""),
    ("fragile flag dropped", '${i.fragile ? \' <span class="muted">(fourchette moins fiable)</span>\' : ""}', ""),
    ("probability wording", "Fourchettes estimées pour la campagne", "Vos chances estimées pour la campagne"),
]


@check("P7 mutation test: leakage, predictor on the hold-out, zero-admit shares, unclipped rates, additive counts, one campaign served, stale formations, UI bugs")
def p7(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    keys = c.small_keys
    want, want_rep = ref_all(c, keys)
    saved = {k: getattr(PV, k) for k in ("errors", "CALIBRATION_TARGET", "bounds", "MIN_HIST", "point", "stratum", "Q_LO")}
    saved_mod = c.mod
    cal_q = (CAL.Q_LO, CAL.Q_HI)

    def leak_errors(data, col, target, p):        # the hold-out year leaks into the calibration ranges
        e = saved["errors"](data, col, target, p)
        return e + saved["errors"](data, col, PV.HOLDOUT, p) if target == PV.CALIBRATION_TARGET else e

    def additive(kind, hat, lo, hi):
        return (max(0.0, hat + lo), hat + hi) if kind == "effectif" else saved["bounds"](kind, hat, lo, hi)

    def unclipped(kind, hat, lo, hi):
        return (hat + lo, hat + hi) if kind == "taux" else saved["bounds"](kind, hat, lo, hi)

    def keep_zero():
        saved_share = PV.admits_share
        PV.admits_share = lambda col: False
        try:
            c.mod = PV.from_rows(c.raw + c.inject)
        finally:
            PV.admits_share = saved_share

    def stale(data, latest):                        # formations absent from the latest campaign are forecast too
        rows, rep = saved_compute(data, latest)
        extra = []
        for lid, years in data.items():
            if latest not in years and latest - 1 in years and years[latest - 1]["acc_tot"] is not None:
                extra.append((years[latest - 1]["cod"], lid, latest + 1, "acc_tot", latest - 1, years[latest - 1]["acc_tot"], 1.0, 0.0, 2.0, "*", 2, "derniere"))
        return rows + extra, rep

    saved_compute = PV.compute
    mutants = [
        ("hold-out year leaks into the calibration ranges", lambda: setattr(PV, "errors", leak_errors)),
        ("predictor and ranges set on the hold-out year", lambda: setattr(PV, "CALIBRATION_TARGET", PV.HOLDOUT)),
        ("count ranges additive instead of proportional", lambda: setattr(PV, "bounds", additive)),
        ("rates not clipped to [0, 100]", lambda: setattr(PV, "bounds", unclipped)),
        ("one campaign of history served", lambda: setattr(PV, "MIN_HIST", 1)),
        ("strata ignore the formation's size", lambda: setattr(PV, "stratum", lambda n, k: saved["stratum"](100, k))),
        ("90 % ranges instead of 80 %", lambda: (setattr(CAL, "Q_LO", 0.05), setattr(CAL, "Q_HI", 0.95))),
        ("zero-admit campaigns' 0 % shares used", keep_zero),
        ("formations absent from the latest campaign forecast", lambda: setattr(PV, "compute", stale)),
    ]
    for name, apply in mutants:
        try:
            apply()
            got, rep = module_serving(c, keys)
            caught = bool(compare_serving(got, want)) or any(
                col in rep and (rep[col][0] != want_rep[col][0] or rep[col][1] != want_rep[col][1] or not close(rep[col][2], want_rep[col][2]))
                for col in want_rep)
        except Exception:  # noqa: BLE001 - a crash is a catch
            caught = True
        finally:
            for k, v in saved.items():
                setattr(PV, k, v)
            PV.compute = saved_compute
            CAL.Q_LO, CAL.Q_HI = cal_q
            c.mod = saved_mod
        if not caught:
            missed.append(name)
    # the unmutated module agrees with the reference on the sample (otherwise every "catch" is meaningless)
    got, rep = module_serving(c, keys)
    clean = not compare_serving(got, want)
    n = len(UI_MUTANTS) + len(mutants)
    return not missed and clean, f"{n - len(missed)}/{n} mutants caught; clean module agrees on the sample {clean}" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
