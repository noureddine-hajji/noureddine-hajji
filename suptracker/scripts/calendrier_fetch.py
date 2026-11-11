"""Sprint 22: fetch the OFFICIAL Parcoursup campaign calendar (parcoursup.gouv.fr is blocked in the development sandbox).
    python scripts/calendrier_fetch.py data/calendrier
Reads data/calendrier/request.json ({"urls": [...]}), downloads each URL (PDF or HTML page) and writes the extracted text
(pdfplumber for a PDF) with the file's digest, so the dates are read from the official document, never from a press article.
The PDF itself is not kept (its illustrations are not under the Licence Ouverte). A redirect to another host is refused. When no
PDF could be read, the previous log is kept and the script fails (review: an empty log would empty the calendar).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ALLOWED = ("https://www.parcoursup.gouv.fr/", "https://parcoursup.gouv.fr/")


def main(out: str) -> int:
    d = Path(out)
    req = json.loads((d / "request.json").read_text())
    log = []
    for url in req["urls"]:
        if not url.startswith(ALLOWED):
            log.append({"url": url, "status": "refused: not an official parcoursup.gouv.fr address"})
            continue
        try:
            r = httpx.get(url, follow_redirects=True, timeout=60, headers={"User-Agent": "SupCompass calendar fetch (robot)"})
        except httpx.HTTPError as e:
            log.append({"url": url, "status": f"error {type(e).__name__}"})
            continue
        if not str(r.url).startswith(ALLOWED):
            log.append({"url": url, "status": f"refused: redirected to {r.url.host}"})
            continue
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.rsplit("/", 1)[-1] or "page")[:120]
        row = {"url": url, "status": r.status_code, "final_url": str(r.url), "bytes": len(r.content),
               "sha256": hashlib.sha256(r.content).hexdigest(), "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if r.status_code == 200:
            ctype = r.headers.get("content-type", "")
            if "pdf" in ctype or r.content[:4] == b"%PDF":
                import io

                import pdfplumber
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    text = "\n\n".join(f"--- page {i + 1} ---\n" + (p.extract_text() or "") for i, p in enumerate(pdf.pages))
                (d / f"{name}.txt").write_text(text)
                row["file"] = name
            else:
                html = r.text
                text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
                text = re.sub(r"<[^>]+>", "\n", text)
                text = re.sub(r"\n\s*\n+", "\n", text)
                (d / f"{name}.txt").write_text(text)
                row["file"] = f"{name}.txt"
        log.append(row)
    if not any(row.get("status") == 200 and str(row.get("file", "")).endswith(".pdf") for row in log):
        print("no official PDF could be read: the previous log is kept", file=sys.stderr)
        return 1
    (d / "fetch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
