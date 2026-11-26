"""Red team of lot 1, PR 11 (owner, 2026-11-26): one figure per question, kept in percent; a search card fits one phone screen.

    python scripts/redteam_unchiffre.py [--db data/suptracker.duckdb] [--real] [--browser]

The 2026-11-25 audit: « toujours trop de pourcentages voisins pour une même question » (4 testers of 4). Léa read 28 % official,
60,7 % « Pour votre profil », 39,7 % « Taux d'accès de ce bac » and 21,3 % « Propositions reçues » on one page; a bac techno
student read « Accès estimé pour votre série » 34 % beside the jury report's 31,2 % in Mes vœux; « Admis sous votre moyenne »
was 77,7–78,3 % on the search card and 12,6–89,2 % in Mes vœux; « Tous les candidats : 6 316 » (a last-called RANK) was read as a
count of 2 086 candidates. The owner kept the PERCENT as the figure (comparable across formation sizes, the very unit of
Parcoursup's « taux d'accès »): the counts it is computed from stay printed beside it, smaller. Now:

  UC1 Mes vœux, bac techno / pro (Node + static): ONE column for the student's bac: the report's line when published, else the
      estimated access the zone reads, labelled estimation; never both in a row; the rate column is the OFFICIAL rate for every bac
  UC2 twin (Node, real /api/voeux answers): Mes vœux's « Admis sous votre moyenne » / « Admis avec votre mention ou moins » =
      the search card's figure, the same printed text, for averages inside and at the edges of their band and with no average
  UC3 « Selon votre bac » opens on THE profile figure (Node + static): profileLead prints the same percent as L'essentiel's
      profileRateTile for every kind (report, similar formations, national, route), with its counts or its estimation label;
      the per-route table is folded under a summary naming its use (comparing), never removed; no figure = no lead, table shown
  UC4 call history (Node): each group's last-called rank says « rang »: never « <label> : <number> » read as a headcount
  UC5 search card (Node + static): the per-bac rates, the most represented line and the apprenticeship offers are folded in ONE
      <details> (carteMore), present in the DOM; the card draws none of them outside it; outside terminale no per-bac rate
  UC6 prévision (Node): the headline range under a published figure is folded (<details>), and the card opens no group
  UC7 shared list (Node + static): the bac techno / pro route rides the link (v=) and comes back with its label; an unknown route
      is dropped, a bac général never carries one; never the average; the page says its zones are read without the average
  UC8 browser (--browser, nightly): on an emulated Pixel 5, every result card of three searches x three profiles is at most the
      visible screen (window height minus the bottom tab bar); after « Rechercher » the count is at the top of the screen and
      said in the status line, the focus not moved; on a wide screen the page does not move; 0 JS error
  UC9 mutation test: every seeded return of an audit defect is caught by UC1-UC7
  UC10 wiring and docs: test file and CI duration, README section, CLAUDE.md rule, nightly suite
"""
from __future__ import annotations

import argparse
import copy
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

import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
STATIC = ROOT / "suptracker" / "static"
CHECKS = []

import redteam_chiffres as CH  # noqa: E402  (its Ctx, client and top)
import redteam_lecture as LE  # noqa: E402  (the reading twins' names)

top = CH.top


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx(CH.Ctx):
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        super().__init__(db, real, browser)
        self.css = (STATIC / "style.css").read_text()


STUBS = r"""
let META = { methodology: {}, fields: {} }, JV = null;
const tip = () => "";
const label = (f) => f;
"""
BASE = ("esc", "fmt", "pct", "ESTIM_DEF", "estimTag", "pc1", "pct1", "isNum", "rpLabel")


def node(js: str, names, body: str, data=None):
    exe = shutil.which("node")
    if not exe:
        return None
    seen, parts = set(), []
    for n in list(BASE) + list(names):
        if n not in seen:
            seen.add(n)
            parts.append(top(js, n))
    prog = STUBS + "\n".join(parts) + "\n" + body
    r = nodefile.run([exe, "-e", prog], input=json.dumps(data if data is not None else {}, default=float), capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-700:])
    return json.loads(r.stdout)


READ_STDIN = "const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"


def view_voeux(js: str) -> str:
    return top(js, "viewVoeux")


# ------------------------------------------------------------------ UC1
@check("UC1 Mes vœux, bac techno / pro: one column for the student's bac (report, else the estimate, labelled), never both; official rate column")
def uc1(c: Ctx):
    bad = []
    rep = {"taux": 31.2, "en_position": 26, "confirmes": 83, "session": "2025", "source": "voie", "libelle": "Msgn/ Mercatique"}
    cases = [{"status": "ok", "rapport": rep, "taux_acces_ens": 34.0},
             {"status": "ok", "rapport": None, "taux_acces_ens": 34.0, "rate_fragile": False},
             {"status": "ok", "rapport": None, "taux_acces_ens": 34.0, "rate_fragile": True},
             {"status": "ok", "rapport": None, "taux_acces_ens": None},
             {"status": "absente"}]
    o = node(c.js, ("voieFigure", "vxVoieFigure"), READ_STDIN + """
const prof = { serie: 'bt', voie: 'stmg_merc' };
process.stdout.write(JSON.stringify(D.map((v) => vxVoieFigure(v, prof))));""", cases)
    if o is None:
        return True, "skipped (node not installed)"
    a, b, f, n, x = o
    if not ("31,2" in a and "26 sur 83" in a and "34" not in a and "estimation" not in a):
        bad.append(("report line: published only", a[:160]))
    if not ("34" in b and "estimation" in b and "rapport public" not in b):
        bad.append(("no report: the estimate, labelled", b[:160]))
    if "peu de candidats" not in f:
        bad.append(("fragile estimate not said", f[:160]))
    if "34" in n or "estimation" in n:
        bad.append(("no figure at all", n[:120]))
    if x != "—":
        bad.append(("absent formation", x))
    v = view_voeux(c.js)
    if 'serie === "bg" ? v.taux_acces_ens : v.taux_acces_all' not in v:
        bad.append("the rate column is not the official rate for a bac techno / pro")
    if "Pour votre bac (cette formation)" not in v or "Votre bac dans le rapport du jury (cette formation)" in v:
        bad.append("the bac column header")
    tbl = v[v.index("const rows = d.voeux.map"): v.index("$view.innerHTML = `${head}\n  <section")]
    if "${rate}" in tbl:
        bad.append("the estimate's name still heads a column of the list")
    if "vxVoieCell(v, prof)" not in tbl:
        bad.append("the bac column is not vxVoieCell")
    return not bad, f"{len(cases)} rows read; problems {bad[:4]}"


# ------------------------------------------------------------------ UC2
TWIN_NAMES = tuple(LE.TWINS) + ("mentionShareOf", "mentionShareTxt", "mentionWho", "cartePosition", "cartePosFigure", "vxPos")
UC2_PROFILES = [
    ({"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab"}, [None, 12.0, 13.1, 13.9]),
    ({"serie": "bg", "spe1": "PC", "spe2": "SVT", "mention": "tb"}, [None, 16.0, 17.2]),
    ({"serie": "bt", "mention": "b"}, [None, 15.3]),
]


def uc2_answers(c: Ctx):
    def build():
        codes = [r[0] for r in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY hash(cod_aff_form)",
                                             [c.latest]).fetchall()]
        lists = [codes[i:i + 10] for i in range(0, min(len(codes), 40 if c.real else 20), 10)]
        out = []
        with CH.client(c.db) as (tc, _):
            for p, avgs in UC2_PROFILES:
                for ids in lists:
                    r = tc.get("/api/voeux", params={"ids": ",".join(ids), **p})
                    if r.status_code == 200:
                        out.append({"p": p, "avgs": avgs, "d": r.json()})
        return out
    return c.memo("uc2", build)


@check("UC2 twin: Mes vœux's « Admis sous votre moyenne » / « avec votre mention ou moins » = the search card's printed figure")
def uc2(c: Ctx):
    ans = uc2_answers(c)
    if not ans:
        return False, "no /api/voeux answer"
    o = node(c.js, TWIN_NAMES, READ_STDIN + """
const out = [];
for (const a of D) for (const m of a.avgs) {
  const p = { statut: 'terminale', ...a.p, moyenne: m };
  const { band, g } = lectureOf(p);
  const d = m === null ? a.d : voeuxLocal(a.d, p);
  for (const v of d.voeux) {
    if (v.status !== 'ok' || !v.lec) continue;
    const card = cartePosFigure(cartePosition(v.lec, v.taux_acces_ens, band, g), false, p.serie);
    const list = cartePosFigure(vxPos(v, m !== null), false, p.serie);
    out.push({ cod: v.cod_aff_form, m, serie: p.serie, card, list });
  }
}
process.stdout.write(JSON.stringify(out));""", ans)
    if o is None:
        return True, "skipped (node not installed)"
    diff = [x for x in o if x["card"] != x["list"]]
    avg = [x for x in o if x["m"] is not None]
    return not diff and len(avg) >= 5 and len(o) >= 10, f"{len(o)} rows read ({len(avg)} with an average); {len(diff)} differ {diff[:2]}"


# ------------------------------------------------------------------ UC3
PR_NAMES = ("PR_SOURCE", "profileRateTile", "profileLead")


@check("UC3 « Selon votre bac » opens on L'essentiel's profile figure; the per-route table folded under a named summary, never removed")
def uc3(c: Ctx):
    bad = []
    prs = [{"kind": "publie", "taux": 60.7, "what": "Maths & SES", "source": "rapport", "session": "2025", "recoupe": True, "en_position": 54, "confirmes": 89},
           {"kind": "estimation", "taux": 44.4, "what": "Maths & SES", "source": "semblables", "n_rapports": 7},
           {"kind": "estimation", "taux": 38.0, "what": "Maths & SES", "source": "national"},
           {"kind": "serie", "taux": 12.5, "what": "Bac technologique", "source": "voie", "fragile": True, "candidats": 14},
           {"kind": "aucun", "what": "vos deux spécialités", "why": "pas de ligne"}, None]
    o = node(c.js, PR_NAMES, READ_STDIN + "process.stdout.write(JSON.stringify(D.map((pr) => [profileLead(pr), profileRateTile(pr)])));", prs)
    if o is None:
        return True, "skipped (node not installed)"
    pctre = re.compile(r"\d+(?:,\d)?\s%")
    for pr, (lead, tile) in zip(prs, o):
        if pr is None or pr.get("taux") is None:
            if lead:
                bad.append(("a lead without a figure", pr and pr["kind"]))
            continue
        lv = pctre.findall(lead.replace(" ", " ").replace("\xa0", " "))
        tv = pctre.findall(tile.replace(" ", " ").replace("\xa0", " "))
        if not lv or not tv or lv[0] != tv[0]:
            bad.append(("lead and L'essentiel differ", pr["kind"], lv[:1], tv[:1]))
        if pr["source"] == "rapport" and "54 sur 89" not in lead:
            bad.append("the report's counts are not beside the percent")
        if pr["source"] in ("semblables", "national") and "estimation" not in lead:
            bad.append(("estimate not labelled", pr["source"]))
        if "Pour votre profil" not in lead or "L'essentiel" not in lead:
            bad.append("the lead does not say it is L'essentiel's figure")
    card = top(c.js, "doubletteCard")
    if not re.search(r"\$\{lead \? `<details class=\"more-card\"><summary>[^<]*comparer[^<]*</summary>\$\{voiesBlock\}</details>` : voiesBlock\}", card):
        bad.append("the per-route table is not folded under a summary naming its use when a lead is shown")
    if card.index("${lead}") > card.index("${own.html}"):
        bad.append("the lead is not first")
    if "${doubletteCard(d.doublettes, d.rapport, d.semblables, profileRate(d, bacProfile()))}" not in c.js:
        bad.append("the formation page does not hand profileRate to the card")
    return not bad, f"{len(prs)} profile figures; problems {bad[:4]}"


# ------------------------------------------------------------------ UC4
@check("UC4 call history: each group's last-called rank says « rang », never « label : number »")
def uc4(c: Ctx):
    rows = [{"session": "2025", "candidats": 2086, "classes": 2086, "places": 120, "profondeur": 1.0, "toute_la_liste": True,
             "groupes": [{"label": "Tous les candidats", "rang": 6316}]},
            {"session": "2024", "candidats": 1900, "classes": 1800, "places": 120, "profondeur": 0.4, "toute_la_liste": False,
             "groupes": [{"label": "Bacheliers généraux", "rang": 400}, {"label": "Bacheliers technologiques", "rang": 320}]}]
    o = node(c.js, ("APPEL_NOTE", "appelCard"), READ_STDIN + "process.stdout.write(JSON.stringify(appelCard(D)));", rows)
    if o is None:
        return True, "skipped (node not installed)"
    t = re.sub(r"<[^>]+>", "", o).replace(" ", " ").replace("\xa0", " ")
    bad = []
    for lab, n in (("Tous les candidats", "6 316"), ("Bacheliers généraux", "400"), ("Bacheliers technologiques", "320")):
        if f"{lab} : rang {n}" not in t:
            bad.append(f"{lab}: rank not said")
        if re.search(rf"{lab} : {n[0]}", t):
            bad.append(f"{lab}: a bare number")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ UC5
@check("UC5 search card: per-bac rates, most represented line and apprenticeship offers folded in ONE <details>, never removed")
def uc5(c: Ctx):
    bad = []
    card = top(c.js, "carteCard")
    for fn in ("carteBacs(", "carteMajo(", "appOffers("):
        if fn in card:
            bad.append(f"{fn} drawn outside the fold")
    if "${carteMore(f, ctx.reo)}" not in card:
        bad.append("the card does not draw carteMore")
    f1 = {"cod_aff_form": "1", "bacs": {"bg": {"taux": 41.2}, "bt": {"taux": 0.6, "estime": True}, "bp": {"masque": True}},
          "majo": {"libelle": "Maths & SES", "bac": "bg"}, "offres_app": [{"etablissement": "CFA <b>X</b>", "ville": "Lyon"}]}
    f2 = {"cod_aff_form": "2", "bacs": None, "majo": None, "offres_app": []}
    f3 = {"cod_aff_form": "3", "majo": None, "offres_app": []}            # details not loaded yet
    o = node(c.js, ("bacAccesHtml", "carteBacs", "carteMajo", "carteFiche", "appParcours", "appOffers", "carteMore"), READ_STDIN + """
const CARTE_DETAIL_KEYS = [];
process.stdout.write(JSON.stringify([carteMore(D[0], false), carteMore(D[0], true), carteMore(D[1], false), carteMore(D[2], false)]));""", [f1, f2, f3])
    if o is None:
        return True, "skipped (node not installed)"
    full, reo, empty, wait = o
    if not (full.startswith('<details class="cc-more">') and full.rstrip().endswith("</details>")):
        bad.append("not one <details>")
    for want in ("cbacs", "cmajo", "offer-list", "aussi en apprentissage", "Taux d'accès par bac"):
        if want not in full:
            bad.append(f"{want} missing from the fold")
    if "<b>X</b>" in full:
        bad.append("an offer's name unescaped")
    if "cbacs" in reo or "cmajo" in reo or "offer-list" not in reo:
        bad.append("outside terminale: no per-bac rate, the offers kept")
    if empty:
        bad.append("an empty fold drawn")
    if "chargement" not in wait:
        bad.append("the per-bac rates' loading line lost")
    if not re.search(r"@media \(max-width: 340px\) \{ \.cfigs \{ grid-template-columns: minmax\(0, 1fr\); \} \}", c.css):
        bad.append("the two profile figures are not side by side on a phone")
    return not bad, f"problems {bad[:5]}"


# ------------------------------------------------------------------ UC6
@check("UC6 prévision folded: the headline range under a published figure is a <details>; the card opens no group")
def uc6(c: Ctx):
    p = {"target": "2026", "last_session": "2025", "calibration": "2024", "holdout": "2025", "level": 0.8,
         "indicators": [{"indicator": "taux_acces_ens", "group": "acces", "kind": "taux", "lo": 8, "hi": 39.5, "last": 28, "coverage": 0.77, "fragile": True},
                        {"indicator": "acc_tot", "group": "volumes", "kind": "count", "lo": 50, "hi": 70, "last": 61, "coverage": 0.8}]}
    o = node(c.js, ("PV_GROUPS", "pvVal", "pvRange", "pvCov", "pvLine", "previsionCard"), READ_STDIN + """
process.stdout.write(JSON.stringify([pvLine(D, 'taux_acces_ens'), pvLine(D, 'acc_tot'), pvLine(D, 'nope'), previsionCard(D)]));""", p)
    if o is None:
        return True, "skipped (node not installed)"
    a, b, none, card = o
    bad = []
    for x in (a, b):
        if not (x.startswith('<details class="pv-fold') and "<summary>Prévision 2026</summary>" in x and x.endswith("</details>")):
            bad.append(("headline not folded", x[:80]))
    if "39,5" not in a or "moins fiable" not in a:
        bad.append("the range or its flag is gone from the fold")
    if none:
        bad.append("a line for an unknown indicator")
    if re.search(r"<details\s+open", card) or "<details open" in card:
        bad.append("a prévision group opens by itself")
    if "39,5" not in card:
        bad.append("the card lost a range")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ UC7
@check("UC7 shared list: the bac route rides the link and returns with its label; unknown route dropped; never the average; zones said read without it")
def uc7(c: Ctx):
    o = node(c.js, ("MENTION_CODES", "BANDS", "validMoyenne", "bandOf", "vxProfile", "REO_LABEL", "isReo", "SHARE_KEYS", "shareCodes", "shareProfile", "shareLink"),
             READ_STDIN + """
JV = D.jv; const voeux = { MAX: 10 };
global.location = { origin: 'https://x.fr', pathname: '/' };
const bt = vxProfile({ statut: 'terminale', serie: 'bt', mention: 'b', moyenne: 13.2, voie: 'stmg_merc', voie_label: 'STMG Mercatique' });
const l1 = shareLink(['1', '2'], bt); const back = shareProfile(l1.split('/liste/1,2/')[1]);
const bad = shareProfile('s=bt&m=b&v=zzz_nope'); const bg = shareProfile('s=bg&m=ab&a=MATHS&b=SES&v=stmg_merc');
const l2 = shareLink(['1'], vxProfile({ statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', moyenne: 12.4 }));
JV = null; const nojv = shareProfile('s=bt&m=b&v=zzz_nope');           // the vocabulary did not load: still never a route it cannot check
process.stdout.write(JSON.stringify({ l1, back, bad, bg, l2, nojv }));""",
             {"jv": {"specialties": [{"code": "MATHS"}, {"code": "SES"}], "voies": {"bt": [{"code": "stmg_merc", "label": "STMG Mercatique"}], "bp": []}}})
    if o is None:
        return True, "skipped (node not installed)"
    bad = []
    if "v=stmg_merc" not in o["l1"]:
        bad.append("the route is not in the link")
    if not o["back"] or o["back"].get("voie") != "stmg_merc" or o["back"].get("voie_label") != "STMG Mercatique":
        bad.append(("the route does not come back with its label", o["back"]))
    if o["back"] and o["back"].get("moyenne") is not None:
        bad.append("an average came back")
    if not o["bad"] or o["bad"].get("voie"):
        bad.append(("an unknown route kept (or the profile lost)", o["bad"]))
    if not o["nojv"] or o["nojv"].get("voie"):
        bad.append(("a route kept without the vocabulary to check it", o["nojv"]))
    if not o["bg"] or o["bg"].get("voie"):
        bad.append(("a bac général carries a route", o["bg"]))
    for link in (o["l1"], o["l2"]):
        if re.search(r"[?&/](?:g|moy|moyenne)=", link) or "13.2" in link or "12.4" in link:
            bad.append(("the average rides the link", link))
    vl = top(c.js, "viewListe")
    if "le lien ne contient jamais la moyenne" not in vl:
        bad.append("the shared list does not say its zones are read without the average")
    if "jamais la moyenne" not in top(c.js, "shareCard"):
        bad.append("the share card does not say the average stays out")
    return not bad, f"link {o['l1'][-40:]}; problems {bad[:4]}"


# ------------------------------------------------------------------ UC8 (browser)
BROWSER = r"""
const { chromium, devices } = require('playwright');
const base = process.argv[1];                        // run through nodefile: node -e's argv
const PROFILES = { none: null,
  bg: { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'b', moyenne: 14.6, academie: 'Lyon' },
  bt: { statut: 'terminale', serie: 'bt', mention: 'ab', voie: 'stmg_merc', voie_label: 'STMG Mercatique' } };
const QUERIES = ['licence economie', 'bts commerce', 'infirmier'];
(async () => {
  const b = await chromium.launch(); const errs = []; const cards = []; const jump = {};
  for (const [pk, prof] of Object.entries(PROFILES)) {
    const ctx = await b.newContext({ ...devices['Pixel 5'] });
    if (prof) await ctx.addInitScript((p) => localStorage.setItem('profile', JSON.stringify(p)), prof);
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(`${pk}: ${e.message}`));
    for (const q of QUERIES) {
      await p.goto(`${base}/#/s/${encodeURIComponent(q)}`);
      await p.waitForSelector('#view .result', { timeout: 60000 }).catch(() => {});
      await p.waitForFunction(() => !document.querySelector('#view .cbacs-wait'), null, { timeout: 60000 }).catch(() => {});
      await p.waitForTimeout(1500);
      const r = await p.evaluate(() => {
        const bar = document.querySelector('.tabbar, nav.bottom, #tabbar, .bottom-nav, .phone-tabs');
        const barH = bar && getComputedStyle(bar).position === 'fixed' ? bar.getBoundingClientRect().height : 0;
        return { screen: innerHeight - barH, h: [...document.querySelectorAll('#view .result')].slice(0, 12).map((c) => Math.round(c.getBoundingClientRect().height)) };
      });
      cards.push({ pk, q, ...r });
    }
    await ctx.close();
  }
  for (const [name, dev] of [['phone', devices['Pixel 5']], ['wide', { viewport: { width: 1280, height: 900 } }]]) {
    const ctx = await b.newContext({ ...dev }); const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(`${name}: ${e.message}`));
    await p.goto(base + '/#/carte'); await p.waitForSelector('#cs-q', { timeout: 60000 }); await p.waitForTimeout(3000);
    await p.fill('#cs-q', 'licence economie'); await p.focus('#cs-q'); await p.keyboard.press('Enter');
    await p.waitForFunction(() => /Résultats/.test((document.getElementById('sr-status') || {}).textContent || ''), null, { timeout: 60000 }).catch(() => {});
    await p.waitForTimeout(1500);
    jump[name] = await p.evaluate(() => ({ y: Math.round(scrollY), top: Math.round(document.getElementById('carte-count').getBoundingClientRect().top),
      st: document.getElementById('sr-status').textContent, active: document.activeElement && document.activeElement.id }));
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ errs, cards, jump })); await b.close();
})();
"""


@check("UC8 browser: every result card fits the visible phone screen; « Rechercher » goes down to the results, said, focus kept; wide screen still")
def uc8(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        # Codex (PR #121): through nodefile, run from the repository: require('playwright') resolves from the working directory
        # (a local node_modules too), never from a temporary directory
        r = nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=1500, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    n = 0
    for x in o["cards"]:
        n += len(x["h"])
        over = [h for h in x["h"] if h > x["screen"]]
        if over:
            bad.append((x["pk"], x["q"], x["screen"], over[:3]))
        if not x["h"]:
            bad.append((x["pk"], x["q"], "no card"))
    ph, wd = o["jump"].get("phone", {}), o["jump"].get("wide", {})
    if not (0 <= ph.get("top", -1) <= 80 and "Résultats" in ph.get("st", "") and ph.get("active") == "cs-q"):
        bad.append(("phone jump", ph))
    if wd.get("y") != 0 or "Résultats" not in wd.get("st", ""):
        bad.append(("wide screen moved or nothing said", wd))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad and n >= 40, f"{n} cards measured, highest {max((max(x['h'] or [0]) for x in o['cards']), default=0)} px; jump {ph}; problems {bad[:4]}"


# ------------------------------------------------------------------ UC9
MUTANTS = [
    ("UC1", "both figures for a bac techno", "  if (v.rapport || !isNum(v.taux_acces_ens)) return voieFigure(v.rapport, prof);",
     "  if (!isNum(v.taux_acces_ens)) return voieFigure(v.rapport, prof);\n  if (v.rapport) return voieFigure(v.rapport, prof) + pct1(v.taux_acces_ens);"),
    ("UC1", "the estimate unlabelled", "${pct1(v.taux_acces_ens)}${estimTag(`accès estimé pour votre série", "${pct1(v.taux_acces_ens)}${(`accès estimé pour votre série"),
    ("UC1", "the estimate back as the rate column", 'serie === "bg" ? v.taux_acces_ens : v.taux_acces_all) ? `${fmt(serie === "bg" ? v.taux_acces_ens : v.taux_acces_all)} %`',
     'v.taux_acces_ens) ? `${fmt(v.taux_acces_ens)} %`'),
    ("UC2", "Mes vœux prints the mention's bounds with an average", "  if (withAverage) {\n    const p = v.position_moyenne;",
     "  if (withAverage && false) {\n    const p = v.position_moyenne;"),
    ("UC2", "one hypothesis only", "return p ? { lo: Math.min(p.normale, p.uniforme), hi: Math.max(p.normale, p.uniforme), moyenne: true } : null;\n  }\n  if (v.bounds)",
     "return p ? { lo: p.normale, hi: p.normale, moyenne: true } : null;\n  }\n  if (v.bounds)"),
    ("UC3", "the lead shows another figure", "<strong class=\"pr-lead-v\">${pct1(pr.taux)}</strong>", "<strong class=\"pr-lead-v\">${pct1(pr.taux * 0.9)}</strong>"),
    ("UC3", "the lead forgets the report's counts", "<p class=\"muted small\">${esc(pr.what)} · ${PR_SOURCE[pr.source](pr)}. Le même",
     "<p class=\"muted small\">${esc(pr.what)}. Le même"),
    ("UC3", "the route table no longer folded", "${lead ? `<details class=\"more-card\"><summary>Les chiffres de chaque voie de bac, pour comparer</summary>${voiesBlock}</details>` : voiesBlock}",
     "${voiesBlock}"),
    ("UC4", "a bare rank", '${esc(g.label || "Groupe")} : <span class="nowrap">rang ${fmt(g.rang)}</span>', '${esc(g.label || "Groupe")} : ${fmt(g.rang)}'),
    ("UC5", "the per-bac rates back outside the fold", '<span class="muted small">officiel</span></div></div>',
     '<span class="muted small">officiel</span></div>${carteBacs(f)}</div>'),
    ("UC5", "the offers lost", "  const app = appOffers(f.offres_app);", '  const app = "";'),
    ("UC5", "per-bac rates outside terminale", '${reo ? "" : `${carteBacs(f)}${carteMajo(f)}`}', "${carteBacs(f)}${carteMajo(f)}"),
    ("UC6", "the prévision headline unfolded", '`<details class="pv-fold small"><summary>Prévision ${esc(p.target)}</summary>', '`<div class="small"><span>Prévision ${esc(p.target)}</span>'),
    ("UC6", "the first group opens", "${PV_GROUPS.map((g) => block(g, false)).join(\"\")}", "${PV_GROUPS.map((g, k) => block(g, k === 0)).join(\"\")}"),
    ("UC7", "the route left out of the link", '    else if (prof.voie && prof.voie !== "autre") q.set("v", prof.voie);', ""),
    ("UC7", "an unknown route kept", "  if (p.voie && !route) delete p.voie;", "  if (false) delete p.voie;"),
    ("UC7", "the notice gone", " Les zones sont lues avec la mention seule : le lien ne contient jamais la moyenne, elles peuvent donc différer de celles de l'élève.", ""),
]


@check("UC9 mutation test: every seeded return of an audit defect is caught by UC1-UC7")
def uc9(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("UC1", "UC2", "UC3", "UC4", "UC5", "UC6", "UC7") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    caught, missed = 0, []
    for target, name, old, new in MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor found {c.js.count(old)} times)")
            continue
        m = copy.copy(c)
        m.js = c.js.replace(old, new, 1)
        m._memo = c._memo
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


# ------------------------------------------------------------------ UC10
@check("UC10 wiring and docs: test file and its CI duration, README section, CLAUDE.md rule, nightly browser suite")
def uc10(c: Ctx):
    bad = []
    t = ROOT / "tests" / "test_unchiffre.py"
    if not t.exists() or "redteam_unchiffre" not in t.read_text():
        bad.append("tests/test_unchiffre.py")
    if '"tests/test_unchiffre.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("CI duration")
    if "## One figure per question, kept in percent (lot 1, PR 11" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**One figure per question, in percent (lot 1, PR 11" not in (ROOT.parent / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    if '"unchiffre": ("UC8",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
    src = Path(__file__).read_text()
    if 'nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}"]' not in src or src.count("cwd=str(ROOT))") < 1:
        bad.append("the browser program is not run through nodefile from the repository (Codex, PR #121)")
    return not bad, f"problems {bad}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
