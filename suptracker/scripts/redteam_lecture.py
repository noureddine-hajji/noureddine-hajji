"""Red team of sprint R6 (owner, 2026-11-12): the student's average stays in the browser.

    python scripts/redteam_lecture.py [--db data/suptracker.duckdb] [--real] [--browser]

The page now sends the mention BAND only and reads the zones inside the band itself, from the counts every answer carries
(`lec`). The server's own R5 reading with `moyenne` (unchanged, still served) is the ORACLE every twin is compared with.

  LE1 the ingredients: every row's `lec` (admits with a known mention, up to the band, in the band; per campaign the series
      bounds of the band and of the band below; the closed and fragile flags) re-derived from an independent SQL read of the
      lineage; invariants (kb <= kt <= n, bounds ordered, the band below never above the band)
  LE2 stage 2 twin (Node): for real types, the three series and a grid of averages (every band, its edges, the rattrapage with
      and without an average), the page's reading of the band answer = the server's reading with the average: zone and
      "incertain" exactly, every share, interval, series bound, position and trend within 1e-9, the repère reduced to the
      access-rate range; no average = the answer untouched
  LE3 Plan B twin: for targets in every zone, averages, an académie or none, paid on or off: status, reason, target, every
      alternative in order (zone, why, position, bounds, km), the counts
  LE4 Mes vœux twin: lists of up to 10 codes (absent and unsituated codes included): every row and the list's reading;
      read_list = readList on random zone lists
  LE5 Compléter twin: the page asks only when its own reading finds no sure safety (= the server's `needed`), and then gets the
      server's suggestions, in order, per filière, with the hidden paid count
  LE6 the map and the API: the map's zones read here = the server's; the band answers (stage 2, Plan B pool, map lectures) stay
      shared-cached, an answer read for an average is still never cached, the pool answers are plain JSON
  LE7 wiring and wording: no page query carries the average except the search (its own builder, used once); every page that
      shows a zone goes through the twin; the privacy text, the method text, README and CLAUDE.md say it
  LE8 browser (--browser / --real): a profile with an average; Mes vœux, a formation page, "Où je me situe" and the map: no JS
      error and no request carrying the average (the search aside)
  LE9 mutation test of LE1-LE7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import calibration as CAL  # noqa: E402
from suptracker import carte as CA  # noqa: E402
from suptracker import journey as J  # noqa: E402
from suptracker import planb as PB  # noqa: E402
from suptracker import voeux as VX  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
TOL = 1e-9
GRID = (8.0, 9.2, 9.9, 10.0, 11.0, 11.9, 12.0, 12.6, 13.0, 13.9, 14.4, 15.3, 16.0, 17.2, 18.0, 19.0, 20.0)
GRID_SHORT = (9.2, 11.0, 12.6, 13.9, 15.3, 17.2)
TWINS = ("MENTION_CODES", "BANDS", "BAND_SIGMA", "validMoyenne", "bandOf", "erf", "withinBand", "bandParam", "localAverage",
         "vxProfile", "ZONE_RULES", "MIN_BOUNDS_N", "ZONE_RANK", "SAME_ZONE_ACCESS_GAIN", "VX_SITUATED", "wilsonCI", "zoneOf",
         "isNum", "classifyZone", "seriesPos", "lire", "relire", "relireVue", "lectureOf", "stage2Local", "readList", "voeuxLocal",
         "pbUsable", "whyBetter", "pbOrder", "capPerEtab", "POOL_KEYS", "unpool", "planBLocal", "completerLocal", "carteZonesLocal")
DISPATCH = r"""
const F = { stage2Local, voeuxLocal, planBLocal, completerLocal, carteZonesLocal, readList, seriesPos };
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", () => {
  const cases = JSON.parse(raw), out = [];
  for (const c of cases) { try { out.push(F[c.fn](...c.args)); } catch (e) { out.push({ __error__: String(e && e.stack || e) }); } }
  process.stdout.write(JSON.stringify(out));
});
"""


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        end = js.find("\n};", m.start())
        if end != -1 and js[m.start():one].count("{") > js[m.start():one].count("}"):
            return js[m.start(): end + 3]
        return js[m.start(): one]
    return js[m.start(): js.find("\n}", m.start()) + 2]


def twin_prog(js: str) -> str:
    return "\n".join(top(js, n) for n in TWINS) + DISPATCH


def run_node(js: str, cases: list[dict]):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", twin_prog(js)], input=json.dumps(cases, default=float), capture_output=True, text=True,
                       timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


def jsonable(o):
    """The answer as the page receives it (JSON: tuples become lists, ints stay ints)."""
    return json.loads(json.dumps(o, default=float))


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.quick = False
        self._memo = {}

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]


def sample_types(c: Ctx, n: int) -> list[str]:
    rows = c.con.execute("""SELECT r.spe_type_key, count(*) FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        WHERE t.session = ? AND r.spe_type_key IS NOT NULL GROUP BY 1 ORDER BY hash(r.spe_type_key)""", [c.latest]).fetchall()
    mid = [k for k, k_n in rows if 20 <= k_n <= 300]
    return (mid or [k for k, _ in sorted(rows, key=lambda r: -r[1])])[:n]


def special_types(c: Ctx) -> list[str]:
    """Types the random sample may miss: one with a formation closed to bac général, one with a fragile bac techno rate."""
    def build():
        cur = c.con.cursor()
        tks = [r[0] for r in cur.execute("""SELECT DISTINCT r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r
            USING (rule_id) WHERE t.session = ? AND r.spe_type_key IS NOT NULL ORDER BY hash(r.spe_type_key)""", [c.latest]).fetchall()]
        out = []
        for serie, dkey, flag in (("bg", "MATHS+SES", "ferme"), ("bt", None, "fragile")):
            for tk in tks:
                rows = J.stage2(cur, dkey, "ab", tk, None, serie=serie)["formations"]
                if 2 <= len(rows) <= 400 and any(f["lec"][flag] for f in rows) and any(f["zone"] in ("cible", "securite", "ambitieux") for f in rows):
                    out.append(tk)
                    break
        return out
    return c.memo("special", build)


def profiles(grid) -> list[tuple[dict, str, float | None, float | None]]:
    """(page profile, band the server reads, average the server reads, average echoed)."""
    out = [({"mention": "rattrapage", "moyenne": None}, "sansmention", 10.0, None)]
    for g in grid:
        band = J.band_of(g)
        out.append(({"mention": "ab", "moyenne": g}, band, g, g))
    return out


SERIES = (("bg", "MATHS+SES"), ("bt", None), ("bp", None))


def answer(con, dkey, band, tk, serie, moyenne, academie=None, public=True):
    """What /api/journey/stage2 serves (stage2 + calibration + public rounding), without the HTTP layer. The ORACLE is read
    unrounded (public=False): the page computes from exact counts, the public rounding (6 decimals) is not its error."""
    res = J.stage2(con, dkey, band, tk, academie, serie=serie, moyenne=moyenne)
    CAL.attach(con, res, band, continuous=moyenne is not None)
    return jsonable(J.public_stage2(res) if public else res)


def close(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    return a == b


ROW_KEYS = ("zone", "uncertain", "cdf", "cdf_ci", "spos", "position", "repere")


def diff_rows(js_rows, py_rows, keys, key="cod_aff_form"):
    bad = []
    J_ = {f[key]: f for f in js_rows}
    if set(J_) != {f[key] for f in py_rows}:
        return [("rows differ", sorted(set(J_) ^ {f[key] for f in py_rows})[:5])]
    def tie(f, sp):
        """`projected` (the all-series share outside the series bounds) is a strict comparison: when the share sits ON a bound
        (a degenerate interval, ~1e-16 apart), the page's erf (1e-15 from Python's) may tip it; anything else must agree."""
        c = f.get("cdf")
        return sp and c is not None and min(abs(c - sp["bounds"][0]), abs(c - sp["bounds"][1])) < 1e-12

    for f in py_rows:
        g = J_[f[key]]
        for k in keys:
            a, b = g.get(k), f.get(k)
            if k == "spos" and tie(f, b) and isinstance(a, dict):
                a, b = {**a, "projected": None}, {**b, "projected": None}
            if not close(a, b):
                bad.append((f[key], k, a, b))
                break
        if True:                                                   # every row's trend, re-read per campaign
            tj, tp = g.get("trend") or [], f.get("trend") or []
            if len(tj) != len(tp) or any(not close(a.get("cdf"), b.get("cdf")) for a, b in zip(tj, tp)):
                bad.append((f[key], "trend", [a.get("cdf") for a in tj], [b.get("cdf") for b in tp]))
    return bad


# ------------------------------------------------------------------ LE1 the ingredients
def lec_ok(c: Ctx, stage2=None) -> tuple[bool, str]:
    stage2 = stage2 or J.stage2
    cur = c.con.cursor()
    bad, n_rows = [], 0
    for tk in sample_types(c, 3 if c.quick else 6):
        for serie, dkey in SERIES:
            for band in ("sansmention", "ab", "tb"):
                res = stage2(cur, dkey, band, tk, None, serie=serie)
                upto = J.MENTIONS[: J.MENTIONS.index(band) + 1]
                for f in res["formations"][: 12 if c.quick else 40]:
                    n_rows += 1
                    L = f["lec"]
                    camps = cur.execute(f"""SELECT fy.session, {' + '.join(f'coalesce(fy.acc_{m},0)' for m in J.MENTIONS)},
                          {' + '.join(f'coalesce(fy.acc_{m},0)' for m in upto)}, coalesce(fy.acc_{band},0),
                          {{{', '.join(f"'{k}': fy.{k}" for k in J.BG_KEYS)}}}
                        FROM core.lineage l0 JOIN core.lineage l ON l.lineage_id = l0.lineage_id
                        JOIN core.formation_year fy ON fy.session = l.session AND fy.cod_aff_form = l.cod_aff_form
                        WHERE l0.session = ? AND l0.cod_aff_form = ? ORDER BY fy.session""", [c.latest, f["cod_aff_form"]]).fetchall()
                    n, kt, kb = (sum(x[i] for x in camps) for i in (1, 2, 3))
                    prev = J.MENTIONS[J.MENTIONS.index(band) - 1] if band != "sansmention" else None
                    s = []
                    for x in camps:
                        b = J.series_cdf_bounds(serie, band, x[4])
                        if b is None:
                            continue
                        p = J.series_cdf_bounds(serie, prev, x[4]) if prev else (0, 0)
                        s.append([b[0], b[1], None if p is None else p[0], None if p is None else p[1], x[4][f"acc_{serie}"]])
                    want = {"n": n, "kt": kt, "kb": kb, "s": s, "ferme": f["zone"] == "non_ouvert",
                            "fragile": bool(f.get("rate_fragile"))}
                    if jsonable(L) != jsonable(want):
                        bad.append((tk, serie, band, f["cod_aff_form"], L, want))
                    elif not (0 <= kb <= kt <= n) or any(not (0 <= a <= b_ <= g) for a, b_, *_, g in s) \
                            or any(p0 is not None and (p0 > a or p1 > b_) for a, b_, p0, p1, _ in s):
                        bad.append((tk, serie, band, f["cod_aff_form"], "invariants", L))
                    for t in f["trend"]:
                        if t["n"] and abs(t["cdf"] - t["kt"] / t["n"]) > TOL:
                            bad.append((f["cod_aff_form"], "trend counts", t))
                            break
                    if len(bad) > 3:
                        return False, f"{n_rows} rows; problems {bad[:3]}"
    return not bad and n_rows > 0, f"{n_rows} rows re-derived; problems {bad[:3]}"


@check("LE1 ingredients: every row's counts and per-campaign series bounds re-derived from an independent read; invariants")
def le1(c: Ctx):
    return lec_ok(c)


# ------------------------------------------------------------------ LE2 stage 2
def stage2_cases(c: Ctx, band_answer=answer):
    def build():
        cur = c.con.cursor()
        cases, oracles = [], []
        for tk in dict.fromkeys(sample_types(c, 2 if c.quick else 5) + special_types(c)):
            for serie, dkey in SERIES:
                grid = GRID_SHORT if (c.quick or serie != "bg") else GRID
                for prof, band, g, given in profiles(grid):
                    p = {"serie": serie, "spe1": "MATHS", "spe2": "SES", **prof}
                    oracles.append((tk, serie, prof, answer(cur, dkey, band, tk, serie, g, public=False), given))
                    cases.append((tk, serie, dkey, band, p))
        return cases, oracles
    cases, oracles = c.memo(("s2", c.quick), build)
    cur = c.con.cursor()
    bands = {}
    node_cases = []
    for tk, serie, dkey, band, p in cases:
        k = (tk, serie, band)
        if k not in bands:
            bands[k] = band_answer(cur, dkey, band, tk, serie, None)
        node_cases.append({"fn": "stage2Local", "args": [bands[k], p]})
    return node_cases, oracles, bands


def scripted_bounds(js: str) -> list:
    """series_position itself (journey.py) on scripted campaigns, some without the band below (never seen in the published
    data, so the rule that leaves them out when mixing is checked here) = the page's seriesPos."""
    rng = random.Random(3)
    cases = []
    for _ in range(300):
        s = []
        for _ in range(rng.randint(1, 4)):
            g = rng.randint(0, 60)
            b0 = rng.randint(0, g); b1 = rng.randint(b0, g)
            p = None if rng.random() < 0.25 else (rng.randint(0, b0), None)
            if p is not None:
                p = (p[0], rng.randint(p[0], b1))
            s.append([b0, b1, None if p is None else p[0], None if p is None else p[1], g])
        cases.append((s, rng.choice([0.0, 0.3, 0.7, 0.999, 1.0]), rng.choice([None, rng.random()])))
    saved = J.series_cdf_bounds
    want = []
    try:
        for s, w, cdf in cases:
            J.series_cdf_bounds = lambda serie, m, camp: ((camp["b0"], camp["b1"]) if m == "ab"
                                                          else None if camp["p0"] is None else (camp["p0"], camp["p1"]))
            margins = [{"b0": b0, "b1": b1, "p0": p0, "p1": p1, "acc_bg": g} for b0, b1, p0, p1, g in s]
            want.append(jsonable(J.series_position("bg", "ab", margins, cdf, w)))
    finally:
        J.series_cdf_bounds = saved
    got = run_node(js, [{"fn": "seriesPos", "args": [s, w, cdf]} for s, w, cdf in cases])
    return [(cases[i], got[i], want[i]) for i in range(len(cases)) if not close(got[i], want[i])]


def stage2_ok(c: Ctx, js: str, band_answer=answer) -> tuple[bool, str]:
    node_cases, oracles, bands = stage2_cases(c, band_answer)
    out = run_node(js, node_cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad, n_rows, zones = [], 0, set()
    bad += [("scripted series bounds", *x) for x in scripted_bounds(js)[:2]]
    for got, (tk, serie, prof, want, given) in zip(out, oracles):
        if "__error__" in got:
            return False, got["__error__"][:400]
        n_rows += len(want["formations"])
        zones |= {f["zone"] for f in want["formations"]}
        if got.get("moyenne") != given:
            bad.append((tk, serie, prof, "the average echoed", got.get("moyenne"), given))
        bad += [(tk, serie, prof, *x) for x in diff_rows(got["formations"], want["formations"], ROW_KEYS)][:2]
        if len(bad) > 3:
            break
    # no average: the answer is used as it came
    plain = run_node(js, [{"fn": "stage2Local", "args": [a, {"serie": k[1], "spe1": "MATHS", "spe2": "SES", "mention": k[2]}]}
                          for k, a in list(bands.items())[:6]])
    if plain and any(p != a for p, a in zip(plain, list(bands.values())[:6])):
        bad.append("an answer without an average was re-read")
    ok = not bad and n_rows > 0 and len(zones & {"securite", "cible", "ambitieux"}) >= 2
    return ok, f"{len(oracles)} answers, {n_rows} rows compared, zones seen {sorted(zones)}; problems {bad[:3]}"


@check("LE2 stage 2 twin: the page's reading of the band answer = the server's reading with the average (every zone, share, bound, trend)")
def le2(c: Ctx):
    return stage2_ok(c, c.js)


# ------------------------------------------------------------------ LE3 Plan B
def planb_targets(c: Ctx) -> list[tuple[str, str, str | None]]:
    def build():
        cur = c.con.cursor()
        out = []
        for tk in sample_types(c, 3 if c.quick else 6):
            res = J.stage2(cur, "MATHS+SES", "ab", tk, None, moyenne=12.6)
            seen = set()
            for f in sorted(res["formations"], key=lambda f: PB._tiebreak(f["cod_aff_form"])):
                if f["zone"] not in seen and f["zone"] in ("ambitieux", "cible", "hors_profil", "securite"):
                    seen.add(f["zone"])
                    out.append((f["cod_aff_form"], tk, f["academie"]))
        return out[: 6 if c.quick else 18]
    return c.memo(("pbt", c.quick), build)


PB_KEYS = ("status", "reason", "n_candidates", "hidden_paid", "include_paid")
VIEW_KEYS = ("cod_aff_form", "zone", "uncertain", "position", "bounds", "why", "km", "paid", "taux_acces_ens")


def amplified(fn):
    """Stage 2 with every formation cloned twice: one clone in the same establishment (the cap of 2 per establishment), in
    another académie and a little further; one fee-charging (the paid filter). The clones keep the original's counts, so the
    oracle (read with the average) and the pool see the same, larger, field: the order, the caps and the paid filter are
    exercised even on the small synthetic warehouse."""
    def stage2(con, *a, **k):
        res = fn(con, *a, **k)
        out = []
        for f in res["formations"]:
            out.append(f)
            out.append({**f, "cod_aff_form": f["cod_aff_form"] + "1", "academie": "Académie témoin",
                        "lat": (f["lat"] or 46.0) + 0.05, "lon": (f["lon"] or 2.0) + 0.05})
            out.append({**f, "cod_aff_form": f["cod_aff_form"] + "2", "contrat_etab": "Privé hors contrat",
                        "lat": (f["lat"] or 46.0) - 0.02, "lon": f["lon"]})                 # third in its establishment
        return {**res, "formations": out}
    return stage2


def planb_ok(c: Ctx, js: str, plan_b=PB.plan_b) -> tuple[bool, str]:
    cur = c.con.cursor()
    cases, oracles = [], []
    targets = planb_targets(c)
    passes = [(False, t) for t in targets] + [(True, t) for t in (targets if c.quick else targets[:6])]
    for i, (amp, (cod, tk, acad)) in enumerate(passes):
        grid = (GRID_SHORT if c.quick else (9.2, 11.0, 12.6, 13.9, 15.3, 17.2))[: 3 if amp else None]
        saved = J.stage2
        if amp:
            J.stage2 = amplified(saved)
        try:
            for prof, band, g, given in profiles(grid):
                academie = ("Académie témoin" if amp else acad) if i % 2 else None
                paid = bool(i % 3 == 0)
                want = c.memo(("pb", amp, cod, band, g, academie, paid),
                              lambda: jsonable(PB.plan_b(cur, cod, dkey="MATHS+SES", mention=band, academie=academie, include_paid=paid, moyenne=g)))
                pool = jsonable(plan_b(cur, cod, dkey="MATHS+SES", mention=band, academie=academie, include_paid=paid, pool=True))
                p = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", **prof}
                cases.append({"fn": "planBLocal", "args": [pool, p, academie]})
                oracles.append((cod, prof, academie, paid, want))
        finally:
            J.stage2 = saved
    out = run_node(js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad, statuses, n_alt = [], {}, 0
    for got, (cod, prof, academie, paid, want) in zip(out, oracles):
        if "__error__" in got:
            return False, got["__error__"][:400]
        statuses[want["status"]] = statuses.get(want["status"], 0) + 1
        n_alt += len(want["alternatives"])
        for k in PB_KEYS:
            if k in want and not close(got.get(k), want[k]):
                bad.append((cod, prof, academie, paid, k, got.get(k), want[k]))
        if want["target"] and any(not close(got["target"].get(k), want["target"].get(k)) for k in VIEW_KEYS if k != "why"):
            bad.append((cod, prof, "target", {k: got["target"].get(k) for k in VIEW_KEYS}, {k: want["target"].get(k) for k in VIEW_KEYS}))
        ga, wa = got.get("alternatives") or [], want["alternatives"]
        if len(ga) != len(wa) or any(not close(x.get(k), y.get(k)) for x, y in zip(ga, wa) for k in VIEW_KEYS):
            bad.append((cod, prof, academie, paid, "alternatives", [x.get("cod_aff_form") for x in ga], [y["cod_aff_form"] for y in wa]))
        if len(bad) > 3:
            break
    ok = not bad and len(statuses) >= 2 and n_alt > 0
    return ok, f"{len(oracles)} Plan B answers, statuses {statuses}, {n_alt} alternatives compared; problems {bad[:3]}"


@check("LE3 Plan B twin: status, target and every alternative in order, for averages, an académie or none, paid on or off")
def le3(c: Ctx):
    return planb_ok(c, c.js)


# ------------------------------------------------------------------ LE4 / LE5 Mes vœux and Compléter
def lists(c: Ctx) -> list[list[str]]:
    def build():
        cur = c.con.cursor()
        rng = random.Random(6)
        out = []
        for tk in sample_types(c, 3 if c.quick else 6):
            res = J.stage2(cur, "MATHS+SES", "ab", tk, None)
            cods = sorted(f["cod_aff_form"] for f in res["formations"])
            amb = [f["cod_aff_form"] for f in res["formations"] if f["zone"] in ("ambitieux", "hors_profil", "cible")]
            if cods:
                out.append(rng.sample(cods, min(len(cods), rng.randint(3, 10))))
            if amb:
                out.append(sorted(amb)[:4])                                  # no sure safety: Compléter runs
        if out:
            out.append(out[0][:3] + ["999999999"])                          # an absent code
        return out[: 6 if c.quick else 14]
    return c.memo(("lists", c.quick), build)


VX_ROW = ("status", "zone", "uncertain", "position", "bounds", "position_moyenne")


def voeux_ok(c: Ctx, js: str, evaluate=VX.evaluate) -> tuple[bool, str]:
    cur = c.con.cursor()
    cases, oracles = [], []
    for i, ids in enumerate(lists(c)):
        for prof, band, g, given in profiles(GRID_SHORT if c.quick else (9.2, 11.0, 12.6, 13.9, 15.3, 17.2, 19.0)):
            academie = "Paris" if i % 2 else None
            want = c.memo(("vx", tuple(ids), band, g, academie),
                          lambda: jsonable(VX.evaluate(cur, ids, dkey="MATHS+SES", mention=band, academie=academie, moyenne=g)))
            got_band = jsonable(evaluate(cur, ids, dkey="MATHS+SES", mention=band, academie=academie))
            p = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "academie": academie, **prof}
            cases.append({"fn": "voeuxLocal", "args": [got_band, p]})
            oracles.append((ids, prof, want))
    # read_list on random zone lists (the rules alone)
    rng = random.Random(11)
    zl = []
    for _ in range(200):
        vx = [{"status": rng.choice(["ok", "ok", "ok", "absente"]), "zone": rng.choice([*VX.SITUATED, "indetermine", "non_ouvert", None]),
               "uncertain": rng.random() < 0.3} for _ in range(rng.randint(0, 10))]
        zl.append(vx)
    out = run_node(js, cases + [{"fn": "readList", "args": [v]} for v in zl])
    if out is None:
        return True, "skipped (node not installed)"
    bad, n_rows, needed = [], 0, 0
    for got, (ids, prof, want) in zip(out, oracles):
        if "__error__" in got:
            return False, got["__error__"][:400]
        n_rows += len(want["voeux"])
        needed += any(m["code"] == "aucune_securite" for m in want["lecture"]["messages"])
        if got["lecture"] != want["lecture"]:
            bad.append((ids, prof, "reading", got["lecture"], want["lecture"]))
        for a, b in zip(got["voeux"], want["voeux"]):
            if a.get("cod_aff_form") != b.get("cod_aff_form") or any(not close(a.get(k), b.get(k)) for k in VX_ROW):
                bad.append((ids, prof, b.get("cod_aff_form"), {k: a.get(k) for k in VX_ROW}, {k: b.get(k) for k in VX_ROW}))
                break
        if got.get("moyenne") != (prof["moyenne"]):
            bad.append((prof, "the average echoed", got.get("moyenne")))
        if len(bad) > 3:
            break
    for got, vx in zip(out[len(cases):], zl):
        want = jsonable(VX.read_list(vx))
        if got != want:
            bad.append(("read_list", vx, got, want))
            break
    ok = not bad and n_rows > 0 and needed > 0
    return ok, f"{len(oracles)} lists x averages ({n_rows} rows, {needed} without a sure safety), {len(zl)} random readings; problems {bad[:3]}"


@check("LE4 Mes vœux twin: every row and the list's reading, for lists of up to 10 codes; read_list = readList")
def le4(c: Ctx):
    return voeux_ok(c, c.js)


def completer_ok(c: Ctx, js: str, completer=VX.completer) -> tuple[bool, str]:
    cur = c.con.cursor()
    cases, oracles = [], []
    for i, ids in enumerate(lists(c)):
        for prof, band, g, given in profiles(GRID_SHORT if c.quick else (9.2, 11.0, 12.6, 13.9, 15.3, 17.2)):
            academie = "Paris" if i % 2 else None
            paid = bool(i % 3 == 0)
            want = c.memo(("cp", tuple(ids), band, g, academie, paid),
                          lambda: jsonable(VX.completer(cur, ids, dkey="MATHS+SES", mention=band, academie=academie, include_paid=paid, moyenne=g)))
            vx = c.memo(("vxb", tuple(ids), band, academie), lambda: jsonable(VX.evaluate(cur, ids, dkey="MATHS+SES", mention=band, academie=academie)))
            pool = jsonable(completer(cur, ids, dkey="MATHS+SES", mention=band, academie=academie, include_paid=paid, pool=True))
            p = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "academie": academie, **prof}
            cases += [{"fn": "voeuxLocal", "args": [vx, p]}, {"fn": "completerLocal", "args": [pool, p, academie]}]
            oracles.append((ids, prof, academie, paid, want))
    out = run_node(js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad, n_needed, n_sugg = [], 0, 0
    for k, (ids, prof, academie, paid, want) in enumerate(oracles):
        vx, got = out[2 * k], out[2 * k + 1]
        if "__error__" in vx or "__error__" in got:
            return False, str(vx.get("__error__") or got.get("__error__"))[:400]
        needed = any(m["code"] == "aucune_securite" for m in vx["lecture"]["messages"])
        if needed != want["needed"]:
            bad.append((ids, prof, "asks when the server would not (or the reverse)", needed, want["needed"]))
            continue
        if not needed:
            continue
        n_needed += 1
        if got.get("hidden_paid") != want["hidden_paid"]:
            bad.append((ids, prof, paid, "hidden paid", got.get("hidden_paid"), want["hidden_paid"]))
        gf, wf = got.get("filieres") or [], want["filieres"]
        if [f["filiere"] for f in gf] != [f["filiere"] for f in wf]:
            bad.append((ids, prof, "filières", [f["filiere"] for f in gf], [f["filiere"] for f in wf]))
        for a, b in zip(gf, wf):
            n_sugg += len(b["formations"])
            if a["n_candidates"] != b["n_candidates"] or len(a["formations"]) != len(b["formations"]) or any(
                    not close(x.get(k), y.get(k)) for x, y in zip(a["formations"], b["formations"]) for k in VIEW_KEYS):
                bad.append((ids, prof, academie, paid, b["filiere"], [x.get("cod_aff_form") for x in a["formations"]],
                            [y["cod_aff_form"] for y in b["formations"]], a["n_candidates"], b["n_candidates"]))
        if len(bad) > 3:
            break
    ok = not bad and n_needed > 0 and n_sugg > 0
    return ok, f"{len(oracles)} lists x averages, {n_needed} needing suggestions, {n_sugg} suggestions compared; problems {bad[:3]}"


@check("LE5 Compléter twin: asked only when the page's reading finds no sure safety; the same suggestions in the same order")
def le5(c: Ctx):
    return completer_ok(c, c.js)


# ------------------------------------------------------------------ LE6 the map and the API
def carte_ok(c: Ctx, js: str, zones=CA.zones) -> tuple[bool, str]:
    cur = c.con.cursor()
    dips = [d["label"] for d in CA.facets(cur)["diplomes"]][:3] if hasattr(CA, "facets") else ["BTS", "BUT"]
    cases, oracles = [], []
    for dip in dips:
        for serie, dkey in SERIES[:2]:
            for prof, band, g, given in profiles((9.2, 12.6, 15.3) if c.quick else (9.2, 11.0, 12.6, 13.9, 15.3, 17.2)):
                want = c.memo(("cz", dip, serie, band, g), lambda: jsonable(CA.zones(cur, dip, None, dkey, band, serie, g)))
                lec = jsonable(zones(cur, dip, None, dkey, band, serie, None, lecture=True))
                cases.append({"fn": "carteZonesLocal", "args": [lec, {"serie": serie, "spe1": "MATHS", "spe2": "SES", **prof}]})
                oracles.append((dip, serie, prof, want))
    out = run_node(js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad, n = [], 0
    for got, (dip, serie, prof, want) in zip(out, oracles):
        n += len(want["zones"])
        if got.get("zones") != want["zones"]:
            diff = [k for k in want["zones"] if (got.get("zones") or {}).get(k) != want["zones"][k]][:3]
            bad.append((dip, serie, prof, diff))
    return not bad and n > 0, f"{len(oracles)} map answers, {n} zones compared; problems {bad[:3]}"


def api_ok(c: Ctx) -> tuple[bool, str]:
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved = os.environ.get("SUPTRACKER_DB"), A.record
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    bad = []
    try:
        tc = TestClient(api.app)
        cod, tk, _ = planb_targets(c)[0]
        prof = "spe1=MATHS&spe2=SES&serie=bg"
        pub = lambda r: "no-store" not in r.headers.get("cache-control", "") and r.status_code == 200  # noqa: E731
        for url, cached in ((f"/api/journey/stage2?mention=ab&type={tk}&{prof}", True),
                            (f"/api/planb/{cod}?mention=ab&{prof}&pool=true", True),
                            (f"/api/carte/zones?diplome=BTS&mention_bac=ab&{prof}&lecture=true", True),
                            (f"/api/journey/stage2?mention=ab&moyenne=12.6&type={tk}&{prof}", False),
                            (f"/api/voeux/completer?ids={cod}&mention=ab&{prof}&pool=true", False),
                            (f"/api/voeux?ids={cod}&mention=ab&{prof}", False)):
            r = tc.get(url)
            if r.status_code != 200 or pub(r) != cached:
                bad.append((url, r.status_code, r.headers.get("cache-control")))
        r = tc.get(f"/api/planb/{cod}?mention=ab&{prof}&pool=true").json()
        if r.get("status") not in ("pool", "non_disponible") or (r["status"] == "pool" and not all("lec" in x and "tb" in x for x in r["candidates"])):
            bad.append(("Plan B pool", r.get("status")))
        z = tc.get(f"/api/carte/zones?diplome=BTS&mention_bac=ab&{prof}&lecture=true").json()
        if set(z.get("lectures", {})) != set(z.get("zones", {})):
            bad.append("map lectures do not cover its zones")
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()
    return not bad, f"problems {bad[:3]}"


@check("LE6 the map and the API: the map's zones read here = the server's; band answers stay shared-cached, an average never")
def le6(c: Ctx):
    ok1, d1 = carte_ok(c, c.js)
    ok2, d2 = api_ok(c)
    return ok1 and ok2, f"{d1}; API {d2}"


# ------------------------------------------------------------------ LE7 wiring and wording
ANCHORS = ("this.data = voeuxLocal(d, prof)",
           "try { d = voeuxLocal(await api(`/api/voeux?${qs}`), prof); }",
           "d = zoned ? voeuxLocal(await api(`/api/voeux?${vxQuery(ids, prof)}`), prof)",
           "stage2Local(await api(`/api/journey/stage2?",
           "if (local) d = planBLocal(d, pbProf, prof.academie || null);",
           "if (local) d = completerLocal(d, prof, prof.academie || null);",
           "&lecture=true\" : \"\"}`).then((z) => carteZonesLocal(z, VP))",
           'if (local) q.set("pool", "true");', 'if (local) qs.set("pool", "true");')


def wiring_ok(js: str, api_src: str, readme: str, claude: str) -> tuple[bool, str]:
    bad = []
    mp = top(js, "mentionParams")
    if "moyenne" in mp or "bandParam(p)" not in mp:
        bad.append(("mentionParams sends the average or the raw mention", mp))
    if top(js, "bandParam").count('"sansmention"') != 1:
        bad.append("the rattrapage is not sent as its band")
    sets = [m.start() for m in re.finditer(r'qs\.set\("moyenne"', js)]
    ms = js.find("function mentionParamsSearch(")
    if len(sets) != 1 or not (ms < sets[0] < js.find("\n}", ms)):
        bad.append(("an average set outside the search's builder", len(sets)))
    if js.count("mentionParamsSearch(") != 2 or "qs.set(\"serie\", v.serie); mentionParamsSearch(qs, v);" not in js:
        bad.append("the search's builder used elsewhere")
    if re.search(r"moyenne=\$\{|&moyenne=|moyenne: (?:p|v|prof|VP)\.moyenne", js):
        bad.append(("a query string carries the average", re.findall(r".{30}moyenne=\$\{.{20}|.{30}&moyenne=.{20}", js)[:2]))
    for a in ANCHORS:
        if a not in js:
            bad.append(("a page reads a zone without the twin", a[:60]))
    if "sauf votre moyenne : elle reste dans ce navigateur" not in js:
        bad.append("the Mes vœux privacy text")
    from suptracker import api as API
    meth = API.METHODOLOGY.get("moyenne", "")
    if "Votre moyenne reste dans votre navigateur" not in meth or "Seule la recherche filtrée par zone l'envoie" not in meth:
        bad.append("the method text does not say where the average is read")
    if "Sprint R6" not in readme or "R6" not in claude or "redteam_lecture" not in claude:
        bad.append("README / CLAUDE.md")
    return not bad, f"{len(ANCHORS)} anchors; problems {bad[:4]}"


@check("LE7 wiring and wording: no query carries the average but the search; every zone goes through the twin; the texts say it")
def le7(c: Ctx):
    return wiring_ok(c.js, c.api_src, c.readme, c.claude)


# ------------------------------------------------------------------ LE8 browser
BROWSER = r"""
const { chromium } = require('playwright');
const base = process.argv[2], cod = process.argv[3];
(async () => {
  const b = await chromium.launch(); const errs = [], reqs = []; const o = {};
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.addInitScript((c) => { localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6, statut: "terminale" })); localStorage.setItem("voeux", JSON.stringify([c])); }, cod);
  const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message)); p.on("request", (r) => { if (r.url().includes("/api/")) reqs.push(r.url()); });
  await p.goto(base + "/#/voeux"); await p.waitForTimeout(4000);
  o.voeux = await p.evaluate(() => document.body.innerText.includes("Admis sous votre moyenne (estimation)"));
  await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(4000);
  o.tile = await p.evaluate(() => !!document.querySelector(".zbadge, .zone-pill, [data-zone]"));
  await p.goto(base + "/#/carte/BTS"); await p.waitForTimeout(5000);
  process.stdout.write(JSON.stringify({ errs, reqs, o })); await b.close();
})();
"""


@check("LE8 browser: a profile with an average reads Mes vœux, a formation page and the map without sending it")
def le8(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    cod = planb_targets(c)[0][0]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".lecture_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    d = json.loads(r.stdout)
    leaked = [u for u in d["reqs"] if "moyenne" in u and "/api/search" not in u]
    bad = []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if leaked:
        bad.append(("a request carries the average", leaked[:2]))
    if not d["o"]["voeux"]:
        bad.append("Mes vœux does not read the average")
    if not any("/api/voeux" in u for u in d["reqs"]) or not any("lecture=true" in u for u in d["reqs"]):
        bad.append(("the pages did not ask", d["reqs"][:5]))
    return not bad, f"{len(d['reqs'])} API requests, none with the average; {d['o']}; problems {bad[:3]}"


# ------------------------------------------------------------------ LE9 mutation test
def js_mutants():
    return [
        ("the band's full share whatever the average", "const k = L.kt - (1 - ww) * L.kb,", "const k = L.kt,", "s2"),
        ("the uniform hypothesis never checked", "uncertain = classifyZone(taux, u.cz, u.ciz[0], u.ciz[1]).zone !== zone;", "uncertain = uncertain;", "s2"),
        ("a closed formation read", 'L.ferme ? { zone: "non_ouvert", uncertain: false } :', "", "s2"),
        ("a fragile rate read", 'if (L.fragile && zone !== "non_ouvert") { zone = "indetermine"; uncertain = true; }', "", "s2"),
        ("the band below never mixed", "if (w < 1) {\n      if (p0", "if (w < 0) {\n      if (p0", "s2"),
        ("a campaign without the band below kept", "      if (p0 === null || p0 === undefined) continue;\n", "", "s2"),
        ("Wilson at 90 %", "const z = 1.959964;", "const z = 1.644854;", "s2"),
        ("a looser erf", "if (Math.abs(add) < 1e-17 * Math.abs(sum)) break;", "if (Math.abs(add) < 1e-6 * Math.abs(sum)) break;", "s2"),
        ("the series bounds below 10 admits", "if (g < MIN_BOUNDS_N) return null;", "if (g < 1) return null;", "s2"),
        ("the trend not re-read", "cdf: t.n ? (t.kt - (1 - r.w) * t.kb) / t.n : null", "cdf: t.cdf", "s2"),
        ("the repère's share range kept", "cdf_hat: null, cdf_lo: null, cdf_hi: null, zone_confirmed: null,", "zone_confirmed: null,", "s2"),
        ("the rattrapage read at the band's top", 'p.mention === "rattrapage" ? 10 : null', "null", "s2"),
        ("the target's own zone kept for Plan B", "const t = relireVue(d.target, band, g);", "const t = d.target;", "pb"),
        ("a same-zone formation proposed without the access gain", "c.taux_acces_ens >= (t.taux_acces_ens || 0) + SAME_ZONE_ACCESS_GAIN",
         "c.taux_acces_ens >= (t.taux_acces_ens || 0)", "pb"),
        ("an uncertain better zone accepted", "if (zc > zt && !c.uncertain) return \"zone\";", "if (zc > zt) return \"zone\";", "pb"),
        ("paid formations shown", "if (why && c.paid && !d.include_paid) { hidden += 1; continue; }", "", "pb"),
        ("the académie not first", "academie && c.academie === academie ? 0 : 1,", "0,", "pb"),
        ("three per establishment", "if ((per.get(k) || 0) >= MAX_PER_ETABLISSEMENT) continue;", "if ((per.get(k) || 0) >= 3) continue;", "pb"),
        ("the better zone not preferred", "withZone ? -ZONE_RANK[c.zone] : 0", "0", "pb"),
        ("an uncertain safety suggested", 'c.zone !== "securite" || c.uncertain) continue;', 'c.zone !== "securite") continue;', "cp"),
        ("a list with an uncertain safety called safe", 'const sure = vx.filter((v) => v.zone === "securite" && !v.uncertain).length;',
         'const sure = vx.filter((v) => v.zone === "securite").length;', "vx"),
        ("the majority rule with >=", "n.ambitieux + n.hors_profil > situated / 2", "n.ambitieux + n.hors_profil >= situated / 2", "vx"),
        ("the list's reading not redone", "return { ...d, moyenne: given, voeux: vx, lecture: readList(vx) };", "return { ...d, moyenne: given, voeux: vx };", "vx"),
        ("the map's zones kept from the band", "zones[cod] = lire(x.lec, x.taux_acces_ens, band, g).zone;", "zones[cod] = x.zone;", "map"),
        ("the average sent again", '  qs.set("mention", bandParam(p));\n  return qs;',
         '  qs.set("mention", bandParam(p));\n  if (p.moyenne !== null && p.moyenne !== undefined) qs.set("moyenne", String(p.moyenne));\n  return qs;', "wire"),
        ("the raw rattrapage sent", 'function bandParam(p) { return p.mention === "rattrapage" ? "sansmention" : p.mention; }',
         "function bandParam(p) { return p.mention; }", "wire"),
        ("the map asks the server with the average", '${localAverage(VP) !== null ? "&lecture=true" : ""}', '${VP.moyenne !== null ? `&moyenne=${VP.moyenne}` : ""}', "wire"),
        ("Mes vœux shown as the server read the band", "try { d = voeuxLocal(await api(`/api/voeux?${qs}`), prof); }", "try { d = await api(`/api/voeux?${qs}`); }", "wire"),
    ]


def py_mutants(c: Ctx):
    """Bugs on the server side of the twin, applied as wrappers (the oracle, read with the average, is left intact)."""
    def bad_lec(fn):
        def stage2(con, *a, **k):
            res = fn(con, *a, **k)
            if k.get("moyenne") is None:
                for f in res["formations"]:
                    f["lec"] = {**f["lec"], "kb": 0}
            return res
        return stage2

    def lec_no_prev(fn):
        def stage2(con, *a, **k):
            res = fn(con, *a, **k)
            if k.get("moyenne") is None:
                for f in res["formations"]:
                    f["lec"] = {**f["lec"], "s": [[b0, b1, 0, 0, g] for b0, b1, _, _, g in f["lec"]["s"]]}
            return res
        return stage2

    def answer_drop_ferme(con, dkey, band, tk, serie, moyenne, academie=None):
        a = answer(con, dkey, band, tk, serie, moyenne, academie)
        for f in a["formations"]:
            f["lec"]["ferme"] = False
        return a

    def pool_band_filtered(fn):
        def plan_b(con, cod, **k):
            r = fn(con, cod, **k)
            if r.get("status") == "pool":          # the pool cut with the band's reading (the zones the average may change)
                r["candidates"] = [x for x in r["candidates"] if x["zone"] == "securite"]
            return r
        return plan_b

    def completer_drop(fn):
        def completer(con, ids, **k):
            r = fn(con, ids, **k)
            for f in r.get("filieres", []):
                f["candidates"] = [x for x in f.get("candidates", []) if not x.get("paid")][:1]
            return r
        return completer

    return [
        ("the band's own admits not sent", "s2", lambda: ("stage2", bad_lec(J.stage2))),
        ("the band below not sent", "s2", lambda: ("stage2", lec_no_prev(J.stage2))),
        ("the closed flag dropped", "s2", lambda: ("answer", answer_drop_ferme)),
        ("Plan B's pool cut with the band's reading", "pb", lambda: ("plan_b", pool_band_filtered(PB.plan_b))),
        ("Compléter's pool cut", "cp", lambda: ("completer", completer_drop(VX.completer))),
    ]


def run_group(c: Ctx, group: str, js: str, stage2=None, answer_fn=None, plan_b=None, completer=None) -> bool:
    if group == "s2":
        if stage2 is not None:
            ok1 = lec_ok(c, stage2)[0]
            saved = J.stage2
            J.stage2 = stage2
            try:
                ok2 = stage2_ok(c, js)[0]
            finally:
                J.stage2 = saved
            return ok1 and ok2
        return stage2_ok(c, js, answer_fn or answer)[0]
    if group == "pb":
        return planb_ok(c, js, plan_b or PB.plan_b)[0]
    if group == "cp":
        return completer_ok(c, js, completer or VX.completer)[0]
    if group == "vx":
        return voeux_ok(c, js)[0]
    if group == "map":
        return carte_ok(c, js)[0]
    if group == "wire":
        return wiring_ok(js, c.api_src, c.readme, c.claude)[0]
    raise KeyError(group)


@check("LE9 mutation test: twin, pool, reading, map and wiring bugs are each caught")
def le9(c: Ctx):
    if not shutil.which("node"):
        return True, "skipped (node not installed)"
    c.quick = True
    missed, n = [], 0
    try:
        for name, old, new, group in js_mutants():
            n += 1
            if c.js.count(old) != 1:
                missed.append(f"{name} (anchor {c.js.count(old)})")
                continue
            try:
                caught = not run_group(c, group, c.js.replace(old, new, 1))
            except Exception:  # noqa: BLE001
                caught = True
            if not caught:
                missed.append(name)
        for name, group, make in py_mutants(c):
            n += 1
            kind, fn = make()
            try:
                caught = not run_group(c, group, c.js, **{{"stage2": "stage2", "answer": "answer_fn", "plan_b": "plan_b",
                                                          "completer": "completer"}[kind]: fn})
            except Exception:  # noqa: BLE001
                caught = True
            if not caught:
                missed.append(name)
    finally:
        c.quick = False
    return not missed, f"{n - len(missed)}/{n} mutants caught; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    c.con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
