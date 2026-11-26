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
  LA9 raw codes and internal labels (audit PR 3, 2026-11-23): no column abbreviation (« (PP) », « (PC) »), internal word
      (« cohorte finale », « Atypique / prérequis non alignés », « Part de destination », « Reconnu »), column name
      (« cod_aff_form »), « an(s) » or « n<10 » in the page's visible strings or the server's labels; the specialty codes are
      printed by their short names (SPE_SHORT = journey.SPECIALTY_SHORT, run in Node); a report's printed bucket and STMG
      labels are made readable by ONE helper (rpLabel, run in Node) at every place a report label is printed; the specialties
      of the profile are never printed as codes.
  LA10 browser (--browser / --real): the TEXT a student reads, every folded block and tab opened, on the real pages (home,
      profile, Où je me situe, Mes vœux, formation pages with reports of bac général and STMG, a search, a job), for a bac
      général and a bac techno profile: none of LA9's words, no « doublette » outside its explanation, no specialty code.
"""
from __future__ import annotations

import argparse
import copy
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
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []

BANNED = re.compile(r"\bdoublettes?\b|\ben position de\b|\bvotre ligne\b|\bvos lignes\b", re.I)
ALLOWED = re.compile(r"(?:on dit aussi |\()« doublette »", re.I)
PY_TEXT = ["voeux.py", "planb.py", "journey.py", "reorientation.py", "voies.py", "metiers.py", "licence_master.py", "insertion.py",
           "passerelles.py", "success.py", "poursuite.py", "cereq.py", "onisep.py", "evidence.py", "prevision.py", "calendrier.py",
           "seo.py", "semblables.py", "rapports.py", "carte.py", "filtres.py", "admis.py", "appel.py", "selectivite.py", "observatoire.py", "tension.py"]
CODE_STRING = re.compile(r"\b(?:SELECT|CREATE|INSERT|FROM|WHERE|JOIN)\b|^[\w.:/-]*$")
# every renderer of a computed figure, with its number of computed figures (each one labelled by estimTag)
ESTIMATE_RENDERERS = {"doubletteCard": 3, "cartePosFigure": 1, "PR_SOURCE": 2, "stage1Matrix": 1, "vxVoieFigure": 1,
                      "viewParcours": 1, "dblFigure": 2, "reoCell": 1, "tensionCard": 1, "distanceText": 1, "apprentiInsertionCard": 1, "aidesCard": 1}
NEXT_PAGES = {"formation": ("viewFormation",), "parcours": ("viewParcours",), "voeux": ("viewVoeux", "viewVoeuxReo"),
              "reorientation": ("viewReorientation",), "metier": ("viewMetier",), "premiere": ("viewPremiere",),
              "observatoire": ("viewObservatoire",)}
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
    z = node_eval(c.js, ["ZONE_RULES", "zoneHelp", "ZONE_NOT_CHANCE", "ZONE_AXIS", "ESTIM_DEF", "AIDE_STEP", "NEXT_STEPS"],
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
    r = node_eval(c.js, ["ZONE_RULES", "zoneHelp", "ZONE_NOT_CHANCE", "ZONE_AXIS", "ZONES", "zoneShape", "ZONE_FILLED", "zoneMark", "isLargeShown", "zonePillHtml",
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
    if '"aide"' not in defn(c.js, "INFO_SLUGS") or not re.search(r"\|aide[|)]", defn(c.js, "pathRoute")):
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
      h1: document.querySelectorAll('h1').length, wide: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,   // innerWidth grows on an emulated phone
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
      // the four zones, then the « sécurité large » nuance (owner, 2026-11-19)
      if (open !== 5) problems.push(`fiche: zone legend opens on ${open} items, expected the four zones and « sécurité large »`);
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
    acorn = node and nodefile.run([node, "-e", "require('acorn')"], capture_output=True).returncode == 0
    if acorn:
        prog = r"""const acorn = require('acorn'); const src = require('fs').readFileSync(0, 'utf8'); const out = [];
const walk = (n) => { if (!n || typeof n.type !== 'string') return; if (n.type === 'Literal' && typeof n.value === 'string') out.push(n.value);
  if (n.type === 'TemplateElement') out.push(n.value.cooked);
  for (const k in n) { const v = n[k]; if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v.type === 'string') walk(v); } };
walk(acorn.parse(src, { ecmaVersion: 2022 })); process.stdout.write(JSON.stringify(out));"""
        r = nodefile.run([node, "-e", prog], input=c.js, capture_output=True, text=True, timeout=60)
        from collections import Counter
        same = Counter(json.loads(r.stdout)) == Counter(t for _o, t in jstext.strings(c.js))
        if not same:
            return False, "the tokenizer does not read the same strings as acorn"
        notes.append("tokenizer = acorn")
    else:
        notes.append("acorn not installed: tokenizer check skipped")
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in ("LA1", "LA2", "LA3", "LA4", "LA5", "LA6", "LA9") and not fn(c)[0]]
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
    js_mut("'votre ligne' back in a header", "Pour votre bac (cette formation)", "Votre ligne (cette formation)", {"LA1"})
    ctx_mut("jargon in the glossary", lambda c: c.glossary.__setitem__("x", ("Votre ligne", "La ligne du rapport.")), {"LA1"})
    ctx_mut("jargon in a method text", lambda c: c.methodology.__setitem__("x", "Part de la doublette parmi les admis."), {"LA1"})
    js_mut("(PP) back in a header", '["Classés (phase principale)",', '["Classés (PP)",', {"LA9"})
    js_mut("cohorte finale back", "Admis (toute la campagne)", "Admis (cohorte finale)", {"LA9"})
    js_mut("column name in the history table", "<th>Code Parcoursup</th>", "<th>cod_aff_form</th>", {"LA9"})
    js_mut("an(s) back", 'spécialités · ${f.years} campagne${f.years > 1 ? "s" : ""}', "spécialités · ${f.years} an(s)", {"LA9"})
    js_mut("internal gate name back", 'label: "Peu courant avec vos spécialités"', 'label: "Atypique / prérequis non alignés"', {"LA9"})
    js_mut("search chip says Reconnu", 'sigle: "Mot compris"', 'sigle: "Reconnu"', {"LA9"})
    js_mut("route names through the report-label helper", "<tr><td>${esc(v.libelle)}</td>", "<tr><td>${esc(rpLabel(v.libelle))}</td>", {"LA9"})
    js_mut("a report row printed raw", "<td>${esc(rpLabel(x.libelle))}", "<td>${esc(x.libelle)}", {"LA9"})
    js_mut("Autres doublettes left as printed", '.replace(/^Autres doublettes$/i, "Autres paires de spécialités")', "", {"LA9"})
    js_mut("STMG label left raw", '.replace(/Msgn\\/\\s*([^&·]+?)(?=\\s*(?:&|·|$))/g, "Management ($1)")', "", {"LA9"})
    js_mut("a specialty printed as its code", '${esc(speName(p.spe1))} + ${esc(speName(p.spe2))}`', '${esc(p.spe1)} + ${esc(p.spe2)}`', {"LA9"})
    js_mut("a short name drifts from the vocabulary", '"MATHS": "Mathématiques", "PC"', '"MATHS": "Maths", "PC"', {"LA9"})
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
    js_mut("help page not opened by the app", '"accessibilite", "aide", "nos-chiffres", "robustesse"];', '"accessibilite", "nos-chiffres", "robustesse"];', {"LA5"})

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


# ---------------------------------------------------------------- LA9 / LA10 (audit PR 3)
RAW = re.compile(r"\((?:PP|PC)\)|cohorte finale|cod_aff_form|\ban\(s\)|n&lt;10|\bn<10\b|Atypique|Part de destination|prérequis non alignés|Msgn/", re.I)
REPORT_PRINTS = ("<td>${esc(rpLabel(x.libelle))}", "<strong>${esc(rpLabel(m.libelle))}</strong>",
                 "ligne « ${esc(rpLabel(mineV.libelle))} »", "ligne « ${esc(rpLabel(r.libelle))} »", "`<mark>${esc(rpLabel(x))}</mark>` : esc(rpLabel(x))",
                 "${esc(rpLabel(lab))} (${fmt(c)})")
# SupCompass's own labels that are NOT report lines: rpLabel never wraps them (CI, 2026-11-24: the BTS route comparison's
# route names went through it by mistake).
OWN_PRINTS = ("${n.voies.map((v) => `<tr><td>${esc(v.libelle)}</td>",)
SPE_PRINTS = ("${esc(speName(p.spe1))} + ${esc(speName(p.spe2))}", 'esc(s1.doublette.split("+").map(speName).join(" + "))')


def node_json(prog: str):
    node = shutil.which("node")
    if not node:
        return None
    r = nodefile.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return json.loads(r.stdout)


@check("LA9 no raw code or internal label: column abbreviations, internal words, codes; readable report labels and specialty names")
def la9(c: Ctx):
    bad = []
    hits = [t[:80] for t in js_visible(c.js) if RAW.search(t)]
    if hits:
        bad.append(("page strings", hits[:3]))
    from suptracker import indicators as IND
    from suptracker import schema as SC
    labels = [f.label for f in SC.VOEUX_FIELDS if getattr(f, "label", None)] + [v[2] for v in IND.__dict__.get("INDICATORS", {}).values()
                                                                             if isinstance(v, tuple) and len(v) > 2 and isinstance(v[2], str)]
    srv = [x for x in labels if RAW.search(x)]
    if srv:
        bad.append(("server labels", srv[:3]))
    if re.search(r'sigle: "Reconnu"', c.js):
        bad.append("the search's word chip says « Reconnu »")
    miss = [x for x in REPORT_PRINTS + SPE_PRINTS if x not in c.js]
    if miss:
        bad.append(("a print without its helper", miss[:3]))
    own = [x for x in OWN_PRINTS if x not in c.js]
    if own:
        bad.append(("our own label put through the report-label helper", own))
    if re.search(r"esc\((?:p|prof)\.spe[12]", c.js):
        bad.append("a specialty code printed raw")
    from suptracker import journey as J
    names = ["SPE_SHORT", "speName", "rpLabel"]
    prog = "\n".join(defn(c.js, n) for n in names) + """
process.stdout.write(JSON.stringify({ short: SPE_SHORT, a: rpLabel("Autres doublettes"), s: rpLabel("Autres spécialités"),
  m: rpLabel("Msgn/ Mercatique & Droit et Economie"), l: rpLabel("Série STMG : Droit et Economie · Msgn/ Gestion et Finance · Msgn/ Mercatique"),
  k: rpLabel("Mathématiques Spécialité & Sciences Economiques et Sociales Spécialité"), x: speName("MATHS"), u: speName("ZZZ") }));"""
    try:
        o = node_json(prog)
    except Exception as e:  # noqa: BLE001
        return False, f"rpLabel / SPE_SHORT do not run: {e}"
    if o is not None:
        want = {"a": "Autres paires de spécialités", "s": "Autres spécialités", "m": "Management (Mercatique) & Droit et Economie",
                "l": "Série STMG : Droit et Economie · Management (Gestion et Finance) · Management (Mercatique)",
                "k": "Mathématiques Spécialité & Sciences Economiques et Sociales Spécialité", "x": "Mathématiques", "u": "ZZZ"}
        diff = {k: (o[k], v) for k, v in want.items() if o[k] != v}
        if diff:
            bad.append(("readable labels", diff))
        if o["short"] != dict(J.SPECIALTY_SHORT):
            bad.append(("SPE_SHORT differs from the vocabulary", {k: (o["short"].get(k), v) for k, v in J.SPECIALTY_SHORT.items() if o["short"].get(k) != v}))
    return not bad, f"{len(bad)} problems {bad[:4]}"


SCAN_JS = r"""
const { chromium, devices } = require('playwright');
const [base, cods] = [process.argv[2], JSON.parse(process.argv[3])];
const RAW = /\((?:PP|PC)\)|cohorte finale|cod_aff_form|\ban\(s\)|\bn<10\b|Atypique|Part de destination|prérequis non alignés|Msgn\/|Reconnu : /i;
const CODE = /\b(?:MATHS|BIOECO)\b/;   // codes the vocabulary renames (EPPCS, SES, SVT... ARE their short names)
const DBL = /\bdoublettes?\b/i, ALLOWED = /(?:on dit aussi |\()« doublette »/i;
(async () => {
  const b = await chromium.launch(); const hits = []; const errs = []; let n = 0;
  const profs = { bg: { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: '' },
    bt: { statut: 'terminale', serie: 'bt', mention: 'sansmention', voie: null } };
  const pages = ['#/', '#/profil', '#/parcours', '#/voeux', '#/guide', ...cods.map((c) => '#/f/' + c), '#/metiers', '#/calendrier', '#/premiere', '#/compare'];
  for (const [pk, prof] of Object.entries(profs)) {
    const ctx = await b.newContext({ ...devices['Pixel 5'] });
    await ctx.addInitScript(([p, c]) => { localStorage.setItem('profile', JSON.stringify(p)); localStorage.setItem('voeux', JSON.stringify(c));
      localStorage.setItem('compare', JSON.stringify(c.slice(0, 2))); }, [prof, cods]);
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    for (const u of pages) {
      await p.goto(base + '/' + u); await p.waitForTimeout(3500);
      await p.evaluate(() => { document.querySelectorAll('details').forEach((d) => { d.open = true; });
        document.querySelectorAll('[role="tabpanel"]').forEach((t) => { t.hidden = false; t.style.display = 'block'; }); });
      const t = await p.evaluate(() => document.querySelector('#view').innerText); n += 1;
      for (const line of t.split('\n')) {
        const l = line.replace(ALLOWED, ' ');
        if (RAW.test(l) || CODE.test(l) || DBL.test(l)) hits.push(`${pk} ${u}: ${line.trim().slice(0, 110)}`);
      }
    }
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ n, hits: [...new Set(hits)], errs })); await b.close();
})();
"""


@check("LA10 browser: the text a student reads (folded blocks and tabs opened) carries no raw code, internal label or jargon")
def la10(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    node = shutil.which("node")
    if not node or nodefile.run([node, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    import duckdb
    from suptracker import config
    db = c.db or config.DB_PATH
    with duckdb.connect(str(db), read_only=True) as con:
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        pick = lambda sql: [r[0] for r in con.execute(sql, [latest]).fetchall()]  # noqa: E731
        cods = pick("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = ? AND bac = 'bt' AND libelle ILIKE 'Msgn%'
                       ORDER BY 1 LIMIT 1""") + pick("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = ? AND bac = 'bg'
                       AND autres ORDER BY 1 LIMIT 2""")
    if not cods:
        return False, "no formation with a report to read"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        script = Path(tmp) / "la10.js"
        script.write_text(SCAN_JS)
        r = subprocess.run([node, str(script), f"http://127.0.0.1:{port}", json.dumps(cods)], capture_output=True, text=True, timeout=900)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    o = json.loads(r.stdout)
    return o["n"] > 20 and not o["hits"] and not o["errs"], f"{o['n']} pages read; {len(o['hits'])} hits {o['hits'][:5]}; JS errors {o['errs'][:2]}"


# ---------------------------------------------------------------- LA11-LA13: the words the testers quoted (lot 1, PR 10)
# what two audits' testers (2026-11-23, 2026-11-25) could not read; « néo-bachelier » only as the quoted official word
TESTER = [
    ("néo-bachelier", re.compile(r"néo-bachelier(?! »)", re.I)),
    ("SIES without « ministère »", re.compile(r"\bSIES\b")),
    ("Pas de conclusion", re.compile(r"\bPas de conclusion\b", re.I)),
    ("note OIT", re.compile(r"\bnote OIT\b")),
    ("Part des classés appelés", re.compile(r"Part des classés appelés")),
    ("Part des terminales générales parmi", re.compile(r"Part des terminales générales parmi")),
    ("taux_acces_ens =", re.compile(r"taux_acces_ens =")),
    ("Indicateurs officiels SIES", re.compile(r"Indicateurs officiels SIES")),
]
JS_TESTER = [("×N (a ratio with a times sign)", re.compile(r">×\$\{fmt\(")),
             ("an académie printed without acadLabel", re.compile(r"esc\((?:(?:\w+\.)+(?:academie|acad_mies)|home|acad)\)")),
             ("a report label printed raw in L'essentiel", re.compile(r"ligne « \$\{v\.libelle\} »|: x\.libelle,"))]


def tester_hits(texts, allow_sies=True):
    out = []
    for t in texts:
        for name, rx in TESTER:
            if rx.search(t) and not (name.startswith("SIES") and allow_sies and "ministère" in t):
                out.append((name, t[:90]))
    return out


@check("LA11 the words the testers quoted (néo-bacheliers, SIES, Pas de conclusion, codes, raw labels) are gone from page and server texts")
def la11(c: Ctx):
    bad = tester_hits(js_visible(c.js))
    for name, rx in JS_TESTER:
        if rx.search(c.js):
            bad.append((name, rx.search(c.js).group(0)[:60]))
    srv = []
    for f in PY_TEXT + ["api.py", "glossary.py", "schema.py"]:
        for t in py_visible(ROOT / "suptracker" / f):
            srv += [(f, n, x) for n, x in tester_hits([t]) if n.startswith("néo")]
    if srv:
        bad.append(("server texts", srv[:3]))
    g = c.glossary.get("neo_bachelier")
    if not g or "néo" in g[0].lower() or "« néo-bachelier »" not in g[1]:
        bad.append(("glossary: « Nouveau bachelier », the official word quoted", g))
    prog = defn(c.js, "ACAD_LABEL") + "\n" + defn(c.js, "acadLabel") + """
process.stdout.write(JSON.stringify([acadLabel("Besancon"), acadLabel("Etranger"), acadLabel("Lyon"), acadLabel(null), acadLabel("")]));"""
    try:
        o = node_json(prog)
    except Exception as e:  # noqa: BLE001
        o, bad = None, bad + [("acadLabel does not run", str(e)[:80])]
    if o is not None and o != ["Besançon", "Étranger", "Lyon", None, ""]:
        bad.append(("acadLabel", o))
    if 'nodefile.run([node, "-e", SCAN2_JS' not in Path(__file__).read_text():         # Codex, PR #121: require from the repository
        bad.append("LA12's browser program is not run through nodefile")
    pr = defn(c.js, "profileRate")
    if pr.count("rpLabel(") < 3:
        bad.append("profileRate prints a report label without rpLabel")
    return not bad, f"{len(bad)} problems {bad[:4]}"


SCAN2_JS = r"""
const { chromium, devices } = require('playwright');
const [base, cods] = [process.argv[1], JSON.parse(process.argv[2])];      // run through nodefile: node -e's argv
const BAN = /\bISCO\b|FAP-20\d\d|O\*NET(?! \(minist)|\bθ\b|néo-bachelier(?! »)|Pas de conclusion|\bBesancon\b|\bEtranger\b|×\s?\d[\d,]*(?![\d,]|\s*m²)|taux_acces_ens|series_eq|stage1|Msgn\/|\bSIES\b/i;
(async () => {
  const b = await chromium.launch(); const hits = []; const errs = []; let n = 0;
  const profs = { bg: { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: 'Besancon' },
    bt: { statut: 'terminale', serie: 'bt', mention: 'sansmention', voie: 'stmg_merc', voie_label: 'STMG Mercatique' },
    reo: { statut: 'reorientation', academie: 'Etranger' } };
  const metiers = await (await fetch(base + '/api/metiers')).json();
  const iid = metiers.fields.indexOf('id'); const ids = metiers.rows.map((r) => r[iid]).filter(Boolean);
  const jobs = [ids[0], ids[Math.floor(ids.length / 2)], ids[ids.length - 1]];
  const pages = ['#/', '#/profil', '#/parcours', '#/voeux', '#/qualite', '#/observatoire', '#/reorientation', ...cods.map((c) => '#/f/' + c), ...jobs.map((j) => '#/metier/' + j)];
  for (const [pk, prof] of Object.entries(profs)) {
    const ctx = await b.newContext({ ...devices['Pixel 5'] });
    await ctx.addInitScript(([p, c]) => { localStorage.setItem('profile', JSON.stringify(p)); localStorage.setItem('voeux', JSON.stringify(c)); }, [prof, cods]);
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    for (const u of pages) {
      await p.goto(base + '/' + u); await p.waitForTimeout(3500);
      const t = await p.evaluate(() => { const v = document.querySelector('#view').cloneNode(true);
        v.querySelectorAll('details.more-card').forEach((d) => d.remove());          // the folded detail of a calculation may keep its codes
        v.querySelectorAll('details').forEach((d) => { d.open = true; });
        v.querySelectorAll('[role="tabpanel"]').forEach((x) => { x.hidden = false; });
        document.body.appendChild(v); v.style.position = 'absolute'; v.style.left = '-99999px';
        const txt = v.innerText; v.remove(); return txt; });
      n += 1;
      for (const line of t.split('\n')) if (BAN.test(line) && !(/\bSIES\b/.test(line) && /minist/i.test(line) && !BAN.test(line.replace(/\bSIES\b/g, '')))) { const m = line.match(BAN); const k = Math.max(0, (m ? m.index : 0) - 50); hits.push(`${pk} ${u}: [${m ? m[0] : ''}] ${line.trim().slice(k, k + 130)}`); }
    }
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ n, hits: [...new Set(hits)], errs })); await b.close();
})();
"""


@check("LA12 browser: the pages the testers read (bac techno with its route, reorientation, job pages, quality page) carry none of their quoted words outside a folded calculation")
def la12(c: Ctx):
    if not (c.browser or c.real):
        return True, "skipped (--browser)"
    node = shutil.which("node")
    if not node or nodefile.run([node, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    import duckdb
    from suptracker import config
    db = c.db or config.DB_PATH
    with duckdb.connect(str(db), read_only=True) as con:
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        cods = [r[0] for r in con.execute("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = ? AND bac = 'bt'
            AND libelle ILIKE 'Msgn/ Mercatique%' ORDER BY 1 LIMIT 1""", [latest]).fetchall()]
        cods += [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND acad_mies IN ('Besancon', 'Etranger')
            ORDER BY cod_aff_form LIMIT 2""", [latest]).fetchall()]
    if not cods:
        return False, "no formation to read"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        # Codex (PR #121): through nodefile, from the repository (require('playwright') from a local node_modules too)
        r = nodefile.run([node, "-e", SCAN2_JS, f"http://127.0.0.1:{port}", json.dumps(cods)], capture_output=True, text=True, timeout=1200, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    o = json.loads(r.stdout)
    return o["n"] > 30 and not o["hits"] and not o["errs"], f"{o['n']} pages read; {len(o['hits'])} hits {o['hits'][:6]}; JS errors {o['errs'][:2]}"


TESTER_MUTANTS = [
    ("the raw report label back in L'essentiel", "`votre bac, ligne « ${rpLabel(v.libelle)} »`", "`votre bac, ligne « ${v.libelle} »`"),
    ("« Pas de conclusion » back", 'incertain: "Prévisions divergentes" };', 'incertain: "Pas de conclusion" };'),
    ("an académie printed raw", "${esc(acadLabel(r.acad_mies))}", "${esc(r.acad_mies)}"),
    ("the reorientation home académie printed raw", "Seulement l'académie de ${esc(acadLabel(home))}", "Seulement l'académie de ${esc(home)}"),
    ("acadLabel forgets Besançon", 'const ACAD_LABEL = { Besancon: "Besançon", Etranger: "Étranger" };', 'const ACAD_LABEL = { Etranger: "Étranger" };'),
    ("néo-bacheliers back in a sentence", "des admis nouveaux bacheliers", "des admis néo-bacheliers"),
    ("the SIES heading back", "Chiffres officiels du ministère · ", "Indicateurs officiels SIES · "),
    ("the times sign back", '${fmt(f.lift, 2)} fois la moyenne</td>', '×${fmt(f.lift, 2)}</td>'),
    ("a quality-page code back", "<tr><td>Taux d'accès = fichier officiel brut</td>", "<tr><td>taux_acces_ens = fichier SIES brut</td>"),
]


@check("LA13 mutation test: every seeded return of a word the testers quoted is caught by LA11")
def la13(c: Ctx):
    ok0, d0 = la11(c)
    if not ok0:
        return False, f"the unmutated code fails LA11: {d0}"
    missed, caught = [], 0
    for name, old, new in TESTER_MUTANTS:
        if c.js.count(old) < 1:
            missed.append(f"{name} (anchor missing)")
            continue
        m = copy.copy(c)
        m.js = c.js.replace(old, new, 1)
        try:
            ok = la11(m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(TESTER_MUTANTS)} caught; missed {missed}"


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
