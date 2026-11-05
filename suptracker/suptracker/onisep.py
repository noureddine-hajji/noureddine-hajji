"""Sprint 8 follow-up: the jobs (métiers) a formation leads to, from Onisep's Idéo open data (ODbL).

What Onisep publishes, checked on the real files before the design (the owner downloads them from
opendata.onisep.fr and commits them under data/sources/: the site rejected the data workflow):

* "Idéo-Fiches formations" (XML, 2,397 diplomas): each diploma (FOR.xxx) with its type, its level and
  the jobs it prepares for (MET.xxx). Only 47 licence mentions have a sheet, but they cover 90 % of the
  Parcoursup licences;
* "Idéo-Fiches métiers" (XML, 1,124 jobs): each job with its minimum access level ("bac + 5"...);
* "Idéo-Métiers" (CSV) and "Idéo-Actions de formation initiale" (CSV, per establishment) are kept as
  published sources; the card does not need them.

No Onisep file carries a Parcoursup code. The jobs belong to the DIPLOMA, not to the establishment, so a
Parcoursup formation is linked to the national Onisep diploma by a fixed rule per filière:
* BTS: the same title (normalised: accents, small words, plural, "opt" = "option", "1re année commune"),
  else the options of that BTS (several sheets), else the BTS without its option;
* BUT: the same specialty, without its "parcours";
* licence (and LAS): the same mention;
* IFSI: the state nursing diploma; EFTS: the state social-work diploma of the same title;
* other filières (CPGE, schools, PASS...): no sheet.

Each job is compared with the diploma's level: "accessible avec ce diplôme" when the job's minimum level
is at most the diploma's, else "après une poursuite d'études (bac + n)". The list is Onisep's, national,
not this establishment's, and it is no promise of a job.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import config

ONISEP_URL = "https://www.onisep.fr/http/redirection/{kind}/slug/{id}"
STOP = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "pour", "sur"}
# the diploma level of each filière, in years after the bac: only a FALLBACK. The level is read from the matched
# Onisep sheet itself (niveau_etudes), because some diplomas break the rule of their filière (the 3-year BTS
# orthoprothésiste and podo-orthésiste are "bac + 3"; red team O3, sprint 12).
LEVEL = {"BTS": 2, "BUT": 3, "Licence": 3, "Licence_Las": 3, "IFSI": 3, "EFTS": 3}
BTS_TYPES = ("brevet de technicien supérieur", "brevet de technicien supérieur agricole")
BUT_TYPE = "bachelor universitaire de technologie"
LICENCE_TYPE = "licence"
NURSE = "diplome etat infirmier"


def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def key(s: str | None) -> str:
    """A comparable title: accents, punctuation, small words, plurals, 'opt' = 'option', common first year."""
    s = fold(s)
    s = re.sub(r"\b1ere annee commune\b|\bspecialite\b", " ", s)
    s = re.sub(r"\bopt\b", "option", s)
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in s.split() if w not in STOP)


def level_rank(label: str | None) -> int | None:
    """'bac + 5' -> 5, 'bac ou équivalent' -> 0, 'CAP ou équivalent' -> -1, '3E' / 'sans diplôme' / brevet -> -2,
    anything else ('autre formation') -> None."""
    t = fold(label)
    m = re.match(r"bac (\d+)", t)
    if m:
        return int(m.group(1))
    if t.startswith("bac"):
        return 0
    if t.startswith("cap") or t.startswith("bep"):
        return -1
    if t in ("3e", "sans diplome", "diplome national du brevet"):
        return -2
    return None


# ------------------------------------------------------------------------- the files
def _xml_root(path: Path):
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
            return ET.fromstring(z.read(names[0])) if names else None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


def find_sources(data_dir: Path | None = None) -> dict:
    """{'formations': zip, 'metiers': zip} recognised by CONTENT (the XML root element), any file name."""
    out = {}
    for p in sorted((data_dir or config.DATA_DIR / "sources").glob("*.zip")):
        root = _xml_root(p)
        if root is not None and root.tag in ("formations", "metiers") and len(root) and root[0].findtext("identifiant"):
            out[root.tag] = p
    return out


def read_formations(path: Path) -> tuple[list[tuple], list[tuple]]:
    """(diplomas, diploma -> job links) from the Idéo-Fiches formations XML."""
    root = _xml_root(path)
    forms, links = [], []
    for f in root:
        fid = f.findtext("identifiant")
        forms.append((fid, f.findtext("libelle_complet"), f.findtext("type_Formation/type_formation_libelle"),
                      f.findtext("niveau_certification"), f.findtext("niveau_etudes/libelle")))
        for m in f.findall("metiers_formation/metier"):
            links.append((fid, m.findtext("id"), m.findtext("nom_metier")))
    return forms, links


def read_metier_extras(path: Path) -> tuple[list[tuple], list[tuple]]:
    """(job id, ROME code) for EVERY ROME code of a job (core.onisep_metier.rome keeps the first; a job carries up to 4),
    and (job id, label, kind) for its search labels: masculine and feminine forms of the job and of each synonym
    (kind "metier" or "synonyme"), from the Idéo-Fiches métiers XML (sprint 12)."""
    root = _xml_root(path)
    romes, labels = [], []
    for m in root:
        mid = m.findtext("identifiant")
        for r in dict.fromkeys(x.text.strip() for x in m.findall("romesV3/romeV3") if x.text and x.text.strip()):
            romes.append((mid, r))
        seen = set()
        for kind, node in [("metier", m)] + [("synonyme", x) for x in m.findall("synonymes/synonyme")]:
            for tag in ("nom_metier", "libelle_masculin", "libelle_feminin"):
                lab = (node.findtext(tag) or "").strip()
                if lab and lab not in seen:
                    seen.add(lab)
                    labels.append((mid, lab, kind))
    return romes, labels


def sheet_level(levels: list[str | None], fili: str | None = None) -> int | None:
    """The diploma level of the matched Onisep sheet(s), in years after the bac (the lowest when several differ);
    the filière's usual level only when no sheet states one."""
    ranks = [r for r in (level_rank(x) for x in levels) if r is not None and r >= 0]
    return min(ranks) if ranks else LEVEL.get(fili)


def read_metiers(path: Path) -> list[tuple]:
    """(job id, name, minimum access level, ROME code) from the Idéo-Fiches métiers XML."""
    root = _xml_root(path)
    out = []
    for m in root:
        out.append((m.findtext("identifiant"), m.findtext("nom_metier"), m.findtext("niveau_acces_min/libelle"),
                    m.findtext("romesV3/romeV3")))
    return out


# ------------------------------------------------------------------------- the link
def index(forms) -> dict:
    """{family: {title key: [diploma ids]}} for the diploma types a Parcoursup filière can match."""
    idx = {"BTS": {}, "BUT": {}, "LIC": {}, "DE": {}}
    for fid, lib, typ, _, _ in forms:
        t, f = typ or "", fold(lib)
        if t in BTS_TYPES:
            fam, spec = "BTS", re.sub(r"^btsa?\s+", "", f)
        elif t == BUT_TYPE:
            fam, spec = "BUT", re.sub(r"\s+parcours\b.*$", "", re.sub(r"^but\s+", "", f))
        elif t == LICENCE_TYPE:
            fam, spec = "LIC", re.sub(r"^licence( mention)?\s+", "", f)
        elif f.startswith("diplome d etat d"):
            fam, spec = "DE", f
        else:
            continue
        idx[fam].setdefault(key(spec), []).append(fid)
    return idx


def match(idx: dict, fili: str | None, programme: str | None) -> tuple[list[str], str]:
    """(Onisep diploma ids, rule) of a Parcoursup formation."""
    if fili == "BTS":
        k = key(programme)
        if k in idx["BTS"]:
            return idx["BTS"][k], "bts_titre"
        opts = sorted({f for kk, v in idx["BTS"].items() if kk.startswith(k + " option") for f in v})
        if opts:
            return opts, "bts_options"
        base = k.split(" option")[0]
        if base != k and base in idx["BTS"]:
            return idx["BTS"][base], "bts_sans_option"
        return [], "bts_sans_fiche"
    if fili == "BUT":
        k = key(re.sub(r"(?i)\s+parcours\b.*$", "", programme or ""))
        return (idx["BUT"][k], "but_specialite") if k in idx["BUT"] else ([], "but_sans_fiche")
    if fili in ("Licence", "Licence_Las"):
        k = key(programme)
        return (idx["LIC"][k], "licence_mention") if k in idx["LIC"] else ([], "licence_sans_fiche")
    if fili == "IFSI":
        k = key(NURSE)
        return (idx["DE"][k], "ifsi") if k in idx["DE"] else ([], "ifsi_sans_fiche")
    if fili == "EFTS":
        k = key("diplome d etat d " + re.sub(r"^d\s*e\s+", "", fold(programme)))
        return (idx["DE"][k], "efts_diplome_etat") if k in idx["DE"] else ([], "efts_sans_fiche")
    return [], "filiere_sans_fiche"


def _insert(con, table: str, rows: list[tuple]) -> None:
    """DuckDB's executemany rejects an empty list: a missing jobs file (or an empty sheet) must not abort the build."""
    if rows:
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows)


def build(con, sources: dict | None = None) -> dict:
    """core.onisep_formation, core.onisep_metier, core.onisep_formation_metier and core.onisep_link.
    sources: {'formations': zip, 'metiers': zip}; default: detected in data/sources/; {} to skip."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.onisep_formation (for_id VARCHAR, libelle VARCHAR, type VARCHAR,
        niveau_certification VARCHAR, niveau_etudes VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE core.onisep_formation_metier (for_id VARCHAR, met_id VARCHAR, nom VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.onisep_metier (met_id VARCHAR, nom VARCHAR, niveau_acces_min VARCHAR,
        niveau_rang INTEGER, rome VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE core.onisep_link (session INTEGER, cod_aff_form VARCHAR, fili VARCHAR,
        programme VARCHAR, for_id VARCHAR, regle VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE core.onisep_metier_rome (met_id VARCHAR, rome VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.onisep_metier_libelle (met_id VARCHAR, libelle VARCHAR, kind VARCHAR)")
    src = find_sources() if sources is None else sources
    if "formations" not in src:
        return {"formations": 0, "metiers": 0, "links": 0}
    forms, links = read_formations(Path(src["formations"]))
    mets = read_metiers(Path(src["metiers"])) if "metiers" in src else []
    _insert(con, "core.onisep_formation", forms)
    _insert(con, "core.onisep_formation_metier", links)
    _insert(con, "core.onisep_metier", [(i, n, lv, level_rank(lv), r) for i, n, lv, r in mets])
    if "metiers" in src:
        romes, labels = read_metier_extras(Path(src["metiers"]))
        _insert(con, "core.onisep_metier_rome", romes)
        _insert(con, "core.onisep_metier_libelle", labels)
    idx = index(forms)
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    rows = []
    for cod, fili, prog in con.execute("SELECT cod_aff_form, fili, fil_lib_voe_acc FROM core.formation_year WHERE session = ?",
                                       [latest]).fetchall():
        fids, rule = match(idx, fili, prog)
        for fid in fids or [None]:
            rows.append((latest, cod, fili, prog, fid, rule))
    _insert(con, "core.onisep_link", rows)
    return {"formations": len(forms), "metiers": len(mets), "links": len({r[1] for r in rows if r[4]})}


# ------------------------------------------------------------------------- serving
def _has(con, table) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = ?",
                            [table]).fetchone()[0])


def for_formation(con, cod: str) -> dict | None:
    """The jobs block of a formation page: the Onisep diploma(s) it matches and their jobs."""
    if not _has(con, "onisep_link"):
        return None
    link = con.execute("SELECT fili, for_id, regle FROM core.onisep_link WHERE cod_aff_form = ? ORDER BY for_id", [cod]).fetchall()
    if not link:
        return None
    fili, rule = link[0][0], link[0][2]
    fids = [f for _, f, _ in link if f]
    if not fids:
        return {"status": "sans_fiche", "regle": rule} if rule != "filiere_sans_fiche" else None
    q = ", ".join("?" * len(fids))
    sheets = con.execute(f"SELECT for_id, libelle, niveau_etudes FROM core.onisep_formation WHERE for_id IN ({q}) ORDER BY libelle",
                         fids).fetchall()
    level = sheet_level([n for _, _, n in sheets], fili)
    dips = [{"id": f, "libelle": lib, "url": ONISEP_URL.format(kind="formation", id=f)} for f, lib, _ in sheets]
    jobs = {}
    for mid, nom, lvl, rank in con.execute(f"""SELECT fm.met_id, coalesce(m.nom, fm.nom), m.niveau_acces_min, m.niveau_rang
                                              FROM core.onisep_formation_metier fm LEFT JOIN core.onisep_metier m USING (met_id)
                                              WHERE fm.for_id IN ({q})""", fids).fetchall():
        acces = None if rank is None or level is None else "direct" if rank <= level else "poursuite"
        jobs[mid] = {"id": mid, "nom": nom, "niveau_acces_min": lvl, "acces": acces,
                     "url": ONISEP_URL.format(kind="metier", id=mid)}
    order = {"direct": 0, None: 1, "poursuite": 2}
    return {"status": "ok", "cod": cod, "regle": rule, "niveau": level, "diplomes": dips,
            "metiers": sorted(jobs.values(), key=lambda j: (order[j["acces"]], fold(j["nom"])))}
