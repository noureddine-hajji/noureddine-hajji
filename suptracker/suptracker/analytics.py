"""First-party, privacy-first audience measurement.

Design (each point is checked by scripts/redteam_analytics.py):

* No cookie, no client identifier, no IP address and no user agent is ever stored. A visitor is
  a daily pseudonym: HMAC(secret, day | ip | user agent), truncated, that rotates every day and
  cannot be linked across days. It is only used to count distinct visitors (HyperLogLog) and to
  de-duplicate counts.
* Only aggregated daily counters are stored, never an event log. Free text is limited to search
  queries; they are folded, emails, URLs and digit runs are masked, and a query is only shown on
  the dashboard once at least K_ANON distinct visitors typed it.
* Every client field is validated against a closed list: an unknown event, route, reason or
  referrer cannot create a new counter (bounded cardinality), and invalid payloads are only
  counted.
* Do-Not-Track / Global Privacy Control are honoured; bots are filtered; each pseudonym has a
  daily event budget; measurement fails open (an analytics error never breaks the app).

Storage: Upstash Redis over its REST API when UPSTASH_REDIS_REST_URL/TOKEN (or Vercel KV's
KV_REST_API_URL/TOKEN) are set, otherwise a local SQLite file (Docker, dev, tests). Both run the
same operations, so the dashboard reads the same structure from either.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001 - no tz database on the host: Paris winter time is close enough
    _TZ = timezone(timedelta(hours=1))

PREFIX = "st"
RETENTION_DAYS = 400            # > 1 year: a full Parcoursup cycle can be compared year on year
K_ANON = 3                      # distinct visitor-days before a query or a fiche is shown
DAILY_EVENT_BUDGET = 300        # events per pseudonym per day; the rest is counted as rate-limited
HASH_FIELD_CAP = 5000           # max distinct queries / fiches per day (cardinality bound)
MAX_BODY = 2048
MAX_QUERY = 80

ROUTES = ("home", "search", "fiche", "evolution", "compare", "specialites", "qualite", "parcours", "stats")
DEVICES = ("mobile", "tablet", "desktop")
FEEDBACK_PAGES = ("fiche", "parcours", "search")
FEEDBACK_REASONS = ("utile", "introuvable", "incomprehensible", "manque_info", "erreur_donnees", "lent")
# Traffic sources: anything else is "autre", so a spoofed referrer cannot mint counters.
REFERRERS = {
    "google": "moteur", "bing": "moteur", "qwant": "moteur", "duckduckgo": "moteur", "ecosia": "moteur",
    "yahoo": "moteur", "lilo": "moteur", "parcoursup": "parcoursup", "onisep": "onisep",
    "education": "education", "ac-": "ent", "ent": "ent", "monlycee": "ent", "pronote": "ent",
    "index-education": "ent", "facebook": "social", "instagram": "social", "tiktok": "social",
    "snapchat": "social", "linkedin": "social", "youtube": "social", "reddit": "social",
    "twitter": "social", "x": "social", "t": "social", "whatsapp": "social", "discord": "social",
}
SOURCES = ("direct", "moteur", "parcoursup", "onisep", "education", "ent", "social", "autre")
STAGES = ("search", "fiche", "out")    # funnel stages counted as distinct visitors
BOT_RX = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|python|curl|wget|httpx|"
                    r"axios|go-http|java/|monitor|uptime|pingdom|scrapy|facebookexternalhit", re.I)

# ---------------------------------------------------------------------------- privacy helpers
_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"(https?://|www\.)\S+")
_DIGITS = re.compile(r"\d[\d .-]{3,}\d|\d{5,}")


def clean_query(q: str) -> str:
    """Fold a search query and mask anything that could identify a person."""
    q = _URL.sub(" [url] ", q or "")
    q = _EMAIL.sub(" [email] ", q)
    q = _DIGITS.sub(" [num] ", q)
    q = unicodedata.normalize("NFKD", q).encode("ascii", "ignore").decode().lower()
    q = re.sub(r"[^a-z0-9\[\] '-]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:MAX_QUERY]


def today() -> date:
    return datetime.now(_TZ).date()


_SECRET = os.environ.get("SUPTRACKER_ANALYTICS_SALT", "").encode() or None
_EPHEMERAL_SECRET = secrets.token_bytes(32)


def visitor_id(ip: str, ua: str, day: date) -> str:
    """Daily pseudonym. Without a configured salt a per-process random one is used: still
    private, but the same visitor may be counted once per server instance."""
    key = _SECRET or _EPHEMERAL_SECRET
    return hmac.new(key, f"{day.isoformat()}|{ip}|{ua}".encode(), hashlib.sha256).hexdigest()[:20]


def client_ip(headers) -> str:
    # x-real-ip is set by Vercel; x-forwarded-for's first hop elsewhere (proxy-headers in Docker)
    return (headers.get("x-real-ip") or headers.get("x-forwarded-for", "").split(",")[0]).strip()


def opted_out(headers) -> bool:
    return headers.get("dnt") == "1" or headers.get("sec-gpc") == "1"


def is_bot(ua: str) -> bool:
    return not ua or bool(BOT_RX.search(ua))


def source_of(ref: str | None) -> str:
    if not ref:
        return "direct"
    host = re.sub(r"^www\.", "", str(ref).lower())[:80]
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return "autre"
    for label in host.split("."):
        for k, v in REFERRERS.items():
            if label == k or (k.endswith("-") and label.startswith(k)):
                return v
    return "autre"


# ---------------------------------------------------------------------------- storage
# One event = a list of operations, applied atomically with the per-visitor budget:
#   ("h", key, field)                  HINCRBY key field 1
#   ("p", key, member)                 PFADD key member
#   ("o", key, field, setkey, token)   HINCRBY once per token (SADD setkey token == 1),
#                                      and only while the hash has < HASH_FIELD_CAP fields
_LUA = """
local ttl = tonumber(ARGV[3])
local n = redis.call('INCR', ARGV[1])
if n == 1 then redis.call('EXPIRE', ARGV[1], 172800) end
if n > tonumber(ARGV[2]) then
  redis.call('HINCRBY', ARGV[4], 'q:ratelimited', 1); redis.call('EXPIRE', ARGV[4], ttl); return 0
end
local i = 5
while i <= #ARGV do
  local op, k, f = ARGV[i], ARGV[i+1], ARGV[i+2]
  if op == 'h' then redis.call('HINCRBY', k, f, 1); redis.call('EXPIRE', k, ttl)
  elseif op == 'p' then redis.call('PFADD', k, f); redis.call('EXPIRE', k, ttl)
  elseif op == 'o' then
    if redis.call('SADD', ARGV[i+3], ARGV[i+4]) == 1 then
      if redis.call('HEXISTS', k, f) == 1 or redis.call('HLEN', k) < %d then
        redis.call('HINCRBY', k, f, 1); redis.call('EXPIRE', k, ttl)
      end
    end
    redis.call('EXPIRE', ARGV[i+3], 172800)
  end
  i = i + 5
end
return 1
"""


def lua_script() -> str:
    return _LUA.replace("%d", str(HASH_FIELD_CAP))


def _key(*parts) -> str:
    return ":".join([PREFIX, *map(str, parts)])


class Store:
    kind = "abstract"
    persistent = True

    def apply(self, rl_key: str, day_key: str, ops: list[tuple]) -> bool: ...
    def bump(self, key: str, field: str) -> None: ...
    def hgetall_many(self, keys: list[str]) -> list[dict[str, int]]: ...
    def pfcount_many(self, groups: list[list[str]]) -> list[int]: ...  # distinct members of each union


class SqliteStore(Store):
    kind = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.persistent = not os.environ.get("VERCEL")      # /tmp on a serverless host is wiped
        self._lock = threading.Lock()
        with self._db() as c:
            c.executescript("""
              CREATE TABLE IF NOT EXISTS h (k TEXT, f TEXT, n INTEGER, exp REAL, PRIMARY KEY (k, f));
              CREATE TABLE IF NOT EXISTS s (k TEXT, m TEXT, exp REAL, PRIMARY KEY (k, m));
              CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, n INTEGER, exp REAL);""")

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            yield c
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def apply(self, rl_key, day_key, ops):
        now, ttl = time.time(), RETENTION_DAYS * 86400
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM c WHERE exp < ?", [now])
            c.execute("INSERT INTO c VALUES (?, 1, ?) ON CONFLICT (k) DO UPDATE SET n = n + 1", [rl_key, now + 172800])
            if c.execute("SELECT n FROM c WHERE k = ?", [rl_key]).fetchone()[0] > DAILY_EVENT_BUDGET:
                self._hincr(c, day_key, "q:ratelimited", now + ttl)
                c.execute("COMMIT")
                return False
            for op in ops:
                if op[0] == "h":
                    self._hincr(c, op[1], op[2], now + ttl)
                elif op[0] == "p":
                    c.execute("INSERT OR IGNORE INTO s VALUES (?, ?, ?)", [op[1], op[2], now + ttl])
                elif op[0] == "o":
                    new = c.execute("INSERT OR IGNORE INTO s VALUES (?, ?, ?)", [op[3], op[4], now + 172800]).rowcount
                    if new:
                        exists = c.execute("SELECT 1 FROM h WHERE k = ? AND f = ?", [op[1], op[2]]).fetchone()
                        size = c.execute("SELECT count(*) FROM h WHERE k = ?", [op[1]]).fetchone()[0]
                        if exists or size < HASH_FIELD_CAP:
                            self._hincr(c, op[1], op[2], now + ttl)
            if secrets.randbelow(200) == 0:                         # occasional retention sweep
                c.execute("DELETE FROM h WHERE exp < ?", [now])
                c.execute("DELETE FROM s WHERE exp < ?", [now])
            c.execute("COMMIT")
        return True

    @staticmethod
    def _hincr(c, k, f, exp):
        c.execute("INSERT INTO h VALUES (?, ?, 1, ?) ON CONFLICT (k, f) DO UPDATE SET n = n + 1, exp = ?",
                  [k, f, exp, exp])

    def bump(self, key, field):
        with self._lock, self._db() as c:
            self._hincr(c, key, field, time.time() + RETENTION_DAYS * 86400)

    def hgetall_many(self, keys):
        with self._db() as c:
            out = []
            for k in keys:
                out.append({f: n for f, n in c.execute("SELECT f, n FROM h WHERE k = ?", [k])})
            return out

    def pfcount_many(self, groups):
        with self._db() as c:
            return [c.execute(f"SELECT count(DISTINCT m) FROM s WHERE k IN ({','.join('?' * len(g))})", g).fetchone()[0]
                    if g else 0 for g in groups]

    def dump(self) -> str:
        """Everything stored, as text (used by the red team to prove no PII is kept)."""
        with self._db() as c:
            return "\n".join(" ".join(map(str, r)) for t in ("h", "s", "c") for r in c.execute(f"SELECT * FROM {t}"))


class UpstashStore(Store):
    kind = "upstash"

    def __init__(self, url: str, token: str, timeout: float = 1.5):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, path: str, body) -> list:
        req = urllib.request.Request(f"{self.url}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - configured https URL
            return json.loads(r.read())

    def apply(self, rl_key, day_key, ops):
        argv = [rl_key, str(DAILY_EVENT_BUDGET), str(RETENTION_DAYS * 86400), day_key]
        for op in ops:
            argv += list(op) + [""] * (5 - len(op))
        res = self._call("", ["EVAL", lua_script(), "0", *argv])
        return res.get("result") == 1

    def bump(self, key, field):
        self._call("/pipeline", [["HINCRBY", key, field, "1"], ["EXPIRE", key, str(RETENTION_DAYS * 86400)]])

    def hgetall_many(self, keys):
        if not keys:
            return []
        res = self._call("/pipeline", [["HGETALL", k] for k in keys])
        out = []
        for r in res:
            flat = r.get("result") or []
            out.append({flat[i]: int(flat[i + 1]) for i in range(0, len(flat), 2)})
        return out

    def pfcount_many(self, groups):
        groups = [g for g in groups]
        res = self._call("/pipeline", [["PFCOUNT", *g] for g in groups if g]) if any(groups) else []
        it = iter(res)
        return [int(next(it).get("result") or 0) if g else 0 for g in groups]


_STORE: Store | None = None
_STORE_LOCK = threading.Lock()


def store() -> Store:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
            tok = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
            if url and tok:
                _STORE = UpstashStore(url, tok)
            else:
                default = Path("/tmp/suptracker-analytics") if os.environ.get("VERCEL") else \
                    Path(__file__).resolve().parents[1] / "data" / "analytics"
                _STORE = SqliteStore(Path(os.environ.get("SUPTRACKER_ANALYTICS_DIR", default)) / "counters.sqlite")
        return _STORE


def reset_store(s: Store | None = None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = s


def enabled() -> bool:
    return os.environ.get("SUPTRACKER_ANALYTICS", "on").lower() not in ("off", "0", "false")


# ---------------------------------------------------------------------------- recording
def _day_keys(day: date) -> dict[str, str]:
    d = day.isoformat()
    return {"d": _key("d", d), "u": _key("u", d), "q": _key("q", d), "q0": _key("q0", d),
            "f": _key("f", d), "seen": _key("seen", d), "rl": _key("rl", d)}


class Rejected(ValueError):
    pass


def validate_client_event(e: dict) -> tuple[str, dict]:
    """Closed-list validation of a beacon. Returns (type, clean props) or raises Rejected."""
    if not isinstance(e, dict):
        raise Rejected("payload")
    t = e.get("t")
    if t == "view":
        r, dev = e.get("route"), e.get("device")
        if r not in ROUTES or dev not in DEVICES:
            raise Rejected("view")
        out = {"route": r, "device": dev, "source": source_of(e.get("ref")) if e.get("first") is True else None}
        cod = e.get("cod")
        if r == "fiche":
            if not (isinstance(cod, str) and cod.isdigit() and len(cod) <= 9):
                raise Rejected("cod")
            out["cod"] = cod
        return t, out
    if t == "out":
        cod = e.get("cod")
        return t, {"cod": cod if isinstance(cod, str) and cod.isdigit() and len(cod) <= 9 else None}
    if t == "feedback":
        page, vote, reason = e.get("page"), e.get("vote"), e.get("reason")
        if page not in FEEDBACK_PAGES or vote not in ("up", "down") or (reason is not None and reason not in FEEDBACK_REASONS):
            raise Rejected("feedback")
        return t, {"page": page, "vote": vote, "reason": reason}
    if t == "jserr":
        r = e.get("route")
        return t, {"route": r if r in ROUTES else "home"}
    raise Rejected("type")


def ops_for(t: str, p: dict, vid: str, day: date) -> list[tuple]:
    k = _day_keys(day)
    ops: list[tuple] = []
    h = lambda f: ops.append(("h", k["d"], f))  # noqa: E731
    if t == "view":
        h("pv"); h(f"pv:{p['route']}")
        ops.append(("p", k["u"], vid))
        ops.append(("o", k["d"], f"dev:{p['device']}", k["seen"], f"dev|{vid}"))
        if p.get("source"):
            ops.append(("o", k["d"], f"src:{p['source']}", k["seen"], f"src|{vid}"))
        if p["route"] == "fiche":
            ops.append(("p", f"{k['u']}:fiche", vid))
            ops.append(("o", k["f"], p["cod"], k["seen"], f"f|{p['cod']}|{vid}"))
    elif t == "out":
        h("out"); ops.append(("p", f"{k['u']}:out", vid))
    elif t == "feedback":
        tok = f"fb|{p['page']}|{vid}"                                  # first vote of the day wins
        ops.append(("o", k["d"], f"fb:{p['page']}:{p['vote']}", k["seen"], tok))
        if p["reason"]:
            ops.append(("o", k["d"], f"fbr:{p['reason']}", k["seen"], f"{tok}|{p['reason']}"))
    elif t == "jserr":
        ops.append(("o", k["d"], "err:js", k["seen"], f"js|{vid}|{p['route']}"))
    elif t == "search":
        h("search")
        if p["partial"]:
            h("search_partial")
        ops.append(("p", f"{k['u']}:search", vid))
        if p["q"]:
            ops.append(("o", k["q"], p["q"], k["seen"], f"q|{p['q']}|{vid}"))
            if p["total"] == 0:
                h("search_zero")
                ops.append(("o", k["q0"], p["q"], k["seen"], f"q0|{p['q']}|{vid}"))
    elif t == "refine":
        h("search_refine")
    elif t == "journey":
        h(f"journey:{p['stage']}"); ops.append(("p", f"{k['u']}:journey", vid))
    return ops


def record(t: str, props: dict, headers) -> str:
    """Record one event. Returns what happened ('ok', 'optout', 'bot', 'limited', 'off', 'error');
    never raises."""
    try:
        if not enabled():
            return "off"
        day = today()
        k = _day_keys(day)
        s = store()
        if opted_out(headers):
            s.bump(k["d"], "q:optout")
            return "optout"
        ua = headers.get("user-agent", "")
        if is_bot(ua):
            s.bump(k["d"], "q:bot")
            return "bot"
        vid = visitor_id(client_ip(headers), ua, day)
        return "ok" if s.apply(k["rl"] + ":" + vid, k["d"], ops_for(t, props, vid, day)) else "limited"
    except Exception:  # noqa: BLE001 - measurement must never break the app
        return "error"


def record_invalid(headers) -> None:
    try:
        if enabled() and not is_bot(headers.get("user-agent", "")):
            store().bump(_day_keys(today())["d"], "q:invalid")
    except Exception:  # noqa: BLE001
        pass


def record_server_error() -> None:
    try:
        if enabled():
            store().bump(_day_keys(today())["d"], "err:server")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if not n:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def two_prop_p(k1: int, n1: int, k2: int, n2: int) -> float | None:
    """Two-sided p-value of a two-proportion z-test (None when undefined)."""
    if not n1 or not n2:
        return None
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    return math.erfc(abs(k1 / n1 - k2 / n2) / se / math.sqrt(2))


def poisson_p(a: int, b: int) -> float | None:
    """Two-sided test that two equal-length periods share a rate (conditional binomial,
    normal approximation): is a change in a count more than noise?"""
    n = a + b
    if n < 10:
        return None
    return math.erfc(abs(a - n / 2) / math.sqrt(n / 4) / math.sqrt(2))


def holm(kpis: list[dict], alpha: float = 0.05) -> None:
    """Holm-Bonferroni across the KPIs tested together: six tests at 5 % would otherwise flag a
    'significant' change by chance in about one period out of four."""
    tested = sorted((k for k in kpis if k["p"] is not None and not k["low_n"]), key=lambda k: k["p"])
    m, stop = len(tested), False
    for k in kpis:
        k["significant"], k["p_adj"] = False, None
    for i, k in enumerate(tested):
        k["p_adj"] = min(1.0, k["p"] * (m - i))
        if not stop and k["p"] <= alpha / (m - i):
            k["significant"] = True
        else:
            stop = True


# Parcoursup calendar (indicative dates, repeated every year): what traffic should follow
PHASES = [
    ((12, 17), (1, 14), "Découverte des formations"),
    ((1, 15), (3, 13), "Formulation des vœux"),
    ((3, 14), (4, 2), "Confirmation des vœux"),
    ((6, 1), (7, 11), "Phase d'admission principale"),
    ((7, 12), (9, 12), "Phase complémentaire"),
]


def phase_of(d: date) -> str | None:
    md = (d.month, d.day)
    for a, b, name in PHASES:
        if (a <= md <= b) if a <= b else (md >= a or md <= b):
            return name
    return None


def _sum(dicts: list[dict], prefix: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for f, n in d.items():
            if prefix is None or f.startswith(prefix):
                out[f] = out.get(f, 0) + int(n)
    return out


def summarize(days: int = 30, end: date | None = None, labels=None) -> dict:
    """Dashboard payload for the last `days` days and the period just before (for deltas).
    `labels(cods) -> {cod: {...}}` names the most viewed formations."""
    s = store()
    end = end or today()
    cur = [end - timedelta(days=i) for i in range(days - 1, -1, -1)]
    prev = [d - timedelta(days=days) for d in cur]
    K = {d: _day_keys(d) for d in cur + prev}
    keys = []
    for d in cur + prev:
        keys += [K[d]["d"], K[d]["q"], K[d]["q0"], K[d]["f"]]
    got = s.hgetall_many(keys)
    H = {k: v for k, v in zip(keys, got)}

    def grp(ds, stage=""):
        return [K[d]["u"] + (f":{stage}" if stage else "") for d in ds]

    groups = {f"day:{d}": [K[d]["u"]] for d in cur}
    for per, ds in (("cur", cur), ("prev", prev)):
        groups[f"{per}:"] = grp(ds)
        for st in (*STAGES, "journey"):
            groups[f"{per}:{st}"] = grp(ds, st)
    names = list(groups)
    U = dict(zip(names, s.pfcount_many([groups[n] for n in names])))

    def uniq(ds, stage=""):
        return U[f"{'cur' if ds is cur else 'prev'}:{stage}"]

    daily = []
    for d in cur:
        c = H[K[d]["d"]]
        daily.append({"day": d.isoformat(), "visitors": U[f"day:{d}"], "pageviews": c.get("pv", 0),
                      "searches": c.get("search", 0), "zero": c.get("search_zero", 0), "phase": phase_of(d)})
    C, P = _sum([H[K[d]["d"]] for d in cur]), _sum([H[K[d]["d"]] for d in prev])

    def kpi(name, a, b, unit="n", k=None, n=None, kb=None, nb=None, good="up"):
        out = {"name": name, "value": a, "previous": b, "unit": unit, "good": good}
        if unit == "rate":
            out["ci"] = wilson(k, n)
            out["n"] = n
            out["p"] = two_prop_p(k, n, kb, nb)
            out["low_n"] = n < 30
        else:
            out["p"] = poisson_p(a or 0, b or 0)
            out["low_n"] = (a or 0) + (b or 0) < 10
        return out

    v_cur, v_prev = uniq(cur), uniq(prev)
    srch, srch_p = C.get("search", 0), P.get("search", 0)
    z, z_p = C.get("search_zero", 0), P.get("search_zero", 0)
    up = sum(n for f, n in C.items() if f.startswith("fb:") and f.endswith(":up"))
    fb = sum(n for f, n in C.items() if f.startswith("fb:"))
    up_p = sum(n for f, n in P.items() if f.startswith("fb:") and f.endswith(":up"))
    fb_p = sum(n for f, n in P.items() if f.startswith("fb:"))
    out_u, out_u_p = uniq(cur, "out"), uniq(prev, "out")
    kpis = [
        kpi("Visiteurs uniques (visiteurs-jours)", v_cur, v_prev),
        kpi("Pages vues", C.get("pv", 0), P.get("pv", 0)),
        kpi("Recherches", srch, srch_p),
        kpi("Recherches sans résultat", z / srch if srch else None, z_p / srch_p if srch_p else None, "rate",
            z, srch, z_p, srch_p, good="down"),
        kpi("Avis positifs", up / fb if fb else None, up_p / fb_p if fb_p else None, "rate", up, fb, up_p, fb_p),
        kpi("Visiteurs allant sur Parcoursup", out_u / v_cur if v_cur else None, out_u_p / v_prev if v_prev else None,
            "rate", out_u, v_cur, out_u_p, v_prev),
    ]

    holm(kpis)

    funnel = [{"stage": "Visite", "visitors": v_cur}]
    for st, lab in (("search", "Recherche"), ("fiche", "Fiche consultée"), ("out", "Clic vers Parcoursup")):
        funnel.append({"stage": lab, "visitors": uniq(cur, st)})

    def top(kind, n=25):
        agg = _sum([H[K[d][kind]] for d in cur])
        return [{"key": f, "visitor_days": c} for f, c in sorted(agg.items(), key=lambda x: (-x[1], x[0]))
                if c >= K_ANON][:n], sum(1 for c in agg.values() if c < K_ANON)

    tq, tq_hidden = top("q")
    zq, zq_hidden = top("q0")
    tf, tf_hidden = top("f", 15)
    if labels and tf:
        names = labels([x["key"] for x in tf])
        for x in tf:
            x.update(names.get(x["key"], {}))

    feedback = []
    for pg in FEEDBACK_PAGES:
        u, dn = C.get(f"fb:{pg}:up", 0), C.get(f"fb:{pg}:down", 0)
        lo, hi = wilson(u, u + dn)
        feedback.append({"page": pg, "up": u, "down": dn, "share_up": u / (u + dn) if u + dn else None,
                         "ci": [lo, hi], "low_n": u + dn < 30})
    reasons = {r: C.get(f"fbr:{r}", 0) for r in FEEDBACK_REASONS}
    routes = {r: C.get(f"pv:{r}", 0) for r in ROUTES}
    devices = {d: C.get(f"dev:{d}", 0) for d in DEVICES}
    sources = {x: C.get(f"src:{x}", 0) for x in SOURCES}
    journey = {st: C.get(f"journey:{st}", 0) for st in ("stage1", "stage2")}
    quality = {"bots_filtered": C.get("q:bot", 0), "opt_out": C.get("q:optout", 0),
               "invalid": C.get("q:invalid", 0), "rate_limited": C.get("q:ratelimited", 0),
               "js_errors": C.get("err:js", 0), "server_errors": C.get("err:server", 0),
               "hidden_queries": tq_hidden, "hidden_zero_queries": zq_hidden, "hidden_fiches": tf_hidden}
    res = {
        "period": {"start": cur[0].isoformat(), "end": end.isoformat(), "days": days,
                   "previous_start": prev[0].isoformat(), "previous_end": prev[-1].isoformat()},
        "store": {"kind": s.kind, "persistent": s.persistent, "salt_configured": _SECRET is not None},
        "k_anon": K_ANON, "kpis": kpis, "daily": daily, "funnel": funnel, "top_queries": tq,
        "zero_queries": zq, "top_fiches": tf, "feedback": feedback, "reasons": reasons, "routes": routes,
        "devices": devices, "sources": sources, "journey": journey, "quality": quality,
        "phases": [{"start": f"{a[0]:02d}-{a[1]:02d}", "end": f"{b[0]:02d}-{b[1]:02d}", "name": n} for a, b, n in PHASES],
    }
    res["insights"] = insights(res)
    return res


def insights(r: dict) -> list[dict]:
    """Plain-language findings, each with the evidence behind it and the action it calls for."""
    out = []
    K = {k["name"]: k for k in r["kpis"]}
    vis = K["Visiteurs uniques (visiteurs-jours)"]
    if not vis["value"]:
        return [{"level": "info", "text": "Aucune visite mesurée sur la période.",
                 "action": "Vérifiez que la mesure est active (SUPTRACKER_ANALYTICS) et que le stockage est persistant."}]
    if not r["store"]["persistent"]:
        out.append({"level": "warn", "text": "Le stockage des mesures est éphémère (serveur sans disque persistant) : "
                    "les chiffres repartent de zéro à chaque redémarrage.",
                    "action": "Connectez Upstash Redis (Vercel → Storage) : UPSTASH_REDIS_REST_URL et _TOKEN."})
    if not r["store"]["salt_configured"]:
        out.append({"level": "warn", "text": "Pas de sel configuré : un même visiteur peut être compté une fois par instance du serveur.",
                    "action": "Définissez SUPTRACKER_ANALYTICS_SALT (une valeur aléatoire longue, gardée secrète)."})
    for k in r["kpis"]:
        if k["significant"] and k["previous"]:
            rise = (k["value"] or 0) > k["previous"]
            good = rise == (k["good"] == "up")
            pval = "p < 0,001" if k["p"] < 0.001 else f"p = {k['p']:.3f}".replace(".", ",")
            val = (lambda v: f"{100 * v:.1f} %".replace(".", ",")) if k["unit"] == "rate" else (lambda v: f"{v:,}".replace(",", " "))
            out.append({"level": "good" if good else "bad",
                        "text": f"{k['name']} : {val(k['value'])} contre {val(k['previous'])} sur la période précédente "
                                f"(variation significative, {pval}).",
                        "action": None if good else "Cherchez la cause dans les recherches sans résultat et les avis négatifs."})
    zk = K["Recherches sans résultat"]
    if zk["value"] is not None and zk["n"] >= 30 and zk["ci"][0] > 0.05:
        out.append({"level": "bad", "text": f"Au moins {100 * zk['ci'][0]:.0f} % des recherches ne trouvent rien (borne basse de l'IC 95 %).",
                    "action": "Ajoutez les requêtes les plus fréquentes du tableau « sans résultat » au gold set de la recherche, puis corrigez-les."})
    f = r["funnel"]
    if f[0]["visitors"] >= 30 and f[1]["visitors"] / f[0]["visitors"] < 0.4:
        out.append({"level": "bad", "text": f"Seuls {100 * f[1]['visitors'] / f[0]['visitors']:.0f} % des visiteurs lancent une recherche.",
                    "action": "Rendez la recherche plus visible sur l'accueil (exemples de requêtes cliquables)."})
    worst = [x for x in r["feedback"] if not x["low_n"] and x["ci"][1] is not None and x["ci"][1] < 0.6]
    for x in worst:
        out.append({"level": "bad", "text": f"Page « {x['page']} » : moins de 60 % d'avis positifs (IC 95 % {100 * x['ci'][0]:.0f}–{100 * x['ci'][1]:.0f} %).",
                    "action": "Lisez les motifs d'avis négatifs et testez la page avec 3 élèves."})
    q = r["quality"]
    tot = vis["value"] + q["bots_filtered"]
    if q["js_errors"] and q["js_errors"] / max(1, vis["value"]) > 0.02:
        out.append({"level": "bad", "text": f"{q['js_errors']} erreurs JavaScript pour {vis['value']} visiteurs-jours.",
                    "action": "Reproduisez sur mobile (le navigateur le plus fréquent) et corrigez avant toute nouvelle fonctionnalité."})
    if tot and q["bots_filtered"] / tot > 0.5:
        out.append({"level": "info", "text": f"{q['bots_filtered']} requêtes de robots ont été écartées des chiffres.", "action": None})
    if not out:
        out.append({"level": "info", "text": "Aucune variation significative ni signal d'alerte sur la période.", "action": None})
    return out
