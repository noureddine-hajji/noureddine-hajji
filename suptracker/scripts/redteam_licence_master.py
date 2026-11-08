"""Red team of sprint 16: from the licence to the master, side by side.

    python scripts/redteam_licence_master.py [--db data/suptracker.duckdb] [--real]

  L1 mention -> Onisep master sheet re-derived (own normalisation, own spelling rules): stored links equal; every link is a
     "master mention" sheet whose title is the mention; no MonMaster mention whose title has a sheet is left unlinked
  L2 per-job axes re-derived from the job page (metiers.detail): ILO and θ ranges, the 2030 class by the fixed rule
  L3 serving on licence pages: the mentions are exactly MonMaster's (latest session, same university by Paysage id, same
     B1 discipline), counts equal; insertion = the same university's master of the same title in the latest national
     class (unique), else none; jobs = the Onisep sheet's; ranges = min / max over the jobs, counts add up, no average;
     landmarks re-derived (disjoint ranges only)
  L4 coverage on real data (mentions with a sheet, with an insertion figure, licences with the card)
  L5 page (card run with Node on hostile data): escaped, units (admits are people, vœux are not), ranges, "non documentés",
     no chance / probability wording
  L6 upkeep: methodology, feature, release wiring, warehouse under 95 MB
  L7 mutation test (each mutant must fail a check; a crash counts as missed)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import licence_master as LM  # noqa: E402
from suptracker import metiers as MT  # noqa: E402
from suptracker import success as SU  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
HORIZON = 18


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def fold(s):
    """Independent normalisation: accents off, lower case, every non-alphanumeric run is one space."""
    s = "".join({"œ": "oe", "æ": "ae"}.get(ch, ch) for ch in (s or "").lower())
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", s))


def spelled(k):
    """The two owner-visible spelling rules, written independently."""
    w = k.split()
    if w[:1] == ["staps"]:
        w = "sciences et techniques des activites physiques et sportives".split() + w[1:]
    return " ".join(x for x in w if x != "meef")


class Ctx:
    def __init__(self, db: Path, real: bool, paysage: dict | None = None):
        self.db, self.real = db, real
        self.paysage = SU.SIES_PAYSAGE if paysage is None else paysage
        self.con = duckdb.connect(str(db), read_only=True)
        self.reload()

    def reload(self):
        self.links = {m: (f, r) for m, f, r in self.con.execute("SELECT mention, for_id, regle FROM core.master_onisep").fetchall()}
        self.axes = {r[0]: r for r in self.con.execute("SELECT * FROM core.metier_axes").fetchall()}


def close(a, b, tol=1e-9):
    return (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) <= tol)


@check("L1 mention -> Onisep master sheet: re-derived links equal, titles equal, no linkable mention left out")
def l1(c: Ctx):
    sheets = {}
    for fid, lib, typ in c.con.execute("SELECT for_id, libelle, type FROM core.onisep_formation").fetchall():
        if typ == "master" and (lib or "").startswith("master mention "):
            sheets.setdefault(fold(lib[len("master mention "):]), fid)
    want = {}
    for (m,) in c.con.execute("SELECT DISTINCT mention FROM core.monmaster WHERE mention IS NOT NULL").fetchall():
        k = fold(m)
        if k in sheets:
            want[m] = (sheets[k], "titre")
        elif spelled(k) in sheets:
            want[m] = (sheets[spelled(k)], "orthographe")
    diff = sorted(set(want.items()) ^ set(c.links.items()))[:3]
    types = dict(c.con.execute("SELECT for_id, type FROM core.onisep_formation").fetchall())
    not_master = [m for m, (f, _) in c.links.items() if types.get(f) != "master"]
    ok = not diff and not not_master and (len(want) >= 150 or not c.real)
    return ok, f"{len(want)} mentions linkable, stored {len(c.links)}, differ {diff}, linked to a non-master sheet {not_master[:3]}"


@check("L2 per-job axes re-derived from the job page: ILO and θ ranges, the 2030 class by the fixed rule")
def l2(c: Ctx):
    ids = sorted(c.axes)
    sample = ids if c.real else ids
    bad = []
    for mid in sample:
        d = MT.detail(c.con, mid)
        ia = d.get("ia") or {}
        lect = [f.get("lecture") for f in (d.get("emploi2030") or []) if not f.get("absent")]
        read = [x for x in lect if x]
        cls = "non_lu" if not read else "insuffisants" if set(read) == {"debutants_insuffisants"} \
            else "nombreux" if set(read) == {"debutants_nombreux"} else "incertain"
        r = c.axes[mid]
        if not (close(r[2], ia.get("min")) and close(r[3], ia.get("max")) and close(r[4], ia.get("theta_min"))
                and close(r[5], ia.get("theta_max")) and r[6] == cls and r[7] == len(read)):
            bad.append(mid)
    n_jobs = c.con.execute("SELECT count(*) FROM core.onisep_metier").fetchone()[0]
    ok = not bad and len(ids) == n_jobs
    return ok, f"{len(sample)} jobs re-derived, {len(bad)} differ {bad[:3]}; axes rows {len(ids)} for {n_jobs} jobs"


def licences(c: Ctx, limit: int | None):
    rows = c.con.execute("""SELECT DISTINCT l.cod_aff_form, f.fili, f.contrat_etab FROM core.licence_success_link l
        JOIN core.formation_year f ON f.cod_aff_form = l.cod_aff_form
        WHERE f.session = (SELECT max(session) FROM core.formation_year) ORDER BY 1""").fetchall()
    return rows if limit is None else rows[:: max(1, len(rows) // limit)]


def ref_insertion(c: Ctx, pid, disc):
    nat = c.con.execute("""SELECT last_year FROM core.insersup WHERE id_paysage = 'all' AND type_diplome = 'Master LMD'
                           AND diplome = 'all' AND nb_sortants_18 IS NOT NULL ORDER BY last_year DESC LIMIT 1""").fetchone()
    year = nat[0] if nat else None
    rows = c.con.execute(f"""SELECT diplome, libelle, sectdis_lib, last_year, nb_sortants_{HORIZON}, tx_sortants_en_emploi_sal_fr_{HORIZON},
            tx_sortants_en_emploi_stable_{HORIZON}, pooled, masked FROM core.insersup
            WHERE id_paysage = ? AND type_diplome = 'Master LMD' AND diplome <> 'all' AND discipline = ?""", [pid, disc]).fetchall()
    groups = {}
    for r in rows:
        if r[4] is None and json.loads(r[8] or "{}").get(f"nb_sortants_{HORIZON}") is None:
            continue
        groups.setdefault((r[0], r[1], r[2]), []).append(r)
    by = {}
    for g in groups.values():
        y = max(x[3] or 0 for x in g)
        top = [x for x in g if (x[3] or 0) == y]
        if len(top) == 1 and y == year:
            by.setdefault(fold(top[0][1]), []).append(top[0])
    return {k: v[0] for k, v in by.items() if len(v) == 1}


@check("L3 serving: MonMaster mentions of the university and discipline, insertion of the same title, jobs, ranges, counts, landmarks")
def l3(c: Ctx):
    s = c.con.execute("SELECT max(session) FROM core.monmaster").fetchone()[0]
    bad, n_ok, n_m = [], 0, 0
    for cod, fili, contrat in licences(c, 120 if c.real else None):
        out = LM.for_licence(c.con, cod, fili, contrat, paysage=c.paysage)
        if fili not in SU.LICENCE_FILI:
            if out is not None:
                bad.append(f"{cod}: card on a non-licence")
            continue
        if out is None or out["status"] != "ok":
            continue
        n_ok += 1
        pid = c.paysage.get(out["etab"])
        want = c.con.execute("""SELECT mention, count(*), sum(n_can), sum(n_accept) FROM core.monmaster
            WHERE session = ? AND id_paysage = ? AND discipline = ? GROUP BY mention""", [s, pid, out["discipline"]]).fetchall()
        got = {m["mention"]: m for m in out["mentions"]}
        if {w[0] for w in want} != set(got) or any((got[w[0]]["n_offres"], got[w[0]]["n_can"], got[w[0]]["n_accept"]) != w[1:] for w in want):
            bad.append(f"{cod}: mentions or counts")
            continue
        ins = ref_insertion(c, pid, out["discipline"])
        lic = out.get("licence")
        for m in out["mentions"]:
            n_m += 1
            r = ins.get(fold(m["mention"]))
            i = m["insertion"]
            if (r is None) != (i is None) or (r and not (close(i["taux_emploi"], r[5]) and i["sortants"] == r[4])):
                bad.append(f"{cod} {m['mention']}: insertion")
            link = c.links.get(m["mention"])
            j = m["metiers"]
            if (link is None) != (j is None):
                bad.append(f"{cod} {m['mention']}: sheet")
                continue
            if j is None:
                if m["reperes"]:
                    bad.append(f"{cod} {m['mention']}: landmark without jobs")
                continue
            ids = sorted(x for (x,) in c.con.execute("SELECT met_id FROM core.onisep_formation_metier WHERE for_id = ?", [link[0]]).fetchall())
            if sorted(x["id"] for x in j["metiers"]) != ids:
                bad.append(f"{cod} {m['mention']}: jobs")
            ax = [c.axes[x] for x in ids if x in c.axes]
            lo = [a[2] for a in ax if a[2] is not None]
            hi = [a[3] for a in ax if a[3] is not None]
            tlo = [a[4] for a in ax if a[4] is not None]
            thi = [a[5] for a in ax if a[5] is not None]
            want_r = (min(lo) if lo else None, max(hi) if hi else None, min(tlo) if tlo else None, max(thi) if thi else None)
            if not all(close(a, b) for a, b in zip((j["ilo_min"], j["ilo_max"], j["theta_min"], j["theta_max"]), want_r)):
                bad.append(f"{cod} {m['mention']}: ranges")
            if sum(j["classes_2030"].values()) != j["n_metiers"] or any(k in j for k in ("moyenne", "mean", "average", "score")):
                bad.append(f"{cod} {m['mention']}: counts or average")
            rep = []
            if lic and None not in (lic["ilo_min"], lic["ilo_max"], j["ilo_min"], j["ilo_max"]):
                rep += ["ia_plus_bas"] if j["ilo_max"] < lic["ilo_min"] else ["ia_plus_haut"] if j["ilo_min"] > lic["ilo_max"] else []
            if lic and None not in (lic["theta_min"], lic["theta_max"], j["theta_min"], j["theta_max"]):
                rep += ["complementarite_plus_haute"] if j["theta_min"] > lic["theta_max"] else \
                    ["complementarite_plus_basse"] if j["theta_max"] < lic["theta_min"] else []
            if rep != m["reperes"]:
                bad.append(f"{cod} {m['mention']}: landmarks {m['reperes']} != {rep}")
    ok = not bad and n_ok > 0 and n_m > 0
    return ok, f"{n_ok} licence cards, {n_m} mentions checked, {len(bad)} wrong {bad[:3]}"


@check("L4 coverage: mentions with an Onisep sheet, with an insertion figure; licences with the card")
def l4(c: Ctx):
    tot = sheet = ins = cards = lics = rep = 0
    for cod, fili, contrat in licences(c, 300 if c.real else None):
        if fili not in SU.LICENCE_FILI:
            continue
        lics += 1
        out = LM.for_licence(c.con, cod, fili, contrat, paysage=c.paysage)
        if not out or out["status"] != "ok":
            continue
        cards += 1
        for m in out["mentions"]:
            tot += 1
            sheet += m["metiers"] is not None
            ins += m["insertion"] is not None
            rep += bool(m["reperes"])
    share = sheet / tot if tot else 0
    ok = tot > 0 and (not c.real or share >= 0.5)
    return ok, (f"{cards}/{lics} licences with the card; {tot} mention rows: {sheet} with jobs ({share:.0%}), {ins} with an "
                f"insertion figure, {rep} with a landmark")


def block(js: str) -> str:
    i = js.index("// ---- Sprint 16: de la licence au master")
    return js[i: js.index("\n// ---- ", i + 1)]


HOSTILE = {"status": "ok", "etab_label": "<b>Univ</b>", "discipline_label": "Sciences", "session": 2025, "annee_insertion": 2023,
           "licence": {"n_metiers": 3, "ilo_min": 0.5, "ilo_max": 0.6, "theta_min": 0.4, "theta_max": 0.45},
           "mentions": [
               {"mention": "<script>alert(1)</script>", "n_offres": 2, "n_can": 1234, "n_accept": 56,
                "insertion": {"sortants": 40, "taux_emploi": 71.25, "taux_stable": 60, "promo": "2022", "regroupe": True},
                "onisep": {"for_id": "FOR.1", "regle": "orthographe"},
                "metiers": {"n_metiers": 2, "ilo_min": 0.21, "ilo_max": 0.38, "theta_min": 0.61, "theta_max": 0.7,
                            "classes_2030": {"insuffisants": 1, "nombreux": 0, "incertain": 1, "non_lu": 0},
                            "metiers": [{"id": "MET.1\"><img src=x onerror=alert(2)>", "nom": "<img src=y onerror=alert(3)>"},
                                        {"id": "MET.2", "nom": "Chimiste"}]},
                "reperes": ["ia_plus_bas", "complementarite_plus_haute"]},
               {"mention": "DROIT PENAL", "n_offres": 1, "n_can": 10, "n_accept": 5, "insertion": None, "onisep": None,
                "metiers": None, "reperes": []},
               {"mention": "PHYSIQUE", "n_offres": 1, "n_can": 3, "n_accept": 2, "onisep": None, "metiers": None, "reperes": [],
                "insertion": {"sortants": 6, "taux_emploi": None, "taux_stable": None, "promo": "2022", "regroupe": True}}]}


def render(js: str):
    node = shutil.which("node")
    if not node:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ")))
    prog = (helpers + "\nconst META = {methodology: {}}; const tip = () => '';\n" + block(js)
            + "\nconst P = JSON.parse(require('fs').readFileSync(0, 'utf8'));\nprocess.stdout.write(JSON.stringify(P.map(licenceMasterCard)));")
    r = subprocess.run([node, "-e", prog], input=json.dumps([HOSTILE, None, {"status": "non_rattachee", "reason": "<i>x</i>"}]),
                       capture_output=True, text=True, timeout=60)
    return ("__error__" + r.stderr[-300:]) if r.returncode else r.stdout


def ui(js: str) -> tuple[bool, str]:
    out = render(js)
    wired = "${licenceMasterCard(d.licence_master)}" in js
    if out is None:
        return wired, "node not installed"
    if out.startswith("__error__"):
        return False, out
    html, none, status = json.loads(out)
    leaks = re.findall(r"<(?:script|img|b|i)\b", html + status)
    flat = html.replace(" ", " ").replace("\xa0", " ")
    words = all(w in flat for w in ("Admis : des personnes", "pas des personnes", "métiers non documentés", "non publié",
                                    "0,21 à 0,38", "0,61 à 0,70", "71,3 %", "1 234 vœux", "jamais une moyenne", "transformé que remplacé",
                                    "estimation adaptée", "pas des chances d'admission ou d'emploi", "ne se chevauchent pas",
                                    "tous moins exposés", "complémentarité humaine plus haute", "1 où les débutants ne suffiraient pas",
                                    "1 incertains", "promotions regroupées", "orthographe différente", "Débouchés directs de cette licence",
                                    "MonMaster 2025", "promotion 2023", "taux non publié", 'data-label="Admis"'))
    banned = [w for w in ("probabilit", "tes chances", "vos chances", "garanti", "moyenne des métiers", "score global") if w in flat.lower()]
    ok = wired and not leaks and words and not banned and none == ""
    return ok, f"raw tags {leaks[:3]}; wording and figures {words}; banned {banned}; wired {wired}"


@check("L5 page (card run with Node on hostile data): escaped, units, ranges, non documentés, no chance wording")
def l5(c: Ctx):
    return ui(APP_JS.read_text())


@check("L6 upkeep: methodology, feature, release wiring, warehouse under 95 MB")
def l6(c: Ctx):
    from suptracker.api import FEATURES, METHODOLOGY
    m = METHODOLOGY.get("licence_master", "")
    rel = (ROOT / "tests" / "test_release.py").read_text()
    size = c.db.stat().st_size / 1e6
    ok = "licence_master" in FEATURES and "jamais une moyenne" in m and "pas des personnes" in m and "ne se chevauchent pas" in m \
        and "function licenceMasterCard(" in rel and (size < 95 or not c.real)
    return ok, f"feature {'licence_master' in FEATURES}; methodology {bool(m)}; release guard {'function licenceMasterCard(' in rel}; warehouse {size:.1f} MB"


UI_MUTANTS = [
    ("mention unescaped", "<strong>${esc(m.mention)}</strong>", "<strong>${m.mention}</strong>"),
    ("job name unescaped", ">${esc(e.nom)}</a>", ">${e.nom}</a>"),
    ("vœux presented as people", "vœux : des candidatures additionnées sur les parcours, pas des personnes", "vœux : des candidats"),
    ("range collapsed to its middle", "two(lo) === two(hi) ? two(lo) : `${two(lo)} à ${two(hi)}`", "two((lo + hi) / 2)"),
    ("undocumented master hidden", "'<span class=\"muted\">métiers non documentés</span>'", "\"\""),
    ("no chance caveat", "pas des chances d'admission ou d'emploi", "vos chances d'admission"),
    ("year printed with a thousands separator", "(MonMaster ${esc(x.session)})", "(MonMaster ${fmt(x.session)})"),
    ("masked rate shown as a dash", "'<span class=\"muted\">taux non publié</span>'", "\"—\""),
]


@check("L7 mutation test: link, axes, serving and page bugs are each caught by a failing check")
def l7(c: Ctx):
    missed, crashed = [], []
    js = APP_JS.read_text()
    i = js.index("// ---- Sprint 16: de la licence au master")
    j = js.index("\n// ---- ", i + 1)
    for name, old, new in UI_MUTANTS:
        if old not in js[i:j] or ui(js[:i] + js[i:j].replace(old, new, 1) + js[j:])[0]:
            missed.append(name)

    saved = {k: getattr(LM, k) for k in ("REWRITES", "job_class", "reperes", "jobs_of", "_insersup", "key", "build_link", "build_axes")}

    def run(apply, fns, rebuild=None):
        tmp = Path(tempfile.gettempdir()) / f"lm_mutant_{c.db.stem}.duckdb"
        try:
            apply()
            m = Ctx.__new__(Ctx)
            m.db, m.real, m.paysage = c.db, c.real, c.paysage
            if rebuild:
                shutil.copy(c.db, tmp)
                w = duckdb.connect(str(tmp))
                rebuild(w)
                w.close()
                m.db, m.con = tmp, duckdb.connect(str(tmp), read_only=True)
            else:
                m.con = c.con
            m.reload()
            caught = any(not fn(m)[0] for fn in fns)
            if rebuild:
                m.con.close()
            return caught
        except Exception as e:  # noqa: BLE001  a crash is not a catch
            crashed.append(f"{type(e).__name__}: {e}"[:120])
            return False
        finally:
            for k, v in saved.items():
                setattr(LM, k, v)
            tmp.unlink(missing_ok=True)

    orig_jobs, orig_ins, orig_key, orig_link = LM.jobs_of, LM._insersup, LM.key, LM.build_link

    def averaged(con, f):
        out = orig_jobs(con, f)
        if out and out["ilo_min"] is not None:
            a = [x["ilo_min"] for x in out["metiers"] if x["ilo_min"] is not None]
            out["ilo_min"] = out["ilo_max"] = sum(a) / len(a)
        return out

    def prefix_link(con):                                          # fuzzy: a sheet whose title starts like the mention
        orig_link(con)
        sheets = con.execute("""SELECT for_id, libelle FROM core.onisep_formation WHERE type = 'master'""").fetchall()
        have = {m for (m,) in con.execute("SELECT mention FROM core.master_onisep").fetchall()}
        for (mention,) in con.execute("SELECT DISTINCT mention FROM core.monmaster").fetchall():
            if mention in have:
                continue
            k = orig_key(mention).split()[:1]
            hit = [f for f, lib in sheets if k and orig_key(lib).split()[2:3] == k]
            if hit:
                con.execute("INSERT INTO core.master_onisep VALUES (?, ?, 'titre')", [mention, hit[0]])

    def any_university_insertion(con, pid, disc):                  # insertion matched on title alone, any university
        # deterministic: the other university with the most master rows (an unordered LIMIT 1 changed with each warehouse build)
        any_pid = con.execute("""SELECT id_paysage FROM core.insersup WHERE id_paysage <> ? AND id_paysage <> 'all'
                                 AND type_diplome = 'Master LMD' GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1""", [pid]).fetchone()
        a, y = orig_ins(con, pid, disc)
        b, _ = orig_ins(con, any_pid[0], disc) if any_pid else ({}, y)
        return {**b, **a} if not a else {**a, **{k: v for k, v in b.items() if k not in a}}, y

    def overlap_landmark(lic, mas):                                # compares the minima only: fires on overlapping ranges
        if not lic or not mas or None in (lic["ilo_min"], mas["ilo_min"]):
            return []
        return ["ia_plus_bas"] if mas["ilo_min"] < lic["ilo_min"] else []

    def any_class(lect):                                           # one "insuffisants" family is enough
        return "insuffisants" if "debutants_insuffisants" in lect else saved["job_class"](lect)

    def theta_low_only(con):
        saved["build_axes"](con)
        con.execute("UPDATE core.metier_axes SET theta_max = theta_min")

    def ascii_key(s):                                              # the bug L1 caught: curly apostrophe dropped, words glued
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+", " ", s).strip()

    data_mutants = [
        ("curly apostrophe dropped (l’espace -> lespace)", lambda: setattr(LM, "key", ascii_key), (l1,), lambda w: LM.build_link(w)),
        ("spelling rules dropped", lambda: setattr(LM, "REWRITES", ()), (l1,), lambda w: LM.build_link(w)),
        ("fuzzy prefix links", lambda: None, (l1,), prefix_link),
        ("2030 class: one family enough", lambda: setattr(LM, "job_class", any_class), (l2,), lambda w: LM.build_axes(w)),
        ("θ range reduced to its low end", lambda: None, (l2,), theta_low_only),
        ("ILO range replaced by an average", lambda: setattr(LM, "jobs_of", averaged), (l3,), None),
        ("insertion from another university", lambda: setattr(LM, "_insersup", any_university_insertion), (l3,), None),
        ("landmark on overlapping ranges", lambda: setattr(LM, "reperes", overlap_landmark), (l3,), None),
    ]
    for name, apply, fns, rebuild in data_mutants:
        if not run(apply, fns, rebuild):
            missed.append(name)
    n = len(UI_MUTANTS) + len(data_mutants)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed} {crashed}" if missed else "")


def run(db: Path, real: bool = False, paysage: dict | None = None) -> list[dict]:
    c = Ctx(db, real, paysage)
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
