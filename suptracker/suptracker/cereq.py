"""Sprint 8 follow-up: does the job match the training? The Céreq Génération 2017 survey, nationally.

What the Céreq publishes, checked on the real file before the design (the owner downloads it from the
"chiffres clés par diplôme" data visualisation and commits it under data/sources/: the file is produced
by a button of an interactive application, no robot can fetch it):

* the young people who left initial education in 2016-2017 (746,000, weighted), surveyed in 2020
  (3 years later, 25,000 respondents) and in 2023 (6 years later, 8,750 respondents);
* about twenty groups of HIGHEST DIPLOMA at the exit, nested by level and broad field (bac+2 industrial
  or tertiary, bac+3/4 and master in humanities-law-management or sciences, health and social work,
  business or engineering schools, doctorates...). Every group adds up to its parent (±1, rounding),
  and every distribution adds up to 100 (±2);
* the share of the EMPLOYED who declare that their job matches their training (`correspondance_ok`,
  3 and 6 years) and, at 3 years, who declare being employed at their skill level (`competence_ok`);
  the employment rate among ALL the leavers; open-ended jobs, managers and intermediate professions
  among the employed; the median monthly income.

It is a national figure for everyone whose highest diploma is in the group, not this formation's
students, and a student who goes on studying ends up in a higher group. The link from a Parcoursup
formation to a group is a fixed rule per filière:
* BTS: bac+2, industrial or tertiary by the NSF field of the diploma (digits 7-9 of its MEFSTAT11 code,
  4-6 of its CFD code, read from
  Inserjeunes for the same BTS title, any establishment; NSF 200-255 production, 300-345 services);
  a BTS whose field is unknown gets the bac+2 total;
* licence: bac+3/4 and, for whoever goes on, master, in humanities-law-management (B1 disciplines
  droit, eco, alsh) or sciences (sciences, staps);
* IFSI, EFTS: health and social work; engineering and business schools: their group; CPGE: the schools
  most of their students enter (scientific tracks -> engineering, ECG/ECT -> business);
* BUT (created in 2021, absent from the 2017 cohort), PASS, literary CPGE and other formations: no figure.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config
from .insertion import bts_key
from .success import fold

SOURCE_GLOB = "*.xlsx"
SHEETS = {"Données_3ans": 3, "Données_6ans": 6}
GENERATION, SURVEYS = 2017, {3: 2020, 6: 2023}
INDICATORS = ("eff_pond_g1", "pct_col", "taux_emploi", "part_chomage", "part_autre", "taux_chomage", "taux_edi",
              "part_tps_partiel", "revenu_travail", "pos_cadres", "pos_prof_int", "pos_emp_ouv_q", "pos_emp_ouv_nq",
              "pos_autres", "correspondance_ok", "competence_ok")
TOTAL = 100

# the Céreq group of a formation: (code, what the student reads)
GROUPS = {
    411: "BTS, DUT et autres bac+2 (hors santé-social)",
    412: "BTS, DUT et autres bac+2 de spécialité industrielle",
    413: "BTS, DUT et autres bac+2 de spécialité tertiaire",
    420: "diplômes bac+2 à bac+4 de la santé et du social",
    441: "licence et bac+4",
    442: "licence et bac+4 en lettres, sciences humaines, gestion, droit",
    443: "licence et bac+4 en sciences, techniques, STAPS",
    511: "master",
    512: "master en lettres, sciences humaines, gestion, droit",
    513: "master en sciences, techniques, STAPS",
    522: "diplôme d'école de commerce",
    523: "diplôme d'école d'ingénieurs",
}
LICENCE_DOMAIN = {"droit": "lsh", "eco": "lsh", "alsh": "lsh", "sciences": "sci", "staps": "sci"}
CPGE_SCI = re.compile(r"^(pcsi|mpsi|ptsi|bcpst|tsi|mp2i|tb|tpc)\b")
CPGE_ECO = re.compile(r"^(ecg|ect)\b")


def nsf_of(code: str | None) -> int | None:
    """NSF field of a diploma code: digits 7-9 of a MEFSTAT11 (11 characters, Inserjeunes lycées: 322 210 312 13 =
    BTS management commercial opérationnel, NSF 312) or digits 4-6 of a diploma code CFD (8 characters, Inserjeunes CFA:
    320 312 12). Any other length: unknown."""
    c = (code or "").strip()
    part = c[6:9] if len(c) == 11 else c[3:6] if len(c) == 8 else ""
    return int(part) if part.isdigit() else None


def nsf_side(nsf: int | None) -> str | None:
    if nsf is None:
        return None
    if 200 <= nsf <= 255:
        return "industrielle"
    if 300 <= nsf <= 345:
        return "tertiaire"
    return None


# ------------------------------------------------------------------------- the workbook
def detect(path: Path) -> bool:
    """The Céreq 'données par diplôme' workbook, recognised by its content (sheets and columns)."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        if not set(SHEETS) <= set(wb.sheetnames):
            return False
        head = next(wb["Données_6ans"].iter_rows(max_row=1, values_only=True))
        return "correspondance_ok" in head and "Code" in head
    finally:
        wb.close()


def source_path(data_dir: Path | None = None) -> Path | None:
    files = [p for p in sorted((data_dir or config.DATA_DIR / "sources").glob(SOURCE_GLOB)) if detect(p)]
    return files[-1] if files else None


def read(path: Path) -> list[dict]:
    """One row per (horizon, group code): the published values, numbers only (anything else -> None)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for sheet, h in SHEETS.items():
        rows = list(wb[sheet].iter_rows(values_only=True))
        head = list(rows[0])
        for r in rows[1:]:
            d = dict(zip(head, r))
            if not isinstance(d.get("Code"), (int, float)):
                continue
            rec = {"horizon": h, "code": int(d["Code"]), "libelle_menu": d.get("Libelle_Menu"), "libelle": d.get("Libelle complet")}
            for k in INDICATORS:
                v = d.get(k)
                rec[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
            out.append(rec)
    wb.close()
    return out


# ------------------------------------------------------------------------- the link
def group_of(fili: str | None, programme: str | None, discipline: str | None, nsf: int | None) -> tuple[int | None, int | None, str]:
    """(group of the diploma itself, group for whoever goes on, rule)."""
    p = fold(programme)
    if fili == "BTS":
        side = nsf_side(nsf)
        return ({"industrielle": 412, "tertiaire": 413}.get(side, 411), None, f"bts_{side or 'inconnu'}")
    if fili in ("Licence", "Licence_Las"):
        dom = LICENCE_DOMAIN.get(discipline or "")
        return ({"lsh": 442, "sci": 443}.get(dom, 441), {"lsh": 512, "sci": 513}.get(dom, 511), f"licence_{dom or 'sans_discipline'}")
    if fili in ("IFSI", "EFTS"):
        return 420, None, "sante_social"
    if fili == "Ecole d'Ingénieur":
        return 523, None, "ecole_ingenieurs"
    if fili == "Ecole de Commerce":
        return 522, None, "ecole_commerce"
    if fili == "CPGE":
        if CPGE_SCI.match(p):
            return 523, None, "cpge_scientifique"
        if CPGE_ECO.match(p):
            return 522, None, "cpge_economique"
        return None, None, "cpge_sans_destination_unique"
    if fili == "BUT":
        return None, None, "but_absent_de_la_generation_2017"
    return None, None, "sans_correspondance"


def build_links(con) -> int:
    """core.cereq_link: each formation of the latest campaign -> its Céreq group(s) and the rule used."""
    con.execute("""CREATE OR REPLACE TABLE core.cereq_link (session INTEGER, cod_aff_form VARCHAR, fili VARCHAR,
        programme VARCHAR, discipline VARCHAR, nsf INTEGER, code INTEGER, code_suite INTEGER, regle VARCHAR)""")
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    if latest is None:
        return 0
    # NSF of each BTS title, from the Inserjeunes codes of any establishment (the field belongs to the diploma)
    nsf_by_key = {}
    try:
        for lib, code in con.execute("SELECT DISTINCT libelle_formation, code FROM core.inserjeunes_bts").fetchall():
            n = nsf_of(code)
            if n is not None:
                nsf_by_key.setdefault(bts_key(lib), set()).add(n)
    except Exception:  # noqa: BLE001 - warehouse without the insertion tables
        pass
    try:
        disc = dict(con.execute("""SELECT cod_aff_form, arg_max(discipline, session) FROM core.licence_success_link
                                   GROUP BY 1""").fetchall())
    except Exception:  # noqa: BLE001
        disc = {}
    rows = []
    for cod, fili, prog in con.execute("""SELECT cod_aff_form, fili, fil_lib_voe_acc FROM core.formation_year
                                          WHERE session = ?""", [latest]).fetchall():
        nsf = None
        if fili == "BTS":
            k = bts_key(prog)
            # the exact title, else its options (Inserjeunes publishes some BTS option by option, Parcoursup as one)
            ns = nsf_by_key.get(k) or set().union(*[v for kk, v in nsf_by_key.items() if kk.startswith(k + " option")] or [set()])
            sides = {nsf_side(n) for n in ns}
            nsf = next(iter(ns)) if len(sides) == 1 and None not in sides else None   # one field, or none at all
        code, suite, rule = group_of(fili, prog, disc.get(cod), nsf)
        rows.append((latest, cod, fili, prog, disc.get(cod), nsf, code, suite, rule))
    if rows:
        import pandas as pd
        con.register("_cl", pd.DataFrame(rows, columns=["session", "cod_aff_form", "fili", "programme", "discipline", "nsf",
                                                        "code", "code_suite", "regle"]))
        con.execute("INSERT INTO core.cereq_link SELECT * FROM _cl")
        con.unregister("_cl")
    return len(rows)


_FIND = object()


def build(con, path=_FIND) -> dict:
    """core.cereq_diplome (the workbook: by default the one detected in data/sources/, None to skip) and
    core.cereq_link. A missing workbook leaves both empty."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    cols = ", ".join(f"{k} DOUBLE" for k in INDICATORS)
    con.execute(f"""CREATE OR REPLACE TABLE core.cereq_diplome (horizon INTEGER, code INTEGER, libelle_menu VARCHAR,
        libelle VARCHAR, {cols})""")
    path = source_path() if path is _FIND else path
    n = 0
    if path is not None and Path(path).exists():
        recs = read(Path(path))
        keys = ["horizon", "code", "libelle_menu", "libelle", *INDICATORS]
        con.executemany(f"INSERT INTO core.cereq_diplome VALUES ({', '.join('?' * len(keys))})", [[r[k] for k in keys] for r in recs])
        n = len(recs)
    links = build_links(con)
    if not n:                       # no workbook: no figure to link to
        con.execute("DELETE FROM core.cereq_link")
        links = 0
    return {"rows": n, "links": links, "source": str(path) if path else None}


def _has(con, schema, table) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                            [schema, table]).fetchone()[0])


# ------------------------------------------------------------------------- serving
def _group(con, code: int | None) -> dict | None:
    if code is None:
        return None
    out = {}
    cols = ["horizon", "code", "libelle", *INDICATORS]
    for r in con.execute(f"SELECT {', '.join(cols)} FROM core.cereq_diplome WHERE code = ? ORDER BY horizon", [code]).fetchall():
        d = dict(zip(cols, r))
        out[f"a{d['horizon']}ans"] = d
    return out or None


def for_formation(con, cod: str) -> dict | None:
    """The Céreq block of a formation page: its diploma group (and the next one for a licence), against all leavers."""
    if not (_has(con, "core", "cereq_link") and _has(con, "core", "cereq_diplome")):
        return None
    link = con.execute("SELECT code, code_suite, regle, nsf FROM core.cereq_link WHERE cod_aff_form = ?", [cod]).fetchall()
    if not link:
        return None
    code, suite, rule, nsf = link[0]
    if code is None:
        return {"status": "sans_correspondance", "regle": rule}
    return {"status": "ok", "regle": rule, "nsf": nsf, "generation": GENERATION, "enquetes": SURVEYS,
            "groupe": {"code": code, "label": GROUPS.get(code), "valeurs": _group(con, code)},
            "suite": {"code": suite, "label": GROUPS.get(suite), "valeurs": _group(con, suite)} if suite else None,
            "ensemble": {"code": TOTAL, "label": "tous les sortants", "valeurs": _group(con, TOTAL)}}
