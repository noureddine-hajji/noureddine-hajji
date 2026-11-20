"""Red team of the jobs card (Onisep Idéo: the jobs a diploma leads to, national, by diploma).

    python scripts/redteam_onisep.py [--db data/suptracker.duckdb] [--real]

The XML files are re-read independently, the link of every formation of the latest campaign is
re-derived with the red team's own normalisation and rules, a truth table of real titles is checked,
the access flag (accessible with this diploma or after further studies) is re-derived, the page is
checked, and a mutation test seeds bugs (a BTS linked to a BUT sheet, options or parcours ignored,
the access flag inverted, a wrong diploma level, an unparsed 'bac' level, UI escaping and wording...)
that must each be caught.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import onisep as ON  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
REF_LEVEL = {"BTS": 2, "BUT": 3, "Licence": 3, "Licence_Las": 3, "IFSI": 3, "EFTS": 3}
# real titles -> the Onisep diploma a careful reader expects (checked when present)
TRUTH = {
    ("BTS", "Management Commercial Opérationnel"): "BTS management commercial opérationnel",
    ("BTS", "Commerce International"): "BTS commerce international",
    ("IFSI", "D.E Infirmier"): "diplôme d'État d'infirmier",
    ("EFTS", "D.E Educateur Spécialisé"): "diplôme d'État d'éducateur spécialisé",
    ("EFTS", "D.E Assistant de Service Social"): "diplôme d'État d'assistant de service social",
    ("Licence", "Droit"): "licence mention droit",
}
# the module's explicit BTS spelling rules, copied at import: O2's reference uses this copy, O6 checks the table itself
REF_SPELLING = dict(ON.BTS_SPELLING)
# national diplomas by exact title (owner, 2026-11-20): the red team's own reading of the types, the SIES labels and the format
REF_NATIONAL_TYPE = {"certificat de spécialisation": "cs", "diplôme d'études universitaires scientifiques et techniques": "deust",
                     "brevet professionnel de la jeunesse, de l'éducation populaire et du sport": "bpjeps", "titre professionnel": "tp"}
REF_NATIONAL_FORM = {"Certificat de Spécialisation": "cs", "DEUST": "deust", "BPJEPS": "bpjeps"}


def rnational(label):
    """Own normalisation: acronyms (Onisep's own « cs / csa / deust / bpjeps / tp » first word, the cartographie's « FP - Titre
    professionnel - », « CS - »...), brackets, « - en apprentissage », then the red team's key."""
    s = (label or "").replace("\xa0", " ")
    s = re.sub(r"(?i)^\s*(fp\s*-\s*titre professionnel\s*-?|csa?\s*-|deust\s*-|bpjeps\s*-)\s*", "", s)
    s = re.sub(r"(?i)\s*-\s*en apprentissage\s*$", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"^(csa?|deust|bpjeps|tp) ", "", rfold(s))
    return rkey(s)


def ref_offer(idx, mention):
    m = (mention or "").replace("\xa0", " ")
    for nat, pre in (("tp", r"(?i)^\s*fp\s*-\s*titre professionnel"), ("cs", r"(?i)^\s*csa?\s*-"), ("deust", r"(?i)^\s*deust\s*-"),
                     ("bpjeps", r"(?i)^\s*bpjeps\s*-")):
        if re.match(pre, m):
            return set(idx.get("NAT", {}).get((nat, rnational(m)), set()))
    return set()


# O6's own reading of a few rules (written apart from the module's table): the option a careful reader expects
SPELLING_TRUTH = {
    "Métiers de l'audio-visuel opt : métiers du son": "BTS métiers de l'audiovisuel option métiers du son",
    "Métiers de l'audio-visuel opt : métiers de l'image": "BTS métiers de l'audiovisuel option métiers de l'image",
    "Technico-commercial - Spécialité vins, bières et spiritueux": "BTSA technico-commercial option vins, bières et spiritueux",
    "QUalité, ALimentation, Innovation et Maîtrise Sanitaire (BioQUALIM) produits laitiers":
        "BTSA qualité, alimentation, innovation et maîtrise sanitaire option produits laitiers",
    "Analyse, conduite et stratégie de l'entreprise agricole, option Territoires ultra-marins":
        "BTSA analyse, conduite et stratégie de l'entreprise agricole option transition agricole dans les territoires ultramarins",
}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def rfold(s):
    s = unicodedata.normalize("NFKD", (s or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", s))


def rkey(s):
    """The red team's own normalisation (same contract as the module, written apart)."""
    words = rfold(s).replace("1ere annee commune", " ").replace("specialite", " ").split()
    words = ["option" if w == "opt" else w for w in words]
    small = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "pour", "sur"}
    return " ".join(w[:-1] if len(w) > 3 and w[-1] == "s" else w for w in words if w not in small)


def rrank(label):
    t = rfold(label)
    if re.fullmatch(r"bac \d+( et plus)?", t):
        return int(t.split()[1])
    if t.startswith("bac ou") or t == "bac":
        return 0
    if t.startswith("cap") or t.startswith("bep"):
        return -1
    if t in ("3e", "sans diplome", "diplome national du brevet"):
        return -2
    return None


def rxml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".xml")][0]))


class Ctx:
    def __init__(self, db: Path, real: bool, sources: dict | None = None):
        self.db, self.real = db, real
        self.sources = ON.find_sources() if sources is None else sources
        con = duckdb.connect(str(db), read_only=True)
        self.forms = {r[0]: r[1:] for r in con.execute("SELECT * FROM core.onisep_formation").fetchall()}
        self.fm = set(con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall())
        self.mets = {r[0]: r[1:] for r in con.execute("SELECT * FROM core.onisep_metier").fetchall()}
        self.links = {}
        for cod, fili, prog, fid, rule in con.execute("SELECT cod_aff_form, fili, programme, for_id, regle FROM core.onisep_link").fetchall():
            self.links.setdefault(cod, [fili, prog, set(), rule])[2].update({fid} if fid else set())
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.latest_forms = con.execute("""SELECT cod_aff_form, fili, fil_lib_voe_acc, form_lib_voe_acc FROM core.formation_year
                                           WHERE session = ?""", [latest]).fetchall()
        con.close()
        self.ref = self._ref_tables()

    def _ref_tables(self):
        fr = rxml(self.sources["formations"])
        forms = {f.findtext("identifiant"): (f.findtext("libelle_complet"), f.findtext("type_Formation/type_formation_libelle"),
                                             f.findtext("niveau_etudes/libelle")) for f in fr}
        fm = {(f.findtext("identifiant"), m.findtext("id")) for f in fr for m in f.findall("metiers_formation/metier")}
        mets = {}
        if "metiers" in self.sources:
            for m in rxml(self.sources["metiers"]):
                mets[m.findtext("identifiant")] = (m.findtext("nom_metier"), m.findtext("niveau_acces_min/libelle"))
        return {"forms": forms, "fm": fm, "mets": mets}

    def ref_index(self):
        idx = {"BTS": {}, "BUT": {}, "LIC": {}, "DE": {}}
        for fid, (lib, typ, _lvl) in self.ref["forms"].items():
            f, t = rfold(lib), typ or ""
            if t.startswith("brevet de technicien sup"):
                fam, spec = "BTS", re.sub(r"^btsa? ", "", f)
            elif t == "bachelor universitaire de technologie":
                fam, spec = "BUT", re.sub(r" parcours .*$", "", re.sub(r"^but ", "", f))
            elif t == "licence":
                fam, spec = "LIC", re.sub(r"^licence (mention )?", "", f)
            elif f.startswith("diplome d etat d"):
                fam, spec = "DE", f
            elif t in REF_NATIONAL_TYPE:
                idx.setdefault("NAT", {}).setdefault((REF_NATIONAL_TYPE[t], rnational(f)), set()).add(fid)
                continue
            else:
                continue
            idx[fam].setdefault(rkey(spec), set()).add(fid)
        return idx

    def ref_links(self, rows=None):
        idx = self.ref_index()
        out = {}
        for cod, fili, prog, *form in self.latest_forms if rows is None else rows:
            fids = set()
            form = form[0] if form else None
            if fili == "Autre formation" and form in REF_NATIONAL_FORM:     # same national title, same diploma type
                fids = idx.get("NAT", {}).get((REF_NATIONAL_FORM[form], rnational(prog)), set())
            elif fili == "BTS":
                k = rkey(prog)
                fids = idx["BTS"].get(k) or {f for kk, v in idx["BTS"].items() if kk.startswith(k + " option") for f in v} \
                    or (idx["BTS"].get(k.split(" option")[0], set()) if " option" in k else set())
                if not fids and (prog or "").strip() in REF_SPELLING:      # explicit spelling rule: the sheet of that exact title
                    t = rfold(REF_SPELLING[(prog or "").strip()])
                    fids = {fid for fid, (lib, typ, _l) in self.ref["forms"].items()
                            if rfold(lib) == t and (typ or "").startswith("brevet de technicien sup")}
            elif fili == "BUT":
                fids = idx["BUT"].get(rkey(re.sub(r"(?i) parcours .*$", "", prog or "")), set())
            elif fili in ("Licence", "Licence_Las"):
                fids = idx["LIC"].get(rkey(prog), set())
            elif fili == "IFSI":
                fids = idx["DE"].get(rkey("diplome d etat d infirmier"), set())
            elif fili == "EFTS":
                fids = idx["DE"].get(rkey("diplome d etat d " + re.sub(r"^d e ", "", rfold(prog))), set())
            out[cod] = (fili, set(fids))
        return out


# ---------------------------------------------------------------- checks
@check("O1 the XML sheets are re-read independently: diplomas, diploma -> job links and jobs stored as published")
def o1(c: Ctx):
    bad = []
    if set(c.forms) != set(c.ref["forms"]):
        bad.append(("formations", len(c.forms), len(c.ref["forms"])))
    if any(c.forms[f][0] != c.ref["forms"][f][0] or c.forms[f][1] != c.ref["forms"][f][1] for f in set(c.forms) & set(c.ref["forms"])):
        bad.append("formation labels")
    if c.fm != c.ref["fm"]:
        bad.append(("links", len(c.fm), len(c.ref["fm"])))
    if set(c.mets) != set(c.ref["mets"]) or any(c.mets[m][0] != c.ref["mets"][m][0] or c.mets[m][1] != c.ref["mets"][m][1] for m in c.mets):
        bad.append("jobs")
    ranks = [m for m, v in c.mets.items() if v[2] != rrank(v[1])]
    return not bad and not ranks and len(c.forms) > 0, f"{len(c.forms)} diplomas, {len(c.fm)} links, {len(c.mets)} jobs; {bad[:3]}; level ranks wrong {ranks[:3]}"


@check("O2 link: every formation of the latest campaign re-derived (same family, title, options, parcours, state diplomas), truth table")
def o2(c: Ctx):
    want = c.ref_links()
    got = {cod: v[2] for cod, v in c.links.items()}
    bad = [(cod, sorted(got.get(cod, set()))[:2], sorted(w[1])[:2]) for cod, w in want.items() if got.get(cod, set()) != w[1]]
    fam = {"BTS": ("brevet de technicien sup",), "BUT": ("bachelor universitaire",), "Licence": ("licence",), "Licence_Las": ("licence",)}
    cross = [(cod, f) for cod, v in c.links.items() for f in v[2] if v[0] in fam and not (c.ref["forms"][f][1] or "").startswith(fam[v[0]])]
    truth = []
    titles = {(v[0], v[1]): v[2] for v in c.links.values()}
    for (fili, prog), lib in TRUTH.items():
        if (fili, prog) in titles and lib not in {c.ref["forms"][f][0] for f in titles[(fili, prog)]}:
            truth.append((fili, prog))
    cov = {}
    for fili in ("BTS", "BUT", "IFSI", "EFTS", "Licence"):
        xs = [v for v in want.values() if v[0] == fili]
        cov[fili] = round(sum(1 for v in xs if v[1]) / len(xs), 3) if xs else None
    floors = {"BTS": 0.85, "BUT": 0.95, "IFSI": 1.0, "EFTS": 1.0, "Licence": 0.80}
    low = [f for f, x in cov.items() if c.real and x is not None and x < floors[f]]
    return not bad and not cross and not truth and not low, f"{len(want)} formations, {len(bad)} differ {bad[:2]}; cross-family {cross[:2]}; truth {truth}; coverage {cov}"


@check("O3 API: the jobs are the union of the matched sheets' jobs, the access flag compares the job's minimum level with the diploma's")
def o3(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    bad, n = [], 0
    by = Counter()
    def ref_level(fili, fids):
        """The diploma level read from the raw sheets (lowest when several differ), the filière's usual one otherwise."""
        ranks = [r for r in (rrank(c.ref["forms"][f][2]) for f in fids if f in c.ref["forms"]) if r is not None]
        return min(ranks) if ranks else REF_LEVEL.get(fili)
    # every formation whose sheet departs from its filière's usual level is checked (3-year BTS: sprint 12 finding)
    odd = {cod for cod, (fili, _, fids, _) in c.links.items() if fids and ref_level(fili, fids) != REF_LEVEL.get(fili)}
    for cod, (fili, prog, fids, rule) in c.links.items():
        if by[rule] >= 30 and cod not in odd:
            continue
        by[rule] += 1
        b = ON.for_formation(con, cod)
        n += 1
        if not fids:
            if (b is None) != (rule == "filiere_sans_fiche") or (b and b["status"] != "sans_fiche"):
                bad.append((cod, "status"))
            continue
        want = {m for f, m in c.ref["fm"] if f in fids}
        got = {j["id"] for j in b["metiers"]}
        if want != got:
            bad.append((cod, "jobs"))
        lvl = ref_level(fili, fids)
        if b["niveau"] != lvl:
            bad.append((cod, "level", b["niveau"], lvl))
        for j in b["metiers"]:
            r = rrank(c.ref["mets"].get(j["id"], (None, None))[1])
            exp = None if r is None or lvl is None else "direct" if r <= lvl else "poursuite"
            if j["acces"] != exp:
                bad.append((cod, j["id"], j["acces"], exp))
        if {d["id"] for d in b["diplomes"]} != fids:
            bad.append((cod, "diplomas"))
    con.close()
    # witness cases, true on any data: a 3-year BTS sheet is bac+3; a sheet stating no level falls back on the filière
    if ON.sheet_level(["bac + 3"], "BTS") != 3 or ON.sheet_level([None], "BTS") != 2 or ON.sheet_level(["bac + 2", "bac + 3"], "BTS") != 2:
        bad.append(("witness", "sheet level"))
    return not bad and n > 0, f"{n} pages ({len(odd)} with a sheet level unusual for the filière), {len(bad)} wrong {bad[:3]}"


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 8 follow-up: the jobs a diploma leads to")
    blk = js[i: js.index("// ---- Sprint 8 follow-up: does the job match", i)]
    code = re.sub(r"(?m)^\s*//.*$", "", blk)
    safe = ("esc(", "tip(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", code)
           if re.search(r"\.(?:nom|libelle|url|niveau_acces_min)\b", m) and not m.lstrip().startswith(safe)]
    blank = re.findall(r'target="_blank"(?! rel="noopener")', code)
    words = all(w in code for w in ("Liste nationale du diplôme, pas propre à cet établissement", "pas une promesse d'emploi",
                                    "licence ODbL", "après une poursuite d'études", "accessible avec ce diplôme"))
    wired = "${metiersCard(d.metiers)}" in js
    ok = not raw and not blank and words and wired
    return ok, f"unescaped {raw[:3]}; links without noopener {len(blank)}; wording {words}; wired {wired}"


@check("O4 page: Onisep strings and links escaped, external links noopener, national-list and no-promise caveats, ODbL credit")
def o4(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped job name", '${esc(j.nom)}</a>', '${j.nom}</a>'),
    ("unescaped diploma URL", 'href="${esc(d.url)}"', 'href="${d.url}"'),
    ("external link without noopener", '<a href="${esc(j.url)}" target="_blank" rel="noopener">', '<a href="${esc(j.url)}" target="_blank">'),
    ("national-list caveat dropped", "Liste nationale du diplôme, pas propre à cet établissement. ", ""),
    ("ODbL credit dropped", "Source : Onisep, Idéo (licence ODbL).", "Source : Onisep."),
    ("card not wired", "${metiersCard(d.metiers)}", ""),
]


def spelling_problems(c: Ctx, table: dict) -> list:
    """What is wrong with a BTS spelling table: a target that is not ONE BTS sheet, a source the general rules already
    match (a dead rule), a source absent from the latest campaign (real data), a target that shares fewer words with its
    source than another target of the same BTS does (swapped options), a reading of SPELLING_TRUTH contradicted."""
    bts = {}
    for fid, (lib, typ, _l) in c.ref["forms"].items():
        if (typ or "").startswith("brevet de technicien sup"):
            bts.setdefault(rfold(lib), []).append(fid)
    saved = dict(REF_SPELLING)
    REF_SPELLING.clear()
    try:
        plain = c.ref_links([(src, "BTS", src) for src in table])
    finally:
        REF_SPELLING.update(saved)
    progs = {p for _, fili, p, *_ in c.latest_forms if fili == "BTS"}
    bad = []
    for src, tgt in table.items():
        words = set(rkey(src).split())
        if len(bts.get(rfold(tgt), [])) != 1:
            bad.append(("not one BTS sheet", tgt))
        if plain[src][1]:
            bad.append(("dead rule: the general rules already match", src))
        if c.real and src not in progs:
            bad.append(("absent from the latest campaign", src))
        rivals = [t for s2, t in table.items() if t != tgt and rkey(s2).split()[:2] == rkey(src).split()[:2]]
        if any(len(words & set(rkey(t).split())) > len(words & set(rkey(tgt).split())) for t in rivals):
            bad.append(("another sheet of this BTS fits the label better", src))
        if src in SPELLING_TRUTH and SPELLING_TRUTH[src] != tgt:
            bad.append(("truth", src))
    return bad


@check("O6 BTS spelling rules: each names ONE real BTS sheet, is needed, is used on real data, keeps its own option")
def o6(c: Ctx):
    # on a fixture (not the real files), the rules' sheets and the one a dead-rule mutant needs are crafted, removed after
    crafted = []
    if not c.real:
        have = {rfold(v[0]) for v in c.ref["forms"].values()}
        for i, t in enumerate(sorted(set(ON.BTS_SPELLING.values()) | {"BTS management commercial opérationnel"})):
            if rfold(t) not in have:
                c.ref["forms"][f"FOR.RTS{i}"] = (t, "brevet de technicien supérieur", None)
                crafted.append(f"FOR.RTS{i}")
    try:
        return _o6(c)
    finally:
        for k in crafted:
            del c.ref["forms"][k]


def _o6(c: Ctx):
    bad = spelling_problems(c, ON.BTS_SPELLING)
    used = Counter(rule for (_f, _p, fids, rule) in c.links.values() if fids)
    # mutants of the table: two options swapped, a rule pointing to a missing sheet, a rule the general rules make dead
    a, b = "Métiers de l'audio-visuel opt : métiers du son", "Métiers de l'audio-visuel opt : métiers de l'image"
    mutants = {"options swapped": {**ON.BTS_SPELLING, a: ON.BTS_SPELLING[b], b: ON.BTS_SPELLING[a]},
               "missing sheet": {**ON.BTS_SPELLING, a: "BTS métiers de l'audiovisuel option métiers du bruit"},
               "dead rule": {**ON.BTS_SPELLING, "Management Commercial Opérationnel": "BTS management commercial opérationnel"}}
    missed = [n for n, t in mutants.items() if not spelling_problems(c, t)]
    ok = not bad and not missed and (not c.real or used["bts_ecriture"] > 0)
    return ok, f"{len(ON.BTS_SPELLING)} rules, {used['bts_ecriture']} formations linked by them; problems {bad[:3]}; mutants missed {missed}"


NAT_FORMS = [("FOR.N1", "CS cybersécurité", "certificat de spécialisation"), ("FOR.N2", "CSA conduite de l'élevage porcin", "certificat de spécialisation"),
             ("FOR.N3", "TP technicien supérieur en méthodes et exploitation logistique", "titre professionnel"),
             ("FOR.N4", "DEUST préparateur technicien en pharmacie", "diplôme d'études universitaires scientifiques et techniques"),
             ("FOR.N5", "BPJEPS spécialité éducateur sportif mention activités du vélo",
              "brevet professionnel de la jeunesse, de l'éducation populaire et du sport"),
             ("FOR.N6", "TP cybersécurité", "titre professionnel"),                  # same words, another diploma: never crossed
             ("FOR.N7", "FCIL métiers du bar", "formation complémentaire d'initiative locale"),
             ("FOR.N8", "CS métiers du bar", "certificat de spécialisation")]        # a FCIL of that title never takes the CS sheet
NAT_SIES = [("N-1", "Autre formation", "Cybersécurité", "Certificat de Spécialisation"),
            ("N-2", "Autre formation", "Métiers du bar", "FCIL"),                           # FCIL: local, never a sheet
            ("N-3", "Autre formation", "Préparateur/Technicien en pharmacie", "DEUST"),     # a slash is a separator
            ("N-4", "Autre formation", "Cybersécurité <b>", "Certificat de Spécialisation"),   # another title: none
            ("N-5", "Autre formation", "Spécialité Educateur sportif - Mention Activités du vélo", "BPJEPS"),   # « - » a separator
            ("N-6", "Licence", "Cybersécurité", None)]
NAT_OFFERS = ["FP - Titre professionnel - Technicien(ne) supérieur(e) en méthodes et exploitation logistique (bac +2)",
              "CSA - Conduite de l'élevage porcin - en apprentissage", "CS - Cybersécurité", "DEUST - Préparateur/Technicien en pharmacie",
              "BPJEPS - Spécialité Educateur sportif - Mention Activités du vélo", "Métiers du bar", "FP - Responsable de chantier",
              "TP - Cybersécurité"]


def national_problems(index, match, match_offer) -> list:
    """The module's national-title link (index, match, match_offer) against the red team's reading of a crafted fixture."""
    forms = [(f, lib, typ, None, None) for f, lib, typ in NAT_FORMS]
    ref = {"NAT": {}}
    for fid, lib, typ in NAT_FORMS:
        if typ in REF_NATIONAL_TYPE:
            ref["NAT"].setdefault((REF_NATIONAL_TYPE[typ], rnational(lib)), set()).add(fid)
    idx = index(forms)
    bad = []
    for cod, fili, prog, form in NAT_SIES:
        want = ref["NAT"].get((REF_NATIONAL_FORM.get(form), rnational(prog)), set()) if fili == "Autre formation" else set()
        got = set(match(idx, fili, prog, form)[0])
        if got != want:
            bad.append((cod, sorted(got), sorted(want)))
    for m in NAT_OFFERS:
        got, want = set(match_offer(idx, m)[0]), ref_offer(ref, m)
        if got != want:
            bad.append((m[:30], sorted(got), sorted(want)))
    # the crafted truth: what a careful reader expects, written apart
    truth = {"N-1": {"FOR.N1"}, "N-2": set(), "N-3": {"FOR.N4"}, "N-4": set(), "N-5": {"FOR.N5"}, "N-6": set()}
    for cod, fili, prog, form in NAT_SIES:
        if set(match(idx, fili, prog, form)[0]) != truth[cod]:
            bad.append(("truth", cod))
    if set(match_offer(idx, NAT_OFFERS[0])[0]) != {"FOR.N3"} or set(match_offer(idx, NAT_OFFERS[1])[0]) != {"FOR.N2"} \
            or set(match_offer(idx, NAT_OFFERS[2])[0]) != {"FOR.N1"} or match_offer(idx, NAT_OFFERS[5])[0]:
        bad.append(("truth", "offers"))
    return bad


@check("O7 national titles (CS, DEUST, BPJEPS, titres professionnels): the same type and exact title, FCIL never, offers read alike")
def o7(c: Ctx):
    bad = national_problems(ON.index, ON.match, ON.match_offer)
    orig_key, orig_match, orig_offer = ON.national_key, ON.match, ON.match_offer

    def types_mixed(forms):                 # a TP sheet answers for a CS of the same words
        idx = ON.index(forms)
        for k in ("NAT_cs", "NAT_tp"):
            idx.setdefault(k, {})
        for kk, v in list(idx["NAT_tp"].items()):
            idx["NAT_cs"].setdefault(kk, []).extend(v)
        return idx

    def fcil(idx, fili, prog, form=None):
        return orig_match(idx, fili, prog, "Certificat de Spécialisation" if form == "FCIL" else form)

    mutants = {"brackets kept": lambda: setattr(ON, "national_key", lambda l: ON.key((l or "").replace("\xa0", " "))),
               "diploma types mixed": lambda: setattr(ON, "index", types_mixed),
               "FCIL read as a certificat": lambda: setattr(ON, "match", fcil),
               "offers ignored": lambda: setattr(ON, "match_offer", lambda idx, m: ([], None))}
    saved = {k: getattr(ON, k) for k in ("national_key", "index", "match", "match_offer")}
    missed = []
    for name, apply in mutants.items():
        try:
            apply()
            caught = bool(national_problems(ON.index, ON.match, ON.match_offer))
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)
    real = ""
    if c.real:
        from suptracker import carte as CA
        con = duckdb.connect(str(c.db), read_only=True)
        try:
            offers = [a["mention"] for a in CA.apprentissage(con) if not a["rattachee"]]
        finally:
            con.close()
        forms, _ = ON.read_formations(Path(c.sources["formations"]))
        idx, ref = ON.index(forms), c.ref_index()
        diff = [m for m in offers if set(ON.match_offer(idx, m)[0]) != ref_offer(ref, m)]
        n = sum(1 for m in offers if ON.match_offer(idx, m)[0])
        used = Counter(rule for (_f, _p, fids, rule) in c.links.values() if fids and (rule or "").startswith("titre_national"))
        if diff:
            bad.append(f"real offers differ: {len(diff)}, e.g. {diff[:2]}")
        if not used:
            bad.append("no SIES formation linked by its national title")
        real = f"; real: {dict(used)} SIES formations, {n} of {len(offers)} apprenticeship offers"
    return not bad and not missed, f"problems {bad[:3]}; mutants missed {missed}{real}"


@check("O5 mutation test: cross-family link, options or parcours ignored, access flag inverted, wrong level, unparsed 'bac', UI bugs")
def o5(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    work = duckdb.connect(str(c.db), read_only=True)
    forms, links = ON.read_formations(Path(c.sources["formations"]))
    # edge rows injected so that every link mutant has something to bite on any data: a BTS without a sheet whose
    # first word is a BUT's, a BTS with an abbreviated option, a BUT with a parcours, a licence named like a licence pro
    edge = [("RT-1", "BTS", "Gestion forestière de démonstration"), ("RT-2", "BTS", "Systèmes numériques opt A"),
            ("RT-3", "BUT", "Gestion des entreprises et des administrations parcours démonstration"), ("RT-4", "Licence", "Droit"),
            ("RT-5", "Licence", "Agencement"), ("RT-6", "BTS", "Métiers de l'audio-visuel opt : métiers du son")]
    rows = c.latest_forms + edge
    # RT-6 needs its spelling rule's sheet: a fixture without it gets a crafted one (removed after the test)
    t6 = REF_SPELLING["Métiers de l'audio-visuel opt : métiers du son"]
    added = not any(rfold(f[1]) == rfold(t6) for f in forms)
    if added:
        forms = forms + [("FOR.RT6", t6, "brevet de technicien supérieur", None, None)]
        c.ref["forms"]["FOR.RT6"] = (t6, "brevet de technicien supérieur", None)
    try:
        want = {cod: w[1] for cod, w in c.ref_links(rows).items()}
    finally:
        if added:
            del c.ref["forms"]["FOR.RT6"]
    saved = {k: getattr(ON, k) for k in ("match", "index", "level_rank", "LEVEL", "key", "sheet_level")}

    def links_now():
        idx = ON.index(forms)
        out = {}
        for cod, fili, prog, *form in rows:
            out[cod] = set(ON.match(idx, fili, prog, form[0] if form else None)[0])
        return out

    def cross_family(idx, fili, prog):
        fids, rule = saved["match"](idx, fili, prog)
        if fili == "BTS" and not fids:                     # a BTS without a sheet borrows a BUT / licence sheet of the same field
            w = ON.key(prog).split()[:1]
            fids = [f for fam in ("BUT", "LIC") for kk, v in idx[fam].items() if kk.split()[:1] == w for f in v][:1]
        return fids, rule

    def with_lpro(forms_):                                  # a licence professionnelle taken for the licence of the same field
        idx = saved["index"](forms_)
        for fid, lib, typ, _, _ in forms_:
            if (typ or "").startswith("licence pro"):
                k = ON.key(re.sub(r"^licence pro(fessionnelle)? (mention )?", "", ON.fold(lib)))
                idx["LIC"][k] = idx["LIC"].get(k, []) + [fid]
        return idx

    def no_options(idx, fili, prog):
        fids, rule = saved["match"](idx, fili, prog)
        return ([], rule) if rule == "bts_options" else (fids, rule)

    def no_spelling(idx, fili, prog):
        fids, rule = saved["match"](idx, fili, prog)
        return ([], rule) if rule == "bts_ecriture" else (fids, rule)

    def keep_parcours(forms_):
        idx = saved["index"](forms_)
        idx["BUT"] = {}
        for fid, lib, typ, _, _ in forms_:
            if typ == ON.BUT_TYPE:
                idx["BUT"].setdefault(ON.key(re.sub(r"^but\s+", "", ON.fold(lib))), []).append(fid)
        return idx

    link_mutants = [("BTS linked to a BUT or licence sheet", lambda: setattr(ON, "match", cross_family)),
                    ("licence professionnelle linked to a licence", lambda: setattr(ON, "index", with_lpro)),
                    ("BTS options ignored", lambda: setattr(ON, "match", no_options)),
                    ("BUT parcours kept in the key", lambda: setattr(ON, "index", keep_parcours)),
                    ("BTS spelling rules ignored", lambda: setattr(ON, "match", no_spelling))]
    for name, apply in link_mutants:
        try:
            apply()
            caught = links_now() != want
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)

    sample = [cod for cod, v in c.links.items() if v[2]][:: max(1, len(c.links) // 400)]

    def flags():
        out = {}
        for cod in sample:
            b = ON.for_formation(work, cod)
            out[cod] = tuple(sorted((j["id"], j["acces"]) for j in b["metiers"])) if b and b["status"] == "ok" else None
        return out
    base = flags()
    serve_mutants = [("sheet level ignored (filière's usual level)", lambda: setattr(ON, "sheet_level", lambda lv, fili=None: saved["LEVEL"].get(fili))),
                     ("'bac ou équivalent' left unparsed", lambda: setattr(ON, "level_rank", lambda l: None if rfold(l).startswith("bac ou") else saved["level_rank"](l)))]
    for name, apply in serve_mutants:
        try:
            apply()
            caught = flags() != base or name.startswith("'bac") or not o3(c)[0]   # a rank mutant acts at build time: O1's rule below
            if name.startswith("'bac"):
                caught = any(ON.level_rank(v[1]) != rrank(v[1]) for v in c.ref["mets"].values())
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)
    # the access flag inverted: re-check O3's rule on a doctored answer
    b = next((ON.for_formation(work, cod) for cod in sample if ON.for_formation(work, cod)), None)
    if b and b["status"] == "ok" and b["metiers"]:
        j = b["metiers"][0]
        flipped = {"direct": "poursuite", "poursuite": "direct"}.get(j["acces"], "direct")
        r = rrank(c.ref["mets"].get(j["id"], (None, None))[1])
        lvl = b["niveau"]
        exp = None if r is None or lvl is None else "direct" if r <= lvl else "poursuite"
        if flipped == exp:
            missed.append("access flag inverted")
    work.close()
    n = len(UI_MUTANTS) + len(link_mutants) + len(serve_mutants) + 1
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, sources: dict | None = None) -> list[dict]:
    c = Ctx(db, real, sources)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
