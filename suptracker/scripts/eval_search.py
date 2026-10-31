"""Search quality evaluation on the real warehouse: gold set + baseline comparison.

Each gold query carries a predicate over the *formation* (not a fixed id), so the set
survives yearly data refreshes. A query passes when at least 4 of the top 5 results satisfy
its predicate, or, when fewer than 5 formations in the whole warehouse satisfy it, when all
of them are ranked first ("relevant first").

    python scripts/eval_search.py --db data/suptracker.duckdb [--baseline] [--out data/verification]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suptracker import config  # noqa: E402


def f(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def has(field, *words):
    """Predicate: every word (folded) appears in the given formation field."""
    return lambda r: all(f(w) in f(r[field]) for w in words)


def any_of(*preds):
    return lambda r: any(p(r) for p in preds)


def all_of(*preds):
    return lambda r: all(p(r) for p in preds)


def fili(*names):
    return lambda r: r["fili"] in names


def loc(*words):
    """Formation located in a place: town, département, académie or region."""
    return lambda r: any(all(f(w) in f(r[k]) for w in words)
                         for k in ("ville_etab", "dep_lib", "acad_mies", "region_etab_aff"))


ECG = has("fil_lib_voe_acc", "ECG")
SCPO = has("fil_lib_voe_acc", "Sciences Po")
HEALTH = fili("PASS", "Licence_Las")

GOLD: list[tuple[str, object]] = [
    # acronyms & student slang
    ("sciences po", SCPO),
    ("sciences po lille", all_of(SCPO, loc("Lille"))),
    ("iep", SCPO),
    ("prépa HEC", ECG),
    ("prepa hec paris", all_of(ECG, loc("Paris"))),
    ("BTS NDRC", has("fil_lib_voe_acc", "Négociation et digitalisation")),
    ("bts ndrc lyon", all_of(has("fil_lib_voe_acc", "Négociation et digitalisation"), loc("Lyon"))),
    ("BTS MCO", has("fil_lib_voe_acc", "Management commercial opérationnel")),
    ("BTS SIO", has("fil_lib_voe_acc", "Services informatiques aux organisations")),
    ("BUT GEA", has("fil_lib_voe_acc", "Gestion des entreprises et des administrations")),
    ("BUT TC Nantes", all_of(has("fil_lib_voe_acc", "Techniques de commercialisation"), loc("Nantes"))),
    ("IUT informatique Toulouse", all_of(fili("BUT"), has("fil_lib_voe_acc", "Informatique"), loc("Toulouse"))),
    ("but mmi", has("fil_lib_voe_acc", "Métiers du multimédia")),
    ("MPSI", has("fil_lib_voe_acc", "MPSI")),
    ("mpsi henri iv", all_of(has("fil_lib_voe_acc", "MPSI"), has("g_ea_lib_vx", "Henri IV"))),
    ("hypokhâgne", has("form_lib_voe_acc", "littéraire")),
    ("khagne lyon", all_of(has("form_lib_voe_acc", "littéraire"), loc("Lyon"))),
    ("école ingénieur post bac", fili("Ecole d'Ingénieur")),
    ("ecole d'ingé bordeaux", all_of(fili("Ecole d'Ingénieur"), loc("Bordeaux"))),
    ("école de commerce post bac", fili("Ecole de Commerce")),
    ("PASS", fili("PASS")),
    ("LAS", fili("Licence_Las")),
    ("MIASHS", has("fil_lib_voe_acc", "Mathématiques et informatique appliquées")),
    ("AES", has("fil_lib_voe_acc", "Administration économique et sociale")),
    ("LEA", has("fil_lib_voe_acc", "Langues étrangères appliquées")),
    ("DN MADE", has("form_lib_voe_acc", "DN MADE")),
    ("DCG", has("form_lib_voe_acc", "DCG")),
    # professions reached through another programme
    ("médecine", HEALTH),
    ("medecine lyon", all_of(HEALTH, loc("Lyon"))),
    ("kiné", any_of(HEALTH, has("fil_lib_voe_acc", "Activités Physiques et Sportives"))),
    ("sage femme", HEALTH),
    ("infirmier", fili("IFSI")),
    ("infirmière bordeaux", all_of(fili("IFSI"), loc("Bordeaux"))),
    ("orthophonie", has("fil_lib_voe_acc", "Orthophoniste")),
    ("vétérinaire", has("form_lib_voe_acc", "vétérinaires")),
    ("architecture", has("fil_lib_voe_acc", "Architecture")),
    # plain discipline + place, typos, morphology
    ("droit", all_of(fili("Licence"), has("fil_lib_voe_acc", "Droit"))),
    ("droit sorbonne", all_of(has("fil_lib_voe_acc", "Droit"), has("g_ea_lib_vx", "Sorbonne"))),
    ("psycho lyon", all_of(has("fil_lib_voe_acc", "Psychologie"), loc("Lyon"))),
    ("psycologie", has("fil_lib_voe_acc", "Psychologie")),
    ("medcine", HEALTH),
    ("informatique", has("fil_lib_voe_acc", "Informatique")),
    ("STAPS Paris", all_of(has("fil_lib_voe_acc", "Activités Physiques et Sportives"), loc("Paris"))),
    ("licence economie gestion", has("fil_lib_voe_acc", "Economie et gestion")),
    ("st etienne", loc("Saint", "Etienne")),
    ("aix en provence droit", all_of(has("fil_lib_voe_acc", "Droit"), loc("Aix"))),
]


def legacy_search(con, q: str, limit: int = 40) -> list[str]:
    """The search shipped until Sprint 1 (substring AND, alphabetical), for the baseline."""
    toks = [t for t in f(q).split() if t]
    if not toks:
        return []
    where = " AND ".join(["fy.search_text LIKE ?"] * len(toks))
    rows = con.execute(f"""
      SELECT cod_aff_form FROM (
        SELECT fy.cod_aff_form, fy.session, fy.g_ea_lib_vx, fy.fil_lib_voe_acc,
          row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) AS rn
        FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
        WHERE l.lineage_id IN (SELECT l2.lineage_id FROM core.formation_year fy
                               JOIN core.lineage l2 USING (session, cod_aff_form) WHERE {where}))
      WHERE rn = 1 ORDER BY session DESC, g_ea_lib_vx, fil_lib_voe_acc LIMIT ?""",
        [f"%{t}%" for t in toks] + [limit]).fetchall()
    return [r[0] for r in rows]


def new_search(con, q: str, limit: int = 40) -> list[str]:
    from suptracker import search as S
    return [r["cod_aff_form"] for r in S.search(con, q, limit=limit)["results"]]


def evaluate(con, engine, k: int = 5) -> dict:
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    cols = ["cod_aff_form", "session", "fili", "form_lib_voe_acc", "fil_lib_voe_acc", "g_ea_lib_vx",
            "ville_etab", "dep_lib", "acad_mies", "region_etab_aff"]

    def row(cod):
        r = con.execute(f"""SELECT {', '.join(cols)} FROM core.formation_year WHERE cod_aff_form = ?
                            ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
        return dict(zip(cols, r))

    latest_rows = [dict(zip(cols, r)) for r in con.execute(f"""
        SELECT {', '.join(cols)} FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
        QUALIFY row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) = 1""").fetchall()]
    out, lat = [], []
    for q, pred in GOLD:
        t0 = time.perf_counter()
        ids = engine(con, q)
        lat.append(1000 * (time.perf_counter() - t0))
        top = [row(c) for c in ids[:k]]
        good = sum(bool(pred(r)) for r in top)
        # relevant results first: >= 4 of the top 5, or, when fewer than 5 relevant formations exist
        # in the whole warehouse, all of them at the top
        n_rel = sum(bool(pred(r)) for r in latest_rows)
        need = 4 if n_rel >= 5 else n_rel
        ok = bool(top) and n_rel > 0 and good >= min(need, len(top))
        out.append({"query": q, "returned": len(ids), "top_ok": good, "top_n": len(top), "pass": ok,
                    "top": [f"{r['g_ea_lib_vx']} | {r['fil_lib_voe_acc']} | {r['ville_etab']}" for r in top[:3]]})
    return {"latest": latest, "queries": out,
            "pass_rate": round(100 * sum(o["pass"] for o in out) / len(out), 1),
            "zero_results": sum(o["returned"] == 0 for o in out),
            "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(sorted(lat)[int(0.95 * len(lat)) - 1], 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--baseline", action="store_true", help="evaluate the pre-Sprint-1 search instead")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--min-pass", type=float, default=0.0, help="exit 1 below this pass rate (%%)")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    con = duckdb.connect(str(a.db), read_only=True)
    rep = evaluate(con, legacy_search if a.baseline else new_search)
    for o in rep["queries"]:
        if a.v or not o["pass"]:
            print(("PASS " if o["pass"] else "FAIL ") + f"{o['query']!r:32} {o['top_ok']}/{o['top_n']} "
                  f"(n={o['returned']})  " + " || ".join(o["top"]))
    print(f"pass rate {rep['pass_rate']} %  zero-result queries {rep['zero_results']}/{len(GOLD)}  "
          f"latency p50 {rep['p50_ms']} ms  p95 {rep['p95_ms']} ms")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "search_eval.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    return 1 if rep["pass_rate"] < a.min_pass else 0


if __name__ == "__main__":
    sys.exit(main())
