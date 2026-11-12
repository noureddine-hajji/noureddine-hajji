"""Red team of sprint R8 (owner, 2026-11-12): accessibility, WCAG 2.1 AA.

    python scripts/redteam_a11y.py [--db data/suptracker.duckdb] [--real] [--browser]

  A1 the shell: French page, a skip link first, <main> focusable and never a live region (it would read whole pages aloud), one
     polite status line, a search landmark, every menu a named navigation landmark
  A2 the page code: the tooltip's text is its accessible name and Escape hides it; after a navigation the tab title names the page
     (its h1), the status line says it and the focus moves to the heading (never on the first load); every scrolling table is a
     focusable region with its own name; the lycée list is named; an unreadable average is marked invalid, then valid again;
     no empty table header
  A3 contrast (WCAG formulas, light and dark tokens): text >= 4.5:1 on the page and the cards, links (accent) >= 4.5:1, form
     fields' edges and the focus ring >= 3:1, zone marks >= 3:1 (1.4.3, 1.4.11)
  A4 browser (--browser / --real): every page on a phone and a wide screen, light and dark: axe-core (WCAG 2.1 A/AA + best
     practices, when axe-core is installed) finds nothing; one h1 per page; each title "<h1> — SupCompass"; no horizontal scroll at
     320 px (1.4.10); the skip link is the first Tab stop and moves the focus to the page; a link click moves the focus to the new
     page's heading; the "Comprendre" menu opens with the keyboard and Escape closes it back on its button; Escape hides a tooltip
  A5 mutation test of A1-A3 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "suptracker" / "static"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.html = (STATIC / "index.html").read_text()
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", js, re.M)
    if not m:
        raise KeyError(name)
    return js[m.start(): js.find("\n}", m.start()) + 2]


# ------------------------------------------------------------------ A1 the shell
def shell_ok(html: str) -> tuple[bool, str]:
    bad = []
    if '<html lang="fr">' not in html:
        bad.append("the page language")
    body = html[html.index("<body>"):]
    first = re.search(r"<(a|button|input|select|textarea)\b[^>]*>", body)
    if not first or 'class="skip"' not in first.group(0) or 'href="#view"' not in first.group(0):
        bad.append(("the skip link is not the first focusable element", first and first.group(0)[:60]))
    main = re.search(r"<main\b[^>]*>", html)
    if not main or 'id="view"' not in main.group(0) or 'tabindex="-1"' not in main.group(0) or "aria-live" in main.group(0):
        bad.append(("<main>: focusable, never a live region", main and main.group(0)))
    st = re.search(r'<div id="sr-status"[^>]*>', html)
    if not st or 'role="status"' not in st.group(0) or 'aria-live="polite"' not in st.group(0) or 'class="sr-only"' not in st.group(0):
        bad.append("the status line")
    if not re.search(r'<form id="search"[^>]*role="search"', html):
        bad.append("the search landmark")
    for nav in re.findall(r"<nav\b[^>]*>", html):
        if "aria-label=" not in nav:
            bad.append(("an unnamed navigation", nav))
    if not re.search(r'<nav id="more-menu"[^>]*aria-label="[^"]+"', html):
        bad.append("the 'Plus' menu is not a named navigation")
    if html.count('aria-live="polite"') != 1:
        bad.append(("live regions in the shell", html.count('aria-live="polite"')))
    return not bad, f"problems {bad[:4]}"


@check("A1 the shell: French, a skip link first, <main> focusable and no live region, a status line, search and menu landmarks")
def a1(c: Ctx):
    return shell_ok(c.html)


# ------------------------------------------------------------------ A2 the page code
def code_ok(js: str) -> tuple[bool, str]:
    bad = []
    tip = re.search(r"const tip = \(key\) => \{.*?\n\};", js, re.S)
    if not tip or 'aria-label="Méthodologie : ${esc(t)}"' not in tip.group(0):
        bad.append("the tooltip's text is not its accessible name")
    if 'if (e.key === "Escape") document.querySelectorAll(".tip:hover, .tip:focus").forEach((t) => t.classList.add("tip-off"));' not in js:
        bad.append("Escape does not hide a tooltip")
    route = top(js, "route")
    if not re.search(r"try \{\n\s+await routeView\(a, b, c\);\n\s+\} catch \(e\) \{\n\s+if \(seq === routeSeq\) showError\(e\);\n\s+\}\n\s+if \(seq === routeSeq\) a11yAfterRoute\(\);", route):
        bad.append("the page is not announced after every navigation (errors included), or a page left early still takes the focus")
    if "const seq = ++routeSeq;" not in route or not re.search(r"(?m)^let routeSeq = 0;$", js):
        bad.append("a navigation gets no number of its own")
    after = top(js, "a11yAfterRoute")
    for need, why in (('$view.querySelector("h1")', "the heading"),
                      ("document.title = name ? `${name} — SupCompass`", "the tab title from the heading"),
                      ("if (a11yFirst) { a11yFirst = false; return; }", "no focus move on the first load"),
                      ('st.textContent = name ? `Page : ${name}`', "the status line"),
                      ("target.focus({ preventScroll: true });", "the focus to the heading")):
        if need not in after:
            bad.append(("a11yAfterRoute", why))
    if after.index("document.title") > after.index("if (a11yFirst)"):
        bad.append("the first page gets no title")
    regions = top(js, "a11yScrollRegions")
    for need in ('el.setAttribute("tabindex", "0");', 'el.setAttribute("role", "region");', "while (root.querySelector(",
                 'el.setAttribute("aria-label", name);'):
        if need not in regions:
            bad.append(("scrolling tables", need[:40]))
    if "new MutationObserver(() => a11yScrollRegions($view)).observe($view, { childList: true, subtree: true });" not in js:
        bad.append("tables drawn later are not made reachable")
    if 'role="listbox" aria-label="Lycées trouvés"' not in js:
        bad.append("the lycée list has no name")
    if 'el.setAttribute("aria-invalid", "true");' not in js or 'el.removeAttribute("aria-invalid")' not in js:
        bad.append("the average's error is not tied to its field")
    if "<th></th>" in js:
        bad.append("an empty table header")
    if 'document.querySelector(".skip")?.addEventListener("click", (e) => { e.preventDefault(); $view.focus(); });' not in js:
        bad.append("the skip link would be read as a route")
    return not bad, f"problems {bad[:4]}"


@check("A2 the page code: tooltip text named and dismissible, title + status + focus after each navigation, reachable tables, named fields")
def a2(c: Ctx):
    return code_ok(c.js)


# ------------------------------------------------------------------ A3 contrast
def _lum(h: str) -> float:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(x * 2 for x in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def tokens(css: str) -> list[dict]:
    """The light tokens (bare :root) and each dark block, every one completed by the light values it does not redefine."""
    blocks = []
    light = {}
    for m in re.finditer(r"(?m)^:root\s*\{(.*?)\n\}", css, re.S):      # every bare :root block (fonts, then colours)
        light.update(dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b", m.group(1))))
    blocks.append(("clair", light))
    for m in re.finditer(r"(?:prefers-color-scheme: dark\)\s*\{\s*:root[^{]*\{|:root\[data-theme=\"dark\"\]\s*\{)(.*?)\}", css, re.S):
        d = dict(light)
        d.update(dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b", m.group(1))))
        blocks.append(("sombre", d))
    return blocks


PAIRS = (("ink", ("surface", "bg"), 4.5, "text"), ("muted", ("surface", "bg"), 4.5, "secondary text"),
         ("accent", ("surface", "bg"), 4.5, "links and the focus ring"), ("line-input", ("surface", "bg"), 3.0, "form fields' edges"),
         ("zone-securite", ("surface",), 3.0, "zone mark"), ("zone-cible", ("surface",), 3.0, "zone mark"),
         ("zone-ambitieux", ("surface",), 3.0, "zone mark"))


def contrast_ok(css: str) -> tuple[bool, str]:
    bad, n = [], 0
    blocks = tokens(css)
    if len(blocks) < 3:
        bad.append(("the dark blocks", len(blocks)))
    for name, t in blocks:
        for fg, bgs, need, why in PAIRS:
            if fg not in t:
                bad.append((name, "missing token", fg))
                continue
            for bg in bgs:
                n += 1
                r = ratio(t[fg], t[bg])
                if r < need:
                    bad.append((name, why, fg, bg, round(r, 2), need))
    if not re.search(r"(?m)^:focus-visible\s*\{\s*outline:\s*3px solid var\(--accent\)", css):   # the global rule
        bad.append("no visible focus ring")
    if 'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]), select, textarea { border-color: var(--line-input); }' not in css:
        bad.append("form fields do not use the stronger edge")
    if ".sr-only {" not in css or ".skip:focus {" not in css or ".tip.tip-off::after { display: none; }" not in css:
        bad.append("helper styles (sr-only, skip, tooltip off)")
    if "prefers-reduced-motion" not in css:
        bad.append("reduced motion")
    return not bad, f"{n} pairs over {len(blocks)} palettes; problems {bad[:4]}"


@check("A3 contrast: text and links >= 4.5:1, field edges, focus ring and zone marks >= 3:1, light and dark (WCAG formulas)")
def a3(c: Ctx):
    return contrast_ok(c.css)


# ------------------------------------------------------------------ A4 browser
def axe_path() -> str | None:
    cands = [os.environ.get("AXE_CORE_JS", "")]
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
        cands.append(os.path.join(root, "axe-core", "axe.min.js"))
    except Exception:  # noqa: BLE001
        pass
    cands.append(str(ROOT / "node_modules" / "axe-core" / "axe.min.js"))
    return next((p for p in cands if p and os.path.exists(p)), None)


BROWSER = r"""
const { chromium } = require('playwright'); const fs = require('fs');
const base = process.argv[2], cod = process.argv[3], axePath = process.argv[4];
const AXE = axePath ? fs.readFileSync(axePath, 'utf8') : null;
const PAGES = ["#/", "#/s/bts%20informatique", "#/f/" + cod, "#/parcours", "#/profil", "#/voeux", "#/guide", "#/carte", "#/metiers",
  "#/compare", "#/comprendre", "#/selectivite", "#/specialites", "#/qualite", "#/glossaire", "#/calendrier", "#/accompagner",
  "#/premiere", "#/reorientation", "#/liste/" + cod, "#/evolution/" + cod];
(async () => {
  const b = await chromium.launch(); const o = { axe: [], h1: [], title: [], reflow: [], errs: [] };
  for (const [mode, vp, scheme] of [["phone-light", { width: 390, height: 844 }, "light"], ["wide-dark", { width: 1280, height: 900 }, "dark"]]) {
    const ctx = await b.newContext({ viewport: vp, colorScheme: scheme });
    await ctx.addInitScript((c) => { localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6, statut: "terminale", academie: "Paris" })); localStorage.setItem("voeux", JSON.stringify([c])); }, cod);
    const p = await ctx.newPage(); p.on("pageerror", (e) => o.errs.push(e.message));
    for (const h of PAGES) {
      await p.goto(base + "/" + h); await p.reload(); await p.waitForTimeout(h.startsWith("#/carte") ? 4500 : 2500);
      await p.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      const r = await p.evaluate(() => ({ h1: [...document.querySelectorAll("#view h1")].map((x) => x.textContent.replace(/\s+/g, " ").trim()), t: document.title }));
      if (r.h1.length !== 1) o.h1.push([mode, h, r.h1.length]);
      else if (r.t !== r.h1[0] + " — SupCompass") o.title.push([mode, h, r.t]);
      if (AXE) {
        await p.addScriptTag({ content: AXE });
        const v = await p.evaluate(async () => (await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] }, resultTypes: ["violations"] })).violations.map((x) => x.id + ":" + x.nodes.length));
        if (v.length) o.axe.push([mode, h, v]);
      }
    }
    await ctx.close();
  }
  const ctx = await b.newContext({ viewport: { width: 320, height: 640 } });
  await ctx.addInitScript((c) => { localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", statut: "terminale" })); localStorage.setItem("voeux", JSON.stringify([c])); }, cod);
  const p = await ctx.newPage(); p.on("pageerror", (e) => o.errs.push(e.message));
  for (const h of PAGES) {
    await p.goto(base + "/" + h); await p.reload(); await p.waitForTimeout(h.startsWith("#/carte") ? 4500 : 2500);
    const w = await p.evaluate(() => document.documentElement.scrollWidth);
    if (w > 320) o.reflow.push([h, w]);
  }
  // keyboard: the skip link first, then into the page
  await p.setViewportSize({ width: 1280, height: 900 });
  await p.goto(base + "/#/"); await p.reload(); await p.waitForTimeout(2000);
  await p.keyboard.press("Tab");
  o.firstTab = await p.evaluate(() => document.activeElement.className);
  await p.keyboard.press("Enter");
  o.afterSkip = await p.evaluate(() => document.activeElement.id);
  // a link click moves the focus to the new page's heading, and the status line names it
  await p.click('.topnav a[href="#/voeux"]'); await p.waitForTimeout(2500);
  o.afterNav = await p.evaluate(() => ({ tag: document.activeElement.tagName, text: document.activeElement.textContent.slice(0, 30), st: document.getElementById("sr-status").textContent }));
  // the "Comprendre" menu with the keyboard
  await p.focus("#comp-btn"); await p.keyboard.press("Enter"); await p.waitForTimeout(200);
  o.menuOpen = await p.evaluate(() => [document.getElementById("comp-btn").getAttribute("aria-expanded"), document.getElementById("comp-menu").hidden]);
  await p.keyboard.press("Escape"); await p.waitForTimeout(200);
  o.menuClosed = await p.evaluate(() => [document.getElementById("comp-btn").getAttribute("aria-expanded"), document.getElementById("comp-menu").hidden, document.activeElement.id]);
  // a tooltip: focused, then Escape
  await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(3000);
  const tip = await p.$(".tip");
  if (tip) {
    await tip.focus();
    o.tipName = await tip.getAttribute("aria-label");
    o.tipShown = await p.evaluate(() => getComputedStyle(document.activeElement, "::after").display);
    await p.keyboard.press("Escape");
    o.tipHidden = await p.evaluate(() => getComputedStyle(document.activeElement, "::after").display);
  }
  // scrolling tables: focusable, each with its own name
  o.regions = await p.evaluate(() => { const r = [...document.querySelectorAll("#view .scroll")]; return { n: r.length, ok: r.every((e) => e.tabIndex === 0 && e.getAttribute("role") === "region" && e.getAttribute("aria-label")), unique: new Set(r.map((e) => e.getAttribute("aria-label"))).size === r.length }; });
  // a page left before its answer came (Codex): its late end must not take the focus or announce anything
  const q = await ctx.newPage(); p.on("pageerror", (e) => o.errs.push(e.message)); q.on("pageerror", (e) => o.errs.push(e.message));
  let release; const held = new Promise((r) => (release = r));
  await q.route("**/api/journey/vocab", async (rt) => { await held; await rt.continue(); });
  await q.goto(base + "/#/profil"); await q.waitForTimeout(1000);
  await q.evaluate(() => { location.hash = "#/metiers"; }); await q.waitForTimeout(2000);
  await q.focus("#mq"); await q.keyboard.type("inf");
  const st0 = await q.evaluate(() => document.getElementById("sr-status").textContent);
  release(); await q.waitForTimeout(2000);
  o.stale = await q.evaluate((s0) => ({ id: document.activeElement.id, same: document.getElementById("sr-status").textContent === s0, h1: document.querySelector("#view h1")?.textContent.slice(0, 20) }), st0);
  process.stdout.write(JSON.stringify(o)); await b.close();
})();
"""


@check("A4 browser: axe finds nothing on every page (phone light, wide dark), one h1 and its title, 320 px reflow, keyboard paths")
def a4(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    import duckdb
    con = duckdb.connect(str(c.db), read_only=True)
    cod = con.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy JOIN core.taxonomy_link t USING (session, cod_aff_form)
        JOIN core.taxonomy_rule r USING (rule_id) WHERE fy.session = (SELECT max(session) FROM core.formation_year)
        AND r.spe_type_key IS NOT NULL AND fy.acc_neobac >= 20 ORDER BY hash(fy.cod_aff_form) LIMIT 1""").fetchone()[0]
    con.close()
    axe = axe_path()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".a11y_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod, axe or ""], capture_output=True, text=True, timeout=900,
                               cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    for k in ("axe", "h1", "title", "reflow", "errs"):
        if o[k]:
            bad.append((k, o[k][:3]))
    if o.get("firstTab") != "skip" or o.get("afterSkip") != "view":
        bad.append(("skip link", o.get("firstTab"), o.get("afterSkip")))
    nav = o.get("afterNav") or {}
    if nav.get("tag") != "H1" or not nav.get("st", "").startswith("Page : "):
        bad.append(("focus after a navigation", nav))
    if o.get("menuOpen") != ["true", False] or o.get("menuClosed") != ["false", True, "comp-btn"]:
        bad.append(("menu with the keyboard", o.get("menuOpen"), o.get("menuClosed")))
    if "tipName" in o and (not o["tipName"].startswith("Méthodologie : ") or len(o["tipName"]) < 40 or o["tipShown"] == "none" or o["tipHidden"] != "none"):
        bad.append(("tooltip", o.get("tipName", "")[:40], o.get("tipShown"), o.get("tipHidden")))
    stale = o.get("stale") or {}
    if stale.get("id") != "mq" or not stale.get("same"):
        bad.append(("a page left before its answer took the focus back", stale))
    reg = o.get("regions") or {}
    if not reg.get("n") or not reg.get("ok") or not reg.get("unique"):
        bad.append(("scrolling tables", reg))
    return not bad, f"axe {'on' if axe else 'not installed (skipped)'}; {json.dumps({k: o.get(k) for k in ('firstTab', 'afterSkip', 'afterNav', 'regions')})}; problems {bad[:4]}"


# ------------------------------------------------------------------ A5 mutation test
MUTANTS = [
    ("html", "no skip link", '<a class="skip" href="#view">Aller au contenu</a>\n', ""),
    ("html", "<main> a live region again", '<main id="view" tabindex="-1"></main>', '<main id="view" tabindex="-1" aria-live="polite"></main>'),
    ("html", "no status line", '<div id="sr-status" class="sr-only" role="status" aria-live="polite"></div>', ""),
    ("html", "no search landmark", ' role="search"', ""),
    ("html", "the 'Plus' menu not a landmark", '<nav id="more-menu" class="more-menu" aria-label="Plus de pages" hidden>', '<div id="more-menu" class="more-menu" hidden>'),
    ("html", "no page language", '<html lang="fr">', "<html>"),
    ("js", "the tooltip's text hidden from screen readers", 'aria-label="Méthodologie : ${esc(t)}"', 'aria-label="Méthodologie"'),
    ("js", "Escape keeps the tooltip", 'forEach((t) => t.classList.add("tip-off"));', "forEach((t) => t);"),
    ("js", "no announcement after a failed page", "  } catch (e) {\n    if (seq === routeSeq) showError(e);\n  }\n  if (seq === routeSeq) a11yAfterRoute();", "    if (seq === routeSeq) a11yAfterRoute();\n  } catch (e) {\n    if (seq === routeSeq) showError(e);\n  }"),
    ("js", "a page left early takes the focus (Codex)", "  if (seq === routeSeq) a11yAfterRoute();", "  a11yAfterRoute();"),
    ("js", "a page left early shows its error (Codex)", "    if (seq === routeSeq) showError(e);", "    showError(e);"),
    ("js", "every navigation shares one number", "  const seq = ++routeSeq;", "  const seq = routeSeq;"),
    ("js", "the same title on every page", "document.title = name ? `${name} — SupCompass` : ", "document.title = "),
    ("js", "the focus moved on the first load", "if (a11yFirst) { a11yFirst = false; return; }", "a11yFirst = false;"),
    ("js", "the focus left where it was", "  target.focus({ preventScroll: true });\n", ""),
    ("js", "scrolling tables not focusable", 'el.setAttribute("tabindex", "0");', ""),
    ("js", "two regions with one name", "while (root.querySelector(", "while (false && root.querySelector("),
    ("js", "the lycée list unnamed", 'role="listbox" aria-label="Lycées trouvés"', 'role="listbox"'),
    ("js", "the average's error not on its field", '      el.setAttribute("aria-invalid", "true");', ""),
    ("js", "an empty header back", '<th><span class="sr-only">Effectif</span></th>', "<th></th>"),
    ("js", "the skip link read as a route", "{ e.preventDefault(); $view.focus(); }", "{ $view.focus(); }"),
    ("css", "pale field edges", "--line-input: #857f8d;", "--line-input: #c9c4cf;"),
    ("css", "pale field edges in the dark", "--line-input: #7a7482;", "--line-input: #4a4550;"),
    ("css", "a pale secondary text", "--muted: #625d69;", "--muted: #9a95a0;"),
    ("css", "no focus ring", ":focus-visible { outline: 3px solid var(--accent);", ":focus-visible { outline: 0 solid var(--accent);"),
    ("css", "fields keep the pale edge", 'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]), select, textarea { border-color: var(--line-input); }', ""),
    ("css", "the skip link never shows", ".skip:focus { top: 8px; }", ""),
]


@check("A5 mutation test: shell, page code and contrast bugs are each caught")
def a5(c: Ctx):
    runs = {"html": lambda s: shell_ok(s)[0], "js": lambda s: code_ok(s)[0], "css": lambda s: contrast_ok(s)[0]}
    src = {"html": c.html, "js": c.js, "css": c.css}
    missed = []
    for kind, name, old, new in MUTANTS:
        if src[kind].count(old) < 1:
            missed.append(f"{name} (anchor missing)")
            continue
        try:
            caught = not runs[kind](src[kind].replace(old, new, 1))
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught; missed {missed}"


@check("A6 docs: README section and CLAUDE.md rule")
def a6(c: Ctx):
    ok = "Sprint R8" in c.readme and "redteam_a11y" in c.claude
    return ok, f"README {('Sprint R8' in c.readme)}, CLAUDE.md {('redteam_a11y' in c.claude)}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
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
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
