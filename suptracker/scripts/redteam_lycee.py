"""Red team of sprint 4, the lycée profile: IPS and IVAL of the student's lycée as context, the
académie that follows from it, Maths expertes noted, the same-lycée share of admits (pct_etab_orig)
and privacy (the chosen lycée never reaches the server).

    python scripts/redteam_lycee.py [--db data/suptracker.duckdb] [--real]

The lycée tables are rebuilt in memory from the raw IPS and IVAL tables of the warehouse, and every
rule is re-derived independently. A mutation test seeds bugs and requires each to be caught.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import evidence as E  # noqa: E402
from suptracker import lycee as L  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
ACADEMIE_TRUTH = {"NORMANDIE": "Normandie", "LA REUNION": "La Réunion", "AIX-MARSEILLE": "Aix-Marseille",
                  "CLERMONT-FERRAND": "Clermont-Ferrand", "NOUVELLE CALEDONIE": "Nouvelle-Calédonie",
                  "ORLEANS-TOURS": "Orléans-Tours", "CRETEIL": "Créteil", "NICE": "Nice",
                  "ST PIERRE ET MIQUELON": None, "WALLIS ET FUTUNA": None}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def num(x):
    """Text or number -> float; empty, None and pandas' NaN -> None."""
    try:
        v = float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return None if v is None or v != v else v


class Ctx:
    def __init__(self, db: Path, real: bool):
        import pandas as pd
        self.db, self.real = db, real
        src = duckdb.connect(str(db), read_only=True)
        self.ips = src.execute("SELECT * FROM ref.lycee_ips_raw").df()
        self.ival = src.execute("SELECT * FROM ref.lycee_ival_raw").df()
        self.fy = src.execute("SELECT session, cod_aff_form, cod_uai, acad_mies, pct_etab_orig, fili FROM core.formation_year").df()
        src.close()
        self.pd = pd
        self.rebuild()

    def rebuild(self):
        con = duckdb.connect()
        con.execute("CREATE SCHEMA ref; CREATE SCHEMA core")
        for name, df in (("ref.lycee_ips_raw", self.ips), ("ref.lycee_ival_raw", self.ival), ("core.formation_year", self.fy)):
            con.register("_t", df)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM _t")
            con.unregister("_t")
        self.n = L.build_profile_tables(con)
        self.con = con

    def rows(self, sql, *a):
        cur = self.con.execute(sql, list(a))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@check("Y1 one row per lycée open at the latest school year, values equal to the raw file")
def y1(c: Ctx):
    latest = c.ips.rentree_scolaire.max()
    raw = {r.uai: r for r in c.ips[c.ips.rentree_scolaire == latest].itertuples()}
    got = {r["uai"]: r for r in c.rows("SELECT * FROM ref.lycee")}
    wrong = []
    for u, r in raw.items():
        g = got.get(u)
        if g is None:
            wrong.append((u, "missing"))
            continue
        exp = {"nom": r.nom_de_l_etablissement, "commune": r.nom_de_la_commune, "secteur": r.secteur, "type": r.type_de_lycee,
               "rentree": latest, "ips_etab": num(r.ips_etab), "ips_gt": num(r.ips_voie_gt)}
        diff = [k for k, v in exp.items() if g[k] != v]
        if diff:
            wrong.append((u, diff))
    extra = sorted(set(got) - set(raw))
    return not wrong and not extra and len(got) == len(raw), f"{len(got)} lycées (rentrée {latest}); wrong {wrong[:3]}; not open at the latest year {extra[:3]}"


@check("Y2 the IPS references are those of the lycée's own type and sector, académie and France")
def y2(c: Ctx):
    latest = c.ips.rentree_scolaire.max()
    raw = {r["uai"]: r for r in c.ips[c.ips.rentree_scolaire == latest].to_dict("records")}
    bad = []
    for g in c.rows("SELECT uai, ips_national, ips_academique FROM ref.lycee"):
        r = raw[g["uai"]]
        suffix = f"{r['type_de_lycee'].lower()}_{'public' if r['secteur'] == 'public' else 'prive'}"
        for level in ("national", "academique"):
            want = r.get(f"ips_{level}_{suffix}")
            want = None if want is None or want != want else float(want)
            if g[f"ips_{level}"] != want:
                bad.append((g["uai"], level, g[f"ips_{level}"], want))
    return not bad, f"{len(bad)} wrong references {bad[:3]}"


@check("Y3 the académie comes from the IPS file and maps to a Parcoursup académie (never IVAL's truncated label)")
def y3(c: Ctx):
    psup = set(c.fy.acad_mies.dropna())
    rows = c.rows("SELECT academie_ips, academie FROM ref.lycee")
    bad = [r for r in rows if r["academie"] is not None and r["academie"] not in psup]
    unmapped = sorted({r["academie_ips"] for r in rows if r["academie"] is None})
    truth = {}
    for r in rows:
        truth.setdefault(r["academie_ips"], r["academie"])
    wrong = [(k, v, truth.get(k)) for k, v in ACADEMIE_TRUTH.items() if k in truth and truth[k] != v]
    allowed = set(L.NO_PARCOURSUP_ACADEMIE)
    truncated = sorted({str(a) for a in c.ival.libelle_academie.dropna()} - {str(a) for a in c.ips.academie.dropna()})
    leaked = [r for r in rows if r["academie"] and fold(r["academie"]) in {fold(t) for t in truncated}]
    ok = not bad and not wrong and set(unmapped) <= allowed and not leaked
    return ok, f"not a Parcoursup académie {bad[:2]}; unmapped {unmapped}; truth-table misses {wrong}; IVAL labels absent from IPS {truncated[:4]}; leaked {leaked[:2]}"


@check("Y4 IVAL: the 3 latest bac sessions, values equal to the raw file, negative value added kept")
def y4(c: Ctx):
    ival = c.ival.copy()
    ival["session"] = ival.annee.astype(str).str[:4].astype(int)
    keep = ival[ival.session > ival.session.max() - 3]
    raw = {(r["uai"], r["session"]): r for r in keep.to_dict("records")}
    got = {(r["uai"], r["session"]): r for r in c.rows("SELECT * FROM ref.lycee_ival")}
    wrong = [k for k in raw if k not in got] + [k for k in got if k not in raw]
    for k, g in got.items():
        r = raw.get(k)
        if r is None:
            continue
        for f in L.IVAL_KEYS:
            rv = r[f]
            rv = None if rv is None or rv != rv else float(rv)
            if (g[f] is None) != (rv is None) or (rv is not None and abs(float(g[f]) - rv) > 1e-9):
                wrong.append((k, f))
    neg_raw = int((keep.va_reu_total < 0).sum())
    neg_got = sum(1 for g in got.values() if (g["va_reu_total"] or 0) < 0)
    return not wrong and neg_raw == neg_got, f"{len(got)} lycée-sessions, {len(wrong)} differ {wrong[:3]}; negative value added raw {neg_raw} / kept {neg_got}"


def grade_ref(v):
    if v["taux_reu_total"] is None:
        return None
    if v["presents_total"] is None or v["presents_total"] < 30:
        return "C"
    return "B" if v["presents_total"] < 100 or 2025 - v["session"] > 3 else "A"


@check("Y5 the lycée list is served whole, without parameter, cacheable, with server-side reliability grades")
def y5(c: Ctx):
    import inspect

    from fastapi.testclient import TestClient

    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"], os.environ["SUPTRACKER_ANALYTICS"] = str(c.db), "off"
    api._con.cache_clear()
    try:
        cl = TestClient(api.app)
        r = cl.get("/api/lycees")
        body = r.json()
        size = len(r.content)
    finally:
        os.environ.pop("SUPTRACKER_ANALYTICS", None)
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()
    params = list(inspect.signature(api.lycees).parameters)
    routes = [rt.path for rt in api.app.routes if "lycee" in getattr(rt, "path", "")]
    n_rows = len(body["rows"])
    stored = duckdb.connect(str(c.db), read_only=True).execute("SELECT count(*) FROM ref.lycee").fetchone()[0]
    gi = list(body["ival_fields"]).index("fiabilite")
    bad_grade = 0
    for rows in body["ival"].values():
        for row in rows:
            v = dict(zip(body["ival_fields"], row))
            bad_grade += v["fiabilite"] != grade_ref(v)
    ok = (r.status_code == 200 and not params and routes == ["/api/lycees"] and n_rows == stored and "public" in r.headers.get("cache-control", "")
          and size < 1_500_000 and gi >= 0 and not bad_grade)
    return ok, f"{n_rows} lycées served ({size} bytes), parameters {params}, lycée routes {routes}, grades wrong {bad_grade}, cache {r.headers.get('cache-control')}"


def ui_privacy(js: str) -> tuple[bool, str]:
    calls = re.findall(r"api\(([^)]*)\)", js)
    leaks = [x for x in calls if re.search(r"lycee|lyc\b|uai", x, re.I) and "/api/lycees" not in x]
    tracks = [x for x in re.findall(r"track\(([^)]*)\)", js) if re.search(r"lycee", x, re.I)]
    loads = re.findall(r'api\("/api/lycees[^"]*"\)', js)
    whole = loads == ['api("/api/lycees")']
    return not leaks and not tracks and whole, f"API calls carrying the lycée {leaks[:2]}; tracked {tracks[:2]}; list fetched whole and parameter-free {whole} {loads}"


@check("Y6 privacy: the chosen lycée is never sent to the server nor to the audience measure")
def y6(c: Ctx):
    return ui_privacy(APP_JS.read_text())


@check("Y7 same-lycée share: Mon parcours rows carry the formation's UAI and its official pct_etab_orig")
def y7(c: Ctx):
    from suptracker import journey as J
    src = duckdb.connect(str(c.db), read_only=True)
    types = [t for (t,) in src.execute("""SELECT DISTINCT r.spe_type_key FROM core.taxonomy_link l JOIN core.taxonomy_rule r USING (rule_id)
        WHERE l.session = (SELECT max(session) FROM core.formation_year) AND r.spe_type_key LIKE 'bts%' ORDER BY 1 LIMIT 2""").fetchall()]
    truth = {cod: (uai, pct) for cod, uai, pct in src.execute("""SELECT cod_aff_form, cod_uai, pct_etab_orig FROM core.formation_year
        WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()}
    bad, n = [], 0
    for t in types:
        for f in J.stage2(src, "MATHS+SES", "ab", t)["formations"]:
            n += 1
            if (f.get("cod_uai"), f.get("pct_etab_orig")) != truth[f["cod_aff_form"]]:
                bad.append(f["cod_aff_form"])
    src.close()
    return n > 0 and not bad, f"{n} rows over {types}, {len(bad)} differ {bad[:3]}"


def ui_card(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 4: the student's lycée")
    blk = js[i: js.index("function stage1Matrix", i)] if "function stage1Matrix" in js[i:] else js[i: i + 9000]
    raw = re.findall(r"\$\{(?:l|p\.lycee|r)\.(?:nom|commune|academie|rentree|uai)\}", blk)
    words = all(w in blk for w in ("pas les tiens", "ne modifie pas", "dans ton lycée"))
    promise = re.findall(r"chances? d['’]être admis|tu seras admis|garanti", blk, re.I)
    me = "ne publient pas les options de Terminale" in blk
    badge = re.search(r"p\.lycee && f\.cod_uai === p\.lycee\.uai \?", js) is not None
    here = "p.lycee.uai !== r.cod_uai" in blk
    pick = 'data-lyc="${esc(l.uai)}">${esc(l.nom)}' in js and '${esc(l.commune)}</span></button>' in js
    ok = not raw and words and not promise and me and badge and here and pick
    return ok, f"unescaped {raw[:3]}; context wording {words}; promises {promise}; Maths expertes note {me}; same-lycée badge gated {badge}; fiche note gated {here}; picker escaped {pick}"


@check("Y8 the lycée card escapes what it prints, says it is context, and badges only the student's own lycée")
def y8(c: Ctx):
    return ui_card(APP_JS.read_text())


@check("Y9 methodology and glossary explain IPS, value added and why the lycée does not move the positioning")
def y9(c: Ctx):
    from suptracker import glossary as G
    from suptracker.api import METHODOLOGY
    t = METHODOLOGY.get("lycee", "")
    need = ["ne modifie donc pas", "jamais envoyé", "même type", "valeur ajoutée", "part de ses admis"]
    miss = [w for w in need if w not in t]
    gl = [k for k in ("ips", "va_lycee") if k not in G.GLOSSARY]
    return not miss and not gl, f"methodology missing {miss}; glossary missing {gl}"


# ------------------------------------------------------------------ mutation test
UI_MUTANTS = [
    ("lycée name unescaped", "<strong>${esc(l.nom)}</strong>", "<strong>${l.nom}</strong>", ui_card),
    ("badge on every row", "p.lycee && f.cod_uai === p.lycee.uai ?", "p.lycee ?", ui_card),
    ("context wording dropped", "ne modifie pas", "change", ui_card),
    ("picker name unescaped", 'data-lyc="${esc(l.uai)}">${esc(l.nom)}', 'data-lyc="${esc(l.uai)}">${l.nom}', ui_card),
    ("same-lycée note on every fiche", "p.lycee.uai !== r.cod_uai", "false", ui_card),
    ("lycée sent to the server", 'api("/api/lycees")', 'api(`/api/lycees?uai=${p.lycee && p.lycee.uai}`)', ui_privacy),
]


@check("Y10 mutation test: every seeded data, reference, académie, grade, privacy and UI bug is caught")
def y10(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new, fn in UI_MUTANTS:
        if old not in js or fn(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"build": L.build_profile_tables, "years": L.IVAL_YEARS, "types": dict(L.TYPES), "secteurs": dict(L.SECTEURS),
             "amap": L.academie_map, "solid": E.SOLID_N}

    def oldest_rentree(con):
        n = saved["build"](con)
        con.execute("""CREATE OR REPLACE TABLE ref.lycee AS SELECT l.* REPLACE (r.rentree_scolaire AS rentree,
            TRY_CAST(r.ips_etab AS DOUBLE) AS ips_etab) FROM ref.lycee l JOIN ref.lycee_ips_raw r USING (uai)
            WHERE r.rentree_scolaire = (SELECT min(rentree_scolaire) FROM ref.lycee_ips_raw)""")
        return n

    def ival_academie(con):
        m = saved["amap"](con)
        trunc = dict(con.execute("""SELECT DISTINCT i.academie, v.libelle_academie FROM ref.lycee_ips_raw i JOIN ref.lycee_ival_raw v USING (uai)""").fetchall())
        return {k: trunc.get(k, v) for k, v in m.items()}

    data_mutants = [
        ("an older school year kept", lambda: setattr(L, "build_profile_tables", oldest_rentree), [y1]),
        ("all IVAL history kept", lambda: setattr(L, "IVAL_YEARS", 50), [y4]),
        ("sector ignored in the IPS reference", lambda: setattr(L, "SECTEURS", {"public": "public", "privé sous contrat": "public"}), [y2]),
        ("académie taken from IVAL's truncated label", lambda: setattr(L, "academie_map", ival_academie), [y3]),
        ("reliability threshold lowered", lambda: setattr(E, "SOLID_N", 10), [y5]),
    ]
    for name, apply, checks in data_mutants:
        try:
            apply()
            c.rebuild()
            caught = any(not fn(c)[0] for fn in checks)
        except Exception:  # noqa: BLE001 - a crash is a detection too
            caught = True
        finally:
            L.build_profile_tables, L.IVAL_YEARS, L.academie_map, E.SOLID_N = saved["build"], saved["years"], saved["amap"], saved["solid"]
            L.TYPES, L.SECTEURS = saved["types"], saved["secteurs"]
        if not caught:
            missed.append(name)
    c.rebuild()
    n = len(UI_MUTANTS) + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
