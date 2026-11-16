"""Journées portes ouvertes (owner, 2026-11-16): fetch the open days (blocked in the development sandbox).
    python scripts/jpo_fetch.py data/jpo [--warehouse data/suptracker.duckdb]
Reads data/jpo/request.json:
  {"onisep": true, "historique": true, "sites": true, "max_sites": 1500, "minutes": 40}
  - onisep: the two Onisep Idéo-Structures files (enseignement supérieur, enseignement secondaire), rows with open days only,
    kept as a NEW version only when their content changed (data/jpo/onisep/<kind>_<date>.csv.gz + versions.csv);
  - historique: the older versions of the same files archived by the Internet Archive (CDX, one capture a day at most), so a
    formation with no date this season can say when its open days usually were;
  - sites: the establishments' own sites (the Onisep « voir » link, the cartographie's « site internet »), oldest check first,
    robots.txt honoured, at most 4 pages per establishment on its own site; only the lines around « portes ouvertes » / « JPO »
    are kept (e-mails and phone numbers masked), appended to data/jpo/sites/extraits.csv.gz when they changed.
The dates are read from these files at build by the fixed rules of suptracker/jpo.py, never here.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html as htmlmod
import io
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from suptracker import jpo as J  # noqa: E402  (stdlib only)

UA = "Mozilla/5.0 (compatible; SupCompass open-days check; robot)"
ONISEP = {"sup": "https://data.onisep.fr/api/v1/downloads/5fa586da5c4b6/5fa586da5c4b6.csv",
          "sec": "https://data.onisep.fr/api/v1/downloads/5fa5816ac6a6e/5fa5816ac6a6e.csv"}
# where the Internet Archive may hold older copies of the same files (any format the files were published in)
ARCHIVE_PREFIXES = {"sup": ("data.onisep.fr/api/v1/downloads/5fa586da5c4b6/", "api.opendata.onisep.fr/downloads/5fa586da5c4b6/"),
                    "sec": ("data.onisep.fr/api/v1/downloads/5fa5816ac6a6e/", "api.opendata.onisep.fr/downloads/5fa5816ac6a6e/")}
CARTO = ("https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets/"
         "fr-esr-cartographie_formations_parcoursup/exports/csv?use_labels=true&delimiter=%3B")
COLS = ["uai", "nom", "onisep_url", "jpo", "modif", "univ"]
HEADERS = {"uai": ("code uai",), "nom": ("nom",), "onisep_url": ("url et id onisep",),
           "jpo": ("journees portes ouvertes",), "modif": ("date de modification",)}
# optional (owner, 2026-11-16): the university an establishment belongs to, « Université X (UAI) »; older files may lack it
OPTIONAL = {"univ": ("universite de rattachement libelle et uai",)}
LINK_WORDS = re.compile(r"portes?[\s_-]*ouvertes?|\bjpo\b|journees?[\s_-]+portes", re.I)


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def gz(text: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
        f.write(text.encode("utf-8"))
    return buf.getvalue()


# -------------------------------------------------------------------------------------------------------------------- Onisep
def onisep_rows(raw: bytes, fmt: str) -> list[dict] | None:
    """The rows with open days or a university of attachment of an Onisep Idéo-Structures file (csv, json or xlsx), with our
    column names; None when the file is not one (its columns are not found)."""
    if fmt == "json":
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            return None
        recs = data if isinstance(data, list) else data.get("results") or data.get("data") or []
        table = [list(recs[0].keys())] + [[r.get(k) for k in recs[0]] for r in recs] if recs else []
    elif fmt == "xlsx":
        try:
            import openpyxl
            ws = openpyxl.load_workbook(io.BytesIO(raw), read_only=True).worksheets[0]
            table = [[("" if c is None else str(c)) for c in row] for row in ws.iter_rows(values_only=True)]
        except Exception:  # noqa: BLE001
            return None
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        delim = ";" if text[:2000].count(";") >= text[:2000].count(",") else ","
        table = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not table:
        return None
    head = [J.fold(str(h)).strip() for h in table[0]]
    idx = {}
    for k, names in HEADERS.items():
        hit = [i for i, h in enumerate(head) if h in names]
        if not hit:
            return None
        idx[k] = hit[0]
    for k, names in OPTIONAL.items():
        hit = [i for i, h in enumerate(head) if h in names]
        if hit:
            idx[k] = hit[0]
    out = []
    for row in table[1:]:
        r = {k: (str(row[i]).strip() if i < len(row) and row[i] is not None else "") for k, i in idx.items()}
        r.setdefault("univ", "")
        # kept: the rows with open days, and the rows naming their university (a component borrows its university's day)
        if (r["jpo"] or r["univ"]) and re.fullmatch(r"\d{7}[A-Za-z]", r["uai"]):
            r["uai"] = r["uai"].upper()
            out.append(r)
    return sorted(out, key=lambda r: (r["uai"], r["jpo"]))


def versions(d: Path) -> list[dict]:
    f = d / "onisep" / "versions.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def store_version(d: Path, kind: str, rows: list[dict], as_of: str, source: str, url: str, log: list) -> None:
    text = J.csv_text(rows, COLS)
    sha = hashlib.sha256(text.encode()).hexdigest()
    vs = versions(d)
    same_kind = sorted((v for v in vs if v["kind"] == kind), key=lambda v: v["as_of"])
    if any(v["sha256"] == sha for v in same_kind):
        log.append({"kind": kind, "source": source, "as_of": as_of, "status": "same content as a kept version"})
        return
    name = f"{kind}_{as_of.replace('-', '')}_{source}.csv.gz"
    (d / "onisep").mkdir(parents=True, exist_ok=True)
    (d / "onisep" / name).write_bytes(gz(text))
    vs.append({"file": name, "kind": kind, "as_of": as_of, "source": source, "url": url, "sha256": sha, "rows": str(len(rows))})
    vs.sort(key=lambda v: (v["kind"], v["as_of"], v["source"]))
    (d / "onisep" / "versions.csv").write_text(J.csv_text(vs, ["file", "kind", "as_of", "source", "url", "sha256", "rows"]),
                                               encoding="utf-8")
    log.append({"kind": kind, "source": source, "as_of": as_of, "status": "kept", "rows": len(rows)})


def fetch_onisep(client, d: Path, log: list) -> None:
    for kind, url in ONISEP.items():
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            log.append({"kind": kind, "status": f"error {type(e).__name__}"})
            continue
        rows = onisep_rows(r.content, "csv") if r.status_code == 200 else None
        if not rows:
            log.append({"kind": kind, "status": f"unreadable (HTTP {r.status_code})"})
            continue
        store_version(d, kind, rows, today(), "onisep", url, log)


def fetch_history(client, d: Path, log: list) -> None:
    """Older copies archived by the Internet Archive: one capture a day at most, every format of the same file; the captures
    already read are listed in data/jpo/onisep/archive_lues.txt."""
    sf = d / "onisep" / "archive_lues.txt"
    seen = set(sf.read_text(encoding="utf-8").splitlines()) if sf.exists() else set()
    for kind, prefixes in ARCHIVE_PREFIXES.items():
        for prefix in prefixes:
            try:
                r = client.get("https://web.archive.org/cdx/search/cdx",
                               params={"url": prefix, "matchType": "prefix", "output": "json", "filter": "statuscode:200",
                                       "collapse": "timestamp:8", "limit": "400"}, timeout=120)
                caps = r.json()[1:] if r.status_code == 200 and r.text.strip() else []
            except (httpx.HTTPError, ValueError) as e:
                log.append({"kind": kind, "prefix": prefix, "status": f"cdx error {type(e).__name__}"})
                continue
            log.append({"kind": kind, "prefix": prefix, "captures": len(caps)})
            for cap in caps:
                ts, orig = cap[1], cap[2]
                if f"{ts} {orig}" in seen:
                    continue                                   # read on an earlier run: never downloaded twice
                fmt = next((x for x in ("csv", "json", "xlsx") if orig.lower().split("?")[0].endswith("." + x)), None)
                if fmt is None:
                    continue
                as_of = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                try:
                    a = client.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=180)
                except httpx.HTTPError as e:
                    log.append({"kind": kind, "as_of": as_of, "status": f"error {type(e).__name__}"})
                    continue
                rows = onisep_rows(a.content, fmt) if a.status_code == 200 else None
                if a.status_code == 200:
                    seen.add(f"{ts} {orig}")                   # a transient error is retried next run
                if not rows:
                    log.append({"kind": kind, "as_of": as_of, "status": f"unreadable {fmt} (HTTP {a.status_code})"})
                    continue
                store_version(d, kind, rows, as_of, "archive", f"https://web.archive.org/web/{ts}/{orig}", log)
    (d / "onisep").mkdir(parents=True, exist_ok=True)
    sf.write_text("".join(f"{x}\n" for x in sorted(seen)), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------------- sites
def page_text(html: str) -> str:
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(p|div|li|tr|h[1-6]|td|th|section|article|span|a|time|strong|b)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t).replace("\xa0", " ").replace(" ", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return "\n".join(x.strip() for x in t.splitlines() if x.strip())


def keyword_lines(text: str) -> str:
    """The lines around « portes ouvertes » / « JPO »: the keyword's line and the next two, masked, at most 4,000 characters."""
    lines = J.mask(text).splitlines()           # masked first: an address like jpo@… is not a keyword
    keep = set()
    for i, ln in enumerate(lines):
        if J.KEYWORD.search(ln):
            keep.update(range(i, min(i + 3, len(lines))))
    out = "\n".join(lines[i][:600] for i in sorted(keep))
    return out[:4000]


def good_url(url: str) -> bool:
    """An http(s) URL with a real host (the cartographie holds a few malformed site addresses)."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and "." in (p.hostname or "") and not re.search(r"[\s\"'<>]", url)


def site_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return ".".join(h.split(".")[-2:])


def jpo_links(html: str, base: str) -> list[str]:
    out = []
    for href, inner in re.findall(r'<a\b[^>]*?href="([^"#]+)[^"]*"[^>]*>(.*?)</a>', html, flags=re.S | re.I):
        try:
            url = urljoin(base, htmlmod.unescape(href))
        except ValueError:                      # a malformed link (« Invalid IPv6 URL »…): skipped
            continue
        text = J.fold(htmlmod.unescape(re.sub(r"<[^>]+>", " ", inner)))
        if good_url(url) and site_of(url) == site_of(base) and (
                LINK_WORDS.search(text) or LINK_WORDS.search(J.fold(url))):
            if url not in out:
                out.append(url)
    return out[:3]


class Crawler:
    def __init__(self, client):
        self.client = client
        self.robots: dict = {}
        self.pages: dict = {}
        self.host_locks: dict = {}
        self.lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        with self.lock:
            rp = self.robots.get(key)
        if rp is None:
            rp = robotparser.RobotFileParser()
            try:
                r = self.client.get(key + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:  # noqa: BLE001  (any failure: no rule known, the page itself is tried)
                rp.parse([])
            with self.lock:
                self.robots[key] = rp
        return rp.can_fetch(UA, url)

    def get(self, url: str) -> tuple[str, str | None]:
        """(status, html): status ok | robots | http <n> | error <type>. One request at a time per host, a second apart."""
        with self.lock:
            if url in self.pages:
                return self.pages[url]
            hl = self.host_locks.setdefault(urlparse(url).netloc, threading.Lock())
        if not good_url(url):
            res = ("adresse invalide", None)
        elif not self.allowed(url):
            res = ("robots", None)
        else:
            with hl:
                try:
                    r = self.client.get(url, timeout=25)
                    ok = r.status_code == 200 and "html" in r.headers.get("content-type", "html")
                    res = ("ok", r.text[:3_000_000]) if ok else (f"http {r.status_code}", None)
                except Exception as e:  # noqa: BLE001  (one bad site never stops the run)
                    res = (f"error {type(e).__name__}", None)
                time.sleep(1.0)
        with self.lock:
            self.pages[url] = res
        return res


def targets(d: Path, warehouse: str | None, client, log: list) -> dict:
    """{uai: [start urls]}: the UAIs of the latest campaign's formations and the cartographie, each with its Onisep « voir »
    links (latest versions) and its cartographie site."""
    uais = set()
    if warehouse and Path(warehouse).exists():
        import duckdb
        con = duckdb.connect(warehouse, read_only=True)
        uais |= {r[0] for r in con.execute("""SELECT DISTINCT upper(trim(cod_uai)) FROM core.formation_year
                 WHERE session = (SELECT max(session) FROM core.formation_year) AND cod_uai IS NOT NULL""").fetchall()}
        uais |= {r[0] for r in con.execute("SELECT DISTINCT upper(trim(etab_uai)) FROM core.cartographie WHERE etab_uai IS NOT NULL").fetchall()}
        con.close()
    starts: dict = {}
    latest = {}
    for v in versions(d):
        if v["kind"] not in latest or v["as_of"] > latest[v["kind"]]["as_of"]:
            latest[v["kind"]] = v
    for v in latest.values():
        with gzip.open(d / "onisep" / v["file"], "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r["uai"] in uais:
                    for p in J.parse_onisep(r["jpo"])[0]:
                        if p["voir"]:
                            starts.setdefault(r["uai"], []).append(p["voir"])
    try:
        r = client.get(CARTO, timeout=300)
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig", errors="replace")), delimiter=";")) if r.status_code == 200 else []
    except httpx.HTTPError as e:
        rows = []
        log.append({"cartographie": f"error {type(e).__name__}"})
    if rows:
        head = [J.fold(h) for h in rows[0]]
        iu = next((i for i, h in enumerate(head) if "uai" in h and "etab" in h), None)
        if iu is None:
            iu = next((i for i, h in enumerate(head) if "uai" in h), None)
        if iu is None:                          # no header names it: the column whose values are UAI codes
            sample = rows[1:2001]
            score = [sum(1 for r in sample if i < len(r) and re.fullmatch(r"\d{7}[A-Za-z]", r[i].strip())) for i in range(len(rows[0]))]
            iu = max(range(len(score)), key=score.__getitem__) if score and max(score) > len(sample) // 2 else None
        isite = next((i for i, h in enumerate(head) if "site internet" in h), None)
        log.append({"cartographie": "read", "uai_col": rows[0][iu] if iu is not None else None,
                    "site_col": rows[0][isite] if isite is not None else None})
        if iu is not None and isite is not None:
            for row in rows[1:]:
                if len(row) > max(iu, isite):
                    u, s = row[iu].strip().upper(), row[isite].strip()
                    if u in uais and s:
                        s = s if s.startswith(("http://", "https://")) else "https://" + s.lstrip("/")
                        if good_url(s):
                            starts.setdefault(u, []).append(s)
    return {u: [x for x in dict.fromkeys(ss) if good_url(x)][:3] for u, ss in starts.items() if any(good_url(x) for x in ss)}


def visit(cr: Crawler, uai: str, starts: list[str]) -> tuple[list[dict], dict]:
    """Up to 4 pages of the establishment's own site: its start pages, then the open-days links they carry."""
    seen, extraits, status = [], [], "pas_de_page"
    queue = list(starts)
    while queue and len(seen) < 4:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.append(url)
        st, html = cr.get(url)
        if html is None:
            status = status if status == "ok" else st
            continue
        status = "ok"
        text = keyword_lines(page_text(html))
        if text:
            extraits.append({"uai": uai, "url": url, "fetched": today(), "text": text})
        queue += [u for u in jpo_links(html, url) if u not in seen]
    return extraits, {"uai": uai, "url": starts[0], "status": status, "checked": today()}


def fetch_sites(client, d: Path, warehouse: str | None, req: dict, log: list) -> None:
    t0 = time.time()
    start = targets(d, warehouse, client, log)
    sd = d / "sites"
    sd.mkdir(parents=True, exist_ok=True)
    etat = {}
    if (sd / "etat.csv").exists():
        with open(sd / "etat.csv", encoding="utf-8", newline="") as f:
            etat = {r["uai"]: r for r in csv.DictReader(f)}
    order = sorted(start, key=lambda u: ((etat.get(u) or {}).get("checked", ""), u))[: int(req.get("max_sites", 1500))]
    old = J._read_csv_gz(sd / "extraits.csv.gz") if (sd / "extraits.csv.gz").exists() else []
    newest = {}
    for r in old:
        k = (r["uai"], r["url"])
        if k not in newest or r["fetched"] > newest[k]["fetched"]:
            newest[k] = r
    cr = Crawler(client)
    added, done = [], 0
    budget = float(req.get("minutes", 40)) * 60

    def job(u):
        if time.time() - t0 > budget:
            return None
        try:
            return visit(cr, u, start[u])
        except Exception as e:  # noqa: BLE001  (one establishment never stops the run: its error is its status)
            return [], {"uai": u, "url": start[u][0], "status": f"error {type(e).__name__}", "checked": today()}
    with ThreadPoolExecutor(8) as ex:
        for res in ex.map(job, order):
            if res is None:
                continue
            ext, st = res
            done += 1
            etat[st["uai"]] = st
            for e in ext:
                prev = newest.get((e["uai"], e["url"]))
                if prev is None or prev["text"] != e["text"]:
                    added.append(e)
    rows = sorted(old + added, key=lambda r: (r["uai"], r["url"], r["fetched"]))
    (sd / "extraits.csv.gz").write_bytes(gz(J.csv_text(rows, ["uai", "url", "fetched", "text"])))
    (sd / "etat.csv").write_text(J.csv_text(sorted(etat.values(), key=lambda r: r["uai"]), ["uai", "url", "status", "checked"]),
                                 encoding="utf-8")
    log.append({"sites": len(start), "visited": done, "new_extracts": len(added)})


def main(out: str, warehouse: str | None) -> int:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    rf = d / "request.json"
    req = json.loads(rf.read_text()) if rf.exists() else {"onisep": True, "historique": True, "sites": True}
    log: list = []
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"}) as client:
        if req.get("onisep", True):
            fetch_onisep(client, d, log)
        if req.get("historique", False):
            fetch_history(client, d, log)
        if req.get("sites", False):
            fetch_sites(client, d, warehouse, req, log)
    print(json.dumps(log, ensure_ascii=False, indent=1))
    if not versions(d):
        print("no Onisep version could be read", file=sys.stderr)
        return 1
    return 0                                    # the log is printed (job log), never committed: no commit for a date alone


if __name__ == "__main__":
    args = sys.argv[1:]
    wh = None
    if "--warehouse" in args:
        i = args.index("--warehouse")
        wh = args[i + 1]
        del args[i:i + 2]
    sys.exit(main(args[0], wh))
