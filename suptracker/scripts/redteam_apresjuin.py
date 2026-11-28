"""Red team of PR 19 « Après le 1er juin » (owner, 2026-11-28): apres_juin.py, the calendar's admission sentences, the page.

    python scripts/redteam_apresjuin.py [--db data/suptracker.duckdb] [--real]

  AJ1 the official calendar's sentences: an independent reading of every fetched PDF version finds each sentence the page
      quotes, word for word (the PDF's arrows split a first letter, its columns interleave « sur parcoursup.gouv.fr »); the
      number of complementary-phase vœux is the one every version prints; doctored versions (a sentence missing in one
      version, another number, an extra word) give None, never a typed value
  AJ2 the measured repeat of complementary-phase admits: an independent count (Python sets) on crafted rows (unknown acc_pc
      on either side, a code gone, a zero) and on the real warehouse; the latest campaign's count is the search filter's
  AJ3 routes: /api/apres-juin takes no parameter and is shared-cached; /api/apres-juin/voeux is no-store, refuses a bad
      code or more than 10 (422), names each vœu from its LATEST campaign, records no audience event
  AJ4 the page (Node): every stored string escaped; a calendar sentence quoted only when its rule holds; no number of vœux
      typed when the calendar's is unreadable; no meaning of the answers without the official page (a warning and its
      link instead); per vœu a name and a link, never a rank asked, no input field; the persistence printed with its counts
      and the estimation label, said « pas des places cette année »
  AJ5 wiring and docs: route, tab, closed audience route, cache policies, calendar link, README, CLAUDE.md, test file, CI
      duration
  AJ6 plain words: vouvoiement, sentences <= 30 words, no chance / probability / guarantee
  AJ7 the official meaning of the answers (service-public F2861, aides.r_reponses): an independent reading of the fetched page
  AJ8 mutation test of AJ1-AJ7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import re
import shutil
import sys
import tempfile
import types
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import redteam_robustesse as RB  # noqa: E402

top = RB.top
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
BAN = re.compile(r"(?i)vos chances|probabilit|garanti|vous serez admis")
CAL = ROOT / "data" / "calendrier"
# the sentences the page quotes from the calendar (they must be the PDF's, word for word)
QUOTED = {"oui_ouisi": "Consultez dans votre dossier, au fur et à mesure, les propositions d'admission (Oui ou Oui-si) des formations que vous avez demandées.",
          "repondre_delais": "Faites votre choix : vous devez répondre dans les délais à chaque proposition d'admission reçue.",
          "classez": "classez vos vœux en attente."}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_aj")
    m.__package__ = "suptracker"
    m.__file__ = str(ROOT / "suptracker" / f"{name}.py")
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path | None, real: bool = False):
        self.db = Path(db) if db and Path(db).exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text()
                    for k in ("apres_juin", "calendrier", "api", "cache", "analytics", "aides")}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.readme = (ROOT / "README.md").read_text()
        self.claude = (REPO / "CLAUDE.md").read_text()
        self.durations = (ROOT / "tests" / "durations.json").read_text()

    def mod(self, k):
        return load(k, self.src[k])


# ------------------------------------------------------------------ AJ1 the calendar's sentences
def own_fold(s: str) -> str:
    """My own folding, not calendrier's: accents and case off, apostrophes and œ normalised, the PDF's split first letters
    joined (« C onsultez »), its interleaved « sur parcoursup.gouv.fr » dropped, every run of spaces one space."""
    s = s.replace("’", "'").replace("œ", "oe").replace("→", " ")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = " ".join(s.lower().split())
    s = re.sub(r"\b([cf]) (onsultez|aites)\b", r"\1\2", s)
    return s.replace("les propositions sur parcoursup.gouv.fr d'admission", "les propositions d'admission")


def versions_text(base: Path) -> list[str]:
    log = json.loads((base / "fetch_log.json").read_text())
    out = []
    for e in log if isinstance(log, list) else log.get("files", log.get("log", [])):
        f = e.get("text") or e.get("txt") or e.get("file")
        if f and (base / Path(f).name).exists() and str(f).endswith(".txt"):
            out.append((base / Path(f).name).read_text())
    if not out:                                         # whatever the log's shape: every extracted text beside it
        out = [p.read_text() for p in sorted(base.glob("*.pdf.txt"))]
    return out


def own_regles(texts: list[str]) -> dict:
    out = {}
    for k, q in QUOTED.items():
        out[k] = bool(texts) and all(own_fold(q) in own_fold(t) for t in texts)
    nums = []
    for t in texts:
        m = re.search(r"jusqu'a (\d+) nouveaux voeux pour des formations ayant encore des places", own_fold(t))
        nums.append(int(m.group(1)) if m else None)
    out["complementaire_max"] = nums[0] if nums and None not in nums and len(set(nums)) == 1 else None
    return out


def doctored(base: Path, how) -> Path:
    d = Path(tempfile.mkdtemp())
    for p in base.iterdir():
        if p.is_file():
            shutil.copy(p, d / p.name)
    txts = sorted(d.glob("*.pdf.txt"))
    how(txts)
    return d


def _sub_first(pat: str, new: str):
    def how(txts):
        t = txts[0].read_text()
        txts[0].write_text(re.sub(pat, new, t, count=1))
    return how


DOCTORED = [
    ("a version without « classez vos vœux en attente »", _sub_first(r"classez vos v\w+ux en attente", "rangez vos choix"), "classez", None),
    ("a version saying 15 new vœux", _sub_first(r"jusqu.à 10 nouveaux", "jusqu'à 15 nouveaux"), "complementaire_max", None),
    ("a version without « Faites votre choix »", _sub_first(r"aites votre choix", "aites attention"), "repondre_delais", None),
    ("a version without « dans les délais »", _sub_first(r"dans les délais", "rapidement"), "repondre_delais", None),
    ("a version adding a word to the Oui / Oui-si sentence", _sub_first(r"des formations que vous avez demandées", "des formations que vous avez bien demandées"), "oui_ouisi", None),
]


@check("AJ1 the calendar's sentences: an own reading of every PDF version finds each quoted sentence; doctored versions give None")
def aj1(c: Ctx):
    if not CAL.exists():
        return True, "no calendar fetched: skipped"
    C = c.mod("calendrier")
    texts = versions_text(CAL)
    mine, theirs = own_regles(texts), C.regles(CAL, C.REGLES_ADMISSION)
    bad = [k for k in mine if (theirs.get(k) or None) != (mine[k] or None)]
    for k, q in QUOTED.items():                         # the page quotes these words
        if q not in c.js:
            bad.append(f"the page no longer quotes « {q[:40]}… »")
    for name, how, key, want in DOCTORED:
        d = doctored(CAL, how)
        try:
            got = C.regles(d, C.REGLES_ADMISSION).get(key)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if got != want:
            bad.append(f"{name}: {key} = {got!r}")
    return not bad, f"{len(texts)} versions, rules {theirs and {k: theirs.get(k) for k in mine}}; problems {bad[:4]}"


# ------------------------------------------------------------------ AJ2 persistence
CRAFTED = [  # (code, session, acc_pc)
    ("1", 2024, 3), ("1", 2025, 2),          # admitted, again
    ("2", 2024, 1), ("2", 2025, 0),          # admitted, not again
    ("3", 2024, 0), ("3", 2025, 4),          # none, then some
    ("4", 2024, 0), ("4", 2025, 0),          # none, none
    ("5", 2024, 2),                          # gone in 2025: out
    ("6", 2024, None), ("6", 2025, 5),       # unknown before: out
    ("7", 2024, 6), ("7", 2025, None),       # unknown after: out
    ("8", 2025, 9),                          # new in 2025: counted in the latest campaign only
    ("9", 2023, 7), ("9", 2025, 1),          # older campaign: not a pair
]


def crafted_con():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core; CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, acc_pc INTEGER)")
    con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?)", CRAFTED)
    return con


def own_persist(rows: list[tuple]) -> dict:
    years = sorted({s for _, s, _ in rows})
    a, b = years[-2], years[-1]
    pa = {c: v for c, s, v in rows if s == a}
    pb = {c: v for c, s, v in rows if s == b}
    both = [c for c in pa if c in pb and pa[c] is not None and pb[c] is not None]
    avec = [c for c in both if pa[c] > 0]
    sans = [c for c in both if pa[c] == 0]
    return {"avant": a, "apres": b,
            "avec": {"n": len(avec), "encore": sum(pb[c] > 0 for c in avec)},
            "sans": {"n": len(sans), "puis": sum(pb[c] > 0 for c in sans)},
            "derniere": {"session": b, "formations": len(pb), "avec_pc": sum((v or 0) > 0 for v in pb.values())}}


def persist_problems(M, con, rows) -> list:
    got, want = M.persistance(con), own_persist(rows)
    if not got:
        return ["no answer"]
    bad = []
    for k in ("avant", "apres"):
        if got[k] != want[k]:
            bad.append((k, got[k], want[k]))
    for g in ("avec", "sans", "derniere"):
        for k, v in want[g].items():
            if got[g].get(k) != v:
                bad.append((g, k, got[g].get(k), v))
    for g, num in (("avec", "encore"), ("sans", "puis")):
        if want[g]["n"] and abs(got[g]["part"] - 100 * want[g][num] / want[g]["n"]) > 0.051:
            bad.append((g, "part", got[g]["part"]))
    return bad


@check("AJ2 the measured repeat of complementary-phase admits: own count on crafted rows and on the warehouse")
def aj2(c: Ctx):
    M = c.mod("apres_juin")
    bad = persist_problems(M, crafted_con(), CRAFTED)
    want = {"avec": (3, 1), "sans": (2, 1)}                  # codes 1,2,7? no: 7 unknown after -> out; 1,2 then 3,4
    got = M.persistance(crafted_con())
    if got and ((got["avec"]["n"], got["avec"]["encore"]) != (2, 1) or (got["sans"]["n"], got["sans"]["puis"]) != (2, 1)):
        bad.append(("crafted by hand", got["avec"], got["sans"]))
    del want
    detail = ""
    if c.real:
        with duckdb.connect(str(c.db), read_only=True) as con:
            rows = con.execute("SELECT cod_aff_form, session, acc_pc FROM core.formation_year").fetchall()
            bad += [("real",) + tuple(x) for x in persist_problems(M, con, rows)]
            g = M.persistance(con)
            filt = con.execute("SELECT count(*) FROM core.formation_year WHERE session = ? AND acc_pc > 0", [g["apres"]]).fetchone()[0]
            if g["derniere"]["avec_pc"] != filt:
                bad.append(("search filter count", g["derniere"]["avec_pc"], filt))
            detail = f"; real {g['avant']}->{g['apres']}: {g['avec']} / {g['sans']}"
    return not bad, f"problems {bad[:4]}{detail}"


# ------------------------------------------------------------------ AJ3 routes
@check("AJ3 routes: /api/apres-juin public, no parameter; /api/apres-juin/voeux no-store, 422 on bad codes, latest names, no event")
def aj3(c: Ctx):
    bad = []
    api = c.src["api"]
    m = re.search(r'@app\.get\("/api/apres-juin/voeux"\)\ndef (\w+)\((.*?)\):(.*?)\n\n\n', api, re.S)
    p = re.search(r'@app\.get\("/api/apres-juin"\)\ndef (\w+)\((.*?)\):(.*?)\n\n\n', api, re.S)
    if not m or not p:
        return False, "routes missing"
    if p.group(2).strip():
        bad.append("/api/apres-juin takes a parameter")
    for fn in (m, p):
        code = re.sub(r'""".*?"""', "", fn.group(3), flags=re.S)      # the docstring says « no analytics event »
        if re.search(r"\bA\.(record|event|track)|_record|analytics", code):
            bad.append(f"{fn.group(1)} records an audience event")
    if "VX.clean_ids" not in m.group(3) or "HTTPException(422" not in m.group(3):
        bad.append("the list route does not validate its codes")
    cache = c.src["cache"]
    if not re.search(r'\(r"/api/apres-juin/voeux", NO_STORE', cache) or not re.search(r'\(r"/api/apres-juin", PUBLIC', cache):
        bad.append("cache policies")
    M = c.mod("apres_juin")
    con = crafted_con()
    con.execute("ALTER TABLE core.formation_year ADD COLUMN g_ea_lib_vx VARCHAR; ALTER TABLE core.formation_year ADD COLUMN lib_for_voe_ins VARCHAR;"
                "ALTER TABLE core.formation_year ADD COLUMN ville_etab VARCHAR")
    con.execute("UPDATE core.formation_year SET g_ea_lib_vx = 'Lycée ' || session, lib_for_voe_ins = 'BTS', ville_etab = 'Lyon'")
    M.APL = types.SimpleNamespace(for_formation=lambda con, cod: [{"groupes": [1]}] if cod == "1" else [])
    v = M.voeux(con, ["1", "9", "404"])["voeux"]
    if [x.get("etablissement") for x in v] != ["Lycée 2025", "Lycée 2025", None] or [x["connu"] for x in v] != [True, True, False]:
        bad.append(("names from the latest campaign", v))
    if [x.get("appel") for x in v[:2]] != [True, False]:
        bad.append(("call link flag", v))
    if any(k in json.dumps(v) for k in ("taux", "profondeur", "rang")):
        bad.append("a figure beside the list")
    if c.real:
        from fastapi.testclient import TestClient
        import suptracker.api as A
        cl = TestClient(A.app)
        r = cl.get("/api/apres-juin")
        if r.status_code != 200 or "s-maxage" not in r.headers.get("cache-control", ""):
            bad.append(("public answer", r.status_code, r.headers.get("cache-control")))
        for q, code in (("x", 422), (",".join(str(i) for i in range(1, 12)), 422), ("1<script>", 422)):
            rr = cl.get(f"/api/apres-juin/voeux?ids={q}")
            if rr.status_code != code or "no-store" not in rr.headers.get("cache-control", ""):
                bad.append(("list", q[:12], rr.status_code))
    return not bad, f"problems {bad[:4]}"


# ------------------------------------------------------------------ AJ4 the page
PAGE_NAMES = ("AJ_PC_SEARCH", "AJ_SANS_PROPOSITION", "ajDay", "ajQuote", "ajReponses", "ajPersistance", "viewApresJuin")
PAGE_STUB = r"""
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d) => (d ? Number(v).toFixed(d).replace(".", ",") : String(v));
const estimTag = (d) => `<span class="estim">estimation</span> ${d || ""}`;
const nextSteps = (k) => `<section class="next">${k}</section>`;
const frDate = (iso) => `le ${iso}`;
const localIso = () => "2027-05-20";
function calState(e, today) { if (!e.verifie) return "inconnu"; const end = e.fin || e.debut; return end < today ? "passe" : e.debut <= today ? "en_cours" : "a_venir"; }
const $view = { dataset: {}, innerHTML: "" };
let LIST = [], ANS = {};
const voeux = { get: () => LIST };
async function api(path) { if (path.startsWith("/api/apres-juin/voeux")) return ANS.list; return ANS.page; }
"""
PAGE_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
(async () => { const out = [];
  for (const k of D.cases) { LIST = k.ids; ANS = k; await viewApresJuin(); out.push($view.innerHTML); }
  process.stdout.write(JSON.stringify(out)); })();"""


def page_case(**kw) -> dict:
    ev = [{"key": "admission", "etape": 3, "libelle": "Début de la phase d'admission principale", "debut": "2027-06-01", "fin": None, "verifie": True},
          {"key": "classement", "etape": 3, "libelle": "Classez vos vœux en attente", "debut": "2027-06-04", "fin": "2027-06-07", "verifie": True},
          {"key": "complementaire", "etape": 3, "libelle": "Début de la phase complémentaire", "debut": "2027-06-10", "fin": None, "verifie": True}]
    page = {"campagne": 2027, "lu_le": "2026-11-23", "evenements": ev,
            "regles": {"repondre_delais": True, "oui_ouisi": True, "classez": True, "complementaire_max": 10},
            "reponses": None,
            "persistance": {"avant": 2024, "apres": 2025, "avec": {"n": 6087, "encore": 4479, "part": 73.6},
                            "sans": {"n": 7453, "puis": 1423, "part": 19.1}, "derniere": {"session": 2025, "formations": 14252, "avec_pc": 6186}},
            "liens": {"parcoursup": "https://www.parcoursup.gouv.fr/"}}
    page.update(kw.pop("page", {}))
    return {"ids": kw.get("ids", ["1", "2"]), "page": page,
            "list": kw.get("list", {"voeux": [{"cod_aff_form": "1", "connu": True, "session": 2025, "etablissement": HOSTILE, "formation": HOSTILE, "ville": HOSTILE, "appel": True},
                                              {"cod_aff_form": "2", "connu": False}]})}


def page_cases() -> list[dict]:
    rep = {"titre": HOSTILE, "verifie": HOSTILE, "source": "javascript:alert(1)", "intro": HOSTILE,
           "reponses": [HOSTILE, "En attente d'une place", "Refus"], "situations": [HOSTILE, "Si vous recevez x."],
           "inscription": {"titre": HOSTILE, "texte": [HOSTILE]}}
    return [page_case(),                                                                    # 0 full, no official answers
            page_case(page={"regles": {"repondre_delais": None, "oui_ouisi": None, "classez": None, "complementaire_max": None}}),  # 1 rules unreadable
            page_case(page={"reponses": rep}),                                               # 2 official answers, hostile
            page_case(ids=[], list=None),                                                    # 3 empty list
            page_case(page={"persistance": None, "evenements": [{"key": "complementaire", "etape": 3, "libelle": "x", "debut": "2027-06-10", "fin": None, "verifie": False}]})]  # 4


def page_problems(o: list[str]) -> list:
    bad = []
    raw = o
    o = [html.unescape(h) for h in o]                    # the quotes are escaped like every string (' -> &#39;)
    full, unread, rep, empty, nodate = o
    for i, h in enumerate(raw):
        if "<img" in h or "javascript:" in h:
            bad.append((i, "a stored string or link not escaped"))
        if re.search(r"<input|<select|<textarea", h):
            bad.append((i, "an input field: the page never asks a rank"))
        if re.search(r"(?i)(votre|quel est votre|indiquez votre) (rang|position)", h.replace("jamais votre rang", "")):
            bad.append((i, "a rank asked"))
    for k, q in QUOTED.items():
        if k != "classez" and q not in full:
            bad.append(("full", f"{k} not quoted"))
        if q in unread:
            bad.append(("unreadable rules", f"{k} quoted anyway"))
    if "Entre le " not in full or "et le le 2027-06-07 inclus : classez vos vœux en attente." not in full:
        bad.append(("full", "the classement sentence is not the calendar's"))
    if "jusqu'à 10 nouveaux vœux" not in full or "nouveaux vœux possibles est sur parcoursup.gouv.fr" not in unread or re.search(r"jusqu'à \d+ nouveaux", unread):
        bad.append(("the number of complementary vœux typed or lost", None))
    if "service-public.gouv.fr/particuliers/vosdroits/F2861" not in full or "n'a pas pu être lue" not in full:
        bad.append(("no official answers: no warning or link", None))
    if "n'a pas pu être lue" in rep or "&lt;img" not in raw[2] or "vosdroits/F2861" not in rep:
        bad.append(("official answers not shown, or their link not the official page", None))
    if "4479 sur 6087" not in full or "73,6 %" not in full or "estimation" not in full or "pas des places cette année" not in full:
        bad.append(("persistence without its counts, label or caveat", None))
    if "f_complementaire%3Doui" not in full:
        bad.append(("no link to the search filter", None))
    if "Votre liste est vide" not in empty or "#/voeux" not in empty:
        bad.append(("empty list", None))
    if "#/f/1" not in full or "jusqu'où sa liste a été appelée" not in full or "introuvable" not in full:
        bad.append(("per vœu: name, link or unknown code", None))
    if "À partir du" in nodate or "Pendant la phase complémentaire" not in nodate or "4479" in nodate:
        bad.append(("an unverified date or a missing persistence shown", None))
    if "parcoursup.gouv.fr" not in full or "Parcoursup fait foi" not in full:
        bad.append(("official link or « fait foi »", None))
    return bad


def render(js: str):
    parts = [top(js, n) for n in PAGE_NAMES]
    if not all(parts):
        return {"error": f"missing {[n for n, p in zip(PAGE_NAMES, parts) if not p]}"}
    return RB.node(PAGE_STUB + "\n".join(parts) + "\n" + PAGE_PROG, {"cases": page_cases()})


@check("AJ4 the page (Node): escaped, quotes only when read, no typed number, the official page or a warning, no rank asked, counts")
def aj4(c: Ctx, js: str | None = None):
    o = render(c.js if js is None else js)
    if o is None:
        return True, "node absent: not run"
    if isinstance(o, dict):
        return False, o["error"]
    bad = page_problems(o)
    return not bad, f"{len(o)} pages; problems {bad[:4]}"


# ------------------------------------------------------------------ AJ5 wiring
def wiring(c: Ctx, js=None, readme=None, claude=None, durations=None, analytics=None) -> list:
    js = c.js if js is None else js
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    durations = c.durations if durations is None else durations
    analytics = c.src["analytics"] if analytics is None else analytics
    bad = []
    if 'if (a === "apres-juin") return await viewApresJuin();' not in js:
        bad.append("route")
    if '"apres-juin": "calendrier"' not in js or '"apres-juin": "apresjuin"' not in js or '"apresjuin"' not in analytics:
        bad.append("tab or closed audience route")
    if 'href="#/apres-juin"' not in js or 'complementaire: "#/apres-juin"' not in js:
        bad.append("calendar links")
    if "## Après le 1er juin (PR 19" not in readme:
        bad.append("README section")
    if "**Après le 1er juin (PR 19" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_apresjuin.py").exists() or '"tests/test_apresjuin.py"' not in durations:
        bad.append("test file or its CI duration")
    return bad


@check("AJ5 wiring and docs: route, tab, closed audience route, calendar links, README, CLAUDE.md, test file, CI duration")
def aj5(c: Ctx):
    bad = wiring(c)
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AJ6 plain words
def page_text(o: list[str]) -> list[str]:
    """The page's text, one piece per block (heading, paragraph, list item, quote, label), entities decoded."""
    t = re.sub(r"</?(p|li|h\d|dt|dd|div|section|blockquote|ol|ul|dl|span class=\"estim\")\b[^>]*>", "\n", " ".join(o))
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return [" ".join(x.split()) for x in t.split("\n") if x.strip()]


def word_problems(blocks: list[str]) -> list:
    bad = []
    text = " \n ".join(blocks)
    if TU.search(text):
        bad.append(("tutoiement", TU.search(text).group(0)))
    if BAN.search(text):
        bad.append(("banned word", BAN.search(text).group(0)))
    for b in blocks:
        for x in re.split(r"(?<=[.!?:])\s+", b):
            if len(x.split()) > 30 and "«" not in x:      # quotes are the official pages' own sentences
                bad.append(("sentence over 30 words", x[:60]))
    if re.search(r"(?i)néo-bachelier|doublette", text):
        bad.append(("jargon", None))
    return bad


@check("AJ6 plain words: vouvoiement, sentences <= 30 words, no chance, probability or guarantee")
def aj6(c: Ctx, js: str | None = None):
    o = render(c.js if js is None else js)
    if o is None:
        return True, "node absent: not run"
    if isinstance(o, dict):
        return False, o["error"]
    bad = word_problems(page_text(o[:2] + o[3:]))          # case 2 holds the hostile stand-in for the official page
    return not bad, f"problems {bad[:4]}"


# ------------------------------------------------------------------ AJ7 the official answers
F2861 = ROOT / "data" / "aides" / "www.service-public.gouv.fr_particuliers_vosdroits_F2861.txt"


def own_reponses(text: str) -> dict | None:
    """My own reading: the block between « il vous donne l'une des réponses suivantes : » and « 3e étape », split by its own
    markers (no line rules of aides.py), plus the 3e étape's sentences up to the next question."""
    t = text.replace("\r", "")
    m = re.search(r"il vous donne l'une des réponses suivantes :\n(.*?)\n3e étape : l'inscription définitive\n(.*?)\n[^\n]*\?\n", t, re.S)
    if not m:
        return None
    lines = [x.strip() for x in m.group(1).split("\n") if x.strip()]
    situations = [x for x in lines if x.startswith("Si vous recevez")]
    reponses = lines[:len(lines) - len(situations)]
    ensuite = [x.strip() for x in m.group(2).split("\n") if x.strip()]
    ver = re.search(r"Vérifié le 0?(\d{1,2} \w+ \d{4})", t)
    return {"reponses": reponses, "situations": situations, "ensuite": ensuite, "verifie": ver.group(1) if ver else None}


REP_DOCTORED = [
    ("a fourth answer", lambda t: t.replace("Refus\n", "Refus\nOui-si\n", 1)),
    ("an answer missing", lambda t: t.replace("En attente d'une place\n", "", 1)),
    ("a situation missing", lambda t: t.replace("Si vous recevez uniquement des réponses en attente, vous devez attendre qu'une place se libère.\n", "", 1)),
    ("the commission gone", lambda t: t.replace("la commission d'accès à l'enseignement supérieur vous fera des propositions", "vous recevrez des propositions", 1)),
    ("the 3e étape renamed", lambda t: t.replace("3e étape : l'inscription définitive", "3e étape : l'inscription", 1)),
    ("the heading renamed", lambda t: t.replace("2e étape : Réception et acceptation des propositions sur Parcoursup", "2e étape : les réponses", 1)),
]


@check("AJ7 the official meaning of the answers: an own reading of service-public F2861 = aides.r_reponses; doctored pages give None")
def aj7(c: Ctx):
    if not F2861.exists():
        return True, "F2861 not fetched: the page warns and links the official page (AJ4)"
    text = F2861.read_text()
    M = c.mod("aides")
    got, mine = M.r_reponses(text, []), own_reponses(text)
    bad = []
    if not got or not mine:
        return False, f"unread: rule {bool(got)}, own {bool(mine)}"
    if got["reponses"] != mine["reponses"] or got["situations"] != mine["situations"] or got["inscription"]["texte"] != mine["ensuite"]:
        bad.append(("rule != own reading", got["reponses"], mine["reponses"]))
    if got["verifie"] != mine["verifie"] or got["source"] != "https://www.service-public.gouv.fr/particuliers/vosdroits/F2861":
        bad.append(("verified date or source", got["verifie"], got["source"]))
    for x in got["reponses"] + got["situations"] + got["inscription"]["texte"] + [got["intro"]]:
        if x not in text.replace("\u2019", "'") and x not in text:
            bad.append(("not verbatim", x[:50]))
    for name, f in REP_DOCTORED:
        if M.r_reponses(f(text), []) is not None:
            bad.append(("doctored page still read", name))
    return not bad, f"{len(got['reponses'])} answers, {len(got['situations'])} situations, vérifié le {got['verifie']}; problems {bad[:4]}"


# ------------------------------------------------------------------ AJ8 mutation test
MUTANTS = [
    ("calendrier", "AJ1", "the sentence rule loses its first words",
     'r"f ?aites votre choix : vous devez repondre', 'r"vous devez repondre'),
    ("calendrier", "AJ1", "a disagreement between versions ignored", "out[key] = found[0] if vs and None not in found and len(set(found)) == 1 else None",
     "out[key] = next((x for x in found if x is not None), None)"),
    ("apres_juin", "AJ2", "unknown acc_pc counted", "WHERE x.session = ? AND y.acc_pc IS NOT NULL", "WHERE x.session = ?"),
    ("apres_juin", "AJ2", "the repeat counted on the wrong side", "count(*) FILTER (WHERE x.acc_pc > 0 AND y.acc_pc > 0)",
     "count(*) FILTER (WHERE y.acc_pc > 0)"),
    ("apres_juin", "AJ3", "names from the oldest campaign", "ORDER BY session DESC LIMIT 1", "ORDER BY session LIMIT 1"),
    ("apres_juin", "AJ3", "a depth beside the list", '"appel": any(x.get("groupes") for x in APL.for_formation(con, cod))}',
     '"appel": any(x.get("groupes") for x in APL.for_formation(con, cod)), "profondeur": 0.5}'),
    ("api", "AJ3", "the list route records an event", "    return AJ.voeux(_con().cursor(), cods)", "    A.record('voeux')\n    return AJ.voeux(_con().cursor(), cods)"),
    ("cache", "AJ3", "the list shared-cached", '(r"/api/apres-juin/voeux", NO_STORE', '(r"/api/apres-juin/voeux", PUBLIC'),
    ("js", "AJ4", "a stored name not escaped", '${esc(v.etablissement)}</a> <span class="muted small">${esc(v.formation)}${v.ville',
     '${v.etablissement}</a> <span class="muted small">${esc(v.formation)}${v.ville'),
    ("js", "AJ4", "the answers not escaped", "R.reponses.map((x) => `<li><strong>${esc(x)}</strong></li>`)", "R.reponses.map((x) => `<li><strong>${x}</strong></li>`)"),
    ("js", "AJ4", "a hostile source link kept", '/^https:\\/\\/www\\.service-public\\.gouv\\.fr\\//.test(R.source || "") ? R.source', 'true ? R.source'),
    ("aides", "AJ7", "a fourth answer accepted", "if (len(reponses) != 3 or", "if (len(reponses) not in (3, 4) or"),
    ("aides", "AJ7", "the commission check dropped", """            or not any("commission d'accès à l'enseignement supérieur" in x for x in situations)):""", "            ):"),
    ("aides", "AJ7", "the 3e étape not checked", "    if i >= len(L) or L[i] != REPONSES_NEXT:\n        return None", "    if i >= len(L):\n        return None"),
    ("aides", "AJ7", "the source not the page", '"verifie": _verifie(text), "source": PAGES["reponses"]}', '"verifie": _verifie(text), "source": PAGES["apprenti"]}'),
    ("js", "AJ4", "a quote shown without its rule", 'g.repondre_delais ? "Faites votre choix', 'true ? "Faites votre choix'),
    ("js", "AJ4", "a typed number of complementary vœux", '" Le nombre de nouveaux vœux possibles est sur parcoursup.gouv.fr."', '" Vous pouvez y formuler jusqu\'à 10 nouveaux vœux."'),
    ("js", "AJ4", "the persistence without its counts", "(${fmt(P.avec.encore)} sur ${fmt(P.avec.n)})", ""),
    ("js", "AJ4", "the persistence's caveat dropped", "pas des places cette année", "des places"),
    ("js", "AJ4", "a rank asked", "${vx}\n", '${vx}<label>Votre rang <input name="rang"></label>\n'),
    ("js", "AJ4", "an unverified date printed", "comp && comp.verifie ? `À partir du", "comp ? `À partir du"),
    ("js", "AJ6", "a chance promised", "Ce n'est pas une prévision : SupCompass", "Vos chances sont bonnes : SupCompass"),
    ("js", "AJ5", "the route lost", 'if (a === "apres-juin") return await viewApresJuin();', ""),
]


@check("AJ8 mutation test: calendar, module, route, cache, page, words and wiring bugs are each caught")
def aj8(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("AJ1", "AJ2", "AJ3", "AJ4", "AJ5", "AJ6", "AJ7") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    caught, missed = 0, []
    for kind, target, name, old, new in MUTANTS:
        src = c.js if kind == "js" else c.src[kind]
        if src.count(old) != 1:
            missed.append(f"{name} (anchor found {src.count(old)} times)")
            continue
        m = copy.copy(c)
        if kind == "js":
            m.js = src.replace(old, new, 1)
        else:
            m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    for name, kw in (("README", {"readme": ""}), ("CLAUDE.md", {"claude": ""}), ("CI duration", {"durations": "{}"}),
                     ("audience route", {"analytics": c.src["analytics"].replace('"apresjuin"', '"x"')})):
        caught += bool(wiring(c, **kw))
        if not wiring(c, **kw):
            missed.append(name)
    total = len(MUTANTS) + 4
    return not missed, f"{caught}/{total} caught; missed {missed}"


def run(db: Path | None, real: bool = False, checks: set | None = None) -> list[dict]:
    import time
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t:.1f} s)"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args()
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS" if r["ok"] else "FAIL"), r["check"], "|", r["detail"])
    sys.exit(0 if all(r["ok"] for r in res) else 1)


if __name__ == "__main__":
    main()
