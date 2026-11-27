"""Red team: « Portes ouvertes et webinaires » of the student's list and « près de chez moi » (owner, 2026-11-27, PR 16).

    python scripts/redteam_portes.py [--db data/suptracker.duckdb] [--real] [--browser]

  PO1 the agenda follows the formation page's rules: every event's formations carry that date in jpo.for_formation, and every
      sampled formation whose block has dates is in the agenda under each of them (one event per establishment, day and kind)
  PO2 coverage measured, never typed: n_formations = the search page's rows, n_avec_date = formations with a date; events
      unique, formations sorted; the concours's sessions = for_concours
  PO3 the list: for_list = for_formation code by code, the concours once; bad codes / more than 10 = 422; the list routes are
      no-store and record no audience event; the agenda takes no parameter and is shared-cached
  PO4 the .ics: coming dates only, one event per establishment, day and kind, each with its source and « À vérifier », RFC 5545
      folding (75 octets), escaped commas, CRLF; the concours's sessions once
  PO5 the page twins (Node): jpoListeEvents (coming only, grouped), poKeep (period, type, radius never applied to an online session,
      keyword), the order (date, then distance, never a figure), escaping, five dates first; the town never in a request
  PO6 browser: the Mes vœux block and the page, a filter changes the list, wide and phone, 0 JS error, no horizontal scroll
  PO7 mutation test
  PO8 wiring and docs
"""
from __future__ import annotations

import argparse
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
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []

import nodefile  # noqa: E402
import redteam_robustesse as RB  # noqa: E402

top = RB.top
HOSTILE = '<img src=x onerror=alert(1)>'
TODAY = date(2026, 11, 27)


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool, browser: bool):
        import duckdb
        self.db, self.real, self.browser = Path(db), real, browser
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.src = (ROOT / "suptracker" / "jpo.py").read_text()
        self.J = None
        self._agenda = None

    def jpo(self):
        if self.J is None:
            from suptracker import jpo
            self.J = jpo
        return self.J

    def agenda(self):
        if self._agenda is None or self._agenda[0] is not self.J:
            self._agenda = (self.J, self.jpo().agenda(self.con, TODAY))
        return self._agenda[1]


# ------------------------------------------------------------------ PO1
def crafted_agenda(J) -> list:
    """The rarer paths on a crafted warehouse (the real season may have none): a date read ONLY on the formation's own fiche, one
    only through its university, an online and an on-site session the same day at the same establishment (two events)."""
    import duckdb
    from suptracker import carte as CA
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year AS SELECT * FROM (VALUES ('1', 'U1', 2025, 'BTS', 'X'), ('2', 'U2', 2025, 'BTS', 'Y'),"
                " ('3', 'U3', 2025, 'Licence', 'Z')) t(cod_aff_form, cod_uai, session, lib_for_voe_ins, lib_comp_voe_ins)")
    con.execute("CREATE TABLE core.cartographie (cod_aff_form VARCHAR, etab_uai VARCHAR)")
    con.execute(f"CREATE TABLE jpo_date AS SELECT * FROM (VALUES ('U1', DATE '2027-01-10', false), ('U1', DATE '2027-01-10', true),"
                f" ('{J.fiche_key('2')}', DATE '2027-02-01', false), ('U4', DATE '2027-03-01', false)) t(uai, debut, virtuel)")
    con.execute("CREATE TABLE jpo_etab AS SELECT * FROM (VALUES ('U3', 'U4')) t(uai, univ_uai)")
    rows = [{"cod_aff_form": c, "formation": f"F{c}", "etablissement": f"E{c}", "lat": 45.0, "lon": 5.0, "ville": "V"} for c in "123"]
    d = lambda u, day, v, src="onisep": {"uai": u, "date": day, "fin": None, "virtuel": v, "source": src, "nom": f"N{u}"}  # noqa: E731
    fake = {"1": {"dates": [d("U1", "2027-01-10", False), d("U1", "2027-01-10", True)]},
            "2": {"dates": [d("U2", "2027-02-01", False, "fiche")]},
            "3": {"dates": [d("U4", "2027-03-01", False)], "universite": {"nom": "Université X"}}}
    saved = (J._src, J._for_formation, CA._layer)
    try:
        J._src = lambda _con: (con, "")
        J._for_formation = lambda _con, cod, _t: fake.get(cod)
        CA._layer = lambda _con: ({"BTS": rows}, None, None)
        A = J.agenda(con, TODAY)
    finally:
        J._src, J._for_formation, CA._layer = saved
        con.close()
    got = sorted((e["uai"], e["date"], e["virtuel"], tuple(e["formations"])) for e in A["evenements"])
    want = [("U1", "2027-01-10", False, ("1",)), ("U1", "2027-01-10", True, ("1",)), ("U2", "2027-02-01", False, ("2",)),
            ("U4", "2027-03-01", False, ("3",))]
    bad = [] if got == want else [("crafted agenda: fiche-only, university-only, online + on-site the same day", got)]
    if not any(e["universite"] and e["nom"] == "Université X" for e in A["evenements"]):
        bad.append("crafted agenda: the university's name")
    return bad


@check("PO1 the agenda follows the formation page's rules (both ways, one event per establishment, day and kind)")
def po1(c: Ctx):
    J = c.jpo()
    A = c.agenda()
    bad = []
    evs = A["evenements"]
    rnd = random.Random(16)
    sample = evs if len(evs) <= 300 else rnd.sample(evs, 300)
    for e in sample:
        for cod in e["formations"][:3]:
            b = J._for_formation(c.con, cod, TODAY) or {}
            if not any(d["uai"] == e["uai"] and d["date"] == e["date"] and bool(d["virtuel"]) == e["virtuel"] for d in b.get("dates") or []):
                bad.append(("an event's formation lacks the date", cod, e["uai"], e["date"]))
                break
    from suptracker import carte as CA
    by_dip, _, _ = CA._layer(c.con)
    rows = [f["cod_aff_form"] for fs in by_dip.values() for f in fs]
    idx = {}
    for e in evs:
        for cod in e["formations"]:
            idx.setdefault(cod, set()).add((e["uai"], e["date"], e["virtuel"]))
    # random formations, plus EVERY formation dated through its university or its own fiche (the rarer paths of the rules)
    sample_f = set(rows if len(rows) <= 1500 else rnd.sample(rows, 1500))
    src, pre = J._src(c.con)
    if src is not None:
        lo, hi = J.window(J.current_season(TODAY))
        live = {r[0] for r in src.execute(f"SELECT DISTINCT uai FROM {pre}jpo_date WHERE debut BETWEEN ? AND ?", [lo, hi]).fetchall()}
        univ_live = {u for u, uu in src.execute(f"SELECT uai, univ_uai FROM {pre}jpo_etab WHERE univ_uai IS NOT NULL").fetchall() if uu in live}
        sies = dict(c.con.execute("SELECT cod_aff_form, any_value(cod_uai ORDER BY session DESC) FROM core.formation_year GROUP BY 1").fetchall())
        sample_f |= {cod for cod in rows if J.fiche_key(cod) in live or str(sies.get(cod) or "").strip().upper() in univ_live}
    for cod in sorted(sample_f):
        b = J._for_formation(c.con, cod, TODAY) or {}
        want = {(d["uai"], d["date"], bool(d["virtuel"])) for d in b.get("dates") or []}
        if want != idx.get(cod, set()):
            bad.append(("a formation's dates differ from the agenda", cod, sorted(want)[:2], sorted(idx.get(cod, set()))[:2]))
            if len(bad) > 3:
                break
    keys = [(e["uai"], e["date"], e["virtuel"]) for e in evs]
    if len(keys) != len(set(keys)):
        bad.append("two events for one establishment, day and kind")
    bad += crafted_agenda(J)
    return not bad, f"{len(evs)} events, {len(sample)} checked; {len(sample_f)} formations re-read; problems {bad[:4]}"


# ------------------------------------------------------------------ PO2
@check("PO2 coverage measured (rows of the search page, formations with a date), events unique and sorted, concours = for_concours")
def po2(c: Ctx):
    J = c.jpo()
    A = c.agenda()
    bad = []
    from suptracker import carte as CA
    by_dip, _, _ = CA._layer(c.con)
    n = sum(len(fs) for fs in by_dip.values())
    if A["n_formations"] != n:
        bad.append(("n_formations", A["n_formations"], n))
    with_date = {cod for e in A["evenements"] for cod in e["formations"]}
    if A["n_avec_date"] != len(with_date) or set(A["formations"]) != with_date:
        bad.append(("n_avec_date", A["n_avec_date"], len(with_date)))
    if any(e["formations"] != sorted(set(e["formations"])) for e in A["evenements"]):
        bad.append("an event's formations unsorted or repeated")
    if [(e["date"], e["uai"], e["virtuel"]) for e in A["evenements"]] != sorted((e["date"], e["uai"], e["virtuel"]) for e in A["evenements"]):
        bad.append("events not sorted by date")
    for k, v in A["concours"].items():
        cb = J.for_concours(c.con, v["formations"][0], TODAY) or {}
        if cb.get("cle") != k or cb.get("dates") != v.get("dates"):
            bad.append(("a concours's sessions differ from for_concours", k))
    if "TODAY" in c.src or re.search(r"n_avec_date\"?\s*[:=]\s*\d", c.src):
        bad.append("a typed count or date in jpo.py")
    if c.real and not (0.05 < A["n_avec_date"] / max(1, A["n_formations"]) < 0.9):
        bad.append(("an implausible coverage", A["n_avec_date"], A["n_formations"]))
    return not bad, f"{A['n_avec_date']} of {A['n_formations']} formations dated, {len(A['evenements'])} events, {len(A['concours'])} concours; problems {bad[:3]}"


# ------------------------------------------------------------------ PO3
def client(db: Path):
    os.environ.setdefault("SUPTRACKER_ANALYTICS_DIR", tempfile.mkdtemp())
    os.environ["SUPTRACKER_DB"] = str(db)
    from fastapi.testclient import TestClient
    from suptracker import api as A
    return TestClient(A.app), A


_BASE_AGENDA: dict = {}


def dated_codes(c: Ctx, n: int = 6) -> list[str]:
    """Codes with a coming date, read on the UNMUTATED agenda (a mutant of the list or the .ics never rebuilds it)."""
    if c.db not in _BASE_AGENDA:
        from suptracker import jpo
        _BASE_AGENDA[c.db] = jpo.agenda(c.con, TODAY)
    A = _BASE_AGENDA[c.db]
    out = []
    for e in A["evenements"]:
        if e["date"] >= TODAY.isoformat() and e["formations"][0] not in out:
            out.append(e["formations"][0])
        if len(out) == n:
            break
    if len(out) < n:
        out += [r[0] for r in c.con.execute("""SELECT cod_aff_form FROM core.formation_year
            WHERE session = (SELECT max(session) FROM core.formation_year) ORDER BY cod_aff_form LIMIT ?""", [n]).fetchall()]
    out = list(dict.fromkeys(out))[:n]
    for k, v in sorted(A["concours"].items()):      # one formation recruited through a concours (its block must lose it)
        if v["formations"] and v["formations"][0] not in out:
            out.append(v["formations"][0])
            break
    return out


@check("PO3 the list = for_formation code by code, concours once; 422 on bad codes; no-store, no audience event; agenda shared")
def po3(c: Ctx):
    J = c.jpo()
    bad = []
    codes = dated_codes(c)
    L = J.for_list(c.con, codes, TODAY)
    for f in L["formations"]:
        b = J.for_formation(c.con, f["cod_aff_form"], TODAY)
        if b and b.get("concours"):
            b = {k: v for k, v in b.items() if k != "concours"}
        if f["jpo"] != b:
            bad.append(("the list differs from the formation page", f["cod_aff_form"]))
    keys = [f["concours"] for f in L["formations"] if f["concours"]]
    if sorted(set(keys)) != sorted(L["concours"]) or any(sorted(v["formations"]) != sorted(f["cod_aff_form"] for f in L["formations"] if f["concours"] == k) for k, v in L["concours"].items()):
        bad.append("the concours are not counted once with their formations")
    tc, A = client(c.db)
    with tc:
        for q in ("abc", "1,2,3,4,5,6,7,8,9,10,11", "1;2", HOSTILE):
            r = tc.get("/api/jpo/liste", params={"ids": q})
            if r.status_code != 422:
                bad.append(("a bad list accepted", q, r.status_code))
        r = tc.get("/api/jpo/liste", params={"ids": ",".join(codes)})
        r2 = tc.get("/api/jpo/liste.ics", params={"ids": ",".join(codes)})
        r3 = tc.get("/api/jpo/agenda", params={"lat": "45", "ville": "Lyon"})
        if r.status_code != 200 or "no-store" not in r.headers.get("cache-control", ""):
            bad.append(("the list route's cache", r.status_code, r.headers.get("cache-control")))
        if r2.status_code != 200 or "no-store" not in r2.headers.get("cache-control", "") or not r2.headers.get("content-type", "").startswith("text/calendar"):
            bad.append(("the .ics route", r2.status_code, r2.headers.get("cache-control"), r2.headers.get("content-type")))
        if r3.status_code != 200 or "public" not in r3.headers.get("cache-control", ""):
            bad.append(("the agenda route's cache", r3.status_code, r3.headers.get("cache-control")))
    from suptracker import cache as CH, analytics as AN
    for path in ("/api/jpo/liste", "/api/jpo/liste.ics"):
        if (CH.policy(path) or (None,))[0] != CH.NO_STORE:
            bad.append(("policy", path))
    if (CH.policy("/api/jpo/agenda") or (None,))[0] != CH.PUBLIC:
        bad.append("the agenda's policy")
    api_src = (ROOT / "suptracker" / "api.py").read_text()
    body = api_src[api_src.index('@app.get("/api/jpo/liste")'): api_src.index('@app.get("/api/reorientation/voeux")')]
    if "A.record" in body or "bg.add_task" in body or "def jpo_agenda(" in body and "Query(" in body.split("def jpo_agenda(")[1].split(")")[0]:
        bad.append("a list route records an event, or the agenda takes a parameter")
    if "portesouvertes" not in AN.ROUTES:
        bad.append("the page's audience route")
    return not bad, f"{len(codes)} codes; problems {bad[:4]}"


# ------------------------------------------------------------------ PO4
def ics_events(text: str) -> list[dict]:
    lines = text.split("\r\n")
    un = []
    for ln in lines:
        if ln.startswith(" ") and un:
            un[-1] += ln[1:]
        else:
            un.append(ln)
    evs, cur = [], None
    for ln in un:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            evs.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            k, v = ln.split(":", 1)
            cur[k] = v
    return evs


@check("PO4 the .ics: coming dates, one event per establishment, day and kind, source and « À vérifier », folding, escaping")
def po4(c: Ctx):
    J = c.jpo()
    bad = []
    codes = dated_codes(c)
    L = J.for_list(c.con, codes, TODAY)
    text = J.ics_list(L)
    if not text.endswith("\r\n") or "\n" in text.replace("\r\n", ""):
        bad.append("not CRLF")
    if any(len(ln.encode()) > 75 for ln in text.split("\r\n")):
        bad.append("a line over 75 octets")
    evs = ics_events(text)
    want = set()
    for f in L["formations"]:
        for e in (f["jpo"] or {}).get("dates") or []:
            if (e.get("fin") or e["date"]) >= TODAY.isoformat():
                want.add((e["uai"], e["date"], bool(e["virtuel"])))
    conc = sum(1 for k in L["concours"].values() for e in k.get("dates") or [] if e["date"] >= TODAY.isoformat())
    if len(evs) != len(want) + conc:
        bad.append(("events", len(evs), len(want), conc))
    for e in evs:
        d = e.get("DESCRIPTION", "")
        if "À vérifier" not in d or ("Source :" not in d and "lu sur le site du concours" not in d):
            bad.append(("an event without its source or « À vérifier »", e.get("UID")))
            break
        if re.search(r"(?<!\\),", e.get("SUMMARY", "") + d):
            bad.append(("an unescaped comma", e.get("UID")))
            break
        if e.get("DTSTART;VALUE=DATE", "") < TODAY.strftime("%Y%m%d"):
            bad.append(("a past date in the .ics", e.get("UID")))
            break
    uids = [e.get("UID") for e in evs]
    if len(uids) != len(set(uids)):
        bad.append("two events with one UID")
    # crafted: two formations of one establishment and day = one event naming both; a passed day left out
    crafted = {"aujourdhui": "2026-11-27", "formations": [
        {"cod_aff_form": "1", "formation": "BTS A, option B", "etablissement": "Lycée X", "jpo": {"dates": [
            {"uai": "0000001A", "date": "2027-01-10", "fin": None, "virtuel": False, "source": "onisep", "nom": "Lycée X", "heures": "9h-12h"},
            {"uai": "0000001A", "date": "2026-11-01", "fin": None, "virtuel": False, "source": "onisep", "nom": "Lycée X"}]}, "concours": None},
        {"cod_aff_form": "2", "formation": "BTS C", "etablissement": "Lycée X", "jpo": {"dates": [
            {"uai": "0000001A", "date": "2027-01-10", "fin": None, "virtuel": False, "source": "site", "nom": "Lycée X"}]}, "concours": None}],
        "concours": {}}
    ce = ics_events(J.ics_list(crafted))
    if len(ce) != 1 or "BTS A\\, option B" not in ce[0].get("DESCRIPTION", "") or "BTS C" not in ce[0].get("DESCRIPTION", "") \
            or "Source : Onisep" not in ce[0].get("DESCRIPTION", ""):
        bad.append(("crafted: one event naming both formations, the passed day out", len(ce)))
    return not bad, f"{len(evs)} events for {len(codes)} formations; problems {bad[:4]}"


# ------------------------------------------------------------------ PO5
PAGE_NAMES = ("JPO_KIND_LINE", "JPO_LISTE_FIRST", "jpoListeEvents", "poKeep", "jpoUrl", "jpoWhen", "jpoSrc", "JPO_KIND", "jpoConcours",
              "jpoListeCard")
PAGE_STUB = r"""
const fmt = (x) => String(x); const frDate = (d) => d; const localIso = () => "2026-11-27";
const foldText = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const haversineKm = (a, b, c, d) => Math.hypot(a - c, b - d) * 100;
"""
PAGE_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const evs = jpoListeEvents(D.L, "2026-11-27");
const keep = D.cases.map(([F, home]) => D.A.evenements.filter((x) => poKeep(x, D.A, home, F, "2026-11-27")).map((x) => x.uai + x.date));
process.stdout.write(JSON.stringify({ evs: evs.map((x) => [x.e.uai, x.e.date, x.forms.map((f) => f.cod_aff_form)]), keep, card: jpoListeCard(D.L, ["1", "2", "3"]) }));"""


def own_keep(x, A, home, F, today):
    if F["periode"] == "avenir" and (x.get("fin") or x["date"]) < today:
        return False
    if F["type"] == "place" and x["virtuel"]:
        return False
    if F["type"] == "ligne" and not x["virtuel"]:
        return False
    if F["q"]:
        q = F["q"].lower()
        if not any(q in (A["formations"].get(cod, [""])[0] or "").lower() for cod in x["formations"]) and q not in (x["nom"] or "").lower():
            return False
    if not x["virtuel"] and home and F["km"]:
        if x["lat"] is None or ((home["lat"] - x["lat"]) ** 2 + (home["lon"] - x["lon"]) ** 2) ** 0.5 * 100 > F["km"]:
            return False
    return True


@check("PO5 page twins: coming dates grouped, filters (radius never on an online session), escaped, five first; the town never sent")
def po5(c: Ctx):
    if not all(top(c.js, n) for n in PAGE_NAMES):
        return False, f"missing {[n for n in PAGE_NAMES if not top(c.js, n)]}"
    ev = lambda uai, d, virt, forms, lat=45.0, nom="Etab": {"uai": uai, "date": d, "fin": None, "virtuel": virt, "source": "onisep",  # noqa: E731
                                                        "nom": nom, "lat": lat, "lon": 4.0, "ville": "V", "formations": forms}
    A = {"formations": {"1": ["BTS Commerce", True], "2": ["Licence Droit", True], "3": [HOSTILE, False]},
         "evenements": [ev("A", "2026-11-01", False, ["1"]), ev("B", "2027-01-10", False, ["1", "2"]), ev("C", "2027-01-11", True, ["3"], lat=None),
                        ev("D", "2027-02-01", False, ["2"], lat=48.0), ev("E", "2027-02-02", False, ["3"], lat=None, nom=HOSTILE)]}
    home = {"lat": 45.0, "lon": 4.0}
    cases = [({"periode": "avenir", "type": "tous", "q": "", "km": 50}, home), ({"periode": "saison", "type": "tous", "q": "", "km": 0}, home),
             ({"periode": "avenir", "type": "place", "q": "", "km": 50}, home), ({"periode": "avenir", "type": "ligne", "q": "", "km": 50}, home),
             ({"periode": "avenir", "type": "tous", "q": "droit", "km": 0}, None), ({"periode": "avenir", "type": "tous", "q": "", "km": 50}, None)]
    lst = {"saison": {"annees": "2026-2027"}, "concours": {}, "formations": [
        {"cod_aff_form": "1", "formation": "BTS Commerce", "etablissement": HOSTILE, "jpo": {"dates": [
            {"uai": "A", "date": "2026-11-01", "virtuel": False, "source": "onisep", "nom": "A"},
            {"uai": "B", "date": "2027-01-10", "virtuel": False, "source": "onisep", "nom": HOSTILE}]}},
        {"cod_aff_form": "2", "formation": "Licence", "etablissement": "Fac", "jpo": {"dates": [
            {"uai": "B", "date": "2027-01-10", "virtuel": False, "source": "site", "nom": "B", "site": "javascript:alert(1)"}] + [
            {"uai": f"Z{i}", "date": f"2027-03-{10 + i}", "virtuel": True, "source": "onisep", "nom": "Z"} for i in range(6)]}},
        {"cod_aff_form": "3", "formation": "Sans", "etablissement": "X", "jpo": None}]}
    o = RB.node(RB.STUB + PAGE_STUB + "\n".join(top(c.js, n) for n in PAGE_NAMES) + PAGE_PROG, {"A": A, "cases": cases, "L": lst})
    if o is None:
        return True, "node absent: not run"
    bad = []
    if o["evs"][0] != ["B", "2027-01-10", ["1", "2"]] or any(e[1] < "2026-11-27" for e in o["evs"]) or len(o["evs"]) != 7:
        bad.append(("jpoListeEvents", o["evs"][:2], len(o["evs"])))
    for (F, h), got in zip(cases, o["keep"]):
        want = [x["uai"] + x["date"] for x in A["evenements"] if own_keep(x, A, h, F, "2026-11-27")]
        if got != want:
            bad.append(("poKeep", F, h, got, want))
    card = o["card"]
    if "<img" in card or "javascript:" in card or "&lt;img" not in card:
        bad.append("the list card is not escaped")
    first = card.split("<details>")[0]
    if first.count("<li>") != 5 or card.count("<li>") < 7 or "Voir les 2 autres dates" not in card or "Sans date à venir (1)" not in card:
        bad.append("five dates first, the others folded; the formations without a coming date listed")
    if "/api/jpo/liste.ics?ids=1%2C2%2C3" not in card or "rien n'en est enregistré" not in card:
        bad.append("the .ics link or the privacy sentence")
    view = top(c.js, "viewPortesOuvertes")
    calls = re.findall(r"api\(([^)]*)\)", view)
    if calls != ['"/api/jpo/agenda"'] or "villeDepart()" not in view:
        bad.append(("the page sends something besides the plain agenda request", calls))
    sort = view[view.index(".sort((a, b) =>"): view.index("const list = document.getElementById")]
    if re.search(r"n_avec|taux|acces|jury|zone", sort) or "a.x.date < b.x.date" not in sort or "(a.km ?? 1e9) - (b.km ?? 1e9)" not in sort:
        bad.append("the order is not date then distance")
    return not bad, f"{len(cases)} filter cases; problems {bad[:4]}"


# ------------------------------------------------------------------ PO6
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[process.argv.length - 2], codes = JSON.parse(process.argv[process.argv.length - 1]);
  const b = await chromium.launch(); const errs = []; const out = {};
  for (const [n, vp] of [['wide', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    const ctx = await b.newContext({ viewport: vp }); const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(n + ': ' + e.message));
    const reqs = []; p.on('request', (r) => reqs.push(r.url()));
    await p.goto(base + '/');
    await p.evaluate((c) => { localStorage.setItem('voeux', JSON.stringify(c)); localStorage.setItem('profile', JSON.stringify({ statut: 'reorientation' }));
      localStorage.setItem('villeDepart', JSON.stringify({ nom: 'Lyon', dep: '69', lat: 45.764, lon: 4.8357 })); }, codes);
    await p.goto(base + '/#/voeux'); await p.waitForSelector('#vx-jpo h2', { timeout: 90000 }).catch(() => {});
    const liste = await p.evaluate(() => { const s = document.getElementById('vx-jpo'); return s ? { h: (s.querySelector('h2') || {}).textContent || '',
      ics: !!s.querySelector('a[href^="/api/jpo/liste.ics?ids="]') } : null; });
    await p.goto(base + '/#/portes-ouvertes'); await p.waitForSelector('#po-list p', { timeout: 90000 }).catch(() => {});
    const before = await p.evaluate(() => (document.querySelector('#po-list [role=status]') || {}).textContent || '');
    await p.selectOption('#po-type', 'ligne').catch(() => {});
    await p.waitForTimeout(500);
    const after = await p.evaluate(() => (document.querySelector('#po-list [role=status]') || {}).textContent || '');
    const scroll = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    out[n] = { liste, before, after, scroll, h1: await p.evaluate(() => (document.querySelector('h1') || {}).textContent || ''),
      leak: reqs.filter((u) => /Lyon|45\.76|4\.83/.test(u)) };
    await ctx.close();
  }
  process.stdout.write(JSON.stringify({ ...out, errs })); await b.close();
})();
"""


@check("PO6 browser: Mes vœux block and the near-me page, a filter changes the list, the town never sent, wide + phone, 0 JS error")
def po6(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, cwd=str(ROOT)).returncode:
        return True, "skipped (node or playwright not installed)"
    if c.jpo().agenda_payload(c.con) is None:
        return False, "the committed warehouse carries no agenda (run the data workflow)"
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tempfile.mkdtemp(), "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        r = nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}", json.dumps(dated_codes(c))], capture_output=True, text=True,
                         timeout=600, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    for n in ("wide", "phone"):
        x = o[n]
        if not x["liste"] or "Portes ouvertes et webinaires de ma liste" not in x["liste"]["h"] or not x["liste"]["ics"]:
            bad.append((n, "the Mes vœux block", x["liste"]))
        if "journée" not in x["before"] or x["before"] == x["after"]:
            bad.append((n, "the type filter did not change the list", x["before"], x["after"]))
        if x["scroll"] or x["leak"] or "Portes ouvertes" not in x["h1"]:
            bad.append((n, "scroll, a request carrying the town, or the h1", x["scroll"], x["leak"][:1]))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad, f"wide {o['wide']['before']!r} -> {o['wide']['after']!r}; problems {bad}"


# ------------------------------------------------------------------ PO7
MUTANTS = [
    ("py", "PO1", "the university's open days forgotten", "        keys = set(uais) | {fiche_key(cod)} | {univ[u] for u in uais if u in univ}",
     "        keys = set(uais) | {fiche_key(cod)}"),
    ("py", "PO1", "the formation's own fiche forgotten", "        keys = set(uais) | {fiche_key(cod)} | {univ[u] for u in uais if u in univ}",
     "        keys = set(uais) | {univ[u] for u in uais if u in univ}"),
    ("py", "PO1", "online and on-site merged", "            key = (e[\"uai\"], e[\"date\"], bool(e[\"virtuel\"]))", "            key = (e[\"uai\"], e[\"date\"], False)"),
    ("py", "PO2", "coverage over the dated formations only", '"n_formations": len(rows), "n_avec_date": n_date,', '"n_formations": n_date, "n_avec_date": n_date,'),
    ("py", "PO4", "past dates in the .ics", "            if (e.get(\"fin\") or e[\"date\"]) < today:\n                continue\n            k = (e[\"uai\"]",
     "            k = (e[\"uai\"]"),
    ("py", "PO4", "the source dropped from the .ics", 'f"Source : {SRC_WORDS.get(e.get(\'source\'), \'Onisep\')}. ', 'f"'),
    ("py", "PO3", "the concours left in each block", "        conc = b.pop(\"concours\", None) if b else None", "        conc = b.get(\"concours\") if b else None"),
    ("js", "PO5", "the radius applied to online sessions", "  if (!x.virtuel && home && F.km &&", "  if (home && F.km &&"),
    ("js", "PO5", "passed dates in the list", "      if ((e.fin || e.date) < today) continue;\n      const k = `${e.uai}", "      const k = `${e.uai}"),
    ("js", "PO5", "an establishment unescaped", '· ${esc(x.nom)}${x.universite ?', '· ${x.nom}${x.universite ?'),
    ("js", "PO5", "every date shown", "evs.slice(0, JPO_LISTE_FIRST).map(line)", "evs.map(line)"),
    ("js", "PO5", "the town sent with the request", 'const A = await api("/api/jpo/agenda");', 'const A = await api(`/api/jpo/agenda?ville=${encodeURIComponent((villeDepart() || {}).nom || "")}`);'),
]


@check("PO7 mutation test: every seeded bug is caught by PO1-PO5")
def po7(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("PO1", "PO2", "PO3", "PO4", "PO5") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    import importlib.util
    missed, skipped = [], []
    dated = bool(c.agenda()["evenements"])
    for kind, target, name, old, new in MUTANTS:
        if kind == "py" and target in ("PO2", "PO3") and not dated:
            skipped.append(name)                  # a warehouse with no open day (the synthetic fixture): these need real dates
            continue
        m = copy.copy(c)
        if kind == "js":
            if c.js.count(old) != 1:
                missed.append(f"{name} (anchor {c.js.count(old)})")
                continue
            m.js = c.js.replace(old, new, 1)
        else:
            if c.src.count(old) != 1:
                missed.append(f"{name} (anchor {c.src.count(old)})")
                continue
            spec = importlib.util.spec_from_loader("suptracker.jpo_mutant", loader=None)
            mod = importlib.util.module_from_spec(spec)
            mod.__package__ = "suptracker"
            mod.__file__ = str(ROOT / "suptracker" / "jpo.py")
            exec(compile(c.src.replace(old, new, 1), "jpo_mutant", "exec"), mod.__dict__)
            m.J = mod
            m._agenda = None
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    if c.real and skipped:
        missed += skipped                        # on the real warehouse every mutant must run
    return not missed, f"{len(MUTANTS) - len(missed) - len(skipped)}/{len(MUTANTS) - len(skipped)} caught; skipped (no open day here) {len(skipped)}; missed {missed}"


# ------------------------------------------------------------------ PO8
@check("PO8 wiring and docs: route, tab, audience name, way in, nightly suite, test file and CI duration, README, CLAUDE.md")
def po8(c: Ctx):
    bad = []
    js = c.js
    if 'if (a === "portes-ouvertes") return await viewPortesOuvertes();' not in js or '"portes-ouvertes": "calendrier"' not in js \
            or '"portes-ouvertes": "portesouvertes"' not in js:
        bad.append("route, tab or audience name")
    if '<a href="#/portes-ouvertes">Portes ouvertes et webinaires près de chez moi</a>' not in top(js, "viewCalendrier"):
        bad.append("the way in from the calendar")
    if js.count("loadJpoListe(ids, marker);") != 2 or js.count('<section class="card" id="vx-jpo"><p class="muted small">Portes ouvertes de votre liste…</p></section>') != 2:
        bad.append("the Mes vœux block in both situations")
    if "jpo.build_agenda(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("the build")
    if '"portes": ("PO6",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
    if not (ROOT / "tests" / "test_portes.py").exists() or '"tests/test_portes.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("test file / CI duration")
    if "## Portes ouvertes et webinaires de ma liste (owner, 2026-11-27, PR 16)" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**Portes ouvertes de ma liste et près de chez moi (owner, 2026-11-27, PR 16).**" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    return not bad, f"problems {bad}"


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
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
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
