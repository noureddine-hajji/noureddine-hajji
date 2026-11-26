"""Red team, the route from the bac to each job (owner, 2026-11-14; suptracker/parcours.py, the job page's parcoursCard).

  PA1 coverage: built on a copy of the warehouse with the (possibly mutated) module; at least 80 % of the jobs that need higher
      studies have a route; the stored measure equals a recount of the stored statuses; every status follows the job's level.
  PA2 independent chains: the Onisep XML re-read by its own parser; every direct or graph route is a real chain of Onisep
      continuations (entry diploma -> each step -> a diploma the job requires or names), its entry diploma is tied to formations
      of the latest Parcoursup campaign, and no step is a Parcoursup diploma itself (the branch ends there).
  PA3 family rules: every rule route reaches only the Parcoursup filières its rule names, from a diploma (or the job name) an
      independent keyword table puts in that family; the health rule's diplomas say "PASS" or "LAS" in Onisep's own access text.
  PA4 places and the 80 % rule: every entry's count and places are re-summed by SQL from its own Parcoursup group (no double
      count when two rules reach it); on every job the routes are sorted by places and the open ones are the shortest prefix
      reaching 80 % of them.
  PA5 ground truth: pédiatre -> PASS and LAS (both open); psychiatre -> PASS through a nearby job; expert-comptable -> DCG by its
      name; vétérinaire -> BCPST; an engineering job -> a scientific CPGE and the engineering schools; a CAP job needs no higher studies.
  PA6 page (node): parcoursCard escapes every stored string, says "pas d'études après le bac" with the Onisep links for a job that
      needs none, never a chance, vouvoiement, the 80 % sentence only with routes, the measure from the data, external links noopener.
  PA7 plumbing: build.py, the job API, source register, README, CLAUDE.md, durations, release feature.
  PA8 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import time
import types
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str, package: str):
    m = types.ModuleType(name)
    m.__file__, m.__package__ = str(path), package
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


def plainfold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {"pa": (ROOT / "suptracker" / "parcours.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self._built = {}

    def built(self):
        """(module, connection) over the warehouse (read only), built with the current (possibly mutated) module; cached per source."""
        key = self.src["pa"]
        if key not in self._built:
            import duckdb
            if self.db is None:
                return None, None
            # an in-memory database reading the warehouse's tables through views: no copy left on disk (each mutant builds again)
            pa = load(ROOT / "suptracker" / "parcours.py", "suptracker.parcours_rt", key, "suptracker")
            con = duckdb.connect()
            con.execute(f"ATTACH '{self.db}' AS w (READ_ONLY)")
            con.execute("CREATE SCHEMA core")
            for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'w' AND schema_name = 'core' AND "
                                    "table_name IN ('formation_year', 'onisep_metier', 'onisep_formation_metier', 'onisep_link', "
                                    "'onisep_formation')").fetchall():
                con.execute(f"CREATE VIEW core.{t} AS SELECT * FROM w.core.{t}")
            pa.build(con)
            self._built = {key: (pa, con)}
        return self._built[key]


# ---------------------------------------------------------------- independent reading of the XML

_XML = {}


def xml_sources():
    if _XML:
        return _XML
    for p in sorted((ROOT / "data" / "sources").glob("ONISEP-*.zip")):
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.endswith(".xml")]
            if not names:
                continue
            root = ET.fromstring(z.read(names[0]))
        if root.tag == "formations":
            _XML["forms"] = {f.findtext("identifiant"): {
                "lib": f.findtext("libelle_complet") or "", "acces": f.findtext("descriptif_acces") or "",
                "type": f.findtext("type_Formation/type_formation_libelle") or "",
                "suite": {x.get("id") for x in f.iter("formation_poursuite_Etudes")}} for f in root}
        elif root.tag == "metiers":
            _XML["jobs"] = {m.findtext("identifiant"): {"nom": m.findtext("nom_metier") or "",
                            "req": [x.findtext("id") for x in m.iter("formation_min_requise")]} for m in root}
    return _XML


def rows(con):
    return {mid: (st, json.loads(d)) for mid, st, d in con.execute("SELECT met_id, statut, data FROM core.parcours_metier").fetchall()}


# ---------------------------------------------------------------- PA1

@check("PA1 coverage >= 80 % of the jobs that need higher studies; stored measure = recount; statuses follow the level")
def pa1(c: Ctx):
    pa, con = c.built()
    if con is None:
        return True, "no warehouse: not run"
    bad = []
    R = rows(con)
    rank = dict(con.execute("SELECT met_id, niveau_rang FROM core.onisep_metier").fetchall())
    need = [m for m, (st, _d) in R.items() if st != "sans_postbac"]
    cov = sum(1 for m in need if R[m][0] == "postbac") / max(1, len(need))
    m = con.execute("SELECT a_besoin, couverts, couverture FROM core.parcours_mesure").fetchone()
    if m is None or (m[0], m[1]) != (len(need), sum(1 for x in need if R[x][0] == "postbac")) or abs((m[2] or 0) - round(cov, 4)) > 1e-9:
        bad.append(f"stored measure {m} != recount {len(need)}, {cov:.4f}")
    if cov < 0.80:
        bad.append(f"coverage {cov:.3f} < 0.80")
    for mid, (st, d) in R.items():
        r = rank.get(mid)
        if r is not None and r <= 0 and st != "sans_postbac":
            bad.append(f"{mid}: level {r} but {st}")
        if r is not None and r >= 1 and st == "sans_postbac":
            bad.append(f"{mid}: level {r} read as needing no higher studies")
        if (st == "postbac") != bool(d["routes"]) and st != "sans_postbac":
            bad.append(f"{mid}: {st} with {len(d['routes'])} routes")
    if len(R) != len(rank):
        bad.append(f"{len(R)} jobs stored for {len(rank)}")
    return not bad, f"coverage {cov:.3f} of {len(need)} jobs; {bad[:4]}"


# ---------------------------------------------------------------- PA2

@check("PA2 independent chains: every direct/graph route is a real Onisep continuation chain from a Parcoursup diploma")
def pa2(c: Ctx):
    pa, con = c.built()
    if con is None:
        return True, "no warehouse: not run"
    X = xml_sources()
    F, J = X["forms"], X["jobs"]
    last = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    linked = {f for (f,) in con.execute("""SELECT DISTINCT l.for_id FROM core.onisep_link l JOIN core.formation_year y
        ON y.cod_aff_form = l.cod_aff_form AND y.session = l.session WHERE l.session = ?""", [last]).fetchall()}
    names = {}
    for fid, mid in con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall():
        names.setdefault(mid, set()).add(fid)
    bad, n = [], 0
    for mid, (_st, d) in rows(con).items():
        targets = {t["id"] for t in d["cibles"]}
        ok_targets = set(J.get(mid, {}).get("req") or []) | names.get(mid, set())
        if targets - ok_targets:
            bad.append(f"{mid}: targets {sorted(targets - ok_targets)[:2]} neither required nor named")
        for r in d["routes"]:
            if r["comment"] not in ("direct", "graphe"):
                continue
            n += 1
            entry = r["entree"].split(":", 1)[1]
            chain = [entry] + [e["id"] for e in r["etapes"]]
            if entry not in linked:
                bad.append(f"{mid}: entry {entry} has no Parcoursup formation")
            if chain[-1] not in targets:
                bad.append(f"{mid}: chain ends on {chain[-1]}, not a target")
            for a, b in zip(chain, chain[1:]):
                if b not in F.get(a, {}).get("suite", set()):
                    bad.append(f"{mid}: {a} does not continue to {b}")
            if any(s in linked for s in chain[1:]):
                bad.append(f"{mid}: a step after the entry is itself a Parcoursup diploma")
            if r["comment"] == "direct" and chain != [entry]:
                bad.append(f"{mid}: a direct route with steps")
    return not bad, f"{n} chains checked; {bad[:4]}"


# ---------------------------------------------------------------- PA3

FAMILY = {  # independent keyword table: rule -> (words in the diploma or job name, Parcoursup filières it may reach)
    "sante_mmopk": (r"medecine|pharmacie|dentaire|sage femme|maieutique", {"PASS", "Licence_Las"}),
    "kine": (r"kinesither", {"PASS", "Licence_Las", "Licence"}),
    "para_ergo": (r"ergoth", {"Autre formation"}), "para_psychomot": (r"psychomot", {"Autre formation"}),
    "para_podo": (r"podolog", {"Autre formation"}), "para_radio": (r"radiolog|imagerie", {"Autre formation"}),
    "para_ortho": (r"orthophon", {"Autre formation"}), "para_orthopt": (r"orthopt", {"Autre formation"}),
    "para_audio": (r"audioprot", {"Autre formation"}),
    "veterinaire": (r"veterinaire", {"Autre formation", "CPGE"}),
    "ingenieur": (r"ingenieur|ingenierie", {"Ecole d'Ingénieur", "CPGE"}),
    "commerce": (r"commerce", {"Ecole de Commerce", "CPGE"}),
    "architecture": (r"architect", {"Autre formation"}),
    "iep": (r"\biep\b|politique", {"Autre formation"}),
    "dnmade": (r"metiers d art et du design|dn made", {"Autre formation"}),
    "art": (r"\bart\b|arts|musique|danse|cinema|design|ecole superieure|professionnel", {"Autre formation"}),
    "comptabilite": (r"compta|dscg|dcg", {"Autre formation"}),
    "droit": (r"avocat|magistrat|notari|commissaire de justice|huissier|greffier", {"Licence"}),
}


@check("PA3 family rules: only their own filières, from a diploma (or job name) of their family; health texts say PASS/LAS")
def pa3(c: Ctx):
    pa, con = c.built()
    if con is None:
        return True, "no warehouse: not run"
    X = xml_sources()
    F, J = X["forms"], X["jobs"]
    fili = dict(con.execute("SELECT entree, fili FROM core.parcours_entree").fetchall())
    bad, n, sante, sante_txt = [], 0, 0, 0
    for mid, (_st, d) in rows(con).items():
        for r in d["routes"]:
            if r["comment"] not in ("regle", "nom"):
                continue
            n += 1
            rule = r["regle"] or ""
            first = r["etapes"][0]["id"] if r["etapes"] else None       # the diploma's label and its type (rules read either)
            src = J.get(mid, {}).get("nom", "") if r["comment"] == "nom" else \
                (r["etapes"][0]["libelle"] + " " + F.get(first, {}).get("type", "") if r["etapes"] else "")
            if rule.startswith("master:"):
                lic = rule.split(":", 1)[1]
                mention = re.sub(r"^master (?:mention )?", "", plainfold(r["etapes"][0]["libelle"] if r["etapes"] else ""))
                if fili.get(r["entree"]) != "Licence" or not (plainfold(lic) == mention or f" {plainfold(lic)} " in f" {mention} "):
                    bad.append(f"{mid}: master rule {rule} from {src[:40]!r}")
                continue
            if rule not in FAMILY:
                bad.append(f"{mid}: unknown rule {rule}")
                continue
            words, filis = FAMILY[rule]
            if not re.search(words, plainfold(src)):
                bad.append(f"{mid}: {rule} from {src[:50]!r}")
            if fili.get(r["entree"]) not in filis:
                bad.append(f"{mid}: {rule} reaches {fili.get(r['entree'])}")
            if rule.startswith("para_") and not re.search(words, plainfold(r["entree"].split(":", 2)[-1]).replace("dts ", "")):
                bad.append(f"{mid}: {rule} reaches another profession's programme {r['entree']}")   # Codex
            if rule == "sante_mmopk" and r["etapes"]:
                sante += 1
                sante_txt += bool(re.search(r"PASS|L\.?AS", F.get(r["etapes"][0]["id"], {}).get("acces", "")))
    if sante and sante_txt / sante < 0.5:
        bad.append(f"the health rule's diplomas rarely say PASS/LAS ({sante_txt}/{sante})")
    return not bad, f"{n} rule routes; health texts naming PASS/LAS {sante_txt}/{sante}; {bad[:4]}"


# ---------------------------------------------------------------- PA4

@check("PA4 places and the 80 % rule: entries re-summed by SQL; routes sorted by places; open = shortest prefix reaching 80 %")
def pa4(c: Ctx):
    pa, con = c.built()
    if con is None:
        return True, "no warehouse: not run"
    last = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    bad = []
    E = {k: (n, p) for k, n, p in con.execute("SELECT entree, n_formations, places FROM core.parcours_entree").fetchall()}
    for k, (n, p) in E.items():
        if k.startswith("onisep:"):
            q = con.execute("""SELECT count(DISTINCT y.cod_aff_form), coalesce(sum(y.capa_fin), 0) FROM (SELECT DISTINCT cod_aff_form FROM core.onisep_link
                WHERE session = ? AND for_id = ?) l JOIN core.formation_year y ON y.cod_aff_form = l.cod_aff_form AND y.session = ?""",
                            [last, k.split(":", 1)[1], last]).fetchone()
        else:
            parts = k.split(":", 3)
            sql = "SELECT count(*), coalesce(sum(capa_fin), 0) FROM core.formation_year WHERE session = ? AND fili = ?"
            args = [last, parts[1]]
            if len(parts) >= 3:
                sql += " AND coalesce(fil_lib_voe_acc, '') = ?"
                args.append(parts[2])
            if len(parts) == 4:
                sql += " AND coalesce(form_lib_voe_acc, '') = ?"
                args.append(parts[3])
            q = con.execute(sql, args).fetchone()
        if (n, p) != tuple(q):
            bad.append(f"{k}: stored {n}, {p} vs {q}")
    # the formations listed under each entry are exactly its group (Codex: never a search on the label), capped
    seen = 0
    for k, (n, _p) in list(E.items())[:: max(1, len(E) // 60)]:
        got = [x[0] for x in pa.entry_formations(con, k, last)]
        if k.startswith("onisep:"):
            want = {c for (c,) in con.execute("""SELECT DISTINCT cod_aff_form FROM core.onisep_link WHERE session = ? AND for_id = ?""",
                                              [last, k.split(":", 1)[1]]).fetchall()}
        else:
            parts = k.split(":", 3)
            q = "SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND fili = ?" + \
                (" AND coalesce(fil_lib_voe_acc, '') = ?" if len(parts) >= 3 else "") + (" AND coalesce(form_lib_voe_acc, '') = ?" if len(parts) == 4 else "")
            want = {c for (c,) in con.execute(q, [last, *parts[1:]]).fetchall()}
        if len(got) != min(n, pa.FORMATIONS_MAX) or not set(got) <= want or (n <= pa.FORMATIONS_MAX and set(got) != want):
            bad.append(f"{k}: {len(got)} formations listed for {n}")
        seen += 1
    for mid, (_st, d) in rows(con).items():
        pl = [E[r["entree"]][1] for r in d["routes"]]
        if pl != sorted(pl, reverse=True):
            bad.append(f"{mid}: routes not sorted by places")
        tot, cum, want = sum(pl), 0, []
        for x in pl:
            want.append(tot == 0 or cum < 0.8 * tot)
            cum += x
        if [r["principale"] for r in d["routes"]] != want:
            bad.append(f"{mid}: open routes are not the 80 % prefix")
    return not bad, f"{len(E)} entries re-summed, {seen} formation lists checked; {bad[:4]}"


# ---------------------------------------------------------------- PA5

@check("PA5 ground truth: pédiatre, psychiatre, expert-comptable, vétérinaire, an engineer, orthophoniste, architecte vs architecte réseaux, a CAP job")
def pa5(c: Ctx):
    pa, con = c.built()
    if con is None:
        return True, "no warehouse: not run"
    bad = []

    def job(pattern):
        r = con.execute("SELECT met_id FROM core.onisep_metier WHERE nom ILIKE ? ORDER BY met_id LIMIT 1", [pattern]).fetchone()
        return pa.for_metier(con, r[0]) if r else None

    def entries(p, open_only=False):
        return {x["entree"] for x in (p or {}).get("routes", []) if x["principale"] or not open_only}
    p = job("pédiatre")
    if not p or not {"ps:PASS", "ps:Licence_Las"} <= entries(p, True):
        bad.append(f"pédiatre: {sorted(entries(p))[:4]}")
    p = job("psychiatre")
    if not p or "ps:PASS" not in entries(p) or not p.get("voisins"):
        bad.append("psychiatre: no PASS through a nearby job")
    p = job("expert%comptable")
    if not p or not any("Comptabilité et de Gestion" in e for e in entries(p)):
        bad.append(f"expert-comptable: {sorted(entries(p))[:3]}")
    p = job("vétérinaire")
    if not p or "ps:CPGE:BCPST:" not in {e.rsplit(":", 0)[0] for e in entries(p)} and not any(e.startswith("ps:CPGE:BCPST") for e in entries(p)):
        bad.append(f"vétérinaire: {sorted(entries(p))[:4]}")
    p = job("ingénieur/e en mécanique")
    if not p or not any(e.startswith("ps:CPGE:MPSI") for e in entries(p)) or not any(e.startswith("ps:Ecole d'Ingénieur") for e in entries(p)):
        bad.append(f"ingénieur en mécanique: {sorted(entries(p))[:4]}")
    p = job("orthophoniste")
    if not p or not entries(p) or any("Orthophon" not in e for e in entries(p)):
        bad.append(f"orthophoniste: {sorted(entries(p))[:4]}")                     # Codex: never another profession's school
    p = job("architecte réseaux")
    if not p or any("Architecture" in e for e in entries(p)):
        bad.append("architecte réseaux reaches the architecture schools")                # Codex: computing, not building
    p = job("architecte")
    if not p or not any("Architecture" in e for e in entries(p)):
        bad.append("architecte does not reach the architecture schools")
    p = job("peintre en bâtiment")

    if not p or p["statut"] != "sans_postbac" or not p["cibles"] or not all(x["url"].startswith("https://www.onisep.fr/") for x in p["cibles"]):
        bad.append(f"peintre en bâtiment: {p and p['statut']}")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- PA6

def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("[") == part.count("]") and part.rstrip().endswith(";"):
                return part
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    n = shutil.which("node")
    if not n:
        return None
    r = nodefile.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


HOSTILE = "<img src=x onerror=alert(1)>"


@check("PA6 page: escaped, statuses worded, Onisep links noopener, 80 % sentence only with routes, measure from data, vouvoiement")
def pa6(c: Ctx):
    defs = "\n".join(top(c.js, n) for n in ("esc", "fmt", "PA_HOW", "paRoute", "parcoursCard"))
    route = {"entree": "ps:PASS", "etapes": [{"id": "FOR.1", "libelle": "DE " + HOSTILE, "niveau": "bac + 9"}], "comment": "regle",
             "regle": "sante_mmopk", "principale": True,
             "entree_info": {"libelle": "PASS " + HOSTILE, "n_formations": 287, "places": 26646, "recherche": "PASS"},
             "formations": [["123", "Université " + HOSTILE, "Lyon", "Lyon", 120, "Licence - " + HOSTILE], ["456", "Fac", "Brest", "Rennes", None, None]]}
    rest = dict(route, principale=False, entree="ps:X", entree_info=dict(route["entree_info"], libelle="LAS"), formations=[])
    mes = {"a_besoin": 612, "couverts": 510, "couverture": 0.8333}          # not the real figures: a typed measure shows
    cib = [{"id": "FOR.9", "libelle": "CAP " + HOSTILE, "niveau": "CAP", "url": "https://www.onisep.fr/x"}]
    cases = [{"statut": "postbac", "routes": [route, rest], "cibles": cib, "voisins": [{"id": "MET.1", "nom": "médecin " + HOSTILE}],
              "regles": [{"id": "sante_mmopk", "texte": "Texte " + HOSTILE}], "acces": "Accès\n" + HOSTILE, "mesure": mes},
             {"statut": "sans_postbac", "routes": [], "cibles": cib, "voisins": [], "regles": [], "acces": None, "mesure": mes},
             {"statut": "hors_parcoursup", "routes": [], "cibles": [], "voisins": [], "regles": [], "acces": "x", "mesure": mes}, None]
    prog = "const store = { get: (k, d) => d };\n" + defs + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify(D.map((p) => parcoursCard(p, { session: 2025 }))));"""
    out = node(prog, cases)
    if out is None:
        return True, "node absent: not run"
    bad = []
    for i, h in enumerate(out):
        if "<img" in h:
            bad.append(f"case {i}: unescaped")
        if re.search(r"(?i)chances? d'|probabilit", h) or re.search(r"\b(?:tu|ton|ta|tes|toi)\b", re.sub(r"<[^>]+>", " ", h)):
            bad.append(f"case {i}: a chance or tutoiement")
        for a in re.findall(r'<a [^>]*target="_blank"[^>]*>', h):
            if 'rel="noopener"' not in a:
                bad.append(f"case {i}: external link without noopener")
    h0, h1, h2, h3 = out
    if "26 646" not in h0.replace(" ", " ") or "Les voies principales" not in h0 or "Autres voies (1)" not in h0 or "83 %" not in h0 or "612" not in h0:
        bad.append("postbac: places, open/folded routes or the measure missing")
    if 'href="#/f/123"' not in h0 or "Voir 2 des 287 formations" not in h0 or "#/s/" in h0:
        bad.append("postbac: the entry's own formations are not listed (or a search link is back)")
    if "ne demande pas d'études après le bac" not in h1 or "https://www.onisep.fr/x" not in h1 or "80 %" in h1:
        bad.append("sans_postbac: wording, Onisep link, or a places sentence without routes")
    if "Pas de voie Parcoursup identifiée" not in h2:
        bad.append("hors_parcoursup: wording")
    if h3 != "":
        bad.append("no route data still draws a card")
    return not bad, f"{len(cases)} cases; {bad[:4]}"


# ---------------------------------------------------------------- PA7

@check("PA7 plumbing: build, job API, source register, docs, durations, release feature")
def pa7(c: Ctx):
    bad = []
    if "parcours.build(con, onisep.find_sources()" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build.py")
    if '"parcours": PA.for_metier(con, mid)' not in (ROOT / "suptracker" / "metiers.py").read_text():
        bad.append("metiers.detail")
    if "${parcoursCard(d.parcours, d)}" not in c.js:
        bad.append("job page")
    from suptracker import sources
    s = next((x for x in sources.SOURCES if x["key"] == "onisep"), None)
    if not s or "parcours" not in s["feeds"]:
        bad.append("source register")
    if "## From each job to its first formations on Parcoursup" not in (ROOT / "README.md").read_text(encoding="utf-8"):
        bad.append("README")
    if "parcours.py" not in (REPO / "CLAUDE.md").read_text(encoding="utf-8"):
        bad.append("CLAUDE.md")
    if "tests/test_parcours.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    if '"parcours_metier"' not in (ROOT / "tests" / "test_release.py").read_text():
        bad.append("release feature")
    return not bad, f"{bad[:5]}"


# ---------------------------------------------------------------- PA8

SOURCE_MUTANTS = [
    ("pa", "double count", "            if (key, gf, fil, form) in counted:", "            if False:", "PA4"),
    ("pa", "50 % instead of 80 %", "MAIN_SHARE = 0.80", "MAIN_SHARE = 0.50", "PA4"),
    ("pa", "unsorted routes", "key=lambda r: (-entries[r[\"entree\"]][4], entries[r[\"entree\"]][0]))", "key=lambda r: entries[r[\"entree\"]][0])", "PA4"),
    ("pa", "graph read forwards", "                for p in pred.get(node, ()):", "                for p in forms[node][\"suite\"]:", "PA2"),
    ("pa", "branch not ended at a Parcoursup diploma", "                    continue                               # a Parcoursup diploma ends the branch",
     "                    pass", "PA2"),
    ("pa", "rules on unfolded text", "        folded = [_fold(v) for v in vals]", "        folded = list(vals)", "PA5"),
    ("pa", "no nearby jobs", "        if not targets and not routes:                      # else the routes", "        if False:                      # else the routes", "PA5"),
    ("pa", "no job-name rule", "            hit = rule_of({\"lib\": noms.get(mid) or \"\", \"type\": \"\"})", "            hit = None", "PA5"),
    ("pa", "bac read as higher studies", "        need = rank is not None and rank >= 1", "        need = rank is not None and rank >= 0", "PA1"),
    ("pa", "measure typed", "    cov = round(stats[\"postbac\"] / need, 4) if need else None", "    cov = 0.9", "PA1"),
    ("pa", "master matched the reverse way", "f\" {f} \" in f\" {mention} \"]", "f\" {mention} \" in f\" {f} \"]", "PA3"),
    ("pa", "one programme list for every paramedical profession", '[("Autre formation", r"Orthophon", None)]',
     '[("Autre formation", r"Ergoth|Psychomot|Pédicure|manipulateur|Imagerie médicale|Orthophon|Orthopt|Audioprot", None)]', "PA5"),
    ("pa", "health rule to every licence", "[(\"PASS\", None, None), (\"Licence_Las\", None, None)],\n     \"Les études de médecine",
     "[(\"PASS\", None, None), (\"Licence\", None, None)],\n     \"Les études de médecine", "PA3"),
    ("js", "step unescaped", "<span class=\"pa-step\">${esc(s.libelle)}", "<span class=\"pa-step\">${s.libelle}", "PA6"),
    ("js", "formation row unescaped", "<a href=\"#/f/${esc(cod)}\">${esc(etab)}</a>", "<a href=\"#/f/${esc(cod)}\">${etab}</a>", "PA6"),
    ("js", "formation title unescaped", "${lib ? ` · ${esc(lib)}` : \"\"}", "${lib ? ` · ${lib}` : \"\"}", "PA6"),
    ("pa", "entry list ignores the programme", "        sql += \" AND coalesce(y.fil_lib_voe_acc, '') = ?\"\n        args.append(parts[2])",
     "        pass", "PA4"),
    ("pa", "architecture for computing jobs", "and not any(re.search(x, v) for x in excl for v in folded)", "and True", "PA5"),
    ("js", "no-postbac wording dropped", "<strong>Ce métier ne demande pas d'études après le bac.</strong>", "<strong>Ce métier.</strong>", "PA6"),
    ("js", "measure typed", "${fmt(100 * m.couverture)} % des ${fmt(m.a_besoin)}", "87 % des 737", "PA6"),
]


@check("PA8 mutation test: mutants of the routes, the rules, the 80 % rule and the page, each caught")
def pa8(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    if c.db is None:
        return True, "no warehouse: mutants not run"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        m._built = {}
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
    ap.add_argument("--real", action="store_true", help="the committed warehouse (the checks always build on a copy of it)")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
