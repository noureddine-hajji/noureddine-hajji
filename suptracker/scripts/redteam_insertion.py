"""Red team of sprint 8, professional insertion: BTS (Inserjeunes, per establishment) and the university's
masters / BUT (InserSup, per diploma).

    python scripts/redteam_insertion.py [--db data/suptracker.duckdb] [--real]

The checks re-parse the staged source rows independently, and compare: stored = published ('nd' and
masked cells NULL, never 0), the identities the producers satisfy (Inserjeunes partition and its
leavers' denominator; InserSup rate = employed / leavers), the BTS link (same establishment only;
options kept apart; renamed BTS never given the old diploma's figures; truth table), the latest
graduating class per diploma, the discipline map (MEEF apart), the API, and the page (escaping,
wording, nothing averaged across options or masters). A mutation test seeds bugs and requires each
to be caught.
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
from suptracker import insertion as I  # noqa: E402
from suptracker import passerelles as PA  # noqa: E402
from suptracker import poursuite as PO  # noqa: E402
from suptracker import success as SU  # noqa: E402

CHECKS = []
APP_JS = ROOT / "suptracker" / "static" / "app.js"
H = I.SERVED_HORIZON

# Real Parcoursup BTS labels -> the Inserjeunes key they must (or must not) match
KEY_TRUTH = {
    "Fluide, énergie, domotique - option B froid et conditionnement d'air": "fluide energie domotique option b froid conditionnement air",
    "Conception et Réalisation de Systèmes Automatiques": "conception realisation systeme automatique",
    "Management en hôtellerie restauration - 1ère année commune": "management hotellerie restauration",
    "Métiers de l'audio-visuel opt : gestion de la production": "metier audio visuel option gestion production",
}
# renamed BTS: the new label must not take the old diploma's key
RENAMED = {"Cybersécurité, Informatique et réseaux, ELectronique - Option A : Informatique et réseaux": "systemes numeriques option a informatique et reseaux",
           "Biologie médicale": "analyses de biologie medicale"}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, paysage=None, b1=None, truth_links=None):
        self.db, self.real, self.paysage, self.truth_links = db, real, paysage, truth_links
        src = duckdb.connect(str(db), read_only=True)
        latest = src.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.forms = src.execute("""SELECT session, cod_aff_form, cod_uai, g_ea_lib_vx, fil_lib_voe_acc, fili, contrat_etab
                                    FROM core.formation_year WHERE session = ?""", [latest]).fetchall()
        has = lambda s, t: src.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?", [s, t]).fetchone()[0]
        self.staged = {k: src.execute(f"SELECT * FROM ref.{k}").df() for k in I.RAW if has("ref", k)}
        self.stored = {t: src.execute(f"SELECT * FROM core.{t}").df() if has("core", t) else None
                       for t in ("inserjeunes_bts", "insersup", "bts_insertion_link")}
        self.b1_links = src.execute("SELECT * FROM core.licence_success_link").df() if has("core", "licence_success_link") else None
        self.but_links = src.execute("SELECT * FROM core.but_success_link").df() if has("core", "but_success_link") else None
        src.close()
        self.b1 = b1
        self.rebuild()

    def rebuild(self):
        con = duckdb.connect()
        for s in ("core", "ref"):
            con.execute(f"CREATE SCHEMA {s}")
        con.execute("""CREATE TABLE core.formation_year (session INTEGER, cod_aff_form VARCHAR, cod_uai VARCHAR, g_ea_lib_vx VARCHAR,
                       fil_lib_voe_acc VARCHAR, fili VARCHAR, contrat_etab VARCHAR)""")
        con.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?, ?)", self.forms)
        for k, df in self.staged.items():
            con.register("_s", df)
            con.execute(f"CREATE TABLE ref.{k} AS SELECT * FROM _s")
            con.unregister("_s")
        for name, df in (("licence_success_link", self.b1_links), ("but_success_link", self.but_links)):
            if df is not None:
                con.register("_s", df)
                con.execute(f"CREATE TABLE core.{name} AS SELECT * FROM _s")
                con.unregister("_s")
        con.execute("CREATE TABLE ref.insertion_profile (source VARCHAR, n_rows BIGINT, col VARCHAR, type VARCHAR, n_null BIGINT, n_distinct BIGINT, top VARCHAR)")
        self.counts = I.build(con, Path("/nonexistent"))
        self.con = con

    def rows(self, t):
        cur = self.con.execute(f"SELECT * FROM core.{t}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def q(self, sql, args=()):
        return self.con.execute(sql, list(args)).fetchall()


def num(v):
    """Independent parser: numbers as floats, 'nd'/blank/None as None."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    t = str(v).strip()
    if not t or t.lower() == "nd":
        return None
    return float(t.replace(",", "."))


@check("I1 Inserjeunes: the stored BTS rows are the latest pooled years of both sources, value by value; masked = NULL, never 0")
def i1(c: Ctx):
    bad, n = [], 0
    stored = {(r["source"], r["uai"], r["libelle_formation"], r["code"]): r for r in c.rows("inserjeunes_bts")}
    want = 0
    for key, tag, code in (("inserjeunes_lycee", "lycee", "code_formation_mefstat11"),
                           ("inserjeunes_cfa", "apprentissage", "code_formation_apprentissage")):
        df = c.staged.get(key)
        if df is None or "annee" not in df.columns:
            continue
        df = df[df.type_diplome == "BTS"]
        latest = df.annee.max()
        df = df[df.annee == latest]
        want += len(df)
        for r in df.itertuples(index=False):
            s = stored.get((tag, r.uai, r.libelle_formation, str(getattr(r, code))))
            if s is None:
                bad.append(("missing", tag, r.uai, r.libelle_formation))
                continue
            for raw, col in (("part_en_poursuite_d_etudes", "part_poursuite"), ("part_en_emploi_6_mois_apres_la_sortie", "part_emploi_6"),
                             ("taux_poursuite_etudes", "taux_poursuite"), ("taux_emploi_6_mois", "taux_emploi_6"),
                             ("taux_emploi_12_mois", "taux_emploi_12"), ("taux_emploi_24_mois", "taux_emploi_24")):
                n += 1
                v = num(getattr(r, raw))
                if (v is None) != (s[col] is None) or (v is not None and abs(v - s[col]) > 1e-9):
                    bad.append((tag, r.uai, col, v, s[col]))
    return n > 0 and not bad and len(stored) == want, f"{n} values compared, {len(bad)} differ {bad[:3]}; rows stored {len(stored)} vs latest published {want}"


@check("I2 Inserjeunes identities: continuing + employed at 6 months + other = 100; employment rate is among the leavers")
def i2(c: Ctx):
    bad = []
    for r in c.rows("inserjeunes_bts"):
        p, e, o = r["part_poursuite"], r["part_emploi_6"], r["part_autres"]
        if None not in (p, e, o) and abs(p + e + o - 100) > 1:
            bad.append(("partition", r["uai"], r["libelle_formation"]))
        if p is not None and r["taux_poursuite"] is not None and p != r["taux_poursuite"]:
            bad.append(("poursuite", r["uai"]))
        # shares are published as integers: e/(100-p) carries their rounding, larger when few leave
        tol = 100 * (0.5 + 0.5 * e / (100 - p)) / (100 - p) + 0.5 if p is not None and p < 100 and e is not None else 0
        if None not in (p, e, r["taux_emploi_6"]) and p < 100 and abs(100 * e / (100 - p) - r["taux_emploi_6"]) > tol:
            bad.append(("leavers", r["uai"], r["libelle_formation"], p, e, r["taux_emploi_6"]))
        for k in ("taux_emploi_6", "taux_emploi_12", "taux_emploi_24", "taux_poursuite"):
            if r[k] is not None and not 0 <= r[k] <= 100:
                bad.append(("bounds", r["uai"], k))
    return not bad, f"{len(bad)} broken {bad[:3]}"


@check("I3 BTS link: same establishment only, exact BTS or its options, every option apart, renamed BTS never given the old figures, truth table")
def i3(c: Ctx):
    bad = []
    ij = defaultdict(set)
    for r in c.rows("inserjeunes_bts"):
        ij[r["uai"]].add((r["source"], r["libelle_formation"], r["cle"]))
    known = {k for v in ij.values() for _, _, k in v}
    forms = {f[1]: f for f in c.forms if f[5] == "BTS"}
    c.rows_ij = c.rows("inserjeunes_bts")
    by_cod = defaultdict(list)
    for l in c.rows("bts_insertion_link"):
        by_cod[l["cod_aff_form"]].append(l)
    for cod, f in forms.items():
        ls = by_cod.get(cod)
        if not ls:
            bad.append((cod, "no link row"))
            continue
        k = I.bts_key(f[4])
        here = ij.get(f[2], set())
        exact = {(s, l) for s, l, kk in here if kk == k}
        opts = {(s, l) for s, l, kk in here if kk.startswith(k + " option")}
        want = ("etablissement_absent", set()) if not here else ("ok", exact) if exact else ("options", opts) if opts else \
               ("non_publie" if k in known else "non_trouve", set())
        got = {(l["ij_source"], l["ij_libelle"]) for l in ls if l["ij_source"]}
        if ls[0]["status"] != want[0] or got != want[1] or any(l["uai"] != f[2] for l in ls):
            bad.append((cod, f[4], ls[0]["status"], want[0]))
        b = I.for_bts(c.con, cod, "BTS")
        n_rows = sum(1 for r in c.rows_ij if r["uai"] == f[2] and (r["source"], r["libelle_formation"]) in got)
        if b and len(b["rows"]) != n_rows:
            bad.append((cod, "served rows", len(b["rows"]), len(got)))
    truth = [(lab, I.bts_key(lab), k) for lab, k in KEY_TRUTH.items() if I.bts_key(lab) != k]
    truth += [(lab, "renamed BTS matched its old name") for lab, old in RENAMED.items() if I.bts_key(lab) == I.bts_key(old)]
    if c.truth_links:
        for cod, st in c.truth_links.items():
            got = by_cod.get(cod, [{}])[0].get("status")
            if got != st:
                truth.append((cod, got, st))
    cov = ""
    if c.real:
        with_uai = [cod for cod, ls in by_cod.items() if ls[0]["status"] != "etablissement_absent"]
        linked = [cod for cod in with_uai if by_cod[cod][0]["status"] in ("ok", "options")]
        cov = f"{len(linked)}/{len(with_uai)} BTS of establishments in Inserjeunes linked"
        if len(linked) < 0.75 * len(with_uai):
            truth.append(("coverage", cov))
    return not bad and not truth, f"{len(forms)} BTS; {len(bad)} wrong {bad[:3]}; truth {truth[:3]}; {cov}"


IS_PAIRS = [(f"{m}_{h}", f"{m}_{h}") for m in I.IS_METRICS for h in I.HORIZONS]


@check("I4 InserSup: only graduates / every gender, nationality, regime are staged; stored values = published ('nd' -> NULL, never 0)")
def i4(c: Ctx):
    df = c.staged.get("insersup")
    if df is None or "promo" not in df.columns:
        return False, "no InserSup rows"
    bad = []
    off = df[(df.obtention_diplome != "diplômé") | (df.genre != "ensemble") | (df.nationalite != "ensemble") | (df.regime_inscription != "ensemble")]
    if len(off):
        bad.append(("staging kept a breakdown", len(off)))
    st = {(r["id_paysage"], r["type_diplome"], r["diplome"], r["libelle"], r["etablissement"], r["sectdis_lib"], r["discipli_lib"], r["promo"]): r
          for r in c.rows("insersup")}
    n = 0
    for r in df.to_dict("records"):
        cur = r.get("id_paysage_actuel")
        pid = cur if isinstance(cur, str) and cur else r["id_paysage"]     # pandas gives NaN (truthy) for a missing id
        s = st.get((pid, r["type_diplome_long"], r["diplome"], r["libelle_diplome"], r["etablissement"], r["sectdis_lib"], r["discipli_lib"], r["promo"]))
        if s is None:
            bad.append(("missing", pid, r["diplome"], r["promo"]))
            continue
        for raw, col in IS_PAIRS:
            if raw not in r:
                continue
            n += 1
            v = num(r[raw])
            if (v is None) != (s[col] is None) or (v is not None and abs(v - s[col]) > 1e-9):
                bad.append((pid, r["diplome"], col, r[raw], s[col]))
            if str(r[raw]).strip().lower() == "nd" and json.loads(s["masked"]).get(col) != "nd":
                bad.append((pid, r["diplome"], col, "nd not recorded"))
    return n > 0 and not bad and len(st) == len(df), f"{n} values compared, {len(bad)} differ {bad[:3]}; stored {len(st)} vs staged {len(df)}"


@check("I5 InserSup identities: employment rate = employed / leavers, rates within [0, 100], salary quartiles ordered, pooling flag = two classes")
def i5(c: Ctx):
    bad, quirks = [], []
    for r in c.rows("insersup"):
        for h in (12, 18, 24, 30):
            n_, e_, t_ = r[f"nb_sortants_{h}"], r[f"nb_sortants_en_emploi_sal_fr_{h}"], r[f"tx_sortants_en_emploi_sal_fr_{h}"]
            if None not in (n_, e_, t_) and n_ > 0 and abs(100 * e_ / n_ - t_) > 0.011:
                bad.append(("rate", r["id_paysage"], r["diplome"], r["promo"], h))
        # stable rates: SIES publishes 103-106 % for a few 2019-2020 classes at 24-30 months (not served): served horizon only
        for k, hs in (("tx_sortants_en_emploi_sal_fr", I.HORIZONS), ("tx_sortants_en_emploi_stable", (H,))):
            for h in hs:
                v = r[f"{k}_{h}"]
                if v is not None and not 0 <= v <= 100:
                    bad.append(("bounds", r["diplome"], k, h))
        for h in I.HORIZONS:
            v = r[f"tx_sortants_en_emploi_stable_{h}"]
            if v is not None and v > 100:
                quirks.append((r["diplome"], r["promo"], h, v))
        for h in I.HORIZONS:
            qs = [r[f"salaire_q{q}_{h}"] for q in (1, 2, 3)]
            if None not in qs and not qs[0] <= qs[1] <= qs[2]:
                bad.append(("quartiles", r["diplome"], h))
        if r["pooled"] != (len(I.promo_years(r["promo"])) > 1):
            bad.append(("pooled", r["promo"]))
    return not bad, f"{len(bad)} broken {bad[:3]}; published stable rates above 100 % (not served) {len(quirks)} {quirks[:2]}"


def ref_latest(rows, pid, typ, disc=None, diplome_all=False):
    """Independent: per diploma, the row with the greatest last year among those with an 18-month leavers figure."""
    best = {}
    for r in rows:
        if r["id_paysage"] != pid or r["type_diplome"] != typ or (r["diplome"] == "all") != diplome_all:
            continue
        if disc is not None and r["discipline"] != disc:
            continue
        if r[f"nb_sortants_{H}"] is None and json.loads(r["masked"]).get(f"nb_sortants_{H}") is None:
            continue
        y = max(int(x) for x in re.findall(r"\d{4}", r["promo"]))
        k = (r["diplome"], r["libelle"], r["etablissement"], r["sectdis_lib"])
        if k not in best or y > best[k][0]:
            best[k] = (y, r)
    return {k: v[1] for k, v in best.items()}


@check("I6 licence block: the university of B1's link, its masters of this discipline only (MEEF apart), the latest class per master, totals and France")
def i6(c: Ctx):
    rows = c.rows("insersup")
    pmap = c.paysage or SU.SIES_PAYSAGE
    links = c.q("SELECT cod_aff_form, etab, discipline FROM core.licence_success_link WHERE etab IS NOT NULL AND discipline IS NOT NULL")
    seen, bad, n = set(), [], 0
    for cod, etab, disc in links:
        if (etab, disc) in seen:
            continue
        seen.add((etab, disc))
        b = I.for_licence(c.con, cod, "Licence", "Public", paysage=c.paysage)
        n += 1
        want = ref_latest(rows, pmap.get(etab), "Master LMD", disc)
        got = {(m["diplome"], m["libelle"], m["etablissement"], m["sectdis_lib"]): m for m in b["masters"]}
        if set(got) != set(want) or any(got[d]["promo"] != want[d]["promo"] for d in want):
            bad.append((etab, disc, sorted(set(got) ^ set(want))[:3]))
        if any(m["discipline"] in ("meef", None) or m["type_diplome"] != "Master LMD" for m in b["masters"]):
            bad.append((etab, disc, "foreign master"))
        tot = ref_latest(rows, pmap.get(etab), "Master LMD", diplome_all=True)
        if (b["total"] or {}).get("promo") != (next(iter(tot.values()))["promo"] if tot else None):
            bad.append((etab, "total"))
        if b["france"] and b["france"]["id_paysage"] != "all":
            bad.append((etab, "france"))
        for m in b["masters"]:
            g, _ = E.grade(m[f"tx_sortants_en_emploi_sal_fr_{H}"], m[f"nb_sortants_{H}"], m["last_year"], "identifiant")
            if m["maillon"]["fiabilite"] not in (g, None) and m["maillon"]["lien"] == "identifiant":
                bad.append((etab, m["diplome"], "grade"))
    meef = c.q("SELECT count(*) FROM core.insersup WHERE type_diplome = 'Master MEEF' AND discipline <> 'meef'")[0][0]
    return n > 0 and not bad and not meef, f"{n} university x discipline blocks, {len(bad)} wrong {bad[:2]}; MEEF in a discipline {meef}"


@check("I7 BUT block: the sprint-6 university and specialty, the specialty row by its key, university and national totals")
def i7(c: Ctx):
    rows = c.rows("insersup")
    pmap = c.paysage or SU.SIES_PAYSAGE
    pairs = set(c.q("SELECT DISTINCT etab, specialite FROM core.but_success_link WHERE etab IS NOT NULL")) if c.but_links is not None else set()
    bad, n = [], 0
    for etab, spe in sorted(pairs, key=str)[:200]:
        b = I.for_but(c.con, etab, spe, paysage=c.paysage)
        n += 1
        pid = pmap.get(etab)
        cand = [r for r in ref_latest(rows, pid, "Bachelor universitaire de technologie").values() if PO._key(r["libelle"]) == spe]
        want = cand[0]["diplome"] if len(cand) == 1 else None      # several parts: no single figure
        if (b["specialite"] or {}).get("diplome") != want:
            bad.append((etab, spe, (b["specialite"] or {}).get("diplome"), want))
        if b["france"] and (b["france"]["id_paysage"] != "all" or b["france"]["diplome"] != "all"):
            bad.append((etab, "france"))
    return not bad, f"{n} BUT blocks, {len(bad)} wrong {bad[:3]}"


def fn_body(js: str, name: str) -> str:
    i = js.index(name)
    j = min(k for k in (js.find("\nfunction ", i + 1), js.find("\nconst ", i + 1)) if k > 0)
    return js[i:j]


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 8: insertion")
    blk = js[i: js.index("function offerCard", i)]
    safe = ("esc(", "isv(", "pc1d(", "fmt(", "fiabBadge(", "promoTxt(", "insRow(", "tip(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", blk)
           if re.search(r"\.(?:libelle|libelle_formation|etab_label|discipline_label|reason|promo|voie|annee|code|sectdis_lib)\b", m) and not m.lstrip().startswith(safe)]
    words = {"function insertionCard(": ("ont quitté les études", "pas des chances", "publiées séparément", "ne publie pas de taux par discipline",
                                         "ne publie pas les effectifs"),
             "const INS_NOTE": ("ont quitté les études", "Emploi salarié en France", "pas des chances")}
    wording = all(w in fn_body(js, f) for f, ws in words.items() for w in ws)
    averaged = re.findall(r"\.reduce\(|Math\.(?:max|min)\([^)]*tx_|/\s*x\.rows\.length|/\s*x\.masters\.length", blk)
    wired = "${insertionCard(d.insertion)}" in js and "${butInsertion(b.insertion)}" in js
    ok = not raw and wording and not averaged and wired
    return ok, f"unescaped {raw[:3]}; wording {wording}; averaged {averaged[:2]}; wired {wired}"


@check("I8 page: stored strings escaped, wording (leavers, salaried in France, not chances, options apart), nothing averaged")
def i8(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped master label", "insRow(`Master ${esc(m.libelle)}${dupM(m)", "insRow(`Master ${m.libelle}${dupM(m)"),
    ("unescaped sector label", "(${esc(m.sectdis_lib)})", "(${m.sectdis_lib})"),
    ("unescaped BTS label", "<tr><td>${esc(r.libelle_formation)}", "<tr><td>${r.libelle_formation}"),
    ("leavers caveat dropped", "Taux parmi les diplômés qui ont quitté les études (ceux qui continuent ne sont pas comptés). ", ""),
    ("options averaged", 'const rows = x.rows.map(', 'const avg = x.rows.reduce((a, r) => a + (r.taux_emploi_6 || 0), 0) / x.rows.length; const rows = x.rows.map('),
    ("card not wired", "${insertionCard(d.insertion)}", ""),
]


@check("I9 mutation test: oldest class served, 'nd' as 0, link across establishments, renamed BTS given old figures, MEEF in a discipline, staging filter dropped, UI bugs")
def i9(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    saved = {"latest": I._latest, "num": I._num, "links": I.build_bts_links, "key": I.bts_key, "disc": dict(PA.MASTER_DISCIPLINE),
             "keep": dict(I.KEEP), "staged": dict(c.staged)}

    def oldest(rows):
        best = {}
        for r in rows:
            k = (r["id_paysage"], r["diplome"])
            if k not in best or (r["last_year"] or 0) < (best[k]["last_year"] or 0):
                best[k] = r
        return list(best.values())

    def nd_zero(v):
        x, why = saved["num"](v)
        return (0.0, None) if why == "nd" else (x, why)

    def any_uai(con):
        n = saved["links"](con)
        con.execute("""UPDATE core.bts_insertion_link l SET status = 'ok', ij_source = j.source, ij_libelle = j.libelle_formation
                       FROM (SELECT DISTINCT cle, source, libelle_formation FROM core.inserjeunes_bts) j
                       WHERE l.status IN ('non_publie') AND j.cle = l.cle""")
        return n

    def renamed_key(label):
        k = saved["key"](label)
        return {saved["key"](new): saved["key"](old) for new, old in RENAMED.items()}.get(k, k).replace(
            "cybersecurite informatique reseaux electronique", "systeme numerique")

    def no_filter():
        df = c.staged["insersup"]
        dup = df.copy()
        dup["genre"] = "femme"
        c.staged["insersup"] = __import__("pandas").concat([df, dup])

    mutants = [   # (name, apply before the rebuild, SQL applied after it, checks that must fail)
        ("oldest graduating class served", lambda: setattr(I, "_latest", oldest), None, (i6,)),
        # InserSup's 'nd' go through the SQL insert, Inserjeunes values through _num: seed both
        ("'nd' stored as 0 (InserSup)", lambda: None,
         "UPDATE core.insersup SET tx_sortants_en_emploi_sal_fr_18 = 0 WHERE masked LIKE '%tx_sortants_en_emploi_sal_fr_18%'", (i4,)),
        ("masked Inserjeunes value stored as 0", lambda: setattr(I, "_num", lambda v: (0.0, None) if v is None or v != v else saved["num"](v)), None, (i1,)),
        ("BTS linked across establishments", lambda: setattr(I, "build_bts_links", any_uai), None, (i3,)),
        ("renamed BTS given the old diploma's key", lambda: setattr(I, "bts_key", renamed_key), None, (i3,)),
        ("MEEF masters filed under a licence discipline", lambda: None,
         "UPDATE core.insersup SET discipline = 'alsh', type_diplome = 'Master LMD' WHERE type_diplome = 'Master MEEF'", (i4, i6)),
        ("staging filter dropped (a gender breakdown kept)", no_filter, None, (i4,)),
    ]
    for name, apply, post, checks in mutants:
        try:
            apply()
            c.rebuild()
            if post:
                c.con.execute(post)
            caught = any(not ch(c)[0] for ch in checks)
        except Exception:  # noqa: BLE001 - a crash is a catch
            caught = True
        finally:
            I._latest, I._num, I.build_bts_links, I.bts_key = saved["latest"], saved["num"], saved["links"], saved["key"]
            PA.MASTER_DISCIPLINE.clear(), PA.MASTER_DISCIPLINE.update(saved["disc"])
            c.staged = dict(saved["staged"])
        if not caught:
            missed.append(name)
    c.rebuild()
    n = len(UI_MUTANTS) + len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, **kw) -> list[dict]:
    c = Ctx(db, real=real, **kw)
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
