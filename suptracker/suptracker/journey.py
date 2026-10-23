"""Student profile -> programme positioning: a two-stage hierarchical funnel.

The two SIES sources are never multiplied together (no ecological inference):

Stage 1  national, per macro-filière, from the specialty dataset
         (fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-*):
         counts are *candidates* of the doublette (>=1 vœu / >=1 proposition /
         accepted), so offer rate, lift and destination share are computed
         within that one table.
Stage 2  per formation, from fr-esr-parcoursup: the admitted cohort's mention
         distribution, official taux_acces_ens, bac-général share, scholarship
         share and academic origin, pooled over the formation's 2022-2025
         lineage. Only the macro-filière chosen in Stage 1 links the stages,
         through a deterministic taxonomy table.

Nothing here produces an individual admission probability: every number is
an empirical share of a published cohort.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

import duckdb

# --------------------------------------------------------------------------- specialties
# The 13 Terminale specialties as spelled in the SIES doublette strings. Several
# contain commas, so a doublette is parsed against this vocabulary, never split on ",".
SPECIALTIES: dict[str, str] = {
    "MATHS": "Mathématiques Spécialité",
    "PC": "Physique-Chimie Spécialité",
    "SVT": "Sciences de la vie et de la Terre Spécialité",
    "SES": "Sciences Economiques et Sociales Spécialité",
    "HGGSP": "Histoire-Géographie, Géopolitique et Sciences politiques",
    "LLCER": "Langues, littératures et cultures étrangères et régionales",
    "HLP": "Humanités, Littérature et Philosophie",
    "NSI": "Numérique et Sciences Informatiques",
    "SI": "Sciences de l'ingénieur et sciences physiques",
    "LLCA": "Littérature et langues et cultures de l'Antiquité",
    "EPPCS": "Éducation physique, pratiques et culture sportives",
    "ART": "Art",
    "BIOECO": "Biologie/Ecologie",
}
SPECIALTY_SHORT = {
    "MATHS": "Mathématiques", "PC": "Physique-Chimie", "SVT": "SVT", "SES": "SES", "HGGSP": "HGGSP",
    "LLCER": "LLCER", "HLP": "HLP", "NSI": "NSI", "SI": "Sciences de l'ingénieur", "LLCA": "LLCA",
    "EPPCS": "EPPCS", "ART": "Arts", "BIOECO": "Biologie-écologie",
}
SCIENTIFIC = {"MATHS", "PC", "SVT", "NSI", "SI", "BIOECO"}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).replace("\xa0", " ")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


_SPE_BY_FOLD = sorted(((_fold(v), k) for k, v in SPECIALTIES.items()), key=lambda x: -len(x[0]))


def parse_doublette(label: str | None) -> tuple[str, str] | None:
    """'Mathématiques Spécialité,Sciences Economiques et Sociales Spécialité' -> ('MATHS', 'SES').

    Returns a sorted pair of codes (a doublette is unordered), or None if the label
    is not exactly two known specialties.
    """
    if not label:
        return None
    rest, found = _fold(label), []
    while rest:
        for f, code in _SPE_BY_FOLD:
            if rest == f or rest.startswith(f + " "):
                found.append(code)
                rest = rest[len(f):].strip()
                break
        else:
            return None
    if len(found) != 2:
        return None
    return tuple(sorted(found))  # type: ignore[return-value]


def doublette_key(a: str, b: str) -> str:
    return "+".join(sorted((a.upper(), b.upper())))


def type_key(label: str | None) -> str | None:
    """Normalise SIES formation-type labels across vintages (nbsp, apostrophes, accents)."""
    return _fold(label) if label else None


# --------------------------------------------------------------------------- taxonomy linker
@dataclass(frozen=True)
class Rule:
    spe_type: str          # SIES specialty-dataset formation type (as published)
    fili: str | None       # exact fili, or None for any
    form: str | None = None    # regex on form_lib_voe_acc
    fil: str | None = None     # regex on fil_lib_voe_acc
    quality: str = "exact"     # exact | approx (the SIES grouping is ambiguous for this branch)


# First matching rule wins; order goes from specific to generic.
TAXONOMY_RULES: tuple[Rule, ...] = (
    Rule("PASS", "PASS"),
    Rule("Licence L.AS", "Licence_Las"),
    Rule("CPGE ECG", "CPGE", r"conomique et commerciale", r"^ECG"),
    Rule("CPGE ECG", "CPGE", r"conomique et commerciale", None, "approx"),   # ECT, ENS D1/D2
    Rule("CPGE S", "CPGE", r"scientifique"),
    Rule("CPGE L", "CPGE", r"litt[ée]raire"),
    Rule("BUT Service", "BUT", r"Service"),
    Rule("BUT Production", "BUT", r"Production"),
    Rule("BTS Agricole", "BTS", r"Agricole"),
    Rule("BTS Service", "BTS", r"Services?"),
    Rule("BTS Production", "BTS", r"Production"),
    Rule("Ecoles d'ingénieurs", "Ecole d'Ingénieur"),
    Rule("Ecoles de Commerce", "Ecole de Commerce"),
    Rule("D.E sanitaire", None, r"D\.E secteur sanitaire"),
    Rule("D.E  social", None, r"D\.E secteur social"),
    Rule("DCG", None, r"^DCG$"),
    Rule("DEUST", None, r"^DEUST$"),
    Rule("CUPGE", None, r"^CUPGE"),
    Rule("Sciences po", "Autre formation", r"^Sciences politiques$"),
    Rule("Formations d'ART", "Autre formation", r"DN MADE|Diplôme National d'Art|écoles supérieures d'art"),
    Rule("Formations des écoles nationales vétérinaires", None, r"vétérinaires"),
    # Licences: the discipline is in fil_lib_voe_acc
    Rule("Licence STAPS", "Licence", None, r"Activités Physiques et Sportives"),
    Rule("Licence STAPS", "Licence", r"STAPS"),
    Rule("Licence Sciences juridiques", "Licence", None, r"^Droit$|^Droit français"),
    Rule("Licence Pluri Sciences économiques - Gestion", "Licence", None, r"^Economie et gestion$"),
    Rule("Licence Sciences économiques", "Licence", None, r"^(Economie|Économie)$"),
    Rule("Licence Sciences de gestion", "Licence", None, r"^Gestion$"),
    Rule("Licence AES", "Licence", None, r"^Administration économique et sociale$"),
    Rule("Licence Pluri Droit - Sciences éco - AES", "Licence", None,
         r"^Droit, |^Administration (et Echanges internationaux|publique)$|^Économie, Science politique$", "approx"),
    Rule("Licence Sciences politiques", "Licence", None, r"^Science politique$"),
    Rule("Licence MASS", "Licence", None, r"^Mathématiques et informatique appliquées aux sciences humaines"),
    Rule("Licence Mathématiques", "Licence", None, r"^Mathématiques$"),
    Rule("Licence Mathématiques et informatique", "Licence", None,
         r"^Informatique, Mathématiques$|^Mathématiques, physique, chimie, informatique$", "approx"),
    Rule("Licence Informatique", "Licence", None, r"^Informatique$"),
    Rule("Licence Physique et chimie", "Licence", None, r"^Physique, chimie$"),
    Rule("Licence Physique", "Licence", None, r"^Physique$"),
    Rule("Licence Chimie", "Licence", None, r"^Chimie$"),
    Rule("Licence Sciences de la vie, biologie, santé", "Licence", None,
         r"^Sciences de la vie$|^Sciences biomédicales$|^Sciences pour la santé$"),
    Rule("Licence Pluri Sciences de la vie, de la santé, de la terre et de l univers", "Licence", None,
         r"^Sciences de la vie et de la terre$"),
    Rule("Licence Sciences de l univers, de la terre, de l espace", "Licence", None, r"^Sciences de la (terre|Terre)"),
    Rule("Licence Formation générale aux métiers de l ingénieur", "Licence", None, r"^Sciences pour l'ingénieur$"),
    Rule("Licence Mécanique, Génie mécanique, Ingénierie mécanique", "Licence", None, r"^Mécanique$"),
    Rule("Licence Génie civil", "Licence", None, r"^Génie civil$"),
    Rule("Licence Electronique, Génie électrique, EEA", "Licence", None, r"^Electronique"),
    Rule("Licence Pluri Sciences", "Licence", None, r"^Sciences et technologies$", "approx"),
    Rule("Licence Histoire", "Licence", None, r"^Histoire$"),
    Rule("Licence Géographie", "Licence", None, r"^Géographie"),
    Rule("Licence Psychlogie, Sciences cognitives", "Licence", None, r"^Psychologie$|^Sciences cognitives$"),
    Rule("Licence Sociologie, Démographie", "Licence", None, r"^Sociologie$"),
    Rule("Licence Philosophie, Epistémologie", "Licence", None, r"^Philosophie$"),
    Rule("Licence Sciences de l éducation", "Licence", None, r"^Sciences de l'éducation"),
    Rule("Licence Sciences de l information et de la communication", "Licence", None, r"^Information et communication$"),
    Rule("Licence Sciences du langage - Linguistique", "Licence", None, r"^Sciences du langage$"),
    Rule("Licence Archéologie, Ethno, Préhistoire, Anthropologie", "Licence", None,
         r"archéologie|Anthropologie", "approx"),
    Rule("Licence Sciences religieuses", "Licence", None, r"^Théologie"),
    Rule("Licence LEA", "Licence", None, r"^Langues étrangères appliquées$"),
    Rule("Licence Langues et littératures étrangères", "Licence", None, r"^Langues, littératures et civilisations"),
    Rule("Licence Langues et littératures françaises", "Licence", None, r"^Lettres$"),
    Rule("Licence Arts", "Licence", None, r"^Arts|^Musicologie$|^Cinéma|^Etudes théâtrales$"),
    Rule("Licence Pluri Sciences humaines et sociales", "Licence", None, r"^Sciences sociales$", "approx"),
    Rule("Licence Pluri Lettres - Langues - Sciences humaines", "Licence", None, r"^Humanités$", "approx"),
)


def build_taxonomy_link(con: duckdb.DuckDBPyConnection) -> None:
    """core.taxonomy_link: one row per (session, cod_aff_form) -> SIES specialty-dataset type."""
    cases = []
    for i, r in enumerate(TAXONOMY_RULES):
        cond = ["TRUE"]
        if r.fili is not None:
            cond.append(f"fili = '{r.fili.replace(chr(39), chr(39) * 2)}'")
        if r.form:
            cond.append(f"regexp_matches(form_lib_voe_acc, '{r.form.replace(chr(39), chr(39) * 2)}')")
        if r.fil:
            cond.append(f"regexp_matches(fil_lib_voe_acc, '{r.fil.replace(chr(39), chr(39) * 2)}')")
        cases.append(f"WHEN {' AND '.join(cond)} THEN {i}")
    con.execute(f"""
    CREATE OR REPLACE TABLE core.taxonomy_link AS
    SELECT session, cod_aff_form, rule_id FROM (
      SELECT session, cod_aff_form, CASE {' '.join(cases)} END AS rule_id FROM core.formation_year)
    WHERE rule_id IS NOT NULL""")
    con.execute("CREATE OR REPLACE TABLE core.taxonomy_rule (rule_id INT, spe_type VARCHAR, spe_type_key VARCHAR,"
                " fili VARCHAR, form_regex VARCHAR, fil_regex VARCHAR, quality VARCHAR)")
    con.executemany("INSERT INTO core.taxonomy_rule VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(i, r.spe_type, type_key(r.spe_type), r.fili, r.form, r.fil, r.quality)
                     for i, r in enumerate(TAXONOMY_RULES)])


# --------------------------------------------------------------------------- group-label parser
_SPE_PATTERNS = {
    "MATHS": r"\bmath", "PC": r"physique[- ]?chimie|\bpc\b", "SVT": r"\bsvt\b|sciences de la vie",
    "SES": r"\bses\b|sciences [ée]conomiques et sociales", "NSI": r"\bnsi\b|num[ée]rique et sciences",
    "SI": r"sciences de l.ing[ée]nieur|\bsi\b", "HGGSP": r"\bhggsp\b|g[ée]opolitique",
    "HLP": r"\bhlp\b|humanit[ée]s", "LLCER": r"\bllcer\b|langues, litt", "BIOECO": r"biologie.?[ée]cologie",
}


def group_applies(label: str | None, spe: tuple[str, str] | None, sex: str | None = None) -> bool | None:
    """Does a Parcoursup calling group (lib_grp*) apply to a *bac général* student?

    True / False when the label decides it, None when it depends on information we do
    not have (e.g. a gender-specific group without a sex input). Specialty-split labels
    ("... spécialité Maths + une spécialité non scientifique") are matched against the
    student's doublette. The 2022-2025 SIES exports contain no specialty-split label,
    so on real data this reduces to the series rules.
    """
    if not label:
        return None
    s = _fold(label)
    named = {c for c, p in _SPE_PATTERNS.items() if re.search(p, label.lower())}
    if "specialit" in s and (named or "non scientifique" in s or "scientifique" in s):
        if spe is None:
            return None
        have = set(spe)
        if " ou " in f" {s} ":                      # "spécialité Maths ou NSI": any one suffices
            return bool(named & have)
        if not named <= have:                       # every named specialty is required
            return False
        rest = have - named
        if "non scientifique" in s:                 # "... + une spécialité non scientifique"
            return bool(rest) and not (rest & SCIENTIFIC)
        if re.search(r"une specialite scientifique|\bscientifique\b", s):
            return bool(rest & SCIENTIFIC) if rest else bool(have & SCIENTIFIC)
        return True
    if re.search(r"sauf les bac (technologiques|professionnels)", s):
        return True                       # excludes techno/pro only
    if re.search(r"^bacheliers (technologiques|professionnels)|^sti2d$|^st2s$|^stmg$", s):
        return False
    if re.search(r"^bacheliers generaux|^bac general|serie generale", s):
        return True
    if re.search(r"voie d acces cep|cep$", s):
        return False                      # Conventions éducation prioritaire: separate track
    if re.search(r"^tous les candidats|groupe par defaut|voie d acces generale", s):
        return True
    if re.search(r"^toutes les filles$", s):
        return None if sex is None else sex == "F"
    if re.search(r"^tous les garcons$", s):
        return None if sex is None else sex == "M"
    if s == "autres candidats":
        return None                       # resolved per formation: the residual group
    return None


def open_to_general(row: dict, spe: tuple[str, str] | None) -> bool | None:
    """False when every published calling group excludes bac général (e.g. CPGE ECT, which
    only ranks bacheliers technologiques); None when the groups do not decide it."""
    verdicts = [group_applies(row.get(f"lib_grp{i}"), spe) for i in (1, 2, 3) if row.get(f"lib_grp{i}")]
    if not verdicts:
        return None
    if any(v is True for v in verdicts):
        return True
    if all(v is False for v in verdicts):
        return False
    return None


def student_group(row: dict, spe: tuple[str, str] | None, sex: str | None = None) -> dict | None:
    """Pick the calling group a bac-général student falls in, with its last-called rank."""
    groups = [(i, row.get(f"lib_grp{i}"), row.get(f"ran_grp{i}")) for i in (1, 2, 3) if row.get(f"lib_grp{i}")]
    if not groups:
        return None
    verdicts = [(i, lib, ran, group_applies(lib, spe, sex)) for i, lib, ran in groups]
    hits = [v for v in verdicts if v[3] is True]
    if not hits:  # "Autres candidats" is the residual group when no explicit group fits
        hits = [v for v in verdicts if v[3] is None and _fold(v[1]) == "autres candidats"]
    if len(hits) != 1:
        return {"group": None, "ambiguous": True, "labels": [g[1] for g in groups]}
    i, lib, ran, _ = hits[0]
    specialty_split = "specialit" in _fold(lib)
    return {"group": i, "label": lib, "last_called_rank": ran, "specialty_split": specialty_split,
            "ambiguous": False}


# --------------------------------------------------------------------------- statistics
MENTIONS = ("sansmention", "ab", "b", "tb", "tbf")      # ordered ladder; "non renseignée" excluded
MENTION_LABEL = {"sansmention": "Sans mention", "ab": "Assez bien", "b": "Bien", "tb": "Très bien",
                 "tbf": "Très bien avec félicitations"}


def wilson(k: float, n: float, z: float = 1.959964) -> tuple[float | None, float | None]:
    """95% Wilson score interval for a binomial share k/n."""
    if not n:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


# Portfolio zones (thresholds are part of the method and shown in the UI).
ZONE_RULES = {
    "hors_profil_cdf": 0.02,     # < 2% of admits hold the expected mention or lower
    "ambitieux_access": 30.0,    # taux d'accès < 30 %
    "ambitieux_cdf": 0.15,       # expected mention in the bottom 15 % of the admitted cohort
    "securite_access": 70.0,     # taux d'accès >= 70 %
    "securite_cdf": 0.50,        # >= half the admits at or below the expected mention
}


def _zone(taux: float, cdf: float) -> str:
    z = ZONE_RULES
    if cdf < z["hors_profil_cdf"]:
        return "hors_profil"
    if taux < z["ambitieux_access"] or cdf < z["ambitieux_cdf"]:
        return "ambitieux"
    if taux >= z["securite_access"] and cdf >= z["securite_cdf"]:
        return "securite"
    return "cible"


def classify_zone(taux: float | None, cdf: float | None, lo: float | None, hi: float | None) -> dict:
    """Zone from the point estimate; 'uncertain' when another value inside the 95 % Wilson
    interval of the CDF would put the formation in a different zone."""
    if cdf is None or taux is None:
        return {"zone": "indetermine", "uncertain": True}
    zone = _zone(taux, cdf)
    probes = [v for v in (lo, hi) if v is not None]
    probes += [c for c in (ZONE_RULES["hors_profil_cdf"], ZONE_RULES["ambitieux_cdf"], ZONE_RULES["securite_cdf"])
               if lo is not None and hi is not None and lo <= c <= hi]
    uncertain = any(_zone(taux, v) != zone for v in probes)
    return {"zone": zone, "uncertain": uncertain}


# Below this share of bacheliers généraux among 2022-2025 admits, a formation is treated as
# closed to bac général in practice, whatever its group labels say.
MIN_GENERAL_SHARE = 0.05

# Stage-1 gates
GATE_RULES = {"atypique_share": 0.02, "predilection_lift": 1.5, "min_candidates": 100}


def classify_gate(share: float | None, lift: float | None, rel_offer: float | None, n_cand: float | None) -> str:
    g = GATE_RULES
    if not n_cand or n_cand < g["min_candidates"]:
        return "insuffisant"
    if share is None or share < g["atypique_share"]:
        return "atypique"
    if lift is not None and lift >= g["predilection_lift"] and rel_offer is not None and rel_offer >= 1.0:
        return "predilection"
    return "accessible"


# --------------------------------------------------------------------------- build (materialised tables)
NATIONAL_TYPE = type_key("Ensemble des bacheliers")


def build_journey(con: duckdb.DuckDBPyConnection) -> None:
    """Materialise the journey layer: taxonomy link + doublette-level specialty facts."""
    build_taxonomy_link(con)
    rows = con.execute("SELECT DISTINCT doublette FROM core.specialites WHERE doublette IS NOT NULL").fetchall()
    con.execute("CREATE OR REPLACE TABLE core.spe_doublette (doublette VARCHAR, spe1 VARCHAR, spe2 VARCHAR,"
                " doublette_key VARCHAR)")
    parsed = [(d, *p, doublette_key(*p)) for (d,) in rows if (p := parse_doublette(d))]
    if parsed:
        con.executemany("INSERT INTO core.spe_doublette VALUES (?, ?, ?, ?)", parsed)
    # Read aggregation levels 0-1 only (the 2025 level-2 rows repeat level-1 totals). Rows of
    # the same unordered pair published in both orders are disjoint candidate groups: summing
    # them is a union, not a double count. Nothing is ever summed across formation types.
    labels = con.execute("""SELECT formation_type FROM core.specialites WHERE formation_type IS NOT NULL
                            GROUP BY 1 ORDER BY max(session)""").fetchall()
    con.execute("CREATE OR REPLACE TEMP TABLE _type_key (formation_type VARCHAR, type_key VARCHAR)")
    con.executemany("INSERT INTO _type_key VALUES (?, ?)", [(l, type_key(l)) for (l,) in labels])
    con.execute("""
    CREATE OR REPLACE TABLE mart.spe_filiere AS
    SELECT s.session, k.type_key, any_value(s.formation_type ORDER BY s.formation_type) AS type_label,
           d.doublette_key, sum(s.n_voeux) AS voeux, sum(s.n_proposition) AS propositions,
           sum(s.n_accepte) AS acceptations
    FROM core.specialites s
    JOIN _type_key k USING (formation_type)
    JOIN core.spe_doublette d USING (doublette)
    WHERE coalesce(s.aggregation_level, '1') IN ('0', '1')
    GROUP BY ALL""")


# --------------------------------------------------------------------------- stage 1
def stage1(con, dkey: str) -> dict:
    nat = NATIONAL_TYPE
    rows = con.execute(f"""
    WITH f AS (
      SELECT type_key, session,
             sum(voeux) FILTER (WHERE doublette_key = $d) AS v_d,
             sum(propositions) FILTER (WHERE doublette_key = $d) AS p_d,
             sum(acceptations) FILTER (WHERE doublette_key = $d) AS a_d,
             sum(voeux) AS v_all, sum(propositions) AS p_all, sum(acceptations) AS a_all
      FROM mart.spe_filiere GROUP BY ALL),
    pooled AS (
      SELECT type_key, count(DISTINCT session) AS years, sum(v_d) v_d, sum(p_d) p_d, sum(a_d) a_d,
             sum(v_all) v_all, sum(p_all) p_all, sum(a_all) a_all,
             list({{'session': session, 'offer_rate': p_d / nullif(v_d, 0), 'share': a_d / nullif(a_all, 0),
                   'candidates': v_d}} ORDER BY session) AS trend
      FROM f GROUP BY 1),
    n AS (SELECT a_d AS nat_a_d, a_all AS nat_a_all, v_d AS nat_v_d, p_d AS nat_p_d FROM pooled WHERE type_key = '{nat}')
    SELECT p.type_key, (SELECT any_value(type_label ORDER BY session DESC) FROM mart.spe_filiere m
                        WHERE m.type_key = p.type_key) AS label,
           p.years, p.v_d, p.p_d, p.a_d, p.a_all,
           p.p_d / nullif(p.v_d, 0) AS offer_rate,
           p.p_all / nullif(p.v_all, 0) AS offer_rate_all,
           p.a_d / nullif(p.a_all, 0) AS share,
           (p.a_d / nullif(p.a_all, 0)) / nullif(n.nat_a_d / nullif(n.nat_a_all, 0), 0) AS lift,
           p.a_d / nullif(n.nat_a_d, 0) AS destination_share,
           p.trend, n.nat_a_d, n.nat_a_all, n.nat_v_d, n.nat_p_d
    FROM pooled p, n
    ORDER BY destination_share DESC NULLS LAST""", {"d": dkey}).fetchall()
    linked = dict(con.execute("""SELECT r.spe_type_key, count(*) FROM core.taxonomy_link t
        JOIN core.taxonomy_rule r USING (rule_id)
        WHERE t.session = (SELECT max(session) FROM core.formation_year) GROUP BY 1""").fetchall())
    cols = ["type_key", "label", "years", "candidates", "offered", "accepted", "accepted_all", "offer_rate",
            "offer_rate_all", "share", "lift", "destination_share", "trend", "nat_a_d", "nat_a_all",
            "nat_v_d", "nat_p_d"]
    out, national = [], None
    for r in rows:
        x = dict(zip(cols, r))
        x["relative_offer"] = (x["offer_rate"] / x["offer_rate_all"]) if x["offer_rate"] is not None and x["offer_rate_all"] else None
        if x["type_key"] == nat:
            national = {"candidates": x["nat_v_d"], "offered": x["nat_p_d"], "accepted": x["nat_a_d"],
                        "accepted_all": x["nat_a_all"],
                        "national_share": (x["nat_a_d"] / x["nat_a_all"]) if x["nat_a_d"] is not None and x["nat_a_all"] else None,
                        "offer_rate": x["offer_rate"], "years": x["years"]}
            continue
        x["gate"] = classify_gate(x["share"], x["lift"], x["relative_offer"], x["candidates"])
        x["n_formations"] = linked.get(x["type_key"], 0)
        for k in ("nat_a_d", "nat_a_all", "nat_v_d", "nat_p_d"):
            x.pop(k)
        out.append(x)
    return {"doublette": dkey, "national": national, "filieres": out}


# --------------------------------------------------------------------------- stage 2
def stage2(con, dkey: str, mention: str, type_key_: str, academie: str | None = None,
           sex: str | None = None, limit: int = 4000) -> dict:
    if mention not in MENTIONS[:4]:
        raise ValueError(f"mention must be one of {MENTIONS[:4]}")
    upto = MENTIONS[: MENTIONS.index(mention) + 1]
    known = " + ".join(f"coalesce(fy.acc_{m}, 0)" for m in MENTIONS)
    cum = " + ".join(f"coalesce(fy.acc_{m}, 0)" for m in upto)
    spe = tuple(dkey.split("+")) if dkey else None
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    rows = con.execute(f"""
    WITH target AS (
      SELECT l.lineage_id, fy.*
      FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
      JOIN core.formation_year fy USING (session, cod_aff_form)
      JOIN core.lineage l USING (session, cod_aff_form)
      WHERE t.session = $latest AND r.spe_type_key = $type),
    hist AS (
      SELECT l.lineage_id,
             sum({known}) AS n_known, sum({cum}) AS k_cum, sum(coalesce(fy.acc_{mention}, 0)) AS k_exact,
             sum(fy.acc_neobac) AS neobac, sum(fy.acc_bg) AS bg, sum(fy.acc_brs) AS brs,
             count(*) AS years,
             list({{'session': fy.session, 'taux_acces_ens': fy.taux_acces_ens,
                   'cdf': ({cum}) / nullif({known}, 0), 'acc_tot': fy.acc_tot}} ORDER BY fy.session) AS trend
      FROM core.lineage l JOIN core.formation_year fy USING (session, cod_aff_form)
      WHERE l.lineage_id IN (SELECT lineage_id FROM target) GROUP BY 1)
    SELECT t.cod_aff_form, t.g_ea_lib_vx, t.ville_etab, t.acad_mies, t.fil_lib_voe_acc, t.lib_comp_voe_ins,
           t.select_form, t.taux_acces_ens, t.acc_bg, t.acc_neobac, t.pct_aca_orig, t.lat, t.lon, t.fiche_url,
           t.lib_grp1, t.ran_grp1, t.lib_grp2, t.ran_grp2, t.lib_grp3, t.ran_grp3, t.subwish_flag,
           h.n_known, h.k_cum, h.k_exact, h.neobac, h.bg, h.brs, h.years, h.trend
    FROM target t JOIN hist h USING (lineage_id)
    ORDER BY t.taux_acces_ens NULLS LAST LIMIT {int(limit)}""", {"latest": latest, "type": type_key_}).fetchall()
    cols = ["cod_aff_form", "etablissement", "ville", "academie", "filiere", "complement", "select_form",
            "taux_acces_ens", "acc_bg_latest", "acc_neobac_latest", "pct_aca_orig", "lat", "lon", "fiche_url",
            "lib_grp1", "ran_grp1", "lib_grp2", "ran_grp2", "lib_grp3", "ran_grp3", "subwish_flag",
            "n_known", "k_cum", "k_exact", "neobac", "bg", "brs", "years", "trend"]
    out = []
    for r in rows:
        x = dict(zip(cols, r))
        n, k = x["n_known"] or 0, x["k_cum"] or 0
        cdf = k / n if n else None
        lo, hi = wilson(k, n)
        eligible = open_to_general(x, spe)
        pct_bg = (x["bg"] / x["neobac"]) if x["neobac"] else None
        if eligible is not False and pct_bg is not None and pct_bg < MIN_GENERAL_SHARE:
            eligible = False   # e.g. CPGE ECT: groups say "Tous les candidats", admits are ~0 % bac général
        x.update({
            "open_to_general": eligible,
            "cdf": cdf, "cdf_ci": [lo, hi], "exact_share": (x["k_exact"] / n) if n else None,
            "pct_bg": pct_bg,
            "pct_boursiers": (x["brs"] / x["neobac"]) if x["neobac"] else None,
            "small_cohort": (x["acc_bg_latest"] or 0) < 10,
            # mentions are published for all néo-bacheliers, not by series: flag cohorts that are
            # mostly technological/professional, where the CDF says little about bac général peers
            "limited_comparability": x["neobac"] and (x["bg"] or 0) / x["neobac"] < 0.5,
            "home_academie": bool(academie) and x["academie"] == academie,
            "non_selective": x["select_form"] == "formation non sélective",
            **(classify_zone(x["taux_acces_ens"], cdf, lo, hi) if eligible is not False
               else {"zone": "non_ouvert", "uncertain": False}),
            "group": student_group(x, spe, sex),
        })
        for g in (1, 2, 3):
            x.pop(f"lib_grp{g}"), x.pop(f"ran_grp{g}")
        out.append(x)
    return {"doublette": dkey, "mention": mention, "type_key": type_key_, "session": latest,
            "zone_rules": ZONE_RULES, "formations": out}
