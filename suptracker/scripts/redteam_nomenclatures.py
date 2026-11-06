"""Red team of sprint 13, the job reference (ROME -> FAP-2021 / FAP-2009 -> ISCO-08).

    python scripts/redteam_nomenclatures.py [--db data/suptracker.duckdb] [--real]

  N1 every stored table equals the raw official file re-read independently (pandas, not the module's readers);
     FAP-2009 is re-derived from the Dares xls (the module reads the SAS program): both must agree row for row
  N2 the ROME -> ISCO table is re-derived independently (pandas merge of the Dares titles with the Insee G44 codes,
     the status column chosen from the qualification by an independent rule): same rows, same precision flags;
     at least 95 % of the titles find their Insee code
  N3 cross-check by another official path: ROME -> FAP-2021 -> PCS 2020 (Dares, probabilistic) -> ISCO (Insee
     matrix): for at least 95 % of the ROME codes the two ISCO sets meet; the Dares title table and the ROME table
     agree on the family for at least 99 % of (title, qualification) rows
  N4 serving: each ROME code's qualification classes are covered exactly once by its FAP-2021 families; FAP-2009
     classes carry no FAP-2021 name; title counts are DISTINCT titles; partial ISCO codes carry no label; unknown or
     malformed codes are handled; a job page carries exactly the codes of its own ROME codes; API public cache
  N5 page (codesCard run with Node on hostile data): every string escaped, no percentage, "pas une part des emplois",
     "pas des chiffres sur l'emploi", partial codes as 21xx, FAP-2009 qualification never named with FAP-2021 names
  N6 upkeep: files registered and online in the source register, methodology and feature, xls reader in the pipeline
     requirements, empty build safe, warehouse under 95 MB
  N7 mutation test
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import metiers as MT  # noqa: E402
from suptracker import nomenclatures as NM  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
# the owner's homonym corrections, copied at import: a mutant that empties the module's list must not empty this one
OWNER_OVERRIDES = dict(NM.TITLE_LINK_OVERRIDES)
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def rfold(s) -> str:
    t = "".join("'" if unicodedata.category(ch) in ("Pi", "Pf") or ch in "'`´" else ch for ch in str(s or ""))
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch)).lower()
    return " ".join(t.encode("ascii", "ignore").decode().split())


def rstatus(q: int) -> tuple:
    """Independent reading of the Dares qualification classes onto the Insee G44 status columns."""
    kind = {9: "ingcad", 7: "tecam", 8: "tecam", 4: "inde", 0: "nr"}.get(q, "ouvemp")
    return {"ingcad": ("ingcad_supv", "ingcad_nsupv"), "tecam": ("tecam_supv", "tecam_nsupv"), "ouvemp": ("ouvemp_supv", "ouvemp_nsupv"),
            "nr": ("nr_supv", "nr_nsupv"), "inde": ("inde_0_9", "inde_sup10", "inde_nr")}[kind]


def xls_fap2009(path: Path) -> set:
    import xlrd
    sh = xlrd.open_workbook(str(path)).sheet_by_name("Table")
    out, fam = set(), None
    for i in range(sh.nrows):
        a, _, _, _, rome, qual = (str(x).strip() for x in sh.row_values(i)[:6])
        if len(a) == 5 and a[:1].isalpha() and a[1].isdigit():
            fam = a
        elif len(a) in (1, 3):
            fam = None
        if fam and re.fullmatch(r"[A-N]\d{4}", rome):
            qs = range(10) if not qual else [int(ch) for ch in qual[2:]]
            out |= {(rome, q, fam) for q in qs}
    return out


class Ctx:
    def __init__(self, db: Path, real: bool, sources: dict | None = None):
        self.db, self.real = db, real
        self.src = NM.find_sources() if sources is None else sources
        self.con = duckdb.connect(str(db), read_only=True)
        S = self.src
        self.rome21 = pd.read_csv(S["rome_fap2021"], sep=";", encoding="cp1252", dtype=str)
        self.titles = pd.read_csv(S["libelles"], sep=";", encoding="cp1252", dtype=str)
        self.g44 = pd.read_csv(S["g44"], dtype=str)
        self.isco_lab = pd.read_excel(S["isco_labels"], sheet_name="Nomenclature_ISCO", dtype=str)
        self.isco4 = set(self.isco_lab.iloc[:, 0].str.zfill(4))
        self._derived = None

    def table(self, sql):
        return {tuple(r) for r in self.con.execute(sql).fetchall()}

    def derived(self):
        """(rome, qualif, isco, precision, g44 id) re-derived with pandas."""
        if self._derived is None:
            t = self.titles.dropna(subset=["Rome"]).copy()
            t = t[t.Rome.str.fullmatch(r"[A-N]\d{4}")]
            t["key"], t["q"] = t.Libelle_PCS2020.map(rfold), t.Qualif.astype(int)
            cols = sorted({c for q in range(10) for c in rstatus(q)})
            g = self.g44.melt(id_vars=["id", "libm", "libf"], value_vars=cols, var_name="col", value_name="isco")
            g = g[g.isco.fillna("").str.fullmatch(r"\d{4}")]
            keys = pd.concat([g.assign(key=g.libm.map(rfold)), g.assign(key=g.libf.map(rfold))]).drop_duplicates(["id", "col", "key"])
            m = t.merge(keys, on="key")
            m = m[[c in rstatus(q) for c, q in zip(m.col, m.q)]]
            prec = m.isco.map(lambda c: 4 if c in self.isco4 else len(c.rstrip("0")) or 1)
            self._derived = set(zip(m.Rome, m.q, m.isco, prec, m.id.astype(int)))
            self.title_match = t.key.isin(set(keys.key)).mean()
        return self._derived


# ---------------------------------------------------------------- checks
@check("N1 stored tables = the raw official files re-read independently; FAP-2009 SAS program = Dares xls")
def n1(c: Ctx):
    r = c.rome21
    exp21 = set(zip(r.ROME, r.Qualif.astype(int), r.FAP341))
    got21 = c.table("SELECT rome, qualif, fap341 FROM core.nomen_rome_fap2021")
    nom = pd.read_csv(c.src["fap2021"], sep=";", encoding="utf-8-sig", dtype=str)
    expn = {tuple(x) for x in nom.iloc[:, [6, 7, 4, 5, 2, 3, 0, 1]].itertuples(index=False)}
    gotn = c.table("SELECT * FROM core.nomen_fap2021")
    exp09 = xls_fap2009(c.src["fap2009_xls"])
    got09 = c.table("SELECT rome, qualif, fap2009 FROM core.nomen_rome_fap2009")
    expi = {(str(a).zfill(4), str(b).strip()) for a, b in c.isco_lab.iloc[:, :2].itertuples(index=False)}
    goti = c.table("SELECT isco, libelle FROM core.nomen_isco")
    titles = dict(zip(r.ROME, r.Intitule_ROME))
    gott = dict(c.table("SELECT rome, intitule FROM core.nomen_rome"))
    used = {f for _, _, f in got21} - {x[0] for x in gotn}
    # no C1 control character anywhere (a Windows-1252 file read as Latin-1 turns ’ and œ into them)
    ctrl = [t for (t,) in c.con.execute("SELECT intitule FROM core.nomen_rome UNION ALL SELECT lib341 FROM core.nomen_fap2021").fetchall()
            if t and re.search(r"[\x80-\x9f]", t)]
    # witness: the Dares files are Windows-1252 (byte 0x92 = ’); no title in use carries one today, so a Latin-1 reading
    # would go unseen in the data: a two-line file in that encoding must come back with its apostrophe
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "w.csv"
        w.write_bytes(b"ROME;Intitule_ROME;Qualif;FAP341;Intitule_FAP341\r\nA1101;Conduite d\x92engins \x9cnologiques;0;A0X43;x\r\n")
        enc_ok = NM.read_rome_fap2021(w)[1].get("A1101") == "Conduite d’engins œnologiques"
    ok = (exp21 == got21 and expn == gotn and exp09 == got09 and expi == goti and titles == gott and not used and len(got09) > 5000
          and not ctrl and enc_ok)
    return ok, (f"ROME→FAP-2021 {len(got21)} rows equal {exp21 == got21}; FAP-2021 nomenclature {len(gotn)} equal {expn == gotn}; "
                f"FAP-2009 {len(got09)} rows, SAS = xls {exp09 == got09} (diff {sorted(exp09 ^ got09)[:3]}); ISCO labels {len(goti)} equal "
                f"{expi == goti}; ROME titles equal {titles == gott}; families without a name {sorted(used)[:3]}; control characters {ctrl[:2]}; "
                f"Windows-1252 witness {enc_ok}")


@check("N2 ROME → ISCO re-derived independently (titles × Insee G44 by status): same rows, precision, ≥ 95 % titles found")
def n2(c: Ctx):
    exp = c.derived()
    got = c.table("SELECT rome, qualif, isco, precision, intitule_id FROM core.nomen_rome_isco")
    bad_prec = [x for x in got if (x[3] == 4) != (x[2] in c.isco4)]
    # witnesses for the join key: accents, case, spaces and apostrophe forms must not split a title (real titles are
    # spelled alike in both files today, so a weaker fold would go unseen in the data)
    wit = ["  Développeuse   d’applications ", "CHARGÉE D'ACCUEIL", "Chargée d‘accueil", "Agent de sécurité\u00a0incendie"]
    bad_fold = [w for w in wit if NM.fold(w) != rfold(w)]
    ok = exp == got and c.title_match >= 0.95 and not bad_prec and len(got) > 0 and not bad_fold
    return ok, (f"{len(got)} rows, equal {exp == got} (only stored {sorted(got - exp)[:2]}, only re-derived {sorted(exp - got)[:2]}); "
                f"titles found in G44 {c.title_match:.1%}; precision errors {bad_prec[:2]}; fold witnesses failing {bad_fold}")


@check("N3 cross-check: ISCO via PCS (Dares + Insee matrices) meets the title path for ≥ 95 % of ROME codes; FAP agreement ≥ 99 %")
def n3(c: Ctx):
    S = c.src
    pf = pd.read_excel(S["rome_qualif_xlsx"].parent / "Dares_Table_passage_PCS2020_FAP2021.xlsx", sheet_name="PCS2020_FAP341", dtype={"PCS2020": str})
    mi = pd.read_csv(S["g44"].parent / "Matrice_PCS_ISCO_pour_programmes.csv", sep=";", dtype=str)
    rf = c.rome21.rename(columns={"ROME": "rome", "FAP341": "fap"})
    m = rf.merge(pf[pf.proba >= 0.05], left_on="fap", right_on="FAP341").merge(mi, left_on="PCS2020", right_on="PCS4")
    viapcs = m.groupby("rome").ISCO4.agg(set).to_dict()
    titles = {}
    for rome, _, isco, prec, _ in c.table("SELECT * FROM core.nomen_rome_isco"):
        if prec == 4:
            titles.setdefault(rome, set()).add(isco)
    common = [r for r in titles if r in viapcs]
    apart = sorted(r for r in common if not titles[r] & viapcs[r])
    rate = 1 - len(apart) / len(common) if common else 0
    t = c.titles.dropna(subset=["Rome"]).merge(c.rome21, left_on=["Rome", "Qualif"], right_on=["ROME", "Qualif"], suffixes=("_t", "_r"))
    agree = (t.FAP341_t == t.FAP341_r).mean()
    ok = rate >= 0.95 and agree >= 0.99 and len(common) > 400
    return ok, f"{len(common)} ROME codes on both paths, ISCO sets meet for {rate:.1%} (apart: {apart[:5]}); family agreement {agree:.2%}"


def ref_romes(c: Ctx, romes):
    """Expected serving answer for a list of ROME codes, from the stored tables with independent SQL."""
    out = []
    for rome in [r for r in dict.fromkeys(romes) if re.fullmatch(r"[A-N]\d{4}", r or "")]:
        f21 = c.con.execute("SELECT fap341, list(qualif ORDER BY qualif) FROM core.nomen_rome_fap2021 WHERE rome = ? GROUP BY 1", [rome]).fetchall()
        isc = c.con.execute("""SELECT isco, count(DISTINCT intitule_id), min(precision) FROM core.nomen_rome_isco WHERE rome = ? GROUP BY 1""",
                            [rome]).fetchall()
        out.append((rome, {f: q for f, q in f21}, {i: (n, p) for i, n, p in isc}))
    return out


@check("N4 serving: qualification classes covered once, FAP-2009 unnamed classes, distinct title counts, partial codes, job pages")
def n4(c: Ctx):
    bad = []
    jobs = c.con.execute("SELECT met_id, list(rome ORDER BY rome) FROM core.onisep_metier_rome GROUP BY 1 ORDER BY 1").fetchall()
    sample = jobs if not c.real else jobs[:: max(1, len(jobs) // 150)]
    for mid, romes in sample:
        d = MT.detail(c.con, mid)
        onisep = [{k: v for k, v in x.items() if k != "origine"} for x in (d or {}).get("codes", []) if x.get("origine") == "onisep"]
        if d is None or onisep != NM.for_romes(c.con, d["romes"]):
            bad.append(f"{mid}: page codes ≠ its ROME codes")
            continue
        for got, (rome, f21, isc) in zip([x for x in onisep if x["connu"]], [x for x in ref_romes(c, romes) if x[1]]):
            qs = sorted(q for e in got["fap2021"] for q in e["qualifications"]["codes"])
            if qs != list(range(10)) or {e["code"]: e["qualifications"]["codes"] for e in got["fap2021"]} != f21:
                bad.append(f"{mid} {rome}: FAP-2021 classes {qs}")
            if any(e["qualifications"]["libelles"] is not None for e in got["fap2009"]):
                bad.append(f"{mid} {rome}: FAP-2009 classes named with FAP-2021 names")
            if any(e["qualifications"]["toutes"] != (len(e["qualifications"]["codes"]) == 10) for e in got["fap2021"] + got["fap2009"] + got["isco"]):
                bad.append(f"{mid} {rome}: 'toutes qualifications' wrong")
            if {e["code"]: (e["n_intitules"], e["precision"]) for e in got["isco"]} != isc:
                bad.append(f"{mid} {rome}: ISCO counts")
            if any((e["libelle"] is None) != (e["precision"] < 4) for e in got["isco"]):
                bad.append(f"{mid} {rome}: partial code labelled or full code unlabelled")
    odd = NM.for_romes(c.con, ["A15", "Z9999", "", None, "<script>", "M1805", "M1805"])
    odd_ok = len(odd) == 1 and odd[0]["rome"] == "M1805" and odd[0]["connu"]
    unknown = NM.for_romes(c.con, ["A9999"])
    unk_ok = unknown and not unknown[0]["connu"] and not unknown[0]["fap2021"] and not unknown[0]["isco"]
    from fastapi.testclient import TestClient

    import os
    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(c.db)
    api._con.cache_clear()
    try:
        r = TestClient(api.app).get(f"/api/metier/{sample[0][0]}")
        api_ok = r.status_code == 200 and "codes" in r.json() and "s-maxage" in r.headers.get("cache-control", "")
    finally:
        os.environ.pop("SUPTRACKER_DB", None) if old is None else os.environ.__setitem__("SUPTRACKER_DB", old)
        api._con.cache_clear()
    ok = not bad and odd_ok and bool(unk_ok) and api_ok and len(sample) > 0
    return ok, f"{len(sample)} jobs checked, {len(bad)} wrong {bad[:3]}; odd codes handled {odd_ok}; unknown code {bool(unk_ok)}; API {api_ok}"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 13: les codes officiels du métier")
    return js[i: js.index("\n// ---- ", i + 1)]


HOSTILE = [{"rome": "M1805", "intitule": "<script>alert(1)</script>", "connu": True,
            "fap2021": [{"code": "<b>X</b>", "libelle": "<img src=x onerror=alert(1)>", "fap86": "<i>", "libelle86": "<u>",
                         "qualifications": {"toutes": False, "codes": [7, 9], "libelles": ["<em>Tech</em>", "Cadres"]}}],
            "fap2009": [{"code": "M1Z80", "libelle": "<svg>", "fap87": "M1Z", "libelle87": "<marquee>",
                         "qualifications": {"toutes": False, "codes": [4], "libelles": None}}],
            "isco": [{"code": "2512", "libelle": "<iframe>", "precision": 4, "n_intitules": 20,
                      "qualifications": {"toutes": True, "codes": list(range(10)), "libelles": ["x"] * 10}},
                     {"code": "2100", "libelle": None, "precision": 2, "n_intitules": 5,
                      "qualifications": {"toutes": True, "codes": list(range(10)), "libelles": ["x"] * 10}}]},
           {"rome": "A9999", "intitule": None, "connu": False, "fap2021": [], "fap2009": [], "isco": []},
           {"rome": "K1405", "intitule": "x", "connu": True, "origine": "analogie", "motif": "<img src=x onerror=alert(2)> voisin",
            "controle": {"n_metiers": 0, "n_ok": 0}, "fap2021": [], "fap2009": [], "isco": []},
           {"rome": "K1601", "intitule": "<script>x</script>", "connu": True, "origine": "intitule_dares", "controle": {"n_metiers": 420, "n_ok": 356},
            "fap2021": [], "fap2009": [], "isco": []}]


def render(js: str, payload) -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    prog = helpers + "\n" + block(js) + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(P.map(codesCard)));"
    r = subprocess.run([node, "-e", prog], input=json.dumps([HOSTILE, [], None]), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return "__error__" + r.stderr[-300:]
    return r.stdout


def ui(js: str) -> tuple[bool, str]:
    b = block(js)
    words = all(w in b for w in ("pas des chiffres sur l'emploi", "n'est pas une part des emplois", "Codes partiels", "Licence Ouverte",
                                 "selon la qualification du poste", "toutes qualifications", "pas de code ROME"))
    out = render(js, HOSTILE)
    if out is None:
        rendered, detail = True, "node not installed"
    elif out.startswith("__error__"):
        rendered, detail = False, out
    else:
        html, empty, none = json.loads(out)
        leaks = re.findall(r"<(?:script|img|svg|iframe|marquee|b|i|u|em)\b", html)
        rendered = (not leaks and "%" not in html and "21xx" in html and "selon la qualification du poste" in html
                    and "moins sûr qu'un code donné par l'Onisep" in html and "retrouve un bon code pour 356" in html
                    and "par analogie avec un métier voisin" in html and "voisin" in html
                    and "pas dans les tables de passage" in html and "pas de code ROME" in empty and none == "")
        detail = (f"raw tags {leaks[:3]}; percent sign {'%' in html}; partial code shown as 21xx {'21xx' in html}; empty list {('pas de code ROME' in empty)}; "
                  f"name-based code flagged with its check {'moins sûr' in html and '356' in html}")
    wired = "${codesCard(d.codes)}" in js
    return words and rendered and wired, f"wording {words}; {detail}; wired {wired}"


@check("N5 page: codesCard run with Node on hostile data: escaped, no percentage, wording, partial codes, wiring")
def n5(c: Ctx):
    return ui(APP_JS.read_text())


@check("N6 upkeep: register, methodology, feature, pipeline requirements, empty build, warehouse size")
def n6(c: Ctx):
    import fnmatch

    from suptracker import sources as SRC
    from suptracker.api import FEATURES, METHODOLOGY
    online = [s for s in SRC.SOURCES if s["key"] in ("dares_fap", "insee_pcs_isco", "rome_arbo")]
    files = list(NM.FILES.values()) + ([c.src["rome_arbo"].name] if "rome_arbo" in c.src else [])
    reg = len(online) == 3 and all(s["status"] == "en_ligne" for s in online) and all(
        any(fnmatch.fnmatch(f, g) for s in online for g in SRC.globs(s)) for f in files)
    meth = "referentiel_metiers" in FEATURES and "pas une part des emplois" in METHODOLOGY.get("referentiel_metiers", "")
    req = "xlrd" in (ROOT / "requirements-pipeline.txt").read_text()
    e = duckdb.connect(":memory:")
    e.execute("CREATE SCHEMA core")
    res = NM.build(e, {})
    empty = res["rome"] == 0 and NM.for_romes(e, ["M1805"])[0]["connu"] is False
    size = c.db.stat().st_size / 1e6
    ok = reg and meth and req and empty and (size < 95 or not c.real)
    return ok, f"files registered and online {reg}; methodology and feature {meth}; xlrd in pipeline requirements {req}; empty build safe {empty}; warehouse {size:.1f} MB"


def ref_title_links(c: Ctx):
    """Independent re-derivation of the name-based links (pandas / openpyxl, the red team's own fold)."""
    usable = {r for (r,) in c.con.execute("SELECT rome FROM core.nomen_rome").fetchall()}
    jobs, own = {}, {}
    for mid, lab in c.con.execute("SELECT met_id, nom FROM core.onisep_metier UNION SELECT met_id, libelle FROM core.onisep_metier_libelle").fetchall():
        jobs.setdefault(mid, set()).add(rfold(lab))
    for mid, rome in c.con.execute("SELECT met_id, rome FROM core.onisep_metier_rome").fetchall():
        own.setdefault(mid, set()).add(rome)
    t = c.titles.dropna(subset=["Rome"])
    dares = {}
    for title, rome in zip(t.Libelle_PCS2020, t.Rome):
        dares.setdefault(rfold(title), set()).add(rome)
    app = {}
    if "rome_arbo" in c.src:
        df = pd.read_excel(c.src["rome_arbo"], sheet_name=1, header=None, dtype=str).fillna("")
        for a, b, cc, lab, ogr in df.iloc[1:, :5].itertuples(index=False):
            rome = f"{a.strip()}{b.strip()}{cc.strip()}"
            if ogr.strip() and rome in usable:
                for form in [lab] + lab.split(" / "):
                    if rfold(form):
                        app.setdefault(rfold(form), set()).add(rome)
    rows, check = set(), []
    for method, idx in (("intitule_dares", dares), ("appellation_rome", app)):
        hits = {m: set().union(*[idx.get(x, set()) for x in labs]) for m, labs in jobs.items()}
        mine = {m: own.get(m, set()) & usable for m in jobs}
        n = sum(1 for m in jobs if mine[m] and hits[m])
        check.append((method, n, sum(1 for m in jobs if mine[m] and hits[m] & mine[m])))
        for m in jobs:
            if not mine[m] and hits[m] and m not in OWNER_OVERRIDES and not any(r[0] == m for r in rows):
                rows |= {(m, r, method, None) for r in hits[m]}
    for m, (rome, why) in OWNER_OVERRIDES.items():      # the owner's list is an input, applied as written
        if m in jobs and not (own.get(m, set()) & usable) and rome in usable:
            rows.add((m, rome, "analogie", why))
    if not app:
        check = check[:1]
    return rows, check, usable, own


@check("N8 jobs without an Onisep code, linked by their name: re-derived, Onisep code always wins, method checked and shown")
def n8(c: Ctx):
    exp_rows, exp_check, usable, own = ref_title_links(c)
    got_rows = c.table("SELECT met_id, rome, methode, motif FROM core.nomen_metier_rome_titre")
    # every owner override is applied as written: a code replaces the name link, None leaves the job unlinked
    over_bad = [m for m, (rome, _) in OWNER_OVERRIDES.items()
                if c.real and {(r, x) for mm, r, x, _ in got_rows if mm == m} != ({(rome, "analogie")} if rome else set())]
    got_check = sorted(c.table("SELECT * FROM core.nomen_titre_controle"))
    override = sorted({r[0] for r in got_rows if own.get(r[0], set()) & usable})
    unusable = sorted({r[1] for r in got_rows if r[1] not in usable})
    both = sorted(m for m in {r[0] for r in got_rows} if len({r[2] for r in got_rows if r[0] == m}) > 1)
    bad = []
    for mid in sorted({r[0] for r in got_rows})[:60]:
        d = MT.detail(c.con, mid)
        flagged = [x for x in d["codes"] if x["origine"] != "onisep"]
        k = dict((m, (n, ok)) for m, n, ok in got_check)
        if {x["rome"] for x in flagged} != {r[1] for r in got_rows if r[0] == mid} or any(
                (x["controle"]["n_metiers"], x["controle"]["n_ok"]) != k.get(x["origine"], (0, 0))
                or (x["origine"] == "analogie") != bool(x.get("motif")) for x in flagged):
            bad.append(mid)
    linked = c.con.execute("SELECT DISTINCT met_id FROM core.onisep_metier_rome WHERE rome IN (SELECT rome FROM core.nomen_rome) LIMIT 40").fetchall()
    bad += [m for (m,) in linked if any(x["origine"] != "onisep" for x in MT.detail(c.con, m)["codes"])]
    sane = all(0 <= ok <= n for _, n, ok in got_check)
    ok = (got_rows == exp_rows and got_check == sorted(exp_check) and not override and not unusable and not both and not bad and sane
          and not over_bad
          and (len(got_rows) > 0 or not c.real))
    return ok, (f"owner overrides not applied {over_bad}; {len({r[0] for r in got_rows})} jobs linked by name, equal to the re-derivation {got_rows == exp_rows} "
                f"(only stored {sorted(got_rows - exp_rows)[:2]}, only re-derived {sorted(exp_rows - got_rows)[:2]}); checks {got_check} "
                f"= {sorted(exp_check)}; over an Onisep code {override[:3]}; codes outside the Dares tables {unusable[:3]}; "
                f"jobs with both methods {both[:3]}; pages wrong {bad[:3]}")


UI_MUTANTS = [
    ("unescaped FAP label", "${esc(f.libelle || \"\")}${sub(f)}", "${f.libelle || \"\"}${sub(f)}"),
    ("unescaped ISCO label", "<td>${esc(i.libelle || \"\")}<div", "<td>${i.libelle || \"\"}<div"),
    ("unescaped qualification", "`pour : ${q.libelles.map(esc).join(\", \")}`", "`pour : ${q.libelles.join(\", \")}`"),
    ("title count shown as a share", "<td class=\"num\">${fmt(i.n_intitules)}</td>", "<td class=\"num\">${fmt(i.n_intitules)} %</td>"),
    ("'not a share of jobs' dropped", "Le nombre d'intitulés n'est pas une part des emplois.", ""),
    ("FAP-2009 classes named with FAP-2021 names", "if (!q.libelles) return \"selon la qualification du poste\";", "if (!q.libelles) return \"\";"),
    ("partial code printed as a full code", "${esc(i.code.slice(0, i.precision))}${\"x\".repeat(4 - i.precision)}", "${esc(i.code)}"),
    ("card not wired", "${codesCard(d.codes)}", ""),
    ("analogy reason unescaped", "${esc(c.motif || \"\")}", "${c.motif || \"\"}"),
    ("name-based code not flagged", ": c.origine && c.origine !== \"onisep\" ?", ": false ?"),
]


@check("N7 mutation test: reader, join, status, count, label, serving and page bugs are each caught")
def n7(c: Ctx):
    import duckdb as ddb
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 13: les codes officiels du métier")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        if name == "card not wired":
            mut = js.replace(old, new, 1)
        else:
            mut = js[:i] + js[i:j].replace(old, new, 1) + js[j:]
        if old not in js or ui(mut)[0]:
            missed.append(name)

    def rebuilt(apply):
        """Build the reference with a seeded bug into a copy of the warehouse, then run the data checks on it."""
        saved = {k: getattr(NM, k) for k in ("TITLE_LINK_OVERRIDES", "title_links", "read_rome_appellations", "for_metier", "ENCODING", "QUALIF_STATUS", "fold", "read_rome_fap2009", "precision", "for_romes", "_qualifs", "read_fap2021")}
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"nomen_mutant_{c.db.stem}.duckdb"   # never inside the repository
        try:
            apply()
            shutil.copy(c.db, tmp)
            con = ddb.connect(str(tmp))
            NM.build(con, c.src)
            con.close()
            m = Ctx.__new__(Ctx)
            m.__dict__.update({k: v for k, v in c.__dict__.items() if k != "con"})
            m.db, m.con = tmp, ddb.connect(str(tmp), read_only=True)
            caught = any(not fn(m)[0] for fn in (n1, n2, n4, n8))
            m.con.close()
            return caught
        except Exception:  # noqa: BLE001
            return True
        finally:
            for k, v in saved.items():
                setattr(NM, k, v)
            tmp.unlink(missing_ok=True)

    orig_for, orig_q, orig_sas = NM.for_romes, NM._qualifs, NM.read_rome_fap2009

    def counts_not_distinct(con, romes):
        out = orig_for(con, romes)
        for o in out:
            for e in o["isco"]:
                e["n_intitules"] *= 2              # masculine and feminine forms counted twice
        return out

    def no_raq(path):
        return [r for r in orig_sas(path) if r[0] not in ("A1301", "A1204", "N3102")]

    orig_tl, orig_app, orig_fm = NM.title_links, NM.read_rome_appellations, NM.for_metier

    def overrides(jobs, own, usable, dares, app):
        return orig_tl(jobs, {}, usable, dares, app)[0], orig_tl(jobs, own, usable, dares, app)[1]

    def merged(jobs, own, usable, dares, app):
        rows, chk = orig_tl(jobs, own, usable, dares, {k: v | app.get(k, set()) for k, v in dares.items()} if False else app)
        extra, _ = orig_tl(jobs, own, usable, dares, {})
        return sorted(set(rows) | {(m, r, "appellation_rome", None) for m, r, *_ in extra}), chk

    def hardcoded(con, mid, romes):
        out = orig_fm(con, mid, romes)
        for x in out:
            if x.get("controle"):
                x["controle"] = {"n_metiers": 100, "n_ok": 100}
        return out

    data_mutants = [
        ("name link applied over an Onisep code", lambda: setattr(NM, "title_links", overrides)),
        ("owner's homonym corrections ignored", lambda: setattr(NM, "TITLE_LINK_OVERRIDES", {})),
        ("ROME 4.0 codes without a Dares link kept", lambda: setattr(NM, "read_rome_appellations", lambda p, usable: orig_app(p, {
            f"{a}{b:02d}{c:02d}" for a in "ABCDEFGHIJKLMN" for b in range(10, 50) for c in range(1, 50)}))),
        ("both methods applied to one job", lambda: setattr(NM, "title_links", merged)),
        ("method check hard-coded on the page", lambda: setattr(NM, "for_metier", hardcoded)),
        ("cadre status read for every qualification", lambda: setattr(NM, "QUALIF_STATUS", {q: ("ingcad_supv", "ingcad_nsupv") for q in range(10)})),
        ("titles joined without folding accents", lambda: setattr(NM, "fold", lambda s: str(s or "").strip())),
        ("curly apostrophe dropped before folding", lambda: setattr(NM, "fold", lambda s: " ".join(unicodedata.normalize("NFKD", str(s or ""))
                                                                                      .encode("ascii", "ignore").decode().lower().split()))),
        ("ROME + qualification FAP-2009 format ignored", lambda: setattr(NM, "read_rome_fap2009", no_raq)),
        ("Dares files read as Latin-1", lambda: setattr(NM, "ENCODING", "latin-1")),
        ("every ISCO code taken as a full unit group", lambda: setattr(NM, "precision", lambda code, isco4: 4)),
        ("title counts not distinct", lambda: setattr(NM, "for_romes", counts_not_distinct)),
        ("'toutes qualifications' from 9 classes", lambda: setattr(NM, "_qualifs", lambda qs, lab: {**orig_q(qs, lab), "toutes": len(qs) >= 9})),
        ("FAP-2021 families with a lowercase suffix dropped", lambda: setattr(NM, "read_fap2021", lambda p, f=NM.read_fap2021: [r for r in f(p) if not r[0][-1].islower()])),
    ]
    for name, apply in data_mutants:
        if not rebuilt(apply):
            missed.append(name)
    n = len(UI_MUTANTS) + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, sources: dict | None = None) -> list[dict]:
    c = Ctx(db, real, sources)
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
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
