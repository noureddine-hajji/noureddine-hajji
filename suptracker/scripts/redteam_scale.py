"""Red team of sprint 10 (scale): HTTP cache policy, lighter "Mon parcours" answers, audience count moved to
the page, one CI run per change, live monitoring.

    python scripts/redteam_scale.py [--db data/suptracker.duckdb] [--real]

  S1 every route of the app has an explicit cache policy (a new route without one fails)
  S2 a route that records an audience event, or answers with a personal list, is never shared-cached
     (found by CALLING every route with the audience recorder patched, not by reading the code)
  S3 headers as served: public data shared-cached only on 200, errors and POST no-store, versioned assets
     immutable only with the current fingerprint, no cached response sets a cookie
  S4 the public "Mon parcours" view drops only fields the page never reads, keeps zones, and every number
     shown (one decimal of a percent, points of access) is identical after rounding
  S5 Plan B and "Mes vœux" still use the full rows; the count of "Mon parcours" is sent by the page (closed list)
  S6 CI runs once per change (main on push, branches through their pull request), cancels stale runs, keeps the
     timing check serial; the monitor runs on a schedule and its checks fail on a broken site
  S7 mutation test: seeded bugs in the policy, the slim view, the audience count, the workflows and the monitor
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import cache as CACHE  # noqa: E402
from suptracker import journey as J  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CI = REPO / ".github" / "workflows" / "suptracker.yml"
MON = REPO / ".github" / "workflows" / "suptracker-monitor.yml"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool):
        self.db, self.real = db, real
        con = duckdb.connect(str(db), read_only=True)
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.cod, self.type_key = con.execute("""SELECT fy.cod_aff_form, r.spe_type_key FROM core.formation_year fy
            JOIN core.taxonomy_link t USING (session, cod_aff_form) JOIN core.taxonomy_rule r USING (rule_id)
            WHERE fy.session = ? ORDER BY fy.cod_aff_form LIMIT 1""", [latest]).fetchone()
        row = con.execute("SELECT min(met_id) FROM core.onisep_metier").fetchone() if con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'onisep_metier'").fetchone()[0] else None
        self.met_id = (row and row[0]) or "MET.1"
        self.has_jobs = bool(row and row[0])
        self.lineage = con.execute("SELECT lineage_id FROM core.lineage WHERE cod_aff_form = ? LIMIT 1", [self.cod]).fetchone()[0]
        big = con.execute("""SELECT r.spe_type_key, count(*) n FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
            WHERE t.session = ? GROUP BY 1 ORDER BY n DESC""", [latest]).fetchall()
        self.types = [b[0] for b in big[: (6 if real else len(big))]]
        self.fil = con.execute("SELECT fil_lib_voe_acc FROM core.formation_year WHERE cod_aff_form = ? LIMIT 1", [self.cod]).fetchone()[0]
        from suptracker import carte as CA                   # the map's smallest type of diploma (sprint "Carte")
        self.diplome = min(CA.facets(con)["diplomes"], key=lambda d: d["n"])["label"]
        con.close()

    def samples(self):
        """One valid GET per route (path template -> concrete URL)."""
        c, bg = self.cod, "spe1=MATHS&spe2=SES"
        return {
            "/healthz": "/healthz", "/readyz": "/readyz", "/api/meta": "/api/meta",
            "/api/search": "/api/search?q=licence", "/api/formation/{cod}": f"/api/formation/{c}",
            "/api/lineage/{lineage_id}": f"/api/lineage/{self.lineage}", "/api/compare": f"/api/compare?ids={c}",
            "/api/specialites": "/api/specialites", "/api/filiere": "/api/filiere?" + __import__("urllib.parse").parse.urlencode({"fil": self.fil}),
            "/api/verification": "/api/verification", "/api/journey/persona": "/api/journey/persona",
            "/api/journey/vocab": "/api/journey/vocab", "/api/journey/stage1": f"/api/journey/stage1?{bg}",
            "/api/journey/stage2": f"/api/journey/stage2?{bg}&mention=ab&type={self.type_key}",
            "/api/lycees": "/api/lycees", "/api/planb/{cod}": f"/api/planb/{c}?{bg}",
            "/api/voeux": f"/api/voeux?{bg}&ids={c}", "/api/voeux/completer": f"/api/voeux/completer?{bg}&ids={c}",
            "/api/continuity": "/api/continuity",
            "/api/metiers": "/api/metiers", "/api/metier/{met_id}": f"/api/metier/{self.met_id}",
            "/api/carte": "/api/carte", "/api/carte/couche": "/api/carte/couche", "/api/carte/formations": "/api/carte/formations?diplome=" + __import__("urllib.parse").parse.quote(self.diplome),
            "/api/carte/zones": f"/api/carte/zones?{bg}&mention_bac=ab&diplome=" + __import__("urllib.parse").parse.quote(self.diplome),
            "/api/carte/chiffres": f"/api/carte/chiffres?{bg}&codes={c}",
            "/api/comprendre": "/api/comprendre",
            "/api/selectivite": "/api/selectivite?diplome=" + __import__("urllib.parse").parse.quote(self.diplome),
            "/api/reorientation": "/api/reorientation?diplome=" + __import__("urllib.parse").parse.quote(self.diplome),
            "/api/reorientation/voeux": f"/api/reorientation/voeux?ids={c}",
            "/api/calendrier": "/api/calendrier", "/api/calendrier.ics": "/api/calendrier.ics",
            "/api/stats": "/api/stats", "/api/version": "/api/version", "/": "/",
            "/docs": "/docs", "/docs/oauth2-redirect": "/docs/oauth2-redirect", "/redoc": "/redoc", "/openapi.json": "/openapi.json",
            "/formation/{cod}": f"/formation/{c}", "/metier/{met_id}": f"/metier/{self.met_id}",
            "/sitemap.xml": "/sitemap.xml", "/robots.txt": "/robots.txt",
            # sprint Q1: the trust and compliance pages, their app twin and the owner's message list (token: not 200 here)
            "/api/page/{slug}": "/api/page/a-propos", "/api/contact/messages": "/api/contact/messages",
            "/a-propos": "/a-propos", "/contact": "/contact", "/mentions-legales": "/mentions-legales",
            "/confidentialite": "/confidentialite", "/accessibilite": "/accessibilite",
        }


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    calls = []
    saved = A.record
    A.record = lambda t, *a, **k: calls.append(t) or "ok"
    try:
        yield TestClient(api.app), calls, api
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def app_routes(api) -> list[str]:
    return sorted({r.path for r in api.app.routes if getattr(r, "methods", None) and "GET" in r.methods})


# ---------------------------------------------------------------- checks
@check("S1 every GET route has an explicit cache policy, and every sample answers 200")
def s1(c: Ctx):
    with client(c.db) as (cl, _, api):
        routes = app_routes(api)
        samples = c.samples()
        missing = [r for r in routes if r not in samples]
        nopol = [r for r in routes if r in samples and CACHE.policy(samples[r].split("?")[0]) is None]
        # persona and verification reports are produced for the real warehouse only (404 by design elsewhere)
        # persona / verification reports exist for the real warehouse only; a job page needs the Onisep jobs (sprint 12)
        ok_codes = lambda r: ({200, 404} if r in ("/api/metier/{met_id}", "/metier/{met_id}") and not c.has_jobs else  # noqa: E731
                              {200} if c.real or r not in ("/api/journey/persona", "/api/verification") else {200, 404})
        bad = [(r, cl.get(samples[r]).status_code) for r in routes if r in samples and r not in ("/api/stats", "/api/contact/messages")
               and cl.get(samples[r]).status_code not in ok_codes(r)]
    return not missing and not nopol and not bad, f"{len(routes)} routes; no sample {missing}; no policy {nopol}; not 200 {bad}"


@check("S2 a route that records an audience event, or answers with a personal list, is never shared-cached (found by calling it)")
def s2(c: Ctx):
    bad, recorders = [], []
    with client(c.db) as (cl, calls, api):
        for route, url in c.samples().items():
            calls.clear()
            r = cl.get(url, headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/120.0"})
            cc = r.headers.get("cache-control", "")
            if calls:
                recorders.append(route)
                if "s-maxage" in cc or "public" in cc:
                    bad.append((route, cc))
        personal = {cl.get(c.samples()[r]).headers.get("cache-control") for r in ("/api/voeux", "/api/voeux/completer")}
        personal = personal.pop() if len(personal) == 1 else personal
    return not bad and personal == "no-store" and "/api/search" in recorders, \
        f"recording routes {recorders}; shared-cached {bad}; Mes vœux {personal}"


@check("S3 served headers: public only on 200, errors and POST no-store, assets immutable only with the live fingerprint, no cookie cached")
def s3(c: Ctx):
    with client(c.db) as (cl, _, api):
        v = api._asset_version()
        got = {
            "formation": cl.get(f"/api/formation/{c.cod}").headers.get("cache-control"),
            "formation 404": cl.get("/api/formation/999999999").headers.get("cache-control"),
            "stage2 422": cl.get("/api/journey/stage2?mention=zz&type=x").headers.get("cache-control"),
            "unknown route": cl.get("/api/nope").headers.get("cache-control"),
            "asset live": cl.get(f"/static/app.js?v={v}").headers.get("cache-control"),
            "asset old": cl.get("/static/app.js?v=000000000000").headers.get("cache-control"),
            "asset bare": cl.get("/static/app.js").headers.get("cache-control"),
            "page": cl.get("/").headers.get("cache-control"),
            "beacon": cl.post("/api/e", json={"t": "view", "route": "home", "device": "mobile"}).headers.get("cache-control"),
        }
        cookies = [u for u in c.samples().values() if "set-cookie" in cl.get(u).headers and "s-maxage" in cl.get(u).headers.get("cache-control", "")]
    want = {"formation": CACHE.PUBLIC, "formation 404": "no-store", "stage2 422": "no-store", "unknown route": "no-store",
            "asset live": CACHE.IMMUTABLE, "asset old": CACHE.SHORT, "asset bare": CACHE.SHORT, "page": "no-cache", "beacon": "no-store"}
    diff = {k: (got[k], want[k]) for k in want if got[k] != want[k]}
    return not diff and not cookies, f"differ {diff}; cached with a cookie {cookies}"


def used_in_page(js: str, k: str) -> bool:
    """A property READ (f.k or f["k"]); an object-literal key such as { bg: "bac général" } is not a read."""
    return re.search(r"\." + k + r"\b|\[\"" + k + r"\"\]", js) is not None


def js(v: float, d: int) -> str:
    """Number#toLocaleString(maximumFractionDigits=d): ICU rounds the EXACT binary value half away from zero."""
    from decimal import ROUND_HALF_UP, Decimal
    return str(Decimal(v).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def shown(path: str, v):
    """What the page can print of a number: a share as a percent (pc1, pct0), a rate or count as is (fmt, pct)."""
    if not isinstance(v, float):
        return v
    key = re.findall(r"[a-z_]+", path)[-1] if re.findall(r"[a-z_]+", path) else ""
    if 0 <= v <= 1 and not key.startswith("taux"):
        return js(100 * v, 1), js(100 * v, 0)
    return js(v, 0), js(v, 1)


def walk(a, b, path=""):
    """Pairs of (full, public) floats, and keys present in one only."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                yield from walk(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif isinstance(a, float):
        yield path, a, b


@check("S4 the public 'Mon parcours' view drops only unread fields, keeps zones, and every number shown is unchanged")
def s4(c: Ctx):
    js = APP_JS.read_text()
    used_dropped = [k for k in J.STAGE2_DROPPED if used_in_page(js, k)]
    con = duckdb.connect(str(c.db), read_only=True)
    flips, zones, extra, n, size = [], 0, [], 0, [0, 0]
    import json
    for tk in c.types:
        for serie, dkey, m in (("bg", J.doublette_key("MATHS", "SES"), "ab"), ("bt", None, "b")):
            full = J.stage2(con, dkey, m, tk, None, serie=serie)
            pub = J.public_stage2(full)
            size[0] += len(json.dumps(full, default=str))
            size[1] += len(json.dumps(pub, default=str))
            for f, p in zip(full["formations"], pub["formations"]):
                n += 1
                if (f["zone"], f["uncertain"]) != (p["zone"], p["uncertain"]):
                    zones += 1
                extra += [k for k in p if k not in f]
                for path, a, b in walk(f, p):
                    if b is None or abs(a - b) > 10 ** -J.PUBLIC_DECIMALS or shown(path, a) != shown(path, b):
                        flips.append((tk, path, a, b))
    con.close()
    gain = 1 - size[1] / size[0] if size[0] else 0
    ok = not used_dropped and not flips and not zones and not extra and n > 0
    return ok, (f"{n} rows; dropped but read by the page {used_dropped}; zones changed {zones}; numbers shown changed "
                f"{len(flips)} {flips[:2]}; payload -{100 * gain:.0f} %")


@check("S5 Plan B and 'Mes vœux' keep full rows; the 'Mon parcours' count is sent by the page and validated on a closed list")
def s5(c: Ctx):
    from suptracker import analytics as A
    js = APP_JS.read_text()
    con = duckdb.connect(str(c.db), read_only=True)
    full = J.stage2(con, J.doublette_key("MATHS", "SES"), "ab", c.type_key, None)["formations"]
    con.close()
    keeps = bool(full) and all(k in full[0] for k in ("bg", "k_cum", "neobac"))
    sends = ('track("journey", { stage: "stage1" })' in js and 'track("journey", { stage: "stage2" })' in js)
    ok_events = all(A.validate_client_event({"t": "journey", "stage": s}) == ("journey", {"stage": s}) for s in ("stage1", "stage2"))
    rejected = 0
    for bad in ({"t": "journey", "stage": "stage3"}, {"t": "journey"}, {"t": "journey", "stage": ["stage1"]}):
        try:
            A.validate_client_event(bad)
        except A.Rejected:
            rejected += 1
    counted = any("journey" in str(op) for op in A.ops_for("journey", {"stage": "stage2"}, "v", __import__("datetime").date(2026, 1, 1)))
    with client(c.db) as (cl, calls, _):
        calls.clear()
        cl.get(c.samples()["/api/journey/stage2"], headers={"user-agent": "Mozilla/5.0 Firefox/120.0"})
        server_records = list(calls)
    ok = keeps and sends and ok_events and rejected == 3 and counted and not server_records
    return ok, (f"full rows kept {keeps}; page sends both stages {sends}; events valid {ok_events}; hostile rejected {rejected}/3; "
                f"dashboard key written {counted}; server still records {server_records}")


def timed_test_files() -> list[str]:
    """Test files whose red team measures time (a clock call): they must not share the runner with busy workers."""
    out = []
    for t in sorted((ROOT / "tests").glob("test_*.py")):
        for mod in re.findall(r"(?:import |from |import_module\([\"'])(redteam_\w+)", t.read_text()):
            src = ROOT / "scripts" / f"{mod}.py"
            if src.exists() and re.search(r"time\.perf_counter\(\)", src.read_text()):
                out.append(f"tests/{t.name}")
                break
    return out


def ci_ok(ci: str, mon: str) -> tuple[bool, str]:
    push = re.search(r"push:\s*\n\s*branches:\s*\[main\]", ci) is not None
    pr = "pull_request:" in ci
    cancel = "cancel-in-progress: true" in ci
    par = re.search(r"^\s*- run: python -m pytest -q -n auto --dist loadfile(.*)$", ci, re.M)
    ser = re.search(r"^\s*- run: python -m pytest -q (tests/\S+(?: tests/\S+)*)\s*$", ci, re.M)
    timed = timed_test_files()
    serial = bool(par and ser) and all(f"--ignore={t}" in par.group(1) and t in ser.group(1).split() for t in timed)
    sched = re.search(r"schedule:\s*\n\s*- cron:", mon) is not None and "vars.SUPTRACKER_URL" in mon and "scripts/monitor.py" in mon
    # CI speed-up: every shard 1..n of the matrix runs with --shard=i/n, and the "test" check fails when any job fails
    m = re.search(r"shard:\s*\[([\d, ]+)\]", ci)
    shards = [int(x) for x in m.group(1).split(",")] if m else []
    n = re.search(r"--shard=\$\{\{ matrix\.shard \}\}/(\d+)", par.group(1)) if par else None
    sharded = bool(shards and n) and shards == list(range(1, int(n.group(1)) + 1))
    gate = re.search(r"\n  test:\n(?:    .*\n|\s*\n)*?    if: always\(\)\n    needs: \[shard, timed\]", ci) is not None \
        and 'test "${{ needs.shard.result }}" = success && test "${{ needs.timed.result }}" = success' in ci
    return all((push, pr, cancel, bool(par), serial, sched, sharded, gate)), (
        f"push only main {push}; PR {pr}; cancel stale {cancel}; parallel {bool(par)}; timed red teams {timed} serial {serial}; "
        f"monitor scheduled {sched}; shards {shards} with --shard=i/{n.group(1) if n else None} {sharded}; test check gates every job {gate}")


def fake_site(c: Ctx, break_=None):
    """The monitor's fetch, served by the app itself (optionally broken)."""
    def fetch(base, path, timeout):
        with client(c.db) as (cl, _, _api):
            r = cl.get(path, headers={"user-agent": "SupCompassMonitor/1.0 (+uptime check; bot)", "DNT": "1"})
            h = {k.lower(): v for k, v in r.headers.items()}
            st, body = r.status_code, r.content
        if break_:
            st, h, body = break_(path, st, h, body)
        return st, h, body, 0.01
    return fetch


@check("S6 CI runs once per change, cancels stale runs and keeps the timing check serial; the monitor is scheduled and fails on a broken site")
def s6(c: Ctx):
    import monitor as M
    ok, d = ci_ok(CI.read_text(), MON.read_text())
    good = M.checks("http://x", 8, fetch=fake_site(c))
    seen = {}
    M.PAUSE = 0           # no real waiting in the red team

    def vercel(p, st, h, b):
        """Vercel's CDN: s-maxage consumed and stripped; x-vercel-cache MISS then HIT for what the policy shares."""
        cc = h.get("cache-control", "")
        shared = "s-maxage" in cc
        h = {**h, "cache-control": ", ".join(x for x in cc.split(", ") if not x.startswith(("s-maxage", "stale-while")))}
        # a freshly deployed CDN: the first THREE asks of a URL miss, then it hits (the monitor must retry, not alarm)
        seen[p] = seen.get(p, 0) + 1
        h["x-vercel-cache"] = ("HIT" if seen[p] > 3 else "MISS") if shared else "BYPASS"
        return st, h, b
    on_vercel = M.checks("http://x", 8, fetch=fake_site(c, vercel))
    vercel_ok = all(x[1] for x in on_vercel)
    seen.clear()
    never = lambda p, st, h, b: (st, {**h, "x-vercel-cache": "MISS", "cache-control": "public, max-age=300"}, b) if p.startswith("/api/formation") else (st, h, b)  # noqa: E731
    breaks = {
        "down": lambda p, st, h, b: (503, h, b),
        "Vercel never caches the formation": lambda p, st, h, b: (st, {**h, "x-vercel-cache": "BYPASS", "cache-control": "public, max-age=300"}, b)
        if p.startswith("/api/formation") else (st, h, b),
        "Vercel never serves the formation from its cache (MISS forever)": never,
        "Vercel serves Mes vœux from its cache": lambda p, st, h, b: (st, {**h, "x-vercel-cache": "HIT"}, b) if p.startswith("/api/voeux") else (st, h, b),
        "old front-end": lambda p, st, h, b: (st, h, b.replace(b"app.js?v=", b"app.js?v=0")) if p == "/" else (st, h, b),
        "assets not immutable": lambda p, st, h, b: (st, {**h, "cache-control": "public, max-age=300"}, b) if p.startswith("/static") else (st, h, b),
        "list shared-cached": lambda p, st, h, b: (st, {**h, "cache-control": CACHE.PUBLIC}, b) if p.startswith("/api/voeux") else (st, h, b),
    }
    missed = [k for k, br in breaks.items() if all(x[1] for x in M.checks("http://x", 8, fetch=fake_site(c, br)))]
    all_good = all(x[1] for x in good)
    return ok and all_good and vercel_ok and not missed, d + (f"; monitor passes on the app {all_good} {[x for x in good if not x[1]]}; "
                                                          f"behind Vercel's CDN (s-maxage stripped) {vercel_ok} {[x for x in on_vercel if not x[1]]}; broken sites not caught {missed}")


CI_MUTANTS = [
    ("CI runs on every branch push again", "  push:\n    branches: [main]\n", "  push:\n"),
    ("stale runs not cancelled", "cancel-in-progress: true", "cancel-in-progress: false"),
    ("timing check run in parallel", " --ignore=tests/test_analytics.py", ""),
    ("Plan B latency check run in parallel", " --ignore=tests/test_planb.py", ""),
    ("a shard left out of the matrix", "shard: [1, 2, 3]", "shard: [1, 2]"),
    ("shards split for another count", "--shard=${{ matrix.shard }}/3", "--shard=${{ matrix.shard }}/4"),
    ("test check ignores the timed job", ' && test "${{ needs.timed.result }}" = success', ""),
    ("test check skipped when a shard fails", "    if: always()\n    needs: [shard, timed]", "    needs: [shard, timed]"),
]
MON_MUTANTS = [("monitor not scheduled", "  schedule:\n    - cron: \"41 */6 * * *\"\n", "")]


@check("S7 mutation test: policy, slim view, audience count, workflows and monitor bugs are each caught")
def s7(c: Ctx):
    missed = []
    ci, mon = CI.read_text(), MON.read_text()
    for name, old, new in CI_MUTANTS:
        if old not in ci or ci_ok(ci.replace(old, new, 1), mon)[0]:
            missed.append(name)
    for name, old, new in MON_MUTANTS:
        if old not in mon or ci_ok(ci, mon.replace(old, new, 1))[0]:
            missed.append(name)
    from suptracker import analytics as A
    saved_pol, saved_comp = CACHE.POLICY[:], CACHE._COMPILED[:]
    saved_drop, saved_dec, saved_val, saved_tie = J.STAGE2_DROPPED, J.PUBLIC_DECIMALS, A.validate_client_event, J._near_tie
    saved_header = CACHE.header

    def set_policy(pol):
        CACHE.POLICY[:] = pol
        CACHE._COMPILED[:] = [(re.compile(f"^{p}$"), x, w) for p, x, w in pol]

    def swap(route, new):
        set_policy([(p, new if p == route else x, w) for p, x, w in saved_pol])

    def no_journey(e):
        if isinstance(e, dict) and e.get("t") == "journey":
            raise A.Rejected("journey")
        return saved_val(e)

    def cache_errors(method, path, v, status, cur):
        return saved_header(method, path, v, 200, cur)

    mutants = [
        ("search shared-cached (its count lost)", lambda: swap(r"/api/search", CACHE.PUBLIC), (s2,)),
        ("Mes vœux shared-cached", lambda: swap(r"/api/voeux", CACHE.PUBLIC), (s2,)),
        ("'Compléter ma liste' shared-cached", lambda: swap(r"/api/voeux/completer", CACHE.PUBLIC), (s2,)),
        ("a route left without a policy", lambda: set_policy([x for x in saved_pol if x[0] != r"/api/planb/[^/]+"]), (s1,)),
        ("errors cached", lambda: setattr(CACHE, "header", cache_errors), (s3,)),
        ("assets immutable whatever their version", lambda: swap(r"/static/.+", CACHE.IMMUTABLE), (s3,)),
        ("a field the page reads dropped", lambda: setattr(J, "STAGE2_DROPPED", saved_drop + ("cdf_ci", "pct_boursiers")), (s4,)),
        ("numbers rounded too coarsely", lambda: setattr(J, "PUBLIC_DECIMALS", 2), (s4,)),
        ("rounding without the display guard", lambda: setattr(J, "_near_tie", lambda v: False), (s4,)),
        ("the page's audience count rejected", lambda: setattr(A, "validate_client_event", no_journey), (s5,)),
    ]
    for name, apply, fns in mutants:
        try:
            apply()
            caught = any(not fn(c)[0] for fn in fns)
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            set_policy(saved_pol)
            CACHE._COMPILED[:] = saved_comp
            CACHE.header = saved_header
            J.STAGE2_DROPPED, J.PUBLIC_DECIMALS, A.validate_client_event = saved_drop, saved_dec, saved_val
            J._near_tie = saved_tie
        if not caught:
            missed.append(name)
    n = len(CI_MUTANTS) + len(MON_MUTANTS) + len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


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
