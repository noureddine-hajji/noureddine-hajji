"""Sprint "Carte": the formations on an OpenStreetMap map, filtered like the Parcoursup map (latest campaign).

Two levels of diploma, as the owner asked (2026-11-08): the TYPE of diploma (BTS, BUT, Licence, Double licence, CPGE ECG,
CPGE ECT, CPES...) then its MENTION (BUT Science des données, CPGE ECG Mathématiques appliquées + ESH...). Both are read
from the published labels (fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins) by fixed rules (`diplome_of`).

The neutral layer comes from here. The zones (sécurité / cible / ambitieux) are NEVER computed here: `zones` asks
journey.stage2 for the formations' own types with `only=` their codes, so a zone is exactly the one of "Mon parcours",
Plan B and "Mes vœux". The visitor's position is never sent: the "around a town" filter runs in the browser.
"""
from __future__ import annotations

import re

from . import journey as J
from . import planb as PB

FIELDS = ["cod_aff_form", "etablissement", "formation", "ville", "academie", "lat", "lon", "contrat_etab", "select_form",
          "internat", "distance", "amenag_sport", "amenag_art", "taux_acces_ens", "type_key"]


def statut_of(contrat: str | None) -> str:
    """Parcoursup's three kinds of establishment; the fee-charging private ones (Plan B's rule) are 'prive'."""
    if contrat == "Public":
        return "public"
    if contrat in PB.PAID_CONTRACTS:
        return "prive"
    return "contrat"                      # private under contract with the State (and the EESC)


def diplome_of(fili: str | None, form: str | None, fil: str | None, lib: str | None) -> tuple[str, str]:
    """(type of diploma, mention) of a formation, from its published labels, by fixed rules."""
    fili, form, fil, lib = fili or "", (form or "").strip(), (fil or "").strip(), (lib or "").strip()
    if re.match(r"(?i)double licence", lib):
        m = re.sub(r"(?i)^double licence\s*-\s*", "", lib).strip(" -")
        return "Double licence", m or fil
    if fili == "BTS":
        return "BTS - BTSA - BTSM", fil
    if fili == "BUT":
        return "BUT", fil
    if fili == "Licence_Las":
        return "Licence Accès Santé (L.AS)", fil
    if fili == "PASS":
        return "PASS - Parcours d'accès spécifique santé", fil or "PASS"
    if form.startswith("LP"):
        return "Licence professionnelle", fil
    if fili == "Licence":
        return "Licence", fil
    if form == "Classe préparatoire économique et commerciale":
        if fil.startswith("ECG"):
            return "CPGE ECG", fil.replace("ECG - ", "", 1)
        if fil.startswith("ECT"):
            return "CPGE ECT", fil.replace("ECT - ", "", 1)
        return "CPGE économique (ENS)", fil
    if form == "Classe préparatoire scientifique":
        return "CPGE scientifique", fil
    if form == "Classe préparatoire littéraire":
        return "CPGE littéraire", fil
    if form == "CPES":
        return "CPES", re.sub(r"^Cycle pluridisciplinaire d'Études Supérieures\s*-\s*", "", fil)
    if form.startswith("CUPGE"):
        return "CUPGE", fil
    rules = [(r"^D\.E secteur sanitaire", "Études de santé (diplômes d'État)"), (r"^D\.E secteur social", "Formations du travail social"),
             (r"écoles d'ingénieurs", "Écoles d'ingénieurs"), (r"écoles de commerce", "Écoles de commerce et de management"),
             (r"^Sciences politiques", "Sciences Po - Instituts d'études politiques"), (r"^(Certificat de Spécialisation|FCIL)", "Certificats de spécialisation et FCIL"),
             (r"^(BPJEPS|DEJEPS)", "Formations aux métiers du sport"), (r"(?i)^Diplôme d'(Université|[EÉé]tablissement)", "Diplômes d'université ou d'établissement"),
             (r"écoles supérieures de cuisine", "Formations aux métiers de l'hôtellerie restauration"),
             (r"^(Mise à niveau|Année préparatoire|Classe préparatoire aux études supérieures)", "Formations préparatoires à l'enseignement supérieur"),
             (r"^(DN MADE|Diplôme National d'Art|Formation des écoles supérieures d'art)", "Formations d'art et de design"),
             (r"^C\.M\.I", "C.M.I - Cursus Master en Ingénierie")]
    for pat, label in rules:
        if re.search(pat, form):
            return label, fil
    return form or fili or "Autre formation", fil


def facets(con) -> dict:
    """Every type of diploma and its mentions, with their number of formations in the latest campaign."""
    rows = con.execute("""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins FROM core.formation_year
                          WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    out: dict = {}
    for r in rows:
        d, m = diplome_of(*r)
        x = out.setdefault(d, {"n": 0, "mentions": {}})
        x["n"] += 1
        x["mentions"][m] = x["mentions"].get(m, 0) + 1
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"session": session, "types": type_diplomes(con), "diplomes": [{"label": d, "n": x["n"], "mentions": [{"label": m, "n": n} for m, n in sorted(x["mentions"].items(), key=lambda kv: (-kv[1], kv[0]))]}
                                              for d, x in sorted(out.items(), key=lambda kv: kv[0].lower())]}


def formations(con, diplome: str, mention: str | None = None) -> dict | None:
    rows = con.execute("""
        WITH s AS (SELECT max(session) AS s FROM core.formation_year)
        SELECT f.cod_aff_form, f.g_ea_lib_vx, f.lib_for_voe_ins, f.ville_etab, f.acad_mies, f.lat, f.lon, f.contrat_etab,
               f.select_form, c.internat, c.distance, c.amenag_sport, c.amenag_art, f.taux_acces_ens, r.spe_type_key,
               f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc
        FROM core.formation_year f JOIN s ON f.session = s.s
        LEFT JOIN core.cartographie c ON c.cod_aff_form = f.cod_aff_form
        LEFT JOIN core.taxonomy_link t ON t.cod_aff_form = f.cod_aff_form AND t.session = f.session
        LEFT JOIN core.taxonomy_rule r USING (rule_id)
        ORDER BY f.g_ea_lib_vx, f.cod_aff_form""").fetchall()
    out = []
    for r in rows:
        d, m = diplome_of(r[15], r[16], r[17], r[2])
        if d != diplome or (mention and m != mention):
            continue
        x = dict(zip(FIELDS, r[:15]))
        if x["lat"] is not None:
            x["lat"], x["lon"] = round(x["lat"], 5), round(x["lon"], 5)
        x["mention"], x["statut"] = m, statut_of(x["contrat_etab"])
        x["payant"] = x["statut"] == "prive"
        out.append(x)
    if not out:
        return None
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"diplome": diplome, "mention": mention, "session": session, "formations": out}


def public(lay: dict | None) -> dict | None:
    """What the page reads (the type key only serves the zones, computed here)."""
    if lay is None:
        return None
    return {**lay, "formations": [{k: v for k, v in f.items() if k != "type_key"} for f in lay["formations"]]}


def type_diplomes(con) -> dict:
    """{type_key of "Mon parcours": its most frequent type of diploma}, for the link from Mon parcours to the map."""
    rows = con.execute("""SELECT r.spe_type_key, f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.lib_for_voe_ins
        FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        JOIN core.formation_year f ON f.cod_aff_form = t.cod_aff_form AND f.session = t.session
        WHERE t.session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    count: dict = {}
    for tk, *lab in rows:
        d = diplome_of(*lab)[0]
        count.setdefault(tk, {}).setdefault(d, 0)
        count[tk][d] += 1
    return {tk: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] for tk, c in count.items()}


def zones(con, diplome: str, mention: str | None, dkey: str | None, mention_bac: str, serie: str) -> dict:
    """{code: zone} for the formations of a diploma (and mention): journey.stage2 on each formation's own type, `only` its
    codes, so every zone is the one "Mon parcours" shows. Formations without a type get none."""
    lay = formations(con, diplome, mention)
    if lay is None:
        return {"zones": {}}
    by_type: dict = {}
    for f in lay["formations"]:
        if f["type_key"]:
            by_type.setdefault(f["type_key"], []).append(f["cod_aff_form"])
    out = {}
    for tk, cods in by_type.items():
        for f in J.stage2(con, dkey, mention_bac, tk, None, serie=serie, only=cods)["formations"]:
            out[f["cod_aff_form"]] = f["zone"]
    return {"zones": out}
