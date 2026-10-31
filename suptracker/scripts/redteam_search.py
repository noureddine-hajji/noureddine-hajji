"""Adversarial (red-team) evaluation of the search engine.

Attacks, each with a hard pass/fail criterion:
  R1  hostile / malformed input never crashes, respects limits, stays fast
  R2  junk words never produce confident results (0 results or flagged partial)
  R3  stop-words alone return nothing (no "everything" dump)
  R4  injection-shaped input is inert (no wildcard / SQL / regex semantics)
  R5  normalisation equivalences (case, accents, hyphens, St/Saint, full-width, zero-width,
      plurals, feminine) give identical top results
  R6  discipline words are never mistaken for places
  R7  filters only narrow (subset), facets are consistent with totals
  R8  pagination is disjoint and stable; results are deterministic
  R9  health professions return access programmes with an explanatory note
  R10 a junk word next to a real one is dropped, flagged and reported
  R11 ranking ignores selectivity (no prestige ordering)
  R12 load: random queries p95 latency, index build time
  R13 output is data only: the query echo is never interpreted as HTML by the UI
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suptracker import config  # noqa: E402
from suptracker import search as S  # noqa: E402

HOSTILE = ["", " ", "\t\n", "a", "é", "%", "_", "%%%", "*", "?", ".*", "\\", "'", '"', "''; DROP TABLE x; --",
           "' OR 1=1 --", "<script>alert(1)</script>", "javascript:alert(1)", "🙂", "🙂🙂 droit 🙂",
           "x" * 5000, "droit " * 400, "\x00", "‮droit", "a" * 300 + " lyon", "../../etc/passwd",
           "${7*7}", "{{7*7}}", "null", "undefined", "NaN", "-1", "0", "9" * 40, "0751234a", "0000000Z"]
JUNK = ["zzzzzz", "pizza", "minecraft", "asdfgh", "qwertyuiop", "xyzzy", "blorptastic"]
STOPS = ["de la", "le", "et", "des", "pour le", "je veux faire"]
EQUIV = [("droit lyon", "DROIT LYON"), ("aix-en-provence droit", "aix en provence droit"),
         ("saint étienne", "st etienne"), ("ＬＹＯＮ droit", "lyon droit"), ("ly​on droit", "lyon droit"),
         ("infirmières", "infirmier"), ("écoles d'ingénieurs", "ecole ingenieur"), ("Médecine", "medecine"),
         ("I.U.T Toulouse", "iut toulouse"), ("licences de droit", "licence droit")]
DISCIPLINES = ["droit", "commerce", "sante", "lettres", "langues", "sport", "art", "histoire", "chimie",
               "biologie", "design", "gestion", "informatique", "musique", "cinema", "economie", "physique",
               "mathematiques", "philosophie", "communication", "tourisme", "transport", "agriculture"]


def check(name, ok, detail=""):
    return {"check": name, "ok": bool(ok), "detail": detail}


def top(con, q, k=5, **kw):
    return [r["cod_aff_form"] for r in S.search(con, q, limit=k, **kw)["results"]]


def run(con, n_load: int = 1000, seed: int = 0) -> list[dict]:
    out = []
    t0 = time.perf_counter()
    S._CACHE.clear()
    idx = S.get_index(con)
    build_ms = 1000 * (time.perf_counter() - t0)
    n_docs = len(idx.docs)

    # R1 hostile input
    bad = []
    for q in HOSTILE:
        try:
            t = time.perf_counter()
            r = S.search(con, q, limit=40)
            ms = 1000 * (time.perf_counter() - t)
            if ms > 250 or len(r["results"]) > 40 or r["total"] > n_docs or len(r["query"]) > S.MAX_QUERY_CHARS:
                bad.append((q[:30], round(ms), r["total"]))
        except Exception as exc:  # noqa: BLE001 - the point is to catch anything
            bad.append((q[:30], repr(exc)))
    out.append(check("R1 hostile input: no crash, limits respected, < 250 ms", not bad, bad))

    # R2 junk
    leaks = [(q, r["total"]) for q in JUNK if (r := S.search(con, q))["total"] and not r["partial"]]
    out.append(check("R2 junk words: 0 results or flagged partial", not leaks, leaks))

    # R3 stop-words
    leaks = [(q, S.search(con, q)["total"]) for q in STOPS if S.search(con, q)["total"]]
    out.append(check("R3 stop-words alone return nothing", not leaks, leaks))

    # R4 injection is inert
    leaks = [(q, S.search(con, q)["total"]) for q in ["%", "_", "' OR 1=1 --", ".*", "*"]
             if S.search(con, q)["total"]]
    out.append(check("R4 wildcard / SQL / regex shapes are inert", not leaks, leaks))

    # R5 normalisation equivalences
    diffs = [(a, b) for a, b in EQUIV if top(con, a) != top(con, b) or not top(con, a)]
    out.append(check("R5 normalisation equivalences give identical top-5", not diffs, diffs))

    # R6 disciplines are not places
    wrong = [w for w in DISCIPLINES if any(i["type"] == "lieu" for i in S.search(con, w)["interpretation"])]
    out.append(check("R6 discipline words are never taken as places", not wrong, wrong))

    # R7 filters narrow; facets add up
    probs = []
    for q in ["droit", "informatique", "lyon", "bts"]:
        r = S.search(con, q, limit=10_000)
        base = {x["cod_aff_form"] for x in r["results"]}
        for fac in ("fili", "academie"):
            for v in r["facets"][fac][:3]:
                kw = {"fili": v["value"]} if fac == "fili" else {"academie": v["value"]}
                rr = S.search(con, q, limit=10_000, **kw)
                sub = {x["cod_aff_form"] for x in rr["results"]}
                if not sub <= base or rr["total"] != v["count"]:
                    probs.append((q, fac, v["value"], v["count"], rr["total"]))
    # combined filters: the second facet's counts must already reflect the first filter
    for q in ["droit", "informatique"]:
        r1 = S.search(con, q, fili="Licence")
        for v in r1["facets"]["academie"][:4]:
            rr = S.search(con, q, fili="Licence", academie=v["value"])
            if rr["total"] != v["count"]:
                probs.append((q, "Licence+" + v["value"], v["count"], rr["total"]))
    out.append(check("R7 filters return subsets whose size equals the facet count (incl. combined)",
                     not probs, probs[:5]))

    # R8 pagination & determinism
    probs = []
    for q in ["droit", "bts", "paris"]:
        p1 = top(con, q, 20)
        p2 = [r["cod_aff_form"] for r in S.search(con, q, offset=20, limit=20)["results"]]
        allp = top(con, q, 40)
        if set(p1) & set(p2) or p1 + p2 != allp or top(con, q, 20) != p1:
            probs.append(q)
    out.append(check("R8 pages are disjoint, stable and deterministic", not probs, probs))

    # R9 health professions
    probs = []
    for q in ["médecine", "kiné", "sage-femme", "pharmacie", "dentaire"]:
        r = S.search(con, q)
        fil = {x["fili"] for x in r["results"][:10]}
        if not r["notes"] or not fil <= {"PASS", "Licence_Las", "Licence"}:
            probs.append((q, fil, len(r["notes"])))
    out.append(check("R9 health professions: access programmes + explanatory note", not probs, probs))

    # R10 junk next to a real word
    r = S.search(con, "droit zzzzzz")
    ok = r["partial"] and r["total"] and all("Droit" in (x["fil_lib_voe_acc"] or "") for x in r["results"][:5]) \
        and any(i["type"] == "ignoré" for i in r["interpretation"])
    out.append(check("R10 'droit zzzzzz': junk dropped, flagged, droit results kept", ok, r["interpretation"]))

    # R11 ranking ignores selectivity
    corr = []
    for q in ["droit", "psychologie", "bts ndrc", "staps"]:
        rs = [x for x in S.search(con, q, limit=200)["results"] if x["taux_acces_ens"] is not None]
        if len(rs) > 20:
            ranks = list(range(len(rs)))
            tx = [x["taux_acces_ens"] for x in rs]
            corr.append((q, round(_spearman(ranks, tx), 3)))
    out.append(check("R11 rank vs access rate |Spearman| < 0.3 (no prestige ordering)",
                     all(abs(c) < 0.3 for _, c in corr), corr))

    # R12 load
    rnd = random.Random(seed)
    vocab = [t for t in idx.postings["fil"] if len(t) > 3]
    places = [p for p in idx.places if len(p) > 3]
    lat = []
    for _ in range(n_load):
        q = " ".join(rnd.sample(vocab, rnd.choice([1, 2]))) + (" " + rnd.choice(places) if rnd.random() < .5 else "")
        if rnd.random() < .2:   # inject a typo
            i = rnd.randrange(len(q))
            q = q[:i] + q[i + 1:]
        t = time.perf_counter()
        S.search(con, q)
        lat.append(1000 * (time.perf_counter() - t))
    p95 = sorted(lat)[int(.95 * len(lat))]
    out.append(check("R12 load: p95 < 60 ms over random queries; index build < 5 s",
                     p95 < 60 and build_ms < 5000,
                     {"queries": n_load, "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(p95, 1),
                      "max_ms": round(max(lat), 1), "index_build_ms": round(build_ms), "docs": n_docs}))

    # R13 the UI escapes everything the API echoes
    js = (Path(__file__).resolve().parents[1] / "suptracker" / "static" / "app.js").read_text()
    m = re.search(r"async function viewSearch[\s\S]*?\n}\n", js)
    body = m.group(0) if m else ""
    # DOM-property assignments (dataset, value, hash) are not parsed as HTML: not an injection sink
    body = "\n".join(l for l in body.splitlines() if not re.search(r"\.(dataset\.\w+|hash|value)\s*=", l))
    # data fields interpolated without esc() (container .map() calls excluded), and bare loop
    # variables such as ${n} that would inject a raw string
    raw = re.findall(r"\$\{(?!esc\()(?:d|r|i|x|n|f|a)\.(?:query|value|notes?|g_ea_lib_vx|fil_lib_voe_acc|ville_etab|"
                     r"acad_mies|lib_comp_voe_ins|type)\b(?!\.map\()(?!\s*\?)", body)   # a field tested in a ternary is not output
    raw += re.findall(r"\$\{(?:n|q|v|i)\}", body)
    out.append(check("R13 viewSearch escapes every echoed string (query, interpretation, labels)",
                     bool(body) and not raw, raw))
    return out


def _spearman(a, b):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** .5
    return num / den if den else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--n", type=int, default=1000)
    a = ap.parse_args(argv)
    res = run(duckdb.connect(str(a.db), read_only=True), a.n)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + ("" if r["ok"] and not isinstance(r["detail"], dict)
                                                              else f"  -> {json.dumps(r['detail'], ensure_ascii=False, default=str)[:400]}"))
    ok = all(r["ok"] for r in res)
    print(f"\nRed team: {sum(r['ok'] for r in res)}/{len(res)} passed")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "search_redteam.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
