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

  * Profils des admis (owner, 2026-11-19), per type, from PUBLISHED counts summed over coherent rows (people):
      - filles: girls among the admits (`acc_tot_f` / `acc_tot`) beside girls among the confirmed vœux (`voe_tot_f` / `voe_tot`,
        vœux not people), latest campaign; a row whose girls exceed its total is left out of that pair;
      - bacs: bac général / techno / pro among the néo-bachelier admits (`acc_bg|bt|bp` / `acc_neobac`), latest campaign, only
        rows whose three counts add up to `acc_neobac` (all of 2022-2025); a low share is "rare", never "closed";
      - mentions: sans mention, AB, B, TB, TBF among the néo-bachelier admits (`acc_neobac`, SIES's own denominator of `pct_tb`...),
        first and latest campaigns. In 2022, 356 rows publish one admit fewer in their mentions than in `acc_neobac` (456 admits):
        they are KEPT (leaving them out would move a type by up to 4 points); a row whose mentions exceed `acc_neobac` is left out.
        Never the level required or a chance, and no mention is published per bac series.
    Same thresholds as the same-académie share: under MIN_NEOBAC admits (all admits for the girls) or MIN_PROX_FORMATIONS
    formations, no figure.
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
MENTIONS = ("sansmention", "ab", "b", "tb", "tbf")      # acc_<m>; "non renseignée" counts in the total only
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


def _part(num, den):
    return round(100 * num / den, 1) if den else None


def profils(con, sessions: list) -> dict:
    """Girls, bac routes and mentions of the admits per type (see the module text): published counts summed, coherent rows."""
    first, last = sessions[0], sessions[-1]
    rows = con.execute("""SELECT session, fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins, acc_tot, acc_tot_f, voe_tot,
               voe_tot_f, acc_neobac, acc_bg, acc_bt, acc_bp, acc_sansmention, acc_ab, acc_b, acc_tb, acc_tbf,
               acc_mention_non_renseignee FROM core.formation_year WHERE session IN (?, ?)""", [first, last]).fetchall()
    fil: dict = {}
    bac: dict = {}
    men: dict = {}
    for ses, fili, form, fl, lib, tot, f, voe, voef, neo, bg, bt, bp, *ments in rows:
        typ = CA.diplome_of(fili, form, fl, lib)[0]
        m5, nr = ments[:5], ments[5]
        for key in (typ, TOUS):
            if ses == last:
                if tot and f is not None and 0 <= f <= tot and voe and voef is not None and 0 <= voef <= voe:
                    x = fil.setdefault(key, {"n": 0, "admis": 0, "admises": 0, "voeux": 0, "voeux_filles": 0})
                    x["n"] += 1
                    x["admis"] += tot
                    x["admises"] += f
                    x["voeux"] += voe
                    x["voeux_filles"] += voef
                if neo and None not in (bg, bt, bp) and bg + bt + bp == neo:
                    x = bac.setdefault(key, {"n": 0, "neo": 0, "general": 0, "techno": 0, "pro": 0})
                    x["n"] += 1
                    x["neo"] += neo
                    x["general"] += bg
                    x["techno"] += bt
                    x["pro"] += bp
            if neo and None not in m5 and sum(m5) + (nr or 0) <= neo:
                x = men.setdefault(key, {}).setdefault(ses, {"n": 0, "neo": 0, **{m: 0 for m in MENTIONS}})
                x["n"] += 1
                x["neo"] += neo
                for m, v in zip(MENTIONS, m5):
                    x[m] += v

    def enough(x, total):
        return total >= MIN_NEOBAC and x["n"] >= MIN_PROX_FORMATIONS
    filles = [{"diplome": k, "formations": x["n"], "admis": x["admis"], "admises": x["admises"], "voeux": x["voeux"],
               "voeux_filles": x["voeux_filles"],
               "part_admis": _part(x["admises"], x["admis"]) if enough(x, x["admis"]) else None,
               "part_voeux": _part(x["voeux_filles"], x["voeux"]) if enough(x, x["admis"]) else None} for k, x in fil.items()]
    filles.sort(key=lambda r: (r["part_admis"] is None, -(r["part_admis"] or 0), r["diplome"]))
    bacs = []
    for k, x in bac.items():
        ok = enough(x, x["neo"])
        bacs.append({"diplome": k, "formations": x["n"], "admis_neobac": x["neo"], "general": x["general"], "techno": x["techno"],
                     "pro": x["pro"], **{f"part_{r}": _part(x[r], x["neo"]) if ok else None for r in ("general", "techno", "pro")}})
    bacs.sort(key=lambda r: (r["part_general"] is None, (r["part_general"] if r["part_general"] is not None else 0), r["diplome"]))

    def reading(x):
        if not x or not enough(x, x["neo"]):
            return None
        parts = {m: _part(x[m], x["neo"]) for m in MENTIONS}
        return {"formations": x["n"], "admis_neobac": x["neo"], "parts": parts, "tb_plus": _part(x["tb"] + x["tbf"], x["neo"])}
    mentions = []
    for k, by in men.items():
        now = by.get(last)
        if not now:
            continue
        r = reading(now)
        mentions.append({"diplome": k, "formations": now["n"], "admis_neobac": now["neo"], "lecture": r,
                         "avant": {"session": first, **(reading(by.get(first)) or {"tb_plus": None})}})
    mentions.sort(key=lambda r: (r["lecture"] is None, -((r["lecture"] or {}).get("tb_plus") or 0), r["diplome"]))
    return {"filles": filles, "bacs": bacs, "mentions": mentions, "mentions_avant": first}


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
            **profils(con, sessions),
            "seuils": {"type": MIN_TYPE, "academie_formations": MIN_ACAD_FORMATIONS, "academie_places": MIN_ACAD_PLACES,
                       "min_neobac": MIN_NEOBAC, "proximite_formations": MIN_PROX_FORMATIONS}}
