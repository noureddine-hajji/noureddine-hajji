"""The "maillon" (link of the evidence chain, sprint 3): one envelope for every figure a journey
step shows, carrying where it comes from and how far it can be trusted.

The chain is never multiplied into one score: each step describes a different population
(admits of a formation, L1 entrants of a university, graduates of another cohort). The envelope
makes that explicit, so the interface never has to choose its own caveat.

Reliability is graded by fixed rules (no judgement call in the UI):
* A: at least SOLID_N people, a cohort at most RECENT_YEARS old, linked by an official identifier;
* B: at least FRAGILE_N people, or an older cohort, or a link made by name;
* C: fewer than FRAGILE_N people;
* none: the value is masked or unavailable (no grade, no number).
"""
from __future__ import annotations

SOLID_N = 100
FRAGILE_N = 30
RECENT_YEARS = 3
REFERENCE_YEAR = 2025          # latest Parcoursup campaign in the warehouse
GRANULARITY = {   # code -> what the student reads
    "formation": "cette formation",
    "universite_x_discipline": "l'université, même grande discipline",
    "universite": "l'université, toutes spécialités",
    "national": "France entière",
}
LINKS = ("identifiant", "nom", "aucun")


def grade(value, effectif, cohorte, lien: str) -> tuple[str | None, list[str]]:
    """(grade, reasons) under the fixed rules above."""
    if value is None:
        return None, ["valeur masquée ou non publiée"]
    reasons = []
    g = "A"
    if effectif is None or effectif < FRAGILE_N:
        return "C", [f"moins de {FRAGILE_N} personnes" if effectif is not None else "effectif inconnu"]
    if effectif < SOLID_N:
        g = "B"
        reasons.append(f"moins de {SOLID_N} personnes")
    if cohorte is not None and REFERENCE_YEAR - cohorte > RECENT_YEARS:
        g = "B"
        reasons.append(f"cohorte {cohorte}, plus de {RECENT_YEARS} ans")
    if lien != "identifiant":
        g = "B"
        reasons.append("rattachement par le nom de l'établissement")
    return g, reasons or ["effectif suffisant, cohorte récente, identifiant officiel"]


def maillon(etape: str, valeur, *, unite: str = "%", france=None, attendu=None, granularite: str,
            population: str, cohorte, effectif, source: str, lien: str, avertissement: str | None = None) -> dict:
    if granularite not in GRANULARITY:
        raise ValueError(f"granularité inconnue: {granularite}")
    if lien not in LINKS:
        raise ValueError(f"lien inconnu: {lien}")
    g, why = grade(valeur, effectif, cohorte, lien)
    return {"etape": etape, "valeur": valeur, "unite": unite, "reference": {"france": france, "attendu": attendu},
            "granularite": granularite, "granularite_label": GRANULARITY[granularite], "population": population,
            "cohorte": cohorte, "effectif": effectif, "fiabilite": g, "raisons": why, "source": source,
            "lien": lien, "avertissement": avertissement}
