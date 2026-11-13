"""Sprint Q1 (owner, 2026-11-13): the contact form ("Écrire / signaler une erreur").

What is kept, and what is not (each point is checked by scripts/redteam_conformite.py):

* A message holds only what the visitor typed in the form: a type from a CLOSED list, the message (10 to 1,000 characters),
  the page and the formation code it is about (validated), and an OPTIONAL reply address. The day it was sent is added.
  No IP address, no user agent, no pseudonym, no audience event is stored with it.
* Every message expires automatically after RETENTION_DAYS (12 months, owner's choice), stored with its own expiry.
* Abuse: a hidden field that people never fill (a robot that fills it is refused), at most PER_VISITOR_DAY messages per
  daily pseudonym (the audience measurement's HMAC of day, IP and browser, kept only as a counter key for two days) and
  at most GLOBAL_DAY messages a day in all.
* Storage fails CLOSED: a message that could not be stored is an error the page shows ("non envoyé"), never a fake
  success. (Audience measurement fails open; a message is not a statistic.) On Vercel a message needs Redis: the
  instance's /tmp is wiped, so without Redis the form answers "non envoyé" (`Unavailable`).
* A visitor over their cap never consumes the global quota (checked first, atomically in Redis).
* The owner reads and deletes messages on the private dashboard (#/stats) with the stats token; the dashboard escapes them.

Storage: the audience measurement's Upstash Redis (REST) when configured, else a local SQLite file (Docker, dev, tests).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.request
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from . import analytics as A

PREFIX = "st:contact"
RETENTION_DAYS = 365
PER_VISITOR_DAY = 5
GLOBAL_DAY = 300
MAX_BODY = 4096
MSG_MIN, MSG_MAX = 10, 1000
EMAIL_MAX = 120
PAGE_MAX = 200
TYPES = {
    "erreur": "Une erreur dans un chiffre ou un texte",
    "question": "Une question sur le site",
    "suggestion": "Une suggestion",
    "autre": "Autre chose",
}
FIELDS = ("type", "message", "page", "code", "email", "site")      # "site" is the hidden field (must stay empty)
STORED = ("id", "jour", "type", "message", "page", "code", "email")
ID_RX = re.compile(r"^\d{8}-[0-9a-f]{12}$")
_CODE = re.compile(r"^\d{1,9}$")
_PAGE = re.compile(r"^/[A-Za-z0-9/#._~%-]*$")
_EMAIL = re.compile(r"^[^\s@<>\"'(),;:]{1,64}@[A-Za-z0-9.-]{1,100}\.[A-Za-z]{2,24}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


class Invalid(ValueError):
    """A form error: `field` names the field the page marks (aria-invalid), the message is said to the visitor."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


class Limited(RuntimeError):
    pass


def _text(v, cap: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Invalid("message", "Le formulaire envoyé est mal formé.")
    v = unicodedata.normalize("NFC", v).replace("\r\n", "\n").replace("\r", "\n")
    v = _CTRL.sub("", v)
    return v.strip()[: cap + 1]


def validate(payload) -> dict:
    """The stored fields of a message, or Invalid. Unknown fields are refused (closed form)."""
    if not isinstance(payload, dict) or set(payload) - set(FIELDS):
        raise Invalid("message", "Le formulaire envoyé est mal formé.")
    if _text(payload.get("site"), 200):
        raise Invalid("site", "Envoi refusé.")
    t = payload.get("type")
    if t not in TYPES:
        raise Invalid("type", "Choisissez le sujet de votre message.")
    msg = _text(payload.get("message"), MSG_MAX)
    if len(msg) < MSG_MIN:
        raise Invalid("message", f"Votre message est trop court (au moins {MSG_MIN} caractères).")
    if len(msg) > MSG_MAX:
        raise Invalid("message", f"Votre message est trop long (au plus {MSG_MAX} caractères).")
    page = _text(payload.get("page"), PAGE_MAX)
    if page and (len(page) > PAGE_MAX or not _PAGE.match(page)):
        raise Invalid("page", "La page indiquée n'est pas valable.")
    code = _text(payload.get("code"), 9)
    if code and not _CODE.match(code):
        raise Invalid("code", "Le numéro de formation n'est pas valable.")
    email = _text(payload.get("email"), EMAIL_MAX)
    if email and (len(email) > EMAIL_MAX or not _EMAIL.match(email)):
        raise Invalid("email", "Cette adresse e-mail n'est pas valable (vous pouvez aussi la laisser vide).")
    return {"type": t, "message": msg, "page": page or None, "code": code or None, "email": email or None}


# ---------------------------------------------------------------------------- storage
class Store:
    kind = "abstract"

    # counts one message against the visitor's counter FIRST; only a visitor still under its cap consumes the global
    # quota (Codex: a blocked visitor must never use up everyone's daily capacity). False when either cap is passed.
    def limit(self, visitor: tuple[str, int], everyone: tuple[str, int]) -> bool: ...
    def put(self, key: str, value: str, ttl: int) -> None: ...
    def all(self) -> list[str]: ...
    def delete(self, key: str) -> bool: ...


class SqliteStore(Store):
    kind = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS msg (k TEXT PRIMARY KEY, v TEXT, exp REAL);
                               CREATE TABLE IF NOT EXISTS rl (k TEXT PRIMARY KEY, n INTEGER, exp REAL);""")

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            yield c
        finally:
            c.close()

    def limit(self, visitor, everyone):
        now = time.time()
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM rl WHERE exp < ?", [now])
            ok = True
            for k, cap in (visitor, everyone):
                c.execute("INSERT INTO rl VALUES (?, 1, ?) ON CONFLICT (k) DO UPDATE SET n = n + 1", [k, now + 172800])
                if c.execute("SELECT n FROM rl WHERE k = ?", [k]).fetchone()[0] > cap:
                    ok = False
                    break                                           # over the visitor's cap: the global quota is not touched
            c.execute("COMMIT")
            return ok

    def put(self, key, value, ttl):
        with self._lock, self._db() as c:
            c.execute("DELETE FROM msg WHERE exp < ?", [time.time()])
            c.execute("INSERT INTO msg VALUES (?, ?, ?)", [key, value, time.time() + ttl])

    def all(self):
        with self._db() as c:
            c.execute("DELETE FROM msg WHERE exp < ?", [time.time()])
            return [v for (v,) in c.execute("SELECT v FROM msg ORDER BY k DESC")]

    def delete(self, key):
        with self._lock, self._db() as c:
            return c.execute("DELETE FROM msg WHERE k = ?", [key]).rowcount > 0

    def dump(self) -> str:
        """Everything stored, as text (the red team proves no IP, user agent or pseudonym is kept with a message)."""
        with self._db() as c:
            return "\n".join(" ".join(map(str, r)) for t in ("msg", "rl") for r in c.execute(f"SELECT * FROM {t}"))


class UpstashStore(Store):
    kind = "upstash"

    def __init__(self, url: str, token: str, timeout: float = 3.0):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, path: str, body):
        req = urllib.request.Request(f"{self.url}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - configured https URL
            return json.loads(r.read())

    # one atomic script: the visitor's counter, then (only under its cap) the global one
    LIMIT_LUA = ("local v = redis.call('INCR', KEYS[1]) redis.call('EXPIRE', KEYS[1], 172800) "
                 "if v > tonumber(ARGV[1]) then return 0 end "
                 "local g = redis.call('INCR', KEYS[2]) redis.call('EXPIRE', KEYS[2], 172800) "
                 "if g > tonumber(ARGV[2]) then return 0 end return 1")

    def limit(self, visitor, everyone):
        res = self._call("", ["EVAL", self.LIMIT_LUA, "2", visitor[0], everyone[0], str(visitor[1]), str(everyone[1])])
        return int(res.get("result") or 0) == 1

    def put(self, key, value, ttl):
        res = self._call("/pipeline", [["SET", key, value, "EX", str(ttl), "NX"]])
        if res[0].get("result") != "OK":
            raise RuntimeError("message not stored")

    def all(self):
        keys, cursor = [], "0"
        for _ in range(200):                                           # bounded: at most 200 SCAN pages
            res = self._call("", ["SCAN", cursor, "MATCH", f"{PREFIX}:msg:*", "COUNT", "500"]).get("result") or ["0", []]
            cursor, batch = str(res[0]), res[1]
            keys += batch
            if cursor == "0":
                break
        if not keys:
            return []
        keys.sort(reverse=True)
        vals = self._call("", ["MGET", *keys[:2000]]).get("result") or []
        return [v for v in vals if v]

    def delete(self, key):
        return int(self._call("", ["DEL", key]).get("result") or 0) > 0


class Unavailable(Store):
    """On Vercel without Redis: /tmp is wiped with the instance, so a message would be confirmed then lost (Codex).
    Every operation fails: the form answers 503 "non envoyé" and the dashboard says the store is unreachable."""
    kind = "indisponible"

    def _no(self, *_a, **_k):
        raise RuntimeError("no durable store for contact messages (set the Upstash / Vercel KV variables)")

    limit = put = all = delete = _no


_STORE: Store | None = None
_LOCK = threading.Lock()


def store() -> Store:
    global _STORE
    with _LOCK:
        if _STORE is None:
            url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
            tok = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
            if url and tok:
                _STORE = UpstashStore(url, tok)
            elif os.environ.get("VERCEL"):
                _STORE = Unavailable()
            else:
                from . import config
                default = config.DATA_DIR / "analytics"
                _STORE = SqliteStore(Path(os.environ.get("SUPTRACKER_ANALYTICS_DIR", default)) / "contact.sqlite")
        return _STORE


def reset_store(s: Store | None = None) -> None:
    global _STORE
    with _LOCK:
        _STORE = s


# ---------------------------------------------------------------------------- operations
def submit(payload, headers, day: date | None = None) -> str:
    """Validates, applies the limits and stores one message. Returns its id. Raises Invalid, Limited, or the store's error."""
    rec = validate(payload)
    day = day or A.today()
    vid = A.visitor_id(A.client_ip(headers), headers.get("user-agent", ""), day)
    d = day.strftime("%Y%m%d")
    s = store()
    if not s.limit((f"{PREFIX}:rl:{d}:{vid}", PER_VISITOR_DAY), (f"{PREFIX}:rl:{d}:all", GLOBAL_DAY)):
        raise Limited("Trop de messages envoyés aujourd'hui. Réessayez demain.")
    mid = f"{d}-{secrets.token_hex(6)}"
    rec = {"id": mid, "jour": day.isoformat(), **rec}
    s.put(f"{PREFIX}:msg:{mid}", json.dumps(rec, ensure_ascii=False), RETENTION_DAYS * 86400)
    return mid


def messages() -> list[dict]:
    out = []
    for v in store().all():
        try:
            r = json.loads(v)
        except (TypeError, ValueError):
            continue
        if isinstance(r, dict) and ID_RX.match(str(r.get("id", ""))):
            r = {k: r.get(k) for k in STORED}
            r["type_label"] = TYPES.get(r["type"], "Autre chose")
            out.append(r)
    return sorted(out, key=lambda r: r["id"], reverse=True)


def remove(mid: str) -> bool:
    if not ID_RX.match(mid or ""):
        raise Invalid("id", "identifiant de message invalide")
    return store().delete(f"{PREFIX}:msg:{mid}")
