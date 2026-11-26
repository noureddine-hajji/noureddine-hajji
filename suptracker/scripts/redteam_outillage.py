"""Red team of the anti-breakage tooling (lot 1, PR 9, owner 2026-11-26): scripts/nodefile.py and scripts/blast.py.

    python scripts/redteam_outillage.py

  OU1 nodefile.run = subprocess.run of `node -e` on the same program: stdout, stderr, return code, stdin, environment,
      process.argv; a 300 KiB program that `-e` refuses (« Argument list too long ») runs; the temporary file is removed,
      after a success, an error and a timeout
  OU2 every script runs Node through nodefile: no `subprocess.run([<node>, "-e", <program>]` left in scripts/ (AST scan),
      every caller imports it
  OU3 blast.py on a crafted git repository: a red team holding a line the diff removes is « certain », one naming a
      touched JS function or a called Python function is « possible », an unrelated one is absent, a Python name used only
      as a word of a sentence does not count; the test file importing a hit red team is listed
  OU4 blast.py replayed on audit PR 8's first commit (6486067 -> acb3e8b, red teams as they were): all ten red teams that
      broke in CI are named, at least seven « certain » (skipped when the history is not in the clone, as in CI)
  OU5 mutation test of OU1-OU4 and OU6 (mutants built in memory)
  OU6 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
BROKE_IN_PR8 = ("vitesse", "carte", "carterecherche", "masque", "reorientation", "admis", "securite_large", "ux", "multiples", "liste")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self):
        self.src = {k: (ROOT / "scripts" / f"{k}.py").read_text() for k in ("nodefile", "blast")}
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (REPO / "CLAUDE.md").read_text() if (REPO / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.scripts = {p: Path(p).read_text() for p in glob.glob(str(ROOT / "scripts" / "*.py"))}

    def mod(self, k):
        m = types.ModuleType(f"{k}_ou")
        m.__file__ = str(ROOT / "scripts" / f"{k}.py")
        exec(compile(self.src[k], m.__file__, "exec"), m.__dict__)
        return m


def tmp_count() -> int:
    return len(glob.glob(os.path.join(tempfile.gettempdir(), "rt_node_*.js")))


# ------------------------------------------------------------------ OU1
PROG = """const fs = require('fs'); const d = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stderr.write('E' + d.x); process.stdout.write(JSON.stringify([process.argv.slice(1), d.x, process.env.OU_VAR || null]));
process.exit(d.code);"""


@check("OU1 nodefile.run = node -e: stdout, stderr, code, stdin, env, argv; a 300 KiB program runs; the temp file is always removed")
def ou1(c: Ctx):
    nf = c.mod("nodefile")
    exe = shutil.which("node")
    if not exe:
        return True, "skipped (node not installed)"
    bad = []
    before = tmp_count()
    for code in (0, 3):
        kw = dict(input=json.dumps({"x": "é<b>", "code": code}), capture_output=True, text=True, timeout=60, env={**os.environ, "OU_VAR": "v"})
        a = subprocess.run([exe, "-e", PROG, "a1", "--b"], **kw)
        b = nf.run([exe, "-e", PROG, "a1", "--b"], **kw)
        if (a.stdout, a.stderr, a.returncode) != (b.stdout, b.stderr, b.returncode):
            bad.append(("differs", code, a.stdout, b.stdout, a.returncode, b.returncode))
    big = "// " + "x" * 300_000 + "\nprocess.stdout.write('ok')"
    try:
        subprocess.run([exe, "-e", big], capture_output=True, text=True, timeout=60)
        refused = False
    except OSError:
        refused = True
    r = nf.run([exe, "-e", big], capture_output=True, text=True, timeout=60)
    if r.stdout != "ok":
        bad.append(("big program", r.stdout[:40], r.stderr[-120:]))
    try:
        nf.run([exe, "-e", "while (true) {}"], capture_output=True, text=True, timeout=1)
        bad.append("no timeout raised")
    except subprocess.TimeoutExpired:
        pass
    r2 = nf.run([exe, "--version"], capture_output=True, text=True)
    if not r2.stdout.startswith("v"):
        bad.append("a plain command is not passed through")
    if tmp_count() != before:
        bad.append(("temporary files left", tmp_count() - before))
    return not bad, f"-e refuses 300 KiB: {refused}; problems {bad[:3]}"


# ------------------------------------------------------------------ OU2
def node_e_calls(src: str) -> list[int]:
    """Lines of `subprocess.run([...,"-e", ...])` (the forbidden form)."""
    import ast
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [-1]
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess" and n.args \
                and isinstance(n.args[0], ast.List) and len(n.args[0].elts) >= 2 \
                and isinstance(n.args[0].elts[1], ast.Constant) and n.args[0].elts[1].value == "-e":
            out.append(n.lineno)
    return out


@check("OU2 every script runs Node through nodefile: no subprocess.run([node, \"-e\", …]) left, every caller imports it")
def ou2(c: Ctx):
    bad = []
    users = 0
    for p, src in sorted(c.scripts.items()):
        name = Path(p).name
        if name in ("nodefile.py", "redteam_outillage.py"):
            continue
        lines = node_e_calls(src)
        if lines:
            bad.append((name, lines[:3]))
        if "nodefile.run(" in src:
            users += 1
            if not re.search(r"^import nodefile\b", src, re.M):
                bad.append((name, "uses nodefile without importing it"))
    return not bad and users >= 50, f"{users} scripts run Node through nodefile; problems {bad[:5]}"


# ------------------------------------------------------------------ OU3
APP_OLD = """function keepMe(a) {
  return a + 1;
}
function changeMe(x) {
  const label = "Formation visée : ancienne ligne";
  return label + x;
}
const SOME_CONST = 3;
function goneSoon(y) {
  return y * 2;
}
"""
APP_NEW = APP_OLD.replace('const label = "Formation visée : ancienne ligne";', 'const label = "Formation visée : nouvelle ligne";') \
    .replace("function goneSoon(y) {\n  return y * 2;\n}\n", "")
PY_OLD = '''def voeux(x):
    return x


def compute_total(a, b):
    return a + b
'''
PY_NEW = PY_OLD.replace("return a + b", "return a + b + 0")
RT = {
    "redteam_anchor.py": 'ANCHOR = "Formation visée : ancienne ligne"\n',
    "redteam_name.py": 'import subprocess\nPROG = "top(js, \\"changeMe\\")"\n',
    "redteam_call.py": "from suptracker import mod\nmod.compute_total(1, 2)\n",
    "redteam_word.py": 'TEXT = "the compute_total of the vœux shown"\n',
    "redteam_other.py": 'X = "keepMe is unrelated"\n',
    "redteam_gone.py": 'NAMES = ("goneSoon",)\n',
}
TESTS = {"test_anchor.py": "import redteam_anchor as R\n", "test_other.py": "import redteam_other as R\n"}


def crafted_repo(d: Path):
    g = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, text=True, check=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.email", "rt@example.invalid")
    g("config", "user.name", "rt")
    (d / "suptracker" / "suptracker" / "static").mkdir(parents=True)
    (d / "suptracker" / "scripts").mkdir()
    (d / "suptracker" / "tests").mkdir()
    (d / "suptracker" / "suptracker" / "static" / "app.js").write_text(APP_OLD)
    (d / "suptracker" / "suptracker" / "mod.py").write_text(PY_OLD)
    for k, v in RT.items():
        (d / "suptracker" / "scripts" / k).write_text(v)
    for k, v in TESTS.items():
        (d / "suptracker" / "tests" / k).write_text(v)
    g("add", "-A")
    g("commit", "-q", "-m", "base")
    (d / "suptracker" / "suptracker" / "static" / "app.js").write_text(APP_NEW)
    (d / "suptracker" / "suptracker" / "mod.py").write_text(PY_NEW)
    return g("rev-parse", "HEAD").stdout.strip()


@check("OU3 blast on a crafted repo: removed anchor = certain, touched name = possible, a word in a sentence or an unrelated red team = absent")
def ou3(c: Ctx):
    bl = c.mod("blast")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        base = crafted_repo(d)
        found = bl.scan(base, cwd=d)
        hits = {h["file"]: h for h in bl.readers(found, root=d / "suptracker")}
        tests = bl.tests_for(list(hits.values()), root=d / "suptracker")
    bad = []
    want = {"scripts/redteam_anchor.py": "certain", "scripts/redteam_name.py": "possible", "scripts/redteam_call.py": "possible",
            "scripts/redteam_gone.py": "possible"}          # a function the diff deletes is read in the OLD file
    for f, tier in want.items():
        if f not in hits or hits[f]["tier"] != tier:
            bad.append((f, hits.get(f, {}).get("tier"), tier))
    for f in ("scripts/redteam_word.py", "scripts/redteam_other.py"):
        if f in hits:
            bad.append((f, "listed", hits[f]["why"]))
    # a deletion's hunk may start on the line before (git's choice): a neighbour may be listed, an untouched far one never
    if not {"changeMe", "goneSoon"} <= found["names"]["js"] or "keepMe" in found["names"]["js"] or "compute_total" not in found["names"]["py"] or "voeux" in found["names"]["py"]:
        bad.append(("names", sorted(found["names"]["js"]), sorted(found["names"]["py"])))
    if "tests/test_anchor.py" not in tests or "tests/test_other.py" in tests:
        bad.append(("tests", tests))
    return not bad, f"hits {sorted((f, h['tier']) for f, h in hits.items())}; problems {bad}"


# ------------------------------------------------------------------ OU4
@check("OU4 blast replayed on audit PR 8 (6486067 -> acb3e8b): every red team that broke in CI is named, >= 7 certain")
def ou4(c: Ctx):
    have = subprocess.run(["git", "cat-file", "-e", "6486067^{commit}"], cwd=REPO, capture_output=True).returncode == 0 \
        and subprocess.run(["git", "cat-file", "-e", "acb3e8b^{commit}"], cwd=REPO, capture_output=True).returncode == 0
    if not have:
        return True, "skipped (audit PR 8's commits are not in this clone)"
    bl = c.mod("blast")
    found = bl.scan("6486067", head="acb3e8b")
    hits = {h["file"]: h["tier"] for h in bl.readers(found, at="6486067")}
    missed = [b for b in BROKE_IN_PR8 if f"scripts/redteam_{b}.py" not in hits]
    certain = [b for b in BROKE_IN_PR8 if hits.get(f"scripts/redteam_{b}.py") == "certain"]
    return not missed and len(certain) >= 7, f"named {len(BROKE_IN_PR8) - len(missed)}/10, certain {certain}; missed {missed}; {len(hits)} files listed"


# ------------------------------------------------------------------ OU6
def docs_ok(c: Ctx, readme=None, claude=None, durations=None) -> list[str]:
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    durations = c.durations if durations is None else durations
    bad = []
    if "## Anti-breakage tooling (lot 1, PR 9" not in readme:
        bad.append("README section")
    if "**Anti-breakage tooling (lot 1, PR 9" not in claude or "scripts/blast.py" not in claude or "nodefile" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_outillage.py").exists() or '"tests/test_outillage.py"' not in durations:
        bad.append("test file or its CI duration")
    return bad


@check("OU6 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration")
def ou6(c: Ctx):
    bad = docs_ok(c)
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ OU5
MUTANTS = [
    ("nodefile", "OU1", "argv keeps the file path", 'f.write("process.argv.splice(1, 1); " + args[2])', "f.write(args[2])"),
    ("nodefile", "OU1", "the program still passed by -e", "return subprocess.run([args[0], path, *args[3:]], *a, **kw)",
     "return subprocess.run(args, *a, **kw)"),
    ("nodefile", "OU1", "the temporary file left behind", "                os.unlink(path)", "                pass"),
    ("blast", "OU3", "anchors never certain", "                    sure = True", "                    sure = False"),
    ("blast", "OU3", "a Python word counts as a use", '(word(n, src) if kind == "js" else py_use(n, src))', "word(n, src)"),
    ("blast", "OU3", "the old file's functions ignored", "names[kind] |= touched(units(old), olds) | touched(units(new), news)",
     "names[kind] |= touched(units(new), news)"),
    ("blast", "OU3", "a removed anchor ignored", "if len(frag) >= MIN_FRAG and frag in old and frag not in new:",
     "if len(frag) >= MIN_FRAG and frag in old and frag in new:"),
    ("blast", "OU3", "test files of a hit red team not listed", "        if any(re.search(", "        if False and any(re.search("),
    ("blast", "OU4", "long anchors only", "MIN_FRAG = 16", "MIN_FRAG = 60"),
]


@check("OU5 mutation test: nodefile and blast bugs are each caught")
def ou5(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name[:3] in ("OU1", "OU3", "OU4", "OU6") and not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    history = "skipped" not in by["OU4"](c)[1]        # without audit PR 8's commits the OU4 mutant cannot be judged
    caught, missed, total = 0, [], 0
    for kind, target, name, old, new in MUTANTS:
        if target == "OU4" and not history:
            continue
        total += 1
        if c.src[kind].count(old) != 1:
            missed.append(f"{name} (anchor found {c.src[kind].count(old)} times)")
            continue
        m = copy.copy(c)
        m.src = dict(c.src, **{kind: c.src[kind].replace(old, new, 1)})
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    for name, kw in (("README", {"readme": ""}), ("CLAUDE.md", {"claude": ""}), ("CI duration", {"durations": "{}"})):
        total += 1
        caught += bool(docs_ok(c, **kw))
        if not docs_ok(c, **kw):
            missed.append(name)
    return not missed, f"{caught}/{total} caught; missed {missed}"


def run(checks: set | None = None) -> list[dict]:
    c = Ctx()
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
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1200])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
