"""Red team of PR 18 (owner, 2026-11-28): « Mes vœux en apprentissage » (a SEPARATE list of apprenticeship offers) and the
apprentice's contract and minimum pay QUOTED from service-public.gouv.fr (aides.r_apprenti, apprentissage.voeux, the page).

    python scripts/redteam_apprentissage_voeux.py [--db data/suptracker.duckdb] [--real]

  AV1 the official table, read again independently (own words, own cleaning) on the saved page: 4 age columns, 3 contract years,
      the Smic percentages of each cell, every printed line verbatim, the two contract sentences, the « Vérifié le » date, the
      page's own links; every euro amount served is printed on the page (a quote, never a computed salary).
  AV2 doctored pages: a year missing, a percentage that falls with the year or with the age, an age column missing, a contract
      sentence missing -> no item (None) and the audit names it; never a typed fallback.
  AV3 the list: apprentissage.voeux re-derived on crafted offers (order kept, unknown code « absente », attached formations named,
      no zone, rate, admission or chance key) and, --real, on 60 offers of the latest map against carte.apprentissage.
  AV4 the route: 200 / 422 (a letter, 11 codes, a long value), never shared-cached (no-store), no audience event, a cache policy.
  AV5 the card (Node): every stored string escaped, no zone or rate, the number of apprenticeship vœux only from the official
      calendar (else « vérifiez »), « vérifiez qu'elle existe toujours » (never « fermée »), only https Parcoursup / service-public /
      La bonne alternance links, a non-official source drops the quote, euro amounts only inside the official quote and each one
      printed by the page, vouvoiement, no chance.
  AV6 the store: hostile stored values cleaned, 10 at most, its own key; the button says « liste pleine » when full; the zones,
      the profile bar, Plan B, Compléter, « Avant de confirmer », the guide never read this list (only the allowed functions).
  AV7 wiring and docs: both Mes vœux views (empty and full) carry the section and load it; the search card of an offer and the
      formation page's CFA lines carry the button; the formation page quotes the table; cache.py, privacy page, source register,
      README, CLAUDE.md, durations.json, tests.
  AV8 mutation test of AV1-AV7 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
import types
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
BAN = re.compile(r"(?i)vos chances|probabilit|garanti|vous serez admis|fermée")
AIDES = ROOT / "data" / "aides"
PAGE = "https://www.service-public.gouv.fr/particuliers/vosdroits/F2918"
EURO = re.compile(r"\d{1,3}(?:[  ]\d{3})*,\d{2} ?€|\d{1,3}(?:[  ]\d{3})+ ?€")


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
    def __init__(self, db: Path | None, real: bool = False):
        self.db = Path(db) if db and Path(db).exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text()
                    for k in ("aides", "apprentissage", "api", "cache", "legal", "sources")}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self, k):
        return load(k, self.src[k])


def _file(url: str, ext: str = ".txt") -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[-1])[:140] + ext


def page_text() -> str:
    return (AIDES / _file(PAGE)).read_text()


# ------------------------------------------------------------------ AV1 independent reading
def own_clean(s: str) -> str:
    s = s.replace(" : titleContent", "").replace(": titleContent", "")
    s = re.sub(r"(\d) (re|e) (année|cycle)", r"\1\2 \3", s)
    s = s.replace("( ", "(").replace(" )", ")")
    return " ".join(s.split())


def own_read(text: str) -> dict | None:
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    try:
        h = [i for i, x in enumerate(lines) if "Rémunération brute mensuelle minimale d'un apprenti" in x and x.startswith("Tableau")][0]
    except IndexError:
        return None
    seg = []
    for x in lines[h + 1:]:
        if x.startswith("À noter"):
            break
        seg.append(x)
    ages = [x for x in seg[:6] if re.fullmatch(r"\d\d (à \d\d ans|ans et plus)|\d\d-\d\d ans", x)]
    marks = [i for i, x in enumerate(seg) if re.fullmatch(r"\d (re|e) année", x)]
    years = []
    for j, i in enumerate(marks):
        body = seg[i + 1: marks[j + 1] if j + 1 < len(marks) else len(seg)]
        smic = [int(p) for p in re.findall(r"(\d+) % du Smic", " ".join(body))]
        years.append({"label": seg[i], "lines": [own_clean(x) for x in body], "smic": smic})
    contrat = [m.group(0) for m in re.finditer(r"Le contrat d'apprentissage est un contrat de travail[^.]*\.|L'apprentissage repose sur le principe[^.]*\.", text)]
    ver = re.search(r"Vérifié le 0?(\d{1,2} \w+ \d{4}) - Service Public", text)
    return {"ages": ages, "years": years, "contrat": [own_clean(x) for x in contrat], "verifie": ver.group(1) if ver else None}


@check("AV1 the official table read again independently: ages, years, Smic percentages, every line verbatim, contract, date, links")
def av1(c: Ctx):
    A = c.mod("aides")
    if not (AIDES / _file(PAGE)).exists():
        return False, "the official page F2918 is not saved in data/aides"
    text = page_text()
    links = json.loads((AIDES / _file(PAGE, ".links.json")).read_text())
    got = A.r_apprenti(text, links)
    mine = own_read(text)
    bad = []
    if not got or not mine:
        return False, f"read {bool(got)}, independent {bool(mine)}"
    if got["ages"] != mine["ages"] or len(mine["ages"]) != 4:
        bad.append(("ages", got["ages"], mine["ages"]))
    if [a["annee"] for a in got["annees"]] != ["1re année", "2e année", "3e année"] or len(mine["years"]) != 3:
        bad.append("years")
    for a, m in zip(got["annees"], mine["years"]):
        if [x for cell in a["cellules"] for x in cell] != m["lines"]:
            bad.append(("lines of", a["annee"]))
        smic = [int(re.search(r"(\d+) % du Smic", cell[0]).group(1)) for cell in a["cellules"]]
        if smic != m["smic"]:
            bad.append(("percentages", a["annee"], smic, m["smic"]))
    flat = json.dumps(got, ensure_ascii=False)
    for e in EURO.findall(flat):
        if e.replace(" ", " ") not in text.replace(" ", " ") and e.replace("(", "( ") not in text:
            bad.append(("a euro amount not printed on the page", e))
    if got["contrat"] != mine["contrat"] or len(got["contrat"]) != 2:
        bad.append(("contract", got["contrat"]))
    if got["verifie"] != mine["verifie"]:
        bad.append(("date", got["verifie"], mine["verifie"]))
    urls = {u for _, u in links}
    for k in ("entreprises", "simulateur"):
        if not got.get(k) or got[k] not in urls or not got[k].startswith("https://www.service-public.gouv.fr/"):
            bad.append(("link", k, got.get(k)))
    if got["source"] != PAGE:
        bad.append("source")
    read = A.read()
    if not read.get("apprenti") or any(x.startswith("apprenti") for x in read["audit"]):
        bad.append(("aides.read", read.get("audit")))
    return not bad, f"{sum(len(a['cellules']) for a in got['annees'])} cells, {len(got['notes'])} notes; problems {bad[:4]}"


# ------------------------------------------------------------------ AV2 doctored pages
def doctored(text: str) -> dict:
    t1 = re.sub(r"\n2 e année\n(?:.*\n){5}", "\n", text, count=1)
    t2 = text.replace("39 % du Smic, soit 728,14 €", "20 % du Smic, soit 728,14 €", 1)
    t3 = text.replace("39 % du Smic, soit 728,14 €", "52 % du Smic, soit 728,14 €", 1)     # still rising with the year
    t4 = text.replace("\n26 ans et plus\n", "\n", 1)                       # a consistent table of 3 columns, still rising
    t4 = re.sub(r"\n100 % du Smic\nSalaire le \+ élevé entre le Smic[^\n]*", "", t4)
    t6 = text.replace("\n2 e année\n", "\n§\n", 1).replace("\n3 e année\n", "\n2 e année\n", 1).replace("\n§\n", "\n3 e année\n", 1)
    t5 = re.sub(r"L'apprentissage repose sur le principe de l'alternance[^\n]*\n", "", text, count=1)
    return {"a year missing": t1, "falls with the year": t2, "falls with the age": t3, "three columns": t4, "a contract sentence missing": t5,
            "years swapped": t6}


@check("AV2 doctored pages: a year, an age or a sentence missing, a percentage that falls -> no item, said in the audit")
def av2(c: Ctx):
    A = c.mod("aides")
    if not (AIDES / _file(PAGE)).exists():
        return False, "page missing"
    text = page_text()
    bad = []
    for name, t in doctored(text).items():
        if t == text:
            bad.append(("doctoring did nothing", name))
            continue
        if A.r_apprenti(t, []) is not None:
            bad.append(("read anyway", name))
        d = Path(tempfile.mkdtemp())
        try:
            for f in AIDES.iterdir():
                if f.is_file():
                    shutil.copy(f, d / f.name)
            (d / _file(PAGE)).write_text(t)
            r = A.read(d)
            if r.get("apprenti") is not None or not any(x.startswith("apprenti:") for x in r["audit"]):
                bad.append(("audit silent", name))
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return not bad, f"{len(doctored(text))} doctored pages; problems {bad[:4]}"


# ------------------------------------------------------------------ AV3 the list
OFFERS = [
    {"cod_aff_form": "501", "etablissement": "CFA " + HOSTILE, "formation": "BTS - X - en apprentissage", "ville": "Lyon", "academie": "Lyon",
     "lat": 45.7, "lon": 4.8, "statut": "public", "diplome": "BTS - BTSA - BTSM", "mention": "X", "parcours": [], "session_offre": 2026,
     "fiche": "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod=501", "rattachee": ["11", "13"],
     "taux_acces_ens": None, "stats": False, "select_form": None},
    {"cod_aff_form": "502", "etablissement": "CFA B", "formation": "DE - en apprentissage", "ville": "Brest", "academie": "Rennes",
     "lat": None, "lon": None, "statut": "prive_app", "diplome": "D", "mention": "M", "parcours": ["P1"], "session_offre": 2026,
     "fiche": "javascript:alert(1)", "rattachee": [], "taux_acces_ens": None, "stats": False, "select_form": None},
]
BANNED_KEYS = {"zone", "taux_acces_ens", "taux", "pct", "chance", "stats", "select_form", "uncertain", "large", "lec"}


def crafted_con():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, g_ea_lib_vx VARCHAR, lib_for_voe_ins VARCHAR)")
    con.execute("INSERT INTO core.formation_year VALUES ('11', 2025, 'Lycée A', 'BTS X'), ('11', 2024, 'Ancien nom', 'BTS X'), ('12', 2025, 'Lycée C', 'BTS Y'), "
                "('13', 2024, 'Fermé depuis', 'BTS Z')")
    return con


def crafted_mod(c: Ctx, src: str | None = None):
    m = load("apprentissage", src if src is not None else c.src["apprentissage"])
    m.carte = types.SimpleNamespace(apprentissage=lambda con: copy.deepcopy(OFFERS), _offer_session=lambda con: 2026)
    m.AID = types.SimpleNamespace(national=lambda con: {"apprenti": {"titre": "t"}})
    return m


@check("AV3 the list: crafted offers re-derived (order, unknown code, attached names, no figure) and, --real, 60 offers of the latest map")
def av3(c: Ctx, src: str | None = None):
    m = crafted_mod(c, src)
    bad = []
    r = m.voeux(crafted_con(), ["502", "999", "501"])
    if [v["cod_aff_form"] for v in r["voeux"]] != ["502", "999", "501"]:
        bad.append("order")
    st = [v["status"] for v in r["voeux"]]
    if st != ["ok", "absente", "ok"]:
        bad.append(("status", st))
    v501 = r["voeux"][2]
    if v501.get("rattachee") != [{"cod_aff_form": "11", "etablissement": "Lycée A", "formation": "BTS X"},
                                 {"cod_aff_form": "13", "etablissement": None, "formation": None}]:       # named from the latest campaign only
        bad.append(("attached", v501.get("rattachee")))
    if r["voeux"][0].get("rattachee") != []:
        bad.append("a lone offer attached")
    for v in r["voeux"]:
        if BANNED_KEYS & set(v):
            bad.append(("a figure key", sorted(BANNED_KEYS & set(v))))
        if v["status"] == "ok" and any(v.get(k) != next(o for o in OFFERS if o["cod_aff_form"] == v["cod_aff_form"]).get(k)
                                       for k in ("etablissement", "formation", "ville", "fiche", "lat", "parcours")):
            bad.append(("fields differ", v["cod_aff_form"]))
    if r["carte_session"] != 2026 or r["session"] != 2025 or r.get("officiel") != {"titre": "t"}:
        bad.append(("sessions or quote", r["carte_session"], r["session"]))
    n = 0
    if c.real:
        from suptracker import apprentissage as AP
        from suptracker import carte as CA
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            offers = CA.apprentissage(con)
            pick = [o for o in offers if o["rattachee"]][:30] + [o for o in offers if not o["rattachee"]][:30]
            by = {o["cod_aff_form"]: o for o in pick}
            for i in range(0, len(pick), 10):
                ids = [o["cod_aff_form"] for o in pick[i:i + 10]]
                got = AP.voeux(con, ids)
                for v in got["voeux"]:
                    o = by[v["cod_aff_form"]]
                    n += 1
                    if v["status"] != "ok" or v["fiche"] != o["fiche"] or [x["cod_aff_form"] for x in v["rattachee"]] != o["rattachee"]:
                        bad.append(("real", v["cod_aff_form"]))
                    if BANNED_KEYS & set(v):
                        bad.append(("real figure key", v["cod_aff_form"]))
            if got["carte_session"] != con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0]:
                bad.append("real map session")
        finally:
            con.close()
    return not bad, f"3 crafted, {n} real offers; problems {bad[:4]}"


# ------------------------------------------------------------------ AV4 route
@check("AV4 route: 200 / 422, never shared-cached, no audience event, a cache policy")
def av4(c: Ctx):
    bad = []
    if not re.search(r'\(r"/api/apprentissage/voeux", NO_STORE,', c.src["cache"]):
        bad.append("cache.py: no no-store policy")
    fn = re.search(r'@app.get\("/api/apprentissage/voeux"\)\ndef apprentissage_voeux\(.*?(?=\n\S)', c.src["api"], re.S)
    if not fn or 'VX.clean_ids(ids.split(","))' not in fn.group(0) or "raise HTTPException(422, str(exc)) from exc" not in fn.group(0) \
            or "APP.voeux(_con().cursor(), cods)" not in fn.group(0) or re.search(r"\bA\.record|bg\.add_task|track\(", fn.group(0)):
        bad.append("route source: codes not validated (422), or an audience event")
    if c.db is None:
        return not bad, f"no warehouse: route not called; {bad}"
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    cl = TestClient(api.app)
    seen = []
    real_record = A.record
    A.record = lambda *a, **k: seen.append(a)
    try:
        r = cl.get("/api/apprentissage/voeux?ids=3,4")
        if r.status_code != 200 or "no-store" not in (r.headers.get("cache-control") or "") or [v["cod_aff_form"] for v in r.json()["voeux"]] != ["3", "4"]:
            bad.append(f"ok answer {r.status_code} {r.headers.get('cache-control')}")
        if cl.get("/api/apprentissage/voeux").json()["voeux"] != []:
            bad.append("no code: not an empty list")
        for q in ("ids=a1", "ids=" + ",".join(str(i) for i in range(1, 12)), "ids=" + "9" * 300):
            if cl.get(f"/api/apprentissage/voeux?{q}").status_code != 422:
                bad.append(f"{q[:20]} not refused")
    finally:
        A.record = real_record
    if seen:
        bad.append("an audience event recorded")
    return not bad, f"{bad}"


# ------------------------------------------------------------------ AV5 the card (Node)
CARD_NAMES = ("carteFiche", "appParcours", "SP_HOST", "appOfficiel", "listeDate", "appVoeuxCard")
STUB = r"""
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v) => String(v);
const acadLabel = (a) => a;
const frDate = (iso) => `le ${iso}`;
const kmFromHome = () => "";
"""
CARD_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(D.cases.map((k) => appVoeuxCard(k.d, k.cal))));"""


def official_item() -> dict | None:
    A = load("aides", (ROOT / "suptracker" / "aides.py").read_text())
    if not (AIDES / _file(PAGE)).exists():
        return None
    return A.r_apprenti(page_text(), json.loads((AIDES / _file(PAGE, ".links.json")).read_text()))


def card_cases(off: dict) -> list:
    hostile_off = {**off, "notes": [HOSTILE], "annees": [{**off["annees"][0], "cellules": [[HOSTILE]] + off["annees"][0]["cellules"][1:]}] + off["annees"][1:]}
    rows = [{**{k: v for k, v in o.items() if k not in ("rattachee", "taux_acces_ens", "stats", "select_form")}, "status": "ok",
             "rattachee": [{"cod_aff_form": "11", "etablissement": "Lycée " + HOSTILE, "formation": "BTS X"}] if o["rattachee"] else []} for o in OFFERS]
    rows.append({"cod_aff_form": "999", "status": "absente"})
    cal = {"regles": {"apprentissage_max": 10, "apprentissage_apres": True}, "evenements": [{"key": "fin_voeux", "verifie": True, "debut": "2027-03-11"}]}
    liens = {"entreprises": "https://labonnealternance.apprentissage.beta.gouv.fr/"}
    d = {"carte_session": 2026, "session": 2025, "voeux": rows, "officiel": hostile_off, "liens": liens}
    return [{"d": d, "cal": cal}, {"d": {**d, "officiel": {**off, "source": "https://evil.example/F2918"}}, "cal": None},
            {"d": {**d, "officiel": off}, "cal": {"regles": {"apprentissage_max": 12}}}]


def card_problems(outs: list, off: dict) -> list:
    bad = []
    a, b, k = outs
    for i, h in enumerate(outs):
        if "<img" in h or "onerror=alert" in h.replace("onerror=alert(1)&gt;", ""):
            bad.append((i, "raw tag"))
        if "javascript:" in h or "evil.example" in h:
            bad.append((i, "unsafe link"))
        for href in re.findall(r'href="([^"]*)"', h):
            if not re.match(r"https://(dossierappel\.parcoursup\.fr|www\.service-public\.gouv\.fr|labonnealternance\.apprentissage\.beta\.gouv\.fr)/|#/f/\d+$", href):
                bad.append((i, "link", href[:40]))
        txt = re.sub(r"<[^>]+>", " ", h)
        if TU.search(txt) or BAN.search(txt):
            bad.append((i, "tutoiement or a chance"))
        if re.search(r"zone-pill|zbadge|zone ?:|Taux d'accès", h):
            bad.append((i, "a zone or a rate"))
        outside = re.sub(r'<div class="grille-officielle">.*?</div></details>', "", h, flags=re.S)
        if re.search(r"\d\s?%|€", re.sub(r"<[^>]+>", " ", outside)):
            bad.append((i, "a figure outside the official quote"))
        printed = {e for cell in (x for y in off["annees"] for x in y["cellules"]) for line in cell for e in EURO.findall(line)}
        for e in EURO.findall(txt):
            if e not in printed:
                bad.append((i, "a euro amount the page does not print", e))
        if "qu'elle existe toujours" not in h.replace("&#39;", "'"):
            bad.append((i, "absent offer not said"))
        if "Mes vœux en apprentissage (3)" not in h:
            bad.append((i, "its own counter"))
    if "10 vœux supplémentaires pour des formations en apprentissage" not in a.replace("&#39;", "'") or "2027-03-11" not in a:
        bad.append("the official rule or its date")
    if "vérifiez-le sur parcoursup.gouv.fr" not in b or re.search(r"\b10 vœux supplémentaires", b):
        bad.append("no calendar: a typed number")
    if "12 vœux supplémentaires" not in k:
        bad.append("the number not read from the calendar")
    if "grille-officielle" in b:
        bad.append("a quote from a non-official source")
    for line in (x for y in off["annees"] for cell in y["cellules"] for x in cell):
        if line.replace("'", "&#39;") not in k:
            bad.append(("a cell of the table missing", line[:40]))
            break
    if "Lycée &lt;img" not in a or 'href="#/f/11"' not in a:
        bad.append("the attached formation not linked")
    if "SupCompass ne calcule pas votre salaire" not in k:
        bad.append("the quote does not say it is not computed")
    return bad


@check("AV5 the card (Node): escaped, no zone or rate, the official rule or « vérifiez », the quote verbatim, euro only quoted")
def av5(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    off = official_item()
    if not off:
        return False, "official item missing"
    parts = [top(js, n) for n in CARD_NAMES]
    if not all(parts):
        return False, f"missing from app.js: {[n for n, p in zip(CARD_NAMES, parts) if not p]}"
    o = RB.node(STUB + "\n".join(parts) + "\n" + CARD_PROG, {"cases": card_cases(off)})
    if o is None:
        return True, "node absent: not run"
    if isinstance(o, dict):
        return False, o.get("error", "node error")
    bad = card_problems(o, off)
    return not bad, f"{len(o)} cards; problems {bad[:4]}"


# ------------------------------------------------------------------ AV6 the store
STORE_PROG = r"""
const _ls = {}; const localStorage = { getItem: (k) => (k in _ls ? _ls[k] : null), setItem: (k, v) => { _ls[k] = String(v); } };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const document = { addEventListener() {}, querySelectorAll: () => [] };
%s
const out = {};
_ls.voeuxApp = JSON.stringify(["1", 2, "1", "<img>", "3", null, "12345678901", ...Array.from({ length: 20 }, (_, i) => String(100 + i))]);
out.clean = voeuxApp.get();
_ls.voeuxApp = "not json"; out.broken = voeuxApp.get();
_ls.voeuxApp = JSON.stringify({ a: 1 }); out.object = voeuxApp.get();
_ls.voeuxApp = "[]";
for (let i = 0; i < 12; i++) voeuxApp.add(String(i + 1));
out.cap = voeuxApp.get(); out.keys = Object.keys(_ls);
out.full = appVoeuButton("99"); out.has = appVoeuButton("1");
voeuxApp.remove("1"); out.removed = voeuxApp.get();
process.stdout.write(JSON.stringify(out));"""
ALLOWED = {"voeuxApp", "appVoeuLabel", "appVoeuButton", "loadAppVoeux", "transferLink", "transferApply", "transferCard", "bindTransfer",
           "viewTransfert"}


def enclosing(js: str) -> set:
    names = set()
    starts = [(m.start(), m.group(1) or m.group(2)) for m in re.finditer(r"^(?:async )?function (\w+)\(|^(?:const|let) (\w+)\b", js, re.M)]
    for m in re.finditer(r"\bvoeuxApp\b", js):
        line = js[js.rfind("\n", 0, m.start()) + 1: m.start()]
        if line.lstrip().startswith("//"):
            continue                                     # a comment names it, the code does not read it
        prev = [n for s, n in starts if s <= m.start()]
        names.add(prev[-1] if prev else "?")
    return names


@check("AV6 the store: hostile values cleaned, 10 at most, its own key, « liste pleine »; no zone or list reading touches it")
def av6(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    src = "\n".join(top(js, n) for n in ("voeuxApp", "appVoeuLabel", "appVoeuButton"))
    o = RB.node(STORE_PROG % src, {})
    if o is None:
        return True, "node absent: not run"
    if isinstance(o, dict) and set(o) == {"error"}:
        return False, o["error"]
    bad = []
    if o["clean"] != ["1", "3"] + [str(100 + i) for i in range(8)]:
        bad.append(("cleaning", o["clean"]))
    if o["broken"] != [] or o["object"] != []:
        bad.append("a broken value")
    if o["cap"] != [str(i) for i in range(1, 11)] or o["keys"] != ["voeuxApp"]:
        bad.append(("cap or key", o["cap"], o["keys"]))
    if "disabled" not in o["full"] or "liste pleine" not in o["full"] or "Retirer de mes vœux en apprentissage" not in o["has"]:
        bad.append("the button")
    if o["removed"] != [str(i) for i in range(2, 11)]:
        bad.append("remove")
    if 'localStorage.getItem("voeuxApp")' not in top(js, "voeuxApp") or 'localStorage.getItem("voeux")' in top(js, "voeuxApp"):
        bad.append("not its own key")
    users = enclosing(js) - ALLOWED
    if users - {"?"}:
        bad.append(("the apprenticeship list read by", sorted(users)))
    handler = js[js.find('closest("[data-appvoeu]")'):][:600]
    if "/^\\d{1,9}$/.test(cod" not in handler:
        bad.append("the click handler does not check the code")
    return not bad, f"problems {bad[:4]}"


# ------------------------------------------------------------------ AV7 wiring and docs
@check("AV7 wiring and docs: both Mes vœux views, the search card, the formation page, cache, privacy, sources, README, CLAUDE.md, tests")
def av7(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    bad = []
    for v in ("viewVoeux", "viewVoeuxReo"):
        body = top(js, v)
        if body.count("${APP_SECTION}") != 2 or body.count("loadAppVoeux(") != 2:
            bad.append(("both states of", v))
    card = top(js, "carteCard")
    if "${f.stats === false ? appVoeuButton(f.cod_aff_form) :" not in card:
        bad.append("the offer's search card has no button")
    ap = top(js, "apprentiCard")
    if "appVoeuButton(o.cod_aff_form)" not in ap or "${appOfficiel(a.officiel, false)}" not in ap:
        bad.append("the formation page's apprenticeship card")
    if "appVoeuButton(o.cod_aff_form)" not in top(js, "appOffers"):
        bad.append("the search card's CFA lines")
    if "voeuxApp.get()" not in top(js, "bindTransfer"):
        bad.append("the transfer link")
    if "vœux en apprentissage" not in c.src["legal"]:
        bad.append("privacy page")
    if "F2918" not in c.src["sources"] or "salaire minimum de l'apprenti" not in c.src["sources"]:
        bad.append("source register")
    if '"apprenti": r_apprenti' not in c.src["aides"].replace("\n         ", " "):
        bad.append("aides.RULES")
    readme = (ROOT / "README.md").read_text()
    claude = (REPO / "CLAUDE.md").read_text()
    if "Mes vœux en apprentissage" not in readme or "redteam_apprentissage_voeux" not in readme:
        bad.append("README")
    if "Mes vœux en apprentissage (PR 18" not in claude or "never \"Mes vœux\"" in claude:
        bad.append("CLAUDE.md")
    if '"tests/test_apprentissage_voeux.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("durations.json")
    if not (ROOT / "tests" / "test_apprentissage_voeux.py").exists():
        bad.append("tests")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AV8 mutation test
MUTANTS = [
    ("AV1", "aides", "the glossary markers kept", '    s = re.sub(r"\\s*:\\s*titleContent\\b", "", s)\n', ""),
    ("AV1", "aides", "a printed line dropped", "                cells[-1].append(_clean(L[i]))", "                pass"),
    ("AV2", "aides", "no year order check", "        if not m or int(m.group(1)) != len(annees) + 1:", "        if not m:"),
    ("AV2", "aides", "no rise with the year", "        if not pct[0][col] < pct[1][col] < pct[2][col]:", "        if False:"),
    ("AV2", "aides", "no rise with the age", "    if any(row[j] > row[j + 1] for row in pct for j in range(len(row) - 1)):", "    if False:"),
    ("AV2", "aides", "a contract sentence optional", "        if not m:\n            return None\n        contrat.append(", "        if not m:\n            continue\n        contrat.append("),
    ("AV2", "aides", "an age column optional", "    if len(ages) != 4:", "    if len(ages) < 3:"),
    ("AV3", "apprentissage", "the order lost", "    for cod in ids:\n        a = O.get(cod)", "    for cod in sorted(ids):\n        a = O.get(cod)"),
    ("AV3", "apprentissage", "an unknown code dropped", '            out.append({"cod_aff_form": cod, "status": "absente"})\n', ""),
    ("AV3", "apprentissage", "the attached names from an old campaign", "FROM core.formation_year WHERE session = ? AND cod_aff_form IN", "FROM core.formation_year WHERE session <= ? AND cod_aff_form IN"),
    ("AV3", "apprentissage", "a rate key served", '"status": "ok",\n', '"status": "ok", "taux_acces_ens": a.get("taux_acces_ens"),\n'),
    ("AV4", "api", "no validation", '        cods = VX.clean_ids(ids.split(",")) if ids else []', '        cods = ids.split(",") if ids else []'),
    ("AV4", "cache", "shared-cached", '(r"/api/apprentissage/voeux", NO_STORE,', '(r"/api/apprentissage/voeux", PUBLIC,'),
    ("AV5", "js", "a stored string unescaped", '${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(v.etablissement)} ↗</a>` : esc(v.etablissement)}',
     '${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${v.etablissement} ↗</a>` : v.etablissement}'),
    ("AV5", "js", "a typed number of vœux", '    : "Le nombre de vœux en apprentissage permis par Parcoursup n\'a pas pu être lu : vérifiez-le sur parcoursup.gouv.fr.";',
     '    : "Parcoursup permet 10 vœux supplémentaires pour des formations en apprentissage.";'),
    ("AV5", "js", "any source quoted", '  if (!o || !Array.isArray(o.ages) || !Array.isArray(o.annees) || !SP_HOST.test(o.source || "")) return "";',
     '  if (!o || !Array.isArray(o.ages) || !Array.isArray(o.annees)) return "";'),
    ("AV5", "js", "a quoted cell unescaped", '${c.map((x) => esc(x)).join("<br>")}', '${c.join("<br>")}'),
    ("AV5", "js", "the fiche link unchecked", "    const url = carteFiche(v), km = kmFromHome(v.lat, v.lon);", "    const url = v.fiche, km = kmFromHome(v.lat, v.lon);"),
    ("AV5", "js", "« fermée » for an absent offer", "vérifiez sur Parcoursup qu'elle existe toujours.</span>", "elle est fermée.</span>"),
    ("AV5", "js", "a zone drawn", '<span class="badge">en apprentissage</span></td>', '<span class="badge">en apprentissage</span><span class="zone-pill">sécurité</span></td>'),
    ("AV6", "js", "no cap", "    return [...new Set(v.filter((c) => typeof c === \"string\" && /^\\d{1,9}$/.test(c)))].slice(0, this.MAX);\n  },\n  set(v) { try { localStorage.setItem(\"voeuxApp\"",
     "    return [...new Set(v.filter((c) => typeof c === \"string\" && /^\\d{1,9}$/.test(c)))];\n  },\n  set(v) { try { localStorage.setItem(\"voeuxApp\""),
    ("AV6", "js", "the main list's key", 'try { localStorage.setItem("voeuxApp", JSON.stringify(v)); }', 'try { localStorage.setItem("voeux", JSON.stringify(v)); }'),
    ("AV6", "js", "the zones read the apprenticeship list", "  const qs = vxQuery(ids, prof);                                        // the profile bar sends the same query",
     "  const qs = vxQuery([...ids, ...voeuxApp.get()], prof);                                        // the profile bar sends the same query"),
    ("AV7", "js", "the reorientation view forgets the list", "securite: null });\n  loadJpoListe(ids, marker);\n  loadAppVoeux(marker);",
     "securite: null });\n  loadJpoListe(ids, marker);"),
    ("AV7", "js", "the offer card without the button", "${f.stats === false ? appVoeuButton(f.cod_aff_form) :", '${f.stats === false ? "" :'),
]


@check("AV8 mutation test: every seeded bug is caught by AV1-AV7")
def av8(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("AV1", "AV2", "AV3", "AV4", "AV5", "AV6", "AV7") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    missed = []
    for target, where, name, old, new in MUTANTS:
        hay = c.js if where == "js" else c.src[where]
        if hay.count(old) != 1:
            missed.append(f"{name} (anchor {hay.count(old)})")
            continue
        m = copy.copy(c)
        if where == "js":
            m.js = hay.replace(old, new, 1)
        else:
            m.src = {**c.src, where: hay.replace(old, new, 1)}
        try:
            if target == "AV3":
                ok = by[target](m, m.src["apprentissage"])[0]
            else:
                ok = by[target](m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} caught; missed {missed}"


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
