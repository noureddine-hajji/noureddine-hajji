"""Red team of the BUT cleanup (owner, 2026-11-21): a BUT is classed by its SPECIALTY, the parcours an apprenticeship offer opens
are listed apart, the offer is attached to the IUT's initial formation of that specialty, and SIES's parcours-split specialties
are grouped under their specialty in the mention filter (carte.but_specialite, carte.groupe_of, app.js appParcours).

    python scripts/redteam_but.py [--db data/suptracker.duckdb] [--real]

  BU1 the rule, on hostile labels: an independent reading (own split, own normalisation) equals carte.but_specialite: every item
      « BUT - <name> », exactly one SIES specialty, the others its parcours in order (a comma inside a parcours name kept);
      no specialty, two specialties, an item of another diploma, an empty label: None.
  BU2 a crafted warehouse: each offer's diploma, mention, parcours and attached formations equal a table written by hand
      (same UAI and same specialty attaches; another IUT, two specialties, SIES's own apprenticeship rows do not).
  BU3 --real: every BUT apprenticeship offer of the latest cartographie re-derived; none keeps a « BUT - … » list as its mention;
      none stays apart while its IUT has an initial formation of its specialty; the owner's two examples (Auxerre 10802, Aix 2710);
      the parcours travel to the initial formation's page (carte.for_formation).
  BU4 the mention filter: a SIES specialty named with its parcours (« Carrières sociales Parcours … », any case) is grouped under
      the specialty, every other BUT mention is its own group; no BUT group names a parcours; every variant in exactly one group.
  BU5 the page (Node): the parcours quoted (« … ») and escaped, on the attached CFA lines (search card and formation page) and on
      an offer listed apart; nothing when an offer has no parcours.
  BU6 docs and wiring: README, CLAUDE.md, durations.json, the test file.
  BU7 mutation test of BU1-BU6 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import duckdb
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
TC, GEA = "Techniques de commercialisation", "Gestion des entreprises et des administrations"
CS = "Carrières sociales Parcours animation sociale et socioculturelle"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_rt")
    m.__package__ = "suptracker"
    m.__file__ = str(ROOT / "suptracker" / f"{name}.py")
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real and self.db is not None
        self.src = {"carte": (ROOT / "suptracker" / "carte.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self):
        return load("carte", self.src["carte"])


# ------------------------------------------------------------------ BU1 the rule
def rt_but(label, names) -> tuple | None:
    """Independent: items cut where « ,BUT - » starts a new one; each must open with « BUT - »; one SIES specialty."""
    label = label or ""
    if not label.startswith("BUT - "):
        return None
    items, cur = [], ""
    for chunk in label.split(","):
        if chunk.startswith("BUT - ") and cur:
            items.append(cur)
            cur = chunk
        else:
            cur = chunk if not cur else cur + "," + chunk
    items.append(cur)
    if not all(x.startswith("BUT - ") for x in items):
        return None
    names_i = [re.sub(r"\s+", " ", x[6:]).strip() for x in items]
    hit = [x for x in names_i if x in names]
    if len(hit) != 1:
        return None
    return hit[0], [x for x in names_i if x != hit[0]]


LABELS = [
    f"BUT - Marketing digital, e-business et entrepreneuriat,BUT - {TC}",
    f"BUT - Contrôle de gestion et pilotage de la performance,BUT - Gestion et pilotage des ressources humaines,BUT - {GEA}",
    f"BUT - {TC}", f"BUT - {CS}", f"BUT - {TC},BUT - {GEA}", "BUT - Cybersécurité,BUT - Développement Système et Cloud",
    "BUT - Cybersécurité,BTS - Comptabilité et gestion", "", None, f"BTS - {TC}", f"BUT -  Optimisation  énergétique,BUT -  {TC}",
    f"{TC}", f"BUT - {HOSTILE},BUT - {TC}", f"BUT - {TC}, option X", f"BUT - P1,,BUT - {TC}",
]


@check("BU1 the rule on hostile labels: an independent reading equals carte.but_specialite (one specialty, parcours in order)")
def bu1(c: Ctx):
    CA = c.mod()
    names = {TC, GEA, CS}
    bad = []
    for lab in LABELS:
        got, want = CA.but_specialite(lab, names), rt_but(lab, names)
        if (got if got is None else (got[0], list(got[1]))) != want:
            bad.append((lab, got, want))
    fixed = {LABELS[0]: (TC, ["Marketing digital, e-business et entrepreneuriat"]), LABELS[4]: None, LABELS[6]: None,
             LABELS[10]: (TC, ["Optimisation énergétique"])}
    bad += [("fixed", k, CA.but_specialite(k, names)) for k, v in fixed.items() if CA.but_specialite(k, names) != v]
    return not bad, f"{len(LABELS)} labels; problems {bad[:3]}"


# ------------------------------------------------------------------ BU2 a crafted warehouse
FY_COLS = "cod_aff_form VARCHAR, session INTEGER, fili VARCHAR, form_lib_voe_acc VARCHAR, fil_lib_voe_acc VARCHAR, lib_for_voe_ins VARCHAR, " \
          "cod_uai VARCHAR, apprentissage BOOLEAN, dep_lib VARCHAR, acad_mies VARCHAR"
CA_COLS = "cod_aff_form VARCHAR, fiche_url VARCHAR, lat DOUBLE, lon DOUBLE, carto_session INTEGER, etablissement_id_paysage VARCHAR, " \
          "composante_id_paysage VARCHAR, apprentissage BOOLEAN, internat VARCHAR, distance VARCHAR, amenag_sport BOOLEAN, amenag_art BOOLEAN, " \
          "etab_uai VARCHAR, etab_nom VARCHAR, types_etab VARCHAR, type_formation VARCHAR, nom_long VARCHAR, mention_lib VARCHAR, " \
          "commune VARCHAR, departement VARCHAR"
# initial (and SIES apprenticeship) formations: code, uai, fili, SIES mention, cartographie mention, SIES apprenticeship
INITIAL = [("1", "U1", "BUT", TC, f"BUT - P1,BUT - P2,BUT - {TC}", False), ("2", "U1", "BUT", GEA, f"BUT - G1,BUT - {GEA}", False),
           ("3", "U2", "BUT", CS, f"BUT - {CS}", False), ("4", "U3", "BTS", "Comptabilité et gestion", "BUT - X,BTS - Comptabilité et gestion", False),
           ("5", "U4", "BUT", TC, f"BUT - P1,BUT - {TC}", True)]
# apprenticeship offers: code, uai, cartographie mention -> (mention, parcours, attached)
OFFERS = [("10", "U1", f"BUT - P2,BUT - {TC}", (TC, ["P2"], ["1"])),
          ("11", "U1", f"BUT - G1,BUT -  Gestion  des entreprises et des administrations", (GEA, ["G1"], ["2"])),
          ("12", "U9", f"BUT - P1,BUT - {TC}", (TC, ["P1"], [])),
          ("13", "U1", f"BUT - {TC},BUT - {GEA}", (f"BUT - {TC},BUT - {GEA}", [], [])),
          ("15", "U2", f"BUT - {CS}", (CS, [], ["3"])),
          ("16", "U1", f"BUT - Marketing digital, e-business et entrepreneuriat,BUT - {TC}", (TC, ["Marketing digital, e-business et entrepreneuriat"], ["1"])),
          ("17", "U4", f"BUT - P1,BUT - {TC}", (TC, ["P1"], []))]


def crafted() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute(f"CREATE TABLE core.formation_year ({FY_COLS})")
    con.execute(f"CREATE TABLE core.cartographie ({CA_COLS})")
    for cod, uai, fili, fil, ml, app in INITIAL:
        con.execute("INSERT INTO core.formation_year VALUES (?, 2025, ?, ?, ?, ?, ?, ?, 'Yonne', 'Dijon')",
                    [cod, fili, f"{fili} formation", fil, f"{fili} - {fil}", uai, app])
        con.execute("INSERT INTO core.cartographie VALUES (?, NULL, 47.0, 3.0, 2026, NULL, NULL, ?, 'non', 'aucune', false, false, ?, 'IUT', "
                    "'Publics', ?, ?, ?, 'Auxerre', 'Yonne')", [cod, app, uai, fili, f"{fili} - {fil}", ml])
    for cod, uai, ml, _ in OFFERS:
        con.execute("INSERT INTO core.cartographie VALUES (?, ?, 47.0, 3.0, 2026, NULL, NULL, true, 'non', 'aucune', false, false, ?, ?, "
                    "'Publics', 'BUT', 'BUT - en apprentissage', ?, 'Auxerre', 'Yonne')",
                    [cod, f"https://dossierappel.parcoursup.fr/x?g_ta_cod={cod}", uai, f"CFA {cod}", ml])
    return con


@check("BU2 crafted warehouse: mention, parcours and attachment of each offer equal a table written by hand")
def bu2(c: Ctx):
    CA = c.mod()
    con = crafted()
    got = {a["cod_aff_form"]: (a["mention"], list(a["parcours"]), a["rattachee"], a["diplome"]) for a in CA.apprentissage(con)}
    bad = [(cod, got.get(cod), want) for cod, _, _, want in OFFERS if got.get(cod, (None,))[:3] != want or got[cod][3] != "BUT"]
    pf = CA.offres_par_formation(con)
    if sorted(o["cod_aff_form"] for o in pf.get("1", [])) != ["10", "16"] or [o.get("parcours") for o in pf.get("2", [])] != [["G1"]]:
        bad.append(("formation page offers", {k: [(o["cod_aff_form"], o.get("parcours")) for o in v] for k, v in pf.items()}))
    return not bad, f"{len(OFFERS)} crafted offers; problems {bad[:3]}"


# ------------------------------------------------------------------ BU3 real data
@check("BU3 real data: every BUT offer re-derived, no raw list as mention, none apart beside its IUT's specialty; owner's examples")
def bu3(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    CA = c.mod()
    con = duckdb.connect(str(c.db), read_only=True)
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    names = {r[0] for r in con.execute("SELECT fil_lib_voe_acc FROM core.formation_year WHERE fili = 'BUT' AND session = ?", [latest]).fetchall() if r[0]}
    lab = {r[0]: r[1:] for r in con.execute("""SELECT cod_aff_form, etab_uai, mention_lib FROM core.cartographie
                                               WHERE carto_session = (SELECT max(carto_session) FROM core.cartographie)""").fetchall()}
    ini: dict = {}
    for cod, u1, u2, fil in con.execute("""SELECT f.cod_aff_form, f.cod_uai, c.etab_uai, f.fil_lib_voe_acc FROM core.formation_year f, core.cartographie c
            WHERE c.cod_aff_form = f.cod_aff_form AND f.session = ? AND f.fili = 'BUT' AND f.apprentissage IS NOT TRUE""", [latest]).fetchall():
        for u in {u1, u2} - {None, ""}:
            ini.setdefault((u, fil), set()).add(cod)
    off = [a for a in CA.apprentissage(con) if a["diplome"] == "BUT"]
    bad = []
    for a in off:
        uai, ml = lab[a["cod_aff_form"]]
        sp = rt_but(ml, names)
        if sp and (a["mention"], list(a["parcours"])) != sp:
            bad.append((a["cod_aff_form"], "mention/parcours", a["mention"], sp))
        if ",BUT - " in (a["mention"] or "") or (a["mention"] or "").startswith("BUT - "):
            bad.append((a["cod_aff_form"], "raw list kept", a["mention"]))
        want = ini.get((uai, sp[0]), set()) if sp else set()
        if not want <= set(a["rattachee"]):
            bad.append((a["cod_aff_form"], "not attached", sorted(want), a["rattachee"]))
    ex = {a["cod_aff_form"]: a for a in off}
    if "10802" in ex or "2710" in ex:
        e1, e2 = ex.get("10802"), ex.get("2710")
        if not e1 or (e1["mention"], e1["parcours"], e1["rattachee"]) != (TC, ["Marketing digital, e-business et entrepreneuriat"], ["10801"]):
            bad.append(("10802", e1 and (e1["mention"], e1["parcours"], e1["rattachee"])))
        if not e2 or (e2["mention"], e2["parcours"], e2["rattachee"]) != (GEA, ["Contrôle de gestion et pilotage de la performance",
                                                                                  "Gestion et pilotage des ressources humaines"], ["2704"]):
            bad.append(("2710", e2 and (e2["mention"], e2["parcours"], e2["rattachee"])))
        if [o.get("parcours") for o in CA.for_formation(con, "10801") if o["cod_aff_form"] == "10802"] != [["Marketing digital, e-business et entrepreneuriat"]]:
            bad.append(("10801 formation page", CA.for_formation(con, "10801")))
    n_att = sum(bool(a["rattachee"]) for a in off)
    if len(off) < 50 or n_att < 100:
        bad.append(("too few", len(off), n_att))
    return not bad, f"{len(off)} BUT apprenticeship offers, {n_att} attached; problems {bad[:3]}"


# ------------------------------------------------------------------ BU4 the mention filter
def rt_group(m: str) -> str:
    low = m.lower()
    i = low.find(" parcours ")
    return m[:i].strip() if i > 0 else m


@check("BU4 mention filter: SIES's parcours-split specialties grouped under the specialty, every other BUT mention its own group")
def bu4(c: Ctx):
    CA = c.mod()
    bad = []
    for m in (CS, "Carrières sociales parcours villes et territoires durables", "Génie biologique Parcours agronomie", TC,
              "Génie civil - Construction durable", "Information communication Parcours journalisme", HOSTILE):
        if CA.groupe_of("BUT", m) != rt_group(m):
            bad.append((m, CA.groupe_of("BUT", m), rt_group(m)))
    if CA.groupe_of("Licence", "Droit parcours X") != "Droit parcours X":
        bad.append(("another diploma grouped",))
    n = 0
    if c.real:
        con = duckdb.connect(str(c.db), read_only=True)
        but = next((d for d in CA.facets(con)["diplomes"] if d["label"] == "BUT"), None)
        if not but:
            return False, "no BUT in the facets"
        seen = []
        for g in but["mentions"]:
            n += 1
            if "parcours" in g["label"].lower():
                bad.append(("group names a parcours", g["label"]))
            for v in g["variantes"]:
                seen.append(v)
                if rt_group(v) != g["label"]:
                    bad.append(("variant in the wrong group", v, g["label"]))
        if len(seen) != len(set(seen)):
            bad.append(("variant in two groups",))
        cs = next((g for g in but["mentions"] if g["label"] == "Carrières sociales"), None)
        if not cs or len(cs["variantes"]) < 2:
            bad.append(("Carrières sociales not grouped", cs))
    return not bad, f"{n} BUT groups; problems {bad[:3]}"


# ------------------------------------------------------------------ BU5 the page
def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        return js[m.start(): m.start() + e.end()]
    return js[m.start(): js.find("\n}", m.start()) + 2]


@check("BU5 page: the parcours quoted and escaped on the CFA lines and on an offer listed apart; nothing without parcours")
def bu5(c: Ctx):
    js = c.js
    exe = shutil.which("node")
    bad = []
    card = top(js, "carteCard")
    if 'f.stats === false && appParcours(f) ? `<div class="small">En apprentissage : ${appParcours(f)}</div>`' not in card:
        bad.append("offer listed apart: no parcours line")
    for fn in ("appOffers", "apprentiCard"):
        if "${appParcours(o) ? ` · ${appParcours(o)}` : \"\"}" not in top(js, fn):
            bad.append(f"{fn}: no parcours")
    if not exe:
        return not bad, f"node not installed; {bad}"
    prog = "const voeuxApp = { has: () => false, get: () => [], MAX: 10 };\n" + "\n".join(top(js, n) for n in (
        "esc", "ACAD_LABEL", "acadLabel", "carteFiche", "appParcours", "appVoeuLabel", "appVoeuButton",   # PR 18: the button
        "SP_HOST", "appOfficiel", "appOffers", "apprentiCard")) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const a = { propose: true, liens: { salaire: "https://x", entreprises: "https://y", guide: "https://z" }, offres: P.offres };
process.stdout.write(JSON.stringify({ p: appParcours(P.offres[0]), none: appParcours(P.offres[1]), list: appOffers(P.offres), card: apprentiCard(a) }));"""
    offres = [{"cod_aff_form": "1", "etablissement": "CFA", "ville": "V", "fiche": "https://dossierappel.parcoursup.fr/x",
               "parcours": ["Marketing digital, e-business et entrepreneuriat", HOSTILE]},
              {"cod_aff_form": "2", "etablissement": "CFA2", "ville": "V", "fiche": None, "parcours": []}]
    r = nodefile.run([exe, "-e", prog], input=json.dumps({"offres": offres}), capture_output=True, text=True, timeout=60)
    if r.returncode:
        return False, r.stderr[-400:]
    o = json.loads(r.stdout)
    if "<img" in r.stdout:
        bad.append("unescaped")
    if not o["p"].startswith("parcours « Marketing digital, e-business et entrepreneuriat », « "):
        bad.append(("quoted names", o["p"][:120]))
    if o["none"] != "":
        bad.append("parcours line without parcours")
    for k in ("list", "card"):
        if o[k].count("parcours «") != 1:
            bad.append((k, "parcours once per CFA with parcours"))
    return not bad, f"3 renders; problems {bad}"


# ------------------------------------------------------------------ BU6 docs
@check("BU6 docs and wiring: README, CLAUDE.md, durations.json, the test file")
def bu6(c: Ctx):
    bad = []
    readme = (ROOT / "README.md").read_text()
    if "BUT par spécialité" not in readme or "redteam_but.py" not in readme:
        bad.append("README")
    cl = (ROOT.parent / "CLAUDE.md").read_text()
    if "carte.but_specialite" not in cl or "redteam_but.py" not in cl:
        bad.append("CLAUDE.md")
    if "tests/test_but.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    if not (ROOT / "tests" / "test_but.py").exists():
        bad.append("test file")
    return not bad, f"problems {bad}"


MUTANTS = [
    ("carte", "first BUT item taken as the specialty", "    spec = [x for x in names if x in specialites]\n    if len(spec) != 1:",
     "    spec = names[-1:]\n    if len(spec) != 1:", "BU1"),
    ("carte", "two specialties accepted", "    if len(spec) != 1:\n        return None\n    return spec[0]", "    if not spec:\n        return None\n    return spec[0]", "BU1"),
    ("carte", "split on every comma", 'BUT_ITEM = re.compile(r",(?=BUT - )")', 'BUT_ITEM = re.compile(r",")', "BU1"),
    ("carte", "another diploma's item kept", '    if not items or not all(x.startswith("BUT - ") for x in items):', '    if not items:', "BU1"),
    ("carte", "spaces not normalised", '    items = [" ".join(x.split()) for x in BUT_ITEM.split(mention_lib or "")]',
     '    items = [x for x in BUT_ITEM.split(mention_lib or "")]', "BU1"),
    ("carte", "parcours dropped", '                    "parcours": bs[1] if bs else [], "rattachee": sorted(att)})',
     '                    "parcours": [], "rattachee": sorted(att)})', "BU2"),
    ("carte", "no attachment by specialty", '            att |= initial_but.get((uai, m), set()) if uai else set()', '            pass', "BU2"),
    ("carte", "attached across IUTs", '            att |= initial_but.get((uai, m), set()) if uai else set()',
     '            att |= {y for (u2, s2), ys in initial_but.items() if s2 == m for y in ys}', "BU2"),
    ("carte", "SIES's apprenticeship rows taken as initial", "WHERE f.session = (SELECT max(session) FROM core.formation_year) AND f.fili = 'BUT'\n              AND NOT coalesce(f.apprentissage, false)",
     "WHERE f.session = (SELECT max(session) FROM core.formation_year) AND f.fili = 'BUT'", "BU2"),
    ("carte", "mention left raw", "            m = bs[0]\n", "", "BU2"),
    ("carte", "parcours lost on the formation page", '                                            "parcours": a["parcours"]})', '                                            "parcours": []})', "BU2"),
    ("carte", "parcours-split specialties not grouped", '        bp = re.match(r"(.+?)\\s+parcours\\s+\\S", m, re.I)', '        bp = re.match(r"(.+?)\\s+Parcours\\s+\\S", m)', "BU4"),
    ("carte", "every BUT mention cut", '        bp = re.match(r"(.+?)\\s+parcours\\s+\\S", m, re.I)', '        bp = re.match(r"(\\S+)\\s+\\S", m)', "BU4"),
    ("js", "parcours unescaped", '`parcours ${o.parcours.map((x) => `« ${esc(x)} »`).join(", ")}`', '`parcours ${o.parcours.map((x) => `« ${x} »`).join(", ")}`', "BU5"),
    ("js", "parcours not quoted", '`parcours ${o.parcours.map((x) => `« ${esc(x)} »`).join(", ")}`', '`parcours ${o.parcours.map((x) => esc(x)).join(", ")}`', "BU5"),
    ("js", "an empty parcours line", '(o && Array.isArray(o.parcours) && o.parcours.length\n', '(o && Array.isArray(o.parcours)\n', "BU5"),
    ("js", "no parcours on the formation page", '      return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${appParcours(o) ? ` · ${appParcours(o)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">sa fiche',
     '      return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">sa fiche', "BU5"),
]


@check("BU7 mutation test: every seeded rule, attachment, grouping and page bug is caught")
def bu7(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:6] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught = [], 0
    for kind, name, old, new, target in MUTANTS:
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
    return not missed, f"{caught}/{len(MUTANTS)} caught; missed {missed}"


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
