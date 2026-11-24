"""Red team of audit PR A (owner, 2026-11-24): every workflow that commits to the repository survives a concurrent push.

    python scripts/redteam_enregistrement.py

On 2026-11-23 the warehouse rebuild was rejected (« fetch first ») because the calendar fetch had pushed to main a few minutes
earlier: main kept a warehouse older than its own open-day files, and red team J9 failed on main and on every PR. Every
committing workflow now pushes through scripts/git_push_retry.sh (fetch, rebase, push, retried; a real conflict fails, never a
force-push).

  EN1 wiring: every workflow step that commits pushes through the script with the workflow's own branch; no bare git push, no
      force-push, no leftover « git pull --rebase » + push
  EN2 behaviour on REAL git repositories (a bare origin, two clones, server hooks): a push made meanwhile to another file is kept
      and ours lands on top; a push rejected once is retried and lands; a conflict on the same file fails, leaves origin as it
      was and the clone out of any rebase; a push rejected every time fails after the configured attempts
  EN3 the script's own guarantees in its text: set -u, rebase --abort on conflict, the attempts and the wait configurable, never
      --force, an ::error:: line on every failure
  EN4 mutation test: each seeded bug (no fetch/rebase, no retry, force-push, no abort, a bare push in a workflow) is caught
  EN5 docs: README section, CLAUDE.md rule, test file and its CI duration
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCRIPT = ROOT / "scripts" / "git_push_retry.sh"
WORKFLOWS = REPO / ".github" / "workflows"
CHECKS = []
CALL = 'bash scripts/git_push_retry.sh "$GITHUB_REF_NAME"'


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self):
        self.script = SCRIPT.read_text()
        self.workflows = {p.name: p.read_text() for p in sorted(WORKFLOWS.glob("*.yml"))}
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (REPO / "CLAUDE.md").read_text() if (REPO / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()


# ------------------------------------------------------------------ EN1 wiring
def steps(text: str) -> list[str]:
    """The `run: |` blocks of a workflow, one string each."""
    out, cur, ind = [], None, None
    for line in text.splitlines():
        m = re.match(r"^(\s*)(?:- )?run: \|\s*$", line)
        if m:
            if cur is not None:
                out.append("\n".join(cur))
            cur, ind = [], len(m.group(1)) + 2
            continue
        if cur is not None:
            if line.strip() and len(line) - len(line.lstrip()) < ind:
                out.append("\n".join(cur))
                cur = None
            else:
                cur.append(line)
    if cur is not None:
        out.append("\n".join(cur))
    return out


def wiring_ok(c: Ctx, workflows: dict | None = None) -> tuple[bool, str]:
    workflows = c.workflows if workflows is None else workflows
    bad, n = [], 0
    for name, text in workflows.items():
        for st in steps(text):
            commits = re.search(r"^\s*git commit\b", st, re.M)
            if re.search(r"^\s*git push\b", st, re.M):
                bad.append((name, "a bare git push"))
            if re.search(r"--force|\s-f\b.*push|push\s.*\s-f\b|--force-with-lease", st):
                bad.append((name, "a force-push"))
            if commits:
                n += 1
                if CALL not in st:
                    bad.append((name, "a commit not pushed through the script"))
                elif st.index(CALL) < commits.start():
                    bad.append((name, "the push before the commit"))
                if re.search(r"^\s*git pull\b", st, re.M):
                    bad.append((name, "a leftover git pull"))
    if n < 8:
        bad.append(("fewer committing steps than the 8 known", n))
    return not bad, f"{n} committing steps; problems {bad[:4]}"


@check("EN1 wiring: every committing workflow step pushes through the script with its own branch; no bare push, no force-push")
def en1(c: Ctx):
    return wiring_ok(c)


# ------------------------------------------------------------------ EN2 behaviour on real repositories
def git(cwd, *args, check=True, env=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr[-300:]}")
    return r.stdout.strip()


def commit(repo: Path, name: str, text: str, msg: str):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg)


def world(tmp: Path) -> tuple[Path, Path, Path]:
    """A bare origin on branch main with one commit, and two clones (the other workflow, ours)."""
    origin, a, b = tmp / "origin.git", tmp / "a", tmp / "b"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp / "seed"
    git(tmp, "init", "-q", "-b", "main", str(seed))
    for r in (seed,):
        git(r, "config", "user.email", "rt@example.invalid")
        git(r, "config", "user.name", "rt")
    commit(seed, "base.txt", "base\n", "base")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")
    for r in (a, b):
        git(tmp, "clone", "-q", "--depth", "1", f"file://{origin}", str(r))
        git(r, "config", "user.email", "rt@example.invalid")
        git(r, "config", "user.name", "rt")
    return origin, a, b


def run_script(script: Path, repo: Path, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), "main"], cwd=repo, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "GIT_PUSH_WAIT": "0", **(env or {})})


def reject_hook(origin: Path, times: int):
    """A pre-receive hook on the origin that rejects the first `times` pushes (a stand-in for a push lost to a race)."""
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(f"""#!/bin/sh
n=$(cat "$GIT_DIR/rejects" 2>/dev/null || echo 0)
if [ "$n" -lt {times} ]; then echo $((n + 1)) > "$GIT_DIR/rejects"; echo "rejected for the test" >&2; exit 1; fi
exit 0
""")
    hook.chmod(0o755)


def behaviour_ok(script: Path) -> tuple[bool, str]:
    if not shutil.which("git"):
        return True, "skipped (git not installed)"
    bad, seen = [], {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # 1. another workflow pushed another file meanwhile: both commits end on origin, ours on top
        t1 = tmp / "t1"; t1.mkdir()
        origin, a, b = world(t1)
        commit(a, "calendrier.txt", "calendar\n", "calendar fetched")
        git(a, "push", "-q", "origin", "main")
        commit(b, "warehouse.txt", "warehouse\n", "warehouse refreshed")
        r = run_script(script, b)
        log = git(origin, "log", "--format=%s", "main")
        seen["concurrent"] = r.returncode
        if r.returncode or log.splitlines()[:2] != ["warehouse refreshed", "calendar fetched"]:
            bad.append(("a concurrent push lost or ours not on top", r.returncode, log.splitlines()[:3], r.stdout[-200:]))
        # 2. a push rejected once is retried and lands
        t2 = tmp / "t2"; t2.mkdir()
        origin, a, b = world(t2)
        reject_hook(origin, 1)
        commit(b, "warehouse.txt", "warehouse\n", "warehouse refreshed")
        r = run_script(script, b, {"GIT_PUSH_ATTEMPTS": "3"})
        seen["retried"] = r.returncode
        if r.returncode or "warehouse refreshed" not in git(origin, "log", "--format=%s", "main") or "attempt 2/3" not in r.stdout:
            bad.append(("a once-rejected push not retried", r.returncode, r.stdout[-200:]))
        # 3. a conflict on the same file fails, origin unchanged, the clone out of the rebase
        t3 = tmp / "t3"; t3.mkdir()
        origin, a, b = world(t3)
        commit(a, "base.txt", "theirs\n", "theirs")
        git(a, "push", "-q", "origin", "main")
        before = git(origin, "rev-parse", "main")
        commit(b, "base.txt", "ours\n", "ours")
        r = run_script(script, b)
        seen["conflict"] = r.returncode
        rebasing = (b / ".git" / "rebase-merge").exists() or (b / ".git" / "rebase-apply").exists()
        if r.returncode == 0 or git(origin, "rev-parse", "main") != before or rebasing or "::error::" not in r.stdout:
            bad.append(("a conflict pushed, forced or left mid-rebase", r.returncode, rebasing, r.stdout[-200:]))
        # 4. rejected every time: fails after the configured attempts
        t4 = tmp / "t4"; t4.mkdir()
        origin, a, b = world(t4)
        reject_hook(origin, 99)
        commit(b, "warehouse.txt", "warehouse\n", "warehouse refreshed")
        t0 = time.time()
        r = run_script(script, b, {"GIT_PUSH_ATTEMPTS": "2"})
        seen["always rejected"] = r.returncode
        if r.returncode == 0 or "after 2 attempts" not in r.stdout or "warehouse refreshed" in git(origin, "log", "--format=%s", "main"):
            bad.append(("a push rejected every time reported as done", r.returncode, r.stdout[-200:]))
        seen["s"] = round(time.time() - t0, 1)
    return not bad, f"exit codes {seen}; problems {bad[:3]}"


@check("EN2 real repositories: a concurrent push kept, a rejected push retried, a conflict fails cleanly, endless rejection fails")
def en2(c: Ctx):
    return behaviour_ok(SCRIPT)


# ------------------------------------------------------------------ EN3 the script's text
def text_ok(script: str) -> tuple[bool, str]:
    need = {
        "set -u": "set -u",
        "fetch then rebase before pushing": 'git fetch --quiet origin "$branch"',
        "rebase on the fetched branch": 'git rebase --quiet "origin/$branch"',
        "abort a conflicting rebase": "git rebase --abort",
        "attempts configurable": 'attempts="${GIT_PUSH_ATTEMPTS:-5}"',
        "wait configurable and growing": "sleep $(( i * ${GIT_PUSH_WAIT:-5} ))",
        "an error line when it gives up": '::error::could not push to $branch after $attempts attempts',
    }
    bad = [k for k, v in need.items() if v not in script]
    if re.search(r"--force|push\s[^\n]*\s-f\b", script):
        bad.append("a force-push")
    return not bad, f"problems {bad}"


@check("EN3 the script: set -u, fetch + rebase, abort on conflict, configurable attempts and wait, never a force-push, error lines")
def en3(c: Ctx):
    return text_ok(c.script)


# ------------------------------------------------------------------ EN5 docs
def docs_ok(c: Ctx, readme: str | None = None, claude: str | None = None) -> tuple[bool, str]:
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    bad = []
    if "## Every workflow push survives a concurrent push (audit PR A" not in readme:
        bad.append("README section")
    if "git_push_retry.sh" not in claude or "redteam_enregistrement.py" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_enregistrement.py").exists() or '"tests/test_enregistrement.py"' not in c.durations:
        bad.append("test file or its CI duration")
    return not bad, f"problems {bad}"


@check("EN5 docs: README section, CLAUDE.md rule, test file and its CI duration")
def en5(c: Ctx):
    return docs_ok(c)


# ------------------------------------------------------------------ EN4 mutation test
@check("EN4 mutation test: no rebase, no retry, force-push, no abort and a bare workflow push are each caught")
def en4(c: Ctx):
    caught, missed = 0, []

    def script_mut(name, old, new, fn):
        nonlocal caught
        if old not in c.script:
            missed.append(f"{name} (anchor lost)")
            return
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "git_push_retry.sh"
            p.write_text(c.script.replace(old, new, 1))
            ok, _ = fn(p, c.script.replace(old, new, 1))
        if ok:
            missed.append(name)
        else:
            caught += 1

    both = lambda p, t: (behaviour_ok(p)[0] and text_ok(t)[0], "")      # noqa: E731
    run_only = lambda p, t: behaviour_ok(p)                             # noqa: E731
    script_mut("no fetch / rebase", 'elif ! git rebase --quiet "origin/$branch"; then', "elif false; then", both)
    script_mut("no retry", 'for i in $(seq 1 "$attempts"); do', "for i in 1; do", run_only)
    script_mut("force-push", 'git push --quiet origin "HEAD:$branch"', 'git push --quiet --force origin "HEAD:$branch"', both)
    script_mut("conflict not aborted", "    git rebase --abort 2>/dev/null || true\n", "", run_only)
    script_mut("success reported on give-up", 'after $attempts attempts"\nexit 1', 'after $attempts attempts"\nexit 0', run_only)
    for name, old, new in (("a bare push back in the data workflow", CALL, "git push"),
                           ("the old pull + push", CALL, "git pull --rebase\n          git push")):
        wf = dict(c.workflows)
        k = "suptracker-data.yml"
        if old not in wf[k]:
            missed.append(f"{name} (anchor lost)")
            continue
        wf[k] = wf[k].replace(old, new, 1)
        if wiring_ok(c, wf)[0]:
            missed.append(name)
        else:
            caught += 1
    for name, kw in (("README", {"readme": ""}), ("CLAUDE.md", {"claude": ""})):
        if docs_ok(c, **kw)[0]:
            missed.append(name)
        else:
            caught += 1
    return not missed, f"mutants caught {caught}/{caught + len(missed)}; missed {missed}"


def run(checks: set | None = None) -> list[dict]:
    c = Ctx()
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail, "s": round(time.time() - t0, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + f" ({r['s']} s)\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
