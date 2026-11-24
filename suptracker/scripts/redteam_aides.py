"""Red team, sprint F "Financer ses études" (owner, 2026-11-15): student aids read from the official pages, in the cost tab.

  AI1 official pages (data/aides, always committed): every item is read (empty audit) and equals an INDEPENDENT re-reading
      written here (own patterns over the whole text: the 8 échelons, the overseas majoration, the instalments, the mérite's
      900 = 10 x 90, the mobility's 500, the year's national tariffs, the CVEC, the Crous meal); the two official sources
      agree (service-public and etudiant.gouv.fr: mérite and mobility amounts); every link is https on an official host.
  AI2 changed pages: a page whose table loses a row, whose amounts stop increasing, whose mérite no longer multiplies, whose
      two mobility amounts disagree, whose simulator link points elsewhere, or that is missing, leaves its item out and names
      it in the audit (never a typed fallback). The fetcher keeps official hosts only and refuses a redirect elsewhere.
  AI3 per formation (fixture warehouse): the fixed rules re-derived: fees exempt only for a PUBLIC establishment whose fee is 0
      or a national tariff of the year; private and unknown fees kept; IFSI/EFTS get the Region's statement and no Crous table;
      an overseas formation gets the majoration on every échelon; the boursier's year = round10(10 x monthly + kept fee), the
      CVEC never counted, none without the cost card's year.
  AI4 page (node): aidesCard and aidesHint escape every stored string, label the computed year, keep links https + noopener,
      never compute an échelon or promise an aid, send nothing (no api call), and read the profile only in the browser
      (mention très bien, same / other académie, bac pro from Île-de-France).
  AI5 cost card coherence: vie.py's CVEC amount and year and its Crous meal (price, date, link) equal the official pages; the
      cost card no longer links the gone meal page or an unverified CAF address.
  AI6 real warehouse (--real, when built): core.aides equals the reading of data/aides (no stale warehouse), and the rules hold
      on a sample of real formations.
  AI7 plumbing: workflow (official hosts, request on a claude/ branch), build, API, fingerprint, source register, docs, tests.
  AI8 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"
DIR = ROOT / "data" / "aides"
OFFICIAL = re.compile(r"^https://(www\.)?(service-public\.gouv\.fr|etudiant\.gouv\.fr|cvec\.etudiant\.gouv\.fr|messervices\.etudiant\.gouv\.fr|"
                      r"legifrance\.gouv\.fr|parcoursup\.gouv\.fr|enseignementsup-recherche\.gouv\.fr)/")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def load(path: Path, name: str, src: str):
    m = types.ModuleType(name)
    m.__file__, m.__package__ = str(path), "suptracker"
    exec(compile(src, str(path), "exec"), m.__dict__)
    return m


class Ctx:
    def __init__(self, db: Path | None = None, real: bool = False):
        self.db = db if db and db.exists() else None
        self.real = real
        self.src = {k: (ROOT / "suptracker" / f"{f}.py").read_text() for k, f in (("ai", "aides"), ("vie", "vie"), ("build", "build"))}
        self.src["fetch"] = (ROOT / "scripts" / "aides_fetch.py").read_text()
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def mod(self, k: str = "ai"):
        import suptracker  # noqa: F401  (the package, for the relative imports)
        if k == "fetch":
            return load(ROOT / "scripts" / "aides_fetch.py", "aides_fetch_rt", self.src["fetch"])
        name = {"ai": "aides", "vie": "vie"}[k]
        return load(ROOT / "suptracker" / f"{name}.py", f"suptracker.{name}_rt", self.src[k])


def page(url_key: str, ext: str = ".txt") -> Path:
    from suptracker import aides
    return DIR / aides._file(aides.PAGES[url_key], ext)


def num(s: str) -> int:
    return int(re.sub(r"\s", "", s))


def reread() -> dict:
    """An independent reading of the official pages (own patterns, whole-text searches)."""
    out = {}
    t = page("bourse").read_text()
    blk = t[t.index("Tableau - Montant "): t.index("À savoir", t.index("Tableau - Montant "))]
    out["annee"] = re.search(r"Montant (\d{4}-\d{4})", blk).group(1)
    out["echelons"] = [(e, num(v)) for e, v in re.findall(r"^(0 bis|[1-7])\n([\d ]+) €$", blk, flags=re.M)]
    out["outre_mer"] = num(re.search(r"majorés de ([\d ]+) €", t).group(1))
    out["mensualites"] = int(re.search(r"en (\d+) mensualités", t).group(1))
    t = page("merite").read_text()
    out["merite"] = (num(re.search(r"annuel de l'aide est de ([\d ]+) €", t).group(1)),
                     *map(int, re.search(r"en (\d+) mensualités de (\d+) €", t).groups()))
    t = page("mobilite").read_text()
    out["mobilite"] = {num(x) for x in re.findall(r"montant (?:de l'aide )?est de ([\d ]+) €", t)}
    t = page("mobilite_mesr").read_text()
    out["mobilite_mesr"] = num(re.search(r"aide financière de ([\d ]+) €", t).group(1))
    t = (DIR / "www.etudiant.gouv.fr_fr_aide-au-merite-1291.txt").read_text()          # the ministry's own page
    out["merite_mesr"] = num(re.search(r"Son montant, pour l'année [\d/]+ est de ([\d ]+) €", t).group(1))
    t = page("droits").read_text()
    tables = re.findall(r"Tableau - Montant des droits d'inscription.*?(?=\nTableau - |\nÀ savoir|\nExonération)", t, flags=re.S)
    out["tarifs"] = sorted({num(x) for b in tables for x in re.findall(r"^([\d ]+) €$", b, flags=re.M)})
    out["droits_annee"] = re.search(r"Frais d'inscription pour l'année (\S+)", t).group(1)
    t = page("cvec").read_text()
    m = re.search(r"année universitaire (\d{4}-\d{4})\. Elle est de (\d+) €", t)
    out["cvec"] = (m.group(1), int(m.group(2)))
    t = page("repas").read_text()
    m = re.search(r"À partir du ([^,]+), l.Etat propose un repas[^\n]*?à hauteur de (\d+) €", t)
    out["repas"] = (m.group(1), int(m.group(2)))
    return out


# ---------------------------------------------------------------- AI1

@check("AI1 official pages: every item read, equal to an independent re-reading, two official sources agree, official links only")
def ai1(c: Ctx):
    A = c.mod().read(DIR)
    bad = list(A["audit"])
    try:
        R = reread()
    except Exception as e:  # noqa: BLE001
        return False, f"the independent re-reading fails: {type(e).__name__} {e}"
    b = A.get("bourse") or {}
    if [(e["echelon"], e["annuel"]) for e in b.get("echelons", [])] != R["echelons"] or len(R["echelons"]) != 8:
        bad.append(f"échelons {b.get('echelons')} vs {R['echelons']}")
    if b.get("annee") != R["annee"] or b.get("outre_mer") != R["outre_mer"] or b.get("mensualites") != R["mensualites"]:
        bad.append("bourse year, majoration or instalments differ")
    if any(abs(e["mensuel"] - e["annuel"] / R["mensualites"]) > 0.005 for e in b.get("echelons", [])):
        bad.append("monthly amount is not annual / instalments")
    m = A.get("merite") or {}
    if (m.get("montant"), m.get("mensualites"), m.get("par_mois")) != R["merite"] or R["merite"][0] != R["merite"][1] * R["merite"][2]:
        bad.append(f"mérite {m} vs {R['merite']}")
    if m.get("montant") != R["merite_mesr"]:
        bad.append("service-public and etudiant.gouv.fr disagree on the mérite amount")
    mo = A.get("mobilite") or {}
    if {mo.get("montant")} != R["mobilite"] or mo.get("montant") != R["mobilite_mesr"]:
        bad.append(f"mobility {mo.get('montant')} vs {R['mobilite']} / {R['mobilite_mesr']}")
    d = A.get("droits") or {}
    if d.get("tarifs") != R["tarifs"] or d.get("annee") != R["droits_annee"] or 178 not in R["tarifs"]:
        bad.append(f"national tariffs {d.get('tarifs')} vs {R['tarifs']}")
    cv = A.get("cvec") or {}
    if (cv.get("annee"), cv.get("montant")) != R["cvec"]:
        bad.append(f"CVEC {cv} vs {R['cvec']}")
    rp = A.get("repas") or {}
    if (rp.get("depuis"), rp.get("prix")) != R["repas"]:
        bad.append(f"meal {rp} vs {R['repas']}")
    links = [b.get("liens", {}).get("simulateur"), b.get("liens", {}).get("dse"), mo.get("lien"), cv.get("lien"),
             (A.get("logement") or {}).get("simulateur")] + [v.get("source") for v in A.values() if isinstance(v, dict) and v.get("source")]
    for u in links:
        if not u or not OFFICIAL.match(u):
            bad.append(f"link not official: {u}")
    for k in ("bourse", "merite", "mobilite", "droits", "logement"):
        if not re.fullmatch(r"\d{1,2} \w+ \d{4}", str((A.get(k) or {}).get("verifie"))):
            bad.append(f"{k}: no 'vérifié le' date")
    return not bad, f"{sum(1 for k in c.mod().RULES if A.get(k))} items; {bad[:4]}"


# ---------------------------------------------------------------- AI2

def tamper(d: Path, key: str, fn) -> None:
    from suptracker import aides
    f = d / aides._file(aides.PAGES[key])
    f.write_text(fn(f.read_text()))


@check("AI2 changed pages: a broken table, amount or link leaves the item out and names it; the fetcher keeps official hosts")
def ai2(c: Ctx):
    ai = c.mod()
    bad = []
    cases = [
        ("bourse", lambda t: t.replace("\n7\n6 335 €", "", 1), "a row lost"),
        ("bourse", lambda t: t.replace("\n5 506 €", "\n5 000 €", 1), "amounts no longer increase"),
        ("merite", lambda t: t.replace("10 mensualités de 90 €", "10 mensualités de 80 €"), "mérite no longer multiplies"),
        ("mobilite", lambda t: t.replace("Le montant de l'aide est de 500 €", "Le montant de l'aide est de 600 €"), "two mobility amounts"),
        ("droits", lambda t: t.replace("vous êtes exonérés des droits d'inscription", "vous pouvez demander"), "no exemption sentence"),
        ("cvec", lambda t: t.replace("Elle est de 105 €", "Elle est de"), "no CVEC amount"),
        ("regions", lambda t: t.replace("sont gérés par les régions", "sont gérés"), "no regions sentence"),
    ]
    for key, fn, why in cases:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for f in DIR.iterdir():
                shutil.copy(f, d / f.name)
            tamper(d, key, fn)
            A = ai.read(d)
            if A.get(key) is not None or not any(x.startswith(key + ":") for x in A["audit"]):
                bad.append(f"{key} ({why}): still read")
            if sum(1 for k in ai.RULES if A.get(k) is None) != 1:
                bad.append(f"{key} ({why}): another item was lost too")
    with tempfile.TemporaryDirectory() as tmp:          # the simulator link moved to a foreign host
        d = Path(tmp)
        for f in DIR.iterdir():
            shutil.copy(f, d / f.name)
        lf = d / ai._file(ai.PAGES["bourse"], ".links.json")
        lf.write_text(lf.read_text().replace("https://www.service-public.gouv.fr/particuliers/vosdroits/R18296", "https://simulateur.example.com/"))
        if ai.read(d).get("bourse") is not None:
            bad.append("a simulator link on a foreign host is kept")
        (d / ai._file(ai.PAGES["merite"])).unlink()
        A = ai.read(d)
        if A.get("merite") is not None or "merite: page not fetched" not in A["audit"]:
            bad.append("a missing page is not said")
    fe = c.mod("fetch")
    if not all(u.startswith("https://") and u.endswith(".gouv.fr/") for u in fe.ALLOWED) or any("example" in u for u in fe.ALLOWED):
        bad.append(f"fetcher hosts {fe.ALLOWED}")
    req = json.loads((DIR / "request.json").read_text())["urls"]
    if any(not u.startswith(fe.ALLOWED) for u in req):
        bad.append("a requested page is not on an official host")
    if "refused: redirected to" not in c.src["fetch"] or "not str(r.url).startswith(ALLOWED)" not in c.src["fetch"]:
        bad.append("the fetcher does not refuse a redirect to another host")
    t = fe.page_text(f"<p>a&nbsp;b</p><script>alert(1)</script><style>x{{}}</style><div>c {HOSTILE}</div>")
    if "alert(1)" in t.split("img")[0] or "x{}" in t or "a b" not in t:
        bad.append(f"page_text: {t!r}")
    L = fe.page_links('<a href="/R1">Calc</a><a href="javascript:x">j</a><a href="http://x.fr/">h</a>', "https://www.service-public.gouv.fr/p")
    if L != [["Calc", "https://www.service-public.gouv.fr/R1"]]:
        bad.append(f"page_links: {L}")
    return not bad, f"{len(cases) + 2} tampered pages; {bad[:4]}"


# ---------------------------------------------------------------- AI3

def fixture():
    import duckdb

    from suptracker import aides
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("""CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session INTEGER, fili VARCHAR, contrat_etab VARCHAR,
        dep VARCHAR, acad_mies VARCHAR)""")
    con.executemany("INSERT INTO core.formation_year VALUES (?, 2025, ?, ?, ?, ?)", [
        ("1", "Licence", "Public", "59", "Lille"), ("2", "Licence", "Public", "59", "Lille"),
        ("3", "BTS", "Privé sous contrat d'association", "69", "Lyon"), ("4", "Ecole de Commerce", "Privé enseignement supérieur", "75", "Paris"),
        ("5", "IFSI", "Public", "33", "Bordeaux"), ("6", "BUT", "Public", "974", "La Réunion"), ("7", "BTS", "Public", "62", "Lille"),
        ("8", "Licence", "Public", "59", "Lille"), ("9", "CPGE", "Privé sous contrat d'association", "59", "Lille")])
    aides.build(con, DIR)
    return con


def vie_of(fee, cvec=105, mmin=600, mmax=900, annuel=True):
    from suptracker.vie import MOIS_PAR_AN, _arrondi
    v = {"frais": {"montant": fee, "cvec": bool(cvec)}, "mensuel": {"min": mmin, "max": mmax}}
    v["annuel"] = {"min": _arrondi(MOIS_PAR_AN * mmin + (fee or 0) + cvec), "max": _arrondi(MOIS_PAR_AN * mmax + (fee or 0) + cvec),
                   "frais": fee or 0, "cvec": cvec} if annuel and fee is not None else None
    return v


@check("AI3 per formation: exemption only for a public establishment at a national tariff, Region for IFSI/EFTS, overseas majoration, boursier year")
def ai3(c: Ctx):
    ai = c.mod()
    con = fixture()
    nat = ai.national(con)
    tarifs = set(nat["droits"]["tarifs"])
    bad = []
    cases = {"1": (vie_of(178), True), "2": (vie_of(175), None), "3": (vie_of(1625, cvec=0), None), "4": (vie_of(9500, cvec=0), None),
             "6": (vie_of(178), True), "7": (vie_of(0, cvec=0), True), "8": (vie_of(178, annuel=False), True),
             "9": (vie_of(178), None)}                   # a PRIVATE establishment at a national-looking fee: kept
    for cod, (v, want) in cases.items():
        a = ai.for_formation(con, cod, v)
        if a["droits_exoneres"] is not want:
            bad.append(f"{cod}: exemption {a['droits_exoneres']} (want {want})")
        an, m = v["annuel"], v["mensuel"]
        if an:
            fee = 0 if want else v["frais"]["montant"]
            exp = {"min": round((10 * m["min"] + fee) / 10) * 10, "max": round((10 * m["max"] + fee) / 10) * 10}
            ab = a["annuel_boursier"] or {}
            if (ab.get("min"), ab.get("max")) != (exp["min"], exp["max"]):
                bad.append(f"{cod}: boursier year {ab} vs {exp}")
            if ab and (ab["min"] > an["min"] or ab["max"] > an["max"]):
                bad.append(f"{cod}: a boursier pays more than the cost card")
        elif a["annuel_boursier"] is not None:
            bad.append(f"{cod}: a boursier year without the cost card's year")
        if want and v["frais"]["montant"] not in tarifs | {0}:
            bad.append(f"{cod}: exempt with a fee that is no national tariff")
    a5 = ai.for_formation(con, "5", vie_of(178))
    if a5["bourse"] is not None or not a5["sanitaire_social"] or "régions" not in a5["sanitaire_social"]["texte"]:
        bad.append("IFSI: the Crous table is shown or the Region is not said")
    a6, a1 = ai.for_formation(con, "6", vie_of(178)), ai.for_formation(con, "1", vie_of(178))
    maj = nat["bourse"]["outre_mer"]
    if not a6["outre_mer"] or [e["annuel"] for e in a6["bourse"]["echelons"]] != [e["annuel"] + maj for e in a1["bourse"]["echelons"]]:
        bad.append("overseas: the majoration is not on every échelon")
    if a1["outre_mer"] or a1["bourse"]["echelons"] != nat["bourse"]["echelons"]:
        bad.append("mainland: the national table is changed")
    if a1["academie"] != "Lille" or ai.for_formation(con, "4", vie_of(9500))["statut"] != "prive":
        bad.append("académie or statut wrong")
    if ai.for_formation(con, "999", vie_of(178)) is not None:
        bad.append("a block for an unknown formation")
    return not bad, f"{len(cases) + 2} formations; {bad[:4]}"


# ---------------------------------------------------------------- AI4

def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^(?:const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        return ""
    if re.match(r"(?:const|let) ", js[m.start():]):
        end = m.start()
        while True:
            end = js.index("\n", end) + 1
            part = js[m.start():end]
            if part.count("{") == part.count("}") and part.count("(") == part.count(")") and part.rstrip().endswith(";"):
                return part
    return js[m.start(): js.find("\n}", m.start()) + 2]


def node(prog: str, data):
    import subprocess
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


STUB = """const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x) => (x === null || x === undefined ? "—" : Number(x).toLocaleString("fr-FR"));
const estimTag = (d) => `<span class="estim">estimation</span> ${esc(d || "")}`;
let PROFILE = null; let CALLS = 0;
const api = () => { CALLS++; return Promise.resolve({}); };
const bacProfile = () => PROFILE;
"""


@check("AI4 page: the card escapes, labels the computed year, safe official links, no échelon or promise, nothing sent, profile read here")
def ai4(c: Ctx):
    names = ("euros", "eurosRange", "euroMois", "aidesHint", "aidesCard")
    if not all(top(c.js, n) for n in names):
        return False, "a renderer is missing from app.js"
    defs = "\n".join(top(c.js, n) for n in names)
    con = fixture()
    ai = c.mod()
    a = ai.for_formation(con, "1", vie_of(178))
    a = json.loads(json.dumps(a).replace("Lille", "Lille " + HOSTILE))
    a["merite"]["conditions"][0] += " " + HOSTILE
    a["mobilite"]["complement_texte"] = (a["mobilite"].get("complement_texte") or "") + HOSTILE
    a["bourse"]["liens"]["simulateur"] = "javascript:alert(1)"
    prog = STUB + defs + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const out = [];
      out.push(aidesCard(D.a, D.v));
      PROFILE = { serie: "bg", mention: "tb", academie: "Paris " + D.h }; out.push(aidesCard(D.a, D.v));
      PROFILE = { serie: "bg", mention: "b", academie: D.a.academie }; out.push(aidesCard(D.a, D.v));
      PROFILE = { serie: "bp", mention: "ab", academie: "Créteil" }; out.push(aidesCard(D.a, D.v));
      PROFILE = { serie: "bp", mention: "ab", academie: "Créteil" }; out.push(aidesCard({ ...D.a, academie: "Versailles" }, D.v));
      PROFILE = null; out.push(aidesCard(D.ifsi, D.v)); out.push(aidesCard(null, D.v));
      PROFILE = { serie: "bg", mention: "ab", academie: "Créteil" }; out.push(aidesCard(D.a, D.v));
      out.push(String(CALLS));
      process.stdout.write(JSON.stringify(out));"""
    out = node(prog, {"a": a, "v": vie_of(178), "ifsi": ai.for_formation(con, "5", vie_of(178)), "h": HOSTILE})
    if out is None:
        return True, "node absent: not run"
    bad = []
    *cards, calls = out
    for i, h in enumerate(cards):
        if "<img" in h:
            bad.append(f"card {i}: unescaped")
        txt = re.sub(r"<[^>]+>", " ", h)
        if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt):
            bad.append(f"card {i}: tutoiement")
        if re.search(r"(?i)vous (?:aurez|recevrez|toucherez)|garanti(?!e? :)|votre échelon est|vos chances", txt):
            bad.append(f"card {i}: a promise or a computed échelon")
        for tag in re.findall(r"<a [^>]*>", h):
            href = re.search(r'href="([^"]*)"', tag)
            if href and not OFFICIAL.match(href.group(1)):
                bad.append(f"card {i}: link {href.group(1)[:30]}")
            if 'target="_blank"' in tag and "noopener" not in tag:
                bad.append(f"card {i}: no noopener")
    base, tb, same, bp_out, bp_in, ifsi, none, bg_idf = cards
    if calls != "0":
        bad.append("the card calls the site")
    if none:
        bad.append("a card with nothing to show")
    if 'class="estim"' not in base or "pas déduite" not in base:
        bad.append("the boursier year is not labelled as an estimation without the bourse")
    if "Rien n'est garanti" not in base or "simulateur officiel le calcule, pas ce site" not in base:
        bad.append("the card does not say aids are requested and the échelon is not computed here")
    hints = lambda h: h.split("aides-hints")[1].split("</ul>")[0] if "aides-hints" in h else ""      # noqa: E731
    if "mention très bien" not in hints(tb):
        bad.append("profile mention très bien: no hint")
    if "aides-hints" in base:
        bad.append("a profile hint without a profile")
    if "pas la vôtre" not in tb or "ne s'applique pas" not in same:
        bad.append("the académie hint is wrong")
    if "complément" not in hints(bp_out) or "complément de" in hints(bp_in) or "complément de" in hints(bg_idf):
        bad.append("the bac pro Île-de-France complement hint is wrong")
    if "Échelon 0 bis" in ifsi or "régions" not in ifsi:
        bad.append("IFSI: the Crous table is shown or the Region is not said")
    if "Échelon 7" not in base or "6 335 €" not in base.replace(" ", " ").replace("\xa0", " "):
        bad.append("the échelon table is not shown")
    if "sont un tarif national" not in base:
        bad.append("the exemption of this formation's fee is not said")
    return not bad, f"{len(cards)} renders; {bad[:4]}"


# ---------------------------------------------------------------- AI5

@check("AI5 cost card coherence: vie.py's CVEC and Crous meal equal the official pages; no gone or unverified link")
def ai5(c: Ctx):
    vie = c.mod("vie")
    A = c.mod().read(DIR)
    bad = []
    if not A.get("cvec") or (vie.CVEC["montant"], vie.CVEC["annee"]) != (A["cvec"]["montant"], A["cvec"]["annee"]):
        bad.append(f"vie.CVEC {vie.CVEC.get('montant')} {vie.CVEC.get('annee')} vs the CVEC page")
    if str(A["cvec"]["montant"]) + " €" not in vie.CVEC["texte"]:
        bad.append("the CVEC sentence does not print the official amount")
    rp = A.get("repas") or {}
    if (vie.REPAS_RU["prix"], vie.REPAS_RU["depuis"], vie.REPAS_RU["url"]) != (rp.get("prix"), rp.get("depuis"), rp.get("source")):
        bad.append(f"vie.REPAS_RU {vie.REPAS_RU} vs the meal page {rp}")
    for gone in ("etudiant.gouv.fr/fr/se-restaurer", "caf.fr/allocataires/aides-et-demarches/mes-demarches/faire-une-simulation"):
        if gone in c.js or gone in c.src["vie"]:
            bad.append(f"a gone or unverified link is still there: {gone}")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- AI6

@check("AI6 real warehouse: core.aides equals the official pages' reading; the rules hold on real formations (skipped until built)")
def ai6(c: Ctx):
    if not (c.real and c.db):
        return True, "fixture mode"
    import duckdb

    from suptracker import vie as V
    con = duckdb.connect(str(c.db), read_only=True)
    if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'core' AND table_name = 'aides'").fetchone()[0]:
        return True, "core.aides not built yet (the data workflow builds it)"
    ai = c.mod()
    stored, now = ai.national(con), ai.read(DIR)
    bad = []
    if {k: v for k, v in stored.items() if k != "lu_le"} != {k: v for k, v in now.items() if k != "lu_le"}:
        bad.append("the warehouse's aids differ from data/aides: rebuild the warehouse")
    tarifs = set(stored["droits"]["tarifs"])
    n = 0
    for cod, fili, contrat, dep in con.execute("""SELECT cod_aff_form, fili, contrat_etab, dep FROM core.formation_year
            WHERE session = (SELECT max(session) FROM core.formation_year) ORDER BY hash(cod_aff_form) LIMIT 400""").fetchall():
        v = V.for_formation(con, cod)
        a = ai.for_formation(con, cod, v)
        n += 1
        fee = ((v or {}).get("frais") or {}).get("montant")
        if a["droits_exoneres"] and not (contrat == "Public" and (fee == 0 or fee in tarifs)):
            bad.append(f"{cod}: exempt ({contrat}, {fee})")
        if fili in ("IFSI", "EFTS") and a["bourse"] is not None:
            bad.append(f"{cod}: Crous table for {fili}")
        if a["annuel_boursier"] and v["annuel"] and a["annuel_boursier"]["max"] > v["annuel"]["max"]:
            bad.append(f"{cod}: boursier pays more")
        if a["bourse"] and str(dep).startswith(("97", "98")) != bool(a["bourse"].get("majoree")):
            bad.append(f"{cod}: overseas majoration wrong")
    return not bad, f"{n} real formations; {bad[:4]}"


# ---------------------------------------------------------------- AI7

@check("AI7 plumbing: workflow, build, API, fingerprint, source register, docs, tests and durations")
def ai7(c: Ctx):
    bad = []
    wf = (REPO / ".github" / "workflows" / "suptracker-aides.yml").read_text()
    for need in ("python scripts/aides_fetch.py data/aides", 'paths: ["suptracker/data/aides/request.json"]', "git add data/aides", 'bash scripts/git_push_retry.sh "$GITHUB_REF_NAME"'):
        if need not in wf:
            bad.append(f"workflow: {need} missing")
    data = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    if "data/sources data/aides" not in data:
        bad.append("the warehouse fingerprint ignores data/aides")
    if "aides.build(con)" not in c.src["build"] or "from . import aides," not in c.src["build"]:
        bad.append("build: aides.build missing")
    api = (ROOT / "suptracker" / "api.py").read_text()
    for need in ('"aides": AID.for_formation(_con().cursor(), rec["cod_aff_form"], vie)', '"financer_etudes"'):
        if need not in api:
            bad.append(f"api: {need} missing")
    if "aidesCard(d.aides, d.vie)" not in c.js:
        bad.append("the cost tab does not show the card")
    from suptracker import sources
    if "aides_etudiantes" not in {s["key"] for s in sources.SOURCES}:
        bad.append("not in the source register")
    readme = (ROOT / "README.md").read_text()
    if "redteam_aides.py" not in readme or "Financer vos études" not in readme:
        bad.append("README section missing")
    if "redteam_aides.py" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule missing")
    if not (ROOT / "tests" / "test_aides.py").exists() or "tests/test_aides.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("test file or its duration missing")
    if '"financer_etudes"' not in (ROOT / "tests" / "test_release.py").read_text():
        bad.append("release guard missing")
    return not bad, f"{bad[:4]}"


# ---------------------------------------------------------------- AI8

SOURCE_MUTANTS = [
    ("ai", "a row of the table skipped", "        if L[i] == ECHELONS[len(rows)] and", "        if L[i] in ECHELONS and L[i] != \"3\" and", "AI1"),
    ("ai", "monthly = annual / 12", '        r["mensuel"] = round(r["annuel"] / n, 2)', '        r["mensuel"] = round(r["annuel"] / 12, 2)', "AI1"),
    ("ai", "increasing order not checked", 'any(a["annuel"] >= b["annuel"] for a, b in zip(rows, rows[1:]))', "False", "AI2"),
    ("ai", "mérite product not checked", "    if n * par != montant:\n        return None", "", "AI2"),
    ("ai", "mobility amounts not compared", 'or a.group(1) != b.group(1)', "", "AI2"),
    ("ai", "simulator on any host", r'and re.match(r"https://(www\.)?[a-z.-]+\.(gouv\.fr|fr)/", url)', "", "AI2"),
    ("ai", "exemption for any public fee", "    return True if frais == 0 or frais in set(tarifs or ()) else None", "    return True", "AI3"),
    ("ai", "exemption for private establishments", '    if frais is None or statut != "public":', "    if frais is None:", "AI3"),
    ("ai", "CVEC counted for boursiers", '"min": _arrondi(MOIS_PAR_AN * m["min"] + frais)', '"min": _arrondi(MOIS_PAR_AN * m["min"] + frais + 105)', "AI3"),
    ("ai", "IFSI gets the Crous table", "    if fili in SANITAIRE_SOCIAL:", "    if fili in ():", "AI3"),
    ("ai", "overseas majoration dropped", "        if out[\"outre_mer\"]:\n            maj", "        if False:\n            maj", "AI3"),
    ("js", "condition unescaped", "a.merite.conditions.map((c) => `<li>${esc(c)}</li>`)", "a.merite.conditions.map((c) => `<li>${c}</li>`)", "AI4"),
    ("js", "académie unescaped", "pas la vôtre (${esc(p.academie)})", "pas la vôtre (${p.academie})", "AI4"),
    ("js", "boursier year not labelled", '${estimTag("même calcul que ci-dessus, sans ce dont les boursiers sont exonérés ; la bourse n\'est pas déduite")}', "", "AI4"),
    ("js", "unsafe link kept", "  const lien = (url, texte) => /^https:\\/\\/[a-z0-9.-]+\\.gouv\\.fr\\//.test(url || \"\") ? ", "  const lien = (url, texte) => url ? ", "AI4"),
    ("ai", "the tariff table cut short", '        if x in ("Transfert d\'inscription", "Règlement", "Exonération des droits d\'inscription"):',
     '        if len(x) > 120 or x in ("Transfert d\'inscription",):', "AI1"),
    ("js", "profile sent to the site", "  const p = bacProfile(), hints = [];", "  const p = bacProfile(), hints = []; api(\"/api/aides?academie=\" + ((bacProfile() || {}).academie || \"\"));", "AI4"),
    ("js", "IdF complement for every bac", 'p.serie === "bp" && idf.includes(p.academie)', "idf.includes(p.academie)", "AI4"),
    ("vie", "CVEC typed differently", '"montant": 105, "annee": "2026-2027"', '"montant": 103, "annee": "2026-2027"', "AI5"),
    ("vie", "meal link reverted", '"url": "https://www.etudiant.gouv.fr/fr/comment-beneficier-du-repas-crous-1-eu-3123"', '"url": "https://www.etudiant.gouv.fr/fr/se-restaurer"', "AI5"),
    ("build", "aids not built", "        aides.build(con)", "        pass", "AI7"),
    ("fetch", "any host fetched", '    "https://sante.gouv.fr/")', '    "https://sante.gouv.fr/", "https://example.com/")', "AI2"),
]


@check("AI8 mutation test: reading, rules, page, coherence and plumbing mutants each caught")
def ai8(c: Ctx):
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
    c = Ctx(db or ROOT / "data" / "suptracker.duckdb", real)
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
    ap.add_argument("--real", action="store_true", help="also check the committed warehouse")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
