"""Red team of the audience measurement: privacy, abuse resistance, correctness, availability.

Each check attacks one promise made in suptracker/analytics.py and fails loudly if it breaks.

    python scripts/redteam_analytics.py --db data/suptracker.duckdb      # or any built warehouse
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOKEN = "rt-" + "x" * 29
UA = "Mozilla/5.0 (X11; Linux x86_64) RedTeam/1.0"


class Harness:
    def __init__(self, db: Path):
        os.environ["SUPTRACKER_DB"] = str(db)
        os.environ["SUPTRACKER_STATS_TOKEN"] = TOKEN
        os.environ.pop("UPSTASH_REDIS_REST_URL", None)
        os.environ.pop("KV_REST_API_URL", None)
        from fastapi.testclient import TestClient

        from suptracker import analytics as A
        from suptracker import api
        self.A, self.api = A, api
        api._con.cache_clear()
        self.client = TestClient(api.app)
        self.fresh()

    def fresh(self):
        self.dir = tempfile.mkdtemp(prefix="st-analytics-")
        self.store = self.A.SqliteStore(Path(self.dir) / "c.sqlite")
        self.A.reset_store(self.store)
        return self.store

    def h(self, ip="203.0.113.7", ua=UA, **extra):
        return {"user-agent": ua, "x-real-ip": ip, **extra}

    def ev(self, payload, **hdr):
        import json
        return self.client.post("/api/e", content=json.dumps(payload) if not isinstance(payload, (bytes, str)) else payload,
                                headers=self.h(**hdr))

    def counters(self) -> dict:
        d = self.A._day_keys(self.A.today())
        return self.store.hgetall_many([d["d"]])[0]

    def stats(self, days=7):
        return self.client.get(f"/api/stats?days={days}", headers={"Authorization": f"Bearer {TOKEN}"}).json()


def check(name):
    def deco(fn):
        fn.check_name = name
        return fn
    return deco


VIEW = {"t": "view", "route": "home", "device": "mobile"}


@check("R1 oversized payloads are refused before parsing")
def r1(H):
    r = H.ev("x" * 5000)
    return r.status_code == 413, f"status {r.status_code}"


@check("R2 closed lists: unknown type/route/device/reason/cod is rejected and only counted")
def r2(H):
    H.fresh()
    bad = [{"t": "admin"}, {**VIEW, "route": "../etc"}, {**VIEW, "device": "fridge"},
           {"t": "feedback", "page": "fiche", "vote": "up", "reason": "<img onerror=1>"},
           {"t": "view", "route": "fiche", "device": "mobile", "cod": "1 OR 1=1"}, "not json", [], None]
    codes = [H.ev(b).status_code for b in bad]
    c = H.counters()
    ok = all(x == 422 for x in codes) and c == {"q:invalid": len(bad)}
    return ok, f"codes {codes}, stored {c}"


@check("R3 unknown fields never reach storage (no free text but the masked query)")
def r3(H):
    H.fresh()
    H.ev({**VIEW, "email": "eleve@lycee.fr", "name": "Camille Martin", "ref": "evil.example/<script>", "first": True})
    dump = H.store.dump()
    leaked = [s for s in ("eleve@lycee.fr", "Camille", "evil", "<script>") if s.lower() in dump.lower()]
    return not leaked, f"leaked {leaked}" if leaked else "only closed-list counters stored"


@check("R4 no IP, no user agent, no email, phone or address digits are stored")
def r4(H):
    H.fresh()
    q = "jean.dupont@gmail.com 06 12 34 56 78 droit 18 rue de la Paix 75011 https://x.io/a?b=c"
    H.client.get("/api/search", params={"q": q}, headers=H.h(ip="198.51.100.23"))
    H.ev(VIEW, ip="198.51.100.23")
    dump = H.store.dump()
    leaked = [s for s in ("198.51.100.23", "RedTeam", "Mozilla", "@", "gmail", "0612", "06 12", "75011", "x.io")
              if s.lower() in dump.lower()]
    stored_q = [ln for ln in dump.splitlines() if ln.startswith("st:q:")]
    return not leaked and stored_q, f"leaked {leaked}; stored query rows {stored_q}"


@check("R5 Do-Not-Track and Global Privacy Control are honoured")
def r5(H):
    H.fresh()
    H.ev(VIEW, dnt="1")
    H.ev(VIEW, **{"sec-gpc": "1"})
    H.client.get("/api/search", params={"q": "droit"}, headers=H.h(dnt="1"))
    c = H.counters()
    return c == {"q:optout": 3}, f"stored {c}"


@check("R6 bots and scripts are filtered out of every metric")
def r6(H):
    H.fresh()
    for ua in ("Mozilla/5.0 (compatible; Googlebot/2.1)", "curl/8.4", "python-requests/2.32", "HeadlessChrome/120", ""):
        H.ev(VIEW, ua=ua)
    c = H.counters()
    return c == {"q:bot": 5}, f"stored {c}"


@check("R7 per-visitor daily budget stops counter inflation")
def r7(H):
    H.fresh()
    A = H.A
    old = A.DAILY_EVENT_BUDGET
    A.DAILY_EVENT_BUDGET = 40
    try:
        for _ in range(60):
            H.ev(VIEW, ip="192.0.2.50")
        c = H.counters()
    finally:
        A.DAILY_EVENT_BUDGET = old
    return c.get("pv") == 40 and c.get("q:ratelimited") == 20, f"pv {c.get('pv')}, limited {c.get('q:ratelimited')}"


@check("R8 k-anonymity counts distinct visitors: repetition by one visitor cannot reveal a query")
def r8(H):
    H.fresh()
    for _ in range(50):
        H.client.get("/api/search", params={"q": "zzqx rare one"}, headers=H.h(ip="192.0.2.1"))
    for ip in ("192.0.2.1", "192.0.2.2"):
        H.client.get("/api/search", params={"q": "zzqx two people"}, headers=H.h(ip=ip))
    for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        H.client.get("/api/search", params={"q": "zzqx three people"}, headers=H.h(ip=ip))
    s = H.stats()
    shown = {r["key"]: r["visitor_days"] for r in s["zero_queries"]}
    ok = shown == {"zzqx three people": 3} and s["quality"]["hidden_zero_queries"] == 2
    return ok, f"shown {shown}, hidden {s['quality']['hidden_zero_queries']}"


@check("R9 dashboard: disabled without a strong token, 401 on a wrong one, never cached, no token in URL")
def r9(H):
    c = H.client
    os.environ["SUPTRACKER_STATS_TOKEN"] = "short"
    weak = c.get("/api/stats", headers={"Authorization": "Bearer short"}).status_code
    os.environ["SUPTRACKER_STATS_TOKEN"] = TOKEN
    none = c.get("/api/stats").status_code
    wrong = c.get("/api/stats", headers={"Authorization": "Bearer " + TOKEN[:-1] + "y"}).status_code
    in_url = c.get(f"/api/stats?token={TOKEN}").status_code
    good = c.get("/api/stats", headers={"Authorization": f"Bearer {TOKEN}"})
    ok = (weak, none, wrong, in_url, good.status_code) == (503, 401, 401, 401, 200) and \
        good.headers.get("cache-control") == "no-store"
    cc = good.headers.get("cache-control")
    return ok, f"weak {weak}, none {none}, wrong {wrong}, url {in_url}, good {good.status_code} {cc}"


@check("R10 bounded cardinality: a flood of distinct queries cannot grow storage without limit")
def r10(H):
    H.fresh()
    A = H.A
    old = A.HASH_FIELD_CAP
    A.HASH_FIELD_CAP = 30
    try:
        for i in range(80):
            A.record("search", {"q": f"flood {i}", "total": 0, "partial": False}, H.h(ip=f"10.0.{i // 250}.{i % 250}"))
        k = A._day_keys(A.today())
        n = len(H.store.hgetall_many([k["q0"]])[0])
    finally:
        A.HASH_FIELD_CAP = old
    return n == 30, f"{n} distinct zero-result queries stored (cap 30)"


@check("R11 spoofed referrers cannot mint new source counters")
def r11(H):
    H.fresh()
    for i in range(40):
        H.ev({**VIEW, "first": True, "ref": f"spam{i}.example"}, ip=f"10.1.0.{i}")
    H.ev({**VIEW, "first": True, "ref": "www.google.fr"}, ip="10.1.1.1")
    H.ev({**VIEW, "first": True, "ref": "ent.ac-lyon.fr"}, ip="10.1.1.2")
    src = {f: n for f, n in H.counters().items() if f.startswith("src:")}
    return src == {"src:autre": 40, "src:moteur": 1, "src:ent": 1}, f"{src}"


@check("R12 fail-open: a broken analytics store never breaks the app")
def r12(H):
    class Broken(H.A.Store):
        kind = "broken"

        def apply(self, *a):
            raise OSError("down")
        bump = hgetall_many = pfcount_many = apply
    H.A.reset_store(Broken())
    try:
        s = H.client.get("/api/search", params={"q": "droit"}, headers=H.h()).status_code
        e = H.ev(VIEW).status_code
        b = H.ev({"t": "nope"}).status_code
        d = H.client.get("/api/stats", headers={"Authorization": f"Bearer {TOKEN}"}).status_code
    finally:
        H.fresh()
    return (s, e, b, d) == (200, 204, 422, 502), f"search {s}, event {e}, invalid {b}, dashboard {d}"


@check("R13 pseudonyms rotate daily and differ across visitors")
def r13(H):
    A = H.A
    d0, d1 = date(2026, 1, 20), date(2026, 1, 21)
    a, b, c = A.visitor_id("1.2.3.4", UA, d0), A.visitor_id("1.2.3.4", UA, d1), A.visitor_id("1.2.3.5", UA, d0)
    ok = a == A.visitor_id("1.2.3.4", UA, d0) and len({a, b, c}) == 3 and "1.2.3.4" not in a
    return ok, "stable within a day, unlinkable across days"


@check("R14 ballot stuffing: one visitor's repeated votes count once per page and day")
def r14(H):
    H.fresh()
    for v in ("up", "down", "up", "down", "down"):
        H.ev({"t": "feedback", "page": "fiche", "vote": v, "reason": None}, ip="10.9.9.9")
    H.ev({"t": "feedback", "page": "fiche", "vote": "down", "reason": None}, ip="10.9.9.8")
    c = {f: n for f, n in H.counters().items() if f.startswith("fb:")}
    return c == {"fb:fiche:up": 1, "fb:fiche:down": 1}, f"{c}"


@check("R15 dashboard never injects stored text as HTML (static check + mutation test)")
def r15(H):
    src = (ROOT / "suptracker" / "static" / "stats.js").read_text()
    # innermost interpolations only; one that touches a stored text field must go through esc()
    risky = re.compile(r"\$\{(?!esc\(|fmt\(|pc\(|encodeURIComponent\()[^${}`]*\.(?:key|etablissement|filiere|ville|text|action|phase|name|message)\b[^${}`]*\}")

    def bad(code):
        return [m.group(0) for ln in code.splitlines() if "textContent" not in ln for m in risky.finditer(ln)]
    found = bad(src)
    mutant = src.replace("<td>${esc(r.key)}</td>", "<td>${r.key}</td>", 1)
    caught = bool(bad(mutant)) and mutant != src
    return not found and caught, f"unescaped {found[:3]}; mutation caught: {caught}"


@check("R16 measurement overhead on /api/search stays small")
def r16(H):
    c = H.client

    def one(i, on):
        if on:
            os.environ.pop("SUPTRACKER_ANALYTICS", None)
        else:
            os.environ["SUPTRACKER_ANALYTICS"] = "off"
        t0 = time.perf_counter()
        c.get("/api/search", params={"q": f"licence droit {i % 3}"}, headers=H.h(ip=f"10.3.{i // 250}.{i % 250}"))
        return 1000 * (time.perf_counter() - t0)
    for i in range(5):
        one(i, True)
    # interleaved pairs: machine noise hits both arms alike, the paired difference isolates the overhead
    diffs = [one(2 * i, True) - one(2 * i + 1, False) for i in range(40)]
    os.environ.pop("SUPTRACKER_ANALYTICS", None)
    d = statistics.median(diffs)
    return d < 10, f"median paired overhead {d:+.1f} ms per search"


@check("R17 the Redis (Upstash) path computes exactly what the SQLite path computes")
def r17(H):
    try:
        import fakeredis  # noqa: F401
        import lupa  # noqa: F401
    except ImportError:
        return None, "skipped: pip install fakeredis lupa"
    import fakeredis
    A = H.A
    r = fakeredis.FakeRedis(decode_responses=True)

    class FakeUpstash(A.UpstashStore):
        def __init__(self):
            super().__init__("https://fake", "t")

        def _call(self, path, body):
            if path == "/pipeline":
                return [{"result": _norm(r.execute_command(*cmd))} for cmd in body]
            return {"result": _norm(r.execute_command(*body))}

    def _norm(x):
        if isinstance(x, dict):
            return [v for kv in x.items() for v in kv]
        return x

    def scenario():
        for i in range(12):
            ip = f"10.7.0.{i % 5}"
            A.record("view", {"route": "fiche" if i % 2 else "search", "device": "mobile", "source": "moteur", "cod": "123"}, H.h(ip=ip))
            A.record("search", {"q": f"q{i % 4}", "total": i % 2, "partial": bool(i % 3)}, H.h(ip=ip))
            A.record("feedback", {"page": "fiche", "vote": "up" if i % 3 else "down", "reason": None}, H.h(ip=ip))
            A.record("out", {"cod": "123"}, H.h(ip=ip))
        A.record("view", {"route": "home", "device": "mobile", "source": None}, H.h(dnt="1"))
        A.record("view", {"route": "home", "device": "mobile", "source": None}, H.h(ua="Googlebot"))
        return A.summarize(7)

    H.fresh()
    a = scenario()
    A.reset_store(FakeUpstash())
    try:
        b = scenario()
    finally:
        H.fresh()
    for x in (a, b):
        x.pop("store")
        x.pop("insights")
    return a == b, "identical dashboards" if a == b else "dashboards differ"


@check("R18 statistics: Wilson interval, two-proportion and count tests, Holm correction")
def r18(H):
    A = H.A
    lo, hi = A.wilson(50, 100)
    ok = abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3 and A.wilson(0, 0) == (None, None)
    ok &= A.two_prop_p(50, 100, 50, 100) == 1.0 and A.two_prop_p(80, 100, 50, 100) < 0.001
    ok &= A.poisson_p(5, 3) is None and A.poisson_p(100, 100) == 1.0 and A.poisson_p(150, 100) < 0.01
    ks = [{"p": p, "low_n": False} for p in (0.001, 0.02, 0.03, 0.04, 0.2, None)]
    ks[-1]["low_n"] = True
    A.holm(ks)
    ok &= [k["significant"] for k in ks] == [True, False, False, False, False, False]   # 0.02 > 0.05/4
    return ok, f"wilson(50/100) = [{lo:.4f}; {hi:.4f}]; Holm keeps 1 of 4 raw p < 0.05"


@check("R19 an empty period renders without error and says so")
def r19(H):
    H.fresh()
    s = H.stats(30)
    return s["kpis"][0]["value"] == 0 and "Aucune visite" in s["insights"][0]["text"], s["insights"][0]["text"]


@check("R20 the dashboard API is a GET with no side effect, and the beacon endpoint has no GET")
def r20(H):
    H.fresh()
    H.stats()
    H.stats()
    get_e = H.client.get("/api/e").status_code
    return H.counters() == {} and get_e == 405, f"counters after 2 dashboard reads {H.counters()}, GET /api/e {get_e}"


@check("R21 without proxy headers, visitors are told apart by their socket address (unforgeable)")
def r21(H):
    A = H.A
    a = A.client_ip({A.PEER_KEY: "192.0.2.10"})
    b = A.client_ip({"x-real-ip": "198.51.100.1", A.PEER_KEY: "192.0.2.10"})
    req = type("R", (), {"headers": {A.PEER_KEY: "6.6.6.6"}, "client": type("C", (), {"host": "192.0.2.99"})()})()
    forged = H.api._hdrs(req)[A.PEER_KEY]
    return (a, b, forged) == ("192.0.2.10", "198.51.100.1", "192.0.2.99"), f"peer {a}, proxied {b}, forged peer -> {forged}"


CHECKS = [r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, r13, r14, r15, r16, r17, r18, r19, r20, r21]


def run(db: Path) -> list[dict]:
    H = Harness(db)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(H)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": ok is not False, "skipped": ok is None, "detail": detail})
    H.A.reset_store(None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(a.db)
    for r in res:
        print(("SKIP " if r["skipped"] else "PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
