"""Red team of "formations semblables" and of the profile bar (owner's request, 2026-11-10).
    python scripts/redteam_semblables.py [--db data/suptracker.duckdb] [--real]
  K1 crafted reports with hand-computed answers: pooled doublette rates over the reports that detail the doublette (same
     reports in "all bac général"), a concours report counted once, "Autres doublettes" never pooled, a report not yet
     cross-checked never used, generic labels (FCIL, licence pro) get no similar formations, thresholds (3 reports, 20
     candidates), jury counts (highest importance per field, specialties, options)
  K2 warehouse re-derivation: mart.semblable_dbl re-derived by SQL, the jury counts re-derived from the texts with an
     independent field mapping
  K3 a formation never reads its own report through this block: where the page uses it (no own bac général table, no own
     texts) the served figures equal the pool of the OTHER formations, and the list of formations excludes it
  K4 estimate: the page (Node) and Python twins agree; capped at 100; same shape as the national estimate
  K5 one figure everywhere: the formation page uses the similar formations only where its own report has no bac général
     table, the evolution chart and Mes vœux use the same estimate; a published figure is never beside it
  K6 pages on hostile data (Node): escaped, figure cells labelled, "pas le rapport de cette formation", counts never a mean,
     "pas des chances", links to the formations' own pages
  K7 profile bar (Node): the stored profile is escaped, counts come from the same /api/voeux query as Mes vœux (vxQuery),
     the alert only from the server's "aucune_securite" message, no request with an empty list, a prompt without a profile
  K8 wording and wiring: no chance or probability, vouvoiement, the bar in the page shell, release guards, features
  K9 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import semblables as SB  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>'
M = {"SB": SB}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-600:]}


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


# ------------------------------------------------------------------ the crafted reports (hand-computed answers)
def crafted():
    """Group BUT X: A, B (bg tables), C (no report), D+E (one concours report), F (not cross-checked), G (no bg table);
    group FCIL: H, I, J (generic label). Session 2025."""
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, fili VARCHAR, fil_lib_voe_acc VARCHAR,
        g_ea_lib_vx VARCHAR, ville_etab VARCHAR, acad_mies VARCHAR)""")
    fy = [(c, 2025, "BUT", "X", f"Etab {c}", "Ville", "Aca") for c in "ABCDEFG"] + [(c, 2025, "Autre formation", "FCIL", f"Etab {c}", "V", "A") for c in "HIJ"] \
        + [("K", 2025, "BUT", "Y", "Etab K", "Ville", "Aca")]           # Codex (PR #41): dDE also covers K, of another group
    con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?, ?)", fy)
    con.execute("CREATE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER, digest VARCHAR, recoupe BOOLEAN)")
    con.executemany("INSERT INTO core.rapport VALUES (?, ?, ?, ?)", [("A", 2025, "dA", True), ("B", 2025, "dB", True),
        ("D", 2025, "dDE", True), ("E", 2025, "dDE", True), ("F", 2025, "dF", False), ("G", 2025, "dG", True),
        ("H", 2025, "dH", True), ("I", 2025, "dI", True), ("J", 2025, "dJ", True), ("K", 2025, "dDE", True)])
    con.execute("""CREATE TABLE core.rapport_doublette (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR, rang INTEGER,
        doublette_key VARCHAR, autres BOOLEAN, confirmes INTEGER, en_position INTEGER)""")
    rows = []
    for cod, tab in {"A": [("MATHS+SES", 100, 40), ("HGGSP+SES", 50, 10), (None, 30, 6)],      # (key, confirmed, en position)
                     "B": [("MATHS+SES", 60, 30), (None, 40, 10)],
                     "D": [("MATHS+SES", 20, 12), ("HGGSP+SES", 10, 1)], "E": [("MATHS+SES", 20, 12), ("HGGSP+SES", 10, 1)],
                     "F": [("MATHS+SES", 500, 500)],
                     "H": [("MATHS+SES", 100, 100)], "I": [("MATHS+SES", 100, 100)], "J": [("MATHS+SES", 100, 100)],
                     "K": [("MATHS+SES", 40, 20)]}.items():
        for i, (k, c, p) in enumerate(tab):
            rows.append((cod, 2025, "bg", i + 1, k, k is None, c, p))
    rows.append(("A", 2025, "bt", 1, "STMG", False, 999, 999))                   # techno rows are not bac général
    con.executemany("INSERT INTO core.rapport_doublette VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    t = lambda crit, eds, opts=None: json.dumps({"criteres": crit, "eds": eds, "options_citees": opts or {}})  # noqa: E731
    texts = {
        "dA": t([{"champ": "Résultats académiques", "importance": "Important"}, {"champ": "Résultats académiques", "importance": "Essentiel"},
                 {"champ": "Savoir-être", "importance": "Complémentaire"}],
                {"pris_en_compte": "Oui", "liste": {"Série Générale": ["Mathématiques Spécialité", "Mathématiques Spécialité", HOSTILE]}},
                {"maths_expertes": ["q"]}),
        "dB": t([{"champ": "Résultat académique", "importance": "Très important"}, {"champ": "scolaires", "importance": "Important"}],
                {"pris_en_compte": "Non"}),
        "dDE": t([{"champ": "Motivation, connaissance de la", "importance": "Essentiel"}, {"champ": "Savoir-être", "importance": "Bulletins"}],
                 {"pris_en_compte": "Oui", "liste": {"Série Générale": ["Mathématiques Spécialité"], "Série STMG": ["Droit et économie"]}},
                 {"maths_expertes": ["q"], "lv3": ["q"]}),
        "dF": t([{"champ": "Savoir-être", "importance": "Essentiel"}], {"pris_en_compte": "Oui"}),
        "dG": t([{"champ": "Savoir-être", "importance": "Essentiel"}], {}),
    }
    con.execute("CREATE TABLE core.rapport_texte (digest VARCHAR, data VARCHAR)")
    con.executemany("INSERT INTO core.rapport_texte VALUES (?, ?)", list(texts.items()))
    return con

def reo_defs(js: str) -> str:
    """Sprint 21: the page's own isReo / bacProfile / REO_LABEL, for harnesses that render profile-reading cards."""
    one = [ln for ln in js.splitlines() if ln.startswith(("const isReo = ", "const REO_LABEL = "))]
    fn = re.search(r"^function bacProfile\(\) \{.*?^\}", js, re.M | re.S).group(0)
    return "\n".join(one) + "\n" + fn + "\n"



@check("K1 crafted reports: pooled rates over the reports detailing the doublette, concours once, no Autres, no unchecked report, generic labels, thresholds, jury counts")
def k1(c: Ctx):
    S = M["SB"]
    con = crafted()
    S.build(con)
    got = {k: v for k, *v in con.execute("""SELECT doublette_key, n_rapports, confirmes, en_position, tous_confirmes, tous_en_position
        FROM mart.semblable_dbl WHERE filiere = 'X' ORDER BY 1""").fetchall()}
    # MATHS+SES: A, B, DE (F not cross-checked): 3 reports, 100+60+20 = 180 confirmed, 40+30+12 = 82; all bg of A, B, DE:
    # A 180/56, B 100/40, DE 30/13 -> 310 / 109. HGGSP+SES: A, DE: 2 reports (under the threshold), 60 / 11; all: 210 / 69
    want = {"HGGSP+SES": [2, 60, 11, 210, 69], "MATHS+SES": [3, 180, 82, 310, 109]}
    sem = S.for_formation(con, "C", 2025)
    keys = [x["key"] for x in sem["doublettes"]] if sem else None
    ms = S.pick(sem, "MATHS+SES") or {}
    rates = ms.get("taux") == round(100 * 82 / 180, 1) and ms.get("tous_taux") == round(100 * 109 / 310, 1)
    generic = S.for_formation(con, "H", 2025) is None
    peers = [f["cod_aff_form"] for f in sem["formations"]] if sem else None
    # jury: A, B, DE, G (F not cross-checked): 4 reports
    j = sem["jury"] if sem else {}
    champs_ok = j and j["n"] == 4 and j["champs"]["resultats"] == {"Essentiel": 1, "Très important": 1, "Important": 0, "Complémentaire": 0} \
        and j["champs"]["savoir_etre"] == {"Essentiel": 1, "Très important": 0, "Important": 0, "Complémentaire": 1} \
        and j["champs"]["engagements"] == {"Essentiel": 0, "Très important": 0, "Important": 1, "Complémentaire": 0} \
        and j["champs"]["motivation"]["Essentiel"] == 1
    eds_ok = j and j["eds"]["oui"] == 2 and j["eds"]["non"] == 1 and j["eds"]["non_dit"] == 1 \
        and j["eds"]["generale"] == {"Mathématiques Spécialité": 2, HOSTILE: 1} and j["eds"]["autres"] == {"Série STMG": {"Droit et économie": 1}}
    opts_ok = j and j["options"] == {"maths_expertes": 2, "lv3": 1}
    # a report covering two groups counts once in EACH, read from that group's own formation (K's table, not D's)
    other = con.execute("SELECT doublette_key, n_rapports, confirmes, en_position, tous_confirmes FROM mart.semblable_dbl WHERE filiere = 'Y'").fetchall()
    other_j = con.execute("SELECT n_rapports FROM mart.semblable_jury WHERE filiere = 'Y'").fetchall()
    shared = other == [("MATHS+SES", 1, 40, 20, 40)] and other_j == [(1,)]
    ok = got == want and keys == ["MATHS+SES"] and rates and generic and peers == ["A", "B", "D", "E", "G"] and champs_ok and eds_ok and opts_ok \
        and shared
    return ok, (f"pool {got == want} ({got}); served {keys}; rates {rates}; generic label {generic}; peers {peers}; shared report in both groups {shared}; "
                f"jury fields {bool(champs_ok)}; specialties {bool(eds_ok)}; options {bool(opts_ok)}")


def _jury_independent(texts):
    """An independent reading of the jury counts (own field mapping, own importance order)."""
    rank = {"Essentiel": 0, "Très important": 1, "Important": 2, "Complémentaire": 3}
    pats = [("resultats", r"r[ée]sultat"), ("competences", r"comp[ée]tence|savoir-\s?faire"), ("savoir_etre", r"savoir[- ][êe]tre"),
            ("motivation", r"motivation|coh[ée]rence du projet|connaissance de la"), ("engagements", r"engagement|int[ée]r[êe]t|extra|scolaires")]
    out = {k: dict.fromkeys(rank, 0) for k, _ in pats}
    for t in texts:
        best = {}
        for cr in t.get("criteres") or []:
            lab = " ".join(str(cr.get("champ") or "").lower().split())
            k = next((k for k, p in pats if re.search(p, lab)), None)
            i = cr.get("importance")
            if k and i in rank and (k not in best or rank[i] < rank[best[k]]):
                best[k] = i
        for k, i in best.items():
            out[k][i] += 1
    return out


@check("K2 warehouse re-derivation: pooled doublettes by SQL, jury counts from the texts with an independent mapping")
def k2(c: Ctx):
    con = c.con
    has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'semblable_dbl'").fetchone()[0]
    if not has:
        return False, "mart.semblable_dbl missing"
    want = con.execute(f"""
        WITH rep AS (SELECT r.session, f.fili, f.fil_lib_voe_acc fil, r.digest, min(r.cod_aff_form) first_cod
                     FROM core.rapport r JOIN core.formation_year f USING (cod_aff_form, session)
                     WHERE coalesce(r.recoupe, true) AND f.fil_lib_voe_acc NOT IN ({", ".join(repr(x) for x in sorted(SB.GENERIC))})
                       AND f.fili IS NOT NULL
                     GROUP BY ALL),
             first AS (SELECT r.session, f.fili, f.fil_lib_voe_acc fil, r.digest, min(d.cod_aff_form) cod FROM core.rapport r
                       JOIN core.formation_year f USING (cod_aff_form, session)
                       JOIN core.rapport_doublette d USING (cod_aff_form, session) WHERE d.bac = 'bg' AND coalesce(r.recoupe, true) GROUP BY ALL),
             rows AS (SELECT rep.session, rep.fili, rep.fil, rep.digest, d.doublette_key k, d.autres, d.confirmes c, d.en_position p
                      FROM rep JOIN first USING (session, fili, fil, digest)
                      JOIN core.rapport_doublette d ON d.session = rep.session AND d.bac = 'bg' AND d.cod_aff_form = first.cod),
             tot AS (SELECT session, fili, fil, digest, sum(c) tc, sum(p) tp FROM rows GROUP BY ALL)
        SELECT rows.session, rows.fili, rows.fil, k, count(*), sum(c), sum(p), sum(tc), sum(tp)
        FROM rows JOIN tot USING (session, fili, fil, digest)
        WHERE NOT coalesce(autres, false) AND k IS NOT NULL GROUP BY ALL ORDER BY ALL""").fetchall()
    got = con.execute("SELECT * FROM mart.semblable_dbl ORDER BY ALL").fetchall()
    # Codex (PR #41): every group compared, those a shared report spans included (it counts once in each)
    w, g = [tuple(r) for r in want], [tuple(r) for r in got]
    dbl_ok = w == g and (len(g) > 0 or not c.real)
    # jury counts of a sample of groups, from the texts
    from suptracker import rapports as RP
    groups = con.execute("SELECT session, fili, filiere, n_rapports, data FROM mart.semblable_jury ORDER BY hash(filiere) LIMIT 25").fetchall()
    bad = []
    for s, fi, fl, n, data in groups:
        digs = [d for (d,) in con.execute("""SELECT DISTINCT r.digest FROM core.rapport r JOIN core.formation_year f USING (cod_aff_form, session)
            WHERE r.session = ? AND f.fili = ? AND f.fil_lib_voe_acc = ? AND coalesce(r.recoupe, true)""", [s, fi, fl]).fetchall()]
        texts = [json.loads(t) for t in (RP.texte(con, d) for d in digs) if t]
        if len(texts) != n or json.loads(data)["champs"] != _jury_independent(texts):
            bad.append(fl)
    jury_ok = not bad and (len(groups) > 0 or not c.real)
    return dbl_ok and jury_ok, f"pooled rows {len(g)} re-derived equal {w == g}; jury groups checked {len(groups)}, wrong {bad[:3]}"


@check("K3 a formation never reads its own report here: served figures = the pool of the OTHER formations; list excludes it")
def k3(c: Ctx):
    S, con = M["SB"], c.con
    cods = [x for (x,) in con.execute("""SELECT f.cod_aff_form FROM core.formation_year f
        WHERE f.session = (SELECT max(session) FROM core.formation_year)
          AND f.cod_aff_form NOT IN (SELECT cod_aff_form FROM core.rapport_doublette WHERE bac = 'bg' AND session = f.session)
        ORDER BY hash(f.cod_aff_form) LIMIT 60""").fetchall()]
    bad, seen = [], 0
    for cod in cods:
        sem = S.for_formation(con, cod)
        if not sem:
            continue
        seen += 1
        if cod in [f["cod_aff_form"] for f in sem["formations"]]:
            bad.append(f"{cod} lists itself")
        for x in sem["doublettes"]:
            # the formation has no bac général row: the pool of the others IS the served row
            n_self = con.execute("""SELECT count(*) FROM core.rapport_doublette d JOIN core.rapport r USING (cod_aff_form, session)
                WHERE d.cod_aff_form = ? AND d.bac = 'bg' AND r.session = ?""", [cod, sem["session"]]).fetchone()[0]
            if n_self:
                bad.append(f"{cod} pooled itself")
            if x["n_rapports"] < S.MIN_REPORTS or x["confirmes"] < S.MIN_CANDIDATS:
                bad.append(f"{cod} under threshold {x['key']}")
    crafted_con = crafted(); S.build(crafted_con)
    g = S.for_formation(crafted_con, "G", 2025)          # G has texts: its jury count includes it, so the page never uses it there
    own_jury = g is not None and g["jury"]["n"] == 4 and "G" not in [f["cod_aff_form"] for f in g["formations"]]
    page = "juryCard(d.rapport) || semblablesJuryCard(d.semblables, d.rapport)" in c.js
    ok = not bad and own_jury and page and (seen > 0 or not c.real)
    return ok, f"{seen} formations without a bac général table read; problems {bad[:3]}; own texts first {page and own_jury}"


def _js_estimate(c: Ctx, cases):
    part = block(c.js, "function estimateSemblable(", "const ownHasBg")
    prog = part + """
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([s, sem, k]) => estimateSemblable({ bg: s }, sem, k))));  // the page passes every route"""
    return node(prog, cases)


@check("K4 estimate: page and Python twins agree, capped at 100, same shape as the national estimate")
def k4(c: Ctx):
    S = M["SB"]
    sem = {"doublettes": [{"key": "MATHS+SES", "label": "Maths + SES", "n_rapports": 5, "taux": 45.6, "tous_taux": 30.4},
                          {"key": "HLP+SES", "label": "HLP + SES", "n_rapports": 4, "taux": 90.0, "tous_taux": 20.0}]}
    ser = {"taux": 40.0, "fragile": False, "trend": [{"session": 2024, "taux": 35.0}, {"session": 2025, "taux": 40.0}]}
    cases = [[ser, sem, "MATHS+SES"], [ser, sem, "HLP+SES"], [ser, sem, "PC+SVT"], [{"taux": None, "trend": []}, sem, "MATHS+SES"]]
    if c.real:
        for (cod,) in c.con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
                ORDER BY hash(cod_aff_form) LIMIT 40""").fetchall():
            from suptracker import doublettes as D
            s = S.for_formation(c.con, cod)
            if s and s["doublettes"]:
                cases.append([D.series(c.con, cod)["bg"], s, s["doublettes"][0]["key"]])
    py = [S.estimate(a, b, k) for a, b, k in cases]
    js = _js_estimate(c, cases)
    if js is None:
        return True, "node not installed"
    if isinstance(js, dict):
        return False, js["error"]
    same = all((p is None) == (j is None) and (p is None or (abs(p["taux"] - j["taux"]) < 0.051 and p["base"] == j["base"]
               and [t["taux"] for t in p["trend"]] == [t["taux"] if t["taux"] is None else round(t["taux"], 1) for t in j["trend"]]))
               for p, j in zip(py, js))
    hand = py[0]["taux"] == round(40.0 * 45.6 / 30.4, 1) and py[1]["taux"] == 100.0 and py[2] is None and py[3] is None
    shape = set(py[0]) >= {"taux", "base", "ratio", "mine", "tous", "n_rapports", "estimation", "trend"}
    return same and hand and shape, f"{len(cases)} cases, twins agree {same}; hand-computed and capped {hand}; shape {shape}"


@check("K5 one figure everywhere: own bac général table first, then the similar formations, then the group; evolution and Mes vœux agree")
def k5(c: Ctx):
    js = c.js
    card = "const semEst = own.hasBg ? null : estimateSemblable(d.series, sem, dkey0);" in js \
        and "const est = own.hasBg || semEst ? null : estimateDoublette(d.series, g, dkey);" in js \
        and "${doubletteCard(d.doublettes, d.rapport, d.semblables)}" in js
    evo = "const est = ownHasBg(rp) ? null : sEst || estimateDoublette(d.series, g, dk);" in js \
        and "${doubletteCharts(f.doublettes, years, f.semblables, f.rapport)}" in js
    vx = ": v.semblable ? `${pct1(v.semblable.taux)}" in js
    py = (ROOT / "suptracker" / "voeux.py").read_text()
    vx_py = 'if b and (b["doublettes"].get("bg") or []):\n            return None' in py and "SB.estimate(DB.series(con, cod)[\"bg\"], SB.for_formation(con, cod), dkey)" in py
    api = '"semblables": SB.for_formation(_con().cursor(), rec["cod_aff_form"], rec["session"])' in (ROOT / "suptracker" / "api.py").read_text()
    ok = card and evo and vx and vx_py and api
    return ok, f"formation card {card}; evolution {evo}; Mes vœux page {vx} and server {vx_py}; API {api}"


def _render(c: Ctx, sem, rp=None, dkey="MATHS+SES", profile=None):
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct1 = ", "const rateBar = ")))
    part = block(c.js, "function estimateSemblable(", "// Codex (PR #37): the pooled figures")
    rp_consts = block(c.js, "const RP_SPE = ", "const rpText")
    jury = block(c.js, "const SEM_CRIT_N", "// the 4-year curves of the evolution page:")
    prog = helpers + "\nconst store = { get: () => JSON.parse(process.env.PROFILE || 'null') };\n" + reo_defs(c.js) + rp_consts + part + jury + """
const [sem, rp, dkey] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ jury: semblablesJuryCard(sem, rp), dbl: semblablesDoublettes(sem, dkey, estimateSemblable({ bg: { taux: 40, trend: [] } }, sem, dkey)) }));"""
    n = shutil.which("node")
    if not n:
        return None
    import os
    r = subprocess.run([n, "-e", prog], input=json.dumps([sem, rp, dkey]), capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PROFILE": json.dumps(profile or {"spe1": "MATHS", "spe2": "SES"})})
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-600:]}


HOSTILE_SEM = {"session": 2025, "fili": "BUT", "filiere": HOSTILE, "min_rapports": 3, "min_candidats": 20,
               "champs": {k: lab for k, lab, _ in SB.CHAMPS},
               "doublettes": [{"key": "MATHS+SES", "label": HOSTILE, "n_rapports": 4, "confirmes": 100, "en_position": 40, "taux": 40.0, "tous_taux": 30.0}],
               "jury": {"n": 4, "champs": {k: {"Essentiel": 1, "Très important": 1, "Important": 1, "Complémentaire": 0} for k, _, _ in SB.CHAMPS},
                        "eds": {"oui": 3, "non": 1, "non_dit": 0, "generale": {HOSTILE: 2, "Mathématiques Spécialité": 3}, "autres": {HOSTILE: {HOSTILE: 1}}},
                        "options": {HOSTILE: 1, "maths_expertes": 2}},
               "formations": [{"cod_aff_form": "1", "etablissement": HOSTILE, "ville": HOSTILE, "academie": HOSTILE}]}


@check("K6 pages on hostile data (Node): escaped, labelled cells, 'pas le rapport de cette formation', counts not means, links")
def k6(c: Ctx):
    o = _render(c, HOSTILE_SEM)
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    j, d = o["jury"], o["dbl"]
    raw = "<img" in j or "<img" in d
    cells = re.findall(r'<td class="num"([^>]*)>', j + d)
    unlabelled = [x for x in cells if "data-label" not in x]
    caveats = "pas le rapport de cette formation" in j and "jamais une moyenne" in j and "pas des chances d'admission" in j \
        and "sa fiche Parcoursup fait foi" in j and "ce ne sont pas des chances d'admission" in d and "Ce ne sont pas les chiffres de cette formation" in d
    counts = "3 rapports sur 4" in j and "Non noté" in j and not re.search(r"(?i)moyenne de|en moyenne", j)
    links = 'href="#/f/1"' in j
    mark = "<mark>Mathématiques Spécialité</mark>" in j
    mine = 'class="dbl-mine"' in d and "Vos spécialités" in d
    ok = not raw and not unlabelled and caveats and counts and links and mark and mine
    return ok, (f"raw tag {raw}; unlabelled cells {len(unlabelled)}; caveats {caveats}; counts {counts}; links {links}; "
                f"student's specialty marked {mark}; student's doublette first {mine}")


def _bar(c: Ctx, profile, ids, answer):
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    bar = block(c.js, "// ---- point 4 of the UI brief", "// ---- SVG primitives")
    zones = block(c.js, "const ZONES = {", "const GATES")
    line = block(c.js, "function profileLine(", "async function viewSearch(")
    prog = helpers + """
const [profile, ids, answer] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const el = { hidden: true, innerHTML: "" };
const chip = { hidden: true, innerHTML: "", classList: { toggle() {} }, setAttribute() {} };   // R1: the header chip, its own element
const ICONS = { edit: "", profile: "" };
const document = { getElementById: (id) => (id === "profile-chip" ? chip : el) };
const store = { get: (k, d) => (k === "profile" ? profile : d) };
const voeux = { get: () => ids };
const calls = [];
const api = (u) => { calls.push(u); return Promise.resolve(answer); };
""" + zones + line + bar + """
profileBar.render("home");
setTimeout(() => { process.stdout.write(JSON.stringify({ html: el.innerHTML, hidden: el.hidden, calls,
  query: profile ? vxQuery(ids, vxProfile(profile)).toString() : null })); }, 50);"""
    return node(prog, [profile, ids, answer])


@check("K7 profile bar (Node): escaped profile, the Mes vœux query, alert from the server message only, no call for an empty list")
def k7(c: Ctx):
    z = {"securite": 0, "cible": 2, "ambitieux": 1, "hors_profil": 1, "indetermine": 0, "non_ouvert": 0, "non_situe": 0}
    prof = {"serie": "bg", "spe1": HOSTILE, "spe2": "SES", "mention": "b", "academie": HOSTILE}
    a = _bar(c, prof, ["123", "456"], {"lecture": {"zones": z, "messages": [{"niveau": "warn", "code": "aucune_securite"}]}})
    if a is None:
        return True, "node not installed"
    if "error" in a:
        return False, a["error"]
    b = _bar(c, prof, ["123"], {"lecture": {"zones": {**z, "securite": 1}, "messages": [{"niveau": "info", "code": "equilibree"}]}})
    # an uncertain safety is not sure (voeux.read_list): the server warns although one vœu is in the safety zone
    u = _bar(c, prof, ["123"], {"lecture": {"zones": {**z, "securite": 1}, "messages": [{"niveau": "warn", "code": "aucune_securite"}]}})
    e = _bar(c, prof, [], {})
    n = _bar(c, None, ["123"], {})
    h = a["html"]
    escaped = "<img" not in h and "&lt;img" in h
    counts = "0 sécurité" in h and "2 cible" in h and "1 ambitieux" in h and "1 autre" in h
    alert = "Aucun vœu de sécurité sûr" in h and "Aucun vœu de sécurité" not in b["html"] and "Aucun vœu de sécurité sûr" in u["html"]
    same_query = a["calls"] == [f"/api/voeux?{a['query']}"] and "const qs = vxQuery(ids, prof);" in c.js
    empty = e["calls"] == [] and "aucun pour l'instant" in e["html"]
    noprof = n["calls"] == [] and 'href="#/profil"' in n["html"]
    shown = not a["hidden"]
    ok = escaped and counts and alert and same_query and empty and noprof and shown
    return ok, f"escaped {escaped}; counts {counts}; alert only from the server {alert}; same query as Mes vœux {same_query}; empty list {empty}; no profile {noprof}"


@check("K8 wording and wiring: no chance or probability, vouvoiement, the bar in the shell, release guards, features")
def k8(c: Ctx):
    views = block(c.js, "// ---- point 4 of the UI brief", "// ---- SVG primitives") + block(c.js, "function estimateSemblable(", "// Codex (PR #37)") \
        + block(c.js, "const SEM_CRIT_N", "// the 4-year curves of the evolution page:")
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", views)
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    shell = 'id="profile-bar"' in c.html and c.html.index('id="profile-bar"') < c.html.index('<main id="view"')
    route = 'profileBar.render(!a && !pathRoute(location.pathname, location.hash) ? "accueil" : TAB_OF[a] || "home");' in c.js and 'if (k === "profile") profileBar.render();' in c.js
    rel = (ROOT / "tests" / "test_release.py").read_text()
    guards = '"profil_visible": ("app.js", "const profileBar = {")' in rel and '"formations_semblables": ("app.js", "function semblablesJuryCard(")' in rel
    from suptracker import api
    feat = {"profil_visible", "formations_semblables"} <= set(api.FEATURES)
    ok = not chance and not tu and shell and route and guards and feat
    return ok, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; bar in the shell {shell}; refreshed on navigation and profile change {route}; release {guards}; features {feat}"


PY_MUTANTS = [
    # the reports print "Autres doublettes" without a key: pooling them would need one (the realistic version of the bug)
    ("autres pooled", "            if autres or not key:\n                continue\n", "            if not key:\n                key = \"AUTRES\"\n"),
    ("all bac général over every report", "a[3] += tc; a[4] += tp", "a[3] += 0; a[4] += 0"),
    ("unchecked reports used", "WHERE coalesce(r.recoupe, true) AND f.fil_lib_voe_acc IS NOT NULL", "WHERE f.fil_lib_voe_acc IS NOT NULL"),
    ("concours counted twice", "        covers.setdefault((s, fili, fil, dig), set()).add(cod)", "        covers.setdefault((s, fili, fil, dig + cod), {cod})"),
    ("shared report kept in one group only", "        covers.setdefault((s, fili, fil, dig), set()).add(cod)",
     "        if any(k[3] == dig and k[:3] != (s, fili, fil) for k in covers):\n            continue\n        covers.setdefault((s, fili, fil, dig), set()).add(cod)"),
    ("shared report read from another group's formation", "first = next((c for c in sorted(cods) if (c, s) in tables), None)",
     "first = next((c for c in sorted(x for k, v in covers.items() if k[0] == s and k[3] == dig for x in v) if (c, s) in tables), None)"),
    ("generic labels kept", 'GENERIC = {"FCIL", "Licence professionnelle"}', "GENERIC = set()"),
    ("threshold dropped", "if n >= MIN_REPORTS and c >= MIN_CANDIDATS]", "if n >= 1]"),
    ("lowest importance kept", "IMPORTANCES.index(imp) < IMPORTANCES.index(best[k])", "IMPORTANCES.index(imp) > IMPORTANCES.index(best[k])"),
    ("self listed", "AND coalesce(r.recoupe, true) AND r.cod_aff_form <> ?", "AND coalesce(r.recoupe, true) AND r.cod_aff_form <> ? || 'x'"),
    ("estimate uncapped", 'return {"taux": round(min(100.0, series_bg["taux"] * r), 1)', 'return {"taux": round(series_bg["taux"] * r, 1)'),
]
JS_MUTANTS = [
    ("label unescaped", "${x === mine ? \"Vos spécialités : \" : \"\"}${esc(x.label)}", "${x === mine ? \"Vos spécialités : \" : \"\"}${x.label}"),
    ("establishment unescaped", '<a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>', '<a href="#/f/${esc(f.cod_aff_form)}">${f.etablissement}</a>'),
    ("profile unescaped", "const ser = { bg: \"bac général\", bt: \"bac technologique\"", "const esc = (s) => s; const ser = { bg: \"bac général\", bt: \"bac technologique\""),
    ("figure without its label", '<td class="num" data-label="Rapports">', '<td class="num">'),
    ("not-own caveat dropped", '<span class="estim">pas le rapport de cette formation</span>', ""),
    ("estimate beside a published table", "const semEst = own.hasBg ? null : estimateSemblable(d.series, sem, dkey0);", "const semEst = estimateSemblable(d.series, sem, dkey0);"),
    ("estimate uncapped (page)", "Math.round(Math.min(100, v * r) * 10) / 10);\n  return { taux: cap(bg.taux), base: bg.taux, ratio: Math.round(r * 1000) / 1000, source: \"semblables\"",
     "Math.round(v * r * 10) / 10);\n  return { taux: cap(bg.taux), base: bg.taux, ratio: Math.round(r * 1000) / 1000, source: \"semblables\""),
    ("alert computed in the page", 'd.lecture.messages.some((m) => m.code === "aucune_securite")', "!(d.lecture.zones.securite > 0)"),
    ("bar sends its own query", "const k = vxQuery(ids, prof).toString();", "const k = vxQuery(ids, { ...prof, academie: \"\" }).toString();"),
    ("call with an empty list", "if (!ids.length) { this.key = \"\"; this.data = null; list =", "if (false) { list ="),
    ("bar out of the shell", '<aside id="profile-bar" class="profile-bar" aria-label="Votre profil et vos vœux" hidden></aside>', ""),
]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "semblables.py"
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType("suptracker._mut_sb")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules["suptracker._mut_sb"] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("K9 mutation test: pooling, thresholds, own report, estimate, escaping, labels, wording and bar bugs are each caught")
def k9(c: Ctx):
    fns = [k1, k2, k3, k4, k5, k6, k7, k8]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    for name, old, new in PY_MUTANTS:
        m = mutated(old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M["SB"] = M["SB"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["SB"] = saved
            sys.modules.pop("suptracker._mut_sb", None)
    for name, old, new in JS_MUTANTS:
        target = "html" if "profile-bar" in old and "aside" in old else "js"
        src = getattr(c, target)
        if old not in src:
            missed.append(f"{name} (anchor gone)"); continue
        setattr(c, target, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, target, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
