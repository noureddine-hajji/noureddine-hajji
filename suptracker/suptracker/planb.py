"""Plan B: the same programme elsewhere, more accessible for the student's profile.

For a target formation and a student profile (bac series, specialties for bac général, expected
mention, académie), the formations of the *same detailed programme* (fil_lib_voe_acc) are placed
with the "Mon parcours" engine (journey.stage2), and those that are more accessible for this
profile are proposed. Nothing here is a probability: zones and shares describe past admitted
cohorts, exactly as in "Mon parcours".
"""
from __future__ import annotations

import hashlib
import math

from . import journey as J
from .search import clean_complement, fold

ZONE_RANK = {"hors_profil": 0, "ambitieux": 1, "cible": 2, "securite": 3}
SAME_ZONE_ACCESS_GAIN = 15.0      # points of access needed to call a same-zone formation more accessible
MAX_PER_ETABLISSEMENT = 2
# Private institutions outside the state contract may charge substantial fees: never proposed
# unless the student asks for them (and then flagged). Public and "privé sous contrat
# d'association" (state-paid teachers, low or no fees) are always eligible.
PAID_CONTRACTS = ("Privé enseignement supérieur", "Privé hors contrat")
DEFAULT_LIMIT = 6


def _tiebreak(cod: str) -> str:
    # attribute-neutral: never favours a name, a size or a selectivity level
    return hashlib.blake2b(f"planb|{cod}".encode(), digest_size=8).hexdigest()


def haversine_km(a: tuple | None, b: tuple | None) -> float | None:
    if not a or not b or None in (*a, *b):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _pos(f: dict) -> float | None:
    return f["spos"]["cdf_used"] if f.get("spos") else f.get("cdf")


def usable(f: dict) -> bool:
    """A formation can only be proposed if its reading for this profile is solid."""
    return (f["zone"] in ZONE_RANK and not f.get("rate_fragile") and not f.get("small_cohort")
            and f.get("taux_acces_ens") is not None and _pos(f) is not None)


def why_better(target: dict, c: dict) -> str | None:
    """Why `c` is more accessible than `target` for this profile, or None if it is not."""
    zt, zc = ZONE_RANK.get(target["zone"]), ZONE_RANK[c["zone"]]
    if zt is None:                                  # target not readable: compare nothing
        return None
    if zc > zt and not c["uncertain"]:
        return "zone"
    if zc >= zt and c["taux_acces_ens"] >= (target["taux_acces_ens"] or 0) + SAME_ZONE_ACCESS_GAIN \
            and (_pos(c) or 0) >= (_pos(target) or 0):
        return "acces"
    return None


def same_pool(target: dict, c: dict) -> bool:
    """Schools of one concours commun (sous-vœux of a vœu multiple) share a single applicant pool,
    published under the same complement label: one is not an alternative to another."""
    return bool(target.get("subwish_flag") and c.get("subwish_flag")
                and c.get("complement") and c.get("complement") == target.get("complement"))


def paid(f: dict) -> bool:
    return f.get("contrat_etab") in PAID_CONTRACTS


def plan_b(con, cod: str, *, serie: str = "bg", dkey: str | None = None, mention: str = "ab",
           academie: str | None = None, include_paid: bool = False, limit: int = DEFAULT_LIMIT) -> dict:
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    row = con.execute("""
        SELECT r.spe_type_key, fy.fil_lib_voe_acc, fy.g_ea_lib_vx, fy.lat, fy.lon
        FROM core.formation_year fy
        LEFT JOIN core.taxonomy_link t USING (session, cod_aff_form)
        LEFT JOIN core.taxonomy_rule r USING (rule_id)
        WHERE fy.cod_aff_form = ? AND fy.session = ?""", [cod, latest]).fetchone()
    if row is None:
        raise LookupError(f"formation {cod} absente de la campagne {latest}")
    type_key, filiere, etab, lat, lon = row
    base = {"cod_aff_form": cod, "filiere": filiere, "session": latest, "serie": serie, "mention": mention}
    if type_key is None:
        return {**base, "status": "non_disponible", "reason": "formation non rattachée à un type de filière",
                "target": None, "alternatives": []}
    res = J.stage2(con, dkey, mention, type_key, academie, serie=serie)
    by_cod = {f["cod_aff_form"]: f for f in res["formations"]}
    target = by_cod.get(cod)
    if target is None:
        return {**base, "status": "non_disponible", "reason": "formation absente du positionnement",
                "target": None, "alternatives": []}
    t_view = _view(target, None)
    if target["zone"] not in ZONE_RANK:
        return {**base, "status": "non_disponible", "target": t_view, "alternatives": [],
                "reason": "la formation visée ne peut pas être située pour votre profil "
                          f"({target['zone'].replace('_', ' ')})"}
    if target["zone"] == "securite" and not target["uncertain"]:
        return {**base, "status": "deja_accessible", "target": t_view, "alternatives": [],
                "reason": "la formation visée est déjà un vœu de sécurité pour votre profil"}
    here = (lat, lon)
    pool, hidden_paid = [], 0
    for c in res["formations"]:
        if c["cod_aff_form"] == cod or c["filiere"] != filiere or not usable(c):
            continue
        if same_pool(target, c):
            continue
        reason = why_better(target, c)
        if reason and paid(c) and not include_paid:
            hidden_paid += 1
            continue
        if reason:
            pool.append((c, reason, haversine_km(here, (c["lat"], c["lon"]))))
    pool.sort(key=lambda x: (0 if academie and x[0]["academie"] == academie else 1,
                             x[2] if x[2] is not None else float("inf"),
                             -ZONE_RANK[x[0]["zone"]], _tiebreak(x[0]["cod_aff_form"])))
    out, per_etab = [], {}
    for c, reason, km in pool:
        key = (c["etablissement"], c["ville"])
        if per_etab.get(key, 0) >= MAX_PER_ETABLISSEMENT:
            continue
        per_etab[key] = per_etab.get(key, 0) + 1
        out.append(_view(c, reason, km))
        if len(out) >= limit:
            break
    return {**base, "status": "ok" if out else "aucune", "target": t_view, "alternatives": out,
            "n_candidates": len(pool), "hidden_paid": hidden_paid, "include_paid": include_paid,
            "type_key": type_key,
            "reason": None if out else "aucune formation de la même filière n'est plus accessible pour votre profil"}


def _view(f: dict, reason: str | None, km: float | None = None) -> dict:
    keys = ("cod_aff_form", "etablissement", "ville", "academie", "filiere", "complement", "zone", "uncertain",
            "taux_acces_ens", "taux_acces_all", "serie", "internat", "distance", "apprentissage")
    v = {k: f.get(k) for k in keys}
    v["complement"] = clean_complement({"lib_comp_voe_ins": f.get("complement"), "g_ea_lib_vx": f.get("etablissement"),
                                        "fili": f.get("fili"), "fil_lib_voe_acc": f.get("filiere"),
                                        "form_lib_voe_acc": f.get("form_lib_voe_acc")})
    # the parcours that tells two formations of one programme apart is often only in detail_forma
    detail = f.get("detail_forma")
    if detail and (not v["complement"] or fold(detail) not in fold(v["complement"])):
        v["complement"] = f"{v['complement']} · {detail}" if v["complement"] else detail
    v["contrat_etab"], v["paid"] = f.get("contrat_etab"), paid(f)
    v.update({"position": _pos(f), "bounds": f["spos"]["bounds"] if f.get("spos") else None,
              "why": reason, "km": None if km is None else round(km)})
    return v
