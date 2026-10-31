"""Red team of A3: the position of a bac-général student's mention among bac-général admits.

SIES does not publish the mention x series table, only its margins, so the share is partially
identified (journey.bg_cdf_bounds). These checks attack the mathematics (validity, sharpness,
degenerate and inconsistent cases), the real-data premises, and the presentation.

    python scripts/redteam_mentions.py --db data/suptracker.duckdb [--real]
"""
from __future__ import annotations

import argparse
import itertools
import random
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import journey as J  # noqa: E402

LADDER = ("sansmention", "ab", "b", "tb", "tbf")
SERIES = ("bg", "bt", "bp")
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def margins(table: dict, unknown: dict) -> dict:
    """Published SIES margins of a full table. table[s][m] = admits of series s with mention m
    (unknown-mention admits are in `unknown[s]`, with their hidden true mention irrelevant here)."""
    c = {f"acc_{m}": sum(table[s][m] for s in SERIES) for m in LADDER}
    c["acc_mention_non_renseignee"] = sum(unknown[s] for s in SERIES)
    for s in SERIES:
        c[f"acc_{s}"] = sum(table[s].values()) + unknown[s]
    for s in SERIES:
        c[f"acc_{s}_mention"] = sum(table[s][m] for m in LADDER[1:])
    return c


def truth_range(table: dict, unknown: dict, mention: str) -> tuple[int, int]:
    """True K for this table: the hidden mentions of unknown-mention admits can be anything."""
    k = sum(table["bg"][m] for m in LADDER[: LADDER.index(mention) + 1])
    return k, k + unknown["bg"]


def random_table(rng: random.Random, scale: int) -> tuple[dict, dict]:
    t = {s: {m: rng.randint(0, scale) * (rng.random() < 0.8) for m in LADDER} for s in SERIES}
    u = {s: rng.randint(0, max(1, scale // 4)) * (rng.random() < 0.3) for s in SERIES}
    return t, u


@check("M1 validity: the true share is inside the bounds for every table (30,000 random tables)")
def m1(con, real):
    rng = random.Random(1)
    bad = 0
    for i in range(30_000):
        t, u = random_table(rng, rng.choice((2, 5, 30, 300)))
        c = margins(t, u)
        for m in LADDER[:4]:
            b = J.bg_cdf_bounds(m, c)
            if b is None:
                continue
            lo_t, hi_t = truth_range(t, u, m)
            if not (b[0] <= lo_t and hi_t <= b[1]):
                bad += 1
    return bad == 0, f"{bad} violation(s)"


def all_bg_rows(c: dict):
    """Every bac-général row (counts by mention, plus unknown) consistent with the margins."""
    g, gm = c["acc_bg"], c["acc_bg_mention"]
    om = c["acc_bt_mention"] + c["acc_bp_mention"]
    cols = [c[f"acc_{m}"] for m in LADDER] + [c["acc_mention_non_renseignee"]]
    for row in itertools.product(*(range(x + 1) for x in cols)):
        if sum(row) != g or sum(row[1:5]) != gm:
            continue
        if sum(cols[1:5]) - sum(row[1:5]) != om:      # the other series hold the remaining mentions
            continue
        yield row


@check("M2 sharpness: on small tables, brute force over every consistent table reaches both bounds")
def m2(con, real):
    rng = random.Random(2)
    loose, tested = [], 0
    while tested < 400:
        t, u = random_table(rng, 2)
        c = margins(t, u)
        if c["acc_bg"] == 0 or sum(c[f"acc_{m}"] for m in LADDER) + c["acc_mention_non_renseignee"] > 12:
            continue
        tested += 1
        for m in LADDER[:4]:
            b = J.bg_cdf_bounds(m, c)
            rows = list(all_bg_rows(c))
            j = LADDER.index(m)
            ks = [(sum(r[: j + 1]), sum(r[: j + 1]) + r[5]) for r in rows]
            reach = (min(k[0] for k in ks), max(k[1] for k in ks))
            if b != reach:
                loose.append((c, m, b, reach))
    return not loose, f"{len(loose)} non-sharp case(s) {loose[:1]}" if loose else f"{tested} tables × 4 mentions: bounds = brute-force extremes"


@check("M3 degenerate case: a cohort of bacheliers généraux only gets the exact share, no interval")
def m3(con, real):
    c = {"acc_bg": 40, "acc_bt": 0, "acc_bp": 0, "acc_bg_mention": 30, "acc_bt_mention": 0, "acc_bp_mention": 0, "acc_sansmention": 10,
         "acc_ab": 12, "acc_b": 9, "acc_tb": 7, "acc_tbf": 2, "acc_mention_non_renseignee": 0}
    got = {m: J.bg_cdf_bounds(m, c) for m in LADDER[:4]}
    want = {"sansmention": (10, 10), "ab": (22, 22), "b": (31, 31), "tb": (38, 38)}
    return got == want, f"{got}"


@check("M4 inconsistent or missing margins never produce an interval")
def m4(con, real):
    base = {"acc_bg": 10, "acc_bt": 0, "acc_bp": 0, "acc_bg_mention": 5, "acc_bt_mention": 0, "acc_bp_mention": 0,
            "acc_sansmention": 5, "acc_ab": 5, "acc_b": 0, "acc_tb": 0, "acc_tbf": 0, "acc_mention_non_renseignee": 0}
    cases = [{**base, "acc_bg_mention": 11}, {**base, "acc_bt_mention": 9}, {**base, "acc_bg": 0},
             {**base, "acc_ab": None}, {**base, "acc_bg_mention": None},
             # more bac général without a mention than the ladder has (found by review on formation 29223)
             {**base, "acc_sansmention": 3},
             # other series: more admits holding a mention than admits
             {**base, "acc_bt_mention": 2, "acc_ab": 7, "acc_bt": 1, "acc_sansmention": 4}]
    out = [J.bg_cdf_bounds("ab", c) for c in cases]
    return all(o is None for o in out) and J.bg_cdf_bounds("ab", base) == (10, 10), f"{out}"


@check("M5 zones: a zone marked certain holds for every value of the widened interval")
def m5(con, real):
    rng = random.Random(5)
    bad = 0
    for _ in range(20_000):
        taux = rng.uniform(0, 100)
        lo = rng.random()
        hi = min(1.0, lo + rng.random() * 0.3)
        used = rng.uniform(lo, hi)
        z = J.classify_zone(taux, used, lo, hi)
        if not z["uncertain"]:
            grid = [lo + (hi - lo) * i / 50 for i in range(51)]
            if any(J._zone(taux, v) != z["zone"] for v in grid):
                bad += 1
    return bad == 0, f"{bad} certain zone(s) contradicted inside the interval"


@check("M12 pooling campaigns: per-campaign bounds are added (valid, and never wider than pooling the margins)")
def m12(con, real):
    rng = random.Random(12)
    bad_valid = wider = strictly = 0
    for _ in range(5_000):
        camps = [random_table(rng, rng.choice((3, 20))) for _ in range(rng.randint(2, 4))]
        ms = [margins(t, u) for t, u in camps]
        if sum(m["acc_bg"] for m in ms) < J.MIN_BG_FOR_BOUNDS:
            continue
        for m in LADDER[:4]:
            pos = J.bg_position(m, ms, None)
            if pos is None:
                continue
            g = sum(x["acc_bg"] for x in ms)
            lo_t = sum(truth_range(t, u, m)[0] for t, u in camps) / g
            hi_t = sum(truth_range(t, u, m)[1] for t, u in camps) / g
            if not (pos["bounds"][0] - 1e-12 <= lo_t and hi_t <= pos["bounds"][1] + 1e-12):
                bad_valid += 1
            # reference: sharp bounds of each campaign, ends added (campaigns are independent tables)
            per = [J.bg_cdf_bounds(m, x) for x in ms]
            keep = [(b, x) for b, x in zip(per, ms) if b is not None]
            gk = sum(x["acc_bg"] for _, x in keep)
            ref = (sum(b[0] for b, _ in keep) / gk, sum(b[1] for b, _ in keep) / gk) if gk else None
            if ref is None or abs(pos["bounds"][0] - ref[0]) > 1e-12 or abs(pos["bounds"][1] - ref[1]) > 1e-12:
                bad_valid += 1
            pooled = J.bg_cdf_bounds(m, {k: sum(x[k] for x in ms) for k in J.BG_KEYS})
            if pooled:
                plo, phi = pooled[0] / g, pooled[1] / g
                wider += pos["bounds"][0] < plo - 1e-12 or pos["bounds"][1] > phi + 1e-12
                strictly += pos["bounds"][0] > plo + 1e-12 or pos["bounds"][1] < phi - 1e-12
    return bad_valid == 0 and wider == 0, (f"{bad_valid} invalid or ≠ per-campaign reference, {wider} wider than pooled margins; "
                                           f"strictly tighter in {strictly} cases (constraints pooling would lose)")


@check("M11 a better mention never ranks lower: both bounds rise along the mention ladder")
def m11(con, real):
    rng = random.Random(11)
    bad = 0
    for _ in range(10_000):
        t, u = random_table(rng, rng.choice((3, 40)))
        c = margins(t, u)
        b = [J.bg_cdf_bounds(m, c) for m in LADDER[:4]]
        if any(x is None for x in b):
            continue
        bad += any(b[i][0] > b[i + 1][0] or b[i][1] > b[i + 1][1] for i in range(3))
    return bad == 0, f"{bad} non-monotone ladder(s)"


# ------------------------------------------------------------------ real-data premises
def _has(con, col):
    return con.execute("""SELECT count(*) FROM information_schema.columns
                          WHERE table_name = 'formation_year' AND column_name = ?""", [col]).fetchone()[0] > 0


@check("M6 premise: by-series mention counts add up to the all-series mentions (the bounds rest on it)")
def m6(con, real):
    if not _has(con, "acc_bg_mention"):
        return False, "warehouse has no acc_bg_mention"
    n, ok, ok_all = con.execute("""SELECT count(*), count(*) FILTER (WHERE acc_bg_mention + acc_bt_mention + acc_bp_mention
                                 = acc_ab + acc_b + acc_tb + acc_tbf),
        count(*) FILTER (WHERE acc_bg_mention + acc_bt_mention + acc_bp_mention = acc_ab + acc_b + acc_tb + acc_tbf
                           AND acc_bg + acc_bt + acc_bp - acc_bg_mention - acc_bt_mention - acc_bp_mention
                               = acc_sansmention + acc_mention_non_renseignee)
        FROM core.formation_year WHERE acc_bg_mention IS NOT NULL AND acc_ab IS NOT NULL""").fetchone()
    share = 100 * ok / n if n else 0
    return share >= 99, (f"mention half {ok}/{n} ({share:.2f} %); both halves {ok_all}/{n} "
                         f"({100 * ok_all / max(1, n):.2f} %); campaigns breaking either get no interval (M4)")


@check("M7 premise: acc_bg_mention <= acc_bg; pct_bg_mention is over acc_neobac (not acc_bg), as labelled")
def m7(con, real):
    if not _has(con, "acc_bg_mention"):
        return False, "warehouse has no acc_bg_mention"
    n, over, mism = con.execute("""SELECT count(*), count(*) FILTER (WHERE acc_bg_mention > acc_bg),
        count(*) FILTER (WHERE acc_neobac > 0 AND pct_bg_mention IS NOT NULL
                         AND abs(pct_bg_mention - 100.0 * acc_bg_mention / acc_neobac) > 1)
        FROM core.formation_year WHERE acc_bg_mention IS NOT NULL""").fetchone()
    from suptracker.schema import FIELD_BY_NAME
    label_ok = "ensemble des néo-bacheliers" in FIELD_BY_NAME["pct_bg_mention"].label
    return over == 0 and mism <= 0.01 * n and label_ok, \
        f"{over} rows with more mentions than admits, {mism}/{n} mismatches over acc_neobac, label {'ok' if label_ok else 'WRONG'}"


@check("M8 impact on real data: how often the bac-général view changes the reading (report)")
def m8(con, real):
    if not _has(con, "acc_bg_mention"):
        return False, "warehouse has no acc_bg_mention"
    types = [r[0] for r in con.execute("SELECT DISTINCT spe_type_key FROM core.taxonomy_rule ORDER BY 1").fetchall()]
    n = proj = narrow = moved = 0
    widths = []
    for t in types:
        for m in ("sansmention", "ab", "b"):
            res = J.stage2(con, "MATHS+SES", m, t)
            for f in res["formations"]:
                if not f["bg"] or f["zone"] == "non_ouvert":
                    continue
                n += 1
                widths.append(f["bg"]["width"])
                proj += f["bg"]["projected"]
                narrow += f["bg"]["width"] <= 0.05
                old = J.classify_zone(f["taux_acces_ens"], f["cdf"], *f["cdf_ci"])["zone"]
                moved += old != f["zone"]
    widths.sort()
    med = widths[len(widths) // 2] if widths else None
    ok = n > 0 if real else True
    return ok, (f"{n} formation × mention readings: all-series share outside the bac-général bounds in {proj} "
                f"({100 * proj / max(1, n):.1f} %), zone changed in {moved}; interval ≤ 5 pts in "
                f"{100 * narrow / max(1, n):.0f} %, median width {100 * (med or 0):.1f} pts")


# ------------------------------------------------------------------ presentation
@check("M9 the UI shows an interval, never a falsely precise number, and escapes what it prints")
def m9(con, real):
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    i = js.index("function bgCell")
    cell = js[i: i + 1200]
    ok = "bounds[0]" in cell and "bounds[1]" in cell and "tous bacs" in cell
    raw = re.findall(r"\$\{f\.bg\.[a-z_]+\}", js)
    return ok and not raw, f"interval rendering {'ok' if ok else 'missing'}; raw interpolations {raw}"


@check("M10 the method says what is known and what is not")
def m10(con, real):
    from suptracker.api import METHODOLOGY
    t = METHODOLOGY.get("journey_bg", "")
    ok = all(w in t for w in ("ne publie pas", "encadrement", "exact", "Wilson"))
    return ok, "methodology states the missing table, the exact interval and the sampling margin"


def run(db: Path, real: bool = False) -> list[dict]:
    con = duckdb.connect(str(db), read_only=True)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(con, real)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    con.close()
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
