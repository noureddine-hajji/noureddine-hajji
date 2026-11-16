"""Red team, journées portes ouvertes (owner, 2026-11-16): the establishment's open days on each formation page.

  J1 Onisep field: an INDEPENDENT reading written here (own pattern per part) equals parse_onisep on every part of the fixture and
     of the committed versions; a part no rule reads (no « le/du », an impossible day, a range that ends before it starts, a weekday
     without a date) is left out and counted, never guessed.
  J2 seasons: for every day of 2019-2031 the season equals the owner's rule written here ([1 September Y-1, 1 May Y], both
     included; 2 May - 31 August in none); the season shown contains today, else is the next one; 16 November 2026 = 1 September
     2026 - 1 May 2027.
  J3 period from past seasons: every day 1-31 of every month maps to its third (1-9 « début », 10-20 « mi- », 21-31 « fin »); dates
     between the 10th and the 20th of January = « aux alentours de mi-janvier » (owner's example); never a day number; more than
     three periods = the span; the years read are listed.
  J4 site text: a date counts only on a keyword line or the two after it, with its year printed or a weekday TRUE for the season;
     a false weekday, a date far from the keyword, a date of the summer are refused; e-mails and phone numbers are masked.
  J5 serving (fixture warehouse, today = 2026-11-16): only the season's dates; a future date only an older Onisep version lists is
     never announced, a passed one is; Onisep + site = confirmed, site only = where and when it was read; no date = the period of
     at most 3 past seasons; exact UAI only (SIES, then cartographie); non-https links dropped; a formation whose establishments
     are unknown gets nothing.
  J6 page (node): jpoCard / jpoLine escape every stored string, mark passed dates, say a period is not a date and must be confirmed,
     credit Onisep (ODbL), keep links https + noopener, use vouvoiement, never speak of chances, call no API.
  J7 fetcher (no network): Onisep files read by their column names (csv, json), rows without open days dropped, an unchanged content
     is not stored twice; the site lines keep the keyword lines only, masked; only same-site links are followed; robots.txt is
     honoured; an archived capture already read is never downloaded again.
  J8 plumbing: workflow (daily schedule, request push on a claude/ branch, data/jpo committed), build, API, fingerprint (Onisep
     versions, site extracts, each site's status, never a check date), vercelignore, source register, README, CLAUDE.md, tests.
  J9 real data (--real, when data/jpo holds versions): the warehouse equals a reading of data/jpo (no stale build), every served
     date is in the season, and the coverage of the latest campaign's formations is printed (measured, never typed).
  J10 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import io
import json
import re
import shutil
import sys
import tempfile
import time
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"
TODAY = date(2026, 11, 16)


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
        self.src = {"jpo": (ROOT / "suptracker" / "jpo.py").read_text(), "fetch": (ROOT / "scripts" / "jpo_fetch.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def J(self):
        import suptracker  # noqa: F401
        return load(ROOT / "suptracker" / "jpo.py", "suptracker.jpo_rt", self.src["jpo"])

    def F(self):
        return load(ROOT / "scripts" / "jpo_fetch.py", "jpo_fetch_rt", self.src["fetch"])


# ------------------------------------------------------------------------------------------------------------------ fixture
def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def csvtext(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


A, B, C, D, E = "0590001A", "0590002B", "0590003C", "0590004D", "0590005E"
F, G, H, K, L = "0590006F", "0590007G", "0590008H", "0590010K", "0590011L"
VERSIONS = [
    # the latest version: A's season (one date in May, outside), C only outside the season
    ("sup_20261110_onisep.csv.gz", "sup", "2026-11-10", "onisep", [
        (A, "Université A " + HOSTILE, "https://www.onisep.fr/ENS.1",
         "le 28/11/2026 de 09h00 à 17h00 (sur inscription " + HOSTILE + ") voir https://a.fr/jpo | le 22/05/2027 | "
         "le 06/02/2027 voir http://a.fr/x | samedi 3 mars"),
        (C, "Lycée C", "javascript:alert(1)", "le 22/05/2027 | le 31/02/2027"),
        # owner, 2026-11-16: a component without a date takes its UNIVERSITY's (named); one with its own keeps its own; an
        # attachment that is not a university lends nothing
        (F, "UFR F", "", "", "Université G " + HOSTILE + " (0590007G)"),
        (G, "Université G", "https://www.onisep.fr/ENS.7", "le 30/01/2027", ""),
        (K, "IUT K", "", "le 03/02/2027", "Université G (0590007G)"),
        (L, "École L", "", "", "Institut catholique M (0590009M)"),
        ("0590009M", "Institut catholique M", "", "le 13/02/2027", ""),
    ]),
    # an older version: a passed date of the season (shown) and a future one the latest no longer lists (never announced)
    ("sup_20261001_onisep.csv.gz", "sup", "2026-10-01", "onisep", [
        (A, "Université A", "https://www.onisep.fr/ENS.1", "le 10/10/2026 | le 20/03/2027"),
    ]),
    # archived versions: B's open days of past seasons, all mid-January; one too old (season 2021) is not used
    ("sup_20250105_archive.csv.gz", "sup", "2025-01-05", "archive", [(B, "École B", "", "le 18/01/2025 | le 20/01/2021")]),
    ("sup_20240102_archive.csv.gz", "sup", "2024-01-02", "archive", [(B, "École B", "", "le 13/01/2024")]),
    ("sup_20251220_archive.csv.gz", "sup", "2025-12-20", "archive", [(B, "École B", "", "du 15/01/2026 au 16/01/2026"),
                                                                       (A, "Université A", "", "le 20/01/2026")]),
]
SITE_TEXT = {
    (A, "https://a.fr/jpo"): ("2026-11-12", "Portes ouvertes\nSamedi 28 novembre 2026 de 9h à 17h\nJPO aussi le samedi 13 mars\n"
                                            "contact jpo@a.fr 03 20 00 00 00"),
    # A has Onisep dates: a date only its site shows (often another campus) is not added
    (A, "https://a.fr/autre"): ("2026-11-12", "Journée portes ouvertes le samedi 6 mars 2027"),
    # E has no Onisep date: its site's dates are added, « à vérifier »; an http page gives no link; a collège's line is refused
    (E, "http://e.fr/jpo"): ("2026-11-12", "Journée portes ouvertes le samedi 6 mars 2027"),
    (E, "https://e.fr/jpo2"): ("2026-11-12", "JPO le samedi 13 mars 2027"),
    (E, "https://e.fr/agenda"): ("2026-11-12", "JPO Lyon samedi 5 décembre 2026 · JPO Annecy samedi 12 décembre 2026 · JPO Genève "
                                               "samedi 9 janvier 2027 · JPO Paris samedi 16 janvier 2027 · JPO Aix samedi 23 janvier 2027"),
    (E, "https://e.fr/college"): ("2026-11-12", "Portes ouvertes du collège : samedi 9 janvier 2027"),
    # an agenda of several campuses: it confirms Onisep's 28 November, adds none of its other dates
    (A, "https://a.fr/agenda"): ("2026-11-12", "JPO Lyon samedi 5 décembre 2026 · JPO Annecy samedi 12 décembre 2026 · JPO Genève "
                                               "samedi 9 janvier 2027 · JPO Paris samedi 16 janvier 2027 · JPO Aix samedi 28 novembre 2026"),
    # an agenda of past campaigns: never the past-season period
    (B, "https://b.fr/agenda"): ("2026-11-12", "Portes ouvertes 2025 : 1er mars 2025, 8 mars 2025, 15 mars 2025, 22 mars 2025, 29 mars 2025"),
}


def make_dir(base: Path) -> Path:
    d = base / "jpo"
    (d / "onisep").mkdir(parents=True)
    (d / "sites").mkdir(parents=True)
    vrows = []
    for name, kind, as_of, source, rows in VERSIONS:
        text = csvtext([{"uai": r[0], "nom": r[1], "onisep_url": r[2], "jpo": r[3], "modif": "2026-10-15",
                         "univ": r[4] if len(r) > 4 else ""} for r in rows],
                       ["uai", "nom", "onisep_url", "jpo", "modif", "univ"])
        (d / "onisep" / name).write_bytes(gz(text))
        vrows.append({"file": name, "kind": kind, "as_of": as_of, "source": source, "url": "x", "sha256": name, "rows": len(rows)})
    (d / "onisep" / "versions.csv").write_text(csvtext(vrows, ["file", "kind", "as_of", "source", "url", "sha256", "rows"]))
    ext = [{"uai": u, "url": url, "fetched": f, "text": t} for (u, url), (f, t) in SITE_TEXT.items()]
    (d / "sites" / "extraits.csv.gz").write_bytes(gz(csvtext(ext, ["uai", "url", "fetched", "text"])))
    (d / "sites" / "etat.csv").write_text(csvtext([{"uai": A, "url": "https://a.fr/jpo", "status": "ok", "checked": "2026-11-12"}],
                                                  ["uai", "url", "status", "checked"]))
    # the formations' own Parcoursup fiches: a past open day (history), Onisep's date again (one day), an agenda (never)
    fd = base / "fiches"
    fd.mkdir()
    texts = {"t8": "Nous recommandons nos journées portes ouvertes le samedi 24 janvier 2026. Date limite le 12 mars 2026.",
             "t1": "Journées portes ouvertes le samedi 6 février 2027.",
             "t10": "Salons et JPO : samedi 9 janvier 2027, samedi 16 janvier 2027, samedi 23 janvier 2027, samedi 30 janvier 2027, "
                    "samedi 6 février 2027."}
    (fd / "textes.csv.gz").write_bytes(gz(csvtext([{"id": k, "texte": v} for k, v in texts.items()], ["id", "texte"])))
    cols = ["cod_aff_form", "session", "nationaux_id", "complementaires_id", "conseils_id", "info_id"]
    (fd / "attendus.csv").write_text(csvtext([
        {"cod_aff_form": "8", "session": "2026", "conseils_id": "t8"},
        {"cod_aff_form": "1", "session": "2027", "info_id": "t1"},
        {"cod_aff_form": "10", "session": "2027", "complementaires_id": "t10"}], cols))
    (fd / "etat.csv").write_text(csvtext([{"cod_aff_form": "8", "status": "ok", "lu_le": "20260110120000", "session": "2026"}],
                                         ["cod_aff_form", "status", "lu_le", "session", "raison", "url", "version"]))
    return d


def fixture(J, base: Path):
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE SCHEMA core")
    con.execute("CREATE TABLE core.formation_year (cod_aff_form VARCHAR, session BIGINT, cod_uai VARCHAR)")
    con.execute(f"""INSERT INTO core.formation_year VALUES ('1', 2025, '{A}'), ('2', 2025, '9999999Z'), ('3', 2025, '{D}'),
                    ('4', 2025, '{C}'), ('5', 2024, '{D}'), ('5', 2025, '{B}'),
                    ('6', 2025, '{E}'), ('7', 2025, '{F}'), ('8', 2025, '{H}'), ('9', 2025, '{K}'), ('10', 2025, '{L}')""")
    con.execute("CREATE TABLE core.cartographie (cod_aff_form VARCHAR, etab_uai VARCHAR)")
    con.execute(f"INSERT INTO core.cartographie VALUES ('2', '{B}'), ('3', '{D}')")
    J.build(con, make_dir(base))
    return con


# ----------------------------------------------------------------------------------------------------------------------- J1
ORACLE_PART = re.compile(r"(le|du) (\d\d)/(\d\d)/(\d{4})( au (\d\d)/(\d\d)/(\d{4}))?( de (\d+)h(\d\d) à (\d+)h(\d\d))?(, en virtuel)?"
                         r"( \((.*?)\))?( voir (\S+))?")


def oracle_parts(field: str):
    good, bad = [], 0
    for p in field.split("|"):
        p = " ".join(p.split())
        if not p:
            continue
        m = ORACLE_PART.fullmatch(p)
        try:
            d1 = date(int(m[4]), int(m[3]), int(m[2])) if m else None
            d2 = date(int(m[8]), int(m[7]), int(m[6])) if m and m[5] else None
        except ValueError:
            d1 = None
        if d1 is None or (d2 is not None and d2 < d1):
            bad += 1
            continue
        good.append((d1, d2, f"{int(m[10])}h{m[11]} à {int(m[12])}h{m[13]}" if m[9] else None, m[16] or None, bool(m[14]),
                     m[18] if m[18] and m[18].startswith(("http://", "https://")) else None))
    return good, bad


def committed_fields():
    d = ROOT / "data" / "jpo" / "onisep"
    out = []
    for f in sorted(d.glob("*.csv.gz")) if d.exists() else []:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            out += [r["jpo"] for r in csv.DictReader(fh)]
    return out


@check("J1 Onisep field: an independent reading equals parse_onisep; unreadable parts are counted, never guessed")
def j1(c: Ctx):
    J = c.J()
    fields = [j for *_, rows in VERSIONS for *_, j in rows] + [
        "le 31/02/2027", "du 14/01/2027 au 12/01/2027", "samedi 3 mars", "le 05/12/2026 voir https://x.fr/a | le 09/01/2027 voir https://…",
        "le 07/11/2026 de 9h00 à 13h00 (sur inscription) voir https://www.croix-rouge.fr/a", "  |  ",
        "le 19/12/2026 de 10h00 à 17h00, en virtuel (session présentation live) voir https://x.fr/a | le 12/12/2026, en virtuel"] + committed_fields()
    bad = []
    for f in fields:
        got, gbad = J.parse_onisep(f)
        got = [(p["debut"], p["fin"], p["heures"], p["remarque"], p["virtuel"], p["voir"]) for p in got]
        exp, ebad = oracle_parts(f)
        if got != exp or len(gbad) != ebad:
            bad.append(f"{f[:60]!r}: {got} / {len(gbad)} != {exp} / {ebad}")
    return not bad, f"{len(fields)} fields ({len(committed_fields())} committed); differences {bad[:3]}"


# ----------------------------------------------------------------------------------------------------------------------- J2
@check("J2 seasons: 1 September Y-1 to 1 May Y included, none in summer; the shown season contains today or is the next")
def j2(c: Ctx):
    J = c.J()
    bad = []
    d = date(2019, 1, 1)
    while d <= date(2031, 12, 31):
        exp = d.year + 1 if d.month >= 9 else d.year if (d.month, d.day) <= (5, 1) else None
        if J.season_of(d) != exp:
            bad.append(f"season_of({d}) = {J.season_of(d)} != {exp}")
        cur = exp if exp is not None else d.year + 1
        if J.current_season(d) != cur:
            bad.append(f"current_season({d})")
        if exp is not None:
            w0, w1 = J.window(exp)
            if not (w0 <= d <= w1) or w0 != date(exp - 1, 9, 1) or w1 != date(exp, 5, 1):
                bad.append(f"window({exp})")
        d += timedelta(days=1)
    if J.window(J.current_season(TODAY)) != (date(2026, 9, 1), date(2027, 5, 1)):
        bad.append("16 November 2026 is not the owner's window")
    return not bad, f"{len(bad)} differences {bad[:4]}"


# ----------------------------------------------------------------------------------------------------------------------- J3
@check("J3 period: thirds of the month, « aux alentours de mi-janvier » for 10-20 January, never a day, years listed")
def j3(c: Ctx):
    J = c.J()
    bad = []
    for day in range(1, 32):
        exp = "début" if day < 10 else "mi" if day <= 20 else "fin"
        if J.third(day) != exp:
            bad.append(f"third({day})")
    for y in (2024, 2025, 2026):
        for day in range(10, 21):
            a = J.approx([date(y, 1, day), date(y - 1, 1, 30 - day)] if day <= 20 and 30 - day >= 10 else [date(y, 1, day)])
            if a["texte"] != "aux alentours de mi-janvier":
                bad.append(f"{day}/01/{y}: {a['texte']}")
    a = J.approx([date(2025, 11, 3), date(2026, 1, 15), date(2025, 2, 25)])
    if a["texte"] != "aux alentours de début novembre, mi-janvier et fin février" or a["annees"] != ["2024-2025", "2025-2026"]:
        bad.append(f"three periods: {a}")
    a = J.approx([date(2025, 11, 3), date(2026, 1, 15), date(2025, 2, 25), date(2026, 3, 12)])
    if a["texte"] != "aux alentours de entre début novembre et mi-mars" and a["texte"] != "aux alentours de entre début novembre et mi-mars":
        bad.append(f"span: {a['texte']}")
    if J.approx([]) is not None:
        bad.append("a period without dates")
    for d in (date(2025, 1, 15), date(2024, 12, 2), date(2025, 4, 30)):
        if re.search(r"\d", J.approx([d])["texte"]):
            bad.append(f"a day number in {J.approx([d])['texte']}")
    return not bad, f"differences {bad[:4]}"


# ----------------------------------------------------------------------------------------------------------------------- J4
@check("J4 site text: keyword lines only, year printed or weekday true, summer refused, e-mails and phones masked")
def j4(c: Ctx):
    J = c.J()
    f = date(2026, 11, 20)
    cases = [
        ("Portes ouvertes\nSamedi 30 janvier 2027", [date(2027, 1, 30)]),
        ("Journée portes ouvertes : samedi 30 janvier", [date(2027, 1, 30)]),        # Saturday in 2027: true
        ("Journée portes ouvertes : samedi 31 janvier", []),                         # a Sunday in 2027: another year's page
        ("JPO le 12/03/2027", [date(2027, 3, 12)]),
        ("JPO le 12/06/2027", []),                                                   # summer: no season
        ("Portes ouvertes le 1er février 2027", [date(2027, 2, 1)]),
        ("Portes ouvertes\nligne 2\nligne 3\nsamedi 6 février 2027", []),            # three lines below: too far
        ("Rentrée le 2 septembre 2026\nInscriptions le 15 mars 2027", []),           # no keyword
        ("nos portes-ouvertes : dimanche 15 novembre 2026", [date(2026, 11, 15)]),
        ("JPO : 7 février", []),                                                     # neither a year nor a weekday
        ("Nous vous attendons à nos journées portes ouvertes pour découvrir toutes nos formations et nos campus\n"
         "Mardi 17 novembre 2026", []),                                              # a long sentence is not a heading
        ("Portes ouvertes - Campus\nPublié le 8 octobre 2025", []),                  # the page's own date
        ("JPO 2027 (mis à jour le 03/11/2026) : samedi 6 février 2027", [date(2027, 2, 6)]),
    ]
    bad = [f"{t!r}: {J.site_dates(t, f)} != {e}" for t, e in cases if J.site_dates(t, f) != e]
    m = J.mask("écrire à jpo@ecole-a.fr ou appeler le 03 20 54 32 32 ou +33 6 12 34 56 78 ; le 06/02/2027")
    if "@" in m or re.search(r"\d\d \d\d \d\d", m) or "06/02/2027" not in m:
        bad.append(f"mask: {m}")
    return not bad, f"{len(cases)} cases; differences {bad[:3]}"


# ----------------------------------------------------------------------------------------------------------------------- J5
@check("J5 serving: season only, removed future dates never announced, confirmed / site-only said, past-season period, exact UAI")
def j5(c: Ctx):
    J = c.J()
    tmp = Path(tempfile.mkdtemp())
    try:
        con = fixture(J, tmp)
        f1 = J.for_formation(con, "1", TODAY)
        f2 = J.for_formation(con, "2", TODAY)
        f3 = J.for_formation(con, "3", TODAY)
        f4 = J.for_formation(con, "4", TODAY)
        f5 = J.for_formation(con, "5", TODAY)
        f6 = J.for_formation(con, "6", TODAY)
        f7, f8, f9, f10 = (J.for_formation(con, k, TODAY) for k in ("7", "8", "9", "10"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = []
    if not f7 or f7.get("universite") != {"uai": G, "nom": "Université G " + HOSTILE} or [e["date"] for e in f7["dates"]] != ["2027-01-30"]:
        bad.append(f"a component without a date does not get its university's, named: {f7 and (f7.get('universite'), f7['dates'])}")
    if not f9 or f9.get("universite") or [e["date"] for e in f9["dates"]] != ["2027-02-03"]:
        bad.append("a component with its own date takes its university's")
    if not f10 or f10.get("universite") or f10["dates"]:
        bad.append("an attachment that is not a university (or an agenda fiche) lends dates")
    if not f8 or f8["dates"] or not f8["environ"] or f8["environ"]["texte"] != "aux alentours de fin janvier" \
            or f8["environ"]["annees"] != ["2025-2026"]:
        bad.append(f"the fiche's past open day does not give the period: {f8}")
    if f1 and len(f1["dates"]) != 3:
        bad.append(f"the fiche's date and Onisep's same date are not one open day: {[e['date'] for e in f1['dates']]}")
    elif f1 and not next((e for e in f1["dates"] if e["date"] == "2027-02-06"), {}).get("fiche"):
        bad.append("the fiche's confirmation of an Onisep date is lost")
    g6 = {e["date"]: e for e in (f6 or {}).get("dates", [])}
    if {k: v["source"] for k, v in g6.items()} != {"2027-03-06": "site", "2027-03-13": "site"}:
        bad.append(f"formation 6 (site only): {list(g6)}")
    elif g6["2027-03-06"]["site"] is not None or g6["2027-03-13"]["site"] != "https://e.fr/jpo2" or g6["2027-03-13"]["lu_le"] != "2026-11-12":
        bad.append("a site-only date without a safe link, or without when it was read")
    got = {e["date"]: e for e in (f1 or {}).get("dates", [])}
    exp = {"2026-10-10": "onisep", "2026-11-28": "onisep_site", "2027-02-06": "onisep"}
    if {k: v["source"] for k, v in got.items()} != exp:
        bad.append(f"formation 1 dates {[(k, v['source']) for k, v in got.items()]} != {exp}")
    else:
        if got["2026-11-28"]["heures"] != "9h00 à 17h00" or got["2026-11-28"].get("voir") != "https://a.fr/jpo":
            bad.append("Onisep hours or link lost")
        if got["2027-02-06"].get("voir") is not None:
            bad.append("a non-https link kept")
        if f1["environ"] is not None:
            bad.append("a period beside this season's dates")
    if f1 and f1["saison"] != {"debut": "2026-09-01", "fin": "2027-05-01", "annees": "2026-2027"}:
        bad.append(f"season {f1['saison']}")
    if f1 and [e["onisep_url"] for e in f1["etablissements"]] != ["https://www.onisep.fr/ENS.1"]:
        bad.append("Onisep page link")
    if not f2 or f2["dates"] or not f2["environ"] or f2["environ"]["texte"] != "aux alentours de mi-janvier" \
            or f2["environ"]["annees"] != ["2023-2024", "2024-2025", "2025-2026"]:
        bad.append(f"formation 2 (cartographie UAI, past seasons only): {f2 and f2['environ']}")
    if f3 is not None:
        bad.append("a formation whose establishment is unknown gets a block")
    if not f4 or f4["dates"] or f4["environ"] or [e["onisep_url"] for e in f4["etablissements"]] != [None]:
        bad.append(f"formation 4 (only a date out of the season, a javascript link): {f4}")
    if not f5 or not f5["environ"]:
        bad.append("the latest campaign's UAI is not the one used")
    return not bad, f"differences {bad[:4]}"


# ----------------------------------------------------------------------------------------------------------------------- J6
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
let CALLS = 0; const api = () => { CALLS++; return Promise.resolve({}); };
const localIso = () => "2026-11-16";
const frDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
"""


@check("J6 page: escaped, passed dates marked, a period is not a date, ODbL credit, safe links, vouvoiement, no chance, no call")
def j6(c: Ctx):
    names = ("jpoUrl", "jpoNext", "jpoWhen", "jpoLine", "jpoCard")
    if not all(top(c.js, n) for n in names):
        return False, "a renderer is missing from app.js"
    J = c.J()
    tmp = Path(tempfile.mkdtemp())
    try:
        con = fixture(J, tmp)
        f1, f2, f4, f6, f7 = (J.for_formation(con, k, TODAY) for k in ("1", "2", "4", "6", "7"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    f1 = json.loads(json.dumps(f1))
    f6 = json.loads(json.dumps(f6))
    f6["dates"][0]["site"] = "javascript:alert(1)"
    prog = STUB + "\n".join(top(c.js, n) for n in names) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const out = [jpoCard(D.f1), jpoLine(D.f1), jpoCard(D.f2), jpoLine(D.f2), jpoCard(D.f4), jpoLine(D.f4), jpoCard(D.f6), jpoLine(D.f6), jpoCard(D.f7), jpoLine(D.f7), jpoCard(null), jpoLine(null), String(CALLS)];
      process.stdout.write(JSON.stringify(out));"""
    out = node(prog, {"f1": f1, "f2": f2, "f4": f4, "f6": f6, "f7": f7})
    if out is None:
        return True, "node absent: not run"
    c1, l1, c2, l2, c4, l4, c6, l6, c7, l7, cn, ln, calls = out
    bad = []
    for i, h in enumerate((c1, l1, c2, l2, c4, l4, c6, l6, c7, l7)):
        if "<img" in h:
            bad.append(f"output {i}: unescaped")
        txt = re.sub(r"<[^>]+>", " ", h)
        if re.search(r"\b(?:tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"(?i)chance|garanti|probabilit", txt):
            bad.append(f"output {i}: tutoiement or a chance")
        for tag in re.findall(r"<a [^>]*>", h):
            href = re.search(r'href="([^"]*)"', tag).group(1)
            if not href.startswith("https://") or "noopener" not in tag:
                bad.append(f"output {i}: link {href[:30]}")
    if c1.count("passée") != 1 or "samedi 10 octobre 2026" not in c1:
        bad.append("the passed date of the season is not marked once")
    if "samedi 28 novembre 2026" not in l1:
        bad.append("the summary line is not the next date")
    if "retrouvée sur le site" not in c1 or "lue sur le site de l'établissement le jeudi 12 novembre 2026, à vérifier" not in c6 \
            or "site de l'établissement, à vérifier" not in l6:
        bad.append("the source of a date is not said")
    if "Onisep, Idéo-Structures (licence ODbL)" not in c1 or "avant de vous déplacer" not in c1:
        bad.append("no ODbL credit or no advice to check")
    if "aux alentours de mi-janvier" not in c2 or "pas une date" not in c2 or "à confirmer" not in c2 or "années passées" not in l2:
        bad.append("the period is not said to be a period to confirm")
    if re.search(r"\b\d{1,2} janvier\b", re.sub(r"<[^>]+>", " ", c2 + l2)):
        bad.append("a day number in a period")
    if "Aucune date" not in c4 or l4:
        bad.append("no date: the card must say so and the summary stay silent")
    if "Voici les portes ouvertes de son université : <strong>Université G &lt;img" not in c7 or "(Université G &lt;img" not in l7:
        bad.append("the university's open days are not named as such")
    if "aussi sur la fiche Parcoursup de la formation" not in c1 or "et la fiche Parcoursup de la formation" not in c1:
        bad.append("the fiche's confirmation is not said")
    if cn or ln or calls != "0":
        bad.append("output without data, or an API call")
    return not bad, f"differences {bad[:4]}"


# ----------------------------------------------------------------------------------------------------------------------- J7
class _Resp:
    def __init__(self, text, status=200, ctype="text/html"):
        self.text, self.status_code, self.headers, self.content = text, status, {"content-type": ctype}, text.encode()

    def json(self):
        return json.loads(self.text)


class _Client:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        return _Resp(*self.pages[url]) if url in self.pages else _Resp("", 404)


@check("J7 fetcher: Onisep columns by name, unchanged content stored once, keyword lines masked, same site, robots.txt, captures once")
def j7(c: Ctx):
    F = c.F()
    bad = []
    raw = ("code UAI;nom;URL et ID Onisep;journées portes ouvertes;date de modification;autre;université de rattachement libellé et UAI\n"
           "0590001a;Univ A;https://www.onisep.fr/E1;\"le 28/11/2026 | le 06/02/2027\";2026-10-15;x;\n"
           "0590002B;École B;;;2026-10-15;x;\n"
           "0590003C;UFR C;;;2026-10-15;x;Université X (0590004D)\n").encode("utf-8-sig")
    rows = F.onisep_rows(raw, "csv")
    if rows != [{"uai": "0590001A", "nom": "Univ A", "onisep_url": "https://www.onisep.fr/E1", "jpo": "le 28/11/2026 | le 06/02/2027",
                 "modif": "2026-10-15", "univ": ""},
                {"uai": "0590003C", "nom": "UFR C", "onisep_url": "", "jpo": "", "modif": "2026-10-15", "univ": "Université X (0590004D)"}]:
        bad.append(f"csv rows {rows}")
    js = json.dumps([{"code UAI": "0590001A", "nom": "A", "URL et ID Onisep": "", "journées portes ouvertes": "le 01/12/2026",
                      "date de modification": ""}]).encode()
    if [r["jpo"] for r in F.onisep_rows(js, "json") or []] != ["le 01/12/2026"]:
        bad.append("json rows")
    if F.onisep_rows(b"a;b\n1;2\n", "csv") is not None:
        bad.append("a file without the columns is read")
    tmp = Path(tempfile.mkdtemp())
    try:
        log = []
        F.store_version(tmp, "sup", rows, "2026-11-16", "onisep", "u", log)
        F.store_version(tmp, "sup", rows, "2026-11-17", "onisep", "u", log)
        if len(F.versions(tmp)) != 1:
            bad.append("an unchanged content stored twice")
        # an archived capture already read is not downloaded again
        (tmp / "onisep" / "archive_lues.txt").write_text("20250105000000 data.onisep.fr/api/v1/downloads/5fa586da5c4b6/5fa586da5c4b6.csv\n")
        cdx = json.dumps([["urlkey", "timestamp", "original"],
                          ["k", "20250105000000", "data.onisep.fr/api/v1/downloads/5fa586da5c4b6/5fa586da5c4b6.csv"]])

        class Cdx(_Client):
            def get(self, url, params=None, **kw):
                self.calls.append(url)
                return _Resp(cdx, 200, "application/json") if "cdx" in url else _Resp("", 404)
        cl = Cdx({})
        F.fetch_history(cl, tmp, [])
        if any("/web/" in u for u in cl.calls):
            bad.append("a capture already read is downloaded again")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    kl = F.keyword_lines("Accueil\nNos formations\nJournées portes ouvertes\nsamedi 30 janvier 2027\ncontact jpo@a.fr\nMentions\nPlan")
    if kl != "Journées portes ouvertes\nsamedi 30 janvier 2027\ncontact [adresse masquée]":
        bad.append(f"keyword lines {kl!r}")
    links = F.jpo_links('<a href="/actus/portes-ouvertes">Agenda</a><a href="https://evil.com/jpo">JPO</a>'
                        '<a href="https://www.univ-a.fr/x">Journées portes ouvertes</a><a href="/contact">Contact</a>',
                        "https://univ-a.fr/")
    try:
        F.jpo_links('<a href="http://[broken/jpo">JPO</a><a href="/jpo">JPO</a>', "https://univ-a.fr/")
    except Exception as e:  # noqa: BLE001
        bad.append(f"a malformed link stops the run ({type(e).__name__})")
    if links != ["https://univ-a.fr/actus/portes-ouvertes", "https://www.univ-a.fr/x"]:
        bad.append(f"links followed {links}")
    cl = _Client({"https://s.fr/robots.txt": ("User-agent: *\nDisallow: /prive/",), "https://s.fr/ok": ("<p>Portes ouvertes le 12/03/2027</p>",)})
    F.time.sleep = lambda s: None
    cr = F.Crawler(cl)
    if cr.get("https://s.fr/prive/jpo")[0] != "robots" or "https://s.fr/prive/jpo" in cl.calls:
        bad.append("robots.txt not honoured")
    for bad_url in ("https://", "https:///robots.txt", "/robots.txt", "https://a b.fr/x"):
        try:
            if cr.get(bad_url)[0] != "adresse invalide" or bad_url in cl.calls:
                bad.append(f"a malformed address fetched: {bad_url}")
        except Exception as e:  # noqa: BLE001
            bad.append(f"a malformed address stops the run: {bad_url} ({type(e).__name__})")

    class Boom(_Client):
        def get(self, url, **kw):
            raise ValueError("unknown url type")
    if F.Crawler(Boom({})).get("https://boom.fr/x")[1] is not None:
        bad.append("an unexpected client error is not caught")
    ext, st = F.visit(cr, "0590001A", ["https://s.fr/ok"])
    if st["status"] != "ok" or [e["text"] for e in ext] != ["Portes ouvertes le 12/03/2027"]:
        bad.append(f"visit {ext} {st}")
    return not bad, f"differences {bad[:4]}"


# ----------------------------------------------------------------------------------------------------------------------- J8
@check("J8 plumbing: workflow, build, API, fingerprint, vercelignore, sources, README, CLAUDE.md, tests and durations")
def j8(c: Ctx):
    bad = []
    wf = (REPO / ".github" / "workflows" / "suptracker-jpo.yml").read_text()
    for need in ("python scripts/jpo_fetch.py data/jpo --warehouse data/suptracker.duckdb", 'paths: ["suptracker/data/jpo/request.json"]',
                 "git add data/jpo", "git pull --rebase", "schedule:", "duckdb==2.0.0"):
        if need not in wf:
            bad.append(f"workflow: {need}")
    data = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    if "data/jpo/onisep data/jpo/sites/extraits.csv.gz" not in data or "cut -d, -f1,3 data/jpo/sites/etat.csv" not in data:
        bad.append("the warehouse fingerprint ignores data/jpo (or counts a check date)")
    if "jpo.build(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build (beside the warehouse: its 95 MB budget)")
    if '"jpo": JPO.for_formation(' not in (ROOT / "suptracker" / "api.py").read_text():
        bad.append("API")
    if "**/data/jpo/" not in (ROOT / ".vercelignore").read_text():
        bad.append("vercelignore")
    from suptracker import sources as SRC
    keys = {s["key"] for s in SRC.SOURCES if "jpo" in s.get("feeds", ())}
    if keys != {"onisep_structures", "sites_etablissements"}:
        bad.append(f"sources {keys}")
    if "jpoCard(d.jpo)" not in c.js or "${jpoLine(d.jpo)}" not in c.js:
        bad.append("the card or the summary line is not on the formation page")
    if "## Journées portes ouvertes" not in (ROOT / "README.md").read_text():
        bad.append("README")
    if "Journées portes ouvertes" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    if "tests/test_jpo.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()):
        bad.append("durations")
    if not (ROOT / "tests" / "test_jpo.py").exists():
        bad.append("test file")
    if not (ROOT / "data" / "jpo" / "request.json").exists():
        bad.append("request.json")
    return not bad, f"missing {bad}"


# ----------------------------------------------------------------------------------------------------------------------- J9
@check("J9 real data: the warehouse equals data/jpo, every served date is in the season, coverage measured")
def j9(c: Ctx):
    J = c.J()
    if not c.real or c.db is None:
        return True, "skipped (no --real)"
    if not (ROOT / "data" / "jpo" / "onisep" / "versions.csv").exists():
        return True, "data/jpo has no Onisep version yet (run the suptracker-jpo workflow)"
    import duckdb
    con = duckdb.connect(str(c.db), read_only=True)
    src, p = J._src(con)
    if src is None:
        return False, "neither the warehouse nor the file beside it has the open days: rebuild it"
    if p == "core.":
        return False, "the open days are in the warehouse, not in the file beside it (95 MB budget)"
    n = src.execute("SELECT count(*) FROM jpo_date").fetchone()[0]
    mem = duckdb.connect()
    mem.execute("CREATE SCHEMA core")
    J.build(mem, ROOT / "data" / "jpo")
    if src.execute("SELECT * FROM jpo_date ORDER BY ALL").fetchall() != mem.execute("SELECT * FROM core.jpo_date ORDER BY ALL").fetchall():
        return False, "the open days built differ from data/jpo and data/fiches: rebuild the warehouse"
    today = date.today()
    s = J.current_season(today)
    w0, w1 = J.window(s)
    cods = [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year
             WHERE session = (SELECT max(session) FROM core.formation_year) ORDER BY cod_aff_form""").fetchall()]
    dated = environ = 0
    bad = []
    for cod in cods:
        b = J.for_formation(con, cod, today)
        if not b:
            continue
        if b["dates"]:
            dated += 1
        elif b["environ"]:
            environ += 1
        for e in b["dates"]:
            if not (w0.isoformat() <= e["date"] <= w1.isoformat()):
                bad.append(f"{cod}: {e['date']}")
    return not bad, (f"{n} dates read; season {w0}..{w1}: {dated}/{len(cods)} formations with a date "
                     f"({100 * dated / max(1, len(cods)):.1f} %), {environ} with a period from past seasons; out of season {bad[:3]}")


# ---------------------------------------------------------------------------------------------------------------------- J10
SOURCE_MUTANTS = [
    ("jpo", "window ends in late May", "return date(season - 1, 9, 1), date(season, 5, 1)", "return date(season - 1, 9, 1), date(season, 5, 31)", "J2"),
    ("jpo", "1 May outside", "if d.month < 5 or (d.month == 5 and d.day == 1):", "if d.month < 5:", "J2"),
    ("jpo", "summer in the season", "    return None\n\n\ndef window", "    return d.year\n\n\ndef window", "J2"),
    ("jpo", "third cut at the 19th", 'return "début" if day <= 9 else "mi" if day <= 20 else "fin"',
     'return "début" if day <= 9 else "mi" if day <= 19 else "fin"', "J3"),
    ("jpo", "a day in the period", 'return f"mi-{m}" if t == "mi" else f"{t} {m}"', 'return f"mi-{m}" if t == "mi" else f"le 1er {m}"', "J3"),
    ("jpo", "removed future date announced", "if not latest and debut >= today:", "if False:", "J5"),
    ("jpo", "false weekday accepted", "if d is not None and fold(WEEKDAYS[d.weekday()]) != wd:", "if False:", "J4"),
    ("jpo", "date without year nor weekday accepted", "            else:\n                d = None\n            if d is not None:\n                out.add(d)",
     "            else:\n                d = _mkdate(dd, mo, s)\n            if d is not None:\n                out.add(d)", "J4"),
    ("jpo", "long line takes the next one", "        elif len(ln) <= HEADING and i + 1 < len(lines):", "        elif i + 1 < len(lines):", "J4"),
    ("jpo", "dated line takes the next one", "        if own:\n            found |= own", "        if False:\n            found |= own", "J5"),
    ("jpo", "agenda page adds dates", 'if e["onisep"] or e["fiche"] or (e.pop("_own") and e["uai"] not in with_onisep and not own_fiche)]',
     'if e["onisep"] or e["fiche"] or (e["uai"] not in with_onisep and not own_fiche)]', "J5"),
    ("jpo", "site adds dates beside Onisep's", 'if e["onisep"] or e["fiche"] or (e.pop("_own") and e["uai"] not in with_onisep and not own_fiche)]',
     'if e["onisep"] or e["fiche"] or e.pop("_own")]', "J5"),
    ("jpo", "collège line read", "if not KEYWORD.search(ln) or _OTHER_SCHOOL.search(fold(ln)):", "if not KEYWORD.search(ln):", "J5"),
    ("jpo", "agenda page feeds the period", ' and source != "site_agenda":', ":", "J5"),
    ("jpo", "publication date read", "            if _published(zone, mt.start()):\n                continue                                           # « Publié",
     "            if False:\n                continue                                           # « Publié", "J4"),
    ("jpo", "virtual flag lost", '"virtuel": bool(m.group(11)),', '"virtuel": False,', "J1"),
    ("jpo", "no masking", 'return _PHONE.sub("[téléphone masqué]", _EMAIL.sub("[adresse masquée]", text))', "return text", "J4"),
    ("jpo", "http links kept", 'url.startswith("https://") and not', 'url.startswith("http") and not', "J5"),
    ("jpo", "older past seasons", "MAX_PAST_SEASONS = 3", "MAX_PAST_SEASONS = 9", "J5"),
    ("jpo", "period beside dates", '"environ": None if dates else approx(past)', '"environ": approx(past)', "J5"),
    ("jpo", "reversed range accepted", "if m.group(4) and (d2 is None or d2 < d1):", "if m.group(4) and d2 is None:", "J1"),
    ("jpo", "cartographie UAI ignored", "    if c and c[0] and str(c[0]).strip().upper() not in out:", "    if False:", "J5"),
    ("jpo", "oldest campaign's UAI", "ORDER BY session DESC LIMIT 1", "ORDER BY session LIMIT 1", "J5"),
    ("jpo", "non-university attachment lends", 'if not m or "universit" not in fold(m.group(1)):', "if not m:", "J5"),
    ("jpo", "university beside own dates", '    if own and own["dates"]:\n        return own', '    if False:\n        return own', "J5"),
    ("jpo", "fiche agenda read", "cache[(tid, ses)] = [] if any(n > AGENDA for n in per.values()) else ds", "cache[(tid, ses)] = ds", "J5"),
    ("jpo", "fiche date shown twice", 'dates = [e for e in dates if not (e["uai"].startswith("formation:") and any(',
     'dates = [e for e in dates if True or not (e["uai"].startswith("formation:") and any(', "J5"),
    ("js", "university not named", "son université : <strong>${esc(j.universite.nom)}</strong>", "son université : <strong></strong>", "J6"),
    ("fetch", "robots ignored", "return rp.can_fetch(UA, url)", "return True", "J7"),
    ("fetch", "other sites followed", "site_of(url) == site_of(base) and (", "(", "J7"),
    ("fetch", "unchanged content stored again", 'if any(v["sha256"] == sha for v in same_kind):', "if False:", "J7"),
    ("fetch", "malformed address fetched", """        if not good_url(url):
            res = ("adresse invalide", None)
        elif not self.allowed(url):""", """        if not self.allowed(url):""", "J7"),
    ("fetch", "malformed link stops the run", """        except ValueError:                      # a malformed link""", """        except KeyError:                      # a malformed link""", "J7"),
    ("fetch", "whole page kept", "keep.update(range(i, min(i + 3, len(lines))))", "keep.update(range(len(lines)))", "J7"),
    ("fetch", "captures downloaded again", 'if f"{ts} {orig}" in seen:', "if False:", "J7"),
    ("fetch", "rows without open days kept", 'if (r["jpo"] or r["univ"]) and re.fullmatch', "if re.fullmatch", "J7"),
    ("fetch", "university column dropped", 'r.setdefault("univ", "")', 'r["univ"] = ""', "J7"),
    ("js", "remark unescaped", '${e.remarque ? ` (${esc(e.remarque)})` : ""}', '${e.remarque ? ` (${e.remarque})` : ""}', "J6"),
    ("js", "establishment unescaped", "noms.map(esc).join", "noms.join", "J6"),
    ("js", "passed date not marked", '${past ? " · passée" : ""}', "", "J6"),
    ("js", "no ODbL credit", "Source : Onisep, Idéo-Structures (licence ODbL)", "Source : Onisep", "J6"),
    ("js", "unsafe link", """const jpoUrl = (u) => (typeof u === "string" && /^https:\\/\\/[^\\s"'<>]+$/.test(u) ? u : null);""",
     "const jpoUrl = (u) => u || null;", "J6"),
    ("js", "period said as a date", "C'est une période, pas une date : à confirmer sur le site de l'établissement.", "", "J6"),
]


@check("J10 mutation test: every seeded bug is caught")
def j10(c: Ctx):
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
    ap.add_argument("--real", action="store_true", help="also check the committed warehouse and data/jpo")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
