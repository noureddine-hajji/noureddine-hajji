"""Next-campaign forecast (n+1) of every published indicator with a history, back-tested, never a probability.

The owner asked for the 2026 forecast of the access rate, of the share of terminales générales among
the candidates called in the main phase and of the number of admits, extended to every indicator that
has 3 to 4 campaigns of history. The method is the sprint-5 "repère", generalised:

* the formation (lineage) needs at least MIN_HIST campaigns with a value before the target;
* point forecast: last campaign, mean of the last two or mean of all, the one with the lowest error
  on the calibration year (2024), chosen per indicator;
* 80 % range: the point plus the 10th and 90th percentiles of the errors per stratum (size of the
  last campaign x campaigns of history), additive in points for rates, multiplicative for counts
  (log((y + 1) / (hat + 1)), so a range scales with the formation);
* hold-out: the same method, set on 2024, forecasts 2025 without seeing it; the share of 2025 values
  inside their range is published per indicator, as measured. The ranges served for the next campaign
  use the errors of 2024 and 2025.

The access rate is not re-forecast: its range is sprint 5's (mart.forecast), so "Mon parcours" and the
formation page show the same numbers. The admits' shares (pct_*) of a zero-admit campaign are 0 % by
convention, not observed shares: those campaigns are ignored for them.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import calibration as CAL

LEVEL = CAL.LEVEL
Q_LO, Q_HI = CAL.Q_LO, CAL.Q_HI
CALIBRATION_TARGET = 2024
HOLDOUT = CAL.HOLDOUT
MIN_HIST = 2                       # campaigns with a value before the target
MIN_STRATUM = CAL.MIN_STRATUM
PREDICTORS = CAL.PREDICTORS
EPS = 1e-9                         # float guard for values on a range bound
FRAGILE = 0.75                     # hold-out coverage below this: the page flags the range as less reliable

# (column, kind, group). Rates are in points (0-100); counts are people or vœux.
INDICATORS = (
    ("taux_acces_ens", "taux", "acces"),
    ("part_terminale_generale_en_position_admis_pp", "taux", "acces"),
    ("part_terminale_techno_en_position_admis_pp", "taux", "acces"),
    ("part_terminale_pro_en_position_admis_pp", "taux", "acces"),
    ("acc_tot", "effectif", "volumes"),
    ("capa_fin", "effectif", "volumes"),
    ("voe_tot", "effectif", "volumes"),
    ("nb_voe_pp", "effectif", "volumes"),
    ("nb_cla_pp", "effectif", "volumes"),
    ("prop_tot", "effectif", "volumes"),
    ("acc_bg", "effectif", "volumes"),
    ("acc_bt", "effectif", "volumes"),
    ("acc_bp", "effectif", "volumes"),
    ("acc_brs", "effectif", "volumes"),
    ("pct_bg", "taux", "admis"),
    ("pct_bt", "taux", "admis"),
    ("pct_bp", "taux", "admis"),
    ("pct_bours", "taux", "admis"),
    ("pct_f", "taux", "admis"),
    ("pct_neobac", "taux", "admis"),
    ("pct_aca_orig", "taux", "admis"),
    ("pct_etab_orig", "taux", "admis"),
    ("pct_sansmention", "taux", "admis"),
    ("pct_ab", "taux", "admis"),
    ("pct_b", "taux", "admis"),
    ("pct_tb", "taux", "admis"),
    ("pct_tbf", "taux", "admis"),
    ("pct_acc_debutpp", "taux", "admis"),
    ("pct_acc_datebac", "taux", "admis"),
    ("pct_acc_finpp", "taux", "admis"),
)
KIND = {c: k for c, k, _ in INDICATORS}
GROUP = {c: g for c, _, g in INDICATORS}
FROM_SPRINT5 = "taux_acces_ens"
PREVISION_COLS = ("cod_aff_form", "lineage_id", "target", "indicator", "last_session", "last_value", "hat", "lo", "hi",
                  "stratum", "n_hist", "predictor")
REPORT_COLS = ("indicator", "kind", "predictor", "target", "holdout", "n", "coverage", "mae", "naive_mae")


ERR = lambda e: e[1]               # noqa: E731 - the error in an errors() tuple


def admits_share(col: str) -> bool:
    return col.startswith("pct_")


def raw_rows(con) -> list[tuple]:
    """(lineage_id, session, cod_aff_form, acc_tot, *the INDICATORS in order)."""
    cols = [c for c, _, _ in INDICATORS]
    return con.execute(f"""SELECT l.lineage_id, fy.session, fy.cod_aff_form, fy.acc_tot, {', '.join('fy.' + c for c in cols)}
                           FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)""").fetchall()


def load(con) -> dict:
    return from_rows(raw_rows(con))


def from_rows(rows) -> dict:
    """{lineage_id: {session: {"cod", "n" (admits), col: value}}}."""
    cols = [c for c, _, _ in INDICATORS]
    out = defaultdict(dict)
    for lid, s, cod, n, *v in rows:
        d = dict(zip(cols, v))
        if not n:
            for c in cols:
                if admits_share(c):
                    d[c] = None          # 0 % by convention in a zero-admit campaign, not an observed share
        d["cod"], d["n"] = cod, n
        out[lid][s] = d
    return out


def stratum(n_last, n_hist: int) -> str:
    return f"{CAL.size_bucket(n_last)} · {min(n_hist, 3)}{'+' if n_hist >= 3 else ''} campagnes"


def point(hist: list[float], predictor: str) -> float:
    return CAL.taux_point(hist, predictor)


def error(kind: str, obs: float, hat: float) -> float:
    return math.log((obs + 1) / (max(hat, 0.0) + 1)) if kind == "effectif" else obs - hat


def bounds(kind: str, hat: float, lo: float, hi: float) -> tuple[float, float]:
    if kind == "effectif":
        # whole people or vœux, rounded outwards (1e-9 guard: an exact integer is not pushed out by float noise)
        return max(0.0, math.floor((hat + 1) * math.exp(lo) - 1 + 1e-9)), max(0.0, math.ceil((hat + 1) * math.exp(hi) - 1 - 1e-9))
    return max(0.0, hat + lo), min(100.0, hat + hi)


def history(years: dict, col: str, target: int) -> tuple[list[float], float | None]:
    """The values before `target` (in order) and the admits of the last campaign before it."""
    past = [s for s in sorted(years) if s < target]
    vals = [years[s][col] for s in past if years[s][col] is not None]
    return vals, (years[past[-1]]["n"] if past else None)


def errors(data: dict, col: str, target: int, predictor: str) -> list[tuple[str, float, float, float]]:
    """(stratum, error, observed value, point forecast) of forecasting `target` from the campaigns before it."""
    kind, out = KIND[col], []
    for years in data.values():
        if target not in years or years[target][col] is None:
            continue
        vals, n_last = history(years, col, target)
        if len(vals) < MIN_HIST:
            continue
        hat = point(vals, predictor)
        out.append((stratum(n_last, len(vals)), error(kind, years[target][col], hat), years[target][col], hat))
    return out


def choose_predictor(data: dict, col: str) -> str:
    mae = {}
    for p in PREDICTORS:
        es = errors(data, col, CALIBRATION_TARGET, p)
        mae[p] = sum(abs(e[1]) for e in es) / len(es) if es else float("inf")
    return min(PREDICTORS, key=lambda p: (mae[p], PREDICTORS.index(p)))


def holdout(data: dict, col: str, predictor: str) -> dict:
    """Ranges set on the calibration year, applied to the hold-out year never seen."""
    kind = KIND[col]
    rr = CAL.ranges(errors(data, col, CALIBRATION_TARGET, predictor), val=ERR)
    ho = errors(data, col, HOLDOUT, predictor)
    if not ho or "*" not in rr:
        return {"n": 0, "coverage": None, "mae": None, "naive_mae": None}
    inside = 0
    for st, _, obs, hat in ho:
        lo, hi, _, _ = CAL.pick(rr, st)
        inside += covered(kind, obs, hat, lo, hi)
    naive = errors(data, col, HOLDOUT, "derniere")
    return {"n": len(ho), "coverage": inside / len(ho), "mae": sum(abs(e[1]) for e in ho) / len(ho),
            "naive_mae": sum(abs(e[1]) for e in naive) / len(naive) if naive else None}


def covered(kind: str, obs: float, hat: float, lo: float, hi: float) -> bool:
    """Is the observed value inside the range the page SHOWS (counts rounded outwards, rates clipped)? A value on a
    bound is inside; EPS guards float noise."""
    b_lo, b_hi = bounds(kind, hat, lo, hi)
    return b_lo - EPS <= obs <= b_hi + EPS


def compute(data: dict, latest: int) -> tuple[list, list]:
    """(forecast rows, report rows) of every indicator but the access rate, for the campaign after `latest`."""
    target, rows, rep = latest + 1, [], []
    for col, kind, _ in INDICATORS:
        if col == FROM_SPRINT5:
            continue
        pred = choose_predictor(data, col)
        h = holdout(data, col, pred)
        rep.append((col, kind, pred, target, HOLDOUT, h["n"], h["coverage"], h["mae"], h["naive_mae"]))
        rr = CAL.ranges(errors(data, col, CALIBRATION_TARGET, pred) + errors(data, col, HOLDOUT, pred), val=ERR)
        if "*" not in rr:
            continue
        for lid, years in data.items():
            if latest not in years:
                continue                  # a formation absent from the latest campaign gets no forecast
            vals, n_last = history(years, col, target)
            if len(vals) < MIN_HIST or years[latest][col] is None:
                continue
            st = stratum(n_last, len(vals))
            hat = point(vals, pred)
            lo, hi, _, used = CAL.pick(rr, st)
            b_lo, b_hi = bounds(kind, hat, lo, hi)
            rows.append((years[latest]["cod"], lid, target, col, latest, years[latest][col], hat, b_lo, b_hi, used, len(vals), pred))
    return rows, rep


def build(con) -> dict:
    """mart.prevision (one row per current formation x indicator) and mart.prevision_report (per indicator:
    predictor, hold-out coverage and errors). Returns {indicator: coverage}."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    con.execute("""CREATE OR REPLACE TABLE mart.prevision (cod_aff_form VARCHAR, lineage_id VARCHAR, target INTEGER,
        indicator VARCHAR, last_session INTEGER, last_value DOUBLE, hat DOUBLE, lo DOUBLE, hi DOUBLE, stratum VARCHAR,
        n_hist INTEGER, predictor VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE mart.prevision_report (indicator VARCHAR, kind VARCHAR, predictor VARCHAR,
        target INTEGER, holdout INTEGER, n INTEGER, coverage DOUBLE, mae DOUBLE, naive_mae DOUBLE)""")
    data = load(con)
    latest = max((s for y in data.values() for s in y), default=None)
    if latest is None or latest < HOLDOUT:
        return {}
    rows, rep = compute(data, latest)
    out = {r[0]: r[6] for r in rep}
    target = latest + 1
    # the access rate: sprint 5's ranges, so both pages agree (same campaign count rule as the other indicators)
    # sprint 5's n_hist counts campaigns, with or without a published rate: count the published rates here
    n_rates = {lid: sum(1 for y in years.values() if y[FROM_SPRINT5] is not None) for lid, years in data.items()}
    for r in con.execute("""SELECT DISTINCT f.cod_aff_form, f.lineage_id, f.target, fy.session, fy.taux_acces_ens, f.taux_hat,
                                   f.taux_lo, f.taux_hi, f.taux_stratum, f.predictor
                            FROM mart.forecast f JOIN core.formation_year fy ON fy.cod_aff_form = f.cod_aff_form AND fy.session = f.target - 1
                            WHERE f.taux_hat IS NOT NULL AND fy.taux_acces_ens IS NOT NULL""").fetchall():
        cod, lid, tg, s, last, hat, lo, hi, st, pred = r
        n = n_rates.get(lid, 0)
        if n >= MIN_HIST:
            rows.append((cod, lid, tg, FROM_SPRINT5, s, last, hat, lo, hi, st, n, pred))
    cov = con.execute("""SELECT n, coverage, mae, predictor FROM mart.calibration_report
                         WHERE phase = 'holdout' AND metric = 'taux' AND stratum = '*'""").fetchall()
    cov = cov[0] if cov else None
    if cov:
        rep.append((FROM_SPRINT5, "taux", cov[3], target, HOLDOUT, cov[0], cov[1], cov[2], None))
        out[FROM_SPRINT5] = cov[1]
    import pandas as pd             # ~350k rows: executemany is far too slow, a registered frame is not
    for table, data_rows, cols in (("prevision", rows, PREVISION_COLS), ("prevision_report", rep, REPORT_COLS)):
        if data_rows:
            con.register("_pv", pd.DataFrame(data_rows, columns=cols))
            con.execute(f"INSERT INTO mart.{table} SELECT * FROM _pv")
            con.unregister("_pv")
    return out


# --------------------------------------------------------------------------- serving
def for_formation(con, cod: str, session: int | None) -> dict | None:
    """The n+1 ranges of a formation page, only when the page shows the latest campaign."""
    try:
        rows = con.execute("""SELECT p.indicator, p.target, p.last_session, p.last_value, p.hat, p.lo, p.hi, p.n_hist,
                                     r.coverage, r.n AS holdout_n
                              FROM mart.prevision p JOIN mart.prevision_report r USING (indicator)
                              WHERE p.cod_aff_form = ?""", [cod]).fetchall()
    except Exception:  # noqa: BLE001 - warehouse built before this feature
        return None
    if not rows or (session is not None and session != rows[0][2]):
        return None
    order = [c for c, _, _ in INDICATORS]
    items = []
    for ind, tg, s, last, hat, lo, hi, n, cov, hn in sorted(rows, key=lambda r: order.index(r[0])):
        items.append({"indicator": ind, "kind": KIND[ind], "group": GROUP[ind], "last": last, "hat": hat, "lo": lo, "hi": hi,
                      "n_hist": n, "coverage": cov, "holdout_n": hn, "fragile": cov is not None and cov < FRAGILE})
    return {"target": rows[0][1], "last_session": rows[0][2], "level": LEVEL, "holdout": HOLDOUT,
            "calibration": CALIBRATION_TARGET, "indicators": items}
