"""Red team, robustesse 2035 per FORMATION (owner, 2026-11-17): an ESTIMATION of the model on each formation page, built on the
per-job model (redteam_robustesse.py).

  RF1 skills: an INDEPENDENT reading of the RNCP export (Standard, Blocs, Rome, VoixdAccès members, ';' and utf-8-sig) and of the
      ROME 4.0 open data (competences, links, mobilities) gives each fiche's blocks, ROME codes, apprenticeship flag, and the
      competences of its ROME codes: portable = « Transverse » or shared by >= 20 sheets; the module equals it (fixture and real).
  RF2 links: Onisep's own France Compétences link first; else the national BTS title before its options, the BUT specialty and
      parcours (else the specialty), among the fiches WITH content, ACTIVE first then the latest decision; never a fuzzy title.
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
  RF6 plumbing: build after the jobs, API, first card of « Emploi et métiers », sources en ligne, the data workflow fingerprint
      and .vercelignore cover data/rncp, README, CLAUDE.md, tests and durations.
  RF7 real (--real): the stored blocks re-derived for a sample (skills from the real RNCP and ROME files, outlets and formula
      from the stored jobs), the repère of every formation re-derived, coverage per filière printed.
  RF8 mutation test.
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
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {"robf": (ROOT / "suptracker" / "robustesse_formation.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def F(self):
        import suptracker  # noqa: F401
        return RB.load(ROOT / "suptracker" / "robustesse_formation.py", "suptracker.robustesse_formation_rt", self.src["robf"])


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
]
BLOCS = [("RNCP1", "Gérer la relation client"), ("RNCP3", "Animer l'offre"), ("RNCP3", " "), ("RNCP4", "Réaliser une application"),
         ("RNCP5", "Analyser " + HOSTILE), ("RNCP6", "Concevoir")]
ROMES = [("RNCP1", "D1501"), ("RNCP2", "D1501"), ("RNCP3", "D1501"), ("RNCP3", "D1502"), ("RNCP4", "M1805"), ("RNCP5", "C1201"), ("RNCP6", "H1203"),
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
        ("D", "BUT informatique parcours autre", {}, ("RNCP4", "titre")),              # parcours unknown: the specialty
        ("E", "licence mention économie", {"E": "RNCP5"}, ("RNCP5", "onisep")),
        ("F", "BTS management commercial", {}, (None, None)),                          # never a partial title
        ("G", "licence mention économie", {"G": "RNCP99"}, (None, None)),              # a link to an unknown fiche
        (None, "BTS management commercial opérationnel", {}, (None, None)),
    ]
    for fid, lab, link, exp in cases:
        got = F.rncp_of(fid, lab, link, idx, rn)
        if got != exp:
            bad.append(f"{lab!r}: {got} != {exp}")
    return not bad, f"differences {bad[:4]}"


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
    conf = min(wm("fraicheur"), {"direct": 1, "poursuite": 0.8, "famille": 0.5}[method] * wm("donnees_observees"), wm("accord_sources"), cover)
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
NAMES = ("ROB_SCEN", "ROB_CONF", "robNum", "ROBF_REPERE", "ROBF_REPERE_NATIONAL", "ROBF_APRES", "ROBF_METHODE", "ROBF_LIEN", "robJobs", "robfFaits", "formationRobustesseCard")


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
    }
    same = copy.deepcopy(full)
    same["repere"] = {"niveau": None, "filiere": "CPGE", "n_formations": 809, "raison": "memes_debouches"}
    same["rncp"] = {"fiche": "RNCP1\" onmouseover=alert(1)", "lien": "titre", "apprentissage": False, "blocs": ["x"]}
    same["repere_national"] = {"niveau": "haut", "n_formations": 12185, "part": 0.2, "apres_etudes": "autres"}
    none = copy.deepcopy(full)
    none["score"], none["scenarios"], none["repere"], none["score_national"], none["repere_national"] = None, None, None, None, None
    none["confiance"]["niveau"] = "faible"
    return full, same, none


@check("RF5 page: escaped, repère and facts first, score only in « Détail du calcul », diploma alone apart, master gain, RNCP")
def rf5(c: Ctx):
    if not all(RB.top(c.js, n) for n in NAMES):
        return False, "a renderer is missing from app.js"
    full, same, none = page_data()
    prog = RB.STUB + "\n".join(RB.top(c.js, n) for n in NAMES) + """
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
    if "Parmi les 20 % de formations les plus robustes de sa filière" not in lead or '<span class="estim">' not in lead:
        bad.append("the repère does not lead the card as an estimation")
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
    # the national repère (owner, 2026-11-17): second line, before the facts, with the later-studies caveat; its score in the detail
    if "Parmi les 20 % de formations les moins robustes, toutes filières confondues" not in lead.split("<ul")[0] \
            or "parmi 12 185 formations" not in lead.replace("\u202f", " ").replace("\xa0", " ") \
            or "ils arrivent après la licence et un master (bac+5)" not in lead:
        bad.append("the national repère, its count or its master caveat is missing before the facts")
    if "base commune à toutes les formations (métiers visés et diversité) : <strong>64</strong>" not in detail:
        bad.append("the national score is not in « Détail du calcul »")
    if "Parmi les 20 % de formations les plus robustes, toutes filières confondues" not in cs or "souvent après d&#39;autres études" not in cs:
        bad.append("a formation not ranked in its filière loses its national repère or its caveat")
    if "toutes filières" in cn or "base commune" in cn:
        bad.append("a national repère without a score")
    if "ne les classons pas" not in cs or "robustes de sa filière" in cs or "francecompetences.fr/recherche/rncp/1" in cs:
        bad.append("shared outlets: no level said, or a link from a non-numeric fiche")
    if "Données insuffisantes" not in cn or re.search(r"Score :|Parmi les 20 % de formations", cn):
        bad.append("insufficient data still shows a number")
    if c0:
        bad.append("output without data")
    return not bad, f"differences {bad[:5]}"


@check("RF6 plumbing: build after the jobs, API, first card of « Emploi et métiers », sources, fingerprint, bundle, docs, tests")
def rf6(c: Ctx):
    bad = []
    b = (ROOT / "suptracker" / "build.py").read_text()
    i, j = b.find("robustesse.build(con,"), b.find("robustesse_formation.build(con,")
    if i < 0 or j < i:
        bad.append("build (after the jobs)")
    if '"robustesse": ROBF.for_formation(' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("API")
    if '["emploi", "Emploi et métiers", `\n  ${formationRobustesseCard(d.robustesse)}' not in c.js:
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
    if set(rows) - set(fili):
        bad.append(f"{len(set(rows) - set(fili))} blocks outside the latest campaign")
    # repère of every formation
    exp = oracle_repere(rows, fili)
    diff = [k for k in rows if got_repere(rows)[k] != exp[k]]
    if diff:
        bad.append(f"repère differs for {len(diff)}, e.g. {diff[:3]}")
    gn, en = got_national(rows), oracle_national(rows)
    dn = [k for k in rows if gn[k] != en[k]]
    if dn:
        bad.append(f"national repère differs for {len(dn)}, e.g. {dn[:3]}")
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


SOURCE_MUTANTS = [
    ("robf", "portable threshold 19", "rome[\"partage\"].get(o, 0) >= PORTABLE_SHEETS", "rome[\"partage\"].get(o, 0) >= PORTABLE_SHEETS - 1", "RF1"),
    ("robf", "technique counted portable", 'C[o]["sous_cat"] == "Transverse" or', 'C[o]["sous_cat"] != "Technique expert" or', "RF1"),
    ("robf", "inactive fiches read", 'r["Actif"] == "ACTIVE"', 'r["Actif"] != ""', "RF1"),
    ("robf", "apprenticeship from any route", 'any("apprentissage" in x.lower() for x in v["voies"])', "bool(v[\"voies\"])", "RF1"),
    ("robf", "empty fiche picked", 'ok = [k for k in fiches or () if rncp[k]["blocs"] or rncp[k]["rome"]]', "ok = list(fiches or ())", "RF2"),
    ("robf", "inactive first", "key=lambda k: (rncp[k][\"actif\"], date(k), k)", "key=lambda k: (date(k), k)", "RF2"),
    ("robf", "options kept", 'return re.split(r" options? | parcours | specialite ", " " + fold(title) + " ")[0].strip()', "return fold(title)", "RF2"),
    ("robf", "insertion weight 0.15", "W_JOBS, W_INS, W_DIV, W_COMP = 0.60, 0.10, 0.15, 0.15", "W_JOBS, W_INS, W_DIV, W_COMP = 0.60, 0.15, 0.15, 0.15", "RF3"),
    ("robf", "entropy over 9 groups", "ISCO_GROUPS = 10", "ISCO_GROUPS = 9", "RF3"),
    ("robf", "famille as sure as direct", '"famille": 0.5}', '"famille": 1.0}', "RF3"),
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
    ("js", "no national line", "${head}${nat}${list}", "${head}${list}", "RF5"),
    ("js", "national caveat dropped", '${qn.apres_etudes ? `<br><span class="small">${esc(ROBF_APRES[qn.apres_etudes] || "")}</span>` : ""}', "", "RF5"),
    ("js", "score in the lead", "${head}${nat}${list}${seul}", "${score}${head}${nat}${list}${seul}", "RF5"),
    ("js", "filière unescaped", "` (${esc(q.filiere.replace(\"_\", \" \"))})`", "` (${q.filiere})`", "RF5"),
    ("js", "fiche link not checked", '/^RNCP\\d+$/.test(rn.fiche || "") ? rn.fiche.slice(4) : null', '(rn.fiche || "").slice(4) || null', "RF5"),
    ("js", "no diploma-alone block", '<h3>Avec ce diplôme seul</h3>', '<h3>Débouchés</h3>', "RF5"),
    ("js", "blocks unescaped", "rn.blocs.map((b) => `<li>${esc(b)}</li>`)", "rn.blocs.map((b) => `<li>${b}</li>`)", "RF5"),
    ("js", "card not first", "${formationRobustesseCard(d.robustesse)}\n  ${insertionCard(d.insertion)}", "${insertionCard(d.insertion)}\n  ${formationRobustesseCard(d.robustesse)}", "RF6"),
]


@check("RF8 mutation test: every seeded bug is caught")
def rf8(c: Ctx):
    targets = {m[4] for m in SOURCE_MUTANTS}
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
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
    return not missed, f"{caught}/{len(SOURCE_MUTANTS)} caught; missed {missed}"


def run(db: Path | None = None, real: bool = False) -> list[dict]:
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real)
    out = []
    for fn in CHECKS:
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
