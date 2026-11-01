"""B1: success after the first year of licence, per university and broad discipline (SIES).

Source: SIES Note Flash 2025-29, "Tableaux réussite et passage par discipline et établissement"
(the Excel file the owner downloads from the ministry site, which rejects automated downloads,
and commits under data/sources/). What SIES publishes there, checked on the real file:

* one row per (university, broad discipline in L1); five broad disciplines plus "Toutes
  disciplines". Nothing per formation: a figure is shown as "university × discipline", never as
  the figure of one licence;
* three cohorts: L1 → L2 transition of the 2023 entrants (with repeat, reorientation and exit, a
  partition of the entrants), licence in 3 years of the 2021 entrants, in 3 or 4 years of the 2020
  entrants; each with an observed rate, a "simulated" rate (expected from the entrants' profile)
  and a value added = observed − simulated, in points;
* small cohorts are masked ("ns"), some values are not available ("nd", ".");
* a university's discipline rows may carry a shorter name than its total row ("UNIVERSITE
  TOULOUSE 1 (CAPITOLE)" then "UNIVERSITE TOULOUSE 1"): rows are grouped by block, the block
  starting at a "Toutes disciplines" row, and the sums of discipline entrants equal the total;
* two national rows: "Etudiants" and "Inscriptions principales". The universities add up to the
  latter, which is therefore the national reference.

Official rates are stored and shown as published, never recomputed.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import config

SOURCE_GLOB = "sies_reussite_licence*.xlsx"
NATIONAL = "__national__"
NATIONAL_ROW = "Inscriptions principales"   # the universities add up to this row, not to "Etudiants"
SKIPPED_ROWS = ("Etudiants",)
SMALL_COHORT = 100                          # SIES masks success rates below ~100 entrants; flag below it
LICENCE_FILI = ("Licence", "Licence_Las")

DISCIPLINES = {   # code -> (SIES label, short French label)
    "toutes": ("Toutes disciplines", "toutes disciplines"),
    "droit": ("Droit, Sc. politiques", "droit, science politique"),
    "eco": ("Economie, AES", "économie, gestion, AES"),
    "alsh": ("Arts, lettres, langues, SHS", "arts, lettres, langues, sciences humaines et sociales"),
    "sciences": ("Sciences-santé", "sciences, santé"),
    "staps": ("STAPS", "STAPS"),
}

# Parcoursup detailed programme (fil_lib_voe_acc) of a licence -> SIES broad discipline in L1.
# Only unambiguous programmes are classified; a double or cross-field licence (droit-économie,
# MIASHS, sciences sanitaires et sociales...) gets no discipline figure rather than a guess.
DISCIPLINE_OF_PROGRAMME = {
    "droit": ("Droit", "Droit français - Droit étranger", "Science politique"),
    "eco": ("Economie et gestion", "Economie", "Gestion", "Administration économique et sociale"),
    "alsh": ("Langues, littératures et civilisations étrangères et régionales", "Langues étrangères appliquées",
             "Lettres", "Histoire", "Sciences de l'éducation et de la formation", "Géographie et aménagement",
             "Philosophie", "Sciences du langage", "Psychologie", "Sociologie", "Information et communication",
             "Histoire de l'art et archéologie", "Histoire de l'art", "Humanités", "Musicologie", "Arts",
             "Arts du spectacle", "Sciences sociales", "Arts plastiques", "Etudes théâtrales", "Cinéma",
             "Cinéma et Audiovisuel", "Sciences de l'Homme, Anthropologie, Ethnologie", "Etudes culturelles",
             "Lettres, langues", "Lettres / Histoire", "Histoire / Géographie", "Histoire / Allemand"),
    "sciences": ("Mathématiques", "Sciences de la vie", "Informatique", "Chimie", "Physique", "Physique, chimie",
                 "Sciences pour l'ingénieur", "Sciences de la vie et de la terre", "Sciences de la terre",
                 "Sciences pour la santé", "Sciences et technologies", "Mécanique",
                 "Electronique, énergie électrique, automatique", "Génie civil", "Sciences biomédicales",
                 "Chimie, Sciences de la vie", "Informatique, Sciences de la vie",
                 "Mathématiques, Physique et Sciences pour l'Ingénieur", "Sciences de la Terre et environnement",
                 "Informatique, Mathématiques", "Mathématiques, physique, chimie, informatique",
                 "Mathématiques, Sciences de la vie", "Sciences de la Terre et Sciences Physiques",
                 "Acoustique et Vibrations", "Sciences des systèmes communicants"),
    "staps": ("Sciences et Techniques des Activités Physiques et Sportives",),
}
PROGRAMME_DISCIPLINE = {p: d for d, ps in DISCIPLINE_OF_PROGRAMME.items() for p in ps}

# SIES university (name of its "Toutes disciplines" row) -> regex on the folded Parcoursup
# establishment name (g_ea_lib_vx). A Parcoursup establishment is linked only when exactly one
# pattern matches it: an ambiguous site (an Évry or Guyancourt campus of Paris-Saclay, which SIES
# may count under Évry or Versailles) stays unlinked rather than guessed.
UNIVERSITIES = {
    "CUFR MAYOTTE": r"^universite de mayotte",
    "CY CERGY UNIVERSITE": r"\bcy cergy\b|cergy-pontoise",
    "INU CHAMPOLLION": r"champollion",
    "LE MANS UNIVERSITE": r"le mans universite|universite du mans",
    "SORBONNE UNIVERSITE": r"\bsorbonne universite\b",
    "UNIV. CLERMONT AUVERGNE (EPE)": r"clermont auvergne",
    "UNIVERSITE  BREST": r"^universite de brest",
    "UNIVERSITE AIX-MARSEILLE": r"^aix-marseille universite",
    "UNIVERSITE AMIENS": r"^universite d'amiens|^insset de saint-quentin",
    "UNIVERSITE ANGERS": r"^universite angers",
    "UNIVERSITE ANTILLES": r"^universite des antilles",
    "UNIVERSITE ARTOIS": r"^universite d'artois",
    "UNIVERSITE AVIGNON": r"^avignon universite",
    "UNIVERSITE BORDEAUX 3": r"bordeaux montaigne",
    "UNIVERSITE BRETAGNE SUD": r"^universite de bretagne sud",
    "UNIVERSITE CORSE": r"^universite de corte|^universite de corse",
    "UNIVERSITE COTE AZUR": r"^universite cote d'azur",
    "UNIVERSITE DE BESANCON": r"franche-comte",
    "UNIVERSITE DE BORDEAUX": r"^universite de bordeaux\b|^departement universitaire de sciences d'agen",
    "UNIVERSITE DE CAEN NORMANDIE": r"^universite de caen",
    "UNIVERSITE DE LORRAINE": r"^universite de lorraine",
    "UNIVERSITE DE RENNES (RENNES 1)": r"^universite de rennes \(epe\)",
    "UNIVERSITE DE ROUEN NORMANDIE": r"^universite de rouen|universite de rouen\b",
    "UNIVERSITE DE TOULON": r"^universite de toulon",
    "UNIVERSITE DIJON": r"bourgogne europe",
    "UNIVERSITE EVRY VAL D ESSONNE": r"^universite d'evry",
    "UNIVERSITE GRENOBLE-ALPES": r"^universite grenoble alpes",
    "UNIVERSITE GUSTAVE EIFFEL": r"gustave eiffel",
    "UNIVERSITE GUYANE": r"^universite de guyane",
    "UNIVERSITE LA REUNION": r"^universite de la reunion",
    "UNIVERSITE LA ROCHELLE": r"^la rochelle universite",
    "UNIVERSITE LE HAVRE NORMANDIE": r"^universite le havre",
    "UNIVERSITE LILLE": r"^universite de lille",
    "UNIVERSITE LIMOGES": r"^universite de limoges",
    "UNIVERSITE LITTORAL": r"^universite du littoral",
    "UNIVERSITE LYON 1 (CLAUDE BERNARD)": r"claude bernard|\blyon 1\b",
    "UNIVERSITE LYON 2 (LUMIERE)": r"\blyon 2\b",
    "UNIVERSITE LYON 3 (JEAN MOULIN)": r"\blyon 3\b",
    "UNIVERSITE MONTPELLIER": r"^universite de montpellier",
    "UNIVERSITE MONTPELLIER 3": r"paul valery|montpellier 3",
    "UNIVERSITE MULHOUSE": r"^universite de mulhouse|^uha business school",
    "UNIVERSITE NANTES": r"^nantes universite",
    "UNIVERSITE NIMES": r"^universite de nimes",
    "UNIVERSITE NOUVELLE-CALEDONIE": r"nouvelle-caledonie",
    "UNIVERSITE ORLEANS": r"^universite d'orleans",
    "UNIVERSITE PARIS 1 (PANTHEON SORBONNE)": r"\bparis 1\b|pantheon sorbonne",
    "UNIVERSITE PARIS 13 (SORBONNE PARIS NORD)": r"sorbonne paris nord|\bparis 13\b",
    "UNIVERSITE PARIS 2 (PANTHEON ASSAS)": r"pantheon-? ?assas|\bparis ?2\b",
    "UNIVERSITE PARIS 3 (SORBONNE NOUVELLE)": r"sorbonne nouvelle|\bparis 3\b",
    "UNIVERSITE PARIS 8 (VINCENNES SAINT-DENIS)": r"^universite paris 8\b",
    "UNIVERSITE PARIS CITE": r"^universite paris cite",
    "UNIVERSITE PARIS NANTERRE": r"^universite paris nanterre",
    "UNIVERSITE PARIS SACLAY": r"^(?!.*\bevry\b)(?!.*versailles)(?!.*guyancourt).*paris-saclay",
    "UNIVERSITE PARIS SCIENCES LETTRES": r"paris sciences (et )?lettres|\bpsl\b",
    "UNIVERSITE PARIS-EST CRETEIL": r"est-? ?creteil|\bupec\b",
    "UNIVERSITE PAU": r"^universite de pau",
    "UNIVERSITE PERPIGNAN": r"^universite de perpignan",
    "UNIVERSITE POITIERS": r"^universite de poitiers",
    "UNIVERSITE POLYNESIE FRANCAISE": r"polynesie francaise",
    "UNIVERSITE POLYTECHNIQUE DES HAUTS DE FRANCE": r"polytechnique hauts-de-france",
    "UNIVERSITE REIMS": r"^universite de reims|\burca\b|^inspe de reims|^eisine|^esireims",
    "UNIVERSITE RENNES 2": r"universite de rennes 2",
    "UNIVERSITE SAINT ETIENNE": r"jean monnet",
    "UNIVERSITE SAVOIE MONT BLANC": r"savoie mont blanc",
    "UNIVERSITE STRASBOURG": r"^universite de strasbourg",
    "UNIVERSITE TOULOUSE 1 (CAPITOLE)": r"toulouse capitole|\btoulouse 1\b",
    "UNIVERSITE TOULOUSE 2 (JEAN JAURES)": r"\btoulouse 2\b|jean jaures",
    "UNIVERSITE TOULOUSE 3 (PAUL SABATIER)": r"toulouse iii|\btoulouse 3\b|paul sabatier",
    "UNIVERSITE TOURS": r"^universite de tours",
    "UNIVERSITE VERSAILLES ST QUENTIN": r"^(?!.*paris-saclay).*versailles[- ]+saint quentin",
}


# Names a university's total row carries in other sheets of the same file -> the name used above.
SIES_ALIASES = {
    "INST NATIONAL UNIVERSITAIRE": "INU CHAMPOLLION",
    "UNIVERSITE BESANCON": "UNIVERSITE DE BESANCON",
    "UNIVERSITE BREST": "UNIVERSITE  BREST",
    "UNIVERSITE CAEN NORMANDIE": "UNIVERSITE DE CAEN NORMANDIE",
    "UNIVERSITE CLERMONT AUVERGNE": "UNIV. CLERMONT AUVERGNE (EPE)",
    "UNIVERSITE PSL": "UNIVERSITE PARIS SCIENCES LETTRES",
}


# Display names of the SIES universities (the SIES file has upper-case, accent-free names).
UNIVERSITY_LABEL = {
    'CUFR MAYOTTE': 'Université de Mayotte',
    'CY CERGY UNIVERSITE': 'CY Cergy Paris Université',
    'INU CHAMPOLLION': 'Institut national universitaire Champollion',
    'LE MANS UNIVERSITE': 'Le Mans Université',
    'SORBONNE UNIVERSITE': 'Sorbonne Université',
    'UNIV. CLERMONT AUVERGNE (EPE)': 'Université Clermont Auvergne',
    'UNIVERSITE  BREST': 'Université de Brest',
    'UNIVERSITE AIX-MARSEILLE': 'Aix-Marseille Université',
    'UNIVERSITE AMIENS': 'Université de Picardie Jules Verne (Amiens)',
    'UNIVERSITE ANGERS': "Université d'Angers",
    'UNIVERSITE ANTILLES': 'Université des Antilles',
    'UNIVERSITE ARTOIS': "Université d'Artois",
    'UNIVERSITE AVIGNON': 'Avignon Université',
    'UNIVERSITE BORDEAUX 3': 'Université Bordeaux Montaigne',
    'UNIVERSITE BRETAGNE SUD': 'Université Bretagne Sud',
    'UNIVERSITE CORSE': 'Université de Corse',
    'UNIVERSITE COTE AZUR': "Université Côte d'Azur",
    'UNIVERSITE DE BESANCON': 'Université Marie et Louis Pasteur (Besançon)',
    'UNIVERSITE DE BORDEAUX': 'Université de Bordeaux',
    'UNIVERSITE DE CAEN NORMANDIE': 'Université de Caen Normandie',
    'UNIVERSITE DE LORRAINE': 'Université de Lorraine',
    'UNIVERSITE DE RENNES (RENNES 1)': 'Université de Rennes',
    'UNIVERSITE DE ROUEN NORMANDIE': 'Université de Rouen Normandie',
    'UNIVERSITE DE TOULON': 'Université de Toulon',
    'UNIVERSITE DIJON': 'Université Bourgogne Europe (Dijon)',
    'UNIVERSITE EVRY VAL D ESSONNE': "Université d'Évry",
    'UNIVERSITE GRENOBLE-ALPES': 'Université Grenoble Alpes',
    'UNIVERSITE GUSTAVE EIFFEL': 'Université Gustave Eiffel',
    'UNIVERSITE GUYANE': 'Université de Guyane',
    'UNIVERSITE LA REUNION': 'Université de La Réunion',
    'UNIVERSITE LA ROCHELLE': 'La Rochelle Université',
    'UNIVERSITE LE HAVRE NORMANDIE': 'Université Le Havre Normandie',
    'UNIVERSITE LILLE': 'Université de Lille',
    'UNIVERSITE LIMOGES': 'Université de Limoges',
    'UNIVERSITE LITTORAL': "Université du Littoral Côte d'Opale",
    'UNIVERSITE LYON 1 (CLAUDE BERNARD)': 'Université Claude Bernard Lyon 1',
    'UNIVERSITE LYON 2 (LUMIERE)': 'Université Lumière Lyon 2',
    'UNIVERSITE LYON 3 (JEAN MOULIN)': 'Université Jean Moulin Lyon 3',
    'UNIVERSITE MONTPELLIER': 'Université de Montpellier',
    'UNIVERSITE MONTPELLIER 3': 'Université Paul-Valéry Montpellier 3',
    'UNIVERSITE MULHOUSE': 'Université de Haute-Alsace (Mulhouse)',
    'UNIVERSITE NANTES': 'Nantes Université',
    'UNIVERSITE NIMES': 'Université de Nîmes',
    'UNIVERSITE NOUVELLE-CALEDONIE': 'Université de la Nouvelle-Calédonie',
    'UNIVERSITE ORLEANS': "Université d'Orléans",
    'UNIVERSITE PARIS 1 (PANTHEON SORBONNE)': 'Université Paris 1 Panthéon-Sorbonne',
    'UNIVERSITE PARIS 13 (SORBONNE PARIS NORD)': 'Université Sorbonne Paris Nord',
    'UNIVERSITE PARIS 2 (PANTHEON ASSAS)': 'Université Paris-Panthéon-Assas',
    'UNIVERSITE PARIS 3 (SORBONNE NOUVELLE)': 'Université Sorbonne Nouvelle',
    'UNIVERSITE PARIS 8 (VINCENNES SAINT-DENIS)': 'Université Paris 8 Vincennes-Saint-Denis',
    'UNIVERSITE PARIS CITE': 'Université Paris Cité',
    'UNIVERSITE PARIS NANTERRE': 'Université Paris Nanterre',
    'UNIVERSITE PARIS SACLAY': 'Université Paris-Saclay',
    'UNIVERSITE PARIS SCIENCES LETTRES': 'Université PSL',
    'UNIVERSITE PARIS-EST CRETEIL': 'Université Paris-Est Créteil',
    'UNIVERSITE PAU': "Université de Pau et des Pays de l'Adour",
    'UNIVERSITE PERPIGNAN': 'Université de Perpignan Via Domitia',
    'UNIVERSITE POITIERS': 'Université de Poitiers',
    'UNIVERSITE POLYNESIE FRANCAISE': 'Université de la Polynésie française',
    'UNIVERSITE POLYTECHNIQUE DES HAUTS DE FRANCE': 'Université Polytechnique Hauts-de-France',
    'UNIVERSITE REIMS': 'Université de Reims Champagne-Ardenne',
    'UNIVERSITE RENNES 2': 'Université Rennes 2',
    'UNIVERSITE SAINT ETIENNE': 'Université Jean Monnet Saint-Étienne',
    'UNIVERSITE SAVOIE MONT BLANC': 'Université Savoie Mont Blanc',
    'UNIVERSITE STRASBOURG': 'Université de Strasbourg',
    'UNIVERSITE TOULOUSE 1 (CAPITOLE)': 'Université Toulouse Capitole',
    'UNIVERSITE TOULOUSE 2 (JEAN JAURES)': 'Université Toulouse Jean Jaurès',
    'UNIVERSITE TOULOUSE 3 (PAUL SABATIER)': 'Université Toulouse III (Paul Sabatier)',
    'UNIVERSITE TOURS': 'Université de Tours',
    'UNIVERSITE VERSAILLES ST QUENTIN': 'Université de Versailles Saint-Quentin-en-Yvelines',
}


def fold(s: str | None) -> str:
    # typographic apostrophes first: dropped by the ASCII fold, "d’Evry" would become "devry"
    s = (s or "").replace("’", "'").replace("‘", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def source_path(data_dir: Path | None = None) -> Path | None:
    files = sorted((data_dir or config.DATA_DIR / "sources").glob(SOURCE_GLOB))
    return files[-1] if files else None


# ------------------------------------------------------------------------- workbook parsing
def _num(v):
    if isinstance(v, bool):
        return None, "type"
    if isinstance(v, (int, float)):
        return float(v), None
    t = str(v).strip().lower() if v is not None else ""
    return None, {"ns": "ns", "nd": "nd", ".": "na", "": "vide"}.get(t, "texte")


# column key -> predicate on the folded header, per sheet kind (headers, not positions: SIES
# reorders and renames columns between releases)
COLUMNS = {
    "passage": {
        "inscrits": lambda h: h.startswith("inscrits en l1"),
        "taux": lambda h: h == "taux de passage en l2",
        "taux_simule": lambda h: h == "taux de passage en l2 simule",
        "va": lambda h: h.startswith("passage en l2 - valeur ajoutee"),
        "taux_mmopk": lambda h: h == "taux de passage en mmopk",
        "taux_redoublement": lambda h: h == "taux de redoublement en l1",
        "taux_reorientation": lambda h: h == "taux de reorientation",
        "taux_sortie": lambda h: h == "taux de sortie de l'enseignement superieur",
        "n_passage": lambda h: h == "passage en l2",
        "n_redoublement": lambda h: h == "redoublement en l1",
        "n_reorientation": lambda h: h == "reorientation",
        "n_sortie": lambda h: h == "sortie de l'enseignement superieur",
    },
    "reussite3": {
        "inscrits": lambda h: h.startswith("inscrits en l1"),
        "taux": lambda h: h == "taux de reussite a 3 ans",
        "taux_simule": lambda h: h == "taux simule",
        "va": lambda h: h.startswith("valeur ajoutee"),
        "n_reussite": lambda h: h == "reussite en 3 ans",
    },
    "reussite34": {
        "inscrits": lambda h: h.startswith("inscrits en l1"),
        "taux": lambda h: h == "reussite en 3 ou 4 ans (taux observe)",
        "taux_simule": lambda h: h == "reussite en 3 ou 4 ans (taux simule)",
        "va": lambda h: h == "valeur ajoutee reussite en 3 ou 4 ans (en points)",
        "taux3": lambda h: h == "reussite en 3 ans (taux observe)",
        "taux4": lambda h: h == "reussite en 4 ans (taux observe)",
        "n_reussite": lambda h: h == "reussite en 3 ou 4 ans",
    },
}
KIND_OF_TITLE = (("devenir", "passage"), ("reussite en licence en 3 ou 4 ans", "reussite34"),
                 ("reussite en licence en 3 ans", "reussite3"))
DISC_CODE = {fold(v[0]): k for k, v in DISCIPLINES.items()}


def _kind(title: str) -> str | None:
    t = fold(title)
    return next((k for needle, k in KIND_OF_TITLE if t.startswith(needle)), None)


def _cohort(title: str, kind: str) -> int | None:
    t = fold(title)
    m = re.search(r"rentree (\d{4})", t) if kind == "passage" else re.search(r"inscrits en licence en (\d{4})", t)
    return int(m.group(1)) if m else None


def parse_workbook(path: Path) -> list[dict]:
    """Every (sheet kind, university block, discipline) row with its published values."""
    import openpyxl   # pipeline-only dependency
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows or not rows[0] or not rows[0][0]:
            continue
        kind = _kind(str(rows[0][0]))
        if kind is None:
            continue
        hi = next(i for i, r in enumerate(rows) if r and r[0] and fold(str(r[0])).startswith("nom etablissement"))
        head = [fold(str(h)) if h else "" for h in rows[hi]]
        cols = {}
        for key, pred in COLUMNS[kind].items():
            idx = [i for i, h in enumerate(head) if pred(h)]
            if len(idx) != 1:
                raise ValueError(f"{ws.title}: column {key} found {len(idx)} times in {head}")
            cols[key] = idx[0]
        cohort = _cohort(str(rows[0][0]), kind)
        block = None
        for r in rows[hi + 1:]:
            if not r or not r[0] or not r[1]:
                continue
            name, disc = str(r[0]).strip(), fold(str(r[1]).replace("\n", " "))
            code = DISC_CODE.get(disc)
            if code is None:
                continue          # notes and footers
            if code == "toutes":
                block = SIES_ALIASES.get(name, name)
            if block in SKIPPED_ROWS:
                continue
            rec = {"kind": kind, "cohort": cohort, "etab": NATIONAL if block == NATIONAL_ROW else block,
                   "etab_row": name, "discipline": code, "masked": {}}
            for key, i in cols.items():
                v, why = _num(r[i] if i < len(r) else None)
                rec[key] = v
                if why:
                    rec["masked"][key] = why
            out.append(rec)
    return out


# ------------------------------------------------------------------------- linking
def university_of(name: str, table: dict[str, str] | None = None) -> tuple[str | None, list[str]]:
    """(SIES university, all matching universities) for a Parcoursup establishment name."""
    f = fold(name)
    hits = [u for u, rx in (table or UNIVERSITIES).items() if re.search(rx, f)]
    return (hits[0] if len(hits) == 1 else None), hits


def discipline_of(programme: str | None) -> str | None:
    return PROGRAMME_DISCIPLINE.get(programme or "")


def attach(con, path: Path | None, table: dict[str, str] | None = None) -> int:
    """Build core.licence_success (published rows) and core.licence_success_link (formation ->
    university, discipline). Returns the number of linked formations (0 without a source)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.licence_success (
        kind VARCHAR, cohort INTEGER, etab VARCHAR, etab_row VARCHAR, discipline VARCHAR,
        inscrits DOUBLE, taux DOUBLE, taux_simule DOUBLE, va DOUBLE, taux3 DOUBLE, taux4 DOUBLE,
        taux_mmopk DOUBLE, taux_redoublement DOUBLE, taux_reorientation DOUBLE, taux_sortie DOUBLE,
        n_passage DOUBLE, n_redoublement DOUBLE, n_reorientation DOUBLE, n_sortie DOUBLE, n_reussite DOUBLE,
        masked VARCHAR, source VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE core.licence_success_link (
        session INTEGER, cod_aff_form VARCHAR, etab VARCHAR, discipline VARCHAR, programme VARCHAR,
        matches VARCHAR)""")
    if path is None or not Path(path).exists():
        return 0
    import json
    rows = parse_workbook(Path(path))
    keys = ("kind", "cohort", "etab", "etab_row", "discipline", "inscrits", "taux", "taux_simule", "va", "taux3",
            "taux4", "taux_mmopk", "taux_redoublement", "taux_reorientation", "taux_sortie", "n_passage",
            "n_redoublement", "n_reorientation", "n_sortie", "n_reussite")
    con.executemany(f"INSERT INTO core.licence_success VALUES ({', '.join('?' * (len(keys) + 2))})",
                    [[r.get(k) for k in keys] + [json.dumps(r["masked"], sort_keys=True), Path(path).name] for r in rows])
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    forms = con.execute(f"""SELECT cod_aff_form, g_ea_lib_vx, fil_lib_voe_acc FROM core.formation_year
        WHERE session = ? AND contrat_etab = 'Public' AND fili IN {LICENCE_FILI}""", [latest]).fetchall()
    known = {r["etab"] for r in rows}
    links = []
    for cod, etab, prog in forms:
        uni, hits = university_of(etab, table)
        if uni is not None and uni not in known:
            uni = None
        links.append([latest, cod, uni, discipline_of(prog), prog, "|".join(hits)])
    con.executemany("INSERT INTO core.licence_success_link VALUES (?, ?, ?, ?, ?, ?)", links)
    return sum(1 for x in links if x[2])


# ------------------------------------------------------------------------- serving
def _row(con, kind, etab, disc):
    r = con.execute("""SELECT * FROM core.licence_success WHERE kind = ? AND etab = ? AND discipline = ?""",
                    [kind, etab, disc]).fetchone()
    if r is None:
        return None
    cols = [d[0] for d in con.description]
    d = dict(zip(cols, r))
    import json
    d["masked"] = json.loads(d["masked"] or "{}")
    d["small"] = d["inscrits"] is not None and d["inscrits"] < SMALL_COHORT
    return d


def for_formation(con, cod: str, fili: str | None, contrat: str | None) -> dict | None:
    """The B1 block of a formation page, or None when the formation is not a licence. The link is
    made on the latest campaign (the SIES tables describe recent cohorts of the university)."""
    if fili not in LICENCE_FILI:
        return None
    try:
        link = con.execute("""SELECT etab, discipline, programme FROM core.licence_success_link
                              WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
        n_rows = con.execute("SELECT count(*) FROM core.licence_success").fetchone()[0]
    except Exception:  # noqa: BLE001 - older warehouse without the B1 tables
        return None
    if not n_rows:
        return None
    base = {"kinds": {}, "national": {}, "discipline": None, "discipline_label": None, "etab": None}
    if contrat != "Public":
        return {**base, "status": "hors_champ", "reason": "SIES publie ces taux pour les universités publiques seulement"}
    if link is None or link[0] is None:
        return {**base, "status": "non_rattachee",
                "reason": "cet établissement n'a pas pu être rattaché avec certitude à une université des tableaux SIES"}
    etab, disc, _ = link
    out = {**base, "status": "ok", "etab": etab, "etab_label": UNIVERSITY_LABEL.get(etab, etab), "discipline": disc,
           "discipline_label": DISCIPLINES[disc][1] if disc else None}
    if disc is None:
        out["status"] = "discipline_non_classee"
        out["reason"] = "cette licence ne relève pas clairement d'une seule des cinq grandes disciplines du SIES"
    for kind in ("passage", "reussite3", "reussite34"):
        nat = _row(con, kind, NATIONAL, disc or "toutes")
        if nat:
            out["national"][kind] = nat
        if disc:
            u = _row(con, kind, etab, disc)
            if u:
                out["kinds"][kind] = u
    if disc and not out["kinds"]:
        out["status"] = "non_publie"
        out["reason"] = "le SIES ne publie pas cette discipline pour cette université"
    return out
