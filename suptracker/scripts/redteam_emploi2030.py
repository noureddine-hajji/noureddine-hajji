"""Red team of sprint 14, employment to 2030 (Dares / France Stratégie, "Les métiers en 2030").

    python scripts/redteam_emploi2030.py [--db data/suptracker.duckdb] [--real]

  E1 the stored families equal the workbook re-read independently (pandas, header-free): every published value, and
     the published identities hold: creations + departures = positions, positions - entrants = imbalance, table B =
     table A / 2019 employment
  E2 calculated groups: each = its domain minus its published families on every column (re-derived), flagged
     calculated; craftsmen (K0Z) get no figure; no other family is invented
  E3 serving: a job's families are exactly the 87-groups of its FAP-2009 codes (sprint 13), mapped to their group when
     unpublished; values equal the table; the range is the min/max of the 5 published scenarios; the reading follows
     the fixed sign rule; several families when the family depends on the qualification
  E4 coverage: share of jobs with a usable ROME code that get at least one family with figures (>= 90 % on real data)
  E5 page (the card run with Node on hostile data): escaped, "ni une prévision ni une promesse", no figure for 2035,
     no "chance" / "probabilité", the three readings, calculated groups flagged, thousands rounded, signs shown
  E6 upkeep: source online in the register, methodology and feature, wiring, warehouse under 95 MB
  E7 mutation test
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
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import emploi2030 as E  # noqa: E402
from suptracker import metiers as MT  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
NUM = ["emploi_2019", "creations", "departs", "postes", "debutants", "deseq_ref", "deseq_precrise", "deseq_covid",
       "deseq_bas_carbone", "deseq_covid_bas_carbone", "mobilites"]
SCEN = NUM[5:10]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def raw(path: Path):
    """(families, domains) re-read with pandas: families {code: (label, values)}, domains {letter: values}."""
    a = pd.read_excel(path, sheet_name="Annexe 4 -Tableau de synthèse A", header=None)
    b = pd.read_excel(path, sheet_name="Annexe 4 -Tableau de synthèse B", header=None)
    fam, dom, order, cur = {}, {}, {}, None
    for _, r in a.iterrows():
        lab = str(r[1]).strip() if pd.notna(r[1]) else ""
        if "Ensemble du domaine" in lab:
            cur = lab.split("domaine")[1].strip()[0]
            dom[cur] = [float(x) for x in r[4:15]]
        elif re.fullmatch(r"[A-Z]\d[A-Z]", lab):
            fam[lab] = (str(r[2]).strip(), [float(x) for x in r[4:15]])
            order.setdefault(lab[0], []).append(lab)       # a family's domain is its first letter (FAP nomenclature)
        elif lab:
            cur = None
    shares = {str(r[1]).strip(): [float(x) for x in r[5:15]] for _, r in b.iterrows()
              if pd.notna(r[1]) and re.fullmatch(r"[A-Z]\d[A-Z]", str(r[1]).strip())}
    return fam, dom, order, shares


class Ctx:
    def __init__(self, db: Path, real: bool, source: Path | None = None):
        self.db, self.real = db, real
        self.src = source or E.source_path()
        self.con = duckdb.connect(str(db), read_only=True)
        self.fam, self.dom, self.order, self.shares = raw(self.src)
        cols = [d[0] for d in self.con.execute("SELECT * FROM core.m2030_famille LIMIT 0").description]
        self.rows = {r[0]: dict(zip(cols, r)) for r in self.con.execute("SELECT * FROM core.m2030_famille").fetchall()}


def close(a, b, tol=1e-6):
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol * max(1, abs(b)))


@check("E1 stored families = the workbook re-read independently; published identities hold")
def e1(c: Ctx):
    bad, ident = [], []
    for code, (lab, v) in c.fam.items():
        r = c.rows.get(code)
        if not r or r["libelle"] != lab or r["calcule"] or not all(close(r[n], x) for n, x in zip(NUM, v)) \
                or not all(close(r[f"part_{n}"], s) for n, s in zip(NUM[1:], c.shares[code])):
            bad.append(code)
        if abs(v[1] + v[2] - v[3]) > 1e-6 or abs(v[3] - v[4] - v[5]) > 1e-6 or any(abs(x / v[0] - s) > 1e-9 for x, s in zip(v[1:], c.shares[code])):
            ident.append(code)
    ok = not bad and not ident and len(c.fam) >= 75
    return ok, f"{len(c.fam)} published families, stored values differ {bad[:4]}; identities broken in the workbook {ident[:4]}"


@check("E2 calculated groups = domain minus published families on every column; K0Z gets no figure; nothing invented")
def e2(c: Ctx):
    bad = []
    for letter, codes in E.GROUPS.items():
        key = "+".join(codes)
        exp = [c.dom[letter][i] - sum(c.fam[f][1][i] for f in c.order.get(letter, [])) for i in range(len(NUM))]
        r = c.rows.get(key)
        if not r or not r["calcule"] or not all(close(r[n], x, 1e-6) for n, x in zip(NUM, exp)) \
                or any(abs(exp[1] + exp[2] - exp[3]) > 1e-6 for _ in [0]) or abs(exp[3] - exp[4] - exp[5]) > 1e-6:
            bad.append(key)
        if any(f in c.fam for f in codes):
            bad.append(f"{key}: a member is published")
    extra = sorted(set(c.rows) - set(c.fam) - {"+".join(x) for x in E.GROUPS.values()})
    k0z = "K0Z" not in c.rows and "K0Z" in E.ABSENT
    ok = not bad and not extra and k0z
    return ok, f"groups wrong {bad}; families not in the workbook {extra}; craftsmen without a figure {k0z}"


def expected(c: Ctx, codes):
    group_of = {m: "+".join(g) for g in E.GROUPS.values() for m in g}
    return {group_of.get(f["fap87"], f["fap87"]) for x in codes for f in x.get("fap2009", [])}


@check("E3 serving: a job's families = its FAP-2009 87-groups, values, scenario range, reading rule, qualification")
def e3(c: Ctx):
    bad, n = [], 0
    jobs = [m for (m,) in c.con.execute("SELECT DISTINCT met_id FROM core.onisep_metier ORDER BY 1").fetchall()]
    sample = jobs if not c.real else jobs[:: max(1, len(jobs) // 200)]
    for mid in sample:
        d = MT.detail(c.con, mid)
        got = {f["fap87"]: f for f in d["emploi2030"]}
        if set(got) != expected(c, d["codes"]):
            bad.append(f"{mid}: families {sorted(got)} != {sorted(expected(c, d['codes']))}")
            continue
        for key, f in got.items():
            n += 1
            if f["absent"]:
                if key in c.rows:
                    bad.append(f"{mid} {key}: figure withheld")
                continue
            r = c.rows[key]
            sc = [r[s] for s in SCEN]
            lo, hi = min(sc), max(sc)
            rule = "debutants_insuffisants" if lo > 0 else "debutants_nombreux" if hi < 0 else "incertain"
            if not all(close(f["milliers"][k], r[k]) for k in NUM) or not close(f["desequilibre"]["min"], lo) \
                    or not close(f["desequilibre"]["max"], hi) or not close(f["desequilibre"]["reference"], r["deseq_ref"]) \
                    or f["lecture"] != rule or f["calcule"] != r["calcule"]:
                bad.append(f"{mid} {key}: values, range or reading")
    ok = not bad and n > 0
    return ok, f"{len(sample)} jobs, {n} job families checked, {len(bad)} wrong {bad[:3]}"


@check("E4 coverage: jobs with a usable ROME code get at least one family with figures")
def e4(c: Ctx):
    jobs = [m for (m,) in c.con.execute("""SELECT DISTINCT met_id FROM core.onisep_metier_rome
                                           WHERE rome IN (SELECT rome FROM core.nomen_rome) ORDER BY 1""").fetchall()]
    covered = sum(any(not f["absent"] for f in MT.detail(c.con, m)["emploi2030"]) for m in jobs)
    rate = covered / len(jobs) if jobs else 0
    ok = rate >= 0.9 or not c.real
    return ok, f"{covered}/{len(jobs)} jobs with figures ({rate:.1%})"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 14: l'emploi du métier d'ici 2030")
    return js[i: js.index("\n// ---- ", i + 1)]


HOSTILE = [
    {"fap87": "<b>A0Z</b>", "libelle": "<script>alert(1)</script>", "absent": False, "calcule": False, "origine": ["onisep"],
     "toutes_qualifications": False, "milliers": {"emploi_2019": 450.0, "postes": 158.2, "departs": 181.7, "creations": -23.4, "debutants": 92.6},
     "parts": {"postes": 0.3517}, "desequilibre": {"reference": 65.6, "min": 62.9, "max": 80.0}, "lecture": "debutants_insuffisants"},
    {"fap87": "D0Z+D3Z", "libelle": "<img src=x onerror=alert(2)>", "absent": False, "calcule": True, "origine": ["intitule_dares"],
     "toutes_qualifications": True, "milliers": {"emploi_2019": 208.0, "postes": 58.6, "departs": 53.4, "creations": 5.2, "debutants": 56.3},
     "parts": {"postes": 0.28}, "desequilibre": {"reference": 2.3, "min": -0.2, "max": 4.0}, "lecture": "incertain"},
    {"fap87": "R1Z", "libelle": "Vendeurs", "absent": False, "calcule": False, "origine": ["onisep"], "toutes_qualifications": True,
     "milliers": {"emploi_2019": 866.0, "postes": 165.0, "departs": 167.0, "creations": -2.0, "debutants": 347.0},
     "parts": {"postes": 0.19}, "desequilibre": {"reference": -182.0, "min": -195.0, "max": -179.0}, "lecture": "debutants_nombreux"},
    {"fap87": "K0Z", "absent": True, "raison": "<svg onload=alert(3)>", "origine": ["onisep"]},
]


def render(js: str):
    node = shutil.which("node")
    if not node:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    prog = helpers + "\n" + block(js) + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(P.map(emploi2030Card)));"
    r = subprocess.run([node, "-e", prog], input=json.dumps([HOSTILE, [], None]), capture_output=True, text=True, timeout=60)
    return ("__error__" + r.stderr[-300:]) if r.returncode else r.stdout


def ui(js: str) -> tuple[bool, str]:
    b = block(js)
    out = render(js)
    if out is None:
        return "${emploi2030Card(d.emploi2030)}" in js, "node not installed"
    if out.startswith("__error__"):
        return False, out
    html, empty, none = json.loads(out)
    html = html.replace("\u202f", " ").replace("\u00a0", " ")        # fr-FR thousands separators
    leaks = re.findall(r"<(?:script|img|svg|b)\b", html)
    words = all(w in html for w in ("ni une prévision ni une promesse", "pas de chiffre pour 2035", "de toute la famille",
                                     "ne suffiraient pas", "plus de jeunes débutants que de postes", "on ne peut pas conclure",
                                     "chiffres calculés", "Les métiers en 2030", "moins sûr", "158 000", "−23 000", "+66 000",
                                     "de +63 000 à +80 000", "selon la qualification du poste"))
    banned = [w for w in ("chance", "probabilit", "garanti") if w in html.lower()]
    ok = not leaks and words and not banned and empty == "" and none == "" and "${emploi2030Card(d.emploi2030)}" in js
    return ok, f"raw tags {leaks[:3]}; wording and figures {words}; banned words {banned}; empty lists render nothing {empty == '' and none == ''}"


@check("E5 page (card run with Node on hostile data): escaped, wording, readings, no 2035 figure, rounding and signs")
def e5(c: Ctx):
    return ui(APP_JS.read_text())


@check("E6 upkeep: source online, methodology and feature, release wiring, warehouse under 95 MB")
def e6(c: Ctx):
    from suptracker import sources as SRC
    from suptracker.api import FEATURES, METHODOLOGY
    s = next(x for x in SRC.SOURCES if x["key"] == "metiers_2030")
    m = METHODOLOGY.get("emploi_2030", "")
    ok = (s["status"] == "en_ligne" and "emploi_2030" in FEATURES and "pas de chiffre pour 2035" in m and "pas une prévision" in m
          and (c.db.stat().st_size / 1e6 < 95 or not c.real))
    return ok, f"register {s['status']}; feature and methodology {'emploi_2030' in FEATURES and bool(m)}; warehouse {c.db.stat().st_size / 1e6:.1f} MB"


UI_MUTANTS = [
    ("unescaped family label", "${esc(f.libelle || \"\")}</h3>", "${f.libelle || \"\"}</h3>"),
    ("unescaped reason", "Pas de chiffre : ${esc(f.raison || \"\")}", "Pas de chiffre : ${f.raison || \"\"}"),
    ("sign dropped", "return signed ? `${k < 0 ? \"−\" : \"+\"}${v}`", "return signed ? `${v}`"),
    ("thousands not rounded", "fmt(Math.round(Math.abs(k)) * 1000)", "fmt(Math.abs(k) * 1000)"),
    ("range shows the reference twice", "de ${kPeople(d.min, true)} à ${kPeople(d.max, true)}", "de ${kPeople(d.reference, true)} à ${kPeople(d.reference, true)}"),
    ("calculated group not flagged", "${f.calcule ? `<p class=\"small warn\">", "${false ? `<p class=\"small warn\">"),
    ("no 2035 notice", "pas de chiffre pour 2035.", "."),
    ("promise wording", "ni une prévision ni une promesse", "une prévision fiable"),
]


@check("E7 mutation test: reader, groups, mapping, range, reading and page bugs are each caught")
def e7(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 14: l'emploi du métier d'ici 2030")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        if old not in js[i:j] or ui(js[:i] + js[i:j].replace(old, new, 1) + js[j:])[0]:
            missed.append(name)

    def rebuilt(apply, fns):
        import tempfile
        saved = {k: getattr(E, k) for k in ("read_workbook", "for_codes", "reading", "GROUPS", "ABSENT")}
        tmp = Path(tempfile.gettempdir()) / f"m2030_mutant_{c.db.stem}.duckdb"
        try:
            apply()
            shutil.copy(c.db, tmp)
            con = duckdb.connect(str(tmp))
            E.build(con, c.src)
            con.close()
            m = Ctx.__new__(Ctx)
            m.__dict__.update({k: v for k, v in c.__dict__.items() if k not in ("con", "rows")})
            m.db, m.con = tmp, duckdb.connect(str(tmp), read_only=True)
            cols = [d[0] for d in m.con.execute("SELECT * FROM core.m2030_famille LIMIT 0").description]
            m.rows = {r[0]: dict(zip(cols, r)) for r in m.con.execute("SELECT * FROM core.m2030_famille").fetchall()}
            caught = any(not fn(m)[0] for fn in fns)
            m.con.close()
            return caught
        except Exception:  # noqa: BLE001
            return True
        finally:
            for k, v in saved.items():
                setattr(E, k, v)
            tmp.unlink(missing_ok=True)

    orig_read, orig_for, orig_reading = E.read_workbook, E.for_codes, E.reading

    def shifted(path):
        rows = orig_read(path)
        for r in rows:
            r["postes"], r["debutants"] = r["debutants"], r["postes"]      # two columns read in the wrong order
        return rows

    def group_sum(path):
        rows = orig_read(path)
        for r in rows:
            if r["calcule"]:
                r["emploi_2019"] *= 1.1                                     # residual computed on the wrong base
        return rows

    def ref_only(con, codes):
        out = orig_for(con, codes)
        for f in out:
            if not f["absent"]:
                f["desequilibre"]["min"] = f["desequilibre"]["max"] = f["desequilibre"]["reference"]
        return out

    def first_family(con, codes):
        return orig_for(con, codes)[:1]                                    # one family picked for the student

    def no_group_map(con, codes):
        out = orig_for(con, codes)
        return [dict(f, fap87=f["membres"][0], absent=True) if f.get("calcule") else f for f in out]   # member shown, no figure

    data_mutants = [
        ("columns read in the wrong order", lambda: setattr(E, "read_workbook", shifted), (e1,)),
        ("calculated group on a wrong base", lambda: setattr(E, "read_workbook", group_sum), (e2,)),
        ("range = the reference scenario only", lambda: setattr(E, "for_codes", ref_only), (e3,)),
        ("only the first family shown", lambda: setattr(E, "for_codes", first_family), (e3,)),
        ("reading rule on the reference only", lambda: setattr(E, "reading", lambda lo, hi: orig_reading(hi, hi)), (e3,)),
        ("unpublished families not mapped to their group", lambda: setattr(E, "for_codes", no_group_map), (e3,)),
        ("craftsmen given the 'Autres' figure", lambda: setattr(E, "ABSENT", {}), (e2,)),
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
