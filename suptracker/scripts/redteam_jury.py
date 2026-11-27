"""Red team: « Ce que regarde le jury » (owner, 2026-11-27), the search page's filter on the weights the fiche's jury publishes.

    python scripts/redteam_jury.py [--db data/suptracker.duckdb] [--real] [--browser]

  JU1 cut points re-derived: own reading of the verified grids (a field not listed weighs 0), own rule (multiples of 5, every
      band >= a tenth, the pair nearest a third each, smallest first), the counts and words of META.jury; real data: the grids'
      own file (data/fiches/champs.csv) gives the same weights
  JU2 the layer: every formation (and apprenticeship offer) carries its OWN five weights in the fixed order, or none without a
      verified grid; never another code's
  JU3 the page's twins: juryLevel = jury.level on every weight and every field's cut points; JURY_KEYS = jury.CHAMPS; the filter
      (OR inside a field, AND between fields, no grid = left out), the counts beside each level, the « sans grille » count
  JU4 what a student reads: one dropdown « Ce que regarde le jury », five fields, three levels drawn as bars 1-3 with their words
      and % range; « la fiche fait foi », « ni une note, ni une chance »; escaped; never a sort by a weight; the card's line
  JU5 the API: /api/meta carries the five fields (no parameter, computed once per warehouse); the filière robustesse filter is
      gone from the page while its repère stays in the payload
  JU6 browser: the dropdown, ticking two levels narrows the list to what the twins expect, the card's line, phone width, 0 JS error
  JU7 mutation test
  JU8 wiring and docs
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []

import nodefile  # noqa: E402
import redteam_robustesse as RB  # noqa: E402

top = RB.top
HOSTILE = '<img src=x onerror=alert(1)>'
OWN_CHAMPS = ["Résultats scolaires", "Engagement et activités", "Motivation", "Savoir-être", "Méthodes de travail"]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool, browser: bool):
        import duckdb
        self.db, self.real, self.browser = Path(db), real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.css = (ROOT / "suptracker" / "static" / "style.css").read_text()
        self.jury_src = (ROOT / "suptracker" / "jury.py").read_text()
        self.J = None

    def jury(self):
        """The module under test (a mutant may replace it)."""
        if self.J is None:
            from suptracker import jury
            self.J = jury
        return self.J


def own_weights(con) -> dict:
    try:
        rows = con.execute("""SELECT c.cod_aff_form, c.champ, c.poids FROM core.fiche_champ c
            WHERE c.cod_aff_form IN (SELECT cod_aff_form FROM core.fiche_grille WHERE grille)""").fetchall()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for cod, champ, poids in rows:
        if champ in OWN_CHAMPS:
            out.setdefault(cod, [0, 0, 0, 0, 0])[OWN_CHAMPS.index(champ)] = poids
    return out


def own_cuts(vals: list) -> tuple | None:
    n = len(vals)
    best = None
    for a in range(5, 100, 5):
        for b in range(a + 5, 100, 5):
            p = (sum(v < a for v in vals), sum(a <= v < b for v in vals), sum(v >= b for v in vals))
            if not n or min(p) < 0.10 * n:
                continue
            g = max(abs(x / n - 1 / 3) for x in p)
            if best is None or g < best[0] - 1e-12:
                best = (g, a, b)
    return (best[1], best[2]) if best else None


def own_level(v, c):
    return None if v is None or not c else "peu" if v < c[0] else "moyen" if v < c[1] else "beaucoup"


# ------------------------------------------------------------------ JU1
@check("JU1 cut points re-derived (multiples of 5, bands >= a tenth, nearest a third), counts and words; the grids' file agrees")
def ju1(c: Ctx):
    J = c.jury()
    bad = []
    W = own_weights(c.con)
    m = J.meta(c.con)
    if m["n_grilles"] != len(W):
        bad.append(("grids", m["n_grilles"], len(W)))
    keys = [x["key"] for x in m["champs"]]
    for i, name in enumerate(OWN_CHAMPS):
        vals = [w[i] for w in W.values()]
        want = own_cuts(vals)
        got = next((x for x in m["champs"] if x["champ"] == name), None)
        if want is None:
            if got:
                bad.append((name, "a field with no usable cut points is offered"))
            continue
        if not got or tuple(got["cuts"]) != want:
            bad.append((name, got and got["cuts"], want))
            continue
        n = {lv: sum(own_level(v, want) == lv for v in vals) for lv in ("peu", "moyen", "beaucoup")}
        if got["n"] != n or sum(n.values()) != len(W):
            bad.append((name, "counts", got["n"], n))
        a, b = want
        if got["labels"]["peu"] != f"moins de {a} %" or got["labels"]["beaucoup"] != f"{b} % ou plus" \
                or (b - 1 > a and got["labels"]["moyen"] != f"de {a} à {b - 1} %"):
            bad.append((name, "words", got["labels"]))
    # crafted: skewed fields (the minimum band binds) and an unverified grid (never read), whatever the data holds
    for vals in ([0] * 80 + [50] * 10 + [100] * 10, [5] * 50 + [10] * 30 + [20] * 15 + [40] * 5, list(range(0, 100, 3)), [0] * 95 + [10] * 5):
        if J.cuts(vals) != own_cuts(vals):
            bad.append(("crafted cut points", J.cuts(vals), own_cuts(vals)))
    import duckdb
    k = duckdb.connect()
    k.execute("CREATE SCHEMA core")
    k.execute("CREATE TABLE core.fiche_grille (cod_aff_form VARCHAR, session INTEGER, lu_le VARCHAR, url VARCHAR, grille BOOLEAN)")
    k.execute("CREATE TABLE core.fiche_champ (cod_aff_form VARCHAR, rang INTEGER, champ VARCHAR, poids INTEGER)")
    k.execute("INSERT INTO core.fiche_grille VALUES ('1', 2026, NULL, NULL, true), ('2', 2026, NULL, NULL, false)")
    k.execute("INSERT INTO core.fiche_champ VALUES ('1', 1, 'Motivation', 60), ('1', 2, 'Résultats scolaires', 40), ('2', 1, 'Motivation', 100)")
    if J.weights(k) != {"1": [40, 0, 60, 0, 0]} or own_weights(k) != {"1": [40, 0, 60, 0, 0]}:
        bad.append(("crafted grids: a field not listed = 0, an unverified grid never read", J.weights(k)))
    k.close()
    if c.real and W:
        if keys != ["res", "eng", "mot", "se", "met"]:
            bad.append(("the five fields on real data", keys))
        f = ROOT / "data" / "fiches" / "champs.csv"
        if f.exists():
            raw = {}
            for r in csv.DictReader(f.open(encoding="utf-8")):
                if r["cod_aff_form"] in W and r["champ"] in OWN_CHAMPS:
                    raw.setdefault(r["cod_aff_form"], [0] * 5)[OWN_CHAMPS.index(r["champ"])] = int(r["poids"])
            diff = [k for k in W if raw.get(k, [0] * 5) != W[k]]
            if diff:
                bad.append(("the warehouse's weights differ from the fiches' file", diff[:3]))
        if any(sum(w) != 100 for w in W.values()):
            bad.append("a verified grid whose weights do not sum to 100")
    return not bad, f"{len(W)} grids; cuts {[(x['key'], x['cuts']) for x in m['champs']]}; problems {bad[:4]}"


# ------------------------------------------------------------------ JU2
@check("JU2 layer: each formation and offer carries its OWN five weights in the fixed order, none without a verified grid")
def ju2(c: Ctx):
    from suptracker import carte as CA
    W = own_weights(c.con)
    by_dip, _, _ = CA._layer(c.con)
    bad, n, with_w = [], 0, 0
    for rows in by_dip.values():
        for f in rows:
            n += 1
            want = W.get(f["cod_aff_form"])
            if f.get("jury") != want:
                bad.append((f["cod_aff_form"], f.get("jury"), want))
            with_w += want is not None
    if CA.DETAIL_KEYS and "jury" in CA.DETAIL_KEYS:
        bad.append("the weights are a detail key: the filter would wait for the cards")
    if c.real and with_w < 0.5 * n:
        bad.append(("too few formations carry their grid", with_w, n))
    return not bad, f"{n} rows, {with_w} with weights; problems {bad[:3]}"


# ------------------------------------------------------------------ JU3
FILTER_NAMES = ("JURY_KEYS", "JURY_LEVELS", "juryMeta", "juryLevel", "juryGroups", "juryCuts", "CARTE_FGROUPS", "carteHas",
                "carteFilter", "carteFacets", "carteCommon", "carteNoGrid", "carteInLieu")
FILTER_STUB = """
const CARTE_R3 = [], fiOptions = () => [], filtreBand = () => null, carteZone = () => "autre", carteText = () => "", haversineKm = () => 0;
const robReady = () => false, robLevel = () => ["sans"];
"""
FILTER_PROG = """
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
var META = { jury: D.meta };
const lv = [];
for (const c of D.meta.champs) for (let v = 0; v <= 100; v++) lv.push(juryLevel(v, c.cuts));
const groups = juryGroups();
const F1 = { jury_res: ["peu"], jury_mot: ["beaucoup", "moyen"] };
const kept = carteFilter(D.rows, F1).map((f) => f.cod_aff_form);
const opts = Object.fromEntries(groups.map(([g, , o]) => [g, o.map(([k]) => k)]));
const fac = carteFacets(D.rows, F1, null, opts);
process.stdout.write(JSON.stringify({ lv, keys: JURY_KEYS, groups, kept, nogrid: carteNoGrid(D.rows, F1), nogrid0: carteNoGrid(D.rows, {}),
  facets: Object.fromEntries(Object.entries(fac).map(([g, m]) => [g, Object.fromEntries(m)])),
  stale: carteFilter(D.rows, { robf: ["haut"] }).length, empty: (() => { META = null; return carteFilter(D.rows, F1).length; })() }));"""


def crafted_rows():
    rows = []
    for i in range(60):
        w = None if i % 7 == 3 else [(i * 13) % 70, (i * 3) % 15, (i * 11) % 40, (i * 7) % 35, 0]
        if w:
            w[4] = max(0, 100 - sum(w[:4]))
        rows.append({"cod_aff_form": str(1000 + i), "statut": "public", "jury": w})
    return rows


@check("JU3 page twins: juryLevel = jury.level, JURY_KEYS = CHAMPS, the filter (OR in a field, AND between, no grid out), counts")
def ju3(c: Ctx):
    J = c.jury()
    if not all(top(c.js, n) for n in FILTER_NAMES):
        return False, f"missing in app.js {[n for n in FILTER_NAMES if not top(c.js, n)]}"
    meta = {"champs": [{"key": k, "champ": n, "titre": n, "cuts": cu, "labels": J.labels(tuple(cu)), "n": {}}
                       for (k, n, _), cu in zip(J.CHAMPS, ([30, 45], [5, 10], [15, 25], [15, 25], [15, 25]))]}
    meta["champs"][2]["titre"] = HOSTILE
    rows = crafted_rows()
    prog = RB.STUB + FILTER_STUB + "\n".join(top(c.js, n) for n in FILTER_NAMES) + FILTER_PROG
    o = RB.node(prog, {"meta": meta, "rows": rows})
    if o is None:
        return True, "node absent: not run"
    bad = []
    want_lv = [J.level(v, x["cuts"]) for x in meta["champs"] for v in range(101)]
    own_lv = [own_level(v, x["cuts"]) for x in meta["champs"] for v in range(101)]
    if o["lv"] != want_lv or want_lv != own_lv:
        bad.append("juryLevel differs from jury.level (or from the red team's own reading)")
    if o["keys"] != [k for k, _, _ in J.CHAMPS]:
        bad.append(("JURY_KEYS", o["keys"]))
    if [g[0] for g in o["groups"]] != [f"jury_{k}" for k, _, _ in J.CHAMPS] or any(len(g[2]) != 3 for g in o["groups"]):
        bad.append("the five fields with their three levels")
    if o["groups"][0][2][0][1] != "Peu : moins de 30 %" or o["groups"][0][2][2][1] != "Beaucoup : 45 % ou plus":
        bad.append(("the levels' words and ranges", o["groups"][0][2]))
    cuts = {x["key"]: x["cuts"] for x in meta["champs"]}
    keep = lambda r, F: r["jury"] is not None and all(  # noqa: E731
        any(own_level(r["jury"][["res", "eng", "mot", "se", "met"].index(g[5:])], cuts[g[5:]]) == o_ for o_ in F[g]) for g in F)
    F1 = {"jury_res": ["peu"], "jury_mot": ["beaucoup", "moyen"]}
    want = [r["cod_aff_form"] for r in rows if keep(r, F1)]
    if sorted(o["kept"]) != sorted(want) or not want:
        bad.append(("kept", len(o["kept"]), len(want)))
    for g in ("jury_res", "jury_mot", "jury_eng"):
        others = {k: v for k, v in F1.items() if k != g}
        for lv in ("peu", "moyen", "beaucoup"):
            n = sum(1 for r in rows if keep(r, {**others, g: [lv]}))
            if o["facets"][g][lv] != n:
                bad.append((g, lv, o["facets"][g][lv], n))
    if o["nogrid"] != sum(1 for r in rows if r["jury"] is None) or o["nogrid0"] != 0:
        bad.append(("the « sans grille » count", o["nogrid"], o["nogrid0"]))
    if o["stale"] != len(rows):
        bad.append("a stored filière robustesse filter still filters")
    if o["empty"] != 0:
        bad.append("META not loaded must keep no jury-filtered formation (no cut points, no level)")
    return not bad, f"{len(rows)} crafted rows, {len(want)} kept; problems {bad[:4]}"


# ------------------------------------------------------------------ JU4
def view_of(js: str) -> str:
    return js[js.index("async function viewCarte("): js.index("\n// ---- lot 2 (Claude design guidelines)")]


@check("JU4 what a student reads: one dropdown, five fields, bars 1-3 with their words; caveats; escaped; never sorted; the card line")
def ju4(c: Ctx):
    bad = []
    view = view_of(c.js)
    need = {
        "one dropdown": 'dd("jury", "Ce que regarde le jury", jn,' in view,
        "the five fields kept out of the generic dropdowns": '&& !gr.startsWith("jury_")' in view,
        "a fieldset per field, legend escaped": '<fieldset class="dd-group jury-row"><legend>${esc(title.replace(/^Jury : /, ""))}</legend>' in view,
        "bars 1 to 3, hidden from screen readers (the words carry the meaning)": 'class="jbars" aria-hidden="true"' in view
                                                                                  and "[1, 2, 3].map((i)" in view,
        "the level's words escaped beside its bars": "${bars(w)}<span>${esc(label)}</span>" in view,
        "the « sans grille » count in the dropdown": "sans grille publiée sur leur fiche" in view and "carteNoGrid(base, F, kw)" in view,
        "the « sans grille » count in the list": "noGridN ? `<p class=\"small muted cs-nogrid\">" in view,
        "a reset for the five fields": "data-clear-jury" in view,
        "placed in the bar": "${groups.slice(1).join(\"\")}${jury}" in view,
    }
    bad += [k for k, v in need.items() if not v]
    h = top(c.js, "JURY_HELP")
    if "la fiche fait foi" not in h or "ni une note, ni une chance" not in h:
        bad.append("the help sentence's caveats")
    start = view.index("const listed = kept.filter(")
    s0 = view.index(".sort((a, b) =>", start)
    sort = view[s0: view.index("byName(a, b))", s0)]            # the list's comparator, whole
    if "jury" in sort.lower():
        bad.append("the list is sorted by a jury weight")
    # the card's line, through node: escaped names, the weights, the fiche credited; none without a grid
    names = ("JURY_KEYS", "juryMeta", "carteJury")
    prog = RB.STUB + "const fmt = (x) => String(x);\n" + "\n".join(top(c.js, n) for n in names) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      var META = { jury: D.meta };
      process.stdout.write(JSON.stringify([carteJury({ jury: [30, 10, 20, 25, 15] }), carteJury({ jury: null }), carteJury({})]));"""
    meta = {"champs": [{"key": k, "titre": t} for k, t in (("res", "Résultats scolaires"), ("eng", HOSTILE), ("mot", "Motivation"),
                                                         ("se", "Savoir-être"), ("met", "Méthodes de travail"))]}
    o = RB.node(prog, {"meta": meta})
    if o is not None:
        line, none1, none2 = o
        if "<img" in line or "&lt;img" not in line or "Résultats scolaires 30 %" not in line or "Méthodes de travail 15 %" not in line \
                or "la fiche fait foi" not in line:
            bad.append(("the card line", line[:120]))
        if none1 or none2:
            bad.append("a card line without a grid")
    if "${jury}${app}" not in top(c.js, "carteMore"):
        bad.append("the card line is not in the folded block")
    css = c.css
    if ".jbars i.on { background: var(--ink); }" not in css or re.search(r"\.jbars[^{]*\{[^}]*#[0-9a-fA-F]{3,6}", css):
        bad.append("the bars' style (tokens only)")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ JU5
@check("JU5 API: /api/meta carries the fields (no parameter, once per warehouse); the filière robustesse filter gone, its repère kept")
def ju5(c: Ctx):
    bad = []
    api = (ROOT / "suptracker" / "api.py").read_text()
    if '"jury": _jury_meta(),' not in api or "return CA.once(_JURY, CA._fingerprint(con), lambda: JU.meta(con))" not in api:
        bad.append("META.jury is not computed once per warehouse")
    os.environ.setdefault("SUPTRACKER_ANALYTICS_DIR", tempfile.mkdtemp())
    os.environ["SUPTRACKER_DB"] = str(c.db)
    from fastapi.testclient import TestClient
    from suptracker import api as A
    with TestClient(A.app) as tc:
        m = tc.get("/api/meta").json().get("jury") or {}
    want = c.jury().meta(c.con)
    if m != json.loads(json.dumps(want)):
        bad.append("META.jury differs from jury.meta")
    if c.real and len(m.get("champs", [])) != 5:
        bad.append(("five fields on real data", len(m.get("champs", []))))
    if '"robf"' in top(c.js, "CARTE_ROB") or '"robf"' in top(c.js, "CARTE_FGROUPS") or "robf:" in top(c.js, "FI_HELP"):
        bad.append("the filière robustesse filter is still on the page")
    if "filiere" not in top(c.js, "robDecode"):
        bad.append("the filière repère is no longer read from the payload (owner: keep it)")
    rf = (ROOT / "suptracker" / "robustesse_formation.py").read_text()
    if "filiere" not in rf:
        bad.append("the filière repère is no longer built")
    return not bad, f"META.jury fields {[x['key'] for x in m.get('champs', [])]}; problems {bad}"


# ------------------------------------------------------------------ JU6
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[process.argv.length - 1], errs = [];
  const b = await chromium.launch();
  const out = {};
  for (const [name, vp] of [['wide', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    const ctx = await b.newContext({ viewport: vp });
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    await p.goto(base + '/#/carte'); await p.waitForSelector('#cs-q', { timeout: 60000 });
    await p.waitForFunction(() => document.querySelector('details[data-dd="jury"]'), null, { timeout: 90000 }).catch(() => {});
    const fold = await p.$('#dd-fold'); if (fold && name === 'phone') { await p.evaluate(() => { const d = document.getElementById('dd-fold'); if (d) d.open = true; }); }
    const before = await p.evaluate(() => (document.getElementById('sr-status') || {}).textContent || '');
    await p.evaluate(() => { const d = document.querySelector('details[data-dd="jury"]'); if (d) d.open = true; });
    const info = await p.evaluate(() => { const d = document.querySelector('details[data-dd="jury"]');
      return d ? { legends: [...d.querySelectorAll('legend')].map((l) => l.textContent), boxes: d.querySelectorAll('input[type=checkbox]').length,
        bars: [...d.querySelectorAll('.jlev')].map((l) => l.querySelectorAll('.jbars i.on').length) } : null; });
    await p.click('details[data-dd="jury"] input[data-g="jury_res"][data-o="peu"]').catch(() => {});
    await p.waitForTimeout(800);
    await p.evaluate(() => { const d = document.querySelector('details[data-dd="jury"]'); if (d) d.open = true; });
    await p.click('details[data-dd="jury"] input[data-g="jury_mot"][data-o="beaucoup"]').catch(() => {});
    await p.waitForTimeout(1500);
    const after = await p.evaluate(() => ({ status: (document.getElementById('sr-status') || {}).textContent || '',
      nogrid: (document.querySelector('.cs-nogrid') || {}).textContent || '',
      jline: (document.querySelector('.cjury') || {}).textContent || '',
      scroll: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
    out[name] = { info, before, ...after };
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ ...out, errs })); await b.close();
})();
"""


@check("JU6 browser: the dropdown (five fields, bars 1-3), two levels narrow the list, the « sans grille » line, phone width, 0 JS error")
def ju6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, cwd=str(ROOT)).returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        r = nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    for name in ("wide", "phone"):
        x = o[name]
        if not x["info"] or len(x["info"]["legends"]) != 5 or x["info"]["boxes"] != 15 or x["info"]["bars"] != [1, 2, 3] * 5:
            bad.append((name, "dropdown", x["info"]))
        if x["status"] == x["before"]:
            bad.append((name, "ticking two levels did not change the list", x["status"][:80]))
        if "sans grille" not in x["nogrid"]:
            bad.append((name, "the « sans grille » line"))
        if x["scroll"]:
            bad.append((name, "horizontal scroll"))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad, f"wide {o['wide']['status'][:60]!r}; problems {bad}"


# ------------------------------------------------------------------ JU7
MUTANTS = [
    ("py", "JU1", "cut points on any value", "    grid = list(range(STEP, 100, STEP))", "    grid = list(range(1, 100))"),
    ("py", "JU1", "no minimum band", "            if min(parts) < MIN_BAND * n:\n                continue\n", ""),
    ("py", "JU1", "upper limit included", '    return "peu" if v < c[0] else "moyen" if v < c[1] else "beaucoup"',
     '    return "peu" if v <= c[0] else "moyen" if v <= c[1] else "beaucoup"'),
    ("py", "JU1", "an unlisted field counted as missing", "            out.setdefault(cod, [0] * len(CHAMPS))[idx[champ]] = int(poids)",
     "            out.setdefault(cod, [None] * len(CHAMPS))[idx[champ]] = int(poids)"),
    ("py", "JU1", "unverified grids read", "            JOIN core.fiche_grille g ON g.cod_aff_form = c.cod_aff_form AND g.grille",
     "            JOIN core.fiche_grille g ON g.cod_aff_form = c.cod_aff_form"),
    ("js", "JU3", "the page's twin includes the upper limit", 'v < c[0] ? "peu" : v < c[1] ? "moyen" : "beaucoup"', 'v <= c[0] ? "peu" : v <= c[1] ? "moyen" : "beaucoup"'),
    ("js", "JU3", "fields out of order", 'const JURY_KEYS = ["res", "eng", "mot", "se", "met"];', 'const JURY_KEYS = ["res", "mot", "eng", "se", "met"];'),
    ("js", "JU3", "no grid kept", "return Array.isArray(f.jury) && juryLevel(", "return !Array.isArray(f.jury) || juryLevel("),
    ("js", "JU3", "the jury groups not filtered", '"robn", ...JURY_KEYS.map((k) => `jury_${k}`)];', '"robn"];'),
    ("js", "JU3", "the « sans grille » count wrong", "  return carteFilter(rows, G, undefined, kw).filter((f) => !Array.isArray(f.jury)).length;",
     "  return carteFilter(rows, F, undefined, kw).filter((f) => !Array.isArray(f.jury)).length;"),
    ("js", "JU4", "the card line unescaped", "`${esc(names[k] || k)} ${fmt(f.jury[i])} %`", "`${names[k] || k} ${fmt(f.jury[i])} %`"),
    ("js", "JU4", "the caveat dropped", "Les niveaux comparent ce poids à celui des autres formations : ni une note, ni une chance.",
     "Les niveaux comparent ce poids à celui des autres formations."),
    ("js", "JU4", "sorted by the weight", "      .sort((a, b) => (a.stats === false) - (b.stats === false) ||",
     "      .sort((a, b) => (a.stats === false) - (b.stats === false) || ((b.jury || [0])[0] - (a.jury || [0])[0]) ||"),
    ("js", "JU5", "the filière filter back", '  ["robn",', '  ["robf", "Robustesse 2035 dans sa filière", [["haut", "x"]]],\n  ["robn",'),
]


@check("JU7 mutation test: every seeded bug is caught by JU1-JU5")
def ju7(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("JU1", "JU3", "JU4", "JU5") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    import importlib.util
    missed = []
    for kind, target, name, old, new in MUTANTS:
        m = copy.copy(c)
        if kind == "js":
            if c.js.count(old) != 1:
                missed.append(f"{name} (anchor {c.js.count(old)})")
                continue
            m.js = c.js.replace(old, new, 1)
        else:
            if c.jury_src.count(old) != 1:
                missed.append(f"{name} (anchor {c.jury_src.count(old)})")
                continue
            spec = importlib.util.spec_from_loader("jury_mutant", loader=None)
            mod = importlib.util.module_from_spec(spec)
            exec(compile(c.jury_src.replace(old, new, 1), "jury_mutant", "exec"), mod.__dict__)
            m.J = mod
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} caught; missed {missed}"


# ------------------------------------------------------------------ JU8
@check("JU8 wiring and docs: test file and CI duration, README section, CLAUDE.md rule, nightly browser suite, sources")
def ju8(c: Ctx):
    bad = []
    if not (ROOT / "tests" / "test_jury.py").exists():
        bad.append("tests/test_jury.py")
    if '"tests/test_jury.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("CI duration")
    if "## Ce que regarde le jury (owner, 2026-11-27)" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**Ce que regarde le jury (owner, 2026-11-27).**" not in (ROOT.parent / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    if '"jury": ("JU6",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
    return not bad, f"problems {bad}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
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
