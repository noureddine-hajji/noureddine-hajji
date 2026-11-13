"""Sprint Q2 (owner, 2026-11-13): security headers, HEAD requests, and the contact form's cross-site guard.

One definition, applied by one middleware in api.py to EVERY answer (errors included). Each rule is checked by
scripts/redteam_securite.py:

* Content-Security-Policy: the pages load scripts, fonts and data from the site only, images from the site, `data:` URIs
  and the map's tile host (app.js CARTE_TILES, the only third party a page contacts: privacy page, red team QC2). Styles
  allow inline `style="…"` attributes (the page templates use them; scripts never). No object, no frame of the site
  elsewhere (`frame-ancestors 'none'`), no `<base>` from elsewhere, forms only to the site. FastAPI's own API
  documentation pages (/docs, /redoc) load their viewer from a CDN: they get their own, wider policy, still unframeable.
* X-Content-Type-Options nosniff, Referrer-Policy strict-origin-when-cross-origin (other sites see the site's origin only,
  never which formation was read; OpenStreetMap's tile policy needs that origin), Permissions-Policy (no camera,
  microphone, geolocation, payment, USB: the town filter runs on a typed town), X-Frame-Options DENY (older browsers),
  Cross-Origin-Opener-Policy same-origin, and Strict-Transport-Security on HTTPS only.
* HEAD: every GET route answers HEAD with the same status and headers and no body (monitors and crawlers send HEAD;
  FastAPI answered 405). The search is the exception: it records an audience event, so a HEAD is never turned into one.
* The contact form refuses a post another site makes in the visitor's browser (Sec-Fetch-Site cross-site, or an Origin
  that is not this site) and any body that is not JSON (a cross-site HTML form cannot send application/json without a
  CORS preflight, which this site never grants).
"""
from __future__ import annotations

from urllib.parse import urlsplit

TILE_HOST = "tile.openstreetmap.org"           # app.js CARTE_TILES (red team SE2 reads it from the page code)

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    f"img-src 'self' data: https://{TILE_HOST}",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "worker-src 'none'",
    "manifest-src 'self'",
])
# FastAPI's /docs (Swagger UI) and /redoc load their viewer from jsDelivr with an inline start-up script
CSP_DOCS = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
    "font-src 'self' https://fonts.gstatic.com",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
])
DOCS_PATHS = ("/docs", "/docs/oauth2-redirect", "/redoc")
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HSTS = "max-age=31536000"
NO_HEAD = ("/api/search",)                     # GET routes whose answer records an audience event


def headers_for(path: str, https: bool) -> dict:
    """The security headers of one answer."""
    h = dict(HEADERS)
    h["Content-Security-Policy"] = CSP_DOCS if path in DOCS_PATHS else CSP
    if https:
        h["Strict-Transport-Security"] = HSTS
    return h


def is_https(scope_scheme: str, headers) -> bool:
    return scope_scheme == "https" or (headers.get("x-forwarded-proto") or "").split(",")[0].strip() == "https"


def head_as_get(path: str) -> bool:
    return path not in NO_HEAD


def cross_site(headers, host: str | None) -> bool:
    """True when the browser says another site sent the request (Sec-Fetch-Site), or the Origin is another host."""
    if (headers.get("sec-fetch-site") or "").lower() == "cross-site":
        return True
    origin = headers.get("origin")
    if origin is None:
        return False                           # not a browser form or fetch from another page (curl, a monitor)
    if origin == "null":
        return True                            # sandboxed frame or file: never this site
    o = urlsplit(origin).netloc.lower()
    return not host or o != host.lower()


def json_body(headers) -> bool:
    return (headers.get("content-type") or "").split(";")[0].strip().lower() == "application/json"
