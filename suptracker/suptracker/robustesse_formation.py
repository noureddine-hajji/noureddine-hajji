"""Robustesse 2035 per FORMATION (owner's PRD 2026-11-16, decisions validated 2026-11-17): built on the per-job model
(robustesse.py), as an ESTIMATION OF THE MODEL, never a forecast for a person, a promise or a chance.

A formation is read through three things (owner, 2026-11-17: « une formation est le résultat des compétences développées par la
théorie, la pratique et l'expérience en entreprise »):

1. Its OUTLETS ω (sum 1), one method per formation, said on the page:
   - « direct »: the jobs of the diploma's Onisep sheet (all at the diploma's level or below: « avec ce diplôme seul »), equal
     weights (Onisep gives none);
   - « poursuite » (licence, LAS; decision 4): the masters of the same university and discipline (sprint 16), weighted by their
     MonMaster admits (people), then the jobs of each master's Onisep sheet, equal within a master; the licence-only jobs are
     shown apart;
   - « famille » (CPGE, PASS, schools, others: no Onisep sheet): the jobs whose route (parcours.py) enters through this
     formation's Parcoursup group, equal weights, a less sure link.
2. Its SKILLS: the RNCP fiche of the diploma (France Compétences: Onisep's own link for licences and DE, the national title for
   BTS and BUT) gives the ROME codes of the jobs it targets; the ROME 4.0 (France Travail) gives each job's competences, which
   France Travail itself classes « technique », « technique expert » or « transverse », and how many job sheets share each one.
   Portable = transverse, or shared by >= PORTABLE_SHEETS job sheets. No text matching (the RNCP blocks are shown verbatim).
3. Its PRACTICE: apprenticeship possible (RNCP access routes); the insertion of the exit diploma where published (InserSup,
   masters of a licence; BTS insertion is at 6 months and stays apart: decision 2).

Score per scenario s (decisions 3 and 5): R(f,s) = 0.60 x Σ ω R_job(m,s) + 0.10 Ins + 0.15 Div + 0.15 Comp, renormalised over
the terms available (a missing term lowers the coverage, never a typed value). R_job = (0.35 IA + 0.25 Dem) / 0.60 per job, so the
first term is the PRD's Σ ω (0.35 IA + 0.25 Dem). Div = normalised Shannon entropy of ω over ISCO major groups (100 x H / ln 10);
Comp = 100 x portable share. Shown: the median of the three scenarios, min-max under it. Confidence = the lowest of freshness,
observed links (method x the jobs' own), agreement (the jobs' own) and coverage; < 0.4 = « données insuffisantes ».
The page leads with a REPÈRE among the formations of the same filière (decision 1; top / bottom 20 %, cut points measured at
build) and three plain facts; the score is in « Détail du calcul » only.

Apprenticeship offers (owner, 2026-11-20): an offer of the cartographie that SIES does not publish takes the block of its DIPLOMA
(`inherit`) only when every formation of the latest campaign with the same type and mention (`carte.diplome_of`, the offer's own
voted pair) has a block and all those blocks are identical: the score then belongs to the diploma, not to an establishment.
It carries `herite` (how many formations share it) and never enters a repère's ranking (computed before, among SIES rows only).
An offer whose diploma SIES never publishes (titres professionnels, most CSA, the DEUST préparateur en pharmacie) is read through
its OWN national Onisep sheet (`onisep.match_offer`: acronym + exact title) like a « direct » formation (`offer_blocks`); its
national repère is PLACED among the SIES formations' national scores (never added to them), it has no filière repère (no SIES
formation of its filière), and it carries `diplome_offre` (the rule).
"""
from __future__ import annotations

import bisect
import csv
import io
import json
import math
import re
import statistics
import unicodedata
import zipfile
from pathlib import Path

from . import robustesse as RJ

MODEL_VERSION = "2027.5-f"
DIR = Path(__file__).resolve().parents[1] / "data" / "rncp"
RNCP_ZIP, ROME_ZIP = "export-fiches-csv.zip", "rome_toutes_donnees.zip"
W_JOBS, W_INS, W_DIV, W_COMP = 0.60, 0.10, 0.15, 0.15
METHOD_WEIGHT = {"direct": 1.0, "poursuite": 0.8, "famille": 0.5}
PORTABLE_SHEETS = 20
REPERE_SHARE = RJ.REPERE_SHARE
MIN_FILIERE = 20                   # fewer scored formations in a filière: the repère is read among all formations
# owner, 2026-11-18 (thresholds re-set the same day): a licence is scored through its university's masters when they cover at
# least MIN_MASTERS masters or MIN_MASTER_JOBS jobs; otherwise on the licence's own jobs, the masters still shown, the reason said
MIN_MASTERS, MIN_MASTER_JOBS = 1, 1
TOP_JOBS = 8                       # the main outlets listed, only when the cut is not inside a tie (equal weights)
ISCO_GROUPS = 10


def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("œ", "oe").replace("Œ", "oe")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def head(title: str | None) -> str:
    """A BTS national title before its options or parcours (RNCP prints the options after the title)."""
    return re.split(r" options? | parcours | specialite ", " " + fold(title) + " ")[0].strip()


# ---------------------------------------------------------------------------------------------------------- sources
def _csv(z: zipfile.ZipFile, part: str) -> list[dict]:
    name = next(n for n in z.namelist() if part in n)
    raw = z.read(name)
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=sep))


def read_rncp(path: Path) -> dict:
    """{fiche: {intitule, abrege, actif, decision, blocs [labels], rome {codes}, apprentissage bool}}."""
    with zipfile.ZipFile(path) as z:
        out = {r["Numero_Fiche"]: {"intitule": r["Intitule"], "abrege": r["Abrege_Libelle"], "actif": r["Actif"] == "ACTIVE",
                                   "decision": r.get("Date_Decision") or "", "blocs": [], "rome": set(), "voies": set()}
               for r in _csv(z, "_Standard_")}
        for r in _csv(z, "_Blocs_"):
            if r["Numero_Fiche"] in out and (r["Bloc_Competences_Libelle"] or "").strip():
                out[r["Numero_Fiche"]]["blocs"].append(r["Bloc_Competences_Libelle"].strip())
        for r in _csv(z, "_Rome_"):
            if r["Numero_Fiche"] in out and r["Codes_Rome_Code"]:
                out[r["Numero_Fiche"]]["rome"].add(r["Codes_Rome_Code"].strip())
        for r in _csv(z, "VoixdAcc"):
            if r["Numero_Fiche"] in out:
                out[r["Numero_Fiche"]]["voies"].add(r["Si_Jury"])
    for v in out.values():
        v["apprentissage"] = any("apprentissage" in x.lower() for x in v["voies"])
    return out


def read_rome(path: Path) -> dict:
    """{competences {ogr: {libelle, sous_cat, eco, num}}, fiche {rome: {ogr}}, partage {ogr: n sheets}, mobilite {rome: {rome}}}."""
    with zipfile.ZipFile(path) as z:
        comp = {r["code_ogr"]: {"libelle": r["libelle_competence"], "sous_cat": r["sous_cat_comp"],
                                "eco": r["transition_eco"] == "O", "num": r["transition_num"] == "O"}
                for r in _csv(z, "referentiel_competence")}
        fiche: dict = {}
        for r in _csv(z, "liens_rome_referentiels"):
            if r["code_ogr"] in comp:
                fiche.setdefault(r["code_rome"], set()).add(r["code_ogr"])
        mob: dict = {}
        for r in _csv(z, "rubrique_mobilite"):
            mob.setdefault(r["code_rome"], set()).add(r["code_rome_cible"])
    partage: dict = {}
    for s in fiche.values():
        for o in s:
            partage[o] = partage.get(o, 0) + 1
    return {"competences": comp, "fiche": fiche, "partage": partage, "mobilite": mob}


def onisep_rncp(sources: dict | None = None) -> dict:
    """{Onisep for_id: RNCP fiche} from each sheet's France Compétences link (licences, DE)."""
    from . import onisep as ON
    src = (ON.find_sources() if sources is None else sources).get("formations")
    if not src:
        return {}
    out = {}
    for f in ON._xml_root(src).iter("formation"):
        m = re.search(r"francecompetences\.fr/recherche/rncp/(\d+)", f.findtext("url") or "")
        if m:
            out[f.findtext("identifiant")] = "RNCP" + m.group(1)
    return out


def tight(s: str | None) -> str:
    """fold() without spaces: « éco-conception » = « Ecoconception », « l’industrie » = « l'industrie » (format only)."""
    return fold(s).replace(" ", "")


def title_index(rncp: dict) -> dict:
    """{("BTS", head): [fiches]} and {("BUTsp", spécialité): {parcours: [fiches]}} (spellings folded by tight())."""
    idx: dict = {}
    for k, v in rncp.items():
        if v["abrege"] == "BTS":
            idx.setdefault(("BTS", head(v["intitule"])), []).append(k)
        elif v["abrege"] == "BUT":
            sp, _, pa = v["intitule"].partition(":")
            idx.setdefault(("BUTsp", tight(sp)), {}).setdefault(tight(pa), []).append(k)
    return idx


def but_parcours(parcours: dict, pa: str) -> list:
    """Codex (PR #82): the fiches of the SAME parcours only, never another parcours of the specialty. Same title once
    folded; else the one parcours whose title is a prefix of the other (« … des matériaux » = « … des matériaux et des
    produits »), only when exactly one parcours of the specialty matches; else nothing."""
    t = tight(pa)
    if not t:
        return []
    if t in parcours:
        return parcours[t]
    hits = [k for k in parcours if k and (k.startswith(t) or t.startswith(k))]
    return parcours[hits[0]] if len(hits) == 1 else []


def pick(fiches: list, rncp: dict) -> str | None:
    """The fiche to read among several of one title: one with content, the ACTIVE one first, then the latest decision."""
    ok = [k for k in fiches or () if rncp[k]["blocs"] or rncp[k]["rome"]]

    def date(k):
        p = rncp[k]["decision"].split("/")
        return "".join(reversed(p)) if len(p) == 3 else rncp[k]["decision"]
    return max(ok, key=lambda k: (rncp[k]["actif"], date(k), k)) if ok else None


def rncp_of(for_id: str | None, label: str | None, on_link: dict, idx: dict, rncp: dict) -> tuple[str | None, str | None]:
    """(fiche, method): Onisep's own link first, else the national BTS / BUT title."""
    if not for_id:
        return None, None
    if on_link.get(for_id) in rncp:
        return on_link[for_id], "onisep"
    lab = fold(label)
    if lab.startswith("bts "):
        f = pick(idx.get(("BTS", head(lab[4:]))), rncp)
        return (f, "titre") if f else (None, None)
    if lab.startswith("but "):
        sp, _, pa = lab[4:].partition(" parcours ")
        f = pick(but_parcours(idx.get(("BUTsp", tight(sp)), {}), pa), rncp)
        return (f, "titre") if f else (None, None)
    return None, None


def skills(fiche: dict | None, rome: dict) -> dict | None:
    """The competences of the jobs the diploma targets (its RNCP ROME codes), as counts and shares (never a score of a person)."""
    if not fiche or not rome:
        return None
    codes = sorted(c for c in fiche["rome"] if c in rome["fiche"])
    comp = set().union(*(rome["fiche"][c] for c in codes)) if codes else set()
    if not comp:
        return None
    C = rome["competences"]
    port = [o for o in comp if C[o]["sous_cat"] == "Transverse" or rome["partage"].get(o, 0) >= PORTABLE_SHEETS]
    mob = set().union(*(rome["mobilite"].get(c, set()) for c in codes)) - set(codes)
    return {"rome": codes, "n": len(comp), "portables": len(port), "part_portable": round(len(port) / len(comp), 4),
            "transverses": sum(1 for o in comp if C[o]["sous_cat"] == "Transverse"),
            "numeriques": sum(1 for o in comp if C[o]["num"]), "ecologiques": sum(1 for o in comp if C[o]["eco"]),
            "metiers_proches": len(mob)}


# ---------------------------------------------------------------------------------------------------------- scoring
def entropy(weights: dict) -> float | None:
    """100 x Shannon entropy of the weights over the ISCO major groups / ln 10 (fixed bound: versions stay comparable)."""
    p = [w for w in weights.values() if w > 0]
    s = sum(p)
    if not s:
        return None
    return 100 * -sum((w / s) * math.log(w / s) for w in p) / math.log(ISCO_GROUPS)


def major_groups(omega: dict, jobs: dict) -> dict:
    out: dict = {}
    for m, w in omega.items():
        lines = (jobs.get(m) or {}).get("isco") or []
        tot = sum(x.get("poids") or 0 for x in lines)
        for x in lines:
            if tot and x.get("isco"):
                out[x["isco"][0]] = out.get(x["isco"][0], 0) + w * x["poids"] / tot
    return out


def _wmean(pairs):
    s = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / s if s else None


def formation(omega: dict, method: str, jobs: dict, ins: float | None, comp: dict | None) -> dict:
    """One formation's block from its outlets ω, the per-job blocks, the insertion term and the skills."""
    tot = sum(omega.values())
    omega = {m: w / tot for m, w in omega.items()} if tot else {}
    scored = {m: w for m, w in omega.items() if (jobs.get(m) or {}).get("score")}
    cov_jobs = sum(scored.values())
    s_tot = sum(scored.values())
    sw = {m: w / s_tot for m, w in scored.items()} if s_tot else {}
    div = entropy(major_groups(omega, jobs))
    comp_term = 100 * comp["part_portable"] if comp else None
    terms = {"metiers": None, "insertion": ins, "diversite": div, "competences": comp_term}
    scen, common = {}, {}
    for s in ("S1", "S2", "S3"):
        a = sum(w * jobs[m]["scenarios"][s] for m, w in sw.items()) if sw else None
        parts = [(v, wt) for v, wt in ((a, W_JOBS), (ins, W_INS), (div, W_DIV), (comp_term, W_COMP)) if v is not None]
        scen[s] = round(_wmean(parts), 1) if a is not None and parts else None
        # national basis (owner, 2026-11-17): only the terms EVERY formation has (its jobs and their diversity), so that
        # formations of all filières are compared on the same terms
        common[s] = round(_wmean([(a, W_JOBS), (div, W_DIV)]), 1) if a is not None and div is not None else None
        if s == "S2":
            terms["metiers"] = round(a, 1) if a is not None else None
    vals = [v for v in scen.values() if v is not None]
    # confidence: the lowest of four
    fresh = _wmean([(jobs[m]["confiance"]["fraicheur"], w) for m, w in sw.items()]) if sw else 0.0
    observed = METHOD_WEIGHT[method] * (_wmean([(jobs[m]["confiance"]["donnees_observees"], w) for m, w in sw.items()]) or 0.0)
    accord = _wmean([(jobs[m]["confiance"]["accord_sources"], w) for m, w in sw.items()]) if sw else 0.0
    avail = W_JOBS * cov_jobs + sum(wt for v, wt in ((ins, W_INS), (div, W_DIV), (comp_term, W_COMP)) if v is not None)
    comps = {"fraicheur": round(fresh, 3), "donnees_observees": round(observed, 3), "accord_sources": round(accord, 3),
             "couverture": round(avail, 3)}
    conf = min(comps.values())
    shown = len(vals) == 3 and conf >= RJ.CONF_LOW
    ranked = sorted(omega.items(), key=lambda kv: (-kv[1], kv[0]))
    lv = {m: (jobs.get(m) or {}).get("repere") or {} for m in omega}
    return {
        "model_version": MODEL_VERSION, "methode": method,
        "score": {"median": statistics.median(vals), "min": min(vals), "max": max(vals),
                  "dependance_scenario": max(vals) - min(vals) > RJ.BADGE_SPREAD} if shown else None,
        "scenarios": scen if shown else None,
        "score_national": statistics.median(common.values()) if shown and None not in common.values() else None,
        "composantes": {k: (round(v, 1) if v is not None else None) for k, v in terms.items()},
        "metiers": {"n": len(omega), "n_notes": len(scored),
                    "n_haut": sum(1 for m in omega if lv[m].get("niveau") == "haut"),
                    "n_bas": sum(1 for m in omega if lv[m].get("niveau") == "bas"),
                    "part_haut_pondere": round(sum(w for m, w in omega.items() if lv[m].get("niveau") == "haut"), 4),
                    "principaux": [[m, round(w, 4)] for m, w in main_jobs(ranked)]},
        "competences": comp,
        "confiance": {"niveau": RJ.level(conf), "valeur": round(conf, 3), **comps},
    }


def enough_masters(n_masters: int, n_jobs: int) -> bool:
    """Owner, 2026-11-18: a licence is scored through its masters only when they cover enough jobs."""
    return n_masters >= MIN_MASTERS or n_jobs >= MIN_MASTER_JOBS


def main_jobs(ranked: list) -> list:
    """The first TOP_JOBS outlets by weight, only when the cut does not split a tie: equal weights (Onisep gives none, a family
    route neither) never show an arbitrary pick of « main » jobs."""
    if len(ranked) <= TOP_JOBS:
        return ranked
    return ranked[:TOP_JOBS] if ranked[TOP_JOBS - 1][1] > ranked[TOP_JOBS][1] else []


def facts_jobs(ids: list[str], jobs: dict) -> dict:
    """The jobs of a list (e.g. « avec ce diplôme seul »): counts and the median of their medians, never a chance."""
    lv = [(jobs.get(m) or {}).get("repere") or {} for m in ids]
    med = [jobs[m]["score"]["median"] for m in ids if (jobs.get(m) or {}).get("score")]
    return {"n": len(ids), "n_notes": len(med), "n_haut": sum(1 for x in lv if x.get("niveau") == "haut"),
            "n_bas": sum(1 for x in lv if x.get("niveau") == "bas"),
            "mediane": round(statistics.median(med), 1) if med else None}


MIN_DISTINCT = 5                   # a filière whose formations share fewer distinct scores says nothing: read among all formations


def place(v: float, others: list[float]) -> str:
    """« haut » when the score is above at least 1 - REPERE_SHARE of the others, « bas » when below at least as many; ties never
    count as above or below (formations of one group share their outlets, hence their score). `others` is SORTED."""
    n = len(others)
    below = bisect.bisect_left(others, v) / n
    above = (n - bisect.bisect_right(others, v)) / n
    return "haut" if below >= 1 - REPERE_SHARE else "bas" if above >= 1 - REPERE_SHARE else "moyen"


def terms_key(d: dict) -> str:
    """The terms a formation's score was computed with: only formations scored with the same terms are compared (a missing term is
    renormalised away, so mixing term sets would favour the formations with fewer data)."""
    return "+".join(k for k in ("metiers", "insertion", "diversite", "competences") if d["composantes"].get(k) is not None)


def with_repere(rows: dict, fili: dict) -> dict:
    """The repère of each scored formation among the scored formations of its filière computed with the same terms (decision 1),
    and its NATIONAL repère (owner, 2026-11-17) among every formation on the common terms (jobs + diversity, `score_national`).
    Fewer than MIN_FILIERE of them, or fewer than MIN_DISTINCT distinct scores (the formations of a filière that share their
    outlets share their score): no repère, said on the page, never a comparison with other filières."""
    by: dict = {}
    for cod, d in rows.items():
        if d["score"]:
            by.setdefault((fili.get(cod), terms_key(d)), []).append(d["score"]["median"])
    for ref in by.values():
        ref.sort()
    for cod, d in rows.items():
        d["repere"] = None
        if not d["score"]:
            continue
        ref = by[(fili.get(cod), terms_key(d))]
        if len(ref) >= MIN_FILIERE and len(set(ref)) >= MIN_DISTINCT:
            d["repere"] = {"niveau": place(d["score"]["median"], ref), "filiere": fili.get(cod), "n_formations": len(ref),
                           "part": REPERE_SHARE}
        else:
            d["repere"] = {"niveau": None, "filiere": fili.get(cod), "n_formations": len(ref), "raison": "memes_debouches"
                           if len(ref) >= MIN_FILIERE else "trop_peu"}
    nat = sorted(d["score_national"] for d in rows.values() if d.get("score_national") is not None)
    for d in rows.values():
        v = d.get("score_national")
        d["repere_national"] = None if v is None else {
            "niveau": place(v, nat), "n_formations": len(nat), "part": REPERE_SHARE,
            # the outlets counted come after more studies (a licence's masters, a family route): said beside the level
            "apres_etudes": {"poursuite": "master", "famille": "autres"}.get(d["methode"])}
    return rows


# ---------------------------------------------------------------------------------------------------------- build
def _family_jobs(con, session: int) -> dict:
    """{cod: {met_id}}: the jobs whose route (parcours.py) enters through a Parcoursup group (ps: entries only)."""
    from . import parcours as PA
    out: dict = {}
    cache: dict = {}
    for mid, data in con.execute("SELECT met_id, data FROM core.parcours_metier WHERE statut = 'postbac'").fetchall():
        for r in (json.loads(data).get("routes") or []):
            key = r.get("entree") or ""
            if not key.startswith("ps:"):
                continue
            if key not in cache:
                sql, args = PA.entry_codes_sql(key)
                cache[key] = [c for (c,) in con.execute(sql, [session, *args]).fetchall()]
            for c in cache[key]:
                out.setdefault(c, set()).add(mid)
    return out


def _jobs(con, textes: Path | None) -> dict:
    """The per-job blocks robustesse.build has just written (beside the warehouse, else in core)."""
    if textes is not None and Path(textes).exists():
        import duckdb
        tc = duckdb.connect(str(textes), read_only=True)
        try:
            return {m: json.loads(v) for m, v in tc.execute("SELECT met_id, data FROM r35_metier").fetchall()}
        except Exception:  # noqa: BLE001
            return {}
        finally:
            tc.close()
    try:
        return {m: json.loads(v) for m, v in con.execute("SELECT met_id, data FROM core.r35_metier").fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def build(con, jobs: dict | None = None, d: Path = DIR, textes: Path | None = None, sources: dict | None = None) -> dict:
    """r35_formation (one JSON per formation of the latest campaign) and r35_rncp (the RNCP fiches read), beside the warehouse.
    jobs: the per-job blocks (default: read where robustesse.build wrote them)."""
    from . import licence_master as LM
    if jobs is None:
        jobs = _jobs(con, textes)
    have = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    rows, rncp_rows = {}, {}
    if "formation_year" in have and jobs:
        session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        forms = con.execute("""SELECT cod_aff_form, any_value(fili), any_value(contrat_etab) FROM core.formation_year
                               WHERE session = ? GROUP BY 1""", [session]).fetchall()
        sheet: dict = {}
        if "onisep_link" in have:
            for cod, fid in con.execute("SELECT DISTINCT cod_aff_form, for_id FROM core.onisep_link WHERE session = ? AND for_id IS NOT NULL",
                                        [session]).fetchall():
                sheet.setdefault(cod, set()).add(fid)
        sheet_jobs: dict = {}
        if "onisep_formation_metier" in have:
            for fid, mid in con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall():
                sheet_jobs.setdefault(fid, set()).add(mid)
        labels = dict(con.execute("SELECT for_id, libelle FROM core.onisep_formation").fetchall()) if "onisep_formation" in have else {}
        family = _family_jobs(con, session) if "parcours_metier" in have else {}
        rncp = read_rncp(d / RNCP_ZIP) if (d / RNCP_ZIP).exists() else {}
        rome = read_rome(d / ROME_ZIP) if (d / ROME_ZIP).exists() else {}
        on_link = onisep_rncp(sources) if rncp else {}
        idx = title_index(rncp)
        fili = {}
        for cod, fl, contrat in forms:
            fili[cod] = fl
            fids = sorted(sheet.get(cod, ()))
            direct = sorted(set().union(*(sheet_jobs.get(f, set()) for f in fids))) if fids else []
            fiche = method_r = None
            for f in fids:
                fiche, method_r = rncp_of(f, labels.get(f), on_link, idx, rncp)
                if fiche:
                    break
            sk = skills(rncp.get(fiche), rome) if fiche else None
            ins = master = master_seul = None
            if fl in ("Licence", "Licence_Las"):
                lic = LM.for_licence(con, cod, fl, contrat) if {"monmaster", "master_onisep", "metier_axes"} <= have else None
                if lic and lic.get("status") == "ok":
                    mentions = [mm for mm in lic["mentions"] if (mm.get("metiers") or {}).get("metiers") and (mm.get("n_accept") or 0) > 0]
                    tot = sum(mm["n_accept"] for mm in mentions)
                    if tot:
                        omega = {}
                        for mm in mentions:
                            ids = [j["id"] for j in mm["metiers"]["metiers"]]
                            for j in ids:
                                omega[j] = omega.get(j, 0) + mm["n_accept"] / tot / len(ids)
                        stable = [(mm["insertion"]["taux_stable"], mm["n_accept"]) for mm in mentions
                                  if mm.get("insertion") and mm["insertion"].get("taux_stable") is not None]
                        ins = _wmean(stable)
                        master = {"n_masters": len(mentions), "n_admis": tot, "insertion_masters": len(stable),
                                  "apres_master": facts_jobs(sorted(omega), jobs)}
                        if enough_masters(len(mentions), len(omega)):
                            block = formation(omega, "poursuite", jobs, ins, sk)
                            block["master"] = master
                            block["diplome_seul"] = facts_jobs(direct, jobs)
                            rows[cod] = block
                        else:
                            # too few documented masters to score the licence through them: kept for display, said
                            master["insuffisant"] = True
                            master_seul = master
            if cod in rows:
                pass
            elif direct:
                rows[cod] = formation({m: 1.0 for m in direct}, "direct", jobs, None, sk)
                rows[cod]["diplome_seul"] = facts_jobs(direct, jobs)
            elif family.get(cod):
                rows[cod] = formation({m: 1.0 for m in family[cod]}, "famille", jobs, None, sk)
            else:
                continue
            if master_seul:
                rows[cod]["master"] = master_seul
            r = rows[cod]
            r["rncp"] = {"fiche": fiche, "lien": method_r, "apprentissage": rncp[fiche]["apprentissage"]} if fiche else None
            if fiche and fiche not in rncp_rows:
                f = rncp[fiche]
                rncp_rows[fiche] = json.dumps({"intitule": f["intitule"], "blocs": f["blocs"], "rome": sorted(f["rome"]),
                                               "actif": f["actif"]}, ensure_ascii=False, sort_keys=True)
        with_repere(rows, fili)
        rows.update(inherit(con, rows, session))
        def skills_of(fids):
            for f in fids:
                fiche, lien = rncp_of(f, labels.get(f), on_link, idx, rncp)
                if fiche:
                    return fiche, lien, skills(rncp.get(fiche), rome)
            return None, None, None
        offers = offer_list(con, rows)
        if offers:
            from . import onisep as ON
            forms_on = con.execute("SELECT for_id, libelle, type, niveau_certification, niveau_etudes FROM core.onisep_formation").fetchall() \
                if "onisep_formation" in have else []
            extra = offer_blocks(offers, ON.index(forms_on), sheet_jobs, jobs, skills_of, rows)
            for cod, b in extra.items():
                fiche = (b.get("rncp") or {}).get("fiche")
                if fiche:
                    b["rncp"]["apprentissage"] = rncp[fiche]["apprentissage"]
                if fiche and fiche not in rncp_rows:
                    f = rncp[fiche]
                    rncp_rows[fiche] = json.dumps({"intitule": f["intitule"], "blocs": f["blocs"], "rome": sorted(f["rome"]),
                                                   "actif": f["actif"]}, ensure_ascii=False, sort_keys=True)
            rows.update(extra)
    out_rows = [(c, json.dumps(v, ensure_ascii=False, sort_keys=True)) for c, v in sorted(rows.items())]

    def write(c, p):
        c.execute(f"CREATE OR REPLACE TABLE {p}r35_formation (cod_aff_form VARCHAR, data VARCHAR)")
        if out_rows:
            c.executemany(f"INSERT INTO {p}r35_formation VALUES (?, ?)", out_rows)
        c.execute(f"CREATE OR REPLACE TABLE {p}r35_rncp (fiche VARCHAR, data VARCHAR)")
        if rncp_rows:
            c.executemany(f"INSERT INTO {p}r35_rncp VALUES (?, ?)", sorted(rncp_rows.items()))

    if textes is None or not Path(textes).exists():
        write(con, "core.")
    else:
        import duckdb
        from . import rapports as RP
        for t in ("r35_formation", "r35_rncp"):
            con.execute(f"DROP TABLE IF EXISTS core.{t}")
        RP._texts_con.cache_clear()
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    return {"formations": len(rows), "formations_score": sum(1 for v in rows.values() if v["score"]),
            "avec_competences": sum(1 for v in rows.values() if v["competences"]), "fiches_rncp": len(rncp_rows),
            "methodes": {m: sum(1 for v in rows.values() if v["methode"] == m) for m in METHOD_WEIGHT},
            "herites": sum(1 for v in rows.values() if v.get("herite")),
            "offres_fiche": sum(1 for v in rows.values() if v.get("diplome_offre"))}


# the cartographie writes some apprenticeship mentions with the diploma's acronym first (« BTS - Management en hôtellerie
# restauration »): that prefix alone is dropped before comparing with the SIES mention (a closed list of acronyms)
MENTION_PREFIX = re.compile(r"^(?:BTSA|BTSM|BTS|BUT|DCG|DEUST|DE|D\.E)\s+-\s+")


def diploma_key(diplome: str | None, mention: str | None) -> tuple[str, str]:
    return (diplome or "", fold(MENTION_PREFIX.sub("", mention or "")))


def inherited(offers: list[tuple], sies: dict, rows: dict) -> dict:
    """The rule alone. offers: (code, type, mention) of the apprenticeship offers; sies: code -> (type, mention) of every
    formation of the latest campaign; rows: their blocks. An offer gets its diploma's block when EVERY SIES formation of the
    same (type, mention) has a scored block and all those blocks are identical; `herite` says how many share it."""
    groups: dict = {}
    for cod, (d, m) in sies.items():
        groups.setdefault(diploma_key(d, m), []).append(cod)
    out = {}
    for cod, d, m in offers:
        cods = groups.get(diploma_key(d, m), [])
        blocks = [rows.get(c) for c in cods]
        if not cods or any(b is None or not b.get("score") for b in blocks):
            continue
        dumped = {json.dumps(b, ensure_ascii=False, sort_keys=True) for b in blocks}
        if len(dumped) == 1:
            out[cod] = {**json.loads(dumped.pop()), "herite": {"source": "diplome", "formations": len(cods)}}
    return out


def offer_list(con, rows: dict) -> list[tuple]:
    """(code, mention) of the apprenticeship offers listed apart (not attached) that have no block yet."""
    from . import carte as CA
    try:
        return [(a["cod_aff_form"], a["mention"]) for a in CA.apprentissage(con) if not a["rattachee"] and a["cod_aff_form"] not in rows]
    except Exception:  # noqa: BLE001
        return []


def offer_blocks(offers: list[tuple], idx: dict, sheet_jobs: dict, jobs: dict, skills_of, rows: dict) -> dict:
    """The block of each offer read through its OWN national Onisep sheet (`onisep.match_offer`), as a « direct » formation;
    its national repère placed among the SIES formations' national scores (`rows`, never changed), no filière repère."""
    from . import onisep as ON
    nat = sorted(d["score_national"] for d in rows.values() if d.get("score_national") is not None and not d.get("herite"))
    out = {}
    for cod, mention in offers:
        fids, rule = ON.match_offer(idx, mention)
        direct = sorted(set().union(*(sheet_jobs.get(f, set()) for f in fids))) if fids else []
        if not direct:
            continue
        fiche, lien, sk = skills_of(fids)
        b = formation({m: 1.0 for m in direct}, "direct", jobs, None, sk)
        b["diplome_seul"] = facts_jobs(direct, jobs)
        b["rncp"] = None
        b["repere"] = None
        v = b.get("score_national")
        b["repere_national"] = None if v is None or not nat else {"niveau": place(v, nat), "n_formations": len(nat),
                                                                    "part": REPERE_SHARE, "apres_etudes": None}
        b["diplome_offre"] = rule
        out[cod] = b
        if fiche:
            out[cod]["rncp"] = {"fiche": fiche, "lien": lien, "apprentissage": None}
    return out


def inherit(con, rows: dict, session: int) -> dict:
    """Blocks for the apprenticeship offers SIES does not publish (carte.apprentissage, not attached to an initial formation)."""
    from . import carte as CA
    try:
        offers = [(a["cod_aff_form"], a["diplome"], a["mention"]) for a in CA.apprentissage(con) if not a["rattachee"]]
    except Exception:  # noqa: BLE001 - no cartographie: nothing to inherit
        return {}
    if not offers:
        return {}
    sies = {cod: CA.diplome_of(fl, form, fil, lib) for cod, fl, form, fil, lib in con.execute(
        """SELECT cod_aff_form, any_value(fili), any_value(form_lib_voe_acc), any_value(fil_lib_voe_acc), any_value(lib_for_voe_ins)
           FROM core.formation_year WHERE session = ? GROUP BY 1""", [session]).fetchall()}
    return inherited(offers, sies, rows)


def _src(con):
    """Where the tables are: core (no texts file) or beside the warehouse (rapport_textes.duckdb), as robustesse._src."""
    try:
        con.execute("SELECT 1 FROM core.r35_formation LIMIT 0")
        return con, "core."
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import rapports as RP
        db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
        f = RP.textes_path(Path(db[0])) if db and db[0] else None
        if f is None or not f.exists():
            return None, None
        c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
        c.execute("SELECT 1 FROM r35_formation LIMIT 0")
        return c, ""
    except Exception:  # noqa: BLE001
        return None, None


def compact(con) -> dict:
    """Both repères of every formation, for the lists (sent inside /api/reconnaissance, no parameter, shared-cached):
    {"filiere": {niveau: "cod,cod"}, "national": {niveau: ...}, "raison": {raison: ...}, "apres": {"master" | "autres": ...}}.
    Mes vœux shows them BESIDE each vœu's zone, never merged with it (owner, 2026-11-17)."""
    c, p = _src(con)
    out: dict = {"filiere": {}, "national": {}, "raison": {}, "apres": {}, "herite": {}}
    if c is None:
        return out
    acc = {k: {} for k in out}
    for cod, data in c.execute(f"SELECT cod_aff_form, data FROM {p}r35_formation").fetchall():
        d = json.loads(data)
        q, n = d.get("repere") or {}, d.get("repere_national") or {}
        if q.get("niveau"):
            acc["filiere"].setdefault(q["niveau"], []).append(cod)
        elif q.get("raison"):
            acc["raison"].setdefault(q["raison"], []).append(cod)
        if d.get("herite") or d.get("diplome_offre"):
            acc["herite"].setdefault("diplome", []).append(cod)
        if n.get("niveau"):
            acc["national"].setdefault(n["niveau"], []).append(cod)
            if n.get("apres_etudes"):
                acc["apres"].setdefault(n["apres_etudes"], []).append(cod)
    return {k: {lv: ",".join(sorted(v)) for lv, v in sorted(m.items())} for k, m in acc.items()}


def for_formation(con, cod: str) -> dict | None:
    c, p = _src(con)
    if c is None:
        return None
    r = c.execute(f"SELECT data FROM {p}r35_formation WHERE cod_aff_form = ?", [cod]).fetchone()
    if not r:
        return None
    out = json.loads(r[0])
    ids = [m for m, _ in out["metiers"]["principaux"]]
    names = dict(con.execute(f"SELECT met_id, nom FROM core.onisep_metier WHERE met_id IN ({','.join('?' * len(ids))})", ids).fetchall()) if ids else {}
    jc, jp = RJ._src(con)
    lv = {}
    if jc is not None and ids:
        for m, d in jc.execute(f"SELECT met_id, data FROM {jp}r35_metier WHERE met_id IN ({','.join('?' * len(ids))})", ids).fetchall():
            lv[m] = (json.loads(d).get("repere") or {}).get("niveau")
    out["metiers"]["principaux"] = [{"id": m, "nom": names.get(m), "poids": w, "repere": lv.get(m)} for m, w in out["metiers"]["principaux"]]
    if out.get("rncp") and out["rncp"].get("fiche"):
        f = c.execute(f"SELECT data FROM {p}r35_rncp WHERE fiche = ?", [out["rncp"]["fiche"]]).fetchone()
        if f:
            out["rncp"].update(json.loads(f[0]))
    return out
