"""Red team of sprint H (owner, 2026-11-15): ONE search page. The list search and the map are merged; a keyword and/or a place
(town, département, région, académie) as on Parcoursup; every filter group a dropdown; no search bar at the top of the site.

    python scripts/redteam_recherche.py [--db data/suptracker.duckdb] [--real] [--browser]

  RS1 the keyword route: /api/search/codes = the engine's own answer (S.search, all results, relevance order) re-derived for
      every query; a bare code or a fiche URL gives that code; a blank, a foreign URL or > 200 characters is a 422; no-store;
      one audience event with the cleaned words only (a profile, a place or a position sent beside it is never recorded);
      with `near` (owner, 2026-11-16: the profile's académie) = the engine's answer with `near`: the same codes, reordered only
      between equally relevant results by the engine's own rule
  RS2 places (Node vs Python): the place list (carteLieux) and its reading (carteLieu: exact label, accents and case off, with or
      without "(région)" / the code, a code alone, unknown = nothing) and carteInLieu, against an independent Python reading, on
      crafted rows (hostile strings included) and on every région, département and académie of the warehouse's layer
  RS3 privacy: the page sends its keyword and the stored profile's académie only (one search request, both encoded; the
      académie only when the layer knows it, never the place typed or « Je me réoriente »'s own académie); the place, the town's
      position, the radius, the filters and the average never leave the browser; the privacy page says so
  RS4 the shell and the home: no search bar in the shell, no list/map switch on the home, the door and the hero link open the
      search page, an old "#/s/<words>" link opens it with its words; two Explorer views (Formations, Métiers)
  RS5 the order and the failures: the list is sorted by published figures first, then distance (around a town), the engine's
      relevance, the name; never by a figure; a failed keyword request keeps the whole list and says so; an unknown place is said
  RS6 browser (--browser / --real): a keyword, then a département, give the counts an independent Python filter gives; no request
      carries the place; one dropdown open at a time, Escape and an outside click close it, a ticked box keeps it open and its count
      shows on the pill; a town with a radius keeps cards within it; on a phone the dropdowns are folded under "Filtrer" and the list
      comes before the map; no JS error, no horizontal scroll
  RS7 wiring and docs: cache policy, release guard, README section, CLAUDE.md rule, test file and its CI duration
  RS8 mutation test of RS1-RS5, RS7 and RS9 (mutants built in memory)
  RS9 no filter field lost (owner, 2026-11-16): every field and option of the earlier list and map pages (type, mention, statut,
      académie, apprentissage, internat, aménagements, sélectivité, capacité, phase complémentaire, taux, zone, keyword, place
      and radius) is a dropdown of the bar or a field of the search bar
  RS10 the shared search link (owner, 2026-11-16): #/recherche/<parameters> round-trips the words, the typed place, the radius,
      types, mentions and the groups that differ from their default; never "Ma ville", the zones or a profile key; hostile or
      unknown values dropped on opening; the reader's zone filter cleared; the message and the link escaped
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import carte as CA  # noqa: E402
from suptracker import search as S  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>'
# the search page's one query: the words and the stored profile's académie, nothing else (owner, 2026-11-16)
KW_QUERY = 'const kwQuery = (q) => { const qs = new URLSearchParams({ q }); if (near) qs.set("near", near); return qs; };'
QUERIES = ["BTS NDRC", "IUT informatique Toulouse", "infirmière Bordeaux", "kiné", "prépa HEC Lyon", "informatique", "droit",
           "licence psycho", "mpsi", "bts", HOSTILE, "Lycée", "zzzzqqq"]


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
        # a const ends at the first ";" that closes every bracket it opened (one line or several)
        depth, i = 0, m.start()
        while i < len(js):
            ch = js[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ";" and depth == 0:
                return js[m.start(): i + 1]
            i += 1
        raise KeyError(name)
    return js[m.start(): js.find("\n}", m.start()) + 2]


def fold(x) -> str:
    """Twin of app.js foldText: accents off (NFD, combining marks dropped), lower case."""
    return "".join(ch for ch in unicodedata.normalize("NFD", str(x or "")) if not ("\u0300" <= ch <= "\u036f")).lower()


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()
        self.cache = (ROOT / "suptracker" / "cache.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self._rows = None

    @property
    def rows(self) -> list:
        """Every formation of the map's layer (the rows the search page filters), apprenticeship offers included."""
        if self._rows is None:
            by_dip = CA._layer(self.con)[0]
            self._rows = [f for fs in by_dip.values() for f in fs]
        return self._rows


@contextmanager
def client(c: Ctx):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved = os.environ.get("SUPTRACKER_DB"), A.record
    calls = []
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    A.record = lambda *a, **k: calls.append(a) or "ok"
    try:
        tc = TestClient(api.app)
        tc.events = calls
        yield tc
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


# ------------------------------------------------------------------ RS1 the keyword route
def keyword_ok(c: Ctx, fn=None) -> tuple[bool, str]:
    """`fn` = the helper under test (the module's keyword_codes, or a mutant of it)."""
    from fastapi import HTTPException

    from suptracker import api
    fn = fn or api.keyword_codes
    bad, n = [], 0
    con = c.con.cursor()
    for q in QUERIES:
        want = []                                   # the engine answers per (formation, campaign): each code once, at its first rank
        for r in S.search(con, q.strip(), offset=0, limit=10 ** 6)["results"]:
            if r["cod_aff_form"] not in want:
                want.append(r["cod_aff_form"])
        got = fn(con, f"  {q} ")
        n += 1
        if got["codes"] != want or len(set(got["codes"])) != len(got["codes"]) or got["query"] != q.strip():
            bad.append((q, "codes", len(got["codes"]), len(want)))
    # near (owner, 2026-11-16): the engine's own tie rule, the same codes; witness: an order it really changes
    acads = [r[0] for r in c.con.execute("""SELECT acad_mies FROM core.formation_year WHERE acad_mies IS NOT NULL
                                             GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 3""").fetchall()]
    moved = 0
    for q in QUERIES[:8]:
        plain = fn(con, q)["codes"]
        for a in acads:
            want = []
            for r in S.search(con, q.strip(), near=a, offset=0, limit=10 ** 6)["results"]:
                if r["cod_aff_form"] not in want:
                    want.append(r["cod_aff_form"])
            got = fn(con, q, a)["codes"]
            if got != want or set(got) != set(plain):
                bad.append((q, a, "near: not the engine's tie rule, or codes added or dropped"))
            moved += got != plain
    c.near_moved = moved
    any_code = c.con.execute("SELECT max(cod_aff_form) FROM core.formation_year").fetchone()[0]
    for q, want in ((str(any_code), [str(any_code)]),
                    (f"https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={any_code}", [str(any_code)])):
        if fn(con, q)["codes"] != want:
            bad.append((q[:40], "a code or a fiche URL"))
    # an older campaign's code (or fiche) gives its formation's latest code first (the page lists the latest campaign; Codex)
    old = c.con.execute("""
        WITH l AS (SELECT l.lineage_id, fy.session, fy.cod_aff_form FROM core.lineage l JOIN core.formation_year fy USING (session, cod_aff_form)),
             top AS (SELECT lineage_id, arg_max(cod_aff_form, session) AS latest, max(session) AS s FROM l GROUP BY lineage_id)
        SELECT l.cod_aff_form, top.latest FROM l JOIN top USING (lineage_id)
        WHERE l.session < top.s AND l.cod_aff_form <> top.latest ORDER BY l.cod_aff_form LIMIT 5""").fetchall()
    for code, latest in old:
        got = fn(con, str(code))["codes"]
        if not got or got[0] != str(latest) or str(code) not in got:
            bad.append((code, "an older code not resolved to its latest formation", got, latest))
    for q in ("", "   ", "https://example.org/x", "www.example.org"):
        try:
            fn(con, q)
            bad.append((q, "accepted"))
        except HTTPException as e:
            if e.status_code != 422:
                bad.append((q, e.status_code))
    return not bad, f"{n} queries = the engine's answer; problems {bad[:4]}"


def api_keyword(q, near):
    from fastapi import HTTPException

    from suptracker import api
    try:
        return api.keyword_codes(api._con().cursor(), q, near)["codes"]
    except HTTPException:
        return None


@check("RS1 the keyword route: the engine's own answer and order, codes and URLs, 422s, no-store, one cleaned audience event")
def rs1(c: Ctx):
    ok, detail = keyword_ok(c)
    bad = []
    from suptracker import analytics as A
    with client(c) as tc:
        for q in ("BTS NDRC", HOSTILE):
            tc.events.clear()
            r = tc.get("/api/search/codes", params={"q": q, "spe1": "MATHS", "academie": "Lyon", "near": "Lyon", "lieu": "Nord (59)", "lat": "45.7", "moyenne": "14.2"})
            d = r.json()
            ev = [e for e in tc.events if e]
            blob = json.dumps([e[1] for e in ev], default=str)
            if r.status_code != 200 or "no-store" not in (r.headers.get("cache-control") or "") or d["total"] != len(d["codes"]):
                bad.append((q, "answer", r.status_code, r.headers.get("cache-control")))
            if r.status_code == 200 and d["codes"] != api_keyword(q, "Lyon"):
                bad.append((q, "the route does not pass near to the engine"))
            if len(ev) != 1 or ev[0][0] != "search" or set(ev[0][1]) != {"q", "total", "partial"} or ev[0][1]["q"] != A.clean_query(q) \
                    or any(k in blob for k in ("MATHS", "Lyon", "Nord", "45.7", "14.2")):
                bad.append((q, "event", blob[:200]))
        for q in ("", " ", "x" * 201, "https://example.org"):
            if tc.get("/api/search/codes", params={"q": q}).status_code != 422:
                bad.append((q[:20], "not a 422"))
    return ok and not bad, f"{detail}; route problems {bad[:3]}"


# ------------------------------------------------------------------ RS2 places
def py_lieux(rows, home):
    """Independent reading of the place list: {label: place}, in the page's order (home, régions, départements, académies, towns)."""
    out = {}
    if home:
        out[f"Ma ville : {home['label']}"] = {"t": "ville", "v": home["label"], "lat": home["lat"], "lon": home["lon"]}
    regions = sorted({f["region"] for f in rows if f.get("region")}, key=lambda r: REG(r))
    deps = {}
    for f in rows:
        if f.get("dep") and f.get("dep_lib"):
            deps.setdefault(f["dep"], f["dep_lib"])
    acads = sorted({f["academie"] for f in rows if f.get("academie")})
    towns = {}
    for f in rows:
        if f.get("ville") and f.get("lat") is not None:
            towns.setdefault(f["ville"], (f["lat"], f["lon"]))
    for r in regions:
        out[f"{REG(r)} (région)"] = {"t": "region", "v": r}
    for code, name in deps.items():
        out[f"{name} ({code})"] = {"t": "dep", "v": code}
    for a in acads:
        out[f"Académie de {a}"] = {"t": "acad", "v": a}
    for t, (la, lo) in towns.items():
        out.setdefault(t, {"t": "ville", "v": t, "lat": la, "lon": lo})
    return out


REG_NAMES: dict = {}


def REG(r: str) -> str:                                         # noqa: N802 - the page's region names, read from app.js
    return REG_NAMES.get(r, r)


def py_lieu(lieux: dict, txt):
    s = str(txt or "").strip()
    if not s:
        return None
    if s in lieux:
        return lieux[s]
    k = fold(s)
    for label, x in lieux.items():
        bare = re.sub(r" \((?:région|[0-9][0-9AB]?[0-9]?)\)$", "", label)
        if fold(label) == k or fold(bare) == k or (x["t"] == "dep" and x["v"] == s.upper()):
            return x
    return None


def py_in(f, L) -> bool:
    if not L or L["t"] == "ville":
        return True
    return f.get({"region": "region", "dep": "dep", "acad": "academie"}[L["t"]]) == L["v"]


PLACE_PROG = r"""
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const lieux = carteLieux(P.rows, P.home);
const out = { labels: [...lieux.keys()], read: {}, counts: {} };
for (const t of P.typed) out.read[t] = carteLieu(lieux, t);
for (const [label, x] of lieux) if (x.t !== "ville") out.counts[label] = P.rows.filter((f) => carteInLieu(f, x)).length;
out.regions = Object.fromEntries(P.regions.map((r) => [r, regionNom(r)]));
process.stdout.write(JSON.stringify(out));"""


def place_defs(js: str) -> str:
    villes = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const foldText = ",)))
    return villes + "\n" + "\n".join(top(js, n) for n in ("REGION_NOM", "regionNom", "villeLabel", "FR_COLL", "carteLieux", "carteLieu", "carteInLieu"))


def places_ok(c: Ctx, js: str) -> tuple[bool, str]:
    crafted = [
        {"cod_aff_form": "1", "region": "Bretagne", "dep": "29", "dep_lib": "Finistère", "academie": "Rennes", "ville": "Brest", "lat": 48.39, "lon": -4.49},
        {"cod_aff_form": "2", "region": "Ile-de-France", "dep": "75", "dep_lib": "Paris", "academie": "Paris", "ville": "Paris", "lat": 48.85, "lon": 2.35},
        {"cod_aff_form": "3", "region": "Corse", "dep": "2A", "dep_lib": "Corse-du-Sud", "academie": "Corse", "ville": "Ajaccio", "lat": 41.92, "lon": 8.74},
        {"cod_aff_form": "4", "region": HOSTILE, "dep": "99", "dep_lib": HOSTILE, "academie": HOSTILE, "ville": HOSTILE, "lat": 1.0, "lon": 1.0},
        {"cod_aff_form": "5", "region": None, "dep": None, "dep_lib": None, "academie": None, "ville": "Nowhere", "lat": None, "lon": None},
        {"cod_aff_form": "6", "region": "Bretagne", "dep": "35", "dep_lib": "Ille-et-Vilaine", "academie": "Rennes", "ville": "Rennes", "lat": 48.11, "lon": -1.68},
        # a town spelt like a département's label never hides the département
        {"cod_aff_form": "7", "region": "Bretagne", "dep": "29", "dep_lib": "Finistère", "academie": "Rennes", "ville": "Finistère (29)", "lat": 48.0, "lon": -4.1},
    ]
    sets = [("crafted", crafted, {"nom": "Brest", "dep": "29", "lat": 48.39, "lon": -4.49})]
    if c.real:
        sets.append(("real", [{k: f.get(k) for k in ("cod_aff_form", "region", "dep", "dep_lib", "academie", "ville", "lat", "lon")} for f in c.rows], None))
    bad, n = [], 0
    for name, rows, home in sets:
        regions = sorted({f["region"] for f in rows if f.get("region")})
        typed = ["Bretagne", "bretagne", "BRETAGNE (région)", "finistere", "Finistère (29)", "29", "2a", "Académie de Rennes", "academie de rennes",
                 "Brest", "brest", "Nowhere", "Atlantide", "", "  ", HOSTILE, "Ma ville : Brest (29)", "Nord (59)", "nord", "59", "Lyon", "Île-de-France"]
        o = node(place_defs(js) + PLACE_PROG, {"rows": rows, "home": home, "typed": typed, "regions": regions})
        if o is None:
            return True, "node not installed"
        REG_NAMES.clear()
        REG_NAMES.update(o["regions"])
        lieux = py_lieux(rows, {"label": f"{home['nom']} ({home['dep']})", "lat": home["lat"], "lon": home["lon"]} if home else None)
        # the same labels, grouped in the page's order (home, régions, départements, académies, towns; French order inside a group)
        rank = {"home": 0, "region": 1, "dep": 2, "acad": 3, "ville": 4}
        kinds = [("home" if lb.startswith("Ma ville : ") else lieux[lb]["t"]) if lb in lieux else "?" for lb in o["labels"]]
        if sorted(o["labels"]) != sorted(lieux) or len(set(o["labels"])) != len(o["labels"]) or [rank.get(k, 9) for k in kinds] != sorted(rank.get(k, 9) for k in kinds):
            bad.append((name, "labels", [x for x in o["labels"] if x not in lieux][:3], [x for x in lieux if x not in o["labels"]][:3]))
        for t in typed:
            want = py_lieu(lieux, t)
            if o["read"][t] != want:
                bad.append((name, "read", t, o["read"][t], want))
        for label, cnt in o["counts"].items():
            n += 1
            if cnt != sum(py_in(f, lieux[label]) for f in rows):
                bad.append((name, "count", label))
        if any(not v or v != v.strip() for v in o["regions"].values()):
            bad.append((name, "a région without a name"))
    return not bad, f"{n} places counted the same way; problems {bad[:4]}"


@check("RS2 places (Node vs Python): the list of places, their reading (accents, case, suffix, a code alone) and the rows each keeps")
def rs2(c: Ctx):
    return places_ok(c, c.js)


# ------------------------------------------------------------------ RS3 privacy
def privacy_ok(js: str, privacy: str) -> tuple[bool, str]:
    vc = js[js.index("async function viewCarte("):js.index("\n// ---- ", js.index("async function viewCarte("))]
    calls = re.findall(r"api\(`([^`]*)`", vc) + re.findall(r'api\("([^"]*)"', vc)
    bad = []
    search = [u for u in calls if u.startswith("/api/search")]
    if search != ["/api/search/codes?${kwQuery(q)}"] or vc.count(KW_QUERY) != 1:
        bad.append(("search requests", search))
    # near = the stored profile's académie, only one the layer knows; never the place typed, a filter or reoAcademie
    nf = js[js.index("function carteNear("):js.index("\n}", js.index("function carteNear(")) + 2] if "function carteNear(" in js else ""
    if "const near = carteNear(CARTE_ACADS);" not in vc or 'store.get("profile", null)' not in nf or "acads.includes(a)" not in nf \
            or re.search(r"lieu|reoAcademie|F\.|carteUI", nf):
        bad.append("near is not the stored profile's checked académie")
    for u in calls:
        if re.search(r"lieu|autour|lat\b|lon\b|ville|km|moyenne|F\.", u, re.I):
            bad.append(("a place or a filter in a request", u))
    if "fetch(" in vc or "navigator.sendBeacon" in vc or "track(\"search\"" in vc:
        bad.append("another channel")
    t = re.sub(r"<[^>]+>", " ", privacy)
    t = re.sub(r"\s+", " ", t)
    if "La recherche de formations envoie les mots que vous tapez et, si vous l'avez indiquée dans votre profil, votre académie" not in t \
            or "elle ne retire aucune formation" not in t or "votre liste de vœux et la recherche de formations" not in t \
            or "ce lieu n'est jamais envoyé" not in t \
            or "votre moyenne et les filtres restent dans votre navigateur" not in t or "avec la recherche, le plan B" in t:
        bad.append("the privacy page")
    return not bad, f"{len(calls)} requests of the page; problems {bad[:3]}"


@check("RS3 privacy: the keyword and the profile's académie only are sent; the place, the position, the radius, the filters and the average stay in the browser")
def rs3(c: Ctx):
    from suptracker import legal as LG
    return privacy_ok(c.js, LG.confidentialite())


# ------------------------------------------------------------------ RS4 shell and home
def shell_ok(html: str, js: str, css: str) -> tuple[bool, str]:
    bad = []
    if re.search(r"<form\b", html) or 'role="search"' in html or 'id="search"' in html:
        bad.append("a search bar in the shell")
    if re.search(r"^\.search\b", css, re.M):
        bad.append("the old bar's styles")
    home = top(js, "viewHome") + top(js, "homeCta")
    if "explorerViews(" in home or "<form" in home or 'type="search"' in home:
        bad.append("a switch or a search field on the home")
    if '<a class="door" href="#/carte">' not in home or '<a href="#/carte">Ou cherchez directement une formation</a>' not in home:
        bad.append("the home does not open the search page")
    vs = top(js, "viewSearch")
    if 'if (!q) return viewHome();' not in vs or 'carteUI.pendingQ = q;\n  location.replace("#/carte");' not in vs:
        bad.append("an old search link")
    if 'carteUI.pendingQ != null) { F.q = carteUI.pendingQ.slice(0, 200); F.lieu = null; F.autour = null; F.lieuTxt = ""; carteUI.pendingQ = null; store.set("carteFiltres2", F); }' not in js:
        bad.append("the old link's words are not the saved keyword (a rebuild loses them: Codex), or keep a stale place")
    if 'const EXPLORER_VIEWS = [["carte", "Formations", "map"], ["metiers", "Métiers", "job"]];' not in js:
        bad.append("the Explorer views")
    if 'if (a === "s") return await viewSearch(' not in js:
        bad.append("the #/s/ route")
    return not bad, f"problems {bad[:4]}"


@check("RS4 shell and home: no search bar at the top, no switch on the home, door and hero link open the one search page, old links kept")
def rs4(c: Ctx):
    return shell_ok(c.html, c.js, c.css)


# ------------------------------------------------------------------ RS5 order and failures
def order_ok(js: str) -> tuple[bool, str]:
    vc = js[js.index("async function viewCarte("):js.index("\n// ---- ", js.index("async function viewCarte("))]
    srt = re.search(r"const listed = kept\.filter\(\(f\) => inView\(f\) \|\| f\.lat == null\)(.*?)\);\n", vc, re.S)
    bad = []
    if not srt:
        return False, "no sort found"
    body = re.sub(r"//[^\n]*", "", srt.group(1))
    want = ['(a.stats === false) - (b.stats === false)', '(F.autour ? (a.dist ?? 1e9) - (b.dist ?? 1e9) : 0)',
            '(kw ? (kw.rank.get(a.cod_aff_form) ?? 1e9) - (kw.rank.get(b.cod_aff_form) ?? 1e9) : 0)',
            'byName(a, b)']
    pos = [body.find(w) for w in want]
    if -1 in pos or pos != sorted(pos):
        bad.append(("sort keys", pos))
    if re.search(r"taux|capa|zone|acc_|pct|tension", body):
        bad.append("sorted by a figure")
    if "try { kw = q ? await kwLoad(q) : null; } catch (e) { err = apiErrorText(e); }" not in vc or "carteUI.kw = kw; carteUI.kwErr = err;" not in vc \
            or "La liste montre toutes les formations." not in vc:
        bad.append("a failed keyword request")
    # one token per submission: an earlier keyword's late answer is dropped (Codex)
    if "const mine = carteUI.kwTok = (carteUI.kwTok || 0) + 1;" not in vc \
            or "if (mine !== carteUI.kwTok || seq !== carteUI.seq" not in vc or vc.index("if (mine !== carteUI.kwTok") > vc.index("carteUI.kw = kw;"):
        bad.append("a superseded keyword answer can overwrite the latest")
    if "carteUI.lieuBad = lt && !L ? lt : \"\";" not in vc or "Lieu non reconnu : « ${esc(carteUI.lieuBad)} »" not in vc:
        bad.append("an unknown place is not said (or not escaped)")
    if "${esc(INTERP_LABEL[i.type] || i.type)} : ${esc(i.value)}" not in vc or "kw.notes.map((n) => `<div class=\"info\">${esc(n)}</div>`)" not in vc:
        bad.append("the engine's reading is not shown escaped")
    return not bad, f"problems {bad[:4]}"


@check("RS5 order and failures: figures first, distance, relevance, name, never a figure; a failed keyword keeps the list; unknown place said")
def rs5(c: Ctx):
    return order_ok(c.js)


# ------------------------------------------------------------------ RS9 no filter field lost
# owner, 2026-11-16: "des drop down list sans pour autant supprimer des champs de filtrage". Every field of the two earlier
# search pages (the list search up to sprint R3 and the map up to sprint R10) and its options, as they were shipped.
EARLIER_FIELDS = {
    "statut": ["public", "contrat", "prive_app", "prive"],                     # map R10 + list R3 "Type d'établissement"
    "acad": None,                                                              # list "Académie" select + map "Académie" select
    "app": ["non", "oui"],                                                     # list option "Apprentissage" + map group
    "internat": ["mixte", "filles", "garcons"],                                # list option "Internat" + map group
    "amenag": ["presentiel", "partielle", "totale", "sport", "art"],           # list options distance / sportifs / artistes + map
    "select": ["oui", "non"],                                                  # list "Sélectivité" select + map group
    "capacite": "vocab", "complementaire": "vocab", "taux": "vocab",           # sprint R3, list and map
}
FIELD_PROG = r"""
const META = { filtres: JSON.parse(process.env.VOCAB) };
CARTE_ACADS.push("Lyon", "<b>Paris</b>");
process.stdout.write(JSON.stringify(carteGroups().map(([g, t, o]) => [g, t, o.map(([k]) => k)])));"""


def fields_ok(c: Ctx, js: str) -> tuple[bool, str]:
    from suptracker import filtres as FI
    voc = FI.vocab()
    prog = "\n".join(top(js, n) for n in ("FI_TITLE", "fiOptions", "CARTE_GROUPS", "CARTE_ACADS", "CARTE_R3", "ECHELLE", "CARTE_ROB", "carteGroups")) + FIELD_PROG
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    r = subprocess.run([exe, "-e", prog], capture_output=True, text=True, timeout=60, env={**os.environ, "VOCAB": json.dumps(voc)})
    if r.returncode:
        return False, r.stderr[-400:]
    groups = {g: (t, o) for g, t, o in json.loads(r.stdout)}
    bad = []
    for g, want in EARLIER_FIELDS.items():
        if g not in groups:
            bad.append(("a field of the earlier pages is gone", g))
            continue
        exp = ["Lyon", "<b>Paris</b>"] if want is None else [x["key"] for x in voc[g]] if want == "vocab" else want
        if groups[g][1] != exp:
            bad.append(("options", g, groups[g][1], exp))
    vc = js[js.index("async function viewCarte("):js.index("\n// ---- ", js.index("async function viewCarte("))]
    # the dropdowns themselves: every group above, the types, the mentions and the zones (with a profile)
    if 'const groups = carteGroups().filter(([gr]) => robOk || !gr.startsWith("rob")).map(([gr, title, opts]) => dd(gr, title,' not in vc or 'dd("dips", "Type de formation"' not in vc \
            or 'const mens = menDips.length ? dd("mens", "Mention ou spécialité"' not in vc or 'const zones = ok ? dd("zones"' not in vc:
        bad.append("a dropdown of the bar")
    if "${groups[0]}${zones}${groups.slice(1).join(\"\")}" not in vc:
        bad.append("a group left out of the bar")
    # the bar's fields: keyword (map "Nom, ville" and the list search), place (map "Autour de", académie, région...), radius
    if 'id="cs-q"' not in vc or 'id="cs-lieu"' not in vc or 'id="cs-km"' not in vc:
        bad.append("a field of the search bar")
    if "<b>Paris</b>" in vc or "box2(gr, o, esc(label))" not in vc:
        bad.append("an option label unescaped")
    return not bad, f"{len(EARLIER_FIELDS)} earlier fields kept as dropdowns + types, mentions, zones and the bar; problems {bad[:3]}"


@check("RS9 no filter field lost: every field and option of the earlier list and map pages is a dropdown (or the bar's fields)")
def rs9(c: Ctx):
    return fields_ok(c, c.js)


# ------------------------------------------------------------------ RS10 the shared search link
# owner, 2026-11-16: "lien de recherche partageable". Everything after "#": the words, the place TYPED (never "Ma ville"), the radius,
# types, mentions and the groups that differ from their default (never the zones); every value checked on opening.
SHARE_PROG = r"""
const META = { filtres: JSON.parse(process.env.VOCAB) };
CARTE_ACADS.push("Lyon", "Lille");
const FAC = { diplomes: [{ label: "BUT", n: 3, mentions: [{ label: "Informatique", n: 2 }, { label: "GEA", n: 1 }] }, { label: "BTS - BTSA - BTSM", n: 2, mentions: [{ label: "NDRC", n: 2 }] }] };
const H = "<img src=x onerror=alert(1)>";
const base = { ...CARTE_DEFAULT, zones: ["securite"], q: "BTS NDRC", lieu: { t: "dep", v: "59" }, autour: null, lieuTxt: "Nord (59)",
  statut: ["public", "contrat", "prive_app", "prive"], acad: ["Lille"], capacite: ["20a49"], app: [], internat: ["mixte"] };
const sel = { d: ["BUT"], m: { BUT: ["Informatique"] } };
const out = {};
out.link = carteShareLink(base, sel);
const raw = decodeURIComponent(out.link.replace("#/recherche/", ""));
out.read = carteShareRead(raw, FAC);
out.town = carteShareLink({ ...base, lieu: null, autour: { lat: 50.6, lon: 3.06, km: 50, ville: "Lille" }, lieuTxt: "Lille" }, sel);
out.mine = carteShareLink({ ...base, lieu: null, autour: { lat: 50.6, lon: 3.06, km: 50, ville: "x" }, lieuTxt: "Ma ville : Arras (62)" }, sel);
out.plain = carteShareLink({ ...CARTE_DEFAULT, q: "", lieu: null, autour: null, lieuTxt: "" }, { d: [], m: {} });
const hostile = new URLSearchParams();
hostile.set("q", H + "x".repeat(400)); hostile.set("lieu", "Ma ville : Arras (62)"); hostile.set("km", "9999");
hostile.append("d", "BUT"); hostile.append("d", H); hostile.append("m", "BUT::" + H); hostile.append("m", "BUT::GEA"); hostile.append("m", H);
hostile.set("f_statut", "public," + H); hostile.set("f_acad", "Lyon,Atlantide"); hostile.set("f_zones", "securite"); hostile.set("f_capacite", "20a49,9999");
hostile.set("serie", "bg"); hostile.set("spe1", "MATHS"); hostile.set("moyenne", "14");
out.hostile = carteShareRead(hostile.toString(), FAC);
out.garbage = carteShareRead("%%%==&&&", FAC);
// Codex: inherited object keys as types or mentions never throw, never reach the selection
out.proto = ["__proto__", "constructor", "toString", "hasOwnProperty"].map((k) => { try {
  const r = carteShareRead(`d=${k}&d=BUT&m=${k}::x&m=BUT::GEA&f_${k}=x`, FAC); return { ok: true, sel: r.sel, F: r.F }; } catch (e) { return { ok: false, e: String(e) }; } });
process.stdout.write(JSON.stringify(out));"""


def share_ok(js: str) -> tuple[bool, str]:
    from suptracker import filtres as FI
    names = ("FI_TITLE", "fiOptions", "CARTE_GROUPS", "CARTE_ACADS", "CARTE_R3", "ECHELLE", "CARTE_ROB", "carteGroups", "CARTE_DEFAULT", "CARTE_KMS", "MA_VILLE",
             "carteSelection", "carteShareLink", "carteShareRead")
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    r = subprocess.run([exe, "-e", "\n".join(top(js, n) for n in names) + SHARE_PROG], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "VOCAB": json.dumps(FI.vocab())})
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    rd = o["read"]
    if rd["q"] != "BTS NDRC" or rd["lieuTxt"] != "Nord (59)" or rd["sel"] != {"d": ["BUT"], "m": {"BUT": ["Informatique"]}}:
        bad.append(("round trip", rd))
    if rd["F"] != {"statut": ["public", "contrat", "prive_app", "prive"], "acad": ["Lille"], "internat": ["mixte"], "capacite": ["20a49"]}:   # app [] = its default: not shared
        bad.append(("groups", rd["F"]))
    for k in ("zones", "securite", "serie", "spe1", "mention", "moyenne", "profil"):
        if k in o["link"]:
            bad.append(("a personal key in the link", k))
    if "km%3D50" not in o["town"] or "Lille" not in o["town"]:
        bad.append(("a typed town loses its radius", o["town"]))
    if "Arras" in o["mine"] or "lieu" in o["mine"] or "km" in o["mine"]:
        bad.append(("the profile's town in the link", o["mine"]))
    if o["plain"] != "#/recherche/":
        bad.append(("an empty search carries values", o["plain"]))
    h = o["hostile"]
    if len(h["q"]) > 200 or h["lieuTxt"] != "" or h["km"] != 25 or h["sel"] != {"d": ["BUT"], "m": {"BUT": ["GEA"]}} \
            or h["F"] != {"statut": ["public"], "acad": ["Lyon"], "capacite": ["20a49"]}:
        bad.append(("hostile parameters kept", h))
    for x in o["proto"]:
        if not x["ok"] or x["sel"] != {"d": ["BUT"], "m": {"BUT": ["GEA"]}} or x["F"] != {}:
            bad.append(("an inherited key as a type or mention (Codex)", x))
    if o["garbage"] is None or o["garbage"]["sel"] != {"d": [], "m": {}}:
        bad.append(("garbage", o["garbage"]))
    vs = js[js.index("function viewRecherche(raw) {"):js.index("\n}", js.index("function viewRecherche(raw) {"))]
    if 'carteUI.pendingShare = raw || "";' not in vs or 'location.replace("#/carte");' not in vs or 'if (a === "recherche") return viewRecherche(b || "");' not in js:
        bad.append("the route")
    if 'recherche: "home"' not in js or 'recherche: "search"' not in js:
        bad.append("the tab and the audience route of the shared link")
    vc = js[js.index("async function viewCarte("):js.index("\n// ---- ", js.index("async function viewCarte("))]
    if "for (const [gr] of carteGroups()) F[gr] = gr in share.F ? share.F[gr] : [...(CARTE_DEFAULT[gr] || [])];" not in vc \
            or "Object.assign(F, { zones: [], q: share.q, lieu: null, autour: null, lieuTxt: share.lieuTxt });" not in vc:
        bad.append("a shared search does not replace the reader's filters (zones cleared)")
    # owner, 2026-11-16: the share block sits at the bottom of the page (after the list and the map), never in the search bar
    sh, bar_end = vc.find('<section class="card cs-share-card"'), vc.find("</form>")
    if sh < 0 or sh < vc.find('<div class="carte-mapcol">') or 'id="cs-share"' in vc[:max(bar_end, 0) + 400]:
        bad.append("the share block is not at the bottom of the page")
    if '${esc(said)}' not in vc or 'value="${esc(link)}"' not in vc:
        bad.append("the share message or link unescaped")
    return not bad, f"round trip, hostile and personal keys checked; problems {bad[:3]}"


@check("RS10 the shared search link: words, typed place, radius, types, mentions and groups round-trip; never Ma ville, zones or profile")
def rs10(c: Ctx):
    return share_ok(c.js)


# ------------------------------------------------------------------ RS6 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2];
(async () => {
  const b = await chromium.launch(); const errs = []; const o = {};
  const ctx = await b.newContext({ viewport: { width: 1366, height: 900 } }); const p = await ctx.newPage();
  const reqs = []; p.on("request", (r) => reqs.push(decodeURIComponent(r.url())));
  p.on("pageerror", (e) => errs.push(e.message));
  const count = () => p.$eval("#carte-count", (e) => Number((e.textContent.match(/^([\d\s\u202f\u00a0]+)/) || ["", "-1"])[1].replace(/\D/g, "")));
  const ready = () => p.waitForFunction(() => /formation/.test((document.getElementById("carte-count") || {}).textContent || ""), null, { timeout: 60000 });
  await p.goto(base + "/#/s/BTS%20NDRC"); await ready(); await p.waitForTimeout(1500);
  o.hash = await p.evaluate(() => location.hash); o.q = await p.$eval("#cs-q", (e) => e.value); o.kw = await count();
  o.storedQ = await p.evaluate(() => (JSON.parse(localStorage.getItem("carteFiltres2") || "{}") || {}).q);
  await p.fill("#cs-lieu", "Nord (59)"); await p.$eval(".cs-go", (b) => b.click()); await p.waitForTimeout(2500); o.kwDep = await count();
  o.status = await p.$eval("#cs-status", (e) => e.textContent);
  o.dipCounts = await p.$$eval('details.dd[data-dd="dips"] .dd-panel label .muted', (xs) => xs.map((x) => Number(x.textContent.replace(/\D/g, ""))));
  // the dropdowns
  const isOpen = (k) => p.$eval(`details.dd[data-dd="${k}"]`, (d) => d.open);
  const s0 = await p.$eval('details.dd[data-dd="statut"] > summary', (e) => (e.querySelector(".dd-n") || { textContent: "" }).textContent);
  await p.click('details.dd[data-dd="statut"] > summary'); const s1 = await isOpen("statut");
  await p.click('details.dd[data-dd="dips"] > summary'); const s2 = [await isOpen("statut"), await isOpen("dips")];
  await p.keyboard.press("Escape"); const s3 = await isOpen("dips");
  await p.click('details.dd[data-dd="statut"] > summary'); await p.click('details.dd[data-dd="statut"] input[data-o="prive"]'); await p.waitForTimeout(800);
  const s4 = [await isOpen("statut"), await p.$eval('details.dd[data-dd="statut"] .dd-n', (e) => e.textContent).catch(() => "")];
  o.kwDepPrive = await count();
  await p.click("h1"); const s5 = await isOpen("statut");
  o.dd = { s0, s1, s2, s3, s4, s5 };
  await p.$eval("#dd-reset", (b) => b.click()); await p.waitForTimeout(3000); await ready();
  // every dropdown on the bar (owner, 2026-11-16: no field of the earlier pages lost), then the académie one filters
  o.summaries = await p.$$eval("#cfilters details.dd > summary", (xs) => xs.map((x) => x.textContent.trim()));
  await p.fill("#cs-lieu", ""); await p.$eval(".cs-go", (b) => b.click()); await p.waitForTimeout(2500);
  await p.click('details.dd[data-dd="acad"] > summary'); await p.$eval('details.dd[data-dd="acad"] input[data-o="Lille"]', (i) => i.click()); await p.waitForTimeout(1500);
  o.kwLille = await count();
  await p.$eval("#dd-reset", (b) => b.click()); await p.waitForTimeout(3000); await ready();
  // a town and its radius
  await p.fill("#cs-q", ""); await p.fill("#cs-lieu", "Lyon"); await p.dispatchEvent("#cs-lieu", "input");
  o.km = await p.$eval(".cs-km", (e) => !e.hidden); await p.selectOption("#cs-km", "10"); await p.$eval(".cs-go", (b) => b.click()); await p.waitForTimeout(3000);
  o.dists = await p.$$eval("#carte-items .rc-meta span", (s) => s.map((x) => x.textContent).filter((t) => / km$/.test(t)).map((t) => Number(t.replace(/\D/g, ""))));
  o.hs = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  // the shared link (owner, 2026-11-16): the same search opened in a blank browser gives the same list
  await p.fill("#cs-q", "BTS NDRC"); await p.fill("#cs-lieu", "Nord (59)"); await p.$eval(".cs-go", (b) => b.click()); await p.waitForTimeout(2500);
  await p.$eval("#cs-share", (b) => b.click()); await p.waitForTimeout(500);
  const link = await p.$eval(".cs-share-link", (i) => i.value);
  const sc = await b.newContext({ viewport: { width: 1366, height: 900 } }); const sp = await sc.newPage(); sp.on("pageerror", (e) => errs.push("shared: " + e.message));
  await sp.goto(link); await sp.waitForFunction(() => /formation/.test((document.getElementById("carte-count") || {}).textContent || ""), null, { timeout: 60000 });
  await sp.waitForTimeout(1500);
  o.shared = await sp.evaluate(() => ({ hash: location.hash, q: document.getElementById("cs-q").value, lieu: document.getElementById("cs-lieu").value,
    n: Number((document.getElementById("carte-count").textContent.match(/^([\d\s\u202f\u00a0]+)/) || ["", "-1"])[1].replace(/\D/g, "")) }));
  o.shareLink = link;
  await sc.close();
  o.leak = reqs.filter((u) => /Nord|\(59\)|Lyon|lieu=|lat=|lon=|km=/.test(u.replace(/^https?:\/\/[^/]+/, "")) && !/tile\.openstreetmap/.test(u));
  await ctx.close();
  // a phone
  const ph = await b.newContext({ ...devices["iPhone 13"] }); const q = await ph.newPage(); q.on("pageerror", (e) => errs.push("phone: " + e.message));
  await q.goto(base + "/#/s/informatique");
  await q.waitForFunction(() => document.querySelector("#carte-items .result"), null, { timeout: 60000 });
  o.phone = await q.evaluate(() => ({ fold: !document.getElementById("dd-fold").open, label: document.querySelector("#dd-fold > summary").textContent,
    order: document.querySelector(".carte-results").getBoundingClientRect().top < document.querySelector(".carte-mapcol").getBoundingClientRect().top,
    hs: document.documentElement.scrollWidth > document.documentElement.clientWidth, cards: document.querySelectorAll("#carte-items .result").length }));
  await ph.close();
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


def py_count(c: Ctx, q: str, lieu=None, statut=("public", "contrat", "prive_app")) -> int:
    from suptracker import api
    codes = set(api.keyword_codes(c.con.cursor(), q)["codes"])
    words = [w for w in re.split(r"[^a-z0-9]+", fold(q)) if len(w) > 1]
    n = 0
    for f in c.rows:
        if f.get("statut") not in statut:
            continue
        if lieu and f.get(lieu[0]) != lieu[1]:
            continue
        if f["cod_aff_form"] in codes or (f.get("stats") is False and words and all(w in fold(f"{f['etablissement']} {f['formation']} {f['ville']}") for w in words)):
            n += 1
    return n


@check("RS6 browser: keyword then département counted as in Python, place never sent, dropdowns, town radius, phone fold; no error, no scroll")
def rs6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".recherche_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=500, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-800:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    want = {"kw": py_count(c, "BTS NDRC"), "kwDep": py_count(c, "BTS NDRC", ("dep", "59")), "kwLille": py_count(c, "BTS NDRC", ("academie", "Lille")),
            "kwDepPrive": py_count(c, "BTS NDRC", ("dep", "59"), ("public", "contrat", "prive_app", "prive"))}
    if o["hash"] != "#/carte" or o["q"] != "BTS NDRC" or o["storedQ"] != "BTS NDRC":
        bad.append(("the old link", o["hash"], o["q"]))
    for k, v in want.items():
        if o[k] != v:
            bad.append((k, o[k], v))
    # the types offered are counted among what the keyword and the place keep (owner's screenshot: national totals before)
    if not o["dipCounts"] or sum(o["dipCounts"]) != want["kwDep"] or min(o["dipCounts"]) <= 0:
        bad.append(("type counts", o["dipCounts"], want["kwDep"]))
    sh = o.get("shared") or {}
    if sh.get("hash") != "#/carte" or sh.get("q") != "BTS NDRC" or sh.get("lieu") != "Nord (59)" or sh.get("n") != want["kwDep"] \
            or "/#/recherche/" not in (o.get("shareLink") or ""):
        bad.append(("the shared link", sh, o.get("shareLink")))
    titles = ("Type de formation", "Types d'établissement", "Académie", "Apprentissage", "Internat", "Aménagements", "Sélectivité",
              "Capacité", "Phase complémentaire", "Taux d'accès officiel")
    if not all(any(s.startswith(t) for s in o["summaries"]) for t in titles):
        bad.append(("a dropdown missing on the page", o["summaries"]))
    dd = o["dd"]
    # statut: three boxes ticked by default (no mark); ticking the paid one marks the group with its 4 ticked boxes
    if not (dd["s1"] and dd["s2"] == [False, True] and not dd["s3"] and dd["s4"][0] and dd["s4"][1].strip() == "4" and not dd["s5"] and dd["s0"] == ""):
        bad.append(("dropdowns", dd))
    if not o["km"] or not o["dists"] or any(x > 10 for x in o["dists"]):
        bad.append(("radius", o["km"], o["dists"][:5]))
    if o["leak"]:
        bad.append(("a place sent", o["leak"][:3]))
    ph = o["phone"]
    if not (ph["fold"] and "Filtrer" in ph["label"] and ph["order"] and not ph["hs"] and ph["cards"] == 10):
        bad.append(("phone", ph))
    if o["hs"] or d["errs"]:
        bad.append(("scroll or JS errors", o["hs"], d["errs"][:2]))
    return not bad, f"counts {[(k, o[k]) for k in want]}; problems {bad[:4]}"


# ------------------------------------------------------------------ RS7 wiring and docs
def docs_ok(c: Ctx, cache: str | None = None, release: str | None = None) -> tuple[bool, str]:
    cache = c.cache if cache is None else cache
    release = c.release if release is None else release
    need = {
        "cache policy": '(r"/api/search/codes", NO_STORE,' in cache and cache.index('r"/api/search/codes"') < cache.index('(r"/api/search", '),
        "feature": '"recherche_unique"' in c.api_src,
        "release guard": '"recherche_unique": ("app.js", "async function doSearch(")' in release,
        "README": "Sprint H" in c.readme and "/api/search/codes" in c.readme and "redteam_recherche.py" in c.readme,
        "CLAUDE.md": "One search page (sprint H" in c.claude and "redteam_recherche.py" in c.claude,
        "test file": (ROOT / "tests" / "test_recherche.py").exists(),
        "CI duration": '"tests/test_recherche.py"' in c.durations,
    }
    bad = [k for k, v in need.items() if not v]
    return not bad, f"missing {bad}"


@check("RS7 wiring and docs: no-store policy before /api/search, release guard, README, CLAUDE.md, test file and its duration")
def rs7(c: Ctx):
    return docs_ok(c)


# ------------------------------------------------------------------ RS8 mutation test
# (name, old, new, witness): a mutant needing a witness ("dup": a code the engine answers for two campaigns, "many": a query with
# more than 40 results) is counted only on a warehouse that has one (the real one does; the small synthetic one does not)
KW_MUTANTS = [
    ("engine order lost", '"codes": list(dict.fromkeys(r["cod_aff_form"] for r in res["results"]))', '"codes": sorted(set(r["cod_aff_form"] for r in res["results"]))', None),
    ("a code once per campaign", '"codes": list(dict.fromkeys(r["cod_aff_form"] for r in res["results"]))', '"codes": [r["cod_aff_form"] for r in res["results"]]', "dup"),
    ("a code at its last rank", '"codes": list(dict.fromkeys(r["cod_aff_form"] for r in res["results"]))', '"codes": list(dict.fromkeys(r["cod_aff_form"] for r in res["results"][::-1]))[::-1]', "dup"),
    ("only the first page", "res = S.search(con, q, near=near or None, offset=0, limit=10 ** 6)", "res = S.search(con, q, near=near or None, offset=0, limit=40)", "many"),
    ("the profile's académie ignored", "res = S.search(con, q, near=near or None, offset=0, limit=10 ** 6)", "res = S.search(con, q, offset=0, limit=10 ** 6)", "near"),
    ("the académie used as a filter", "res = S.search(con, q, near=near or None, offset=0, limit=10 ** 6)", "res = S.search(con, q, academie=near or None, near=near or None, offset=0, limit=10 ** 6)", "near"),
    ("blank accepted", '    if not q:\n        raise HTTPException(422, "Recherche vide : tapez au moins un mot.")\n', "", None),
    ("foreign URL searched", 'if q.lower().startswith(("http", "www.")) and not cod:', "if False:", None),
    ("a code searched as words", "if cod or (q.isdigit() and len(q) <= 9):", "if cod:", None),
    ("an older code not resolved (Codex)", '"codes": list(dict.fromkeys([*(latest or []), code]))', '"codes": [code]', "old"),
    ("words not trimmed", "    q = q.strip()\n    if not q:", "    if not q.strip():", None),
]
JS_MUTANTS = [
    ("places: accents kept", "if (foldText(label) === k || ", "if (label.toLowerCase() === k || ", "rs2"),
    ("places: a code alone ignored", ' || (x.t === "dep" && x.v === s.toUpperCase())', "", "rs2"),
    ("places: suffix not dropped", 'foldText(label.replace(/ \\((?:région|[0-9][0-9AB]?[0-9]?)\\)$/, "")) === k', "false", "rs2"),
    ("places: région read as académie", 'L.t === "region" ? f.region === L.v', 'L.t === "region" ? f.academie === L.v', "rs2"),
    ("places: académies left out", '.forEach((a) => out.set(`Académie de ${a}`, { t: "acad", v: a }));', ";", "rs2"),
    ("places: a town hides a département", 'forEach(([t, x]) => { if (!out.has(t)) out.set(t,', "forEach(([t, x]) => { if (true) out.set(t,", "rs2"),
    ("privacy: the place sent", 'if (near) qs.set("near", near); return qs; };', 'if (near) qs.set("near", near); if (F.lieuTxt) qs.set("lieu", F.lieuTxt); return qs; };', "rs3"),
    ("privacy: the typed place sent as the académie", "const near = carteNear(CARTE_ACADS);", "const near = F.lieu ? F.lieu.v : carteNear(CARTE_ACADS);", "rs3"),
    ("privacy: a stored académie not checked", 'return a && acads.includes(a) ? a : "";', "return a;", "rs3"),
    ("home: the switch back", "  ${homeProfile()}\n", '  ${explorerViews("carte")}${homeProfile()}\n', "rs4"),
    ("old link: words lost", 'carteUI.pendingQ = q;\n  location.replace("#/carte");', 'location.replace("#/carte");', "rs4"),
    ("old link: a stale place kept", "F.q = carteUI.pendingQ.slice(0, 200); F.lieu = null; F.autour = null;", "F.q = carteUI.pendingQ.slice(0, 200);", "rs4"),
    ("old link: words not saved (Codex)", 'carteUI.pendingQ = null; store.set("carteFiltres2", F); }', "carteUI.pendingQ = null; }", "rs4"),
    ("order: by the official rate", '|| byName(a, b));', '|| (b.taux_acces_ens ?? 0) - (a.taux_acces_ens ?? 0));', "rs5"),
    ("order: relevance ignored", "(kw ? (kw.rank.get(a.cod_aff_form) ?? 1e9) - (kw.rank.get(b.cod_aff_form) ?? 1e9) : 0)", "0", "rs5"),
    ("failure: the list emptied", "catch (e) { err = apiErrorText(e); }", "catch (e) { err = apiErrorText(e); kw = { codes: new Set(), rank: new Map(), words: [], interp: [], notes: [] }; }", "rs5"),
    ("a superseded answer kept (Codex)", "if (mine !== carteUI.kwTok || seq !== carteUI.seq", "if (seq !== carteUI.seq", "rs5"),
    ("unknown place unescaped", "Lieu non reconnu : « ${esc(carteUI.lieuBad)} »", "Lieu non reconnu : « ${carteUI.lieuBad} »", "rs5"),
    ("the académie dropdown dropped (owner, 2026-11-16)", '["acad", "Académie", CARTE_ACADS.map((a) => [a, a])], ', "", "rs9"),
    ("the apprenticeship group dropped", '  ["app", "Apprentissage", [["non", "Formations hors apprentissage"], ["oui", "Formations en apprentissage"]]],\n', "", "rs9"),
    ("an aménagement option dropped", '["sport", "Aménagements pour sportifs de haut niveau"], ', "", "rs9"),
    ("the R3 groups dropped", "  ...CARTE_R3.map((g) => [g, FI_TITLE[g], fiOptions(g).map((o) => [o.key, o.label])]), ...CARTE_ROB];", "  ...CARTE_ROB];", "rs9"),
    ("the mention dropdown dropped", 'const mens = menDips.length ? dd("mens", "Mention ou spécialité"', 'const mens = false ? dd("mens", "Mention ou spécialité"', "rs9"),
    ("share: the profile's town kept", "if ((F.lieu || F.autour) && lt && !lt.startsWith(MA_VILLE))", "if ((F.lieu || F.autour) && lt)", "rs10"),
    ("share: the zones shared", "  for (const [gr] of carteGroups()) {\n    if (JSON.stringify", "  qs.set(\"f_zones\", (F.zones || []).join(\",\"));\n  for (const [gr] of carteGroups()) {\n    if (JSON.stringify", "rs10"),
    ("share: any radius accepted", "km: CARTE_KMS.includes(Number(qs.get(\"km\"))) ? Number(qs.get(\"km\")) : 25", "km: Number(qs.get(\"km\")) || 25", "rs10"),
    ("share: unknown options kept", "F[gr] = [...new Set(qs.get(`f_${gr}`).split(\",\").filter((k) => keys.includes(k)))];", "F[gr] = [...new Set(qs.get(`f_${gr}`).split(\",\"))];", "rs10"),
    ("share: an inherited key breaks the page (Codex)",
     "  const m = Object.create(null);\n  qs.getAll(\"m\").forEach((x) => { const i = x.indexOf(\"::\"); if (i > 0) { const d = x.slice(0, i); (m[d] = Array.isArray(m[d]) ? m[d] : []).push(x.slice(i + 2)); } });",
     "  const m = {};\n  qs.getAll(\"m\").forEach((x) => { const i = x.indexOf(\"::\"); if (i > 0) (m[x.slice(0, i)] = m[x.slice(0, i)] || []).push(x.slice(i + 2)); });", "rs10"),
    ("share: types not checked", 'sel: carteSelection(FAC, "", "", { d: qs.getAll("d"), m }), F };', 'sel: { d: qs.getAll("d"), m }, F };', "rs10"),
    ("share: a stale zone filter kept", "Object.assign(F, { zones: [], q: share.q,", "Object.assign(F, { q: share.q,", "rs10"),
]
OTHER_MUTANTS = [
    ("html", "a search bar back in the shell", '<a class="skip" href="#view">Aller au contenu</a>\n', '<a class="skip" href="#view">Aller au contenu</a>\n<form id="search" role="search"></form>\n'),
    ("cache", "the keyword cached", '(r"/api/search/codes", NO_STORE,', '(r"/api/search/codes", PUBLIC,'),
    ("privacy", "the privacy page silent", "La recherche de formations envoie les mots que vous tapez et, si vous l'avez indiquée dans votre profil, votre académie", "La recherche de formations envoie les mots que vous tapez"),
]


@check("RS8 mutation test: keyword route, places, privacy, shell and home, order and failure bugs are each caught")
def rs8(c: Ctx):
    from suptracker import api
    from suptracker import legal as LG
    base = {"rs1": keyword_ok(c)[0], "rs2": places_ok(c, c.js)[0], "rs3": privacy_ok(c.js, LG.confidentialite())[0],
            "rs4": shell_ok(c.html, c.js, c.css)[0], "rs5": order_ok(c.js)[0], "rs7": docs_ok(c)[0], "rs9": fields_ok(c, c.js)[0], "rs10": share_ok(c.js)[0]}
    if not all(base.values()):
        return False, f"the unmutated code fails {[k for k, v in base.items() if not v]}: mutants not counted"
    missed = []
    src = inspect.getsource(api.keyword_codes)
    con = c.con.cursor()
    answers = [[r["cod_aff_form"] for r in S.search(con, q, offset=0, limit=10 ** 6)["results"]] for q in QUERIES]
    witness = {None: True, "dup": any(len(set(a)) < len(a) for a in answers), "many": any(len(set(a)) > 40 for a in answers),
               "old": c.con.execute("SELECT count(DISTINCT session) > 1 FROM core.lineage").fetchone()[0],
               "near": bool(getattr(c, "near_moved", 0))}
    skipped = []
    for name, old, new, need in KW_MUTANTS:
        if not witness[need]:
            skipped.append(name)
            continue
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone)")
            continue
        ns = dict(vars(api))
        exec(compile(src.replace(old, new), "<mutant>", "exec"), ns)         # noqa: S102 - our own source, mutated in memory
        try:
            caught = not keyword_ok(c, ns["keyword_codes"])[0]
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    for name, old, new, chk in JS_MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor gone)")
            continue
        m = c.js.replace(old, new)
        run = {"rs10": lambda: share_ok(m), "rs9": lambda: fields_ok(c, m), "rs2": lambda: places_ok(c, m), "rs3": lambda: privacy_ok(m, LG.confidentialite()), "rs4": lambda: shell_ok(c.html, m, c.css),
               "rs5": lambda: order_ok(m)}[chk]
        try:
            caught = not run()[0]
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    for kind, name, old, new in OTHER_MUTANTS:
        text = {"html": c.html, "cache": c.cache, "privacy": LG.confidentialite()}[kind]
        if text.count(old) != 1:
            missed.append(f"{name} (anchor gone)")
            continue
        m = text.replace(old, new)
        ok = {"html": lambda: shell_ok(m, c.js, c.css), "cache": lambda: docs_ok(c, cache=m), "privacy": lambda: privacy_ok(c.js, m)}[kind]()[0]
        if ok:
            missed.append(name)
    n = len(KW_MUTANTS) + len(JS_MUTANTS) + len(OTHER_MUTANTS) - len(skipped)
    return not missed, (f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")
                        + (f"; no witness in this warehouse for {skipped}" if skipped else ""))


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
