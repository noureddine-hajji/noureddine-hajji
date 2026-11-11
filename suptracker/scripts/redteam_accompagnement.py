"""Red team of sprint 22, accompaniment (owner's go, 2026-11-11): the official calendar, the page for the adults who help, the
seconde / première entry, the shared and printable list.
    python scripts/redteam_accompagnement.py [--db data/suptracker.duckdb] [--real]
  T1 the calendar re-derived independently from every fetched version of the official PDF: every served date is printed in
     every version with its true weekday next to its official wording; a date printed with a wrong weekday or disagreeing
     between versions is never served; crafted versions (disagreement, wrong weekday, missing step, no file, hostile text)
  T2 the .ics file parsed independently: CRLF, folded lines of at most 75 octets, one all-day event per verified date
     (exclusive end), unique ids, escaping, the same file for every visitor
  T3 routes and register: cache policies, content type and attachment, no audience event, no parameter; the fetch script
     refuses any host but parcoursup.gouv.fr; the source register entry; the PDFs kept out of the Vercel bundle, the text kept
  T4 the calendar page in Node, at fixed dates: the next step and its countdown, past / ongoing / to come, an unverified date
     said "à vérifier", escaping, the source line ("fait foi"), the .ics link, a navigation race
  T5 seconde / première in Node: three specialties give the three doublettes, each cell the stage-1 share of THAT doublette in
     THAT filière, rows ordered by the destination share (never a chance), a missing doublette said, rare flagged, stored
     choices validated, escaping, data-label on every cell
  T6 the shared list: codes and profile validated (whitelist, never the académie or the lycée), the link round-trips, the
     profile only when the box is ticked; the page in Node reads zones only with a joined terminale profile, the estimate
     outside terminale, official rates otherwise; "add" merges up to 10 and never replaces the student's list or profile; a race
  T7 wording and wiring: no chance, vouvoiement, routes, tabs, menus, analytics, the share card on both Mes vœux pages, print
     styles, home links, features, release guard, README, CLAUDE.md
  T8 mutation test (in memory)
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import calendrier as CAL  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit[ée] d|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti|vos chances")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>"\'&'
M = {"CAL": CAL}
BLOCK_START = "// ---- sprint 22: accompaniment"
BLOCK_END = "// ---- lot 1 UI: the current tab is marked"
WD = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MO = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
# the official step and the words printed next to its date (independent of calendrier.RULES: plain lowercase substrings)
ANCHORS = {"carte": "ouverture de la carte", "fin_voeux": "dernier jour pour formuler", "confirmation": "dernier jour pour compléter",
           "admission": "début de la phase d’admission principale", "complementaire": "début de la phase complémentaire",
           "fin_principale": "fin de la phase principale", "fin_complementaire": "fin de la phase complémentaire",
           "voeux": "au jeudi 11 mars 2027", "classement": "classez vos vœux en attente"}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.js = (STATIC / "app.js").read_text()
        self.css = (STATIC / "style.css").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.stats = (STATIC / "stats.js").read_text()
        self.api = (ROOT / "suptracker" / "api.py").read_text()
        self.cache = (ROOT / "suptracker" / "cache.py").read_text()
        self.analytics = (ROOT / "suptracker" / "analytics.py").read_text()


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-700:]}


def top(js: str, name: str) -> str:
    m = re.search(rf"^(?:async function|function|const|let) {re.escape(name)}\b", js, re.M)
    if not m:
        raise KeyError(name)
    nxt = re.search(r"^(?:async function |function |const |let |//|\{|\S+\s*=)", js[m.end():], re.M)
    return js[m.start(): m.end() + (nxt.start() if nxt else len(js))].rstrip() + "\n"


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


@contextmanager
def client(db: Path):
    from fastapi.testclient import TestClient

    from suptracker import analytics as A
    from suptracker import api
    old, saved, saved_cal = os.environ.get("SUPTRACKER_DB"), A.record, api.CALR
    calls = []
    os.environ["SUPTRACKER_DB"] = str(db)
    api._con.cache_clear()
    A.record = lambda *a, **k: calls.append(a) or "ok"
    api.CALR = M["CAL"]
    try:
        tc = TestClient(api.app)
        tc.events = calls
        yield tc
    finally:
        A.record, api.CALR = saved, saved_cal
        if old is None:
            os.environ.pop("SUPTRACKER_DB", None)
        else:
            os.environ["SUPTRACKER_DB"] = old
        api._con.cache_clear()


# ---------------------------------------------------------------- T1 the calendar
def tokens(text: str):
    """Every 'weekday day month [year]' printed in a text, with what follows it (independent reading: lowercase, ’ kept)."""
    t = " ".join(text.lower().split())
    rx = re.compile(r"(" + "|".join(WD) + r")\s+(1er|\d{1,2})\s+(" + "|".join(MO) + r")(?:\s+(\d{4}))?")
    out = []
    for m in rx.finditer(t):
        out.append((m.group(1), 1 if m.group(2) == "1er" else int(m.group(2)), MO.index(m.group(3)) + 1,
                    int(m.group(4)) if m.group(4) else None, t[m.end(): m.end() + 80]))
    return out


def served_ok(cal: dict, texts: list[str]) -> list:
    """Problems: a served date not printed, with its true weekday next to its official wording, in EVERY version."""
    bad = []
    for e in cal["evenements"]:
        if not e["verifie"]:
            continue
        for d_iso in [e["debut"]] + ([e["fin"]] if e["fin"] else []):
            d = date.fromisoformat(d_iso)
            for t in texts:
                found = [x for x in tokens(t) if (x[1], x[2]) == (d.day, d.month) and (x[3] in (d.year, None))]
                if not found:
                    bad.append((e["key"], d_iso, "not printed"))
                elif not any(x[0] == WD[d.weekday()] for x in found):
                    bad.append((e["key"], d_iso, "weekday"))
            anchor = ANCHORS[e["key"]]
            if not all(anchor in " ".join(t.lower().split()) for t in texts):
                bad.append((e["key"], "anchor missing"))
    return bad


def ev_date(cal: dict, key: str):
    return next((e["debut"] for e in cal["evenements"] if e["key"] == key), None)


def write_versions(d: Path, texts: list[str]):
    log = []
    for i, t in enumerate(texts):
        (d / f"v{i}.pdf.txt").write_text(t)
        log.append({"url": f"https://www.parcoursup.gouv.fr/v{i}.pdf", "status": 200, "file": f"v{i}.pdf", "sha256": str(i),
                    "fetched": "2026-11-11T10:00:00+00:00"})
    (d / "fetch_log.json").write_text(json.dumps(log))


@check("T1 the calendar re-derived from every official version; disagreement, wrong weekday and missing steps are never served")
def t1(c: Ctx):
    C = M["CAL"]
    bad = []
    real = C.calendar()
    texts = [v["text"] for v in C.versions()]
    if texts:
        bad += served_ok(real, texts)
        # the wrongly printed heading of the first 2027 version ("samedi 10 juin 2027") exists and is never read as a step
        wrong = [(wd, d, mo, yr) for t in texts for wd, d, mo, yr, _ in tokens(t) if yr and WD[date(yr, mo, d).weekday()] != wd]
        if c.real and ("samedi", 10, 6, 2027) not in wrong:
            bad.append("the known misprint is no longer in the files: re-check the versions")
        if ev_date(real, "fin_principale") not in (None, "2027-07-10"):
            bad.append(("the misprint was read", ev_date(real, "fin_principale")))
        if c.real and sum(e["verifie"] for e in real["evenements"]) != len(C.RULES):
            bad.append(("not every official step verified", [e["key"] for e in real["evenements"] if not e["verifie"]]))
    good = (texts[0] if texts else "")
    if not good:
        good = ("JEUDI 17 DÉCEMBRE 2026 — Ouverture de la carte des formations 2027\nDU LUNDI 18 JANVIER AU JEUDI 11 MARS 2027\n"
                "JEUDI 11 MARS 2027 — Dernier jour pour formuler vos vœux\nJEUDI 1er AVRIL 2027 — Dernier jour pour compléter\n"
                "MARDI 1er JUIN 2027 — Début de la phase d’admission principale\n→ E ntre le vendredi 4 juin et le lundi 7 juin 2027 inclus : classez vos vœux en attente.\n"
                "JEUDI 10 JUIN 2027 — Début de la phase complémentaire\nSAMEDI 10 JUILLET 2027 — Fin de la phase principale\n"
                "JEUDI 9 SEPTEMBRE 2027 — Fin de la phase complémentaire")
    cases = {
        "agree": ([good, good], {"carte": "2026-12-17", "fin_principale": "2027-07-10", "classement": "2027-06-04"}),
        "disagree": ([good, good.replace("SAMEDI 10 JUILLET 2027", "SAMEDI 17 JUILLET 2027")], {"fin_principale": None, "carte": "2026-12-17"}),
        "weekday": ([good.replace("JEUDI 9 SEPTEMBRE 2027", "VENDREDI 9 SEPTEMBRE 2027")], {"fin_complementaire": None}),
        "missing": ([good.replace("Fin de la phase principale", "Fin")], {"fin_principale": None, "admission": "2027-06-01"}),
        "range": ([good.replace("AU JEUDI 11 MARS", "AU JEUDI 11 JANVIER")], {"voeux": None}),        # a Monday, and before the start
        "range_ok": ([good.replace("AU JEUDI 11 MARS", "AU JEUDI 11 FÉVRIER")], {"voeux": "2027-01-18"}),  # a Thursday: a valid range
        "hostile": ([good.replace("Ouverture de la carte", HOSTILE)], {"carte": None}),
        # an impossible date (Codex, PR #52): that step unverified, the others kept, no crash
        "impossible": ([good.replace("JEUDI 11 MARS 2027 — Dernier", "JEUDI 31 FÉVRIER 2027 — Dernier")], {"fin_voeux": None, "carte": "2026-12-17"}),
        "impossible_range": ([good.replace("AU JEUDI 11 MARS", "AU JEUDI 30 FÉVRIER")], {"voeux": None, "admission": "2027-06-01"}),
        "none": ([], {"carte": None, "voeux": None}),
    }
    for name, (vs, want) in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            write_versions(Path(tmp), vs)
            got = {e["key"]: e["debut"] for e in C.calendar(Path(tmp))["evenements"]}
            for k, v in want.items():
                if got.get(k) != v:
                    bad.append((name, k, got.get(k), v))
    n = sum(e["verifie"] for e in real["evenements"])
    return not bad, f"{len(texts)} official versions, {n}/{len(real['evenements'])} steps verified; {len(bad)} problems {bad[:4]}"


# ---------------------------------------------------------------- T2 the .ics file
def parse_ics(s: str):
    if "\r\n" not in s or re.search(r"(?<!\r)\n", s):
        return None, "not CRLF"
    raw = s.split("\r\n")
    if any(len(x.encode()) > 75 for x in raw):
        return None, "line over 75 octets"
    lines = []
    for x in raw:
        if x.startswith(" "):
            lines[-1] += x[1:]
        elif x:
            lines.append(x)
    events, cur = [], None
    for x in lines:
        if x == "BEGIN:VEVENT":
            cur = {}
        elif x == "END:VEVENT":
            events.append(cur)
            cur = None
        elif cur is not None and ":" in x:
            k, v = x.split(":", 1)
            cur[k] = v
    return {"lines": lines, "events": events}, ""


@check("T2 the .ics file parsed independently: CRLF, folding, one all-day event per verified date, unique ids, escaping")
def t2(c: Ctx):
    C = M["CAL"]
    bad = []
    cal = C.calendar()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        write_versions(t, [v["text"] for v in C.versions()] or [""])
        crafted = C.calendar(t)
    crafted["evenements"] = [dict(e) for e in crafted["evenements"]]
    for e in crafted["evenements"]:
        e["sur_supcompass"] = "Virgule, point-virgule; antislash \\ et\nretour"
    if crafted["evenements"]:
        crafted["evenements"][0]["verifie"] = False          # dates still present: an unverified step must not be exported
    for label, cl in (("served", cal), ("crafted", crafted)):
        txt = C.ics(cl)
        parsed, err = parse_ics(txt)
        if not parsed:
            bad.append((label, err)); continue
        if parsed["lines"][0] != "BEGIN:VCALENDAR" or parsed["lines"][-1] != "END:VCALENDAR":
            bad.append((label, "envelope"))
        ver = [e for e in cl["evenements"] if e["verifie"]]
        if len(parsed["events"]) != len(ver):
            bad.append((label, "events", len(parsed["events"]), len(ver)))
        uids = [ev.get("UID") for ev in parsed["events"]]
        if len(set(uids)) != len(uids):
            bad.append((label, "uid"))
        for ev, e in zip(parsed["events"], ver):
            d1 = date.fromisoformat(e["debut"])
            d2 = date.fromisoformat(e["fin"] or e["debut"]) + timedelta(days=1)
            if ev.get("DTSTART;VALUE=DATE") != d1.strftime("%Y%m%d") or ev.get("DTEND;VALUE=DATE") != d2.strftime("%Y%m%d"):
                bad.append((label, e["key"], "dates", ev.get("DTSTART;VALUE=DATE"), ev.get("DTEND;VALUE=DATE")))
            if e["libelle"] not in ev.get("SUMMARY", "").replace("\\,", ","):
                bad.append((label, e["key"], "summary"))
            desc = ev.get("DESCRIPTION", "")
            if re.search(r"(?<!\\)[,;]", desc) or "\n" in desc:
                bad.append((label, e["key"], "escaping"))
        if C.ics(cl) != txt:
            bad.append((label, "not the same file twice"))
    return not bad, f"{len(cal['evenements'])} steps; {len(bad)} problems {bad[:4]}"


# ---------------------------------------------------------------- T3 routes and register
@check("T3 routes, cache, fetch script, source register, Vercel bundle")
def t3(c: Ctx):
    bad = []
    with client(c.db) as tc:
        n0 = len(tc.events)
        r = tc.get("/api/calendrier")
        cc = r.headers.get("cache-control", "")
        if r.status_code != 200 or "s-maxage" not in cc or cc.startswith("no-store"):
            bad.append(("calendar", r.status_code, cc))
        if r.json() != json.loads(json.dumps(M["CAL"].calendar())):
            bad.append("the route is not calendrier.calendar()")
        r2 = tc.get("/api/calendrier.ics")
        if r2.status_code != 200 or not r2.headers.get("content-type", "").startswith("text/calendar") \
                or "attachment" not in r2.headers.get("content-disposition", "") or "s-maxage" not in r2.headers.get("cache-control", ""):
            bad.append(("ics", r2.status_code, dict(r2.headers)))
        if r2.text != M["CAL"].ics(M["CAL"].calendar()):
            bad.append("the .ics route is not the module's file")
        if tc.get("/api/calendrier", params={"x": "<b>"}).json() != r.json():
            bad.append("a parameter changes the answer")
        if len(tc.events) != n0:
            bad.append("an audience event recorded")
        # nothing verified: no empty VCALENDAR (not a valid file), a 404
        empty = types.SimpleNamespace(**{k: getattr(M["CAL"], k) for k in dir(M["CAL"]) if not k.startswith("__")})
        empty.calendar = lambda base=None: {**M["CAL"].calendar(), "evenements": [{**e, "verifie": False, "debut": None, "fin": None}
                                                                              for e in M["CAL"].calendar()["evenements"]]}
        from suptracker import api as _api
        saved_cal = _api.CALR
        _api.CALR = empty
        try:
            if tc.get("/api/calendrier.ics").status_code != 404:
                bad.append("an empty .ics served")
        finally:
            _api.CALR = saved_cal
    if '(r"/api/calendrier", PUBLIC,' not in c.cache or '(r"/api/calendrier\\.ics", PUBLIC,' not in c.cache:
        bad.append("cache policies")
    sys.path.insert(0, str(ROOT / "scripts"))
    import calendrier_fetch as F
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "request.json").write_text(json.dumps({"urls": ["https://evil.example/cal.pdf", "http://www.parcoursup.gouv.fr/x.pdf",
                                                                    "https://www.parcoursup.gouv.fr.evil.example/x.pdf"]}))
        Path(tmp, "fetch_log.json").write_text('[{"previous": true}]')
        rc = F.main(tmp)
        if rc == 0 or json.loads(Path(tmp, "fetch_log.json").read_text()) != [{"previous": True}]:
            bad.append("a run that read no PDF replaced the previous log")
        # a redirect off parcoursup.gouv.fr is refused even when the first address is official
        import httpx
        saved_get = F.httpx.get
        F.httpx.get = lambda url, **k: httpx.Response(200, content=b"%PDF-1.4", request=httpx.Request("GET", "https://evil.example/x.pdf"))
        try:
            Path(tmp, "request.json").write_text(json.dumps({"urls": ["https://www.parcoursup.gouv.fr/x.pdf"]}))
            F.main(tmp)
        finally:
            F.httpx.get = saved_get
        if any(p.suffix in (".pdf", ".txt") for p in Path(tmp).iterdir()):
            bad.append("a redirect to another host was saved")
    from suptracker import sources as S
    src = [s for s in S.SOURCES if s["key"] == "calendrier_parcoursup"]
    if not src or src[0]["access"] not in S.ACCESS or "parcoursup.gouv.fr" not in (src[0]["url"] or ""):
        bad.append("source register")
    ign = [ln.strip() for ln in (ROOT / ".vercelignore").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    def ignored(path):
        return any(fnmatch.fnmatch(path, p.rstrip("/") + ("/*" if p.endswith("/") else "")) or fnmatch.fnmatch(path, p) for p in ign)
    if not ignored("suptracker/data/calendrier/calendrier-parcoursup-2027-805.pdf") or ignored("suptracker/data/calendrier/calendrier-parcoursup-2027-805.pdf.txt") \
            or ignored("suptracker/data/calendrier/fetch_log.json"):
        bad.append("the Vercel bundle keeps the PDFs or drops the text")
    return not bad, f"{len(bad)} problems {bad[:4]}"


# ---------------------------------------------------------------- Node harness for the pages
HARNESS = r"""
let JV = null, CALLS = [], VOEUX = [], NOW = "2026-11-11";
const RealDate = Date;
globalThis.Date = class extends RealDate { constructor(...a) { if (a.length) super(...a); else super(`${NOW}T10:00:00`); } static now() { return new RealDate(`${NOW}T10:00:00`).getTime(); } };
const store = { d: {}, get(k, x) { return (k in this.d ? JSON.parse(JSON.stringify(this.d[k])) : undefined) ?? x; }, set(k, v) { this.d[k] = v; } };
const voeux = { MAX: 10, get: () => VOEUX.slice(), has: (c) => VOEUX.includes(c), add: (c) => { if (VOEUX.includes(c) || VOEUX.length >= 10) return false; VOEUX.push(c); return true; }, render() {} };
const els = {};
const node = (id) => ({ id, value: "", checked: false, onchange: null, onclick: null, textContent: "", innerHTML: "", disabled: false, focus() {}, select() {} });
const document = { getElementById: (id) => ($view.innerHTML.includes(`id="${id}"`) ? (els[id] = els[id] || node(id)) : null) };
globalThis.FormData = class { constructor() { this.v = FORM; } get(k) { return this.v[k] ?? null; } };
let FORM = {};
const $view = { dataset: {}, innerHTML: "", querySelectorAll: () => [] };
const location = { hash: "", origin: "https://supcompass.example", pathname: "/" };
const window = { print() { CALLS.push("print"); } };
const tip = () => "", feedbackBox = (p) => `<fb ${p}>`, profileBar = { render() {} };
let API = {};
const api = async (u) => { CALLS.push(u); for (const k of Object.keys(API)) if (u.startsWith(k)) { const v = API[k]; if (v instanceof Error) throw v; return JSON.parse(JSON.stringify(v)); } throw new Error("no stub " + u); };
const ZONES = { securite: { label: "Vœu de sécurité", color: "var(--zone-securite)" }, cible: { label: "Vœu cible", color: "var(--zone-cible)" }, ambitieux: { label: "Vœu ambitieux", color: "var(--zone-ambitieux)" } };
"""


def page_prog(c: Ctx) -> str:
    js = c.js
    parts = [top(js, n) for n in ("fmt", "pct", "pct1", "pc1", "esc", "vxProfile", "vxQuery", "REO_LABEL", "isReo", "profileLine",
                                  "REO_NO_ZONE", "reoWhy", "reoCell")]
    return HARNESS + "\n".join(parts) + block(js, BLOCK_START, BLOCK_END)


def run_page(c: Ctx, script: str, data):
    prog = page_prog(c) + "\n(async () => { const IN = JSON.parse(require('fs').readFileSync(0, 'utf8')); " + script + \
        " })().catch((e) => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });"
    return node(prog, data)


@check("T4 the calendar page at fixed dates: next step, countdown, states, unverified said, escaping, source, race")
def t4(c: Ctx):
    cal = M["CAL"].calendar()
    crafted = json.loads(json.dumps(cal))
    if crafted["evenements"]:
        crafted["evenements"][-1] = {**crafted["evenements"][-1], "debut": None, "fin": None, "verifie": False}
        crafted["evenements"][0] = {**crafted["evenements"][0], "libelle": HOSTILE}
    script = r"""
    const out = {};
    API = { "/api/calendrier": IN.cal };
    for (const day of ["2026-11-11", "2027-02-01", "2027-06-05", "2027-10-01"]) { NOW = day; await viewCalendrier(); out[day] = $view.innerHTML; }
    API = { "/api/calendrier": IN.crafted }; NOW = "2026-11-11"; await viewCalendrier(); out.crafted = $view.innerHTML;
    API = { "/api/calendrier": IN.none }; NOW = "2027-10-01"; await viewCalendrier(); out.none = $view.innerHTML;
    // a race: the page is left while the calendar loads
    API = { "/api/calendrier": IN.cal }; const slow = viewCalendrier(); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; await slow; out.race = $view.innerHTML;
    console.log(JSON.stringify(out));
    """
    none = {**cal, "evenements": [{**e, "verifie": False, "debut": None, "fin": None} for e in cal["evenements"]]}
    r = run_page(c, script, {"cal": cal, "crafted": crafted, "none": none})
    if r is None:
        return True, "node absent: skipped"
    if "error" in r:
        return False, r["error"]
    bad = []
    ev = {e["key"]: e for e in cal["evenements"]}
    if ev.get("carte", {}).get("verifie"):
        days = (date.fromisoformat(ev["carte"]["debut"]) - date(2026, 11, 11)).days
        if f"Prochaine étape dans {days} jours" not in r["2026-11-11"]:
            bad.append(("countdown", days))
    if ev.get("voeux", {}).get("verifie") and "En ce moment" not in r["2027-02-01"]:
        bad.append("an ongoing range is not said")
    if ev.get("classement", {}).get("verifie") and "En ce moment : <strong>Classez vos vœux en attente" not in r["2027-06-05"]:
        bad.append("the ongoing step on 5 June")
    if "est terminée" not in r["2027-10-01"]:
        bad.append("the end of the campaign")
    passe = len(re.findall(r'class="cal-item cal-passe"', r["2027-06-05"]))
    want = sum(1 for e in cal["evenements"] if e["verifie"] and (e["fin"] or e["debut"]) < "2027-06-05")
    if passe != want:
        bad.append(("past steps", passe, want))
    h = r["crafted"]
    if HOSTILE in h or "<img" in h:
        bad.append("unescaped label")
    if "date à vérifier sur parcoursup.gouv.fr" not in h:
        bad.append("an unverified date is not said")
    for need in ('href="/api/calendrier.ics"', "fait foi", "calendrier officiel Parcoursup", "Sur SupCompass"):
        if need not in r["2026-11-11"]:
            bad.append(("missing", need))
    if r["race"] != "OTHER PAGE":
        bad.append("a late answer drew over another page")
    if "est terminée" in r["none"] or "calendrier.ics" in r["none"] or "Les dates officielles n'ont pas pu être lues" not in r["none"]:
        bad.append("no date read: the page says the campaign is over or offers an empty .ics")
    return not bad, f"{len(bad)} problems {bad[:4]}"


@check("T5 seconde / première: the three doublettes, each cell its own share, ordered by destination, missing and rare said")
def t5(c: Ctx):
    stage = {}
    with client(c.db) as tc:
        jv = tc.get("/api/journey/vocab").json()
        sp = [x["code"] for x in jv["specialties"]]
        trio = [s for s in ("MATHS", "PC", "SVT") if s in sp] or sp[:3]
        trio = (trio + [s for s in sp if s not in trio])[:3]
        for a, b in ((trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2])):
            r = tc.get("/api/journey/stage1", params={"spe1": a, "spe2": b})
            stage[f"{a}+{b}"] = r.json() if r.status_code == 200 else None
    first = next((v for v in stage.values() if v and v["filieres"]), None)
    if not first:
        return False, "no stage-1 answer to render"
    crafted = json.loads(json.dumps(first))
    crafted["filieres"][0] = {**crafted["filieres"][0], "label": HOSTILE, "rare": True}
    script = r"""
    const out = {}; JV = IN.jv;
    const keys = Object.keys(IN.stage);
    API = {};
    for (const k of keys) { const [a, b] = k.split("+"); API[`/api/journey/stage1?spe1=${a}&spe2=${b}`] = IN.stage[k] || new Error("Doublette absente des données SIES 2022–2025"); }
    store.d = { premiere: IN.trio }; await viewPremiere(); out.html = $view.innerHTML; out.calls = CALLS.slice();
    out.pairs = premiereDoublettes(IN.trio); out.pairsDup = premiereDoublettes([IN.trio[0], IN.trio[0], IN.trio[1]]);
    // a missing doublette and a crafted hostile, rare row
    const [a, b] = keys[1].split("+"); API[`/api/journey/stage1?spe1=${a}&spe2=${b}`] = new Error("Doublette absente des données SIES 2022–2025");
    const [c0, c1] = keys[0].split("+");
    API[`/api/journey/stage1?spe1=${c0}&spe2=${c1}`] = IN.crafted;
    await viewPremiere(); out.missing = $view.innerHTML;
    // stored hostile choices are ignored
    store.d = { premiere: ["<b>", IN.trio[0], "ZZZ"] }; CALLS = []; await viewPremiere(); out.hostile = $view.innerHTML; out.hostileCalls = CALLS.slice();
    store.d = { premiere: IN.trio }; API[`/api/journey/stage1?spe1=${a}&spe2=${b}`] = new Error("Erreur interne"); await viewPremiere(); out.down = $view.innerHTML;
    JV = null; API["/api/journey/vocab"] = IN.jv; const slow = viewPremiere(); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; await slow; out.race = $view.innerHTML;
    console.log(JSON.stringify(out));
    """
    r = run_page(c, script, {"jv": jv, "stage": stage, "trio": trio, "crafted": crafted})
    if r is None:
        return True, "node absent: skipped"
    if "error" in r:
        return False, r["error"]
    bad = []
    if [tuple(p) for p in r["pairs"]] != [(trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2])] or r["pairsDup"]:
        bad.append(("pairs", r["pairs"], r["pairsDup"]))
    h = r["html"]
    # each cell = that doublette's share in that filière (formatted like the page: one decimal, French comma)
    rows = re.findall(r'<tr><td data-label="Filière">(.*?)</td>(.*?)</tr>', h, re.S)
    keys = list(stage)
    lab = {f["label"]: f for f in first["filieres"]}
    order = []
    import html as H
    for name, cells in rows:
        name = H.unescape(name)
        vals = re.findall(r'<td class="num" data-label="[^"]+">(.*?)</td>', cells, re.S)
        order.append(name)
        for i, v in enumerate(vals):
            st = stage[keys[i]]
            f = next((x for x in (st["filieres"] if st else []) if x["label"] == name), None)
            want = "—" if not f else f"{100 * f['share']:.1f}".replace(".", ",").replace(",0", "") + " %"
            got = re.sub(r"<[^>]+>.*", "", v, flags=re.S).strip()
            if got.replace(" ", " ").replace("\xa0", " ") != want:
                bad.append((name, keys[i], got, want)); break
    dest = {}
    for st in stage.values():
        for f in (st["filieres"] if st else []):
            dest[f["label"]] = max(dest.get(f["label"], 0), f.get("destination_share") or 0)
    if [dest.get(n, 0) for n in order] != sorted([dest.get(n, 0) for n in order], reverse=True):
        bad.append("rows not ordered by destination share")
    if len(rows) != min(12, len(dest)):
        bad.append(("rows shown", len(rows)))
    for td in re.findall(r"<td(?![^>]*data-label=)[^>]*>", h):
        bad.append(("cell without data-label", td)); break
    m = r["missing"]
    if "absente des données 2022–2025" not in m or HOSTILE in m or "<img" in m or "rare (moins de 20 candidats)" not in m:
        bad.append("missing doublette, escaping or rare flag")
    if "Choisissez trois spécialités différentes" not in r["hostile"] or any("stage1" in u for u in r["hostileCalls"]):
        bad.append("stored hostile choices used")
    if "lecture impossible pour le moment" not in r["down"]:
        bad.append("a server failure is said as an absent doublette")
    if r["race"] != "OTHER PAGE":
        bad.append("a late answer drew over another page")
    if "pas un conseil de spécialités ni une chance d'admission" not in h:
        bad.append("the caveat")
    return not bad, f"doublettes {keys}; {len(rows)} rows; {len(bad)} problems {bad[:4]}"


@check("T6 the shared list: validation, link round trip, profile only on request, reading per profile, merge never replaces")
def t6(c: Ctx):
    with client(c.db) as tc:
        jv = tc.get("/api/journey/vocab").json()
        import duckdb
        con = duckdb.connect(str(c.db), read_only=True)
        cods = [x[0] for x in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session)
            FROM core.formation_year) ORDER BY cod_aff_form LIMIT 3""").fetchall()]
        con.close()
        prof = {"serie": "bg", "spe1": jv["specialties"][0]["code"], "spe2": jv["specialties"][1]["code"], "mention": "b", "academie": "Lyon",
                "lycee": {"uai": "0690000A", "nom": "X"}, "statut": "terminale"}
        from urllib.parse import urlencode
        q = urlencode({"ids": ",".join(cods), "serie": "bg", "mention": "b", "spe1": prof["spe1"], "spe2": prof["spe2"]})
        vx = tc.get(f"/api/voeux?{q}").json()
        vxp = tc.get(f"/api/voeux?{urlencode({'ids': ','.join(cods), 'serie': 'bp', 'mention': 'b'})}").json()
        ro = tc.get("/api/reorientation/voeux", params={"ids": ",".join(cods)}).json()
    vx["voeux"][0] = {**vx["voeux"][0], "etablissement": HOSTILE}
    script = r"""
    const out = {}; JV = IN.jv;
    out.codes = shareCodes("12,abc,12,<b>,1234567890, 3 ," + Array.from({ length: 12 }, (_, i) => 100 + i).join(","));
    out.p0 = shareProfile("s=bg&a=" + IN.p.spe1 + "&b=" + IN.p.spe2 + "&m=b&academie=Lyon&lycee=X&z=1");
    out.pBad = shareProfile("s=bg&a=" + IN.p.spe1 + "&b=" + IN.p.spe1 + "&m=b");
    out.pHost = shareProfile("s=<b>&m=<i>");
    out.pReo = shareProfile("t=r&s=bg");
    out.link0 = shareLink(IN.cods, null);
    out.link1 = shareLink(IN.cods, vxProfile(IN.p));
    out.round = shareProfile(out.link1.split("/").pop());
    out.linkReo = shareLink(IN.cods, vxProfile({ statut: "reorientation", academie: "Lyon" }));
    // the page: joined terminale profile -> zones from /api/voeux; none -> official rates; reorientation -> estimate
    API = { "/api/voeux": IN.vx, "/api/reorientation/voeux": IN.ro };
    CALLS = []; await viewListe(IN.cods.join(","), out.link1.split("/").pop()); out.zoned = $view.innerHTML; out.zonedCalls = CALLS.slice();
    CALLS = []; await viewListe(IN.cods.join(","), ""); out.plain = $view.innerHTML; out.plainCalls = CALLS.slice();
    CALLS = []; await viewListe(IN.cods.join(","), "t=r"); out.reo = $view.innerHTML;
    API["/api/voeux"] = IN.vxp; await viewListe(IN.cods.join(","), "s=bp&m=b"); out.bp = $view.innerHTML; API["/api/voeux"] = IN.vx;
    await viewListe(IN.cods.join(","), "s=xx&m=b"); out.unread = $view.innerHTML;
    out.linkBp = shareLink(IN.cods, vxProfile({ serie: "bp", mention: "b", voie: "autre", voie_label: "ASSP" }));   // "autre" is kept on any warehouse
    JV = null; API["/api/journey/vocab"] = IN.jv; const slow0 = viewListe(IN.cods.join(","), ""); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; await slow0; out.race0 = $view.innerHTML; JV = IN.jv;
    $view.innerHTML = shareCard(IN.cods, false); bindShare(IN.cods, null); out.cardNone = $view.innerHTML; out.urlNone = els["share-url"].value;
    // merge: 9 vœux already, three shared -> one added, the student's own list and profile kept
    VOEUX = ["1", "2", "3", "4", "5", "6", "7", "8", IN.cods[0]]; store.d = { profile: { serie: "bt", mention: "tb" } };
    await viewListe(IN.cods.join(","), out.link1.split("/").pop()); out.mergeHtml = $view.innerHTML; els["liste-add"].onclick();
    out.after = VOEUX.slice(); out.profileAfter = store.get("profile", null);
    // a race
    const slow = viewListe(IN.cods.join(","), ""); $view.innerHTML = "OTHER PAGE"; $view.dataset.rendered = "other"; await slow; out.race = $view.innerHTML;
    // the share card: the box off -> no profile in the link
    $view.innerHTML = shareCard(IN.cods, true); bindShare(IN.cods, vxProfile(IN.p)); out.card = $view.innerHTML; out.url0 = els["share-url"] ? els["share-url"].value : null;
    els["share-prof"].checked = true; els["share-prof"].onchange(); out.url1 = els["share-url"].value;
    console.log(JSON.stringify(out));
    """
    r = run_page(c, script, {"jv": jv, "p": prof, "cods": cods, "vx": vx, "ro": ro, "vxp": vxp})
    if r is None:
        return True, "node absent: skipped"
    if "error" in r:
        return False, r["error"]
    bad = []
    # bac pro: the official column is the official rate, never the series estimate
    import html as H
    for v in vxp["voeux"]:
        if v.get("status") == "ok":
            row = re.search(rf'href="#/f/{v["cod_aff_form"]}">.*?</tr>', r["bp"], re.S)
            cell = re.search(r'data-label="Taux d\'accès officiel[^"]*">(.*?)</td>', row.group(0), re.S) if row else None
            want = "—" if v.get("taux_acces_all") is None else (f"{v['taux_acces_all']:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " %")
            if not cell or H.unescape(cell.group(1)).replace("\u202f", " ").strip() != want:
                bad.append(("bac pro: an estimate under the official label", v["cod_aff_form"], cell and cell.group(1), want)); break
    if "Le profil joint n'a pas pu être lu" not in r["unread"]:
        bad.append("an unreadable joined profile is said as none")
    if "v=" in r["linkBp"] or "autre" in r["linkBp"] or "ASSP" in r["linkBp"]:
        bad.append(("the bac pro route in the link", r["linkBp"]))
    if r["race0"] != "OTHER PAGE":
        bad.append("a late answer drew over another page before the vocabulary")
    if 'id="share-prof"' in r["cardNone"] or r["urlNone"] != f"https://supcompass.example/#/liste/{','.join(cods)}":
        bad.append("no stored profile: the box is offered or a profile is shared")
    for fn in ("viewVoeux", "viewVoeuxReo"):
        body = c.js[c.js.index(f"async function {fn}("):]
        body = body[:body.index("\n}\n")]
        if 'bindShare(ids, store.get("profile", null) ? prof : null);' not in body or 'shareCard(ids, !!store.get("profile", null))' not in body:
            bad.append(("Mes vœux shares a default profile", fn))
    if not re.search(r'const TAB_OF = \{[^}]*liste: "liste"', c.js) or 'this.tab === "liste"' not in top(c.js, "profileBar"):
        bad.append("the shared list shows the recipient's own tab and profile bar")
    if r["codes"] != ["12", "3", "100", "101", "102", "103", "104", "105", "106", "107"]:
        bad.append(("codes", r["codes"]))
    p0 = r["p0"] or {}
    if p0.get("serie") != "bg" or p0.get("spe1") != prof["spe1"] or "academie" in p0 or "lycee" in p0 or "z" in p0:
        bad.append(("profile whitelist", p0))
    if r["pBad"] is not None or r["pHost"] is not None:
        bad.append(("invalid profiles accepted", r["pBad"], r["pHost"]))
    if not r["pReo"] or r["pReo"].get("statut") != "reorientation":
        bad.append(("reorientation profile", r["pReo"]))
    if r["link0"] != f"https://supcompass.example/#/liste/{','.join(cods)}":
        bad.append(("link without profile", r["link0"]))
    rd = r["round"] or {}
    if (rd.get("serie"), rd.get("spe1"), rd.get("spe2"), rd.get("mention")) != ("bg", prof["spe1"], prof["spe2"], "b"):
        bad.append(("round trip", rd))
    for lk in (r["link1"], r["linkReo"], r["url1"] or ""):
        if "Lyon" in lk or "academie" in lk or "lycee" in lk or "0690000A" in lk:
            bad.append(("the académie or the lycée in a link", lk))
    if not r["linkReo"].endswith("/t=r"):
        bad.append(("reorientation link", r["linkReo"]))
    if r["url0"] != r["link0"] or r["url1"] != r["link1"]:
        bad.append(("the card's link", r["url0"], r["url1"]))
    if not any(u.startswith("/api/voeux?") for u in r["zonedCalls"]) or "Zone pour ce profil" not in r["zoned"]:
        bad.append("a joined profile is not read with zones")
    if HOSTILE in r["zoned"] or "<img" in r["zoned"]:
        bad.append("unescaped name")
    if any(u.startswith("/api/voeux?") for u in r["plainCalls"]) or "Zone" in r["plain"] or "Aucun profil n'a été joint" not in r["plain"]:
        bad.append("zones read without a joined profile")
    for h, lab in ((r["zoned"], "zoned"), (r["plain"], "plain"), (r["reo"], "reo")):
        if not all(f'href="#/f/{cod}"' in h for cod in cods):
            bad.append(("the list is not shown", lab))
    if "Accès estimé hors terminale" not in r["reo"] or "Zone pour ce profil" in r["reo"]:
        bad.append("reorientation reading")
    for h in (r["zoned"], r["plain"], r["reo"]):
        for td in re.findall(r"<td(?![^>]*data-label=)[^>]*>", h):
            bad.append(("cell without data-label", td)); break
        if "pas des chances d'admission" not in h:
            bad.append("caveat")
    if r["after"] != ["1", "2", "3", "4", "5", "6", "7", "8", cods[0], cods[1]] or r["profileAfter"] != {"serie": "bt", "mention": "tb"}:
        bad.append(("merge", r["after"], r["profileAfter"]))
    if "ne seront pas ajoutée" not in r["mergeHtml"] and "ne sera pas ajoutée" not in r["mergeHtml"]:
        bad.append("the merge does not say what is left out")
    if r["race"] != "OTHER PAGE":
        bad.append("a late answer drew over another page")
    if "Le lien lui-même n'est jamais envoyé au serveur" not in r["card"] or "jamais l'académie ni le lycée" not in r["card"]:
        bad.append("the share card's privacy line")
    return not bad, f"{len(bad)} problems {bad[:5]}"


@check("T7 wording and wiring: no chance, vouvoiement, routes, tabs, menus, analytics, share card, print, features, docs")
def t7(c: Ctx):
    js, bad = c.js, []
    sec = block(js, BLOCK_START, BLOCK_END)
    text = " ".join(a or b or q for a, b, q in re.findall(r"`([^`]*)`|\"([^\"]*)\"|'([^'\n]*)'", sec))
    C = M["CAL"]                                             # the module in use (a mutant included), not the file on disk
    text += " " + " ".join([*C.SUR_SUPCOMPASS.values(), *C.STEPS.values(), *(r[2] for r in C.RULES)])
    words = re.sub(r"<[^>]+>|\$\{[^}]*\}", " ", text)
    if CHANCE.search(words):
        bad.append(("chance wording", CHANCE.search(words).group(0)))
    if FORMAL.search(words):
        bad.append(("tutoiement", FORMAL.search(words).group(0)))
    for name, fn in (("calendrier", "viewCalendrier()"), ("accompagner", "viewAccompagner()"), ("premiere", "viewPremiere()"),
                     ("liste", 'viewListe(b || "", c || "")')):
        if f'if (a === "{name}") return' not in js or fn not in js.split(f'if (a === "{name}") return', 1)[-1].split("\n", 1)[0]:
            bad.append(("route", name))
        if not re.search(rf'const ROUTE_NAME = \{{[^}}]*\b{name}: "{name}"', js):
            bad.append(("route name", name))
        if f'"{name}"' not in c.analytics.split("ROUTES = (", 1)[1].split(")", 1)[0]:
            bad.append(("analytics route", name))
    if not re.search(r'const TAB_OF = \{[^}]*liste: "liste"', js) or not re.search(r'const MORE_TABS = \[[^\]]*"calendrier", "accompagner"\]', js):
        bad.append("tabs")
    for href in ("#/calendrier", "#/accompagner"):
        if c.html.count(f'href="{href}"') != 2:
            bad.append(("menus", href))
    if 'href="#/premiere"' not in top(js, "viewHome"):
        bad.append("home link to seconde / première")
    for fn in ("viewVoeux", "viewVoeuxReo"):
        body = js[js.index(f"async function {fn}("):]
        body = body[:body.index("\n}\n")]
        if "${shareCard(ids, " not in body or "bindShare(ids, " not in body or 'class="print-only' not in body:
            bad.append(("share card, binding or print line", fn))
    pm = re.search(r"@media print \{(.*?)\n\}", c.css, re.S)
    pr = re.search(r":root:root:root \{([^}]*)\}", pm.group(1) if pm else "")
    if not pr or not all(t in pr.group(1) for t in ("--ink: #000000;", "--surface: #ffffff;", "--bg: #ffffff;", "--warn-bg: #ffffff;", "--muted: #444444;")):
        bad.append("print keeps the dark theme's colours")
    if not pm or not all(x in pm.group(1) for x in ("nav", ".tabbar", "#profile-bar", ".no-print", "button", ".print-only { display: block")) \
            or ".print-only { display: none; }" not in c.css:
        bad.append("print styles")
    dec = node(top(c.js, "safeDecode") + 'console.log(JSON.stringify([safeDecode("%E0%A4%A"), safeDecode("a%20b")]))')
    if dec is not None and dec != ["%E0%A4%A", "a b"]:
        bad.append(("a malformed link breaks the router", dec))
    if ".map(safeDecode)" not in top(c.js, "route"):
        bad.append("the router does not decode safely")
    for k in ("calendrier", "accompagner", "premiere", "liste_partagee"):
        if f'"{k}"' not in c.api.split("FEATURES = [", 1)[1].split("]", 1)[0]:
            bad.append(("feature", k))
    rel = (ROOT / "tests" / "test_release.py").read_text()
    if '"liste_partagee": ("app.js", "async function viewListe(")' not in rel:
        bad.append("release guard")
    if 'calendrier: "Calendrier"' not in c.stats:
        bad.append("dashboard labels")
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    if "Sprint 22" not in readme:
        bad.append("README")
    claude = ROOT.parent / "CLAUDE.md"
    if claude.exists() and "calendrier.py" not in claude.read_text():
        bad.append("CLAUDE.md")
    return not bad, f"{len(bad)} problems {bad[:5]}"


# ---------------------------------------------------------------- T8 mutation test
PY_MUTANTS = [
    ("weekday not checked", "return d, WEEKDAYS[d.weekday()] == wd", "return d, True"),
    ("impossible date crashes", '''    except ValueError:                                  # "31 février": an impossible date leaves the step unverified (Codex)\n        return None, False''',
     "    except ZeroDivisionError:\n        return None, False"),
    ("versions not compared", 'and len({(f["debut"], f["fin"]) for f in found}) == 1', ""),
    ("first version only", "found = [p.get(key) for p in parsed]", "found = [p.get(key) for p in parsed[:1]]"),
    ("drop cap not read", 'r"e ?ntre le\\s+"', 'r"entre le\\s+"'),
    ("range year on the start", "d1, ok1 = _date(g[0], g[1], g[2], g[6])", "d1, ok1 = _date(g[0], g[1], g[2], str(int(g[6]) - 1))"),
    ("ics end not exclusive", "end = date.fromordinal(d2.toordinal() + 1)", "end = d2"),
    ("ics not folded", 'if len((cur + ch).encode()) > (75 if not out else 74):', "if False:"),
    ("ics commas not escaped", '.replace(",", "\\\\,")', ""),
    ("ics unverified dates", '        if not e["verifie"]:\n            continue\n        d1', "        d1"),
    ("tutoiement in the calendar", "Vérifiez sur parcoursup.gouv.fr que les formations", "Vérifie sur parcoursup.gouv.fr que tes formations"),
    ("ics stamp from the clock", 'stamp = (cal.get("lu_le") or "2026-01-01").replace("-", "") + "T000000Z"',
     'import time as _t; stamp = _t.strftime("%Y%m%dT%H%M%SZ", _t.gmtime(_t.time() + __import__("random").random() * 1e6))'),
]
JS_MUTANTS = [
    ("countdown off by one", "Prochaine étape dans ${fmt(daysBetween(today, next.debut))}", "Prochaine étape dans ${fmt(daysBetween(today, next.debut) + 1)}"),
    ("unverified date not said", '(!e.verifie ? `<span class="muted">date à vérifier sur parcoursup.gouv.fr</span>`', '(!e.verifie ? ""'),
    ("calendar label unescaped", '<div class="cal-what">${esc(e.libelle)}</div>', '<div class="cal-what">${e.libelle}</div>'),
    ("calendar race", '  const d = await api("/api/calendrier");\n  if ($view.dataset.rendered !== marker) return;', '  const d = await api("/api/calendrier");'),
    ("source line dropped", "En cas de différence, le calendrier officiel fait foi.", ""),
    ("pairs wrong", "return [[s[0], s[1]], [s[0], s[2]], [s[1], s[2]]];", "return [[s[0], s[1]], [s[0], s[2]], [s[0], s[2]]];"),
    ("cell shows the destination share", "${pc1(f.share)}<div", "${pc1(f.destination_share)}<div"),
    ("rows by name", "rows = [...by.values()].sort((a, b) => b.dest - a.dest || a.label.localeCompare(b.label, \"fr\"))",
     "rows = [...by.values()].sort((a, b) => a.label.localeCompare(b.label, \"fr\"))"),
    ("stored choices not validated", '.filter((c) => typeof c === "string" && codes.has(c))', '.filter((c) => typeof c === "string")'),
    ("missing doublette not said", ': "absente des données 2022–2025"}', ': ""}'),
    ("codes not validated", 'if (/^\\d{1,9}$/.test(c) && !out.includes(c)', "if (c && !out.includes(c)"),
    ("académie shared", 'const SHARE_KEYS = { s: "serie", a: "spe1", b: "spe2", m: "mention", t: "statut" };',
     'const SHARE_KEYS = { s: "serie", a: "spe1", b: "spe2", m: "mention", t: "statut", academie: "academie" };'),
    ("profile always in the link", "url.value = shareLink(ids, box && box.checked ? prof : null);", "url.value = shareLink(ids, prof);"),
    ("zones without a profile", "const zoned = prof && !isReo(prof);", "const zoned = !isReo(prof);"),
    ("merge replaces the list", "for (const c of fresh) if (voeux.add(c)) n++;", 'VOEUX = []; for (const c of fresh) if (voeux.add(c)) n++;'),
    ("list race", "  if ($view.dataset.rendered !== marker) return;\n  const rows = d.voeux.map", "  const rows = d.voeux.map"),
    ("list name unescaped", '<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere || v.formation || "")}',
     '<a href="#/f/${esc(v.cod_aff_form)}">${v.etablissement}</a><div class="muted small">${esc(v.filiere || v.formation || "")}'),
    ("share card dropped outside terminale", "rien n'en est enregistré sur le serveur.</p>${howto}</div>${shareCard(ids, !!store.get(\"profile\", null))}",
     "rien n'en est enregistré sur le serveur.</p>${howto}</div>"),
    ("chance wording", "Des parts d'admis des campagnes passées, pas des chances d'admission. Les vœux", "Vos chances d'admission. Les vœux"),
    ("tutoiement", "Choisissez trois spécialités de première.", "Choisis tes trois spécialités de première."),
]
JS_MUTANTS += [
    ("bac pro estimate as official", '(prof.serie === "bg" ? v.taux_acces_ens : v.taux_acces_all)', "v.taux_acces_ens"),
    ("default profile shared", 'bindShare(ids, store.get("profile", null) ? prof : null);             // sprint 22: never a default profile (review)\n}',
     "bindShare(ids, prof);\n}"),
    ("box without a profile", '${withProfile ? `<label class="small"><input type="checkbox" id="share-prof">', '${true ? `<label class="small"><input type="checkbox" id="share-prof">'),
    ("over when nothing read", '  const head = !nOk ? "Les dates officielles n\'ont pas pu être lues : vérifiez-les sur parcoursup.gouv.fr."\n    : next', "  const head = next"),
    ("list race before vocabulary", '  JV = JV || await api("/api/journey/vocab").catch(() => null);\n  if ($view.dataset.rendered !== marker) return;',
     '  JV = JV || await api("/api/journey/vocab").catch(() => null);'),
    ("premiere race", '  JV = JV || await api("/api/journey/vocab");\n  if ($view.dataset.rendered !== first) return;', '  JV = JV || await api("/api/journey/vocab");'),
    ("failure said absent", '/absente/i.test(e.message) ? "absente" : "indisponible"', '"absente"'),
    ("codes not trimmed", "const c = c0.trim();", "const c = c0;"),
    ("route in the link", '    if (prof.serie === "bg") { q.set("a", prof.spe1 || "MATHS"); q.set("b", prof.spe2 || "SES"); }\n  }',
     '    if (prof.serie === "bg") { q.set("a", prof.spe1 || "MATHS"); q.set("b", prof.spe2 || "SES"); }\n    else if (prof.voie) q.set("v", prof.voie);\n  }'),
    ("unsafe decoding", "function safeDecode(x) { try { return decodeURIComponent(x); } catch (_) { return x; } }", "function safeDecode(x) { return decodeURIComponent(x); }"),
    ("profile bar on a shared list", 'if (this.tab === "stats" || this.tab === "liste")', 'if (this.tab === "stats")'),
]
TEXT_MUTANTS = [("cache", "calendar shared nowhere", '(r"/api/calendrier", PUBLIC,', '(r"/api/calendrier", NO_STORE,'),
                ("css", "print keeps the menus", "  header, nav, .tabbar,", "  header,"),
                ("css", "print in dark colours", "  :root:root:root { --bg: #ffffff;", "  :root:root:root { --bgx: #ffffff;"),
                ("html", "menu link dropped", '  <a href="#/accompagner" data-tab="accompagner">Accompagner un élève</a>\n</div>', "</div>")]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "calendrier.py"
    src = path.read_text()
    if src.count(old) != 1:
        return None
    m = types.ModuleType("suptracker._mut_calendrier")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules[m.__name__] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("T8 mutation test: calendar, .ics, pages, sharing, wording and wiring bugs are each caught")
def t8(c: Ctx):
    fns = [t1, t2, t7, t4, t5, t6, t3]
    missed = []

    def caught():
        for fn in fns:
            try:
                if not fn(c)[0]:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False
    for name, old, new in PY_MUTANTS:
        m = mutated(old, new)
        if m is None:
            missed.append(f"{name} (anchor gone)"); continue
        saved, M["CAL"] = M["CAL"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["CAL"] = saved
            sys.modules.pop("suptracker._mut_calendrier", None)
    for name, old, new in JS_MUTANTS:
        src = c.js
        if src.count(old) != 1:
            missed.append(f"{name} (anchor: {src.count(old)})"); continue
        c.js = src.replace(old, new, 1)
        try:
            if not caught():
                missed.append(name)
        finally:
            c.js = src
    for attr, name, old, new in TEXT_MUTANTS:
        src = getattr(c, attr)
        if src.count(old) != 1:
            missed.append(f"{name} (anchor gone)"); continue
        setattr(c, attr, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, attr, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS) + len(TEXT_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, checks=None) -> list[dict]:
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
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
