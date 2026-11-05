"""Red team of the jobs card (Onisep Idéo: the jobs a diploma leads to, national, by diploma).

    python scripts/redteam_onisep.py [--db data/suptracker.duckdb] [--real]

The XML files are re-read independently, the link of every formation of the latest campaign is
re-derived with the red team's own normalisation and rules, a truth table of real titles is checked,
the access flag (accessible with this diploma or after further studies) is re-derived, the page is
checked, and a mutation test seeds bugs (a BTS linked to a BUT sheet, options or parcours ignored,
the access flag inverted, a wrong diploma level, an unparsed 'bac' level, UI escaping and wording...)
that must each be caught.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import onisep as ON  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
REF_LEVEL = {"BTS": 2, "BUT": 3, "Licence": 3, "Licence_Las": 3, "IFSI": 3, "EFTS": 3}
# real titles -> the Onisep diploma a careful reader expects (checked when present)
TRUTH = {
    ("BTS", "Management Commercial Opérationnel"): "BTS management commercial opérationnel",
    ("BTS", "Commerce International"): "BTS commerce international",
    ("IFSI", "D.E Infirmier"): "diplôme d'État d'infirmier",
    ("EFTS", "D.E Educateur Spécialisé"): "diplôme d'État d'éducateur spécialisé",
    ("EFTS", "D.E Assistant de Service Social"): "diplôme d'État d'assistant de service social",
    ("Licence", "Droit"): "licence mention droit",
}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def rfold(s):
    s = unicodedata.normalize("NFKD", (s or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", s))


def rkey(s):
    """The red team's own normalisation (same contract as the module, written apart)."""
    words = rfold(s).replace("1ere annee commune", " ").replace("specialite", " ").split()
    words = ["option" if w == "opt" else w for w in words]
    small = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "a", "au", "aux", "pour", "sur"}
    return " ".join(w[:-1] if len(w) > 3 and w[-1] == "s" else w for w in words if w not in small)


def rrank(label):
    t = rfold(label)
    if re.fullmatch(r"bac \d+( et plus)?", t):
        return int(t.split()[1])
    if t.startswith("bac ou") or t == "bac":
        return 0
    if t.startswith("cap") or t.startswith("bep"):
        return -1
    if t in ("3e", "sans diplome", "diplome national du brevet"):
        return -2
    return None


def rxml(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".xml")][0]))


class Ctx:
    def __init__(self, db: Path, real: bool, sources: dict | None = None):
        self.db, self.real = db, real
        self.sources = ON.find_sources() if sources is None else sources
        con = duckdb.connect(str(db), read_only=True)
        self.forms = {r[0]: r[1:] for r in con.execute("SELECT * FROM core.onisep_formation").fetchall()}
        self.fm = set(con.execute("SELECT for_id, met_id FROM core.onisep_formation_metier").fetchall())
        self.mets = {r[0]: r[1:] for r in con.execute("SELECT * FROM core.onisep_metier").fetchall()}
        self.links = {}
        for cod, fili, prog, fid, rule in con.execute("SELECT cod_aff_form, fili, programme, for_id, regle FROM core.onisep_link").fetchall():
            self.links.setdefault(cod, [fili, prog, set(), rule])[2].update({fid} if fid else set())
        latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.latest_forms = con.execute("SELECT cod_aff_form, fili, fil_lib_voe_acc FROM core.formation_year WHERE session = ?", [latest]).fetchall()
        con.close()
        self.ref = self._ref_tables()

    def _ref_tables(self):
        fr = rxml(self.sources["formations"])
        forms = {f.findtext("identifiant"): (f.findtext("libelle_complet"), f.findtext("type_Formation/type_formation_libelle"),
                                             f.findtext("niveau_etudes/libelle")) for f in fr}
        fm = {(f.findtext("identifiant"), m.findtext("id")) for f in fr for m in f.findall("metiers_formation/metier")}
        mets = {}
        if "metiers" in self.sources:
            for m in rxml(self.sources["metiers"]):
                mets[m.findtext("identifiant")] = (m.findtext("nom_metier"), m.findtext("niveau_acces_min/libelle"))
        return {"forms": forms, "fm": fm, "mets": mets}

    def ref_index(self):
        idx = {"BTS": {}, "BUT": {}, "LIC": {}, "DE": {}}
        for fid, (lib, typ, _lvl) in self.ref["forms"].items():
            f, t = rfold(lib), typ or ""
            if t.startswith("brevet de technicien sup"):
                fam, spec = "BTS", re.sub(r"^btsa? ", "", f)
            elif t == "bachelor universitaire de technologie":
                fam, spec = "BUT", re.sub(r" parcours .*$", "", re.sub(r"^but ", "", f))
            elif t == "licence":
                fam, spec = "LIC", re.sub(r"^licence (mention )?", "", f)
            elif f.startswith("diplome d etat d"):
                fam, spec = "DE", f
            else:
                continue
            idx[fam].setdefault(rkey(spec), set()).add(fid)
        return idx

    def ref_links(self, rows=None):
        idx = self.ref_index()
        out = {}
        for cod, fili, prog in self.latest_forms if rows is None else rows:
            fids = set()
            if fili == "BTS":
                k = rkey(prog)
                fids = idx["BTS"].get(k) or {f for kk, v in idx["BTS"].items() if kk.startswith(k + " option") for f in v} \
                    or (idx["BTS"].get(k.split(" option")[0], set()) if " option" in k else set())
            elif fili == "BUT":
                fids = idx["BUT"].get(rkey(re.sub(r"(?i) parcours .*$", "", prog or "")), set())
            elif fili in ("Licence", "Licence_Las"):
                fids = idx["LIC"].get(rkey(prog), set())
            elif fili == "IFSI":
                fids = idx["DE"].get(rkey("diplome d etat d infirmier"), set())
            elif fili == "EFTS":
                fids = idx["DE"].get(rkey("diplome d etat d " + re.sub(r"^d e ", "", rfold(prog))), set())
            out[cod] = (fili, set(fids))
        return out


# ---------------------------------------------------------------- checks
@check("O1 the XML sheets are re-read independently: diplomas, diploma -> job links and jobs stored as published")
def o1(c: Ctx):
    bad = []
    if set(c.forms) != set(c.ref["forms"]):
        bad.append(("formations", len(c.forms), len(c.ref["forms"])))
    if any(c.forms[f][0] != c.ref["forms"][f][0] or c.forms[f][1] != c.ref["forms"][f][1] for f in set(c.forms) & set(c.ref["forms"])):
        bad.append("formation labels")
    if c.fm != c.ref["fm"]:
        bad.append(("links", len(c.fm), len(c.ref["fm"])))
    if set(c.mets) != set(c.ref["mets"]) or any(c.mets[m][0] != c.ref["mets"][m][0] or c.mets[m][1] != c.ref["mets"][m][1] for m in c.mets):
        bad.append("jobs")
    ranks = [m for m, v in c.mets.items() if v[2] != rrank(v[1])]
    return not bad and not ranks and len(c.forms) > 0, f"{len(c.forms)} diplomas, {len(c.fm)} links, {len(c.mets)} jobs; {bad[:3]}; level ranks wrong {ranks[:3]}"


@check("O2 link: every formation of the latest campaign re-derived (same family, title, options, parcours, state diplomas), truth table")
def o2(c: Ctx):
    want = c.ref_links()
    got = {cod: v[2] for cod, v in c.links.items()}
    bad = [(cod, sorted(got.get(cod, set()))[:2], sorted(w[1])[:2]) for cod, w in want.items() if got.get(cod, set()) != w[1]]
    fam = {"BTS": ("brevet de technicien sup",), "BUT": ("bachelor universitaire",), "Licence": ("licence",), "Licence_Las": ("licence",)}
    cross = [(cod, f) for cod, v in c.links.items() for f in v[2] if v[0] in fam and not (c.ref["forms"][f][1] or "").startswith(fam[v[0]])]
    truth = []
    titles = {(v[0], v[1]): v[2] for v in c.links.values()}
    for (fili, prog), lib in TRUTH.items():
        if (fili, prog) in titles and lib not in {c.ref["forms"][f][0] for f in titles[(fili, prog)]}:
            truth.append((fili, prog))
    cov = {}
    for fili in ("BTS", "BUT", "IFSI", "EFTS", "Licence"):
        xs = [v for v in want.values() if v[0] == fili]
        cov[fili] = round(sum(1 for v in xs if v[1]) / len(xs), 3) if xs else None
    floors = {"BTS": 0.85, "BUT": 0.95, "IFSI": 1.0, "EFTS": 1.0, "Licence": 0.80}
    low = [f for f, x in cov.items() if c.real and x is not None and x < floors[f]]
    return not bad and not cross and not truth and not low, f"{len(want)} formations, {len(bad)} differ {bad[:2]}; cross-family {cross[:2]}; truth {truth}; coverage {cov}"


@check("O3 API: the jobs are the union of the matched sheets' jobs, the access flag compares the job's minimum level with the diploma's")
def o3(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    bad, n = [], 0
    by = Counter()
    def ref_level(fili, fids):
        """The diploma level read from the raw sheets (lowest when several differ), the filière's usual one otherwise."""
        ranks = [r for r in (rrank(c.ref["forms"][f][2]) for f in fids if f in c.ref["forms"]) if r is not None and r >= 0]
        return min(ranks) if ranks else REF_LEVEL.get(fili)
    # every formation whose sheet departs from its filière's usual level is checked (3-year BTS: sprint 12 finding)
    odd = {cod for cod, (fili, _, fids, _) in c.links.items() if fids and ref_level(fili, fids) != REF_LEVEL.get(fili)}
    for cod, (fili, prog, fids, rule) in c.links.items():
        if by[rule] >= 30 and cod not in odd:
            continue
        by[rule] += 1
        b = ON.for_formation(con, cod)
        n += 1
        if not fids:
            if (b is None) != (rule == "filiere_sans_fiche") or (b and b["status"] != "sans_fiche"):
                bad.append((cod, "status"))
            continue
        want = {m for f, m in c.ref["fm"] if f in fids}
        got = {j["id"] for j in b["metiers"]}
        if want != got:
            bad.append((cod, "jobs"))
        lvl = ref_level(fili, fids)
        if b["niveau"] != lvl:
            bad.append((cod, "level", b["niveau"], lvl))
        for j in b["metiers"]:
            r = rrank(c.ref["mets"].get(j["id"], (None, None))[1])
            exp = None if r is None or lvl is None else "direct" if r <= lvl else "poursuite"
            if j["acces"] != exp:
                bad.append((cod, j["id"], j["acces"], exp))
        if {d["id"] for d in b["diplomes"]} != fids:
            bad.append((cod, "diplomas"))
    con.close()
    # witness cases, true on any data: a 3-year BTS sheet is bac+3; a sheet stating no level falls back on the filière
    if ON.sheet_level(["bac + 3"], "BTS") != 3 or ON.sheet_level([None], "BTS") != 2 or ON.sheet_level(["bac + 2", "bac + 3"], "BTS") != 2:
        bad.append(("witness", "sheet level"))
    return not bad and n > 0, f"{n} pages ({len(odd)} with a sheet level unusual for the filière), {len(bad)} wrong {bad[:3]}"


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 8 follow-up: the jobs a diploma leads to")
    blk = js[i: js.index("// ---- Sprint 8 follow-up: does the job match", i)]
    code = re.sub(r"(?m)^\s*//.*$", "", blk)
    safe = ("esc(", "tip(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", code)
           if re.search(r"\.(?:nom|libelle|url|niveau_acces_min)\b", m) and not m.lstrip().startswith(safe)]
    blank = re.findall(r'target="_blank"(?! rel="noopener")', code)
    words = all(w in code for w in ("Liste nationale du diplôme, pas propre à cet établissement", "pas une promesse d'emploi",
                                    "licence ODbL", "après une poursuite d'études", "accessible avec ce diplôme"))
    wired = "${metiersCard(d.metiers)}" in js
    ok = not raw and not blank and words and wired
    return ok, f"unescaped {raw[:3]}; links without noopener {len(blank)}; wording {words}; wired {wired}"


@check("O4 page: Onisep strings and links escaped, external links noopener, national-list and no-promise caveats, ODbL credit")
def o4(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped job name", '${esc(j.nom)}</a>', '${j.nom}</a>'),
    ("unescaped diploma URL", 'href="${esc(d.url)}"', 'href="${d.url}"'),
    ("external link without noopener", '<a href="${esc(j.url)}" target="_blank" rel="noopener">', '<a href="${esc(j.url)}" target="_blank">'),
    ("national-list caveat dropped", "Liste nationale du diplôme, pas propre à cet établissement. ", ""),
    ("ODbL credit dropped", "Source : Onisep, Idéo (licence ODbL).", "Source : Onisep."),
    ("card not wired", "${metiersCard(d.metiers)}", ""),
]


@check("O5 mutation test: cross-family link, options or parcours ignored, access flag inverted, wrong level, unparsed 'bac', UI bugs")
def o5(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    work = duckdb.connect(str(c.db), read_only=True)
    forms, links = ON.read_formations(Path(c.sources["formations"]))
    # edge rows injected so that every link mutant has something to bite on any data: a BTS without a sheet whose
    # first word is a BUT's, a BTS with an abbreviated option, a BUT with a parcours, a licence named like a licence pro
    edge = [("RT-1", "BTS", "Gestion forestière de démonstration"), ("RT-2", "BTS", "Systèmes numériques opt A"),
            ("RT-3", "BUT", "Gestion des entreprises et des administrations parcours démonstration"), ("RT-4", "Licence", "Droit"),
            ("RT-5", "Licence", "Agencement")]
    rows = c.latest_forms + edge
    want = {cod: w[1] for cod, w in c.ref_links(rows).items()}
    saved = {k: getattr(ON, k) for k in ("match", "index", "level_rank", "LEVEL", "key", "sheet_level")}

    def links_now():
        idx = ON.index(forms)
        out = {}
        for cod, fili, prog in rows:
            out[cod] = set(ON.match(idx, fili, prog)[0])
        return out

    def cross_family(idx, fili, prog):
        fids, rule = saved["match"](idx, fili, prog)
        if fili == "BTS" and not fids:                     # a BTS without a sheet borrows a BUT / licence sheet of the same field
            w = ON.key(prog).split()[:1]
            fids = [f for fam in ("BUT", "LIC") for kk, v in idx[fam].items() if kk.split()[:1] == w for f in v][:1]
        return fids, rule

    def with_lpro(forms_):                                  # a licence professionnelle taken for the licence of the same field
        idx = saved["index"](forms_)
        for fid, lib, typ, _, _ in forms_:
            if (typ or "").startswith("licence pro"):
                k = ON.key(re.sub(r"^licence pro(fessionnelle)? (mention )?", "", ON.fold(lib)))
                idx["LIC"][k] = idx["LIC"].get(k, []) + [fid]
        return idx

    def no_options(idx, fili, prog):
        fids, rule = saved["match"](idx, fili, prog)
        return ([], rule) if rule == "bts_options" else (fids, rule)

    def keep_parcours(forms_):
        idx = saved["index"](forms_)
        idx["BUT"] = {}
        for fid, lib, typ, _, _ in forms_:
            if typ == ON.BUT_TYPE:
                idx["BUT"].setdefault(ON.key(re.sub(r"^but\s+", "", ON.fold(lib))), []).append(fid)
        return idx

    link_mutants = [("BTS linked to a BUT or licence sheet", lambda: setattr(ON, "match", cross_family)),
                    ("licence professionnelle linked to a licence", lambda: setattr(ON, "index", with_lpro)),
                    ("BTS options ignored", lambda: setattr(ON, "match", no_options)),
                    ("BUT parcours kept in the key", lambda: setattr(ON, "index", keep_parcours))]
    for name, apply in link_mutants:
        try:
            apply()
            caught = links_now() != want
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)

    sample = [cod for cod, v in c.links.items() if v[2]][:: max(1, len(c.links) // 400)]

    def flags():
        out = {}
        for cod in sample:
            b = ON.for_formation(work, cod)
            out[cod] = tuple(sorted((j["id"], j["acces"]) for j in b["metiers"])) if b and b["status"] == "ok" else None
        return out
    base = flags()
    serve_mutants = [("sheet level ignored (filière's usual level)", lambda: setattr(ON, "sheet_level", lambda lv, fili=None: saved["LEVEL"].get(fili))),
                     ("'bac ou équivalent' left unparsed", lambda: setattr(ON, "level_rank", lambda l: None if rfold(l).startswith("bac ou") else saved["level_rank"](l)))]
    for name, apply in serve_mutants:
        try:
            apply()
            caught = flags() != base or name.startswith("'bac") or not o3(c)[0]   # a rank mutant acts at build time: O1's rule below
            if name.startswith("'bac"):
                caught = any(ON.level_rank(v[1]) != rrank(v[1]) for v in c.ref["mets"].values())
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(ON, k, v)
        if not caught:
            missed.append(name)
    # the access flag inverted: re-check O3's rule on a doctored answer
    b = next((ON.for_formation(work, cod) for cod in sample if ON.for_formation(work, cod)), None)
    if b and b["status"] == "ok" and b["metiers"]:
        j = b["metiers"][0]
        flipped = {"direct": "poursuite", "poursuite": "direct"}.get(j["acces"], "direct")
        r = rrank(c.ref["mets"].get(j["id"], (None, None))[1])
        lvl = b["niveau"]
        exp = None if r is None or lvl is None else "direct" if r <= lvl else "poursuite"
        if flipped == exp:
            missed.append("access flag inverted")
    work.close()
    n = len(UI_MUTANTS) + len(link_mutants) + len(serve_mutants) + 1
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, sources: dict | None = None) -> list[dict]:
    c = Ctx(db, real, sources)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
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
