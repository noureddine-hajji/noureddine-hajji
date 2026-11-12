"""Red team of the "Carte" sprint: the formations on an OpenStreetMap map, filtered like Parcoursup (type of diploma, mention), coloured by zone.
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
  C10 merge: an apprenticeship offer of the SAME establishment (UAI) for the same diploma and mention as an initial formation is
     attached to it (both labels, the CFA listed, never apart); any other offer stays apart; the formation page gets the same
     list; re-derived by SQL
  C9 apprenticeship (cartographie offers SIES does not publish): the layer re-derived by SQL (latest cartographie session,
     not in the latest SIES campaign, never twice); no zone, no rate, no paid flag, never a vœu; status, type and mention
     (vote of the SIES formations with the same labels) and académie (UAI, else département) re-derived; the Parcoursup
     link only to Parcoursup; the page card on hostile data (Node)
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
        self.db, self.real, self.part = db, real, None
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.fac = M["CA"].facets(self.con)
        labels = [d["label"] for d in self.fac["diplomes"]]
        want = ["BUT", "CPGE ECG", "Double licence", "BTS - BTSA - BTSM"]
        self.sample = [d for d in want if d in labels] if real else sorted(labels, key=lambda d: -next(x["n"] for x in self.fac["diplomes"] if x["label"] == d))[:3]


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


def node(prog: str, data) -> object:
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


def zone_shape(js: str) -> str:
    """R4: the markers are drawn by the shared zone shape helper (rond, carré, triangle), defined outside the map section."""
    out = []
    for pat in (r"^function zoneShape\(.*?^\}", r"^const ZONE_FILLED = .*?$", r"^function zoneMark\(.*?^\}", r"^function zoneBadge\(.*?^\}"):
        m = re.search(pat, js, re.M | re.S)
        out.append(m.group(0) if m else "")
    return "\n".join(out)


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
@check("C1 zones on the map = 'Mon parcours' zones (full type stage 2, independent); page merge in Node; none without a profile")
def c1(c: Ctx):
    js = carte_js(c.js)
    m = re.search(r"function carteMerge\(neutral, stage2, ok\) \{.*?\n\}", js, re.S)
    if not m:
        return False, "carteMerge missing"
    bad, n = [], 0
    dk = J.doublette_key("MATHS", "SES")
    for d in c.sample[:2]:
        lay = M["CA"].formations(c.con, d)
        got = M["CA"].zones(c.con, d, None, dk, "ab", "bg")["zones"]
        want = {}
        for tk in {f["type_key"] for f in lay["formations"] if f["type_key"]}:          # the FULL type, as Mon parcours reads it
            want.update({f["cod_aff_form"]: f["zone"] for f in J.stage2(c.con, dk, "ab", tk, None)["formations"]})
        mine = {f["cod_aff_form"] for f in lay["formations"]}
        want = {k: v for k, v in want.items() if k in mine}
        if got != want:
            bad.append((d, len(got), len(want), [k for k in want if got.get(k) != want[k]][:3]))
        page = node(m.group(0) + """
const [n, s] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify([carteMerge(n, s, true).map((f) => [f.cod_aff_form, f.zone]), carteMerge(n, s, false).every((f) => f.zone === null)]));""",
                    [M["CA"].public(lay)["formations"], {"formations": [{"cod_aff_form": k, "zone": v} for k, v in got.items()]}])
        if page is None:
            return True, "node not installed"
        if isinstance(page, dict):
            return False, page["error"]
        merged, neutral = page
        n += len(merged)
        if [(k, z) for k, z in merged if z != got.get(k)] or not neutral:
            bad.append((d, "page merge"))
    return not bad and n > 0, f"{n} formations over {min(2, len(c.sample))} types of diploma; problems {bad[:2]}"


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


def craft(i, **kw):
    base = {"cod_aff_form": str(i), "etablissement": f"Lycée {i}", "formation": "BTS X", "ville": "Lyon", "academie": "Lyon", "lat": 45.76,
            "lon": 4.84, "statut": "public", "select_form": "formation sélective", "internat": "non", "distance": "aucune",
            "amenag_sport": False, "amenag_art": False, "zone": "cible", "apprentissage": False, "initiale": True, "stats": True, "offres_app": []}
    return {**base, **kw}


CRAFT = [craft(1, internat="mixte"), craft(2, statut="prive", zone="securite", ville="Villeurbanne", lat=45.77, lon=4.88),
         craft(3, statut="contrat", select_form="formation non sélective", internat=None, zone=None, ville="Paris", academie="Paris", lat=48.85, lon=2.35),
         craft(4, lat=None, lon=None, zone="ambitieux", academie="Polynésie", distance="totale"),
         craft(5, internat="filles", distance="partielle", amenag_sport=True), craft(6, internat="garcons", amenag_art=True, distance=None),
         craft(7, statut="prive_app", apprentissage=True, initiale=False, stats=False, select_form=None, zone=None, internat="mixte"),
         craft(8, statut="public", apprentissage=True, initiale=False, stats=False, select_form=None, zone=None, lat=None, lon=None),
         craft(9, apprentissage=True, offres_app=[{"cod_aff_form": "99", "etablissement": "CFA", "formation": "BTS X", "ville": "Lyon", "fiche": None}])]
FILTERS = [{}, {"statut": ["public", "contrat"]}, {"statut": ["prive"]}, {"academie": "Lyon"}, {"select": ["non"]}, {"internat": ["mixte", "filles"]},
           {"amenag": ["presentiel"]}, {"amenag": ["totale", "sport"]}, {"amenag": ["art"]}, {"zones": ["cible", "autre"]}, {"q": "lycée 1"},
           {"autour": {"lat": 45.76, "lon": 4.84, "km": 10}}, {"autour": {"lat": 45.76, "lon": 4.84, "km": 1}, "statut": ["public", "contrat", "prive"]},
           {"app": ["oui"]}, {"app": ["non"]}, {"app": ["oui", "non"]}, {"select": ["oui"]}, {"statut": ["prive_app"], "app": ["oui"]},
           {"statut": ["public", "contrat", "prive_app"]}]


def has(f, g, o):
    z = f["zone"] if f["zone"] in ("securite", "cible", "ambitieux") else "autre"
    return {"statut": lambda: f["statut"] == o, "internat": lambda: f["internat"] == o, "zones": lambda: z == o,
            "app": lambda: bool(f.get("apprentissage")) if o == "oui" else bool(f.get("initiale")),
            "select": lambda: f["select_form"] == ("formation sélective" if o == "oui" else "formation non sélective"),
            "amenag": lambda: (f["distance"] in (None, "aucune")) if o == "presentiel" else bool(f["amenag_sport"]) if o == "sport"
            else bool(f["amenag_art"]) if o == "art" else f["distance"] == o}[g]()


def py_filter(rows, F, skip=None):
    def km(a, b, c, d):
        r = math.pi / 180
        x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
        return 12742 * math.asin(math.sqrt(x))
    q = (F.get("q") or "").strip().lower()
    out = []
    for f in rows:
        if any(F.get(g) and not any(has(f, g, o) for o in F[g]) for g in ("statut", "app", "internat", "amenag", "select", "zones") if g != skip):
            continue
        if F.get("academie") and f["academie"] != F["academie"]:
            continue
        if q and q not in f"{f['etablissement']} {f['formation']} {f['ville']}".lower():
            continue
        a = F.get("autour")
        if a and (f["lat"] is None or km(a["lat"], a["lon"], f["lat"], f["lon"]) > a["km"]):
            continue
        out.append(f["cod_aff_form"])
    return out


@check("C3 filters: page carteFilter/carteHas = independent reading (crafted and real rows, facet counts); paid unticked by default")
def c3(c: Ctx):
    js = carte_js(c.js)
    fns = "\n".join(m.group(0) for m in (re.search(r"function haversineKm\(a, b, c, d\) \{.*?\n\}", js, re.S),
                                         re.search(r"const carteZone = .*?;", js),
                                         re.search(r"function carteHas\(f, g, o\) \{.*?\n\}", js, re.S),
                                         re.search(r"function carteFilter\(rows, F, skip\) \{.*?\n\}", js, re.S),
                                         # sprint R3: the shared bands (META absent here: no band, the R3 groups stay empty)
                                         re.search(r"const CARTE_R3 = .*?;", js), re.search(r"const fiOptions = .*?;", js),
                                         re.search(r"function filtreBand\(v, bands\) \{.*?\n\}", js, re.S)) if m)
    d = c.sample[0]
    real = [{**f, "zone": z} for f, z in zip(M["CA"].public(M["CA"].formations(c.con, d))["formations"], ["securite", "cible", "ambitieux", None] * 99999)]
    acad = next((f["academie"] for f in real if f["academie"]), "")
    town = next((f for f in real if f["lat"] is not None), None)
    real_f = [{}, {"academie": acad}, {"statut": ["public"]}, {"internat": ["mixte"], "statut": ["public", "contrat", "prive"]}, {"zones": ["securite"]},
              {"amenag": ["sport", "partielle"]}, {"autour": {"lat": town["lat"], "lon": town["lon"], "km": 50}} if town else {}]
    cases = [[CRAFT, F, None] for F in FILTERS] + [[real, F, None] for F in real_f] + [[CRAFT, {"statut": ["contrat"], "internat": ["mixte"]}, "statut"]]
    page = node("const CARTE_ZONES = ['securite', 'cible', 'ambitieux'];\n" + fns + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([rows, F, skip]) => carteFilter(rows, F, skip || undefined).map((f) => f.cod_aff_form))));""", cases)
    if page is None:
        return True, "node not installed"
    if isinstance(page, dict):
        return False, page["error"]
    want = [py_filter(rows, F, skip) for rows, F, skip in cases]
    diff = [i for i, (a, b) in enumerate(zip(page, want)) if a != b]
    m = re.search(r"const CARTE_DEFAULT = (\{.*?\});", js)
    default = bool(m) and json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1))) == {"statut": ["public", "contrat", "prive_app"]}
    return not diff and default, f"{len(cases)} filter cases ({len(real)} real rows of {d}); differing cases {diff}; paid unticked by default {default}"


@check("C4 neutral layer: every formation of the latest campaign in exactly one type of diploma, counts and mentions agree, rules re-derived")
def c4(c: Ctx):
    bad = []
    rows = c.con.execute("""SELECT cod_aff_form, fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins, contrat_etab FROM core.formation_year
                            WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    seen = {}
    for d in c.fac["diplomes"]:
        lay = M["CA"].formations(c.con, d["label"])
        codes = [f["cod_aff_form"] for f in (lay or {"formations": []})["formations"]]
        if len(codes) != d["n"] or sum(m["n"] for m in d["mentions"]) != d["n"]:
            bad.append((d["label"], "counts", len(codes), d["n"]))
        for f in (lay or {"formations": []})["formations"]:
            seen[f["cod_aff_form"]] = seen.get(f["cod_aff_form"], 0) + 1
            if not f["stats"]:
                continue                            # apprenticeship offers: C9
            if f["payant"] != (f["contrat_etab"] in PB.PAID_CONTRACTS) or f["statut"] != ("public" if f["contrat_etab"] == "Public" else "prive" if f["payant"] else "contrat"):
                bad.append((d["label"], "status", f["cod_aff_form"]))
    apart = {a for a, ys in attach(c.con).items() if not ys}
    if sorted(seen) != sorted([r[0] for r in rows] + list(apart)) or any(v != 1 for v in seen.values()):
        bad.append(("coverage", len(seen), len(rows)))
    for d in c.sample[:2]:
        men = next(x for x in c.fac["diplomes"] if x["label"] == d)["mentions"][0]
        sub = M["CA"].formations(c.con, d, men["label"])
        if len(sub["formations"]) != men["n"] or any(f["mention"] != men["label"] for f in sub["formations"]):
            bad.append((d, "mention filter"))
    # a few rules written again: the owner's examples
    for cod, fili, form, fil, lib, _ in rows:
        want = ("Double licence" if (lib or "").lower().startswith("double licence") else "BUT" if fili == "BUT"
                else "CPGE ECG" if form == "Classe préparatoire économique et commerciale" and (fil or "").startswith("ECG")
                else "CPGE ECT" if form == "Classe préparatoire économique et commerciale" and (fil or "").startswith("ECT") else None)
        if want and M["CA"].diplome_of(fili, form, fil, lib)[0] != want:
            bad.append((cod, "rule", want))
    return not bad and seen, f"{len(c.fac['diplomes'])} types of diploma, {len(seen)} formations each listed once; problems {bad[:3]}"


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
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const AUTRES_LABEL = ", "const autresBadge = ")))
    z = re.search(r"const ZONES = \{.*?\n\};", c.js, re.S)
    prog = helpers + "\n" + (z.group(0) if z else "") + "\n" + zone_shape(c.js) + """
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
    route = 'if (a === "carte") return await viewCarte(b || "", c || "");' in c.js and 'carte: "carte"' in c.js
    # R1 (owner, 2026-11-11): the map is one of the Explorer views (list, map, jobs), shown on the home, search and map pages
    menus = 'carte: "#/carte", metiers' in c.js and all("explorerViews(" in c.js[c.js.index(f"function {fn}("):][:3000]
                                                        for fn in ("viewHome", "viewCarte"))
    an = "carte" in analytics.ROUTES
    pol = cache.policy("/api/carte") and cache.policy("/api/carte/formations") and cache.policy("/api/carte/zones")
    rel = '"carte": ("app.js", "function viewCarte(")' in (ROOT / "tests" / "test_release.py").read_text()
    parcours = 'href="#/carte/t/${encodeURIComponent(drill.type)}"' in c.js and "const d = FAC.types[mArg]" in c.js
    ok = route and menus and an and bool(pol) and rel and parcours
    return ok, f"route {route}; reached through the Explorer views {menus}; analytics {an}; cache {bool(pol)}; release guard {rel}; link from Mon parcours {parcours}"


def app_codes(con) -> set:
    """Independent: the apprenticeship offers of the latest cartographie session absent from the latest SIES campaign."""
    if not con.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core' AND table_name = 'cartographie' AND column_name = 'type_formation'").fetchone()[0]:
        return set()
    return {r[0] for r in con.execute("""SELECT cod_aff_form FROM core.cartographie WHERE apprentissage IS TRUE
        AND carto_session = (SELECT max(carto_session) FROM core.cartographie)
        EXCEPT SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()}


def attach(con) -> dict:
    """Independent: {apprenticeship offer: initial formations of the latest SIES campaign, same UAI (SIES or cartographie),
    same cartographie type and mention labels; SIES's own apprenticeship formations are not initial}."""
    codes = app_codes(con)
    if not codes:
        return {}
    off = {r[0]: r[1:] for r in con.execute("SELECT cod_aff_form, etab_uai, type_formation, mention_lib FROM core.cartographie").fetchall()}
    ini = con.execute("""SELECT f.cod_aff_form, f.cod_uai, c.etab_uai, c.type_formation, c.mention_lib FROM core.formation_year f, core.cartographie c
        WHERE c.cod_aff_form = f.cod_aff_form AND f.session = (SELECT max(session) FROM core.formation_year)
        AND f.apprentissage IS NOT TRUE""").fetchall()
    out = {}
    for a in codes:
        u, tf, fl = off[a]
        out[a] = sorted({y for y, u1, u2, tf2, fl2 in ini if u and u in (u1, u2) and (tf2, fl2) == (tf, fl)})
    return out


def _fold(x):
    import unicodedata
    return unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower().strip()


# every establishment label the cartographie has published (all sessions), read by hand (Codex: "hors contrat" is outside)
STATUT_CARTO = {"Publics": "public", "Privés en contrat avec l’Etat / EESC": "contrat", "Privés sous contrat": "contrat",
                "Privés hors contrat": "prive_app", "Privés": "prive_app", "Privés enseignement supérieur": "prive_app", None: None, "": None}


@check("C9 apprenticeship: layer re-derived (latest offer, not in SIES, once), no zone/rate/paid/vœu, status, vote, académie, link, card")
def c9(c: Ctx):
    want = {a for a, ys in attach(c.con).items() if not ys}
    rows = [a for d in c.fac["diplomes"] for a in (M["CA"].formations(c.con, d["label"]) or {"formations": []})["formations"] if not a["stats"]]
    got = [a["cod_aff_form"] for a in rows]
    bad = [("label", t, M["CA"].statut_carto(t), v) for t, v in STATUT_CARTO.items() if M["CA"].statut_carto(t) != v]
    labels = {t for (t,) in c.con.execute("SELECT DISTINCT types_etab FROM core.cartographie").fetchall()} if want else set()
    bad += [("unread label", t) for t in labels - set(STATUT_CARTO)]
    if sorted(got) != sorted(want) or len(set(got)) != len(got):
        bad.append(("layer", len(got), len(want)))
    if c.real and len(app_codes(c.con)) < 1000:
        bad.append(("real layer too small", len(want)))
    info = {r[0]: r[1:] for r in c.con.execute("""SELECT cod_aff_form, types_etab, type_formation, mention_lib, etab_uai, departement, fiche_url
                                                  FROM core.cartographie""").fetchall()} if want else {}
    # the vote, written again: SIES formations of the latest campaign carrying the same cartographie labels
    votes, tvotes = {}, {}
    for tf, fl, *lab in c.con.execute("""SELECT c.type_formation, c.mention_lib, f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.lib_for_voe_ins
            FROM core.formation_year f, core.cartographie c WHERE c.cod_aff_form = f.cod_aff_form
            AND f.session = (SELECT max(session) FROM core.formation_year)""").fetchall() if want else []:
        dm = CA.diplome_of(*lab)
        votes.setdefault((tf, fl), {}).setdefault(dm, 0)
        votes[(tf, fl)][dm] += 1
        tvotes.setdefault(tf, {}).setdefault(dm[0], 0)
        tvotes[tf][dm[0]] += 1
    pick = lambda d: min(d.items(), key=lambda kv: (-kv[1], kv[0]))[0] if d else None  # noqa: E731
    uai_ac, dep_ac = {}, {}
    for uai, dep, ac in c.con.execute("""SELECT cod_uai, dep_lib, acad_mies FROM core.formation_year WHERE acad_mies IS NOT NULL
                                         AND session = (SELECT max(session) FROM core.formation_year)""").fetchall():
        uai_ac.setdefault(uai, {}).setdefault(ac, 0); uai_ac[uai][ac] += 1
        dep_ac.setdefault(_fold(dep), {}).setdefault(ac, 0); dep_ac[_fold(dep)][ac] += 1
    by_label = {}
    for d in c.fac["diplomes"]:
        for a in (M["CA"].formations(c.con, d["label"]) or {"formations": []})["formations"]:
            if not a["stats"]:
                by_label[a["cod_aff_form"]] = (d["label"], a)
    zones_seen = set()
    for d in c.sample[:2]:
        zones_seen |= set(M["CA"].zones(c.con, d, None, J.doublette_key("MATHS", "SES"), "ab", "bg")["zones"])
    for cod, (dl, a) in by_label.items():
        tc, tf, fl, uai, dep, fiche = info[cod]
        st = STATUT_CARTO.get(tc)
        parts = [x.strip() for x in (tf or "").split(",") if x.strip()]
        typ = pick(tvotes.get(tf, {})) or next((pick(tvotes[x]) for x in parts if x in tvotes), None) or (parts[0] if parts else "Autre formation")
        exp = pick(votes.get((tf, fl), {})) or (typ, fl or "")
        acad = pick(uai_ac.get(uai, {})) or pick(dep_ac.get(_fold(dep), {}))
        if a["zone"] if "zone" in a else None:
            bad.append((cod, "zone"))
        if a["taux_acces_ens"] is not None or a["payant"] or a["type_key"] is not None or not a["apprentissage"] or cod in zones_seen:
            bad.append((cod, "figure or zone"))
        if a["statut"] != st or (dl, a["mention"]) != exp or a["academie"] != acad:
            bad.append((cod, "status/type/académie", a["statut"], st, (dl, a["mention"]), exp, a["academie"], acad))
        if a["fiche"] != (fiche if (fiche or "").startswith("https://dossierappel.parcoursup.fr/") else None):
            bad.append((cod, "link"))
    # the page card on hostile data
    js = carte_js(c.js)
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const AUTRES_LABEL = ", "const autresBadge = ")))
    zz = re.search(r"const ZONES = \{.*?\n\};", c.js, re.S)
    prog = helpers + "\n" + (zz.group(0) if zz else "") + "\n" + zone_shape(c.js) + """
const store = { get: () => null }; const narrow = () => false; const searchPage = () => 40;
const voeux = { has: () => false, get: () => [], MAX: 10 };
""" + block(c.js, "function voeuButton(cod) {", "\nfunction bindVoeuButton(") + "\n" + js + """
const fs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(fs.map((f) => ({ d: carteDetail(f, true), l: carteList([f], true), m: carteMarker(f) }))));"""
    good = {**CRAFT[6], "etablissement": HOSTILE, "formation": HOSTILE, "ville": HOSTILE, "contrat_etab": HOSTILE, "taux_acces_ens": None,
            "fiche": "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod=7&x=\"><b>"}
    evil = {**good, "fiche": "javascript:alert(1)"}
    o = node(prog, [good, evil])
    if o is None:
        return not bad, f"node not installed; {len(got)} offers; problems {bad[:3]}"
    if isinstance(o, dict):
        return False, o["error"]
    flat = json.dumps(o)
    page = {"raw tag": "<img" in flat or "<b>" in flat, "vœu button": "data-voeu" in flat or "mes vœux" in flat.lower(),
            "zone pill": "zone-pill" in flat or "zbadge" in flat, "internal page link": "#/f/" in flat,
            "note": "Aucune statistique d'admission n'est publiée pour les formations en apprentissage" not in o[0]["d"],
            "Parcoursup link": 'href="https://dossierappel.parcoursup.fr/' not in o[0]["d"] or 'rel="noopener noreferrer"' not in o[0]["d"],
            "javascript link": "javascript:" in o[1]["d"] + o[1]["l"], "marker": ", en apprentissage" not in o[0]["m"]}
    wrong = [k for k, v in page.items() if v]
    return not bad and not wrong, f"{len(got)} apprenticeship offers (want {len(want)}); problems {bad[:3]}; page problems {wrong}"


@check("C10 merge: same UAI and diploma -> attached to the initial formation (both labels, CFA listed, not apart); page twin")
def c10(c: Ctx):
    att = attach(c.con)
    if not att:
        return True, "no apprenticeship labels in this warehouse"
    want_by_ini = {}
    for a, ys in att.items():
        for y in ys:
            want_by_ini.setdefault(y, set()).add(a)
    bad, n_both = [], 0
    rows = [f for d in c.fac["diplomes"] for f in (M["CA"].formations(c.con, d["label"]) or {"formations": []})["formations"]]
    listed = {f["cod_aff_form"] for f in rows}
    for f in rows:
        got = {o["cod_aff_form"] for o in f.get("offres_app") or []}
        if f["stats"]:
            if got != want_by_ini.get(f["cod_aff_form"], set()):
                bad.append((f["cod_aff_form"], "offers", sorted(got)[:3]))
            if got and not (f["apprentissage"] and f["initiale"]):
                bad.append((f["cod_aff_form"], "both labels"))
            n_both += bool(got)
    if any(a in listed for a, ys in att.items() if ys):
        bad.append(("attached offer listed apart",))
    if c.real and n_both < 1000:
        bad.append(("too few merges", n_both))
    sample = next(iter(sorted(want_by_ini)), None)
    if sample and {o["cod_aff_form"] for o in M["CA"].for_formation(c.con, sample)} != want_by_ini[sample]:
        bad.append((sample, "formation page"))
    # the page: both labels and the CFA list, escaped
    js = carte_js(c.js)
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const AUTRES_LABEL = ", "const autresBadge = ")))
    zz = re.search(r"const ZONES = \{.*?\n\};", c.js, re.S)
    prog = helpers + "\n" + (zz.group(0) if zz else "") + "\n" + zone_shape(c.js) + """
const store = { get: () => null }; const narrow = () => false; const searchPage = () => 40;
const voeux = { has: () => false, get: () => [], MAX: 10 };
""" + block(c.js, "function voeuButton(cod) {", "\nfunction bindVoeuButton(") + "\n" + js + """
const [f] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ d: carteDetail(f, true), l: carteList([f], true) }));"""
    f = {**CRAFT[8], "etablissement": HOSTILE, "offres_app": [{"cod_aff_form": "99", "etablissement": HOSTILE, "formation": "x", "ville": HOSTILE,
                                                            "fiche": "https://dossierappel.parcoursup.fr/x?g_ta_cod=99"}]}
    o = node(prog, [f])
    if isinstance(o, dict) and "error" in o:
        return False, o["error"]
    if o is not None:
        flat = json.dumps(o)
        page = {"raw tag": "<img" in flat, "labels": not ("formation initiale" in o["d"] and "apprentissage</span>" in o["d"] and "formation initiale" in o["l"]),
                "CFA listed": "Aussi en apprentissage" not in o["d"] or 'href="https://dossierappel.parcoursup.fr/x?g_ta_cod=99"' not in o["d"]}
        bad += [("page", k) for k, v in page.items() if v]
    return not bad, f"{sum(1 for ys in att.values() if ys)} offers attached to {len(want_by_ini)} initial formations ({n_both} served with both labels); problems {bad[:3]}"


PY_MUTANTS = [
    ("paid flag lost", 'x["payant"] = x["statut"] == "prive"', 'x["payant"] = False'),
    ("an older campaign", "FROM core.formation_year f JOIN s ON f.session = s.s", "FROM core.formation_year f JOIN s ON f.session = s.s - 1"),
    ("ECG mentions filed under ECT", 'return "CPGE ECG", fil.replace("ECG - ", "", 1)', 'return "CPGE ECT", fil.replace("ECG - ", "", 1)'),
    ("double licences missed", 'if re.match(r"(?i)double licence", lib):', 'if False:'),
    ("apprenticeship of an older offer", "WHERE c.apprentissage AND c.carto_session = (SELECT max(carto_session) FROM core.cartographie)",
     "WHERE c.apprentissage AND c.carto_session >= (SELECT min(carto_session) FROM core.cartographie)"),
    ("SIES formations listed again as apprenticeship", "AND c.cod_aff_form NOT IN (SELECT", "AND c.cod_aff_form IN (SELECT cod_aff_form FROM core.cartographie) OR c.cod_aff_form IN (SELECT"),
    ("apprenticeship private filed as paid", 'return "prive_app"\n    return None', 'return "prive"\n    return None'),
    ("outside contract read as under contract", 'if "hors contrat" in t:', 'if False:'),
    ("attached by town, not by establishment", 'sorted(initial.get((uai, tf, fl), ())) if uai else []', 'sorted({y for (u2, t2, f2), ys in initial.items() if (t2, f2) == (tf, fl) for y in ys})[:1] if uai else []'),
    ("attachment ignores the mention", "initial.setdefault((u, tf, fl), set()).add(cod)", "initial.setdefault((u, tf, None), set()).add(cod)"),
    ("attached offers still listed apart", "for a in apprentissage(con) if not a[\"rattachee\"] and a[\"diplome\"] == diplome", "for a in apprentissage(con) if a[\"diplome\"] == diplome"),
    ("vote ignores the mention", "d, m = pair.get((tf, fl)) or", "d, m = None or"),
    ("académie by département only", "top(by_uai.get(uai)) or top(by_dep.get(_fold(dep)))", "top(by_dep.get(_fold(dep)))"),
    ("list types kept whole", 'return next((typ[x] for x in parts if x in typ), parts[0] if parts else "Autre formation")', 'return tf or "Autre formation"'),
    ("any link kept", 'fiche if (fiche or "").startswith(FICHE_PREFIX) else None', "fiche"),
    ("zones from another profile", "J.stage2(con, dkey, mention_bac, tk, None, serie=serie, only=cods)", "J.stage2(con, dkey, 'tb', tk, None, serie=serie, only=cods)"),
]
JS_MUTANTS = [
    ("zone shown without a profile", "zone: ok ? (zones.get(f.cod_aff_form) || null) : null", "zone: zones.get(f.cod_aff_form) || null"),
    ("paid ticked by default", 'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };', 'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app", "prive"] };'),
    ("presentiel misread", 'o === "presentiel" ? (!f.distance || f.distance === "aucune")', 'o === "presentiel" ? f.distance === "aucune"'),
    ("facet counts ignore other groups", '.filter((g) => g !== skip);', ';'),
    ("radius ignored", "haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon) <= F.autour.km", "true"),
    ("statut inverted", 'if (g === "statut") return f.statut === o;', 'if (g === "statut") return f.statut !== o;'),
    ("groups lose points", "grid.get(k).push(p);", "if (grid.get(k).length < 3) grid.get(k).push(p);"),
    ("unlocated formations dropped from the list", "kept.filter((f) => inView(f) || f.lat == null)", "kept.filter((f) => inView(f))"),
    ("IP note dropped", "qui voient votre adresse IP", "rapides"),
    ("Leaflet from a CDN", 'src: "/static/vendor/leaflet/leaflet.js"', 'src: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"'),
    ("name unescaped", "<strong>${esc(f.etablissement)}</strong></a> <span class=\"muted\">· ${esc(f.ville)}</span>", "<strong>${f.etablissement}</strong></a> <span class=\"muted\">· ${esc(f.ville)}</span>"),
    ("marker without its zone", 'aria-label="${esc(f.etablissement)}, ${esc(carteLabel(z))}${f.apprentissage', 'aria-label="${esc(f.etablissement)}${f.apprentissage'),
    ("one shape for all", ': zoneShape(z, 9, 9, z === "ambitieux" ? 7.2 : 6.8,', ': zoneShape("securite", 9, 9, z === "ambitieux" ? 7.2 : 6.8,'),
    ("caveat dropped", "à partir des admis des campagnes passées : ce ne sont pas des chances d'admission", "à partir des admis des campagnes passées : voici vos résultats"),
    ("apprenticeship filter inverted", 'if (g === "app") return o === "oui" ? !!f.apprentissage : !!f.initiale;', 'if (g === "app") return o === "oui" ? !!f.initiale : !!f.apprentissage;'),
    ("a formation offering both loses one label", 'if (g === "app") return o === "oui" ? !!f.apprentissage : !!f.initiale;', 'if (g === "app") return o === "oui" ? !!f.apprentissage : !f.apprentissage;'),
    ("both labels dropped", "const voieBadges = (f) => (f.initiale && f.apprentissage ?", "const voieBadges = (f) => (false ?"),
    ("CFA name unescaped", "return `<li>${esc(o.etablissement)}", "return `<li>${o.etablissement}"),
    ("apprenticeship offer shown as a formation with figures", "if (f.stats === false) return carteAppDetail(f);", ""),
    ("free apprenticeship unticked by default", 'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };', 'const CARTE_DEFAULT = { statut: ["public", "contrat"] };'),
    ("unknown selectivity read as non selective", 'return f.select_form === (o === "oui" ? "formation sélective" : "formation non sélective");', 'return o === "oui" ? f.select_form === "formation sélective" : f.select_form !== "formation sélective";'),
    ("apprenticeship link unchecked", 'const carteFiche = (f) => (f.fiche && /^https:\\/\\/dossierappel\\.parcoursup\\.fr\\//.test(f.fiche) ? f.fiche : null);', "const carteFiche = (f) => f.fiche;"),
]


@check("C8 mutation test: zones, filters, paid rule, groups, escaping, markers, OpenStreetMap hosting and wording bugs are each caught")
def c8(c: Ctx):
    fns = [c1, c2, c3, c4, c5, c6, c7, c9, c10]
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
    # likewise the double-licence mutant needs a double licence in the warehouse
    dbl = c.con.execute("SELECT count(*) FROM core.formation_year WHERE lib_for_voe_ins ILIKE 'double licence%'").fetchone()[0] > 0
    # and the link mutant needs an apprenticeship offer whose link is not a Parcoursup page (every real one is)
    shown = app_codes(c.con)
    links = any(not (u or "").startswith("https://dossierappel.parcoursup.fr/") for cod, u in
                c.con.execute("SELECT cod_aff_form, fiche_url FROM core.cartographie WHERE apprentissage IS TRUE").fetchall() if cod in shown)
    skipped = {n for n, cond in (("paid flag lost", paid), ("double licences missed", dbl), ("any link kept", links)) if not cond}
    # CI speed-up: c.part = (i, n) runs every n-th mutant from the i-th (tests/test_carte_mutants_*.py spread them over shards)
    mine = lambda k: c.part is None or k % c.part[1] == c.part[0]  # noqa: E731
    py = [m for k, m in enumerate(PY_MUTANTS) if mine(k) and m[0] not in skipped]
    js_m = [m for k, m in enumerate(JS_MUTANTS, start=len(PY_MUTANTS)) if mine(k)]
    for name, old, new in py:
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
    for name, old, new in js_m:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        saved, c.js = c.js, c.js.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = saved
    n = len(py) + len(js_m)
    part = f" (part {c.part[0] + 1}/{c.part[1]})" if c.part else ""
    return not missed and n > 0, f"{n - len(missed)}/{n} mutants caught by a failing check{part}" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, checks: set[str] | None = None, part: tuple[int, int] | None = None) -> list[dict]:
    """checks: the check ids to run (e.g. {"C8"}), all by default; part: (i, n) for C8's mutants (CI speed-up)."""
    c = Ctx(db, real)
    c.part = part
    out = []
    for fn in CHECKS:
        if checks is not None and fn.check_name.split()[0] not in checks:
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
