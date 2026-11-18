"""Red team of sprint R3 (owner, 2026-11-12): the advanced filters shared by the search and the map.

    python scripts/redteam_filtres.py [--db data/suptracker.duckdb] [--real] [--browser]

  FI1 bands: capacity and official-rate bands are contiguous, never overlap, lower limit in / upper limit out; the page's
      filtreBand gives the same band as filtres.band on every boundary and a grid of values; the map cuts with the same bands
  FI2 the server filters nothing any more (owner, 2026-11-16): /api/search has no advanced or profile parameter, the module keeps
      the bands only (no zone reader, no filtering, no sort)
  FI3 privacy: a profile or filters sent with /api/search change nothing and are never recorded; no-store; the search page sends
      its keyword only
  FI4 never sorted by a figure: the module sorts nothing; the search page's list keeps figures first, relevance, name
  FI5 the page (Node): every group with its counts, labels escaped, the zone group asks for a profile (link to Mon profil) or for a
      narrower search above the limit; the help texts say "pas une promesse" / "pas vos chances"; zone pills escaped
  FI6 the map: the payload's capacity and complementary-phase admits equal the warehouse; the map's filter (Node, the page's own
      carteFilter) keeps, for each new option, the formations an independent Python filter keeps
  FI7 browser (--browser / --real): a profile, the zone chip filters the list to its own count; the map shows the new groups; 0 JS
      error; no horizontal scroll on a phone
  FI8 mutation test of FI1-FI6 (mutants built in memory: the module re-loaded from a mutated source, api.py and the page's script mutated)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import carte as CA  # noqa: E402
from suptracker import filtres as FI0  # noqa: E402
from suptracker import journey as J  # noqa: E402
from suptracker import search as S  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
SRC = (ROOT / "suptracker" / "filtres.py").read_text()
CHECKS = []
CHANCE = re.compile(r"(?i)probabilit|vos chances(?! ?[)»])|chances? d['’]être admis|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load_module(src: str):
    """The filters module from a (possibly mutated) source, in the package (relative imports work)."""
    spec = importlib.util.spec_from_loader("suptracker.filtres_rt", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "suptracker"
    exec(compile(src, "filtres_rt.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.cache = (ROOT / "suptracker" / "cache.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.FI = FI0
        self.src = SRC
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]


@contextmanager
def client(c: Ctx):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved, saved_fi = os.environ.get("SUPTRACKER_DB"), A.record, api.FI
    calls = []
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    A.record = lambda *a, **k: calls.append(a) or "ok"
    api.FI = c.FI
    try:
        tc = TestClient(api.app)
        tc.events = calls
        yield tc
    finally:
        A.record, api.FI = saved, saved_fi
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return "__error__ " + r.stderr[-800:]
    return r.stdout


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        end = js.find("\n};", m.start())
        if end != -1 and js[m.start():one].count("{") + js[m.start():one].count("[") > js[m.start():one].count("}") + js[m.start():one].count("]"):
            end2 = js.find("\n];", m.start())
            ends = [x for x in (end, end2) if x != -1]
            return js[m.start(): min(ends) + 3]
        return js[m.start(): one]
    end = js.find("\n}", m.start())
    return js[m.start(): end + 2]


# ------------------------------------------------------------------ FI1 bands
def bands_js(js: str, vocab: dict, values: list):
    prog = top(js, "filtreBand") + """
const [V, vals] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(vals.map((v) => [filtreBand(v, V.capacite), filtreBand(v, V.taux)])));"""
    return node(prog, [vocab, values])


@check("FI1 bands: contiguous, never overlapping, lower in / upper out; the page and the map cut like the module")
def fi1(c: Ctx):
    bad = []
    v = c.FI.vocab()
    for g in ("capacite", "taux"):
        b = v[g]
        if b[0]["min"] is not None or b[-1]["max"] is not None or any(b[i]["max"] != b[i + 1]["min"] for i in range(len(b) - 1)):
            bad.append(("bands not contiguous", g))
    values = [None, 0, 0.5, 19, 19.99, 20, 29.9, 30, 49, 50, 59.9, 60, 89.9, 90, 99, 100, 100.0, 250]
    for x in values:
        exp_c = None if x is None else ("moins20" if x < 20 else "20a49" if x < 50 else "50a99" if x < 100 else "100plus")
        exp_t = None if x is None else ("moins30" if x < 30 else "30a59" if x < 60 else "60a89" if x < 90 else "90plus")
        if c.FI.band(x, c.FI.CAPACITE) != exp_c or c.FI.band(x, c.FI.TAUX) != exp_t:
            bad.append(("module band", x, c.FI.band(x, c.FI.CAPACITE), c.FI.band(x, c.FI.TAUX)))
    r = bands_js(c.js, v, values)
    if r is not None:
        if r.startswith("__error__"):
            return False, r
        got = json.loads(r)
        want = [[c.FI.band(x, c.FI.CAPACITE), c.FI.band(x, c.FI.TAUX)] for x in values]
        if got != want:
            bad.append(("the page cuts differently", [(x, g, w) for x, g, w in zip(values, got, want) if g != w][:3]))
    has = top(c.js, "carteHas")
    if 'filtreBand(f.capa_fin, fiOptions("capacite"))' not in has or 'filtreBand(f.taux_acces_ens, fiOptions("taux"))' not in has:
        bad.append("the map does not cut with the served bands")
    if '"filtres": FI.vocab()' not in c.api:
        bad.append("the bands are not served to the page")
    return not bad, f"{len(bad)} problems {bad[:3]}"


# ------------------------------------------------------------------ FI2 the server filters nothing any more
# owner, 2026-11-16: the advanced search of sprint R3 (`/api/search?avance=true`, filters and zones read on the server for a profile
# sent with the search) is removed. The one search page (sprint H) asks the engine for its keyword's codes and filters in the
# browser with the bands below (FI5-FI7, red team redteam_recherche.py).
ADVANCED = ("capacite", "complementaire", "statut", "taux", "zone", "serie", "spe1", "spe2", "mention", "moyenne", "avance")


def module_ok(src: str, FI) -> tuple[bool, str]:
    bad = []
    left = [n for n in ("parse", "attributes", "zones", "tags", "apply", "GROUPS", "_CACHE") if hasattr(FI, n)]
    if left:
        bad.append(("the server-side filtering is back in the module", left))
    if re.search(r"\bsort(?:ed)?\(", src):
        bad.append("the module sorts")
    if set(FI.vocab()) != {"capacite", "taux", "complementaire", "statut", "zone"}:
        bad.append(("the vocabulary", sorted(FI.vocab())))
    return not bad, f"problems {bad[:3]}"


def route_ok(api_src: str) -> tuple[bool, str]:
    sig = api_src[api_src.index('@app.get("/api/search")'):api_src.index("\n    q = q.strip()", api_src.index('@app.get("/api/search")'))]
    back = [p for p in ADVANCED if re.search(rf"\b{p}\s*:", sig)]
    gone = "_search_advanced" not in api_src and "FI.parse(" not in api_src and "FI.zones(" not in api_src
    return not back and gone, f"advanced parameters back {back}; server filtering gone {gone}"


@check("FI2 the server filters nothing any more: no advanced parameter on /api/search, the module keeps the bands only, sorts nothing")
def fi2(c: Ctx):
    ok1, d1 = module_ok(c.src, c.FI)
    ok2, d2 = route_ok(c.api)
    return ok1 and ok2, f"module: {d1}; route: {d2}"


@check("FI3 privacy: a profile or filters sent with /api/search are not read (same answer, no zone), never recorded; no-store")
def fi3(c: Ctx):
    bad = []
    prof = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "moyenne": "14.2", "zone": "securite", "capacite": "20a49", "avance": "true"}
    with client(c) as tc:
        for q in ("informatique", "BTS commerce"):
            tc.events.clear()
            r, plain = tc.get("/api/search", params={"q": q, **prof}), tc.get("/api/search", params={"q": q})
            blob = json.dumps([e[1] for e in tc.events if e], default=str)
            if r.status_code != 200 or "no-store" not in (r.headers.get("cache-control") or ""):
                bad.append((q, r.status_code, r.headers.get("cache-control")))
                continue
            if [x["cod_aff_form"] for x in r.json()["results"]] != [x["cod_aff_form"] for x in plain.json()["results"]] or r.json()["total"] != plain.json()["total"]:
                bad.append((q, "a profile or a filter changed the answer"))
            if any(k in x for x in r.json()["results"] for k in ("zone", "uncertain", "estime_serie")) or "filtres" in r.json():
                bad.append((q, "a zone or a filter read on the server"))
            if any(k in blob for k in ("MATHS", "SES", "14.2", "securite", "20a49")):
                bad.append((q, "the profile or a filter recorded", blob[:120]))
    vc = top(c.js, "viewCarte")
    calls = re.findall(r'api\(`(/api/search[^`]*)`', vc)
    # owner, 2026-11-16: the keyword and the stored profile's académie (equal-relevance ties only), never a filter or the bac profile
    if calls != ["/api/search/codes?${kwQuery(q)}"] \
            or 'const kwQuery = (q) => { const qs = new URLSearchParams({ q }); if (near) qs.set("near", near); return qs; };' not in vc:
        bad.append(("the search page sends more than its keyword and the académie", calls))
    return not bad, f"problems {bad[:3]}"


@check("FI4 never sorted by a figure: the module sorts nothing; the search page's list keeps figures first, relevance, name")
def fi4(c: Ctx):
    vc = top(c.js, "viewCarte")
    srt = re.search(r"const listed = kept\.filter\(\(f\) => inView\(f\) \|\| f\.lat == null\)(.*?)\);\n", vc, re.S)
    body = re.sub(r"//[^\n]*", "", srt.group(1)) if srt else ""
    ok = bool(srt) and not re.search(r"capa|taux|acc_pc|zone", body) and not re.search(r"\bsort(?:ed)?\(", c.src)
    return ok, f"list sort found {bool(srt)}; sorted by a figure {bool(re.search(r'capa|taux|acc_pc|zone', body))}"


PAGE_PROG = r"""
const META = { filtres: JSON.parse(process.env.VOCAB), low_n_threshold: 5 };
const H = "<img src=x onerror=alert(1)>";
let PROFILE = null;
const store = { get: (k, d) => (k === "profile" ? PROFILE : d) };
const chip = (label, href, active) => `<a class="badge${active ? " exact" : ""}" href="${esc(href)}">${esc(label)}</a>`;
const go = (patch) => "#/s/q/" + new URLSearchParams(patch).toString();
const facets = { zone: { securite: 3, cible: 5 }, statut: { public: 7 }, capacite: { moins20: 2, "100plus": 1 }, complementaire: { oui: 4 }, taux: { "90plus": 6 } };
const out = {};
PROFILE = { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b" };
out.prof = searchAdvanced({ capacite: "moins20" }, go, { facets, zones_lues: true }, chip);
PROFILE = null;
out.none = searchAdvanced({}, go, { facets, zones_lues: false }, chip);
PROFILE = { statut: "reorientation", academie: "Lyon" };
out.reoGroup = searchAdvanced({}, go, { facets: {}, zones_lues: false }, chip);
out.pill = zonePillHtml("cible", true) + zonePillHtml("hors_profil", false) + zonePillHtml(H, false);
PROFILE = { statut: "reorientation", academie: "Lyon" };
const q1 = new URLSearchParams(); out.reo = fiProfileQuery(q1) || q1.toString();
PROFILE = { serie: "bg", spe1: "MATHS", spe2: "MATHS", mention: "b" };
const q2 = new URLSearchParams(); out.same = fiProfileQuery(q2) || q2.toString();
PROFILE = { serie: "bt", mention: "ab", voie: "sti2d" };
const q3 = new URLSearchParams(); fiProfileQuery(q3); out.bt = q3.toString();
process.stdout.write(JSON.stringify(out));
"""


def page_ok(c: Ctx):
    """owner, 2026-11-15: the list search is the map page; its dropdowns carry the shared groups (META's bands, FI_TITLE),
    each with its help text, the zone group only with a readable terminale profile, the pills escaped."""
    js = c.js
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    zones = re.search(r"^const ZONES = \{.*?^\};", js, re.M | re.S).group(0)
    parts = [top(js, n) for n in ("FI_TITLE", "FI_HELP", "fiOptions", "CARTE_GROUPS", "CARTE_ACADS", "CARTE_R3", "CARTE_ROB", "carteGroups", "zoneHelp", "zoneShape",
                                  "ZONE_FILLED", "zoneMark", "zonePillHtml", "ZONE_RULES")]
    prog = helpers + "\n" + zones + "\n" + "\n".join(parts) + r"""
const META = { filtres: JSON.parse(process.env.VOCAB) };
const H = "<img src=x onerror=alert(1)>";
process.stdout.write(JSON.stringify({ groups: carteGroups(), pill: zonePillHtml("cible", true) + zonePillHtml("hors_profil", false) + zonePillHtml(H, false) }));"""
    r = subprocess.run([exe, "-e", prog], capture_output=True, text=True, timeout=60, env={**os.environ, "VOCAB": json.dumps(c.FI.vocab())})
    if r.returncode:
        return False, "__error__ " + r.stderr[-600:]
    o = json.loads(r.stdout)
    bad = []
    groups = {g: (title, [k for k, _ in opts]) for g, title, opts in o["groups"]}
    voc = c.FI.vocab()
    for g in ("capacite", "complementaire", "taux"):
        if g not in groups or groups[g][1] != [x["key"] for x in voc[g]]:
            bad.append(("a shared group or its options", g))
    if "statut" not in groups:
        bad.append("no establishment group")
    if "<img" in o["pill"] or "incertain" not in o["pill"] or "cible" not in o["pill"]:
        bad.append(("zone pill", o["pill"]))
    panel = top(js, "viewCarte")
    if 'const zones = ok ? dd("zones"' not in panel or "FI_HELP[gr] ?" not in panel or "esc(FI_HELP.zone)" not in panel:
        bad.append("the dropdowns: zone group without a profile, or the help texts missing")
    help_ = top(js, "FI_HELP")
    if "pas une promesse" not in help_ or "pas vos chances" not in help_ or "rien n'est enregistré" not in help_:
        bad.append("help texts")
    words = re.sub(r"<[^>]+>", " ", help_ + o["pill"])
    if CHANCE.search(words.replace("pas vos chances", "").replace("pas des chances", "")) or FORMAL.search(words):
        bad.append("wording")
    return not bad, f"{len(bad)} problems {bad[:3]}"


@check("FI5 the page (Node): groups and counts, untick, help texts, zone group rules, pills escaped, profile only in terminale")
def fi5(c: Ctx):
    return page_ok(c)


# ------------------------------------------------------------------ FI6 the map
MAP_PROG = r"""
const META = { filtres: JSON.parse(process.env.VOCAB) };
const rows = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
for (const [g, opts] of [["capacite", META.filtres.capacite], ["taux", META.filtres.taux], ["complementaire", META.filtres.complementaire]])
  for (const o of opts) out[g + ":" + o.key] = carteFilter(rows, { [g]: [o.key] }).map((f) => f.cod_aff_form);
process.stdout.write(JSON.stringify(out));
"""


def map_ok(c: Ctx):
    lay = CA.formations(c.con.cursor(), "BTS - BTSA - BTSM") or CA.formations(c.con.cursor(), "Licence")
    if not lay:
        return False, "no BTS layer"
    rows = [f for f in lay["formations"] if f.get("stats")]
    sql = {a: (cap, pc) for a, cap, pc in c.con.execute("SELECT cod_aff_form, capa_fin, acc_pc FROM core.formation_year WHERE session = ?",
                                                         [c.latest]).fetchall()}
    bad = [f["cod_aff_form"] for f in rows if (f.get("capa_fin"), f.get("acc_pc")) != sql.get(f["cod_aff_form"])]
    # crafted rows every warehouse may lack: no admit, admits, unknown; capacity and rate on each boundary
    rows = rows + [{"cod_aff_form": f"X{i}", "capa_fin": cap, "acc_pc": pc, "taux_acces_ens": t, "statut": "public", "initiale": True}
                   for i, (cap, pc, t) in enumerate([(19, 0, 29.9), (20, 2, 30), (50, None, 90), (100, 0, None), (None, 1, 60)])]
    js = c.js
    parts = [top(js, n) for n in ("fiOptions", "filtreBand", "CARTE_R3", "CARTE_FGROUPS", "carteFolded", "carteHas", "carteText", "carteCommon",
                                 "carteFilter", "carteInLieu", "foldText")]
    prog = "const carteZone = () => 'autre'; const haversineKm = () => 0;\n" + "\n".join(parts) + MAP_PROG
    exe = shutil.which("node")
    if not exe:
        return not bad, f"payload {len(bad)} rows differ; node not installed"
    r = subprocess.run([exe, "-e", prog], input=json.dumps(rows, default=str), capture_output=True, text=True, timeout=120,
                       env={**os.environ, "VOCAB": json.dumps(c.FI.vocab())})
    if r.returncode:
        return False, "__error__ " + r.stderr[-600:]
    got = json.loads(r.stdout)
    want = {}
    for k, lo, hi in [(b[0], b[2], b[3]) for b in FI0.CAPACITE]:
        want["capacite:" + k] = [f["cod_aff_form"] for f in rows if f.get("capa_fin") is not None and (lo is None or f["capa_fin"] >= lo) and (hi is None or f["capa_fin"] < hi)]
    for k, lo, hi in [(b[0], b[2], b[3]) for b in FI0.TAUX]:
        want["taux:" + k] = [f["cod_aff_form"] for f in rows if f.get("taux_acces_ens") is not None and (lo is None or f["taux_acces_ens"] >= lo) and (hi is None or f["taux_acces_ens"] < hi)]
    want["complementaire:oui"] = [f["cod_aff_form"] for f in rows if (f.get("acc_pc") or 0) > 0]
    want["complementaire:non"] = [f["cod_aff_form"] for f in rows if f.get("acc_pc") == 0]
    diff = [k for k in want if got.get(k) != want[k]]
    groups = "carteGroups()" in js and 'const CARTE_R3 = ["capacite", "complementaire", "taux"];' in js
    ok = not bad and not diff and groups
    return ok, f"{len(rows)} BTS rows; payload differs {len(bad)}; filter differs {diff[:3]}; groups drawn {groups}"


@check("FI6 the map: capacity and complementary admits as in the warehouse; the page's filter keeps what a Python filter keeps")
def fi6(c: Ctx):
    return map_ok(c)


# ------------------------------------------------------------------ FI7 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2];
const PROF = { serie: 'bg', spe1: 'MATHS', spe2: 'NSI', mention: 'b', statut: 'terminale' };
(async () => {
  const b = await chromium.launch(); const errs = []; const o = {};
  for (const [name, opts] of [['wide', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
    const c = await b.newContext(opts); await c.addInitScript((p) => localStorage.setItem('profile', JSON.stringify(p)), PROF);
    const p = await c.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    await p.goto(base + '/#/s/informatique'); await p.waitForTimeout(9000);
    await p.$eval('details.dd[data-dd="zones"] > summary', (s) => s.click()); await p.waitForTimeout(400);
    const chipTxt = await p.$eval('details.dd[data-dd="zones"] input[data-o="securite"]', (i) => i.closest('label').textContent);
    await p.$eval('details.dd[data-dd="zones"] input[data-o="securite"]', (i) => i.click()); await p.waitForTimeout(2500);
    o[name] = await p.evaluate(() => ({ hash: location.hash, q: document.getElementById('cs-q').value, total: document.getElementById('carte-count').textContent,
      pills: document.querySelectorAll('#carte-items .zone-pill, #carte-items .zbadge').length, hs: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
    o[name].chip = chipTxt;
    o[name].mapGroups = await p.evaluate(() => [...document.querySelectorAll('#cfilters details.dd > summary')].map((l) => l.textContent));
    o[name].hsMap = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    await c.close();
  }
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


@check("FI7 browser: the zone chip filters the list to its own count; the map shows the new groups; no error; no scroll")
def fi7(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".filtres_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    d = json.loads(r.stdout)
    bad = []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    for k, v in d["o"].items():
        n = re.search(r"(\d[\d\s ]*)\s*$", v["chip"])
        tot = re.search(r"^(\d[\d\s ]*)", v["total"])
        if v["hash"] != "#/carte" or v["q"] != "informatique" or not n or not tot or re.sub(r"\D", "", n.group(1)) != re.sub(r"\D", "", tot.group(1)) or not v["pills"]:
            bad.append((k, "zone option", v))
        if not all(any(g in x for x in v["mapGroups"]) for g in ("Capacité", "Phase complémentaire", "Taux d'accès officiel")):
            bad.append((k, "map groups", v["mapGroups"]))
        if v["hs"] or v["hsMap"]:
            bad.append((k, "horizontal scroll"))
    return not bad, f"{len(bad)} problems {bad[:2]}; {d['o']}"


# ------------------------------------------------------------------ FI8 mutation test
PY_MUTANTS = [
    ("capacity upper limit included", "        if (lo is None or value >= lo) and (hi is None or value < hi):",
     "        if (lo is None or value >= lo) and (hi is None or value <= hi):", ("fi1",)),
    ("a zone reader back in the module", "def band(value, bands) -> str | None:",
     "def zones(con, results):\n    return {}\n\n\ndef band(value, bands) -> str | None:", ("fi2",)),
    ("the module sorts the bands", "    for key, _, lo, hi in bands:", "    for key, _, lo, hi in sorted(bands, key=lambda b: b[0]):", ("fi1", "fi2")),
]
API_MUTANTS = [
    ("a profile parameter back on /api/search", "           offset: int = Query(0, ge=0, le=20_000), limit: int = Query(40, ge=1, le=200)):",
     "           offset: int = Query(0, ge=0, le=20_000), limit: int = Query(40, ge=1, le=200), zone: str | None = None):", ("fi2",)),
]
JS_MUTANTS = [
    ("page band upper limit included", "(x.max === null || x.max === undefined || v < x.max)", "(x.max === null || x.max === undefined || v <= x.max)", ("fi1", "fi6")),
    ("map complementary phase from candidates", '(o === "oui" ? f.acc_pc > 0 : f.acc_pc === 0)', '(o === "oui" ? f.acc_pc >= 0 : f.acc_pc === 0)', ("fi6",)),
    ("map ignores the new groups", 'const CARTE_FGROUPS = ["statut", "acad", "app", "internat", "amenag", "select", "zones", ...CARTE_R3, "robf", "robn"];',
     'const CARTE_FGROUPS = ["statut", "app", "internat", "amenag", "select", "zones"];', ("fi6",)),
    ("profile sent with the keyword", 'if (near) qs.set("near", near); return qs; };', 'if (near) qs.set("near", near); new URLSearchParams(sq).forEach((v, k) => qs.set(k, v)); return qs; };', ("fi3",)),
    ("the list sorted by capacity", '|| byName(a, b));', "|| (b.capa_fin ?? 0) - (a.capa_fin ?? 0));", ("fi4",)),
    ("no help text", '  complementaire: "Des admis en phase complémentaire lors de la campagne de la formation : pas une promesse de places cette année.",',
     '  complementaire: "Des places en phase complémentaire.",', ("fi5",)),
    ("zone group shown without a profile", '    const zones = ok ? dd("zones"', '    const zones = true ? dd("zones"', ("fi5",)),
    ("help texts not in the dropdowns", '${FI_HELP[gr] ? `<p class="muted small">${esc(FI_HELP[gr])}</p>` : ""}', "", ("fi5",)),
    ("a shared group left out of the dropdowns", "...CARTE_GROUPS.slice(1),\n  ...CARTE_R3.map(", "...CARTE_GROUPS.slice(1),\n  ...CARTE_R3.slice(1).map(", ("fi5",)),
]


@check("FI8 mutation test: bands, facets, zones, status, order, privacy and page bugs are each caught")
def fi8(c: Ctx):
    fns = {"fi1": fi1, "fi2": fi2, "fi3": fi3, "fi4": fi4,
           "fi5": fi5, "fi6": fi6}
    base = {k: f(c)[0] for k, f in fns.items()}
    if not all(base.values()):
        return False, f"baseline fails: {[k for k, v in base.items() if not v]}"
    missed, n = [], 0
    for name, old, new, which in PY_MUTANTS:
        if not which:
            continue
        if old not in SRC:
            missed.append(f"{name} (anchor gone)"); continue
        m = Ctx.__new__(Ctx); m.__dict__.update(c.__dict__)
        m.FI = load_module(SRC.replace(old, new, 1)); m.src = SRC.replace(old, new, 1)
        n += 1
        if all(fns[w](m)[0] for w in which):
            missed.append(name)
    for name, old, new, which in API_MUTANTS:
        if old not in c.api:
            missed.append(f"{name} (anchor gone)"); continue
        m = Ctx.__new__(Ctx); m.__dict__.update(c.__dict__)
        m.api = c.api.replace(old, new, 1)
        n += 1
        if all(fns[w](m)[0] for w in which):
            missed.append(name)
    for name, old, new, which in JS_MUTANTS:
        if not which:
            continue
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        m = Ctx.__new__(Ctx); m.__dict__.update(c.__dict__)
        m.js = c.js.replace(old, new, 1)
        n += 1
        if all(fns[w](m)[0] for w in which):
            missed.append(name)
    return not missed, f"{n - len(missed)}/{n} mutants caught; missed {missed}"


@check("FI9 wording and docs: the method says admits not places, never chances; cache policy; README and CLAUDE.md")
def fi9(c: Ctx):
    bad = []
    if "pas une promesse de places" not in c.js or "Admis of a past campaign" not in SRC.replace("Admits\n  of a past campaign", "Admis of a past campaign") \
            and "never places left this year" not in SRC:
        bad.append("the complementary phase is not said to be past admits")
    if '(r"/api/search", NO_STORE' not in c.cache:
        bad.append("search policy")
    if c.readme and "Sprint R3" not in c.readme:
        bad.append("README")
    if c.claude and "Advanced filters (sprint R3" not in c.claude:
        bad.append("CLAUDE.md")
    return not bad, f"{len(bad)} problems {bad}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
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
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
