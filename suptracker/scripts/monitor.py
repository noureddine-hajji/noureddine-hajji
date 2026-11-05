"""Sprint 10: check the LIVE site (run every 6 hours by .github/workflows/suptracker-monitor.yml).

    python scripts/monitor.py https://<production domain> [--max-seconds 8]

Exit code 1 (the workflow turns red and GitHub e-mails the owner) when the site is down, slow, serves an
old front-end, or breaks one of its promises: versioned assets immutable, personal answers never cached.
The monitor sends `DNT: 1` and a robot user agent: it is never counted in the audience.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

UA = "SupTrackerMonitor/1.0 (+uptime check; bot)"
RETRIES, PAUSE = 2, 2.0


def get(base: str, path: str, timeout: float) -> tuple[int, dict, bytes, float]:
    req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": UA, "DNT": "1", "Accept-Encoding": "identity"})
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body, time.monotonic() - t
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(), time.monotonic() - t


def checks(base: str, max_s: float, fetch=get) -> list[tuple[str, bool, str]]:
    out = []

    def add(name, ok, detail):
        out.append((name, bool(ok), detail))

    st, h, body, dt = fetch(base, "/readyz", 30)
    add("readyz", st == 200 and dt < max_s * 3, f"{st} in {dt:.1f}s")
    st, h, body, dt = fetch(base, "/api/version", 30)
    ver = json.loads(body) if st == 200 else {}
    add("version", st == 200 and ver.get("assets") and "no-store" in h.get("cache-control", ""),
        f"{st}, commit {ver.get('commit')}, assets {ver.get('assets')}, cache {h.get('cache-control')}")
    st, h, page, dt = fetch(base, "/", 30)
    v = re.search(rb'/static/app\.js\?v=([0-9a-f]+)', page or b"")
    add("page points to the live assets", st == 200 and v and v.group(1).decode() == ver.get("assets"),
        f"{st}, page v={v.group(1).decode() if v else None}")
    if v:
        st, h, _, dt = fetch(base, f"/static/app.js?v={v.group(1).decode()}", 30)
        add("versioned app.js immutable", st == 200 and "immutable" in h.get("cache-control", ""), f"{st}, {h.get('cache-control')}")
    st, h, body, dt = fetch(base, "/api/search?q=licence%20droit", 30)
    res = json.loads(body).get("results", []) if st == 200 else []
    add("search", st == 200 and res and dt < max_s, f"{st}, {len(res)} results in {dt:.1f}s")
    if res:
        cod = res[0]["cod_aff_form"]
        # Vercel's CDN consumes s-maxage and strips it from what the client sees (Codex review): ask twice and read its
        # client-visible verdict (x-vercel-cache: HIT / STALE on the second answer); off Vercel, read Cache-Control.
        # right after a deployment the CDN may still be filling: up to RETRIES more asks, PAUSE seconds apart; an answer
        # that is never served from the cache stays red (sprint 12, first live run after PR #28)
        fetch(base, f"/api/formation/{cod}", 30)
        for attempt in range(RETRIES + 1):
            st, h, body, dt = fetch(base, f"/api/formation/{cod}", 30)
            shared = h.get("x-vercel-cache", "").upper() in ("HIT", "STALE") if "x-vercel-cache" in h else "s-maxage" in h.get("cache-control", "")
            if shared or st != 200 or attempt == RETRIES:
                break
            time.sleep(PAUSE)
        add("formation page (shared-cached)", st == 200 and dt < max_s and shared,
            f"{st} in {dt:.1f}s, x-vercel-cache {h.get('x-vercel-cache')}, {h.get('cache-control')}")
        fetch(base, f"/api/voeux?serie=bt&ids={cod}", 30)
        st, h, body, dt = fetch(base, f"/api/voeux?serie=bt&ids={cod}", 30)
        add("Mes vœux never shared-cached", st == 200 and h.get("cache-control") == "no-store"
            and h.get("x-vercel-cache", "").upper() not in ("HIT", "STALE"), f"{st}, {h.get('cache-control')}, x-vercel-cache {h.get('x-vercel-cache')}")
    st, h, body, dt = fetch(base, "/api/journey/stage2?spe1=MATHS&spe2=SES&mention=ab&type=licence%20sciences%20juridiques", 60)
    add("Mon parcours positioning", st == 200 and dt < max_s * 2, f"{st} in {dt:.1f}s")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-seconds", type=float, default=8.0)
    a = ap.parse_args(argv)
    try:
        res = checks(a.url, a.max_seconds)
    except Exception as e:  # noqa: BLE001 - an unreachable site is a failure, reported plainly
        print(f"FAIL site unreachable: {type(e).__name__}: {e}")
        return 1
    for name, ok, detail in res:
        print(("PASS " if ok else "FAIL ") + name + " - " + detail)
    return 0 if all(ok for _, ok, _ in res) else 1


if __name__ == "__main__":
    sys.exit(main())
