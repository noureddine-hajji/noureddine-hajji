"""Red team of sprint 4 (owner, 2026-11-21): disability support, a student ambassador, immersions and mini-stages, as each LIVE
Parcoursup fiche prints them (scripts/fiche_parse.contact, suptracker/handicap.py, suptracker/immersion.py, the formation page's
handicapCard and decouvrirCard).

    python scripts/redteam_handicap.py [--db data/suptracker.duckdb] [--real]

  HA1 independent reading: BeautifulSoup re-reads the 9 saved live fiches (callout « Sur l'accompagnement pour les situations de
      handicap », the referent line, « Informations supplémentaires » and its paragraphs on disability with their links, the
      ambassador's « Contact : ») with its own rules; equal to fiche_parse.contact.
  HA2 privacy: hostile fiches print a referent's address and phone, an ambassador's, a relay's in the free text: nothing read,
      harvested, built or served carries an e-mail address or a phone number; the referent's contact is never stored, only
      that the fiche gives one.
  HA3 hostile inputs: « néant » referent or ambassador = no contact; no referent line = unknown (never « non »); javascript:,
      data:, mailto: and quoted links dropped (reading and build), and every link carrying an e-mail address or a phone number,
      even percent-encoded (Codex, PR #98); a paragraph that does not speak of disability not kept;
      markup inside a text stays text; an unknown fiche or one with nothing to say = no card.
  HA4 build round trip: fake harvest -> handicap.build / immersion.build -> for_formation gives back what was read; a missing
      text id drops the formation whole; a fiche no longer read (failed, gone) shows nothing.
  HA5 immersion quotes: an independent re-derivation (own folding and words) on crafted texts and, --real, on every harvested
      fiche: each quote is verbatim from its own source text (its pieces when cut, « … » marked), every sentence of the
      formation's OWN texts naming an immersion, a mini-stage, « cours ouverts » or « étudiant d'un jour » is quoted once,
      never a national expectation, each with the right source label.
  HA6 page (Node): both cards escape every stored string, show no address, never claim the place is « accessible » or
      « adapté », say the fiche prevails with its campaign, address the student with « vous », link only the parcoursup.fr
      fiche (https) and http(s) pages with rel="noopener", show nothing when there is nothing; decouvrirCard right after the
      open days in « Y entrer », handicapCard in « Réussir et poursuivre »; our own sentences <= 30 words.
  HA7 plumbing: the formation route serves both blocks, the build calls both modules, the reader is version 4, contact.csv is in
      the warehouse fingerprint, README, CLAUDE.md, durations.json.
  HA8 mutation test of HA1-HA7 (mutants built in memory).
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
import types
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PAGES = ROOT / "data" / "rapports" / "live" / "fiches_live"
FICHES = ROOT / "data" / "fiches"
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>"\''
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
TU = re.compile(r"(?i)\b(tu|ton|ta|tes|toi)\b")
CLAIM = re.compile(r"(?i)\baccessibles?\b|\badapt[ée]e?s?\b|garanti|vos chances|probabilit")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str, package: str | None = None):
    m = types.ModuleType(name)
    m.__file__ = str(path)
    if package:
        m.__package__ = package
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {"fp": (ROOT / "scripts" / "fiche_parse.py").read_text(), "fg": (ROOT / "scripts" / "fiches_grilles.py").read_text(),
                    "ha": (ROOT / "suptracker" / "handicap.py").read_text(), "im": (ROOT / "suptracker" / "immersion.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.build = (ROOT / "suptracker" / "build.py").read_text()
        self.workflow = (ROOT.parent / ".github" / "workflows" / "suptracker-data.yml").read_text()
        self.pages = {p.stem: p.read_text(encoding="utf-8") for p in sorted(PAGES.glob("*.html"))}

    def mod(self, k: str):
        if k == "fp":
            return load(ROOT / "scripts" / "fiche_parse.py", "fiche_parse_ha", self.src["fp"])
        if k == "fg":
            m = load(ROOT / "scripts" / "fiches_grilles.py", "fiches_grilles_ha", self.src["fg"])
            m.parse = self.mod("fp").parse
            return m
        name = {"ha": "handicap", "im": "immersion"}[k]
        return load(ROOT / "suptracker" / f"{name}.py", f"suptracker.{name}_ha", self.src[k], package="suptracker")


# ------------------------------------------------------------------ HA1 independent reading
def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def bs_contact(page: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    out = {"handicap": None, "referent": None, "handicap_infos": [], "ambassadeur": None}
    t = next((h for h in soup.find_all(["h4", "h5", "h6"], class_="fr-callout__title")
              if norm(h.get_text()) == "Sur l'accompagnement pour les situations de handicap"), None)
    if t is not None:
        box = t.find_parent("div")
        ps = [norm(p.get_text(" ")) for p in box.find_all("p")]
        ref = [p for p in ps if p.startswith("Référent handicap")]
        out["handicap"] = " ".join(p for p in ps if p and p not in ref) or None
        if ref:
            rest = norm(ref[0].split(":", 1)[1]) if ":" in ref[0] else ""
            out["referent"] = bool(rest) and rest.lower().rstrip(".") not in ("néant", "neant", "aucun", "aucune", "non renseigné", "non communiqué", "-")
    h = next((x for x in soup.find_all(["h4", "h5"]) if norm(x.get_text()) == "Informations supplémentaires"), None)
    if h is not None:
        for p in h.find_next_siblings("p"):
            links = [a["href"] for a in p.find_all("a", href=True) if re.match(r"https?://", a["href"])]
            txt = norm(p.get_text(" "))
            f = unicodedata.normalize("NFKD", (txt + " " + " ".join(links)).lower())
            if "handicap" in f:
                out["handicap_infos"].append({"texte": txt, "liens": list(dict.fromkeys(links))})
    a = next((x for x in soup.find_all(["h4", "h5", "button"]) if norm(x.get_text()) == "Echanger avec un étudiant ambassadeur de la formation"), None)
    if a is not None:
        sec = a.find_parent("section") or a.find_parent("div")
        p = next((p for p in sec.find_all("p") if norm(p.get_text()).startswith("Contact")), None) if sec else None
        if p is not None:
            v = norm(p.get_text().split(":", 1)[1]) if ":" in p.get_text() else ""
            out["ambassadeur"] = bool(v) and v.lower().rstrip(".") not in ("néant", "neant", "aucun", "aucune", "non renseigné", "non communiqué", "-")
    return out


def _ws(s: str | None) -> str:
    """Whitespace ignored: an inline tag read with get_text(" ") adds spaces the page does not show."""
    return re.sub(r"\s+", "", s or "")


def _same(a: dict, b: dict) -> list:
    diffs = []
    for k in ("referent", "ambassadeur"):
        if a[k] != b[k]:
            diffs.append((k, a[k], b[k]))
    if _ws(a["handicap"]) != _ws(b["handicap"]):
        diffs.append(("handicap", a["handicap"], b["handicap"]))
    ai = [(_ws(x["texte"]), x["liens"]) for x in a["handicap_infos"]]
    bi = [(_ws(x["texte"]), x["liens"]) for x in b["handicap_infos"]]
    if ai != bi:
        diffs.append(("infos", ai, bi))
    return diffs


@check("HA1 independent reading: BeautifulSoup re-reads the saved fiches; callout, referent, disability paragraphs and links, ambassador agree")
def ha1(c: Ctx):
    fp = c.mod("fp")
    if len(c.pages) < 9:
        return False, f"{len(c.pages)} saved pages (9 expected)"
    bad, n_ref, n_amb, n_inf = [], 0, 0, 0
    for k, p in c.pages.items():
        mine, theirs = fp.contact(p), bs_contact(p)
        d = _same(mine, theirs)
        if d:
            bad.append((k, d[:2]))
        n_ref += mine["referent"] is True
        n_amb += mine["ambassadeur"] is not None
        n_inf += len(mine["handicap_infos"])
    # ground truth read by eye (2026-11-21): every saved fiche names a referent; Le Mans prints 3 disability paragraphs, Toulouse
    # and Sorbonne one; the ambassador section says « néant » at Le Mans
    lm = fp.contact(c.pages["8710"])
    if n_ref != 9 or len(lm["handicap_infos"]) != 3 or lm["ambassadeur"] is not False or len(fp.contact(c.pages["4100"])["handicap_infos"]) != 1:
        bad.append(f"ground truth: referents {n_ref}, Le Mans {len(lm['handicap_infos'])} paragraphs ambassador {lm['ambassadeur']}")
    return not bad, f"{len(c.pages)} fiches: {n_ref} referents, {n_amb} ambassador sections, {n_inf} disability paragraphs; {bad[:2]}"


# ------------------------------------------------------------------ hostile pages
def _hostile_pages(c: Ctx) -> dict:
    base = c.pages["4100"]
    pers = "jeanne.martin@univ-exemple.fr"
    p1 = base.replace("[adresse sur la fiche Parcoursup]", pers).replace("[numéro sur la fiche Parcoursup]", "05 61 55 66 77")
    p1 = p1.replace("Informations concernant l'accueil des étudiants en situation de handicap :",
                    f"Relais handicap : écrire à {pers} ou appeler le 06 12 34 56 78. {HOSTILE} "
                    '<a href="https://univ.example/handicap?contact=jeanne.martin%40univ.example&amp;tel=0612345678">page</a> '
                    '<a href="https://univ.example/handicap/06-12-34-56-78">tel</a> '
                    '<a href="https://univ.example/handicap?c=jeanne.martin%2540univ.example">double</a> '
                    "Informations concernant l'accueil des étudiants en situation de handicap :")
    p2 = re.sub(r"(Référent handicap : ).*?</p>", r"\1néant</p>", base, count=1, flags=re.S).replace("<p>Contact : [adresse sur la fiche Parcoursup]</p>", "<p>Contact : néant</p>")
    p3 = re.sub(r"\s*<p>Référent handicap :.*?</p>", "", base, count=1, flags=re.S)
    p4 = base.replace('href="https://iut.univ-tlse3.fr/sante-handicap"', 'href="javascript:alert(1)//handicap"', 1)
    p5 = base.replace("<p>Informations concernant l'accueil", "<p>Accueil handicap : <a href=\"data:text/html,handicap\">ici</a> <a href='https://ok.example.fr/handicap\"x'>là</a> Informations concernant l'accueil", 1)
    return {"pers": p1, "neant": p2, "sans_ligne": p3, "js_lien": p4, "data_lien": p5}


def _fake_harvest(c: Ctx, out: Path, pages: dict, fg=None):
    fg = fg or c.mod("fg")
    fg.codes = lambda db: sorted(pages, key=lambda x: (len(x), x))

    class R:
        def __init__(self, code, text):
            self.status_code, self.text = code, text

    def fetch(http, cod, pause):
        if pages.get(cod) is None:
            return None, R(404, "")
        return f"https://dossier.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={cod}&typeBac=0&originePc=0", R(200, pages[cod])
    fg.fetch_fiche = fetch
    fg.carto_codes = lambda db: None
    return fg.harvest(None, "unused", out, 600, pause=0)


def _built(c: Ctx, src: Path, ha=None, im=None):
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    from suptracker import grilles as GR
    GR.build(con, textes=None, src=src)
    (ha or c.mod("ha")).build(con, src=src)
    (im or c.mod("im")).build(con, src=src)
    return con


def _decoded(s: str) -> str:
    """Percent-encoding undone (three times: a double-encoded address too), HTML entities read: an encoded contact is seen."""
    import html as H
    from urllib.parse import unquote
    for _ in range(3):
        s = unquote(H.unescape(s))
    return s


def _contact_in(s: str) -> bool:
    d = _decoded(s)
    return bool(EMAIL.search(d) or PHONE.search(d) or re.search(r"(?<!\d)0[1-9](?:\d{2}){4}(?!\d)", re.sub(r"[\s.+_()-]", "", d)))


def _all_text(path: Path) -> str:
    out = []
    for f in sorted(path.rglob("*")):
        if f.is_file():
            out.append(gzip.open(f, "rt", encoding="utf-8").read() if f.suffix == ".gz" else f.read_text(encoding="utf-8"))
    return "\n".join(out)


@check("HA2 privacy: no e-mail address or phone number read, harvested, built or served; never the referent's contact")
def ha2(c: Ctx):
    fp = c.mod("fp")
    bad = []
    pages = {"4100": _hostile_pages(c)["pers"]}
    got = fp.contact(pages["4100"])
    blob = json.dumps(got, ensure_ascii=False)
    if _contact_in(blob):
        bad.append(f"read: {blob[:200]}")
    if got["referent"] is not True:
        bad.append("a referent with an address not seen as given")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fiches"
        _fake_harvest(c, out, pages)
        stored = _all_text(out)
        if "jeanne.martin" in _decoded(stored) or _contact_in(stored):
            bad.append("harvest files carry an address or a phone")
        con = _built(c, out)
        served = json.dumps([c.mod("ha").for_formation(con, "4100"), c.mod("im").for_formation(con, "4100")], ensure_ascii=False)
        tables = json.dumps(con.execute("SELECT * FROM core.fiche_handicap").fetchall(), ensure_ascii=False, default=str)
        if _contact_in(served) or _contact_in(tables):
            bad.append(f"built or served: {served[:200]}")
        # a row an older reader stored with a link carrying a contact is cleaned at the next run (Codex, PR #98)
        rows = list(csv.DictReader(open(out / "contact.csv", encoding="utf-8")))
        rows[0]["handicap_infos"] = json.dumps([{"texte_id": "", "liens": ["https://u.fr/h?c=jeanne.martin%40u.fr", "https://u.fr/handicap"]}])
        with open(out / "contact.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        _fake_harvest(c, out, pages)                         # an open site, nothing due: the stored rows are saved again
        again = (out / "contact.csv").read_text(encoding="utf-8")
        if _contact_in(again) or "https://u.fr/handicap" not in again:
            bad.append("a stored link with a contact survives the next run, or a plain one is lost")
        cols = {r[0] for r in con.execute("DESCRIBE core.fiche_handicap").fetchall()}
        if cols & {"contact", "adresse", "email", "mail", "telephone"}:
            bad.append(f"a contact column {cols}")
    return not bad, f"hostile fiche read, harvested, built and served; {bad[:3]}"


@check("HA3 hostile inputs: néant, no referent line, javascript/data/quoted links, paragraphs off topic, markup, empty fiches")
def ha3(c: Ctx):
    fp, ha = c.mod("fp"), c.mod("ha")
    hp = _hostile_pages(c)
    bad = []
    n = fp.contact(hp["neant"])
    if n["referent"] is not False or n["ambassadeur"] is not False:
        bad.append(f"néant read as a contact: {n['referent']} {n['ambassadeur']}")
    s = fp.contact(hp["sans_ligne"])
    if s["referent"] is not None:
        bad.append(f"no referent line read as {s['referent']}")
    for k in ("js_lien", "data_lien"):
        links = [u for x in fp.contact(hp[k])["handicap_infos"] for u in x["liens"]]
        if any(not re.match(r"https?://[^\s\"'<>]+$", u) for u in links):
            bad.append(f"{k}: link kept {links}")
    if ha._links(["javascript:alert(1)", "data:x", "mailto:a@b.fr", 'https://a.fr/"x', "https://ok.fr/handicap", "http://ok.fr/h",
                  "https://a.fr/h?m=jeanne.martin%40univ.fr", "https://a.fr/h?m=jeanne%2540univ.fr", "https://a.fr/h/06.12.34.56.78",
                  "https://a.fr/h?tel=%2B33612345678", "https://a.fr/mailto:x"]) != ["https://ok.fr/handicap", "http://ok.fr/h"]:
        bad.append("build-side link filter keeps a link with contact information")
    kept = [u for x in fp.contact(_hostile_pages(c)["pers"])["handicap_infos"] for u in x["liens"]]
    if any(_contact_in(u) for u in kept) or "https://iut.univ-tlse3.fr/sante-handicap" not in kept:
        bad.append(f"reader: links with contact information kept, or the plain one dropped: {kept}")
    off = fp.contact(c.pages["4100"])
    if any("Découvrir le campus" in x["texte"] for x in off["handicap_infos"]):
        bad.append("a paragraph off topic kept")
    m = fp.contact(c.pages["4100"].replace("Possibilité d'aménagement de la scolarité pour les personnes en situation de handicap.",
                                            "Possibilité &lt;script&gt;x&lt;/script&gt; d'aménagement.", 1))
    if "<script>" not in (m["handicap"] or ""):
        bad.append("an escaped markup lost (the page escapes it)")
    if fp.contact("<html><title>Fiche formation</title></html>") != {"handicap": None, "referent": None, "infos": None,
                                                                       "handicap_infos": [], "ambassadeur": None}:
        bad.append("an empty fiche read as something")
    return not bad, f"5 hostile fiches; {bad[:4]}"


@check("HA4 build round trip: harvest -> build -> API equals the reading; a missing text drops the formation whole; gone fiches show nothing")
def ha4(c: Ctx):
    fp, ha = c.mod("fp"), c.mod("ha")
    bad = []
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fiches"
        pages = dict(c.pages)
        _fake_harvest(c, out, pages)
        con = _built(c, out)
        for k, p in pages.items():
            want, got = fp.contact(p), ha.for_formation(con, k)
            if got is None:
                bad.append(f"{k}: nothing served")
                continue
            if got["referent"] != want["referent"] or got["ambassadeur"] != want["ambassadeur"] or got["handicap"] != want["handicap"] \
                    or [(x["texte"], x["liens"]) for x in got["infos"]] != [(x["texte"], x["liens"]) for x in want["handicap_infos"]]:
                bad.append(f"{k}: served differs")
            if got["session"] != 2026 or not (got["url"] or "").startswith("https://dossier.parcoursup.fr/"):
                bad.append(f"{k}: credit {got['session']} {got['url']}")
        if ha.for_formation(con, "999999") is not None:
            bad.append("an unknown code served")
        # a missing text id: the formation is dropped whole
        rows = list(csv.DictReader(open(out / "contact.csv", encoding="utf-8")))
        for r in rows:
            if r["cod_aff_form"] == "8710":
                inf = json.loads(r["handicap_infos"])
                inf[0]["texte_id"] = "ffffffffffffffff"
                r["handicap_infos"] = json.dumps(inf)
            if r["cod_aff_form"] == "4100":
                r["handicap_id"] = "eeeeeeeeeeeeeeee"
        with open(out / "contact.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        et = list(csv.DictReader(open(out / "etat.csv", encoding="utf-8")))
        for r in et:
            if r["cod_aff_form"] == "2986":
                r["status"] = "failed"
        with open(out / "etat.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(et[0].keys()))
            w.writeheader()
            w.writerows(et)
        con2 = _built(c, out)
        for k in ("8710", "4100", "2986"):
            if ha.for_formation(con2, k) is not None:
                bad.append(f"{k}: shown although its text is missing or its fiche no longer read")
    return not bad, f"{len(c.pages)} round trips, 3 tampered; {bad[:3]}"


# ------------------------------------------------------------------ HA5 immersion quotes
def rt_fold(s: str) -> str:
    s = s.replace("’", "'").lower()
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


RT_WORDS = [re.compile(p) for p in (r"\bimmersions?\b", r"\bmini ?-? ?stages?\b", r"\bcours ouverts?\b",  # whole words: « stage-dimmersion »
                                    r"\b(etudiant|etudiante|lyceen|lyceenne|eleve)s?( ?\( ?e ?\))? d.?un jour\b")]
RT_LABEL = {"conseils": "Conseils aux candidats", "complementaires": "Attendus de la formation", "critere": "Ce que le jury examine",
            "infos": "Informations de l'établissement", "info": "Candidater à la formation"}


def rt_has(s: str) -> bool:
    f = rt_fold(s)
    return any(r.search(f) for r in RT_WORDS)


def rt_sentences(t: str) -> list[str]:
    out = []
    for line in (t or "").split("\n"):
        out += [x.strip() for x in re.split(r"(?<=[.!?;])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"(-])", line) if x.strip()]
    return out


def quote_ok(q: str, sources: list[str]) -> bool:
    """A quote is verbatim from one of the sources, or its pieces are (a cut sentence, « … » at the cut)."""
    core = q.removeprefix("… ").removesuffix(" …")
    return any(core in s for s in sources)


def _check_quotes(im, parts: dict, quotes: list[dict], national: list[str]) -> list:
    """parts: source kind -> list of own texts. Every keyword sentence quoted once with its label; every quote verbatim."""
    bad = []
    want = []
    for kind in ("conseils", "complementaires", "critere", "infos", "info"):
        for t in parts.get(kind, []):
            for s in rt_sentences(t):
                if rt_has(s):
                    want.append((kind, s))
    seen = set()
    expect = []
    for kind, s in want:
        if s not in seen:
            seen.add(s)
            expect.append((kind, s))
    if len(quotes) != len({im.excerpt(s) for _k, s in expect}):
        bad.append(f"{len(quotes)} quotes for {len(expect)} sentences")
    for q in quotes:
        own = parts.get(q["source"], [])
        if not quote_ok(q["texte"], own):
            bad.append(f"not verbatim: {q['texte'][:60]}")
        if q["label"] != RT_LABEL[q["source"]]:
            bad.append(f"label {q['label']}")
        if any(q["texte"] in n for n in national) and not any(q["texte"] in o for k in parts for o in parts[k]):
            bad.append("a national expectation quoted")
    return bad


@check("HA5 immersion: each quote verbatim from its own source; every keyword sentence quoted once; never a national expectation (crafted, --real)")
def ha5(c: Ctx):
    im = c.mod("im")
    bad = []
    long = "Nous accueillons les lycéens " + "pour une journée complète de découverte des enseignements " * 9 + "lors de nos journées d'immersion en janvier, et " + "nous répondons à toutes les questions des familles " * 6 + "."
    crafted = {"conseils": ["Venez à nos journées d’immersion ! Inscrivez-vous en ligne. Les mini-stages sont possibles toute l'année.",
                            "Participer aux Cours ouverts du samedi. Devenez Étudiant d'un jour.", long],
               "critere": ["Participation à une immersion", "Lettre de motivation"],
               "infos": ["L'immersion linguistique est obligatoire au S3 ; le campus est neuf."],
               "complementaires": ["Aucune mention ici."]}
    parts = [(k, t) for k, ts in crafted.items() for t in ts]
    quotes = im.quotes(parts)
    bad += _check_quotes(im, crafted, quotes, [])
    if not any(q["texte"].startswith("… ") or q["texte"].endswith(" …") for q in quotes):
        bad.append("a long sentence not cut")
    if any(len(q["texte"]) > im.MAX_CHARS + 4 for q in quotes):
        bad.append("a quote longer than the limit")
    if im.quotes([("conseils", "Une démarche d'immersion. Une démarche d'immersion.")]).__len__() != 1:
        bad.append("a sentence quoted twice")
    if im.matches("Le ministère organise un séminaire") or not im.matches("MINI STAGE en BTS"):
        bad.append("keywords")
    # the harvest's own files: a national expectation naming an immersion is never quoted, the formation's advice is
    with tempfile.TemporaryDirectory() as d:
        src = Path(d)
        nat, own = "Les candidats ont fait une immersion en entreprise.", "Venez à nos journées d'immersion."
        with open(src / "etat.csv", "w", encoding="utf-8") as f:
            f.write("cod_aff_form,status,lu_le,session,raison,url,version\n77,ok,20261121000000,2026,,,4\n")
        with open(src / "attendus.csv", "w", encoding="utf-8") as f:
            f.write("cod_aff_form,session,nationaux_id,complementaires_id,conseils_id,info_id\n77,2026,n1,,c1,\n")
        with gzip.open(src / "textes.csv.gz", "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerows([("id", "texte"), ("n1", nat), ("c1", own)])
        rows = im.assemble(src)
        if [r[3] for r in rows] != [own]:
            bad.append(f"harvest files: quoted {[r[3] for r in rows]}")
    real = 0
    if c.real and (FICHES / "etat.csv").exists():
        from suptracker import grilles as GR
        texts = GR.read_texts(FICHES / "textes.csv.gz")
        own: dict = {}
        nat: dict = {}
        for r in GR._read(FICHES / "attendus.csv"):
            for k, col in (("complementaires", "complementaires_id"), ("conseils", "conseils_id"), ("info", "info_id")):
                if r.get(col) in texts:
                    own.setdefault(r["cod_aff_form"], {}).setdefault(k, []).append(texts[r[col]])
            if r.get("nationaux_id") in texts:
                nat.setdefault(r["cod_aff_form"], []).append(texts[r["nationaux_id"]])
        for r in GR._read(FICHES / "criteres.csv"):
            for col in ("critere_id", "elements_id"):
                if r.get(col) in texts:
                    own.setdefault(r["cod_aff_form"], {}).setdefault("critere", []).append(texts[r[col]])
        for r in GR._read(FICHES / "contact.csv") if (FICHES / "contact.csv").exists() else []:
            if r.get("infos_id") in texts:
                own.setdefault(r["cod_aff_form"], {}).setdefault("infos", []).append(texts[r["infos_id"]])
        etat = {r["cod_aff_form"]: r["status"] for r in GR._read(FICHES / "etat.csv")}
        rows = im.assemble(FICHES)
        by: dict = {}
        for cod, _rang, src, texte, mots in rows:
            by.setdefault(cod, []).append({"source": src, "label": im.LABEL[src], "texte": texte})
        for cod, p in own.items():
            if etat.get(cod) not in ("ok", "sans_grille", "rejetee"):
                continue
            b = _check_quotes(im, p, by.get(cod, []), nat.get(cod, []))
            if b:
                bad.append((cod, b[:2]))
            real += 1
        if len(by) < 1000:
            bad.append(f"only {len(by)} formations quoted on the real harvest")
    return not bad, f"crafted + {real} real fiches re-derived; {bad[:3]}"


# ------------------------------------------------------------------ HA6 page
def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        return js[m.start(): m.start() + e.end()]
    return js[m.start(): js.find("\n}", m.start()) + 2]


NAMES = ("esc", "frDate", "ficheLink", "ficheCredit", "decouvrirCard", "handicapCard")


def run_node(js: str, payload):
    exe = shutil.which("node")
    if not exe:
        return None
    prog = "\n".join(top(js, n) for n in NAMES) + """
const P = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(P.map(([kind, a, b]) => kind === "d" ? decouvrirCard(a, b) : handicapCard(a))));"""
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout)


def page_ok(js: str) -> tuple[bool, str]:
    bad = []
    H = HOSTILE
    im = {"session": 2026, "lu_le": "2026-11-15", "url": "https://dossier.parcoursup.fr/x?g_ta_cod=1",
          "phrases": [{"source": "conseils", "label": "Conseils" + H, "texte": "Venez en immersion " + H, "mots": ["immersion"]},
                      {"source": "critere", "label": "Jury", "texte": "Mini-stage", "mots": ["mini-stage"]},
                      {"source": "infos", "label": "Infos", "texte": "Troisième " + H, "mots": ["immersion"]}]}
    ha = {"session": 2026, "lu_le": "2026-11-15", "url": "https://dossier.parcoursup.fr/x?g_ta_cod=1", "handicap": "Possibilité " + H,
          "referent": True, "ambassadeur": True,
          "infos": [{"texte": "Relais handicap " + H, "liens": ["https://univ.fr/handicap?a=1&b=2", "javascript:alert(1)"]}]}
    evil = dict(ha, url="javascript:alert(1)")
    evil2 = dict(im, url="https://evil.example.com/parcoursup.fr/x")
    cases = [["d", im, ha], ["d", None, dict(ha, ambassadeur=False)], ["d", None, None], ["d", {"phrases": []}, {"ambassadeur": None}],
             ["h", ha, None], ["h", dict(ha, referent=False, infos=[]), None], ["h", None, None], ["h", {"handicap": None, "referent": None, "infos": []}, None],
             ["h", evil, None], ["d", evil2, None], ["h", dict(ha, referent=None), None]]
    r = run_node(js, cases)
    if r is None:
        return True, "node not installed"
    d_full, d_none_amb, d_null, d_empty, h_full, h_no, h_null, h_empty, h_evil, d_evil, h_unknown = r
    for name, html in (("decouvrir", d_full), ("handicap", h_full)):
        if "<img" in html or "onerror=alert(1)>" in html.replace("&lt;img src=x onerror=alert(1)&gt;", ""):
            bad.append(f"{name}: unescaped")
        if EMAIL.search(html) or PHONE.search(html):
            bad.append(f"{name}: an address or a phone")
        if CLAIM.search(re.sub(r"<[^>]+>", " ", html)):
            bad.append(f"{name}: a claim ({CLAIM.search(re.sub(r'<[^>]+>', ' ', html)).group(0)})")
        if TU.search(re.sub(r"<[^>]+>", " ", html)):
            bad.append(f"{name}: tutoiement")
        if "La fiche fait foi." not in html or "campagne 2026" not in html:
            bad.append(f"{name}: no credit")
        for a in re.findall(r"<a [^>]*>", html):
            if 'rel="noopener"' not in a or not re.search(r'href="https?://', a):
                bad.append(f"{name}: link {a[:80]}")
    if "javascript:" in h_full or "javascript:" in h_evil or "evil.example.com" in d_evil:
        bad.append("a link not on the fiche's host or not http(s)")
    if d_full.count("<blockquote") != 3 or "<details>" not in d_full:
        bad.append("quotes: 2 shown, the rest folded")
    if "étudiant ambassadeur" not in d_full or "étudiant ambassadeur" in d_none_amb or d_null or d_empty:
        bad.append("ambassador line / empty card")
    if "référent handicap" not in h_full or "n'indique pas de référent" not in h_no or h_null or h_empty:
        bad.append("referent lines / empty card")
    if "référent" in h_unknown.replace("Situation de handicap", ""):
        bad.append("an unknown referent line said")
    if "ne vous demande jamais si vous êtes en situation de handicap" not in h_full:
        bad.append("the card does not say the site never asks")
    own = re.findall(r"<p[^>]*>([^<«]+)</p>", d_full + h_full)
    long = [s for p in own for s in re.split(r"(?<=[.!?])\s+", p) if len(s.split()) > 30]
    if long:
        bad.append(f"sentences over 30 words: {long[:1]}")
    vf = js[js.index("async function viewFormation("):]
    adm = vf[vf.index('["admission", "Y entrer", `'):vf.index('["jury", "Ce que regarde le jury"')]
    reu = vf[vf.index('["reussite", "Réussir et poursuivre", `'):vf.index('["emploi", "Emploi et métiers"')]
    if "  ${jpoCard(d.jpo)}\n  ${decouvrirCard(d.immersion, d.handicap)}\n" not in adm:
        bad.append("decouvrirCard not right after the open days")
    if "${handicapCard(d.handicap)}" not in reu:
        bad.append("handicapCard not in « Réussir et poursuivre »")
    return not bad, f"{len(cases)} renders; {bad[:4]}"


@check("HA6 page: escaped, no address, no claim, credit and fait foi, vous, fiche and http(s) links only, nothing when empty, placed")
def ha6(c: Ctx):
    return page_ok(c.js)


@check("HA7 plumbing: route, build, reader version 4, fingerprint, README, CLAUDE.md, durations")
def ha7(c: Ctx):
    bad = []
    if '"handicap": HA.for_formation(_con().cursor(), rec["cod_aff_form"])' not in c.api or '"immersion": IMM.for_formation(' not in c.api:
        bad.append("route")
    if "handicap.build(con)" not in c.build or "immersion.build(con)" not in c.build:
        bad.append("build")
    if not re.search(r"^VERSION = 4\b", c.src["fp"], re.M) or 'out["contact"] = contact(page)' not in c.src["fp"]:
        bad.append("reader version")
    if "data/fiches/contact.csv" not in c.workflow.split("fp=$(", 1)[-1].split("sha256sum", 1)[0]:
        bad.append("contact.csv not in the warehouse fingerprint")
    readme = (ROOT / "README.md").read_text()
    claude = (ROOT.parent / "CLAUDE.md").read_text()
    dur = json.loads((ROOT / "tests" / "durations.json").read_text())
    if "handicap.py" not in readme or "immersion.py" not in readme:
        bad.append("README")
    if "redteam_handicap.py" not in claude:
        bad.append("CLAUDE.md")
    if "tests/test_handicap.py" not in dur:
        bad.append("durations.json")
    return not bad, f"{bad}"


MUTANTS = [
    ("fp", "referent's address kept", '            out["referent"] = bool(rest) and not NEANT.fullmatch(rest)',
     '            out["referent"] = rest or None', "HA2"),
    ("fp", "texts not masked", '        out["infos"] = mask(text(i.group(1))) or None', '        out["infos"] = text(i.group(1)) or None', "HA2"),
    ("fp", "paragraphs not masked", "            t = mask(text(p))", "            t = text(p)", "HA2"),
    ("fp", "néant is a contact", '            out["referent"] = bool(rest) and not NEANT.fullmatch(rest)', '            out["referent"] = bool(rest)', "HA3"),
    ("fp", "no line = no referent", '    out = {"handicap": None, "referent": None,', '    out = {"handicap": None, "referent": False,', "HA3"),
    ("fp", "any link kept", r'''re.findall(r"""href=["'](https?://[^"'\s<>]+)["']""", p)''', r'''re.findall(r"""href=["']([^"']+)["']""", p)''', "HA3"),
    ("fp", "every paragraph kept", '            if "handicap" in _fold(f"{t} {\' \'.join(links)}"):', "            if True:", "HA1"),
    ("fp", "referent line in the text", '        out["handicap"] = mask("\\n".join(x for x in lines if x and x not in ref)) or None',
     '        out["handicap"] = mask("\\n".join(x for x in lines if x)) or None', "HA1"),
    ("fp", "ambassador never read", '        out["ambassadeur"] = bool(v) and not NEANT.fullmatch(v)', '        out["ambassadeur"] = None', "HA1"),
    ("fp", "reader keeps links with a contact", "if not personal_link(html.unescape(u))]", "]", "HA2"),
    ("fg", "stored rows not cleaned", '{r["cod_aff_form"]: clean_contact(r) for r in', '{r["cod_aff_form"]: r for r in', "HA2"),
    ("ha", "build keeps links with a contact", "                and not _personal(u):", "                and True:", "HA3"),
    ("ha", "encoded contacts not decoded", "    for _ in range(3):\n        s = unquote(s)\n    return \"@\" in s", "    return \"@\" in s", "HA3"),
    ("ha", "build keeps any link", '(u.startswith("https://") or u.startswith("http://")) and not any(ch in u for ch in \' "<>\\\'`\')', "True", "HA3"),
    ("ha", "half a card", "            continue                                       # a missing text: nothing rather than half a card",
     "            infos = []", "HA4"),
    ("ha", "gone fiches shown", '        if e.get("status") not in ("ok", "sans_grille", "rejetee"):\n            continue                                       # a fiche no longer read',
     '        if False:\n            continue                                       # a fiche no longer read', "HA4"),
    ("ha", "missing callout text served", "        if h and h not in texts:\n            continue", "        if False:\n            continue", "HA4"),
    ("im", "national expectations quoted", '        add(c, "complementaires", r.get("complementaires_id"))', '        add(c, "complementaires", r.get("complementaires_id"))\n        add(c, "conseils", r.get("nationaux_id"))', "HA5"),
    ("im", "sentence rewritten", '            out.append({"source": src, "label": LABEL[src], "texte": q, "mots": m})',
     '            out.append({"source": src, "label": LABEL[src], "texte": q.lower(), "mots": m})', "HA5"),
    ("im", "mini-stages missed", '    ("mini-stage", re.compile(r"\\bmini\\s*-?\\s*stages?\\b")),', "", "HA5"),
    ("im", "duplicates quoted", "            if q in seen:\n                continue", "            if False:\n                continue", "HA5"),
    ("im", "no cut", "    if len(s) <= MAX_CHARS:", "    if True:", "HA5"),
    ("im", "wrong label", '("critere", "Ce que le jury examine")', '("critere", "Conseils aux candidats")', "HA5"),
    ("js", "quote unescaped", "<blockquote class=\"imm-q\">« ${esc(x.texte)} »</blockquote>", "<blockquote class=\"imm-q\">« ${x.texte} »</blockquote>", "HA6"),
    ("js", "callout unescaped", "<blockquote class=\"imm-q\">« ${esc(ha.handicap)} »</blockquote>", "<blockquote class=\"imm-q\">« ${ha.handicap} »</blockquote>", "HA6"),
    ("js", "any fiche host", 'const ficheLink = (u) => (typeof u === "string" && /^https:\\/\\/[a-z0-9.-]*parcoursup\\.fr\\/[^\\s"\'<>]*$/.test(u) ? u : null);',
     'const ficheLink = (u) => (typeof u === "string" ? u : null);', "HA6"),
    ("js", "no fait foi", "La fiche fait foi.`;", "`;", "HA6"),
    ("js", "an accessibility claim", "C'est la personne à qui parler de vos besoins, avant ou après votre admission.",
     "La formation est accessible : c'est la personne à qui parler de vos besoins.", "HA6"),
    ("js", "card shown empty", '  if (!ph.length && !amb) return "";', "", "HA6"),
    ("js", "unknown referent said no", '    : ha.referent === false ?', "    : ha.referent !== true ?", "HA6"),
    ("js", "card moved after the SIES figures", "  ${jpoCard(d.jpo)}\n  ${decouvrirCard(d.immersion, d.handicap)}\n", "  ${jpoCard(d.jpo)}\n", "HA6"),
    ("api", "route without the blocks", '            "handicap": HA.for_formation(_con().cursor(), rec["cod_aff_form"]),\n', "", "HA7"),
    ("fp", "reader version not bumped", "VERSION = 4 ", "VERSION = 3 ", "HA7"),
]


@check("HA8 mutation test: every seeded reading, privacy, build, quote, page and plumbing bug is caught")
def ha8(c: Ctx):
    base = [fn.check_name.split()[0] for fn in CHECKS[:7] if not fn(c)[0]]
    if base:
        return False, f"the unmutated code fails {base}: mutants not counted"
    missed, caught = [], 0
    for kind, name, old, new, target in MUTANTS:
        m = copy.copy(c)
        if kind in c.src:
            if old not in c.src[kind]:
                missed.append(f"{name} (anchor gone)")
                continue
            m.src = dict(c.src, **{kind: c.src[kind].replace(old, new, 1)})
        else:
            if old not in getattr(c, kind):
                missed.append(f"{name} (anchor gone)")
                continue
            setattr(m, kind, getattr(c, kind).replace(old, new, 1))
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
