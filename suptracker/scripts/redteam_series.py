"""Red team of B4: "Mon parcours" for bac technologique / professionnel students.

    python scripts/redteam_series.py --db data/suptracker.duckdb [--real]
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import journey as J  # noqa: E402

CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()


# every calling-group label of the 2022-2025 SIES exports, and who it admits
GROUPS = {
    "Tous les candidats": (True, True, True),
    "Groupe par defaut": (True, True, True),
    "Voie d'acces generale": (True, True, True),       # ordinary route (vs CEP), not "bac général"
    "Voie d'acces CEP": (False, False, False),
    "Bacheliers technologiques toutes series": (False, True, False),
    "Bacheliers professionnels toutes series": (False, False, True),
    "Autres candidats": (None, None, None),              # residual: resolved per formation
    "Toutes les filles": (None, None, None),
    "Tous les garcons": (None, None, None),
    # spellings and variants found in the 2022-2025 exports
    "Bacheliers professionnels toutes séries": (False, False, True),
    "Bacheliers technologiques toutes séries": (False, True, False),
    "Groupe par défaut": (True, True, True),
    "Voie d'accès CEP": (False, False, False),
    "Voie d'accès générale": (True, True, True),
    "Tous les candidats - Paris": (True, True, True),
    "Tous les candidats - Toulouse": (True, True, True),
    "Tous les candidats sauf les Bac Professionnels": (True, True, False),
    "Tous les candidats sauf les Bac professionnels": (True, True, False),
    "Tous les candidats sauf les Bac technologiques": (True, False, True),
    "Tous les candidats sauf les Bac technologiques et Bac professionnels": (True, False, False),
    "STI2D": (False, None, False),                     # one techno series: depends on the student's
    "Autres formations": (None, None, None),
    "bac francais S": (None, None, None),              # unclear label: never decides
}


@check("S1 calling groups: every real label routes each series to the right group")
def s1(con, real):
    bad = {lab: got for lab, want in GROUPS.items()
           if (got := tuple(J.group_applies(lab, None, None, s) for s in J.SERIES)) != want}
    labels = {r[0] for r in con.execute("""SELECT DISTINCT lib FROM (SELECT lib_grp1 lib FROM core.formation_year
        UNION SELECT lib_grp2 FROM core.formation_year UNION SELECT lib_grp3 FROM core.formation_year) WHERE lib IS NOT NULL""").fetchall()}
    unknown = sorted(labels - set(GROUPS)) if real else []
    return not bad and not unknown, f"wrong {bad}; labels not covered by this table {unknown}" if bad or unknown else f"{len(GROUPS)} labels × 3 series"


@check("S2 part_terminale_* is a composition (sums to 100), and nothing calls it an access rate")
def s2(con, real):
    n, ok = one(con, """SELECT count(*), count(*) FILTER (WHERE abs(part_terminale_generale_en_position_admis_pp
        + part_terminale_techno_en_position_admis_pp + part_terminale_pro_en_position_admis_pp - 100) <= 2)
        FROM core.formation_year WHERE part_terminale_generale_en_position_admis_pp IS NOT NULL""")
    from suptracker.api import METHODOLOGY
    from suptracker.indicators import PEER_METRICS
    from suptracker.schema import FIELD_BY_NAME
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    wording = ("composition" in METHODOLOGY["part_terminale_generale_en_position_admis_pp"]
               and all("parmi les candidats" in FIELD_BY_NAME[f"part_terminale_{x}_en_position_admis_pp"].label
                       for x in ("generale", "techno", "pro"))
               and "parmi les candidats" in PEER_METRICS["part_terminale_generale_en_position_admis_pp"][2]
               and "en position d'admis (PP)\" +" not in js and "Terminales générales en position d'admis" not in js)
    share = 100 * ok / n if n else 100
    return (share >= 99 or not real) and wording, f"sums to 100 on {share:.1f} % of rows; wording {'fixed' if wording else 'STILL WRONG'}"


@check("S3 series counts are consistent (proposals <= candidates, sum <= total, admits <= proposals)")
def s3(con, real):
    n, bad = one(con, """SELECT count(*), count(*) FILTER (WHERE
           prop_tot_bt > nb_voe_pp_bt + coalesce(nb_voe_pc_bt, 0) OR prop_tot_bp > nb_voe_pp_bp + coalesce(nb_voe_pc_bp, 0)
        OR prop_tot_bg + prop_tot_bt + prop_tot_bp > prop_tot OR acc_bt > prop_tot_bt OR acc_bp > prop_tot_bp)
        FROM core.formation_year WHERE prop_tot_bt IS NOT NULL""")
    return bad <= 0.01 * max(1, n), f"{bad}/{n} inconsistent rows"


@check("S4 estimated access: bounded, = official rate when the series does as well, undefined stays undefined")
def s4(con, real):
    mem = duckdb.connect()
    mem.execute("""CREATE TABLE fy AS SELECT * FROM (VALUES
        (60.0, 50, 100, 0, 50, 100, 0),     -- series as successful as all: estimate = official
        (60.0, 50, 100, 0, 25, 100, 0),     -- half as successful: 30
        (90.0, 50, 100, 0, 100, 100, 0),    -- twice as successful: capped at 100
        (60.0, 50, 100, 0, 0, 100, 0),      -- never proposed: 0
        (0.0, 0, 100, 0, 0, 29, 0),         -- nobody proposed at all: undefined, NOT 100 (review)
        (NULL, 50, 100, 0, 50, 100, 0),     -- no official rate: undefined
        (60.0, 50, 100, 0, 5, 0, 0))        -- no series candidate: undefined
        t(taux_acces_ens, prop_tot, nb_voe_pp, nb_voe_pc, prop_tot_bt, nb_voe_pp_bt, nb_voe_pc_bt)""")
    got = [None if r[0] is None else round(r[0], 6)
           for r in mem.execute(f"SELECT {J.series_access_sql('bt')} FROM fy").fetchall()]
    return got == [60.0, 30.0, 100.0, 0.0, None, None, None], f"{got}"


@check("S5 units: stage 1 counts people (admits), never sums candidates across formations")
def s5(con, real):
    import inspect
    src = inspect.getsource(J.stage1_series)
    sums = re.findall(r"sum\(([^)]*)\)", src)
    bad = [x for x in sums if "nb_voe" in x or "prop_tot" in x]
    r = J.stage1_series(con, "bt")
    cov = r["coverage"]
    return not bad and 0 < cov <= 1.0 + 1e-9, f"sums {sums}; destination shares add up to {cov:.3f} (linked formations)"


@check("S6 no false closure: a licence stays open to techno / pro students; techno CPGE welcome them")
def s6(con, real):
    lic = J.stage2(con, None, "b", "licence sciences juridiques", serie="bt")["formations"]
    closed = sum(f["zone"] == "non_ouvert" for f in lic)
    ok = closed <= 0.05 * max(1, len(lic))
    detail = f"licence droit: {closed}/{len(lic)} marked closed"
    if real:
        cp = J.stage2(con, None, "tb", "cpge s", serie="bt")["formations"]
        tsi = [f for f in cp if f["filiere"] == "TSI"]
        mpsi_safe = [f for f in cp if f["filiere"] in ("MPSI", "PCSI") and f["zone"] == "securite"]
        good_tsi = sum(f["zone"] in ("securite", "cible") for f in tsi)
        ok &= len(tsi) > 0 and good_tsi >= 0.6 * len(tsi) and not mpsi_safe
        detail += f"; TSI sécurité/cible {good_tsi}/{len(tsi)}; MPSI/PCSI shown as sécurité: {len(mpsi_safe)}"
    return ok, detail


@check("S7 a rate over fewer than 20 series candidates never sets a zone")
def s7(con, real):
    types = [r[0] for r in con.execute("SELECT DISTINCT spe_type_key FROM core.taxonomy_rule").fetchall()]
    bad = n = 0
    for t in types:
        for se in ("bt", "bp"):
            for f in J.stage2(con, None, "ab", t, serie=se)["formations"]:
                if f["rate_fragile"]:
                    n += 1
                    bad += f["zone"] not in ("indetermine", "non_ouvert")
    return bad == 0, f"{n} fragile readings, {bad} with a zone"


@check("S8 mention bounds for techno / pro: valid and sharp, as for bac général")
def s8(con, real):
    import redteam_mentions as M
    rng = random.Random(8)
    invalid = loose = tested = 0
    for _ in range(20_000):
        t, u = M.random_table(rng, rng.choice((2, 5, 40)))
        c = M.margins(t, u)
        for se in ("bt", "bp"):
            for m in M.LADDER[:4]:
                b = J.series_cdf_bounds(se, m, c)
                if b is None:
                    continue
                k = sum(t[se][x] for x in M.LADDER[: M.LADDER.index(m) + 1])
                if not (b[0] <= k and k + u[se] <= b[1]):
                    invalid += 1
    # sharpness by brute force on the series row, small tables
    while tested < 200:
        t, u = M.random_table(rng, 2)
        c = M.margins(t, u)
        if not c["acc_bt"] or sum(c[f"acc_{m}"] for m in M.LADDER) + c["acc_mention_non_renseignee"] > 12:
            continue
        tested += 1
        swapped = {**c, "acc_bg": c["acc_bt"], "acc_bt": c["acc_bg"], "acc_bg_mention": c["acc_bt_mention"],
                   "acc_bt_mention": c["acc_bg_mention"]}           # bt plays the role of bg
        for m in M.LADDER[:4]:
            rows = list(M.all_bg_rows(swapped))
            j = M.LADDER.index(m)
            reach = (min(sum(r[: j + 1]) for r in rows), max(sum(r[: j + 1]) + r[5] for r in rows))
            if J.series_cdf_bounds("bt", m, c) != reach:
                loose += 1
    return invalid == 0 and loose == 0, f"{invalid} invalid, {loose} non-sharp ({tested} brute-forced tables)"


@check("S9 bac général is unchanged: the default call and serie='bg' agree, persona invariants hold")
def s9(con, real):
    a = J.stage2(con, "MATHS+SES", "ab", "cpge ecg")
    b = J.stage2(con, "MATHS+SES", "ab", "cpge ecg", serie="bg")
    za = [(f["cod_aff_form"], f["zone"], f["uncertain"]) for f in a["formations"]]
    zb = [(f["cod_aff_form"], f["zone"], f["uncertain"]) for f in b["formations"]]
    ect_open = [f for f in a["formations"] if "ECT" in (f["filiere"] or "") and f["zone"] != "non_ouvert"]
    return za == zb and not ect_open, f"{len(za)} formations identical; CPGE ECT open to bac général: {len(ect_open)}"


@check("S10 API: series is a closed list; techno / pro need no specialties; bac général still does")
def s10(con, real):
    import os
    from fastapi.testclient import TestClient

    from suptracker import api
    path = one(con, "SELECT path FROM duckdb_databases() WHERE database_name = current_database()")[0]
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(path)
    os.environ["SUPTRACKER_ANALYTICS"] = "off"
    api._con.cache_clear()
    try:
        c = TestClient(api.app)
        codes = (c.get("/api/journey/stage1", params={"serie": "bt"}).status_code,
                 c.get("/api/journey/stage1", params={"serie": "stmg"}).status_code,
                 c.get("/api/journey/stage1").status_code,
                 c.get("/api/journey/stage2", params={"serie": "bp", "mention": "ab", "type": "bts production"}).status_code,
                 c.get("/api/journey/stage2", params={"serie": "bg", "mention": "ab", "type": "bts production"}).status_code)
    finally:
        os.environ.pop("SUPTRACKER_ANALYTICS", None)
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()
    return codes == (200, 422, 422, 200, 422), f"{codes}"


@check("S11 the UI says what is estimated and that STMG / STI2D / ST2S cannot be told apart")
def s11(con, real):
    from suptracker.api import METHODOLOGY
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    t = METHODOLOGY.get("serie_offer", "")
    ok = all(w in t for w in ("estimation", "STMG", "ne distingue pas", "plafonné"))
    ok &= "STMG, STI2D, ST2S" in js and "Accès estimé" in js and "estim. ·" in js and "Estimation. Taux de proposition" in js
    # the series code may only be used as a key into a closed label table, never printed raw
    raw = [m for m in re.findall(r"\$\{(?:f\.)?serie\}", js)]
    return ok and not raw, f"disclosure {'ok' if ok else 'MISSING'}; raw serie interpolations {raw}"


@check("S12 plausibility: techno and pro students are steered where their peers actually go")
def s12(con, real):
    if not real:
        return True, "real data only"
    bt = {f["type_key"]: f["gate"] for f in J.stage1_series(con, "bt")["filieres"]}
    bp = {f["type_key"]: f["gate"] for f in J.stage1_series(con, "bp")["filieres"]}
    want = [(bt, "bts service", "predilection"), (bt, "but service", "predilection"), (bp, "bts production", "predilection"),
            (bp, "bts service", "predilection")]
    bad = [(k, g, d.get(k)) for d, k, g in want if d.get(k) != g]
    not_pred = [k for k in ("pass", "licence l as") if bp.get(k) == "predilection"]
    return not bad and not not_pred, f"mismatch {bad}; PASS / L.AS predilection for bac pro: {not_pred}"


@check("S13 no zone without a rate: a formation whose (estimated) access is unknown is never sécurité / cible / ambitieux")
def s13(con, real):
    types = [r[0] for r in con.execute("SELECT DISTINCT spe_type_key FROM core.taxonomy_rule").fetchall()]
    bad, n = [], 0
    for t in types:
        for se, d in (("bg", "MATHS+SES"), ("bt", None), ("bp", None)):
            for f in J.stage2(con, d, "tb", t, serie=se)["formations"]:
                n += 1
                if f["taux_acces_ens"] is None and f["zone"] in ("securite", "cible", "ambitieux", "hors_profil"):
                    bad.append((se, t, f["cod_aff_form"], f["zone"]))
    return not bad, f"{len(bad)} zoned without a rate {bad[:3]}" if bad else f"{n} readings, none zoned without a rate"


def run(db: Path, real: bool = False) -> list[dict]:
    con = duckdb.connect(str(db), read_only=True)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(con, real)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']}\n       {r['detail']}")
    bad = [r for r in res if not r["ok"]]
    print(f"\n{len(res) - len(bad)}/{len(res)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
