"""The browser checks of every red team, in one run (owner, 2026-11-19).

The CI runners have no browser: every check that opens the site in Chromium (phone screens, dark mode, headings, page
lengths, the map, the speed budgets...) SKIPS itself there, silently. Three of them failed on main for days without anyone
seeing it. This script runs them all, on the committed warehouse, and FAILS on any skip: in the nightly workflow
(.github/workflows/suptracker-browser.yml) a skipped browser check is a broken check.

    python scripts/browser_nightly.py [--db data/suptracker.duckdb] [--only a11y,mobile] [--report out.md]

Exit 0 when every red team passes with its browser checks really run; 1 otherwise. The report (Markdown) lists each red
team, its browser checks, their verdict and the first line of every failure: the workflow posts it in an issue.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# red team -> the checks that open the browser (they are the ones that skip without one). The other checks of a red team
# run too when its run() cannot be restricted: they are the same as in CI, a failure there is still a failure.
SUITE = {
    "a11y": ("A4",),
    "carterecherche": ("CR8",),
    "conformite": ("QC10",),
    "design": ("DE8",),
    "evolution": ("EV9",),
    "filtres": ("FI7",),
    "guide": ("GU6",),
    "langage": ("LA7",),
    "lecture": ("LE8",),
    "mobile": ("MB5", "MB6"),
    "moyenne": ("MO7",),
    "navigation": ("U6",),
    "recherche": ("RS6",),
    "securite": ("SE9",),
    "seo": ("G11",),
    "tauxprofil": ("Z5",),
    "ux": ("X7",),
    "visuel": ("VI8",),
    "vitesse": ("VT6",),
}
SKIP_WORDS = ("skipped", "skip (", "not installed", "non installé")


def check_id(name: str) -> str:
    return name.split()[0]


def browser_ready() -> str | None:
    """None when node can require Playwright and launch Chromium; else the reason (the run fails on it)."""
    node = shutil.which("node")
    if not node:
        return "node is not installed"
    prog = "const { chromium } = require('playwright'); chromium.launch().then((b) => b.close()).then(() => process.exit(0), (e) => { console.error(e.message); process.exit(1); });"
    r = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=120)
    return None if r.returncode == 0 else f"Playwright / Chromium unavailable: {(r.stderr or r.stdout).strip()[-300:]}"


def call_run(mod, db: Path, ids: tuple[str, ...]) -> list[dict]:
    """The red team's own run(), with its real warehouse, its browser checks on, restricted to them when it can be."""
    params = inspect.signature(mod.run).parameters
    kw = {}
    if "db" in params:
        kw["db"] = db
    if "real" in params:
        kw["real"] = True
    if "browser" in params:
        kw["browser"] = True
    if "checks" in params:
        kw["checks"] = set(ids)
    return mod.run(**kw)


def judge(name: str, results: list[dict], ids: tuple[str, ...]) -> list[str]:
    """The problems of one red team: a failed check, a browser check skipped, a browser check missing from the results."""
    problems = []
    seen = {check_id(r["check"]): r for r in results}
    for i in ids:
        r = seen.get(i)
        if r is None:
            problems.append(f"{i}: did not run")
        elif any(w in str(r.get("detail", "")).lower() for w in SKIP_WORDS):
            problems.append(f"{i}: skipped ({str(r.get('detail'))[:160]})")
    for r in results:
        if not r.get("ok"):
            problems.append(f"{check_id(r['check'])}: {str(r.get('detail', '')).splitlines()[0][:240] if r.get('detail') else 'failed'}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--only", default="", help="comma-separated red teams (default: all)")
    ap.add_argument("--report", type=Path, default=None, help="write a Markdown report here")
    a = ap.parse_args(argv)
    names = [n for n in (a.only.split(",") if a.only else SUITE) if n]
    unknown = [n for n in names if n not in SUITE]
    if unknown:
        print(f"unknown red teams: {unknown}")
        return 2
    lines, failed = ["| Red team | Browser checks | Result | Time |", "|---|---|---|---|"], {}
    why = browser_ready()
    if why or not a.db.exists():
        failed["(setup)"] = [why or f"no warehouse at {a.db}"]
    else:
        for n in names:
            t = time.time()
            try:
                problems = judge(n, call_run(importlib.import_module(f"redteam_{n}"), a.db, SUITE[n]), SUITE[n])
            except Exception as e:  # noqa: BLE001  a crash is a failure, never a skip
                problems = [f"crash: {type(e).__name__}: {str(e)[:240]}"]
            dt = round(time.time() - t)
            if problems:
                failed[n] = problems
            lines.append(f"| {n} | {', '.join(SUITE[n])} | {'OK' if not problems else 'ÉCHEC'} | {dt} s |")
            print(f"{'PASS' if not problems else 'FAIL'} {n} ({dt} s)" + "".join(f"\n     {p}" for p in problems), flush=True)
    if failed:
        lines += ["", "**Problèmes**", ""] + [f"- `{n}` : {p}" for n, ps in failed.items() for p in ps]
    if a.report:
        a.report.write_text("\n".join(lines) + "\n")
    if "(setup)" in failed:
        print("FAIL setup:", failed["(setup)"][0])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
