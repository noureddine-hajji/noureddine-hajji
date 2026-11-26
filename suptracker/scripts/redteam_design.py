"""Red team of the Neo Brutalism design (owner, 2026-11-22: « version 3 », design and UX quality of at least 90/100).

    python scripts/redteam_design.py [--db data/suptracker.duckdb] [--browser]

A SCORE out of 100, from measurements only (never a taste): 56 points read in the stylesheet, 44 measured in a browser on the
real pages (home, search, formation, Mes vœux, Mon profil, Observatoire, À propos; phone light and dark, 320 px, wide light and
dark). Without a browser (CI) the static part must be complete; the nightly browser run must reach 90.

  DE1 tokens and contrast (15): the brutal tokens exist (--edge, --bw, --sh, --select, --cta #ffd93d, the three tiles, the paper
      reading tokens); the two dark blocks are equal; ink on the CTA, on the selected state and on every tile >= 4.5 (the paper
      muted text too), the edge against the ground and the cards >= 3 (1.4.11), the focus ring >= 3, ink >= 7 and muted >= 4.5
      on the ground and the cards, white text on each paper zone >= 4.5, in every theme
  DE2 fonts (8): Space Grotesk only, self-hosted, latin AND latin-ext faces, both font tokens on it, its licence shipped, no
      font file left unreferenced
  DE3 motion (7): the press effect (transform on :active) only inside `prefers-reduced-motion: no-preference`; no transition,
      animation or keyframes outside the reduced-motion block; that block exists
  DE4 balanced intensity (8): rotations and capitals only on the selectors the owner allowed (home, search cards, the logo,
      the dropdown chevrons; never a table, a tab panel or a figure)
  DE5 hard shadows (6): every box-shadow has a zero blur (an offset or an inset edge), the shadow tokens too
  DE6 one call-to-action colour (6): --cta fills only the page's main action selectors; app.js never paints with it
  DE7 links and selected states (6): links are ink with a thick underline; the open tab, the chosen view, an open or active
      filter, the current menu entry and the phone bar's page are pale violet (--select) with an ink edge
  DE8 browser (44, --browser): 0 JS error (6); no horizontal scroll at 320 / 393 / 1360 px, no block wider than its card (8); text contrast measured on the
      rendered pages >= 4.5 (3 for large text) (10, proportional); controls >= 44 px on a phone (8, proportional); exactly one
      yellow main action on the home, the search and a formation page, at most one elsewhere (6); Space Grotesk loaded and used
      (3); dark parity: the cards' edge and shadow in the cream edge colour, the ground dark (3). The press effect moves a
      button and stops under reduced motion (part of the 6 JS points: a failure there removes them)
  DE9 score (owner, 2026-11-22): 0.6 x the measured score + 0.4 x the independent screenshot review >= 90, the review alone
      >= 80, static 56/56. The review (scripts/design_review.json) is done by a reviewer who saw only the screenshots, scores 10
      classic UX criteria out of 10 with a reason each, and names the stylesheet it saw; CI reads the measured score recorded with
      it, the nightly browser run measures it again
  DE10 mutation test of DE1-DE7 and DE11 (mutants built in memory)
  DE11 (Codex) the folded phone profile bar keeps the keyboard focus on its button when it opens or closes; DE8 presses Enter
       then Space on it in the browser (part of the 6 JS points)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "suptracker" / "static"
REVIEW = ROOT / "scripts" / "design_review.json"
CHECKS = []
WEIGHTS = {"DE1": 15, "DE2": 8, "DE3": 7, "DE4": 8, "DE5": 6, "DE6": 6, "DE7": 6}
BROWSER_WEIGHTS = {"errors": 6, "overflow": 8, "contrast": 10, "targets": 8, "cta": 6, "font": 3, "dark": 3}
ROTATE_OK = {".dd > summary::after", ".dd[open] > summary::after", ".pb-chev", ".pb-open .pb-chev", ".brand::before", ".rc-badges .badge:nth-child(odd)",
             ".rc-badges .badge:nth-child(even)"}
UPPER_OK = {".stage h3", ".sum-label", ".badge.statut", ".badge.sel", ".hero-cta .btnlink.primary", ".door strong"}
CTA_OK = {"button.primary", ".btnlink.primary", ".search button", ".cs-go"}
SELECTED = ('.tabs button[aria-selected="true"]', '.views a[aria-current="true"]', ".dd[open] > summary", ".dd.on > summary",
            '.topnav > a[aria-current="page"]', '.tabbar a[aria-current="page"]')


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, browser: bool = False):
        self.db, self.browser = db, browser
        self.css = (STATIC / "style.css").read_text()
        self.js = (STATIC / "app.js").read_text()
        self.fonts = sorted(p.name for p in (STATIC / "fonts").iterdir()) if (STATIC / "fonts").is_dir() else []
        self.measured: dict | None = None


# ------------------------------------------------------------------ colours and rules
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(h: str) -> float:
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    r, g, b = (x / 255 for x in _rgb(h))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def strip(css: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r"@media print\s*\{.*?\n\}\n", "", body, flags=re.S)


def themes(css: str) -> dict:
    body = strip(css)
    tok = lambda b: dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", b))  # noqa: E731
    light, dm, da = {}, {}, {}
    for m in re.finditer(r"(?m)^:root\s*\{([^}]*)\}", body):
        light.update(tok(m.group(1)))
    for m in re.finditer(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{([^}]*)\}", body):
        dm.update(tok(m.group(1)))
    for m in re.finditer(r"(?m)^:root\[data-theme=\"dark\"\]\s*\{([^}]*)\}", body):
        da.update(tok(m.group(1)))
    return {"light": light, "dark_media": dm, "dark_attr": da}


def rules(css: str) -> list[tuple[str, str, str]]:
    """(selector, declarations, enclosing at-rule or '') of every rule outside the print block, comments off."""
    body, out, stack, i = strip(css), [], [], 0
    sel_start = 0
    while i < len(body):
        ch = body[i]
        if ch == "{":
            head = " ".join(body[sel_start:i].split())
            j = body.find("}", i)
            nxt = body.find("{", i + 1)
            if head.startswith("@") or (nxt != -1 and nxt < j):
                stack.append(head)
                i += 1
                sel_start = i
                continue
            out.append((head, body[i + 1:j], " ".join(stack)))
            i = j + 1
            sel_start = i
            continue
        if ch == "}":
            if stack:
                stack.pop()
            i += 1
            sel_start = i
            continue
        i += 1
    return out


def selectors(head: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in head:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur.strip()] if p]


# ------------------------------------------------------------------ static checks
def tokens_ok(css: str) -> tuple[bool, str]:
    t, bad = themes(css), []
    L = t["light"]
    need = ("edge", "cta", "cta-ink", "select", "select-ink", "tile-peach", "tile-yellow", "tile-violet", "paper-ink", "paper-muted",
            "paper-surface", "paper-securite", "paper-cible", "paper-ambitieux", "accent", "bg", "surface", "ink", "muted")
    miss = [k for k in need if k not in L]
    if miss:
        bad.append(("missing tokens", miss))
    if L.get("cta", "").lower() != "#ffd93d":
        bad.append(("the call to action is not the owner's yellow", L.get("cta")))
    if not re.search(r"--bw:\s*3px", css) or not re.search(r"--sh:\s*4px", css) or not re.search(r"--sh-big:\s*8px", css):
        bad.append("edge / shadow sizes missing")
    if t["dark_media"] != t["dark_attr"]:
        diff = sorted(k for k in set(t["dark_media"]) | set(t["dark_attr"]) if t["dark_media"].get(k) != t["dark_attr"].get(k))
        bad.append(("the two dark blocks differ", diff[:4]))
    low = []
    for name in ("light", "dark_media"):
        T = {**L, **t[name]} if name != "light" else L
        if miss:
            break
        pairs = [("cta-ink", "cta", 4.5), ("select-ink", "select", 4.5), ("edge", "bg", 3), ("edge", "surface", 3), ("accent", "bg", 3),
                 ("accent", "surface", 3), ("ink", "bg", 7), ("ink", "surface", 7), ("muted", "bg", 4.5), ("muted", "surface", 4.5)]
        for a, b, lim in pairs:
            if contrast(T[a], T[b]) < lim:
                low.append((name, a, b, round(contrast(T[a], T[b]), 2)))
        for tile in ("tile-peach", "tile-yellow", "tile-violet"):        # tiles keep the paper reading tokens in both themes
            for txt in ("paper-ink", "paper-muted"):
                if contrast(L[txt], T[tile]) < 4.5:
                    low.append((name, txt, tile, round(contrast(L[txt], T[tile]), 2)))
        for z in ("paper-securite", "paper-cible", "paper-ambitieux"):
            if contrast(L["paper-surface"], L[z]) < 4.5:
                low.append((name, "paper-surface", z, round(contrast(L["paper-surface"], L[z]), 2)))
    if low:
        bad.append(("contrast", low[:4]))
    return not bad, f"{len(L)} light tokens; problems {bad[:3]}"


def fonts_ok(css: str, files: list[str]) -> tuple[bool, str]:
    faces = re.findall(r"@font-face\s*\{(.*?)\}", css, re.S)
    fams = {m for f in faces for m in re.findall(r"font-family:\s*\"([^\"]+)\"", f)}
    urls = [u for f in faces for u in re.findall(r"url\(\"?([^\")]+)\"?\)", f)]
    bad = []
    if fams != {"Space Grotesk"}:
        bad.append(("families", sorted(fams)))
    if not any("latin-wght" in u for u in urls) or not any("latin-ext" in u for u in urls):
        bad.append(("latin and latin-ext faces", urls))
    if any(not u.startswith("/static/fonts/") for u in urls) or re.search(r"fonts\.googleapis|fonts\.gstatic|@import", css):
        bad.append("a font host")
    for tok in ("--font-display", "--font-body"):
        m = re.search(rf"{tok}:\s*\"([^\"]+)\"", css)
        if not m or m.group(1) != "Space Grotesk":
            bad.append((tok, m and m.group(1)))
    if "LICENSE-space-grotesk.txt" not in files:
        bad.append("licence missing")
    used = {u.rsplit("/", 1)[-1] for u in urls}
    dead = [f for f in files if f.endswith((".woff2", ".woff", ".ttf")) and f not in used]
    missing = [u for u in used if u not in files]
    if dead or missing:
        bad.append(("font files unreferenced / missing", dead, missing))
    return not bad, f"{len(faces)} faces {sorted(fams)}; problems {bad[:3]}"


def motion_ok(css: str) -> tuple[bool, str]:
    bad, press = [], 0
    if not re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*transition-duration", css):
        bad.append("no reduced-motion block")
    for head, dec, at in rules(css):
        if ":active" in head and "transform" in dec:
            press += 1
            if "prefers-reduced-motion: no-preference" not in at:
                bad.append(("a press effect outside the no-preference block", head[:60]))
        if re.search(r"(?<![-\w])(transition|animation)(-duration)?\s*:", dec) and "prefers-reduced-motion: reduce" not in at:
            bad.append(("motion outside the reduced-motion block", head[:60]))
    if re.search(r"@keyframes", strip(css)):
        bad.append("keyframes")
    if not press:
        bad.append("no press effect")
    return not bad, f"{press} press rules; problems {bad[:3]}"


def intensity_ok(css: str) -> tuple[bool, str]:
    rot, up, bad = set(), set(), []
    for head, dec, _ in rules(css):
        for s in selectors(head):
            if re.search(r"rotate\(", dec):
                rot.add(s)
            if "uppercase" in dec:
                up.add(s)
    if rot - ROTATE_OK:
        bad.append(("rotation on", sorted(rot - ROTATE_OK)[:3]))
    if up - UPPER_OK:
        bad.append(("capitals on", sorted(up - UPPER_OK)[:3]))
    if not ({".rc-badges .badge:nth-child(odd)", ".brand::before"} <= rot) or ".door strong" not in up:
        bad.append("the home and cards lost their tilt / capitals")
    return not bad, f"rotated {len(rot)}; capitals {len(up)}; problems {bad[:3]}"


def shadow_blur(value: str) -> list[str]:
    """The shadows of a box-shadow value with a non-zero blur (third length)."""
    out = []
    for sh in selectors(value):                                           # split on top-level commas
        parts = [p for p in re.split(r"\s+(?![^(]*\))", sh.strip()) if p and p != "inset"]
        lens = [p for p in parts if re.fullmatch(r"-?\d*\.?\d+(px|em|rem)?|var\(--[a-z-]+\)", p)]
        if len(lens) >= 3 and not re.fullmatch(r"0(px)?", lens[2]):
            out.append(sh.strip())
    return out


def shadows_ok(css: str) -> tuple[bool, str]:
    bad, n = [], 0
    for head, dec, _ in rules(css):
        for v in re.findall(r"box-shadow:\s*([^;]+)", dec):
            n += 1
            if shadow_blur(v):
                bad.append((head[:40], v.strip()[:40]))
    for tok in ("shadow-tip", "shadow-pop"):
        for v in re.findall(rf"--{tok}:\s*([^;]+);", strip(css)):
            if shadow_blur(v):
                bad.append((tok, v))
    return not bad, f"{n} shadows; soft ones {bad[:3]}"


def cta_ok(css: str, js: str) -> tuple[bool, str]:
    bad = []
    for head, dec, _ in rules(css):
        if "var(--cta)" in dec:
            other = [s for s in selectors(head) if s not in CTA_OK]
            if other or not re.search(r"background(-color)?:\s*var\(--cta\)", dec):
                bad.append(head[:60])
    if "--cta" in js:
        bad.append("app.js paints with --cta")
    return not bad, f"problems {bad[:3]}"


def links_ok(css: str) -> tuple[bool, str]:
    bad = []
    rs = rules(css)
    a_rules = [dec for head, dec, at in rs if head == "a" and not at]
    if not any("color: var(--ink)" in d and "text-decoration-thickness" in d for d in a_rules):
        bad.append("links not ink with a thick underline")
    for want in SELECTED:
        hit = [dec for head, dec, _ in rs if want in selectors(head)]
        if not any(re.search(r"background:\s*var\(--select\)", d) and "var(--select-ink)" in d for d in hit):
            bad.append(("not pale violet", want))
    return not bad, f"problems {bad[:3]}"


def focus_ok(js: str) -> tuple[bool, str]:
    """Codex: the folded profile bar is redrawn on every toggle; the focus must come back to the new toggle."""
    m = re.search(r"const profileBar = \{.*?\n\};", js, re.S)
    body = m.group(0) if m else ""
    before = body.find("const hadFocus") != -1 and body.find("const hadFocus") < body.find("el.innerHTML = `<button type=\"button\" class=\"pb-toggle\"")
    ok = before and "if (hadFocus) tog.focus();" in body and 'aria-expanded="${this.open ? "true" : "false"}"' in body
    return ok, f"focus read before the redraw {before}; restored {'if (hadFocus) tog.focus();' in body}"


@check("DE1 tokens and contrast: brutal tokens, equal dark blocks, ink on every tile, edges and focus ring visible")
def de1(c: Ctx):
    return tokens_ok(c.css)


@check("DE2 fonts: Space Grotesk only, self-hosted latin + latin-ext, licence shipped, no dead font file")
def de2(c: Ctx):
    return fonts_ok(c.css, c.fonts)


@check("DE3 motion: press effect only without reduced motion; no transition or animation elsewhere")
def de3(c: Ctx):
    return motion_ok(c.css)


@check("DE4 balanced intensity: tilts and capitals only on the home, cards and the logo")
def de4(c: Ctx):
    return intensity_ok(c.css)


@check("DE5 hard shadows: no blur anywhere")
def de5(c: Ctx):
    return shadows_ok(c.css)


@check("DE6 one call-to-action colour: only the main action selectors are yellow")
def de6(c: Ctx):
    return cta_ok(c.css, c.js)


@check("DE7 links ink and underlined; selected states pale violet with an ink edge")
def de7(c: Ctx):
    return links_ok(c.css)


@check("DE11 the folded phone profile bar keeps the keyboard focus on its button when it opens or closes (Codex)")
def de11(c: Ctx):
    return focus_ok(c.js)


# ------------------------------------------------------------------ browser measurements
BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2];
const PROFILE = { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b", statut: "terminale" };
const MEASURE = () => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.1; };
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
    return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; };
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const bgOf = (e) => { for (let a = e; a; a = a.parentElement) { const s = getComputedStyle(a);
      if (s.backgroundImage !== 'none' && a !== document.documentElement) return null;   // a gradient or image: not measured
      const c = parse(s.backgroundColor); if (c && c.a >= 0.99) return c; if (c && c.a > 0.01) return null; }
    return parse(getComputedStyle(document.body).backgroundColor); };
  const main = document.querySelector('main#view');
  let n = 0; const low = [];
  for (const e of document.querySelectorAll('body *')) {
    if (e.closest('.leaflet-container, svg, .sr-only, [aria-hidden="true"], #more-menu[hidden]') || !vis(e)) continue;
    if (![...e.childNodes].some((t) => t.nodeType === 3 && t.textContent.trim())) continue;
    const s = getComputedStyle(e); const fg = parse(s.color); const bg = bgOf(e);
    if (!fg || !bg || fg.a < 0.99) continue;
    n += 1;
    const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight, 10) >= 700;
    const lim = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const r = ratio(fg, bg);
    if (r < lim - 0.01) low.push(`${e.tagName.toLowerCase()}.${String(e.className).slice(0, 24)} ${r.toFixed(2)} "${e.textContent.trim().slice(0, 20)}"`);
  }
  const W = document.documentElement.clientWidth;
  const targets = [...document.querySelectorAll('button, .btnlink, select, summary, input:not([type=checkbox]):not([type=radio]):not([type=range]), .tabbar a, .tabs button, .views a')]
    .filter((e) => vis(e) && !e.closest('.leaflet-container') && !e.classList.contains('tip'));
  const small = targets.filter((e) => e.getBoundingClientRect().height < 43.5).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 20)} ${Math.round(e.getBoundingClientRect().height)}`);
  const cta = getComputedStyle(document.documentElement).getPropertyValue('--cta').trim();
  const probe = document.createElement('i'); probe.style.color = cta; document.body.appendChild(probe); const ctaRgb = getComputedStyle(probe).color; probe.remove();
  const filled = main ? [...main.querySelectorAll('a, button')].filter((e) => vis(e) && getComputedStyle(e).backgroundColor === ctaRgb).length : 0;
  const card = document.querySelector('main .card');
  const edge = getComputedStyle(document.documentElement).getPropertyValue('--edge').trim();
  probe.style.color = edge; document.body.appendChild(probe); const edgeRgb = getComputedStyle(probe).color; probe.remove();
  const cs = card && getComputedStyle(card);
  // a block wider than its card (a long badge at 320 px), unless a scrolling container holds it
  const spill = [...document.querySelectorAll('main .card, main .result.rc')].filter(vis).flatMap((c) => {
    const cr = c.getBoundingClientRect();
    return [...c.querySelectorAll('*')].filter((e) => { if (!vis(e) || e.closest('.leaflet-container, svg')) return false;
      const r = e.getBoundingClientRect(); if (r.right <= cr.right + 1) return false;
      for (let a = e; a && a !== c; a = a.parentElement) { const st = getComputedStyle(a);   // an overlay (dropdown panel) floats over the card on purpose
        if (st.position === 'absolute' || st.position === 'fixed') return false;
        if (a !== e && (st.overflowX === 'auto' || st.overflowX === 'scroll' || st.overflowX === 'hidden')) return false; }
      return true; }).slice(0, 1).map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 20)}`); });
  return { n, low, targets: targets.length, small, filled, hs: document.documentElement.scrollWidth > W + 1 || spill.length > 0, spill,
    font: getComputedStyle(document.body).fontFamily.startsWith('"Space Grotesk"') && document.fonts.check('700 16px "Space Grotesk"'),
    edgeOk: !card || (cs.borderTopColor === edgeRgb && (cs.boxShadow === 'none' || cs.boxShadow.includes(edgeRgb))),
    bg: getComputedStyle(document.body).backgroundColor };
};
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  const ctx0 = await b.newContext({ viewport: { width: 1280, height: 900 } }); const p0 = await ctx0.newPage();
  await p0.goto(base + "/#/s/licence");
  await p0.waitForFunction(() => document.querySelector("#carte-items a.rc-title[href^='#/f/']"), null, { timeout: 90000 });
  const fhref = await p0.$eval("#carte-items a.rc-title[href^='#/f/']", (a) => a.getAttribute("href"));
  await ctx0.close();
  const PAGES = [["home", "#/", 1], ["search", "#/carte", 1], ["formation", fhref, 1], ["voeux", "#/voeux", 0], ["profil", "#/profil", 0],
    ["observatoire", "#/observatoire", 0], ["info", "#/info/a-propos", 0]];
  const MODES = [["phone", { ...devices["Pixel 5"], colorScheme: "light" }], ["phonedark", { ...devices["Pixel 5"], colorScheme: "dark" }],
    ["small", { viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true, colorScheme: "light" }],
    ["wide", { viewport: { width: 1360, height: 900 }, colorScheme: "light" }], ["widedark", { viewport: { width: 1360, height: 900 }, colorScheme: "dark" }]];
  for (const [m, opts] of MODES) {
    const ctx = await b.newContext({ ...opts, deviceScaleFactor: 1 });
    await ctx.addInitScript((p) => localStorage.setItem("profile", JSON.stringify(p)), PROFILE);
    const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(`${m}: ${e.message}`));
    for (const [name, hash, one] of PAGES) {
      await p.goto(base + "/" + hash);
      if (name === "formation") await p.waitForSelector(".card.summary", { timeout: 90000 }).catch(() => {});
      await p.waitForLoadState("networkidle").catch(() => {});
      await p.evaluate(() => document.fonts.ready);
      await p.waitForTimeout(1200);
      out[`${m}/${name}`] = { ...(await p.evaluate(MEASURE)), one };
    }
    await ctx.close();
  }
  // the press effect: a button moves under the finger, never under reduced motion
  const press = {};
  for (const rm of ["no-preference", "reduce"]) {
    const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: rm }); const p = await ctx.newPage();
    await p.goto(base + "/#/"); const btn = await p.waitForSelector(".hero-cta .btnlink.primary");
    const bx = await btn.boundingBox(); await p.mouse.move(bx.x + 10, bx.y + 10); await p.mouse.down();
    press[rm] = await btn.evaluate((e) => getComputedStyle(e).transform); await p.mouse.up(); await ctx.close();
  }
  // Codex: the phone profile bar opens and closes from the keyboard, the focus staying on its button
  const kctx = await b.newContext({ ...devices["Pixel 5"] });
  await kctx.addInitScript((p) => localStorage.setItem("profile", JSON.stringify(p)), PROFILE);
  const kp = await kctx.newPage(); await kp.goto(base + "/#/profil"); await kp.waitForSelector(".pb-toggle");
  await kp.focus(".pb-toggle"); const kbd = [];
  for (let i = 0; i < 2; i += 1) {
    await kp.keyboard.press(i ? "Space" : "Enter");
    kbd.push(await kp.evaluate(() => { const a = document.activeElement; return a && a.classList.contains("pb-toggle") ? a.getAttribute("aria-expanded") : "lost"; }));
  }
  await kctx.close();
  process.stdout.write(JSON.stringify({ errs, out, press, kbd })); await b.close();
})();
"""


def measure(c: Ctx) -> dict | str:
    """The browser measurements (once per run), or why they are skipped."""
    if c.measured is not None:
        return c.measured
    exe = shutil.which("node")
    probe = nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        c.measured = "skipped (node or playwright not installed)"
        return c.measured
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".design_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=1500, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    c.measured = json.loads(r.stdout) if not r.returncode else f"browser failed: {r.stderr[-600:]}"
    return c.measured


def browser_points(d: dict) -> tuple[dict, list]:
    """Points per measured criterion (out of BROWSER_WEIGHTS) and the problems behind lost points."""
    out, bad, pts = d["out"], [], {}
    press_ok = d["press"].get("no-preference", "none") != "none" and d["press"].get("reduce") == "none" \
        and d.get("kbd") == ["true", "false"]                           # Codex: the folded bar keeps the keyboard focus
    pts["errors"] = BROWSER_WEIGHTS["errors"] if not d["errs"] and press_ok else 0
    if d["errs"] or not press_ok:
        bad.append(("JS errors / press effect", d["errs"][:2], d["press"]))
    hs = [(k, v.get("spill", [])[:2]) for k, v in out.items() if v["hs"]]
    pts["overflow"] = BROWSER_WEIGHTS["overflow"] * (1 - len(hs) / len(out))
    if hs:
        bad.append(("horizontal scroll", hs[:3]))
    n = sum(v["n"] for v in out.values())
    low = [(k, x) for k, v in out.items() for x in v["low"]]
    pts["contrast"] = BROWSER_WEIGHTS["contrast"] * max(0.0, 1 - 20 * len(low) / max(n, 1))    # 1 % of the texts low = 2 points off
    if low:
        bad.append(("low contrast", len(low), low[:4]))
    phone = {k: v for k, v in out.items() if k.split("/")[0] in ("phone", "phonedark", "small")}
    tn = sum(v["targets"] for v in phone.values())
    small = [(k, x) for k, v in phone.items() for x in v["small"]]
    pts["targets"] = BROWSER_WEIGHTS["targets"] * max(0.0, 1 - 10 * len(small) / max(tn, 1))
    if small:
        bad.append(("controls under 44 px", len(small), small[:4]))
    cta = [k for k, v in out.items() if (v["one"] and v["filled"] != 1) or (not v["one"] and v["filled"] > 1)]
    pts["cta"] = BROWSER_WEIGHTS["cta"] * (1 - len(cta) / len(out))
    if cta:
        bad.append(("yellow actions", [(k, out[k]["filled"]) for k in cta[:4]]))
    nofont = [k for k, v in out.items() if not v["font"]]
    pts["font"] = BROWSER_WEIGHTS["font"] if not nofont else 0
    if nofont:
        bad.append(("font not loaded", nofont[:3]))
    dark = [k for k, v in out.items() if not v["edgeOk"] or (k.split("/")[0].endswith("dark") and v["bg"] != "rgb(18, 18, 18)")]
    pts["dark"] = BROWSER_WEIGHTS["dark"] if not dark else 0
    if dark:
        bad.append(("edge / dark ground", dark[:3]))
    return pts, bad


@check("DE8 browser: errors, overflow, measured contrast, 44 px controls, one yellow action, font, dark parity, press effect")
def de8(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser)"
    d = measure(c)
    if isinstance(d, str):
        return d.startswith("skipped"), d
    pts, bad = browser_points(d)
    total = sum(pts.values())
    return total >= sum(BROWSER_WEIGHTS.values()) - 4, f"{round(total, 1)}/44 {({k: round(v, 1) for k, v in pts.items()})}; problems {bad[:4]}"


def review(css: str) -> tuple[dict | None, str]:
    """The recorded independent review, or why it is unusable."""
    if not REVIEW.exists():
        return None, "no independent review"
    r = json.loads(REVIEW.read_text())
    crit = r.get("criteria", {})
    if len(crit) < 8 or not all("why" in v and 0 <= v.get("score", -1) <= 10 for v in crit.values()) or not r.get("screenshots"):
        return None, "the review lacks its criteria, reasons or screenshots"
    if sum(v["score"] for v in crit.values()) != r.get("total"):
        return None, "the review's total is not the sum of its criteria"
    seen = "the current one" if r.get("style_sha256") == hashlib.sha256(css.encode()).hexdigest() else "an earlier version"
    return r, f"review {r['total']}/100 over {len(crit)} criteria on {r.get('date')} (stylesheet: {seen})"


def combined(measured: float, review_total: float) -> float:
    """Owner, 2026-11-22: 60 % measured, 40 % the independent review."""
    return 0.6 * measured + 0.4 * review_total


@check("DE9 score: static 56/56; 0.6 x measured + 0.4 x independent review >= 90, the review alone >= 80 (owner, 2026-11-22)")
def de9(c: Ctx):
    static = sum(WEIGHTS[fn.check_name.split()[0]] for fn in CHECKS if fn.check_name.split()[0] in WEIGHTS and fn(c)[0])
    r, rdet = review(c.css)
    if r is None:
        return False, f"static {static}/56; {rdet}"
    measured, how = r.get("measured_score"), "recorded at the review"
    if c.browser:
        d = measure(c)
        if not isinstance(d, str):
            measured, how = static + sum(browser_points(d)[0].values()), "measured now"
    if measured is None:
        return False, f"static {static}/56; no measured score; {rdet}"
    score = combined(measured, r["total"])
    ok = static == 56 and r["total"] >= 80 and score >= 90
    return ok, f"design score {round(score, 1)}/100 = 0.6 x {round(measured, 1)} ({how}) + 0.4 x {r['total']} (review); static {static}/56; {rdet}"


# ------------------------------------------------------------------ DE10 mutation test
MUTANTS = [
    ("the dark ground drifts in one block", ":root[data-theme=\"dark\"] {\n    --bg: #121212;", ":root[data-theme=\"dark\"] {\n    --bg: #161616;", tokens_ok),
    ("the call to action another yellow", "--cta: #ffd93d; --cta-ink: #000000; --tint: #f1eee2;", "--cta: #ffe680; --cta-ink: #000000; --tint: #f1eee2;", tokens_ok),
    ("a dark peach tile under ink", "--tile-peach: #ffb38a; --tile-yellow: #fff1a8;", "--tile-peach: #b03030; --tile-yellow: #fff1a8;", tokens_ok),
    ("a pale edge", "--edge: #000000;", "--edge: #d0d0d0;", tokens_ok),
    ("a faint focus ring in the dark", "--accent: #e033ff;", "--accent: #2a2a2a;", tokens_ok),
    ("a grey paper muted text", "--paper-muted: #2b2a30;", "--paper-muted: #6a6870;", tokens_ok),
    ("a Google font back", "@font-face {", "@import url(\"https://fonts.googleapis.com/css2?family=Inter\");\n@font-face {", lambda s: fonts_ok(s, CTX.fonts)),
    ("the latin-ext face dropped", "src: url(\"/static/fonts/space-grotesk-latin-ext-wght-normal.woff2\")", "src: url(\"/static/fonts/space-grotesk-latin-wght-normal.woff2\")",
     lambda s: fonts_ok(s, CTX.fonts)),
    ("the body in another family", "--font-body: \"Space Grotesk\"", "--font-body: \"Inter\"", lambda s: fonts_ok(s, CTX.fonts)),
    ("the press effect without the motion guard", "@media (prefers-reduced-motion: no-preference) {\n  :is(", "@media (min-width: 1px) {\n  :is(", motion_ok),
    ("a hover transition", ".door strong { text-transform: uppercase;", ".door { transition: transform .2s; }\n.door strong { text-transform: uppercase;", motion_ok),
    ("a tilted table", ".carte-box { border: 0; }", ".carte-box { border: 0; }\n.tabpanel table { transform: rotate(-1deg); }", intensity_ok),
    ("capital column heads", ".carte-box { border: 0; }", ".carte-box { border: 0; }\nth { text-transform: uppercase; }", intensity_ok),
    ("the cards' tilt lost", ".rc-badges .badge:nth-child(odd) { transform: rotate(-2deg); }", "", intensity_ok),
    ("a soft card shadow", ".card { border: var(--bw) solid var(--edge); border-radius: var(--r-md); padding: 18px 20px; box-shadow: var(--sh) var(--sh) 0 var(--edge);",
     ".card { border: var(--bw) solid var(--edge); border-radius: var(--r-md); padding: 18px 20px; box-shadow: 0 6px 18px var(--edge);", shadows_ok),
    ("a soft shadow token", "--shadow-pop: 6px 6px 0 var(--edge);\n  --box", "--shadow-pop: 0 8px 24px var(--edge);\n  --box", shadows_ok),
    ("a yellow badge", ".badge.sel { background: var(--tile-yellow);", ".badge.sel { background: var(--cta);", lambda s: cta_ok(s, CTX.js)),
    ("the yellow as a text colour", "a.badge { text-decoration: none; }", "a.badge { text-decoration: none; color: var(--cta); }", lambda s: cta_ok(s, CTX.js)),
    ("violet links", "a { color: var(--ink); text-decoration-thickness: 2px;", "a { color: var(--accent); text-decoration-thickness: 2px;", links_ok),
    ("the open tab without the pale violet", ".tabs button[aria-selected=\"true\"] { background: var(--select);", ".tabs button[aria-selected=\"true\"] { background: var(--ink);", links_ok),
    ("the open filter without the pale violet", ".dd.on > summary, .dd[open] > summary, .dd-fold[open] > summary { background: var(--select);",
     ".dd.on > summary, .dd[open] > summary, .dd-fold[open] > summary { background: var(--surface);", links_ok),
]
CTX: Ctx | None = None


@check("DE10 mutation test: token, contrast, font, motion, intensity, shadow, call-to-action and link bugs are each caught")
def de10(c: Ctx):
    global CTX
    CTX = c
    missed = []
    for name, old, new, fn in MUTANTS:
        if c.css.count(old) < 1:
            missed.append(f"{name} (anchor gone)")
            continue
        try:
            ok = fn(c.css.replace(old, new, 1))[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    if "      if (hadFocus) tog.focus();\n" not in c.js:
        missed.append("the profile bar's focus restore (anchor gone)")
    elif focus_ok(c.js.replace("      if (hadFocus) tog.focus();\n", "", 1))[0]:
        missed.append("the profile bar's toggle loses the keyboard focus")
    js_mut = c.js.replace("const store = {", 'const DE_PROBE = "var(--cta)";\nconst store = {', 1)
    if js_mut != c.js and cta_ok(c.css, js_mut)[0]:
        missed.append("app.js painting with the call-to-action colour")
    n = len(MUTANTS) + 2
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, browser or real)
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
