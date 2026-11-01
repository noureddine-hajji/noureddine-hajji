"""Red team of sprint 7, gateways: reorientation after L1 (B1 workbook) and the university's masters (MonMaster).

    python scripts/redteam_passerelles.py [--db data/suptracker.duckdb] [--real]

The checks re-read the reorientation sheet independently (fixed positions, own block grouping),
recompute the MonMaster aggregates with their own SQL over the raw table, and compare: stored =
published (masked never 0), the identities SIES and MonMaster satisfy, the cross-sheet consistency
with the "Devenir" table B1 already shows, the university names, the discipline map (MEEF and mixed
masters kept out), the link (the same university and discipline as B1, by Paysage id), the API and
its grades, the page (escaping, wording, no proposal/application ratio, no remainder computed by
difference). A mutation test seeds bugs and requires each to be caught.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import evidence as E  # noqa: E402
from suptracker import passerelles as PA  # noqa: E402
from suptracker import success as SU  # noqa: E402

CHECKS = []
APP_JS = ROOT / "suptracker" / "static" / "app.js"
NAT = PA.NATIONAL
SHEET = "Réorientations - cohorte 2023"
FIELDS = ("inscrits", "n_reorientation", "taux_reorientation", "n_hors_univ", "taux_hors_univ", None, "taux_cpge", None, "taux_sts_app",
          None, "taux_sts", None, "taux_commerce", None, "taux_ingenieur", "n_univ", "taux_univ", None, "taux_but", None, "taux_infirmier")
# truth table of the discipline map: (disci_lib, disci_master) -> B1 discipline
DISC_TRUTH = {("Droit, sciences politiques", "Droit et sc. politiques"): "droit",
              ("Administration économique et sociale", "Economie, gestion et AES"): "eco",
              ("Sciences humaines et sociales", "SHS"): "alsh",
              ("Sciences humaines et sociales", "M.E.E.F."): "meef",
              ("Sciences humaines et sociales", "MEEF"): "meef",
              ("Pluridisciplinaire droit, sciences économiques, AES", "Economie, gestion et AES"): None,
              ("Théologie", "SHS"): None,
              ("STAPS", "Sc. fondamentales et appliquées (dont STAPS)"): "staps",
              ("Sciences de la vie, de la terre et de l'univers", "Sc. fondamentales et appliquées (dont S.T.A.P.S.)"): "sciences"}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, b1_xlsx: Path, real: bool = False, raw_dir: Path | None = None, aliases=None,
                 paysage=None, b1_table=None, b1_paysage=None):
        self.db, self.xlsx, self.real, self.raw_dir = db, Path(b1_xlsx), real, raw_dir
        self.aliases, self.paysage = aliases, paysage
        src = duckdb.connect(str(db), read_only=True)
        latest = src.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.forms = src.execute("""SELECT session, cod_aff_form, g_ea_lib_vx, fil_lib_voe_acc, fili, contrat_etab
                                    FROM core.formation_year WHERE session = ?""", [latest]).fetchall()
        has = lambda s, t: src.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?", [s, t]).fetchone()[0]
        self.raw = src.execute("SELECT * FROM ref.monmaster_raw").df() if has("ref", "monmaster_raw") else None
        self.stored = {t: src.execute(f"SELECT * FROM core.{t}").df() if has("core", t) else None
                       for t in ("licence_reorientation", "monmaster")}
        self.ids = src.execute("SELECT session, cod_aff_form, id_resolu FROM ref.formation_etablissement WHERE session = ?",
                               [latest]).fetchall() if has("ref", "formation_etablissement") else []
        src.close()
        self.b1_table, self.b1_paysage = b1_table, b1_paysage
        self.b1 = None                                # B1 tables, built once (no mutant touches them)
        self.rebuild()

    def rebuild(self):
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core")
        con.execute("CREATE SCHEMA ref")
        con.execute("CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, g_ea_lib_vx VARCHAR, fil_lib_voe_acc VARCHAR, fili VARCHAR, contrat_etab VARCHAR)")
        con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?)", self.forms)
        con.execute("CREATE TABLE ref.formation_etablissement (session INTEGER, cod_aff_form VARCHAR, id_resolu VARCHAR)")
        if self.ids:
            con.executemany("INSERT INTO ref.formation_etablissement VALUES (?, ?, ?)", self.ids)
        if self.b1 is None:
            SU.attach(con, self.xlsx, self.b1_table, paysage_table=self.b1_paysage)
            self.b1 = {t: con.execute(f"SELECT * FROM core.{t}").df() for t in ("licence_success", "licence_success_link")}
        else:
            for t, df in self.b1.items():
                con.register("_b1", df)
                con.execute(f"CREATE TABLE core.{t} AS SELECT * FROM _b1")
                con.unregister("_b1")
        if self.raw is not None:
            con.register("_raw", self.raw)
            con.execute("CREATE TABLE ref.monmaster_raw AS SELECT * FROM _raw")
            con.unregister("_raw")
        self.counts = PA.build(con, self.raw_dir or Path("/nonexistent"), reo_source=self.xlsx, aliases=self.aliases)
        self.con = con

    def rows(self, table):
        cur = self.con.execute(f"SELECT * FROM core.{table}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def q(self, sql, args=()):
        return self.con.execute(sql, list(args)).fetchall()


# ---------------------------------------------------------------- independent re-reading
def reread(path: Path) -> dict:
    """{(block total row, discipline label): {field: value}} by fixed positions and own grouping."""
    import openpyxl
    rows = [list(r) for r in openpyxl.load_workbook(path, read_only=True, data_only=True)[SHEET].iter_rows(values_only=True)]
    start = next(i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].startswith("Nom"))
    out, block = {}, None
    for r in rows[start + 1:]:
        if not r or r[0] is None or len(r) < 2 or r[1] is None:
            continue
        label = " ".join(str(r[1]).split())
        if label.lower().startswith("toutes"):
            block = r[0]
        if block == "Etudiants":
            continue
        out[(block, label)] = {f: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else ("masked", v))
                               for f, v in zip(FIELDS, r[2:23]) if f}
    return out


DISC = {"toutes disciplines": "toutes", "droit, sc. politiques": "droit", "economie, aes": "eco",
        "arts, lettres, langues, shs": "alsh", "sciences-sante": "sciences", "staps": "staps"}


@check("Q1 reorientation sheet: stored = published, cell by cell, masked cells NULL (never 0), no row dropped or added")
def q1(c: Ctx):
    pub = reread(c.xlsx)
    by_key = {}
    for r in c.rows("licence_reorientation"):
        by_key[(r["etab"], r["discipline"])] = r
    # map each published block to the stored etab through its total row
    block_etab = {r["etab_row"]: r["etab"] for r in c.rows("licence_reorientation") if r["discipline"] == "toutes"}
    bad, n = [], 0
    for (block, label), vals in pub.items():
        etab = block_etab.get(block)
        r = by_key.get((etab, DISC.get(SU.fold(label))))
        if r is None:
            bad.append(("missing", block, label))
            continue
        m = json.loads(r["masked"])
        for f, v in vals.items():
            n += 1
            if isinstance(v, tuple):
                if r[f] is not None or f not in m:
                    bad.append((block, label, f, v, r[f]))
            elif r[f] is None or abs(r[f] - v) > 1e-9:
                bad.append((block, label, f, v, r[f]))
    extra = len(by_key) - len(pub)
    zero = [r["etab"] for r in c.rows("licence_reorientation") if any(r[f] == 0 for f in json.loads(r["masked"]))]
    stale = []
    if c.real and c.stored["licence_reorientation"] is not None:
        old = {(a, b, None if t != t else t) for a, b, t in c.stored["licence_reorientation"][["etab", "discipline", "taux_reorientation"]].itertuples(index=False)}
        fresh = {(r["etab"], r["discipline"], r["taux_reorientation"]) for r in c.rows("licence_reorientation")}
        stale = sorted(old ^ fresh, key=str)[:3]
    return n > 0 and not bad and not extra and not zero and not stale, f"{n} cells compared, {len(bad)} differ {bad[:3]}; extra rows {extra}; masked as 0 {zero[:2]}; warehouse vs fresh build {stale}"


@check("Q2 reorientation identities: hors + université = reoriented, details within their family, rates = counts, sums, masking, same as the 'Devenir' table")
def q2(c: Ctx):
    bad = []
    rows = c.rows("licence_reorientation")
    for r in rows:
        if r["taux_reorientation"] is None:
            if r["etab"] != NAT and (r["inscrits"] or 0) >= 100:
                bad.append(("masked above 100", r["etab"], r["discipline"]))
            continue
        if r["etab"] != NAT and r["inscrits"] < 100:
            bad.append(("published below 100", r["etab"], r["discipline"]))
        gap = r["n_hors_univ"] + r["n_univ"] - r["n_reorientation"]
        if (r["etab"] != NAT and gap != 0) or abs(gap) > 3:            # national row: multiple enrolments, 1-3
            bad.append(("hors + univ", r["etab"], r["discipline"], gap))
        hors = sum(r[k] for k in ("taux_cpge", "taux_sts_app", "taux_sts", "taux_commerce", "taux_ingenieur"))
        univ = r["taux_but"] + r["taux_infirmier"]
        if hors > r["taux_hors_univ"] + 0.35 or univ > r["taux_univ"] + 0.25:
            bad.append(("detail > family", r["etab"], r["discipline"]))
        for n_, t_ in (("n_reorientation", "taux_reorientation"), ("n_hors_univ", "taux_hors_univ"), ("n_univ", "taux_univ")):
            if abs(round(100 * r[n_] / r["inscrits"], 1) - r[t_]) > 0.051:
                bad.append(("rate", r["etab"], r["discipline"], t_))
    nat = {r["discipline"]: r for r in rows if r["etab"] == NAT}
    tot = defaultdict(float)
    for r in rows:
        if r["etab"] != NAT:
            tot[r["discipline"]] += r["inscrits"] or 0
    bad += [("entrants sum", d, tot[d], r["inscrits"]) for d, r in nat.items() if abs(tot[d] - r["inscrits"]) > 0.5]
    # the B1 "Devenir" table (already on the page): same entrants and reoriented, where both are published
    dev = {(e, d): (i, n) for e, d, i, n in c.q("SELECT etab, discipline, inscrits, n_reorientation FROM core.licence_success WHERE kind = 'passage'")}
    cross = [(r["etab"], r["discipline"]) for r in rows if (r["etab"], r["discipline"]) in dev and r["n_reorientation"] is not None
             and dev[(r["etab"], r["discipline"])][1] is not None
             and (dev[(r["etab"], r["discipline"])][0] != r["inscrits"] or dev[(r["etab"], r["discipline"])][1] != r["n_reorientation"])]
    blocks = {r["etab"] for r in rows if r["etab"] != NAT}
    known = set(c.paysage) if c.paysage else set(SU.SIES_PAYSAGE)
    unmapped = sorted(blocks - known)
    return not bad and not cross and not unmapped, f"{len(bad)} broken {bad[:3]}; differ from the Devenir table {cross[:3]}; blocks not a B1 university {unmapped[:3]}"


@check("Q3 MonMaster staging: every 2024-2025 offer kept once, totals = raw, origins = admits, funnel never grows")
def q3(c: Ctx):
    raw = c.raw
    if raw is None or "n_can_pp" not in raw.columns:
        return False, "no MonMaster raw table"
    r = raw[raw.session.isin(PA.MASTER_SESSIONS)]
    st = c.rows("monmaster")
    bad = []
    if len(st) != len(r) or len({(x["session"], x["ifc"]) for x in st}) != len(st):
        bad.append(("rows", len(st), len(r)))
    for s in PA.MASTER_SESSIONS:
        rs = r[r.session == s]
        ss = [x for x in st if x["session"] == s]
        for raw_col, col in (("n_accept_total", "n_accept"), ("n_prop_total", "n_prop"), ("n_accept_etab", "n_accept_etab")):
            if int(rs[raw_col].sum()) != sum(x[col] for x in ss):
                bad.append((s, col))
        if int((rs.n_can_pp + rs.n_can_pc).sum()) != sum(x["n_can"] for x in ss):
            bad.append((s, "n_can = pp + pc"))
    for x in st:
        if sum(x[f"n_accept_{o}"] for o in PA.ORIGINS) != x["n_accept"] or x["n_accept"] > x["n_prop"] or x["n_accept_etab"] > x["n_accept"]:
            bad.append(("identity", x["session"], x["ifc"]))
    return not bad, f"{len(st)} offers; {len(bad)} wrong {bad[:3]}"


@check("Q4 discipline map: every MonMaster discipline is mapped explicitly, MEEF and mixed masters stay out, truth table")
def q4(c: Ctx):
    labels = c.q("SELECT DISTINCT disci_lib, disci_master FROM core.monmaster")
    silent = [(dl, dm) for dl, dm in labels if not PA.is_meef(dm) and SU.fold(dl) not in PA.MASTER_DISCIPLINE]
    truth = [(k, PA.master_discipline(*k), v) for k, v in DISC_TRUTH.items() if PA.master_discipline(*k) != v]
    stored = c.q("SELECT count(*) FROM core.monmaster WHERE discipline IN ('droit','eco','alsh','sciences','staps') AND upper(replace(disci_master, '.', '')) = 'MEEF'")[0][0]
    wrong = [(dl, dm, d) for dl, dm, d in c.q("SELECT DISTINCT disci_lib, disci_master, discipline FROM core.monmaster") if PA.master_discipline(dl, dm) != d]
    return not silent and not truth and not stored and not wrong, f"unmapped labels {silent[:3]}; truth table {truth[:3]}; MEEF counted in a discipline {stored}; stored code differs {wrong[:3]}"


def ref_masters(raw, pid, disc, session):
    """Independent aggregate from the raw table (pandas)."""
    r = raw[(raw.session == session)]
    disc_col = [PA.master_discipline(a, b) for a, b in zip(r.disci_lib, r.disci_master)]
    r = r[[d == disc for d in disc_col]]
    if pid is not None:
        r = r[r.id_paysage_actuel.fillna(r.id_paysage) == pid]
    if not len(r):
        return None
    return {"n_offres": len(r), "n_accept": int(r.n_accept_total.sum()), "n_accept_etab": int(r.n_accept_etab.sum()),
            "n_can": int((r.n_can_pp + r.n_can_pc).sum()), "but3": int(r.n_accept_but3_total.sum())}


@check("Q5 licence -> masters: B1's university (by Paysage id) and discipline; aggregates re-derived from the raw MonMaster rows")
def q5(c: Ctx):
    # one licence per university x discipline pair, plus every 10th other one (the block depends on the pair only)
    links, firsts = [], set()
    for i, (cod, etab, disc) in enumerate(c.q("""SELECT cod_aff_form, etab, discipline FROM core.licence_success_link
                                                 WHERE etab IS NOT NULL AND discipline IS NOT NULL ORDER BY cod_aff_form""")):
        if (etab, disc) not in firsts or i % 10 == 0:
            firsts.add((etab, disc))
            links.append((cod, etab, disc))
    fili = {f[1]: f[4] for f in c.forms}
    pmap = c.paysage or SU.SIES_PAYSAGE
    s = PA.latest_session(c.con)
    bad, n, seen = [], 0, {}
    for cod, etab, disc in links:
        b = PA.for_licence(c.con, cod, fili.get(cod), "Public", paysage=c.paysage)
        n += 1
        if b["etab"] != etab or b["discipline"] != disc:
            bad.append((cod, "link"))
            continue
        key = (etab, disc)
        if key not in seen:
            seen[key] = ref_masters(c.raw, pmap.get(etab), disc, s)
        want, got = seen[key], b["masters"]
        if (want is None) != (got is None) or (want and any(got[k] != want[k] for k in ("n_offres", "n_accept", "n_accept_etab", "n_can"))):
            bad.append((cod, etab, disc, want, got and {k: got[k] for k in ("n_offres", "n_accept", "n_accept_etab", "n_can")}))
        if got and got["n_accept"] and abs(got["part_etab"] - 100 * got["n_accept_etab"] / got["n_accept"]) > 1e-9:
            bad.append((cod, "share"))
        if ("FR", disc) not in seen:
            seen[("FR", disc)] = ref_masters(c.raw, None, disc, s)
        fr = seen[("FR", disc)]
        if fr and b["masters_france"]["n_accept"] != fr["n_accept"]:
            bad.append((cod, "france"))
    matched = sum(1 for k, v in seen.items() if v and k[0] != "FR")
    return n > 0 and not bad and matched > 0, f"{n} licences, {len(seen)} university x discipline pairs ({matched} with masters), {len(bad)} wrong {bad[:2]}"


@check("Q6 API: reorientation row and grade by the fixed rules, out-of-scope cases, BUT 3 -> master counts re-derived")
def q6(c: Ctx):
    bad = []
    links = c.q("SELECT cod_aff_form, etab, discipline, lien FROM core.licence_success_link WHERE etab IS NOT NULL AND discipline IS NOT NULL LIMIT 300")
    for cod, etab, disc, lien in links:
        b = PA.for_licence(c.con, cod, "Licence", "Public", paysage=c.paysage)
        r = b["reorientation"]
        if r is None:
            continue
        if r["etab"] != etab or r["discipline"] != disc or b["reorientation_france"]["etab_row"] != "Inscriptions principales":
            bad.append((cod, "row"))
        g, _ = E.grade(r["taux_reorientation"], r["inscrits"], r["cohort"], lien or "nom")
        if r["maillon"]["fiabilite"] != g:
            bad.append((cod, "grade", r["maillon"]["fiabilite"], g))
    any_cod = c.forms[0][1]
    scope = [PA.for_licence(c.con, any_cod, "BTS", "Public") is None,
             PA.for_licence(c.con, links[0][0] if links else any_cod, "Licence", "Privé enseignement supérieur")["status"] == "hors_champ"]
    s = PA.latest_session(c.con)
    pmap = c.paysage or SU.SIES_PAYSAGE
    for etab in list(pmap)[:15]:
        got = PA.for_but(c.con, etab, paysage=c.paysage)
        r = c.raw[(c.raw.session == s) & (c.raw.id_paysage_actuel.fillna(c.raw.id_paysage) == pmap[etab])]
        want = int(r.n_accept_but3_total.sum()) if len(r) else None
        if (got["universite"] or {}).get("n_accept_but3") != (want if want else None) and not (want == 0 and got["universite"]):
            bad.append(("but3", etab, want, got["universite"]))
    return not bad and all(scope), f"{len(bad)} wrong {bad[:3]}; out of scope {scope}"


def fn_body(js: str, name: str) -> str:
    i = js.index(name)
    j = min(k for k in (js.find("\nfunction ", i + 1), js.find("\nconst ", i + 1)) if k > 0)
    return js[i:j]


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 7: gateways")
    blk = js[i: js.index("function offerCard", i)]
    safe = ("esc(", "suVal(", "pc1d(", "pcs(", "fmt(", "fiabBadge(", "statusCard(", "reoTable(", "mastersBox(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", blk)
           if re.search(r"\.(?:mention|etab_label|discipline_label|session|cohort|reason)\b", m) and not m.lstrip().startswith(safe)]
    words = {"function reoTable(": ("parts des inscrits en L1", "pas complet"),
             "function mastersBox(": ("des vœux", "pas des chances", "calculées"),
             "function passerellesCard(": ("pas des chances", "pas seulement de cette licence")}
    wording = all(w in fn_body(js, f) for f, ws in words.items() for w in ws)
    ratio = re.findall(r"n_prop\s*/|/\s*\(?\w*\.?n_can|n_accept\s*/\s*\w*\.?n_can", blk)        # no "chance-like" ratio
    remainder = re.findall(r"taux_(?:hors_univ|univ|reorientation)\]?\s*-\s*", blk)              # no remainder by difference
    but3 = "masters_but3" in js and "titulaires d'un BUT" in js
    wired = "${passerellesCard(d.passerelles)}" in js
    ok = not raw and wording and not ratio and not remainder and but3 and wired
    return ok, f"unescaped {raw[:3]}; wording {wording}; ratio shown {ratio[:2]}; remainder computed {remainder[:2]}; BUT line {but3}; wired {wired}"


@check("Q7 page: stored strings escaped, wording (shares of L1 entrants, incomplete detail, vœux, not chances), no ratio, no remainder")
def q7(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped mention", "<td>${esc(x.mention)}</td>", "<td>${x.mention}</td>"),
    ("unescaped university", "<strong>${esc(p.etab_label)}</strong>", "<strong>${p.etab_label}</strong>"),
    ("vœux caveat dropped", "(des vœux : une même personne postule à plusieurs masters)", ""),
    ("incomplete-detail caveat dropped", "Le détail publié n'est pas complet : les autres réorientés suivent des formations que le SIES ne détaille pas.", ""),
    ("proposal ratio shown", "<strong>${fmt(m.n_accept)} admis</strong>", "<strong>${fmt(m.n_accept)} admis</strong> (${pcs(100 * m.n_prop / m.n_can)} de propositions)"),
    ("remainder computed", '<td class="num">${suVal(r, k)}</td>', '<td class="num">${pcs(r.taux_hors_univ - r[k])}</td>'),
    ("card not wired", "${passerellesCard(d.passerelles)}", ""),
]


@check("Q8 mutation test: wrong national row, masked as 0, no block grouping, MEEF in a discipline, guessed mixed discipline, masters by name, UI bugs are caught")
def q8(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"num": SU._num, "parse": PA.parse_reorientation, "md": PA.master_discipline, "disc": dict(PA.MASTER_DISCIPLINE),
             "masters": PA.masters_of}

    def num_zero(v):
        x, why = saved["num"](v)
        return (0.0, None) if why == "ns" else (x, why)

    def students_row(path, aliases=None):
        rows = saved["parse"](path, aliases)
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[SHEET]
        et = {" ".join(str(r[1]).split()): r for r in ws.iter_rows(values_only=True) if r and r[0] == "Etudiants"}
        for r in rows:
            if r["etab"] == NAT:
                e = et.get(next(k for k in et if DISC.get(SU.fold(k)) == r["discipline"]), None)
                if e and isinstance(e[2], (int, float)):
                    r["inscrits"] = float(e[2])
        return rows

    def no_blocks(path, aliases=None):
        rows = saved["parse"](path, aliases)
        for r in rows:
            if r["etab"] != NAT:
                r["etab"] = r["etab_row"]
        return rows

    def meef_in(dl, dm):
        return PA.MASTER_DISCIPLINE.get(SU.fold(dl))

    def by_name(con, pid, disc, session):                      # masters matched on a name fragment, not the id
        return saved["masters"](con, None, disc, session) if pid else None

    mutants = [
        ("'Etudiants' as the national reorientation row", lambda: setattr(PA, "parse_reorientation", students_row), (q2,)),
        ("masked cell stored as 0", lambda: setattr(SU, "_num", num_zero), (q1, q2)),
        ("discipline rows not grouped by block", lambda: setattr(PA, "parse_reorientation", no_blocks), (q1, q2)),
        ("MEEF counted in its listed discipline", lambda: setattr(PA, "master_discipline", meef_in), (q4,)),
        ("mixed droit-éco master guessed as droit", lambda: PA.MASTER_DISCIPLINE.update({"pluridisciplinaire droit, sciences economiques, aes": "droit"}), (q4,)),
        ("masters not restricted to the university", lambda: setattr(PA, "masters_of", by_name), (q5,)),
    ]
    for name, apply, checks in mutants:
        try:
            apply()
            c.rebuild()
            caught = any(not ch(c)[0] for ch in checks)
        except Exception:  # noqa: BLE001 - a crash is a catch
            caught = True
        finally:
            SU._num, PA.parse_reorientation, PA.master_discipline, PA.masters_of = saved["num"], saved["parse"], saved["md"], saved["masters"]
            PA.MASTER_DISCIPLINE.clear(), PA.MASTER_DISCIPLINE.update(saved["disc"])
        if not caught:
            missed.append(name)
    c.rebuild()
    n = len(UI_MUTANTS) + len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, b1_xlsx: Path | None = None, real: bool = False, **kw) -> list[dict]:
    c = Ctx(db, b1_xlsx or SU.source_path(ROOT / "data" / "sources"), real=real, **kw)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, real=a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
