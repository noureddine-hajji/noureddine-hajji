"""Red team of "Préparer son projet motivé" (owner, 2026-11-10): the points to check, in the jury's own words.

    python scripts/redteam_projet.py [--db data/suptracker.duckdb] [--real]

Checks:
  J1 crafted texts: the points are the criteria that name the projet motivé (independent reading), verbatim, by importance then
     the jury's order; the other criteria counted; eliminating lines that name it, verbatim; advice verbatim; no criteria = none
  J2 real reports: the same re-derivation on a sample of formations whose own report is readable, through for_formation
  J3 similar formations: counts re-derived from the texts of the group's verified reports (independent field mapping)
  J4 API: /api/projet/{cod} = the formation page's block; bad code 422, unknown 404; shared-cacheable; no analytics event
  J5 pages (Node, hostile texts): escaped, the jury's words quoted, caveats (fait foi, not a chance, nothing written for you),
     "pas le rapport de cette formation" for similar formations, pending mark, wording; wiring (jury tab, Mes vœux on opening)
  J6 mutation test: Python mutants built in memory and page mutants must each be caught
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
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import projet as PJ  # noqa: E402
from suptracker import semblables as SB  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
HOSTILE = '<img src=x onerror=alert(1)>'
CHECKS = []
M = {"PJ": PJ}
IMP = ["Essentiel", "Très important", "Important", "Complémentaire"]


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


# ---------------------------------------------------------------- the red team's own reading
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def names_projet(c: dict) -> bool:
    """Written apart from projet.PROJET: the criterion's words or elements name the projet motivé or the lettre de motivation."""
    t = _fold(f"{c.get('critere') or ''} {c.get('elements') or ''}")
    return ("projet motiv" in t or "projet de formation" in t or "lettre de motiv" in t
            or re.search(r"(^|[^a-z])pfm([^a-z]|$)", t) is not None)


def ref_checklist(textes):
    if not textes:
        return None
    crit = [c for c in textes.get("criteres") or [] if c.get("critere") or c.get("elements")]
    if not crit:
        return None
    named = [(i, c) for i, c in enumerate(crit) if names_projet(c)]
    rank = lambda c: IMP.index(c.get("importance")) if c.get("importance") in IMP else 4  # noqa: E731
    named.sort(key=lambda x: (rank(x[1]), x[0]))
    elim = [ln.strip()[:400] for ln in (textes.get("eliminatoires") or "").split("\n")
            if names_projet({"critere": ln})][:6]
    return {"points": [{k: c.get(k) or "" for k in ("champ", "critere", "elements", "importance")} for _, c in named],
            "n_criteres": len(crit), "autres_criteres": len(crit) - len(named), "eliminatoires": elim,
            "conseils": (textes.get("conseils") or "").strip()}


def crafted_texts():
    return [
        ({"criteres": [
            {"champ": "Résultats académiques", "critere": "Notes de maths", "elements": "Bulletins", "importance": "Essentiel"},
            {"champ": "Engagements, activités", "critere": "Engagement", "elements": "Projet de formation motivé, fiche Avenir", "importance": "Complémentaire"},
            {"champ": "Motivation, connaissance de la formation", "critere": "Connaissance de la formation", "elements": "Lettre de motivation",
             "importance": "Très important"},
            {"champ": "Savoir-être", "critere": "Autonomie", "elements": "PFM et appréciations", "importance": "Essentiel"},
            {"champ": "Motivation", "critere": "Projet", "elements": "projet  de   formation", "importance": ""},
            {"champ": "Vide", "critere": "", "elements": "", "importance": "Essentiel"}],
          "eliminatoires": "Note < 8\nLettre de motivation hors sujet\nAbsence de projet motivé\n",
          "conseils": "  Soignez votre dossier.  "}, "mixed"),
        ({"criteres": [{"champ": "Résultats", "critere": "Notes", "elements": "Bulletins", "importance": "Essentiel"}],
          "eliminatoires": "", "conseils": ""}, "none named"),
        ({"criteres": [], "eliminatoires": "Lettre de motivation absente", "conseils": "x"}, "no criteria"),
        (None, "no texts"),
    ]


@check("J1 crafted texts: verbatim points naming the projet motivé, by importance then the jury's order; the rest counted; "
       "eliminating lines and advice verbatim")
def j1(c: Ctx):
    bad = []
    for t, name in crafted_texts():
        got, want = M["PJ"].checklist(t), ref_checklist(t)
        if got != want:
            bad.append((name, got and [p["critere"] for p in got["points"]], want and [p["critere"] for p in want["points"]]))
    mixed = M["PJ"].checklist(crafted_texts()[0][0]) or {}
    order = [p["critere"] for p in mixed.get("points", [])] == ["Autonomie", "Connaissance de la formation", "Engagement", "Projet"]
    return not bad and order, f"cases wrong {bad[:3]}; order by importance then the jury's {order}"


@check("J2 real reports: for_formation's points = the re-derivation from the report's own texts (sample)")
def j2(c: Ctx):
    from suptracker import rapports as RP
    cods = [x for (x,) in c.con.execute("""SELECT r.cod_aff_form FROM core.rapport r
        WHERE r.session = (SELECT max(session) FROM core.formation_year) ORDER BY hash(r.cod_aff_form) LIMIT ?""",
                                         [300 if c.real else 50]).fetchall()] if _has(c.con, "core", "rapport") else []
    bad, seen, with_points = [], 0, 0
    for cod in cods:
        rp = RP.for_formation(c.con, cod)
        got = M["PJ"].for_formation(c.con, cod)
        want = ref_checklist(rp["textes"]) if rp else None
        if want is None:
            if got and got["source"] == "rapport":
                bad.append((cod, "own points without readable texts"))
            continue
        seen += 1
        with_points += bool(want["points"])
        keep = {k: got.get(k) for k in want} if got else None
        if not got or got["source"] != "rapport" or keep != want or got["session"] != rp["session"]:
            bad.append((cod, "differs"))
    ok = not bad and (seen > 0 and with_points > 0 or not c.real)
    return ok, f"{seen} formations read, {with_points} with points; problems {bad[:3]}"


def _has(con, schema, table):
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                            [schema, table]).fetchone()[0])


def ref_similar(texts):
    pats = [("resultats", r"r[ée]sultat"), ("competences", r"comp[ée]tence|savoir-\s?faire"), ("savoir_etre", r"savoir[- ][êe]tre"),
            ("motivation", r"motivation|coh[ée]rence du projet|connaissance de la"), ("engagements", r"engagement|int[ée]r[êe]t|extra|scolaires")]
    order = IMP + [""]
    out = {k: dict.fromkeys(order, 0) for k, _ in pats}
    n_cite = 0
    for t in texts:
        best = {}
        for cr in t.get("criteres") or []:
            if not names_projet(cr):
                continue
            lab = " ".join(str(cr.get("champ") or "").lower().split())
            k = next((k for k, p in pats if re.search(p, lab)), None)
            imp = cr.get("importance") if cr.get("importance") in IMP else ""
            if k and (k not in best or order.index(imp) < order.index(best[k])):
                best[k] = imp
        n_cite += bool(best)
        for k, imp in best.items():
            out[k][imp] += 1
    return n_cite, out


@check("J3 similar formations: n citing and field x importance counts re-derived from the group's verified reports")
def j3(c: Ctx):
    from suptracker import rapports as RP
    if not _has(c.con, "mart", "semblable_jury"):
        return (not c.real), "mart.semblable_jury missing"
    groups = c.con.execute("""SELECT session, fili, filiere, n_rapports, data FROM mart.semblable_jury
        ORDER BY hash(filiere) LIMIT 25""").fetchall()
    bad, checked = [], 0
    for s, fi, fl, n, data in groups:
        pj = json.loads(data).get("projet")
        if pj is None:
            bad.append((fl, "no projet counts in the mart (rebuild)"))
            continue
        digs = [d for (d,) in c.con.execute("""SELECT DISTINCT r.digest FROM core.rapport r JOIN core.formation_year f USING (cod_aff_form, session)
            WHERE r.session = ? AND f.fili = ? AND f.fil_lib_voe_acc = ? AND coalesce(r.recoupe, true)""", [s, fi, fl]).fetchall()]
        texts = [json.loads(t) for t in (RP.texte(c.con, d) for d in digs) if t]
        n_cite, champs = ref_similar(texts)
        checked += 1
        if pj["n_cite"] != n_cite or pj["champs"] != champs:
            bad.append((fl, pj["n_cite"], n_cite))
    # a formation without readable texts of its own is served the counts, labelled as similar formations
    cod = next((x for (x,) in c.con.execute("""SELECT f.cod_aff_form FROM core.formation_year f
        WHERE f.session = (SELECT max(session) FROM core.formation_year)
          AND f.cod_aff_form NOT IN (SELECT cod_aff_form FROM core.rapport) ORDER BY hash(f.cod_aff_form) LIMIT 400""").fetchall()
                if (M["PJ"].for_formation(c.con, x) or {}).get("source") == "semblables"), None) if _has(c.con, "core", "rapport") else None
    served = True
    if cod:
        r = M["PJ"].for_formation(c.con, cod)
        served = r["source"] == "semblables" and "points" not in r and r["n_cite"] <= r["n_rapports"]
    ok = not bad and served and (checked > 0 or not c.real) and (cod is not None or not c.real)
    return ok, f"groups checked {checked}, wrong {bad[:3]}; a formation without its own texts gets counts only {served} ({cod})"


def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api

    class _C:
        def __enter__(self):
            self.old = os.environ.get("SUPTRACKER_DB")
            os.environ["SUPTRACKER_DB"] = str(db)
            api._con.cache_clear()
            self.calls, self.saved = [], A.record
            A.record = lambda *a, **k: self.calls.append(a) or "ok"
            return TestClient(api.app), self.calls

        def __exit__(self, *exc):
            A.record = self.saved
            if self.old is None:
                os.environ.pop("SUPTRACKER_DB", None)
            else:
                os.environ["SUPTRACKER_DB"] = self.old
            api._con.cache_clear()
    return _C()


@check("J4 API: /api/projet = the formation page's block; bad code 422, unknown 404; shared-cacheable; no analytics event")
def j4(c: Ctx):
    cod = None
    if _has(c.con, "core", "rapport"):
        cod = next(iter(c.con.execute("""SELECT cod_aff_form FROM core.rapport WHERE session = (SELECT max(session) FROM core.formation_year)
            ORDER BY hash(cod_aff_form) LIMIT 1""").fetchall()), (None,))[0]
    cod = cod or c.con.execute("SELECT min(cod_aff_form) FROM core.formation_year").fetchone()[0]
    with client(c.db) as (cl, calls):
        r = cl.get(f"/api/projet/{cod}")
        page = cl.get(f"/api/formation/{cod}").json().get("projet", "missing")
        codes = (r.status_code, cl.get("/api/projet/12a").status_code, cl.get("/api/projet/999999999").status_code)
        cache = r.headers.get("cache-control", "")
        n_events = sum(1 for a in calls if a and isinstance(a[0], dict) and a[0].get("t") == "projet")
    same = r.status_code == 200 and r.json()["projet"] == page
    ok = codes == (200, 422, 404) and "s-maxage" in cache and same and n_events == 0
    return ok, f"status {codes}; cache {cache!r}; same as the formation page {same}; events {n_events}"


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i: js.index(end, i)]


def render(js: str, pjs: list):
    n = shutil.which("node")
    if not n:
        return None
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ")))
    rp_consts = block(js, "const RP_SPE = ", "function juryCard(")
    pend = block(js, "const rpPending = ", "function rapportDoublettes(")
    sem_name = block(js, "const semName = ", "\n") + "\n"
    part = block(js, "// ---- \"Préparer son projet motivé\"", "// the 4-year curves of the evolution page:")
    prog = (helpers + "\nconst tip = () => '';\n" + rp_consts + pend + sem_name + part + """
const pjs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(pjs.map((p) => projetCard(p))));""")
    r = subprocess.run([n, "-e", prog], input=json.dumps(pjs), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-600:]}


HOSTILE_OWN = {"source": "rapport", "session": 2026, "recoupe": False, "live": True, "archive": "https://dossier.parcoursup.fr/x",
               "capture": "20260115", "points": [{"champ": HOSTILE, "critere": HOSTILE, "elements": HOSTILE, "importance": "Essentiel"},
                                                 {"champ": "c", "critere": "d", "elements": "e", "importance": ""}],
               "n_criteres": 5, "autres_criteres": 3, "eliminatoires": [HOSTILE], "conseils": HOSTILE + "\nligne"}
HOSTILE_SEM = {"source": "semblables", "session": 2025, "n_rapports": 9, "n_cite": 7, "fili": "BUT", "filiere": HOSTILE,
               "formations": [], "champs": [{"key": "motivation", "label": HOSTILE, "n": 6,
                                             "importances": {"Essentiel": 4, "Très important": 0, "Important": 2, "Complémentaire": 0, "": 0}}]}


def ui(js: str) -> tuple[bool, str]:
    o = render(js, [HOSTILE_OWN, HOSTILE_SEM, None])
    if o is None:
        return True, "node not installed"
    if isinstance(o, dict):
        return False, o["error"]
    own, sem, none = o
    raw = any("<img" in x for x in o)
    words = ("mot pour mot" in own and "fait foi" in own and "ne disent pas vos chances" in own and "ne rédigent pas votre texte" in own
             and "Le jury regarde : « &lt;img" in own and "pas encore recoupé avec les chiffres de 2026" in own
             and "lu le 15/01/2026 sur la fiche Parcoursup" in own and "3 autres critères" in own)
    sem_ok = ("pas le rapport de cette formation" in sem and "pas les critères de celle-ci" in sem and "Sur 9 rapports" in sem
              and "7 citent" in sem and "Essentiel 4, Important 2" in sem and "fait foi" in sem)
    none_ok = "Aucun rapport public" in none and "fait foi" in none
    chance = [x for x in o if re.search(r"(?i)\d+\s*% de chances|probabilit|vous serez admis|garanti", x)]
    tu = [x for x in o if re.search(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b", re.sub(r"<[^>]+>", " ", x.replace("&lt;img src=x onerror=alert(1)&gt;", "")))]
    wired = ('projetCard(d.projet) + (juryCard(d.rapport) || semblablesJuryCard(d.semblables, d.rapport))' in js
             and 'r = await api(`/api/projet/${encodeURIComponent(el.dataset.pjcod)}`)' in js
             and "if (el.isConnected) body.innerHTML = projetBody(r.projet);" in js
             and "if (!el.open || el.dataset.loaded) return;" in js)
    ok = not raw and words and sem_ok and none_ok and not chance and not tu and wired
    return ok, (f"raw tag {raw}; own report wording {words}; similar formations {sem_ok}; no report {none_ok}; chance {len(chance)}; "
                f"tutoiement {len(tu)}; wired (jury tab, Mes vœux on opening, guarded) {wired}")


@check("J5 pages (Node, hostile texts): escaped, quoted, caveats, similar formations labelled, pending mark, wording, wiring")
def j5(c: Ctx):
    from suptracker import api, glossary
    ok, d = ui(c.js)
    extra = "projet_motive" in api.FEATURES and "projet_motive" in api.METHODOLOGY and any(g["key"] == "projet_motive" for g in glossary.as_list())
    return ok and extra, d + f"; feature, method, glossary {extra}"


PY_MUTANTS = [
    ("lettre de motivation not read", r"|lettre\s+de\s+motiv", ""),
    ("every criterion kept", "    pts = [c for c in crit if cites(c)]\n", "    pts = list(crit)\n"),
    ("jury's order instead of importance", "key=lambda x: (_rank(x[1]), x[0])", "key=lambda x: x[0]"),
    ("importance reversed", "key=lambda x: (_rank(x[1]), x[0])", "key=lambda x: (-_rank(x[1]), x[0])"),
    ("every eliminating line quoted", "for ln in (textes.get(\"eliminatoires\") or \"\").splitlines() if PROJET.search(ln)]",
     "for ln in (textes.get(\"eliminatoires\") or \"\").splitlines()]"),
    ("other criteria miscounted", "\"autres_criteres\": len(crit) - len(pts)", "\"autres_criteres\": len(crit)"),
    ("similar: every importance counted", "if k not in best or (IMPORTANCES + (\"\",)).index(imp) < (IMPORTANCES + (\"\",)).index(best[k]):",
     "if True:"),
    ("similar: a report counted without citing", "            if not cites(c):\n                continue\n", ""),
]
UI_MUTANTS = [
    ("criterion unescaped", "<strong>${esc(p.critere)}</strong>", "<strong>${p.critere}</strong>"),
    ("eliminating line unescaped", "« ${esc(l)} »", "« ${l} »"),
    ("similar formations shown as own", '<span class="estim">pas le rapport de cette formation</span> ', ""),
    ("caveat dropped", 'const PJ_CAVEAT = "Ces points ne rédigent pas votre texte et ne disent pas vos chances',
     'const PJ_CAVEAT = "Ces points'),
    ("pending mark dropped", "de cette formation${rpPending(pj)} :", "de cette formation :"),
    ("Mes vœux answer drawn after leaving", "if (el.isConnected) body.innerHTML = projetBody(r.projet);", "body.innerHTML = projetBody(r.projet);"),
    ("not on the formation page", "projetCard(d.projet) + (juryCard", "(juryCard"),
]


def mutated(old: str, new: str):
    path = Path(PJ.__file__)
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType("suptracker._projet_mutant")
    m.__package__, m.__file__ = "suptracker", str(path)
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


def similar_caught(m) -> bool:
    """A similar-counts mutant is caught when its counts differ from the reference on crafted texts."""
    texts = [t for t, _ in crafted_texts() if t] + [
        {"criteres": [{"champ": "Motivation, connaissance de la formation", "critere": "a", "elements": "lettre de motivation", "importance": "Complémentaire"},
                      {"champ": "Motivation", "critere": "b", "elements": "projet motivé", "importance": "Essentiel"},
                      {"champ": "Résultats académiques", "critere": "c", "elements": "Bulletins", "importance": "Essentiel"}]}]
    got = m.similar_counts(texts)
    n, champs = ref_similar(texts)
    return got["n_cite"] != n or got["champs"] != champs


@check("J6 mutation test: selection, order, quotes, counts and page bugs are each caught")
def j6(c: Ctx):
    missed = []
    for name, old, new in PY_MUTANTS:
        m = mutated(old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)")
            continue
        saved, M["PJ"] = M["PJ"], m
        try:
            caught = not j1(c)[0] or similar_caught(m)
        finally:
            M["PJ"] = saved
        if not caught:
            missed.append(name)
    for name, old, new in UI_MUTANTS:
        if old not in c.js or ui(c.js.replace(old, new, 1))[0]:
            missed.append(name)
    n = len(PY_MUTANTS) + len(UI_MUTANTS)
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
