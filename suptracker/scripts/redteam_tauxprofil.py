"""Red team of sprint R2 (owner, 2026-11-11): one sourced figure "Pour votre profil" beside the official access rate.

    python scripts/redteam_tauxprofil.py [--db data/suptracker.duckdb] [--real] [--browser]

  Z1 reference (Node vs Python): for formations of every kind (own report with a bac général table, a bac techno or bac pro
     table, similar formations only, national group only, nothing) and profiles of every kind (a detailed doublette, a doublette
     in the "Autres doublettes" line, a rare one, bac techno / pro lines, "autre", an unknown route), the page's profileRate gives
     the figure re-derived in Python from the modules' own twins (rapports.pick, semblables.estimate, doublettes.estimate,
     voies.pick_voie) in the published-first order: same kind, same source, same rate
  Z2 the summary and the card agree: for the same formation and profile, the "Selon votre bac" card's headline ("Votre
     doublette / Votre ligne dans cette formation : x %") is the tile's figure, and when the tile is published the card shows
     no estimate (a published figure replaces an estimate, never sits beside it)
  Z3 the tile (Node): escaped, its source said in words (publié + rapport du jury + session / estimation + its basis), never a
     chance; bac techno / pro without a line waits for the Plan B answer and is filled with the estimated series access (or "—",
     never left on "…", errors included); the summary has the official rate first, the profile's next, 5 tiles with a terminale
     profile, 4 without one and outside terminale (the estimated access keeps its own tile)
  Z4 wiring and wording: bacProfile() feeds the tile; Plan B fills both tiles, errors included; phone and wide layouts;
     feature, release guard, method text, README and CLAUDE.md
  Z5 browser (--browser / --real): the formation page with a bac général and a bac techno profile, 0 JS error, no "…" left, no
     horizontal scroll on a phone
  Z6 mutation test of Z1-Z4 (mutants built in memory)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import doublettes as DB  # noqa: E402
from suptracker import rapports as RP  # noqa: E402
from suptracker import semblables as SB  # noqa: E402
from suptracker import voies as VO  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
CHANCE = re.compile(r"(?i)probabilit|vos chances|votre chance|chances? d['’]être admis|vous serez admis|garanti")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False, browser: bool = False):
        self.db, self.real, self.browser = db, real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.release = (ROOT / "tests" / "test_release.py").read_text()
        self.readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
        self.claude = (ROOT.parent / "CLAUDE.md").read_text() if (ROOT.parent / "CLAUDE.md").exists() else ""
        self._cases = None

    def cases(self):
        if self._cases is None:
            self._cases = build_cases(self.con)
        return self._cases


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async )?function {re.escape(name)}\(|^const {re.escape(name)} = ", js, re.M)
    if not m:
        raise KeyError(name)
    if js[m.start():].startswith("const "):
        e = re.search(r";[ \t]*(?://[^\n]*)?$", js[m.start():], re.M)
        # a multi-line object literal ends with "};" at column 0
        end = js.find("\n};", m.start())
        one = m.start() + e.end()
        if end != -1 and js[m.start():one].count("{") > js[m.start():one].count("}"):
            return js[m.start(): end + 3]
        return js[m.start(): one]
    end = js.find("\n}", m.start())
    return js[m.start(): end + 2]


def node(prog: str, payload=None):
    exe = shutil.which("node")
    if not exe:
        return None
    r = subprocess.run([exe, "-e", prog], input=json.dumps(payload, default=str), capture_output=True, text=True, timeout=120)
    if r.returncode:
        return "__error__ " + r.stderr[-800:]
    return r.stdout


# ------------------------------------------------------------------ cases: real formations x profiles of every kind
def payload(con, cod: str, session: int) -> dict:
    """The parts of /api/formation the tile reads, for the page of (cod, session)."""
    cur = con.cursor()
    return {"doublettes": DB.for_formation(cur, cod, session), "rapport": RP.for_formation(cur, cod, session),
            "semblables": SB.for_formation(cur, cod, session), "record": {"cod_aff_form": cod, "session": session}}


def build_cases(con, per_kind: int = 6) -> list[tuple[dict, dict]]:
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    has = lambda t: con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema || '.' || table_name = ?", [t]).fetchone()[0]  # noqa: E731
    picks: list[str] = []
    if has("core.rapport_doublette"):
        for bac in ("bg", "bt", "bp"):
            picks += [c for (c,) in con.execute("""SELECT DISTINCT cod_aff_form FROM core.rapport_doublette WHERE session = ? AND bac = ?
                ORDER BY hash(cod_aff_form) LIMIT ?""", [latest, bac, per_kind]).fetchall()]
    # no own bac général table, but similar formations' reports for its diploma and mention
    if has("mart.semblable_dbl") and has("core.rapport_doublette"):
        picks += [c for (c,) in con.execute("""SELECT fy.cod_aff_form FROM core.formation_year fy
            WHERE fy.session = ? AND EXISTS (SELECT 1 FROM mart.semblable_dbl s WHERE s.session = fy.session AND s.fili = fy.fili
                AND s.filiere = fy.fil_lib_voe_acc)
            AND NOT EXISTS (SELECT 1 FROM core.rapport_doublette r WHERE r.cod_aff_form = fy.cod_aff_form AND r.bac = 'bg')
            ORDER BY hash(fy.cod_aff_form) LIMIT ?""", [latest, per_kind]).fetchall()]
    # no own bac général table: similar formations or the national group, or nothing
    picks += [c for (c,) in con.execute(f"""SELECT cod_aff_form FROM core.formation_year fy WHERE session = ?
        {"AND NOT EXISTS (SELECT 1 FROM core.rapport_doublette r WHERE r.cod_aff_form = fy.cod_aff_form AND r.bac = 'bg')" if has("core.rapport_doublette") else ""}
        ORDER BY hash(cod_aff_form) LIMIT ?""", [latest, per_kind * 4]).fetchall()]
    # Codex (PR #54): older pages of lineages that continue to the latest campaign (the series' top-level figure is not theirs)
    old = []
    if has("core.lineage"):
        old = [(c, s) for c, s in con.execute("""SELECT l.cod_aff_form, l.session FROM core.lineage l
            WHERE l.session < ? AND EXISTS (SELECT 1 FROM core.lineage m WHERE m.lineage_id = l.lineage_id AND m.session = ?)
            ORDER BY hash(l.cod_aff_form) LIMIT ?""", [latest, latest, per_kind * 2]).fetchall()]
    out = []
    for cod, sess in [(c, latest) for c in dict.fromkeys(picks)] + old:
        d = payload(con, cod, sess)
        rp, dbl, sem = d["rapport"], d["doublettes"], d["semblables"]
        keys = []                                   # ordered: every source of figures gets its keys tried
        if sem:
            keys += [x["key"] for x in (sem.get("doublettes") or [])[:2]]
        if rp:
            keys += [x["key"] for x in rp["doublettes"].get("bg") or [] if x.get("key")][:2]
        if dbl and dbl.get("status") == "ok":
            keys += [x["key"] for x in dbl["groupe"]["doublettes"][:2]] + [x["key"] for x in dbl["groupe"]["doublettes"] if x.get("rare")][:1]
        keys += ["MATHS+SES", "ART+EPPCS"]
        for k in list(dict.fromkeys(keys))[:8]:
            a, b = k.split("+")
            out.append((d, {"serie": "bg", "spe1": a, "spe2": b, "mention": "b", "statut": "terminale"}))
        for bac in ("bt", "bp"):
            vk = [x["voie"] for x in (rp["doublettes"].get(bac) or [])] if rp else []
            for v in [x for x in vk if x][:3] + ["autre", "cle-inconnue", None]:
                out.append((d, {"serie": bac, "voie": v, "mention": "ab", "statut": "terminale"}))
    # crafted from a payload of this warehouse (every warehouse, the synthetic one has no report): an own report with bac général,
    # bac techno and bac pro rows, and similar formations' reports, so each branch of the order is exercised everywhere
    import copy
    base = next((d for d, _ in out if d["doublettes"] and (d["doublettes"].get("series") or {}).get("bg", {}).get("taux") is not None), None)
    if base:
        H = "<img src=x onerror=alert(1)>"
        row = lambda key, lib, taux, autres=False, voie=None: {"key": key, "libelle": lib, "taux": taux, "autres": autres, "voie": voie,  # noqa: E731
                                                               "en_position": 7, "confirmes": 9, "classes": 9, "acceptes": 3}
        rp = {"session": 2025, "sessions": [2025], "capture": "20250701", "source": "archive", "recoupe": True, "archive": "https://web.archive.org/x",
              "doublettes": {"bg": [row("MATHS+SES", "Mathématiques, SES", 77.7), row(None, "Autres doublettes", 12.5, autres=True)],
                             "bt": [row(None, f"STI2D {H}", 61.0, voie="sti2d"), row(None, "Autres", 20.0, autres=True)],
                             "bp": [row(None, "Commerce", 33.3, voie="commerce")]},
              "masques": [], "voie_keys": {"bt": ["sti2d", "stmg"], "bp": ["commerce"]}, "textes": None, "concours": False}
        d1 = copy.deepcopy(base); d1["rapport"] = rp; d1["record"]["cod_aff_form"] += "-rapport"
        for prof in ({"serie": "bg", "spe1": "SES", "spe2": "MATHS"}, {"serie": "bg", "spe1": "HGGSP", "spe2": "LLCER"},
                     {"serie": "bt", "voie": "sti2d"}, {"serie": "bt", "voie": "stmg"}, {"serie": "bt", "voie": "inconnue"},
                     {"serie": "bp", "voie": "commerce"}, {"serie": "bp", "voie": "autre"}, {"serie": "bg", "spe1": "ART", "spe2": "ART"}):
            out.append((d1, {**prof, "mention": "b", "statut": "terminale"}))
        sem = {"session": 2025, "fili": "BUT", "filiere": "Informatique", "min_rapports": 3, "min_candidats": 20,
               "doublettes": [{"key": "MATHS+NSI", "label": "Mathématiques, NSI", "taux": 30.0, "tous_taux": 40.0, "n_rapports": 4,
                               "en_position": 30, "confirmes": 100}]}
        d2 = copy.deepcopy(base); d2["rapport"] = None; d2["semblables"] = sem; d2["record"]["cod_aff_form"] += "-semblables"
        out.append((d2, {"serie": "bg", "spe1": "NSI", "spe2": "MATHS", "mention": "b", "statut": "terminale"}))
        out.append((d2, {"serie": "bg", "spe1": "MATHS", "spe2": "SES", "mention": "b", "statut": "terminale"}))
    # crafted from a real payload: an own bac général table with neither the student's doublette nor an "Autres doublettes"
    # line (the report gives no figure for them, and no estimate may stand in for it)
    own = next((d for d, _ in out if d["rapport"] and d["rapport"]["doublettes"].get("bg")), None)
    if own:
        d2 = copy.deepcopy(own)
        d2["rapport"]["doublettes"]["bg"] = [x for x in d2["rapport"]["doublettes"]["bg"] if not x["autres"] and x.get("key") != "ART+EPPCS"]
        d2["record"]["cod_aff_form"] += "-sans-ligne"
        if d2["rapport"]["doublettes"]["bg"]:
            out.append((d2, {"serie": "bg", "spe1": "ART", "spe2": "EPPCS", "mention": "b", "statut": "terminale"}))
    return out


def dkey_of(p):
    return "+".join(sorted([p["spe1"].upper(), p["spe2"].upper()]))


def reference(d: dict, p: dict) -> dict:
    """The figure the page must show, re-derived from the modules' Python twins, published first."""
    rp, dbl, sem = d["rapport"], d["doublettes"], d["semblables"]
    series = (dbl or {}).get("series") or {}
    session = d["record"]["session"]                 # Codex (PR #54): the page's own campaign, never the lineage's latest

    def at(trend):
        return next((t for t in trend or [] if t["session"] == session), None)

    def route():                                     # the card's "votre bac" row: this formation's proposal rate for the route
        v = at((series.get(p["serie"]) or {}).get("trend"))
        return {"kind": "serie", "source": "voie", "taux": v["taux"]} if v and v.get("taux") is not None else {"kind": "aucun"}

    def est_at(e):
        t = at(e["trend"]) if e else None
        return t["taux"] if t and t["taux"] is not None else None
    if p["serie"] == "bg":
        # two identical specialties (the form refuses them; ART+ART exists nationally, see README): no doublette at all
        if p["spe1"].upper() == p["spe2"].upper():
            return {"kind": "incomplet"}
        dkey = dkey_of(p)
        if rp and rp["doublettes"].get("bg"):
            x = RP.pick(rp, dkey)
            return {"kind": "publie", "source": "rapport", "taux": x["taux"]} if x else {"kind": "aucun"}
        e = SB.estimate(series.get("bg"), sem, dkey)
        if est_at(e) is not None:
            return {"kind": "estimation", "source": "semblables", "taux": est_at(e)}
        e = DB.estimate(series.get("bg"), dbl.get("groupe"), dkey) if dbl and dbl.get("status") == "ok" else None
        if est_at(e) is not None:
            return {"kind": "estimation", "source": "national", "taux": est_at(e)}
        return route()
    v = VO.pick_voie(rp, p["serie"], p.get("voie"))
    return {"kind": "publie", "source": "rapport", "taux": v["taux"]} if v else route()


def harness(js: str) -> str:
    """The page's own code for the doublette card and the profile tile (no copy)."""
    blk = js[js.index('// ---- Sprint "Doublettes"'):js.index("// ---- lot 2 (Claude design guidelines)")]
    r2 = js[js.index("// R2 (owner, 2026-11-11): ONE sourced figure"):js.index("function summaryBand(")]
    helpers = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pc1 = ", "const pct = ",
                                                                          "const isReo = ", "const REO_LABEL = ")))
    bac = re.search(r"^function bacProfile\(\) \{.*?^\}", js, re.M | re.S).group(0)
    return helpers + "\nlet PROFILE = null; const store = { get: (k, d) => (k === 'profile' ? PROFILE : d) };\n" \
        + "const tip = () => ''; const legend = () => ''; const lineChart = () => '';\n" + bac + "\n" + blk + "\n" + r2


Z1_PROG = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([d, p]) => {
  PROFILE = p;
  const pr = profileRate(d, bacProfile());
  const card = doubletteCard(d.doublettes, d.rapport, d.semblables);
  const tile = profileRateTile(pr);
  return { pr, card, tile };
});
process.stdout.write(JSON.stringify(out));
"""


def run_cases(js: str, cases):
    r = node(harness(js) + Z1_PROG, cases)
    if r is None or r.startswith("__error__"):
        return r
    return json.loads(r)


def close(a, b):
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-9)


@check("Z1 reference: the page's figure for the profile is the one re-derived in Python, published first, for every kind")
def z1(c: Ctx):
    cases = c.cases()
    got = run_cases(c.js, cases)
    if got is None:
        return True, "node not installed"
    if isinstance(got, str):
        return False, got
    bad, kinds = [], {}
    for (d, p), g in zip(cases, got):
        ref, pr = reference(d, p), g["pr"] or {}
        kinds[(p["serie"], ref["kind"], ref.get("source"))] = kinds.get((p["serie"], ref["kind"], ref.get("source")), 0) + 1
        if pr.get("kind") != ref["kind"] or pr.get("source") != ref.get("source") or not close(pr.get("taux"), ref.get("taux")):
            bad.append((d["record"]["cod_aff_form"], p, ref, {k: pr.get(k) for k in ("kind", "source", "taux")}))
    olds = sum(1 for d, _ in cases if any(t["session"] > d["record"]["session"]
                                             for t in (((d["doublettes"] or {}).get("series") or {}).get("bg") or {}).get("trend") or []))
    need = {("bg", "publie", "rapport"), ("bg", "estimation", "semblables"), ("bt", "publie", "rapport"), ("bp", "publie", "rapport"),
            ("bt", "serie", "voie"), ("bp", "serie", "voie")}
    if c.real:                                   # the real warehouse also has the national estimate
        need |= {("bg", "estimation", "national")}
    missing = need - set(kinds)
    ok = not bad and not missing and len(cases) >= 20 and olds >= 5
    return ok, f"{len(cases)} cases ({olds} on older pages); kinds {dict(sorted(kinds.items(), key=str))}; uncovered {sorted(missing)}; {len(bad)} differences {bad[:2]}"


ROUTE_ROW = re.compile(r'votre bac</span></td>\s*<td class="num" data-label="Taux de proposition">([0-9][0-9 ,.]*) %')
HEAD = re.compile(r"Votre (?:doublette|ligne) dans cette formation : ([0-9][0-9 ,.]*) %")


def to_num(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


@check("Z2 the summary and the card agree: the card's headline is the tile's figure; a published tile has no estimate beside it")
def z2(c: Ctx):
    cases = c.cases()
    got = run_cases(c.js, cases)
    if got is None:
        return True, "node not installed"
    if isinstance(got, str):
        return False, got
    bad = []
    for (d, p), g in zip(cases, got):
        pr, card = g["pr"] or {}, g["card"] or ""
        tr = (((d["doublettes"] or {}).get("series") or {}).get("bg") or {}).get("trend") or []
        if tr and tr[-1]["session"] != d["record"]["session"]:
            continue                                # an older page: the card shows the lineage's latest campaign (Z1 checks the tile)
        heads = [to_num(x) for x in HEAD.findall(card.replace(" ", " "))]
        if pr.get("kind") in ("publie", "estimation"):
            if pr.get("taux") is not None and not any(abs(h - pr["taux"]) < 0.051 for h in heads):
                bad.append(("card headline differs", d["record"]["cod_aff_form"], p, pr.get("taux"), heads))
        elif pr.get("kind") == "serie":
            row = ROUTE_ROW.search(card.replace("\u202f", " "))
            if not row or abs(to_num(row.group(1)) - pr["taux"]) > 0.051:
                bad.append(("the card's 'votre bac' row differs", d["record"]["cod_aff_form"], p, pr.get("taux"), row and row.group(1)))
        if heads and p["serie"] == "bg" and pr.get("kind") not in ("publie", "estimation"):
            bad.append(("the card has a doublette figure the tile does not show", d["record"]["cod_aff_form"], p, heads))
        if pr.get("kind") == "publie" and ("estimation" in g["tile"] or "estimation à partir" in card or "<span class=\"estim-tag\">estimation</span>" in card.split("Détail national du groupe")[0]):
            bad.append(("estimate beside a published figure", d["record"]["cod_aff_form"], p))
    return not bad, f"{len(cases)} cases; {len(bad)} problems {bad[:2]}"


Z3_PROG = r"""
const H = "<img src=x onerror=alert(1)>";
const out = {};
out.none = profileRateTile(null);
out.incomplet = profileRateTile({ kind: "incomplet" });
out.pub = profileRateTile({ kind: "publie", taux: 89.84, what: `votre bac, ligne « ${H} »`, source: "rapport", session: 2025, recoupe: true, en_position: 7, confirmes: 9 });
out.pending = profileRateTile({ kind: "publie", taux: 50, what: "x", source: "rapport", session: 2026, recoupe: false, en_position: 1, confirmes: 2 });
out.sem = profileRateTile({ kind: "estimation", taux: 42, what: H, source: "semblables", n_rapports: 7 });
out.nat = profileRateTile({ kind: "estimation", taux: 42, what: "Mathématiques, SES", source: "national" });
out.ser = profileRateTile({ kind: "serie", taux: 30, what: "Bac technologique", source: "voie", fragile: true, candidats: 12 });
out.serOk = profileRateTile({ kind: "serie", taux: 30, what: "Bac technologique", source: "voie", fragile: false, candidats: 120 });
out.no = profileRateTile({ kind: "aucun", what: H, why: H });
process.stdout.write(JSON.stringify(out));
"""


def tile_ok(js: str):
    r = node(harness(js) + Z3_PROG)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    bad = []
    text = " ".join(v if isinstance(v, str) else " ".join(v) for v in o.values())
    if "<img" in text:
        bad.append("unescaped")
    if CHANCE.search(text) or FORMAL.search(re.sub(r"<[^>]+>", " ", text)):
        bad.append("chance wording or tutoiement")
    if 'href="#/profil"' not in o["none"] or "Pour votre profil" not in o["none"]:
        bad.append("no profile: no way to create one")
    if 'href="#/profil"' not in o["incomplet"] or "deux spécialités" not in o["incomplet"]:
        bad.append("no doublette: no way to give the specialties")
    if not ("89,8" in o["pub"] and "publié" in o["pub"] and "rapport du jury 2025" in o["pub"] and "7 sur 9 candidats" in o["pub"] and "estimation" not in o["pub"]):
        bad.append(("published", o["pub"]))
    if "pas encore recoupé" not in o["pending"]:
        bad.append("report not cross-checked yet, not said")
    if not ("estimation" in o["sem"] and "7 formations semblables" in o["sem"] and "estimation" in o["nat"] and "national" in o["nat"]):
        bad.append("estimate basis not said")
    if not ("taux de proposition de cette formation (effectifs publiés)" in o["ser"] and "peu de candidats (12)" in o["ser"]
            and "peu de candidats" not in o["serOk"] and "publié ·" not in o["ser"] and "estimation" not in o["ser"]):
        bad.append(("route rate", o["ser"], o["serOk"]))
    if "fermé" in text or "rare" in text:
        bad.append("the tile reads a rate as rare or closed (the card's own flags only)")
    return not bad, f"{len(bad)} problems {bad[:3]}"


BAND_PROG = r"""
const ICONS = new Proxy({}, { get: () => "" });
const out = {};
const r = { session: 2025, taux_acces_ens: 76, acc_tot: 30, capa_fin: 32 };
const d = { metiers: null, admis: null, reorientation: { acces_estime: 33.3, plafonne: false, candidats: 40, propositions: 12 },
  doublettes: { status: "sans_groupe", series: { bg: { taux: 40, candidats: 100, fragile: false, trend: [] } } }, rapport: null, semblables: null };
for (const [k, p] of [["none", null], ["bg", { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b" }], ["reo", { statut: "reorientation", academie: "Lyon" }]]) {
  PROFILE = p; out[k] = summaryBand(r, d);
}
process.stdout.write(JSON.stringify(out));
"""


def band_ok(js: str):
    extra = "\n".join(top(js, n) for n in ("admisBar", "reoWhy") if re.search(rf"^function {n}\(", js, re.M))
    rs = "\n".join(ln for ln in js.splitlines() if ln.startswith(("const REO_NO_ZONE = ", "const REO_METHOD = ")))
    prog = harness(js) + "\n" + rs + "\n" + extra + "\n" + top(js, "summaryBand") + BAND_PROG
    r = node(prog)
    if r is None:
        return True, "node not installed"
    if r.startswith("__error__"):
        return False, r
    o = json.loads(r)
    count = {k: len(re.findall(r'class="sum-tile', v)) for k, v in o.items()}
    labels = {k: re.findall(r'<span class="sum-label">([^<]*)</span>', v) for k, v in o.items()}
    bad = []
    if count != {"none": 4, "bg": 5, "reo": 4}:
        bad.append(("tile counts", count))
    if any(not lab or not lab[0].startswith("Taux d'accès") for lab in labels.values()):
        bad.append(("official rate not first", labels))
    if labels["bg"][1:3] != ["Pour votre profil", "Votre zone"] or labels["none"][1] != "Pour votre profil":
        bad.append(("profile figure not next to the official rate", labels))
    if "Pour votre profil" in labels["reo"] or "Votre zone" in " ".join(labels["reo"]) or "Accès estimé hors terminale" not in labels["reo"]:
        bad.append(("outside terminale", labels["reo"]))
    if "officiel" not in o["bg"].split("Pour votre profil")[0]:
        bad.append("official rate not said official")
    return not bad, f"tiles {count}; {len(bad)} problems {bad[:2]}"


@check("Z3 the tile: escaped, source in words, never a chance; bac techno / pro filled by Plan B or '—'; official first, 5 / 4 tiles")
def z3(c: Ctx):
    a, da = tile_ok(c.js)
    b, db = band_ok(c.js)
    return a and b, f"tile: {da}; summary: {db}"


@check("Z4 wiring and wording: bacProfile feeds the tile, Plan B fills both tiles (errors too), layouts, feature, docs")
def z4(c: Ctx):
    js, bad = c.js, []
    sb = top(js, "summaryBand")
    if "const pr = profileRate(d, bacProfile());" not in sb or "${isReo(prof) ? \"\" : profileRateTile(pr)}" not in sb:
        bad.append("the tile does not read the validated profile")
    lp = js[js.index("async function loadPlanB("):js.index("async function loadPlanB(") + 4000]
    if "fillZoneTile(null);" not in lp or "fillZoneTile(d.target);" not in lp:
        bad.append("Plan B leaves the zone tile waiting")
    pr = top(js, "profileRate")
    # review: the figure is the card's, for the page's own campaign; never the latest campaign's Plan B estimate
    if "target" in pr or "planb" in pr.lower() or "fillProfileTile" in js:
        bad.append("the tile reads Plan B (another campaign, a figure the card does not show)")
    order = [pr.find(x) for x in ("ownHasBg(rp)", "estimateSemblable(", "estimateDoublette(", "return route();")]
    if -1 in order or order != sorted(order) or "pickVoie(rp, serie, prof.voie || null)" not in pr:
        bad.append(("the published-first order", order))
    if ".sum-grid:has(> :nth-child(5)) { grid-template-columns: repeat(5, minmax(0, 1fr)); }" not in c.css \
            or ".sum-grid > :nth-child(5):last-child { grid-column: span 2; }" not in c.css:
        bad.append("5-tile layouts")
    if '"taux_profil"' not in c.api.split("FEATURES = [", 1)[1].split("]", 1)[0] or '"taux_profil": ("app.js", "function profileRate(")' not in c.release:
        bad.append("feature or release guard")
    words = re.sub(r"<[^>]+>|\$\{[^}]*\}", " ", " ".join(re.findall(r"`([^`]*)`", js[js.index("// R2 (owner, 2026-11-11): ONE sourced figure"):js.index("function summaryBand(")])))
    if CHANCE.search(words) or FORMAL.search(words):
        bad.append("wording")
    if c.readme and "Pour votre profil" not in c.readme:
        bad.append("README")
    if c.claude and "Pour votre profil" not in c.claude:
        bad.append("CLAUDE.md")
    return not bad, f"{len(bad)} problems {bad[:3]}"


BROWSER = r"""
const { chromium, devices } = require('playwright');
const [base, codBg, codBt] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [name, opts, prof, cod] of [
      ["wide-bg", { viewport: { width: 1280, height: 900 } }, { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "b", statut: "terminale" }, codBg],
      ["phone-bt", { ...devices["iPhone 13"] }, { serie: "bt", voie: null, mention: "ab", statut: "terminale" }, codBt],
      ["phone-none", { ...devices["iPhone 13"] }, null, codBg]]) {
    const c = await b.newContext(opts);
    if (prof) await c.addInitScript((p) => localStorage.setItem("profile", JSON.stringify(p)), prof);
    const p = await c.newPage(); p.on("pageerror", (e) => errs.push(e.message));
    await p.goto(base + "/#/f/" + cod); await p.waitForTimeout(4000);
    out[name] = await p.evaluate(() => {
      const t = [...document.querySelectorAll(".summary .sum-tile")];
      const prof = t.find((x) => /Pour votre profil/.test(x.textContent));
      return { n: t.length, first: t[0] && t[0].querySelector(".sum-label").textContent, profil: prof ? prof.textContent.replace(/\s+/g, " ").trim() : null,
               hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth };
    });
    await c.close();
  }
  process.stdout.write(JSON.stringify({ errs, out })); await b.close();
})();
"""


@check("Z5 browser: the formation page with a bac général, a bac techno and no profile: tile filled, 0 JS error, no scroll")
def z5(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    probe = subprocess.run([exe, "-e", "require('playwright')"], capture_output=True, text=True) if exe else None
    if not exe or probe.returncode:
        return True, "skipped (node or playwright not installed)"
    latest = c.con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    cod_bg = c.con.execute("""SELECT cod_aff_form FROM core.rapport_doublette WHERE session = ? AND bac = 'bg' AND doublette_key = 'MATHS+SES'
        ORDER BY hash(cod_aff_form) LIMIT 1""", [latest]).fetchone()[0]
    cod_bt = c.con.execute("""SELECT cod_aff_form FROM core.formation_year fy WHERE session = ? AND nb_voe_pp_bt > 50 AND NOT EXISTS
        (SELECT 1 FROM core.rapport_doublette r WHERE r.cod_aff_form = fy.cod_aff_form AND r.bac = 'bt') ORDER BY hash(cod_aff_form) LIMIT 1""",
                           [latest]).fetchone()[0]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**__import__("os").environ, "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=str(ROOT), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        tmp = ROOT / ".tauxprofil_probe.js"
        tmp.write_text(BROWSER)
        try:
            r = subprocess.run([exe, str(tmp), f"http://127.0.0.1:{port}", cod_bg, cod_bt], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-400:]
    d = json.loads(r.stdout)
    o, bad = d["out"], []
    if d["errs"]:
        bad.append(("JS errors", d["errs"][:2]))
    if o["wide-bg"]["n"] != 5 or "publié" not in (o["wide-bg"]["profil"] or "") or "%" not in (o["wide-bg"]["profil"] or ""):
        bad.append(("bac général", o["wide-bg"]))
    bt = o["phone-bt"]["profil"] or ""
    if "…" in bt or not ("taux de proposition de cette formation" in bt or "pas de chiffre" in bt):
        bad.append(("bac techno unsourced", bt))
    if o["phone-none"]["n"] != 4 or "créez votre profil" not in (o["phone-none"]["profil"] or ""):
        bad.append(("no profile", o["phone-none"]))
    if any(v["hscroll"] for v in o.values()) or any(not (v["first"] or "").startswith("Taux d'accès") for v in o.values()):
        bad.append("scroll or official rate not first")
    return not bad, f"{len(bad)} problems {bad[:3]}; {o}"


MUTANTS = [
    ("estimate before the published figure", "    if (ownHasBg(rp)) {\n      const x = pickRapport(rp, dkey);",
     "    if (false) {\n      const x = pickRapport(rp, dkey);", ("z1", "z2")),
    ("national before similar formations", "    const sem = estimateSemblable(series, d.semblables, dkey);",
     "    const sem = null;", ("z1", "z2")),
    ("bac techno line ignored", "  const v = pickVoie(rp, serie, prof.voie || null);", "  const v = null;", ("z1", "z2")),
    ("route row of another bac", "    const v = series && series[serie] && at(series[serie].trend);", "    const v = series && series.bg && at(series.bg.trend);", ("z1", "z2")),
    ("the lineage's latest campaign on an older page", "  const at = (trend) => (trend || []).find((t) => t.session === session) || null;",
     "  const at = (trend) => (trend || []).slice(-1)[0] || null;", ("z1",)),
    ("series rate shown for a missing report row", '        : { kind: "aucun", what: "vos deux spécialités", why: `pas de ligne dans le rapport ${rp.session}` };',
     "        : route();", ("z1",)),
    ("identical specialties read as a doublette", '    if (!dkey) return { kind: "incomplet" };', "", ("z1",)),
    ("estimate called published", 'if (sem && estAt(sem) !== null) return { kind: "estimation",', 'if (sem && estAt(sem) !== null) return { kind: "publie",', ("z1", "z2")),
    ("row label unescaped", "return tile(pct1(pr.taux), `${esc(pr.what)} ·", "return tile(pct1(pr.taux), `${pr.what} ·", ("z3",)),
    ("source not said", "  rapport: (pr) => `publié · rapport du jury ${esc(pr.session)}", "  rapport: (pr) => `${esc(pr.session)}", ("z3",)),
    ("report counts dropped", " · ${fmt(pr.en_position)} sur ${fmt(pr.confirmes)} candidats`,", "`,", ("z3",)),
    ("not-cross-checked report hidden", '${pr.recoupe ? "" : ", pas encore recoupé"}', "", ("z3",)),
    ("few candidates not said", '${pr.fragile ? ` · peu de candidats (${fmt(pr.candidats)})` : ""}', "", ("z3",)),
    ("profile tile after the zone", "      ${isReo(prof) ? \"\" : profileRateTile(pr)}\n      ${isReo(prof) ? tile(",
     "      ${isReo(prof) ? tile(", ("z3", "z4")),
    ("chance wording", 'national: () => estimTag("écart national de vos deux spécialités", false, true),',
     'national: () => "vos chances d\'être admis",', ("z3", "z4")),
    ("raw profile read", "  const pr = profileRate(d, bacProfile());", "  const pr = profileRate(d, prof);", ("z4",)),
]


@check("Z6 mutation test: order, sources, escaping, waiting tile, layout and wiring bugs are each caught")
def z6(c: Ctx):
    fns = {"z1": z1, "z2": z2, "z3": z3, "z4": z4}
    base = {k: f(c)[0] for k, f in fns.items()}
    if not all(base.values()):                    # a failing baseline would count every mutant as caught
        return False, f"baseline fails: {[k for k, v in base.items() if not v]}"
    missed = []
    for name, old, new, which in MUTANTS:
        if old not in c.js:
            missed.append(f"{name} (anchor gone)")
            continue
        m = Ctx.__new__(Ctx)
        m.__dict__.update(c.__dict__)
        m.js = c.js.replace(old, new, 1)
        if all(fns[w](m)[0] for w in which):
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} mutants caught; missed {missed}"


def run(db: Path, real: bool = False, browser: bool = False) -> list[dict]:
    c = Ctx(db, real, browser)
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
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
