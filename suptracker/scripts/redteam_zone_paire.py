"""Red team, the zone read on the student's pair rate (owner, 2026-11-19). Bac général: when the formation's OWN cross-checked
report of the latest campaign publishes the student's pair of specialties (else its « Autres » line), for at least 20
candidates, the zone (and « sécurité large », and Plan B's +15 points) reads that rate; otherwise the official access rate,
which stays displayed as it is. Never the « Autres » line when the report's detail carries a pair label no rule knows.

    python scripts/redteam_zone_paire.py [--db data/suptracker.duckdb] [--real]

  ZP1 the rate: every stage-2 row's taux_zone and its source re-derived from an independent read of the reports (own rules,
      written apart); bac techno rows read the official rate; non-vacuous (pair lines, « Autres » lines, official fallbacks).
  ZP2 the zone: each row's zone = the REAL classify_zone on taux_zone (the official rate gives another zone on a counted share).
  ZP3 page twin (Node): relire / relireVue / carteZonesLocal read taux_zone: the page's zone for an average = the server's.
  ZP4 Plan B: why_better / whyBetter compare the zones' rate (a candidate better only on its official rate is not « acces »).
  ZP5 stability: pair-read zones measured with that method (calibration.pair_persistence), re-derived; served on such rows.
  ZP6 the guard: journey.pick_pair, rapports.pick and the page's pickRapport never claim « Autres » beside an unknown pair label
      (arts), never below 20 candidates, never an impossible line.
  ZP7 page and plumbing: the note says what the zone was read on (escaped, the served rate, the report's session), at every zone
      spot, in L'essentiel and the legend; the method text; views carry the rate; README, CLAUDE.md, tests.
  ZP8 real data (--real) and mutation test.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import redteam_securite_large as SL  # noqa: E402  (the module loader, the node harness and the oracle's journey)

MODS = {**SL.MODS, "rapports": "rapports.py"}
SL.MODS.update(MODS)
JR = SL.JR
CHECKS = []
MIN_CONF = 20
DKEYS = ("MATHS+SES", "MATHS+PC", "HGGSP+SES", "ART+HLP")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx(SL.Ctx):
    def __init__(self, db: Path, real: bool = False):
        super().__init__(db, real)
        self.src["rapports"] = (ROOT / "suptracker" / "rapports.py").read_text()
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]


# ------------------------------------------------------------------------------------------------------------ oracle
def reports(c: Ctx) -> dict:
    """{cod: [(key, autres, confirmes, en_position)]} of the latest campaign's cross-checked reports, bac général tables."""
    def build():
        out = defaultdict(list)
        for cod, key, autres, conf, pos in c.con.execute("""SELECT d.cod_aff_form, d.doublette_key, d.autres, d.confirmes, d.en_position
                FROM core.rapport_doublette d, core.rapport r
                WHERE r.cod_aff_form = d.cod_aff_form AND r.session = d.session AND r.recoupe AND d.session = ? AND d.bac = 'bg'""",
                                                         [c.latest]).fetchall():
            out[cod].append((key, bool(autres), conf, pos))
        return dict(out)
    return c.memo("reports", build)


def oracle_rate(rows, dkey):
    """Written apart from journey.pick_pair: (rate, kind) or None."""
    if not rows or not dkey:
        return None
    own = [r for r in rows if r[0] == dkey and not r[1]]
    if own:
        line, kind = own[0], "paire"
    else:
        if any(r[0] is None and not r[1] for r in rows):
            return None
        bucket = [r for r in rows if r[1]]
        if not bucket:
            return None
        line, kind = bucket[0], "autres"
    conf, pos = line[2], line[3]
    if conf is None or conf < MIN_CONF or pos is None or pos > conf:
        return None
    return round(100.0 * pos / conf, 6), kind


def rows_of(c: Ctx, J) -> list[tuple]:
    out = []
    cur = c.con.cursor()
    tks = SL.sample_types(c)[: 2 if c.quick else 4]
    for tk in tks:
        for dkey in (DKEYS[:2] if c.quick else DKEYS):
            for f in J.stage2(cur, dkey, "ab", tk, None, serie="bg")["formations"]:
                out.append((tk, dkey, "bg", f))
        for f in J.stage2(cur, None, "ab", tk, None, serie="bt")["formations"]:
            out.append((tk, None, "bt", f))
    return out


@check("ZP1 the rate: taux_zone and its source = an independent read of the formation's own report (pair, else « Autres », >= 20, guard)")
def zp1(c: Ctx):
    J = c.mod("journey")
    rep = reports(c)
    bad, kinds = [], Counter()
    for tk, dkey, serie, f in rows_of(c, J):
        want = oracle_rate(rep.get(f["cod_aff_form"]), dkey) if serie == "bg" else None
        src = f.get("taux_zone_source")
        got = (src["taux"], "paire" if src["source"] == "paire" else "autres") if src else None
        if got != want or f.get("taux_zone") != (want[0] if want else f["taux_acces_ens"]):
            bad.append((tk, dkey, serie, f["cod_aff_form"], got, want, f.get("taux_zone"), f["taux_acces_ens"]))
        if src and (src.get("session") != c.latest or src.get("confirmes") is None):
            bad.append(("session or counts", f["cod_aff_form"], src))
        kinds[(serie, want[1] if want else "officiel")] += 1
        if serie == "bg" and want is None and rep.get(f["cod_aff_form"]):
            kinds["report but official (guard or < 20)"] += 1
    bad += hostile_reports(J)
    vacuous = c.real and not (kinds[("bg", "paire")] and kinds[("bg", "autres")] and kinds["report but official (guard or < 20)"])
    return not bad and not vacuous, f"readings {dict(kinds)}; problems {bad[:3]}"


def hostile_reports(J) -> list:
    """pair_rates on a tiny warehouse: a report not cross-checked, another session, a line under 20, a bac techno table and an
    unknown label are never read (the real warehouse may hold none of them today)."""
    import duckdb
    m = duckdb.connect()
    m.execute("CREATE SCHEMA core")
    m.execute("CREATE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER, recoupe BOOLEAN)")
    m.execute("""CREATE TABLE core.rapport_doublette (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR, doublette_key VARCHAR,
        autres BOOLEAN, confirmes INTEGER, en_position INTEGER)""")
    m.executemany("INSERT INTO core.rapport VALUES (?, ?, ?)", [("1", 2025, True), ("2", 2025, False), ("3", 2024, True), ("4", 2025, True),
                                                                ("5", 2025, True), ("6", 2025, True)])
    k = "MATHS+SES"
    m.executemany("INSERT INTO core.rapport_doublette VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ("1", 2025, "bg", k, False, 40, 10), ("2", 2025, "bg", k, False, 40, 30), ("3", 2024, "bg", k, False, 40, 30),
        ("4", 2025, "bg", k, False, 19, 5), ("4", 2025, "bg", None, True, 60, 30), ("5", 2025, "bt", k, False, 40, 30),
        ("6", 2025, "bg", None, False, 40, 30), ("6", 2025, "bg", None, True, 60, 30)])
    got = {cod: (x["taux"], x["source"], x["session"]) for cod, x in J.pair_rates(m, list("123456"), 2025, k).items()}
    return [] if got == {"1": (25.0, "paire", 2025)} else [("hostile reports", got)]


@check("ZP2 the zone: classify_zone on taux_zone (the official rate would give another zone on a counted share)")
def zp2(c: Ctx):
    J = c.mod("journey")
    bad, changed, n = [], 0, 0
    for tk, dkey, serie, f in rows_of(c, J):
        if f["zone"] in ("non_ouvert", "indetermine"):
            continue
        L = f["lec"]
        rd = JR.zone_reading(serie, "ab", L["kt"], L["n"], [], 1.0, L["s"])
        want = JR.classify_zone(f["taux_zone"], rd["cdf_zone"], *rd["ci_zone"])
        off = JR.classify_zone(f["taux_acces_ens"], rd["cdf_zone"], *rd["ci_zone"])
        n += 1
        changed += off["zone"] != want["zone"]
        if (f["zone"], f["uncertain"]) != (want["zone"], want["uncertain"]):
            bad.append((tk, dkey, f["cod_aff_form"], f["zone"], want["zone"]))
    vacuous = c.real and changed == 0
    return not bad and not vacuous, f"{n} zones read, {changed} differ from the official rate's reading ({100 * changed / max(1, n):.1f} %); problems {bad[:3]}"


@check("ZP3 page twin: the page reads the zone on taux_zone for an average = the server's reading (zone, incertain, large)")
def zp3(c: Ctx):
    J = c.mod("journey")
    cur = c.con.cursor()
    cases, want = [], []
    for tk in SL.sample_types(c)[:2]:
        band_rows = {f["cod_aff_form"]: f for f in J.stage2(cur, "MATHS+SES", "b", tk, None, serie="bg")["formations"]}
        for g in (14.3, 15.6):
            for f in JR.stage2(cur, "MATHS+SES", "b", tk, None, serie="bg", moyenne=g)["formations"]:
                b = band_rows.get(f["cod_aff_form"])
                if b is None or not b.get("taux_zone_source"):
                    continue
                cases.append({"fn": "relire", "args": [b, "b", g]})
                want.append((f["zone"], f["uncertain"], f["large"]))
                cases.append({"fn": "relireVue", "args": [b, "b", g]})
                want.append((f["zone"], f["uncertain"], f["large"]))
    out = SL.node(c.js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad = [(w, (o.get("zone"), o.get("uncertain"), o.get("large"))) for o, w in zip(out, want)
           if isinstance(o, dict) and (o.get("zone"), o.get("uncertain"), o.get("large")) != w]
    errs = [o for o in out if isinstance(o, dict) and "__error__" in o]
    vacuous = c.real and not cases
    return not bad and not errs and not vacuous, f"{len(cases)} page readings of pair-read rows; problems {bad[:3]} {errs[:1]}"


def pb_cases():
    """(target, candidate, expected why): the official rate says « +15 », the zone's rate does not, and the reverse."""
    t = {"zone": "cible", "uncertain": False, "taux_acces_ens": 40.0, "taux_zone": 60.0, "position": 0.5}
    c1 = {"zone": "cible", "uncertain": False, "taux_acces_ens": 70.0, "taux_zone": 62.0, "position": 0.6}   # official +30, zone +2
    c2 = {"zone": "cible", "uncertain": False, "taux_acces_ens": 45.0, "taux_zone": 80.0, "position": 0.6}   # official +5, zone +20
    c3 = {"zone": "cible", "uncertain": False, "taux_acces_ens": 70.0, "taux_zone": None, "position": 0.6}    # no pair rate: official
    # a tie up to floating-point noise (1 ulp: Python and the page's libm round the same share differently) is a tie
    tt = {**t, "position": 0.062423143136910615}
    c4 = {**c2, "position": 0.06242314313691061}
    c5 = {**c2, "position": 0.0624}                                                                          # really lower
    return [(t, c1, None), (t, c2, "acces"), ({**t, "taux_zone": None}, c3, "acces"), (tt, c4, "acces"), (tt, c5, None)]


@check("ZP4 Plan B: why_better / whyBetter compare the rate the zones are read on; a float-noise tie is a tie")
def zp4(c: Ctx):
    PB = c.mod("planb")
    bad = []
    for t, cand, w in pb_cases():
        # the server reads the position from the row's series reading (spos) or its share (cdf); the page view carries it as such
        got = PB.why_better({**t, "bounds": None, "cdf": t.get("position")}, {**cand, "bounds": None, "cdf": cand.get("position")})
        if got != w:
            bad.append(("python", cand, got, w))
    prog_cases = [{"fn": "whyBetter", "args": [t, cand]} for t, cand, _ in pb_cases()]
    import shutil
    import subprocess
    if shutil.which("node"):
        names = ("ZONE_RANK", "SAME_ZONE_ACCESS_GAIN", "isNum", "tauxZone", "whyBetter")
        prog = "\n".join(SL.top(c.js, n) for n in names) + """
const cs = JSON.parse(require('fs').readFileSync(0, 'utf8')); process.stdout.write(JSON.stringify(cs.map((x) => whyBetter(...x.args))));"""
        r = subprocess.run(["node", "-e", prog], input=json.dumps(prog_cases), capture_output=True, text=True, timeout=60)
        if r.returncode:
            return False, r.stderr[-300:]
        for got, (t, cand, w) in zip(json.loads(r.stdout), pb_cases()):
            if got != w:
                bad.append(("page", cand, got, w))
    return not bad, f"problems {bad}"


@check("ZP5 stability: pair-read zones measured with their own method (re-derived), served on such rows, never typed")
def zp5(c: Ctx):
    C = c.mod("calibration")
    from suptracker import calibration as CR
    data = c.memo("cal", lambda: CR.load(c.con.cursor()))
    got = C.pair_persistence(c.con.cursor(), data)
    rep = defaultdict(list)
    for cod, s, key, autres, conf, pos in c.con.execute("""SELECT d.cod_aff_form, d.session, d.doublette_key, d.autres, d.confirmes,
            d.en_position FROM core.rapport_doublette d, core.rapport r WHERE r.cod_aff_form = d.cod_aff_form AND r.session = d.session
            AND r.recoupe AND d.bac = 'bg'""").fetchall():
        rep[(cod, s)].append((key, bool(autres), conf, pos))
    ref, hit = Counter(), Counter()
    for t in (2024, 2025):
        for years in data.values():
            if t not in years or t - 1 not in years:
                continue
            r0, r1 = rep.get((years[t - 1]["cod"], t - 1)), rep.get((years[t]["cod"], t))
            if not r0 or not r1:
                continue
            hist = [s for s in sorted(years) if s < t]
            for key in sorted({k for k, a, _, _ in r0 + r1 if k and not a}):
                a, b = oracle_rate(r0, key), oracle_rate(r1, key)
                if a is None or b is None:
                    continue
                for m in CR.MENTIONS:
                    z = SL._zone(years, hist, m, a[0])
                    if z is None or z[0] not in ("securite", "cible", "ambitieux", "hors_profil"):
                        continue
                    o = SL._zone(years, [t], m, b[0])
                    if o is None:
                        continue
                    k = ("paire:securite_large", False) if z[2] else ("paire:" + z[0], z[1])
                    ref[k] += 1
                    hit[k] += o[0] == z[0]
    want = {k: (n, hit[k] / n) for k, n in ref.items()}
    diff = [k for k in set(want) | set(got) if k not in got or k not in want or got[k][0] != want[k][0] or abs(got[k][1] - want[k][1]) > 1e-12]
    # served: a pair-read row reads its « paire: » row
    cur = c.con.cursor()
    served_bad, n_served = [], 0
    try:
        zp = {(z, u): r for z, u, n, r in cur.execute("SELECT zone, uncertain, n, rate FROM mart.zone_persistence").fetchall()}
        for tk in SL.sample_types(c)[:2]:
            res = JR.stage2(cur, "MATHS+SES", "b", tk, None, serie="bg")
            C.attach(cur, res, "b")
            for f in res["formations"]:
                r = f.get("repere")
                if r and f.get("taux_zone_source"):
                    n_served += 1
                    key = ("paire:securite_large", False) if f.get("large") else ("paire:" + f["zone"], bool(f["uncertain"]))
                    if r["zone_confirmed"] != zp.get(key):
                        served_bad.append((f["cod_aff_form"], key, r["zone_confirmed"], zp.get(key)))
    except Exception as e:  # noqa: BLE001
        served_bad.append(str(e)[:80])
    rebuilt = any(k[0].startswith("paire:") for k in zp) if c.real else True
    ok = not diff and bool(got) and not served_bad and rebuilt
    return ok, (f"pair rows {dict((k, v[0]) for k, v in sorted(got.items()))}; differ {diff[:3]}; served {n_served} rows, problems "
                f"{served_bad[:2]}; warehouse carries them {rebuilt}")


@check("ZP6 the guard: no « Autres » beside an unknown label, no line under 20 candidates, no impossible line (server, report card, page)")
def zp6(c: Ctx):
    J, RPm = c.mod("journey"), c.mod("rapports")
    cases = [  # rows, dkey, expected (rate, kind) or None
        ([("MATHS+SES", False, 100, 60), (None, True, 50, 10)], "MATHS+SES", (60.0, "paire")),
        ([("MATHS+PC", False, 100, 60), (None, True, 50, 10)], "MATHS+SES", (20.0, "autres")),
        ([(None, False, 40, 30), (None, True, 50, 10)], "ART+HLP", None),                     # an unknown label (arts): never « Autres »
        ([(None, False, 40, 30), ("MATHS+SES", False, 80, 40), (None, True, 50, 10)], "MATHS+SES", (50.0, "paire")),
        ([("MATHS+SES", False, 19, 10), (None, True, 50, 10)], "MATHS+SES", None),             # < 20: official
        ([("MATHS+PC", False, 100, 60), (None, True, 19, 10)], "MATHS+SES", None),
        ([("MATHS+SES", False, 30, 31), (None, True, 50, 10)], "MATHS+SES", None),             # impossible line
        ([], "MATHS+SES", None), ([("MATHS+SES", False, 30, 15)], None, None),
    ]
    bad = []
    for rows, dkey, want in cases:
        got = J.pick_pair(rows, dkey)
        g = (got["taux"], got["source"]) if got else None
        if g != want:
            bad.append(("pick_pair", rows, dkey, g, want))
    # the report card's pick (rapports.pick) and the page's twin: the same guard on the bucket
    def block(rows):
        return {"doublettes": {"bg": [{"key": k, "autres": a, "confirmes": cf, "en_position": p, "taux": 100.0 * p / cf} for k, a, cf, p in rows]}}
    guard = [(rows, dkey) for rows, dkey, _ in cases[:4]]
    for rows, dkey in guard:
        r = RPm.pick(block(rows), dkey)
        want = None if (not any(k == dkey and not a for k, a, *_ in rows) and any(k is None and not a for k, a, *_ in rows)) else "x"
        if (r is None) != (want is None):
            bad.append(("rapports.pick", rows, dkey, r))
    import shutil
    import subprocess
    if shutil.which("node"):
        prog = SL.top(c.js, "pickRapport") + """
const cs = JSON.parse(require('fs').readFileSync(0, 'utf8')); process.stdout.write(JSON.stringify(cs.map(([b, k]) => { const x = pickRapport(b, k); return x ? x.source : null; })));"""
        r = subprocess.run(["node", "-e", prog], input=json.dumps([[block(rows), dkey] for rows, dkey in guard]), capture_output=True, text=True, timeout=60)
        if r.returncode:
            return False, r.stderr[-300:]
        for got, (rows, dkey) in zip(json.loads(r.stdout), guard):
            py = RPm.pick(block(rows), dkey)
            if got != (py["source"] if py else None):
                bad.append(("pickRapport", rows, dkey, got))
    return not bad, f"{len(cases)} cases; problems {bad[:3]}"


SPOTS = (r"zoneBadge\(f\.zone, f\.uncertain, f\.large\)\}\$\{zoneAxisNote\(f\)\}",
         r"zoneBadge\(v\.zone, v\.uncertain, v\.large\)\}\$\{v\.status === \"ok\" \? zoneAxisNote\(v\) : \"\"\}",
         r"zoneBadge\(a\.zone, false, a\.large && !a\.uncertain\)\}\$\{zoneAxisNote\(a\)\}",
         r"else if \(target && target\.taux_zone_source\) el\.querySelector\(\"\.sum-note\"\)\.textContent")


@check("ZP7 page and plumbing: the note (escaped, served rate, session) at every zone spot, L'essentiel, legend, method; views; docs; tests")
def zp7(c: Ctx):
    import shutil
    import subprocess
    bad = []
    if shutil.which("node"):
        names = ("esc", "fmt", "pct1", "zoneAxisNote", "ZONE_AXIS")
        prog = "\n".join(SL.top(c.js, n) for n in names) + """
process.stdout.write(JSON.stringify([zoneAxisNote({ taux_zone_source: { taux: 62.5, source: "paire", session: "<b>2025" } }),
  zoneAxisNote({ taux_zone_source: { taux: 40, source: "autres", session: 2025 } }), zoneAxisNote({}), zoneAxisNote(null), ZONE_AXIS]));"""
        r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
        if r.returncode:
            return False, r.stderr[-300:]
        pair, autres, none1, none2, axis = json.loads(r.stdout)
        if "vos deux spécialités" not in pair or "62,5 %" not in pair or "<b>" in pair or "&lt;b&gt;2025" not in pair:
            bad.append(f"pair note {pair}")
        if "autres paires de spécialités" not in autres or none1 or none2:
            bad.append("autres note, or a note without a source")
        if "20 candidats" not in axis or "taux d'accès officiel" not in axis:
            bad.append("legend sentence")
    missing = [p for p in SPOTS if not re.search(p, c.js)]
    if missing:
        bad.append(f"spots {missing}")
    if "${esc(ZONE_AXIS)}" not in SL.top(c.js, "zoneLegend"):
        bad.append("the legend does not say what the zone reads")
    api = (ROOT / "suptracker" / "api.py").read_text()
    if "Le taux lu est celui de vos deux spécialités" not in api:
        bad.append("method text")
    for mod, needle in (("planb", '"taux_zone", "taux_zone_source"'), ("voeux", '"taux_zone", "taux_zone_source"'), ("carte", '"taux_zone": f["taux_zone"]')):
        if needle not in c.src[mod]:
            bad.append(f"{mod} drops the rate")
    J = c.mod("journey")
    if "taux_zone" in J.STAGE2_DROPPED or "taux_zone_source" in J.STAGE2_DROPPED:
        bad.append("public_stage2 drops it")
    if "## The zone read on your pair of specialties" not in (ROOT / "README.md").read_text():
        bad.append("README")
    if "Zone read on the pair rate (owner, 2026-11-19)" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    if "tests/test_zone_paire.py" not in dur or not (ROOT / "tests" / "test_zone_paire.py").exists():
        bad.append("tests")
    return not bad, f"problems {bad}"


MUTANTS = [
    ("journey", "the bucket beside an unknown label", "    elif any(not r[1] and r[0] is None for r in rows):\n        return None", "    elif False:\n        return None", "ZP1"),
    ("journey", "no minimum of candidates", "    if not conf or conf < PAIR_MIN_CONFIRMED or pos is None or pos > conf:", "    if not conf or pos is None or pos > conf:", "ZP1"),
    ("journey", "no « Autres » line", '        chosen = next((r for r in rows if r[1]), None)', '        chosen = None', "ZP1"),
    ("journey", "zone on the official rate", '            **(classify_zone(x["taux_zone"], cdf_zone, lo_zone, hi_zone) if eligible is not False',
     '            **(classify_zone(x["taux_acces_ens"], cdf_zone, lo_zone, hi_zone) if eligible is not False', "ZP2"),
    ("journey", "uncross-checked reports read", "WHERE d.session = ? AND d.bac = 'bg' AND r.recoupe AND list_contains", "WHERE d.session = ? AND d.bac = 'bg' AND list_contains", "ZP1"),
    ("journey", "rate not rounded at the source", '    return {"taux": round(100.0 * pos / conf, 6), "source": source,', '    return {"taux": 100.0 * pos / conf, "source": source,', "ZP1"),
    ("planb", "Plan B on the official rate", '    v = f.get("taux_zone")\n    return v if v is not None else f.get("taux_acces_ens")', '    return f.get("taux_acces_ens")', "ZP4"),
    ("calibration", "pair stability on the official prefix", '    p = "paire:" if z.get("taux_zone_source") else ""', '    p = ""', "ZP5"),
    ("calibration", "pair stability read on the official rate", '                    z = zone_of(years, hist, m, p0["taux"])', '                    z = zone_of(years, hist, m, years[t - 1]["taux"])', "ZP5"),
    ("rapports", "report card claims the bucket", '    if any(x["key"] is None and not x["autres"] for x in rows):\n        return None', '    if False:\n        return None', "ZP6"),
    ("js", "page twin on the official rate", "const tauxZone = (f) => (isNum(f.taux_zone) ? f.taux_zone : f.taux_acces_ens);", "const tauxZone = (f) => f.taux_acces_ens;", "ZP3"),
    ("js", "page Plan B on the official rate", "if (zc >= zt && tauxZone(c) >= (tauxZone(t) || 0) + SAME_ZONE_ACCESS_GAIN", "if (zc >= zt && c.taux_acces_ens >= (t.taux_acces_ens || 0) + SAME_ZONE_ACCESS_GAIN", "ZP4"),
    ("planb", "Plan B decided by float noise", "(_pos(c) or 0) >= (_pos(target) or 0) - POS_EPS:", "(_pos(c) or 0) >= (_pos(target) or 0):", "ZP4"),
    ("js", "page Plan B decided by float noise", "(c.position || 0) >= (t.position || 0) - POS_EPS) return", "(c.position || 0) >= (t.position || 0)) return", "ZP4"),
    ("js", "page claims the bucket", "  if (rows.some((x) => x.key == null && !x.autres)) return null;", "", "ZP6"),
    ("js", "note unescaped", "(rapport public ${esc(s.session)})", "(rapport public ${s.session})", "ZP7"),
    ("js", "note on a spot missing", "${zoneBadge(f.zone, f.uncertain, f.large)}${zoneAxisNote(f)}", "${zoneBadge(f.zone, f.uncertain, f.large)}", "ZP7"),
    ("js", "legend silent", "<p class=\"small muted\">${esc(ZONE_AXIS)}</p>", "", "ZP7"),
]


@check("ZP8 mutation test: every seeded bug is caught")
def zp8(c: Ctx):
    targets = {m[4] for m in MUTANTS}
    q = copy.copy(c)
    q.quick = True
    q._memo = {k: v for k, v in c._memo.items() if k in ("types", "cal", "reports")}
    base = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(q)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(q)
        m._memo = dict(q._memo)
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


def run(db: Path | None = None, real: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(a.db, a.real, set(a.checks.split(",")) if a.checks else None)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
