"""Red team of sprint Q3 (owner, 2026-11-13): speed of the map, without changing one figure.

    python scripts/redteam_vitesse.py [--db data/suptracker.duckdb] [--real] [--browser]

  VT1 the compact layer = the per-diploma answers: /api/carte/couche (base, then details) decoded by the server's decoder
      AND by the page's twin (coucheDec / coucheDecode / coucheDetails, run in Node) gives, for EVERY type of diploma, exactly
      the formations, keys and values /api/carte/formations serves (plus the diploma), in the same order; base and details
      split the keys as announced (the list, the map and the filters never need a detail key)
  VT2 the zones read in one query = the zones read type by type: for several profiles (bac général with and without an
      average, bac techno, bac pro), every diploma's zones and reading ingredients equal those of the former algorithm
      (stage 2 per own type, re-implemented here), and diplome=* equals the union of all diplomas
  VT3 serving: the layer is built once per warehouse (same bytes, gzip without a timestamp, one ETag per content), a
      matching If-None-Match is a 304, Vary: Accept-Encoding, the public cache policy (a 304 keeps it), a client without
      gzip gets the same JSON, and the bytes stay under the budget (base and details, compressed)
  VT4 the page: one layer request, one details request and (nothing ticked) ONE zones request for every diploma; a ticked
      selection asks its diplomas' zones; the page never asks /api/carte/formations; the cards say "chargement…" for the
      rates until the details come, and a failed details answer leaves the rates out (never "chargement…" forever)
  VT5 the memoised calling-group reading equals the unmemoised one for every published label x series x doublette, and the
      memoised fold equals the plain fold
  VT6 browser (--browser / --real), a mid-range phone (Pixel 5, CPU x4 slower, slow 4G): the map's list and its zones within
      the budget, at most 5 map requests, no JS error; the home and a formation page show their heading within budget
  VT7 docs: README section and CLAUDE.md rule
  VT8 mutation test of VT1-VT5 and VT7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []

import duckdb  # noqa: E402

from suptracker import admis as ADM  # noqa: E402
from suptracker import cache as CACHE  # noqa: E402
from suptracker import carte as CA  # noqa: E402
from suptracker import journey as J  # noqa: E402

DETAIL = ("bacs", "majo", "offres_app", "fiche")          # written here: the keys only the cards read
BUDGET_KB = {"base": 700, "details": 500}                 # compressed bytes of the two layer answers (real warehouse)
PHONE_BUDGET_MS = {"list": 9000, "zones": 15000, "home": 4000, "formation": 5000}
PROFILES = [("MATHS+SES", "ab", "bg", None), ("PC+SVT", "tb", "bg", 16.4), (None, "b", "bt", None), (None, "sansmention", "bp", None)]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.reload()

    def reload(self):
        self.js = (STATIC / "app.js").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""

    def con(self):
        return duckdb.connect(str(self.db), read_only=True)


@contextlib.contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    from suptracker import api
    api._con.cache_clear()
    CA._COUCHE.clear()
    try:
        yield TestClient(api.app), api
    finally:
        api._con.cache_clear()
        CA._COUCHE.clear()
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old


def fn_src(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", js, re.M)
    return js[m.start(): js.find("\n}", m.start()) + 2] if m else ""


def expected(cl) -> list[dict]:
    """Every formation as /api/carte/formations serves it, diploma by diploma (in the map's order), with its diploma."""
    out = []
    for d in [x["label"] for x in cl.get("/api/carte").json()["diplomes"]]:
        r = cl.get("/api/carte/formations", params={"diplome": d})
        if r.status_code == 200:
            out += [{**f, "diplome": d} for f in r.json()["formations"]]
    return out


def node_decode(c: Ctx, base: dict, details: dict) -> list | None:
    """The page's twin, run in Node on the two answers: whole formations."""
    node = shutil.which("node")
    if not node:
        return None
    src = "\n".join(fn_src(c.js, n) for n in ("coucheDec", "coucheDecode", "coucheDetails"))
    with tempfile.TemporaryDirectory() as d:
        Path(d, "b.json").write_text(json.dumps(base))
        Path(d, "d.json").write_text(json.dumps(details))
        Path(d, "t.js").write_text(src + """
const fs = require('fs');
const C = coucheDecode(JSON.parse(fs.readFileSync(process.argv[2])));
coucheDetails(C, coucheDecode(JSON.parse(fs.readFileSync(process.argv[3]))));
fs.writeFileSync(process.argv[4], JSON.stringify(C.rows));""")
        r = subprocess.run([node, str(Path(d, "t.js")), str(Path(d, "b.json")), str(Path(d, "d.json")), str(Path(d, "o.json"))],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise RuntimeError(r.stderr[-300:])
        return json.loads(Path(d, "o.json").read_text())


# ------------------------------------------------------------------ VT1
@check("VT1 the compact layer (base + details), decoded by the server and by the page's twin, = every per-diploma answer, in order")
def vt1(c: Ctx):
    bad = []
    with client(c.db) as (cl, _):
        want = expected(cl)
        base, det = cl.get("/api/carte/couche").json(), cl.get("/api/carte/couche?partie=details").json()
    py = [CA.dec(r, base["kinds"], base["strings"], top=True) for r in base["rows"]]
    pyd = {x["cod_aff_form"]: x for x in (CA.dec(r, det["kinds"], det["strings"], top=True) for r in det["rows"])}
    whole = []
    for f in py:
        if any(k in f for k in DETAIL):
            bad.append(("detail key in base", f.get("cod_aff_form")))
        x = pyd.get(f["cod_aff_form"], {})
        if set(x) - {"cod_aff_form", *DETAIL}:
            bad.append(("non-detail key in details", f.get("cod_aff_form")))
        whole.append({**f, **x})
    if len(whole) != len(want) or [f["cod_aff_form"] for f in whole] != [f["cod_aff_form"] for f in want]:
        bad.append(("order or count", len(whole), len(want)))
    diff = [w["cod_aff_form"] for w, g in zip(want, whole) if w != g]
    if diff:
        bad.append(("server decoder differs", diff[:3]))
    js = node_decode(c, base, det)
    if js is not None:
        jd = [w["cod_aff_form"] for w, g in zip(want, js) if w != g]
        if len(js) != len(want) or jd:
            bad.append(("page twin differs", len(js), jd[:3]))
    if base.get("session") is None or base.get("partie") != "base" or det.get("partie") != "details":
        bad.append("header fields")
    return not bad, f"{len(want)} formations; page twin {'run' if js is not None else 'skipped (no node)'}; problems {bad[:4]}"


# ------------------------------------------------------------------ VT2
def zones_reference(con, diplome, dkey, mb, serie, moyenne):
    """The former algorithm: stage 2 on each formation's own type, one query per type."""
    lay = CA.formations(con, diplome, None)
    by = {}
    for f in lay["formations"]:
        if f.get("stats", True) is not False:
            by.setdefault(f["type_key"] or J.SANS_TYPE, []).append(f["cod_aff_form"])
    out, lec = {}, {}
    for tk, cods in by.items():
        for f in J.stage2(con, dkey, mb, tk, None, serie=serie, only=cods, moyenne=moyenne)["formations"]:
            out[f["cod_aff_form"]] = f["zone"]
            lec[f["cod_aff_form"]] = {"zone": f["zone"], "uncertain": f["uncertain"], "taux_acces_ens": f["taux_acces_ens"], "lec": f["lec"]}
    return {"zones": out, "lectures": lec}


@check("VT2 the zones read in one query = the zones read type by type (4 profiles, every diploma), and diplome=* = their union")
def vt2(c: Ctx):
    bad, n = [], 0
    con = c.con()
    try:
        dips = [d["label"] for d in CA.facets(con)["diplomes"]]
        profiles = PROFILES if c.real else PROFILES
        for dkey, mb, serie, moy in profiles:
            union = {}
            for d in dips:
                got = CA.zones(con, d, None, dkey, mb, serie, moy, lecture=True)
                ref = zones_reference(con, d, dkey, mb, serie, moy)
                n += len(ref["zones"])
                if json.dumps(got, sort_keys=True) != json.dumps(ref, sort_keys=True):
                    bad.append((serie, mb, d))
                union.update(got["lectures"])
            alls = CA.zones(con, CA.TOUS, None, dkey, mb, serie, moy, lecture=True)
            if json.dumps(alls["lectures"], sort_keys=True) != json.dumps(union, sort_keys=True):
                bad.append((serie, mb, "*"))
    finally:
        con.close()
    return not bad, f"{n} zones compared; problems {bad[:4]}"


# ------------------------------------------------------------------ VT3
@check("VT3 serving: built once, gzip without timestamp, one ETag per content, 304, Vary, public cache, plain JSON too, under budget")
def vt3(c: Ctx):
    bad, sizes = [], {}
    with client(c.db) as (cl, api):
        for partie in ("base", "details"):
            url = "/api/carte/couche" + ("" if partie == "base" else "?partie=details")
            a = cl.get(url, headers={"accept-encoding": "gzip"})
            b = cl.get(url, headers={"accept-encoding": "gzip"})
            raw = cl.get(url, headers={"accept-encoding": "identity"})
            built = CA.couche(api._con().cursor(), ADM.mark, partie)
            sizes[partie] = len(built["gzip"]) // 1024
            if a.headers.get("etag") != b.headers.get("etag") or a.headers.get("etag") != built["etag"]:
                bad.append((partie, "etag"))
            if built["gzip"][4:8] != b"\x00\x00\x00\x00" or gzip.decompress(built["gzip"]) != built["json"]:
                bad.append((partie, "gzip timestamp or content"))
            if raw.headers.get("content-encoding") or json.loads(raw.content) != a.json():
                bad.append((partie, "plain JSON"))
            if "accept-encoding" not in (a.headers.get("vary") or "").lower():
                bad.append((partie, "vary"))
            if a.headers.get("cache-control") != CACHE.PUBLIC:
                bad.append((partie, "cache", a.headers.get("cache-control")))
            nm = cl.get(url, headers={"if-none-match": a.headers.get("etag")})
            if nm.status_code != 304 or nm.content or nm.headers.get("cache-control") != CACHE.PUBLIC:
                bad.append((partie, "304", nm.status_code, nm.headers.get("cache-control")))
            if c.real and sizes[partie] > BUDGET_KB[partie]:
                bad.append((partie, "over budget", sizes[partie]))
        if cl.get("/api/carte/couche?partie=autre").status_code != 422:
            bad.append("unknown part accepted")
        if CA.couche(api._con().cursor(), ADM.mark) is not CA.couche(api._con().cursor(), ADM.mark):
            bad.append("built again for the same warehouse")
    if CACHE.header("GET", "/api/carte/couche", None, 304, "v") != CACHE.PUBLIC:
        bad.append("a 304 loses the policy")
    return not bad, f"compressed KB {sizes}; problems {bad}"


# ------------------------------------------------------------------ VT4
@check("VT4 the page: one layer + one details request, ONE zones request when nothing is ticked, never /api/carte/formations; rates wait, never forever")
def vt4(c: Ctx):
    view = c.js[c.js.index("async function viewCarte("): c.js.index("\n// ---- lot 2 (Claude design guidelines)")]
    need = {
        "one layer answer": view.count('api("/api/carte/couche")') == 1 and 'cached("couche", ' in view,
        "asked before the types": view.index('loadCouche().catch(() => {});') < view.index('const FAC = await api("/api/carte");'),
        "one details answer": view.count('api("/api/carte/couche?partie=details")') == 1,
        "no per-diploma layer": not re.search(r"""api\(\s*[`'"]/api/carte/formations""", c.js),
        "zones: all at once when nothing is ticked": "Promise.all(tous ? [loadZ(CARTE_TOUS)] : dips.map(loadZ))" in view,
        "CARTE_TOUS = carte.TOUS": f'const CARTE_TOUS = "{CA.TOUS}";' in c.js,
        "detail keys = carte.DETAIL_KEYS": f'const CARTE_DETAIL_KEYS = {json.dumps(list(CA.DETAIL_KEYS))};'.replace('","', '", "') in c.js
                                           and tuple(CA.DETAIL_KEYS) == DETAIL,
        "details merged into the drawn rows": "CARTE_DETAIL_KEYS.forEach((k) => { if (k in g) f[k] = g[k]; });" in view,
        "a failed details answer clears the wait": 'rows.forEach((f) => { if (f.bacs === undefined) f.bacs = null; });' in view,
        "rates wait while details come": "if (f.bacs === undefined && f.stats !== false) return" in fn_src(c.js, "carteBacs")
                                         and "chargement…" in fn_src(c.js, "carteBacs"),
    }
    # the list, the map and the filters read no detail key (they are drawn before the details come)
    for fn in ("carteFilter", "carteHas", "carteSortName", "carteMarker"):
        src = fn_src(c.js, fn)
        if any(re.search(rf"\.{k}\b", src) for k in DETAIL):
            need[f"{fn} reads a detail key"] = False
    bad = [k for k, v in need.items() if not v]
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ VT5
@check("VT5 the memoised calling-group reading = the plain one for every label x series x doublette; the memoised fold = the plain fold")
def vt5(c: Ctx):
    con = c.con()
    try:
        labels = [r[0] for r in con.execute("""SELECT DISTINCT x FROM (SELECT lib_grp1 x FROM core.formation_year UNION
            SELECT lib_grp2 FROM core.formation_year UNION SELECT lib_grp3 FROM core.formation_year) WHERE x IS NOT NULL""").fetchall()]
    finally:
        con.close()
    labels += ["Bacheliers généraux spécialité Maths + une spécialité non scientifique", "spécialité Maths ou NSI", "Toutes les filles"]
    plain = J._group_applies.__wrapped__
    spes = [None, ("MATHS", "SES"), ("PC", "SVT"), ("HLP", "SES"), ("MATHS", "NSI")]
    bad, n = [], 0
    for lab in labels:
        for serie in J.SERIES:
            for spe in spes:
                for sex in (None, "F"):
                    n += 1
                    if J.group_applies(lab, list(spe) if spe else None, sex, serie) != plain(lab, spe, sex, serie):
                        bad.append((lab[:40], serie, spe, sex))
    fold_bad = [lab for lab in labels if J._fold(lab) != J._fold.__wrapped__(lab)]
    return not bad and not fold_bad, f"{len(labels)} labels, {n} readings; differing {bad[:3]}; fold {fold_bad[:2]}"


# ------------------------------------------------------------------ VT6
@check("VT6 browser: a mid-range phone on slow 4G gets the map's list and zones within budget, few map requests, no JS error")
def vt6(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    import socket
    import time
    node = shutil.which("node")
    if not node:
        return True, "node not installed"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_DB": str(c.db), "SUPTRACKER_ANALYTICS_DIR": tmp}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        import urllib.request
        for u in ("/api/carte/couche", "/api/carte/couche?partie=details"):      # the layer is built at the first request
            urllib.request.urlopen(f"http://127.0.0.1:{port}{u}", timeout=120).read()
        with duckdb.connect(str(c.db), read_only=True) as con:
            cod = con.execute("SELECT cod_aff_form FROM core.formation_year ORDER BY session DESC, cod_aff_form LIMIT 1").fetchone()[0]
        script = Path(tmp, "vt6.js")
        script.write_text(PHONE_JS.replace("__PORT__", str(port)).replace("__COD__", str(cod)))
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=600)
        out = (r.stdout or "").strip().splitlines()
        res = json.loads(out[-1]) if out and out[-1].startswith("{") else {"errors": [r.stderr[-300:]]}
    finally:
        srv.terminate()
    over = [k for k, v in PHONE_BUDGET_MS.items() if res.get(k) is None or res[k] > v]
    ok = not over and not res.get("errors") and res.get("map_requests", 99) <= 5
    return ok, f"phone ms {({k: res.get(k) for k in PHONE_BUDGET_MS})} (budget {PHONE_BUDGET_MS}); map requests {res.get('map_requests')}; errors {res.get('errors')}"


PHONE_JS = r"""
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch(); const errors = []; const out = {};
  const page = async (profile) => {
    const ctx = await b.newContext({ ...devices['Pixel 5'] });
    if (profile) await ctx.addInitScript(() => localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", statut: "terminale" })));
    const p = await ctx.newPage(); const cdp = await ctx.newCDPSession(p);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6e6 / 8, uploadThroughput: 750e3 / 8 });
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    p.on('pageerror', (e) => errors.push(e.message));
    return { ctx, p };
  };
  let { ctx, p } = await page(true);
  let mapReq = 0; p.on('request', (r) => { if (/\/api\/carte/.test(r.url())) mapReq++; });
  let t0 = Date.now();
  await p.goto('http://127.0.0.1:__PORT__/#/carte');
  await p.waitForFunction(() => document.querySelector('#carte-items [data-pick]'), null, { timeout: 60000 }).catch(() => {});
  out.list = Date.now() - t0;
  await p.waitForFunction(() => { const l = document.getElementById('carte-legend'); return l && !/chargement/.test(l.textContent) && /\d/.test(l.textContent); }, null, { timeout: 60000 }).catch(() => {});
  out.zones = Date.now() - t0;
  await p.waitForTimeout(3000);
  out.map_requests = mapReq;
  await ctx.close();
  for (const [k, u] of [['home', '/'], ['formation', '/formation/__COD__']]) {
    ({ ctx, p } = await page(false));
    t0 = Date.now();
    await p.goto('http://127.0.0.1:__PORT__' + u);
    await p.waitForSelector('#view h1', { timeout: 60000 }).catch(() => {});
    out[k] = Date.now() - t0;
    await ctx.close();
  }
  out.errors = errors;
  console.log(JSON.stringify(out)); await b.close();
})();
"""


# ------------------------------------------------------------------ VT7
@check("VT7 docs: README section and CLAUDE.md rule")
def vt7(c: Ctx):
    ok = "## Sprint Q3" in c.readme and "/api/carte/couche" in c.readme and "Speed (sprint Q3" in c.claude
    return ok, f"README {'## Sprint Q3' in c.readme}, CLAUDE.md {'Speed (sprint Q3' in c.claude}"


# ------------------------------------------------------------------ VT8 mutation test
def mutants():
    out = []

    def py(name, target, attr, value, checks):
        state = {}

        def apply(_c):
            state["v"] = getattr(target, attr)
            setattr(target, attr, value(state["v"]) if callable(value) and not isinstance(value, (str, tuple, dict)) else value)
            CA._COUCHE.clear()

        def restore(_c):
            setattr(target, attr, state["v"])
            CA._COUCHE.clear()
        out.append((name, apply, restore, checks))

    py("a card key sent in the base answer", CA, "DETAIL_KEYS", ("bacs", "majo", "offres_app"), {"VT1", "VT4"})
    py("a detail key dropped", CA, "_couche_build",
       lambda f: (lambda con, mark: (lambda r: (r["details"].update(_drop_majo(r["details"])), r)[1])(f(con, mark))), {"VT1"})
    py("strings shifted by one in the decoder", CA, "dec",
       lambda f: (lambda v, kinds, strings, top=False: f(v, kinds, strings[1:] + strings[:1], top)), {"VT1"})
    # only a defect where formations without a type exist (the real warehouse has them; a fixture may not)
    py("zones: the untyped formations forgotten", CA, "zones",
       lambda f: (lambda con, d, m, dk, mb, se, mo=None, lecture=False: _without_untyped(f(con, d, m, dk, mb, se, mo, lecture), con, d)), {"VT2"})
    py("an ETag per request", CA, "couche",
       lambda f: (lambda con, mark=None, partie="base": {**f(con, mark, partie), "etag": f'"{os.urandom(4).hex()}"'}), {"VT3"})
    py("a 304 loses the cache policy", CACHE, "header",
       lambda f: (lambda m, p, v, st, cur, fine=False: CACHE.NO_STORE if st == 304 else f(m, p, v, st, cur, fine)), {"VT3"})
    py("the memo ignores the series", J, "group_applies",
       lambda f: (lambda label, spe, sex=None, serie="bg": J._group_applies(label, tuple(spe) if spe else None, sex, "bg")), {"VT5"})

    def page_mut(name, old, new, checks):
        def apply(c):
            if old not in c.js:
                raise AssertionError(f"anchor not found: {old[:50]}")
            c.js = c.js.replace(old, new, 1)
        out.append((name, apply, lambda c: c.reload(), checks))

    page_mut("one zones request per diploma when nothing is ticked", "Promise.all(tous ? [loadZ(CARTE_TOUS)] : dips.map(loadZ))",
             "Promise.all(dips.map(loadZ))", {"VT4"})
    page_mut("details never merged into the drawn rows", "CARTE_DETAIL_KEYS.forEach((k) => { if (k in g) f[k] = g[k]; });", "", {"VT4"})
    page_mut("rates wait forever after a failure", "rows.forEach((f) => { if (f.bacs === undefined) f.bacs = null; });", "", {"VT4"})
    # (decoding the dictionary inside nested objects too is an equivalent mutant on this layer: no nested key of
    # DICT_KEYS ever holds an integer; the build's round-trip check guards that case)
    page_mut("the page twin forgets the strings table", "o[cols[i]] = top && K.dict.has(cols[i]) && Number.isInteger(x) ? S[x]",
             "o[cols[i]] = top && K.dict.has(cols[i]) && Number.isInteger(x) ? x", {"VT1"})
    page_mut("the page twin drops a null value", "return v;\n}\nfunction coucheDecode", "return v ?? undefined;\n}\nfunction coucheDecode", {"VT1"})
    page_mut("the page twin forgets the details", "D.rows.forEach((x) => { const f = by.get(x.cod_aff_form); if (f) Object.assign(f, x); });",
             "", {"VT1"})
    page_mut("the layer waits for the types", "  loadCouche().catch(() => {});\n", "\n", {"VT4"})

    def docs(c):
        c.claude = c.claude.replace("Speed (sprint Q3", "Speed (sprint")
    out.append(("rule dropped from CLAUDE.md", docs, lambda c: c.reload(), {"VT7"}))
    return out


def _drop_majo(details: dict) -> dict:
    import json as _j
    P = _j.loads(details["json"])
    P["kinds"] = [[k for k in kind if k != "majo"] for kind in P["kinds"]]
    raw = _j.dumps(P).encode()
    return {"json": raw, "gzip": gzip.compress(raw, 6, mtime=0), "etag": '"x"'}


def _without_untyped(res: dict, con, d):
    lay = CA.formations(con, d, None) if d != CA.TOUS else None
    untyped = {f["cod_aff_form"] for f in (lay or {"formations": []})["formations"] if not f.get("type_key")}
    if d == CA.TOUS:
        untyped = {f["cod_aff_form"] for x in CA.facets(con)["diplomes"] for f in (CA.formations(con, x["label"]) or {"formations": []})["formations"]
                   if not f.get("type_key")}
    return {k: {c: v for c, v in res[k].items() if c not in untyped} for k in res}


@check("VT8 mutation test: each seeded defect is caught by its check")
def vt8(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    missed, n = [], 0
    con = c.con()
    try:
        untyped = bool(J.untyped_codes(con))
    finally:
        con.close()
    for name, apply, restore, expect in mutants():
        if name.startswith("zones: the untyped") and not untyped:
            continue                                     # equivalent here: nothing untyped to forget
        n += 1
        try:
            apply(c)
            caught = set()
            for k in expect:
                try:
                    ok, _ = by[k](c)
                except Exception:  # noqa: BLE001 - a crash is a catch
                    ok = False
                if not ok:
                    caught.add(k)
        finally:
            restore(c)
        if not caught:
            missed.append(name)
    return not missed, f"{n - len(missed)}/{n} mutants caught; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        try:
            ok, detail = fn(c)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args()
    res = run(Path(a.db), a.real, a.browser)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"]))
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    sys.exit(0 if all(r["ok"] for r in res) else 1)


if __name__ == "__main__":
    main()
