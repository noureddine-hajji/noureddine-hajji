"""Red team of sprint 3, the data foundation: establishment register, Paysage links, successions,
B1 rebuilt on ids, reliability grades ("maillon"), source register and glossary.

    python scripts/redteam_referentiel.py [--db data/suptracker.duckdb] [--real]

The checks rebuild the links in memory from the warehouse's formations, cartographie and register,
re-derive each rule independently in Python, and compare. A mutation test seeds bugs and requires
each to be caught.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from suptracker import config  # noqa: E402
from suptracker import evidence as E  # noqa: E402
from suptracker import glossary as G  # noqa: E402
from suptracker import referentiel as R  # noqa: E402
from suptracker import sources as SRC  # noqa: E402
from suptracker import success as SU  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
INDEX = ROOT / "suptracker" / "static" / "index.html"
CHECKS = []
SHARE_REF, MIN_REF = 0.8, 5   # the red team's own copy of the succession thresholds (README, sprint 3)
STOP = {"universite", "université", "de", "des", "du", "la", "le", "les", "et", "site", "campus", "antenne", "i.u.t",
        "iut", "ecole", "école", "institut", "national", "nationale", "superieur", "superieure", "faculte", "ufr", "paris"}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tokens(s):
    return {t for t in fold(s).split() if (len(t) >= 4 or t.isdigit()) and t not in STOP}


class Ctx:
    def __init__(self, db: Path, real: bool, xlsx: Path | None, table=None, paysage=None):
        self.db, self.real, self.xlsx, self.table, self.paysage = db, real, xlsx, table, paysage
        src = duckdb.connect(str(db), read_only=True)
        fy_cols = {r[0] for r in src.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'core' AND table_name = 'formation_year'""").fetchall()}
        want = ["session", "cod_aff_form", "cod_uai", "g_ea_lib_vx", "etablissement_id_paysage", "composante_id_paysage",
                "fili", "contrat_etab", "fil_lib_voe_acc"]
        sel = ", ".join(c if c in fy_cols else f"NULL::VARCHAR AS {c}" for c in want)
        self.fy = src.execute(f"SELECT {sel} FROM core.formation_year").fetchall()
        carto_cols = {r[0] for r in src.execute("""SELECT column_name FROM information_schema.columns
                      WHERE table_schema = 'core' AND table_name = 'cartographie'""").fetchall()}
        self.carto = (src.execute("SELECT cod_aff_form, etablissement_id_paysage, composante_id_paysage FROM core.cartographie").fetchall()
                      if "etablissement_id_paysage" in carto_cols else [])
        self.reg = src.execute(f"SELECT {', '.join(R.REF_COLUMNS.values())} FROM ref.etablissement").fetchall()
        self.stored = {t: src.execute(f"SELECT * FROM ref.{t}").fetchall() for t in ("succession", "formation_etablissement")
                       if src.execute(f"""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'ref'
                                         AND table_name = '{t}'""").fetchone()[0]}
        src.close()
        self.rebuild()

    def rebuild(self):
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core; CREATE SCHEMA ref")
        con.execute("""CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, cod_uai VARCHAR, g_ea_lib_vx VARCHAR,
            etablissement_id_paysage VARCHAR, composante_id_paysage VARCHAR, fili VARCHAR, contrat_etab VARCHAR, fil_lib_voe_acc VARCHAR)""")
        import pandas as pd   # bulk load: a row-by-row insert of ~56k formations per rebuild is too slow
        fy = pd.DataFrame(self.fy, columns=["session", "cod_aff_form", "cod_uai", "g_ea_lib_vx", "etablissement_id_paysage",
                                            "composante_id_paysage", "fili", "contrat_etab", "fil_lib_voe_acc"])
        con.register("_fy", fy)
        con.execute("INSERT INTO core.formation_year SELECT * FROM _fy")
        con.unregister("_fy")
        con.execute("CREATE TABLE core.cartographie (cod_aff_form VARCHAR, etablissement_id_paysage VARCHAR, composante_id_paysage VARCHAR)")
        if self.carto:
            con.register("_ca", pd.DataFrame(self.carto, columns=["cod_aff_form", "etablissement_id_paysage", "composante_id_paysage"]))
            con.execute("INSERT INTO core.cartographie SELECT * FROM _ca")
            con.unregister("_ca")
        con.execute(f"CREATE TABLE ref.etablissement ({', '.join(f'{v} VARCHAR' for v in R.REF_COLUMNS.values())})")
        con.executemany(f"INSERT INTO ref.etablissement VALUES ({', '.join('?' * len(R.REF_COLUMNS))})", self.reg)
        R.build_links(con)
        self.n_b1 = SU.attach(con, self.xlsx, self.table, self.paysage) if self.xlsx else 0
        self.con = con
        self.latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]

    def q(self, sql, *a):
        return self.con.execute(sql, list(a)).fetchall()


# --------------------------------------------------------------------------------- register
@check("F1 register: one row per Paysage id; a UAI shared by two establishments (split university) is reported and never votes")
def f1(c: Ctx):
    ids = Counter(r[0] for r in c.reg)
    dup = [k for k, n in ids.items() if n > 1 or not k]
    owner = defaultdict(set)
    for r in c.reg:
        rec = dict(zip(R.REF_COLUMNS.values(), r))
        for u in [rec["uai"], *(rec["anciens_codes_uai"] or "").split(";")]:
            if u and u.strip():
                owner[u.strip()].add(rec["id_paysage"])
    shared = {u: s for u, s in owner.items() if len(s) > 1}
    voted = [o for o, n, m, *_ in c.q("SELECT old_id, new_id, method FROM ref.succession WHERE method = 'uai'")
             if any(u in shared for u in {x[0] for x in c.q("SELECT DISTINCT cod_uai FROM ref.formation_etablissement WHERE etablissement_id_paysage = ?", o)})]
    return not dup and len(ids) > 0 and not voted, f"{len(ids)} establishments; duplicate ids {dup[:3]}; shared UAIs (ignored) {sorted(shared)}; successions voted through a shared UAI {voted}"


# --------------------------------------------------------------------------------- links
def expected_links(c: Ctx):
    """Independent Python re-derivation of the raw id and its source per (session, formation)."""
    carto = {cod: pid for cod, pid, _ in c.carto if pid}
    by_cod = defaultdict(list)
    for s, cod, uai, name, pid, comp, *_ in c.fy:
        by_cod[cod].append((s, (pid or "").strip() or None))
    out = {}
    for cod, rows in by_cod.items():
        rows.sort()
        last = None
        for s, pid in rows:
            if pid:
                out[(s, cod)] = (pid, "parcoursup")
            elif carto.get(cod):
                out[(s, cod)] = (carto[cod], "cartographie")
            elif last:
                out[(s, cod)] = (last, "campagne_precedente")
            else:
                out[(s, cod)] = (None, None)
            last = pid or last
    return out


@check("F2 every formation keeps SIES's own id when published; 2025's empty ids come from the cartographie, then the previous campaign")
def f2(c: Ctx):
    exp = expected_links(c)
    got = {(s, cod): (pid, src) for s, cod, pid, src in c.q(
        "SELECT session, cod_aff_form, etablissement_id_paysage, id_source FROM ref.formation_etablissement")}
    wrong = [(k, exp[k], got.get(k)) for k in exp if got.get(k) != exp[k]]
    srcs = Counter(v[1] for k, v in got.items() if k[0] == c.latest)
    return not wrong, f"{len(exp)} formation-campaigns, {len(wrong)} differ {wrong[:2]}; latest campaign sources {dict(srcs)}"


def expected_successions(c: Ctx):
    reg = {r[0] for r in c.reg}
    owners = defaultdict(set)
    for r in c.reg:
        rec = dict(zip(R.REF_COLUMNS.values(), r))
        for u in [rec["uai"], *(rec["anciens_codes_uai"] or "").split(";")]:
            if u and u.strip():
                owners[u.strip()].add(rec["id_paysage"])
    uai_owner = {u: next(iter(s)) for u, s in owners.items() if len(s) == 1}
    raw = expected_links(c)
    sies = {(s, cod): (pid or "").strip() or None for s, cod, uai, name, pid, *_ in c.fy}
    trans = defaultdict(Counter)
    for (s, cod), pid in sies.items():
        nxt = sies.get((s + 1, cod))
        if pid and nxt and pid != nxt and pid not in reg:
            trans[pid][nxt] += 1
    votes = defaultdict(lambda: defaultdict(set))
    for s, cod, uai, *_ in c.fy:
        pid = raw[(s, cod)][0]
        if pid and pid not in reg and uai in uai_owner:
            votes[pid][uai_owner[uai]].add(cod)
    out = {}
    for old in set(trans) | set(votes):
        for method, cnt in (("transition", trans.get(old, Counter())),
                            ("uai", Counter({k: len(v) for k, v in votes.get(old, {}).items()}))):
            tot = sum(cnt.values())
            best = [(n, new) for new, n in cnt.items() if new in reg and n / tot >= SHARE_REF and n >= MIN_REF]
            if best:
                out[old] = (max(best)[1], method)
                break
    return out


@check("F3 successions (mergers, renamings) re-derived independently: same old -> new ids, near-unanimous evidence")
def f3(c: Ctx):
    exp = expected_successions(c)
    got = {o: (n, m) for o, n, m, *_ in c.q("SELECT old_id, new_id, method, n, n_old, share FROM ref.succession")}
    reg = {r[0] for r in c.reg}
    chain = [o for o, (n, _) in got.items() if n in got or o in reg]
    return got == exp and not chain, f"{len(got)} successions; differ {set(got.items()) ^ set(exp.items())}; chains or register olds {chain}"


@check("F4 a succession is plausible: the new establishment's name shares a word with the old id's formations")
def f4(c: Ctx):
    names = dict((r[0], r[3]) for r in c.reg)
    by_old = defaultdict(set)
    for s, cod, uai, name, pid, *_ in c.fy:
        if pid:
            by_old[pid.strip()].add(name)
    bad = []
    for old, new, *_ in c.q("SELECT * FROM ref.succession"):
        t = tokens(names.get(new))
        if not any(t & tokens(n) for n in by_old.get(old, ())):
            # the old id may only be known from the 2025 fill: use those formations too
            fill = {r[0] for r in c.q("SELECT g_ea_lib_vx FROM ref.formation_etablissement WHERE etablissement_id_paysage = ?", old)}
            if not any(t & tokens(n) for n in fill):
                bad.append((old, new, names.get(new)))
    return not bad, f"implausible {bad[:3]}"


@check("F5 coverage: public licences, LAS, PASS and BUT of the latest campaign reach the register")
def f5(c: Ctx):
    rows = c.q("""SELECT f.fili, count(*), avg((r.id_resolu IS NOT NULL)::INT) FROM ref.formation_etablissement r
                  JOIN core.formation_year f USING (session, cod_aff_form)
                  WHERE r.session = ? AND f.contrat_etab = 'Public' AND f.fili IN ('Licence', 'Licence_Las', 'PASS', 'BUT')
                  GROUP BY 1 ORDER BY 2 DESC""", c.latest)
    cover = {f: round(100 * a, 1) for f, n, a in rows}
    lic = cover.get("Licence", 0)
    ok = (lic >= 90 and cover.get("BUT", 0) >= 90) if c.real else bool(rows)
    unresolved = c.q("""SELECT r.etablissement_id_paysage, count(*) FROM ref.formation_etablissement r JOIN core.formation_year f
        USING (session, cod_aff_form) WHERE r.session = ? AND f.contrat_etab = 'Public' AND f.fili IN ('Licence', 'BUT')
        AND resolution = 'hors_registre' GROUP BY 1 ORDER BY 2 DESC LIMIT 4""", c.latest)
    return ok, f"resolved % by programme {cover}; main unresolved ids {unresolved}"


MERGERS_REAL = {   # formation name (folded regex) -> words of the register name it must resolve to
    r"bourgogne": "bourgogne europe", r"franche comte": "marie et louis pasteur", r"universite de brest": "bretagne occidentale",
    r"universite jean monnet": "jean monnet", r"paul valery": "paul valery", r"toulouse iii": "universite de toulouse",
    r"universite de rennes epe": "universite de rennes", r"toulouse capitole": "toulouse capitole",
}
MERGERS_SYN = {r"exemple lyon": "exemple lyon", r"exemple paris": "exemple paris"}


@check("F14 known mergers and renamings resolve to the right current establishment")
def f14(c: Ctx):
    names = dict((r[0], fold(r[3])) for r in c.reg)
    truth = MERGERS_REAL if c.real else MERGERS_SYN
    bad, seen = [], Counter()
    # public university programmes that carry an id (formations new in 2025 without any id are F5's concern)
    for name, idr in c.q("""SELECT r.g_ea_lib_vx, r.id_resolu FROM ref.formation_etablissement r JOIN core.formation_year f
                            USING (session, cod_aff_form) WHERE r.session = ? AND r.resolution <> 'absent'
                            AND f.contrat_etab = 'Public' AND f.fili IN ('Licence', 'Licence_Las', 'BUT', 'PASS')""", c.latest):
        for rx, want in truth.items():
            if re.search(rx, fold(name)):
                seen[rx] += 1
                if want not in names.get(idr, ""):
                    bad.append((name, idr, names.get(idr)))
    unseen = [rx for rx in truth if not seen[rx]]
    return not bad and not unseen, f"wrong or unresolved {len(bad)} {bad[:2]}; cases absent from the data {unseen}; checked {dict(seen)}"


# --------------------------------------------------------------------------------- B1 on ids
@check("F6 the SIES-university -> Paysage table: ids in the register, distinct, public universities whose name matches")
def f6(c: Ctx):
    table = c.paysage and {v: k for k, v in c.paysage.items()} or SU.SIES_PAYSAGE
    reg = {r[0]: dict(zip(R.REF_COLUMNS.values(), r)) for r in c.reg}
    missing = [k for k, v in table.items() if v not in reg]
    dup = [v for v, n in Counter(table.values()).items() if n > 1]
    private = [k for k, v in table.items() if v in reg and reg[v]["secteur"] != "public"]
    if c.paysage is None:
        unnamed = [k for k, v in table.items() if v in reg and not (tokens(SU.UNIVERSITY_LABEL.get(k, k)) | tokens(k)) & tokens(reg[v]["nom"])]
        absent = sorted(set(SU.UNIVERSITIES) - set(table))
    else:
        unnamed, absent = [], []
    return not (missing or dup or private or unnamed or absent), f"not in register {missing}; shared ids {dup}; private {private}; name mismatch {unnamed}; universities without id {absent}"


@check("F7 B1 by id and B1 by name never disagree; the link records how it was made")
def f7(c: Ctx):
    if not c.xlsx:
        return True, "no SIES workbook: B1 not built"
    rows = c.q("""SELECT l.cod_aff_form, l.etab, l.lien, l.id_paysage, f.g_ea_lib_vx FROM core.licence_success_link l
                  JOIN core.formation_year f ON f.cod_aff_form = l.cod_aff_form AND f.session = l.session""")
    by_id = c.paysage or SU.PAYSAGE_SIES
    dis, bad_lien, n_both = [], [], 0
    for cod, etab, lien, pid, name in rows:
        by_name, _ = SU.university_of(name, c.table)
        if pid and by_name and by_id.get(pid):
            n_both += 1
            if by_id[pid] != by_name:
                dis.append((name, by_name, by_id[pid]))
        if etab and lien != ("identifiant" if pid else "nom"):
            bad_lien.append((cod, lien, pid))
        if not etab and lien is not None:
            bad_lien.append((cod, "lien without a university"))
    n_id = sum(1 for r in rows if r[2] == "identifiant")
    return not dis and not bad_lien, f"{n_both} formations linked both ways, {len(dis)} disagree {dis[:2]}; link labels wrong {bad_lien[:2]}; by id {n_id}, by name {sum(1 for r in rows if r[2] == 'nom')}"


# --------------------------------------------------------------------------------- reliability
def grade_ref(value, n, cohort, lien):
    if value is None:
        return None
    if n is None or n < 30:
        return "C"
    weak = n < 100 or (cohort is not None and 2025 - cohort > 3) or lien != "identifiant"
    return "B" if weak else "A"


@check("F8 reliability grades follow the published rules, everywhere they are shown")
def f8(c: Ctx):
    cases = [(50.0, 2000, 2023, "identifiant"), (50.0, 99, 2023, "identifiant"), (50.0, 2000, 2020, "identifiant"),
             (50.0, 2000, 2023, "nom"), (50.0, 29, 2023, "identifiant"), (None, 2000, 2023, "identifiant"), (50.0, None, 2023, "identifiant"),
             (50.0, 100, 2022, "identifiant"), (50.0, 30, 2022, "identifiant")]
    wrong = [x for x in cases if E.grade(*x)[0] != grade_ref(*x)]
    served = []
    if c.xlsx:
        for (cod,) in c.q("SELECT cod_aff_form FROM core.licence_success_link WHERE etab IS NOT NULL AND discipline IS NOT NULL ORDER BY hash(cod_aff_form) LIMIT 120"):
            b = SU.for_formation(c.con, cod, "Licence", "Public")
            for k in b["kinds"].values():
                m = k["maillon"]
                if m["fiabilite"] != grade_ref(k["taux"], k["inscrits"], k["cohort"], b["lien"]) or m["granularite"] != "universite_x_discipline" \
                        or "pas seulement cette licence" not in (m["avertissement"] or "") or m["lien"] != b["lien"]:
                    served.append((cod, m["fiabilite"], m["lien"]))
    return not wrong and not served, f"rule cases wrong {wrong}; served grades wrong {served[:3]}"


# --------------------------------------------------------------------------------- sources, glossary, UI
@check("F9 source register: every ingested dataset and every committed file is registered, and vice versa")
def f9(c: Ctx):
    reg_ds = {d for s in SRC.SOURCES for d in s.get("datasets", ())}
    cfg = {d.key for d in config.DATASETS}
    files = [p.name for p in (ROOT / "data" / "sources").glob("*") if p.is_file()]
    globs = [s["file_glob"] for s in SRC.SOURCES if s["access"] == "owner_upload"]
    import fnmatch
    orphan_files = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in globs)]
    bad = [s["key"] for s in SRC.SOURCES if s["access"] not in SRC.ACCESS or s["status"] not in SRC.STATUS
           or (s["status"] == "prevu") != (s["access"] == "planned") or (s["status"] == "prevu" and not (s.get("sprint") and s.get("url")))]
    keys = [k for k, n in Counter(s["key"] for s in SRC.SOURCES).items() if n > 1]
    ok = cfg == reg_ds and not orphan_files and not bad and not keys
    return ok, f"datasets not registered {sorted(cfg - reg_ds)}; registered but not ingested {sorted(reg_ds - cfg)}; unregistered files {orphan_files}; bad entries {bad}; duplicate keys {keys}"


def ui_glossary(js: str, html: str) -> tuple[bool, str]:
    i = js.index("function viewGlossaire")
    blk = js[i: js.index("// ---- audience measurement", i)]
    raw = re.findall(r"\$\{(?:g|s)\.(?:terme|definition|title|producer|granularity|url|key|sprint)\}", blk)
    meth = "esc(META.methodology[g.methode])" in blk
    routed = 'if (a === "glossaire") return viewGlossaire(' in js and 'glossaire: "glossaire"' in js
    nav = 'href="#/glossaire"' in html
    from suptracker.analytics import ROUTES
    ok = not raw and meth and routed and nav and "glossaire" in ROUTES
    return ok, f"unescaped {raw[:3]}; method text escaped {meth}; routed {routed}; nav link {nav}; analytics route {'glossaire' in ROUTES}"


@check("F10 glossary: definitions point to existing methods, promise nothing, and the page escapes what it prints")
def f10(c: Ctx):
    from suptracker.api import METHODOLOGY
    dangling = [k for k, (_, _, m) in G.GLOSSARY.items() if m and m not in METHODOLOGY]
    promise = [k for k, (t, d, _) in G.GLOSSARY.items() if re.search(r"tu seras admis|garanti|probabilit[ée] d'(?:être )?admis", d, re.I)
               and "pas des probabilit" not in d]
    ok, detail = ui_glossary(APP_JS.read_text(), INDEX.read_text())
    return ok and not dangling and not promise, f"methods missing {dangling}; promise wording {promise}; {detail}"


def ui_badge(js: str) -> tuple[bool, str]:
    i = js.index("function fiabBadge")
    blk = js[i: js.index("\n}\n", i)]
    esc_ok = 'esc((m.raisons || []).join(" ; "))' in blk
    white = '["A", "B", "C"].includes(m.fiabilite)' in blk
    shown = "${fiabBadge(u && u.maillon)}" in js and 'tip("fiabilite")' in js
    return esc_ok and white and shown, f"reasons escaped {esc_ok}; grade whitelisted {white}; shown on the B1 table {shown}"


@check("F11 the reliability badge escapes its reasons, whitelists the grade and is shown with its explanation")
def f11(c: Ctx):
    return ui_badge(APP_JS.read_text())


@check("F12 the published warehouse has the same links and successions as this rebuild")
def f12(c: Ctx):
    if not c.stored:
        return True, "warehouse built before sprint 3"
    fresh = set(c.q("SELECT * FROM ref.formation_etablissement"))
    stored = set(c.stored.get("formation_etablissement", []))
    s_f, s_s = set(c.q("SELECT * FROM ref.succession")), set(c.stored.get("succession", []))
    return fresh == stored and s_f == s_s, f"links differ {len(fresh ^ stored)}; successions differ {len(s_f ^ s_s)}"


# --------------------------------------------------------------------------------- mutation test
@check("F13 mutation test: every seeded bug in links, successions, B1, grades, register and UI is caught")
def f13(c: Ctx):
    missed = []
    js, html = APP_JS.read_text(), INDEX.read_text()
    for name, old, new, fn in [
        ("glossary term unescaped", "${esc(g.terme)}", "${g.terme}", lambda j: ui_glossary(j, html)),
        ("glossary method unescaped", "esc(META.methodology[g.methode])", "META.methodology[g.methode]", lambda j: ui_glossary(j, html)),
        ("badge reasons unescaped", 'esc((m.raisons || []).join(" ; "))', '(m.raisons || []).join(" ; ")', ui_badge),
        ("grade not whitelisted", '["A", "B", "C"].includes(m.fiabilite) ? m.fiabilite : "C"', "m.fiabilite", ui_badge),
    ]:
        if old not in js or fn(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"share": R.SUCCESSION_SHARE, "min": R.SUCCESSION_MIN, "build_links": R.build_links, "solid": E.SOLID_N,
             "grade": E.grade, "PAYSAGE_SIES": SU.PAYSAGE_SIES, "SOURCES": SRC.SOURCES, "reg": c.reg, "paysage": c.paysage}
    orig_grade = E.grade
    data_mutants = [
        ("weak succession evidence accepted", lambda: setattr(R, "SUCCESSION_SHARE", 0.0), [f3]),
        ("single-formation succession accepted", lambda: setattr(R, "SUCCESSION_MIN", 1), [f3]),
        ("former UAIs ignored", lambda: setattr(c, "reg", [tuple(None if i == 2 else v for i, v in enumerate(r)) for r in saved["reg"]]), [f14]),
        ("reliability ignores the link method", lambda: setattr(E, "grade", lambda v, n, co, lien: orig_grade(v, n, co, "identifiant")), [f8]),
        ("reliability threshold lowered", lambda: setattr(E, "SOLID_N", 10), [f8]),
        ("a dataset left out of the source register", lambda: setattr(SRC, "SOURCES", saved["SOURCES"][1:]), [f9]),
    ]
    if c.real:
        swap = dict(SU.PAYSAGE_SIES)
        a, b = "8k883", "6G2TU"     # Sorbonne Nouvelle <-> Paris 1
        swap[a], swap[b] = SU.PAYSAGE_SIES[b], SU.PAYSAGE_SIES[a]
        data_mutants += [("two universities' ids swapped", lambda: setattr(SU, "PAYSAGE_SIES", swap), [f7])]
    if any(r[1] for r in c.carto):
        data_mutants += [("cartographie preferred over SIES's own id", lambda: setattr(R, "build_links", _carto_first(saved["build_links"])), [f2])]
    for name, apply, checks in data_mutants:
        try:
            apply()
            c.rebuild()
            caught = any(not fn(c)[0] for fn in checks)
        except Exception:  # noqa: BLE001 - a crash is a detection too
            caught = True
        finally:
            R.SUCCESSION_SHARE, R.SUCCESSION_MIN, R.build_links = saved["share"], saved["min"], saved["build_links"]
            E.SOLID_N, E.grade, SU.PAYSAGE_SIES, SRC.SOURCES = saved["solid"], saved["grade"], saved["PAYSAGE_SIES"], saved["SOURCES"]
            c.reg, c.paysage = saved["reg"], saved["paysage"]
        if not caught:
            missed.append(name)
    c.rebuild()
    n = 4 + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def _carto_first(orig):
    def run(con):
        orig(con)
        con.execute("""UPDATE ref.formation_etablissement r SET etablissement_id_paysage = c.etablissement_id_paysage, id_source = 'cartographie'
                       FROM core.cartographie c WHERE c.cod_aff_form = r.cod_aff_form AND c.etablissement_id_paysage IS NOT NULL
                       AND r.id_sies IS NOT NULL AND c.etablissement_id_paysage <> r.id_sies""")
        con.execute("""UPDATE ref.formation_etablissement r SET id_source = 'cartographie'
                       FROM core.cartographie c WHERE c.cod_aff_form = r.cod_aff_form AND c.etablissement_id_paysage IS NOT NULL""")
    return run


def run(db: Path, real: bool = False, xlsx: Path | None = None, table=None, paysage=None) -> list[dict]:
    c = Ctx(db, real, xlsx, table, paysage)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real, SU.source_path(ROOT / "data" / "sources"))
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
