"""Red team, « Étudier là-bas » (sprint V1, owner 2026-11-15): the State-label badge (reconnaissance.py) and the cost of a year
of study (vie.py), with the fiche reader's version 3 (fiche_parse.badges / frais).

  V1 fiche reader: on the saved live fiches, the State label(s) (image code + text), the establishment and grants badges and the
     fee lines equal an independent BeautifulSoup reading; an error page yields nothing.
  V2 badge: a ground-truth table of printed labels -> category; every label read (fixture, and the real harvest when present)
     sorted again by an independent keyword reading; no label -> "aucun" (never "non reconnu"), the RNCP fallback only from a
     Parcoursup title naming a professional title.
  V3 fees: a ground-truth table of fee texts -> amount (a plain sum of euro amounts only); hostile and mixed texts give none;
     on every real fee line read, an amount equals the sum of the numbers its text prints, never on a line naming the CVEC,
     only on the "Par année" line.
  V4 cost card (a fixture warehouse built here): rent = 20 m² x the published bounds (rounded to 10 €), matched by town AND
     department only; Crous residences by an independent haversine within 10 km, closed ones out, a rent only when the text
     prints euros, https links only; the monthly total = the fixed rule (rent low + running items; rent high + every item);
     the year = 10 months + the fees read + the CVEC when the fiche prints it; no total when a part is missing.
  V5 OVE survey: the transcribed CSV against the brochure kept in data/sources (page 27 text: every label and amount, the
     781 € total, amounts in decreasing order as the chart prints them, the sentences quoting 413, 115 and 95 €).
  V6 page (node): coutCard, recoCard, recoPill escape every stored string, label the computed figures with estimTag, say
     the fiche fait foi and that only the rent is local, vouvoiement, never a chance; external links noopener and https.
  V7 real warehouse: the stored tables re-derived (categories, fee amounts, totals of a sample of formations, the lists'
     compact answer = the table).
  V8 plumbing: build, API, cache policy, analytics tab list, source register, fingerprints, release feature, durations, docs.
  V9 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []
FICHES_LIVE = ROOT / "data" / "rapports" / "live" / "fiches_live"
HOSTILE = "<img src=x onerror=alert(1)>"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str, package: str | None):
    m = types.ModuleType(name)
    m.__file__, m.__package__ = str(path), package
    if package is None:
        sys.modules[name] = m
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


def plainfold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {"rc": (ROOT / "suptracker" / "reconnaissance.py").read_text(),
                    "vie": (ROOT / "suptracker" / "vie.py").read_text(),
                    "fp": (ROOT / "scripts" / "fiche_parse.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mods(self):
        """reconnaissance, vie, fiche_parse loaded from the (possibly mutated) sources."""
        import suptracker  # noqa: F401  (the package, for the relative imports)
        rc = load(ROOT / "suptracker" / "reconnaissance.py", "suptracker.reconnaissance", self.src["rc"], "suptracker")
        sys.modules["suptracker.reconnaissance"] = rc
        vie = load(ROOT / "suptracker" / "vie.py", "suptracker.vie_rt", self.src["vie"], "suptracker")
        fp = load(ROOT / "scripts" / "fiche_parse.py", "fiche_parse_rt", self.src["fp"], None)
        return rc, vie, fp


def pages():
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(FICHES_LIVE.glob("*.html"))} | \
        {p.stem: p.read_text(encoding="utf-8") for p in sorted((FICHES_LIVE / "cas").glob("*.html"))}


# ---------------------------------------------------------------- V1

def bs_read(page: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    t = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not t.startswith("Fiche formation"):
        return None
    head = soup.find(id="header-ff-liste-badges")
    out = {"labels": [], "etab": None, "bourses": None, "frais": []}
    if head:
        e = head.find(id="badge-type-contrat")
        out["etab"] = " ".join(e.get_text(" ").split()) if e else None
        for sp in head.find_all("span", class_="fr-badge"):
            x = " ".join(sp.get_text(" ").split())
            if x == "Formation ouvrant droit aux bourses":
                out["bourses"] = True
            elif re.fullmatch(r"Formation n.ouvrant pas droit aux bourses", x):
                out["bourses"] = False
        for img in head.find_all("img", class_="img_labellisation"):
            code = re.search(r"labellisation/([A-Za-z0-9_]+)\.svg", img.get("src", "")).group(1)
            sp = img.find_parent("div", class_="d-flex").find_next("span", class_="fr-badge")
            out["labels"].append((code, " ".join(sp.get_text(" ").split())))
    for title in soup.find_all(class_="fr-callout__title"):
        if title.get_text(strip=True).startswith("Frais de scolarit"):
            box = title.find_parent(class_="fr-callout")
            for h in box.find_all(["h5", "h6"]):
                if "fr-callout__title" in (h.get("class") or []):
                    continue
                p = h.find_next_sibling("p")
                if p is not None:
                    out["frais"].append((" ".join(h.get_text(" ").split()), " ".join(p.get_text(" ").split())))
            break
    return out


@check("V1 fiche reader: State labels, establishment and grants badges, fee lines = an independent BeautifulSoup reading")
def v1(c: Ctx):
    _rc, _vie, fp = c.mods()
    bad, n = [], 0
    for code, page in pages().items():
        ref = bs_read(page)
        got = fp.parse(page)
        if ref is None:
            if got.get("badges") or got.get("frais"):
                bad.append(f"{code}: an error page gives badges or fees")
            continue
        n += 1
        b = got["badges"] or {}
        if [(x["code"], x["texte"]) for x in b.get("labels", [])] != ref["labels"]:
            bad.append(f"{code}: labels {b.get('labels')} != {ref['labels']}")
        if b.get("bourses") != ref["bourses"] or b.get("etab_type") != ref["etab"]:
            bad.append(f"{code}: grants/establishment {b.get('bourses')}/{b.get('etab_type')} != {ref['bourses']}/{ref['etab']}")
        fr = [(x["rubrique"], " ".join(x["texte"].split())) for x in got["frais"]]
        if fr != ref["frais"]:
            bad.append(f"{code}: fees {fr[:2]} != {ref['frais'][:2]}")
    if n < 8:
        bad.append(f"only {n} fiches read")
    return not bad, f"{n} fiches; {bad[:4]}"


# ---------------------------------------------------------------- V2

GROUND = {
    "Diplôme national de licence contrôlé par l'Etat": "national", "BTS contrôlé par l'Etat": "national",
    "BUT contrôlé par l'Etat": "national", "Diplôme d'Etat contrôlé": "etat",
    "Classe préparatoire contrôlée par l'Etat": "cpge", "Diplôme d'ingénieur contrôlé par l'Etat": "ingenieur",
    "Diplôme conférant grade de licence contrôlé par l'Etat": "grade_licence",
    "Diplôme visé conférant le grade de master contrôlé par l'Etat": "grade_master",
    "Diplôme visé contrôlé par l'Etat": "vise", "Titre RNCP de niveau 6": "rncp",
    "Diplôme national des métiers d'art et du design contrôlé par l'Etat": "national",
    "Un label inconnu": "autre",
}


def independent_cat(label: str) -> str:
    """The same categories, read with its own keyword lists (words, not the module's regexes)."""
    w = set(plainfold(label).split())
    f = " " + plainfold(label) + " "
    if "preparatoire" in w or "cpge" in w:
        return "cpge"
    if " grade de master " in f:
        return "grade_master"
    if " grade de licence " in f:
        return "grade_licence"
    if " diplome d ingenieur " in f:
        return "ingenieur"
    if "vise" in w:
        return "vise"
    if "rncp" in w or " titre professionnel " in f:
        return "rncp"
    if " diplome d etat " in f:
        return "etat"
    if " diplome national " in f or w & {"bts", "btsa", "but", "dcg", "deust", "dma", "licence", "master"} or " dn made " in f:
        return "national"
    return "autre"


@check("V2 badge: ground truth, every label sorted again independently, no label = aucun, RNCP only from a professional title")
def v2(c: Ctx):
    rc, _vie, _fp = c.mods()
    bad = []
    for lab, want in GROUND.items():
        if rc.categorie(lab) != want or independent_cat(lab) != want:
            bad.append(f"{lab!r}: {rc.categorie(lab)} / {independent_cat(lab)} != {want}")
    if rc.categorie("") is not None:
        bad.append("an empty label gets a category")
    # the build: labels from a fixture harvest; the RNCP fallback from the title only
    import duckdb
    with tempfile.TemporaryDirectory() as d:
        src = Path(d)
        rows = [("1", "Diplôme d'Etat contrôlé", "oui"), ("2", "", "non"), ("3", "", ""), ("4", "Un label inconnu", "")]
        with open(src / "identite.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["cod_aff_form", "session", "etab_type", "bourses", "labels_codes", "labels_textes"])
            for cod, lab, b in rows:
                w.writerow([cod, "2026", "Établissement public", b, "DL_09" if lab else "", lab])
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core")
        con.execute("""CREATE TABLE core.formation_year AS SELECT * FROM (VALUES ('1', 'DE Infirmier'),
            ('2', 'Formation professionnelle - Titre professionnel - Technicien'), ('3', 'BTS - Services'), ('4', 'X'))
            t(cod_aff_form, lib_for_voe_ins)""")
        rc.build(con, src)
        got = dict(con.execute("SELECT cod_aff_form, categorie FROM core.fiche_identite").fetchall())
        if got != {"1": "etat", "2": "rncp", "3": "aucun", "4": "autre"}:
            bad.append(f"build categories {got}")
        if con.execute("SELECT bourses FROM core.fiche_identite WHERE cod_aff_form = '2'").fetchone()[0] is not False:
            bad.append("'non' grants not stored as false")
        audit = dict(con.execute("SELECT categorie, exemple FROM meta.reconnaissance_audit").fetchall())
        if "Un label inconnu" not in (audit.get("autre") or ""):
            bad.append("an unknown label is not listed in the audit")
        txt = rc.LIBELLE["aucun"] + " " + rc.EXPLICATION["aucun"]
        if re.search(r"(?i)non reconnu", txt):
            bad.append("'aucun' is worded as 'non reconnu'")
    real = ROOT / "data" / "fiches" / "identite.csv"
    n = 0
    if real.exists():
        for r in csv.DictReader(open(real, encoding="utf-8")):
            for lab in (r.get("labels_textes") or "").split("|"):
                if lab.strip():
                    n += 1
                    if rc.categorie(lab) != independent_cat(lab):
                        bad.append(f"real label {lab!r}: {rc.categorie(lab)} != {independent_cat(lab)}")
    return not bad, f"{len(GROUND)} ground labels, {n} real labels; {bad[:4]}"


# ---------------------------------------------------------------- V3

FEES = {
    "178 euros + 800 euros de frais spécifiques": 978, "178 euros.": 178, "777": 777, "Aucun frais": 0,
    "628 € (Montant pour 2025/2026)": 628, "0 (Montant pour 2025/2026)": 0, "8 900 € par an": 8900,
    "1 415 € - Possibilité de régler en plusieurs fois sans frais": 1415,
    "Aucun frais - les frais sont à la charge de l'employeur": 0, "4 950 € par année": 4950,
    "178€ + 105€ (CVEC) tarif rentrée 2025 (Montant pour 2025/2026)": None,
    "Identique au candidat non boursier, mais remboursement sur présentation de la notification": None,
    "3 000 € - 1 500 € pour les boursiers": None, "8 900 € - 2 versements de 4 450 €": None,
    "Entre 5 000 et 7 000 €": None, "Voir le site de l'école": None, "": None, HOSTILE: None,
    "12 000 € (dont 2 000 € de frais de dossier)": None, "178 euros + " + HOSTILE: None, "178 € + 105 € de frais CVEC": None,
}


def numbers_sum(text: str) -> int:
    """Independent: the sum of the integer amounts printed (thousands separated by spaces or dots), the year left out."""
    t = re.sub(r"\(montant pour 20\d\d/20\d\d\)", "", text, flags=re.I)
    return sum(int(re.sub(r"\D", "", m)) for m in re.findall(r"\d{1,3}(?:[ \u202f\xa0.]\d{3})+|\d+", t))


@check("V3 fees: ground truth, hostile and mixed texts give no amount, every real amount = the numbers its text prints")
def v3(c: Ctx):
    _rc, vie, _fp = c.mods()
    bad = []
    for t, want in FEES.items():
        if vie.montant_annuel(t) != want:
            bad.append(f"{t[:40]!r}: {vie.montant_annuel(t)} != {want}")
    n = 0
    fr, tx = ROOT / "data" / "fiches" / "frais.csv", ROOT / "data" / "fiches" / "textes.csv.gz"
    if fr.exists() and tx.exists():
        with gzip.open(tx, "rt", encoding="utf-8", newline="") as f:
            texts = {r["id"]: r["texte"] for r in csv.DictReader(f)}
        for r in csv.DictReader(open(fr, encoding="utf-8")):
            t = texts.get(r["texte_id"]) or ""
            a = vie.montant_annuel(t)
            if a is None:
                continue
            n += 1
            if "cvec" in t.lower() or a != numbers_sum(t):
                bad.append(f"{r['cod_aff_form']}: {a} read from {t[:50]!r}")
    return not bad, f"{len(FEES)} ground texts, {n} real amounts; {bad[:4]}"


# ---------------------------------------------------------------- V4

def haversine(a, b, c2, d):
    p = math.pi / 180
    h = 0.5 - math.cos((c2 - a) * p) / 2 + math.cos(a * p) * math.cos(c2 * p) * (1 - math.cos((d - b) * p)) / 2
    return 12742 * math.asin(math.sqrt(h))


def fixture(vie, rc, d: Path, fees: str = "178 euros + 800 euros de frais spécifiques", cvec: bool = True, postes: bool = True):
    """A small warehouse: formations in Paris 5e, Toulouse (zone-predicted rent) and Nowhere (no rent), rents, Crous, fees."""
    import duckdb
    import pandas as pd
    raw, fiches = d / "raw", d / "fiches"
    raw.mkdir(parents=True)
    fiches.mkdir(parents=True)
    pd.DataFrame([{"INSEE_C": "75105", "LIBGEO": "Paris 5e Arrondissement", "DEP": "75", "loypredm2": "33,1", "lwr.IPm2": "26,8",
                   "upr.IPm2": "40,2", "TYPPRED": "commune", "nbobs_com": "5000"},
                  {"INSEE_C": "31555", "LIBGEO": "Toulouse", "DEP": "31", "loypredm2": "15.2", "lwr.IPm2": "12.4", "upr.IPm2": "18.9",
                   "TYPPRED": "maille", "nbobs_com": "3"},
                  {"INSEE_C": "86194", "LIBGEO": "Toulouse", "DEP": "86", "loypredm2": "99", "lwr.IPm2": "98", "upr.IPm2": "100",
                   "TYPPRED": "commune", "nbobs_com": "9"},
                  {"INSEE_C": "54547", "LIBGEO": "Vandœuvre-lès-Nancy", "DEP": "54", "loypredm2": "11", "lwr.IPm2": "9", "upr.IPm2": "13",
                   "TYPPRED": "commune", "nbobs_com": "900"}]).to_parquet(raw / "loyers_app12_2025.parquet")
    pd.DataFrame([{"title": "Résidence " + HOSTILE, "zone": "Paris", "infos": "(Loyer TCC hors ALS au 01/09/24) chambres 9m² : 269 € ; studios : 450,50 €",
                   "geocalisation": "48.8399, 2.3378", "bookingurl": "https://trouverunlogement.lescrous.fr/"},
                  {"title": "Fermée", "zone": "Paris", "infos": "Fermeture définitive au 31 août 2025 ; 300 €", "geocalisation": "48.84, 2.34",
                   "bookingurl": "https://x"},
                  {"title": "Sans prix", "zone": "Paris", "infos": "Studios de 18 m²", "geocalisation": "48.85, 2.35",
                   "bookingurl": "javascript:alert(1)"},
                  {"title": "Loin", "zone": "Paris", "infos": "250 €", "geocalisation": "48.95, 2.45", "bookingurl": "https://y"}]
                 ).to_parquet(raw / "crous_logement.parquet")
    pd.DataFrame([{"title": "RU", "geolocalisation": "48.8395, 2.3370"}, {"title": "RU loin", "geolocalisation": "49.5, 2.3"}]
                 ).to_parquet(raw / "crous_restauration.parquet")
    texts = {"t1": fees, "t2": "Aucun frais"}
    with gzip.open(fiches / "textes.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "texte"])
        w.writerows(texts.items())
    with open(fiches / "frais.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cod_aff_form", "session", "rang", "titre", "rubrique", "texte_id"])
        w.writerow(["1", "2026", "1", "Frais de scolarité", "Par année", "t1"])
        w.writerow(["1", "2026", "2", "Frais de scolarité", "Par année pour les étudiants boursiers", "t2"])
        if cvec:
            w.writerow(["1", "2026", "3", "Frais de scolarité", "Contribution Vie Etudiante et de Campus (CVEC)", "t2"])
        w.writerow(["2", "2026", "1", "Frais de scolarité", "Par année", "t2"])
    ove = d / "ove.csv"
    src = list(csv.DictReader(open(vie.OVE_CSV, encoding="utf-8")))
    with open(ove, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(src[0]))
        w.writeheader()
        w.writerows(src if postes else src[:6])
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.formation_year AS SELECT * FROM (VALUES
        ('1', 2025, 'Paris  5e  Arrondissement', '75', 48.8462, 2.3445), ('2', 2025, 'Toulouse', '31', 43.6, 1.44),
        ('3', 2025, 'Nowhere', '99', NULL, NULL), ('2', 2024, 'Paris 5e Arrondissement', '75', 48.8, 2.3),
        ('4', 2025, 'Vandoeuvre-lès-Nancy', '54', NULL, NULL))
        t(cod_aff_form, session, ville_etab, dep, lat, lon)""")
    vie.build(con, raw, fiches, ove)
    return con


@check("V4 cost card: rent = 20 m² x bounds by town and department, Crous by distance (closed out, euros only, https), totals by the fixed rule")
def v4(c: Ctx):
    rc, vie, _fp = c.mods()
    bad = []
    with tempfile.TemporaryDirectory() as d:
        con = fixture(vie, rc, Path(d))
        p, t, n = vie.for_formation(con, "1"), vie.for_formation(con, "2"), vie.for_formation(con, "3")
        r10 = lambda x: int(round(x / 10) * 10)  # noqa: E731
        lo = p and p["loyer"]
        if not lo or (lo["min"], lo["max"]) != (r10(26.8 * 20), r10(40.2 * 20)) or lo["maille"]:
            bad.append(f"Paris rent {lo}")
        if not t or not t["loyer"] or (t["loyer"]["min"], t["loyer"]["max"]) != (r10(12.4 * 20), r10(18.9 * 20)) or not t["loyer"]["maille"]:
            bad.append(f"Toulouse (31, zone-predicted) rent {t and t['loyer']}: the department must decide, the zone be flagged")
        if n and n["loyer"]:
            bad.append("a town without rent got one")
        v4_ = vie.for_formation(con, "4")
        if not v4_ or not v4_["loyer"] or v4_["loyer"]["min"] != 180:
            bad.append("Vandoeuvre (SIES) does not find Vandœuvre (rents): the ligature is not folded")
        names = [x["nom"] for x in (p or {}).get("crous", [])]
        cand = (("Résidence " + HOSTILE, 48.8399, 2.3378), ("Sans prix", 48.85, 2.35), ("Loin", 48.95, 2.45))
        want = [nm for dist, nm in sorted((haversine(48.8462, 2.3445, la, lo2), nm) for nm, la, lo2 in cand) if dist <= 10]
        if names != want or "Fermée" in names:
            bad.append(f"Crous {names} != {want}")
        res = {x["nom"]: x for x in (p or {}).get("crous", [])}
        r1 = res.get("Résidence " + HOSTILE) or {}
        if (r1.get("loyer_min"), r1.get("loyer_max"), r1.get("loyer_date")) != (269, 450.5, "01/09/24"):
            bad.append(f"Crous rent {r1}")
        if (res.get("Sans prix") or {}).get("loyer_min") is not None or (res.get("Sans prix") or {}).get("url"):
            bad.append("a residence without euros got a rent, or a javascript: link kept")
        if (p or {}).get("resto_n") != 1:
            bad.append(f"restaurants within 2 km {p and p.get('resto_n')}")
        post = {x["source_poste"]: x for x in (p or {}).get("postes", [])}
        run_ = sum(post[k]["montant"] for k in vie.POSTES_COURANTS)
        allp = run_ + sum(post[k]["montant"] for k in vie.POSTES_SELON)
        if "Dépense de loyer" in post or "Garde d'enfant" in post:
            bad.append("the survey's rent or child care item is used")
        m = (p or {}).get("mensuel") or {}
        if (m.get("min"), m.get("max")) != (r10(lo["min"] + run_), r10(lo["max"] + allp)):
            bad.append(f"monthly {m} != rule")
        a = (p or {}).get("annuel") or {}
        if (a.get("min"), a.get("max")) != (r10(10 * m["min"] + 978 + 105), r10(10 * m["max"] + 978 + 105)):
            bad.append(f"year {a}")
        if t and t.get("annuel") and t["annuel"]["cvec"] != 0:
            bad.append("the CVEC added where the fiche prints no CVEC paragraph")
        con2 = fixture(vie, rc, Path(d) / "b", fees="Entre 5 000 et 7 000 €")
        if vie.for_formation(con2, "1")["annuel"] is not None:
            bad.append("a year computed without a fee amount")
        con3 = fixture(vie, rc, Path(d) / "c", postes=False)
        if vie.for_formation(con3, "1")["mensuel"] is not None:
            bad.append("a monthly total with survey items missing")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- V5

@check("V5 OVE survey: the transcribed items = the brochure kept in data/sources (labels, amounts, 781 € total, order, quoted sentences)")
def v5(c: Ctx):
    _rc, vie, _fp = c.mods()
    bad = []
    pdf = ROOT / "data" / "sources" / "ove" / "OVE-BROCHURE-REPERES-CDV2023-1.pdf"
    rows = list(csv.DictReader(open(vie.OVE_CSV, encoding="utf-8")))
    if len(rows) != 12:
        bad.append(f"{len(rows)} items")
    amounts = [int(r["montant"]) for r in rows]
    if amounts != sorted(amounts, reverse=True) or len(set(amounts)) != len(amounts):
        bad.append("amounts not in the chart's decreasing order")
    if set(vie.POSTES_COURANTS + vie.POSTES_SELON) - {r["poste"] for r in rows}:
        bad.append("an item of the rule is not in the survey")
    if not pdf.exists():
        return False, "the brochure is missing"
    import logging
    logging.disable(logging.WARNING)
    import pypdf
    text = pypdf.PdfReader(str(pdf)).pages[26].extract_text() or ""
    logging.disable(logging.NOTSET)
    flat = re.sub(r"\s+", " ", text).replace("\u2019", "'")
    for r in rows:
        if r["poste"].split(" (")[0] not in flat:
            bad.append(f"label {r['poste']!r} not on page 27")
        if not re.search(rf"\b{r['montant']} €", flat):
            bad.append(f"amount {r['montant']} € not on page 27")
        if not re.search(rf"\b{r['part_concernes']} ?%\*", flat):
            bad.append(f"share {r['part_concernes']} % not on page 27")
    if "781 €" not in flat or "413 € de dépenses de loyer et 115 € de frais liés au logement" not in flat.replace("  ", " ") \
            or not re.search(r"frais de vie quotidienne qui représentent .{0,80}95 € mensuels", flat):
        bad.append("the total or the quoted sentences differ")
    return not bad, f"{len(rows)} items; {bad[:4]}"


# ---------------------------------------------------------------- V6

def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("(") == part.count(")") and part.rstrip().endswith(";"):
                return part
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


@check("V6 page: escaped, computed figures labelled, fiche fait foi, only the rent is local, vouvoiement, no chance, safe links")
def v6(c: Ctx):
    rc, vie, _fp = c.mods()
    defs = "\n".join(top(c.js, n) for n in ("esc", "fmt", "euros", "eurosRange", "recoPill", "recoBadge", "recoCard", "coutCard"))
    stub = """const ICONS = { check: '<svg class="i"></svg>' };
      const estimTag = (d) => `<span class="estim">estimation</span> ${esc(d || "")}`;
      let RECO = null;\n"""
    import duckdb
    with tempfile.TemporaryDirectory() as d:
        con = fixture(vie, rc, Path(d))
        v = vie.for_formation(con, "1")
    v["commune"] = "Paris " + HOSTILE
    v["frais"]["lignes"].append({"rubrique": "Par année " + HOSTILE, "texte": "x " + HOSTILE})
    reco = {"categorie": "national", "libelle": "Diplôme national", "explication": "Expl " + HOSTILE, "source": "label",
            "labels": ["Label " + HOSTILE], "codes": ["DL_01"], "bourses": False, "session": 2026}
    none = {"categorie": "aucun", "libelle": rc.LIBELLE["aucun"], "explication": rc.EXPLICATION["aucun"], "source": "label",
            "labels": [], "codes": [], "bourses": None, "session": 2026}
    prog = stub + defs + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify([coutCard(D.v, {}), coutCard(null, {}), recoCard(D.r), recoCard(D.n), recoCard(null),
        recoBadge("1"), recoPill("x" + D.h, "Lib " + D.h, "E " + D.h)]));"""
    out = node(prog, {"v": v, "r": reco, "n": none, "h": HOSTILE})
    if out is None:
        return True, "node absent: not run"
    cout, empty, rec, rnone, rnull, badge0, pill = out
    bad = []
    for i, h in enumerate(out):
        if "<img" in h:
            bad.append(f"output {i}: unescaped")
        txt = re.sub(r"<[^>]+>", " ", h)
        if re.search(r"(?i)\bchances?\b|probabilit", txt) or re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt):
            bad.append(f"output {i}: a chance or tutoiement")
        for a in re.findall(r"<a [^>]*>", h):
            if 'target="_blank"' in a and 'rel="noopener"' not in a:
                bad.append(f"output {i}: external link without noopener")
            href = re.search(r'href="([^"]*)"', a)
            if href and not re.match(r"https://|#/", href.group(1)):
                bad.append(f"output {i}: link {href.group(1)[:30]}")
    seg = lambda a, b: cout[cout.find(a): cout.find(b, cout.find(a))]  # noqa: E731
    for a, b in (("Par mois sur place", "Frais de la formation"), ("Sur une année", "</div>"), ("Loyer d'un studio", "</tr>"),
                 ("<strong>Total</strong>", "</tr>")):
        if 'class="estim"' not in seg(a, b):
            bad.append(f"{a!r} shown without the estimation label")
    if "fait foi" not in cout or "Seul le loyer est propre à la commune" not in cout:
        bad.append("cost card: the fiche or the national items not said")
    if "Pas encore de données" not in empty:
        bad.append("no data: no message")
    if "fait foi" not in rec or "« Label &lt;img" not in rec or "ouvre pas droit aux bourses" not in rec:
        bad.append("recognition card: label verbatim, fiche or grants missing")
    if re.search(r"(?i)non reconnu", rnone) or rnull != "" or badge0 != "":
        bad.append("no label worded 'non reconnu', or a card/badge without data")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- V7

@check("V7 real warehouse: categories, fee amounts, totals of a sample and the lists' answer re-derived from the stored tables")
def v7(c: Ctx):
    if c.db is None:
        return True, "no warehouse"
    import duckdb
    rc, vie, _fp = c.mods()
    con = duckdb.connect(str(c.db), read_only=True)
    has = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'core'").fetchall()}
    if not {"fiche_identite", "vie_loyer", "vie_frais", "vie_poste"} <= has:
        return True, "tables not built yet in this warehouse (the data workflow builds them)"
    bad = []
    for cod, labs, cat, source in con.execute("SELECT cod_aff_form, labels_textes, categorie, source FROM core.fiche_identite").fetchall():
        first = next((x for x in (labs or "").split("|") if x.strip()), None)
        want = independent_cat(first) if first else ("rncp" if source == "intitule" else "aucun")
        if cat != want:
            bad.append(f"{cod}: {cat} != {want}")
    for cod, rub, txt, m in con.execute("SELECT cod_aff_form, rubrique, texte, montant FROM core.vie_frais WHERE montant IS NOT NULL").fetchall():
        if (rub or "").strip().lower() != "par année" or m != numbers_sum(txt or "") or "cvec" in (txt or "").lower():
            bad.append(f"{cod}: fee {m} from {(txt or '')[:40]!r}")
    sample = [c2 for (c2,) in con.execute("""SELECT DISTINCT cod_aff_form FROM core.vie_frais USING SAMPLE 60 ROWS""").fetchall()]
    n_tot = 0
    for cod in sample:
        v = vie.for_formation(con, cod)
        if not v or not v.get("mensuel"):
            continue
        n_tot += 1
        post = {x["source_poste"]: x["montant"] for x in v["postes"]}
        lo = v["loyer"]
        m = v["mensuel"]
        r10 = lambda x: int(round(x / 10) * 10)  # noqa: E731
        if m["min"] != r10(lo["min"] + sum(post[k] for k in vie.POSTES_COURANTS)) or \
                m["max"] != r10(lo["max"] + sum(post.values())):
            bad.append(f"{cod}: monthly {m}")
    comp = rc.compact(con, vie.compact(con))
    codes = {x for v in comp["codes"].values() for x in v.split(",") if x}
    if codes != {x for (x,) in con.execute("SELECT cod_aff_form FROM core.fiche_identite").fetchall()}:
        bad.append("the lists' answer differs from the table")
    return not bad, f"{n_tot} totals re-derived; {bad[:4]}"


# ---------------------------------------------------------------- V8

@check("V8 plumbing: build, API, cache policy, analytics tab, sources, fingerprints, release feature, durations, docs")
def v8(c: Ctx):
    bad = []
    b = (ROOT / "suptracker" / "build.py").read_text()
    if "reconnaissance.build(con)" not in b or "vie.build(con, raw_dir)" not in b:
        bad.append("build.py")
    api = (ROOT / "suptracker" / "api.py").read_text()
    for w in ('"reconnaissance": RC.for_formation(', '"vie": VIE.for_formation(', '@app.get("/api/reconnaissance")'):
        if w not in api:
            bad.append(f"api: {w}")
    from suptracker import analytics, cache, config, sources
    if "cout" not in analytics.FICHE_TABS or '["cout", "Combien ça coûte"' not in c.js:
        bad.append("tab 'cout' (page and analytics list)")
    if '(r"/api/reconnaissance", PUBLIC,' not in (ROOT / "suptracker" / "cache.py").read_text():
        bad.append("cache policy")
    keys = {s["key"] for s in sources.SOURCES}
    for k in ("crous_logement", "crous_restauration", "carte_loyers", "ove_cdv2023"):
        if k not in keys:
            bad.append(f"source {k}")
    ds = {d.key for d in config.DATASETS}
    if not {"crous_logement", "crous_restauration", "loyers_app12_2025"} <= ds:
        bad.append("datasets")
    wf = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    if wf.count("data/fiches/identite.csv data/fiches/frais.csv") != 3:
        bad.append("data workflow fingerprints")
    if '"reconnaissance_vie"' not in (ROOT / "tests" / "test_release.py").read_text():
        bad.append("release feature")
    if "tests/test_vie.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    if "## Étudier là-bas" not in (ROOT / "README.md").read_text(encoding="utf-8"):
        bad.append("README")
    if "vie.py" not in (REPO / "CLAUDE.md").read_text(encoding="utf-8"):
        bad.append("CLAUDE.md")
    for call in ("recoLoad()", "${recoBadge(r.cod_aff_form)}", "recoBadge(f.cod_aff_form)", "${recoBadge(v.cod_aff_form)}",
                 "${recoCard(d.reconnaissance)}", "coutCard(d.vie, r)"):
        if call not in c.js:
            bad.append(f"page: {call}")
    return not bad, f"{bad[:5]}"


# ---------------------------------------------------------------- V9

SOURCE_MUTANTS = [
    ("fp", "fees: only h5 lines", 'r"<h([56])[^>]*>(.*?)</h\\1>\\s*<p[^>]*>(.*?)</p>"', 'r"<h([5])[^>]*>(.*?)</h\\1>\\s*<p[^>]*>(.*?)</p>"', "V1"),
    ("fp", "grants never false", '            out["bourses"] = False', '            out["bourses"] = None', "V1"),
    ("rc", "visé before grade", '    ("grade_master", r"grade de master"),\n    ("grade_licence", r"grade de licence"),\n    ("ingenieur", r"\\bdiplome d ingenieur"),\n    ("vise", r"\\bvise\\b"),',
     '    ("vise", r"\\bvise\\b"),\n    ("grade_master", r"grade de master"),\n    ("grade_licence", r"grade de licence"),\n    ("ingenieur", r"\\bdiplome d ingenieur"),', "V2"),
    ("rc", "ligature not folded", '    s = (s or "").replace("œ", "oe")', '    s = (s or "").replace("œ", "œ")', "V4"),
    ("rc", "unknown label as national", '    return "autre"', '    return "national"', "V2"),
    ("rc", "RNCP from any title", '        elif re.search(TITLE_RNCP, fold(titles.get(r["cod_aff_form"]))):', "        elif True:", "V2"),
    ("vie", "CVEC summed in the fees", '    if "cvec" in f:\n        return None', '    if False:\n        return None', "V3"),
    ("vie", "comment with figures accepted", 'r"(.*?\\d.*?)\\s+-\\s+([^\\d+]*)"', 'r"(.*?\\d.*?)\\s+-\\s+(.*)"', "V3"),
    ("vie", "studio 25 m²", "STUDIO_M2 = 20", "STUDIO_M2 = 25", "V4"),
    ("vie", "rent by name only", '    key = f"{fold(nom)}|{str(dep or \'\').strip()}"', '    key = f"{fold(nom)}|%"', "V4"),
    ("vie", "zone-predicted rent not flagged", "(typ or \"\").strip().lower() != \"commune\"", "False", "V4"),
    ("vie", "closed residences kept", 'if re.search(r"fermeture definitive|ferme definitivement|definitivement ferme", fold(text)):', "if False:", "V4"),
    ("vie", "Crous radius 20 km", "RAYON_CROUS_KM = 10", "RAYON_CROUS_KM = 20", "V4"),
    ("vie", "every item in the low bound", '"min": _arrondi(out["loyer"]["min"] + toujours)', '"min": _arrondi(out["loyer"]["min"] + toujours + selon)', "V4"),
    ("vie", "CVEC always added", '        cv = CVEC["montant"] if out["frais"]["cvec"] else 0', '        cv = CVEC["montant"]', "V4"),
    ("vie", "unsafe link kept", 'url if (url or "").startswith("https://") else None', "url", "V4"),
    ("vie", "survey rent used", 'POSTES_COURANTS = ("Frais de vie quotidienne",', 'POSTES_COURANTS = ("Dépense de loyer", "Frais de vie quotidienne",', "V4"),
    ("js", "label unescaped", '`« ${esc(t)} »`', '`« ${t} »`', "V6"),
    ("js", "monthly without estimation", '`logement, courses, transports… ${estimTag("loyer local + moyennes nationales")}`', '`logement, courses, transports…`', "V6"),
    ("js", "commune unescaped", "<h3>Vivre à ${esc(v.commune || \"\")}, chaque mois</h3>", "<h3>Vivre à ${v.commune || \"\"}, chaque mois</h3>", "V6"),
    ("js", "Crous link without noopener", 'target="_blank" rel="noopener">Demander un logement ↗</a>', 'target="_blank">Demander un logement ↗</a>', "V6"),
    ("js", "national items not said", "<p class=\"muted small\">Seul le loyer est propre à la commune.", "<p class=\"muted small\">", "V6"),
]


@check("V9 mutation test: mutants of the reader, the badge rules, the fees, the cost card and the page, each caught")
def v9(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:8] if not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
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
        except Exception:  # noqa: BLE001  a crash is a catch
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
    ap.add_argument("--real", action="store_true", help="also re-derive the committed warehouse's tables")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
