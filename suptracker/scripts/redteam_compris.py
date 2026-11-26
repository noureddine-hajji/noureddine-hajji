"""Red team of lot 1, PR 13 (owner, 2026-11-26): the search says what it understood, and « tous vos mots » before the distance.

    python scripts/redteam_compris.py [--db data/suptracker.duckdb] [--real] [--browser]

The 2026-11-25 audit (Léa): « licence économie gestion » with « Autour de ma ville » listed licences of any mention first,
sorted by distance, and the chip said « Mot compris : licence » (she read « only licence was understood »). The engine already
ranked « Économie et gestion » first; the page sorted by distance before relevance. Now:

  SC1 server, re-derived: /api/search/codes' `mots` = for each code (in its order), how many typed word groups
      (search.offer_terms: a word, or an acronym's own label phrases) its best result's names carry (filière, mention, labels,
      establishment; NEVER the broad domain « Droit-économie-gestion », never a place word), re-counted here with an own
      folding; aligned with the codes; a bare code gets zeros
  SC2 the sort (static): figures first, then with a keyword the words carried (more first), then distance, the engine's rank,
      the name; never a figure
  SC3 the chips (Node): the recognised words with their kind (« Mot compris », « Lieu »…), every other typed word under « Mots
      cherchés » as typed (accents kept), escaped; around a town, the order said in words; never an internal label
  SC4 browser (--browser, nightly): Léa's search around Lyon lists « Economie et gestion » first; the chips name both words;
      0 JS error
  SC5 mutation test: every seeded return of the audit defect is caught by SC1-SC3
  SC6 wiring and docs
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []

import redteam_chiffres as CH  # noqa: E402
import redteam_unchiffre as UC  # noqa: E402

top = CH.top
HOSTILE = '<img src=x onerror="alert(1)">'
QUERIES = ["licence economie gestion", "licence économie gestion lyon", "bts ndrc", "but informatique", "cpge mpsi", "licence psycho",
           "ecole de commerce", "droit sorbonne",
           # Codex (PR #123): a place of several words is split into words by offer_terms; none of them may count
           "licence aix en provence", "bts saint denis", "droit clermont-ferrand"]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx(CH.Ctx):
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        super().__init__(db, real, browser)
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()


def my_fold(s) -> str:
    """Own folding (not search.fold): accents and case off, every non letter-digit a space."""
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


# ------------------------------------------------------------------ SC1
@check("SC1 server, re-derived: each code's count of typed word groups its names carry (never the domain, never a place), aligned")
def sc1(c: Ctx):
    from suptracker import search as S
    bad, n = [], 0
    with CH.client(c.db) as (tc, api):
        for q in QUERIES + ["10005" if c.real else "1"]:
            r = tc.get("/api/search/codes", params={"q": q})
            if r.status_code != 200:
                continue
            d = r.json()
            if len(d.get("mots", [])) != len(d["codes"]):
                bad.append((q, "not aligned"))
                continue
            if q.isdigit():
                if any(d["mots"]):
                    bad.append((q, "a bare code carries words"))
                continue
            res = S.search(c.con.cursor(), q, offset=0, limit=10 ** 6)
            first = {}
            for x in res["results"]:
                first.setdefault(x["cod_aff_form"], x)
            places = {my_fold(i["value"]) for i in res.get("interpretation", []) if i.get("type") == "lieu"}
            place_words = {w for p in places for w in p.split()}
            groups = [g for g in S.offer_terms(q) if not any(my_fold(a) and set(my_fold(a).split()) <= place_words for a in g)]
            if any(set(my_fold(a).split()) <= place_words for g in api.word_groups(q, res.get("interpretation")) for a in g):
                bad.append((q, "a word of the place counted"))
            for cod, m in zip(d["codes"], d["mots"]):
                x = first[cod]
                text = " " + my_fold(" ".join(str(x.get(k) or "") for k in ("fili", "fil_lib_voe_acc", "lib_for_voe_ins", "lib_comp_voe_ins", "g_ea_lib_vx"))) + " "
                want = sum(any((" " + my_fold(a) + " ") in text if a.startswith(" ") else my_fold(a) in text for a in g) for g in groups)
                n += 1
                if want != m:
                    bad.append((q, cod, m, want))
                    break
            if places and any(m > len(groups) for m in d["mots"]):
                bad.append((q, "a place counted"))
    if 'MOTS_FIELDS = ("fili", "fil_lib_voe_acc", "lib_for_voe_ins", "lib_comp_voe_ins", "g_ea_lib_vx")' not in c.api_src:
        bad.append("the counted fields changed (the domain must stay out)")
    return not bad and n > 50, f"{n} codes re-counted over {len(QUERIES)} queries; problems {bad[:4]}"


# ------------------------------------------------------------------ SC2
@check("SC2 the sort: figures first, then (keyword) words carried, then distance, rank, name; never a figure")
def sc2(c: Ctx):
    import redteam_recherche as RS
    ok, d = RS.order_ok(c.js)
    vc = c.js[c.js.index("async function viewCarte("):]
    if "mots: new Map(Array.isArray(d.mots) && d.mots.length === d.codes.length ? d.codes.map((c, i) => [c, d.mots[i]]) : [])," not in vc:
        return False, "the page does not read the server's counts (or trusts a misaligned answer)"
    return ok, d


# ------------------------------------------------------------------ SC3
@check("SC3 the chips: recognised words with their kind, the other typed words as typed, escaped; the order said around a town")
def sc3(c: Ctx):
    kws = [{"q": "licence économie gestion", "interp": [{"type": "sigle", "value": "licence"}], "terms": [[" licence "], ["economie"], ["gestion"]]},
           {"q": "licence psycho lyon", "interp": [{"type": "lieu", "value": "lyon"}, {"type": "sigle", "value": "licence"}, {"type": "approché", "value": "psycho"}],
            "terms": [[" licence "], ["psycho"], ["lyon"]]},
           {"q": "x" + HOSTILE, "interp": [{"type": "sigle", "value": HOSTILE}], "terms": [["ximg"]]}]
    o = UC.node(c.js, ("INTERP_LABEL", "foldText", "kwChips"), UC.READ_STDIN + """
process.stdout.write(JSON.stringify(D.map((k) => [kwChips(k, null), kwChips(k, { km: 25 })])));""", kws)
    if o is None:
        return True, "skipped (node not installed)"
    bad = []
    a, aa = o[0]
    if "Mot compris : licence" not in a or "Mots cherchés : économie, gestion" not in a:
        bad.append(("licence économie gestion", re.sub(r"<[^>]+>", " ", a)))
    if "puis les plus proches" in a or "puis les plus proches" not in aa:
        bad.append("the order sentence")
    b = o[1][0]
    if "Lieu : lyon" not in b or "Mots cherchés" in b:
        bad.append(("a recognised word repeated as searched", re.sub(r"<[^>]+>", " ", b)))
    if "<img" in "".join(o[2]):
        bad.append("unescaped")
    if "Reconnu" in a + b:
        bad.append("an internal label (« Reconnu », banned by red team LA9)")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ SC4 (browser)
BROWSER = r"""
const { chromium } = require('playwright');
const base = process.argv[1];                                    // run through nodefile: node -e's argv
(async () => {
  const b = await chromium.launch(); const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
  await p.goto(base + '/#/carte'); await p.waitForSelector('#cs-q', { timeout: 60000 }); await p.waitForTimeout(3000);
  await p.fill('#cs-q', 'licence économie gestion'); await p.fill('#cs-lieu', 'Lyon'); await p.press('#cs-q', 'Enter');
  await p.waitForFunction(() => /Résultats/.test((document.getElementById('sr-status') || {}).textContent || ''), null, { timeout: 60000 }).catch(() => {});
  await p.waitForTimeout(2500);
  const r = await p.evaluate(() => ({ chips: (document.getElementById('cs-status') || {}).innerText,
    first: [...document.querySelectorAll('#view .result')].slice(0, 5).map((c) => c.querySelector('.rc-sub').textContent.trim()) }));
  process.stdout.write(JSON.stringify({ ...r, errs })); await b.close();
})();
"""


@check("SC4 browser: Léa's search around Lyon lists « Economie et gestion » first, the chips name her words; 0 JS error")
def sc4(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        # Codex (PR #121): through nodefile, from the repository (require('playwright') from a local node_modules too)
        r = nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    if not o["first"] or not all("Economie et gestion" in x for x in o["first"]):
        bad.append(("first results", o["first"]))
    if "économie" not in o["chips"] or "gestion" not in o["chips"]:
        bad.append(("chips", o["chips"]))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad, f"{o['first'][:3]}; problems {bad}"


# ------------------------------------------------------------------ SC5
MUTANTS = [
    ("api", "SC1", "the domain counted", 'MOTS_FIELDS = ("fili", "fil_lib_voe_acc",', 'MOTS_FIELDS = ("fili", "form_lib_voe_acc", "fil_lib_voe_acc",'),
    ("api", "SC1", "a place counted", "    return [g for g in S.offer_terms(q) if not any(set(a.split()) <= place_words for a in g)]", "    return S.offer_terms(q)"),
    ("api", "SC1", "a multiword place's words counted (Codex, PR #123)",
     "    return [g for g in S.offer_terms(q) if not any(set(a.split()) <= place_words for a in g)]",
     "    return [g for g in S.offer_terms(q) if not any(a.strip() in {' '.join(sorted(place_words))} for a in g)]"),
    ("api", "SC1", "counts misaligned", "    for c in codes:\n        r = first[c]", "    for c in reversed(codes):\n        r = first[c]"),
    ("js", "SC2", "distance before the words", "(kw ? (kw.mots.get(b.cod_aff_form) ?? 0) - (kw.mots.get(a.cod_aff_form) ?? 0) : 0)\n        || (F.autour ? (a.dist ?? 1e9) - (b.dist ?? 1e9) : 0)",
     "(F.autour ? (a.dist ?? 1e9) - (b.dist ?? 1e9) : 0)\n        || (kw ? (kw.mots.get(b.cod_aff_form) ?? 0) - (kw.mots.get(a.cod_aff_form) ?? 0) : 0)"),
    ("js", "SC2", "fewer words first", "(kw ? (kw.mots.get(b.cod_aff_form) ?? 0) - (kw.mots.get(a.cod_aff_form) ?? 0) : 0)",
     "(kw ? (kw.mots.get(a.cod_aff_form) ?? 0) - (kw.mots.get(b.cod_aff_form) ?? 0) : 0)"),
    ("js", "SC3", "an internal label", 'sigle: "Mot compris"', 'sigle: "Reconnu"'),
    ("js", "SC3", "the plain words dropped", '    plain.length ? `<span class="badge">Mots cherchés : ', '    false ? `<span class="badge">Mots cherchés : '),
    ("js", "SC3", "the chip unescaped", 'const chips = [...kw.interp.map((i) => `<span class="badge">${esc(INTERP_LABEL[i.type] || i.type)} : ${esc(i.value)}</span>`)',
     'const chips = [...kw.interp.map((i) => `<span class="badge">${INTERP_LABEL[i.type] || i.type} : ${i.value}</span>`)'),
]


@check("SC5 mutation test: every seeded return of the audit defect is caught by SC1-SC3")
def sc5(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("SC1", "SC2", "SC3") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    caught, missed = 0, []
    import importlib
    for kind, target, name, old, new in MUTANTS:
        if kind == "js":
            if c.js.count(old) != 1:
                missed.append(f"{name} (anchor {c.js.count(old)})")
                continue
            m = copy.copy(c)
            m.js = c.js.replace(old, new, 1)
            try:
                ok = by[target](m)[0]
            except Exception:  # noqa: BLE001
                ok = False
        else:
            p = ROOT / "suptracker" / "api.py"
            src = p.read_text()
            if src.count(old) != 1:
                missed.append(f"{name} (anchor {src.count(old)})")
                continue
            mod = importlib.import_module("suptracker.api")
            saved = {k: getattr(mod, k) for k in ("MOTS_FIELDS", "word_groups", "words_matched", "keyword_codes")}
            try:
                ns = dict(mod.__dict__)
                exec(compile(src.replace(old, new, 1), str(p), "exec"), ns)
                for k in saved:
                    setattr(mod, k, ns[k])
                m = copy.copy(c)
                m.api_src = src.replace(old, new, 1)
                ok = by[target](m)[0]
            except Exception:  # noqa: BLE001
                ok = False
            finally:
                for k, v in saved.items():
                    setattr(mod, k, v)
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


# ------------------------------------------------------------------ SC6
@check("SC6 wiring and docs: test file and CI duration, README section, CLAUDE.md rule, nightly browser suite")
def sc6(c: Ctx):
    bad = []
    t = ROOT / "tests" / "test_compris.py"
    if not t.exists() or "redteam_compris" not in t.read_text():
        bad.append("tests/test_compris.py")
    if '"tests/test_compris.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("CI duration")
    if "## The search says what it understood (lot 1, PR 13" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**The search says what it understood (lot 1, PR 13" not in (ROOT.parent / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    if '"compris": ("SC4",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
    if 'nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}"]' not in Path(__file__).read_text():
        bad.append("the browser program is not run through nodefile from the repository (Codex, PR #121)")
    return not bad, f"problems {bad}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
    c.con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
