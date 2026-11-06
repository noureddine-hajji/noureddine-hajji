"""Red team of the UI lot 1 (audience 16-20 ans, téléphone d'abord).

    python scripts/redteam_ux.py [--browser]

  X1 tutoiement: no "vous / votre / vos / vôtre" and no vous-imperative in any text a student can read (the page script,
     the shell, method texts, glossary, server messages)
  X2 no internal column name in what a student reads: method texts and glossary (shown in the "i" bubbles), the home page
  X3 navigation: on a phone a bottom bar with the 4 main pages + "Plus" holding the 4 others (every page of the top menu
     reachable), the current tab marked, the top menu hidden, the page padded above the bar
  X4 touch targets: on a phone every control is at least 44 px high (CSS), the small "i" buttons get a >= 44 px hidden zone
  X5 search: filters folded under "Filtrer" on a phone (open on wide screens), active filters visible and removable, escaped
  X6 home: three doors (formation, job, where I stand), example searches escaped, no technical note
  X7 browser (--browser, needs node + playwright and a running warehouse): phone screens measured: 0 JS errors, no horizontal
     scroll, every control >= 44 px, the first search result on the first screen, no column name in the visible text
  X8 mutation test
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []

FORMAL = re.compile(r"\b(?:[Vv]ous|[Vv]otre|[Vv]os|[Vv]ôtre)\b")
IMPERATIVES = re.compile(r"\b(?:[Tt]apez|[Ee]ssayez|[Rr]éessayez|[Rr]etirez|[Aa]joutez|[Cc]hoisissez|[Cc]liquez|[Rr]enseignez|[Uu]tilisez|"
                         r"[Cc]onsultez|[Vv]érifiez|[Ii]ndiquez|[Ss]électionnez|[Cc]ollez|[Cc]ochez|[Ss]aisissez|[Rr]egardez|[Cc]omparez)\b")
PY_TEXT = ["api.py", "glossary.py", "planb.py", "search.py", "journey.py", "voeux.py", "metiers.py", "licence_master.py",
           "insertion.py", "passerelles.py", "success.py", "poursuite.py", "cereq.py", "onisep.py", "evidence.py", "prevision.py"]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, browser: bool = False):
        self.browser = browser
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.css = (STATIC / "style.css").read_text()
        from suptracker.api import METHODOLOGY
        from suptracker import glossary as G
        self.methodology = dict(METHODOLOGY)
        self.glossary = {k: v[1] for k, v in G.GLOSSARY.items()}


def js_text(js: str) -> str:
    """The page script without its comments (what remains can reach the screen)."""
    out = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(ln for ln in out.splitlines() if not ln.lstrip().startswith("//"))


def py_strings(path: Path) -> list[str]:
    """String constants of a module, docstrings excluded."""
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def field_names() -> set[str]:
    from suptracker import schema
    names = {f.name for f in getattr(schema, "VOEUX_FIELDS", [])} | {"cod_aff_form", "cod_uai", "fil_lib_voe_acc", "lib_grp1", "acc_neobac", "acc_term"}
    return {n for n in names if "_" in n}


@check("X1 tutoiement: no vous / votre / vos and no vous-imperative in the student-facing text")
def x1(c: Ctx):
    hits = []
    for src, text in [("app.js", js_text(c.js)), ("index.html", c.html)] + [(f"METHODOLOGY[{k}]", v) for k, v in c.methodology.items()] \
            + [(f"glossaire[{k}]", v) for k, v in c.glossary.items()]:
        for m in list(FORMAL.finditer(text)) + list(IMPERATIVES.finditer(text)):
            hits.append(f"{src}: …{text[max(0, m.start() - 30): m.end() + 20]}…")
    for name in PY_TEXT:
        p = ROOT / "suptracker" / name
        if p.exists() and name not in ("api.py", "glossary.py"):
            for s in py_strings(p):
                for m in list(FORMAL.finditer(s)) + list(IMPERATIVES.finditer(s)):
                    hits.append(f"{name}: …{s[max(0, m.start() - 30): m.end() + 20]}…")
    return not hits, f"{len(hits)} formal phrases {hits[:3]}"


@check("X2 no internal column name in what a student reads (method texts, glossary, home)")
def x2(c: Ctx):
    names = field_names()
    pat = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
    bad = [(k, m) for k, v in {**c.methodology, **{f"g:{k}": v for k, v in c.glossary.items()}}.items() for m in pat.findall(v)]
    home = block(c.js, "// ---- lot 1 UI: the home page opens on three doors")
    shown = re.sub(r"\$\{[^}]*\}", "", home)
    home_bad = [n for n in names if re.search(rf"[>\s(]{re.escape(n)}\b", shown)]
    label = re.findall(r"(?<![.\w$])(?:cod_aff_form|cod_uai)\s+\$\{", c.js)
    ok = not bad and not home_bad and not label
    return ok, f"identifiers in texts {bad[:4]}; on the home page {home_bad[:3]}; printed as a label {label[:2]}"


def block(js: str, marker: str) -> str:
    i = js.index(marker)
    return js[i: js.index("\n// ---- ", i + 1)]


@check("X3 navigation: bottom bar (4 pages + Plus), every top-menu page reachable on a phone, current tab marked")
def x3(c: Ctx):
    def hrefs(sel_open: str):
        i = c.html.find(sel_open)
        if i < 0:
            return []
        j = c.html.find("</nav>", i) if "<nav" in sel_open else c.html.find("</div>", i)
        return re.findall(r'href="(#/[^"]*)"', c.html[i:j])
    top, bar, more = hrefs('<nav class="topnav"'), hrefs('<nav class="tabbar"'), hrefs('<div id="more-menu"')
    main = ["#/", "#/parcours", "#/metiers", "#/voeux"]
    plus = 'id="more-btn"' in c.html and 'aria-controls="more-menu"' in c.html
    reach = set(top) <= set(bar) | set(more)
    marked = "markTab(TAB_OF[a] || \"home\");" in c.js and 'setAttribute("aria-current", "page")' in c.js
    mobile = mobile_css(c.css)
    css = bool(re.search(r"\.topnav\s*\{\s*display:\s*none", mobile)) and bool(re.search(r"\.tabbar\s*\{[^}]*position:\s*fixed", mobile)) \
        and bool(re.search(r"body\s*\{[^}]*padding-bottom", mobile))
    ok = bar == main and plus and reach and len(more) == len(set(top) - set(main)) and marked and css
    return ok, f"bar {bar}; Plus button {plus}; Plus menu {more}; every top page reachable {reach}; tab marked {marked}; phone CSS {css}"


def mobile_css(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return "\n".join(m.group(1) for m in re.finditer(r"@media \(max-width: 720px\) \{(.*?)\n\}", css, flags=re.S))


@check("X4 touch targets: every control at least 44 px high on a phone; the 'i' buttons get a hidden 44 px zone")
def x4(c: Ctx):
    m = mobile_css(c.css)
    rule = re.search(r"([^{}]*)\{\s*min-height:\s*(\d+)px;\s*\}", m)
    sel = {s.strip() for s in rule.group(1).split(",")} if rule else set()
    need = {"button", "select", "summary", "a.badge", ".toolbar a", ".search input", ".search button"}
    h = int(rule.group(2)) if rule else 0
    tab = re.search(r"\.tabbar a, \.tabbar button\s*\{[^}]*min-height:\s*(\d+)px", m)
    tip = re.search(r"\.tip::before\s*\{[^}]*inset:\s*-(\d+)px", m)
    ok = need <= sel and h >= 44 and tab and int(tab.group(1)) >= 44 and tip and 17 + 2 * int(tip.group(1)) >= 44
    return ok, (f"44 px rule on {sorted(need - sel) or 'all controls'} (height {h}); tab height {tab.group(1) if tab else None}; "
                f"'i' zone {17 + 2 * int(tip.group(1)) if tip else None} px")


def node_run(prog: str, payload) -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    r = subprocess.run([node, "-e", prog], input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    return ("__error__" + r.stderr[-400:]) if r.returncode else r.stdout


def helpers(js: str) -> str:
    return "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ")))


def filters_ui(js: str) -> tuple[bool, str]:
    blk = block(js, "// ---- lot 1 UI: search filters are folded")
    prog = helpers(js) + """
const FILI_LABEL = {bts: "BTS"}, OPT_LABEL = {distance: "À distance"};
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const go = (patch) => "#/s/q?" + new URLSearchParams(patch).toString();
const out = {};
for (const wide of [false, true]) {
  globalThis.matchMedia = () => ({ matches: wide });
""" + blk + """
  out[wide ? "wide" : "narrow"] = searchFilters(P, go, {}, ["distance"], "<div class='toolbar'>x</div>");
}
out.empty = searchFilters(P, go, {}, [], "   ");
process.stdout.write(JSON.stringify(out));"""
    r = node_run(prog, {"fili": "bts", "academie": "<img src=x onerror=alert(1)>", "selective": "true"})
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    narrow_closed = '<details class="filters">' in o["narrow"]
    wide_open = '<details class="filters" open>' in o["wide"]
    chips = len(re.findall(r'class="badge exact"[^>]*>[^<]*✕</a>', o["narrow"]))
    leak = "<img" in o["narrow"]
    count = "Filtrer (4 actifs)" in o["narrow"]
    ok = narrow_closed and wide_open and chips == 4 and not leak and count and o["empty"] == "" and "searchFilters(P, go, facets, activeOpts" in js
    return ok, f"closed on a phone {narrow_closed}; open on a wide screen {wide_open}; removable chips {chips}/4; count {count}; raw tag {leak}"


@check("X5 search: filters folded under 'Filtrer' on a phone, active filters visible and removable, escaped")
def x5(c: Ctx):
    return filters_ui(c.js)


def home_ui(js: str) -> tuple[bool, str]:
    blk = block(js, "// ---- lot 1 UI: the home page opens on three doors")
    prog = helpers(js) + """
const store = {}; const voeux = { get: () => JSON.parse(require('fs').readFileSync(0, 'utf8')) };
const $view = { innerHTML: "", dataset: {} };
const document = { getElementById: () => null };
""" + blk.replace('const HOME_EXAMPLES = [', 'const HOME_EXAMPLES = ["<b>x</b>", ') + """
viewHome(); process.stdout.write(JSON.stringify([$view.innerHTML, $view.dataset.rendered]));"""
    r = node_run(prog, ["1", "2"])
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    html, rendered = json.loads(r)
    doors = len(re.findall(r'class="door"', html))
    links = all(h in html for h in ('href="#/metiers"', 'href="#/parcours"', 'id="door-search"'))
    leak = "<b>x</b>" in html
    words = all(w in html for w in ("Je cherche une formation", "Je pars d'un métier", "Je veux savoir où je me situe",
                                     "jamais des pronostics", "Tu as 2 vœux dans ta liste"))
    technical = "META.methodology" in blk or "voe_tot" in html
    ok = doors == 3 and links and not leak and words and not technical and rendered == "home" and "if (!q) return viewHome();" in js
    return ok, f"doors {doors}; links {links}; raw tag {leak}; wording {words}; technical note {technical}; routed {'if (!q) return viewHome();' in js}"


@check("X6 home: three doors (formation, job, where I stand), examples escaped, no technical note")
def x6(c: Ctx):
    return home_ui(c.js)


BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2], fields = JSON.parse(process.argv[3]);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [mode, opts] of [["phone", {...devices["iPhone 13"]}], ["phone-dark", {...devices["iPhone 13"], colorScheme: "dark"}]]) {
    const ctx = await b.newContext(opts); const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
    for (const h of ["#/", "#/s/informatique", "#/parcours", "#/metiers", "#/voeux", "#/glossaire"]) {
      await p.goto(base + "/" + h); await p.waitForTimeout(2000);
      out[mode + " " + h] = await p.evaluate((fields) => {
        const ctl = [...document.querySelectorAll("button, select, summary, a.badge, .toolbar a, .tabbar a, .more-menu a, .door, input[type=search]")]
          .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.classList.contains("tip"); });
        const small = ctl.filter((e) => e.getBoundingClientRect().height < 44).length;
        const text = document.body.innerText;
        const shown = fields.filter((f) => new RegExp("\\b" + f + "\\b").test(text));
        const first = document.querySelector(".result");
        return { hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, small, shown,
                 first: first ? first.getBoundingClientRect().top < innerHeight : null,
                 bar: getComputedStyle(document.querySelector(".tabbar")).display };
      }, fields);
    }
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""


@check("X7 browser: phone screens measured (0 JS errors, no horizontal scroll, controls >= 44 px, first result on screen, no column name)")
def x7(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser)"
    node = shutil.which("node")
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, text=True) if node else None
    if not node or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = Path(ROOT / ".ux_probe.js")
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([node, str(tmp), f"http://127.0.0.1:{port}", json.dumps(sorted(field_names()))],
                               capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-300:]
    d = json.loads(r.stdout)
    bad = {k: v for k, v in d["out"].items() if v["hscroll"] or v["small"] or v["shown"] or v["bar"] != "flex" or v["first"] is False}
    ok = not d["errs"] and not bad and d["out"]
    return ok, f"{len(d['out'])} phone screens; JS errors {d['errs'][:2]}; problems {dict(list(bad.items())[:3])}"


UI_MUTANTS = [
    ("formal home text", "jamais des pronostics.</p>", "jamais des pronostics. Tapez ce que vous cherchez.</p>", ("js", (x1, x6))),
    ("column label back in the formation header", "n° Parcoursup ${esc(r.cod_aff_form)}", "cod_aff_form ${esc(r.cod_aff_form)}", ("js", (x2,))),
    ("Mes vœux tab dropped", '<a href="#/voeux" data-tab="voeux"><svg', '<a href="#/stats" data-tab="voeux"><svg', ("html", (x3,))),
    ("glossary missing from Plus", '  <a href="#/glossaire" data-tab="glossaire">Glossaire</a>\n</div>', "</div>", ("html", (x3,))),
    ("current tab never marked", 'markTab(TAB_OF[a] || "home");', "", ("js", (x3,))),
    ("top menu kept on a phone", "  .topnav { display: none; }\n", "", ("css", (x3,))),
    ("touch targets back to 32 px", "a.badge, .toolbar a, input[type=\"search\"], input[type=\"text\"] { min-height: 44px; }",
     "a.badge, .toolbar a, input[type=\"search\"], input[type=\"text\"] { min-height: 32px; }", ("css", (x4,))),
    ("'i' zone too small", ".tip::before { content: \"\"; position: absolute; inset: -14px; }", ".tip::before { content: \"\"; position: absolute; inset: -4px; }", ("css", (x4,))),
    ("filters always open", '<details class="filters"${wide ? " open" : ""}>', '<details class="filters" open>', ("js", (x5,))),
    ("active filter unescaped", "${esc(l)} ✕</a>", "${l} ✕</a>", ("js", (x5,))),
    ("home example unescaped", '>${esc(e)}</a>`).join("")', '>${e}</a>`).join("")', ("js", (x6,))),
    ("home technical note back", '    ${n ? `<p><a href="#/voeux">', '    <div class="info">${esc(META.methodology.funnel)}</div>${n ? `<p><a href="#/voeux">', ("js", (x6,))),
]


@check("X8 mutation test: formal text, column names, navigation, touch targets, filters and home bugs are each caught")
def x8(c: Ctx):
    missed = []
    for name, old, new, (where, fns) in UI_MUTANTS:
        src = {"js": c.js, "html": c.html, "css": c.css}[where]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        setattr(m, where, src.replace(old, new, 1))
        if not any(not fn(m)[0] for fn in fns):
            missed.append(name)
    m = Ctx.__new__(Ctx)                                   # a column name back in a method text
    m.__dict__.update(c.__dict__)
    m.methodology = {**c.methodology, "funnel": c.methodology["funnel"] + " (voe_tot)"}
    if x2(m)[0]:
        missed.append("column name in a method text")
    m.methodology = {**c.methodology, "funnel": c.methodology["funnel"] + " Vérifiez votre fiche."}
    if x1(m)[0]:
        missed.append("formal method text")
    n = len(UI_MUTANTS) + 2
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(browser: bool = False) -> list[dict]:
    c = Ctx(browser)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--real", action="store_true", help="same as --browser (the browser check reads the real warehouse)")
    a = ap.parse_args(argv)
    res = run(a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
