"""Étudier là-bas : what a year of study costs, on site and for the formation (sprint V1, owner 2026-11-15).

Owner's request: the monthly cost on site (housing, food, transport and every other running cost) and the annual cost of
the formation. His choices (2026-11-15): a monthly TOTAL as a range, line by line with each line's source and whether it is
local or national, labelled "estimation"; the rent of a 20 m² studio.

Sources and rules:
  * Rent (LOCAL): "Carte des loyers" 2025 (Ministère de la Transition écologique), 1-2 room flats, asking rent per m²
    CHARGES INCLUDED, per commune, with its published prediction interval. Rent = STUDIO_M2 x the interval's bounds (the
    central value said beside). Linked by the formation's town and department (folded names); a commune predicted from its
    zone ("maille", few listings of its own) is flagged. No town match = no rent and no total, never a neighbour's.
  * Crous residences (LOCAL): the Crous register (SIES portal), within RAYON_CROUS_KM of the formation, nearest first; the
    rent only when the residence's own text prints amounts in euros (as written, with the Crous' date when printed); a
    residence whose text says it is closed is left out. The Crous restaurants within RAYON_RESTO_KM are counted.
  * Everything else (NATIONAL): the Observatoire national de la vie étudiante, survey "Conditions de vie des étudiants
    2023" (brochure "Repères", p. 27): monthly means per item, among the students concerned. They are not this town's
    prices: the page says so. Fixed rule: POSTES_COURANTS enter both bounds of the total; POSTES_SELON (housing costs
    beyond the rent, health insurance, study costs, leisure) only the upper bound. The rent and child care items of the
    survey are never used (the local rent replaces the first; the second concerns 1 % of students).
  * The meal at the university restaurant (Crous): REPAS_RU, the national price, said with its date.
  * Formation (ANNUAL): the tuition fees VERBATIM from the formation's live Parcoursup fiche (data/fiches/frais.csv); an
    amount is read only when the text is a plain sum of euro amounts ("178 euros + 800 euros de frais spécifiques" = 978;
    "Aucun frais" = 0); anything else ("Identique au candidat non boursier, mais remboursement...", an amount mixed with the
    CVEC) shows the text only. The CVEC (CVEC) is national: its amount for the year, said when the fiche prints the CVEC
    paragraph.
  * The year: 10 months on site (an academic year) x the monthly bounds + the tuition read + the CVEC. Only when every part
    is known; always "estimation".
  * Never a budget to plan for a given family, never a promise: ranges, sources and dates; grants and housing aid lower
    the bill (links, not computed).
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from .reconnaissance import fold

SOURCES_DIR = Path(__file__).resolve().parents[1] / "data" / "sources"
OVE_CSV = SOURCES_DIR / "ove_cdv2023_depenses.csv"
FICHES = Path(__file__).resolve().parents[1] / "data" / "fiches"

STUDIO_M2 = 20
RAYON_CROUS_KM = 10
RAYON_RESTO_KM = 2
MOIS_PAR_AN = 10
POSTES_COURANTS = ("Frais de vie quotidienne", "Frais de transport", "Frais de restauration universitaire",
                   "Communication (Internet, téléphone, etc.)")
POSTES_SELON = ("Frais liés au logement", "Mutuelle", "Frais liés aux études (hors frais d'inscription)",
                "Frais liés aux activités sociales et de loisirs")
NOMS = {"Frais de vie quotidienne": "Courses et vie quotidienne", "Frais de transport": "Transports",
        "Frais de restauration universitaire": "Repas au restaurant universitaire",
        "Communication (Internet, téléphone, etc.)": "Téléphone et internet",
        "Frais liés au logement": "Énergie, assurance et autres frais du logement", "Mutuelle": "Mutuelle santé",
        "Frais liés aux études (hors frais d'inscription)": "Fournitures et matériel d'études",
        "Frais liés aux activités sociales et de loisirs": "Sorties et loisirs"}
REPAS_RU = {"prix": 1.0, "depuis": "4 mai 2026", "texte": "Repas au restaurant universitaire du Crous : 1 € pour tous les étudiants depuis le 4 mai 2026.",
            "url": "https://www.etudiant.gouv.fr/fr/se-restaurer"}
CVEC = {"montant": 105, "annee": "2026-2027", "url": "https://cvec.etudiant.gouv.fr/",
        "texte": "La CVEC (contribution vie étudiante et de campus) : 105 € en 2026-2027, une fois par an ; les boursiers en sont exonérés."}
OVE = {"titre": "Observatoire national de la vie étudiante, enquête Conditions de vie des étudiants 2023 (Repères, p. 27)",
       "url": "https://www.ove-national.education.fr/enquete/enquete-conditions-de-vie-des-etudiants-2023/"}
LOYERS = {"titre": "Carte des loyers 2025, appartements d'une ou deux pièces, charges comprises (Ministère de la Transition écologique)",
          "url": "https://www.data.gouv.fr/datasets/carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025"}
EURO = r"(\d{1,3}(?:[\s \xa0.]\d{3})+|\d+)(?:[,.](\d{1,2}))?\s*(?:€|euros?\b)"


def _num(x) -> float | None:
    try:
        return float(str(x).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def montant_annuel(texte: str | None) -> int | None:
    """The yearly amount a fee line states when it is a PLAIN sum of euro amounts, else None (the text is shown alone).
    "Aucun frais" / "Gratuit" / "0" = 0. The year in "(Montant pour 2025/2026)" and a trailing "par an" are not amounts;
    a text naming the CVEC is never summed (the CVEC is shown apart)."""
    t = re.sub(r"\s+", " ", (texte or "")).strip()
    if not t:
        return None
    f = fold(t)
    if re.fullmatch(r"(aucun frais|gratuit|gratuite|0|0 ?(€|euros?))[ .]*(\(montant pour 20\d\d/20\d\d\))?\.?", f) \
            or re.fullmatch(r"aucun frais (?:les )?frais (?:sont )?a la charge de l employeur\.?", f):
        return 0
    if "cvec" in f:
        return None
    t2 = re.sub(r"\(montant pour 20\d\d/20\d\d\)", "", t, flags=re.I)
    t2 = re.sub(r"\b(par an|par année|annuels?|/ ?an)\b", "", t2, flags=re.I).strip(" .")
    # "1 415 € - Possibilité de régler en plusieurs fois sans frais": a comment without any figure after a dash
    m = re.fullmatch(r"(.*?\d.*?)\s+-\s+([^\d+]*)", t2)
    if m:
        t2 = m.group(1).strip(" .")
    # a bare number ("777") on a line headed "Par année" is an amount in euros (the fiche's note: "sauf indication
    # contraire les sommes indiquées sont en euros")
    if re.fullmatch(r"\d{1,3}(?:[\s \xa0.]\d{3})*|\d+", t2):
        return int(re.sub(r"\D", "", t2))
    terms = re.split(r"\s*\+\s*", t2)
    cents = 0
    for term in terms:
        m = re.fullmatch(EURO + r"(?:\s+de frais [a-zéèêàç ]+)?", term.strip(" ."), flags=re.I)
        if not m:
            return None
        # "2329,79 €" is 2,329.79 euros (never 2,329 nor 232,979): the cents are kept, the sum rounded to the euro, half up
        cents += int(re.sub(r"\D", "", m.group(1))) * 100 + int((m.group(2) or "0").ljust(2, "0"))
    return (cents + 50) // 100


def _fees(src: Path) -> dict:
    """{code: {"titre", "lignes": [(rubrique, texte)], "cvec": bool}} from the harvest (texts by id)."""
    from .grilles import read_texts
    rows = list(csv.DictReader(open(src / "frais.csv", encoding="utf-8"))) if (src / "frais.csv").exists() else []
    texts = read_texts(src / "textes.csv.gz") if rows else {}
    out: dict = {}
    for r in sorted(rows, key=lambda r: (r["cod_aff_form"], int(r["rang"] or 0))):
        d = out.setdefault(r["cod_aff_form"], {"titre": r["titre"], "lignes": [], "cvec": False})
        if "CVEC" in r["rubrique"] or "Contribution Vie Etudiante" in r["rubrique"]:
            d["cvec"] = True
            continue
        d["lignes"].append((r["rubrique"], texts.get(r["texte_id"]) or ""))
    return out


def _postes(path: Path = OVE_CSV) -> list[dict]:
    if not path.exists():
        return []
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    return [{"poste": r["poste"], "montant": int(r["montant"]), "part": int(r["part_concernes"])} for r in rows]


def build(con, raw_dir: Path, fiches: Path | None = FICHES, ove: Path = OVE_CSV) -> dict:
    """core.vie_loyer (commune rents), core.vie_crous (residences), core.vie_resto (restaurants), core.vie_poste (national
    items), core.vie_frais (fee lines per formation, verbatim, with the amount read). Returns counts for the audit."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.vie_loyer (insee VARCHAR, commune VARCHAR, dep VARCHAR, cle VARCHAR, m2 DOUBLE,
        bas DOUBLE, haut DOUBLE, maille BOOLEAN, nbobs INTEGER)""")
    con.execute("""CREATE OR REPLACE TABLE core.vie_crous (nom VARCHAR, zone VARCHAR, lat DOUBLE, lon DOUBLE, loyer_min DOUBLE,
        loyer_max DOUBLE, loyer_date VARCHAR, url VARCHAR, extrait VARCHAR)""")
    con.execute("CREATE OR REPLACE TABLE core.vie_resto (nom VARCHAR, lat DOUBLE, lon DOUBLE)")
    con.execute("CREATE OR REPLACE TABLE core.vie_poste (poste VARCHAR, montant INTEGER, part INTEGER, inclus VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.vie_frais (cod_aff_form VARCHAR, titre VARCHAR, rang INTEGER, rubrique VARCHAR,
        texte VARCHAR, montant INTEGER, cvec BOOLEAN)""")
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute("CREATE OR REPLACE TABLE meta.vie_audit (dataset VARCHAR, colonnes VARCHAR, lignes INTEGER, gardees INTEGER, champs VARCHAR)")
    got = {"loyers": 0, "crous": 0, "resto": 0, "postes": 0, "frais": 0}
    # rents
    p = raw_dir / "loyers_app12_2025.parquet"
    if p.exists():
        cols = [c for (c,) in con.execute(f"SELECT name FROM parquet_schema('{p}')").fetchall()]
        need = {"INSEE_C", "LIBGEO", "DEP", "loypredm2", "lwr.IPm2", "upr.IPm2", "TYPPRED"}
        if need <= set(cols):
            rows = con.execute(f"""SELECT "INSEE_C", "LIBGEO", "DEP", "loypredm2", "lwr.IPm2", "upr.IPm2", "TYPPRED",
                {'"nbobs_com"' if 'nbobs_com' in cols else 'NULL'} FROM read_parquet('{p}')""").fetchall()
            out = []
            for insee, lib, dep, m2, lo, hi, typ, nb in rows:
                m2, lo, hi = _num(m2), _num(lo), _num(hi)
                if not lib or m2 is None or lo is None or hi is None or not (lo <= m2 <= hi):
                    continue
                dep = str(dep or "").strip()
                out.append((insee, lib, dep, f"{fold(lib)}|{dep}", m2, lo, hi, (typ or "").strip().lower() != "commune",
                            int(_num(nb)) if _num(nb) is not None else None))
            con.executemany("INSERT INTO core.vie_loyer VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", out)
            got["loyers"] = len(out)
    # Crous residences and restaurants
    for key, table in (("crous_logement", "vie_crous"), ("crous_restauration", "vie_resto")):
        p = raw_dir / f"{key}.parquet"
        if not p.exists():
            continue
        df = con.execute(f"SELECT * FROM read_parquet('{p}')").df()
        cols = {fold(c).replace(" ", "_"): c for c in df.columns}

        def pick(*names, contains: tuple = ()):
            """An exact field name first, else the first field whose name contains one of `contains` (the portal's
            parquet export names its fields itself: checked on the real file through meta.vie_audit)."""
            hit = next((cols[n] for n in names if n in cols), None)
            return hit or next((c for k, c in cols.items() for w in contains if w in k), None)
        c_nom = pick("title", "nom", "name", contains=("title", "nom"))
        c_geo = pick("geolocalisation", "geocalisation", "geo_point", "geo_point_2d", "geo", "localisation",
                     contains=("geo", "locali", "coord"))
        c_txt = [c for c in (pick("infos", "adresse"), pick("short_desc", "description"), pick("zone")) if c]
        c_url = pick("bookingurl", "booking_url", "interneturl", "internet_url")
        rows = []
        for _i, r in df.iterrows():
            lat, lon = _latlon(r[c_geo]) if c_geo else (None, None)
            if lat is None or not c_nom:
                continue
            if table == "vie_resto":
                rows.append((str(r[c_nom]).strip(), lat, lon))
                continue
            text = " ".join(str(r[c]) for c in c_txt if r[c] is not None)
            if re.search(r"fermeture definitive|ferme definitivement|definitivement ferme", fold(text)):
                continue
            amounts, extrait = crous_loyers(text)
            d = re.search(r"\bau (\d{2}/\d{2}/\d{2,4})", text)
            zone = str(r[pick("zone")]).strip() if pick("zone") else None
            url = str(r[c_url]).strip() if c_url and r[c_url] is not None else ""
            rows.append((str(r[c_nom]).strip(), zone, lat, lon, min(amounts) if amounts else None,
                         max(amounts) if amounts else None, d.group(1) if (d and amounts) else None,
                         url if url.startswith("https://") else None, extrait))
        if rows:
            ph = ", ".join("?" * len(rows[0]))
            con.executemany(f"INSERT INTO core.{table} VALUES ({ph})", rows)
        got["crous" if table == "vie_crous" else "resto"] = len(rows)
        ex = next((repr(v)[:120] for v in (df[c_geo] if c_geo else []) if v is not None), None)
        con.execute("INSERT INTO meta.vie_audit VALUES (?, ?, ?, ?, ?)",
                    [key, " | ".join(map(str, df.columns))[:2000], len(df), len(rows), f"nom={c_nom} geo={c_geo} exemple={ex}"])
    # national items
    for x in _postes(ove):
        inclus = "toujours" if x["poste"] in POSTES_COURANTS else "selon" if x["poste"] in POSTES_SELON else None
        if inclus:
            con.execute("INSERT INTO core.vie_poste VALUES (?, ?, ?, ?)", [x["poste"], x["montant"], x["part"], inclus])
            got["postes"] += 1
    # tuition fees, verbatim
    if fiches is not None:
        fees = _fees(fiches)
        rows = []
        for cod, d in fees.items():
            if not d["lignes"]:
                rows.append((cod, d["titre"], 0, None, None, None, d["cvec"]))
            for i, (rub, txt) in enumerate(d["lignes"]):
                amount = montant_annuel(txt) if rub.strip().lower() == "par année" else None
                rows.append((cod, d["titre"], i + 1, rub, txt, amount, d["cvec"]))
        if rows:
            con.executemany("INSERT INTO core.vie_frais VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        got["frais"] = len(fees)
    return got


LOYER_MOTS = r"loyer|redevance|chambre|studio|\bt ?[1-5]\b|\bt1 ?bis\b|logement|appartement|colocation|\bm2\b|\bm²|studette|duplex"
# "hors ALS / APL" qualifies a rent (housing aid not deducted): it never excludes a segment
HORS_LOYER = r"depot|caution|garantie|avance|frais de dossier|frais d inscription|cvec|parking|garage|laverie|repas|ticket|internet|forfait"


def crous_loyers(text: str) -> tuple[list[float], str | None]:
    """The rents a residence's text prints: euro amounts (80 to 1,500 €) found only in a segment (a line or a sentence) that
    speaks of a rent or a room AND not of a deposit, a guarantee, fees, parking, laundry or meals (a 100 € deposit
    is not a rent). Returns the amounts and the first such segment (kept for the audit)."""
    out, extrait = [], None
    for seg in re.split(r"[\n;]|(?<=[.!?])\s+(?=[A-ZÉÈ(])", text or ""):
        f = fold(seg)
        if not re.search(LOYER_MOTS, f) or re.search(HORS_LOYER, f):
            continue
        vals = [a for a in (_num(m.group(1).replace(" ", "").replace("\u202f", "").replace("\xa0", "").replace(".", "")
                                 + ("." + m.group(2) if m.group(2) else ""))
                            # an amount glued to a letter ("= T1468,86 €" is "T1" then "468,86 €") is not read
                            for m in re.finditer(r"(?<![\w,.])" + EURO, seg, flags=re.I)) if a is not None and 80 <= a <= 1500]
        if vals:
            out += vals
            extrait = extrait or re.sub(r"\s+", " ", seg).strip()[:200]
    return out, extrait


def _latlon(v) -> tuple[float | None, float | None]:
    """A geo point as the portals export it: "lat, lon" text, a [lat, lon] list or a {lat, lon} dict."""
    if v is None:
        return None, None
    if isinstance(v, (bytes, bytearray, memoryview)):
        # the SIES portal's parquet export writes geo points as WKB: byte order, type 1 (point), then x = lon, y = lat
        import struct
        b = bytes(v)
        if len(b) >= 21 and b[0] in (0, 1):
            e = "<" if b[0] == 1 else ">"
            if struct.unpack(e + "I", b[1:5])[0] == 1:
                lon, lat = struct.unpack(e + "dd", b[5:21])
                return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else (None, None)
        return None, None
    m = re.match(r"\s*POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", str(v), re.I)
    if m:                                                                   # WKT: lon then lat
        return float(m.group(2)), float(m.group(1))
    if isinstance(v, dict):
        return _num(v.get("lat")), _num(v.get("lon"))
    if not isinstance(v, (str, bytes)) and hasattr(v, "__len__") and len(v) == 2:     # a list, tuple or numpy array
        return _num(v[0]), _num(v[1])
    m = re.match(r"\s*\[?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", str(v))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def km(lat1, lon1, lat2, lon2) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'core' AND table_name = ?", [table]).fetchone()[0])


def _arrondi(x: float, pas: int = 10) -> int:
    return int(round(x / pas) * pas)


def for_formation(con, cod: str) -> dict | None:
    """The cost card of one formation (latest campaign's place). None when nothing is known."""
    if not _has(con, "vie_loyer"):
        return None
    f = con.execute("""SELECT ville_etab, dep, lat, lon FROM core.formation_year WHERE cod_aff_form = ?
        ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    if not f:
        return None
    ville, dep, lat, lon = f
    lat, lon = (float(lat), float(lon)) if lat is not None and lon is not None else (None, None)
    out = {"commune": ville, "loyer": None, "crous": [], "crous_n": 0, "resto_n": None, "postes": [], "mensuel": None,
           "frais": None, "annuel": None, "crous_loyers": None, "studio_m2": STUDIO_M2, "mois": MOIS_PAR_AN, "repas_ru": REPAS_RU, "cvec": CVEC,
           "sources": {"loyers": LOYERS, "ove": OVE}}
    nom = re.sub(r"\s+", " ", ville or "")
    key = f"{fold(nom)}|{str(dep or '').strip()}"
    lo = con.execute("SELECT commune, m2, bas, haut, maille, nbobs FROM core.vie_loyer WHERE cle = ? LIMIT 1", [key]).fetchone()
    if lo:
        com, m2, bas, haut, maille, nb = lo
        out["loyer"] = {"commune": com, "m2": round(m2, 1), "bas_m2": round(bas, 1), "haut_m2": round(haut, 1),
                        "min": _arrondi(bas * STUDIO_M2), "max": _arrondi(haut * STUDIO_M2), "central": _arrondi(m2 * STUDIO_M2),
                        "maille": bool(maille), "nbobs": nb}
    if lat is not None and lon is not None:
        res = []
        for nom, zone, la, lo2, lmin, lmax, ldate, url in con.execute(
                "SELECT nom, zone, lat, lon, loyer_min, loyer_max, loyer_date, url FROM core.vie_crous").fetchall():
            d = km(lat, lon, la, lo2)
            if d <= RAYON_CROUS_KM:
                res.append({"nom": nom, "zone": zone, "km": round(d, 1), "loyer_min": lmin, "loyer_max": lmax,
                            "loyer_date": ldate, "url": url})                   # https only, kept so at build
        res.sort(key=lambda x: (x["km"], x["nom"]))
        out["crous"], out["crous_n"] = res[:5], len(res)
        priced = [x for x in res if x["loyer_min"] is not None]
        if priced:                                     # every residence of the radius, not only the five listed
            out["crous_loyers"] = {"min": min(x["loyer_min"] for x in priced), "max": max(x["loyer_max"] for x in priced),
                                   "n": len(priced)}
        if _has(con, "vie_resto"):
            out["resto_n"] = sum(1 for _n, la, lo2 in con.execute("SELECT * FROM core.vie_resto").fetchall()
                                 if km(lat, lon, la, lo2) <= RAYON_RESTO_KM)
    postes = con.execute("SELECT poste, montant, part, inclus FROM core.vie_poste").fetchall()
    order = {p: i for i, p in enumerate(POSTES_COURANTS + POSTES_SELON)}
    out["postes"] = sorted(({"poste": NOMS.get(p, p), "source_poste": p, "montant": m, "part": pa, "inclus": inc}
                            for p, m, pa, inc in postes), key=lambda x: order.get(x["source_poste"], 99))
    toujours = sum(x["montant"] for x in out["postes"] if x["inclus"] == "toujours")
    selon = sum(x["montant"] for x in out["postes"] if x["inclus"] == "selon")
    complete = {x["source_poste"] for x in out["postes"]} == set(POSTES_COURANTS + POSTES_SELON)
    if out["loyer"] and complete:
        out["mensuel"] = {"min": _arrondi(out["loyer"]["min"] + toujours), "max": _arrondi(out["loyer"]["max"] + toujours + selon),
                          "courants": toujours, "selon": selon}
    fr = con.execute("""SELECT titre, rang, rubrique, texte, montant, cvec FROM core.vie_frais WHERE cod_aff_form = ?
        ORDER BY rang""", [cod]).fetchall() if _has(con, "vie_frais") else []
    if fr:
        lignes = [{"rubrique": r, "texte": t} for _ti, rg, r, t, _m, _c in fr if rg]
        par_an = next((m for _ti, rg, r, _t, m, _c in fr if (r or "").strip().lower() == "par année"), None)
        out["frais"] = {"titre": fr[0][0], "lignes": lignes, "montant": par_an, "cvec": bool(fr[0][5])}
    if out["mensuel"] and out["frais"] and out["frais"]["montant"] is not None:
        cv = CVEC["montant"] if out["frais"]["cvec"] else 0
        out["annuel"] = {"min": _arrondi(MOIS_PAR_AN * out["mensuel"]["min"] + out["frais"]["montant"] + cv),
                         "max": _arrondi(MOIS_PAR_AN * out["mensuel"]["max"] + out["frais"]["montant"] + cv),
                         "frais": out["frais"]["montant"], "cvec": cv}
    if not (out["loyer"] or out["crous"] or out["frais"] or out["postes"]):
        return None
    return out


def compact(con) -> dict:
    """{code: [tuition read or null, monthly min, monthly max]} for the lists (comparator, map card): no parameter."""
    out: dict = {}
    if not _has(con, "vie_frais"):
        return out
    for cod, m in con.execute("""SELECT cod_aff_form, any_value(montant) FILTER (WHERE lower(trim(rubrique)) = 'par année')
            FROM core.vie_frais GROUP BY cod_aff_form""").fetchall():
        out[cod] = m
    return out
