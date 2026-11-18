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
  - a date read on Onisep AND on the site is « retrouvée sur le site de l'établissement »; a site-only date says where it was
    read and when, « à vérifier ». A site date must be on the keyword's own line (or under a short heading), never right after
    « publié le », never on a line naming a collège or a primary school; it only CONFIRMS Onisep's dates for an establishment
    Onisep dates this season, and is added (« à vérifier ») only where Onisep has none; a page printing more than AGENDA dates in
    a season is an agenda (several campuses or events): its dates only confirm and never feed the past-season period. The open days are the ESTABLISHMENT's, said with its name.
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
    r"(,\s*en virtuel)?"
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
        voir = m.group(13)
        out.append({"debut": d1, "fin": d2, "heures": heures, "remarque": (m.group(12) or "").strip() or None,
                    "virtuel": bool(m.group(11)),
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


HEADING = 80
_OTHER_SCHOOL = re.compile(r"\bcolleges?\b|\becoles? (?:primaires?|maternelles?|elementaires?)\b")   # another school on the same site
AGENDA = 4          # a page printing more open days than this in one season is an agenda (several campuses or events)
_PUBLISHED = re.compile(r"(?:publie|mis a jour|mise a jour|modifie|actualise|poste|redige)e?s?\s*(?:le\s*|:\s*|en date du\s*)*$")


def _published(zone: str, start: int) -> bool:
    """A date right after « publié le », « mis à jour le »… is the page's own date."""
    return bool(_PUBLISHED.search(zone[max(0, start - 40):start]))


def _dates_in(zone: str, s: int) -> set:
    """The dates of a folded zone of text: with their year printed, or with a weekday printed that is TRUE for season `s`."""
    out = set()
    for mt in _SITE_TEXTUAL.finditer(zone):
        if _published(zone, mt.start()):
            continue                                           # « Publié le 8 octobre 2025 »: the page's date, not an event
        wd, day, mon, year = mt.groups()
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
            out.add(d)
    for mt in _SITE_NUMERIC.finditer(zone):
        if _published(zone, mt.start()):
            continue
        dd, mo, yy = mt.groups()
        y = int(yy) + 2000 if len(yy) == 2 else int(yy)
        d = _mkdate(dd, mo, y)
        if d is not None:
            out.add(d)
    return out


def site_dates(text: str, fetched: date) -> list[date]:
    """The dates a site prints with « portes ouvertes » / « JPO »: on the keyword's own line, or on the next line when the
    keyword's line is a short heading (at most HEADING characters). A date counts with its year printed, or with a weekday
    printed that is TRUE for the season of the reading day (September-December = the reading season's first year,
    January-May its second); a date right after « publié le », « mis à jour le »… is the page's own date."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    s = current_season(fetched)
    found = set()

    def dates_in(zone: str) -> set:
        return _dates_in(zone, s)

    for i, ln in enumerate(lines):
        if not KEYWORD.search(ln) or _OTHER_SCHOOL.search(fold(ln)):
            continue
        own = dates_in(fold(ln))
        if own:
            found |= own                                           # the keyword's own line has its dates: the next line is other
        elif len(ln) <= HEADING and i + 1 < len(lines) and not _OTHER_SCHOOL.search(fold(lines[i + 1])):
            found |= dates_in(fold(ln + " " + lines[i + 1]))       # a short heading, its date on the next line (never a collège's: Codex)
    return sorted(d for d in found if season_of(d) is not None)


# ------------------------------------------------------------------------------------------------------------------ concours
# owner, 2026-11-18: a formation recruited through a concours (one exam for several schools) often has the CONCOURS's own
# information days and webinars. One row per concours: (key, name, the words of the formation's Parcoursup labels that name it,
# folded, and its official site). The site is read by the `suptracker-jpo` workflow (scripts/jpo_fetch.py, robots.txt honoured);
# it is shown only when a reading succeeded AND the page names the concours (`nomme`): a wrong or moved address shows nothing.
CONCOURS = (
    ("puissance_alpha", "Concours Puissance Alpha", r"\bconcours puissance alpha\b", "https://www.concourspuissancealpha.fr/", "puissance alpha"),
    ("avenir", "Concours Avenir", r"\bconcours avenir\b", "https://www.concours-avenir.fr/", "concours avenir"),
    ("geipi", "Concours Geipi Polytech", r"\bconcours geipi polytech\b", "https://www.geipi-polytech.org/", "geipi"),
    ("sesame", "Concours SESAME", r"\bconcours sesame\b", "https://www.concours-sesame.net/", "sesame"),
    ("advance", "Concours Advance", r"\bconcours advance\b", "https://www.concours-advance.fr/", "advance"),
    ("acces", "Concours ACCÈS", r"\bconcours acces\b", "https://www.concours-acces.com/", "acces"),
)
# an event line: a webinar or an online session, else an information day or open day; a line about registration, the exam
# or its results is never an event (the concours sites print those dates beside their sessions)
CONCOURS_EVENT = re.compile(r"webinaires?|webinars?|\bvisio|\blives?\b|portes?[\s-]+ouvertes?|\bjpo\b|"
                            r"(?:journees?|reunions?|sessions?|soirees?|matinees?) d.?information|\bsalons?\b")
CONCOURS_ONLINE = re.compile(r"webinaires?|webinars?|\bvisio|\blives?\b|\ben ligne\b|\ben distanciel\b|\bvirtuel")
CONCOURS_NOT = re.compile(r"\bepreuves?\b|\bresultats?\b|date limite|\bclotures?\b|\binscriptions? (?:sur|jusqu|du|avant)|"
                          r"\boraux?\b|\bentretiens?\b|\badmissibilit|\bconvocations?\b|\bpaiements?\b")
CONCOURS_AGENDA = 12      # more sessions than this in one season on one page: an agenda of every school, not the concours's own
# an event counts only when its own line (or heading + line) NAMES the concours: the concours agendas also list single schools'
# fairs and open days (SESAME: « LEM Strasbourg … salon Oriaction de Metz »), which are not the concours's (first real run)
CONCOURS_NAMES = {"puissance_alpha": r"\bpuissance alpha\b", "avenir": r"\bconcours avenir\b", "geipi": r"\bgeipi\b",
                  "sesame": r"\bsesame\b", "advance": r"\badvance\b", "acces": r"\bconcours acces\b"}
# a range of days « les 8-9 janvier 2027 », « du 19, 20 au 21 novembre » starts on its FIRST day (the date reader alone takes the last)
_DAY_RANGE = re.compile(r"\b(1er|\d{1,2})(?:\s*(?:-|–|,|et|au)\s*(?:1er|\d{1,2}))+\s+(" + "|".join(
    sorted(map(re.escape, _FOLD_MONTHS), key=len, reverse=True)) + r")\b")


def concours_of(labels: str) -> tuple | None:
    """The registry row of the concours a formation's Parcoursup labels name (folded words), or None."""
    t = fold(labels)
    return next((c for c in CONCOURS if re.search(c[2], t)), None)


def concours_events(text: str, fetched: date, concours: str | None = None) -> list[tuple[date, str]]:
    """(date, « en_ligne » | « information ») of the events a concours page prints: the event word and the date on the SAME
    line (or the next line under a short heading), the same date rules as the establishments' sites; never a line about
    registration, the exam or its results. With `concours`, only the events whose zone names it (CONCOURS_NAMES); a range of
    days counts from its first day."""
    lines = [_DAY_RANGE.sub(r"\1 \2", fold(ln.strip())) for ln in (text or "").splitlines()]
    named = re.compile(CONCOURS_NAMES[concours]) if concours else None
    s = current_season(fetched)
    out = {}
    for i, ln in enumerate(lines):
        if not CONCOURS_EVENT.search(ln) or CONCOURS_NOT.search(ln):
            continue
        zone = ln
        found = _dates_in(zone, s)
        if not found and len(ln) <= HEADING and i + 1 < len(lines) and not CONCOURS_NOT.search(lines[i + 1]):
            zone = ln + " " + lines[i + 1]
            found = _dates_in(zone, s)
        if named is not None and not named.search(zone):
            continue                                           # a school's own event listed on the concours's agenda
        kind = "en_ligne" if CONCOURS_ONLINE.search(zone) else "information"
        for d in found:
            if season_of(d) is not None and (d not in out or kind == "en_ligne"):
                out[d] = kind
    return sorted(out.items())


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
                un, uu = univ_of(r.get("univ") or "")
                etabs[uai] = {"nom": r.get("nom") or None, "onisep_url": r.get("onisep_url") or None,
                              "modif": r.get("modif") or None, "kind": v["kind"], "univ_uai": uu, "univ_nom": un}
            parts, bad = parse_onisep(r.get("jpo") or "")
            bad_parts += len(bad)
            for p in parts:
                dates.append({"uai": uai, "debut": p["debut"], "fin": p["fin"], "heures": p["heures"],
                              "remarque": p["remarque"], "virtuel": p["virtuel"], "ref_url": p["voir"], "source": "onisep",
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
            found = site_dates(r["text"], fetched)
            per_season = {}
            for dd in found:
                per_season[season_of(dd)] = per_season.get(season_of(dd), 0) + 1
            agenda = any(n > AGENDA for n in per_season.values())     # its dates only confirm Onisep's, never add one
            for dd in found:
                dates.append({"uai": r["uai"], "debut": dd, "fin": None, "heures": None, "remarque": None, "virtuel": False,
                              "ref_url": r["url"], "source": "site_agenda" if agenda else "site", "as_of": r["fetched"][:10],
                              "latest": r["fetched"] == newest[(r["uai"], r["url"])]})
    dates += fiche_dates(d.parent / "fiches", audit)
    conc, conc_sites = read_concours(d)
    return {"dates": dates, "etabs": etabs, "sites": sites, "audit": audit, "concours": conc, "concours_sites": conc_sites,
            "versions": [{k: v[k] for k in ("file", "kind", "as_of", "source")} for v in versions]}


def read_concours(d: Path = DIR) -> tuple[list[dict], list[dict]]:
    """The events read on the concours' official sites (data/jpo/concours, latest reading of each page flagged) and each
    site's reading status (`nomme`: the page names the concours)."""
    known = {c[0] for c in CONCOURS}
    events, sites = [], []
    ef = d / "concours" / "etat.csv"
    if ef.exists():
        with open(ef, encoding="utf-8", newline="") as f:
            sites = [r for r in csv.DictReader(f) if r.get("concours") in known]
    xf = d / "concours" / "extraits.csv.gz"
    if xf.exists():
        rows = [r for r in _read_csv_gz(xf) if r.get("concours") in known]
        newest = {}
        for r in rows:
            k = (r["concours"], r["url"])
            if k not in newest or r["fetched"] > newest[k]:
                newest[k] = r["fetched"]
        for r in rows:
            try:
                fetched = date.fromisoformat(r["fetched"][:10])
            except ValueError:
                continue
            ev = concours_events(r["text"], fetched, r["concours"])
            per_season = {}
            for dd, _ in ev:
                per_season[season_of(dd)] = per_season.get(season_of(dd), 0) + 1
            if any(n > CONCOURS_AGENDA for n in per_season.values()):
                continue
            for dd, kind in ev:
                events.append({"concours": r["concours"], "debut": dd, "kind": kind, "ref_url": r["url"], "as_of": r["fetched"][:10],
                               "latest": r["fetched"] == newest[(r["concours"], r["url"])]})
    return events, sites


def fiche_key(cod) -> str:
    return f"formation:{cod}"


FICHE_TEXT_COLS = ("complementaires_id", "conseils_id", "info_id")


def fiche_dates(fd: Path, audit: list) -> list[dict]:
    """The open days a formation's OWN Parcoursup fiche prints in its free texts (attendus complémentaires, conseils,
    informations), read by the site rules sentence by sentence (year printed or a weekday true for the fiche's campaign; no
    « publié le »; no collège line); a text printing more than AGENDA dates in a season is an agenda (salons, several
    campuses): never used. Keyed by formation (fiche_key), the reading day = the fiche's campaign (its January)."""
    af, tf = fd / "attendus.csv", fd / "textes.csv.gz"
    if not af.exists() or not tf.exists():
        audit.append("data/fiches: no attendus or texts (fiche open days not read)")
        return []
    with open(af, encoding="utf-8", newline="") as f:
        refs = [r for r in csv.DictReader(f)]
    need = {r[c] for r in refs for c in FICHE_TEXT_COLS if r.get(c)}
    texts = {}
    csv.field_size_limit(1 << 30)
    with gzip.open(tf, "rt", encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) == 2 and row[0] in need:
                texts[row[0]] = row[1]
    lus = {}
    ef = fd / "etat.csv"
    if ef.exists():
        with open(ef, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("status") == "ok" and r.get("lu_le"):
                    lus[(r["cod_aff_form"], r.get("session"))] = f"{r['lu_le'][:4]}-{r['lu_le'][4:6]}-{r['lu_le'][6:8]}"
    newest = {}
    for r in refs:
        newest[r["cod_aff_form"]] = max(newest.get(r["cod_aff_form"], ""), r["session"])
    cache, out = {}, []
    for r in refs:
        try:
            ses = int(r["session"])
        except ValueError:
            continue
        found = set()
        for c in FICHE_TEXT_COLS:
            tid = r.get(c)
            if not tid or tid not in texts:
                continue
            if (tid, ses) not in cache:
                t = texts[tid].replace(". ", ".\n").replace("; ", ";\n")
                ds = site_dates(t, date(ses, 1, 15))
                per = {}
                for dd in ds:
                    per[season_of(dd)] = per.get(season_of(dd), 0) + 1
                cache[(tid, ses)] = [] if any(n > AGENDA for n in per.values()) else ds
            found.update(cache[(tid, ses)])
        for dd in sorted(found):
            out.append({"uai": fiche_key(r["cod_aff_form"]), "debut": dd, "fin": None, "heures": None, "remarque": None,
                        "virtuel": False, "ref_url": None, "source": "fiche",
                        "as_of": lus.get((r["cod_aff_form"], r["session"]), f"{ses}-01-15"),
                        "latest": r["session"] == newest[r["cod_aff_form"]]})
    return out


_UNIV = re.compile(r"^(.*\S)\s*\((\d{7}[A-Z])\)\s*$")


def univ_of(label: str) -> tuple[str | None, str | None]:
    """« Université du Littoral Côte d'Opale (0595964M) » -> (name, UAI), only for a UNIVERSITY (the word in its name):
    another attachment (an institute, a group) is not a university."""
    m = _UNIV.match((label or "").strip())
    if not m or "universit" not in fold(m.group(1)):
        return None, None
    return m.group(1), m.group(2)


TABLES = ("jpo_date", "jpo_etab", "jpo_site", "jpo_meta", "jpo_concours", "jpo_concours_site")


def build(con, d: Path = DIR, textes: Path | None = None) -> dict:
    """jpo_date (every date read, with provenance), jpo_etab (latest Onisep establishments and their university), jpo_site
    (sites checked), jpo_meta (versions and audit). Written in the file BESIDE the warehouse (rapport_textes.duckdb, like the
    communes): in the warehouse they pushed it over its 95 MB budget (2026-11-16). Tests without that file keep them in core."""
    data = read(d) if d.exists() else {"dates": [], "etabs": {}, "sites": {}, "audit": ["data/jpo missing"], "versions": []}
    rows = sorted({(r["uai"], r["debut"], r["fin"], r["heures"], r["remarque"], r["virtuel"], r["ref_url"], r["source"], r["as_of"],
                    r["latest"]) for r in data["dates"]}, key=lambda t: tuple("" if x is None else str(x) for x in t))
    erows = [[u, e["nom"], e["onisep_url"], e["modif"], e["kind"], e.get("univ_uai"), e.get("univ_nom")]
             for u, e in sorted(data["etabs"].items())]
    srows = [[u, s["url"], s["status"], s["checked"]] for u, ss in sorted(data["sites"].items()) for s in ss]
    crows = sorted({(e["concours"], e["debut"], e["kind"], e["ref_url"], e["as_of"], e["latest"]) for e in data.get("concours", [])},
                   key=lambda t: tuple(str(x) for x in t))
    csrows = sorted({(r["concours"], r["url"], r["status"], r["checked"], r.get("nomme") == "1") for r in data.get("concours_sites", [])},
                    key=lambda t: tuple(str(x) for x in t))

    def write(c, p):
        c.execute(f"""CREATE OR REPLACE TABLE {p}jpo_date (uai VARCHAR, debut DATE, fin DATE, heures VARCHAR, remarque VARCHAR,
                      virtuel BOOLEAN, ref_url VARCHAR, source VARCHAR, as_of VARCHAR, latest BOOLEAN)""")
        if rows:
            c.executemany(f"INSERT INTO {p}jpo_date VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [list(r) for r in rows])
        c.execute(f"""CREATE OR REPLACE TABLE {p}jpo_etab (uai VARCHAR, nom VARCHAR, onisep_url VARCHAR, modif VARCHAR, kind VARCHAR,
                      univ_uai VARCHAR, univ_nom VARCHAR)""")
        if erows:
            c.executemany(f"INSERT INTO {p}jpo_etab VALUES (?, ?, ?, ?, ?, ?, ?)", erows)
        c.execute(f"CREATE OR REPLACE TABLE {p}jpo_site (uai VARCHAR, url VARCHAR, status VARCHAR, checked VARCHAR)")
        if srows:
            c.executemany(f"INSERT INTO {p}jpo_site VALUES (?, ?, ?, ?)", srows)
        c.execute(f"""CREATE OR REPLACE TABLE {p}jpo_concours (concours VARCHAR, debut DATE, kind VARCHAR, ref_url VARCHAR,
                      as_of VARCHAR, latest BOOLEAN)""")
        if crows:
            c.executemany(f"INSERT INTO {p}jpo_concours VALUES (?, ?, ?, ?, ?, ?)", [list(r) for r in crows])
        c.execute(f"""CREATE OR REPLACE TABLE {p}jpo_concours_site (concours VARCHAR, url VARCHAR, status VARCHAR, checked VARCHAR,
                      nomme BOOLEAN)""")
        if csrows:
            c.executemany(f"INSERT INTO {p}jpo_concours_site VALUES (?, ?, ?, ?, ?)", [list(r) for r in csrows])
        c.execute(f"CREATE OR REPLACE TABLE {p}jpo_meta (data VARCHAR)")
        c.execute(f"INSERT INTO {p}jpo_meta VALUES (?)",
                  [json.dumps({"versions": data["versions"], "audit": data["audit"]}, ensure_ascii=False)])

    if textes is None or not Path(textes).exists():
        write(con, "core.")
    else:
        import duckdb
        from . import rapports as RP
        for t in TABLES:
            con.execute(f"DROP TABLE IF EXISTS core.{t}")         # never a stale copy in the warehouse beside the file's
        RP._texts_con.cache_clear()                                # no read-only handle on the file while it is written
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    return {"dates": len(rows), "etablissements": len(erows), "concours": len(crows), "audit": data["audit"]}


def _src(con):
    """(cursor, table prefix) where the open days live: the warehouse (tests) or the file beside it; (None, None) before."""
    try:
        con.execute("SELECT 1 FROM core.jpo_date LIMIT 0")
        return con, "core."
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import rapports as RP
        db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
        f = RP.textes_path(Path(db[0])) if db and db[0] else None
        if f is None or not f.exists():
            return None, None
        c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
        c.execute("SELECT 1 FROM jpo_date LIMIT 0")
        return c, ""
    except Exception:  # noqa: BLE001  (a file built before the open days)
        return None, None


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
    return _src(con)[0] is not None


def for_uais(con, uais: list[str], today: date) -> dict | None:
    """The block of a list of establishments for the season of `today` (see the module's rules)."""
    c, p = _src(con)
    if not uais or c is None:
        return None
    s = current_season(today)
    w0, w1 = window(s)
    ph = ", ".join("?" * len(uais))
    rows = c.execute(f"""SELECT uai, debut, fin, heures, remarque, virtuel, ref_url, source, as_of, latest FROM {p}jpo_date
                         WHERE uai IN ({ph})""", uais).fetchall()
    etabs = {r[0]: {"nom": r[1], "onisep_url": https(r[2]), "modif": r[3]}
             for r in c.execute(f"SELECT uai, nom, onisep_url, modif FROM {p}jpo_etab WHERE uai IN ({ph})", uais).fetchall()}
    checked = {}
    for u, url, status, when in c.execute(f"SELECT uai, url, status, checked FROM {p}jpo_site WHERE uai IN ({ph})",
                                          uais).fetchall():
        if status == "ok" and (u not in checked or when > checked[u]["checked"]):
            checked[u] = {"url": https(url), "checked": when}
    cur, past = {}, []
    for uai, debut, fin, heures, remarque, virtuel, ref_url, source, as_of, latest in rows:
        ses = season_of(debut)
        if ses is None:
            continue
        if ses == s and w0 <= debut <= w1:
            if not latest and debut >= today:
                continue                              # a future date the newest version no longer lists: never announced
            k = (uai, debut)
            e = cur.setdefault(k, {"uai": uai, "date": debut.isoformat(), "fin": None, "heures": None, "remarque": None,
                                   "virtuel": False, "onisep": False, "fiche": None, "site": None, "lu_le": None, "_own": False})
            if source == "fiche":
                e["fiche"] = as_of
            elif source == "onisep":
                e["onisep"] = True
                e["fin"] = e["fin"] or (fin.isoformat() if fin else None)
                e["heures"] = e["heures"] or heures
                e["remarque"] = e["remarque"] or remarque
                e["virtuel"] = e["virtuel"] or bool(virtuel)
                e["voir"] = e.get("voir") or https(ref_url)
            else:
                e["_own"] = e["_own"] or source == "site"
                if e["site"] is None or as_of > (e["lu_le"] or ""):
                    e["site"], e["lu_le"] = https(ref_url), as_of
        elif ses < s and ses >= s - MAX_PAST_SEASONS and source != "site_agenda":
            past.append(debut)
    # a site date only CONFIRMS a date Onisep lists for an establishment that has Onisep dates this season (a site often
    # shows another campus or component); it is added only where Onisep has none, and never from an agenda page
    # (the formation's own fiche counts like Onisep: a formation whose fiche gives a date takes no site-only date)
    with_onisep = {e["uai"] for e in cur.values() if e["onisep"]}
    own_fiche = any(e["fiche"] for e in cur.values())
    dates = [e for e in cur.values()
             if e["onisep"] or e["fiche"] or (e.pop("_own") and e["uai"] not in with_onisep and not own_fiche)]
    # the fiche's date and the establishment's same date are one open day
    fiche_days = {e["date"]: e["fiche"] for e in dates if e["fiche"] and e["uai"].startswith("formation:")}
    dates = [e for e in dates if not (e["uai"].startswith("formation:") and any(
        x["date"] == e["date"] and not x["uai"].startswith("formation:") for x in dates))]
    for e in dates:
        e.pop("_own", None)
        e["fiche"] = e["fiche"] or fiche_days.get(e["date"])
    dates.sort(key=lambda e: (e["date"], e["uai"]))
    for e in dates:
        e["source"] = ("onisep_site" if e["onisep"] and e["site"] else "onisep" if e["onisep"]
                       else "fiche" if e["fiche"] and not e["site"] else "fiche_site" if e["fiche"] else "site")
        e["nom"] = (etabs.get(e["uai"]) or {}).get("nom")
    out = {"saison": {"debut": w0.isoformat(), "fin": w1.isoformat(), "annees": f"{s - 1}-{s}"},
           "dates": dates, "etablissements": [{"uai": u, **etabs[u]} for u in uais if u in etabs],
           "sites_verifies": [{"uai": u, **checked[u]} for u in uais if u in checked],
           "environ": None if dates else approx(past)}
    if not dates and not out["environ"] and not out["etablissements"]:
        return None
    return out


def university(con, uais: list[str]) -> tuple[str, str] | None:
    """The university the formation's establishment belongs to, as Onisep links it (« université de rattachement »), or the
    establishment itself when Onisep names a university attachment for it; None otherwise."""
    if not uais:
        return None
    c, p = _src(con)
    if c is None:
        return None
    try:
        ph = ", ".join("?" * len(uais))
        rows = c.execute(f"SELECT uai, univ_uai, univ_nom FROM {p}jpo_etab WHERE uai IN ({ph})", uais).fetchall()
    except Exception:  # noqa: BLE001  (a file before the university link)
        return None
    by = {u: (uu, un) for u, uu, un in rows}
    for u in uais:
        uu, un = by.get(u, (None, None))
        if uu and un and uu not in uais:
            return uu, un
    return None


def for_concours(con, cod: str, today: date) -> dict | None:
    """The concours block of a formation recruited through a concours of the registry: its name, its official site (only when
    a reading succeeded and named the concours), the events of the season read on that site (latest readings; a passed one
    flagged), each with the page read and the day it was read. None for a formation of no concours of the registry."""
    try:
        r = con.execute("""SELECT lib_for_voe_ins, lib_comp_voe_ins FROM core.formation_year WHERE cod_aff_form = ?
                           ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    except Exception:  # noqa: BLE001  (a warehouse without the labels)
        return None
    k = concours_of(" ".join(x or "" for x in r)) if r else None
    if k is None:
        return None
    out = {"cle": k[0], "nom": k[1], "site": None, "lu_le": None, "dates": []}
    c, p = _src(con)
    if c is None:
        return out
    try:
        sites = c.execute(f"SELECT url, status, checked, nomme FROM {p}jpo_concours_site WHERE concours = ?", [k[0]]).fetchall()
        rows = c.execute(f"SELECT debut, kind, ref_url, as_of FROM {p}jpo_concours WHERE concours = ? AND latest", [k[0]]).fetchall()
    except Exception:  # noqa: BLE001  (a file built before the concours)
        return out
    ok = sorted((s for s in sites if s[1] == "ok" and s[3]), key=lambda s: s[2], reverse=True)
    if ok:
        out["site"], out["lu_le"] = https(ok[0][0]) or https(k[3]), ok[0][2]
    s = current_season(today)
    w0, w1 = window(s)
    best = {}
    for debut, kind, url, as_of in rows:
        if season_of(debut) == s and w0 <= debut <= w1 and (debut not in best or kind == "en_ligne"):
            best[debut] = {"date": debut.isoformat(), "kind": kind, "url": https(url), "lu_le": as_of, "passee": debut < today}
    out["dates"] = [best[d] for d in sorted(best)] if out["site"] else []
    return out


def for_formation(con, cod: str, today: date | None = None) -> dict | None:
    """The formation's block: its establishment(s) and its own fiche. No date this season: the open days of the UNIVERSITY it
    belongs to (owner, 2026-11-16), named; then the period of past seasons (own first, else the university's). A formation
    recruited through a concours of the registry also carries the concours's own sessions (`concours`, owner 2026-11-18)."""
    today = today or datetime.now().date()
    res = _for_formation(con, cod, today)
    conc = for_concours(con, cod, today)
    if conc is None:
        return res
    if res is None:
        s = current_season(today)
        w0, w1 = window(s)
        res = {"saison": {"debut": w0.isoformat(), "fin": w1.isoformat(), "annees": f"{s - 1}-{s}"}, "dates": [],
               "etablissements": [], "sites_verifies": [], "environ": None}
    res["concours"] = conc
    return res


def _for_formation(con, cod: str, today: date) -> dict | None:
    uais = _uais(con, cod)
    own = for_uais(con, uais + [fiche_key(cod)], today)
    if own and own["dates"]:
        return own
    u = university(con, uais)
    ub = for_uais(con, [u[0]], today) if u else None
    if ub and (ub["dates"] or (ub["environ"] and not (own and own["environ"]))):
        ub["universite"] = {"uai": u[0], "nom": u[1]}
        if not ub["dates"] and own and own["environ"]:
            ub["environ"] = own["environ"]
        return ub
    return own


def meta(con) -> dict:
    c, p = _src(con)
    try:
        r = c.execute(f"SELECT data FROM {p}jpo_meta").fetchone() if c is not None else None
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
