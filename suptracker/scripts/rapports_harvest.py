"""Harvest of the Parcoursup public reports archived by the Internet Archive (run by the `suptracker-rapports` workflow).

  1. ENUMERATE: the CDX API lists every archived `telechargerRapportPublic` PDF (both domains, every year), one row per
     distinct file (collapse on the content digest). The query is a PATH prefix: the archive sorts query parameters
     (c_ja_cod, g_ea_cod, g_ti_cod), so a prefix on "?g_ea_cod=" finds nothing (probe 1).
  2. FETCH + PARSE: each file not yet done is downloaded (`id_` = the original bytes) and parsed by rapports_parse;
     resumable: the state lives in data/rapports/harvest/ and each run stops after a time budget.
Outputs (CSV, small, committed): pdf_index.csv (one row per archived file, with its status), doublettes.csv,
synthese.csv, masked.csv. The PDFs themselves are not kept. Polite: one request at a time, pauses, back-off on 429/5xx,
generic User-Agent.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from rapports_parse import parse  # noqa: E402

UA = "SupCompass-research/1.0 (+https://github.com/noureddine-hajji/noureddine-hajji)"
ROOTS = ("dossier.parcoursup.fr/Candidats/public/fiches/telechargerRapportPublic",
         "dossierappel.parcoursup.fr/Candidats/public/fiches/telechargerRapportPublic")
CDX = "https://web.archive.org/cdx/search/cdx"
INDEX_COLS = ["timestamp", "original", "digest", "length", "status", "session", "codes", "n_doublettes", "n_synthese", "error"]
DBL_COLS = ["digest", "timestamp", "session", "code", "jury", "bac", "doublette", "confirmes", "classes", "en_position", "acceptes"]
SYN_COLS = ["digest", "timestamp", "session", "code", "jury", "groupe", "places", "confirmes", "classes", "en_position", "acceptes"]
MSK_COLS = ["digest", "timestamp", "session", "code", "jury", "bac"]


def call(http: httpx.Client, url: str, params=None, pause: float = 1.0, tries: int = 6):
    wait = 5.0
    for _ in range(tries):
        time.sleep(pause)
        try:
            r = http.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(wait); wait = min(wait * 2, 300); continue
            return r
        except httpx.HTTPError:
            time.sleep(wait); wait = min(wait * 2, 300)
    return None


def enumerate_pdfs(http: httpx.Client, out: Path) -> int:
    seen, rows = set(), []
    for root in ROOTS:
        base = {"url": root, "matchType": "prefix", "output": "json", "fl": "timestamp,original,digest,length,statuscode,mimetype",
                "filter": ["statuscode:200", "mimetype:application/pdf"], "collapse": "digest"}
        r = call(http, CDX, {**base, "showNumPages": "true"})
        pages = int(r.text.strip()) if r is not None and r.text.strip().isdigit() else 1
        print(f"{root}: {pages} CDX page(s)", flush=True)
        for p in range(pages):
            r = call(http, CDX, {**base, "page": str(p)})
            if r is None or r.status_code != 200 or not r.text.strip():
                print(f"  page {p}: {None if r is None else r.status_code}", flush=True)
                continue
            data = r.json()
            for ts, orig, dig, ln, *_ in data[1:] if data and data[0][0] == "timestamp" else data:
                if dig in seen:
                    continue
                seen.add(dig)
                rows.append({"timestamp": ts, "original": orig, "digest": dig, "length": ln, "status": "todo"})
            print(f"  page {p}: {len(rows)} files so far", flush=True)
    old = {}
    if (out / "pdf_index.csv").exists():
        old = {r["digest"]: r for r in csv.DictReader(open(out / "pdf_index.csv", encoding="utf-8"))}
    merged = {**{r["digest"]: r for r in rows}, **old}        # a file already processed keeps its status
    write(out / "pdf_index.csv", INDEX_COLS, sorted(merged.values(), key=lambda r: (r["timestamp"], r["digest"])))
    return len(merged)


def write(path: Path, cols, rows, append: bool = False):
    new = not path.exists() or not append
    with open(path, "a" if append else "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def fetch(http: httpx.Client, out: Path, budget_s: float) -> dict:
    t0 = time.time()
    idx = list(csv.DictReader(open(out / "pdf_index.csv", encoding="utf-8")))
    todo = [r for r in idx if r["status"] in ("todo", "retry")]
    done = 0
    for r in todo:
        if time.time() - t0 > budget_s:
            break
        resp = call(http, f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}", pause=1.0)
        if resp is None or resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            r["status"] = "retry" if r["status"] == "todo" else "failed"
            r["error"] = "download " + (str(resp.status_code) if resp is not None else "none")
            continue
        try:
            p = parse(resp.content)
        except Exception as e:  # noqa: BLE001
            r["status"], r["error"] = "parse_error", f"{type(e).__name__}: {e}"[:200]
            continue
        key = {"digest": r["digest"], "timestamp": r["timestamp"], "session": p["session"]}
        write(out / "doublettes.csv", DBL_COLS, [{**key, **d} for d in p["doublettes"]], append=True)
        write(out / "synthese.csv", SYN_COLS, [{**key, **d} for d in p["synthese"]], append=True)
        write(out / "masked.csv", MSK_COLS, [{**key, **d} for d in p["masked"]], append=True)
        r.update(status="ok", session=p["session"], codes=";".join(p["codes"]), n_doublettes=len(p["doublettes"]),
                 n_synthese=len(p["synthese"]), error="")
        done += 1
        if done % 200 == 0:
            write(out / "pdf_index.csv", INDEX_COLS, idx)
            print(f"{done} parsed, {time.time() - t0:.0f} s", flush=True)
    write(out / "pdf_index.csv", INDEX_COLS, idx)
    left = sum(1 for r in idx if r["status"] in ("todo", "retry"))
    return {"parsed_this_run": done, "left": left, "total": len(idx),
            "by_status": {s: sum(1 for r in idx if r["status"] == s) for s in sorted({r["status"] for r in idx})}}


def main(out: str, budget_min: float, reenumerate: bool) -> None:
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
        if reenumerate or not (dest / "pdf_index.csv").exists():
            print("enumerated", enumerate_pdfs(http, dest), flush=True)
        res = fetch(http, dest, budget_min * 60)
    (dest / "last_run.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 300, "--enumerate" in sys.argv)
