"""Sprint 5: a calibrated "repère" for the next campaign, back-tested, never a probability.

Open data cannot calibrate a chance of admission: SIES publishes the mentions of ADMITS, not of
CANDIDATES. What can be calibrated honestly is how the published indicators move from one
campaign to the next. For every formation (lineage) this module forecasts, for the next campaign:

* the official access rate (taux_acces_ens), with an 80 % range;
* the share of admits holding each mention or lower (all series), with an 80 % range;

and measures how often a zone of "Mon parcours" (sécurité, cible, ambitieux, hors profil) was
confirmed the next campaign.

Method, fixed before looking at the hold-out year:
* point forecast of the access rate: the predictor (last campaign, mean of the last two, mean of all
  campaigns) with the lowest error on the calibration year (2024); the share of admits: counts pooled
  over all past campaigns, as "Mon parcours" does;
* 80 % range: point + the 10th and 90th percentiles of the errors observed on the calibration
  transitions (targets 2023 and 2024), per stratum (selectivity x number of past campaigns for the
  access rate; admits headcount for the share);
* hold-out: the same method forecasts 2025 without seeing it; the share of 2025 values inside their
  range is the published coverage. The ranges served for the next campaign use the errors of every
  transition, 2025 included.
"""
from __future__ import annotations

from collections import defaultdict

from . import journey as J

LEVEL = 0.80                       # nominal coverage of the ranges
Q_LO, Q_HI = (1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2
CALIBRATION_TARGETS = (2023, 2024)  # transitions used to set the ranges before the hold-out
HOLDOUT = 2025
SIZE_BUCKETS = ((0, 30, "moins de 30 admis"), (30, 100, "30 à 99 admis"), (100, 10 ** 9, "100 admis ou plus"))
MIN_STRATUM = 30                   # fewer errors than this in a stratum: use the pooled errors
PREDICTORS = ("derniere", "moyenne_2", "moyenne")
MENTIONS = J.MENTIONS[:4]          # the mentions a student can choose


def quantile(xs: list[float], q: float) -> float:
    """Linear-interpolation quantile (numpy's default), no numpy needed at serving time."""
    s = sorted(xs)
    if not s:
        raise ValueError("empty")
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def size_bucket(n: float | None) -> str:
    n = n or 0
    return next(lab for lo, hi, lab in SIZE_BUCKETS if lo <= n < hi)


def load(con) -> dict:
    """{lineage_id: {session: row}} with the official access rate and the mention counts."""
    cols = ", ".join(f"fy.acc_{m}" for m in J.MENTIONS)
    rows = con.execute(f"""SELECT l.lineage_id, fy.session, fy.cod_aff_form, fy.taux_acces_ens, fy.select_form, {cols}
                           FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)""").fetchall()
    out = defaultdict(dict)
    for r in rows:
        lid, s, cod, t, sel, *acc = r
        counts = dict(zip(J.MENTIONS, [a or 0 for a in acc]))
        out[lid][s] = {"cod": cod, "taux": t, "selective": sel == "formation sélective", "counts": counts}
    return out


def taux_point(hist: list[float], predictor: str) -> float:
    if predictor == "derniere":
        return hist[-1]
    if predictor == "moyenne_2":
        return sum(hist[-2:]) / len(hist[-2:])
    return sum(hist) / len(hist)


def cdf_of(counts_list: list[dict], mention: str) -> tuple[float | None, float]:
    upto = J.MENTIONS[: J.MENTIONS.index(mention) + 1]
    known = sum(sum(c[m] for m in J.MENTIONS) for c in counts_list)
    cum = sum(sum(c[m] for m in upto) for c in counts_list)
    return (cum / known if known else None), known


def taux_stratum(selective: bool, n_hist: int) -> str:
    return f"{'sélective' if selective else 'non sélective'} · {min(n_hist, 3)}{'+' if n_hist >= 3 else ''} campagne(s)"


def errors(data: dict, target: int, predictor: str) -> tuple[list, list]:
    """(access-rate errors, share errors) of forecasting `target` from the campaigns before it."""
    te, ce = [], []
    for lid, years in data.items():
        if target not in years:
            continue
        hist = [s for s in sorted(years) if s < target]
        th = [years[s]["taux"] for s in hist if years[s]["taux"] is not None]
        y = years[target]
        if th and y["taux"] is not None:
            te.append((taux_stratum(y["selective"], len(th)), y["taux"] - taux_point(th, predictor)))
        if hist:
            for m in MENTIONS:
                pred, known = cdf_of([years[s]["counts"] for s in hist], m)
                obs, kn_obs = cdf_of([y["counts"]], m)
                if pred is not None and obs is not None:
                    ce.append((size_bucket(known), m, obs - pred))
    return te, ce


def ranges(errs: list, key=lambda e: e[0], val=lambda e: e[-1]) -> dict:
    """Per stratum (and pooled under '*'): (q_lo, q_hi, n) of the errors."""
    by = defaultdict(list)
    for e in errs:
        by[key(e)].append(val(e))
        by["*"].append(val(e))
    return {k: (quantile(v, Q_LO), quantile(v, Q_HI), len(v)) for k, v in by.items() if v}


def pick(r: dict, stratum: str) -> tuple[float, float, int, str]:
    """The stratum's range, or the pooled one when the stratum has too few errors."""
    if stratum in r and r[stratum][2] >= MIN_STRATUM:
        return (*r[stratum], stratum)
    return (*r["*"], "*")


def choose_predictor(data: dict) -> tuple[str, dict]:
    mae = {}
    for p in PREDICTORS:
        te, _ = errors(data, CALIBRATION_TARGETS[-1], p)
        mae[p] = sum(abs(e[-1]) for e in te) / len(te) if te else float("inf")
    return min(PREDICTORS, key=lambda p: (mae[p], PREDICTORS.index(p))), mae


def backtest(data: dict, predictor: str, calib: tuple = CALIBRATION_TARGETS, target: int = HOLDOUT) -> dict:
    """Ranges set on `calib`, applied to forecast `target`; coverage and error per stratum."""
    te, ce = [], []
    for t in calib:
        a, b = errors(data, t, predictor)
        te += a
        ce += b
    rt, rc = ranges(te), ranges(ce)
    ht, hc = errors(data, target, predictor)
    rep = {"taux": defaultdict(lambda: [0, 0, 0.0]), "cdf": defaultdict(lambda: [0, 0, 0.0])}
    for st, e in ht:
        lo, hi, _, _ = pick(rt, st)
        for k in (st, "*"):
            rep["taux"][k][0] += 1
            rep["taux"][k][1] += lo <= e <= hi
            rep["taux"][k][2] += abs(e)
    for st, m, e in hc:
        lo, hi, _, _ = pick(rc, st)
        for k in (st, "*"):
            rep["cdf"][k][0] += 1
            rep["cdf"][k][1] += lo <= e <= hi
            rep["cdf"][k][2] += abs(e)
    return {"ranges_taux": rt, "ranges_cdf": rc,
            "coverage": {m: {k: (n, inside / n, err / n) for k, (n, inside, err) in v.items()} for m, v in rep.items()}}


def zone_persistence(data: dict, targets=(2024, 2025)) -> dict:
    """How often the zone of "Mon parcours" (all-series reading: latest access rate, pooled mention
    share, Wilson margin) was confirmed by the next campaign alone, per (zone, uncertain)."""
    out = defaultdict(lambda: [0, 0])
    for t in targets:
        for lid, years in data.items():
            if t not in years or (t - 1) not in years:
                continue
            hist = [s for s in sorted(years) if s < t]
            prev, nxt = years[t - 1], years[t]
            if prev["taux"] is None or nxt["taux"] is None:
                continue
            for m in MENTIONS:
                k = sum(sum(years[s]["counts"][x] for x in J.MENTIONS[: J.MENTIONS.index(m) + 1]) for s in hist)
                n = sum(sum(years[s]["counts"][x] for x in J.MENTIONS) for s in hist)
                if not n:
                    continue
                lo, hi = J.wilson(k, n)
                z = J.classify_zone(prev["taux"], k / n, lo, hi)
                obs, _ = cdf_of([nxt["counts"]], m)
                if obs is None:
                    continue
                key = (z["zone"], bool(z["uncertain"]))
                out[key][0] += 1
                out[key][1] += J._zone(nxt["taux"], obs) == z["zone"]
    return {k: (n, c / n) for k, (n, c) in out.items() if n}


def build_calibration(con) -> dict:
    """mart.forecast (next campaign, per formation and mention), mart.calibration_report and
    mart.zone_persistence. Returns the hold-out coverage."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    data = load(con)
    latest = max((s for y in data.values() for s in y), default=None)
    con.execute("""CREATE OR REPLACE TABLE mart.forecast (lineage_id VARCHAR, cod_aff_form VARCHAR, target INTEGER,
        mention VARCHAR, taux_hat DOUBLE, taux_lo DOUBLE, taux_hi DOUBLE, taux_stratum VARCHAR, cdf_hat DOUBLE,
        cdf_lo DOUBLE, cdf_hi DOUBLE, cdf_stratum VARCHAR, known_hist DOUBLE, n_hist INTEGER, predictor VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE mart.calibration_report (phase VARCHAR, metric VARCHAR, stratum VARCHAR,
        target INTEGER, n INTEGER, coverage DOUBLE, mae DOUBLE, q_lo DOUBLE, q_hi DOUBLE, predictor VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE mart.zone_persistence (zone VARCHAR, uncertain BOOLEAN, n INTEGER, rate DOUBLE)""")
    if latest is None or latest < HOLDOUT or not any(len(y) > 1 for y in data.values()):
        return {}
    predictor, mae = choose_predictor(data)
    bt = backtest(data, predictor)
    rows = []
    for metric in ("taux", "cdf"):
        rr = bt[f"ranges_{metric}"]
        for st, (n, cov, err) in bt["coverage"][metric].items():
            lo, hi, _, _ = pick(rr, st)
            rows.append(("holdout", metric, st, HOLDOUT, n, cov, err, lo, hi, predictor))
    for p, v in mae.items():
        rows.append(("predictor", "taux", p, CALIBRATION_TARGETS[-1], None, None, v, None, None, predictor))
    # ranges served for the next campaign: the errors of every transition, the hold-out included
    te, ce = [], []
    for t in (*CALIBRATION_TARGETS, HOLDOUT):
        a, b = errors(data, t, predictor)
        te += a
        ce += b
    rt, rc = ranges(te), ranges(ce)
    for metric, rr in (("taux", rt), ("cdf", rc)):
        for st, (lo, hi, n) in rr.items():
            rows.append(("serving", metric, st, latest + 1, n, None, None, lo, hi, predictor))
    con.executemany("INSERT INTO mart.calibration_report VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    fc = []
    for lid, years in data.items():
        if latest not in years:
            continue                  # a formation absent from the latest campaign gets no forecast
        hist = sorted(years)
        th = [years[s]["taux"] for s in hist if years[s]["taux"] is not None]
        cur = years[latest]
        if th:
            st_t = taux_stratum(cur["selective"], len(th))
            t_hat = taux_point(th, predictor)
            lo, hi, _, used_t = pick(rt, st_t)
            t_lo, t_hi = max(0.0, t_hat + lo), min(100.0, t_hat + hi)
        else:
            t_hat = t_lo = t_hi = used_t = None
        for m in MENTIONS:
            c_hat, known = cdf_of([years[s]["counts"] for s in hist], m)
            if c_hat is not None:
                lo, hi, _, used_c = pick(rc, size_bucket(known))
                c_lo, c_hi = max(0.0, c_hat + lo), min(1.0, c_hat + hi)
            else:
                c_lo = c_hi = used_c = None
            fc.append((lid, cur["cod"], latest + 1, m, t_hat, t_lo, t_hi, used_t, c_hat, c_lo, c_hi, used_c, known, len(hist), predictor))
    con.executemany("INSERT INTO mart.forecast VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", fc)
    zp = zone_persistence(data)
    con.executemany("INSERT INTO mart.zone_persistence VALUES (?, ?, ?, ?)", [(z, u, n, r) for (z, u), (n, r) in zp.items()])
    return {m: bt["coverage"][m]["*"] for m in ("taux", "cdf")}


# --------------------------------------------------------------------------- serving
ZONES_WITH_REPERE = ("securite", "cible", "ambitieux", "hors_profil")


def summary(con) -> dict | None:
    """Hold-out coverage and target campaign, for the page header."""
    try:
        rows = con.execute("""SELECT metric, coverage, n FROM mart.calibration_report
                              WHERE phase = 'holdout' AND stratum = '*'""").fetchall()
        target = con.execute("SELECT max(target) FROM mart.forecast").fetchone()[0]
    except Exception:  # noqa: BLE001 - warehouse built before sprint 5
        return None
    if not rows or target is None:
        return None
    cov = {m: {"coverage": c, "n": n} for m, c, n in rows}
    return {"level": LEVEL, "target": target, "holdout": HOLDOUT, "coverage": cov}


def attach(con, res: dict, mention: str) -> dict:
    """Adds to each stage-2 formation its 'repere' (next-campaign ranges for the student's mention)
    and the confirmation rate of its zone; adds the hold-out summary to the response."""
    head = summary(con)
    res["calibration"] = head
    if head is None:
        return res
    cods = [f["cod_aff_form"] for f in res.get("formations", [])]
    fc = {}
    if cods:
        q = ", ".join("?" * len(cods))
        for r in con.execute(f"""SELECT cod_aff_form, taux_hat, taux_lo, taux_hi, cdf_hat, cdf_lo, cdf_hi, n_hist
                                 FROM mart.forecast WHERE mention = ? AND cod_aff_form IN ({q})""", [mention, *cods]).fetchall():
            fc[r[0]] = dict(zip(("taux_hat", "taux_lo", "taux_hi", "cdf_hat", "cdf_lo", "cdf_hi", "n_hist"), r[1:]))
    zp = {(z, u): (n, rate) for z, u, n, rate in con.execute("SELECT zone, uncertain, n, rate FROM mart.zone_persistence").fetchall()}
    for f in res.get("formations", []):
        r = fc.get(f["cod_aff_form"])
        if r is None or f.get("zone") not in ZONES_WITH_REPERE:
            f["repere"] = None
            continue
        n, rate = zp.get((f["zone"], bool(f.get("uncertain"))), (None, None))
        f["repere"] = {**r, "zone_confirmed": rate, "zone_n": n}
    return res
