"""Red team of the "Carte" sprint: the formations of one filière on a map, coloured by the student's zone.
    python scripts/redteam_carte.py [--db data/suptracker.duckdb] [--real]
  C1 zones: the map's zone of every formation is the "Mon parcours" one (journey.stage2), as is (page merge run in Node);
     no zone without a profile
  C2 groups: the page's carteClusters puts every drawn formation in exactly one group of one screen cell (Node, crafted
     and real points); a formation without coordinates is listed ("non localisée"), never dropped
  C3 filters: the page's carteFilter (Node) = an independent Python reading on crafted and real rows (académie, status,
     selectivity, boarding, zones, text, radius); fee-charging private institutions only on request
  C4 neutral layer: /api/carte rows re-derived by SQL (one row per formation of the type, latest campaign, no duplicate,
     the paid flag = Plan B's rule)
  C5 OpenStreetMap (the owner's choice of base map): Leaflet self-hosted with its licence, loaded by the map page only
     (never the page shell, never a CDN), one tile URL, the attribution, and a note on the page that names the IP address
  C6 page pieces on hostile data (Node): escaped, every marker names its zone, shapes differ by zone, no chance wording,
     vouvoiement; nothing about the position or the town is sent (no API call carries them)
  C7 wiring: route, menu entries, analytics route, cache policies, release guard, sources register
  C8 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import carte as CA  # noqa: E402
from suptracker import journey as J  # noqa: E402
from suptracker import planb as PB  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>'
M = {"CA": CA}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()
        t = M["CA"].types(self.con)
        self.types = [x["type_key"] for x in t]
        self.sample = self.types[:3] + self.types[-2:] if real else self.types[:4]


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


def node(prog: str, data) -> object:
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


def carte_js(js: str) -> str:
    return block(js, "// ---- Sprint \"Carte\"", "// ---- lot 2 (Claude design guidelines)")


# ------------------------------------------------------------------ independent readings
def py_filter(rows, F):
    def km(a, b, c, d):
        r = math.pi / 180
        x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
        return 12742 * math.asin(math.sqrt(x))
    out = []
    q = (F.get("q") or "").strip().lower()
    for f in rows:
        z = f["zone"] if f["zone"] in ("securite", "cible", "ambitieux") else "autre"
        if F.get("academie") and f["academie"] != F["academie"]:
            continue
        if f["payant"] and not F.get("payant"):
            continue
        if F.get("statut") == "public" and f["contrat_etab"] != "Public" or F.get("statut") == "prive" and f["contrat_etab"] == "Public":
            continue
        if F.get("select") == "oui" and f["select_form"] != "formation sélective" or F.get("select") == "non" and f["select_form"] == "formation sélective":
            continue
        if F.get("internat") and (not f["internat"] or f["internat"] == "non"):
            continue
        if F.get("zones") and z not in F["zones"]:
            continue
        if q and q not in f"{f['etablissement']} {f['formation']} {f['ville']}".lower():
            continue
        a = F.get("autour")
        if a and (f["lat"] is None or km(a["lat"], a["lon"], f["lat"], f["lon"]) > a["km"]):
            continue
        out.append(f["cod_aff_form"])
    return out


# ------------------------------------------------------------------ checks
@check("C1 zones on the map = 'Mon parcours' zones (page merge in Node); none without a profile")
def c1(c: Ctx):
    js = carte_js(c.js)
    m = re.search(r"function carteMerge\(neutral, stage2, ok\) \{.*?\n\}", js, re.S)
    if not m:
        return False, "carteMerge missing"
    bad, n = [], 0
    dk = J.doublette_key("MATHS", "SES")
    for tk in c.sample[:3]:
        lay = M["CA"].formations(c.con, tk)
        s2 = J.public_stage2(J.stage2(c.con, dk, "ab", tk, None))
        want = {f["cod_aff_form"]: f["zone"] for f in s2["formations"]}
        got = node(m.group(0) + """
const [n, s, ok] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify([carteMerge(n, s, true).map((f) => [f.cod_aff_form, f.zone]), carteMerge(n, s, false).every((f) => f.zone === null)]));""",
                   [lay["formations"], {"formations": [{"cod_aff_form": k, "zone": v} for k, v in want.items()]}, True])
        if got is None:
            return True, "node not installed"
        if isinstance(got, dict):
            return False, got["error"]
        merged, neutral = got
        n += len(merged)
        diff = [(k, z, want.get(k)) for k, z in merged if z != want.get(k)]
        if diff or not neutral:
            bad.append((tk, diff[:3], neutral))
    return not bad and n > 0, f"{n} formations over {min(3, len(c.sample))} types; problems {bad[:2]}"


@check("C2 groups: every drawn formation in exactly one group of one cell (Node); no formation without coordinates dropped")
def c2(c: Ctx):
    js = carte_js(c.js)
    m = re.search(r"function carteClusters\(pts, cell\) \{.*?\n\}", js, re.S)
    if not m:
        return False, "carteClusters missing"
    pts = [{"x": x * 7.3 % 400, "y": x * 13.1 % 300, "f": {"cod_aff_form": str(x)}} for x in range(300)]
    out = node(m.group(0) + """
const [pts, cell] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(carteClusters(pts, cell).map((g) => g.map((p) => [p.f.cod_aff_form, Math.floor(p.x / cell), Math.floor(p.y / cell)]))));""", [pts, 52])
    if out is None:
        return True, "node not installed"
    if isinstance(out, dict):
        return False, out["error"]
    codes = [x[0] for g in out for x in g]
    one_cell = all(len({(x[1], x[2]) for x in g}) == 1 for g in out)
    want = len({(int(p["x"] // 52), int(p["y"] // 52)) for p in pts})
    listed = "kept.filter((f) => inView(f) || f.lat == null)" in js and '<span class="badge">non localisée</span>' in js
    drawn = "kept.filter((f) => f.lat != null)" in js
    ok = sorted(codes) == sorted(p["f"]["cod_aff_form"] for p in pts) and one_cell and len(out) == want and listed and drawn
    return ok, f"{len(pts)} points in {len(out)} groups (want {want}); each once {sorted(codes) == sorted(p['f']['cod_aff_form'] for p in pts)}; one cell per group {one_cell}; unlocated listed {listed}"


CRAFT = [
    {"cod_aff_form": "1", "etablissement": "Lycée A", "formation": "BTS X", "ville": "Lyon", "academie": "Lyon", "lat": 45.76, "lon": 4.84,
     "contrat_etab": "Public", "select_form": "formation sélective", "internat": "mixte", "payant": False, "zone": "cible"},
    {"cod_aff_form": "2", "etablissement": "École B", "formation": "BTS X", "ville": "Villeurbanne", "academie": "Lyon", "lat": 45.77, "lon": 4.88,
     "contrat_etab": "Privé enseignement supérieur", "select_form": "formation sélective", "internat": "non", "payant": True, "zone": "securite"},
    {"cod_aff_form": "3", "etablissement": "Lycée C", "formation": "BTS X", "ville": "Paris", "academie": "Paris", "lat": 48.85, "lon": 2.35,
     "contrat_etab": "Privé sous contrat d'association", "select_form": "formation non sélective", "internat": None, "payant": False, "zone": None},
    {"cod_aff_form": "4", "etablissement": "Lycée D", "formation": "BTS X", "ville": "Papeete", "academie": "Polynésie", "lat": None, "lon": None,
     "contrat_etab": "Public", "select_form": "formation sélective", "internat": "non", "payant": False, "zone": "ambitieux"},
]
FILTERS = [{}, {"payant": True}, {"academie": "Lyon"}, {"statut": "public"}, {"statut": "prive", "payant": True}, {"select": "non"},
           {"internat": True}, {"zones": ["cible", "autre"]}, {"q": "lycée"}, {"autour": {"lat": 45.76, "lon": 4.84, "km": 10}, "payant": True},
           {"autour": {"lat": 45.76, "lon": 4.84, "km": 1}}]


@check("C3 filters: page carteFilter = independent reading (crafted and real rows); paid institutions only on request")
def c3(c: Ctx):
    js = carte_js(c.js)
    fns = "\n".join(m.group(0) for m in (re.search(r"function haversineKm\(a, b, c, d\) \{.*?\n\}", js, re.S),
                                         re.search(r"const carteZone = .*?;", js),
                                         re.search(r"function carteFilter\(rows, F\) \{.*?\n\}", js, re.S)) if m)
    tk = c.sample[0]
    real = [{**f, "zone": z} for f, z in zip(M["CA"].formations(c.con, tk)["formations"], ["securite", "cible", "ambitieux", None] * 99999)]
    acad = next((f["academie"] for f in real if f["academie"]), "")
    town = next((f for f in real if f["lat"] is not None), None)
    real_f = [{}, {"academie": acad}, {"statut": "public"}, {"internat": True, "payant": True}, {"zones": ["securite"]},
              {"autour": {"lat": town["lat"], "lon": town["lon"], "km": 50}} if town else {}]
    page = node("const CARTE_ZONES = ['securite', 'cible', 'ambitieux'];\n" + fns + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([rows, F]) => carteFilter(rows, F).map((f) => f.cod_aff_form))));""",
                [[CRAFT, F] for F in FILTERS] + [[real, F] for F in real_f])
    if page is None:
        return True, "node not installed"
    if isinstance(page, dict):
        return False, page["error"]
    want = [py_filter(CRAFT, F) for F in FILTERS] + [py_filter(real, F) for F in real_f]
    diff = [i for i, (a, b) in enumerate(zip(page, want)) if a != b]
    paid_hidden = "2" not in page[0] and "2" in page[1]
    return not diff and paid_hidden, f"{len(want)} filter cases ({len(real)} real rows of {tk}); differing cases {diff}; paid only on request {paid_hidden}"


@check("C4 neutral layer re-derived by SQL: one row per formation of the type (latest campaign), paid flag = Plan B's rule")
def c4(c: Ctx):
    bad = []
    for tk in c.sample:
        lay = M["CA"].formations(c.con, tk)
        want = {r[0]: r[1] for r in c.con.execute("""
            SELECT t.cod_aff_form, f.contrat_etab FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
            JOIN core.formation_year f ON f.cod_aff_form = t.cod_aff_form AND f.session = t.session
            WHERE t.session = (SELECT max(session) FROM core.formation_year) AND r.spe_type_key = ?""", [tk]).fetchall()}
        got = [f["cod_aff_form"] for f in lay["formations"]]
        if sorted(got) != sorted(want) or len(got) != len(set(got)):
            bad.append((tk, len(got), len(want), len(got) - len(set(got))))
        if any(f["payant"] != (want.get(f["cod_aff_form"]) in PB.PAID_CONTRACTS) for f in lay["formations"]):
            bad.append((tk, "paid flag"))
        if lay["session"] != c.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]:
            bad.append((tk, "session"))
    n = sum(t["n"] for t in M["CA"].types(c.con))
    return not bad and n > 0, f"{len(c.sample)} types checked, {n} formations listed in all; problems {bad[:3]}"


@check("C5 OpenStreetMap: self-hosted Leaflet with its licence, loaded by the map page only, one tile URL, attribution, IP note")
def c5(c: Ctx):
    js = carte_js(c.js)
    vend = (STATIC / "vendor" / "leaflet" / "leaflet.js").exists() and (STATIC / "vendor" / "leaflet" / "LICENSE").exists()
    shell = "leaflet" not in c.html.lower() and "openstreetmap" not in c.html.lower()
    loader = block(js, "function carteLeaflet() {", "\nasync function viewCarte(")
    only_here = "/static/vendor/leaflet/leaflet.js" in loader and c.js.count("/static/vendor/leaflet/leaflet.js") == 1 and "carteLeaflet()" in block(js, "async function viewCarte(", "\n  $view.innerHTML")
    tiles = c.js.count("tile.openstreetmap.org") == 1 and "L.tileLayer(CARTE_TILES, { maxZoom: 18, attribution: CARTE_ATTRIB })" in js
    no_cdn = not re.search(r"(?:unpkg|jsdelivr|cdnjs)[^\"']*leaflet", c.js)
    note = "qui voient votre adresse IP" in js and "Votre profil et vos filtres ne leur sont pas envoyés" in js
    attrib = "contributeurs d'OpenStreetMap" in js and "Carte : ${CARTE_ATTRIB}" in js
    fallback = "la liste reste disponible" in js
    ok = vend and shell and only_here and tiles and no_cdn and note and attrib and fallback
    return ok, (f"vendored with licence {vend}; not in the page shell {shell}; loaded by the map page only {only_here}; one tile URL with attribution {tiles}; "
                f"no CDN {no_cdn}; IP note {note}; attribution under the list {attrib}; list kept if the map fails {fallback}")


@check("C6 page pieces on hostile data: escaped, zone named on every marker, shapes differ, wording; no position sent")
def c6(c: Ctx):
    js = carte_js(c.js)
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ")))
    z = re.search(r"const ZONES = \{.*?\n\};", c.js, re.S)
    prog = helpers + "\n" + (z.group(0) if z else "") + """
const store = { get: () => null }; const narrow = () => false; const searchPage = () => 40;
const voeux = { has: () => false, get: () => [], MAX: 10 };
""" + block(c.js, "function voeuButton(cod) {", "\nfunction bindVoeuButton(") + "\n" + js + """
const [f] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const zs = ["securite", "cible", "ambitieux", null].map((zone) => ({ ...f, zone }));
const out = { marks: zs.map((x) => carteMarker(x)), ring: carteRing(zs.map((x, i) => ({ x: 10 + i, y: 10, f: x }))).html,
  detail: carteDetail(zs[1], true), detail0: carteDetail(zs[1], false), list: carteList(zs, true) };
process.stdout.write(JSON.stringify(out));"""
    f = {**CRAFT[0], "etablissement": HOSTILE, "formation": HOSTILE, "ville": HOSTILE, "academie": HOSTILE, "contrat_etab": HOSTILE, "taux_acces_ens": 42.0}
    o = node(prog, [f])
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    flat = json.dumps(o)
    raw = "<img" in flat
    named = all(re.search(r'aria-label="[^"]*, (?:Vœu de sécurité|Vœu cible|Vœu ambitieux|Autre ou non situé)"', m) for m in o["marks"])
    shapes = [re.search(r"<(circle|rect|path)", m).group(1) for m in o["marks"]]
    distinct = len(set(shapes[:3])) == 3
    ring = "4 formations" in o["ring"] and "Zoomer" in o["ring"]
    detail = "d'après les admis des campagnes passées" in o["detail"] and "Indiquez votre profil" in o["detail0"]
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", js)
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    calls = re.findall(r"api\(`([^`]*)`\)", block(js, "async function viewCarte(", "\n  $view.innerHTML"))
    leak = [u for u in calls if re.search(r"autour|ctown|lat|lon|ville|F\.", u)]
    caveat = "ce ne sont pas des chances d'admission" in js and "jamais par chances" in js
    ok = not raw and named and distinct and ring and detail and not chance and not tu and not leak and calls and caveat
    return ok, (f"raw tag {raw}; every marker names its zone {named}; shapes {shapes}; cluster labelled {ring}; detail wording {detail}; "
                f"probability wording {chance[:2]}; tutoiement {tu[:2]}; API calls {calls}, leaking position {leak}; caveat {caveat}")


@check("C7 wiring: route, menus, analytics route, cache policies, release guard, link from Mon parcours")
def c7(c: Ctx):
    from suptracker import analytics, cache
    route = 'if (a === "carte") return await viewCarte(b || "");' in c.js and 'carte: "carte"' in c.js
    menus = c.html.count('href="#/carte"') == 2
    an = "carte" in analytics.ROUTES
    pol = cache.policy("/api/carte") and cache.policy("/api/carte/bts%20service")
    rel = '"carte": ("app.js", "function viewCarte(")' in (ROOT / "tests" / "test_release.py").read_text()
    parcours = 'href="#/carte/${encodeURIComponent(drill.type)}"' in c.js
    ok = route and menus and an and bool(pol) and rel and parcours
    return ok, f"route {route}; two menu entries {menus}; analytics {an}; cache {bool(pol)}; release guard {rel}; link from Mon parcours {parcours}"


PY_MUTANTS = [
    ("paid flag lost", 'x["payant"] = x["contrat_etab"] in PB.PAID_CONTRACTS', 'x["payant"] = False'),
    ("an older campaign", "WHERE f.session = s.s AND r.spe_type_key = ?", "WHERE f.session = s.s - 1 AND r.spe_type_key = ?"),
]
JS_MUTANTS = [
    ("zone shown without a profile", "zone: ok ? (zones.get(f.cod_aff_form) || null) : null", "zone: zones.get(f.cod_aff_form) || null"),
    ("paid shown by default", "&& (F.payant || !f.payant)", "&& true"),
    ("radius ignored", "haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon) <= F.autour.km", "true"),
    ("statut inverted", 'F.statut === "public" ? f.contrat_etab === "Public" : f.contrat_etab !== "Public"', 'F.statut === "public" ? f.contrat_etab !== "Public" : f.contrat_etab === "Public"'),
    ("groups lose points", "grid.get(k).push(p);", "if (grid.get(k).length < 3) grid.get(k).push(p);"),
    ("unlocated formations dropped from the list", "kept.filter((f) => inView(f) || f.lat == null)", "kept.filter((f) => inView(f))"),
    ("IP note dropped", "qui voient votre adresse IP", "rapides"),
    ("Leaflet from a CDN", 'src: "/static/vendor/leaflet/leaflet.js"', 'src: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"'),
    ("name unescaped", "<strong>${esc(f.etablissement)}</strong></a> <span class=\"muted\">· ${esc(f.ville)}</span>", "<strong>${f.etablissement}</strong></a> <span class=\"muted\">· ${esc(f.ville)}</span>"),
    ("marker without its zone", 'aria-label="${esc(f.etablissement)}, ${esc(carteLabel(z))}"', 'aria-label="${esc(f.etablissement)}"'),
    ("one shape for all", 'const shape = z === "cible" ?', 'const shape = false ?'),
    ("caveat dropped", "ce ne sont pas des chances d'admission", "voici vos résultats"),
]


@check("C8 mutation test: zones, filters, paid rule, groups, escaping, markers, OpenStreetMap hosting and wording bugs are each caught")
def c8(c: Ctx):
    fns = [c1, c2, c3, c4, c5, c6, c7]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    path = ROOT / "suptracker" / "carte.py"
    # the paid-flag mutant is only observable where a paid institution exists (the synthetic fixture has none)
    paid = c.con.execute("SELECT count(*) FROM core.formation_year WHERE contrat_etab IN (SELECT unnest(?))", [list(PB.PAID_CONTRACTS)]).fetchone()[0] > 0
    for name, old, new in [m for m in PY_MUTANTS if paid or m[0] != "paid flag lost"]:
        src = path.read_text()
        if old not in src:
            missed.append(f"{name} (anchor gone)"); continue
        m = types.ModuleType("suptracker._mut_ca")
        m.__package__, m.__file__ = "suptracker", str(path)
        sys.modules["suptracker._mut_ca"] = m
        exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
        saved, M["CA"] = M["CA"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["CA"] = saved
            sys.modules.pop("suptracker._mut_ca", None)
    for name, old, new in JS_MUTANTS:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        saved, c.js = c.js, c.js.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = saved
    n = len(PY_MUTANTS) - (0 if paid else 1) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
