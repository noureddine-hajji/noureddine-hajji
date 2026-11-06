"""Red team of sprint 12, "Du métier aux formations" (and its upkeep).

    python scripts/redteam_metiers.py [--db data/suptracker.duckdb] [--real]

  M1 the Onisep jobs XML is re-read independently: EVERY ROME code of a job and every search label (masculine,
     feminine, synonyms) are stored as published
  M2 a job page is re-derived from the raw XML links and the latest campaign: same diplomas, same formations,
     same access flag (job minimum level vs the diploma level read from its own sheet)
  M3 the two pages agree both ways: every formation a job page lists shows that job, with the same flag, on its own
     jobs card; every job on a formation's card lists that formation
  M4 search (the page's own JavaScript, run with Node): accents, case, feminine forms and synonyms find the job;
     hostile queries do not crash; the catalogue covers every job
  M5 API: the catalogue takes no parameter (a query never reaches the server), public cache on both routes,
     malformed and unknown ids refused, no audience event
  M6 page: escaped strings, external links noopener, national-list / no-promise / no-ranking / privacy wording,
     ODbL credit, navigation race guarded, the formation the student came from always shown, wiring
  M7 upkeep: data/sources stays out of the Vercel bundle; the source register accepts no unregistered file
  M8 mutation test
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import metiers as MT  # noqa: E402
from suptracker import onisep as ON  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def rfold(s):
    return " ".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()))


def rrank(label):
    t = rfold(label)
    if re.fullmatch(r"bac \d+( et plus)?", t):
        return int(t.split()[1])
    if t.startswith("bac ou") or t == "bac":
        return 0
    if t.startswith("cap") or t.startswith("bep"):
        return -1
    if t in ("3e", "sans diplome", "diplome national du brevet"):
        return -2
    return None


def rxml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".xml")][0]))


class Ctx:
    def __init__(self, db: Path, real: bool, sources: dict | None = None):
        self.db, self.real = db, real
        self.sources = ON.find_sources() if sources is None else sources
        self.con = duckdb.connect(str(db), read_only=True)
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        fr, mr = rxml(self.sources["formations"]), rxml(self.sources["metiers"])
        self.sheet = {f.findtext("identifiant"): (f.findtext("libelle_complet"), f.findtext("niveau_etudes/libelle")) for f in fr}
        self.sheets_of = {}
        for f in fr:
            for m in f.findall("metiers_formation/metier"):
                self.sheets_of.setdefault(m.findtext("id"), set()).add(f.findtext("identifiant"))
        self.job = {}
        for m in mr:
            labels = set()
            for node in [m] + m.findall("synonymes/synonyme"):
                for tag in ("nom_metier", "libelle_masculin", "libelle_feminin"):
                    if (node.findtext(tag) or "").strip():
                        labels.add(node.findtext(tag).strip())
            self.job[m.findtext("identifiant")] = {
                "nom": m.findtext("nom_metier"), "niveau": m.findtext("niveau_acces_min/libelle"),
                "romes": {x.text.strip() for x in m.findall("romesV3/romeV3") if x.text and x.text.strip()}, "labels": labels}
        # Parcoursup formations of the latest campaign by sheet, from the stored link (the link itself is red team O2's)
        self.forms_of = {}
        for fid, cod, fili in self.con.execute("SELECT for_id, cod_aff_form, fili FROM core.onisep_link WHERE for_id IS NOT NULL").fetchall():
            self.forms_of.setdefault(fid, {})[cod] = fili
        rng = random.Random(12)
        ids = sorted(self.job)
        with_forms = [j for j in ids if any(self.forms_of.get(f) for f in self.sheets_of.get(j, ()))]
        self.sample = sorted(set(rng.sample(with_forms, min(len(with_forms), 60 if real else len(with_forms)))
                                 + rng.sample(ids, min(len(ids), 40 if real else len(ids)))))

    def ref_level(self, fids, fili):
        ranks = [r for r in (rrank(self.sheet[f][1]) for f in fids if f in self.sheet) if r is not None]
        return min(ranks) if ranks else {"BTS": 2, "BUT": 3, "Licence": 3, "Licence_Las": 3, "IFSI": 3, "EFTS": 3}.get(fili)


# ---------------------------------------------------------------- checks
@check("M1 every ROME code and every search label of a job (masculine, feminine, synonyms) is stored as published")
def m1(c: Ctx):
    romes, labels = {}, {}
    for mid, r in c.con.execute("SELECT met_id, rome FROM core.onisep_metier_rome").fetchall():
        romes.setdefault(mid, set()).add(r)
    for mid, lab in c.con.execute("SELECT met_id, libelle FROM core.onisep_metier_libelle").fetchall():
        labels.setdefault(mid, set()).add(lab)
    bad_r = [m for m, j in c.job.items() if j["romes"] != romes.get(m, set())]
    bad_l = [m for m, j in c.job.items() if j["labels"] != labels.get(m, set())]
    multi = sum(1 for j in c.job.values() if len(j["romes"]) > 1)
    first = [m for m, r in c.con.execute("SELECT met_id, rome FROM core.onisep_metier WHERE rome IS NOT NULL").fetchall()
             if r not in c.job.get(m, {}).get("romes", set())]
    return not bad_r and not bad_l and not first, (f"{len(c.job)} jobs, {multi} with several ROME codes; ROME differ {bad_r[:3]}; "
                                                   f"labels differ {bad_l[:3]}; first ROME not among the job's {first[:3]}")


@check("M2 a job page re-derived from the raw links: same diplomas, formations and access flag")
def m2(c: Ctx):
    bad, n = [], 0
    for mid in c.sample:
        d = MT.detail(c.con, mid)
        n += 1
        fids = c.sheets_of.get(mid, set())
        if {x["id"] for x in d["diplomes"]} != fids:
            bad.append((mid, "diplomas"))
            continue
        rank = rrank(c.job[mid]["niveau"])
        for x in d["diplomes"]:
            want = set(c.forms_of.get(x["id"], {}))
            if {f["cod_aff_form"] for f in x["formations"]} != want:
                bad.append((mid, x["id"], "formations"))
            fili = next(iter(c.forms_of.get(x["id"], {}).values()), None)
            lvl = c.ref_level([x["id"]], fili)
            exp = None if rank is None or lvl is None else "direct" if rank <= lvl else "poursuite"
            if x["acces"] != exp:
                bad.append((mid, x["id"], x["acces"], exp))
        n_form = len({f for x in d["diplomes"] for f in c.forms_of.get(x["id"], {})})
        status = "ok" if n_form else "hors_parcoursup" if fids else "sans_diplome"
        if d["status"] != status or d["n_formations"] != n_form or d["session"] != c.latest:
            bad.append((mid, "status", d["status"], status))
        keys = [(x["niveau_rang"] if x["niveau_rang"] is not None else 99) for x in d["diplomes"]]
        if keys != sorted(keys):
            bad.append((mid, "order by level"))
    # witnesses, true on any data: a diploma whose sheet says bac+3 is bac+3 even in a filière usually at bac+2 (3-year
    # BTS); a CAP is below the bac (rank -1), never "unknown" (Codex: CAP métiers de la mode lost their flag and order)
    if ON.sheet_level(["bac + 3"], "BTS") != 3 or ON.sheet_level(["CAP ou équivalent"]) != -1:
        bad.append(("witness", "sheet level"))
    return not bad and n > 0, f"{n} job pages, {len(bad)} wrong {bad[:3]}"


@check("M3 both pages agree both ways: job page ↔ formation jobs card (same job, same formation, same flag)")
def m3(c: Ctx):
    bad, n = [], 0
    rng = random.Random(3)
    for mid in c.sample[: (40 if c.real else len(c.sample))]:
        d = MT.detail(c.con, mid)
        for x in d["diplomes"]:
            for f in rng.sample(x["formations"], min(len(x["formations"]), 3)):
                n += 1
                card = ON.for_formation(c.con, f["cod_aff_form"])
                job = next((j for j in (card or {}).get("metiers", []) if j["id"] == mid), None)
                # the card reads the level of ALL its sheets (options); the job page reads this sheet's: agree on one-level options
                if job is None:
                    bad.append((mid, f["cod_aff_form"], "job missing on the card"))
                elif job["acces"] != x["acces"] and len({rrank(c.sheet[y["id"]][1]) for y in card["diplomes"]}) == 1:
                    bad.append((mid, f["cod_aff_form"], job["acces"], x["acces"]))
    cods = [r[0] for r in c.con.execute("SELECT DISTINCT cod_aff_form FROM core.onisep_link WHERE for_id IS NOT NULL ORDER BY 1").fetchall()]
    for cod in random.Random(4).sample(cods, min(len(cods), 25 if c.real else len(cods))):
        card = ON.for_formation(c.con, cod)
        for j in random.Random(cod).sample(card["metiers"], min(len(card["metiers"]), 3)):
            n += 1
            d = MT.detail(c.con, j["id"])
            if d is None or cod not in {f["cod_aff_form"] for x in d["diplomes"] for f in x["formations"]}:
                bad.append((cod, j["id"], "formation missing on the job page"))
    return not bad and n > 0, f"{n} pairs checked both ways, {len(bad)} disagree {bad[:3]}"


def run_node(js_src: str, payload: dict) -> dict | None:
    node = shutil.which("node")
    if not node:
        return None
    a, b = js_src.index("const mfold"), js_src.index("let METIERS")
    prog = js_src[a:b] + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + r"""
const out = {};
for (const q of P.queries) {
  out[q] = P.rows.map((r) => [metierMatch(q, r[1], r[2]), r[0]]).filter(([s]) => s > 0)
    .sort((x, y) => y[0] - x[0]).slice(0, 10).map((x) => x[1]);
}
process.stdout.write(JSON.stringify(out));"""
    r = subprocess.run([node, "-e", prog], input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"__error__": r.stderr[-300:]}
    return json.loads(r.stdout)


SEARCH_TRUTH = [  # (query, a label the top results must contain, folded)
    ("infirmière", "infirmier"), ("INFIRMIER", "infirmier"), ("comptable", "comptable"), ("développeur web", "developpeur"),
    ("developpeur", "developpeur"), ("aide soignante", "aide soignant"), ("gestionnaire de paie", None), ("électricien", "electricien"),
    # typed without accents, as on a phone
    ("infirmiere", "infirmier"), ("electricien", "electricien"), ("ingenieur securite", "ingenieur"), ("educatrice specialisee", "educat"),
]
HOSTILE = ["", " ", "(", "[a-z]+", "\\", "' OR 1=1 --", "<script>", "a" * 500, "é" * 30]


def search_ok(js: str, c: Ctx) -> tuple[bool, str]:
    cat = MT.catalogue(c.con)
    rows = [[r[0], r[1], r[5]] for r in cat["rows"]]
    pairs = [("infirmière", "infirmiere"), ("électricien", "electricien"), ("éducatrice spécialisée", "educatrice specialisee"),
             ("ingénieur sécurité", "ingenieur securite"), ("Développeur", "developpeur")]
    res = run_node(js, {"rows": rows, "queries": [q for q, _ in SEARCH_TRUTH] + HOSTILE + ["zzqx comptable"] + [x for p in pairs for x in p]})
    if res is None:
        return True, "node not installed: search not exercised"
    if "__error__" in res:
        return False, f"search crashed: {res['__error__']}"
    names = {r[0]: rfold(r[1]) + " " + " ".join(rfold(x) for x in r[2]) for r in rows}
    miss = []
    for q, want in SEARCH_TRUTH:
        top = res.get(q, [])
        if c.real and (not top or (want and not any(want in names[i] for i in top))):
            miss.append(q)
    noisy = [q for q in HOSTILE[:2] if res.get(q)]
    # accents and case never change the answer
    miss += [f"{a} ≠ {b}" for a, b in pairs if res.get(a) != res.get(b)]
    # a close match never outranks a full one: "zzqx comptable" (no job has both) still lists "comptable" jobs only
    if c.real and not any("comptable" in names[i] for i in res.get("zzqx comptable", [])[:3]):
        miss.append("close match")
    complete = len(cat["rows"]) == len(c.job)
    return not miss and not noisy and complete, f"truth queries missed {miss}; empty queries returning jobs {noisy}; catalogue covers every job {complete}"


@check("M4 search (the page's own JavaScript, run with Node): accents, case, feminine forms, synonyms; hostile queries")
def m4(c: Ctx):
    return search_ok(APP_JS.read_text(), c)


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    calls, saved = [], A.record
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


@check("M5 API: catalogue without parameter, public cache, malformed / unknown ids refused, no audience event")
def m5(c: Ctx):
    with client(c.db) as (cl, calls, api):
        route = next(r for r in api.app.routes if getattr(r, "path", "") == "/api/metiers")
        no_param = not [p for p in route.dependant.query_params]
        mid = c.sample[0]
        got = (cl.get("/api/metiers").status_code, cl.get(f"/api/metier/{mid}").status_code,
               cl.get("/api/metier/MET.99999999").status_code, cl.get("/api/metier/1 OR 1=1").status_code,
               cl.get("/api/metier/..%2F..%2Fetc").status_code, cl.get("/api/metier/MET.999999").status_code)
        cc = (cl.get("/api/metiers").headers.get("cache-control", ""), cl.get(f"/api/metier/{mid}").headers.get("cache-control", ""))
        n_calls = len(calls)
    ok = no_param and got[:2] == (200, 200) and got[2] == 422 and got[3] in (404, 422) and got[4] in (404, 422) and got[5] == 404 \
        and all("s-maxage" in x for x in cc) and n_calls == 0
    return ok, f"catalogue takes no parameter {no_param}; status {got}; cache {cc}; audience events {n_calls}"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 12: \"Du métier aux formations\"")
    # the block ends at the NEXT top-level section, not at the router: a later view sharing a line (the navigation
    # guard) must not stand in for this one (sprint 12: the "Métiers" block hid the "Mes vœux" race mutant)
    return js[i: js.index("\n// ---- ", i + 1)]


def ui(js: str) -> tuple[bool, str]:
    b = re.sub(r"(?m)^\s*//.*$", "", block(js))
    # a stored string printed as is: the whole interpolation is the field (or a fallback chain of fields)
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", b)
           if re.fullmatch(r"\s*(?:[xfdr]\.(?:libelle|nom|url|etablissement|filiere|complement|ville|academie|niveau|niveau_acces_min|cod_aff_form)"
                           r"|r\[[0-5]\])(?:\s*\|\|\s*\S+)?\s*", m)]
    blank = re.findall(r'target="_blank"(?! rel="noopener")', b)
    words = all(w in b for w in ("Liste nationale", "pas parce que ses étudiants exercent ce métier", "pas une promesse d'emploi",
                                 "pas par chances d'admission", "n'est pas envoyé au site", "licence ODbL", "après une poursuite d'études"))
    race = "if ($view.dataset.rendered !== marker) return;" in b and \
        ('$view.dataset.rendered = "metiers:loading";' in b and 'if ($view.dataset.rendered !== "metiers:loading") return;' in b)
    pinned = "const mine = x.formations.filter((f) => f.cod_aff_form === from);" in b and "40 + mine.length" in b
    wired = ('if (a === "metiers") return await viewMetiers(' in js and 'href="#/metiers/${esc(j.id)}/${esc(m.cod || "")}"' in js)
    # every browser-storage access is guarded: a privacy setting that blocks storage throws (Codex, sprint 12)
    unguarded = [ln.strip()[:60] for ln in b.splitlines() if re.search(r"\b(?:session|local)Storage\.", ln) and "try {" not in ln]
    ok = not raw and not blank and words and race and pinned and wired and not unguarded
    return ok, f"unescaped {raw[:3]}; links without noopener {len(blank)}; wording {words}; race guard {race}; came-from formation pinned {pinned}; wired {wired}; unguarded storage {unguarded}"


@check("M6 page: escaping, noopener, wording, credit, race guard, the formation the student came from always shown, wiring")
def m6(c: Ctx):
    from suptracker import analytics as A
    from suptracker.api import FEATURES, METHODOLOGY
    ok, d = ui(APP_JS.read_text())
    html = (ROOT / "suptracker" / "static" / "index.html").read_text()
    extra = 'href="#/metiers"' in html and "metiers" in A.ROUTES and "metier_formations" in FEATURES and "pas une promesse" in METHODOLOGY["metier_formations"]
    return ok and extra, d + f"; nav, analytics route, feature, method {extra}"


def _ignore_rx(pattern: str) -> re.Pattern | None:
    """One .vercelignore line as gitignore reads it. Vercel applies it to paths from the REPOSITORY root
    (its build log lists "/suptracker/scripts/..."), so a pattern with an inner slash is anchored there."""
    p = pattern.strip()
    if not p or p.startswith(("#", "!")):
        return None
    p = p.rstrip("/")
    anchored = "/" in p
    p = p.lstrip("/")
    rx = ""
    i = 0
    while i < len(p):
        if p.startswith("**/", i):
            rx += "(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            rx += ".*"
            i += 2
        elif p[i] == "*":
            rx += "[^/]*"
            i += 1
        elif p[i] == "?":
            rx += "[^/]"
            i += 1
        else:
            rx += re.escape(p[i])
            i += 1
    return re.compile(("^" if anchored else "^(?:.*/)?") + rx + "$")


def vercel_ignored(path: str, text: str) -> bool:
    """Whether Vercel drops `path` (from the repository root): the file or one of its folders matches a line."""
    rxs = [r for r in (_ignore_rx(x) for x in text.splitlines()) if r]
    parts = path.strip("/").split("/")
    return any(r.match("/".join(parts[:k])) for r in rxs for k in range(1, len(parts) + 1))


BUNDLE_OUT = ("data/sources", "data/probe")          # owner uploads and probes: never read when serving
BUNDLE_IN = ("data/suptracker.duckdb", "suptracker/api.py", "suptracker/static/app.js", "requirements.txt")


def deploy_ok(text: str) -> bool:
    """Every committed file of BUNDLE_OUT is dropped and the serving files are kept, read as Vercel reads it."""
    base = ROOT.name
    out = [f"{base}/{d}/{p.name}" for d in BUNDLE_OUT for p in (ROOT / d).glob("*") if p.is_file()]
    return bool(out) and all(vercel_ignored(f, text) for f in out) and not any(vercel_ignored(f"{base}/{f}", text) for f in BUNDLE_IN)


@check("M7 upkeep: data/sources stays out of the Vercel bundle; every committed source file is registered")
def m7(c: Ctx):
    import fnmatch

    from suptracker import sources as SRC
    vi = deploy_ok((ROOT / ".vercelignore").read_text())
    files = [p.name for p in (ROOT / "data" / "sources").glob("*") if p.is_file()]
    globs = [g for s in SRC.SOURCES if s["access"] == "owner_upload" for g in SRC.globs(s)]
    orphans = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in globs)]
    deposes = [s["key"] for s in SRC.SOURCES if s["status"] == "depose" and not (s.get("sprint") and s.get("role"))]
    return vi and not orphans and not deposes, f"data/sources excluded from Vercel {vi}; unregistered files {orphans[:3]}; deposited sources without sprint or role {deposes}"


UI_MUTANTS = [
    ("unescaped establishment", '<a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>', '<a href="#/f/${esc(f.cod_aff_form)}">${f.etablissement}</a>'),
    ("unescaped diploma label", '${esc(x.libelle)}</a></h2>', '${x.libelle}</a></h2>'),
    ("external link without noopener", '<h2><a href="${esc(x.url)}" target="_blank" rel="noopener">', '<h2><a href="${esc(x.url)}" target="_blank">'),
    ("national-list caveat dropped", "Liste nationale : un établissement figure parce qu'il prépare le diplôme, pas parce que ses étudiants exercent ce métier. ", ""),
    ("ranking caveat dropped", "Les formations sont rangées par académie et par ville, pas par chances d'admission.", ""),
    ("privacy note dropped", "La recherche se fait dans ton navigateur : ce que tu tapes n'est pas envoyé au site. ", ""),
    ("navigation race unguarded", "if ($view.dataset.rendered !== marker) return;", ""),
    ("stored query read unguarded", 'try { q0 = sessionStorage.getItem("metierQ") || ""; } catch (_) { /* storage blocked: start empty (Codex) */ }', 'q0 = sessionStorage.getItem("metierQ") || "";'),
    ("catalogue load race unguarded", 'if ($view.dataset.rendered !== "metiers:loading") return;', ""),
    ("came-from formation not pinned", "40 + mine.length", "40"),
    ("formation card no longer links the job page", 'href="#/metiers/${esc(j.id)}/${esc(m.cod || "")}"', 'href="#/metiers/${esc(j.id)}"'),
]
SEARCH_MUTANTS = [
    ("search keeps accents", 'normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")', 'normalize("NFC")'),
    ("search ignores synonyms and feminine forms", "[nom, ...(labels || [])].forEach", "[nom].forEach"),
    ("empty query matches everything", "if (!words.length) return 0;", "if (!words.length) return 1;"),
]


@check("M8 mutation test: link, flag, extras, level, search, API and page bugs are each caught")
def m8(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 12: \"Du métier aux formations\"")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        mut = js[:i] + js[i:j].replace(old, new, 1) + js[j:] if old in js[i:j] else js.replace(old, new, 1)
        if old not in js or ui(mut)[0]:
            missed.append(name)
    if c.real and shutil.which("node"):
        for name, old, new in SEARCH_MUTANTS:     # seeded in the sprint-12 block only (other views share some lines)
            if old not in js[i:j] or search_ok(js[:i] + js[i:j].replace(old, new, 1) + js[j:], c)[0]:
                missed.append(name)
    saved = {k: getattr(MT, k) for k in ("detail",)}
    saved_on = {k: getattr(ON, k) for k in ("sheet_level",)}
    orig = MT.detail

    def flag_inverted(con, mid):
        d = orig(con, mid)
        if d:
            for x in d["diplomes"]:
                x["acces"] = {"direct": "poursuite", "poursuite": "direct"}.get(x["acces"])
        return d

    def other_campaign(con, mid):
        d = orig(con, mid)
        if d:
            for x in d["diplomes"]:
                x["formations"] = x["formations"][1:]           # a formation lost (e.g. joined on another campaign)
        return d

    mutants = [
        ("access flag inverted", lambda: setattr(MT, "detail", flag_inverted), (m2, m3)),
        ("a formation dropped from the job page", lambda: setattr(MT, "detail", other_campaign), (m2, m3)),
        ("diploma level = the filière's, not the sheet's", lambda: setattr(ON, "sheet_level", lambda lv, fili=None: ON.LEVEL.get(fili, 3)), (m2,)),
    ]
    for name, apply, fns in mutants:
        try:
            apply()
            caught = any(not fn(c)[0] for fn in fns)
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(MT, k, v)
            for k, v in saved_on.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)
    vi = (ROOT / ".vercelignore").read_text()
    for name, text in [("data/sources back in the Vercel bundle", vi.replace("**/data/sources/", "")),
                       ("ignore rule anchored at suptracker/ (the PR #29 bundle overflow)", vi.replace("**/data/", "data/")),
                       ("whole data folder ignored (warehouse dropped)", vi + "\n**/data/\n")]:
        if deploy_ok(text):
            missed.append(name)
    n = len(UI_MUTANTS) + (len(SEARCH_MUTANTS) if c.real and shutil.which("node") else 0) + len(mutants) + 3
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, sources: dict | None = None) -> list[dict]:
    c = Ctx(db, real, sources)
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
