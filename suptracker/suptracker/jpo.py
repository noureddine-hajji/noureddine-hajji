"""Journées portes ouvertes (owner, 2026-11-16): the open days of the establishment of each formation.

Sources, read by fixed rules only (never a date typed by hand, never a guess):
  - Onisep, Idéo-Structures d'enseignement supérieur and d'enseignement secondaire (the lycées that host BTS and CPGE), ODbL:
    the field « journées portes ouvertes » ("le 06/02/2027 de 09h00 à 16h00 (sur inscription) voir https://… | le …"),
    fetched by the `suptracker-jpo` workflow into data/jpo/onisep/ (every version whose content changed is kept, older
    versions come from the Internet Archive). The establishment is the Onisep UAI; a formation is linked by EXACT UAI only
    (its SIES UAI, then its cartographie UAI), never by name.
  - The establishment's own site (the Onisep « voir » link and the cartographie's site), read by the same workflow: only the
    lines around the words « portes ouvertes » / « JPO » are kept (data/jpo/sites/extraits.csv.gz, e-mails and phone numbers
    masked). A site date counts only with its year printed, or with its weekday printed and TRUE for the season's year.

Rules (owner's words):
  - the season of a date is [1 September Y-1, 1 May Y] (both included); a date outside every season (2 May - 31 August) is never
    shown. The season shown contains today, else it is the next one (2026-11-16: 1 September 2026 - 1 May 2027);
  - a future date of the season must be in the LATEST Onisep version (or on the site): a date Onisep removed is never announced;
    a past date of the season from an older version is shown as passed (Onisep drops passed open days);
  - no date this season: the dates of the previous seasons (at most 3) give a PERIOD by thirds of the month (1-9 « début »,
    10-20 « mi- », 21-31 « fin »): « aux alentours de mi-janvier », with the years read and « à confirmer ». Never a day;
  - a date read on Onisep AND on the site is « confirmée sur le site de l'établissement »; a site-only date says where it was
    read and when. The open days are the ESTABLISHMENT's, said with the establishment's name.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "jpo"
MAX_PAST_SEASONS = 3
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_FOLD_MONTHS = {unicodedata.normalize("NFKD", m).encode("ascii", "ignore").decode(): i + 1 for i, m in enumerate(MONTHS)}
_FOLD_MONTHS["fevr"] = 2
_FOLD_MONTHS["janv"] = 1
_FOLD_MONTHS["sept"] = 9
_FOLD_MONTHS["oct"] = 10
_FOLD_MONTHS["nov"] = 11
_FOLD_MONTHS["dec"] = 12


# --------------------------------------------------------------------------------------------------------------------- seasons
def season_of(d: date) -> int | None:
    """The season (its May year) a date belongs to, or None (2 May - 31 August belongs to none)."""
    if d.month >= 9:
        return d.year + 1
    if d.month < 5 or (d.month == 5 and d.day == 1):
        return d.year
    return None


def window(season: int) -> tuple[date, date]:
    return date(season - 1, 9, 1), date(season, 5, 1)


def current_season(today: date) -> int:
    """The season containing today, else the next one (summer: the coming school year)."""
    s = season_of(today)
    return s if s is not None else today.year + 1


def third(day: int) -> str:
    return "début" if day <= 9 else "mi" if day <= 20 else "fin"


def period_label(month: int, t: str) -> str:
    m = MONTHS[month - 1]
    return f"mi-{m}" if t == "mi" else f"{t} {m}"


def _season_rank(month: int) -> int:
    """September first, May last."""
    return (month - 9) % 12


def approx(past: list[date]) -> dict | None:
    """The period of the previous seasons' dates: distinct (month, third) in season order; more than three periods = the
    span « entre <first> et <last> »."""
    if not past:
        return None
    periods = sorted({(d.month, third(d.day)) for d in past},
                     key=lambda p: (_season_rank(p[0]), ("début", "mi", "fin").index(p[1])))
    labels = [period_label(*p) for p in periods]
    if len(labels) > 3:
        text = f"entre {labels[0]} et {labels[-1]}"
    elif len(labels) == 1:
        text = labels[0]
    else:
        text = ", ".join(labels[:-1]) + " et " + labels[-1]
    seasons = sorted({season_of(d) for d in past})
    return {"texte": f"aux alentours de {text}", "periodes": labels,
            "annees": [f"{s - 1}-{s}" for s in seasons], "n_dates": len(set(past))}


# ------------------------------------------------------------------------------------------------------------- Onisep parsing
_ONISEP_PART = re.compile(
    r"^(?:le|du)\s+(\d{2})/(\d{2})/(\d{4})"
    r"(?:\s+au\s+(\d{2})/(\d{2})/(\d{4}))?"
    r"(?:\s+de\s+(\d{1,2})h(\d{2})\s+(?:à|a)\s+(\d{1,2})h(\d{2}))?"
    r"\s*(?:\((.*?)\))?"
    r"\s*(?:voir\s+(\S+))?\s*$", re.I)


def _mkdate(d, m, y) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_onisep(field: str) -> tuple[list[dict], list[str]]:
    """The parts of an Onisep « journées portes ouvertes » field: [{debut, fin, heures, remarque, voir}], and the parts that
    match no rule (kept for the audit, never guessed)."""
    out, bad = [], []
    for part in (field or "").split("|"):
        part = " ".join(part.split())
        if not part:
            continue
        m = _ONISEP_PART.match(part)
        d1 = _mkdate(*m.group(1, 2, 3)) if m else None
        if not m or d1 is None:
            bad.append(part)
            continue
        d2 = _mkdate(*m.group(4, 5, 6)) if m.group(4) else None
        if m.group(4) and (d2 is None or d2 < d1):
            bad.append(part)
            continue
        heures = (f"{int(m.group(7))}h{m.group(8)} à {int(m.group(9))}h{m.group(10)}" if m.group(7) else None)
        voir = m.group(12)
        out.append({"debut": d1, "fin": d2, "heures": heures, "remarque": (m.group(11) or "").strip() or None,
                    "voir": voir if voir and voir.startswith(("https://", "http://")) else None})
    return out, bad


# --------------------------------------------------------------------------------------------------------------- site parsing
KEYWORD = re.compile(r"portes?[\s-]+ouvertes?|\bjpo\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\+33\s?|\b0)[1-9](?:[\s.-]?\d{2}){4}\b")


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def mask(text: str) -> str:
    """E-mail addresses and phone numbers masked (the sites name people)."""
    return _PHONE.sub("[téléphone masqué]", _EMAIL.sub("[adresse masquée]", text))


_MONTH_RE = "|".join(sorted(_FOLD_MONTHS, key=len, reverse=True))
_WD_RE = "|".join(fold(w) for w in WEEKDAYS)
_SITE_TEXTUAL = re.compile(
    rf"(?:\b({_WD_RE})\s+)?\b(1er|[0-3]?\d)\s+({_MONTH_RE})\.?(?:\s+(20\d\d))?\b")
_SITE_NUMERIC = re.compile(r"(?<![\d/])([0-3]?\d)[/.]([01]?\d)[/.](20\d\d|\d\d)(?![\d/])")


def site_dates(text: str, fetched: date) -> list[date]:
    """The dates a site prints near « portes ouvertes » / « JPO »: the keyword's line and the next two (a heading then its
    date). A date counts with its year printed, or with a weekday printed that is TRUE for the season of the reading day
    (September-December = the reading season's first year, January-May its second)."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    s = current_season(fetched)
    found = set()
    for i, ln in enumerate(lines):
        if not KEYWORD.search(ln):
            continue
        zone = fold(" ".join(lines[i:i + 3]))
        for wd, day, mon, year in _SITE_TEXTUAL.findall(zone):
            mo = _FOLD_MONTHS[mon]
            dd = 1 if day == "1er" else int(day)
            if year:
                d = _mkdate(dd, mo, year)
            elif wd:
                d = _mkdate(dd, mo, s - 1 if mo >= 9 else s)
                if d is not None and fold(WEEKDAYS[d.weekday()]) != wd:
                    d = None                                       # a weekday that is false that year: another year's page
            else:
                d = None
            if d is not None:
                found.add(d)
        for dd, mo, yy in _SITE_NUMERIC.findall(zone):
            y = int(yy) + 2000 if len(yy) == 2 else int(yy)
            d = _mkdate(dd, mo, y)
            if d is not None:
                found.add(d)
    return sorted(d for d in found if season_of(d) is not None)


# --------------------------------------------------------------------------------------------------------------------- reading
def _read_csv_gz(p: Path) -> list[dict]:
    with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read(d: Path = DIR) -> dict:
    """Every parsed date with its provenance, the establishments of the latest Onisep versions, the sites checked."""
    audit, dates, etabs, sites = [], [], {}, {}
    versions = []
    vf = d / "onisep" / "versions.csv"
    if vf.exists():
        with open(vf, encoding="utf-8", newline="") as f:
            versions = [r for r in csv.DictReader(f) if (d / "onisep" / r["file"]).exists()]
    else:
        audit.append("data/jpo/onisep/versions.csv missing")
    latest = {}
    for v in versions:
        if v["kind"] not in latest or v["as_of"] > latest[v["kind"]]["as_of"]:
            latest[v["kind"]] = v
    bad_parts = 0
    for v in versions:
        is_latest = latest[v["kind"]] is v
        for r in _read_csv_gz(d / "onisep" / v["file"]):
            uai = (r.get("uai") or "").strip().upper()
            if not re.fullmatch(r"\d{7}[A-Z]", uai):
                continue
            if is_latest:
                etabs[uai] = {"nom": r.get("nom") or None, "onisep_url": r.get("onisep_url") or None,
                              "modif": r.get("modif") or None, "kind": v["kind"]}
            parts, bad = parse_onisep(r.get("jpo") or "")
            bad_parts += len(bad)
            for p in parts:
                dates.append({"uai": uai, "debut": p["debut"], "fin": p["fin"], "heures": p["heures"],
                              "remarque": p["remarque"], "ref_url": p["voir"], "source": "onisep",
                              "as_of": v["as_of"], "latest": is_latest})
    if bad_parts:
        audit.append(f"{bad_parts} Onisep parts match no rule (not shown)")
    ef = d / "sites" / "etat.csv"
    if ef.exists():
        with open(ef, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                sites.setdefault(r["uai"], []).append({"url": r["url"], "status": r["status"], "checked": r["checked"]})
    xf = d / "sites" / "extraits.csv.gz"
    if xf.exists():
        rows = _read_csv_gz(xf)
        newest = {}
        for r in rows:
            k = (r["uai"], r["url"])
            if k not in newest or r["fetched"] > newest[k]:
                newest[k] = r["fetched"]
        for r in rows:
            try:
                fetched = date.fromisoformat(r["fetched"][:10])
            except ValueError:
                continue
            for dd in site_dates(r["text"], fetched):
                dates.append({"uai": r["uai"], "debut": dd, "fin": None, "heures": None, "remarque": None,
                              "ref_url": r["url"], "source": "site", "as_of": r["fetched"][:10],
                              "latest": r["fetched"] == newest[(r["uai"], r["url"])]})
    return {"dates": dates, "etabs": etabs, "sites": sites, "audit": audit,
            "versions": [{k: v[k] for k in ("file", "kind", "as_of", "source")} for v in versions]}


def build(con, d: Path = DIR) -> dict:
    """core.jpo_date (every date read, with provenance), core.jpo_etab (latest Onisep establishments), core.jpo_site (sites
    checked), core.jpo_meta (versions and audit)."""
    data = read(d) if d.exists() else {"dates": [], "etabs": {}, "sites": {}, "audit": ["data/jpo missing"], "versions": []}
    con.execute("""CREATE OR REPLACE TABLE core.jpo_date (uai VARCHAR, debut DATE, fin DATE, heures VARCHAR, remarque VARCHAR,
                   ref_url VARCHAR, source VARCHAR, as_of VARCHAR, latest BOOLEAN)""")
    rows = sorted({(r["uai"], r["debut"], r["fin"], r["heures"], r["remarque"], r["ref_url"], r["source"], r["as_of"],
                    r["latest"]) for r in data["dates"]}, key=lambda t: tuple("" if x is None else str(x) for x in t))
    if rows:
        con.executemany("INSERT INTO core.jpo_date VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [list(r) for r in rows])
    con.execute("CREATE OR REPLACE TABLE core.jpo_etab (uai VARCHAR, nom VARCHAR, onisep_url VARCHAR, modif VARCHAR, kind VARCHAR)")
    if data["etabs"]:
        con.executemany("INSERT INTO core.jpo_etab VALUES (?, ?, ?, ?, ?)",
                        [[u, e["nom"], e["onisep_url"], e["modif"], e["kind"]] for u, e in sorted(data["etabs"].items())])
    con.execute("CREATE OR REPLACE TABLE core.jpo_site (uai VARCHAR, url VARCHAR, status VARCHAR, checked VARCHAR)")
    srows = [[u, s["url"], s["status"], s["checked"]] for u, ss in sorted(data["sites"].items()) for s in ss]
    if srows:
        con.executemany("INSERT INTO core.jpo_site VALUES (?, ?, ?, ?)", srows)
    con.execute("CREATE OR REPLACE TABLE core.jpo_meta (data VARCHAR)")
    con.execute("INSERT INTO core.jpo_meta VALUES (?)",
                [json.dumps({"versions": data["versions"], "audit": data["audit"]}, ensure_ascii=False)])
    return {"dates": len(rows), "etablissements": len(data["etabs"]), "audit": data["audit"]}


# ------------------------------------------------------------------------------------------------------------------- serving
def https(url: str | None) -> str | None:
    return url if url and url.startswith("https://") and not re.search(r"[\s\"'<>]", url) else None


def _uais(con, cod: str) -> list[str]:
    """The formation's SIES UAI (latest campaign), then its cartographie UAI: exact codes only."""
    out = []
    r = con.execute("SELECT cod_uai FROM core.formation_year WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1",
                    [cod]).fetchone()
    if r and r[0]:
        out.append(str(r[0]).strip().upper())
    try:
        c = con.execute("SELECT etab_uai FROM core.cartographie WHERE cod_aff_form = ?", [cod]).fetchone()
    except Exception:  # noqa: BLE001  (a warehouse without the cartographie table)
        c = None
    if c and c[0] and str(c[0]).strip().upper() not in out:
        out.append(str(c[0]).strip().upper())
    return out


def _has(con) -> bool:
    try:
        con.execute("SELECT 1 FROM core.jpo_date LIMIT 0")
        return True
    except Exception:  # noqa: BLE001  (a warehouse built before the open days)
        return False


def for_uais(con, uais: list[str], today: date) -> dict | None:
    """The block of a list of establishments for the season of `today` (see the module's rules)."""
    if not uais or not _has(con):
        return None
    s = current_season(today)
    w0, w1 = window(s)
    ph = ", ".join("?" * len(uais))
    rows = con.execute(f"""SELECT uai, debut, fin, heures, remarque, ref_url, source, as_of, latest FROM core.jpo_date
                           WHERE uai IN ({ph})""", uais).fetchall()
    etabs = {r[0]: {"nom": r[1], "onisep_url": https(r[2]), "modif": r[3]}
             for r in con.execute(f"SELECT uai, nom, onisep_url, modif FROM core.jpo_etab WHERE uai IN ({ph})", uais).fetchall()}
    checked = {}
    for u, url, status, when in con.execute(f"SELECT uai, url, status, checked FROM core.jpo_site WHERE uai IN ({ph})",
                                            uais).fetchall():
        if status == "ok" and (u not in checked or when > checked[u]["checked"]):
            checked[u] = {"url": https(url), "checked": when}
    cur, past = {}, []
    for uai, debut, fin, heures, remarque, ref_url, source, as_of, latest in rows:
        ses = season_of(debut)
        if ses is None:
            continue
        if ses == s and w0 <= debut <= w1:
            if not latest and debut >= today:
                continue                              # a future date the newest version no longer lists: never announced
            k = (uai, debut)
            e = cur.setdefault(k, {"uai": uai, "date": debut.isoformat(), "fin": None, "heures": None, "remarque": None,
                                   "onisep": False, "site": None, "lu_le": None})
            if source == "onisep":
                e["onisep"] = True
                e["fin"] = e["fin"] or (fin.isoformat() if fin else None)
                e["heures"] = e["heures"] or heures
                e["remarque"] = e["remarque"] or remarque
                e["voir"] = e.get("voir") or https(ref_url)
            else:
                if e["site"] is None or as_of > (e["lu_le"] or ""):
                    e["site"], e["lu_le"] = https(ref_url), as_of
        elif ses < s and ses >= s - MAX_PAST_SEASONS:
            past.append(debut)
    dates = sorted(cur.values(), key=lambda e: (e["date"], e["uai"]))
    for e in dates:
        e["source"] = "onisep_site" if e["onisep"] and e["site"] else "onisep" if e["onisep"] else "site"
        e["nom"] = (etabs.get(e["uai"]) or {}).get("nom")
    out = {"saison": {"debut": w0.isoformat(), "fin": w1.isoformat(), "annees": f"{s - 1}-{s}"},
           "dates": dates, "etablissements": [{"uai": u, **etabs[u]} for u in uais if u in etabs],
           "sites_verifies": [{"uai": u, **checked[u]} for u in uais if u in checked],
           "environ": None if dates else approx(past)}
    if not dates and not out["environ"] and not out["etablissements"]:
        return None
    return out


def for_formation(con, cod: str, today: date | None = None) -> dict | None:
    return for_uais(con, _uais(con, cod), today or datetime.now().date())


def meta(con) -> dict:
    try:
        r = con.execute("SELECT data FROM core.jpo_meta").fetchone()
    except Exception:  # noqa: BLE001
        return {}
    return json.loads(r[0]) if r else {}


def csv_text(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()
