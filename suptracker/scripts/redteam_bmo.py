"""Red team of the BMO 2026 card (sprint 14 follow-up, short-term hiring context).

    python scripts/redteam_bmo.py [--db data/suptracker.duckdb] [--real]

  B1 the stored sums are re-derived independently from the basin cells (openpyxl, not pandas; "*" = masked) for
     2026 and 2025, and equal the workbook's own France sheet (two independent aggregations agree); the national
     2025 total covers at least 98 % of France Travail's official figure (workbook's control sheet)
  B2 consistency: difficult and seasonal projects never exceed projects; the 217 codes are FAP-2021 228 codes with the
     Dares label; the same codes both years
  B3 serving: a job's BMO families are exactly the 228-level parents of its FAP-2021 families (sprint 13); values,
     shares, fragility (masked cells could move the share by > 5 points) and the national reference are re-derived
  B4 coverage of jobs with a usable ROME code
  B5 page (card run with Node on hostile data): escaped, "intentions", "ni des offres", "ne dit rien de l'emploi en
     2030", "au moins", fragile badge, no 2025 comparison, no "chance" / "garanti"
  B6 upkeep: register online, methodology and feature, release wiring, warehouse under 95 MB
  B7 mutation test
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import bmo as B  # noqa: E402
from suptracker import metiers as MT  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def raw_sums(path: Path):
    """{(year, code): [p, mp, d, md, s, ms, cells]} from the basin sheets with openpyxl, header found by name."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out = {}
    for year in (2026, 2025):
        it = wb[f"Bassins_{year}"].iter_rows(values_only=True)
        for row in it:
            if row and "Code métier BMO" in row:
                head = list(row)
                break
        ic = head.index("Code métier BMO")
        ip, idf, isz = head.index(f"Projets {year}"), head.index(f"dont difficiles {year}"), head.index(f"dont saisonniers {year}")
        for row in it:
            if not row or not row[ic]:
                continue
            acc = out.setdefault((year, str(row[ic]).strip()), [0.0, 0, 0.0, 0, 0.0, 0, 0])
            for k, i in enumerate((ip, idf, isz)):
                v = row[i]
                if isinstance(v, str) and v.strip() == "*":
                    acc[2 * k + 1] += 1
                else:
                    acc[2 * k] += float(v)
            acc[6] += 1
    france = {}
    rows = list(wb["Métiers_France"].iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and "Code métier BMO" in r)
    head = list(rows[h])
    for r in rows[h + 1:]:
        if r and r[0] and re.fullmatch(r"[A-Z][A-Z0-9]X\d{2}[a-z]?|[A-Z]\d[A-Z]\d{2}", str(r[0]).strip()):
            france[str(r[0]).strip()] = (r[head.index("Projets 2026")], r[head.index("dont difficiles")], r[head.index("dont saisonniers")])
    ctl = list(wb["Contrôle_2025"].iter_rows(values_only=True))
    official = next(r for r in ctl if r and r[0] and str(r[0]).startswith("France entière"))
    return out, france, (official[1], official[2])


class Ctx:
    def __init__(self, db: Path, real: bool, source: Path | None = None):
        self.db, self.real = db, real
        self.src = source or B.source_path()
        self.con = duckdb.connect(str(db), read_only=True)
        self.raw, self.france, self.official = raw_sums(self.src)
        self.rows = {(r[0], r[1]): r for r in self.con.execute("SELECT * FROM core.bmo_metier").fetchall()}


@check("B1 sums re-derived from the basin cells (openpyxl) = stored = the workbook's France sheet; 2025 covers >= 98 % of the official total")
def b1(c: Ctx):
    bad = []
    for key, (p, mp, d, md, s, ms, n) in c.raw.items():
        r = c.rows.get(key)
        if not r or (r[3], r[4], r[5], r[6], r[7], r[8], r[9]) != (p, mp, d, md, s, ms, n):
            bad.append(key)
    extra = sorted(set(c.rows) - set(c.raw))
    fr = [code for code, (p, d, s) in c.france.items() if c.raw.get((2026, code), [None])[0] != p
          or c.raw[(2026, code)][2] != d or c.raw[(2026, code)][4] != s]
    tot25 = sum(v[0] for (y, _), v in c.raw.items() if y == 2025)
    cover = tot25 / c.official[0] if c.official[0] else 0
    ok = not bad and not extra and not fr and 0.98 <= cover <= 1.0 and len(c.raw) > 400
    return ok, f"{len(c.raw)} code-years, stored differ {bad[:3]}, extra {extra[:3]}; France sheet differs {fr[:3]}; 2025 published / official {cover:.2%}"


@check("B2 consistency: difficult and seasonal <= projects; codes are FAP-2021 228 codes with the Dares label; same codes both years")
def b2(c: Ctx):
    over = [k for k, v in c.raw.items() if v[2] > v[0] or v[4] > v[0]]
    nomen = dict(c.con.execute("SELECT DISTINCT fap228, lib228 FROM core.nomen_fap2021").fetchall())
    lab = {r[1]: r[2] for r in c.rows.values() if r[0] == 2026}
    unknown = sorted(code for code in lab if code not in nomen)
    renamed = sorted(code for code in lab if code in nomen and nomen[code].strip().lower() != lab[code].strip().lower())
    years = {y: {k for (yy, k) in c.raw if yy == y} for y in (2025, 2026)}
    ok = not over and not unknown and not renamed and years[2025] == years[2026] and len(years[2026]) >= 200
    return ok, f"over {over[:3]}; not FAP-228 {unknown[:3]}; label differs {renamed[:3]}; same codes both years {years[2025] == years[2026]} ({len(years[2026])})"


def expected_shares(v):
    p, mp, d, md, s, ms, _ = v
    sd = d / p
    lo, hi = d / (p + 4 * mp), min(1.0, (d + 4 * md) / p)
    return sd, s / p, max(sd - lo, hi - sd) * 100


@check("B3 serving: families = the 228-level parents of the job's FAP-2021 families; values, shares, fragility, national")
def b3(c: Ctx):
    parent = dict(c.con.execute("SELECT fap341, fap228 FROM core.nomen_fap2021").fetchall())
    nat = [v for (y, _), v in c.raw.items() if y == 2026]
    np_, nd = sum(v[0] for v in nat), sum(v[2] for v in nat)
    jobs = [m for (m,) in c.con.execute("SELECT met_id FROM core.onisep_metier ORDER BY 1").fetchall()]
    sample = jobs if not c.real else jobs[:: max(1, len(jobs) // 200)]
    bad, n = [], 0
    for mid in sample:
        d = MT.detail(c.con, mid)
        exp = {parent[f["code"]] for x in d["codes"] for f in x.get("fap2021", []) if f["code"] in parent}
        got = {f["code"]: f for f in (d["bmo"] or {}).get("familles", [])}
        if set(got) != exp:
            bad.append(f"{mid}: {sorted(got)} != {sorted(exp)}")
            continue
        if got and abs(d["bmo"]["national"]["part_difficile"] - nd / np_) > 1e-12:
            bad.append(f"{mid}: national share")
        for code, f in got.items():
            n += 1
            v = c.raw.get((2026, code))
            if not v:
                if not f["absent"]:
                    bad.append(f"{mid} {code}: figure without data")
                continue
            sd, ss, marge = expected_shares(v)
            if f["projets"] != v[0] or abs(f["part_difficile"] - sd) > 1e-12 or abs(f["part_saisonniere"] - ss) > 1e-12 \
                    or abs(f["marge_points"] - marge) > 1e-9 or f["fragile"] != (marge > 5):
                bad.append(f"{mid} {code}: values")
    ok = not bad and n > 0
    return ok, f"{len(sample)} jobs, {n} job families checked, {len(bad)} wrong {bad[:3]}"


@check("B4 coverage: jobs with a usable ROME code get BMO figures")
def b4(c: Ctx):
    jobs = [m for (m,) in c.con.execute("""SELECT DISTINCT met_id FROM core.onisep_metier_rome
                                           WHERE rome IN (SELECT rome FROM core.nomen_rome) ORDER BY 1""").fetchall()]
    cov = sum(any(not f["absent"] for f in (MT.detail(c.con, m)["bmo"] or {}).get("familles", [])) for m in jobs)
    rate = cov / len(jobs) if jobs else 0
    return (rate >= 0.9 or not c.real), f"{cov}/{len(jobs)} jobs with figures ({rate:.1%})"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 14 follow-up: les recrutements prévus en 2026")
    return js[i: js.index("\n// ---- ", i + 1)]


HOSTILE = {"annee": 2026, "national": {"projets": 2237486, "part_difficile": 0.4314, "part_saisonniere": 0.3229}, "familles": [
    {"code": "<b>V1X80</b>", "libelle": "<script>alert(1)</script>", "absent": False, "toutes_qualifications": True, "projets": 36491,
     "part_difficile": 0.6002, "part_saisonniere": 0.0908, "fragile": False, "projets_2025": 39004},
    {"code": "M1X80", "libelle": "<img src=x onerror=alert(2)>", "absent": False, "toutes_qualifications": False, "projets": 9331,
     "part_difficile": 0.4305, "part_saisonniere": 0.0225, "fragile": True, "projets_2025": 13987},
    {"code": "<svg onload=alert(3)>", "absent": True}]}


def render(js: str):
    node = shutil.which("node")
    if not node:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    prog = helpers + "\n" + block(js) + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(P.map(bmoCard)));"
    r = subprocess.run([node, "-e", prog], input=json.dumps([HOSTILE, None, {"familles": []}]), capture_output=True, text=True, timeout=60)
    return ("__error__" + r.stderr[-300:]) if r.returncode else r.stdout


def ui(js: str) -> tuple[bool, str]:
    out = render(js)
    wired = "${bmoCard(d.bmo)}" in js
    if out is None:
        return wired, "node not installed"
    if out.startswith("__error__"):
        return False, out
    html, none, empty = json.loads(out)
    html = html.replace(" ", " ").replace(" ", " ")
    leaks = re.findall(r"<(?:script|img|svg|b)\b", html)
    words = all(w in html for w in ("Intentions d'embauche", "ni des offres d'emploi ni des embauches", "ne dit rien de l'emploi en 2030",
                                     "au moins 36 491", "au moins 9 331", "fragile", "60 %", "tous métiers : 43 %", "valeurs inférieures à 5",
                                     "selon la qualification du poste", "Pas de chiffre BMO"))
    no_2025 = "39 004" not in html and "13 987" not in html
    badge = html.count('<span class="badge">fragile</span>') == 1          # only the fragile family carries it
    words = words and badge
    banned = [w for w in ("chance", "garanti", "probabilit") if w in html.lower()]
    ok = wired and not leaks and words and no_2025 and not banned and none == "" and empty == ""
    return ok, f"raw tags {leaks[:3]}; wording and figures {words}; no 2025 comparison {no_2025}; banned {banned}; wired {wired}"


@check("B5 page (card run with Node on hostile data): escaped, intentions wording, floors, fragile, no 2025 comparison")
def b5(c: Ctx):
    return ui(APP_JS.read_text())


@check("B6 upkeep: register online, methodology and feature, warehouse under 95 MB")
def b6(c: Ctx):
    from suptracker import sources as SRC
    from suptracker.api import FEATURES, METHODOLOGY
    s = next(x for x in SRC.SOURCES if x["key"] == "bmo")
    m = METHODOLOGY.get("bmo_2026", "")
    size = c.db.stat().st_size / 1e6
    ok = s["status"] == "en_ligne" and "bmo_2026" in FEATURES and "au moins" in m and "rien de l'emploi en 2030" in m and (size < 95 or not c.real)
    return ok, f"register {s['status']}; feature and methodology {bool(m) and 'bmo_2026' in FEATURES}; warehouse {size:.1f} MB"


UI_MUTANTS = [
    ("unescaped label", "${esc(f.code)} · ${esc(f.libelle || \"\")}</h3>", "${esc(f.code)} · ${f.libelle || \"\"}</h3>"),
    ("floor wording dropped", "<td class=\"num\">au moins ${fmt(f.projets)}</td>", "<td class=\"num\">${fmt(f.projets)}</td>"),
    ("fragile badge dropped", "${f.fragile ? ' <span class=\"badge\">fragile</span>' : \"\"}", ""),
    ("2025 comparison shown", "<td class=\"num\">au moins ${fmt(f.projets)}</td>", "<td class=\"num\">au moins ${fmt(f.projets)} (${fmt(f.projets_2025)} en 2025)</td>"),
    ("intentions wording dropped", "ce ne sont ni des offres d'emploi ni des embauches, et cela ne dit rien de l'emploi en 2030", "les embauches de l'année"),
    ("national reference dropped", "(tous métiers : ${pct(n.part_difficile)})", ""),
]


@check("B7 mutation test: masking, years, denominators, mapping, fragility and page bugs are each caught")
def b7(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 14 follow-up: les recrutements prévus en 2026")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        if old not in js[i:j] or ui(js[:i] + js[i:j].replace(old, new, 1) + js[j:])[0]:
            missed.append(name)

    def rebuilt(apply, fns):
        import tempfile
        saved = {k: getattr(B, k) for k in ("read_year", "for_codes", "share_bounds", "SHEETS", "FRAGILE_POINTS", "MASK_MAX")}
        tmp = Path(tempfile.gettempdir()) / f"bmo_mutant_{c.db.stem}.duckdb"
        try:
            apply()
            shutil.copy(c.db, tmp)
            con = duckdb.connect(str(tmp))
            B.build(con, c.src)
            con.close()
            m = Ctx.__new__(Ctx)
            m.__dict__.update({k: v for k, v in c.__dict__.items() if k not in ("con", "rows")})
            m.db, m.con = tmp, duckdb.connect(str(tmp), read_only=True)
            m.rows = {(r[0], r[1]): r for r in m.con.execute("SELECT * FROM core.bmo_metier").fetchall()}
            caught = any(not fn(m)[0] for fn in fns)
            m.con.close()
            return caught
        except Exception:  # noqa: BLE001
            return True
        finally:
            for k, v in saved.items():
                setattr(B, k, v)
            tmp.unlink(missing_ok=True)

    orig_read, orig_for, orig_bounds = B.read_year, B.read_year.__globals__["for_codes"], B.share_bounds

    def star_as_five(path, year):
        g = orig_read(path, year)
        g["projets"] = g["projets"] + 5 * g["masques_projets"]          # masked cells counted at 5
        return g

    def wrong_denominator(con, codes):
        out = orig_for(con, codes)
        for f in (out or {}).get("familles", []):
            if not f.get("absent") and f["part_difficile"]:
                f["part_difficile"] = f["part_difficile"] * f["projets"] / (f["projets"] + (f.get("cellules_masquees") or 0) * 4)
        return out

    def fap341_codes(con, codes):
        out = orig_for(con, codes)
        if out:
            for f in out["familles"]:
                f["code"] = f["code"] + "a"                              # the 341 code used instead of its 228 parent
        return out

    data_mutants = [
        ("masked cells counted as 5", lambda: setattr(B, "read_year", star_as_five), (b1,)),
        ("2025 figures served as 2026", lambda: setattr(B, "read_year", lambda path, year: orig_read(path, 2025).assign(annee=year)), (b1,)),
        ("difficult share over a wrong denominator", lambda: setattr(B, "for_codes", wrong_denominator), (b3,)),
        ("family code not mapped to its 228 parent", lambda: setattr(B, "for_codes", fap341_codes), (b3,)),
        ("fragility never flagged", lambda: setattr(B, "FRAGILE_POINTS", 1e9), (b3,)),
        ("masking bound ignored", lambda: setattr(B, "MASK_MAX", 0), (b3,)),
    ]
    for name, apply, fns in data_mutants:
        if not rebuilt(apply, fns):
            missed.append(name)
    n = len(UI_MUTANTS) + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, source: Path | None = None) -> list[dict]:
    c = Ctx(db, real, source)
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
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
