"""Download every file linked from an HTML page whose href matches a regex.

Used by the `suptracker-probe` workflow to bring a new official source into the repository
for inspection. Writes the page itself (page.html), the files and an index.json
(url, file, bytes, sha256).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

MAX_FILES = 20
MAX_BYTES = 30_000_000


def main(page: str, pattern: str, out: str) -> None:
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "suptracker-probe"}) as http:
        html = http.get(page).raise_for_status().text
        (dest / "page.html").write_text(html, encoding="utf-8")
        hrefs = re.findall(r'href="([^"]+)"', html)
        rx = re.compile(pattern, re.I)
        urls = list(dict.fromkeys(urljoin(page, h) for h in hrefs if rx.search(h)))[:MAX_FILES]
        index = []
        for url in urls:
            name = re.sub(r"[^\w.\-]", "_", unquote(Path(urlparse(url).path).name)) or "file"
            body = http.get(url).raise_for_status().content
            if len(body) > MAX_BYTES:
                print(f"skip {url}: {len(body)} bytes")
                continue
            (dest / name).write_bytes(body)
            index.append({"url": url, "file": name, "bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest()})
            print(f"{name}: {len(body)} bytes")
    (dest / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    if not index:
        sys.exit("no file matched")


if __name__ == "__main__":
    main(*sys.argv[1:4])
