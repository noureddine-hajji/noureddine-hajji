"""Préparer son projet de formation motivé (owner, 2026-11-10): the points to check, from what the jury itself wrote.

The "projet de formation motivé" is the short text (1 500 characters) Parcoursup asks for each vœu. A formation's public report
lists the jury's criteria, each with the elements it is judged on and its importance. The points to check are the criteria whose
elements or wording name the projet motivé (or the lettre de motivation that preceded it), quoted VERBATIM and ordered by the
jury's importance; the lines of the eliminating criteria that name it; and the jury's advice. Nothing is written for the student,
nothing is scored, nothing is promised: the fiche Parcoursup prevails.

Without readable texts in the formation's own report, the similar formations' reports (semblables) give COUNTS: how many cite the
projet motivé, and under which field and importance (precomputed at build in mart.semblable_jury). Never the criteria of another
formation shown as this one's.
"""
from __future__ import annotations

import json
import re

# a criterion "reads" the projet motivé when its wording or the elements it is judged on name it
PROJET = re.compile(r"(?i)projet\s+(?:de\s+formation\s+)?motiv|lettre\s+de\s+motiv|\bpfm\b|projet\s+de\s+formation")
IMPORTANCES = ("Essentiel", "Très important", "Important", "Complémentaire")
MAX_ELIM = 6                     # lines quoted from the eliminating criteria
MAX_LINE = 400


def cites(c: dict) -> bool:
    return bool(PROJET.search(f"{c.get('critere') or ''} {c.get('elements') or ''}"))


def _rank(c: dict) -> int:
    imp = c.get("importance")
    return IMPORTANCES.index(imp) if imp in IMPORTANCES else len(IMPORTANCES)


def checklist(textes: dict | None) -> dict | None:
    """The points of a report's texts (verbatim), or None when the report has no readable criteria."""
    if not textes:
        return None
    crit = [c for c in (textes.get("criteres") or []) if (c.get("critere") or c.get("elements"))]
    if not crit:
        return None
    pts = [c for c in crit if cites(c)]
    pts = [p for _, p in sorted(enumerate(pts), key=lambda x: (_rank(x[1]), x[0]))]      # importance, then the jury's order
    elim = [ln.strip()[:MAX_LINE] for ln in (textes.get("eliminatoires") or "").splitlines() if PROJET.search(ln)][:MAX_ELIM]
    return {"points": [{k: c.get(k) or "" for k in ("champ", "critere", "elements", "importance")} for c in pts],
            "n_criteres": len(crit), "autres_criteres": len(crit) - len(pts), "eliminatoires": elim,
            "conseils": (textes.get("conseils") or "").strip()}


def similar_counts(texts: list[dict]) -> dict:
    """Counts over similar formations' reports (build time): how many cite the projet motivé, per field and importance."""
    from . import semblables as SB
    champs = {k: dict.fromkeys(IMPORTANCES, 0) | {"": 0} for k, _, _ in SB.CHAMPS}
    n_cite = 0
    for t in texts:
        best = {}
        for c in t.get("criteres") or []:
            if not cites(c):
                continue
            k = SB.champ_of(c.get("champ"))
            if not k:
                continue
            imp = c.get("importance") if c.get("importance") in IMPORTANCES else ""
            if k not in best or (IMPORTANCES + ("",)).index(imp) < (IMPORTANCES + ("",)).index(best[k]):
                best[k] = imp
        if best:
            n_cite += 1
        for k, imp in best.items():
            champs[k][imp] += 1
    return {"n_cite": n_cite, "champs": champs}


def for_formation(con, cod: str, session: int | None = None) -> dict | None:
    from . import rapports as RP
    from . import semblables as SB
    rp = RP.for_formation(con, cod, session)
    own = checklist(rp["textes"]) if rp else None
    if own:
        return {"source": "rapport", "session": rp["session"], "recoupe": rp["recoupe"], "live": rp["source"] == "live",
                "archive": rp["archive"], "capture": rp["capture"], **own}
    sem = SB.for_formation(con, cod, session)
    jury = (sem or {}).get("jury") or {}
    pj = jury.get("projet")
    if not pj:
        return None
    return {"source": "semblables", "session": sem["session"], "n_rapports": jury["n"], "n_cite": pj["n_cite"],
            "champs": [{"key": k, "label": SB.CHAMP_LABEL[k], "n": sum(v.values()), "importances": v}
                       for k, v in pj["champs"].items() if sum(v.values())],
            "filiere": sem["filiere"], "fili": sem["fili"], "formations": sem["formations"]}


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
