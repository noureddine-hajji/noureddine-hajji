"""Red team, the nightly browser checks (owner, 2026-11-19): scripts/browser_nightly.py + .github/workflows/suptracker-browser.yml.

    python scripts/redteam_navigateur.py

  BN1 coverage: every red team with a --browser switch is in the suite; every listed check exists in its red team and is a
      browser check (its name says « browser » and its body skips without one); nothing listed twice.
  BN2 the verdict: a failed check, a skipped browser check, a browser check that did not run, a crash: each is a problem;
      a clean run is none.
  BN3 the setup: no Playwright / Chromium or no warehouse fails the run (exit 1), never a silent pass; the report names it.
  BN4 the workflow: nightly + by hand only (never on push), Playwright pinned to the version the checks were written with
      and found by `require` from any folder, Chromium installed with its system libraries, the script run on the committed
      warehouse, an issue opened or commented on failure and closed when green again, the right permissions, a time limit.
  BN5 mutation test: every seeded bug in the script or the workflow is caught.
"""
from __future__ import annotations

import copy
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "browser_nightly.py"
WORKFLOW = REPO / ".github" / "workflows" / "suptracker-browser.yml"
PW_VERSION = "1.56.1"            # the Playwright the checks were written with (the sandbox's), typed here on purpose
AXE_VERSION = "4.14.0"           # axe-core for red team A4 (WCAG audit of every page): without it A4 skips its audit
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self):
        self.src = SCRIPT.read_text()
        self.wf = WORKFLOW.read_text() if WORKFLOW.exists() else ""

    def mod(self):
        m = types.ModuleType("browser_nightly_rt")
        m.__file__ = str(SCRIPT)
        sys.modules[m.__name__] = m
        try:
            exec(compile(self.src, str(SCRIPT), "exec"), m.__dict__)
        finally:
            sys.modules.pop(m.__name__, None)
        return m


def check_body(src: str, cid: str) -> str:
    m = re.search(rf'@check\("{re.escape(cid)} [^\n]*\n(?:.*\n)*?(?=@check\(|^MUTANTS|^def run\b)', src, re.M)
    return m.group(0) if m else ""


@check("BN1 coverage: every red team with a --browser switch is in the suite, every listed check is a browser check of it")
def bn1(c: Ctx):
    m = c.mod()
    bad = []
    with_switch = sorted(p.stem.removeprefix("redteam_") for p in (ROOT / "scripts").glob("redteam_*.py")
                         if p.name != Path(__file__).name and 'add_argument("--browser"' in p.read_text())
    missing = [n for n in with_switch if n not in m.SUITE]
    if missing:
        bad.append(("red teams with a --browser switch left out", missing))
    for n, ids in m.SUITE.items():
        f = ROOT / "scripts" / f"redteam_{n}.py"
        if not f.exists():
            bad.append((n, "no such red team"))
            continue
        src = f.read_text()
        if len(set(ids)) != len(ids) or not ids:
            bad.append((n, "a check listed twice or none"))
        for i in ids:
            body = check_body(src, i)
            if not body:
                bad.append((n, i, "no such check"))
            # a browser check names the browser in its title AND skips itself without one (its body says when)
            elif "browser" not in body.split("\n")[0].lower() or "skip" not in body.lower():
                bad.append((n, i, "not a browser check"))
    return not bad, f"{len(m.SUITE)} red teams, {sum(len(v) for v in m.SUITE.values())} browser checks; problems {bad[:4]}"


@check("BN2 the verdict: a failure, a skipped browser check, a browser check that did not run each count; a clean run is clean")
def bn2(c: Ctx):
    m = c.mod()
    ok_ = {"check": "A4 browser: x", "ok": True, "detail": "problems []"}
    cases = [
        ("clean", [ok_, {"check": "A1 x", "ok": True, "detail": ""}], ("A4",), 0),
        ("failed other check", [ok_, {"check": "A1 x", "ok": False, "detail": "broken\nmore"}], ("A4",), 1),
        ("browser check skipped", [{"check": "A4 browser: x", "ok": True, "detail": "skipped (run with --browser or --real)"}], ("A4",), 1),
        ("node or playwright missing", [{"check": "A4 browser: x", "ok": True, "detail": "axe not installed (skipped); problems []"}], ("A4",), 1),
        ("node missing, said without the word skipped", [{"check": "A4 browser: x", "ok": True, "detail": "node not installed"}], ("A4",), 1),
        ("browser check absent", [{"check": "A1 x", "ok": True, "detail": ""}], ("A4",), 1),
        ("browser check failed", [{"check": "A4 browser: x", "ok": False, "detail": "h1 missing"}], ("A4",), 1),
    ]
    bad = []
    for name, res, ids, want in cases:
        got = m.judge("a11y", res, ids)
        if (len(got) > 0) != (want > 0):
            bad.append((name, got))
    return not bad, f"{len(cases)} cases; problems {bad}"


@check("BN3 the setup: no Playwright / Chromium or no warehouse fails the run with its reason, never a silent pass")
def bn3(c: Ctx, tmp=None):
    import tempfile
    m = c.mod()
    bad = []
    with tempfile.TemporaryDirectory() as d:
        rep = Path(d) / "r.md"
        m.browser_ready = lambda: "Playwright / Chromium unavailable: test"
        code = m.main(["--db", str(ROOT / "data" / "suptracker.duckdb"), "--report", str(rep)])
        if code != 1 or "Playwright" not in rep.read_text():
            bad.append(("no browser", code))
        m.browser_ready = lambda: None
        code = m.main(["--db", str(Path(d) / "absent.duckdb"), "--report", str(rep)])
        if code != 1 or "no warehouse" not in rep.read_text():
            bad.append(("no warehouse", code))
        # a red team that crashes is a failure, its name in the report
        m.browser_ready = lambda: None
        fake = types.ModuleType("redteam_fake_rt")
        fake.run = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        sys.modules["redteam_fake_rt"] = fake
        m.SUITE = {"fake_rt": ("Z9",)}
        try:
            code = m.main(["--db", str(ROOT / "data" / "suptracker.duckdb"), "--report", str(rep)])
        finally:
            sys.modules.pop("redteam_fake_rt", None)
        if code != 1 or "crash" not in rep.read_text() or "fake_rt" not in rep.read_text():
            bad.append(("crash", code))
    return not bad, f"problems {bad}"


@check("BN4 the workflow: nightly and by hand, pinned Playwright found from anywhere, Chromium, the script, issue opened / closed, permissions")
def bn4(c: Ctx):
    wf, bad = c.wf, []
    if not wf:
        return False, "no workflow file"
    on = wf.split("\njobs:")[0]
    need = {
        "nightly": re.search(r'(?m)^\s+- cron: "\d+ \d+ \* \* \*"', on),
        "by hand": "workflow_dispatch:" in on,
        "never on push": "push:" not in on and "pull_request" not in on,
        "issues permission": re.search(r"(?m)^\s+issues: write$", wf),
        "pinned global install": f"npm install -g playwright@{PW_VERSION} axe-core@{AXE_VERSION}" in wf,
        "found by require from anywhere": 'echo "NODE_PATH=$(npm root -g)" >> "$GITHUB_ENV"' in wf,
        "chromium with its libraries": f"playwright@{PW_VERSION} install --with-deps chromium" in wf,
        "the script": "python scripts/browser_nightly.py --report" in wf,
        "issue on failure": re.search(r"if: failure\(\)[\s\S]*gh issue (create|comment)", wf),
        "both create and comment": "gh issue create" in wf and "gh issue comment" in wf,
        "closed when green": re.search(r"if: success\(\)[\s\S]*gh issue close", wf),
        "a time limit": re.search(r"timeout-minutes: (\d+)", wf) and int(re.search(r"timeout-minutes: (\d+)", wf).group(1)) >= 120,
        "report kept": "actions/upload-artifact@v4" in wf,
        "same title both ways": wf.count("Contrôles navigateur en échec") >= 2,
    }
    bad = [k for k, v in need.items() if not v]
    return not bad, f"missing {bad}"


MUTANTS = [
    ("src", "skips not counted", '        elif any(w in str(r.get("detail", "")).lower() for w in SKIP_WORDS):', '        elif False:', "BN2"),
    ("src", "a missing browser check passes", '            problems.append(f"{i}: did not run")', '            pass', "BN2"),
    ("src", "only the browser checks judged", '    for r in results:\n        if not r.get("ok"):', '    for r in []:\n        if not r.get("ok"):'),
    ("src", "'not installed' read as a pass", '"not installed", ', ''),
    ("src", "no browser = pass", '    return 1 if failed else 0', '    return 0'),
    ("src", "a crash is a skip", '                problems = [f"crash: {type(e).__name__}: {str(e)[:240]}"]', '                problems = []'),
    ("src", "a red team left out", '    "visuel": ("VI8",),\n', ''),
    ("src", "a non-browser check listed", '    "guide": ("GU6",),', '    "guide": ("GU1",),'),
    ("wf", "issues not writable", "  issues: write\n", ""),
    ("wf", "no issue on failure", "if: failure()", "if: false"),
    ("wf", "Playwright unpinned", f"npm install -g playwright@{PW_VERSION}", "npm install -g playwright"),
    ("wf", "no axe audit", f" axe-core@{AXE_VERSION}", ""),
    ("wf", "require cannot find Playwright", 'echo "NODE_PATH=$(npm root -g)" >> "$GITHUB_ENV"', "true"),
    ("wf", "run on every push", "  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n"),
    ("wf", "never closed", "gh issue close", "echo close"),
]
# the third and fourth mutants carry their target in MUTANT_TARGETS (they sit outside one check's anchor list)
MUTANT_TARGETS = {"only the browser checks judged": "BN2", "'not installed' read as a pass": "BN2", "no browser = pass": "BN3",
                  "a crash is a skip": "BN3", "a red team left out": "BN1", "a non-browser check listed": "BN1"}


@check("BN5 mutation test: every seeded bug in the script or the workflow is caught")
def bn5(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] != "BN5" and not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    caught, missed = 0, []
    for mt in MUTANTS:
        kind, name, old, new = mt[:4]
        target = mt[4] if len(mt) > 4 else MUTANT_TARGETS.get(name, "BN4")
        m = copy.copy(c)
        src = c.src if kind == "src" else c.wf
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        if kind == "src":
            m.src = src.replace(old, new, 1)
        else:
            m.wf = src.replace(old, new, 1)
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


def run() -> list[dict]:
    c, out = Ctx(), []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crash {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail})
    return out


def main() -> int:
    res = run()
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']}\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
