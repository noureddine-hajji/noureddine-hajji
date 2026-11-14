"""Red team of "Qui sont les admis ?" (owner's request, 2026-11-10): néo-bacheliers and the other admits, on the formation
page ("L'essentiel") and as a label in the lists (search, comparator, map, Mes vœux).
    python scripts/redteam_admis.py [--db data/suptracker.duckdb] [--real]
  H1 the rule re-derived in SQL on every row of every campaign (published counts add up, at least 10 admits, other admits
     strictly more than néo-bacheliers), and crafted edge rows (tie, 9 admits, counts that miss the total, nulls, no admit)
  H2 every route that feeds a list or the formation page carries the server's rule, re-derived in SQL: search (words and a
     formation code), comparator, map (apprenticeship offers never labelled), Mes vœux; the search index documents are never
     modified by the label
  H3 the page in Node: the bar only when the counts add up, widths from the published counts, its text alternative, the
     published share of néo-bacheliers, the label only from the server's flag, the comparator cell
  H4 wording: no chance or promise, vouvoiement, the mentions and series cover néo-bacheliers only, SIES does not detail the
     other admits
  H5 wiring and design: every list renders the label, the summary renders the bar, own colour tokens in both themes (never a
     zone's, a route's or the accent), feature list, release guard
  H6 mutation test (in memory)
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
from suptracker import admis as ADM  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
API = ROOT / "suptracker" / "api.py"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
LABEL = "Majorité d'admis hors néo-bacheliers"
M = {"ADM": ADM}
RULE_SQL = "acc_tot >= 10 AND acc_tot = acc_neobac + acc_at AND acc_at > acc_neobac"


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
        self.css = (STATIC / "style.css").read_text()
        self.api = API.read_text()
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


@contextmanager
def client(db: Path, mod=None):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved, saved_adm = os.environ.get("SUPTRACKER_DB"), A.record, api.ADM
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    api.ADM = mod or M["ADM"]
    try:
        yield TestClient(api.app)
    finally:
        A.record, api.ADM = saved, saved_adm
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def truth(c: Ctx, keys) -> dict:
    """(cod, session) -> the rule, by SQL alone (absent row = False)."""
    by: dict = {}
    for cod, s in keys:
        by.setdefault(s, set()).add(cod)
    out = {(cod, s): False for cod, s in keys}
    for s, cods in by.items():
        for cod, v in c.con.execute(f"""SELECT cod_aff_form, coalesce({RULE_SQL}, false) FROM core.formation_year
                WHERE session = ? AND cod_aff_form IN (SELECT unnest(?))""", [s, sorted(cods)]).fetchall():
            out[(cod, s)] = bool(v)
    return out


@check("H1 the rule re-derived in SQL on every row, and on crafted edge rows")
def h1(c: Ctx):
    A = M["ADM"]
    bad, n, yes = [], 0, 0
    for s, cod, t, neo, at, pn, want in c.con.execute(f"""SELECT session, cod_aff_form, acc_tot, acc_neobac, acc_at, pct_neobac,
            coalesce({RULE_SQL}, false) FROM core.formation_year""").fetchall():
        n += 1
        yes += want
        got = A.autres_majoritaires(t, neo, at)
        rep = A.repartition({"session": s, "acc_tot": t, "acc_neobac": neo, "acc_at": at, "pct_neobac": pn})
        exp = None if not t else {"session": s, "admis": t, "admis_neobac": neo, "admis_autres": at, "pct_neobac": pn,
                                  "coherent": t == neo + at, "autres_majoritaires": bool(want), "min_admis": 10}
        if got != bool(want) or rep != exp:
            bad.append(cod)
    edge = {(10, 5, 5): False, (10, 4, 6): True, (9, 2, 7): False, (12, 3, 8): False, (12, 3, None): False,
            (None, 3, 8): False, (0, 0, 0): False, (40, 1, 39): True, (40, 39, 1): False}
    wrong = [k for k, v in edge.items() if A.autres_majoritaires(*k) != v]
    empty = A.repartition({"acc_tot": 0, "acc_neobac": 0, "acc_at": 0}) is None
    # a crafted warehouse holding every case (a fixture may hold none): two campaigns that disagree, a tie, counts that miss
    # the total; rows outside the list never labelled; the input dicts never modified (they can be shared documents)
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA core")
    mem.execute("CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, acc_tot BIGINT, acc_neobac BIGINT, acc_at BIGINT)")
    mem.execute("""INSERT INTO core.formation_year VALUES (2024, 'A', 30, 5, 25), (2024, 'B', 30, 25, 5), (2025, 'A', 30, 25, 5),
        (2025, 'B', 30, 5, 25), (2025, 'C', 21, 7, 13), (2025, 'D', 10, 5, 5)""")
    fl = A.flags(mem, [("A", 2025), ("B", 2025), ("C", 2025), ("D", 2025), ("A", 2024), ("Z", 2025)])
    items = [{"cod_aff_form": "B", "stats": False}, {"cod_aff_form": "B"}, {"cod_aff_form": "A", "session": 2024}, {"cod_aff_form": "A"}]
    out = A.mark(mem, items, session=2025, only=lambda x: x.get("stats") is not False)
    mem.close()
    inc = A.repartition({"session": 2025, "acc_tot": 21, "acc_neobac": 7, "acc_at": 13, "pct_neobac": 33.0})
    crafted = (fl == {("A", 2025): False, ("B", 2025): True, ("C", 2025): False, ("D", 2025): False, ("A", 2024): True}
               and [x["autres_majoritaires"] for x in out] == [False, True, True, False]
               and all("autres_majoritaires" not in x for x in items) and all(a is not b for a, b in zip(out, items))
               and inc["coherent"] is False and inc["autres_majoritaires"] is False and inc["pct_neobac"] == 33.0)
    ok = not bad and not wrong and empty and crafted and n > 0
    return ok, (f"{n} rows re-derived ({yes} labelled), mismatches {bad[:3]}; edge rows wrong {wrong}; no admit = no block {empty}; "
                f"crafted warehouse (campaigns, rows outside the list, untouched inputs, counts that miss the total) {crafted}")


@check("H2 every route carries the server's rule (search, formation, comparator, map, Mes vœux); index documents untouched")
def h2(c: Ctx):
    from suptracker import search as S
    labels = c.con.execute(f"""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND {RULE_SQL}
        ORDER BY hash(cod_aff_form) LIMIT 4""", [c.latest]).fetchall()
    others = c.con.execute(f"""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND NOT coalesce({RULE_SQL}, false)
        AND acc_tot > 0 ORDER BY hash(cod_aff_form) LIMIT 4""", [c.latest]).fetchall()
    cods = [x for (x,) in labels + others]
    bad, seen = [], 0
    with client(c.db) as cl:
        def same(rows, tag, session=None):
            nonlocal seen
            keys = [(r["cod_aff_form"], r.get("session", session)) for r in rows if r.get("stats", True) is not False
                    and r.get("status", "ok") == "ok"]
            t = truth(c, keys)
            for r in rows:
                k = (r["cod_aff_form"], r.get("session", session))
                exp = t.get(k, False) if r.get("stats", True) is not False and r.get("status", "ok") == "ok" else False
                seen += 1
                if r.get("autres_majoritaires") is not exp:
                    bad.append((tag, r["cod_aff_form"]))
        for q in ("bts", "licence", "but informatique", "ifsi", "assistant de service social"):
            same(cl.get("/api/search", params={"q": q, "limit": 200}).json()["results"], f"search {q}")
        for cod in cods[:3]:
            same(cl.get("/api/search", params={"q": cod}).json()["results"], f"search code {cod}")
        for cod in cods:
            d = cl.get(f"/api/formation/{cod}").json()
            r = d["record"]
            exp = ADM.repartition(r)
            if d["admis"] != exp or (d["admis"] or {}).get("autres_majoritaires") != truth(c, [(cod, r["session"])])[(cod, r["session"])]:
                bad.append(("formation", cod))
        cmp = cl.get("/api/compare", params={"ids": ",".join(cods[:6])}).json()["formations"]
        for f in cmp:
            r = f["record"]
            if f["admis"] != ADM.repartition({**r, "pct_neobac": f["admis"]["pct_neobac"] if f["admis"] else None}):
                bad.append(("compare", r["cod_aff_form"]))
            elif f["admis"] and f["admis"]["autres_majoritaires"] != truth(c, [(r["cod_aff_form"], r["session"])])[(r["cod_aff_form"], r["session"])]:
                bad.append(("compare rule", r["cod_aff_form"]))
        from suptracker import carte as CA
        for d in [x["label"] for x in CA.facets(c.con)["diplomes"]][:3 if not c.real else 4]:
            res = cl.get("/api/carte/formations", params={"diplome": d}).json()
            same(res["formations"], f"carte {d}", res["session"])
            if any(f.get("stats") is False and f.get("autres_majoritaires") for f in res["formations"]):
                bad.append(("carte apprentissage", d))
        v = cl.get("/api/voeux", params={"ids": ",".join(cods[:8] + ["99999999"]), "serie": "bg", "spe1": "MATHS", "spe2": "SES",
                                         "mention": "ab"}).json()
        same(v["voeux"], "voeux", v["session"])
        if any(x["status"] != "ok" and x.get("autres_majoritaires") for x in v["voeux"]):
            bad.append(("voeux non situé", "labelled"))
        S._CACHE.clear()
        cl.get("/api/search", params={"q": "licence"})
        ix = S.get_index(c.con)
        touched = any("autres_majoritaires" in d for d in ix.docs)
    lab = sum(1 for k, v in truth(c, [(x, c.latest) for x in cods]).items() if v)
    ok = not bad and not touched and seen > 0 and (lab > 0 or not c.real)
    return ok, f"{seen} list rows checked ({lab} of {len(cods)} sampled formations labelled); problems {bad[:4]}; index documents modified {touched}"


@check("H3 the page in Node: bar only when the counts add up, widths and text from the published counts, label from the flag")
def h3(c: Ctx):
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ")))
    part = block(c.js, "const AUTRES_LABEL = ", "function summaryBand(")
    prog = helpers + "\n" + part + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map((a) => ({ bar: admisBar(a), cell: admisCell(a), badge: autresBadge(a) }))));"""
    cases = [{"session": 2025, "admis": 28, "admis_neobac": 6, "admis_autres": 22, "pct_neobac": 21.0, "coherent": True, "autres_majoritaires": True},
             {"session": 2025, "admis": 120, "admis_neobac": 100, "admis_autres": 20, "pct_neobac": 83.0, "coherent": True, "autres_majoritaires": False},
             {"session": 2022, "admis": 21, "admis_neobac": 13, "admis_autres": 7, "pct_neobac": 62.0, "coherent": False, "autres_majoritaires": False},
             None, {"session": "<img src=x onerror=1>", "admis": 9, "admis_neobac": 2, "admis_autres": 7, "pct_neobac": None, "coherent": True,
                    "autres_majoritaires": False}]
    o = node(prog, cases)
    if o is None:
        return True, "node not installed"
    if isinstance(o, dict):
        return False, o["error"]
    a, b, inc, none, small = o
    widths = lambda h: [float(x) for x in re.findall(r'style="width:([\d.]+)%"', h)]
    w1, w2 = widths(a["bar"]), widths(b["bar"])
    ok_bar = (w1 == [round(600 / 28, 2), round(2200 / 28, 2)] and abs(sum(w2) - 100) < 0.02 and "adm-bar" in a["bar"]
              and 'aria-label="6 néo-bacheliers et 22 autres admis sur 28 admis"' in a["bar"]
              and "6 néo-bacheliers (21 % des admis)" in a["bar"] and "22 autres admis" in a["bar"])
    ok_label = LABEL in a["bar"] and LABEL not in b["bar"] and LABEL in a["badge"] and not b["badge"] and LABEL in a["cell"] and LABEL not in b["cell"]
    ok_inc = ("adm-bar" not in inc["bar"] and "13 néo-bacheliers et 7 autres admis publiés, pour 21 admis" in inc["bar"]
              and "ne font pas exactement le total publié" in inc["bar"] and "(total publié 21)" in inc["cell"])
    ok_none = none["bar"] == "" and none["cell"] == "—" and none["badge"] == ""
    ok_small = "<img" not in small["bar"] and "adm-bar" in small["bar"] and "des admis)" not in small["bar"]
    ok = ok_bar and ok_label and ok_inc and ok_none and ok_small
    return ok, (f"bar from counts {ok_bar} ({w1}); label only from the flag {ok_label}; counts that miss the total: no bar, said {ok_inc}; "
                f"no admit: nothing {ok_none}; escaped, no share when unpublished {ok_small}")


@check("H4 wording: no chance or promise, vouvoiement, mentions and series cover néo-bacheliers only, other admits not detailed")
def h4(c: Ctx):
    part = block(c.js, "const AUTRES_LABEL = ", "function summaryBand(")
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", part)
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    scope = "Les mentions et les séries de bac publiées ne concernent que les néo-bacheliers." in part
    detail = "le SIES ne les détaille pas" in part
    label = f'const AUTRES_LABEL = "{LABEL}";' in part
    ok = not chance and not tu and scope and detail and label
    return ok, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; néo-bacheliers scope said {scope}; other admits not detailed {detail}; label {label}"


@check("H5 wiring and design: every list renders the label, the summary renders the bar, own tokens in both themes")
def h5(c: Ctx):
    js = c.js
    # R4: the search result is drawn by resultCard, used by the search page
    search = "${offerBadges(r, true)}${autresBadge(r)}" in block(js, "function resultCard(", "async function viewSearch") \
        and "${d.results.map(resultCard).join(\"\")}" in block(js, "async function viewSearch", "function suggestLycee") if "function resultCard(" in js else False
    # R10: one card for the map's list and the pinned formation (carteCard)
    carte = block(js, "function carteCard(", "function carteList(")
    carte_ok = carte.count("${autresBadge(f)}") == 1 and "carteCard(f, ctx, false)" in js and "carteCard(f, ctx, true)" in js
    cmp_ok = '["Néo-bacheliers / autres admis", (f) => admisCell(f.admis)]' in block(js, "async function viewCompare(", "async function viewSpecialites(")
    vx_ok = "${autresBadge(v)}${exigeMark(v.cod_aff_form)}`;" in block(js, "async function viewVoeux(", "const position = v.bounds")
    summary = "    ${admisBar(d.admis)}\n" in block(js, "function summaryBand(", "function fillZoneTile(")
    blocks = re.findall(r"(?s)(:root \{.*?\n\}|:root:not\(\[data-theme=\"light\"\]\) \{.*?\n  \}|:root\[data-theme=\"dark\"\] \{.*?\n\})", c.css)
    tok = [b for b in blocks if "--adm-neo:" in b and "--adm-autres:" in b]
    vals = set(re.findall(r"--adm-(?:neo|autres): (#[0-9a-f]{6})", c.css))
    others = set(re.findall(r"--(?:zone-[a-z]+|voie-b[gtp]|accent): (#[0-9a-f]{6})", c.css))
    css_ok = len(tok) == 3 and vals and not (vals & others) and ".badge.autres { border-color: var(--adm-autres)" in c.css
    api_ok = (c.api.count("ADM.mark(") == 4 and '"admis": ADM.repartition(rec)' in c.api and '"admis": f["admis"]' in c.api
              and '"admis_neobac"' in c.api.split("FEATURES = [", 1)[1].split("]", 1)[0] and 'only=lambda f: f.get("stats") is not False' in c.api)
    rel = '"admis_neobac": ("app.js", "function admisBar(")' in (ROOT / "tests" / "test_release.py").read_text()
    ok = search and carte_ok and cmp_ok and vx_ok and summary and css_ok and api_ok and rel
    return ok, (f"search {search}; map list and card {carte_ok}; comparator {cmp_ok}; Mes vœux {vx_ok}; summary bar {summary}; "
                f"tokens in 3 theme blocks, own colours {css_ok}; api wiring {api_ok}; release guard {rel}")


PY_MUTANTS = [
    ("tie counted as a majority", "and at > neo", "and at >= neo"),
    ("no admit floor", "and tot >= MIN_ADMIS and", "and"),
    ("counts not checked", "    return coherent(tot, neo, at) and tot >= MIN_ADMIS", "    return tot is not None and neo is not None and at is not None and tot >= MIN_ADMIS"),
    ("néo-bacheliers majority labelled", "and at > neo", "and neo > at"),
    ("another campaign read", "WHERE session = ? AND list_contains", "WHERE session = ? - 1 AND list_contains"),
    ("non-listed rows labelled", '"autres_majoritaires": bool(only(x) and fl.get(key(x), False))', '"autres_majoritaires": bool(fl.get(key(x), False))'),
    ("non-listed rows looked up and labelled", "    fl = flags(con, [key(x) for x in items if only(x)])\n    return [{**x, \"autres_majoritaires\": bool(only(x) and fl.get(key(x), False))}",
     "    fl = flags(con, [key(x) for x in items])\n    return [{**x, \"autres_majoritaires\": bool(fl.get(key(x), False))}"),
    ("shared documents modified", "    return [{**x, \"autres_majoritaires\"", "    for x in items:\n        x[\"autres_majoritaires\"] = bool(only(x) and fl.get(key(x), False))\n    return [{**x, \"autres_majoritaires\""),
    ("published share dropped", '"pct_neobac": rec.get("pct_neobac")', '"pct_neobac": None'),
    ("incoherent counts called coherent", '"coherent": coherent(tot, neo, at)', '"coherent": True'),
]
JS_MUTANTS = [
    ("bar drawn when the counts miss the total", "  if (!a.coherent) return `", "  if (false) return `"),
    ("width from the wrong count", '<span class="neo" style="width:${w(a.admis_neobac)}%"></span>', '<span class="neo" style="width:${w(a.admis_autres)}%"></span>'),
    ("label shown for every formation", "(x && x.autres_majoritaires ?", "(x ?"),
    ("session unescaped", "Qui sont les admis ${esc(a.session)} ?", "Qui sont les admis ${a.session} ?"),
    ("scope of the mentions dropped", "Les mentions et les séries de bac publiées ne concernent que les néo-bacheliers.", ""),
    ("bar dropped from the summary", "    ${admisBar(d.admis)}\n", "\n"),
    ("label dropped from the search", "${offerBadges(r, true)}${autresBadge(r)}", "${offerBadges(r, true)}"),
    ("label dropped from Mes vœux", "${autresBadge(v)}${exigeMark(v.cod_aff_form)}`;", "${exigeMark(v.cod_aff_form)}`;"),
    ("comparator row dropped", '    ["Néo-bacheliers / autres admis", (f) => admisCell(f.admis)],\n', ""),
    ("chance wording", "Néo-bacheliers : ils passaient le bac", "Vous serez admis : ils passaient le bac"),
]
CSS_MUTANTS = [("zone colour reused", "--adm-autres: #a8683c;", "--adm-autres: #b9460f;"),
               ("dark theme token missing", "    --adm-neo: #a9bccb; --adm-autres: #e0a77c;\n  }", "  }")]
API_MUTANTS = [("search not labelled", 'res = {**res, "results": ADM.mark(_con().cursor(), res["results"])}', "res = res"),
               ("apprenticeship offers labelled", 'only=lambda f: f.get("stats") is not False', "only=lambda f: True")]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "admis.py"
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType("suptracker._mut_admis")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("H6 mutation test: rule, routes, page, wording, wiring and design bugs are each caught")
def h6(c: Ctx):
    fns = [h1, h3, h4, h5, h2]                      # the route check (slow on real data) last
    missed = []

    def caught():
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
        saved, M["ADM"] = M["ADM"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["ADM"] = saved
            sys.modules.pop("suptracker._mut_admis", None)
    for group, attr in ((JS_MUTANTS, "js"), (CSS_MUTANTS, "css"), (API_MUTANTS, "api")):
        for name, old, new in group:
            src = getattr(c, attr)
            if old not in src:
                missed.append(f"{name} (anchor gone)"); continue
            setattr(c, attr, src.replace(old, new, 1))
            try:
                if not caught():
                    missed.append(name)
            finally:
                setattr(c, attr, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS) + len(CSS_MUTANTS) + len(API_MUTANTS)
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
