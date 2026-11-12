"""Red team of sprint R1 (owner, 2026-11-11): the journey menus and the explained "Mon profil" page.

    python scripts/redteam_navigation.py [--browser | --real]

  U1 menus: the phone bar is Explorer, Mon profil, Mes vœux, Calendrier + "Plus"; the wide-screen menu is the same four, a
     "Comprendre" menu (comparator, call depth, true selectivity, specialties, data quality, glossary) and "Parents et
     professeurs"; every page of one menu is reachable from the other; the map and the jobs are reached through the Explorer views,
     "Où je me situe", "Je me réoriente" and seconde/première through "Mon profil"
  U2 router: every route has a tab (Explorer = list, map, jobs and every formation page; Mon profil = the profile, Où je me situe,
     Je me réoriente, seconde/première); "Comprendre" and "Plus" mark exactly their own pages; every route name is a closed
     analytics route; the profile page is routed
  U3 header chip (Node): escaped, validated by vxProfile (an invalid series reads as bac général), "Créer mon profil" without a
     profile, the reorientation label outside terminale, hidden where the profile bar is (stats, a shared list)
  U4 the form (Node): only the fields of the situation are drawn (terminale bac général / techno / pro, not in terminale = the
     académie only), every field has its "what it is used for" line, stored strings escaped, the first save is explicit
  U5 reading the form (Node): outside terminale the stored fields are kept as they are and no bac field is ever invented; the
     status is validated; the route of bac techno/pro is kept only with the same bac; missing specialties take the defaults
  U6 browser (--browser): nothing is stored before "Enregistrer", a later change is saved at once, terminale <-> not in terminale
     keeps the bac fields, erasing asks first, the chip follows, "Comprendre" opens and closes (Escape, click elsewhere), the
     Explorer tab is marked on the map, no JS error and no horizontal scroll on a phone
  U7 wording and privacy: vouvoiement, no chance or probability, the page sends nothing but the vocabulary request (the lycée is
     searched in the browser), the privacy promises match the code, docs and release guards
  U8 mutation test of U1-U5 and U7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")


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
        self.analytics = (ROOT / "suptracker" / "analytics.py").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


def top(js: str, name: str) -> str:
    """A top-level definition of app.js (function or const), as written."""
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    lines, out = js[m.start():].split("\n"), []
    is_const = lines[0].startswith("const ")
    for k, ln in enumerate(lines):
        out.append(ln)
        if k and (ln == "}" or ln == "};") and not is_const:
            break
        if is_const and (ln.endswith(";") and (k == 0 or ln in ("};", "];") or not ln.startswith(" "))):
            break
    return "\n".join(out)


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    if r.returncode:
        return "__error__ " + r.stderr[-600:]
    return r.stdout


def hrefs(html: str, opener: str) -> list[str]:
    i = html.find(opener)
    if i < 0:
        return []
    j = html.find("</nav>", i) if "<nav" in opener else html.find("</div>", i)
    return re.findall(r'href="(#/[^"]*)"', html[i:j])


def tabs(html: str, opener: str) -> list[str]:
    i = html.find(opener)
    if i < 0:
        return []
    j = html.find("</div>", i)
    return re.findall(r'data-tab="([a-z]+)"', html[i:j])


MAIN = ["#/", "#/profil", "#/voeux", "#/calendrier"]
COMP = ["#/compare", "#/comprendre", "#/selectivite", "#/specialites", "#/qualite", "#/glossaire"]


@check("U1 menus: phone bar and wide-screen menu follow the journey, every page reachable from both, map and jobs via Explorer")
def u1(c: Ctx):
    bad = []
    bar, more = hrefs(c.html, '<nav class="tabbar"'), hrefs(c.html, '<div id="more-menu"')
    topnav, comp = hrefs(c.html, '<nav class="topnav"'), hrefs(c.html, '<div id="comp-menu"')
    if bar != MAIN:
        bad.append(("phone bar", bar))
    if 'id="more-btn"' not in c.html or 'aria-controls="more-menu"' not in c.html:
        bad.append("no Plus button")
    if more != COMP + ["#/accompagner"]:
        bad.append(("Plus menu", more))
    if comp != COMP or 'id="comp-btn"' not in c.html or 'aria-controls="comp-menu"' not in c.html:
        bad.append(("Comprendre menu", comp))
    if topnav != MAIN + COMP + ["#/accompagner"]:
        bad.append(("wide-screen menu", topnav))
    if set(bar) | set(more) != set(topnav):
        bad.append("a page of one menu is missing from the other")
    for label in ("Explorer", "Mon profil", "Mes vœux", "Calendrier", "Parents et professeurs"):
        if c.html.count(f">{label}<") + c.html.count(f">{label} <") + len(re.findall(rf"</svg>{label}(?:<|$)", c.html, re.M)) < 2:
            bad.append(("label not in both menus", label))
    try:
        views = top(c.js, "explorerViews") + top(c.js, "EXPLORER_VIEWS")
    except KeyError:
        views = ""
    if not all(h in views for h in ('"#/carte"', '"#/metiers"', '"#/"')):
        bad.append("Explorer views do not reach the map and the jobs")
    for fn in ("viewHome", "viewCarte", "viewMetiers"):
        try:
            if "explorerViews(" not in top(c.js, fn):
                bad.append(("no Explorer views", fn))
        except KeyError:
            bad.append(("page gone", fn))
    vs = c.js[c.js.index("async function viewSearch("):c.js.index("function stageCard(")]
    if 'explorerViews("liste", q)' not in vs:
        bad.append("search results without the Explorer views")
    try:
        prof = top(c.js, "viewProfil") + top(c.js, "profileForm")
    except KeyError:
        prof = ""
    for h in ("#/parcours", "#/reorientation", "#/premiere", "#/voeux"):
        if f'href="{h}"' not in prof:
            bad.append(("not reachable from Mon profil", h))
    mob = "\n".join(m.group(1) for m in re.finditer(r"@media \(max-width: 720px\) \{(.*?)\n\}", re.sub(r"/\*.*?\*/", "", c.css), re.S))
    if not re.search(r"\.profile-chip \{ display: none; \}", mob) or ".topnav { display: none; }" not in mob:
        bad.append("wide-screen menu or chip shown on a phone")
    if ".profile-chip[hidden], .profile-bar[hidden] { display: none; }" not in c.css:
        bad.append("hidden chip or bar still displayed (their display overrides the attribute)")
    return not bad, f"{len(bad)} problems {bad[:4]}"


def const(js: str, name: str) -> str:
    """A top-level const statement, up to the first line that ends it (`;`, an end-of-line comment allowed)."""
    m = re.search(rf"^const {re.escape(name)} = .*?;[ \t]*(?://[^\n]*)?$", js, re.M | re.S)
    if not m:
        raise KeyError(name)
    return m.group(0)


def tables(c: Ctx):
    prog = "\n".join(const(c.js, n) for n in ("TAB_OF", "COMP_TABS", "MORE_TABS", "ROUTE_NAME")) + \
        "\nprocess.stdout.write(JSON.stringify({TAB_OF, COMP_TABS, MORE_TABS, ROUTE_NAME}));"
    r = node(prog)
    if r is None or r.startswith("__error__"):
        return r
    return json.loads(r)


@check("U2 router: every route has its journey tab, Comprendre and Plus mark their own pages, routes are closed analytics routes")
def u2(c: Ctx):
    t = tables(c)
    if t is None:
        return True, "node not installed"
    if isinstance(t, str):
        return False, t
    bad = []
    T, R = t["TAB_OF"], t["ROUTE_NAME"]
    explorer, profil = ("s", "f", "evolution", "carte", "metiers"), ("parcours", "profil", "reorientation", "premiere")
    for k in explorer:
        if T.get(k) != "home":
            bad.append(("not under Explorer", k, T.get(k)))
    for k in profil:
        if T.get(k) != "profil":
            bad.append(("not under Mon profil", k, T.get(k)))
    for k in ("voeux", "calendrier", "liste", "stats", *t["COMP_TABS"], "accompagner"):
        if T.get(k) != k:
            bad.append(("own tab", k, T.get(k)))
    if set(R) - set(T):
        bad.append(("route without a tab", sorted(set(R) - set(T))))
    if t["COMP_TABS"] != tabs(c.html, '<div id="comp-menu"'):
        bad.append(("Comprendre marks other pages", t["COMP_TABS"]))
    if t["MORE_TABS"] != tabs(c.html, '<div id="more-menu"'):
        bad.append(("Plus marks other pages", t["MORE_TABS"]))
    routes = c.analytics.split("ROUTES = (", 1)[1].split(")", 1)[0]
    if [v for v in R.values() if f'"{v}"' not in routes]:
        bad.append(("route name outside the closed analytics routes", [v for v in R.values() if f'"{v}"' not in routes]))
    if R.get("profil") != "profil" or 'if (a === "profil") return await viewProfil();' not in c.js:
        bad.append("profile page not routed")
    if '(!menu.contains(e.target) || e.target.closest("a"))' not in c.js:
        bad.append("a menu stays open after a click on a link to the current page")
    vp = top(c.js, "viewParcours")
    awaits = vp.count("await ")
    guards = vp.count('if ($view.dataset.rendered !== mk) return;')
    if 'const mk = "parcours:loading";' not in vp or vp.index("$view.dataset.rendered = mk;") > vp.index("await ") or guards < awaits - 1 \
            or vp.index('if ($view.dataset.rendered !== mk) return;\n  $view.dataset.rendered = "parcours";') > vp.index("$view.innerHTML ="):
        bad.append(("Où je me situe can draw over another page", awaits, guards))
    mt = top(c.js, "markTab")
    if '["comp-btn", "comp-menu", COMP_TABS]' not in mt or '["more-btn", "more-menu", MORE_TABS]' not in mt or "menu.hidden = true;" not in mt:
        bad.append("menus not marked or not closed on navigation")
    return not bad, f"{len(bad)} problems {bad[:4]}"


CHIP_PROG = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = [];
const ICONS = { edit: "<svg edit></svg>", profile: "<svg prof></svg>" };
const JV = null;
for (const [tab, raw] of cases) {
  const el = { hidden: false, innerHTML: "", attrs: {}, cls: new Set(),
    classList: { toggle(k, on) { on ? el.cls.add(k) : el.cls.delete(k); } }, setAttribute(k, v) { el.attrs[k] = v; } };
  const document = { getElementById: (id) => (id === "profile-chip" ? el : null) };
  globalThis.document = document;
  profileChip(tab, raw);
  out.push({ hidden: el.hidden, html: el.innerHTML, empty: el.cls.has("empty"), label: el.attrs["aria-label"] || "" });
}
process.stdout.write(JSON.stringify(out));
"""


def chip_run(js: str):
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const REO_LABEL = ", "const isReo = ")))
    prog = helpers + "\n" + top(js, "vxProfile") + "\n" + top(js, "MENTION_SHORT") + "\n" + top(js, "chipLine") + "\n" + top(js, "profileChip") + CHIP_PROG
    hostile = "<img src=x onerror=alert(1)>"
    cases = [["home", None], ["home", {"serie": "bg", "spe1": hostile, "spe2": "SES", "mention": "b"}],
             ["voeux", {"serie": "bt", "voie": "autre", "voie_label": hostile, "mention": "tb"}],
             ["home", {"serie": "xx", "spe1": "MATHS", "spe2": "SES", "mention": "zz"}],
             ["home", {"statut": "reorientation", "academie": hostile}], ["stats", {"serie": "bg"}], ["liste", None], ["home", [1, 2]]]
    return node(prog, cases)


def chip_ok(r) -> tuple[bool, str]:
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    none, bg, bt, inval, reo, stats, liste, arr = o
    if none["hidden"] or not none["empty"] or "Créer mon profil" not in none["html"] or none["label"] != "Créer mon profil":
        bad.append(("no profile", none))
    if "<img" in bg["html"] or "&lt;img" not in bg["html"] or "bac général" not in bg["html"] or "bien" not in bg["html"] or bg["empty"]:
        bad.append(("bac général", bg["html"]))
    if "<img" in bt["html"] or "bac techno" not in bt["html"] or "très bien" not in bt["html"]:
        bad.append(("bac techno", bt["html"]))
    if "bac général" not in inval["html"] or "assez bien" not in inval["html"]:
        bad.append(("not validated", inval["html"]))
    if "Je ne suis plus en terminale" not in reo["html"] or "<img" in reo["html"] or "bac" in reo["html"]:
        bad.append(("reorientation", reo["html"]))
    if not stats["hidden"] or not liste["hidden"]:
        bad.append("chip shown on the stats or a shared list")
    if not arr["empty"]:
        bad.append("an array stored as profile is read as a profile")
    return not bad, f"{len(bad)} problems {bad[:3]}"


@check("U3 header chip (Node): escaped, validated, 'Créer mon profil' without a profile, reorientation label, hidden on stats and lists")
def u3(c: Ctx):
    return chip_ok(chip_run(c.js))


FORM_PROG = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const JV = { series: [{ code: "bg", label: "bac général" }, { code: "bt", label: "bac technologique" }, { code: "bp", label: "bac professionnel" }],
  specialties: [{ code: "MATHS", short: "Mathématiques" }, { code: "SES", short: "SES" }, { code: "X", short: "<b>spé</b>" }],
  mentions: [{ code: "ab", label: "Assez bien" }, { code: "b", label: "Bien" }],
  academies: ["Lyon", "<i>Acad</i>"], voies: { bt: [{ code: "sti2d", label: "<u>STI2D</u>" }], bp: [{ code: "cuisine", label: "Cuisine" }] } };
process.stdout.write(JSON.stringify(cases.map(([p, saved]) => profileForm(p, saved))));
"""


def form_run(js: str):
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const REO_LABEL = ", "const isReo = ")))
    prog = helpers + "\n" + const(js, "PF_SAVE") + "\n" + top(js, "spe2Of") + "\n" + top(js, "profileForm") + FORM_PROG
    hostile = {"nom": "<img src=x onerror=alert(1)>", "uai": "1", "commune": "x"}
    cases = [[{"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "academie": "Lyon", "lycee": hostile}, True],
             [{"serie": "bt", "voie": "sti2d", "mention": "ab"}, True],
             [{"serie": "bp", "mention": "ab"}, False],
             [{"statut": "reorientation", "serie": "bg", "spe1": "MATHS", "spe2": "SES", "academie": "Lyon"}, True],
             [{"serie": "bg", "spe1": "SES", "spe2": "X", "mention": "ab"}, False],
             [{"statut": "reorientation", "academie": "Lyon"}, False],
             [{"serie": "bg", "spe1": "MATHS", "spe2": "MATHS", "mention": "ab"}, True]]
    return node(prog, cases)


def names(html: str) -> list[str]:
    return re.findall(r'name="([a-z_0-9]+)"', html)


def form_ok(r) -> tuple[bool, str]:
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    bg, bt, bp, reo, nomaths, reo_new, same = json.loads(r)
    bad = []
    # owner, 2026-11-12: two DIFFERENT specialties in terminale, one artistic at most (a single Arts code): the second list never
    # offers the first choice, a stored identical pair shows another one, and the rule is said
    second = lambda h: re.search(r'<select name="spe2"[^>]*>(.*?)</select>', h, re.S).group(1)  # noqa: E731
    if 'value="SES"' in second(nomaths) or 'value="MATHS"' in second(same) or 'value="MATHS"' in second(bg) \
            or not re.search(r'<option value="SES" selected', second(bg)) or not re.search(r"selected", second(same)):
        bad.append("the second specialty can repeat the first")
    if "une seule peut être artistique" not in bg:
        bad.append("the one-arts-specialty rule is not said")
    want = {"bg": ["statut", "statut", "serie", "spe1", "spe2", "maths_expertes", "mention", "academie", "boursier"],
            "bt": ["statut", "statut", "serie", "voie", "mention", "academie", "boursier"],
            "bp": ["statut", "statut", "serie", "voie", "mention", "academie", "boursier"],
            "reo": ["statut", "statut", "academie"], "nomaths": ["statut", "statut", "serie", "spe1", "spe2", "mention", "academie", "boursier"]}
    for k, h in (("bg", bg), ("bt", bt), ("bp", bp), ("reo", reo), ("nomaths", nomaths)):
        if names(h) != want[k]:
            bad.append(("fields", k, names(h)))
        fields = re.findall(r'<div class="pf-field">(.*?)<p class="pf-why">(.*?)</p></div>', h, re.S)
        if h.count('class="pf-field"') != len(fields) or any(len(re.sub(r"<[^>]+>", "", w).strip()) < 40 for _, w in fields):
            bad.append(("a field without its explanation", k))
        if 'href="#/premiere"' not in h or 'value="terminale"' not in h or 'value="reorientation"' not in h:
            bad.append(("situation choices", k))
    if "<img" in bg or "&lt;img" not in bg or "<i>Acad" in bg or "<b>spé" in nomaths or "<u>STI2D" in bt:
        bad.append("a stored or vocabulary string is not escaped")
    if 'id="lyc-q"' not in bg or "lyc-q" in reo or 'name="mention"' in reo or 'name="serie"' in reo:
        bad.append("the situation does not decide the fields")
    if not re.search(r'value="reorientation" checked', reo) or re.search(r'value="terminale" checked', reo) or not re.search(r'value="terminale" checked', bg):
        bad.append("situation not read back")
    if "Enregistrer mon profil" in bg or "Enregistrer mon profil" not in bp or "Enregistrer mon profil" not in nomaths:
        bad.append("first save not explicit, or a button after it")
    if "Enregistrer mon profil" not in reo_new or "Enregistrer mon profil" in reo:
        bad.append("no save button outside terminale before the first save")
    if '<option value="sti2d" selected' not in bt:
        bad.append("route not read back")
    return not bad, f"{len(bad)} problems {bad[:3]}"


@check("U4 the form (Node): the situation decides the fields, each field says what it is used for, strings escaped, explicit first save")
def u4(c: Ctx):
    return form_ok(form_run(c.js))


READ_PROG = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([data, p, serie, raw, voieLabel]) => {
  const fd = { get: (k) => (k in data ? data[k] : null) };
  const form = { querySelector: (q) => (q.includes("voie") && voieLabel ? { selectedOptions: [{ textContent: voieLabel }] } : null) };
  return readForm(fd, p, serie, { uai: "1" }, form, raw);
});
process.stdout.write(JSON.stringify(out));
"""


def read_run(js: str):
    prog = top(js, "voieFromForm") + "\n" + top(js, "readForm") + READ_PROG
    cases = [
        [{"statut": "reorientation", "academie": "Lyon"}, {"serie": "bg", "mention": "ab"}, "bg", None, None],
        [{"statut": "reorientation", "academie": ""}, {"serie": "bg"}, "bg", {"serie": "bt", "voie": "sti2d", "mention": "tb", "academie": "Lyon"}, None],
        [{"statut": "terminale", "serie": "bt", "voie": "sti2d", "mention": "b", "academie": "Lyon"}, {"serie": "bt"}, "bt", None, "STI2D"],
        [{"statut": "terminale", "serie": "bp", "voie": "sti2d", "mention": "b"}, {"serie": "bt"}, "bt", None, "STI2D"],
        [{"statut": "hacked", "serie": "bg", "mention": "b"}, {}, "bg", None, None],
        [{"statut": "terminale", "serie": "bt", "mention": "b"}, {"serie": "bg", "maths_expertes": True}, "bg", {"serie": "bg", "maths_expertes": True}, None],
    ]
    return node(prog, cases)


def read_ok(r) -> tuple[bool, str]:
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    reo_new, reo_keep, bt, changed, hacked, me = json.loads(r)
    bad = []
    if reo_new != {"academie": "Lyon", "statut": "reorientation"}:
        bad.append(("a bac field invented outside terminale", reo_new))
    if reo_keep != {"serie": "bt", "voie": "sti2d", "mention": "tb", "academie": "", "statut": "reorientation"}:
        bad.append(("stored fields not kept outside terminale", reo_keep))
    if bt.get("voie") != "sti2d" or bt.get("voie_label") != "STI2D" or bt.get("statut") != "terminale" or bt.get("lycee") != {"uai": "1"}:
        bad.append(("bac techno", bt))
    if changed.get("voie") is not None or changed.get("serie") != "bp":
        bad.append(("route kept across a new bac", changed))
    if hacked.get("statut") != "terminale" or hacked.get("spe1") != "MATHS" or hacked.get("spe2") != "SES":
        bad.append(("status not validated or no default specialties", hacked))
    if me.get("maths_expertes") is not True:
        bad.append(("a field the form does not draw is dropped", me))
    return not bad, f"{len(bad)} problems {bad[:3]}"


@check("U5 reading the form (Node): no bac field invented outside terminale, status validated, route kept only with the same bac")
def u5(c: Ctx):
    return read_ok(read_run(c.js))


BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[2];
(async () => {
  const b = await chromium.launch(); const errs = []; const o = {};
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } }); const p = await ctx.newPage();
  p.on("pageerror", (e) => errs.push(e.message));
  const prof = () => p.evaluate(() => JSON.parse(localStorage.getItem("profile")));
  const wait = (s) => p.waitForFunction((s) => document.getElementById("view").dataset.rendered === s, s, { timeout: 15000 });
  await p.goto(base + "/#/profil"); await wait("profil");
  o.chip0 = await p.textContent("#profile-chip");
  await p.selectOption('#pf [name="mention"]', "tb"); await wait("profil"); await p.waitForTimeout(200);
  o.beforeSave = await prof();
  o.keptDraft = await p.inputValue('#pf [name="mention"]');
  await p.click("#pf button.primary"); await p.waitForTimeout(300);
  o.saved = await prof();
  await p.selectOption('#pf [name="mention"]', "b"); await p.waitForTimeout(300);
  o.changed = await prof();
  o.chip1 = await p.textContent("#profile-chip");
  await p.check('#pf [name="statut"][value="reorientation"]'); await p.waitForTimeout(300);
  o.reo = await prof();
  o.reoFields = await p.$$eval("#pf [name]", (els) => els.map((e) => e.name));
  await p.check('#pf [name="statut"][value="terminale"]'); await p.waitForTimeout(300);
  o.back = await prof();
  await p.click("#pf-erase"); await p.waitForTimeout(200);
  o.notYet = await prof();
  await p.click("#pf-erase-yes"); await p.waitForTimeout(300);
  o.erased = await prof();
  // the "Comprendre" menu: opens, Escape closes it with the focus back on its button, a click elsewhere closes it
  await p.click("#comp-btn"); o.open = await p.isVisible("#comp-menu");
  await p.keyboard.press("Escape"); o.esc = !(await p.isVisible("#comp-menu")) && (await p.evaluate(() => document.activeElement.id)) === "comp-btn";
  await p.click("#comp-btn"); await p.mouse.click(20, 600); o.outside = !(await p.isVisible("#comp-menu"));
  await p.goto(base + "/#/carte"); await p.waitForTimeout(1500);
  o.mapTab = await p.$eval('.topnav a[data-tab="home"]', (a) => a.getAttribute("aria-current"));
  o.viewsOn = await p.$eval('.views a[aria-current="true"]', (a) => a.textContent.trim());
  await p.goto(base + "/#/glossaire"); await p.waitForTimeout(500);
  o.compMarked = await p.$eval("#comp-btn", (x) => x.classList.contains("current"));
  await p.goto(base + "/#/stats"); await p.waitForTimeout(800);
  o.chipStats = await p.$eval("#profile-chip", (x) => getComputedStyle(x).display);
  await ctx.close();
  // review scenarios, no profile stored: Enter in the lycée box, a situation switch and back keep everything a draft
  const c2 = await b.newContext({ viewport: { width: 1280, height: 900 } }); const r = await c2.newPage();
  r.on("pageerror", (e) => errs.push(e.message));
  await r.goto(base + "/#/profil"); await r.waitForFunction(() => document.getElementById("view").dataset.rendered === "profil");
  await r.fill("#lyc-q", "lycee"); await r.press("#lyc-q", "Enter"); await r.waitForTimeout(300);
  o.enter = await r.evaluate(() => localStorage.getItem("profile"));
  await r.selectOption('#pf [name="serie"]', "bt"); await r.waitForTimeout(300);
  await r.selectOption('#pf [name="mention"]', "tb"); await r.waitForTimeout(300);
  await r.check('#pf [name="statut"][value="reorientation"]'); await r.waitForTimeout(300);
  o.switchStored = await r.evaluate(() => localStorage.getItem("profile"));
  o.focusChecked = await r.evaluate(() => document.activeElement.checked === true && document.activeElement.value === "reorientation");
  o.reoSave = await r.isVisible("#pf button.primary");
  await r.check('#pf [name="statut"][value="terminale"]'); await r.waitForTimeout(300);
  o.draftBack = [await r.inputValue('#pf [name="serie"]'), await r.inputValue('#pf [name="mention"]')];
  o.stillNone = await r.evaluate(() => localStorage.getItem("profile"));
  await c2.close();
  const ph = await b.newContext({ ...devices["iPhone 13"] }); const q = await ph.newPage(); q.on("pageerror", (e) => errs.push(e.message));
  o.phone = {};
  for (const h of ["#/", "#/profil", "#/carte", "#/metiers", "#/parcours"]) {
    await q.goto(base + "/" + h); await q.waitForTimeout(1500);
    o.phone[h] = await q.evaluate(() => ({ hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      chip: getComputedStyle(document.getElementById("profile-chip")).display, bar: getComputedStyle(document.querySelector(".tabbar")).display,
      cur: (document.querySelector('.tabbar a[aria-current="page"]') || {}).textContent }));
  }
  await ph.close();
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


@check("U6 browser: explicit first save, later changes saved at once, situations keep the bac fields, erase asks first, menus work")
def u6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".nav_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if "Créer mon profil" not in o["chip0"] or o["beforeSave"] is not None or o["keptDraft"] != "tb":
        bad.append(("stored before Enregistrer, or the draft lost", o["beforeSave"], o["keptDraft"]))
    if not o["saved"] or o["saved"].get("mention") != "tb" or o["saved"].get("statut") != "terminale":
        bad.append(("first save", o["saved"]))
    if not o["changed"] or o["changed"].get("mention") != "b" or "bien" not in o["chip1"]:
        bad.append(("later change not saved at once", o["changed"], o["chip1"]))
    if not o["reo"] or o["reo"].get("statut") != "reorientation" or o["reo"].get("serie") != "bg" or o["reoFields"] != ["statut", "statut", "academie"]:
        bad.append(("not in terminale", o["reo"], o["reoFields"]))
    if not o["back"] or o["back"].get("statut") != "terminale" or o["back"].get("mention") != "b":
        bad.append(("back to terminale lost the bac fields", o["back"]))
    if o["notYet"] is None or o["erased"] is not None:
        bad.append(("erase without asking, or not erased", o["notYet"], o["erased"]))
    if not (o["open"] and o["esc"] and o["outside"]):
        bad.append(("Comprendre menu", o["open"], o["esc"], o["outside"]))
    if o["mapTab"] != "page" or o["viewsOn"] != "Carte" or not o["compMarked"]:
        bad.append(("tabs", o["mapTab"], o["viewsOn"], o["compMarked"]))
    if o["chipStats"] != "none":
        bad.append(("chip shown on the stats", o["chipStats"]))
    if o["enter"] is not None or o["switchStored"] is not None or o["stillNone"] is not None:
        bad.append(("stored before Enregistrer", o["enter"], o["switchStored"], o["stillNone"]))
    if o["draftBack"] != ["bt", "tb"] or not o["focusChecked"] or not o["reoSave"]:
        bad.append(("draft lost on a situation switch, focus or save button", o["draftBack"], o["focusChecked"], o["reoSave"]))
    ph = {k: v for k, v in o["phone"].items() if v["hscroll"] or v["chip"] != "none" or v["bar"] != "flex"}
    want = {"#/": "Explorer", "#/profil": "Mon profil", "#/carte": "Explorer", "#/metiers": "Explorer", "#/parcours": "Mon profil"}
    cur = {k: v["cur"] for k, v in o["phone"].items() if v["cur"] != want[k]}
    if ph or cur:
        bad.append(("phone", ph, cur))
    return not bad, f"{len(bad)} problems {bad[:3]}"


@check("U7 wording and privacy: vouvoiement, no chance, nothing sent but the vocabulary request, promises match the code, docs")
def u7(c: Ctx):
    bad = []
    try:
        page = top(c.js, "viewProfil") + top(c.js, "profileForm") + top(c.js, "homeProfile") + top(c.js, "readForm")
    except KeyError as e:
        return False, f"gone: {e}"
    words = " ".join(re.findall(r"`([^`]*)`|\"([^\"\n]*)\"", page) and [a or b for a, b in re.findall(r"`([^`]*)`|\"([^\"\n]*)\"", page)])
    words = re.sub(r"<[^>]+>|\$\{[^}]*\}", " ", words)
    if FORMAL.search(words):
        bad.append(("tutoiement", FORMAL.search(words).group(0)))
    if CHANCE.search(words):
        bad.append(("chance wording", CHANCE.search(words).group(0)))
    if "jamais des chances d'admission" not in page:
        bad.append("the page does not say these are not chances")
    calls = re.findall(r"api\(([^)]*)\)", top(c.js, "viewProfil"))
    if calls != ['"/api/journey/vocab"']:
        bad.append(("the profile page sends something", calls))
    if "fetch(" in page or "track(" in page:
        bad.append("the profile page records or sends an event")
    if 'api("/api/lycees")' not in top(c.js, "loadLycees") or "lycSearch(lq.value)" not in page:
        bad.append("the lycée is not searched in the browser")
    for promise in ("Il reste dans ce navigateur", "Votre lycée n'est jamais envoyé", "aucune mesure d'audience ne les contient"):
        if promise not in page:
            bad.append(("promise missing", promise))
    if '$view.dataset.rendered = "profil:loading";' not in top(c.js, "viewProfil").split("await", 1)[0]:
        bad.append("no navigation marker before the first await")
    if 'if ($view.dataset.rendered !== "profil:loading") return;' not in top(c.js, "viewProfil"):
        bad.append("no navigation guard after the vocabulary request")
    sugg = c.js[c.js.index("async function suggestLycee("):c.js.index("// ---- Sprint 5")]
    if 'else store.set("profilDraft", { lycee: lyc, academie: l.academie || "" });' not in sugg or "spe1:" in sugg:
        bad.append("the lycée suggestion stores a profile the student never chose")
    vpf = top(c.js, "viewProfil")
    if 'if (lq) lq.onkeydown = (e) => { if (e.key === "Enter") e.preventDefault(); };' not in vpf:
        bad.append("Enter in the lycée box saves the profile")
    clear = vpf[vpf.index('if (lc) lc.onclick'):vpf.index("const er =")]
    if "if (has) document.getElementById(\"pf\").requestSubmit();" not in clear or "draft = " not in clear:
        bad.append("Retirer saves before Enregistrer")
    sit = vpf[vpf.index("const setSituation"):vpf.index("draw();\n}")]
    if not sit.lstrip().split("\n")[1].strip().startswith("if (!has) {") or "store.set(" in sit[:sit.index("} else if")]:
        bad.append("a situation switch stores before Enregistrer")
    if '"lycee", "boursier"' not in sit:
        bad.append("back to terminale drops the lycée")
    if '${focusName === "statut" ? ":checked" : ""}' not in vpf:
        bad.append("focus on the wrong situation")
    if '"mon_profil"' not in c.api.split("FEATURES = [", 1)[1].split("]", 1)[0] or '"mon_profil": ("app.js", "async function viewProfil(")' not in c.release:
        bad.append("feature or release guard")
    if c.readme and "Mon profil" not in c.readme:
        bad.append("README section")
    if c.claude and "Mon profil" not in c.claude:
        bad.append("CLAUDE.md rule")
    return not bad, f"{len(bad)} problems {bad[:4]}"


MUTANTS = [
    ("html", "Mon profil dropped from the phone bar", '<a href="#/profil" data-tab="profil"><svg', '<a href="#/parcours" data-tab="profil"><svg', "u1"),
    ("html", "glossary missing from Comprendre", '        <a href="#/glossaire" data-tab="glossaire">Glossaire</a>\n      </div>', "      </div>", "u1"),
    ("html", "adult page missing from Plus", '  <a href="#/accompagner" data-tab="accompagner">Parents et professeurs</a>\n</div>', "</div>", "u1"),
    ("js", "map unreachable from Explorer", 'carte: "#/carte", metiers', 'carte: "#/", metiers', "u1"),
    ("js", "search results lose the views", '${explorerViews("liste", q)}', "", "u1"),
    ("css", "chip kept on a phone", "  .profile-chip { display: none; }\n", "", "u1"),
    ("js", "map back under its own tab", 'carte: "home", compare', 'carte: "carte", compare', "u2"),
    ("js", "Où je me situe under no tab", 'parcours: "profil", profil', 'parcours: "parcours", profil', "u2"),
    ("js", "Plus marks the calendar", 'const MORE_TABS = [...COMP_TABS, "accompagner"];', 'const MORE_TABS = [...COMP_TABS, "calendrier", "accompagner"];', "u2"),
    ("js", "profile page not routed", '    if (a === "profil") return await viewProfil();\n', "", "u2"),
    ("js", "menus left open on navigation", "    if (menu) menu.hidden = true;\n  }\n}", "  }\n}", "u2"),
    ("js", "chip unescaped", '`${esc(p.spe1 || "")} + ${esc(p.spe2 || "")}` : p.voie_label ? esc(p.voie_label) : "";',
     '`${p.spe1 || ""} + ${p.spe2 || ""}` : p.voie_label ? p.voie_label : "";', "u3"),
    ("js", "chip reads the raw profile", "<span>${chipLine(vxProfile(raw))}</span>", "<span>${chipLine(raw)}</span>", "u3"),
    ("js", "chip on a shared list", '  if (tab === "stats" || tab === "liste") { el.hidden = true; return; }\n  el.hidden = false;\n  const has',
     '  el.hidden = false;\n  const has', "u3"),
    ("js", "reorientation chip shows the bac", "  if (isReo(p)) return REO_LABEL;\n  const ser = { bg: \"bac général\", bt: \"bac techno\"",
     "  const ser = { bg: \"bac général\", bt: \"bac techno\"", "u3"),
    ("js", "bac fields drawn outside terminale", "  if (reo) {\n    return `<form id=\"pf\">", "  if (false) {\n    return `<form id=\"pf\">", "u4"),
    ("js", "lycée name unescaped in the form", 'value="${p.lycee ? esc(p.lycee.nom) : ""}"', 'value="${p.lycee ? p.lycee.nom : ""}"', "u4"),
    ("js", "second specialty list offers the first", "JV.specialties.filter((x) => x.code !== p.spe1), spe2Of(p)", "JV.specialties, p.spe2", "u4"),
    ("js", "identical stored pair shown as is", "return p.spe2 && p.spe2 !== p.spe1 ? p.spe2 :", "return p.spe2 ? p.spe2 :", "u4"),
    ("js", "a field without its explanation", '"Chaque formation publie la part de ses admis venant du bac général, technologique ou professionnel."', '""', "u4"),
    ("js", "first save no longer explicit", '${mention}${where}${saved ? "" : PF_SAVE}', '${mention}${where}${true ? "" : PF_SAVE}', "u4"),
    ("js", "no save button outside terminale", '${acad}</section>${saved ? "" : PF_SAVE}', '${acad}</section>', "u4"),
    ("js", "bac fields invented outside terminale", '  if (reo) return { ...(raw || {}), academie', '  if (reo) return { ...p, academie', "u5"),
    ("js", "status not validated", 'lycee: lyc, statut: fd.get("statut") === "reorientation" ? "reorientation" : "terminale" };',
     'lycee: lyc, statut: fd.get("statut") };', "u5"),
    ("js", "no default specialty", 'spe1: fd.get("spe1") || p.spe1 || "MATHS"', 'spe1: fd.get("spe1") || p.spe1', "u5"),
    ("js", "tutoiement on the profile page", "SupCompass lit les chiffres officiels de Parcoursup pour vous",
     "SupCompass lit les chiffres officiels de Parcoursup pour toi", "u7"),
    ("js", "chance wording on the profile page", "Ce sont des repères, jamais des chances d'admission.", "Vos chances d'être admis sont calculées.", "u7"),
    ("js", "the profile page sends the profile", '  JV = JV || await api("/api/journey/vocab");\n  if ($view.dataset.rendered !== "profil:loading") return;',
     '  JV = JV || await api("/api/journey/vocab");\n  api(`/api/voeux?${vxQuery([], PF_DEFAULT)}`);\n  if ($view.dataset.rendered !== "profil:loading") return;', "u7"),
    ("js", "no navigation guard", '  if ($view.dataset.rendered !== "profil:loading") return;\n  let draft', "  let draft", "u7"),
    ("css", "hidden chip still displayed", ".profile-chip[hidden], .profile-bar[hidden] { display: none; }", "", "u1"),
    ("js", "menu left open on a same-page link", '(!menu.contains(e.target) || e.target.closest("a"))', "!menu.contains(e.target)", "u2"),
    ("js", "Où je me situe draws over another page", '  if ($view.dataset.rendered !== mk) return;\n  $view.dataset.rendered = "parcours";', '  $view.dataset.rendered = "parcours";', "u2"),
    ("js", "maths expertes dropped when the box is hidden", "!!(raw ? raw.maths_expertes : p.maths_expertes)", "false", "u5"),
    ("js", "suggestion stores invented bac fields", 'else store.set("profilDraft", { lycee: lyc, academie: l.academie || "" });',
     'else store.set("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", lycee: lyc });', "u7"),
    ("js", "Enter saves the profile", '    if (lq) lq.onkeydown = (e) => { if (e.key === "Enter") e.preventDefault(); };   // Enter picks nothing and saves nothing (review)\n', "", "u7"),
    ("js", "Retirer saves before Enregistrer", "      if (has) document.getElementById(\"pf\").requestSubmit();\n      else {", "      document.getElementById(\"pf\").requestSubmit();\n      if (false) {", "u7"),
    ("js", "situation switch stores at once", "    if (!has) {                                                       // no profile yet",
     "    if (false) {                                                       // no profile yet", "u7"),
    ("js", "focus on the first situation", '${focusName === "statut" ? ":checked" : ""}', "", "u7"),
    ("js", "privacy promise dropped", "<li>Votre lycée n'est jamais envoyé : la liste des lycées est cherchée dans ce navigateur.</li>", "", "u7"),
]


@check("U8 mutation test: menu, router, chip, form, form reading, wording and privacy bugs are each caught")
def u8(c: Ctx):
    fns = {"u1": u1, "u2": u2, "u3": u3, "u4": u4, "u5": u5, "u7": u7}
    missed = []
    for where, name, old, new, fn in MUTANTS:
        src = getattr(c, where)
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        setattr(m, where, src.replace(old, new, 1))
        if fns[fn](m)[0]:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught; missed {missed}"


def run(browser: bool = False) -> list[dict]:
    c = Ctx(browser)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:                                   # a crash is a failure, never a pass
            ok, detail = False, f"crash: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--real", action="store_true", help="same as --browser (the browser check reads the real warehouse)")
    a = ap.parse_args()
    res = run(a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"]))
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    sys.exit(0 if all(r["ok"] for r in res) else 1)
