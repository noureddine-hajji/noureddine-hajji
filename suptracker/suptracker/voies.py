"""Sprint 20: bac techno and bac pro, "votre ligne" in a formation's public report (owner's go, 2026-11-11).

A verified report (sprint "Rapports publics") prints one table per bac route. For bac général the rows are doublettes, matched
by `doublette_key`. For bac techno the rows are a series with its two terminale specialties ("Msgn/ Mercatique & Droit et
Economie" is STMG, Mercatique); for bac pro they are the bac pro specialty. Both tables end with the formation's own bucket
("Autres doublettes" / "Autres spécialités") for what it does not detail. The reports carry no key for these rows: this module
gives them one, with fixed rules:
  * bac techno: one explicit rule per printed label (BT_RULES). A label no rule knows gets no key (red team W1 lists the
    labels of the warehouse: every one must be known, every rule must match one);
  * bac pro: the printed label, normalised (`bp_key`): accents off, case off, a leading "Bac pro" off, "opt." = "option",
    punctuation and quotes off. Two labels merge only if they differ by these alone (red team W2); a reformed diploma keeps its
    own key (the 2025 "Accompagnement soins et services à la personne" is not one of the old option a / option b labels).
The student's row = the row with their key, else the formation's own bucket, else nothing (`pick_voie`, the twin of
`rapports.pick` for doublettes). A table the formation did not publish (`core.rapport_masque`) gives nothing.
The figures are the report's published counts: en position / confirmés, candidates in terminale in France only. Never a chance.
"""
from __future__ import annotations

import re
import unicodedata

# (key, series, specialties as a student names them, the report label(s) normalised by `norm`)
BT_RULES = [
    ("stmg_merc", "STMG", "Mercatique", ["msgn mercatique droit et economie"]),
    ("stmg_rhc", "STMG", "Ressources humaines et communication", ["msgn ressources humaines et communication droit et economie"]),
    ("stmg_gf", "STMG", "Gestion et finance", ["msgn gestion et finance droit et economie"]),
    ("stmg_sig", "STMG", "Systèmes d'information de gestion", ["msgn systemes d information et de gestion droit et economie"]),
    ("sti2d", "STI2D", "Ingénierie, innovation et développement durable",
     ["physique chimie et mathematiques ingenierie innovation et developpement durable"]),
    ("st2s", "ST2S", "Chimie, biologie et physiopathologie humaines",
     ["sciences et techniques sanitaires et sociales chimie biologie et physiopathologie humaines"]),
    ("stl_bio", "STL", "Biochimie-biologie-biotechnologie", ["physique chimie et mathematiques biochimie biologie biotechnologie"]),
    ("stl_spcl", "STL", "Sciences physiques et chimiques en laboratoire",
     ["sciences physiques et chimiques en laboratoire physique chimie et mathematiques"]),
    ("std2a", "STD2A", "Design et métiers d'art",
     ["conception et creation en design et metiers d art analyse et methodes en design"]),
    ("stav", "STAV", "Agronomie, alimentation, environnement, territoires",
     ["gestion des ressources et alimentation territoires et technologie"]),
    ("sthr", "STHR", "Hôtellerie et restauration",
     ["economie et gestion hoteliere sciences et technologies culinaires et services esae"]),
    ("s2tmd_musique", "S2TMD", "Musique", ["culture et sciences musicale pratique musicale"]),
    ("s2tmd_danse", "S2TMD", "Danse", ["culture et sciences choregraphiques pratique choregraphiques"]),
]
BT_BY_LABEL = {lab: key for key, _, _, labs in BT_RULES for lab in labs}
BT_NAME = {key: (serie, spe) for key, serie, spe, _ in BT_RULES}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def bp_key(label: str) -> str | None:
    k = norm(label)
    k = re.sub(r"^bac pro\b ?", "", k)
    k = re.sub(r"\bopt\b", "option", k)
    return k or None


def voie_key(bac: str, label: str, autres: bool = False) -> str | None:
    """The key of a report row of bac techno or pro; None for the formation's own bucket and for an unknown techno label."""
    if autres:
        return None
    if bac == "bt":
        return BT_BY_LABEL.get(norm(label))
    if bac == "bp":
        return bp_key(label)
    return None


def pick_voie(block: dict | None, bac: str, key: str | None) -> dict | None:
    """The student's row in THIS formation's report for bac techno or pro: the row with their key, else the formation's own
    bucket; nothing when the route's table is not published or the student gave no series / specialty."""
    if not block or bac not in ("bt", "bp") or not key:
        return None
    rows = block["doublettes"].get(bac) or []
    mine = next((x for x in rows if x.get("voie") == key), None)
    if mine:
        return {**mine, "source": "voie"}
    other = next((x for x in rows if x["autres"]), None)
    return {**other, "source": "autres"} if other else None


def choices(con) -> dict:
    """What a student can choose: the techno series and specialties of BT_RULES, the bac pro specialties the reports detail,
    each with the number of formations whose latest verified report prints its row (latest session read)."""
    try:
        rows = con.execute("""SELECT d.bac, d.libelle, count(DISTINCT d.cod_aff_form) FROM core.rapport_doublette d
            WHERE d.bac IN ('bt', 'bp') AND NOT d.autres AND d.session = (SELECT max(session) FROM core.rapport)
            GROUP BY 1, 2""").fetchall()
    except Exception:  # noqa: BLE001 - a warehouse built before the reports
        rows = []
    bt: dict[str, int] = {}
    bp: dict[str, dict] = {}
    for bac, lab, n in rows:
        k = voie_key(bac, lab)
        if bac == "bt" and k:
            bt[k] = bt.get(k, 0) + n
        elif bac == "bp" and k:
            x = bp.setdefault(k, {"n": 0, "labels": {}})
            x["n"] += n
            x["labels"][lab] = x["labels"].get(lab, 0) + n
    def clean(s):
        s = re.sub(r"^\s*bac pro\s+", "", s, flags=re.I).strip()
        return s[:1].upper() + s[1:]
    return {
        "bt": [{"code": k, "serie": s, "label": f"{s}, {p}", "n": bt[k]} for k, s, p, _ in BT_RULES if k in bt],
        "bp": sorted(({"code": k, "label": clean(max(x["labels"].items(), key=lambda kv: (kv[1], kv[0]))[0]), "n": x["n"]}
                      for k, x in bp.items()), key=lambda d: norm(d["label"])),
    }
