"""Red team of the "Doublettes" sprint: proposal rates by doublette (group, national) and by bac route (formation).

    python scripts/redteam_doublettes.py [--db data/suptracker.duckdb] [--real]

  D1 units: the SIES column named "voeux" counts CANDIDATES. Its acceptations equal the formations' admits from the bac
     général (summed over the formations of the group), while it stays below the formations' bac général vœux; the
     audit maps it to n_candidats (no more "missing")
  D2 re-derivation: every figure of a group (each doublette, all candidates, the "Autres doublettes" bucket, pooled and
     per campaign) recomputed from core.specialites with an independent reading (levels 0-1, both spelling orders pooled,
     the counting-break campaigns left out by an independent re-implementation of the rule)
  D3 rules: rare = fewer than 20 candidates over the campaigns; the bucket is the exact sum of the rare doublettes; a
     doublette with enough candidates is never replaced; the bucket is always flagged as an estimation (Python twin and
     page twin agree on crafted cases)
  D4 per-route rates of a formation re-derived from its published counts (candidates with a proposal / candidates of
     the series, main + complementary phase), each campaign of its lineage; fewer than 20 candidates = fragile
  D5 colours: --voie-bg / --voie-bt / --voie-bp in every theme, far from each zone colour, the accent and each other;
     the page draws a route only with its name
  D6 one figure everywhere: stage 1 of "Mon parcours", the formation page, the vœux list and the 4-year curves give the
     same rate for the same group and doublette; a formation without a group shows no doublette figure
  D7 wording: national, per group, "pas des chances", never a probability; vouvoiement
  D8 page run with Node on hostile data: escaped, every stacked figure labelled, a rare doublette shows the bucket
  D9 mutation test (each mutant must fail a check; mutants are built in memory, no source file is written)
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

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import doublettes as DB  # noqa: E402
from suptracker import journey as J  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
M = {"DB": DB, "J": J}          # the modules the checks call (the mutation test swaps in mutated copies, in memory)


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
        self.types = [t for (t,) in self.con.execute("SELECT DISTINCT type_key FROM mart.spe_group ORDER BY 1").fetchall()]
        self.sample_types = self.types if not real else self.types[:: max(1, len(self.types) // 15)] + [
            t for t in ("licence l as", "licence sciences juridiques") if t in self.types]


# ------------------------------------------------------------------ independent reading
def independent(con) -> dict:
    """{type_key: {session: {doublette_key: [cand, prop, acc]}}} from core.specialites, levels 0-1, national row apart."""
    key_of = dict(con.execute("SELECT doublette, doublette_key FROM core.spe_doublette").fetchall())
    out = {}
    for ft, d, s, c, p, a, lvl in con.execute("""SELECT formation_type, doublette, session, n_candidats, n_proposition, n_accepte,
                                                        aggregation_level FROM core.specialites""").fetchall():
        if lvl not in (None, "0", "1") or d not in key_of or ft is None:
            continue
        tk = J.type_key(ft)
        if tk == J.NATIONAL_TYPE:
            continue
        x = out.setdefault(tk, {}).setdefault(s, {}).setdefault(key_of[d], [0, 0, 0])
        x[0] += c or 0
        x[1] += p or 0
        x[2] += a or 0
    return out


def breaks_of(ind: dict) -> dict:
    """The counting-break rule, written again: {type_key: [sessions left out]}."""
    res = {}
    for tk, by in ind.items():
        tot = {s: (sum(v[0] for v in d.values()), sum(v[1] for v in d.values())) for s, d in by.items()}
        mc, mp = min(c for c, _ in tot.values()), min(p for _, p in tot.values())
        if mp >= 2000:
            res[tk] = sorted(s for s, (c, p) in tot.items() if c > 2 * mc and p < 1.5 * mp)
    return res


def pct(p, c):
    return None if not c else round(100.0 * p / c, 1)


# ------------------------------------------------------------------ checks
@check("D1 units: the SIES 'voeux' column counts candidates (acceptations = formations' bac général admits, below their vœux)")
def d1(c: Ctx):
    last = c.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    spe = dict((t, (cand, acc)) for t, cand, acc in c.con.execute(
        "SELECT type_key, sum(candidats), sum(acceptations) FROM mart.spe_filiere WHERE session = ? GROUP BY 1", [last]).fetchall())
    fy = dict((t, (v, a)) for t, v, a in c.con.execute(f"""
        SELECT r.spe_type_key, sum({J.series_candidates_sql('bg')}), sum(fy.acc_bg) FROM core.formation_year fy
        JOIN core.taxonomy_link t USING (session, cod_aff_form) JOIN core.taxonomy_rule r USING (rule_id)
        WHERE fy.session = ? GROUP BY 1""", [last]).fetchall())
    both = [t for t in spe if t in fy and t != J.NATIONAL_TYPE and (spe[t][1] or 0) >= (200 if c.real else 1)]
    close = [t for t in both if abs((spe[t][1] or 0) - (fy[t][1] or 0)) <= max(5, 0.05 * (fy[t][1] or 0))]
    # where the site's formation groups match SIES's (acceptations within 5 %), people stay below the vœux; elsewhere the
    # gap comes from the group mapping (e.g. archéologie: 307 SIES admits vs 2 431 in the mapped formations), not the units
    below = [t for t in close if (spe[t][0] or 0) <= (fy[t][0] or 0)]
    audit = dict(c.con.execute("SELECT canonical, upstream FROM meta.schema_audit WHERE canonical LIKE 'specialites%n_candidats'").fetchall())
    audit_ok = bool(audit) and all(v == "voeux" for v in audit.values())
    share = len(close) / max(1, len(both))
    order = c.con.execute("SELECT count(*) FROM core.specialites WHERE n_candidats < n_proposition OR n_proposition < n_accepte").fetchone()[0]
    if not c.real:      # the synthetic fixture's specialty counts are not built from its formations: units on real data only
        return audit_ok and order == 0, f"synthetic: audit {audit}; rows with candidates < proposals < acceptations broken: {order}"
    ok = both and share >= 0.75 and len(below) == len(close) and audit_ok and order == 0
    return ok, (f"{len(both)} groups; acceptations = formations' bac général admits (±5 %) in {len(close)} ({share:.0%}); "
                f"candidates ≤ formations' vœux in {len(below)}/{len(close)} of them; audit {audit}; order broken in {order} rows")


@check("D2 every figure of a group re-derived independently (doublettes, all, 'Autres doublettes', pooled and per campaign, breaks left out)")
def d2(c: Ctx):
    ind = independent(c.con)
    brk = breaks_of(ind)
    bad = []
    for tk in c.sample_types:
        g = M["DB"].for_group(c.con, tk)
        by = {s: d for s, d in ind.get(tk, {}).items() if s not in brk.get(tk, [])}
        pooled = {}
        for s, d in by.items():
            for k, v in d.items():
                x = pooled.setdefault(k, [0, 0, 0])
                for i in range(3):
                    x[i] += v[i]
        rare = {k for k, v in pooled.items() if v[0] < 20}
        if g is None:
            bad.append((tk, "missing"))
            continue
        if sorted(g.get("campagnes_ecartees", [])) != brk.get(tk, []):
            bad.append((tk, "breaks", g.get("campagnes_ecartees"), brk.get(tk)))
        for d in g["doublettes"]:
            v = pooled.get(d["key"], [0, 0, 0])
            if (d["candidats"], d["propositions"], d["acceptations"]) != tuple(v) or d["taux"] != pct(v[1], v[0]) or d["rare"] != (d["key"] in rare):
                bad.append((tk, d["key"], "pooled"))
            for tr in d["trend"]:
                vv = by.get(tr["session"], {}).get(d["key"], [0, 0, 0])
                if tr["candidats"] != vv[0] or tr["taux"] != pct(vv[1], vv[0]):
                    bad.append((tk, d["key"], tr["session"]))
        tot = [sum(v[i] for v in pooled.values()) for i in range(3)]
        aut = [sum(pooled[k][i] for k in rare) for i in range(3)]
        if (g["tous"]["candidats"], g["tous"]["taux"]) != (tot[0], pct(tot[1], tot[0])):
            bad.append((tk, "tous"))
        if (g["autres"]["candidats"], g["autres"]["taux"], g["autres"]["n_doublettes"]) != (aut[0], pct(aut[1], aut[0]), len(rare)):
            bad.append((tk, "autres", g["autres"]["candidats"], aut[0]))
    # the build itself, re-run on a scratch copy: the stored break table must be what the rule gives
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA mart")
    cols = [r[0] for r in c.con.execute("DESCRIBE mart.spe_filiere").fetchall()]
    mem.execute(f"CREATE TABLE mart.spe_filiere ({', '.join(f'{x} {t}' for x, t in c.con.execute('SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position', ['mart', 'spe_filiere']).fetchall())})")
    mem.executemany(f"INSERT INTO mart.spe_filiere VALUES ({', '.join('?' for _ in cols)})", c.con.execute("SELECT * FROM mart.spe_filiere").fetchall())
    # plus a crafted group with the Licence L.AS counting break, so the rule is exercised on any warehouse
    for s, cc, pp in ((2022, 96307, 53522), (2023, 272454, 55246), (2024, 262625, 56058), (2025, 103979, 53442)):
        mem.execute("INSERT INTO mart.spe_filiere (session, type_key, type_label, doublette_key, candidats, propositions, acceptations) "
                    "VALUES (?, 'zz rupture', 'ZZ', 'A+B', ?, ?, 1)", [s, cc, pp])
    M["DB"].build(mem)
    rebuilt = {}
    for tk, s in mem.execute("SELECT type_key, session FROM mart.spe_break ORDER BY 1, 2").fetchall():
        rebuilt.setdefault(tk, []).append(s)
    want = {k: v for k, v in brk.items() if v}
    if rebuilt != {**want, "zz rupture": [2023, 2024]}:
        bad.append(("build break rule", rebuilt, want))
    mem.close()
    return not bad, f"{len(c.sample_types)} groups; breaks {want}; problems {bad[:3]}"


def _crafted():
    mk = lambda k, cand, rare, taux: {"key": k, "label": k, "rare": rare, "candidats": cand, "taux": taux, "trend": []}  # noqa: E731
    return {"doublettes": [mk("A+B", 500, False, 70.0), mk("C+D", 20, False, 50.0), mk("E+F", 19, True, 10.0), mk("G+H", 0, True, None)],
            "autres": {"candidats": 19, "taux": 10.0, "n_doublettes": 2, "trend": []}, "tous": {"candidats": 539, "taux": 66.0, "trend": []}}


PICK_CASES = [("A+B", ("doublette", 70.0)), ("C+D", ("doublette", 50.0)), ("E+F", ("autres", 10.0)), ("G+H", ("autres", 10.0)),
              ("X+Y", ("autres", 10.0)), (None, None)]


def page_pick(js: str):
    m = re.search(r"function pickDoublette\(g, dkey\) \{.*?\n\}", js, re.S)
    node = shutil.which("node")
    if not m or not node:
        return None if m else "missing"
    prog = m.group(0) + """
const [g, keys] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(keys.map((k) => { const x = pickDoublette(g, k); return x ? [x.source, x.taux, !!x.estimation] : null; })));"""
    r = subprocess.run([node, "-e", prog], input=json.dumps([_crafted(), [k for k, _ in PICK_CASES]]), capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 else "error: " + r.stderr[-200:]


@check("D3 rules: rare below 20 candidates; the bucket = exact sum of the rare ones; never replaces a doublette with enough candidates")
def d3(c: Ctx):
    py = [M["DB"].pick(_crafted(), k) for k, _ in PICK_CASES]
    py_ok = all((x is None and w is None) or (x and w and (x["source"], x["taux"]) == w and (x["source"] == "autres") == bool(x.get("estimation")))
                for x, (_, w) in zip(py, PICK_CASES))
    js = page_pick(c.js)
    js_ok = js is None or (js != "missing" and not str(js).startswith("error") and all(
        (x is None and w is None) or (x and w and (x[0], x[1]) == w and (x[0] == "autres") == x[2]) for x, (_, w) in zip(js, PICK_CASES)))
    seuil = M["DB"].THRESHOLD == 20 and "const DBL_SEUIL = 20;" in c.js
    real_ok = True
    for tk in c.sample_types[:8]:
        g = M["DB"].for_group(c.con, tk)
        if g and any(d["rare"] != (d["candidats"] < 20) for d in g["doublettes"]):
            real_ok = False
    return py_ok and js_ok and seuil and real_ok, f"Python twin {py_ok}; page twin {js_ok} ({js}); threshold 20 {seuil}; rare flags {real_ok}"


@check("D4 per-route rates of a formation re-derived from its published counts, each campaign; < 20 candidates = fragile")
def d4(c: Ctx):
    cods = [x for (x,) in c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
                                            ORDER BY hash(cod_aff_form) LIMIT ?""", [20 if c.real else 6]).fetchall()]
    bad = []
    for cod in cods:
        s = M["DB"].series(c.con, cod)
        lin = c.con.execute("SELECT lineage_id FROM core.lineage WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1", [cod]).fetchone()[0]
        rows = c.con.execute("""SELECT fy.session, nb_voe_pp_bg, nb_voe_pc_bg, prop_tot_bg, nb_voe_pp_bt, nb_voe_pc_bt, prop_tot_bt,
                                       nb_voe_pp_bp, nb_voe_pc_bp, prop_tot_bp FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
                                WHERE l.lineage_id = ? ORDER BY 1""", [lin]).fetchall()
        for i, v in enumerate(("bg", "bt", "bp")):
            want = [(r[0], (r[1 + 3 * i] or 0) + (r[2 + 3 * i] or 0) if r[1 + 3 * i] is not None else None, r[3 + 3 * i]) for r in rows]
            got = [(t["session"], t["candidats"], t["taux"]) for t in s[v]["trend"]]
            exp = [(y, cand, pct(p or 0, cand) if cand else None) for y, cand, p in want]
            if got != exp:
                bad.append((cod, v, got[-1:], exp[-1:]))
            if s[v]["fragile"] != ((s[v]["candidats"] or 0) < 20):
                bad.append((cod, v, "fragile"))
    return not bad, f"{len(cods)} formations; problems {bad[:3]}"


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colours_ok(css: str, js: str) -> tuple[bool, str]:
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    blocks = [m.group(0) for m in re.finditer(r"--zone-securite:[^;]+;[^}]*", body)]
    bad = []
    for b in blocks[:3]:
        tok = dict(re.findall(r"--((?:voie|zone)-[a-z]+|accent):\s*(#[0-9a-fA-F]{6})", b))
        names = [f"voie-{v}" for v in ("bg", "bt", "bp")]
        if any(n not in tok for n in names):
            bad.append("missing voie token")
            continue
        for n in names:                                   # by token NAME: two equal colours are a failure, not "itself"
            for o in names + ["zone-securite", "zone-cible", "zone-ambitieux"]:
                if o != n and o in tok and sum((x - y) ** 2 for x, y in zip(_rgb(tok[n]), _rgb(tok[o]))) ** 0.5 < 60:
                    bad.append((n, tok[n], o, tok[o]))
    decl = re.search(r"const VOIES = \{(.*?)\};", js, re.S)
    js_ok = bool(decl) and all(re.search(rf'{v}: \{{ label: "[^"]+", color: "var\(--voie-{v}\)" \}}', decl.group(1)) for v in ("bg", "bt", "bp")) and \
        'const voiePill = (s) => `<span class="voie-pill" style="color:${VOIES[s].color}">${VOIES[s].label}</span>`;' in js
    acc = [m.group(1) for m in re.finditer(r"--accent:\s*(#[0-9a-fA-F]{6})", body)][:3]
    vo = [m.group(1) for m in re.finditer(r"--voie-(?:bg|bt|bp):\s*(#[0-9a-fA-F]{6})", body)]
    acc_far = all(sum((x - y) ** 2 for x, y in zip(_rgb(v), _rgb(a))) ** 0.5 >= 60 for v in vo for a in acc)
    ok = len(blocks) >= 3 and not bad and js_ok and acc_far
    return ok, f"{len(blocks)} themes; too close {bad[:3]}; page uses tokens with the route name {js_ok}; far from the accent {acc_far}"


@check("D5 route colours: own tokens in every theme, far from the zones, the accent and each other; always with the route's name")
def d5(c: Ctx):
    return colours_ok(c.css, c.js)


@check("D6 one figure everywhere: stage 1, formation page, vœux list and curves agree; no group = no doublette figure")
def d6(c: Ctx):
    bad = []
    keys = [k for (k,) in c.con.execute("SELECT doublette_key FROM core.spe_doublette GROUP BY 1 ORDER BY 1 LIMIT ?", [4 if c.real else 3]).fetchall()]
    for dkey in keys:
        s1 = {f["type_key"]: f for f in M["J"].stage1(c.con, dkey)["filieres"]}
        for tk in c.sample_types[:8] + [t for t in c.sample_types[8:] if t in ("licence l as",)]:
            g = M["DB"].for_group(c.con, tk)
            f = s1.get(tk)
            if not g or not f:
                continue
            mine = next((d for d in g["doublettes"] if d["key"] == dkey), None)
            if mine and mine["candidats"] and (f["offer_rate"] is None or abs(100 * f["offer_rate"] - mine["taux"]) > 0.051
                                               or f["candidates"] != mine["candidats"]):
                bad.append(("stage1", dkey, tk, f["offer_rate"], mine["taux"]))
            if f["rare"] != ((f["candidates"] or 0) < 20) or (f["rare"] and f["autres"] and f["autres"]["taux"] != g["autres"]["taux"]):
                bad.append(("stage1 bucket", dkey, tk))
    from suptracker import voeux as VX
    cods = [x for (x,) in c.con.execute("""SELECT t.cod_aff_form FROM core.taxonomy_link t WHERE t.session = (SELECT max(session) FROM core.formation_year)
                                            ORDER BY hash(t.cod_aff_form) LIMIT 4""").fetchall()]
    if keys and cods:
        a, b = keys[0].split("+")
        v = VX.evaluate(c.con, cods, serie="bg", dkey=keys[0], mention="ab")
        for x in v["voeux"]:
            if x["status"] != "ok":
                continue
            want = M["DB"].pick(M["DB"].for_group(c.con, x["type_key"]), keys[0])
            want = {k: w for k, w in want.items() if k != "trend"} if want else None
            if x.get("doublette") != want:
                bad.append(("voeux", x["cod_aff_form"]))
        f = M["DB"].for_formation(c.con, cods[0])
        if f["groupe"] != M["DB"].for_group(c.con, M["DB"].type_of(c.con, cods[0])):
            bad.append(("formation", cods[0]))
    orphan = c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE cod_aff_form NOT IN (SELECT cod_aff_form FROM core.taxonomy_link)
                              ORDER BY 1 LIMIT 1""").fetchone()
    if orphan and M["DB"].for_formation(c.con, orphan[0])["status"] != "sans_groupe":
        bad.append(("orphan has a group", orphan[0]))
    curves = "values: at(mine.trend, \"taux\")" in c.js and "values: at(g.tous.trend, \"taux\")" in c.js and "pickDoublette(g, profileDkey(" in c.js
    return not bad and curves, f"{len(keys)} doublettes × {min(10, len(c.sample_types))} groups; curves read the same rows {curves}; problems {bad[:3]}"


@check("D7 wording: national, per group, 'pas des chances', never a probability; vouvoiement")
def d7(c: Ctx):
    blk = c.js[c.js.index("// ---- Sprint \"Doublettes\""):c.js.index("// ---- lot 2 (Claude design guidelines)")]
    s1 = c.js[c.js.index("function stage1Matrix("):c.js.index("function stage1SeriesMatrix(")]
    text = re.sub(r"(?m)^\s*//.*$", "", blk + s1)
    words = all(w in blk for w in ("Chiffre national du groupe, pas propre à cet établissement", "Ce ne sont pas des chances d'admission",
                                   "estimation")) and "Pas des chances d'admission" in s1
    chance = CHANCE.search(text)
    tu = FORMAL.search(re.sub(r"\$\{[^}]*\}", "", text))
    doc = "pas des chances" in (DB.__doc__ or "").lower() or "never a chance" in (DB.__doc__ or "").lower()
    return words and not chance and not tu and doc, f"caveats {words}; probability wording {chance and chance.group(0)}; tutoiement {tu and tu.group(0)}"


def node_card(js: str):
    node = shutil.which("node")
    if not node:
        return None
    blk = js[js.index("// ---- Sprint \"Doublettes\""):js.index("// ---- lot 2 (Claude design guidelines)")]
    blk += js[js.index("function stage1Matrix("):js.index("function stage1SeriesMatrix(")]
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pc1 = ")))
    g0 = re.search(r"const GATES = \{.*?\n\};", js, re.S)
    helpers += "\n" + (g0.group(0) if g0 else "")
    hostile = '<img src=x onerror=alert(1)>'
    g = {"label": hostile, "seuil": 20, "tous": {"candidats": 100, "taux": 50, "trend": []},
         "autres": {"candidats": 19, "taux": 10, "n_doublettes": 3, "trend": []},
         "doublettes": [{"key": "A+B", "label": hostile, "rare": False, "candidats": 81, "taux": 60, "trend": []},
                        {"key": "ART+EPPCS", "label": "Arts + EPPCS", "rare": True, "candidats": 2, "taux": 0, "trend": []}]}
    ser = {s: {"label": s, "candidats": 10, "taux": 40, "fragile": True, "trend": [{"session": 2025, "candidats": 10, "taux": 40}]} for s in ("bg", "bt", "bp")}
    prog = helpers + """
let PROFILE = null; const store = { get: (k, d) => (k === "profile" ? PROFILE : d) };
const tip = () => ""; const legend = () => ""; const lineChart = () => "";
""" + blk + """
const [d, prof] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {}; PROFILE = prof; out.rare = doubletteCard(d); PROFILE = null; out.none = doubletteCard(d);
out.nogroup = doubletteCard({ ...d, status: "sans_groupe", groupe: null });
out.stage1 = stage1Matrix({ filieres: [
  { type_key: "a", label: "Licence A", gate: "insuffisant", candidates: 3, years: 4, offer_rate: null, offer_rate_all: 0.5, share: 0, lift: 0,
    destination_share: 0, n_formations: 2, rare: true, autres: { taux: 44.7, candidats: 85, n_doublettes: 16 } }] },
  new Set(["predilection", "accessible"]), false);
process.stdout.write(JSON.stringify(out));"""
    r = subprocess.run([node, "-e", prog], input=json.dumps([{"series": ser, "groupe": g, "status": "ok"},
                                                            {"serie": "bg", "spe1": "ART", "spe2": "EPPCS"}]), capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-300:]}


@check("D8 page on hostile data: escaped, every stacked figure labelled, a rare doublette shows the bucket as an estimation")
def d8(c: Ctx):
    o = node_card(c.js)
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    raw = any("<img" in v for v in o.values())
    rare = "Votre doublette : Arts + EPPCS" in o["rare"] and "« Autres doublettes »" in o["rare"] and "estimation" in o["rare"]
    invite = "Indiquez vos spécialités" in o["none"]
    nogroup = "Pas de donnée par doublette" in o["nogroup"] and "Votre doublette" not in o["nogroup"]
    unlabelled = [len(re.findall(r'<td class="num"(?![^>]*data-label)', v)) for v in o.values()]
    pills = all(o[k].count('class="voie-pill"') == 3 for k in o if k != "stage1")
    s1 = o.get("stage1", "")
    rare_s1 = "Votre doublette est rare" in s1 and "44,7 %" in s1 and "Autres doublettes (estimation" in s1 and "Licence A" in s1
    ok = not raw and rare and invite and nogroup and not any(unlabelled) and pills and rare_s1
    return ok, (f"raw tag {raw}; rare shows the bucket {rare}; invites a profile {invite}; no group {nogroup}; unlabelled cells {unlabelled}; "
                f"route pills {pills}; a rare doublette's filières shown with the bucket in Mon parcours {rare_s1}")


# ------------------------------------------------------------------ mutation test
DBL_PY = ROOT / "suptracker" / "doublettes.py"
JOURNEY_PY = ROOT / "suptracker" / "journey.py"
PY_MUTANTS = [
    ("threshold lowered", "THRESHOLD = 20 ", "THRESHOLD = 5 "),
    ("bucket used for a doublette with enough candidates", '    if mine and not mine["rare"]:\n', "    if False:\n"),
    ("bucket mixes every doublette", "autres = _pack([r for d, rs in per.items() if rare[d] for r in rs])", "autres = _pack([r for d, rs in per.items() for r in rs])"),
    ("bucket not flagged", '"n_doublettes": a["n_doublettes"], "trend": a["trend"], "estimation": True}', '"n_doublettes": a["n_doublettes"], "trend": a["trend"]}'),
    ("route rate over vœux", 'cols = ", ".join(f"{J.series_candidates_sql(s)} AS c_{s}', 'cols = ", ".join(f"fy.voe_tot AS c_{s}'),
    ("fragile threshold dropped", '"fragile": (last["candidats"] or 0) < THRESHOLD', '"fragile": False'),
    ("break rule disabled", "BREAK_CAND, BREAK_PROP, BREAK_MIN_PROP = 2.0, 1.5, 2000", "BREAK_CAND, BREAK_PROP, BREAK_MIN_PROP = 99.0, 1.5, 2000"),
    ("rate on acceptations", 'return {"candidats": cand, "propositions": prop, "acceptations": acc, "taux": rate(prop, cand),',
     'return {"candidats": cand, "propositions": prop, "acceptations": acc, "taux": rate(acc, cand),'),
]
JOURNEY_MUTANTS = [
    ("stage 1 keeps the break campaigns", "         OR (type_key, session) NOT IN (SELECT (type_key, session) FROM mart.spe_break)", "         OR TRUE"),
]
JS_MUTANTS = [
    ("page uses the bucket for a common doublette", "if (mine && !mine.rare) return", "if (mine && false) return"),
    ("route coloured like a zone", 'bg: { label: "Bac général", color: "var(--voie-bg)" }', 'bg: { label: "Bac général", color: "var(--zone-cible)" }'),
    ("national caveat dropped", "Chiffre national du groupe, pas propre à cet établissement. ", ""),
    ("group label unescaped", "Groupe : <strong>${esc(g.label)}</strong>", "Groupe : <strong>${g.label}</strong>"),
    ("doublette label unescaped", "top.map((x) => row(esc(x.label), x,", "top.map((x) => row(x.label, x,"),
    ("figure without its label", '<td class="num" data-label="Candidats">${fmt(v.candidats)}', '<td class="num">${fmt(v.candidats)}'),
    ("stage 1 hides the rare doublette's filières", "const onlyRare = !s1.filieres.some", "const onlyRare = false && !s1.filieres.some"),
]
CSS_MUTANTS = [
    ("route colour equal to a zone", "--voie-bt: #8a6d00;", "--voie-bt: #c4581f;"),
]


def mutated(modname: str, path: Path, old: str, new: str):
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType(modname)
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[modname] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("D9 mutation test: threshold, bucket, units, breaks, colours, escaping, labels and wording bugs are each caught")
def d9(c: Ctx):
    fns = [d1, d2, d3, d4, d5, d6, d7, d8]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001  (a crash is not a catch)
                pass
        return False
    has_break = c.con.execute("SELECT count(*) FROM mart.spe_break").fetchone()[0] > 0
    for group, path, slot in ((PY_MUTANTS, DBL_PY, "DB"), (JOURNEY_MUTANTS if has_break else [], JOURNEY_PY, "J")):
        for name, old, new in group:
            m = mutated(f"suptracker._mut_{slot}", path, old, new)
            if m is None:
                missed.append(f"{name} (anchor gone)")
                continue
            saved = M[slot]
            M[slot] = m
            if slot == "J":                      # the journey copy must call the same doublettes module
                m.DB = DB
            try:
                if not caught():
                    missed.append(name)
            finally:
                M[slot] = saved
                sys.modules.pop(f"suptracker._mut_{slot}", None)
    for group, attr in ((JS_MUTANTS, "js"), (CSS_MUTANTS, "css")):
        for name, old, new in group:
            src = getattr(c, attr)
            if old not in src:
                missed.append(f"{name} (anchor gone)")
                continue
            setattr(c, attr, src.replace(old, new, 1))
            try:
                if not caught():
                    missed.append(name)
            finally:
                setattr(c, attr, src)
    n = len(PY_MUTANTS) + (len(JOURNEY_MUTANTS) if has_break else 0) + len(JS_MUTANTS) + len(CSS_MUTANTS)
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
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + str(r["detail"]))
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
