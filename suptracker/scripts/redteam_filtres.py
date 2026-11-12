"""Red team of sprint R3 (owner, 2026-11-12): the advanced filters shared by the search and the map.

    python scripts/redteam_filtres.py [--db data/suptracker.duckdb] [--real] [--browser]

  FI1 bands: capacity and official-rate bands are contiguous, never overlap, lower limit in / upper limit out; the page's
      filtreBand gives the same band as filtres.band on every boundary and a grid of values; the map cuts with the same bands
  FI2 the filtered search, re-derived: for queries of every size and filter combinations, the kept list (same relevance order),
      the total and every facet (each group counted with the other groups applied) equal an independent computation from the
      search's full results and the warehouse's own rows (capacity, complementary-phase admits, status, official rate, zones
      from the FULL type's stage-2 rows, not the `only=` call)
  FI3 privacy and validation: the audience event never carries the profile; /api/search stays no-store; a zone filter without a
      profile, an unknown key, two identical specialties are refused (422); the page sends a profile only in terminale
  FI4 never sorted by a figure: the filtered list is a subsequence of the plain search order; the module sorts nothing
  FI5 the page (Node): every group with its counts, labels escaped, the zone group asks for a profile (link to Mon profil) or for a
      narrower search above the limit; the help texts say "pas une promesse" / "pas vos chances"; zone pills escaped
  FI6 the map: the payload's capacity and complementary-phase admits equal the warehouse; the map's filter (Node, the page's own
      carteFilter) keeps, for each new option, the formations an independent Python filter keeps
  FI7 browser (--browser / --real): a profile, the zone chip filters the list to its own count; the map shows the new groups; 0 JS
      error; no horizontal scroll on a phone
  FI8 mutation test of FI1-FI6 (mutants built in memory: the module re-loaded from a mutated source, the page's script mutated)
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


# ------------------------------------------------------------------ FI2 the filtered search, re-derived
QUERIES = ["informatique", "licence droit", "BTS commerce", "kiné", "IUT informatique Toulouse", "paris"]
COMBOS = [{}, {"capacite": "20a49"}, {"capacite": "moins20,100plus", "statut": "public"}, {"complementaire": "oui"},
          {"complementaire": "non", "taux": "90plus"}, {"statut": "prive"}, {"taux": "moins30,30a59", "capacite": "50a99"},
          {"zone": "securite"}, {"zone": "cible,ambitieux", "complementaire": "oui"}, {"zone": "autre"}]
PROFILES = [{"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b"}, {"serie": "bt", "mention": "ab"},
            {"serie": "bg", "spe1": "SVT", "spe2": "PC", "mention": "tb"}]


def reference(c: Ctx, q: str, combo: dict, prof: dict | None, base: dict):
    """Independent: the search's full results; the warehouse's own rows; zones from the FULL type's stage-2 rows."""
    cur = c.con.cursor()
    full = S.search(cur, q, offset=0, limit=10 ** 6)["results"]
    if not hasattr(c, "_att"):
        c._att = {(a, s): (cap, pc, ct) for a, s, cap, pc, ct in cur.execute(
            "SELECT cod_aff_form, session, capa_fin, acc_pc, contrat_etab FROM core.formation_year").fetchall()}
        c._types = dict(cur.execute("""SELECT t.cod_aff_form, r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
                                       WHERE t.session = ?""", [c.latest]).fetchall())
        c._stage2 = {}
    att, types = c._att, c._types
    zone = None
    if prof:
        dkey = J.doublette_key(prof["spe1"], prof["spe2"]) if prof["serie"] == "bg" else None
        codes = {r["cod_aff_form"] for r in full if r["session"] == c.latest}
        zone = {}
        for tk in {types.get(x) for x in codes} - {None}:
            key = (tk, dkey, prof["mention"], prof["serie"])
            if key not in c._stage2:          # the FULL type (no `only`, no row limit): an independent reading of every zone
                c._stage2[key] = J.stage2(cur, dkey, prof["mention"], tk, None, limit=10 ** 6, serie=prof["serie"])["formations"]
            for f in c._stage2[key]:
                if f["cod_aff_form"] in codes:
                    zone[f["cod_aff_form"]] = f["zone"]

    def tag(r):
        cap, pc, ct = att.get((r["cod_aff_form"], r["session"]), (None, None, None))
        t = r.get("taux_acces_ens")
        st = None if not ct else ("public" if ct == "Public" else "prive" if ct in ("Privé enseignement supérieur", "Privé hors contrat") else "contrat")
        z = None
        if zone is not None:
            zz = zone.get(r["cod_aff_form"]) if r["session"] == c.latest else None
            z = zz if zz in ("securite", "cible", "ambitieux") else "autre"
        return {"capacite": None if cap is None else ("moins20" if cap < 20 else "20a49" if cap < 50 else "50a99" if cap < 100 else "100plus"),
                "taux": None if t is None else ("moins30" if t < 30 else "30a59" if t < 60 else "60a89" if t < 90 else "90plus"),
                "complementaire": None if pc is None else ("oui" if pc > 0 else "non"), "statut": st, "zone": z,
                "fili": r.get("fili"), "academie": r.get("acad_mies"), "selectivite": r.get("select_form")}
    rows = [(r, tag(r)) for r in full]
    act = {g: [x for x in combo.get(g, "").split(",") if x] for g in ("capacite", "complementaire", "statut", "taux", "zone")}
    act.update({g: [v] for g, v in base.items() if v})

    def ok(t, skip=None):
        return all(not v or t[g] in v for g, v in act.items() if g != skip)
    kept = [r["cod_aff_form"] + ":" + str(r["session"]) for r, t in rows if ok(t)]
    facets = {}
    for g in ("capacite", "complementaire", "statut", "taux", "zone", "fili", "academie", "selectivite"):
        cnt = {}
        for _, t in rows:
            if ok(t, skip=g) and t[g] is not None:
                cnt[t[g]] = cnt.get(t[g], 0) + 1
        facets[g] = cnt
    if zone is None:
        facets["zone"] = {}
    return kept, facets


def crafted(FI) -> list:
    """Cases every warehouse may lack: an older result sharing a code with a zoned one; a search filter; facets of each group."""
    bad = []
    zoned = {("A", 2025): ("securite", False, None, False)}
    if FI.tags({"cod_aff_form": "A", "session": 2023}, {}, zoned)["zone"] != "autre" or FI.tags({"cod_aff_form": "A", "session": 2025}, {}, zoned)["zone"] != "securite":
        bad.append("an older result takes the latest campaign's zone")
    r = lambda cod, sel, fili: {"cod_aff_form": cod, "session": 2025, "select_form": sel, "fili": fili, "acad_mies": "Lyon", "taux_acces_ens": 50}  # noqa: E731
    att = {("A", 2025): (10, 0, "Public"), ("B", 2025): (60, 3, "Public"), ("C", 2025): (60, 0, "Privé hors contrat")}
    rows = [{"r": r(k, sel, fi), "t": FI.tags(r(k, sel, fi), att, None)} for k, sel, fi in
            (("A", "formation sélective", "BTS"), ("B", "formation non sélective", "BTS"), ("C", "formation sélective", "BUT"))]
    kept, fac = FI.apply(rows, {"capacite": ("50a99",)}, {"fili": None, "academie": None, "selectivite": "formation sélective"})
    if [x["r"]["cod_aff_form"] for x in kept] != ["C"]:
        bad.append(("a search filter ignored", [x["r"]["cod_aff_form"] for x in kept]))
    if fac["capacite"] != {"moins20": 1, "50a99": 1} or fac["selectivite"] != {"formation sélective": 1, "formation non sélective": 1} \
            or fac["statut"] != {"prive": 1} or fac["complementaire"] != {"non": 1}:
        bad.append(("crafted facets", fac))
    return bad


def cache_by_average(c: Ctx) -> list:
    """R5: the zones read for an average are never the cached zones of the band's top (the cache key carries the average)."""
    cur = c.con.cursor()
    res = S.search(cur, "bts", limit=10 ** 6)["results"]
    top = c.FI.zones(cur, res, "bg", "MATHS+SES", "ab")               # the band's top, cached first
    low = c.FI.zones(cur, res, "bg", "MATHS+SES", "ab", 12.1)         # then the bottom of the same band
    return [] if low != top else ["the cache answers the band's zones for an average"]


def fi2_run(c: Ctx, quick: bool = False):
    bad, n = crafted(c.FI), 0
    bad += cache_by_average(c)
    with client(c) as tc:
        for qi, q in enumerate(QUERIES[: 3 if quick else None]):
            for ci, combo in enumerate(COMBOS):
                prof = PROFILES[(qi + ci) % len(PROFILES)] if "zone" in combo or ci % 3 == 0 else None
                if "zone" in combo and prof is None:
                    continue
                base = {"academie": None, "fili": None, "selectivite": None}
                params = {"q": q, "avance": "true", "limit": 200, **combo}
                if prof:
                    params.update(prof)
                if ci == 2:
                    base["selectivite"] = "formation sélective"
                    params["selective"] = "true"
                d = tc.get("/api/search", params=params).json()
                if "results" not in d:
                    bad.append(("error", q, combo, d)); continue
                kept, facets = reference(c, q, combo, prof, base)
                got = []
                off = 0
                while True:
                    got += [r["cod_aff_form"] + ":" + str(r["session"]) for r in d["results"]]
                    off += 200
                    if off >= d["total"] or quick:
                        break
                    d2 = tc.get("/api/search", params={**params, "offset": off}).json()
                    d = {**d, "results": d2["results"]}
                n += 1
                if d["total"] != len(kept) or got != kept[:len(got)]:
                    bad.append(("kept list", q, combo, prof and prof["serie"], d["total"], len(kept)))
                fac = d["facets"]
                for g in ("capacite", "complementaire", "statut", "taux", "zone"):
                    if dict(fac.get(g) or {}) != facets[g]:
                        bad.append(("facet", g, q, combo, fac.get(g), facets[g])); break
                for g in ("fili", "academie", "selectivite"):
                    if {x["value"]: x["count"] for x in fac.get(g) or []} != facets[g]:
                        bad.append(("facet", g, q, combo)); break
    return bad, n


def broad(c: Ctx) -> list:
    """Review: a broad search (thousands of results) with a zone filter keeps its formations; the cache answers the same zones."""
    bad = []
    q = "lycee" if c.real else "informatique"
    prof = PROFILES[0]
    with client(c) as tc:
        d = tc.get("/api/search", params={"q": q, "avance": "true", "zone": "securite", **prof}).json()
    kept, fac = reference(c, q, {"zone": "securite"}, prof, {"academie": None, "fili": None, "selectivite": None})
    if d.get("total") != len(kept) or (fac["zone"].get("securite") and not d.get("total")):
        bad.append(("broad search with a zone filter", q, d.get("total"), len(kept)))
    cur = c.con.cursor()
    res = S.search(cur, q, limit=10 ** 6)["results"]
    if c.FI.zones(cur, res, "bg", "MATHS+SES", "b") != c.FI.zones(cur, res, "bg", "MATHS+SES", "b"):
        bad.append("the cache answers other zones")
    src = SRC if c.FI is FI0 else getattr(c.FI, "__src__", "")
    if "duckdb_databases()" not in src or "key = (db, latest, serie, dkey, mention, moyenne, tk, tuple(sorted(cods)))" not in src or "limit=10 ** 6" not in src:
        bad.append("the cache key misses the warehouse or the profile, or a row limit cuts a type")
    return bad


@check("FI2 the filtered search re-derived: kept list, total and every facet (other groups applied), zones from the full type")
def fi2(c: Ctx):
    bad, n = fi2_run(c)
    bad += broad(c)
    return not bad and n >= 30, f"{n} searches; {len(bad)} problems {bad[:2]}"


# ------------------------------------------------------------------ FI3 privacy and validation
@check("FI3 privacy: no profile in the audience event, no-store, refused inputs, a profile sent only in terminale")
def fi3(c: Ctx):
    bad = []
    with client(c) as tc:
        prof = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "tb"}
        r = tc.get("/api/search", params={"q": "informatique", "avance": "true", "zone": "securite", **prof})
        ev = [e for e in tc.events if e and e[0] in ("search", "refine")]
        blob = json.dumps([e[1] for e in ev], default=str)
        if r.status_code != 200 or not ev or any(k in blob for k in ("MATHS", "SES", '"tb"', "serie", "spe1", "mention", "securite")):
            bad.append(("audience event carries the profile or the zone", blob[:200]))
        if "no-store" not in (r.headers.get("cache-control") or ""):
            bad.append(("search shared-cached", r.headers.get("cache-control")))
        for p, why in (({"q": "x", "zone": "securite"}, "zone without a profile"), ({"q": "x", "taux": "nope"}, "unknown key"),
                       ({"q": "x", "serie": "bg", "spe1": "ART", "spe2": "ART", "mention": "b"}, "identical specialties"),
                       ({"q": "x", "serie": "zz", "mention": "b"}, "unknown series")):
            if tc.get("/api/search", params=p).status_code != 422:
                bad.append(("accepted", why))
        tc.events.clear()
        tc.get("/api/search", params={"q": "informatique", "avance": "true", "capacite": "20a49"})
        if not tc.events or tc.events[0][0] != "refine":
            bad.append("an advanced filter is not counted as a refined search")
    fp = top(c.js, "fiProfileQuery")
    if "const p = bacProfile();" not in fp or "if (!p) return false;" not in fp:
        bad.append("the page may send a profile outside terminale")
    vs = c.js[c.js.index("async function viewSearch("):c.js.index("function stageCard(")]
    if 'if (!withProfile) { qs.delete("zone"); delete P.zone; }' not in vs or "track(" in vs:
        bad.append("search page wiring")
    return not bad, f"{len(bad)} problems {bad[:3]}"


# ------------------------------------------------------------------ FI4 order
@check("FI4 never sorted by a figure: the filtered list keeps the search's relevance order; the module sorts nothing")
def fi4(c: Ctx):
    bad = []
    with client(c) as tc:
        for q in ("informatique", "licence droit"):
            key = lambda r: f'{r["cod_aff_form"]}:{r["session"]}'  # noqa: E731
            plain = [key(r) for r in tc.get("/api/search", params={"q": q, "limit": 200}).json()["results"]]
            adv = [key(r) for r in tc.get("/api/search", params={"q": q, "limit": 200, "avance": "true", "complementaire": "oui"}).json()["results"]]
            it = iter(plain)
            if not all(x in it for x in adv if x in set(plain)):
                bad.append(("order changed", q))
    src = SRC if c.FI is FI0 else getattr(c.FI, "__src__", "")
    adv_src = c.api[c.api.index("def _search_advanced("):c.api.index("def _record(")]
    if re.search(r"\bsort(ed)?\(", src.split("def apply(")[1]) or re.search(r"sorted\(kept|\.sort\(", adv_src):
        bad.append("a sort in the filtering")
    return not bad, f"{len(bad)} problems {bad[:3]}"


# ------------------------------------------------------------------ FI5 the page (Node)
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
    js = c.js
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const isReo = ", "const REO_LABEL = ")))
    zones = re.search(r"^const ZONES = \{.*?^\};", js, re.M | re.S).group(0)
    bac = re.search(r"^function bacProfile\(\) \{.*?^\}", js, re.M | re.S).group(0)
    parts = [top(js, n) for n in ("FI_GROUPS", "FI_TITLE", "FI_HELP", "fiOptions", "filtreBand", "zoneShape", "ZONE_FILLED", "zoneMark", "zonePillHtml", "MENTION_CODES", "BANDS", "validMoyenne", "bandOf", "mentionParams", "vxProfile", "fiProfileQuery", "searchAdvanced")]
    prog = helpers + "\nconst JV = null;\n" + zones + "\n" + bac + "\n" + "\n".join(parts) + PAGE_PROG
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    r = subprocess.run([exe, "-e", prog], capture_output=True, text=True, timeout=60, env={**os.environ, "VOCAB": json.dumps(c.FI.vocab())})
    if r.returncode:
        return False, "__error__ " + r.stderr[-600:]
    o = json.loads(r.stdout)
    bad = []
    if not all(x in o["prof"] for x in ("Vœux de sécurité (3)", "Vœux cibles (5)", "Publics (7)", "Moins de 20 places (2)", "100 places et plus (1)",
                                          "A admis des candidats en phase complémentaire (4)", "90 % et plus (6)")):
        bad.append("a group or a count is missing")
    if 'badge exact" href="#/s/q/capacite=">Moins de 20 places' not in o["prof"].replace("&amp;", "&"):
        bad.append("a ticked option does not untick")
    plain = o["prof"].replace("&#39;", "'").replace("&#x27;", "'")
    if "pas une promesse" not in plain or "pas vos chances" not in plain or "rien n'est enregistré" not in plain:
        bad.append("help texts")
    if 'href="#/profil"' not in o["none"] or "Vœux de sécurité" in o["none"]:
        bad.append("zone group without a profile")
    if o["reoGroup"].strip():
        bad.append("outside terminale the zone group invites to create a profile (no zone exists there)")
    if "<img" in o["pill"] or "incertain" not in o["pill"] or "cible" not in o["pill"]:
        bad.append(("zone pill", o["pill"]))
    if o["reo"] != "" or o["same"] != "" or "serie=bt" not in o["bt"] or "spe1" in o["bt"]:
        bad.append(("profile sent", o["reo"], o["same"], o["bt"]))
    words = re.sub(r"<[^>]+>", " ", " ".join(v for v in o.values() if isinstance(v, str)))
    if CHANCE.search(words.replace("pas vos chances", "")) or FORMAL.search(words):
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
    parts = [top(js, n) for n in ("fiOptions", "filtreBand", "CARTE_R3", "carteHas", "carteFilter")]
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
    await p.goto(base + '/#/s/informatique'); await p.waitForTimeout(3500);
    const chipTxt = await p.$eval('.fi-group a.badge', (a) => a.textContent);
    await p.$eval('.fi-group a.badge', (a) => a.click()); await p.waitForTimeout(3000);
    o[name] = await p.evaluate(() => ({ hash: location.hash, total: document.querySelector('.card h2').textContent,
      pills: document.querySelectorAll('.result .zone-pill').length, hs: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
    o[name].chip = chipTxt;
    await p.goto(base + '/#/carte'); await p.waitForTimeout(3500);
    o[name].mapGroups = await p.evaluate(() => [...document.querySelectorAll('#cfilters legend')].map((l) => l.textContent));
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
        n = re.search(r"\((\d[\d\s ]*)\)", v["chip"])
        tot = re.search(r"^(\d[\d\s ]*)", v["total"])
        from urllib.parse import unquote
        if "zone=securite" not in unquote(v["hash"]) or not n or not tot or re.sub(r"\D", "", n.group(1)) != re.sub(r"\D", "", tot.group(1)) or not v["pills"]:
            bad.append((k, "zone chip", v))
        if not all(g in v["mapGroups"] for g in ("Capacité", "Phase complémentaire", "Taux d'accès officiel")):
            bad.append((k, "map groups", v["mapGroups"]))
        if v["hs"] or v["hsMap"]:
            bad.append((k, "horizontal scroll"))
    return not bad, f"{len(bad)} problems {bad[:2]}; {d['o']}"


# ------------------------------------------------------------------ FI8 mutation test
PY_MUTANTS = [
    ("capacity upper limit included", "        if (lo is None or value >= lo) and (hi is None or value < hi):",
     "        if (lo is None or value >= lo) and (hi is None or value <= hi):", ("fi1", "fi2")),
    ("complementary phase read from candidates", '"complementaire": None if pc is None else ("oui" if pc > 0 else "non")',
     '"complementaire": None if pc is None else ("oui" if pc >= 0 else "non")', ("fi2",)),
    ("facets counted with every group applied", "            if ok(x, skip=g) and x[\"t\"][g] is not None:",
     "            if ok(x) and x[\"t\"][g] is not None:", ("fi2",)),
    ("zones of an older campaign", "    z = zoned.get((r[\"cod_aff_form\"], r[\"session\"])) if zoned is not None else None",
     "    z = zoned.get((r[\"cod_aff_form\"], max(k[1] for k in zoned) if zoned else 0)) if zoned is not None else None", ("fi2",)),
    ("non-zone results dropped from 'autre'", '    zone = None if zoned is None else (z[0] if z and z[0] in ZONE_KEYS else "autre")',
     '    zone = None if zoned is None else (z[0] if z and z[0] in ZONE_KEYS else None)', ("fi2",)),
    ("a search filter ignored", '            if g != skip and v is not None and x["r"].get(src[g]) != v:',
     '            if False:', ("fi2",)),
    ("cache shared across profiles", "        key = (db, latest, serie, dkey, mention, moyenne, tk, tuple(sorted(cods)))",
     "        key = (db, latest, tk, tuple(sorted(cods)))", ("fi2",)),
    ("cache shared across averages (R5)", "        key = (db, latest, serie, dkey, mention, moyenne, tk, tuple(sorted(cods)))",
     "        key = (db, latest, serie, dkey, mention, tk, tuple(sorted(cods)))", ("fi2",)),
    ("sorted by capacity", "    kept = [x for x in rows if ok(x)]", "    kept = sorted([x for x in rows if ok(x)], key=lambda x: -(x['t']['_capa'] or 0))", ("fi2", "fi4")),
]
JS_MUTANTS = [
    ("page band upper limit included", "(x.max === null || x.max === undefined || v < x.max)", "(x.max === null || x.max === undefined || v <= x.max)", ("fi1", "fi6")),
    ("map complementary phase from candidates", '(o === "oui" ? f.acc_pc > 0 : f.acc_pc === 0)', '(o === "oui" ? f.acc_pc >= 0 : f.acc_pc === 0)', ("fi6",)),
    ("map ignores the new groups", '  const groups = ["statut", "app", "internat", "amenag", "select", "zones", ...CARTE_R3].filter',
     '  const groups = ["statut", "app", "internat", "amenag", "select", "zones"].filter', ("fi6",)),
    ("profile sent outside terminale", "  const p = bacProfile();\n  if (!p) return false;", "  const p = store.get(\"profile\", null);\n  if (!p) return false;", ("fi3", "fi5")),
    ("zone kept without a profile", '  if (!withProfile) { qs.delete("zone"); delete P.zone; }', "", ("fi3",)),
    ("zone chip left for a filter not applied", '  if (!withProfile) { qs.delete("zone"); delete P.zone; }', '  if (!withProfile) { qs.delete("zone"); }', ("fi3",)),
    ("profile invitation outside terminale", '      return isReo(store.get("profile", null)) ? ""', '      return false ? ""', ("fi5",)),
    ("no help text", '  complementaire: "Des admis en phase complémentaire lors de la campagne de la formation : pas une promesse de places cette année.",',
     '  complementaire: "Des places en phase complémentaire.",', ("fi5",)),
    ("zone group shown without a profile", '        : !bacProfile() ? `<p class="small"><span class="muted">${FI_TITLE.zone} :</span> <a href="#/profil">',
     '        : false ? `<p class="small"><span class="muted">${FI_TITLE.zone} :</span> <a href="#/profil">', ("fi5",)),
    ("untick broken", "(a.includes(k) ? a.filter((x) => x !== k) : [...a, k])", "[...a, k]", ("fi5",)),
]


@check("FI8 mutation test: bands, facets, zones, status, order, privacy and page bugs are each caught")
def fi8(c: Ctx):
    fns = {"fi1": fi1, "fi2": lambda m: (lambda b, n: (not b and n > 0, ""))(*fi2_run(m, quick=True)), "fi3": fi3, "fi4": fi4,
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
        m.FI = load_module(SRC.replace(old, new, 1)); m.FI.__src__ = SRC.replace(old, new, 1)
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
