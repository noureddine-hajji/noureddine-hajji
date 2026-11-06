"""Sprint 13: the job reference. Which official families and codes does a job (its ROME codes) belong to?

ROME (France Travail) -> FAP-2021 and FAP-2009 (Dares families) -> ISCO-08 (international classification), only
from the official tables the owner committed under data/sources/:

* ROME x qualification -> FAP-2021 (FAP-341): Dares "Table_passage_ROME_Qualif_to_FAP2021", one row per ROME code
  and qualification class 0-9 (the FAP-2021 classes: 4 = independent workers). For 282 of the 532 ROME codes the
  family depends on the qualification: every family is kept, none is picked for the student.
* FAP-2021 levels (341 -> 228 -> 86 -> 22): Dares nomenclature.
* ROME x qualification -> FAP-2009: the Dares SAS program `passage_fap2009_romev3.txt` ($FAP9RSQ: the ROME code
  alone; $FAP9RAQ: ROME code and qualification). Its qualification is France Travail's (4 = highly qualified
  worker), NOT the FAP-2021 one: the two are never mixed. FAP-2009 is the family of the "Métiers 2030" projections
  (sprint 14); the Dares xls of the same table is the red team's independent re-derivation.
* ROME x qualification -> ISCO-08: the Dares table of PCS 2020 job TITLES (each title, gender and qualification ->
  FAP and ROME) joined by title to the Insee ISCO codification of the same titles (G44). G44 gives the ISCO code
  per employment status; the status column follows the FAP-2021 qualification class (QUALIF_STATUS). A ROME code
  thus has several possible ISCO codes; each comes with the number of job titles behind it. That count is NOT a
  share of jobs (no weight is published along this path): it is shown as a count, never as a percentage.
  Some titles only allow a partial ISCO code (2100 = sub-major group 21): precision < 4, flagged, no label invented.

Nothing here is a figure about the job market: these are codes, so the page says where each link comes from
instead of grading a population. Sprints 14 and 15 read their figures through these tables.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

from . import config

QUALIF_COUNT = 10
# FAP-2021 qualification class -> the Insee G44 employment-status columns that apply to it
QUALIF_STATUS = {
    0: ("nr_supv", "nr_nsupv"),                       # non précisé
    1: ("ouvemp_supv", "ouvemp_nsupv"),               # manœuvres
    2: ("ouvemp_supv", "ouvemp_nsupv"),               # ouvriers non qualifiés
    3: ("ouvemp_supv", "ouvemp_nsupv"),               # ouvriers qualifiés
    4: ("inde_0_9", "inde_sup10", "inde_nr"),         # indépendants
    5: ("ouvemp_supv", "ouvemp_nsupv"),               # employés non qualifiés
    6: ("ouvemp_supv", "ouvemp_nsupv"),               # employés qualifiés
    7: ("tecam_supv", "tecam_nsupv"),                 # techniciens
    8: ("tecam_supv", "tecam_nsupv"),                 # agents de maîtrise
    9: ("ingcad_supv", "ingcad_nsupv"),               # ingénieurs et cadres
}
G44_STATUS = sorted({c for cs in QUALIF_STATUS.values() for c in cs})
ROME_CODE = re.compile(r"^[A-N]\d{4}$")
ISCO_CODE = re.compile(r"^\d{4}$")
# The Dares CSV files are Windows-1252, not Latin-1: read as Latin-1, ’ and œ become invisible control characters
ENCODING = "cp1252"
FAP2021_CODE = re.compile(r"^[A-Z][A-Z0-9][A-Z]\d{2}[a-z]?$")

FILES = {   # role -> file name in data/sources (registered in sources.py: dares_fap, insee_pcs_isco)
    "rome_fap2021": "Dares_Table_passage_ROME_Qualif_to_FAP2021_pour_programme.csv",
    "fap2021": "dares_nomenclature_fap2021.csv",
    "rome_fap2009": "passage_fap2009_romev3.txt",
    "fap2009_xls": "Table de correspondance PCS-2003, Rome-V3 vers Fap-2009.xls",
    "rome_qualif_xlsx": "Dares_Table_passage_ROME_Qualif_to_FAP2021_pour_visualisation.xlsx",
    "libelles": "Dares_Table_passage_LibellesPCS_Qualif_to_FAP2021_pour_programme_v20260327.csv",
    "g44": "G44_Matrice_codification_ISCO_collecte_2026.csv",
    "isco_labels": "Matrice_PCS_ISCO_pour_visualisation.xlsx",
}


def fold(s) -> str:
    """Accent-, case- and space-insensitive form of a job title (the join key between Dares and Insee titles)."""
    t = re.sub(r"[’‘`´]", "'", str(s or ""))        # before the ASCII pass, which would drop the curly apostrophe
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def _csv(path: Path, encoding: str, sep: str = ";") -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding=encoding)), delimiter=sep))


# ------------------------------------------------------------------------- readers
def read_rome_fap2021(path: Path) -> tuple[list[tuple], dict]:
    rows, titles = [], {}
    for r in _csv(path, ENCODING):
        rome = r["ROME"].strip()
        if ROME_CODE.match(rome):
            rows.append((rome, int(r["Qualif"]), r["FAP341"].strip()))
            titles.setdefault(rome, r["Intitule_ROME"].strip())
    return rows, titles


def read_fap2021(path: Path) -> list[tuple]:
    out = []
    for r in csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"):
        if len(r) >= 8 and FAP2021_CODE.match(r[6].strip()):
            c22, l22, c86, l86, c228, l228, c341, l341 = (x.strip() for x in r[:8])
            out.append((c341, l341, c228, l228, c86, l86, c22, l22))
    return out


_SAS_LINE = re.compile(r'^\s*((?:"[^"]+"\s*,\s*)*"[^"]+")\s*=\s*"([^"]+)"', re.M)


def read_rome_fap2009(path: Path) -> list[tuple]:
    """(rome, qualif, fap2009) for every qualification 0-9: the code-only format applies to every qualification;
    the ROME+qualification format fills the codes the first one sends to 'ZZZZZ' (the program's own order)."""
    text = path.read_text(encoding="latin-1")
    parts = re.split(r"value\s+\$(FAP9RSQ|FAP9RAQ)", text)
    fmt = {parts[i]: parts[i + 1].split("run;")[0] for i in range(1, len(parts), 2)}
    rsq, raq = {}, {}
    for name, target in (("FAP9RSQ", rsq), ("FAP9RAQ", raq)):
        for keys, fap in _SAS_LINE.findall(fmt.get(name, "")):
            for k in re.findall(r'"([^"]+)"', keys):
                target[k] = fap
    out = []
    for rome in sorted({k for k in rsq if ROME_CODE.match(k)} | {k[:5] for k in raq if ROME_CODE.match(k[:5])}):
        for q in range(QUALIF_COUNT):
            fap = rsq.get(rome) or raq.get(f"{rome}{q}")
            if fap and fap != "ZZZZZ":
                out.append((rome, q, fap))
    return out


def read_fap2009_labels(path: Path) -> list[tuple]:
    """(code, label) of the FAP-2009 families (5 characters) and of the 87 groups (3 characters), from the Dares xls."""
    import xlrd
    sh = xlrd.open_workbook(str(path)).sheet_by_name("Table")
    out = {}
    for i in range(sh.nrows):
        code, lab = (str(x).strip() for x in sh.row_values(i)[:2])
        if re.match(r"^[A-Z]\d[A-Z](\d{2})?$", code) and lab:
            out.setdefault(code, lab.rstrip("*").strip())
    return sorted(out.items())


def read_fap2009_xls(path: Path) -> list[tuple]:
    """(rome, qualif, fap2009) from the Dares xls (red team: independent of the SAS program). The family column is
    filled down; an empty qualification cell means every class, 'Q_246' means classes 2, 4 and 6."""
    import xlrd
    sh = xlrd.open_workbook(str(path)).sheet_by_name("Table")
    out, fap = set(), None
    for i in range(sh.nrows):
        r = [str(x).strip() for x in sh.row_values(i)]
        if re.match(r"^[A-Z]\d[A-Z]\d{2}$", r[0]):
            fap = r[0]
        elif re.match(r"^[A-Z]\d[A-Z]$|^[A-Z]$", r[0]):
            fap = None
        if fap and ROME_CODE.match(r[4]):
            qs = range(QUALIF_COUNT) if not r[5] else [int(c) for c in r[5].removeprefix("Q_")]
            out |= {(r[4], q, fap) for q in qs}
    return sorted(out)


def read_isco_labels(path: Path) -> list[tuple]:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True)
    return [(str(c).zfill(4), str(lab).strip()) for c, lab, *_ in wb["Nomenclature_ISCO"].iter_rows(min_row=2, values_only=True)
            if c is not None and lab]


def read_g44(path: Path) -> dict:
    """folded title -> list of {status column: ISCO code} (a title may appear in several G44 rows)."""
    out = {}
    for r in _csv(path, "utf-8", sep=","):
        codes = {c: (r.get(c) or "").strip() for c in G44_STATUS}
        if not any(ISCO_CODE.match(v) for v in codes.values()):
            continue
        for lab in {fold(r["libm"]), fold(r["libf"])}:
            if lab:
                out.setdefault(lab, []).append((r["id"], codes))
    return out


def read_libelles(path: Path) -> list[tuple]:
    """(title, qualif, rome) from the Dares title table (titles without a ROME code are dropped)."""
    out = []
    for r in _csv(path, ENCODING):
        rome = (r.get("Rome") or "").strip()
        if ROME_CODE.match(rome):
            out.append((r["Libelle_PCS2020"].strip(), int(r["Qualif"]), rome))
    return out


def rome_isco(libelles: list[tuple], g44: dict, isco4: set) -> tuple[list[tuple], dict]:
    """(rome, qualif, isco, precision, g44 title id) and coverage counts. The masculine and feminine forms of a title
    are one G44 row (one id); the ISCO code is the one of the status columns of the qualification."""
    out, stats = set(), {"titles": 0, "matched": 0}
    for title, q, rome in libelles:
        stats["titles"] += 1
        hits = g44.get(fold(title))
        if not hits:
            continue
        stats["matched"] += 1
        for gid, codes in hits:
            for col in QUALIF_STATUS[q]:
                isco = codes.get(col, "")
                if ISCO_CODE.match(isco):
                    out.add((rome, q, isco, precision(isco, isco4), int(gid)))
    return sorted(out), stats


def precision(code: str, isco4: set) -> int:
    """4 for an ISCO-08 unit group; otherwise the significant digits of a padded code (2100 -> 2, 2130 -> 3)."""
    return 4 if code in isco4 else max(1, len(code.rstrip("0")))


def qualif_labels(path: Path) -> dict:
    """FAP-2021 qualification classes 0-9 and their names, from the Dares readme."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True)
    out = {}
    for row in wb["Lisez-moi"].iter_rows(values_only=True):
        if row and isinstance(row[0], (int, float)) and len(row) > 1 and row[1]:
            out[int(row[0])] = str(row[1]).strip()
    return out


# ------------------------------------------------------------------------- build
ARBO_GLOB = "*rome_arboprincipale*.xlsx"     # France Travail ROME tree (its name carries the month of release)
METHODS = ("intitule_dares", "appellation_rome")


def find_sources(data_dir: Path | None = None) -> dict:
    d = data_dir or config.DATA_DIR / "sources"
    out = {k: d / f for k, f in FILES.items() if (d / f).exists()}
    arbo = sorted(d.glob(ARBO_GLOB))
    if arbo:
        out["rome_arbo"] = arbo[-1]
    return out


def read_rome_appellations(path: Path, usable: set) -> dict:
    """folded appellation (whole label and each of its masculine / feminine forms) -> ROME codes, kept only for the
    codes the Dares tables know: the tree is ROME 4.0 (1,923 sheets) and its newer codes have no FAP nor ISCO link."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True)
    ws = next(w for w in wb.worksheets if w.title.lower().startswith("arbo"))
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        a, b, c, lab, ogr = ((str(x).strip() if x is not None else "") for x in (list(row) + [None] * 5)[:5])
        rome = f"{a}{b}{c}"
        if ogr and rome in usable:
            for form in [lab, *lab.split(" / ")]:
                if fold(form):
                    out.setdefault(fold(form), set()).add(rome)
    return out


def title_links(jobs: dict, own: dict, usable: set, dares: dict, appellations: dict) -> tuple[list[tuple], list[tuple]]:
    """ROME codes found from a job's NAME for the jobs whose Onisep sheet gives no usable ROME code.

    jobs: met_id -> its labels (name, masculine, feminine, synonyms); own: met_id -> Onisep ROME codes. A label equal
    to a Dares job title gives that title's ROME codes; only when no label does, a label equal to a France Travail
    appellation gives its code. Returns (met_id, rome, method) rows and, per method, its check on the jobs whose
    Onisep code is known: (method, jobs matched, jobs whose matched codes include an Onisep code)."""
    rows, check = [], []
    for method, index in zip(METHODS, (dares, appellations)):
        n = ok = 0
        for mid, labels in jobs.items():
            found = set().union(*[index.get(fold(x), set()) for x in labels]) if labels else set()
            mine = own.get(mid, set()) & usable
            if mine and found:
                n, ok = n + 1, ok + bool(found & mine)
        check.append((method, n, ok))
    for mid, labels in sorted(jobs.items()):
        if own.get(mid, set()) & usable:
            continue                                   # the Onisep code always wins
        for method, index in zip(METHODS, (dares, appellations)):
            found = set().union(*[index.get(fold(x), set()) for x in labels]) if labels else set()
            if found:
                rows += [(mid, r, method) for r in sorted(found)]
                break
    return rows, check


def _put(con, table: str, rows) -> None:
    """Insert through a data frame (executemany takes 26 s for the 57 000 ROME x ISCO rows); empty lists are skipped."""
    rows = list(rows)
    if not rows:
        return
    import pandas as pd
    cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
    con.register("_nomen_frame", pd.DataFrame(rows, columns=cols))
    try:
        con.execute(f"INSERT INTO {table} SELECT * FROM _nomen_frame")
    finally:
        con.unregister("_nomen_frame")


def build(con, sources: dict | None = None) -> dict:
    """core.nomen_* tables; with no sources (or a missing file) the tables exist and stay empty."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("CREATE OR REPLACE TABLE core.nomen_rome (rome VARCHAR, intitule VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.nomen_qualif (qualif INTEGER, libelle VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.nomen_rome_fap2021 (rome VARCHAR, qualif INTEGER, fap341 VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.nomen_fap2021 (fap341 VARCHAR, lib341 VARCHAR, fap228 VARCHAR, lib228 VARCHAR,
        fap86 VARCHAR, lib86 VARCHAR, fap22 VARCHAR, lib22 VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE core.nomen_rome_fap2009 (rome VARCHAR, qualif INTEGER, fap2009 VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.nomen_fap2009 (code VARCHAR, libelle VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.nomen_rome_isco (rome VARCHAR, qualif INTEGER, isco VARCHAR, precision INTEGER,
        intitule_id INTEGER)""")
    con.execute("CREATE OR REPLACE TABLE core.nomen_isco (isco VARCHAR, libelle VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.nomen_metier_rome_titre (met_id VARCHAR, rome VARCHAR, methode VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.nomen_titre_controle (methode VARCHAR, n_metiers INTEGER, n_ok INTEGER)")
    src = find_sources() if sources is None else sources
    need = ("rome_fap2021", "fap2021", "rome_fap2009", "fap2009_xls", "rome_qualif_xlsx", "libelles", "g44", "isco_labels")
    if any(k not in src for k in need):
        return {"rome": 0, "missing": [k for k in need if k not in src]}
    f21, titles = read_rome_fap2021(src["rome_fap2021"])
    _put(con, "core.nomen_rome", sorted(titles.items()))
    _put(con, "core.nomen_qualif", sorted(qualif_labels(src["rome_qualif_xlsx"]).items()))
    _put(con, "core.nomen_rome_fap2021", f21)
    _put(con, "core.nomen_fap2021", read_fap2021(src["fap2021"]))
    _put(con, "core.nomen_rome_fap2009", read_rome_fap2009(src["rome_fap2009"]))
    _put(con, "core.nomen_fap2009", read_fap2009_labels(src["fap2009_xls"]))
    labels = read_isco_labels(src["isco_labels"])
    _put(con, "core.nomen_isco", labels)
    rows, stats = rome_isco(read_libelles(src["libelles"]), read_g44(src["g44"]), {c for c, _ in labels})
    _put(con, "core.nomen_rome_isco", rows)
    links = _build_title_links(con, src, set(titles))
    return {"rome": len(titles), "rome_isco": len(rows), **stats, "metiers_par_intitule": links}


def _build_title_links(con, src: dict, usable: set) -> int:
    """Jobs without a usable Onisep ROME code, linked by their name (needs the Onisep tables, built before)."""
    tabs = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    if not {"onisep_metier", "onisep_metier_libelle", "onisep_metier_rome"} <= tabs:
        return 0
    jobs = {}
    for mid, lab in con.execute("""SELECT met_id, nom FROM core.onisep_metier UNION SELECT met_id, libelle FROM core.onisep_metier_libelle""").fetchall():
        jobs.setdefault(mid, set()).add(lab)
    own = {}
    for mid, rome in con.execute("SELECT met_id, rome FROM core.onisep_metier_rome").fetchall():
        own.setdefault(mid, set()).add(rome)
    dares = {}
    for title, _, rome in read_libelles(src["libelles"]):
        dares.setdefault(fold(title), set()).add(rome)
    appellations = read_rome_appellations(src["rome_arbo"], usable) if "rome_arbo" in src else {}
    rows, check = title_links(jobs, own, usable, dares, appellations)
    _put(con, "core.nomen_metier_rome_titre", rows)
    _put(con, "core.nomen_titre_controle", [c for c in check if c[0] != "appellation_rome" or appellations])
    return len({r[0] for r in rows})


# ------------------------------------------------------------------------- serving
def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                               AND table_name = 'nomen_rome'""").fetchone()[0])


def _qualifs(qs: set, labels: dict | None) -> dict:
    """The qualification classes a link applies to; `labels` None when the classes are not the FAP-2021 ones."""
    qs = sorted(qs)
    return {"toutes": len(qs) == QUALIF_COUNT, "codes": qs,
            "libelles": None if labels is None else [labels.get(q, str(q)) for q in qs]}


def for_metier(con, met_id: str, romes: list[str]) -> list[dict]:
    """The codes of a job: its Onisep ROME codes; when none is usable, the codes found from its name, each flagged
    with the method and that method's check on the jobs whose Onisep code is known (counts, never a probability)."""
    codes = [dict(c, origine="onisep") for c in for_romes(con, romes)]
    if any(c["connu"] for c in codes) or not _has(con):
        return codes
    try:
        links = con.execute("SELECT rome, methode FROM core.nomen_metier_rome_titre WHERE met_id = ? ORDER BY rome", [met_id]).fetchall()
        check = {m: (n, ok) for m, n, ok in con.execute("SELECT * FROM core.nomen_titre_controle").fetchall()}
    except Exception:  # noqa: BLE001 - a warehouse built before the title links
        return codes
    how = dict(links)
    for c in for_romes(con, [r for r, _ in links]):
        n, ok = check.get(how[c["rome"]], (0, 0))
        codes.append(dict(c, origine=how[c["rome"]], controle={"n_metiers": n, "n_ok": ok}))
    return codes


def for_romes(con, romes: list[str]) -> list[dict]:
    """For each ROME code: its France Travail title, FAP-2021 families (with the qualification classes each applies
    to), FAP-2009 families (with their 87-group), and possible ISCO-08 codes (distinct job titles behind each)."""
    romes = [r for r in dict.fromkeys(romes) if ROME_CODE.match(r or "")]
    if not romes or not _has(con):
        return []
    q = ", ".join("?" * len(romes))
    qlab = dict(con.execute("SELECT qualif, libelle FROM core.nomen_qualif").fetchall())
    title = dict(con.execute(f"SELECT rome, intitule FROM core.nomen_rome WHERE rome IN ({q})", romes).fetchall())
    f21 = {}
    for rome, fap, lib, f86, l86, qual in con.execute(f"""
            SELECT r.rome, r.fap341, f.lib341, f.fap86, f.lib86, r.qualif FROM core.nomen_rome_fap2021 r
            LEFT JOIN core.nomen_fap2021 f USING (fap341) WHERE r.rome IN ({q})""", romes).fetchall():
        f21.setdefault(rome, {}).setdefault(fap, {"code": fap, "libelle": lib, "fap86": f86, "libelle86": l86, "q": set()})["q"].add(qual)
    f09 = {}
    for rome, fap, lib, lib87, qual in con.execute(f"""
            SELECT r.rome, r.fap2009, a.libelle, b.libelle, r.qualif FROM core.nomen_rome_fap2009 r
            LEFT JOIN core.nomen_fap2009 a ON a.code = r.fap2009 LEFT JOIN core.nomen_fap2009 b ON b.code = left(r.fap2009, 3)
            WHERE r.rome IN ({q})""", romes).fetchall():
        f09.setdefault(rome, {}).setdefault(fap, {"code": fap, "libelle": lib, "fap87": fap[:3], "libelle87": lib87, "q": set()})["q"].add(qual)
    isc = {}
    for rome, code, prec, n, quals, lib in con.execute(f"""
            SELECT r.rome, r.isco, any_value(r.precision), count(DISTINCT r.intitule_id), list(DISTINCT r.qualif), any_value(i.libelle)
            FROM core.nomen_rome_isco r LEFT JOIN core.nomen_isco i USING (isco) WHERE r.rome IN ({q}) GROUP BY 1, 2""", romes).fetchall():
        isc.setdefault(rome, {})[code] = {"code": code, "libelle": lib if prec == 4 else None, "precision": prec,
                                          "n_intitules": n, "q": set(quals)}
    out = []
    for rome in romes:
        def fin(d, key, labels):
            items = []
            for e in d.get(rome, {}).values():
                e = dict(e)
                e["qualifications"] = _qualifs(e.pop("q"), labels)
                items.append(e)
            return sorted(items, key=key)
        out.append({"rome": rome, "intitule": title.get(rome), "connu": rome in title,
                    "fap2021": fin(f21, lambda e: (e["qualifications"]["codes"][:1], e["code"]), qlab),
                    # FAP-2009 qualification codes are France Travail's (4 = highly qualified worker): no FAP-2021 name
                    "fap2009": fin(f09, lambda e: (e["qualifications"]["codes"][:1], e["code"]), None),
                    "isco": fin(isc, lambda e: (-e["precision"], -e["n_intitules"], e["code"]), qlab)})
    return out
