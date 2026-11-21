"""Load test before the January-March peak (sprint 3 « Solidité avant le pic », owner 2026-11-21).

Hundreds of virtual visitors at once, each running a real student's visit against ONE server process on the committed
warehouse (a Vercel instance runs one such process; the CDN serves the shared-cached answers before they reach it, so this
measures the worst case: every request reaches the server). Each visitor, after a short random pause:
  home page -> /api/meta -> the search page's layer (/api/carte/couche) -> a keyword search -> a formation page
  (/api/formation + its indexable page) -> its zones for a profile (/api/journey/stage2) -> Mes vœux (/api/voeux) -> the
  motivation-letter page (/api/projet) -> a job page (/api/metier).
Codes, profiles and words are drawn at random (seeded) among the latest campaign's formations, real specialty pairs and
common words. Nothing is sent outside this machine: the server runs here (127.0.0.1), with no analytics store (fail-open).

Prints, per route: requests, errors, median, 95th percentile and slowest time; the throughput; exits 1 on any error (an
answer >= 500, a timeout, a refused connection). Usage:
  python scripts/charge.py [--visiteurs 50] [--seed 1] [--db data/suptracker.duckdb] [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = ("licence droit", "bts", "infirmier", "informatique", "psychologie", "cpge", "but gea", "commerce", "staps", "médecine",
         "architecture", "langues", "biologie", "économie", "design", "comptabilité", "mathématiques", "histoire")
PAIRS = (("MATHS", "PC"), ("MATHS", "SES"), ("SES", "HGGSP"), ("SVT", "PC"), ("MATHS", "NSI"), ("HLP", "LLCER"), ("SVT", "SES"))
MENTIONS = ("sansmention", "ab", "b", "tb")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sample(db: Path, n: int, seed: int) -> dict:
    import duckdb
    con = duckdb.connect(str(db), read_only=True)
    try:
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        rows = con.execute("""SELECT fy.cod_aff_form, r.spe_type_key FROM core.formation_year fy
            JOIN core.taxonomy_link t USING (session, cod_aff_form) JOIN core.taxonomy_rule r USING (rule_id)
            WHERE fy.session = ? ORDER BY fy.cod_aff_form""", [latest]).fetchall()
        mets = [m for (m,) in con.execute("SELECT met_id FROM core.onisep_metier ORDER BY met_id").fetchall()]
    finally:
        con.close()
    rnd = random.Random(seed)
    return {"forms": rnd.sample(rows, min(n, len(rows))), "mets": rnd.sample(mets, min(n, len(mets))) if mets else []}


def visit(rnd: random.Random, s: dict) -> list[tuple[str, str]]:
    """One visitor's requests, in order: (route name, path)."""
    cod, typ = rnd.choice(s["forms"])
    codes = ",".join(c for c, _t in rnd.sample(s["forms"], rnd.randint(1, 8)))
    a, b = rnd.choice(PAIRS)
    bg = f"serie=bg&spe1={a}&spe2={b}&mention={rnd.choice(MENTIONS)}"
    out = [("/", "/"), ("/api/meta", "/api/meta"), ("/api/carte/couche", "/api/carte/couche"),
           ("/api/search/codes", "/api/search/codes?q=" + rnd.choice(WORDS).replace(" ", "+")),
           ("/api/formation/{cod}", f"/api/formation/{cod}"), ("/formation/{cod}", f"/formation/{cod}"),
           ("/api/journey/stage2", f"/api/journey/stage2?{bg}&type={typ}"),
           ("/api/voeux", f"/api/voeux?{bg}&ids={codes}"), ("/api/projet/{cod}", f"/api/projet/{cod}")]
    if s["mets"]:
        out.append(("/api/metier/{id}", f"/api/metier/{rnd.choice(s['mets'])}"))
    return out


async def run(base: str, n: int, s: dict, seed: int, timeout: float) -> tuple[dict, float]:
    import httpx
    times: dict[str, list] = {}
    errors: dict[str, list] = {}
    limits = httpx.Limits(max_connections=n, max_keepalive_connections=n)
    async with httpx.AsyncClient(base_url=base, timeout=timeout, limits=limits,
                                 headers={"user-agent": "SupCompass-charge/1.0 (test local)", "dnt": "1"}) as cl:
        async def one(i: int):
            rnd = random.Random(seed * 100_003 + i)
            await asyncio.sleep(rnd.random() * 2.0)          # visitors arrive over two seconds
            for name, path in visit(rnd, s):
                t = time.perf_counter()
                try:
                    r = await cl.get(path)
                    bad = r.status_code >= 500
                    info = r.status_code
                except Exception as e:  # noqa: BLE001  a timeout or a refused connection is an error
                    bad, info = True, type(e).__name__
                times.setdefault(name, []).append(time.perf_counter() - t)
                if bad:
                    errors.setdefault(name, []).append(info)
        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(n)))
        wall = time.perf_counter() - t0
    rep = {}
    for name, ts in times.items():
        ts = sorted(ts)
        rep[name] = {"n": len(ts), "erreurs": len(errors.get(name, [])), "exemples_erreurs": errors.get(name, [])[:3],
                     "median_s": round(statistics.median(ts), 3), "p95_s": round(ts[min(len(ts) - 1, int(0.95 * len(ts)))], 3),
                     "max_s": round(ts[-1], 3)}
    return rep, wall


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--visiteurs", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    db = Path(a.db)
    s = sample(db, 400, a.seed)
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KV_", "UPSTASH", "SUPTRACKER_STATS"))}
    env.update({"SUPTRACKER_DATA": str(db.parent), "PYTHONPATH": str(ROOT)})
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--host", "127.0.0.1", "--port", str(port),
                            "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        import httpx
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):                                  # the server is ready when /readyz answers
            try:
                if httpx.get(base + "/readyz", timeout=2).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        else:
            print("server did not start", flush=True)
            return 1
        rep, wall = asyncio.run(run(base, a.visiteurs, s, a.seed, a.timeout))
    finally:
        srv.terminate()
        srv.wait(timeout=20)
    total = sum(r["n"] for r in rep.values())
    errs = sum(r["erreurs"] for r in rep.values())
    print(f"{a.visiteurs} visiteurs simultanés, {total} requêtes en {wall:.1f} s ({total / wall:.0f} requêtes/s), {errs} erreur(s)")
    print(f"{'route':28} {'n':>5} {'err':>4} {'médiane':>8} {'p95':>8} {'max':>8}")
    for name, r in sorted(rep.items(), key=lambda kv: -kv[1]["p95_s"]):
        print(f"{name:28} {r['n']:>5} {r['erreurs']:>4} {r['median_s']:>7.2f}s {r['p95_s']:>7.2f}s {r['max_s']:>7.2f}s"
              + (f"  {r['exemples_erreurs']}" if r["erreurs"] else ""))
    if a.json:
        Path(a.json).write_text(json.dumps({"visiteurs": a.visiteurs, "requetes": total, "duree_s": round(wall, 1),
                                            "erreurs": errs, "routes": rep}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
