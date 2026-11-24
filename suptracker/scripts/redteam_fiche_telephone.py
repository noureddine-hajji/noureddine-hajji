"""Red team of audit PR 5 (owner, 2026-11-24): a shorter formation page on a phone, the right card where a link points.

    python scripts/redteam_fiche_telephone.py [--db data/suptracker.duckdb] [--real] [--browser]

The audit's testers found, on a phone:
  - « Emploi et métiers » opened on the Robustesse 2035 model; the Onisep jobs came last;
  - the summary's apprenticeship link (« Cette formation se fait aussi en apprentissage → ») opened « Combien ça coûte » 5.8
    screens above the apprenticeship card;
  - « Compléter ma liste » sat at the very bottom of Mes vœux, far below the « aucune sécurité » alert that points to it;
  - « i » buttons drawn at 17 px.
The owner kept Robustesse 2035 visible in « L'essentiel » (2026-11-23): only the Emploi tab's order changes.

  FT1 Emploi tab order (static): the jobs card first, then published insertion, apprenticeship insertion, Céreq, the robustesse
      model last; nothing removed
  FT2 links land on their card (static): the summary's apprenticeship link and the Robustesse tile carry data-goto-card, their
      cards carry the id, bindTabs scrolls to the card under the sticky tab bar (the tab's start when the card is absent)
  FT3 Compléter ma liste (static): inserted right after the reading of the list (the « aucune sécurité » alert), not before
      « Et maintenant ? »; the alert's text says « juste en dessous »
  FT4 browser on an emulated phone, real data: the apprenticeship link puts the card's top on screen; the Robustesse tile puts
      its card on screen; the Emploi tab's first card is the jobs card; every « i » button of the page answers a tap anywhere
      in a 44 x 44 px square around its centre; in Mes vœux with no sure safety, Compléter ma liste starts within one screen of
      the alert and above the list; no JS error, no horizontal scroll
  FT5 mutation test of FT1-FT3 and FT6
  FT6 docs: README section, CLAUDE.md rule, test file and its CI duration, nightly browser suite
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

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

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
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.nightly = (ROOT / "scripts" / "browser_nightly.py").read_text()


# ------------------------------------------------------------------ FT1 Emploi tab order
EMPLOI_ORDER = ("metiersCard(d.metiers)", "insertionCard(d.insertion)", "apprentiInsertionCard(d.apprenti)", "cereqCard(d.cereq)",
                "formationRobustesseCard(d.robustesse,")


def emploi_ok(js: str) -> tuple[bool, str]:
    m = re.search(r'\["emploi", "Emploi et métiers", `(.*?)`\]', js, re.S)
    if not m:
        return False, "the Emploi tab is gone"
    body = m.group(1)
    pos = [body.find(x) for x in EMPLOI_ORDER]
    if -1 in pos:
        return False, f"a card missing from the Emploi tab: {[x for x, p in zip(EMPLOI_ORDER, pos) if p < 0]}"
    if pos != sorted(pos):
        return False, f"order {pos}: the jobs first, the robustesse model last"
    return True, "jobs, insertion, apprenticeship insertion, Céreq, robustesse"


@check("FT1 Emploi tab: the jobs card first, the robustesse model last, nothing removed")
def ft1(c: Ctx):
    return emploi_ok(c.js)


# ------------------------------------------------------------------ FT2 links land on their card
LANDING = {
    "apprenticeship link": 'class="linkish" data-goto="cout" data-goto-card="app-card">',
    "apprenticeship card id": '<div class="card app-card" id="app-card">',
    "robustesse tile": 'class="sum-tile sum-rob" data-goto="emploi" data-goto-card="robustesse">',
    "robustesse card id (both branches)": '<div class="card" id="robustesse"><h2>Robustesse 2035 de la formation</h2>',
    "scroll to the card under the bar": "if (card && !card.closest(\"[hidden]\")) window.scrollBy(0, card.getBoundingClientRect().top - bar.offsetHeight - 8);",
    "else the tab's start": "else bar.scrollIntoView({ block: \"start\" });",
}


def landing_ok(js: str) -> tuple[bool, str]:
    bad = [k for k, v in LANDING.items() if v not in js]
    if js.count('<div class="card" id="robustesse"><h2>Robustesse 2035 de la formation</h2>') < 2:
        bad.append("one robustesse branch without the id")
    return not bad, f"problems {bad}"


def taps_ok(css: str) -> tuple[bool, str]:
    """The « i » buttons' invisible 44 px zone is never clipped by a stacked cell or its scroll wrapper (static twin of FT4)."""
    bad = []
    if "table.stack td[data-label] { text-align: right; display: flow-root; overflow-wrap: anywhere; }" not in css:
        bad.append("a stacked cell clips again (overflow: hidden)")
    if ".scroll:has(> table.stack) { overflow-x: visible; }" not in css:
        bad.append("the stacked table's wrapper clips")
    if ".tip::before { content: \"\"; position: absolute; inset: -14px; }" not in css:
        bad.append("the « i » buttons lost their 44 px zone")
    return not bad, f"problems {bad}"


@check("FT2 links land on their card (data-goto-card, ids, scroll under the tab bar); the « i » tap zones are never clipped")
def ft2(c: Ctx):
    a, da = landing_ok(c.js)
    b, db = taps_ok(c.css)
    return a and b, f"links: {da}; taps: {db}"


# ------------------------------------------------------------------ FT3 Compléter ma liste
def completer_ok(js: str) -> tuple[bool, str]:
    bad = []
    if '$view.querySelector("section.summary").insertAdjacentHTML("afterend", \'<section class="card" id="vx-completer"' not in js:
        bad.append("not right after the reading of the list")
    if 'querySelector(".next-steps").insertAdjacentHTML("beforebegin", \'<section class="card" id="vx-completer"' in js:
        bad.append("still at the bottom")
    if "La carte « Compléter ma liste », juste en dessous, en propose" not in js:
        bad.append("the alert does not say where the card is")
    return not bad, f"problems {bad}"


@check("FT3 Compléter ma liste right under the « aucune sécurité » alert, the alert says « juste en dessous »")
def ft3(c: Ctx):
    return completer_ok(c.js)


# ------------------------------------------------------------------ FT4 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
(async () => {
  const [base, cod, lowJson] = process.argv.slice(2), low = JSON.parse(lowJson), errs = [], o = {};
  const b = await chromium.launch();
  const ctx = await b.newContext({ ...devices['Pixel 5'] });
  await ctx.addInitScript(([low]) => {
    localStorage.setItem('profile', JSON.stringify({ statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: '' }));
    localStorage.setItem('voeux', JSON.stringify(low));
  }, [low]);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(String(e)));
  const vh = await p.evaluate(() => window.innerHeight).catch(() => 0);
  const onScreen = async (sel) => p.evaluate((sel) => { const el = document.querySelector(sel); if (!el) return null;
    const r = el.getBoundingClientRect(); return { top: Math.round(r.top), h: window.innerHeight, ok: r.top >= 0 && r.top < window.innerHeight * 0.6 }; }, sel);
  await p.goto(`${base}/#/f/${cod}`); await p.waitForSelector('.sum-app button', { timeout: 120000 }); await p.waitForTimeout(1500);
  // the apprenticeship link: its card's top on screen
  await p.click('.sum-app button'); await p.waitForTimeout(800);
  o.app = await onScreen('#app-card');
  // the Robustesse tile: its card on screen
  await p.evaluate(() => window.scrollTo(0, 0)); await p.waitForTimeout(300);
  await p.click('.sum-rob'); await p.waitForTimeout(800);
  o.rob = await onScreen('#robustesse');
  // the Emploi tab's first card
  o.first = await p.evaluate(() => { const panel = document.querySelector('[id$="-emploi"][role=tabpanel]'); const c = panel && panel.querySelector('.card');
    return c ? (c.querySelector('h2') || c).textContent.trim().slice(0, 80) : null; });
  // every « i » button answers a tap in a 44 x 44 px square around its centre
  o.tips = await p.evaluate(async () => {
    const out = { n: 0, small: [] };
    for (const panel of document.querySelectorAll('[role=tabpanel]')) panel.hidden = false;
    document.querySelectorAll('details').forEach((x) => { x.open = true; });   // a folded button is tapped once its block is open
    document.documentElement.style.scrollBehavior = 'auto';            // the page scrolls smoothly: measure where the button IS
    for (const t of [...document.querySelectorAll('button.tip')].slice(0, 40)) {
      t.scrollIntoView({ block: 'center', behavior: 'instant' });
      const r = t.getBoundingClientRect(); if (!r.width) continue;
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2; out.n++;
      for (const [dx, dy] of [[-20, 0], [20, 0], [0, -20], [0, 20]]) {
        const el = document.elementFromPoint(cx + dx, cy + dy);
        if (!(el && (el === t || t.contains(el)))) { out.small.push([t.getAttribute('aria-label') ? t.getAttribute('aria-label').slice(0, 30) : '?', dx, dy, el ? el.tagName : null]); break; }
      }
    }
    return out; });
  o.hs1 = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  // Mes vœux with no sure safety: Compléter ma liste right under the alert, above the list
  await p.goto(`${base}/#/voeux`); await p.waitForSelector('#vx-completer', { timeout: 120000 }); await p.waitForTimeout(2500);
  o.vx = await p.evaluate(() => { const a = document.querySelector('.vx-alert'), c = document.getElementById('vx-completer');
    const list = [...document.querySelectorAll('.card h2')].find((h) => /^Mes \d+ vœux/.test(h.textContent));
    if (!a || !c || !list) return { missing: [!!a, !!c, !!list] };
    const y = (el) => el.getBoundingClientRect().top + window.scrollY;
    return { gap: Math.round(y(c) - y(a)), above: y(c) < y(list), h: window.innerHeight }; });
  o.hs2 = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await b.close();
  process.stdout.write(JSON.stringify({ o, errs }));
})().catch((e) => { console.error(String(e).slice(0, 600)); process.exit(1); });
"""


def cases(db: Path) -> tuple[str | None, list]:
    """A formation proposed in apprenticeship with its jobs and a robustesse card, and a list with no sure safety, read from the
    API on the warehouse (never hard-coded)."""
    os.environ["SUPTRACKER_DB"] = str(db)
    from fastapi.testclient import TestClient

    from suptracker import api
    api._con.cache_clear()
    cl = TestClient(api.app)
    con = duckdb.connect(str(db), read_only=True)
    s = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    pick = None
    for (cod,) in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND fili = 'BTS'
                                 ORDER BY acc_tot DESC NULLS LAST, cod_aff_form LIMIT 80""", [s]).fetchall():
        d = cl.get(f"/api/formation/{cod}").json()
        if (d.get("apprenti") or {}).get("propose") and d.get("robustesse") and d.get("metiers"):
            pick = cod
            break
    low = [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND taux_acces_ens < 8
                                        AND capa_fin > 20 ORDER BY taux_acces_ens, cod_aff_form LIMIT 4""", [s]).fetchall()]
    r = cl.get("/api/voeux", params={"ids": ",".join(low), "serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab"}).json()
    if "aucune_securite" not in [m["code"] for m in (r.get("lecture") or {}).get("messages", [])]:
        low = []
    return pick, low


@check("FT4 browser (phone): links land on their cards, Emploi opens on the jobs, « i » taps 44 px, Compléter under the alert")
def ft4(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    cod, low = cases(c.db)
    if not cod or not low:
        return False, f"no test case in the warehouse (formation {cod}, list {low})"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".fiche_telephone_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod, json.dumps(low)], capture_output=True, text=True,
                               timeout=600, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-800:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    if not (o["app"] and o["app"]["ok"]):
        bad.append(("apprenticeship card not on screen", o["app"]))
    if not (o["rob"] and o["rob"]["ok"]):
        bad.append(("robustesse card not on screen", o["rob"]))
    if not o["first"] or "métier" not in o["first"].lower():
        bad.append(("the Emploi tab does not open on the jobs", o["first"]))
    if not o["tips"]["n"] or o["tips"]["small"]:
        bad.append(("« i » buttons under 44 px", o["tips"]))
    vx = o["vx"]
    if "missing" in vx or not vx["above"] or not (0 < vx["gap"] <= vx["h"]):
        bad.append(("Compléter ma liste not right under the alert", vx))
    if o["hs1"] or o["hs2"] or d["errs"]:
        bad.append(("scroll or JS errors", o["hs1"], o["hs2"], d["errs"][:2]))
    return not bad, (f"formation {cod}: apprenticeship card at {o['app'] and o['app']['top']} px, robustesse at "
                     f"{o['rob'] and o['rob']['top']} px, first Emploi card « {o['first']} », {o['tips']['n']} « i » buttons; "
                     f"Compléter {vx.get('gap')} px under the alert; problems {bad[:3]}")


# ------------------------------------------------------------------ FT6 docs
def docs_ok(c: Ctx, readme: str | None = None, claude: str | None = None, nightly: str | None = None) -> tuple[bool, str]:
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    nightly = c.nightly if nightly is None else nightly
    bad = []
    if "## A shorter formation page on a phone (audit PR 5" not in readme:
        bad.append("README section")
    if "redteam_fiche_telephone.py" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_fiche_telephone.py").exists() or '"tests/test_fiche_telephone.py"' not in c.durations:
        bad.append("test file or its CI duration")
    if '"fiche_telephone": ("FT4",)' not in nightly:
        bad.append("nightly browser suite")
    return not bad, f"problems {bad}"


@check("FT6 docs: README section, CLAUDE.md rule, test file and its duration, nightly browser suite")
def ft6(c: Ctx):
    return docs_ok(c)


# ------------------------------------------------------------------ FT5 mutation test
@check("FT5 mutation test: Emploi order, card landing, Compléter's place and docs bugs are each caught")
def ft5(c: Ctx):
    caught, missed = 0, []

    def mut(name, old, new, fn):
        nonlocal caught
        if old not in c.js:
            missed.append(f"{name} (anchor lost)")
            return
        if fn(c.js.replace(old, new, 1))[0]:
            missed.append(name)
        else:
            caught += 1

    mut("robustesse back first", "  ${metiersCard(d.metiers)}\n  ${insertionCard(d.insertion)}",
        "  ${insertionCard(d.insertion)}\n  ${metiersCard(d.metiers)}", emploi_ok)
    mut("jobs card dropped", "  ${metiersCard(d.metiers)}\n", "", emploi_ok)
    mut("apprenticeship link without its card", 'data-goto="cout" data-goto-card="app-card">', 'data-goto="cout">', landing_ok)
    mut("apprenticeship card without its id", '<div class="card app-card" id="app-card">', '<div class="card app-card">', landing_ok)
    mut("robustesse tile lands on the tab start", 'data-goto="emploi" data-goto-card="robustesse">', 'data-goto="emploi">', landing_ok)
    mut("no scroll to the card", "window.scrollBy(0, card.getBoundingClientRect().top - bar.offsetHeight - 8);", "void 0;", landing_ok)
    mut("Compléter back at the bottom", '$view.querySelector("section.summary").insertAdjacentHTML("afterend", \'<section class="card" id="vx-completer"',
        '$view.querySelector(".next-steps").insertAdjacentHTML("beforebegin", \'<section class="card" id="vx-completer"', completer_ok)
    mut("the alert says « ci-dessous »", "« Compléter ma liste », juste en dessous, en propose", "« Compléter ma liste » ci-dessous en propose", completer_ok)
    for name, old, new in (("stacked cell clips again", "display: flow-root; overflow-wrap: anywhere; }", "overflow: hidden; }"),
                           ("wrapper clips again", ".scroll:has(> table.stack) { overflow-x: visible; }", ""),
                           ("tap zone removed", ".tip::before { content: \"\"; position: absolute; inset: -14px; }", "")):
        if old not in c.css:
            missed.append(f"{name} (anchor lost)")
        elif taps_ok(c.css.replace(old, new, 1))[0]:
            missed.append(name)
        else:
            caught += 1
    for name, kw in (("README", {"readme": ""}), ("CLAUDE.md", {"claude": ""}), ("nightly", {"nightly": ""})):
        if docs_ok(c, **kw)[0]:
            missed.append(name)
        else:
            caught += 1
    return not missed, f"mutants caught {caught}/{caught + len(missed)}; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail, "s": round(time.time() - t0, 1)})
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
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + f" ({r['s']} s)\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
