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
from . import semblables as SB
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
    def semblable(cod):
        """Where the formation's own report has no bac général table: the estimate from its similar formations' reports."""
        if serie != "bg" or not dkey:
            return None
        b = RP.for_formation(con, cod)
        if b and (b["doublettes"].get("bg") or []):
            return None
        est = SB.estimate(DB.series(con, cod)["bg"], SB.for_formation(con, cod), dkey)
        return {k: v for k, v in est.items() if k != "trend"} if est else None
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
                        "rapport": rapport(c), "semblable": semblable(c)})
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


# ---- "Compléter ma liste" (owner, 2026-11-10): when the list has no SURE safety, safety vœux of the same filières ----
# Plan B's rules, restricted to the zone "sécurité" read with certainty: same detailed programme (fil_lib_voe_acc) as a vœu
# of the list, a solid reading (planb.usable), never a formation already listed or of the same concours pool, fee-charging
# private institutions only on request (flagged), at most 2 per establishment, the student's académie first, then the
# distance to the nearest vœu of that filière. Zones of past admitted cohorts, never a chance.
SUGG_PER_FILIERE = 3


def completer(con, ids: list[str], *, serie: str = "bg", dkey: str | None = None, mention: str = "ab",
              academie: str | None = None, include_paid: bool = False, per_filiere: int = SUGG_PER_FILIERE) -> dict:
    ev = evaluate(con, ids, serie=serie, dkey=dkey, mention=mention, academie=academie)
    needed = any(m["code"] == "aucune_securite" for m in ev["lecture"]["messages"])
    base = {"session": ev["session"], "needed": needed, "include_paid": include_paid, "per_filiere": per_filiere,
            "filieres": [], "hidden_paid": 0}
    if not needed:
        return base
    listed = {v["cod_aff_form"] for v in ev["voeux"]}
    groups = {}
    for v in ev["voeux"]:
        if v["status"] == "ok" and v.get("type_key") and v.get("filiere"):
            groups.setdefault((v["type_key"], v["filiere"]), []).append(v["cod_aff_form"])
    hidden = 0
    for (tk, fil), mine in groups.items():
        rows = J.stage2(con, dkey, mention, tk, academie, serie=serie)["formations"]
        by_cod = {f["cod_aff_form"]: f for f in rows}
        targets = [by_cod[c] for c in mine if c in by_cod]
        pool = []
        for f in rows:
            if f["filiere"] != fil or f["cod_aff_form"] in listed or not PB.usable(f):
                continue
            if f["zone"] != "securite" or f["uncertain"]:
                continue
            if any(PB.same_pool(t, f) for t in targets):
                continue
            if PB.paid(f) and not include_paid:
                hidden += 1
                continue
            kms = [PB.haversine_km((t.get("lat"), t.get("lon")), (f.get("lat"), f.get("lon"))) for t in targets]
            kms = [k for k in kms if k is not None]
            pool.append((f, min(kms) if kms else None))
        pool.sort(key=lambda x: (0 if academie and x[0]["academie"] == academie else 1,
                                 x[1] if x[1] is not None else float("inf"), PB._tiebreak(x[0]["cod_aff_form"])))
        out, per_etab = [], {}
        for f, km in pool:
            key = (f["etablissement"], f["ville"])
            if per_etab.get(key, 0) >= PB.MAX_PER_ETABLISSEMENT:
                continue
            per_etab[key] = per_etab.get(key, 0) + 1
            out.append(PB._view(f, "securite", km))
            if len(out) >= per_filiere:
                break
        fili = next((t.get("fili") for t in targets if t.get("fili")), None)     # "Informatique" is a licence AND a BUT
        base["filieres"].append({"filiere": fil, "fili": fili, "type_key": tk, "pour": mine, "n_candidates": len(pool),
                                 "formations": out})
    base["hidden_paid"] = hidden
    return base
