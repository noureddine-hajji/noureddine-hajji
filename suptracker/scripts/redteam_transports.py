"""Red team, travel costs (owner, 2026-11-18): the round trip between the student's town and the formation, in the cost tab.

  TR1 reading: an INDEPENDENT reading of crafted SNCF and fuel files equals transports.read: only 2nd class « Tarif Normal » rows,
      both directions pooled (lowest minimum, highest maximum), carriers named OUIGO / TGV INOUI, a station without a position left
      out and counted, a fuel median over the stations updated in the last 30 days before the newest update, absurd prices dropped.
  TR2 page arithmetic (node): trCar, trTrain and the formatters equal a Python re-derivation on a grid of distances: road = crow-fly
      x detour range, round trip, the lowest price with the lowest consumption and the highest with the highest, time one way from
      the speed range; the nearest fare station within the radius on each side, none when the same station serves both, the
      published range x 2; euros rounded OUTWARDS.
  TR3 page text (node): every stored string escaped; no figure for carpooling, bus or plane; the plane only from 500 km; tolls and
      parking said not counted; the estimation label on the car; ODbL and Licence Ouverte credited; https links with noopener;
      vouvoiement; never a guaranteed price; a town at the formation says so; no town = a link to Mon profil.
  TR4 privacy: /api/transports takes no parameter and is shared-cached; the page calls it without a query string and never sends the
      town; the card is filled only while it is still on the page.
  TR5 fetcher (no network): columns read by their header names whatever the delimiter; a missing column keeps the file unchanged;
      an unchanged content is not rewritten; only the official hosts are fetched.
  TR6 plumbing: workflow (monthly, dispatch, request push on a claude/ branch, data/transports committed), build hook, API route,
      cache policy, sources (three, en ligne, licences), fingerprint, vercelignore, the card in « Combien ça coûte », README,
      CLAUDE.md, tests and durations.
  TR7 real data (--real, when data/transports holds the files): the served payload equals a reading of data/transports, and the
      share of the latest campaign's formations with a fare station within the radius is printed (measured, never typed).
  TR8 mutation test.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import io
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
CHECKS = []
HOSTILE = "<img src=x onerror=alert(1)>"


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
        self.src = {"tr": (ROOT / "suptracker" / "transports.py").read_text(), "fetch": (ROOT / "scripts" / "transports_fetch.py").read_text()}
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()

    def T(self):
        import suptracker  # noqa: F401
        return load(ROOT / "suptracker" / "transports.py", "suptracker.transports_rt", self.src["tr"])

    def F(self):
        return load(ROOT / "scripts" / "transports_fetch.py", "transports_fetch_rt", self.src["fetch"])


# ----------------------------------------------------------------------------------------------------------------- fixture
def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def csvtext(rows, cols):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


TARIFS = [  # transporteur, origine, uic, destination, uic, classe, profil, min, max
    ("OUIGO TRAIN CLASSIQUE", "PARIS " + HOSTILE, "87000001", "LYON", "87000002", "2", "Tarif Normal", "19", "79"),
    ("TGV INOUI", "LYON", "87000002", "PARIS " + HOSTILE, "87000001", "2", "Tarif Normal", "25", "120"),   # other direction: pooled
    ("TGV INOUI", "PARIS " + HOSTILE, "87000001", "LYON", "87000002", "1", "Tarif Normal", "40", "200"),  # 1st class: out
    ("TGV INOUI", "PARIS " + HOSTILE, "87000001", "LYON", "87000002", "2", "Tarif Avantage", "10", "50"),  # discount profile: out
    ("TGV INOUI", "PARIS " + HOSTILE, "87000001", "LILLE", "87000003", "2", "Tarif Normal", "30", "90"),
    ("TGV INOUI", "LYON", "87000002", "NOWHERE", "87000009", "2", "Tarif Normal", "15", "60"),          # no position: out, counted
    ("OUIGO", "LYON", "87000002", "LILLE", "87000003", "2", "Tarif Normal", "abc", "60"),              # unreadable price: out
    ("OUIGO", "LYON", "87000002", "LILLE", "87000003", "2", "Tarif Normal", "70", "40"),               # max < min: out
]
GARES = [("Paris " + HOSTILE, "87000001", "48.8443, 2.3744"), ("Lyon Part-Dieu", "87000002", "45.7606, 4.8595"),
         ("Lille Europe", "87000003", "50.6394, 3.0755"), ("Sans position", "87000004", "")]
FUEL = [  # id, gazole, maj, e10, maj
    ("1", "1.80", "2026-11-17T10:00:00+01:00", "1.90", "2026-11-17T10:00:00+01:00"),
    ("2", "1.70", "2026-11-10T10:00:00+01:00", "1.95", "2026-11-12T10:00:00+01:00"),
    ("3", "1.75", "2026-09-01T10:00:00+01:00", "1.70", "2026-09-01T10:00:00+01:00"),   # older than 30 days: out
    ("4", "0", "2026-11-17T10:00:00+01:00", "99", "2026-11-17T10:00:00+01:00"),        # absurd: out
    ("5", "1.90", "2026-11-16T10:00:00+01:00", "", ""),
    ("6", "2.40", "2026-11-15T10:00:00+01:00", "", ""),                                # a median, not a mean
]


def make_dir(base: Path) -> Path:
    d = base / "transports"
    d.mkdir(parents=True)
    tcols = ["transporteur", "origine", "origine_uic", "destination", "destination_uic", "classe", "profil", "prix_min", "prix_max"]
    (d / "tarifs_tgv.csv.gz").write_bytes(gz(csvtext([dict(zip(tcols, t)) for t in TARIFS], tcols)))
    (d / "gares.csv.gz").write_bytes(gz(csvtext([{"nom": n, "uic": u, "position": p, "commune": ""} for n, u, p in GARES],
                                                ["nom", "uic", "position", "commune"])))
    fcols = ["id", "departement", "gazole", "gazole_maj", "e10", "e10_maj", "sp95", "sp95_maj"]
    (d / "carburants.csv.gz").write_bytes(gz(csvtext([{"id": i, "departement": "75", "gazole": g, "gazole_maj": gm, "e10": e, "e10_maj": em,
                                                       "sp95": "", "sp95_maj": ""} for i, g, gm, e, em in FUEL], fcols)))
    (d / "versions.csv").write_text(csvtext([{"fichier": "tarifs_tgv.csv.gz", "lu_le": "2026-11-18", "url": "x", "lignes": "8", "sha256": "x"}],
                                            ["fichier", "lu_le", "url", "lignes", "sha256"]))
    return d


def oracle_read():
    pos = {u: tuple(float(x) for x in p.split(",")) for _n, u, p in GARES if p}
    od = {}
    for car, _o, a, _de, b, cl, prof, lo, hi in TARIFS:
        if cl != "2" or prof.lower() != "tarif normal":
            continue
        try:
            lo, hi = float(lo), float(hi)
        except ValueError:
            continue
        if hi < lo or a not in pos or b not in pos:
            continue
        k = "-".join(sorted((a, b)))
        e = od.setdefault(k, [lo, hi, set()])
        e[0], e[1] = min(e[0], lo), max(e[1], hi)
        e[2].add("OUIGO" if "OUIGO" in car else "TGV INOUI")
    fuel = {}
    for col, idx in (("gazole", (1, 2)), ("e10", (3, 4))):
        vals = [(float(r[idx[0]]), r[idx[1]][:10]) for r in FUEL if r[idx[0]] and 0.5 <= float(r[idx[0]]) <= 5]
        newest = max(t for _, t in vals)
        from datetime import date, timedelta
        cut = (date.fromisoformat(newest) - timedelta(days=30)).isoformat()
        rec = [v for v, t in vals if t >= cut]
        fuel[col] = {"prix": round(statistics.median(rec), 3), "n": len(rec), "date": newest}
    return {k: [v[0], v[1], sorted(v[2])] for k, v in od.items()}, fuel


@check("TR1 reading: 2nd class normal fare, both directions pooled, stations with a position, fuel medians of the last 30 days")
def tr1(c: Ctx):
    T = c.T()
    tmp = Path(tempfile.mkdtemp())
    try:
        got = T.read(make_dir(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    od, fuel = oracle_read()
    bad = []
    if got["od"] != od:
        bad.append(f"fares {got['od']} != {od}")
    if got["carburant"] != fuel:
        bad.append(f"fuels {got['carburant']} != {fuel}")
    if sorted(s[0] for s in got["stations"]) != ["87000001", "87000002", "87000003"]:
        bad.append(f"stations {[s[0] for s in got['stations']]}")
    if not any("without a position" in a for a in got["audit"]):
        bad.append("a station without a position is not counted")
    if got["hypotheses"] != T.HYPOTHESES or got["lu_le"].get("tarifs_tgv") != "2026-11-18":
        bad.append("hypotheses or reading date not served")
    return not bad, f"{len(od)} fares, {len(fuel)} fuels; differences {bad[:3]}"


# ------------------------------------------------------------------------------------------------------------------ page
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
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


STUB = """const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d });
const estimTag = () => '<span class="estim">estimation</span>';
const frDate = (iso) => iso;
const villeLabel = (c) => `${c.nom} (${c.dep})`;
"""
NAMES = ("haversineKm", "trNearest", "trCar", "trTrain", "trEuros", "trHours", "trFr", "TR_LINKS", "transportsHtml")


def hav(a, b, c, d):
    R = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def payload(T):
    tmp = Path(tempfile.mkdtemp())
    try:
        return T.read(make_dir(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@check("TR2 page arithmetic: car range and time, nearest stations within the radius, published range x 2, euros rounded outwards")
def tr2(c: Ctx):
    if not all(top(c.js, n) for n in NAMES):
        return False, "a function is missing from app.js"
    T = c.T()
    P = payload(T)
    H = P["hypotheses"]
    homes = [{"nom": "A", "dep": "75", "lat": 48.85 + i * 0.4, "lon": 2.35 + i * 0.3} for i in range(-3, 9)] \
        + [{"nom": "Villeurbanne", "dep": "69", "lat": 45.77, "lon": 4.88}]          # the same station serves both
    dest = (45.76, 4.86)
    prog = STUB + "\n".join(top(c.js, n) for n in NAMES) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const out = D.homes.map((h) => { const km = haversineKm(h.lat, h.lon, D.dest[0], D.dest[1]);
        return { km, car: trCar(km, D.P.hypotheses, D.P.carburant), tr: trTrain(D.P, h, D.dest[0], D.dest[1]) }; });
      out.push({ eur: [trEuros([19.4, 79.2]), trEuros([40, 40]), trHours(59.6), trHours(125), trHours(119.7)] });
      process.stdout.write(JSON.stringify(out));"""
    out = node(prog, {"homes": homes, "dest": dest, "P": P})
    if out is None:
        return True, "node absent: not run"
    bad = []
    prices = [x["prix"] for x in P["carburant"].values()]
    st = {s[0]: (s[2], s[3]) for s in P["stations"]}
    for h, o in zip(homes, out):
        km = hav(h["lat"], h["lon"], *dest)
        if abs(o["km"] - km) > 1e-6:
            bad.append("haversine")
            break
        road = [km * H["detour"][0], km * H["detour"][1]]
        cost = [2 * road[0] * H["conso_l_100km"][0] / 100 * min(prices), 2 * road[1] * H["conso_l_100km"][1] / 100 * max(prices)]
        mins = [road[0] / H["vitesse_kmh"][1] * 60, road[1] / H["vitesse_kmh"][0] * 60]
        if any(abs(a - b) > 1e-6 for a, b in zip(o["car"]["cost"] + o["car"]["minutes"], cost + mins)):
            bad.append(("car", o["car"], cost, mins))
            break
        near = lambda la, lo: min(((hav(la, lo, *p), u) for u, p in st.items() if hav(la, lo, *p) <= H["gare_km"]), default=None)
        a, b = near(h["lat"], h["lon"]), near(*dest)
        tr = o["tr"]
        if a is None or b is None:
            ok = "none" in tr and "price" not in tr
        elif a[1] == b[1]:
            ok = "none" in tr and "même gare" in tr["none"]
        else:
            k = "-".join(sorted((a[1], b[1])))
            ok = (k in P["od"] and tr.get("price") == [2 * P["od"][k][0], 2 * P["od"][k][1]]) or (k not in P["od"] and "none" in tr)
        if not ok:
            bad.append(("train", h, tr))
            break
    if out[-1]["eur"] != ["19 à 80 €", "40 €", "1 h", "2 h 05", "2 h"]:
        bad.append(("formatting", out[-1]["eur"]))
    covered = sum(1 for o in out[:-1] if o["tr"].get("price"))
    if not covered:
        bad.append("no trip with a TGV price (vacuous)")
    return not bad, f"{len(homes)} towns, {covered} with a TGV fare; differences {bad[:3]}"


@check("TR3 page text: escaped, no figure for carpooling / bus / plane, plane from 500 km, tolls said, credits, safe links, no promise")
def tr3(c: Ctx):
    if not all(top(c.js, n) for n in NAMES):
        return False, "a function is missing from app.js"
    P = payload(c.T())
    prog = STUB + "\n".join(top(c.js, n) for n in NAMES + ("transportsCard",)) + """
      const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      let VD = null; const villeDepart = () => VD;
      const near = transportsHtml(D.P, { nom: "Paris" + D.H, dep: "75", lat: 48.8443, lon: 2.3744 }, 45.7606, 4.8595);
      const far = transportsHtml(D.P, { nom: "Brest", dep: "29", lat: 48.39, lon: -4.49 }, 43.3, 5.37);
      const same = transportsHtml(D.P, { nom: "Lyon", dep: "69", lat: 45.7606, lon: 4.8595 }, 45.7606, 4.8595);
      const noTown = transportsCard({ lat: 45.7, lon: 4.8 }); VD = { nom: "x", dep: "1", lat: 1, lon: 1 };
      process.stdout.write(JSON.stringify([near, far, same, noTown, transportsCard({ lat: null })]));"""
    o = node(prog, {"P": P, "H": HOSTILE})
    if o is None:
        return True, "node absent: not run"
    near, far, same, no_town, none = o
    bad = []
    if "<img" in near + far:
        bad.append("a stored string is not escaped")
    rows = dict(re.findall(r"<tr><td>([^<]*)</td><td class=\"num\" data-label=\"Aller-retour\">([^<]*)</td>", near + far))
    for mode in ("Covoiturage", "Bus", "Avion"):
        if mode in rows and rows[mode] != "pas de prix public":
            bad.append(f"a figure for {mode}")
    if "Avion" in near or "Avion" not in far:
        bad.append("the plane is not limited to long trips")
    if not re.search(r"Train \(OUIGO, TGV INOUI\)</td><td class=\"num\" data-label=\"Aller-retour\">38 à 240 €", near):
        bad.append("the TGV row is not the published range x 2 with its carriers")
    if "Péages et parking non compris" not in near or "estimation" not in near or "carburant seul" not in near:
        bad.append("the car row lacks its estimation label or its caveats")
    if "ODbL" not in near or "Licence Ouverte" not in near or "jamais envoyée" not in near or "pas des prix garantis" not in near:
        bad.append("credits, privacy sentence or caveat missing")
    links = re.findall(r'<a href="([^"]+)"([^>]*)>', near + far)
    if not links or any(not u.startswith("https://") or 'rel="noopener"' not in a for u, a in links):
        bad.append("an unsafe link")
    if "même commune" not in same or 'href="#/profil"' not in no_town or none != "":
        bad.append("same town, no town or no position not handled")
    txt = re.sub(r"<[^>]+>", " ", near + far + same + no_town)
    if re.search(r"\b(tu|ton|ta|tes|toi)\b", txt, re.I) or re.search(r"garanti", txt.replace("pas des prix garantis", "")):
        bad.append("tutoiement or a promise")
    return not bad, f"differences {bad[:4]}"


@check("TR4 privacy: no parameter, shared-cached, the town never sent, the card filled only while on the page")
def tr4(c: Ctx):
    bad = []
    api = (ROOT / "suptracker" / "api.py").read_text()
    if '@app.get("/api/transports")\ndef transports_data():' not in api:
        bad.append("the route takes a parameter or is gone")
    cache_src = (ROOT / "suptracker" / "cache.py").read_text()
    if '(r"/api/transports", PUBLIC,' not in cache_src:
        bad.append("not shared-cached")
    if 'api("/api/transports")' not in top(c.js, "trLoad") and 'api("/api/transports")' not in c.js:
        bad.append("the page does not call the route plainly")
    body = c.js[c.js.index("let TRANSPORTS_P"):c.js.index("function distanceBlock(")]
    if re.search(r'api\(`[^`]*\$\{', body) or re.search(r"/api/transports\?", body):
        bad.append("a parameter sent with the trip")
    fill = top(c.js, "fillTransports")
    if 'if (!el || el !== document.getElementById("transports-body")) return;' not in fill:
        bad.append("the card is filled after the student left the page")
    return not bad, f"problems {bad}"


@check("TR5 fetcher: columns by header name, a missing column keeps the file, unchanged content not rewritten, official hosts only")
def tr5(c: Ctx):
    F = c.F()
    bad = []
    raw = "﻿Transporteur;Gare origine;Gare origine - code UIC;Gare destination;Gare destination - code UIC;Classe;Profil tarifaire;Prix minimum;Prix maximum\nOUIGO;A;1;B;2;2;Tarif Normal;10;20\n".encode()
    rows = F.pick(raw, F.SOURCES["tarifs_tgv"][1])
    if rows != [{"transporteur": "OUIGO", "origine": "A", "origine_uic": "1", "destination": "B", "destination_uic": "2", "classe": "2",
                 "profil": "Tarif Normal", "prix_min": "10", "prix_max": "20"}]:
        bad.append(f"columns by name {rows}")
    if F.pick(b"a,b\n1,2\n", F.SOURCES["gares"][1]) is not None:
        bad.append("a file without the columns is read")
    hosts = {re.match(r"https://([^/]+)/", u).group(1) for u, _ in F.SOURCES.values()}
    if hosts != {"ressources.data.sncf.com", "data.economie.gouv.fr"}:
        bad.append(f"hosts {hosts}")
    if "if f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == digest:" not in c.src["fetch"]:
        bad.append("an unchanged file is rewritten")
    return not bad, f"problems {bad}"


@check("TR6 plumbing: workflow, build, API, cache, sources, fingerprint, vercelignore, card in the cost tab, docs, tests")
def tr6(c: Ctx):
    bad = []
    wf = REPO / ".github" / "workflows" / "suptracker-transports.yml"
    w = wf.read_text() if wf.exists() else ""
    if not w or "workflow_dispatch" not in w or "schedule" not in w or "suptracker/data/transports/request.json" not in w or "git add data/transports" not in w:
        bad.append("workflow")
    if "transports.build(con, textes=rapports.textes_path(db_path))" not in (ROOT / "suptracker" / "build.py").read_text():
        bad.append("build")
    data = (REPO / ".github" / "workflows" / "suptracker-data.yml").read_text()
    if "data/transports/tarifs_tgv.csv.gz data/transports/gares.csv.gz data/transports/carburants.csv.gz" not in data:
        bad.append("fingerprint")
    if "**/data/transports/" not in (ROOT / ".vercelignore").read_text():
        bad.append("vercelignore")
    from suptracker import sources as SRC
    srcs = {s["key"]: s for s in SRC.SOURCES if "transports" in s.get("feeds", ())}
    if set(srcs) != {"sncf_tarifs_tgv", "sncf_gares", "prix_carburants"} or any(s["status"] != "en_ligne" for s in srcs.values()) \
            or srcs.get("sncf_tarifs_tgv", {}).get("licence", "").find("ODbL") < 0:
        bad.append("sources")
    vf = c.js[c.js.index("async function viewFormation("):]
    if '["cout", "Combien ça coûte", coutCard(d.vie, r) + transportsCard(d.vie)' not in vf or "fillTransports(d.vie);" not in vf:
        bad.append("the card is not in « Combien ça coûte »")
    if "## Travel costs" not in (ROOT / "README.md").read_text():
        bad.append("README")
    if "Travel costs (owner, 2026-11-18)" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md")
    if "tests/test_transports.py" not in json.loads((ROOT / "tests" / "durations.json").read_text()) or not (ROOT / "tests" / "test_transports.py").exists():
        bad.append("tests")
    if not (ROOT / "data" / "transports" / "request.json").exists():
        bad.append("request.json")
    return not bad, f"missing {bad}"


@check("TR7 real data: the payload equals data/transports, the stations near the formations measured")
def tr7(c: Ctx):
    d = ROOT / "data" / "transports"
    if not c.real or not (d / "tarifs_tgv.csv.gz").exists():
        return True, "skipped (no --real or no data/transports files yet)"
    import duckdb
    T = c.T()
    con = duckdb.connect(str(c.db), read_only=True)
    served = T.payload(con)
    want = T.read(d)
    want.pop("audit", None)
    if served != want or not served["stations"]:
        return False, "the served payload differs from data/transports (warehouse not rebuilt?)"
    st = [(s[2], s[3]) for s in served["stations"]]
    rows = con.execute("""SELECT DISTINCT lat, lon FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year)
                          AND lat IS NOT NULL AND lon IS NOT NULL""").fetchall()
    near = sum(1 for la, lo in rows if any(hav(la, lo, a, b) <= T.HYPOTHESES["gare_km"] for a, b in st))
    return True, f"{len(served['stations'])} stations, {len(served['od'])} fares, fuels {sorted(served['carburant'])}; {near} of {len(rows)} formations within {T.HYPOTHESES['gare_km']} km of a fare station"


SOURCE_MUTANTS = [
    ("tr", "1st class read", 'if r.get("classe", "").strip() != CLASSE or r.get("profil", "").strip().lower() != PROFIL:',
     'if r.get("profil", "").strip().lower() != PROFIL:', "TR1"),
    ("tr", "discount fares read", 'if r.get("classe", "").strip() != CLASSE or r.get("profil", "").strip().lower() != PROFIL:',
     'if r.get("classe", "").strip() != CLASSE:', "TR1"),
    ("tr", "directions not pooled", 'k = "-".join(sorted((a, b)))', 'k = f"{a}-{b}"', "TR1"),
    ("tr", "reversed range kept", "if not a or not b or a == b or lo is None or hi is None or hi < lo:", "if not a or not b or a == b or lo is None or hi is None:", "TR1"),
    ("tr", "stations without position kept", "            if a not in pos or b not in pos:\n                continue", "            if False:\n                continue", "TR1"),
    ("tr", "old fuel prices counted", "recent = [v for v, t in vals if t >= newest - timedelta(days=PRICE_DAYS)]", "recent = [v for v, t in vals]", "TR1"),
    ("tr", "absurd prices counted", "if v is None or not 0.5 <= v <= 5:", "if v is None:", "TR1"),
    ("tr", "mean instead of median", '"prix": round(statistics.median(recent), 3)', '"prix": round(statistics.mean(recent), 3)', "TR1"),
    ("js", "one way instead of a round trip", "  return { a, b, price: [2 * od[0], 2 * od[1]], carriers: od[2] };", "  return { a, b, price: [od[0], od[1]], carriers: od[2] };", "TR2"),
    ("js", "detour ignored", "  const road = [km * H.detour[0], km * H.detour[1]];", "  const road = [km, km];", "TR2"),
    ("js", "prices crossed", "* H.conso_l_100km[0] / 100 * Math.min(...prices), 2 * road[1] * H.conso_l_100km[1] / 100 * Math.max(...prices)]",
     "* H.conso_l_100km[0] / 100 * Math.max(...prices), 2 * road[1] * H.conso_l_100km[1] / 100 * Math.min(...prices)]", "TR2"),
    ("js", "radius ignored", "    if (km <= maxKm && (!best || km < best.km)) best = { uic, nom, km };", "    if (!best || km < best.km) best = { uic, nom, km };", "TR2"),
    ("js", "same station priced", '  if (a.uic === b.uic) return { none: "la même gare TGV dessert votre ville et la formation" };', "", "TR2"),
    ("js", "euros rounded inwards", "Math.floor(x[0]))}${x[0] === x[1] ? \"\" : ` à ${fmt(Math.ceil(x[1]))}`}", "Math.round(x[0]))}${x[0] === x[1] ? \"\" : ` à ${fmt(Math.round(x[1]))}`}", "TR2"),
    ("js", "station name unescaped", "entre les gares de ${esc(tr.a.nom)} et ${esc(tr.b.nom)}", "entre les gares de ${tr.a.nom} et ${tr.b.nom}", "TR3"),
    ("js", "plane always shown", "  if (km >= H.avion_km) rows.push(", "  if (true) rows.push(", "TR3"),
    ("js", "tolls not said", " Péages et parking non compris.", "", "TR3"),
    ("js", "credits dropped", "« Gares de voyageurs » (licence ODbL)", "« Gares de voyageurs »", "TR3"),
    ("js", "town sent", 'api("/api/transports")', 'api(`/api/transports?ville=${encodeURIComponent((villeDepart() || {}).nom || "")}`)', "TR4"),
    ("js", "late fill", '  if (!el || el !== document.getElementById("transports-body")) return;', "  if (!el) return;", "TR4"),
    ("fetch", "other host", 'ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/gares-de-voyageurs', 'example.com/api/explore/v2.1/catalog/datasets/gares-de-voyageurs', "TR5"),
]


@check("TR8 mutation test: every seeded bug is caught")
def tr8(c: Ctx):
    targets = {m[4] for m in SOURCE_MUTANTS}
    base_bad = [fn.check_name.split()[0] for fn in CHECKS if fn.check_name.split()[0] in targets and not fn(c)[0]]
    if base_bad:
        return False, f"the unmutated code fails {base_bad}: mutants not counted"
    caught, missed = 0, []
    for kind, name, old, new, target in SOURCE_MUTANTS:
        m = copy.copy(c)
        m.real = False
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
    ap.add_argument("--real", action="store_true", help="also check the committed warehouse and data/transports")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    a = ap.parse_args(argv)
    res = run(db=a.db, real=a.real)
    for r in res:
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['check']} ({r['s']} s)\n     {r['detail']}")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
