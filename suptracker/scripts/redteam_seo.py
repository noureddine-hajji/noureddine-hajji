"""Red team of sprint 17: SupCompass can be found by a search engine (and is called SupCompass).

    python scripts/redteam_seo.py [--db data/suptracker.duckdb] [--real] [--browser]

  G1 sitemap: valid XML, absolute https URLs, under the 50 000-URL limit, exactly the latest campaign's formations and every
     job (re-derived from the warehouse), no duplicate, nothing else; robots.txt points to it, leaves the data the pages render
     from open (a crawler that runs the app must load it: Codex) and keeps search, vœux and stats off
  G2 formation page: 200, the app shell, one <title>, a meta description, a canonical equal to its own address, Open Graph,
     JSON-LD that parses; the figures in title, description and body are the PUBLISHED ones (re-read from the warehouse,
     never recomputed) and agree with /api/formation; the caveat "pas des chances d'admission"; no probability wording
  G3 job page: 200, title, description, canonical, JSON-LD; every diploma of /api/metier listed; formation links point to
     real formation pages; the "pas une promesse d'emploi" caveat and the ODbL credit
  G4 hostile strings (an establishment or job name with markup, quotes, "</script>"): escaped in the title, the meta
     tags, the body and the JSON-LD; nothing can close a tag or the script
  G5 unknown or malformed addresses (unknown code, letters, path tricks, unknown job): 404 HTML with noindex, never cached
  G6 indexing rules: an older formation (absent from the latest campaign) is served with noindex and left out of the
     sitemap; a preview deployment is never indexed (every page noindex, robots "Disallow: /", empty sitemap); the
     canonical origin is the production domain Vercel declares
  G7 the app boots on these addresses: the router maps /formation/<code> and /metier/<id> to the same views as their hash
     routes (run with Node), returns to "/#/…" when the visitor navigates, and a failed data load keeps the server summary
     (the error shows above it, never in its place: Codex)
  G8 name: "SupCompass" in the shell, the API title and the footer, with the independence notice (not affiliated with
     Parcoursup or the ministry); "SupTracker" nowhere a visitor can read
  G9 cache: every new route has a policy; pages are kept by the CDN only as 200s and always revalidated by browsers
  G10 mutation test (each mutant must fail a check; a crash counts as caught only through a failing check)
  --browser: the pages on a phone (light and dark), with and without JavaScript: 0 JS errors, no horizontal scroll, the
     app's summary after boot, the server summary without JavaScript
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import cache as CACHE  # noqa: E402
from suptracker import seo as SEO  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
API = None           # the API module the checks call (the mutation test swaps in a mutated copy, in memory)
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
HOSTILE = '"><script>alert(1)</script><b>X</b> & </script>'


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Head(HTMLParser):
    """An independent reading of what a crawler sees: head tags, JSON-LD blocks and the text of <main id="view">."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles, self.meta, self.links, self.ld, self.view_text = [], {}, {}, [], []
        self._in, self._ld, self._depth_view = None, False, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in = "title"
            self.titles.append("")
        elif tag == "meta" and (a.get("name") or a.get("property")):
            self.meta[a.get("name") or a.get("property")] = a.get("content")
        elif tag == "link" and a.get("rel"):
            self.links[a["rel"]] = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._ld = True
            self.ld.append("")
        if tag == "main" and a.get("id") == "view":
            self._depth_view = 1
        elif self._depth_view and tag not in ("br", "img", "input", "meta", "link"):
            self._depth_view += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in = None
        if tag == "script":
            self._ld = False
        if self._depth_view and tag not in ("br", "img", "input", "meta", "link"):
            self._depth_view -= 1

    def handle_data(self, data):
        if self._in == "title":
            self.titles[-1] += data
        if self._ld:
            self.ld[-1] += data
        if self._depth_view:
            self.view_text.append(data)

    @property
    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.view_text)).strip()


def parse(html: str) -> Head:
    h = Head()
    h.feed(html)
    return h


@contextmanager
def client(db: Path, env: dict | None = None):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    api = API or sys.modules.get("suptracker.api") or __import__("suptracker.api", fromlist=["app"])
    saved_env = {k: os.environ.get(k) for k in ("SUPTRACKER_DB", "VERCEL_ENV", "VERCEL_PROJECT_PRODUCTION_URL")}
    os.environ["SUPTRACKER_DB"] = str(db)
    for k in ("VERCEL_ENV", "VERCEL_PROJECT_PRODUCTION_URL"):
        os.environ.pop(k, None)
    os.environ.update(env or {})
    api._con.cache_clear()
    saved = A.record
    A.record = lambda *a, **k: "ok"
    try:
        yield TestClient(api.app, base_url="https://supcompass.test"), api
    finally:
        A.record = saved
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        api._con.cache_clear()


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        con = duckdb.connect(str(db), read_only=True)
        self.last = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.latest = sorted(c for (c,) in con.execute(
            "SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE session = ?", [self.last]).fetchall())
        self.older = [c for (c,) in con.execute(
            """SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE cod_aff_form NOT IN
               (SELECT cod_aff_form FROM core.formation_year WHERE session = ?) ORDER BY 1 LIMIT 3""", [self.last]).fetchall()]
        has_jobs = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_name='onisep_metier'").fetchone()[0]
        self.jobs = sorted(m for (m,) in con.execute("SELECT met_id FROM core.onisep_metier").fetchall()) if has_jobs else []
        # a spread of formations: first, last, one with Onisep jobs, and (real data) more
        n = 12 if real else 4
        step = max(1, len(self.latest) // n)
        self.sample = self.latest[::step][:n]
        if has_jobs:
            j = con.execute("""SELECT l.cod_aff_form FROM core.onisep_link l WHERE l.session = ? AND l.for_id IS NOT NULL
                               ORDER BY 1 LIMIT 1""", [self.last]).fetchone() if con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_name='onisep_link'").fetchone()[0] else None
            if j and j[0] not in self.sample:
                self.sample.append(j[0])
        self.job_sample = (self.jobs[:: max(1, len(self.jobs) // 6)][:6]) if self.jobs else []
        # a job where one formation prepares several of its diplomas (Codex: counted once, not once per diploma)
        dup = con.execute("""SELECT fm.met_id FROM core.onisep_formation_metier fm JOIN core.onisep_link l USING (for_id)
                             WHERE l.session = ? GROUP BY fm.met_id, l.cod_aff_form HAVING count(DISTINCT fm.for_id) > 1
                             ORDER BY 1 LIMIT 1""", [self.last]).fetchone() if has_jobs and con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_name='onisep_link'").fetchone()[0] else None
        if dup and dup[0] not in self.job_sample:
            self.job_sample.append(dup[0])
        self.published = {c: dict(zip(("taux", "acc", "capa", "etab", "ville", "lib"), r)) for c, *r in con.execute(
            """SELECT cod_aff_form, taux_acces_ens, acc_tot, capa_fin, g_ea_lib_vx, ville_etab, lib_for_voe_ins
               FROM core.formation_year WHERE session = ?""", [self.last]).fetchall() if c in self.sample}
        con.close()
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()


def fr_num(x) -> str:
    """Independent French number formatting (the app's toLocaleString for counts)."""
    return f"{int(x):,}".replace(",", " ")


def fr_pct(x) -> str:
    return f"{fr_num(x)} %" if float(x).is_integer() else f"{x:.1f}".replace(".", ",") + " %"


# ---------------------------------------------------------------- checks
def sitemap_ok(xml_text: str, robots: str, base: str, latest: list[str], jobs: list[str]) -> tuple[bool, str]:
    try:
        root = ET.fromstring(xml_text.encode())
    except ET.ParseError as e:
        return False, f"sitemap is not XML: {e}"
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = [u.findtext(f"{ns}loc") for u in root.findall(f"{ns}url")]
    want = {f"{base}/formation/{c}" for c in latest} | {f"{base}/metier/{m}" for m in jobs}
    got = set(locs)
    ok = (root.tag == f"{ns}urlset" and len(locs) == len(got) and got == want and len(locs) <= 50000
          and all(u.startswith("https://") for u in locs))
    rules = [ln.split(":", 1)[1].strip() for ln in robots.splitlines() if ln.lower().startswith("disallow:")]
    blocked = lambda path: any(r and path.startswith(r) for r in rules)  # noqa: E731  (robots prefix rule)
    # what the pages render from must stay fetchable by a crawler that runs the app (Codex finding)
    render_ok = not any(blocked(x) for x in ("/api/meta", "/api/formation/1", "/api/metier/MET.1", "/api/journey/vocab",
                                             "/api/planb/1", "/static/app.js", "/formation/1", "/metier/MET.1"))
    private_off = all(blocked(x) for x in ("/api/search", "/api/voeux", "/api/stats"))
    rob = render_ok and private_off and f"Sitemap: {base}/sitemap.xml" in robots
    return ok and rob, (f"{len(locs)} URLs (want {len(want)}); missing {sorted(want - got)[:2]}; extra {sorted(got - want)[:2]}; "
                        f"duplicates {len(locs) - len(got)}; robots: render data allowed {render_ok}, private routes off {private_off}")


@check("G1 sitemap = the latest campaign's formations + every job, valid, absolute, no duplicate; robots points to it, leaves the render data open, keeps private routes off")
def g1(c: Ctx):
    with client(c.db) as (cl, _):
        sm, rb = cl.get("/sitemap.xml"), cl.get("/robots.txt")
    if sm.status_code != 200 or rb.status_code != 200:
        return False, f"status {sm.status_code} / {rb.status_code}"
    return sitemap_ok(sm.text, rb.text, "https://supcompass.test", c.latest, c.jobs)


def formation_ok(html: str, url: str, pub: dict, api_rec: dict, session: int) -> tuple[bool, str]:
    h = parse(html)
    title = h.titles[0] if len(h.titles) == 1 else ""
    desc = h.meta.get("description") or ""
    try:
        ld = [json.loads(x) for x in h.ld]
    except json.JSONDecodeError:
        ld = None
    rate = fr_pct(pub["taux"]) if pub["taux"] is not None else None
    figures = (rate is None or (rate in desc and rate in h.text)) and fr_num(pub["acc"]) in h.text and \
        (pub["capa"] is None or fr_num(pub["capa"]) in desc)
    same = (api_rec["taux_acces_ens"] == pub["taux"] and api_rec["acc_tot"] == pub["acc"] and api_rec["capa_fin"] == pub["capa"])
    names = pub["etab"] in title and pub["ville"] in title and str(session) in title and title.endswith("| SupCompass")
    head = (h.links.get("canonical") == url and h.meta.get("og:url") == url and h.meta.get("robots") == "index, follow"
            and bool(desc) and 50 <= len(desc) <= 320)
    ld_ok = bool(ld) and ld[0].get("@type") == "EducationalOccupationalProgram" and ld[0].get("url") == url \
        and ld[0]["provider"]["name"] == pub["etab"]
    words = "pas des chances d'admission" in desc and "pas des chances d'admission" in h.text and not CHANCE.search(h.text + desc)
    shell = '<script src="/static/app.js?v=' in html and '<main id="view" aria-live="polite"><article class="seo" data-seo="formation">' in html
    ok = figures and same and names and head and ld_ok and words and shell
    return ok, (f"published figures shown {figures}; equal to /api/formation {same}; title {names}; head {head}; JSON-LD {ld_ok}; "
                f"caveat {words}; app shell {shell}")


@check("G2 formation pages: head tags, canonical, JSON-LD, PUBLISHED figures (equal to /api/formation), caveat, app shell")
def g2(c: Ctx):
    bad = []
    with client(c.db) as (cl, _):
        for cod in c.sample:
            url = f"https://supcompass.test/formation/{cod}"
            r = cl.get(f"/formation/{cod}")
            if r.status_code != 200:
                bad.append((cod, r.status_code))
                continue
            ok, d = formation_ok(r.text, url, c.published[cod], cl.get(f"/api/formation/{cod}").json()["record"], c.last)
            if not ok:
                bad.append((cod, d))
    return not bad, f"{len(c.sample)} formations; problems {bad[:2]}"


def metier_ok(html: str, url: str, api_d: dict) -> tuple[bool, str]:
    h = parse(html)
    title = h.titles[0] if len(h.titles) == 1 else ""
    try:
        ld = [json.loads(x) for x in h.ld]
    except json.JSONDecodeError:
        ld = None
    dips = all(re.sub(r"\s+", " ", d["libelle"]).strip() in h.text for d in api_d["diplomes"])   # Onisep titles may hold double spaces
    links = re.findall(r'href="/formation/(\d+)"', html)
    known = {f["cod_aff_form"] for d in api_d["diplomes"] for f in (d.get("formations") or [])}
    links_ok = set(links) <= known
    head = (api_d["nom"] in title and title.endswith("| SupCompass") and h.links.get("canonical") == url
            and h.meta.get("robots") == "index, follow" and bool(h.meta.get("description")))
    ld_ok = bool(ld) and ld[0].get("@type") == "Occupation" and ld[0].get("name") == api_d["nom"]
    distinct = len(known)                                   # each formation once, whatever the number of its diplomas
    m = re.search(r"([\d\u202f]+) formation\(s\) Parcoursup", h.meta.get("description") or "")
    count_ok = bool(m) and int(m.group(1).replace("\u202f", "")) == distinct
    words = "pas une promesse d’emploi" in h.text and "Onisep, Idéo (licence ODbL)" in h.text and not CHANCE.search(h.text)
    ok = dips and links_ok and head and ld_ok and words and count_ok
    return ok, (f"every diploma listed {dips}; links to real formations {links_ok} ({len(links)}); head {head}; JSON-LD {ld_ok}; "
                f"wording {words}; distinct formations in the description {count_ok} ({m and m.group(1)} vs {distinct})")


@check("G3 job pages: head tags, canonical, JSON-LD, every diploma of /api/metier, formation links real, caveat and credit")
def g3(c: Ctx):
    if not c.jobs:
        return True, "no Onisep jobs in this warehouse"
    bad = []
    with client(c.db) as (cl, _):
        for mid in c.job_sample:
            r = cl.get(f"/metier/{mid}")
            ok, d = metier_ok(r.text, f"https://supcompass.test/metier/{mid}", cl.get(f"/api/metier/{mid}").json()) \
                if r.status_code == 200 else (False, r.status_code)
            if not ok:
                bad.append((mid, d))
    return not bad, f"{len(c.job_sample)} jobs; problems {bad[:2]}"


def hostile_ok() -> tuple[bool, str]:
    """The render functions on hostile strings: nothing may open a tag or close the JSON-LD script."""
    r = {"session": 2025, "cod_aff_form": "1", "g_ea_lib_vx": HOSTILE, "lib_for_voe_ins": HOSTILE, "fil_lib_voe_acc": HOSTILE,
         "lib_comp_voe_ins": HOSTILE, "fili": "BTS", "ville_etab": HOSTILE, "acad_mies": HOSTILE, "contrat_etab": HOSTILE,
         "select_form": HOSTILE, "taux_acces_ens": 50.0, "acc_tot": 10, "capa_fin": 12, "indexable": True,
         "metiers": [{"id": "MET.1", "nom": HOSTILE}], "related": [{"cod": "2", "etab": HOSTILE, "ville": HOSTILE, "label": HOSTILE}]}
    d = {"id": "MET.1", "nom": HOSTILE, "niveau_acces_min": HOSTILE, "diplomes": [{"libelle": HOSTILE, "niveau": HOSTILE, "parcoursup": True,
         "formations": [{"cod_aff_form": "1", "etablissement": HOSTILE, "ville": HOSTILE}]}]}
    url = "https://x.test/formation/1"
    shell = (STATIC / "index.html").read_text()
    pages = [SEO.page(shell, SEO.head_tags(SEO.formation_title(r), SEO.formation_description(r), url, True, SEO.formation_ld(r, url)),
                      SEO.formation_body(r)),
             SEO.page(shell, SEO.head_tags(SEO.metier_title(d), SEO.metier_description(d), url, True, SEO.metier_ld(d, url)),
                      SEO.metier_body(d))]
    bad = []
    for html in pages:
        if "<script>alert" in html or "<b>X</b>" in html:
            bad.append("raw markup")
        for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            try:
                if json.loads(block).get("name") != HOSTILE and HOSTILE not in json.dumps(json.loads(block), ensure_ascii=False):
                    bad.append("JSON-LD lost the value")
            except json.JSONDecodeError:
                bad.append("JSON-LD broken")
        h = parse(html)
        if len(h.titles) != 1 or HOSTILE not in h.titles[0]:
            bad.append(f"title {h.titles[:1]}")
        if HOSTILE not in (h.meta.get("description") or ""):
            bad.append("description")
        if html.count('<script type="application/ld+json">') != 1:
            bad.append("JSON-LD count")
    return not bad, f"problems {bad[:4]}"


@check("G4 hostile names are escaped in the title, meta tags, body and JSON-LD (nothing opens a tag or closes the script)")
def g4(c: Ctx):
    return hostile_ok()


@check("G5 unknown or malformed addresses: 404 HTML page, noindex, never cached")
def g5(c: Ctx):
    bad = []
    with client(c.db) as (cl, _):
        for u in ("/formation/999999999", "/formation/abc", "/formation/1%20OR%201=1", "/formation/..%2f..%2fetc", "/metier/MET.0",
                  "/metier/abc", "/metier/MET.1%3Cscript%3E"):
            r = cl.get(u)
            h = parse(r.text) if r.headers.get("content-type", "").startswith("text/html") else None
            if r.status_code != 404 or h is None or h.meta.get("robots") != "noindex, follow" or r.headers.get("cache-control") != "no-store" \
                    or "<script>" in r.text.split("</head>")[-1].replace('<script src="/static/', ""):
                bad.append((u, r.status_code, r.headers.get("cache-control"), h and h.meta.get("robots")))
    return not bad, f"bad answers {bad[:3]}"


@check("G6 indexing rules: older formations noindex and out of the sitemap; previews never indexed; production canonical")
def g6(c: Ctx):
    out = []
    with client(c.db) as (cl, _):
        for cod in c.older:
            r = cl.get(f"/formation/{cod}")
            if r.status_code != 200 or parse(r.text).meta.get("robots") != "noindex, follow":
                out.append(("older indexable", cod))
    with client(c.db, {"VERCEL_ENV": "preview", "VERCEL_PROJECT_PRODUCTION_URL": "supcompass.fr"}) as (cl, _):
        r = cl.get(f"/formation/{c.latest[0]}")
        h = parse(r.text)
        if h.meta.get("robots") != "noindex, follow":
            out.append("preview page indexable")
        if h.links.get("canonical") != f"https://supcompass.fr/formation/{c.latest[0]}":
            out.append(("canonical", h.links.get("canonical")))
        if cl.get("/robots.txt").text != "User-agent: *\nDisallow: /\n":
            out.append("preview robots")
        if "<url>" in cl.get("/sitemap.xml").text:
            out.append("preview sitemap not empty")
        if parse(cl.get("/").text).meta.get("robots") != "noindex, follow":
            out.append("preview home indexable")
    with client(c.db, {"VERCEL_ENV": "production", "VERCEL_PROJECT_PRODUCTION_URL": "supcompass.fr"}) as (cl, _):
        h = parse(cl.get(f"/formation/{c.latest[0]}", headers={"host": "evil.example"}).text)
        if h.links.get("canonical") != f"https://supcompass.fr/formation/{c.latest[0]}" or h.meta.get("robots") != "index, follow":
            out.append(("production canonical / robots", h.links.get("canonical"), h.meta.get("robots")))
    return not out, f"{len(c.older)} older formations checked; problems {out[:3]}"


ROUTER = r"""
const out = {};
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
"""


def router_ok(js: str) -> tuple[bool, str]:
    m = re.search(r"function pathRoute\(pathname, hash\) \{.*?\n\}", js, re.S)
    if not m:
        return False, "pathRoute missing"
    node = shutil.which("node")
    if not node:
        return True, "node not installed"
    prog = m.group(0) + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([p, h]) => pathRoute(p, h))));"""
    cases = [["/formation/2882", ""], ["/formation/2882/", ""], ["/metier/MET.798", ""], ["/formation/2882", "#/parcours"],
             ["/formation/abc", ""], ["/formation/12345678901", ""], ["/metier/MET.1<x>", ""], ["/", ""], ["/formation/2882", "#"],
             ["/x/formation/2882", ""]]
    r = subprocess.run([node, "-e", prog], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    if r.returncode:
        return False, r.stderr[-300:]
    got = json.loads(r.stdout)
    want = ["/f/2882", "/f/2882", "/metiers/MET.798", None, None, None, None, None, "/f/2882", None]
    rt = js[js.index("async function route()"):js.index("document.getElementById(\"search\").onsubmit")]
    wired = ("(pathRoute(location.pathname, location.hash) || location.hash.slice(1) || \"/\")" in rt
             and 'history.replaceState(null, "", "/" + location.hash)' in rt and "document.title = " in rt)
    boot = js[js.index("window.addEventListener(\"hashchange\", route);"):]
    se = re.search(r"function showError\(e\) \{.*?\n\}", js, re.S)
    keep = (bool(se) and '$view.querySelector("[data-seo]")' in se.group(0) and 'insertAdjacentHTML("beforebegin"' in se.group(0)
            and "showError(e);" in rt and 'catch (e) { showError(e); return; }' in boot and "$view.innerHTML = `<div class=\"warn\">" not in rt + boot)
    ok = got == want and wired and keep
    return ok, (f"path → view {got == want} ({[g for g, w in zip(got, want) if g != w][:3]}); router wired, URL cleaned, title reset {wired}; "
                f"a failed load keeps the server summary {keep}")


@check("G7 the app boots on /formation/<code> and /metier/<id> (same views as the hash routes), then returns to '/#/…'")
def g7(c: Ctx):
    return router_ok(c.js)


def name_ok(html: str, js: str, api_title: str) -> tuple[bool, str]:
    files = {p.name: p.read_text() for p in [STATIC / "index.html", STATIC / "app.js", STATIC / "stats.js"]}
    files["index.html"] = html
    files["app.js"] = js
    py_visible = [ROOT / "suptracker" / f for f in ("api.py", "glossary.py", "search.py", "seo.py")]
    # the Vercel setting names (SUPTRACKER_…) are technical and kept on purpose: the owner set them on Vercel
    old = [n for n, t in files.items() if re.search(r"(?i)sup\s*tracker", re.sub(r"SUPTRACKER_[A-Z_]+", "", t))] + \
          [p.name for p in py_visible if re.search(r"SupTracker", p.read_text())]
    brand = '<a class="brand" href="/">SupCompass <span>' in html and "<title>SupCompass" in html and api_title == "SupCompass"
    notice = "SupCompass est un site indépendant, non affilié à Parcoursup ni au ministère" in html
    ok = not old and brand and notice
    return ok, f"old name in {old}; brand {brand}; independence notice {notice}"


@check("G8 the site is called SupCompass (shell, API, footer with the independence notice); 'SupTracker' nowhere a visitor reads")
def g8(c: Ctx):
    from suptracker import api
    return name_ok(c.html, c.js, (API or api).app.title)


@check("G9 cache: every new route has a policy; pages kept by the CDN only as 200 and always revalidated by browsers")
def g9(c: Ctx):
    paths = ["/formation/1", "/metier/MET.1", "/sitemap.xml", "/robots.txt"]
    pol = {p: CACHE.policy(p) for p in paths}
    page = [CACHE.header("GET", p, None, 200, "v") for p in paths]
    err = [CACHE.header("GET", p, None, 404, "v") for p in paths]
    ok = all(pol.values()) and all(h and "max-age=0" in h and "must-revalidate" in h and "s-maxage=" in h for h in page) \
        and all(e == "no-store" for e in err)
    with client(c.db) as (cl, _):
        live = cl.get(f"/formation/{c.latest[0]}").headers.get("cache-control")
        head = cl.head(f"/formation/{c.latest[0]}").status_code
    ok = ok and live == CACHE.PAGE and head == 200
    return ok, f"policies {all(pol.values())}; 200 headers {page[0]}; errors {set(err)}; live {live}; HEAD {head}"


# ---------------------------------------------------------------- mutation test
SEO_PY = ROOT / "suptracker" / "seo.py"
MUTANTS = [
    ("title unescaped", "out = [f\"<title>{esc(title)}</title>\",", "out = [f\"<title>{title}</title>\","),
    ("description unescaped", "f'<meta name=\"description\" content=\"{esc(description)}\">',", "f'<meta name=\"description\" content=\"{description}\">',"),
    ("JSON-LD can close the script", 'return s.replace("<", "\\\\u003c").replace(">", "\\\\u003e").replace("&", "\\\\u0026")', "return s"),
    ("body name unescaped", "<div class=\"card\"><h1>{esc(r['g_ea_lib_vx'])}</h1>", "<div class=\"card\"><h1>{r['g_ea_lib_vx']}</h1>"),
    ("rate recomputed from admits", "{tile(f\"Taux d'accès {esc(r['session'])}\", esc(pct(r['taux_acces_ens']))",
     "{tile(f\"Taux d'accès {esc(r['session'])}\", esc(pct(100 * r['acc_tot'] / max(1, r['capa_fin'] or 1)))"),
    ("caveat dropped", "Ce ne sont pas des chances d'admission. \"", "\""),
    ("description too long to show the figures", "    return s if len(s) <= 300 else s[:299].rstrip() + \"…\"", "    return s + \" \" + s"),
    ("older formations indexable", 'rec["indexable"] = rec["session"] == last', 'rec["indexable"] = True'),
    ("preview indexed", 'robots = "index, follow" if indexable and not is_preview() else "noindex, follow"',
     'robots = "index, follow" if indexable else "noindex, follow"'),
    ("preview robots open", '    if is_preview():\n        return "User-agent: *\\nDisallow: /\\n"\n', ""),
    ("sitemap lists every campaign", '"SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY 1", [last]',
     '"SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE session <= ? ORDER BY 1", [last]'),
    ("jobs left out of the sitemap", 'paths += [f"/metier/{m}"', 'paths += [f"/metiers/{m}"'),
    ("formations counted once per diploma", '    n_f = d.get("n_formations")\n', '    n_f = sum(len(x.get("formations") or []) for x in d.get("diplomes") or [])\n'),
    ("canonical from the visitor's host", '    prod = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")', "    prod = None"),
    ("robots blocks the data the pages render from", 'ROBOTS_OFF = ("/api/search",', 'ROBOTS_OFF = ("/api/", "/api/search",'),
    ("robots lets crawlers into search", 'ROBOTS_OFF = ("/api/search", ', 'ROBOTS_OFF = ('),
]
API_MUTANTS = [
    ("unknown code answers 200", '        return _html_404(request, "Cette formation n\'existe pas dans les données Parcoursup 2022–2025.")',
     '        return Response("introuvable", media_type="text/html")'),
    ("HEAD refused", '@app.api_route("/formation/{cod}", methods=["GET", "HEAD"], include_in_schema=False)', '@app.get("/formation/{cod}")'),
]
JS_MUTANTS = [
    ("router ignores the path", "(pathRoute(location.pathname, location.hash) || location.hash.slice(1) || \"/\")", "(location.hash.slice(1) || \"/\")"),
    ("job path not mapped", "if (m) return `/metiers/${m[1]}`;", "if (m) return null;"),
    ("a failed data load erases the server summary", "  } catch (e) {\n    showError(e);\n  }", "  } catch (e) {\n    $view.innerHTML = `<div class=\"warn\">${esc(e.message)}</div>`;\n  }"),
    ("letters accepted as a code", "const f = /^\\/formation\\/(\\d{1,9})\\/?$/.exec(pathname);", "const f = /^\\/formation\\/([^/]+)\\/?$/.exec(pathname);"),
]
HTML_MUTANTS = [
    ("independence notice dropped", "SupCompass est un site indépendant, non affilié à Parcoursup ni au ministère de l'Enseignement supérieur. ", ""),
    ("old name back", '<a class="brand" href="/">SupCompass <span>', '<a class="brand" href="/">SupTracker <span>'),
]
CACHE_MUTANTS = [
    ("pages cached by browsers", 'PAGE = "public, max-age=0, must-revalidate, s-maxage=86400"', 'PAGE = "public, max-age=86400, s-maxage=86400"'),
]


def mutated(modname: str, path: Path, old: str, new: str):
    """A fresh copy of a package module built from mutated source, in memory only (files are never written)."""
    import types
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType(modname)
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[modname] = m                       # dataclasses and pydantic look the module up while it executes
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("G10 mutation test: escaping, figures, caveat, indexing rules, sitemap, canonical, robots, router, name, cache bugs are each caught")
def g10(c: Ctx):
    global API, SEO, CACHE
    from suptracker import api
    from suptracker import cache as cache0
    from suptracker import seo as seo0
    missed = []
    fns = [g1, g2, g3, g4, g5, g6, g7, g8, g9]

    def caught() -> bool:
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001  a crash is not counted as a catch
                pass
        return False

    def trial(name, modname, path, old, new, install, uninstall):
        m = mutated(f"suptracker._mut_{modname}", path, old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)")
            return
        try:
            install(m)
            if not caught():
                missed.append(name)
        finally:
            uninstall()
            sys.modules.pop(f"suptracker._mut_{modname}", None)

    def put_seo(m):
        global SEO
        SEO = m
        api.SEO = m

    def back_seo():
        global SEO
        SEO = seo0
        api.SEO = seo0

    def put_api(m):
        global API
        API = m

    def back_api():
        global API
        API = None

    def put_cache(m):
        global CACHE
        CACHE = m
        api.CACHE = m

    def back_cache():
        global CACHE
        CACHE = cache0
        api.CACHE = cache0

    for name, old, new in MUTANTS:
        trial(name, "seo", SEO_PY, old, new, put_seo, back_seo)
    for name, old, new in API_MUTANTS:
        trial(name, "api", ROOT / "suptracker" / "api.py", old, new, put_api, back_api)
    for name, old, new in CACHE_MUTANTS:
        trial(name, "cache", ROOT / "suptracker" / "cache.py", old, new, put_cache, back_cache)
    for group, attr in ((JS_MUTANTS, "js"), (HTML_MUTANTS, "html")):
        for name, old, new in group:
            src = getattr(c, attr)
            if old not in src:
                missed.append(f"{name} (anchor gone)")
                continue
            setattr(c, attr, src.replace(old, new, 1))
            try:
                if not caught():
                    missed.append(name)
            finally:
                setattr(c, attr, src)
    n = len(MUTANTS) + len(API_MUTANTS) + len(CACHE_MUTANTS) + len(JS_MUTANTS) + len(HTML_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


BROWSER = r"""
const { chromium, devices } = require('playwright');
const [base, cod, job] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [mode, o] of [["phone", { ...devices["iPhone 13"] }], ["phone-dark", { ...devices["iPhone 13"], colorScheme: "dark" }]]) {
    const ctx = await b.newContext(o); const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
    for (const u of [`/formation/${cod}`].concat(job ? [`/metier/${job}`] : [])) {
      await p.goto(base + u); await p.waitForTimeout(3500);
      out[mode + " " + u] = await p.evaluate(() => ({ summary: !!document.querySelector(".summary"), server: !!document.querySelector("[data-seo]"),
        hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, path: location.pathname }));
    }
    await ctx.close();
  }
  { // a crawler that renders the app but may not fetch the data: the server summary must stay (Codex)
    const ctx = await b.newContext({ ...devices["iPhone 13"] }); const p = await ctx.newPage();
    await p.route("**/api/**", (r) => r.abort());
    await p.goto(base + `/formation/${cod}`); await p.waitForTimeout(2500);
    out.noapi = await p.evaluate(() => ({ server: !!document.querySelector("[data-seo] .summary"), warn: !!document.querySelector("#view > .warn") }));
    await ctx.close();
  }
  const ctx = await b.newContext({ ...devices["iPhone 13"], javaScriptEnabled: false }); const p = await ctx.newPage();
  await p.goto(base + `/formation/${cod}`);
  out.nojs = await p.evaluate(() => ({ server: !!document.querySelector("[data-seo] .summary"), text: document.querySelector("main").innerText.length,
    hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""


@check("G11 browser (--browser): the pages on a phone, light and dark, with and without JavaScript")
def g11(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser)"
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    import socket
    import time
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = {**os.environ, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".seo_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([node, str(tmp), f"http://127.0.0.1:{port}", c.sample[0], c.job_sample[0] if c.job_sample else ""],
                               capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-300:]
    d = json.loads(r.stdout)
    bad = {k: v for k, v in d["out"].items() if k not in ("nojs", "noapi") and (not v["summary"] or v["server"] or v["hscroll"])}
    noapi = d["out"]["noapi"]
    if not noapi["server"]:
        bad["API blocked"] = noapi
    nojs = d["out"]["nojs"]
    ok = not d["errs"] and not bad and nojs["server"] and nojs["text"] > 100 and not nojs["hscroll"]
    return ok, f"JS errors {d['errs'][:2]}; phone problems {bad}; without JavaScript {nojs}; data blocked {noapi}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
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
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real, a.browser)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + str(r["detail"]))
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
