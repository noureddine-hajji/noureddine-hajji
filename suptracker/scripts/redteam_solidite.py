"""Red team of sprint 3 « Solidité avant le pic » (owner, 2026-11-21).

    python scripts/redteam_solidite.py [--db data/suptracker.duckdb] [--real]

  SO1 staging beside the warehouse: staging.move writes the six raw staging tables into sources_brutes.duckdb with every row
      (a hand-made warehouse), drops them from the warehouse, and relation() finds each one there (or in the warehouse, for an
      older build); the build calls move before its last CHECKPOINT and compact before the swap. --real: the committed warehouse
      holds none of them, the side file holds all six, the three red teams that re-read them find them.
  SO2 compaction: a table dropped during a build leaves its blocks in the file; compact() writes a fresh copy with every table,
      view and row, the file is smaller, no block is free.
  SO3 size budget (--real): the warehouse under 85 MB (the data workflow warns above, fails at 95 MB, GitHub refuses 100 MB;
      each SIES campaign adds about 8 MB), the side files under 95 MB; the workflow commits the side file and checks its size.
  SO4 the peer benchmark, slimmed: mart.peer_rank no longer repeats its group's distribution on 446,752 rows; what the
      formation page receives (value, percentile, n, p10..p90, unstable) equals an independent pandas re-derivation from
      core.formation_year (groups, reference set, interpolated quantiles, mid-rank percentile), crafted and --real.
  SO5 Vercel bundle: .vercelignore, read as Vercel reads it, drops the side file of raw rows and keeps the warehouse, the
      texts file, the code.
  SO6 load test: scripts/charge.py's visit uses routes that exist, only GETs to 127.0.0.1, records no audience event store
      (no Redis variables passed), fails on any error.
  SO7 docs and wiring: README, CLAUDE.md, durations.json, the release table.
  SO8 mutation test of SO1-SO6 and SO9 (mutants built in memory).
  SO9 one build per warehouse (the load test's finding): concurrent first requests build each shared answer once (carte.once,
      a re-entrant lock); the map layer, the layer answer, the bac lines, the apprenticeship offers and the badges go through it.
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
BUDGET_MB = 85


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str):
    import suptracker  # noqa: F401
    mod = types.ModuleType(f"suptracker.{name}")
    mod.__package__ = "suptracker"
    mod.__file__ = str(path)
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text() for k in ("staging", "indicators", "build", "api", "carte")}
        self.charge = (ROOT / "scripts" / "charge.py").read_text()
        self.workflow = (ROOT.parent / ".github" / "workflows" / "suptracker-data.yml").read_text()
        self.vercelignore = (ROOT / ".vercelignore").read_text()

    def mod(self, k: str):
        return load(ROOT / "suptracker" / f"{k}.py", f"{k}_rt", self.src[k])


def _toy(path: Path, rows: int = 3000) -> dict:
    """A small warehouse with the six staging tables, a core table and a view."""
    con = duckdb.connect(str(path))
    for s in ("ref", "core", "mart"):
        con.execute(f"CREATE SCHEMA {s}")
    counts = {}
    for i, t in enumerate(("monmaster_raw", "insersup", "inserjeunes_lycee", "inserjeunes_cfa", "lycee_ips_raw", "lycee_ival_raw")):
        n = rows + 37 * i
        con.execute(f"CREATE TABLE ref.{t} AS SELECT range AS k, md5(range::VARCHAR || '{t}') AS v FROM range({n})")
        counts[t] = n
    con.execute("CREATE TABLE ref.lycee AS SELECT range AS uai FROM range(50)")       # a derived table: never moved
    con.execute("CREATE TABLE core.formation_year AS SELECT range AS cod, range % 7 AS x FROM range(500)")
    con.execute("CREATE VIEW mart.v AS SELECT cod FROM core.formation_year WHERE x = 1")
    con.execute("CHECKPOINT")
    con.close()
    return counts


@check("SO1 staging: the six raw tables move beside the warehouse, every row; relation() finds them; the build calls move and compact")
def so1(c: Ctx):
    ST = c.mod("staging")
    bad = []
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "suptracker.building"
        counts = _toy(w)
        con = duckdb.connect(str(w))
        moved = ST.move(con, Path(d) / "suptracker.duckdb")
        left = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'ref'").fetchall()}
        con.execute("CHECKPOINT")
        con.close()
        side = Path(d) / ST.BRUT_FILE
        if moved != counts:
            bad.append(f"moved {moved} != staged {counts}")
        if left != {"lycee"}:
            bad.append(f"left in the warehouse: {sorted(left)}")
        if not side.exists():
            return False, "no side file"
        b = duckdb.connect(str(side), read_only=True)
        got = {t: b.execute(f"SELECT count(*), sum(hash(v)) FROM ref.{t}").fetchone() for t in counts}
        b.close()
        if {t: g[0] for t, g in got.items()} != counts:
            bad.append(f"side file rows {got}")
        # read back from a read-only connection on the (renamed) warehouse
        shutil.move(str(w), str(Path(d) / "suptracker.duckdb"))
        r = duckdb.connect(str(Path(d) / "suptracker.duckdb"), read_only=True)
        rels = {t: ST.relation(r, t) for t in counts}
        if any(v != f"brut.ref.{t}" for t, v in rels.items()):
            bad.append(f"relation {rels}")
        n = {t: r.execute(f"SELECT count(*) FROM {rels[t]}").fetchone()[0] for t in counts if rels[t]}
        if n != counts:
            bad.append(f"read back {n}")
        r.close()
        # an older warehouse that still holds a table: its own copy is read
        w2 = Path(d) / "old" / "suptracker.duckdb"
        w2.parent.mkdir()
        _toy(w2, 10)
        r2 = duckdb.connect(str(w2), read_only=True)
        if ST.relation(r2, "insersup") != "ref.insersup":
            bad.append("an older warehouse's own table not read")
        r2.close()
        try:
            ST.relation(duckdb.connect(), "formation_year")
            bad.append("relation() accepts a table that is not staging")
        except ValueError:
            pass
    b = c.src["build"]
    i_move, i_ck, i_cmp, i_swap = (b.find("staging.move(con, db_path)"), b.rfind('con.execute("CHECKPOINT")'),
                                   b.find("staging.compact(tmp)"), b.find("tmp.replace(db_path)"))
    if not (0 < i_move < i_ck < i_cmp < i_swap):
        bad.append("build: move before the last CHECKPOINT, compact before the swap")
    if c.real:
        con = duckdb.connect(str(c.db), read_only=True)
        inside = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = current_database() "
                                            "AND schema_name = 'ref'").fetchall()} & set(ST.TABLES)
        rel = {t: ST.relation(con, t) for t in ST.TABLES}
        con.close()
        if inside:
            bad.append(f"real warehouse still holds {sorted(inside)}")
        if any(v is None or not v.startswith("brut.") for v in rel.values()):
            bad.append(f"real side file: {rel}")
        for name in ("redteam_lycee", "redteam_passerelles", "redteam_insertion"):
            t = (ROOT / "scripts" / f"{name}.py").read_text()
            if "ST.relation(src," not in t:
                bad.append(f"{name} reads the raw tables without staging.relation")
    return not bad, f"6 tables moved and read back; build order checked; real {c.real}; {bad[:4]}"


@check("SO2 compaction: a fresh copy keeps every table, view and row, frees the dropped tables' blocks")
def so2(c: Ctx):
    ST = c.mod("staging")
    bad = []
    with tempfile.TemporaryDirectory() as d:
        w = Path(d) / "w.duckdb"
        _toy(w, 200_000)
        con = duckdb.connect(str(w))
        for t in ("monmaster_raw", "insersup", "inserjeunes_lycee"):
            con.execute(f"DROP TABLE ref.{t}")
        con.execute("CHECKPOINT")
        before = {r[0]: r[1] for r in con.execute(
            "SELECT schema_name || '.' || table_name, estimated_size FROM duckdb_tables() ORDER BY 1").fetchall()}
        sums = {t: con.execute(f"SELECT count(*), sum(hash(columns(*))) FROM {t}").fetchone() for t in before}
        con.close()
        size0 = w.stat().st_size
        ST.compact(w)
        size1 = w.stat().st_size
        con = duckdb.connect(str(w), read_only=True)
        after = {r[0]: r[1] for r in con.execute(
            "SELECT schema_name || '.' || table_name, estimated_size FROM duckdb_tables() ORDER BY 1").fetchall()}
        sums2 = {t: con.execute(f"SELECT count(*), sum(hash(columns(*))) FROM {t}").fetchone() for t in after}
        views = [v for (v,) in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()]
        free = con.execute("SELECT free_blocks FROM pragma_database_size()").fetchone()[0]
        con.close()
        if set(after) != set(before) or sums2 != sums:
            bad.append(f"tables or rows changed: {sorted(set(before) ^ set(after))}")
        if views != ["v"]:
            bad.append(f"views {views}")
        if not size1 < size0 or free:
            bad.append(f"size {size0} -> {size1}, free blocks {free}")
        if Path(str(w) + ".compact").exists():
            bad.append("the temporary copy is left behind")
    return not bad, f"compacted, every row kept; {bad[:3]}"


@check(f"SO3 size budget: warehouse under {BUDGET_MB} MB, side files under 95 MB; the workflow commits and checks the side file")
def so3(c: Ctx):
    bad = []
    wf = c.workflow
    add = re.search(r"git add data/suptracker\.duckdb[^\n]*", wf)
    if not add or "data/sources_brutes.duckdb" not in add.group(0):
        bad.append("the data workflow does not commit the side file")
    if 'bsize=$(stat -c %s data/sources_brutes.duckdb)' not in wf or 'test "$bsize" -lt 95000000' not in wf:
        bad.append("the data workflow does not check the side file's size")
    if 'test "$size" -lt 85000000 || echo "::warning::' not in wf:
        bad.append("no warning above 85 MB")
    sizes = {}
    if c.real:
        for f in ("suptracker.duckdb", "rapport_textes.duckdb", "sources_brutes.duckdb"):
            p = c.db.with_name(f)
            sizes[f] = round(p.stat().st_size / 1e6, 1) if p.exists() else None
        if sizes["suptracker.duckdb"] is None or sizes["suptracker.duckdb"] >= BUDGET_MB:
            bad.append(f"warehouse {sizes['suptracker.duckdb']} MB")
        if any(v is None or v >= 95 for v in sizes.values()):
            bad.append(f"side files {sizes}")
    return not bad, f"sizes (MB) {sizes or 'not measured'}; {bad[:3]}"


def _peers_pandas(fy, metrics: dict, low_n: int, min_peers: int):
    """The benchmark as the formation page should receive it, re-derived without SQL: per (campaign, filière, metric), the
    reference set, its interpolated quantiles, and each formation's mid-rank percentile among it."""
    import numpy as np
    out = {}
    col = {"pct_tb_tbf": lambda d: d["pct_tb"] + d["pct_tbf"].fillna(0)}
    for key, (_expr, needs_n, _l, _h) in metrics.items():
        v = col[key](fy) if key in col else fy[key]
        d = fy[["session", "cod_aff_form", "fil_lib_voe_acc", "acc_tot"]].assign(value=v.astype(float))
        d["ref"] = d["value"].notna() & ((d["acc_tot"] >= low_n) if needs_n else True)
        for (s, fil), g in d.groupby(["session", "fil_lib_voe_acc"], dropna=False):
            r = np.sort(g.loc[g["ref"], "value"].to_numpy())
            n = len(r)
            q = [float(np.quantile(r, p)) for p in (0.1, 0.25, 0.5, 0.75, 0.9)] if n else [None] * 5
            for _i, x in g.iterrows():
                pr = None
                if x["ref"] and n > 1:
                    below = int((r < x["value"]).sum())
                    tied = int((r == x["value"]).sum())
                    x100 = 100.0 * (below + 0.5 * (tied - 1)) / (n - 1)
                    pr = math.floor(x100 * 10 + 0.5) / 10          # DuckDB's round: half away from zero (x100 >= 0)
                out[(int(s), x["cod_aff_form"], key)] = {"value": None if np.isnan(x["value"]) else x["value"], "ref": bool(x["ref"]),
                                                         "pct": pr, "n": n or None, "q": q if n else [None] * 5,
                                                         "unstable": (n < min_peers) if n else None}
    return out


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 1e-6


def _compare(served: list[dict], want: dict, s: int, cod: str) -> list:
    bad = []
    for p in served:
        w = want.get((s, cod, p["metric"]))
        if w is None:
            bad.append((cod, p["metric"], "unexpected"))
            continue
        got_q = [p["p10"], p["p25"], p["p50"], p["p75"], p["p90"]]
        if not (_close(p["value"], w["value"]) and _close(p["peer_percentile"], w["pct"]) and bool(p["in_reference"]) == w["ref"]
                and (p["n_peers"] or None) == w["n"] and all(_close(a, b) for a, b in zip(got_q, w["q"]))
                and (p["unstable"] if w["n"] else None) == w["unstable"]):
            bad.append((cod, p["metric"], {k: p[k] for k in ("value", "peer_percentile", "n_peers", "p50", "unstable")},
                        {k: w[k] for k in ("value", "pct", "n", "unstable")}))
    return bad


PEER_SQL = """SELECT r.metric, r.value, r.in_reference, r.peer_percentile, d.n_peers, d.p10, d.p25, d.p50, d.p75, d.p90, d.unstable
    FROM mart.peer_rank r LEFT JOIN mart.peer_distribution d
      ON d.session = r.session AND d.metric = r.metric AND d.fil_lib_voe_acc IS NOT DISTINCT FROM r.fil_lib_voe_acc
    WHERE r.session = ? AND r.cod_aff_form = ?"""


@check("SO4 peer benchmark: value, percentile, n, p10..p90, unstable equal an independent pandas re-derivation (crafted, --real)")
def so4(c: Ctx):
    import numpy as np
    import pandas as pd
    from suptracker import config
    IND = c.mod("indicators")
    api_sql = re.search(r'peers = rows\("""(.*?)""",', c.src["api"], re.S)
    if not api_sql:
        return False, "the formation route's benchmark query is gone"
    sql = api_sql.group(1)
    if "mart.peer_rank r LEFT JOIN mart.peer_distribution d" not in sql:
        return False, "the formation route no longer joins the group's distribution"
    bad = []
    # crafted: 3 campaigns x 4 filières (one NULL), ties, missing values, small admits, a filière of one formation
    rnd = np.random.default_rng(7)
    n = 400
    fy = pd.DataFrame({"session": rnd.choice([2023, 2024, 2025], n), "cod_aff_form": [str(1000 + i) for i in range(n)],
                       "fil_lib_voe_acc": rnd.choice(["Licence - Droit", "BTS - MCO", None, "CPGE - MPSI"], n),
                       "acc_tot": rnd.integers(0, 60, n)})
    for k in ("taux_acces_ens", "part_terminale_generale_en_position_admis_pp", "pct_tb", "pct_tbf", "pct_bours", "pct_f", "pct_bg",
              "pct_aca_orig", "pct_etab_orig"):
        v = rnd.choice([0.0, 12.5, 50.0, 87.5, 100.0], n) + rnd.choice([0, 0, 0.25], n)
        fy[k] = np.where(rnd.random(n) < 0.15, np.nan, v)
    fy.loc[0, "fil_lib_voe_acc"] = "Seule"
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.register("_fy", fy)
    con.execute("CREATE TABLE core.formation_year AS SELECT * FROM _fy")
    IND.build_peers(con)
    want = _peers_pandas(fy, IND.PEER_METRICS, config.LOW_N_THRESHOLD, config.MIN_PEERS)
    for s, cod in fy[["session", "cod_aff_form"]].itertuples(index=False):
        cur = con.execute(sql, [int(s), cod])
        names = [d[0] for d in cur.description]
        served = [dict(zip(names, r)) for r in cur.fetchall()]
        if len(served) != len(IND.PEER_METRICS):
            bad.append((cod, f"{len(served)} metrics"))
        bad += _compare(served, want, int(s), cod)
    slim = {r[0] for r in con.execute("DESCRIBE mart.peer_rank").fetchall()}
    if slim & {"n_peers", "p10", "p25", "p50", "p75", "p90", "unstable"}:
        bad.append(f"mart.peer_rank repeats its group's distribution: {sorted(slim)}")
    real = 0
    if c.real:
        rcon = duckdb.connect(str(c.db), read_only=True)
        rfy = rcon.execute("""SELECT session, cod_aff_form, fil_lib_voe_acc, acc_tot, taux_acces_ens,
            part_terminale_generale_en_position_admis_pp, pct_tb, pct_tbf, pct_bours, pct_f, pct_bg, pct_aca_orig, pct_etab_orig
            FROM core.formation_year""").df()
        fils = rfy.groupby("fil_lib_voe_acc", dropna=False).size().sort_values(ascending=False).index[:12].tolist()
        sub = rfy[rfy["fil_lib_voe_acc"].isin(fils)]
        want = _peers_pandas(sub, IND.PEER_METRICS, config.LOW_N_THRESHOLD, config.MIN_PEERS)
        pick = sub.sample(min(300, len(sub)), random_state=3)
        for s, cod in pick[["session", "cod_aff_form"]].itertuples(index=False):
            cur = rcon.execute(sql, [int(s), cod])
            names = [d[0] for d in cur.description]
            bad += _compare([dict(zip(names, r)) for r in cur.fetchall()], want, int(s), cod)
            real += 1
        rcon.close()
    return not bad, f"{len(fy)} crafted formations, {real} real ones re-derived; {bad[:3]}"


@check("SO5 Vercel bundle: the side file of raw rows is dropped, the warehouse, the texts and the code are kept")
def so5(c: Ctx):
    import redteam_metiers as M
    base = ROOT.name
    out = M.vercel_ignored(f"{base}/data/sources_brutes.duckdb", c.vercelignore)
    keep = [f for f in ("data/suptracker.duckdb", "data/rapport_textes.duckdb", "suptracker/api.py", "suptracker/staging.py",
                        "suptracker/static/app.js") if M.vercel_ignored(f"{base}/{f}", c.vercelignore)]
    return out and not keep, f"side file dropped {out}; kept files dropped {keep}"


@check("SO6 load test script: real routes only, GETs to 127.0.0.1, no analytics store, fails on any error")
def so6(c: Ctx):
    from fastapi.routing import APIRoute
    bad = []
    ch = c.charge
    m = types.ModuleType("charge_rt")
    m.__file__ = str(ROOT / "scripts" / "charge.py")
    exec(compile(ch, "charge.py", "exec"), m.__dict__)
    import random

    from suptracker import api
    routes = {r.path for r in api.app.routes if isinstance(r, APIRoute) or hasattr(r, "path")}
    s = {"forms": [(str(100 + i), f"t{i % 3}") for i in range(12)], "mets": ["MET.1"]}
    names = set()
    for i in range(30):
        for name, path in m.visit(random.Random(i), s):
            names.add(name)
            tmpl = name.replace("{id}", "{met_id}")
            if tmpl not in routes:
                bad.append(f"no route {name}")
            if not path.startswith("/") or "//" in path:
                bad.append(f"path {path}")
    if len(names) < 9:
        bad.append(f"only {len(names)} routes visited")
    if '"127.0.0.1"' not in ch or "http://127.0.0.1" not in ch or re.search(r"https?://(?!127\.0\.0\.1)[a-z]", ch):
        bad.append("the load test may reach another host")
    if '"KV_", "UPSTASH", "SUPTRACKER_STATS"' not in ch:
        bad.append("the server could inherit the analytics store")
    if "return 1 if errs else 0" not in ch or "r.status_code >= 500" not in ch:
        bad.append("errors do not fail the run")
    if re.search(r"\.(post|put|delete|patch)\(", ch):
        bad.append("the load test writes")
    return not bad, f"{len(names)} routes per visit checked; {sorted(set(bad))[:4]}"


@check("SO7 docs and wiring: README, CLAUDE.md, the test in durations.json")
def so7(c: Ctx):
    import json
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text()
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    bad = []
    if "sources_brutes.duckdb" not in readme or "scripts/charge.py" not in readme:
        bad.append("README")
    if "sources_brutes.duckdb" not in claude or "redteam_solidite.py" not in claude:
        bad.append("CLAUDE.md")
    if "tests/test_solidite.py" not in dur:
        bad.append("durations.json")
    return not bad, f"{bad}"


@check("SO9 one build per warehouse: concurrent first requests build each shared answer once (map layer, layer answer, bac lines, apprenticeship, badges)")
def so9(c: Ctx):
    """The load test of 2026-11-21: 50 visitors on a fresh server built the map layer 50 times at once (40 waited > 60 s)."""
    import threading
    import time
    CA = load(ROOT / "suptracker" / "carte.py", "carte_rt", c.src["carte"])
    bad = []
    calls = []

    def slow():
        # a build waits (up to 3 s) for every visitor to reach it: without the lock all 12 do, with it only one does, so the
        # mutant is caught however slowly a loaded runner schedules the threads (a fixed 0.3 s let CI serialise them)
        calls.append(1)
        deadline = time.time() + 3
        while len(calls) < 12 and time.time() < deadline:
            time.sleep(0.01)
        return {"v": len(calls)}
    cache: dict = {}
    got = []
    gate = threading.Barrier(12)      # every request arrives at once, however loaded the runner (CI: a thread could start late)

    def visitor():
        gate.wait()
        got.append(CA.once(cache, "k", slow))
    ts = [threading.Thread(target=visitor) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    first = len(calls)
    if first != 1 or {g["v"] for g in got} != {1} or len(got) != 12:
        bad.append(f"{first} builds for 12 concurrent first requests")
    CA.once(cache, "k2", slow)
    if list(cache) != ["k2"]:
        bad.append(f"an older warehouse's answer kept: {list(cache)}")
    inner = CA.once({}, "a", lambda: CA.once({}, "b", lambda: 3))          # re-entrant: a build may build another
    if inner != 3:
        bad.append("nested build")
    src = c.src["carte"]
    for cache_name in ("_CACHE", "_LAYER", "_COUCHE", "_LINES"):
        if f"once({cache_name}, _fingerprint(con)," not in src or re.search(rf"{cache_name}\[key\] = ", src):
            bad.append(f"carte.{cache_name} not built through once()")
    if "return CA.once(_RECO, CA._fingerprint(con), build)" not in c.src["api"]:
        bad.append("api._RECO not built through once()")
    return not bad, f"12 concurrent first requests, {first} build(s); {bad[:3]}"


MUTANTS = [
    ("staging", "a table left in the warehouse", '    for t in here:\n        con.execute(f"DROP TABLE ref.{t}")\n', "", "SO1"),
    ("staging", "a table not copied", 'TABLES = ("monmaster_raw", "insersup",', 'TABLES = ("monmaster_raw",', "SO1"),
    ("staging", "rows lost on the way", 'AS SELECT * FROM ref.{t}")', 'AS SELECT * FROM ref.{t} LIMIT 100")', "SO1"),
    ("staging", "the side file never read", "    return f\"{ALIAS}.ref.{name}\" if", "    return None if", "SO1"),
    ("staging", "any table accepted", '    if name not in TABLES:\n        raise ValueError(f"not a staging table: {name}")\n', "", "SO1"),
    ("build", "no move", "        staging.move(con, db_path)\n", "", "SO1"),
    ("build", "no compaction", "    staging.compact(tmp)", "    pass", "SO1"),
    ("staging", "compaction copies nothing", '        con.execute("COPY FROM DATABASE src TO dst")', '        con.execute("SELECT 1")', "SO2"),
    ("staging", "temporary copy left", "    fresh.replace(db_file)", "    shutil.copy(fresh, db_file)\nimport shutil", "SO2"),
    ("indicators", "distribution repeated again", "    SELECT l.*,\n      CASE", "    SELECT l.*, d.n_peers, d.p10, d.p25, d.p50, d.p75, d.p90, d.unstable,\n      CASE", "SO4"),
    ("indicators", "percentile over every formation", "      FROM mart._peer_long WHERE in_reference\n", "      FROM mart._peer_long\n", "SO4"),
    ("indicators", "ties not shared", "0.5 * (r.n_tied - 1)", "0 * (r.n_tied - 1)", "SO4"),
    ("api", "group joined without the filière", "AND d.fil_lib_voe_acc IS NOT DISTINCT FROM r.fil_lib_voe_acc\n                           WHERE",
     "\n                           WHERE", "SO4"),
    ("vercelignore", "side file shipped to Vercel", "**/data/sources_brutes.duckdb\n", "", "SO5"),
    ("workflow", "side file not committed", "data/rapport_textes.duckdb data/sources_brutes.duckdb data/verification",
     "data/rapport_textes.duckdb data/verification", "SO3"),
    ("workflow", "no early warning", 'test "$size" -lt 85000000 || echo "::warning::', 'true || echo "::warning::', "SO3"),
    ("charge", "errors do not fail", "    return 1 if errs else 0", "    return 0", "SO6"),
    ("carte", "no lock", "    with _BUILD_LOCK:\n        if key not in cache:", "    if True:\n        if key not in cache:", "SO9"),
    ("carte", "older answers kept", "            cache.clear()\n            cache[key] = value", "            cache[key] = value", "SO9"),
    ("carte", "the layer built outside once()", "    by_dip, session, offre = once(_LAYER, _fingerprint(con), lambda: _layer(con))",
     "    _LAYER[key] = _layer(con)\n    by_dip, session, offre = once(_LAYER, _fingerprint(con), lambda: _layer(con))", "SO9"),
    ("charge", "server keeps the analytics store", 'not k.startswith(("KV_", "UPSTASH", "SUPTRACKER_STATS"))', "True", "SO6"),
    ("charge", "a route that does not exist", '("/api/projet/{cod}", f"/api/projet/{cod}")', '("/api/projets/{cod}", f"/api/projets/{cod}")', "SO6"),
]


@check("SO8 mutation test: every seeded staging, compaction, benchmark, bundle, workflow, load-test and lock bug is caught")
def so8(c: Ctx):
    import copy
    missed, caught = [], 0
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(c)
        if kind in c.src:
            if old not in c.src[kind]:
                missed.append(f"{name} (anchor gone)")
                continue
            m.src = dict(c.src, **{kind: c.src[kind].replace(old, new, 1)})
        else:
            attr = {"vercelignore": "vercelignore", "workflow": "workflow", "charge": "charge"}[kind]
            if old not in getattr(c, attr):
                missed.append(f"{name} (anchor gone)")
                continue
            setattr(m, attr, getattr(c, attr).replace(old, new, 1))
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


def run(db: Path, real: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
