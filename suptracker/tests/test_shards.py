"""CI sharding (tests/conftest.py): every test file runs in exactly one shard, and the durations table stays current."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import conftest as C  # noqa: E402

CI = ROOT.parent / ".github" / "workflows" / "suptracker.yml"


def test_plan_is_a_partition_and_balanced():
    files = [f"tests/t{i}.py" for i in range(9)]
    w = {f: float(i + 1) for i, f in enumerate(files)}
    for n in range(1, 6):
        p = C.plan(files, n, w)
        assert sorted(p) == sorted(files) and set(p.values()) <= set(range(n))
    p = C.plan(files, 3, w)                                   # 45 s over 3 shards: within one file of 15 s each
    loads = [sum(w[f] for f in files if p[f] == k) for k in range(3)]
    assert sum(loads) == 45 and max(loads) - min(loads) <= max(w.values()), loads
    assert C.plan(files + ["tests/new.py"], 2, w)["tests/new.py"] in (0, 1)      # an unmeasured file still runs


def collected(*args):
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    return {ln.split("::")[0] for ln in r.stdout.splitlines() if "::" in ln}


def test_every_file_runs_in_exactly_one_ci_shard():
    ci = CI.read_text()
    n = int(re.search(r"shard:\s*\[([\d, ]+)\]", ci).group(1).split(",")[-1])
    ignore = re.findall(r"--ignore=(\S+)", ci)
    base = [f"--ignore={x}" for x in ignore]
    every = collected(*base)
    parts = [collected(*base, f"--shard={i}/{n}") for i in range(1, n + 1)]
    assert every and set().union(*parts) == every, sorted(every - set().union(*parts))
    assert sum(len(p) for p in parts) == len(every), "a file runs in two shards"
    assert all(parts), "an empty shard"


def test_durations_table_lists_the_parallel_files():
    w = json.loads(C.DURATIONS.read_text())
    ci = CI.read_text()
    timed = set(re.findall(r"--ignore=(\S+)", ci))
    files = {f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py")} - timed
    assert set(w) == files, f"add to tests/durations.json: {sorted(files - set(w))}; drop: {sorted(set(w) - files)}"


def test_build_cache_key_follows_every_input(tmp_path, monkeypatch):
    """tests/synthetic.py cached_build: same inputs share one build; any changed input is a new build."""
    from synthetic import _inputs_key, make_raw
    a, b = tmp_path / "a" / "raw", tmp_path / "b" / "raw"
    make_raw(a)
    make_raw(b)
    assert _inputs_key(a, {}) == _inputs_key(b, {})                                   # same content, another folder
    assert _inputs_key(a, {"success_source": None}) != _inputs_key(a, {})               # another argument
    f = sorted(p for p in b.rglob("*") if p.is_file())[0]
    f.write_bytes(f.read_bytes() + b"x")
    assert _inputs_key(a, {}) != _inputs_key(b, {})                                   # a raw file changed
    x, y = tmp_path / "x.xlsx", tmp_path / "y.xlsx"
    x.write_bytes(b"1")
    y.write_bytes(b"2")
    assert _inputs_key(a, {"success_source": x}) != _inputs_key(a, {"success_source": y})   # an argument file's content
    ext = tmp_path / "ext"                                                             # a data directory outside the repository
    (ext / "sources").mkdir(parents=True)
    monkeypatch.setenv("SUPTRACKER_DATA", str(ext))
    k1 = _inputs_key(a, {})
    (ext / "sources" / "new.xlsx").write_bytes(b"1")
    assert _inputs_key(a, {}) != k1                                                   # a source added there (Codex, PR #42)
