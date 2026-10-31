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


def dest_name(url: str, taken: set[str]) -> str:
    """A file name for `url` that no other downloaded URL uses: same-basename links (other year
    folder, other query string) get a short URL hash so none overwrites another."""
    name = re.sub(r"[^\w.\-]", "_", unquote(Path(urlparse(url).path).name)) or "file"
    if name in taken:
        stem, dot, ext = name.rpartition(".")
        tag = hashlib.sha256(url.encode()).hexdigest()[:8]
        name = f"{stem}-{tag}.{ext}" if dot and stem else f"{name}-{tag}"
    taken.add(name)
    return name


def main(page: str, pattern: str, out: str) -> None:
    dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "suptracker-probe"}) as http:
        html = http.get(page).raise_for_status().text
        (dest / "page.html").write_text(html, encoding="utf-8")
        hrefs = re.findall(r'href="([^"]+)"', html)
        rx = re.compile(pattern, re.I)
        urls = list(dict.fromkeys(urljoin(page, h) for h in hrefs if rx.search(h)))[:MAX_FILES]
        index, taken = [], {"page.html", "index.json"}
        for url in urls:
            name = dest_name(url, taken)
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
