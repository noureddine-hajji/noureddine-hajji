"""Sprint "Carte": the formations on an OpenStreetMap map, filtered like the Parcoursup map (latest campaign).

Two levels of diploma, as the owner asked (2026-11-08): the TYPE of diploma (BTS, BUT, Licence, Double licence, CPGE ECG,
CPGE ECT, CPES...) then its MENTION (BUT Science des données, CPGE ECG Mathématiques appliquées + ESH...). Both are read
from the published labels (fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins) by fixed rules (`diplome_of`).

The neutral layer comes from here. The zones (sécurité / cible / ambitieux) are NEVER computed here: `zones` asks
journey.stage2 for the formations' own types with `only=` their codes, so a zone is exactly the one of "Mon parcours",
Plan B and "Mes vœux". The visitor's position is never sent: the "around a town" filter runs in the browser.

Apprenticeship (owner's request, 2026-11-08): SIES publishes no statistics for apprenticeship offers after 2022 (they have
their own codes, absent from the vœux files), so the map adds them from the Parcoursup CARTOGRAPHIE, latest session, as
listed offers only: no zone, no access rate, no "Mes vœux" (which reads SIES rows); the page links to their Parcoursup page.
Their type of diploma and mention are those of the SIES formations that carry the SAME cartographie labels (a vote,
`label_votes`), their académie that of their establishment (UAI), else of their département. Apprenticeship training is free
for the apprentice (Code du travail, art. L6211-1): a private establishment outside State contract is "prive_app", never the
fee-charging "prive" of Plan B's rule.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

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


def statut_carto(types_etab: str | None) -> str | None:
    """The cartographie's three kinds of establishment, for an apprenticeship offer (free for the apprentice)."""
    t = (types_etab or "").strip()
    if t == "Publics":
        return "public"
    if "contrat" in t:
        return "contrat"
    if t.startswith("Priv"):
        return "prive_app"
    return None


def _fold(x: str | None) -> str:
    return unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower().strip()


FICHE_PREFIX = "https://dossierappel.parcoursup.fr/"


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


def _has_labels(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
                               AND table_name = 'cartographie' AND column_name = 'type_formation'""").fetchone()[0])


def label_votes(con) -> tuple[dict, dict]:
    """{(type_formation, mention_lib): (type, mention)} and {type_formation: type}: the most frequent reading among the SIES
    formations of the latest campaign that carry these cartographie labels (ties: alphabetical)."""
    rows = con.execute("""SELECT c.type_formation, c.mention_lib, f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.lib_for_voe_ins
        FROM core.formation_year f JOIN core.cartographie c USING (cod_aff_form)
        WHERE f.session = (SELECT max(session) FROM core.formation_year) AND c.type_formation IS NOT NULL""").fetchall()
    pair, typ = {}, {}
    for tf, fl, *lab in rows:
        dm = diplome_of(*lab)
        pair.setdefault((tf, fl), Counter())[dm] += 1
        typ.setdefault(tf, Counter())[dm[0]] += 1
    best = lambda c: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]  # noqa: E731
    return {k: best(v) for k, v in pair.items()}, {k: best(v) for k, v in typ.items()}


def _type_of(tf: str | None, typ: dict) -> str:
    """A cartographie type no SIES formation carries as a whole: a list "A,B" takes its first part SIES knows, else its
    first part; any other label is kept as published."""
    if tf in typ:
        return typ[tf]
    parts = [x.strip() for x in (tf or "").split(",") if x.strip()]
    return next((typ[x] for x in parts if x in typ), parts[0] if parts else "Autre formation")


def apprentissage(con) -> list[dict]:
    """The apprenticeship offers of the latest cartographie session that SIES does not publish (no statistics)."""
    if not _has_labels(con):
        return []
    rows = con.execute("""
        SELECT c.cod_aff_form, c.etab_nom, c.nom_long, c.commune, c.departement, c.etab_uai, c.lat, c.lon, c.types_etab,
               c.type_formation, c.mention_lib, c.internat, c.distance, c.amenag_sport, c.amenag_art, c.fiche_url, c.carto_session
        FROM core.cartographie c
        WHERE c.apprentissage AND c.carto_session = (SELECT max(carto_session) FROM core.cartographie)
          AND c.cod_aff_form NOT IN (SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year))
        ORDER BY c.etab_nom, c.cod_aff_form""").fetchall()
    if not rows:
        return []
    pair, typ = label_votes(con)
    acad_rows = con.execute("""SELECT cod_uai, dep_lib, acad_mies FROM core.formation_year
                               WHERE session = (SELECT max(session) FROM core.formation_year) AND acad_mies IS NOT NULL""").fetchall()
    by_uai, by_dep = {}, {}
    for uai, dep, ac in acad_rows:
        by_uai.setdefault(uai, Counter())[ac] += 1
        by_dep.setdefault(_fold(dep), Counter())[ac] += 1
    top = lambda c: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if c else None  # noqa: E731
    out = []
    for (cod, etab, nom, commune, dep, uai, lat, lon, tc, tf, fl, internat, distance, sport, art, fiche, sess) in rows:
        d, m = pair.get((tf, fl)) or (_type_of(tf, typ), fl or "")
        out.append({"cod_aff_form": cod, "etablissement": etab or "", "formation": nom or fl or "", "ville": commune or "",
                    "academie": top(by_uai.get(uai)) or top(by_dep.get(_fold(dep))),
                    "lat": None if lat is None else round(lat, 5), "lon": None if lon is None else round(lon, 5),
                    "contrat_etab": tc, "select_form": None, "internat": internat, "distance": distance, "amenag_sport": sport,
                    "amenag_art": art, "taux_acces_ens": None, "type_key": None, "diplome": d, "mention": m,
                    "statut": statut_carto(tc), "payant": False, "apprentissage": True, "stats": False, "session_offre": sess,
                    "fiche": fiche if (fiche or "").startswith(FICHE_PREFIX) else None})
    return out


def facets(con) -> dict:
    """Every type of diploma and its mentions, with their number of formations in the latest campaign (and the current
    apprenticeship offers)."""
    rows = con.execute("""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins FROM core.formation_year
                          WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    out: dict = {}
    for r in [diplome_of(*r) for r in rows] + [(a["diplome"], a["mention"]) for a in apprentissage(con)]:
        d, m = r
        x = out.setdefault(d, {"n": 0, "mentions": {}})
        x["n"] += 1
        x["mentions"][m] = x["mentions"].get(m, 0) + 1
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"session": session, "offre_apprentissage": _offer_session(con), "types": type_diplomes(con), "diplomes": [{"label": d, "n": x["n"], "mentions": [{"label": m, "n": n} for m, n in sorted(x["mentions"].items(), key=lambda kv: (-kv[1], kv[0]))]}
                                              for d, x in sorted(out.items(), key=lambda kv: kv[0].lower())]}


def _offer_session(con):
    return con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0] if _has_labels(con) else None


def formations(con, diplome: str, mention: str | None = None) -> dict | None:
    rows = con.execute("""
        WITH s AS (SELECT max(session) AS s FROM core.formation_year)
        SELECT f.cod_aff_form, f.g_ea_lib_vx, f.lib_for_voe_ins, f.ville_etab, f.acad_mies, f.lat, f.lon, f.contrat_etab,
               f.select_form, c.internat, c.distance, c.amenag_sport, c.amenag_art, f.taux_acces_ens, r.spe_type_key,
               f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.apprentissage
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
        x["apprentissage"], x["stats"], x["fiche"] = bool(r[18]), True, None
        if x["apprentissage"] and x["statut"] == "prive":
            x["statut"] = "prive_app"         # free for the apprentice: never the fee-charging rule
        x["payant"] = x["statut"] == "prive"
        out.append(x)
    out += [{k: v for k, v in a.items() if k != "diplome"} for a in apprentissage(con)
            if a["diplome"] == diplome and (not mention or a["mention"] == mention)]
    if not out:
        return None
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return {"diplome": diplome, "mention": mention, "session": session, "offre_apprentissage": _offer_session(con), "formations": out}


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
