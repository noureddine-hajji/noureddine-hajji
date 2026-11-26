"""Blast radius of a change: the red teams and test files that read the code a diff touches (lot 1, PR 9, owner 2026-11-26).

    python scripts/blast.py [--base origin/main] [--head <commit>] [--readers-at <commit>] [--run [--certain]] [--json]

Red teams pin page and server code by NAME (a function they extract and run in Node or import) and by exact TEXT (an
anchor they look for, a line a mutant rewrites). Audit PR 8 needed four extra CI rounds because nine red teams read code
it had rewritten and nobody ran them before pushing. This script reads `git diff <base>` (committed, staged and working
changes) and finds:

  1. the top-level JS functions/consts (`function f(`, `const f =`) and the Python functions (`def f`) whose body a
     hunk changes, in the old or the new file;
  2. the text fragments a red team holds verbatim (its string literals of >= 16 characters) that appear in the OLD
     file but no longer in the NEW one: such a red team is « certain » to need a look; one that only names a touched
     function is « possible »;
then lists every red team script (scripts/redteam_*.py) and test file concerned, with the reason and the tier. `--run` runs their test files (pytest -n auto --dist loadfile; each reads the real
warehouse too when it is present), `--certain` only those of the « certain » red teams. Replayed on audit PR 8's first commit (`--base 6486067 --head
acb3e8b --readers-at 6486067`) it names all ten red teams that broke in CI, seven of them « certain ». Red team
redteam_outillage.py (OU3-OU5) checks it.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CODE = (".js", ".py")
MIN_FRAG = 16


def git(*args, cwd=REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def rng(base: str, head: str | None) -> list[str]:
    return [base, head] if head else [base]


def changed_files(base: str, cwd=REPO, head: str | None = None) -> list[str]:
    out = git("diff", "--name-only", *rng(base, head), cwd=cwd)
    return [f for f in out.splitlines() if f.endswith(CODE) and "/scripts/" not in f and "/tests/" not in f
            and not f.startswith(("scripts/", "tests/"))]


def old_text(base: str, path: str, cwd=REPO) -> str:
    try:
        return git("show", f"{base}:{path}", cwd=cwd)
    except subprocess.CalledProcessError:
        return ""


def new_text(path: str, cwd=REPO, head: str | None = None) -> str:
    if head:
        return old_text(head, path, cwd)
    p = Path(cwd) / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def hunks(base: str, path: str, cwd=REPO, head: str | None = None) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[str]]:
    """(old line ranges, new line ranges, removed lines) of a file's diff."""
    out = git("diff", "-U0", *rng(base, head), "--", path, cwd=cwd)
    olds, news, removed = [], [], []
    for line in out.splitlines():
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            o, oc, n, nc = int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)
            olds.append((o, o + max(oc, 1) - 1))
            news.append((n, n + max(nc, 1) - 1))
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())
    return olds, news, removed


# ---------------------------------------------------------------- the units of a file (name -> line span)
JS_START = re.compile(r"^(?:async )?function (\w+)\(|^const (\w+) = ", re.M)


def js_units(src: str) -> list[tuple[str, int, int]]:
    """Top-level JS functions and consts with their 1-based line spans (a unit ends where the next one starts)."""
    marks = [(m.group(1) or m.group(2), src.count("\n", 0, m.start()) + 1) for m in JS_START.finditer(src)]
    total = src.count("\n") + 1
    return [(name, a, (marks[i + 1][1] - 1) if i + 1 < len(marks) else total) for i, (name, a) in enumerate(marks)]


def py_units(src: str) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return [(n.name, n.lineno, n.end_lineno) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]


def touched(units, ranges) -> set[str]:
    return {name for name, a, b in units for lo, hi in ranges if lo <= b and hi >= a}


def scan(base: str, cwd=REPO, head: str | None = None) -> dict:
    """What the diff touches: functions (by file kind) and vanished text fragments."""
    names: dict[str, set] = {"js": set(), "py": set()}
    removed: list[str] = []
    files = changed_files(base, cwd, head)
    olds_all = {}
    for f in files:
        old, new = old_text(base, f, cwd), new_text(f, cwd, head)
        olds, news, rem = hunks(base, f, cwd, head)
        units = js_units if f.endswith(".js") else py_units
        kind = "js" if f.endswith(".js") else "py"
        names[kind] |= touched(units(old), olds) | touched(units(new), news)
        removed += [r for r in rem if len(r) >= MIN_FRAG]
        olds_all[f] = (old, new)
    return {"files": files, "names": names, "removed": removed, "texts": olds_all}


def literals(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) >= MIN_FRAG]


def word(name: str, src: str) -> bool:
    return re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", src) is not None


def py_use(name: str, src: str) -> bool:
    """A Python name read as code, not as a word of a sentence: called, an attribute, or imported."""
    n = re.escape(name)
    return re.search(rf"(?<![\w$]){n}\s*\(|\.{n}(?![\w$])|\bimport [^\n]*(?<![\w$]){n}(?![\w$])", src) is not None


def sources(root: Path = ROOT, at: str | None = None) -> list[tuple[str, str]]:
    """(relative path, text) of every red team and test file, in the working tree or as they were at a commit."""
    if not at:
        rels = [str(p.relative_to(root)) for p in sorted(root.glob("scripts/redteam_*.py")) + sorted(root.glob("tests/test_*.py"))]
        return [(r, (root / r).read_text(encoding="utf-8")) for r in rels]
    prefix = str(root.relative_to(REPO)) + "/" if root != REPO else ""
    listed = git("ls-tree", "-r", "--name-only", at, "--", prefix + "scripts", prefix + "tests").splitlines()
    out = []
    for f in listed:
        rel = f[len(prefix):]
        if re.fullmatch(r"scripts/redteam_\w+\.py|tests/test_\w+\.py", rel):
            out.append((rel, old_text(at, f)))
    return out


def readers(found: dict, root: Path = ROOT, at: str | None = None) -> list[dict]:
    """Every red team / test file that reads what the diff touched, with its reasons: « certain » when a text it holds
    verbatim is gone from the code, « possible » when it only names a touched function."""
    out = []
    for rel, src in sources(root, at):
        why, sure = [], False
        for kind in ("js", "py"):
            for n in sorted(found["names"][kind]):
                if len(n) >= 4 and (word(n, src) if kind == "js" else py_use(n, src)):
                    why.append(f"{kind} {n}")
        lits = literals(src)
        for f, (old, new) in found["texts"].items():
            for lit in lits:
                frag = lit.strip()
                if len(frag) >= MIN_FRAG and frag in old and frag not in new:
                    why.append(f"anchor gone from {Path(f).name}: {frag[:60]!r}")
                    sure = True
        if why:
            out.append({"file": rel, "tier": "certain" if sure else "possible", "why": sorted(set(why))})
    return sorted(out, key=lambda h: (h["tier"] != "certain", h["file"]))


def tests_for(hits: list[dict], root: Path = ROOT) -> list[str]:
    """The test files to run: each hit test file, and the test files that import a hit red team."""
    files = {h["file"] for h in hits if h["file"].startswith("tests/")}
    rts = {Path(h["file"]).stem for h in hits if h["file"].startswith("scripts/")}
    for t in sorted(root.glob("tests/test_*.py")):
        src = t.read_text(encoding="utf-8")
        if any(re.search(rf"\bimport {rt}\b|\bfrom {rt} import\b|\b{rt}\b", src) for rt in rts):
            files.add(str(t.relative_to(root)))
    return sorted(files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default=None, help="a commit to compare with (default: the working tree)")
    ap.add_argument("--run", action="store_true", help="run the test files of the red teams found")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--readers-at", default=None, help="read the red teams as they were at this commit (replaying a past diff)")
    ap.add_argument("--certain", action="store_true", help="with --run: only the red teams whose anchors are gone")
    a = ap.parse_args(argv)
    found = scan(a.base, head=a.head)
    hits = readers(found, at=a.readers_at)
    tests = tests_for([h for h in hits if h["tier"] == "certain"] if a.certain else hits)
    if a.json:
        print(json.dumps({"files": found["files"], "names": {k: sorted(v) for k, v in found["names"].items()},
                          "readers": hits, "tests": tests}, ensure_ascii=False, indent=1))
    else:
        print(f"changed code files: {found['files']}")
        print(f"touched: js {sorted(found['names']['js'])[:40]} | py {sorted(found['names']['py'])[:40]}")
        for h in hits:
            print(f"  [{h['tier']}] {h['file']}: {'; '.join(h['why'][:4])}{' …' if len(h['why']) > 4 else ''}")
        print(f"test files to run ({len(tests)}): {' '.join(tests)}")
    if a.run and tests:
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-n", "auto", "--dist", "loadfile", *tests], cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
