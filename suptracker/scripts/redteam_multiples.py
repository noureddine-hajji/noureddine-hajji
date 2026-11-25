"""Red team of the vœux multiples (audit PR 7, owner 2026-11-25): multiples.py, the fiche reader's heading (fiche_parse version 5),
the Mes vœux card « Avant de confirmer sur Parcoursup » and the formation page's note.

    python scripts/redteam_multiples.py [--db data/suptracker.duckdb] [--real]

  VM1 reader: on every saved fiche (masked samples, archived fiches), the vœu multiple = an independent BeautifulSoup reading of
      the heading: its first line when that line does not end with the department of an establishment, verbatim with the
      formation line; crafted headings (hostile, one line, an establishment with its town) give None.
  VM2 groups: core.voeu_multiple re-derived independently on crafted rows: same campaign AND same name AND same formation line,
      at least two formations; a name printed on one fiche alone, another campaign or another formation line is another group.
  VM3 count: multiples.compte and its page twin vxCompte = an independent count (each group once) on 300 random lists.
  VM4 card (Node): « N formations, soit M vœux », one line per group naming its formations, the group name escaped, a formation
      alone in its group said so, the concours hedge never repeated for a grouped formation, no « liste valide », vouvoiement.
  VM5 page: the note on the formation page (escaped, absent without a group), the API keys, the counter of the guide in
      formations, the list route unchanged (codes only, no-store).
  VM6 real data (--real, a warehouse built with reader version 5): every stored group re-derived from data/fiches/identite.csv,
      at least two formations each; the IFSI coverage measured and printed.
  VM7 plumbing: build order, reader version, harvest columns, README, CLAUDE.md, durations.json, the test file.
  VM8 mutation test of VM1-VM7 (mutants built in memory).
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
BAN = re.compile(r"(?i)liste (?:est )?valide|vos chances|probabilit|garanti|vous serez admis")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(name: str, src: str, pkg: bool = True):
    import suptracker  # noqa: F401
    m = types.ModuleType(f"suptracker.{name}_rt" if pkg else f"{name}_rt")
    m.__package__ = "suptracker" if pkg else ""
    m.__file__ = str(ROOT / ("suptracker" if pkg else "scripts") / f"{name}.py")
    exec(compile(src, m.__file__, "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real and self.db is not None
        self.src = {k: (ROOT / "suptracker" / f"{k}.py").read_text() for k in ("multiples", "liste", "api", "build", "reconnaissance")}
        self.src["fiche_parse"] = (ROOT / "scripts" / "fiche_parse.py").read_text()
        self.src["fiches_grilles"] = (ROOT / "scripts" / "fiches_grilles.py").read_text()
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self, k):
        return load(k, self.src[k], pkg=k not in ("fiche_parse",))


def top(js: str, name: str) -> str:
    import redteam_liste as RL
    return RL.top(js, name)


# ------------------------------------------------------------------ VM1 reader
DEP = re.compile(r"\((?:[^()]*-\s*)?(?:\d{2,3}|2[AB])\s*\)\s*$")


def rt_heading(page: str):
    from bs4 import BeautifulSoup
    h = BeautifulSoup(page, "html.parser").find("h2", id="libelle-etab-ff")
    if h is None:
        return None
    lines, cur = [], []
    for el in h.children:
        if getattr(el, "name", None) == "br":
            lines.append("".join(cur))
            cur = []
        else:
            cur.append(el.get_text() if hasattr(el, "get_text") else str(el))
    lines.append("".join(cur))
    lines = [re.sub(r"\s+", " ", x.replace("\xa0", " ")).strip() for x in lines]
    lines = [x for x in lines if x]
    if len(lines) < 2:
        return None
    first, rest = lines[0], " ".join(lines[1:])
    if DEP.search(first):
        return None
    return {"nom": first, "formation": rest}


CRAFTED = [
    ('<h2 id="libelle-etab-ff" class="x">\n Regroupement IFSI Université de Lille<br>D.E Infirmier\n</h2>',
     {"nom": "Regroupement IFSI Université de Lille", "formation": "D.E Infirmier"}),
    ('<h2 id="libelle-etab-ff">Lycée Descartes (Tours - 37)<br><span class="fr-h4">CPGE - BCPST</span></h2>', None),
    ('<h2 id="libelle-etab-ff">Université de Brest (EPE) (29)<br>Licence</h2>', None),
    ('<h2 id="libelle-etab-ff">Lycée A (Ajaccio - 2A)<br>BTS</h2>', None),
    ('<h2 id="libelle-etab-ff">Concours ' + HOSTILE.replace("<", "&lt;").replace(">", "&gt;") + '<br>Formation</h2>',
     {"nom": "Concours " + HOSTILE, "formation": "Formation"}),
    ('<h2 id="libelle-etab-ff">Réseau ScPo – concours commun</h2>', None),
    ('<h2 id="libelle-etab">Réseau<br>X</h2>', None),
    ('<h2 id="libelle-etab-ff">Regroupement contact x.y@ifsi.fr<br>D.E Infirmier</h2>',
     {"nom": "Regroupement contact [adresse sur la fiche Parcoursup]", "formation": "D.E Infirmier"}),
]


def saved_pages() -> list[Path]:
    out = sorted((ROOT / "data" / "fiches" / "echantillon").glob("*.html"))
    out += sorted((ROOT / "data" / "rapports" / "probe" / "wayback_fiches").glob("*.html"))
    return out


@check("VM1 reader: the heading's vœu multiple = an independent BeautifulSoup reading on every saved fiche and crafted headings")
def vm1(c: Ctx):
    fp = c.mod("fiche_parse")
    bad, n, named = [], 0, 0
    for page, want in CRAFTED:
        mine = rt_heading(page)
        mine = mine and {k: fp.mask(v) for k, v in mine.items()}
        if fp.voeu_multiple(page) != want or mine != want:
            bad.append(f"crafted {page[:50]!r}: {fp.voeu_multiple(page)} / {rt_heading(page)} != {want}")
    for p in saved_pages():
        t = p.read_text(encoding="utf-8", errors="replace")
        got, want = fp.voeu_multiple(t), rt_heading(t)
        want = want and {k: fp.mask(v) for k, v in want.items()}
        n += 1
        named += got is not None
        if got != want:
            bad.append(f"{p.name}: {got} != {want}")
        if got is not None and fp.parse(t).get("voeu_multiple") != got:
            bad.append(f"{p.name}: parse() does not carry it")
    lille = ROOT / "data" / "fiches" / "echantillon" / "code_23130.html"
    if lille.exists() and (fp.voeu_multiple(lille.read_text(encoding="utf-8")) or {}).get("nom") != "Regroupement IFSI Université de Lille":
        bad.append("the Lille IFSI regroupement is not read")
    return not bad, f"{len(CRAFTED)} crafted, {n} saved fiches, {named} name a vœu multiple; {bad[:4]}"


# ------------------------------------------------------------------ VM2 groups
ROWS = [  # (code, session, nom, formation)
    ("1", 2026, "Regroupement IFSI Université de Lille", "D.E Infirmier"),
    ("2", 2026, "Regroupement IFSI Université de Lille", "D.E Infirmier"),
    ("3", 2026, "Regroupement IFSI Université de Lille", "D.E Infirmier"),
    ("4", 2026, "Concours Geipi Polytech", "Formation d'ingénieur Bac + 5 - Bac général"),
    ("5", 2026, "Concours Geipi Polytech", "Formation d'ingénieur Bac + 5 - Bac technologique"),
    ("6", 2026, "Concours Geipi Polytech", "Formation d'ingénieur Bac + 5 - Bac général"),
    ("7", 2026, "ASKORIA", "D.E Educateur Spécialisé"),                    # alone: no group
    ("8", 2025, "Regroupement IFSI Université de Lille", "D.E Infirmier"),  # another campaign, alone
    ("9", 2026, None, None),
    ("10", 2026, "Concours " + HOSTILE, "X"), ("11", 2026, "Concours " + HOSTILE, "X"),
    ("12", None, "Regroupement IFSI Université de Lille", "D.E Infirmier"),
]


def rt_groups(rows) -> dict:
    by: dict = {}
    for cod, s, nom, f in rows:
        if nom and f and s is not None:
            by.setdefault((s, nom, f), []).append(cod)
    return {cod: {"nom": k[1], "formation": k[2], "session": k[0], "n_formations": len(v)} for k, v in by.items() if len(v) >= 2 for cod in v}


def crafted_con(mu, rows=ROWS):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.fiche_identite (cod_aff_form VARCHAR, session INTEGER, etab_type VARCHAR, bourses BOOLEAN,
        labels_codes VARCHAR, labels_textes VARCHAR, categorie VARCHAR, source VARCHAR, voeu_multiple VARCHAR, voeu_multiple_formation VARCHAR)""")
    con.executemany("INSERT INTO core.fiche_identite VALUES (?, ?, NULL, NULL, NULL, NULL, 'aucun', 'label', ?, ?)", rows)
    mu.build(con)
    return con


@check("VM2 groups: same campaign, name and formation line, at least two formations, re-derived independently")
def vm2(c: Ctx):
    mu = c.mod("multiples")
    con = crafted_con(mu)
    codes = [r[0] for r in ROWS] + ["404"]
    got, want = mu.of_codes(con, codes), rt_groups(ROWS)
    bad = [] if got == want else [f"{got} != {want}"]
    if set(want) != {"1", "2", "3", "4", "6", "10", "11"}:
        bad.append(f"the oracle itself: {sorted(want)}")
    if mu.for_formation(con, "7") is not None or mu.for_formation(con, "1") != want["1"]:
        bad.append("for_formation")
    old = duckdb.connect()
    old.execute("CREATE SCHEMA core")
    old.execute("CREATE TABLE core.fiche_identite (cod_aff_form VARCHAR, session INTEGER)")
    if mu.build(old) != 0 or mu.of_codes(old, ["1"]) != {}:
        bad.append("a warehouse read by an older reader must give no group")
    if mu.of_codes(duckdb.connect(), ["1"]) != {}:
        bad.append("a warehouse without the table must give no group")
    return not bad, f"{len(want)} grouped codes; {bad[:3]}"


# ------------------------------------------------------------------ VM3 count
def rt_count(voeux) -> int:
    keys = [(v["voeu_multiple"]["session"], v["voeu_multiple"]["nom"], v["voeu_multiple"]["formation"]) if v.get("voeu_multiple") else None
            for v in voeux]
    return sum(1 for k in keys if k is None) + len({k for k in keys if k is not None})


def node(prog: str, data):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout)


def random_lists(n=300):
    rnd = random.Random(20261125)
    groups = [{"nom": "Regroupement IFSI " + x, "formation": "D.E Infirmier", "session": 2026, "n_formations": 5} for x in "ABC"]
    groups.append({"nom": "Regroupement IFSI A", "formation": "D.E Infirmier", "session": 2025, "n_formations": 3})
    groups.append({"nom": "Regroupement IFSI A", "formation": "Autre ligne", "session": 2026, "n_formations": 2})
    out = []
    for _ in range(n):
        k = rnd.randint(0, 10)
        out.append([{"cod_aff_form": str(i), "voeu_multiple": rnd.choice(groups + [None, None, None])} for i in range(k)])
    return out


@check("VM3 count: multiples.compte and the page twin vxCompte = an independent count on 300 random lists")
def vm3(c: Ctx):
    mu = c.mod("multiples")
    lists = random_lists()
    bad = [i for i, L in enumerate(lists) if mu.compte(L) != rt_count(L)]
    prog = "\n".join(top(c.js, n) for n in ("vmKey", "vxCompte")) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(P.map((L) => vxCompte(L))));"""
    js = node(prog, lists)
    if js is not None:
        bad += [f"js {i}" for i, (L, n) in enumerate(zip(lists, js)) if n != rt_count(L)]
    return not bad, f"{len(lists)} lists{'' if js is not None else ' (node absent: Python only)'}; {bad[:5]}"


# ------------------------------------------------------------------ VM4 card
def _cal():
    ev = [{"key": "fin_voeux", "debut": "2027-03-11", "verifie": True}, {"key": "confirmation", "debut": "2027-04-01", "verifie": True}]
    return {"campagne": 2027, "evenements": ev, "regles": {"voeux_max": 10, "apprentissage_max": 10, "sous_voeux": True, "apprentissage_apres": True}}


def card_renders(js: str, cases):
    import redteam_liste as RL
    names = RL.NAMES
    prog = """let STORE = {};
const store = { get: (k, d) => (k in STORE ? STORE[k] : d), set: (k, v) => { STORE[k] = v; } };
const localIso = () => "2027-02-01";
""" + "\n".join(top(js, n) for n in names) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(P.map(([ids, f, opts]) => verifierCard(ids, f, P.cal, opts))));"""
    prog = prog.replace("P.cal", json.dumps(_cal()))
    return node(prog, cases)


@check("VM4 card: « N formations, soit M vœux », one line per group, escaped, a lone sub-wish said, no concours hedge repeated")
def vm4(c: Ctx):
    lille = {"nom": "Regroupement IFSI Université de Lille", "formation": "D.E Infirmier", "session": 2026, "n_formations": 12}
    host = {"nom": "Réseau " + HOSTILE, "formation": "IEP", "session": 2026, "n_formations": 7}
    v = lambda cod, g=None, conc=None: {"cod_aff_form": cod, "connu": True, "dans_carte": True, "concours": conc,  # noqa: E731
                                         "apprentissage": False, "voeu_multiple": g}
    f1 = {"session": 2025, "carte_session": 2026, "voeux": [v("1", lille), v("2", lille), v("3", lille), v("4"), v("5", host, "Concours commun"),
                                                            v("6", None, "Concours SESAME"), v("8", host, "Concours commun")]}
    f2 = {"session": 2025, "carte_session": 2026, "voeux": [v("1", lille), v("4")]}
    f3 = {"session": 2025, "carte_session": 2026, "voeux": [v("4"), v("7")]}
    noms = {"1": "IFSI A", "2": "IFSI B", "3": "IFSI C", "4": "Lycée D", "5": "IEP E", "6": "École F", "7": "Lycée G", "8": "IEP H"}
    opts = {"noms": noms, "securite": "ok", "today": "2027-02-01"}
    r = card_renders(c.js, [[list("1234568"), f1, opts], [["1", "4"], f2, opts], [["4", "7"], f3, opts]])
    if r is None:
        return True, "node not installed"
    full, lone, plain_ = r
    txt = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")  # noqa: E731
    bad = []
    t = txt(full)
    if "Votre liste compte 7 formations, soit 4 vœux sur Parcoursup" not in t:
        bad.append("the count of vœux")
    lines = [txt(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", full, re.S)]
    g = [x for x in lines if "Regroupement IFSI Université de Lille" in x]
    if len(g) != 1 or not all(n in g[0] for n in ("IFSI A", "IFSI B", "IFSI C")) or "un seul vœu" not in g[0] or "Lycée D" in g[0]:
        bad.append(f"the group line {g}")
    if "<img" in full or "onerror=alert(1)>" in full:
        bad.append("a group name unescaped")
    if any("IEP E" in x and "concours commun. Sur Parcoursup, elle peut compter" in x for x in lines):
        bad.append("the concours hedge repeated for a formation the fiche groups")
    if not any("École F" in x and "concours" in x for x in lines):
        bad.append("a concours formation without a fiche group lost its line")
    if "compteraient avec elle pour un seul vœu" not in txt(lone) or "12 formations" not in txt(lone) or "soit" in txt(lone).split("Votre liste compte")[1][:40]:
        bad.append("a formation alone in its group")
    if "Votre liste compte 2 vœux." not in txt(plain_) or "vœu multiple" in txt(plain_) or "sous-vœux" not in txt(plain_):
        bad.append("a list without a group changed")
    for h in (full, lone, plain_):
        if BAN.search(txt(h)) or TU.search(txt(h)):
            bad.append("wording")
    return not bad, f"3 renders; {bad[:4]}"


# ------------------------------------------------------------------ VM5 page and API
@check("VM5 page: the formation page note (escaped, absent without a group), the API keys, the guide's counter in formations")
def vm5(c: Ctx):
    bad = []
    prog = "\n".join(top(c.js, n) for n in ("esc", "fmt", "vmKey", "vmNote")) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify([vmNote(P.g), vmNote(null), vmNote({ nom: 1 })]));"""
    r = node(prog, {"g": {"nom": "Regroupement " + HOSTILE, "formation": "D.E", "session": 2026, "n_formations": 4}})
    if r is not None:
        note, none, broken = r
        if "<img" in note or "4 formations" not in note or "un seul vœu" not in note or none != "" or broken != "":
            bad.append(f"note {note[:80]!r} / {none!r} / {broken!r}")
    if "</div>${vmNote(d.voeu_multiple)}\n  </div>" not in c.js:
        bad.append("the note is not on the formation page")
    if '"voeu_multiple": MU.for_formation(_con().cursor(), rec["cod_aff_form"]),' not in c.src["api"]:
        bad.append("/api/formation does not carry the group")
    if '"voeu_multiple": groupes.get(cod)' not in c.src["liste"] or '"n_voeux": MU.compte(out)' not in c.src["liste"]:
        bad.append("/api/liste/verifier does not carry the groups")
    if "dans votre liste (les sous-vœux d'un même vœu multiple comptent pour un seul vœu)" not in c.js:
        bad.append("the guide counts formations as vœux")
    return not bad, f"{bad}"


# ------------------------------------------------------------------ VM6 real data
@check("VM6 real data: every stored group re-derived from data/fiches/identite.csv, IFSI coverage measured")
def vm6(c: Ctx):
    if not c.real:
        return True, "not --real"
    con = duckdb.connect(str(c.db), read_only=True)
    has = con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'voeu_multiple'""").fetchone()[0]
    path = ROOT / "data" / "fiches" / "identite.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []
    if not has or not rows or "voeu_multiple" not in rows[0]:
        return True, "warehouse or fiches not read by reader version 5 yet (the harvest, then the data workflow)"
    want = rt_groups([(r["cod_aff_form"], int(r["session"]) if r["session"].isdigit() else None, r["voeu_multiple"] or None,
                       r["voeu_multiple_formation"] or None) for r in rows])
    got = {c_: {"nom": n, "formation": f, "session": s, "n_formations": k}
           for c_, n, f, s, k in con.execute("SELECT cod_aff_form, nom, formation, session, n_formations FROM core.voeu_multiple").fetchall()}
    bad = [] if got == want else [f"{len(set(got) ^ set(want))} codes differ, e.g. {sorted(set(got) ^ set(want))[:5]}"]
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    ifsi = [x for (x,) in con.execute("SELECT cod_aff_form FROM core.formation_year WHERE session = ? AND fili = 'IFSI'", [latest]).fetchall()]
    cov = sum(x in got for x in ifsi)
    groups = {(v["session"], v["nom"], v["formation"]) for v in got.values()}
    if ifsi and cov / len(ifsi) < 0.5:
        bad.append(f"only {cov} of {len(ifsi)} IFSI in a group: the heading rule may have stopped matching")
    return not bad, f"{len(got)} formations in {len(groups)} groups; IFSI {cov}/{len(ifsi)}; {bad[:3]}"


# ------------------------------------------------------------------ VM7 plumbing
@check("VM7 plumbing: build order, reader version 5, harvest columns, docs, durations, test file")
def vm7(c: Ctx):
    b = c.src["build"]
    bad = []
    i, j = b.find("reconnaissance.build(con)"), b.find("multiples.build(con)")
    if i < 0 or j < i:
        bad.append("multiples.build must run after reconnaissance.build")
    if not re.search(r"^VERSION = ([5-9]|\d\d)\b", c.src["fiche_parse"], re.M) or 'out["voeu_multiple"] = voeu_multiple(page)' not in c.src["fiche_parse"]:
        bad.append("reader version")
    if '"voeu_multiple", "voeu_multiple_formation"]' not in c.src["fiches_grilles"]:
        bad.append("harvest columns")
    if 'r.get("voeu_multiple") or None, r.get("voeu_multiple_formation") or None' not in c.src["reconnaissance"]:
        bad.append("fiche_identite columns")
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text()
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    for x, ok in (("README", "multiples.py" in readme and "vœu multiple" in readme), ("CLAUDE.md", "redteam_multiples.py" in claude),
                  ("durations", "tests/test_multiples.py" in dur), ("test", (ROOT / "tests" / "test_multiples.py").exists())):
        if not ok:
            bad.append(x)
    return not bad, f"{bad}"


MUTANTS = [
    ("fiche_parse", "department end not checked", "    if len(parts) != 2 or _DEP_END.search(parts[0]):", "    if len(parts) != 2:", "VM1"),
    ("fiche_parse", "unmasked name", '    return {"nom": mask(parts[0]), "formation": mask(parts[1])}', '    return {"nom": parts[0], "formation": mask(parts[1])}', "VM1"),
    ("fiche_parse", "parse does not carry it", '    out["voeu_multiple"] = voeu_multiple(page)', '    out["voeu_multiple"] = None', "VM1"),
    ("fiche_parse", "Corsica as a group", "(?:\\d{2,3}|2[AB])", "(?:\\d{2,3})", "VM1"),
    ("multiples", "a lone name is a group", "MIN_FORMATIONS = 2", "MIN_FORMATIONS = 1", "VM2"),
    ("multiples", "formation line ignored", "PARTITION BY session, nom, formation", "PARTITION BY session, nom", "VM2"),
    ("multiples", "campaign ignored", "PARTITION BY session, nom, formation", "PARTITION BY nom, formation", "VM2"),
    ("multiples", "count by name only", '        key = (g["session"], g["nom"], g["formation"]) if g else None', '        key = g["nom"] if g else None', "VM3"),
    ("multiples", "every formation counted", "        if key is None or key not in seen:", "        if True:", "VM3"),
    ("js", "twin by name only", 'const vmKey = (g) => (g && typeof g.nom === "string" && typeof g.formation === "string" ? `${g.session}|${g.nom}|${g.formation}` : null);',
     'const vmKey = (g) => (g && typeof g.nom === "string" && typeof g.formation === "string" ? g.nom : null);', "VM3"),
    ("js", "count of formations shown as vœux", '  const compte = nVx === n ?', '  const compte = true ?', "VM4"),
    ("js", "group name unescaped", "sous-vœux du même vœu multiple «&nbsp;${esc(x.g.nom)}&nbsp;»", "sous-vœux du même vœu multiple «&nbsp;${x.g.nom}&nbsp;»", "VM4"),
    ("js", "concours hedge repeated", ' && v.concours && vmKey(v.voeu_multiple) === null);', " && v.concours);", "VM4"),
    ("js", "group line dropped", "  for (const x of vms) {\n    items.push(", "  for (const x of []) {\n    items.push(", "VM4"),
    ("js", "note unescaped", "vœu multiple «&nbsp;${esc(g.nom)}&nbsp;» (${fmt(g.n_formations)} formations, nom écrit sur sa fiche)",
     "vœu multiple «&nbsp;${g.nom}&nbsp;» (${fmt(g.n_formations)} formations, nom écrit sur sa fiche)", "VM5"),
    ("js", "note not on the page", "</div>${vmNote(d.voeu_multiple)}\n  </div>", "</div>\n  </div>", "VM5"),
    ("liste", "groups not sent", '                    "voeu_multiple": groupes.get(cod)})', '                    "voeu_multiple": None})', "VM5"),
    ("build", "groups never built", "        multiples.build(con)  ", "        pass  ", "VM7"),
]


@check("VM8 mutation test: every seeded reader, group, count, card and page bug is caught")
def vm8(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught = [], 0
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(c)
        src = c.js if kind == "js" else c.src[kind]
        if src.count(old) != 1:
            missed.append(f"{name} (anchor found {src.count(old)} times)")
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
