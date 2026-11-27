"""Red team, robustesse 2035 per FORMATION (owner, 2026-11-17): an ESTIMATION of the model on each formation page, built on the
per-job model (redteam_robustesse.py).

  RF1 skills: an INDEPENDENT reading of the RNCP export (Standard, Blocs, Rome, VoixdAccès members, ';' and utf-8-sig) and of the
      ROME 4.0 open data (competences, links, mobilities) gives each fiche's blocks, ROME codes, apprenticeship flag, and the
      competences of its ROME codes: portable = « Transverse » or shared by >= 20 sheets; the module equals it (fixture and real).
  RF2 links: Onisep's own France Compétences link first; else the national BTS title before its options, the BUT specialty and
      its OWN parcours (same title once folded, else the one parcours whose title is a prefix of the other; never another
      parcours of the specialty: Codex, PR #82), among the fiches WITH content, ACTIVE first then the latest decision.
  RF3 formula: an independent implementation of R(f,s) = 0.60 Σω R_job + 0.10 Ins + 0.15 Div + 0.15 Comp renormalised over the
      available terms (Div = 100 x Shannon entropy over ISCO major groups / ln 10; Comp = 100 x portable share), the median of
      the three scenarios, min, max, the confidence (lowest of four, method weight 1 / 0.8 / 0.5), « données insuffisantes »
      under 0.4 or without the three scenarios; main jobs never cut inside a tie; equals the module on crafted formations.
  RF4 repère: among the scored formations of the SAME filière computed with the SAME terms, top / bottom 20 % by rank, ties never
      above or below; fewer than 20 formations or fewer than 5 distinct scores = no level, with its reason; re-derived. The
      NATIONAL repère (owner, 2026-11-17): among every scored formation on the terms all of them have (jobs 0.60 + diversity
      0.15, renormalised; `score_national` re-derived in RF3), with the later-studies caveat (licence -> master, family routes).
  RF5 page (node): formationRobustesseCard escapes every stored string, leads with the repère (or its reason) and the plain
      facts, never the score before « Détail du calcul »; « avec ce diplôme seul » apart; the master gain for a licence; the
      RNCP blocks verbatim with an https France Compétences link built from digits only; vouvoiement, no chance or promise.
  RF6 plumbing: build after the jobs, API, in « Emploi et métiers » after the jobs card (owner, 2026-11-24: audit PR 5; it was the
      tab's first card), sources en ligne, the data workflow fingerprint
      and .vercelignore cover data/rncp, README, CLAUDE.md, tests and durations.
  RF7 real (--real): the stored blocks re-derived for a sample (skills from the real RNCP and ROME files, outlets and formula
      from the stored jobs), the repère of every formation re-derived, coverage per filière printed.
  RF8 mutation test.
  RF9 Mes vœux comparator; RF10 the method page.
  RF11 (owner, 2026-11-18): the published BTS / BUT insertion beside the score (never in it), the search page's two robustesse
      filters re-derived from the compact payload, their counts, the card line, never a sort by a repère.
  RF12 (owner, 2026-11-18): L'essentiel shows the formation's robustesse: the median score « / 100 » with its two repères in words
      and the estimation label; no score = « données insuffisantes », no block = « pas d'estimation », never a number invented;
      the tile opens « Emploi et métiers ».
"""
from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import math
import random
import re
import statistics
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import redteam_robustesse as RB  # noqa: E402

CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False, part: tuple[int, int] | None = None):
        self.db = db if db and db.exists() else None
        self.real = real
        self.part = part          # RF8 only: (i, n) runs the i-th of n slices of the mutants (one CI file per slice)
        self.src = {"robf": (ROOT / "suptracker" / "robustesse_formation.py").read_text(),
                    "api": (ROOT / "suptracker" / "api.py").read_text(),
                    "methode": (ROOT / "suptracker" / "methode_robustesse.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def F(self):
        import suptracker  # noqa: F401
        return RB.load(ROOT / "suptracker" / "robustesse_formation.py", "suptracker.robustesse_formation_rt", self.src["robf"])

    def M(self, F=None):
        """The method page module, reading the (possibly mutated) formation module."""
        import suptracker  # noqa: F401
        m = RB.load(ROOT / "suptracker" / "methode_robustesse.py", "suptracker.methode_robustesse_rt",
                    self.src["methode"].replace("from . import robustesse_formation as RF", "RF = None"))
        m.RF = F or self.F()
        return m


# ------------------------------------------------------------------------------------------------------------- fixtures
def _member(rows: list[dict], sep=";") -> bytes:
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=list(rows[0]), delimiter=sep)
    w.writeheader()
    w.writerows(rows)
    return b.getvalue().encode("utf-8-sig")


STD = [  # fiche, intitulé, abrégé, actif, décision
    ("RNCP1", "Management commercial opérationnel", "BTS", "ACTIVE", "01/09/2019"),
    ("RNCP2", "Management commercial opérationnel", "BTS", "INACTIVE", "01/09/2024"),
    ("RNCP3", "Management commercial opérationnel", "BTS", "ACTIVE", "01/09/2022"),
    ("RNCP4", "Informatique : Développement d'applications", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP5", "Licence Économie " + HOSTILE, "LIC", "ACTIVE", ""),
    ("RNCP6", "Conception de produits options A et B", "BTS", "ACTIVE", "02/02/2021"),
    ("RNCP7", "Management commercial opérationnel", "BTS", "ACTIVE", "01/09/2023"),   # newer, but no content: never read
    ("RNCP8", "Informatique : Cybersécurité", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP9", "Packaging emballage : Ecoconception et industrialisation", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP10", "Matériaux : Métiers du recyclage des matériaux et des produits", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP11", "Matériaux : Métiers de la caractérisation", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP12", "Énergie : Management de l’énergie", "BUT", "ACTIVE", "15/06/2022"),
    ("RNCP13", "Énergie : Management de l’énergie et des fluides", "BUT", "ACTIVE", "15/06/2022"),
]
BLOCS = [("RNCP1", "Gérer la relation client"), ("RNCP3", "Animer l'offre"), ("RNCP3", " "), ("RNCP4", "Réaliser une application"),
         ("RNCP5", "Analyser " + HOSTILE), ("RNCP6", "Concevoir")]
ROMES = [("RNCP8", "M1805"), ("RNCP9", "H1203"), ("RNCP10", "H1203"), ("RNCP11", "H1203"), ("RNCP12", "H1203"), ("RNCP13", "H1203"),
         ("RNCP1", "D1501"), ("RNCP2", "D1501"), ("RNCP3", "D1501"), ("RNCP3", "D1502"), ("RNCP4", "M1805"), ("RNCP5", "C1201"), ("RNCP6", "H1203"),
         ("RNCP5", "")]
VOIES = [("RNCP3", "Par apprentissage"), ("RNCP3", "Après un parcours de formation sous statut d'élève ou d'étudiant"),
         ("RNCP4", "Par candidature individuelle")]


def fixture_rncp(path: Path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("export_fiches_CSV_Standard_2026.csv", _member([{"Numero_Fiche": f, "Intitule": t, "Abrege_Libelle": a, "Actif": ac,
                                                                    "Date_Decision": d} for f, t, a, ac, d in STD]))
        z.writestr("export_fiches_CSV_Blocs_De_Compétences_2026.csv",
                   _member([{"Numero_Fiche": f, "Bloc_Competences_Code": "B", "Bloc_Competences_Libelle": b} for f, b in BLOCS]))
        z.writestr("export_fiches_CSV_Rome_2026.csv", _member([{"Numero_Fiche": f, "Codes_Rome_Code": r, "Codes_Rome_Libelle": "x"} for f, r in ROMES]))
        z.writestr("export_fiches_CSV_VoixdAccès_2026.csv", _member([{"Numero_Fiche": f, "Si_Jury": v} for f, v in VOIES]))


COMP = [  # ogr, sous-catégorie, transition éco, num
    ("1", "Transverse", "N", "O"), ("2", "Technique", "N", "N"), ("3", "Technique expert", "O", "N"), ("4", "Technique", "N", "N"),
    ("5", "Technique", "N", "O")]
LINKS = [("D1501", "1"), ("D1501", "2"), ("D1502", "2"), ("D1502", "3"), ("M1805", "4"), ("M1805", "5"), ("H1203", "9")]


def fixture_rome(path: Path, shared4: int = 20):
    links = LINKS + [(f"Z{i:04d}", "4") for i in range(shared4 - 1)]   # competence 4 shared by `shared4` sheets
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("unix_referentiel_competence_v460_utf8.csv", _member(
            [{"code_ogr": o, "libelle_competence": f"c{o}", "sous_cat_comp": s, "transition_eco": e, "transition_num": n} for o, s, e, n in COMP], sep=","))
        z.writestr("unix_liens_rome_referentiels_v460_utf8.csv", _member([{"code_rome": r, "code_ogr": o} for r, o in links], sep=","))
        z.writestr("unix_rubrique_mobilite_v460_utf8.csv", _member(
            [{"code_rome": "D1501", "code_rome_cible": "D1502"}, {"code_rome": "D1501", "code_rome_cible": "D1506"},
             {"code_rome": "M1805", "code_rome_cible": "M1806"}], sep=","))


def _read(z, part):
    name = next(n for n in z.namelist() if part in n)
    text = z.read(name).decode("utf-8-sig")
    first = text.split("\n", 1)[0]
    return list(csv.DictReader(io.StringIO(text), delimiter=";" if first.count(";") > first.count(",") else ","))


def oracle_rncp(path: Path) -> dict:
    out = {}
    with zipfile.ZipFile(path) as z:
        for r in _read(z, "Standard"):
            out[r["Numero_Fiche"]] = {"intitule": r["Intitule"], "abrege": r["Abrege_Libelle"], "actif": r["Actif"] == "ACTIVE",
                                      "decision": r["Date_Decision"], "blocs": [], "rome": set(), "app": False}
        for r in _read(z, "Blocs"):
            if r["Numero_Fiche"] in out and r["Bloc_Competences_Libelle"].strip():
                out[r["Numero_Fiche"]]["blocs"].append(r["Bloc_Competences_Libelle"].strip())
        for r in _read(z, "_Rome_"):
            if r["Numero_Fiche"] in out and r["Codes_Rome_Code"].strip():
                out[r["Numero_Fiche"]]["rome"].add(r["Codes_Rome_Code"].strip())
        for r in _read(z, "VoixdAcc"):
            if r["Numero_Fiche"] in out and "apprentissage" in r["Si_Jury"].lower():
                out[r["Numero_Fiche"]]["app"] = True
    return out


_ROME: dict = {}


def oracle_rome(path: Path) -> tuple:
    """(competences, sheets per ROME code, sheets per competence, mobilities), read once per file."""
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _ROME:
        with zipfile.ZipFile(path) as z:
            comp = {r["code_ogr"]: r for r in _read(z, "referentiel_competence")}
            sheets: dict = {}
            for r in _read(z, "liens_rome_referentiels"):
                if r["code_ogr"] in comp:
                    sheets.setdefault(r["code_rome"], set()).add(r["code_ogr"])
            mob = [(r["code_rome"], r["code_rome_cible"]) for r in _read(z, "rubrique_mobilite")]
        n_sheets: dict = {}
        for s in sheets.values():
            for o in s:
                n_sheets[o] = n_sheets.get(o, 0) + 1
        _ROME[key] = (comp, sheets, n_sheets, mob)
    return _ROME[key]


def oracle_skills(codes: set, path: Path) -> dict | None:
    comp, sheets, n_sheets, mob = oracle_rome(path)
    mine = sorted(c for c in codes if c in sheets)
    cs = set()
    for c in mine:
        cs |= sheets[c]
    if not cs:
        return None
    port = {o for o in cs if comp[o]["sous_cat_comp"] == "Transverse" or n_sheets[o] >= 20}
    return {"rome": mine, "n": len(cs), "portables": len(port), "part_portable": round(len(port) / len(cs), 4),
            "transverses": sum(comp[o]["sous_cat_comp"] == "Transverse" for o in cs),
            "numeriques": sum(comp[o]["transition_num"] == "O" for o in cs), "ecologiques": sum(comp[o]["transition_eco"] == "O" for o in cs),
            "metiers_proches": len({t for s, t in mob if s in mine} - set(mine))}


@check("RF1 skills: own reading of the RNCP export and the ROME 4.0 competences equals the module (fixture and real)")
def rf1(c: Ctx):
    F = c.F()
    bad = []
    with tempfile.TemporaryDirectory() as t:
        rz, oz = Path(t) / "r.zip", Path(t) / "o.zip"
        fixture_rncp(rz)
        fixture_rome(oz)
        mod, ora = F.read_rncp(rz), oracle_rncp(rz)
        for k, o in ora.items():
            m = mod.get(k) or {}
            if (m.get("blocs"), set(m.get("rome") or ()), m.get("actif"), m.get("apprentissage")) != (o["blocs"], o["rome"], o["actif"], o["app"]):
                bad.append(f"fiche {k}")
        rome = F.read_rome(oz)
        for k in ora:
            if F.skills(mod[k], rome) != oracle_skills(ora[k]["rome"], oz):
                bad.append(f"skills {k}: {F.skills(mod[k], rome)} vs {oracle_skills(ora[k]['rome'], oz)}")
        # the 20-sheet threshold: competence 4 shared by 19 sheets is not portable
        oz2 = Path(t) / "o2.zip"
        fixture_rome(oz2, shared4=19)
        s19 = F.skills(mod["RNCP4"], F.read_rome(oz2))
        if not s19 or s19["portables"] != 0:
            bad.append(f"19 sheets counted as portable: {s19}")
        if F.skills(mod["RNCP4"], rome)["portables"] != 1:
            bad.append("20 sheets not counted as portable")
    d = ROOT / "data" / "rncp"
    if c.real and (d / F.RNCP_ZIP).exists() and (d / F.ROME_ZIP).exists():
        mod, ora = F.read_rncp(d / F.RNCP_ZIP), oracle_rncp(d / F.RNCP_ZIP)
        diff = [k for k, o in ora.items() if (mod[k]["blocs"], mod[k]["rome"], mod[k]["actif"], mod[k]["apprentissage"]) != (o["blocs"], o["rome"], o["actif"], o["app"])]
        if diff or set(mod) != set(ora):
            bad.append(f"real RNCP: {len(diff)} fiches differ, e.g. {diff[:3]}")
        rome = F.read_rome(d / F.ROME_ZIP)
        sample = random.Random(7).sample(sorted(k for k in ora if ora[k]["rome"]), 60)
        diff = [k for k in sample if F.skills(mod[k], rome) != oracle_skills(ora[k]["rome"], d / F.ROME_ZIP)]
        if diff:
            bad.append(f"real skills differ for {diff[:3]}")
        return not bad, f"differences {bad[:4]}; real: {len(ora)} RNCP fiches, 60 skill sets re-derived"
    return not bad, f"differences {bad[:4]}"


@check("RF2 links: Onisep's link first, else the national BTS title (options off) or BUT specialty, content and ACTIVE first")
def rf2(c: Ctx):
    F = c.F()
    bad = []
    with tempfile.TemporaryDirectory() as t:
        rz = Path(t) / "r.zip"
        fixture_rncp(rz)
        rn = F.read_rncp(rz)
    idx = F.title_index(rn)
    cases = [  # for_id, Onisep label, Onisep link, expected
        ("A", "BTS management commercial opérationnel", {}, ("RNCP3", "titre")),       # RNCP7 newer but empty; RNCP2 inactive
        ("B", "BTS conception de produits option A", {}, ("RNCP6", "titre")),          # options off on both sides
        ("C", "BUT informatique parcours développement d'applications", {}, ("RNCP4", "titre")),
        ("D", "BUT informatique parcours autre", {}, (None, None)),                    # Codex: never another parcours
        ("D2", "BUT informatique", {}, (None, None)),                                  # no parcours: no fiche
        ("D3", "BUT packaging emballage parcours éco-conception et industrialisation", {}, ("RNCP9", "titre")),  # spelling only
        ("D4", "BUT matériaux parcours métiers du recyclage des matériaux", {}, ("RNCP10", "titre")),          # the one prefix
        ("D5", "BUT énergie parcours management de l'énergie", {}, ("RNCP12", "titre")),  # exact wins over a longer prefix
        ("D6", "BUT énergie parcours management", {}, (None, None)),                   # two parcours start so: none
        ("E", "licence mention économie", {"E": "RNCP5"}, ("RNCP5", "onisep")),
        ("F", "BTS management commercial", {}, (None, None)),                          # never a partial title
        ("G", "licence mention économie", {"G": "RNCP99"}, (None, None)),              # a link to an unknown fiche
        (None, "BTS management commercial opérationnel", {}, (None, None)),
    ]
    for fid, lab, link, exp in cases:
        got = F.rncp_of(fid, lab, link, idx, rn)
        if got != exp:
            bad.append(f"{lab!r}: {got} != {exp}")
    # real: every BUT sheet linked by title reaches a fiche of its OWN parcours (independent check on the folded words)
    d = ROOT / "data" / "rncp"
    info = ""
    if c.real and (d / F.RNCP_ZIP).exists():
        from suptracker import onisep as ON
        src = ON.find_sources().get("formations")
        if src:
            rr = F.read_rncp(d / F.RNCP_ZIP)
            ix = F.title_index(rr)
            words = lambda x: re.sub(r"[^a-z0-9]", "", F.fold(x))  # noqa: E731
            n = 0
            for f in ON._xml_root(src).iter("formation"):
                lab = f.findtext("libelle_complet") or f.findtext("libelle") or ""
                if not F.fold(lab).startswith("but "):
                    continue
                fiche, how = F.rncp_of(f.findtext("identifiant"), lab, {}, ix, rr)
                if not fiche:
                    continue
                n += 1
                mine = words(F.fold(lab)[4:].partition(" parcours ")[2])
                theirs = words(rr[fiche]["intitule"].partition(":")[2])
                if not mine or not (mine == theirs or mine.startswith(theirs) or theirs.startswith(mine)):
                    bad.append(f"real: {lab!r} -> {rr[fiche]['intitule']!r}")
            info = f"; real: {n} BUT sheets linked to their own parcours"
    return not bad, f"differences {bad[:4]}{info}"


# ------------------------------------------------------------------------------------------------------------- formula
CONF_LOW = 0.4


def oracle_formation(omega: dict, method: str, jobs: dict, ins, comp) -> dict:
    tot = sum(omega.values())
    w = {m: v / tot for m, v in omega.items()}
    sc = {m: v for m, v in w.items() if (jobs.get(m) or {}).get("score")}
    st = sum(sc.values())
    groups: dict = {}
    for m, v in w.items():
        lines = (jobs.get(m) or {}).get("isco") or []
        pt = sum(x["poids"] for x in lines)
        for x in lines:
            groups[x["isco"][0]] = groups.get(x["isco"][0], 0) + v * x["poids"] / pt
    gs = sum(groups.values())
    div = 100 * -sum(p / gs * math.log(p / gs) for p in groups.values() if p > 0) / math.log(10) if gs else None
    cterm = 100 * comp["part_portable"] if comp else None
    scen, nat = {}, {}
    for s in ("S1", "S2", "S3"):
        a = sum(v / st * jobs[m]["scenarios"][s] for m, v in sc.items()) if st else None
        terms = [(a, 0.6), (ins, 0.1), (div, 0.15), (cterm, 0.15)]
        av = [(x, y) for x, y in terms if x is not None]
        scen[s] = round(sum(x * y for x, y in av) / sum(y for _, y in av), 1) if a is not None else None
        nat[s] = round((0.6 * a + 0.15 * div) / 0.75, 1) if a is not None and div is not None else None
    wm = lambda key: sum(v / st * jobs[m]["confiance"][key] for m, v in sc.items()) if st else 0.0  # noqa: E731
    cover = 0.6 * st + sum(y for x, y in ((ins, 0.1), (div, 0.15), (cterm, 0.15)) if x is not None)
    conf = min(wm("fraicheur"), {"direct": 1, "poursuite": 0.8, "famille": 0.5, "certification": 0.5}[method] * wm("donnees_observees"), wm("accord_sources"), cover)
    vals = [v for v in scen.values() if v is not None]
    ok = len(vals) == 3 and conf >= CONF_LOW
    return {"median": statistics.median(vals) if ok else None, "min": min(vals) if ok else None, "max": max(vals) if ok else None,
            "conf": round(conf, 3), "div": None if div is None else round(div, 1),
            "nat": statistics.median(nat.values()) if ok and None not in nat.values() else None}


def job(score, s1, s2, s3, isco, conf=(0.9, 1.0, 0.8), niveau="moyen"):
    return {"score": {"median": score} if score is not None else None, "scenarios": {"S1": s1, "S2": s2, "S3": s3},
            "confiance": {"fraicheur": conf[0], "donnees_observees": conf[1], "accord_sources": conf[2]},
            "isco": [{"isco": i, "poids": p} for i, p in isco], "repere": {"niveau": niveau}}


JOBS = {
    "m1": job(70, 66, 70, 71, [("2512", 1)], niveau="haut"),
    "m2": job(60, 55, 60, 62, [("3313", 2), ("4110", 1)]),
    "m3": job(50, 47, 50, 50, [("7212", 1)], conf=(0.9, 0.4, 0.7), niveau="bas"),
    "m4": job(None, None, None, None, [("9112", 1)], conf=(0, 0, 0)),
}
SKL = {"part_portable": 0.5, "n": 10}
CASES = [
    ({"m1": 1, "m2": 1, "m3": 1}, "direct", None, SKL),
    ({"m1": 3, "m2": 1}, "poursuite", 72.0, SKL),
    ({"m1": 1, "m4": 1}, "famille", None, None),             # half the outlets unscored: coverage and the observed term drop
    ({"m3": 1}, "famille", None, None),                      # 0.5 x 0.4 observed: insufficient
    ({"m4": 1}, "direct", None, SKL),                       # no scored job: no score at all
]


@check("RF3 formula: an independent R(f,s), renormalisation, entropy, confidence and main-jobs rule equal the module")
def rf3(c: Ctx):
    F = c.F()
    bad = []
    for i, (om, me, ins, comp) in enumerate(CASES):
        got = F.formation(om, me, JOBS, ins, comp)
        exp = oracle_formation(om, me, JOBS, ins, comp)
        s = got["score"] or {}
        if (s.get("median"), s.get("min"), s.get("max")) != (exp["median"], exp["min"], exp["max"]):
            bad.append(f"case {i}: score {s} vs {exp}")
        if abs(got["confiance"]["valeur"] - exp["conf"]) > 0.001:
            bad.append(f"case {i}: confidence {got['confiance']['valeur']} vs {exp['conf']}")
        if got["composantes"]["diversite"] != exp["div"]:
            bad.append(f"case {i}: diversity {got['composantes']['diversite']} vs {exp['div']}")
        if got.get("score_national") != exp["nat"]:
            bad.append(f"case {i}: national score {got.get('score_national')} vs {exp['nat']}")
        if got["score"] is None and got.get("scenarios"):
            bad.append(f"case {i}: scenarios without a score")
    first = F.formation(CASES[0][0], CASES[0][1], JOBS, CASES[0][2], CASES[0][3])["metiers"]
    if first["n_haut"] != 1 or first["n_bas"] != 1:
        bad.append("the outlets' repère counts")
    # main jobs: equal weights beyond the cut = none listed; a strict cut = the first ones
    many = {f"x{i}": 1.0 for i in range(F.TOP_JOBS + 3)}
    if F.formation(many, "famille", JOBS, None, None)["metiers"]["principaux"]:
        bad.append("an arbitrary pick of main jobs among equal weights")
    lead = dict(many, x0=5.0, x1=5.0, x2=5.0, x3=5.0, x4=5.0, x5=5.0, x6=5.0, x7=5.0)
    if [m for m, _ in F.formation(lead, "famille", JOBS, None, None)["metiers"]["principaux"]] != sorted(f"x{i}" for i in range(8)):
        bad.append("the heavier outlets are not listed")
    # owner, 2026-11-18 (re-set): through its masters with at least 1 master or 1 job
    table = {(1, 4): True, (1, 1): True, (0, 1): True, (1, 0): True, (0, 0): False, (3, 9): True}
    got_t = {k: F.enough_masters(*k) for k in table}
    if got_t != table:
        bad.append(f"enough_masters {got_t} != {table}")
    # invariants: a missing term is never a typed value; more portable skills never lower the score
    a = F.formation({"m1": 1, "m2": 1}, "direct", JOBS, None, {"part_portable": 0.3})["score"]["median"]
    b = F.formation({"m1": 1, "m2": 1}, "direct", JOBS, None, {"part_portable": 0.6})["score"]["median"]
    if not b > a:
        bad.append("more portable skills do not raise the score")
    return not bad, f"differences {bad[:4]}"


def oracle_repere(rows: dict, fili: dict) -> dict:
    by: dict = {}
    key = lambda d: tuple(k for k in ("metiers", "insertion", "diversite", "competences") if d["composantes"][k] is not None)  # noqa: E731
    for cod, d in rows.items():
        if d["score"]:
            by.setdefault((fili[cod], key(d)), []).append(d["score"]["median"])
    out = {}
    for cod, d in rows.items():
        if not d["score"]:
            out[cod] = None
            continue
        ref = by[(fili[cod], key(d))]
        v = d["score"]["median"]
        if len(ref) < 20 or len(set(ref)) < 5:
            out[cod] = ("-", "trop_peu" if len(ref) < 20 else "memes_debouches")
            continue
        lo = sum(x < v for x in ref) / len(ref)
        hi = sum(x > v for x in ref) / len(ref)
        out[cod] = "haut" if lo >= 0.8 else "bas" if hi >= 0.8 else "moyen"
    return out


def oracle_national(rows: dict) -> dict:
    vals = [d["score_national"] for d in rows.values() if d.get("score_national") is not None]
    out = {}
    for cod, d in rows.items():
        v = d.get("score_national")
        if v is None:
            out[cod] = None
            continue
        lo = sum(x < v for x in vals) / len(vals)
        hi = sum(x > v for x in vals) / len(vals)
        out[cod] = ("haut" if lo >= 0.8 else "bas" if hi >= 0.8 else "moyen", {"poursuite": "master", "famille": "autres"}.get(d["methode"]))
    return out


def got_national(rows):
    return {c: None if d.get("repere_national") is None else (d["repere_national"]["niveau"], d["repere_national"]["apres_etudes"])
            for c, d in rows.items()}


def got_repere(rows):
    return {c: None if d["repere"] is None else (d["repere"]["niveau"] or ("-", d["repere"]["raison"])) for c, d in rows.items()}


def crafted_rows():
    rnd = random.Random(3)
    rows, fili = {}, {}
    comp = lambda x: {"metiers": 60, "insertion": x, "diversite": 40, "competences": 50}  # noqa: E731
    for i in range(40):                                   # BTS: 40 distinct scores, same terms
        rows[f"b{i}"], fili[f"b{i}"] = {"score": {"median": 50 + i * 0.5}, "composantes": comp(None)}, "BTS"
    for i in range(6):                                    # same filière, an extra term: compared apart (too few)
        rows[f"i{i}"], fili[f"i{i}"] = {"score": {"median": 90 + i}, "composantes": comp(70)}, "BTS"
    for i in range(30):                                   # CPGE: one shared score
        rows[f"c{i}"], fili[f"c{i}"] = {"score": {"median": 66.8 if i % 2 else 66.9}, "composantes": comp(None)}, "CPGE"
    for i in range(25):                                   # ties at the top
        rows[f"t{i}"], fili[f"t{i}"] = {"score": {"median": 70 if i >= 15 else 50 + i + rnd.random()}, "composantes": comp(None)}, "BUT"
    rows["n"], fili["n"] = {"score": None, "composantes": comp(None)}, "BTS"
    order = list(range(30))
    rnd.shuffle(order)
    for i in order:                                       # LAS: distinct scores inserted in a shuffled order
        rows[f"l{i}"], fili[f"l{i}"] = {"score": {"median": 40 + i}, "composantes": comp(None)}, "Licence_Las"
    meth = ("direct", "poursuite", "famille")
    for i, (k, d) in enumerate(sorted(rows.items())):                      # national basis: its own score, every filière mixed
        d["methode"] = meth[i % 3]
        d["score_national"] = None if d["score"] is None else round(55 + rnd.random() * 15, 1) if i % 7 else 70.0
    return rows, fili


@check("RF4 repère: same filière, same terms, top / bottom 20 % by rank, ties never above, reasons; national repère on common terms")
def rf4(c: Ctx):
    F = c.F()
    rows, fili = crafted_rows()
    got = got_repere(F.with_repere(copy.deepcopy(rows), fili))
    exp = oracle_repere(rows, fili)
    diff = {k: (got[k], exp[k]) for k in exp if got[k] != exp[k]}
    bad = [f"{k}: {v}" for k, v in list(diff.items())[:4]]
    if got["b39"] != "haut" or got["b0"] != "bas" or got["i5"] != ("-", "trop_peu") or got["c0"] != ("-", "memes_debouches"):
        bad.append("the crafted landmarks")
    if got["n"] is not None:
        bad.append("a repère without a score")
    out = F.with_repere(copy.deepcopy(rows), fili)
    gn, en = got_national(out), oracle_national(rows)
    dn = [k for k in en if gn[k] != en[k]]
    if dn:
        bad.append(f"national repère differs for {dn[:3]}: {[(gn[k], en[k]) for k in dn[:2]]}")
    if {v[0] for v in en.values() if v} != {"haut", "moyen", "bas"}:
        bad.append("the crafted national levels do not cover the three levels")
    return not bad, f"differences {bad[:5]}"


# ------------------------------------------------------------------------------------------------------------- page
ECH_NAMES = ("ECHELLE", "echIdx", "echelleSpan", "echelleWords", "echelleNote", "echelleJauge")   # owner, 2026-11-22: the five levels
NAMES = ECH_NAMES + ("pc1d", "promoTxt", "robPc", "robInsPublie", "ROB_SCEN", "ROB_CONF", "robNum", "ROBF_REPERE", "ROBF_REPERE_NATIONAL", "ROBF_APRES", "ROBF_METHODE", "ROBF_VOISINE", "ROBF_ABSENT", "ROBF_LIEN", "robJobs", "robfFaits", "formationRobustesseCard")


def page_data():
    full = {
        "model_version": HOSTILE, "methode": "poursuite",
        "score": {"median": 66.2, "min": 64.0, "max": 66.6, "dependance_scenario": False}, "scenarios": {"S1": 64.0, "S2": 66.2, "S3": 66.6},
        "composantes": {"metiers": 74.6, "insertion": 79.6, "diversite": 40.6, "competences": 49.7},
        "confiance": {"niveau": "moyenne", "valeur": 0.55, "fraicheur": 0.9, "donnees_observees": 0.8, "accord_sources": 0.72, "couverture": 0.55},
        "metiers": {"n": 8, "n_notes": 7, "n_haut": 1, "n_bas": 0, "principaux": [{"id": "MET.1", "nom": HOSTILE, "poids": 0.5, "repere": "haut"}]},
        "competences": {"n": 195, "part_portable": 0.4974, "numeriques": 20, "ecologiques": 4},
        "master": {"n_masters": 2, "n_admis": 26, "insertion_masters": 1, "apres_master": {"n": 8, "n_notes": 7, "n_haut": 1, "n_bas": 0, "mediane": 74.6}},
        "diplome_seul": {"n": 4, "n_notes": 3, "n_haut": 0, "n_bas": 2, "mediane": 64.6},
        "rncp": {"fiche": "RNCP40114", "lien": "onisep", "apprentissage": True, "intitule": HOSTILE, "blocs": ["Bloc " + HOSTILE]},
        "repere": {"niveau": "haut", "filiere": "Licence" + HOSTILE, "n_formations": 2403, "part": 0.2},
        "score_national": 64.4, "repere_national": {"niveau": "bas", "n_formations": 12185, "part": 0.2, "apres_etudes": "master"},
        "echelle": {"niveaux": ["robuste"], "n_formations": 13176, "parts": [0.1, 0.3]},
    }
    same = copy.deepcopy(full)
    same["repere"] = {"niveau": None, "filiere": "CPGE", "n_formations": 809, "raison": "memes_debouches"}
    same["rncp"] = {"fiche": "RNCP1\" onmouseover=alert(1)", "lien": "titre", "apprentissage": False, "blocs": ["x"]}
    same["repere_national"] = {"niveau": "haut", "n_formations": 12185, "part": 0.2, "apres_etudes": "autres"}
    same["echelle"] = {"niveaux": ["robuste", "moyenne"], "n_formations": 13176, "parts": [0.1, 0.3]}
    none = copy.deepcopy(full)
    none["score"], none["scenarios"], none["repere"], none["score_national"], none["repere_national"] = None, None, None, None, None
    none["echelle"] = {"niveaux": ["robuste"], "n_formations": 13176, "parts": [0.1, 0.3]}   # stale: no score, so no level shown
    none["confiance"]["niveau"] = "faible"
    return full, same, none


@check("RF5 page: escaped, repère and facts first, score only in « Détail du calcul », diploma alone apart, master gain, RNCP")
def rf5(c: Ctx):
    if not all(RB.top(c.js, n) for n in NAMES):
        return False, "a renderer is missing from app.js"
    full, same, none = page_data()
    prog = RB.STUB + "const H = 18;\n" + "\n".join(RB.top(c.js, n) for n in NAMES) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([formationRobustesseCard(D.f), formationRobustesseCard(D.s), formationRobustesseCard(D.n), formationRobustesseCard(null)]));"""
    out = RB.node(prog, {"f": full, "s": same, "n": none})
    if out is None:
        return True, "node absent: not run"
    cf, cs, cn, c0 = out
    bad = []
    for i, h in enumerate((cf, cs, cn)):
        txt = re.sub(r"<[^>]+>", " ", h)
        if "<img" in h or "onmouseover" in h:
            bad.append(f"output {i}: unescaped")
        if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt, re.I):
            bad.append(f"output {i}: tutoiement")
        if re.search(r"(?i)condamn|menac|danger|disparaî|chance|garanti|probabilit|feu rouge", txt):
            bad.append(f"output {i}: an alarming word, a chance or a promise")
    lead, _, detail = cf.partition("<summary>Détail du calcul</summary>")
    first = lead.split("<ul")[0]
    nb = lambda t: t.replace("\u202f", " ").replace("\xa0", " ")  # noqa: E731
    # owner, 2026-11-22: the LEVEL leads (word + gauge + estimation + its reference count); the repères go into the detail
    if "<strong>Robuste</strong>" not in first or '<span class="estim">' not in first or 'class="ech"' not in first:
        bad.append("the level does not lead the card as an estimation with its gauge")
    if "parmi 13 176 formations Parcoursup" not in nb(first) or "ils arrivent après la licence et un master (bac+5)" not in first:
        bad.append("the level's reference count or the master caveat is missing before the facts")
    if "robustes de sa filière" in first or "toutes filières confondues" in first:
        bad.append("a repère still leads the card instead of the level")
    if re.search(r"Score :|sur 100,", lead.split("<h3>")[0]):
        bad.append("the score is shown before « Détail du calcul »")
    for w in ("8 métiers (7 estimés) : 1 parmi les 20 % de métiers les plus robustes", "50 sur 100 sont transférables", "20 touchent au numérique",
              "apprentissage", "Avec ce diplôme seul", "4 métiers (3 estimés) : 0 parmi", "Après un master de l'université",
              "score médian : 75 sur 100, contre 65 avec la licence seule", "Emploi stable 18 mois après ces masters : 80 %",
              "https://www.francecompetences.fr/recherche/rncp/40114/", "Bloc &lt;img"):
        if w not in lead:
            bad.append(f"lead lacks « {w} »")
    if "<strong>66</strong> sur 100" not in detail or "<strong>64</strong>" not in detail or "<strong>67</strong>" not in detail:
        bad.append("the score and its range are not in « Détail du calcul »")
    for w in ("fraîcheur", "liens observés", "accord des sources", "couverture", "Version du modèle", "RNCP", "ROME 4.0", "transverse"):
        if w not in cf:
            bad.append(f"card lacks « {w} »")
    # both repères (filière, national: owner, 2026-11-17) stay readable, in « Détail du calcul » (owner, 2026-11-22)
    if "Parmi les 20 % de formations les plus robustes de sa filière" not in detail \
            or "Parmi les 20 % de formations les moins robustes, toutes filières confondues" not in detail \
            or "parmi 12 185 formations" not in nb(detail):
        bad.append("the filière or national repère (or its count) is missing from « Détail du calcul »")
    if "base commune à toutes les formations (métiers visés et diversité) : <strong>64</strong>" not in detail:
        bad.append("the national score is not in « Détail du calcul »")
    if "Parmi les 20 % de formations les plus robustes, toutes filières confondues" not in cs or "souvent après d&#39;autres études" not in cs:
        bad.append("a formation not ranked in its filière loses its national repère or its caveat")
    if "Entre « robuste » et « dans la moyenne »" not in cs or "selon le scénario retenu" not in cs:
        bad.append("scenarios that disagree: both levels are not said")
    if "toutes filières" in cn or "base commune" in cn or 'class="ech"' in cn:
        bad.append("a national repère or a level without a score")
    if "ne les classons pas" not in cs or "robustes de sa filière" in cs or "francecompetences.fr/recherche/rncp/1" in cs:
        bad.append("shared outlets: no level said, or a link from a non-numeric fiche")
    if "Données insuffisantes" not in cn or re.search(r"Score :|Parmi les 20 % de formations", cn):
        bad.append("insufficient data still shows a number")
    if c0:
        bad.append("output without data")
    weak = copy.deepcopy(page_data()[0])
    weak["methode"], weak["master"] = "direct", {"n_masters": 1, "n_admis": 30, "insertion_masters": 0, "insuffisant": True,
                                               "apres_master": {"n": 3, "n_notes": 3, "n_haut": 1, "n_bas": 0, "mediane": 73.9}}
    out2 = RB.node(prog, {"f": weak, "s": same, "n": none})
    if out2 is not None and ("ne mènent qu&#39;à 3 métiers" not in out2[0] or "notée sur les métiers de la licence seule" not in out2[0]):
        bad.append("a licence scored on its own jobs does not say why its masters were set aside")
    if "ne mènent qu" in cf:
        bad.append("the insufficient-masters sentence on a licence scored through its masters")
    return not bad, f"differences {bad[:5]}"


@check("RF6 plumbing: build after the jobs, API, in « Emploi et métiers » after the jobs, sources, fingerprint, bundle, docs, tests")
def rf6(c: Ctx):
    bad = []
    b = (ROOT / "suptracker" / "build.py").read_text()
    i, j = b.find("robustesse.build(con,"), b.find("robustesse_formation.build(con,")
    if i < 0 or j < i:
        bad.append("build (after the jobs)")
    if '"robustesse": ROBF.for_formation(' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("API")
    emploi = re.search(r'\["emploi", "Emploi et métiers", `(.*?)`\]', c.js, re.S)
    body = emploi.group(1) if emploi else ""
    k, m = body.find("${formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })}"), body.find("${metiersCard(d.metiers)}")
    if k < 0 or m < 0 or k < m:                  # owner, 2026-11-24 (audit PR 5): the jobs first, the robustesse model after them
        bad.append("formation page")
    from suptracker import sources as SRC
    st = {s["key"]: s["status"] for s in SRC.SOURCES}
    if st.get("rncp_france_competences") != "en_ligne" or st.get("rome4_competences") != "en_ligne":
        bad.append("sources")
    wf = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    if "data/rncp/export-fiches-csv.zip" not in wf or "data/rncp/rome_toutes_donnees.zip" not in wf:
        bad.append("data workflow fingerprint")
    if "**/data/rncp/" not in (ROOT / ".vercelignore").read_text():
        bad.append(".vercelignore")
    if "## Robustesse 2035 des formations" not in (ROOT / "README.md").read_text():
        bad.append("README")
    if "Robustesse 2035 per formation" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    if "tests/test_robustesse_formations.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()) \
            or not (ROOT / "tests" / "test_robustesse_formations.py").exists():
        bad.append("tests / durations")
    return not bad, f"missing {bad}"


@check("RF7 real: stored blocks re-derived (skills, outlets, formula), every repère re-derived, coverage per filière")
def rf7(c: Ctx):
    if not (c.real and c.db):
        return True, "real mode off"
    import duckdb
    from suptracker import rapports as RP
    F = c.F()
    tx = RP.textes_path(c.db)
    tc = duckdb.connect(str(tx), read_only=True)
    try:
        have = {t for (t,) in tc.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        if "r35_formation" not in have:
            return True, "no r35_formation yet (data workflow not run)"
        rows = {k: json.loads(v) for k, v in tc.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
        jobs = {k: json.loads(v) for k, v in tc.execute("SELECT met_id, data FROM r35_metier").fetchall()}
        rn_rows = {k: json.loads(v) for k, v in tc.execute("SELECT fiche, data FROM r35_rncp").fetchall()}
    finally:
        tc.close()
    con = duckdb.connect(str(c.db), read_only=True)
    try:
        session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        fili = dict(con.execute("SELECT cod_aff_form, any_value(fili) FROM core.formation_year WHERE session = ? GROUP BY 1", [session]).fetchall())
        sheet: dict = {}
        for cod, fid in con.execute("SELECT DISTINCT cod_aff_form, for_id FROM core.onisep_link WHERE session = ? AND for_id IS NOT NULL", [session]).fetchall():
            sheet.setdefault(cod, set()).add(fid)
        sj: dict = {}
        for fid, mid in con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall():
            sj.setdefault(fid, set()).add(mid)
    finally:
        con.close()
    bad = []
    inh = {k: v for k, v in rows.items() if v.get("herite") or v.get("diplome_offre") or v.get("voisine") or v.get("certification")}
    rows = {k: v for k, v in rows.items() if k not in inh}       # borrowed blocks: RF13 (inherited), RF14 (own sheet), RF15 (neighbour), RF17 (certification)
    inh = {k: v for k, v in inh.items() if not v.get("voisine")}  # a neighbour-borrowing formation is a SIES formation
    if set(rows) - set(fili):
        bad.append(f"{len(set(rows) - set(fili))} blocks outside the latest campaign")
    if set(inh) & set(fili):
        bad.append("a SIES formation carries an inherited block")
    # repère of every formation
    exp = oracle_repere(rows, fili)
    diff = [k for k in rows if got_repere(rows)[k] != exp[k]]
    if diff:
        bad.append(f"repère differs for {len(diff)}, e.g. {diff[:3]}")
    gn, en = got_national(rows), oracle_national(rows)
    dn = [k for k in rows if gn[k] != en[k]]
    if dn:
        bad.append(f"national repère differs for {len(dn)}, e.g. {dn[:3]}")
    # owner, 2026-11-18: a licence scored through its masters only when they cover enough jobs
    for k, v in rows.items():
        m = v.get("master") or {}
        if v["methode"] == "poursuite" and not (m.get("n_masters", 0) >= 1 or v["metiers"]["n"] >= 1):
            bad.append(f"{k}: scored through too few masters")
            break
        if m.get("insuffisant") and (v["methode"] == "poursuite" or m.get("n_masters", 0) >= 1 or (m.get("apres_master") or {}).get("n", 0) >= 1):
            bad.append(f"{k}: flagged insufficient wrongly")
            break
    # direct outlets and the formula on a sample
    rnd = random.Random(11)
    direct = [k for k, v in rows.items() if v["methode"] == "direct"]
    n_ok = 0
    for k in rnd.sample(direct, min(150, len(direct))):
        om = {m: 1.0 for m in set().union(*(sj.get(f, set()) for f in sheet.get(k, ())))}
        if len(om) != rows[k]["metiers"]["n"]:
            bad.append(f"{k}: {len(om)} outlets vs {rows[k]['metiers']['n']}")
            continue
        comp = rows[k]["competences"]
        e = oracle_formation(om, "direct", jobs, None, comp)
        s = rows[k]["score"] or {}
        if (s.get("median"), s.get("min"), s.get("max"), rows[k].get("score_national")) != (e["median"], e["min"], e["max"], e["nat"]) \
                or abs(rows[k]["confiance"]["valeur"] - e["conf"]) > 0.001:
            bad.append(f"{k}: formula")
        n_ok += 1
    # skills of the stored fiches from the real files
    d = ROOT / "data" / "rncp"
    if (d / F.ROME_ZIP).exists():
        for k, v in rnd.sample(sorted(rows.items()), 400):
            fiche = (v.get("rncp") or {}).get("fiche")
            if fiche and v["competences"] != oracle_skills(set(rn_rows[fiche]["rome"]), d / F.ROME_ZIP):
                bad.append(f"{k}: skills")
                break
    # the API path: the stored block, with the main jobs named, their repère, and the RNCP fiche merged
    con = duckdb.connect(str(c.db), read_only=True)
    try:
        names = dict(con.execute("SELECT met_id, nom FROM core.onisep_metier").fetchall())
        for k in rnd.sample(sorted(rows), 40):
            api = F.for_formation(con.cursor(), k)
            if api is None:
                bad.append(f"{k}: the API reads no block")
                break
            exp = [{"id": m, "nom": names.get(m), "poids": w, "repere": (jobs.get(m, {}).get("repere") or {}).get("niveau")}
                   for m, w in rows[k]["metiers"]["principaux"]]
            fiche = (rows[k].get("rncp") or {}).get("fiche")
            if api["metiers"]["principaux"] != exp or api["score"] != rows[k]["score"] or api["repere"] != rows[k]["repere"] \
                    or (fiche and api["rncp"].get("blocs") != rn_rows[fiche]["blocs"]):
                bad.append(f"{k}: the API differs from the stored block")
                break
            if api.get("repere_national") != rows[k].get("repere_national"):
                bad.append(f"{k}: the API loses the national repère")
                break
        if F.for_formation(con.cursor(), "no-such-code") is not None:
            bad.append("a block for an unknown code")
    finally:
        con.close()
    per: dict = {}
    for k, f in fili.items():
        p = per.setdefault(f, [0, 0, 0])
        p[0] += 1
        p[1] += bool(rows.get(k, {}).get("score"))
        p[2] += bool((rows.get(k, {}).get("repere") or {}).get("niveau"))
        nv = (rows.get(k, {}).get("repere_national") or {}).get("niveau")
        if nv:
            p.append(nv)
    cov = sum(p[1] for p in per.values()) / max(1, len(fili))
    top = ", ".join(f"{f} {p[1]}/{p[0]} ({p[2]} situées dans la filière; national haut {p[3:].count('haut')} bas {p[3:].count('bas')})"
                    for f, p in sorted(per.items(), key=lambda x: -x[1][0])[:11])
    return not bad, f"differences {bad[:4]}; {n_ok} direct blocks re-derived; scored {cov:.1%}; {top}"


# ------------------------------------------------------------------------------------------------------- Mes vœux + method
VX_NAMES = ("esc",) + ECH_NAMES + ("ROB_WORD", "ROB_RAISON", "robDecode", "robVoeuxCard")


@check("RF9 Mes vœux: the robustesse level beside each zone, never merged or sorted by; compact payload re-derived; escaped")
def rf9(c: Ctx):
    import duckdb
    F = c.F()
    bad = []
    # compact(): every formation's levels, re-derived from the stored blocks (a crafted table in core)
    rows = {"1": {"repere": {"niveau": "haut"}, "repere_national": {"niveau": "bas", "apres_etudes": "master"}, "echelle": {"niveaux": ["robuste"]}},
            "2": {"repere": {"niveau": None, "raison": "memes_debouches"}, "repere_national": {"niveau": "haut", "apres_etudes": "autres"},
                  "echelle": {"niveaux": ["robuste", "moyenne"]}},
            "3": {"repere": {"niveau": None, "raison": "trop_peu"}, "repere_national": None},
            "4": {"repere": None, "repere_national": None},
            "5": {"repere": {"niveau": "moyen"}, "repere_national": {"niveau": "moyen", "apres_etudes": None}},
            "6": {"repere": {"niveau": "moyen"}, "repere_national": {"niveau": "haut", "apres_etudes": None}, "herite": {"source": "diplome", "formations": 2}},
            "7": {"repere": None, "repere_national": {"niveau": "bas", "apres_etudes": None}, "certification": {"fiches": ["RNCP1"], "rome": ["A1"]}}}
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.r35_formation (cod_aff_form VARCHAR, data VARCHAR)")
    con.executemany("INSERT INTO core.r35_formation VALUES (?, ?)", [(k, json.dumps(v)) for k, v in rows.items()])
    got = F.compact(con)
    exp = {"filiere": {"haut": "1", "moyen": "5,6"}, "national": {"bas": "1,7", "haut": "2,6", "moyen": "5"},
           "raison": {"memes_debouches": "2", "trop_peu": "3"}, "apres": {"autres": "2", "master": "1"}, "herite": {"diplome": "6"},
           "voisine": {}, "certification": {"rncp": "7"}, "echelle": {"moyenne": "2", "robuste": "1,2"}}
    if got != exp:
        bad.append(f"compact {got} != {exp}")
    pc_src = (ROOT / "suptracker" / "precomp.py").read_text()
    if '"robustesse": RF.compact(con)' not in pc_src:
        bad.append("the lists' payload (/api/reconnaissance) does not carry the repères")
    # the page: decoded from the payload, both repères in their own cells beside the zone, escaped, nothing combined or sorted
    if not all(RB.top(c.js, n) for n in VX_NAMES[1:]):
        return False, "a renderer is missing from app.js"
    prog = RB.STUB + "\n".join(RB.top(c.js, n) for n in VX_NAMES[1:]) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      var RECO = { rob: robDecode(D.p) };
      const zone = (v) => `<span class="zone">Z-${v.zone}</span>`;
      process.stdout.write(JSON.stringify([robVoeuxCard(D.v, zone), robVoeuxCard(D.reo), robVoeuxCard([]), robVoeuxCard(D.none, zone)]));"""
    # Codex (PR #83): two courses of one establishment must stay apart: terminale rows carry `filiere` + `complement`, the
    # reorientation rows (/api/reorientation/voeux) the course name in `formation`
    vx = [{"cod_aff_form": "1", "status": "ok", "etablissement": RB.HOSTILE, "filiere": "BTS", "complement": "Option Ω" + RB.HOSTILE,
           "zone": "cible"},
          {"cod_aff_form": "2", "status": "ok", "etablissement": "Lycée B", "filiere": "CPGE", "zone": "securite"},
          {"cod_aff_form": "3", "status": "ok", "etablissement": "C", "filiere": "x", "zone": "ambitieux"},
          {"cod_aff_form": "9", "status": "absente", "zone": None}]
    reo = [{"cod_aff_form": "1", "status": "ok", "etablissement": "Université A", "formation": "Licence - Droit Ψ" + RB.HOSTILE},
           {"cod_aff_form": "2", "status": "ok", "etablissement": "Université A", "formation": "Licence - Histoire Φ"},
           {"cod_aff_form": "3", "status": "ok", "etablissement": "C", "formation": "BUT"}, {"cod_aff_form": "9", "status": "absente"}]
    out = RB.node(prog, {"p": exp, "v": vx, "reo": reo, "none": [{"cod_aff_form": "77", "status": "ok", "etablissement": "Z", "zone": "cible"}]})
    if out is None:
        return not bad, "node absent: page not run"
    full, nozone, empty, none = out
    if "<img" in full or "<img" in nozone:
        bad.append("an unescaped stored string")
    trs = re.findall(r"<tr>(.*?)</tr>", full, re.S)
    # owner, 2026-11-22: one cell per vœu for the robustesse LEVEL (word + gauge), beside the zone's own cell
    if len(trs) != 4 or any(len(re.findall(r"<td", t)) != 3 for t in trs):
        bad.append("each vœu must have its own row with three cells (formation, zone, robustesse 2035)")
    else:
        cells = [re.findall(r"<td[^>]*>(.*?)</td>", t, re.S) for t in trs]
        if "Z-cible" not in cells[0][1] or "<strong>Robuste</strong>" not in cells[0][2] or 'class="ech"' not in cells[0][2] \
                or "métiers après un master" not in cells[0][2]:
            bad.append("row 1: the zone and the level (word and gauge) are not each in their own cell")
        if "Entre « robuste » et « dans la moyenne »" not in cells[1][2] or "après d&#39;autres études" not in cells[1][2].replace("'", "&#39;"):
            bad.append("row 2: two levels or the later-studies caveat are missing")
        if "pas d" not in cells[2][2] or "ech-c" in cells[2][2]:
            bad.append("row 3: a formation with no level must say so, never a gauge")
        if [re.search(r'href="#/f/(\d+)"', t).group(1) if re.search(r'href="#/f/(\d+)"', t) else None for t in trs] != ["1", "2", "3", None]:
            bad.append("the rows are not in the list's own order")
        if any("Z-" in x for row in cells for x in row[2:]) or any("Robuste" in row[1] or "ech-c" in row[1] for row in cells):
            bad.append("a zone and a repère share a cell")
    if "Option Ω" not in full:
        bad.append("a terminale row loses the course's complement (two courses of one filière look alike)")
    if "Licence - Droit Ψ" not in nozone or "Licence - Histoire Φ" not in nozone:
        bad.append("a reorientation row loses the course name (/api/reorientation/voeux sends it as `formation`)")
    if "Zone pour votre profil" in nozone or "Z-" in nozone:
        bad.append("outside terminale (no zone) the card shows a zone column")
    if empty or none:
        bad.append("a card with no vœu or no repère")
    txt = re.sub(r"<[^>]+>", " ", full)
    if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"(?i)note globale|score combin|probabilit|garanti", txt):
        bad.append("tutoiement, a combined mark or a promise")
    if "jamais réunis en une seule note" not in full or "ni des chances d'admission, ni des promesses d'emploi" not in full.replace("&#39;", "'") \
            or 'href="#/info/robustesse"' not in full:
        bad.append("the card does not say the two are never merged, or lacks its caveat or the method link")
    for fn in ("viewVoeux", "viewVoeuxReo"):
        body = c.js[c.js.find(f"async function {fn}("):]
        body = body[: body.find("\n}\n") + 3]
        if "robVoeuxCard(d.voeux" not in body:
            bad.append(f"{fn} does not show the comparator")
    if "rob: robDecode(d.robustesse)" not in c.js:
        bad.append("recoLoad does not decode the repères")
    return not bad, f"differences {bad[:5]}"


@check("RF10 method page: a trust page, numbers read from the modules, every model version in the changelog, plain words")
def rf10(c: Ctx):
    F = c.F()
    M = c.M(F)
    from suptracker import cache as CA
    from suptracker import legal as LG
    from suptracker import robustesse as RJ
    bad = []
    html = M.page()
    pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
    for w in (F.W_JOBS, F.W_INS, F.W_DIV, F.W_COMP, RJ.REPERE_SHARE):
        if pct(w) not in html:
            bad.append(f"the page does not print {pct(w)} read from the modules")
    if f"{round(100 * RJ.RANK_GAP)} points d'écart" not in html:
        bad.append("the rank gap is not printed in points")
    versions = " ".join(v for v, _, _ in M.CHANGELOG)
    for v in (RJ.MODEL_VERSION, F.MODEL_VERSION):
        if v not in versions or v not in html:
            bad.append(f"model version {v} missing from the changelog or the page")
    if "robustesse" not in LG.SLUGS or LG.page("robustesse") is None or (CA.policy("/robustesse") or (None,))[0] != CA.PAGE:
        bad.append("not served as a trust page (slug, page, cache policy)")
    if '"robustesse"];' not in c.js or "|nos-chiffres|robustesse)" not in c.js:
        bad.append("the app does not open #/info/robustesse or /robustesse")
    txt = re.sub(r"<[^>]+>", " ", html)
    if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"(?i)probabilit|garanti|vos chances", txt):
        bad.append("tutoiement, a probability or a promise")
    long = [x for x in re.split(r"(?<=[.!?:])\s+", " ".join(txt.split())) if len(x.split()) > 30]
    if long:
        bad.append(f"sentences over 30 words: {long[:1]}")
    if "<script" in html or "javascript:" in html:
        bad.append("script in the page")
    return not bad, f"differences {bad[:5]}"


# ------------------------------------------------------------------------- RF11: insertion beside the score, search filters
FILTER_NAMES = ECH_NAMES + ("CARTE_ROB", "robReady", "robLevel", "CARTE_FGROUPS", "carteHas", "carteFilter", "carteFacets", "carteCommon",
                             "carteInLieu", "robCardLine")
FILTER_STUB = """
const CARTE_R3 = [], fiOptions = () => [], filtreBand = () => null, carteZone = () => "autre", carteText = () => "", haversineKm = () => 0;
const JURY_KEYS = ["res", "eng", "mot", "se", "met"], juryLevel = () => null, juryCuts = () => null;
"""
FILTER_PROG = """
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
var RECO = { rob: robDecode(D.p) };
const ref = {};
for (const [g, os] of Object.entries(D.opts)) for (const o of os) ref[g + ":" + o] = carteFilter(D.rows, { [g]: [o] }).map((f) => f.cod_aff_form);
const both = carteFilter(D.rows, { robf: ["haut"] }).map((f) => f.cod_aff_form);   // owner, 2026-11-27: a stored filière filter is ignored
const fac = carteFacets(D.rows, { robn: ["plus_exposee"] }, null, D.opts);
const facets = Object.fromEntries(Object.entries(fac).map(([g, m]) => [g, Object.fromEntries(m)]));
const lines = D.rows.map((f) => robCardLine(f.cod_aff_form));
RECO = { rob: robDecode({ filiere: {}, national: {}, raison: {}, apres: {} }) };     // tables missing: an empty payload (Codex)
const empty = carteFilter(D.rows, { robn: ["plus_exposee"] }).length;
RECO = null;
const none = carteFilter(D.rows, { robn: ["plus_exposee"] }).length;
process.stdout.write(JSON.stringify({ ref, both, facets, lines, none, empty, noline: robCardLine("1") }));"""


@check("RF11 beside the score: published BTS / BUT insertion apart, never in it; search filters by the five levels (the filière filter gone, its repère kept), counted, never sorted by")
def rf11(c: Ctx):
    bad = []
    if not all(RB.top(c.js, n) for n in NAMES + FILTER_NAMES + VX_NAMES[1:]):
        return False, "a renderer is missing from app.js"
    # 1. the published insertion block (robInsPublie), alone and inside the card
    full, _, none = page_data()
    bts1 = {"annee": "cumul 2023-2024", "rows": [{"libelle_formation": HOSTILE, "taux_emploi_6": 61.0, "taux_poursuite": 45.5}]}
    bts2 = {"annee": "cumul 2023-2024", "rows": [{"libelle_formation": "option A " + HOSTILE, "taux_emploi_6": 40.0, "taux_poursuite": None},
                                                {"libelle_formation": "option B", "taux_emploi_6": 60.0, "taux_poursuite": 30.0}]}
    ins = lambda emp, st, promo="2024": {"promo": promo, "pooled": False, "tx_sortants_en_emploi_sal_fr_18": emp, "tx_sortants_en_emploi_stable_18": st}
    but1 = {"specialite": ins(88.2, 70.1, HOSTILE), "total": ins(99.0, 99.0), "france_specialite": ins(77.0, 77.0)}
    but2 = {"specialite": None, "total": ins(81.0, 66.0), "france_specialite": ins(77.0, 77.0)}
    but3 = {"specialite": None, "total": None, "france_specialite": ins(77.3, None)}
    prog = RB.STUB + "const H = 18;\n" + "\n".join(RB.top(c.js, n) for n in NAMES) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([robInsPublie(D.b1), robInsPublie(D.b2), robInsPublie(null, D.u1), robInsPublie(null, D.u2),
        robInsPublie(null, D.u3), robInsPublie({ rows: [] }, null), robInsPublie(null, {}), formationRobustesseCard(D.f, { ins: D.b1 }),
        formationRobustesseCard(D.n, { but: D.u1 })]));"""
    out = RB.node(prog, {"b1": bts1, "b2": bts2, "u1": but1, "u2": but2, "u3": but3, "f": full, "n": none})
    if out is None:
        return True, "node absent: not run"
    b1, b2, u1, u2, u3, e1, e2, cf, cn = out
    nb = lambda h: h.replace("\u202f", " ").replace("\xa0", " ")
    if "<img" in "".join(out):
        bad.append("an unescaped stored string")
    if "61,0 %" not in nb(b1) or "45,5 %" not in nb(b1) or "sortis en 2023-2024" not in b1 or "&lt;img" in b1:
        bad.append("BTS: the published rates, the class or the single-row rule")
    if "option A &lt;img" not in b2 or "option B" not in b2 or b2.count("<li>") != 2 or "non publié" not in b2 or "50,0" in b2 \
            or "chaque option à part" not in b2:
        bad.append("BTS options: each named on its own line, a masked value said, never averaged")
    if "88,2 %" not in nb(u1) or "70,1 %" not in nb(u1) or "99,0" in u1 or "Cette spécialité dans l&#39;université" not in u1 \
            or "18 mois" not in u1 or "ne sont pas comptés" not in u1:
        bad.append("BUT: the specialty of the university first, its two published rates, the leavers caveat")
    if "Tous les BUT de l&#39;université" not in u2 or "81,0 %" not in nb(u2) or "en France" not in u3 or "non publié" not in u3:
        bad.append("BUT fallbacks: university total, then the specialty in France, a masked rate said")
    if e1 or e2:
        bad.append("a block with nothing published")
    for h in (b1, u1):
        if "jamais dedans" not in h or "pas des chances d&#39;emploi" not in h.replace("'", "&#39;"):
            bad.append("the block does not say it stays out of the score, or lacks its caveat")
    lead, _, detail = cf.partition("<summary>Détail du calcul</summary>")
    if "À côté : l&#39;insertion publiée" not in lead.replace("'", "&#39;") or "61,0 %" in nb(detail):
        bad.append("the block is not beside the repères, before the calculation")
    if "À côté" not in cn or "88,2 %" not in nb(cn):
        bad.append("with no estimate, the published insertion disappears")
    rf_src = c.src["robf"]
    if re.search(r"for_bts|for_but|taux_emploi|inserjeunes", rf_src, re.I):
        bad.append("the formation model reads the BTS / BUT insertion (it must stay out of the score)")
    # 2. the search filters, re-derived from the compact payload: the filière repère, and the FIVE levels (owner, 2026-11-22),
    # a formation between two levels kept by either
    lv = ["haut", "moyen", "bas", None]
    E = ["tres_robuste", "robuste", "moyenne", "plus_exposee", "tres_exposee"]
    spans = [[e] for e in E] + [[E[k], E[k + 1]] for k in range(4)] + [None]
    rows, p = [], {"filiere": {}, "national": {}, "raison": {}, "apres": {}, "echelle": {}}
    exp = {}
    for i in range(40):
        cod = str(100 + i)
        a, b = lv[i % 4], spans[(i // 4) % len(spans)]
        if a:
            p["filiere"].setdefault(a, []).append(cod)
        elif i % 8 == 3:
            p["raison"].setdefault("memes_debouches", []).append(cod)
        for e in b or []:
            p["echelle"].setdefault(e, []).append(cod)
        rows.append({"cod_aff_form": cod, "statut": "public"})
        exp[cod] = (a or "sans", b or ["sans"])
    rows.append({"cod_aff_form": "X1", "statut": "prive_app", "stats": False})          # an apprenticeship offer: no repère
    exp["X1"] = ("sans", ["sans"])
    payload = {k: {lvl: ",".join(v) for lvl, v in d.items()} for k, d in p.items()}
    opts = {"robn": E + ["sans"]}
    fprog = RB.STUB + FILTER_STUB + "\n".join(RB.top(c.js, n) for n in ("robDecode",) + FILTER_NAMES) + FILTER_PROG
    o = RB.node(fprog, {"p": payload, "rows": rows, "opts": opts})
    for g, k in (("robn", 1),):
        for lvl in opts[g]:
            want = [cod for cod, e in exp.items() if (lvl in e[k] if k else e[k] == lvl)]
            if sorted(o["ref"][f"{g}:{lvl}"]) != sorted(want):
                bad.append(f"filter {g}={lvl}: {len(o['ref'][f'{g}:{lvl}'])} kept, {len(want)} expected")
    if sorted(o["both"]) != sorted(exp):
        bad.append("a filière filter kept from an earlier visit still filters (owner, 2026-11-27: the filter is gone)")
    want_n = {lvl: sum(1 for cod in exp if lvl in exp[cod][1]) for lvl in opts["robn"]}
    if o["facets"]["robn"] != want_n:
        bad.append("the counts beside the options are not those of the other groups' selection")
    if o["empty"] != len(rows):
        bad.append("an empty repères payload (tables missing) filters every formation out (Codex, PR #84)")
    if o["none"] != len(rows):
        bad.append("repères not loaded: the filter must keep every formation (and the dropdowns are hidden)")
    for f, line in zip(rows, o["lines"]):
        a, b = exp[f["cod_aff_form"]]
        if b == ["sans"]:
            if line:
                bad.append("a card line with no level")
            continue
        names = {"tres_robuste": "Très robuste", "robuste": "Robuste", "moyenne": "Dans la moyenne", "plus_exposee": "Plus exposée",
                 "tres_exposee": "Très exposée"}
        want = names[b[0]] if len(b) == 1 else f"Entre « {names[b[0]].lower()} » et « {names[b[1]].lower()} »"
        if "estimation" not in line or want not in line or 'class="ech"' not in line or "de sa filière" in line:
            bad.append(f"a card line without its label, its level ({want}) or its gauge")
            break
    if o["noline"]:
        bad.append("a card line without the repères loaded")
    # a level the payload never sends is never printed
    q = RB.node(RB.STUB + "\n".join(RB.top(c.js, n) for n in ECH_NAMES + ("robCardLine",)) + """
      var RECO = { rob: { filiere: { "1": "<img src=x>" }, national: { "1": "zz" }, echelle: { "1": ["<img src=x>", "zz"] } } };
      process.stdout.write(JSON.stringify(robCardLine("1")));""", {})
    if q:
        bad.append("an unknown level printed on a card")
    view = c.js[c.js.index("async function viewCarte("): c.js.index("\n// ---- lot 2 (Claude design guidelines)")]
    start = view.index("const listed = kept.filter(")
    sort = view[start: view.index('document.getElementById("cs-status")', start)]   # the end after the start (draw's guard names it too)
    wiring = {
        "the groups in the dropdowns": "...CARTE_ROB, ...juryGroups()];" in c.js and '"robn", ...JURY_KEYS' in c.js,
        "the filière filter is gone (owner, 2026-11-27)": '"robf"' not in RB.top(c.js, "CARTE_ROB") and '"robf"' not in RB.top(c.js, "CARTE_FGROUPS")
                                                          and 'g === "robf"' not in RB.top(c.js, "carteHas"),
        "the filière repère is still read (kept in the payload)": "filiere" in RB.top(c.js, "robDecode"),
        "hidden when the repères did not load or are empty": '.filter(([gr]) => (robOk || !gr.startsWith("rob"))' in view
                                                              and "const robOk = robReady();" in view,
        "estimation label and method link in the dropdowns": 'estimTag("modèle de SupCompass")} <a href="#/info/robustesse">' in view,
        "card line on the formations with statistics": "    ${robCardLine(f.cod_aff_form)}`}" in c.js,
        "never sorted by a repère": "rob" not in sort.lower(),
        "help texts": "robf" not in RB.top(c.js, "FI_HELP") and "robn" in RB.top(c.js, "FI_HELP"),
        "the formation page passes its insertion": "formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })" in c.js,
    }
    bad += [k for k, v in wiring.items() if not v]
    return not bad, f"differences {bad[:5]}"


@check("RF12 L'essentiel: the robustesse tile (the level in words + gauge, estimation; no score; none invented), opens « Emploi et métiers »")
def rf12(c: Ctx):
    names = ECH_NAMES + ("robNum", "formationRobTile")
    if not all(RB.top(c.js, n) for n in names):
        return False, "a renderer is missing from app.js"
    full, same, none = page_data()
    prog = RB.STUB + "\n".join(RB.top(c.js, n) for n in names) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([formationRobTile(D.f), formationRobTile(D.s), formationRobTile(D.n), formationRobTile(null),
        formationRobTile(D.t)]));"""
    trop = copy.deepcopy(full)
    trop["repere"] = {"niveau": None, "raison": "trop_peu"}
    trop["repere_national"] = {"niveau": "moyen"}
    trop["echelle"] = {"niveaux": ["<img src=x>"]}                     # an unknown level is never printed
    out = RB.node(prog, {"f": full, "s": same, "n": none, "t": trop})
    if out is None:
        return True, "node absent: not run"
    f, sm, n, z, t = out
    bad = []
    if "pas de niveau" not in t or 'class="ech"' in t:
        bad.append("an unknown level is printed instead of « pas de niveau »")
    # owner, 2026-11-22: the LEVEL in words (one, or « entre … et … » when the scenarios disagree), its gauge and the estimation
    # label; never the score « / 100 » nor a repère (both in « Détail du calcul » of « Emploi et métiers »)
    if ">Robuste<" not in f or 'class="ech"' not in f or "parmi les 20 % de formations suivantes" not in f or "estimation" not in f:
        bad.append("the level, its gauge, its meaning or the estimation label is missing")
    if "Entre « robuste » et « dans la moyenne »" not in sm or "selon le scénario retenu" not in sm:
        bad.append("scenarios that disagree: both levels are not said")
    if any("/ 100" in x or "de sa filière" in x or "toutes les formations" in x for x in (f, sm, t)):
        bad.append("the tile still shows the score or a repère")
    if "/ 100" in n or "données insuffisantes" not in n or ">Robuste<" in n or 'class="ech"' in n or "/ 100" in z or "pas d'estimation" not in z:
        bad.append("a number without a score, or the absence not said")
    if any('data-goto="emploi"' not in x for x in out) or "<img" in "".join(out):
        bad.append("the tile does not open « Emploi et métiers », or is not escaped")
    sb = RB.top(c.js, "summaryBand")
    if "${formationRobTile(d.robustesse)}" not in sb:
        bad.append("the tile is not in L'essentiel")
    if re.search(r"\bchances?\b|promesse|garanti", re.sub(r"<[^>]+>", " ", "".join(out)), re.I):
        bad.append("a chance or a promise")
    return not bad, f"differences {bad[:4]}"


SOURCE_MUTANTS = [
    ("js", "level without its estimation label", '${esc(echelleNote(niv))} ${estimTag("", false, true)}`;', '${esc(echelleNote(niv))}`;', "RF12"),
    ("js", "gauge dropped from the tile", '    : `${echelleJauge(niv)}<span class="sr-only">', '    : `<span class="sr-only">', "RF12"),
    ("js", "a level with no score", '  const words = s ? echelleWords(niv) : "";', '  const words = echelleWords(niv);', "RF12"),
    ("js", "the score back in the tile", '<span class="sum-value sum-words">${words ? esc(words) : "—"}</span>', '<span class="sum-value sum-words">${s ? `${robNum(s.median)} / 100` : "—"}</span>', "RF12"),
    ("js", "both levels not said", '  return sp[0] === sp[1] ? ECHELLE[sp[0]][1] : `Entre', '  return sp[0] === sp[0] ? ECHELLE[sp[0]][1] : `Entre', "RF12"),
    ("js", "an unknown level accepted", '  if (!ix.length || ix.some((i) => i < 0)) return null;', '  if (!ix.length) return null;', "RF12"),
    ("js", "tile out of the summary", "      ${formationRobTile(d.robustesse)}\n", "", "RF12"),
    ("robf", "portable threshold 19", "rome[\"partage\"].get(o, 0) >= PORTABLE_SHEETS", "rome[\"partage\"].get(o, 0) >= PORTABLE_SHEETS - 1", "RF1"),
    ("robf", "technique counted portable", 'C[o]["sous_cat"] == "Transverse" or', 'C[o]["sous_cat"] != "Technique expert" or', "RF1"),
    ("robf", "inactive fiches read", 'r["Actif"] == "ACTIVE"', 'r["Actif"] != ""', "RF1"),
    ("robf", "apprenticeship from any route", 'any("apprentissage" in x.lower() for x in v["voies"])', "bool(v[\"voies\"])", "RF1"),
    ("robf", "empty fiche picked", 'ok = [k for k in fiches or () if rncp[k]["blocs"] or rncp[k]["rome"]]', "ok = list(fiches or ())", "RF2"),
    ("robf", "inactive first", "key=lambda k: (rncp[k][\"actif\"], date(k), k)", "key=lambda k: (date(k), k)", "RF2"),
    ("robf", "two masters required", "MIN_MASTERS, MIN_MASTER_JOBS = 1, 1", "MIN_MASTERS, MIN_MASTER_JOBS = 2, 1", "RF3"),
    ("robf", "five jobs required", "MIN_MASTERS, MIN_MASTER_JOBS = 1, 1", "MIN_MASTERS, MIN_MASTER_JOBS = 0, 5", "RF3"),
    ("robf", "masters rule needs both", "return n_masters >= MIN_MASTERS or n_jobs >= MIN_MASTER_JOBS", "return n_masters >= MIN_MASTERS and n_jobs >= MIN_MASTER_JOBS", "RF3"),
    ("js", "insufficient masters not said", "  if (r.master && r.master.insuffisant) out.push(", "  if (false) out.push(", "RF5"),
    ("robf", "another parcours substituted", '        f = pick(but_parcours(idx.get(("BUTsp", tight(sp)), {}), pa), rncp)',
     '        f = pick(but_parcours(idx.get(("BUTsp", tight(sp)), {}), pa), rncp) or pick([x for v in idx.get(("BUTsp", tight(sp)), {}).values() for x in v], rncp)', "RF2"),
    ("robf", "ambiguous prefix accepted", "return parcours[hits[0]] if len(hits) == 1 else []", "return parcours[hits[0]] if hits else []", "RF2"),
    ("robf", "spelling not folded", '    return fold(s).replace(" ", "")', "    return fold(s)", "RF2"),
    ("robf", "options kept", 'return re.split(r" options? | parcours | specialite ", " " + fold(title) + " ")[0].strip()', "return fold(title)", "RF2"),
    ("robf", "insertion weight 0.15", "W_JOBS, W_INS, W_DIV, W_COMP = 0.60, 0.10, 0.15, 0.15", "W_JOBS, W_INS, W_DIV, W_COMP = 0.60, 0.15, 0.15, 0.15", "RF3"),
    ("robf", "entropy over 9 groups", "ISCO_GROUPS = 10", "ISCO_GROUPS = 9", "RF3"),
    ("robf", "famille as sure as direct", '"famille": 0.5, ', '"famille": 1.0, ', "RF3"),
    ("robf", "score with low confidence", "shown = len(vals) == 3 and conf >= RJ.CONF_LOW", "shown = len(vals) == 3", "RF3"),
    ("robf", "unscored jobs count", "scored = {m: w for m, w in omega.items() if (jobs.get(m) or {}).get(\"score\")}", "scored = dict(omega)", "RF3"),
    ("robf", "arbitrary main jobs", "return ranked[:TOP_JOBS] if ranked[TOP_JOBS - 1][1] > ranked[TOP_JOBS][1] else []", "return ranked[:TOP_JOBS]", "RF3"),
    ("robf", "terms mixed", 'by.setdefault((fili.get(cod), terms_key(d)), [])', 'by.setdefault((fili.get(cod), ""), [])', "RF4"),
    ("robf", "terms mixed (read)", "ref = by[(fili.get(cod), terms_key(d))]", "ref = [x for (f, _), v in by.items() if f == fili.get(cod) for x in v]", "RF4"),
    ("robf", "no distinct-score rule", "if len(ref) >= MIN_FILIERE and len(set(ref)) >= MIN_DISTINCT:", "if len(ref) >= MIN_FILIERE:", "RF4"),
    ("robf", "national on every term", "common[s] = round(_wmean([(a, W_JOBS), (div, W_DIV)]), 1) if a is not None and div is not None else None",
     "common[s] = scen[s]", "RF3"),
    ("robf", "national without the caveat", '"apres_etudes": {"poursuite": "master", "famille": "autres"}.get(d["methode"])}', '"apres_etudes": None}', "RF4"),
    ("robf", "filière lists unsorted", "    for ref in by.values():\n        ref.sort()\n", "", "RF4"),
    ("robf", "national ties count as below", "below = bisect.bisect_left(others, v) / n", "below = bisect.bisect_right(others, v) / n", "RF4"),
    ("js", "no level line", "${vois}${lvl}${list}", "${vois}${list}", "RF5"),
    ("js", "master caveat dropped", '${(qn && qn.apres_etudes) ? ` · ${esc(ROBF_APRES[qn.apres_etudes] || "")}` : ""}', "", "RF5"),
    ("robf", "compact drops the national repère", '            acc["national"].setdefault(n["niveau"], []).append(cod)', "            pass", "RF9"),
    ("robf", "compact drops the reasons", '            acc["raison"].setdefault(q["raison"], []).append(cod)', "            pass", "RF9"),
    ("js", "zone and level merged", '      ${zcol ? `<td data-label="Zone pour votre profil">${zoneOf(v)}</td>` : ""}\n      <td data-label="Robustesse 2035">${level(v.cod_aff_form)}</td>',
     '      <td data-label="Robustesse 2035">${zcol ? zoneOf(v) : ""} ${level(v.cod_aff_form)}</td>', "RF9"),
    ("js", "comparator rows sorted by repère", "const body = rows.map(", "const body = [...rows].sort((a, b) => (R.national[b.cod_aff_form] || \"z\").localeCompare(R.national[a.cod_aff_form] || \"z\")).map(", "RF9"),
    ("js", "comparator name unescaped", "${esc(v.etablissement || v.cod_aff_form)}", "${v.etablissement || v.cod_aff_form}", "RF9"),
    ("js", "comparator drops the complement", '${v.complement ? ` · ${esc(v.complement)}` : ""}</div>`}</td>\n      ${zcol', '</div>`}</td>\n      ${zcol', "RF9"),
    ("js", "comparator ignores the reorientation course name", '${esc(v.filiere || v.formation || "")}${v.complement', '${esc(v.filiere || "")}${v.complement', "RF9"),
    ("js", "comparator complement unescaped", '` · ${esc(v.complement)}` : ""}</div>`}</td>\n      ${zcol', '` · ${v.complement}` : ""}</div>`}</td>\n      ${zcol', "RF9"),
    ("js", "no comparator in Mes vœux", "${robVoeuxCard(d.voeux, (v) =>", "${(() => \"\")(d.voeux, (v) =>", "RF9"),
    ("methode", "a version missing from the changelog", '    ("2027.2 / 2027.2-f", "17 novembre 2026",', '    ("2027.9", "17 novembre 2026",', "RF10"),
    ("methode", "a weight typed on the page", "<li>Les métiers visés comptent pour {pc(RF.W_JOBS)}.", "<li>Les métiers visés comptent pour 50 %.", "RF10"),
    ("js", "score in the lead", "${vois}${lvl}${list}${robInsPublie", "${vois}${score}${lvl}${list}${robInsPublie", "RF5"),
    ("js", "filière unescaped", "` (${esc(q.filiere.replace(\"_\", \" \"))})`", "` (${q.filiere})`", "RF5"),
    ("js", "fiche link not checked", '/^RNCP\\d+$/.test(rn.fiche || "") ? rn.fiche.slice(4) : null', '(rn.fiche || "").slice(4) || null', "RF5"),
    ("js", "no diploma-alone block", '<h3>Avec ce diplôme seul</h3>', '<h3>Débouchés</h3>', "RF5"),
    ("js", "blocks unescaped", "rn.blocs.map((b) => `<li>${esc(b)}</li>`)", "rn.blocs.map((b) => `<li>${b}</li>`)", "RF5"),
    ("js", "card before the jobs", "  ${metiersCard(d.metiers)}\n  ${insertionCard(d.insertion)}",
     "  ${formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })}\n  ${metiersCard(d.metiers)}\n  ${insertionCard(d.insertion)}", "RF6"),
    ("js", "card dropped from Emploi", "\n  ${formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })}`],", "`],", "RF6"),
    # RF11 (owner, 2026-11-18): published insertion beside the score, robustesse filters and card line on the search page
    ("js", "options not named", "${many ? `${esc(r.libelle_formation)} : ` : \"\"}", "", "RF11"),
    ("js", "option name unescaped", "${many ? `${esc(r.libelle_formation)} : `", "${many ? `${r.libelle_formation} : `", "RF11"),
    ("js", "masked value shown as 0", "(v == null ? '<span class=\"muted\">non publié</span>'", "(v == null ? '<strong>0 %</strong>'", "RF11"),
    ("js", "BUT university total before the specialty", '["Cette spécialité dans l\'université", but.specialite]', '["Cette spécialité dans l\'université", but.total || but.specialite]', "RF11"),
    ("js", "insertion said to be in the score", "restent à côté de la robustesse, jamais dedans", "complètent la robustesse", "RF11"),
    ("js", "insertion block dropped", "${robInsPublie(pub && pub.ins, pub && pub.but)}", "", "RF11"),
    ("js", "page does not pass the insertion", "formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })}`],",
     "formationRobustesseCard(d.robustesse, {})}`],", "RF11"),
    ("js", "national repère read for the filière filter", '  : (RECO && RECO.rob && RECO.rob.filiere[cod]) || "sans");', '  : (RECO && RECO.rob && RECO.rob.national[cod]) || "sans");', "RF11"),
    ("js", "no level counted as average", 'RECO.rob.echelle[cod]) || ["sans"])', 'RECO.rob.echelle[cod]) || ["moyenne"])', "RF11"),
    ("js", "the level filter matches one level only", '  if (g === "robn") return !robReady() || robLevel(f.cod_aff_form, g).includes(o);',
     '  if (g === "robn") return !robReady() || robLevel(f.cod_aff_form, g)[0] === o;', "RF11"),
    ("js", "repères not loaded hide every formation", "return !robReady() || robLevel(f.cod_aff_form, g) === o;", "return robLevel(f.cod_aff_form, g) === o;", "RF11"),
    ("js", "empty payload counted as loaded (Codex)", "out.ok = Object.keys(out.filiere).length > 0 || Object.keys(out.national).length > 0 || Object.keys(out.echelle).length > 0;", "out.ok = true;", "RF11"),
    ("js", "readiness ignores an empty payload", "const robReady = () => !!(RECO && RECO.rob && RECO.rob.ok);", "const robReady = () => !!(RECO && RECO.rob);", "RF11"),
    ("js", "dropdowns shown for an empty payload", "    const robOk = robReady();", "    const robOk = !!(RECO && RECO.rob);", "RF11"),
    ("js", "filter ignored by the list", '...CARTE_R3, "robn", ...JURY_KEYS', "...CARTE_R3, ...JURY_KEYS", "RF11"),
    ("js", "groups not offered", "fiOptions(g).map((o) => [o.key, o.label])]), ...CARTE_ROB, ...juryGroups()];", "fiOptions(g).map((o) => [o.key, o.label])]), ...juryGroups()];", "RF11"),
    ("js", "groups offered without repères", '.filter(([gr]) => (robOk || !gr.startsWith("rob"))', '.filter(([gr]) => (true', "RF11"),
    ("js", "dropdown without its estimation label", '${gr.startsWith("rob") ? `<p class="small">${estimTag("modèle de SupCompass")} ', '${gr.startsWith("rob") ? `<p class="small"> ', "RF11"),
    ("js", "card line reads unknown levels", "const w = R && R.echelle && echelleWords(R.echelle[cod]);", "const w = R && R.echelle && (echelleWords(R.echelle[cod]) || (R.echelle[cod] || []).join(\" \"));", "RF11"),
    ("robf", "ties counted below", "    below = bisect.bisect_left(ref, v) / n\n    above = (n - bisect.bisect_right(ref, v)) / n\n    for i, part in enumerate(ECHELLE_PARTS):",
     "    below = bisect.bisect_right(ref, v) / n\n    above = (n - bisect.bisect_right(ref, v)) / n\n    for i, part in enumerate(ECHELLE_PARTS):", "RF18"),
    ("robf", "the top 20 % called very robust", "ECHELLE_PARTS = (0.10, 0.30)", "ECHELLE_PARTS = (0.20, 0.30)", "RF18"),
    ("robf", "the central scenario only", 'idx = sorted({ECHELLE.index(niveau5(d["nationaux"][s], refs[s])) for s in ("S1", "S2", "S3")})',
     'idx = sorted({ECHELLE.index(niveau5(d["nationaux"][s], refs[s])) for s in ("S2",)})', "RF18"),
    ("robf", "borrowed blocks counted in the reference", '    return not (d.get("herite") or d.get("diplome_offre") or d.get("voisine") or d.get("certification"))',
     "    return True", "RF18"),
    ("robf", "one reference for every scenario", 'refs = {s: sorted(d["nationaux"][s] for d in own) for s in ("S1", "S2", "S3")}',
     'refs = {s: sorted(d["nationaux"]["S2"] for d in own) for s in ("S1", "S2", "S3")}', "RF18"),
    ("robf", "a level without a score", '        if not (d.get("score") and d.get("nationaux")) or len(own) < MIN_ECHELLE:',
     '        if not d.get("nationaux") or len(own) < MIN_ECHELLE:', "RF18"),
    ("robf", "levels dropped from the payload", '            acc["echelle"].setdefault(lv, []).append(cod)', "            pass", "RF9"),
    ("js", "card line without estimation", 'Robustesse 2035 des métiers visés ${estimTag("", false, true)} :', "Robustesse 2035 des métiers visés :", "RF11"),
    ("robf", "neighbour confidence not lowered", 'k["valeur"] = round(k["valeur"] * VOISIN_WEIGHT, 3)', 'k["valeur"] = round(k["valeur"], 3)', "RF15"),
    ("robf", "neighbour kept in its filière ranking", '        b["repere"] = None\n        v = b.get("score_national")\n        apres =',
     '        v = b.get("score_national")\n        apres =', "RF15"),
    ("robf", "CMI linked to any licence of the mention", "fi == \"Licence\" and u and u == uai and fold(fl) == fold(fil)", "fi == \"Licence\" and fold(fl) == fold(fil)", "RF15"),
    ("robf", "disagreeing neighbours tolerated", "        if len(dumped) != 1:\n            continue\n        b = json.loads(dumped.pop())", "        b = json.loads(dumped.pop())", "RF15"),
    ("js", "borrowed block not said on the card", "  const vois = v ? `<p", "  const vois = false ? `<p", "RF15"),
    ("robf", "ambiguous titles read", "    if len({frozenset(rncp[f][\"rome\"]) for f in act}) != 1:\n        return [], \"intitule_ambigu\"", "    if False:\n        return [], \"intitule_ambigu\"", "RF17"),
    ("robf", "expired fiches read", 'act = sorted(f for f in fs if rncp[f]["actif"] and rncp[f]["rome"])', 'act = sorted(f for f in fs if rncp[f]["rome"])', "RF17"),
    ("robf", "any mention read as a certification", "    if not CERT_PREFIX.match(s):\n        return None", "    if False:\n        return None", "RF17"),
    ("robf", "certification as sure as a diploma's list", '"certification": 0.5}', '"certification": 1.0}', "RF17"),
    ("robf", "certification blocks in the national pool", 'd.get("diplome_offre") or d.get("certification")))\n    out = {}\n    for cod, mention in offers:\n        fs, why',
     'd.get("diplome_offre")))\n    out = {}\n    for cod, mention in offers:\n        fs, why', "RF17"),
    ("robf", "fiche linked when several", '"apprentissage": rncp[fs[0]]["apprentissage"]} if len(fs) == 1 else None', '"apprentissage": rncp[fs[0]]["apprentissage"]}', "RF17"),
    ("js", "certification not said on the card", ': R.certification && R.certification[cod] ? " Métiers', ': false ? " Métiers', "RF17"),
    ("robf", "engineering diploma counted as a bachelor", 're.match(r"Formation Bac \\+ [34]\\b"', 're.match(r"Formation"', "RF16"),
    ("robf", "bac + 5 counted as a bachelor", 're.match(r"Formation Bac \\+ [34]\\b"', 're.match(r"Formation Bac \\+ \\d"', "RF16"),
    ("robf", "borrowed block loses its later studies", '"part": REPERE_SHARE, "apres_etudes": apres}', '"part": REPERE_SHARE, "apres_etudes": None}', "RF15"),
    ("js", "neighbour notice in one long sentence", '"}. ${ROBF_VOISINE[v.regle] ? `Pourquoi : ', '"} : ${ROBF_VOISINE[v.regle] ? `', "RF15"),
    ("robf", "bachelor rule on every filière", '(rec.get("fili") or "") == "Ecole d\'Ingénieur" and ', "", "RF16"),
    ("api", "reason not sent", ' or ROBF.absent(rec),', ',', "RF16"),
    ("js", "card silent on the reason", "    return a ? `<div", "    return false ? `<div", "RF16"),
    ("js", "tile ignores the reason", ": rb.absent ? esc(", ": false ? esc(", "RF16"),
    ("js", "unknown reason shown raw", '|| "pas d\'estimation pour cette formation")', '|| rb.absent)', "RF16"),
    ("robf", "offers counted in the national pool", "\n                 and not (d.get(\"herite\") or d.get(\"voisine\")))", ")", "RF14"),
    ("robf", "offer given a filière repère", '        b["rncp"] = None\n        b["repere"] = None', '        b["rncp"] = None\n        b["repere"] = {"niveau": "moyen"}', "RF14"),
    ("robf", "offer rule not said", "        b[\"diplome_offre\"] = rule", "        b[\"diplome_offre\"] = 1", "RF14"),
    ("robf", "offer blocks ranked", "        rows.update(inherit(con, rows, session))          # after the neighbours: an offer of a borrowing diploma inherits it too\n        def skills_of", "        def skills_of", "RF14"),
    ("robf", "an unscored formation tolerated", 'if not cods or any(b is None or not b.get("score") for b in blocks):', "if not cods:", "RF13"),
    ("robf", "different blocks tolerated", "        if len(dumped) == 1:\n            out[cod]", "        if dumped:\n            out[cod]", "RF13"),
    ("robf", "acronym prefix kept", 'MENTION_PREFIX.sub("", mention or "")', '(mention or "")', "RF13"),
    ("robf", "inherited rows ranked", "        rows.update(inherit(con, rows, session))          # after",
     "        rows.update(inherit(con, rows, session))\n        with_repere(rows, fili)          # after", "RF13"),
    ("robf", "inheritance not said", '"herite": {"source": "diplome", "formations": len(cods)}', '"herite": {"source": "diplome", "formations": 1}', "RF13"),
    ("robf", "compact drops the inherited list", '            acc["herite"].setdefault("diplome", []).append(cod)', "            pass", "RF13"),
    ("js", "inherited repère not said", '" Repères du diplôme : les mêmes pour toutes les formations qui y préparent."', '""', "RF13"),
    ("js", "no line on apprenticeship cards", 'data-tip="${esc(CARTE_APP_NOTE)}">i</button></p>${robCardLine(f.cod_aff_form)}`', 'data-tip="${esc(CARTE_APP_NOTE)}">i</button></p>`', "RF13"),
    ("js", "card line dropped", "    ${robCardLine(f.cod_aff_form)}`}", "    `}", "RF11"),
    ("js", "list sorted by repère", "        || byName(a, b));", "        || (robLevel(a.cod_aff_form, \"robn\") < robLevel(b.cod_aff_form, \"robn\") ? -1 : 0) || byName(a, b));", "RF11"),
]


# ------------------------------------------------------------------------------------------------ apprenticeship offers
PREFIX_RT = re.compile(r"^(BTSA|BTSM|BTS|BUT|DCG|DEUST|DE|D\.E) - ")      # the red team's own reading of the closed acronym list


def rt_key(d, m):
    m = PREFIX_RT.sub("", re.sub(r"\s+-\s+", " - ", m or "", count=1)) if m else ""
    return (d or "", re.sub(r"[^a-z0-9]+", " ", __import__("unicodedata").normalize("NFKD", m).encode("ascii", "ignore").decode().lower()).strip())


def oracle_inherited(offers, sies, rows):
    by: dict = {}
    for c, (d2, m2) in sorted(sies.items()):
        by.setdefault(rt_key(d2, m2), []).append(c)
    out = {}
    for cod, d, m in offers:
        same = by.get(rt_key(d, m), [])
        if not same or any(not (rows.get(c) or {}).get("score") for c in same):
            continue
        if all(rows[c] == rows[same[0]] for c in same):
            out[cod] = (same[0], len(same))
    return out


@check("RF13 apprenticeship offers: the diploma's block only when every SIES formation of it has the SAME scored block; said; never ranked")
def rf13(c: Ctx):
    F = c.F()
    bad = []
    blk = lambda v, lv="moyen": {"score": {"median": v, "min": v - 1, "max": v + 1}, "repere": {"niveau": lv}, "methode": "direct"}  # noqa: E731
    sies = {"S1": ("BTS - BTSA - BTSM", "Management en hôtellerie restauration"), "S2": ("BTS - BTSA - BTSM", "Management en hôtellerie restauration"),
            "S3": ("BTS - BTSA - BTSM", "Commerce international"), "S4": ("BTS - BTSA - BTSM", "Commerce international"),
            "S5": ("BTS - BTSA - BTSM", "Banque"), "S6": ("BTS - BTSA - BTSM", "Banque"), "S7": ("DCG", "DCG"),
            "S8": ("Licence", "Droit"), "S9": ("BUT", "Chimie " + HOSTILE)}
    rows = {"S1": blk(60), "S2": blk(60), "S3": blk(55), "S4": blk(54), "S5": {"score": None}, "S6": {"score": None}, "S7": blk(70), "S8": blk(65),
            "S9": blk(40, HOSTILE)}
    offers = [("A1", "BTS - BTSA - BTSM", "BTS - Management en hôtellerie restauration"),   # acronym prefix: the diploma's block
              ("A2", "BTS - BTSA - BTSM", "Commerce international"),                         # two different blocks: none
              ("A3", "BTS - BTSA - BTSM", "Banque"),                                         # unscored (identical) blocks: none
              ("A4", "DCG", "DCG"), ("A5", "Licence", "Licence - Droit"),                    # « Licence » is not in the closed list
              ("A6", "BUT", "Chimie " + HOSTILE), ("A7", "BTS - BTSA - BTSM", "Inconnu"), ("A8", "Formation professionnelle", "DCG")]
    got = F.inherited(offers, sies, rows)
    exp = oracle_inherited(offers, sies, rows)
    if set(got) != set(exp):
        bad.append(f"crafted: inherited {sorted(got)} vs {sorted(exp)}")
    for k, (src, n) in exp.items():
        g = dict(got.get(k) or {})
        if g.pop("herite", None) != {"source": "diplome", "formations": n} or g != rows[src]:
            bad.append(f"crafted {k}: block or count")
    if any("herite" in v for v in rows.values() if v):
        bad.append("the SIES blocks were modified")
    # the build order: the inherited rows are added AFTER the repères (never ranked), and the compact payload says which
    body = c.src["robf"]
    if not (0 <= body.find("with_repere(rows, fili)") < body.find("rows.update(inherit(con, rows, session))")) or body.count("with_repere(rows, fili)") != 1:
        bad.append("inherited rows enter the repères' ranking")
    # the card: the line on an apprenticeship card too, saying the repères are the diploma's
    q = RB.node(RB.STUB + "\n".join(RB.top(c.js, n) for n in ECH_NAMES + ("robCardLine",)) + """
      var RECO = { rob: { filiere: { "1": "moyen", "2": "haut" }, national: { "1": "bas", "2": "bas" }, herite: { "2": "diplome" },
        echelle: { "1": ["moyenne"], "2": ["plus_exposee"] } } };
      process.stdout.write(JSON.stringify([robCardLine("1"), robCardLine("2")]));""", {})
    if q is not None:
        own, inh = q
        if "diplôme" in own or "Repères du diplôme" not in inh or "Plus exposée" not in inh:
            bad.append("the card does not say an inherited repère is the diploma's (or says it of a formation's own)")
    if "herite: {}" not in RB.top(c.js, "robDecode"):
        bad.append("the page does not decode the inherited list")
    card = RB.top(c.js, "carteCard")
    app = card[card.index("f.stats === false ? `<p class=\"small muted\">Pas de statistiques"):]
    if "robCardLine(f.cod_aff_form)" not in app.split("` :")[0]:
        bad.append("no repère line on an apprenticeship card")
    if 'acc["herite"].setdefault("diplome", []).append(cod)' not in c.src["robf"]:
        bad.append("the compact payload drops the inherited list")
    real = ""
    if c.real and c.db:
        import duckdb
        from suptracker import carte as CA, rapports as RP
        tc = duckdb.connect(str(RP.textes_path(c.db)), read_only=True)
        try:
            stored = {k: json.loads(v) for k, v in tc.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
        finally:
            tc.close()
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
            offers_r = [(a["cod_aff_form"], a["diplome"], a["mention"]) for a in CA.apprentissage(con) if not a["rattachee"]]
            sies_r = {cod: CA.diplome_of(fl, fo, fi, li) for cod, fl, fo, fi, li in con.execute(
                """SELECT cod_aff_form, any_value(fili), any_value(form_lib_voe_acc), any_value(fil_lib_voe_acc), any_value(lib_for_voe_ins)
                   FROM core.formation_year WHERE session = ? GROUP BY 1""", [session]).fetchall()}
        finally:
            con.close()
        own = {k: v for k, v in stored.items() if not v.get("herite")}
        exp_r = oracle_inherited(offers_r, sies_r, own)
        got_r = {k for k, v in stored.items() if v.get("herite")}
        if got_r != set(exp_r):
            bad.append(f"real: {len(got_r)} inherited vs {len(exp_r)} expected, e.g. {sorted(got_r ^ set(exp_r))[:3]}")
        for k, (src, n) in list(exp_r.items())[:: max(1, len(exp_r) // 300)]:
            g = dict(stored.get(k) or {})
            if g.pop("herite", None) != {"source": "diplome", "formations": n} or g != own[src]:
                bad.append(f"real {k}: block or count")
                break
        real = f"; real: {len(got_r)} of {len(offers_r)} offers inherit their diploma's block"
    return not bad, f"differences {bad[:4]}{real}"


def oracle_place(v, pool):
    lo = sum(x < v for x in pool) / len(pool)
    hi = sum(x > v for x in pool) / len(pool)
    return "haut" if lo >= 0.8 else "bas" if hi >= 0.8 else "moyen"


@check("RF14 apprenticeship offers on their OWN national sheet: a « direct » block, national repère placed among SIES rows only, said")
def rf14(c: Ctx):
    F = c.F()
    from suptracker import onisep as ON
    bad = []
    forms = [("FOR.T1", "TP technicien supérieur en méthodes et exploitation logistique", "titre professionnel", None, None),
             ("FOR.T2", "CSA conduite de l'élevage porcin", "certificat de spécialisation", None, None),
             ("FOR.T3", "TP graphiste", "titre professionnel", None, None)]                       # no job on its sheet
    sheet_jobs = {"FOR.T1": {"m1", "m2"}, "FOR.T2": {"m3", "m4"}}
    offers = [("O1", "FP - Titre professionnel - Technicien(ne) supérieur(e) en méthodes et exploitation logistique (bac +2)"),
              ("O2", "CSA - Conduite de l'élevage porcin - en apprentissage"), ("O3", "FP - Titre professionnel - Graphiste (Bac +2)"),
              ("O4", "Métiers du bar"), ("O5", HOSTILE)]
    sies = {f"S{i}": {"score_national": float(v), "score": {"median": float(v)}} for i, v in enumerate(range(40, 80, 2))}
    for i in range(60):                     # inherited blocks (copies of a diploma's) are never in the pool: enough to move a level
        sies[f"H{i}"] = {"score_national": 99.0, "score": {"median": 99.0}, "herite": {"source": "diplome", "formations": 2}}
    got = F.offer_blocks(offers, ON.index(forms), sheet_jobs, JOBS, lambda fids: (None, None, SKL), sies)
    pool = sorted(v["score_national"] for k, v in sies.items() if not k.startswith("H"))
    if set(got) != {"O1", "O2"}:
        bad.append(f"offers with a block {sorted(got)}")
    for cod, om in (("O1", {"m1": 1.0, "m2": 1.0}), ("O2", {"m3": 1.0, "m4": 1.0})):
        b, e = got.get(cod) or {}, oracle_formation(om, "direct", JOBS, None, SKL)
        sc = b.get("score") or {}
        if (sc.get("median"), sc.get("min"), sc.get("max"), b.get("score_national")) != (e["median"], e["min"], e["max"], e["nat"]):
            bad.append(f"{cod}: formula")
        if b.get("repere") is not None or b.get("methode") != "direct" or not (b.get("diplome_offre") or "").startswith("titre_national"):
            bad.append(f"{cod}: filière repère, method or rule")
        n = b.get("repere_national")
        if (e["nat"] is None) != (n is None) or (n and n["niveau"] != oracle_place(e["nat"], pool)):
            bad.append(f"{cod}: national repère {n} vs {e['nat'] and oracle_place(e['nat'], pool)}")
    if any("diplome_offre" in v for v in sies.values()):
        bad.append("the SIES blocks were modified")
    body = c.src["robf"]
    i_rep, i_inh, i_off = body.find("with_repere(rows, fili)"), body.find("rows.update(inherit(con, rows, session))"), body.find("rows.update(extra)")
    if not (0 <= i_rep < i_inh < i_off):
        bad.append("offer blocks enter the repères (order)")
    if 'if d.get("herite") or d.get("diplome_offre"):' not in body:
        bad.append("the compact payload drops the offers read on their own sheet")
    real = ""
    if c.real and c.db:
        import duckdb
        from suptracker import rapports as RP
        tc = duckdb.connect(str(RP.textes_path(c.db)), read_only=True)
        try:
            stored = {k: json.loads(v) for k, v in tc.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
            jobs = {k: json.loads(v) for k, v in tc.execute("SELECT met_id, data FROM r35_metier").fetchall()}
        finally:
            tc.close()
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            idx = ON.index(con.execute("SELECT for_id, libelle, type, niveau_certification, niveau_etudes FROM core.onisep_formation").fetchall())
            sj: dict = {}
            for fid, mid in con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall():
                sj.setdefault(fid, set()).add(mid)
            from suptracker import carte as CA
            mentions = {a["cod_aff_form"]: a["mention"] for a in CA.apprentissage(con) if not a["rattachee"]}
        finally:
            con.close()
        own = {k: v for k, v in stored.items() if v.get("diplome_offre")}
        pool_r = sorted(v["score_national"] for v in stored.values() if v.get("score_national") is not None
                        and not v.get("herite") and not v.get("diplome_offre") and not v.get("voisine") and not v.get("certification"))
        exp = {k for k, m in mentions.items() if not (stored.get(k) or {}).get("herite")
               and set().union(*(sj.get(f, set()) for f in ON.match_offer(idx, m)[0] or [None]))}
        if set(own) != exp:
            bad.append(f"real: {len(own)} offer blocks vs {len(exp)} expected, e.g. {sorted(set(own) ^ exp)[:3]}")
        for k in sorted(own)[:: max(1, len(own) // 200)]:
            fids = ON.match_offer(idx, mentions[k])[0]
            om = {m: 1.0 for m in set().union(*(sj.get(f, set()) for f in fids))}
            e = oracle_formation(om, "direct", jobs, None, own[k]["competences"])
            s = own[k]["score"] or {}
            if (s.get("median"), own[k].get("score_national")) != (e["median"], e["nat"]):
                bad.append(f"real {k}: formula")
                break
            n = own[k].get("repere_national")
            if e["nat"] is not None and (not n or n["niveau"] != oracle_place(e["nat"], pool_r)):
                bad.append(f"real {k}: national repère")
                break
        real = f"; real: {len(own)} offers scored on their own sheet ({sum(1 for v in own.values() if v.get('score'))} with a score)"
    return not bad, f"differences {bad[:4]}{real}"


def rt_fold(x):
    return re.sub(r"[^a-z0-9]+", " ", __import__("unicodedata").normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()).strip()


def oracle_neighbours(sies, rows):
    """The red team's own reading of the two owner rules (CMI -> licence of the same mention and UAI; mise à niveau
    hôtellerie-restauration -> every BTS MHR), every neighbour scored and identical, confidence x 0.8."""
    own = {c: d for c, d in rows.items() if d.get("score") and not (d.get("herite") or d.get("diplome_offre") or d.get("voisine") or d.get("certification"))}
    pool = sorted(d["score_national"] for d in own.values() if d.get("score_national") is not None)
    out = {}
    for cod, fili, form, fil, uai, lib in sies:
        if cod in rows:
            continue
        if (form or "").startswith("C.M.I"):
            cands = [c for c, fi, fo, fl, u, _ in sies if fi == "Licence" and u and u == uai and rt_fold(fl) == rt_fold(fil)]
        elif rt_fold(form) == "mise a niveau" and rt_fold(fil) == "hotellerie restauration":
            cands = [c for c, fi, fo, fl, u, _ in sies if fi == "BTS" and rt_fold(fl) == "management en hotellerie restauration"]
        else:
            continue
        if not cands or any(not (rows.get(c) or {}).get("score") for c in cands) or len({json.dumps(rows[c], sort_keys=True) for c in cands}) != 1:
            continue
        src = rows[sorted(cands)[0]]
        v = round(src["confiance"]["valeur"] * 0.8, 3)
        nat = src.get("score_national") if v >= 0.4 else None
        out[cod] = {"valeur": v, "score": src["score"] if v >= 0.4 else None,
                    "national": None if nat is None else oracle_place(nat, pool),
                    "apres": None if nat is None else (src.get("repere_national") or {}).get("apres_etudes")}
    return out


@check("RF15 neighbours (owner, 2026-11-20): CMI -> its licence, mise à niveau -> BTS MHR; borrowed, said, lower confidence, never ranked")
def rf15(c: Ctx):
    F = c.F()
    bad = []
    blk = lambda v, conf=0.9: {"score": {"median": v, "min": v - 1, "max": v + 1}, "score_national": v, "repere": {"niveau": "moyen"},  # noqa: E731
                               "confiance": {"valeur": conf, "niveau": "haute"}, "methode": "direct"}
    sies = [("C1", "Autre formation", "C.M.I - Cursus Master en Ingénierie", "Informatique", "U1", "CMI info"),
            ("L1", "Licence", "Licence", "Informatique", "U1", "Licence info"),
            ("C2", "Autre formation", "C.M.I - Cursus Master en Ingénierie", "Chimie", "U1", "CMI chimie"),     # no licence of that mention
            ("C3", "Autre formation", "C.M.I - Cursus Master en Ingénierie", "Informatique", "U2", "CMI ailleurs"),   # other UAI
            ("L3", "Licence", "Licence", "Informatique", "U3", "Licence ailleurs"),
            ("M1", "Autre formation", "Mise à niveau", "Hôtellerie restauration", "U4", "MAN"),
            ("B1", "BTS", "BTS - Services", "Management en hôtellerie restauration", "U5", "BTS MHR 1"),
            ("B2", "BTS", "BTS - Services", "Management en hôtellerie restauration", "U6", "BTS MHR 2"),
            ("C4", "Autre formation", "C.M.I - Cursus Master en Ingénierie", "Physique", "U7", "CMI faible"),
            ("L4", "Licence", "Licence", "Physique", "U7", "Licence faible"),
            ("X1", "Autre formation", "FCIL", "Hôtellerie restauration", "U4", "FCIL")]                         # no rule
    rows = {"L1": dict(blk(60), repere_national={"niveau": "moyen", "apres_etudes": "master"}), "L3": blk(70), "B1": blk(55),
            "B2": blk(55), "L4": blk(50, conf=0.45)}
    for i in range(30):
        rows[f"P{i}"] = blk(40 + i)
    got = F.neighbours(sies, rows)
    exp = oracle_neighbours(sies, rows)
    if set(got) != set(exp):
        bad.append(f"crafted: borrowed {sorted(got)} vs {sorted(exp)}")
    for k, e in exp.items():
        g = got.get(k) or {}
        if g.get("confiance", {}).get("valeur") != e["valeur"] or g.get("score") != e["score"] or (g.get("repere_national") or {}).get("niveau") != e["national"]:
            bad.append(f"crafted {k}: {g.get('confiance')}, {g.get('score')}, {g.get('repere_national')} vs {e}")
        if g.get("repere") is not None or not (g.get("voisine") or {}).get("regle"):
            bad.append(f"crafted {k}: filière repère or rule")
        if (g.get("repere_national") or {}).get("apres_etudes") != e["apres"]:
            bad.append(f"crafted {k}: the borrowed block's later studies (« après un master ») are lost")
    if (got.get("C1") or {}).get("voisine", {}).get("code") != "L1":
        bad.append("the CMI does not name its licence")
    rows2 = dict(rows, B2=blk(56))                     # two BTS MHR blocks differ: the mise à niveau borrows nothing
    if "M1" in F.neighbours(sies, rows2):
        bad.append("borrowed while the neighbours disagree")
    # the order: after the repères, before the inheritance; the page says it
    body = c.src["robf"]
    if not (0 <= body.find("with_repere(rows, fili)") < body.find("rows.update(neighbours(") < body.find("rows.update(inherit(con, rows, session))")):
        bad.append("neighbours computed in the wrong order")
    for need, where in (("emprunté à la formation voisine", "formationRobTile"), ("Repère emprunté à la formation voisine", "robCardLine")):
        if need not in RB.top(c.js, where):
            bad.append(f"{where} does not say the block is borrowed")
    full = page_data()[0]
    vb = dict(full, repere=None, voisine={"regle": "cmi_licence", "code": "123", "libelle": "Licence " + HOSTILE, "formations": 1})
    prog = RB.STUB + "const H = 18;\n" + "\n".join(RB.top(c.js, n) for n in NAMES) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([formationRobustesseCard(D.v), formationRobustesseCard(D.f), formationRobustesseCard(D.l)]));"""
    longue = dict(vb, voisine=dict(vb["voisine"], libelle="Université Paris-Saclay - Faculté des sciences d'Orsay · Informatique"))
    out = RB.node(prog, {"v": vb, "f": full, "l": longue})
    if out is not None:
        cv, cf, cl = out
        notice = re.sub(r"<[^>]+>", "", re.search(r'<p class="small warn">(.*?)</p>', cl, re.S).group(1)) if '<p class="small warn">' in cl else ""
        longest = max((len(x.split()) for x in re.split(r"[.!?;]\s", notice) if x.strip()), default=99)
        if longest > 30:
            bad.append(f"the neighbour notice has a sentence of {longest} words with a long label (CLAUDE.md: <= 30)")
        if "Repère emprunté à la formation voisine" not in cv or "Trop peu de formations comparables" in cv or HOSTILE in cv \
                or "#/f/123" not in cv or "emprunté" in cf:
            bad.append("the formation card does not say (or wrongly says) the block is borrowed, or leaks the label unescaped")
    real = ""
    if c.real and c.db:
        import duckdb
        from suptracker import rapports as RP
        tc = duckdb.connect(str(RP.textes_path(c.db)), read_only=True)
        try:
            stored = {k: json.loads(v) for k, v in tc.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
        finally:
            tc.close()
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
            sies_r = [tuple(r) for r in con.execute("""SELECT cod_aff_form, any_value(fili), any_value(form_lib_voe_acc), any_value(fil_lib_voe_acc),
                any_value(cod_uai), '' FROM core.formation_year WHERE session = ? GROUP BY 1 ORDER BY 1""", [session]).fetchall()]
        finally:
            con.close()
        own = {k: v for k, v in stored.items() if not v.get("voisine") and not v.get("herite") and not v.get("diplome_offre") and not v.get("certification")}
        exp_r = oracle_neighbours(sies_r, own)
        got_r = {k: v for k, v in stored.items() if v.get("voisine")}
        if set(got_r) != set(exp_r):
            bad.append(f"real: {len(got_r)} borrowed vs {len(exp_r)} expected, e.g. {sorted(set(got_r) ^ set(exp_r))[:3]}")
        for k, e in exp_r.items():
            g = got_r.get(k) or {}
            if g.get("confiance", {}).get("valeur") != e["valeur"] or g.get("score") != e["score"] \
                    or (g.get("repere_national") or {}).get("apres_etudes") != e["apres"]:
                bad.append(f"real {k}: confidence, score or later studies")
                break
        real = f"; real: {len(got_r)} formations borrow a neighbour's block ({sum(1 for v in got_r.values() if v.get('score'))} with a score)"
    return not bad, f"differences {bad[:4]}{real}"


@check("RF16 no block on purpose (owner, 2026-11-20): an engineering school's bachelor says why, never borrows the engineer's score")
def rf16(c: Ctx):
    F = c.F()
    bad = []
    cases = [({"fili": "Ecole d'Ingénieur", "fil_lib_voe_acc": "Formation Bac + 3"}, "bachelor_ecole_ingenieur"),
             ({"fili": "Ecole d'Ingénieur", "fil_lib_voe_acc": "Formation Bac + 4"}, "bachelor_ecole_ingenieur"),
             ({"fili": "Ecole d'Ingénieur", "fil_lib_voe_acc": "Formation d'ingénieur Bac + 5"}, None),
             ({"fili": "Ecole d'Ingénieur", "fil_lib_voe_acc": "Formation Bac + 5"}, None),        # not a bachelor (review)
             ({"fili": "Ecole de Commerce", "fil_lib_voe_acc": "Formation Bac + 3"}, None),
             ({"fili": "Licence", "fil_lib_voe_acc": "Informatique"}, None), ({}, None)]
    for rec, exp in cases:
        got = (F.absent(rec) or {}).get("absent")
        if got != exp:
            bad.append(f"{rec}: {got} vs {exp}")
    if set(F.ABSENT_RULES) != {"bachelor_ecole_ingenieur"}:
        bad.append(f"rules {F.ABSENT_RULES}")
    if 'ROBF.for_formation(_con().cursor(), rec["cod_aff_form"]) or ROBF.absent(rec)' not in c.src["api"]:
        bad.append("the formation answer does not carry the reason when there is no block")
    prog = RB.STUB + "\n".join(RB.top(c.js, n) for n in NAMES + ("ROB_SUM", "formationRobTile")) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([formationRobustesseCard(D.a), formationRobustesseCard(D.u), formationRobTile(D.a), formationRobTile(D.u)]));"""
    out = RB.node(prog, {"a": {"absent": "bachelor_ecole_ingenieur"}, "u": {"absent": "inconnu" + HOSTILE}})
    if out is not None:
        ca, cu, ta, tu = out
        if "Onisep ne publie pas les métiers" not in ca or "cycle ingénieur" not in ca or "/ 100" in ca or "Score" in ca or 'id="robustesse"' not in ca:
            bad.append("the card does not say why, or shows a figure")
        ta, tu = (x.replace("&#39;", "'") for x in (ta, tu))
        if cu or HOSTILE in tu or "pas d'estimation" not in tu:
            bad.append("an unknown reason is shown, or leaks")
        if "Onisep ne publie pas les métiers de ce bachelor" not in ta or "/ 100" in ta or "données insuffisantes" in ta:
            bad.append("the L'essentiel tile does not say why")
    real = ""
    if c.real and c.db:
        import duckdb
        from suptracker import rapports as RP
        tc = duckdb.connect(str(RP.textes_path(c.db)), read_only=True)
        try:
            stored = {k for (k,) in tc.execute("SELECT cod_aff_form FROM r35_formation").fetchall()}
        finally:
            tc.close()
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
            recs = con.execute("""SELECT cod_aff_form, any_value(fili), any_value(fil_lib_voe_acc) FROM core.formation_year
                                  WHERE session = ? GROUP BY 1""", [session]).fetchall()
        finally:
            con.close()
        named = [k for k, fi, fl in recs if F.absent({"fili": fi, "fil_lib_voe_acc": fl})]
        hidden = [k for k in named if k in stored]
        if hidden:
            bad.append(f"real: the rule names {len(hidden)} formations that have a block, e.g. {hidden[:3]}")
        if not named:
            bad.append("real: the rule names no formation")
        real = f"; real: {len(named)} bachelors say why they have no score"
    return not bad, f"differences {bad[:4]}{real}"


def rt_cert_key(t):
    """The red team's own reading of a certification title: no brackets, accents, case, spaces or punctuation."""
    t = re.sub(r"\([^)]*\)", " ", t or "").replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    return re.sub(r"[^a-z0-9]", "", rt_fold(t))


def rt_cert_title(mention):
    m = re.match(r"\s*FP\s*-\s*(.*)$", (mention or "").replace("\xa0", " "))
    if not m:
        return None
    s = re.sub(r"^(?:titre professionnel|formation professionnelle)\s*-?\s*", "", m.group(1), flags=re.I)
    s = re.sub(r"\s*\((?:bac|niveau)[^)]*\)\s*$", "", s, flags=re.I)
    return rt_cert_key(re.sub(r"\s*-\s*$", "", s)) or None


def oracle_cert(mention, rncp):
    """The ACTIVE fiches (with ROME codes) of the same title, when they all carry the same codes; else []."""
    k = rt_cert_title(mention)
    if not k:
        return []
    act = sorted(f for f, v in rncp.items() if v["actif"] and v["rome"] and rt_cert_key(v["intitule"]) == k)
    return act if len({frozenset(rncp[f]["rome"]) for f in act}) == 1 else []


@check("RF17 offers read through the RNCP certification of the same title (owner, 2026-11-20): non-ambiguous active fiches, said")
def rf17(c: Ctx):
    F = c.F()
    bad = []
    cases = {"FP - Titre professionnel - Gestionnaire de Paie (Bac +2)": "gestionnairedepaie",
             "FP - Titre Professionnel - Chef de Chantier Gros-Oeuvre (Bac + 2)": "chefdechantiergrosoeuvre",
             "FP - Formation professionnelle - Administrateur(trice) systèmes et réseaux (Bac +3)": "administrateursystemesetreseaux",
             "FP - Gestionnaire en maintenance et support informatique - (Bac +2)": "gestionnaireenmaintenanceetsupportinformatique",
             "FP - Titre Professionnel - Formateur Professionnel d'Adultes (Bac + 2)": "formateurprofessionneldadultes",
             "BTS - Management en hôtellerie restauration": None, "Métiers du bar": None, "": None}
    for m, e in cases.items():
        if F.cert_title(m) != e or rt_cert_title(m) != e:
            bad.append(f"title of {m!r}: {F.cert_title(m)} / {rt_cert_title(m)} vs {e}")
    rncp = {"R1": {"intitule": "Gestionnaire de paie", "actif": True, "rome": {"M1501"}, "apprentissage": True, "blocs": []},
            "R2": {"intitule": "Gestionnaire de Paie", "actif": True, "rome": {"M1501"}, "apprentissage": False, "blocs": []},
            "R3": {"intitule": "Chargé RH", "actif": True, "rome": {"M1502"}, "apprentissage": True, "blocs": []},
            "R4": {"intitule": "Chargé RH", "actif": True, "rome": {"M1503"}, "apprentissage": True, "blocs": []},
            "R5": {"intitule": "Assistant juridique", "actif": False, "rome": {"K1902"}, "apprentissage": True, "blocs": []},
            "R6": {"intitule": "Graphiste", "actif": True, "rome": {"E1205"}, "apprentissage": True, "blocs": []},
            "R7": {"intitule": "Graphiste", "actif": True, "rome": set(), "apprentissage": True, "blocs": ["b"]},
            "R8": {"intitule": "Sans métier", "actif": True, "rome": {"Z9999"}, "apprentissage": True, "blocs": []},
            "R9": {"intitule": "Développeur " + HOSTILE, "actif": True, "rome": {"M1805"}, "apprentissage": True, "blocs": []}}
    offers = [("O1", "FP - Titre professionnel - Gestionnaire de paie (Bac +2)"), ("O2", "FP - Chargé RH (Bac +3)"),
              ("O3", "FP - Assistant juridique (Bac +2)"), ("O4", "FP - Graphiste (Bac +2)"), ("O5", "FP - Sans métier (Bac +2)"),
              ("O6", "FP - Inconnu (Bac +2)"), ("O7", "Graphiste"), ("O8", "FP - Développeur " + HOSTILE)]
    rome_jobs = {"M1501": {"m1", "m2"}, "E1205": {"m3"}, "M1805": {"m4"}, "M1502": {"m1"}, "M1503": {"m2"}, "K1902": {"m3"}}
    sies = {f"S{i}": {"score_national": float(v), "score": {"median": float(v)}} for i, v in enumerate(range(40, 80, 2))}
    for i in range(60):                     # borrowed blocks never enter the pool
        sies[f"C{i}"] = {"score_national": 99.0, "score": {"median": 99.0}, "certification": {"fiches": ["X"]}}
    before = copy.deepcopy(sies)
    got = F.cert_blocks(offers, F.cert_index(rncp), rncp, rome_jobs, JOBS, {}, sies)
    exp = {k: oracle_cert(m, rncp) for k, m in offers}
    exp = {k: v for k, v in exp.items() if v and set().union(*(rome_jobs.get(x, set()) for f in v for x in rncp[f]["rome"]))}
    if set(got) != set(exp) or set(exp) != {"O1", "O4", "O8"}:
        bad.append(f"offers with a block {sorted(got)} vs {sorted(exp)}")
    pool = sorted(v["score_national"] for k, v in sies.items() if k.startswith("S"))
    for k, fs in exp.items():
        b = got.get(k) or {}
        om = {m: 1.0 for m in set().union(*(rome_jobs.get(x, set()) for x in rncp[fs[0]]["rome"]))}
        e = oracle_formation(om, "certification", JOBS, None, None)
        sc = b.get("score") or {}
        if (sc.get("median"), b.get("score_national")) != (e["median"], e["nat"]):
            bad.append(f"{k}: formula")
        if b.get("methode") != "certification" or b.get("repere") is not None or (b.get("certification") or {}).get("fiches") != fs:
            bad.append(f"{k}: method, filière repère or fiches")
        n = b.get("repere_national")
        if (e["nat"] is None) != (n is None) or (n and n["niveau"] != oracle_place(e["nat"], pool)):
            bad.append(f"{k}: national repère")
        if (b.get("rncp") is None) != (len(fs) > 1):
            bad.append(f"{k}: one fiche link only when the title has one fiche")
    if sies != before:
        bad.append("the SIES blocks were modified")
    body = c.src["robf"]
    i_off, i_cert = body.find("rows.update(extra)"), body.find("rows.update(cert)")
    if not (0 <= i_off < i_cert):
        bad.append("the certification is read before the offers' own Onisep sheets (order)")
    if F.METHOD_WEIGHT.get("certification") != 0.5:
        bad.append("the certification link is as sure as a diploma's own list")
    if 'acc["certification"].setdefault("rncp", []).append(cod)' not in body:
        bad.append("the compact payload drops the certification")
    line = RB.top(c.js, "robCardLine")
    if "certification du même intitulé" not in line or "moins sûr" not in line or ": R.certification && R.certification[cod] ?" not in line:
        bad.append("the search card does not say the jobs come from the certification")
    if "certification" not in RB.top(c.js, "ROBF_METHODE"):
        bad.append("the formation card has no words for the method")
    real = ""
    if c.real and c.db:
        import duckdb
        from suptracker import rapports as RP
        tc = duckdb.connect(str(RP.textes_path(c.db)), read_only=True)
        try:
            stored = {k: json.loads(v) for k, v in tc.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
            jobs = {k: json.loads(v) for k, v in tc.execute("SELECT met_id, data FROM r35_metier").fetchall()}
        finally:
            tc.close()
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            from suptracker import carte as CA
            mentions = {a["cod_aff_form"]: a["mention"] for a in CA.apprentissage(con) if not a["rattachee"]}
            rj: dict = {}
            for mid, code in con.execute("SELECT met_id, rome FROM core.onisep_metier_rome").fetchall():
                rj.setdefault(code, set()).add(mid)
        finally:
            con.close()
        rn = F.read_rncp(F.DIR / F.RNCP_ZIP)
        byk: dict = {}
        for f, v in rn.items():
            if v["actif"] and v["rome"]:
                byk.setdefault(rt_cert_key(v["intitule"]), []).append(f)
        own = {k: v for k, v in stored.items() if v.get("certification")}
        exp_r = {}
        for k, m in mentions.items():
            if k in stored and not stored[k].get("certification"):
                continue                                    # read another way first (inherited, own Onisep sheet)
            t = rt_cert_title(m)
            act = sorted(byk.get(t, [])) if t else []
            if act and len({frozenset(rn[f]["rome"]) for f in act}) == 1 and set().union(*(rj.get(x, set()) for x in rn[act[0]]["rome"])):
                exp_r[k] = act
        if set(own) != set(exp_r):
            bad.append(f"real: {len(own)} certification blocks vs {len(exp_r)} expected, e.g. {sorted(set(own) ^ set(exp_r))[:3]}")
        pool_r = sorted(v["score_national"] for v in stored.values() if v.get("score_national") is not None
                        and not (v.get("herite") or v.get("diplome_offre") or v.get("voisine") or v.get("certification")))
        for k in sorted(own)[:: max(1, len(own) // 150)]:
            b, fs = own[k], exp_r.get(k) or []
            om = {m: 1.0 for m in set().union(*(rj.get(x, set()) for x in rn[fs[0]]["rome"]))} if fs else {}
            e = oracle_formation(om, "certification", jobs, None, b["competences"])
            if b["certification"]["fiches"] != fs or ((b["score"] or {}).get("median"), b.get("score_national")) != (e["median"], e["nat"]):
                bad.append(f"real {k}: fiches or formula")
                break
            n = b.get("repere_national")
            if e["nat"] is not None and (not n or n["niveau"] != oracle_place(e["nat"], pool_r)) or b.get("repere") is not None:
                bad.append(f"real {k}: repères")
                break
        real = f"; real: {len(own)} offers read through their certification ({sum(1 for v in own.values() if v.get('score'))} with a score)"
    return not bad, f"differences {bad[:4]}{real}"


def oracle_echelle(rows: dict, parts=(0.10, 0.30)) -> dict:
    """An independent reading of the five-level scale (owner, 2026-11-22): per scenario, the share of the OWN blocks strictly below
    and strictly above; the top level from 90 % below, the second from 70 %; the same at the bottom; the middle otherwise."""
    names = ["tres_robuste", "robuste", "moyenne", "plus_exposee", "tres_exposee"]
    own = [d for d in rows.values() if d.get("score") and d.get("nationaux")
           and not any(d.get(k) for k in ("herite", "diplome_offre", "voisine", "certification"))]
    out = {}
    for cod, d in rows.items():
        if not (d.get("score") and d.get("nationaux")) or len(own) < 100:
            out[cod] = None
            continue
        lv = set()
        for sc in ("S1", "S2", "S3"):
            vals = [o["nationaux"][sc] for o in own]
            v = d["nationaux"][sc]
            lo, hi = sum(x < v for x in vals) / len(vals), sum(x > v for x in vals) / len(vals)
            k = 0 if lo >= 1 - parts[0] else 1 if lo >= 1 - parts[1] else 4 if hi >= 1 - parts[0] else 3 if hi >= 1 - parts[1] else 2
            lv.add(k)
        out[cod] = [names[min(lv)]] if len(lv) == 1 else [names[min(lv)], names[max(lv)]]
    return out


@check("RF18 five levels (owner, 2026-11-22): per scenario among the OWN blocks, 10/20/40/20/10, ties never above, both levels when they disagree")
def rf18(c: Ctx):
    import random
    F = c.F()
    rnd = random.Random(7)
    bad = []
    rows = {}
    for i in range(240):
        base = rnd.choice([40, 50, 55, 58, 60, 60, 60, 62, 64, 66, 70, 73]) + rnd.random() * 2
        nat = {"S1": round(base - rnd.random() * 3, 1), "S2": round(base, 1), "S3": round(base + rnd.random() * 0.5, 1)}
        rows[str(i)] = {"score": {"median": base}, "nationaux": nat}
    rows["T1"], rows["T2"] = ({"score": {"median": 60}, "nationaux": {"S1": 60.0, "S2": 60.0, "S3": 60.0}} for _ in range(2))
    rows["H"] = {"score": {"median": 99}, "nationaux": {"S1": 99.0, "S2": 99.0, "S3": 99.0}, "herite": {"source": "diplome"}}
    rows["V"] = {"score": {"median": 1}, "nationaux": {"S1": 1.0, "S2": 1.0, "S3": 1.0}, "voisine": {"regle": "x"}}
    rows["N"] = {"score": None, "nationaux": {"S1": 50.0, "S2": 50.0, "S3": 50.0}}
    exp = oracle_echelle(copy.deepcopy(rows))
    got = F.with_echelle(copy.deepcopy(rows))
    diff = [k for k in rows if (got[k].get("echelle") or {}).get("niveaux") != exp[k]]
    if diff:
        bad.append(f"crafted: {len(diff)} levels differ from the oracle (e.g. {diff[:3]})")
    if got["H"]["echelle"]["n_formations"] != 242:
        bad.append("an inherited or borrowed block counted in the reference")
    if got["H"]["echelle"]["niveaux"] != ["tres_robuste"] or got["V"]["echelle"]["niveaux"] != ["tres_exposee"]:
        bad.append("a borrowed block is not placed")
    if got["N"]["echelle"] is not None:
        bad.append("a level without a score")
    small = F.with_echelle({k: copy.deepcopy(rows[k]) for k in list(rows)[:50]})
    if any(v.get("echelle") for v in small.values()):
        bad.append("a level read among too few formations")
    shares = [sum(1 for k in rows if exp[k] and exp[k][0] == n and len(exp[k]) == 1) for n in ("tres_robuste", "moyenne")]
    # the real blocks (sidecar beside the warehouse): every stored level re-derived, the shares measured
    detail = ""
    if c.db is not None:
        import duckdb
        tp = c.db.parent / "rapport_textes.duckdb"
        if tp.exists():
            con = duckdb.connect(str(tp), read_only=True)
            try:
                real = {k: json.loads(v) for k, v in con.execute("SELECT cod_aff_form, data FROM r35_formation").fetchall()}
            except Exception:  # noqa: BLE001
                real = {}
            con.close()
            if real and any("nationaux" in v for v in real.values()):
                want = oracle_echelle(real)
                wrong = [k for k, v in real.items() if (v.get("echelle") or {}).get("niveaux") != want[k]]
                if wrong:
                    bad.append(f"real: {len(wrong)} stored levels differ from the oracle (e.g. {wrong[:3]})")
                own = [v for v in real.values() if v.get("echelle") and not any(v.get(k) for k in ("herite", "diplome_offre", "voisine", "certification"))]
                two = sum(1 for v in own if len(v["echelle"]["niveaux"]) == 2) / max(1, len(own))
                if two > 0.25:
                    bad.append(f"the scenarios disagree on {two:.0%} of the formations: the scale says little")
                detail = f"; real: {len(real)} blocks, {len(own)} own levels, two levels {two:.1%}"
            elif real:
                detail = "; real blocks without the per-scenario national scores (an older build): not re-derived"
    return not bad, f"differences {bad[:4]}; crafted single tres_robuste/moyenne {shares}{detail}"


@check("RF8 mutation test: every seeded bug is caught")
def rf8(c: Ctx):
    # 2026-11-23: the mutants run on the crafted data (real off), so the unmutated baseline is read the same way (it ran the
    # real-data checks a second time, RF18's oracle included); `part` splits the mutants over CI files
    mutants = SOURCE_MUTANTS if not c.part else SOURCE_MUTANTS[c.part[0] - 1::c.part[1]]
    base = copy.copy(c)
    base.real = False
    targets = {m[4] for m in mutants}
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(base)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in mutants:
        m = copy.copy(c)
        m.real = False
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        if kind == "js":
            m.js = src.replace(old, new, 1)
        else:
            m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        fn = next(f for f in CHECKS if f.check_name.startswith(target + " "))
        try:
            ok = fn(m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    return not missed, f"{caught}/{len(mutants)} caught; missed {missed}"


def run(db: Path | None = None, real: bool = False, checks: set | None = None, part: tuple[int, int] | None = None) -> list[dict]:
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real, part)
    out = []
    for fn in CHECKS:
        if checks is not None and fn.check_name.split()[0] not in checks:
            continue
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
