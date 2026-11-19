"""Red team, « sécurité large » (owner, 2026-11-19): a nuance of a SURE « sécurité » (never a zone of its own), bac général
only: access rate >= 85 % AND the LOWER bound of the share's 95 % interval >= 60 %, under both within-band hypotheses when the
student gives an average. Chosen on the 2024-2025 back-test before use; its stability is measured apart, never typed.

    python scripts/redteam_securite_large.py [--db data/suptracker.duckdb] [--real]

  SL1 server rule: journey.stage2 rows of real types, four mentions, with and without an average, bac général and bac techno, =
      an independent oracle (the zone's interval re-read with the REAL journey.zone_reading, both hypotheses); large only on a
      sure sécurité of the bac général; non-vacuous (some large, some sure safeties not large).
  SL2 page twin (Node): lire / relire / relireVue / carteZonesLocal give the oracle's « large » for the same rows and averages,
      never for a bac techno or pro reading; relire keeps it on the row.
  SL3 the list's reading: voeux.read_list = readList (counts, messages in order): « securite_large » counts a sure sécurité only;
      the information « aucune_securite_large » comes only when a sure safety exists and none is large, never instead of an alert.
  SL4 stability: the back-test measures « sécurité large » apart (persistence_key), re-derived here; calibration.attach gives a
      large row that measured rate; the page never types the rate.
  SL5 page text and display: the pill and the badge say « large » only on a sure sécurité, with its own help (from ZONE_RULES,
      no typed threshold) and its own mark (shape, not colour alone); the legend lists it; the Mes vœux message reads the
      threshold from ZONE_RULES; every place that shows a zone passes the flag; vouvoiement, never a chance.
  SL6 plumbing: ZONE_RULES identical in journey.py and app.js; Plan B, Mes vœux and the map answers carry the flag
      (public_stage2 keeps it); the twin red team compares it (LE); README, CLAUDE.md, tests and durations.
  SL7 real data (--real): share of sure safeties that are large per mention; the stability published by the warehouse
      (mart.zone_persistence) for « sécurité large » above the other sure safeties.
  SL8 mutation test: every seeded bug (server, list, back-test, views, page) is caught.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import time
import types
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from suptracker import journey as JR  # noqa: E402  the REAL journey: the oracle never reads a mutant

CHECKS = []
MODS = {"journey": "journey.py", "voeux": "voeux.py", "calibration": "calibration.py", "planb": "planb.py", "carte": "carte.py"}
LARGE_ACCESS, LARGE_LO = 85.0, 0.60          # the stated rule, typed here on purpose: the oracle does not read the code's constants
MENTIONS = ("sansmention", "ab", "b", "tb")
AVERAGES = (None, 12.4, 13.9, 15.3, 17.2)


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    m = types.ModuleType(f"suptracker.{name}_sl")
    m.__file__, m.__package__ = str(ROOT / "suptracker" / MODS[name]), "suptracker"
    sys.modules[m.__name__] = m                  # dataclasses look their module up while the code runs
    try:
        exec(compile(src, m.__file__, "exec"), m.__dict__)
    finally:
        sys.modules.pop(m.__name__, None)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        self.src = {k: (ROOT / "suptracker" / f).read_text() for k, f in MODS.items()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.quick = False
        self._memo = {}

    def mod(self, name):
        return load(name, self.src[name])

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]


# ------------------------------------------------------------------------------------------------------------ node harness
def top(js: str, name: str) -> str:
    import redteam_lecture as RL
    return RL.top(js, name)


JS_NAMES = ("esc", "fmt", "MENTION_CODES", "BANDS", "BAND_SIGMA", "validMoyenne", "bandOf", "erf", "withinBand", "bandParam",
            "localAverage", "vxProfile", "ZONE_RULES", "MIN_BOUNDS_N", "ZONE_RANK", "VX_SITUATED", "wilsonCI", "zoneOf", "isNum",
            "classifyZone", "isLarge", "seriesPos", "tauxZone", "lire", "relire", "relireVue", "lectureOf", "readList", "carteZonesLocal",
            "zoneHelp", "ZONE_NOT_CHANCE", "ZONE_AXIS", "ZONES", "zoneShape", "ZONE_FILLED", "zoneMark", "isLargeShown", "zonePillHtml",
            "zoneBadge", "zoneLegend", "VX_MSG", "zoneTiles")
DISPATCH = r"""
const F = { lire, relire, relireVue, readList, carteZonesLocal, zonePillHtml, zoneBadge, zoneLegend, zoneHelp, zoneTiles,
            msg: (k) => VX_MSG[k] };
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", () => {
  const out = [];
  for (const c of JSON.parse(raw)) { try { out.push(F[c.fn](...c.args)); } catch (e) { out.push({ __error__: String(e && e.stack || e) }); } }
  process.stdout.write(JSON.stringify(out));
});
"""


def node(js: str, cases: list[dict]):
    exe = shutil.which("node")
    if not exe:
        return None
    prog = "\n".join(top(js, n) for n in JS_NAMES) + DISPATCH
    r = subprocess.run([exe, "-e", prog], input=json.dumps(cases, default=float), capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


# ------------------------------------------------------------------------------------------------------------ oracle
def oracle_large(row: dict, band: str, moyenne: float | None, serie: str) -> bool:
    """The stated rule, from the row's own reading ingredients and the REAL zone_reading: never the code under test."""
    # the rate the zone is read on (taux_zone: the pair rate or the official one; checked by redteam_zone_paire)
    if serie != "bg" or row["zone"] != "securite" or row["uncertain"] or row["taux_zone"] is None:
        return False
    L = row["lec"]
    w = JR.within(moyenne, band) if moyenne is not None else 1.0
    wu = JR.within(moyenne, band, "uniforme") if moyenne is not None else 1.0
    los = []
    for ww in {w, wu}:
        rd = JR.zone_reading("bg", band, L["kt"] - (1.0 - ww) * L["kb"], L["n"], [], ww, L["s"])
        los.append(rd["ci_zone"][0])
    return row["taux_zone"] >= LARGE_ACCESS and all(lo is not None and lo >= LARGE_LO for lo in los)


def sample_types(c: Ctx) -> list[str]:
    def build():
        rows = c.con.execute("""SELECT r.spe_type_key, count(*) FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
            WHERE t.session = (SELECT max(session) FROM core.formation_year) AND r.spe_type_key IS NOT NULL
            GROUP BY 1 ORDER BY hash(r.spe_type_key)""").fetchall()
        mid = [k for k, n in rows if 30 <= n <= 400] or [k for k, _ in sorted(rows, key=lambda r: -r[1])]
        return mid[:4]
    return c.memo("types", build)


def readings(c: Ctx, J) -> list[tuple]:
    """(type, serie, band, moyenne, row) for the sampled types: what the page receives (public rounding aside)."""
    out = []
    tks = sample_types(c)[: 2 if c.quick else 4]
    cur = c.con.cursor()
    for tk in tks:
        for m in (MENTIONS[:2] + MENTIONS[3:] if c.quick else MENTIONS):
            for g in (AVERAGES[:3] if c.quick else AVERAGES):
                band = m if g is None else JR.band_of(g)
                if g is not None and band != m:
                    continue
                for f in J.stage2(cur, "MATHS+SES", band, tk, None, serie="bg", moyenne=g)["formations"]:
                    out.append((tk, "bg", band, g, f))
        for f in J.stage2(cur, None, "b", tk, None, serie="bt")["formations"]:
            out.append((tk, "bt", "b", None, f))
    return out


@check("SL1 server rule: stage 2's « large » = the stated rule (sure sécurité, bac général, access >= 85 %, lower bound >= 60 %, both hypotheses)")
def sl1(c: Ctx):
    J = c.mod("journey")
    rows = readings(c, J)
    bad, n_large, n_sure, n_avg_large = [], 0, 0, 0
    for tk, serie, band, g, f in rows:
        want = oracle_large(f, band, g, serie)
        if bool(f.get("large")) != want:
            bad.append((tk, serie, band, g, f["cod_aff_form"], f.get("large"), want))
        n_large += want
        n_avg_large += want and g is not None
        n_sure += f["zone"] == "securite" and not f["uncertain"] and serie == "bg"
    rules_ok = J.ZONE_RULES.get("large_access") == LARGE_ACCESS and J.ZONE_RULES.get("large_cdf_lo") == LARGE_LO
    # the rule itself, on its edges (an uncertain safety never, whatever its figures; the edges included)
    table = [(("securite", False, 85.0, 0.60), True), (("securite", False, 84.9, 0.90), False), (("securite", False, 99.0, 0.599), False),
             (("securite", True, 95.0, 0.90), False), (("cible", False, 95.0, 0.90), False), (("securite", False, None, 0.9), False),
             (("securite", False, 95.0, None), False), (("ambitieux", False, 100.0, 1.0), False)]
    bad += [("is_large", a, J.is_large(*a), w) for a, w in table if bool(J.is_large(*a)) != w]
    vacuous = c.real and (n_large == 0 or n_large == n_sure or n_avg_large == 0)
    return not bad and rules_ok and not vacuous, (f"{len(rows)} rows, {n_sure} sure safeties of the bac général, {n_large} large "
                                                  f"({n_avg_large} read with an average); rules {rules_ok}; problems {bad[:3]}")


@check("SL2 page twin: lire / relire / relireVue / carteZonesLocal = the oracle's « large », never for bac techno or pro")
def sl2(c: Ctx):
    rows = c.memo("rows", lambda: readings(c, JR))
    cases, want = [], []
    # the page reads the BAND answer (the server's reading without the average) for the average it keeps
    band_row = {(tk, band, f["cod_aff_form"]): f for tk, serie, band, g, f in rows if serie == "bg" and g is None}
    for tk, serie, band, g, f in rows:
        if serie == "bg" and g is not None and (tk, band, f["cod_aff_form"]) in band_row:
            b = band_row[(tk, band, f["cod_aff_form"])]
            cases.append({"fn": "relire", "args": [b, band, g]})
            want.append(("relire", oracle_large(f, band, g, "bg"), f["cod_aff_form"]))
            cases.append({"fn": "relireVue", "args": [{**b, "serie": "bg"}, band, g]})
            want.append(("relireVue", oracle_large(f, band, g, "bg"), f["cod_aff_form"]))
            cases.append({"fn": "lire", "args": [f["lec"], f["taux_zone"], band, g, False]})
            want.append(("lire bt", False, f["cod_aff_form"]))
        elif serie == "bt":
            cases.append({"fn": "relire", "args": [{**f, "serie": "bt"}, band, 15.5]})
            want.append(("relire bt", False, f["cod_aff_form"]))
    # the map: one lectures answer per (type, band, average) with the page's profile
    groups = {}
    for tk, serie, band, g, f in rows:
        if serie == "bg" and g is not None:
            groups.setdefault((tk, band, g), []).append(f)
    for (tk, band, g), fs in list(groups.items())[:6]:
        lec = {"zones": {}, "lectures": {f["cod_aff_form"]: {"lec": f["lec"], "taux_acces_ens": f["taux_acces_ens"], "taux_zone": f["taux_zone"], "zone": f["zone"]}
                                         for f in fs}}
        cases.append({"fn": "carteZonesLocal", "args": [lec, {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": band, "moyenne": g}]})
        want.append(("carte", sorted(f["cod_aff_form"] for f in fs if oracle_large(f, band, g, "bg")), tk))
    out = node(c.js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    bad, n_true = [], 0
    for got, (kind, w, cod) in zip(out, want):
        if isinstance(got, dict) and "__error__" in got:
            return False, got["__error__"][:400]
        val = got.get("larges") if kind == "carte" else bool(got.get("large"))
        n_true += bool(w)
        if val != w:
            bad.append((kind, cod, val, w))
    vacuous = c.real and n_true == 0
    return not bad and not vacuous, f"{len(cases)} page readings, {n_true} large expected; problems {bad[:3]}"


def lists():
    sure_l = {"status": "ok", "zone": "securite", "uncertain": False, "large": True, "serie": "bg"}
    sure = {"status": "ok", "zone": "securite", "uncertain": False, "large": False, "serie": "bg"}
    sure_bt = {"status": "ok", "zone": "securite", "uncertain": False, "large": False, "serie": "bt"}   # no nuance outside the bac général
    unc_l = {"status": "ok", "zone": "securite", "uncertain": True, "large": True}            # never counted (forged flag)
    cible_l = {"status": "ok", "zone": "cible", "uncertain": False, "large": True}            # never counted (forged flag)
    cible = {"status": "ok", "zone": "cible", "uncertain": False, "large": False}
    amb = {"status": "ok", "zone": "ambitieux", "uncertain": False, "large": False}
    return [([sure_l, cible, amb], 1, False), ([sure, cible, amb], 0, True), ([sure, unc_l, cible_l, cible], 0, True),
            ([unc_l, cible], 0, False), ([], 0, False), ([sure_l, sure, cible], 1, False), ([cible_l, amb], 0, False),
            ([sure], 0, True), ([sure_bt, cible], 0, False), ([sure_bt], 0, False)]


@check("SL3 the list's reading: read_list = readList; a sure sécurité only counts; « aucune_securite_large » only with a sure safety and none large")
def sl3(c: Ctx):
    VX = c.mod("voeux")
    L = lists()
    bad = []
    py = [json.loads(json.dumps(VX.read_list(v))) for v, _, _ in L]
    for (v, n_large, info), r in zip(L, py):
        codes = [m["code"] for m in r["messages"]]
        if r.get("securite_large") != n_large:
            bad.append(("count", v, r.get("securite_large"), n_large))
        if ("aucune_securite_large" in codes) != info:
            bad.append(("message", v, codes))
        if "aucune_securite_large" in codes and "aucune_securite" in codes:
            bad.append(("both", codes))
        if "aucune_securite_large" in codes and r["messages"][codes.index("aucune_securite_large")]["niveau"] != "info":
            bad.append(("level", codes))
    out = node(c.js, [{"fn": "readList", "args": [v]} for v, _, _ in L])
    if out is not None:
        for got, want in zip(out, py):
            if got != want:
                bad.append(("twin", got, want))
                break
    return not bad, f"{len(L)} lists; problems {bad[:3]}"


@check("SL4 stability: « sécurité large » measured apart in the back-test (re-derived), served on large rows, never typed")
def sl4(c: Ctx):
    C = c.mod("calibration")
    from suptracker import calibration as CR
    data = c.memo("cal", lambda: CR.load(c.con.cursor()))
    keys = sorted(data)[: 1500 if c.quick else 4000]
    small = {k: data[k] for k in keys}
    got = C.zone_persistence(small)
    # independent: the same next-campaign confirmation, keyed by the stated rule
    ref = Counter()
    hit = Counter()
    for t in (2024, 2025):
        for years in small.values():
            if t not in years or t - 1 not in years:
                continue
            hist = [s for s in sorted(years) if s < t]
            for m in CR.MENTIONS:                    # the mentions the back-test reads (calibration's own list)
                z = _zone(years, hist, m, years[t - 1]["taux"])
                if z is None or z[0] not in ("securite", "cible", "ambitieux", "hors_profil"):
                    continue
                o = _zone(years, [t], m, years[t]["taux"])
                if o is None:
                    continue
                k = ("securite_large", False) if z[2] else (z[0], z[1])
                ref[k] += 1
                hit[k] += o[0] == z[0]
    want = {k: (n, hit[k] / n) for k, n in ref.items()}
    diff = [k for k in set(want) | set(got) if k not in got or k not in want or got[k][0] != want[k][0] or abs(got[k][1] - want[k][1]) > 1e-12]
    # attach: a large row reads the large row of the table
    cur = c.con.cursor()
    res = JR.stage2(cur, "MATHS+SES", "b", sample_types(c)[0], None, serie="bg")
    att = ok_att = 0
    try:
        zp = {(z, u): (n, r) for z, u, n, r in cur.execute("SELECT zone, uncertain, n, rate FROM mart.zone_persistence").fetchall()}
        C.attach(cur, res, "b")
        for f in res["formations"]:
            if f.get("repere") and f.get("large"):
                att += 1
                pre = "paire:" if f.get("taux_zone_source") else ""          # a zone read on the pair rate reads its own rows
                ok_att += f["repere"]["zone_confirmed"] == zp.get((pre + "securite_large", False), (None, None))[1]
    except duckdb.Error:
        zp = {}
    typed = re.findall(r"9 sur 10|90 ?%|90\.\d ?%", _page_text(c.js))
    served = att == ok_att and (att > 0 or not c.real or ("securite_large", False) not in zp)
    ok = not diff and ("securite_large", False) in got and served and not typed
    return ok, f"rows {dict((k, v[0]) for k, v in sorted(got.items()))}; differ {diff[:3]}; large rows served {ok_att}/{att}; typed rates {typed}"


def _zone(years, sessions, mention, taux):
    if taux is None:
        return None
    rows = [years[s] for s in sessions]
    k = sum(sum(r["counts"][x] for x in JR.MENTIONS[: JR.MENTIONS.index(mention) + 1]) for r in rows)
    n = sum(sum(r["counts"][x] for x in JR.MENTIONS) for r in rows)
    if not n:
        return None
    neo = sum(r["neobac"] or 0 for r in rows)
    if neo and sum(r["margins"].get("acc_bg") or 0 for r in rows) / neo < JR.MIN_GENERAL_SHARE:
        return None
    rd = JR.zone_reading("bg", mention, k, n, [r["margins"] for r in rows])
    z = JR.classify_zone(taux, rd["cdf_zone"], *rd["ci_zone"])
    lo = rd["ci_zone"][0]
    large = z["zone"] == "securite" and not z["uncertain"] and taux >= LARGE_ACCESS and lo is not None and lo >= LARGE_LO
    return z["zone"], bool(z["uncertain"]), large


def _page_text(js: str) -> str:
    """The strings of the zone help, the legend and the Mes vœux messages (where a typed rate would be read by a student)."""
    return "\n".join(top(js, n) for n in ("zoneHelp", "zoneLegend", "VX_MSG", "zoneTiles"))


DISPLAY_SPOTS = (
    r"zonePillHtml\(target\.zone, false, target\.large && !target\.uncertain\)",
    r"zoneBadge\(d\.target\.zone, false, d\.target\.large && !d\.target\.uncertain\)",
    r"zoneBadge\(a\.zone, false, a\.large && !a\.uncertain\)",
    r"zoneBadge\(f\.zone, f\.uncertain, f\.large\)",
    r"zoneBadge\(v\.zone, v\.uncertain, v\.large\)\}\$\{v\.status === \"ok\" \? zoneAxisNote\(v\) : \"\"\}\$\{flags\}",
    r"robVoeuxCard\(d\.voeux, \(v\) => \(v\.status === \"ok\" \? zoneBadge\(v\.zone, v\.uncertain, v\.large\)",
    r"zoneBadge\(\"securite\", false, f\.large\)",
    r"zoneBadge\(z, false, f\.large\)",
    r"f\.large = ok && f\.zone === \"securite\" && larges\.has\(f\.cod_aff_form\)",
    r"zoneTiles\(z, z\.hors_profil \+ z\.non_ouvert \+ z\.indetermine \+ z\.non_situe, L\.securite_large\)",
)


@check("SL5 page text: « large » only on a sure sécurité, own help from ZONE_RULES, own mark, in the legend, at every zone spot; no chance")
def sl5(c: Ctx):
    js = c.js
    H = "<b>&"
    cases = [{"fn": "zonePillHtml", "args": ["securite", False, True]}, {"fn": "zonePillHtml", "args": ["securite", True, True]},
             {"fn": "zonePillHtml", "args": ["cible", False, True]}, {"fn": "zonePillHtml", "args": ["securite", False, False]},
             {"fn": "zoneBadge", "args": ["securite", False, True]}, {"fn": "zoneBadge", "args": ["securite", True, True]},
             {"fn": "zoneBadge", "args": ["ambitieux", False, True]}, {"fn": "zoneLegend", "args": []},
             {"fn": "zoneHelp", "args": ["securite_large"]}, {"fn": "msg", "args": ["aucune_securite_large"]},
             {"fn": "zoneTiles", "args": [{"securite": 3, "cible": 1, "ambitieux": 0}, 0, 2]},
             {"fn": "zoneTiles", "args": [{"securite": 2, "cible": 1, "ambitieux": 0}, 0, 0]}]
    out = node(js, cases)
    if out is None:
        return True, "skipped (node not installed)"
    pill_l, pill_unc, pill_cible, pill_plain, bad_l, bad_unc, bad_amb, legend, helpl, msg, tiles, tiles0 = out
    bad = []
    if "sécurité large" not in re.sub(r"<[^>]+>", "", pill_l) or helpl not in pill_l.replace("&#39;", "'"):
        bad.append("the large pill lacks its name or its help")
    if " large" in re.sub(r"<[^>]+>", "", pill_unc + pill_cible + pill_plain + bad_unc + bad_amb):
        bad.append("« large » shown on an uncertain safety, another zone or a plain sécurité")
    if "Vœu de sécurité large" not in re.sub(r"<[^>]+>", "", bad_l):
        bad.append("the large badge lacks its name")
    if pill_l.count("<circle") < 2 or pill_plain.count("<circle") != 1:
        bad.append("the large mark is not its own shape (the colour alone)")
    if helpl not in legend.replace("&#39;", "'"):
        bad.append("the legend does not explain the nuance")
    if "85 %" not in helpl or "60 admis sur 100" not in helpl:
        bad.append(f"help text {helpl}")
    zh = top(js, "zoneHelp")
    if "${R.large_access}" not in zh or "${sur100(R.large_cdf_lo)}" not in zh:
        bad.append("the help types its thresholds instead of reading ZONE_RULES")
    if "${ZONE_RULES.large_access}" not in top(js, "VX_MSG") or "85 %" not in msg:
        bad.append("the Mes vœux message types its threshold")
    if "dont 2 « sécurité large »" not in tiles or "large" in tiles0:
        bad.append("the Mes vœux tile does not count the large safeties (or prints « dont 0 »)")
    missing = [p for p in DISPLAY_SPOTS if not re.search(p, js)]
    if missing:
        bad.append(f"zone spots without the flag {missing[:3]}")
    txt = re.sub(r"<[^>]+>", " ", helpl + msg + legend)
    if re.search(r"\b(tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"chance", txt.replace("jamais une chance", ""), re.I):
        bad.append("tutoiement or a chance")
    if H in pill_l:
        bad.append("unescaped")
    return not bad, f"problems {bad}"


@check("SL6 plumbing: ZONE_RULES twins, views carry the flag, the twin red team compares it, docs, tests")
def sl6(c: Ctx):
    J = c.mod("journey")
    bad = []
    m = re.search(r"const ZONE_RULES = (\{[^}]*\});", c.js)
    js_rules = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1))) if m else {}
    if js_rules != J.ZONE_RULES:
        bad.append(f"ZONE_RULES differ {js_rules} {J.ZONE_RULES}")
    if '"large"' not in c.src["planb"].split("def _view", 1)[1].split("v = {", 1)[0]:
        bad.append("Plan B's view drops the flag")
    if '"large"' not in c.src["voeux"].split("ROW_KEYS = (", 1)[1].split(")", 1)[0]:
        bad.append("Mes vœux rows drop the flag")
    if '"larges": sorted(larges)' not in c.src["carte"] or '"large": f["large"]' not in c.src["carte"]:
        bad.append("the map answers drop the flag")
    if "large" in J.STAGE2_DROPPED:
        bad.append("public_stage2 drops the flag")
    rl = (ROOT / "scripts" / "redteam_lecture.py").read_text()
    if not all(f'"uncertain", "large"' in rl.split(k, 1)[1].split("\n", 1)[0] for k in ("ROW_KEYS = (", "VIEW_KEYS = (", "VX_ROW = (")) \
            or '"isLarge"' not in rl or '"larges"' not in rl:
        bad.append("the twin red team does not compare the flag")
    readme = (ROOT / "README.md").read_text()
    if "## Sécurité large" not in readme:
        bad.append("README")
    if "« Sécurité large » (owner, 2026-11-19)" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    if "tests/test_securite_large.py" not in dur or not (ROOT / "tests" / "test_securite_large.py").exists():
        bad.append("tests")
    return not bad, f"problems {bad}"


@check("SL7 real data: coverage per mention, the published stability of « sécurité large » above the other sure safeties")
def sl7(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    cur = c.con.cursor()
    try:
        pub = {(z, u): (n, r) for z, u, n, r in cur.execute("SELECT zone, uncertain, n, rate FROM mart.zone_persistence").fetchall()}
    except duckdb.Error:
        pub = {}
    if ("securite_large", False) not in pub:
        return False, "mart.zone_persistence has no « sécurité large » row: rebuild the warehouse (data workflow)"
    cov = {}
    for tk, serie, band, g, f in c.memo("rows", lambda: readings(c, JR)):
        if serie == "bg" and g is None and f["zone"] == "securite" and not f["uncertain"]:
            a = cov.setdefault(band, [0, 0])
            a[0] += 1
            a[1] += bool(f.get("large"))
    nl, rl = pub[("securite_large", False)]
    ns, rs = pub.get(("securite", False), (0, 1.0))
    share = {b: f"{100 * v[1] / v[0]:.0f} % of {v[0]}" for b, v in cov.items() if v[0]}
    return rl > rs, f"stability: large {rl:.3f} (n={nl}) vs other sure safeties {rs:.3f} (n={ns}); large share per mention {share}"


# ------------------------------------------------------------------------------------------------------------ SL8 mutants
MUTANTS = [
    ("journey", "the point instead of the lower bound", """        x["large"] = (serie == "bg" and is_large(x["zone"], x["uncertain"], x["taux_zone"], lo_zone)
                      and is_large(x["zone"], x["uncertain"], x["taux_zone"], lo_u))""",
     """        x["large"] = (serie == "bg" and is_large(x["zone"], x["uncertain"], x["taux_zone"], cdf_zone))""", "SL1"),
    ("journey", "uniform hypothesis ignored", "                      and is_large(x[\"zone\"], x[\"uncertain\"], x[\"taux_zone\"], lo_u))",
     "                      and True)", "SL1"),
    ("journey", "bac techno read large", '        x["large"] = (serie == "bg" and is_large(', '        x["large"] = (is_large(', "SL1"),
    ("journey", "uncertain safeties large", '    return (zone == "securite" and not uncertain and taux is not None', '    return (zone == "securite" and taux is not None', "SL1"),
    ("journey", "access threshold moved", '    "large_access": 85.0,', '    "large_access": 80.0,', "SL1"),
    ("journey", "bound threshold moved", '    "large_cdf_lo": 0.60,', '    "large_cdf_lo": 0.50,', "SL1"),
    ("voeux", "uncertain large counted", 'large = sum(1 for v in voeux if v.get("zone") == "securite" and not v.get("uncertain") and v.get("large"))',
     'large = sum(1 for v in voeux if v.get("large"))', "SL3"),
    ("voeux", "information missing", '        if sure_bg and not large:', '        if False:', "SL3"),
    ("voeux", "information for bac techno", '        if sure_bg and not large:', '        if sure and not large:', "SL3"),
    ("js", "twin information for bac techno", 'if (sureBg && !large) msgs.push', 'if (sure && !large) msgs.push', "SL3"),
    ("voeux", "information as an alert", '            msgs.append(("info", "aucune_securite_large"))', '            msgs.append(("warn", "aucune_securite_large"))', "SL3"),
    ("calibration", "stability not measured apart", '    return (p + "securite_large", False) if z.get("large") else (p + z["zone"], bool(z.get("uncertain")))',
     '    return (p + z["zone"], bool(z.get("uncertain")))', "SL4"),
    ("calibration", "large read on the point", '    return {**z, "large": J.is_large(z["zone"], z["uncertain"], taux, rd["ci_zone"][0])}',
     '    return {**z, "large": J.is_large(z["zone"], z["uncertain"], taux, rd["cdf_zone"])}', "SL4"),
    ("planb", "Plan B view drops the flag", '"zone", "uncertain", "large",\n            "taux_acces_ens", "taux_zone"', '"zone", "uncertain",\n            "taux_acces_ens", "taux_zone"', "SL6"),
    ("carte", "map answer drops the flag", '    return {"zones": out, "larges": sorted(larges), **', '    return {"zones": out, **', "SL6"),
    ("js", "page twin ignores the uniform hypothesis", "const large = !!bg && isLarge(zone, uncertain, taux, r.ciz[0]) && isLarge(zone, uncertain, taux, loU);",
     "const large = !!bg && isLarge(zone, uncertain, taux, r.ciz[0]);", "SL2"),
    ("js", "page twin reads bac techno", "const large = !!bg && isLarge(", "const large = isLarge(", "SL2"),
    ("js", "page twin threshold", "taux >= ZONE_RULES.large_access && ciLo >= ZONE_RULES.large_cdf_lo", "taux >= ZONE_RULES.large_access && ciLo >= 0.5", "SL2"),
    ("js", "relire drops the flag", "  return { ...f, zone: r.zone, uncertain: r.uncertain, large: r.large,", "  return { ...f, zone: r.zone, uncertain: r.uncertain,", "SL2"),
    ("js", "map twin drops larges", "  return { zones, larges: larges.sort() };", "  return { zones, larges: [] };", "SL2"),
    ("js", "readList counts uncertain", "const large = vx.filter((v) => v.zone === \"securite\" && !v.uncertain && v.large).length;",
     "const large = vx.filter((v) => v.large).length;", "SL3"),
    ("js", "large shown on uncertain", "const isLargeShown = (z, uncertain, large) => !!large && z === \"securite\" && !uncertain;",
     "const isLargeShown = (z, uncertain, large) => !!large;", "SL5"),
    ("js", "same mark", '  if (large && z === "securite") return', '  if (false) return', "SL5"),
    ("js", "legend without the nuance", '<li>${zonePillHtml("securite", false, true)} ${esc(zoneHelp("securite_large"))}</li>', "", "SL5"),
    ("js", "typed threshold in the help", "taux d'accès d'au moins ${R.large_access} %.", "taux d'accès d'au moins 85 %.", "SL5"),
    ("js", "a spot without the flag", "zoneBadge(\"securite\", false, f.large)", "zoneBadge(\"securite\")", "SL5"),
    ("js", "JS rules differ", "securite_cdf: 0.50, large_access: 85.0, large_cdf_lo: 0.60 };", "securite_cdf: 0.50, large_access: 85.0, large_cdf_lo: 0.55 };", "SL6"),
]


@check("SL8 mutation test: every seeded bug is caught")
def sl8(c: Ctx):
    targets = {m[4] for m in MUTANTS}
    q = copy.copy(c)
    q.quick, q.real = True, c.real
    q._memo = {k: v for k, v in c._memo.items() if k in ("types", "cal")}
    base = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(q)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(q)
        m._memo = {k: v for k, v in q._memo.items() if k in ("types", "cal") or (k == "rows" and kind != "journey")}
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
