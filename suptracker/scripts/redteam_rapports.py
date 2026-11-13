"""Red team of the "Rapports publics" sprint: each formation's own public report (archived PDF), its doublette table and
the jury's texts.
    python scripts/redteam_rapports.py [--db data/suptracker.duckdb] [--real]
  R1 parser on the committed probe PDFs: every formation read from its tables; on the real warehouse, the candidates who
     confirmed (summed over its groups) EQUAL the SIES nb_voe_pp; a known table (31899, 2025) read cell by cell; the
     jury's signature is never kept
  R2 selection rules re-derived on a CRAFTED harvest built from the warehouse: a report is kept only when confirmed =
     nb_voe_pp; a code printed in the tables wins, an old report goes through its link's g_ti_cod and is checked the same
     way; one report per (code, session), the latest capture; a concours report feeds each of its formations
  R3 figures: every served row equals the harvested counts; the rate is en_position / confirmed recomputed independently;
     the student's row is their doublette, else the formation's own "Autres doublettes" (Python and page twins agree)
  R4 page run with Node on hostile texts: escaped everywhere, every stacked figure labelled, the estimate is replaced by the
     published figure when the report has bac général rows (and kept otherwise), source and "pas des chances" shown
  R5 wording and data: the jury's options only as quotes, the specialty labels the page highlights = journey.SPECIALTIES,
     vouvoiement, never a probability; the sources register lists the archive
  R6 mutation test (mutants built in memory, no source file written)
  R7 repaired files (harvest --repair): a probe PDF cut after its last page is rebuilt and read exactly like the intact
     file; a file cut inside its pages is never used (empty pages or no signature line); the build keeps "ok_repare"
     rows and drops "incomplet" ones (own mutants: completeness ignored, repaired rows dropped)
  R8 live harvest (rapports_live, fake Parcoursup): a closed site writes nothing; an open one reads the fiche's report link
     (relative, &amp;-escaped; another host or a javascript: link is ignored), stores each PDF once (archive digest form,
     source "live"), resumes without duplicates; the build keeps the same verification and credits the fiche, not the archive
     (own mutants)
  R9 not yet cross-checked (owner's choice): a report read on the LIVE fiche, for a session SIES has not published, with its
     code printed and coherent counts, is kept with recoupe = false; an archived one, one without a printed code, one of a
     published session that does not match, or one with en position > confirmed is not; the page marks it "pas encore recoupé
     avec les chiffres de <session>" on both cards and in Mes vœux (Node)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from suptracker import journey as J  # noqa: E402
from suptracker import rapports as RP  # noqa: E402
import rapports_harvest as HARVEST  # noqa: E402
import rapports_live as LIVE  # noqa: E402
import rapports_parse as PARSE  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
PROBE = ROOT / "data" / "rapports" / "probe" / "pdf"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>'
M = {"RP": RP, "PARSE": PARSE, "H": HARVEST, "L": LIVE}


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
        self.tmp = Path(tempfile.mkdtemp(prefix="rt_rapports_"))
        self.fy = self.con.execute("""SELECT cod_aff_form, session, nb_voe_pp, ran_grp1, ran_grp2, ran_grp3 FROM core.formation_year
                                      WHERE nb_voe_pp > 30 ORDER BY hash(cod_aff_form || session) LIMIT 8""").fetchall()
        self.parsed = {p.name: PARSE.parse(p.read_bytes()) for p in sorted(PROBE.glob("*.pdf"))} if PROBE.exists() else {}


# ------------------------------------------------------------------ the crafted harvest (independent of rapports.build)
def craft(c: Ctx, dest: Path) -> dict:
    """Write a harvest from the warehouse's own figures and return what the build MUST keep, written independently."""
    dest.mkdir(parents=True, exist_ok=True)
    (a, sa, va, *_), (b, sb, vb, *_), (d, sd, vd, *_), (f, sf, vf, *_) = c.fy[:4]
    # a concours report prints formations of ONE session: the second one is taken from the same session
    e, se, ve = c.con.execute("""SELECT cod_aff_form, session, nb_voe_pp FROM core.formation_year WHERE session = ? AND nb_voe_pp > 30
                                 AND cod_aff_form NOT IN (?, ?, ?, ?) ORDER BY hash(cod_aff_form) LIMIT 1""", [sf, a, b, d, f]).fetchone()
    U = "https://dossier.parcoursup.fr/Candidats/public/fiches/telechargerRapportPublic?g_ea_cod=0000000X&g_ti_cod={}&c_ja_cod=1"
    sn = max(x[1] for x in c.fy + [(e, se)]) + 1            # a session SIES has not published
    idx = [  # digest, ts, url, session, codes, source
        ("A1", "20250101000000", U.format(a), sa, a),            # printed code, verified, older capture
        ("A2", "20260101000000", U.format(a), sa, a),            # same report, later capture: wins
        ("B1", "20260101000000", U.format(b), sb, b),            # confirmed off by one: rejected
        ("D1", "20240101000000", U.format(d), sd, ""),           # old report: no printed code, g_ti_cod checked
        ("E1", "20240101000000", U.format("999999"), sb, ""),    # old report whose g_ti_cod is another code: rejected
        ("F1", "20260101000000", U.format(f), sf, f"{f};{e}"),   # a concours report printing two formations
        ("L1", "20261215000000", U.format(a), sn, a, "live"),    # live, unpublished session, code printed: kept, not cross-checked
        ("L2", "20261215000000", U.format(b), sn, b),            # archived, unpublished session: rejected
        ("L3", "20261215000000", U.format(d), sn, "", "live"),   # live, no printed code: rejected
        ("L4", "20261215000000", U.format(a), sa, a, "live"),    # live, published session, does not match: rejected
        ("L5", "20261215000000", U.format(f), sn, f, "live"),    # live, en position > confirmed: rejected
        ("L6", "20261215000000", U.format("777777"), sa, "777777", "live"),   # live, published session, code SIES lacks: rejected
    ]
    syn = [("A1", a, va, 5), ("A2", a, va, 6), ("B1", b, vb + 1, 7), ("D1", "", vd, 8), ("E1", "", vb, 9),
           ("F1", f, vf, 10), ("F1", e, ve, 11), ("L1", a, 30, 10), ("L2", b, 30, 10), ("L3", "", 30, 10), ("L4", a, va + 2, 10),
           ("L5", f, 10, 20), ("L6", "777777", 30, 10)]
    with open(dest / "pdf_index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["timestamp", "original", "digest", "length", "status", "session", "codes", "n_doublettes", "n_synthese", "error", "source"])
        for dg, ts, url, s, codes, *src in idx:
            w.writerow([ts, url, dg, 1, "ok", s, codes, 0, 0, "", (src or [""])[0]])
    with open(dest / "synthese.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["digest", "timestamp", "session", "code", "jury", "groupe", "places", "confirmes", "classes", "en_position", "acceptes"])
        for dg, code, conf, pos in syn:
            s = next(x[3] for x in idx if x[0] == dg)
            w.writerow([dg, "", s, code, "J", "Tous les candidats", 10, conf, conf, pos, 1])
    dbl = [("A2", a, "Baccalauréat Général", "Mathématiques Spécialité & Physique-Chimie Spécialité", 40, 30, 20, 3),
           ("A2", a, "Baccalauréat Général", "Autres doublettes", 25, 10, 5, 1),
           ("A2", a, "Baccalauréat Technologique", "Sciences et technologies de l'industrie & " + HOSTILE, 9, 3, 3, 0),
           ("A1", a, "Baccalauréat Général", "Mathématiques Spécialité & Physique-Chimie Spécialité", 1, 1, 1, 1),   # superseded
           ("B1", b, "Baccalauréat Général", "Autres doublettes", 30, 10, 9, 1),                                   # rejected report
           ("D1", "", "Baccalauréat Général", "Sciences Economiques et Sociales Spécialité & Mathématiques Spécialité", 50, 20, 0, 0),
           ("F1", f, "Baccalauréat Général", "Autres doublettes", 70, 60, 50, 9),
           ("F1", e, "Baccalauréat Général", "Autres doublettes", 80, 60, 40, 8)]
    with open(dest / "doublettes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["digest", "timestamp", "session", "code", "jury", "bac", "doublette", "confirmes", "classes", "en_position", "acceptes"])
        for dg, code, bac, lab, *n in dbl:
            w.writerow([dg, "", "", code, "J", bac, lab, *n])
    with open(dest / "masked.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["digest", "timestamp", "session", "code", "jury", "bac"])
        w.writerow(["A2", "", "", a, "J", "Baccalauréat Professionnel"])
    with gzip.open(dest / "qualitatif.jsonl.gz", "wt", encoding="utf-8") as g:
        for dg in ("A2", "F1", "B1"):
            g.write(json.dumps({"digest": dg, "criteres": [{"champ": HOSTILE, "critere": HOSTILE, "elements": HOSTILE, "importance": "Essentiel"}],
                                "eds": {"pris_en_compte": "Oui", "poids": HOSTILE, "liste": {"Série Générale": ["Mathématiques Spécialité", HOSTILE],
                                        "Série STL": ["Physique-Chimie et Mathématiques", "Critères « parcours en cordée de la réussite »", "Oui"]}},
                                "options_citees": {"maths_expertes": [HOSTILE + " mathématiques expertes"]}, "eliminatoires": HOSTILE,
                                "modalites": HOSTILE, "algorithme": HOSTILE, "conseils": HOSTILE}) + "\n")
    want = {(a, sa): ("A2", va), (d, sd): ("D1", vd), (f, sf): ("F1", vf), (e, sf): ("F1", ve), (a, sn): ("L1", 30)}
    rows = {(a, sa): [("bg", "MATHS+PC", False, 40, 20), ("bg", None, True, 25, 5), ("bt", None, False, 9, 3)],
            (d, sd): [("bg", "MATHS+SES", False, 50, 0)], (f, sf): [("bg", None, True, 70, 50)], (e, sf): [("bg", None, True, 80, 40)]}
    return {"want": want, "rows": rows, "a": (a, sa), "pending": {(a, sn)}, "masked": {(a, sa, "bp")}, "e_row": (e, se, ve, None, None, None)}


def built(c: Ctx):
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA core")
    mem.execute("CREATE TABLE core.formation_year AS SELECT * FROM (VALUES (NULL::VARCHAR, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER)) t(cod_aff_form, session, nb_voe_pp, ran_grp1, ran_grp2, ran_grp3) WHERE false")
    spec = craft(c, c.tmp / "h")
    mem.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?)", c.fy + [spec["e_row"]])
    res = M["RP"].build(mem, c.tmp / "h")
    return mem, spec, res


# ------------------------------------------------------------------ checks


def reo_defs(js: str) -> str:
    """Sprint 21: the page's own isReo / bacProfile / REO_LABEL, for harnesses that render profile-reading cards."""
    one = [ln for ln in js.splitlines() if ln.startswith(("const isReo = ", "const REO_LABEL = "))]
    fn = re.search(r"^function bacProfile\(\) \{.*?^\}", js, re.M | re.S).group(0)
    return "\n".join(one) + "\n" + fn + "\n"



@check("R1 parser on the committed probe PDFs: formations, SIES identity on real data, a known table, no signature kept")
def r1(c: Ctx):
    if not c.parsed:
        return True, "no probe PDF committed"
    bad, n = [], 0
    for name, p in c.parsed.items():
        if not p["codes"] or p["session"] is None:
            bad.append((name, "no code/session"))
        for code in p["codes"]:
            n += 1
            conf = sum(x["confirmes"] or 0 for x in p["synthese"] if x["code"] == code)
            if c.real:
                ref = c.con.execute("SELECT nb_voe_pp FROM core.formation_year WHERE cod_aff_form = ? AND session = ?", [code, p["session"]]).fetchone()
                if not ref or ref[0] != conf:
                    bad.append((name, code, conf, ref))
        blob = json.dumps({k: p.get(k) for k in ("eliminatoires", "modalites", "algorithme", "conseils")}, ensure_ascii=False)
        if re.search(r"Signature\s*:", blob):
            bad.append((name, "signature kept"))
    k = next((p for n_, p in c.parsed.items() if "31899" in n_), None)
    known = k is not None and [(x["doublette"], x["confirmes"], x["classes"], x["en_position"], x["acceptes"]) for x in k["doublettes"] if x["bac"].startswith("Baccalauréat Général")] == [
        ("Mathématiques Spécialité & Sciences de la vie et de la Terre Spécialité", 35, 35, 26, 2),
        ("Physique-Chimie Spécialité & Sciences de la vie et de la Terre Spécialité", 34, 34, 30, 2),
        ("Autres doublettes", 200, 200, 160, 19)] and [m["bac"] for m in k["masked"]] == ["Baccalauréat Professionnel"]
    return not bad and known and n > 0, f"{len(c.parsed)} PDFs, {n} formations; known 31899 table {known}; problems {bad[:3]}"


@check("R2 selection: verified only (confirmed = nb_voe_pp), printed code or checked g_ti_cod, latest capture, concours split")
def r2(c: Ctx):
    mem, spec, res = built(c)
    got = {(cd, s): (dg, conf) for cd, s, dg, conf in mem.execute("SELECT cod_aff_form, session, digest, confirmes FROM core.rapport").fetchall()}
    audit = mem.execute("SELECT digest, decision FROM core.rapport_audit ORDER BY 1").fetchall()
    rejected = {d for d, dec in audit if dec == "écarté"}
    rec = {(cd, s): r for cd, s, r in mem.execute("SELECT cod_aff_form, session, recoupe FROM core.rapport").fetchall()}
    flags = all(bool(rec[k]) == (k not in spec["pending"]) for k in rec)
    ok = got == spec["want"] and {"B1", "E1", "L2", "L3", "L4", "L5", "L6"} <= rejected and not {"A2", "L1"} & rejected and flags
    return ok, f"kept {sorted(got)} want {sorted(spec['want'])}; rejected {sorted(rejected)}; not cross-checked flags {flags}; build {res}"


@check("R3 figures: served rows = harvested counts, rate re-derived, the student's row (Python and page twins), EDS lists cut")
def r3(c: Ctx):
    mem, spec, _ = built(c)
    bad = []
    for (cod, s), rows in spec["rows"].items():
        b = M["RP"].for_formation(mem, cod, s)
        if b is None:
            bad.append((cod, "no block")); continue
        served = [(v, x["key"], x["autres"], x["confirmes"], x["en_position"]) for v in ("bg", "bt", "bp") for x in b["doublettes"].get(v, [])]
        if served != rows:
            bad.append((cod, served, rows))
        for v in b["doublettes"].values():
            for x in v:
                want = None if not x["confirmes"] else round(100 * x["en_position"] / x["confirmes"], 1)
                if x["taux"] != want:
                    bad.append((cod, "rate", x["taux"], want))
    a = spec["a"]
    ba = M["RP"].for_formation(mem, *a)
    # a specialty list stops where the next section of the report begins (harvested texts are cleaned at build)
    stl = ((ba.get("textes") or {}).get("eds") or {}).get("liste", {}).get("Série STL")
    if stl != ["Physique-Chimie et Mathématiques"]:
        bad.append(("EDS list not cut at the next section", stl))
    if ba["masques"] != ["bp"]:
        bad.append(("masked", ba["masques"]))
    picks = {k: (M["RP"].pick(ba, k) or {}).get("source") for k in ("MATHS+PC", "HLP+SES", None)}
    if picks != {"MATHS+PC": "doublette", "HLP+SES": "autres", None: None}:
        bad.append(("pick", picks))
    js = page_pick(c.js, ba, ["MATHS+PC", "HLP+SES", None])
    if js is not None and js != [[(M["RP"].pick(ba, k) or {}).get("source"), (M["RP"].pick(ba, k) or {}).get("taux")] for k in ("MATHS+PC", "HLP+SES", None)]:
        bad.append(("page twin", js))
    return not bad, f"{len(spec['rows'])} formations; problems {bad[:3]}"


def page_pick(js: str, block: dict, keys: list):
    m = re.search(r"function pickRapport\(rp, dkey\) \{.*?\n\}", js, re.S)
    node = shutil.which("node")
    if not m:
        return "missing"
    if not node:
        return None
    prog = m.group(0) + """
const [b, keys] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(keys.map((k) => { const x = pickRapport(b, k); return x ? [x.source, x.taux] : [null, null]; })));"""
    r = subprocess.run([node, "-e", prog], input=json.dumps([block, keys]), capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 else "error: " + r.stderr[-200:]


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


def node_render(js: str, block: dict, block_nobg: dict):
    node = shutil.which("node")
    if not node:
        return None
    a = js.index("// ---- Sprint \"Doublettes\"")
    blk = js[a:js.index("// ---- lot 2 (Claude design guidelines)")]
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pc1 = ")))
    series = {s: {"label": s, "candidats": 50, "taux": 40, "fragile": False, "trend": [{"session": 2025, "candidats": 50, "taux": 40}]} for s in ("bg", "bt", "bp")}
    g = {"label": "G", "seuil": 20, "campagnes_ecartees": [], "tous": {"candidats": 100, "taux": 50, "trend": []},
         "autres": {"candidats": 0, "taux": None, "n_doublettes": 0, "trend": []},
         "doublettes": [{"key": "MATHS+PC", "label": "Maths PC", "rare": False, "candidats": 60, "taux": 60, "trend": []}]}
    d = {"series": series, "groupe": g, "status": "ok"}
    prog = helpers + """
let PROFILE = null; const store = { get: (k, dft) => (k === "profile" ? PROFILE : dft) };
const tip = () => ""; const legend = () => ""; const lineChart = () => "";
""" + reo_defs(js) + blk + """
const [d, b, b2] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
PROFILE = { serie: "bg", spe1: "MATHS", spe2: "PC", maths_expertes: true };
const out = { card: doubletteCard(d, b), card_nobg: doubletteCard(d, b2), card_none: doubletteCard(d, null), jury: juryCard(b) };
PROFILE = { serie: "bg", spe1: "HLP", spe2: "SES" }; out.card_autres = doubletteCard(d, b); out.jury_nome = juryCard(b);
process.stdout.write(JSON.stringify(out));"""
    r = subprocess.run([node, "-e", prog], input=json.dumps([d, block, block_nobg]), capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-400:]}


@check("R4 page on hostile texts: escaped, labelled, published figure replaces the estimate (only then), source and caveat")
def r4(c: Ctx):
    mem, spec, _ = built(c)
    b = M["RP"].for_formation(mem, *spec["a"])
    b2 = json.loads(json.dumps(b)); b2["doublettes"].pop("bg", None)
    o = node_render(c.js, b, b2)
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    raw = [k for k, v in o.items() if "<img" in v]
    unlabelled = {k: len(re.findall(r'<td class="num"(?![^>]*data-label)', v)) for k, v in o.items()}
    mine = "Vos deux spécialités dans cette formation : 50 %" in o["card"] and "rapport public" in o["card"]
    no_est = "estim-tag" not in o["card"].split("Détail national du groupe")[0]
    est_kept = '<span class="estim-tag">estimation</span>' in o["card_nobg"] and '<span class="estim-tag">estimation</span>' in o["card_none"]
    autres = "Vos deux spécialités dans cette formation : 20 %" in o["card_autres"] and "vos deux spécialités en font partie" in o["card_autres"]
    masked = "chiffres non publiés" in o["card"]
    source = all("voir le rapport" in o[k] and "web.archive.org" in o[k] for k in ("card", "jury"))
    own = o["card"][o["card"].find("Dans cette formation, par doublette"):o["card"].find("Par doublette de spécialités")]
    caveat = "pas des chances d'admission" in own and "détaillé par doublette" in own and "pas des chances d'admission" in o["jury"]
    me_cited = "le rapport de cette formation la cite" in o["jury"] and "Mathématiques expertes" not in o["jury_nome"].split("Options et parcours")[0]
    ok = not raw and not any(unlabelled.values()) and mine and no_est and est_kept and autres and masked and source and caveat and me_cited
    return ok, (f"raw tag in {raw}; unlabelled {unlabelled}; own figure {mine}; estimate hidden by it {no_est}, kept otherwise {est_kept}; "
                f"'Autres doublettes' row {autres}; masked route said {masked}; source {source}; caveat {caveat}; maths expertes line {me_cited}")


@check("R5 wording and data: quotes only, specialty labels = journey, vouvoiement, no probability, source registered")
def r5(c: Ctx):
    js = c.js
    blk = js[js.index("// ---- Sprint \"Rapports publics\""):js.index("// ---- lot 2 (Claude design guidelines)")] if "// ---- Sprint \"Rapports publics\"" in js else ""
    m = re.search(r"^const RP_SPE = (\{.*?\});", js, re.M)
    labels = bool(m) and json.loads(m.group(1)) == J.SPECIALTIES
    quotes = "« ${esc(q)} »" in blk and "rp-quote" in blk
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", blk)
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    from suptracker import sources as SRC
    reg = any(s["key"] == "rapports_publics_parcoursup" for s in SRC.SOURCES)
    ok = labels and quotes and not chance and not tu and reg and bool(blk)
    return ok, f"labels = journey.SPECIALTIES {labels}; options quoted {quotes}; probability wording {chance[:2]}; tutoiement {tu[:2]}; registered {reg}"


# ------------------------------------------------------------------ mutation test
PY_MUTANTS = [
    ("EDS list runs into the next section", "if not x or \"?\" in x or len(x) > 90 or re.match(r\"(?i)(crit[èe]res?|vous avez|pr[ée]ciser|non,|oui,)\", x):\n            break", "if not x:\n            break"),
    ("unverified reports kept", "ok = bool(rs) and ref is not None and ref[0] == conf", "ok = bool(rs) and ref is not None"),
    ("first capture wins", 'if k not in chosen or r["timestamp"] > chosen[k]["capture"]:', 'if k not in chosen:'),
    ("rate inverted", "return None if not conf or pos is None else round(100 * pos / conf, 1)", "return None if not pos else round(100 * conf / pos, 1)"),
    ("student's doublette ignored", 'mine = next((x for x in rows if x["key"] == dkey), None)', "mine = None"),
    ("concours rows dropped", 'targets = [used[(dig, r["code"])]] if r["code"] and (dig, r["code"]) in used else \\', 'targets = [] if r["code"] else \\'),
    ("masked routes lost", 'msk.add((v["cod_aff_form"], v["session"], b))', "pass"),
    ("an archived report kept unverified", 'ref is None and r.get("source") == "live" and how == "code_imprime"', 'ref is None and how == "code_imprime"'),
    ("a report without its printed code kept", 'r.get("source") == "live" and how == "code_imprime"', 'r.get("source") == "live"'),
    ("a published session kept unverified", "and s is not None and max_sies is not None and s > max_sies and", "and s is not None and max_sies is not None and"),
    ("incoherent counts kept", "s > max_sies and conf > 0 and pos <= conf", "s > max_sies and conf > 0"),
    ("not cross-checked shown as verified", '"source": "live" if r.get("source") == "live" else "archive", "recoupe": ok}', '"source": "live" if r.get("source") == "live" else "archive", "recoupe": True}'),
]
JS_MUTANTS = [
    ("label unescaped", "<td>${esc(x.libelle)}", "<td>${x.libelle}"),
    ("jury text unescaped", 'const rpText = (t) => esc(t || "")', 'const rpText = (t) => String(t || "")'),
    ("criterion unescaped", '<td data-label="Critère">${esc(c.critere)}</td>', '<td data-label="Critère">${c.critere}</td>'),
    ("estimate kept beside the published figure", "const est = own.hasBg || semEst ? null : estimateDoublette(d.series, g, dkey);", "const est = semEst ? null : estimateDoublette(d.series, g, dkey);"),
    ("figure without its label", '<td class="num" data-label="Taux d\'accès">${pct1(x.taux)}${x.taux !== null', '<td class="num">${pct1(x.taux)}${x.taux !== null'),
    ("caveat dropped", "Ce sont des résultats passés, pas des chances d'admission.\";\n// a report SIES", "\";\n// a report SIES"),
    ("page uses the group bucket", "const other = rows.find((x) => x.autres);", "const other = null;"),
    ("source link dropped", "voir le rapport ↗</a>", "</a>"),
    ("mark dropped from the doublette card", "(rapport public ${esc(rp.session)})${rpPending(rp)}</h3>", "(rapport public ${esc(rp.session)})</h3>"),
    ("mark always empty", 'const rpPending = (rp) => (rp && rp.recoupe === false ?', "const rpPending = (rp) => (false ?"),
]


def mutated(path: Path, old: str, new: str, name: str):
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType(name)
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[name] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("R6 mutation test: selection, rate, pick, escaping, labels, wording and source bugs are each caught")
def r6(c: Ctx):
    fns = [r1, r2, r3, r4, r5, r9]
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
        m = mutated(ROOT / "suptracker" / "rapports.py", old, new, "suptracker._mut_rp")
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M["RP"] = M["RP"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["RP"] = saved
            sys.modules.pop("suptracker._mut_rp", None)
    for name, old, new in JS_MUTANTS:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        saved, c.js = c.js, c.js.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = saved
    n = len(PY_MUTANTS) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def _r7(c: Ctx):
    bad = []
    probe = next(iter(sorted(PROBE.glob("*.pdf"))), None) if PROBE.exists() else None
    if probe is not None:
        b = probe.read_bytes()
        full = PARSE.parse(b)
        tail = b[:b.rfind(b"xref", 0, b.rfind(b"startxref"))]          # cross-reference table and trailer lost
        p, st, _ = M["H"].try_parse(b)
        if st != "ok":
            bad.append(("intact", st))
        p, st, _ = M["H"].try_parse(tail)
        if st != "ok_repare" or p is None or p["doublettes"] != full["doublettes"] or p["synthese"] != full["synthese"]:
            bad.append(("cut after the last page", st))
        p, st, _ = M["H"].try_parse(b[:int(len(b) * 0.6)])               # cut inside the pages
        if p is not None:
            bad.append(("cut inside the pages used", st))
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA core")
    mem.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, nb_voe_pp INTEGER, ran_grp1 INTEGER, ran_grp2 INTEGER, ran_grp3 INTEGER)")
    spec = craft(c, c.tmp / "h7")
    mem.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?)", c.fy + [spec["e_row"]])
    kept = sorted({dg for dg, _ in spec["want"].values()})
    if len(kept) < 2:
        return False, f"crafted harvest keeps {kept}"
    rep, inc = kept[0], kept[1]
    idx = list(csv.DictReader(open(c.tmp / "h7" / "pdf_index.csv", encoding="utf-8")))
    for r in idx:
        r["status"] = {rep: "ok_repare", inc: "incomplet"}.get(r["digest"], r["status"])
    with open(c.tmp / "h7" / "pdf_index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(idx[0]))
        w.writeheader(); w.writerows(idx)
    M["RP"].build(mem, c.tmp / "h7")
    got = {d for (d,) in mem.execute("SELECT digest FROM core.rapport").fetchall()}
    if rep not in got:
        bad.append(("ok_repare dropped", rep))
    if inc in got:
        bad.append(("incomplet kept", inc))
    return not bad, f"probe {probe.name if probe else None}; problems {bad}"


@check("R7 repaired files: rebuilt only when complete and then read like the intact file; build keeps ok_repare, drops incomplet")
def r7(c: Ctx):
    ok, detail = _r7(c)
    missed = []
    for name, path, key, old, new in [
            ("completeness ignored", ROOT / "scripts" / "rapports_harvest.py", "H",
             'return p["pages"] > 0 and p["pages_vides"] == 0 and p["fin"]', "return True"),
            ("repaired rows dropped", ROOT / "suptracker" / "rapports.py", "RP", 'USABLE = ("ok", "ok_repare")', 'USABLE = ("ok",)')]:
        m = mutated(path, old, new, f"suptracker._mut7_{key}")
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M[key] = M[key], m
        try:
            if _r7(c)[0]:
                missed.append(name)
        except Exception:  # noqa: BLE001
            pass
        finally:
            M[key] = saved
            sys.modules.pop(f"suptracker._mut7_{key}", None)
    return ok and not missed, detail + f"; 2 own mutants, missed {missed}"


class _Resp:
    def __init__(self, code, content=b"", text=""):
        self.status_code, self.content, self.text = code, content, text or content.decode("latin-1")


def _r8(c: Ctx):
    L = M["L"]
    probe = next(iter(sorted(PROBE.glob("*.pdf"))), None) if PROBE.exists() else None
    if probe is None:
        return True, "no probe PDF"
    pdf = probe.read_bytes()
    code = PARSE.parse(pdf)["codes"][0]
    fiche = ('<a id="lien-rapp-pub" href="/Candidats/public/fiches/telechargerRapportPublic?g_ea_cod=X&amp;g_ti_cod=' + code +
             '&amp;c_ja_cod=1">Télécharger</a><a href="https://evil.example/telechargerRapportPublic?x=1">x</a>'
             '<a href="javascript:alert(1)//telechargerRapportPublic?x">y</a>')
    want_link = "https://dossier.parcoursup.fr/Candidats/public/fiches/telechargerRapportPublic?g_ea_cod=X&g_ti_cod=" + code + "&c_ja_cod=1"
    bad = []
    links = L.report_links(fiche, L.FICHE.format(cod=code))
    if links != [want_link]:
        bad.append(("links", links))
    seen = []

    def fake(open_):
        def call(http, url, params=None, pause=0, tries=1):
            seen.append(url)
            if "afficherFicheFormation" in url:
                return _Resp(200, text=fiche) if open_ else _Resp(404, text="")
            return _Resp(200, pdf) if url == want_link else _Resp(404, text="")
        return call
    saved = (L.call, L.codes)
    out = {}
    try:
        L.codes = lambda db: [code, "999991", "999992"]
        for name, open_ in (("closed", False), ("open", True), ("again", True), ("gone", True)):
            d = c.tmp / "live"
            if name == "closed":
                shutil.rmtree(d, ignore_errors=True)
                (d / "h").mkdir(parents=True)
            L.call = fake(open_)
            if name == "gone":     # a formation gone for good (its fiche 404s) first in line must not read as a closed site
                L.codes = lambda db: ["999994", "999995", "999996", code, "999997"]     # three never-read fiches 404 first
                gone = fake(True)
                L.call = lambda http, url, params=None, pause=0, tries=1: (_Resp(404, text="") if any(k in url for k in ("999994", "999995", "999996"))
                                                                         else gone(http, url, params, pause, tries))
            out[name] = L.harvest(None, str(c.db), d / "h", d / "state", 600, pause=0)
            out[name + "_files"] = sorted(p.name for p in (d / "h").iterdir())
            out[name + "_idx"] = list(csv.DictReader(open(d / "h" / "pdf_index.csv", encoding="utf-8"))) if (d / "h" / "pdf_index.csv").exists() else []
    finally:
        L.call, L.codes = saved
    if not L.is_closed(_Resp(200, text="<h1>Service indisponible</h1>")) or L.is_closed(_Resp(200, text=fiche + " maintenance")):
        bad.append(("closed page reading",))
    if out["closed"]["status"] != "closed" or out["closed_files"]:
        bad.append(("closed site wrote", out["closed_files"]))
    idx = out["open_idx"]
    if len(idx) != 1 or idx[0]["source"] != "live" or idx[0]["digest"] != L.digest(pdf) or idx[0]["original"] != want_link or idx[0]["status"] != "ok":
        bad.append(("stored", [(r["source"], r["status"]) for r in idx]))
    if out["gone"]["status"] != "open":
        bad.append(("formations gone for good read as a closed site",))
    if len(out["again_idx"]) != 1:
        bad.append(("duplicated on resume", len(out["again_idx"])))
    # the build: same verification, the fiche is credited
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA core")
    mem.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, nb_voe_pp INTEGER, ran_grp1 INTEGER, ran_grp2 INTEGER, ran_grp3 INTEGER)")
    p = PARSE.parse(pdf)
    conf = sum(x["confirmes"] or 0 for x in p["synthese"] if x["code"] == code)
    mem.execute("INSERT INTO core.formation_year VALUES (?, ?, ?, 0, 0, 0)", [code, p["session"], conf])
    M["RP"].build(mem, c.tmp / "live" / "h")
    blk = M["RP"].for_formation(mem, code, p["session"])
    if not blk or blk["source"] != "live" or blk["archive"] != want_link:
        bad.append(("build", blk and (blk["source"], blk["archive"])))
    mem.execute("UPDATE core.formation_year SET nb_voe_pp = nb_voe_pp + 1")
    M["RP"].build(mem, c.tmp / "live" / "h")
    if M["RP"].for_formation(mem, code, p["session"]):
        bad.append(("unverified live report kept",))
    credit = 'sur la fiche Parcoursup de la formation' in c.js and 'rp.source === "live"' in c.js
    # the owner's priority: formations without a report of the newest report session read come first (campaign 2027: the
    # fiches link 2026 reports while SIES stops at 2025)
    order = L.codes(str(c.db))
    with_rep = {x for (x,) in c.con.execute("""SELECT cod_aff_form FROM core.rapport
        WHERE session = (SELECT max(session) FROM core.rapport)""").fetchall()}
    flags = [x in with_rep for x in order]
    if flags != sorted(flags) or len(set(order)) != len(order):
        bad.append(("priority order",))
    return not bad and credit, f"links {links == [want_link]}; closed {out['closed']['status']}; problems {bad[:3]}; page credit {credit}"


@check("R9 not yet cross-checked: kept only from the live fiche of an unpublished session (R2 crafted rows); the page marks it everywhere")
def r9(c: Ctx):
    js = c.js
    fn = "\n".join(m.group(0) for m in (re.search(r"const esc = .*", js), re.search(r"const rpPending = .*", js),
                                          re.search(r"function rapportSource\(rp\) \{.*?\n\}", js, re.S)) if m)
    o = node(fn + """
const rp = { recoupe: false, session: 2026, capture: "20261215000000", source: "live", archive: "https://dossierappel.parcoursup.fr/x" };
process.stdout.write(JSON.stringify({ pend: rpPending(rp), src: rapportSource(rp), ok: rpPending({ ...rp, recoupe: true }), ok2: rapportSource({ ...rp, recoupe: true }) }));""")
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    mark = "pas encore recoupé avec les chiffres de 2026"
    page = (mark in o["pend"] and "recoupé avec les chiffres de 2026" in o["src"] and not o["ok"] and "égalent" in o["ok2"]
            and "${rpPending(rp)}</h3>" in js and "${rpPending(rp)}</h2>" in js and "pas encore recoupé avec les chiffres de ${esc(v.rapport.session)}" in js)
    ok2, detail = r2(c)
    return page and ok2, f"page marks {page}; selection {ok2}"


@check("R8 live harvest: closed site writes nothing, fiche link read, each PDF once, same verification, the fiche credited")
def r8(c: Ctx):
    ok, detail = _r8(c)
    missed = []
    n_rep = c.con.execute("SELECT count(*) FROM core.rapport WHERE session = (SELECT max(session) FROM core.formation_year)").fetchone()[0]
    for name, path, key, old, new in [
            ("closed site not detected", ROOT / "scripts" / "rapports_live.py", "L", "if resp is not None and resp.status_code == 200 and not is_closed(resp):", "if resp is not None:"),
            ("closed when the first fiches are gone", ROOT / "scripts" / "rapports_live.py", "L", 'probes = ([r for r in state.values() if r["status"] == "ok"] or [r for r in todo if r["status"] == "todo"] or todo)[:probe_codes]', "probes = todo[:probe_codes]"),
            ("link left escaped", ROOT / "scripts" / "rapports_live.py", "L", "u = urljoin(base, html.unescape(m.group(1)))", "u = urljoin(base, m.group(1))"),
            ("any host followed", ROOT / "scripts" / "rapports_live.py", "L", 'if u.startswith("https://") and "parcoursup.fr/" in u and u not in out:', "if u not in out:"),
            *([] if not n_rep else [("no priority", ROOT / "scripts" / "rapports_live.py", "L", "return sorted(allc - done, key=_num) + sorted(allc & done, key=_num)", "return sorted(allc, key=_num)")]),
            ("same PDF stored twice", ROOT / "scripts" / "rapports_live.py", "L", "            if dg in known:\n                continue\n", ""),
            ("live credited to the archive", ROOT / "suptracker" / "rapports.py", "RP", '"archive": url if live else f"https://web.archive.org/web/{cap}/{url}"', '"archive": f"https://web.archive.org/web/{cap}/{url}"')]:
        m = mutated(path, old, new, f"suptracker._mut8_{key}")
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M[key] = M[key], m
        try:
            if _r8(c)[0]:
                missed.append(name)
        except Exception:  # noqa: BLE001
            pass
        finally:
            M[key] = saved
            sys.modules.pop(f"suptracker._mut8_{key}", None)
    return ok and not missed, detail + f"; {7 if n_rep else 6} own mutants (priority only where reports exist), missed {missed}"


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
    shutil.rmtree(c.tmp, ignore_errors=True)
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
