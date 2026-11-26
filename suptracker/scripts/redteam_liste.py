"""Red team of sprint 5 (owner, 2026-11-21): « Vérifier et confirmer ma liste » (calendrier.regles, liste.py, the Mes vœux card
« Avant de confirmer sur Parcoursup »).

    python scripts/redteam_liste.py [--db data/suptracker.duckdb] [--real]

  LI1 the rules of the list, read on the OFFICIAL calendar: an independent reading of every saved version (own words, no folding
      helper) gives 10 vœux, 10 more in apprenticeship, sous-vœux printed, apprenticeship vœux possible after the confirmation day;
      a version that prints another number, or none, leaves the rule unknown (None), never a typed default.
  LI2 the facts per vœu: an independent re-derivation (own SQL, own concours words) on crafted rows and, --real, on 400 latest-
      campaign codes: in the latest map of formations or not, the concours named (« Préparation aux concours » is not one), an
      apprenticeship row; an unknown code is said unknown; the list's order is kept.
  LI3 the route: 200 / 422 (a letter, 11 codes) ; never shared-cached (no-store), records no audience event; in cache.py.
  LI4 the card (Node): each check with its status in words (Fait / À vérifier / À savoir), every stored string escaped, the dates
      as the calendar prints them (« 1er »), « date à vérifier » when the calendar is unknown, the number of vœux only from the
      calendar, no « liste valide », no chance, vouvoiement, the drafts counted from this browser only, the safety line only from
      the list's own reading.
  LI5 the page: a placeholder in both Mes vœux views, filled by one request per list (codes only) and the shared calendar; a list
      the student left or changed is never drawn over; a failed check removes the placeholder; a failed calendar still shows it.
  LI6 docs and wiring: README, CLAUDE.md, durations.json, the release table, FEATURES.
  LI7 mutation test of LI1-LI6 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unicodedata
from pathlib import Path

import duckdb
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
BAN = re.compile(r"(?i)liste (?:est )?valide|vos chances|probabilit|garanti|vous serez admis")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_rt")
    m.__package__ = "suptracker"
    m.__file__ = str(ROOT / "suptracker" / f"{name}.py")
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text() for k in ("calendrier", "liste", "api", "cache")}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self, k):
        return load(k, self.src[k])


# ------------------------------------------------------------------ LI1 rules
def rt_rules(text: str) -> dict:
    t = unicodedata.normalize("NFC", text).replace("’", "'")
    t = re.sub(r"\s+", " ", t)
    a = re.search(r"jusqu'à (\d+) vœux sans obligation", t)
    b = re.search(r"ajouter (\d+) vœux supplémentaires.{0,60}?pour des formations en apprentissage", t)
    return {"voeux_max": int(a.group(1)) if a else None, "apprentissage_max": int(b.group(1)) if b else None,
            "sous_voeux": True if re.search(r"vous pouvez également faire des sous-vœux", t) else None,
            "apprentissage_apres": True if re.search(r"apprentissage, vous pouvez toujours formuler des vœux après", t) else None}


def _with_versions(texts: list[str]):
    d = Path(tempfile.mkdtemp())
    log = []
    for i, t in enumerate(texts):
        f = f"v{i}.pdf"
        (d / f"{f}.txt").write_text(t)
        log.append({"url": f"https://www.parcoursup.gouv.fr/{f}", "status": 200, "file": f, "fetched": "2026-11-21T00:00:00",
                    "sha256": str(i)})
    (d / "fetch_log.json").write_text(json.dumps(log))
    return d


@check("LI1 rules of the list from the official calendar: independent reading, every version agrees, else unknown")
def li1(c: Ctx):
    C = c.mod("calendrier")
    bad = []
    vs = C.versions()
    if not vs:
        return False, "no saved calendar version"
    mine = [rt_rules(v["text"]) for v in vs]
    got = C.regles()
    want = {k: (mine[0][k] if all(m[k] == mine[0][k] for m in mine) else None) for k in mine[0]}
    if got != want or got != {"voeux_max": 10, "apprentissage_max": 10, "sous_voeux": True, "apprentissage_apres": True}:
        bad.append(f"read {got}, independent {want}")
    base = vs[0]["text"]
    other = base.replace("jusqu’à 10 vœux", "jusqu’à 12 vœux").replace("jusqu'à 10 vœux", "jusqu'à 12 vœux")
    none = re.sub(r"Formulez vos vœux[^\n]*", "", base)
    for texts, key, label in (([base, other], "voeux_max", "two versions disagree"), ([none], "voeux_max", "sentence missing")):
        d = _with_versions(texts)
        r = C.regles(d)
        shutil.rmtree(d, ignore_errors=True)
        if r[key] is not None:
            bad.append(f"{label}: {key} = {r[key]}")
    if "regles" not in C.calendar():
        bad.append("the served calendar has no rules")
    return not bad, f"{len(vs)} versions; {bad[:3]}"


# ------------------------------------------------------------------ LI2 facts
NAMED = (("Concours Puissance Alpha", r"concours puissance alpha"), ("Concours Avenir", r"concours avenir"),
         ("Concours Geipi Polytech", r"concours geipi polytech"), ("Concours SESAME", r"concours sesame"),
         ("Concours Advance", r"concours advance"), ("Concours ACCÈS", r"concours acces"))


def rt_concours(labels: str) -> str | None:
    t = "".join(ch for ch in unicodedata.normalize("NFD", (labels or "").lower()) if unicodedata.category(ch) != "Mn")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    for name, pat in NAMED:
        if re.search(rf"\b{pat}\b", t):
            return name
    return "Concours commun" if re.search(r"\bconcours communs?\b", t) else None


def _crafted():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, lib_for_voe_ins VARCHAR,
        lib_comp_voe_ins VARCHAR, detail_forma VARCHAR, apprentissage BOOLEAN)""")
    con.execute("""INSERT INTO core.formation_year VALUES
        (2024, '11', 'Formation d''ingénieur', 'Concours Puissance Alpha', NULL, FALSE),
        (2025, '11', 'Formation d''ingénieur', NULL, NULL, FALSE),
        (2025, '22', 'Licence - Histoire - Parcours Préparation aux concours d''entrée des I.E.P.', NULL, NULL, FALSE),
        (2025, '33', 'BTS - Services', NULL, NULL, TRUE),
        (2025, '44', 'Ecole de commerce', 'Concours SESAME', 'concours commun', FALSE),
        (2025, '55', 'Ecole', 'Recrutement sur concours commun', NULL, FALSE)""")
    con.execute("CREATE TABLE core.cartographie (cod_aff_form VARCHAR, carto_session INTEGER)")
    con.execute("INSERT INTO core.cartographie VALUES ('11', 2026), ('22', 2025), ('33', 2026), ('44', 2026), ('55', 2026)")
    return con


@check("LI2 facts per vœu: independent re-derivation (map of formations, named concours, apprenticeship), unknown code said, order kept")
def li2(c: Ctx):
    L = c.mod("liste")
    bad = []
    con = _crafted()
    got = L.verifier(con, ["55", "22", "11", "999", "33", "44"])
    want = [("55", True, True, "Concours commun", False), ("22", True, False, None, False), ("11", True, True, None, False),
            ("999", False, False, None, False), ("33", True, True, None, True), ("44", True, True, "Concours SESAME", False)]
    rows = [(v["cod_aff_form"], v["connu"], v["dans_carte"], v["concours"], v["apprentissage"]) for v in got["voeux"]]
    if rows != want or got["carte_session"] != 2026 or got["session"] != 2025:
        bad.append(f"crafted: {rows}")
    n = 0
    if c.real:
        rc = duckdb.connect(str(c.db), read_only=True)
        latest = rc.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        cs = rc.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0]
        carte = {r[0] for r in rc.execute("SELECT cod_aff_form FROM core.cartographie WHERE carto_session = ?", [cs]).fetchall()}
        sample = rc.execute("""SELECT cod_aff_form, concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma), apprentissage
            FROM core.formation_year WHERE session = ? ORDER BY hash(cod_aff_form) LIMIT 400""", [latest]).fetchall()
        named = rc.execute("""SELECT cod_aff_form, concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma), apprentissage
            FROM core.formation_year WHERE session = ? AND lower(concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma))
            LIKE '%concours%' LIMIT 200""", [latest]).fetchall()
        for i in range(0, len(sample + named), 10):
            chunk = (sample + named)[i:i + 10]
            res = L.verifier(rc, [r[0] for r in chunk])["voeux"]
            for r, v in zip(chunk, res):
                exp = (r[0], True, r[0] in carte, rt_concours(r[1]), bool(r[2]))
                if (v["cod_aff_form"], v["connu"], v["dans_carte"], v["concours"], v["apprentissage"]) != exp:
                    bad.append(f"{r[0]}: {v} != {exp}")
                n += 1
        rc.close()
    return not bad, f"6 crafted, {n} real codes re-derived; {bad[:3]}"


# ------------------------------------------------------------------ LI3 route
@check("LI3 route: 200 / 422, never shared-cached, no audience event, a cache policy")
def li3(c: Ctx):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    bad = []
    if not re.search(r'\(r"/api/liste/verifier", NO_STORE,', c.src["cache"]):
        bad.append("cache.py: no no-store policy")
    if '"verifier_liste"' not in c.src["api"]:
        bad.append("FEATURES")
    fn = re.search(r'@app.get\("/api/liste/verifier"\)\ndef liste_verifier\(.*?(?=\n@app\.)', c.src["api"], re.S)
    if not fn or "cods = VX.clean_ids(ids.split(\",\"))" not in fn.group(0) or "raise HTTPException(422, str(exc)) from exc" not in fn.group(0) \
            or "LST.verifier(_con().cursor(), cods)" not in fn.group(0) or re.search(r"\bA\.record|bg\.add_task|track\(", fn.group(0)):
        bad.append("route source: codes not validated (422), or an audience event")
    if c.db is None:
        return not bad, f"no warehouse: route not called; {bad}"
    cl = TestClient(api.app)
    seen = []
    real_record = A.record
    A.record = lambda *a, **k: seen.append(a)
    try:
        r = cl.get("/api/liste/verifier?ids=3,4")
        if r.status_code != 200 or "no-store" not in (r.headers.get("cache-control") or "") or [v["cod_aff_form"] for v in r.json()["voeux"]] != ["3", "4"]:
            bad.append(f"ok answer {r.status_code} {r.headers.get('cache-control')}")
        for q in ("ids=a1", "ids=" + ",".join(str(i) for i in range(1, 12)), "ids=" + "9" * 300):
            if cl.get(f"/api/liste/verifier?{q}").status_code != 422:
                bad.append(f"{q[:20]} not refused")
    finally:
        A.record = real_record
    if seen:
        bad.append("an audience event recorded")
    return not bad, f"{bad}"


# ------------------------------------------------------------------ LI4 card
def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        end = js.find("\n};", m.start())
        if end != -1 and js[m.start():one].count("{") > js[m.start():one].count("}"):
            return js[m.start(): end + 3]
        return js[m.start(): one]
    return js[m.start(): js.find("\n}", m.start()) + 2]


NAMES = ("esc", "fmt", "frDate", "PROJET_MAX", "projetLoad", "listeDate", "listeJours", "vmKey", "vxCompte", "vxCompteTxt", "verifierCard")


def run_node(js: str, payload):
    exe = shutil.which("node")
    if not exe:
        return None
    prog = """let STORE = {};
const store = { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v; } };
const localIso = () => "2027-02-01";
""" + "\n".join(top(js, n) for n in NAMES) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(P.map(([ids, f, cal, opts, st]) => { STORE = st || {}; return verifierCard(ids, f, cal, opts); })));"""
    r = nodefile.run([exe, "-e", prog], input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout)


def _cal(regles=None, dates=True):
    ev = [{"key": "fin_voeux", "debut": "2027-03-11", "verifie": dates}, {"key": "confirmation", "debut": "2027-04-01", "verifie": dates}]
    return {"campagne": 2027, "evenements": ev, "regles": regles if regles is not None else
            {"voeux_max": 10, "apprentissage_max": 10, "sous_voeux": True, "apprentissage_apres": True}}


def card_ok(js: str) -> tuple[bool, str]:
    bad = []
    f = {"session": 2025, "carte_session": 2026, "voeux": [
        {"cod_aff_form": "1", "connu": True, "dans_carte": True, "concours": "Concours " + HOSTILE, "apprentissage": False},
        {"cod_aff_form": "2", "connu": True, "dans_carte": False, "concours": None, "apprentissage": True},
        {"cod_aff_form": "3", "connu": True, "dans_carte": True, "concours": None, "apprentissage": False}]}
    noms = {"1": "École " + HOSTILE, "2": "Lycée B", "3": "Université C"}
    cases = [[["1", "2", "3"], f, _cal(), {"noms": noms, "securite": "aucune", "today": "2027-02-01"}, {"projet": {"3": {"coches": [], "brouillon": "x"}}}],
             [["3"], {"session": 2025, "carte_session": 2026, "voeux": [f["voeux"][2]]}, _cal({}, False), {"noms": noms, "securite": "ok", "today": "2027-02-01"}, {}],
             [["3"], {"session": 2025, "carte_session": 2026, "voeux": [f["voeux"][2]]}, None, {"noms": noms, "securite": None, "today": "2027-04-02"},
              {"projet": {"3": {"coches": [1], "brouillon": "projet"}}}],
             [["3"], None, _cal(), {}, {}]]
    mix = [("10", "Concours Puissance Alpha"), ("11", "Concours SESAME"), ("12", "Concours SESAME"), ("13", "Concours commun"),
           ("14", "Concours commun")]
    cases.append([[c for c, _ in mix], {"session": 2025, "carte_session": 2026, "voeux": [
        {"cod_aff_form": c, "connu": True, "dans_carte": True, "concours": k, "apprentissage": False} for c, k in mix]},
        _cal(), {"noms": {c: f"F{c}" for c, _ in mix}, "securite": "ok", "today": "2027-02-01"}, {}])
    r = run_node(js, cases)
    if r is None:
        return True, "node not installed"
    full, unknown, nocal, empty, mixed = r
    plain = lambda h: re.sub(r"<[^>]+>", " ", h)  # noqa: E731
    # Codex (PR #99): one line per named concours; different concours never in one line; « Concours commun » never grouped
    lines = [plain(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", mixed, re.S) if "concours" in plain(x)]
    if len(lines) != 4 or any(("F10" in t) + ("F11" in t) + ("F13" in t) + ("F14" in t) > 1 for t in lines) \
            or not any("F11" in t and "F12" in t and "même concours" in t for t in lines) \
            or sum("même vœu" in t for t in lines) != 1:
        bad.append(f"concours lines: {lines}")
    if "<img" in full or "onerror=alert(1)>" in full:
        bad.append("unescaped")
    for need in ("Votre liste compte 3 vœux, dont 1 en apprentissage", "jusqu'à 10 vœux", "jusqu'à 10 vœux en apprentissage en plus",
                 "compter comme sous-vœu", "absente de la carte des formations Parcoursup 2026", "Aucun vœu de votre liste n'est une sécurité sûre",
                 "1 vœu sur 3 a un brouillon", "jeudi 11 mars 2027", "jeudi 1er avril 2027", "dans 38 jours", "En apprentissage, vous pourrez encore",
                 'href="/api/calendrier.ics"', "Avant de confirmer sur Parcoursup", "qui fait foi"):
        if need not in full:
            bad.append(f"missing « {need} »")
    if full.count('vf-st vf-look">À vérifier') != 4 or full.count('vf-st vf-ok">Fait') != 1:
        bad.append("statuses: 4 À vérifier (concours, map, safety, drafts), 1 Fait (the count)")
    if "Vérifiez le nombre de vœux permis sur parcoursup.gouv.fr" not in unknown or "date à vérifier sur parcoursup.gouv.fr" not in unknown \
            or "jusqu'à 10" in unknown or "calendrier.ics" in unknown:
        bad.append("an unknown calendar shows a typed number, a date or the agenda link")
    if "Votre liste contient au moins une sécurité sûre" not in unknown or "sécurité" in plain(nocal).replace("sécurité sûre", "") and "Aucun vœu" in nocal:
        bad.append("safety line")
    if "sécurité" in plain(nocal):
        bad.append("a safety line outside terminale")
    if "1 vœu sur 1 a un brouillon" not in nocal or "Vérifiez le nombre de vœux permis" not in nocal:
        bad.append("no calendar at all")
    if empty != "":
        bad.append("a card with no answer")
    for h in (full, unknown, nocal):
        t = plain(h)
        if BAN.search(t) or TU.search(t):
            bad.append(f"wording: {(BAN.search(t) or TU.search(t)).group(0)}")
    return not bad, f"5 renders; {bad[:4]}"


@check("LI4 card: statuses in words, escaped, the calendar's numbers and dates only (« 1er »), unknown said, no valid list, vous")
def li4(c: Ctx):
    return card_ok(c.js)


# ------------------------------------------------------------------ LI5 page wiring
@check("LI5 page: a placeholder in both Mes vœux views, one request (codes only), race guarded, failures handled")
def li5(c: Ctx):
    js = c.js
    bad = []
    ph = '<section class="card" id="vx-verifier"><p class="muted small">Vérification de votre liste…</p></section>'
    main = js[js.index("async function viewVoeux("):js.index("async function viewVoeux(") + 9000]
    reo = js[js.index("async function viewVoeuxReo("):js.index("async function viewVoeuxReo(") + 6000]
    for name, body in (("main", main), ("reo", reo)):
        if ph not in body or "loadVerifier(ids, marker," not in body:
            bad.append(f"{name} view not wired")
    if "securite: null" not in reo:
        bad.append("a safety line outside terminale")
    lv = top(js, "loadVerifier")
    if 'api(`/api/liste/verifier?${new URLSearchParams({ ids: ids.join(",") })}`)' not in lv or 'api("/api/calendrier").catch(() => null)' not in lv:
        bad.append("requests")
    if "if ($view.dataset.rendered !== marker || !box || !box.isConnected) return;" not in lv:
        bad.append("race guard")
    if "box.remove()" not in lv:
        bad.append("a failed check leaves the placeholder")
    if re.search(r"profile|spe1|mention|academie|projet", lv):
        bad.append("the request carries more than the codes")
    return not bad, f"{bad}"


@check("LI6 docs and wiring: README, CLAUDE.md, durations.json, release table")
def li6(c: Ctx):
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text()
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    rel = (ROOT / "tests" / "test_release.py").read_text()
    bad = [x for x, ok in (("README", "liste.py" in readme and "Avant de confirmer sur Parcoursup" in readme),
                           ("CLAUDE.md", "redteam_liste.py" in claude), ("durations", "tests/test_liste.py" in dur),
                           ("release", "loadVerifier(ids, marker," in rel)) if not ok]
    return not bad, f"{bad}"


MUTANTS = [
    ("calendrier", "versions not compared", "out[key] = found[0] if vs and None not in found and len(set(found)) == 1 else None",
     "out[key] = found[0] if vs else None", "LI1"),
    ("calendrier", "a typed default", "out[key] = found[0] if vs and None not in found and len(set(found)) == 1 else None",
     "out[key] = (found[0] if vs and None not in found and len(set(found)) == 1 else None) or 10", "LI1"),
    ("calendrier", "wrong number read", '("voeux_max", r"jusqu\'a (\\d{1,2}) voeux', '("voeux_max", r"jusqu\'a (\\d) voeux', "LI1"),
    ("liste", "older campaign's labels", "ORDER BY session DESC LIMIT 1", "ORDER BY session ASC LIMIT 1", "LI2"),
    ("liste", "any concours word", '    return "Concours commun" if COMMUN.search(JPO.fold(labels or "")) else None',
     '    return "Concours commun" if "concours" in JPO.fold(labels or "") else None', "LI2"),
    ("liste", "any map session", "WHERE cod_aff_form = ? AND carto_session = ?\",\n                                    [cod, carte_session]",
     "WHERE cod_aff_form = ? AND carto_session <= ?\",\n                                    [cod, carte_session]", "LI2"),
    ("liste", "apprenticeship ignored", '"apprentissage": bool(r[2]) if r else False', '"apprentissage": False', "LI2"),
    ("api", "no 422", "        raise HTTPException(422, str(exc)) from exc\n    return LST.verifier", "        cods = []\n    return LST.verifier", "LI3"),
    ("cache", "shared cache", '(r"/api/liste/verifier", NO_STORE,', '(r"/api/liste/verifier", PUBLIC,', "LI3"),
    ("js", "name unescaped", "const nom = (c) => `« ${esc(noms[c] || `formation ${c}`)} »`;", "const nom = (c) => `« ${noms[c] || `formation ${c}`} »`;", "LI4"),
    ("js", "concours unescaped", "(${esc(g.nom)})", "(${g.nom})", "LI4"),
    ("js", "different concours in one vœu", 'v.concours !== "Concours commun" && groups.find((x) => x.nom === v.concours)',
     'groups[0]', "LI4"),
    ("js", "« Concours commun » grouped", 'v.concours !== "Concours commun" && groups.find', 'groups.find', "LI4"),
    ("js", "typed maximum", "const max = Number.isInteger(R.voeux_max) ? R.voeux_max : null,", "const max = Number.isInteger(R.voeux_max) ? R.voeux_max : 10,", "LI4"),
    ("js", "unverified date shown", "return e && e.verifie && typeof e.debut", "return e && typeof e.debut", "LI4"),
    ("js", "no « 1er »", 'frDate(iso).replace(/^(\\S+) 1 /, "$1 1er ")', "frDate(iso)", "LI4"),
    ("js", "card without an answer", "  if (!f || !Array.isArray(f.voeux)) return \"\";\n", "", "LI4"),
    ("js", "safety always said", "  else if (opts.securite === \"ok\") items.push", "  else items.push", "LI4"),
    ("js", "a valid list", "SupCompass ne voit pas votre dossier Parcoursup&nbsp;: ces repères ne remplacent pas la confirmation de chaque vœu.",
     "Votre liste est valide.", "LI4"),
    ("js", "race unguarded", "  if ($view.dataset.rendered !== marker || !box || !box.isConnected) return;", "", "LI5"),
    ("js", "profile sent", 'api(`/api/liste/verifier?${new URLSearchParams({ ids: ids.join(",") })}`)',
     'api(`/api/liste/verifier?${new URLSearchParams({ ids: ids.join(","), mention: (opts.profil || {}).mention })}`)', "LI5"),
    ("js", "reo view not wired", "  loadVerifier(ids, marker, { noms: Object.fromEntries(d.voeux.filter((v) => v.status === \"ok\")", "  void (0, { noms: Object.fromEntries(d.voeux.filter((v) => v.status === \"ok\")", "LI5"),
]


@check("LI7 mutation test: every seeded rule, fact, route, card and page bug is caught")
def li7(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:6] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught = [], 0
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(c)
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        if kind == "js":
            m.js = src.replace(old, new, 1)
        else:
            m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


def run(db: Path, real: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real)
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
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
