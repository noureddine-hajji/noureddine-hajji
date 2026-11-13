"""Red team of sprint Q1 (owner, 2026-11-13): trust and compliance pages and the contact form.

    python scripts/redteam_conformite.py [--db data/suptracker.duckdb] [--real] [--browser]

  QC1 legal notice: the publisher and the publication director (owner's wording), the host's name and postal address, the
      non-professional publisher's LCEN sentence, independence, and EVERY source "en_ligne" of sources.py with its licence
      (re-read from the register: a source missing from the page is caught); the server page and /api/page give the same HTML
  QC2 privacy: every third party the pages contact is named (host, analytics store, map tile host read from the page code's
      CARTE_TILES), every retention said is the code's constant (analytics days, k-anonymity, contact months), the profile
      stays in the browser, DNT/GPC, the CNIL; no cookie is set by any page
  QC3 accessibility statement: no conformity claimed without an audit ("non conforme" in the RGAA sense, never "partiellement"
      or "totalement conforme"), the checks actually run, the known limits, a contact, the Défenseur des droits with its free
      postal address, a date; the footer says "Accessibilité : non conforme"
  QC4 the form: a closed list of subjects (page twin = server list, same labels), length bounds, unknown fields refused, the
      hidden field refuses robots, page / code / e-mail validated, control and bidi characters stripped; hostile text kept as
      TEXT and escaped by the dashboard (every field of a message goes through esc())
  QC5 what is stored: exactly the form's fields + id + day; no IP, user agent or pseudonym in a message (store dump); the
      message expires after 12 months (its own TTL)
  QC6 limits and failure: 5 messages per visitor and day, then 429 (another visitor still passes), a global daily cap; a store
      that fails gives a 503 "non envoyé", and the page shows success ONLY on a 201 with ok
  QC7 owner endpoints and caching: messages need the stats token (401 without, 503 with no token configured), delete works
      (404 twice, 422 on a bad id); /api/contact* no-store, /api/page public, the pages PAGE; robots.txt keeps /api/contact
      off; the sitemap lists the five pages
  QC8 one tagline everywhere (index.html, the home head, the app's titles, legal.TAGLINE); "les vrais chiffres" is gone
  QC9 wiring: footer links on every server page, the five addresses open their page in the app (pathRoute), the "info" route
      is a closed audience route, the formation page links "Signaler une erreur" with its code, the README and CLAUDE.md say it;
      vouvoiement in every page and in the form
  QC10 browser (--browser / --real): the five pages and the form on a phone and a wide dark screen: one h1, no horizontal
      scroll at 320 px, axe-core (when installed) finds nothing, a message is sent, a 503 is said "non envoyé" with the
      button usable again, and the only third-party host contacted on the home, a formation, the map and the contact page is
      the map's tile host, named in the privacy page
  QC11 mutation test of QC1-QC9 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import contextlib
import html as H
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []

from suptracker import analytics as A  # noqa: E402
from suptracker import cache as CACHE  # noqa: E402
from suptracker import contact as CT  # noqa: E402
from suptracker import legal as LG  # noqa: E402
from suptracker import seo as SEO  # noqa: E402
from suptracker import sources as SRC  # noqa: E402

TOKEN = "redteam-token-0123456789"
# what the pages must name, written here independently of legal.py (a page that drops one is caught)
OWNER = "M. N. HAJJI"                                         # owner's wording, 2026-11-13
HOST_NAME, HOST_STREET = "Vercel Inc.", "440 N Barranca Ave #4133, Covina, CA 91723"   # Vercel's own terms of service
STORE_NAME = "Upstash"                                        # analytics.py / contact.py: UPSTASH_REDIS_REST_URL or KV_REST_API_URL
OPERATOR = {"tile.openstreetmap.org": "OpenStreetMap Foundation"}   # every host a page loads -> who runs it
PER_DAY, RETENTION = 5, 365                                   # owner-confirmed limits (5 messages per visitor-day, 12 months)
TU = re.compile(r"\b(tu|ton|ta|tes|toi|t'|te)\b", re.I)


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path | None, real: bool = False, browser: bool = False):
        self.db = db if db and Path(db).exists() else None
        self.real, self.browser = real, browser
        self.reload()

    def reload(self):
        self.html = (STATIC / "index.html").read_text()
        self.js = (STATIC / "app.js").read_text()
        self.stats = (STATIC / "stats.js").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


def text_of(fragment: str) -> str:
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


@contextlib.contextmanager
def client(db: Path | None):
    """The app with a private SQLite contact store and the owner's token."""
    from fastapi.testclient import TestClient
    saved = {k: os.environ.get(k) for k in ("SUPTRACKER_DB", "SUPTRACKER_STATS_TOKEN", "VERCEL_ENV")}
    with tempfile.TemporaryDirectory() as d:
        if db:
            os.environ["SUPTRACKER_DB"] = str(db)
        os.environ["SUPTRACKER_STATS_TOKEN"] = TOKEN
        os.environ.pop("VERCEL_ENV", None)
        CT.reset_store(CT.SqliteStore(Path(d) / "contact.sqlite"))
        from suptracker import api
        try:
            yield TestClient(api.app, base_url="https://supcompass.test"), api
        finally:
            CT.reset_store(None)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def fn_src(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", js, re.M)
    if not m:
        raise KeyError(name)
    return js[m.start(): js.find("\n}", m.start()) + 2]


# ------------------------------------------------------------------ QC1 legal notice
@check("QC1 legal notice: publisher, director, host and address, LCEN, independence, every served source with its licence")
def qc1(c: Ctx):
    t = text_of(LG.mentions_legales())
    need = {
        "publisher": f"édité par {OWNER}, à titre personnel" in t,
        "director": "Directeur de la publication" in t and t.count(OWNER) >= 2,
        "host": HOST_NAME in t and HOST_STREET in t,
        "lcen": "2004-575" in t and "éléments d'identification à l'hébergeur" in t,
        "independent": "n'est affilié ni à Parcoursup" in t,
        "contact": 'href="/contact"' in LG.mentions_legales(),
        "privacy link": 'href="/confidentialite"' in LG.mentions_legales(),
        "map licence": "OpenStreetMap" in t and "ODbL" in t,
    }
    missing_src = [s["key"] for s in SRC.SOURCES if s.get("status") == "en_ligne"
                   and not (s["title"] in t and (s.get("licence") or "") in t)]
    same = True
    with client(c.db) as (cl, _):
        for slug in LG.SLUGS:
            page = cl.get(f"/{slug}").text
            api_html = cl.get(f"/api/page/{slug}").json()["html"]
            same &= api_html in page
    bad = [k for k, v in need.items() if not v]
    return not bad and not missing_src and same, f"missing {bad}; sources not listed {missing_src}; server page = app page {same}"


# ------------------------------------------------------------------ QC2 privacy
@check("QC2 privacy: every third party named (host, store, the map's tile host), retentions = the code's constants, no cookie")
def qc2(c: Ctx):
    t = text_of(LG.confidentialite())
    tiles = re.search(r'const CARTE_TILES = "https://([^/"]+)/', c.js)
    hosts = re.findall(r"https://([a-z0-9.-]+)", c.js)
    # hosts the page LOADS (tiles, scripts, fetch); links the student follows (Parcoursup fiches, sources) are not contacted
    loaded = {tiles.group(1)} if tiles else set()
    loaded |= {h for h in hosts if re.search(rf"fetch\(\s*[`'\"]https://{re.escape(h)}", c.js)}
    named = {h: OPERATOR.get(h, "\x00") in t for h in loaded}
    need = {
        "host": HOST_NAME in t,
        "store": STORE_NAME in t,
        "analytics days": f"{A.RETENTION_DAYS} jours" in t,
        "k-anon": f"au moins {A.K_ANON} visiteurs" in t,
        "contact months": f"{CT.RETENTION_DAYS // 365 * 12} mois" in t,
        "profile in browser": "uniquement dans votre navigateur" in t,
        "lycée never sent": "lycée et votre académie ne sont jamais envoyés" in t,
        "no IP stored": "Aucune adresse IP" in t,
        "dnt/gpc": "Do Not Track" in t and "Global Privacy Control" in t,
        "cnil": "cnil.fr" in LG.confidentialite(),
        "rights": "effacement" in t,
        "under 15": "moins de 15 ans" in t,
        "no other third party": "aucun autre service tiers" in t,
    }
    cookies = []
    with client(c.db) as (cl, _):
        for p in ("/", *(f"/{s}" for s in LG.SLUGS), *(("/api/meta",) if c.db else ())):
            if "set-cookie" in {k.lower() for k in cl.get(p).headers}:
                cookies.append(p)
    bad = [k for k, v in need.items() if not v] + [h for h, ok in named.items() if not ok]
    return bool(tiles) and not bad and not cookies, f"loaded third-party hosts {sorted(loaded)}; missing {bad}; cookies {cookies}"


# ------------------------------------------------------------------ QC3 accessibility statement
@check("QC3 accessibility statement: 'non conforme' without an audit, checks run, known limits, contact, Défenseur des droits")
def qc3(c: Ctx):
    page = LG.accessibilite()
    t = text_of(page)
    need = {
        "no audit said": "n'a pas encore fait l'objet d'un audit" in t,
        "non conforme": "non conforme" in t,
        "no false claim": not re.search(r"(partiellement|totalement|pleinement) conforme", t, re.I),
        "rgaa": "RGAA 4.1" in t and "WCAG 2.1" in t,
        "checks": "axe-core" in t and "320 pixels" in t,
        "limits": "Limites connues" in t and "carte" in t and "PDF" in t and "lecteur d'écran" in t,
        "contact": 'href="/contact"' in page,
        "defenseur": "Défenseur des droits" in t and "Libre réponse 71120" in t and LG.DEFENSEUR in page,
        "date": LG.UPDATED in t,
        "footer": "Accessibilité : non conforme" in LG.footer(),
    }
    bad = [k for k, v in need.items() if not v]
    return not bad, f"missing {bad}"


# ------------------------------------------------------------------ QC4 the form
def _ok(**kw):
    base = {"type": "erreur", "message": "Le taux affiché pour 2025 semble faux."}
    base.update(kw)
    return base


@check("QC4 the form: closed subjects (twin = server), bounds, unknown fields, hidden field, validated page/code/e-mail, escaped")
def qc4(c: Ctx):
    bad = []

    def refused(p, field=None):
        try:
            CT.validate(p)
        except CT.Invalid as e:
            return field is None or e.field == field
        return False

    cases = [
        (_ok(type="spam"), "type"), (_ok(type=None), "type"), (_ok(message="court"), "message"),
        (_ok(message="x" * (CT.MSG_MAX + 1)), "message"), (_ok(message="   \n\t  "), "message"), (_ok(site="http://spam"), "site"),
        (_ok(extra="1"), None), (_ok(page="javascript:alert(1)"), "page"), (_ok(page="/" + "a" * 300), "page"),
        (_ok(code="12a"), "code"), (_ok(code="1234567890"), "code"), (_ok(email="pas-une-adresse"), "email"),
        (_ok(email="a@b.c<script>"), "email"), (_ok(message=123), None), ("not a dict", None), (None, None),
    ]
    for p, f in cases:
        if not refused(p, f):
            bad.append(("accepted", str(p)[:60]))
    good = CT.validate(_ok(message="  <script>alert('x')</script>‮\u0000 réel  ", page="/formation/6332", code="6332",
                           email="eleve@example.fr"))
    if good["message"] != "<script>alert('x')</script> réel" or good["code"] != "6332" or good["email"] != "eleve@example.fr":
        bad.append(("cleaning", good))
    if CT.validate(_ok(message="x" * CT.MSG_MAX))["message"] != "x" * CT.MSG_MAX:
        bad.append("the maximum length is refused")
    # page twin: the same closed list and labels, the same bounds
    twin = re.search(r"const CONTACT_TYPES = (\[.*?\]);", c.js, re.S)
    pairs = json.loads(re.sub(r"\s+", " ", twin.group(1))) if twin else []
    if dict(pairs) != CT.TYPES:
        bad.append(("subjects differ", pairs))
    if f"CONTACT_MAX = {CT.MSG_MAX}, CONTACT_MIN = {CT.MSG_MIN}" not in c.js:
        bad.append("bounds differ")
    # the dashboard escapes every field of a message
    lm = fn_src(c.stats, "loadMessages")
    raw = re.findall(r"\$\{x\.(\w+)\}", lm)                                # a field written into the page as it is
    if raw or not all(f"esc(x.{k})" in lm for k in ("jour", "type_label", "message", "email", "code", "page", "id")):
        bad.append(("dashboard escaping", raw))
    return not bad, f"{len(cases)} hostile payloads; problems {bad}"


# ------------------------------------------------------------------ QC5 what is stored
@check("QC5 stored: only the form's fields + id + day; no IP, user agent or pseudonym; a 12-month TTL per message")
def qc5(c: Ctx):
    bad = []
    with tempfile.TemporaryDirectory() as d:
        st = CT.SqliteStore(Path(d) / "c.sqlite")
        CT.reset_store(st)
        try:
            ip, ua = "203.0.113.77", "Mozilla/5.0 RedTeamBrowser/9.9"
            day = date(2026, 11, 13)
            vid = A.visitor_id(ip, ua, day)
            CT.submit(_ok(page="/formation/1", code="1"), {"x-real-ip": ip, "user-agent": ua}, day=day)
            with st._db() as con:
                rows = con.execute("SELECT k, v, exp FROM msg").fetchall()
            msgs = [json.loads(v) for _, v, _ in rows]
            if len(msgs) != 1 or set(msgs[0]) != set(CT.STORED):
                bad.append(("fields", msgs and sorted(msgs[0])))
            for _, v, _ in rows:
                for leak in (ip, ua, "RedTeamBrowser", vid):
                    if leak in v:
                        bad.append(("leak in a message", leak))
            ttl = rows[0][2] - __import__("time").time() if rows else 0
            if not (CT.RETENTION_DAYS - 1) * 86400 < ttl <= CT.RETENTION_DAYS * 86400 + 5:
                bad.append(("ttl days", round(ttl / 86400, 1)))
            if CT.RETENTION_DAYS != RETENTION:
                bad.append(("retention is not 12 months", CT.RETENTION_DAYS))
            dump = st.dump()
            if ip in dump or "RedTeamBrowser" in dump:
                bad.append("ip / user agent in the store")
        finally:
            CT.reset_store(None)
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ QC6 limits and failure
@check("QC6 limits: 5 per visitor-day then 429, other visitors pass, a global cap; a failing store is a 503 'non envoyé'")
def qc6(c: Ctx):
    bad = []
    with client(c.db) as (cl, api):
        hv = {"x-real-ip": "198.51.100.1", "user-agent": "Mozilla/5.0 A"}
        codes = [cl.post("/api/contact", json=_ok(), headers=hv).status_code for _ in range(PER_DAY + 1)]
        if codes != [201] * PER_DAY + [429]:
            bad.append(("per visitor", codes))
        if cl.post("/api/contact", json=_ok(), headers={"x-real-ip": "198.51.100.2", "user-agent": "Mozilla/5.0 B"}).status_code != 201:
            bad.append("another visitor is blocked")
        r = cl.post("/api/contact", json=_ok(type="nope"), headers={"x-real-ip": "198.51.100.3", "user-agent": "C"})
        if r.status_code != 422 or r.json().get("field") != "type":
            bad.append(("422 with its field", r.status_code, r.text[:80]))
        if cl.post("/api/contact", content=b"x" * (CT.MAX_BODY + 10), headers={"content-type": "application/json"}).status_code != 413:
            bad.append("no body limit")
        saved = CT.GLOBAL_DAY
        CT.GLOBAL_DAY = PER_DAY + 3
        try:
            got = [cl.post("/api/contact", json=_ok(), headers={"x-real-ip": f"192.0.2.{i}", "user-agent": "D"}).status_code for i in range(4)]
        finally:
            CT.GLOBAL_DAY = saved
        if 429 not in got:
            bad.append(("no global cap", got))

        class Broken(CT.SqliteStore):
            def put(self, *a, **k):
                raise OSError("down")
        with tempfile.TemporaryDirectory() as d:
            CT.reset_store(Broken(Path(d) / "b.sqlite"))
            r = cl.post("/api/contact", json=_ok(), headers={"x-real-ip": "192.0.2.200", "user-agent": "E"})
            if r.status_code != 503 or "non envoyé" not in r.json().get("detail", ""):
                bad.append(("failing store", r.status_code, r.text[:80]))
    cf = fn_src(c.js, "contactForm")
    if "if (r && r.status === 201 && d.ok) {" not in cf or "Message non envoyé" not in cf:
        bad.append("the page shows success on another answer than a 201")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ QC7 owner endpoints and caching
@check("QC7 owner endpoints need the token, delete works; caching: contact no-store, pages PAGE; robots; sitemap")
def qc7(c: Ctx):
    bad = []
    with client(c.db) as (cl, _):
        auth = {"Authorization": f"Bearer {TOKEN}"}
        cl.post("/api/contact", json=_ok(), headers={"x-real-ip": "203.0.113.9", "user-agent": "F"})
        if cl.get("/api/contact/messages").status_code != 401:
            bad.append("messages without a token")
        if cl.get("/api/contact/messages", headers={"Authorization": "Bearer wrong-token-000000"}).status_code != 401:
            bad.append("messages with a wrong token")
        r = cl.get("/api/contact/messages", headers=auth)
        msgs = r.json().get("messages", []) if r.status_code == 200 else []
        if r.status_code != 200 or len(msgs) != 1 or r.headers.get("cache-control") != "no-store" or "noindex" not in r.headers.get("x-robots-tag", ""):
            bad.append(("read", r.status_code, r.headers.get("cache-control")))
        if msgs:
            mid = msgs[0]["id"]
            if cl.delete(f"/api/contact/messages/{mid}").status_code != 401:
                bad.append("delete without a token")
            if cl.delete(f"/api/contact/messages/{mid}", headers=auth).status_code != 200:
                bad.append("delete")
            if cl.delete(f"/api/contact/messages/{mid}", headers=auth).status_code != 404:
                bad.append("deleted twice")
        if cl.delete("/api/contact/messages/..%2Fx", headers=auth).status_code not in (404, 422):
            bad.append("bad id")
        os.environ["SUPTRACKER_STATS_TOKEN"] = "short"
        if cl.get("/api/contact/messages", headers={"Authorization": "Bearer short"}).status_code != 503:
            bad.append("a short token opens the messages")
        os.environ["SUPTRACKER_STATS_TOKEN"] = TOKEN
        heads = {p: cl.get(p).headers.get("cache-control") for p in ("/api/page/contact", *(f"/{s}" for s in LG.SLUGS))}
        if heads.pop("/api/page/contact") != CACHE.PUBLIC or set(heads.values()) != {CACHE.PAGE}:
            bad.append(("page caching", heads))
        post = cl.post("/api/contact", json=_ok(), headers={"x-real-ip": "203.0.113.10", "user-agent": "G"})
        if post.headers.get("cache-control") != "no-store":
            bad.append(("post caching", post.headers.get("cache-control")))
        if "Disallow: /api/contact" not in cl.get("/robots.txt").text:
            bad.append("robots.txt")
        if c.db:
            sm = cl.get("/sitemap.xml").text
            if not all(f"supcompass.test/{s}</loc>" in sm for s in LG.SLUGS):
                bad.append("sitemap")
    for p in ("/api/contact", "/api/contact/messages", "/api/contact/messages/20261113-abcdefabcdef"):
        if CACHE.policy(p)[0] != CACHE.NO_STORE:
            bad.append(("policy", p))
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ QC8 one tagline
@check("QC8 one tagline everywhere (index.html, the home head, the app's titles, legal.TAGLINE); 'les vrais chiffres' is gone")
def qc8(c: Ctx):
    tl = LG.TAGLINE
    srcs = {"index title": f"<title>SupCompass — {tl}</title>" in c.html, "index brand": f"SupCompass <span>{H.escape(tl, quote=False)}</span>" in c.html
            or f"SupCompass <span>{tl}</span>" in c.html,
            "seo": SEO.TAGLINE == tl, "app": f'const HOME_TITLE = "SupCompass — {tl}";' in c.js}
    gone = {name: "vrais chiffres" not in txt for name, txt in (("index", c.html), ("app", c.js), ("seo home", SEO.home_head("https://x/")),
                                                                 ("legal", "".join(LG.page(s)["html"] for s in LG.SLUGS)))}
    bad = [k for k, v in {**srcs, **gone}.items() if not v]
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ QC9 wiring and wording
@check("QC9 wiring: footer on every page, the five addresses open in the app, closed 'info' route, 'Signaler une erreur'; vouvoiement")
def qc9(c: Ctx):
    bad = []
    with client(c.db) as (cl, _):
        for p in ("/", *(f"/{s}" for s in LG.SLUGS)):
            page = cl.get(p).text
            if not all(f'href="/{s}"' in page for s in LG.SLUGS) or "<!--legal-->" in page:
                bad.append(("footer", p))
            if p != "/" and page.count("<h1") != 1:
                bad.append(("one h1", p))
    pr = fn_src(c.js, "pathRoute")
    for s in LG.SLUGS:
        if s not in pr:
            bad.append(("pathRoute", s))
    if json.loads(re.search(r"const INFO_SLUGS = (\[.*?\]);", c.js).group(1)) != list(LG.SLUGS):
        bad.append("INFO_SLUGS")
    if "info" not in A.ROUTES or 'info: "info"' not in c.js or 'if (a === "info") return await viewInfo(' not in c.js:
        bad.append("route")
    if "${feedbackBox(\"fiche\")}${reportLink(r.cod_aff_form)}" not in c.js or "#/info/contact/${esc(cod)}" not in c.js:
        bad.append("Signaler une erreur on the formation page")
    words = []
    for s in LG.SLUGS:
        words += [(s, m) for m in TU.findall(text_of(LG.page(s)["html"]))]
    words += [("form", m) for m in TU.findall(text_of(fn_src(c.js, "contactForm")))]
    if words:
        bad.append(("tutoiement", words[:5]))
    if "Sprint Q1" not in c.readme or "Trust and compliance (sprint Q1" not in c.claude:
        bad.append("docs")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ QC10 browser
@check("QC10 browser: five pages and the form, phone and wide dark: one h1, 320 px, axe, sent / 503 said, only the tile host")
def qc10(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    import shutil
    import socket
    import subprocess
    import time
    node = shutil.which("node")
    if not node:
        return True, "node not installed"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_STATS_TOKEN": TOKEN}
    if c.db:
        env["SUPTRACKER_DB"] = str(c.db)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        cod = "1"
        if c.db:
            import duckdb
            with duckdb.connect(str(c.db), read_only=True) as con:
                cod = con.execute("SELECT cod_aff_form FROM core.formation_year ORDER BY session DESC, cod_aff_form LIMIT 1").fetchone()[0]
        script = Path(tmp) / "qc10.js"
        from redteam_a11y import axe_path                  # the same axe-core the R8 red team uses (AXE_CORE_JS, npm -g, node_modules)
        script.write_text(BROWSER_JS.replace("__AXE__", json.dumps(axe_path())).replace("__PORT__", str(port)).replace("__COD__", str(cod))
                          .replace("__SLUGS__", json.dumps(list(LG.SLUGS))).replace("__TILES__", LG.TILES["host"]))
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=600,
                           env={**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", "")})
        out = (r.stdout or "").strip().splitlines()
        res = json.loads(out[-1]) if out and out[-1].startswith("{") else {"problems": [r.stderr[-400:]]}
    finally:
        srv.terminate()
    return not res["problems"], f"third-party hosts {res.get('hosts')}; axe {res.get('axe')}; problems {res['problems'][:5]}"


BROWSER_JS = r"""
const { chromium, devices } = require('playwright');
const AXE_PATH = __AXE__; const AXE = AXE_PATH ? require('fs').readFileSync(AXE_PATH, 'utf8') : null;
(async () => {
  const b = await chromium.launch(); const problems = []; const hosts = new Set();
  const base = 'http://127.0.0.1:__PORT__', slugs = __SLUGS__;
  for (const [name, opts] of [['phone', { ...devices['Pixel 5'] }], ['wide-dark', { viewport: { width: 1280, height: 900 }, colorScheme: 'dark' }], ['w320', { viewport: { width: 320, height: 640 } }]]) {
    const ctx = await b.newContext(opts); const p = await ctx.newPage();
    p.on('pageerror', (e) => problems.push(`${name} js ${e}`));
    p.on('request', (q) => { const h = new URL(q.url()).hostname; if (h !== '127.0.0.1') hosts.add(h); });
    for (const s of slugs) {
      await p.goto(`${base}/${s}`); await p.waitForSelector('#view h1'); await p.waitForTimeout(300);
      const n = await p.locator('h1').count(); if (n !== 1) problems.push(`${name} ${s} h1 ${n}`);
      const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth); if (over > 0) problems.push(`${name} ${s} overflow ${over}`);
      if (AXE && name !== 'w320') {
        await p.addScriptTag({ content: AXE });
        const v = await p.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })).violations.map((x) => x.id));
        if (v.length) problems.push(`${name} ${s} axe ${v.join(',')}`);
      }
    }
    if (name === 'w320') { await ctx.close(); continue; }
    await p.goto(`${base}/contact`); await p.waitForSelector('#cform');
    await p.fill('#cmsg', 'Le taux affiché pour cette formation semble faux.'); await p.click('#cform button[type=submit]');
    await p.waitForFunction(() => /envoyé/.test(document.getElementById('cform-msg').textContent), null, { timeout: 10000 }).catch(() => {});
    const ok = await p.textContent('#cform-msg'); if (!/^Message envoyé/.test(ok)) problems.push(`${name} send: ${ok}`);
    await p.route('**/api/contact', (rt) => rt.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Message non envoyé : le service est momentanément indisponible.' }) }));
    await p.fill('#cmsg', 'Deuxième message pour tester une panne du service.'); await p.click('#cform button[type=submit]');
    await p.waitForTimeout(500);
    const ko = await p.textContent('#cform-msg'); const dis = await p.isDisabled('#cform button[type=submit]');
    if (!/non envoyé/.test(ko) || dis || /^Message envoyé/.test(ko)) problems.push(`${name} 503: ${ko} disabled ${dis}`);
    await p.unroute('**/api/contact');
    await p.fill('#cmsg', ''); await p.click('#cform button[type=submit]');
    if (await p.getAttribute('#cmsg', 'aria-invalid') !== 'true') problems.push(`${name} empty message not marked invalid`);
    for (const u of ['/', '/#/f/__COD__', '/#/carte']) { await p.goto(base + u); await p.waitForTimeout(2500); }
    await p.goto(`${base}/#/f/__COD__`); await p.waitForSelector('.report-link a', { timeout: 20000 }).catch(() => problems.push(`${name} no report link`));
    await ctx.close();
  }
  const third = [...hosts].filter((h) => h !== '__TILES__');
  if (third.length) problems.push(`unexpected third-party hosts ${third.join(',')}`);
  console.log(JSON.stringify({ problems, hosts: [...hosts], axe: !!AXE }));
  await b.close();
})();
"""


# ------------------------------------------------------------------ QC11 mutation test
def mutants():
    """(name, apply, restore, checks expected to fail). Python mutants patch modules; page mutants patch the Ctx's source."""
    import suptracker.api as api
    out = []

    def py(name, target, attr, value, checks):
        def apply(_c):
            py.saved = getattr(target, attr)
            setattr(target, attr, value(py.saved) if callable(value) and not isinstance(value, type) else value)

        def restore(_c):
            setattr(target, attr, py.saved)
        out.append((name, apply, restore, checks))

    py("host without its address", LG, "HOST", {**LG.HOST, "address": "États-Unis"}, {"QC1"})
    py("a source forgotten in the legal notice", LG, "_sources", lambda f: (lambda: f().replace("<li>", "<li hidden>", 1).split("</li>", 1)[1]), {"QC1"})
    py("publisher missing", LG, "PUBLISHER", "l'éditeur", {"QC1"})
    py("the map's tile host not named", LG, "TILES", {**LG.TILES, "name": "un prestataire"}, {"QC2"})
    py("the analytics store not named", LG, "STORE", {**LG.STORE, "name": "un prestataire"}, {"QC2"})
    py("conformity claimed", LG, "accessibilite", lambda f: (lambda: f().replace("non conforme", "partiellement conforme")), {"QC3"})
    py("no Défenseur des droits", LG, "accessibilite", lambda f: (lambda: re.sub(r"Défenseur des\s+droits", "médiateur", f())), {"QC3"})
    py("open list of subjects", CT, "TYPES", {**CT.TYPES, "spam": "Spam"}, {"QC4"})
    def no_honeypot(f):
        def v(p):
            if isinstance(p, dict):
                p = {k: x for k, x in p.items() if k != "site"}
            return f(p)
        return v
    py("hidden field ignored", CT, "validate", no_honeypot, {"QC4"})

    def leak_ip(f):
        def s(payload, headers, day=None):
            st = CT.store()
            put = st.put
            st.put = lambda k, v, ttl: put(k, v[:-1] + f', "ip": "{A.client_ip(headers)}"}}', ttl)
            try:
                return f(payload, headers, day)
            finally:
                st.put = put
        return s
    py("the IP stored with a message", CT, "submit", leak_ip, {"QC5"})
    py("a two-year retention", CT, "RETENTION_DAYS", 730, {"QC5"})
    py("no limit per visitor", CT, "PER_VISITOR_DAY", 10 ** 6, {"QC6"})

    def fail_open(f):
        def s(payload, headers, day=None):
            try:
                return f(payload, headers, day)
            except (CT.Invalid, CT.Limited):
                raise
            except Exception:  # noqa: BLE001
                return "00000000-000000000000"
        return s
    py("a failing store answered as sent", CT, "submit", fail_open, {"QC6"})
    py("messages readable without the token", api, "_owner", lambda f: (lambda request: None), {"QC7"})
    py("the contact form shared-cached", CACHE, "_COMPILED",
       lambda f: [(rx, CACHE.PUBLIC if rx.pattern == "^/api/contact$" else pol, why) for rx, pol, why in f], {"QC7"})
    py("the old tagline", SEO, "TAGLINE", "Parcoursup 2022–2025, les vrais chiffres", {"QC8"})

    def page_mut(name, attr, old, new, checks):
        def apply(c):
            src = getattr(c, attr)
            if old not in src:
                raise AssertionError(f"anchor not found: {old[:50]}")
            setattr(c, attr, src.replace(old, new, 1))

        def restore(c):
            c.reload()
        out.append((name, apply, restore, checks))

    page_mut("a message shown unescaped", "stats", "${esc(x.message)}", "${x.message}", {"QC4"})
    page_mut("the page's subjects differ", "js", '["autre", "Autre chose"]', '["autre", "Autre"]', {"QC4"})
    page_mut("success shown on any answer", "js", "if (r && r.status === 201 && d.ok) {", "if (r) {", {"QC6"})
    page_mut("no report link on the formation page", "js", '${feedbackBox("fiche")}${reportLink(r.cod_aff_form)}', '${feedbackBox("fiche")}', {"QC9"})
    page_mut("an address that does not open in the app", "js", "(a-propos|contact|mentions-legales|confidentialite|accessibilite)",
             "(a-propos|contact|mentions-legales|confidentialite)", {"QC9"})
    page_mut("tutoiement in the form", "js", "Votre message <span", "Ton message <span", {"QC9"})
    page_mut("the app's title keeps the old tagline", "js", "const HOME_TITLE = \"SupCompass — ", "const HOME_TITLE = \"SupCompass — les vrais chiffres ", {"QC8"})
    return out


@check("QC11 mutation test: each seeded defect is caught by its check")
def qc11(c: Ctx):
    missed, n = [], 0
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    for name, apply, restore, expect in mutants():
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


def run(db: Path | None = None, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
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
