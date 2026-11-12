"""Red team of sprint 20, "votre ligne" for bac techno and bac pro students in a formation's public report (owner, 2026-11-11).
    python scripts/redteam_voies.py [--db data/suptracker.duckdb] [--real]
  W1 bac techno labels: an INDEPENDENT keyword reading of every label the reports print (embedded list + the warehouse's own)
     gives the same key as voies.BT_RULES; every rule matches a label; "Autres doublettes" gets no key
  W2 bac pro labels: format-only variants share a key ("Bac pro", "opt.", quotes, colons, case, accents), different words never
     do; on the warehouse, two labels share a key only when their words agree
  W3 the student's row, re-derived: own key, else the formation's bucket, else nothing; a masked table or no choice = nothing;
     on the warehouse, every report row's key and every pick against a SQL re-derivation
  W4 the routes: /api/journey/vocab lists the choices (counts re-derived, no "Bac pro" prefix, codes unique, never "autre"),
     /api/voeux returns the row for bac techno / pro, ignores `voie` for bac général, survives hostile values
  W5 the page in Node: pickVoie equals pick_voie; the formation page marks exactly one row and names it, the bucket and the
     masked table said, hostile labels escaped; the profile form, the profile line and the Mes vœux query
  W6 wording: never a chance, vouvoiement, "rare" not "fermé", the report caveat (terminale en France) kept
  W7 wiring: Mes vœux column, Mon parcours note, apprenticeship pointer for bac pro, feature list, release guard
  W8 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import voies as VO  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
M = {"VO": VO}
HOSTILE = '<img src=x onerror=alert(1)>'
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")

# the bac techno labels the 2024-2025 reports print (as printed), and what a reader of the reports would call them
BT_PRINTED = {
    "Msgn/ Mercatique & Droit et Economie": "stmg_merc",
    "Msgn/ Ressources humaines et communication & Droit et Economie": "stmg_rhc",
    "Msgn/ Gestion et Finance & Droit et Economie": "stmg_gf",
    "Msgn/ Systèmes d'information et de Gestion & Droit et Economie": "stmg_sig",
    "Physique-Chimie et Mathématiques & Ingénierie, innovation et développement durable": "sti2d",
    "Sciences et techniques sanitaires et sociales & Chimie, biologie et physiopathologie humaines": "st2s",
    "Physique-Chimie et Mathématiques & Biochimie-Biologie- Biotechnologie": "stl_bio",
    "Sciences physiques et chimiques en laboratoire & Physique-Chimie et Mathématiques": "stl_spcl",
    "Conception et création en design et métiers d'art & Analyse et méthodes en design": "std2a",
    "Gestion des ressources et alimentation & Territoires et technologie": "stav",
    "Economie et gestion hôtelière & Sciences et Technologies culinaires et services- ESAE": "sthr",
    "Economie et gestion hôtelière & Sciences et Technologies culinaires et services-ESAE": "sthr",
    "Culture et sciences musicale & Pratique musicale": "s2tmd_musique",
    "Culture et sciences chorégraphiques & Pratique chorégraphiques": "s2tmd_danse",
}


def independent_bt(label: str) -> str | None:
    """A second reading of a techno label, by keywords (not the module's table)."""
    t = label.lower()
    if "autres" in t:
        return None
    for words, key in ((("mercatique",), "stmg_merc"), (("ressources humaines",), "stmg_rhc"), (("gestion et finance",), "stmg_gf"),
                       (("information et de gestion",), "stmg_sig"), (("ingénierie",), "sti2d"), (("sanitaires",), "st2s"),
                       (("biotechnologie",), "stl_bio"), (("en laboratoire",), "stl_spcl"), (("design",), "std2a"),
                       (("territoires et technologie",), "stav"), (("hôtelière",), "sthr"), (("musical",), "s2tmd_musique"),
                       (("chorégraphiques",), "s2tmd_danse")):
        if all(w in t for w in words):
            return key
    return None


def words_of(label: str) -> tuple:
    """The words of a bac pro label, read independently: letters and digits only, a leading 'bac pro' and 'opt' set aside."""
    import unicodedata
    s = unicodedata.normalize("NFKD", re.sub(r"[’'«»]", " ", label)).encode("ascii", "ignore").decode().lower()   # ’ separates words
    w = re.findall(r"[a-z0-9]+", s)
    if w[:2] == ["bac", "pro"]:
        w = w[2:]
    return tuple("option" if x == "opt" else x for x in w)


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.vx = (ROOT / "suptracker" / "voeux.py").read_text()
        self.has = self.con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
            AND table_name = 'rapport_doublette'""").fetchone()[0] > 0


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-500:]}


def top(js: str, name: str) -> str:
    """A top-level definition of app.js (function or const), as written."""
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    lines, out = js[m.start():].split("\n"), []
    is_const = lines[0].startswith("const ")
    for k, ln in enumerate(lines):
        out.append(ln)
        if is_const and ln.rstrip().endswith(";") and (k == 0 or ln.rstrip().endswith("};") or not ln.startswith(" ")):
            break
        if not is_const and k > 0 and ln == "}":
            break
    return "\n".join(out)


@check("W1 bac techno: an independent keyword reading gives the same key for every printed label; every rule is used")
def w1(c: Ctx):
    A = M["VO"]
    labels = dict(BT_PRINTED)
    if c.has:
        labels.update({lab: independent_bt(lab) for (lab,) in c.con.execute(
            "SELECT DISTINCT libelle FROM core.rapport_doublette WHERE bac = 'bt' AND NOT autres").fetchall()})
    bad = [(lab, A.voie_key("bt", lab), want) for lab, want in labels.items()
           if A.voie_key("bt", lab) != want or independent_bt(lab) != want]
    used = {A.voie_key("bt", lab) for lab in labels}
    dead = [k for k, *_ in A.BT_RULES if k not in used]
    autres = A.voie_key("bt", "Autres doublettes", True) is None and A.voie_key("bt", "Autres doublettes") is None
    unique = len({k for k, *_ in A.BT_RULES}) == len(A.BT_RULES)
    ok = not bad and not dead and autres and unique
    return ok, f"{len(labels)} labels read twice; disagreements {bad[:3]}; unused rules {dead}; bucket keyless {autres}; keys unique {unique}"


@check("W2 bac pro: format-only variants share a key, different words never do (crafted and warehouse labels)")
def w2(c: Ctx):
    A = M["VO"]
    same = [("Bac pro Métiers de la sécurité", "Métiers de la sécurité", "métiers de la SÉCURITÉ"),
            ("Maintenance des matériels option a: agricoles", "Maintenance des matériels option a : agricoles", "Maintenance des matériels opt. a agricoles"),
            ("Accompagnement, soins et services à la personne option b : « en structure »", "Accompagnement soins et services à la personne option b en structure"),
            ("Etude et Réalisation d’Agencement", "Etude et réalisation d'agencement")]
    differ = [("Accompagnement soins et services à la personne", "Accompagnement, soins et services à la personne option b : « en structure »"),
              ("Systèmes numériques, option a: sûreté", "Systèmes numériques, option b: sûreté"),
              ("Services aux personnes et animation dans les territoires", "Services aux personnes et aux territoires"),
              ("Bac pro Logistique", "Organisation de transport de marchandises")]
    bad = [g for g in same if len({A.bp_key(x) for x in g}) != 1] + [g for g in differ if A.bp_key(g[0]) == A.bp_key(g[1])]
    merged = []
    if c.has:
        labs = [lab for (lab,) in c.con.execute("SELECT DISTINCT libelle FROM core.rapport_doublette WHERE bac = 'bp' AND NOT autres").fetchall()]
        groups: dict = {}
        for lab in labs:
            groups.setdefault(A.voie_key("bp", lab), set()).add(words_of(lab))
        merged = [k for k, w in groups.items() if len(w) > 1 or k is None]
        indep = len({words_of(lab) for lab in labs}) == len(groups)
    else:
        indep = True
    ok = not bad and not merged and indep
    return ok, f"crafted problems {bad[:2]}; warehouse keys merging different words {merged[:2]}; same grouping as an independent reading {indep}"


def crafted_block():
    rows = {"bt": [{"libelle": "Msgn/ Mercatique & Droit et Economie", "voie": "stmg_merc", "autres": False, "confirmes": 194, "en_position": 70, "taux": 36.1},
                   {"libelle": "Physique-Chimie et Mathématiques & Ingénierie, innovation et développement durable", "voie": "sti2d", "autres": False,
                    "confirmes": 50, "en_position": 10, "taux": 20.0},
                   {"libelle": "Autres doublettes", "voie": None, "autres": True, "confirmes": 55, "en_position": 35, "taux": 63.6}],
            "bp": [{"libelle": "Cuisine", "voie": "cuisine", "autres": False, "confirmes": 30, "en_position": 3, "taux": 10.0}],
            "bg": [{"libelle": "Autres doublettes", "key": None, "voie": None, "autres": True, "confirmes": 80, "en_position": 40, "taux": 50.0}]}
    return {"session": 2025, "recoupe": True, "doublettes": rows, "masques": []}


@check("W3 the student's row: own key, else the formation's bucket, else nothing; re-derived on the warehouse")
def w3(c: Ctx):
    A = M["VO"]
    b = crafted_block()
    cases = [(("bt", "stmg_merc"), ("voie", 36.1)), (("bt", "stmg_rhc"), ("autres", 63.6)), (("bt", "autre"), ("autres", 63.6)),
             (("bt", None), None), (("bp", "cuisine"), ("voie", 10.0)), (("bp", "logistique"), None), (("bg", "stmg_merc"), None)]
    got = {k: (lambda x: (x["source"], x["taux"]) if x else None)(A.pick_voie(b, *k)) for k, _ in cases}
    bad = [(k, got[k], want) for k, want in cases if got[k] != want]
    # review (sprint 20): an older session that never printed the student's key gives no bucket ("autre" still does);
    # a label no rule knows stops the bucket claim
    old = {**b, "voie_keys": {"bt": ["sti2d", "stmg_merc"], "bp": ["cuisine"]}}
    unk = {**b, "doublettes": {**b["doublettes"], "bt": b["doublettes"]["bt"] + [{"libelle": "Nouvelle série", "voie": None, "autres": False,
                                                                                  "confirmes": 9, "en_position": 1, "taux": 11.1}]}}
    session = [(A.pick_voie(old, "bt", "stmg_rhc"), None), ((A.pick_voie(old, "bt", "autre") or {}).get("source"), "autres"),
               ((A.pick_voie(old, "bt", "sti2d") or {}).get("source"), "voie"), (A.pick_voie(unk, "bt", "stmg_rhc"), None)]
    bad += [("session/unknown", i, g) for i, (g, w) in enumerate(session) if g != w]
    n = 0
    if c.real and c.has:
        from suptracker import rapports as RP
        cods = [x for (x,) in c.con.execute("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = (SELECT max(session)
            FROM core.rapport) AND bac IN ('bt', 'bp') ORDER BY hash(cod_aff_form) LIMIT 120""").fetchall()]
        cods += [x for (x,) in c.con.execute("""SELECT cod_aff_form FROM core.rapport_masque WHERE session = (SELECT max(session)
            FROM core.rapport) ORDER BY hash(cod_aff_form) LIMIT 20""").fetchall()]
        for cod in cods:
            blk = RP.for_formation(c.con, cod)
            s = blk["session"]
            vk = {b: sorted({(independent_bt(lab) if b == "bt" else " ".join(words_of(lab))) for (lab,) in c.con.execute(
                """SELECT DISTINCT libelle FROM core.rapport_doublette WHERE session = ? AND bac = ? AND NOT autres""", [s, b]).fetchall()})
                  for b in ("bt", "bp")}
            if blk.get("voie_keys") != vk:
                bad.append((cod, "session keys"))
            sql = {(bac, lab): (bool(a), p, cf) for bac, lab, a, p, cf in c.con.execute("""SELECT bac, libelle, autres, en_position, confirmes
                FROM core.rapport_doublette WHERE cod_aff_form = ? AND session = ? AND bac IN ('bt', 'bp')""", [cod, s]).fetchall()}
            for bac in ("bt", "bp"):
                for x in blk["doublettes"].get(bac, []):
                    want = None if x["autres"] else (independent_bt(x["libelle"]) if bac == "bt" else " ".join(words_of(x["libelle"])))
                    if x["voie"] != want:
                        bad.append((cod, bac, x["libelle"], x["voie"]))
                for key in ("stmg_merc", "sti2d", "assistance a la gestion des organisations et de leurs activites", "autre"):
                    pick = A.pick_voie(blk, bac, key)
                    own = [(lab, v) for (bb, lab), v in sql.items() if bb == bac and not v[0]
                           and (independent_bt(lab) if bac == "bt" else " ".join(words_of(lab))) == key]
                    bucket = [(lab, v) for (bb, lab), v in sql.items() if bb == bac and v[0]]
                    comparable = key == "autre" or key in vk[bac]
                    exp = own[0] if own else bucket[0] if bucket and comparable else None
                    if (pick is None) != (exp is None) or (pick and (pick["libelle"] != exp[0] or pick["en_position"] != exp[1][1]
                                                                    or pick["confirmes"] != exp[1][2])):
                        bad.append((cod, bac, key, "pick"))
                    n += 1
        b24 = RP.for_formation(c.con, "23379", 2024)
        if b24 and b24["session"] == 2024 and A.pick_voie(b24, "bp", "services aux personnes et animation dans les territoires") is not None:
            bad.append(("23379", 2024, "renamed diploma sent to the bucket"))
    return not bad, f"{len(cases) + len(session)} crafted cases; {n} warehouse picks re-derived by SQL; problems {bad[:3]}"


@contextmanager
def client(db: Path, mod=None):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api, voeux
    old, saved = os.environ.get("SUPTRACKER_DB"), A.record
    saved_vo, saved_vx = api.VO, voeux.VO
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    A.record = lambda *a, **k: "ok"
    api.VO = voeux.VO = mod or M["VO"]
    try:
        yield TestClient(api.app)
    finally:
        A.record, api.VO, voeux.VO = saved, saved_vo, saved_vx
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


@check("W4 routes: the choices (counts re-derived, clean labels, unique codes), Mes vœux rows for bac techno / pro, bac général unchanged")
def w4(c: Ctx):
    bad = []
    with client(c.db) as cl:
        v = cl.get("/api/journey/vocab").json().get("voies")
        if v is None:
            return False, "no 'voies' in the vocabulary"
        codes = [x["code"] for x in v["bt"] + v["bp"]]
        if len(codes) != len(set(codes)) or "autre" in codes or any(x["label"].lower().startswith("bac pro") or not x["label"][:1].isupper() for x in v["bp"]):
            bad.append("choices")
        if [x["code"] for x in v["bt"]] != [k for k, *_ in M["VO"].BT_RULES if k in {x["code"] for x in v["bt"]}]:
            bad.append("techno order")
        if c.has:
            s = c.con.execute("SELECT max(session) FROM core.rapport").fetchone()[0]
            for x in v["bt"][:4]:
                labs = [lab for lab, k in BT_PRINTED.items() if k == x["code"]]
                n = c.con.execute(f"""SELECT count(DISTINCT cod_aff_form) FROM core.rapport_doublette WHERE session = ? AND bac = 'bt'
                    AND libelle IN ({','.join('?' * len(labs))})""", [s, *labs]).fetchone()[0]
                if n != x["n"]:
                    bad.append(("count", x["code"], n, x["n"]))
        hostile = [cl.get("/api/voeux", params={"ids": "1", "serie": "bt", "mention": "ab", "voie": x}).status_code
                   for x in ("'; DROP TABLE x; --", HOSTILE, "")] + [cl.get("/api/voeux", params={"ids": "1", "serie": "bt", "voie": "x" * 500}).status_code]
        if hostile != [200, 200, 200, 422]:
            bad.append(("hostile", hostile))
        if c.real and c.has:
            from suptracker import rapports as RP
            cods = [x for (x,) in c.con.execute("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = (SELECT max(session)
                FROM core.rapport) AND bac = 'bt' ORDER BY hash(cod_aff_form) LIMIT 8""").fetchall()]
            for serie, key in (("bt", "stmg_merc"), ("bt", None)):
                r = cl.get("/api/voeux", params={"ids": ",".join(cods), "serie": serie, "mention": "ab", **({"voie": key} if key else {})}).json()
                for x in r["voeux"]:
                    if x["status"] != "ok":
                        continue
                    want = M["VO"].pick_voie(RP.for_formation(c.con, x["cod_aff_form"]), serie, key)
                    got = x.get("rapport")
                    blk = RP.for_formation(c.con, x["cod_aff_form"])
                    full = None if not want else {"session": blk["session"], "source": want["source"], "taux": want["taux"], "confirmes": want["confirmes"],
                                                  "en_position": want["en_position"], "recoupe": blk["recoupe"], "libelle": want["libelle"]}
                    if got != full:
                        bad.append((serie, key, x["cod_aff_form"]))
            cross = cl.get("/api/voeux", params={"ids": ",".join(cods), "serie": "bp", "mention": "ab", "voie": "stmg_merc"}).json()
            if any(x.get("rapport") for x in cross["voeux"]):
                bad.append("a techno key read for a bac pro student")
            g1 = cl.get("/api/voeux", params={"ids": ",".join(cods), "serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab"}).json()
            g2 = cl.get("/api/voeux", params={"ids": ",".join(cods), "serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab", "voie": "stmg_merc"}).json()
            if [x.get("rapport") for x in g1["voeux"]] != [x.get("rapport") for x in g2["voeux"]]:
                bad.append("bg changed by voie")
        if any(x["label"].lower().startswith("autres") for x in v["bp"] + v["bt"]):
            bad.append("a bucket offered as a choice")
    # a crafted warehouse: the buckets are never a choice, labels are cleaned, counts are per formation, latest session only
    mem = duckdb.connect(":memory:")
    mem.execute("CREATE SCHEMA core")
    mem.execute("CREATE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER)")
    mem.execute("INSERT INTO core.rapport VALUES ('1', 2025), ('2', 2025), ('3', 2024), ('4', 2025)")
    mem.execute("CREATE TABLE core.rapport_doublette (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR, libelle VARCHAR, autres BOOLEAN)")
    mem.execute("""INSERT INTO core.rapport_doublette VALUES ('1', 2025, 'bt', 'Msgn/ Mercatique & Droit et Economie', false),
        ('2', 2025, 'bt', 'Msgn/ Mercatique & Droit et Economie', false), ('1', 2025, 'bt', 'Autres doublettes', true),
        ('1', 2025, 'bp', 'Bac pro cuisine', false), ('2', 2025, 'bp', 'Cuisine', false), ('1', 2025, 'bp', 'Autres spécialités', true),
        ('4', 2025, 'bp', 'Bac pro cuisine', false), ('3', 2024, 'bp', 'Logistique', false)""")
    ch = M["VO"].choices(mem)
    validity = [M["VO"].valid(mem, "bp", "stmg_merc"), M["VO"].valid(mem, "bt", "stmg_merc"), M["VO"].valid(mem, "bt", "autre"),
                M["VO"].valid(mem, "bg", "stmg_merc"), M["VO"].valid(mem, "bt", "stale_key")]
    if validity != [None, "stmg_merc", "autre", None, None]:
        bad.append(("validity", validity))
    mem.close()
    crafted = ch == {"bt": [{"code": "stmg_merc", "serie": "STMG", "label": "STMG, Mercatique", "n": 2}],
                     "bp": [{"code": "cuisine", "label": "Cuisine", "n": 3}]}
    if not crafted:
        bad.append(("crafted choices", ch))
    return not bad, f"{len(v['bt'])} techno and {len(v['bp'])} pro choices; crafted warehouse {crafted}; problems {bad[:3]}"


@check("W5 the page (Node): pickVoie = pick_voie, one row marked and named, bucket and masked table said, escaping, profile, query")
def w5(c: Ctx):
    js = c.js
    try:
        lib = "\n".join(top(js, n) for n in ("esc", "fmt", "pct", "VOIES", "pct1", "rateBar", "voiePill", "profileDkey", "pickRapport",
                                             "pickVoie", "VOIE_WORD", "RP_CAVEAT", "rpPending", "rapportSource", "rapportDoublettes",
                                             "REO_LABEL", "isReo", "profileLine", "vxQuery", "vxVoieCell", "voieFromForm",
                                             "MENTION_CODES", "BANDS", "validMoyenne", "bandOf", "mentionParams", "bandParam", "mentionParamsSearch", "localAverage", "BAND_SIGMA", "erf", "withinBand", "ZONE_RULES", "MIN_BOUNDS_N", "VX_SITUATED", "wilsonCI", "zoneOf", "isNum", "classifyZone", "seriesPos", "lire", "relireVue", "lectureOf", "readList", "voeuxLocal", "moyenneText", "MENTION_SHORT", "vxProfile"))
    except KeyError as e:
        return False, f"missing definition {e}"
    prog = lib + """
const [blk, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = { picks: cases.map(([bac, key]) => { const x = pickVoie(blk, bac, key); return x ? [x.source, x.taux] : null; }) };
out.own = rapportDoublettes(blk, { serie: "bt", voie: "stmg_merc", mention: "ab" }).html;
out.bucket = rapportDoublettes(blk, { serie: "bt", voie: "stmg_rhc", mention: "ab" }).html;
out.none = rapportDoublettes(blk, { serie: "bt", mention: "ab" }).html;
out.masked = rapportDoublettes({ ...blk, doublettes: { bg: blk.doublettes.bg }, masques: ["bt"] }, { serie: "bt", voie: "stmg_merc", mention: "ab" }).html;
out.bg = rapportDoublettes(blk, { serie: "bg", spe1: "MATHS", spe2: "SES", voie: "stmg_merc", mention: "ab" }).html;
out.bgMasked = rapportDoublettes({ ...blk, doublettes: { bt: blk.doublettes.bt }, masques: ["bg"] }, { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab" }).html;
out.line = profileLine({ serie: "bt", voie_label: "<img src=x>", mention: "ab" }, "bt");
out.qbt = vxQuery(["1"], { serie: "bt", mention: "ab", voie: "stmg_merc" }).toString();
out.qbg = vxQuery(["1"], { serie: "bg", mention: "ab", spe1: "MATHS", spe2: "SES", voie: "stmg_merc" }).toString();
const r1 = { session: 2026, source: "autres", taux: 40.0, confirmes: 50, en_position: 20, recoupe: false, libelle: "<b>Autres</b>" };
out.cell = vxVoieCell({ status: "ok", rapport: r1 }, { voie: "stmg_merc" });
out.cellNone = vxVoieCell({ status: "ok", rapport: null }, { voie: null });
const fd = (o) => ({ get: (k) => (k in o ? o[k] : null) });
out.formSame = voieFromForm(fd({ serie: "bt", voie: "sti2d" }), "bt", "STI2D, Ingénierie");
out.formNew = voieFromForm(fd({ serie: "bp", voie: "sti2d" }), "bt", "STI2D, Ingénierie");
var JV = { voies: { bt: [{ code: "sti2d" }], bp: [{ code: "cuisine" }] } };
out.stale = vxProfile({ serie: "bp", mention: "ab", voie: "sti2d", voie_label: "x" });
out.autre = vxProfile({ serie: "bp", mention: "ab", voie: "autre", voie_label: "Autre spécialité" });
out.oldSession = rapportDoublettes({ ...blk, voie_keys: { bt: ["sti2d"], bp: [] } }, { serie: "bt", voie: "stmg_rhc", mention: "ab" }).html;
process.stdout.write(JSON.stringify(out));"""
    b = crafted_block()
    b["doublettes"]["bt"][1]["libelle"] = HOSTILE
    b["doublettes"]["bg"] = [{"libelle": "Mathématiques & SES", "key": "MATHS+SES", "voie": None, "autres": False, "confirmes": 100, "en_position": 50, "taux": 50.0}]
    b.update({"capture": "20250701", "source": "archive", "archive": "https://web.archive.org/x"})
    cases = [["bt", "stmg_merc"], ["bt", "stmg_rhc"], ["bt", None], ["bp", "cuisine"], ["bp", "x"], ["bg", "stmg_merc"]]
    o = node(prog, [b, cases])
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    py = [(lambda x: [x["source"], x["taux"]] if x else None)(M["VO"].pick_voie(b, *k)) for k in cases]
    twin = o["picks"] == py
    mine = lambda h: re.findall(r'<tr class="dbl-mine"><td>(.*?)</td>', h)  # noqa: E731
    own = (mine(o["own"]) == ['Msgn/ Mercatique &amp; Droit et Economie <span class="estim">votre ligne</span>']
           and "Votre ligne dans cette formation : 36,1 %" in o["own"] and "ligne « Msgn/ Mercatique &amp; Droit et Economie »" in o["own"]
           and "70 candidats sur 194 de votre série" in o["own"])
    bucket = (mine(o["bucket"]) == ['Autres doublettes <span class="estim">votre série en fait partie</span>']
              and "ligne « Autres doublettes » de la formation" in o["bucket"] and "la vôtre est comptée avec les autres" in o["bucket"])
    none = not mine(o["none"]) and "Indiquez votre série et vos spécialités</a> pour voir votre ligne" in o["none"]
    masked = "la formation n'a pas publié son tableau" in o["masked"] and not mine(o["masked"])
    bg = mine(o["bg"]) == ['Mathématiques &amp; SES <span class="estim">votre doublette</span>'] and "Votre ligne dans" not in o["bg"]
    esc_ok = all("<img" not in o[k] for k in ("own", "bucket", "none", "masked", "bg", "line"))
    query = "voie=stmg_merc" in o["qbt"] and "voie=" not in o["qbg"]
    cell = ("40 %" in o["cell"] or "40,0 %" in o["cell"]) and "20 sur 50" in o["cell"] and "pas encore recoupé avec les chiffres de 2026" in o["cell"] \
        and "&lt;b&gt;Autres" in o["cell"] and "indiquez votre série" in o["cellNone"]
    form = o["formSame"] == {"voie": "sti2d", "voie_label": "STI2D, Ingénierie"} and o["formNew"] == {"voie": None, "voie_label": None}
    stored = o["stale"]["voie"] is None and o["stale"]["voie_label"] is None and o["autre"]["voie"] == "autre"
    older = "n'apparaît pas dans les rapports de la session 2025" in o["oldSession"] and not mine(o["oldSession"])
    once = o["masked"].count("non publiés par la formation") == 0 and o["bgMasked"].count("non publiés par la formation") == 1   # bac général: kept (Codex)
    ok = twin and own and bucket and none and masked and bg and esc_ok and query and cell and form and stored and older and once
    return ok, (f"twin {twin}; own row {own}; bucket {bucket}; no choice {none}; masked {masked}; bac général unchanged {bg}; "
                f"escaped {esc_ok}; query {query}; Mes vœux cell {cell}; form keeps a choice only for the same bac {form}; stale key dropped {stored}; "
                f"older session {older}; masked note once {once}")


@check("W6 wording: never a chance, vouvoiement, 'rare' not 'fermé', the report caveat kept")
def w6(c: Ctx):
    parts = [top(c.js, "rapportDoublettes"), top(c.js, "profileForm")]
    note = re.search(r"<p class=\"small\">Une part faible veut dire « rare », pas « fermé ».*?</p>", c.js)
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", "\n".join(parts) + (note.group(0) if note else ""))
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    caveat = "${RP_CAVEAT}" in parts[0] and "scolarisés en terminale en France" in top(c.js, "RP_CAVEAT")
    ok = not chance and not tu and bool(note) and caveat
    return ok, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; rare-not-closed note {bool(note)}; terminale caveat {caveat}"


@check("W7 wiring: profile form, Mes vœux column, Mon parcours note and apprenticeship pointer, vocabulary, features, release guard")
def w7(c: Ctx):
    js = c.js
    form = 'select name="voie"' in top(js, "profileForm") and "return { ...voieFromForm(fd, serie, vsel ? vsel.selectedOptions[0].textContent : null)," in top(js, "readForm")
    column = 'data-label="Votre ligne, rapport du jury"' in js and "Votre ligne dans le rapport du jury (cette formation)" in js
    appr = 'serie === "bp" ? ` Beaucoup de BTS se préparent aussi en apprentissage' in js
    vocab = '"voies": VO.choices(_con().cursor())' in c.api
    voeux = "x = VO.pick_voie(b, serie, voie)" in c.vx and "voie=VO.valid(_con().cursor(), serie, voie)" in c.api
    feat = '"voie_rapport"' in c.api.split("FEATURES = [", 1)[1].split("]", 1)[0]
    rel = '"voie_rapport": ("app.js", "function pickVoie(")' in (ROOT / "tests" / "test_release.py").read_text()
    ok = form and column and appr and vocab and voeux and feat and rel
    return ok, f"form {form}; Mes vœux column {column}; apprenticeship pointer {appr}; vocabulary {vocab}; Mes vœux route {voeux}; feature {feat}; release {rel}"


PY_MUTANTS = [
    ("a techno rule label mistyped", '["msgn mercatique droit et economie"]', '["msgn mercatique droit economie"]'),
    ("two techno series on one key", '("stmg_rhc", "STMG"', '("stmg_merc", "STMG"'),
    ("'opt.' not read as 'option'", '    k = re.sub(r"\\bopt\\b", "option", k)\n', ""),
    ("a 'Bac pro' prefix kept", '    k = re.sub(r"^bac pro\\b ?", "", k)\n', ""),
    ("the bucket given a key", "    if autres:\n        return None\n", "    if autres:\n        return norm(label)\n"),
    ("no fallback to the bucket", '    return {**other, "source": "autres"} if other else None', "    return None"),
    ("a row matched by its label", 'mine = next((x for x in rows if x.get("voie") == key), None)', 'mine = next((x for x in rows if x.get("libelle") == key), None)'),
    ("bac général read as a route", 'if not block or bac not in ("bt", "bp") or not key:', "if not block or not key:"),
    ("the bucket listed as a choice", "WHERE d.bac IN ('bt', 'bp') AND NOT d.autres", "WHERE d.bac IN ('bt', 'bp')"),
    ("curly apostrophe glues words", '    s = re.sub(r"[^\\w]+", " ", str(s or ""))', '    s = str(s or "")'),
    ("older session sent to the bucket", '    if key != "autre" and known is not None and key not in known:\n        return None', "    if False:\n        return None"),
    ("unknown label ignored", '    if any(x.get("voie") is None and not x["autres"] for x in rows):\n        return None', "    if False:\n        return None"),
    ("any key accepted", 'return key if key == "autre" or key in {x["code"] for x in choices(con)[serie]} else None', "return key"),
    ("'Bac pro' left in the labels", '        s = re.sub(r"^\\s*bac pro\\s+", "", s, flags=re.I).strip()\n', "        s = s.strip()\n"),
]
JS_MUTANTS = [
    ("page twin without the bucket", "  const other = rows.find((x) => x.autres);\n  return other ? { ...other, source: \"autres\" } : null;\n}\nconst VOIE_WORD",
     "  return null;\n}\nconst VOIE_WORD"),
    ("every row marked", "const meV = v === myVoie && mineV && (mineV.source === \"voie\" ? x.voie === vkey : x.autres);", "const meV = v === myVoie && mineV;"),
    ("row label unescaped", "ligne « ${esc(mineV.libelle)} »${mineV.source", "ligne « ${mineV.libelle} »${mineV.source"),
    ("masked table not said", "la formation n'a pas publié son tableau (effectifs trop faibles)", "aucun chiffre"),
    ("route sent for bac général", 'if (prof.serie !== "bg" && typeof prof.voie === "string" && prof.voie)', 'if (typeof prof.voie === "string" && prof.voie)'),
    ("profile label unescaped", ': p.voie_label ? esc(p.voie_label) : "", men', ': p.voie_label ? p.voie_label : "", men'),
    ("closed instead of rare", "Une part faible veut dire « rare », pas « fermé ».", "Une part faible veut dire que la formation est fermée."),
    ("chance wording", "pour voir votre ligne.</p>", "pour voir vos chances d'être admis.</p>"),
    ("Mes vœux cell without its recheck flag", '${r.recoupe === false ? `, pas encore recoupé avec les chiffres de ${esc(r.session)}` : ""}</div>` : prof.voie',
     '</div>` : prof.voie'),
    ("Mes vœux cell shows the candidates", "r ? `${pct1(r.taux)}<div", "r ? `${pct1(r.confirmes)}<div"),
    ("a choice kept across a change of bac", 'const keep = fd.get("serie") === serie && !!fd.get("voie");', 'const keep = !!fd.get("voie");'),
    ("stale stored key kept", "(!codes || p.voie === \"autre\" || codes.includes(p.voie))", "true"),
    ("older-session page claims the bucket", 'if (key !== "autre" && Array.isArray(known) && !known.includes(key)) return null;', ""),
    ("masked bac général table not said (Codex)", '(v === "bg" || v !== myVoie)', "v !== myVoie"),
    ("apprenticeship pointer dropped", ' Beaucoup de BTS se préparent aussi en apprentissage', " Voir la carte"),
]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "voies.py"
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType("suptracker._mut_voies")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("W8 mutation test: rule, normalisation, pick, route, page and wording bugs are each caught")
def w8(c: Ctx):
    fns = [w1, w2, w3, w5, w6, w7, w4]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    for name, old, new in PY_MUTANTS:
        m = mutated(old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M["VO"] = M["VO"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["VO"] = saved
            sys.modules.pop("suptracker._mut_voies", None)
    for name, old, new in JS_MUTANTS:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)"); continue
        src = c.js
        c.js = src.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = src
    n = len(PY_MUTANTS) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    c.con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
