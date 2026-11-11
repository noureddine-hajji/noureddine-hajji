"""Red team of sprint 21, "Je me réoriente ou je reprends mes études" (owner's choices, 2026-11-11).
    python scripts/redteam_reorientation.py [--db data/suptracker.duckdb] [--real]
  E1 the block re-derived in SQL on every row of every campaign (candidates and proposals outside terminale from the published
     counts, the counts that do not hold, the 20-candidate threshold, NULL guards, the cap at 100 and its flag, the share of
     other admits only when the counts add up), and crafted edge rows
  E2 the listing: exactly the latest campaign's SIES formations of the type (apprenticeship offers never), the mention filter,
     each row's block = E1's, only the keys the page reads; unknown or hostile types are a 404
  E3 routes: cache policies (the personal list never shared-cached), no audience event, hostile and too many ids, the
     formation page and Mes vœux blocks = E1's, latest campaign only
  E4 the page in Node: escaping of every stored string, data-label on every cell, "estimation" and the reason when there is
     none, sorted by the student's académie then by name and NEVER by a figure, paged, filters, "C'est ma situation"
  E5 the profile outside terminale: validated status, profile line escaped, profile bar without any zone request, Mes vœux read
     through /api/reorientation/voeux with no zone, no Plan B, no "Compléter ma liste", Mon parcours delegates, Plan B refused
  E6 the formation page: the summary tile shows the estimated access instead of the zone, never both
  E7 wording and wiring: no chance or promise, vouvoiement, the four doors, route, tab, analytics route and feedback page, cache
     policies, feature list, release guard, README and CLAUDE.md
  E8 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import reorientation as RO  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti|vos chances")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
M = {"RO": RO}
S = ("bg", "bt", "bp")
HOSTILE = '<img src=x onerror=alert(1)>"\'&'
BLOCK_START = "// ---- sprint 21: \"Je me réoriente ou je reprends mes études\""
BLOCK_END = "// ---- lot 1 UI: the current tab is marked"


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
        self.stats = (STATIC / "stats.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.cache = (ROOT / "suptracker" / "cache.py").read_text()
        self.analytics = (ROOT / "suptracker" / "analytics.py").read_text()
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self._truth = None

    def truth(self) -> dict:
        """(cod, session) -> the block, by SQL alone (independent of reorientation.py), from the PUBLISHED counts."""
        if self._truth is None:
            rows = self.con.execute("""SELECT session, cod_aff_form,
                    nb_voe_pp_at IS NOT NULL AND prop_tot_at IS NOT NULL AND prop_tot IS NOT NULL AS present,
                    coalesce(nb_voe_pp, 0) + coalesce(nb_voe_pc, 0) AS ca, coalesce(nb_voe_pp_at, 0) + coalesce(nb_voe_pc_at, 0) AS co,
                    coalesce(prop_tot, 0) AS pa, coalesce(prop_tot_at, 0) AS po, taux_acces_ens, acc_tot, acc_neobac, acc_at
                FROM core.formation_year""").fetchall()
            out = {}
            for s, cod, present, ca, co, pa, po, t, tot, neo, at in rows:
                ok = bool(present) and 0 <= po <= co <= ca and po <= pa
                raw = t * (po / co) / (pa / ca) if ok and co >= 20 and t is not None and pa > 0 else None
                coh = tot is not None and neo is not None and at is not None and tot == neo + at
                out[(cod, s)] = {"candidats": co if ok else None, "propositions": po if ok else None, "raw": raw,
                                 "acces_estime": None if raw is None else min(100.0, raw), "plafonne": raw is not None and raw > 100,
                                 "taux_acces_ens": t, "admis": tot, "part_admis_autres": 100 * at / tot if coh and tot else None,
                                 "admis_autres": at if coh and tot else None,
                                 "autres_majoritaires": coh and tot >= 10 and at > neo,
                                 "taux_proposition": round(100 * po / co, 1) if ok and co else None}
            self._truth = out
        return self._truth


def same(b: dict | None, t: dict, keys=None) -> bool:
    if b is None:
        return False
    for k in keys or ("candidats", "propositions", "acces_estime", "plafonne", "taux_acces_ens", "admis", "admis_autres",
                      "part_admis_autres", "autres_majoritaires"):
        x, y = b.get(k), t[k]
        if isinstance(y, float) or isinstance(x, float):
            if x is None or y is None or abs(x - y) > 0.051:
                return False
        elif x != y:
            return False
    return True


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-600:]}


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


def top(js: str, name: str) -> str:
    """A top-level declaration of app.js, up to the next top-level line (continuation lines are indented)."""
    m = re.search(rf"^(?:async function|function|const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        raise KeyError(name)
    nxt = re.search(r"^(?:async function |function |const |let |//|\{|\S+\s*=)", js[m.end():], re.M)
    body = js[m.start(): m.end() + (nxt.start() if nxt else len(js))]
    return body.rstrip() + "\n"


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved, saved_ro = os.environ.get("SUPTRACKER_DB"), A.record, api.RO
    calls = []
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    A.record = lambda *a, **k: calls.append(a) or "ok"
    api.RO = M["RO"]
    try:
        tc = TestClient(api.app)
        tc.events = calls
        yield tc
    finally:
        A.record, api.RO = saved, saved_ro
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


EDGE_COLS = ["nb_voe_pp", "nb_voe_pc", "prop_tot", "taux_acces_ens", "acc_tot", "acc_neobac", "acc_at",
             "nb_voe_pp_at", "nb_voe_pc_at", "prop_tot_at", *(f"{k}_{s}" for s in S for k in ("nb_voe_pp", "nb_voe_pc", "prop_tot"))]


def edge(**kw):
    r = {k: 0 for k in EDGE_COLS}
    r.update(kw)
    return r


EDGES = [   # (row, expected) expected: candidats, propositions, acces_estime, plafonne, part_admis_autres, autres_majoritaires
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=10, acc_tot=20, acc_neobac=8, acc_at=12),
     (40, 10, 60 * (10 / 40) / (50 / 100), False, 60.0, True)),
    (edge(nb_voe_pp=100, nb_voe_pc=20, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=10, nb_voe_pc_at=9, prop_tot_at=10),
     (19, 10, None, False, None, False)),                                      # 19 outside terminale: no estimate
    (edge(nb_voe_pp=100, nb_voe_pc=20, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=30, nb_voe_pc_at=10, prop_tot_at=10),
     (40, 10, 60 * (10 / 40) / (50 / 120), False, None, False)),               # both phases counted, in both rates
    # the published count wins over the difference of the series (here the series would say 60 - 10 = 50 and 40 - 30 = 10)
    (edge(nb_voe_pp=100, prop_tot=40, taux_acces_ens=60, nb_voe_pp_bg=50, prop_tot_bg=30, nb_voe_pp_at=40, prop_tot_at=8),
     (40, 8, 60 * (8 / 40) / (40 / 100), False, None, False)),
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=41), (None, None, None, False, None, False)),  # proposals > candidates
    (edge(nb_voe_pp=100, prop_tot=5, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=6), (None, None, None, False, None, False)),    # more than all proposals
    (edge(nb_voe_pp=30, prop_tot=10, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=5), (None, None, None, False, None, False)),    # more than all candidates
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=-1), (None, None, None, False, None, False)),  # negative
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=None, nb_voe_pp_at=40, prop_tot_at=10), (40, 10, None, False, None, False)),    # no official rate
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=None, prop_tot_at=None), (None, None, None, False, None, False)),  # not published
    (edge(nb_voe_pp=100, prop_tot=0, taux_acces_ens=0, nb_voe_pp_at=40, prop_tot_at=0), (40, 0, None, False, None, False)),          # no proposal
    (edge(nb_voe_pp=100, prop_tot=20, taux_acces_ens=90, nb_voe_pp_at=40, prop_tot_at=20), (40, 20, 100.0, True, None, False)),      # capped
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=100, nb_voe_pp_at=50, prop_tot_at=25), (50, 25, 100.0, False, None, False)),    # exactly 100
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=10, acc_tot=12, acc_neobac=3, acc_at=8),
     (40, 10, 30.0, False, None, False)),                                      # admits that miss the total: no share
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=10, acc_tot=9, acc_neobac=2, acc_at=7),
     (40, 10, 30.0, False, 700 / 9, False)),                                   # 9 admits: a share, not a majority
    (edge(nb_voe_pp=100, prop_tot=50, taux_acces_ens=60, nb_voe_pp_at=40, prop_tot_at=10, acc_tot=10, acc_neobac=5, acc_at=5),
     (40, 10, 30.0, False, 50.0, False)),                                      # a tie is not a majority
]


@check("E1 the block re-derived in SQL on every row, and on crafted edge rows")
def e1(c: Ctx):
    R = M["RO"]
    T = c.truth()
    cols = ", ".join(R.FIELDS)
    bad, n, est, cap, held = [], 0, 0, 0, 0
    for row in c.con.execute(f"SELECT cod_aff_form, session, {cols} FROM core.formation_year").fetchall():
        n += 1
        b = R.block(dict(zip(R.FIELDS, row[2:])), row[1])
        t = T[(row[0], row[1])]
        if not same(b, t, None) or b.get("session") != row[1] or b.get("min_candidats") != 20 \
                or b.get("taux_proposition") != t["taux_proposition"]:
            bad.append((row[0], row[1]))
        est += t["acces_estime"] is not None
        cap += t["plafonne"]
        held += t["candidats"] is not None
    wrong = []
    for r, (cand, prop, acc, pl, part, maj) in EDGES:
        b = R.block(r, 2025)
        got = (b["candidats"], b["propositions"], b["acces_estime"], b["plafonne"], b["part_admis_autres"], b["autres_majoritaires"])
        exp = (cand, prop, None if acc is None else round(acc, 1), pl, None if part is None else round(part, 1), maj)
        if got != exp:
            wrong.append((exp, got))
    cross = c.con.execute("""SELECT session, count(*), count(nb_voe_pp_at),
            count(*) FILTER (WHERE nb_voe_pp = coalesce(nb_voe_pp_bg, 0) + coalesce(nb_voe_pp_bt, 0) + coalesce(nb_voe_pp_bp, 0) + nb_voe_pp_at),
            count(*) FILTER (WHERE prop_tot = coalesce(prop_tot_bg, 0) + coalesce(prop_tot_bt, 0) + coalesce(prop_tot_bp, 0) + prop_tot_at)
        FROM core.formation_year GROUP BY 1 ORDER BY 1""").fetchall()
    published = sum(x[2] for x in cross)
    sums = "; ".join(f"{s0}: {pub}/{tot} published, series + others = total for {a} candidates / {b} proposals" for s0, tot, pub, a, b in cross)
    return not bad and not wrong and published > 0, (f"{sums}. {n} rows: {held} with counts that hold, {est} estimates, {cap} capped at 100; "
                                   f"{len(bad)} differ {bad[:3]}; {len(EDGES) - len(wrong)}/{len(EDGES)} edge rows right {wrong[:2]}")


def types_to_check(c: Ctx) -> list[tuple[str, str | None]]:
    from suptracker import carte as CA
    if c.real:
        bts = CA.formations(c.con, "BTS - BTSA - BTSM")["formations"]
        top_m = max({f.get("mention") for f in bts if f.get("mention")}, key=lambda m: sum(f.get("mention") == m for f in bts))
        return [("BUT", None), ("BUT", "Science des données"), ("BTS - BTSA - BTSM", top_m), ("Licence", None)]
    fac = CA.facets(c.con)["diplomes"]                 # every type the page offers, and one mention of each
    return [(x["label"], None) for x in fac] + [(x["label"], x["mentions"][0]["label"]) for x in fac if x["mentions"]]


@check("E2 the listing: the latest campaign's SIES formations of the type, the mention filter, each block = E1's, slim rows")
def e2(c: Ctx):
    from suptracker import carte as CA
    T = c.truth()
    sies = {r[0] for r in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ?", [c.latest]).fetchall()}
    bad, n, types_seen, appr = [], 0, 0, 0
    with client(c.db) as tc:
        for dip, men in types_to_check(c):
            qs = {"diplome": dip, **({"mention": men} if men else {})}
            r = tc.get("/api/reorientation", params=qs)
            if r.status_code != 200:
                bad.append((dip, men, r.status_code)); continue
            d = r.json()
            types_seen += 1
            lay = CA.formations(c.con, dip, men)
            want = {f["cod_aff_form"] for f in lay["formations"] if f["cod_aff_form"] in sies}
            appr += sum(f["cod_aff_form"] not in sies for f in lay["formations"])
            got = [f["cod_aff_form"] for f in d["formations"]]
            if set(got) != want or len(got) != len(set(got)) or d["session"] != c.latest:
                bad.append((dip, men, "set", len(got), len(want)))
            for f in d["formations"]:
                n += 1
                b = f["reorientation"]
                if men and f.get("mention", men) != men:
                    bad.append((dip, men, "mention", f["cod_aff_form"]))
                if set(f) != {"cod_aff_form", "etablissement", "formation", "ville", "academie", "payant", "reorientation"}:
                    bad.append(("row keys", sorted(f)))
                if b is None or set(b) != set(M["RO"].LIST_KEYS) or not same(b, T[(f["cod_aff_form"], c.latest)]):
                    bad.append((dip, f["cod_aff_form"], "block"))
        for hostile in ("Licence pro", HOSTILE, ""):
            if tc.get("/api/reorientation", params={"diplome": hostile}).status_code not in (404, 422):
                bad.append(("hostile type answered", hostile))
        if tc.get("/api/reorientation").status_code != 422:
            bad.append("no type answered")
    return not bad and types_seen > 0, f"{types_seen} types, {n} rows checked, {appr} apprenticeship offers left out; {len(bad)} problems {bad[:4]}"


@check("E3 routes: cache policies, no audience event, hostile ids, formation and Mes vœux blocks = E1's, latest campaign")
def e3(c: Ctx):
    T = c.truth()
    bad = []
    cods = [r[0] for r in c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY cod_aff_form
        LIMIT 12""", [c.latest]).fetchall()]
    old = c.con.execute("""SELECT cod_aff_form, session FROM core.formation_year WHERE session < ? ORDER BY session, cod_aff_form
        LIMIT 1""", [c.latest]).fetchone()
    with client(c.db) as tc:
        n0 = len(tc.events)
        r = tc.get("/api/reorientation", params={"diplome": "BUT"})
        if "s-maxage" not in r.headers.get("cache-control", "") or r.headers.get("cache-control", "").startswith("no-store"):
            bad.append(("listing cache", r.headers.get("cache-control")))
        for hostile in ("<b>", "1;DROP", ",".join(cods[:11])):
            if tc.get("/api/reorientation/voeux", params={"ids": hostile}).status_code != 422:
                bad.append(("hostile or too many ids answered", hostile[:20]))
        ids = ",".join(cods[:3] + ["99999999", cods[0], " "])
        r = tc.get("/api/reorientation/voeux", params={"ids": ids})
        if "no-store" not in r.headers.get("cache-control", ""):
            bad.append(("voeux cache", r.headers.get("cache-control")))
        d = r.json()
        got = [v["cod_aff_form"] for v in d["voeux"]]
        if got != cods[:3] + ["99999999"] or d["session"] != c.latest:
            bad.append(("ids", got))
        names = {r0[0]: tuple(r0[1:]) for r0 in c.con.execute("""SELECT cod_aff_form, g_ea_lib_vx, lib_for_voe_ins, ville_etab, acad_mies
            FROM core.formation_year WHERE session = ?""", [c.latest]).fetchall()}
        for v in d["voeux"]:
            if v["status"] == "ok" and (v["etablissement"], v["formation"], v["ville"], v["academie"]) != names.get(v["cod_aff_form"]):
                bad.append(("voeux names", v["cod_aff_form"]))
            if v["status"] == "ok" and not same(v["reorientation"], T[(v["cod_aff_form"], c.latest)]):
                bad.append(("voeux block", v["cod_aff_form"]))
            if v["cod_aff_form"] == "99999999" and v["status"] != "absente":
                bad.append("unknown code not absent")
        if old and old[0] not in cods[:3]:
            v = tc.get("/api/reorientation/voeux", params={"ids": old[0]}).json()["voeux"][0]
            if v["status"] == "ok" and (old[0], c.latest) not in T:
                bad.append(("an older campaign read", old))
            if v["status"] == "ok" and not same(v["reorientation"], T[(old[0], c.latest)]):
                bad.append(("not the latest campaign", old))
        if tc.get("/api/reorientation/voeux", params={"ids": "1," * 150}).status_code != 422:
            bad.append("an over-long ids answered")
        f = tc.get(f"/api/formation/{cods[0]}").json()
        if not same(f.get("reorientation"), T[(cods[0], c.latest)]):
            bad.append(("formation block", cods[0]))
        if old:
            f = tc.get(f"/api/formation/{old[0]}", params={"session": old[1]}).json()
            if not same(f.get("reorientation"), T[(old[0], old[1])]):
                bad.append(("formation block of an older campaign", old))
        if len(tc.events) != n0:
            bad.append(("audience event recorded by a route", tc.events[n0:][:1]))
    return not bad, f"{len(cods)} codes; {len(bad)} problems {bad[:4]}"


# ---------------------------------------------------------------- the page in Node
def page_prog(c: Ctx) -> str:
    js = c.js
    parts = [top(js, n) for n in ("fmt", "pct", "pct1", "esc")]
    parts += [top(js, "vxProfile"), top(js, "REO_LABEL"), top(js, "isReo"), top(js, "bacProfile"), top(js, "profileDkey"), top(js, "AUTRES_LABEL"), top(js, "autresBadge"),
              top(js, "voeuButton"), top(js, "bindVoeuButton"), top(js, "profileLine")]
    sec = block(js, BLOCK_START, BLOCK_END)
    return "\n".join(parts) + "\n" + sec


NODE_HARNESS = r"""
let JV = null, PAGE = 3, CALLS = [], PROFILE = null, VOEUX = [];
const store = { d: {}, get(k, x) { return (k in this.d ? JSON.parse(JSON.stringify(this.d[k])) : undefined) ?? x; }, set(k, v) { this.d[k] = v; } };
const voeux = { MAX: 10, get: () => VOEUX.slice(), has: (c) => VOEUX.includes(c), add: (c) => { VOEUX.push(c); return true; }, remove: (c) => { VOEUX = VOEUX.filter((x) => x !== c); } };
const els = {};
const node = (id) => ({ id, value: "", checked: false, onchange: null, onclick: null });
const document = { getElementById: (id) => { const html = $view.innerHTML; return html.includes(`id="${id}"`) ? (els[id] = els[id] || node(id)) : null; } };
const $view = { dataset: {}, innerHTML: "", querySelectorAll: () => [] };
const location = { hash: "" };
const tip = () => "", feedbackBox = (p) => `<fb ${p}>`, searchPage = () => PAGE, profileBar = { render() {} };
let API = {};
const api = async (u) => { CALLS.push(u); for (const k of Object.keys(API)) if (u.startsWith(k)) return JSON.parse(JSON.stringify(API[k])); throw new Error("no stub " + u); };
"""


def run_page(c: Ctx, script: str, data):
    prog = NODE_HARNESS + page_prog(c) + "\n(async () => { const IN = JSON.parse(require('fs').readFileSync(0, 'utf8')); " + script + " })()" \
        ".catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });"
    return node(prog, data)


def listing_fixture(c: Ctx):
    with client(c.db) as tc:
        d = tc.get("/api/reorientation", params={"diplome": "BUT"}).json()
        fac = tc.get("/api/carte").json()
        jv = tc.get("/api/journey/vocab").json()
    return d, fac, jv


@check("E4 the page in Node: escaping, data-label, estimation and reasons, académie then name (never a figure), paging, filters")
def e4(c: Ctx):
    d, fac, jv = listing_fixture(c)
    rows = d["formations"]
    if len(rows) < 3:
        return False, f"too few BUT rows ({len(rows)})"
    acad = next((r["academie"] for r in rows if r["academie"]), "")
    # crafted rows: a hostile name, a missing estimate with each reason, a capped estimate, a hostile académie
    mk = lambda i, **kw: {**rows[i % len(rows)], **kw}  # noqa: E731
    base = rows[0]["reorientation"] or {}
    crafted = [mk(0, cod_aff_form="900001", etablissement="Zeta " + HOSTILE, academie=acad),
               mk(1, cod_aff_form="900002", etablissement="alpha école", academie="Autre"),
               mk(2, cod_aff_form="900003", etablissement="Beta", formation=HOSTILE, ville=HOSTILE, academie=HOSTILE,
                  reorientation={**base, "acces_estime": None, "candidats": 7, "min_candidats": 20}),
               mk(0, cod_aff_form="900004", etablissement="Gamma", academie="Autre", reorientation={**base, "acces_estime": None, "candidats": None}),
               mk(1, cod_aff_form="900005", etablissement="Delta", academie=acad, reorientation={**base, "acces_estime": 100.0, "plafonne": True,
                  "autres_majoritaires": True}),
               mk(2, cod_aff_form="900006", etablissement="Epsilon", academie="Autre", reorientation=None),
               mk(0, cod_aff_form="900007", etablissement="Eta", academie="Autre", reorientation={**base, "acces_estime": 12.3,
                  "plafonne": False, "taux_acces_ens": 77, "part_admis_autres": 61.5, "admis_autres": 8, "admis": 13, "propositions": 5,
                  "candidats": 41})]
    data = {"rows": rows + crafted, "fac": fac, "jv": jv, "acad": acad, "session": d["session"], "hostile": HOSTILE}
    script = r"""
    JV = IN.jv; API = { "/api/carte": IN.fac, "/api/journey/vocab": IN.jv };
    const D = { diplome: "BUT", mention: null, session: IN.session, min_candidats: 20, formations: IN.rows };
    API["/api/reorientation"] = D;
    const out = {};
    // 1. no profile: name order; the académie select has no choice; "C'est ma situation" offered
    PAGE = 1000; await viewReorientation("BUT", "");
    out.plain = $view.innerHTML; out.calls = CALLS.slice();
    // 2. a profile with the académie: that académie first; shuffled figures give the same order
    store.set("profile", { statut: "reorientation", academie: IN.acad });
    await viewReorientation("BUT", ""); out.home = $view.innerHTML;
    const shuffled = IN.rows.map((r, i) => ({ ...r, reorientation: r.reorientation && { ...r.reorientation, acces_estime: (i * 37) % 101, taux_acces_ens: (i * 53) % 101, part_admis_autres: (i * 71) % 101 } }));
    API["/api/reorientation"] = { ...D, formations: shuffled.slice().reverse() };
    await viewReorientation("BUT", ""); out.shuffled = $view.innerHTML;
    // 3. paging: 3 rows, then 6 after "Afficher"
    API["/api/reorientation"] = D; PAGE = 3; await viewReorientation("BUT", ""); out.page1 = $view.innerHTML;
    els.rmore && els.rmore.onclick(); out.page2 = $view.innerHTML;
    // 4. filters: the majority of other admits, the home académie only
    PAGE = 1000; await viewReorientation("BUT", "");
    els.raut.onchange({ target: { checked: true } }); out.autres = $view.innerHTML;
    els.raut.onchange({ target: { checked: false } });
    if (els.rhome) { els.rhome.checked = true; els.rhome.onchange(); } out.onlyhome = $view.innerHTML;
    // 5. "C'est ma situation" from no profile; "Je suis en terminale" back
    store.d = {}; await viewReorientation("BUT", ""); els["reo-me"].onclick(); out.me = store.get("profile", null); out.mine = $view.innerHTML;
    els["reo-back"].onclick(); out.back = store.get("profile", null); out.hash = location.hash;
    store.d = { profile: { statut: "reorientation", serie: "bt", mention: "b", academie: "Lyon" } }; await viewReorientation("BUT", "");
    els["reo-back"].onclick(); out.backBac = store.get("profile", null);
    // 5b. an académie picked with no profile: kept apart, never a profile; it still sorts; "Je suis en terminale" with no bac
    store.d = {}; await viewReorientation("BUT", ""); els.racad.onchange({ target: { value: IN.acad } });
    out.noProfile = store.get("profile", null); out.reoAcad = store.get("reoAcademie", null); out.apart = $view.innerHTML;
    els["reo-me"].onclick(); out.meAcad = store.get("profile", null); els["reo-back"].onclick(); out.backNoBac = store.get("profile", null);
    // 5c. a race: the page is left while the type list loads; the late answer never draws
    store.d = {}; let release; const gate = new Promise((r) => { release = r; });
    const api0 = API["/api/carte"]; const slow = viewReorientation("BUT", "");
    $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; release();
    await slow; out.race = $view.innerHTML;
    // 6. a hostile type in the address falls back to a known one
    store.d = {}; CALLS = []; await viewReorientation(IN.hostile, IN.hostile); out.hostileCalls = CALLS.slice();
    console.log(JSON.stringify(out));
    """
    r = run_page(c, script, data)
    if r is None:
        return True, "node absent: skipped"
    if "error" in r:
        return False, r["error"]
    bad = []
    import html as H
    trs = lambda h: re.findall(r'<tr><td data-label="Formation"><a href="#/f/([^"]+)">', h)  # noqa: E731
    order_plain, order_home, order_shuf = trs(r["plain"]), trs(r["home"]), trs(r["shuffled"])
    by = {x["cod_aff_form"]: x for x in data["rows"]}
    if sorted(order_plain) != sorted(by):
        bad.append(("rows missing", len(order_plain), len(by)))
    home_flags = [by[k]["academie"] == acad for k in order_home]
    if home_flags != sorted(home_flags, reverse=True):
        bad.append("the student's académie is not first")
    if order_home != order_shuf:
        bad.append("the order depends on a figure or on the answer's order")
    names = [f"{by[k]['etablissement']} {by[k]['formation']}".casefold() for k in order_plain]
    inv = sum(1 for a, b in zip(names, names[1:]) if a > b and a.split()[0][:1].isascii() and b.split()[0][:1].isascii()
              and a.split()[0][:1].isalpha() and b.split()[0][:1].isalpha() and a.split()[0][0] != b.split()[0][0])
    if inv:
        bad.append(("not by name", inv))
    for k in ("plain", "home", "page2", "autres", "mine"):
        h = r[k]
        if HOSTILE in h or "<img" in h:
            bad.append((k, "unescaped string"))
        for td in re.findall(r"<td(?![^>]*data-label=)[^>]*>", h):
            bad.append((k, "cell without data-label", td)); break
    h = r["plain"]
    if "estimation" not in h or "plafonnée à 100 %" not in h or "moins de 20 candidats hors terminale (7)" not in h \
            or "effectifs publiés incohérents" not in h or "pas de chiffres pour cette formation" not in h:
        bad.append("an estimate, the cap or a reason is not said")
    if "C'est ma situation" not in h or "Ordre : le nom de l'établissement" not in H.unescape(h):
        bad.append("no situation button or no order sentence")
    if "Ordre : l'académie de" not in r["home"]:
        bad.append("the order sentence ignores the académie")
    if len(trs(r["page1"])) != 3 or len(trs(r["page2"])) != 6:
        bad.append(("paging", len(trs(r["page1"])), len(trs(r["page2"]))))
    if any(not by[k]["reorientation"] or not by[k]["reorientation"].get("autres_majoritaires") for k in trs(r["autres"])) \
            or not trs(r["autres"]):
        bad.append("the other-admits filter")
    if any(by[k]["academie"] != acad for k in trs(r["onlyhome"])) or not trs(r["onlyhome"]):
        bad.append("the académie filter")
    if not r["me"] or r["me"].get("statut") != "reorientation" or "Je suis en terminale" not in r["mine"]:
        bad.append(("C'est ma situation", r["me"]))
    if r["back"] is not None or r["hash"] != "#/parcours":
        bad.append(("back to terminale with no bac: a profile invented", r["back"], r["hash"]))
    if not r["backBac"] or r["backBac"].get("statut") != "terminale" or r["backBac"].get("serie") != "bt" or r["backBac"].get("mention") != "b":
        bad.append(("back to terminale: the bac entered is lost", r["backBac"]))
    if any(HOSTILE in u or "<" in u for u in r["hostileCalls"]) or not any(u.startswith("/api/reorientation?diplome=") for u in r["hostileCalls"]):
        bad.append(("hostile type sent", r["hostileCalls"]))
    eta = re.search(r'href="#/f/900007">.*?</tr>', r["plain"], re.S)
    cells = re.findall(r'data-label="([^"]+)">(.*?)</td>', eta.group(0), re.S) if eta else []
    got = {k: re.sub(r"<[^>]+>", " ", v) for k, v in cells}
    if not eta or not got.get("Accès estimé hors terminale", "").strip().startswith("12,3 %") \
            or "5 propositions pour 41 candidats" not in got.get("Accès estimé hors terminale", "") \
            or got.get("Taux d'accès officiel, tous candidats", "").strip() != "77 %" \
            or not got.get("Admis hors néo-bacheliers", "").strip().startswith("61,5 %") or "8 sur 13 admis" not in got.get("Admis hors néo-bacheliers", ""):
        bad.append(("a figure in the wrong cell", got))
    if r["noProfile"] is not None or r["reoAcad"] != acad or "Ordre : l'académie de" not in r["apart"]:
        bad.append(("an académie picked with no profile", r["noProfile"], r["reoAcad"]))
    if not r["meAcad"] or r["meAcad"].get("academie") != acad or r["meAcad"].get("statut") != "reorientation" or r["backNoBac"] is not None:
        bad.append(("status switches with no bac", r["meAcad"], r["backNoBac"]))
    if r["race"] != "OTHER PAGE":
        bad.append("a late answer drew over another page")
    if any("academie" in u or "statut" in u for u in r["calls"]):
        bad.append(("the académie or the status sent to the server", r["calls"]))
    return not bad, f"{len(order_plain)} rows rendered; {len(bad)} problems {bad[:4]}"


@check("E5 profile outside terminale: validated, escaped, no zone request, Mes vœux without zones / Plan B / Compléter, delegation")
def e5(c: Ctx):
    js = c.js
    bad = []
    # static wiring: delegation happens before any positioning or zone request
    vp = block(js, "async function viewParcours()", "\n}\n")
    if not re.search(r"^\s*if \(isReo\(store\.get\(\"profile\", null\)\)\) return viewReorientation\(", vp.split("\n")[1]):
        bad.append("Mon parcours does not delegate first")
    vv = block(js, "async function viewVoeux()", "\n}\n")
    i = vv.find("if (isReo(prof)) return viewVoeuxReo(ids, prof);")
    if i < 0 or i > vv.find("api(") or i > vv.find("vxQuery("):
        bad.append("Mes vœux does not switch before the zone request")
    pf = top(js, "profileForm")
    if 'name="statut"' not in pf or "REO_LABEL" not in pf:
        bad.append("no situation in the profile form")
    if 'statut: fd.get("statut") === "reorientation" ? "reorientation" : "terminale"' not in vp:
        bad.append("the form does not store a validated status")
    for fn in ("doubletteCard", "juryCard", "semblablesJuryCard", "doubletteCharts", "viewCarte", "profileRows"):
        try:
            body = top(js, fn)
        except KeyError:
            bad.append(("page gone", fn)); continue
        raw = [m.start() for m in re.finditer(r'store\.get\("profile"', body) if not body[max(0, m.start() - 6):m.start()].endswith("isReo(")]
        if raw or "bacProfile()" not in body:
            bad.append(("reads the bac without bacProfile", fn))
    # profile bar, Mes vœux and Plan B run in Node
    harness = top(js, "PB_ZONES") + top(js, "vxQuery") + "\nconst ZONES = {securite:{label:'s',color:'x'},cible:{label:'c',color:'x'},ambitieux:{label:'a',color:'x'}};\n" \
        + top(js, "profileBar") + "\nlet planbSeq = 0;\n" + top(js, "loadPlanB")
    script = r"""
    const out = {};
    const el = { hidden: false, innerHTML: "" };
    const realGet = document.getElementById; document.getElementById = (id) => id === "profile-bar" ? el : realGet(id);
    // profile bar outside terminale: no request, the status and the count
    store.set("profile", { statut: "reorientation", academie: IN.hostile, serie: "bg", mention: "tb" }); VOEUX = ["1", "2"]; CALLS = [];
    profileBar.render("home"); out.bar = el.innerHTML; out.barCalls = CALLS.slice();
    // a hostile status is "terminale"
    out.hostileStatut = vxProfile({ statut: IN.hostile }).statut; out.okStatut = vxProfile({ statut: "reorientation" }).statut;
    out.line = profileLine(vxProfile({ statut: "reorientation", academie: IN.hostile }), "bg");
    // Plan B: refused before any request
    const box = { innerHTML: "", dataset: {}, isConnected: true, querySelector: () => null, querySelectorAll: () => [] };
    CALLS = []; await loadPlanB("123", { box, profile: { statut: "reorientation" } }); out.pb = box.innerHTML; out.pbCalls = CALLS.slice();
    const box2 = { ...box, innerHTML: "" }; await loadPlanB("123", { box: box2, profile: { statut: "reorientation" }, inline: true }); out.pbInline = box2.innerHTML;
    // Mes vœux outside terminale
    API = { "/api/reorientation/voeux": IN.vx }; CALLS = [];
    await viewVoeuxReo(IN.ids, vxProfile({ statut: "reorientation", academie: IN.hostile })); out.vx = $view.innerHTML; out.vxCalls = CALLS.slice();
    CALLS = []; await viewVoeuxReo([], vxProfile({ statut: "reorientation" })); out.vxEmpty = $view.innerHTML; out.vxEmptyCalls = CALLS.slice();
    const slow = viewVoeuxReo(IN.ids, vxProfile({ statut: "reorientation" })); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other";
    await slow; out.vxRace = $view.innerHTML;
    // the bac of a reorientation profile is never read: no doublette, no bac profile
    store.set("profile", { statut: "reorientation", serie: "bg", spe1: "MATHS", spe2: "PC", mention: "b" });
    out.dkey = profileDkey(store.get("profile", null)); out.bac = bacProfile();
    store.set("profile", { statut: "terminale", serie: "bg", spe1: "MATHS", spe2: "PC", mention: "b" }); out.dkeyT = profileDkey(bacProfile());
    console.log(JSON.stringify(out));
    """
    with client(c.db) as tc:
        cods = [r[0] for r in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY 1 LIMIT 2",
                                            [c.latest]).fetchall()]
        vx = tc.get("/api/reorientation/voeux", params={"ids": ",".join(cods + ["99999999"])}).json()
    vx["voeux"][0] = {**vx["voeux"][0], "etablissement": HOSTILE, "formation": HOSTILE}
    prog = NODE_HARNESS.replace("profileBar = { render() {} }", "profileBar_ = 0") + page_prog(c) + harness + \
        "\n(async () => { const IN = JSON.parse(require('fs').readFileSync(0, 'utf8')); " + script + \
        " })().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });"
    r = node(prog, {"hostile": HOSTILE, "vx": vx, "ids": cods + ["99999999"]})
    if r is None:
        return not bad, "node absent: static part only"
    if "error" in r:
        return False, r["error"]
    if r["barCalls"] or "Je ne suis plus en terminale" not in r["bar"] or "Mes vœux : 2" not in r["bar"] or HOSTILE in r["bar"] \
            or "pb-zone" in r["bar"] or "pb-alert" in r["bar"]:
        bad.append(("profile bar", r["barCalls"], r["bar"][:160]))
    if r["hostileStatut"] != "terminale" or r["okStatut"] != "reorientation":
        bad.append("status not validated")
    if HOSTILE in r["line"] or "Je ne suis plus en terminale" not in r["line"]:
        bad.append(("profile line", r["line"]))
    if r["pbCalls"] or "n'est pas proposé" not in r["pb"] or "n'est pas proposé" not in r["pbInline"]:
        bad.append(("Plan B outside terminale", r["pbCalls"]))
    v = r["vx"]
    if r["vxCalls"] != [f"/api/reorientation/voeux?ids={'%2C'.join(cods + ['99999999'])}"]:
        bad.append(("Mes vœux request", r["vxCalls"]))
    if HOSTILE in v or "<img" in v:
        bad.append("Mes vœux unescaped")
    for td in re.findall(r"<td(?![^>]*data-label=)[^>]*>", v):
        bad.append(("Mes vœux cell without data-label", td)); break
    if any(w in v for w in ("data-vxplanb", "vx-completer", "sum-tile", "zone-pill", "Vœu de sécurité", "Voir un plan B")):
        bad.append("Mes vœux shows a zone, a Plan B or Compléter")
    if "absente de la campagne" not in v or "estimation" not in v or "ne sont pas proposés" not in v or "data-vxdel" not in v:
        bad.append("Mes vœux misses the absent row, the estimation, the reason or the remove button")
    if r["vxRace"] != "OTHER PAGE":
        bad.append("Mes vœux: a late answer drew over another page")
    if r["dkey"] is not None or r["bac"] is not None or r["dkeyT"] != "MATHS+PC":
        bad.append(("the bac of a reorientation profile is read", r["dkey"], r["bac"], r["dkeyT"]))
    if r["vxEmptyCalls"] or "Votre liste est vide" not in r["vxEmpty"]:
        bad.append("empty list requested")
    return not bad, f"{len(bad)} problems {bad[:4]}"


@check("E6 the formation page: the estimated access replaces the zone tile outside terminale, never both")
def e6(c: Ctx):
    js = c.js
    harness = top(js, "admisBar") + top(js, "summaryBand")
    vf = top(js, "viewFormation")
    more = vf[vf.find("Plus de chiffres sur l'admission"):]
    more = more[:more.find("</details>")]
    with client(c.db) as tc:
        cod = c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND taux_acces_ens IS NOT NULL
            ORDER BY nb_voe_pp DESC LIMIT 1""", [c.latest]).fetchone()[0]
        d = tc.get(f"/api/formation/{cod}").json()
    script = r"""
    const out = {};
    store.set("profile", { statut: "reorientation" }); out.reo = summaryBand(IN.d.record, IN.d);
    out.none = summaryBand(IN.d.record, { ...IN.d, reorientation: { ...IN.d.reorientation, acces_estime: null, candidats: 3 } });
    store.set("profile", { statut: "terminale", serie: "bg" }); out.term = summaryBand(IN.d.record, IN.d);
    store.d = {}; out.nop = summaryBand(IN.d.record, IN.d);
    out.card = reoCard({ ...IN.d.reorientation, session: IN.hostile }); out.cardNone = reoCard(null);
    out.candFmt = fmt(IN.d.reorientation.candidats);
    console.log(JSON.stringify(out));
    """
    prog = NODE_HARNESS + page_prog(c) + harness + "\n(async () => { const IN = JSON.parse(require('fs').readFileSync(0, 'utf8')); " \
        + script + " })().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });"
    r = node(prog, {"d": d, "hostile": HOSTILE})
    if r is None:
        return True, "node absent: skipped"
    if "error" in r:
        return False, r["error"]
    bad = []
    est = d["reorientation"]["acces_estime"]
    want = "—" if est is None else f"{est:.1f}".replace(".", ",").replace(",0", "") + " %"
    if "Accès estimé hors terminale" not in r["reo"] or 'id="sum-zone"' in r["reo"] or "Votre zone" in r["reo"]:
        bad.append("outside terminale: no estimate tile, or a zone tile")
    if est is not None and want.split()[0] not in r["reo"]:
        bad.append(("the estimate is not the block's", want))
    if "moins de 20 candidats hors terminale (3)" not in r["none"]:
        bad.append("no reason when there is no estimate")
    if 'id="sum-zone"' not in r["term"] or "Accès estimé hors terminale" in r["term"]:
        bad.append("in terminale: the zone tile is gone or the estimate shows")
    if "Accès estimé hors terminale" in r["nop"]:
        bad.append("no profile: the estimate shows")
    b = d["reorientation"]
    if "${reoCard(d.reorientation)}" not in more:
        bad.append("the calculation card is not folded in « Plus de chiffres sur l'admission »")
    if HOSTILE in r["card"] or r["cardNone"] or (b["candidats"] is not None and f"pour {r['candFmt']} candidats" not in r["card"]) \
            or "plafonné à 100 %" not in r["card"]:
        bad.append("the calculation card: counts, method or escaping")
    return not bad, f"formation {cod} (estimate {est}); {len(bad)} problems {bad[:3]}"


def texts(js: str) -> str:
    sec = block(js, BLOCK_START, BLOCK_END)
    return " ".join(a or b for a, b in re.findall(r"`([^`]*)`|\"([^\"]*)\"", sec))


@check("E7 wording and wiring: no chance, vouvoiement, four doors, route, tab, analytics, cache, features, release, docs")
def e7(c: Ctx):
    js, bad = c.js, []
    t = texts(js)
    if CHANCE.search(t):
        bad.append(("chance wording", CHANCE.search(t).group(0)))
    words = re.sub(r"<[^>]+>|\$\{[^}]*\}", " ", t)
    if FORMAL.search(words):
        bad.append(("tutoiement", FORMAL.search(words).group(0)))
    for need in ("pas des chances d'admission", "pas un taux officiel ni une chance d'admission", "plafonné à 100 %",
                 "aucune zone (sécurité, cible, ambitieux)", "jamais les chiffres"):
        if need not in t:
            bad.append(("missing", need))
    home = top(js, "viewHome")
    doors = re.findall(r'class="door"', home)
    if len(doors) != 4 or 'href="#/reorientation"' not in home or "Je me réoriente ou je reprends mes études" not in home:
        bad.append(("doors", len(doors)))
    if 'if (a === "reorientation") return await viewReorientation(b || "", c || "");' not in js:
        bad.append("no route")
    if not re.search(r'const ROUTE_NAME = \{[^}]*reorientation: "reorientation"', js) or not re.search(r'const TAB_OF = \{[^}]*reorientation: "parcours"', js):
        bad.append("route name or tab")
    if not re.search(r'ROUTES = \([^)]*"reorientation"\)', c.analytics) or not re.search(r'FEEDBACK_PAGES = \([^)]*"reorientation"', c.analytics):
        bad.append("analytics route or feedback page")
    if 'reorientation: "Je me réoriente"' not in c.stats:
        bad.append("dashboard label")
    if not re.search(r'\(r"/api/reorientation", PUBLIC,', c.cache) or not re.search(r'\(r"/api/reorientation/voeux", NO_STORE,', c.cache):
        bad.append("cache policies")
    if '"reorientation"]' not in c.api or '"reorientation": RO.for_formation(' not in c.api:
        bad.append("feature list or formation block")
    rel = (ROOT / "tests" / "test_release.py").read_text()
    if '"reorientation": ("app.js", "async function viewReorientation(")' not in rel:
        bad.append("release guard")
    readme = (ROOT.parent / "README.md") if (ROOT.parent / "README.md").exists() else ROOT / "README.md"
    docs = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    docs += readme.read_text() if readme.exists() else ""
    if "Je me réoriente" not in docs:
        bad.append("README section")
    claude = ROOT.parent / "CLAUDE.md"
    if claude.exists() and "reorientation.py" not in claude.read_text():
        bad.append("CLAUDE.md rule")
    return not bad, f"{len(bad)} problems {bad[:5]}"


# ---------------------------------------------------------------- mutation test
PY_MUTANTS = [
    ("threshold lowered", "MIN_CANDIDATS = 20", "MIN_CANDIDATS = 2"),
    ("no cap", "est, capped = round(min(100.0, raw), 1), raw > 100", "est, capped = round(raw, 1), raw > 100"),
    ("cap flag at 100", "raw > 100", "raw >= 100"),
    ("negative proposals kept", "and 0 <= prop <= cand <= cand_all", "and prop <= cand <= cand_all"),
    ("proposals above candidates kept", "and 0 <= prop <= cand <= cand_all", "and 0 <= prop and cand <= cand_all"),
    ("more than all proposals kept", ' and prop <= z("prop_tot"))', ")"),
    ("complementary phase of the others forgotten", 'cand = z("nb_voe_pp_at") + z("nb_voe_pc_at")', 'cand = z("nb_voe_pp_at")'),
    ("series difference instead of the published count", 'prop = z("prop_tot_at")', 'prop = z("prop_tot") - z("prop_tot_bg") - z("prop_tot_bt") - z("prop_tot_bp")'),
    ("no scaling", 'raw = taux * (prop / cand) / (z("prop_tot") / cand_all)', 'raw = taux * (prop / cand) / 1'),
    ("share when the counts miss the total", "if tot and ADM.coherent(tot, neo, at) else None", "if tot else None"),
    ("majority without the threshold", '"autres_majoritaires": ADM.autres_majoritaires(tot, neo, at)', '"autres_majoritaires": part is not None and part > 50'),
    ("oldest campaign for Mes vœux", "session = (SELECT max(session) FROM core.formation_year)", "session = (SELECT min(session) FROM core.formation_year)"),
    ("apprenticeship offers listed", 'if f.get("stats") is not False]', "if True]"),
    ("estimate dropped from the list", '"candidats", "propositions", "acces_estime", "plafonne"', '"candidats", "propositions", "plafonne"'),
]
JS_MUTANTS = [
    ("sorted by the estimate", '|| by(a).localeCompare(by(b), "fr", { sensitivity: "base" })',
     '|| ((b.reorientation || {}).acces_estime || 0) - ((a.reorientation || {}).acces_estime || 0) || by(a).localeCompare(by(b), "fr", { sensitivity: "base" })'),
    ("académie not first", "(home ? (b.academie === home) - (a.academie === home) : 0)", "0"),
    ("name unescaped", '<a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}${f.academie ?',
     '<a href="#/f/${esc(f.cod_aff_form)}">${f.etablissement}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}${f.academie ?'),
    ("cell without label", '<td class="num" data-label="Admis hors néo-bacheliers">${reoAutres(b)}</td>\n      <td class="acts" data-label="Mes vœux">${voeuButton',
     '<td class="num">${reoAutres(b)}</td>\n      <td class="acts" data-label="Mes vœux">${voeuButton'),
    ("estimation word dropped", '<div class="estim">estimation${b.plafonne', '<div class="estim">${b.plafonne'),
    ("cap not said", '${b.plafonne ? ", plafonnée à 100 %" : ""}', ""),
    ("threshold reason dropped", "`moins de ${b.min_candidats} candidats hors terminale (${b.candidats}) : pas d'estimation`", '"pas d\'estimation"'),
    ("paging broken", "rows.slice(0, shown).map(row)", "rows.map(row)"),
    ("other-admits filter ignored", "(!onlyAutres || (f.reorientation && f.reorientation.autres_majoritaires))", "true"),
    ("académie sent", 'const qs = new URLSearchParams({ diplome: D.label });', 'const qs = new URLSearchParams({ diplome: D.label, academie: "x" });'),
    ("situation not stored", 'if (me) me.onclick = () => { setStatut("reorientation"); draw(); };', 'if (me) me.onclick = () => { draw(); };'),
    ("Plan B for a reorientation profile", "  if (isReo(p)) {                                                     // sprint 21", "  if (false) {"),
    ("profile bar zone request", "    if (isReo(prof)) {                                                   // sprint 21", "    if (false) {"),
    ("status not validated", 'statut: p.statut === "reorientation" ? "reorientation" : "terminale" };', "statut: p.statut };"),
    ("académie unescaped in the profile line", '[REO_LABEL, p.academie ? `académie de ${esc(p.academie)}`', '[REO_LABEL, p.academie ? `académie de ${p.academie}`'),
    ("Mes vœux reads zones", "  if (isReo(prof)) return viewVoeuxReo(ids, prof);", ""),
    ("Mes vœux reo through the zone route", "d = await api(`/api/reorientation/voeux?${qs}`)", "d = await api(`/api/voeux?${qs}`)"),
    ("Mes vœux reo name unescaped", '${esc(v.etablissement)}</a><div class="muted small">${esc(v.formation)} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}</div>${v.reorientation',
     '${v.etablissement}</a><div class="muted small">${esc(v.formation)} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}</div>${v.reorientation'),
    ("Mon parcours does not delegate", '  if (isReo(store.get("profile", null))) return viewReorientation("", "");', ""),
    ("zone tile outside terminale", "${isReo(prof) ? tile(", "${false ? tile("),
    ("door removed", '<a class="door" href="#/reorientation">', '<a class="doorx" href="#/reorientation">'),
    ("chance wording", "Les chiffres ci-dessous sont des parts", "Vous serez admis : les chiffres ci-dessous sont des parts"),
    ("tutoiement", "<p>Vous n'êtes plus en terminale", "<p>Tu n'es plus en terminale"),
    # independent review's gaps
    ("official rate shown as the estimate", '${pct1(b.acces_estime)}<div class="estim">estimation', '${pct1(b.taux_acces_ens)}<div class="estim">estimation'),
    ("share of other admits reversed", "`${pct1(b.part_admis_autres)}<div", "`${pct1(100 - b.part_admis_autres)}<div"),
    ("race guard dropped (list)", "  if ($view.dataset.rendered !== first) return;\n  JV = V;", "  JV = V;"),
    ("race guard dropped (Mes vœux)", "  if ($view.dataset.rendered !== marker) return;\n  const ok = d.voeux", "  const ok = d.voeux"),
    ("académie stored as a profile", 'else store.set("reoAcademie", e.target.value);', 'else store.set("profile", { academie: e.target.value });'),
    ("terminale profile invented", 'else store.set("profile", null);', 'else store.set("profile", { ...(p0 || {}), statut: st });'),
    ("bacProfile ignores the status", "!Array.isArray(p) && !isReo(p) ? p : null;", "!Array.isArray(p) ? p : null;"),
    ("map reads the raw profile", "  const P = bacProfile();", '  const P = store.get("profile", null);'),
    ("calculation card dropped", "  ${reoCard(d.reorientation)}\n", ""),
    ("calculation card without counts", "${fmt(b.propositions)} propositions pour ${fmt(b.candidats)} candidats hors terminale (${pct1(b.taux_proposition)})",
     "des propositions (${pct1(b.taux_proposition)})"),
]
TEXT_MUTANTS = [("cache", "voeux route shared-cached", '(r"/api/reorientation/voeux", NO_STORE,', '(r"/api/reorientation/voeux", PUBLIC,'),
                ("analytics", "feedback page refused", '"voeux", "reorientation")', '"voeux")')]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "reorientation.py"
    src = path.read_text()
    if src.count(old) != 1:
        return None
    m = types.ModuleType("suptracker._mut_reorientation")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("E8 mutation test: rule, listing, routes, page, profile, wording and wiring bugs are each caught")
def e8(c: Ctx):
    fns = [e1, e7, e6, e5, e4, e2, e3]
    missed = []

    def caught():
        c._truth = c._truth          # the SQL truth never depends on the module
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    for name, old, new in PY_MUTANTS:
        m = mutated(old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M["RO"] = M["RO"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["RO"] = saved
            sys.modules.pop("suptracker._mut_reorientation", None)
    for name, old, new in JS_MUTANTS:
        src = c.js
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone or not unique: {src.count(old)})"); continue
        c.js = src.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = src
    for attr, name, old, new in TEXT_MUTANTS:
        src = getattr(c, attr)
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone)"); continue
        setattr(c, attr, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, attr, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS) + len(TEXT_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, checks=None) -> list[dict]:
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
    c.con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
