"""Red team of sprint 6, "success beyond licence": BUT per university, master per university x discipline.

    python scripts/redteam_poursuite.py [--db data/suptracker.duckdb] [--real]

The checks re-read the five SIES workbooks independently (openpyxl, their own block grouping and
column positions), rebuild the sprint-6 tables in memory from the warehouse's formations, and
compare: stored = published (masked never 0), the identities SIES must satisfy, the masking rule,
the university names (no collision), the BUT links (truth table of the hard sites, cross-check of
the id against the name rules), the specialty map, the licence -> master link (the same as B1),
the API blocks and their grades, the national margins, the UI (escaping, wording, no multiplied
rates, the profile never sent). A mutation test seeds bugs and requires each to be caught.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import evidence as E  # noqa: E402
from suptracker import journey as J  # noqa: E402
from suptracker import poursuite as P  # noqa: E402
from suptracker import success as SU  # noqa: E402

CHECKS = []
APP_JS = ROOT / "suptracker" / "static" / "app.js"
NAT = P.NATIONAL

# Real BUT sites that are easy to get wrong -> SIES university (None: must stay unlinked)
BUT_TRUTH = {
    "I.U.T de Toulouse": "UNIVERSITE TOULOUSE 3 (PAUL SABATIER)",
    "I.U.T de Toulouse - Antenne de Castres": "UNIVERSITE TOULOUSE 3 (PAUL SABATIER)",
    "I.U.T de Toulouse - Antenne d'Auch": "UNIVERSITE TOULOUSE 3 (PAUL SABATIER)",
    "I.U.T de Nîmes": "UNIVERSITE MONTPELLIER",   # an IUT of Montpellier carrying the id of Nîmes (owner-confirmed)
    "IUT de Bordeaux - Antenne de Polynésie Française": None,
    "Institut Supérieur Saint-Denis": None,       # private
}
SPECIALTY_TRUTH = {
    "Science des données": "statistique et informatique decisionnelle",
    "Génie biologique parcours biologie médicale et biotechnologie": "genie biologique",
    "Carrières sociales Parcours éducation spécialisée": "carrieres sociales",
    "Information communication Parcours journalisme": "information communication",
    "Génie chimique génie des procédés": "genie chimique genie des procedes",
    "Métiers de la Transition et de l'Efficacité Énergétiques": "metiers de la transition et de l efficacite energetique",
    "Science et génie des matériaux": "sciences et genie des materiaux",
    "Génie civil - Construction durable": "genie civil construction durable",
    "Management de la Logistique et des Transports": "management de la logistique et des transports",
}
# SIES rows whose seven M1 outcome shares do not add up to 100 (as published): shown as is
KNOWN_PARTITION_GAPS = {("UNIVERSITE GRENOBLE-ALPES", "alsh"), ("UNIVERSITE GRENOBLE-ALPES", "toutes")}
MASK_BELOW = {"but": 100, "master": 50}       # SIES: nothing published below these entrants (measured)


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def fold(s):
    return SU.fold(s)


class Ctx:
    def __init__(self, db: Path, sources: dict, real: bool = False, aliases=None, paysage=None, rules=None, b1=None,
                 but_truth=None, spe_truth=None, overrides=None):
        self.overrides = overrides
        self.db, self.real, self.sources = db, real, {k: Path(v) for k, v in sources.items()}
        self.but_truth = BUT_TRUTH if but_truth is None else but_truth
        self.spe_truth = SPECIALTY_TRUTH if spe_truth is None else spe_truth
        self.aliases, self.paysage, self.rules = aliases, paysage, rules
        src = duckdb.connect(str(db), read_only=True)
        latest = src.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.forms = src.execute("""SELECT session, cod_aff_form, g_ea_lib_vx, fil_lib_voe_acc, fili, contrat_etab
                                    FROM core.formation_year WHERE session = ?""", [latest]).fetchall()
        has = lambda s, t: src.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?", [s, t]).fetchone()[0]
        self.ids = src.execute("SELECT session, cod_aff_form, id_resolu FROM ref.formation_etablissement WHERE session = ?",
                               [latest]).fetchall() if has("ref", "formation_etablissement") else []
        self.b1_links = src.execute("SELECT * FROM core.licence_success_link").fetchall() if has("core", "licence_success_link") else []
        self.stored = {t: src.execute(f"SELECT * FROM core.{t}").df() if has("core", t) else None
                       for t in ("but_success", "master_success", "poursuite_national", "but_success_link")}
        src.close()
        self.b1 = b1
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
        if self.b1:                                   # synthetic: B1 links from its own workbook
            SU.attach(con, *self.b1)
        else:
            con.execute("""CREATE TABLE core.licence_success_link (session INTEGER, cod_aff_form VARCHAR, etab VARCHAR,
                discipline VARCHAR, programme VARCHAR, matches VARCHAR, lien VARCHAR, id_paysage VARCHAR)""")
            if self.b1_links:
                con.executemany("INSERT INTO core.licence_success_link VALUES (?, ?, ?, ?, ?, ?, ?, ?)", self.b1_links)
        self.counts = P.build(con, self.sources, paysage_table=self.paysage, name_rules=self.rules, aliases=self.aliases,
                              overrides=self.overrides)
        self.con = con

    def q(self, sql, args=()):
        return self.con.execute(sql, list(args)).fetchall()

    def rows(self, table):
        cur = self.con.execute(f"SELECT * FROM core.{table}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- independent re-reading
def _val(v):
    if isinstance(v, bool):
        return ("masked", "type")
    if isinstance(v, (int, float)):
        return float(v)
    return ("masked", str(v).strip() if v is not None else "")


def _sheet(path, name):
    import openpyxl
    return [list(r) for r in openpyxl.load_workbook(path, read_only=True, data_only=True)[name].iter_rows(values_only=True)]


def reread_but(path):
    """{(kind, raw name): {field: value}} by fixed positions (the real layout), independent of the parser."""
    out = {}
    for kind, sheet, fields in (("reussite3", "Réussite BUT établissements", ("inscrits", "n_reussite", "taux", "taux_simule", "va")),
                                ("poursuite", "Poursuite diplômés 3ans", ("n_diplomes", None, "taux_poursuite", "taux_master", "taux_commerce", "taux_ingenieur"))):
        rows = _sheet(path, sheet)
        start = next(i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].startswith("Nom"))
        for r in rows[start + 1:]:
            if not r or r[0] is None or len(r) < 2 or r[1] is None or r[0] == "Etudiants":
                continue
            out[(kind, r[0])] = {f: _val(r[i + 1]) for i, f in enumerate(fields) if f}
    return out


def reread_master(path):
    """{(kind, block total name, discipline label): {field: value}}: own block grouping."""
    out = {}
    for kind, sheet in (("reussite23", "Tableau 1"), ("passage_m2", "Tableau 3")):
        rows = _sheet(path, sheet)
        start = next(i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].startswith("Discipline"))
        fields = ("inscrits", "n_reussite", "taux", "taux_simule", "va") if kind == "reussite23" else (
            "inscrits", "n_passage", "taux", "taux_simule", "va", None, "taux_redoublement", None, "taux_reo_univ", None,
            "taux_reo_ingenieur", None, "taux_reo_management", None, "taux_reo_autres", None, "taux_sortie")
        block = None
        for r in rows[start + 1:]:
            if not r or r[0] is None or len(r) < 3 or r[1] is None or r[2] is None:
                continue
            disc = " ".join(str(r[0]).split())
            if disc.lower().startswith("toutes"):
                block = r[1]
            if block == "Etudiants":
                continue
            out[(kind, block, disc)] = {f: _val(r[i + 2]) for i, f in enumerate(fields) if f}
    return out


def _same(pub, stored, masked):
    if isinstance(pub, tuple):                    # masked in the workbook
        return stored is None and masked is not None
    return stored is not None and abs(stored - pub) < 1e-9


@check("P1 stored = published: every workbook cell re-read independently, masked cells NULL (never 0), no row dropped")
def p1(c: Ctx):
    bad, n = [], 0
    pub = reread_but(c.sources["but_etab"])
    got = {(r["kind"], r["etab_row"]): r for r in c.rows("but_success")}
    for key, vals in pub.items():
        r = got.get(key)
        if r is None:
            bad.append(("missing", key))
            continue
        m = json.loads(r["masked"])
        for f, v in vals.items():
            n += 1
            if not _same(v, r[f], m.get(f)):
                bad.append((key, f, v, r[f]))
    bad += [("extra", k) for k in got if k not in pub]
    pubm = reread_master(c.sources["master_etab"])
    gotm = {(r["kind"], r["block_row"], r["discipline"]): r for r in c.rows("master_success")}
    for (kind, block, label), vals in pubm.items():
        code = DISC_LABELS.get(fold(label))
        r = gotm.get((kind, block, code))
        if r is None:
            bad.append(("missing", kind, block, label))
            continue
        m = json.loads(r["masked"])
        for f, v in vals.items():
            n += 1
            if not _same(v, r[f], m.get(f)):
                bad.append((kind, block, label, f, v, r[f]))
    if len(gotm) != len(pubm):
        bad.append(("row count", len(gotm), len(pubm)))
    zero_masks = [r for t in ("but_success", "master_success") for r in c.rows(t)
                  if any(r[f] == 0 for f in json.loads(r["masked"]))]
    if c.real:                                    # the committed warehouse = a fresh build from the committed workbooks
        for t, cols in (("but_success", ("kind", "etab", "taux")), ("master_success", ("kind", "etab", "discipline", "taux")),
                        ("but_success_link", ("cod_aff_form", "etab", "specialite"))):
            df = c.stored[t]
            fresh = {tuple(r[k] for k in cols) for r in c.rows(t)}
            old = set() if df is None else {tuple(None if v != v else v for v in row) for row in df[list(cols)].itertuples(index=False)}
            if fresh != old:
                bad.append(("warehouse differs from a fresh build", t, len(fresh ^ old)))
    return n > 0 and not bad and not zero_masks, f"{n} cells compared, {len(bad)} differ {bad[:3]}; masked stored as 0: {len(zero_masks)}"


DISC_LABELS = {"toutes disciplines": "toutes", "droit, sc. politiques": "droit", "economie, aes": "eco",
               "arts, lettres, langues, shs": "alsh", "sciences-sante": "sciences", "staps": "staps"}


@check("P2 university names: every block maps to one B1 university (or a known grouping), no two blocks of a table collide")
def p2(c: Ctx):
    known = set(c.paysage.values()) | set((c.rules or {}).values()) if c.paysage else set(SU.SIES_PAYSAGE)
    issues, collisions = [], []
    for table, kinds in (("but_success", P.BUT_SHEETS), ("master_success", P.MASTER_SHEETS)):
        for k in kinds:
            rows = [r for r in c.rows(table) if r["kind"] == k and r["etab"] != NAT]
            blocks = {(r.get("block_row") or r["etab_row"]): r["etab"] for r in rows}
            for raw, etab in blocks.items():
                if etab not in known and raw not in P.UNLINKED:
                    issues.append((table, k, raw, etab))
            dup = [e for e, n in Counter(blocks.values()).items() if n > 1]
            collisions += [(table, k, e, sorted(b for b, x in blocks.items() if x == e)) for e in dup]
    targets = [v for v in (c.aliases or P.NAME_ALIASES).values() if v not in known]
    return not issues and not collisions and not targets, f"unmapped {issues[:4]}; collisions {collisions[:3]}; alias targets unknown {targets[:3]}"


@check("P3 identities: universities add up to 'Inscriptions principales', disciplines to their block, rates = counts, VA = observed - simulated, outcomes partition the M1 entrants")
def p3(c: Ctx):
    bad = []
    for table, kinds, key in (("but_success", ("reussite3",), None), ("master_success", P.MASTER_SHEETS, "discipline")):
        rows = c.rows(table)
        for k in kinds:
            groups = defaultdict(lambda: [0.0, 0.0, None, None])
            for r in rows:
                if r["kind"] != k:
                    continue
                g = groups[r[key] if key else "all"]
                if r["etab"] == NAT:
                    g[2], g[3] = r["inscrits"], (r.get("n_reussite") or r.get("n_passage"))
                else:
                    g[0] += r["inscrits"] or 0
                    g[1] += (r.get("n_reussite") or r.get("n_passage") or 0)
            for d, (e, num, ne, nn) in groups.items():
                if ne is None or abs(e - ne) > 0.5 or (nn is not None and num > nn + 0.5):
                    bad.append((table, k, d, e, ne, num, nn))
        if key:
            blocks = defaultdict(lambda: [0.0, None])
            for r in rows:
                if r["etab"] == NAT:
                    continue
                b = blocks[(r["kind"], r["block_row"])]
                if r["discipline"] == "toutes":
                    b[1] = r["inscrits"]
                else:
                    b[0] += r["inscrits"] or 0
            bad += [("block", k, s, t) for k, (s, t) in blocks.items() if t is None or abs(s - t) > 0.5]
    for r in c.rows("but_success") + c.rows("master_success"):
        num = r.get("n_reussite") if r["kind"] in ("reussite3", "reussite23") else r.get("n_passage")
        if r["taux"] is not None and r["inscrits"] and num is not None:
            if abs(100 * num / r["inscrits"] - r["taux"]) > (0.051 if r["etab"] == NAT else 0.101):
                bad.append(("rate", r["kind"], r["etab"], r.get("discipline"), r["taux"], num, r["inscrits"]))
        if r["taux"] is not None and r["taux_simule"] is not None and r["va"] is not None and abs(r["taux"] - r["taux_simule"] - r["va"]) > 0.111:
            bad.append(("va", r["kind"], r["etab"], r.get("discipline")))
        if r["kind"] == "passage_m2" and all(r[f] is not None for f in P.DEVENIR_M2):
            gap = abs(sum(r[f] for f in P.DEVENIR_M2) - 100)
            if gap > (1.05 if (r["etab"], r["discipline"]) in KNOWN_PARTITION_GAPS else 0.35):
                bad.append(("partition", r["etab"], r["discipline"], round(gap, 2)))
    b = {(r["kind"], r["etab"]): r for r in c.rows("but_success")}
    for (k, e), r in b.items():
        if k != "poursuite":
            continue
        s = b.get(("reussite3", e))
        if s and s["n_reussite"] is not None and r["n_diplomes"] != s["n_reussite"]:
            bad.append(("graduates != BUT in 3 years", e, r["n_diplomes"], s["n_reussite"]))
        parts = [r[f] for f in ("taux_master", "taux_commerce", "taux_ingenieur")]
        if r["taux_poursuite"] is not None and None not in parts and sum(parts) > r["taux_poursuite"] + 0.01:
            bad.append(("dont > poursuite", e))
    nat = b.get(("reussite3", NAT))
    for code_tab in ("profil", "specialite"):
        ens = c.q("SELECT taux FROM core.poursuite_national WHERE source_kind = 'but_nat' AND tab = ? AND code = 'ensemble'", [code_tab])
        if not nat or not ens or abs(ens[0][0] - nat["taux"]) > 0.051:
            bad.append(("national BUT tables disagree", code_tab, ens, nat and nat["taux"]))
    return not bad, f"{len(bad)} identities broken {bad[:4]}"


@check("P4 masking: nothing published below the SIES threshold (BUT 100, master 50), everything published above it")
def p4(c: Ctx):
    bad = []
    for table, thr in (("but_success", MASK_BELOW["but"]), ("master_success", MASK_BELOW["master"])):
        for r in c.rows(table):
            if r["kind"] == "poursuite":
                n, v = r["n_diplomes"], r["taux_poursuite"]
            else:
                n, v = r["inscrits"], r["taux"]
            if n is None or r["etab"] == NAT:
                continue
            if (n < thr) != (v is None):
                bad.append((table, r["kind"], r["etab"], r.get("discipline"), n, v))
    return not bad, f"{len(bad)} rows break the masking rule {bad[:4]}"


@check("P5 BUT links: Paysage id first, explicit site rules, truth table of the hard sites, every programme mapped to its specialty")
def p5(c: Ctx):
    by_id = c.paysage or SU.PAYSAGE_SIES
    ids = {cod: pid for _, cod, pid in c.ids}
    names = {f[1]: f for f in c.forms}
    known = {r["etab"] for r in c.rows("but_success")}
    bad = []
    links = c.rows("but_success_link")
    for l in links:
        f = names[l["cod_aff_form"]]
        pid = ids.get(l["cod_aff_form"])
        site = [u for rx, u in (P.BUT_SITE_OVERRIDES if c.overrides is None else c.overrides).items() if re.search(rx, fold(f[2]))]
        forced = len(site) == 1 and by_id.get(pid) not in known
        if f[5] != "Public":
            want = None
        elif forced:
            want = site[0]
        elif pid is not None:
            want = by_id.get(pid)
        else:
            hits = [u for rx, u in (c.rules or P.BUT_NAME_RULES).items() if re.search(rx, fold(f[2]))]
            want = hits[0] if len(hits) == 1 else None
        want = want if want in known else None
        if l["etab"] != want or (want and l["lien"] != ("identifiant" if pid and not forced else "nom")):
            bad.append((l["cod_aff_form"], f[2], l["etab"], want))
    truth = []
    for name, want in c.but_truth.items():
        got = {l["etab"] for l in links if names[l["cod_aff_form"]][2] == name}
        if got and got != {want}:
            truth.append((name, got, want))
        if not got:
            truth.append((name, "absent"))
    if c.real:
        # cross-check: where the B1 name rules recognise the site, they agree with the id
        dis = [(names[l["cod_aff_form"]][2], l["etab"]) for l in links if l["lien"] == "identifiant"
               and (u := SU.university_of(names[l["cod_aff_form"]][2])[0]) is not None and u != l["etab"]]
        truth += dis
        public = [l for l in links if names[l["cod_aff_form"]][5] == "Public"]
        if sum(1 for l in public if l["etab"]) < 0.98 * len(public):
            truth.append(("coverage", sum(1 for l in public if l["etab"]), len(public)))
    # an override may only replace an id that names a university with no BUT row
    ov = P.BUT_SITE_OVERRIDES if c.overrides is None else c.overrides
    truth += [("override over a usable id", names[l["cod_aff_form"]][2]) for l in links
              if any(re.search(rx, fold(names[l["cod_aff_form"]][2])) for rx in ov)
              and by_id.get(ids.get(l["cod_aff_form"])) in known]
    spe_missing = [l["programme"] for l in links if l["specialite"] is None]
    spe_known = {r[0] for r in c.q("SELECT code FROM core.poursuite_national WHERE source_kind = 'but_nat' AND dim = 'specialite'")}
    spe_bad = [(p, P.specialty_of(p, spe_known), w) for p, w in c.spe_truth.items() if P.specialty_of(p, spe_known) != w]
    ok = not bad and not truth and not spe_missing and not spe_bad and len(links) > 0
    return ok, f"{len(links)} BUT formations; wrong link {bad[:3]}; truth table {truth[:3]}; programmes without specialty {sorted(set(spe_missing))[:3]}; specialty truth {spe_bad[:3]}"


@check("P6 licence -> master: the same university and discipline as B1, the national reference of that discipline")
def p6(c: Ctx):
    links = c.q("SELECT cod_aff_form, etab, discipline FROM core.licence_success_link WHERE etab IS NOT NULL")
    contrat = {f[1]: f[5] for f in c.forms}
    fili = {f[1]: f[4] for f in c.forms}
    bad, n = [], 0
    for cod, etab, disc in links:
        b = P.master_for_formation(c.con, cod, fili.get(cod), contrat.get(cod))
        if b is None:
            bad.append((cod, "no block"))
            continue
        n += 1
        if b["status"] == "ok":
            if b["etab"] != etab or b["discipline"] != disc or any(u["etab"] != etab or u["discipline"] != disc for u in b["kinds"].values()):
                bad.append((cod, b["etab"], etab, b["discipline"], disc))
            if any(v["etab"] != NAT or v["discipline"] != disc or v["etab_row"] != "Inscriptions principales" for v in b["national"].values()):
                bad.append((cod, "national row"))
    return n > 0 and not bad, f"{n} licences checked, {len(bad)} wrong {bad[:3]}"


@check("P7 API blocks: values = warehouse, national = 'Inscriptions principales', grades by the fixed rules, out-of-scope cases")
def p7(c: Ctx):
    bad, n = [], 0
    for l in c.rows("but_success_link")[:400]:
        b = P.but_for_formation(c.con, l["cod_aff_form"], "BUT", "Public")
        n += 1
        if l["etab"] is None:
            bad += [] if b["status"] == "non_rattachee" else [(l["cod_aff_form"], b["status"])]
            continue
        r = b["kinds"].get("reussite3")
        stored = c.q("SELECT taux, inscrits, cohort FROM core.but_success WHERE kind = 'reussite3' AND etab = ?", [l["etab"]])[0]
        if r is None or r["taux"] != stored[0]:
            bad.append((l["cod_aff_form"], "value"))
            continue
        nat = b["national"]["reussite3"]
        if nat["etab_row"] != "Inscriptions principales":
            bad.append((l["cod_aff_form"], "national", nat["etab_row"]))
        g, _ = E.grade(stored[0], stored[1], int(stored[2]), l["lien"])
        if r["maillon"]["fiabilite"] != g or r["maillon"]["granularite"] != "universite":
            bad.append((l["cod_aff_form"], "grade", r["maillon"]["fiabilite"], g))
        if (b["specialite"] or {}).get("code") != l["specialite"]:
            bad.append((l["cod_aff_form"], "specialty"))
    any_cod = c.forms[0][1]
    scope = [P.but_for_formation(c.con, any_cod, "Licence", "Public") is None,
             P.master_for_formation(c.con, any_cod, "BUT", "Public") is None,
             P.but_for_formation(c.con, any_cod, "BUT", "Privé enseignement supérieur")["status"] == "hors_champ"]
    masked = [b for b in c.rows("but_success") if b["taux"] is None and b["kind"] == "reussite3" and b["etab"] != NAT]
    for m in masked[:3]:
        cod = next((l["cod_aff_form"] for l in c.rows("but_success_link") if l["etab"] == m["etab"]), None)
        if cod:
            r = P.but_for_formation(c.con, cod, "BUT", "Public")["kinds"]["reussite3"]
            if r["maillon"]["fiabilite"] is not None:
                bad.append((cod, "masked value graded"))
    return n > 0 and not bad and all(scope), f"{n} BUT blocks, {len(bad)} wrong {bad[:3]}; out-of-scope handling {scope}"


@check("P8 national margins: doublettes map to the journey's specialty codes, mentions to the profile's, the 2017 chain is ordered")
def p8(c: Ctx):
    rows = c.rows("poursuite_national")
    spe = set(J.SPECIALTIES)
    bad = []
    for r in rows:
        if r["source_kind"] == "but_nat" and r["code"].startswith("bg:"):
            a, b = r["code"][3:].split("+")
            if a not in spe or b not in spe or r["code"][3:] != J.doublette_key(a, b):
                bad.append(r["code"])
        if r["dim"] == "mention" and r["code"] not in ("tb", "b", "ab", "passable1", "passable2", "inconnue"):
            bad.append(r["code"])
        # 5-6 years <= 5-7 years. NOT <= "entered master after 3-4 years": some enter later (real: L1 SVT)
        if r["tab"] == "chaine_l1" and None not in (r["master56"], r["master567"]) and r["master56"] > r["master567"] + 1e-9:
            bad.append(("chain order", r["code"]))
    have = {(r["tab"], r["dim"], r["code"]) for r in rows}
    need = {("profil", "serie", "bg"), ("profil", "serie", "bt"), ("profil", "serie", "bp"), ("profil", "mention", "ab"),
            ("profil", "serie", "bg:MATHS+SES"), ("chaine_l1", "bac", "bg"), ("chaine_l1", "mention", "ab"), ("chaine_l1", "ensemble", "ensemble"),
            ("poursuite_lg", "discipline", "droit"), ("poursuite_lg", "discipline", "toutes")}
    nspe = sum(1 for r in rows if r["dim"] == "specialite")
    ok = not bad and need <= have and (nspe == 24 if c.real else nspe > 0)
    return ok, f"bad codes {bad[:4]}; missing {sorted(need - have)}; specialties {nspe}"


def fn_body(js: str, name: str) -> str:
    i = js.index(name)
    j = min(k for k in (js.find("\nfunction ", i + 1), js.find("\nconst ", i + 1)) if k > 0)
    return js[i:j]


STORED = r"(?:etab_label|label|reason|discipline_label|cohort|programme|code)"


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 6: success beyond licence")
    blk = js[i: js.index("function offerCard", i)]
    # every interpolation that reads a stored string must go through esc() (or a numeric formatter)
    safe = ("esc(", "suVal(", "pc1d(", "fmt(", "fiabBadge(", "m2Bar(", "expCell(", "statusCard(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", blk)
           if re.search(r"\." + STORED + r"\b", m) and not m.lstrip().startswith(safe)]
    cards = {"function butCard(": ("pas des chances", "ne croise pas", "toutes spécialités"),
             "function masterCard(": ("pas des chances", "ne croise pas", "d'où qu'ils viennent", "pas une multiplication",
                            "ce ne sont pas les diplômés de cette licence"),
             "const statusCard =": ("pas des chances",)}
    words = all(w in fn_body(js, f) for f, ws in cards.items() for w in ws)
    # rates are never multiplied with each other or chained into one figure
    product = re.findall(r"(taux|master567|licence34|passage2|passage3)[\w.\]\"' ]*\*\s*[\w.(]*(taux|master567|licence34|passage)", blk)
    local = "store.get(\"profile\"" in blk and not re.search(r"\b(api|fetch)\(", blk)
    trusted = '["bg", "bt", "bp"].includes(p.serie)' in blk and "/^[A-Z]{2,7}$/" in blk
    wired = "${masterCard(d.master)}" in js and "${butCard(d.but)}" in js
    ok = not raw and words and not product and local and trusted and wired
    return ok, f"unescaped {raw[:3]}; wording {words}; multiplied rates {product[:2]}; profile stays local {local}; profile validated {trusted}; wired {wired}"


@check("P9 page: stored strings escaped, wording (not chances, margins not crossed, every M1 entrant), no multiplied rates, profile local and validated")
def p9(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped university", "<strong>${esc(b.etab_label)}</strong>", "<strong>${b.etab_label}</strong>"),
    ("unescaped specialty label", "<strong>${esc(b.specialite.label)}</strong>", "<strong>${b.specialite.label}</strong>"),
    ("unescaped reason", '${esc(x.reason || "non publié")}', '${x.reason || "non publié"}'),
    ("'not chances' dropped", "Résultats de cohortes passées, pas des chances de réussite ; l'écart au taux attendu ne classe pas les universités.</p></div>`;\n}\nconst M2_DEVENIR",
     "Résultats de cohortes passées ; l'écart au taux attendu ne classe pas les universités.</p></div>`;\n}\nconst M2_DEVENIR"),
    ("master population caveat dropped", "d'où qu'ils viennent : ce ne sont pas les diplômés de cette licence.", "."),
    ("chain multiplied", '<strong>${suVal(r, "master567")}</strong>', '<strong>${pc1d(r.licence34 * r.passage_master / 100)}</strong>'),
    ("profile sent to the server", "const p = store.get(\"profile\", null) || {};", "const p = store.get(\"profile\", null) || {}; api(\"/api/x?\" + JSON.stringify(p));"),
    ("stored series trusted", '["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg"', 'p.serie || "bg"'),
    ("BUT card not wired", "${butCard(d.but)}", ""),
]


@check("P10 mutation test: wrong national row, masked as 0, alias collision, no block grouping, guessed IUT, wrong specialty, master off B1's discipline, UI bugs are caught")
def p10(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"num": P._num, "aliases": dict(P.NAME_ALIASES), "rules": dict(P.BUT_NAME_RULES), "spe": dict(P.SPECIALTY_ALIASES),
             "site": dict(P.BUT_SITE_OVERRIDES), "c_overrides": c.overrides,
             "pm": P.parse_master_etab, "pb": P.parse_but_etab, "mf": P.master_for_formation, "c_aliases": c.aliases,
             "c_rules": c.rules, "c_paysage": c.paysage}

    def num_zero(v):
        x, why = saved["num"](v)
        return (0.0, None) if why == "ns" else (x, why)

    def students_reference(path, aliases=None):          # "Etudiants" taken as the national row
        rows = saved["pb"](path, aliases)
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Réussite BUT établissements"]
        et = next(r for r in ws.iter_rows(values_only=True) if r and r[0] == "Etudiants")
        for r in rows:
            if r["kind"] == "reussite3" and r["etab"] == NAT:
                r["inscrits"], r["n_reussite"], r["taux"] = float(et[1]), float(et[2]), float(et[3])
        return rows

    def no_blocks(path, aliases=None):                    # the row's own name, not its block's
        rows = saved["pm"](path, aliases)
        for r in rows:
            if r["etab"] != NAT:
                r["etab"] = P.canonical(r["etab_row"], aliases)
                r["block_row"] = r["etab_row"]
        return rows

    def other_discipline(con, cod, fili, contrat):
        b = saved["mf"](con, cod, fili, contrat)
        if b and b.get("status") == "ok" and b["discipline"] != "toutes":
            u = con.execute("SELECT * FROM core.master_success WHERE kind = 'passage_m2' AND etab = ? AND discipline = 'toutes'", [b["etab"]]).fetchone()
            if u is not None:
                cols = [d[0] for d in con.description]
                b["kinds"]["passage_m2"] = {**dict(zip(cols, u)), "masked": {}}
        return b

    first_alias = next(k for k, v in (c.aliases or P.NAME_ALIASES).items())
    other_target = sorted({v for v in (c.aliases or P.NAME_ALIASES).values() if v != (c.aliases or P.NAME_ALIASES)[first_alias]})[0]
    collide = {**(c.aliases or P.NAME_ALIASES), first_alias: other_target}

    mutants = [
        ("'Etudiants' as the national reference", lambda: setattr(P, "parse_but_etab", students_reference), (p3, p7)),
        ("masked cell stored as 0", lambda: setattr(P, "_num", num_zero), (p1, p4)),
        ("alias collision", lambda: setattr(c, "aliases", collide) if c.aliases else P.NAME_ALIASES.update({first_alias: other_target}), (p1, p2, p3)),
        ("discipline rows not grouped by block", lambda: setattr(P, "parse_master_etab", no_blocks), (p1, p2, p3)),
        ("site guessed by a loose name rule", lambda: (setattr(c, "rules", {r"exemple": next(iter(c.paysage.values()))}) if c.rules
                                                      else P.BUT_NAME_RULES.update({r"i\.?u\.?t": "UNIVERSITE MONTPELLIER"})), (p5,)),
        ("site override dropped", lambda: (setattr(c, "overrides", {}), P.BUT_SITE_OVERRIDES.clear()), (p5,)),
        ("specialty renamed wrongly", lambda: P.SPECIALTY_ALIASES.update({"science des donnees": "informatique",
                                                                           "genie mecanique et productique": "gestion des entreprises et des administrations"}), (p5,)),
        ("master block off B1's discipline", lambda: setattr(P, "master_for_formation", other_discipline), (p6,)),
    ]
    for name, apply, checks in mutants:
        try:
            apply()
            c.rebuild()
            caught = any(not ch(c)[0] for ch in checks)
        except Exception:  # noqa: BLE001 - a crash is a catch
            caught = True
        finally:
            P._num, P.parse_master_etab, P.parse_but_etab, P.master_for_formation = saved["num"], saved["pm"], saved["pb"], saved["mf"]
            P.NAME_ALIASES.clear(), P.NAME_ALIASES.update(saved["aliases"])
            P.BUT_NAME_RULES.clear(), P.BUT_NAME_RULES.update(saved["rules"])
            P.SPECIALTY_ALIASES.clear(), P.SPECIALTY_ALIASES.update(saved["spe"])
            P.BUT_SITE_OVERRIDES.clear(), P.BUT_SITE_OVERRIDES.update(saved["site"])
            c.overrides = saved["c_overrides"]
            c.aliases, c.rules, c.paysage = saved["c_aliases"], saved["c_rules"], saved["c_paysage"]
        if not caught:
            missed.append(name)
    c.rebuild()
    n = len(UI_MUTANTS) + len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, sources: dict | None = None, real: bool = False, **kw) -> list[dict]:
    c = Ctx(db, sources or P.find_sources(), real=real, **kw)
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
