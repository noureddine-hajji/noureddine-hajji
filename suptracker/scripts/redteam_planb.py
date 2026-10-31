"""Red team of "Plan B": the same programme elsewhere, more accessible for the student's profile.

    python scripts/redteam_planb.py --db data/suptracker.duckdb [--real]
"""
from __future__ import annotations

import argparse
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import journey as J  # noqa: E402
from suptracker import planb as PB  # noqa: E402

PROFILES = [dict(serie="bg", dkey="MATHS+SES", mention="ab"), dict(serie="bg", dkey="MATHS+PC", mention="tb", academie="Lyon"),
            dict(serie="bt", mention="b"), dict(serie="bp", mention="sansmention")]
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def sample_targets(con, n=None, seed=3):
    """Mostly selective formations (where a plan B matters), plus some accessible ones."""
    n = n or int(os.environ.get("REDTEAM_PLANB_N", 40))
    rows = con.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy JOIN core.taxonomy_link t USING (session, cod_aff_form)
        WHERE fy.session = (SELECT max(session) FROM core.formation_year) AND fy.taux_acces_ens IS NOT NULL
        ORDER BY fy.taux_acces_ens, fy.cod_aff_form""").fetchall()
    cods = [r[0] for r in rows]
    rng = random.Random(seed)
    low = cods[: max(1, len(cods) // 4)]
    return rng.sample(low, min(n * 3 // 4, len(low))) + rng.sample(cods, min(n // 4, len(cods)))


_RUNS: dict = {}


def runs(con):
    """Every (target, profile) Plan B, computed once and shared by the checks."""
    key = id(con)
    if key not in _RUNS:
        out = []
        for cod in sample_targets(con):
            for prof in PROFILES:
                for paid in (False, True):
                    t0 = time.perf_counter()
                    r = PB.plan_b(con, cod, include_paid=paid, **prof)
                    out.append((cod, prof, paid, r, 1000 * (time.perf_counter() - t0)))
        _RUNS[key] = out
    return _RUNS[key]


def stage_view(con, cod, prof):
    t = con.execute("""SELECT r.spe_type_key FROM core.taxonomy_link l JOIN core.taxonomy_rule r USING (rule_id)
        WHERE l.cod_aff_form = ? AND l.session = (SELECT max(session) FROM core.formation_year)""", [cod]).fetchone()
    res = J.stage2(con, prof.get("dkey"), prof["mention"], t[0], prof.get("academie"), serie=prof["serie"])
    return {f["cod_aff_form"]: f for f in res["formations"]}


@check("B1 every suggestion is more accessible for the profile, re-derived independently from 'Mon parcours'")
def b1(con, real):
    rank = {"hors_profil": 0, "ambitieux": 1, "cible": 2, "securite": 3}
    bad, n = [], 0
    for cod, prof, paid, r, _ in runs(con):
        if not r["alternatives"]:
            continue
        v = stage_view(con, cod, prof)
        t = v[cod]
        tp = t["spos"]["cdf_used"] if t.get("spos") else t["cdf"]
        for a in r["alternatives"]:
            n += 1
            c = v[a["cod_aff_form"]]
            cp = c["spos"]["cdf_used"] if c.get("spos") else c["cdf"]
            zone_up = rank[c["zone"]] > rank[t["zone"]] and not c["uncertain"]
            access_up = rank[c["zone"]] >= rank[t["zone"]] and c["taux_acces_ens"] >= t["taux_acces_ens"] + 15 and cp >= tp
            if not (zone_up or access_up):
                bad.append((cod, a["cod_aff_form"], t["zone"], c["zone"]))
    return not bad, f"{len(bad)} not more accessible {bad[:2]}" if bad else f"{n} suggestions verified"


@check("B2 same programme: every suggestion has exactly the target's detailed programme")
def b2(con, real):
    bad = n = 0
    for cod, prof, paid, r, _ in runs(con):
        for a in r["alternatives"]:
            n += 1
            f = con.execute("""SELECT fil_lib_voe_acc FROM core.formation_year WHERE cod_aff_form = ?
                               AND session = (SELECT max(session) FROM core.formation_year)""", [a["cod_aff_form"]]).fetchone()[0]
            bad += f != r["filiere"]
    return bad == 0, f"{bad}/{n} from another programme"


@check("B3 never a fragile, closed, tiny or unreadable formation")
def b3(con, real):
    bad = []
    for cod, prof, paid, r, _ in runs(con):
        if not r["alternatives"]:
            continue
        v = stage_view(con, cod, prof)
        for a in r["alternatives"]:
            c = v[a["cod_aff_form"]]
            if c["zone"] in ("non_ouvert", "indetermine") or c.get("rate_fragile") or c.get("small_cohort") or c["taux_acces_ens"] is None:
                bad.append(a["cod_aff_form"])
    return not bad, f"{len(bad)} unusable suggestions"


@check("B4 no paid private institution unless asked; asking adds exactly what was hidden, flagged")
def b4(con, real):
    by = {}
    for cod, prof, paid, r, _ in runs(con):
        by.setdefault((cod, tuple(sorted(prof.items()))), {})[paid] = r
    bad = []
    for k, d in by.items():
        free, withp = d[False], d[True]
        if any(a["paid"] for a in free["alternatives"]):
            bad.append((k, "paid in default"))
        if free.get("n_candidates") is not None and withp.get("n_candidates") is not None \
                and withp["n_candidates"] != free["n_candidates"] + free["hidden_paid"]:
            bad.append((k, "hidden count inexact"))
        if any(a["paid"] != (a["contrat_etab"] in PB.PAID_CONTRACTS) for a in withp["alternatives"]):
            bad.append((k, "paid flag wrong"))
    return not bad, f"{bad[:2]}" if bad else f"{len(by)} target × profile pairs"


@check("B5 never the target, never its concours pool, at most 2 per establishment")
def b5(con, real):
    bad = []
    for cod, prof, paid, r, _ in runs(con):
        cods = [a["cod_aff_form"] for a in r["alternatives"]]
        if cod in cods or len(set(cods)) != len(cods):
            bad.append((cod, "self or duplicate"))
        if r["alternatives"]:
            info = {x[0]: x[1:] for x in con.execute(f"""SELECT cod_aff_form, subwish_flag, lib_comp_voe_ins
                FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
                AND cod_aff_form IN ({",".join("?" * (len(cods) + 1))})""", [cod, *cods]).fetchall()}
            t = info.get(cod)
            if t and t[0] and any(info[c][0] and info[c][1] == t[1] for c in cods):
                bad.append((cod, "same concours pool"))
        per = {}
        for a in r["alternatives"]:
            per[(a["etablissement"], a["ville"])] = per.get((a["etablissement"], a["ville"]), 0) + 1
        if per and max(per.values()) > PB.MAX_PER_ETABLISSEMENT:
            bad.append((cod, "too many per establishment"))
    return not bad, f"{bad[:3]}" if bad else "ok"


@check("B6 order: the student's académie first, then nearest; deterministic")
def b6(con, real):
    bad = []
    for cod, prof, paid, r, _ in runs(con):
        al = r["alternatives"]
        acad = prof.get("academie")
        keys = [(0 if acad and a["academie"] == acad else 1, a["km"] if a["km"] is not None else 10 ** 9) for a in al]
        if keys != sorted(keys):
            bad.append(cod)
    cod, prof, paid, r, _ = runs(con)[0]
    again = PB.plan_b(con, cod, include_paid=paid, **prof)
    same = [a["cod_aff_form"] for a in again["alternatives"]] == [a["cod_aff_form"] for a in r["alternatives"]]
    return not bad and same, f"{len(bad)} badly ordered; deterministic: {same}"


@check("B7 a target that is already a safe choice gets no plan B, and the reason says so")
def b7(con, real):
    bad = [cod for cod, prof, paid, r, _ in runs(con) if r["target"] and r["target"]["zone"] == "securite"
           and not r["target"]["uncertain"] and (r["status"] != "deja_accessible" or r["alternatives"])]
    return not bad, f"{len(bad)} safe targets given a plan B"


@check("B8 API: closed lists, 404 on an unknown formation, 422 on a malformed code or missing specialties")
def b8(con, real):
    from fastapi.testclient import TestClient

    from suptracker import api
    path = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()[0]
    cod = runs(con)[0][0]
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"], os.environ["SUPTRACKER_ANALYTICS"] = str(path), "off"
    api._con.cache_clear()
    try:
        c = TestClient(api.app)
        codes = (c.get(f"/api/planb/{cod}", params={"serie": "bt", "mention": "ab"}).status_code,
                 c.get(f"/api/planb/{cod}", params={"serie": "bg", "mention": "ab", "spe1": "MATHS", "spe2": "SES"}).status_code,
                 c.get(f"/api/planb/{cod}", params={"serie": "bg", "mention": "ab"}).status_code,
                 c.get(f"/api/planb/{cod}", params={"serie": "stmg"}).status_code,
                 c.get(f"/api/planb/{cod}", params={"mention": "excellent", "serie": "bt"}).status_code,
                 c.get("/api/planb/999999999", params={"serie": "bt"}).status_code,
                 c.get("/api/planb/1%20OR%201=1", params={"serie": "bt"}).status_code)
    finally:
        os.environ.pop("SUPTRACKER_ANALYTICS", None)
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()
    return codes == (200, 200, 422, 422, 422, 404, 422), f"{codes}"


@check("B9 the UI makes no promise and escapes what it prints")
def b9(con, real):
    from suptracker.api import METHODOLOGY
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    i = js.index("async function loadPlanB")
    block = js[i: js.index("function offerCard", i)]
    promise = re.findall(r"garanti|vous serez admis|sûr d'être|certain d'être", block, re.I)
    raw = [m for m in re.findall(r"\$\{(?!esc\(|fmt\(|pc1\(|ZONES\[|WHY\[|offerBadges\()[^${}`]*\ba\.(?:etablissement|ville|complement|filiere|academie|contrat_etab)\b[^${}`]*\}", block)]
    ok = not promise and not raw and "pas des chances d'admission" in block and "pas des chances" in METHODOLOGY["planb"]
    return ok, f"promises {promise}; unescaped {raw[:2]}"


@check("B10 libellés: an establishment whose name contains ' - ' is stripped from the complement")
def b10(con, real):
    from suptracker.search import clean_complement
    got = clean_complement({"lib_comp_voe_ins": "Université Lumière - Lyon 2 - Licence - Droit - Parcours X",
                            "g_ea_lib_vx": "Université Lumière - Lyon 2", "fili": "Licence", "fil_lib_voe_acc": "Droit",
                            "form_lib_voe_acc": "Licence - Droit-économie-gestion"})
    return got == "Parcours X", repr(got)


@check("B11 latency: a plan B answers fast enough for a page (p95 on the sample, warm)")
def b11(con, real):
    lat = sorted(x[4] for x in runs(con)[4:])
    p95 = lat[int(0.95 * len(lat)) - 1] if lat else 0
    return p95 < 800, f"p50 {statistics.median(lat):.0f} ms, p95 {p95:.0f} ms over {len(lat)} calls"


@check("B12 usefulness: selective targets (ambitieux / hors profil) usually get a plan B (report)")
def b12(con, real):
    hard = [r for _, _, paid, r, _ in runs(con) if not paid and r["target"] and r["target"]["zone"] in ("ambitieux", "hors_profil")]
    got = sum(1 for r in hard if r["alternatives"])
    share = 100 * got / len(hard) if hard else 100
    return (share >= 50 if real else True), f"{got}/{len(hard)} selective targets get at least one suggestion ({share:.0f} %)"


@check("B13 concours commun: a school of the target's pool is never an alternative, and plan_b applies the rule")
def b13(con, real):
    import inspect
    t = {"subwish_flag": True, "complement": "Concours Puissance Alpha"}
    cases = [({"subwish_flag": True, "complement": "Concours Puissance Alpha"}, True),
             ({"subwish_flag": True, "complement": "Concours Avenir"}, False),
             ({"subwish_flag": False, "complement": "Concours Puissance Alpha"}, False),
             ({"subwish_flag": True, "complement": None}, False)]
    wrong = [c for c, want in cases if PB.same_pool(t, c) != want]
    wrong += [None] if PB.same_pool({"subwish_flag": True, "complement": None}, {"subwish_flag": True, "complement": None}) else []
    src = inspect.getsource(PB.plan_b)
    applied = re.search(r"if same_pool\(target, c\):\s*\n\s*continue", src) is not None
    return not wrong and applied, f"wrong verdicts {wrong}; rule applied in plan_b: {applied}"


@check("B14 a late answer never fills or rebinds another formation's card (navigation race)")
def b14(con, real):
    js = (ROOT / "suptracker" / "static" / "app.js").read_text()
    i = js.index("async function loadPlanB")
    block = js[i: js.index("function offerCard", i)]
    after = block[block.index("await api("):]
    guard = re.search(r'getElementById\("planb"\) !== box', after) is not None
    scoped = 'box.querySelector("#pbpaid")' in after and 'document.getElementById("pbpaid")' not in after
    return guard and scoped, f"identity guard after the request: {guard}; toggle looked up inside the card: {scoped}"


def run(db: Path, real: bool = False) -> list[dict]:
    con = duckdb.connect(str(db), read_only=True)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(con, real)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed check
            ok, detail = False, f"crash: {type(exc).__name__}: {exc}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    _RUNS.clear()
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
