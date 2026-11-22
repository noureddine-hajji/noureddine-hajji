"""Red team of the evolution page (owner, 2026-11-22): « Évolution de la cohorte 2022–2025 » in colour, with the student's own curves.

    python scripts/redteam_evolution.py [--db data/suptracker.duckdb] [--real] [--browser]

  EV1 tokens: the categorical set --k1..--k4 and the mention ramp --m1..--m5 are defined in the light block, the dark media block
      and the [data-theme="dark"] block (the two dark blocks with the same values) and in the print block (the light values)
  EV2 colours, every theme: each k and m step >= 60 (RGB) from every zone, bac route and accent colour; k1..k4 >= 3:1 on the card;
      every pair of k colours apart (CIE76 dE >= 20 in normal vision, >= 10 under deuteranopia, protanopia and tritanopia,
      Machado 2009); the mention ramp ordered, TB félicitations darkest in every theme, neighbours >= 10 L apart and >= 10
      dE apart under each colour-blindness
  EV3 wiring: every line of the evolution page has its own token colour (never the grey ramp) AND its own dash within its chart;
      the mention bars use the m ramp; the stacked bars carry the ink edge; no chart of the page falls back on COLORS
  EV4 « Vous parmi les admis » (Node vs an independent Python reading): per year, the share of néo-bachelier admits (mention known)
      with the student's mention or lower, strictly lower, and with an average the estimate below it (truncated normal, sigma 1,
      centred in the band; the uniform spread the other end); rattrapage read in « sans mention »; no year without admits; crafted
      and real lineages
  EV5 the pair, year by year (Node vs Python): the formation's OWN report of that campaign (pair line, else « Autres » unless an
      unknown pair label; a table without either = no point, never an estimate); else the page's estimate; a published point is a
      square and never sits beside an estimate the same year; hollow below 20 confirmed; the key is printed when a square is drawn
  EV6 the API: /api/lineage's `rapports` = the report of THAT code and THAT session only, cross-checked only, its bac général lines
      re-read by an independent query (rate = 100 x en_position / confirmés, 1 decimal); a crafted warehouse checks the fallbacks
  EV7 privacy and words: the page asks /api/formation and /api/lineage only, with no profile key (the average stays in the
      browser); stored strings escaped (group, pair labels); « pas des chances », never a chance word; the average line is an
      estimTag; the new sentences <= 30 words
  EV8 accessibility (Node): every chart is named with its series and years and preceded by its legend; the outside-terminale
      profile gets no mention card, a missing profile a link to « Mon profil »
  EV9 browser (--browser / --real): light, dark, phone, 320 px; bac général with an average, bac techno, no profile,
      reorientation: 0 JS error, no horizontal scroll, every chart named, squares = published years of the API
  EV10 quality score (owner: >= 90): 0.6 x measured (EV1-EV9 weights, 100) + 0.4 x the independent screenshot review
      (scripts/evolution_review.json, 10 criteria by a reviewer who saw only screenshots), the review alone >= 80
  EV11 mutation test: palette, wiring, reading, API and wording bugs are each caught (mutants built in memory)
  EV12 wiring and docs: test file, durations, nightly browser suite, README section, CLAUDE.md rule
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
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
STATIC = ROOT / "suptracker" / "static"
REVIEW = ROOT / "scripts" / "evolution_review.json"
CHECKS = []
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")
SEMANTIC = ("zone-securite", "zone-cible", "zone-ambitieux", "voie-bg", "voie-bt", "voie-bp", "accent")
KS, MS = ("k1", "k2", "k3", "k4"), ("m1", "m2", "m3", "m4", "m5")
# R5 bands (CLAUDE.md, written down independently of app.js): [bottom, top, centre]
BANDS = {"sansmention": (8, 12, 11), "ab": (12, 14, 13), "b": (14, 16, 15), "tb": (16, 18, 17), "tbf": (18, 20, 19)}
LADDER = ("sansmention", "ab", "b", "tb", "tbf")
WEIGHTS = {"EV1": 8, "EV2": 14, "EV3": 10, "EV4": 14, "EV5": 14, "EV6": 10, "EV7": 10, "EV8": 6, "EV9": 14}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False, js: str | None = None, css: str | None = None,
                 rapports_src: str | None = None):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True) if db and Path(db).exists() else None
        self.js = js if js is not None else (STATIC / "app.js").read_text()
        self.css = css if css is not None else (STATIC / "style.css").read_text()
        self.rapports_src = rapports_src if rapports_src is not None else (ROOT / "suptracker" / "rapports.py").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()


# ------------------------------------------------------------------ colours
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(h):
    r, g, b = (_lin(c) for c in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def dist(a, b):
    return math.dist(rgb(a), rgb(b))


MACHADO = {"deut": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
           "prot": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
           "trit": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900))}


def lab(h, cvd=None):
    lin = [_lin(c) for c in rgb(h)]
    if cvd:
        m = MACHADO[cvd]
        lin = [max(0.0, min(1.0, sum(m[i][j] * lin[j] for j in range(3)))) for i in range(3)]
    r, g, b = lin
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def de(a, b, cvd=None):
    return math.dist(lab(a, cvd), lab(b, cvd))


def themes(css: str) -> dict:
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    pm = re.search(r"@media print\s*\{", body)
    printed = body[pm.start():] if pm else ""
    body = body[:pm.start()] if pm else body
    tok = lambda b: dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", b))  # noqa: E731
    light, dm, da = {}, {}, {}
    for m in re.finditer(r"(?m)^:root\s*\{([^}]*)\}", body):
        light.update(tok(m.group(1)))
    m = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{([^}]*)\}", body)
    if m:
        dm = tok(m.group(1))
    m = re.search(r"(?m)^:root\[data-theme=\"dark\"\]\s*\{([^}]*)\}", body)
    if m:
        da = tok(m.group(1))
    pr = {}
    m = re.search(r":root:root:root\s*\{([^}]*)\}", printed)
    if m:
        pr = tok(m.group(1))
    return {"light": light, "dark_media": dm, "dark_attr": da, "print": pr}


def tokens_ok(css: str):
    t, bad = themes(css), []
    for th in ("light", "dark_media", "dark_attr", "print"):
        miss = [k for k in KS + MS if k not in t[th]]
        if miss:
            bad.append((th, "missing", miss))
    diff = [k for k in KS + MS if t["dark_media"].get(k) != t["dark_attr"].get(k)]
    if diff:
        bad.append(("the two dark blocks differ", diff))
    pdiff = [k for k in KS + MS if t["print"].get(k) != t["light"].get(k)]
    if pdiff:
        bad.append(("print is not the light palette", pdiff))
    return not bad, f"{len(KS) + len(MS)} tokens in 4 blocks; problems {bad[:4]}"


def palette_ok(css: str):
    t, bad, low = themes(css), [], []
    for th, light_first in (("light", True), ("dark_media", True), ("dark_attr", True)):   # TB félicitations darkest in every theme
        tok = t[th]
        if any(k not in tok for k in KS + MS + SEMANTIC + ("surface",)):
            bad.append((th, "tokens missing"))
            continue
        for k in KS + MS:
            for s in SEMANTIC:
                if dist(tok[k], tok[s]) < 60:
                    bad.append((th, k, "near", s, round(dist(tok[k], tok[s]))))
        for k in KS:
            r = contrast(tok[k], tok["surface"])
            low.append(r)
            if r < 3:
                bad.append((th, k, "contrast", round(r, 2)))
        for a, b in itertools.combinations(KS, 2):
            if de(tok[a], tok[b]) < 20:
                bad.append((th, a, b, "dE normal", round(de(tok[a], tok[b]))))
            for cvd in MACHADO:
                if de(tok[a], tok[b], cvd) < 10:
                    bad.append((th, a, b, cvd, round(de(tok[a], tok[b], cvd))))
        ls = [lab(tok[k])[0] for k in MS]
        if ls != sorted(ls, reverse=not light_first):
            bad.append((th, "mention ramp out of order", [round(x) for x in ls]))
        for a, b in zip(MS, MS[1:]):
            if abs(lab(tok[a])[0] - lab(tok[b])[0]) < 10:
                bad.append((th, a, b, "dL < 10"))
            for cvd in MACHADO:
                if de(tok[a], tok[b], cvd) < 10:
                    bad.append((th, a, b, cvd))
    return not bad, f"3 themes; lowest line contrast {round(min(low), 2) if low else None}; problems {bad[:5]}"


@check("EV1 tokens: k1-k4 and m1-m5 in the light, both dark (identical) and print blocks")
def ev1(c: Ctx):
    return tokens_ok(c.css)


@check("EV2 colours: >= 60 from zones, routes and accent; lines >= 3:1; categorical and ramp apart in normal and colour-blind vision")
def ev2(c: Ctx):
    return palette_ok(c.css)


# ------------------------------------------------------------------ JS extraction
def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        return js[m.start(): one]
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return "__error__ " + r.stderr[-900:]
    return r.stdout


NAMES = ("esc", "fmt", "pc1", "ESTIM_DEF", "estimTag", "validMoyenne", "BANDS", "BAND_SIGMA", "MENTION_CODES", "bandOf", "erf",
         "withinBand", "LADDER", "positionMoyenne", "moyenneText", "MENTION_SHORT", "isReo", "bacProfile", "vxProfile", "COLORS",
         "DASHES", "seriesDash", "chartName", "PHONE_CHART", "lineChart", "stackedBars", "legend", "lineLegend", "markKey", "EVO", "MENTIONS",
         "mentionYears", "mentionEvolutionCard", "VOIES", "DBL_SEUIL", "DBL_CAVEAT", "ownHasBg", "pickRapport", "profileDkey",
         "pickDoublette", "estimateSemblable", "estimateDoublette", "pairByYear", "doubletteCharts")


def harness(js: str) -> str:
    parts = []
    for n in NAMES:
        try:
            parts.append(top(js, n))
        except KeyError:
            parts.append(f"/* missing {n} */")
    return ("let STORE = {}; const store = { get: (k, d) => (k in STORE ? STORE[k] : d) };\n"
            "const tip = () => ''; const label = (k) => k; const META = { low_n_threshold: 10, years: [2022, 2023, 2024, 2025] };\n"
            + "\n".join(parts) + "\nconst CAP = []; const _lc = lineChart; lineChart = (y, s, o) => { CAP.push(s); return _lc(y, s, o); };\n"
            "const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n")


# ------------------------------------------------------------------ EV3 wiring
def block(js: str, start: str, end: str) -> str:
    a = js.find(start)
    return js[a: js.find(end, a)] if a >= 0 else ""


def wiring_ok(js: str, css: str):
    bad = []
    evo = block(js, "async function viewEvolution(", "\nasync function viewCompare(")
    dbl = block(js, "function doubletteCharts(", "\n// ---- Sprint")
    men = block(js, "function mentionEvolutionCard(", "\nasync function viewEvolution(")
    page = evo + dbl + men
    if not evo or not dbl or not men:
        return False, "a piece of the page is missing"
    if re.search(r"var\(--c[1-6]\)", evo + dbl + men):
        bad.append("a grey ramp colour on an evolution chart")
    if re.search(r"lineChart\(years, \[\{ name:", page):
        bad.append("an inline series without colour")
    if "EVO.k1" not in page or "EVO.ref" not in page:
        bad.append("the categorical palette is not used")
    for name in ("socialLines", "accesLines"):          # the page's own lists: a colour and a dash each, none repeated
        lst = block(evo, f"const {name} = ", ";\n")
        pairs = re.findall(r'\[\s*"pct_[a-z_]+", (EVO\.\w+), "([^"]*)"\]', lst) or re.findall(r'color: (EVO\.\w+), dash: "([^"]*)"', lst)
        if len(pairs) < 2 or len({p[0] for p in pairs}) != len(pairs) or len({p[1] for p in pairs}) != len(pairs):
            bad.append((name, pairs))
    ms = block(js, "const MENTIONS = [", "];")
    if [m for m in re.findall(r'color: "var\(--(m\d)\)"', ms)] != list(MS):
        bad.append(("mention ramp", re.findall(r'color: "var\(--([a-z0-9]+)\)"', ms)))
    if 'stroke="var(--edge)"' not in top(js, "stackedBars"):
        bad.append("the stacked bars lost their ink edge")
    return not bad, f"problems {bad[:4]}"


SERIES_PROG = r"""
STORE.profile = input.profile;
const years = [2022, 2023, 2024, 2025];
const rows = input.rows;
CAP.length = 0;
const html = mentionEvolutionCard(years, rows) + doubletteCharts(input.d, years, input.sem, input.rps);
const out = CAP.map((s) => s.map((x) => ({ name: x.name, color: x.color || null, dash: x.dash === undefined ? null : x.dash })));
process.stdout.write(JSON.stringify({ out, html }));
"""


def charts_distinct(js: str):
    """Every line of each evolution chart: its own colour token and its own dash (rendered, crafted inputs)."""
    r = node(harness(js) + SERIES_PROG, crafted_inputs()[0])
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    for ch in o["out"]:
        cols = [x["color"] for x in ch]
        dashes = [x["dash"] for x in ch]
        if any(not col or "--c" in col and "--c5" not in col for col in cols):
            bad.append(("no own colour", cols))
        voie = all(col and "--voie-" in col for col in cols)            # the bac routes: their own named colours, solid
        if not voie and (any(d is None for d in dashes) or len(set(dashes)) != len(dashes)):
            bad.append(("dashes", dashes))
        if not voie and len(set(cols)) != len(cols):
            bad.append(("same colour twice", cols))
    return not bad and len(o["out"]) >= 3, f"{len(o['out'])} charts drawn; problems {bad[:4]}"


@check("EV3 wiring: every line its token colour and own dash, mention bars on the m ramp with the ink edge, never the grey ramp")
def ev3(c: Ctx):
    a, da = wiring_ok(c.js, c.css)
    b, db = charts_distinct(c.js)
    return a and b, f"static {da}; rendered {db}"


# ------------------------------------------------------------------ EV4 the mention reading
def py_band(p):
    g = p.get("moyenne")
    if isinstance(g, (int, float)) and 8 <= g <= 20:
        g = round(g * 10) / 10
        m = "rattrapage" if g < 10 else "sansmention" if g < 12 else next((k for k in ("ab", "b", "tb") if BANDS[k][0] <= g < BANDS[k][1]), "tbf")
        return m, g
    return p.get("mention"), None


def py_within(g, band, model):
    lo, hi, mid = BANDS[band]
    x = min(max(g, lo), hi)
    if model == "uniforme":
        return (x - lo) / (hi - lo)
    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))  # noqa: E731
    a, b = phi(lo - mid), phi(hi - mid)
    return (phi(x - mid) - a) / (b - a)


def py_mention_years(rows, profile):
    m, g = py_band(profile)
    band = "sansmention" if m == "rattrapage" else m
    out = []
    for r in rows:
        counts = {k: (r or {}).get(f"acc_{k}") or 0 for k in LADDER}
        n = sum(counts.values())
        if not r or not n:
            out.append(None)
            continue
        below = sum(counts[k] for k in LADDER[:LADDER.index(band)])
        moy = rng = None
        if g is not None:
            gb = "sansmention" if g < 12 else band
            bl = sum(counts[k] for k in LADDER[:LADDER.index(gb)])
            nn, uu = (bl + py_within(g, gb, "normale") * counts[gb]) / n, (bl + py_within(g, gb, "uniforme") * counts[gb]) / n
            moy, rng = 100 * nn, [100 * min(nn, uu), 100 * max(nn, uu)]
        out.append({"n": n, "below": 100 * below / n, "upto": 100 * (below + counts[band]) / n, "moy": moy, "moyRange": rng})
    return out


MENTION_PROG = r"""
const res = input.cases.map((k) => { STORE.profile = k.profile; const vp = vxProfile(k.profile); return mentionYears(k.rows, vp); });
process.stdout.write(JSON.stringify(res));
"""

PROFILES = [{"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "statut": "terminale"},
            {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "moyenne": 14.6, "statut": "terminale"},
            {"serie": "bt", "mention": "sansmention", "statut": "terminale"},
            {"serie": "bg", "spe1": "SVT", "spe2": "PC", "mention": "rattrapage", "moyenne": 9.4, "statut": "terminale"},
            {"serie": "bg", "spe1": "SVT", "spe2": "PC", "mention": "tbf", "moyenne": 20, "statut": "terminale"},
            {"serie": "bp", "mention": "ab", "moyenne": 12.0, "statut": "terminale"}]


def crafted_rows():
    return [{"acc_sansmention": 10, "acc_ab": 20, "acc_b": 15, "acc_tb": 4, "acc_tbf": 1, "acc_mention_non_renseignee": 3},
            None,
            {"acc_sansmention": 0, "acc_ab": 0, "acc_b": 0, "acc_tb": 0, "acc_tbf": 0},
            {"acc_sansmention": 3, "acc_ab": 5, "acc_b": 8, "acc_tb": 2, "acc_tbf": 0}]


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return abs(a - b) < 1e-7


def mention_ok(js: str, con):
    cases = [{"profile": p, "rows": crafted_rows()} for p in PROFILES]
    if con is not None:
        lids = [x for (x,) in con.execute("""SELECT lineage_id FROM core.lineage GROUP BY 1 HAVING count(*) >= 3
                                              ORDER BY hash(lineage_id) LIMIT 40""").fetchall()]
        for i, lid in enumerate(lids):
            got = {s: dict(zip(("acc_sansmention", "acc_ab", "acc_b", "acc_tb", "acc_tbf"), v)) for s, *v in con.execute(
                """SELECT fy.session, fy.acc_sansmention, fy.acc_ab, fy.acc_b, fy.acc_tb, fy.acc_tbf FROM core.lineage l
                   JOIN core.formation_year fy USING (session, cod_aff_form) WHERE l.lineage_id = ?""", [lid]).fetchall()}
            cases.append({"profile": PROFILES[i % len(PROFILES)], "rows": [got.get(y) for y in (2022, 2023, 2024, 2025)]})
    r = node(harness(js) + MENTION_PROG, {"cases": cases})
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    got, bad = json.loads(r), []
    for k, g in zip(cases, got):
        want = py_mention_years(k["rows"], k["profile"])
        for y, (a, b) in enumerate(zip(g, want)):
            if (a is None) != (b is None):
                bad.append((k["profile"].get("mention"), y, "a year appears or vanishes"))
                continue
            if a is None:
                continue
            if a["n"] != b["n"] or not all(close(a[f], b[f]) for f in ("below", "upto", "moy", "moyRange")):
                bad.append((k["profile"].get("mention"), k["profile"].get("moyenne"), y, a, b))
    hand = got[0][0]["upto"] == 100 * 45 / 50 and got[0][0]["below"] == 60 and got[0][1] is None and got[0][2] is None
    return not bad and hand, f"{len(cases)} lineages x profiles re-read in Python; hand case {hand}; problems {bad[:3]}"


@check("EV4 « Vous parmi les admis »: mention or lower, lower, below the average (R5), year by year = an independent Python reading")
def ev4(c: Ctx):
    return mention_ok(c.js, c.con)


# ------------------------------------------------------------------ EV5 the pair, year by year
def py_pick(rp, dk):
    rows = rp["doublettes"].get("bg") or []
    mine = next((x for x in rows if x["key"] == dk), None)
    if mine:
        return mine
    if any(x["key"] is None and not x["autres"] for x in rows):
        return None
    return next((x for x in rows if x["autres"]), None)


def py_pair(rps, years, dk, est):
    out = []
    for i, y in enumerate(years):
        rp = next((x for x in rps if x["session"] == y), None)
        if dk and rp and (rp["doublettes"].get("bg") or []):
            r = py_pick(rp, dk)
            out.append(("pub", r["taux"], (r["confirmes"] or 0) < 20) if r else ("absent", None, False))
        else:
            out.append(("est", est[i] if est else None, False))
    return out


def crafted_inputs():
    """Two crafted pages: own reports in 2023 (no pair line: « Autres ») and 2025 (the pair, 12 confirmed), an unknown label in
    2024 (no point), estimates in 2022; and a page whose group is missing but whose own report detailed the pair."""
    bgt = [{"session": y, "taux": t, "candidats": 40} for y, t in zip((2022, 2023, 2024, 2025), (50, 40, 30, 20))]
    d = {"status": "ok", "series": {"bg": {"taux": 20, "fragile": False, "trend": bgt}, "bt": {"trend": bgt}, "bp": {"trend": bgt}},
         "groupe": {"label": "<b>Grp</b>", "tous": {"taux": 40, "trend": [{"session": y, "taux": 40} for y in (2022, 2023, 2024, 2025)]},
                    "doublettes": [{"key": "MATHS+SES", "label": "Maths <i>SES</i>", "taux": 60, "candidats": 300, "rare": False,
                                    "trend": [{"session": y, "taux": 60} for y in (2022, 2023, 2024, 2025)]}],
                    "autres": {"taux": 30, "candidats": 50, "trend": []}}}
    row = lambda k, a, c, p: {"libelle": "x", "key": k, "autres": a, "confirmes": c, "en_position": p, "taux": round(100 * p / c, 1)}  # noqa: E731
    rps = [{"session": 2023, "doublettes": {"bg": [row("SVT+PC", False, 80, 40), row(None, True, 50, 10)]}},
           {"session": 2024, "doublettes": {"bg": [row("SVT+PC", False, 80, 40), row(None, False, 30, 3), row(None, True, 40, 8)]}},
           {"session": 2025, "doublettes": {"bg": [row("MATHS+SES", False, 12, 9)]}},
           {"session": 2026, "doublettes": {"bg": [row("MATHS+SES", False, 99, 1)]}}]
    prof = {"serie": "bg", "spe1": "SES", "spe2": "MATHS", "mention": "ab", "statut": "terminale"}
    one = {"profile": prof, "rows": crafted_rows(), "d": d, "sem": None, "rps": rps}
    d2 = {**d, "status": "sans_groupe"}
    two = {"profile": prof, "rows": crafted_rows(), "d": d2, "sem": None, "rps": rps}
    return one, two


PAIR_PROG = r"""
const res = input.cases.map((k) => {
  STORE.profile = k.profile; CAP.length = 0;
  const html = doubletteCharts(k.d, [2022, 2023, 2024, 2025], k.sem, k.rps);
  const mine = CAP.flat().find((s) => s.name === "Vos deux spécialités dans cette formation") || null;
  return { html, mine: mine && { values: mine.values, marks: mine.marks, hollow: mine.hollow } };
});
process.stdout.write(JSON.stringify(res));
"""


def pair_ok(js: str, con, rapports_src: str | None = None):
    one, two = crafted_inputs()
    cases = [one, two]
    est_one = [round(min(100, t * 60 / 40) * 10) / 10 for t in (50, 40, 30, 20)]
    wants = [py_pair(one["rps"], [2022, 2023, 2024, 2025], "MATHS+SES", est_one), py_pair(two["rps"], [2022, 2023, 2024, 2025], "MATHS+SES", None)]
    if con is not None:
        mod = load_rapports(rapports_src)
        lids = [x for (x,) in con.execute("""SELECT l.lineage_id FROM core.rapport_doublette d JOIN core.lineage l USING (cod_aff_form, session)
                                              WHERE d.bac = 'bg' GROUP BY 1 ORDER BY count(DISTINCT d.session) DESC, hash(l.lineage_id) LIMIT 12""").fetchall()]
        for lid in lids:
            ys = [{"session": s, "cod_aff_form": cod} for s, cod in con.execute(
                "SELECT session, cod_aff_form FROM core.lineage WHERE lineage_id = ? ORDER BY session", [lid]).fetchall()]
            rps = mod.lineage_pairs(con, ys)
            keys = [k for (k,) in con.execute("""SELECT doublette_key FROM core.rapport_doublette d JOIN core.lineage l USING (cod_aff_form, session)
                     WHERE l.lineage_id = ? AND d.bac = 'bg' AND doublette_key IS NOT NULL GROUP BY 1 ORDER BY 1 LIMIT 1""", [lid]).fetchall()]
            dk = keys[0] if keys else "MATHS+SES"
            a, b = dk.split("+")
            dd = {"status": "sans_groupe", "series": {s: {"trend": []} for s in ("bg", "bt", "bp")}}
            cases.append({"profile": {"serie": "bg", "spe1": a, "spe2": b, "mention": "ab", "statut": "terminale"}, "rows": [], "d": dd, "sem": None, "rps": rps})
            wants.append(py_pair(rps, [2022, 2023, 2024, 2025], dk, None))
    r = node(harness(js) + PAIR_PROG, {"cases": cases})
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    got, bad = json.loads(r), []
    for i, (g, w) in enumerate(zip(got, wants)):
        m = g["mine"]
        vals = m["values"] if m else [None] * 4
        for y, (kind, v, hollow) in enumerate(w):
            if not close(vals[y], v):
                bad.append((i, 2022 + y, kind, vals[y], v))
            if m and kind == "pub" and (m["marks"][y] != "pub" or bool(m["hollow"][y]) != hollow):
                bad.append((i, 2022 + y, "mark or hollow", m["marks"][y], m["hollow"][y]))
            if m and kind != "pub" and m["marks"][y] == "pub":
                bad.append((i, 2022 + y, "a square without a published figure"))
        diamonds = g["html"].count('class="mk-est"')
        if diamonds != sum(1 for k, v, _ in w if k == "est" and v is not None):
            bad.append((i, "estimates not drawn as diamonds", diamonds))
        squares = g["html"].count('class="mk-pub"')
        if squares != sum(1 for k, v, _ in w if k == "pub" and v is not None):
            bad.append((i, "squares", squares))
        if (squares or diamonds) and ("carré : chiffre publié" not in g["html"] or "losange : estimation" not in g["html"]):
            bad.append((i, "squares without their key"))
        if "<b>Grp</b>" in g["html"] or "<i>SES</i>" in g["html"]:
            bad.append((i, "unescaped label"))
    hand = wants[0][0][0] == "est" and wants[0][1][:2] == ("pub", 20.0) and wants[0][2][0] == "absent" and wants[0][3][:2] == ("pub", 75.0)
    return not bad and hand, f"{len(cases)} pages ({len(cases) - 2} real lineages) re-read in Python; hand case {hand}; problems {bad[:4]}"


@check("EV5 the pair, year by year: own report that campaign (square), else the estimate; never both; no point on an unknown label")
def ev5(c: Ctx):
    return pair_ok(c.js, c.con, c.rapports_src)


# ------------------------------------------------------------------ EV6 the API
def load_rapports(src: str | None):
    if src is None:
        from suptracker import rapports
        return rapports
    spec = importlib.util.spec_from_loader("suptracker.rapports_ev", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "suptracker"
    mod.__file__ = str(ROOT / "suptracker" / "rapports.py")
    exec(compile(src, "rapports_ev.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


def crafted_con():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER, digest VARCHAR, capture VARCHAR, url VARCHAR,
                   confirmes INTEGER, en_position INTEGER, acceptes INTEGER, methode VARCHAR, n_formations INTEGER, source VARCHAR, recoupe BOOLEAN)""")
    con.execute("""CREATE TABLE core.rapport_doublette (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR, rang INTEGER, libelle VARCHAR,
                   doublette_key VARCHAR, autres BOOLEAN, confirmes INTEGER, classes INTEGER, en_position INTEGER, acceptes INTEGER)""")
    con.execute("CREATE TABLE core.rapport_masque (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR)")
    con.execute("""INSERT INTO core.rapport VALUES ('A', 2024, 'd1', '2024', 'u', 100, 50, 10, 'code', 1, 'archive', true),
                   ('A', 2025, 'd2', '2025', 'u', 90, 30, 10, 'code', 1, 'live', true), ('B', 2023, 'd3', '2023', 'u', 80, 20, 5, 'code', 1, 'archive', true),
                   ('A', 2026, 'd4', '2026', 'u', 70, 10, 5, 'code', 1, 'live', false), ('C', 2025, 'd5', '2025', 'u', 60, 10, 5, 'code', 1, 'live', false)""")
    con.execute("""INSERT INTO core.rapport_doublette VALUES ('A', 2024, 'bg', 1, 'Maths SES', 'MATHS+SES', false, 40, 40, 30, 20),
                   ('A', 2024, 'bt', 1, 'STMG', NULL, false, 10, 10, 5, 5), ('A', 2025, 'bg', 2, 'Autres', NULL, true, 30, 30, 7, 5),
                   ('A', 2025, 'bg', 1, 'SVT PC', 'PC+SVT', false, 3, 3, 3, 3), ('B', 2024, 'bg', 1, 'faux', 'MATHS+SES', false, 9, 9, 9, 9),
                   ('C', 2025, 'bg', 1, 'non recoupé', 'MATHS+SES', false, 9, 9, 1, 1)""")
    con.execute("INSERT INTO core.rapport_masque VALUES ('A', 2024, 'bg')")
    return con


def api_ok(c: Ctx):
    mod, bad = load_rapports(c.rapports_src), []
    cc = crafted_con()
    ys = [{"session": 2023, "cod_aff_form": "A"}, {"session": 2024, "cod_aff_form": "A"}, {"session": 2025, "cod_aff_form": "A"},
          {"session": 2024, "cod_aff_form": "B"}, {"session": 2025, "cod_aff_form": "C"}, {"session": 2026, "cod_aff_form": "A"}]
    got = mod.lineage_pairs(cc, ys)
    seen = [(r["cod_aff_form"], r["session"]) for r in got]
    if seen != [("A", 2024), ("A", 2025)]:
        bad.append(("crafted: another session, another code or a report not cross-checked", seen))
    else:
        a, b = got
        if [x["key"] for x in a["doublettes"]["bg"]] != ["MATHS+SES"] or a["doublettes"]["bg"][0]["taux"] != 75.0 or not a["masque_bg"]:
            bad.append(("crafted 2024", a))
        if [x["key"] for x in b["doublettes"]["bg"]] != ["PC+SVT", None] or b["doublettes"]["bg"][1]["taux"] != round(700 / 30, 1) \
                or b["archive"] != "u" or a["archive"] != "https://web.archive.org/web/2024/u":
            bad.append(("crafted 2025: order, rate or link", b))
    n = 0
    if c.con is not None:
        lids = [x for (x,) in c.con.execute("""SELECT l.lineage_id FROM core.rapport r JOIN core.lineage l USING (cod_aff_form, session)
                                                GROUP BY 1 ORDER BY count(*) DESC, hash(l.lineage_id) LIMIT 25""").fetchall()]
        for lid in lids:
            ys = [{"session": s, "cod_aff_form": cod} for s, cod in c.con.execute(
                "SELECT session, cod_aff_form FROM core.lineage WHERE lineage_id = ? ORDER BY session", [lid]).fetchall()]
            for r in mod.lineage_pairs(c.con, ys):
                n += 1
                want = [(lib, k, au, cf, p, None if not cf or p is None else round(100 * p / cf, 1)) for lib, k, au, cf, p in c.con.execute(
                    """SELECT libelle, doublette_key, autres, confirmes, en_position FROM core.rapport_doublette
                       WHERE cod_aff_form = ? AND session = ? AND bac = 'bg' ORDER BY rang""", [r["cod_aff_form"], r["session"]]).fetchall()]
                have = [(x["libelle"], x["key"], x["autres"], x["confirmes"], x["en_position"], x["taux"]) for x in r["doublettes"]["bg"]]
                if have != want or not any(y == {"session": r["session"], "cod_aff_form": r["cod_aff_form"]} for y in ys):
                    bad.append((lid, r["session"]))
    route = '"rapports": RP.lineage_pairs(_con().cursor(), res)' in c.api
    if not route:
        bad.append("the lineage route does not serve the reports")
    return not bad, f"crafted fallbacks refused; {n} real report blocks re-read; route {route}; problems {bad[:3]}"


@check("EV6 the API: /api/lineage's reports = that code, that session, cross-checked, its bac général lines as published")
def ev6(c: Ctx):
    return api_ok(c)


# ------------------------------------------------------------------ EV7 privacy and words
def literals(src: str) -> list[str]:
    """The text of every string literal of a piece of JS (templates with their ${...} replaced by « x »), nesting-aware."""
    out, i, n = [], 0, len(src)

    def skip_expr(j):                      # from after "${" to its closing "}", over nested strings and templates
        depth = 1
        while j < n and depth:
            ch = src[j]
            if ch in "\"'`":
                j = read(j)[1]
                continue
            depth += ch == "{"
            depth -= ch == "}"
            j += 1
        return j

    def read(j):                           # a literal starting at src[j]: (its text, the index after it)
        q, j, buf = src[j], j + 1, []
        while j < n and src[j] != q:
            if src[j] == "\\":
                buf.append(src[j + 1:j + 2])
                j += 2
            elif q == "`" and src.startswith("${", j):
                buf.append(" x ")
                j = skip_expr(j + 2)
            else:
                buf.append(src[j])
                j += 1
        out.append("".join(buf))
        return "".join(buf), j + 1

    while i < n:
        if src[i] in "\"'`" and not (src[i] == "'" and i and src[i - 1].isalpha()):
            i = read(i)[1]
        elif src.startswith("//", i):
            i = src.find("\n", i) if src.find("\n", i) != -1 else n
        else:
            i += 1
    return out


def words(text: str) -> int:
    return len(re.findall(r"[\wÀ-ÿ’'-]+", re.sub(r"<[^>]+>|\$\{[^}]*\}", " x ", text)))


def privacy_ok(js: str):
    bad = []
    evo = block(js, "async function viewEvolution(", "\nasync function viewCompare(")
    calls = re.findall(r"api\(`([^`]*)`", evo)
    if calls != ["/api/formation/${encodeURIComponent(cod)}", "/api/lineage/${encodeURIComponent(f.record.lineage_id)}"]:
        bad.append(("requests", calls))
    page = evo + block(js, "function doubletteCharts(", "\n// ---- Sprint") + block(js, "function mentionEvolutionCard(", "\nasync function viewEvolution(") \
        + block(js, "function pairByYear(", "\nfunction doubletteCharts(")
    if CHANCE.search(page):
        bad.append(("a chance word", CHANCE.search(page).group(0)))
    if "pas des chances" not in block(js, "function mentionEvolutionCard(", "\nasync function viewEvolution(") or "pas des chances" not in js[js.find("const DBL_CAVEAT"):js.find("const DBL_CAVEAT") + 400]:
        bad.append("the « pas des chances » line is gone")
    men = block(js, "function mentionEvolutionCard(", "\nasync function viewEvolution(")
    if "estimTag(" not in men or "(estimation)" not in men:
        bad.append("the average's line is not labelled an estimation")
    texts = literals(block(js, "function pairByYear(", "\n// ---- Sprint") + men)
    for t in texts:
        t = re.sub(r"</?(?:h\d|p|div|li|summary|details)\b[^>]*>", " . ", t)          # a block ends a sentence
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"<[^>]+>", " ", t)):
            if words(sentence) > 30:
                bad.append(("long sentence", words(sentence), sentence[:80]))
    if len(texts) < 20:
        bad.append(("too few texts read", len(texts)))
    return not bad, f"requests {len(calls)}; problems {bad[:3]}"


@check("EV7 privacy and words: no profile key sent, escaped labels, « pas des chances », the average an estimation, sentences <= 30 words")
def ev7(c: Ctx):
    return privacy_ok(c.js)


# ------------------------------------------------------------------ EV8 accessibility
A11Y_PROG = r"""
const res = input.cases.map((k) => { STORE.profile = k.profile; return mentionEvolutionCard([2022, 2023, 2024, 2025], k.rows); });
process.stdout.write(JSON.stringify(res));
"""


def a11y_ok(js: str):
    one, _ = crafted_inputs()
    r = node(harness(js) + SERIES_PROG, one)
    cards = node(harness(js) + A11Y_PROG, {"cases": [{"profile": None, "rows": crafted_rows()},
                                                     {"profile": {"statut": "reorientation", "mention": "b"}, "rows": crafted_rows()},
                                                     {"profile": {"serie": "bg", "statut": "terminale"}, "rows": crafted_rows()}]})
    if r is None or cards is None:
        return True, "node not installed"
    if r.startswith("__error__") or cards.startswith("__error__"):
        return False, (r + cards)[-600:]
    html, bad = json.loads(r)["html"], []
    svgs = re.findall(r'<svg class="chart"[^>]*>', html)
    for s in svgs:
        lab = re.search(r'aria-label="([^"]*)"', s)
        if 'role="img"' not in s or not lab or not lab.group(1).startswith("Graphique") or "2022–2025" not in lab.group(1):
            bad.append(("unnamed chart", s[:120]))
    if html.count('<div class="legend">') < len(svgs):
        bad.append("a chart without its legend")
    none, reo, nomention = json.loads(cards)
    if 'href="#/profil"' not in none or reo != "" or 'href="#/profil"' not in nomention:
        bad.append(("profile prompts", none[:80], reo[:80], nomention[:80]))
    return not bad, f"{len(svgs)} charts named with their legend; prompts ok; problems {bad[:3]}"


@check("EV8 accessibility: every chart named with its series and years after its legend; prompts without a profile, none outside terminale")
def ev8(c: Ctx):
    return a11y_ok(c.js)


# ------------------------------------------------------------------ EV9 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
const [base, cod, lid] = process.argv.slice(2);
const PROFILES = {
  bgmoy: { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b", moyenne: 14.6, statut: "terminale" },
  bt: { serie: "bt", mention: "ab", statut: "terminale", voie: "autre" }, none: null,
  reo: { statut: "reorientation" } };
(async () => {
  const b = await chromium.launch(); const o = {}; const errs = [];
  const lin = await (await fetch(`${base}/api/lineage/${encodeURIComponent(lid)}`)).json();
  for (const [name, opts] of [["light", { viewport: { width: 1280, height: 900 }, colorScheme: "light" }],
    ["dark", { viewport: { width: 1280, height: 900 }, colorScheme: "dark" }], ["phone", { ...devices["Pixel 5"] }],
    ["small", { viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true }]]) {
    for (const prof of Object.keys(PROFILES)) {
      if (name !== "light" && prof !== "bgmoy") continue;
      const ctx = await b.newContext(opts);
      await ctx.addInitScript((p) => { if (p) localStorage.setItem("profile", JSON.stringify(p)); }, PROFILES[prof]);
      const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(`${name}/${prof}: ${e.message}`));
      await p.goto(`${base}/#/evolution/${cod}`);
      await p.waitForSelector(".charts", { timeout: 60000 }); await p.waitForTimeout(800);
      o[`${name}/${prof}`] = await p.evaluate(() => ({
        charts: document.querySelectorAll("svg.chart").length,
        named: [...document.querySelectorAll("svg.chart")].every((s) => (s.getAttribute("aria-label") || "").startsWith("Graphique")),
        squares: document.querySelectorAll("svg.chart rect.mk-pub").length,
        mention: !!([...document.querySelectorAll("h2")].find((h) => h.textContent.startsWith("Vous parmi les admis"))),
        hs: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
      await ctx.close();
    }
  }
  process.stdout.write(JSON.stringify({ errs, o, rapports: lin.rapports || [] })); await b.close();
})();
"""


def browser_ok(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    row = c.con.execute("""SELECT l.lineage_id, max(l.cod_aff_form) FILTER (WHERE l.session = (SELECT max(session) FROM core.lineage))
                           FROM core.rapport_doublette d JOIN core.lineage l USING (cod_aff_form, session)
                           WHERE d.bac = 'bg' AND d.doublette_key = 'MATHS+SES' GROUP BY 1 HAVING count(DISTINCT d.session) >= 2
                              AND max(l.cod_aff_form) FILTER (WHERE l.session = (SELECT max(session) FROM core.lineage)) IS NOT NULL
                           ORDER BY 1 LIMIT 1""").fetchone()
    if not row:
        return False, "no lineage with two reports detailing MATHS+SES"
    lid, cod = row
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".evolution_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod, lid], capture_output=True, text=True, timeout=500, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-600:]
    d = json.loads(r.stdout)
    want = sum(1 for rp in d["rapports"] if py_pick(rp, "MATHS+SES") and py_pick(rp, "MATHS+SES")["taux"] is not None)
    bad = [("JS errors", d["errs"][:2])] if d["errs"] else []
    for k, v in d["o"].items():
        if v["hs"] or not v["named"] or v["charts"] < 5:
            bad.append((k, v))
        if k.endswith("bgmoy") and (v["squares"] != want or not v["mention"]):
            bad.append((k, "squares", v["squares"], want))
        if k.endswith("/reo") and v["mention"]:
            bad.append((k, "a mention card outside terminale"))
    return not bad, f"{len(d['o'])} screens on lineage {lid}; {want} published years; problems {bad[:3]}"


@check("EV9 browser: light, dark, phone, 320 px; profiles bg + average, techno, none, reorientation; squares = published years")
def ev9(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    return browser_ok(c)


# ------------------------------------------------------------------ EV10 quality score
def review(css: str):
    if not REVIEW.exists():
        return None, "no independent review"
    r = json.loads(REVIEW.read_text())
    crit = r.get("criteria", {})
    if len(crit) < 10 or not all("why" in v and 0 <= v.get("score", -1) <= 10 for v in crit.values()) or not r.get("screenshots"):
        return None, "the review lacks its criteria, reasons or screenshots"
    if sum(v["score"] for v in crit.values()) != r.get("total"):
        return None, "the review's total is not the sum of its criteria"
    return r, f"review {r['total']}/100 over {len(crit)} criteria on {r.get('date')}"


def combined(measured: float, review_total: float) -> float:
    return 0.6 * measured + 0.4 * review_total


@check("EV10 quality: 0.6 x measured (EV1-EV9) + 0.4 x independent screenshot review >= 90, the review alone >= 80 (owner)")
def ev10(c: Ctx):
    measured = 0
    for fn in CHECKS:
        cid = fn.check_name.split()[0]
        if cid in WEIGHTS:
            ok, det = c.results[cid] if cid in getattr(c, "results", {}) else fn(c)     # already run in this pass: reused
            if cid == "EV9" and "skipped" in det:
                ok = bool(json.loads(REVIEW.read_text()).get("browser_ok")) if REVIEW.exists() else False   # the nightly run measures it
            measured += WEIGHTS[cid] if ok else 0
    r, rdet = review(c.css)
    if r is None:
        return False, f"measured {measured}/100; {rdet}"
    score = combined(measured, r["total"])
    return score >= 90 and r["total"] >= 80, f"quality {round(score, 1)}/100 = 0.6 x {measured} + 0.4 x {r['total']}; {rdet}"


# ------------------------------------------------------------------ EV11 mutation test
def js_mut(old, new):
    return ("js", old, new)


MUTANTS = [
    ("k2 drifts onto the accent", ("css", "--k2: #d0475f; --k3: #2b8cbe; --k4: #71697a;\n", "--k2: #b0105a; --k3: #2b8cbe; --k4: #71697a;\n"), "EV2"),
    ("a dark block drifts", ("css_last", "--k3: #3f95d0;", "--k3: #3f95d1;"), "EV1"),
    ("k3 too close to k1 for colour-blind eyes", ("css", "--k3: #2b8cbe; --k4: #71697a;\n", "--k3: #1f3a7a; --k4: #71697a;\n"), "EV2"),
    ("the mention ramp out of order", ("css_all", "--m1: #2b1a10; --m2: #5e3a20; --m3: #a0703f; --m4: #dcae78; --m5: #f6e3c4;\n", "--m1: #2b1a10; --m2: #a0703f; --m3: #5e3a20; --m4: #dcae78; --m5: #f6e3c4;\n"), "EV2"),
    ("a pale line on the card", ("css", "--k4: #71697a;\n", "--k4: #c8c2cf;\n"), "EV2"),
    ("print keeps the dark palette", ("css", "--k1: #1f2f57; --k2: #d0475f; --k3: #2b8cbe; --k4: #71697a; --m1", "--k1: #e8e2d0; --k2: #d0475f; --k3: #2b8cbe; --k4: #71697a; --m1"), "EV1"),
    ("a grey ramp line again", js_mut('["pct_f", EVO.k2, "6 4"]', '["pct_f", "var(--c3)", "6 4"]'), "EV3"),
    ("two lines with one dash", js_mut('["pct_aca_orig", EVO.k3, "2 3"]', '["pct_aca_orig", EVO.k3, "6 4"]'), "EV3"),
    ("the bars lose their edge", js_mut(' stroke="var(--edge)" stroke-width="1"><title>', '><title>'), "EV3"),
    ("a mention on the grey ramp", js_mut('{ key: "acc_b", name: "Bien", color: "var(--m3)" }', '{ key: "acc_b", name: "Bien", color: "var(--c3)" }'), "EV3"),
    ("the band counted in « lower »", js_mut("for (const m of LADDER) { if (m === band) break; below += counts[m]; }\n    const pm",
                                            "for (const m of LADDER) { below += counts[m]; if (m === band) break; }\n    const pm"), "EV4"),
    ("the uniform spread as the estimate", js_mut("moy: pm ? 100 * pm.normale : null", "moy: pm ? 100 * pm.uniforme : null"), "EV4"),
    ("unknown mentions in the denominator", js_mut("const n = counts ? LADDER.reduce((a, m) => a + counts[m], 0) : 0;",
                                                   "const n = counts ? LADDER.reduce((a, m) => a + counts[m], 0) + (r.acc_mention_non_renseignee || 0) : 0;"), "EV4"),
    ("rattrapage read in its own band", js_mut('const band = vp.mention === "rattrapage" ? "sansmention" : vp.mention, g = vp.moyenne;',
                                               'const band = vp.mention === "rattrapage" ? "ab" : vp.mention, g = vp.moyenne;'), "EV4"),
    ("an estimate where the report has no row", js_mut("return r ? { ...r, session: y } : { absent: true, session: y };", "return r ? { ...r, session: y } : null;"), "EV5"),
    ("the estimate beside the published year", js_mut("const vals = own.map((o, i) => (o ? (o.absent ? null : o.taux) : estAt[i]));",
                                                       "const vals = own.map((o, i) => (o && !o.absent && estAt[i] == null ? o.taux : estAt[i] ?? (o && !o.absent ? o.taux : null)));"), "EV5"),
    ("« Autres » beside an unknown label", js_mut("if (rows.some((x) => x.key == null && !x.autres)) return null;     // a pair label", "if (false) return null;     // a pair label"), "EV5"),
    ("estimates drawn as ordinary round points", js_mut(': s.marks?.[i] === "est" ? `<path class="mk-est"', ': s.marks?.[i] === "xx" ? `<path class="mk-est"'), "EV5"),
    ("published points drawn round", js_mut('s.marks?.[i] === "pub" ? `<rect class="mk-pub"', 's.marks?.[i] === "xx" ? `<rect class="mk-pub"'), "EV5"),
    ("a small report counted as solid", js_mut("hollow: own.map((o) => !!o && !o.absent && (o.confirmes || 0) < DBL_SEUIL)", "hollow: own.map(() => false)"), "EV5"),
    ("the key forgotten", js_mut("${vals.some((v) => v != null) ? markKey(EVO.k1) : \"\"}", ""), "EV5"),
    ("an escaped group label no more", js_mut("et le groupe «\\u00a0${esc(g.label)}\\u00a0» (national)", "et le groupe «\\u00a0${g.label}\\u00a0» (national)"), "EV5"),
    ("a report of another session", ("py", "WHERE cod_aff_form = ? AND session = ? AND {ok_col}", "WHERE cod_aff_form = ? AND session <= ? AND {ok_col}"), "EV6"),
    ("a report not cross-checked", ("py", "AND {ok_col}\"\"\", [cod, s]", "\"\"\", [cod, s]"), "EV6"),
    ("lines out of order", ("py", "AND bac = 'bg' ORDER BY rang", "AND bac = 'bg' ORDER BY libelle"), "EV6"),
    ("the profile sent with the lineage", js_mut("api(`/api/lineage/${encodeURIComponent(f.record.lineage_id)}`)",
                                                 "api(`/api/lineage/${encodeURIComponent(f.record.lineage_id)}?mention=${bacProfile() ? bacProfile().mention : \"\"}`)"), "EV7"),
    ("a chance word", js_mut("Des parts d'admis, pas des chances d'admission.", "Vos chances d'admission."), "EV7"),
    ("the average's line not an estimation", js_mut("${vp.moyenne !== null ? estimTag(", "${vp.moyenne !== null ? String("), "EV7"),
    ("a long sentence", js_mut("Plus la part est haute, plus les admis de la formation avaient une mention comme la vôtre ou plus basse.",
                               "Plus la part est haute et plus elle monte d'année en année, plus les admis de la formation avaient eu au bac une mention identique à la vôtre ou bien une mention plus basse que la vôtre."), "EV7"),
    ("a mention card outside terminale", js_mut("if (isReo(raw)) return \"\";", "if (false) return \"\";"), "EV8"),
]

FN = {"EV1": lambda c: tokens_ok(c.css), "EV2": lambda c: palette_ok(c.css), "EV3": lambda c: (wiring_ok(c.js, c.css)[0] and charts_distinct(c.js)[0], ""),
      "EV4": lambda c: mention_ok(c.js, None), "EV5": lambda c: pair_ok(c.js, None, c.rapports_src), "EV6": lambda c: api_ok(c),
      "EV7": lambda c: privacy_ok(c.js), "EV8": lambda c: a11y_ok(c.js)}


@check("EV11 mutation test: palette, wiring, reading, API and wording bugs are each caught (in memory)")
def ev11(c: Ctx):
    if not shutil.which("node"):
        return True, "skipped (node not installed)"
    missed, ran = [], 0
    for name, (kind, old, new), cid in MUTANTS:
        src = {"css": c.css, "css_last": c.css, "css_all": c.css, "js": c.js, "py": c.rapports_src}[kind]
        if kind == "css_all":                        # every theme block at once (the dark blocks repeat the light ramp)
            if not src.count(old):
                missed.append((name, "anchor not found"))
                continue
            mut, kind = src.replace(old, new), "css"
        elif kind == "css_last":                       # the second dark block only (the same values as the first)
            if src.count(old) != 2:
                missed.append((name, "anchor not found twice"))
                continue
            k = src.rfind(old)
            mut, kind = src[:k] + new + src[k + len(old):], "css"
        elif src.count(old) != 1:
            missed.append((name, "anchor not found once"))
            continue
        else:
            mut = src.replace(old, new)
        cm = Ctx(None, js=mut if kind == "js" else c.js, css=mut if kind == "css" else c.css, rapports_src=mut if kind == "py" else c.rapports_src)
        cm.api = c.api
        ran += 1
        try:
            ok = FN[cid](cm)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    return not missed, f"{ran - len([m for m in missed if isinstance(m, str)])}/{len(MUTANTS)} mutants caught; missed {missed}"


# ------------------------------------------------------------------ EV12 docs
@check("EV12 wiring and docs: test file, durations, nightly browser suite, README section, CLAUDE.md rule")
def ev12(c: Ctx):
    test = (ROOT / "tests" / "test_evolution.py").exists()
    dur = '"tests/test_evolution.py"' in (ROOT / "tests" / "durations.json").read_text()
    nightly = '"evolution": ("EV9",)' in (ROOT / "scripts" / "browser_nightly.py").read_text()
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
    doc = "redteam_evolution" in readme and "redteam_evolution" in claude
    return test and dur and nightly and doc, f"test {test}; durations {dur}; nightly {nightly}; README + CLAUDE.md {doc}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    c.results = {}
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        c.results[fn.check_name.split()[0]] = (bool(ok), detail)
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real, set(a.only.split(",")) if a.only else None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
