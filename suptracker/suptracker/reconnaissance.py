"""Is the diploma recognised? One badge per formation, from the State label its LIVE Parcoursup fiche prints (sprint V1,
owner 2026-11-15).

The fiche's identity card prints, next to an image (`labellisation/DL_xx.svg`), the label Parcoursup gives a formation
the State controls: "Diplôme national de licence contrôlé par l'Etat", "BTS contrôlé par l'Etat", "Diplôme d'Etat
contrôlé", "Classe préparatoire contrôlée par l'Etat", "Diplôme d'ingénieur contrôlé par l'Etat", "Diplôme conférant grade
de licence contrôlé par l'Etat"... (read by scripts/fiche_parse.badges, harvested into data/fiches/identite.csv). The owner
asked for ONE badge among: diplôme national, diplôme visé, grade de licence ou de master, titre RNCP, or none.

Rules:
  * The badge is the fiche's own label, sorted into a category by FIXED rules on its words (RULES, first match); the page
    always shows the label verbatim beside it ("la fiche Parcoursup fait foi"). A label no rule knows keeps its text
    under "autre" and is listed by the build (meta.reconnaissance_audit), never guessed.
  * A diploma of engineer controlled by the State (CTI) confers the grade de master (Code de l'éducation, art. D612-34):
    said in its own category, never merged with a plain master.
  * A preparatory class is a CONTROLLED formation, not a diploma: its own category.
  * A formation whose fiche prints no label: "aucun label de l'État sur la fiche", unless its Parcoursup title says it
    prepares a professional title (titre professionnel, RNCP: registered by the Ministry of Labour) -> "rncp", source
    "intitulé". Never "non reconnu" by inference: the page says what the fiche shows.
  * A formation whose fiche was not read yet gets no badge (no row), never a default.
  * Whether the formation opens the right to grants ("ouvrant droit aux bourses") is the fiche's own badge, shown as such.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

FICHES = Path(__file__).resolve().parents[1] / "data" / "fiches"

# first match wins: the most specific words first (a "diplôme visé conférant grade de licence" is a grade)
RULES = (
    ("cpge", r"classe preparatoire|\bcpge\b"),
    ("grade_master", r"grade de master"),
    ("grade_licence", r"grade de licence"),
    ("ingenieur", r"\bdiplome d ingenieur"),
    ("vise", r"\bvise\b"),
    ("rncp", r"\brncp\b|\btitre (?:professionnel|certifie|enregistre)"),
    ("etat", r"\bdiplome d etat\b"),
    ("national", r"\bdiplome national\b|\bbtsa?\b|\bbut\b|\bdn ?made\b|\bdcg\b|\bdeust\b|\bdma\b|\blicence\b|\bmaster\b"),
)
LIBELLE = {
    "national": "Diplôme national",
    "etat": "Diplôme d'État",
    "grade_licence": "Grade de licence",
    "grade_master": "Grade de master",
    "ingenieur": "Diplôme d'ingénieur (grade de master)",
    "vise": "Diplôme visé par l'État",
    "rncp": "Titre RNCP",
    "cpge": "Prépa contrôlée par l'État",
    "autre": "Label de l'État",
    "aucun": "Aucun label de l'État sur la fiche",
}
EXPLICATION = {
    "national": "Un diplôme délivré au nom de l'État, le même partout en France.",
    "etat": "Un diplôme délivré par l'État pour exercer une profession réglementée (santé, social...).",
    "grade_licence": "L'État reconnaît ce diplôme au niveau licence (bac + 3) : il permet de poursuivre en master.",
    "grade_master": "L'État reconnaît ce diplôme au niveau master (bac + 5).",
    "ingenieur": "Un diplôme d'ingénieur habilité par la Commission des titres d'ingénieur : il vaut le grade de master (bac + 5).",
    "vise": "L'État a vérifié la qualité de ce diplôme d'école. Un visa ne vaut pas forcément un grade.",
    "rncp": "Une certification professionnelle enregistrée par France compétences. Elle atteste un métier ; elle ne vaut pas forcément un grade pour poursuivre ses études.",
    "cpge": "Une classe préparatoire contrôlée par l'État. Ce n'est pas un diplôme : elle prépare aux concours des écoles.",
    "autre": "La fiche Parcoursup indique un label de l'État : lisez-le tel qu'il est écrit.",
    "aucun": "La fiche Parcoursup de cette formation n'affiche aucun label de l'État. Renseignez-vous auprès de l'établissement.",
}
TITLE_RNCP = r"\btitre professionnel\b|\brncp\b"


def fold(s: str | None) -> str:
    """Lower case, no accent, apostrophes and hyphens as spaces, spaces collapsed."""
    s = (s or "").replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")   # Schœlcher = Schoelcher
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[’'`\-]", " ", s)).strip()


def categorie(label: str | None) -> str | None:
    """The category of one printed label (None for an empty label)."""
    f = fold(label)
    if not f:
        return None
    for cat, rx in RULES:
        if re.search(rx, f):
            return cat
    return "autre"


def _read(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def build(con, src: Path | None = FICHES) -> dict:
    """core.fiche_identite: one row per formation whose fiche was read by reader version 3: the establishment badge, grants,
    the label(s) as printed and the category. meta.reconnaissance_audit: counts per category and every label text of
    category "autre" (to extend RULES knowingly)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute("""CREATE OR REPLACE TABLE core.fiche_identite (cod_aff_form VARCHAR, session INTEGER, etab_type VARCHAR,
        bourses BOOLEAN, labels_codes VARCHAR, labels_textes VARCHAR, categorie VARCHAR, source VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE meta.reconnaissance_audit (categorie VARCHAR, n INTEGER, exemple VARCHAR)")
    rows = _read(src / "identite.csv") if src else []
    titles = {}
    if rows:
        try:
            titles = {c: t for c, t in con.execute("""SELECT cod_aff_form, any_value(lib_for_voe_ins) FROM core.formation_year
                GROUP BY cod_aff_form""").fetchall()}
        except Exception:  # noqa: BLE001  (a test warehouse without formations)
            titles = {}
    out, audit = [], {}
    for r in rows:
        textes = [t for t in (r.get("labels_textes") or "").split("|") if t.strip()]
        cats = [categorie(t) for t in textes]
        if cats:
            cat, source = cats[0], "label"
        elif re.search(TITLE_RNCP, fold(titles.get(r["cod_aff_form"]))):
            cat, source = "rncp", "intitule"
        else:
            cat, source = "aucun", "label"
        bourses = {"oui": True, "non": False}.get(r.get("bourses") or "")
        sess = int(r["session"]) if (r.get("session") or "").isdigit() else None
        out.append((r["cod_aff_form"], sess, r.get("etab_type") or None, bourses, r.get("labels_codes") or None,
                    r.get("labels_textes") or None, cat, source))
        a = audit.setdefault(cat, [0, set()])
        a[0] += 1
        if cat == "autre":
            a[1].update(textes)
    if out:
        con.executemany("INSERT INTO core.fiche_identite VALUES (?, ?, ?, ?, ?, ?, ?, ?)", out)
    for cat, (n, ex) in sorted(audit.items()):
        con.execute("INSERT INTO meta.reconnaissance_audit VALUES (?, ?, ?)", [cat, n, " | ".join(sorted(ex))[:2000] or None])
    return {cat: n for cat, (n, _ex) in audit.items()}


def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'core'
        AND table_name = 'fiche_identite'""").fetchone()[0])


def for_formation(con, cod: str) -> dict | None:
    """The badge of one formation: category, its plain name and explanation, the label(s) verbatim, grants."""
    if not _has(con):
        return None
    r = con.execute("""SELECT categorie, source, labels_textes, labels_codes, etab_type, bourses, session
        FROM core.fiche_identite WHERE cod_aff_form = ?""", [cod]).fetchone()
    if not r:
        return None
    cat, source, textes, codes, etab, bourses, sess = r
    return {"categorie": cat, "libelle": LIBELLE[cat], "explication": EXPLICATION[cat], "source": source,
            "labels": [t for t in (textes or "").split("|") if t], "codes": [c for c in (codes or "").split("|") if c],
            "etab_type": etab, "bourses": bourses, "session": sess}


def compact(con, fees: dict | None = None) -> dict:
    """For the lists (search, map, Mes vœux, comparator), read once (no parameter, shared-cached): per category the codes
    whose fiche prints it ("cod,cod,..."), the codes whose fiche says the formation does NOT open the right to grants, and
    the tuition read on the fiche (only where an amount was read). Grouped by category to stay small (~14,000 codes)."""
    out = {"categories": LIBELLE, "explications": EXPLICATION, "codes": {}, "sans_bourse": "", "frais": {}}
    if not _has(con):
        return out
    by: dict = {}
    for c, cat in con.execute("SELECT cod_aff_form, categorie FROM core.fiche_identite ORDER BY cod_aff_form").fetchall():
        by.setdefault(cat, []).append(c)
    out["codes"] = {k: ",".join(v) for k, v in sorted(by.items())}
    out["sans_bourse"] = ",".join(c for (c,) in con.execute(
        "SELECT cod_aff_form FROM core.fiche_identite WHERE bourses = false ORDER BY cod_aff_form").fetchall())
    out["frais"] = {c: m for c, m in (fees or {}).items() if m is not None}
    return out
