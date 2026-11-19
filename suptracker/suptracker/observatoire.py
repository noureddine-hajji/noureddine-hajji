"""Observatoire: three national overviews of the published SIES figures (owner, 2026-11-19).

Every figure is either PUBLISHED per formation by SIES or a sum / median of published figures, computed here and labelled:

  * Tendances (every campaign, per type of diploma = the map's types, `carte.diplome_of`):
      - "vœux par place" = SUM of the main-phase vœux (`nb_voe_pp`) / SUM of the places (`capa_fin`), over the formations of
        the type that publish both, places > 0. These are VŒUX, not people: a candidate makes up to 10 vœux, and the ratio
        measures demand, never a difficulty or a chance (same wording as `tension.PRUDENCE`);
      - the MEDIAN of the official access rates (`taux_acces_ens`, never recomputed) over the formations that publish one;
      - the number of formations, because the offer changes from one campaign to the next (FCIL x4, new schools...).
    A type is followed only when it has at least MIN_TYPE formations in EVERY campaign.
  * Demande par académie (latest campaign, per type and for all types): the same ratio per académie of the formation, with its
    two counts; fewer than MIN_ACAD_FORMATIONS formations or MIN_ACAD_PLACES places = no figure (said). The académie labels
    are folded (accents, case) because SIES spells one of them two ways (Besançon 2022, Besancon 2023-2025); the label shown
    is the accented spelling. The position of a metropolitan académie on the page's map is the mean position of its
    formations (latest campaign, published coordinates); overseas and abroad are listed apart, never placed.
    Île-de-France: one more line per type, the ratio of the three académies' summed counts (`IDF`), for the map only.
  * Rester près ou partir loin (latest campaign, per type): the néo-bachelier admits who passed their bac in the
    formation's académie (`acc_aca_orig`) / all néo-bachelier admits (`acc_neobac`), both SUMMED: admits are people, so the
    sum is a count of people. SIES publishes this only for néo-bacheliers: the page says so. Fewer than MIN_NEOBAC néo-
    bachelier admits, or fewer than MIN_PROX_FORMATIONS formations, = no figure. A row without the count, or with more
    same-académie admits than néo-bacheliers (none in 2022-2025), is left out of both sums.

Nothing here is read for a student: no profile, no parameter, one shared-cached answer. Never a probability of admission.
"""
from __future__ import annotations

import unicodedata
from statistics import median

from . import carte as CA
from . import tension as TE

MIN_TYPE = 20               # formations of a type in every campaign to follow its trend
MIN_ACAD_FORMATIONS = 5     # formations of a type in an académie to give its ratio
MIN_ACAD_PLACES = 100       # places of a type in an académie to give its ratio
MIN_NEOBAC = 100            # néo-bachelier admits of a type to give its same-académie share
MIN_PROX_FORMATIONS = 5     # ... spread over at least this many formations (one formation's share is its own fiche's)
TOUS = "Toutes les formations"
# Île-de-France's three académies are one bubble on the page's map (their centres are a few kilometres apart): the ratio of
# their SUMMED counts, with the same thresholds; each académie keeps its own row in the table
IDF = ("paris", "creteil", "versailles")
# a metropolitan académie is placed on the map when the mean position of its formations falls in this box (lat, lon)
METRO = ((41.0, 51.5), (-5.5, 10.0))


def fold(label: str | None) -> str:
    """Académie key: accents and case off, every non-letter a single space."""
    s = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s).split())


def _accents(label: str) -> int:
    return sum(1 for ch in label if ord(ch) > 127)


def labels(con) -> dict[str, str]:
    """folded key -> shown label: the spelling with the most accented letters, then the latest campaign's."""
    rows = con.execute("""SELECT acad_mies, max(session) FROM core.formation_year WHERE acad_mies IS NOT NULL
                          GROUP BY 1""").fetchall()
    best: dict[str, tuple] = {}
    for lab, ses in rows:
        k = fold(lab)
        cand = (_accents(lab), ses, lab)
        if k not in best or cand > best[k]:
            best[k] = cand
    return {k: v[2] for k, v in best.items()}


def ratio(voeux: int, places: int) -> float | None:
    return round(voeux / places, 1) if places else None


def _rows(con):
    return con.execute("""SELECT session, fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins, acad_mies, nb_voe_pp,
                                 capa_fin, taux_acces_ens, acc_neobac, acc_aca_orig, lat, lon
                          FROM core.formation_year""").fetchall()


def build(con) -> dict:
    rows = _rows(con)
    sessions = sorted({r[0] for r in rows})
    if not sessions:
        return {"sessions": [], "session": None, "tendances": [], "demande": {}, "academies": [], "proximite": []}
    last = sessions[-1]
    lab = labels(con)
    trend: dict = {}
    dem: dict = {}
    prox: dict = {}
    pos: dict = {}
    for ses, fili, form, fil, lib, acad, voe, capa, taux, neo, aca, lat, lon in rows:
        typ = CA.diplome_of(fili, form, fil, lib)[0]
        t = trend.setdefault(typ, {}).setdefault(ses, {"n": 0, "voeux": 0, "places": 0, "n_ratio": 0, "taux": []})
        t["n"] += 1
        usable = voe is not None and capa is not None and capa > 0
        if usable:
            t["voeux"] += voe
            t["places"] += capa
            t["n_ratio"] += 1
        if taux is not None:
            t["taux"].append(taux)
        if ses != last:
            continue
        k = fold(acad)
        if k and lat is not None and lon is not None:
            p = pos.setdefault(k, [0.0, 0.0, 0])
            p[0] += lat
            p[1] += lon
            p[2] += 1
        for key in (typ, TOUS):
            if k:
                d = dem.setdefault(key, {}).setdefault(k, {"n": 0, "voeux": 0, "places": 0})
                if usable:
                    d["n"] += 1
                    d["voeux"] += voe
                    d["places"] += capa
            if neo and aca is not None and 0 <= aca <= neo:     # a row with more same-académie admits than néo-bacheliers is left out
                x = prox.setdefault(key, {"neobac": 0, "meme_academie": 0, "n": 0})
                x["neobac"] += neo
                x["meme_academie"] += aca
                x["n"] += 1
    tendances = []
    for typ, by in trend.items():
        if any(by.get(s, {}).get("n", 0) < MIN_TYPE for s in sessions):
            continue
        serie = []
        for s in sessions:
            x = by[s]
            serie.append({"session": s, "formations": x["n"], "formations_ratio": x["n_ratio"], "voeux": x["voeux"],
                          "places": x["places"], "voeux_par_place": ratio(x["voeux"], x["places"]),
                          "taux_median": round(median(x["taux"]), 1) if x["taux"] else None, "n_taux": len(x["taux"])})
        tendances.append({"diplome": typ, "serie": serie})
    tendances.sort(key=lambda t: (-t["serie"][-1]["formations"], t["diplome"]))
    academies = []
    for k in sorted(set(pos) | set(dem.get(TOUS, {})), key=lambda k: CA.sort_key(lab[k])):
        p = pos.get(k)
        la, lo = (p[0] / p[2], p[1] / p[2]) if p else (None, None)
        metro = p is not None and METRO[0][0] <= la <= METRO[0][1] and METRO[1][0] <= lo <= METRO[1][1]
        academies.append({"cle": k, "academie": lab[k], "lat": round(la, 3) if metro else None,
                          "lon": round(lo, 3) if metro else None, "metropole": metro})
    demande = {}
    for typ, by in dem.items():
        out = {}
        for k, d in by.items():
            enough = d["n"] >= MIN_ACAD_FORMATIONS and d["places"] >= MIN_ACAD_PLACES
            out[k] = {"formations": d["n"], "voeux": d["voeux"], "places": d["places"],
                      "voeux_par_place": ratio(d["voeux"], d["places"]) if enough else None}
        demande[typ] = out
    idf = {}
    for typ, by in dem.items():
        parts = [by[k] for k in IDF if k in by]
        n, v, p = (sum(x[f] for x in parts) for f in ("n", "voeux", "places"))
        idf[typ] = {"formations": n, "voeux": v, "places": p,
                    "voeux_par_place": ratio(v, p) if n >= MIN_ACAD_FORMATIONS and p >= MIN_ACAD_PLACES else None}
    proximite = []
    for typ, x in prox.items():
        part = round(100 * x["meme_academie"] / x["neobac"], 1) if x["neobac"] >= MIN_NEOBAC and x["n"] >= MIN_PROX_FORMATIONS else None
        proximite.append({"diplome": typ, "formations": x["n"], "admis_neobac": x["neobac"],
                          "meme_academie": x["meme_academie"], "part_meme_academie": part})
    proximite.sort(key=lambda p: (p["part_meme_academie"] is None, -(p["part_meme_academie"] or 0), p["diplome"]))
    return {"sessions": sessions, "session": last, "tendances": tendances, "academies": academies, "demande": demande,
            "ile_de_france": {"academies": list(IDF), "demande": idf}, "proximite": proximite, "tous": TOUS, "prudence": TE.PRUDENCE,
            "seuils": {"type": MIN_TYPE, "academie_formations": MIN_ACAD_FORMATIONS, "academie_places": MIN_ACAD_PLACES,
                       "min_neobac": MIN_NEOBAC, "proximite_formations": MIN_PROX_FORMATIONS}}
