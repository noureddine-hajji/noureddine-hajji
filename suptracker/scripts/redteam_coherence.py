"""Red team of audit PR 8 (owner, 2026-11-25): one count of the list, one message on the search page, one name for a formation,
no error on « Mon profil », a lighter search page.

    python scripts/redteam_coherence.py [--db data/suptracker.duckdb] [--real] [--browser]

The re-audit of 2026-11-25 (same rubric as 2026-11-23) found five defects, each re-checked by hand:
  1. Mes vœux outside terminale said « 3 vœux » and « Mes 3 vœux » while its « Avant de confirmer » card said « 3 formations, soit
     2 vœux » (PR 7 counted the vœux multiples in that card only);
  2. « école de commerce » + Lyon printed « Aucune formation ne correspond » twice while 22 paid formations were only hidden;
  3. the formation page of a licence named « Economie et gestion » while Mes vœux and Plan B named its parcours « Economie et
     gestion - Informatique » (the student thought she had added the wrong formation);
  4. « Mon profil » threw « Failed to set the 'innerHTML' property … moved in a 'blur' event handler » before the first save;
  5. the search page blocked a phone longer than before (Lighthouse 49, 1.0-1.6 s of blocking time against 0.8 s).

  CO1 count: the page's vxCompteTxt / vxTitre / zoneTiles (Node) = an independent wording on crafted lists (groups, a lone
      sub-wish, none); both Mes vœux views title the list with vxTitre and the reading outside terminale counts with it; no
      « Mes N vœux » from the list's length is left; /api/voeux and /api/reorientation/voeux rows carry the group of
      multiples.of_codes and n_voeux = an independent count (real warehouse)
  CO2 search: when the criteria keep nothing but hidden paid formations, the status says so with the button, never « Aucune
      formation ne correspond » beside them; the list's empty line says the same (escaped); the count is computed first
  CO3 one name: for every formation (crafted rows, the warehouse's rows), each part of the complement Mes vœux and Plan B show is
      on the formation page (in its title, its h1 or the new line), the new line repeats neither, a parcours (detail_forma) the
      title lacks is always shown; the page escapes it; the API serves it
  CO4 « Mon profil »: a change fired by a field LOSING focus is acted on after the blur (form still on the page), a change of a
      focused field at once; the four actions unchanged
  CO5 lighter search page (Node twins): coucheDetailsParts = coucheDetails(C, coucheDecode(D)) on the warehouse's layer, sliced;
      carteMerge writes on the layer's rows (no copy) and resets zone and large; setHtml writes only a changed content; the place
      suggestions are written on first use, the same list; details and figures redraw the cards only; zones already here are
      read before the first draw
  CO6 browser (--browser / --real): the search page on an emulated phone (CPU x4) makes ONE full draw without a profile and at
      most TWO with one (four before), its long tasks printed; « école de commerce » + Lyon (real data) says the paid ones and shows
      them on click; the formation page shows the parcours Mes vœux names; Mes vœux counts a vœu multiple once in its title and
      reading; « Mon profil » filled field by field then saved raises no error and saves the profile; no JS error, no scroll
  CO7 mutation test of CO1-CO5 and CO8 (mutants built in memory)
  CO8 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration, nightly browser suite
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_co")
    m.__package__ = "suptracker"
    m.__file__ = str(ROOT / "suptracker" / f"{name}.py")
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db = db if db and Path(db).exists() else None
        self.real = real and self.db is not None
        self.browser = browser and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text() for k in ("planb", "api", "voeux", "multiples")}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.nightly = (ROOT / "scripts" / "browser_nightly.py").read_text()

    def mod(self, k):
        return load(k, self.src[k])

    def con(self):
        return duckdb.connect(str(self.db), read_only=True)


def top(js: str, name: str) -> str:
    import redteam_liste as RL
    return RL.top(js, name)


def fn_src(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", js, re.M)
    return js[m.start(): js.find("\n}", m.start()) + 2] if m else ""


def view_src(js: str, name: str) -> str:
    """The body of a (possibly async) top-level view function, up to the next top-level function."""
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(", js, re.M)
    if not m:
        return ""
    n = re.search(r"^(?:async )?function \w+\(", js[m.end():], re.M)
    return js[m.start(): m.end() + (n.start() if n else len(js))]


def node(prog: str, data=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout)


def txt(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ").replace(" ", " ").strip()


# ------------------------------------------------------------------ CO1 count
def rt_key(v):
    g = v.get("voeu_multiple")
    return (g["session"], g["nom"], g["formation"]) if g else None


def rt_count(voeux) -> int:
    keys = [rt_key(v) for v in voeux]
    return sum(k is None for k in keys) + len({k for k in keys if k is not None})


def plural(n, one, many):
    return one if n <= 1 else many


def rt_compte_txt(n, m) -> str:
    return f"{n} {plural(n, 'vœu', 'vœux')}" if m == n else f"{n} formations, soit {m} {plural(m, 'vœu', 'vœux')} sur Parcoursup"


def rt_titre(L) -> str:
    n, m = len(L), rt_count(L)
    return f"Mes {n} {plural(n, 'vœu', 'vœux')}" if m == n else f"Mes {n} formations ({m} {plural(m, 'vœu', 'vœux')} sur Parcoursup)"


def crafted_lists():
    rnd = random.Random(20261125)
    g = [{"nom": n, "formation": "D.E Infirmier", "session": 2026, "n_formations": 6} for n in ("Regroupement IFSI A", "Regroupement IFSI B")]
    g.append({"nom": "Regroupement IFSI A", "formation": "D.E Infirmier", "session": 2025, "n_formations": 3})
    out = [[], [{"cod_aff_form": "1", "voeu_multiple": None}], [{"cod_aff_form": "1", "voeu_multiple": g[0]}],
           [{"cod_aff_form": str(i), "voeu_multiple": g[0]} for i in range(3)]]
    for _ in range(120):
        out.append([{"cod_aff_form": str(i), "voeu_multiple": rnd.choice(g + [None, None])} for i in range(rnd.randint(1, 10))])
    return out


def co1_static(js: str, api: str) -> list[str]:
    bad = []
    vx, reo = view_src(js, "viewVoeux"), js
    if js.count("<h2>${vxTitre(d.voeux)}</h2>") != 2:
        bad.append("both Mes vœux views title the list with vxTitre")
    if re.search(r"Mes \$\{fmt\(d\.voeux\.length\)\} vœu", js):
        bad.append("a « Mes N vœux » from the list's length is left")
    if "${vxCompteTxt(d.voeux.length, vxCompte(d.voeux))} · ${fmt(nEst)}" not in reo:
        bad.append("the reading outside terminale counts formations as vœux")
    if 'vxCompte(d.voeux) === d.voeux.length ? "vœu" : "formation")}' not in vx:
        bad.append("the zone tiles count sub-wishes as vœux")
    if "const compte = vxCompteTxt(n, nVx);" not in fn_src(js, "verifierCard"):
        bad.append("the « Avant de confirmer » card has its own wording")
    if 'Vous avez ${n} formation${n > 1 ? "s" : ""} dans votre liste' not in js:
        bad.append("the home's link counts formations as vœux")
    if api.count("_with_groups(") < 3 or api.count('"n_voeux": MU.compte(') != 2:
        bad.append("/api/voeux and /api/reorientation/voeux carry the groups and the count")
    if 'groups.get(v["cod_aff_form"])}' not in api:
        bad.append("_with_groups reads multiples.of_codes")
    return bad


@check("CO1 count: vxCompteTxt / vxTitre / zoneTiles = an independent wording; both Mes vœux views and the APIs count a vœu multiple once")
def co1(c: Ctx):
    bad = co1_static(c.js, c.src["api"])
    lists = crafted_lists()
    prog = "\n".join(top(c.js, n) for n in ("esc", "fmt", "vmKey", "vxCompte", "vxCompteTxt", "vxTitre", "zoneTiles")) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({ t: P.map((L) => [vxTitre(L), vxCompteTxt(L.length, vxCompte(L))]),
  tiles: [zoneTiles({ securite: 2, cible: 1, ambitieux: 0 }, 1, 0), zoneTiles({ securite: 2, cible: 1, ambitieux: 0 }, 1, 0, "formation")] }));"""
    prog = "const zonePillHtml = (k) => `<span>${k}</span>`;\n" + prog
    r = node(prog, lists)
    if r is not None:
        for L, (titre, compte) in zip(lists, r["t"]):
            if not L:
                continue
            if titre != rt_titre(L) or compte != rt_compte_txt(len(L), rt_count(L)):
                bad.append(f"{len(L)} formations / {rt_count(L)} vœux: {titre!r} {compte!r}")
                break
        if r["tiles"] is not None:
            v, f = (txt(x) for x in r["tiles"])
            if "2 vœux" not in v or "1 vœu " not in v + " " or "2 formations" not in f or "1 formation " not in f + " " or "vœu" in f.replace("Autres", ""):
                bad.append(f"tiles {v[:80]!r} / {f[:80]!r}")
    n_api = 0
    if c.real:
        from fastapi.testclient import TestClient

        from suptracker import api
        con = c.con()
        try:
            has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_name='voeu_multiple'").fetchone()[0]
            grp = con.execute("""SELECT list(cod_aff_form ORDER BY cod_aff_form) FROM core.voeu_multiple GROUP BY session, nom, formation
                HAVING count(*) >= 2 ORDER BY min(cod_aff_form) LIMIT 1""").fetchone() if has else None
            other = con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
                AND cod_aff_form NOT IN (SELECT cod_aff_form FROM core.voeu_multiple) ORDER BY cod_aff_form LIMIT 1""").fetchone() if has else None
        finally:
            con.close()
        if grp and other:
            ids = [*grp[0][:2], other[0]]
            mu = c.mod("multiples")
            want_g = mu.of_codes(c.con(), ids)
            cl = TestClient(api.app)
            for url in (f"/api/reorientation/voeux?ids={','.join(ids)}",
                        f"/api/voeux?ids={','.join(ids)}&serie=bg&spe1=MATHS&spe2=SES&mention=ab"):
                d = cl.get(url).json()
                got = {v["cod_aff_form"]: v.get("voeu_multiple") for v in d.get("voeux", [])}
                n_api += 1
                if got != {k: want_g.get(k) for k in ids} or d.get("n_voeux") != rt_count(d["voeux"]) or d.get("n_voeux") != 2:
                    bad.append(f"{url.split('?')[0]}: {got} n_voeux {d.get('n_voeux')}")
    return not bad, f"{len(lists)} crafted lists{'' if r is not None else ' (node absent)'}; {n_api} API answers; {bad[:4]}"


# ------------------------------------------------------------------ CO2 search
def co2_static(js: str) -> list[str]:
    bad = []
    v = view_src(js, "viewCarte")
    i_paid = v.find("const paid = carteHiddenPaid(shown(), F, kw)")
    i_status = v.find('setHtml(document.getElementById("cs-status"), [')
    i_only = v.find("!kept.length && paid ? `<p class=\"info cs-paid-only\">")
    i_none = v.find("Aucune formation ne correspond.")
    if min(i_paid, i_status, i_only, i_none) < 0 or not i_paid < i_status < i_only < i_none:
        bad.append("the paid-only message comes first, the count before it")
    elif not re.match(r"[^\n]*\n\s*: !kept\.length && \(kw \|\| F\.lieu", v[i_only:]):
        bad.append("« Aucune formation ne correspond » is not the alternative of the paid-only message")
    if v.count("data-show-paid") < 2 or 'document.querySelectorAll("#cs-status [data-show-paid]").forEach((b) => { b.onclick = showPaid; });' not in v:
        bad.append("the status button does not show the paid ones")
    if "carteList(lastCards.listed, ctx, lastCards.empty)" not in v or "privés payants (voir ci-dessus)" not in v:
        bad.append("the empty list line does not say the paid ones")
    return bad


@check("CO2 search: nothing kept but hidden paid formations = said with the button, never « Aucune formation ne correspond »")
def co2(c: Ctx):
    bad = co2_static(c.js)
    prog = "\n".join(top(c.js, n) for n in ("esc", "fmt", "carteList")) + """
const carteUI = { page: 0 }; const cartePage = () => 10; const carteCard = () => 'CARD';
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify([carteList([], {}, P.e), carteList([], {}, null), carteList([{}], {}, P.e)]));"""
    r = node(prog, {"e": "Les 3 sont " + HOSTILE})
    if r is not None:
        e, d, full = r
        if "<img" in e or "Les 3 sont" not in txt(e) or "Aucune formation ne correspond" not in txt(d) or "CARD" not in full or "Les 3" in full:
            bad.append(f"carteList empty line {e[:90]!r} / {d[:60]!r}")
    m = re.search(r"cs-paid-only\">([^\n]*?)<button", c.js)
    if not m or TU.search(m.group(1)) or "masqués par défaut" not in m.group(1):
        bad.append("wording of the paid-only message")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ CO3 one name
def rt_fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


CRAFTED_RECS = [
    {"lib_for_voe_ins": "Licence - Economie et gestion", "g_ea_lib_vx": "Université Lumière - Lyon 2", "fili": "Licence",
     "fil_lib_voe_acc": "Economie et gestion", "form_lib_voe_acc": "Licence - Droit-économie-gestion",
     "lib_comp_voe_ins": "Université Lumière - Lyon 2 - Licence - Economie et gestion", "detail_forma": "Economie et gestion - Informatique"},
    {"lib_for_voe_ins": "BTS - Services - Assurance", "g_ea_lib_vx": "Lycée A", "fili": "BTS", "fil_lib_voe_acc": "Assurance",
     "form_lib_voe_acc": "BTS - Services", "lib_comp_voe_ins": "Lycée A - BTS - Services - Assurance", "detail_forma": None},
    {"lib_for_voe_ins": "D.E Infirmier", "g_ea_lib_vx": "IFSI X", "fili": "IFSI", "fil_lib_voe_acc": "D.E Infirmier",
     "form_lib_voe_acc": "D.E Infirmier", "lib_comp_voe_ins": "IFSI X - D.E Infirmier", "detail_forma": "Regroupement IFSI " + HOSTILE},
    {"lib_for_voe_ins": "Licence - Langues - Parcours LLCER Anglais", "g_ea_lib_vx": "Université B", "fili": "Licence",
     "fil_lib_voe_acc": "Langues", "form_lib_voe_acc": "Licence", "lib_comp_voe_ins": "Université B - Licence - Langues - Parcours LLCER Anglais",
     "detail_forma": "Parcours LLCER Anglais"},
    # a real 2025 row (Université du littoral): its parcours line is only the h1, so the page must not print it again
    {"lib_for_voe_ins": "Licence - Portail Droit", "g_ea_lib_vx": "Université du littoral - Site de Boulogne-sur-Mer", "fili": "Licence_Las",
     "fil_lib_voe_acc": "Droit", "form_lib_voe_acc": "Licence - Droit-économie-gestion",
     "lib_comp_voe_ins": "Université du littoral - Site de Boulogne-sur-Mer - Licence - Portail Droit",
     "detail_forma": ": Université du littoral - Site de Boulogne-sur-Mer"},
]


def co3_rows(c: Ctx, real: bool):
    if c.db is None:
        return []
    con = c.con()
    try:
        cur = con.execute("SELECT * FROM core.formation_year" + ("" if real else " USING SAMPLE 3000 ROWS"))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def co3_check(pb, recs) -> list:
    bad = []
    for rec in recs:
        full, fiche = pb.complement_of(rec), pb.complement_fiche(rec)
        seen = [rt_fold(rec.get("lib_for_voe_ins") or ""), rt_fold(rec.get("g_ea_lib_vx") or "")]
        parts = [p for p in (full or "").split(" · ") if p.strip()]
        fparts = [p for p in (fiche or "").split(" · ") if p.strip()]
        shown = " ".join(seen + [rt_fold(p) for p in fparts])
        lost = [p for p in parts if rt_fold(p) not in shown]
        twice = [p for p in fparts if any(rt_fold(p) in s for s in seen)]
        foreign = [p for p in fparts if p not in parts]
        det = rec.get("detail_forma")
        miss_det = det and not any(rt_fold(det) in s for s in seen) and rt_fold(det) not in shown
        same_view = pb._view({"complement": rec.get("lib_comp_voe_ins"), "etablissement": rec.get("g_ea_lib_vx"), "fili": rec.get("fili"),
                              "filiere": rec.get("fil_lib_voe_acc"), "form_lib_voe_acc": rec.get("form_lib_voe_acc"),
                              "detail_forma": det, "spos": None}, None)["complement"] == full
        if lost or twice or foreign or miss_det or not same_view or (fiche is not None and not fiche.strip()):
            bad.append((rec.get("cod_aff_form"), rec.get("lib_for_voe_ins"), full, fiche, lost[:1], twice[:1], bool(miss_det), same_view))
    return bad


@check("CO3 one name: every part Mes vœux / Plan B show is on the formation page, never twice; the parcours always; escaped; served")
def co3(c: Ctx):
    pb = c.mod("planb")
    recs = CRAFTED_RECS + co3_rows(c, c.real)
    bad = co3_check(pb, recs)
    if pb.complement_fiche(CRAFTED_RECS[0]) != "Economie et gestion - Informatique":
        bad.append(("the licence's parcours", pb.complement_fiche(CRAFTED_RECS[0])))
    if pb.complement_fiche(CRAFTED_RECS[1]) is not None or pb.complement_fiche(CRAFTED_RECS[3]) is not None \
            or pb.complement_fiche(CRAFTED_RECS[4]) is not None:
        bad.append(("a part the title prints is repeated", pb.complement_fiche(CRAFTED_RECS[1]), pb.complement_fiche(CRAFTED_RECS[3])))
    if '${d.complement ? `<span class="fhead-parcours"> · ${esc(d.complement)}</span>` : ""}' not in c.js:
        bad.append("the formation page does not print it (escaped)")
    if '"complement": PB.complement_fiche(rec),' not in c.src["api"]:
        bad.append("/api/formation does not serve it")
    if '"complement": PB._view(f, None)["complement"]' not in c.src["voeux"]:
        bad.append("Mes vœux reads another complement")
    served = None
    if c.real:
        from fastapi.testclient import TestClient

        from suptracker import api
        served = TestClient(api.app).get("/api/formation/35342").json().get("complement")
        if served is not None and "Informatique" not in served:
            bad.append(("35342 served", served))
    n_shown = sum(1 for r in recs if pb.complement_fiche(r))
    return not bad, f"{len(recs)} formations, {n_shown} with a line on their page; 35342 served {served!r}; {bad[:3]}"


# ------------------------------------------------------------------ CO4 « Mon profil »
PROFILE_ACT = '''      const act = () => {
        if (name === "moyenne" && badMoyenne()) return;
        if (name === "statut") return setSituation(e.target.value, has, raw, new FormData(form), p, serie, lyc, form);
        if (has) { form.requestSubmit(); return; }
        draft = { ...(draft || {}), ...readForm(new FormData(form), p, serie, lyc, form, null) }; draw(name);'''


@check("CO4 « Mon profil »: a change fired by a blur is acted on after it (form still on the page), a focused field's change at once")
def co4(c: Ctx):
    bad = []
    m = re.search(r"    form\.onchange = \(e\) => \{\n(.*?)\n    \};\n", c.js, re.S)
    body = m.group(1) if m else ""
    if PROFILE_ACT not in body:
        bad.append("the four actions changed")
    if "if (document.activeElement === e.target) act();" not in body:
        bad.append("a focused field's change is not acted on at once")
    if "else setTimeout(() => { if (form.isConnected) act(); }, 0);" not in body:
        bad.append("a blur-fired change redraws inside the blur (or a gone form)")
    if body.count("draw(") != 1 or body.count("requestSubmit(") != 1:
        bad.append("a redraw outside act()")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ CO5 lighter search page
@contextlib.contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient
    old = os.environ.get("SUPTRACKER_DB")
    os.environ["SUPTRACKER_DB"] = str(db)
    from suptracker import api
    from suptracker import carte as CA
    api._con.cache_clear()
    CA._COUCHE.clear()
    try:
        yield TestClient(api.app)
    finally:
        api._con.cache_clear()
        CA._COUCHE.clear()
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old


def twins_run(js: str, base: dict, det: dict, slice_rows: int = 7):
    exe = shutil.which("node")
    if not exe:
        return None
    src = "\n".join(top(js, n) for n in ("coucheDec", "coucheDecode", "coucheDetails", "coucheDetailsParts", "carteMerge", "setHtml"))
    src = re.sub(r"const CARTE_SLICE = \d+;", "", src)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "b.json").write_text(json.dumps(base))
        Path(d, "d.json").write_text(json.dumps(det))
        Path(d, "t.js").write_text(f"const CARTE_SLICE = {slice_rows};\n" + src + """
const fs = require('fs');
(async () => {
  const B = JSON.parse(fs.readFileSync(process.argv[2])), D = JSON.parse(fs.readFileSync(process.argv[3]));
  const C1 = coucheDecode(B), C2 = coucheDecode(B);
  coucheDetails(C1, coucheDecode(D));
  let yields = 0; const st = global.setTimeout; global.setTimeout = (f, t) => { yields++; return st(f, t); };
  const same = await coucheDetailsParts(C2, D);
  global.setTimeout = st;
  const equal = JSON.stringify(C1) === JSON.stringify(C2);
  const rows = C2.rows.slice(0, 50);
  const merged = carteMerge(rows, { formations: [{ cod_aff_form: rows[0].cod_aff_form, zone: 'cible' }] }, true);
  const identity = merged === rows && merged[0] === C2.rows[0], zone0 = merged[0].zone, zone1 = merged[1].zone;
  rows[1].zone = 'securite'; rows[1].large = true;
  const again = carteMerge(rows, null, false);
  const el = { innerHTML: '', writes: 0 }; Object.defineProperty(el, 'innerHTML', { set(v) { this.writes++; this._h = v; }, get() { return this._h; } });
  setHtml(el, 'a'); setHtml(el, 'a'); setHtml(el, 'b'); setHtml(null, 'x');
  fs.writeFileSync(process.argv[4], JSON.stringify({ equal, details: C2.details === true && same === C2,
    yields, n: C2.rows.length, identity, zone0, zone1,
    reset: again.every((f) => f.zone === null && f.large === false), writes: el.writes, last: el._h }));
})().catch((e) => { console.error(e); process.exit(1); });""")
        r = subprocess.run([exe, str(Path(d, "t.js")), str(Path(d, "b.json")), str(Path(d, "d.json")), str(Path(d, "o.json"))],
                           capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise RuntimeError(r.stderr[-400:])
        return json.loads(Path(d, "o.json").read_text())


def co5_static(js: str) -> list[str]:
    bad = []
    v = view_src(js, "viewCarte")
    if "{ ...f, zone" in fn_src(js, "carteMerge"):
        bad.append("carteMerge copies every formation again")
    if 'api("/api/carte/couche?partie=details").then((D) => coucheDetailsParts(C, D))' not in v:
        bad.append("the details are decoded in one task")
    if "CARTE_DETAIL_KEYS.forEach((k) => { if (k in g) f[k] = g[k]; });" in v:
        bad.append("the details are copied a second time")
    if '<datalist id="cs-lieux"></datalist>' not in v or "[...lieux.keys()].map((l) => `<option value=\"${esc(l)}\">`).join(\"\")" not in v \
            or 'lieuEl.addEventListener("focus", fillLieux, { once: true });' not in v or "lieuEl.oninput = () => { fillLieux();" not in v:
        bad.append("the place suggestions are not written on first use (same list)")
    for el in ("cs-status", "carte-count", "carte-legend"):
        if f'setHtml(document.getElementById("{el}"), ' not in v or f'document.getElementById("{el}").innerHTML' in v:
            bad.append(f"#{el} is rewritten when unchanged")
    det = v[v.find("loadDetails(C)).then(() => {"):v.find("if (ok && !early) zonesP.then")]
    if det.count("drawCards();") != 2 or "draw(" in det.replace("drawCards(", ""):
        bad.append("the details redraw the whole page")
    if '$view.dataset.rendered === "carte") drawCards();' not in fn_src(v, "figures") and '$view.dataset.rendered === "carte") drawCards();' not in v:
        bad.append("the figures redraw the whole page")
    if "zonesP.then((zs) => { zonesEarly = zs; }, () => {});" not in v or "const early = ok && zonesEarly !== undefined;" not in v \
            or "if (ok && !early) zonesP.then((zs) => {" not in v:
        bad.append("zones already here are not read before the first draw")
    return bad


@check("CO5 lighter search page: sliced details = coucheDetails, no copy of the layer, unchanged lines kept, cards-only redraws")
def co5(c: Ctx):
    bad = co5_static(c.js)
    r = None
    if c.db is not None and shutil.which("node"):
        with client(c.db) as cl:
            base, det = cl.get("/api/carte/couche").json(), cl.get("/api/carte/couche?partie=details").json()
        if not c.real:
            base = {**base, "rows": base["rows"][:400]}
        r = twins_run(c.js, base, det, slice_rows=7 if not c.real else 1500)
        want_yields = max(0, -(-len(det["rows"]) // (7 if not c.real else 1500)) - 1)
        if not r["equal"] or not r["details"] or r["yields"] != want_yields:
            bad.append(("sliced details", r["equal"], r["details"], r["yields"], want_yields))
        if not r["identity"] or r["zone0"] != "cible" or r["zone1"] is not None or not r["reset"]:
            bad.append(("carteMerge", r["identity"], r["zone0"], r["zone1"], r["reset"]))
        if r["writes"] != 2 or r["last"] != "b":
            bad.append(("setHtml", r["writes"], r["last"]))
    return not bad, f"{'' if r is None else str(r['n']) + ' formations decoded'}; problems {bad[:4]}"


# ------------------------------------------------------------------ CO6 browser
BROWSER = r"""
const { chromium, devices } = require('playwright');
(async () => {
  const base = process.argv[2], P = JSON.parse(process.argv[3]), o = {}, errs = [];
  const b = await chromium.launch();
  const prof = { statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab', academie: 'Lyon' };
  // the search page on a phone, CPU x4: full draws (carteNameRank and carteFacets each run once per full draw) and long tasks
  for (const withProfile of [false, true]) {
    global.STEP = 'search ' + withProfile;
    const ctx = await b.newContext({ ...devices['Pixel 5'] }); const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(String(e)));
    if (withProfile) await ctx.addInitScript((pr) => localStorage.setItem('profile', pr), JSON.stringify(prof));
    const cdp = await ctx.newCDPSession(p); await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await p.addInitScript(() => { window.__long = []; new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push(Math.round(e.duration)))).observe({ type: 'longtask', buffered: true });
      window.__n = { rank: 0, facets: 0 };
      addEventListener('DOMContentLoaded', () => { for (const [k, fn] of [['rank', 'carteNameRank'], ['facets', 'carteFacets']]) { const f = window[fn]; window[fn] = function () { window.__n[k]++; return f.apply(this, arguments); }; } }); });
    await p.goto(base + '/#/carte');
    await p.waitForFunction(() => /formation/.test(document.getElementById('carte-count')?.textContent || ''), null, { timeout: 180000 });
    await p.waitForFunction(() => !document.querySelector('#carte-items .rc-bacs .muted')?.textContent?.includes('chargement'), null, { timeout: 180000 }).catch(() => {});
    await p.waitForTimeout(8000);
    o['search' + (withProfile ? 'P' : '')] = await p.evaluate(() => ({ n: window.__n, sum: window.__long.reduce((a, b) => a + b, 0), max: Math.max(0, ...window.__long),
      hs: document.documentElement.scrollWidth > innerWidth + 1, datalist: document.getElementById('cs-lieux').options.length }));
    await p.focus('#cs-lieu'); o['datalist' + (withProfile ? 'P' : '')] = await p.evaluate(() => document.getElementById('cs-lieux').options.length);
    await ctx.close();
  }
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } }); const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(String(e)));
  if (P.paid) {
    global.STEP = 'paid';
    await p.goto(base + '/#/carte'); await p.evaluate(() => localStorage.clear()); await p.goto(base + '/#/accueil'); await p.goto(base + '/#/carte');
    await p.waitForSelector('#cs-q', { timeout: 120000 }); await p.waitForTimeout(1500);
    await p.fill('#cs-q', 'école de commerce'); await p.fill('#cs-lieu', 'Académie de Lyon'); await p.click('.cs-go');
    await p.waitForFunction(() => /formation/.test(document.getElementById('carte-count')?.textContent || '') && document.getElementById('cs-q').value === 'école de commerce', null, { timeout: 120000 });
    await p.waitForTimeout(1500);
    o.paid = await p.evaluate(() => ({ status: document.getElementById('cs-status').textContent, items: document.getElementById('carte-items').textContent,
      only: !!document.querySelector('.cs-paid-only [data-show-paid]') }));
    const btn = await p.$('.cs-paid-only [data-show-paid]'); if (btn) { await btn.click(); await p.waitForTimeout(2000); }
    o.paidAfter = await p.evaluate(() => ({ count: document.getElementById('carte-count').textContent, only: !!document.querySelector('.cs-paid-only') }));
  }
  global.STEP = 'fiche';
  await p.goto(base + '/#/f/' + P.fiche); await p.waitForSelector('.fhead-lib', { timeout: 120000 });
  o.fiche = await p.evaluate(() => document.querySelector('.fhead-lib').textContent);
  if (P.group) {
    global.STEP = 'voeux';
    await p.evaluate((L) => { localStorage.setItem('voeux', JSON.stringify(L)); localStorage.setItem('profile', JSON.stringify({ statut: 'reorientation', academie: 'Lille' })); }, P.group);
    await p.goto(base + '/#/accueil'); await p.goto(base + '/#/voeux'); await p.waitForSelector('#vx-verifier .vf-list', { timeout: 120000 });
    o.reo = await p.evaluate(() => document.getElementById('view').innerText);
    await p.evaluate(() => localStorage.setItem('profile', JSON.stringify({ statut: 'terminale', serie: 'bg', spe1: 'MATHS', spe2: 'SES', mention: 'ab' })));
    await p.goto(base + '/#/accueil'); await p.goto(base + '/#/voeux'); await p.waitForSelector('#vx-verifier .vf-list', { timeout: 120000 });
    o.term = await p.evaluate(() => document.getElementById('view').innerText);
  }
  global.STEP = 'profil';
  const c2 = await b.newContext({ viewport: { width: 1440, height: 900 } }); const q = await c2.newPage(); const perr = []; q.on('pageerror', (e) => perr.push(String(e)));
  await q.goto(base + '/#/profil', { waitUntil: 'networkidle' }); await q.waitForTimeout(800);
  await q.click('text=En terminale');
  await q.selectOption('select[name=serie]', 'bg'); await q.selectOption('select[name=spe1]', 'MATHS'); await q.selectOption('select[name=spe2]', 'NSI');
  await q.selectOption('select[name=mention]', 'b'); await q.fill('input[name=moyenne]', '14,5'); await q.selectOption('select[name=academie]', P.acad);
  await q.fill('#pf-ville', 'Nan'); await q.waitForTimeout(800);
  await q.click('text=Enregistrer mon profil'); await q.waitForTimeout(2000);
  o.profil = await q.evaluate(() => JSON.parse(localStorage.getItem('profile') || 'null')); o.profilErr = perr;
  await b.close();
  process.stdout.write(JSON.stringify({ o, errs }));
})().catch((e) => { console.error('step ' + (global.STEP || '?') + ': ' + String(e).slice(0, 300)); process.exit(1); });
"""


@check("CO6 browser: one full draw without a profile (two with one), paid ones said, the parcours on the page, a vœu multiple once, no profile error")
def co6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    pb = c.mod("planb")
    con = c.con()
    try:
        cols = [d[0] for d in con.execute("SELECT * FROM core.formation_year LIMIT 0").description]
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        fiche = None
        for r in con.execute("SELECT * FROM core.formation_year WHERE session = ? AND detail_forma IS NOT NULL ORDER BY cod_aff_form = '35342' DESC, cod_aff_form",
                             [latest]).fetchall():
            rec = dict(zip(cols, r))
            if pb.complement_fiche(rec):
                fiche = (rec["cod_aff_form"], pb.complement_fiche(rec))
                break
        has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='core' AND table_name='voeu_multiple'").fetchone()[0]
        grp = con.execute("""SELECT list(cod_aff_form ORDER BY cod_aff_form) FROM core.voeu_multiple GROUP BY session, nom, formation
            HAVING count(*) >= 2 ORDER BY min(cod_aff_form) LIMIT 1""").fetchone() if has else None
        other = con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND cod_aff_form NOT IN
            (SELECT cod_aff_form FROM core.voeu_multiple) ORDER BY cod_aff_form LIMIT 1""", [latest]).fetchone() if has else None
        acad = con.execute("SELECT min(acad_mies) FROM core.formation_year WHERE session = ?", [latest]).fetchone()[0]
    finally:
        con.close()
    group = [*grp[0][:2], other[0]] if grp and other else None
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".coherence_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}",
                                json.dumps({"paid": c.real, "fiche": fiche[0] if fiche else "1", "group": group, "acad": acad or "Lyon"})],
                               capture_output=True, text=True, timeout=1500, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-800:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    s0, s1 = o["search"], o["searchP"]
    if s0["n"]["rank"] > 1 or s0["n"]["facets"] > 1:
        bad.append(("full draws without a profile", s0["n"]))
    if s1["n"]["rank"] > 2 or s1["n"]["facets"] > 2:
        bad.append(("full draws with a profile", s1["n"]))
    if max(s0["max"], s1["max"]) > 2500:
        bad.append(("a long task over 2.5 s at CPU x4", s0["max"], s1["max"]))
    if s0["datalist"] or s1["datalist"] or not o["datalist"] or o["datalist"] != o["datalistP"]:
        bad.append(("place suggestions", s0["datalist"], o["datalist"]))
    if s0["hs"] or s1["hs"]:
        bad.append("horizontal scroll on a phone")
    if c.real:
        p, a = o["paid"], o["paidAfter"]
        if "Aucune formation ne correspond" in p["status"] or "Aucune formation ne correspond" in p["items"] or not p["only"] \
                or "privés payants" not in p["items"] or a["only"] or not re.match(r"\s*[1-9]", a["count"]):
            bad.append(("paid only", p["status"][:120], p["items"][:120], a))
    if fiche and fiche[1] not in o["fiche"]:
        bad.append(("formation page", fiche, o["fiche"][:160]))
    if group:
        for k in ("reo", "term"):
            t = o[k]
            if "Mes 3 formations (2 vœux sur Parcoursup)" not in t or "Mes 3 vœux" in t or "3 formations, soit 2 vœux sur Parcoursup" not in t:
                bad.append((f"Mes vœux {k}", re.findall(r"Mes \d[^\n]*", t)[:2]))
        if "3 formations, soit 2 vœux sur Parcoursup · 3 formations avec un accès estimé" not in o["reo"]:
            bad.append(("reading outside terminale", re.findall(r"\d formations?, soit[^\n]*", o["reo"])[:1]))
    pr = o["profil"] or {}
    if o["profilErr"] or pr.get("spe2") != "NSI" or pr.get("moyenne") != 14.5 or pr.get("academie") != (acad or "Lyon"):
        bad.append(("profile", o["profilErr"][:1], pr))
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    return not bad, (f"draws {s0['n']} / {s1['n']} (profile); long tasks {s0['sum']} ms (max {s0['max']}) / {s1['sum']} ms (max {s1['max']}) "
                     f"at CPU x4; fiche {fiche}; group {group}; problems {bad[:3]}")


# ------------------------------------------------------------------ CO8 wiring and docs
def docs_ok(c: Ctx, readme=None, claude=None, nightly=None, durations=None) -> list[str]:
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    nightly = c.nightly if nightly is None else nightly
    durations = c.durations if durations is None else durations
    bad = []
    if "## One count, one message, one name (audit PR 8" not in readme:
        bad.append("README section")
    if "**One count, one message, one name (audit PR 8" not in claude or "redteam_coherence.py" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_coherence.py").exists() or '"tests/test_coherence.py"' not in durations:
        bad.append("test file or its CI duration")
    if '"coherence": ("CO6",)' not in nightly:
        bad.append("nightly browser suite")
    return bad


@check("CO8 wiring and docs: README section, CLAUDE.md rule, test file and its duration, nightly browser suite")
def co8(c: Ctx):
    bad = docs_ok(c)
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ CO7 mutation test
JS_MUTANTS = [
    ("CO1", "the title from the list's length", "  return nVx === n ? `Mes ${fmt(n)} vœu${n > 1 ? \"x\" : \"\"}` : `Mes ${fmt(n)} formations",
     "  return true ? `Mes ${fmt(n)} vœu${n > 1 ? \"x\" : \"\"}` : `Mes ${fmt(n)} formations"),
    ("CO1", "the wording counts formations", "  return nVx === n ? `${fmt(n)} vœu${n > 1 ? \"x\" : \"\"}` : `${fmt(n)} formations, soit ${fmt(nVx)}",
     "  return nVx === n ? `${fmt(n)} vœu${n > 1 ? \"x\" : \"\"}` : `${fmt(n)} formations, soit ${fmt(n)}"),
    ("CO1", "the reorientation heading from the length", "  <div class=\"card\"><h2>${vxTitre(d.voeux)}</h2>\n    <div class=\"scroll\"><table class=\"stack\"><tr class=\"stack-head\"><th>Formation</th><th class=\"num\">Accès",
     "  <div class=\"card\"><h2>Mes ${fmt(d.voeux.length)} vœux</h2>\n    <div class=\"scroll\"><table class=\"stack\"><tr class=\"stack-head\"><th>Formation</th><th class=\"num\">Accès"),
    ("CO1", "the reading outside terminale in vœux", "${vxCompteTxt(d.voeux.length, vxCompte(d.voeux))} · ${fmt(nEst)}",
     "${fmt(d.voeux.length)} vœux · ${fmt(nEst)}"),
    ("CO1", "tiles always in vœux", "  const word = (n) => (unit === \"formation\" ? `formation${n > 1 ? \"s\" : \"\"}` : `vœu${n > 1 ? \"x\" : \"\"}`);",
     "  const word = (n) => `vœu${n > 1 ? \"x\" : \"\"}`;"),
    ("CO1", "the verifier card's own wording", "  const compte = vxCompteTxt(n, nVx);", "  const compte = `${fmt(n)} vœux`;"),
    ("CO2", "« aucune » beside the paid ones", "      !kept.length && paid ? `<p class=\"info cs-paid-only\">", "      false ? `<p class=\"info cs-paid-only\">"),
    ("CO2", "the empty list line unescaped", "${esc(empty || \"Aucune formation ne correspond à ces filtres dans cette partie de la carte.\")}",
     "${empty || \"Aucune formation ne correspond à ces filtres dans cette partie de la carte.\"}"),
    ("CO2", "the status button unbound", "    document.querySelectorAll(\"#cs-status [data-show-paid]\").forEach((b) => { b.onclick = showPaid; });\n", ""),
    ("CO3", "the parcours unescaped", "<span class=\"fhead-parcours\"> · ${esc(d.complement)}</span>", "<span class=\"fhead-parcours\"> · ${d.complement}</span>"),
    ("CO4", "the redraw inside the blur", "      if (document.activeElement === e.target) act();\n      else setTimeout(() => { if (form.isConnected) act(); }, 0);",
     "      act();"),
    ("CO4", "a gone form acted on", "      else setTimeout(() => { if (form.isConnected) act(); }, 0);", "      else setTimeout(() => { act(); }, 0);"),
    ("CO5", "the layer copied again", "  neutral.forEach((f) => { f.zone = ok ? (zones.get(f.cod_aff_form) || null) : null; f.large = false; });\n  return neutral;",
     "  return neutral.map((f) => ({ ...f, zone: ok ? (zones.get(f.cod_aff_form) || null) : null, large: false }));"),
    ("CO5", "large kept from a profile", "f.zone = ok ? (zones.get(f.cod_aff_form) || null) : null; f.large = false; });",
     "f.zone = ok ? (zones.get(f.cod_aff_form) || null) : null; });"),
    ("CO5", "details in one task", "api(\"/api/carte/couche?partie=details\").then((D) => coucheDetailsParts(C, D))",
     "api(\"/api/carte/couche?partie=details\").then((D) => coucheDetails(C, coucheDecode(D)))"),
    ("CO5", "a slice lost", "    for (const r of P.rows.slice(i, i + CARTE_SLICE)) {", "    for (const r of P.rows.slice(i + 1, i + CARTE_SLICE)) {"),
    ("CO5", "setHtml writes always", "  if (!el || el.__html === html) return;", "  if (!el) return;"),
    ("CO5", "the suggestions with the page", "      <datalist id=\"cs-lieux\"></datalist>",
     "      <datalist id=\"cs-lieux\">${[...lieux.keys()].map((l) => `<option value=\"${esc(l)}\">`).join(\"\")}</datalist>"),
    ("CO5", "the details redraw everything", "    // the drawn rows ARE the layer's rows (carteMerge writes on them): coucheDetails filled them, only the cards change\n    drawCards();",
     "    // the drawn rows ARE the layer's rows (carteMerge writes on them): coucheDetails filled them, only the cards change\n    draw(false);"),
    ("CO5", "zones read after the first draw", "  const early = ok && zonesEarly !== undefined;", "  const early = false;"),
]
PY_MUTANTS = [
    ("planb", "CO3", "a part the title prints repeated", "parts = [p for p in full.split(\" · \") if p.strip() and not any(fold(p) in s for s in seen)]",
     "parts = [p for p in full.split(\" · \") if p.strip()]"),
    ("planb", "CO3", "the h1 not read", "seen = (fold(rec.get(\"lib_for_voe_ins\") or \"\"), fold(rec.get(\"g_ea_lib_vx\") or \"\"))",
     "seen = (fold(rec.get(\"lib_for_voe_ins\") or \"\"),)"),
    ("planb", "CO3", "the parcours dropped", "    if detail and (not out or fold(detail) not in fold(out)):", "    if False:"),
    ("planb", "CO3", "the page's rule apart from Mes vœux", "    full = complement_of(rec)", "    full = clean_complement(rec)"),
    ("api", "CO1", "the reorientation list without its groups", "    voeux = _with_groups([{\"cod_aff_form\": c, \"status\": \"ok\"",
     "    voeux = ([{\"cod_aff_form\": c, \"status\": \"ok\""),
    ("api", "CO3", "the page served the full complement", "            \"complement\": PB.complement_fiche(rec),", "            \"complement\": PB.complement_of(rec),"),
]


@check("CO7 mutation test: count, search message, one name, profile and speed bugs are each caught")
def co7(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name[:3] in ("CO1", "CO2", "CO3", "CO4", "CO5", "CO8") and not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught = [], 0
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    for target, name, old, new in JS_MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor found {c.js.count(old)} times)")
            continue
        m = copy.copy(c)
        m.js = c.js.replace(old, new, 1)
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001  a crash is a catch
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    for kind, target, name, old, new in PY_MUTANTS:
        src = c.src[kind]
        if src.count(old) != 1:
            missed.append(f"{name} (anchor found {src.count(old)} times)")
            continue
        m = copy.copy(c)
        m.src = dict(c.src, **{kind: src.replace(old, new, 1)})
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        caught += not ok
        if ok:
            missed.append(name)
    for name, kw in (("README section", {"readme": ""}), ("CLAUDE.md rule", {"claude": ""}), ("nightly entry", {"nightly": ""}),
                     ("CI duration", {"durations": "{}"})):
        caught += bool(docs_ok(c, **kw))
        if not docs_ok(c, **kw):
            missed.append(name)
    total = len(JS_MUTANTS) + len(PY_MUTANTS) + 4
    return not missed, f"{caught}/{total} caught; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail, "s": round(time.time() - t0, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--checks", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real, set(a.checks.split(",")) - {""} or None)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + f" ({r['s']} s)\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
