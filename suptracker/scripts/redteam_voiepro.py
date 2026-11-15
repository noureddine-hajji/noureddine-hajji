"""Red team, sprint V2 (owner, 2026-11-15): bac techno and bac pro and apprenticeship merged into the pages, formations under
pressure, the distance from the student's town, the CAES; the unread fiches are covered by redteam_grilles GR5.

  VP1 demand per place (tension.py), fixture warehouse built here: the ratio = vœux / places (published counts) on every
      formation with places, re-derived; the 75th and 90th percentiles per (campaign, type) recomputed independently (linear
      interpolation); the class = the fixed rule (>= p90 "tres", >= p75 "forte", none below 20 formations of the type or with
      no places); the lists' codes = the latest campaign's "tres" only.
  VP2 apprenticeship (apprentissage.py): per BTS title and route, the number of establishments and the median of the published
      employment rate re-derived (statistics.median), a route kept only with 5 establishments publishing; the block exists for
      a formation with an offer (propose) or a BTS comparison, never otherwise; the lists' codes = attached offers + SIES
      apprenticeship formations; links on La bonne alternance only (https).
  VP3 page (node): tensionCard, apprentiCard, apprentiInsertionCard, tensionBadge, appBadge escape every stored string, label
      computed figures with estimTag, say demand is not a chance, never compute a salary, keep links https and noopener;
      the demand badge never uses a zone colour or the accent.
  VP4 distance (node + Python): haversineKm = an independent haversine; the stored town is never trusted (tampered values
      give no town); the town box sends nothing (only /api/communes, no parameter); /api/communes and /api/reconnaissance
      are shared-cached with no parameter; the API Géo JSON is flattened to name, code, department and centre.
  VP5 CAES and phase complémentaire: the help page lists the official Parcoursup page; Mes vœux' next steps link it.
  VP6 real warehouse (--real, when built): the stored tension and apprenticeship tables re-derived from core.formation_year
      and core.inserjeunes_bts.
  VP7 plumbing: build, API answers (formation, compare, reconnaissance, communes), source register, docs, tests, durations.
  VP8 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import statistics
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str):
    m = types.ModuleType(name)
    m.__file__, m.__package__ = str(path), "suptracker"
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {k: (ROOT / "suptracker" / f"{f}.py").read_text() for k, f in
                    (("ts", "tension"), ("ap", "apprentissage"), ("ing", "ingest"), ("aide", "aide"))}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.css = (ROOT / "suptracker" / "static" / "style.css").read_text()

    def mod(self, k: str):
        import suptracker  # noqa: F401  (the package, for the relative imports)
        name = {"ts": "tension", "ap": "apprentissage", "ing": "ingest", "aide": "aide"}[k]
        return load(ROOT / "suptracker" / f"{name}.py", f"suptracker.{name}_rt", self.src[k])


def quantile(xs: list[float], q: float) -> float:
    """Linear interpolation between order statistics (the definition of DuckDB's quantile_cont), written here."""
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def fixture():
    """A small warehouse: two campaigns, a type of 30 formations (positions), a type of 5 (no position), places 0 / NULL."""
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, fili VARCHAR, nb_voe_pp INTEGER,
        capa_fin INTEGER, fil_lib_voe_acc VARCHAR, apprentissage BOOLEAN)""")
    rows = []
    for s in (2024, 2025):
        for i in range(30):
            rows.append((str(1000 + i), s, "BTS", 10 * (i + 1) + (s - 2024) * 7, 10 + (i % 3), "Comptabilité et gestion", i == 7))
        for i in range(5):
            rows.append((str(2000 + i), s, "Licence", 100 * (i + 1), 50, "Licence - Droit", False))
        rows.append(("3000", s, "BTS", 50, 0, "Comptabilité et gestion", False))
        rows.append(("3001", s, "BTS", 50, None, "Comptabilité et gestion", False))
    con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("""CREATE TABLE core.inserjeunes_bts (source VARCHAR, annee VARCHAR, uai VARCHAR, cle VARCHAR,
        taux_emploi_6 DOUBLE, taux_poursuite DOUBLE)""")
    ij = []
    for i, rate in enumerate((50.0, 52.0, 55.0, 70.0, 71.0, 90.0, 95.0)):      # skewed: the mean (69) is not the median (70)
        ij.append(("apprentissage", "cumul 2023-2024", f"CFA{i}", "comptabilite gestion", rate, 40.0 + i))
    for i in range(4):
        ij.append(("lycee", "cumul 2023-2024", f"LY{i}", "comptabilite gestion", 60.0 + i, 55.0))
    ij.append(("lycee", "cumul 2023-2024", "LYX", "comptabilite gestion", None, None))
    con.executemany("INSERT INTO core.inserjeunes_bts VALUES (?, ?, ?, ?, ?, ?)", ij)
    return con


# ---------------------------------------------------------------- VP1

@check("VP1 demand per place: ratio of published counts, percentiles per campaign and type, the fixed class rule, the lists' codes")
def vp1(c: Ctx):
    ts = c.mod("ts")
    con = fixture()
    ts.build(con)
    bad = []
    rows = con.execute("SELECT cod_aff_form, session, fili, nb_voe_pp, capa_fin FROM core.formation_year").fetchall()
    groups: dict = {}
    for cod, s, f, v, p in rows:
        if p and p > 0 and v is not None:
            groups.setdefault((s, f), []).append((cod, v / p))
    want = {}
    for (s, f), xs in groups.items():
        ratios = [r for _c, r in xs]
        p75, p90 = quantile(ratios, 0.75), quantile(ratios, 0.90)
        for cod, r in xs:
            cl = None if len(xs) < 20 else "tres" if r >= p90 - 1e-9 else "forte" if r >= p75 - 1e-9 else None
            want[(cod, s)] = (round(r, 6), cl)
    got = {(cod, s): (round(pp, 6), cl) for cod, s, pp, cl in con.execute(
        "SELECT cod_aff_form, session, par_place, classe FROM mart.tension").fetchall()}
    if got != want:
        diff = sorted(set(got.items()) ^ set(want.items()))[:4]
        bad.append(f"stored {len(got)} rows vs {len(want)} re-derived; first differences {diff}")
    if any(k[0] in ("3000", "3001") for k in got):
        bad.append("a formation without places got a ratio")
    if any(cl for (cod, _s), (_r, cl) in got.items() if cod.startswith("2")):
        bad.append("a type of 5 formations got a position")
    f = ts.for_formation(con, "1029", 2025)
    if not f or f["voeux"] != 307 or f["places"] != 12 or abs(f["par_place"] - round(307 / 12, 1)) > 1e-9 \
            or f["classe"] != want[("1029", 2025)][1] or (f["classe"] and not f["libelle"]):
        bad.append(f"for_formation {f}")
    if "pas dire peu de chances" not in (f or {}).get("prudence", ""):
        bad.append("the caveat (demand is not a chance) is missing")
    comp = ts.compact(con)
    latest = sorted(cod for (cod, s), (_r, cl) in want.items() if s == 2025 and cl == "tres")
    if sorted(x for x in comp["tres"].split(",") if x) != latest:
        bad.append(f"lists' codes {comp['tres']} != {latest}")
    if ts.classe(None, 1, 2, 100) or ts.classe(5, 1, 2, 19) or ts.classe(2, 1, 2, 20) != "tres" or ts.classe(1.5, 1, 2, 20) != "forte":
        bad.append("classe(): the fixed rule")
    return not bad, f"{len(got)} ratios re-derived; {bad[:4]}"


# ---------------------------------------------------------------- VP2

@check("VP2 apprenticeship: route medians re-derived (5 establishments at least), block only with an offer or a comparison, codes, official links")
def vp2(c: Ctx):
    ap = c.mod("ap")
    con = fixture()
    ap.build(con)
    bad = []
    rows = con.execute("SELECT source, uai, cle, taux_emploi_6, taux_poursuite FROM core.inserjeunes_bts").fetchall()
    for voie in ("apprentissage", "lycee"):
        e = [r[3] for r in rows if r[0] == voie and r[3] is not None]
        got = con.execute("SELECT n_etab, n_emploi, emploi_med FROM mart.app_insertion WHERE voie = ?", [voie]).fetchone()
        n_etab = len({r[1] for r in rows if r[0] == voie})
        if not got or got[0] != n_etab or got[1] != len(e) or abs(got[2] - statistics.median(e)) > 1e-9:
            bad.append(f"{voie}: stored {got}, re-derived {n_etab} establishments, {len(e)} rates, median {statistics.median(e)}")
    nat = ap.national(con, "Comptabilité et gestion")
    voies = [v["voie"] for v in (nat or {}).get("voies", [])]
    if voies != ["apprentissage"]:                  # the lycées: 4 rates only, under the threshold of 5
        bad.append(f"routes kept {voies} (lycée has 4 establishments publishing: must be dropped)")
    if nat and nat["voies"][0]["emploi_med"] != round(statistics.median([50.0, 52.0, 55.0, 70.0, 71.0, 90.0, 95.0])):
        bad.append("the median shown is not the re-derived one")
    # the block: a BTS with a comparison and no offer has propose = false; a licence with no offer has no block
    import suptracker.carte as carte_mod
    real_for = carte_mod.for_formation
    try:
        carte_mod.for_formation = lambda con_, cod: [{"cod_aff_form": "9", "etablissement": "CFA " + HOSTILE, "formation": "x", "ville": "V", "fiche": None}] if cod == "1003" else []
        carte_mod.offres_par_formation = lambda con_: {"1003": [{}]}
        b0 = ap.for_formation(con, "1000", 2025)
        b3 = ap.for_formation(con, "1003", 2025)
        b7 = ap.for_formation(con, "1007", 2025)
        lic = ap.for_formation(con, "2000", 2025)
        codes = set(ap.codes(con).split(","))
    finally:
        carte_mod.for_formation = real_for
        import importlib
        importlib.reload(carte_mod)
    if not b0 or b0["propose"] or not b0["national"]:
        bad.append(f"BTS without offer: {b0 and {k: b0[k] for k in ('propose', 'national')}}")
    if not b3 or not b3["propose"] or len(b3["offres"]) != 1:
        bad.append("BTS with an attached offer: propose must be true")
    if not b7 or not b7["propose"] or not b7["sies_apprentissage"]:
        bad.append("an apprenticeship SIES formation: propose must be true")
    if lic is not None:
        bad.append("a licence with neither offer nor comparison got a block")
    if codes != {"1003", "1007"}:
        bad.append(f"lists' codes {codes}")
    for k, u in (b0 or {}).get("liens", {}).items():
        if not u.startswith("https://labonnealternance.apprentissage.beta.gouv.fr/"):
            bad.append(f"link {k} off the official host: {u}")
    return not bad, f"{len(rows)} Inserjeunes rows; {bad[:4]}"


# ---------------------------------------------------------------- VP3

def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("(") == part.count(")") and part.rstrip().endswith(";"):
                return part
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    import shutil
    import subprocess
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


STUB = """const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x) => (x === null || x === undefined ? "—" : Number(x).toLocaleString("fr-FR"));
const estimTag = (d) => `<span class="estim">estimation</span> ${esc(d || "")}`;
const carteFiche = (o) => (o.fiche && /^https:\\/\\/dossierappel\\.parcoursup\\.fr\\//.test(o.fiche) ? o.fiche : null);
let store = { v: null, get() { return this.v; }, set(k, v) { this.v = v; } };
"""


@check("VP3 page: the cards and badges escape, label computed figures, say demand is not a chance, compute no salary, safe links, no zone colour")
def vp3(c: Ctx):
    defs = "\n".join(top(c.js, n) for n in ("tensionCard", "apprentiCard", "apprentiInsertionCard", "tensionBadge", "appBadge"))
    if not all(top(c.js, n) for n in ("tensionCard", "apprentiCard", "apprentiInsertionCard", "tensionBadge", "appBadge")):
        return False, "a renderer is missing from app.js"
    t = {"voeux": 300, "places": 10, "par_place": 30, "type": "BTS", "n_type": 5000, "classe": "tres", "libelle": "Forte " + HOSTILE,
         "explication": "Expl " + HOSTILE, "prudence": "Beaucoup de vœux par place ne veut pas dire peu de chances " + HOSTILE}
    a = {"propose": True, "sies_apprentissage": False, "offres": [{"etablissement": "CFA " + HOSTILE, "ville": HOSTILE, "fiche": "javascript:alert(1)"}],
         "national": {"voies": [{"voie": "apprentissage", "libelle": "En apprentissage " + HOSTILE, "annee": HOSTILE, "n_etab": 9, "n_emploi": 7,
                                 "emploi_med": 66, "emploi_q1": 59, "emploi_q3": 73, "poursuite_med": 45}]},
         "liens": {"entreprises": "https://labonnealternance.apprentissage.beta.gouv.fr/", "salaire": "https://labonnealternance.apprentissage.beta.gouv.fr/salaire-alternant",
                   "guide": "https://labonnealternance.apprentissage.beta.gouv.fr/guide-alternant/comprendre-la-remuneration"}}
    prog = STUB + defs + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      let RECO = { tres: new Set(["1"]), tresLib: "Forte " + D.h, tresExp: "E " + D.h, app: new Set(["1"]) };
      process.stdout.write(JSON.stringify([tensionCard(D.t, 2025), apprentiCard(D.a), apprentiInsertionCard(D.a), tensionBadge("1"), appBadge("1"),
        tensionCard(null, 2025), apprentiCard({ ...D.a, propose: false }), apprentiInsertionCard(null), tensionBadge("2"), appBadge("2")]));"""
    out = node(prog, {"t": t, "a": a, "h": HOSTILE})
    if out is None:
        return True, "node absent: not run"
    bad = []
    for i, h in enumerate(out):
        if "<img" in h:
            bad.append(f"output {i}: unescaped")
        txt = re.sub(r"<[^>]+>", " ", h)
        if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt):
            bad.append(f"output {i}: tutoiement")
        if re.search(r"(?i)vos chances|probabilit|\d+ ?% de chances", txt):
            bad.append(f"output {i}: a chance")
        for tag in re.findall(r"<a [^>]*>", h):
            href = re.search(r'href="([^"]*)"', tag)
            if href and not href.group(1).startswith("https://"):
                bad.append(f"output {i}: link {href.group(1)[:24]}")
            if 'target="_blank"' in tag and "noopener" not in tag:
                bad.append(f"output {i}: no noopener")
    tc, ac, ic, tb, ab, *empty = out
    if any(empty):
        bad.append("a card or badge shown with nothing to show")
    if 'class="estim"' not in tc or 'class="estim"' not in ic:
        bad.append("a computed figure (ratio, median) without the estimation label")
    if "pas dire peu de chances" not in tc:
        bad.append("the demand card does not say it is not a chance")
    if re.search(r"\d[\d  ]*(?:,\d+)? ?€", re.sub(r"<[^>]+>", " ", ac)):
        bad.append("the apprenticeship card prints a euro amount (never a computed salary)")
    if "L6211-1" not in ac or "javascript:" in ac:
        bad.append("apprenticeship card: free tuition not sourced, or an unsafe fiche link kept")
    if "médiane des établissements" not in ic:
        bad.append("the route comparison does not say it is a median of establishments")
    css = re.search(r"\.badge\.tension\s*\{([^}]*)\}", c.css)
    if not css or re.search(r"--zone-|--accent", css.group(1)):
        bad.append("the demand badge uses a zone colour or the accent")
    return not bad, f"{len(out)} renders; {bad[:4]}"


# ---------------------------------------------------------------- VP4

def haversine(a, b, c, d):
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@check("VP4 distance: computed in the browser = an independent haversine, stored town never trusted, nothing sent, communes flattened")
def vp4(c: Ctx):
    bad = []
    names = ("haversineKm", "villeLabel", "villeDepart", "distanceText", "distanceBlock", "foldTxt")
    defs = "\n".join(top(c.js, n) for n in names)
    pairs = [(50.29, 2.78, 43.61, 3.88), (48.86, 2.35, 48.86, 2.35), (-21.1, 55.5, 16.24, -61.53), (49.49, 0.11, 49.48, 0.12)]
    prog = STUB + defs + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const tampered = [null, { nom: 1 }, { nom: "A", dep: "1", lat: "x", lon: 2 }, { nom: "A", dep: "1", lat: 91, lon: 2 }, { nom: D.h, dep: "62", lat: 50, lon: 2 }];
      const trust = tampered.map((v) => { store.v = v; return villeDepart(); });
      store.v = { nom: "Arras " + D.h, dep: "62", lat: 50.29, lon: 2.78 };
      process.stdout.write(JSON.stringify([D.p.map((x) => haversineKm(...x)), trust, distanceBlock({ lat: 43.61, lon: 3.88 }), distanceBlock({ lat: null, lon: null }),
        foldTxt("Saint-Étienne-du-Rouvray")]));"""
    out = node(prog, {"p": pairs, "h": HOSTILE})
    if out is not None:
        kms, trust, block, none_block, folded = out
        for (a, b, cc, d), k in zip(pairs, kms):
            if abs(k - haversine(a, b, cc, d)) > 0.5:
                bad.append(f"haversine {a},{b} -> {cc},{d}: {k} vs {haversine(a, b, cc, d):.1f}")
        if any(trust[:4]) or not trust[4]:
            bad.append(f"stored town trusted when tampered, or a valid one refused: {trust}")
        if "<img" in block or "km</strong>" not in block or "rien n'est envoyé" not in block or none_block:
            bad.append("distance block: unescaped, no distance, no privacy sentence, or shown without coordinates")
        if folded != "saint etienne du rouvray":
            bad.append(f"foldTxt {folded!r}")
    bind = top(c.js, "bindDistance")
    calls = re.findall(r'api\(\s*[`"]([^`"]+)[`"]', bind + top(c.js, "communesLoad"))
    if calls != ["/api/communes"] or re.search(r"fetch\(|navigator\.sendBeacon|track\(", bind):
        bad.append(f"the town box calls {calls} or sends something")
    from suptracker import cache as CA
    for path in ("/api/communes", "/api/reconnaissance"):
        pol = CA.policy(path) if hasattr(CA, "policy") else None
        if pol is None or "public" not in str(pol).lower():
            bad.append(f"cache policy of {path}: {pol}")
    ing = c.mod("ing")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        p.write_text(json.dumps([{"nom": "Arras", "code": "62041", "codeDepartement": "62", "centre": {"type": "Point", "coordinates": [2.78, 50.29]}},
                                 {"nom": "Sans centre", "code": "1", "codeDepartement": "01"}]))
        df = ing._json_records(p)
        r0 = df.iloc[0].to_dict()
        if (r0.get("centre_lat"), r0.get("centre_lon"), r0.get("codeDepartement")) != ("50.29", "2.78", "62"):
            bad.append(f"API Géo flattened as {r0}")
    return not bad, f"{len(pairs)} distances, 5 stored towns; {bad[:4]}"


# ---------------------------------------------------------------- VP5

CAES_URL = "https://www.parcoursup.gouv.fr/contenus/les-solutions-si-vous-n-avez-pas-recu-de-proposition-d-admission-3456"


@check("VP5 CAES and phase complémentaire: the help page and Mes vœux' next steps link the official Parcoursup page")
def vp5(c: Ctx):
    aide = c.mod("aide")
    bad = []
    svc = [s for s in aide.SERVICES if s.get("url") == CAES_URL]
    if not svc or "CAES" not in svc[0]["titre"] + svc[0]["comment"] or "phase complémentaire" not in svc[0]["titre"].lower() + svc[0]["comment"].lower():
        bad.append("help page: no CAES / phase complémentaire service on the official page")
    if CAES_URL not in aide.page():
        bad.append("help page: the official link is not rendered")
    ns = re.search(r"const NEXT_STEPS = \{(.*?)\n\};", c.js, re.S)
    voeux = re.search(r"voeux: \[(.*?)\],\n", ns.group(1), re.S) if ns else None
    if not voeux or CAES_URL not in voeux.group(1):
        bad.append("Mes vœux' next steps do not link the CAES page")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- VP6

@check("VP6 real warehouse: the stored demand and apprenticeship tables re-derived (skipped until built)")
def vp6(c: Ctx):
    if not (c.real and c.db):
        return True, "fixture mode"
    import duckdb
    con = duckdb.connect(str(c.db), read_only=True)
    have = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'mart'").fetchall()}
    if not {"tension", "app_insertion"} <= have:
        return True, "tables not built yet in this warehouse (the data workflow builds them)"
    bad = []
    n_bad = con.execute("""SELECT count(*) FROM mart.tension t JOIN core.formation_year f USING (cod_aff_form, session)
        WHERE abs(t.par_place - f.nb_voe_pp * 1.0 / f.capa_fin) > 1e-9 OR f.capa_fin <= 0""").fetchone()[0]
    if n_bad:
        bad.append(f"{n_bad} ratios differ from vœux / places")
    latest = con.execute("SELECT max(session) FROM mart.tension").fetchone()[0]
    for fili, in con.execute("SELECT DISTINCT fili FROM mart.tension WHERE session = ? AND n_type >= 20 LIMIT 6", [latest]).fetchall():
        xs = [r for (r,) in con.execute("SELECT par_place FROM mart.tension WHERE session = ? AND fili = ?", [latest, fili]).fetchall()]
        p90 = quantile(xs, 0.90)
        n_tres = con.execute("SELECT count(*) FROM mart.tension WHERE session = ? AND fili = ? AND classe = 'tres'", [latest, fili]).fetchone()[0]
        if n_tres != sum(1 for x in xs if x >= p90 - 1e-9):
            bad.append(f"{fili}: {n_tres} 'tres' vs {sum(1 for x in xs if x >= p90 - 1e-9)} re-derived")
    for cle, voie, n_e, med in con.execute("SELECT cle, voie, n_emploi, emploi_med FROM mart.app_insertion ORDER BY n_emploi DESC LIMIT 20").fetchall():
        xs = [x for (x,) in con.execute("SELECT taux_emploi_6 FROM core.inserjeunes_bts WHERE cle = ? AND source = ? AND taux_emploi_6 IS NOT NULL",
                                        [cle, voie]).fetchall()]
        if len(xs) != n_e or (xs and abs(statistics.median(xs) - med) > 1e-9):
            bad.append(f"{cle} / {voie}: {n_e} rates median {med}, re-derived {len(xs)} / {statistics.median(xs) if xs else None}")
    return not bad, f"campaign {latest}; {bad[:4]}"


# ---------------------------------------------------------------- VP7

@check("VP7 plumbing: build, API answers, cache, sources, docs, tests and durations")
def vp7(c: Ctx):
    bad = []
    build = (ROOT / "suptracker" / "build.py").read_text()
    api = (ROOT / "suptracker" / "api.py").read_text()
    for need, where, text in (("tension.build(con)", "build", build), ("apprentissage.build(con)", "build", build),
                              ('"tension": TS.for_formation(', "api", api), ('"apprenti": APP.for_formation(', "api", api),
                              ('"tension": f.get("tension"), "apprenti": f.get("apprenti")', "api (compare)", api),
                              ('"tension": TS.compact(con), "apprentissage": APP.codes(con)', "api (lists)", api),
                              ('@app.get("/api/communes")', "api", api)):
        if need not in text:
            bad.append(f"{where}: {need} missing")
    from suptracker import sources
    if "communes_geo" not in {k for s in sources.SOURCES for k in s.get("datasets", ())}:
        bad.append("API Géo not in the source register")
    readme = (ROOT / "README.md").read_text()
    claude = (REPO / "CLAUDE.md").read_text()
    if "redteam_voiepro.py" not in readme or "VP1-VP8" not in claude:
        bad.append("README or CLAUDE.md does not describe the sprint")
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    if "tests/test_voiepro.py" not in dur or not (ROOT / "tests" / "test_voiepro.py").exists():
        bad.append("tests/test_voiepro.py missing or absent from durations.json")
    for js in ("function tensionCard(", "function apprentiCard(", "function bindDistance(", "bindDistance();", "tensionBadge(r.cod_aff_form)",
               "tensionBadge(v.cod_aff_form)", "apprentiCard(d.apprenti)", "apprentiInsertionCard(d.apprenti)", "tensionCard(d.tension, r.session)"):
        if js not in c.js:
            bad.append(f"app.js: {js} missing")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- VP8

SOURCE_MUTANTS = [
    ("ts", "ratio inverted", "nb_voe_pp * 1.0 / capa_fin AS par_place", "capa_fin * 1.0 / nb_voe_pp AS par_place", "VP1"),
    ("ts", "places zero kept", "            WHERE capa_fin > 0 AND nb_voe_pp IS NOT NULL),", "            WHERE nb_voe_pp IS NOT NULL AND capa_fin IS NOT NULL),", "VP1"),
    ("ts", "percentiles over every type", "            FROM r GROUP BY session, fili)", "            FROM r GROUP BY session, fili, cod_aff_form)", "VP1"),
    ("ts", "small types positioned", "or n_type < MIN_TYPE:", "or n_type < 0:", "VP1"),
    ("ts", "p75 as the top class", "    if par_place >= p90:\n        return \"tres\"", "    if par_place >= p75:\n        return \"tres\"", "VP1"),
    ("ts", "lists from every class", "AND classe = 'tres' ORDER BY", "AND classe IS NOT NULL ORDER BY", "VP1"),
    ("ts", "caveat dropped", 'PRUDENCE = ("Beaucoup de vœux par place ne veut pas dire peu de chances', 'PRUDENCE = ("Beaucoup de vœux par place', "VP1"),
    ("ap", "mean for median", "median(taux_emploi_6), quantile_cont", "avg(taux_emploi_6), quantile_cont", "VP2"),
    ("ap", "no threshold", "        if n_e >= MIN_ETAB:", "        if n_e >= 1:", "VP2"),
    ("ap", "block for every formation", "    if not offres and not sies_app and not nat:\n        return None", "", "VP2"),
    ("ap", "propose from the comparison", '"propose": bool(offres or sies_app)', '"propose": bool(offres or sies_app or nat)', "VP2"),
    ("ap", "apprenticeship formations forgotten", "    out |= {c for (c,) in", "    out = out or {c for (c,) in", "VP2"),
    ("js", "demand card unescaped", "${esc(t.libelle)}</span>` : \"\"}</p>", "${t.libelle}</span>` : \"\"}</p>", "VP3"),
    ("js", "ratio without the label", '${fmt(t.par_place)} vœux par place ${estimTag("vœux ÷ places, deux chiffres publiés")}', "${fmt(t.par_place)} vœux par place", "VP3"),
    ("js", "caveat not shown", '<p class="small muted">${esc(t.prudence)}</p></div>`;', "</div>`;", "VP3"),
    ("js", "CFA name unescaped", 'return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">sa fiche',
     'return `<li>${o.etablissement}${o.ville ? ` · ${esc(o.ville)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">sa fiche', "VP3"),
    ("js", "median not labelled", 'le publient ${estimTag("médiane des établissements, pas un taux national")}', "le publient", "VP3"),
    ("js", "badge for every code", "return RECO && RECO.tres && RECO.tres.has(cod) ?", "return RECO && RECO.tres ?", "VP3"),
    ("js", "haversine radius", "return 12742 * Math.asin(Math.sqrt(x));", "return 12000 * Math.asin(Math.sqrt(x));", "VP4"),
    ("js", "stored town trusted", 'Number.isFinite(v.lat) && Number.isFinite(v.lon)\n    && Math.abs(v.lat) <= 90 && Math.abs(v.lon) <= 180 ?', "true ?", "VP4"),
    ("js", "town sent to the site", 'COMMUNES_P = api("/api/communes")', 'COMMUNES_P = api("/api/communes?ville=" + encodeURIComponent((store.get("villeDepart") || {}).nom || ""))', "VP4"),
    ("ing", "JSON point read as lat lon", 'flat[f"{k}_lon"], flat[f"{k}_lat"] = (str(x) for x in v["coordinates"][:2])',
     'flat[f"{k}_lat"], flat[f"{k}_lon"] = (str(x) for x in v["coordinates"][:2])', "VP4"),
    ("aide", "CAES page replaced", '"url": "https://www.parcoursup.gouv.fr/contenus/les-solutions-si-vous-n-avez-pas-recu-de-proposition-d-admission-3456",',
     '"url": "https://www.parcoursup.gouv.fr/",', "VP5"),
]


@check("VP8 mutation test: demand, apprenticeship, page, distance, CAES mutants each caught")
def vp8(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        if kind == "js":
            m.js = src.replace(old, new, 1)
        else:
            m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(SOURCE_MUTANTS)} caught; missed {missed}"


def run(db: Path | None = None, real: bool = False) -> list[dict]:
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real)
    out = []
    for fn in CHECKS:
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="also re-derive the committed warehouse's tables")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
