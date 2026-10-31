"""Red team of A2 (offer timing) and A4 (offer options: internat, apprentissage, distance, sport / art).

Each check attacks one promise: the data is decoded faithfully, the numbers cannot be misread,
the search filters return exactly what they announce, and nothing breaks or leaks.

    python scripts/redteam_offer.py --db data/suptracker.duckdb [--real]

--real adds the plausibility thresholds that only make sense on the full SIES warehouse.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import search as S  # noqa: E402

CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()


# ------------------------------------------------------------------ data fidelity
@check("O1 decoded options stay inside their closed domains")
def o1(con, real):
    bad = one(con, """SELECT count(*) FROM core.formation_year
        WHERE internat NOT IN ('mixte', 'filles', 'garcons', 'oui', 'non')
           OR distance NOT IN ('aucune', 'partielle', 'totale')""")[0]
    return bad == 0, f"{bad} row(s) outside the closed domains"


@check("O2 the SQL decoder and its Python twin agree on every real-world value shape")
def o2(con, real):
    from suptracker.harmonize import carto_flags
    shapes = [
        ("Formations en apprentissage", "Etablissements avec internat pour filles et garçons",
         "Enseignement en présentiel,Formations avec aménagements pour sportifs haut niveau"),
        ("", "Etablissements avec internat pour filles", "Enseignement partiellement à distance"),
        ("", "Etablissements avec internat pour garçons", "Enseignement à distance"),
        ("", "", "Formations avec aménagements pour artistes haut niveau,Enseignement en présentiel"),
        ("", "", ""),
    ]
    mem = duckdb.connect()
    diffs = []
    for app, it, amg in shapes:
        mem.execute("CREATE OR REPLACE TABLE t AS SELECT ? AS app, ? AS int, ? AS amg", [app, it, amg])
        sql_row = mem.execute("""
          WITH f AS (SELECT lower(strip_accents(app)) a, lower(strip_accents(int)) i, lower(strip_accents(amg)) g FROM t)
          SELECT contains(a, 'apprentissage'),
            CASE WHEN NOT contains(i, 'internat') THEN 'non' WHEN contains(i, 'filles') AND contains(i, 'garcons') THEN 'mixte'
                 WHEN contains(i, 'filles') THEN 'filles' WHEN contains(i, 'garcons') THEN 'garcons' ELSE 'oui' END,
            CASE WHEN contains(g, 'partiellement a distance') THEN 'partielle' WHEN contains(g, 'a distance') THEN 'totale'
                 ELSE 'aucune' END, contains(g, 'sportif'), contains(g, 'artiste') FROM f""").fetchone()
        py = carto_flags(app, it, amg)
        py_row = (py["apprentissage"], py["internat"], py["distance"], py["amenag_sport"], py["amenag_art"])
        if tuple(sql_row) != py_row:
            diffs.append((app, it, amg, sql_row, py_row))
    return not diffs, f"{len(diffs)} disagreement(s) {diffs[:1]}" if diffs else f"{len(shapes)} shapes identical"


@check("O3 the decoder in the warehouse is the one tested (same SQL as harmonize.build_cartographie)")
def o3(con, real):
    src = (ROOT / "suptracker" / "harmonize.py").read_text()
    needles = ["contains(int_raw, 'filles') AND contains(int_raw, 'garcons') THEN 'mixte'",
               "contains(amg_raw, 'partiellement a distance') THEN 'partielle'",
               "contains(amg_raw, 'a distance') THEN 'totale'"]
    missing = [n for n in needles if n not in src]
    return not missing, f"decoder drifted from the red-team copy: {missing}" if missing else "in sync"


@check("O4 offer timing is cumulative and bounded (opening <= before bac <= end of main phase <= 100)")
def o4(con, real):
    n, bad = one(con, """SELECT count(*) FILTER (WHERE pct_acc_debutpp IS NOT NULL),
        count(*) FILTER (WHERE pct_acc_debutpp > pct_acc_datebac OR pct_acc_datebac > pct_acc_finpp
                         OR pct_acc_debutpp < 0 OR pct_acc_finpp > 100)
        FROM core.formation_year""")
    share = 100 * bad / n if n else 0
    return share <= 0.5, f"{bad}/{n} rows non-monotonic or out of bounds ({share:.2f} %, tolerance 0.5 % for SIES rounding)"


@check("O5 published shares match the published counts (no field swapped or misaligned)")
def o5(con, real):
    n, ok_tot, ok_pp = one(con, """SELECT count(*),
        count(*) FILTER (WHERE abs(pct_acc_debutpp - 100.0 * acc_debutpp / acc_tot) <= 1
                           AND abs(pct_acc_datebac - 100.0 * acc_datebac / acc_tot) <= 1
                           AND abs(pct_acc_finpp - 100.0 * acc_finpp / acc_tot) <= 1),
        count(*) FILTER (WHERE acc_pp > 0 AND abs(pct_acc_debutpp - 100.0 * acc_debutpp / acc_pp) <= 1
                           AND abs(pct_acc_finpp - 100.0 * acc_finpp / acc_pp) <= 1)
        FROM core.formation_year WHERE acc_tot > 0 AND pct_acc_debutpp IS NOT NULL""")
    best = max(ok_tot, ok_pp)
    den = "acc_tot (all admits)" if ok_tot >= ok_pp else "acc_pp (main-phase admits)"
    return (n == 0 or best / n >= 0.95), f"{best}/{n} rows consistent with denominator {den}"


@check("O6 the latest cartographie listing wins, and every formation keeps one value per attribute")
def o6(con, real):
    multi = one(con, """SELECT count(*) FROM (SELECT cod_aff_form FROM core.cartographie GROUP BY 1 HAVING count(*) > 1)""")[0]
    drift = one(con, """SELECT count(*) FROM (SELECT cod_aff_form FROM core.formation_year
        GROUP BY 1 HAVING count(DISTINCT internat) > 1 OR count(DISTINCT distance) > 1)""")[0]
    return multi == 0 and drift == 0, f"{multi} duplicated cartographie ids, {drift} formations with varying offer attributes"


@check("O7 coverage: the latest campaign is matched to the cartographie")
def o7(con, real):
    n, hit = one(con, """SELECT count(*), count(carto_session) FROM core.formation_year
                         WHERE session = (SELECT max(session) FROM core.formation_year)""")
    share = 100 * hit / n if n else 0
    return (share >= 85 if real else True), f"{hit}/{n} formations of the latest campaign matched ({share:.1f} %)"


@check("O8 plausibility: apprenticeship labels agree with the cartographie; internat is a CPGE feature")
def o8(con, real):
    lab, agree = one(con, """SELECT count(*), count(*) FILTER (WHERE apprentissage)
        FROM core.formation_year WHERE lib_for_voe_ins ILIKE '%apprentissage%'""")
    cpge, lic = one(con, """SELECT
        avg(CASE WHEN internat IN ('mixte','filles','garcons','oui') THEN 1.0 ELSE 0 END) FILTER (WHERE fili = 'CPGE' AND carto_session IS NOT NULL),
        avg(CASE WHEN internat IN ('mixte','filles','garcons','oui') THEN 1.0 ELSE 0 END) FILTER (WHERE fili = 'Licence' AND carto_session IS NOT NULL)
        FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""")
    ok = agree == lab and (not real or (cpge or 0) > (lic or 0) + 0.2)
    return ok, f"apprenticeship label → flag {agree}/{lab}; internat CPGE {100 * (cpge or 0):.0f} % vs licence {100 * (lic or 0):.0f} %"


@check("O9 admits housed at the internat imply an internat (upstream inconsistencies stay rare)")
def o9(con, real):
    n, bad = one(con, """SELECT count(*) FILTER (WHERE acc_internat > 0 AND carto_session IS NOT NULL),
        count(*) FILTER (WHERE acc_internat > 0 AND internat = 'non')
        FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)""")
    share = 100 * bad / n if n else 0
    return share <= 5, f"{bad}/{n} formations with internat admits but no internat listed ({share:.1f} %, tolerance 5 %)"


# ------------------------------------------------------------------ search filters
QUERIES = ["bts", "licence droit", "cpge", "mpsi", "but informatique", "ecole ingenieur", "lyon", "paris"]


@check("O10 option facets are exact: each count is what a click on it returns")
def o10(con, real):
    bad = []
    for q in QUERIES:
        r = S.search(con, q, limit=1)
        acad = next((a["value"] for a in r["facets"].get("academie", [])), None)
        # with nothing else active, with an académie active, and with another option active
        for ctx in ({}, {"academie": acad}, {"options": ("sport",)}):
            rr = S.search(con, q, limit=1, **ctx)
            for f in rr["facets"].get("options", []):
                opts = tuple(dict.fromkeys((*ctx.get("options", ()), f["value"])))
                got = S.search(con, q, limit=1, **{**ctx, "options": opts})["total"]
                if got != f["count"]:
                    bad.append((q, ctx, f["value"], f["count"], got))
    return not bad, f"{len(bad)} mismatch(es) {bad[:2]}" if bad else f"{len(QUERIES)} queries × 3 filter contexts × {len(S.OPTIONS)} options exact"


@check("O11 options are conjunctive filters: they never reorder results, and combine as AND")
def o11(con, real):
    bad = []
    for q in QUERIES:
        base = [x["cod_aff_form"] for x in S.search(con, q, limit=10_000)["results"]]
        a = [x["cod_aff_form"] for x in S.search(con, q, options=("internat",), limit=10_000)["results"]]
        ab = [x["cod_aff_form"] for x in S.search(con, q, options=("internat", "distance"), limit=10_000)["results"]]
        keep = set(a)
        if a != [c for c in base if c in keep] or not set(ab) <= set(a):
            bad.append(q)
    return not bad, f"order or AND broken for {bad}" if bad else "filtered lists are ordered subsequences"


@check("O12 unknown or hostile options are refused (no silent widening, no injection)")
def o12(con, real):
    out = []
    for opts in (("handicap",), ("internat' OR 1=1 --",), ("<script>",), ("",)):
        try:
            S.search(con, "bts", options=opts)
            out.append(("accepted", opts))
        except ValueError:
            pass
    return not out, f"accepted {out}" if out else "4 hostile option sets refused"


@check("O13 a warehouse built before these columns existed still serves search (NULL options)")
def o13(con, real):
    path = one(con, "SELECT path FROM duckdb_databases() WHERE database_name = current_database()")[0]
    tmp = Path(tempfile.mkdtemp()) / "old.duckdb"
    shutil.copy(path, tmp)
    c = duckdb.connect(str(tmp))
    for col in ("apprentissage", "internat", "distance", "amenag_sport", "amenag_art", "carto_session"):
        c.execute(f"ALTER TABLE core.formation_year DROP COLUMN IF EXISTS {col}")
    c.close()
    c = duckdb.connect(str(tmp), read_only=True)
    try:
        r = S.search(c, "bts", limit=3)
        ok = r["total"] > 0 and all(f["count"] == 0 for f in r["facets"]["options"])
    finally:
        c.close()
        S._CACHE.clear()
    return ok, "search works; every option count is 0"


@check("O17 no misleading filter: every offered option is substantial, apprenticeship is not offered")
def o17(con, real):
    n, = one(con, "SELECT count(*) FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)")
    tests = {"internat": "internat IN ('mixte','filles','garcons','oui')", "distance": "distance IN ('partielle','totale')",
             "sport": "amenag_sport", "art": "amenag_art"}
    small = {o: c for o, w in tests.items() if o in S.OPTIONS
             for c in [one(con, f"SELECT count(*) FROM core.formation_year WHERE {w} AND session = "
                                "(SELECT max(session) FROM core.formation_year)")[0]] if real and c < 0.01 * n}
    sies, carto = one(con, """SELECT (SELECT count(*) FROM core.formation_year WHERE apprentissage AND session =
                                       (SELECT max(session) FROM core.formation_year)),
                                     (SELECT count(*) FROM core.cartographie WHERE apprentissage)""")
    appr_offered = "apprentissage" in S.OPTIONS
    ok = not small and not (appr_offered and carto and sies < 0.1 * carto)
    return ok, (f"options under 1 % of formations: {small}; apprenticeship in SIES stats {sies} vs cartographie "
                f"{carto} → {'offered (misleading!)' if appr_offered else 'not offered'}")


@check("O18 student phrasing: 'avec internat' becomes the filter; apprenticeship queries are told why")
def o18(con, real):
    a = S.search(con, "prepa avec internat lyon", limit=200)
    b = S.search(con, "internat", limit=1)
    c = S.search(con, "bts alternance", limit=1)
    ok = all(r["internat"] in ("mixte", "filles", "garcons", "oui") for r in a["results"])
    ok &= {"type": "option", "value": "internat"} in a["interpretation"]
    # independent ground truth: SQL on the latest row of every lineage (what the index holds)
    truth = one(con, """SELECT count(*) FROM (SELECT fy.internat FROM core.formation_year fy
        JOIN core.lineage l USING (session, cod_aff_form)
        QUALIFY row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) = 1)
        WHERE internat IN ('mixte', 'filles', 'garcons', 'oui')""")[0]
    ok &= b["total"] == truth
    ok &= S.APPRENTICESHIP_NOTE in c["notes"]
    return ok, f"'prepa avec internat lyon' {a['total']} results all with internat; 'internat' {b['total']} (SQL {truth}); apprenticeship note"


# ------------------------------------------------------------------ presentation
@check("O14 the UI never prints a raw cartographie string or an unescaped field")
def o14(con, real):
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    raw = re.findall(r"\$\{r\.(internat|distance|apprentissage|amenag_sport|amenag_art)\}", js)
    # a chart series `name:` is data, escaped where it is rendered (legend(), <title>): not an HTML sink
    unesc = [m for ln in js.splitlines() if "name: `" not in ln
             for m in re.findall(r"\$\{(?!esc\()[^${}`]*\.(?:fil_lib_voe_acc|g_ea_lib_vx|ville_etab)\b[^${}`]*\}", ln)]
    sinks = "${esc(k.name)}" in js and "${esc(s.name)}" in js
    return not raw and not unesc and sinks, f"raw {raw}, unescaped {unesc[:2]}" if raw or unesc else "enum labels only, text escaped"


@check("O15 the timing card cannot be read as a chance of admission")
def o15(con, real):
    from suptracker.api import METHODOLOGY
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    t = METHODOLOGY.get("timing", "")
    ok = "pas des chances" in t.replace("non des chances", "pas des chances") or "non des chances" in t
    ok &= "cumulées" in t and "des admis" in js and "low_n_flag" in js[js.index("function timingCard"):]
    return ok, "methodology says shares of admits, cumulative; low-n warning wired"


@check("O16 the disability claim is not made: the data has no disability field, the UI says so")
def o16(con, real):
    from suptracker.api import METHODOLOGY
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    claims = re.findall(r"handicap", js, re.I)
    return not claims and "handicap ne figurent pas" in METHODOLOGY["offer"], \
        f"{len(claims)} disability claim(s) in the UI" if claims else "no claim; methodology points to the référent handicap"


@check("O19 empty cohorts say nothing: zero-admit rows never draw a timing card, row or comparator cell")
def o19(con, real):
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    card = js[js.index("function timingCard"):js.index("function timingCard") + 900]
    ok = "acc_tot > 0" in card.split("const later")[0] and "h.acc_tot > 0" in card
    ok &= "f.record.acc_tot > 0 ? pct(f.record.pct_acc_debutpp)" in js
    n, = one(con, "SELECT count(*) FROM core.formation_year WHERE acc_tot = 0 AND pct_acc_debutpp IS NOT NULL")
    return ok, f"guards present; {n} zero-admit rows carry published timing shares and are suppressed"


@check("O20 every surface that shows options receives them (fiche, search results, comparator)")
def o20(con, real):
    from fastapi.testclient import TestClient
    path = one(con, "SELECT path FROM duckdb_databases() WHERE database_name = current_database()")[0]
    cod, = one(con, """SELECT cod_aff_form FROM core.formation_year WHERE internat IN ('mixte','filles','garcons','oui')
                       ORDER BY session DESC, cod_aff_form LIMIT 1""") or (None,)
    if cod is None:
        return False, "no formation with an internat in this warehouse"
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(path)
    from suptracker import api
    api._con.cache_clear()
    try:
        c = TestClient(api.app)
        fiche = c.get(f"/api/formation/{cod}").json()["record"]
        comp = c.get("/api/compare", params={"ids": cod}).json()["formations"][0]["record"]
        res = c.get("/api/search", params={"q": cod}).json()["results"][0]
    finally:
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()
    keys = ("internat", "distance", "amenag_sport", "amenag_art", "apprentissage")
    missing = {name: [k for k in keys if k not in rec] for name, rec in
               (("fiche", fiche), ("comparator", comp), ("search", res)) if any(k not in rec for k in keys)}
    same = fiche["internat"] == comp.get("internat")
    return not missing and same, f"missing {missing}" if missing else f"formation {cod}: internat '{comp['internat']}' everywhere"


def run(db: Path, real: bool = False) -> list[dict]:
    os.environ.setdefault("SUPTRACKER_ANALYTICS", "off")
    S._CACHE.clear()
    con = duckdb.connect(str(db), read_only=True)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(con, real)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    con.close()
    S._CACHE.clear()
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
