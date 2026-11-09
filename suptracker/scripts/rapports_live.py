"""Direct harvest of the Parcoursup public reports from the LIVE fiches (run by the `suptracker-rapports` workflow,
mode "live", and every day on its schedule).

Parcoursup publishes no list of its reports: each one is linked from its formation's fiche
(`afficherFicheFormation?g_ta_cod=<code>`, link id "lien-rapp-pub"), and only while the fiches are open (from the new
campaign's opening, in December). The archive covered a third of the formations; this harvest reads every fiche of the latest
cartographie session, follows its report link(s), and parses each PDF with rapports_parse, into the SAME harvest files as the
archive (pdf_index.csv rows with source "live"), so rapports.build applies the same verification (printed code + confirmed
candidates = SIES nb_voe_pp of that code and session).

  * Closed site: the first fiches answer 404 / "indisponible": the run records "closed" and stops (a daily run costs seconds).
  * Resumable: data/rapports/live/fiches.csv holds each code's state; each run stops after its time budget.
  * Polite: one request at a time, paced, back-off on 429/5xx, a generic User-Agent (never a person's address).
  * A PDF already harvested (same content digest) is not stored twice.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from rapports_harvest import INDEX_COLS, UA, call, store, write  # noqa: E402
from rapports_parse import parse  # noqa: E402

FICHE = "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={cod}&typeBac=0&originePc=0"
LINK_RE = re.compile(r"""href=["']([^"']*telechargerRapportPublic\?[^"']+)["']""")
SESSION_RE = re.compile(r"rapport d'analyse des candidatures de la session (\d{4})", re.I)
STATE_COLS = ["cod_aff_form", "status", "fetched_at", "links", "digests", "error"]
CLOSED_MARKS = ("indisponible", "maintenance")


def report_links(page: str, base: str) -> list[str]:
    """The report links of a fiche page, absolute, unescaped, in page order, each once."""
    out = []
    for m in LINK_RE.finditer(page):
        u = urljoin(base, html.unescape(m.group(1)))
        if u.startswith("https://") and "parcoursup.fr/" in u and u not in out:
            out.append(u)
    return out


def digest(content: bytes) -> str:
    """The archive's digest form (base32 of the SHA-1), so a file already archived is recognised."""
    return base64.b32encode(hashlib.sha1(content).digest()).decode()


def is_closed(resp) -> bool:
    return resp is None or resp.status_code == 404 or any(k in resp.text.lower() for k in CLOSED_MARKS) and not LINK_RE.search(resp.text)


def codes(db: str) -> list[str]:
    import duckdb
    con = duckdb.connect(db, read_only=True)
    try:
        return [c for (c,) in con.execute("""SELECT cod_aff_form FROM core.cartographie
            WHERE carto_session = (SELECT max(carto_session) FROM core.cartographie) ORDER BY cod_aff_form""").fetchall()]
    finally:
        con.close()


def read_state(path: Path, all_codes: list[str]) -> dict:
    st = {r["cod_aff_form"]: r for r in csv.DictReader(open(path, encoding="utf-8"))} if path.exists() else {}
    for c in all_codes:
        st.setdefault(c, {"cod_aff_form": c, "status": "todo", "fetched_at": "", "links": "", "digests": "", "error": ""})
    return st


def harvest(http, db: str, out: Path, live: Path, budget_s: float, pause: float = 1.5, probe_codes: int = 3) -> dict:
    t0 = time.time()
    live.mkdir(parents=True, exist_ok=True)
    state = read_state(live / "fiches.csv", codes(db))
    todo = [r for r in state.values() if r["status"] in ("todo", "retry")]
    idx = list(csv.DictReader(open(out / "pdf_index.csv", encoding="utf-8"))) if (out / "pdf_index.csv").exists() else []
    known = {r["digest"] for r in idx}
    # is the site open? a few fiches first
    closed = 0
    for r in todo[:probe_codes]:
        resp = call(http, FICHE.format(cod=r["cod_aff_form"]), pause=pause)
        closed += is_closed(resp)
    if todo and closed == min(probe_codes, len(todo)):
        res = {"status": "closed", "checked_at": _now(), "todo": len(todo), "total": len(state)}
        prev = live / "last_run.json"
        # a closed site changes nothing: no commit (hence no deployment) every day; only the first closed run is written
        if not prev.exists() or json.loads(prev.read_text(encoding="utf-8")).get("status") != "closed":
            prev.write_text(json.dumps(res, indent=1), encoding="utf-8")
        return res
    n_pdf = 0
    for r in todo:
        if time.time() - t0 > budget_s:
            break
        url = FICHE.format(cod=r["cod_aff_form"])
        resp = call(http, url, pause=pause)
        r["fetched_at"] = _now()
        if resp is None or resp.status_code != 200:
            r["status"] = "retry" if r["status"] == "todo" else "failed"
            r["error"] = f"fiche {resp.status_code if resp is not None else 'none'}"
            continue
        links = report_links(resp.text, url)
        r["links"] = ";".join(links)
        if not links:
            r["status"], r["error"] = "sans_rapport", ""
            continue
        digs, errs = [], []
        for link in links:
            pdf = call(http, link, pause=pause)
            if pdf is None or pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
                errs.append(f"pdf {pdf.status_code if pdf is not None else 'none'}")
                continue
            dg = digest(pdf.content)
            digs.append(dg)
            if dg in known:
                continue
            row = {"timestamp": r["fetched_at"], "original": link, "digest": dg, "length": str(len(pdf.content)),
                   "status": "todo", "source": "live"}
            try:
                store(out, row, parse(pdf.content))
            except Exception as e:  # noqa: BLE001
                row.update(status="parse_error", error=f"{type(e).__name__}: {e}"[:200])
            idx.append(row)
            known.add(dg)
            n_pdf += 1
        r["digests"], r["error"] = ";".join(digs), "; ".join(errs)
        r["status"] = "ok" if digs and not errs else "retry" if r["status"] == "todo" else "failed"
        if n_pdf and n_pdf % 200 == 0:
            _save(out, live, idx, state)
    _save(out, live, idx, state)
    by = {}
    for r in state.values():
        by[r["status"]] = by.get(r["status"], 0) + 1
    res = {"status": "open", "checked_at": _now(), "new_pdfs": n_pdf, "total": len(state), "by_status": by}
    (live / "last_run.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _save(out: Path, live: Path, idx: list, state: dict) -> None:
    write(out / "pdf_index.csv", INDEX_COLS, idx)
    write(live / "fiches.csv", STATE_COLS, sorted(state.values(), key=lambda r: r["cod_aff_form"]))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def main(db: str, out: str, live: str, budget_min: float) -> None:
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
        res = harvest(http, db, Path(out), Path(live), budget_min * 60)
    print(json.dumps(res), flush=True)





# ------------------------------------------------------------------ probe (mode "liveprobe"): what Parcoursup serves today
PROBE_REPORTS = [("0160006V", "2986", "1833"), ("0720083Z", "8710", "7269"), ("0670080Y", "31389", "24273")]   # owner's examples
HOSTS = ("dossier.parcoursup.fr", "dossierappel.parcoursup.fr")


def probe(http, out: Path, pause: float = 1.5) -> dict:
    """Each owner's example as given, without its jury code, and on the other host; the fiche pages on both hosts."""
    res = []
    rap = "https://{h}/Candidats/public/fiches/telechargerRapportPublic?g_ea_cod={u}&g_ti_cod={t}{j}"
    for u, t, j in PROBE_REPORTS:
        for h in HOSTS:
            for jj in (f"&c_ja_cod={j}", ""):
                url = rap.format(h=h, u=u, t=t, j=jj)
                r = call(http, url, pause=pause)
                row = {"url": url, "status": None if r is None else r.status_code, "pdf": bool(r is not None and r.content.startswith(b"%PDF")),
                       "bytes": None if r is None else len(r.content), "type": None if r is None else r.headers.get("content-type")}
                if row["pdf"]:
                    try:
                        p = parse(r.content)
                        row.update(session=p["session"], codes=p["codes"], n_doublettes=len(p["doublettes"]))
                    except Exception as e:  # noqa: BLE001
                        row["parse_error"] = f"{type(e).__name__}: {e}"[:120]
                res.append(row)
            fiche = f"https://{h}/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={t}&typeBac=0&originePc=0"
            r = call(http, fiche, pause=pause)
            res.append({"url": fiche, "status": None if r is None else r.status_code, "closed": is_closed(r),
                        "links": report_links(r.text, fiche) if r is not None else [],
                        "sessions": SESSION_RE.findall(r.text) if r is not None else []})
    summary = {"checked_at": _now(), "results": res}
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":
    if sys.argv[1] == "--probe":
        with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
            print(json.dumps(probe(http, Path(sys.argv[2])), ensure_ascii=False)[:4000], flush=True)
    else:
        main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 300)
