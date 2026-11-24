"""Sprint F (financer ses études): fetch the OFFICIAL texts that set the student aids (blocked in the development sandbox).
    python scripts/aides_fetch.py data/aides
Reads data/aides/request.json ({"urls": [...]}), downloads each page of an official host only (Légifrance, service-public,
etudiant.gouv.fr, parcoursup.gouv.fr, the ministry) and writes its extracted text with its digest; a redirect to another host is
refused. The amounts the site shows are read from these files by fixed rules (`aides.py`), never typed from a press article.
When no page could be read, the previous log is kept and the script fails (an empty log would empty the card).
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ALLOWED = ("https://www.legifrance.gouv.fr/", "https://www.service-public.gouv.fr/", "https://www.etudiant.gouv.fr/",
           "https://www.parcoursup.gouv.fr/", "https://www.enseignementsup-recherche.gouv.fr/", "https://cvec.etudiant.gouv.fr/",
           "https://www.messervices.etudiant.gouv.fr/")


def page_text(html: str) -> str:
    """The visible text of an HTML page, one block per line (scripts, styles and tags dropped, entities decoded)."""
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(p|div|li|tr|h[1-6]|td|th|section|article)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t).replace("\xa0", " ").replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", "\n".join(x.strip() for x in t.splitlines())).strip() + "\n"


def page_links(html: str, base: str) -> list:
    """[text, absolute https URL] of every link of the page, in order, deduplicated (the card links only what an official
    page links: the simulator, the online services)."""
    out, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        url = str(httpx.URL(base).join(htmlmod.unescape(href)))
        text = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if url.startswith("https://") and (text, url) not in seen:
            seen.add((text, url))
            out.append([text, url])
    return out


def name_of(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[-1])[:140] + ".txt"


def main(out: str) -> int:
    d = Path(out)
    req = json.loads((d / "request.json").read_text())
    log = []
    with httpx.Client(follow_redirects=True, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (compatible; SupCompass official-texts fetch; robot)",
                               "Accept-Language": "fr-FR,fr;q=0.9"}) as client:
        for url in req["urls"]:
            if not url.startswith(ALLOWED):
                log.append({"url": url, "status": "refused: not an official host"})
                continue
            try:
                r = client.get(url)
            except httpx.HTTPError as e:
                log.append({"url": url, "status": f"error {type(e).__name__}"})
                continue
            if not str(r.url).startswith(ALLOWED):
                log.append({"url": url, "status": f"refused: redirected to {r.url.host}"})
                continue
            text = page_text(r.text) if r.status_code == 200 else ""
            row = {"url": url, "status": r.status_code, "final_url": str(r.url),
                   "sha256": hashlib.sha256(text.encode()).hexdigest(),          # of the text read: a page's tokens change daily
                   "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if r.status_code == 200:
                (d / name_of(url)).write_text(text)
                (d / name_of(url).replace(".txt", ".links.json")).write_text(
                    json.dumps(page_links(r.text, str(r.url)), ensure_ascii=False, indent=0) + "\n")
                row["file"] = name_of(url)
            log.append(row)
    if not any(row.get("status") == 200 for row in log):
        print("no official page could be read: the previous log is kept", file=sys.stderr)
        print(json.dumps(log, ensure_ascii=False, indent=1), file=sys.stderr)
        return 1
    old = d / "fetch_log.json"
    strip = lambda rows: [{k: v for k, v in r.items() if k != "fetched"} for r in rows]       # noqa: E731
    if old.exists() and strip(json.loads(old.read_text())) == strip(log):
        return 0                                # same pages: no new commit, no warehouse rebuild for a date
    old.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
