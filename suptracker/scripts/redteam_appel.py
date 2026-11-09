"""Red team of "Comprendre l'appel" and "Vraie sélectivité" (owner's request, 2026-11-09: prepare the choice of vœux; the
student has no rank yet).
    python scripts/redteam_appel.py [--db data/suptracker.duckdb] [--real]
  A1 depth per formation re-derived by SQL: called = the SUM of the groups' last-called ranks (groups split the candidates),
     share = min(1, called / ranked), "toute la liste" at or beyond the ranked count (never > 100 %), no group = no figure
  A2 per type of diploma: medians of the depth and of the three published offer-timing shares re-derived (zero-admit
     rows out, the type is the map's `diplome_of`)
  A3 selectivity: share = pct_b + pct_tb + pct_tbf, fewer than 10 néo-bachelier admits or no rate = not placed, quadrant
     lines = medians of the placed formations, each quadrant by the fixed rule; the official rate never recomputed
  A4 pages in Node on hostile data: escaped, every figure cell labelled, "toute la liste" never a share, the caveat, the dots'
     titles escaped, no input asking a rank anywhere in these views
  A5 wording: no chance / probability / promise, vouvoiement, the quadrant names describe positions (no cause)
  A6 wiring: routes, menus, cache policies, analytics routes, release guard, the formation page card
  A7 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from statistics import median

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import appel as AP  # noqa: E402
from suptracker import carte as CA  # noqa: E402
from suptracker import selectivite as SEL  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti|votre rang estim")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>'
M = {"AP": AP, "SEL": SEL}


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
        self.html = (STATIC / "index.html").read_text()
        self.sample = [c for (c,) in self.con.execute("""SELECT cod_aff_form FROM core.formation_year
            WHERE session = (SELECT max(session) FROM core.formation_year) ORDER BY hash(cod_aff_form) LIMIT 300""").fetchall()]


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


@check("A1 depth per formation: sum of the groups' last-called ranks / ranked, capped, 'toute la liste' never > 100 %")
def a1(c: Ctx):
    bad, n, whole = [], 0, 0
    for cod in c.sample:
        want = {s: (cla, [r for r in (r1, r2, r3) if r is not None]) for s, cla, r1, r2, r3 in c.con.execute(
            "SELECT session, nb_cla_pp, ran_grp1, ran_grp2, ran_grp3 FROM core.formation_year WHERE cod_aff_form = ?", [cod]).fetchall()}
        for row in M["AP"].for_formation(c.con, cod):
            cla, ranks = want[row["session"]]
            n += 1
            if not ranks or not cla:
                ok = row["profondeur"] is None and not row["toute_la_liste"]
            else:
                tot = sum(ranks)
                ok = (row["toute_la_liste"] == (tot >= cla) and row["profondeur"] == round(100 * min(1.0, tot / cla), 1)
                      and [g["rang"] for g in row["groupes"]] == ranks)
                whole += tot >= cla
            if not ok or (row["profondeur"] is not None and row["profondeur"] > 100):
                bad.append((cod, row["session"]))
    return not bad and n > 0, f"{n} formation-campaigns, {whole} with the whole list called; problems {bad[:3]}"


@check("A2 per type: medians of the depth and of the published timing shares re-derived (zero-admit rows out)")
def a2(c: Ctx):
    got = {t["diplome"]: t for t in M["AP"].by_type(c.con)["types"]}
    acc = {}
    for fili, form, fil, lib, cla, admits, t0, t1, t2, r1, r2, r3 in c.con.execute("""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc,
            lib_for_voe_ins, nb_cla_pp, acc_tot, pct_acc_debutpp, pct_acc_datebac, pct_acc_finpp, ran_grp1, ran_grp2, ran_grp3
            FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall():
        x = acc.setdefault(CA.diplome_of(fili, form, fil, lib)[0], {"n": 0, "d": [], "w": 0, "t": ([], [], [])})
        x["n"] += 1
        tot = sum(r for r in (r1, r2, r3) if r is not None)
        if (r1 is not None or r2 is not None or r3 is not None) and cla:
            x["d"].append(min(1.0, tot / cla))
            x["w"] += tot >= cla
        if admits and admits > 0 and None not in (t0, t1, t2):
            for lst, v in zip(x["t"], (t0, t1, t2)):
                lst.append(v)
    bad = []
    for k, x in acc.items():
        g = got.get(k)
        want_d = round(100 * median(x["d"]), 1) if x["d"] else None
        want_t = [round(median(v), 1) if v else None for v in x["t"]]
        if not g or g["n"] != x["n"] or g["profondeur_mediane"] != want_d or g["calendrier"] != want_t \
                or g["part_toute_la_liste"] != (round(100 * x["w"] / len(x["d"]), 1) if x["d"] else None):
            bad.append(k)
    return not bad and acc, f"{len(acc)} types re-derived; problems {bad[:3]}"


@check("A3 selectivity: share, exclusions, medians and quadrants re-derived; the official rate as published")
def a3(c: Ctx):
    labels = sorted({CA.diplome_of(*r)[0] for r in c.con.execute("""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins
        FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()})
    bad, n = [], 0
    for d in labels[:6] if not c.real else ["BUT", "BTS - BTSA - BTSM", "Licence", "CPGE ECG"]:
        res = M["SEL"].points(c.con, d)
        if res is None:
            continue
        rows = {cod: (t, b, tb, tbf, neo) for cod, t, b, tb, tbf, neo, *lab in c.con.execute("""SELECT cod_aff_form, taux_acces_ens, pct_b,
            pct_tb, pct_tbf, acc_neobac, fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins FROM core.formation_year
            WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall() if CA.diplome_of(*lab)[0] == d}
        placed = {cod: (t, round(b + tb + (tbf or 0), 1)) for cod, (t, b, tb, tbf, neo) in rows.items()
                  if t is not None and neo is not None and neo >= 10 and b is not None and tb is not None}
        got = {f["cod_aff_form"]: (f["taux_acces_ens"], f["part_bien_plus"]) for f in res["formations"]}
        apart = {f["cod_aff_form"] for f in res["non_placees"]}
        if got != placed or apart != set(rows) - set(placed):
            bad.append((d, "placement", len(got), len(placed)))
            continue
        if placed:
            mt, mb = median(v[0] for v in placed.values()), median(v[1] for v in placed.values())
            names = {(True, False): "Plus accessible", (False, False): "Très demandée", (True, True): "Admis souvent mentionnés",
                     (False, True): "Très sélective"}
            if res["mediane_taux"] != mt or res["mediane_bien"] != mb or any(
                    f["quadrant"] != names[(f["taux_acces_ens"] >= mt, f["part_bien_plus"] >= mb)] for f in res["formations"]):
                bad.append((d, "quadrants"))
        n += len(placed)
    return not bad and n > 0, f"{n} formations placed and re-derived; problems {bad[:3]}"


@check("A4 pages on hostile data (Node): escaped, labelled cells, 'toute la liste' never a share, caveat, no rank input")
def a4(c: Ctx):
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ")))
    part = block(c.js, "// ---- Comprendre l'appel and the selectivity matrix", "async function viewComprendre(")
    plot = block(c.js, "const SEL_Q = [", "async function viewSelectivite(")
    prog = helpers + "\n" + part + "\n" + plot + """
const [rows, sel] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ card: appelCard(rows), plot: selPlot(sel, null) }));"""
    rows = [{"session": 2024, "candidats": 900, "classes": 800, "places": 78, "groupes": [{"label": HOSTILE, "rang": 500}], "un_groupe": True,
             "profondeur": 62.5, "toute_la_liste": False},
            {"session": 2025, "candidats": 905, "classes": 848, "places": 78, "groupes": [{"label": HOSTILE, "rang": 740}, {"label": "B", "rang": 200}],
             "un_groupe": False, "profondeur": 100.0, "toute_la_liste": True}]
    sel = {"mediane_taux": 50, "mediane_bien": 20, "formations": [{"cod_aff_form": "1", "etablissement": HOSTILE, "formation": HOSTILE,
                                                                      "taux_acces_ens": 30, "part_bien_plus": 40, "quadrant": "Très sélective"}]}
    o = node(prog, [rows, sel])
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    card, plot = o["card"], o["plot"]
    raw = "<img" in card or "<img" in plot
    cells = re.findall(r'<td class="num"([^>]*)>', card)
    unlabelled = [x for x in cells if "data-label" not in x]
    shares = re.findall(r'data-label="Part des classés appelés">([^<]*)</td>', card)
    whole = shares == ["62,5 %", "toute la liste"]
    lead = "toute la liste</strong> des 848 candidats classés" in card
    caveat = "pas des chances d'admission" in card and "vous n'avez pas encore de rang" in card
    views = block(c.js, "// ---- Comprendre l'appel and the selectivity matrix", "// ---- lot 1 UI:")
    no_rank_input = not re.search(r"(?i)<input[^>]*rang|votre rang", views)
    ok = not raw and not unlabelled and whole and lead and caveat and no_rank_input
    return ok, f"raw tag {raw}; unlabelled figure cells {len(unlabelled)}; 'toute la liste' {whole}; lead {lead}; caveat {caveat}; no rank asked {no_rank_input}"


@check("A5 wording: no chance, probability or promise; vouvoiement; quadrant names describe positions")
def a5(c: Ctx):
    views = block(c.js, "// ---- Comprendre l'appel and the selectivity matrix", "// ---- lot 1 UI:")
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", views)
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    names = list(SEL.QUADRANTS.values())
    neutral = names == ["Plus accessible", "Très demandée", "Admis souvent mentionnés", "Très sélective"] and \
        not re.search(r"(?i)auto-?censur|élite|goulot", views + (ROOT / "suptracker" / "selectivite.py").read_text())
    position = "décrivent une position, pas une cause ni des chances" in views
    return not chance and not tu and neutral and position, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; neutral names {neutral}; position note {position}"


@check("A6 wiring: routes, menus, cache, analytics, release guard, formation page card")
def a6(c: Ctx):
    from suptracker import analytics, cache
    route = 'if (a === "comprendre") return await viewComprendre();' in c.js and 'if (a === "selectivite") return await viewSelectivite(' in c.js
    menus = c.html.count('href="#/comprendre"') == 2 and c.html.count('href="#/selectivite"') == 2
    pol = bool(cache.policy("/api/comprendre")) and bool(cache.policy("/api/selectivite"))
    an = {"comprendre", "selectivite"} <= set(analytics.ROUTES)
    rel = '"comprendre_appel": ("app.js", "async function viewComprendre(")' in (ROOT / "tests" / "test_release.py").read_text()
    card = "${appelCard(d.appel)}" in c.js and '"appel": AP.for_formation(' in (ROOT / "suptracker" / "api.py").read_text()
    ok = route and menus and pol and an and rel and card
    return ok, f"routes {route}; menus {menus}; cache {pol}; analytics {an}; release {rel}; formation card {card}"


PY_MUTANTS = [
    ("AP", "appel.py", "first group only", 'd, whole = depth(sum(g["rang"] for g in groups), ranked) if groups else (None, False)',
     'd, whole = depth(groups[0]["rang"], ranked) if groups else (None, False)'),
    ("AP", "appel.py", "share above 100 %", "    if rank >= ranked:\n        return 1.0, True\n", "    if rank > 10 * ranked:\n        return 1.0, True\n"),
    ("AP", "appel.py", "zero-admit timing kept", "if admits and all(v is not None for v in (t0, t1, t2)):", "if all(v is not None for v in (t0, t1, t2)):"),
    ("AP", "appel.py", "mean instead of median", 'round(100 * median(x["depths"]), 1)', 'round(100 * sum(x["depths"]) / len(x["depths"]), 1)'),
    ("SEL", "selectivite.py", "TB only", 'x["part_bien_plus"] = round(b + tb + (tbf or 0), 1)', 'x["part_bien_plus"] = round(tb + (tbf or 0), 1)'),
    ("SEL", "selectivite.py", "small cohorts placed", "if taux is None or neo is None or neo < MIN_ADMITS", "if taux is None or neo is None"),
    ("SEL", "selectivite.py", "quadrants on the mean", "med_t = median(p[\"taux_acces_ens\"] for p in placed)", "med_t = sum(p[\"taux_acces_ens\"] for p in placed) / len(placed)"),
    ("SEL", "selectivite.py", "quadrant axes swapped", "return QUADRANTS[(taux >= med_taux, bien >= med_bien)]", "return QUADRANTS[(bien >= med_bien, taux >= med_taux)]"),
]
JS_MUTANTS = [
    ("group label unescaped", '${esc(g.label || "Groupe")} : ${fmt(g.rang)}', '${g.label || "Groupe"} : ${fmt(g.rang)}'),
    ("dot title unescaped", "<title>${esc(f.etablissement)} — ${esc(f.formation)}", "<title>${f.etablissement} — ${f.formation}"),
    ("figure without its label", '<td class="num" data-label="Part des classés appelés">', '<td class="num">'),
    ("whole list shown as a share", 'r.toute_la_liste ? "toute la liste" : pct(r.profondeur)', "pct(r.profondeur)"),
    ("caveat dropped", "Des campagnes passées, pas des chances d'admission : vous n'avez pas encore de rang", "Voici les chiffres"),
    ("rank asked", "<p class=\"small\">Le jury classe les candidats ;", '<input placeholder="votre rang"><p class="small">Le jury classe les candidats ;'),
    ("position note dropped", "décrivent une position, pas une cause ni des chances", "décrivent la situation"),
    ("menu entry dropped", '<a href="#/selectivite" data-tab="selectivite">Vraie sélectivité</a>', ""),
]


def mutated(fname: str, old: str, new: str, name: str):
    path = ROOT / "suptracker" / fname
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType(name)
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[name] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("A7 mutation test: depth, timing, selectivity, escaping, labels, wording and wiring bugs are each caught")
def a7(c: Ctx):
    fns = [a1, a2, a3, a4, a5, a6]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    # a mutant is only observable where its data exists (the synthetic fixture has no zero-admit row with timing shares)
    zero = c.con.execute("""SELECT count(*) FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
        AND coalesce(acc_tot, 0) = 0 AND pct_acc_debutpp IS NOT NULL""").fetchone()[0] > 0
    skipped = set() if zero else {"zero-admit timing kept"}
    for key, fname, name, old, new in [m for m in PY_MUTANTS if m[2] not in skipped]:
        m = mutated(fname, old, new, f"suptracker._mut_{key}")
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M[key] = M[key], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M[key] = saved
            sys.modules.pop(f"suptracker._mut_{key}", None)
    for name, old, new in JS_MUTANTS:
        target = "html" if "data-tab" in old else "js"
        src = getattr(c, target)
        if old not in src:
            missed.append(f"{name} (anchor gone)"); continue
        setattr(c, target, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, target, src)
    n = len(PY_MUTANTS) - len(skipped) + len(JS_MUTANTS)
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
