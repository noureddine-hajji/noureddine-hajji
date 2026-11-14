"""From each job to the Parcoursup formations where its studies START (owner, 2026-11-14).

The job page listed only the Parcoursup formations that prepare a diploma Onisep ties to the job: 331 of the 1,124 jobs had
one, and none of the long-study jobs (pédiatre: "DE de docteur en médecine", which nobody tied to PASS or LAS). What Onisep
publishes, checked on the real files (Idéo-Fiches, 2026-09-15):
  * each job sheet names the diploma(s) REQUIRED (`formations_min_requise`, 987 jobs) and its minimum level;
  * each diploma sheet lists its continuations (`poursuites_etudes`: BTS -> licence pro, licence -> master...) and says in words
    how one gets in (`descriptif_acces`: "il faut obligatoirement passer par une année de sélection universitaire (PASS ou LAS)").
So a route is read BACKWARDS, from the required diploma to a formation of the latest Parcoursup campaign, with fixed rules:
  1. direct: the required diploma itself is a Parcoursup formation (onisep.match: BTS, BUT, licence, LAS, IFSI, EFTS);
  2. graph: Onisep's continuation links, followed backwards (at most MAX_DEPTH steps) up to a diploma that is a Parcoursup
     formation; the chain is shown (licence -> master);
  3. family rules (FAMILY_RULES): the official entries of the diplomas Onisep does not chain to Parcoursup, one rule per family,
     each written from Onisep's own access text (médecine, pharmacie, odontologie, maïeutique: PASS or LAS; engineering schools:
     post-bac schools and scientific CPGE; business schools; architecture; IEP; DN MADE; art schools; paramedical state diplomas
     to their own Parcoursup programme; comptabilité; law professions: a law licence; a master with the same name as a licence).
Every entry is a GROUP of Parcoursup formations of the latest campaign (a diploma's formations, or a programme), with its count
and its places (`capa_fin`). On each job page the entries are ranked by places and the first ones that gather 80 % of them are
shown open ("voies principales"), the rest folded: the places are a proxy, no open data counts who reached a job by which route.
A job whose minimum level is the bac or below needs no higher studies: the page says so and links the Onisep sheet of the
diploma that leads to it (outside Parcoursup); the routes, if any, are offered "pour aller plus loin".
Coverage is measured at build (`core.parcours_mesure`): among the jobs that need higher studies, the share with at least one
route; the red team fails below 80 %.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path

from . import onisep as ON

MAX_DEPTH = 4
MAIN_SHARE = 0.80
CPGE_SCIENCE = ("MPSI", "PCSI", "PTSI", "MP2I", "BCPST", "TSI", "TPC", "TB")
CPGE_ECO = ("ECG", "ECT")

# (rule id, what it applies to: Onisep sheet type or label regex, Parcoursup groups: (fili, fil_lib regex or None, form_lib
# regex or None), the sentence shown, i.e. what Onisep's access text says). Fixed, explicit, one line per family.
FAMILY_RULES = [
    ("sante_mmopk", ("label", r"docteur en (?:medecine|pharmacie|chirurgie dentaire)|sage femme|maieutique"),
     [("PASS", None, None), ("Licence_Las", None, None)],
     "Les études de médecine, pharmacie, odontologie et maïeutique commencent par une année de PASS ou de LAS, sur Parcoursup."),
    ("kine", ("label", r"masseur kinesitherapeute|kinesitherapie"),
     [("PASS", None, None), ("Licence_Las", None, None), ("Licence", r"STAPS|Sciences et techniques des activit", None)],
     "Les instituts de kinésithérapie recrutent après une première année de PASS, de LAS ou de licence STAPS."),
    # one rule per paramedical profession, to ITS OWN programme only (Codex: a shared rule sent the orthophonie certificate to
    # ergotherapy, podiatry and radiography institutes as well)
    ("para_ergo", ("label", r"ergotherapeute"), [("Autre formation", r"Ergoth", None)],
     "Le diplôme d'État d'ergothérapeute se prépare dans des instituts qui recrutent sur Parcoursup."),
    ("para_psychomot", ("label", r"psychomotricien"), [("Autre formation", r"Psychomot", None)],
     "Le diplôme d'État de psychomotricien se prépare dans des instituts qui recrutent sur Parcoursup."),
    ("para_podo", ("label", r"pedicure podologue"), [("Autre formation", r"Pédicure", None)],
     "Le diplôme d'État de pédicure-podologue se prépare dans des instituts qui recrutent sur Parcoursup."),
    ("para_radio", ("label", r"electroradiologie|imagerie medicale"), [("Autre formation", r"manipulateur|Imagerie médicale", None)],
     "Les manipulateurs en électroradiologie se forment en institut (DE) ou en lycée (DTS), sur Parcoursup."),
    ("para_ortho", ("label", r"orthophoniste"), [("Autre formation", r"Orthophon", None)],
     "Le certificat de capacité d'orthophoniste se prépare dans des centres universitaires qui recrutent sur Parcoursup."),
    ("para_orthopt", ("label", r"orthoptiste"), [("Autre formation", r"Orthopt", None)],
     "Le certificat de capacité d'orthoptiste se prépare dans des centres universitaires qui recrutent sur Parcoursup."),
    ("para_audio", ("label", r"audioprothesiste"), [("Autre formation", r"Audioprot", None)],
     "Le diplôme d'État d'audioprothésiste se prépare dans des écoles qui recrutent sur Parcoursup."),
    ("veterinaire", ("label", r"docteur veterinaire"),
     [("Autre formation", r"^Formation Bac\+6", r"(?i)v[ée]t[ée]rinaire"), ("CPGE", r"^BCPST$|^TB$", None)],
     "Les écoles nationales vétérinaires recrutent après le bac (sur Parcoursup) ou après une prépa BCPST ou TB."),
    ("ingenieur", ("label_or_type", r"^diplome d ingenieur|\bingenieur (?:du|de l|des|en|civil)\b|^ingenierie"),
     [("Ecole d'Ingénieur", r"ingénieur", None), ("CPGE", "|".join(CPGE_SCIENCE), None)],
     "On entre en école d'ingénieurs après le bac (cycle préparatoire intégré, sur Parcoursup) ou après une prépa scientifique ; "
     "des admissions parallèles existent après un BUT ou une licence."),
    ("commerce", ("type", r"^diplome d ecole de commerce vise"),
     [("Ecole de Commerce", None, None), ("CPGE", "|".join(CPGE_ECO), None)],
     "On entre en école de commerce après le bac (sur Parcoursup) ou après une prépa économique et commerciale ; "
     "des admissions parallèles existent après un bac + 2 ou + 3."),
    # building architecture only: "architecte réseaux", "architecture logicielle" are computing (Codex)
    ("architecture", ("label_or_type", r"^diplome des ecoles d architecture|\barchitecte?\b|\barchitecture\b",
                      r"reseau|logiciel|informati|systeme|cloud|donnee|cyber|application|numerique|\bdata\b|securite|solution|\bsi\b"),
     [("Autre formation", r"^Architecture", None)],
     "Les écoles nationales d'architecture recrutent sur Parcoursup."),
    ("iep", ("type", r"^diplome d iep"), [("Autre formation", r"Sciences Po", None)],
     "Les instituts d'études politiques recrutent après le bac, sur Parcoursup ou par leur concours."),
    ("dnmade", ("label_or_type", r"^diplome national des metiers d art et du design|^dn made"), [("Autre formation", None, r"^DN MADE")],
     "Le DN MADE se prépare après le bac, sur Parcoursup."),
    ("art", ("type", r"^diplome (?:d etat en art|national superieur professionnel|d etablissement en art)"),
     [("Autre formation", r"Diplôme National d'Art|écoles supérieure d'art", None)],
     "Les écoles supérieures d'art recrutent après le bac, sur Parcoursup ou sur concours."),
    ("comptabilite", ("label", r"comptab|expertise comptable|\bdscg\b|\bdcg\b"),
     [("Autre formation", r"Comptabilité et de Gestion", None)],
     "La filière comptable commence par le DCG, qui se prépare après le bac sur Parcoursup."),
    ("droit", ("label", r"avocat|magistrat|notari|commissaire de justice|huissier|greffier"), [("Licence", r"^Droit", None)],
     "Les professions du droit demandent une licence puis un master de droit avant leur école ou leur concours."),
]
RULE_TEXT = {rid: text for rid, _f, _g, text in FAMILY_RULES}
SEARCH = {"PASS": "PASS", "Licence_Las": "LAS", "Ecole de Commerce": "école de commerce", "Ecole d'Ingénieur": "école d'ingénieurs"}
FIL_LABEL = {"PASS": "PASS (parcours d'accès spécifique santé)", "Licence_Las": "LAS (licence accès santé)"}


def _fold(s: str | None) -> str:
    return ON.fold(s or "")


def read_sources(sources: dict) -> tuple[dict, dict]:
    """(diplomas, jobs, neighbours) from the Idéo-Fiches XML: diplomas {for_id: {lib, type, niveau, suite: [for_id]}}, jobs
    {met_id: [for_id]} (the diplomas each job sheet names as required), neighbours {met_id: [met_id]} (its "métiers associés")."""
    forms, jobs, near, acces = {}, {}, {}, {}
    root = ON._xml_root(sources["formations"]) if sources.get("formations") else None
    for f in (root if root is not None else []):
        fid = f.findtext("identifiant")
        forms[fid] = {"lib": f.findtext("libelle_complet") or "", "type": f.findtext("type_Formation/type_formation_libelle") or "",
                      "niveau": f.findtext("niveau_etudes/libelle"),
                      "suite": [x.get("id") for x in f.findall("poursuites_etudes/poursuite_etudes/formation_poursuite_Etudes") if x.get("id")]}
    root = ON._xml_root(sources["metiers"]) if sources.get("metiers") else None
    for m in (root if root is not None else []):
        mid = m.findtext("identifiant")
        jobs[mid] = [x.findtext("id") for x in m.findall("formations_min_requise/formation_min_requise") if x.findtext("id")]
        near[mid] = [x.findtext("id") for x in m.findall("metiers_associes/metier_associe") if x.findtext("id")]
        acces[mid] = plain(m.findtext("acces_metier"))
    return forms, jobs, near, acces


def plain(html: str | None) -> str:
    """Onisep's HTML text as plain paragraphs (tags out, entities decoded, one paragraph per line); escaped by the page."""
    import html as H
    t = re.sub(r"(?i)<\s*(?:br|/p|/h\d|/li)\s*/?>", "\n", html or "")
    t = H.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(" ".join(x.split()) for x in t.split("\n") if x.strip())


def rule_of(sheet: dict) -> tuple | None:
    """The family rule a diploma sheet falls under, or None (first match in FAMILY_RULES)."""
    for rid, (field, rx, *excl), groups, text in FAMILY_RULES:
        vals = [sheet["lib"]] if field == "label" else [sheet["type"]] if field == "type" else [sheet["lib"], sheet["type"]]
        folded = [_fold(v) for v in vals]                        # no accent, no apostrophe, no hyphen
        if any(re.search(rx, v) for v in folded) and not any(re.search(x, v) for x in excl for v in folded):
            return rid, groups, text
    return None


def master_rule(sheet: dict, licences: list[str]) -> tuple | None:
    """A master whose mention IS, or else CONTAINS, the name of a Parcoursup licence: that licence ("master mention cinéma et
    audiovisuel" -> licence "Cinéma et audiovisuel"). A contained name has at least two words or 8 letters."""
    if _fold(sheet["type"]) != "master":
        return None
    mention = re.sub(r"^master (?:mention )?", "", _fold(sheet["lib"]))
    # the licence of the SAME name first; else a licence whose name is CONTAINED in the mention (never the reverse: "master
    # mention mathématiques" is not the double licence "Économie, Mathématiques"; red team PA3)
    named = [(lic, _fold(lic)) for lic in licences]
    hits = [lic for lic, f in named if f == mention] or \
        [lic for lic, f in named if f and (len(f.split()) >= 2 or len(f) >= 8) and f" {f} " in f" {mention} "]
    if not hits:
        return None
    return (f"master:{hits[0]}", [("Licence", "^" + re.escape(h) + "$", None) for h in hits],
            "Un master se prépare après une licence du même domaine.")


def _groups(con, session: int) -> dict:
    """Every Parcoursup programme of the campaign: {(fili, fil_lib, form_lib): (codes, places)}."""
    out = defaultdict(lambda: [[], 0])
    for cod, fili, fil, form, capa in con.execute("""SELECT cod_aff_form, fili, fil_lib_voe_acc, form_lib_voe_acc, capa_fin
            FROM core.formation_year WHERE session = ?""", [session]).fetchall():
        g = out[(fili, fil or "", form or "")]
        g[0].append(cod)
        g[1] += capa or 0
    return out


def build(con, sources: dict | None = None) -> dict:
    """core.parcours_entree (one row per entry: a Parcoursup group, its count and places), core.parcours_metier (per job: status
    and routes, JSON), core.parcours_mesure (coverage)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.parcours_entree (entree VARCHAR, libelle VARCHAR, kind VARCHAR, fili VARCHAR,
        n_formations INTEGER, places INTEGER, recherche VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE core.parcours_metier (met_id VARCHAR, statut VARCHAR, data VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.parcours_mesure (a_besoin INTEGER, couverts INTEGER, couverture DOUBLE,
        sans_postbac INTEGER, hors_parcoursup INTEGER, directs INTEGER, graphe INTEGER, regles INTEGER, voisins INTEGER)""")
    sources = ON.find_sources() if sources is None else sources
    if not (sources.get("formations") and sources.get("metiers")) or not ON._has(con, "onisep_metier"):
        return {"status": "no source"}
    forms, req, near, acces = read_sources(sources)
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    groups = _groups(con, session)
    capa = dict(con.execute("SELECT cod_aff_form, capa_fin FROM core.formation_year WHERE session = ?", [session]).fetchall())
    linked = defaultdict(set)
    for fid, cod in con.execute("SELECT for_id, cod_aff_form FROM core.onisep_link WHERE session = ?", [session]).fetchall():
        linked[fid].add(cod)
    pred = defaultdict(set)
    for a, f in forms.items():
        for b in f["suite"]:
            pred[b].add(a)

    entries: dict = {}
    counted: set = set()

    def entry_sheet(fid):
        key = f"onisep:{fid}"
        if key not in entries:
            cods = sorted(linked[fid])
            entries[key] = (forms[fid]["lib"] if fid in forms else fid, "diplome", None, len(cods),
                            sum(capa.get(c) or 0 for c in cods), forms[fid]["lib"] if fid in forms else "")
        return key

    def entry_rule(fili, fil_rx, form_rx):
        keys = []
        for (gf, fil, form), (cods, places) in groups.items():
            if gf != fili or (fil_rx and not re.search(fil_rx, fil)) or (form_rx and not re.search(form_rx, form)):
                continue
            whole = not fil_rx and not form_rx            # a whole filière (PASS, LAS, business schools): one entry
            key = f"ps:{gf}" if whole else f"ps:{gf}:{fil}:{form}" if form_rx else f"ps:{gf}:{fil}"
            lab = FIL_LABEL.get(gf) or (gf if whole else f"CPGE {fil}" if gf == "CPGE" else f"{form} {fil}".strip() if form_rx else fil)
            if (key, gf, fil, form) in counted:            # the same programme reached by another rule: counted once
                keys.append(key)
                continue
            counted.add((key, gf, fil, form))
            if key in entries:                              # a programme split over several form labels: add up
                old = entries[key]
                entries[key] = (old[0], old[1], old[2], old[3] + len(cods), old[4] + places, old[5])
            else:
                entries[key] = (lab, "programme", gf, len(cods), places, SEARCH.get(gf) if whole else fil if gf == "CPGE" else lab)
            keys.append(key)
        return sorted(set(keys))

    licences = sorted({fil for (gf, fil, _form) in groups if gf == "Licence" and fil})
    rule_cache: dict = {}
    rows, stats = [], defaultdict(int)
    names = dict(con.execute("SELECT met_id, niveau_rang FROM core.onisep_metier").fetchall())
    noms = dict(con.execute("SELECT met_id, nom FROM core.onisep_metier").fetchall())
    listing = defaultdict(list)
    for fid, mid in con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall():
        listing[mid].append(fid)
    def routes_of(targets):
        routes = {}                                         # entry -> best route (shortest chain)

        def add(entry, chain, how, rule=None):
            r = routes.get(entry)
            if r is None or len(chain) < len(r["etapes"]):
                routes[entry] = {"entree": entry, "etapes": chain, "comment": how, "regle": rule}

        for t in targets:
            seen, queue = {t}, deque([(t, [])])
            while queue:                                    # backwards through the continuations
                node, after = queue.popleft()
                chain = [node] + after                     # node -> ... -> target
                if linked.get(node):
                    add(entry_sheet(node), chain[1:], "direct" if node == t else "graphe")
                    continue                               # a Parcoursup diploma ends the branch
                hit = rule_of(forms[node]) or master_rule(forms[node], licences)
                if hit:
                    rid, gs, _text = hit
                    if rid not in rule_cache:
                        rule_cache[rid] = sorted({k for g in gs for k in entry_rule(*g)})
                    for k in rule_cache[rid]:
                        add(k, chain, "regle", rid)
                    continue
                if len(chain) > MAX_DEPTH:
                    continue
                for p in pred.get(node, ()):
                    if p not in seen and p in forms:
                        seen.add(p)
                        queue.append((p, chain))
        return routes

    first = {}
    for mid in names:
        # the diplomas the job sheet requires; else the diplomas whose sheets name the job
        targets = [t for t in req.get(mid) or [] if t in forms] or [t for t in listing.get(mid) or [] if t in forms]
        first[mid] = (targets, routes_of(targets))
    for mid, rank in names.items():
        targets, routes = first[mid]
        voisins = []
        if not targets:                                     # no diploma at all: the family rule of the job's own name,
            hit = rule_of({"lib": noms.get(mid) or "", "type": ""})   # e.g. "expert-comptable" -> DCG
            if hit:
                rid, gs, _text = hit
                if rid not in rule_cache:
                    rule_cache[rid] = sorted({k for g in gs for k in entry_rule(*g)})
                for k in rule_cache[rid]:
                    routes.setdefault(k, {"entree": k, "etapes": [], "comment": "nom", "regle": rid})
        if not targets and not routes:                      # else the routes of Onisep's associated jobs
            for n in near.get(mid) or []:
                if n in first and first[n][0] and first[n][1]:
                    voisins.append({"id": n, "nom": noms.get(n)})
                    for k, r in first[n][1].items():
                        routes.setdefault(k, dict(r, comment="voisin", voisin=n))
        need = rank is not None and rank >= 1 or (rank is None and any((ON.level_rank(forms[t]["niveau"]) or 0) >= 1 for t in targets))
        statut = ("postbac" if routes else "hors_parcoursup") if need else "sans_postbac"
        ranked = sorted((dict(r) for r in routes.values()), key=lambda r: (-entries[r["entree"]][4], entries[r["entree"]][0]))
        total, cum = sum(entries[r["entree"]][4] for r in ranked), 0
        for r in ranked:                                    # the first entries that gather 80 % of the places
            r["principale"] = total == 0 or cum < MAIN_SHARE * total
            cum += entries[r["entree"]][4]
            r["etapes"] = [{"id": f, "libelle": forms[f]["lib"], "niveau": forms[f]["niveau"]} for f in r["etapes"]]
        cibles = [{"id": t, "libelle": forms[t]["lib"], "niveau": forms[t]["niveau"], "url": ON.ONISEP_URL.format(kind="formation", id=t)}
                  for t in targets]
        regles = sorted({r["regle"] for r in ranked if r["regle"]})
        data = {"routes": ranked, "cibles": cibles, "voisins": voisins, "acces": acces.get(mid) or None,
                "regles": [{"id": rid, "texte": RULE_TEXT.get(rid, "Un master se prépare après une licence du même domaine.")} for rid in regles]}
        rows.append((mid, statut, json.dumps(data, ensure_ascii=False)))
        stats[statut] += 1
        if need and routes:
            kinds = {r["comment"] for r in ranked}
            stats["directs" if "direct" in kinds else "graphe" if "graphe" in kinds else "regles" if kinds & {"regle", "nom"} else "voisins"] += 1
    ON._insert(con, "core.parcours_entree", [(k, *v) for k, v in sorted(entries.items())])
    ON._insert(con, "core.parcours_metier", rows)
    need = stats["postbac"] + stats["hors_parcoursup"]
    cov = round(stats["postbac"] / need, 4) if need else None
    ON._insert(con, "core.parcours_mesure", [(need, stats["postbac"], cov, stats["sans_postbac"], stats["hors_parcoursup"],
                                              stats["directs"], stats["graphe"], stats["regles"], stats["voisins"])])
    return {"jobs": len(rows), "need": need, "covered": stats["postbac"], "coverage": cov, "entries": len(entries),
            "sans_postbac": stats["sans_postbac"]}


FORMATIONS_MAX = 400


def entry_codes_sql(key: str) -> tuple[str, list]:
    """The SQL selecting an entry's formation codes in core.formation_year (alias y) for a session (first parameter)."""
    if key.startswith("onisep:"):
        return ("SELECT DISTINCT y.cod_aff_form FROM core.onisep_link l JOIN core.formation_year y ON y.session = l.session "
                "AND y.cod_aff_form = l.cod_aff_form WHERE l.session = ? AND l.for_id = ?", [key.split(":", 1)[1]])
    parts = key.split(":", 3)
    sql, args = "SELECT y.cod_aff_form FROM core.formation_year y WHERE y.session = ? AND y.fili = ?", [parts[1]]
    if len(parts) >= 3:
        sql += " AND coalesce(y.fil_lib_voe_acc, '') = ?"
        args.append(parts[2])
    if len(parts) == 4:
        sql += " AND coalesce(y.form_lib_voe_acc, '') = ?"
        args.append(parts[3])
    return sql, args


def entry_formations(con, key: str, session: int) -> list[dict]:
    """The formations of one entry (at most FORMATIONS_MAX), by académie, town and name, as compact rows [code, establishment,
    town, académie, places, label]: exactly the group its count and places count (no search on its label). The label (the
    formation's own Parcoursup title, trailing dash off) tells apart two formations of one establishment."""
    sql, args = entry_codes_sql(key)
    rows = con.execute(f"""SELECT f.cod_aff_form, f.g_ea_lib_vx, f.ville_etab, f.acad_mies, f.capa_fin,
        nullif(trim(regexp_replace(coalesce(f.lib_for_voe_ins, ''), '[\\s-]+$', '')), '') FROM core.formation_year f
        WHERE f.session = ? AND f.cod_aff_form IN ({sql}) ORDER BY f.acad_mies, f.ville_etab, f.g_ea_lib_vx, f.cod_aff_form LIMIT ?""",
                       [session, session, *args, FORMATIONS_MAX]).fetchall()
    return [list(r) for r in rows]                       # compact rows: [code, establishment, town, académie, places, label]


def for_metier(con, met_id: str) -> dict | None:
    """The job's routes with their entries (label, count, places, search words), its status and the build's coverage."""
    if not ON._has(con, "parcours_metier"):
        return None
    r = con.execute("SELECT statut, data FROM core.parcours_metier WHERE met_id = ?", [met_id]).fetchone()
    if not r:
        return None
    statut, data = r[0], json.loads(r[1])
    keys = sorted({x["entree"] for x in data["routes"]})
    ent = {}
    if keys:
        q = ", ".join("?" * len(keys))
        for k, lab, kind, fili, n, places, rech in con.execute(f"""SELECT entree, libelle, kind, fili, n_formations, places, recherche
                FROM core.parcours_entree WHERE entree IN ({q})""", keys).fetchall():
            ent[k] = {"libelle": lab, "kind": kind, "fili": fili, "n_formations": n, "places": places, "recherche": rech}
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    for x in data["routes"]:
        x["entree_info"] = ent.get(x["entree"])
        # the entry's own formations, as counted (Codex: a search link on its label found only part of them)
        x["formations"] = entry_formations(con, x["entree"], session)
    m = con.execute("SELECT a_besoin, couverts, couverture FROM core.parcours_mesure").fetchone()
    return {"statut": statut, **data, "mesure": dict(zip(("a_besoin", "couverts", "couverture"), m)) if m else None}
