"""Red team of sprint R9, "Recherche depuis la carte" (owner, 2026-11-12).

    python scripts/redteam_carterecherche.py [--db data/suptracker.duckdb] [--real] [--browser]

The owner's eight points: filters and map on the left, the list in the middle, the chosen formation on the right; several
types of diploma and mentions at once; mentions that name the same thing grouped by fixed rules; French alphabetical order;
formations the SIES specialty dataset does not type (CPES, CMI, licences pro...) placed in a zone; three figures per formation
(the OFFICIAL access rate, the figure for the student's doublette as Mes vœux shows it, the average's position among the
admits as a range, never an access rate or a chance).

  CR1 zones for untyped formations: every formation of the latest campaign with published mention counts gets the zone of
      journey.stage2 (read alone or with its filière: one row), on the map, in Mes vœux and in Plan B; never a national list
  CR2 mention groups: each mention in exactly one group, counts add up; double licence = the unordered pair (independent
      parse), the owner's examples, Gestion apart from Économie; groups never cross diplomas; only the listed diplomas grouped
  CR3 French alphabetical order of diplomas and groups (accents and case ignored, independent fold)
  CR4 selection: the API's group filter = the formations of the group; page twins carteSelection / carteKeep / carteHash in Node
  CR5 figures = Mes vœux: /api/carte/chiffres = voeux.figures (bac général); bac techno / pro: the page's pickVoie over the
      report's lines = Mes vœux's line for every printed key; the series line is never sent; 40 codes at most; cache policy
  CR6 position: the page's cartePosition (Node) = the server's stage 2 `position` read with the average (oracle); without an
      average, the published bounds of the band
  CR7 wording: no chance or access rate for the average, the estimation and "pas de taux d'accès par moyenne" said, vouvoiement
  CR8 browser (--browser / --real): three columns in order on a wide screen, the map on the first screen (owner), one column
      without horizontal scroll on a phone
      (390 and 320 px), multi-select and mention filter in the page, CPES placed in a zone, 0 JS errors
  CR9 mutation test: Python and page mutants, each must be caught
  CR10 docs: README section and CLAUDE.md rule
  CR11-CR13 (sprint R10, owner 2026-11-13): rate per bac (report, else estimation) and the most represented line re-derived;
      the card in Node (statut, selectivity, masked, estimation, line, compare); nothing ticked = everything, list first
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import carte as CA  # noqa: E402
from suptracker import journey as J  # noqa: E402
from suptracker import planb as PB  # noqa: E402
from suptracker import voeux as V  # noqa: E402

import redteam_lecture as RL  # noqa: E402

CHECKS = []
STATIC = ROOT / "suptracker" / "static"
CHANCE = re.compile(r"(?i)probabilit|chances? d'[eê]tre|de chances|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
PAGE_TWINS = ("cartePosition", "pctRange", "carteSelection", "foldText", "carteHash", "carteKeep", "pickVoie")
DISPATCH = r"""
const F = { cartePosition, carteSelection, carteHash, carteKeep, pickVoie, lire };
let raw = ""; process.stdin.on("data", (x) => (raw += x)); process.stdin.on("end", () => {
  const out = [];
  for (const c of JSON.parse(raw)) { try { out.push(F[c.fn](...c.args)); } catch (e) { out.push({ __error__: String(e && e.stack || e) }); } }
  process.stdout.write(JSON.stringify(out === undefined ? null : out));
});
"""


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False, js: str | None = None):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = js if js is not None else (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.latest = self.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]


def node(js: str, cases: list[dict]):
    exe = shutil.which("node")
    if not exe:
        return None
    prog = "\n".join(RL.top(js, n) for n in RL.TWINS + PAGE_TWINS) + DISPATCH
    r = subprocess.run([exe, "-e", prog], input=json.dumps(cases, default=float), capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


def fold(x: str) -> str:
    """Independent of carte.sort_key: Unicode decomposition, combining marks dropped, case folded, spaces collapsed."""
    return " ".join("".join(ch for ch in unicodedata.normalize("NFD", x) if not unicodedata.combining(ch)).casefold().split())


def untyped(con, latest) -> list[tuple]:
    return con.execute("""SELECT fy.cod_aff_form, fy.fil_lib_voe_acc, fy.fili, fy.form_lib_voe_acc, fy.lib_for_voe_ins
        FROM core.formation_year fy LEFT JOIN core.taxonomy_link t USING (session, cod_aff_form)
        WHERE fy.session = ? AND t.rule_id IS NULL ORDER BY 1""", [latest]).fetchall()


# ------------------------------------------------------------------ CR1
@check("CR1 zones for untyped formations: stage 2 rows (alone = with their filière), on the map, in Mes vœux and Plan B; never a national list")
def cr1(c: Ctx):
    dk = J.doublette_key("MATHS", "SES")
    rows = untyped(c.con, c.latest)
    bad, n_zone = [], 0
    by_dip: dict = {}
    for cod, fil, fili, form, lib in rows:
        by_dip.setdefault(CA.diplome_of(fili, form, fil, lib)[0], set()).add(cod)
    for d, cods in sorted(by_dip.items()):
        got = CA.zones(c.con, d, None, dk, "b", "bg")["zones"]
        missing = [x for x in cods if x not in got]
        if missing:
            bad.append((d, "no zone", missing[:3]))
        n_zone += sum(1 for x in cods if x in got)
    # a row does not depend on the set it is read with: alone = with its filière (independent reading of each)
    sample = rows[:: max(1, len(rows) // 25)][:25]
    for cod, fil, *_ in sample:
        alone = J.stage2(c.con, dk, "b", J.SANS_TYPE, only=[cod])["formations"]
        group = {f["cod_aff_form"]: f for f in J.stage2(c.con, dk, "b", J.SANS_TYPE, only=J.untyped_codes(c.con, [fil]))["formations"]}
        if not alone or alone[0]["zone"] != group[cod]["zone"] or alone[0]["cdf"] != group[cod]["cdf"]:
            bad.append((cod, "row depends on its set"))
    # Mes vœux and Plan B read the same zone as the map
    for cod, fil, fili, form, lib in sample[:8]:
        d = CA.diplome_of(fili, form, fil, lib)[0]
        z = CA.zones(c.con, d, None, dk, "b", "bg")["zones"].get(cod)
        ev = V.evaluate(c.con, [cod], serie="bg", dkey=dk, mention="b")["voeux"][0]
        pb = PB.plan_b(c.con, cod, serie="bg", dkey=dk, mention="b")
        if ev.get("zone") != z or (pb.get("target") or {}).get("zone", z) != z:
            bad.append((cod, "zone differs", z, ev.get("zone"), (pb.get("target") or {}).get("zone")))
    try:
        J.stage2(c.con, dk, "b", J.SANS_TYPE)
        bad.append("sans_type read without `only`")
    except ValueError:
        pass
    need = n_zone > 0 if c.real else True
    return need and not bad, f"{len(rows)} untyped formations, {n_zone} placed in a zone; problems {bad[:4]}"


# ------------------------------------------------------------------ CR2
DL_TRUTH = [  # (label A, label B, same group?)  the owner's examples and their opposites
    ("Mathématiques / Informatique - Double licence Mathématiques - Informatique", "Informatique / Mathématiques - Double Licence Informatique/Mathématiques", True),
    ("Mathématiques / Economie", "Economie / Mathématiques - Double licence - Economie - Mathématiques", True),
    ("Mathématiques / Economie et gestion - Double licence Mathématiques - Economie", "Mathématiques / Economie", True),
    ("Droit / Gestion - Droit - Gestion", "Droit / Economie et gestion", False),                 # owner: Gestion apart
    ("Droit / Histoire", "Histoire / Droit - double licence HISTOIRE - DROIT", True),
    ("Mathématiques / Physique", "Mathématiques / Informatique", False),
    ("Histoire / Langues, littératures et civilisations étrangères et régionales - HISTOIRE - LLCER ANGLAIS",
     "Histoire / Langues, littératures et civilisations étrangères et régionales - Histoire -Espagnol", True),
    ("Droit / Langues étrangères appliquées - Droit Langues Anglais/Allemand", "Droit / Langues, littératures et civilisations étrangères et régionales - Droit - LLCER Parcours Anglais", False),
]


def dl_pair(m: str) -> frozenset:
    """Independent: the head before ' - ' when it holds '/', the two disciplines, each read once in a short own table."""
    head = m.split(" - ")[0] if "/" in m.split(" - ")[0] else m
    parts = [p for p in re.split(r"\s*/\s*|\s+-\s+", head) if p.strip()][:2]
    own = {"economie et gestion": "economie", "physique, chimie": "physique-chimie", "geographie et amenagement": "geographie",
           "langues, litteratures et civilisations etrangeres et regionales": "llcer", "cinema et audiovisuel": "cinema",
           "cinema : pratique et esthetique": "cinema", "lettres, langues": "lettres", "musique et musicologie": "musicologie",
           "mathematiques et informatique appliquees aux sciences humaines et sociales": "miashs",
           "langues etrangeres appliquees": "lea", "sciences de l'homme, anthropologie, ethnologie": "anthropologie, ethnologie"}
    return frozenset(own.get(fold(p), fold(p)) for p in parts) if len(parts) == 2 else frozenset([fold(m)])


@check("CR2 mention groups: each mention in one group, counts add up; double licence = unordered pair; owner's examples; per diploma only")
def cr2(c: Ctx):
    fac = CA.facets(c.con)
    bad = []
    for d in fac["diplomes"]:
        seen = {}
        for g in d["mentions"]:
            for v in g["variantes"]:
                seen[v] = seen.get(v, 0) + 1
                if CA.groupe_of(d["label"], v) != g["label"]:
                    bad.append((d["label"], v, "group"))
        if any(x != 1 for x in seen.values()) or sum(g["n"] for g in d["mentions"]) != d["n"]:
            bad.append((d["label"], "partition"))
        if d["label"] not in ("Double licence", "CUPGE", "CPES", "Licence", "Licence Accès Santé (L.AS)"):
            bad += [(d["label"], g["label"], "grouped") for g in d["mentions"] if {" ".join(v.split()) for v in g["variantes"]} != {g["label"]}]
        if d["label"] == "Double licence":
            pairs: dict = {}
            for g in d["mentions"]:
                for v in g["variantes"]:
                    pairs.setdefault(dl_pair(v), set()).add(g["label"])
            bad += [("pair split", sorted(p), sorted(gs)) for p, gs in pairs.items() if len(gs) > 1]
            owners = {}
            for g in d["mentions"]:
                for v in g["variantes"]:
                    owners.setdefault(g["label"], set()).add(dl_pair(v))
            bad += [("pairs merged", gl) for gl, ps in owners.items() if len(ps) > 1]
    for a, b, same in DL_TRUTH:
        if (CA.groupe_of("Double licence", a) == CA.groupe_of("Double licence", b)) != same:
            bad.append(("truth", a[:40], b[:40]))
    if CA.groupe_of("Licence", "Théologie Catholique") != CA.groupe_of("Licence", "Théologie Protestante") or \
            CA.groupe_of("Licence", "Droit") != "Droit" or CA.groupe_of("BUT", "Informatique") != "Informatique":
        bad.append("licence near-duplicates")
    dl = next((d for d in fac["diplomes"] if d["label"] == "Double licence"), None)
    shrink = f"double licence {sum(len(g['variantes']) for g in dl['mentions'])} -> {len(dl['mentions'])}" if dl else "no double licence"
    return not bad, f"{len(fac['diplomes'])} diplomas; {shrink}; problems {bad[:4]}"


# ------------------------------------------------------------------ CR3
@check("CR3 French alphabetical order of diplomas and mention groups (accents and case ignored)")
def cr3(c: Ctx):
    fac = CA.facets(c.con)
    labels = [d["label"] for d in fac["diplomes"]]
    bad = [] if labels == sorted(labels, key=fold) else ["diplomas"]
    bad += [d["label"] for d in fac["diplomes"] if [g["label"] for g in d["mentions"]] != sorted((g["label"] for g in d["mentions"]), key=fold)]
    acc = [x for x in labels if fold(x)[:1] == "e" and x[:1] in "ÉÈ"]
    if c.real and acc and not all(labels.index(x) < labels.index("Formation professionnelle") for x in acc if "Formation professionnelle" in labels):
        bad.append(("accented after F", acc))
    return not bad, f"{len(labels)} diplomas in order; accented labels {acc[:3]}; problems {bad[:3]}"


# ------------------------------------------------------------------ CR4
@check("CR4 selection: API group filter = the group's formations; page carteSelection / carteKeep / carteHash (Node)")
def cr4(c: Ctx):
    fac = CA.facets(c.con)
    bad = []
    for d in fac["diplomes"]:
        if d["label"] not in ("Double licence", "CPES", "CUPGE", "BUT"):
            continue
        allf = CA.formations(c.con, d["label"])["formations"]
        for g in d["mentions"][:6]:
            sub = CA.formations(c.con, d["label"], g["label"])["formations"]
            want = sorted(f["cod_aff_form"] for f in allf if f["groupe"] == g["label"])
            if sorted(f["cod_aff_form"] for f in sub) != want or len(want) != g["n"]:
                bad.append((d["label"], g["label"]))
    small = {"diplomes": [{"label": d["label"], "n": d["n"], "mentions": [{"label": g["label"], "variantes": g["variantes"]} for g in d["mentions"]]}
                          for d in fac["diplomes"]]}
    dl = next((d for d in fac["diplomes"] if d["label"] == "Double licence"), fac["diplomes"][0])
    g0 = dl["mentions"][0]
    cases = [{"fn": "carteSelection", "args": [small, dl["label"], g0["variantes"][-1], None]},           # an old link: a raw label
             {"fn": "carteSelection", "args": [small, "", "", {"d": ["<img>", dl["label"]], "m": {dl["label"]: ["x", g0["label"]]}}]},
             {"fn": "carteSelection", "args": [small, "", "", {"d": "BUT"}]},
             {"fn": "carteSelection", "args": [small, "", "", None]},
             {"fn": "carteHash", "args": [{"d": [dl["label"]], "m": {dl["label"]: [g0["label"]]}}]},
             {"fn": "carteHash", "args": [{"d": [dl["label"], "BUT"], "m": {}}]},
             {"fn": "carteKeep", "args": [{"diplome": dl["label"], "groupe": g0["label"]}, {"d": [dl["label"]], "m": {dl["label"]: [g0["label"]]}}]},
             {"fn": "carteKeep", "args": [{"diplome": dl["label"], "groupe": "autre"}, {"d": [dl["label"]], "m": {dl["label"]: [g0["label"]]}}]},
             {"fn": "carteKeep", "args": [{"diplome": "BUT", "groupe": "x"}, {"d": [dl["label"], "BUT"], "m": {dl["label"]: [g0["label"]]}}]},
             {"fn": "carteKeep", "args": [{"diplome": "CPES", "groupe": "x"}, {"d": [dl["label"]], "m": {}}]},
             {"fn": "carteKeep", "args": [{"diplome": "CPES", "groupe": "x"}, {"d": [], "m": {}}]}]
    out = node(c.js, cases)
    if out is None:
        return not bad, f"node not installed; API problems {bad[:3]}"
    want = [{"d": [dl["label"]], "m": {dl["label"]: [g0["label"]]}}, {"d": [dl["label"]], "m": {dl["label"]: [g0["label"]]}},
            {"d": [], "m": {}}, {"d": [], "m": {}}, None, "#/carte", True, False, True, False, True]   # R10: nothing ticked = all
    page = []
    for k, (o, w) in enumerate(zip(out, want)):
        if k == 4:
            ok = isinstance(o, str) and o.startswith("#/carte/") and o.count("/") == 3
        else:
            ok = o == w
        if not ok:
            page.append((cases[k]["fn"], o))
    return not bad and not page, f"API group filter problems {bad[:3]}; page problems {page[:3]}"


# ------------------------------------------------------------------ CR5
@check("CR5 figures = Mes vœux: /api/carte/chiffres = voeux.figures; bac techno/pro line picked by the page = Mes vœux's; 40 codes max")
def cr5(c: Ctx):
    from fastapi.testclient import TestClient
    from suptracker import api, cache
    dk = J.doublette_key("MATHS", "NSI")
    lay = CA.formations(c.con, "Licence", None) or CA.formations(c.con, CA.facets(c.con)["diplomes"][0]["label"])
    cods = [f["cod_aff_form"] for f in lay["formations"] if f.get("stats") is not False][:40]
    bad = []
    got = CA.chiffres(c.con, cods, "bg", dk)["chiffres"]
    for k in range(0, len(cods), 10):
        for v in V.evaluate(c.con, cods[k:k + 10], serie="bg", dkey=dk, mention="b")["voeux"]:
            if v["status"] == "ok" and {x: v[x] for x in ("doublette", "rapport", "semblable")} != got.get(v["cod_aff_form"]):
                bad.append((v["cod_aff_form"], "bg figure"))
    # bac techno: the page picks the line among the report's lines; Mes vœux picks it on the server
    rp = c.con.execute("SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE bac = 'bt' LIMIT 12").fetchall() \
        if c.con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'rapport_doublette'").fetchone()[0] else []
    tcods = [r[0] for r in rp if r[0] in {x[0] for x in c.con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ?", [c.latest]).fetchall()}][:10]
    cases, want = [], []
    if tcods:
        bt = CA.chiffres(c.con, tcods, "bt", None)["chiffres"]
        keys = sorted({x["voie"] for cd in tcods for x in ((bt[cd].get("voies") or {}).get("doublettes", {}).get("bt") or []) if x.get("voie")})[:4] + ["autre"]
        for key in keys:
            ev = {v["cod_aff_form"]: v for v in V.evaluate(c.con, tcods, serie="bt", mention="ab", voie=key)["voeux"]}
            for cd in tcods:
                block = bt[cd].get("voies")
                cases.append({"fn": "pickVoie", "args": [block, "bt", key]})
                want.append((cd, key, block, (ev[cd].get("rapport") if ev[cd]["status"] == "ok" else None)))
    out = node(c.js, cases) if cases else []
    if out is None:
        out = []
    for o, (cd, key, block, w) in zip(out, want):
        mine = None if not o else {"session": block["session"], "source": o["source"], "taux": o["taux"], "confirmes": o["confirmes"],
                                   "en_position": o["en_position"], "recoupe": block["recoupe"], "libelle": o["libelle"]}
        if mine != w:
            bad.append((cd, key, "bt line"))
    for wrong in ([str(i) for i in range(41)], ["12a"]):
        try:
            CA.chiffres(c.con, wrong, "bg", dk)
            bad.append(("accepted", len(wrong)))
        except ValueError:
            pass
    cl = TestClient(api.app)
    r = cl.get("/api/carte/chiffres", params={"codes": ",".join(cods[:3]), "spe1": "MATHS", "spe2": "NSI"})
    r422 = cl.get("/api/carte/chiffres", params={"codes": ",".join(str(i) for i in range(41)), "spe1": "MATHS", "spe2": "NSI"}).status_code
    pol = cache.policy("/api/carte/chiffres")
    sig = "voie" not in api.carte_chiffres.__code__.co_varnames and "moyenne" not in api.carte_chiffres.__code__.co_varnames
    call = re.search(r"api\(`/api/carte/chiffres\?([^`]*)`\)", c.js)
    sent = call and "voie" not in call.group(1) and "moyenne" not in call.group(1)
    ok = not bad and r.status_code == 200 and r422 == 422 and sig and bool(sent) and pol is not None and pol[0] == cache.PUBLIC
    return ok, (f"{len(cods)} bac général figures, {len(want)} bac techno lines; problems {bad[:3]}; API {r.status_code}/{r422}; "
                f"no series line or average in the endpoint {sig}, nor in the page's call {bool(sent)}; cache {pol}")


# ------------------------------------------------------------------ CR6
@check("CR6 position: page cartePosition (Node) = server stage 2 `position` with the average; without one, the band's published bounds")
def cr6(c: Ctx):
    dk = J.doublette_key("MATHS", "SES")
    rows = untyped(c.con, c.latest)
    typed = c.con.execute("""SELECT t.cod_aff_form, r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        WHERE t.session = ? ORDER BY hash(t.cod_aff_form) LIMIT 30""", [c.latest]).fetchall()
    sets = [(J.SANS_TYPE, [r[0] for r in rows[:30]])] if rows else []
    for tk in {t for _, t in typed}:
        sets.append((tk, [cd for cd, t in typed if t == tk]))
    cases, want = [], []
    for band, g in (("b", 14.6), ("ab", 12.1), ("tb", 17.9), ("sansmention", 11.2)):
        for tk, cods in sets:
            if not cods:
                continue
            plain = {f["cod_aff_form"]: f for f in J.stage2(c.con, dk, band, tk, only=cods)["formations"]}
            oracle = {f["cod_aff_form"]: f for f in J.stage2(c.con, dk, band, tk, only=cods, moyenne=g)["formations"]}
            for cd, f in plain.items():
                cases.append({"fn": "cartePosition", "args": [f["lec"], f["taux_acces_ens"], band, g]})
                p = oracle[cd]["position"]
                want.append(None if not p else (min(p["normale"], p["uniforme"]), max(p["normale"], p["uniforme"]), True))
                cases.append({"fn": "cartePosition", "args": [f["lec"], f["taux_acces_ens"], band, None]})
                want.append(None if not p else (p["bornes"][0], p["bornes"][1], False))
    out = node(c.js, cases)
    if out is None:
        return True, "node not installed"
    bad = []
    for o, w in zip(out, want):
        if isinstance(o, dict) and "__error__" in o:
            bad.append(o["__error__"][:120])
        elif (o is None) != (w is None) or (o and (abs(o["lo"] - w[0]) > 1e-9 or abs(o["hi"] - w[1]) > 1e-9 or o["moyenne"] != w[2])):
            bad.append((o, w))
    return len(want) > 0 and not bad, f"{len(want)} positions compared with the server's reading; differing {bad[:3]}"


# ------------------------------------------------------------------ CR7
def section(js: str) -> str:
    return js[js.index("// R9 (owner, 2026-11-12): three figures per formation"): js.index("\n// ---- lot 2 (Claude design guidelines)")]


@check("CR7 wording: no chance or access rate for the average; estimation and 'no access rate by average' said; three figures; vouvoiement")
def cr7(c: Ctx):
    sec = section(c.js)
    texts = [t for t in re.findall(r"`[^`]*`|\"[^\"]*\"", sec)]
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    pos = sec[sec.index("function cartePosFigure("): sec.index("\n}", sec.index("function cartePosFigure("))]
    pos_ok = "estimation" in pos and "taux d'accès" not in pos.lower() and "chance" not in pos.lower()
    labels = all(x in sec for x in ("Taux d'accès ${esc(ctx.session)}", '"Votre doublette"', '"Votre moyenne parmi les admis"', '"Votre mention parmi les admis"'))
    footnote = "aucun taux d'accès par moyenne n'est publié" in sec and "pas une chance d'admission" in sec and "jamais par chances" in sec
    official = "officiel" in sec and "dblFigure(ch)" in sec and "voieFigure(" in sec and "pickVoie(ch.voies" in sec
    # Codex: the chosen formation's figures are asked whatever chose it (a map marker can be on no loaded page of the list)
    show = sec[sec.index("function showSel(fromMap) {"): sec.index("\n  }", sec.index("function showSel(fromMap) {"))]
    picked = "if (f) figures([f]);" in show and "focus && f) figures" not in show
    ok = not chance and not tu and pos_ok and labels and footnote and official and picked
    return ok, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; position wording {pos_ok}; three labelled figures {labels}; footnote {footnote}; sources {official}; chosen formation's figures asked {picked}"


# ------------------------------------------------------------------ CR8
BROWSER = r"""
const { chromium } = require('playwright');
const base = process.argv[2];
(async () => {
  const b = await chromium.launch(); const o = { errs: [], layout: null, phone: [], multi: null };
  const prof = () => { localStorage.setItem("profile", JSON.stringify({ serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b", moyenne: 14.6, statut: "terminale" }));
    localStorage.setItem("carteSel", JSON.stringify({ d: ["CPES", "Double licence"], m: {} })); };
  const ctx = await b.newContext({ viewport: { width: 1440, height: 950 } }); await ctx.addInitScript(prof);
  const p = await ctx.newPage(); p.on("pageerror", (e) => o.errs.push(e.message));
  await p.route(/tile\.openstreetmap\.org/, (r) => r.abort());
  await p.goto(base + "/#/carte"); await p.waitForTimeout(5000);
  o.layout = await p.evaluate(() => { const x = (s) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().left : null; };
    const m = document.getElementById("carte-osm").getBoundingClientRect();
    return { mapSeen: Math.round(innerHeight - m.top), side: x(".carte-side"), map: x("#carte-osm"), list: x(".carte-results"), mapcol: x(".carte-mapcol"),
      cpes: [...document.querySelectorAll('.carte-rc[data-rdip="CPES"]')].map((e) => e.classList.contains("rc-z")),
      dips: [...document.querySelectorAll("[data-dip]:checked")].map((e) => e.dataset.dip),
      figs: [...document.querySelectorAll(".carte-results .carte-rc")].filter((e) => !/apprentissage/.test(e.querySelector(".rc-badges").innerText)).every((e) => e.querySelector(".cofficiel") && e.querySelectorAll(".cbacs li").length === 3 && e.querySelectorAll(".cfigs .cf").length === 2 && e.querySelector("[data-cmp]")) }; });
  // tick one mention group of Double licence: only that group stays among the double licences
  const box = await p.$('[data-mdip="Double licence"]');
  if (box) { const label = await box.getAttribute("data-men"); await box.check(); await p.waitForTimeout(1500);
    o.multi = await p.evaluate((l) => ({ label: l, dips: [...new Set([...document.querySelectorAll(".carte-rc")].map((e) => e.dataset.rdip))],
      off: [...document.querySelectorAll('.carte-rc[data-rdip="Double licence"]')].filter((e) => e.dataset.groupe !== l).length, hash: location.hash }), label); }
  await ctx.close();
  for (const w of [390, 320]) {
    const c2 = await b.newContext({ viewport: { width: w, height: 800 } }); await c2.addInitScript(prof);
    const q = await c2.newPage(); q.on("pageerror", (e) => o.errs.push(e.message)); await q.route(/tile\.openstreetmap\.org/, (r) => r.abort());
    await q.goto(base + "/#/carte"); await q.waitForTimeout(4000);
    o.phone.push([w, await q.evaluate(() => document.documentElement.scrollWidth)]); await c2.close();
  }
  process.stdout.write(JSON.stringify(o)); await b.close();
})();
"""


@check("CR8 browser: three columns in order, phone without horizontal scroll, multi-select and mention filter, CPES placed, 0 JS errors")
def cr8(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or subprocess.run([exe, "-e", "require('playwright')"], capture_output=True).returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".carterecherche_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    o = json.loads(r.stdout)
    L = o["layout"] or {}
    # R10 (owner): filters on the left, the list in the middle, the map on the right
    order = None not in (L.get("side"), L.get("list"), L.get("mapcol")) and L["side"] < L["list"] < L["mapcol"] and L.get("map") is not None and L["map"] >= L["mapcol"] - 1
    phone = all(w2 <= w for w, w2 in o["phone"])
    m = o.get("multi") or {}
    multi = L.get("dips") == ["CPES", "Double licence"] and (not c.real or (bool(m) and m.get("off") == 0 and "CPES" in (m.get("dips") or [])))
    cp = L.get("cpes") or []                     # CPES placed in a zone (the edge of its zone; "indéterminé" has none)
    cpes = not c.real or (len(cp) > 0 and sum(cp) >= 0.8 * len(cp))
    figs = L.get("figs") is True
    seen = (L.get("mapSeen") or 0) >= 250          # owner (2026-11-12): "je ne vois pas la carte": it shows on the first screen
    ok = order and phone and multi and cpes and figs and seen and not o["errs"]
    return ok, f"map on the first screen {seen} ({L.get('mapSeen')} px); columns in order {order} {L and {k: L.get(k) for k in ('side', 'map', 'list', 'detail')}}; phone {o['phone']}; multi {multi} {m.get('hash')}; CPES zoned {cpes} ({sum(cp)}/{len(cp)}); 3 figures per card {figs}; errors {o['errs'][:2]}"


# ------------------------------------------------------------------ CR11-CR13 (sprint R10, owner 2026-11-13)
SHORT = {"MATHS": "Maths", "PC": "Physique-chimie", "SVT": "SVT", "SES": "SES", "HGGSP": "HGGSP", "LLCER": "LLCER", "HLP": "HLP",
         "NSI": "NSI", "SI": "SI", "LLCA": "LLCA", "EPPCS": "EPPCS", "ART": "Arts", "BIOECO": "Biologie-écologie"}


@check("CR11 rate per bac and most represented line among the admits, re-derived from the report tables and SIES counts")
def cr11(c: Ctx):
    from suptracker import voies as VO
    got = CA.bac_lines(c.con)
    L = c.latest
    rep = {}
    for cod, bac, lib, dkey, autres, conf, pos, acc in c.con.execute("""
            SELECT d.cod_aff_form, d.bac, d.libelle, d.doublette_key, d.autres, d.confirmes, d.en_position, d.acceptes
            FROM core.rapport_doublette d JOIN core.rapport r USING (cod_aff_form, session) WHERE d.session = ? AND r.recoupe""", [L]).fetchall():
        rep.setdefault(cod, {}).setdefault(bac, []).append((lib, dkey, autres, conf or 0, pos or 0, acc or 0))
    # a cross-checked report exists apart from its detail rows (every table masked: still "non publié", never an estimation; Codex)
    reports = {r for (r,) in c.con.execute("SELECT cod_aff_form FROM core.rapport WHERE session = ? AND recoupe", [L]).fetchall()}
    masked = set(c.con.execute("""SELECT m.cod_aff_form, m.bac FROM core.rapport_masque m JOIN core.rapport r USING (cod_aff_form, session)
                                  WHERE m.session = ? AND r.recoupe""", [L]).fetchall())
    n_nodetail = len({cod for cod in reports if cod not in rep})
    sies = {r[0]: r[1:] for r in c.con.execute(f"""SELECT fy.cod_aff_form, fy.acc_bg, fy.acc_bt, fy.acc_bp,
        {J.series_access_sql('bg')}, {J.series_candidates_sql('bg')}, {J.series_access_sql('bt')}, {J.series_candidates_sql('bt')},
        {J.series_access_sql('bp')}, {J.series_candidates_sql('bp')} FROM core.formation_year fy WHERE fy.session = ?""", [L]).fetchall()}
    bad, n_rep, n_est, n_majo = [], 0, 0, 0
    for cod, (abg, abt, abp, ebg, nbg, ebt, nbt, ebp, nbp) in sies.items():
        g = got.get(cod)
        if g is None:
            bad.append((cod, "missing"))
            continue
        mine = rep.get(cod, {}) if cod in reports else None
        for b, e, n in (("bg", ebg, nbg), ("bt", ebt, nbt), ("bp", ebp, nbp)):
            x = g["bacs"][b]
            if mine is not None:
                n_rep += 1
                if (cod, b) in masked:
                    want = None
                else:
                    lines = mine.get(b) or []
                    cf = sum(t[3] for t in lines)
                    want = round(100 * sum(t[4] for t in lines) / cf, 1) if cf else None
                if x["taux"] != want or x["source"] != "rapport" or bool(x.get("masque")) != ((cod, b) in masked):
                    bad.append((cod, b, "report rate", x, want))
            else:
                n_est += 1
                want = None if e is None or not n else round(min(100.0, e), 1)
                if x["taux"] != want or x["source"] != "estimation" or (x["taux"] is not None and x["taux"] > 100) or x["fragile"] != ((n or 0) < 20):
                    bad.append((cod, b, "estimation", x, want))
        a = {"bg": abg or 0, "bt": abt or 0, "bp": abp or 0}
        top = max(a.values())
        route = [b for b in a if a[b] == top]
        want = None
        if top > 0 and len(route) == 1 and mine is not None and (cod, route[0]) not in masked:
            lines = [t for t in (mine.get(route[0]) or []) if not t[2] and t[5] > 0]
            if lines:
                best = max(t[5] for t in lines)
                win = [t for t in lines if t[5] == best]
                lib, dkey = win[0][0], win[0][1]
                if route[0] == "bg" and dkey and all(p in SHORT for p in dkey.split("+")):
                    lab = " & ".join(SHORT[p] for p in dkey.split("+"))
                elif route[0] == "bt" and VO.voie_key("bt", lib) in VO.BT_NAME:
                    lab = " · ".join(VO.BT_NAME[VO.voie_key("bt", lib)])
                else:
                    lab = None                  # printed label: compared loosely below
                want = (route[0], best, len(win) > 1, lab)
        m = g["majo"]
        if (m is None) != (want is None) or (m and (m["bac"], m["acceptes"], m["exaequo"]) != want[:3]) or (m and want[3] and m["libelle"] != want[3]):
            bad.append((cod, "majo", m, want))
        n_majo += m is not None
    return n_rep > 0 and not bad, (f"{len(sies)} formations; {n_rep} report rates ({n_nodetail} reports print no line), {n_est} estimations, "
                                   f"{n_majo} lines; differing {bad[:3]}")


CARD_TWINS = ("esc", "fmt", "pct", "pct1", "STATUT_LABEL", "carteBacs", "carteMajo", "compareButton", "carteSortName")


@check("CR12 the card (Node): statut and selectivity said, rate per bac (masked = non publié, estimation starred and named), the line, compare button")
def cr12(c: Ctx):
    exe = shutil.which("node")
    if not exe:
        return True, "node not installed"
    try:
        lib = "\n".join(RL.top(c.js, n) for n in CARD_TWINS)
    except KeyError as e:
        return False, f"missing definition {e}"
    prog = lib + r"""
const store = new Map(); const basket = { get: () => store.get("b") || [] };
const f = { statut: "prive", bacs: { bg: { taux: 42.5, source: "rapport" }, bt: { taux: null, source: "rapport", masque: true }, bp: { taux: 88, source: "estimation", fragile: true } },
  majo: { bac: "bt", libelle: "STMG · Mercatique <img>", exaequo: true } };
const out = { bacs: carteBacs(f), majo: carteMajo(f), none: carteMajo({}), statut: STATUT_LABEL[f.statut], cmp0: compareButton("12") };
store.set("b", ["12"]); out.cmp1 = compareButton("12"); store.set("b", ["1", "2", "3", "4", "5", "6"]); out.cmp2 = compareButton("12");
out.sort = ["(CFA b)", "Alpha", "« Zeta »"].map((e) => ({ etablissement: e })).sort((a, b) => carteSortName(a).localeCompare(carteSortName(b), "fr")).map((x) => x.etablissement);
process.stdout.write(JSON.stringify(out));"""
    r = subprocess.run([exe, "-e", prog], capture_output=True, text=True, timeout=60)
    if r.returncode:
        return False, r.stderr[-300:]
    o = json.loads(r.stdout)
    sec = section(c.js)
    card = sec[sec.index("function carteCard("): sec.index("\nfunction carteList(")]
    checks = {
        "bac général 42,5 %": "Bac général</span> <strong>42,5 %" in o["bacs"],
        "masked = non publié": "Bac techno</span> <strong><span class=\"muted\">non publié" in o["bacs"],
        "estimation starred and named": "88" in o["bacs"] and "(estimation)" in o["bacs"] and "*" in o["bacs"] and "peu de candidats" in o["bacs"],
        "line escaped, route and ex aequo": "&lt;img&gt;" in o["majo"] and "bac techno" in o["majo"] and "ex æquo" in o["majo"] and o["none"] == "",
        "statut words": o["statut"] == "Privé hors contrat (payant)",
        "compare states": "Comparer" in o["cmp0"] and "aria-pressed=\"false\"" in o["cmp0"] and "Retirer du comparateur" in o["cmp1"] and "disabled" in o["cmp2"],
        "sort ignores punctuation": o["sort"] == ["Alpha", "(CFA b)", "« Zeta »"],
        "card shows statut, selectivity, rates, line, actions": all(x in card for x in ("STATUT_LABEL[f.statut]", "Sélective", "Non sélective", "carteBacs(f)", "carteMajo(f)", "compareButton(f.cod_aff_form)", "voeuButton(f.cod_aff_form)")),
        "compare wired": "basket.toggle(b.dataset.cmp)" in sec,
        "footnote says both sources": "rapport du jury de la formation (candidats de terminale en France)" in sec and "* = pas de rapport, accès estimé" in sec,
    }
    bad = [k for k, v in checks.items() if not v]
    return not bad, f"problems {bad}"


@check("CR13 nothing ticked = everything (diplomas and every other group), the list first and the zones after, never sorted by a figure")
def cr13(c: Ctx):
    sec = section(c.js)
    view = c.js[c.js.index("async function viewCarte("): c.js.index("\n// ---- lot 2 (Claude design guidelines)")]
    checks = {
        # sprint Q3: the layer is one answer (all diplomas), the ticked ones kept in the browser; nothing ticked = all
        "every diploma when none ticked": "const tous = !sel.d.length;" in view and "const dips = tous ? FAC.diplomes.map((d) => d.label) : sel.d;" in view
                                          and "carteMerge(tous ? C.rows : C.rows.filter((f) => keep.has(f.diplome)), null, ok)" in view,
        "unticking every diploma allowed": "at least one type of diploma" not in view and "data-clear-dips" in view,
        "a group's clear button": "data-clear=" in view and "F[b.dataset.clear] = [];" in view,
        "selectivity group named": '["select", "Sélectivité",' in c.js,
        "zones after the list": "const zonesP = coucheP.then(" in view and "zonesReady" in view,
        "sort: stats first then name": "(a.stats === false) - (b.stats === false)" in view and "carteSortName(a).localeCompare(carteSortName(b), \"fr\")" in view,
        "no figure in the sort": not re.search(r"\.sort\(\(a, b\) => [^\n]*(taux|zone|position)", view),
        "keep all with nothing ticked": "!sel.d.length ||" in sec,
        # cards a saved zone filter reveals only once the zones arrive need their figures (Codex): that redraw fetches, the
        # figures' own redraw never does (no request loop), and a pending or known code is never asked twice
        "figures after the zones": bool(re.search(r"if \(applyZones\(zs\)\)[^\n]*\n\s*panel\(\); draw\(\);", view)),
        "no figures loop": "if (seq === carteUI.seq && $view.dataset.rendered === \"carte\") { draw(false); }" in view
                           and "!ctx.chiffres.has(f.cod_aff_form)" in view,
    }
    bad = [k for k, v in checks.items() if not v]
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ CR9
def py_mutants():
    import suptracker.carte as C
    import suptracker.voeux as VX
    from suptracker import journey as JJ
    orig = {"lines": C.bac_lines, "groupe_of": C.groupe_of, "sort_key": C.sort_key, "zones": C.zones, "figures": VX.figures, "untyped": JJ.untyped_codes,
            "dl": dict(C.DL_DISCIPLINE), "chmax": C.CHIFFRES_MAX}

    def restore():
        C.groupe_of, C.sort_key, C.zones, VX.figures, JJ.untyped_codes = orig["groupe_of"], orig["sort_key"], orig["zones"], orig["figures"], orig["untyped"]
        C.bac_lines = orig["lines"]
        C.DL_DISCIPLINE.clear(); C.DL_DISCIPLINE.update(orig["dl"]); C.CHIFFRES_MAX = orig["chmax"]

    def ordered_pair(d, m):                         # double licence pair kept in the printed order
        if d == "Double licence" and "/" in m:
            return " / ".join(p.strip() for p in m.split(" - ")[0].split("/")[:2])
        return orig["groupe_of"](d, m)

    def zones_typed_only(con, diplome, mention, dkey, mb, serie, moyenne=None, lecture=False):
        out = orig["zones"](con, diplome, mention, dkey, mb, serie, moyenne, lecture)
        un = set(JJ.untyped_codes(con))
        return {**out, "zones": {k: v for k, v in out["zones"].items() if k not in un}}

    def lines_mut(kind):
        def f(con):
            out = {}
            for k, v in orig["lines"](con).items():
                v = json.loads(json.dumps(v))
                for b, x in v["bacs"].items():
                    if kind == "masked0" and x.get("masque"):
                        x["taux"] = 0.0
                    if kind == "uncapped" and x["source"] == "estimation" and x["taux"] is not None:
                        x["taux"] = round(x["taux"] * 1.5, 1)
                if kind == "nodetail" and all(x["source"] == "rapport" and not x.get("n") for x in v["bacs"].values()):
                    v["bacs"] = {b: {"taux": 50.0, "source": "estimation", "n": 30, "fragile": False} for b in v["bacs"]}
                if v["majo"] and kind == "noexaequo":
                    v["majo"]["exaequo"] = False
                if v["majo"] and kind == "route":
                    v["majo"]["bac"] = "bg"
                out[k] = v
            return out
        return f

    def other_figures(con, cods, types, *, serie="bg", dkey=None, voie=None):   # the map reads another figure than Mes vœux
        f = orig["figures"](con, cods, types, serie=serie, dkey=dkey, voie=voie)
        return {k: {**v, "rapport": None, "semblable": None} for k, v in f.items()}

    return [
        ("double licence pair ordered", lambda: setattr(C, "groupe_of", ordered_pair), {"CR2"}),
        ("Gestion merged with Économie", lambda: C.DL_DISCIPLINE.update({"gestion": "Économie"}), {"CR2"}),
        ("order keeps accents", lambda: setattr(C, "sort_key", lambda x: x.lower()), {"CR3"}),
        ("untyped formations left without a zone", lambda: setattr(C, "zones", zones_typed_only), {"CR1"}),
        ("the map's figure is not Mes vœux's", lambda: setattr(VX, "figures", other_figures), {"CR5"}),
        ("no limit on the codes", lambda: setattr(C, "CHIFFRES_MAX", 10 ** 6), {"CR5"}),
        ("a masked bac table shown as 0 %", lambda: setattr(C, "bac_lines", lines_mut("masked0")), {"CR11"}),
        ("a report printing no line (tables masked) read as no report", lambda: setattr(C, "bac_lines", lines_mut("nodetail")), {"CR11"}),
        ("estimation not capped at 100", lambda: setattr(C, "bac_lines", lines_mut("uncapped")), {"CR11"}),
        ("ex aequo never said", lambda: setattr(C, "bac_lines", lines_mut("noexaequo")), {"CR11"}),
        ("line of another route than the majority", lambda: setattr(C, "bac_lines", lines_mut("route")), {"CR11"}),
    ], restore


JS_MUTANTS = [
    ("bounds swapped without an average", "return { lo: (L.kt - L.kb) / L.n, hi: L.kt / L.n, moyenne: false };", "return { lo: L.kt / L.n, hi: (L.kt - L.kb) / L.n, moyenne: false };", "CR6"),
    ("one hypothesis only", "lo: Math.min(p.normale, p.uniforme), hi: Math.max(p.normale, p.uniforme)", "lo: p.normale, hi: p.normale", "CR6"),
    ("mention filter ignored", "(!(sel.m[f.diplome] || []).length || sel.m[f.diplome].includes(f.groupe))", "true", "CR4"),
    ("stored diploma trusted", "(stored && Array.isArray(stored.d) ? stored.d : []).filter((x) => typeof x === \"string\" && known(x))", "(stored && Array.isArray(stored.d) ? stored.d : [])", "CR4"),
    ("series line sent to the server", "api(`/api/carte/chiffres?codes=${want.join(\",\")}&${sq}`)", "api(`/api/carte/chiffres?codes=${want.join(\",\")}&${sq}&voie=${encodeURIComponent(ctx.prof.voie || \"\")}`)", "CR5"),
    ("position called a chance", "des admis sous votre moyenne\" : \"des admis sous ou à votre mention\"} · estimation", "chances d'être admis\" : \"des admis sous ou à votre mention\"} · estimation", "CR7"),
    ("footnote without the caveat", "aucun taux d'accès par moyenne n'est publié", "", "CR7"),
    ("doublette figure not Mes vœux's", "ctx.serie === \"bg\" ? dblFigure(ch)", "ctx.serie === \"bg\" ? pct(ch.taux)", "CR7"),
    ("marker choice never asks its figures (Codex)", "    if (f) figures([f]);", "    if (focus && f) figures([f]);", "CR7"),
    ("masked table shown as a dash", "x.masque ? '<span class=\"muted\">non publié</span>'", "x.masque ? '<span class=\"muted\">—</span>'", "CR12"),
    ("estimation not named", "'<span class=\"sr-only\"> (estimation)</span>'", "''", "CR12"),
    ("compare button never wired", "basket.toggle(b.dataset.cmp); draw(false);", "draw(false);", "CR12"),
    ("payant not said", 'prive: "Privé hors contrat (payant)"', 'prive: "Privé"', "CR12"),
    ("one diploma when none ticked", "carteMerge(tous ? C.rows : C.rows.filter((f) => keep.has(f.diplome)), null, ok)", "carteMerge(C.rows.filter((f) => f.diplome === dips[0]), null, ok)", "CR13"),
    ("cards revealed by the zones never get their figures", "panel(); draw();          // a saved zone filter", "panel(); draw(false);          // a saved zone filter", "CR13"),
    ("figures asked again for every redraw", "!ctx.chiffres.has(f.cod_aff_form)", "true", "CR13"),
    ("sorted by the access rate", "|| carteSortName(a).localeCompare(carteSortName(b), \"fr\"));", "|| (b.taux_acces_ens || 0) - (a.taux_acces_ens || 0));", "CR13"),
]


@check("CR9 mutation test: Python and page mutants are each caught")
def cr9(c: Ctx):
    missed = []
    fns = {fn.check_name.split()[0]: fn for fn in CHECKS}
    muts, restore = py_mutants()
    for name, apply, want in muts:
        try:
            apply()
            caught = any(not fns[k](c)[0] for k in want)
        except Exception:  # noqa: BLE001 - a crash is a catch
            caught = True
        finally:
            restore()
        if not caught:
            missed.append(name)
    js0 = c.js
    for name, old, new, k in JS_MUTANTS:
        if old not in js0:
            missed.append(name + " (anchor)")
            continue
        c.js = js0.replace(old, new, 1)
        try:
            caught = not fns[k](c)[0]
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            c.js = js0
        if not caught:
            missed.append(name)
    n = len(muts) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught; missed {missed}"


@check("CR10 docs: README section and CLAUDE.md rule")
def cr10(c: Ctx):
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
    a = "Sprint R9" in readme and "redteam_carterecherche.py" in readme
    b = "redteam_carterecherche.py" in claude and "SANS_TYPE" in claude
    return a and b, f"README {a}, CLAUDE.md {b}"


def run(db: Path, real: bool = False, browser: bool | None = None) -> list[dict]:
    c = Ctx(db, real, real if browser is None else browser)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real, a.browser or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
