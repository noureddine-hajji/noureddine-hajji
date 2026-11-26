"""Red team of audit PR 6 (owner, 2026-11-24): « Je me réoriente ou je reprends mes études », completed.

    python scripts/redteam_reprise.py [--db data/suptracker.duckdb] [--real] [--browser]

The audit of 2026-11-23 found the reorientation journey incomplete: outside terminale the search cards showed the rates per bac
and « Indiquez votre profil » instead of the estimated access outside terminale; nothing helped an adult (Mission locale, France
Travail, CEP, Transitions Pro, CPF); the « Je me réoriente » door sat below the first screen (841 px on a 768 px laptop, two
screens on a phone); and the page was the one under the readability bar.

  RP1 the card's figure (Python): the map layer's `reo` detail of every latest-campaign SIES formation = the reorientation red
      team's independent SQL reading (candidates and proposals outside terminale, the estimate, its cap); a detail key on both
      sides (carte.DETAIL_KEYS = app.js CARTE_DETAIL_KEYS); the card keys are list keys
  RP2 the card (Node): outside terminale the card shows « Accès estimé hors terminale » through reoCell (the same cell as the
      page and Mes vœux), never the rates per bac, the most represented line or « Indiquez votre profil »; « chargement… » before
      the details, the reason when there is no estimate, escaped; in terminale the card is unchanged; the page reads the status
  RP3 the adults' services (Python): every link is an official page READ by the suptracker-aides workflow (fetch_log status 200,
      its saved text titled as ADULTES_TITRES says), or a link such a page prints (`via`); https only; our words only (no amount,
      no age figure, vouvoiement, no chance, sentences <= 30 words); the help page carries them, /api/meta serves the same list,
      the reorientation page's folded card escapes them and drops a non-https link
  RP4 the home (Node): the hero names « Je me réoriente » in one LINK (never a second primary action), right after the main
      action; not repeated for a student already outside terminale; the door stays
  RP5 readability (Python): the reorientation page's own texts (method, no-zone sentence, intro, notes) and the adults' services:
      every sentence <= 30 words, Kandel-Moles >= 70; the phrases the reorientation red team requires are kept
  RP6 browser (--browser / --real): the hero link inside the first screen (1366x768 laptop, Pixel 5); a search card outside
      terminale shows the estimate = the layer's, without the rates per bac; the folded services open; the page's prose scores
      >= 70; no JS error, no horizontal scroll
  RP7 mutation test of RP1-RP5 and RP8 (mutants built in memory)
  RP8 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration, nightly browser suite
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
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import aide as AI  # noqa: E402
from suptracker import carte as CA  # noqa: E402
from suptracker import reorientation as RO  # noqa: E402
import redteam_langage as LA  # noqa: E402
import redteam_reorientation as RR  # noqa: E402
import redteam_visuel as VI  # noqa: E402
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
AIDES = ROOT / "data" / "aides"
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\'&'
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|vous serez admis|garanti|vos chances|promesse")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
AGE = re.compile(r"\b\d{1,2}\s*(?:à\s*\d{1,2}\s*)?ans\b|\d+\s*€|\beuros?\b")
M = {"RO": RO, "AI": AI, "CA": CA}


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
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.nightly = (ROOT / "scripts" / "browser_nightly.py").read_text()
        self.fetch_log = json.loads((AIDES / "fetch_log.json").read_text()) if (AIDES / "fetch_log.json").exists() else []
        self._rr = None
        self.layers = {}

    def truth(self) -> dict:
        if self._rr is None:
            self._rr = RR.Ctx(self.db, self.real)
        return self._rr.truth()


def node(prog: str):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-"], input=prog, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


# ---------------------------------------------------------------- RP1
@check("RP1 the card's figure: the layer's `reo` = the independent SQL reading on every latest formation; a detail key both sides")
def rp1(c: Ctx):
    bad = []
    RO_, CA_ = M["RO"], M["CA"]
    latest = c.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    truth = c.truth()
    got = RO_.latest(c.con)
    cods = [r[0] for r in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ?", [latest]).fetchall()]
    keys = ("candidats", "propositions", "acces_estime", "plafonne")
    n = 0
    for cod in cods:
        t, b = truth.get((cod, latest)), got.get(cod)
        if b is None or not RR.same(b, t, keys) or b.get("min_candidats") != 20 or set(b) != set(RO_.CARD_KEYS):
            bad.append((cod, b, t and {k: t[k] for k in keys}))
            if len(bad) > 3:
                break
        n += 1
    for row, exp in RR.EDGES:          # crafted rows (a capped estimate, the thresholds): the same block the card reads
        b = RO_.block(row)
        if (b["candidats"], b["propositions"], b["plafonne"]) != exp[:2] + (exp[3],) or (exp[2] is None) != (b["acces_estime"] is None) \
                or (exp[2] is not None and abs(b["acces_estime"] - min(100.0, exp[2])) > 0.051):
            bad.append(("crafted row", exp, {k: b[k] for k in keys}))
    if not set(RO_.CARD_KEYS) <= set(RO_.LIST_KEYS):
        bad.append("a card key the list does not carry")
    m = re.search(r"const CARTE_DETAIL_KEYS = \[([^\]]*)\]", c.js)
    page = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    if "reo" not in CA_.DETAIL_KEYS or list(CA_.DETAIL_KEYS) != page:
        bad.append(("detail keys", CA_.DETAIL_KEYS, page))
    # the layer itself carries the block (the cards read the layer, never another request)
    key = id(CA_)                       # the layer is built once per module (the mutation test swaps modules)
    if key not in c.layers:
        c.layers[key] = CA_._layer(c.con)[0]
    rows = {f["cod_aff_form"]: f for fs in c.layers[key].values() for f in fs if f.get("stats") is not False}
    miss = [k for k, f in rows.items() if f.get("reo") != got.get(k)]
    if miss:
        bad.append(("layer rows without their block", miss[:3]))
    return not bad, f"{n} formations of {latest} read; {len(rows)} layer rows; problems {bad[:3]}"


# ---------------------------------------------------------------- RP2
CARD_PROG = r"""
var STORE = {}; const store = { get: (k, x) => (k in STORE ? STORE[k] : x) }; const narrow = () => false; const searchPage = () => 40; const cartePage = () => 40;
const voeux = { has: () => false, get: () => [], MAX: 10 }; const ICONS = { places: '<svg class="ico" aria-hidden="true"></svg>' };
const pct1 = (x) => (x === null || x === undefined ? "—" : String(x).replace(".", ",") + " %"); const basket = { get: () => [] };
const recoBadge = () => ""; const tensionBadge = () => ""; var RECO = null; const rpLabel = (x) => x;
const H = "<img src=x onerror=alert(1)>";
const base = { cod_aff_form: "123", etablissement: H, formation: "<u>BTS</u>", ville: "<b>Lyon</b>", academie: "<i>Lyon</i>", statut: "public",
  contrat_etab: "Public", select_form: "formation sélective", stats: true, taux_acces_ens: 63.5, capa_fin: 24, lat: 45.7, lon: 4.8, offres_app: [],
  bacs: { bg: { taux: 70.2, source: "rapport" }, bt: { taux: 12, source: "estimation", fragile: false }, bp: { taux: 0, source: "estimation", fragile: true } },
  majo: { bac: "bg", libelle: "SES & HGGSP", acceptes: 9, exaequo: false } };
const reo = { candidats: 47, propositions: 23, acces_estime: 51.4, plafonne: false, min_candidats: 20 };
const ctx = (ok, r) => ({ ok, prof: {}, serie: "bg", chiffres: new Map(), lec: {}, band: "b", g: null, session: 2025, reo: r });
const out = {
  reo: carteCard({ ...base, reo }, ctx(false, true), false),
  capped: carteCard({ ...base, reo: { ...reo, acces_estime: 100, plafonne: true } }, ctx(false, true), false),
  few: carteCard({ ...base, reo: { ...reo, acces_estime: null, candidats: 7 } }, ctx(false, true), false),
  none: carteCard({ ...base, reo: null }, ctx(false, true), false),
  wait: carteCard({ ...base }, ctx(false, true), false),
  failed: carteCard({ ...base, reo: false }, ctx(false, true), false),
  term: carteCard({ ...base, reo }, ctx(false, false), false),
  offer: carteCard({ ...base, stats: false, reo: undefined }, ctx(false, true), false),
};
process.stdout.write(JSON.stringify(out));
"""


def card_prog(js: str) -> str:
    sec = js[js.index('// ---- Sprint "Carte"'):js.index("// ---- lot 2 (Claude design guidelines)")]
    extra = js[js.index("function voeuButton(cod, primary) {"):js.index("\nfunction bindVoeuButton(")] + "\n" \
        + js[js.index("function dblFigure(v) {"):js.index("\nfunction vxVoieCell(")]
    reo = "\n".join(LA.defn(js, n) for n in ("reoWhy", "reoCell"))
    return VI.base_defs(js) + "\n" + extra + "\n" + reo + "\n" + sec + CARD_PROG


@check("RP2 the card (Node): outside terminale the estimate through reoCell, never the rates per bac or « Indiquez votre profil »")
def rp2(c: Ctx):
    try:
        o = node(card_prog(c.js))
    except RuntimeError as e:
        return False, f"node: {e}"
    if o is None:
        return True, "skipped (node not installed)"
    bad = []
    txt = {k: re.sub(r"<[^>]+>", " ", h) for k, h in o.items()}
    for k in ("reo", "capped", "few", "none"):
        h = o[k]
        if "Accès estimé hors terminale" not in h or 'class="cbacs"' in h or "Indiquez votre profil" in h or 'class="cmajo' in h:
            bad.append((k, "estimate missing, or bac rates / majo / profile prompt shown"))
        if re.search(r"<(?:img|b|i|u)>|<img ", h):
            bad.append((k, "unescaped"))
    if "51,4 %" not in txt["reo"] or "estimation" not in txt["reo"] or "23 propositions pour 47 candidats hors terminale" not in txt["reo"]:
        bad.append("the estimate, its label or its counts")
    if "plafonnée à 100 %" not in txt["capped"]:
        bad.append("the cap is not said")
    if "moins de 20 candidats hors terminale (7)" not in txt["few"] or "pas de chiffres" not in txt["none"]:
        bad.append("no reason when there is no estimate")
    if "chargement" not in txt["wait"]:
        bad.append("no loading line before the details")
    # Codex (PR #116): when the details fail, the card says so, never « chargement… » forever
    if "chargement" in txt["failed"] or "indisponible" not in txt["failed"]:
        bad.append("a failed details load keeps « chargement »")
    if "if (f.reo === undefined) f.reo = false;" not in c.js:
        bad.append("the details failure path does not clear the estimate's loading line")
    if "Accès estimé hors terminale" in o["term"] or 'class="cbacs"' not in o["term"] or "Indiquez votre profil" not in o["term"]:
        bad.append("the terminale card changed")
    if "Accès estimé hors terminale" in o["offer"]:
        bad.append("an apprenticeship offer listed apart got the estimate")
    if not re.search(r"const ctx = \{[^\n]*reo: isReo\(store\.get\(\"profile\", null\)\)", c.js):
        bad.append("the search page does not read the status")
    for k, t in txt.items():
        if CHANCE.search(t):
            bad.append((k, "chance wording"))
    return not bad, f"{len(o)} cards; problems {bad[:4]}"


# ---------------------------------------------------------------- RP3
def _saved(url: str) -> tuple[dict | None, str, list]:
    row = next((r for r in M["fetch_log"] if r.get("url") == url), None)
    if not row or row.get("status") != 200 or not row.get("file"):
        return row, "", []
    p = AIDES / row["file"]
    lk = AIDES / row["file"].replace(".txt", ".links.json")
    return row, p.read_text() if p.exists() else "", json.loads(lk.read_text()) if lk.exists() else []


def sentences_of(t: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?:])\s+", t) if LA.words(s)]


@check("RP3 the adults' services: every link read on an official page (or printed by one), our words only, the same list everywhere")
def rp3(c: Ctx):
    A, bad = M["AI"], []
    M["fetch_log"] = c.fetch_log
    used = set()
    for s in A.ADULTES:
        for k in ("id", "titre", "pour", "comment", "liens"):
            if not s.get(k):
                bad.append((s.get("id"), f"no {k}"))
        for x in s.get("liens", ()):
            url = x.get("url", "")
            if not url.startswith("https://"):
                bad.append((s["id"], "not https", url))
                continue
            page = x.get("via") or url
            used.add(page)
            title = A.ADULTES_TITRES.get(page)
            row, text, links = _saved(page)
            if title is None or not text or title not in text.splitlines()[0]:
                bad.append((s["id"], "page not read or not titled as expected", page, row and row.get("status")))
                continue
            if x.get("via") and url not in {u for _t, u in links}:
                bad.append((s["id"], "a link the official page does not print", url))
        words = f"{s.get('titre', '')} {s.get('pour', '')} {s.get('comment', '')}"
        if AGE.search(words) or CHANCE.search(words) or FORMAL.search(words):
            bad.append((s["id"], "an amount, an age, a chance or tutoiement"))
        for sent in sentences_of(f"{s.get('pour', '')} {s.get('comment', '')}"):
            if len(LA.words(sent)) > 30:
                bad.append((s["id"], "a sentence over 30 words"))
    if set(A.ADULTES_TITRES) - used:
        bad.append(("a checked page no service uses", sorted(set(A.ADULTES_TITRES) - used)))
    hostile = A._adulte({"id": HOSTILE, "titre": HOSTILE, "pour": HOSTILE, "comment": HOSTILE, "liens": ({"texte": HOSTILE, "url": "https://x/" + HOSTILE},)})
    if "<img" in hostile or "onerror=alert(1)>" in hostile.replace("&lt;img", ""):
        bad.append("the help page's services are not escaped")
    page = A.page()
    # the help page's own services keep their class (red team LA7 counts `.aide-service`): the adults' sections have theirs
    if A.adultes_html() not in page or page.count('id="aide-adultes"') != 1 or page.count('class="aide-service"') != len(A.SERVICES) \
            or page.count('class="aide-adulte"') != len(A.ADULTES):
        bad.append("the help page does not carry the services")
    for s in A.ADULTES:
        for x in s["liens"]:
            if f'href="{A.esc(x["url"])}"' not in page:
                bad.append((s["id"], "a link missing from the help page"))
    if '"reprise": {"intro": AIDE.ADULTES_INTRO, "verifie": AIDE.ADULTES_CHECKED, "services": AIDE.ADULTES}' not in c.api_src:
        bad.append("/api/meta does not serve the list")
    # the reorientation page's folded card (Node): escaped, https only, nothing without the list
    prog = "\n".join(LA.defn(c.js, n) for n in ("esc", "reoAdultesCard")) + r"""
    const H = "<img src=x onerror=alert(1)>";
    var META = { reprise: { intro: H, verifie: H, services: [ { titre: H, pour: H, comment: H,
      liens: [ { texte: H, url: "https://www.service-public.gouv.fr/x" }, { texte: "bad", url: "javascript:alert(1)" }, { texte: "http", url: "http://x.fr/" } ] } ] } };
    const out = { card: reoAdultesCard() };
    META = null; out.none = reoAdultesCard(); META = { reprise: { services: [] } }; out.empty = reoAdultesCard();
    process.stdout.write(JSON.stringify(out));"""
    try:
        o = node(prog)
    except RuntimeError as e:
        return False, f"node: {e}"
    if o is not None:
        h = o["card"]
        if "<img" in h or "javascript:" in h or 'href="http://' in h or 'href="https://www.service-public.gouv.fr/x"' not in h or o["none"] or o["empty"]:
            bad.append(("the page's card", h[:200], o["none"], o["empty"]))
        if "<summary><h2>" not in h or "<details" not in h:
            bad.append("the card is not folded")
    if "${reoAdultesCard()}" not in RR.top(c.js, "viewReorientation"):
        bad.append("the reorientation page does not show the card")
    return not bad, f"{len(A.ADULTES)} services, {sum(len(s['liens']) for s in A.ADULTES)} links, {len(used)} official pages read; problems {bad[:4]}"


# ---------------------------------------------------------------- RP4
@check("RP4 the home: « Je me réoriente » in the hero as one link after the main action, not repeated outside terminale; the door stays")
def rp4(c: Ctx):
    bad = []
    home = RR.top(c.js, "viewHome")
    if "${homeCta()}${homeReo()}</section>" not in home:
        bad.append("the hero does not name it right after the main action")
    if '<a class="door" href="#/reorientation">' not in home:
        bad.append("the door is gone")
    prog = "\n".join(LA.defn(c.js, n) for n in ("isReo", "homeReo")) + r"""
    var P = null; const store = { get: () => P };
    const out = { none: homeReo() }; P = { serie: "bg" }; out.term = homeReo(); P = { statut: "reorientation" }; out.reo = homeReo();
    process.stdout.write(JSON.stringify(out));"""
    try:
        o = node(prog)
    except RuntimeError as e:
        return False, f"node: {e}"
    if o is not None:
        for k in ("none", "term"):
            h = o[k]
            if 'href="#/reorientation"' not in h or "btnlink" in h or "primary" in h or "<button" in h or "Je me réoriente ou je reprends mes études" not in h:
                bad.append((k, h))
        if o["reo"]:
            bad.append(("repeated outside terminale", o["reo"]))
    if ".hero-reo {" not in c.css:
        bad.append("no style for the line")
    return not bad, f"problems {bad[:3]}"


# ---------------------------------------------------------------- RP5
def reo_texts(js: str) -> str:
    """The prose the reorientation page prints: its method and no-zone sentences, the intro and notes of viewReorientation, and
    the adults' services (template expressions and markup dropped)."""
    out = []
    for name in ("REO_METHOD", "REO_NO_ZONE"):
        m = re.search(rf'^const {name} = "(.*)";$', js, re.M)
        out.append(m.group(1) if m else "")
    body = RR.top(js, "viewReorientation")
    for _off, t in LA.jstext.strings(body):
        v = LA.jstext.visible(t)
        if len(LA.words(v)) >= 6 and not v.startswith(("#", "/")):
            out.append(v)
    A = M["AI"]
    out.append(A.ADULTES_INTRO)
    out += [f"{s['titre']}. {s['pour']} {s['comment']}" for s in A.ADULTES]
    return "\n".join(out)


@check("RP5 readability: the reorientation page's texts and the adults' services, sentences <= 30 words, Kandel-Moles >= 70")
def rp5(c: Ctx):
    t = reo_texts(c.js)
    long = [s for s in LA.sentences(t) if len(LA.words(s)) > 30]
    km = LA.kandel_moles(t)
    bad = [("over 30 words", s[:90]) for s in long[:3]]
    if km < 70:
        bad.append(("Kandel-Moles", round(km, 1)))
    for need in ("pas un taux officiel ni une chance d'admission", "plafonné à 100 %", "aucune zone (sécurité, cible, ambitieux)"):
        if need not in t:
            bad.append(("missing", need))
    return not bad, f"Kandel-Moles {km:.1f}, {len(LA.sentences(t))} sentences; problems {bad[:4]}"


# ---------------------------------------------------------------- RP6
BROWSER = r"""
const { chromium, devices } = require('playwright');
(async () => {
  const base = process.argv[2], out = { errors: [] };
  const b = await chromium.launch();
  for (const [tag, opts] of [["laptop", { viewport: { width: 1366, height: 768 } }], ["phone", devices["Pixel 5"]]]) {
    const ctx = await b.newContext(opts); const p = await ctx.newPage();
    p.on("pageerror", (e) => out.errors.push(`${tag}: ${e.message}`));
    await p.goto(base + "/#/"); await p.waitForSelector(".hero-reo a");
    out[tag] = await p.evaluate(() => ({ bottom: document.querySelector(".hero-reo a").getBoundingClientRect().bottom, vh: innerHeight,
      sw: document.documentElement.scrollWidth, vw: innerWidth }));
    await p.evaluate(() => localStorage.setItem("profile", JSON.stringify({ statut: "reorientation" })));
    await p.goto(base + "/#/carte/BTS"); await p.waitForSelector(".cf-reo .cf-v", { timeout: 90000 });
    await p.waitForFunction(() => !document.querySelector(".cbacs-wait"), null, { timeout: 60000 }).catch(() => {});
    out[tag + "Card"] = await p.evaluate(() => { const c = document.querySelector(".carte-rc[data-pick]");
      return { cod: c.dataset.pick, txt: c.querySelector(".cf-reo").innerText, bacs: !!c.querySelector(".cbacs"), prompt: c.innerText.includes("Indiquez votre profil"),
        sw: document.documentElement.scrollWidth, vw: innerWidth }; });
    await p.goto(base + "/#/reorientation"); await p.waitForSelector("table.stack", { timeout: 90000 });
    await p.click(".reo-adultes > summary");
    out[tag + "Reo"] = await p.evaluate(() => ({ links: document.querySelectorAll(".reo-adultes a").length,
      text: [...document.querySelectorAll("#view h1, #view h2, #view p, #view li")].filter((e) => !e.closest("table")).map((e) => e.innerText).join("\n"),
      sw: document.documentElement.scrollWidth, vw: innerWidth }));
    await ctx.close();
  }
  await b.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


@check("RP6 browser: the hero link in the first screen, the card's estimate = the layer's without bac rates, the services open, prose >= 70")
def rp6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".reprise_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=900, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-800:]
    o, bad = json.loads(r.stdout), []
    got = M["RO"].latest(c.con)
    for tag in ("laptop", "phone"):
        h, card, reo = o[tag], o[tag + "Card"], o[tag + "Reo"]
        if h["bottom"] > h["vh"]:
            bad.append((tag, "hero link below the first screen", round(h["bottom"]), h["vh"]))
        b = got.get(card["cod"]) or {}
        want = f"{b.get('acces_estime'):.1f}".replace(".", ",") + " %" if b.get("acces_estime") is not None else "—"
        if want not in card["txt"] or card["bacs"] or card["prompt"]:
            bad.append((tag, "card", card["cod"], card["txt"][:80], want))
        if reo["links"] < sum(len(s["liens"]) for s in M["AI"].ADULTES):
            bad.append((tag, "services not all shown", reo["links"]))
        km = LA.kandel_moles(reo["text"])
        if km < 70:
            bad.append((tag, "page prose Kandel-Moles", round(km, 1)))
        for k in (h, card, reo):
            if k["sw"] > k["vw"]:
                bad.append((tag, "horizontal scroll"))
    if o["errors"]:
        bad.append(("JS errors", o["errors"][:2]))
    return not bad, f"laptop link at {o['laptop']['bottom']:.0f}/{o['laptop']['vh']} px, phone at {o['phone']['bottom']:.0f}/{o['phone']['vh']}; problems {bad[:4]}"


# ---------------------------------------------------------------- RP8
@check("RP8 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration, nightly browser suite")
def rp8(c: Ctx):
    bad = []
    if "## The reorientation journey, completed (audit PR 6" not in c.readme:
        bad.append("README section")
    if "Reorientation, completed (audit PR 6" not in c.claude or "redteam_reprise.py" not in c.claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_reprise.py").exists() or '"tests/test_reprise.py"' not in c.durations:
        bad.append("test file or CI duration")
    if not re.search(r'"reprise":\s*\("RP6",?\)', c.nightly):
        bad.append("nightly browser suite")
    return not bad, f"problems {bad}"


# ---------------------------------------------------------------- RP7 mutation test
PY_MUTANTS = [   # (module key, file, name, old, new)
    ("RO", "reorientation.py", "card block from the oldest campaign", 'blocks = _rows(con, "session IN (SELECT max(session) FROM core.formation_year)", [])',
     'blocks = _rows(con, "session IN (SELECT min(session) FROM core.formation_year)", [])'),
    ("RO", "reorientation.py", "estimate left out of the card", 'CARD_KEYS = ("candidats", "propositions", "acces_estime", "plafonne", "min_candidats")',
     'CARD_KEYS = ("candidats", "propositions", "plafonne", "min_candidats")'),
    ("RO", "reorientation.py", "cap dropped", "est, capped = round(min(100.0, raw), 1), raw > 100", "est, capped = round(raw, 1), raw > 100"),
    ("CA", "carte.py", "card detail dropped from the layer", '        x["reo"] = reo.get(x["cod_aff_form"])\n', ""),
    ("CA", "carte.py", "not a detail key", 'DETAIL_KEYS = ("bacs", "majo", "offres_app", "fiche", "reo")', 'DETAIL_KEYS = ("bacs", "majo", "offres_app", "fiche")'),
    ("AI", "aide.py", "a link never read", '"url": SP + "F2401"}', '"url": SP + "F2402"}'),
    ("AI", "aide.py", "a foreign link not printed by the page", '"url": "https://www.unml.info/le-reseau/annuaire/"', '"url": "https://www.example.com/annuaire/"'),
    ("AI", "aide.py", "a page titled otherwise", 'SP + "F14018": "Projet de transition professionnelle (PTP)"', 'SP + "F14018": "Projet de transition (PTP)"'),
    ("AI", "aide.py", "an age typed", '"pour": "Les jeunes, selon leur âge et leur situation : le site officiel le précise."',
     '"pour": "Les jeunes de 16 à 25 ans."'),
    ("AI", "aide.py", "the help page without the services", "{adultes_html()}\n", ""),
    ("AI", "aide.py", "a name unescaped", "<h3>{esc(s[\"titre\"])}</h3>", "<h3>{s[\"titre\"]}</h3>"),
    ("AI", "aide.py", "the adults' sections counted as the help page's services", '<section class="aide-adulte"', '<section class="aide-service"'),
    ("AI", "aide.py", "a long sentence", '"comment": "Votre expérience peut être reconnue par un diplôme ou par un titre professionnel."',
     '"comment": "Votre expérience peut être reconnue par un diplôme ou par un titre professionnel et cela vaut pour toute la vie et pour toutes les '
     'expériences que vous avez eues dans votre carrière ou dans vos activités bénévoles depuis toujours."'),
]
JS_MUTANTS = [
    ("estimate replaced by the official rate", "reoCell(f.reo && { ...f.reo, taux_acces_ens: f.taux_acces_ens })",
     "reoCell(f.reo && { ...f.reo, acces_estime: f.taux_acces_ens, taux_acces_ens: f.taux_acces_ens })"),
    ("bac rates kept outside terminale", '${ctx.reo ? "" : carteBacs(f)}', "${carteBacs(f)}"),
    ("profile prompt kept outside terminale", "  if (ctx.reo) return carteReo(f);\n", ""),
    ("no loading line", "if (f.reo === undefined) return '<p class=\"cbacs-wait small muted\">Accès estimé hors terminale : chargement…</p>';",
     "if (f.reo === undefined) return '';"),
    ("status not read", 'reo: isReo(store.get("profile", null)) };', "reo: false };"),
    ("loading forever when the details fail", " if (f.reo === undefined) f.reo = false; });", " });"),
    ("a failed load shown as loading", "  if (f.reo === false) return '<p class=\"small muted\">Accès estimé hors terminale : indisponible",
     "  if (f.reo === 1) return '<p class=\"small muted\">Accès estimé hors terminale : indisponible"),
    ("detail key missing in the page", 'const CARTE_DETAIL_KEYS = ["bacs", "majo", "offres_app", "fiche", "reo"];',
     'const CARTE_DETAIL_KEYS = ["bacs", "majo", "offres_app", "fiche"];'),
    ("hero line dropped", "${homeCta()}${homeReo()}</section>", "${homeCta()}</section>"),
    ("hero line as a primary button", 'Vous n\'êtes plus en terminale ? <a href="#/reorientation">',
     'Vous n\'êtes plus en terminale ? <a class="btnlink primary" href="#/reorientation">'),
    ("hero line repeated outside terminale", '  if (isReo(store.get("profile", null))) return "";\n  return `<p class="hero-reo', '  return `<p class="hero-reo'),
    ("services card unescaped", "<strong>${esc(s.titre)}</strong>", "<strong>${s.titre}</strong>"),
    ("services card keeps any link", '.filter((x) => /^https:\\/\\//.test(String(x.url || "")))', ""),
    ("services card not folded", '<details class="card reo-adultes"><summary><h2>', '<div class="card reo-adultes"><div><h2>'),
    ("services card not shown", "\n    ${reoAdultesCard()}", ""),
    ("method back in one long sentence", "On le multiplie par la part des candidats hors terminale qui ont reçu une proposition, puis on le divise par la même part pour tous les candidats.",
     "On le multiplie par la part des candidats hors terminale qui ont reçu une proposition, puis on le divise par la même part pour tous les candidats qui ont "
     "formulé au moins un vœu dans la formation, en phase principale comme en phase complémentaire, sans exception."),
]
TEXT_MUTANTS = [("api_src", "the list not served", '"reprise": {"intro": AIDE.ADULTES_INTRO', '"reprisex": {"intro": AIDE.ADULTES_INTRO'),
                ("readme", "README section gone", "## The reorientation journey, completed (audit PR 6", "## Reorientation"),
                ("nightly", "nightly suite entry gone", '"reprise": ("RP6",)', '"reprisex": ("RP6",)')]


def mutated(key: str, file: str, old: str, new: str):
    path = ROOT / "suptracker" / file
    src = path.read_text()
    if src.count(old) != 1:
        return None
    m = types.ModuleType(f"suptracker._mut_{key}")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("RP7 mutation test: card figure, card, services, home, readability and wiring bugs are each caught")
def rp7(c: Ctx):
    fns = [rp1, rp2, rp3, rp4, rp5, rp8]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    for key, file, name, old, new in PY_MUTANTS:
        m = mutated(key, file, old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)")
            continue
        saved, M[key] = M[key], m
        if key == "CA":
            m._LAYER.clear()
        try:
            if not caught():
                missed.append(name)
        finally:
            M[key] = saved
            sys.modules.pop(f"suptracker._mut_{key}", None)
    for name, old, new in JS_MUTANTS:
        src = c.js
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone or not unique: {src.count(old)})")
            continue
        c.js = src.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = src
    for attr, name, old, new in TEXT_MUTANTS:
        src = getattr(c, attr)
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone)")
            continue
        setattr(c, attr, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, attr, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS) + len(TEXT_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser or real)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
    c.con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
