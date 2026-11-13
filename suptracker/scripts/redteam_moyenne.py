"""Red team of sprint R5 (owner, 2026-11-12): the student's average places them INSIDE their mention band.

    python scripts/redteam_moyenne.py [--db data/suptracker.duckdb] [--real] [--browser]

  MO1 the model (Python): bands (sans mention 8-12 centred on 11, rattrapage at its bottom; AB 12-14 ... TBF 18-20), the
      within-band fraction re-derived by numerical integration of the truncated normal curve (sigma 1) and the uniform one: 0 at
      the floor, 1 at the top, increasing; band_of at every edge; resolve_mention (an average sets its band, a different mention
      or a rattrapage at 10 or more is an error, out of 8-20 is an error)
  MO2 twins (Node): bandOf, validMoyenne (comma, rounding to the tenth, bounds, junk), withinBand (erf within 1e-6 of Python),
      positionMoyenne on real mention counts = the Python formula
  MO3 stage 2 re-derived: for real types and averages, every row's share = (admits of the bands below + w x admits of the band) /
      known admits from an independent SQL read; the published bounds; the zone from the same reading; "uncertain" when the
      uniform hypothesis gives another zone; the share is continuous at every band edge and never decreases with the average;
      without an average the rows are those of the band's top (pre-R5 reading)
  MO4 the API: every route that reads a zone takes the average (stage 2, Plan B, Mes vœux, Compléter, the map, the search) and
      gives the SAME zone as stage 2 for the same formation; a mismatch, a rattrapage at 10+, 7.9 or 20.1 are 422; an answer read
      for an average is never shared-cached; the vocabulary serves the six bands; "sm" (the map's old code) reads "sans mention"
  MO5 the page (Node): the form draws the average (escaped), the list follows the average's band; reading the form keeps a valid
      average and drops a blank one; vxProfile lets the average set the band; the queries carry it; a shared list never carries
      it; the formation card: its range, "estimation", the published bounds, the rattrapage note, a small cohort flagged, never a
      chance, escaped
  MO6 wiring and wording: no query sends the raw stored mention; the map asks zones for every band (the "sm" bug); calibration
      keeps only the access-rate range with an average; method, glossary, README, CLAUDE.md
  MO7 browser (--browser / --real): set an average in "Mon profil", then "Où je me situe", "Mes vœux", a formation page and the
      map with a sans-mention profile: no JS error, the stored profile, the card, zones on the map
  MO8 mutation test of MO1-MO6 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import journey as J  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")
LADDER = ("sansmention", "ab", "b", "tb", "tbf")
WANT_BANDS = {"sansmention": (8, 12, 11), "ab": (12, 14, 13), "b": (14, 16, 15), "tb": (16, 18, 17), "tbf": (18, 20, 19)}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    spec = importlib.util.spec_from_loader(f"suptracker.{name}_mo", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "suptracker"
    sys.modules[spec.name] = mod
    exec(compile(src, f"{name}_mo.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.J = J
        self.j_src = (ROOT / "suptracker" / "journey.py").read_text()
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()
        self.cache_src = (ROOT / "suptracker" / "cache.py").read_text()
        self.cal_src = (ROOT / "suptracker" / "calibration.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


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


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return "__error__ " + r.stderr[-800:]
    return r.stdout


# ------------------------------------------------------------------ MO1 the model
def integ_normal(g: float, lo: float, hi: float, mid: float, sd: float = 1.0, steps: int = 4000) -> float:
    """The truncated normal CDF re-derived by Simpson integration of the density (independent of math.erf)."""
    pdf = lambda x: math.exp(-0.5 * ((x - mid) / sd) ** 2)  # noqa: E731

    def simpson(a, b):
        if b <= a:
            return 0.0
        h = (b - a) / steps
        s = pdf(a) + pdf(b) + sum((4 if i % 2 else 2) * pdf(a + i * h) for i in range(1, steps))
        return s * h / 3
    return simpson(lo, min(max(g, lo), hi)) / simpson(lo, hi)


def model_ok(Jm) -> tuple[bool, str]:
    bad = []
    if {m: tuple(v) for m, v in Jm.BANDS.items()} != WANT_BANDS or Jm.BAND_SIGMA != 1.0 or Jm.RATTRAPAGE_TOP != 10.0:
        bad.append(("bands", Jm.BANDS, Jm.BAND_SIGMA))
    for m, (lo, hi, mid) in WANT_BANDS.items():
        prev = -1.0
        for i in range(0, 41):
            g = lo + (hi - lo) * i / 40
            w, u = Jm.within(g, m), Jm.within(g, m, "uniforme")
            if abs(w - integ_normal(g, lo, hi, mid)) > 1e-6 or abs(u - (g - lo) / (hi - lo)) > 1e-9:
                bad.append((m, g, "within", w, u))
                break
            if w < prev - 1e-12:
                bad.append((m, g, "decreasing"))
                break
            prev = w
        if Jm.within(None, m) != 1.0:
            bad.append((m, "no average must read the band's top"))
    edges = {8: "sansmention", 9.99: "sansmention", 10: "sansmention", 11.99: "sansmention", 12: "ab", 13.99: "ab", 14: "b",
             16: "tb", 17.99: "tb", 18: "tbf", 20: "tbf"}
    for g, m in edges.items():
        if Jm.band_of(g) != m:
            bad.append(("band_of", g, Jm.band_of(g)))
    for g in (7.99, 20.01):
        try:
            Jm.band_of(g)
            bad.append(("band_of accepts", g))
        except ValueError:
            pass
    cases = [(("ab", 12.4), ("ab", 12.4)), ((None, 15.0), ("b", 15.0)), (("rattrapage", None), ("sansmention", 10.0)),
             (("rattrapage", 9.0), ("sansmention", 9.0)), (("tbf", None), ("tbf", None)), (("sansmention", None), ("sansmention", None))]
    for args, want in cases:
        try:
            got = Jm.resolve_mention(*args)
        except ValueError as exc:
            got = ("error", str(exc))
        if got != want:
            bad.append(("resolve", args, got))
    for args in (("b", 12.4), ("rattrapage", 10.0), ("rattrapage", 12.0), ("zz", None), (None, None)):
        try:
            Jm.resolve_mention(*args)
            bad.append(("resolve accepts", args))
        except ValueError:
            pass
    return not bad, f"5 bands, 41 points each; problems {bad[:4]}"


@check("MO1 the model: bands, the within-band fraction re-derived by integration, band_of at every edge, resolve_mention")
def mo1(c: Ctx):
    return model_ok(c.J)


# ------------------------------------------------------------------ MO2 twins
TWIN_PROG = r"""
const IN = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = { band: IN.grades.map(bandOf), valid: IN.raw.map(validMoyenne),
  within: IN.within.map(([g, m, model]) => withinBand(g, m, model)), pos: IN.pos.map(([c, g]) => positionMoyenne(c, g)) };
process.stdout.write(JSON.stringify(out));
"""


def mention_counts(con, n: int = 40) -> list[dict]:
    rows = con.execute(f"""SELECT {', '.join(f'acc_{m}' for m in LADDER)} FROM core.formation_year
        WHERE session = (SELECT max(session) FROM core.formation_year) AND acc_neobac >= 1 ORDER BY hash(cod_aff_form) LIMIT {n}""").fetchall()
    return [dict(zip(LADDER, (x or 0 for x in r))) for r in rows]


def py_position(counts: dict, g: float, Jm=J) -> dict | None:
    n = sum(counts.values())
    if not n:
        return None
    band = "sansmention" if g < 12 else Jm.band_of(g)
    below = sum(counts[m] for m in LADDER[:LADDER.index(band)])
    k = counts[band]
    return {"normale": (below + Jm.within(g, band) * k) / n, "uniforme": (below + Jm.within(g, band, "uniforme") * k) / n,
            "bornes": [below / n, (below + k) / n], "band": band, "n": n}


def twins_ok(js: str, con) -> tuple[bool, str]:
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const fmt = ",)))
    defs = [top(js, n) for n in ("BANDS", "BAND_SIGMA", "validMoyenne", "bandOf", "erf", "withinBand", "LADDER", "positionMoyenne")]
    grades = [8, 9.99, 10, 11.99, 12, 13.5, 14, 16, 17.99, 18, 20]
    raw = ["13,4", "13.44", " 15 ", "8", "20", "7.9", "20.1", "abc", "", None, "12,96", "1e1"]
    within = [(g, m, model) for m, (lo, hi, _) in WANT_BANDS.items() for g in (lo, (lo + hi) / 2 - 0.37, hi) for model in ("normale", "uniforme")]
    counts = mention_counts(con)
    pos = [(c, g) for c in counts[:20] for g in (9.0, 11.3, 12.6, 15.9, 18.5)]
    r = node("\n".join([helpers, *defs]) + TWIN_PROG, {"grades": grades, "raw": raw, "within": within, "pos": pos})
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    want_band = ["rattrapage" if g < 10 else J.band_of(g) for g in grades]
    if o["band"] != want_band:
        bad.append(("bandOf", o["band"]))
    if o["valid"] != [13.4, 13.4, 15, 8, 20, None, None, None, None, None, 13, 10]:
        bad.append(("validMoyenne", o["valid"]))
    for (g, m, model), v in zip(within, o["within"]):
        if abs(v - J.within(g, m, model)) > 1e-6:
            bad.append(("withinBand", g, m, model, v))
            break
    for (cts, g), v in zip(pos, o["pos"]):
        w = py_position(cts, g)
        if (w is None) != (v is None) or (w and any(abs(v[k] - w[k]) > 1e-6 for k in ("normale", "uniforme"))
                                          or w and (v["band"] != w["band"] or max(abs(a - b) for a, b in zip(v["bornes"], w["bornes"])) > 1e-12)):
            bad.append(("positionMoyenne", g, v, w))
            break
    return not bad, f"{len(grades)} grades, {len(raw)} inputs, {len(within)} fractions, {len(pos)} positions on real counts; problems {bad[:3]}"


@check("MO2 twins (Node): bandOf, validMoyenne, withinBand (erf < 1e-6), positionMoyenne on real counts = Python")
def mo2(c: Ctx):
    return twins_ok(c.js, c.con)


# ------------------------------------------------------------------ MO3 stage 2 re-derived
def sample_types(con, n: int = 5) -> list[str]:
    """Mid-sized types on the real warehouse; on the small synthetic fixture (no type reaches 20 formations) the largest
    ones, so the re-derivation never passes on an empty sample (CI: MO3 once checked 0 rows there)."""
    rows = con.execute("""SELECT r.spe_type_key, count(*) FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        WHERE t.session = (SELECT max(session) FROM core.formation_year) AND r.spe_type_key IS NOT NULL
        GROUP BY 1 ORDER BY hash(r.spe_type_key)""").fetchall()
    mid = [k for k, c in rows if 20 <= c <= 400]
    return (mid or [k for k, _ in sorted(rows, key=lambda r: -r[1])])[:n]


def stage2_ok(con, Jm) -> tuple[bool, str]:
    cur = con.cursor()
    bad, rows_n, edges_n = [], 0, 0
    counts = {}
    for cod, *cs in cur.execute(f"""SELECT l.cod_aff_form, {', '.join(f'sum(coalesce(fy.acc_{m}, 0))' for m in LADDER)}
            FROM core.lineage l0 JOIN core.lineage l ON l.lineage_id = l0.lineage_id
            JOIN core.formation_year fy ON fy.session = l0.session AND fy.cod_aff_form = l0.cod_aff_form
            WHERE l.session = (SELECT max(session) FROM core.formation_year) GROUP BY 1""").fetchall():
        counts[cod] = dict(zip(LADDER, cs))
    for tk in sample_types(cur):
        for serie, dk in (("bg", "MATHS+SES"), ("bt", None)):
            for g in (9.2, 10.0, 11.4, 12.6, 13.95, 15.0, 17.2, 19.0):
                band = Jm.band_of(g)
                res = Jm.stage2(cur, dk, band, tk, None, serie=serie, moyenne=g)
                for f in res["formations"]:
                    rows_n += 1
                    cts = counts.get(f["cod_aff_form"])
                    if not cts or not sum(cts.values()):
                        continue
                    want = py_position(cts, g, Jm)
                    if f["cdf"] is None or abs(f["cdf"] - want["normale"]) > 1e-9 or not f["position"] \
                            or abs(f["position"]["uniforme"] - want["uniforme"]) > 1e-9 \
                            or max(abs(a - b) for a, b in zip(f["position"]["bornes"], want["bornes"])) > 1e-9:
                        bad.append((tk, serie, g, f["cod_aff_form"], f["cdf"], want))
                        break
            # continuity at the band edges and monotony along the averages, every formation
            grid = [8, 9, 10, 11, 11.999, 12, 13, 13.999, 14, 15.999, 16, 17.999, 18, 19, 20]
            seq = {}
            for g in grid:
                for f in Jm.stage2(cur, dk, Jm.band_of(g), tk, None, serie=serie, moyenne=g)["formations"]:
                    seq.setdefault(f["cod_aff_form"], []).append((g, f["cdf"]))
            for cod, s in seq.items():
                vals = [v for _, v in s if v is not None]
                if any(b < a - 1e-9 for a, b in zip(vals, vals[1:])):
                    bad.append((tk, cod, "the share decreases with the average", s))
                    break
                d = dict(s)
                for e in (12, 14, 16, 18):
                    edges_n += 1
                    if d.get(e) is not None and d.get(e - 0.001) is not None and abs(d[e] - d[e - 0.001]) > 0.01:
                        bad.append((tk, cod, "a jump at", e, d[e - 0.001], d[e]))
                        break
            # no average = the band's top; the zone and uncertainty rule
            for m in ("sansmention", "ab", "b", "tb"):
                top_ = {f["cod_aff_form"]: f for f in Jm.stage2(cur, dk, m, tk, None, serie=serie)["formations"]}
                hi = Jm.BANDS[m][1] - 1e-9
                at = {f["cod_aff_form"]: f for f in Jm.stage2(cur, dk, m, tk, None, serie=serie, moyenne=hi)["formations"]}
                for cod, f in top_.items():
                    if f["cdf"] is not None and abs(f["cdf"] - at[cod]["cdf"]) > 1e-6:
                        bad.append((tk, m, cod, "no average is not the band's top", f["cdf"], at[cod]["cdf"]))
                        break
            g = 12.6
            for f in Jm.stage2(cur, dk, "ab", tk, None, serie=serie, moyenne=g)["formations"]:
                if f["zone"] in ("non_ouvert", "indetermine") or f.get("rate_fragile") or f["position"] is None:
                    continue
                z_n = Jm.classify_zone(f["taux_acces_ens"], f["spos"]["cdf_used"] if f.get("spos") else f["cdf"],
                                       *(f["spos"]["ci"] if f.get("spos") else f["cdf_ci"]))
                if z_n["zone"] != f["zone"]:
                    bad.append((tk, f["cod_aff_form"], "zone not from the reading", z_n, f["zone"]))
                    break
    return not bad and rows_n > 0 and edges_n > 0, f"{rows_n} rows re-derived, {edges_n} band edges; problems {bad[:3]}"


@check("MO3 stage 2 re-derived: every share from independent counts, continuous at the edges, never decreasing, the band's top without an average; uncertain when the two hypotheses disagree")
def mo3(c: Ctx):
    ok, detail = stage2_ok(c.con, c.J)
    unc = unc_ok(c.con, c.J)
    return ok and unc, f"{detail}; the hypotheses' disagreement makes the zone uncertain {unc}"


# ------------------------------------------------------------------ MO4 the API
@contextmanager
def client(c: Ctx, jmod=None):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved = os.environ.get("SUPTRACKER_DB"), A.record
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    try:
        yield TestClient(api.app)
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def api_ok(c: Ctx) -> tuple[bool, str]:
    cur = c.con.cursor()
    latest = cur.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    picks = cur.execute("""SELECT fy.cod_aff_form, r.spe_type_key, fy.fil_lib_voe_acc FROM core.formation_year fy
        JOIN core.taxonomy_link t USING (session, cod_aff_form) JOIN core.taxonomy_rule r USING (rule_id)
        WHERE fy.session = ? AND r.spe_type_key IS NOT NULL AND fy.acc_tot >= 20 ORDER BY hash(fy.cod_aff_form) LIMIT 6""", [latest]).fetchall()
    bad = []
    prof = "spe1=MATHS&spe2=SES&serie=bg"
    with client(c) as tc:
        v = tc.get("/api/journey/vocab").json()
        if [m["code"] for m in v["mentions"]] != ["rattrapage", "sansmention", "ab", "b", "tb", "tbf"]:
            bad.append(("vocabulary", [m["code"] for m in v["mentions"]]))
        for q, code in (("mention=b&moyenne=12.4", 422), ("mention=rattrapage&moyenne=10", 422), ("moyenne=7.9", 422),
                        ("moyenne=20.1", 422), ("moyenne=abc", 422), ("moyenne=12.4", 200), ("mention=rattrapage", 200), ("mention=tbf", 200)):
            r = tc.get(f"/api/journey/stage2?{q}&type={picks[0][1]}&{prof}")
            if r.status_code != code:
                bad.append((q, r.status_code))
            if code == 200 and "moyenne" in q and "no-store" not in r.headers.get("cache-control", ""):
                bad.append((q, "an answer read for an average is shared-cached", r.headers.get("cache-control")))
        if "no-store" in tc.get(f"/api/journey/stage2?mention=ab&type={picks[0][1]}&{prof}").headers.get("cache-control", "x"):
            bad.append("a coarse answer lost its public cache")
        for g in (9.4, 12.6, 15.3):
            band = J.band_of(g)
            for cod, tk, _ in picks:
                s2 = {f["cod_aff_form"]: f for f in tc.get(f"/api/journey/stage2?moyenne={g}&type={tk}&{prof}").json()["formations"]}
                if cod not in s2:
                    continue
                want = s2[cod]["zone"]
                vx = tc.get(f"/api/voeux?ids={cod}&moyenne={g}&{prof}").json()["voeux"][0]
                pb = tc.get(f"/api/planb/{cod}?moyenne={g}&{prof}").json()
                mz = None
                if vx.get("zone") != want:
                    bad.append((cod, g, "Mes vœux", vx.get("zone"), want))
                if pb.get("target") and pb["target"].get("zone") != want:
                    bad.append((cod, g, "Plan B", pb["target"].get("zone"), want))
                if vx.get("position_moyenne") is None and s2[cod].get("position") is not None:
                    bad.append((cod, g, "Mes vœux lost the average's range"))
                mz = tc.get(f"/api/carte/zones?diplome=x&mention_bac={band}&moyenne={g}&spe1=MATHS&spe2=SES")
                if mz.status_code not in (200, 404):
                    bad.append((cod, g, "map", mz.status_code))
        # the map's old "sm" code reads "sans mention" (it was never accepted by stage 2)
        r_sm = tc.get("/api/carte/zones?diplome=BUT&mention_bac=sm&spe1=MATHS&spe2=SES")
        r_sans = tc.get("/api/carte/zones?diplome=BUT&mention_bac=sansmention&spe1=MATHS&spe2=SES")
        if r_sm.status_code != 200 or r_sm.json() != r_sans.json():
            bad.append(("map 'sm'", r_sm.status_code))
        # the search zones carry the average too
        rs = tc.get(f"/api/search?q=bts&avance=true&{prof}&moyenne=9.5&limit=30")
        rb = tc.get(f"/api/search?q=bts&avance=true&{prof}&mention=sansmention&limit=30")
        if rs.status_code != 200 or rb.status_code != 200:
            bad.append(("search", rs.status_code, rb.status_code))
        else:
            zs = [x.get("zone") for x in rs.json()["results"]]
            zb = [x.get("zone") for x in rb.json()["results"]]
            if zs == zb:
                bad.append("the search ignores the average")
        # review: the answers echo the student's OWN average (a rattrapage without one is not "sous votre moyenne")
        cod0, tk0, _ = picks[0]
        echo = [tc.get(f"/api/journey/stage2?mention=rattrapage&type={tk0}&{prof}").json().get("moyenne"),
                tc.get(f"/api/voeux?ids={cod0}&mention=rattrapage&{prof}").json().get("moyenne"),
                tc.get(f"/api/planb/{cod0}?mention=rattrapage&{prof}").json().get("moyenne"),
                tc.get(f"/api/journey/stage2?mention=rattrapage&moyenne=9&type={tk0}&{prof}").json().get("moyenne")]
        if echo != [None, None, None, 9.0]:
            bad.append(("the echoed average", echo))
        rc = tc.get(f"/api/voeux/completer?ids={picks[0][0]}&moyenne=9.1&{prof}")
        if rc.status_code != 200 or "no-store" not in rc.headers.get("cache-control", ""):
            bad.append(("completer", rc.status_code))
    return not bad, f"{len(picks)} formations x 3 averages; problems {bad[:4]}"


@check("MO4 the API: every route takes the average, gives the stage-2 zone, 422 on a mismatch or out of range, never shared-cached")
def mo4(c: Ctx):
    return api_ok(c)


# ------------------------------------------------------------------ MO5 the page
PAGE_PROG = r"""
const IN = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const H = "<img src=x onerror=alert(1)>";
let PROFILE = null;
const store = { get: (k, d) => (k === "profile" ? PROFILE : d), set() {} };
const JV = { mentions: IN.mentions, specialties: [{ code: "MATHS", short: "Maths" }, { code: "SES", short: "SES" }], academies: ["Lyon"],
  series: [{ code: "bg", label: "bac général" }], voies: {} };
const tip = () => "";
const out = {};
out.form = profileForm({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6 }, true);
out.formNone = profileForm({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "tb" }, true);
const fd = (o) => ({ get: (k) => (k in o ? o[k] : null) });
const form = { querySelector: () => null };
out.read = [readForm(fd({ statut: "terminale", serie: "bg", moyenne: "15,74", mention: "ab" }), {}, "bg", null, form, null),
  readForm(fd({ statut: "terminale", serie: "bg", moyenne: "", mention: "tb" }), {}, "bg", null, form, null),
  readForm(fd({ statut: "terminale", serie: "bg", moyenne: "9" }), { mention: "ab" }, "bg", null, form, null)];
out.vx = [vxProfile({ mention: "ab", moyenne: 17.2 }), vxProfile({ mention: "zz" }), vxProfile({ mention: "rattrapage" }), vxProfile({ mention: "ab", moyenne: "<b>" })];
out.q = [mentionParams(new URLSearchParams(), vxProfile({ mention: "ab", moyenne: 12.6 })).toString(), mentionParams(new URLSearchParams(), vxProfile({ mention: "tbf" })).toString(),
  mentionParams(new URLSearchParams(), vxProfile({ mention: "rattrapage" })).toString(), mentionParamsSearch(new URLSearchParams(), vxProfile({ mention: "ab", moyenne: 12.6 })).toString()];
out.words = [mentionWords({ mention: "tbf" }), mentionWords({ mention: "rattrapage" }), mentionWords({ mention: "tb", moyenne: 12.4 }),
  mentionWords({ mention: "<b>" })];
out.rows = ["rattrapage", "sansmention", "ab", "tbf"].map((m) => MENTION_ROW[vxProfile({ mention: m }).mention]);
out.rowLabels = Object.values(MENTION_ROW).map((r) => MENTION_TXT[r]);
out.line = [chipLine(vxProfile({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6 })), profileLine({ spe1: "MATHS", spe2: "SES", mention: "rattrapage" }, "bg")];
const rec = (o) => ({ session: 2025, acc_sansmention: 30, acc_ab: 40, acc_b: 20, acc_tb: 8, acc_tbf: 2, ...o });
PROFILE = { serie: "bg", mention: "ab", moyenne: 12.6, statut: "terminale" };
out.card = moyenneCard(rec({}));
PROFILE = { serie: "bg", mention: "rattrapage", moyenne: 9.2, statut: "terminale" };
out.cardR = moyenneCard(rec({ session: H }));
PROFILE = { serie: "bg", mention: "ab", moyenne: 13, statut: "terminale" };
out.cardSmall = moyenneCard(rec({ acc_sansmention: 3, acc_ab: 4, acc_b: 2, acc_tb: 0, acc_tbf: 0 }));
PROFILE = null;
out.cardNone = moyenneCard(rec({}));
out.cardEmpty = moyenneCard(rec({ acc_sansmention: 0, acc_ab: 0, acc_b: 0, acc_tb: 0, acc_tbf: 0 }));
process.stdout.write(JSON.stringify(out));
"""


def page_ok(js: str, mentions: list[dict]) -> tuple[bool, str]:
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const pc1 = ",
                                                                       "const REO_LABEL = ", "const isReo = ")))
    names = ("MENTION_CODES", "BANDS", "BAND_SIGMA", "validMoyenne", "bandOf", "mentionParams", "moyenneText", "mentionWords", "MENTION_ROW", "MENTION_TXT", "vxProfile", "bandParam", "mentionParamsSearch",
             "MENTION_SHORT", "chipLine", "profileLine", "PF_SAVE", "spe2Of", "profileForm", "voieFromForm", "readForm", "erf",
             "withinBand", "LADDER", "positionMoyenne", "COLORS", "DASHES", "seriesDash", "lineLegend", "moyenneChart", "moyenneCard",
             "bacProfile")
    prog = helpers + "\n" + "\n".join(top(js, n) for n in names) + PAGE_PROG
    r = node(prog, {"mentions": mentions})
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    if 'name="moyenne"' not in o["form"] or 'value="12,6"' not in o["form"] or 'name="mention" disabled' not in o["form"] \
            or not re.search(r'<option value="ab" selected', o["form"]):
        bad.append("the form does not draw the average, or the list does not follow it")
    if 'name="mention" disabled' in o["formNone"] or 'value=""' not in re.search(r'name="moyenne"[^>]*', o["formNone"]).group(0):
        bad.append("the form without an average")
    if not all(f"<option value=\"{m}\"" in o["form"] for m in ("rattrapage", "sansmention", "ab", "b", "tb", "tbf")):
        bad.append("a band is missing from the list")
    r0, r1, r2 = o["read"]
    if (r0.get("moyenne"), r0.get("mention")) != (15.7, "b") or (r1.get("moyenne"), r1.get("mention")) != (None, "tb") \
            or (r2.get("moyenne"), r2.get("mention")) != (9, "rattrapage"):
        bad.append(("reading the form", [(x.get("moyenne"), x.get("mention")) for x in o["read"]]))
    v0, v1, v2, v3 = o["vx"]
    if (v0["mention"], v0["moyenne"]) != ("tb", 17.2) or v1["mention"] != "ab" or v2["mention"] != "rattrapage" or v3["moyenne"] is not None:
        bad.append(("vxProfile", o["vx"]))
    # R6: the zone queries carry the band only (the page reads the average itself); the search alone sends the average
    if o["q"] != ["mention=ab", "mention=tbf", "mention=sansmention", "mention=ab&moyenne=12.6"]:
        bad.append(("queries", o["q"]))
    if o["words"] != ["mention très bien félicitations", "bac au rattrapage", "mention assez bien, moyenne visée 12,4/20", "mention assez bien"]:
        bad.append(("the band in words (Plan B, Mes vœux)", o["words"]))
    if o["rows"] != ["passable2", "passable1", "ab", "tb"]:
        bad.append(("the success rows of a band", o["rows"]))
    if any(not isinstance(t, str) or not t or "undefined" in t for t in o["rowLabels"]) or "rattrapage" not in " ".join(o["rowLabels"]):
        bad.append(("a success row the BUT / master cards read has no label (Codex: 'mention undefined')", o["rowLabels"]))
    if "12,6/20" not in o["line"][0] or "rattrapage" not in o["line"][1]:
        bad.append(("profile lines", o["line"]))
    card = o["card"]
    plain = re.sub(r"<[^>]+>", " ", card)
    # 30/40/20/8/2: 12.6 in AB -> normal: 30 + 40 * within(12.6) ; the card prints both ends
    a = 100 * (30 + 40 * J.within(12.6, "ab")) / 100
    b = 100 * (30 + 40 * J.within(12.6, "ab", "uniforme")) / 100
    fr = lambda v: f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731  (the page's fmt: no trailing zero)
    want = [fr(min(a, b)), fr(max(a, b))]
    if not all(f"{w} %" in plain for w in want) or "selon cette estimation" not in plain or "30 %" not in plain or "70 %" not in plain:
        bad.append(("the card's range or bounds", want))
    if "pas des chances" not in plain or CHANCE.search(plain.replace("pas des chances", "")):
        bad.append("chance wording")
    if "rattrapage" not in o["cardR"] or "<img" in o["cardR"] or "&lt;img" not in o["cardR"]:
        bad.append("rattrapage note or escaping")
    if "peu d'admis" not in o["cardSmall"].replace("&#39;", "'") or "peu d'admis" in card.replace("&#39;", "'"):
        bad.append("a small cohort is not flagged (or a large one is)")
    if 'href="#/profil"' not in o["cardNone"] or "Avec " in o["cardNone"] or o["cardEmpty"] != "":
        bad.append("the card without an average or without admits")
    if 'aria-label="' not in card or 'role="img"' not in card:
        bad.append("the curve has no accessible name")
    return not bad, f"form, reading, profile, queries, 5 cards; problems {bad[:4]}"


@check("MO5 the page (Node): the form draws and reads the average, vxProfile lets it set the band, the queries carry it, the card says its range")
def mo5(c: Ctx):
    with client(c) as tc:
        mentions = tc.get("/api/journey/vocab").json()["mentions"]
    return page_ok(c.js, mentions)


# ------------------------------------------------------------------ MO6 wiring and wording
def wiring_ok(js: str, api_src: str, cache_src: str, cal_src: str, readme: str, claude: str) -> tuple[bool, str]:
    bad = []
    raw = re.findall(r'mention: prof\.mention|mention=\$\{p\.mention\}|mention_bac=\$\{P\.mention\}|qs\.set\("mention", v\.mention\)', js)
    if raw:
        bad.append(("a query sends the raw stored mention", raw[:3]))
    for site in ("const qs = mentionParams(new URLSearchParams({ ids: ids.join(\",\"), serie: prof.serie }), prof);",
                 "qs.set(\"serie\", v.serie); mentionParamsSearch(qs, v);",
                 "mentionParams(new URLSearchParams({ serie }), vxProfile({ mention: \"ab\", ...prof }))",
                 "${mentionParams(new URLSearchParams(), vxProfile(p))}&type=",
                 "mention_bac=${encodeURIComponent(bandParam(VP))}"):
        if site not in js:
            bad.append(("a query does not carry the average", site[:50]))
    if re.search(r'\{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" \}\[', js):
        bad.append("a four-band mention map left (TBF and rattrapage read 'undefined')")
    if 'const avg = vxProfile(store.get("profile", {}) || {}).moyenne !== null;' not in js or "F[0] && F[0].position ?" in js:
        bad.append("the scatter labels keyed on the rattrapage's implicit average")
    if '["sm", "ab", "b", "tb"].includes(P.mention)' in js or "MENTION_CODES.includes(VP && VP.mention)" not in js:
        bad.append("the map asks zones only for some bands (the 'sm' bug)")
    if "!MENTION_CODES.includes(p.mention)) return null;   // never a default; the average is never shared" not in js \
            or re.search(r'q\.set\("[a-z]+", prof\.moyenne\)', js):
        bad.append("the shared list and the average")
    if 'fine="moyenne" in request.query_params' not in api_src or 'if status not in (200, 304) or (fine and pol != "asset"):' not in cache_src:
        bad.append("an answer read for an average may be shared-cached")
    if 'continuous=moyenne is not None' not in api_src or '"zone_confirmed": None' not in cal_src:
        bad.append("calibration keeps the band's share range or stability with an average")
    if "Sprint R5" not in readme or "moyenne" not in readme or "Continuous average (sprint R5" not in claude or "redteam_moyenne.py" not in claude:
        bad.append("README or CLAUDE.md")
    return not bad, f"problems {bad[:4]}"


@check("MO6 wiring and wording: every query carries the average, the map reads every band, no-store, calibration, docs")
def mo6(c: Ctx):
    return wiring_ok(c.js, c.api_src, c.cache_src, c.cal_src, c.readme, c.claude)


# ------------------------------------------------------------------ MO7 browser
BROWSER = r"""
const { chromium } = require('playwright');
const base = process.argv[2], cod = process.argv[3];
(async () => {
  const b = await chromium.launch(); const errs = []; const o = {};
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((c) => { if (!localStorage.getItem("profile")) localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", statut: "terminale" })); localStorage.setItem("voeux", JSON.stringify([c])); }, cod);
  const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
  await p.goto(base + "/#/profil"); await p.waitForTimeout(1500);
  await p.fill('#pf [name="moyenne"]', "12,6"); await p.press('#pf [name="moyenne"]', "Tab"); await p.waitForTimeout(500);
  o.stored = await p.evaluate(() => JSON.parse(localStorage.getItem("profile")));
  o.disabled = await p.$eval('#pf [name="mention"]', (s) => s.disabled);
  await p.goto(base + "/#/voeux"); await p.waitForTimeout(3500);
  o.voeux = await p.evaluate(() => document.body.innerText.includes("estimation dans la mention"));
  await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(3500);
  await p.evaluate(() => document.querySelectorAll("details.more-card").forEach((d) => (d.open = true)));
  o.card = await p.evaluate(() => [...document.querySelectorAll("h2")].some((h) => h.textContent.startsWith("Votre moyenne parmi les admis")));
  await p.evaluate(() => localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "sansmention", statut: "terminale" })));
  const zreq = [];
  p.on("request", (r) => { if (r.url().includes("/api/carte/zones")) zreq.push(r.url()); });
  await p.goto(base + "/#/carte/BTS"); await p.waitForTimeout(5000);
  o.mapZones = zreq;
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


@check("MO7 browser: the average saved from Mon profil, read in Mes vœux and on the formation page; the map asks zones for a sans-mention profile")
def mo7(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    cod = c.con.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy JOIN core.taxonomy_link t USING (session, cod_aff_form)
        JOIN core.taxonomy_rule r USING (rule_id) WHERE fy.session = (SELECT max(session) FROM core.formation_year)
        AND r.spe_type_key IS NOT NULL AND fy.acc_neobac >= 20 AND fy.fili = 'BTS' ORDER BY hash(fy.cod_aff_form) LIMIT 1""").fetchone()[0]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".moyenne_probe.js"
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
    o, bad = d["o"], []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if (o["stored"].get("moyenne"), o["stored"].get("mention")) != (12.6, "ab") or not o["disabled"]:
        bad.append(("stored", o["stored"], o["disabled"]))
    if not o["voeux"] or not o["card"]:
        bad.append(("Mes vœux or the formation card", o["voeux"], o["card"]))
    if not o["mapZones"] or "mention_bac=sansmention" not in o["mapZones"][0]:
        bad.append(("the map asks no zone for a sans-mention profile", o["mapZones"][:1]))
    return not bad, f"{o}; problems {bad[:3]}"


@check("MO8 mutation test: model, twins, stage 2, API, page and wiring bugs are each caught")
def mo8(c: Ctx):
    mutants = [
        ("py", "a gaussian centred on the band's floor", '''BANDS = {"sansmention": (8.0, 12.0, 11.0), "ab": (12.0, 14.0, 13.0),''',
         '''BANDS = {"sansmention": (8.0, 12.0, 11.0), "ab": (12.0, 14.0, 12.0),''', "mo1"),
        ("py", "sans mention from 10 (the rattrapage left out)", '''BANDS = {"sansmention": (8.0, 12.0, 11.0),''', '''BANDS = {"sansmention": (10.0, 12.0, 11.0),''', "mo1"),
        ("py", "a wider normal curve", "BAND_SIGMA = 1.0", "BAND_SIGMA = 2.0", "mo1"),
        ("py", "the rattrapage read at the band's top", "RATTRAPAGE_TOP = 10.0          #", "RATTRAPAGE_TOP = 12.0          #", "mo1"),
        ("py", "a mention that contradicts the average accepted", '''        if mention is not None and mention != band:
            raise ValueError("la mention et la moyenne ne correspondent pas")''', "", "mo1"),
        ("py", "the band's full share whatever the average", "        k = k_top - (1.0 - w) * k_band                      # R5",
         "        k = k_top                      # R5", "mo3"),
        ("py", "the uniform hypothesis never checked", '''            x["uncertain"] = alt != x["zone"]''', '''            x["uncertain"] = x["uncertain"]''', "mo3_unc"),
        ("js", "bandOf without the rattrapage", '  if (g < 10) return "rattrapage";\n', "", "mo2"),
        ("js", "an average to the unit", "Math.round(x * 10) / 10 : null;", "Math.round(x) : null;", "mo2"),
        ("js", "commas refused", '.trim().replace(",", "."));', ".trim());", "mo2"),
        ("js", "the average does not set the band", 'const mention = moyenne !== null ? bandOf(moyenne) : MENTION_CODES.includes(p.mention) ? p.mention : "ab";',
         'const mention = MENTION_CODES.includes(p.mention) ? p.mention : "ab";', "mo5"),
        ("js", "the query drops the average", '  if (p.moyenne !== null && p.moyenne !== undefined) qs.set("moyenne", String(p.moyenne));\n', "", "mo5"),
        ("js", "the card's range not said as an estimation", "avaient, selon cette estimation, une note", "avaient une note", "mo5"),
        ("js", "a small cohort not flagged", '${n < 20 ? ` <span class="badge warnb">peu d', '${false ? ` <span class="badge warnb">peu d', "mo5"),
        ("js", "the rattrapage success row unlabelled", ' passable2: "passable (2nd groupe, rattrapage)",', "", "mo5"),
        ("js", "the old map codes back", "MENTION_CODES.includes(VP && VP.mention)", '["sm", "ab", "b", "tb"].includes(P.mention)', "mo6"),
        ("js", "Plan B names the raw stored mention", '}, ${mentionWords({ mention: "ab", ...prof })}${prof.academie',
         '}, mention ${{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[prof.mention] || "assez bien"}${prof.academie', "mo6"),
        ("js", "TBF reads the assez bien row", 'b: "b", tb: "tb", tbf: "tb" };', 'b: "b", tb: "tb" };', "mo5"),
        ("js", "the band in words ignores the average", "return v.moyenne !== null ? `${m}, moyenne visée ${moyenneText(v.moyenne)}` : m;", "return m;", "mo5"),
        ("api", "the rattrapage's implicit 10 echoed", '    res["moyenne"] = given ', '    res["moyenne"] = moyenne ', "mo4"),
        ("js", "Mes vœux sends the raw mention", "const qs = mentionParams(new URLSearchParams({ ids: ids.join(\",\"), serie: prof.serie }), prof);",
         "const qs = new URLSearchParams({ ids: ids.join(\",\"), serie: prof.serie, mention: prof.mention });", "mo6"),
        ("api", "an average answer kept by the CDN", 'fine="moyenne" in request.query_params', "fine=False", "mo6"),
    ]
    missed = []
    for kind, name, old, new, which in mutants:
        src = {"py": c.j_src, "js": c.js, "api": c.api_src}[kind]
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone)")
            continue
        mut = src.replace(old, new)
        try:
            if kind == "py":
                Jm = load("journey", mut)
                ok = model_ok(Jm)[0] if which == "mo1" else (stage2_ok(c.con, Jm)[0] if which == "mo3" else unc_ok(c.con, Jm))
            elif kind == "js":
                ok = {"mo2": lambda: twins_ok(mut, c.con), "mo5": lambda: page_ok(mut, MENTIONS_FIXED),
                      "mo6": lambda: wiring_ok(mut, c.api_src, c.cache_src, c.cal_src, c.readme, c.claude)}[which]()[0]
            elif which == "mo4":
                ok = api_echo_ok(c, mut)
            else:
                ok = wiring_ok(c.js, mut, c.cache_src, c.cal_src, c.readme, c.claude)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    n = len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def api_echo_ok(c, api_src):
    """The stage-2 route of a (possibly mutated) api.py echoes the student's own average: None for a rattrapage without one."""
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    mod = load("api", api_src)
    old, saved = os.environ.get("SUPTRACKER_DB"), A.record
    os.environ["SUPTRACKER_DB"] = str(c.db)
    mod._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    try:
        tk = sample_types(c.con.cursor(), 1)[0]
        r = TestClient(mod.app).get(f"/api/journey/stage2?mention=rattrapage&type={tk}&spe1=MATHS&spe2=SES&serie=bg")
        return r.status_code == 200 and r.json().get("moyenne") is None
    finally:
        A.record = saved
        mod._con.cache_clear()
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old


MENTIONS_FIXED = [{"code": "rattrapage", "label": "Bac au rattrapage (8 à 10)", "min": 8, "max": 10},
                  {"code": "sansmention", "label": "Sans mention", "min": 10, "max": 12}, {"code": "ab", "label": "Assez bien", "min": 12, "max": 14},
                  {"code": "b", "label": "Bien", "min": 14, "max": 16}, {"code": "tb", "label": "Très bien", "min": 16, "max": 18},
                  {"code": "tbf", "label": "Très bien avec félicitations", "min": 18, "max": 20}]


def margins_of(cur, cod: str) -> list[dict]:
    """The campaign-by-campaign margins of the mention x series table of a formation's lineage (as stage 2 reads them)."""
    keys = list(J.BG_KEYS)
    rows = cur.execute(f"""SELECT {', '.join('fy.' + k for k in keys)} FROM core.lineage l0 JOIN core.lineage l ON l.lineage_id = l0.lineage_id
        JOIN core.formation_year fy ON fy.session = l.session AND fy.cod_aff_form = l.cod_aff_form
        WHERE l0.cod_aff_form = ? AND l0.session = (SELECT max(session) FROM core.formation_year) ORDER BY fy.session""", [cod]).fetchall()
    return [dict(zip(keys, r)) for r in rows]


def unc_ok(con, Jm) -> bool:
    """A zone the uniform hypothesis reads differently (same reading as the page: the bac-général bounds when they exist) must be
    said uncertain; at least one such row must exist on the sample, and some must not already be uncertain by sampling alone."""
    cur = con.cursor()
    seen = 0
    for tk in sample_types(cur, 8):
        for g in (10.3, 12.4, 14.4):
            band = Jm.band_of(g)
            w_u = Jm.within(g, band, "uniforme")
            for f in Jm.stage2(cur, "MATHS+SES", band, tk, None, moyenne=g)["formations"]:
                if f["zone"] in ("non_ouvert", "indetermine") or f["position"] is None or f.get("rate_fragile"):
                    continue
                n = f["n_known"]
                rd = Jm.zone_reading("bg", band, f["position"]["uniforme"] * n, n, margins_of(cur, f["cod_aff_form"]), w_u)
                alt = Jm.classify_zone(f["taux_acces_ens"], rd["cdf_zone"], *rd["ci_zone"])["zone"]
                if alt != f["zone"]:
                    seen += 1
                    if not f["uncertain"]:
                        return False
    return seen > 0


@check("MO9 wiring of the docs: the method text and the glossary say the average is an estimation, never a chance")
def mo9(c: Ctx):
    with client(c) as tc:
        meta = tc.get("/api/meta").json()
    meth = meta.get("methodology", {}).get("moyenne", "")
    gl = [g for g in meta.get("glossary", []) if g.get("key") == "moyenne"]
    ok = bool(meth) and "estimation" in meth and "chance" not in meth.replace("jamais une chance", "") and len(gl) == 1
    return ok, f"method text {bool(meth)}; glossary entry {len(gl)}"


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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
