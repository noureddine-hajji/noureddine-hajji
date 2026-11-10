"""Sprint 10 (scale): one explicit HTTP cache policy per route.

Vercel's CDN keeps a GET response only when it carries `s-maxage`; it keys it by the full URL (path and
query) and drops it at every new deployment. The warehouse is read-only within a deployment, so a public
data answer depends only on its URL and can be served by the CDN without running the function again.

Rules (red team S1-S3):
  - a route that records an audience event, or that carries a personal list, is NEVER shared-cached
    (a CDN hit would skip the count, or keep the list): `no-store`;
  - only successful answers (200) are cached; errors are `no-store`;
  - versioned assets (`?v=` equal to the current fingerprint) are immutable for a year; anything else short;
  - every route is in the table: a new route without a policy fails the red team.
"""
from __future__ import annotations

import re

PUBLIC = "public, max-age=300, s-maxage=86400, stale-while-revalidate=86400"
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"
NO_STORE = "no-store"
# an HTML page points to the current asset fingerprint: browsers always revalidate it, the CDN keeps it for the deployment
PAGE = "public, max-age=0, must-revalidate, s-maxage=86400"

# (path pattern, policy, why); the first match wins. `None` keeps what the route sets itself.
POLICY = [
    (r"/api/search", NO_STORE, "records a search event"),
    (r"/api/e", NO_STORE, "audience beacon"),
    (r"/api/voeux", NO_STORE, "the student's personal list: never kept by a shared cache"),
    (r"/api/voeux/completer", NO_STORE, "safety vœux for the student's personal list: never kept by a shared cache"),
    (r"/api/stats", NO_STORE, "private dashboard (token)"),
    (r"/api/version", NO_STORE, "what is live right now"),
    (r"/healthz", NO_STORE, "liveness"),
    (r"/readyz", NO_STORE, "readiness"),
    (r"/", None, "the page sets no-cache itself: it points to the current asset fingerprint"),
    (r"/docs|/docs/oauth2-redirect|/redoc|/openapi\.json", SHORT, "FastAPI's API documentation"),
    (r"/formation/[^/]+", PAGE, "indexable formation page (sprint 17): kept by the CDN for one deployment, revalidated by browsers"),
    (r"/metier/[^/]+", PAGE, "indexable job page (sprint 17)"),
    (r"/sitemap\.xml", PAGE, "sitemap (sprint 17)"),
    (r"/robots\.txt", PAGE, "robots.txt (sprint 17)"),
    (r"/api/lycees", None, "sets its own day-long public cache"),
    (r"/api/meta", PUBLIC, "warehouse metadata"),
    (r"/api/formation/[^/]+", PUBLIC, "formation page data"),
    (r"/api/lineage/[^/]+", PUBLIC, "lineage"),
    (r"/api/compare", PUBLIC, "comparator (formation codes only)"),
    (r"/api/specialites", PUBLIC, "specialties"),
    (r"/api/filiere", PUBLIC, "filière"),
    (r"/api/verification", PUBLIC, "verification page"),
    (r"/api/continuity", PUBLIC, "continuity report"),
    (r"/api/journey/persona", PUBLIC, "persona"),
    (r"/api/journey/vocab", PUBLIC, "vocabulary"),
    (r"/api/journey/stage1", PUBLIC, "positioning (the audience count is sent by the page)"),
    (r"/api/journey/stage2", PUBLIC, "positioning (the audience count is sent by the page)"),
    (r"/api/planb/[^/]+", PUBLIC, "plan B for one formation and a coarse profile"),
    (r"/api/carte", PUBLIC, "map: the types of diploma and their mentions (no parameter)"),
    (r"/api/carte/formations", PUBLIC, "map: the neutral layer of a type of diploma (no profile, no position)"),
    (r"/api/carte/zones", PUBLIC, "map: zones of Mon parcours for a coarse profile (the audience count is sent by the page)"),
    (r"/api/comprendre", PUBLIC, "how far the lists were called and when the offers came, per type of diploma (no parameter)"),
    (r"/api/selectivite", PUBLIC, "selectivity matrix of a type of diploma (no profile)"),
    (r"/api/metiers", PUBLIC, "job catalogue (no parameter: searched in the browser)"),
    (r"/api/metier/[^/]+", PUBLIC, "one job and the formations preparing it"),
    (r"/static/.+", "asset", "front-end files"),
]
_COMPILED = [(re.compile(f"^{p}$"), pol, why) for p, pol, why in POLICY]


def policy(path: str) -> tuple[str | None, str] | None:
    """(policy, why) of the first matching route, or None when no route matches."""
    for rx, pol, why in _COMPILED:
        if rx.match(path):
            return pol, why
    return None


def header(method: str, path: str, query_v: str | None, status: int, current_version: str) -> str | None:
    """The Cache-Control to set, or None to leave the response as it is."""
    if method not in ("GET", "HEAD"):
        return NO_STORE
    p = policy(path)
    if p is None:
        return NO_STORE                     # unknown route (404 included): never cached
    pol = p[0]
    if pol is None:
        return None
    if status != 200:
        return NO_STORE
    if pol == "asset":
        return IMMUTABLE if query_v and query_v == current_version else SHORT
    return pol
