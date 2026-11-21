"""Red team of the apprenticeship offers whose type the cartographie writes alone while their initial formations carry a LIST of
types (owner, 2026-11-21: « BTS - Management en hôtellerie restauration » under « BTS - BTSA - BTSM » for the offers, under
« Formations aux métiers de l'hôtellerie restauration,BTS - BTSA - BTSM » for the initial formations). Rule: carte.part_votes
(a reading only when EVERY SIES formation whose type list contains the offer's type, with the same mention label, reads the same)
and the attachment by one part of the type list (same UAI, same mention label, same reading).

    python scripts/redteam_types_liste.py [--db data/suptracker.duckdb] [--real]

  TY1 a crafted warehouse: each offer's diploma, mention and attached formations equal a table written by hand (a list type
      read through its part; a split reading keeps the raw label; another UAI, another reading, SIES's own apprenticeship rows
      and a part the offer's type is not do not attach; the whole-label vote and attachment are unchanged).
  TY2 --real: every offer of the latest cartographie re-derived by an independent reading (own split, own unanimity, own
      attachment); no BTS offer keeps a « BTS - … » / « BTSA - … » label whose name SIES publishes as a BTS mention; the four
      owner-visible cases (hôtellerie restauration, sanitaire et social, aménagements paysagers, économie sociale familiale)
      classed; enough offers read and attached through the parts.
  TY3 --real: the BTS mention filter has no group SIES does not publish (each offer is under a SIES BTS mention).
  TY4 docs and wiring: README, CLAUDE.md, durations.json, the test file.
  TY5 mutation test of TY1-TY3 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
BTS = "BTS - BTSA - BTSM"
MHR, SP3S, CG = "Management en hôtellerie restauration", "Services et prestations des secteurs sanitaire et social", "Comptabilité et gestion"


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

    def mod(self):
        return load("carte", self.src["carte"])


# ------------------------------------------------------------------ TY1 a crafted warehouse
FY_COLS = "cod_aff_form VARCHAR, session INTEGER, fili VARCHAR, form_lib_voe_acc VARCHAR, fil_lib_voe_acc VARCHAR, lib_for_voe_ins VARCHAR, " \
          "cod_uai VARCHAR, apprentissage BOOLEAN, dep_lib VARCHAR, acad_mies VARCHAR"
CA_COLS = "cod_aff_form VARCHAR, fiche_url VARCHAR, lat DOUBLE, lon DOUBLE, carto_session INTEGER, etablissement_id_paysage VARCHAR, " \
          "composante_id_paysage VARCHAR, apprentissage BOOLEAN, internat VARCHAR, distance VARCHAR, amenag_sport BOOLEAN, amenag_art BOOLEAN, " \
          "etab_uai VARCHAR, etab_nom VARCHAR, types_etab VARCHAR, type_formation VARCHAR, nom_long VARCHAR, mention_lib VARCHAR, " \
          "commune VARCHAR, departement VARCHAR"
HR = f"Formations aux métiers de l'hôtellerie restauration,{BTS}"
SOC = f"Formations diplômantes du travail social,Etudes de santé,{BTS}"
# SIES formations: code, uai, fili, form label, SIES mention, cartographie type, cartographie mention, SIES apprenticeship
INITIAL = [("1", "U1", "BTS", "BTS", MHR, HR, f"BTS - {MHR}", False),
           ("2", "U2", "BTS", "BTS", MHR, HR, f"BTS - {MHR}", False),
           ("3", "U1", "BTS", "BTS", SP3S, SOC, f"BTS - {SP3S}", False),
           ("4", "U3", "BTS", "BTS", "Ambigu", f"A,{BTS}", "X - Ambigu", False),
           ("5", "U3", "Autre", "Mise à niveau", "Ambigu", f"B,{BTS}", "X - Ambigu", False),     # same part and label, another reading
           ("6", "U4", "BTS", "BTS", CG, BTS, f"BTS - {CG}", False),
           ("7", "U4", "BTS", "BTS", CG, f"I.A.E - Instituts d'administration des entreprises,{BTS}", f"BTS - {CG}", False),
           ("8", "U5", "BTS", "BTS", MHR, HR, f"BTS - {MHR}", True),                               # SIES's own apprenticeship row
           ("9", "U6", "Autre", "Mise à niveau", CG, f"Y,{BTS}", f"BTS - {CG}", False)]           # same part and label, other reading
# apprenticeship offers: code, uai, cartographie type, cartographie mention -> (diploma, mention, attached)
OFFERS = [("10", "U1", BTS, f"BTS - {MHR}", (BTS, MHR, ["1"])),
          ("11", "U9", BTS, f"BTS - {MHR}", (BTS, MHR, [])),
          ("12", "U1", BTS, f"BTS - {SP3S}", (BTS, SP3S, ["3"])),
          ("13", "U3", BTS, "X - Ambigu", (BTS, "X - Ambigu", [])),
          ("14", "U4", BTS, f"BTS - {CG}", (BTS, CG, ["6", "7"])),
          ("15", "U5", BTS, f"BTS - {MHR}", (BTS, MHR, [])),
          ("16", "U1", "Licence", f"BTS - {MHR}", ("Licence", f"BTS - {MHR}", [])),
          ("17", "U6", BTS, f"BTS - {CG}", (BTS, CG, [])),
          ("18", "U2", HR, f"BTS - {MHR}", (BTS, MHR, ["2"]))]


def crafted() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute(f"CREATE TABLE core.formation_year ({FY_COLS})")
    con.execute(f"CREATE TABLE core.cartographie ({CA_COLS})")
    for cod, uai, fili, form, fil, tf, ml, app in INITIAL:
        con.execute("INSERT INTO core.formation_year VALUES (?, 2025, ?, ?, ?, ?, ?, ?, 'Yonne', 'Dijon')",
                    [cod, fili, form, fil, f"{form} - {fil}", uai, app])
        con.execute("INSERT INTO core.cartographie VALUES (?, NULL, 47.0, 3.0, 2026, NULL, NULL, ?, 'non', 'aucune', false, false, ?, 'Lycée', "
                    "'Publics', ?, ?, ?, 'Auxerre', 'Yonne')", [cod, app, uai, tf, f"{form} - {fil}", ml])
    for cod, uai, tf, ml, _ in OFFERS:
        con.execute("INSERT INTO core.cartographie VALUES (?, ?, 47.0, 3.0, 2026, NULL, NULL, true, 'non', 'aucune', false, false, ?, ?, "
                    "'Publics', ?, 'en apprentissage', ?, 'Auxerre', 'Yonne')",
                    [cod, f"https://dossierappel.parcoursup.fr/x?g_ta_cod={cod}", uai, f"CFA {cod}", tf, ml])
    return con


@check("TY1 crafted warehouse: diploma, mention and attachment of each offer equal a table written by hand")
def ty1(c: Ctx):
    CA = c.mod()
    got = {a["cod_aff_form"]: (a["diplome"], a["mention"], a["rattachee"]) for a in CA.apprentissage(crafted())}
    bad = [(cod, got.get(cod), want) for cod, _, _, _, want in OFFERS if got.get(cod) != want]
    return not bad, f"{len(OFFERS)} crafted offers; problems {bad[:3]}"


# ------------------------------------------------------------------ TY2 / TY3 real data
def parts_of(tf) -> list:
    """Independent: the types of a cartographie list, as written between its commas."""
    return [p for p in (x.strip() for x in (tf or "").split(",")) if p]


def rt_readings(con, CA) -> tuple[dict, dict, dict, list]:
    """Independent: whole-label votes {(tf, fl): {reading: n}}, part readings {(part, fl): {readings}}, the latest campaign's
    initial formations [(code, {uais}, tf, fl, reading)], and the offers [(code, uai, tf, fl)]."""
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    whole, part, ini = {}, {}, []
    for cod, u1, u2, tf, fl, fili, form, fil, lib, app in con.execute("""
            SELECT f.cod_aff_form, f.cod_uai, c.etab_uai, c.type_formation, c.mention_lib, f.fili, f.form_lib_voe_acc,
                   f.fil_lib_voe_acc, f.lib_for_voe_ins, f.apprentissage
            FROM core.formation_year f, core.cartographie c WHERE c.cod_aff_form = f.cod_aff_form AND f.session = ?
            AND c.type_formation IS NOT NULL""", [latest]).fetchall():
        r = CA.diplome_of(fili, form, fil, lib)
        whole.setdefault((tf, fl), {}).setdefault(r, 0)
        whole[(tf, fl)][r] += 1
        for p in parts_of(tf):
            part.setdefault((p, fl), set()).add(r)
        if app is not True:
            ini.append((cod, {u1, u2} - {None, ""}, tf, fl, r))
    offers = con.execute("""SELECT cod_aff_form, etab_uai, type_formation, mention_lib FROM core.cartographie WHERE apprentissage IS TRUE
        AND carto_session = (SELECT max(carto_session) FROM core.cartographie)
        AND cod_aff_form NOT IN (SELECT cod_aff_form FROM core.formation_year WHERE session = ?)""", [latest]).fetchall()
    return whole, part, ini, offers


@check("TY2 real data: every offer re-derived (reading through a part, attachment by a part); no raw « BTS - … » label SIES names")
def ty2(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    CA = c.mod()
    con = duckdb.connect(str(c.db), read_only=True)
    whole, part, ini, offers = rt_readings(con, CA)
    by_part: dict = {}
    for cod, uais, tf, fl, r in ini:
        for u in uais:
            for p in parts_of(tf):
                by_part.setdefault((u, p, fl), []).append((cod, r))
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    sies_bts = {r[0] for r in con.execute("SELECT fil_lib_voe_acc FROM core.formation_year WHERE fili = 'BTS' AND session = ?", [latest]).fetchall()}
    got = {a["cod_aff_form"]: a for a in CA.apprentissage(con)}
    bad, n_read, n_att = [], 0, 0
    for cod, uai, tf, fl in offers:
        a = got[cod]
        if (tf, fl) not in whole and len(part.get((tf, fl), ())) == 1:
            n_read += 1
            want = next(iter(part[(tf, fl)]))
            if (a["diplome"], a["mention"]) != want:
                bad.append((cod, "reading", (a["diplome"], a["mention"]), want))
        reading = (a["diplome"], a["mention"])
        want_att = {y for y, r in by_part.get((uai, tf, fl), ()) if r == reading} if uai else set()
        if not want_att <= set(a["rattachee"]):
            bad.append((cod, "not attached", sorted(want_att), a["rattachee"]))
        extra = set(a["rattachee"]) - want_att - {y for y, us, tf2, fl2, _ in ini if uai in us and (tf2, fl2) == (tf, fl)}
        if extra and a["diplome"] != "BUT":
            bad.append((cod, "attached beyond the rule", sorted(extra)))
        n_att += bool(want_att - {y for y, us, tf2, fl2, _ in ini if uai in us and (tf2, fl2) == (tf, fl)})
        m = a["mention"] or ""
        for pre in ("BTS - ", "BTSA - "):
            if a["diplome"] == BTS and m.startswith(pre) and m[len(pre):] in sies_bts:
                bad.append((cod, "raw BTS label", m))
    seen = {a["mention"] for a in got.values() if a["diplome"] == BTS}
    for name in (MHR, SP3S, "Aménagements paysagers", "Economie sociale familiale"):
        if name in sies_bts and name not in seen:
            bad.append(("owner case not classed", name))
    if n_read < 500 or n_att < 100:
        bad.append(("too few", n_read, n_att))
    return not bad, f"{len(offers)} offers; {n_read} read through a part of the type list, {n_att} attached only through it; problems {bad[:3]}"


@check("TY3 real data: every BTS group of the mention filter is a mention SIES publishes")
def ty3(c: Ctx):
    if not c.real:
        return True, "skipped (no --real)"
    CA = c.mod()
    con = duckdb.connect(str(c.db), read_only=True)
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    sies = {CA.groupe_of(BTS, r[0]) for r in con.execute("SELECT fil_lib_voe_acc FROM core.formation_year WHERE fili = 'BTS' AND session = ?",
                                                          [latest]).fetchall()}
    groups = next((d["mentions"] for d in CA.facets(con)["diplomes"] if d["label"] == BTS), [])
    extra = [g["label"] for g in groups if g["label"] not in sies]
    return not extra and len(groups) > 50, f"{len(groups)} BTS groups; not published by SIES: {extra[:5]}"


# ------------------------------------------------------------------ TY4 docs
@check("TY4 docs and wiring: README, CLAUDE.md, durations.json, the test file")
def ty4(c: Ctx):
    bad = []
    if "Types en liste" not in (ROOT / "README.md").read_text() or "redteam_types_liste.py" not in (ROOT / "README.md").read_text():
        bad.append("README")
    cl = (ROOT.parent / "CLAUDE.md").read_text()
    if "carte.part_votes" not in cl or "redteam_types_liste.py" not in cl:
        bad.append("CLAUDE.md")
    if "tests/test_types_liste.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations.json")
    if not (ROOT / "tests" / "test_types_liste.py").exists():
        bad.append("test file")
    return not bad, f"problems {bad}"


MUTANTS = [
    ("split reading kept", "    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}",
     "    return {k: sorted(v)[0] for k, v in seen.items()}", "TY1"),
    ("part vote ignored", "d, m = pair.get((tf, fl)) or parts.get((tf, fl)) or", "d, m = pair.get((tf, fl)) or", "TY1"),
    ("part vote ignored (real)", "d, m = pair.get((tf, fl)) or parts.get((tf, fl)) or", "d, m = pair.get((tf, fl)) or", "TY2"),
    ("no attachment by a part", "            att |= {y for y, dm in initial_part.get((uai, tf, fl), ()) if dm == (d, m)}", "            pass", "TY1"),
    ("no attachment by a part (real)", "            att |= {y for y, dm in initial_part.get((uai, tf, fl), ()) if dm == (d, m)}", "            pass", "TY2"),
    ("reading not compared", "initial_part.get((uai, tf, fl), ()) if dm == (d, m)}", "initial_part.get((uai, tf, fl), ())}", "TY1"),
    ("attached across establishments", "{y for y, dm in initial_part.get((uai, tf, fl), ()) if dm == (d, m)}",
     "{y for (u2, p2, f2), ys in initial_part.items() if (p2, f2) == (tf, fl) for y, dm in ys if dm == (d, m)}", "TY1"),
    ("SIES's apprenticeship rows taken as initial",
     "            WHERE f.session = (SELECT max(session) FROM core.formation_year) AND c.type_formation IS NOT NULL\n"
     "              AND NOT coalesce(f.apprentissage, false)\"\"\").fetchall():\n        dm = diplome_of(*lab)",
     "            WHERE f.session = (SELECT max(session) FROM core.formation_year) AND c.type_formation IS NOT NULL\n"
     "              \"\"\").fetchall():\n        dm = diplome_of(*lab)", "TY1"),
    ("the whole list taken as a part", '    return [x.strip() for x in (tf or "").split(",") if x.strip()]', '    return [tf] if tf else []', "TY1"),
    ("filter keeps raw labels", "d, m = pair.get((tf, fl)) or parts.get((tf, fl)) or", "d, m = pair.get((tf, fl)) or", "TY3"),
]


@check("TY5 mutation test: every seeded reading and attachment bug is caught")
def ty5(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:4] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught, n = [], 0, 0
    for name, old, new, target in MUTANTS:
        if target in ("TY2", "TY3") and not c.real:
            continue
        n += 1
        src = c.src["carte"]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
            continue
        m = copy.copy(c)
        m.src = dict(c.src, carte=src.replace(old, new, 1))
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
