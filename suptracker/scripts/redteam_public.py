"""Red team: the repository is public (owner, 2026-11-27).

    python scripts/redteam_public.py [--db data/suptracker.duckdb] [--real]

What a public repository must not hold, and what keeps it that way:
  PB1 no e-mail address or phone number in the Parcoursup material the repository keeps (the report and fiche pages kept as
      probes, the live probe, the harvested jury texts, the fiches' texts) nor in the jury texts of the warehouse: the reports
      print the contacts of named staff. Own patterns, not the code's (a phone is never inside a longer run of letters or
      digits: the fiches' hex digests are not phones)
  PB2 report PDFs (signature, contacts) only in the parser's frozen test set (10 official reports, red team rapports R1/R7/R8):
      none elsewhere, the probe writes no new one, the harvest keeps none
  PB3 the writers mask: the harvest's store (crafted report), the build's mask_contacts (nested values), the probe and the live
      probe write through fiche_parse.mask; the build's patterns are the fiche reader's
  PB4 no secret in the tracked files: token formats (GitHub, AWS, Slack, Google, OpenAI / Anthropic, private keys) and the
      site's own variables (Upstash, stats token, analytics salt) assigned a value other than a « demo » one
  PB5 workflows safe in a public repository: no pull_request_target; a workflow a pull request triggers reads no secret, cannot
      write the repository and interpolates no pull-request text in a shell line
  PB6 mutation test: every seeded leak is caught
  PB7 wiring and docs
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []

# own patterns (PB1): an address, a French phone number standing alone (never inside a run of letters, digits or a decimal)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.,])(?:\+33\s?|0)[1-9](?:[ .-]?\d{2}){4}(?![\w])")
KEPT = ("data/rapports", "data/fiches/textes.csv.gz")
QUALI_KEYS = ("criteres", "eds", "options_citees", "eliminatoires", "modalites", "algorithme", "conseils")
BINARY = (".duckdb", ".parquet", ".pdf", ".png", ".jpg", ".woff", ".woff2", ".zip", ".xlsx", ".xls", ".ods")
TOKENS = {
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|github_pat_[A-Za-z0-9_]{50,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "Google key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "OpenAI / Anthropic key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    "site variable": re.compile(r"(?i)\b(KV_REST_API_TOKEN|KV_REST_API_URL|SUPTRACKER_STATS_TOKEN|SUPTRACKER_ANALYTICS_SALT|"
                                r"UPSTASH_REDIS_REST_TOKEN|VERCEL_TOKEN)\s*[=:]\s*['\"]?(?!demo)[A-Za-z0-9_\-:/.]{16,}"),
}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool):
        self.db, self.real = Path(db), real
        self.files = [f for f in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n") if f]


def contacts(text: str) -> list[str]:
    return EMAIL.findall(text) + PHONE.findall(text)


def texts_of(path: Path):
    """(where, text) of a kept file: a gzip of JSON lines gives its jury texts only (digests are hex, never phones)."""
    if path.name == "qualitatif.jsonl.gz":
        with gzip.open(path, "rt", encoding="utf-8") as g:
            for i, line in enumerate(g):
                d = json.loads(line)
                yield f"{path.name}:{i + 1}", json.dumps({k: d.get(k) for k in QUALI_KEYS}, ensure_ascii=False)
    elif path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as g:
            yield path.name, g.read()
    elif path.suffix in (".html", ".txt", ".json", ".jsonl", ".md"):
        yield path.name, path.read_text(encoding="utf-8", errors="ignore")


def kept_leaks(c: Ctx) -> list:
    bad = []
    for f in c.files:
        if not f.startswith(KEPT) or f.endswith(BINARY):
            continue
        for where, t in texts_of(ROOT / f):
            if (found := contacts(t)):
                bad.append((f, where, len(found)))
                break
    return bad


def warehouse_leaks(db: Path) -> list:
    """The jury texts the page serves (rapport_textes.duckdb beside the warehouse, else core.rapport_texte)."""
    import duckdb
    from suptracker import rapports
    bad = []
    for path, table in ((rapports.textes_path(db), "rapport_texte"), (db, "core.rapport_texte")):
        if not Path(path).exists():
            continue
        con = duckdb.connect(str(path), read_only=True)
        try:
            rows = con.execute(f"SELECT digest, data FROM {table}").fetchall()
        except duckdb.Error:
            rows = []
        con.close()
        bad += [(Path(path).name, d[:12]) for d, t in rows if contacts(t or "")]
    return bad


# ------------------------------------------------------------------ PB1
@check("PB1 no staff e-mail address or phone number in the kept Parcoursup material nor in the warehouse's jury texts")
def pb1(c: Ctx):
    kept = kept_leaks(c)
    wh = warehouse_leaks(c.db)
    n = sum(1 for f in c.files if f.startswith(KEPT) and not f.endswith(BINARY))
    return not kept and not wh, f"{n} kept files read; leaks in files {kept[:4]}; in the warehouse's jury texts {len(wh)} {wh[:3]}"


# ------------------------------------------------------------------ PB2
# the parser's test set (red team rapports R1, R7, R8): official reports as Parcoursup published them, kept frozen
PDF_TEST_SET = "data/rapports/probe/pdf/"


@check("PB2 report PDFs only in the parser's frozen test set; the probe writes none, the live harvest keeps none")
def pb2(c: Ctx):
    pdfs = [f for f in c.files if f.lower().endswith(".pdf") and f.startswith("data/rapports")]
    outside = [f for f in pdfs if not f.startswith(PDF_TEST_SET)]
    probe = (ROOT / "scripts" / "rapports_probe.py").read_text()
    writes = re.findall(r"\.write_bytes\(", probe)
    live = (ROOT / "scripts" / "rapports_live.py").read_text() + (ROOT / "scripts" / "rapports_harvest.py").read_text()
    live_pdf = re.findall(r"\.pdf[\"']\)\.write_bytes|write_bytes\(pdf", live)
    return not outside and not writes and not live_pdf and len(pdfs) <= 10, (
        f"{len(pdfs)} PDFs in the test set; outside it {outside[:3]}; PDF writes in the probe {len(writes)}, in the harvest {len(live_pdf)}")


# ------------------------------------------------------------------ PB3
@check("PB3 the writers mask: harvest store, build mask_contacts, probe and live probe through fiche_parse.mask; same patterns")
def pb3(c: Ctx):
    import fiche_parse as FP
    import rapports_harvest as RH
    from suptracker import rapports as RP
    bad = []
    leak = "Contact : jeanne.martin@univ-exemple.fr ou 06 12 34 56 78."
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        r = {"digest": "abc", "timestamp": "20260101000000"}
        p = {"session": 2026, "codes": ["1"], "doublettes": [], "synthese": [], "masked": [],
             **{k: None for k in RH.QUALI}}
        p["conseils"] = leak
        p["criteres"] = [{"champ": "X", "texte": leak, "items": [leak]}]
        RH.store(out, r, p)
        with gzip.open(out / "qualitatif.jsonl.gz", "rt", encoding="utf-8") as g:
            written = g.read()
        if contacts(written) or "dans le rapport Parcoursup" not in written:
            bad.append(("harvest store", contacts(written)[:2]))
    m = json.dumps(RP.mask_contacts({"a": leak, "b": [leak, {"c": leak}], "n": 3}), ensure_ascii=False)
    if contacts(m) or '"n": 3' not in m:
        bad.append(("build mask_contacts", m[:80]))
    if (RP.CONTACT_EMAIL.pattern, RP.CONTACT_PHONE.pattern) != (FP.EMAIL.pattern, FP.PHONE.pattern):
        bad.append("the build's patterns are not the fiche reader's")
    if 'json.dumps({k: mask_contacts(d.get(k)) for k in TEXT_KEYS}' not in (ROOT / "suptracker" / "rapports.py").read_text():
        bad.append("the build does not mask the jury texts")
    probe = (ROOT / "scripts" / "rapports_probe.py").read_text()
    if len(re.findall(r"\.write_text\((?!FP\.mask\()", probe)) != 1 or 'write_text(json.dumps(summary' not in probe:
        bad.append("the probe writes a page or a text unmasked")       # the one unmasked write: its own summary (counts, URLs)
    live = (ROOT / "scripts" / "rapports_live.py").read_text()
    if '(out / "probe.json").write_text(FP.mask(json.dumps(summary' not in live:
        bad.append("the live probe writes unmasked")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ PB4
def token_leaks(files: list[str]) -> list:
    bad = []
    for f in files:
        p = ROOT / f
        if f.endswith(BINARY) or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore") if p.suffix != ".gz" else ""
        except OSError:
            continue
        for name, rx in TOKENS.items():
            if rx.search(t):
                bad.append((f, name))
    return bad


@check("PB4 no secret in the tracked files (token formats, private keys, the site's variables with a real value)")
def pb4(c: Ctx):
    own = {"scripts/redteam_public.py"}                                 # the patterns themselves
    bad = token_leaks([f for f in c.files if f not in own])
    bad += [(n_, n) for n_, t in workflows().items() for n, rx in TOKENS.items() if rx.search(t)]
    return not bad, f"{len(c.files)} tracked files and the workflows read; secrets {bad[:4]}"


# ------------------------------------------------------------------ PB5
def workflow_problems(texts: dict[str, str]) -> list:
    bad = []
    for name, t in texts.items():
        on = t.split("\njobs:", 1)[0]
        if "pull_request_target" in t:
            bad.append((name, "pull_request_target"))
        if re.search(r"(?m)^\s*pull_request:", on):
            if "secrets." in t:
                bad.append((name, "a pull request reads a secret"))
            if re.search(r"contents:\s*write", t):
                bad.append((name, "a pull request can write the repository"))
            if re.search(r"\$\{\{\s*github\.(?:event\.pull_request\.(?:title|body|head\.ref|head\.label)|head_ref)", t):
                bad.append((name, "pull-request text in a shell line"))
    return bad


def workflows() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted((REPO / ".github" / "workflows").glob("*.yml"))}


@check("PB5 workflows public-safe: no pull_request_target; a pull request reads no secret, writes nothing, runs no PR text")
def pb5(c: Ctx):
    w = workflows()
    bad = workflow_problems(w)
    pr = [n for n, t in w.items() if re.search(r"(?m)^\s*pull_request:", t.split("\njobs:", 1)[0])]
    return not bad and pr == ["suptracker.yml"], f"{len(w)} workflows; triggered by a pull request {pr}; problems {bad}"


# ------------------------------------------------------------------ PB6
@check("PB6 mutation test: every seeded leak is caught by PB1-PB5")
def pb6(c: Ctx):
    missed = []
    leak = "Contact : jeanne.martin@univ-exemple.fr ou 06 12 34 56 78."
    # PB1: the patterns find a leak in a jury text, and miss a hex digest
    if not contacts(json.dumps({"conseils": leak})) or contacts("6ef0986814332abe 18.0123456789"):
        missed.append("PB1 patterns")
    # PB3: the harvest writer unmasked, the build identity, the probe writing raw text
    import rapports_harvest as RH
    from suptracker import rapports as RP
    saved = RH.masked, RP.mask_contacts
    try:
        RH.masked = lambda v: v
        if pb3(c)[0]:
            missed.append("harvest store unmasked")
        RH.masked = saved[0]
        RP.mask_contacts = lambda v: v
        if pb3(c)[0]:
            missed.append("build mask_contacts identity")
    finally:
        RH.masked, RP.mask_contacts = saved
    # PB4: a token, a private key, a real stats token are flagged; a demo value is not (seeded strings, built here)
    for name, text in (("a GitHub token", "token = ghp_" + "A1b2C3d4" * 4 + "Zz9Y"),
                       ("a private key", "-----BEGIN OPENSSH " + "PRIVATE KEY-----"),
                       ("a real stats token", "SUPTRACKER_STATS_TOKEN=" + "Xk29fjsl20sjdk20sldk")):
        if not any(rx.search(text) for rx in TOKENS.values()):
            missed.append(name)
    if any(rx.search("SUPTRACKER_STATS_TOKEN=demo-token-for-local-runs") for rx in TOKENS.values()):
        missed.append("a demo value flagged")
    # PB5: seeded workflow risks
    ci = workflows()["suptracker.yml"]
    for name, mutated in (("pull_request_target", ci.replace("  pull_request:\n", "  pull_request_target:\n", 1)),
                          ("a PR reads a secret", ci.replace("    steps:\n", "    env:\n      T: ${{ secrets.KV_REST_API_TOKEN }}\n    steps:\n", 1)),
                          ("a PR can write", ci.replace("jobs:\n", "permissions:\n  contents: write\njobs:\n", 1)),
                          ("PR title in a shell", ci.replace("      - run: pip install", "      - run: echo \"${{ github.event.pull_request.title }}\"\n      - run: pip install", 1))):
        if mutated == ci or not workflow_problems({"suptracker.yml": mutated}):
            missed.append(name)
    # PB2: a PDF write back in the probe
    probe = (ROOT / "scripts" / "rapports_probe.py").read_text()
    if not re.findall(r"\.write_bytes\(", probe + '\n(dest / "pdf" / "x.pdf").write_bytes(r.content)'):
        missed.append("PDF write")
    return not missed, f"missed {missed}"


# ------------------------------------------------------------------ PB7
@check("PB7 wiring and docs: test file and CI duration, README section, CLAUDE.md rule")
def pb7(c: Ctx):
    bad = []
    if not (ROOT / "tests" / "test_public.py").exists():
        bad.append("tests/test_public.py")
    if '"tests/test_public.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("CI duration")
    if "## The repository is public (owner, 2026-11-27)" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**Public repository (owner, 2026-11-27).**" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    return not bad, f"problems {bad}"


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
