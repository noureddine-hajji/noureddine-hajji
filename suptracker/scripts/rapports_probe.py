"""Probe of the Parcoursup public reports ("rapports publics des commissions d'examen des vœux"), run by the
`suptracker-rapports` workflow (the Parcoursup, SIES and Internet Archive hosts are blocked in the development sandbox).

It brings back SMALL samples so the full harvest and its PDF parser can be designed on real material:
  1. the SIES 2020 and 2021 exports, reduced to the formation keys (code, UAI, labels, fiche link);
  2. a few LIVE formation pages (current session), with every link that looks like a public report;
  3. the PDFs those links point to, and their text extracted page by page (pdfplumber);
  4. Wayback Machine CDX answers for the same codes and their UAIs (fiches and report PDFs, both domains),
     and one archived PDF when one exists.
Everything is written under data/rapports/probe/ with a summary.json. Polite: one request at a time, a pause
between requests, a generic User-Agent (no personal address).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import duckdb
import httpx

UA = "SupCompass-research/1.0 (+https://github.com/noureddine-hajji/noureddine-hajji)"
PAUSE = 1.5
DOMS = ("dossierappel.parcoursup.fr", "dossier.parcoursup.fr")
FICHE = "https://{d}/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={c}"
RAPP = "https://{d}/Candidats/public/fiches/telechargerRapportPublic?g_ea_cod={u}"
SIES = "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets/fr-esr-parcoursup_{y}/exports/csv?delimiter=%3B"
KEYS = ("session", "cod_aff_form", "cod_uai", "g_ea_lib_vx", "lib_for_voe_ins", "fil_lib_voe_acc", "form_lib_voe_acc",
        "ville_etab", "acad_mies", "lien_form_psup")


def get(http: httpx.Client, url: str, log: list, **kw) -> httpx.Response | None:
    time.sleep(PAUSE)
    try:
        r = http.get(url, **kw)
        log.append({"url": url, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content)})
        return r
    except httpx.HTTPError as e:
        log.append({"url": url, "error": f"{type(e).__name__}: {e}"})
        return None


def cdx(u: str, code_re: str, pdf: bool = False) -> str:
    q = ("https://web.archive.org/cdx/search/cdx?url=" + quote(u, safe=":/") + "&matchType=prefix&output=json"
         "&fl=timestamp,original,mimetype,statuscode&filter=statuscode:200&filter=" + quote("original:" + code_re, safe=":"))
    return q + ("&filter=mimetype:application/pdf" if pdf else "&collapse=timestamp:6")


def pdf_text(content: bytes) -> list[str]:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def sies_keys(http, year: int, dest: Path, log: list) -> dict:
    r = get(http, SIES.format(y=year), log, timeout=300)
    if r is None or r.status_code != 200:
        return {"year": year, "ok": False}
    text = r.content.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text), delimiter=";")
    cols = rd.fieldnames or []
    rows = list(rd)
    keep = [k for k in KEYS if k in cols]
    with open(dest / f"sies_{year}_keys.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(keep)
        for x in rows:
            w.writerow([x.get(k, "") for k in keep])
    return {"year": year, "ok": True, "rows": len(rows), "columns": cols, "kept": keep,
            "distinct_codes": len({x.get("cod_aff_form") for x in rows})}


def main(db: str, out: str, n: int) -> None:
    dest = Path(out)
    (dest / "fiches").mkdir(parents=True, exist_ok=True)
    (dest / "pdf").mkdir(parents=True, exist_ok=True)
    log: list = []
    summary: dict = {"n": n}
    con = duckdb.connect(db, read_only=True)
    # a spread of filières, latest campaign; the IUT de Nice example (2327) first: its 2025 PDF is the owner's reference
    sample = ["2327"] + [c for (c,) in con.execute("""
        SELECT cod_aff_form FROM (SELECT cod_aff_form, fili, row_number() OVER (PARTITION BY fili ORDER BY hash(cod_aff_form)) k
                                  FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year))
        WHERE k <= 2 AND cod_aff_form <> '2327' ORDER BY hash(cod_aff_form) LIMIT ?""", [n - 1]).fetchall()]
    uai = dict(con.execute("SELECT cod_aff_form, any_value(cod_uai ORDER BY session DESC) FROM core.formation_year GROUP BY 1").fetchall())
    summary["sample"] = sample
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": UA}) as http:
        summary["sies"] = [sies_keys(http, y, dest, log) for y in (2020, 2021)]
        links: dict = {}
        for cod in sample:
            r = get(http, FICHE.format(d=DOMS[0], c=cod) + "&typeBac=0&originePc=0", log)
            if r is None:
                continue
            html = r.text
            (dest / "fiches" / f"{cod}.html").write_text(html, encoding="utf-8")
            hrefs = sorted({urljoin(str(r.url), h.replace("&amp;", "&")) for h in re.findall(r'href="([^"]+)"', html)
                            if re.search(r"rapport|Rapport|\.pdf", h)})
            links[cod] = hrefs
        summary["report_links"] = links
        pdfs = []
        for cod, hrefs in links.items():
            for h in hrefs[:2]:
                r = get(http, h, log)
                if r is None or r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    continue
                tag = hashlib.sha256(h.encode()).hexdigest()[:8]
                (dest / "pdf" / f"live_{cod}_{tag}.pdf").write_bytes(r.content)
                try:
                    pages = pdf_text(r.content)
                    (dest / "pdf" / f"live_{cod}_{tag}.txt").write_text("\n\n=== PAGE ===\n\n".join(pages), encoding="utf-8")
                except Exception as e:  # noqa: BLE001
                    pages = [f"parse error {e}"]
                pdfs.append({"code": cod, "url": h, "bytes": len(r.content), "pages": len(pages)})
        summary["live_pdfs"] = pdfs
        wb = {}
        for cod in sample:
            u = uai.get(cod)
            entry = {}
            for d in DOMS:
                r = get(http, cdx(FICHE.format(d=d, c=cod), r".*g_ta_cod=" + re.escape(cod) + r"(&.*)?$"), log)
                entry[f"fiche_{d}"] = r.json() if r is not None and r.status_code == 200 and r.text.strip() else (r.status_code if r else None)
                if u:
                    r = get(http, cdx(RAPP.format(d=d, u=u), r".*g_ea_cod=" + re.escape(u) + r"(&.*)?$", True), log)
                    entry[f"pdf_{d}"] = r.json() if r is not None and r.status_code == 200 and r.text.strip() else (r.status_code if r else None)
            wb[cod] = entry
        summary["wayback"] = wb
        got = 0
        for cod, entry in wb.items():
            for k, v in entry.items():
                if k.startswith("pdf_") and isinstance(v, list) and len(v) > 1 and got < 3:
                    ts, orig = v[1][0], v[1][1]
                    r = get(http, f"https://web.archive.org/web/{ts}id_/{orig}", log)
                    if r is not None and r.content.startswith(b"%PDF"):
                        (dest / "pdf" / f"wayback_{cod}_{ts}.pdf").write_bytes(r.content)
                        try:
                            (dest / "pdf" / f"wayback_{cod}_{ts}.txt").write_text("\n\n=== PAGE ===\n\n".join(pdf_text(r.content)), encoding="utf-8")
                        except Exception:  # noqa: BLE001
                            pass
                        got += 1
        summary["wayback_pdfs_downloaded"] = got
        # probe 2: the ARCHIVED fiche pages (a capture made during a campaign links the previous session's report, with its
        # g_ti_cod and c_ja_cod); every report link found is looked up in the archive and fetched when it is there
        (dest / "wayback_fiches").mkdir(exist_ok=True)
        found = {}
        for cod, entry in wb.items():
            for k, v in entry.items():
                if not (k.startswith("fiche_") and isinstance(v, list) and len(v) > 1):
                    continue
                for ts, orig, *_ in v[1:][-2:]:
                    r = get(http, f"https://web.archive.org/web/{ts}id_/{orig}", log)
                    if r is None or r.status_code != 200:
                        continue
                    (dest / "wayback_fiches" / f"{cod}_{ts}.html").write_text(r.text, encoding="utf-8")
                    hrefs = sorted({urljoin(orig, h.replace("&amp;", "&")) for h in re.findall(r'href="([^"]+)"', r.text)
                                    if re.search(r"[Rr]apport|\.pdf", h)})
                    found[f"{cod}_{ts}"] = hrefs
                    for h in hrefs[:2]:
                        r2 = get(http, "https://web.archive.org/cdx/search/cdx?url=" + quote(h, safe=":/") + "&output=json&fl=timestamp,original,mimetype,statuscode", log)
                        rows = r2.json() if r2 is not None and r2.status_code == 200 and r2.text.strip() else []
                        found[f"{cod}_{ts}"].append({"cdx": h, "captures": rows[1:4]})
                        for row in rows[1:2]:
                            r3 = get(http, f"https://web.archive.org/web/{row[0]}id_/{row[1]}", log)
                            if r3 is not None and r3.content.startswith(b"%PDF"):
                                (dest / "pdf").mkdir(exist_ok=True)
                                (dest / "pdf" / f"wayback_{cod}_{row[0]}.pdf").write_bytes(r3.content)
                                try:
                                    (dest / "pdf" / f"wayback_{cod}_{row[0]}.txt").write_text("\n\n=== PAGE ===\n\n".join(pdf_text(r3.content)), encoding="utf-8")
                                except Exception:  # noqa: BLE001
                                    pass
        summary["wayback_fiche_report_links"] = found
        # is the live site back? (it answered a maintenance page on 2026-11-08)
        for u in ("https://www.parcoursup.gouv.fr/", "https://dossierappel.parcoursup.fr/Candidats/carte", FICHE.format(d=DOMS[0], c="2327")):
            r = get(http, u, log)
            summary.setdefault("live_status", {})[u] = (r.status_code, "indisponible" in r.text) if r is not None else None
    summary["requests"] = log
    (dest / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "requests"}, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 12)
