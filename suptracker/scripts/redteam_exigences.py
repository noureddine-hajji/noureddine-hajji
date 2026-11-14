"""Red team, what each Parcoursup fiche WRITES about specialties and about setting a file aside (owner, 2026-11-14;
suptracker/exigences.py, the jury tab's specialitesCard, the lists' exigeMark, the specialties page's exigencesTypeCard).

  EX1 measure: the rules read the hand-labelled sentences (data/exigences_gold.csv, every sentence of the first harvest that
      names a specialty and carries a requirement word, labelled by reading) with precision >= 0.90 and recall >= 0.85; the
      gold file holds both labels, no address or number; the build stores exactly the measure it recomputes (never typed).
  EX2 independent marks: norm() keeps every index; every quoted mention slices the original text to a spelling of its own
      specialty, read by an independent table of word stems; nothing outside a specialty name is marked.
  EX3 hostile sentences: French words ("si", "ses"), a formation's name ("licence Physique-Chimie"), physical condition,
      the ST2S "physique-chimie pour la santé", negations ("nullement", "n'est pas un prérequis", "sans qu'elle soit
      indispensable"), a level ("un bon niveau en physique est requis"), a condition ("lorsque la spécialité SVT est
      suivie..."), advice after the name ("l'option maths expertes est un plus") are never "required"; alternatives ("ou",
      "et/ou", "ou les") are one group; years read as written ("première et/ou terminale" = either); the elimination reading
      drops its negations.
  EX4 twin: the page's exigeManque equals exigences.missing for every pair of specialties, Maths expertes or not, on synthetic
      groups and (--real) on every group the warehouse serves.
  EX5 build round trip on synthetic fiches: every quoted sentence is a verbatim piece of its fiche's text; the required groups
      the lists read equal those of the quoted sentences; a fiche naming no specialty is absent; the side file is used when
      given; an unknown code is None. --real: the same on the committed warehouse and its texts file.
  EX6 page (node): every stored string escaped (sentences, establishment, type); the student's specialties marked, others
      not; the list mark appears only for a stored terminale bac général profile whose pair misses a required group, never
      for bac techno, outside terminale, without data, for a pair that meets the group or a première-only group; never a zone
      colour, never "refusé" as a verdict, the measure printed from the data, vouvoiement.
  EX7 plumbing: /api/exigences has no parameter and a public cache policy; the page asks it with no query; the build calls
      exigences.build; search results, map cards, Mes vœux, L'essentiel, the jury tab and the specialties page use it;
      release feature; README, CLAUDE.md, durations.
  EX8 mutation test: mutants of the rules and the page, each caught.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import inspect
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
CHECKS = []
CODES = ["MATHS", "PC", "SVT", "SES", "HGGSP", "HLP", "LLCER", "LLCA", "NSI", "SI", "BIOECO", "EPPCS", "ART"]


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str | None = None, package: str | None = None):
    m = types.ModuleType(name)
    m.__file__ = str(path)
    if package:
        m.__package__ = package
    exec(compile(src if src is not None else path.read_text(), str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, real: bool = False, db: Path | None = None):
        self.real, self.db = real, db
        self.src = {"ex": (ROOT / "suptracker" / "exigences.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self):
        return load(ROOT / "suptracker" / "exigences.py", "suptracker.exigences_rt", self.src["ex"], package="suptracker")


# ---------------------------------------------------------------- EX1

@check("EX1 measure: precision >= 0.90 and recall >= 0.85 on the hand-read sentences; the build stores the recomputed measure")
def ex1(c: Ctx):
    import duckdb
    X = c.mod()
    gold = X.read_gold()
    bad = []
    if len(gold) < 300 or not any(g for _s, g in gold) or all(g for _s, g in gold):
        bad.append(f"gold set: {len(gold)} sentences")
    if any(re.search(r"@|\b0\d(?:[ .]?\d\d){4}\b", s) for s, _g in gold):
        bad.append("an address or a phone number in the gold set")
    # recomputed here, independently of measure()
    tp = sum(1 for s, g in gold if g and X.requirement(s))
    fp = sum(1 for s, g in gold if not g and X.requirement(s))
    fn = sum(1 for s, g in gold if g and not X.requirement(s))
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    if prec < 0.90 or rec < 0.85:
        bad.append(f"precision {prec:.3f}, recall {rec:.3f}")
    m = X.measure()
    if (m["justes"], m["lus_exiges"], m["positifs"], m["n"]) != (tp, tp + fp, tp + fn, len(gold)):
        bad.append(f"measure() {m} differs from the recount {tp}/{tp + fp}/{tp + fn}")
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as d:
        X.build(con, textes=None, src=Path(d))
    if X.mesure(con) != {k: m[k] for k in ("n", "positifs", "lus_exiges", "justes", "precision", "rappel")}:
        bad.append(f"stored measure {X.mesure(con)} != {m}")
    return not bad, f"precision {prec:.3f}, recall {rec:.3f} on {len(gold)} sentences; {bad[:4]}"


# ---------------------------------------------------------------- EX2

STEMS = {"MATHS": ("math",), "MATHS_EXP": ("expert",), "MATHS_COMP": ("complem",), "PC": ("physi",), "SVT": ("svt", "vie"),
         "SES": ("ses", "econom"), "HGGSP": ("hggsp", "geopol"), "HLP": ("hlp", "humanit"), "LLCER": ("llce", "litterat"),
         "LLCA": ("llca", "antiq"), "NSI": ("nsi", "numeri"), "SI": ("si", "ingen"), "BIOECO": ("ecolog",),
         "EPPCS": ("eppcs", "education physique"), "ART": ("art", "cinema", "musique", "theatre", "danse", "cirque")}


def _plain(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


@check("EX2 independent marks: indexes kept; every mention slices to a spelling of its own specialty")
def ex2(c: Ctx):
    X = c.mod()
    bad, n = [], 0
    texts = [s for s, _g in X.read_gold()] + [s for s, *_ in HOSTILE_CASES]
    for s in texts:
        if len(X.norm(s)) != len(s):
            bad.append(f"norm changes the length: {s[:40]!r}")
            continue
        ms, _ns = X.mentions(s)
        for a, b, k in ms:
            n += 1
            piece = _plain(s[a:b])
            if not any(st in piece for st in STEMS[k]):
                bad.append(f"{k} marks {s[a:b]!r}")
            if k in ("SI", "SES") and len(piece) <= 4 and s[a:b] != s[a:b].upper():
                bad.append(f"lower-case {s[a:b]!r} read as {k}")
    return not bad, f"{n} mentions checked; {bad[:4]}"


# ---------------------------------------------------------------- EX3

# sentence, requirement?, expected required groups (as sets) or None (not checked), year of the first required group
HOSTILE_CASES = [
    ("Il est indispensable de lire ses appréciations si possible.", False, None, None),
    ("Il est indispensable pour les candidats à la licence Physique-Chimie, de suivre l'enseignement de Spécialité Physique-Chimie jusqu'en terminale.", True, [{"PC"}], "terminale"),
    ("Une bonne condition physique est nécessaire pour intégrer cette formation.", False, None, None),
    ("doivent avoir suivi les spécialités « biologie et physiopathologies humaines » + « physique chimie pour la santé » et ST2S", False, None, None),
    ("L'option \"mathématiques expertes\", nullement obligatoire, est aussi un atout pour le dossier.", False, None, None),
    ("En complément, une apétance pour l'économie est un plus, bien que la spécialité SES ne soit pas un prérequis.", False, None, None),
    ("Le suivi de la spécialité sciences de l'ingénieur est utile, sans qu'elle n'ait pour autant un caractère indispensable.", False, None, None),
    ("Un bon niveau en mathématiques et en physique-chimie est requis.", False, None, None),
    # the condition is not a requirement of SVT; what it requires then (Maths or Physique-chimie) is one group
    ("Lorsque la spécialité SVT est suivie en terminale celle-ci doit être combinée avec la spécialité Maths ou Physique-Chimie.", True, [{"MATHS", "PC"}], "terminale"),
    ("La spécialité mathématiques en terminale est indispensable, l'option mathématiques expertes est un plus.", True, [{"MATHS"}], "terminale"),
    ("En Terminale, la mathématique est obligatoire, l'autre spécialité doit être la physique-chimie ou les sciences de l'ingénieur.", True, [{"MATHS"}, {"PC", "SI"}], "terminale"),
    ("Le suivi de SVT en première et/ou Terminale est indispensable.", True, [{"SVT"}], "l_une"),
    ("Spé mathématiques obligatoire en première et terminale", True, [{"MATHS"}], "les_deux"),
    ("En Première, la physique-chimie est obligatoire.", True, [{"PC"}], "premiere"),
    ("Nous exigeons la spécialité Mathématiques ou l'option Mathématiques complémentaires en Terminale.", True, [{"MATHS", "MATHS_COMP"}], "terminale"),
    ("La présence d'enseignement de science de la vie ou de biologie-écologie dans le parcours récent est obligatoire.", True, [{"SVT", "BIOECO"}], None),
]
ELIM_CASES = [("Une note inférieure à 10/20 à l'entretien individuel est éliminatoire.", True),
              ("Néanmoins une faiblesse dans une matière n'est pas éliminatoire.", False),
              ("Il n'y a pas de seuils de notes à atteindre.", False),
              ("Les dossiers avec avis réservé du Chef d'établissement ne sont pas étudiés.", True),
              ("Tout dossier incomplet sera refusé.", True)]


@check("EX3 hostile sentences: French words, names, levels, negations, conditions, advice never required; alternatives one group")
def ex3(c: Ctx):
    X = c.mod()
    bad = []
    for s, req, groups, year in HOSTILE_CASES:
        st = X.statements(s)
        got = [x for x in st if x["classe"] == "exigee"]
        if bool(got) != req:
            bad.append(f"{'missed' if req else 'read as required'}: {s[:60]!r} {st}")
            continue
        if groups is not None and sorted(map(sorted, (set(x["spe"]) for x in got))) != sorted(map(sorted, groups)):
            bad.append(f"groups {[x['spe'] for x in got]} != {groups}: {s[:50]!r}")
        if req and got[-1]["annee"] != year and got[0]["annee"] != year:
            bad.append(f"year {got[0]['annee']} != {year}: {s[:50]!r}")
    for s, el in ELIM_CASES:
        if X.elimination(s) != el:
            bad.append(f"elimination {not el}: {s[:50]!r}")
    return not bad, f"{len(HOSTILE_CASES)} + {len(ELIM_CASES)} sentences; {bad[:3]}"


# ---------------------------------------------------------------- page helpers

def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:                                       # whole lines until the brackets balance and the line ends the statement
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("[") == part.count("]") and part.rstrip().endswith(";"):
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


# ---------------------------------------------------------------- EX4

def _groups_real(c: Ctx) -> list[dict]:
    if not (c.real and c.db and c.db.exists()):
        return []
    import duckdb
    X = c.mod()
    con = duckdb.connect(str(c.db), read_only=True)
    try:
        return [g for f in X.listing(con.cursor())["formations"].values() for g in f["exige"]]
    finally:
        con.close()


@check("EX4 twin: the page's exigeManque equals exigences.missing for every pair, Maths expertes or not")
def ex4(c: Ctx):
    X = c.mod()
    groups = [{"spe": ["PC"], "annee": None}, {"spe": ["PC"], "annee": "premiere"}, {"spe": ["SVT"], "annee": "l_une"},
              {"spe": ["PC", "SI"], "annee": "terminale"}, {"spe": ["MATHS_EXP"], "annee": None}, {"spe": ["MATHS_COMP"], "annee": None},
              {"spe": ["MATHS", "MATHS_COMP"], "annee": "terminale"}, {"spe": ["ART"], "annee": "les_deux"},
              {"spe": ["SES", "HGGSP"], "annee": None}] + _groups_real(c)
    cases = [(a, b, me) for i, a in enumerate(CODES) for b in CODES[i + 1:] for me in (False, True)]
    want = [[len(X.missing([g], (a, b), me)) > 0 for g in groups] for a, b, me in cases]
    prog = top(c.js, "exigeManque") + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify(D.cases.map(([a, b, me]) => D.groups.map((g) => exigeManque([g], { spe: [a, b], me }).length > 0))));"""
    got = node(prog, {"cases": cases, "groups": groups})
    if got is None:
        return True, "node absent: not run"
    diff = [(cases[i], groups[j]) for i in range(len(cases)) for j in range(len(groups)) if got[i][j] != want[i][j]]
    return not diff, f"{len(cases)} pairs x {len(groups)} groups; {diff[:3]}"


# ---------------------------------------------------------------- EX5

def _fiches(d: Path, fiches: dict) -> Path:
    """A data/fiches directory in the harvest's format: {code: {"conseils": text, "criteres": [(champ, label, elements, imp)]}}."""
    import hashlib
    tid = lambda t: hashlib.sha1(t.encode()).hexdigest()[:16] if t else ""  # noqa: E731
    texts, etat, champs, crits, atts = {}, [], [], [], []
    for cod, f in fiches.items():
        st = "ok" if f.get("criteres") else "sans_grille"
        etat.append({"cod_aff_form": cod, "status": st, "lu_le": "20261114120000", "session": "2026", "raison": "",
                     "url": f"https://dossier.parcoursup.fr/x?g_ta_cod={cod}", "version": "2"})
        a = {"cod_aff_form": cod, "session": "2026", "nationaux_id": tid("Attendus nationaux."), "complementaires_id": tid(f.get("complementaires")),
             "conseils_id": tid(f.get("conseils")), "info_id": ""}
        texts[tid("Attendus nationaux.")] = "Attendus nationaux."
        for k in ("complementaires", "conseils"):
            if f.get(k):
                texts[tid(f[k])] = f[k]
        atts.append(a)
        if st == "ok":
            champs.append({"cod_aff_form": cod, "session": "2026", "rang": 1, "champ": "Résultats scolaires", "poids": 100, "intitule_id": ""})
            for i, (_ch, lab, el, imp) in enumerate(f["criteres"], 1):
                texts[tid(lab)], texts[tid(el)] = lab, el
                crits.append({"cod_aff_form": cod, "session": "2026", "champ_rang": 1, "rang": i, "critere_id": tid(lab),
                              "elements_id": tid(el), "importance": imp})
    d.mkdir(parents=True, exist_ok=True)

    def w(name, rows, cols):
        with open(d / name, "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)
    w("etat.csv", etat, ["cod_aff_form", "status", "lu_le", "session", "raison", "url", "version"])
    w("champs.csv", champs, ["cod_aff_form", "session", "rang", "champ", "poids", "intitule_id"])
    w("criteres.csv", crits, ["cod_aff_form", "session", "champ_rang", "rang", "critere_id", "elements_id", "importance"])
    w("attendus.csv", atts, ["cod_aff_form", "session", "nationaux_id", "complementaires_id", "conseils_id", "info_id"])
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=["id", "texte"])
    wr.writeheader()
    wr.writerows({"id": k, "texte": v} for k, v in texts.items())
    (d / "textes.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))
    return d


SYNTH = {
    "101": {"conseils": "Spé mathématiques obligatoire en première et terminale. Spé physique-chimie obligatoire en terminale. Une note "
                        "inférieure à 8/20 à l'oral est éliminatoire.",
            "criteres": [("Résultats scolaires", "Résultats en physique-chimie", "Notes de terminale <b>pc</b>", 4)]},
    "102": {"conseils": "La spécialité SES n'est pas un prérequis. Un bon niveau en mathématiques est requis."},
    "103": {"conseils": "Soyez motivés et curieux."},
    "104": {"complementaires": "Il est nécessaire d'avoir suivi la spécialité NSI ou SI en terminale <script>x</script>."},
}


@check("EX5 round trip: quoted sentences verbatim, list groups = quoted groups, side file, unknown code; --real on the warehouse")
def ex5(c: Ctx):
    import duckdb
    X = c.mod()
    bad = []
    with tempfile.TemporaryDirectory() as d:
        src = _fiches(Path(d) / "fiches", SYNTH)
        from suptracker import rapports
        side = rapports.textes_path(Path(d) / "w.duckdb")
        duckdb.connect(str(side)).close()
        con = duckdb.connect(str(Path(d) / "w.duckdb"))
        con.execute("CREATE SCHEMA core")
        con.execute("CREATE TABLE core.formation_year AS SELECT * FROM (VALUES ('101', 2025, 'MPSI', 'Lycée <A>'), ('102', 2025, 'ECG', 'L2'), "
                    "('104', 2025, 'BUT', 'IUT')) t(cod_aff_form, session, fil_lib_voe_acc, g_ea_lib_vx)")
        res = X.build(con, textes=side, src=src)
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'exigence_data'").fetchone()[0]:
            bad.append("sentences in the warehouse although a texts file was given")
        con.close()
        con = duckdb.connect(str(Path(d) / "w.duckdb"))
        raw = {k: " ".join(v.get(x, "") for x in ("conseils", "complementaires")) + " " + " ".join(a + " " + b for _c, a, b, _i in v.get("criteres", []))
               for k, v in SYNTH.items()}
        for cod in SYNTH:
            sp = X.for_formation(con, cod)
            if cod == "103":
                if sp is not None:
                    bad.append("a fiche naming no specialty is served")
                continue
            if not sp:
                bad.append(f"{cod}: nothing served")
                continue
            for p in sp["phrases"]:
                if p["texte"] not in raw[cod]:
                    bad.append(f"{cod}: {p['texte'][:40]!r} not verbatim")
            want = X.required_groups(sp["phrases"])
            lst = X.listing(con).get("formations", {})
            if want and lst.get(cod, {}).get("exige") != want:
                bad.append(f"{cod}: list {lst.get(cod)} != quoted {want}")
            if not want and cod in lst:
                bad.append(f"{cod} listed without a required group")
        g101 = sorted(tuple(x["spe"]) for x in (X.for_formation(con, "101") or {}).get("exige", []))
        if g101 != [("MATHS",), ("PC",)]:
            bad.append(f"101 groups {g101}")
        if not any(p["ecarter"] for p in (X.for_formation(con, "101") or {}).get("phrases", [])):
            bad.append("101: the elimination sentence is not kept")
        if (X.for_formation(con, "102") or {}).get("exige"):
            bad.append("102: a negation or a level read as required")
        if X.for_formation(con, "999") is not None:
            bad.append("an unknown code is served")
        if X.listing(con)["formations"].get("101", {}).get("etab") != "Lycée <A>":
            bad.append("listing: establishment not carried")
        con.close()
    real = ""
    if c.real and c.db and c.db.exists():
        con = duckdb.connect(str(c.db), read_only=True)
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'fiche_exigence'").fetchone()[0]:
            con.close()
            return not bad, f"{len(SYNTH)} synthetic fiches; real: warehouse built before this feature (run the data workflow); {bad[:4]}"
        L = X.listing(con.cursor())
        if not L["mesure"] or not L["formations"]:
            bad.append("real: no measure or no formation listed")
        for cod, f in list(L["formations"].items()):
            sp = X.for_formation(con.cursor(), cod)
            if not sp or X.required_groups(sp["phrases"]) != f["exige"]:
                bad.append(f"real {cod}: list and quoted groups differ")
            for p in (sp or {}).get("phrases", []):
                for a, b, _k in p["marques"]:
                    if not (0 <= a < b <= len(p["texte"])):
                        bad.append(f"real {cod}: mark out of the sentence")
        real = f"; real: {len(L['formations'])} formations listed"
        con.close()
    return not bad, f"{len(SYNTH)} synthetic fiches{real}; {bad[:4]}"


# ---------------------------------------------------------------- EX6

HOSTILE = "<img src=x onerror=alert(1)>"


def _page_prog(c: Ctx) -> str:
    names = ("esc", "fmt", "pct1", "GR_IMP", "EX_SPE", "EX_SRC", "EX_CLASS", "EX_YEAR", "EX_HELP", "isReo", "bacProfile", "exigPair",
             "exigeManque", "exGroup", "exigeMark", "exMesure", "exQuote", "specialitesCard", "exigencesTypeCard")
    return """let PROFILE = null; let EXIG = null;
      const store = { get: (k, d) => (k === 'profile' ? (PROFILE ?? d) : d) };
      const ICONS = { fiche: '<svg class="ic"></svg>' };
      const profileRate = () => null; const PR_SOURCE = {};
      """ + "\n".join(top(c.js, n) for n in names) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const out = D.runs.map((r) => { PROFILE = r.profile; EXIG = r.exig;
        return { mark: exigeMark(r.cod), card: specialitesCard(r.sp, {}), type: exigencesTypeCard(r.exig) }; });
      process.stdout.write(JSON.stringify(out));"""


@check("EX6 page: escaped, own specialties marked, the list mark only for a missing group, never a zone or a verdict, vouvoiement")
def ex6(c: Ctx):
    mes = {"n": 360, "positifs": 125, "lus_exiges": 97, "justes": 89, "precision": 0.918, "rappel": 0.712}
    s1 = f"Spé physique-chimie obligatoire en terminale {HOSTILE}."
    sp = {"phrases": [{"src": "conseils", "champ": None, "critere": None, "importance": None, "texte": s1,
                       "groupes": [{"spe": ["PC"], "classe": "exigee", "annee": "terminale"}], "marques": [[4, 19, "PC"]], "ecarter": False},
                      {"src": "critere", "champ": "Résultats " + HOSTILE, "critere": "x", "importance": 4, "texte": "Notes en SES et en SVT.",
                       "groupes": [{"spe": ["SES"], "classe": "citee", "annee": None}, {"spe": ["SVT"], "classe": "citee", "annee": None}],
                       "marques": [[9, 12, "SES"], [19, 22, "SVT"]], "ecarter": False},
                      {"src": "conseils", "champ": None, "critere": None, "importance": None, "texte": "Absences éliminatoires " + HOSTILE,
                       "groupes": [], "marques": [], "ecarter": True}],
          "exige": [{"spe": ["PC"], "annee": "terminale"}], "mesure": mes}
    exig = {"mesure": mes, "lues": {"MPSI " + HOSTILE: 10}, "formations": {
        "1": {"exige": [{"spe": ["PC"], "annee": "terminale"}], "type": "MPSI " + HOSTILE, "etab": "Lycée " + HOSTILE},
        "2": {"exige": [{"spe": ["PC"], "annee": "premiere"}], "type": "PCSI", "etab": "L2"}}}
    bg = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "statut": "terminale"}
    runs = [{"cod": "1", "profile": bg, "exig": exig, "sp": sp},                                     # 0 mark
            {"cod": "1", "profile": None, "exig": exig, "sp": sp},                                   # 1 no profile
            {"cod": "1", "profile": dict(bg, serie="bt"), "exig": exig, "sp": sp},                   # 2 bac techno
            {"cod": "1", "profile": dict(bg, statut="reorientation"), "exig": exig, "sp": sp},       # 3 outside terminale
            {"cod": "1", "profile": dict(bg, spe2="PC"), "exig": exig, "sp": sp},                    # 4 the pair meets it
            {"cod": "2", "profile": bg, "exig": exig, "sp": sp},                                     # 5 première only
            {"cod": "1", "profile": bg, "exig": None, "sp": sp},                                     # 6 no data yet
            {"cod": "1", "profile": dict(bg, spe2="MATHS"), "exig": exig, "sp": sp}]                 # 7 same specialty twice
    out = node(_page_prog(c), {"runs": runs})
    if out is None:
        return True, "node absent: not run"
    bad = []
    if "ex-mark" not in out[0]["mark"] or "condition à lire" not in out[0]["mark"]:
        bad.append("no mark for a missing required group")
    for i in (1, 2, 3, 4, 5, 6, 7):
        if out[i]["mark"]:
            bad.append(f"run {i}: a mark where none is due")
    for i, o in enumerate(out):
        html = o["mark"] + o["card"] + o["type"]
        if "<img" in html or "<script" in html:
            bad.append(f"run {i}: an unescaped string")
        if re.search(r"--zone|ZONES|zone-", html):
            bad.append(f"run {i}: a zone colour")
        if re.search(r"refusée?s?\b(?! )|vous êtes refus|sera refus", html) or re.search(r"\b(?:tu|ton|ta|tes|toi)\b", re.sub(r"<[^>]+>", " ", html)):
            bad.append(f"run {i}: a verdict or tutoiement")
    card = out[0]["card"]
    if 'class="ex-mine"' not in card or card.count('class="ex-mine"') != 1 or 'class="ex-spe">physique-chimie' not in card:
        bad.append("the student's own specialty (SES) is not the only one marked as theirs")
    if "La fiche écrit comme obligatoire : Physique-chimie en terminale" not in card or "pas un refus" not in card:
        bad.append("the missing group or its caveat is not said")
    if "97" not in card or "89" not in card or "360" not in card:
        bad.append("the measure is not printed from the data")
    if "Absences éliminatoires" not in card:
        bad.append("the elimination sentence is not quoted")
    if "obligatoire : Physique-chimie" in out[4]["card"] and "Vous ne la suivez pas" in out[4]["card"]:
        bad.append("a pair that meets the group is told it lacks it")
    if "Celles qui citent une spécialité que vous n'avez pas" not in out[0]["type"] or "Lycée &lt;img" not in out[0]["type"]:
        bad.append("specialties page: the concerned types or their formations are missing")
    return not bad, f"{len(runs)} profiles; {bad[:4]}"


# ---------------------------------------------------------------- EX7

@check("EX7 plumbing: route without parameter and public cache, page and build wired, every surface, docs")
def ex7(c: Ctx):
    from suptracker import api, cache
    bad = []
    if cache.policy("/api/exigences") is None or cache.policy("/api/exigences")[0] != cache.PUBLIC:
        bad.append("cache policy")
    fn = next((r.endpoint for r in api.app.routes if getattr(r, "path", "") == "/api/exigences"), None)
    if fn is None or inspect.signature(fn).parameters:
        bad.append("/api/exigences missing or takes a parameter")
    if 'api("/api/exigences")' not in c.js or re.search(r"/api/exigences\?", c.js):
        bad.append("the page does not ask /api/exigences without a query")
    if "exigences.build(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build.py")
    if '"specialites": EX.for_formation(' not in (ROOT / "suptracker" / "api.py").read_text() or '"exigences_specialites"' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("formation API or feature list")
    surfaces = {"resultCard": "exigeMark(r.cod_aff_form)", "carteCard": "exigeMark(f.cod_aff_form)", "viewVoeux": None,
                "summaryBand": "exigeManque(d.specialites.exige, exigPair())", "viewFormation": "specialitesCard(d.specialites, d)",
                "viewSpecialites": "exigencesTypeCard(E)"}
    for f, needle in surfaces.items():
        body = top(c.js, f)
        if needle and needle not in body:
            bad.append(f"{f} does not use it")
    if "exigeMark(v.cod_aff_form)" not in c.js:
        bad.append("Mes vœux does not use it")
    for f in ("viewSearch", "viewVoeux", "viewCarte", "viewSpecialites"):
        if "exigLoad()" not in top(c.js, f):
            bad.append(f"{f} renders before the table is loaded")
    if '"exigences_specialites"' not in (ROOT / "tests" / "test_release.py").read_text():
        bad.append("release feature table")
    if "## What the fiches write about specialties" not in (REPO / "README.md").read_text(encoding="utf-8") \
            and "## What the fiches write about specialties" not in (ROOT / "README.md").read_text(encoding="utf-8"):
        bad.append("README section")
    if "exigences.py" not in (REPO / "CLAUDE.md").read_text(encoding="utf-8"):
        bad.append("CLAUDE.md rule")
    if "tests/test_exigences.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    return not bad, f"{bad[:5]}"


# ---------------------------------------------------------------- EX8

SOURCE_MUTANTS = [
    ("ex", "negations ignored", "    if NEG.search(seg):\n", "    if False:\n", "EX3"),
    ("ex", "level sentences required", "            c = \"citee\"                                   # \"un bon niveau", "            pass  # \"un bon niveau", "EX3"),
    ("ex", "conditions required", "            c = \"citee\"                                   # \"lorsque", "            pass  # \"lorsque", "EX3"),
    ("ex", "lower-case si read", "and (raw != raw.upper() or capital):", "and False:", "EX2"),
    ("ex", "formation names read", "            if nm and not re.search(", "            if False and not re.search(", "EX3"),
    ("ex", "ST2S physics read", "            if k == \"PC\" and ns[b:b + 14] == \" pour la sante\":", "            if False:", "EX3"),
    ("ex", "no alternatives", "        if groups and JOIN.fullmatch(ns[ms[i - 1][1]:a]):", "        if False:", "EX3"),
    ("ex", "advice after the name ignored", "        if near != \"citee\":", "        if False:", "EX3"),
    ("ex", "either year read as both", "        return \"l_une\" if re.search(", "        return \"les_deux\" if re.search(", "EX3"),
    ("ex", "première-only groups read", "        if g.get(\"annee\") in (\"premiere\", \"l_une\"):", "        if False:", "EX4"),
    ("ex", "maths complémentaires known", "                vals.append(True if \"MATHS\" in pair else None)", "                vals.append(\"MATHS\" in pair)", "EX4"),
    ("ex", "elimination negations kept", "    return bool(ELIM.search(ns)) and not ELIM_NEG.search(ns)", "    return bool(ELIM.search(ns))", "EX3"),
    ("ex", "measure typed", "    gold = read_gold() if gold is None else gold", "    gold = (read_gold() if gold is None else gold)[:300]", "EX1"),
    ("ex", "sentence not verbatim", "        yield {\"src\": src, \"champ\": champ, \"critere\": critere, \"importance\": importance, \"texte\": s,",
     "        yield {\"src\": src, \"champ\": champ, \"critere\": critere, \"importance\": importance, \"texte\": s.capitalize() + \" \",", "EX5"),
    ("ex", "every fiche listed", "        if r:\n            req.append(", "        if True:\n            req.append(", "EX5"),
    ("js", "première groups marked", "    if (g.annee === \"premiere\" || g.annee === \"l_une\") return false;", "", "EX4"),
    ("js", "mark for bac techno", "  if (!p || (p.serie && p.serie !== \"bg\") ||", "  if (!p ||", "EX6"),
    ("js", "sentence unescaped", "  return h + esc(p.texte.slice(at));", "  return h + p.texte.slice(at);", "EX6"),
    ("js", "every specialty marked as the student's", "(mine.includes(k) ? `<mark class=\"ex-mine\">", "(true ? `<mark class=\"ex-mine\">", "EX6"),
    ("js", "measure typed", "${fmt(m.lus_exiges)} étaient lues", "120 étaient lues", "EX6"),
    ("js", "mark on Mes voeux removed", "${autresBadge(v)}${exigeMark(v.cod_aff_form)}", "${autresBadge(v)}", "EX7"),
]


@check("EX8 mutation test: mutants of the rules and the page, each caught")
def ex8(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
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
    c = Ctx(real=real, db=db)
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
    ap.add_argument("--real", action="store_true", help="also the committed warehouse")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
