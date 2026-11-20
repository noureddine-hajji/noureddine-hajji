"""Red team of sprint 1 (owner, 2026-11-20): « Préparer mes projets de formation motivés ».

    python scripts/redteam_projet.py [--db data/suptracker.duckdb] [--real]

  PJ1 the answer (Python): lines split on the fiche's own line breaks, empty ones dropped, words untouched; every criterion of
      the detailed grid, from the most important to the least, then the fiche's order (an independent re-derivation, crafted
      and on the warehouse); the exact set of keys, the limit, an https parcoursup.fr fiche address only
  PJ2 the route: 200 / 422 (letters, 10 digits, non-ASCII digits) / 404; a public cache like /api/formation; no audience event;
      the page in the closed route lists (router, tab, analytics)
  PJ3 the card (Node): every stored string escaped, one checkbox per criterion in the served order, the credit (campaign, date
      read, « la fiche fait foi »), a missing fiche said with its link, vouvoiement, never a chance, never a model text
  PJ4 the browser only: stored data read back through a validator (hostile shapes dropped), the page requests /api/projet/<code>
      per vœu and nothing else (never the draft), no request with an empty list, a late answer never draws over another page;
      the privacy page says the drafts stay in the browser
  PJ5 the counter: characters as a person counts them (an accent or an emoji is one), the limit said with « espaces compris »
      and « fait foi », the warning only beyond the limit
  PJ6 entry points and docs: the Mes vœux link, the router, the release guard, README, CLAUDE.md, the test in durations.json
  PJ7 real data (--real): formations of the latest campaign whose fiche the page can show, measured and printed
  PJ8 mutation test of PJ1-PJ6 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
MODEL = re.compile(r"(?i)lettre[- ]type|modèle de lettre|exemple de projet|texte généré")
NAMES = ("esc", "fmt", "frDate", "PROJET_MAX", "projetCount", "projetLoad", "projetSave", "projetCounter", "projetOver", "projetCard",
         "viewProjet")
HARNESS = r"""
let STORE = {}, CALLS = [], API = {}, IDS = [];
const $view = { innerHTML: "", dataset: {}, querySelectorAll: () => [] };
let projetSeq = 0;
const store = { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v; } };
const voeux = { MAX: 10, get: () => IDS.slice() };
async function api(u) { CALLS.push(u); const f = API.fn; if (!f) throw new Error("no api"); return f(u); }
"""


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
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        end = js.find("\n};", m.start())
        if end != -1 and js[m.start():one].count("{") > js[m.start():one].count("}"):
            return js[m.start(): end + 3]
        return js[m.start(): one]
    return js[m.start(): js.find("\n}", m.start()) + 2]


def run_node(js: str, prog: str, payload):
    exe = shutil.which("node")
    if not exe:
        return None
    src = HARNESS + "\n".join(top(js, n) for n in NAMES) + "\n" + prog
    r = subprocess.run([exe, "-e", src], input=json.dumps(payload), capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


def load_projet(src: str):
    """projet.py from its (possibly mutated) source, its relative import resolved."""
    import suptracker  # noqa: F401
    mod = types.ModuleType("suptracker.projet_rt")
    mod.__package__ = "suptracker"
    exec(compile(src, "projet_rt.py", "exec"), mod.__dict__)
    return mod


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.py = (ROOT / "suptracker" / "projet.py").read_text()
        self.js = (STATIC / "app.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.analytics = (ROOT / "suptracker" / "analytics.py").read_text()
        self.legal = (ROOT / "suptracker" / "legal.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()


# ------------------------------------------------------------------ PJ1 the answer
def rt_lines(t):
    return [x.strip() for x in re.split(r"\r\n|\r|\n", t or "") if x.strip()]


def rt_order(champs):
    flat = [(k["importance"], ch["rang"], i, ch, k) for ch in champs for i, k in enumerate(ch["criteres"])]
    flat.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [(ch["champ"], ch["poids"], k["critere"], k["elements"], k["importance"], k["importance_label"]) for _, _, _, ch, k in flat]


KEYS = {"cod", "etablissement", "formation", "ville", "limite", "fiche", "fiche_url"}
FKEYS = {"session", "lu_le", "grille", "attendus", "complementaires", "conseils", "info", "criteres"}


def answer_ok(src: str, db: Path | None, real: bool) -> tuple[bool, str]:
    P = load_projet(src)
    bad = []
    if P.lignes("  a  \n\n b \r\n\nc") != ["a", "b", "c"] or P.lignes(None) != []:
        bad.append("lines")
    champs = [{"rang": 2, "champ": "Motivation", "poids": 40, "criteres": [
                  {"critere": "M1", "elements": "e1", "importance": 3, "importance_label": "Très important"},
                  {"critere": "M2", "elements": None, "importance": 4, "importance_label": "Essentiel"}]},
              {"rang": 1, "champ": "Résultats", "poids": 60, "criteres": [
                  {"critere": "R1", "elements": "e2", "importance": 3, "importance_label": "Très important"},
                  {"critere": "R2", "elements": "e3", "importance": 1, "importance_label": "Complémentaire"}]}]
    got = [(k["champ"], k["poids"], k["critere"], k["elements"], k["importance"], k["importance_label"]) for k in P.criteres(champs)]
    if got != rt_order(champs):
        bad.append(f"crafted order {[g[2] for g in got]}")
    if P.LIMITE != 1500:
        bad.append("limit")
    for u, ok in (("https://dossierappel.parcoursup.fr/Candidat/carte?x=1", True), ("http://dossierappel.parcoursup.fr/x", False),
                  ("javascript:alert(1)//parcoursup.fr/", False), ("https://evil.example/?parcoursup.fr/", False), (None, False)):
        if bool(P._fiche_url(u)) != ok:
            bad.append(f"fiche address {u}")
    n = 0
    if db is not None:
        import duckdb
        from suptracker import grilles as GR
        con = duckdb.connect(str(db), read_only=True)
        try:
            if GR.RP._has(con, "core", "fiche_grille"):
                codes = [r[0] for r in con.execute("SELECT cod_aff_form FROM core.fiche_grille ORDER BY cod_aff_form").fetchall()]
                random.Random(7).shuffle(codes)
                for cod in codes[: 300 if real else 60]:
                    d, g = P.for_formation(con, cod), GR.for_formation(con, cod)
                    if d is None:
                        continue
                    n += 1
                    if set(d) != KEYS or d["limite"] != 1500 or d["cod"] != cod:
                        bad.append(f"{cod}: keys or limit")
                        break
                    if (g is None) != (d["fiche"] is None):
                        bad.append(f"{cod}: a fiche shown that the grid reader refuses, or the reverse")
                        break
                    if g:
                        f = d["fiche"]
                        if set(f) != FKEYS or f["attendus"] != rt_lines(g["nationaux"]) or f["complementaires"] != rt_lines(g["complementaires"]) \
                                or f["conseils"] != rt_lines(g["conseils"]) or f["session"] != g["session"]:
                            bad.append(f"{cod}: texts")
                            break
                        mine = [(k["champ"], k["poids"], k["critere"], k["elements"], k["importance"], k["importance_label"]) for k in f["criteres"]]
                        if mine != rt_order(g["champs"]):
                            bad.append(f"{cod}: criteria order or content")
                            break
                    if d["fiche_url"] and not (d["fiche_url"].startswith("https://") and "parcoursup.fr/" in d["fiche_url"]):
                        bad.append(f"{cod}: fiche address")
                        break
        finally:
            con.close()
    return not bad, f"{n} formations re-derived; differences {bad[:4]}"


@check("PJ1 the answer: lines, every criterion from the most important (then the fiche's order), exact keys, limit, fiche address")
def pj1(c: Ctx):
    return answer_ok(c.py, c.db, c.real)


# ------------------------------------------------------------------ PJ2 the route
def route_ok(js: str, api_src: str, analytics: str) -> tuple[bool, str]:
    bad = []
    if 'projet: "projet" };' not in js or 'guide: "voeux", projet: "voeux" };' not in js:
        bad.append("router or tab list")
    if not re.search(r'ROUTES = \([^)]*"projet"\)', analytics, re.S):
        bad.append("analytics closed route list")
    body = api_src[api_src.find('@app.get("/api/projet/{cod}")'):]
    body = body[: body.find("\n\n\n")]
    if not body or re.search(r"\b(AN|analytics|track|record)\b", body):
        bad.append("the route records an audience event (or is missing)")
    if "cod.isascii() and cod.isdigit() and len(cod) <= 9" not in body:
        bad.append("the code is not checked")
    return not bad, f"problems {bad}"


@check("PJ2 the route: 200/422/404, a public cache, no audience event, the closed route lists")
def pj2(c: Ctx):
    ok, d = route_ok(c.js, c.api, c.analytics)
    bad = [] if ok else [d]
    from suptracker import cache as CA
    pol = CA.policy("/api/projet/123")
    if not pol or pol[0] != CA.PUBLIC:
        bad.append(f"cache policy {pol}")
    if c.db is not None:
        import os
        os.environ.setdefault("SUPTRACKER_DB", str(c.db))
        from fastapi.testclient import TestClient
        from suptracker.api import app
        import duckdb
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            cod = con.execute("SELECT max(cod_aff_form) FROM core.formation_year").fetchone()[0]
        finally:
            con.close()
        cl = TestClient(app)
        for path, want in ((f"/api/projet/{cod}", 200), ("/api/projet/abc", 422), ("/api/projet/1234567890", 422),
                           ("/api/projet/%D9%A1%D9%A2", 422), ("/api/projet/999999999", 404)):
            r = cl.get(path)
            if r.status_code != want:
                bad.append(f"{path}: {r.status_code}")
            elif want == 200 and not r.headers.get("cache-control", "").startswith("public"):
                bad.append("not publicly cached")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ PJ3 the card
def card_ok(js: str) -> tuple[bool, str]:
    crit = [{"champ": "Motivation " + HOSTILE, "poids": 50, "critere": "IMPLICATION " + HOSTILE, "elements": "Lettre " + HOSTILE,
             "importance": 4, "importance_label": "Essentiel"},
            {"champ": "Résultats", "poids": 50, "critere": "RESULTATS", "elements": None, "importance": 3, "importance_label": "Très important"}]
    full = {"cod": "123", "etablissement": "Lycée " + HOSTILE, "formation": "BTS " + HOSTILE, "ville": "Ville " + HOSTILE, "limite": 1500,
            "fiche_url": "https://dossierappel.parcoursup.fr/x?a=1&b=2",
            "fiche": {"session": 2026, "lu_le": "2026-11-15", "grille": True, "attendus": ["Attendu " + HOSTILE], "complementaires": ["Plus " + HOSTILE],
                      "conseils": ["Conseil " + HOSTILE], "info": [], "criteres": crit}}
    none = dict(full, fiche=None)
    prog = r"""
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([projetCard(D.f, { coches: [1], brouillon: "x".repeat(1600) + D.h }, true), projetCard(D.n, {}, false),
        projetCard(D.f, {}, false)]));"""
    out = run_node(js, prog, {"f": full, "n": none, "h": HOSTILE})
    if out is None:
        return True, "node absent: not run"
    a, b, e = out
    bad = []
    if HOSTILE in a or HOSTILE in b or "<img" in a + b:
        bad.append("a stored string unescaped")
    boxes = re.findall(r'<input type="checkbox" data-pj="123" data-i="(\d)"( checked)?>', a)
    if [i for i, _ in boxes] != ["0", "1"] or [bool(x) for _, x in boxes] != [False, True]:
        bad.append(f"checkboxes {boxes}")
    if a.find("IMPLICATION") > a.find("RESULTATS"):
        bad.append("criteria not in the served order")
    if "D'après la fiche Parcoursup 2026" not in a or "La fiche fait foi" not in a or "https://dossierappel.parcoursup.fr/x?a=1&amp;b=2" not in a:
        bad.append("credit or link")
    if "Nous n'avons pas pu lire la fiche Parcoursup" not in b or "dossierappel.parcoursup.fr" not in b or "<h3>Ce que son jury" in b:
        bad.append("a missing fiche not said")
    if "open" not in a.split(">")[0] or "open" in e.split(">")[0]:
        bad.append("open state")
    plain = re.sub(r"<[^>]+>", " ", a + b)
    if TU.search(plain) or CHANCE.search(plain) or MODEL.search(plain):
        bad.append("tutoiement, a chance or a model text")
    if "n'est jamais envoyé" not in a:
        bad.append("the draft's privacy not said on the card")
    return not bad, f"problems {bad}"


@check("PJ3 the card: escaped, one checkbox per criterion in order, the credit, a missing fiche said, vouvoiement, never a chance or a model text")
def pj3(c: Ctx):
    return card_ok(c.js)


# ------------------------------------------------------------------ PJ4 the browser only
def local_ok(js: str, legal: str) -> tuple[bool, str]:
    prog = r"""
      (async () => {
        const out = {};
        STORE = { projet: { "12": { coches: [2, 2, 1, -1, 1.5, "3", 999], brouillon: "abc" }, "x1": { coches: [1] }, "13": [1, 2],
                            "14": { coches: [], brouillon: 7 }, "15": { coches: [3], brouillon: "y".repeat(25000) } } };
        out.load = projetLoad();
        STORE = { projet: [1, 2] }; out.arr = projetLoad();
        STORE = {}; IDS = []; CALLS = []; API.fn = async () => ({}); await viewProjet(""); out.empty = CALLS.slice(); out.emptyHtml = $view.innerHTML;
        IDS = ["12", "345"]; CALLS = [];
        API.fn = async (u) => ({ cod: u.split("/").pop(), etablissement: "E", formation: "F", ville: "V", limite: 1500, fiche: null, fiche_url: null });
        await viewProjet("345"); out.calls = CALLS.slice(); out.html = $view.innerHTML;
        CALLS = []; const rel = [];
        API.fn = (u) => new Promise((r) => { rel.push(() => r({ cod: u.split("/").pop(), etablissement: "E", formation: "F", ville: "V", limite: 1500, fiche: null, fiche_url: null })); });
        const p = viewProjet(""); await null; $view.dataset.rendered = "autre"; $view.innerHTML = "AUTRE"; rel.forEach((f) => f()); await p; out.race = $view.innerHTML;
        process.stdout.write(JSON.stringify(out));
      })();"""
    out = run_node(js, prog, {})
    bad = []
    if out is not None:
        if out["load"] != {"12": {"coches": [1, 2], "brouillon": "abc"}, "15": {"coches": [3], "brouillon": "y" * 20000}} or out["arr"] != {}:
            bad.append(f"stored data not validated: {out['load']}")
        if out["empty"] or "Votre liste de vœux est vide" not in out["emptyHtml"] or "#/carte" not in out["emptyHtml"]:
            bad.append("an empty list: a request, or not said with a way to search")
        if out["calls"] != ["/api/projet/12", "/api/projet/345"]:
            bad.append(f"requests {out['calls']}")
        if out["html"].count('<details class="card projet"') != 2 or 'id="pj-345" open' not in out["html"]:
            bad.append("the asked vœu is not the open one")
        if out["race"] != "AUTRE":
            bad.append("a late answer drew over another page")
    body = "".join(top(js, n) for n in ("projetLoad", "projetSave", "projetCard", "viewProjet"))
    calls = re.findall(r"\b(api|fetch|sendBeacon|track|navigator\.)\s*\(?([^)\n]{0,40})", body)
    if any(not (k == "api" and a.startswith("`/api/projet/")) for k, a in calls):
        bad.append(f"another request from the page: {calls}")
    if "brouillons de projet de formation motivé" not in legal or "ne sont jamais envoyés au site" not in legal:
        bad.append("the privacy page does not say the drafts stay in the browser")
    return not bad, f"problems {bad}"


@check("PJ4 browser only: stored data validated, one request per vœu and nothing else, none with an empty list, no late draw, privacy page")
def pj4(c: Ctx):
    return local_ok(c.js, c.legal)


# ------------------------------------------------------------------ PJ5 the counter
def counter_ok(js: str) -> tuple[bool, str]:
    prog = r"""
      process.stdout.write(JSON.stringify([projetCount("é à"), projetCount("😀a"), projetCount(""), projetCount(null),
        projetCounter(1, 1500), projetCounter(1501, 1500), projetOver(1500, 1500), projetOver(1501, 1500)]));"""
    out = run_node(js, prog, {})
    if out is None:
        return True, "node absent: not run"
    bad = []
    if out[:4] != [3, 2, 0, 0]:
        bad.append(f"count {out[:4]}")
    if out[4] != "1 caractère sur 1 500, espaces compris." and out[4] != "1 caractère sur 1 500, espaces compris.":
        bad.append(f"counter text {out[4]!r}")
    if "espaces compris" not in out[5] or out[6] or not out[7]:
        bad.append("the warning before or without the limit")
    card = top(js, "projetCard")
    if "La limite affichée pour chaque vœu sur Parcoursup fait foi" not in card:
        bad.append("the vœu's own limit not said to prevail")
    return not bad, f"problems {bad}"


@check("PJ5 the counter: characters as a person counts them, « espaces compris », the vœu's own limit prevails, a warning only beyond it")
def pj5(c: Ctx):
    return counter_ok(c.js)


# ------------------------------------------------------------------ PJ6 entry points and docs
def entries_ok(js: str, release: str, readme: str, claude: str, durations: str) -> tuple[bool, str]:
    bad = []
    if '<a href="#/projet">Préparer mes projets de formation motivés</a>' not in js:
        bad.append("Mes vœux link")
    if 'if (a === "projet") return await viewProjet(b || "")' not in js or "viewProjet" not in release:
        bad.append("router or release guard")
    if "Préparer mes projets de formation motivés" not in readme or "redteam_projet" not in readme:
        bad.append("README")
    if "projet.py" not in claude or "PJ1" not in claude:
        bad.append("CLAUDE.md")
    if "tests/test_projet.py" not in json.loads(durations):
        bad.append("durations")
    return not bad, f"missing {bad}"


@check("PJ6 entry points and docs: the Mes vœux link, the router, the release guard, README, CLAUDE.md, durations")
def pj6(c: Ctx):
    return entries_ok(c.js, c.release, c.readme, c.claude, c.durations)


# ------------------------------------------------------------------ PJ7 real data
@check("PJ7 real data: formations of the latest campaign whose fiche the page can show, measured")
def pj7(c: Ctx):
    if not (c.real and c.db):
        return True, "skipped (no --real)"
    import duckdb
    P = load_projet(c.py)
    con = duckdb.connect(str(c.db), read_only=True)
    try:
        s = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        codes = [r[0] for r in con.execute("SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY 1", [s]).fetchall()]
        random.Random(11).shuffle(codes)
        sample = codes[:1000]
        got = [P.for_formation(con, k) for k in sample]
    finally:
        con.close()
    shown = sum(1 for d in got if d and d["fiche"])
    crit = sum(1 for d in got if d and d["fiche"] and d["fiche"]["criteres"])
    link = sum(1 for d in got if d and (d["fiche"] or d["fiche_url"]))
    return shown > 0, (f"{shown} of {len(sample)} sampled formations ({100 * shown / len(sample):.1f} %) show their fiche, {crit} with "
                       f"the jury's criteria; {link} have at least a link to their fiche")


# ------------------------------------------------------------------ PJ8 mutation test
PY_MUTANTS = [
    ("criteria in the fiche's order only", "    flat.sort(key=lambda k: (-k[\"importance\"], k[\"_o\"]))\n", ""),
    ("least important first", '(-k["importance"], k["_o"])', '(k["importance"], k["_o"])'),
    ("ties not in the fiche's order", '(-k["importance"], k["_o"])', '(-k["importance"], k["critere"])'),
    ("empty lines kept", 'return [x.strip() for x in (texte or "").splitlines() if x.strip()]', 'return [x.strip() for x in (texte or "").splitlines()]'),
    ("any fiche address", 'return url if url and url.startswith("https://") and "parcoursup.fr/" in url.split("?")[0] else None', "return url"),
    ("another limit", "LIMITE = 1500", "LIMITE = 2000"),
]
JS_MUTANTS = [
    ("a criterion unescaped", ": ${esc(k.critere)}${k.elements ?", ": ${k.critere}${k.elements ?", "pj3"),
    ("the name unescaped", "<summary><h2>${esc(d.etablissement)}</h2>", "<summary><h2>${d.etablissement}</h2>", "pj3"),
    ("the draft unescaped", ' rows="8">${esc(brouillon)}</textarea>', ' rows="8">${brouillon}</textarea>', "pj3"),
    ("checkboxes forget their ticks", '${coches.has(i) ? " checked" : ""}', "", "pj3"),
    ("the credit dropped", ". La fiche fait foi.${link}</p>`;", ".${link}</p>`;", "pj3"),
    ("a missing fiche not said", "Nous n'avons pas pu lire la fiche Parcoursup de cette formation.", "", "pj3"),
    ("tutoiement", "Écrivez ici votre projet pour cette formation.", "Écris ici ton projet pour cette formation.", "pj3"),
    ("stored ticks not validated", "Number.isInteger(i) && i >= 0 && i < 200", "true", "pj4"),
    ("a stored draft not cut", "v.brouillon.slice(0, PROJET_MAX)", "v.brouillon", "pj4"),
    ("a request with an empty list", "  if (!ids.length) {\n    $view.innerHTML = `${head}<div class=\"card\"><p>Votre liste de vœux est vide", "  if (false) {\n    $view.innerHTML = `${head}<div class=\"card\"><p>Votre liste de vœux est vide", "pj4"),
    ("no race guard", "  if ($view.dataset.rendered !== mk) return;\n  const saved = projetLoad()", "  const saved = projetLoad()", "pj4"),
    ("the draft sent", "api(`/api/projet/${encodeURIComponent(c)}`)", "api(`/api/projet/${encodeURIComponent(c)}?b=${encodeURIComponent((projetLoad()[c] || {}).brouillon || \"\")}`)", "pj4"),
    ("the asked vœu not opened", "open = cod && ids.includes(cod) ? cod : ids[0];", "open = ids[0];", "pj4"),
    ("code units counted", 'const projetCount = (t) => [...String(t || "")].length;', 'const projetCount = (t) => String(t || "").length;', "pj5"),
    ("the warning at the limit", "return n > limite ?", "return n >= limite ?", "pj5"),
    ("the vœu's limit not said to prevail", "La limite affichée pour chaque vœu sur Parcoursup fait foi.", "", "pj5"),
    ("the Mes vœux link dropped", ' · <a href="#/projet">Préparer mes projets de formation motivés</a>', "", "pj6"),
    ("the route dropped", '    if (a === "projet") return await viewProjet(b || "");\n', "", "pj6"),
]


@check("PJ8 mutation test: answer, route, card, privacy, counter and entry-point bugs are each caught")
def pj8(c: Ctx):
    missed = []
    for name, old, new in PY_MUTANTS:
        if c.py.count(old) != 1:
            missed.append(f"{name} (anchor {c.py.count(old)})")
            continue
        try:
            caught = not answer_ok(c.py.replace(old, new, 1), c.db, False)[0]
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    if not shutil.which("node"):
        return not missed, f"node absent: JS mutants not run; missed {missed}"
    runs = {"pj3": lambda js: card_ok(js)[0], "pj4": lambda js: local_ok(js, c.legal)[0], "pj5": lambda js: counter_ok(js)[0],
            "pj6": lambda js: entries_ok(js, c.release, c.readme, c.claude, c.durations)[0]}
    for name, old, new, g in JS_MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor {c.js.count(old)})")
            continue
        try:
            caught = not runs[g](c.js.replace(old, new, 1))
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    for name, mutate in (("route records an event", lambda a: a.replace('    d = PRJ.for_formation(_con().cursor(), cod)',
                                                                         '    AN.record("projet")\n    d = PRJ.for_formation(_con().cursor(), cod)', 1)),
                         ("the code not checked", lambda a: a.replace("cod.isascii() and cod.isdigit() and len(cod) <= 9", "cod", 1))):
        if route_ok(c.js, mutate(c.api), c.analytics)[0]:
            missed.append(name)
    total = len(PY_MUTANTS) + len(JS_MUTANTS) + 2
    return not missed, f"{total - len(missed)}/{total} mutants caught; missed {missed}"


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
