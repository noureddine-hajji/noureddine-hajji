"""Red team of sprint 15 (first part): exposure of a job's tasks to generative AI (ILO 2025) and France Travail's tag.

    python scripts/redteam_ia.py [--db data/suptracker.duckdb] [--real]

  I1 the ILO file re-read independently (openpyxl): stored published mean, sd and gradient per ISCO code; task means
     re-derived from the tasks match the published (2-decimal) means except a known upstream list; the 4 exposed
     gradients are ordered bands of the published means
  I2 France Travail tags re-read: stored values equal, only Oui / Non / not assessed
  I3 serving: a job's codes are exactly the 4-digit ISCO codes of its official codes (sprint 13); published values;
     range = min / max over scored codes (no average anywhere); codes without an ILO note listed; main codes first
  I4 coverage of jobs with a usable ROME code
  I5 page (card run with Node on hostile data): escaped, "pas une prévision de pertes d'emplois", "transformé que
     remplacé", no average, CC BY credit, two decimals, unscored codes said, no alarming words
  I6 upkeep: register online, methodology and feature, release wiring, warehouse under 95 MB
  I7 mutation test
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

from suptracker import ia_exposition as IA  # noqa: E402
from suptracker import metiers as MT  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
KNOWN_UPSTREAM = {"7126"}           # published mean 0.18, its 5 tasks average 0.1515: an inconsistency of the ILO file


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def raw_ilo(path: Path) -> dict:
    import openpyxl
    rows = list(openpyxl.load_workbook(str(path), read_only=True, data_only=True).active.iter_rows(values_only=True))
    h = list(rows[0])
    ix = {k: h.index(k) for k in ("ISCO_08", "score_2025", "mean_score_2025", "SD_2025", "potential25")}
    out = {}
    for r in rows[1:]:
        if r[ix["ISCO_08"]] is None:
            continue
        code = str(r[ix["ISCO_08"]]).strip().zfill(4)
        e = out.setdefault(code, {"tasks": [], "mean": r[ix["mean_score_2025"]], "sd": r[ix["SD_2025"]], "grad": r[ix["potential25"]]})
        v = r[ix["score_2025"]]
        if isinstance(v, (int, float)):
            e["tasks"].append(float(v))
    return out


def raw_tags(path: Path) -> dict:
    import openpyxl
    ws = openpyxl.load_workbook(str(path), read_only=True, data_only=True)["Tag des fiches ROME"]
    rows = list(ws.iter_rows(values_only=True))
    h = list(rows[0])
    ic, it = h.index("Code ROME"), h.index("Transition Numérique")
    return {str(r[ic]).strip(): (str(r[it]).strip() if r[it] not in (None, "") else None) for r in rows[1:]
            if r[ic] and re.fullmatch(r"[A-N]\d{4}", str(r[ic]).strip())}


class Ctx:
    def __init__(self, db: Path, real: bool, srcs: dict | None = None):
        self.db, self.real = db, real
        self.src = srcs or IA.sources()
        self.con = duckdb.connect(str(db), read_only=True)
        self.ilo, self.tags = raw_ilo(self.src["ilo"]), raw_tags(self.src["tags"])
        self.rows = {r[0]: r for r in self.con.execute("SELECT * FROM core.ia_oit_isco").fetchall()}
        self.stored_tags = dict(self.con.execute("SELECT rome, transition_numerique FROM core.ia_rome_tag").fetchall())


def close(a, b, tol=1e-9):
    return (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) <= tol)


@check("I1 ILO file re-read: published mean / sd / gradient stored; task means match the published means; gradients are ordered bands")
def i1(c: Ctx):
    bad = [k for k, e in c.ilo.items() if k not in c.rows or not close(c.rows[k][2], e["mean"]) or not close(c.rows[k][3], e["sd"])
           or c.rows[k][4] != e["grad"] or c.rows[k][6] != len(e["tasks"])]
    extra = sorted(set(c.rows) - set(c.ilo))
    off = {k for k, e in c.ilo.items() if e["tasks"] and abs(sum(e["tasks"]) / len(e["tasks"]) - float(e["mean"])) > 0.005 + 1e-9}
    bands = {}
    for e in c.ilo.values():
        if str(e["grad"]).startswith("Exposed: Gradient"):
            bands.setdefault(int(str(e["grad"])[-1]), []).append(float(e["mean"]))
    ordered = all(max(bands[g]) < min(bands[g + 1]) for g in (1, 2, 3)) if len(bands) == 4 else False
    ok = not bad and not extra and off == KNOWN_UPSTREAM and ordered and len(c.ilo) >= 400
    return ok, (f"{len(c.ilo)} ISCO codes, stored differ {bad[:3]}, extra {extra[:3]}; task means off the published means {sorted(off)} "
                f"(known {sorted(KNOWN_UPSTREAM)}); exposed gradients ordered bands {ordered}")


@check("I2 France Travail tags re-read: stored values equal; only Oui / Non / not assessed")
def i2(c: Ctx):
    bad = [k for k, v in c.tags.items() if c.stored_tags.get(k, "missing") != (v if v in ("Oui", "Non") else None)]
    vals = set(c.stored_tags.values()) - {"Oui", "Non", None}
    ok = not bad and not vals and len(c.tags) >= 1500
    return ok, f"{len(c.tags)} ROME sheets, differ {bad[:3]}; unexpected values {vals}"


@check("I3 serving: the job's 4-digit ISCO codes, published values, min / max range, no average, unscored codes listed, main codes first")
def i3(c: Ctx):
    jobs = [m for (m,) in c.con.execute("SELECT met_id FROM core.onisep_metier ORDER BY 1").fetchall()]
    sample = jobs if not c.real else jobs[:: max(1, len(jobs) // 200)]
    bad, n = [], 0
    for mid in sample:
        d = MT.detail(c.con, mid)
        ia = d["ia"]
        exp = {i["code"] for x in d["codes"] for i in x.get("isco", []) if i["precision"] == 4}
        got = {i["code"]: i for i in (ia or {}).get("isco", [])}
        if set(got) != exp:
            bad.append(f"{mid}: codes {sorted(got)} != {sorted(exp)}")
            continue
        if not got:
            continue
        n += 1
        for code, i in got.items():
            r = c.rows.get(code)
            if (r is None) != (i["score"] is None) or (r and (not close(i["score"], r[2]) or i["gradient"] != r[4])):
                bad.append(f"{mid} {code}: values")
        sc = [i["score"] for i in got.values() if i["score"] is not None]
        if (ia["min"], ia["max"]) != ((min(sc), max(sc)) if sc else (None, None)):
            bad.append(f"{mid}: range")
        if any(k in ia for k in ("moyenne", "mean", "average")) or set(ia["sans_score"]) != {k for k, i in got.items() if i["score"] is None}:
            bad.append(f"{mid}: average or unscored list")
        scored = [i for i in ia["isco"] if i["score"] is not None]
        if [i["n_intitules"] for i in scored] != sorted((i["n_intitules"] for i in scored), reverse=True):
            bad.append(f"{mid}: main codes not first")
    ok = not bad and n > 0
    return ok, f"{len(sample)} jobs, {n} with codes, {len(bad)} wrong {bad[:3]}"


@check("I4 coverage: jobs with a usable ROME code get at least one ILO note")
def i4(c: Ctx):
    jobs = [m for (m,) in c.con.execute("""SELECT DISTINCT met_id FROM core.onisep_metier_rome
                                           WHERE rome IN (SELECT rome FROM core.nomen_rome) ORDER BY 1""").fetchall()]
    cov = sum(bool((MT.detail(c.con, m)["ia"] or {}).get("min") is not None) for m in jobs)
    rate = cov / len(jobs) if jobs else 0
    return (rate >= 0.9 or not c.real), f"{cov}/{len(jobs)} jobs with an ILO note ({rate:.1%})"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 15: l'IA générative et les tâches du métier")
    return js[i: js.index("\n// ---- ", i + 1)]


HOSTILE = {"min": 0.43, "max": 0.6, "sans_score": ["0210"], "tags": [{"rome": "<b>M1805</b>", "transition_numerique": "Oui"},
                                                                    {"rome": "J1506", "transition_numerique": None}],
           "isco": [{"code": "<script>2512</script>", "libelle": "<img src=x onerror=alert(1)>", "n_intitules": 20, "score": 0.53,
                     "gradient": "Exposed: Gradient 3"},
                    {"code": "2513", "libelle": "Concepteurs", "n_intitules": 8, "score": 0.6, "gradient": "Exposed: Gradient 4"},
                    {"code": "0210", "libelle": "<svg onload=alert(2)>", "n_intitules": 1, "score": None, "gradient": None}]}


def render(js: str):
    node = shutil.which("node")
    if not node:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    prog = helpers + "\n" + block(js) + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(P.map(iaCard)));"
    r = subprocess.run([node, "-e", prog], input=json.dumps([HOSTILE, None, {"isco": [], "tags": []}]), capture_output=True, text=True, timeout=60)
    return ("__error__" + r.stderr[-300:]) if r.returncode else r.stdout


def ui(js: str) -> tuple[bool, str]:
    out = render(js)
    wired = "${iaCard(d.ia)}" in js
    if out is None:
        return wired, "node not installed"
    if out.startswith("__error__"):
        return False, out
    html, none, empty = json.loads(out)
    leaks = re.findall(r"<(?:script|img|svg|b)\b", html)
    words = all(w in html for w in ("pas une prévision de pertes d'emplois", "transformé que remplacé", "on ne fait pas la moyenne",
                                     "CC BY 4.0", "pas de note OIT", "0,60", "0,53", "de 0,43 à 0,60", "exposé, gradient 4 sur 4",
                                     "liée à la transition numérique", "non renseignée pour la transition numérique",
                                     "complémentarité humaine (méthode du FMI) n'est pas encore affichée"))
    banned = [w for w in ("chance", "risque élevé", "menacé", "disparaîtr", "probabilit", "moyenne de ce métier") if w in html.lower()]
    ok = wired and not leaks and words and not banned and none == "" and empty == ""
    return ok, f"raw tags {leaks[:3]}; wording and figures {words}; banned {banned}; wired {wired}"


@check("I5 page (card run with Node on hostile data): escaped, wording, two decimals, unscored codes, no alarming words")
def i5(c: Ctx):
    return ui(APP_JS.read_text())


@check("I6 upkeep: register online, methodology and feature, warehouse under 95 MB")
def i6(c: Ctx):
    from suptracker import sources as SRC
    from suptracker.api import FEATURES, METHODOLOGY
    st = {s["key"]: s["status"] for s in SRC.SOURCES}
    m = METHODOLOGY.get("ia_exposition", "")
    size = c.db.stat().st_size / 1e6
    ok = st.get("oit_genai") == "en_ligne" and st.get("rome_tags") == "en_ligne" and "ia_exposition" in FEATURES \
        and "pas une prévision de pertes d'emplois" in m and "jamais une moyenne" in m and (size < 95 or not c.real)
    return ok, f"register {st.get('oit_genai')}/{st.get('rome_tags')}; feature and methodology {'ia_exposition' in FEATURES and bool(m)}; warehouse {size:.1f} MB"


UI_MUTANTS = [
    ("unescaped label", "${esc(i.libelle || \"\")}<div class=\"muted small\">", "${i.libelle || \"\"}<div class=\"muted small\">"),
    ("unescaped ROME", "fiche ROME ${esc(t.rome)}", "fiche ROME ${t.rome}"),
    ("one decimal", "minimumFractionDigits: 2, maximumFractionDigits: 2", "maximumFractionDigits: 1"),
    ("range replaced by an average", "va de ${score(ia.min)} à ${score(ia.max)} sur 1", "est en moyenne de ${score((ia.min + ia.max) / 2)} sur 1"),
    ("job-loss caveat dropped", "pas une prévision de pertes d'emplois ni un risque pour toi", "un risque pour ton avenir"),
    ("unscored code hidden", "'<span class=\"muted\">pas de note OIT</span>'", "\"\""),
    ("gradient label raw English", "esc(IA_GRADIENT[i.gradient] || i.gradient)", "esc(i.gradient)"),
]


@check("I7 mutation test: year, published vs re-computed, gradients, partial codes, tags column, range and page bugs are each caught")
def i7(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 15: l'IA générative et les tâches du métier")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        if old not in js[i:j] or ui(js[:i] + js[i:j].replace(old, new, 1) + js[j:])[0]:
            missed.append(name)

    def rebuilt(apply, fns):
        import tempfile
        saved = {k: getattr(IA, k) for k in ("read_ilo", "read_tags", "for_codes", "GRADIENTS")}
        tmp = Path(tempfile.gettempdir()) / f"ia_mutant_{c.db.stem}.duckdb"
        try:
            apply()
            shutil.copy(c.db, tmp)
            con = duckdb.connect(str(tmp))
            IA.build(con, c.src)
            con.close()
            m = Ctx.__new__(Ctx)
            m.__dict__.update({k: v for k, v in c.__dict__.items() if k not in ("con", "rows", "stored_tags")})
            m.db, m.con = tmp, duckdb.connect(str(tmp), read_only=True)
            m.rows = {r[0]: r for r in m.con.execute("SELECT * FROM core.ia_oit_isco").fetchall()}
            m.stored_tags = dict(m.con.execute("SELECT rome, transition_numerique FROM core.ia_rome_tag").fetchall())
            caught = any(not fn(m)[0] for fn in fns)
            m.con.close()
            return caught
        except Exception:  # noqa: BLE001
            return True
        finally:
            for k, v in saved.items():
                setattr(IA, k, v)
            tmp.unlink(missing_ok=True)

    orig_read, orig_tags, orig_for = IA.read_ilo, IA.read_tags, IA.for_codes

    def recomputed(path):
        g = orig_read(path)
        g["moyenne"] = g["moyenne_taches"].round(2)       # re-computed means served instead of the published ones
        return g

    def year_2023(path):
        import pandas as pd
        g = orig_read(path)
        d = pd.read_excel(path, dtype={"ISCO_08": str})
        m = d.assign(isco=d["ISCO_08"].str.zfill(4)).groupby("isco")["mean_score_2023"].first()
        g["moyenne"] = g["isco"].map(pd.to_numeric(m, errors="coerce"))
        return g

    def shifted_gradient(path):
        g = orig_read(path)
        g["gradient"] = g["gradient"].replace({"Exposed: Gradient 3": "Exposed: Gradient 4"})
        return g

    def ecological_tag(path):
        import pandas as pd
        t = pd.read_excel(path, sheet_name="Tag des fiches ROME", dtype=str)
        t = t[t["Code ROME"].fillna("").str.fullmatch(r"[A-N]\d{4}")]
        v = t["Transition Ecologique"].fillna("").str.strip()
        return pd.DataFrame({"rome": t["Code ROME"], "transition_numerique": v.where(v.isin(["Oui", "Non"]), None)})

    def with_partial(con, codes):
        import copy
        cc = copy.deepcopy(codes)
        for x in cc:
            for i in x.get("isco", []):
                i["precision"] = 4                          # partial codes (21xx) treated as unit groups
        return orig_for(con, cc)

    def averaged(con, codes):
        out = orig_for(con, codes)
        if out and out["min"] is not None:
            sc = [i["score"] for i in out["isco"] if i["score"] is not None]
            out["min"] = out["max"] = sum(sc) / len(sc)
        return out

    data_mutants = [
        ("re-computed means served", lambda: setattr(IA, "read_ilo", recomputed), (i1,)),
        ("2023 scores served as 2025", lambda: setattr(IA, "read_ilo", year_2023), (i1,)),
        ("gradient 3 shown as 4", lambda: setattr(IA, "read_ilo", shifted_gradient), (i1,)),
        ("ecological tag read as the digital one", lambda: setattr(IA, "read_tags", ecological_tag), (i2,)),
        ("partial ISCO codes served", lambda: setattr(IA, "for_codes", with_partial), (i3,)),
        ("range collapsed to an average", lambda: setattr(IA, "for_codes", averaged), (i3,)),
    ]
    for name, apply, fns in data_mutants:
        if not rebuilt(apply, fns):
            missed.append(name)
    n = len(UI_MUTANTS) + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, srcs: dict | None = None) -> list[dict]:
    c = Ctx(db, real, srcs)
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
