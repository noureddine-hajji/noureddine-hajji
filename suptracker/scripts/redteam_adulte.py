"""Red team of lot 1, PR 12 (owner, 2026-11-26): the path of an adult who goes back to studies, finished.

    python scripts/redteam_adulte.py [--db data/suptracker.duckdb] [--real] [--browser]

The 2026-11-25 audit's adult tester (Sarah, an aide-soignante who wants to become a nurse) found, outside terminale:
« Selon votre bac » (bac général 47,2 %) before the block that concerns her, last of a fold; an IFSI absent from the 2026
map offered with no warning by the search and its page (only Mes vœux said it); « formation continue : 9 000 € » without
saying whom it concerns; aids for lycéens in the tiles; nothing on the continuing-education route into an IFSI; « 783
propositions pour 4 836 candidats (16 %) » beside the 22 % estimate; a help page and a share card written for lycéens. Now:

  AD1 « Y entrer » outside terminale opens on the estimate (reoCard, before « Selon votre bac »), with the IFSI route; in
      terminale both stay folded in « Plus de chiffres sur l'admission »; the card leads with the estimate, its counts under
      it as what it is computed from; L'essentiel's tile points to it
  AD2 absent from the latest map (re-derived in SQL): /api/carte/absentes = the latest campaign's codes with no row in the
      latest cartographie session, sorted, no parameter, public cache, no audience event; /api/formation's `carte` = the same
      rule as « Avant de confirmer » (liste.presence), None without a map (never « absente » by default)
  AD3 the page (Node): the search card's badge and the formation page's warning say « vérifiez … qu'elle existe toujours »,
      never « fermée », escaped; no badge for a code on the map or before the list is loaded
  AD4 fees « formation continue » (Node): the note shows when a fee line names it, never otherwise; our words only: no
      amount, no age, no condition beyond « pas les élèves de terminale »; sentences <= 30 words; vouvoiement; help link
  AD5 the IFSI route (aides.r_ifsi_fpc): the official page's own sentence, verbatim, on one line; a changed page = no item,
      said in the audit; only IFSI formations carry it; the card quotes it escaped, links parcoursup.gouv.fr only
  AD6 outside terminale (Node): the two aids tied to the lycée and the year's bac are folded, never removed (in terminale
      they stay in the tiles); the share card names a relative or adviser, not « votre professeur principal »
  AD7 browser (--browser, nightly): real data, a reorientation profile: an IFSI absent from the map warned on its page and
      badged in the search; « Y entrer » order; the help page opens on the adults' services; a terminale profile keeps the
      old order; 0 JS error
  AD8 mutation test: every seeded return of an audit defect is caught by AD1-AD6
  AD9 wiring and docs: test file and CI duration, README section, CLAUDE.md rule, nightly suite, cache policy
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

import redteam_chiffres as CH  # noqa: E402  (Ctx, client, top)
import redteam_unchiffre as UC  # noqa: E402  (the Node runner)

top = CH.top
HOSTILE = '<img src=x onerror="alert(1)">'
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx(CH.Ctx):
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        super().__init__(db, real, browser)
        self.liste = (ROOT / "suptracker" / "liste.py").read_text()
        self.aides_src = (ROOT / "suptracker" / "aides.py").read_text()


def node(js, names, body, data=None):
    return UC.node(js, names, UC.READ_STDIN + body, data)


# ------------------------------------------------------------------ AD1
@check("AD1 « Y entrer » outside terminale opens on the estimate, then « Selon votre bac »; folded in terminale; the card leads with the estimate")
def ad1(c: Ctx):
    bad = []
    vf = top(c.js, "viewFormation")
    if 'const reoFirst = isReo(store.get("profile", null)) && !!d.reorientation;' not in vf:
        bad.append("reoFirst is not the stored profile outside terminale")
    i_first, i_bac = vf.find("${reoFirst ? reoCard(d.reorientation) + ifsiFpcCard(d.aides) : \"\"}"), vf.find("${doubletteCard(d.doublettes")
    if i_first < 0 or i_bac < 0 or i_first > i_bac:
        bad.append("the estimate does not come before « Selon votre bac » outside terminale")
    more = vf[vf.find("Plus de chiffres sur l'admission"):]
    more = more[:more.find("</details>")]
    if '${reoFirst ? "" : reoCard(d.reorientation) + ifsiFpcCard(d.aides)}' not in more:
        bad.append("in terminale the cards are not folded where they were")
    b = {"session": "2025", "candidats": 4836, "propositions": 783, "taux_proposition": 16.2, "taux_proposition_tous": 22.0,
         "acces_estime": 19.6, "plafonne": False}
    o = node(c.js, ("REO_METHOD", "REO_NO_ZONE", "reoWhy", "reoCell", "reoCard"), "process.stdout.write(JSON.stringify(reoCard(D)));", b)
    if o is None:
        return True, "skipped (node not installed)"
    t = re.sub(r"<[^>]+>", " ", o)
    lead, calc = t.find("Accès estimé hors terminale"), t.find("Calculé à partir des effectifs publiés")
    if lead < 0 or calc < 0 or lead > calc or "19,6" not in t[lead:calc]:
        bad.append("the card does not lead with the estimate, its counts under it")
    if "calcul en tête de l'onglet « Y entrer »" not in top(c.js, "accesTile"):
        bad.append("L'essentiel's tile still points to the fold")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AD2
@check("AD2 absent from the latest map, re-derived in SQL: /api/carte/absentes and /api/formation's carte; no parameter, public cache, no event")
def ad2(c: Ctx):
    bad = []
    con = c.con
    has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'cartographie'").fetchone()[0]
    ks = con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0] if has else None
    want = sorted(set(r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ?""", [c.latest]).fetchall())
                  - set(r[0] for r in con.execute("SELECT cod_aff_form FROM core.cartographie WHERE carto_session = ?", [ks]).fetchall())) if ks else []
    from suptracker import analytics as A
    events = []
    with CH.client(c.db) as (tc, api):
        A.record = lambda *a, **k: events.append(a) or "ok"
        r = tc.get("/api/carte/absentes")
        r2 = tc.get("/api/carte/absentes", params={"academie": "Lyon", "x": HOSTILE})
        got = r.json()
        if r.status_code != 200 or got.get("codes") != want or got.get("carte_session") != ks or got.get("session") != c.latest:
            bad.append(("absentes", r.status_code, len(got.get("codes") or []), len(want)))
        if r2.json() != got:
            bad.append("a parameter changes the answer")
        cc = r.headers.get("cache-control", "")
        if "public" not in cc or "no-store" in cc:
            bad.append(("cache", cc))
        sample = (want[:3] + [x for x in [r[0] for r in con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY hash(cod_aff_form) LIMIT 4", [c.latest]).fetchall()] if x not in want][:3])
        for cod in sample:
            f = tc.get(f"/api/formation/{cod}").json()
            exp = None if ks is None else (cod not in want)
            if (f.get("carte") or {}).get("dans") is not exp or (f.get("carte") or {}).get("session") != ks:
                bad.append(("formation carte", cod, f.get("carte"), exp))
    if events:
        bad.append(("audience events", events[:2]))
    if "never « absente » by default" not in c.liste or "if session is None:\n        return None" not in c.liste:
        bad.append("presence without a map is not None")
    if (ROOT / "suptracker" / "cache.py").read_text().count('(r"/api/carte/absentes", PUBLIC') != 1:
        bad.append("no cache policy line")
    return not bad and (ks is None or len(want) > 0), f"{len(want)} codes absent from the {ks} map; problems {bad[:4]}"


# ------------------------------------------------------------------ AD3
@check("AD3 the page: the search badge and the formation warning say « vérifiez qu'elle existe toujours », never « fermée », escaped")
def ad3(c: Ctx):
    o = node(c.js, ("absenteText", "absBadge"), """
let ABS = null;
const before = absBadge('1');
ABS = { session: D.s, codes: new Set(['1']) };
process.stdout.write(JSON.stringify([before, absBadge('1'), absBadge('2'), absenteText(D.s)]));""", {"s": "2026" + HOSTILE})
    if o is None:
        return True, "skipped (node not installed)"
    before, on, off, txt = o
    bad = []
    if before or off:
        bad.append("a badge without the list, or for a code on the map")
    if "absente de la carte" not in on or "<img" in on or "existe toujours" not in on:
        bad.append(("badge", on[:160]))
    if re.search(r"(?i)ferm[ée]", txt + on) or "vérifiez sur Parcoursup qu'elle existe toujours" not in txt:
        bad.append(("wording", txt))
    vf = top(c.js, "viewFormation")
    if '${d.carte && d.carte.dans === false && d.carte.session ? `<div class="warn">${ICONS.warn} ${esc(absenteText(d.carte.session))}</div>` : ""}' not in vf:
        bad.append("the formation page does not warn")
    if "+ absBadge(f.cod_aff_form)" not in top(c.js, "carteCard") or "absLoad()]" not in c.js:
        bad.append("the search card does not draw or load the badge")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AD4
@check("AD4 fees « formation continue »: the note only when a line names it; our words, no amount, age or condition; <= 30 words; help link")
def ad4(c: Ctx):
    def v(lines):
        return {"frais": {"titre": "Frais de scolarité", "lignes": lines, "cvec": False}, "mensuel": None, "annuel": None, "loyer": None,
                "mois": 10, "studio_m2": 20, "postes": [], "crous": []}
    fc = [{"rubrique": "Par année", "texte": "170 €"}, {"rubrique": "Frais pour les inscrits de la formation continue", "texte": "9 000 € " + HOSTILE}]
    plain = [{"rubrique": "Par année", "texte": "170 €"}]
    try:
        o = node(c.js, ("FC_RE", "FC_NOTE", "fcNote"), "process.stdout.write(JSON.stringify(D.map((x) => fcNote(x.frais))));", [v(fc), v(plain), {"frais": None}])
    except Exception as e:  # noqa: BLE001
        return False, f"the note does not run: {str(e)[:300]}"
    if o is None:
        return True, "skipped (node not installed)"
    if o[2]:
        return False, "a note without fees"
    if "${fcNote(fr)}" not in top(c.js, "coutCard"):
        return False, "the cost card does not draw the note"
    a, b = o[0], o[1]
    bad = []
    if 'class="small fc-note"' not in a or 'href="#/info/aide"' not in a:
        bad.append(("no note under a formation-continue fee", a[:200]))
    if "fc-note" in b:
        bad.append("a note without such a fee")
    note = re.search(r'const FC_NOTE = "([^"]+)";', c.js)
    t = note.group(1) if note else ""
    if not t or re.search(r"\d|€|\bans?\b|âgé|moins de|plus de", t):
        bad.append(("the note carries an amount, an age or a condition", t[:120]))
    if any(len(s.split()) > 30 for s in re.split(r"(?<=[.!?])\s+", t) if s):
        bad.append("a sentence over 30 words")
    if TU.search(t):
        bad.append("tutoiement")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AD5
SENT = ("Les professionnels en particulier les détenteurs du diplôme d'aide-soignant qui sont en exercice, relèvent du recrutement "
        "de la formation professionnelle continue et font l'objet de modalités d'admission spécifiques, hors Parcoursup.")


@check("AD5 the IFSI route: the official page's own sentence verbatim; a changed page = no item, said; IFSI only; quoted escaped, parcoursup.gouv.fr only")
def ad5(c: Ctx):
    import importlib
    ai = importlib.import_module("suptracker.aides")
    bad = []
    page = f"Les formations en soins infirmiers\n{SENT} Autre phrase.\nPied de page"
    got = ai.r_ifsi_fpc(page, [])
    if not got or got["texte"] != SENT or not got["source"].startswith("https://www.parcoursup.gouv.fr/"):
        bad.append(("verbatim", got))
    if ai.r_ifsi_fpc("Les professionnels relèvent de la formation professionnelle continue.\nhors Parcoursup.", []) is not None:
        bad.append("a sentence across two lines is glued")
    if ai.r_ifsi_fpc("Une page sans la phrase.", []) is not None:
        bad.append("a changed page still yields an item")
    if "ifsi_fpc" not in ai.RULES or ai.PAGES.get("ifsi_fpc", "").split("/")[2] != "www.parcoursup.gouv.fr":
        bad.append("rule or page not registered")
    if 'out["ifsi_fpc"] = A.get("ifsi_fpc") if fili == "IFSI" else None' not in c.aides_src:
        bad.append("not limited to IFSI formations")
    o = node(c.js, ("ifsiFpcCard",), "process.stdout.write(JSON.stringify(D.map((a) => ifsiFpcCard(a))));",
             [{"ifsi_fpc": {"texte": SENT + HOSTILE, "source": ai.PAGES["ifsi_fpc"]}},
              {"ifsi_fpc": {"texte": SENT, "source": "https://evil.example/x"}}, {"ifsi_fpc": None}, None])
    if o is None:
        return True, "skipped (node not installed)"
    ok, evil, none1, none2 = o
    if "<img" in ok or "hors Parcoursup" not in ok or 'href="https://www.parcoursup.gouv.fr/' not in ok or "fait foi" not in ok:
        bad.append(("card", ok[:200]))
    if evil or none1 or none2:
        bad.append("a card from another host or without the item")
    req = json.loads((ROOT / "data" / "aides" / "request.json").read_text())["urls"]
    if ai.PAGES["ifsi_fpc"] not in req:
        bad.append("the page is not requested from the workflow")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AD6
@check("AD6 outside terminale: lycée aids folded (never removed), share card for a relative or adviser; in terminale unchanged")
def ad6(c: Ctx):
    def real_aides():
        cod = c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND fili = 'Licence' ORDER BY hash(cod_aff_form) LIMIT 1""",
                            [c.latest]).fetchone()
        cod = cod or c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? LIMIT 1", [c.latest]).fetchone()
        with CH.client(c.db) as (tc, _):
            f = tc.get(f"/api/formation/{cod[0]}").json()
        return {"a": f.get("aides"), "v": f.get("vie")}
    data = c.memo("ad6", real_aides)
    if not data["a"]:
        return True, "skipped (no aids read on this warehouse)"
    data = {**data, "a": {**data["a"], "merite": data["a"].get("merite") or {"par_mois": 100}, "mobilite": data["a"].get("mobilite") or {"montant": 500}}}
    names = ("REO_LABEL", "isReo", "bacProfile", "euros", "eurosRange", "euroMois", "aidesHint", "aidesCard", "shareLink", "shareCard")
    body = """
const voeux = { MAX: 10 }; const STORE = {}; const store = { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v; } };
global.location = { origin: 'https://x.fr', pathname: '/' };
const out = {};
STORE.profile = { statut: 'reorientation' }; out.reo = aidesCard(D.a, D.v); out.shareReo = shareCard(['1'], false);
STORE.profile = { statut: 'terminale', serie: 'bg' }; out.term = aidesCard(D.a, D.v); out.shareTerm = shareCard(['1'], false);
process.stdout.write(JSON.stringify(out));"""
    try:
        o = node(c.js, names, body, data)
    except Exception as e:  # noqa: BLE001
        return False, f"does not run: {str(e)[:500]}"
    if o is None:
        return True, "skipped (node not installed)"
    bad = []
    grid = lambda h: h.split("</div>\n  </div>")[0] if "</div>\n  </div>" in h else h  # noqa: E731
    reo_fold = re.search(r'<details class="more-card"><summary>Aides liées au lycée[^<]*</summary>(.*?)</details>', o["reo"], re.S)
    if not reo_fold or "Aide au mérite" not in reo_fold.group(1) or "Aide à la mobilité Parcoursup" not in reo_fold.group(1):
        bad.append("outside terminale the lycée aids are not folded (or lost)")
    if o["reo"].count("Aide au mérite") != 1:
        bad.append("outside terminale the mérite tile is also in the grid")
    if "Aides liées au lycée" in o["term"] or "Aide au mérite" not in o["term"]:
        bad.append("in terminale the tiles changed")
    if "professeur principal" in o["shareReo"] or "conseiller" not in o["shareReo"] or "professeur principal" not in o["shareTerm"]:
        bad.append("share card wording by situation")
    if "aideAdultesFirst()" not in top(c.js, "viewInfo") or 'if (slug === "aide" && isReo(store.get("profile", null)))' not in top(c.js, "viewInfo"):
        bad.append("the help page is not reordered outside terminale")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ AD7 (browser)
BROWSER = r"""
const { chromium, devices } = require('playwright');
const [base, absent] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [k, prof] of [['reo', { statut: 'reorientation', academie: 'Reims' }], ['term', { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SVT', mention: 'b' }]]) {
    const ctx = await b.newContext({ ...devices['Pixel 5'] });
    await ctx.addInitScript((p) => localStorage.setItem('profile', JSON.stringify(p)), prof);
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(`${k}: ${e.message}`));
    await p.goto(`${base}/#/f/${absent}`); await p.waitForSelector('.summary', { timeout: 60000 }); await p.waitForTimeout(2500);
    out[k] = await p.evaluate(() => {
      const panel = document.querySelector('#tab-admission, [id$="admission"][role="tabpanel"]') || document;
      const heads = [...panel.querySelectorAll('h2')].map((h) => h.textContent);
      const folded = (re) => { const h = [...panel.querySelectorAll('h2')].find((x) => re.test(x.textContent)); return !!(h && h.closest('details.more-card')); };
      return { warn: [...document.querySelectorAll('.warn')].some((w) => /existe toujours/.test(w.textContent)),
        reo: heads.findIndex((h) => /plus en terminale/.test(h)), bac: heads.findIndex((h) => /Selon votre bac/.test(h)), reoFolded: folded(/plus en terminale/) };
    });
    if (k === 'reo') {
      await p.goto(`${base}/#/info/aide`); await p.waitForSelector('article.legal h2', { timeout: 60000 }); await p.waitForTimeout(800);
      out.aide = await p.evaluate(() => [...document.querySelectorAll('article.legal h2')].map((h) => h.textContent).slice(0, 2));
      await p.goto(`${base}/#/carte`); await p.waitForSelector('#cs-q', { timeout: 60000 });
      await p.fill('#cs-q', ''); await p.waitForTimeout(500);
      await p.goto(`${base}/#/s/${encodeURIComponent(absent)}`);
      await p.waitForSelector('#view .result', { timeout: 60000 }).catch(() => {}); await p.waitForTimeout(3000);
      out.badge = await p.evaluate((cod) => { const r = [...document.querySelectorAll('#view .result')].find((x) => x.dataset.pick === cod);
        return r ? [...r.querySelectorAll('.badge')].some((x) => /absente de la carte/.test(x.textContent)) : null; }, absent);
    }
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""


@check("AD7 browser: absent IFSI warned and badged, « Y entrer » order by situation, help page adults first; 0 JS error")
def ad7(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    ks = c.con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0]
    row = c.con.execute("""SELECT f.cod_aff_form FROM core.formation_year f WHERE f.session = ? AND f.fili = 'IFSI'
        AND NOT EXISTS (SELECT 1 FROM core.cartographie k WHERE k.cod_aff_form = f.cod_aff_form AND k.carto_session = ?)
        AND EXISTS (SELECT 1 FROM mart.reorientation r WHERE r.cod_aff_form = f.cod_aff_form) ORDER BY 1 LIMIT 1""", [c.latest, ks]).fetchone() \
        if c.con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'reorientation'").fetchone()[0] else None
    if not row:
        row = c.con.execute("""SELECT f.cod_aff_form FROM core.formation_year f WHERE f.session = ? AND f.fili = 'IFSI'
            AND NOT EXISTS (SELECT 1 FROM core.cartographie k WHERE k.cod_aff_form = f.cod_aff_form AND k.carto_session = ?) ORDER BY 1 LIMIT 1""", [c.latest, ks]).fetchone()
    if not row:
        return True, "skipped (no IFSI absent from the latest map)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tmp, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        script = Path(tmp) / "ad7.js"
        script.write_text(BROWSER)
        r = subprocess.run([exe, str(script), f"http://127.0.0.1:{port}", row[0]], capture_output=True, text=True, timeout=900)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    x, bad = o["out"], []
    reo, term = x.get("reo", {}), x.get("term", {})
    if not reo.get("warn") or not term.get("warn"):
        bad.append("no warning on the page")
    if not (0 <= reo.get("reo", -1) < reo.get("bac", -1)) or reo.get("reoFolded"):
        bad.append(("reorientation order", reo))
    if term.get("reo", -1) >= 0 and not term.get("reoFolded"):
        bad.append(("terminale: the card left its fold", term))
    if x.get("badge") is not True:
        bad.append(("search badge", x.get("badge")))
    if not x.get("aide") or not re.search(r"reprenez", x["aide"][0]):
        bad.append(("help page order", x.get("aide")))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad, f"formation {row[0]}; {x}; problems {bad[:4]}"


# ------------------------------------------------------------------ AD8
MUTANTS = [
    ("js", "AD1", "the estimate after « Selon votre bac »", "  ${reoFirst ? reoCard(d.reorientation) + ifsiFpcCard(d.aides) : \"\"}\n  ${doubletteCard(", "  ${doubletteCard("),
    ("js", "AD1", "the counts back before the estimate", '<div class="pr-lead"><span class="sum-label">Accès estimé hors terminale</span><div class="pr-lead-v">${reoCell(b)}</div></div>',
     '<p class="small">Calculé à partir des effectifs publiés</p><div class="pr-lead"><span class="sum-label">Accès estimé hors terminale</span><div class="pr-lead-v">${reoCell(b)}</div></div>'),
    ("py", "AD2", "an apprenticeship-free map read as absent", "AND NOT EXISTS (SELECT 1 FROM core.cartographie k WHERE k.cod_aff_form = f.cod_aff_form AND k.carto_session = ?)",
     "AND NOT EXISTS (SELECT 1 FROM core.cartographie k WHERE k.cod_aff_form = f.cod_aff_form AND k.carto_session = ? - 1)"),
    ("py", "AD2", "no map = absent", "    if session is None:\n        return None\n", "    if session is None:\n        return False\n"),
    ("js", "AD3", "« fermée »", "Absente de la carte des formations Parcoursup ${session} : vérifiez sur Parcoursup qu'elle existe toujours.",
     "Absente de la carte des formations Parcoursup ${session} : cette formation est fermée."),
    ("js", "AD3", "the badge's year unescaped", "absente de la carte ${esc(ABS.session)}", "absente de la carte ${ABS.session}"),
    ("js", "AD4", "the note under every fee", "(fr && (fr.lignes || []).some((l) => FC_RE.test(`${l.rubrique} ${l.texte}`))", "(true"),
    ("js", "AD4", "a condition of our own", "ces frais concernent les personnes inscrites au titre de la formation professionnelle, pas les élèves de terminale.",
     "ces frais concernent les personnes de plus de 26 ans inscrites au titre de la formation professionnelle."),
    ("pyaides", "AD5", "the sentence glued across lines", "    for line in _lines(text):\n        m = re.search(", "    for line in [re.sub(r\"\\s+\", \" \", text)]:\n        m = re.search("),
    ("js", "AD5", "the official sentence unescaped", "<blockquote class=\"small\">« ${esc(x.texte)} »</blockquote>", "<blockquote class=\"small\">« ${x.texte} »</blockquote>"),
    ("js", "AD5", "any host linked", '  if (!x || !/^https:\\/\\/www\\.parcoursup\\.gouv\\.fr\\//.test(x.source || "")) return "";', '  if (!x) return "";'),
    ("js", "AD6", "the lycée aids back in the grid", "    ${reo ? \"\" : lyc}", "    ${lyc}"),
    ("js", "AD6", "the share card for lycéens only", '${isReo(store.get("profile", null)) ? "à un proche ou au conseiller qui vous accompagne" : "à un parent ou à votre professeur principal"}',
     "à un parent ou à votre professeur principal"),
]


@check("AD8 mutation test: every seeded return of an audit defect is caught by AD1-AD6")
def ad8(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("AD1", "AD2", "AD3", "AD4", "AD5", "AD6") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    files = {"py": ROOT / "suptracker" / "liste.py", "pyaides": ROOT / "suptracker" / "aides.py"}
    caught, missed = 0, []
    for kind, target, name, old, new in MUTANTS:
        if kind == "js":
            if c.js.count(old) != 1:
                missed.append(f"{name} (anchor {c.js.count(old)})")
                continue
            m = copy.copy(c)
            m.js = c.js.replace(old, new, 1)
            m._memo = {}
            try:
                ok = by[target](m)[0]
            except Exception:  # noqa: BLE001
                ok = False
        else:
            p = files[kind]
            src = p.read_text()
            if src.count(old) != 1:
                missed.append(f"{name} (anchor {src.count(old)})")
                continue
            mod = "suptracker.liste" if kind == "py" else "suptracker.aides"
            import importlib
            m_mod = importlib.import_module(mod)
            saved = dict(m_mod.__dict__)
            try:
                exec(compile(src.replace(old, new, 1), str(p), "exec"), m_mod.__dict__)
                m = copy.copy(c)
                m._memo = {}
                if kind == "pyaides":
                    m.aides_src = src.replace(old, new, 1)
                else:
                    m.liste = src.replace(old, new, 1)
                ok = by[target](m)[0]
            except Exception:  # noqa: BLE001
                ok = False
            finally:
                m_mod.__dict__.clear()
                m_mod.__dict__.update(saved)
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


# ------------------------------------------------------------------ AD9
@check("AD9 wiring and docs: test file and CI duration, README section, CLAUDE.md rule, nightly browser suite")
def ad9(c: Ctx):
    bad = []
    t = ROOT / "tests" / "test_adulte.py"
    if not t.exists() or "redteam_adulte" not in t.read_text():
        bad.append("tests/test_adulte.py")
    if '"tests/test_adulte.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("CI duration")
    if "## The adult path, finished (lot 1, PR 12" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**The adult path, finished (lot 1, PR 12" not in (ROOT.parent / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    if '"adulte": ("AD7",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
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
