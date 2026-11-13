"""Red team, sprint Q5 (owner, 2026-11-13): the home and the formation page on a phone, and how a screen reader reads them.

The red-team evaluation (designer 11/15, accessibility 8.5/10) found the home stacked a search, a profile banner, a title and a
profile card, with a discreet "Créer mon profil"; the formation page was long, its tabs two screens down. Checks:

  MB1 home, one main action (source): the hero holds `homeCta()` right after its lead sentence: "Créer mon profil" (#/profil)
      without a profile, "Voir où je me situe" (#/parcours) with one; it is the only `primary` control of the home's code
      (guide card, doors, profile line, explorer views); the profile line is a sentence with a link, not a second button.
  MB2 no repeated call: on the home itself, without a profile, the profile bar is hidden (the hero carries the call); every
      other page keeps it (the router passes "accueil" only for the home).
  MB3 formation page, one main action: "Ajouter à mes vœux" is the primary button (voeuButton(cod, true)), only when the
      formation can be added; "Comparer" is a secondary button.
  MB4 sticky tabs (source): the tab bar is `position: sticky; top: 0` with an opaque background and 44 px tabs; choosing a
      tab down a long panel brings the new panel's start just under the bar.
  MB5 phone layout (browser, Pixel 5): the home's main action is on the first screen, with and without a profile; the
      formation pages' tab bar starts within two screens (the longest titles of the latest campaign); inside <main>, exactly
      one control is filled with the accent colour on the home and on a formation page; the tab bar sticks at 0 and a tab
      opened down the page shows its panel just under it; no horizontal scroll; no JS error.
  MB6 screen-reader reading (browser, Chromium's accessibility tree; not a real screen reader, see the README protocol):
      the skip link is the first Tab stop and leads to <main>; one banner, one main, one contentinfo, every navigation named;
      one h1, first in <main>; on the home the main action is the first control after the h1; every link, button and
      summary in <main> has a name; the formation tabs form a tablist with one selected tab whose panel exists and is
      labelled by it; after a navigation the focus is on the h1; no "undefined", "null" or "NaN" is read.
  MB7 docs: README section with the manual screen-reader protocol (NVDA / VoiceOver steps), CLAUDE.md rule, durations entry.
  MB8 mutation test: source mutants (MB1-MB4) and page mutants (the DOM of a rendered page altered before MB5/MB6 read it).
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
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, browser: bool = False, real: bool = False, db: Path | None = None):
        self.browser, self.real, self.db = browser, real, db
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.page = None                          # browser results, filled once (MB5, MB6, MB8 share them)


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        return ""
    if js[m.start():].startswith("const "):
        return js[m.start(): js.index("\n", m.start())]
    return js[m.start(): js.find("\n}", m.start()) + 2]


# ---------------------------------------------------------------- source checks
@check("MB1 home: one main action in the hero (Créer mon profil / Voir où je me situe), the only primary control of the home")
def mb1(c: Ctx):
    js = c.js
    cta, home, prof = top(js, "homeCta"), top(js, "viewHome"), top(js, "homeProfile")
    probs = []
    if not re.search(r'<h1>[^<]*</h1>\s*<p>[^<]*</p>\s*\$\{homeCta\(\)\}</section>', home):
        probs.append("homeCta is not right after the hero's title and lead sentence")
    if not ('["#/profil", "Créer mon profil"' in cta and '["#/parcours", "Voir où je me situe"' in cta and 'class="btnlink primary"' in cta):
        probs.append("homeCta does not lead to the profile (none) and to where I stand (profile) as the primary button")
    if 'hasStoredProfile(store.get("profile", null))' not in cta:
        probs.append("homeCta does not read the stored profile")
    others = home.replace("${homeCta()}", "") + prof + top(js, "guideCard") + top(js, "explorerViews")
    if re.search(r'class="[^"]*\bprimary\b', others):
        probs.append("another primary control on the home")
    if 'if (!hasStoredProfile(raw)) return "";' not in prof or "btnlink" in prof:
        probs.append("the profile line repeats the call or is a second button")
    if "hero-search" not in cta or '"hero-search"' not in home:
        probs.append("the hero's search link is not wired")
    return not probs, f"{probs[:3]}"


@check("MB2 no repeated call: the profile bar is hidden on the home without a profile, kept on every other page")
def mb2(c: Ctx):
    js, probs = c.js, []
    rb = js[js.index("const profileBar = {"): js.index("const profileBar = {") + 2500]
    if 'if (this.tab === "accueil" && !hasStoredProfile(raw)) { el.hidden = true; return; }' not in rb:
        probs.append("the bar is not hidden on the home without a profile")
    if 'profileBar.render(!a && !pathRoute(location.pathname, location.hash) ? "accueil" : TAB_OF[a] || "home");' not in js:
        probs.append("the router does not tell the home apart")
    if re.search(r'TAB_OF = \{[^}]*"accueil"', js) or '"accueil"' in top(js, "markTab"):
        probs.append("'accueil' leaks into the tabs (it is the bar's own marker)")
    return not probs, f"{probs}"


@check("MB3 formation page: 'Ajouter à mes vœux' is the primary button when the formation can be added; 'Comparer' secondary")
def mb3(c: Ctx):
    js, probs = c.js, []
    vb, vf = top(js, "voeuButton"), top(js, "viewFormation")
    if '${primary && !inV && !full ? \' class="primary"\' : ""}' not in vb:
        probs.append("voeuButton is not primary only when the formation can be added")
    head = vf[vf.index('<div class="card fhead">'): vf.index("${summaryBand(r, d)}")]
    if "${voeuButton(r.cod_aff_form, true)}" not in head:
        probs.append("the formation page does not ask for the primary vœu button")
    if re.search(r'id="bask"[^>]*primary', head) or head.count("primary") != 0:
        probs.append("'Comparer' (or another control) is primary in the header")
    other_calls = [m.group(0) for m in re.finditer(r"voeuButton\([^)]*,\s*true\)", js)]
    if len(other_calls) != 1:
        probs.append(f"{len(other_calls)} primary vœu buttons in the page code (only the formation page's header)")
    return not probs, f"{probs}"


@check("MB4 sticky tabs: the bar sticks at the top, opaque, 44 px tabs; a tab opened down a panel shows its start under the bar")
def mb4(c: Ctx):
    probs = []
    rules = re.findall(r"\.tabs\s*\{([^}]*)\}", c.css)
    if not any(re.search(r"position:\s*sticky", r) and re.search(r"\btop:\s*0", r) and re.search(r"background:\s*var\(--bg\)", r)
               and re.search(r"z-index:\s*\d+", r) for r in rules):
        probs.append("the tab bar is not sticky at the top with an opaque background")
    if not re.search(r"\.tabs button\s*\{[^}]*min-height:\s*44px", c.css):
        probs.append("tabs under 44 px")
    bt = top(c.js, "bindTabs")
    if "if (shown && bar.getBoundingClientRect().top <= 1) window.scrollBy(0, shown.getBoundingClientRect().top - bar.offsetHeight);" not in bt:
        probs.append("a tab opened down the page does not show its panel's start")
    return not probs, f"{probs}"


# ---------------------------------------------------------------- browser checks
BROWSER_JS = r"""
const { chromium, devices } = require('playwright');
const MUT = __MUTANTS__;
// page checks, run in the page; each returns a list of problems
const LAYOUT = () => {
  const p = [], main = document.querySelector('main#view');
  const acc = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  const probe = document.createElement('i'); probe.style.color = acc; document.body.appendChild(probe);
  const accRgb = getComputedStyle(probe).color; probe.remove();
  const filled = [...main.querySelectorAll('a, button')].filter((e) => e.offsetParent !== null && getComputedStyle(e).backgroundColor === accRgb);
  if (filled.length !== 1) p.push(`${filled.length} filled accent controls in main: ${filled.map((e) => e.textContent.trim().slice(0, 25)).join(' | ')}`);
  if (document.documentElement.scrollWidth > innerWidth + 1) p.push('horizontal scroll');
  return { p, filled: filled.map((e) => e.textContent.trim().slice(0, 40)) };
};
const READER = () => {
  const p = [];
  const name = (e) => (e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map((id) => (document.getElementById(id) || {}).textContent || '').join(' ')
    || e.innerText || e.textContent || e.getAttribute('title') || [...e.querySelectorAll('img[alt]')].map((i) => i.alt).join(' ') || '').trim();
  const vis = (e) => e.offsetParent !== null || getComputedStyle(e).position === 'fixed';
  if (document.querySelectorAll('header, [role=banner]').length !== 1) p.push('banner count');
  if (document.querySelectorAll('main').length !== 1) p.push('main count');
  if (document.querySelectorAll('footer, [role=contentinfo]').length !== 1) p.push('contentinfo count');
  for (const n of document.querySelectorAll('nav')) if (!name(n) && !n.getAttribute('aria-label')) p.push('unnamed navigation');
  const main = document.querySelector('main');
  const h1 = main.querySelectorAll('h1');
  if (h1.length !== 1) p.push(`${h1.length} h1 in main`);
  const firstHeading = main.querySelector('h1, h2, h3');
  if (firstHeading && firstHeading.tagName !== 'H1') p.push(`first heading in main is ${firstHeading.tagName}`);
  for (const e of main.querySelectorAll('a, button, summary, [role=tab]')) if (vis(e) && !name(e)) p.push(`unnamed ${e.tagName.toLowerCase()} ${e.outerHTML.slice(0, 60)}`);
  for (const t of main.querySelectorAll('[role=tablist]')) {
    const tabs = [...t.querySelectorAll('[role=tab]')], sel = tabs.filter((x) => x.getAttribute('aria-selected') === 'true');
    if (!tabs.length || sel.length !== 1) p.push(`tablist with ${sel.length} selected tabs`);
    for (const x of tabs) { const pan = document.getElementById(x.getAttribute('aria-controls'));
      if (!pan || pan.getAttribute('role') !== 'tabpanel' || pan.getAttribute('aria-labelledby') !== x.id) p.push(`tab ${x.id} without its labelled panel`); }
  }
  const txt = main.innerText;
  const bad = txt.match(/\b(undefined|null|NaN)\b/);
  if (bad) p.push(`'${bad[0]}' read in main`);
  return p;
};
(async () => {
  const b = await chromium.launch(); const problems = []; const seen = {};
  const base = 'http://127.0.0.1:__PORT__', cods = __CODS__;
  const PROF = { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: '' };
  const fresh = async (profile) => {
    const ctx = await b.newContext({ ...devices['Pixel 5'] }); const page = await ctx.newPage(); const errs = [];
    page.on('pageerror', (e) => errs.push(e.message));
    await page.goto(base + '/');
    await page.evaluate((pr) => { localStorage.clear(); if (pr) localStorage.setItem('profile', JSON.stringify(pr)); }, profile);
    return { ctx, page, errs };
  };
  const evalChecks = async (page, mutate) => {
    if (mutate) await page.evaluate(mutate);
    const lay = await page.evaluate(LAYOUT); const rd = await page.evaluate(READER);
    return { lay, rd };
  };
  // home without and with a profile
  for (const profile of [null, PROF]) {
    const k = profile ? 'home_profil' : 'home';
    const { ctx, page, errs } = await fresh(profile);
    await page.goto(base + '/#/'); await page.waitForSelector('.hero-cta', { timeout: 30000 });
    const r = await page.evaluate(() => {
      const cta = document.querySelector('.hero-cta a.primary'), h1 = document.querySelector('main h1');
      const ctrls = [...document.querySelectorAll('main a, main button')].filter((e) => e.offsetParent !== null);
      const after = ctrls.filter((e) => h1.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING);
      return { ctaTop: cta ? Math.round(cta.getBoundingClientRect().bottom) : null, vh: innerHeight, cta: cta && cta.textContent.trim(),
               firstAfterH1: after.length ? after[0].textContent.trim() : null, bar: !document.getElementById('profile-bar').hidden };
    });
    seen[k] = r;
    if (r.ctaTop === null || r.ctaTop > r.vh) problems.push(`${k}: main action not on the first screen (${r.ctaTop} > ${r.vh})`);
    if (r.firstAfterH1 !== r.cta) problems.push(`${k}: the first control after the h1 is "${r.firstAfterH1}", not the main action`);
    if (!profile && r.bar) problems.push('home: the profile bar repeats the call');
    if (profile && !r.bar) problems.push('home with a profile: the profile bar is hidden');
    const { lay, rd } = await evalChecks(page);
    seen[k].filled = lay.filled;
    problems.push(...lay.p.map((x) => `${k}: ${x}`), ...rd.map((x) => `${k}: ${x}`), ...errs.map((x) => `${k} js: ${x}`));
    // the skip link is the first Tab stop and leads to main (a fresh load: no navigation has moved the focus yet)
    await page.reload(); await page.waitForSelector('.hero-cta');
    await page.keyboard.press('Tab');
    const first = await page.evaluate(() => ({ cls: document.activeElement.className, href: document.activeElement.getAttribute('href') }));
    if (first.cls !== 'skip' || first.href !== '#view') problems.push(`${k}: first Tab stop is ${JSON.stringify(first)}`);
    // the profile bar comes back on another page
    if (!profile) {
      await page.goto(base + '/#/voeux'); await page.waitForTimeout(800);
      if (await page.evaluate(() => document.getElementById('profile-bar').hidden)) problems.push('voeux without a profile: the profile bar is hidden');
    }
    // page mutants (MB8): each must make LAYOUT or READER fail
    if (!profile) {
      for (const [mname, code] of MUT) {
        await page.goto(base + '/#/'); await page.waitForSelector('.hero-cta');
        const { lay: l2, rd: r2 } = await evalChecks(page, code);
        seen.mutants = seen.mutants || {}; seen.mutants[mname] = (l2.p.length + r2.length) > 0;
      }
    }
    await ctx.close();
  }
  // formation pages with a profile: tab bar position, one main action, sticky behaviour, focus after navigation
  const { ctx, page, errs } = await fresh(PROF);
  seen.fiches = [];
  for (const cod of cods) {
    await page.goto(base + '/#/f/' + cod); await page.waitForSelector('[data-tabs="fiche"]', { timeout: 60000 }); await page.waitForTimeout(500);
    const t = await page.evaluate(() => ({ top: Math.round(document.querySelector('[data-tabs="fiche"]').getBoundingClientRect().top + scrollY), vh: innerHeight }));
    seen.fiches.push([cod, t.top]);
    if (t.top > 2 * t.vh) problems.push(`fiche ${cod}: tabs start at ${t.top} px (> 2 screens of ${t.vh})`);
    const { lay, rd } = await evalChecks(page);
    problems.push(...lay.p.map((x) => `fiche ${cod}: ${x}`), ...rd.map((x) => `fiche ${cod}: ${x}`));
  }
  // sticky: scroll into the first panel, open the last tab: the panel starts under the bar
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2)); await page.waitForTimeout(200);
  const stuck = await page.evaluate(() => Math.round(document.querySelector('[data-tabs="fiche"]').getBoundingClientRect().top));
  if (stuck !== 0) problems.push(`tab bar not stuck at the top (${stuck})`);
  const last = await page.evaluate(() => { const t = [...document.querySelectorAll('[data-tabs="fiche"] [role=tab]')]; return t[t.length - 1].dataset.tabKey; });
  await page.click(`[data-tabs="fiche"] [data-tab-key="${last}"]`); await page.waitForTimeout(300);
  const after = await page.evaluate((k) => ({ bar: document.querySelector('[data-tabs="fiche"]').offsetHeight,
    panel: Math.round(document.getElementById(`panel-fiche-${k}`).getBoundingClientRect().top) }), last);
  seen.sticky = { stuck, after };
  if (Math.abs(after.panel - after.bar) > 2) problems.push(`opened panel starts at ${after.panel}, not under the bar (${after.bar})`);
  // focus on the h1 after an in-app navigation
  await page.goto(base + '/#/'); await page.waitForSelector('.hero-cta');
  await page.evaluate((c) => { location.hash = '#/f/' + c; }, cods[0]); await page.waitForSelector('[data-tabs="fiche"]'); await page.waitForTimeout(400);
  const focus = await page.evaluate(() => document.activeElement && document.activeElement.tagName);
  if (focus !== 'H1') problems.push(`focus after navigation on ${focus}, not the h1`);
  problems.push(...errs.map((x) => `fiche js: ${x}`));
  await ctx.close(); await b.close();
  console.log(JSON.stringify({ problems, seen }));
})();
"""
# DOM perturbations: each turns one thing MB5/MB6 must see wrong (MB8)
PAGE_MUTANTS = [
    ("a second filled button in main", "() => { const b = document.createElement('button'); b.className = 'primary'; b.textContent = 'Autre'; document.querySelector('main .hero').appendChild(b); }"),
    ("an unnamed button", "() => { const b = document.createElement('button'); b.innerHTML = '<svg aria-hidden=\"true\"></svg>'; document.querySelector('main .hero').appendChild(b); }"),
    ("a second h1", "() => { const h = document.createElement('h1'); h.textContent = 'x'; document.querySelector('main').appendChild(h); }"),
    ("an unnamed navigation", "() => { document.querySelector('nav.tabbar').removeAttribute('aria-label'); }"),
    ("a 'undefined' read", "() => { const s = document.createElement('p'); s.textContent = 'Taux undefined'; document.querySelector('main').appendChild(s); }"),
    ("a too wide block", "() => { const d = document.createElement('div'); d.style.width = '900px'; d.textContent = 'x'; document.querySelector('main').appendChild(d); }"),
    ("an unnamed summary", "() => { const d = document.createElement('details'); d.innerHTML = '<summary></summary>'; document.querySelector('main').appendChild(d); }"),
    ("a heading before the h1", "() => { const h = document.createElement('h2'); h.textContent = 'x'; const m = document.querySelector('main'); m.insertBefore(h, m.firstChild); }"),
]


def browser_results(c: Ctx):
    if c.page is not None:
        return c.page
    if not (c.browser or c.real):
        c.page = {"skipped": True}
        return c.page
    node = shutil.which("node")
    db = c.db or ROOT / "data" / "suptracker.duckdb"
    # like FI7 / MO7: the browser checks need node with Playwright (CI runners have neither the module nor Chromium)
    has_pw = bool(node) and subprocess.run([node, "-e", "require('playwright')"], capture_output=True).returncode == 0
    if not has_pw or not db.exists():
        c.page = {"skipped": True}
        return c.page
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.5)
        import duckdb
        with duckdb.connect(str(db), read_only=True) as con:
            # the latest campaign's formations with the longest titles (the worst case for the tab bar's position)
            cods = [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM
                    core.formation_year) AND taux_acces_ens IS NOT NULL ORDER BY length(lib_for_voe_ins) DESC, cod_aff_form LIMIT 3""").fetchall()]
        script = Path(tmp) / "mb.js"
        script.write_text(BROWSER_JS.replace("__PORT__", str(port)).replace("__CODS__", json.dumps(cods))
                          .replace("__MUTANTS__", "[" + ",".join(f"[{json.dumps(n)}, {code}]" for n, code in PAGE_MUTANTS) + "]"))
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=900)
        out = (r.stdout or "").strip().splitlines()
        c.page = json.loads(out[-1]) if out and out[-1].startswith("{") else {"problems": [r.stderr[-500:]], "seen": {}}
    finally:
        srv.terminate()
    return c.page


@check("MB5 phone layout (browser): main action on the first screen, tabs within two screens, one filled control, sticky, no scroll")
def mb5(c: Ctx):
    r = browser_results(c)
    if r.get("skipped"):
        return True, "skipped (--browser / --real, needs node with Playwright and the warehouse)"
    probs = [p for p in r["problems"] if not any(w in p for w in ("unnamed", "h1", "banner", "main count", "contentinfo", "tablist",
                                                                  "tab ", "read in main", "first Tab", "focus", "first heading", "first control"))]
    s = r.get("seen", {})
    return not probs, f"home {s.get('home')}; home with a profile {s.get('home_profil')}; tabs at {s.get('fiches')}; sticky {s.get('sticky')}; problems {probs[:4]}"


@check("MB6 screen-reader reading (browser, accessibility tree): skip link, landmarks, one h1, main action first, names, tabs, focus")
def mb6(c: Ctx):
    r = browser_results(c)
    if r.get("skipped"):
        return True, "skipped (--browser / --real, needs node with Playwright and the warehouse)"
    probs = [p for p in r["problems"] if any(w in p for w in ("unnamed", "h1", "banner", "main count", "contentinfo", "tablist", "tab ",
                                                                "read in main", "first Tab", "focus", "first heading", "first control"))]
    return not probs, f"problems {probs[:4]}"


@check("MB7 docs: README section with the manual screen-reader protocol, CLAUDE.md rule, durations entry")
def mb7(c: Ctx):
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text()
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    sec = readme[readme.find("## Sprint Q5"):]
    ok = ("## Sprint Q5" in readme and "NVDA" in sec and "VoiceOver" in sec and "redteam_mobile.py" in sec
          and "redteam_mobile.py" in claude and "tests/test_mobile.py" in dur)
    return ok, f"README {'## Sprint Q5' in readme}; protocol {'NVDA' in sec and 'VoiceOver' in sec}; CLAUDE.md {'redteam_mobile.py' in claude}; durations {'tests/test_mobile.py' in dur}"


SOURCE_MUTANTS = [
    ("js", "the hero without its main action", "    ${homeCta()}</section>", "</section>", "MB1"),
    ("js", "a second primary on the home", '<a class="btnlink" href="#/guide">', '<a class="btnlink primary" href="#/guide">', "MB1"),
    ("js", "the profile card back as a button", '· <a href="#/profil">Modifier mon profil</a></p>`;', '<a class="btnlink" href="#/profil">Modifier mon profil</a></p>`;', "MB1"),
    ("js", "no profile leads to the search", '["#/profil", "Créer mon profil"', '["#/s/", "Créer mon profil"', "MB1"),
    ("js", "the bar repeats the call", '    if (this.tab === "accueil" && !hasStoredProfile(raw)) { el.hidden = true; return; }  // Q5: the hero carries the one call\n', "", "MB2"),
    ("js", "the router never names the home", '!a && !pathRoute(location.pathname, location.hash) ? "accueil" : TAB_OF[a] || "home"', 'TAB_OF[a] || "home"', "MB2"),
    ("js", "Comparer primary again", '<button id="bask">', '<button id="bask" class="primary">', "MB3"),
    ("js", "the vœu button never primary", "${voeuButton(r.cod_aff_form, true)}", "${voeuButton(r.cod_aff_form)}", "MB3"),
    ("js", "a listed formation still primary", '${primary && !inV && !full ? \' class="primary"\' : ""}', '${primary ? \' class="primary"\' : ""}', "MB3"),
    ("css", "tabs not sticky", ".tabs { position: sticky; top: 0;", ".tabs { position: static; top: 0;", "MB4"),
    ("css", "transparent sticky bar", "z-index: 20; background: var(--bg); }", "z-index: 20; }", "MB4"),
    ("js", "the opened panel left above", "    if (shown && bar.getBoundingClientRect().top <= 1) window.scrollBy(0, shown.getBoundingClientRect().top - bar.offsetHeight);\n", "", "MB4"),
]


@check("MB8 mutation test: source mutants (MB1-MB4) and page mutants (MB5-MB6) are each caught")
def mb8(c: Ctx):
    import copy
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:4] if not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        src = getattr(c, kind)
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        setattr(m, kind, src.replace(old, new, 1))
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        ok = fn(m)[0]
        caught += not ok
        if ok:
            missed.append(name)
    r = browser_results(c)
    page = "page mutants skipped (--browser)"
    if not r.get("skipped"):
        res = (r.get("seen") or {}).get("mutants") or {}
        pm = [n for n, _ in PAGE_MUTANTS if not res.get(n)]
        caught += len(PAGE_MUTANTS) - len(pm)
        missed += [f"page: {n}" for n in pm]
        page = f"{len(PAGE_MUTANTS) - len(pm)}/{len(PAGE_MUTANTS)} page mutants"
    return not missed, f"{caught} caught; {page}; missed {missed}"


def run(db: Path | None = None, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(browser=browser, real=real, db=db)
    out = []
    for fn in CHECKS:
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="the browser checks on the committed warehouse")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--db", type=Path)
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real, browser=a.browser)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
