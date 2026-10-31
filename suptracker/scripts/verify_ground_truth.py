"""Ground-truth verification of the warehouse against SIES accounting identities.

Checks, for every campaign 2022–2025:
  1. series identity   acc_bg + acc_bt + acc_bp            == acc_neobac
  2. mention identity  sansmention + ab + b + tb + tbf + nr == acc_neobac
     plus  series + acc_at == acc_tot. The same sums against acc_term are kept as
     diagnostics: on the real 2022–2025 exports SIES uses acc_neobac (néo-bacheliers)
     as the denominator of both breakdowns, not acc_term.
     Every identity is evaluated on the warehouse AND on the raw upstream file.
     Rows that violate it identically in both are an inconsistency inside the SIES
     export itself ("upstream_inconsistency": reported, flagged in the UI, not a
     pipeline failure); any other difference is a pipeline "fail".
  3. taux_acces_ens fidelity: warehouse value == value in the raw upstream Parquet,
     re-read independently with pyarrow (no DuckDB transform), and optionally
     == the live SIES records API for a random sample (--live N)
  4. bounds: SIES shares within [0, 100]
  5. structure: unique (session, cod_aff_form), every row in exactly one lineage
Then writes the longitudinal continuity report (% of 2025 formations linked back).

Rows where a component is NULL are counted as "not evaluable", never as passes.

    python scripts/verify_ground_truth.py --db data/suptracker.duckdb --raw-dir data/raw \
        [--out data/verification/] [--live 25] [--strict]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suptracker import config  # noqa: E402
from suptracker.crosswalk import continuity_report  # noqa: E402
from suptracker.schema import FIELD_BY_NAME, MENTION_FIELDS, SERIES_FIELDS, VOEUX_FIELDS, resolve  # noqa: E402

IDENTITIES = [
    # name, components, total, primary?
    ("series_eq_acc_neobac", SERIES_FIELDS, "acc_neobac", True),
    ("mentions_eq_acc_neobac", MENTION_FIELDS, "acc_neobac", True),
    ("series_plus_at_eq_acc_tot", (*SERIES_FIELDS, "acc_at"), "acc_tot", True),
    ("series_eq_acc_term", SERIES_FIELDS, "acc_term", False),
    ("mentions_eq_acc_term", MENTION_FIELDS, "acc_term", False),
]
SHARES = [f.name for f in VOEUX_FIELDS if f.dtype == "DOUBLE" and f.stage == "indicator"]


def raw_violators(raw_dir: Path, year: int, comps, total) -> dict[str, float] | None:
    """{cod_aff_form: sum(components) - total} for rows violating the identity in the raw
    upstream file (no warehouse involved)."""
    path = raw_dir / f"parcoursup_{year}.parquet"
    if not path.exists():
        return None
    fields = tuple(FIELD_BY_NAME[c] for c in ("cod_aff_form", *comps, total))
    m = resolve(fields, pq.ParquetFile(path).schema_arrow.names)
    if any(m[f.name] is None for f in fields):
        return None
    num = lambda c: f"TRY_CAST(REPLACE(CAST(\"{m[c]}\" AS VARCHAR), ',', '.') AS DOUBLE)"  # noqa: E731
    s = " + ".join(num(c) for c in comps)
    nn = " AND ".join(f"{num(c)} IS NOT NULL" for c in (*comps, total))
    key = f"regexp_replace(CAST(\"{m['cod_aff_form']}\" AS VARCHAR), '\\.0$', '')"
    rows = duckdb.sql(f"""SELECT {key}, ({s}) - {num(total)} FROM read_parquet('{path}')
                          WHERE {nn} AND ({s}) <> {num(total)}""").fetchall()
    return {k: float(d) for k, d in rows}


def check_identities(con, raw_dir: Path) -> list[dict]:
    out = []
    for name, comps, total, primary in IDENTITIES:
        s = " + ".join(comps)
        nn = " AND ".join(f"{c} IS NOT NULL" for c in (*comps, total))
        for r in con.execute(f"""
            SELECT session, count(*) AS n_rows,
              count(*) FILTER (WHERE {nn}) AS n_evaluable,
              max(abs(({s}) - {total})) FILTER (WHERE {nn}) AS max_abs_diff,
              list({{'k': cod_aff_form, 'd': ({s}) - {total}}} ORDER BY abs(({s}) - {total}) DESC)
                FILTER (WHERE {nn} AND ({s}) <> {total}) AS violators
            FROM core.formation_year GROUP BY session ORDER BY session""").fetchall():
            session, n, ev, mad, viol = r
            diffs = {v["k"]: float(v["d"]) for v in (viol or [])}
            viol = list(diffs)
            upstream = raw_violators(raw_dir, session, comps, total)
            if not ev:
                status = "not_evaluable"
            elif upstream is None:
                status = "pass" if not diffs else "fail"
            elif diffs != upstream:
                status = "fail"   # the warehouse does not reproduce the upstream discrepancies row by row
            elif not diffs:
                status = "pass"
            else:
                status = "upstream_inconsistency"   # same rows, same discrepancy as the SIES export
            out.append({"check": name, "primary": primary, "session": session, "n_rows": n,
                        "n_evaluable": ev, "n_violations": len(viol),
                        "n_violations_upstream": None if upstream is None else len(upstream),
                        "max_abs_diff": mad,
                        "pct_ok": round(100 * (ev - len(viol)) / ev, 2) if ev else None,
                        "status": status, "sample_violators": viol[:5]})
    return out


def _to_float(v):
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        return None
    return None if math.isnan(f) else f


def check_taux_raw(con, raw_dir: Path) -> list[dict]:
    """Independent pyarrow re-read of the raw upstream file vs the warehouse."""
    out = []
    want = (FIELD_BY_NAME["cod_aff_form"], FIELD_BY_NAME["taux_acces_ens"])
    for year in config.YEARS:
        path = raw_dir / f"parcoursup_{year}.parquet"
        if not path.exists():
            out.append({"session": year, "status": "not_evaluable", "reason": "raw file missing"})
            continue
        cols = pq.ParquetFile(path).schema_arrow.names
        m = resolve(want, cols)
        if not m["taux_acces_ens"]:
            out.append({"session": year, "status": "not_evaluable", "reason": "taux_acces_ens absent upstream"})
            continue
        t = pq.read_table(path, columns=[m["cod_aff_form"], m["taux_acces_ens"]]).to_pydict()
        raw = {}
        for k, v in zip(t[m["cod_aff_form"]], t[m["taux_acces_ens"]]):
            if k is None:
                continue
            key = str(k)
            raw[key[:-2] if key.endswith(".0") else key] = _to_float(v)
        wh = dict(con.execute("SELECT cod_aff_form, taux_acces_ens FROM core.formation_year WHERE session = ?",
                              [year]).fetchall())
        mism = [k for k in raw if k in wh and not _same(raw[k], wh[k])]
        out.append({"session": year, "n_upstream": len(raw), "n_warehouse": len(wh),
                    "n_missing_in_warehouse": len(set(raw) - set(wh)),
                    "n_mismatch": len(mism), "sample_mismatch": mism[:5],
                    "status": "pass" if not mism and set(raw) <= set(wh) else "fail"})
    return out


def _same(a, b) -> bool:
    if a is None or b is None or (isinstance(b, float) and math.isnan(b)):
        return (a is None) == (b is None or (isinstance(b, float) and math.isnan(b)))
    return abs(a - b) < 1e-9


def check_taux_live(con, n: int, seed: int = 0) -> list[dict]:
    import httpx

    out = []
    rng = random.Random(seed)
    ids = {d.year: d.ods_ids[0] for d in config.DATASETS if d.kind == "voeux"}
    for year in config.YEARS:
        keys = [r[0] for r in con.execute(
            "SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND taux_acces_ens IS NOT NULL",
            [year]).fetchall()]
        sample = rng.sample(keys, min(n, len(keys)))
        mism, errors = [], 0
        for k in sample:
            try:
                r = httpx.get(config.records_url(ids[year]), timeout=30, params={
                    "select": "cod_aff_form,taux_acces_ens", "where": f'cod_aff_form="{k}"', "limit": 1})
                r.raise_for_status()
                res = r.json().get("results", [])
            except Exception:  # noqa: BLE001 - network errors are reported, not hidden
                errors += 1
                continue
            up = _to_float(res[0].get("taux_acces_ens")) if res else None
            wh = con.execute("SELECT taux_acces_ens FROM core.formation_year WHERE session=? AND cod_aff_form=?",
                             [year, k]).fetchone()[0]
            if not res or not _same(up, wh):
                mism.append(k)
        out.append({"session": year, "n_sampled": len(sample), "n_errors": errors, "n_mismatch": len(mism),
                    "sample_mismatch": mism[:5],
                    "status": "not_evaluable" if errors == len(sample) else ("pass" if not mism and not errors
                                                                             else "fail")})
    return out


def check_bounds(con) -> list[dict]:
    out = []
    for c in SHARES:
        n = con.execute(f"SELECT count(*) FROM core.formation_year WHERE {c} < 0 OR {c} > 100").fetchone()[0]
        out.append({"field": c, "n_out_of_bounds": n, "status": "pass" if n == 0 else "fail"})
    return out


def check_structure(con) -> list[dict]:
    dup = con.execute("""SELECT count(*) FROM (SELECT session, cod_aff_form FROM core.formation_year
                         GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    orphan = con.execute("""SELECT count(*) FROM core.formation_year fy ANTI JOIN core.lineage l
                            USING (session, cod_aff_form)""").fetchone()[0]
    multi = con.execute("""SELECT count(*) FROM (SELECT session, cod_aff_form FROM core.lineage
                           GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    one2one = con.execute("""SELECT count(*) FROM (SELECT session_to, cod_aff_form_to FROM core.crosswalk_link
                             GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    return [{"check": "unique_session_cod_aff_form", "violations": dup},
            {"check": "every_row_in_a_lineage", "violations": orphan},
            {"check": "row_in_single_lineage", "violations": multi},
            {"check": "links_one_to_one", "violations": one2one}]


def check_timing(con) -> list[dict]:
    """Offer timing (acc_debutpp <= acc_datebac <= acc_finpp, cumulative) and which denominator the
    published shares use. Diagnostic: the app shows the published pct_acc_* as they are."""
    out = []
    for (session,) in con.execute("SELECT DISTINCT session FROM core.formation_year ORDER BY 1").fetchall():
        r = con.execute("""
          SELECT count(*) FILTER (WHERE acc_debutpp IS NOT NULL AND acc_datebac IS NOT NULL AND acc_finpp IS NOT NULL),
            count(*) FILTER (WHERE acc_debutpp > acc_datebac OR acc_datebac > acc_finpp),
            count(*) FILTER (WHERE acc_finpp > acc_tot),
            count(*) FILTER (WHERE pct_acc_debutpp > pct_acc_datebac OR pct_acc_datebac > pct_acc_finpp),
            count(*) FILTER (WHERE acc_tot > 0 AND pct_acc_debutpp IS NOT NULL),
            count(*) FILTER (WHERE acc_tot > 0 AND abs(pct_acc_debutpp - 100.0 * acc_debutpp / acc_tot) <= 1
                                               AND abs(pct_acc_finpp - 100.0 * acc_finpp / acc_tot) <= 1),
            count(*) FILTER (WHERE acc_pp > 0 AND abs(pct_acc_debutpp - 100.0 * acc_debutpp / acc_pp) <= 1
                                              AND abs(pct_acc_finpp - 100.0 * acc_finpp / acc_pp) <= 1),
            count(*) FILTER (WHERE acc_finpp = acc_pp), count(*) FILTER (WHERE acc_finpp = acc_tot),
            count(*) FILTER (WHERE acc_tot > 0 AND acc_pp > 0)
          FROM core.formation_year WHERE session = ?""", [session]).fetchone()
        n, nonmono, over, pct_nonmono, n_pct, den_tot, den_pp, eq_pp, eq_tot, n_both = r
        out.append({"session": session, "n_evaluable": n, "non_monotonic": nonmono, "finpp_gt_acc_tot": over,
                    "pct_non_monotonic": pct_nonmono, "n_pct": n_pct,
                    "pct_match_acc_tot": round(100 * den_tot / n_pct, 1) if n_pct else None,
                    "pct_match_acc_pp": round(100 * den_pp / n_pct, 1) if n_pct else None,
                    "finpp_eq_acc_pp": eq_pp, "finpp_eq_acc_tot": eq_tot, "n_with_admits": n_both,
                    "status": "n/a" if not n else "pass" if not (nonmono or over or pct_nonmono) else "upstream"})
    return out


def check_offer_attributes(con) -> list[dict]:
    """Coverage of the cartographie offer attributes on the latest campaign (diagnostic)."""
    return [dict(zip(("session", "n", "with_carto", "apprentissage", "internat", "distance", "sport", "art"), r))
            for r in con.execute("""
      SELECT session, count(*), count(carto_session), count(*) FILTER (WHERE apprentissage),
             count(*) FILTER (WHERE internat NOT IN ('non')), count(*) FILTER (WHERE distance IN ('partielle', 'totale')),
             count(*) FILTER (WHERE amenag_sport), count(*) FILTER (WHERE amenag_art)
      FROM core.formation_year GROUP BY 1 ORDER BY 1""").fetchall()]


def render_md(rep: dict) -> str:
    L = [f"# SIES ground-truth verification — {rep['generated_at']}", ""]
    L += ["## Accounting identities", "",
          "| check | primary | session | evaluable | violations | same rows in raw SIES file | % ok | max abs diff | status |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["identities"]:
        L.append(f"| {r['check']} | {'yes' if r['primary'] else 'diag'} | {r['session']} | {r['n_evaluable']} | "
                 f"{r['n_violations']} | {r['n_violations_upstream']} | {r['pct_ok']} | {r['max_abs_diff']} | {r['status']} |")
    L += ["", "## taux_acces_ens fidelity (warehouse vs raw upstream Parquet)", "",
          "| session | upstream rows | mismatches | missing in warehouse | status |", "|---|---|---|---|---|"]
    for r in rep["taux_raw"]:
        L.append(f"| {r['session']} | {r.get('n_upstream', '')} | {r.get('n_mismatch', '')} | "
                 f"{r.get('n_missing_in_warehouse', '')} | {r['status']} {r.get('reason', '')} |")
    if rep.get("taux_live"):
        L += ["", "## taux_acces_ens vs live SIES records API (random sample)", "",
              "| session | sampled | errors | mismatches | status |", "|---|---|---|---|---|"]
        for r in rep["taux_live"]:
            L.append(f"| {r['session']} | {r['n_sampled']} | {r['n_errors']} | {r['n_mismatch']} | {r['status']} |")
    bad = [b for b in rep["bounds"] if b["status"] != "pass"]
    L += ["", "## Bounds", "", "All SIES shares within [0, 100]." if not bad else
          "\n".join(f"- {b['field']}: {b['n_out_of_bounds']} out of bounds" for b in bad)]
    if rep.get("timing"):
        L += ["", "## Offer timing (diagnostic)", "",
              "| session | evaluable | non-monotonic counts | acc_finpp > acc_tot | non-monotonic shares | "
              "shares = count / acc_tot (%) | shares = count / acc_pp (%) | acc_finpp = acc_pp | acc_finpp = acc_tot | status |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for t in rep["timing"]:
            L.append(f"| {t['session']} | {t['n_evaluable']} | {t['non_monotonic']} | {t['finpp_gt_acc_tot']} | "
                     f"{t['pct_non_monotonic']} | {t['pct_match_acc_tot']} | {t['pct_match_acc_pp']} | "
                     f"{t['finpp_eq_acc_pp']} | {t['finpp_eq_acc_tot']} | {t['status']} |")
    if rep.get("offer"):
        L += ["", "## Offer attributes from the cartographie (diagnostic)", "",
              "| session | formations | with cartographie | apprentissage | internat | distance | sport HN | art HN |",
              "|---|---|---|---|---|---|---|---|"]
        L += [f"| {o['session']} | {o['n']} | {o['with_carto']} | {o['apprentissage']} | {o['internat']} | "
              f"{o['distance']} | {o['sport']} | {o['art']} |" for o in rep["offer"]]
    L += ["", "## Structure", ""] + [f"- {s['check']}: {s['violations']} violation(s)" for s in rep["structure"]]
    c = rep["continuity"]
    if c:
        cols = list(c[0])
        L += ["", f"## Longitudinal continuity — share of {config.LATEST_YEAR} formations linked back", "",
              "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        L += ["| " + " | ".join(str(r[k]) for k in cols) + " |" for r in c]
    L += ["", f"**Overall: {rep['overall']}**", ""]
    return "\n".join(L)


def run(db: Path, raw_dir: Path, live: int = 0) -> dict:
    con = duckdb.connect(str(db), read_only=True)
    ident = check_identities(con, raw_dir)
    raw = check_taux_raw(con, raw_dir)
    lv = check_taux_live(con, live) if live else []
    bounds = check_bounds(con)
    struct = check_structure(con)
    cont = continuity_report(con)
    timing, offer = check_timing(con), check_offer_attributes(con)
    failed = ([r for r in ident if r["primary"] and r["status"] == "fail"]
              + [r for r in raw + lv if r["status"] == "fail"]
              + [b for b in bounds if b["status"] == "fail"] + [s for s in struct if s["violations"]])
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "identities": ident, "taux_raw": raw, "taux_live": lv, "bounds": bounds, "structure": struct,
            "timing": timing, "offer": offer, "continuity": cont, "overall": "FAIL" if failed else "PASS", "n_failed_checks": len(failed)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    ap.add_argument("--out", type=Path, default=config.DB_PATH.parent / "verification",
                    help="report directory; /api/verification reads <warehouse dir>/verification")
    ap.add_argument("--live", type=int, default=0, help="sample size per year for the live API check")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any primary check fails")
    a = ap.parse_args(argv)
    rep = run(a.db, a.raw_dir, a.live)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "verification.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str))
    md = render_md(rep)
    (a.out / "verification.md").write_text(md)
    print(md)
    return 1 if a.strict and rep["overall"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
