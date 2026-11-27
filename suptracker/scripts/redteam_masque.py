"""Red team of audit PR 4 (owner, 2026-11-24): the search page hides nothing without saying so.

    python scripts/redteam_masque.py [--db data/suptracker.duckdb] [--real] [--browser]

The audit of 2026-11-23 found four silent gaps on the search page: the paid private formations were unticked by default with
nothing in the list saying so (« école de commerce Lyon » showed none of its 24), an acronym (« BTS MCO ») found none of the
apprenticeship offers listed apart (0 against 988 with the full title), « apprentissage » was « Ignoré » with a note saying the
results were « sous statut scolaire » while the cards carried the apprenticeship badge, and a filter kept from an earlier visit
(a zone) gave 0 results with nothing on screen naming it.

  MQ1 offer terms (Python): the « Mot compris » chip says the words typed, never a tag name (« ecom »); search.offer_terms gives, for each word, the typed word or for an acronym / known phrase the typed
      phrase and its tag's label phrases (TAG_RULES literals only, never fuzzy); apprenticeship, internat and stop words out; no
      empty group; on real data an acronym finds exactly the offers its full title finds (BTS MCO, NDRC, SIO, GPME, CG...)
  MQ2 the page's twin (Node vs Python): carteOfferMatch and carteCommon on crafted rows and keywords = an independent Python
      reading (terms, the apprenticeship option, the internat option (Codex, PR #111: « BTS avec internat » let 7,138 offers
      without an internat through), a bare code); the keyword answer's terms and flags reach the page (kwLoad); the page's
      internat values are the engine's option
  MQ3 apprenticeship is an option, never « Ignoré »: the engine strips the words, says « Option : apprentissage », sets the flag;
      the page keeps the formations offered in apprenticeship; the note is true (no « statut scolaire » anywhere a student reads)
  MQ4 the hidden paid formations are counted and offered: carteHiddenPaid (Node) = an independent count (crafted rows and the real
      layer for several keywords); « N formations d'établissements privés payants masquées — les afficher » ticks their box
  MQ5 filters kept from an earlier visit are named: carteActive (Node) names every group that differs from its default and the zone
      filter; the notice appears on entering the page (never for a shared link), any change of filter clears it, the reset is the
      bar's own; a search with no result names the active filters with the same reset
  MQ6 browser (--browser / --real): the real page shows the paid line with the Python count and shows them on click; a stored
      filter is named on entering and cleared by the reset; « BTS MCO » lists as many offers as the full title; leaving the page
      right after a search raises no JS error and the page comes back (the testers' « Cannot set properties of null »: the map's
      animated zoom ended on another page, redrew the gone list and saved invalid bounds, then « Bounds are not valid. » replaced
      the whole page on the way back); no JS error, no horizontal scroll (phone)
  MQ7 mutation test of MQ1-MQ5 and MQ8 (mutants built in memory)
  MQ8 wiring and docs: README section, CLAUDE.md rule, test file and its CI duration, nightly browser suite
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import carte as CA  # noqa: E402
from suptracker import search as S  # noqa: E402
from redteam_recherche import top  # noqa: E402
import os as _os_nf, sys as _sys_nf  # noqa: E401,E402  lot 1, PR 9: Node programs through a file (nodefile.py)
_sys_nf.path.insert(0, _os_nf.path.dirname(_os_nf.path.abspath(__file__)))
import nodefile  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
HOSTILE = '<img src=x onerror=alert(1)>'
# acronym -> its full title, for the « an acronym finds what its title finds » witness
PAIRS = (("BTS MCO", "BTS management commercial opérationnel"), ("BTS NDRC", "BTS négociation et digitalisation"),
         ("BTS SIO", "BTS services informatiques aux organisations"), ("BTS GPME", "BTS gestion de la PME"),
         ("BTS CG", "BTS comptabilité et gestion"), ("BUT GEA", "BUT gestion des entreprises et des administrations"),
         ("BUT TC", "BUT techniques de commercialisation"))
APP_WORDS = ("apprentissage", "alternance", "apprenti", "en alternance", "apprentie")
STOPS = ("de", "la", "le", "et", "en", "pour", "avec")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def fold(x) -> str:
    """Independent twin of the page's folded name: accents off, lower case, every non-alphanumeric a space."""
    t = "".join(ch for ch in unicodedata.normalize("NFD", str(x or "")) if not ("̀" <= ch <= "ͯ")).lower()
    return re.sub(r"[^a-z0-9]+", " ", t)


def literals() -> set:
    """Every literal phrase of the engine's tag rules, read again here (anchors off, alternatives split)."""
    out = set()
    for _tags, _f, rx in S.TAG_RULES:
        for alt in rx.split("|"):
            alt = alt.strip("^$").strip()
            if re.fullmatch(r"[a-z0-9 ]+", alt):
                out.add(alt)
    return out


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.search_src = (ROOT / "suptracker" / "search.py").read_text()
        self.api_src = (ROOT / "suptracker" / "api.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self.durations = (ROOT / "tests" / "durations.json").read_text()
        self.nightly = (ROOT / "scripts" / "browser_nightly.py").read_text()
        self._rows = None

    @property
    def rows(self) -> list:
        if self._rows is None:
            by_dip = CA._layer(self.con)[0]
            self._rows = [f for fs in by_dip.values() for f in fs]
        return self._rows


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = nodefile.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


INTERNAT_OK = ("mixte", "filles", "garcons", "oui")     # the engine's « internat » option, read again here


def offer_hits(rows, terms, app, codes=(), internat=False) -> list:
    """Independent reading of the page's keyword rule: a code the engine gave, else an offer listed apart whose folded name holds
    one alternative of every term (no term: only when the query named apprenticeship); the apprenticeship option keeps only the
    formations offered in apprenticeship."""
    out = []
    for f in rows:
        text = f" {fold(f"{f.get('etablissement')} {f.get('formation')} {f.get('ville')}")} "
        offer = f.get("stats") is False and (all(any(a in text for a in alts) for alts in terms) if terms else bool(app))
        if (f["cod_aff_form"] in codes or offer) and (not app or f.get("apprentissage")) \
                and (not internat or f.get("internat") in INTERNAT_OK):     # Codex: the internat option holds for offers too
            out.append(f["cod_aff_form"])
    return out


# ------------------------------------------------------------------ MQ1 offer terms
def terms_ok(c: Ctx, fn=None) -> tuple[bool, str]:
    fn = fn or S.offer_terms
    lit, bad = literals(), []
    queries = ["BTS MCO", "bts ndrc lyon", "école de commerce Lyon", "IFSI Marseille", "BUT info en alternance", "Sciences Po",
               "prépa HEC avec internat", "licence de droit et économie", HOSTILE, "apprentissage", "école", "  ", "BTS  MCO  "]
    for q in queries:
        got = fn(q)
        typed = f" {' '.join(fold(q).split())} "
        for alts in got:
            if not alts:
                bad.append((q, "an empty group"))
            for a in alts:
                # an alternative is something typed (a word or phrase of the folded query) or a tag rule's literal; a tag's
                # alternatives are whole words (padded), a free word is bare
                if f" {a.strip()} " not in typed and a.strip() not in lit:
                    bad.append((q, "an alternative neither typed nor a tag literal", a))
                if any(w in a.split() for w in ("apprentissage", "alternance", "apprenti", "internat")):
                    bad.append((q, "an option word kept", a))
            if len(alts) == 1 and alts[0] in STOPS:
                bad.append((q, "a stop word kept", alts))
    if fn("apprentissage") != [] or fn("en alternance") != []:
        bad.append(("apprentissage alone", fn("apprentissage")))
    mco = fn("BTS MCO")
    if len(mco) != 2 or " management commercial operationnel " not in mco[1] or " mco " not in mco[1] or mco[0] != [" bts "]:
        bad.append(("BTS MCO", mco))
    if fn("école") != [["ecole"]] or fn("école de commerce Lyon")[-1] != ["lyon"] or fn("BUT info")[1] != ["info"]:
        bad.append(("generic word only when alone", fn("école"), fn("école de commerce Lyon")))
    # the « Mot compris » chip says the words typed, never the engine's tag name (« ecom », « scpo »)
    tags = {t[2:] for t in S.PHRASES.values() if t.startswith("t_") and t[2:] not in S.PHRASES}
    for q, want in (("école de commerce Lyon", "ecole de commerce"), ("sciences po Paris", "sciences po"), ("BTS MCO", "mco")):
        chips = [i["value"] for i in S.search(c.con.cursor(), q, limit=1)["interpretation"] if i["type"] == "sigle"]
        if want not in chips or any(v in tags for v in chips):
            bad.append((q, "the chip shows a tag name", chips))
    witness = []
    if c.real:
        from suptracker import api
        for acr, full in PAIRS:
            a = api.keyword_codes(c.con.cursor(), acr)
            b = api.keyword_codes(c.con.cursor(), full)
            oa = set(offer_hits([f for f in c.rows if f.get("stats") is False], fn(acr), a["apprentissage"]))
            ob = set(offer_hits([f for f in c.rows if f.get("stats") is False], fn(full), b["apprentissage"]))
            witness.append((acr, len(oa), len(ob)))
            if oa != ob:
                bad.append((acr, "the acronym's offers differ from its title's", len(oa), len(ob)))
        if not any(n for _, n, _ in witness):
            bad.append(("no offer found by any acronym on real data", witness))
    return not bad, f"{len(queries)} queries; acronym = title {witness}; problems {bad[:4]}"


@check("MQ1 offer terms: the typed word or the tag's label phrases, never fuzzy; option and stop words out; acronym = full title")
def mq1(c: Ctx):
    return terms_ok(c)


# ------------------------------------------------------------------ MQ2 the page's twin
STUBS = """const CARTE_R3 = [], fiOptions = () => [], filtreBand = () => null, robReady = () => false, robLevel = () => "",
  haversineKm = () => 0, carteZone = (f) => f.zone || "autre", FI_TITLE = {}, CARTE_ROB = [];
"""
NAMES = ("ACAD_LABEL", "acadLabel", "foldText", "CARTE_DEFAULT", "CARTE_GROUPS", "CARTE_ACADS", "JURY_KEYS", "JURY_LEVELS", "juryMeta", "juryLevel", "juryGroups", "juryCuts", "carteGroups", "CARTE_FGROUPS", "carteHas",
         "carteFolded", "carteText", "carteOfferMatch", "KW_INTERNAT", "carteInLieu", "carteCommon", "carteFilter", "carteHiddenPaid", "carteActive")


def harness(js: str) -> str:
    return STUBS + "\n".join(top(js, n) for n in NAMES) + "\n"


def crafted() -> list:
    base = {"ville": "Lyon", "lat": None, "lon": None, "academie": "Lyon", "internat": "non", "distance": None, "select_form": None}
    rows = [
        {"cod_aff_form": "1", "etablissement": "Lycée A", "formation": "BTS - Management commercial opérationnel", "stats": True,
         "statut": "public", "initiale": True, "apprentissage": False},
        {"cod_aff_form": "2", "etablissement": "CFA B", "formation": "BTS - Management commercial opérationnel - en apprentissage",
         "stats": False, "statut": "prive_app", "initiale": False, "apprentissage": True},
        {"cod_aff_form": "3", "etablissement": "CFA C", "formation": "BTS - Négociation et digitalisation de la relation client",
         "stats": False, "statut": "contrat", "initiale": False, "apprentissage": True, "internat": "mixte"},
        {"cod_aff_form": "4", "etablissement": "École D", "formation": "Bachelor - commerce", "stats": True, "statut": "prive",
         "initiale": True, "apprentissage": False},
        {"cod_aff_form": "5", "etablissement": "École E", "formation": "Ecole de commerce - Programme Grande Ecole", "stats": True,
         "statut": "prive", "initiale": True, "apprentissage": True},
        {"cod_aff_form": "6", "etablissement": HOSTILE, "formation": "BTS - Métiers du multimédia et de l'internet", "stats": False,
         "statut": "public", "initiale": False, "apprentissage": True},
        {"cod_aff_form": "7", "etablissement": "Lycée F", "formation": "Licence - Droit", "stats": True, "statut": "contrat",
         "initiale": True, "apprentissage": False, "zone": "cible"},
    ]
    return [{**base, **r} for r in rows]


KWS = [  # (name, codes the engine gave, terms, apprenticeship flag[, internat option])
    ("mco", ["1"], [[" bts "], [" mco ", " management commercial operationnel "]], False),
    ("ndrc", [], [[" ndrc ", " negociation et digitalisation "]], False),
    ("inside", [], [[" ion "]], False),
    ("free", [], [["multimed"]], False),
    ("app-only", ["1", "4", "5"], [], True),
    ("app-bts", ["1"], [[" bts "]], True),
    ("code", ["4"], [], False),
    ("internet", [], [[" l internet "]], False),
    ("none", [], [["zzz"]], False),
    ("internat-bts", [], [[" bts "]], False, True),
    ("internat-all", ["1", "4"], [], False, True),
]


def twin_prog() -> str:
    return """
const D = JSON.parse(require('fs').readFileSync(0, 'utf8')); const out = {};
for (const [name, codes, terms, app, internat] of D.kws) {
  const kw = { codes: new Set(codes), terms, app, internat: !!internat, words: [] };
  out[name] = D.rows.filter((f) => carteCommon(f, { lieu: null, autour: null }, kw)).map((f) => f.cod_aff_form);
}
process.stdout.write(JSON.stringify(out));"""


def twin_ok(c: Ctx, js: str | None = None) -> tuple[bool, str]:
    js = c.js if js is None else js
    rows, bad = crafted(), []
    try:
        got = node(harness(js) + twin_prog(), {"rows": rows, "kws": KWS})
    except Exception as e:  # noqa: BLE001
        return False, f"the page's twin does not run: {str(e)[:300]}"
    if got is None:
        return True, "skipped (node not installed)"
    for name, codes, terms, app, *opt in KWS:
        want = offer_hits(rows, terms, app, set(codes), bool(opt and opt[0]))
        if got[name] != want:
            bad.append((name, got[name], want))
    # the keyword answer's terms and flag reach the page; an older answer without terms falls back on the typed words
    if not re.search(r"terms: Array\.isArray\(d\.terms\) \? d\.terms : kwWords\(q\)\.map\(\(w\) => \[w\]\), app: !!d\.apprentissage, internat: !!d\.internat", js):
        bad.append("kwLoad does not read terms / apprentissage / internat")
    # the page's internat values = the engine's option, read from search.py's own OPTIONS
    eng = re.search(r'"internat": lambda x: x\.get\("internat"\) in \(([^)]*)\)', c.search_src)
    page = re.search(r"const KW_INTERNAT = \[([^\]]*)\];", js)
    if not eng or not page or sorted(re.findall(r'"(\w+)"', eng.group(1))) != sorted(re.findall(r'"(\w+)"', page.group(1))) \
            or sorted(INTERNAT_OK) != sorted(re.findall(r'"(\w+)"', eng.group(1))):
        bad.append("KW_INTERNAT is not the engine's internat option")
    from suptracker import api
    if c.con.execute("SELECT count(*) FROM core.formation_year").fetchone()[0]:
        if not api.keyword_codes(c.con.cursor(), "prépa avec internat").get("internat") or api.keyword_codes(c.con.cursor(), "prépa").get("internat"):
            bad.append("the keyword answer's internat flag")
    return not bad, f"{len(KWS)} keywords x {len(rows)} rows = the Python reading; problems {bad[:3]}"


@check("MQ2 the page's twin: carteOfferMatch and carteCommon (Node) = the Python reading on crafted rows; kwLoad reads terms and flag")
def mq2(c: Ctx):
    return twin_ok(c)


# ------------------------------------------------------------------ MQ3 apprenticeship as an option
def app_ok(c: Ctx, src: str | None = None, js: str | None = None, note: str | None = None) -> tuple[bool, str]:
    src = c.search_src if src is None else src
    js = c.js if js is None else js
    note = S.APPRENTICESHIP_NOTE if note is None else note
    bad = []
    from suptracker import api
    for q in ("bts alternance", "apprentissage lyon", "BUT informatique en apprentissage", "apprentissage"):
        r = S.search(c.con.cursor(), q, limit=5)
        kc = api.keyword_codes(c.con.cursor(), q)
        if not r.get("apprentissage") or not kc.get("apprentissage"):
            bad.append((q, "the flag is not set"))
        # an unrelated word the warehouse lacks may still be « ignoré » (the synthetic one has no BUT informatique); the
        # apprenticeship words never
        if {"type": "option", "value": "apprentissage"} not in r["interpretation"] or any(
                i["type"] == "ignoré" and re.search(r"apprenti|alternan", i["value"]) for i in r["interpretation"]):
            bad.append((q, "not read as an option", r["interpretation"]))
        if note not in r["notes"]:
            bad.append((q, "no note"))
        if q != "apprentissage" and not r["results"]:
            bad.append((q, "no result"))
    for q in ("bts", "droit lyon"):
        if api.keyword_codes(c.con.cursor(), q).get("apprentissage"):
            bad.append((q, "flag set without the word"))
    if "statut scolaire" in note or "statut scolaire" in js or re.search(r"statut scolaire", src):
        bad.append("« statut scolaire » is back")
    if not re.search(r"Apprentissage : .{0,200}cartographie Parcoursup", note):
        bad.append(("the note does not say where they come from", note[:120]))
    if len(max(re.split(r"(?<=[.!?])\s+", note), key=lambda x: len(x.split())).split()) > 30:
        bad.append("a note sentence over 30 words")
    if "&& (!kw || !kw.app || !!f.apprentissage)" not in js:
        bad.append("the page does not keep apprenticeship formations only")
    if "Les offres en apprentissage listées à part viennent de la cartographie Parcoursup" not in js:
        bad.append("the filter bar's note is not the corrected one")
    return not bad, f"4 apprenticeship queries read as an option; problems {bad[:4]}"


@check("MQ3 apprenticeship is an option, never « Ignoré »: stripped, flagged, kept by the page; the note is true, no « statut scolaire »")
def mq3(c: Ctx):
    return app_ok(c)


# ------------------------------------------------------------------ MQ4 hidden paid formations
PAID_PROG = """
const D = JSON.parse(require('fs').readFileSync(0, 'utf8')); const out = [];
for (const [statut, kwd] of D.cases) {
  const F = { statut, lieu: null, autour: null, zones: [] };
  const kw = kwd ? { codes: new Set(kwd[0]), terms: kwd[1], app: kwd[2], internat: !!kwd[3], words: [] } : null;
  out.push(carteHiddenPaid(D.rows, F, kw));
}
process.stdout.write(JSON.stringify(out));"""


def py_hidden(rows, statut, kwd) -> int:
    if not statut or "prive" in statut:
        return 0
    paid = [f for f in rows if f.get("statut") == "prive"]
    if kwd is None:
        return len(paid)
    return len(offer_hits(paid, kwd[1], kwd[2], set(kwd[0]), bool(kwd[3]) if len(kwd) > 3 else False))


def paid_ok(c: Ctx, js: str | None = None) -> tuple[bool, str]:
    js = c.js if js is None else js
    bad = []
    D = ["public", "contrat", "prive_app"]
    cases = [(D, None), (D, [["4", "5"], [], False]), ([], None), (D + ["prive"], None), (["public"], [["1", "5"], [], True]),
             (D, [["1"], [[" bts "]], False])]
    rows = crafted()
    try:
        got = node(harness(js) + PAID_PROG, {"rows": rows, "cases": cases})
    except Exception as e:  # noqa: BLE001
        return False, f"carteHiddenPaid does not run: {str(e)[:300]}"
    if got is None:
        return True, "skipped (node not installed)"
    want = [py_hidden(rows, s, k) for s, k in cases]
    if got != want:
        bad.append(("crafted", got, want))
    real = []
    if c.real:
        from suptracker import api
        cases = []
        for q in ("école de commerce Lyon", "BTS MCO", "infirmier Marseille", "droit"):
            d = api.keyword_codes(c.con.cursor(), q)
            cases.append((D, [d["codes"], d["terms"], d["apprentissage"], d["internat"]]))
        got = node(harness(js) + PAID_PROG, {"rows": c.rows, "cases": cases})
        want = [py_hidden(c.rows, s, k) for s, k in cases]
        real = list(zip(("école de commerce Lyon", "BTS MCO", "infirmier Marseille", "droit"), got))
        if got != want or not got[0]:
            bad.append(("real layer", got, want))
    # the line: its count, the owner's words, a button that ticks the paid box and saves
    if not re.search(r"d'établissements privés payants \$\{paid > 1 \? \"masquées\" : \"masquée\"\} — <button type=\"button\" class=\"linkish\" id=\"cs-paid\" data-show-paid>les afficher</button>", js):
        bad.append("the line « N … masquées — les afficher » is not drawn")
    # audit PR 8: one handler for this button and the paid-only message's (showPaid), bound to every [data-show-paid]
    if 'showPaid = () => { F.statut = [...new Set([...F.statut, "prive"])]; save(); };' not in js \
            or 'document.querySelectorAll("[data-show-paid]").forEach((pb) => { pb.onclick = showPaid; });' not in js:
        bad.append("« les afficher » does not tick the paid box")
    if "const paid = carteHiddenPaid(shown(), F, kw)," not in js:
        bad.append("the count is not the shown rows' (the other criteria applied)")
    if 'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };' not in js:
        bad.append("the paid box is ticked by default (Plan B's rule)")
    return not bad, f"crafted {got if not c.real else 'ok'}; real {real}; problems {bad[:3]}"


@check("MQ4 hidden paid formations counted (Node = Python, crafted and real) and offered: « N … masquées — les afficher » ticks the box")
def mq4(c: Ctx):
    return paid_ok(c)


# ------------------------------------------------------------------ MQ5 filters kept from an earlier visit
ACTIVE_PROG = """
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
CARTE_ACADS.push("Lyon", "Paris");
process.stdout.write(JSON.stringify(D.map((F) => carteActive(F))));"""


def restored_ok(c: Ctx, js: str | None = None) -> tuple[bool, str]:
    js = c.js if js is None else js
    bad = []
    D = ["public", "contrat", "prive_app"]
    Fs = [{"statut": D, "zones": []}, {"statut": D, "zones": ["cible"]}, {"statut": ["public"], "zones": [], "internat": ["mixte"]},
          {"statut": D + ["prive"], "zones": ["securite"], "acad": ["Lyon"]}, {"statut": [], "zones": []}]
    want = [[], ["Votre zone"], ["Types d'établissement", "Internat"], ["Votre zone", "Types d'établissement", "Académie"], ["Types d'établissement"]]
    try:
        got = node(harness(js) + ACTIVE_PROG, Fs)
    except Exception as e:  # noqa: BLE001
        return False, f"carteActive does not run: {str(e)[:300]}"
    if got is not None and got != want:
        bad.append(("carteActive", got, want))
    needs = {
        "on entering only": 'const fresh = $view.dataset.rendered !== "carte";',
        "never for a shared link": "if (fresh) carteUI.restored = shareRaw != null ? [] : carteRestored(F);",
        "any change clears it": 'function save(repanel = true) { carteUI.restored = []; store.set("carteFiltres2", F);',
        "the notice and its reset": "Filtres gardés de votre dernière visite : ${esc(carteUI.restored.join(\", \"))}. <button type=\"button\" class=\"linkish\" data-reset-filters>Réinitialiser les filtres</button>",
        "no result names the filters": "Aucune formation ne correspond.${carteActive(F).length ? ` Filtres actifs : ${esc(carteActive(F).join(\", \"))}.",
        "one reset for both": 'document.querySelectorAll("#cs-status [data-reset-filters]").forEach((b) => { b.onclick = resetFilters; });',
        "the bar's reset is the same": "if (rs) rs.onclick = resetFilters;",
        "the reset clears the notice": "F.zones = []; carteUI.open = null; carteUI.restored = [];",
        "draw never writes into a page that is gone": 'if (seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("cs-status")) return;',
        "panel neither": 'if (seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("cfilters")) return;',
        "Leaflet loaded once": "carteUI.leafletP = carteUI.leafletP || Promise.all([",
        "only valid map bounds restored, as numbers": "if (carteUI.type === type && Array.isArray(carteUI.bounds) && carteUI.bounds.flat().every(Number.isFinite)) carteUI.map.fitBounds(carteUI.bounds);",
        "only valid map bounds kept, as numbers": "if (bb.isValid()) { const sw = bb.getSouthWest(), ne = bb.getNorthEast(); carteUI.bounds = [[sw.lat, sw.lng], [ne.lat, ne.lng]]; }",
        "a left map's moves ignored": 'if (map !== carteUI.map || seq !== carteUI.seq || $view.dataset.rendered !== "carte") return;   // a map the page left',
    }
    for k, v in needs.items():
        if v not in js:
            bad.append(k)
    return not bad, f"{len(Fs)} filter sets named as expected; problems {bad[:4]}"


@check("MQ5 filters kept from an earlier visit named on entering (never for a shared link), cleared by a change or the reset; no result names them")
def mq5(c: Ctx):
    return restored_ok(c)


# ------------------------------------------------------------------ MQ6 browser
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2], errs = [], o = {};
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errs.push(String(e)));
  const count = async () => { await p.waitForFunction(() => /formation/.test(document.getElementById('carte-count')?.textContent || ''), null, { timeout: 120000 });
    return Number((document.getElementById('carte-count')?.textContent || '').replace(/\s/g, '').match(/^(\d+)/)?.[1] ?? -1); };
  const num = async () => p.evaluate(() => Number((document.getElementById('carte-count').textContent || '').replace(/[\s ]/g, '').match(/^(\d+)/)[1]));
  const search = async (q, lieu) => {
    await p.fill('#cs-q', q); await p.fill('#cs-lieu', lieu || '');
    await p.click('.cs-go'); await p.waitForTimeout(400);
    await p.waitForFunction((q) => document.getElementById('cs-q')?.value === q && /formation/.test(document.getElementById('carte-count')?.textContent || ''), q, { timeout: 120000 });
    await p.waitForTimeout(800);
  };
  global.STEP = "await p.goto(base + '/#/carte'";
  await p.goto(base + '/#/carte'); await p.evaluate(() => localStorage.clear()); await p.goto(base + '/#/accueil'); await p.goto(base + '/#/carte');
  await p.waitForSelector('#cs-q', { timeout: 120000 }); await p.waitForTimeout(1500);
  global.STEP = "await search('école de commerc";
  await search('école de commerce', 'Académie de Lyon');
  o.before = await num();
  o.paidLine = await p.evaluate(() => document.querySelector('.cs-paid')?.textContent || '');
  if (o.paidLine) { await p.click('#cs-paid'); await p.waitForTimeout(1200); }
  o.after = await num();
  o.paidAfter = await p.evaluate(() => !!document.querySelector('.cs-paid'));
  global.STEP = "await search('BTS MCO', ''); o";
  await search('BTS MCO', ''); o.mco = await num();
  await search('BTS management commercial opérationnel', ''); o.full = await num();
  await search('bts alternance', ''); o.app = await p.evaluate(() => [document.getElementById('cs-status').textContent, document.getElementById('carte-count').textContent]);
  global.STEP = '// a filter kept from an earli';
  // a filter kept from an earlier visit: named on entering, cleared by the reset
  // leaving right after a search (the map's animated zoom ends on another page): never a JS error (audit testers, twice)
  global.STEP = 'leave during a search';
  for (let i = 0; i < 4; i++) {
    await p.fill('#cs-q', i % 2 ? 'BTS MCO' : 'licence droit'); await p.click('.cs-go'); await p.waitForTimeout(150 + 100 * i);
    await p.evaluate(() => { location.hash = '#/accueil'; }); await p.waitForTimeout(900);
    await p.evaluate(() => { location.hash = '#/carte'; });
    try { await p.waitForSelector('#cs-q', { timeout: 120000 }); }
    catch (e) { throw new Error('the page did not come back: ' + JSON.stringify(await p.evaluate(() => [location.hash, document.getElementById('view')?.dataset.rendered, (document.getElementById('view')?.innerText || '').slice(0, 200)])) + ' errors ' + JSON.stringify(errs.slice(0, 2))); }
    await p.waitForTimeout(600);
  }
  o.raceErrs = errs.length;
  // the next visit: a new page load with the filters an earlier visit stored
  global.STEP = 'kept filters';
  await p.evaluate(() => localStorage.setItem('carteFiltres2', JSON.stringify({ statut: ['public'], internat: ['mixte'], q: '' })));
  await p.reload();
  await p.waitForSelector('#cs-q', { timeout: 120000 }); await p.waitForTimeout(2500);
  o.restored = await p.evaluate(() => document.querySelector('.cs-restored')?.textContent || '');
  const rb = await p.$('.cs-restored [data-reset-filters]');
  if (rb) { await rb.click(); await p.waitForTimeout(2500); }
  o.restoredAfter = await p.evaluate(() => document.querySelector('.cs-restored')?.textContent || '');
  o.stored = await p.evaluate(() => JSON.parse(localStorage.getItem('carteFiltres2') || '{}').statut || null);
  o.hs = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  global.STEP = 'const ph = await b.newContext(';
  const ph = await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  const q = await ph.newPage(); q.on('pageerror', (e) => errs.push(String(e)));
  await q.goto(base + '/#/carte'); await q.waitForSelector('#cs-q', { timeout: 120000 }); await q.waitForTimeout(1500);
  await q.fill('#cs-q', 'école de commerce'); await q.fill('#cs-lieu', 'Académie de Lyon'); await q.click('.cs-go'); await q.waitForTimeout(3000);
  o.phonePaid = await q.evaluate(() => !!document.querySelector('.cs-paid'));
  o.phoneHs = await q.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await b.close();
  process.stdout.write(JSON.stringify({ o, errs }));
})().catch((e) => { console.error('step ' + (global.STEP || '?') + ': ' + String(e).slice(0, 300)); process.exit(1); });
"""


def py_count(c: Ctx, q: str, acad=None, statut=("public", "contrat", "prive_app")) -> int:
    from suptracker import api
    d = api.keyword_codes(c.con.cursor(), q)
    rows = [f for f in c.rows if f.get("statut") in statut and (not acad or f.get("academie") == acad)]
    return len(offer_hits(rows, d["terms"], d["apprentissage"], set(d["codes"]), d["internat"]))


@check("MQ6 browser: the paid line with the Python count and its button, a stored filter named then reset, BTS MCO = its title; no error")
def mq6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT),
                           env={**os.environ, "SUPTRACKER_DB": str(c.db)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".masque_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}"], capture_output=True, text=True, timeout=900, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-800:]
    d = json.loads(r.stdout)
    o, bad = d["o"], []
    acad = "Lyon"
    shown = py_count(c, "école de commerce", acad)
    every = py_count(c, "école de commerce", acad, ("public", "contrat", "prive_app", "prive"))
    hidden = every - shown
    m = re.match(r"\s*([\d\s ]+)", o["paidLine"] or "")
    n = int(re.sub(r"\D", "", m.group(1))) if m else None
    if o["before"] != shown or n != hidden or not hidden or o["after"] != every or o["paidAfter"]:
        bad.append(("paid line", o["before"], shown, o["paidLine"][:80], hidden, o["after"], every))
    every_mco = py_count(c, "BTS MCO", None, ("public", "contrat", "prive_app", "prive"))     # the paid box is ticked by now
    if o["mco"] != o["full"] or o["mco"] != every_mco:
        bad.append(("acronym", o["mco"], o["full"], every_mco))
    st, cnt = o["app"]
    if "Option : apprentissage" not in st or "Ignoré" in st or "statut scolaire" in st:
        bad.append(("apprenticeship", st[:200]))
    if "Types d'établissement" not in o["restored"] or "Internat" not in o["restored"] or o["restoredAfter"] or o["stored"] != ["public", "contrat", "prive_app"]:
        bad.append(("restored filters", o["restored"], o["restoredAfter"], o["stored"]))
    if o.get("raceErrs"):
        bad.append(("a JS error after leaving during a search", d["errs"][:2]))
    if not o["phonePaid"] or o["phoneHs"] or o["hs"] or d["errs"]:
        bad.append(("phone, scroll or JS errors", o["phonePaid"], o["phoneHs"], o["hs"], d["errs"][:2]))
    return not bad, f"école de commerce (académie de Lyon): {shown} shown, {hidden} hidden; BTS MCO {o['mco']} = title {o['full']}; problems {bad[:3]}"


# ------------------------------------------------------------------ MQ8 wiring and docs
def docs_ok(c: Ctx, readme: str | None = None, claude: str | None = None, nightly: str | None = None) -> tuple[bool, str]:
    readme = c.readme if readme is None else readme
    claude = c.claude if claude is None else claude
    nightly = c.nightly if nightly is None else nightly
    bad = []
    if "## Nothing hidden without saying so (audit PR 4" not in readme:
        bad.append("README section")
    if "**Nothing hidden without saying so (audit PR 4" not in claude or "redteam_masque.py" not in claude:
        bad.append("CLAUDE.md rule")
    if not (ROOT / "tests" / "test_masque.py").exists() or '"tests/test_masque.py"' not in c.durations:
        bad.append("test file or its CI duration")
    if '"masque": ("MQ6",)' not in nightly:
        bad.append("nightly browser suite")
    return not bad, f"problems {bad}"


@check("MQ8 wiring and docs: README section, CLAUDE.md rule, test file and its duration, nightly browser suite")
def mq8(c: Ctx):
    return docs_ok(c)


# ------------------------------------------------------------------ MQ7 mutation test
@check("MQ7 mutation test: offer terms, page twin, apprenticeship option, hidden paid line, kept filters and docs bugs are each caught")
def mq7(c: Ctx):
    caught, missed = 0, []
    if node("process.stdout.write('1')") is None:
        return True, "skipped (node not installed)"

    def js_mut(name, old, new, fn):
        nonlocal caught
        if old not in c.js:
            missed.append(f"{name} (anchor lost)")
            return
        ok, _ = fn(c.js.replace(old, new, 1))
        if ok:
            missed.append(name)
        else:
            caught += 1

    T = lambda j: twin_ok(c, j)            # noqa: E731
    P = lambda j: paid_ok(c, j)            # noqa: E731
    R = lambda j: restored_ok(c, j)        # noqa: E731
    A = lambda j: app_ok(c, js=j)          # noqa: E731
    js_mut("offers matched on any word", "kw.terms.every((alts) =>", "kw.terms.some((alts) =>", T)
    js_mut("acronym labels ignored", "alts.some((a) => ` ${carteText(f)} `.includes(a))", "` ${carteText(f)} `.includes(alts[0])", T)
    js_mut("apprenticeship-only query keeps no offer", ": kw.app;\n// Codex (PR #111)", ": false;\n// Codex (PR #111)", T)
    js_mut("apprenticeship option not applied", "&& (!kw || !kw.app || !!f.apprentissage)", "", T)
    js_mut("acronyms matched inside words", "alts.some((a) => ` ${carteText(f)} `.includes(a))", "alts.some((a) => carteText(f).includes(a.trim()))", T)
    js_mut("punctuation kept in names", '.replace(/[^a-z0-9]+/g, " ");   // punctuation', ';   // punctuation', T)
    js_mut("internat option not applied to offers", "  && (!kw || !kw.internat || KW_INTERNAT.includes(f.internat))\n", "", T)
    js_mut("internat values drift", 'const KW_INTERNAT = ["mixte", "filles", "garcons", "oui"];', 'const KW_INTERNAT = ["mixte", "oui", "non"];', T)
    js_mut("kwLoad drops the terms", "terms: Array.isArray(d.terms) ? d.terms :", "terms: [] || ", T)
    js_mut("hidden count ignores the keyword", "{ ...F, statut: [] }, undefined, kw).length", "{ ...F, statut: [] }, undefined, null).length", P)
    js_mut("hidden count with paid ticked", '|| F.statut.includes("prive")) return 0;', ") return 0;", P)
    js_mut("paid line without its button", 'masquée"} — <button type="button" class="linkish" id="cs-paid" data-show-paid>les afficher</button>', 'masquée"}', P)
    js_mut("button does not tick the box", '[...new Set([...F.statut, "prive"])]', "[...F.statut]", P)
    js_mut("paid ticked by default", 'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };',
           'const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app", "prive"] };', P)
    js_mut("zone filter not named", 'return (F.zones || []).length ? ["Votre zone", ...out] : out;', "return out;", R)
    js_mut("notice for a shared link", "carteUI.restored = shareRaw != null ? [] : carteRestored(F);", "carteUI.restored = carteRestored(F);", R)
    js_mut("notice never cleared", "function save(repanel = true) { carteUI.restored = []; ", "function save(repanel = true) { ", R)
    js_mut("no result says nothing of the filters", ' Filtres actifs : ${esc(carteActive(F).join(", "))}.', "", R)
    js_mut("draw after the page is gone", 'if (seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("cs-status")) return;', "", R)
    js_mut("Leaflet loaded at every opening", "carteUI.leafletP = carteUI.leafletP || Promise.all([", "carteUI.leafletP = Promise.all([", R)
    js_mut("bounds restored unchecked", "Array.isArray(carteUI.bounds) && carteUI.bounds.flat().every(Number.isFinite)) carteUI.map", "carteUI.bounds) carteUI.map", R)
    js_mut("Leaflet's own bounds object kept", "{ const sw = bb.getSouthWest(), ne = bb.getNorthEast(); carteUI.bounds = [[sw.lat, sw.lng], [ne.lat, ne.lng]]; }", "carteUI.bounds = bb;", R)
    js_mut("statut scolaire back", "Les offres en apprentissage listées à part viennent de la cartographie Parcoursup",
           "Les résultats sont des formations sous statut scolaire. Les offres en apprentissage viennent de la cartographie Parcoursup", A)
    # the engine
    real_terms = S.offer_terms

    def fuzzy(q):
        return [alts + [alts[0][:-1]] for alts in real_terms(q)]

    def keeps_app(q):
        return [[w] for w in fold(q).split() if len(w) > 1]

    def drops_tags(q):
        return [[alts[0]] for alts in real_terms(q)]
    for name, fn in (("a fuzzy alternative", fuzzy), ("apprenticeship and stop words kept", keeps_app), ("tag labels dropped", drops_tags)):
        ok, _ = terms_ok(c, fn)
        if ok:
            missed.append(name)
        else:
            caught += 1
    for name, note in (("the old note", "Les résultats ci-dessous sont des formations sous statut scolaire."),
                       ("a note without its source", "Apprentissage : ces formations sont à part.")):
        ok, _ = app_ok(c, note=note)
        if ok:
            missed.append(name)
        else:
            caught += 1
    for name, kw in (("README", {"readme": ""}), ("CLAUDE.md", {"claude": ""}), ("nightly", {"nightly": ""})):
        ok, _ = docs_ok(c, **kw)
        if ok:
            missed.append(name)
        else:
            caught += 1
    total = caught + len(missed)
    return not missed, f"mutants caught {caught}/{total}; missed {missed}"


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
