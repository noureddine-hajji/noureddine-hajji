"""Run Node on a program written to a file, never as an `-e` argument (lot 1, PR 9, owner 2026-11-26).

Linux caps ONE argv string at 128 KiB (MAX_ARG_STRLEN): a red team that passes `node -e <program>` breaks with
« Argument list too long » as soon as the page block it extracts grows past it (rapports R4, audit PR 8). `run` takes
the same arguments as `subprocess.run` and, when they are `[node, "-e", program, *args]`, writes the program to a
temporary .js file and runs `[node, file, *args]` instead: same stdin, stdout, stderr, return code, environment and
timeout, the same `process.argv` (the file's own path is removed) and the same module resolution (`require` from the working
directory, as `node -e` does). Any other command is passed to `subprocess.run` unchanged. Every red team calls Node through it (red team
redteam_outillage.py OU2).
"""
from __future__ import annotations

import os
import subprocess
import tempfile


PRELUDE = "process.argv.splice(1, 1); require = require('module').createRequire(process.cwd() + '/'); "


def run(args, *a, **kw):
    """subprocess.run, with a `-e` program moved to a temporary file (deleted afterwards, whatever happens)."""
    args = list(args)
    if len(args) >= 3 and args[1] == "-e" and isinstance(args[2], str):
        fd, path = tempfile.mkstemp(suffix=".js", prefix="rt_node_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # `node -e` gives process.argv = [node, *args]; a file adds its own path: drop it. `node -e` resolves
                # require() from the working directory (its node_modules, then NODE_PATH); a file in /tmp would resolve
                # from /tmp: rebind require to the working directory (Codex, PR #119). One line: stack traces keep
                # the program's own line numbers.
                f.write(PRELUDE + args[2])
            return subprocess.run([args[0], path, *args[3:]], *a, **kw)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    return subprocess.run(args, *a, **kw)
