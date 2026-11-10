"""Red team of sprint 11, "Mes vœux" (the student's list read for the current profile).

    python scripts/redteam_voeux.py [--db data/suptracker.duckdb] [--real]

Checks:
  V1 every vœu gets the zone of "Mon parcours" (the full-type stage2 row) and of Plan B, for several profiles
  V2 the `only` restriction of stage2 changes no row (all types)
  V3 the reading of the list is re-derived with the red team's own rules: counts only, an uncertain safety never counts
  V4 API: hostile inputs (11 codes, bad codes, SQL-like, duplicates, unknown codes, missing / equal specialties,
     unknown mention or series), no analytics event, the profile changes the zones
  V5 page: escaping, stored list never trusted, navigation race, wording (no chance, no ranking, privacy), wiring
  V6 mutation test: seeded bugs in the reading, the evaluation and the page must each be caught
  V7 "Compléter ma liste" re-derived: only without a sure safety, Plan B's rules restricted to a sure safety
  V8 its API (inputs, no analytics, no-store) and its card (escaping, labels, race, wording, wiring)
  V9 mutation test of "Compléter ma liste"
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import journey as J  # noqa: E402
from suptracker import planb as PB  # noqa: E402
from suptracker import voeux as VX  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def profiles():
    out = [("bg", "ab"), ("bg", "tb"), ("bt", "b"), ("bp", "sansmention")]
    spe = [s for s in ("MATHS", "SES", "PC") if s in J.SPECIALTIES]
    res = []
    for serie, m in out:
        if serie == "bg":
            for a, b in (("MATHS", "SES"), ("MATHS", "PC")):
                if a in spe and b in spe:
                    res.append((serie, J.doublette_key(a, b), m))
                    break
        else:
            res.append((serie, None, m))
    return res


class Ctx:
    def __init__(self, db: Path, real: bool):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        c = self.con
        self.latest = c.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        typed = c.execute("""SELECT fy.cod_aff_form, r.spe_type_key FROM core.formation_year fy
            JOIN core.taxonomy_link t USING (session, cod_aff_form) JOIN core.taxonomy_rule r USING (rule_id)
            WHERE fy.session = ? ORDER BY fy.cod_aff_form""", [self.latest]).fetchall()
        self.type_of = dict(typed)
        untyped = [r[0] for r in c.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy
            LEFT JOIN core.taxonomy_link t USING (session, cod_aff_form) WHERE fy.session = ? AND t.cod_aff_form IS NULL
            ORDER BY 1 LIMIT 3""", [self.latest]).fetchall()]
        rng = random.Random(11)
        cods = sorted(self.type_of)
        self.lists = [rng.sample(cods, min(10, len(cods))) for _ in range(4 if real else 3)]
        self.lists.append((rng.sample(cods, min(7, len(cods))) + untyped[:1] + ["999999999"])[:10])
        self.profiles = profiles()
        self._full = {}

    def full(self, serie, dkey, mention, tk):
        k = (serie, dkey, mention, tk)
        if k not in self._full:
            self._full[k] = {f["cod_aff_form"]: f for f in J.stage2(self.con, dkey, mention, tk, None, serie=serie)["formations"]}
        return self._full[k]


def ref_reading(voeux: list[dict]) -> dict:
    """The red team's own reading: counts per zone and the fixed messages (written apart from voeux.read_list)."""
    zones = [v["zone"] for v in voeux]
    cnt = lambda z: sum(1 for x in zones if x == z)  # noqa: E731
    situated = cnt("securite") + cnt("cible") + cnt("ambitieux") + cnt("hors_profil")
    sure = len([v for v in voeux if v["zone"] == "securite" and v["uncertain"] is False])
    codes = []
    if voeux:
        if sure == 0:
            codes.append("aucune_securite")
        if situated > 0 and 2 * (cnt("ambitieux") + cnt("hors_profil")) > situated:
            codes.append("majorite_ambitieuse")
        if cnt("hors_profil") > 0:
            codes.append("hors_profil")
        if cnt("non_ouvert") > 0:
            codes.append("non_ouvert")
        if cnt("indetermine") + len([v for v in voeux if v["status"] != "ok"]) > 0:
            codes.append("non_situe")
        if situated > 0 and cnt("cible") == 0:
            codes.append("aucune_cible")
        codes = codes or ["equilibree"]
    return {"codes": codes, "sure": sure, "situated": situated}


# ---------------------------------------------------------------- checks
@check("V1 every vœu has the zone of 'Mon parcours' (full-type stage2 row) and of Plan B, for every profile")
def v1(c: Ctx):
    bad, n, npb = [], 0, 0
    for serie, dkey, mention in c.profiles:
        for L in c.lists:
            d = VX.evaluate(c.con, L, serie=serie, dkey=dkey, mention=mention)
            if [v["cod_aff_form"] for v in d["voeux"]] != list(dict.fromkeys(L)):
                bad.append(("order", serie))
            for v in d["voeux"]:
                n += 1
                tk = c.type_of.get(v["cod_aff_form"])
                full = c.full(serie, dkey, mention, tk).get(v["cod_aff_form"]) if tk else None
                if full is None:
                    if v["status"] == "ok":
                        bad.append((v["cod_aff_form"], "situated without a row"))
                    continue
                pos = full["spos"]["cdf_used"] if full.get("spos") else full.get("cdf")
                if (v["zone"], v["uncertain"], v["taux_acces_ens"], v["position"]) != (full["zone"], full["uncertain"], full["taux_acces_ens"], pos):
                    bad.append((v["cod_aff_form"], serie, mention, v["zone"], full["zone"]))
                if v["zone"] in PB.ZONE_RANK and npb < (12 if c.real else 30):
                    npb += 1
                    t = PB.plan_b(c.con, v["cod_aff_form"], serie=serie, dkey=dkey, mention=mention)
                    if t["target"] and (t["target"]["zone"], t["target"]["uncertain"]) != (v["zone"], v["uncertain"]):
                        bad.append((v["cod_aff_form"], "plan B", t["target"]["zone"], v["zone"]))
    return not bad and n > 0, f"{n} vœux × profiles, {npb} Plan B targets; {len(bad)} differ {bad[:3]}"


@check("V2 restricting stage2 to the listed codes changes no row (every type, a sample of codes)")
def v2(c: Ctx):
    bad, n = [], 0
    types = sorted(set(c.type_of.values()))
    serie, dkey, mention = c.profiles[0]
    for tk in types[: (12 if c.real else len(types))]:
        full = c.full(serie, dkey, mention, tk)
        some = sorted(full)[::max(1, len(full) // 5)]
        part = J.stage2(c.con, dkey, mention, tk, None, serie=serie, only=some)["formations"]
        n += len(part)
        if {f["cod_aff_form"] for f in part} != set(some) or any(f != full[f["cod_aff_form"]] for f in part):
            bad.append(tk)
    return not bad and n > 0, f"{n} rows over {min(len(types), 12 if c.real else len(types))} types; differ in {bad[:3]}"


@check("V3 the reading counts zones with fixed rules (re-derived); an uncertain safety never counts as sure")
def v3(c: Ctx):
    bad, n = [], 0
    rng = random.Random(3)
    zs = [None, "securite", "cible", "ambitieux", "hors_profil", "indetermine", "non_ouvert"]
    cases = [[]]
    for _ in range(400):         # synthetic lists: every combination of zones, uncertainty and status
        k = rng.randint(1, 10)
        cases.append([{"zone": (z := rng.choice(zs)), "uncertain": rng.random() < .3,
                       "status": "ok" if z else rng.choice(["absente", "non_situable"])} for _ in range(k)])
    for serie, dkey, mention in c.profiles[:2]:
        for L in c.lists:
            cases.append(VX.evaluate(c.con, L, serie=serie, dkey=dkey, mention=mention)["voeux"])
    for vs in cases:
        n += 1
        got, ref = VX.read_list(vs), ref_reading(vs)
        if [m["code"] for m in got["messages"]] != ref["codes"] or got["securite_sure"] != ref["sure"] or got["situes"] != ref["situated"]:
            bad.append(([m["code"] for m in got["messages"]], ref["codes"]))
        z = got["zones"]
        if sum(z[k] for k in ("securite", "cible", "ambitieux", "hors_profil", "indetermine", "non_ouvert")) + z["non_situe"] != len(vs):
            bad.append("counts do not add up")
        if any(m["niveau"] not in ("warn", "info") for m in got["messages"]):
            bad.append("level")
    return not bad, f"{n} lists, {len(bad)} wrong {bad[:2]}"


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    calls = []
    saved = A.record
    A.record = lambda *a, **k: calls.append(a) or "ok"
    try:
        yield TestClient(api.app), calls
    finally:
        A.record = saved
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


@check("V4 API: 11 codes, bad or SQL-like codes, missing / equal specialties, unknown mention or series are refused; "
       "duplicates once; unknown codes flagged; no analytics event; the profile changes the zones")
def v4(c: Ctx):
    L = c.lists[0]
    bg = {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "ab"}
    with client(c.db) as (cl, calls):
        g = lambda **p: cl.get("/api/voeux", params=p)  # noqa: E731
        codes = (g(ids=",".join(L), **bg).status_code,
                 g(ids=",".join(str(10000 + i) for i in range(11)), serie="bt").status_code,
                 g(ids="1 OR 1=1", serie="bt").status_code,
                 g(ids="12a", serie="bt").status_code,
                 g(ids=L[0], serie="bg", mention="ab").status_code,
                 g(ids=L[0], serie="bg", spe1="MATHS", spe2="MATHS").status_code,
                 g(ids=L[0], serie="bt", mention="excellent").status_code,
                 g(ids=L[0], serie="stmg").status_code,
                 g(ids="", serie="bt").status_code)
        dup = g(ids=f"{L[0]},{L[0]}, {L[1]},,", serie="bt").json()
        unk = g(ids="999999999", serie="bt").json()
        zb = [v["zone"] for v in g(ids=",".join(L), **{**bg, "mention": "sansmention"}).json()["voeux"]]
        zt = [v["zone"] for v in g(ids=",".join(L), **{**bg, "mention": "tb"}).json()["voeux"]]
        n_calls = len(calls)
    ok = (codes == (200, 422, 422, 422, 422, 422, 422, 422, 200)
          and [v["cod_aff_form"] for v in dup["voeux"]] == [L[0], L[1]]
          and unk["voeux"][0]["status"] == "absente" and n_calls == 0 and zb != zt)
    return ok, f"status {codes}; dedup {[v['cod_aff_form'] for v in dup['voeux']]}; unknown {unk['voeux'][0]['status']}; analytics calls {n_calls}; profile changes zones {zb != zt}"


def block(js: str) -> str:
    i = js.index("// ---- Sprint 11: \"Mes vœux\"")
    # the block ends at the NEXT top-level section, not at the router: a later view sharing a line (the navigation
    # guard) must not stand in for this one (sprint 12: the "Métiers" block hid the "Mes vœux" race mutant)
    return js[i: js.index("\n// ---- ", i + 1)]


def ui(js: str) -> tuple[bool, str]:
    b = re.sub(r"(?m)^\s*//.*$", "", block(js))
    store_ = js[js.index("const voeux = {"): js.index("// ---- SVG primitives")]
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", b)
           if re.search(r"\bv\.(?:etablissement|filiere|complement|ville|academie|cod_aff_form)\b", m) and not m.lstrip().startswith("esc(")]
    trusted = all(x in store_ for x in ("/^\\d{1,9}$/", ".slice(0, this.MAX)", "new Set("))
    race = "if ($view.dataset.rendered !== marker) return;" in b
    zone_guard = "v.zone && ZONES[v.zone]" in b
    rate_label = bool(re.search(r'const rate = serie === "bg" \? "Taux d\'accès" : "Accès estimé pour votre série";', b))
    words = all(w in b for w in ("pas des chances d'admission", "les vœux ne sont pas classés", "ne se combinent pas en une probabilité",
                                 "rien n'est enregistré ni compté sur le serveur", "Accès estimé pour votre série"))
    msg = re.search(r"const VX_MSG = \{(.*?)\n\};", b, re.S)
    codes_ok = bool(msg) and all(f"{k}:" in msg.group(1) for k in ("aucune_securite", "majorite_ambitieuse", "hors_profil", "non_ouvert",
                                                                  "non_situe", "aucune_cible", "equilibree"))
    no_chance = bool(msg) and not re.search(r"(?i)\bchances? de\b|probabilit|\d+\s*% de chances", msg.group(1))
    wired = all(x in js for x in ('if (a === "voeux") return await viewVoeux()', "${voeuButton(r.cod_aff_form)}", "voeux.render(); route();"))
    ok = not raw and trusted and race and zone_guard and rate_label and words and codes_ok and no_chance and wired
    return ok, (f"unescaped {raw[:3]}; stored list validated {trusted}; race guard {race}; zone guard {zone_guard}; rate label {rate_label}; wording {words}; "
                f"messages {codes_ok}; no chance wording {no_chance}; wired {wired}")


@check("V5 page: escaped strings, stored list never trusted, navigation race guarded, wording, every message, wiring")
def v5(c: Ctx):
    from suptracker import analytics as A
    from suptracker.api import FEATURES, METHODOLOGY
    ok, d = ui(APP_JS.read_text())
    html = (ROOT / "suptracker" / "static" / "index.html").read_text()
    extra = 'href="#/voeux"' in html and "voeux" in A.ROUTES and "voeux" in FEATURES and "pas classés" in METHODOLOGY["voeux"]
    return ok and extra, d + f"; nav, analytics route, feature, method {extra}"


UI_MUTANTS = [
    ("unescaped establishment", '<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a>', '<a href="#/f/${esc(v.cod_aff_form)}">${v.etablissement}</a>'),
    ("stored codes not validated", 'typeof c === "string" && /^\\d{1,9}$/.test(c)', 'typeof c === "string"'),
    ("no cap on the stored list", ".slice(0, this.MAX)", ""),
    ("navigation race unguarded", "if ($view.dataset.rendered !== marker) return;", ""),
    ("no-chance caveat dropped", "Ils ne disent pas vos chances d'être admis quelque part : les zones décrivent les admis des campagnes passées, et vos vœux ne se combinent pas en une probabilité.", ""),
    ("ranking caveat dropped", "Sur Parcoursup, les vœux ne sont pas classés : l'ordre de votre liste ne compte pas.", ""),
    ("techno / pro rate labelled as official", '"Accès estimé pour votre série"', '"Taux d\'accès"'),
    ("a message left out", "  aucune_cible: \"Aucun vœu cible pour l'instant.\",\n", ""),
    ("a chance promised", "equilibree: \"Votre liste combine", "equilibree: \"Vous avez 90 % de chances d'être admis : votre liste combine"),
    ("route not wired", 'if (a === "voeux") return await viewVoeux();', ""),
]


@check("V6 mutation test: reading, evaluation and page bugs are each caught")
def v6(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 11: \"Mes vœux\"")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        # a mutant is seeded in the "Mes vœux" block when it is there (other views share some lines)
        mut = js[:i] + js[i:j].replace(old, new, 1) + js[j:] if old in js[i:j] else js.replace(old, new, 1)
        if old not in js or ui(mut)[0]:
            missed.append(name)
    saved = {"read_list": VX.read_list, "position": VX.position, "clean_ids": VX.clean_ids, "MAX_VOEUX": VX.MAX_VOEUX}
    orig_read, orig_pos, orig_clean, orig_stage2 = VX.read_list, VX.position, VX.clean_ids, J.stage2

    def read_uncertain_sure(vs):
        r = orig_read([{**v, "uncertain": False} for v in vs])
        return {**r, "zones": orig_read(vs)["zones"]}

    def read_ge(vs):                 # "half or more" instead of "more than half"
        r = orig_read(vs)
        z = r["zones"]
        amb = z["ambitieux"] + z["hors_profil"]
        codes = [m["code"] for m in r["messages"]]
        if r["situes"] and amb * 2 == r["situes"] and "majorite_ambitieuse" not in codes:
            r["messages"].insert(1 if "aucune_securite" in codes else 0, {"niveau": "warn", "code": "majorite_ambitieuse"})
        return r

    def read_no_closed(vs):
        return orig_read([{**v, "zone": None if v.get("zone") == "non_ouvert" else v.get("zone")} for v in vs])

    def no_dedup(ids):
        out = [x.strip() for x in ids if x.strip()]
        if any(not VX.CODE.match(x) for x in out) or len(out) > 10:
            raise ValueError("x")
        return out

    def stage2_bg(con, dkey, mention, tk, academie=None, sex=None, limit=4000, serie="bg", only=None):
        return orig_stage2(con, dkey or J.doublette_key("MATHS", "SES"), mention, tk, academie, sex, limit, "bg", only)

    def stage2_ab(con, dkey, mention, tk, academie=None, sex=None, limit=4000, serie="bg", only=None):
        return orig_stage2(con, dkey, "ab", tk, academie, sex, limit, serie, only)

    mutants = [
        ("uncertain safety counted as sure", lambda: setattr(VX, "read_list", read_uncertain_sure), ("v3",)),
        ("'more than half' read as 'half or more'", lambda: setattr(VX, "read_list", read_ge), ("v3",)),
        ("vœux closed to the series not flagged", lambda: setattr(VX, "read_list", read_no_closed), ("v3",)),
        ("all-series position instead of the series one", lambda: setattr(VX, "position", lambda f: f.get("cdf")), ("v1",)),
        ("duplicates kept", lambda: setattr(VX, "clean_ids", no_dedup), ("v4",)),
        ("no cap at 10", lambda: setattr(VX, "MAX_VOEUX", 99), ("v4",)),
        ("series ignored (always bac général)", lambda: setattr(J, "stage2", stage2_bg), ("v1",)),
        ("mention frozen", lambda: setattr(J, "stage2", stage2_ab), ("v1", "v4")),
    ]
    fns = {"v1": v1, "v3": v3, "v4": v4}
    for name, apply, which in mutants:
        try:
            apply()
            caught = False
            for w in which:
                try:
                    caught = caught or not fns[w](c)[0]
                except Exception:  # noqa: BLE001
                    caught = True
        finally:
            for k, v in saved.items():
                setattr(VX, k, v)
            J.stage2 = orig_stage2
        if not caught:
            missed.append(name)
    n = len(UI_MUTANTS) + len(mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


# ---------------------------------------------------------------- "Compléter ma liste" (owner, 2026-11-10)
PAID = ("Privé enseignement supérieur", "Privé hors contrat")       # Plan B's list, written apart


def _km(a, b):
    import math
    if None in (*a, *b):
        return None
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    return 2 * 6371.0 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


_STAGE2 = {}


def _rows(con, dkey, mention, tk, academie, serie):
    k = (id(con), dkey, mention, tk, academie, serie)
    if k not in _STAGE2:
        _STAGE2[k] = J.stage2(con, dkey, mention, tk, academie, serie=serie)["formations"]
    return _STAGE2[k]


def ref_completer(con, ev, *, serie, dkey, mention, academie, include_paid, limit=3):
    """The red team's own suggestions: safety read with certainty, same programme, solid reading, not listed, not the same
    concours pool, paid only on request, 2 per establishment, 3 per filière, académie then nearest vœu (independent code)."""
    needed = not any(v.get("zone") == "securite" and v.get("uncertain") is False for v in ev["voeux"])
    if not needed:
        return {"needed": False, "groups": {}, "hidden": 0}
    listed = {v["cod_aff_form"] for v in ev["voeux"]}
    groups, hidden = {}, 0
    keys = []
    for v in ev["voeux"]:
        if v["status"] == "ok" and v.get("type_key") and v.get("filiere") and (v["type_key"], v["filiere"]) not in keys:
            keys.append((v["type_key"], v["filiere"]))
    for tk, fil in keys:
        rows = _rows(con, dkey, mention, tk, academie, serie)
        mine = [r for r in rows if r["cod_aff_form"] in listed and r["filiere"] == fil]
        ok = []
        for f in rows:
            pos = f["spos"]["cdf_used"] if f.get("spos") else f.get("cdf")
            if (f["filiere"] != fil or f["cod_aff_form"] in listed or f["zone"] != "securite" or f["uncertain"] is not False
                    or f.get("rate_fragile") or f.get("small_cohort") or f.get("taux_acces_ens") is None or pos is None):
                continue
            if any(t.get("subwish_flag") and f.get("subwish_flag") and f.get("complement") and f.get("complement") == t.get("complement")
                   for t in mine):
                continue
            if f.get("contrat_etab") in PAID and not include_paid:
                hidden += 1
                continue
            d = [x for x in (_km((t.get("lat"), t.get("lon")), (f.get("lat"), f.get("lon"))) for t in mine) if x is not None]
            ok.append((0 if academie and f["academie"] == academie else 1, min(d) if d else float("inf"), PB._tiebreak(f["cod_aff_form"]), f))
        ok.sort(key=lambda x: x[:3])
        out, seen = [], {}
        for *_, f in ok:
            k = (f["etablissement"], f["ville"])
            if seen.get(k, 0) == 2:
                continue
            seen[k] = seen.get(k, 0) + 1
            out.append(f["cod_aff_form"])
            if len(out) == limit:
                break
        groups[(tk, fil)] = out
    return {"needed": True, "groups": groups, "hidden": hidden}


def completer_cases(c: Ctx, quick: bool = False):
    """Lists with no sure safety: the ambitious or target formations of a few types for each profile, without and with an
    académie (quick: the first profile only, for the mutation test)."""
    cases = []
    from collections import Counter
    big = [tk for tk, _ in Counter(c.type_of.values()).most_common(4 if quick else 6)]   # the largest types: most alternatives
    for serie, dkey, mention in c.profiles[:1 if quick else 3]:
        picked, safe_acads = [], Counter()
        for tk in big:
            rows = c.full(serie, dkey, mention, tk)
            picked += [cod for cod, f in sorted(rows.items()) if f["zone"] in ("ambitieux", "cible")][:2]
            safe_acads.update(f["academie"] for f in rows.values() if f["zone"] == "securite" and f["uncertain"] is False and f.get("academie"))
        acad = safe_acads.most_common(1)[0][0] if safe_acads else None
        cases.append((serie, dkey, mention, None, picked[:8]))
        cases.append((serie, dkey, mention, acad, picked[:8]))
        # the cap of 2 per establishment shows only where one establishment has 3+ safeties of one programme: a list of
        # one non-safe vœu of such a programme, when the warehouse has one (real data: engineering schools' bac+3)
        for tk in big:
            rows = c.full(serie, dkey, mention, tk)
            n = Counter((f["filiere"], f["etablissement"], f["ville"]) for f in rows.values()
                        if f["zone"] == "securite" and f["uncertain"] is False and not f.get("rate_fragile") and not f.get("small_cohort"))
            fil = next((k[0] for k, v in n.most_common() if v >= 3), None)
            vo = next((cod for cod, f in sorted(rows.items()) if fil and f["filiere"] == fil and f["zone"] in ("ambitieux", "cible")), None)
            if vo:
                cases.append((serie, dkey, mention, None, [vo]))
                break
    return cases


def check_completer(c: Ctx, fn=None, quick: bool = False):
    fn = fn or VX.completer
    bad, n_groups, n_sugg = [], 0, 0
    for serie, dkey, mention, acad, ids in completer_cases(c, quick):
        if not ids:
            continue
        ev = VX.evaluate(c.con, ids, serie=serie, dkey=dkey, mention=mention, academie=acad)
        # (paid, per filière): the default 3 without and with paid institutions, and 10 with them (the cap per establishment shows)
        for paid, lim in ((False, 3), (True, 3), (True, 10)):
            got = fn(c.con, ids, serie=serie, dkey=dkey, mention=mention, academie=acad, include_paid=paid, per_filiere=lim)
            want = ref_completer(c.con, ev, serie=serie, dkey=dkey, mention=mention, academie=acad, include_paid=paid, limit=lim)
            if got["needed"] != want["needed"]:
                bad.append(("needed", serie, mention, acad))
                continue
            g = {(x["type_key"], x["filiere"]): [f["cod_aff_form"] for f in x["formations"]] for x in got["filieres"]}
            if g != want["groups"]:
                bad.append(("suggestions", serie, mention, acad, paid))
            if got["hidden_paid"] != want["hidden"]:
                bad.append(("hidden paid", serie, mention, acad, paid))
            for x in got["filieres"]:
                for f in x["formations"]:
                    if f["paid"] and not paid:
                        bad.append(("paid shown", f["cod_aff_form"]))
            n_groups += len(g)
            n_sugg += sum(len(v) for v in g.values())
        # a list WITH a sure safety asks for nothing
        sure = [cod for cod, f in c.full(serie, dkey, mention, c.type_of[ids[0]]).items() if f["zone"] == "securite" and f["uncertain"] is False][:1]
        if sure:
            r = fn(c.con, ids[:3] + sure, serie=serie, dkey=dkey, mention=mention, academie=acad)
            if r["needed"] or r["filieres"]:
                bad.append(("asked with a sure safety", serie, mention))
    return not bad and n_sugg > 0, f"groups {n_groups}, suggestions {n_sugg}; problems {bad[:4]}"


@check("V7 'Compléter ma liste': only without a sure safety; safety read with certainty, same programme, solid reading, not listed, "
       "no shared concours pool, paid only on request, 2 per establishment, 3 per filière, académie then distance (re-derived)")
def v7(c: Ctx):
    return check_completer(c)


def ui_completer(js: str) -> tuple[bool, str]:
    i = js.index("async function loadCompleter(")
    f = js[i: js.index("\n// ---- ", i)]
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", f)
           if re.search(r"\b[fg]\.(?:etablissement|filiere|fili|complement|ville|academie|cod_aff_form)\b", m) and not m.lstrip().startswith("esc(")]
    cells = re.findall(r'<td class="num"[^>]*>', f)
    labelled = bool(cells) and all("data-label=" in x for x in cells)
    race = "if ($view.dataset.rendered !== marker || !box()) return;" in f
    words = all(w in f for w in ("pas des chances d'admission", "vérifiez chaque fiche Parcoursup", "zone sécurité sans incertitude",
                                 "privé payant"))
    no_chance = not re.search(r"(?i)\d+\s*% de chances|probabilit|vous serez admis", f)
    wired = bool(re.search(r'if \(L\.messages\.some\(\(m\) => m\.code === "aucune_securite"\)\) \{[^}]*loadCompleter\(qs, marker, rate, false\);', js))
    ok = not raw and labelled and race and words and no_chance and wired
    return ok, f"unescaped {raw[:3]}; labelled cells {labelled}; race guard {race}; wording {words}; no chance {no_chance}; shown on 'aucune_securite' {wired}"


@check("V8 'Compléter ma liste' API and page: inputs refused like /api/voeux, no analytics event, never shared-cached; escaped, labelled, "
       "race-guarded, worded as past cohorts, loaded only on 'aucune sécurité'")
def v8(c: Ctx):
    from suptracker.api import FEATURES
    L = c.lists[0]
    with client(c.db) as (cl, calls):
        g = lambda **p: cl.get("/api/voeux/completer", params=p)  # noqa: E731
        r = g(ids=",".join(L), serie="bt")
        codes = (r.status_code, g(ids="1 OR 1=1", serie="bt").status_code, g(ids=L[0], serie="bg").status_code,
                 g(ids=L[0], serie="bt", paid=2).status_code, g(ids=",".join(str(10000 + i) for i in range(11)), serie="bt").status_code)
        cache = r.headers.get("cache-control", "")
        n_calls = len(calls)
    ok_ui, d = ui_completer(APP_JS.read_text())
    ok = codes == (200, 422, 422, 422, 422) and cache == "no-store" and n_calls == 0 and ok_ui and "voeux_completer" in FEATURES
    return ok, f"status {codes}; cache {cache!r}; analytics calls {n_calls}; " + d


COMPLETER_MUTANTS = [
    ("uncertain safety proposed", 'if f["zone"] != "securite" or f["uncertain"]:', 'if f["zone"] != "securite":'),
    ("target zone proposed", 'if f["zone"] != "securite" or f["uncertain"]:', 'if f["zone"] not in ("securite", "cible") or f["uncertain"]:'),
    ("fragile reading proposed", 'or not PB.usable(f):', ':'),
    ("another programme proposed", 'if f["filiere"] != fil or f["cod_aff_form"]', 'if f["cod_aff_form"]'),
    ("paid institutions not hidden", "if PB.paid(f) and not include_paid:", "if False:"),
    ("same concours pool proposed", "if any(PB.same_pool(t, f) for t in targets):", "if False:"),
    ("no cap per establishment", "if per_etab.get(key, 0) >= PB.MAX_PER_ETABLISSEMENT:", "if False:"),
    ("académie ignored", '(0 if academie and x[0]["academie"] == academie else 1,', "(0,"),
    ("farthest vœu instead of nearest", "min(kms) if kms", "max(kms) if kms"),
    ("suggests even with a sure safety", "    if not needed:\n        return base", "    if False:\n        return base"),
]
COMPLETER_UI_MUTANTS = [
    ("unescaped establishment", '<a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${f.complement',
     '<a href="#/f/${esc(f.cod_aff_form)}">${f.etablissement}</a><div class="muted small">${f.complement'),
    ("unescaped filière title", "${esc(g.filiere)}", "${g.filiere}"),
    ("race unguarded", "if ($view.dataset.rendered !== marker || !box()) return;", ""),
    ("caveat dropped", "pas des chances d'admission ; vérifiez", "vérifiez"),
    ("paid flag dropped", "${f.paid ? ' · <span class=\"badge warnb\">privé payant</span>' : \"\"}", ""),
    ("distance cell unlabelled", '<td class="num" data-label="Distance au plus proche de vos vœux">', '<td class="num">'),
    ("never loaded", "loadCompleter(qs, marker, rate, false);", ""),
]


def mutated_completer(old: str, new: str):
    import types
    src = Path(VX.__file__).read_text()
    if old not in src:
        return None
    mod = types.ModuleType("suptracker._voeux_mutant")
    mod.__package__ = "suptracker"
    exec(compile(src.replace(old, new, 1), VX.__file__, "exec"), mod.__dict__)
    return mod.completer


@check("V9 mutation test of 'Compléter ma liste': rules and page bugs are each caught")
def v9(c: Ctx):
    missed = []
    for name, old, new in COMPLETER_MUTANTS:
        fn = mutated_completer(old, new)
        if fn is None or check_completer(c, fn, quick=True)[0]:
            missed.append(name)
    js = APP_JS.read_text()
    for name, old, new in COMPLETER_UI_MUTANTS:
        if old not in js or ui_completer(js.replace(old, new, 1))[0]:
            missed.append(name)
    n = len(COMPLETER_MUTANTS) + len(COMPLETER_UI_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


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
