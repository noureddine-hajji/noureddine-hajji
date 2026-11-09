"""Harvest of the Parcoursup public reports archived by the Internet Archive (run by the `suptracker-rapports` workflow).

  1. ENUMERATE: the CDX API lists every archived `telechargerRapportPublic` PDF (both domains, every year), one row per
     distinct file (collapse on the content digest). The query is a PATH prefix: the archive sorts query parameters
     (c_ja_cod, g_ea_cod, g_ti_cod), so a prefix on "?g_ea_cod=" finds nothing (probe 1).
  2. FETCH + PARSE: each file not yet done is downloaded (`id_` = the original bytes) and parsed by rapports_parse;
     resumable: the state lives in data/rapports/harvest/ and each run stops after a time budget.
  3. REPAIR (--repair): the files left unread (download 404, damaged PDF) are tried again on every other capture of
     the same URL, as archived then rebuilt by qpdf; a rebuilt file counts only if COMPLETE (`complete`).
Outputs (CSV, small, committed): pdf_index.csv (one row per archived file, with its status), doublettes.csv,
synthese.csv, masked.csv. The PDFs themselves are not kept. Polite: one request at a time, pauses, back-off on 429/5xx,
generic User-Agent.
"""
from __future__ import annotations

import csv
import gzip
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
INDEX_COLS = ["timestamp", "original", "digest", "length", "status", "session", "codes", "n_doublettes", "n_synthese", "error",
              "source"]          # source: "" = the Internet Archive, "live" = the Parcoursup fiche itself (rapports_live)
DBL_COLS = ["digest", "timestamp", "session", "code", "jury", "bac", "doublette", "confirmes", "classes", "en_position", "acceptes"]
SYN_COLS = ["digest", "timestamp", "session", "code", "jury", "groupe", "places", "confirmes", "classes", "en_position", "acceptes"]
QUALI = ("criteres", "eds", "options_citees", "eliminatoires", "modalites", "algorithme", "conseils")
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


def store(out: Path, r: dict, p: dict, status: str = "ok") -> None:
    """Append a parsed report's rows and texts, and mark its index row (caller holds the lock)."""
    key = {"digest": r["digest"], "timestamp": r["timestamp"], "session": p["session"]}
    write(out / "doublettes.csv", DBL_COLS, [{**key, **d} for d in p["doublettes"]], append=True)
    write(out / "synthese.csv", SYN_COLS, [{**key, **d} for d in p["synthese"]], append=True)
    write(out / "masked.csv", MSK_COLS, [{**key, **d} for d in p["masked"]], append=True)
    # the jury's own texts (criteria, EDS, eliminating criteria, method, algorithm, advice), gzip members appended
    with gzip.open(out / "qualitatif.jsonl.gz", "at", encoding="utf-8") as g:
        g.write(json.dumps({**key, "codes": p["codes"], **{k: p[k] for k in QUALI}}, ensure_ascii=False) + "\n")
    r.update(status=status, session=p["session"], codes=";".join(p["codes"]), n_doublettes=len(p["doublettes"]),
             n_synthese=len(p["synthese"]))


def repaired(content: bytes) -> bytes:
    """qpdf (pikepdf) rebuilds a damaged cross-reference table: a file cut after its last page is readable again."""
    import io
    import pikepdf
    with pikepdf.open(io.BytesIO(content)) as pdf:
        buf = io.BytesIO()
        pdf.save(buf)
        return buf.getvalue()


def complete(p: dict) -> bool:
    """A repaired report is used only when nothing was lost: every page has text and its last section (the signature
    line) is there. Otherwise a table cut by the damage could pass the SIES check with missing doublette rows."""
    return p["pages"] > 0 and p["pages_vides"] == 0 and p["fin"]


def try_parse(content: bytes) -> tuple[dict | None, str, str]:
    """(parsed, status, note): the file as archived, else repaired and complete; never a partial report."""
    try:
        return parse(content), "ok", ""
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:120]
    try:
        p = parse(repaired(content))
    except Exception as e:  # noqa: BLE001
        return None, "parse_error", f"{err}; repair: {type(e).__name__}"[:200]
    if not complete(p):
        return None, "incomplet", f"{err}; repaired, {p['pages_vides']} empty page(s), end {'found' if p['fin'] else 'missing'}"
    return p, "ok_repare", f"repaired ({err})"[:200]


def captures(http: httpx.Client, original: str) -> list[tuple[str, str]]:
    """Every archived capture of this exact URL answered 200, newest first (timestamp, digest)."""
    r = call(http, CDX, {"url": original, "output": "json", "fl": "timestamp,digest,statuscode", "filter": "statuscode:200"})
    if r is None or r.status_code != 200 or not r.text.strip():
        return []
    rows = r.json()
    return sorted({(ts, dg) for ts, dg, _ in rows[1:]}, reverse=True)


def repair(http: httpx.Client, out: Path, budget_s: float, max_captures: int = 8) -> dict:
    """The files a harvest could not read (download failed, or unreadable PDF): try the URL's other captures, newest
    first, each as archived then repaired; the first complete one is kept. The archive link then names that capture."""
    t0 = time.time()
    idx = list(csv.DictReader(open(out / "pdf_index.csv", encoding="utf-8")))
    todo = [r for r in idx if r["status"] in ("retry", "failed", "parse_error", "incomplet")]
    for r in todo:
        if time.time() - t0 > budget_s:
            break
        own = (r["timestamp"], r["digest"])
        caps = [own] + [c for c in captures(http, r["original"]) if c != own]
        notes = []
        for ts, dg in caps[:max_captures]:
            resp = call(http, f"https://web.archive.org/web/{ts}id_/{r['original']}", pause=1.0)
            if resp is None or resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
                notes.append(f"{ts}: download {resp.status_code if resp is not None else 'none'}")
                continue
            p, status, note = try_parse(resp.content)
            if p is None:
                notes.append(f"{ts}: {note}")
                r["status"] = status
                continue
            r["timestamp"] = ts                 # the archive link shows the capture actually read
            store(out, r, p, status)
            r["error"] = "; ".join(notes + [f"{ts}: {note or 'ok'}"])[:300]
            break
        else:
            if r["status"] == "retry":
                r["status"] = "failed"
            r["error"] = "; ".join(notes)[:300] or r.get("error", "")
        print(r["digest"], r["status"], r["error"][:160], flush=True)
    write(out / "pdf_index.csv", INDEX_COLS, idx)
    return {"repair_tried": len(todo), "total": len(idx),
            "by_status": {s: sum(1 for r in idx if r["status"] == s) for s in sorted({r["status"] for r in idx})}}


def fetch(http: httpx.Client, out: Path, budget_s: float, workers: int = 2) -> dict:
    """Download and parse the files still to do; `workers` downloads at a time (each paced), writes under one lock."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    idx = list(csv.DictReader(open(out / "pdf_index.csv", encoding="utf-8")))
    todo = [r for r in idx if r["status"] in ("todo", "retry")]
    lock = threading.Lock()
    done = [0]

    def one(r):
        if time.time() - t0 > budget_s:
            return
        resp = call(http, f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}", pause=1.0)
        if resp is None or resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            r["status"] = "retry" if r["status"] == "todo" else "failed"
            r["error"] = "download " + (str(resp.status_code) if resp is not None else "none")
            return
        try:
            p = parse(resp.content)
        except Exception as e:  # noqa: BLE001
            r["status"], r["error"] = "parse_error", f"{type(e).__name__}: {e}"[:200]
            return
        r["error"] = ""
        with lock:
            store(out, r, p)
            done[0] += 1
            if done[0] % 200 == 0:
                write(out / "pdf_index.csv", INDEX_COLS, idx)
                print(f"{done[0]} parsed, {time.time() - t0:.0f} s", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    write(out / "pdf_index.csv", INDEX_COLS, idx)
    left = sum(1 for r in idx if r["status"] in ("todo", "retry"))
    return {"parsed_this_run": done[0], "left": left, "total": len(idx),
            "by_status": {s: sum(1 for r in idx if r["status"] == s) for s in sorted({r["status"] for r in idx})}}


def main(out: str, budget_min: float, reenumerate: bool, fix: bool = False) -> None:
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
        if reenumerate or not (dest / "pdf_index.csv").exists():
            print("enumerated", enumerate_pdfs(http, dest), flush=True)
        res = repair(http, dest, budget_min * 60) if fix else fetch(http, dest, budget_min * 60)
    (dest / "last_run.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 300, "--enumerate" in sys.argv, "--repair" in sys.argv)
