"""Red team of the lighter mention filter (owner, 2026-11-21): professional titles under the official NSF domain of their RNCP
fiches (domaines.py, core.fp_domaine), BTS / certificate options under their diploma, BPJEPS / DEJEPS mentions under their
spécialité, acronym prefixes and « - en apprentissage » out of the group name, a double licence under EACH of its two
disciplines (carte.groupes_of, the layer's « groupe2 », the page's carteGroupes). Each formation keeps its own label.

    python scripts/redteam_filtres_mentions.py [--db data/suptracker.duckdb] [--real]

  FM1 the grouping rule on a table written by hand (hostile labels included): an independent reading equals carte.groupes_of;
      labels of other types are untouched (licence, BUT, « Opticien-Lunetier », an option word inside a name).
  FM2 the NSF rule on a crafted RNCP export: one group; several groups of one sub-domain = its plurivalent code; several
      sub-domains; no fiche; an active fiche preferred over an expired one; an expired fiche alone still read; letter suffixes;
      a missing plurivalent label; domaines.build on a crafted cartographie.
  FM3 --real: every « FP - … » mention's domain re-derived from the committed RNCP export by an own reader; the warehouse table
      equals it; every professional title of the layer is listed under its domain; far fewer groups than titles.
  FM4 --real: the filter and the layer agree: each facet group counts exactly the layer rows listed under it (a double licence in
      both its disciplines), each variant is a label of a row of that group; no group keeps a closed acronym prefix; no two BTS
      groups share a diploma head.
  FM5 the page (Node): carteGroupes and carteKeep keep a double licence when either discipline is ticked, and the facet counts
      count it in both.
  FM6 docs and wiring: README, CLAUDE.md, durations.json, the test file, the build step, the source register.
  FM7 mutation test of FM1-FM5 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
BTS, CERT, SPORT, DEUST, DU = ("BTS - BTSA - BTSM", "Certificats de spécialisation et FCIL", "Formations aux métiers du sport", "DEUST",
                               "Diplômes d'université ou d'établissement")
FP, DL = "Formation professionnelle", "Double licence"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str, extra: dict | None = None):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_rt")
    m.__package__ = "suptracker"
    m.__file__ = str(ROOT / "suptracker" / f"{name}.py")
    m.__dict__.update(extra or {})
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text() for k in ("carte", "domaines")}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def dom(self):
        return load("domaines", self.src["domaines"])

    def carte(self):
        CA = load("carte", self.src["carte"])
        CA.DOM = self.dom()
        return CA


# ------------------------------------------------------------------ FM1 the grouping rule
CASES = [
    (BTS, "Métiers de l'audio-visuel opt : métiers du son", ["Métiers de l'audio-visuel"]),
    (BTS, "Métiers de l'audio-visuel opt : techn. d'ingeniérie et exploit. équipements", ["Métiers de l'audio-visuel"]),
    (BTS, "Maintenance des systèmes - option D: maintenance des ascenseurs et élévateurs", ["Maintenance des systèmes"]),
    (BTS, "Cybersécurité, Informatique et réseaux, ELectronique - Option A : Informatique et réseaux",
     ["Cybersécurité, Informatique et réseaux, ELectronique"]),
    (BTS, "Analyse, conduite et stratégie de l'entreprise agricole, option Territoires métropolitains",
     ["Analyse, conduite et stratégie de l'entreprise agricole"]),
    (BTS, "Maintenance des véhicules option voitures particulières", ["Maintenance des véhicules"]),
    (BTS, "Technico-commercial - Spécialité vins, bières et spiritueux", ["Technico-commercial"]),
    (BTS, "Opticien-Lunetier", ["Opticien-Lunetier"]),
    (BTS, "Management en hôtellerie restauration", ["Management en hôtellerie restauration"]),
    (BTS, "BTSA - Aménagements paysagers", ["Aménagements paysagers"]),
    (BTS, "Conception des produits industriels", ["Conception des produits industriels"]),
    (CERT, "Aéronautique option avions à moteurs à turbines", ["Aéronautique"]),
    (CERT, "Techn. en énergies renouvelables opt. b énergie thermique", ["Techn. en énergies renouvelables"]),
    (CERT, "CSA - Conduites de productions maraîchères - en apprentissage", ["Conduites de productions maraîchères"]),
    (CERT, "CSA - Arboriste-grimpeur", ["Arboriste-grimpeur"]),
    (CERT, "CS - Agent de contrôle non destructif", ["Agent de contrôle non destructif"]),
    (CERT, "Encadrement secteur sportif opt. activités de la forme-cours collectifs", ["Encadrement secteur sportif"]),
    (SPORT, "BPJEPS - Spécialité Educateur sportif - Mention Voile", ["Educateur sportif"]),
    (SPORT, "Spécialité Educateur sportif - Mention Activités physiques pour tous", ["Educateur sportif"]),
    (SPORT, "DEJEPS - Spécialité Animation socio-éducative ou culturelle - Mention coordination de projets",
     ["Animation socio-éducative ou culturelle"]),
    (SPORT, "CS - Encadrement secteur sportif option multi-activités physiques ou sportives pour tous", ["Encadrement secteur sportif"]),
    (DEUST, "DEUST - Préparateur/Technicien en pharmacie", ["Préparateur/Technicien en pharmacie"]),
    (DU, "DSP - DSP - Assistant designer web", ["Assistant designer web"]),
    (DL, "Droit / Histoire", ["Droit", "Histoire"]),
    (DL, "Histoire / Droit", ["Droit", "Histoire"]),
    (DL, "Anglais / Allemand", ["Allemand", "Anglais"]),
    (DL, "Droit / DROIT", ["Droit"]),
    (DL, "Droit", ["Droit"]),
    (DL, f"{HOSTILE} / Droit", None),
    ("Licence", "Droit parcours option européenne", ["Droit parcours option européenne"]),
    ("BUT", "Carrières sociales Parcours animation sociale et socioculturelle", ["Carrières sociales"]),
    ("Licence", "DEUST - X", ["DEUST - X"]),
    ("Formations d'art et de design", "DSP - Design graphique", ["DSP - Design graphique"]),
    (FP, "FP - Titre professionnel - Gestionnaire de Paie (Bac +2)", ["Ressources humaines"]),
    (FP, "FP - Inconnu (Bac +2)", ["FP - Inconnu (Bac +2)"]),
    (FP, "  FP -  Titre  professionnel - Gestionnaire de Paie (Bac +2) ", ["Ressources humaines"]),
]
DOMAINS = {"FP - Titre professionnel - Gestionnaire de Paie (Bac +2)": "Ressources humaines"}
PREFIXES = ("BTS", "BTSA", "DEUST", "CS", "CSA", "DSP", "BPJEPS", "DEJEPS")
OPTION_WORD = re.compile(r"(?i)(?:, ?| - ?| )(?:option\b|opt ?[.:])| - Spécialité ")


def rt_groupes(CA, d, m, dom):
    """Independent: the group(s) of a label, written from the rules (not from carte's regexes)."""
    m = " ".join((m or "").split())
    if d == DL:
        head = m.split(" - ")[0] if "/" in m.split(" - ")[0] else m
        parts = [p for p in re.split(r"\s*/\s*|\s+-\s+", head) if p.strip()][:2]
        if len(parts) < 2:
            return [m or "Sans précision"]
        return sorted({CA._dl_discipline(p) for p in parts}, key=CA.sort_key)
    if d == FP:
        return [dom.get(m, m)]
    if d not in (BTS, CERT, SPORT, DEUST, DU):
        return [CA.groupe_of(d, m)]       # other types: the earlier rules, unchanged
    g = m
    while True:                            # every leading closed acronym, one by one
        head, sep, rest = g.partition(" - ")
        if sep and head in PREFIXES:
            g = rest
        else:
            break
    if g.lower().endswith(" - en apprentissage"):
        g = g[: -len(" - en apprentissage")]
    if d in (BTS, CERT, SPORT):
        hit = OPTION_WORD.search(g)
        g = g[: hit.start()] if hit else g
        if d == SPORT and g.startswith("Spécialité ") and " - Mention " in g:
            g = g[len("Spécialité "): g.index(" - Mention ")]
    return [g.strip()]


@check("FM1 the grouping rule on a table written by hand: an independent reading equals carte.groupes_of; other types untouched")
def fm1(c: Ctx):
    CA = c.carte()
    dom = {" ".join(k.split()): v for k, v in DOMAINS.items()}
    bad = []
    for d, m, want in CASES:
        got = CA.groupes_of(d, m, dom)
        ind = rt_groupes(CA, d, m, dom)
        if got != ind or (want is not None and got != want):
            bad.append((d, m, got, ind, want))
        if CA.groupe_of(d, m, dom) != got[0]:
            bad.append((d, m, "groupe_of is not the first group"))
    return not bad, f"{len(CASES)} labels; problems {bad[:3]}"


# ------------------------------------------------------------------ FM2 the NSF rule
FICHES = [  # numero, intitule, actif, [nsf codes]
    ("R1", "Gestionnaire de Paie", "ACTIVE", ["315t"]),
    ("R2", "Responsable de chantier", "ACTIVE", ["230p", "232p", "233"]),
    ("R3", "Chargé de marketing et communication", "ACTIVE", ["312", "320"]),
    ("R4", "Titre sans NSF", "ACTIVE", []),
    ("R5", "Assistant de direction", "INACTIVE", ["324"]),
    ("R6", "Assistant de direction", "ACTIVE", ["324t"]),
    ("R7", "Ancien titre", "INACTIVE", ["311p"]),
    ("R8", "Domaine orphelin", "ACTIVE", ["251", "252r"]),        # no « 250 » label printed anywhere
    ("R9", "Gestionnaire de Paie", "INACTIVE", ["314"]),           # an expired fiche of an active title: ignored
]
LABELS = {"315": "Ressources humaines, gestion du personnel", "230": "Spécialités pluritechnologiques génie civil, construction, bois",
          "232": "Bâtiment : construction et couverture", "233": "Bâtiment : finitions", "312": "Commerce, vente",
          "320": "Spécialites plurivalentes de la communication", "324": "Secrétariat, bureautique", "311": "Transports, manutention",
          "251": "Mécanique générale", "252": "Moteurs et mécanique auto", "314": "Comptabilite, gestion",
          "310": "Spécialités plurivalentes des échanges et de la gestion"}   # 312 + 320 must NOT read as 310
EXPECT = {"Gestionnaire de Paie": ("315", "Ressources humaines, gestion du personnel", "nsf"),
          "Responsable de chantier": ("230", "Spécialités pluritechnologiques génie civil, construction, bois", "nsf_plurivalent"),
          "Chargé de marketing et communication": (None, None, "plusieurs_domaines"),
          "Titre sans NSF": (None, None, "sans_fiche"), "Assistant de direction": ("324", "Secrétariat, bureautique", "nsf"),
          "Ancien titre": ("311", "Transports, manutention", "nsf"), "Domaine orphelin": (None, None, "plusieurs_domaines"),
          "Absent du répertoire": (None, None, "sans_fiche")}


def crafted_zip(path: Path):
    def text(header, rows):
        b = io.StringIO()
        w = csv.writer(b, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)
        return b.getvalue()
    std = text(["Id_Fiche", "Numero_Fiche", "Intitule", "Abrege_Libelle", "Actif"], [[i, n, t, "", a] for i, (n, t, a, _) in enumerate(FICHES)])
    nsf = [["Numero_Fiche", "Nsf_Code", "Nsf_Intitule"]]
    for n, _, _, codes in FICHES:
        for code in codes:
            nsf.append([n, code, f"{code} : " + (LABELS.get(code) or LABELS.get(code[:3], "") + " (détail)")])
    for code, lab in LABELS.items():       # the plain 3-digit rows the export prints for the groups
        nsf.append(["RX" + code, code, f"{code} : {lab}"])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("export_fiches_CSV_Standard_2026.csv", std)
        z.writestr("export_fiches_CSV_Nsf_2026.csv", text(nsf[0], nsf[1:]))


@check("FM2 NSF rule on a crafted RNCP export: one group, one sub-domain's plurivalent code, several, none, active first")
def fm2(c: Ctx):
    DM = c.dom()
    bad = []
    with tempfile.TemporaryDirectory() as td:
        z = Path(td) / "export-fiches-csv.zip"
        crafted_zip(z)
        fiches, nsf, labels = DM.read(z)
        by_key: dict = {}
        for f, (k, _) in fiches.items():
            by_key.setdefault(k, []).append(f)
        for title, want in EXPECT.items():
            got = DM.domain(DM.RF.cert_key(title), by_key, fiches, nsf, labels)
            if got != want:
                bad.append((title, got, want))
        con = duckdb.connect()
        con.execute("CREATE SCHEMA core")
        con.execute("CREATE TABLE core.cartographie (carto_session INTEGER, mention_lib VARCHAR)")
        con.executemany("INSERT INTO core.cartographie VALUES (?, ?)", [
            (2026, "FP - Titre professionnel - Gestionnaire de Paie (Bac +2)"), (2026, "FP - Responsable de chantier (Bac +2)"),
            (2026, "FP - Chargé de marketing et communication (Bac +3)"), (2026, "FP - Absent du répertoire (Bac +3)"),
            (2026, "BTS - Comptabilité et gestion"), (2025, "FP - Ancien titre (Bac +2)")])
        DM.build(con, z)
        rows = {m: (n, d, r) for m, n, d, r in con.execute("SELECT * FROM core.fp_domaine").fetchall()}
        want_rows = {"FP - Titre professionnel - Gestionnaire de Paie (Bac +2)": ("315", "Ressources humaines, gestion du personnel", "nsf"),
                     "FP - Responsable de chantier (Bac +2)": ("230", EXPECT["Responsable de chantier"][1], "nsf_plurivalent"),
                     "FP - Chargé de marketing et communication (Bac +3)": (None, DM.SEVERAL, "plusieurs_domaines"),
                     "FP - Absent du répertoire (Bac +3)": (None, DM.NONE, "sans_fiche")}
        if rows != want_rows:
            bad.append(("build", rows))
        if DM.groups(con) != {k: v[1] for k, v in want_rows.items()}:
            bad.append(("groups", DM.groups(con)))
        con.execute("INSERT INTO core.fp_domaine VALUES ('FP -  Titre  à espaces (Bac +2) ', NULL, 'Domaine X', 'nsf')")
        if DM.groups(con).get("FP - Titre à espaces (Bac +2)") != "Domaine X":
            bad.append(("spaces not normalised in the lookup",))
    return not bad, f"{len(EXPECT)} titles; problems {bad[:3]}"


# ------------------------------------------------------------------ FM3 / FM4 real data
def rt_domains(zpath: Path, mentions: list, RF) -> dict:
    """Independent: own CSV reading of the export (encoding sniffed), own grouping of the NSF codes."""
    with zipfile.ZipFile(zpath) as z:
        def rows(part):
            name = next(n for n in z.namelist() if part in n)
            raw = z.read(name)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252")
            return list(csv.DictReader(io.StringIO(text), delimiter=";"))
        std = rows("_Standard_")
        nsf_rows = rows("_Nsf_")
    titles: dict = {}
    for r in std:
        titles.setdefault(RF.cert_key(r["Intitule"]), []).append((r["Numero_Fiche"], r["Actif"] == "ACTIVE"))
    codes: dict = {}
    lab = {}
    for r in nsf_rows:
        codes.setdefault(r["Numero_Fiche"], []).append(r["Nsf_Code"].strip())
        if re.fullmatch(r"\d{3}", r["Nsf_Code"].strip()):
            lab[r["Nsf_Code"].strip()] = r["Nsf_Intitule"].split(":", 1)[-1].strip()
    out = {}
    for m in mentions:
        fs = titles.get(RF.cert_title(m) or "", [])
        act = [f for f, a in fs if a] or [f for f, _ in fs]
        gs = sorted({x[:3] for f in act for x in codes.get(f, []) if x[:3].isdigit()})
        if len(gs) == 1 and gs[0] in lab:
            out[m] = (gs[0], lab[gs[0]])
        elif len(gs) > 1 and len({g[:2] for g in gs}) == 1 and gs[0][:2] + "0" in lab:
            out[m] = (gs[0][:2] + "0", lab[gs[0][:2] + "0"])
        else:
            out[m] = (None, None)
    return out


@check("FM3 real: every « FP - » mention's NSF domain re-derived by an own reader; the table and the layer agree; fewer groups")
def fm3(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    DM = c.dom()
    CA = c.carte()
    con = duckdb.connect(str(c.db), read_only=True)
    zp = DM.DIR / DM.RF.RNCP_ZIP
    if not zp.exists():
        return True, "no RNCP export in this checkout"
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'fp_domaine'").fetchone()[0]:
        return False, "core.fp_domaine missing: the build does not run domaines.build"
    table = {m: (n, d, r) for m, n, d, r in con.execute("SELECT * FROM core.fp_domaine").fetchall()}
    want = rt_domains(zp, sorted(table), DM.RF)
    bad = [(m, table[m], w) for m, w in want.items() if (table[m][0], table[m][1] if table[m][0] else None) != w]
    latest = {m for (m,) in con.execute("""SELECT DISTINCT mention_lib FROM core.cartographie WHERE mention_lib IS NOT NULL
                                           AND carto_session = (SELECT max(carto_session) FROM core.cartographie)""").fetchall()}
    if {m for m in latest if DM.RF.cert_title(m)} != set(table):
        bad.append(("table does not cover the FP mentions", len(table)))
    dom = DM.groups(con)
    rows = (CA.formations(con, FP) or {"formations": []})["formations"]
    for f in rows:
        k = " ".join((f["mention"] or "").split())
        if k in dom and f["groupe"] != dom[k]:
            bad.append((f["cod_aff_form"], "layer group", f["groupe"], dom[k]))
    n_titles = len({f["mention"] for f in rows})
    n_groups = len({f["groupe"] for f in rows})
    read = sum(1 for v in want.values() if v[0])
    if n_titles >= 50 and n_groups * 2 > n_titles:
        bad.append(("too many groups", n_groups, n_titles))
    return not bad, f"{len(table)} titles, {read} with a domain; {n_titles} titles listed in {n_groups} groups; problems {bad[:3]}"


@check("FM4 real: facet groups count exactly the layer rows listed under them (double licence in both); no acronym left in a group")
def fm4(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    CA = c.carte()
    con = duckdb.connect(str(c.db), read_only=True)
    fac = CA.facets(con)
    bad = []
    n_dl2 = 0
    for d in fac["diplomes"]:
        rows = (CA.formations(con, d["label"]) or {"formations": []})["formations"]
        listed: dict = {}
        for f in rows:
            gs = [f["groupe"]] + ([f["groupe2"]] if f.get("groupe2") else [])
            n_dl2 += bool(f.get("groupe2"))
            if d["label"] != DL and f.get("groupe2"):
                bad.append((f["cod_aff_form"], "second group outside a double licence"))
            if len(set(gs)) != len(gs):
                bad.append((f["cod_aff_form"], "same group twice"))
            for g in gs:
                listed.setdefault(g, []).append(f["mention"])
        for g in d["mentions"]:
            if g["n"] != len(listed.get(g["label"], [])) or not set(g["variantes"]) <= set(listed.get(g["label"], [])):
                bad.append((d["label"], g["label"], g["n"], len(listed.get(g["label"], []))))
                break
        if set(listed) != {g["label"] for g in d["mentions"]}:
            bad.append((d["label"], "groups differ", sorted(set(listed) ^ {g["label"] for g in d["mentions"]})[:3]))
        if d["label"] in CA.PREFIX_TYPES:
            left = [g["label"] for g in d["mentions"] if re.match(r"(?:BTSA?|DEUST|CSA?|DSP|BPJEPS|DEJEPS) - ", g["label"])]
            if left:
                bad.append((d["label"], "prefix left", left[:3]))
        if d["label"] in (BTS, CERT, SPORT):
            opt = [g["label"] for g in d["mentions"] if OPTION_WORD.search(g["label"])]
            if opt:
                bad.append((d["label"], "an option left in a group name", opt[:3]))
    if n_dl2 < 50:
        bad.append(("too few double licences under two disciplines", n_dl2))
    return not bad, f"{len(fac['diplomes'])} diplomas; {n_dl2} double licences in two groups; problems {bad[:3]}"


# ------------------------------------------------------------------ FM5 the page
def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        return js[m.start(): m.start() + e.end()]
    return js[m.start(): js.find("\n}", m.start()) + 2]


@check("FM5 page (Node): a double licence kept when either discipline is ticked, and counted in both")
def fm5(c: Ctx):
    js = c.js
    bad = []
    try:
        lib = top(js, "carteGroupes") + "\n" + top(js, "carteKeep")
    except KeyError as e:
        return False, f"missing {e}"
    count = re.search(r"pool\.forEach\(\(f\) => \{ nDip\.set.*?\}\);\n", js)
    if not count:
        return False, "facet count line not found"
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    prog = lib + """
const nDip = new Map(), nMen = new Map();
const pool = [{ diplome: "Double licence", groupe: "Droit", groupe2: "Histoire" }, { diplome: "Double licence", groupe: "Droit" },
              { diplome: "BTS", groupe: "Maintenance des systèmes" }];
""" + count.group(0).strip() + """
const sel = (m) => ({ d: ["Double licence"], m: { "Double licence": m } });
process.stdout.write(JSON.stringify({ h: carteKeep(pool[0], sel(["Histoire"])), d: carteKeep(pool[0], sel(["Droit"])),
  x: carteKeep(pool[0], sel(["Lettres"])), one: carteKeep(pool[1], sel(["Histoire"])), all: carteKeep(pool[0], sel([])),
  counts: Object.fromEntries(nMen) }));"""
    r = subprocess.run([exe, "-e", prog], capture_output=True, text=True, timeout=60)
    if r.returncode:
        return False, r.stderr[-400:]
    o = json.loads(r.stdout)
    want = {"h": True, "d": True, "x": False, "one": False, "all": True}
    bad += [(k, o[k]) for k, v in want.items() if o[k] != v]
    if o["counts"] != {"Double licence\u0000Droit": 2, "Double licence\u0000Histoire": 1, "BTS\u0000Maintenance des systèmes": 1}:
        bad.append(("counts", o["counts"]))
    return not bad, f"problems {bad[:3]}"


# ------------------------------------------------------------------ FM6 docs and wiring
@check("FM6 docs and wiring: README, CLAUDE.md, durations.json, the test file, the build step, the source register")
def fm6(c: Ctx):
    bad = []
    readme = (ROOT / "README.md").read_text()
    if "Filtre des mentions allégé" not in readme or "redteam_filtres_mentions.py" not in readme:
        bad.append("README")
    cl = (ROOT.parent / "CLAUDE.md").read_text()
    if "carte.groupes_of" not in cl or "redteam_filtres_mentions.py" not in cl:
        bad.append("CLAUDE.md")
    if "tests/test_filtres_mentions.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    if not (ROOT / "tests" / "test_filtres_mentions.py").exists():
        bad.append("test file")
    if "domaines.build(con)" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build step")
    from suptracker import sources
    if "mention_filter" not in next(s for s in sources.SOURCES if s["key"] == "rncp_france_competences")["feeds"]:
        bad.append("source register")
    return not bad, f"problems {bad}"


MUTANTS = [
    ("carte", "options not cut", '        g = OPTION_CUT.split(g, 1)[0].strip() or g\n', "", "FM1"),
    ("carte", "option word anywhere", 'OPTION_CUT = re.compile(r"(?:,\\s*|\\s+-\\s*|\\s+)(?:option\\b|opt\\s*[.:])|\\s+-\\s+Spécialité\\s", re.I)',
     'OPTION_CUT = re.compile(r"opt", re.I)', "FM1"),
    ("carte", "prefix kept", '        g = GROUP_SUFFIX.sub("", GROUP_PREFIX.sub("", g)).strip() or m', '        g = GROUP_SUFFIX.sub("", g).strip() or m', "FM1"),
    ("carte", "one prefix only", 'GROUP_PREFIX = re.compile(r"^(?:(?:BTSA?|DEUST|CSA?|DSP|BPJEPS|DEJEPS)\\s+-\\s+)+")',
     'GROUP_PREFIX = re.compile(r"^(?:(?:BTSA?|DEUST|CSA?|DSP|BPJEPS|DEJEPS)\\s+-\\s+)")', "FM1"),
    ("carte", "apprenticeship suffix kept", '        g = GROUP_SUFFIX.sub("", GROUP_PREFIX.sub("", g)).strip() or m', '        g = GROUP_PREFIX.sub("", g).strip() or m', "FM1"),
    ("carte", "prefix stripped on every type", '    if diplome in PREFIX_TYPES:\n', '    if True:\n', "FM1"),
    ("carte", "BPJEPS mention kept", "        g = sp.group(1).strip() if sp else g\n", "", "FM1"),
    ("carte", "double licence under one discipline", "        return sorted({_dl_discipline(p) for p in parts}, key=sort_key)",
     "        return sorted({_dl_discipline(p) for p in parts}, key=sort_key)[:1]", "FM1"),
    ("carte", "domain map ignored", "    if diplome == FP_TYPE and domaines and m in domaines:", "    if False:", "FM1"),
    ("domaines", "active fiche not preferred", "    use = [f for f in fs if fiches[f][1]] or fs", "    use = fs", "FM2"),
    ("domaines", "expired-only title dropped", "    use = [f for f in fs if fiches[f][1]] or fs", "    use = [f for f in fs if fiches[f][1]]", "FM2"),
    ("domaines", "letter suffix kept", '    groups = {c[:3] for f in use for c in nsf.get(f, ()) if re.match(r"\\d{3}", c)}',
     '    groups = {c for f in use for c in nsf.get(f, ()) if re.match(r"\\d{3}", c)}', "FM2"),
    ("domaines", "several sub-domains read as one", "    if len(subs) == 1 and labels.get(next(iter(subs)) + \"0\"):",
     "    if labels.get(sorted(subs)[0] + \"0\"):", "FM2"),
    ("domaines", "first group of several taken", "    if len(groups) == 1:\n", "    if groups:\n        groups = {sorted(groups)[0]}\n", "FM2"),
    ("domaines", "an older cartographie read", "WHERE carto_session = (SELECT max(carto_session) FROM core.cartographie) AND mention_lib IS NOT NULL",
     "WHERE mention_lib IS NOT NULL", "FM2"),
    ("domaines", "spaces not normalised", '    return {" ".join(m.split()): d for m, d in con.execute("SELECT mention, domaine FROM core.fp_domaine").fetchall()}',
     '    return {m: d for m, d in con.execute("SELECT mention, domaine FROM core.fp_domaine").fetchall()}', "FM2"),
    ("carte", "second discipline not stored", '            x["groupe2"] = gs[1]', '            pass', "FM4"),
    ("carte", "facets count one discipline", "        for gl in groupes_of(d, m, dom):", "        for gl in groupes_of(d, m, dom)[:1]:", "FM4"),
    ("js", "second discipline not kept", "carteGroupes(f).some((g) => sel.m[f.diplome].includes(g))", "sel.m[f.diplome].includes(f.groupe)", "FM5"),
    ("js", "second discipline not counted", "const carteGroupes = (f) => (f.groupe2 ? [f.groupe, f.groupe2] : [f.groupe]);",
     "const carteGroupes = (f) => [f.groupe];", "FM5"),
]


@check("FM7 mutation test: every seeded grouping, domain, layer and page bug is caught")
def fm7(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:6] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught, n = [], 0, 0
    for kind, name, old, new, target in MUTANTS:
        if target in ("FM3", "FM4") and not c.real:
            continue
        n += 1
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = copy.copy(c)
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
    return not missed, f"{caught}/{n} caught; missed {missed}"


def run(db: Path, real: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
