"""Red team of sprint R4 (owner, 2026-11-12): visual improvements. Result cards, zone shapes, charts and colour tokens.

    python scripts/redteam_visuel.py [--db data/suptracker.duckdb] [--real] [--browser]

  VI1 tokens: every colour lives in a token; the light block, the dark media block and the [data-theme="dark"] block define the
      same colour tokens, the two dark blocks with the same values; no colour literal in a rule (the print block aside) or in app.js
  VI2 the data ramp (--c1..--c6) is neutral and ordered (light: dark to light; dark: light to dark), and far (RGB distance >= 60)
      from every zone, bac route and accent token in every theme: a chart that is not about zones never borrows a zone's colour
  VI3 contrast (WCAG): ink and muted text on the page and on cards >= 4.5; the pill text (--surface) on each zone fill >= 4.5; each
      zone token as a mark on a card >= 3, in every theme
  VI4 zone marks (Node): sécurité = rond, cible = carré, ambitieux = triangle (CARTE_SHAPE), every other reading an empty ring;
      the pill and the badge carry the mark AND the name (never the colour alone), escaped; an unknown zone reads "non situé"; the
      map markers and the "Où je me situe" chart draw the same shape through the one helper; no zone badge is drawn by hand
  VI5 result card (Node): escaped strings; a zoned card has the zone's token as its left edge (never the accent) and its pill;
      the OFFICIAL rate is labelled as such; the series estimate appears only when the answer carries one (0 % included), said as
      an estimation, "peu de candidats" when fragile; capacity, complementary admits; never a chance
  VI6 the API (the warehouse): for a bac techno / pro profile every zoned result carries the estimate of the FULL type's stage-2
      row (independent reading: no `only`, no row limit) and its fragile flag; a bac général profile and results of an older
      campaign carry none
  VI7 charts (Node): every line and bar chart has an accessible name with its series (escaped); a neutral series is dashed (the
      i-th dash), a series with its own colour stays solid; the line legend draws the same dash; gaps stay gaps; no emoji marker
      anywhere in the page code; every line chart is preceded by a line legend
  VI8 browser (--browser / --real): the search page with a bac général and a bac techno profile, light, dark and phone: cards drawn
      with their marks, the left edge in the zone's colour, 0 JS error, no horizontal scroll; the formation page's charts named
  VI9 wiring and docs: feature, release guard, README section, CLAUDE.md rule
  VI10 mutation test of VI1-VI7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import filtres as FI  # noqa: E402
from suptracker import journey as J  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")
ZONE_TOKENS = ("zone-securite", "zone-cible", "zone-ambitieux", "zone-autre")
SEMANTIC = ZONE_TOKENS[:3] + ("voie-bg", "voie-bt", "voie-bp", "accent")
RAMP = tuple(f"c{i}" for i in range(1, 7))


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.fi_src = (ROOT / "suptracker" / "filtres.py").read_text()
        self.FI = FI
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


def load_module(src: str):
    """The filters module from a (possibly mutated) source, in the package (relative imports work)."""
    spec = importlib.util.spec_from_loader("suptracker.filtres_vi", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "suptracker"
    exec(compile(src, "filtres_vi.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        one = m.start() + e.end()
        end = js.find("\n};", m.start())
        if end != -1 and js[m.start():one].count("{") > js[m.start():one].count("}"):
            return js[m.start(): end + 3]
        return js[m.start(): one]
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return "__error__ " + r.stderr[-800:]
    return r.stdout


# ------------------------------------------------------------------ colours
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(h: str) -> float:
    c = [x / 255 for x in _rgb(h)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def dist(a: str, b: str) -> float:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5


def themes(css: str) -> dict:
    """{light, dark_media, dark_attr}: the hex colour tokens of each theme (the light theme spans every bare :root block)."""
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    body = re.sub(r"@media print\s*\{.*$", "", body, flags=re.S)       # the print block is the last one: black on white by design
    tok = lambda b: dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", b))  # noqa: E731
    light, dm, da = {}, {}, {}
    for m in re.finditer(r"(?m)^:root\s*\{([^}]*)\}", body):
        light.update(tok(m.group(1)))
    for m in re.finditer(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{([^}]*)\}", body):
        dm.update(tok(m.group(1)))
    for m in re.finditer(r"(?m)^:root\[data-theme=\"dark\"\]\s*\{([^}]*)\}", body):
        da.update(tok(m.group(1)))
    return {"light": light, "dark_media": dm, "dark_attr": da}


def block_doublette(js: str) -> str:
    """The doublette chart's lines (a route colour means the bac route: the national doublette line never borrows one)."""
    i = js.find("const lines = [{ name: \"Tous les bacheliers généraux du groupe\"")
    return js[i: js.find("second = `", i)] if i != -1 else ""


def tokens_ok(css: str, js: str) -> tuple[bool, str]:
    t = themes(css)
    bad = []
    colour_names = [k for k in t["light"] if re.match(r"(?:c[1-6]|zone-|voie-|accent|bg$|surface|ink|muted|line|adm-)", k)]
    for k in colour_names:
        for th in ("dark_media", "dark_attr"):
            if k not in t[th]:
                bad.append((th, "missing", k))
    for k in set(t["dark_media"]) | set(t["dark_attr"]):
        if t["dark_media"].get(k) != t["dark_attr"].get(k):
            bad.append(("dark blocks differ", k))
    # no colour literal in a rule: strip the token blocks, the print block and the comments, then look for any colour
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    body = re.sub(r"@media print\s*\{.*$", "", body, flags=re.S)
    body = re.sub(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root[^{]*\{[^}]*\}\s*\}", "", body)
    body = re.sub(r"(?m)^:root(?:\[data-theme=\"dark\"\])?\s*\{[^}]*\}", "", body)
    lit = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", body)
    if lit:
        bad.append(("colour literal in a rule", lit[:3]))
    js_lit = [m for m in re.findall(r"(?<![&\w/])#[0-9a-fA-F]{6}\b|rgba?\(\s*\d", js)]
    if js_lit:
        bad.append(("colour literal in app.js", js_lit[:3]))
    if not re.search(r"\.rc-est \{[^}]*white-space: normal", css):
        bad.append("the estimate's sentence cannot wrap in the nowrap figure column (Codex)")
    glyph = re.findall(r'content:\s*"([^"]*[\u2600-\u27bf\U0001f000-\U0001faff][^"]*)"', css)   # a drawn icon, never an emoji as a CSS marker
    if glyph:
        bad.append(("a glyph used as a CSS marker", glyph[:3]))
    if re.search(r'color: "var\(--voie-[a-z]+\)"', block_doublette(js)):
        bad.append("a route colour used for a doublette line")
    pr = re.search(r"@media print\s*\{(?:\s*/\*.*?\*/)?\s*:root:root:root\s*\{([^}]*)\}", css, re.S)
    ptok = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", pr.group(1))) if pr else {}
    lost = [k for k in RAMP + ZONE_TOKENS if ptok.get(k) != themes(css)["light"].get(k)]
    if lost:
        bad.append(("printing from the dark theme keeps dark tokens", lost[:4]))
    for k in ("zone-autre", "shadow-tip", "shadow-pop"):
        if not re.search(rf"--{k}:", css):
            bad.append(("token missing", k))
    return not bad, f"{len(colour_names)} colour tokens x 3 themes; problems {bad[:4]}"


@check("VI1 tokens: every colour is a token, the same set in the three theme blocks, the dark ones equal; no literal in a rule or in app.js")
def vi1(c: Ctx):
    return tokens_ok(c.css, c.js)


def ramp_ok(css: str) -> tuple[bool, str]:
    t = themes(css)
    bad = []
    for th, light_first in (("light", True), ("dark_media", False), ("dark_attr", False)):
        tok = t[th]
        if any(k not in tok for k in RAMP):
            bad.append((th, "ramp incomplete"))
            continue
        lums = [_lum(tok[k]) for k in RAMP]
        if lums != sorted(lums, reverse=not light_first):
            bad.append((th, "ramp not ordered", [tok[k] for k in RAMP]))
        for k in RAMP:
            r, g, b = _rgb(tok[k])
            if max(r, g, b) - min(r, g, b) > 40:
                bad.append((th, k, tok[k], "not neutral"))
            for s in SEMANTIC:
                if s in tok and dist(tok[k], tok[s]) < 60:
                    bad.append((th, k, tok[k], s, tok[s]))
    return not bad, f"3 themes; problems {bad[:4]}"


@check("VI2 the data ramp is neutral, ordered, and far from every zone, bac route and accent colour in every theme")
def vi2(c: Ctx):
    return ramp_ok(c.css)


def contrast_ok(css: str) -> tuple[bool, str]:
    t = themes(css)
    bad, low = [], []
    for th, tok in t.items():
        if not all(k in tok for k in ("bg", "surface", "ink", "muted") + ZONE_TOKENS):
            bad.append((th, "tokens missing"))
            continue
        for fg in ("ink", "muted"):
            for bgk in ("bg", "surface"):
                r = contrast(tok[fg], tok[bgk])
                low.append(r)
                if r < 4.5:
                    bad.append((th, fg, bgk, round(r, 2)))
        for z in ZONE_TOKENS:
            pill = contrast(tok["surface"], tok[z])           # the pill's text is the surface colour on the zone fill
            mark = contrast(tok[z], tok["surface"])
            if pill < 4.5:
                bad.append((th, "pill text", z, round(pill, 2)))
            if mark < 3:
                bad.append((th, "mark", z, round(mark, 2)))
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    body = re.sub(r"@media print\s*\{.*$", "", body, flags=re.S)
    text_ramp = sorted(set(re.findall(r"(?<![-\w])color:\s*var\(--(c[1-6])\)", body)))
    for th, tok in t.items():
        for k in text_ramp:
            if k in tok and "surface" in tok and contrast(tok[k], tok["surface"]) < 4.5:
                bad.append((th, "ramp colour as text", k, round(contrast(tok[k], tok["surface"]), 2)))
    return not bad, f"3 themes; lowest text contrast {round(min(low), 2) if low else None}; ramp steps used as text {text_ramp}; problems {bad[:4]}"


@check("VI3 contrast: text on page and card >= 4.5, the pill's text on every zone fill >= 4.5, zone marks >= 3, every theme")
def vi3(c: Ctx):
    return contrast_ok(c.css)


# ------------------------------------------------------------------ Node harnesses
def base_defs(js: str) -> str:
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const AUTRES_LABEL = ", "const autresBadge = ")))
    zones = re.search(r"^const ZONES = \{.*?^\};", js, re.M | re.S).group(0)
    parts = [top(js, n) for n in ("zoneShape", "ZONE_FILLED", "zoneMark", "zonePillHtml", "zoneBadge")]
    return helpers + "\n" + zones + "\n" + "\n".join(parts)


MARK_PROG = r"""
const H = "<img src=x onerror=alert(1)>";
ZONES.hostile = { label: H, color: "var(--zone-autre)" };
const ks = ["securite", "cible", "ambitieux", "hors_profil", "indetermine", "non_ouvert"];
const out = { marks: {}, pills: {}, badges: {} };
for (const k of ks) { out.marks[k] = zoneMark(k); out.pills[k] = zonePillHtml(k, k === "cible"); out.badges[k] = zoneBadge(k, false); }
out.hostilePill = zonePillHtml("hostile"); out.hostileBadge = zoneBadge("hostile");
out.unknownBadge = zoneBadge("zzz"); out.unknownPill = zonePillHtml("zzz");
out.carte = ["securite", "cible", "ambitieux"].map((z) => zoneShape(z, 9, 9, 6.8, 'fill="x"'));
process.stdout.write(JSON.stringify(out));
"""


def marks_ok(js: str) -> tuple[bool, str]:
    r = node(base_defs(js) + MARK_PROG)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    shape = lambda h: "circle" if "<circle" in h else "rect" if "<rect" in h else "path" if "<path" in h else None  # noqa: E731
    want = {"securite": "circle", "cible": "rect", "ambitieux": "path"}
    carte_shape = re.search(r'const CARTE_SHAPE = \{ securite: "rond", cible: "carré", ambitieux: "triangle" \};', js)
    if not carte_shape:
        bad.append("the map's shape names changed")
    for k, s in want.items():
        if shape(o["marks"][k]) != s or 'fill="currentColor"' not in o["marks"][k]:
            bad.append((k, "mark shape", o["marks"][k][:80]))
    for k in ("hors_profil", "indetermine", "non_ouvert"):
        if shape(o["marks"][k]) != "circle" or 'fill="none"' not in o["marks"][k] or "stroke=" not in o["marks"][k]:
            bad.append((k, "other readings are an empty ring"))
    if len({o["marks"][k] for k in want}) != 3:
        bad.append("two zones share a mark")
    for k in want:
        if [shape(x) for x in o["carte"]] != list(want.values()):
            bad.append("map markers do not use the zone shapes")
            break
    zl = {"securite": "de sécurité", "cible": "cible", "ambitieux": "ambitieux", "hors_profil": "Hors-profil", "indetermine": "Indéterminé",
          "non_ouvert": "Non ouvert"}
    for k, lab in zl.items():
        for kind in ("pills", "badges"):
            h = o[kind][k]
            if 'class="zmark"' not in h or 'aria-hidden="true"' not in h or lab not in h:
                bad.append((k, kind, "mark and name"))
        if f"var(--zone-{k})" not in o["pills"][k] and k in want:
            bad.append((k, "pill not in the zone token"))
    if "incertain" not in o["pills"]["cible"]:
        bad.append("uncertain not said on the pill")
    if "<img" in o["hostilePill"] + o["hostileBadge"] or "&lt;img" not in o["hostilePill"] or "&lt;img" not in o["hostileBadge"]:
        bad.append("zone label not escaped")
    if "non situé" not in o["unknownBadge"] or o["unknownPill"] != "":
        bad.append("an unknown zone is drawn")
    # the zone is drawn only through the helpers: no hand-made zone badge or pill, scatter and map through zoneShape
    hand = re.findall(r'style="border-color:\$\{ZONES\[|class="zone-pill"', js)
    if len(hand) != 1:                                                  # the one zone-pill is inside zonePillHtml
        bad.append(("a zone drawn by hand", len(hand)))
    if "g += zoneShape(f.zone, x(f.taux_acces_ens)" not in js or "zoneShape(z, 9, 9," not in js:
        bad.append("scatter or map marker not drawn with the zone shape")
    # review: a reading outside the three zones is an empty ring everywhere (chart, map marker, map legend), never a disc
    if 'fill="${filled ? c : "var(--surface)"}"' not in js or "const c = ZONES[f.zone].color, filled = ZONE_FILLED.includes(f.zone)" not in js:
        bad.append("the chart fills the other readings")
    if 'z === "autre" ? zoneShape(z, 9, 9, 5.8, `fill="var(--surface)" stroke="${col}"' not in js \
            or 'const CARTE_OTHER = { label: "Autre ou non situé", color: "var(--zone-autre)" };' not in js:
        bad.append("the map draws 'autre' as a disc, or in another token")
    if js.count('class="badge zbadge"') != 2:
        bad.append(("a zone badge drawn outside its helpers", js.count('class="badge zbadge"')))
    return not bad, f"{len(zl)} zone readings; problems {bad[:4]}"


@check("VI4 zone marks (Node): rond, carré, triangle, a ring for the others; mark AND name; escaped; one helper for every zone drawing")
def vi4(c: Ctx):
    return marks_ok(c.js)


CARD_PROG = r"""
const META = { low_n_threshold: 20 };
const FI_HELP = { complementaire: "Des admis en phase complémentaire" };
const FILI_LABEL = { BTS: "BTS" };
const ICONS = { places: '<svg class="ico" aria-hidden="true"></svg>' };
const lineageBadge = () => '<span class="badge exact">exact</span>';
const offerBadges = (r) => (r.internat === "oui" ? '<span class="badge offer">Internat</span>' : "");
const H = "<img src=x onerror=alert(1)>";
const base = { cod_aff_form: "123", g_ea_lib_vx: H, ville_etab: "<b>Lyon</b>", acad_mies: "<i>Lyon</i>", fil_lib_voe_acc: "<u>BTS</u>",
  lib_comp_voe_ins: "<s>MCO</s>", fili: "BTS", session: 2025, lineage_years: 4, lineage_confidence: "exact", taux_acces_ens: 63.5,
  capa_fin: 24, acc_pc: 3, internat: "oui" };
const out = {
  plain: resultCard({ ...base }),
  zoned: resultCard({ ...base, zone: "cible", uncertain: true }),
  est: resultCard({ ...base, zone: "ambitieux", estime_serie: 12, estime_fragile: false }),
  est0: resultCard({ ...base, zone: "ambitieux", estime_serie: 0, estime_fragile: true }),
  estNull: resultCard({ ...base, zone: "securite", estime_serie: null }),
  other: resultCard({ ...base, zone: "hors_profil" }),
  noRate: resultCard({ ...base, taux_acces_ens: null, capa_fin: null, acc_pc: 0 }),
};
process.stdout.write(JSON.stringify(out));
"""


def card_ok(js: str) -> tuple[bool, str]:
    r = node(base_defs(js) + "\n" + top(js, "resultCard") + CARD_PROG)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    for k, h in o.items():
        if re.search(r"<(?:img|b|i|u|s)>|<img ", h):
            bad.append((k, "unescaped"))
        if CHANCE.search(h):
            bad.append((k, "chance wording"))
        if "taux d'accès officiel" not in h.replace("&#39;", "'"):
            bad.append((k, "official rate not labelled"))
    if "rc-z" in o["plain"] or "--zc" in o["plain"] or "zone-pill" in o["plain"]:
        bad.append("a card without a zone reading draws one")
    if 'class="result rc rc-z" style="--zc:var(--zone-cible)"' not in o["zoned"] or "zone-pill" not in o["zoned"] or "incertain" not in o["zoned"]:
        bad.append("the zoned card's edge or pill")
    if "var(--accent)" in "".join(o.values()):
        bad.append("the accent used for a zone")
    if 'style="--zc:var(--zone-autre)"' not in o["other"] or "Hors-profil" not in o["other"]:
        bad.append("another reading is not drawn with its own token and name")
    est = lambda h: re.search(r'<div class="rc-est">(.*?)</div>', h, re.S)  # noqa: E731
    if not est(o["est"]) or "12 %" not in est(o["est"]).group(1) or "estimation" not in est(o["est"]).group(1) or "peu de candidats" in est(o["est"]).group(1):
        bad.append(("series estimate", est(o["est"]) and est(o["est"]).group(1)))
    if not est(o["est0"]) or "0 %" not in est(o["est0"]).group(1) or "peu de candidats" not in est(o["est0"]).group(1):
        bad.append("a 0 % estimate hidden, or fragile not said")
    if est(o["plain"]) or est(o["estNull"]) or est(o["zoned"]):
        bad.append("an estimate drawn without one")
    if "24 places" not in o["plain"] or "admis en phase complémentaire 2025" not in o["plain"] or "places" in o["noRate"] or "phase complémentaire" in o["noRate"]:
        bad.append("capacity or complementary admits")
    if "63,5 %" not in o["plain"].replace(" ", " ").replace("\xa0", " ") or "—" not in o["noRate"]:
        bad.append("the official rate figure")
    if 'href="#/f/123"' not in o["plain"]:
        bad.append("the card does not link its formation")
    return not bad, f"{len(o)} cards; problems {bad[:4]}"


@check("VI5 result card (Node): escaped, zone edge and pill, OFFICIAL rate labelled, series estimate only when given (0 % too), never a chance")
def vi5(c: Ctx):
    return card_ok(c.js)


# ------------------------------------------------------------------ VI6 the API
@contextmanager
def client(c: Ctx, fi):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved, saved_fi = os.environ.get("SUPTRACKER_DB"), A.record, api.FI
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    api.FI = fi
    try:
        yield TestClient(api.app)
    finally:
        A.record, api.FI = saved, saved_fi
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


def api_ok(c: Ctx, fi) -> tuple[bool, str]:
    cur = c.con.cursor()
    latest = cur.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    types = dict(cur.execute("""SELECT t.cod_aff_form, r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
                                WHERE t.session = ?""", [latest]).fetchall())
    queries = ["bts", "licence", "but", "sti2d", "cpge ect"]          # the last two also return older campaigns (review)
    bad, n_est, n_frag, n_zoned, n_old, full = [], 0, 0, 0, 0, {}
    with client(c, fi) as tc:
        for serie, mention in (("bt", "ab"), ("bp", "sansmention"), ("bg", "b")):
            for q in queries:
                params = {"q": q, "avance": "true", "limit": 60, "serie": serie, "mention": mention}
                if serie == "bg":
                    params.update({"spe1": "MATHS", "spe2": "SES"})
                r = tc.get("/api/search", params=params)
                if r.status_code != 200:
                    bad.append((q, serie, r.status_code))
                    continue
                for x in r.json()["results"]:
                    has = "estime_serie" in x
                    if serie == "bg" or x["session"] != latest:
                        n_old += x["session"] != latest
                        if has:
                            bad.append((x["cod_aff_form"], x["session"], serie, "an estimate where none exists"))
                        continue
                    tk = types.get(x["cod_aff_form"])
                    if not tk:
                        if has:
                            bad.append((x["cod_aff_form"], "an estimate without a type"))
                        continue
                    key = (tk, serie, mention)
                    if key not in full:                         # the FULL type: no `only`, no row limit
                        full[key] = {f["cod_aff_form"]: f for f in J.stage2(cur, None, mention, tk, None, limit=10 ** 6, serie=serie)["formations"]}
                    row = full[key].get(x["cod_aff_form"])
                    if row is None:
                        continue
                    n_zoned += 1
                    want = row["taux_acces_ens"]
                    if want is None:
                        if has:
                            bad.append((x["cod_aff_form"], "an estimate the row lacks"))
                        continue
                    if not has or x["estime_serie"] != want or bool(x.get("estime_fragile")) != bool(row.get("rate_fragile")):
                        bad.append((x["cod_aff_form"], serie, x.get("estime_serie"), want, x.get("estime_fragile"), row.get("rate_fragile")))
                    n_est += 1
                    n_frag += bool(row.get("rate_fragile"))
    ok = not bad and n_est > 0
    return ok, f"{n_zoned} zoned techno/pro results, {n_est} estimates ({n_frag} fragile), {n_old} results of an older campaign; problems {bad[:4]}"


@check("VI6 the API: bac techno / pro results carry the full type's estimate and fragile flag; bac général and older campaigns carry none")
def vi6(c: Ctx):
    return api_ok(c, c.FI)


# ------------------------------------------------------------------ VI7 charts
CHART_PROG = r"""
const META = { low_n_threshold: 20 };
const H = "<img src=x onerror=alert(1)>";
const out = {};
out.line = lineChart([2022, 2023, 2024, 2025], [{ name: H, values: [10, null, 30, 40] }, { name: "B", values: [5, 6, 7, 8] },
  { name: "C", values: [1, 2, 3, 4] }, { name: "Voie", color: "var(--voie-bg)", values: [9, 9, 9, 9] }]);
out.legend = lineLegend([{ name: H }, { name: "B" }, { name: "C" }, { name: "Voie", color: "var(--voie-bg)" }]);
out.bars = stackedBars([2024, 2025], [{ key: "a", name: H }, { key: "b", name: "B" }], [{ a: 3, b: 1, low_n_flag: true }, null]);
process.stdout.write(JSON.stringify(out));
"""


def charts_ok(js: str) -> tuple[bool, str]:
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    defs = [top(js, n) for n in ("COLORS", "DASHES", "seriesDash", "chartName", "lineChart", "stackedBars", "lineLegend")]
    r = node(helpers + "\n" + "\n".join(defs) + CHART_PROG)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    for k in ("line", "bars"):
        lab = re.search(r'<svg class="chart"[^>]*role="img" aria-label="([^"]*)"', o[k])
        if not lab or "&lt;img" not in lab.group(1) or "Graphique" not in lab.group(1) or "2022" not in lab.group(1) and k == "line":
            bad.append((k, "no accessible name", lab and lab.group(1)))
        if "<img" in o[k]:
            bad.append((k, "unescaped"))
    paths = re.findall(r'<path d="([^"]*)" fill="none" stroke="([^"]*)" stroke-width="2"( stroke-dasharray="([^"]*)")?/>', o["line"])
    dashes = [p[3] for p in paths]
    if len(paths) != 4 or dashes[0] != "" or len({d for d in dashes[:3]}) != 3 or dashes[3] != "":
        bad.append(("dash patterns", dashes))
    if paths and paths[0][0].count("M") != 2:
        bad.append("a gap interpolated")
    leg = re.findall(r'<line [^>]*stroke="([^"]*)" stroke-width="2.5"(?: stroke-dasharray="([^"]*)")?/>', o["legend"])
    if [d for _, d in leg] != dashes or "&lt;img" not in o["legend"]:
        bad.append(("the legend's dashes differ from the lines", [d for _, d in leg]))
    if "⚠" in js or "⚠" in o["bars"]:
        bad.append("an emoji used as a marker")
    if re.search(r"\$\{legend\([^)]*\)\}\s*\$\{lineChart\(", js) or re.search(r"\$\{legend\(\[[^\]]*\]\)\}\s*\n\s*\$\{lineChart\(", js):
        bad.append("a line chart with a colour-only legend")
    if js.count("${lineLegend(") < 5:
        bad.append(("line legends", js.count("${lineLegend(")))
    if 'role="img" aria-label="Où je me situe' not in js:
        bad.append("the positioning chart has no name")
    return not bad, f"line dashes {dashes}; problems {bad[:4]}"


@check("VI7 charts (Node): named with their series, neutral series dashed and the legend alike, own-colour series solid, gaps kept, no emoji")
def vi7(c: Ctx):
    return charts_ok(c.js)


# ------------------------------------------------------------------ VI8 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2];
const PROFILES = { bg: { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b", statut: "terminale" },
  bt: { serie: "bt", mention: "ab", statut: "terminale", voie: "autre" } };
(async () => {
  const b = await chromium.launch(); const o = {}; const errs = [];
  for (const [name, opts] of [["light", { viewport: { width: 1280, height: 900 }, colorScheme: "light" }],
    ["dark", { viewport: { width: 1280, height: 900 }, colorScheme: "dark" }], ["phone", { ...devices["iPhone 13"] }],
    ["small", { viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true }]]) {   // Codex: the smallest phones
    for (const prof of ["bg", "bt"]) {
      const ctx = await b.newContext(opts);
      await ctx.addInitScript((p) => localStorage.setItem("profile", JSON.stringify(p)), PROFILES[prof]);
      const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(`${name}/${prof}: ${e.message}`));
      await p.goto(base + "/#/s/bts");
      await p.waitForFunction(() => (document.getElementById("view").dataset.rendered || "").startsWith("s:"), null, { timeout: 30000 });
      o[`${name}/${prof}`] = await p.evaluate(() => {
        const cards = [...document.querySelectorAll("article.result.rc")];
        const zoned = cards.filter((c) => c.classList.contains("rc-z"));
        const edgeOk = zoned.every((c) => {
          const pill = c.querySelector(".zone-pill");
          return pill && getComputedStyle(c).borderLeftColor === getComputedStyle(pill).backgroundColor;
        });
        // Codex: no card content wider than its card (the estimate's sentence must wrap)
        const spill = cards.filter((c) => [...c.querySelectorAll(".rc-est, .rc-fig, .rc-main")].some((e) => e.scrollWidth > c.clientWidth + 1
          || e.getBoundingClientRect().right > c.getBoundingClientRect().right + 1)).length;
        return { spill, cards: cards.length, zoned: zoned.length, marks: document.querySelectorAll("article.result .zone-pill svg.zmark").length,
          est: document.querySelectorAll("article.result .rc-est").length, edgeOk,
          hs: document.documentElement.scrollWidth > document.documentElement.clientWidth };
      });
      await ctx.close();
    }
  }
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } }); const p = await ctx.newPage();
  p.on("pageerror", (e) => errs.push(`formation: ${e.message}`));
  await p.goto(base + "/#/s/bts"); await p.waitForTimeout(1500);
  const href = await p.$eval("article.result a.rc-title", (a) => a.getAttribute("href"));
  await p.goto(base + "/" + href.replace("#/f/", "#/evolution/")); await p.waitForTimeout(3000);
  o.named = await p.$$eval("svg.chart", (s) => s.map((x) => !!x.getAttribute("aria-label")));
  await ctx.close();
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


@check("VI8 browser: cards with marks and the zone edge, light, dark and phone, bac général and techno; charts named; no error, no scroll")
def vi8(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".visuel_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=400, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-600:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    for k, v in o.items():
        if k == "named":
            continue
        if not v["cards"] or v["hs"] or v["spill"] or not v["edgeOk"] or v["marks"] < v["zoned"]:
            bad.append((k, v))
        if k.endswith("/bg") and v["est"]:
            bad.append((k, "a bac général card shows a series estimate"))
    if not o.get("named") or not all(o["named"]):
        bad.append(("unnamed charts", o.get("named")))
    if not any(v["est"] for k, v in o.items() if k.endswith("/bt")):
        bad.append("no bac techno estimate drawn")
    return not bad, f"{ {k: v for k, v in o.items() if k != 'named'} }; charts named {o.get('named')}; problems {bad[:3]}"


@check("VI9 wiring and docs: feature, release guard, README section, CLAUDE.md rule")
def vi9(c: Ctx):
    feat = '"cartes_resultats"' in c.api and '"cartes_resultats": ("app.js", "function resultCard(")' in c.release
    readme = "Sprint R4" in c.readme and "zoneShape" in c.readme and "neutral" in c.readme
    claude = "Visual improvements (sprint R4" in c.claude and "redteam_visuel.py" in c.claude
    return feat and readme and claude, f"feature + release guard {feat}; README {readme}; CLAUDE.md {claude}"


# ------------------------------------------------------------------ VI10 mutation test
MUTANTS = [
    ("css", "a chart colour equal to a zone's", "--c2: #4d4655;", "--c2: #2b5fd9;", (vi2,)),
    ("css", "the dark ramp out of order", "--c1: #f0ecf3; --c2: #cdc6d4;", "--c1: #cdc6d4; --c2: #f0ecf3;", (vi2,)),
    ("css", "a coloured data ramp", "--c3: #71697a;", "--c3: #2e9e6a;", (vi2,)),
    ("css", "the old ambitieux (pill text below 4.5)", "--zone-ambitieux: #b9460f; --voie-bg", "--zone-ambitieux: #c4581f; --voie-bg", (vi3,)),
    ("css", "a pale 'autre' zone", "--zone-autre: #6f6977;", "--zone-autre: #b8b2bf;", (vi3,)),
    ("css", "zone-autre missing from a dark block", "--zone-autre: #a39dab; --shadow-tip", "--shadow-tip", (vi1,)),
    ("css", "the estimate cannot wrap (Codex)", "  white-space: normal; text-align: right; }", "  text-align: right; }", (vi1,)),
    ("css", "a gear glyph as the filter marker", "details.filters > summary .ico { width: 18px; height: 18px; margin-right: 8px; }",
     'details.filters > summary::before { content: "\u2699"; margin-right: 8px; }', (vi1,)),
    ("js", "a route colour for the national doublette line", 'groupe national`, color: "var(--c2)", dash: "6 4", values', 'groupe national`, color: "var(--voie-bt)", values', (vi1,)),
    ("css", "a pale ramp step as badge text", ".fiab-B { border-color: var(--c3); color: var(--ink); }", ".fiab-B { border-color: var(--c3); color: var(--c5); }", (vi3,)),
    ("css", "printing keeps the dark ramp", "--c1: #2a2430; --c2: #4d4655; --c3: #71697a; --c4: #958d9e; --c5: #b7b0bf; --c6: #d4cedb; }   /* beats",
     "}   /* beats", (vi1,)),
    ("js", "the chart fills the other readings", 'fill="${filled ? c : "var(--surface)"}"', 'fill="${c}"', (vi4,)),
    ("js", "the map's 'autre' a disc", 'z === "autre" ? zoneShape(z, 9, 9, 5.8, `fill="var(--surface)" stroke="${col}" stroke-width="2.5"`)',
     'z === "autre" ? zoneShape(z, 9, 9, 5.8, `fill="${col}" stroke="var(--surface)" stroke-width="2.5"`)', (vi4,)),
    ("css", "a colour literal in a rule", ".rc-est strong { font-size: var(--fs-md); color: var(--ink); }",
     ".rc-est strong { font-size: var(--fs-md); color: #333333; }", (vi1,)),
    ("js", "every zone a circle", 'return z === "cible" ? `<rect', 'return z === "nope" ? `<rect', (vi4,)),
    ("js", "the pill without its mark", 'style="background:${zz.color}">${zoneMark(z)}${esc(', 'style="background:${zz.color}">${esc(', (vi4,)),
    ("js", "the badge without its name", '${zoneMark(z)}${esc(zz.label)}</span>', "${zoneMark(z)}</span>", (vi4,)),
    ("js", "the scatter in circles only", "g += zoneShape(f.zone, x(f.taux_acces_ens)", 'g += zoneShape("securite", x(f.taux_acces_ens)', (vi4,)),
    ("js", "a card title unescaped", '<a class="rc-title" href="#/f/${esc(r.cod_aff_form)}">${esc(r.g_ea_lib_vx)}</a>',
     '<a class="rc-title" href="#/f/${esc(r.cod_aff_form)}">${r.g_ea_lib_vx}</a>', (vi5,)),
    ("js", "the official rate unlabelled", '<div class="muted small">taux d\'accès officiel</div>', '<div class="muted small">taux d\'accès</div>', (vi5,)),
    ("js", "the estimate not said as one", "accès estimé pour votre bac (estimation)", "accès pour votre bac", (vi5,)),
    ("js", "a 0 % estimate hidden", "const est = r.estime_serie !== undefined && r.estime_serie !== null", "const est = r.estime_serie", (vi5,)),
    ("js", "the zone edge in the accent", '${z ? ` style="--zc:${ZONES[z].color}"` : ""}', '${z ? ` style="--zc:var(--accent)"` : ""}', (vi5,)),
    ("js", "an unnamed line chart", 'role="img" aria-label="${esc(chartName(series.map((x) => x.name), years))}"', 'role="img"', (vi7,)),
    ("js", "own-colour series dashed", 'const seriesDash = (s, i) => (s.dash !== undefined ? s.dash : s.color ? "" : DASHES[i % DASHES.length]);',
     "const seriesDash = (s, i) => DASHES[i % DASHES.length];", (vi7,)),
    ("js", "the legend without dashes", '<line x1="1" y1="4" x2="21" y2="4" stroke="${k.color || COLORS[i]}" stroke-width="2.5"${seriesDash(k, i) ? ` stroke-dasharray="${seriesDash(k, i)}"` : ""}/>',
     '<line x1="1" y1="4" x2="21" y2="4" stroke="${k.color || COLORS[i]}" stroke-width="2.5"/>', (vi7,)),
    ("js", "the emoji marker back", 'text-anchor="middle">n&lt;${META.low_n_threshold}</text>', 'text-anchor="middle">⚠ n&lt;${META.low_n_threshold}</text>', (vi7,)),
    ("js", "a colour-only legend on the comparator", "<h3>Taux d'accès 2022–2025</h3>${lineLegend(series)}", "<h3>Taux d'accès 2022–2025</h3>${legend(series)}", (vi7,)),
    ("py", "an estimate for bac général", '                                               f.get("taux_acces_ens") if serie != "bg" else None,',
     '                                               f.get("taux_acces_ens"),', (vi6,)),
    ("py", "the official rate as the estimate", 'f.get("taux_acces_ens") if serie != "bg" else None,', 'f.get("taux_acces_all") if serie != "bg" else None,', (vi6,)),
    ("py", "fragile never said", 'bool(f.get("rate_fragile")))', "False)", (vi6,)),
]


@check("VI10 mutation test: token, ramp, contrast, mark, card, API and chart bugs are each caught")
def vi10(c: Ctx):
    missed = []
    for kind, name, old, new, checks in MUTANTS:
        src = {"css": c.css, "js": c.js, "py": c.fi_src}[kind]
        if src.count(old) < 1 or (src.count(old) > 1 and kind != "css"):
            missed.append(f"{name} (anchor gone)")
            continue
        mut = src.replace(old, new, 1)                                   # css: the first block only (the dark media one)
        caught = False
        for fn in checks:
            try:
                if kind == "css":
                    ok = {vi1: lambda: tokens_ok(mut, c.js), vi2: lambda: ramp_ok(mut), vi3: lambda: contrast_ok(mut)}[fn]()[0]
                elif kind == "js":
                    ok = {vi1: lambda: tokens_ok(c.css, mut), vi4: lambda: marks_ok(mut), vi5: lambda: card_ok(mut), vi7: lambda: charts_ok(mut)}[fn]()[0]
                else:
                    ok = api_ok(c, load_module(mut))[0]
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                caught = True
                break
        if not caught:
            missed.append(name)
    n = len(MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


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
