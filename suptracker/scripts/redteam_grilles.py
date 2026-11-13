"""Red team, Parcoursup fiches (owner, 2026-11-13): the evaluation grids (weight of each field, criteria and their importance)
and the expected skills read on the LIVE fiches (scripts/fiche_parse.py, scripts/fiches_grilles.py, suptracker/grilles.py,
the jury tab's grilleCard).

  GR1 independent reading: BeautifulSoup re-reads the saved live pages (data/rapports/live/fiches_live/, 9 kinds of fiche)
      with its own rules; fields, weights, criteria, elements, importance, the session and both expectations texts equal
      fiche_parse's.
  GR2 ground truth and invariants: the owner's example (CPGE ECG, Lycée Kléber, 31389) reads 50/30/10/5/5 with 8+2+2+1+1
      criteria; every saved fiche: weights add up to 100, each caption's weight equals its field's, every importance label
      matches its "n sur 4", 4 or 5 fields among the five the fiches name, national expectations present.
  GR3 privacy: the e-mail addresses and phone numbers a page prints in its free texts are masked in everything read
      (pages and synthetic texts); the masking never touches a weight.
  GR4 hostile pages are rejected whole, with a reason: weights summing to 99, a total that is not 100, a caption weight that
      differs, an importance label against its score, a detailed table missing, a row without importance; a page without grid
      is "pas de grille" with its expectations still read; markup inside a criterion stays text (the page escapes it).
  GR5 harvest (fake Parcoursup): a closed site writes nothing; an open one writes every fiche; a second run reads nothing new;
      a reading older than REFRESH_DAYS is read again; a shared text is stored once; a missing fiche goes retry, then failed;
      a rejected fiche keeps its expectations and no grid.
  GR6 build round trip: harvest -> grilles.build -> grilles.for_formation gives back exactly what fiche_parse read; the build
      drops whole (never half) a formation whose stored weights do not add up, whose text id is missing, whose importance is
      out of 1-4 or whose criterion has no field. --real: every stored grid of data/fiches (and of the warehouse) adds up to 100.
  GR7 page (node): grilleCard escapes every stored string, shows each weight and each importance with its label and its dots
      (4 = Essentiel), says the campaign, "fait foi" and "pas des chances", no tutoiement, nothing without grid nor
      expectations; the jury tab puts it first and the summary link names it when there is no own report.
  GR8 plumbing: workflow modes "grilles" and "quotidien" (the schedule), data/fiches committed; the warehouse fingerprint
      takes the grids' content files, never etat.csv; .vercelignore; sources.py; the formation API; README, CLAUDE.md, durations.
  GR9 mutation test: mutants of the reader, the harvest, the build and the page, each caught.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
PAGES = ROOT / "data" / "rapports" / "live" / "fiches_live"
FICHES = ROOT / "data" / "fiches"
FIELDS = ("Résultats scolaires", "Méthodes de travail", "Savoir-être", "Motivation", "Engagement et activités")
LABELS = {"Complémentaire": 1, "Important": 2, "Très important": 3, "Essentiel": 4}
CHECKS = []


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str | None = None, package: str | None = None):
    """A module from its (possibly mutated) source, never cached in sys.modules."""
    m = types.ModuleType(name)
    m.__file__ = str(path)
    if package:
        m.__package__ = package
    exec(compile(src if src is not None else path.read_text(), str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, real: bool = False, db: Path | None = None):
        self.real, self.db = real, db
        self.src = {"fp": (ROOT / "scripts" / "fiche_parse.py").read_text(), "fg": (ROOT / "scripts" / "fiches_grilles.py").read_text(),
                    "gr": (ROOT / "suptracker" / "grilles.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.pages = {p.stem: p.read_text(encoding="utf-8") for p in sorted(PAGES.glob("*.html"))}

    def mod(self, k: str):
        if k == "fp":
            return load(ROOT / "scripts" / "fiche_parse.py", "fiche_parse_rt", self.src["fp"])
        if k == "fg":
            m = load(ROOT / "scripts" / "fiches_grilles.py", "fiches_grilles_rt", self.src["fg"])
            m.parse = self.mod("fp").parse                          # the harvest reads with the (possibly mutated) reader
            return m
        return load(ROOT / "suptracker" / "grilles.py", "suptracker.grilles_rt", self.src["gr"], package="suptracker")


# ---------------------------------------------------------------- independent reading (BeautifulSoup)
def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def bs_read(page: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    out = {"champs": [], "criteres": [], "nationaux": None, "complementaires": None, "session": None}
    m = re.search(r"analysent les candidatures en [^.]*?(20\d\d)", norm(soup.get_text(" ")))
    out["session"] = int(m.group(1)) if m else None
    for key, title in (("nationaux", "Les attendus nationaux"), ("complementaires", "Les attendus complémentaires")):
        h = next((x for x in soup.find_all(["h3", "h4"]) if norm(x.get_text()) == title), None)
        if h is None:
            continue
        for li in [li for sib in h.find_next_siblings() for li in (sib.find_all("li") if hasattr(sib, "find_all") else [])]:
            li.insert(0, "- ")                              # a list item reads "- item", as on the page's bullets
        parts = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) in ("h2", "h3", "h4", "button") or (getattr(sib, "name", None) == "div" and any(
                    c.startswith("fr-col") for c in (sib.get("class") or []))):
                break
            parts.append(sib.get_text(" ") if hasattr(sib, "get_text") else str(sib))
        out[key] = norm(" ".join(parts)) or None
    g = soup.find("table", id="table-analyse-cddt-onglet2")
    if g is None:
        return out
    for tr in g.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if th is None or td is None or norm(th.get_text()) == "Au total":
            continue
        out["champs"].append((norm(th.get_text()), int(re.sub(r"\D", "", td.get_text()))))
    for i, t in enumerate(soup.find_all("table", class_="table-forme-notation-cgev")):
        for tr in t.find("tbody").find_all("tr"):
            p = tr.find("p", class_="psup-rating-text")
            n = tr.find(attrs={"title": re.compile(r"^[1-4] sur 4$")})
            out["criteres"].append((i + 1, norm(tr.find("th").get_text()), norm(tr.find("td").get_text(" ")),
                                    norm(p.get_text()) if p else None, int(n["title"][0]) if n else None))
    return out


@check("GR1 independent reading: BeautifulSoup re-reads the saved fiches; fields, weights, criteria, importance, texts agree")
def gr1(c: Ctx):
    if len(c.pages) < 9:
        return False, f"{len(c.pages)} saved pages (9 expected in {PAGES.relative_to(ROOT)})"
    fp, bad = c.mod("fp"), []
    for cod, page in c.pages.items():
        a, b = fp.parse(page), bs_read(page)
        if [(x["champ"], x["poids"]) for x in a["champs"]] != b["champs"]:
            bad.append(f"{cod} fields {a['champs']} vs {b['champs']}")
        mine = [(k["champ_rang"], norm(k["critere"]), norm(k["elements"]), k["importance_label"], k["importance"]) for k in a["criteres"]]
        theirs = [(r, fp.mask(cr), fp.mask(el), lab, n) for r, cr, el, lab, n in b["criteres"]]
        theirs = [(r, norm(cr), norm(el), lab, n) for r, cr, el, lab, n in theirs]
        if mine != theirs:
            diff = next((x, y) for x, y in zip(mine + [None] * 99, theirs + [None] * 99) if x != y)
            bad.append(f"{cod} criteria differ: {diff}")
        for k in ("nationaux", "complementaires"):
            mine_t = norm((a[f"attendus_{k}"] or "").replace("\n", " ")) or None
            theirs_t = norm(fp.mask(b[k])) if b[k] else None
            if mine_t != theirs_t:
                bad.append(f"{cod} {k}: {str(mine_t)[:60]!r} vs {str(theirs_t)[:60]!r}")
        if a["session"] != b["session"]:
            bad.append(f"{cod} session {a['session']} vs {b['session']}")
    n = sum(len(bs_read(p)["criteres"]) for p in c.pages.values())
    return not bad, f"{len(c.pages)} fiches, {n} criteria read twice; {bad[:4]}"


@check("GR2 ground truth (Kléber ECG 50/30/10/5/5, 8+2+2+1+1) and invariants on every saved fiche")
def gr2(c: Ctx):
    fp, bad = c.mod("fp"), []
    k = fp.parse(c.pages.get("31389", ""))
    if [(x["champ"], x["poids"]) for x in k["champs"]] != [("Résultats scolaires", 50), ("Méthodes de travail", 30),
                                                           ("Savoir-être", 10), ("Motivation", 5), ("Engagement et activités", 5)]:
        bad.append(f"Kléber ECG weights {k['champs']}")
    if [sum(1 for x in k["criteres"] if x["champ_rang"] == i) for i in range(1, 6)] != [8, 2, 2, 1, 1]:
        bad.append("Kléber ECG criteria per field")
    if not k["criteres"] or k["criteres"][0]["importance_label"] != "Essentiel" or "mathématiques" not in k["criteres"][0]["critere"].lower():
        bad.append(f"Kléber ECG first criterion {k['criteres'][:1]}")
    for cod, page in c.pages.items():
        p = fp.parse(page)
        if not p["ok"]:
            bad.append(f"{cod} rejected: {p['reason']}")
            continue
        if sum(x["poids"] for x in p["champs"]) != 100 or not 4 <= len(p["champs"]) <= 5 or any(x["champ"] not in FIELDS for x in p["champs"]):
            bad.append(f"{cod} fields {[(x['champ'], x['poids']) for x in p['champs']]}")
        for x in p["champs"]:
            w = re.search(r"compte(?:nt)? pour (\d+)", x.get("intitule") or "")
            if not w or int(w.group(1)) != x["poids"]:
                bad.append(f"{cod} caption {x.get('intitule')!r} vs {x['poids']}")
        if any(LABELS.get(y["importance_label"]) != y["importance"] for y in p["criteres"]):
            bad.append(f"{cod} label/score")
        if {y["champ_rang"] for y in p["criteres"]} != set(range(1, len(p["champs"]) + 1)):
            bad.append(f"{cod} a field without criteria")
        if not p["attendus_nationaux"] or p["session"] != 2026:
            bad.append(f"{cod} expectations {bool(p['attendus_nationaux'])} session {p['session']}")
    return not bad, f"{len(c.pages)} fiches checked; {bad[:4]}"


@check("GR3 privacy: e-mail addresses and phone numbers masked in every text read; weights untouched")
def gr3(c: Ctx):
    fp, bad = c.mod("fp"), []
    em = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    ph = re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
    raw = 0
    for cod, page in c.pages.items():
        raw += len(em.findall(page))
        p = fp.parse(page)
        texts = [p["attendus_nationaux"], p["attendus_complementaires"], p["conseils"]] + \
            [x.get("intitule") for x in p["champs"]] + [y[k] for y in p["criteres"] for k in ("critere", "elements")]
        for t in filter(None, texts):
            if em.search(t) or ph.search(t):
                bad.append(f"{cod}: {t[:60]!r}")
    for s, want in (("Contact : jean.dupont@lycee-kleber.fr ou 03 88 12 34 56", 2), ("Tél. +33 3 88 12 34 56 / 0388123456", 2),
                    ("Écrire à a.b+c@ac-strasbourg.education.fr.", 1)):
        m = fp.mask(s)
        if em.search(m) or ph.search(m) or m.count("[") != want:
            bad.append(f"synthetic {s!r} -> {m!r}")
    if fp.mask("comptent pour 50 %, 2026, 14 critères, 1ère et Terminale") != "comptent pour 50 %, 2026, 14 critères, 1ère et Terminale":
        bad.append("masking touches figures")
    return not bad and raw > 0, f"{raw} addresses in the raw pages, none in what is read; {bad[:3]}"


def _mutate_page(page: str, old: str, new: str, count: int = 1) -> str | None:
    return page.replace(old, new, count) if old in page else None


@check("GR4 hostile pages rejected whole with a reason; no grid = 'pas de grille'; markup in a criterion stays text")
def gr4(c: Ctx):
    fp, bad = c.mod("fp"), []
    page = c.pages.get("31389", "")
    g = re.search(r'<table id="table-analyse-cddt-onglet2".*?</table>', page, re.S)
    gtab = g.group(0) if g else ""
    cases = {
        "weights 99": page.replace(gtab, gtab.replace(">5 %<", ">4 %<", 1)) if ">5 %<" in gtab else None,
        "total 90": page.replace(gtab, re.sub(r"(Au total.*?<td[^>]*>[^<]*?)100", r"\g<1>90", gtab, count=1, flags=re.S)),
        "caption weight differs": _mutate_page(page, "comptent pour 50%", "comptent pour 40%"),
        "label against score": re.sub(r'(<table class="table-forme-notation-cgev.*?title=")([1-4])( sur 4")',
                                      lambda m: m.group(1) + str(5 - int(m.group(2))) + m.group(3), page, count=1, flags=re.S),
        "a detailed table missing": (lambda ts: page[:ts[-1].start()] + page[ts[-1].end():] if ts else None)(
            list(re.finditer(r'<table class="table-forme-notation-cgev[^"]*">.*?</table>', page, re.S))),   # the last: the others align
        "weights 99, caption agreeing": (lambda p: p.replace("pour 5%", "pour 4%", 1) if p and "pour 5%" in p else None)(
            page.replace(gtab, gtab.replace(">5 %<", ">4 %<", 1)) if ">5 %<" in gtab else None),
        "a row without importance": _mutate_page(page, '<p class="psup-rating-text">', '<p class="psup-x">'),
    }
    for name, mp in cases.items():
        if mp is None or mp == page:
            bad.append(f"{name}: page not mutated (anchor gone)")
            continue
        p = fp.parse(mp)
        if p["ok"] or not p["reason"]:
            bad.append(f"{name}: accepted")
    nog = fp.parse(page.replace(gtab, "")) if gtab else {"reason": "?"}
    if nog.get("reason") != "pas de grille" or not nog.get("attendus_nationaux") or nog.get("champs"):
        bad.append(f"no grid: {nog.get('reason')}")
    th = re.search(r'(<table class="table-forme-notation-cgev.*?<tbody>.*?<th scope="row"[^>]*>)(.*?)(</th>)', page, re.S)
    if th:
        hostile = page[:th.start(2)] + "&lt;img src=x onerror=alert(1)&gt; Notes" + page[th.end(2):]
        p = fp.parse(hostile)
        if not p["ok"] or p["criteres"][0]["critere"] != "<img src=x onerror=alert(1)> Notes":
            bad.append(f"markup criterion: {p['criteres'][:1]}")
    for junk in ("", "<html></html>", "<table id=\"table-analyse-cddt-onglet2\"></table>"):
        if fp.parse(junk)["ok"]:
            bad.append(f"junk {junk!r} accepted")
    return not bad, f"{len(cases)} hostile pages, no grid, markup, junk; {bad[:4]}"


class _R:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


def _fake_harvest(c: Ctx, out: Path, pages: dict, closed: bool = False, now_shift_days: int = 0, fg=None):
    fg = fg or c.mod("fg")
    fg.codes = lambda db: sorted(pages, key=lambda x: (len(x), x))
    reads = []

    def fetch(http, cod, pause):
        reads.append(cod)
        if closed or pages.get(cod) is None:
            return None, _R(404, "")
        return f"https://dossier.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={cod}&typeBac=0&originePc=0", _R(200, pages[cod])
    fg.fetch_fiche = fetch
    if now_shift_days:
        real = fg.datetime

        class Shifted(real):
            @classmethod
            def now(cls, tz=None):
                return real.now(tz) + fg.timedelta(days=now_shift_days)
        fg.datetime = Shifted
    res = fg.harvest(None, "unused", out, 600, pause=0)
    return res, reads


def _texts(out: Path) -> list[dict]:
    p = out / "textes.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@check("GR5 harvest: closed site writes nothing; resumable; refresh after REFRESH_DAYS; texts once; retry then failed")
def gr5(c: Ctx):
    bad = []
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fiches"
        res, _r = _fake_harvest(c, out, c.pages, closed=True)
        if res.get("status") != "closed" or (out.exists() and any(out.iterdir())):
            bad.append(f"closed site: {res} {list(out.iterdir()) if out.exists() else ''}")
        pages = dict(c.pages)
        pages["999999"] = None                                  # a formation whose fiche is gone
        g = re.search(r'<table id="table-analyse-cddt-onglet2".*?</table>', pages["31389"], re.S)
        pages["31390"] = pages["31389"].replace(">5 %<", ">4 %<", 1) if g else None     # a rejected fiche (sums to 99)
        res, reads = _fake_harvest(c, out, pages)
        etat = {r["cod_aff_form"]: r for r in csv.DictReader(open(out / "etat.csv", encoding="utf-8"))}
        if res.get("status") != "open" or {r["status"] for k, r in etat.items() if k in c.pages} != {"ok"}:
            bad.append(f"open site: {res}")
        if etat.get("999999", {}).get("status") != "retry" or etat.get("31390", {}).get("status") != "rejetee":
            bad.append(f"missing/rejected: {etat.get('999999')} {etat.get('31390')}")
        champs = list(csv.DictReader(open(out / "champs.csv", encoding="utf-8")))
        if any(r["cod_aff_form"] == "31390" for r in champs) or not any(r["cod_aff_form"] == "31389" for r in champs):
            bad.append("a rejected fiche has a grid, or a good one none")
        att = {r["cod_aff_form"]: r for r in csv.DictReader(open(out / "attendus.csv", encoding="utf-8"))}
        if not att.get("31390", {}).get("nationaux_id"):
            bad.append("a rejected fiche lost its expectations")
        tx = _texts(out)
        ids = [r["id"] for r in tx]
        if len(ids) != len(set(ids)) or att["31389"]["nationaux_id"] != att["31390"]["nationaux_id"]:
            bad.append(f"texts stored {len(ids)} times for {len(set(ids))} ids")
        res2, reads2 = _fake_harvest(c, out, pages)
        etat2 = {r["cod_aff_form"]: r for r in csv.DictReader(open(out / "etat.csv", encoding="utf-8"))}
        probe = [x for x in reads2 if x in c.pages]          # the open-site probe reads at most 3 known fiches
        if [x for x in reads2 if x not in c.pages] != ["999999"] or len(probe) > 3 or etat2["999999"]["status"] != "failed":
            bad.append(f"second run read {reads2[:5]} (the probe and the retry expected), retry -> {etat2['999999']['status']}")
        if len(_texts(out)) != len(tx):
            bad.append("second run stored texts again")
        res3, reads3 = _fake_harvest(c, out, dict(pages, **{"31389": pages["31390"]}), now_shift_days=25)
        etat3 = {r["cod_aff_form"]: r for r in csv.DictReader(open(out / "etat.csv", encoding="utf-8"))}
        if etat3["31389"]["status"] != "rejetee" or any(r["cod_aff_form"] == "31389" for r in csv.DictReader(open(out / "champs.csv", encoding="utf-8"))) \
                or any(r["cod_aff_form"] == "31389" for r in csv.DictReader(open(out / "criteres.csv", encoding="utf-8"))):
            bad.append("a fiche rejected on refresh keeps its old grid")
        if sorted(reads3) != sorted(set(pages)) and not set(c.pages) <= set(reads3):
            bad.append(f"refresh after 25 days read {len(reads3)} fiches")
        if not (set(c.pages) <= set(reads3)):
            bad.append("an old reading is not read again")
    return not bad, f"closed, open, rerun, refresh; {bad[:4]}"


def _built(c: Ctx, out: Path, gr=None):
    import duckdb
    gr = gr or c.mod("gr")
    con = duckdb.connect()
    res = gr.build(con, textes=None, src=out)
    return gr, con, res


@check("GR6 build round trip harvest -> build -> API equals the reading; inconsistent stored grids dropped whole")
def gr6(c: Ctx):
    bad = []
    fp = c.mod("fp")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fiches"
        _fake_harvest(c, out, c.pages)
        gr, con, res = _built(c, out)
        for cod, page in c.pages.items():
            p, g = fp.parse(page), gr.for_formation(con, cod)
            if g is None:
                bad.append(f"{cod} not served")
                continue
            want = [(x["champ"], x["poids"], x["intitule"], [(y["critere"], y["elements"], y["importance"]) for y in p["criteres"] if y["champ_rang"] == x["rang"]])
                    for x in p["champs"]]
            got = [(x["champ"], x["poids"], x["intitule"], [(y["critere"], y["elements"], y["importance"]) for y in x["criteres"]]) for x in g["champs"]]
            if want != got or g["nationaux"] != p["attendus_nationaux"] or g["complementaires"] != p["attendus_complementaires"] \
                    or g["conseils"] != p["conseils"] or g["session"] != p["session"] or not g["grille"]:
                bad.append(f"{cod} differs after the round trip")
            if any(gr.IMPORTANCE[y["importance"]] != y["importance_label"] for x in g["champs"] for y in x["criteres"]):
                bad.append(f"{cod} label")
            if not (g["url"] or "").startswith("https://dossier.parcoursup.fr/") or not re.fullmatch(r"\d{4}-\d\d-\d\d", g["lu_le"] or ""):
                bad.append(f"{cod} url/date {g['url']} {g['lu_le']}")
        if gr.for_formation(con, "0") is not None:
            bad.append("an unknown code is served")
        con.close()

        def tamper(fname, fn):
            for fname, fn in ([(fname, fn)] if isinstance(fname, str) else zip(fname, fn)):
                src = out / fname
                rows = list(csv.DictReader(open(src, encoding="utf-8")))
                cols = list(rows[0].keys())
                rows = fn(rows)
                with open(src, "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                    w.writerows(rows)
        keep = {f: (out / f).read_bytes() for f in ("champs.csv", "criteres.csv", "attendus.csv", "etat.csv")}
        t1 = lambda rows: [dict(r, poids="49") if r["cod_aff_form"] == "31389" and r["rang"] == "1" else r for r in rows]  # noqa: E731
        t2 = lambda rows: [dict(r, critere_id="ffffffffffffffff") if r["cod_aff_form"] == "31389" and r["rang"] == "1" else r for r in rows]  # noqa: E731
        t3 = lambda rows: [dict(r, importance="5") if r["cod_aff_form"] == "31389" and r["rang"] == "1" else r for r in rows]  # noqa: E731
        t4 = lambda rows: [dict(r, champ_rang="9") if r["cod_aff_form"] == "31389" and r["rang"] == "1" and r["champ_rang"] == "1" else r for r in rows]  # noqa: E731
        t5 = lambda rows: [dict(r, rang="7") if r["cod_aff_form"] == "31389" and r["rang"] == "5" else r for r in rows]  # noqa: E731
        t5c = lambda rows: [dict(r, champ_rang="7") if r["cod_aff_form"] == "31389" and r["champ_rang"] == "5" else r for r in rows]  # noqa: E731
        for name, fname, fn in (("weights 99", "champs.csv", t1), ("missing text id", "criteres.csv", t2), ("importance 5", "criteres.csv", t3),
                                ("criterion without field", "criteres.csv", t4), ("field ranks with a gap", ("champs.csv", "criteres.csv"), (t5, t5c))):
            for f, b in keep.items():
                (out / f).write_bytes(b)
            tamper(fname, fn)
            gr2, con2, _ = _built(c, out)
            g = gr2.for_formation(con2, "31389")
            if g is not None and g.get("grille"):
                bad.append(f"{name}: still served")
            if gr2.for_formation(con2, "4100") is None:
                bad.append(f"{name}: another formation lost")
            con2.close()
    real = ""
    if c.real and (FICHES / "etat.csv").exists():
        gr = c.mod("gr")
        rows, _used, audit = gr.assemble(FICHES)
        off = [g["cod_aff_form"] for g in rows if g["grille"] and sum(x["poids"] for x in g["champs"]) != 100]
        bad += [f"real: {off[:5]}"] if off else []
        real = f"; real: {len(rows)} fiches, {sum(g['grille'] for g in rows)} grids, {sum(1 for a in audit if a[2].startswith('écartée'))} dropped"
        if c.db and Path(c.db).exists():
            import duckdb
            con = duckdb.connect(str(c.db), read_only=True)
            try:
                if gr.RP._has(con, "core", "fiche_champ"):
                    n = con.execute("""SELECT count(*) FROM (SELECT cod_aff_form FROM core.fiche_champ GROUP BY 1
                                       HAVING sum(poids) <> 100)""").fetchone()[0]
                    bad += [f"warehouse: {n} grids not adding up"] if n else []
            finally:
                con.close()
    return not bad, f"{len(c.pages)} round trips, 5 tampered stores{real}; {bad[:4]}"


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        return ""
    if js[m.start():].startswith("const "):
        end = js.index("\n", m.start())
        if js[m.start():end].rstrip().endswith("{"):
            end = js.index("\n};", m.start()) + 3
        return js[m.start(): end]
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


HOSTILE = "<img src=x onerror=alert(1)>"


@check("GR7 page: grilleCard escapes, shows every weight and importance (label + dots), campaign, fait foi, no chance, vouvoiement")
def gr7(c: Ctx):
    defs = "\n".join(top(c.js, n) for n in ("esc", "fmt", "rateBar", "GR_IMP", "ficheText", "grilleImp", "grilleCard"))
    g = {"session": 2026, "lu_le": "2026-11-13", "url": "https://dossier.parcoursup.fr/x?g_ta_cod=1", "grille": True,
         "nationaux": f"Savoir lire.\n- {HOSTILE}\n- Écrire", "complementaires": None, "conseils": HOSTILE,
         "champs": [{"rang": 1, "champ": "Résultats scolaires", "poids": 73, "intitule": "x", "criteres": [
             {"critere": HOSTILE, "elements": "Notes de " + HOSTILE, "importance": 4, "importance_label": "Essentiel"},
             {"critere": "Rang", "elements": None, "importance": 1, "importance_label": "Complémentaire"}]},
                    {"rang": 2, "champ": "Motivation", "poids": 27, "intitule": "y", "criteres": [
                        {"critere": "Projet", "elements": "Lettre", "importance": 3, "importance_label": "Très important"}]}]}
    empty = {"session": 2026, "grille": False, "nationaux": None, "complementaires": None, "champs": []}
    only = dict(empty, nationaux="Attendus " + HOSTILE)
    prog = defs + """
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(data.map((g) => grilleCard(g))));"""
    try:
        out = node(prog, [g, empty, only, None])
    except RuntimeError as e:
        return False, f"node: {e}"
    if out is None:
        return True, "node not installed"
    h, e, o, n = out
    bad = []
    if "<img" in h or "<img" in o or "&lt;img src=x onerror=alert(1)&gt;" not in h:
        bad.append("a stored string is not escaped")
    for w in ("73 %", "27 %", "Essentiel", "Complémentaire", "Très important", "campagne 2026", "fait foi", "pas des chances d'admission",
              "Les attendus nationaux", "13/11/2026", "https://dossier.parcoursup.fr/x?g_ta_cod=1"):
        if w not in h:
            bad.append(f"missing {w!r}")
    dots = re.findall(r'<span class="gr-dots" aria-hidden="true">(.*?)</span>', h)
    if [d.count('class="on"') for d in dots] != [4, 1, 3]:
        bad.append(f"dots {[d.count('class=\"on\"') for d in dots]}")
    if 'class="rp-imp imp0">Essentiel' not in h or 'class="rp-imp imp3">Complémentaire' not in h:
        bad.append("importance class")
    if "<li>" not in h:
        bad.append("expectations list not rendered as a list")
    if e != "" or n != "" or "Les attendus nationaux" not in o or "Vue d'ensemble" in o:
        bad.append(f"empty/only-expectations: {e[:40]!r} {o[:40]!r}")
    txt = re.sub(r"<[^>]+>", " ", h)
    if re.search(r"\b(tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"\bchances?\b", txt.replace("pas des chances", "")):
        bad.append("tutoiement or a chance")
    vf = top(c.js, "viewFormation")
    if "grilleCard(d.grille)" not in vf or "const juryHtml = grHtml + repHtml;" not in vf or 'kind: "grille"' not in vf:
        bad.append("the jury tab does not put the grid first")
    if 'd.jury_tab.kind === "grille" ? `Comment votre dossier sera examiné' not in top(c.js, "summaryBand"):
        bad.append("the summary link does not name the grid")
    return not bad, f"3 cards rendered; {bad[:4]}"


@check("GR8 plumbing: workflow modes, fingerprint, vercelignore, sources, API, README, CLAUDE.md, durations")
def gr8(c: Ctx):
    bad = []
    wf = (REPO / ".github" / "workflows" / "suptracker-rapports.yml").read_text()
    for w in ("steps.req.outputs.mode == 'grilles' || steps.req.outputs.mode == 'quotidien'", "python scripts/fiches_grilles.py data/suptracker.duckdb data/fiches",
              "\"quotidien\" if \"${{ github.event_name }}\" == \"schedule\"", "steps.req.outputs.mode == 'live' || steps.req.outputs.mode == 'quotidien'",
              "data/rapports/live data/fiches"):
        if w not in wf:
            bad.append(f"rapports workflow: {w[:50]}")
    dw = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    content = "data/fiches/champs.csv data/fiches/criteres.csv data/fiches/attendus.csv data/fiches/textes.csv.gz"
    if dw.count(content) != 3 or "data/fiches/etat.csv" in dw or re.search(r"data/fiches(?:/)?[ ;|]", dw):
        bad.append("data workflow fingerprint")
    if "**/data/fiches/" not in (ROOT / ".vercelignore").read_text().splitlines():
        bad.append(".vercelignore")
    from suptracker import sources
    s = next((x for x in sources.SOURCES if x["key"] == "fiches_parcoursup"), None)
    if not s or s["status"] != "en_ligne" or "grilles" not in s["feeds"]:
        bad.append("sources.py")
    api = (ROOT / "suptracker" / "api.py").read_text()
    if '"grille": GR.for_formation(_con().cursor(), rec["cod_aff_form"])' not in api:
        bad.append("api")
    if "grilles.build(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build")
    readme = (ROOT / "README.md").read_text()
    if "redteam_grilles.py" not in readme or "## The evaluation grids of the Parcoursup fiches" not in readme:
        bad.append("README")
    if "redteam_grilles.py" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    if "tests/test_grilles.py" not in dur and "test_grilles.py" not in dur:
        bad.append("durations")
    if "beautifulsoup4" not in (ROOT / "requirements-pipeline.txt").read_text():
        bad.append("requirements-pipeline (bs4)")
    return not bad, f"{bad}"


SOURCE_MUTANTS = [
    ("fp", "caption weight not checked", "if not w or int(w.group(1)) != out[\"champs\"][i][\"poids\"]:", "if not w:", "GR4"),
    ("fp", "sum not checked", 'if sum(x["poids"] for x in out["champs"]) != 100:', "if False:", "GR4"),
    ("fp", "total not checked", "or pct(total[0][1]) != 100:", "or pct(total[0][1]) is None:", "GR4"),
    ("fp", "label vs score not checked", "if IMPORTANCE.get(label) != int(sur.group(1)):", "if label not in IMPORTANCE:", "GR4"),
    ("fp", "table count not checked", "if len(tables) != len(champs):", "if not tables:", "GR4"),
    ("fp", "importance shifted", '"importance": int(sur.group(1)), "importance_label": label', '"importance": 5 - int(sur.group(1)), "importance_label": label', "GR1"),
    ("fp", "e-mails kept", "return PHONE.sub(MASK_PHONE, EMAIL.sub(MASK_EMAIL, s))", "return PHONE.sub(MASK_PHONE, s)", "GR3"),
    ("fp", "phones kept", "return PHONE.sub(MASK_PHONE, EMAIL.sub(MASK_EMAIL, s))", "return EMAIL.sub(MASK_EMAIL, s)", "GR3"),
    ("fp", "elements from the wrong cell", '"elements": mask(text(tds[0]))', '"elements": mask(text(tds[-1]))', "GR1"),
    ("fp", "complementary read as national", 'out["attendus_complementaires"] = mask(_section(page, "Les attendus complémentaires"))',
     'out["attendus_complementaires"] = mask(_section(page, "Les attendus nationaux"))', "GR1"),
    ("fp", "no session", "out[\"session\"] = int(s.group(1)) if s else None", "out[\"session\"] = None", "GR2"),
    ("fg", "closed site writes", "if probe and all(fetch_fiche(http, c, pause)[0] is None for c in probe):", "if False:", "GR5"),
    ("fg", "texts stored again", "if i and i not in ids:", "if i:", "GR5"),
    ("fg", "no refresh", 'and etat[c]["lu_le"] < old)', 'and False)', "GR5"),
    ("fg", "a rejected fiche keeps an old grid", "        champs.pop(c, None)\n        crits.pop(c, None)\n", "", "GR5"),
    ("fg", "retry forever", 'r["status"] = "retry" if r["status"] == "todo" else "failed"', 'r["status"] = "retry"', "GR5"),
    ("gr", "weights not checked again", "sum(poids) != 100 or", "False or", "GR6"),
    ("gr", "importance not checked", "if not k or any(_int(x[\"importance\"]) not in IMPORTANCE for x in k):", "if not k:", "GR6"),
    ("gr", "orphan criteria ignored", 'if sum(len(x["criteres"]) for x in g["champs"]) != len(cr):', "if False:", "GR6"),
    ("gr", "half a grid served", "        return None                                   # a missing text: nothing rather than half a grid\n", "", "GR6"),
    ("gr", "rank gaps accepted", " or [_int(r[\"rang\"]) for r in ch] != list(range(1, len(ch) + 1))", "", "GR6"),
    ("js", "criterion not escaped", "<td data-label=\"Critère\">${esc(k.critere)}</td>", "<td data-label=\"Critère\">${k.critere}</td>", "GR7"),
    ("js", "expectations not escaped", "if (/^- /.test(ln)) { list.push(ln.slice(2)); continue; }", "if (/^- /.test(ln)) { out.push(`<li>${ln.slice(2)}</li>`); continue; }", "GR7"),
    ("js", "dots off by one", "`<i class=\"${i <= n ? \"on\" : \"\"}\"></i>`", "`<i class=\"${i < n ? \"on\" : \"\"}\"></i>`", "GR7"),
    ("js", "no fait foi", "La grille peut changer d'une campagne à l'autre : la fiche Parcoursup fait foi.", "La grille peut changer.", "GR7"),
    ("js", "grid not in the jury tab", "const juryHtml = grHtml + repHtml;", "const juryHtml = repHtml;", "GR7"),
    ("js", "empty card shown", "if (!g || (!g.grille && !g.nationaux && !g.complementaires)) return \"\";", "if (!g) return \"\";", "GR7"),
]


@check("GR9 mutation test: reader, harvest, build and page mutants each caught")
def gr9(c: Ctx):
    base_bad = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        src = c.js if kind == "js" else c.src[kind]
        if old not in src:
            missed.append(f"{name} (anchor gone)")
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
    return not missed, f"{caught}/{len(SOURCE_MUTANTS)} caught; missed {missed}"


def run(db: Path | None = None, real: bool = False) -> list[dict]:
    c = Ctx(real=real, db=db)
    out = []
    for fn in CHECKS:
        t = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": ok, "detail": detail, "s": round(time.time() - t, 1)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", action="store_true", help="also the harvested data/fiches and the committed warehouse")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
