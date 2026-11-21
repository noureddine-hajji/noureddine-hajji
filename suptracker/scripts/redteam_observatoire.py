"""Red team of the Observatoire page (owner, 2026-11-19): national trends, demand per académie, same-académie admits.
    python scripts/redteam_observatoire.py [--db data/suptracker.duckdb] [--real]
  OB1 trends re-derived in SQL: per campaign and type (the map's `diplome_of`), vœux par place = SUM(nb_voe_pp) / SUM(capa_fin)
      over the rows with places > 0, the MEDIAN of the official access rates, the formation counts; a type is followed only
      with MIN_TYPE formations in EVERY campaign, and every such type is followed
  OB2 demand per académie re-derived in SQL (latest campaign, folded académie labels): counts, ratio and thresholds, the
      Île-de-France line = the three académies' summed counts, one label per folded key (the accented spelling), every
      académie of the campaign listed, overseas never placed on the map
  OB3 same-académie share re-derived in SQL: SUM(acc_aca_orig) / SUM(acc_neobac) over coherent rows (people), thresholds,
      never above 100 %; on real data the published pct_aca_orig = acc_aca_orig / acc_neobac (the denominator is said)
  OB4 a crafted warehouse: Besançon spelled two ways is one académie, Île-de-France summed, places 0 left out, an incoherent
      row left out, a type missing a campaign not followed, overseas not placed
  OB5 page in Node on hostile data: escaped labels, every figure cell labelled, "pas vos chances", the vœux / people and
      néo-bachelier wording, no figure under the threshold ("trop peu de formations"), one Île-de-France bubble, overseas
      listed apart, chart and map named, no ramp shade below 3:1 on the chart, at most OBS_MAX series
  OB6 wording: no chance / probability / promise, vouvoiement, no sort of formations
  OB7 wiring: route, both menus, TAB_OF / ROUTE_NAME, shared cache with no parameter, analytics route, release guard, feature
  OB8 mutation test (in memory)
  OB9 who the admits are, re-derived in SQL: girls among the admits and among the vœux, bac routes, mentions (first and latest
      campaigns, SIES's own denominator; 2022's one-admit gaps kept), coherent rows only, thresholds, order
  OB10 a crafted table: incoherent girls / routes / mentions rows left out, the one-admit gap kept, thresholds, first campaign
  OB11 the page's three new sections in Node: escaped, 10 types shown then folded, route colours named, caveats, the gap computed
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suptracker import carte as CA  # noqa: E402
from suptracker import observatoire as OBS  # noqa: E402

STATIC = ROOT / "suptracker" / "static"
CHECKS = []
CHANCE = re.compile(r"(?i)\bprobabilit|\d+\s*%\s*de chances|chances? d'[eê]tre (?:admis|pris)|vous serez admis|garanti")
FORMAL = re.compile(r"\b(?:[Tt]u|[Tt]on|[Tt]a|[Tt]es|[Tt]oi)\b")
HOSTILE = '<img src=x onerror=alert(1)>'
M = {"OBS": OBS}
COLS = ("session", "fili", "form_lib_voe_acc", "fil_lib_voe_acc", "lib_for_voe_ins", "acad_mies", "nb_voe_pp", "capa_fin",
        "taux_acces_ens", "acc_neobac", "acc_aca_orig", "lat", "lon", "acc_tot", "acc_tot_f", "voe_tot", "voe_tot_f", "acc_bg", "acc_bt",
        "acc_bp", "acc_sansmention", "acc_ab", "acc_b", "acc_tb", "acc_tbf", "acc_mention_non_renseignee")


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def mem_of(con) -> duckdb.DuckDBPyConnection:
    """An in-memory copy of the columns read, with the type of each row from the map's rule (a table, then plain SQL)."""
    src = con.execute(f"SELECT {', '.join(COLS)} FROM core.formation_year").df()
    m = duckdb.connect(":memory:")
    m.register("src", src)
    m.execute("""CREATE TABLE f AS SELECT session::INT AS session, fili, form_lib_voe_acc AS form, fil_lib_voe_acc AS fil,
        lib_for_voe_ins AS lib, acad_mies AS acad, nb_voe_pp::BIGINT AS voe, capa_fin::BIGINT AS capa, taux_acces_ens::DOUBLE AS taux,
        acc_neobac::BIGINT AS neo, acc_aca_orig::BIGINT AS aca, lat::DOUBLE AS lat, lon::DOUBLE AS lon, acc_tot::BIGINT AS tot,
        acc_tot_f::BIGINT AS tot_f, voe_tot::BIGINT AS vt, voe_tot_f::BIGINT AS vt_f, acc_bg::BIGINT AS bg, acc_bt::BIGINT AS bt,
        acc_bp::BIGINT AS bp, acc_sansmention::BIGINT AS sm, acc_ab::BIGINT AS ab, acc_b::BIGINT AS b, acc_tb::BIGINT AS tb,
        acc_tbf::BIGINT AS tbf, acc_mention_non_renseignee::BIGINT AS nr FROM src""")
    m.unregister("src")
    keys = m.execute("SELECT DISTINCT fili, form, fil, lib FROM f").fetchall()
    m.execute("CREATE TABLE ty (fili VARCHAR, form VARCHAR, fil VARCHAR, lib VARCHAR, typ VARCHAR)")
    m.executemany("INSERT INTO ty VALUES (?, ?, ?, ?, ?)", [(*k, CA.diplome_of(*k)[0]) for k in keys])
    m.execute("""CREATE TABLE r AS SELECT f.*, ty.typ,
        trim(regexp_replace(regexp_replace(lower(strip_accents(coalesce(acad, ''))), '[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g')) AS k
        FROM f JOIN ty ON f.fili IS NOT DISTINCT FROM ty.fili AND f.form IS NOT DISTINCT FROM ty.form
          AND f.fil IS NOT DISTINCT FROM ty.fil AND f.lib IS NOT DISTINCT FROM ty.lib""")
    return m


def r1(x):
    return None if x is None else round(x, 1)


def derive(m, o=None) -> dict:
    o = o or M["OBS"]
    sessions = [s for (s,) in m.execute("SELECT DISTINCT session FROM r ORDER BY 1").fetchall()]
    last = sessions[-1]
    tr = {}
    for typ, ses, n, v, p, nr, med, nt in m.execute("""SELECT typ, session, count(*),
            sum(voe) FILTER (WHERE voe IS NOT NULL AND capa > 0), sum(capa) FILTER (WHERE voe IS NOT NULL AND capa > 0),
            count(*) FILTER (WHERE voe IS NOT NULL AND capa > 0), median(taux), count(taux) FROM r GROUP BY ALL""").fetchall():
        tr.setdefault(typ, {})[ses] = {"session": ses, "formations": n, "formations_ratio": nr, "voeux": v or 0, "places": p or 0,
                                       "voeux_par_place": round((v or 0) / p, 1) if p else None, "taux_median": r1(med), "n_taux": nt}
    followed = {t: [by[s] for s in sessions] for t, by in tr.items() if all(by.get(s, {}).get("formations", 0) >= o.MIN_TYPE for s in sessions)}
    dem = {}
    for scope in ("typ", f"'{o.TOUS}'"):
        for typ, k, n, v, p in m.execute(f"""SELECT {scope}, k, count(*) FILTER (WHERE voe IS NOT NULL AND capa > 0),
                coalesce(sum(voe) FILTER (WHERE voe IS NOT NULL AND capa > 0), 0), coalesce(sum(capa) FILTER (WHERE voe IS NOT NULL AND capa > 0), 0)
                FROM r WHERE session = {last} AND k <> '' GROUP BY ALL""").fetchall():
            ok = n >= o.MIN_ACAD_FORMATIONS and p >= o.MIN_ACAD_PLACES
            dem.setdefault(typ, {})[k] = {"formations": n, "voeux": v, "places": p, "voeux_par_place": round(v / p, 1) if ok and p else None}
    idf = {}
    for typ, by in dem.items():
        n, v, p = (sum(by[k][f] for k in ("paris", "creteil", "versailles") if k in by) for f in ("formations", "voeux", "places"))
        idf[typ] = {"formations": n, "voeux": v, "places": p,
                    "voeux_par_place": round(v / p, 1) if n >= o.MIN_ACAD_FORMATIONS and p >= o.MIN_ACAD_PLACES and p else None}
    prox = {}
    for scope in ("typ", f"'{o.TOUS}'"):
        for typ, n, neo, aca in m.execute(f"""SELECT {scope}, count(*), sum(neo), sum(aca) FROM r
                WHERE session = {last} AND neo > 0 AND aca IS NOT NULL AND aca BETWEEN 0 AND neo GROUP BY ALL""").fetchall():
            part = round(100 * aca / neo, 1) if neo >= o.MIN_NEOBAC and n >= o.MIN_PROX_FORMATIONS else None
            prox[typ] = {"diplome": typ, "formations": n, "admis_neobac": neo, "meme_academie": aca, "part_meme_academie": part}
    pos = {k: (la, lo) for k, la, lo in m.execute(f"""SELECT k, avg(lat), avg(lon) FROM r WHERE session = {last} AND k <> ''
        AND lat IS NOT NULL AND lon IS NOT NULL GROUP BY k""").fetchall()}
    keys = {k for (k,) in m.execute(f"SELECT DISTINCT k FROM r WHERE session = {last} AND k <> ''").fetchall()}
    return {"sessions": sessions, "last": last, "followed": followed, "demande": dem, "idf": idf, "prox": prox, "pos": pos, "keys": keys}


def derive_profils(m, o=None) -> dict:
    """Girls, bac routes and mentions per type re-derived in SQL from the same published counts (people)."""
    o = o or M["OBS"]
    first, last = m.execute("SELECT min(session), max(session) FROM r").fetchone()
    ok = lambda n, tot: tot >= o.MIN_NEOBAC and n >= o.MIN_PROX_FORMATIONS  # noqa: E731
    pc = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    fil, bac, men = {}, {}, {}
    for scope in ("typ", f"'{o.TOUS}'"):
        for typ, n, tot, f, vt, vf in m.execute(f"""SELECT {scope}, count(*), sum(tot), sum(tot_f), sum(vt), sum(vt_f) FROM r
                WHERE session = {last} AND tot > 0 AND tot_f BETWEEN 0 AND tot AND vt > 0 AND vt_f BETWEEN 0 AND vt GROUP BY ALL""").fetchall():
            fil[typ] = {"diplome": typ, "formations": n, "admis": tot, "admises": f, "voeux": vt, "voeux_filles": vf,
                        "part_admis": pc(f, tot) if ok(n, tot) else None, "part_voeux": pc(vf, vt) if ok(n, tot) else None}
        for typ, n, neo, g, t, p in m.execute(f"""SELECT {scope}, count(*), sum(neo), sum(bg), sum(bt), sum(bp) FROM r
                WHERE session = {last} AND neo > 0 AND bg + bt + bp = neo GROUP BY ALL""").fetchall():
            good = ok(n, neo)
            bac[typ] = {"diplome": typ, "formations": n, "admis_neobac": neo, "general": g, "techno": t, "pro": p,
                        "part_general": pc(g, neo) if good else None, "part_techno": pc(t, neo) if good else None,
                        "part_pro": pc(p, neo) if good else None}
        for typ, ses, n, neo, sm, ab, b, tb, tbf in m.execute(f"""SELECT {scope}, session, count(*), sum(neo), sum(sm), sum(ab), sum(b),
                sum(tb), sum(tbf) FROM r WHERE session IN ({first}, {last}) AND neo > 0 AND sm + ab + b + tb + tbf + coalesce(nr, 0) <= neo
                GROUP BY ALL""").fetchall():
            men.setdefault(typ, {})[ses] = {"formations": n, "admis_neobac": neo, "parts": dict(zip(o.MENTIONS, (pc(x, neo) for x in (sm, ab, b, tb, tbf)))),
                                            "tb_plus": pc(tb + tbf, neo)} if ok(n, neo) else {"n": n, "neo": neo, "none": True}
    mentions = {}
    for typ, by in men.items():
        if last not in by:
            continue
        now, old = by[last], by.get(first)
        mentions[typ] = {"diplome": typ, "formations": now.get("formations", now.get("n")), "admis_neobac": now.get("admis_neobac", now.get("neo")),
                         "lecture": None if now.get("none") else now,
                         "avant": {"session": first, **({"tb_plus": None} if not old or old.get("none") else old)}}
    return {"filles": fil, "bacs": bac, "mentions": mentions, "first": first}


class Ctx:
    def __init__(self, db: Path, real: bool = False):
        self.db, self.real = db, real
        self.con = duckdb.connect(str(db), read_only=True)
        self.js = (STATIC / "app.js").read_text()
        self.html = (STATIC / "index.html").read_text()
        self.mem = mem_of(self.con)
        self.want = derive(self.mem)
        self.want_p = derive_profils(self.mem)


def node(prog: str, data=None):
    n = shutil.which("node")
    if not n:
        return None
    r = subprocess.run([n, "-e", prog], input=json.dumps(data), capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-600:]}


def block(js: str, start: str, end: str) -> str:
    i = js.index(start)
    return js[i:js.index(end, i)]


def compare(got: dict, want: dict) -> list:
    bad = []
    gt = {t["diplome"]: t["serie"] for t in got["tendances"]}
    if set(gt) != set(want["followed"]):
        bad.append(("followed types", sorted(set(gt) ^ set(want["followed"]))[:3]))
    for t, serie in want["followed"].items():
        if gt.get(t) != serie:
            bad.append(("trend", t))
    if got["sessions"] != want["sessions"] or got["session"] != want["last"]:
        bad.append("sessions")
    if got["demande"] != want["demande"]:
        diff = [(t, k) for t in want["demande"] for k in want["demande"][t] if got["demande"].get(t, {}).get(k) != want["demande"][t][k]]
        bad.append(("demand", diff[:3] or sorted(set(got["demande"]) ^ set(want["demande"]))[:3]))
    if got["ile_de_france"]["demande"] != want["idf"] or got["ile_de_france"]["academies"] != ["paris", "creteil", "versailles"]:
        bad.append("Île-de-France")
    gp = {p["diplome"]: p for p in got["proximite"]}
    if gp != want["prox"]:
        bad.append(("same académie", [t for t in set(gp) | set(want["prox"]) if gp.get(t) != want["prox"].get(t)][:3]))
    if any(p["part_meme_academie"] is not None and not 0 <= p["part_meme_academie"] <= 100 for p in got["proximite"]):
        bad.append("share outside 0-100")
    ga = {a["cle"]: a for a in got["academies"]}
    if set(ga) != want["keys"] or len({a["academie"] for a in got["academies"]}) != len(ga):
        bad.append(("académies listed", sorted(set(ga) ^ want["keys"])[:3]))
    (la0, la1), (lo0, lo1) = M["OBS"].METRO
    for k, a in ga.items():
        p = want["pos"].get(k)
        metro = p is not None and la0 <= p[0] <= la1 and lo0 <= p[1] <= lo1
        if a["metropole"] != metro or (metro and (abs(a["lat"] - p[0]) > 0.001 or abs(a["lon"] - p[1]) > 0.001)) or (not metro and a["lat"] is not None):
            bad.append(("position", k))
    return bad


@check("OB1 trends: vœux / places summed, median official rate, counts; followed = MIN_TYPE formations in every campaign")
def ob1(c: Ctx):
    got = M["OBS"].build(c.con)
    bad = [b for b in compare(got, c.want) if b == "sessions" or (isinstance(b, tuple) and b[0] in ("followed types", "trend"))]
    n = len(got["tendances"])
    return not bad and (n > 0 or not c.real), f"{n} types followed over {got['sessions']}; problems {bad[:3]}"


@check("OB2 demand per académie: folded labels, counts, thresholds, Île-de-France summed, every académie listed, overseas apart")
def ob2(c: Ctx):
    got = M["OBS"].build(c.con)
    bad = [b for b in compare(got, c.want) if b in ("Île-de-France",) or (isinstance(b, tuple) and b[0] in ("demand", "académies listed", "position"))]
    labels = M["OBS"].labels(c.con)
    accent = all(sum(ord(ch) > 127 for ch in lab) >= max(sum(ord(ch) > 127 for ch in raw) for (raw,) in c.con.execute(
        "SELECT DISTINCT acad_mies FROM core.formation_year WHERE acad_mies IS NOT NULL").fetchall() if M["OBS"].fold(raw) == k)
        for k, lab in labels.items())
    if not accent:
        bad.append("an unaccented spelling shown")
    real = ""
    if c.real:
        names = {a["academie"] for a in got["academies"]}
        two = "Besançon" in names and "Besancon" not in names
        real = f"; Besançon one académie {two}"
        if not two:
            bad.append("Besançon split")
    tous = got["demande"].get(got["tous"], {})
    return not bad, f"{len(got['academies'])} académies, {sum(v['voeux_par_place'] is not None for v in tous.values())} with a figure (all types){real}; problems {bad[:3]}"


@check("OB3 same-académie share: SUM(acc_aca_orig) / SUM(acc_neobac) over coherent rows, thresholds, published share agrees")
def ob3(c: Ctx):
    got = M["OBS"].build(c.con)
    bad = [b for b in compare(got, c.want) if b == "share outside 0-100" or (isinstance(b, tuple) and b[0] == "same académie")]
    agree = ""
    if c.real:
        off = c.con.execute("""SELECT count(*) FROM core.formation_year WHERE acc_neobac > 0
            AND abs(100.0 * acc_aca_orig / acc_neobac - pct_aca_orig) > 0.6""").fetchone()[0]
        over = c.con.execute("SELECT count(*) FROM core.formation_year WHERE acc_aca_orig > acc_neobac").fetchone()[0]
        agree = f"; published share disagrees on {off} rows, {over} rows above their néo-bacheliers"
        if off or over:
            bad.append("the published share is not over néo-bacheliers")
    tous = next((p for p in got["proximite"] if p["diplome"] == got["tous"]), None)
    return not bad and tous is not None, f"all formations {tous and tous['part_meme_academie']} %{agree}; problems {bad[:3]}"


def crafted() -> duckdb.DuckDBPyConnection:
    m = duckdb.connect(":memory:")
    m.execute("CREATE SCHEMA core")
    m.execute("""CREATE TABLE core.formation_year (session INT, fili VARCHAR, form_lib_voe_acc VARCHAR, fil_lib_voe_acc VARCHAR,
        lib_for_voe_ins VARCHAR, acad_mies VARCHAR, nb_voe_pp BIGINT, capa_fin BIGINT, taux_acces_ens DOUBLE, acc_neobac BIGINT,
        acc_aca_orig BIGINT, lat DOUBLE, lon DOUBLE)""")
    bts, but = ("BTS", "BTS - Services", "Comptabilité", "BTS - Comptabilité"), ("BUT", "BUT - Service", "Informatique", "BUT - Informatique")
    rows = []
    for s, n in ((2024, 20), (2025, 22)):
        for i in range(n):
            aca = ("Besançon" if s == 2024 else "Besancon") if i < 8 else ("Paris", "Créteil", "Versailles")[i % 3] if i < 14 else "Lyon"
            rows.append((s, *bts, aca, 300 + i, 0 if (s == 2025 and i == 0) else 30, 30.0 if i < 10 else 80.0 + i, 20, 10, 47.2 if i < 8 else 48.8, 6.0 if i < 8 else 2.4))
    for i in range(25):
        rows.append((2025, *but, "Guyane" if i < 6 else "Lyon", 900, 40, None if i == 3 else 40.0, 30, 40 if i == 7 else 15,
                     4.9 if i < 6 else 45.7, -52.3 if i < 6 else 4.8))
    for i in range(5):
        rows.append((2024, *but, "Lyon", 900, 40, 40.0, 30, 15, 45.7, 4.8))
    rows.append((2025, "Licence", "Licence", "Droit", "Licence - Droit", "Mayotte", 100, 20, 80.0, 10, 9, None, None))   # no position
    m.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    for col in COLS[13:]:                       # the profile counts are crafted apart (OB10): NULL here, every row left out
        m.execute(f"ALTER TABLE core.formation_year ADD COLUMN {col} BIGINT")
    return m


@check("OB4 crafted warehouse: two spellings one académie, Île-de-France summed, places 0 and incoherent rows out, overseas apart")
def ob4(c: Ctx):
    m = crafted()
    got, want = M["OBS"].build(m), derive(mem_of(m))
    bad = compare(got, want)
    BTS, BUT = CA.diplome_of("BTS", "BTS - Services", "Comptabilité", "BTS - Comptabilité")[0], CA.diplome_of("BUT", "BUT - Service", "Informatique", "BUT - Informatique")[0]
    ga = {a["cle"]: a for a in got["academies"]}
    d = got["demande"].get(BTS, {})
    facts = {
        "Besançon one académie": ga.get("besancon", {}).get("academie") == "Besançon" and "besancon" in d and len([k for k in ga if "besan" in k]) == 1,
        "places 0 left out": d.get("besancon", {}).get("formations") == 7 and d["besancon"]["voeux_par_place"] == round(sum(300 + i for i in range(1, 8)) / 210, 1),
        "each IdF académie below the threshold": all(d.get(k, {}).get("voeux_par_place") is None for k in ("paris", "creteil", "versailles")),
        "Île-de-France summed": got["ile_de_france"]["demande"].get(BTS) == {"formations": 6, "voeux": sum(300 + i for i in range(8, 14)),
                                                                             "places": 180, "voeux_par_place": round(sum(300 + i for i in range(8, 14)) / 180, 1)},
        "type missing a campaign not followed": [t["diplome"] for t in got["tendances"]] == [BTS],
        "trend": got["tendances"] and got["tendances"][0]["serie"][1]["formations"] == 22 and got["tendances"][0]["serie"][1]["formations_ratio"] == 21,
        "overseas not placed": ga.get("guyane", {}).get("metropole") is False and ga["guyane"]["lat"] is None,
        "incoherent row out": next(p for p in got["proximite"] if p["diplome"] == BUT)["formations"] == 24,
        "académie without a position listed": ga.get("mayotte", {}).get("metropole") is False and ga["mayotte"]["lat"] is None,
        "median rate": got["tendances"] and got["tendances"][0]["serie"][0]["taux_median"] == 60.0,   # skewed: the mean is 60.25
    }
    miss = [k for k, v in facts.items() if not v]
    return not bad and not miss, f"re-derivation problems {bad[:3]}; facts failing {miss}"


def compare_profils(got: dict, want: dict) -> list:
    bad = []
    for key in ("filles", "bacs", "mentions"):
        g = {r["diplome"]: r for r in got[key]}
        if g != want[key]:
            bad.append((key, [t for t in set(g) | set(want[key]) if g.get(t) != want[key].get(t)][:3]))
    if got.get("mentions_avant") != want["first"]:
        bad.append("first campaign")
    for r in got["filles"] + got["bacs"]:
        if any(v is not None and not 0 <= v <= 100 for k, v in r.items() if k.startswith("part_")):
            bad.append(("share outside 0-100", r["diplome"]))
    order = [r["part_general"] for r in got["bacs"] if r["part_general"] is not None]
    if order != sorted(order) or [r["part_admis"] for r in got["filles"] if r["part_admis"] is not None] != sorted(
            [r["part_admis"] for r in got["filles"] if r["part_admis"] is not None], reverse=True):
        bad.append("order")
    return bad


@check("OB9 who the admits are: girls (admits and vœux), bac routes, mentions re-derived in SQL over coherent rows, thresholds")
def ob9(c: Ctx):
    got = M["OBS"].build(c.con)
    bad = compare_profils(got, c.want_p)
    real = ""
    if c.real:
        t = next(r for r in got["mentions"] if r["diplome"] == got["tous"])
        # 2022: 356 rows publish one admit fewer in their mentions than in acc_neobac; they stay in (SIES's own denominator)
        kept = t["avant"]["admis_neobac"] == c.con.execute(f"SELECT sum(acc_neobac) FROM core.formation_year WHERE session = {got['sessions'][0]}").fetchone()[0]
        real = f"; every 2022 row kept in the mentions {kept}"
        if not kept:
            bad.append("2022 rows dropped from the mentions")
    return not bad, f"{len(got['filles'])} / {len(got['bacs'])} / {len(got['mentions'])} types{real}; problems {bad[:3]}"


def crafted_profils() -> duckdb.DuckDBPyConnection:
    m = duckdb.connect(":memory:")
    m.execute("CREATE SCHEMA core")
    m.execute("""CREATE TABLE core.formation_year (session INT, fili VARCHAR, form_lib_voe_acc VARCHAR, fil_lib_voe_acc VARCHAR,
        lib_for_voe_ins VARCHAR, acc_tot BIGINT, acc_tot_f BIGINT, voe_tot BIGINT, voe_tot_f BIGINT, acc_neobac BIGINT, acc_bg BIGINT,
        acc_bt BIGINT, acc_bp BIGINT, acc_sansmention BIGINT, acc_ab BIGINT, acc_b BIGINT, acc_tb BIGINT, acc_tbf BIGINT,
        acc_mention_non_renseignee BIGINT)""")
    bts = ("BTS", "BTS - Services", "Comptabilité", "BTS - Comptabilité")
    rows = []
    for s in (2022, 2025):
        for i in range(8):
            # 2022 row 0: its mentions count one admit fewer than acc_neobac (kept); row 1: one more (left out)
            sm = (10 if i == 0 else 12 if i == 1 else 11) if s == 2022 else 10
            rows.append((s, *bts, 40, 10, 400, 120, 30, 5, 10, 15, sm, 10, 5, 4 if s == 2025 else 3, 1, 0))
    rows += [(2025, *bts, 40, 50, 400, 120, 30, 5, 10, 15, 10, 10, 5, 4, 1, 0),      # more girls than admits: out of the girls
             (2025, *bts, 0, 0, 400, 120, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),              # no admit: out
             (2025, *bts, 40, 10, 400, 120, 30, 5, 10, 16, 10, 10, 5, 4, 1, 0)]       # routes add to 31 != 30: out of the bacs
    for i in range(4):                                                               # 4 formations: under the threshold
        rows.append((2025, "BUT", "BUT - Service", "Informatique", "BUT - Informatique", 100, 30, 900, 200, 80, 40, 38, 2, 20, 30, 20, 8, 2, 0))
    m.executemany("INSERT INTO core.formation_year VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return m


@check("OB10 crafted counts: incoherent girls / routes / mentions rows out, the 2022 one-admit gap kept, thresholds, first campaign")
def ob10(c: Ctx):
    m = crafted_profils()
    got = M["OBS"].profils(m, [2022, 2025])
    BTS = CA.diplome_of("BTS", "BTS - Services", "Comptabilité", "BTS - Comptabilité")[0]
    BUT = CA.diplome_of("BUT", "BUT - Service", "Informatique", "BUT - Informatique")[0]
    f = {r["diplome"]: r for r in got["filles"]}
    b = {r["diplome"]: r for r in got["bacs"]}
    mn = {r["diplome"]: r for r in got["mentions"]}
    facts = {
        "girls: incoherent and zero-admit rows out": f[BTS]["formations"] == 9 and f[BTS]["admis"] == 360 and f[BTS]["part_admis"] == 25.0
        and f[BTS]["part_voeux"] == 30.0,
        "girls: under the threshold": f[BUT]["part_admis"] is None and f[BUT]["admis"] == 400,
        "bacs: routes not adding up out": b[BTS]["formations"] == 9 and b[BTS]["admis_neobac"] == 270 and b[BTS]["part_techno"] == round(100 * 90 / 270, 1),
        "mentions 2022: one fewer kept, one more out": mn[BTS]["avant"]["formations"] == 7 and mn[BTS]["avant"]["admis_neobac"] == 210
        and mn[BTS]["avant"]["tb_plus"] == round(100 * 7 * 4 / 210, 1),
        "mentions 2025 over acc_neobac": mn[BTS]["lecture"]["tb_plus"] == round(100 * 5 / 30, 1) and mn[BTS]["lecture"]["parts"]["sansmention"] == round(100 * 10 / 30, 1),
        "mentions: under the threshold": mn[BUT]["lecture"] is None,
        "first campaign named": got["mentions_avant"] == 2022 and mn[BTS]["avant"]["session"] == 2022,
    }
    miss = [k for k, v in facts.items() if not v]
    return not miss, f"facts failing {miss}"


SAMPLE = {
    "sessions": [2022, 2025], "session": 2025, "tous": "Toutes les formations", "prudence": "Beaucoup de vœux par place ne veut pas dire peu de chances.",
    "seuils": {"type": 20, "academie_formations": 5, "academie_places": 100, "min_neobac": 100, "proximite_formations": 5},
    "tendances": [{"diplome": HOSTILE, "serie": [{"session": 2022, "formations": 30, "voeux_par_place": 10.0, "taux_median": 50.0},
                                                {"session": 2025, "formations": 35, "voeux_par_place": 12.5, "taux_median": 45.0}]}]
    + [{"diplome": f"Type {i}", "serie": [{"session": 2022, "formations": 30, "voeux_par_place": 9.0 - i, "taux_median": 60.0},
                                          {"session": 2025, "formations": 30, "voeux_par_place": 8.0 - i, "taux_median": 61.0}]} for i in range(6)],
    "academies": [{"cle": "x", "academie": HOSTILE, "lat": 45.7, "lon": 4.8, "metropole": True},
                  {"cle": "paris", "academie": "Paris", "lat": 48.8, "lon": 2.4, "metropole": True},
                  {"cle": "creteil", "academie": "Créteil", "lat": 48.8, "lon": 2.5, "metropole": True},
                  {"cle": "versailles", "academie": "Versailles", "lat": 48.8, "lon": 2.2, "metropole": True},
                  {"cle": "lille", "academie": "Lille", "lat": 50.6, "lon": 2.9, "metropole": True},
                  {"cle": "guyane", "academie": "Guyane", "lat": None, "lon": None, "metropole": False}],
    "ile_de_france": {"academies": ["paris", "creteil", "versailles"], "demande": {"BUT": {"formations": 9, "voeux": 4040, "places": 100, "voeux_par_place": 40.4}}},
    "demande": {"BUT": {"x": {"formations": 9, "voeux": 2000, "places": 100, "voeux_par_place": 20.0},
                        "paris": {"formations": 6, "voeux": 2000, "places": 40, "voeux_par_place": 50.0},
                        "creteil": {"formations": 3, "voeux": 1040, "places": 30, "voeux_par_place": None},
                        "versailles": {"formations": 3, "voeux": 1000, "places": 30, "voeux_par_place": None},
                        "lille": {"formations": 2, "voeux": 50, "places": 20, "voeux_par_place": None},
                        "guyane": {"formations": 6, "voeux": 500, "places": 100, "voeux_par_place": 5.0}},
                "Toutes les formations": {"x": {"formations": 9, "voeux": 2000, "places": 100, "voeux_par_place": 20.0}}},
    "proximite": [{"diplome": "Toutes les formations", "formations": 99, "admis_neobac": 1000, "meme_academie": 697, "part_meme_academie": 69.7},
                  {"diplome": HOSTILE, "formations": 40, "admis_neobac": 500, "meme_academie": 410, "part_meme_academie": 82.0},
                  {"diplome": "Petit", "formations": 6, "admis_neobac": 300, "meme_academie": 30, "part_meme_academie": 10.0},
                  {"diplome": "Rare", "formations": 2, "admis_neobac": 50, "meme_academie": 5, "part_meme_academie": None}],
    "mentions_avant": 2022,
    "filles": [{"diplome": "Toutes les formations", "formations": 99, "admis": 1000, "admises": 563, "voeux": 9000, "voeux_filles": 5000, "part_admis": 56.3, "part_voeux": 55.6},
               {"diplome": HOSTILE, "formations": 40, "admis": 500, "admises": 400, "voeux": 900, "voeux_filles": 700, "part_admis": 80.0, "part_voeux": 77.8},
               {"diplome": "Écoles X", "formations": 30, "admis": 500, "admises": 140, "voeux": 900, "voeux_filles": 270, "part_admis": 28.0, "part_voeux": 30.0}]
    + [{"diplome": f"F{i}", "formations": 10 - i, "admis": 200, "admises": 100, "voeux": 900, "voeux_filles": 450, "part_admis": 50.0, "part_voeux": 50.0} for i in range(9)]
    + [{"diplome": "Rare", "formations": 2, "admis": 50, "admises": 10, "voeux": 90, "voeux_filles": 20, "part_admis": None, "part_voeux": None}],
    "bacs": [{"diplome": "Toutes les formations", "formations": 99, "admis_neobac": 1000, "general": 683, "techno": 195, "pro": 122, "part_general": 68.3, "part_techno": 19.5, "part_pro": 12.2},
             {"diplome": HOSTILE, "formations": 40, "admis_neobac": 500, "general": 90, "techno": 185, "pro": 225, "part_general": 18.0, "part_techno": 37.0, "part_pro": 45.0}],
    "mentions": [{"diplome": "Toutes les formations", "formations": 99, "admis_neobac": 1000, "lecture": {"parts": {"sansmention": 30, "ab": 33, "b": 24, "tb": 11, "tbf": 1.3}, "tb_plus": 12.3}, "avant": {"session": 2022, "tb_plus": 12.8}},
                 {"diplome": HOSTILE, "formations": 40, "admis_neobac": 500, "lecture": {"parts": {"sansmention": 3, "ab": 14, "b": 35, "tb": 39, "tbf": 9}, "tb_plus": 48.0}, "avant": {"session": 2022, "tb_plus": 52.4}},
                 {"diplome": "Nouveau", "formations": 9, "admis_neobac": 139, "lecture": {"parts": {"sansmention": 53, "ab": 39, "b": 7, "tb": 1, "tbf": 0}, "tb_plus": 1.0}, "avant": {"session": 2022, "tb_plus": None}}],
}


def page(c: Ctx, data):
    helpers = "\n".join(ln for ln in c.js.splitlines() if ln.startswith(("const esc = ", "const fmt = ", "const pct = ", "const lineLegend = ")))
    svg = block(c.js, "const COLORS = [", "function stackedBars(")
    view = block(c.js, "// ---- Observatoire (owner, 2026-11-19)", "// the selectivity matrix:")
    prog = helpers + "\n" + svg + "\n" + view + """
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
global.location = { hash: "#/observatoire" };
const $view = { innerHTML: "", dataset: {}, querySelectorAll: () => [], querySelector: () => null };
global.document = { getElementById: () => null };
const api = async () => data;
const nextSteps = (k) => `<section data-next="${k}"></section>`;
(async () => {
  await viewObservatoire();
  obsUI.type = "BUT";
  const dem = obsDemande(data);
  process.stdout.write(JSON.stringify({ html: $view.innerHTML, dem, rendered: $view.dataset.rendered, max: OBS_MAX, series: OBS_SERIES, defaults: obsUI.types }));
})().catch((e) => { process.stderr.write(String(e.stack)); process.exit(1); });"""
    return node(prog, data)


@check("OB5 page (Node, hostile data): escaped, labelled cells, caveats, thresholds said, one Île-de-France bubble, overseas apart")
def ob5(c: Ctx):
    o = page(c, SAMPLE)
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    h, dem = o["html"], o["dem"]
    raw = "<img" in h or "<img" in dem
    cells = re.findall(r'<td class="num"([^>]*)>', h + dem)
    unlabelled = [x for x in cells if "data-label" not in x]
    caveat = "Ce ne sont pas vos chances" in h and "Ce sont des vœux, pas des personnes" in h and "admis néo-bacheliers" in h \
        and "Elle n'est pas publiée pour les autres admis" in h and SAMPLE["prudence"] in h
    under = dem.count("trop peu de formations") >= 3
    bubbles = re.findall(r"<circle [^>]*><title>([^<]*)</title>", dem)
    idf = sum("Île-de-France" in b for b in bubbles) == 1 and not any(re.match(r"(Paris|Créteil|Versailles) :", b) for b in bubbles)
    apart = "Pas sur la carte (outre-mer, étranger) : Guyane 5" in dem and not any(b.startswith("Guyane") for b in bubbles)
    named = 'role="img" aria-label="Carte des académies de métropole' in dem and 'role="img" aria-label="Graphique' in h
    shades = all(col not in ("var(--c5)", "var(--c6)") for col, _ in o["series"]) and len({tuple(x) for x in o["series"]}) == len(o["series"])
    count = len(o["defaults"]) <= o["max"] == len(o["series"])
    sec = h[h.index('id="obs-p"'):h.index('id="obs-f"')] if 'id="obs-f"' in h else h[h.index('id="obs-p"'):]
    small = "Les types de moins de 20 formations (1)" in sec and sec.count("<li><span class=\"obs-lab\">") == 2
    range_ = "De <strong>5</strong> vœux par place (Guyane) à <strong>50</strong> (Paris)" in dem
    ok = not raw and not unlabelled and caveat and under and idf and apart and named and shades and count and small and o["rendered"] == "observatoire" and range_
    return ok, (f"raw tag {raw}; unlabelled cells {len(unlabelled)}; caveats {caveat}; under threshold said {under}; one IdF bubble {idf}; "
                f"overseas apart {apart}; named {named}; chart shades {shades}; series cap {count}; small types folded {small}; range {range_}")


@check("OB11 page sections (Node): girls, bac routes, mentions escaped, sorted as served, 10 shown, routes named, caveats, gap computed")
def ob11(c: Ctx):
    o = page(c, SAMPLE)
    if o is None:
        return True, "node not installed"
    if "error" in o:
        return False, o["error"]
    h = o["html"]
    f, b, mn = (h[h.index(f'id="obs-{k}"'):] for k in ("f", "b", "m"))
    f, b = f[:f.index("</section>")], b[:b.index("</section>")]
    mn = mn[:mn.index("</section>")]
    raw = "<img" in f + b + mn
    girls = ("Les filles font <strong>56,3 %</strong> des admis (563 sur 1 000)" in f.replace("\u202f", " ")
             and f.count('<li><span class="obs-lab">') == 11 and "Les autres types de formation (1)" in f
             and "à 2,2 points au plus" in f and "vœux 77,8 %" in f and "des vœux, pas des personnes" in f)
    routes = (all(f'<i style="background:var(--voie-{v})"></i>bac {n}' in b for v, n in (("bg", "général"), ("bt", "techno"), ("bp", "pro")))
              and "« rare », jamais « fermé »" in b and "Admis néo-bacheliers seulement" in b and "<strong>37 % · 45 %</strong>" in b
              and "bac général 18 %" in b)
    ments = ("<strong>12,3 %</strong> des admis néo-bacheliers" in mn and "(12,8 % en 2022)" in mn and "<strong>52,4 % → 48 %</strong>" in mn
             and "<strong>1 %</strong>" in mn and "ni le niveau demandé ni vos chances" in mn and "pas publiées par série de bac" in mn)
    hero = "Six regards" in h
    ok = not raw and girls and routes and ments and hero
    return ok, f"raw tag {raw}; girls {girls}; routes named and caveat {routes}; mentions {ments}; hero {hero}"


@check("OB6 wording: no chance, probability or promise; vouvoiement")
def ob6(c: Ctx):
    view = block(c.js, "// ---- Observatoire (owner, 2026-11-19)", "// the selectivity matrix:")
    texts = re.findall(r"`[^`]*`|\"[^\"]*\"", view) + [OBS.TE.PRUDENCE]
    chance = [t[:60] for t in texts if CHANCE.search(t)]
    tu = [t[:60] for t in texts if FORMAL.search(re.sub(r"\$\{[^}]*\}", "", t))]
    no_formation = "#/f/" not in view
    return not chance and not tu and no_formation, f"chance wording {chance[:2]}; tutoiement {tu[:2]}; no formation listed or ranked {no_formation}"


@check("OB7 wiring: route, menus, TAB_OF, ROUTE_NAME, shared cache, analytics, release guard, feature")
def ob7(c: Ctx):
    from suptracker import analytics, cache
    api_src = (ROOT / "suptracker" / "api.py").read_text()
    route = 'if (a === "observatoire") return await viewObservatoire();' in c.js
    menus = c.html.count('<a href="#/observatoire" data-tab="observatoire">Observatoire</a>') == 2
    tabs = 'observatoire: "observatoire"' in block(c.js, "const TAB_OF = {", "};") and 'observatoire: "observatoire"' in block(c.js, "const ROUTE_NAME = {", "};") \
        and '"observatoire"' in block(c.js, "const COMP_TABS = [", "];")
    pol = cache.policy("/api/observatoire")
    shared = bool(pol) and pol[0] == cache.PUBLIC
    no_param = re.search(r'@app\.get\("/api/observatoire"\)\ndef observatoire\(\):', api_src) is not None
    an = "observatoire" in analytics.ROUTES
    rel = '"observatoire": ("app.js", "async function viewObservatoire(")' in (ROOT / "tests" / "test_release.py").read_text()
    feat = re.search(r'^FEATURES = \[[^\]]*"observatoire"[,\]]', api_src, re.M) is not None
    nxt = "observatoire: [" in block(c.js, "const NEXT_STEPS = {", "\n};")
    ok = route and menus and tabs and shared and no_param and an and rel and feat and nxt
    return ok, f"route {route}; menus {menus}; tabs {tabs}; shared cache {shared}; no parameter {no_param}; analytics {an}; release {rel}; feature {feat}; next steps {nxt}"


PY_MUTANTS = [
    ("girls more than admits kept", "if tot and f is not None and 0 <= f <= tot and voe and voef is not None and 0 <= voef <= voe:",
     "if tot and f is not None and voe and voef is not None:"),
    ("routes not adding up kept", "if neo and None not in (bg, bt, bp) and bg + bt + bp == neo:", "if neo and None not in (bg, bt, bp):"),
    ("2022 one-admit gap dropped", "sum(m5) + (nr or 0) <= neo:", "sum(m5) + (nr or 0) == neo:"),
    ("mentions over their own sum", 'parts = {m: _part(x[m], x["neo"]) for m in MENTIONS}', 'parts = {m: _part(x[m], sum(x[k] for k in MENTIONS)) for m in MENTIONS}'),
    ("TB without félicitations", '"tb_plus": _part(x["tb"] + x["tbf"], x["neo"])', '"tb_plus": _part(x["tb"], x["neo"])'),
    ("girls among vœux = among admits", '"part_voeux": _part(x["voeux_filles"], x["voeux"])', '"part_voeux": _part(x["admises"], x["admis"])'),
    ("profiles threshold dropped", '        return total >= MIN_NEOBAC and x["n"] >= MIN_PROX_FORMATIONS', '        return total > 0'),
    ("before = latest campaign", '"avant": {"session": first, **(reading(by.get(first)) or {"tb_plus": None})}', '"avant": {"session": first, **(reading(by.get(last)) or {"tb_plus": None})}'),
    ("mean of ratios instead of summed counts", 't["voeux"] += voe\n', 't["voeux"] += voe * 1.1\n'),
    ("places 0 kept", "usable = voe is not None and capa is not None and capa > 0", "usable = voe is not None and capa is not None"),
    ("mean instead of median", 'round(median(x["taux"]), 1)', 'round(sum(x["taux"]) / len(x["taux"]), 1)'),
    ("type missing a campaign followed", 'if any(by.get(s, {}).get("n", 0) < MIN_TYPE for s in sessions):', "if False:"),
    ("académie threshold dropped", 'enough = d["n"] >= MIN_ACAD_FORMATIONS and d["places"] >= MIN_ACAD_PLACES', "enough = True"),
    ("labels not folded", '    s = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode().lower()\n', '    s = (label or "").lower()\n'),
    ("unaccented label shown", "cand = (_accents(lab), ses, lab)", "cand = (0, ses, lab)"),
    ("one IdF académie only", 'parts = [by[k] for k in IDF if k in by]', 'parts = [by[k] for k in IDF[:1] if k in by]'),
    ("share over all rows", "if neo and aca is not None and 0 <= aca <= neo:", "if neo and aca is not None:"),
    ("share threshold dropped", 'if x["neobac"] >= MIN_NEOBAC and x["n"] >= MIN_PROX_FORMATIONS else None', "if x[\"neobac\"] else None"),
    ("overseas placed", "metro = p is not None and METRO[0][0] <= la <= METRO[0][1] and METRO[1][0] <= lo <= METRO[1][1]", "metro = p is not None"),
    ("académie without a position dropped", "for k in sorted(set(pos) | set(dem.get(TOUS, {})), key=lambda k: CA.sort_key(lab[k])):",
     "for k in sorted(set(pos), key=lambda k: CA.sort_key(lab[k])):"),
    ("earlier campaign mixed into the académies", "        if ses != last:\n            continue\n", ""),
]
JS_MUTANTS = [
    ("girls type unescaped", '`<li><span class="obs-lab">${esc(r.diplome)}</span><span class="obs-dumb"', '`<li><span class="obs-lab">${r.diplome}</span><span class="obs-dumb"'),
    ("route colour without its name", '<i style="background:var(--voie-bt)"></i>bac techno', '<i style="background:var(--voie-bt)"></i>'),
    ("rare caveat dropped", "Une part faible veut dire « rare », jamais « fermé ».", ""),
    ("mention caveat dropped", "ni le niveau demandé ni vos chances", "voilà"),
    ("vœux called girls", "des vœux, pas des personnes. Calcul", "des filles. Calcul"),
    ("all types shown", "const OBS_SHOWN = 10;", "const OBS_SHOWN = 99;"),
    ("gap hard-coded", "est à ${fmt(gap, 1)} points au plus", "est à 5 points au plus"),
    ("félicitations left out of the before figure", '`${pct(r.avant.tb_plus)} → `}${pct(r.lecture.tb_plus)}', '`${pct(r.avant.tb_plus)} → `}${pct(r.lecture.parts.tb)}'),
    ("académie unescaped", '<td data-label="Académie">${esc(r.a.academie)}</td>', '<td data-label="Académie">${r.a.academie}</td>'),
    ("type label unescaped", '<span class="obs-lab">${esc(p.diplome)}</span>', '<span class="obs-lab">${p.diplome}</span>'),
    ("figure without its label", '<td class="num" data-label="Vœux par place">${r.x.voeux_par_place', '<td class="num">${r.x.voeux_par_place'),
    ("chance caveat dropped", "Ce ne sont pas vos chances.", "Voici les chiffres."),
    ("vœux called people", "Ce sont des vœux, pas des personnes.", "Ce sont des candidats."),
    ("threshold not said", '"trop peu de formations" : fmt(r.x.voeux_par_place, 1)', '"—" : fmt(r.x.voeux_par_place, 1)'),
    ("Île-de-France drawn three times", "!idf.academies.includes(a.cle) && dem[a.cle]", "dem[a.cle]"),
    ("overseas not listed", "const apart = d.academies.filter((a) => !a.metropole && dem[a.cle]);", "const apart = [];"),
    ("light shade on the chart", '["var(--c4)", "8 3 2 3"]', '["var(--c6)", "8 3 2 3"]'),
    ("no series cap", "const OBS_MAX = 5;", "const OBS_MAX = 9;"),
    ("map unnamed", 'role="img" aria-label="Carte des académies de métropole', 'role="img" data-x="Carte'),
    ("néo-bachelier caveat dropped", "Elle n'est pas publiée pour les autres admis.", ""),
    ("menu entry dropped", '<a href="#/observatoire" data-tab="observatoire">Observatoire</a>', ""),
    ("chance wording", "Ces chiffres décrivent les années passées", "Vos chances d'être admis, d'après les années passées"),
]


def mutated(old: str, new: str):
    path = ROOT / "suptracker" / "observatoire.py"
    src = path.read_text()
    if old not in src:
        return None
    m = types.ModuleType("suptracker._mut_obs")
    m.__package__, m.__file__ = "suptracker", str(path)
    sys.modules["suptracker._mut_obs"] = m
    exec(compile(src.replace(old, new, 1), str(path), "exec"), m.__dict__)
    return m


@check("OB8 mutation test: aggregation, threshold, folding, Île-de-France, escaping, wording and wiring bugs are each caught")
def ob8(c: Ctx):
    fns = [ob1, ob2, ob3, ob4, ob5, ob6, ob7, ob9, ob10, ob11]
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
        saved, M["OBS"] = M["OBS"], m
        try:
            if not caught():
                missed.append(name)
        finally:
            M["OBS"] = saved
            sys.modules.pop("suptracker._mut_obs", None)
    for name, old, new in JS_MUTANTS:
        target = "html" if "data-tab" in old else "js"
        src = getattr(c, target)
        if old not in src:
            missed.append(f"{name} (anchor gone)"); continue
        setattr(c, target, src.replace(old, new, 1))
        try:
            if not caught():
                missed.append(name)
        finally:
            setattr(c, target, src)
    n = len(PY_MUTANTS) + len(JS_MUTANTS)
    return not missed, f"{n - len(missed)}/{n} mutants caught by a failing check" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False) -> list[dict]:
    c = Ctx(db, real)
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
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + r["detail"])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
