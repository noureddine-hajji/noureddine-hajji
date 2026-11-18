"""Owner, 2026-11-18: what a round trip between the student's town and the formation costs, and how long it takes, « à titre
d'information » in the cost tab. The student's town NEVER leaves the browser: this module serves one parameter-less answer
(`/api/transports`, shared-cached) and the page computes everything there.

Sources (fetched by the `suptracker-transports` workflow into data/transports/, scripts/transports_fetch.py):
  - SNCF « Tarifs TGV INOUI et OUIGO »: the price RANGE (minimum, maximum) of a one-way ticket per origin-destination; only the
    2nd class « Tarif Normal » rows are read (the fare without a discount card), the two directions pooled;
  - SNCF « Gares de voyageurs »: the position of the stations those fares name (by UIC code); a station without a position is
    left out (counted);
  - « Prix des carburants en France » (Ministère de l'Économie): the MEDIAN price of each fuel over the stations that updated it
    in the last PRICE_DAYS days before the newest update, with its count and date; the same median PER DEPARTMENT (owner,
    2026-11-18: « au plus proche ») when at least MIN_STATIONS_DEP stations of the department updated it in that window. The
    page uses the student's department and falls back on the national median, fuel by fuel, and says which one it used.

The car estimate needs hypotheses no open dataset gives per trip; they are FIXED here (HYPOTHESES), sent with the data and
printed on the page: the road is 1.2 to 1.3 times the distance as the crow flies, a car burns 5 to 7 litres per 100 km, the
average speed is 90 to 110 km/h; tolls and parking are not counted (said). Plane and ferry fares are not public: the
page gives no figure for them, only a sentence; no carpooling or bus line (no public data). Never a promise of a price, always ranges.
"""
from __future__ import annotations

import csv
import gzip
import json
import statistics
import zlib
from datetime import date, timedelta
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "transports"
CLASSE, PROFIL = "2", "tarif normal"
PROFIL_ETUDIANT = "tarif eleve - etudiant - apprenti"     # folded: the SNCF's « Tarif Elève - Etudiant - Apprenti »
PRICE_DAYS = 30
MIN_STATIONS_DEP = 10            # fewer stations in the department: the national median of that fuel
FUELS = ("gazole", "e10", "sp95")
HYPOTHESES = {
    "detour": [1.2, 1.3],            # road distance / distance as the crow flies
    "conso_l_100km": [5, 7],         # litres per 100 km
    "vitesse_kmh": [90, 110],        # average speed on the road, door to door
    "gare_km": 30,                   # a station farther than this from the town (or the formation) is not « nearby »
    "avion_km": 500,                 # below this distance the plane is not suggested
}


def _rows(p: Path) -> list[dict]:
    with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _num(x: str) -> float | None:
    try:
        v = float(str(x).replace(",", ".").strip())
    except ValueError:
        return None
    return v if v > 0 else None


def fold(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def carrier(name: str) -> str:
    n = (name or "").upper()
    return "OUIGO" if "OUIGO" in n else "TGV INOUI" if "INOUI" in n else (name or "").strip()


def position(p: str) -> tuple[float, float] | None:
    """« 49.6852237, 1.7743058 » -> (lat, lon), or None."""
    try:
        la, lo = (float(x) for x in str(p).split(","))
    except ValueError:
        return None
    return (la, lo) if -90 <= la <= 90 and -180 <= lo <= 180 else None


def read(d: Path = DIR) -> dict:
    audit = []
    out = {"stations": [], "od": {}, "carburant": {}, "carburant_dep": {}, "lu_le": {}, "hypotheses": HYPOTHESES, "audit": audit}
    vf = d / "versions.csv"
    if vf.exists():
        with open(vf, encoding="utf-8", newline="") as f:
            out["lu_le"] = {r["fichier"].split(".")[0]: r["lu_le"] for r in csv.DictReader(f)}
    # stations: the positions, by UIC code
    pos = {}
    if (d / "gares.csv.gz").exists():
        for r in _rows(d / "gares.csv.gz"):
            uic = "".join(ch for ch in r.get("uic", "") if ch.isdigit())
            p = position(r.get("position", ""))
            if uic and p:
                pos[uic] = (r.get("nom") or "").strip(), p
    else:
        audit.append("gares.csv.gz missing")
    # fares: 2nd class, the normal fare and (apart) the pupil-student-apprentice fare, both directions pooled; a station needs a position
    od, etu, names, nopos = {}, {}, {}, set()
    if (d / "tarifs_tgv.csv.gz").exists():
        for r in _rows(d / "tarifs_tgv.csv.gz"):
            prof = fold(r.get("profil", ""))
            if r.get("classe", "").strip() != CLASSE or prof not in (PROFIL, PROFIL_ETUDIANT):
                continue
            a, b = r.get("origine_uic", "").strip(), r.get("destination_uic", "").strip()
            lo, hi = _num(r.get("prix_min", "")), _num(r.get("prix_max", ""))
            if not a or not b or a == b or lo is None or hi is None or hi < lo:
                continue
            for u, n in ((a, r.get("origine", "")), (b, r.get("destination", ""))):
                if u not in pos:
                    nopos.add(u)
                names.setdefault(u, n.strip())
            if a not in pos or b not in pos:
                continue
            k = "-".join(sorted((a, b)))
            if prof == PROFIL_ETUDIANT:
                x = etu.setdefault(k, [lo, hi])
                x[0], x[1] = min(x[0], lo), max(x[1], hi)
                continue
            e = od.setdefault(k, [lo, hi, set()])
            e[0], e[1] = min(e[0], lo), max(e[1], hi)
            e[2].add(carrier(r.get("transporteur", "")))
    else:
        audit.append("tarifs_tgv.csv.gz missing")
    if nopos:
        audit.append(f"{len(nopos)} fare stations without a position in « Gares de voyageurs » (left out)")
    used = sorted({u for k in od for u in k.split("-")})
    out["stations"] = [[u, (pos[u][0] or names.get(u, "")).strip(), round(pos[u][1][0], 4), round(pos[u][1][1], 4)] for u in used]
    # [normal min, normal max, carriers, student min, student max] (the student range only where the SNCF publishes it)
    out["od"] = {k: [round(v[0], 2), round(v[1], 2), sorted(v[2])] + ([round(etu[k][0], 2), round(etu[k][1], 2)] if k in etu else [])
                 for k, v in sorted(od.items())}
    # fuels: median over the stations updated in the last PRICE_DAYS days before the newest update
    if (d / "carburants.csv.gz").exists():
        rows = _rows(d / "carburants.csv.gz")
        for fuel in FUELS:
            vals = []
            for r in rows:
                v, m = _num(r.get(fuel, "")), (r.get(f"{fuel}_maj") or "")[:10]
                if v is None or not 0.5 <= v <= 5:          # euros per litre: a typo (0, 1000…) is never a price
                    continue
                try:
                    vals.append((v, date.fromisoformat(m), (r.get("departement") or "").strip().upper()))
                except ValueError:
                    continue
            if not vals:
                continue
            newest = max(t for _, t, _d in vals)
            recent = [(v, dep) for v, t, dep in vals if t >= newest - timedelta(days=PRICE_DAYS)]
            out["carburant"][fuel] = {"prix": round(statistics.median([v for v, _d in recent]), 3), "n": len(recent), "date": newest.isoformat()}
            per = {}
            for v, dep in recent:
                if dep:
                    per.setdefault(dep, []).append(v)
            for dep, vs in sorted(per.items()):
                if len(vs) >= MIN_STATIONS_DEP:
                    out["carburant_dep"].setdefault(dep, {})[fuel] = {"prix": round(statistics.median(vs), 3), "n": len(vs)}
    else:
        audit.append("carburants.csv.gz missing")
    return out


def build(con, d: Path = DIR, textes: Path | None = None) -> dict:
    """One compressed JSON value (`transports_data`) in the file beside the warehouse (like the communes: 95 MB budget); in the
    warehouse when that file does not exist (tests)."""
    data = read(d) if d.exists() else {"stations": [], "od": {}, "carburant": {}, "carburant_dep": {}, "lu_le": {}, "hypotheses": HYPOTHESES,
                                        "audit": ["data/transports missing"]}
    blob = zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"), 9)

    def write(c, p):
        c.execute(f"CREATE OR REPLACE TABLE {p}transports_data (data BLOB)")
        c.execute(f"INSERT INTO {p}transports_data VALUES (?)", [blob])

    if textes is None or not Path(textes).exists():
        write(con, "core.")
    else:
        import duckdb
        from . import rapports as RP
        con.execute("DROP TABLE IF EXISTS core.transports_data")
        RP._texts_con.cache_clear()
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    return {"stations": len(data["stations"]), "od": len(data["od"]), "carburants": sorted(data["carburant"]),
            "departements": len(data.get("carburant_dep", {})), "audit": data["audit"]}


def payload(con) -> dict:
    """The served answer (no parameter), from the warehouse (tests) or the file beside it; empty lists before the first build
    (the page then says the fares are not available yet)."""
    r = None
    try:
        r = con.execute("SELECT data FROM core.transports_data LIMIT 1").fetchone()
    except Exception:  # noqa: BLE001
        try:
            from . import rapports as RP
            db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
            f = RP.textes_path(Path(db[0])) if db and db[0] else None
            if f is not None and f.exists():
                c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
                r = c.execute("SELECT data FROM transports_data LIMIT 1").fetchone()
        except Exception:  # noqa: BLE001  (a file built before the transports)
            r = None
    if not r or r[0] is None:
        return {"stations": [], "od": {}, "carburant": {}, "carburant_dep": {}, "lu_le": {}, "hypotheses": HYPOTHESES}   # before the first build
    data = json.loads(zlib.decompress(bytes(r[0])).decode("utf-8"))
    data.pop("audit", None)
    return data
