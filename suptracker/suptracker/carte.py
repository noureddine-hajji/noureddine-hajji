"""Sprint "Carte": the formations on an OpenStreetMap map, filtered like the Parcoursup map (latest campaign).

Two levels of diploma, as the owner asked (2026-11-08): the TYPE of diploma (BTS, BUT, Licence, Double licence, CPGE ECG,
CPGE ECT, CPES...) then its MENTION (BUT Science des données, CPGE ECG Mathématiques appliquées + ESH...). Both are read
from the published labels (fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins) by fixed rules (`diplome_of`).

The neutral layer comes from here. The zones (sécurité / cible / ambitieux) are NEVER computed here: `zones` asks
journey.stage2 for the formations' own types with `only=` their codes, so a zone is exactly the one of "Mon parcours",
Plan B and "Mes vœux". The visitor's position is never sent: the "around a town" filter runs in the browser.

Apprenticeship (owner's request, 2026-11-08): SIES publishes no statistics for apprenticeship offers after 2022 (they have
their own codes, absent from the vœux files), so the map adds them from the Parcoursup CARTOGRAPHIE, latest session, as
listed offers only: no zone, no access rate, no "Mes vœux" (which reads SIES rows); the page links to their Parcoursup page.
Their type of diploma and mention are those of the SIES formations that carry the SAME cartographie labels (a vote,
`label_votes`), their académie that of their establishment (UAI), else of their département. Apprenticeship training is free
for the apprentice (Code du travail, art. L6211-1): a private establishment outside State contract is "prive_app", never the
fee-charging "prive" of Plan B's rule.

Merge (owner's request, 2026-11-09): an apprenticeship offer of the SAME establishment (UAI) for the SAME diploma and mention
(the same cartographie labels) as an initial formation of the latest SIES campaign is not listed apart: it is attached to that
formation (`rattachee`), which then carries both labels, "Formation initiale" and "Apprentissage", and the CFA's name and
Parcoursup page. Only the same UAI counts: another establishment of the same town is another school.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from . import journey as J
from . import planb as PB

FIELDS = ["cod_aff_form", "etablissement", "formation", "ville", "academie", "lat", "lon", "contrat_etab", "select_form",
          "internat", "distance", "amenag_sport", "amenag_art", "taux_acces_ens", "type_key"]


def statut_of(contrat: str | None) -> str:
    """Parcoursup's three kinds of establishment; the fee-charging private ones (Plan B's rule) are 'prive'."""
    if contrat == "Public":
        return "public"
    if contrat in PB.PAID_CONTRACTS:
        return "prive"
    return "contrat"                      # private under contract with the State (and the EESC)


def statut_carto(types_etab: str | None) -> str | None:
    """The cartographie's three kinds of establishment, for an apprenticeship offer (free for the apprentice)."""
    t = (types_etab or "").strip()
    if t == "Publics":
        return "public"
    if "hors contrat" in t:               # "Privés hors contrat" (older sessions) is outside contract, not under it
        return "prive_app"
    if "contrat" in t:
        return "contrat"
    if t.startswith("Priv"):
        return "prive_app"
    return None


def _fold(x: str | None) -> str:
    return unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower().strip()


FICHE_PREFIX = "https://dossierappel.parcoursup.fr/"


def diplome_of(fili: str | None, form: str | None, fil: str | None, lib: str | None) -> tuple[str, str]:
    """(type of diploma, mention) of a formation, from its published labels, by fixed rules."""
    fili, form, fil, lib = fili or "", (form or "").strip(), (fil or "").strip(), (lib or "").strip()
    if re.match(r"(?i)double licence", lib):
        m = re.sub(r"(?i)^double licence\s*-\s*", "", lib).strip(" -")
        return "Double licence", m or fil
    if fili == "BTS":
        return "BTS - BTSA - BTSM", fil
    if fili == "BUT":
        return "BUT", fil
    if fili == "Licence_Las":
        return "Licence Accès Santé (L.AS)", fil
    if fili == "PASS":
        return "PASS - Parcours d'accès spécifique santé", fil or "PASS"
    if form.startswith("LP"):
        return "Licence professionnelle", fil
    if fili == "Licence":
        return "Licence", fil
    if form == "Classe préparatoire économique et commerciale":
        if fil.startswith("ECG"):
            return "CPGE ECG", fil.replace("ECG - ", "", 1)
        if fil.startswith("ECT"):
            return "CPGE ECT", fil.replace("ECT - ", "", 1)
        return "CPGE économique (ENS)", fil
    if form == "Classe préparatoire scientifique":
        return "CPGE scientifique", fil
    if form == "Classe préparatoire littéraire":
        return "CPGE littéraire", fil
    if form == "CPES":
        return "CPES", re.sub(r"^Cycle pluridisciplinaire d'Études Supérieures\s*-\s*", "", fil)
    if form.startswith("CUPGE"):
        return "CUPGE", fil
    rules = [(r"^D\.E secteur sanitaire", "Études de santé (diplômes d'État)"), (r"^D\.E secteur social", "Formations du travail social"),
             (r"écoles d'ingénieurs", "Écoles d'ingénieurs"), (r"écoles de commerce", "Écoles de commerce et de management"),
             (r"^Sciences politiques", "Sciences Po - Instituts d'études politiques"), (r"^(Certificat de Spécialisation|FCIL)", "Certificats de spécialisation et FCIL"),
             (r"^(BPJEPS|DEJEPS)", "Formations aux métiers du sport"), (r"(?i)^Diplôme d'(Université|[EÉé]tablissement)", "Diplômes d'université ou d'établissement"),
             (r"écoles supérieures de cuisine", "Formations aux métiers de l'hôtellerie restauration"),
             (r"^(Mise à niveau|Année préparatoire|Classe préparatoire aux études supérieures)", "Formations préparatoires à l'enseignement supérieur"),
             (r"^(DN MADE|Diplôme National d'Art|Formation des écoles supérieures d'art)", "Formations d'art et de design"),
             (r"^C\.M\.I", "C.M.I - Cursus Master en Ingénierie")]
    for pat, label in rules:
        if re.search(pat, form):
            return label, fil
    return form or fili or "Autre formation", fil


def _has_labels(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
                               AND table_name = 'cartographie' AND column_name = 'type_formation'""").fetchone()[0])


def label_votes(con) -> tuple[dict, dict]:
    """{(type_formation, mention_lib): (type, mention)} and {type_formation: type}: the most frequent reading among the SIES
    formations of the latest campaign that carry these cartographie labels (ties: alphabetical)."""
    rows = con.execute("""SELECT c.type_formation, c.mention_lib, f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.lib_for_voe_ins
        FROM core.formation_year f JOIN core.cartographie c USING (cod_aff_form)
        WHERE f.session = (SELECT max(session) FROM core.formation_year) AND c.type_formation IS NOT NULL""").fetchall()
    pair, typ = {}, {}
    for tf, fl, *lab in rows:
        dm = diplome_of(*lab)
        pair.setdefault((tf, fl), Counter())[dm] += 1
        typ.setdefault(tf, Counter())[dm[0]] += 1
    best = lambda c: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]  # noqa: E731
    return {k: best(v) for k, v in pair.items()}, {k: best(v) for k, v in typ.items()}


def _type_of(tf: str | None, typ: dict) -> str:
    """A cartographie type no SIES formation carries as a whole: a list "A,B" takes its first part SIES knows, else its
    first part; any other label is kept as published."""
    if tf in typ:
        return typ[tf]
    parts = [x.strip() for x in (tf or "").split(",") if x.strip()]
    return next((typ[x] for x in parts if x in typ), parts[0] if parts else "Autre formation")


_CACHE: dict = {}


def _fingerprint(con) -> tuple:
    db = tuple(r[2] for r in con.execute("PRAGMA database_list").fetchall())
    n = con.execute("""SELECT (SELECT count(*) FROM core.cartographie), (SELECT count(*) FROM core.formation_year),
                              (SELECT max(session) FROM core.formation_year)""").fetchone()
    return db + tuple(n)


def apprentissage(con) -> list[dict]:
    """The apprenticeship offers of the latest cartographie session that SIES does not publish (no statistics), each with
    the initial formations it is attached to (`rattachee`: same UAI, same diploma and mention). Cached per warehouse."""
    if not _has_labels(con):
        return []
    key = _fingerprint(con)
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = _apprentissage(con)
    return _CACHE[key]


def _apprentissage(con) -> list[dict]:
    rows = con.execute("""
        SELECT c.cod_aff_form, c.etab_nom, c.nom_long, c.commune, c.departement, c.etab_uai, c.lat, c.lon, c.types_etab,
               c.type_formation, c.mention_lib, c.internat, c.distance, c.amenag_sport, c.amenag_art, c.fiche_url, c.carto_session
        FROM core.cartographie c
        WHERE c.apprentissage AND c.carto_session = (SELECT max(carto_session) FROM core.cartographie)
          AND c.cod_aff_form NOT IN (SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session) FROM core.formation_year))
        ORDER BY c.etab_nom, c.cod_aff_form""").fetchall()
    if not rows:
        return []
    pair, typ = label_votes(con)
    initial: dict = {}                     # (UAI, type label, mention label) -> initial formations of the latest campaign
    for cod, uais, tf, fl in con.execute("""SELECT f.cod_aff_form, list_distinct([f.cod_uai, c.etab_uai]), c.type_formation, c.mention_lib
            FROM core.formation_year f JOIN core.cartographie c USING (cod_aff_form)
            WHERE f.session = (SELECT max(session) FROM core.formation_year) AND c.type_formation IS NOT NULL
              AND NOT coalesce(f.apprentissage, false)""").fetchall():
        for u in uais:
            if u:
                initial.setdefault((u, tf, fl), set()).add(cod)
    acad_rows = con.execute("""SELECT cod_uai, dep_lib, acad_mies FROM core.formation_year
                               WHERE session = (SELECT max(session) FROM core.formation_year) AND acad_mies IS NOT NULL""").fetchall()
    by_uai, by_dep = {}, {}
    for uai, dep, ac in acad_rows:
        by_uai.setdefault(uai, Counter())[ac] += 1
        by_dep.setdefault(_fold(dep), Counter())[ac] += 1
    top = lambda c: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if c else None  # noqa: E731
    out = []
    for (cod, etab, nom, commune, dep, uai, lat, lon, tc, tf, fl, internat, distance, sport, art, fiche, sess) in rows:
        d, m = pair.get((tf, fl)) or (_type_of(tf, typ), fl or "")
        out.append({"cod_aff_form": cod, "etablissement": etab or "", "formation": nom or fl or "", "ville": commune or "",
                    "academie": top(by_uai.get(uai)) or top(by_dep.get(_fold(dep))),
                    "lat": None if lat is None else round(lat, 5), "lon": None if lon is None else round(lon, 5),
                    "contrat_etab": tc, "select_form": None, "internat": internat, "distance": distance, "amenag_sport": sport,
                    "amenag_art": art, "taux_acces_ens": None, "type_key": None, "diplome": d, "mention": m,
                    "statut": statut_carto(tc), "payant": False, "apprentissage": True, "stats": False, "session_offre": sess,
                    "fiche": fiche if (fiche or "").startswith(FICHE_PREFIX) else None,
                    "rattachee": sorted(initial.get((uai, tf, fl), ())) if uai else []})
    return out


# ---- R10 (owner, 2026-11-13): per formation, the access rate of each bac route and the most represented line among the admits ----
BACS = ("bg", "bt", "bp")
BAC_NAME = {"bg": "bac général", "bt": "bac techno", "bp": "bac pro"}
_LINES: dict = {}


SPE_SHORT = {"MATHS": "Maths", "PC": "Physique-chimie", "SVT": "SVT", "SES": "SES", "HGGSP": "HGGSP", "LLCER": "LLCER", "HLP": "HLP",
             "NSI": "NSI", "SI": "SI", "LLCA": "LLCA", "EPPCS": "EPPCS", "ART": "Arts", "BIOECO": "Biologie-écologie"}


def _line_label(bac: str, libelle: str, dkey: str | None = None) -> str:
    """A report line as a student reads it: bac général 'SES & HGGSP' (short names from the doublette key, else the printed
    label without 'Spécialité'); bac techno 'SERIE · specialty'; bac pro the specialty as printed."""
    if bac == "bg" and dkey and all(p in SPE_SHORT for p in dkey.split("+")):
        return " & ".join(SPE_SHORT[p] for p in dkey.split("+"))
    if bac == "bt":
        from . import voies as VO
        k = VO.voie_key("bt", libelle)
        if k in VO.BT_NAME:
            serie, spe = VO.BT_NAME[k]
            return f"{serie} · {spe}"
        return re.sub(r"^Msgn/\s*", "STMG · ", " ".join(libelle.split()))
    return " ".join(re.sub(r"\s+Spécialité\b", "", libelle).split())


def bac_lines(con) -> dict:
    """{code: {"bacs": {bac: {taux, source, n}}, "majo": {...} | None}} for the latest SIES campaign.
    - Rate per bac: the formation's own report of that campaign (verified, cross-checked), en_position / confirmes over every
      line of the bac (its "Autres" bucket included): published counts, the Parcoursup fiche's "taux d'accès" of that bac, for
      candidates in terminale in France; a masked table = no figure (`masque`). No report: the site's ESTIMATED access of the
      route (journey.series_access_sql, capped at 100), flagged `source` "estimation" and `fragile` below 20 candidates.
    - Most represented line among the admits (owner): the route with the most admits in the SIES campaign (acc_bg / acc_bt /
      acc_bp; a tie = none), then that route's report line with the most admits (`acceptes`, never the "Autres" bucket); a tie on
      the top = `exaequo`. No report, a masked table or no admits = none."""
    key = _fingerprint(con)
    if key in _LINES:
        return _LINES[key]
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    est = ", ".join(f"{J.series_access_sql(b)}, {J.series_candidates_sql(b)}" for b in BACS)
    fy = con.execute(f"""SELECT fy.cod_aff_form, fy.acc_bg, fy.acc_bt, fy.acc_bp, {est}
                         FROM core.formation_year fy WHERE fy.session = ?""", [latest]).fetchall()
    has = lambda t: con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = ?", [t]).fetchone()[0]  # noqa: E731
    rows, masked, reports = {}, set(), set()
    if has("rapport") and has("rapport_doublette"):
        rec = "AND r.recoupe" if con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
                                                AND table_name = 'rapport' AND column_name = 'recoupe'""").fetchone()[0] else ""
        # a report EXISTS apart from its detail rows: 2,816 cross-checked 2025 reports print no line (every table masked,
        # or no candidate of a bac); they are reports, never "no report" (Codex)
        reports = {c for (c,) in con.execute(f"SELECT DISTINCT r.cod_aff_form FROM core.rapport r WHERE r.session = ? {rec}", [latest]).fetchall()}
        for cod, bac, rang, lib, dkey, autres, conf, pos, acc in con.execute(f"""
                SELECT d.cod_aff_form, d.bac, d.rang, d.libelle, d.doublette_key, d.autres, d.confirmes, d.en_position, d.acceptes
                FROM core.rapport_doublette d JOIN core.rapport r ON r.cod_aff_form = d.cod_aff_form AND r.session = d.session
                WHERE d.session = ? {rec} ORDER BY d.cod_aff_form, d.bac, d.rang""", [latest]).fetchall():
            rows.setdefault(cod, {}).setdefault(bac, []).append((rang, lib, bool(autres), conf or 0, pos or 0, acc or 0, dkey))
        if has("rapport_masque"):
            masked = {(c, b) for c, b in con.execute(f"""SELECT m.cod_aff_form, m.bac FROM core.rapport_masque m
                      JOIN core.rapport r ON r.cod_aff_form = m.cod_aff_form AND r.session = m.session
                      WHERE m.session = ? {rec}""", [latest]).fetchall()}
    out = {}
    for cod, abg, abt, abp, ebg, nbg, ebt, nbt, ebp, nbp in fy:
        acc, estim, cand = {"bg": abg, "bt": abt, "bp": abp}, {"bg": ebg, "bt": ebt, "bp": ebp}, {"bg": nbg, "bt": nbt, "bp": nbp}
        mine = rows.get(cod, {}) if cod in reports else None
        bacs = {}
        for b in BACS:
            if (cod, b) in masked:
                bacs[b] = {"taux": None, "source": "rapport", "masque": True}
            elif mine is not None and mine.get(b):
                c = sum(x[3] for x in mine[b])
                bacs[b] = {"taux": round(100 * sum(x[4] for x in mine[b]) / c, 1) if c else None, "source": "rapport", "n": c}
            elif mine is not None:
                bacs[b] = {"taux": None, "source": "rapport", "n": 0}          # the report prints no candidate of this bac
            else:                                     # no report: the site's estimated access of the route (journey), flagged
                n = cand[b] or 0
                bacs[b] = {"taux": None if estim[b] is None or not n else round(estim[b], 1), "source": "estimation", "n": n,
                           "fragile": n < J.MIN_SERIES_CANDIDATES}
        majo = None
        a = {b: (acc[b] or 0) for b in BACS}
        top = max(a.values())
        route = [b for b in BACS if a[b] == top]
        if top > 0 and len(route) == 1 and mine is not None and (cod, route[0]) not in masked:
            lines = [x for x in mine.get(route[0], []) if not x[2] and x[5] > 0]
            if lines:
                best = max(x[5] for x in lines)
                win = [x for x in lines if x[5] == best]
                majo = {"bac": route[0], "libelle": _line_label(route[0], win[0][1], win[0][6]), "acceptes": best,
                        "exaequo": len(win) > 1, "admis_route": a[route[0]]}
        out[cod] = {"bacs": bacs, "majo": majo}
    _LINES.clear()
    _LINES[key] = out
    return out


def offres_par_formation(con) -> dict:
    """{initial formation code: the apprenticeship offers attached to it (CFA, Parcoursup page)}."""
    out: dict = {}
    for a in apprentissage(con):
        for cod in a["rattachee"]:
            out.setdefault(cod, []).append({"cod_aff_form": a["cod_aff_form"], "etablissement": a["etablissement"],
                                            "formation": a["formation"], "ville": a["ville"], "fiche": a["fiche"]})
    return out


def for_formation(con, cod: str) -> list:
    """The apprenticeship offers attached to one initial formation (its page)."""
    return offres_par_formation(con).get(cod, [])


# ---- R9 (owner, 2026-11-12): mentions that name the same thing are grouped by FIXED rules, never by fuzzy matching ----
# Double licence: the unordered pair of disciplines (Maths / Info = Info / Maths), each discipline under one spelling.
# "Economie" and "Economie et gestion" are one discipline, "Gestion" another (owner). Unknown spellings stay as printed.
DL_DISCIPLINE = {
    "economie": "Économie", "economie et gestion": "Économie", "gestion": "Gestion",
    "langues, litteratures et civilisations etrangeres et regionales": "Langues (LLCER)", "llcer": "Langues (LLCER)",
    "langues etrangeres appliquees": "Langues étrangères appliquées (LEA)",
    "mathematiques et informatique appliquees aux sciences humaines et sociales": "MIASHS",
    "physique, chimie": "Physique-chimie", "geographie et amenagement": "Géographie", "geographie": "Géographie",
    "histoire de l'art et archeologie": "Histoire de l'art et archéologie", "lettres, langues": "Lettres",
    "cinema et audiovisuel": "Cinéma", "cinema": "Cinéma", "cinema : pratique et esthetique": "Cinéma",
    "musique et musicologie": "Musicologie", "etudes theatrales": "Études théâtrales", "sciences de l'homme, anthropologie, ethnologie": "Anthropologie, ethnologie",
}
# CUPGE and CPES: one rule per family, read in order on the folded mention (the first that matches wins)
FAMILY_RULES = {
    "CUPGE": [("commerce", "Préparation aux écoles de commerce"), (r"agro|veto|sciences de la vie", "Biologie, préparation agro-véto"),
              (r"lettres", "Lettres"), (r"chimie", "Physique-chimie"),
              (r"informatique|math|physique|mecanique|isima|ingenieur|scientifique", "Maths, physique, informatique"),
              (r".", "Sans précision de discipline")],
    "CPES": [(r"donnees", "Sciences des données"), (r"ingenieur", "Sciences pour l'ingénieur"),
             (r"environnement|ecologique", "Environnement, transition écologique"),
             (r"economie|droit", "Économie, droit, société"), (r"sciences et humanites", "Sciences et humanités"),
             (r"humanites|sciences sociales", "Humanités, sciences sociales"), (r"sciences et societe", "Sciences et société"),
             (r"matiere|sciences de la vie|^sciences$", "Sciences (matière, vie)"), (r".", "Autre CPES")],
}
# Licence and L.AS: only near-duplicates of one national mention
NEAR_DUPLICATES = {"theologie": "Théologie", "theologie catholique": "Théologie", "theologie protestante": "Théologie",
                   "cinema": "Cinéma et Audiovisuel", "cinema et audiovisuel": "Cinéma et Audiovisuel",
                   "histoire de l'art": "Histoire de l'art et archéologie"}


def sort_key(label: str) -> str:
    """Alphabetical order in French: accents and case ignored ("Écoles" sorts with "E", not after "z")."""
    return " ".join(_fold(label).split())


def _dl_discipline(x: str) -> str:
    k = " ".join(_fold(x).split())
    if k in DL_DISCIPLINE:
        return DL_DISCIPLINE[k]
    x = " ".join(x.split())
    return x[:1].upper() + x[1:].lower() if x.isupper() else x


def groupe_of(diplome: str, mention: str | None) -> str:
    """The group a mention is shown under in the map's mention filter (the formation keeps its own label)."""
    m = " ".join((mention or "").split())
    if diplome == "Double licence":
        head = m.split(" - ")[0] if "/" in m.split(" - ")[0] else m
        parts = [p for p in re.split(r"\s*/\s*|\s+-\s+", head) if p.strip()][:2]
        if len(parts) < 2:
            return m or "Sans précision"
        a, b = sorted((_dl_discipline(p) for p in parts), key=sort_key)
        return f"{a} / {b}"
    if diplome in FAMILY_RULES:
        f = " ".join(_fold(m).split())
        return next(label for rx, label in FAMILY_RULES[diplome] if re.search(rx, f))
    if diplome in ("Licence", "Licence Accès Santé (L.AS)"):
        return NEAR_DUPLICATES.get(" ".join(_fold(m).split()), m)
    return m


def facets(con) -> dict:
    """Every type of diploma and its mentions, with their number of formations in the latest campaign (and the current
    apprenticeship offers)."""
    rows = con.execute("""SELECT fili, form_lib_voe_acc, fil_lib_voe_acc, lib_for_voe_ins FROM core.formation_year
                          WHERE session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    out: dict = {}
    for r in [diplome_of(*r) for r in rows] + [(a["diplome"], a["mention"]) for a in apprentissage(con) if not a["rattachee"]]:
        d, m = r
        x = out.setdefault(d, {"n": 0, "mentions": {}})
        x["n"] += 1
        g = x["mentions"].setdefault(groupe_of(d, m), {"n": 0, "variantes": set()})
        g["n"] += 1
        g["variantes"].add(m)
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    # R9: diplomas and mention groups in French alphabetical order; each group lists the published labels it gathers
    return {"session": session, "offre_apprentissage": _offer_session(con), "types": type_diplomes(con),
            "diplomes": [{"label": d, "n": x["n"], "mentions": [{"label": g, "n": v["n"], "variantes": sorted(v["variantes"], key=sort_key)}
                                                                for g, v in sorted(x["mentions"].items(), key=lambda kv: sort_key(kv[0]))]}
                         for d, x in sorted(out.items(), key=lambda kv: sort_key(kv[0]))]}


def _offer_session(con):
    return con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0] if _has_labels(con) else None


_LAYER: dict = {}


def formations(con, diplome: str, mention: str | None = None) -> dict | None:
    """The neutral layer of a type of diploma (and mention group). R10: the whole layer is built once per warehouse and sliced
    (34 answers when no diploma is ticked); each answer gets its own dicts (callers add keys to them)."""
    key = _fingerprint(con)
    if key not in _LAYER:
        _LAYER.clear()
        _LAYER[key] = _layer(con)
    by_dip, session, offre = _LAYER[key]
    out = [dict(x) for x in by_dip.get(diplome, []) if not mention or mention in (x["mention"], x["groupe"])]
    if not out:
        return None
    return {"diplome": diplome, "mention": mention, "session": session, "offre_apprentissage": offre, "formations": out}


# ---- sprint Q3 (owner, 2026-11-13): the whole map layer in ONE compact answer, built and compressed once per warehouse ----
# The map asked 34 answers (one per type of diploma, 22 MB of JSON when nothing is ticked), each re-encoded and re-compressed
# by the server at every call. `couche` serves the same formations, the same keys and values (red team VT1 decodes it and
# compares it with every per-diploma answer), as rows of values under a few key templates, repeated strings sent once.
TOUS = "*"                 # /api/carte/zones?diplome=* : the zones of every type of diploma at once
DICT_KEYS = ("etablissement", "ville", "academie", "contrat_etab", "select_form", "internat", "distance", "formation", "mention",
             "groupe", "statut", "diplome")
_COUCHE: dict = {}


DETAIL_KEYS = ("bacs", "majo", "offres_app", "fiche")   # read by the cards only: sent in a second answer, after the list


def couche(con, mark=None, partie: str = "base") -> dict:
    """{"json": bytes, "gzip": bytes, "etag": str, "n": int} of the whole layer. `mark` = admis.mark (the list label), applied
    as /api/carte/formations applies it. `partie` "base": every key but DETAIL_KEYS (what the list, the map and the filters
    read); "details": for each formation its code and its DETAIL_KEYS present (the cards). base + details = each formation."""
    key = _fingerprint(con)
    if key not in _COUCHE:
        _COUCHE.clear()
        _COUCHE[key] = _couche_build(con, mark)
    return _COUCHE[key][partie]


def _couche_build(con, mark) -> dict:
    import gzip
    import hashlib
    import json
    facs = facets(con)
    parts = {}
    for partie in ("base", "details"):
        parts[partie] = {"strings": [], "sidx": {}, "kinds": [], "kidx": {}, "rows": []}
    session = offre = None
    def enc(P, v, top=False):
        """An object = [-(1 + its key template), values...]; a list = its encoded items; a string of DICT_KEYS (top level)
        = its index in `strings`; anything else as it is."""
        if isinstance(v, dict):
            cols = tuple(v)
            if cols not in P["kidx"]:
                P["kidx"][cols] = len(P["kinds"])
                P["kinds"].append(list(cols))
            out = [-1 - P["kidx"][cols]]
            for c in cols:
                x = v[c]
                if top and c in DICT_KEYS and isinstance(x, str):
                    if x not in P["sidx"]:
                        P["sidx"][x] = len(P["strings"])
                        P["strings"].append(x)
                    out.append(P["sidx"][x])
                else:
                    out.append(enc(P, x))
            return out
        if isinstance(v, list):
            return [enc(P, x) for x in v]
        return v

    for d in [x["label"] for x in facs["diplomes"]]:
        lay = public(formations(con, d))
        if lay is None:
            continue
        session, offre = lay["session"], lay["offre_apprentissage"]
        items = lay["formations"]
        if mark is not None:
            items = mark(con, items, session=lay["session"], only=lambda f: f.get("stats") is not False)
        for f in items:
            f = {**f, "diplome": d}
            pieces = {"base": {k: v for k, v in f.items() if k not in DETAIL_KEYS},
                      "details": {"cod_aff_form": f["cod_aff_form"], **{k: f[k] for k in DETAIL_KEYS if k in f}}}
            for partie, obj in pieces.items():
                P = parts[partie]
                row = enc(P, obj, top=True)
                if dec(row, P["kinds"], P["strings"], top=True) != obj:   # self-check: the page's decoder twin reads it back
                    raise RuntimeError(f"couche: {f.get('cod_aff_form')} does not round-trip")
                P["rows"].append(row)
    out = {}
    for partie, P in parts.items():
        payload = {"partie": partie, "session": session, "offre_apprentissage": offre, "dict_keys": list(DICT_KEYS),
                   "strings": P["strings"], "kinds": P["kinds"], "rows": P["rows"]}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        out[partie] = {"json": raw, "gzip": gzip.compress(raw, 6, mtime=0),
                       "etag": '"' + hashlib.sha256(raw).hexdigest()[:20] + '"', "n": len(P["rows"])}
    return out


def dec(v, kinds: list, strings: list, top: bool = False):
    """The decoder (the page's twin is `coucheDec` in app.js). An encoded object is a list whose first item is a negative
    int; a plain list never starts with one in this layer (the build checks every row round-trips)."""
    if isinstance(v, list):
        if v and isinstance(v[0], int) and not isinstance(v[0], bool) and v[0] < 0:
            cols = kinds[-1 - v[0]]
            return {c: (strings[x] if top and c in DICT_KEYS and isinstance(x, int) and not isinstance(x, bool)
                        else dec(x, kinds, strings)) for c, x in zip(cols, v[1:])}
        return [dec(x, kinds, strings) for x in v]
    return v


def _layer(con) -> tuple:
    rows = con.execute("""
        WITH s AS (SELECT max(session) AS s FROM core.formation_year)
        SELECT f.cod_aff_form, f.g_ea_lib_vx, f.lib_for_voe_ins, f.ville_etab, f.acad_mies, f.lat, f.lon, f.contrat_etab,
               f.select_form, c.internat, c.distance, c.amenag_sport, c.amenag_art, f.taux_acces_ens, r.spe_type_key,
               f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.apprentissage, f.capa_fin, f.acc_pc
        FROM core.formation_year f JOIN s ON f.session = s.s
        LEFT JOIN core.cartographie c ON c.cod_aff_form = f.cod_aff_form
        LEFT JOIN core.taxonomy_link t ON t.cod_aff_form = f.cod_aff_form AND t.session = f.session
        LEFT JOIN core.taxonomy_rule r USING (rule_id)
        ORDER BY f.g_ea_lib_vx, f.cod_aff_form""").fetchall()
    by_dip: dict = {}
    offres = offres_par_formation(con)
    lines = bac_lines(con)                    # R10: rate per bac and most represented line among the admits
    for r in rows:
        d, m = diplome_of(r[15], r[16], r[17], r[2])
        x = dict(zip(FIELDS, r[:15]))
        if x["lat"] is not None:
            x["lat"], x["lon"] = round(x["lat"], 5), round(x["lon"], 5)
        x["mention"], x["groupe"], x["statut"] = m, groupe_of(d, m), statut_of(x["contrat_etab"])
        x["capa_fin"], x["acc_pc"] = r[19], r[20]       # sprint R3: capacity and complementary-phase admits (the map's filters)
        sies_app = bool(r[18])                # SIES's own "en apprentissage" formations (3 in 2025)
        x["stats"], x["fiche"] = True, None
        if sies_app and x["statut"] == "prive":
            x["statut"] = "prive_app"         # free for the apprentice: never the fee-charging rule
        x["payant"] = x["statut"] == "prive"
        x["offres_app"] = offres.get(x["cod_aff_form"], [])
        ln = lines.get(x["cod_aff_form"]) or {}
        x["bacs"], x["majo"] = ln.get("bacs"), ln.get("majo")
        x["initiale"], x["apprentissage"] = not sies_app, sies_app or bool(x["offres_app"])
        by_dip.setdefault(d, []).append(x)
    for a in apprentissage(con):
        if not a["rattachee"]:
            by_dip.setdefault(a["diplome"], []).append({**{k: v for k, v in a.items() if k not in ("diplome", "rattachee")},
                                                        "groupe": groupe_of(a["diplome"], a["mention"]), "initiale": False, "offres_app": []})
    session = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    return by_dip, session, _offer_session(con)


def public(lay: dict | None) -> dict | None:
    """What the page reads (the type key only serves the zones, computed here)."""
    if lay is None:
        return None
    return {**lay, "formations": [{k: v for k, v in f.items() if k != "type_key"} for f in lay["formations"]]}


def type_diplomes(con) -> dict:
    """{type_key of "Mon parcours": its most frequent type of diploma}, for the link from Mon parcours to the map."""
    rows = con.execute("""SELECT r.spe_type_key, f.fili, f.form_lib_voe_acc, f.fil_lib_voe_acc, f.lib_for_voe_ins
        FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
        JOIN core.formation_year f ON f.cod_aff_form = t.cod_aff_form AND f.session = t.session
        WHERE t.session = (SELECT max(session) FROM core.formation_year)""").fetchall()
    count: dict = {}
    for tk, *lab in rows:
        d = diplome_of(*lab)[0]
        count.setdefault(tk, {}).setdefault(d, 0)
        count[tk][d] += 1
    return {tk: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] for tk, c in count.items()}


def zones(con, diplome: str, mention: str | None, dkey: str | None, mention_bac: str, serie: str,
          moyenne: float | None = None, lecture: bool = False) -> dict:
    """{code: zone} for the formations of a diploma (and mention): journey.stage2 on each formation's own type, `only` its
    codes, so every zone is the one "Mon parcours" shows. Formations without a SIES type are read under J.SANS_TYPE (R9)."""
    if diplome == TOUS:          # sprint Q3: every type of diploma in one answer (the map when nothing is ticked)
        items = [f for d in facets(con)["diplomes"] for f in (formations(con, d["label"]) or {"formations": []})["formations"]]
    else:
        lay = formations(con, diplome, mention)
        if lay is None:
            return {"zones": {}}
        items = lay["formations"]
    by_type: dict = {}
    for f in items:
        if f.get("stats", True) is not False:   # R9: a formation with no SIES type is read under J.SANS_TYPE
            by_type.setdefault(f["type_key"] or J.SANS_TYPE, []).append(f["cod_aff_form"])
    out, lec = {}, {}
    cods = [c for cs in by_type.values() for c in cs]
    if not cods:
        return {"zones": {}, **({"lectures": {}} if lecture else {})}
    # sprint Q3: every type of the diploma in one stage-2 query (each row is read from its own lineage, the same row)
    rows = J.stage2(con, dkey, mention_bac, next(iter(by_type)), None, serie=serie, only=cods, moyenne=moyenne,
                    types=list(by_type), limit=len(cods) + 1)["formations"]
    for f in rows:
        out[f["cod_aff_form"]] = f["zone"]
        if lecture:      # R6: what the page needs to read the zone with the average it keeps (journey.stage2's `lec`)
            lec[f["cod_aff_form"]] = {"zone": f["zone"], "uncertain": f["uncertain"], "taux_acces_ens": f["taux_acces_ens"],
                                      "lec": f["lec"]}
    return {"zones": out, **({"lectures": lec} if lecture else {})}


CHIFFRES_MAX = 40          # one page of the map's list (searchPage: 20 on a phone, 40 on a wide screen)


def chiffres(con, codes: list[str], serie: str, dkey: str | None) -> dict:
    """R9 (owner, 2026-11-12): for the formations of one page of the map's list, the figure for the student's doublette
    (bac général): voeux.figures, the function Mes vœux reads, so the map, Mes vœux and the formation page show one figure.
    Bac techno / pro: the report's lines of that bac (`voies`), the page picks the student's line itself (pickVoie): the
    series / specialty is sent only to /api/voeux. No zone, no average here: the page reads those from /api/carte/zones."""
    from . import rapports as RP
    from . import voeux as V
    cods = list(dict.fromkeys(c.strip() for c in codes if c.strip()))
    if len(cods) > CHIFFRES_MAX or any(not re.fullmatch(r"\d{1,9}", c) for c in cods):
        raise ValueError(f"au plus {CHIFFRES_MAX} codes de formation (chiffres)")
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    types = dict(con.execute("""SELECT fy.cod_aff_form, r.spe_type_key FROM core.formation_year fy
        LEFT JOIN core.taxonomy_link t USING (session, cod_aff_form) LEFT JOIN core.taxonomy_rule r USING (rule_id)
        WHERE fy.session = ? AND list_contains(?, fy.cod_aff_form)""", [latest, cods]).fetchall())
    known = [c for c in cods if c in types]
    figs = V.figures(con, known, types, serie=serie, dkey=dkey)
    if serie in ("bt", "bp"):
        for c in known:
            b = RP.for_formation(con, c, textes=False)
            figs[c]["voies"] = None if not b else {"session": b["session"], "recoupe": b["recoupe"],
                                                    "doublettes": {serie: b["doublettes"].get(serie) or []},
                                                    "voie_keys": {serie: (b.get("voie_keys") or {}).get(serie)}}
    return {"session": latest, "serie": serie, "doublette": dkey, "chiffres": figs}
