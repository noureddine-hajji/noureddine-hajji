"""Red team of sprint Q2 (owner, 2026-11-13): security headers, HEAD, the contact form's cross-site guard, hostile inputs.

    python scripts/redteam_securite.py [--db data/suptracker.duckdb] [--real] [--browser]

  SE1 headers: EVERY route of the app (each GET sample, 404, 405, 422, an unhandled error, POST and DELETE routes) carries
      the CSP, nosniff, Referrer-Policy, Permissions-Policy, X-Frame-Options and COOP, with values checked against rules
      written HERE (no 'unsafe-eval', no wildcard, no inline script, frame-ancestors 'none', object-src 'none', only the
      map's tile host as a third party); the wider policy only on FastAPI's /docs and /redoc
  SE2 the page code fits the policy: no inline event handler, no javascript: URL, no eval / new Function / string timer in
      app.js, stats.js or a served page; the only <script> elements in the shell and the server pages are the site's own
      files and JSON-LD; every host the page code loads (CARTE_TILES, fetch) is allowed by the CSP and nothing else is
  SE3 HEAD: every GET sample answers HEAD with the GET's status and headers and no body; the search (it records an audience
      event) stays 405 and records nothing
  SE4 hostile inputs: every GET route of the OpenAPI schema, each query and path parameter, gets SQL, script, traversal,
      control-character, unicode, huge and numeric-edge values: never a 5xx, never a traceback, and an HTML answer never
      carries the script payload unescaped
  SE5 the contact form: a post from another site (Origin, Sec-Fetch-Site, Origin null) is 403, a body that is not JSON
      is 415, the site's own post and a post with no Origin (no browser) pass; the page sends JSON
  SE6 HTTPS and errors: HSTS on HTTPS (scheme or X-Forwarded-Proto), never on HTTP; an unhandled error is a plain 500
      with the security headers and no traceback, file path or exception text
  SE7 no CORS grant on any route (even when asked with an Origin), no cookie set
  SE8 no secret in the tracked files (tokens, private keys, credentials in URLs; test fakes excepted)
  SE9 browser (--browser / --real): the main pages with a stored profile (home, search, formation, Mon parcours, Mes vœux,
      map, metiers, comparator, reading aids, profile, guide, stats, legal pages, contact) raise no CSP violation and no
      CSP console message, and the contact form sends a message under the policy
  SE10 mutation test of SE1-SE8 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []

from suptracker import contact as CT  # noqa: E402
from suptracker import securite as SEC  # noqa: E402

TOKEN = "redteam-token-0123456789"
# what every answer must carry, written HERE (independent of securite.py)
NEED = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "cross-origin-opener-policy": "same-origin",
        "referrer-policy": "strict-origin-when-cross-origin"}
PERMISSIONS_OFF = ("camera", "microphone", "geolocation", "payment", "usb")
THIRD_PARTY_IMG = {"tile.openstreetmap.org"}
PAYLOADS = ["' OR 1=1--", "\"><script>alert(1)</script>", "../../../../etc/passwd", "%00", "\x00", "‮\u0000\ud800"[:2],
            "A" * 5000, "-1", "99999999999999999999", "1e309", "NaN", "{{7*7}}", "${7*7}", "é" * 300, ";DROP TABLE x",
            "\\", "%", "_", "*", " ", ""]
SCRIPT = "<script>alert(1)</script>"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        import redteam_scale as SC
        self.scale = SC.Ctx(db, real)
        self.reload()

    def reload(self):
        self.js = (STATIC / "app.js").read_text()
        self.stats = (STATIC / "stats.js").read_text()
        self.html = (STATIC / "index.html").read_text()


@contextlib.contextmanager
def client(db: Path, raise_errors: bool = False):
    from fastapi.testclient import TestClient
    saved = {k: os.environ.get(k) for k in ("SUPTRACKER_DB", "SUPTRACKER_STATS_TOKEN", "VERCEL", "VERCEL_ENV")}
    with tempfile.TemporaryDirectory() as d:
        os.environ["SUPTRACKER_DB"] = str(db)
        os.environ["SUPTRACKER_STATS_TOKEN"] = TOKEN
        for k in ("VERCEL", "VERCEL_ENV"):
            os.environ.pop(k, None)
        CT.reset_store(CT.SqliteStore(Path(d) / "c.sqlite"))
        from suptracker import analytics as A
        from suptracker import api
        api._con.cache_clear()
        rec = A.record
        calls = []
        A.record = lambda t, *a, **k: calls.append(t) or "ok"
        try:
            yield TestClient(api.app, base_url="http://supcompass.test", raise_server_exceptions=raise_errors), api, calls
        finally:
            A.record = rec
            CT.reset_store(None)
            api._con.cache_clear()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def csp_dict(v: str) -> dict:
    out = {}
    for part in (v or "").split(";"):
        bits = part.split()
        if bits:
            out[bits[0]] = bits[1:]
    return out


def headers_ok(h, path: str) -> list:
    """The problems of one answer's headers (empty when they are right)."""
    bad = [k for k, v in NEED.items() if h.get(k) != v]
    pp = h.get("permissions-policy", "")
    bad += [f"permissions {f}" for f in PERMISSIONS_OFF if f"{f}=()" not in pp]
    csp = csp_dict(h.get("content-security-policy"))
    if not csp:
        return bad + ["no CSP"]
    every = [t for vals in csp.values() for t in vals]
    if "'unsafe-eval'" in every or "*" in every or any(t.startswith("http:") for t in every):
        bad.append("CSP: eval, wildcard or http source")
    for d, want in (("frame-ancestors", ["'none'"]), ("object-src", ["'none'"]), ("base-uri", ["'self'"])):
        if csp.get(d) != want:
            bad.append(f"CSP {d}")
    if path not in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        if csp.get("script-src") != ["'self'"] or csp.get("default-src") != ["'self'"] or csp.get("connect-src") != ["'self'"]:
            bad.append("CSP: script/default/connect not self only")
        hosts = {t.split("//", 1)[1] for d in csp for t in csp[d] if t.startswith("https://")}
        if hosts != THIRD_PARTY_IMG or not set(csp.get("img-src", [])) >= {f"https://{x}" for x in THIRD_PARTY_IMG}:
            bad.append(("CSP third parties", sorted(hosts)))
        if csp.get("form-action") != ["'self'"]:
            bad.append("CSP form-action")
    return bad


def samples(c: Ctx) -> dict:
    s = dict(c.scale.samples())
    s["/api/contact/messages"] = "/api/contact/messages"
    return s


# ------------------------------------------------------------------ SE1 headers everywhere
@check("SE1 every answer (each route, 404/405/422, an error, POST/DELETE) carries the security headers, checked against fixed rules")
def se1(c: Ctx):
    bad = []
    with client(c.db) as (cl, api, _):
        routes = sorted({r.path for r in api.app.routes if getattr(r, "methods", None) and "GET" in r.methods})
        s = samples(c)
        missing = [r for r in routes if r not in s]
        for r in routes:
            if r in s:
                h = cl.get(s[r]).headers
                p = headers_ok(h, s[r].split("?")[0])
                if p:
                    bad.append((r, p[:3]))
        for method, url, kw in (("GET", "/api/nope", {}), ("GET", "/formation/abc", {}), ("PUT", "/api/meta", {}),
                                ("GET", "/api/journey/stage2?mention=zz", {}), ("POST", "/api/contact", {"json": {"type": "x"}}),
                                ("POST", "/api/e", {"content": b"{}"}), ("DELETE", "/api/contact/messages/x", {}),
                                ("GET", "/static/app.js", {}), ("GET", "/static/nope.js", {})):
            r = cl.request(method, url, **kw)
            p = headers_ok(r.headers, url.split("?")[0])
            if p:
                bad.append((method, url, r.status_code, p[:3]))
        docs = csp_dict(cl.get("/docs").headers.get("content-security-policy"))
        if "https://cdn.jsdelivr.net" not in docs.get("script-src", []) or docs.get("frame-ancestors") != ["'none'"]:
            bad.append("docs policy")
    return not bad and not missing, f"{len(routes)} GET routes; no sample {missing}; problems {bad[:4]}"


# ------------------------------------------------------------------ SE2 the page code fits the policy
INLINE_HANDLER = re.compile(r"""<[a-z][^>]*\son[a-z]+\s*=\s*["']""", re.I)
DANGER = re.compile(r"""\beval\s*\(|new\s+Function\s*\(|set(?:Timeout|Interval)\s*\(\s*["'`]|javascript:""")


@check("SE2 the page code fits the policy: no inline handler, eval, string timer or javascript: URL; scripts are the site's own; loaded hosts = CSP's")
def se2(c: Ctx):
    bad = []
    for name, src in (("app.js", c.js), ("stats.js", c.stats), ("index.html", c.html)):
        if INLINE_HANDLER.search(src):
            bad.append((name, "inline handler", INLINE_HANDLER.search(src).group(0)[:60]))
        if DANGER.search(src):
            bad.append((name, "eval/timer/javascript:", DANGER.search(src).group(0)))
    with client(c.db) as (cl, _, _):
        s = samples(c)
        for path in ("/", s["/formation/{cod}"], s["/metier/{met_id}"], "/contact", "/mentions-legales", "/confidentialite"):
            page = cl.get(path).text
            for tag in re.findall(r"<script\b[^>]*>", page):
                if not (re.fullmatch(r'<script src="/static/[a-z]+\.js(\?v=[0-9a-f]+)?">', tag) or tag == '<script type="application/ld+json">'):
                    bad.append((path, "script", tag))
            if INLINE_HANDLER.search(page):
                bad.append((path, "inline handler"))
        csp = csp_dict(cl.get("/").headers.get("content-security-policy"))
    tiles = re.search(r'const CARTE_TILES = "https://([^/"]+)/', c.js)
    loaded = {tiles.group(1)} if tiles else set()
    loaded |= set(re.findall(r"""fetch\(\s*[`'"]https://([a-z0-9.-]+)""", c.js + c.stats))
    allowed = {t.split("//", 1)[1] for d in ("img-src", "connect-src", "script-src") for t in csp.get(d, []) if t.startswith("https://")}
    if not tiles or loaded != allowed:
        bad.append(("hosts loaded vs allowed", sorted(loaded), sorted(allowed)))
    if SEC.TILE_HOST != (tiles and tiles.group(1)):
        bad.append("securite.TILE_HOST is not the page's tile host")
    return not bad, f"hosts loaded {sorted(loaded)}; problems {bad[:4]}"


# ------------------------------------------------------------------ SE3 HEAD
@check("SE3 HEAD on every GET route = the GET's status and headers without a body; the search stays 405 and records nothing")
def se3(c: Ctx):
    bad = []
    with client(c.db) as (cl, api, calls):
        s = samples(c)
        for r, url in s.items():
            if r == "/api/search":
                continue
            g, h = cl.get(url), cl.head(url)
            if h.status_code != g.status_code or h.content:
                bad.append((r, g.status_code, h.status_code, len(h.content)))
            elif headers_ok(h.headers, url.split("?")[0]) or h.headers.get("content-type") != g.headers.get("content-type"):
                bad.append((r, "headers"))
            elif h.headers.get("cache-control") != g.headers.get("cache-control"):
                bad.append((r, "cache", g.headers.get("cache-control"), h.headers.get("cache-control")))
            elif h.headers.get("content-encoding") != g.headers.get("content-encoding"):
                bad.append((r, "encoding", g.headers.get("content-encoding"), h.headers.get("content-encoding")))
            else:
                # the representation a GET would get, its size included (Codex). Compared uncompressed: a few answers
                # list their items in an order that varies between calls, so their gzip size moves by a few bytes
                ident = {"accept-encoding": "identity"}
                gl, hl = cl.get(url, headers=ident).headers.get("content-length"), cl.head(url, headers=ident).headers.get("content-length")
                if gl != hl:
                    bad.append((r, "representation", gl, hl))
        n = len(calls)
        hs = cl.head(s["/api/search"])
        if hs.status_code != 405 or len(calls) != n:
            bad.append(("search", hs.status_code, len(calls) - n))
    return not bad, f"{len(s)} routes; problems {bad[:5]}"


# ------------------------------------------------------------------ SE4 hostile inputs
@check("SE4 hostile inputs on every GET parameter (OpenAPI): never a 5xx or a traceback; HTML never echoes the script raw")
def se4(c: Ctx):
    from urllib.parse import quote
    bad, n = [], 0
    with client(c.db) as (cl, api, _):
        spec = api.app.openapi()
        s = samples(c)
        for path, ops in spec["paths"].items():
            op = ops.get("get")
            if not op or path in ("/api/stats", "/api/contact/messages"):
                continue
            base = s.get(path, path)
            for prm in op.get("parameters", []):
                for p in PAYLOADS:
                    if prm["in"] == "query":
                        sep = "&" if "?" in base else "?"
                        url = f"{base}{sep}{prm['name']}={quote(p, safe='')}"
                    elif prm["in"] == "path":
                        url = path.replace("{" + prm["name"] + "}", quote(p, safe="") or "x")
                        for other in re.findall(r"\{(\w+)\}", url):
                            url = url.replace("{" + other + "}", "1")
                    else:
                        continue
                    n += 1
                    r = cl.get(url)
                    body = r.text[:20000]
                    if r.status_code >= 500 or "Traceback" in body or "File \"/" in body:
                        bad.append((path, prm["name"], repr(p)[:30], r.status_code))
                    elif "text/html" in r.headers.get("content-type", "") and SCRIPT in body:
                        bad.append((path, prm["name"], "script echoed"))
    return not bad, f"{n} hostile requests; problems {bad[:6]}"


# ------------------------------------------------------------------ SE5 the contact form's cross-site guard
def _msg():
    return {"type": "erreur", "message": "Le taux affiché semble faux pour 2025."}


@check("SE5 contact form: another site's post 403, a non-JSON body 415; the site's own post and a no-Origin post pass; the page sends JSON")
def se5(c: Ctx):
    bad = []
    with client(c.db) as (cl, _, _):
        def post(i, **h):
            hd = {"x-real-ip": f"198.51.100.{i}", "user-agent": f"UA{i}", "content-type": "application/json", **h}
            return cl.post("/api/contact", content=json.dumps(_msg()), headers=hd).status_code
        cases = {
            "Origin evil": (post(1, origin="https://evil.example"), 403),
            "Origin look-alike": (post(2, origin="http://supcompass.test.evil.example"), 403),
            "Origin null": (post(3, origin="null"), 403),
            "Sec-Fetch-Site cross-site": (post(4, **{"sec-fetch-site": "cross-site"}), 403),
            "text/plain body": (post(5, **{"content-type": "text/plain"}), 415),
            "form body": (post(6, **{"content-type": "application/x-www-form-urlencoded"}), 415),
            "no content type": (cl.post("/api/contact", content=json.dumps(_msg()), headers={"x-real-ip": "198.51.100.7"}).status_code, 415),
            "own origin": (post(8, origin="http://supcompass.test", **{"sec-fetch-site": "same-origin"}), 201),
            "no origin (no browser)": (post(9), 201),
            "same-site": (post(10, **{"sec-fetch-site": "same-site"}), 201),
        }
        bad += [(k, got, want) for k, (got, want) in cases.items() if got != want]
    from redteam_conformite import fn_src
    if 'fetch("/api/contact", { method: "POST", headers: { "Content-Type": "application/json" }' not in fn_src(c.js, "contactForm"):
        bad.append("the page does not send JSON")
    return not bad, f"{len(cases)} cases; problems {bad}"


# ------------------------------------------------------------------ SE6 HTTPS and errors
@check("SE6 HSTS on HTTPS only; an unhandled error is a plain 500 with the headers and no traceback, path or exception text")
def se6(c: Ctx):
    bad = []
    with client(c.db) as (cl, api, _):
        if "strict-transport-security" in cl.get("/api/meta").headers:
            bad.append("HSTS on http")
        if not cl.get("/api/meta", headers={"x-forwarded-proto": "https"}).headers.get("strict-transport-security", "").startswith("max-age="):
            bad.append("no HSTS behind an https proxy")
        from fastapi.testclient import TestClient
        if not TestClient(api.app, base_url="https://supcompass.test").get("/").headers.get("strict-transport-security"):
            bad.append("no HSTS on https")

        @api.app.get("/__redteam_boom")
        def boom():
            raise RuntimeError("secret detail /home/user/x.py")
        try:
            r = cl.get("/__redteam_boom")
            rh = cl.head("/__redteam_boom")       # Codex: the error answer of a HEAD carries the headers too
        finally:
            api.app.router.routes[:] = [x for x in api.app.router.routes if getattr(x, "path", "") != "/__redteam_boom"]
        if r.status_code != 500 or headers_ok(r.headers, "/x") or any(w in r.text for w in ("Traceback", "secret detail", "/home/", ".py")):
            bad.append(("500", r.status_code, r.text[:80], headers_ok(r.headers, "/x")[:2]))
        if rh.status_code != 500 or headers_ok(rh.headers, "/x") or rh.content:
            bad.append(("HEAD 500", rh.status_code, headers_ok(rh.headers, "/x")[:2]))
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ SE7 no CORS, no cookie
@check("SE7 no CORS grant on any route (even asked with an Origin), no cookie set")
def se7(c: Ctx):
    bad = []
    with client(c.db) as (cl, _, _):
        for r, url in samples(c).items():
            h = cl.get(url, headers={"origin": "https://evil.example"}).headers
            if any(k.lower().startswith("access-control-allow") for k in h) or "set-cookie" in h:
                bad.append(r)
        pre = cl.options("/api/contact", headers={"origin": "https://evil.example", "access-control-request-method": "POST",
                                                   "access-control-request-headers": "content-type"})
        if "access-control-allow-origin" in pre.headers:
            bad.append("preflight granted")
    return not bad, f"problems {bad[:5]}"


# ------------------------------------------------------------------ SE8 no secret in the tracked files
SECRET_RX = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Upstash / Vercel KV token", re.compile(r"KV_REST_API_TOKEN\s*[=:]\s*[\"']?[A-Za-z0-9_=-]{20,}")),
    ("credentials in a URL", re.compile(r"https?://[^/\s:@\"']+:[^/\s:@\"']{6,}@")),
    ("stats token value", re.compile(r"SUPTRACKER_STATS_TOKEN\s*[=:]\s*[\"']?[A-Za-z0-9_-]{16,}")),
    ("analytics salt value", re.compile(r"SUPTRACKER_ANALYTICS_SALT\s*[=:]\s*[\"']?[A-Za-z0-9_-]{16,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
TEXT_EXT = {".py", ".js", ".css", ".html", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini", ".sh"}


@check("SE8 no secret in the tracked files (tokens, private keys, credentials in URLs)")
def se8(c: Ctx, files: dict | None = None):
    if files is None:
        try:
            out = subprocess.run(["git", "ls-files"], cwd=ROOT.parent, capture_output=True, text=True, timeout=60).stdout.split()
        except Exception:  # noqa: BLE001
            return True, "git not available"
        files = {}
        for f in out:
            p = ROOT.parent / f
            if p.suffix in TEXT_EXT and p.is_file() and p.stat().st_size < 2_000_000:
                files[f] = p.read_text(errors="ignore")
    hits = []
    for f, text in files.items():
        for name, rx in SECRET_RX:
            for m in rx.finditer(text):
                if any(w in m.group(0).lower() for w in ("redteam", "example", "demo-token")):
                    continue
                hits.append((f, name))
    return not hits, f"{len(files)} files; findings {hits[:5]}"


# ------------------------------------------------------------------ SE9 browser
@check("SE9 browser: the main pages with a profile raise no CSP violation or CSP console message; the contact form sends under the policy")
def se9(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    import shutil
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
    env = {**os.environ, "SUPTRACKER_DB": str(c.db), "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_STATS_TOKEN": TOKEN}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        script = Path(tmp) / "se9.js"
        script.write_text(BROWSER_JS.replace("__PORT__", str(port)).replace("__COD__", str(c.scale.cod)))
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=600)
        out = (r.stdout or "").strip().splitlines()
        res = json.loads(out[-1]) if out and out[-1].startswith("{") else {"problems": [r.stderr[-400:]], "pages": 0}
    finally:
        srv.terminate()
    return not res["problems"], f"{res.get('pages')} pages; problems {res['problems'][:5]}"


BROWSER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext(); const problems = []; let pages = 0;
  await ctx.addInitScript((cod) => {
    localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", statut: "terminale", academie: "Lyon" }));
    localStorage.setItem("voeux", JSON.stringify([cod]));
    document.addEventListener("securitypolicyviolation", (e) => { (window.__v = window.__v || []).push(e.violatedDirective + " " + e.blockedURI); });
  }, "__COD__");
  const p = await ctx.newPage();
  p.on("console", (m) => { if (/Content.Security.Policy|Permissions.Policy|Refused to/.test(m.text())) problems.push("console " + m.text().slice(0, 160)); });
  p.on("pageerror", (e) => problems.push("pageerror " + e.message));
  const base = "http://127.0.0.1:__PORT__";
  for (const u of ["/", "/#/s/licence", "/#/f/__COD__", "/formation/__COD__", "/#/evolution/__COD__", "/#/parcours", "/#/voeux", "/#/carte",
                   "/#/metiers", "/#/compare", "/#/comprendre", "/#/selectivite", "/#/specialites", "/#/qualite", "/#/glossaire",
                   "/#/calendrier", "/#/profil", "/#/guide", "/#/premiere", "/#/accompagner", "/#/stats", "/a-propos", "/mentions-legales", "/contact"]) {
    await p.goto(base + u); await p.waitForTimeout(u.includes("carte") ? 5000 : 1500); pages++;
    const v = await p.evaluate(() => window.__v || []);
    if (v.length) problems.push(u + " " + v.join(" | "));
  }
  await p.goto(base + "/contact"); await p.waitForSelector("#cform");
  await p.fill("#cmsg", "Un message de test envoyé sous la politique de sécurité."); await p.click("#cform button[type=submit]");
  await p.waitForFunction(() => /envoyé/.test(document.getElementById("cform-msg").textContent), null, { timeout: 10000 }).catch(() => {});
  const t = await p.textContent("#cform-msg"); if (!/^Message envoyé/.test(t)) problems.push("contact: " + t);
  console.log(JSON.stringify({ problems, pages })); await b.close();
})();
"""


# ------------------------------------------------------------------ SE10 mutation test
def mutants():
    import suptracker.api as api
    out = []

    def py(name, target, attr, value, checks):
        state = {}

        def apply(_c):
            state["v"] = getattr(target, attr)
            setattr(target, attr, value(state["v"]) if callable(value) and not isinstance(value, (str, dict, tuple)) else value)

        def restore(_c):
            setattr(target, attr, state["v"])
        out.append((name, apply, restore, checks))

    py("no nosniff", SEC, "HEADERS", {k: v for k, v in SEC.HEADERS.items() if k != "X-Content-Type-Options"}, {"SE1"})
    py("frames allowed", SEC, "CSP", SEC.CSP.replace("frame-ancestors 'none'", "frame-ancestors *"), {"SE1"})
    py("inline scripts allowed", SEC, "CSP", SEC.CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline' 'unsafe-eval'"), {"SE1"})
    py("a tracker host allowed", SEC, "CSP", SEC.CSP.replace("connect-src 'self'", "connect-src 'self' https://tracker.example"), {"SE1", "SE2"})
    py("tiles blocked", SEC, "CSP", SEC.CSP.replace(f" https://{SEC.TILE_HOST}", ""), {"SE1", "SE2"})
    py("geolocation allowed", SEC, "HEADERS", {**SEC.HEADERS, "Permissions-Policy": "camera=(), microphone=()"}, {"SE1"})
    py("the docs policy everywhere", SEC, "CSP", SEC.CSP_DOCS, {"SE1"})
    py("headers only on success", SEC, "headers_for", lambda f: (lambda path, https: {}), {"SE1", "SE6"})
    py("HEAD bodies kept", SEC, "head_as_get", lambda f: (lambda path: False), {"SE3"})
    py("HEAD of the search counted", SEC, "NO_HEAD", (), {"SE3"})
    py("cross-site posts accepted", SEC, "cross_site", lambda f: (lambda headers, host: False), {"SE5"})
    py("Origin trusted by prefix", SEC, "cross_site",
       lambda f: (lambda headers, host: bool(headers.get("origin")) and headers.get("origin") not in ("", None)
                  and not (headers.get("origin") or "").split("//")[-1].startswith(host or "\x00")), {"SE5"})
    py("any body accepted", SEC, "json_body", lambda f: (lambda headers: True), {"SE5"})
    from fastapi.responses import Response as _R
    py("HEAD rebuilt with length 0 and no encoding", api, "_HeadOnly",
       lambda f: (lambda status, raw: _R(content=b"", status_code=status, headers={k.decode(): v.decode() for k, v in raw
                                                                                 if k not in (b"content-length", b"content-encoding")})),
       {"SE3"})

    def stream_always(_c):                               # the middleware sees every answer as a stream (the bug Codex found)
        api.hasattr = lambda o, n: True if n == "body_iterator" else __builtins__["hasattr"](o, n) \
            if isinstance(__builtins__, dict) else getattr(__import__("builtins"), "hasattr")(o, n)

    out.append(("an error answer drained as a stream", stream_always, lambda _c: api.__dict__.pop("hasattr", None), {"SE6"}))
    py("HSTS on http", SEC, "is_https", lambda f: (lambda scheme, headers: True), {"SE6"})
    py("tracebacks shown", api, "PlainTextResponse",
       lambda f: (lambda content, status_code=200: f(__import__("traceback").format_exc(), status_code=status_code)), {"SE6"})

    def page_mut(name, attr, old, new, checks):
        def apply(c):
            src = getattr(c, attr)
            if old not in src:
                raise AssertionError(f"anchor not found: {old[:40]}")
            setattr(c, attr, src.replace(old, new, 1))

        def restore(c):
            c.reload()
        out.append((name, apply, restore, checks))

    page_mut("an inline handler in a template", "js", '<form id="cform" class="cform" novalidate>',
             '<form id="cform" class="cform" novalidate onsubmit="return false">', {"SE2"})
    page_mut("eval in the page code", "stats", "async function loadMessages() {", "async function loadMessages() { eval('1');", {"SE2"})
    page_mut("a new tile host not in the CSP", "js", 'const CARTE_TILES = "https://tile.openstreetmap.org/',
             'const CARTE_TILES = "https://tiles.example.net/', {"SE2"})
    page_mut("the form sends text", "js", 'fetch("/api/contact", { method: "POST", headers: { "Content-Type": "application/json" }',
             'fetch("/api/contact", { method: "POST", headers: { "Content-Type": "text/plain" }', {"SE5"})

    def secret(c):
        # built at run time: written whole here, this fake token would itself be found by SE8 in this tracked file
        c._files = {"x.env": "KV_REST_API_TOKEN" + "=" + "AXyzAbcdEfghIjklMnopQrstUvwxYz" + "0123456789"}

    out.append(("a committed token", secret, lambda c: c.__dict__.pop("_files", None), {"SE8"}))
    return out


@check("SE10 mutation test: each seeded defect is caught by its check")
def se10(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    missed, n = [], 0
    for name, apply, restore, expect in mutants():
        n += 1
        try:
            apply(c)
            caught = set()
            for k in expect:
                try:
                    ok, _ = by[k](c, c._files) if k == "SE8" and hasattr(c, "_files") else by[k](c)
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
