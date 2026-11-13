"""Red team, sprint Q4 (owner, 2026-11-13): plain language and human help.

The red-team evaluation (Psy-EN expert, 11/15) found jargon ("doublette", "en position de recevoir", "votre ligne"), six
different ways of saying "estimation", zones never explained in words, no "what now?" and no way to a person. Checks:

  LA1 jargon: none of the banned words in what a student reads: the page script's visible strings (scripts/jstext.py: string
      literals and the fixed parts of templates, tags and code attributes removed), index.html, the method texts, the glossary,
      every page of legal.py (help page included) and the visible strings of the modules that write messages. One form is
      allowed, to teach the official word once: « doublette » after "on dit aussi" or in the glossary title.
  LA2 one estimation label: estimTag is the only maker of the label; it carries the same short explanation (ESTIM_DEF: not an
      official figure, not a chance) except inside a button; no raw "estimation" badge is left; every renderer of a computed
      figure (ESTIMATE_RENDERERS) calls it.
  LA3 zones explained: zoneHelp is written from ZONE_RULES, which equal journey.ZONE_RULES; each zone's text carries its own
      thresholds, run in Node; the legend covers the four zones and says "jamais une chance"; every zone pill and badge has
      its explanation as a title; the pages that show zones (summary, Mes vœux, Où je me situe) show the legend.
  LA4 "Et maintenant ?": every kind has its page (NEXT_PAGES), every block ends with the help page, every link is an app route
      or an https page, and no step carries a figure.
  LA5 human help: only official hosts over https; phone numbers equal this red team's own table, and the tel: link dials the
      number shown; no opening hours printed (they change); the check date and "n'est lié à aucun" are said; the page is in
      legal.SLUGS, the footer, both menus, INFO_SLUGS, pathRoute and the cache policy.
  LA6 readability: in the short texts a student reads first (glossary, help page, zone texts, estimation text, next steps)
      no sentence is longer than MAX_WORDS words and the Kandel-Moles score (French Flesch) is at least MIN_KM; the method
      texts keep every sentence under MAX_WORDS_METHOD words (no regression).
  LA7 browser (--browser / --real): on a phone, the formation page and Mes vœux show one "Et maintenant ?" and the zone legend,
      the help page lists every service with its phone links, no horizontal scroll, no JS error.
  LA8 the tokenizer reads exactly the strings of a full JavaScript parser (acorn, when installed), and the mutation test:
      every seeded bug is caught.
"""
from __future__ import annotations

import argparse
import html as H
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
sys.path.insert(0, str(ROOT / "scripts"))
import jstext  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []

BANNED = re.compile(r"\bdoublettes?\b|\ben position de\b|\bvotre ligne\b|\bvos lignes\b", re.I)
ALLOWED = re.compile(r"(?:on dit aussi |\()« doublette »", re.I)
PY_TEXT = ["voeux.py", "planb.py", "journey.py", "reorientation.py", "voies.py", "metiers.py", "licence_master.py", "insertion.py",
           "passerelles.py", "success.py", "poursuite.py", "cereq.py", "onisep.py", "evidence.py", "prevision.py", "calendrier.py",
           "seo.py", "semblables.py", "rapports.py", "carte.py", "filtres.py", "admis.py", "appel.py", "selectivite.py"]
CODE_STRING = re.compile(r"\b(?:SELECT|CREATE|INSERT|FROM|WHERE|JOIN)\b|^[\w.:/-]*$")
# every renderer of a computed figure, with its number of computed figures (each one labelled by estimTag)
ESTIMATE_RENDERERS = {"resultCard": 1, "doubletteCard": 3, "cartePosFigure": 2, "PR_SOURCE": 2, "stage1Matrix": 1, "moyRange": 1,
                      "viewParcours": 1, "dblFigure": 2, "reoCell": 1}
NEXT_PAGES = {"formation": ("viewFormation",), "parcours": ("viewParcours",), "voeux": ("viewVoeux", "viewVoeuxReo"),
              "reorientation": ("viewReorientation",), "metier": ("viewMetier",), "premiere": ("viewPremiere",)}
ZONE_PAGES = ("summaryBand", "viewVoeux", "viewParcours")
# the red team's own copy of what the services publish (checked on their sites, 2026-11-13), never read from aide.py
PHONES = {"moel": "01 77 77 12 25", "parcoursup": "0 800 400 070", "ecoute": "0 800 235 236"}
HOSTS = {"www.parcoursup.gouv.fr", "www.onisep.fr", "www.education.gouv.fr", "www.filsantejeunes.com", "www.monparcourshandicap.gouv.fr"}
HOURS = re.compile(r"\b\d{1,2} ?h(?: ?\d{2})?\b|\bheures?\b|\b24 ?h ?/ ?24\b|\bdu lundi\b", re.I)
MAX_WORDS, MIN_KM, MAX_WORDS_METHOD = 30, 70.0, 70


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
        self.html = (STATIC / "index.html").read_text()
        from suptracker import aide as AI
        from suptracker import glossary as G
        from suptracker import legal as LG
        from suptracker.api import METHODOLOGY
        self.AI, self.LG = AI, LG
        self.methodology = dict(METHODOLOGY)
        self.glossary = {k: (t, d) for k, (t, d, _m) in G.GLOSSARY.items()}


# ---------------------------------------------------------------- helpers
def defn(js: str, name: str) -> str:
    """A top-level function or const of the page script, whole: a function up to its closing line, a const up to the ";" that
    ends it outside brackets, strings and templates (scripts/jstext.py skips those)."""
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        return ""
    if not js[m.start():].startswith("const "):
        return js[m.start(): js.find("\n}", m.start()) + 2]
    first = js[m.start(): js.index("\n", m.start())]
    if first.rstrip().endswith(";"):
        return first
    i, depth = m.end(), 0
    while i < len(js):
        ch = js[i]
        if ch in "'\"":
            i = jstext._quoted(js, i, ch)[0]
            continue
        if ch == "`":
            i = jstext._template(js, i, [])
            continue
        if ch == "/" and js.startswith("//", i):
            i = js.index("\n", i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0:
            return js[m.start(): i + 1]
        i += 1
    return js[m.start():]


def node_eval(js: str, names: list[str], expr: str):
    node = shutil.which("node")
    if not node:
        return None
    prog = defn(js, "esc") + "\n" + "\n".join(defn(js, n) for n in names) + f"\nprocess.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout)


def js_visible(js: str) -> list[str]:
    out = []
    for _off, t in jstext.strings(js):
        v = jstext.visible(t)
        if re.search(r"\s", v) or v[:1].isupper():
            out.append(v)
    return out


def py_visible(path: Path) -> list[str]:
    import ast
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
            and not CODE_STRING.search(n.value)]


def page_text(h: str) -> str:
    return H.unescape(re.sub(r"<[^>]+>", " ", h))


V = "aeiouyàâäéèêëîïôöùûüœæ"


def syllables(w: str) -> int:
    w = w.lower()
    n = len(re.findall(f"[{V}]+", w))
    if n > 1 and re.search(rf"[^{V}](?:e|es|ent)$", w):
        n -= 1
    return max(1, n)


def sentences(t: str) -> list[str]:
    """Sentences, and every heading, paragraph, list item or table cell on its own (a block is never one long sentence)."""
    t = re.sub(r"</?(?:p|h\d|li|ul|ol|section|div|td|th|tr|br)\b[^>]*>", "\n", t)
    out = []
    for block in page_text(t).split("\n"):
        block = re.sub(r"\s+", " ", block).strip()
        out += [s for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«0-9])", block) if re.search(r"\w", s)]
    return out


def words(s: str) -> list[str]:
    return re.findall(r"[\wÀ-ÿœ'’-]+", s)


def kandel_moles(t: str) -> float:
    """Kandel & Moles (1958), the French adaptation of Flesch: 207 - 1.015 x words/sentence - 73.6 x syllables/word."""
    S = sentences(t)
    W = [w for s in S for w in words(s)]
    return 207 - 1.015 * len(W) / len(S) - 73.6 * sum(syllables(w) for w in W) / len(W)


def short_texts(c: Ctx) -> dict[str, str]:
    out = {f"glossaire[{k}]": d for k, (_t, d) in c.glossary.items()}
    out["aide"] = c.AI.page()
    z = node_eval(c.js, ["ZONE_RULES", "zoneHelp", "ZONE_NOT_CHANCE", "ESTIM_DEF", "AIDE_STEP", "NEXT_STEPS"],
                  "{zones: ['securite','cible','ambitieux','hors_profil'].map(zoneHelp), nc: ZONE_NOT_CHANCE, est: ESTIM_DEF, "
                  "steps: [AIDE_STEP, ...Object.values(NEXT_STEPS).flat()].map((x) => x.text)}")
    if z is not None:
        for i, t in enumerate(z["zones"]):
            out[f"zone[{i}]"] = t
        out["ZONE_NOT_CHANCE"], out["ESTIM_DEF"] = z["nc"], z["est"]
        for i, t in enumerate(z["steps"]):
            out[f"étape[{i}]"] = t + "."
    return out


# ---------------------------------------------------------------- checks
@check("LA1 no jargon (doublette, en position de, votre ligne) in what a student reads")
def la1(c: Ctx):
    sources = [("app.js", v) for v in js_visible(c.js)] + [("index.html", page_text(c.html))]
    sources += [(f"méthode[{k}]", v) for k, v in c.methodology.items()]
    sources += [(f"glossaire[{k}]", f"{t} {d}") for k, (t, d) in c.glossary.items()]
    sources += [(f"page[{s}]", page_text(c.LG.page(s)["html"])) for s in c.LG.SLUGS]
    for name in PY_TEXT:
        p = ROOT / "suptracker" / name
        if p.exists():
            sources += [(name, s) for s in py_visible(p)]
    hits = []
    for src, text in sources:
        for m in BANNED.finditer(ALLOWED.sub(" ", text)):
            t = ALLOWED.sub(" ", text)
            hits.append(f"{src}: …{t[max(0, m.start() - 40): m.end() + 30]}…")
    return not hits and len(sources) > 2000, f"{len(sources)} texts read; {len(hits)} jargon hits {hits[:4]}"


@check("LA2 one estimation label (estimTag), same explanation, no raw badge, every computed-figure renderer uses it")
def la2(c: Ctx):
    probs = []
    r = node_eval(c.js, ["ESTIM_DEF", "estimTag"], "{a: estimTag('x'), b: estimTag('', true), p: estimTag('y', false, true), d: ESTIM_DEF, e: esc(ESTIM_DEF)}")
    if r is None:
        return True, "node not installed"
    d = r["d"]
    if not ("pas un chiffre officiel" in d and "chance" in d and "SupCompass" in d):
        probs.append(f"ESTIM_DEF says too little: {d}")
    for k in ("a", "b"):
        if 'class="estim-tag">estimation<' not in r[k] or f'data-tip="{r["e"]}"' not in r[k]:
            probs.append(f"estimTag without its label or its explanation: {r[k][:160]}")
    if "<button" in r["p"] or "estim-tag" not in r["p"]:
        probs.append("estimTag(plain) must keep the label without a button")
    if not r["b"].startswith("<div"):
        probs.append("estimTag(block) is not a block")
    body = c.js.replace(defn(c.js, "estimTag"), "")
    makers = [m.start() for m in re.finditer(r"estim-tag", body)]
    if makers:
        probs.append(f"{len(makers)} estimation labels made outside estimTag")
    raw = re.findall(r'class="estim">\s*\(?\s*estimation|class="estim">[^<]{0,80}?(?:· estimation|estimation ·|, estimation\b)|>estim\. ·|'
                     r'"estimation · |\(estimation[ ,:][^)]{0,10}\d', body)
    if raw:
        probs.append(f"raw estimation badges {raw[:3]}")
    missing = [f"{n} ({defn(c.js, n).count('estimTag(')} of {k})" for n, k in ESTIMATE_RENDERERS.items() if defn(c.js, n).count("estimTag(") < k]
    if missing:
        probs.append(f"renderers without estimTag {missing}")
    return not probs, f"{len(ESTIMATE_RENDERERS)} renderers; {probs[:4]}"


@check("LA3 zones explained in words from their own rules, legend on every zone page, every pill titled")
def la3(c: Ctx):
    from suptracker import journey as J
    probs = []
    r = node_eval(c.js, ["ZONE_RULES", "zoneHelp", "ZONE_NOT_CHANCE", "ZONES", "zoneShape", "ZONE_FILLED", "zoneMark", "zonePillHtml",
                         "zoneBadge", "zoneLegend"],
                  "{rules: ZONE_RULES, help: Object.fromEntries(['securite','cible','ambitieux','hors_profil'].map((z) => [z, zoneHelp(z)])), "
                  "legend: zoneLegend(), pill: zonePillHtml('cible'), badge: zoneBadge('ambitieux'), nc: ZONE_NOT_CHANCE, "
                  "e: Object.fromEntries(['securite','cible','ambitieux','hors_profil'].map((z) => [z, esc(zoneHelp(z))])), enc: esc(ZONE_NOT_CHANCE)}")
    if r is None:
        return True, "node not installed"
    R = J.ZONE_RULES
    if {k: float(v) for k, v in r["rules"].items()} != {k: float(v) for k, v in R.items()}:
        probs.append(f"ZONE_RULES {r['rules']} differ from journey {R}")
    h = r["help"]
    pct = lambda x: f"{x:g}"  # noqa: E731
    want = {"securite": [f"au moins {pct(R['securite_access'])} %", f"au moins {round(R['securite_cdf'] * 100)} admis sur 100"],
            "ambitieux": [f"sous {pct(R['ambitieux_access'])} %", f"moins de {round(R['ambitieux_cdf'] * 100)} admis sur 100"],
            "hors_profil": [f"moins de {round(R['hors_profil_cdf'] * 100)} sur 100"], "cible": ["Entre sécurité et ambitieux"]}
    for z, parts in want.items():
        for p in parts:
            if p not in h[z]:
                probs.append(f"zone {z}: '{p}' missing in «{h[z]}»")
    for z in ("securite", "cible", "ambitieux", "hors_profil"):
        if r["e"][z] not in r["legend"]:
            probs.append(f"legend without {z}")
    if "jamais une chance" not in r["nc"] or r["enc"] not in r["legend"]:
        probs.append("legend does not say 'jamais une chance'")
    if f'title="{r["e"]["cible"]}"' not in r["pill"] or f'title="{r["e"]["ambitieux"]}"' not in r["badge"]:
        probs.append("zone pill or badge without its explanation")
    missing = [n for n in ZONE_PAGES if "zoneLegend()" not in defn(c.js, n)]
    if missing:
        probs.append(f"zone pages without the legend {missing}")
    zg = c.glossary.get("zone", ("", ""))[1]
    if not all(w in zg for w in ("Sécurité", "Ambitieux", "Cible")):
        probs.append("glossary 'zone' does not explain the three zones")
    return not probs, f"{probs[:4]}"


@check("LA4 'Et maintenant ?' on every decision page, ending with a person to talk to; app routes or https; no figure")
def la4(c: Ctx):
    probs = []
    r = node_eval(c.js, ["AIDE_STEP", "NEXT_STEPS", "NEXT_KINDS", "nextSteps", "ROUTE_NAME"],
                  "{kinds: NEXT_KINDS, routes: Object.keys(ROUTE_NAME), html: Object.fromEntries(NEXT_KINDS.map((k) => [k, nextSteps(k, [{href: 'https://x.test/', text: 'Fiche'}])])), "
                  "items: NEXT_STEPS, aide: AIDE_STEP}")
    if r is None:
        return True, "node not installed"
    if set(r["kinds"]) != set(NEXT_PAGES):
        probs.append(f"kinds {sorted(r['kinds'])} != pages {sorted(NEXT_PAGES)}")
    for k, views in NEXT_PAGES.items():
        for v in views:
            if f'nextSteps("{k}"' not in defn(c.js, v):
                probs.append(f"{v} does not show nextSteps('{k}')")
    if r["aide"]["href"] != "#/info/aide":
        probs.append("the last step is not the help page")
    for k, h in r["html"].items():
        if "<h2" not in h or "Et maintenant ?" not in h:
            probs.append(f"{k}: no heading")
        hrefs = re.findall(r'href="([^"]*)"', h)
        if not hrefs or hrefs[-1] != "#/info/aide":
            probs.append(f"{k}: does not end with the help page")
        for u in hrefs:
            if not (u.startswith("https://") or (u.startswith("#/") and u[2:].split("/")[0] in r["routes"])):
                probs.append(f"{k}: link {u} is neither an app route nor https")
    for k, items in r["items"].items():
        for x in items + [r["aide"]]:
            if re.search(r"\d", x["text"]):
                probs.append(f"{k}: a figure in a step «{x['text']}»")
    return not probs, f"{len(r['kinds'])} kinds; {probs[:4]}"


@check("LA5 help page: official hosts, the services' own numbers, no hours, reachable from every menu")
def la5(c: Ctx):
    from urllib.parse import urlsplit
    from suptracker import cache as CA
    probs = []
    AI = c.AI
    if set(AI.OFFICIAL_HOSTS) != HOSTS:
        probs.append(f"official hosts {AI.OFFICIAL_HOSTS} != {sorted(HOSTS)}")
    for s in AI.SERVICES:
        if s["url"]:
            u = urlsplit(s["url"])
            if u.scheme != "https" or u.netloc not in HOSTS:
                probs.append(f"{s['id']}: {s['url']} is not an official https address")
        if s["tel"]:
            shown, dial = s["tel"]
            if PHONES.get(s["id"]) != shown:
                probs.append(f"{s['id']}: phone {shown} != {PHONES.get(s['id'])}")
            dd = re.sub(r"\D", "", dial)
            sd = re.sub(r"\D", "", shown)
            if not (dd == sd or (dial.startswith("+33") and dd[2:] == sd.lstrip("0"))):
                probs.append(f"{s['id']}: tel:{dial} does not dial {shown}")
    if set(PHONES) - {s["id"] for s in AI.SERVICES if s["tel"]}:
        probs.append("a service lost its phone number")
    page = AI.page()
    txt = page_text(page)
    if HOURS.search(txt):
        probs.append(f"opening hours printed: {HOURS.search(txt).group(0)}")
    for need in (AI.CHECKED, "n'est lié à aucun", "gratuit", "psychologue de l'Éducation nationale", "CIO"):
        if need not in txt:
            probs.append(f"the page does not say «{need}»")
    for s in AI.SERVICES:
        if s["tel"] and f'href="tel:{s["tel"][1]}"' not in page:
            probs.append(f"{s['id']}: no tel link")
    if "aide" not in c.LG.SLUGS or "aide" not in dict(c.LG.FOOTER) or c.LG.page("aide") is None:
        probs.append("help page not registered in legal.py (slug, footer)")
    if c.html.count('href="#/info/aide"') < 2:
        probs.append("help page not in both menus of index.html")
    if '"aide"' not in defn(c.js, "INFO_SLUGS") or "|aide)" not in defn(c.js, "pathRoute"):
        probs.append("help page not opened by the app (INFO_SLUGS, pathRoute)")
    pol = CA.policy("/aide") if hasattr(CA, "policy") else None
    if pol is not None and "PAGE" not in str(pol).upper() and "public" not in str(pol).lower():
        probs.append(f"cache policy of /aide: {pol}")
    return not probs, f"{len(AI.SERVICES)} services; {probs[:4]}"


@check(f"LA6 readability: sentences of at most {MAX_WORDS} words and Kandel-Moles >= {MIN_KM:g} in the short texts")
def la6(c: Ctx):
    texts = short_texts(c)
    long_ = [(k, len(words(s)), s[:60]) for k, t in texts.items() for s in sentences(t) if len(words(s)) > MAX_WORDS]
    km = {"glossaire": kandel_moles(" ".join(d for _t, d in c.glossary.values())), "aide": kandel_moles(texts["aide"])}
    low = {k: round(v, 1) for k, v in km.items() if v < MIN_KM}
    meth = [(k, len(words(s))) for k, t in c.methodology.items() for s in sentences(t) if len(words(s)) > MAX_WORDS_METHOD]
    ok = not long_ and not low and not meth and len(texts) > 40
    return ok, (f"{len(texts)} texts; Kandel-Moles {({k: round(v, 1) for k, v in km.items()})}; long sentences {long_[:3]}; "
                f"low {low}; method sentences > {MAX_WORDS_METHOD} words {meth[:3]}")


@check("LA7 browser: next steps and zone legend on the phone pages, help page, no horizontal scroll, no JS error")
def la7(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    node = shutil.which("node")
    if not node:
        return True, "node not installed"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp}
    if c.db:
        env["SUPTRACKER_DB"] = str(c.db)
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
        from suptracker import config
        db = c.db or config.DB_PATH
        with duckdb.connect(str(db), read_only=True) as con:
            cods = [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session)
                    FROM core.formation_year) AND taux_acces_ens IS NOT NULL ORDER BY acc_tot DESC NULLS LAST LIMIT 2""").fetchall()]
        script = Path(tmp) / "la7.js"
        script.write_text(BROWSER_JS.replace("__PORT__", str(port)).replace("__CODS__", json.dumps(cods))
                          .replace("__N__", str(len(c.AI.SERVICES))))
        r = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=600)
        out = (r.stdout or "").strip().splitlines()
        res = json.loads(out[-1]) if out and out[-1].startswith("{") else {"problems": [r.stderr[-400:]]}
    finally:
        srv.terminate()
    return not res["problems"], f"pages {res.get('seen')}; problems {res['problems'][:5]}"


BROWSER_JS = r"""
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch(); const problems = []; const seen = {};
  const ctx = await b.newContext({ ...devices['Pixel 5'] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push('js: ' + e.message));
  const base = 'http://127.0.0.1:__PORT__', cods = __CODS__;
  await page.goto(base + '/');
  await page.evaluate((cods) => {
    localStorage.setItem('profile', JSON.stringify({ statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: '' }));
    localStorage.setItem('voeux', JSON.stringify(cods));
  }, cods);
  for (const [name, hash, want] of [['fiche', '#/f/' + cods[0], { next: 1, legend: 1 }], ['voeux', '#/voeux', { next: 1, legend: 1 }],
                                    ['aide', '#/info/aide', { services: __N__ }]]) {
    await page.goto(base + '/' + hash);
    await page.waitForSelector(want.services ? '.aide-service' : '.next-steps', { timeout: 60000 }).catch(() => problems.push(name + ': nothing rendered'));
    await page.waitForTimeout(800);
    const r = await page.evaluate(() => ({ next: document.querySelectorAll('.next-steps').length, legend: document.querySelectorAll('.zone-legend').length,
      services: document.querySelectorAll('.aide-service').length, tel: document.querySelectorAll('a[href^="tel:"]').length,
      h1: document.querySelectorAll('h1').length, wide: document.documentElement.scrollWidth > window.innerWidth + 1,
      lastNext: (() => { const a = document.querySelectorAll('.next-steps a'); return a.length ? a[a.length - 1].getAttribute('href') : null; })() }));
    seen[name] = r;
    if (r.h1 !== 1) problems.push(`${name}: ${r.h1} h1`);
    if (r.wide) problems.push(`${name}: horizontal scroll`);
    for (const k of Object.keys(want)) if (r[k] !== want[k]) problems.push(`${name}: ${k} = ${r[k]}, expected ${want[k]}`);
    if (want.next && r.lastNext !== '#/info/aide') problems.push(`${name}: last step ${r.lastNext}`);
    if (want.services && r.tel < 3) problems.push(`${name}: ${r.tel} phone links`);
    if (name === 'fiche') {
      await page.click('.zone-legend summary');
      const open = await page.evaluate(() => document.querySelector('.zone-legend').open && document.querySelectorAll('.zone-legend li').length);
      if (open !== 4) problems.push('fiche: zone legend does not open on four zones');
    }
  }
  await b.close();
  console.log(JSON.stringify({ problems, seen }));
})();
"""


@check("LA8 tokenizer = a full JavaScript parser (when installed); mutation test: every seeded bug is caught")
def la8(c: Ctx):
    notes = []
    node = shutil.which("node")
    acorn = node and subprocess.run([node, "-e", "require('acorn')"], capture_output=True).returncode == 0
    if acorn:
        prog = r"""const acorn = require('acorn'); const src = require('fs').readFileSync(0, 'utf8'); const out = [];
const walk = (n) => { if (!n || typeof n.type !== 'string') return; if (n.type === 'Literal' && typeof n.value === 'string') out.push(n.value);
  if (n.type === 'TemplateElement') out.push(n.value.cooked);
  for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v.type === 'string') walk(v); } };
walk(acorn.parse(src, { ecmaVersion: 2022 })); process.stdout.write(JSON.stringify(out));"""
        r = subprocess.run([node, "-e", prog], input=c.js, capture_output=True, text=True, timeout=60)
        from collections import Counter
        same = Counter(json.loads(r.stdout)) == Counter(t for _o, t in jstext.strings(c.js))
        if not same:
            return False, "the tokenizer does not read the same strings as acorn"
        notes.append("tokenizer = acorn")
    else:
        notes.append("acorn not installed: tokenizer check skipped")
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in ("LA1", "LA2", "LA3", "LA4", "LA5", "LA6") and not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = mutants(c)
    return not missed, f"{'; '.join(notes)}; mutants caught {caught}/{caught + len(missed)}; missed {missed}"


def mutants(base: Ctx) -> tuple[int, list[str]]:
    import copy
    AI = base.AI
    caught, missed = 0, []

    def js_mut(name, old, new, checks):
        nonlocal caught
        c = copy.copy(base)
        if old not in base.js:
            missed.append(f"{name} (anchor lost)")
            return
        c.js = base.js.replace(old, new, 1)
        bad = [fn for fn in CHECKS if fn.check_name.split()[0] in checks and not fn(c)[0]]
        (missed.append(name) if not bad else None)
        caught += bool(bad)

    def ctx_mut(name, mutate, checks, restore=None):
        nonlocal caught
        c = copy.copy(base)
        c.glossary, c.methodology = dict(base.glossary), dict(base.methodology)
        mutate(c)
        try:
            bad = [fn for fn in CHECKS if fn.check_name.split()[0] in checks and not fn(c)[0]]
        finally:
            if restore:
                restore()
        (missed.append(name) if not bad else None)
        caught += bool(bad)

    js_mut("a raw estimation badge", "${pct1(est.taux)}</strong> ${estimTag()}", '${pct1(est.taux)}</strong> <span class="estim">estimation</span>', {"LA2"})
    js_mut("estimTag without its explanation", 'const tipBtn = plain ? "" : `<button', 'const tipBtn = true ? "" : `<button', {"LA2"})
    js_mut("explanation says nothing of officialness", "Ce n'est pas un chiffre officiel, ni une chance d'admission.", "C'est un repère.", {"LA2"})
    js_mut("a renderer drops the label", '${estimTag(`${fmt(v.semblable.n_rapports)} rapports de formations semblables`, true)}',
           '<div class="estim">${fmt(v.semblable.n_rapports)} rapports</div>', {"LA2"})
    js_mut("jargon back on the formation page", "Vos deux spécialités dans cette formation", "Votre doublette dans cette formation", {"LA1"})
    js_mut("'en position de' back", "qui ont été classés assez haut pour recevoir une proposition en phase principale : le taux d'accès",
           "qui ont été en position de recevoir une proposition en phase principale : le taux d'accès", {"LA1"})
    js_mut("'votre ligne' back in a header", "Votre bac dans le rapport du jury (cette formation)", "Votre ligne dans le rapport du jury (cette formation)", {"LA1"})
    ctx_mut("jargon in the glossary", lambda c: c.glossary.__setitem__("x", ("Votre ligne", "La ligne du rapport.")), {"LA1"})
    ctx_mut("jargon in a method text", lambda c: c.methodology.__setitem__("x", "Part de la doublette parmi les admis."), {"LA1"})
    js_mut("a hard-coded zone threshold", "taux d'accès d'au moins ${R.securite_access} %", "taux d'accès d'au moins 60 %", {"LA3"})
    js_mut("zone texts off by the cdf", "${sur100(R.ambitieux_cdf)} admis sur 100", "${sur100(R.securite_cdf)} admis sur 100", {"LA3"})
    js_mut("legend dropped from Mes vœux", "    ${zoneLegend()}\n", "\n", {"LA3"})
    js_mut("zone pill without its explanation", '"background:${zz.color}"${h ? ` title="${esc(h)}"` : ""}>', '"background:${zz.color}">', {"LA3"})
    js_mut("legend without 'jamais une chance'", "ce n'est jamais une chance d'admission.", "c'est un repère.", {"LA3"})
    js_mut("next steps without a person", "const items = [...(extra || []), ...(NEXT_STEPS[kind] || []), AIDE_STEP];",
           "const items = [...(extra || []), ...(NEXT_STEPS[kind] || [])];", {"LA4"})
    js_mut("job page without next steps", '${nextSteps("metier", ', '${("metier", ', {"LA4"})
    js_mut("a step to an unknown route", '{ href: "#/calendrier", text: "Noter les dates de Parcoursup" }],\n  metier',
           '{ href: "#/conseils", text: "Noter les dates de Parcoursup" }],\n  metier', {"LA4"})
    js_mut("a figure in a step", "avec au moins un vœu de sécurité\" },\n    { href: \"#/carte\"", "avec 3 vœux de sécurité\" },\n    { href: \"#/carte\"", {"LA4"})
    js_mut("help page not opened by the app", '"accessibilite", "aide"];', '"accessibilite"];', {"LA5"})

    orig = AI.SERVICES

    def services(fn):
        def go(_c):
            AI.SERVICES = tuple(fn(dict(s)) for s in orig)
        return go

    def restore():
        AI.SERVICES = orig
    ctx_mut("a wrong phone number", services(lambda s: {**s, "tel": ("0 800 400 007", "0800400007")} if s["id"] == "parcoursup" else s), {"LA5"}, restore)
    ctx_mut("a tel link dialling another number", services(lambda s: {**s, "tel": (s["tel"][0], "+33177771226")} if s["id"] == "moel" else s), {"LA5"}, restore)
    ctx_mut("a non-official address", services(lambda s: {**s, "url": "https://www.orientation-conseil.example/"} if s["id"] == "cio" else s), {"LA5"}, restore)
    ctx_mut("opening hours printed", services(lambda s: {**s, "comment": s["comment"] + " Ouvert de 10 h à 19 h."} if s["id"] == "moel" else s), {"LA5"}, restore)
    ctx_mut("help link removed from the menus", lambda c: setattr(c, "html", c.html.replace('<a href="#/info/aide" data-tab="aide">Se faire aider</a>', "", 1)), {"LA5"})
    ctx_mut("a 40-word glossary sentence", lambda c: c.glossary.__setitem__("x", ("Test", " ".join(["mot"] * 40) + ".")), {"LA6"})
    ctx_mut("a long method sentence", lambda c: c.methodology.__setitem__("x", " ".join(["mot"] * 80) + "."), {"LA6"})
    return caught, missed


def run(db: Path | None = None, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(browser=browser, real=real, db=db)
    out = []
    for fn in CHECKS:
        name = fn.check_name.split()[0]
        if checks and name not in checks:
            continue
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="also the browser check on the committed warehouse")
    ap.add_argument("--browser", action="store_true", help="the browser check (LA7)")
    ap.add_argument("--db", type=Path)
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real, browser=a.browser)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
