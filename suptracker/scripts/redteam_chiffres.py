"""Red team of PR 2 of the audit (owner, 2026-11-23): one figure per question, the same name for the same figure.

    python scripts/redteam_chiffres.py [--db data/suptracker.duckdb] [--real] [--browser]

The audit's four testers each met a formation printed with several neighbouring percentages under similar names: the search
card's « Bac général 41,2 % », the formation page's « Bac général 14,1 % », a « Votre mention parmi les admis 43 à 89 % » on the
card against « 81,1 % – 100 % » in Mes vœux. They were different figures (a report's access rate per bac and the ministry's
proposal rate; a [strictly lower ; lower or equal] range and the bac général's exact bounds) under one name. Now:

  CH1 one rendering, one name (static): « taux d'accès de ce bac » is drawn by ONE function (bacAccesHtml) on the search card
      and on the formation page, whose route table names the ministry's proposal rate « Propositions reçues, toutes phases »;
      « admis avec votre mention ou moins » is ONE reading (mentionShareOf: the zone's reading with no average) drawn by ONE
      formatter (mentionShareTxt) with who it counts (mentionWho) on the card and in Mes vœux; the old competing names are gone;
      the formation answer carries the card's figures (`bacs`) and the page hands them to « Selon votre bac »
  CH2 server: /api/formation's `bacs` = carte.bac_lines (the search card's source) for latest-campaign formations; an older
      campaign's page carries none (the search lists the latest campaign only)
  CH3 twin (Node): for real /api/voeux answers (bac général with two pairs and two mentions, bac techno, bac pro), the card's
      mentionShareOf(lec) = the bounds Mes vœux prints (else its all-bacs share), within 1e-9, and says the same population
  CH4 browser (--browser / --real): a real formation found through the search page, with a bac général profile: the card's
      « Bac général » = the formation page's « Taux d'accès de ce bac »; the card's « Admis avec votre mention ou moins » = Mes
      vœux's; the card's « Vos deux spécialités » = Mes vœux's = L'essentiel's « Pour votre profil »; 0 JS error
  CH5 mutation test: every seeded bug in CH1-CH3 is caught
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
from contextlib import contextmanager
from pathlib import Path

import duckdb
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

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


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        return js[m.start(): m.start() + e.end()]
    return js[m.start(): js.find("\n}", m.start()) + 2]


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self._memo = {}

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    saved = A.record
    A.record = lambda *a, **k: "ok"
    try:
        yield TestClient(api.app), api
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


OLD_NAMES = ("Votre mention parmi les admis", "Votre mention ou moins parmi les admis",
             "Taux de proposition pour vos deux spécialités (cette formation, estimation)",
             "une mention plus basse (bas de la fourchette) ou égale (haut)")


@check("CH1 one rendering and one name: taux d'accès de ce bac, admis avec votre mention ou moins, the route table's two figures")
def ch1(c: Ctx):
    js, bad = c.js, []
    try:
        bacs, dbl, pos, fig, mes = top(js, "carteBacs"), top(js, "doubletteCard"), top(js, "cartePosition"), top(js, "cartePosFigure"), top(js, "carteFigures")
        share, view = top(js, "mentionShareOf"), top(js, "viewVoeux")
    except KeyError as e:
        return False, f"missing function {e}"
    if "bacAccesHtml(f.bacs[b])" not in bacs:
        bad.append("the search card draws its per-bac rate by itself")
    if "bacAccesHtml(acc[s])" not in dbl or "<th class=\"num\">Taux d'accès de ce bac</th>" not in dbl:
        bad.append("the formation page's route table does not print the card's rate under the card's name")
    if "Propositions reçues, toutes phases" not in dbl or 'data-label="${acc ? "Propositions reçues, toutes phases" : "Taux de proposition"}"' not in dbl:
        bad.append("the ministry's proposal rate is not named for what it is beside the card's rate")
    if "le chiffre de la carte de recherche" not in dbl:
        bad.append("the route table does not say its first figure is the search card's")
    if "seriesPos(L.s, 1, cdf)" not in share or "L.kt / L.n" not in share:
        bad.append("mentionShareOf is not the zone's reading with no average (the band's top)")
    if "mentionShareOf(L)" not in pos:
        bad.append("the search card reads its own mention range")
    if "mentionShareTxt(pos.lo, pos.hi)" not in fig or "mentionWho(pos.serie, serie)" not in fig:
        bad.append("the card's mention share is not drawn by the shared formatter with who it counts")
    if '"Admis avec votre mention ou moins"' not in mes or "cartePosFigure(pos, ctx.compact, ctx.serie)" not in mes:
        bad.append("the card's label is not the shared one")
    # lot 1, PR 11: Mes vœux draws the card's figure through the card's own formatter (vxPos -> cartePosFigure)
    if "cartePosFigure(vxPos(v, avg), false, serie)" not in view or "lo: v.bounds[0], hi: v.bounds[1], serie: true" not in top(js, "vxPos") \
            or view.count('"Admis avec votre mention ou moins"') < 1:
        bad.append("Mes vœux does not print the same figure under the same name")
    old = [n for n in OLD_NAMES if n in js]
    if old:
        bad.append(("old competing names still printed", old))
    if 'd.doublettes = { ...d.doublettes, acces: d.bacs }' not in top(js, "viewFormation"):
        bad.append("the formation page does not hand the card's figures to « Selon votre bac »")
    if '"bacs": _bacs_block(rec)' not in c.api or "CA.bac_lines(con).get(rec[\"cod_aff_form\"])" not in c.api:
        bad.append("the formation answer does not carry the card's source")
    return not bad, f"{len(bad)} problems {bad[:4]}"


@check("CH2 server: the formation answer's per-bac rates = the search card's source (carte.bac_lines); none on an older page")
def ch2(c: Ctx):
    from suptracker import carte as CA
    lines = CA.bac_lines(c.con)
    codes = sorted(lines)
    sample = codes[:: max(1, len(codes) // 25)][:25]           # 25 formations spread over the codes (all on a small warehouse)
    bad, n = [], 0
    with client(c.db) as (tc, api):
        for cod in sample:
            r = tc.get(f"/api/formation/{cod}")
            if r.status_code != 200:
                bad.append((cod, r.status_code))
                continue
            n += 1
            if r.json().get("bacs") != json.loads(json.dumps(lines[cod]["bacs"])):
                bad.append((cod, r.json().get("bacs"), lines[cod]["bacs"]))
        old = c.con.execute("""SELECT cod_aff_form, session FROM core.formation_year WHERE session < ? ORDER BY hash(cod_aff_form) LIMIT 3""",
                            [c.latest]).fetchall()
        for cod, s in old:
            r = tc.get(f"/api/formation/{cod}?session={s}")
            if r.status_code == 200 and r.json().get("bacs") is not None:
                bad.append(("older page carries the latest figures", cod, s))
    return n > 0 and not bad, f"{n} formations compared; {len(bad)} wrong {bad[:3]}"


TWIN = """
const pc1 = (v) => (v === null || v === undefined ? "—" : `${(100 * v).toFixed(1).replace(".", ",")} %`);
""" + "\n"


def twin_prog(js: str) -> str:
    names = ["MIN_BOUNDS_N", "wilsonCI", "seriesPos", "mentionShareOf", "mentionShareTxt", "mentionWho"]
    return TWIN + "\n".join(top(js, n) for n in names) + """
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map((v) => { const m = mentionShareOf(v.lec); return m && { lo: m.lo, hi: m.hi, serie: m.serie,
  who: mentionWho(m.serie, v.serie) }; })));
"""


def run_twin(js: str, cases: list[dict]):
    exe = shutil.which("node")
    if not exe:
        return None
    r = nodefile.run([exe, "-e", twin_prog(js)], input=json.dumps(cases, default=float), capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout)


PROFILES = [("bg", {"spe1": "MATHS", "spe2": "SES", "mention": "ab"}), ("bg", {"spe1": "PC", "spe2": "SVT", "mention": "tb"}),
            ("bt", {"mention": "b"}), ("bp", {"mention": "sansmention"})]


def voeux_rows(c: Ctx) -> list[dict]:
    def build():
        codes = [r[0] for r in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY hash(cod_aff_form)",
                                             [c.latest]).fetchall()]
        lists = [codes[i:i + 10] for i in range(0, min(len(codes), 60 if c.real else 30), 10)]
        rows = []
        with client(c.db) as (tc, _):
            for serie, p in PROFILES:
                for ids in lists:
                    q = {"ids": ",".join(ids), "serie": serie, **p}
                    r = tc.get("/api/voeux", params=q)
                    if r.status_code != 200:
                        continue
                    rows += [{**v, "serie": serie} for v in r.json()["voeux"] if v.get("status") == "ok" and v.get("lec")]
        return rows
    return c.memo("rows", build)


@check("CH3 twin (Node): the card's « admis avec votre mention ou moins » = Mes vœux's, same population, every real row")
def ch3(c: Ctx):
    rows = voeux_rows(c)
    if not rows:
        return False, "no /api/voeux row with its reading ingredients"
    got = run_twin(c.js, [{"lec": v["lec"], "serie": v["serie"]} for v in rows])
    if got is None:
        return True, "skipped (node not installed)"
    bad = []
    for v, m in zip(rows, got):
        want = (v["bounds"][0], v["bounds"][1]) if v.get("bounds") else (v["position"], v["position"])
        if m is None or want[0] is None or abs(m["lo"] - want[0]) > 1e-9 or abs(m["hi"] - want[1]) > 1e-9 or m["serie"] != bool(v.get("bounds")):
            bad.append((v["cod_aff_form"], v["serie"], want, m))
    series = {v["serie"] for v in rows}
    return not bad and len(series) >= 2, f"{len(rows)} rows ({sorted(series)}); {len(bad)} differ {bad[:3]}"


BROWSER = r"""
const { chromium } = require('playwright');
const [base, cod, words] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  const ctx = await b.newContext({ viewport: { width: 1360, height: 900 } });
  await ctx.addInitScript(([c]) => { localStorage.setItem("profile", JSON.stringify({ statut: "terminale", serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", academie: "" }));
    localStorage.setItem("voeux", JSON.stringify([c])); }, [cod]);
  const p = await ctx.newPage(); p.on("pageerror", (e) => errs.push(e.message));
  await p.goto(base + "/#/s/" + encodeURIComponent(words));
  try { await p.waitForSelector(`.result a[href="#/f/${cod}"]`, { timeout: 60000 }); } catch (e) { out.card = null; }
  if (out.card !== null) {
    await p.waitForFunction((c) => { const r = document.querySelector(`.result:has(a[href="#/f/${c}"])`);
      return r && !r.querySelector(".cbacs-wait") && !/…/.test((r.querySelector("[data-cfig]") || {}).textContent || "…"); }, cod, { timeout: 60000 }).catch(() => {});
    out.card = await p.evaluate((c) => { const r = document.querySelector(`.result:has(a[href="#/f/${c}"])`);
      const cf = [...r.querySelectorAll(".cf")].map((x) => [x.querySelector(".cf-k").textContent.trim(), x.querySelector(".cf-v").textContent.replace(/\s+/g, " ").trim()]);
      return { bg: (r.querySelector(".cb-bg strong") || {}).textContent, figs: cf }; }, cod);
  }
  await p.goto(base + "/#/f/" + cod); await p.waitForSelector(".summary"); await p.waitForTimeout(2500);
  out.fiche = await p.evaluate(() => {
    const card = [...document.querySelectorAll(".card")].find((x) => (x.querySelector("h2") || {}).textContent === "Selon votre bac");
    const row = card && [...card.querySelectorAll("tr")].find((t) => /Bac général/.test(t.textContent));
    const cell = row && row.querySelector('[data-label="Taux d\'accès de ce bac"] strong');
    const tile = [...document.querySelectorAll(".summary .sum-tile, .summary .acc-half")].find((x) => /Pour votre profil/.test(x.textContent));
    return { bg: cell ? cell.textContent : null, profil: tile ? tile.textContent.replace(/\s+/g, " ") : null };
  });
  await p.goto(base + "/#/voeux"); await p.waitForSelector('td[data-label="Admis avec votre mention ou moins"]', { timeout: 60000 }).catch(() => {});
  out.voeux = await p.evaluate(() => ({ mention: (document.querySelector('td[data-label="Admis avec votre mention ou moins"]') || {}).textContent,
    pair: (document.querySelector('td[data-label="Vos deux spécialités, cette formation"]') || {}).textContent }));
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""

PCT = re.compile(r"\d[\d  ]*(?:,\d)?\s?%")


def first_pct(t: str | None) -> str | None:
    m = PCT.search(t or "")
    return re.sub(r"\s", "", m.group(0)) if m else None


@check("CH4 browser: the search card, the formation page and Mes vœux print the same figure under the same name")
def ch4(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    cands = c.con.execute("""SELECT fy.cod_aff_form, fy.g_ea_lib_vx, fy.lib_for_voe_ins FROM core.formation_year fy
        WHERE fy.session = ? AND fy.fili = 'Licence' AND EXISTS (SELECT 1 FROM core.rapport_doublette d WHERE d.cod_aff_form = fy.cod_aff_form
          AND d.session = fy.session AND d.bac = 'bg' AND d.doublette_key = 'MATHS+SES')
        ORDER BY hash(fy.cod_aff_form) LIMIT 4""", [c.latest]).fetchall()
    if not cands:
        return False, "no latest-campaign licence with a MATHS+SES report line"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tried, bad, done = [], [], None
    try:
        time.sleep(8)
        tmp = ROOT / ".chiffres_probe.js"
        tmp.write_text(BROWSER)
        try:
            for cod, etab, lib in cands:
                words = f"{lib.split(' - ')[-1]} {etab}"[:90]
                r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod, words], capture_output=True, text=True, timeout=400, cwd=str(ROOT))
                if r.returncode:
                    return False, r.stderr[-400:]
                d = json.loads(r.stdout)
                tried.append(cod)
                if d["out"].get("card"):
                    done = (cod, d)
                    break
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if not done:
        return False, f"no candidate found through the search page {tried}"
    cod, d = done
    o = d["out"]
    figs = dict(o["card"]["figs"])
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if first_pct(o["card"]["bg"]) is None or first_pct(o["card"]["bg"]) != first_pct(o["fiche"]["bg"]):
        bad.append(("bac général: card vs formation page", o["card"]["bg"], o["fiche"]["bg"]))
    cm, vm = figs.get("Admis avec votre mention ou moins"), o["voeux"]["mention"]
    if not cm or not vm or re.sub(r"\s", "", cm) != re.sub(r"\s", "", vm):
        bad.append(("mention share: card vs Mes vœux", cm, vm))
    cp, vp = first_pct(figs.get("Vos deux spécialités")), first_pct(o["voeux"]["pair"])
    pp = first_pct(((o["fiche"]["profil"] or "").split("Pour votre profil") + [""])[1])   # the tile's figure, not its explanation
    if cp is None or not (cp == vp == pp):
        bad.append(("pair: card vs Mes vœux vs L'essentiel", cp, vp, pp))
    return not bad, f"formation {cod}; {len(bad)} problems {bad[:3]}; {o}"


MUTANTS = [
    ("js", "card draws its own per-bac rate", "  const cell = (b) => `<li class=\"cb cb-${b}\"><span class=\"cb-k\">${{ bg: \"Bac général\", bt: \"Bac techno\", bp: \"Bac pro\" }[b]}</span> ${bacAccesHtml(f.bacs[b])}</li>`;",
     "  const cell = (b) => `<li class=\"cb cb-${b}\"><span class=\"cb-k\">${{ bg: \"Bac général\", bt: \"Bac techno\", bp: \"Bac pro\" }[b]}</span> <strong>${pct1((f.bacs[b] || {}).taux)}</strong></li>`;", "ch1"),
    ("js", "the page's route table loses the card's rate", "${acc ? `<td class=\"num\" data-label=\"Taux d'accès de ce bac\">${bacAccesHtml(acc[s])}</td>` : \"\"}", "", "ch1"),
    ("js", "proposal rate called the access rate", 'data-label="${acc ? "Propositions reçues, toutes phases" : "Taux de proposition"}"', 'data-label="Taux d\'accès de ce bac"', "ch1"),
    ("js", "card back to its [lower ; lower or equal] range", "  const m = mentionShareOf(L);\n  return m && { ...m, moyenne: false };",
     "  return { lo: (L.kt - L.kb) / L.n, hi: L.kt / L.n, moyenne: false };", "ch1"),
    ("js", "card's share without who it counts", "${mentionShareTxt(pos.lo, pos.hi)} <span class=\"muted small\">(${mentionWho(pos.serie, serie)})</span>", "${mentionShareTxt(pos.lo, pos.hi)}", "ch1"),
    ("js", "old card name back", '"Admis sous votre moyenne" : "Admis avec votre mention ou moins"', '"Admis sous votre moyenne" : "Votre mention parmi les admis"', "ch1"),
    ("js", "Mes vœux header renamed", 'const posHead = avg ? "Admis sous votre moyenne" : "Admis avec votre mention ou moins";', 'const posHead = avg ? "Admis sous votre moyenne" : "Votre mention ou moins parmi les admis";', "ch1"),
    ("js", "formation page keeps the card's figures to itself", "  if (d.doublettes && d.bacs) d.doublettes = { ...d.doublettes, acces: d.bacs };", "", "ch1"),
    ("api", "formation answer without the card's source", '"bacs": _bacs_block(rec)}', '"bacs": None}', "ch2"),
    ("api", "an older page carries the latest figures", '    if rec["session"] != con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]:\n        return None\n', "", "ch2"),
    ("api", "another campaign's lines", "    e = CA.bac_lines(con).get(rec[\"cod_aff_form\"])\n    return e[\"bacs\"] if e else None",
     "    e = CA.bac_lines(con).get(rec[\"cod_aff_form\"])\n    return {k: {**v, \"taux\": (v.get(\"taux\") or 0) + 1} for k, v in e[\"bacs\"].items()} if e else None", "ch2"),
    ("js", "the share read at the band's bottom", "const cdf = L.kt / L.n, sp = seriesPos(L.s, 1, cdf);", "const cdf = (L.kt - L.kb) / L.n, sp = seriesPos(L.s, 0, cdf);", "ch3"),
    ("js", "series bounds ignored", "  return sp ? { lo: sp.bounds[0], hi: sp.bounds[1], serie: true } : { lo: cdf, hi: cdf, serie: false };",
     "  return { lo: cdf, hi: cdf, serie: false };", "ch3"),
]


def _patched_api(c: Ctx, src: str):
    """Load api.py with its source mutated, as the module the TestClient serves (restored afterwards)."""
    import importlib

    import suptracker.api as api_mod
    path = ROOT / "suptracker" / "api.py"
    code = compile(src, str(path), "exec")
    saved = dict(api_mod.__dict__)
    exec(code, api_mod.__dict__)   # noqa: S102 (red team: a mutant of our own module, in memory)
    return api_mod, saved, importlib


@check("CH5 mutation test: every seeded bug in the shared renderings, the server's source and the twin is caught")
def ch5(c: Ctx):
    base = {k: f(c)[0] for k, f in (("ch1", ch1), ("ch2", ch2), ("ch3", ch3))}
    if not all(base.values()):
        return False, f"baseline fails {base}"
    missed = []
    for where, name, old, new, fn in MUTANTS:
        src = c.js if where == "js" else c.api
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        m._memo = dict(c._memo)
        if where == "js":
            m.js = src.replace(old, new, 1)
            ok = {"ch1": ch1, "ch3": ch3}[fn](m)[0]
        else:
            m.api = src.replace(old, new, 1)
            ok = ch1(m)[0]
            if ok or fn == "ch2":
                api_mod, saved, _ = _patched_api(m, m.api)
                try:
                    ok = ok and ch2(m)[0]
                finally:
                    api_mod.__dict__.clear()
                    api_mod.__dict__.update(saved)
        if ok:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
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
