"""Sprint 11: "Mes vœux", the student's list of up to 10 formations, read for the CURRENT profile.

Every vœu is placed with the "Mon parcours" engine (journey.stage2, restricted to the listed codes:
the same row as the full type, so the zone here is the zone of "Mon parcours" and of Plan B). The list
is read with fixed rules that only COUNT zones: nothing is multiplied or combined, never a chance of
getting at least one vœu (vœux are not independent and these are past admitted cohorts).

The list itself lives in the student's browser. The page sends the codes and the profile, as
"Mon parcours" and Plan B do; nothing is stored or counted on the server (no analytics event here).
"""
from __future__ import annotations

import re

from . import doublettes as DB
from . import rapports as RP
from . import journey as J
from . import planb as PB

MAX_VOEUX = 10                         # Parcoursup: 10 vœux (sub-vœux aside)
CODE = re.compile(r"^\d{1,9}$")
SITUATED = ("securite", "cible", "ambitieux", "hors_profil")
ROW_KEYS = ("cod_aff_form", "etablissement", "ville", "academie", "filiere", "complement", "zone", "uncertain",
            "taux_acces_ens", "taux_acces_all", "serie", "select_form", "rate_fragile", "rare_for_serie",
            "small_cohort", "home_academie", "internat", "apprentissage", "distance", "fiche_url")


def clean_ids(ids: list[str]) -> list[str]:
    """Codes as sent by the page: trimmed, deduplicated in order. ValueError on a bad code or more than 10."""
    out = []
    for c in ids:
        c = c.strip()
        if not c:
            continue
        if not CODE.match(c):
            raise ValueError("code formation invalide")
        if c not in out:
            out.append(c)
    if len(out) > MAX_VOEUX:
        raise ValueError(f"{MAX_VOEUX} vœux au maximum")
    return out


def position(f: dict) -> float | None:
    """'Ta mention ou moins' among the admitted: the bac-série reading when it exists (as Mon parcours)."""
    return f["spos"]["cdf_used"] if f.get("spos") else f.get("cdf")


def evaluate(con, ids: list[str], *, serie: str = "bg", dkey: str | None = None, mention: str = "ab",
             academie: str | None = None) -> dict:
    cods = clean_ids(ids)
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    meta = {}
    if cods:
        for cod, tk, fil, etab, ville, capa in con.execute("""
            SELECT fy.cod_aff_form, r.spe_type_key, fy.fil_lib_voe_acc, fy.g_ea_lib_vx, fy.ville_etab, fy.capa_fin
            FROM core.formation_year fy
            LEFT JOIN core.taxonomy_link t USING (session, cod_aff_form)
            LEFT JOIN core.taxonomy_rule r USING (rule_id)
            WHERE fy.session = ? AND list_contains(?, fy.cod_aff_form)""", [latest, cods]).fetchall():
            meta[cod] = {"type_key": tk, "filiere": fil, "etablissement": etab, "ville": ville, "capa_fin": capa}
    by_type = {}
    for c in cods:
        if c in meta and meta[c]["type_key"]:
            by_type.setdefault(meta[c]["type_key"], []).append(c)
    rows = {}
    for tk, cs in by_type.items():
        for f in J.stage2(con, dkey, mention, tk, academie, serie=serie, only=cs)["formations"]:
            rows[f["cod_aff_form"]] = f
    groups = {tk: DB.for_group(con, tk) for tk in by_type} if serie == "bg" and dkey else {}

    def dbl(tk, cod=None):
        """The student's doublette: the per-formation estimate (this formation's bac général rate x the doublette's ratio in its
        group), with the group's national figure it rests on; no trend here."""
        x = DB.pick(groups.get(tk), dkey)
        if not x:
            return None
        out = {k: v for k, v in x.items() if k != "trend"}
        est = DB.estimate(DB.series(con, cod)["bg"], groups.get(tk), dkey) if cod else None
        out["formation"] = {k: v for k, v in est.items() if k != "trend"} if est else None
        return out
    def rapport(cod):
        if serie != "bg" or not dkey:
            return None
        b = RP.for_formation(con, cod)
        x = RP.pick(b, dkey)
        return {"session": b["session"], "source": x["source"], "taux": x["taux"], "confirmes": x["confirmes"],
                "en_position": x["en_position"], "recoupe": b["recoupe"]} if x else None
    out = []
    for c in cods:
        if c not in meta:
            out.append({"cod_aff_form": c, "status": "absente", "zone": None})
        elif c not in rows:
            out.append({"cod_aff_form": c, "status": "non_situable", "zone": None,
                        **{k: meta[c][k] for k in ("filiere", "etablissement", "ville", "capa_fin")}})
        else:
            f = rows[c]
            out.append({"status": "ok", **{k: f.get(k) for k in ROW_KEYS},
                        "complement": PB._view(f, None)["complement"],      # cleaned exactly as Plan B shows it
                        "position": position(f),
                        "bounds": f["spos"]["bounds"] if f.get("spos") else None, "capa_fin": meta[c]["capa_fin"],
                        "type_key": meta[c]["type_key"], "doublette": dbl(meta[c]["type_key"], c),
                        # sprint "Rapports publics": the formation's OWN published figure for the doublette, when its report exists
                        "rapport": rapport(c)})
    return {"session": latest, "serie": serie, "mention": mention, "doublette": dkey, "academie": academie,
            "max": MAX_VOEUX, "voeux": out, "lecture": read_list(out)}


def read_list(voeux: list[dict]) -> dict:
    """Fixed rules over the zones (counts only, never a combined chance)."""
    z = [v.get("zone") for v in voeux]
    n = {k: z.count(k) for k in (*SITUATED, "indetermine", "non_ouvert")}
    n["non_situe"] = sum(1 for v in voeux if v["status"] != "ok")
    sure = sum(1 for v in voeux if v.get("zone") == "securite" and not v.get("uncertain"))
    situated = sum(n[k] for k in SITUATED)
    msgs = []
    if voeux:
        if not sure:
            msgs.append(("warn", "aucune_securite"))
        if situated and n["ambitieux"] + n["hors_profil"] > situated / 2:
            msgs.append(("warn", "majorite_ambitieuse"))
        if n["hors_profil"]:
            msgs.append(("warn", "hors_profil"))
        if n["non_ouvert"]:
            msgs.append(("warn", "non_ouvert"))
        if n["indetermine"] + n["non_situe"]:
            msgs.append(("info", "non_situe"))
        if situated and not n["cible"]:
            msgs.append(("info", "aucune_cible"))
        if not msgs:
            msgs.append(("info", "equilibree"))
    return {"n": len(voeux), "zones": n, "securite_sure": sure, "situes": situated,
            "messages": [{"niveau": a, "code": b} for a, b in msgs]}
