"""CI sharding: `--shard i/n` keeps the test FILES of shard i (1-based) of n.

Files are spread by their measured duration (tests/durations.json, seconds per file), heaviest first onto the
lightest shard. A file missing from durations.json still runs: it gets DEFAULT seconds and a shard like any other.
Every shard collects the same files (same command), so the plan is the same on every runner and each file runs in
exactly one shard (tests/test_shards.py checks it).
"""
from __future__ import annotations

import json
from pathlib import Path

DURATIONS = Path(__file__).with_name("durations.json")
DEFAULT = 120.0


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="i/n: run only the test files of shard i of n")


def weights() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(DURATIONS.read_text()).items()}
    except (OSError, ValueError):
        return {}


def plan(files, n: int, w: dict[str, float] | None = None) -> dict[str, int]:
    """file -> shard index (0-based). Longest first onto the least loaded shard; ties broken by name and index."""
    w = weights() if w is None else w
    loads, out = [0.0] * n, {}
    for f in sorted(set(files), key=lambda f: (-w.get(f, DEFAULT), f)):
        k = min(range(n), key=lambda i: (loads[i], i))
        out[f] = k
        loads[k] += w.get(f, DEFAULT)
    return out


def parse(spec: str) -> tuple[int, int]:
    i, n = (int(x) for x in spec.split("/"))
    if not 1 <= i <= n:
        raise ValueError(f"--shard {spec}: expected i/n with 1 <= i <= n")
    return i, n


def pytest_collection_modifyitems(config, items):
    spec = config.getoption("--shard")
    if not spec:
        return
    i, n = parse(spec)
    files = [it.nodeid.split("::")[0] for it in items]
    where = plan(files, n)
    keep = [it for it, f in zip(items, files) if where[f] == i - 1]
    drop = [it for it, f in zip(items, files) if where[f] != i - 1]
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep
