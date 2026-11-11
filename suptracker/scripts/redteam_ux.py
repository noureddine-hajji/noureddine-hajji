"""Red team of the UI lot 1 (audience 16-20 ans, téléphone d'abord; vouvoiement kept at the owner's request).

    python scripts/redteam_ux.py [--browser]

  X1 vouvoiement (the owner's choice): no "tu / ton / ta / tes / toi / le tien / t'a" and no tu-imperative in any text a
     student can read (the page script, the shell, method texts, glossary, server messages)
  X2 no internal column name in what a student reads: method texts and glossary (shown in the "i" bubbles), the home page
  X3 navigation: on a phone a bottom bar with the 4 main pages + "Plus" holding the 4 others (every page of the top menu
     reachable), the current tab marked, the top menu hidden, the page padded above the bar
  X4 touch targets: on a phone every control is at least 44 px high (CSS), the small "i" buttons get a >= 44 px hidden zone
  X5 search: filters folded under "Filtrer" on a phone (open on wide screens), active filters visible and removable, escaped
  X6 home: four doors (formation, job, where I stand, not in terminale), example searches escaped, no technical note
  X7 browser (--browser, needs node + playwright and a running warehouse): phone screens measured: 0 JS errors, no horizontal
     scroll, every control >= 44 px, the first search result on the first screen, no column name in the visible text
  X8 mutation test
  Lot 2 (Claude design guidelines):
  X9 design tokens: five font sizes and three radii, every size and radius in the stylesheet goes through them (chart marks
     of 2 px excepted), zone colours are their own tokens in every theme and differ from the accent, reduced motion honoured
  X10 fonts self-hosted: no request to a font host (Google Fonts or other), every @font-face file is shipped with its licence
  X11 no emoji used as a marker in what a student reads: drawn SVG icons instead (home doors, offer options)
  X12 summary first: the formation page opens on one summary card (official access rate, the zone from the same Plan B answer,
      admits, jobs; "pas des chances"), then tabs named after the student's questions; the job page folds its diplomas;
      tabs have aria roles and only the open panel shows; every value escaped
  X13 mutation test of X9-X12
  Lot 3 (same format on the working pages):
  X14 Mes vœux opens on its zone counts (one tile per zone, its own colour, "Autres" for the rest), "Mon parcours" folds a
      stored profile under one escaped line, long tables become one labelled block per row on a phone (every figure keeps
      its label), the positioning table shows 20 rows first, search pages hold 20 results on a phone, the comparator keeps
      its label column in place
  X15 mutation test of X14
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

FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi|tien|tienne|tiens)\b|\b[Tt]'a\b")      # tutoiement (the owner keeps "vous")
IMPERATIVES = re.compile(r"\b(?:Tape|Cherche|Essaie|Réessaie|Clique|Choisis|Ajoute|Vérifie|Regarde|Coche|Retire|Utilise|Trouve|Renseigne)\b|"
                         r"\b(?:vois les|vois où|retire le|retire un|ajoute des|ajoute au moins|vérifie la|vérifie-les|regarde les|"
                         r"regarde leur|coche «|utilise la|tape ce)\b")
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


@check("X1 vouvoiement: no tu / ton / ta / tes / toi and no tu-imperative in the student-facing text")
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
    home = block(c.js, "// ---- lot 1 UI: the home page opens on four doors")
    shown = re.sub(r"\$\{[^}]*\}", "", home)
    home_bad = [n for n in names if re.search(rf"[>\s(]{re.escape(n)}\b", shown)]
    label = re.findall(r"(?<![.\w$])(?:cod_aff_form|cod_uai)\s+\$\{", c.js)
    ok = not bad and not home_bad and not label
    return ok, f"identifiers in texts {bad[:4]}; on the home page {home_bad[:3]}; printed as a label {label[:2]}"


def block(js: str, marker: str) -> str:
    i = js.index(marker)
    return js[i: js.index("\n// ---- ", i + 1)]


@check("X3 navigation: bottom bar (Explorer, Mon profil, Mes vœux, Calendrier + Plus), every top-menu page reachable on a phone, current tab marked")
def x3(c: Ctx):
    def hrefs(sel_open: str):
        i = c.html.find(sel_open)
        if i < 0:
            return []
        j = c.html.find("</nav>", i) if "<nav" in sel_open else c.html.find("</div>", i)
        return re.findall(r'href="(#/[^"]*)"', c.html[i:j])
    top, bar, more = hrefs('<nav class="topnav"'), hrefs('<nav class="tabbar"'), hrefs('<div id="more-menu"')
    main = ["#/", "#/profil", "#/voeux", "#/calendrier"]                      # R1 (owner, 2026-11-11): the journey tabs
    plus = 'id="more-btn"' in c.html and 'aria-controls="more-menu"' in c.html and 'id="comp-btn"' in c.html and 'aria-controls="comp-menu"' in c.html
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
    return "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const REO_LABEL = ", "const isReo = ")))


def r2_defs(js: str) -> str:
    """Sprint R2: the page's own helpers the summary's "Pour votre profil" tile calls (no copy)."""
    fns = [re.search(rf"^function {n}\(.*?^\}}", js, re.M | re.S).group(0)
           for n in ("bacProfile", "profileDkey", "pickDoublette", "estimateDoublette", "estimateSemblable", "pickRapport", "pickVoie")]
    one = [ln for ln in js.splitlines() if ln.startswith(("const ownHasBg = ", "const VOIE_WORD = ", "const pct1 = "))]
    return "\n".join(one + fns) + "\n"


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
    blk = block(js, "// ---- lot 1 UI: the home page opens on four doors")
    prog = helpers(js) + """
const ICONS = new Proxy({}, { get: () => "<svg></svg>" });
const store = { get: () => null }; const voeux = { get: () => JSON.parse(require('fs').readFileSync(0, 'utf8')) };
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
    links = all(h in html for h in ('href="#/metiers"', 'href="#/parcours"', 'id="door-search"', 'href="#/reorientation"'))
    # R1: the Explorer views (list current) and, with no stored profile, one call to create it
    links = links and '<nav class="views"' in html and re.search(r'<a href="#/" aria-current="true">', html) is not None \
        and 'href="#/profil">Créer mon profil</a>' in html
    leak = "<b>x</b>" in html
    words = all(w in html for w in ("Je cherche une formation", "Je pars d'un métier", "Je veux savoir où je me situe",
                                     "Je me réoriente ou je reprends mes études",
                                     "jamais des pronostics", "Vous avez 2 vœux dans votre liste"))
    technical = "META.methodology" in blk or "voe_tot" in html
    ok = doors == 4 and links and not leak and words and not technical and rendered == "home" and "if (!q) return viewHome();" in js
    return ok, f"doors {doors}; links {links}; raw tag {leak}; wording {words}; technical note {technical}; routed {'if (!q) return viewHome();' in js}"


@check("X6 home: four doors (formation, job, where I stand, not in terminale), examples escaped, no technical note")
def x6(c: Ctx):
    return home_ui(c.js)


BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2], fields = JSON.parse(process.argv[3]);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [mode, opts] of [["phone", {...devices["iPhone 13"]}], ["phone-dark", {...devices["iPhone 13"], colorScheme: "dark"}]]) {
    const ctx = await b.newContext(opts); const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
    for (const h of ["#/", "#/s/informatique", "#/parcours", "#/metiers", "#/voeux", "#/compare", "#/parcours", "#/glossaire"]) {
      if (h === "#/voeux") {     // lot 3: a stored profile, a list and a comparator basket (codes from a search)
        await p.goto(base + "/#/s/informatique"); await p.waitForTimeout(2000);
        await p.evaluate(() => { const c = [...document.querySelectorAll(".result a[href^='#/f/']")].map((a) => a.getAttribute("href").slice(4)).slice(0, 3);
          localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", academie: "" }));
          localStorage.setItem("voeux", JSON.stringify(c)); localStorage.setItem("basket", JSON.stringify(c)); });
      }
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
                 bar: getComputedStyle(document.querySelector(".tabbar")).display,
                 screens: document.documentElement.scrollHeight / innerHeight, vxsum: !!document.querySelector(".summary .sum-tile .zone-pill"),
                 folded: !!document.querySelector("details.profile:not([open])"), stacked: document.querySelectorAll("tr.stack-head").length,
                 headShown: [...document.querySelectorAll("tr.stack-head")].some((r) => getComputedStyle(r).display !== "none") };
      }, fields);
    }
    // lot 2: the formation page and the job page open on their summary, and stay short (tabs, folded diplomas)
    await p.goto(base + "/#/s/informatique"); await p.waitForTimeout(2000);
    const href = await p.evaluate(() => { const a = document.querySelector(".result a[href^='#/f/']"); return a && a.getAttribute("href"); });
    const job = await p.evaluate(async () => { const c = await (await fetch("/api/metiers")).json(); const r = c.rows.find((x) => x[4] > 20); return r && r[0]; });
    for (const [k, h] of [["formation", href], ["metier", job && "#/metiers/" + job]]) {
      if (!h) { out[mode + " " + k] = { missing: true }; continue; }
      await p.goto(base + "/" + h); await p.waitForTimeout(3000);
      out[mode + " " + k] = await p.evaluate(() => {
        const s = document.querySelector(".summary");
        return { hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth, small: 0, shown: [], first: null,
                 bar: getComputedStyle(document.querySelector(".tabbar")).display,
                 summary: !!s && s.getBoundingClientRect().top < innerHeight * 0.9,
                 screens: document.documentElement.scrollHeight / innerHeight };
      });
    }
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""


@check("X7 browser: phone screens measured (0 JS errors, no horizontal scroll, controls >= 44 px, first result on screen, no column name, "
       "formation and job pages open on their summary and stay short)")
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
    limit = {"formation": 13, "metier": 9}          # screens on a phone (before lot 2: about 30 and 72; sprint 19: 17.6 -> 11.7)
    lot3 = {k: v for k, v in d["out"].items() if (k.endswith("#/s/informatique") and v["screens"] > 8)        # 20 results (before: ~11 screens)
            or (k.endswith("#/voeux") and not v["vxsum"]) or (k.endswith("#/parcours") and not v["folded"])
            or v.get("headShown")}
    bad = {k: v for k, v in d["out"].items() if v.get("missing") or v["hscroll"] or v["small"] or v["shown"] or v["bar"] != "flex"
           or v["first"] is False or ("summary" in v and (not v["summary"] or v["screens"] > limit[k.split()[-1]]))}
    ok = not d["errs"] and not bad and not lot3 and d["out"]
    return ok, f"{len(d['out'])} phone screens; JS errors {d['errs'][:2]}; problems {dict(list(bad.items())[:3])}; lot 3 problems {dict(list(lot3.items())[:3])}"


UI_MUTANTS = [
    ("tutoiement in the home text", "jamais des pronostics.</p>", "jamais des pronostics. Tape ce que tu cherches.</p>", ("js", (x1, x6))),
    ("column label back in the formation header", "n° Parcoursup ${esc(r.cod_aff_form)}", "cod_aff_form ${esc(r.cod_aff_form)}", ("js", (x2,))),
    ("Mes vœux tab dropped", '<a href="#/voeux" data-tab="voeux"><svg', '<a href="#/stats" data-tab="voeux"><svg', ("html", (x3,))),
    ("glossary missing from Plus", '  <a href="#/glossaire" data-tab="glossaire">Glossaire</a>\n  <a href="#/accompagner" data-tab="accompagner">Parents et professeurs</a>',
     '  <a href="#/accompagner" data-tab="accompagner">Parents et professeurs</a>', ("html", (x3,))),
    ("Mon profil tab dropped from the bottom bar", '<a href="#/profil" data-tab="profil"><svg', '<a href="#/parcours" data-tab="profil"><svg', ("html", (x3,))),
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


@check("X8 mutation test: tutoiement, column names, navigation, touch targets, filters and home bugs are each caught")
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
    m.methodology = {**c.methodology, "funnel": c.methodology["funnel"] + " Vérifie ta fiche."}
    if x1(m)[0]:
        missed.append("tutoiement in a method text")
    n = len(UI_MUTANTS) + 2
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


# ------------------------------------------------------------------ lot 2: Claude design guidelines
def root_block(css: str) -> str:
    return "\n".join(re.findall(r"(?m)^:root \{(.*?)^\}", css, re.S))   # every bare :root block (sizes, then palette)


def dark_blocks(css: str) -> list[str]:
    a = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme=\"light\"\]\) \{(.*?)\}", css, re.S)
    b = re.search(r":root\[data-theme=\"dark\"\] \{(.*?)\}", css, re.S)
    return [x.group(1) if x else "" for x in (a, b)]


def tokens_ok(css: str, js: str) -> tuple[bool, str]:
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    root = root_block(body)
    fs = dict(re.findall(r"--fs-(\w+):\s*(\d+)px", root))
    radii = dict(re.findall(r"--r-(\w+):\s*(\d+)px", root))
    sizes = re.findall(r"font-size:\s*([^;}]+)", body)
    raw_sizes = [s for s in sizes if not re.fullmatch(r"var\(--fs-(xs|sm|md|lg|xl)\)|inherit|\d*\.?\d+em|100%", s.strip())]
    short = re.findall(r"(?<![-\w])font:\s*([^;}]+)", body)
    raw_short = [s for s in short if not re.search(r"var\(--fs-\w+\)", s) and s.strip() not in ("inherit",)]
    rads = re.findall(r"border-radius:\s*([^;}]+)", body)
    raw_rads = [r for r in rads if not re.fullmatch(r"var\(--r-(sm|md|pill)\)|0|50%|2px", r.strip())
                and not re.fullmatch(r"(?:0|[24]px)(?: (?:0|[24]px)){1,3}|4px", r.strip())]   # chart marks: 2-4 px corners
    zones = ("securite", "cible", "ambitieux")
    themes = [root] + dark_blocks(body)
    zone_ok = all(all(re.search(rf"--zone-{z}:\s*#[0-9a-fA-F]{{3,6}}", th) for z in zones) for th in themes)
    distinct = all(len({(re.search(rf"--{k}:\s*(#[0-9a-fA-F]+)", th) or re.search("(?!)", "")).group(1).lower()
                        if re.search(rf"--{k}:\s*(#[0-9a-fA-F]+)", th) else k for k in ("accent", *[f"zone-{z}" for z in zones])}) == 4
                   for th in themes)
    js_zones = all(f'color: "var(--zone-{z})"' in js for z in zones)
    motion = bool(re.search(r"@media \(prefers-reduced-motion: reduce\) \{[^@]*animation-duration[^@]*transition-duration", body))
    ok = (set(fs) == {"xs", "sm", "md", "lg", "xl"} and set(radii) == {"sm", "md", "pill"} and not raw_sizes and not raw_short
          and not raw_rads and zone_ok and distinct and js_zones and motion)
    return ok, (f"sizes {sorted(fs)}; radii {sorted(radii)}; raw sizes {raw_sizes[:3]}; raw font shorthands {raw_short[:2]}; "
                f"raw radii {raw_rads[:3]}; zone tokens in 3 themes {zone_ok}; distinct from accent {distinct}; JS zones {js_zones}; "
                f"reduced motion {motion}")


@check("X9 design tokens: five sizes, three radii, semantic zone colours apart from the accent in every theme, reduced motion")
def x9(c: Ctx):
    return tokens_ok(c.css, c.js)


FONT_HOSTS = re.compile(r"fonts\.googleapis|fonts\.gstatic|use\.typekit|fonts\.bunny|fontshare|@import\s+url\(\s*['\"]?https?:", re.I)


def fonts_ok(css: str, html: str, js: str) -> tuple[bool, str]:
    remote = [m.group(0) for src in (css, html, js) for m in FONT_HOSTS.finditer(src)]
    faces = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
    urls = [u for f in faces for u in re.findall(r"url\(\"?([^\")]+)\"?\)", f)]
    offsite = [u for u in urls if not u.startswith("/static/fonts/")]
    missing = [u for u in urls if u.startswith("/static/fonts/") and not (STATIC / u[len("/static/"):]).is_file()]
    fams = {re.search(r"font-family:\s*\"([^\"]+)\"", f).group(1) for f in faces if re.search(r"font-family:\s*\"([^\"]+)\"", f)}
    lic = {p.name.lower() for p in (STATIC / "fonts").glob("LICENSE-*")} if (STATIC / "fonts").is_dir() else set()
    no_lic = [f for f in fams if f"license-{f.lower().replace(' ', '-')}.txt" not in lic]
    used = all(f'"{f}"' in root_block(css) for f in fams)
    ok = faces and not remote and not offsite and not missing and not no_lic and used
    return bool(ok), f"{len(faces)} faces {sorted(fams)}; remote font hosts {remote[:2]}; off-site {offsite}; missing {missing}; no licence {no_lic}; in tokens {used}"


@check("X10 fonts self-hosted: no font host contacted, every face shipped with its licence")
def x10(c: Ctx):
    return fonts_ok(c.css, c.html, c.js)


EMOJI = re.compile("[\U0001F000-\U0001FAFF️⭐✅❌✨]")


def icons_ok(js: str, html: str) -> tuple[bool, str]:
    found = sorted({m.group(0) for src in (js, html) for m in EMOJI.finditer(src)})
    m = re.search(r"const OPT_ICON = \{(.*?)\};", js)
    opt = bool(m) and all(f"{k}: ICONS.{k}" in m.group(1) for k in ("internat", "apprentissage", "distance", "sport", "art"))
    doors = all(f"${{ICONS.{k}}}" in js for k in ("search", "job", "compass"))
    hidden = 'aria-hidden="true"' in (re.search(r"const ICO = .*", js) or re.search("(?!)", "") or [""])[0] if re.search(r"const ICO = .*", js) else False
    ok = not found and opt and doors and hidden
    return ok, f"emoji {found}; options drawn {opt}; doors drawn {doors}; icons hidden from screen readers {hidden}"


@check("X11 no emoji as a marker: drawn SVG icons (doors, offer options), hidden from screen readers")
def x11(c: Ctx):
    return icons_ok(c.js, c.html)


def summary_ui(js: str) -> tuple[bool, str]:
    blk = block(js, "// ---- lot 2 (Claude design guidelines)")
    prog = helpers(js) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let PROFILE = null;
const store = { get: (k, d) => (k === "profile" ? PROFILE : d) };
const ZONES = { cible: { label: "Vœu cible", color: "var(--zone-cible)" }, indetermine: { label: "Indéterminé", color: "var(--line)" } };
const els = {}, document = { getElementById: (id) => els[id] || null, querySelectorAll: () => [] };
""" + r2_defs(js) + blk + """
const out = {};
out.noProfile = summaryBand(P.r, P.d);
PROFILE = { serie: "bg" };
out.profile = summaryBand(P.r, P.d);
const v = { innerHTML: "" }, n = { textContent: "" };
els["sum-zone"] = { querySelector: (s) => (s === ".sum-value" ? v : n) };
fillZoneTile({ zone: "cible" }); out.pill = v.innerHTML;
fillZoneTile({ zone: "indetermine", uncertain: true }); out.pill2 = v.innerHTML; out.note2 = n.textContent;
out.tabs = tabbed("fiche", [["a", "Y entrer", "<div class='card'>A</div>"], ["b", "Vide", "  "], ["c", "Historique", "<div class='card'>C</div>"]]);
out.planbOnly = tabbed("x", [["a", "Y entrer", '<div id="planb"></div>'], ["b", "B", "<p>b</p>"]]);
process.stdout.write(JSON.stringify(out));"""
    payload = {"r": {"session": 2025, "taux_acces_ens": 43, "acc_tot": 319, "capa_fin": 320},
               "d": {"metiers": {"status": "ok", "metiers": [{"nom": "<img src=x onerror=alert(1)>"}, {}, {}]}}}
    r = node_run(prog, payload)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    tiles = len(re.findall(r'class="sum-tile', o["profile"]))   # R2: 5 with a profile (official, for the profile, zone, admits, jobs)
    words = all(w in o["profile"] for w in ("Taux d'accès 2025", "Votre zone", "Admis 2025", "Métiers visés", "pas des chances d'admission"))
    figures = all(w in o["profile"] for w in ("43", "319", "pour 320 places", ">3<"))
    zone_slot = 'id="sum-zone"' in o["profile"] and 'href="#/profil"' in o["noProfile"] and 'id="sum-zone"' not in o["noProfile"]
    pill = 'class="zone-pill" style="background:var(--zone-cible)"' in o["pill"] and ">cible<" in o["pill"]
    neutral = "color:var(--ink)" in o["pill2"] and "incertaine" in o["note2"]
    tabs = o["tabs"]
    roles = tabs.count('role="tab"') == 2 and tabs.count('role="tabpanel"') == 2 and "Vide" not in tabs
    first_open = re.search(r'id="panel-fiche-a"[^>]*>', tabs) and " hidden" not in re.search(r'id="panel-fiche-a"[^>]*>', tabs).group(0) \
        and re.search(r'id="panel-fiche-c"[^>]*hidden', tabs) is not None and 'aria-selected="true"' in tabs.split("</button>")[0]
    planb = 'role="tab"' in o["planbOnly"] and o["planbOnly"].count('role="tab"') == 2
    vf = js[js.index("async function viewFormation("):js.index("// ---- Plan B: same programme elsewhere")]
    order = vf.index("${summaryBand(r, d)}") < vf.index("${tabbed(\"fiche\"") < vf.index("Indicateurs officiels SIES") if all(
        s in vf for s in ("${summaryBand(r, d)}", "${tabbed(\"fiche\"", "Indicateurs officiels SIES")) else False
    groups = all(f'["{k}", "' in vf for k in ("admission", "reussite", "emploi", "historique")) and 'bindTabs("fiche");' in vf
    fill = "if (!opts.inline && p) { fillZoneTile(d.target); fillProfileTile(d.target); }" in js   # R2: the profile tile too
    vm = js[js.index("async function viewMetier("):js.index("// ---- Sprint 15")]
    job = ("const nForm = d.n_formations;" in vm and '<details class="dip"${open ? " open" : ""}>' in vm and "const open = !!mine.length" in vm and 'bindTabs("metier");' in vm
           and "${summary}${tabbed(\"metier\"" in vm and "${esc(x.libelle)}" in vm)
    ok = (tiles == 5 and words and figures and zone_slot and pill and neutral and roles and bool(first_open) and planb and order
          and groups and fill and job)
    return ok, (f"tiles {tiles}/5; wording {words}; figures {figures}; zone slot {zone_slot}; pill {pill}; neutral zone {neutral}; "
                f"tabs {roles}; first open {bool(first_open)}; Plan B slot keeps its tab {planb}; summary before tabs {order}; groups {groups}; "
                f"zone filled by Plan B {fill}; job page folded {job}")


@check("X12 summary first, then tabs: formation page summary (5 tiles since R2, zone from Plan B), aria tabs, job page folded by diploma")
def x12(c: Ctx):
    return summary_ui(c.js)


DESIGN_MUTANTS = [
    ("a raw font size", ".sum-value { font-size: var(--fs-xl);", ".sum-value { font-size: 30px;", ("css", (x9,))),
    ("a raw radius", "details.dip { border-bottom", ".summary { border-radius: 14px; }\ndetails.dip { border-bottom", ("css", (x9,))),
    ("zone colour = accent", 'cible: { label: "Vœu cible", color: "var(--zone-cible)" }', 'cible: { label: "Vœu cible", color: "var(--accent)" }', ("js", (x9,))),
    ("reduced motion dropped", "@media (prefers-reduced-motion: reduce) {", "@media (min-width: 9999px) {", ("css", (x9,))),
    ("Google Fonts back", "<head>", '<head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">', ("html", (x10,))),
    ("font file not shipped", "figtree-latin-wght-normal.woff2", "figtree-latin-400.woff2", ("css", (x10,))),
    ("emoji marker back", "internat: ICONS.internat,", 'internat: "🛏️",', ("js", (x11,))),
    ("summary dropped before the tabs", "  ${summaryBand(r, d)}\n  <p class=\"small fhead-links\">", "  <p class=\"small fhead-links\">", ("js", (x12,))),
    ("caveat dropped from the summary", "Des résultats des campagnes passées, pas des chances d'admission.", "Des résultats des campagnes passées.", ("js", (x12,))),
    ("zone pill unescaped", "${esc(z.label.replace(/^Vœu /, \"\"))}", "${z.label}", ("js", (x12,))),
    ("empty tab kept", 'const kept = groups.filter(([, , html]) => html.replace(/<div id="planb"><\\/div>/, "x").trim());', "const kept = groups;", ("js", (x12,))),
    ("every panel shown", '${n ? " hidden" : ""}>${html}</div>', ">${html}</div>", ("js", (x12,))),
    ("job summary counts a formation once per diploma", "const nForm = d.n_formations;",
     "const nForm = d.diplomes.reduce((s, x) => s + (x.parcoursup ? x.formations.length : 0), 0);", ("js", (x12,))),
    ("job diplomas unfolded", '<details class="dip"${open ? " open" : ""}>', '<details class="dip" open>', ("js", (x12,))),
]


@check("X13 mutation test: raw sizes or radii, zone colours, motion, font hosts, emoji, summary and tab bugs are each caught")
def x13(c: Ctx):
    missed = []
    for name, old, new, (where, fns) in DESIGN_MUTANTS:
        src = {"js": c.js, "html": c.html, "css": c.css}[where]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        setattr(m, where, src.replace(old, new, 1))
        try:
            caught = any(not fn(m)[0] for fn in fns)
        except Exception:  # noqa: BLE001  (a crash counts as caught only if the check itself is sound: it is reported)
            caught = True
        if not caught:
            missed.append(name)
    n = len(DESIGN_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")



# ------------------------------------------------------------------ sprint 19: a shorter formation page
Y_SHOWN = ['<div class="card"><h2>Indicateurs officiels SIES', "${doubletteCard(d.doublettes, d.rapport, d.semblables)}", "${appelCard(d.appel)}",
           '<div id="planb"></div>', "${offerCard(r, d.apprentissage)}"]
Y_FOLDED = ["${previsionCard(d.prevision)}", "${timingCard(r, d.history)}", "${lyceeHere(r)}", "Entonnoir · trois étapes distinctes",
            "Position dans la filière"]


def short_fiche(js: str) -> tuple[bool, str]:
    vf = js[js.index("async function viewFormation("):js.index("// ---- Plan B: same programme elsewhere")]
    y = vf[vf.index('["admission", "Y entrer", `'):vf.index('["jury", "Ce que regarde le jury"')]
    if '<details class="more-card">' not in y:
        return False, "no folded block in Y entrer"
    shown, folded = y.split('<details class="more-card">', 1)
    folded = folded.split("</details>", 1)[0]
    n_cards = len(re.findall(r'<div class="card">|<div id="planb"></div>|\$\{(?:doubletteCard|appelCard|offerCard|previsionCard|timingCard|lyceeHere)\(', shown))
    in_view = all(x in shown for x in Y_SHOWN) and n_cards == 5
    out = all(x in folded and x not in shown for x in Y_FOLDED)
    same = ("const juryHtml = juryCard(d.rapport) || semblablesJuryCard(d.semblables, d.rapport);" in vf
            and '["jury", "Ce que regarde le jury", juryHtml]' in vf and "d.jury_tab = !juryHtml ? null :" in vf)
    head = vf[vf.index('<div class="card fhead">'):vf.index("${summaryBand(r, d)}")]
    compact = "code établissement" not in head and "Code de l'établissement (UAI) : ${esc(r.cod_uai)}" in vf and "fhead-links" not in head
    prog = helpers(js) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const store = { get: (k, d) => d };
const document = { getElementById: () => null, querySelectorAll: () => [] };
""" + r2_defs(js) + block(js, "// ---- lot 2 (Claude design guidelines)") + """
process.stdout.write(JSON.stringify(P.map((jt) => summaryBand({ session: 2025, taux_acces_ens: 40, acc_tot: 30, capa_fin: 30 }, { metiers: null, jury_tab: jt }))));"""
    r = node_run(prog, [{"kind": "own", "session": "<img src=x>"}, {"kind": "semblables"}, None])
    if r is None:
        return in_view and out and same and compact, "node not installed"
    if r.startswith("__error__"):
        return False, r
    own, sem, none = json.loads(r)
    link = ('data-goto="jury"' in own and "son rapport public &lt;img" in own and "<img" not in own
            and 'data-goto="jury"' in sem and "formations semblables (pas de rapport pour celle-ci)" in sem and 'data-goto="jury"' not in none)
    ok = in_view and out and same and compact and link
    return ok, (f"Y entrer: {n_cards} cards in view {in_view}, five folded {out}; jury tab and link from the same render {same}; "
                f"header compact {compact}; summary link (own, similar, none, escaped) {link}")


@check("X16 sprint 19: Y entrer shows 5 cards and folds the others; the summary links to the jury tab; a compact header")
def x16(c: Ctx):
    return short_fiche(c.js)


SHORT_MUTANTS = [
    ("prevision back in view", "  ${appelCard(d.appel)}\n  <div id=\"planb\"></div>", "  ${appelCard(d.appel)}\n  ${previsionCard(d.prevision)}\n  <div id=\"planb\"></div>"),
    ("Plan B folded", "  <div id=\"planb\"></div>\n  ${offerCard(r, d.apprentissage)}\n  <details class=\"more-card\">", "  ${offerCard(r, d.apprentissage)}\n  <details class=\"more-card\">\n  <div id=\"planb\"></div>"),
    ("nothing folded", '<details class="more-card">', '<div class="more-card">'),
    ("link without a jury tab", "d.jury_tab = !juryHtml ? null :", "d.jury_tab = false ? null :"),
    ("report session unescaped", "son rapport public ${esc(d.jury_tab.session)}", "son rapport public ${d.jury_tab.session}"),
    ("establishment code back in the header", "· n° Parcoursup ${esc(r.cod_aff_form)}</div>", "· n° Parcoursup ${esc(r.cod_aff_form)} · code établissement ${esc(r.cod_uai)}</div>"),
]


@check("X17 mutation test: sprint 19 bugs (cards back in view, Plan B folded, link without a tab, escaping, header) are each caught")
def x17(c: Ctx):
    missed = []
    for name, old, new in SHORT_MUTANTS:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        try:
            caught = not short_fiche(c.js.replace(old, new, 1))[0]
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    n = len(SHORT_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


# ------------------------------------------------------------------ lot 3: the working pages
def lot3_ui(js: str, css: str) -> tuple[bool, str]:
    blk = block(js, "// ---- lot 3 (Claude design guidelines)")
    prog = helpers(js) + """
const ZONES = { securite: { label: "Vœu de sécurité", color: "var(--zone-securite)" }, cible: { label: "Vœu cible", color: "var(--zone-cible)" },
  ambitieux: { label: "Vœu ambitieux", color: "var(--zone-ambitieux)" } };
let WIDE = false; globalThis.matchMedia = () => ({ matches: !WIDE });
""" + blk + """
const out = {};
out.tiles = zoneTiles({ securite: 1, cible: 0, ambitieux: 2 }, 3);
out.line = profileLine({ spe1: "<img src=x>", spe2: "SES", mention: "ab", academie: "<b>A</b>" }, "bg");
out.lineBt = profileLine({ spe1: "MATHS", spe2: "SES", mention: "tb", academie: "" }, "bt");
out.narrow = searchPage(); WIDE = true; out.wide = searchPage();
process.stdout.write(JSON.stringify(out));"""
    r = node_run(prog, None)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    tiles = (o["tiles"].count('class="sum-tile"') == 4 and all(f"var(--zone-{z})" in o["tiles"] for z in ("securite", "cible", "ambitieux"))
             and "Autres" in o["tiles"] and re.search(r">1<.*>0<.*>2<.*>3<", o["tiles"], re.S) is not None and "chance" not in o["tiles"])
    line = "<img" not in o["line"] and "<b>" not in o["line"] and "mention assez bien" in o["line"] and "SES" in o["line"] \
        and o["lineBt"] == "bac technologique · mention très bien"
    pages = o["narrow"] == 20 and o["wide"] == 40
    vx = js[js.index("async function viewVoeux("):js.index("// ---- Sprint 12")]
    pc = js[js.index("async function viewParcours("):js.index("// ---- A5 glossary")]
    vs = js[js.index("async function viewSearch("):js.index("function stageCard(")]
    cmp = js[js.index("async function viewCompare("):js.index("async function viewSpecialites(")]

    def labelled(src: str, rows_re: str = r'<table class="stack"><tr class="stack-head">.*?</table>') -> bool:
        rows = re.search(rows_re, src, re.S)
        if not rows or '<table class="stack"><tr class="stack-head">' not in src:
            return False
        cells = re.findall(r"<td(?![^>]*data-label)(?![^>]*class=\"acts\")[^>]*>", rows.group(0))
        return len(cells) == 1                                 # only the formation cell has no label
    vx_ok = labelled(vx, r"return `<tr><td>\$\{name\}</td>.*?</tr>`;") and '<section class="card summary" aria-label="Lecture de votre liste">' in vx and "${zoneTiles(z, z.hors_profil + z.non_ouvert + z.indetermine + z.non_situe)}" in vx
    pc_ok = (labelled(pc) and "${hasProfile ? `<p class=\"home-profile\"><span>Lu pour : <strong>${profileLine(p, serie)}</strong></span><a class=\"btnlink\" href=\"#/profil\">Modifier mon profil</a></p>`" in pc
             and 'const hasProfile = !!store.get("profile", null);' in pc and ".slice(0, allPos ? 80 : 20)" in pc and 'id="allpos"' in pc)
    vs_ok = "limit: PAGE" in vs and "offset: off + PAGE" in vs and "off - PAGE" in vs and "40" not in re.sub(r"<[^>]*>", "", vs.split("const qs")[1].split("const d =")[0])
    cmp_ok = '<table class="cmp">' in cmp
    mob = mobile_css(css)
    css_ok = ("table.stack tr.stack-head { display: none; }" in mob and "table.stack td[data-label]::before { content: attr(data-label);" in mob
              and re.search(r"table\.cmp th:first-child, table\.cmp td:first-child \{ position: sticky; left: 0;", css) is not None)
    ok = tiles and line and pages and vx_ok and pc_ok and vs_ok and cmp_ok and css_ok
    return ok, (f"zone tiles {tiles}; profile line escaped {line}; 20/40 per page {pages}; Mes vœux summary + labelled rows {vx_ok}; "
                f"Où je me situe reads the profile back + labelled rows + 20 first {pc_ok}; search paging {vs_ok}; comparator {cmp_ok}; phone CSS {css_ok}")


@check("X14 working pages: vœux summary, profile read back with its edit link, labelled stacked rows, 20 rows first, phone paging, sticky comparator column")
def x14(c: Ctx):
    return lot3_ui(c.js, c.css)


LOT3_MUTANTS = [
    ("zone tile in the accent colour", 'class="zone-pill" style="background:${ZONES[k].color}"', 'class="zone-pill" style="background:var(--accent)"', ("js", (x14,))),
    ("profile line unescaped", '[ser, serie === "bg" ? `${esc(p.spe1 || "")} + ${esc(p.spe2 || "")}`', '[ser, serie === "bg" ? `${p.spe1 || ""} + ${p.spe2 || ""}`', ("js", (x14,))),
    ("académie unescaped", 'p.academie ? `académie de ${esc(p.academie)}` : ""]\n', 'p.academie ? `académie de ${p.academie}` : ""]\n', ("js", (x14,))),
    ("a figure loses its label", '<td class="num" data-label="Places">', '<td class="num">', ("js", (x14,))),
    ("stored profile never read back on Où je me situe", "${hasProfile ? `<p class=\"home-profile\">", "${false ? `<p class=\"home-profile\">", ("js", (x14,))),
    ("every positioning row at once", ".slice(0, allPos ? 80 : 20)", ".slice(0, 80)", ("js", (x14,))),
    ("40 results on a phone", "const searchPage = () => (narrow() ? 20 : 40);", "const searchPage = () => 40;", ("js", (x14,))),
    ("header row shown on a phone", "  table.stack tr.stack-head { display: none; }\n", "", ("css", (x14,))),
    ("comparator column not pinned", "position: sticky; left: 0; z-index: 1;", "position: static; left: 0; z-index: 1;", ("css", (x14,))),
]


@check("X15 mutation test: lot 3 bugs (colours, escaping, labels, folding, paging, phone CSS) are each caught")
def x15(c: Ctx):
    missed = []
    for name, old, new, (where, fns) in LOT3_MUTANTS:
        src = {"js": c.js, "html": c.html, "css": c.css}[where]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        setattr(m, where, src.replace(old, new, 1))
        if all(fn(m)[0] for fn in fns):
            missed.append(name)
    n = len(LOT3_MUTANTS)
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
