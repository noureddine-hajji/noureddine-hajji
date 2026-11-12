"""Red team of sprint R7 (owner, 2026-11-12): "Construire ma liste", the five steps of the site in one place.

    python scripts/redteam_guide.py [--db data/suptracker.duckdb] [--real] [--browser]

  GU1 the steps (Node): guideState = an independent re-implementation of the rules, on 3,000 random states (profiles valid or
      not, outside terminale, lists of 0-10 codes, the list's reading pending, failed or read, the two local flags): every
      status, the next step, the count of steps done
  GU2 the page (Node): five steps in order, each with its own link(s); the progress bar's ARIA value = the steps done; the
      "Continuer" link = the next step's; stored strings escaped; vouvoiement; never a chance; the "pas des chances" line; a drawn
      check mark, no emoji
  GU3 the reading (Node, fake API): no request without a profile, outside terminale or with an empty list; one request otherwise,
      the profile bar's own query (never the average), none when the bar already read it; the list read with the twin; a late
      answer never draws over another page; a failed reading is said
  GU4 local only: the two flags are written by the formation page and the share card and read by the guide, nowhere sent; the
      guide records no event of its own; the page view is in the closed route lists
  GU5 entry points and docs: the home card (the four doors kept), the Mes vœux link, the route, the release guard, README, CLAUDE.md
  GU6 browser (--browser / --real): a student walks the five steps on a phone (profile, a formation page, a vœu, the list read,
      the link copied): each step turns "Fait", no JS error, no horizontal scroll, controls >= 44 px
  GU7 outside terminale: the safety step is "sans objet", it links "Je me réoriente", no request
  GU8 mutation test of GU1-GU5 and GU7 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
NAMES = ("esc", "fmt", "MENTION_CODES", "BANDS", "BAND_SIGMA", "validMoyenne", "bandOf", "bandParam", "mentionParams",
         "localAverage", "moyenneText", "MENTION_SHORT", "vxProfile", "REO_LABEL", "isReo", "vxQuery", "profileLine", "ICO",
         "ICONS", "erf", "withinBand", "ZONE_RULES", "MIN_BOUNDS_N", "VX_SITUATED", "wilsonCI", "zoneOf", "isNum", "classifyZone",
         "seriesPos", "lire", "relireVue", "lectureOf", "readList", "voeuxLocal",
         "GUIDE_STEPS", "GUIDE_STATUT", "profileReady", "guideState", "guideFlags", "guideHtml", "viewGuide", "guideCard")
HARNESS = r"""
let STORE = {}, CALLS = [], API = {}, $view = { innerHTML: "", dataset: {} }, IDS = [], JV = null;
let guideSeq = 0;                                                       // app.js: the guide's per-visit counter
const store = { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v; } };
const voeux = { MAX: 10, get: () => IDS.slice() };
const profileBar = { key: "", data: null };
async function api(u) { CALLS.push(u); const f = API.fn; if (!f) throw new Error("no api"); return f(u); }
"""


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


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


def run_node(js: str, prog: str, payload):
    exe = shutil.which("node")
    if not exe:
        return None
    src = HARNESS + "\n".join(top(js, n) for n in NAMES) + "\n" + prog
    r = subprocess.run([exe, "-e", src], input=json.dumps(payload), capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.analytics = (ROOT / "suptracker" / "analytics.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""


# ------------------------------------------------------------------ GU1 the steps
MENTIONS = ("rattrapage", "sansmention", "ab", "b", "tb", "tbf")


def py_ready(raw) -> bool:
    if not isinstance(raw, dict):
        return False
    if raw.get("statut") == "reorientation":
        return True
    if raw.get("serie") not in ("bg", "bt", "bp"):
        return False
    m = raw.get("moyenne")
    ok_avg = isinstance(m, (int, float)) and not isinstance(m, bool) and 8 <= m <= 20 or \
        (isinstance(m, str) and re.fullmatch(r"\s*\d+([.,]\d+)?\s*", m or "") is not None and 8 <= float(m.strip().replace(",", ".")) <= 20)
    if raw.get("mention") not in MENTIONS and not ok_avg:
        return False
    if raw["serie"] != "bg":
        return True
    s1, s2 = raw.get("spe1"), raw.get("spe2")
    return isinstance(s1, str) and isinstance(s2, str) and bool(s1) and bool(s2) and s1 != s2


def py_state(raw, n, lecture, flags):
    """The rules, written again from the owner's brief (not from the page): steps 1-3 from the profile and the list, step 4 from
    the list's reading (no zone outside terminale), step 5 once the list was shared; the next step = the first one to do."""
    ready = py_ready(raw)
    reo = ready and raw.get("statut") == "reorientation"
    if reo:
        sec = "sans_objet"
    elif not ready or not n:
        sec = "en_attente"
    elif lecture == "pending":
        sec = "lecture"
    elif lecture == "failed":
        sec = "indisponible"
    else:
        sec = "fait" if lecture["securite_sure"] > 0 else "a_faire"
    st = {"profil": "fait" if ready else "a_faire", "explorer": "fait" if (flags["vu"] or n) else "a_faire",
          "voeux": "fait" if n else "a_faire", "securite": sec,
          "partager": "en_attente" if not n else ("fait" if flags["partage"] else "a_faire")}
    order = ("profil", "explorer", "voeux", "securite", "partager")
    nxt = next((k for k in order if st[k] == "a_faire"), None)
    return {"statuts": [st[k] for k in order], "next": nxt, "faites": sum(st[k] in ("fait", "sans_objet") for k in order)}


def random_states(seed=7, n=3000):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        kind = rng.random()
        if kind < 0.1:
            raw = rng.choice([None, [], "x", 3])
        elif kind < 0.25:
            raw = {"statut": "reorientation", "academie": rng.choice(["Paris", None])}
        else:
            raw = {"serie": rng.choice(["bg", "bt", "bp", "zz", None]), "mention": rng.choice([*MENTIONS, "passable", None]),
                   "moyenne": rng.choice([None, 12.6, 7.5, 20, 21, "13,4", "", "abc"]), "spe1": rng.choice(["MATHS", "SES", "", None]),
                   "spe2": rng.choice(["MATHS", "SES", "PC", None]), "statut": rng.choice(["terminale", None, "autre"])}
        lec = rng.choice(["pending", "failed", {"securite_sure": 0}, {"securite_sure": rng.randint(1, 4)}])
        out.append({"raw": raw, "n": rng.randint(0, 10) if rng.random() < 0.7 else 0, "lecture": lec,
                    "flags": {"vu": rng.random() < 0.4, "partage": rng.random() < 0.3}})
    return out


STATE_PROG = r"""
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", () => {
  const out = JSON.parse(raw).map((c) => {
    const lec = c.lecture === "pending" ? null : c.lecture === "failed" ? undefined : c.lecture;
    const G = guideState(c.raw, Array.from({ length: c.n }, (_, i) => String(100 + i)), lec, c.flags);
    return { statuts: G.steps.map((s) => s.statut), next: G.next, faites: G.faites, keys: G.steps.map((s) => s.key), hrefs: G.steps.map((s) => s.href) };
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def states_ok(js: str) -> tuple[bool, str]:
    cases = random_states()
    got = run_node(js, STATE_PROG, cases)
    if got is None:
        return True, "skipped (node not installed)"
    bad, seen = [], set()
    for c, g in zip(cases, got):
        want = py_state(c["raw"], c["n"], c["lecture"], c["flags"])
        seen.update(want["statuts"])
        if g["keys"] != ["profil", "explorer", "voeux", "securite", "partager"]:
            bad.append(("order", g["keys"]))
        if {k: g[k] for k in want} != want:
            bad.append((c, {k: g[k] for k in want}, want))
        if len(bad) > 3:
            break
    ok = not bad and seen >= {"fait", "a_faire", "en_attente", "lecture", "indisponible", "sans_objet"}
    return ok, f"{len(cases)} states, statuses seen {sorted(seen)}; problems {bad[:2]}"


@check("GU1 the steps: guideState = the rules written again, on 3,000 random states (statuses, next step, steps done)")
def gu1(c: Ctx):
    return states_ok(c.js)


# ------------------------------------------------------------------ GU2 the page
PAGE_PROG = r"""
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", () => {
  const out = JSON.parse(raw).map((c) => {
    const lec = c.lecture === "pending" ? null : c.lecture === "failed" ? undefined : c.lecture;
    const ids = Array.from({ length: c.n }, (_, i) => String(100 + i));
    const G = guideState(c.raw, ids, lec, c.flags);
    const reo = profileReady(c.raw) && isReo(c.raw), prof = profileReady(c.raw) ? vxProfile(c.raw) : null;
    return { G, html: guideHtml(G, { n: ids.length, reo, profLine: prof ? profileLine(prof, prof.serie) : "", sure: lec ? lec.securite_sure : 0 }) };
  });
  STORE = { profile: { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab" } }; IDS = ["1", "2"];
  out.push({ card: guideCard() });
  process.stdout.write(JSON.stringify(out));
});
"""
EVIL = '<img src=x onerror="alert(1)">'
WANT_LINKS = {"profil": ['href="#/profil"'], "explorer": ['href="#/"', 'href="#/carte"', 'href="#/metiers"'],
              "voeux": ['href="#/voeux"'], "securite": ['href="#/voeux"'], "partager": ['href="#/voeux"']}


def page_ok(js: str) -> tuple[bool, str]:
    cases = random_states(11, 300) + [
        {"raw": {"serie": "bg", "spe1": EVIL, "spe2": "SES", "mention": "ab", "academie": EVIL}, "n": 2, "lecture": {"securite_sure": 1},
         "flags": {"vu": True, "partage": False}},
        {"raw": {"statut": "reorientation", "academie": EVIL}, "n": 3, "lecture": "pending", "flags": {"vu": True, "partage": True}},
        *[{"raw": {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab"}, "n": 2, "lecture": lec, "flags": {"vu": True, "partage": True}}
          for lec in ("pending", "failed", {"securite_sure": 1})]]
    got = run_node(js, PAGE_PROG, cases)
    if got is None:
        return True, "skipped (node not installed)"
    card = got.pop()["card"]
    bad = []
    for c, g in zip(cases, got):
        h, G = g["html"], g["G"]
        steps = re.findall(r'<li class="card guide-step(?: next)?">(.*?)</li>', h, re.S)
        if len(steps) != 5:
            bad.append(("five steps", len(steps)))
            break
        for (k, links), s, st in zip(WANT_LINKS.items(), steps, G["steps"]):
            reo_safety = k == "securite" and st["statut"] == "sans_objet"
            for ln in (['href="#/reorientation"'] if reo_safety else links):
                if ln not in s:
                    bad.append((k, "link", ln))
            if f'<span class="badge">' not in s or (st["statut"] == "fait") != ('<path d="M5 12.5l4.5 4.5L19 7.5"/>' in s):
                bad.append((k, "status badge or check mark", st["statut"]))
        if f'aria-valuenow="{G["faites"]}"' not in h or 'aria-valuemax="5"' not in h or 'role="progressbar"' not in h:
            bad.append(("progress", G["faites"]))
        done_msg = "Toutes les étapes sont faites" in h
        if done_msg != (G["faites"] == 5):
            bad.append(("the completion message with steps left (Codex)", G["faites"], [s["statut"] for s in G["steps"]]))
        nxt = next((s for s in G["steps"] if s["key"] == G["next"]), None)
        cont = re.findall(r'<a class="btnlink primary" href="([^"]*)">Continuer : ([^<]*)</a>', h)
        if (nxt is None) != (not cont) or (nxt and cont[0] != (nxt["href"], nxt["titre"])):
            bad.append(("continue link", cont, nxt and nxt["key"]))
        if nxt and len(re.findall(r'guide-step next', h)) != 1:
            bad.append("the next step is not the one highlighted")
        text = re.sub(r"<[^>]+>", " ", h)
        if EVIL in h or "<img" in h:
            bad.append("a stored string is not escaped")
        if TU.search(text) or CHANCE.search(text) or "pas des chances d'admission" not in text:
            bad.append(("wording", (TU.search(text) or CHANCE.search(text) or [""])[0]))
        if re.search(r"[☀-➿\U0001F300-\U0001FAFF]", h):
            bad.append("an emoji used as a marker")
        if len(bad) > 3:
            break
    if 'href="#/guide"' not in card or "étape" not in card or "<img" in card:
        bad.append(("home card", card[:120]))
    return not bad, f"{len(cases)} pages drawn; problems {bad[:3]}"


@check("GU2 the page: five steps with their links, the progress, the next step highlighted and linked, escaped, vouvoiement, never a chance")
def gu2(c: Ctx):
    return page_ok(c.js)


# ------------------------------------------------------------------ GU3 the reading
READ_PROG = r"""
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", async () => {
  const L = JSON.parse(raw), out = {};
  const ans = { session: 2025, voeux: [{ status: "ok", cod_aff_form: "1", zone: "cible", uncertain: false, lec: L.lec, taux_acces_ens: 90 }], lecture: { securite_sure: 0, messages: [] } };
  const run = async (name, profile, ids, pre) => {
    STORE = { profile }; IDS = ids; CALLS = []; profileBar.key = ""; profileBar.data = null; $view = { innerHTML: "", dataset: {} };
    API.fn = async () => JSON.parse(JSON.stringify(ans));
    if (pre) pre();
    await viewGuide();
    out[name] = { calls: CALLS.slice(), html: $view.innerHTML };
  };
  const P = { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6, statut: "terminale" };
  await run("none", null, ["1"]);
  await run("reo", { statut: "reorientation" }, ["1"]);
  await run("empty", P, []);
  await run("read", P, ["1"]);
  // the bar's RAW answer for the same query (zone "cible" from the band's top): the guide reads it for THIS profile
  await run("bar", P, ["1"], () => { profileBar.key = vxQuery(["1"], vxProfile(P)).toString(); profileBar.data = JSON.parse(JSON.stringify(ans)); });
  await run("fail", P, ["1"], () => { API.fn = async () => { throw new Error("down"); }; });
  await run("evil", { ...P, spe1: '<img src=x onerror="alert(1)">', academie: '<img src=x>' }, ["1"]);
  // a late answer for another page never draws
  STORE = { profile: P }; IDS = ["1"]; CALLS = []; $view = { innerHTML: "", dataset: {} };
  let release; API.fn = () => new Promise((r) => { release = () => r(JSON.parse(JSON.stringify(ans))); });
  const p = viewGuide(); await new Promise((r) => setTimeout(r, 5)); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; release(); await p;
  out.race = $view.innerHTML;
  // Codex: visit 1 (old profile) pending, visit 2 (new profile, same list) drawn; visit 1's late answer must not redraw
  STORE = { profile: P }; IDS = ["1"]; CALLS = []; $view = { innerHTML: "", dataset: {} };
  let rel1; API.fn = () => new Promise((r) => { rel1 = () => r(JSON.parse(JSON.stringify(ans))); });
  const v1 = viewGuide(); await new Promise((r) => setTimeout(r, 5));
  STORE = { profile: { statut: "reorientation" } }; API.fn = async () => { throw new Error("no request outside terminale"); };
  await viewGuide(); const second = $view.innerHTML; rel1(); await v1;
  out.race2 = $view.innerHTML === second;
  out.query = vxQuery(["1"], vxProfile(P)).toString();
  process.stdout.write(JSON.stringify(out));
});
"""
# the server reads the band's top and says "cible"; read with 12,6/20 in the browser the row is a SURE safety (cdf ~0.88): the
# guide must show the browser's reading
LEC = {"n": 100, "kt": 95, "kb": 10, "s": [], "ferme": False, "fragile": False}


def reading_ok(js: str) -> tuple[bool, str]:
    o = run_node(js, READ_PROG, {"lec": LEC})
    if o is None:
        return True, "skipped (node not installed)"
    bad = []
    for k in ("none", "reo", "empty"):
        if o[k]["calls"]:
            bad.append((k, "a request", o[k]["calls"]))
    if o["read"]["calls"] != [f"/api/voeux?{o['query']}"] or "moyenne" in o["query"]:
        bad.append(("not the bar's query, or the average sent", o["read"]["calls"]))
    # the twin read the row with the average: 12.6 in AB keeps the formation "cible" -> the step says no sure safety
    if "1 vœu de sécurité sûr dans votre liste" not in o["read"]["html"] or "Lecture de votre liste" in o["read"]["html"]:
        bad.append("the list's reading (with the average kept in the browser) is not shown")
    if "<img" in o["evil"]["html"] or "&lt;img" not in o["evil"]["html"]:
        bad.append("the profile line is not escaped")
    if o["bar"]["calls"] or "1 vœu de sécurité sûr dans votre liste" not in o["bar"]["html"]:
        bad.append(("the bar's answer not reused, or not read for this profile (review: a stale average)", o["bar"]["calls"]))
    if "n'a pas pu être lue" not in o["fail"]["html"]:
        bad.append("a failed reading is not said")
    if o["race"] != "OTHER PAGE":
        bad.append("a late answer drew over another page")
    if not o["race2"]:
        bad.append("an earlier visit's answer redrew the guide (same list, another profile: Codex)")
    return not bad, f"no request in 3 cases, 1 with the bar's query, reuse, failure, race; problems {bad[:3]}"


@check("GU3 the reading: no request when nothing can be read, the profile bar's query otherwise (never the average), reuse, failure, race")
def gu3(c: Ctx):
    return reading_ok(c.js)


# ------------------------------------------------------------------ GU4 local only / GU5 entry points
def local_ok(js: str, analytics: str) -> tuple[bool, str]:
    bad = []
    uses = re.findall(r'.{0,40}"guide(?:Vu|Partage)".{0,40}', js)
    for u in uses:
        if not re.search(r'store\.(get|set)\("guide(?:Vu|Partage)"', u):
            bad.append(("a flag used outside the browser's store", u))
    sets = re.findall(r'store\.set\("(guideVu|guidePartage)", true\)', js)
    if sorted(sets) != ["guidePartage", "guidePartage", "guideVu"]:
        bad.append(("the flags are not set by the formation page and the share card (copy and print)", sets))
    if "store.set(\"guideVu\", true)" not in top(js, "viewFormation") or top(js, "bindShare").count("store.set(\"guidePartage\", true)") != 2:
        bad.append("a flag set elsewhere")
    vg = top(js, "viewGuide") + top(js, "guideHtml") + top(js, "guideState") + top(js, "guideCard")
    if "track(" in vg or "guideVu" in re.sub(r"guideFlags\(\)", "", vg):
        bad.append("the guide records an event or reads a flag outside guideFlags")
    if '"guide")' not in re.search(r"ROUTES = \((.*?)\)\n", analytics, re.S).group(0) or 'guide: "guide" }' not in js:
        bad.append("the page view is not in the closed route lists")
    return not bad, f"{len(uses)} flag uses; problems {bad[:3]}"


@check("GU4 local only: the two flags live in this browser (formation page, share card), the guide records no event, closed route lists")
def gu4(c: Ctx):
    return local_ok(c.js, c.analytics)


def entries_ok(js: str, release: str, readme: str, claude: str) -> tuple[bool, str]:
    bad = []
    home = top(js, "viewHome")
    if "${guideCard()}\n  <div class=\"doors\">" not in home or home.count('class="door"') != 4:
        bad.append("the home card (before the four doors)")
    if '<a href="#/guide">Construire ma liste : les 5 étapes</a>' not in top(js, "viewVoeux"):
        bad.append("the Mes vœux link")
    if 'if (a === "guide") return await viewGuide();' not in js or 'guide: "voeux" };' not in js:
        bad.append("the route or its tab")
    if '"construire_ma_liste": ("app.js", "async function viewGuide(")' not in release:
        bad.append("the release guard")
    if "Sprint R7" not in readme or "redteam_guide" not in claude:
        bad.append("README / CLAUDE.md")
    return not bad, f"problems {bad[:3]}"


@check("GU5 entry points and docs: the home card before the four doors, the Mes vœux link, the route, the release guard, README, CLAUDE.md")
def gu5(c: Ctx):
    return entries_ok(c.js, c.release, c.readme, c.claude)


# ------------------------------------------------------------------ GU6 browser
BROWSER = r"""
const { chromium } = require('playwright');
const base = process.argv[2], cod = process.argv[3];
(async () => {
  const b = await chromium.launch(); const errs = [], o = {};
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, permissions: ["clipboard-read", "clipboard-write"] });
  const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
  const steps = async () => { await p.goto(base + "/#/guide"); await p.reload(); await p.waitForTimeout(3000);
    return p.evaluate(() => [...document.querySelectorAll(".guide-step .badge")].map((e) => e.textContent)); };
  o.s0 = await steps();
  o.layout = await p.evaluate(() => ({ noScroll: document.documentElement.scrollWidth <= window.innerWidth,
    small: [...document.querySelectorAll("#view a.btnlink, #view button")].filter((e) => e.getBoundingClientRect().height < 44).length }));
  await p.evaluate(() => localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", moyenne: 12.6, statut: "terminale" })));
  o.s1 = await steps();
  await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(3500);
  o.s2 = await steps();
  await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(3500);
  const add = await p.$("button:has-text('Ajouter à mes vœux')"); if (add) await add.click(); await p.waitForTimeout(500);
  o.s3 = await steps();
  await p.goto(base + "/#/voeux"); await p.waitForTimeout(4000);
  const copy = await p.$("#share-copy"); if (copy) await copy.click(); await p.waitForTimeout(500);
  o.s4 = await steps();
  process.stdout.write(JSON.stringify({ errs, o })); await b.close();
})();
"""


@check("GU6 browser: a student walks the five steps on a phone; each step turns Fait; no JS error, no horizontal scroll, 44 px controls")
def gu6(c: Ctx):
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
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".guide_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if not o["layout"]["noScroll"] or o["layout"]["small"]:
        bad.append(("layout", o["layout"]))
    walk = [o[f"s{i}"] for i in range(5)]
    if walk[0][0] != "À faire" or walk[1][0] != "Fait" or walk[2][1] != "Fait" or walk[3][2] != "Fait" \
            or walk[3][3] not in ("Fait", "À faire") or walk[4][4] != "Fait":
        bad.append(("the walk", walk))
    return not bad, f"walk {walk}; problems {bad[:3]}"


# ------------------------------------------------------------------ GU7 outside terminale
def reo_ok(js: str) -> tuple[bool, str]:
    cases = [{"raw": {"statut": "reorientation"}, "n": n, "lecture": "pending", "flags": {"vu": True, "partage": False}} for n in (0, 3)]
    got = run_node(js, PAGE_PROG, cases)
    if got is None:
        return True, "skipped (node not installed)"
    got.pop()
    bad = []
    for c, g in zip(cases, got):
        sec = next(s for s in g["G"]["steps"] if s["key"] == "securite")
        if sec["statut"] != "sans_objet" or sec["href"] != "#/reorientation" or 'href="#/reorientation"' not in g["html"]:
            bad.append((c["n"], sec))
        if "aucune zone n'est publiée" not in g["html"]:
            bad.append("the reason is not said")
    o = run_node(js, READ_PROG, {"lec": LEC})
    if o and o["reo"]["calls"]:
        bad.append(("a request outside terminale", o["reo"]["calls"]))
    return not bad, f"problems {bad[:3]}"


@check("GU7 outside terminale: the safety step is 'sans objet' and links 'Je me réoriente', with its reason, and nothing is read")
def gu7(c: Ctx):
    return reo_ok(c.js)


# ------------------------------------------------------------------ GU8 mutation test
MUTANTS = [
    ("the profile done without two different specialties", "!!raw.spe2 && raw.spe1 !== raw.spe2);", "!!raw.spe2);", "gu1"),
    ("a profile without a mention or an average done", "if (!MENTION_CODES.includes(raw.mention) && validMoyenne(raw.moyenne) === null) return false;", "", "gu1"),
    ("exploring done by default", "explorer: flags.vu || n > 0 ?", "explorer: true || n > 0 ?", "gu1"),
    ("an uncertain or absent safety counted as done", "lecture.securite_sure > 0 ? \"fait\" : \"a_faire\"", "\"fait\"", "gu1"),
    ("a reading in progress counted as done", 'lecture === null ? "lecture"', 'lecture === null ? "fait"', "gu1"),
    ("sharing asked with an empty list", 'partager: !n ? "en_attente" :', "partager:", "gu1"),
    ("the next step: the last one to do", 'const next = steps.find((x) => x.statut === "a_faire") || null;',
     'const next = [...steps].reverse().find((x) => x.statut === "a_faire") || null;', "gu1"),
    ("a step 'sans objet' not counted", 'x.statut === "fait" || x.statut === "sans_objet").length', 'x.statut === "fait").length', "gu1"),
    ("the progress counts the steps to do", 'aria-valuenow="${G.faites}"', 'aria-valuenow="${5 - G.faites}"', "gu2"),
    ("the profile line unescaped", 'profLine: prof ? profileLine(prof, prof.serie) : ""', 'profLine: prof ? `${prof.spe1} ${prof.academie}` : ""', "gu3"),
    ("the chance caveat dropped", "Des repères tirés des admis des campagnes 2022–2025, pas des chances d'admission. ", "", "gu2"),
    ("tutoiement", "Cherchez une formation par son nom", "Cherche une formation par ton nom", "gu2"),
    ("the map link dropped", '<a class="btnlink" href="#/carte">La carte</a>', "", "gu2"),
    ("no check mark", '${x.statut === "fait" ? ICONS.check : i + 1}', "${i + 1}", "gu2"),
    ("a request with an empty list", "if (!ready || reo || !ids.length) return;", "if (!ready || reo) return;", "gu3"),
    ("a request outside terminale", "if (!ready || reo || !ids.length) return;", "if (!ready || !ids.length) return;", "gu3"),
    ("the bar's reading not reused", "let d = profileBar.key === k && profileBar.data && profileBar.data.lecture ? voeuxLocal(profileBar.data, prof) : null;", "let d = null;", "gu3"),
    ("the bar's reading of another average reused", "profileBar.data.lecture ? voeuxLocal(profileBar.data, prof) : null;", "profileBar.data.lecture ? profileBar.data : null;", "gu3"),
    ("the list not read with the average", "d = voeuxLocal(await api(`/api/voeux?${k}`), prof);", "d = await api(`/api/voeux?${k}`);", "gu3"),
    ("no race guard", "  if ($view.dataset.rendered !== gmk) return;\n  draw(", "  draw(", "gu3"),
    ("one token per list, not per visit (Codex)", "const gmk = `guide:${++guideSeq}`;", "const gmk = `guide:${ids.join(\",\")}`;", "gu3"),
    ("completion announced with steps left (Codex)", ": G.faites === GUIDE_STEPS.length ? `<p class=\"small\">Toutes", ": true ? `<p class=\"small\">Toutes", "gu2"),
    ("a failed reading said as pending", "draw(d && d.lecture ? d.lecture : undefined);", "draw(d && d.lecture ? d.lecture : null);", "gu3"),
    ("the average sent with the reading", 'const k = vxQuery(ids, prof).toString();                               // the profile bar',
     'const k = vxQuery(ids, prof).toString() + "&moyenne=" + prof.moyenne;                               // the profile bar', "gu3"),
    ("the visit flag never set", '  store.set("guideVu", true);', "", "gu4"),
    ("the guide records an event", "  draw(null);\n", '  draw(null);\n  track("action", { a: "guide" });\n', "gu4"),
    ("the share flag only on copy", '() => { store.set("guidePartage", true); window.print(); }', "() => window.print()", "gu4"),
    ("the home card dropped", "  ${guideCard()}\n", "", "gu5"),
    ("the Mes vœux link dropped", '<p class="small no-print"><a href="#/guide">Construire ma liste : les 5 étapes</a></p>', "", "gu5"),
    ("outside terminale: a safety step to do", 'securite: reo ? "sans_objet"', 'securite: false ? "sans_objet"', "gu7"),
    ("outside terminale: Mes vœux instead of Je me réoriente", 'href: x.key === "securite" && reo ? "#/reorientation" : x.href', "href: x.href", "gu7"),
]


@check("GU8 mutation test: step rules, page, reading, privacy, entry points and outside-terminale bugs are each caught")
def gu8(c: Ctx):
    if not shutil.which("node"):
        return True, "skipped (node not installed)"
    runs = {"gu1": lambda js: states_ok(js)[0], "gu2": lambda js: page_ok(js)[0], "gu3": lambda js: reading_ok(js)[0],
            "gu4": lambda js: local_ok(js, c.analytics)[0], "gu5": lambda js: entries_ok(js, c.release, c.readme, c.claude)[0],
            "gu7": lambda js: reo_ok(js)[0]}
    missed = []
    for name, old, new, g in MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor {c.js.count(old)})")
            continue
        try:
            caught = not runs[g](c.js.replace(old, new, 1))
        except Exception:  # noqa: BLE001
            caught = True
        if not caught:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught; missed {missed}"


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
