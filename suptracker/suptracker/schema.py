"""Canonical analytical schema and the alias table that reconciles SIES vintages.

Every canonical field lists the upstream column names it may appear under, in
priority order. Matching is done on a normalised form (lower-case, accents
stripped, non-alphanumerics -> "_"), so "ACC_TOT", "acc-tot" and "acc_tot" all
resolve. A field that resolves to nothing becomes NULL *and* is written to
meta.schema_audit; nothing is dropped silently.

The funnel stage of each count is recorded so the UI and API can refuse to mix
stages (e.g. never divide prop_tot by voe_tot).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str                 # DuckDB type: VARCHAR | BIGINT | DOUBLE | GEO
    aliases: tuple[str, ...] = ()
    stage: str | None = None   # candidates | ranked_offered | admitted | indicator
    label: str = ""

    @property
    def candidates(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


def F(name, dtype, *aliases, stage=None, label=""):
    return Field(name, dtype, tuple(aliases), stage, label)


VOEUX_FIELDS: tuple[Field, ...] = (
    # --- identifiers & taxonomy -------------------------------------------------
    F("session", "BIGINT", "annee", label="Session Parcoursup"),
    F("cod_uai", "VARCHAR", "uai", "code_uai", label="Code UAI de l'établissement"),
    F("cod_aff_form", "VARCHAR", "g_ta_cod", "code_aff_form", label="Code d'affectation de la formation"),
    F("g_ea_lib_vx", "VARCHAR", "etablissement", "lib_etab", label="Établissement"),
    F("contrat_etab", "VARCHAR", "statut_etab", label="Statut de l'établissement"),
    # Paysage identifiers (MESR establishment register), published by SIES on every campaign: the
    # parent establishment (the university of a UFR or an antenna) and the component.
    F("etablissement_id_paysage", "VARCHAR", label="Identifiant Paysage de l'établissement de rattachement"),
    F("composante_id_paysage", "VARCHAR", label="Identifiant Paysage de la composante"),
    F("dep", "VARCHAR", "code_departemental", label="Département"),
    F("dep_lib", "VARCHAR", label="Département (libellé)"),
    F("region_etab_aff", "VARCHAR", "region", label="Région"),
    F("acad_mies", "VARCHAR", "academie", label="Académie"),
    F("ville_etab", "VARCHAR", "commune", label="Commune"),
    F("select_form", "VARCHAR", "selectivite", label="Sélectivité"),
    F("fili", "VARCHAR", "filiere_agregee", label="Filière de formation très agrégée"),
    F("form_lib_voe_acc", "VARCHAR", label="Filière de formation"),
    F("fil_lib_voe_acc", "VARCHAR", label="Filière de formation détaillée"),
    F("lib_for_voe_ins", "VARCHAR", label="Libellé de la formation (vœu)"),
    F("lib_comp_voe_ins", "VARCHAR", label="Libellé complémentaire"),
    F("detail_forma", "VARCHAR", "detail_forma2", label="Détail de la formation"),
    F("lien_form_psup", "VARCHAR", "lien_form", label="Lien Parcoursup"),
    F("g_olocalisation_des_formations", "GEO", "geo_point_2d", "coordonnees_gps", label="Coordonnées"),
    # --- stage 1: candidates (vœux) --------------------------------------------
    F("capa_fin", "BIGINT", "capacite", label="Capacité"),
    F("voe_tot", "BIGINT", stage="candidates", label="Vœux confirmés (toutes phases)"),
    F("voe_tot_f", "BIGINT", stage="candidates", label="dont candidates"),
    F("nb_voe_pp", "BIGINT", stage="candidates", label="Vœux en phase principale"),
    F("nb_voe_pc", "BIGINT", stage="candidates", label="Vœux en phase complémentaire"),
    # --- stage 2: ranked & offered ---------------------------------------------
    F("nb_cla_pp", "BIGINT", stage="ranked_offered", label="Candidats classés (PP)"),
    F("nb_cla_pc", "BIGINT", stage="ranked_offered", label="Candidats classés (PC)"),
    F("prop_tot", "BIGINT", stage="ranked_offered", label="Candidats ayant reçu une proposition"),
    F("ran_grp1", "BIGINT", stage="ranked_offered", label="Rang du dernier appelé, groupe 1"),
    F("ran_grp2", "BIGINT", stage="ranked_offered", label="Rang du dernier appelé, groupe 2"),
    F("ran_grp3", "BIGINT", stage="ranked_offered", label="Rang du dernier appelé, groupe 3"),
    F("lib_grp1", "VARCHAR", label="Groupe 1"),
    F("lib_grp2", "VARCHAR", label="Groupe 2"),
    F("lib_grp3", "VARCHAR", label="Groupe 3"),
    # --- stage 3: final admitted cohort ----------------------------------------
    F("acc_tot", "BIGINT", stage="admitted", label="Admis (total)"),
    F("acc_tot_f", "BIGINT", stage="admitted", label="Admises"),
    F("acc_pp", "BIGINT", stage="admitted", label="Admis en phase principale"),
    F("acc_pc", "BIGINT", stage="admitted", label="Admis en phase complémentaire"),
    F("acc_term", "BIGINT", stage="admitted", label="Admis issus de terminale"),
    F("acc_term_f", "BIGINT", stage="admitted", label="Admises issues de terminale"),
    F("acc_neobac", "BIGINT", stage="admitted", label="Admis néo-bacheliers"),
    F("acc_brs", "BIGINT", stage="admitted", label="Admis boursiers"),
    F("acc_bg", "BIGINT", stage="admitted", label="Admis bac général"),
    F("acc_bt", "BIGINT", stage="admitted", label="Admis bac technologique"),
    F("acc_bp", "BIGINT", stage="admitted", label="Admis bac professionnel"),
    F("acc_at", "BIGINT", stage="admitted", label="Admis autres candidats"),
    F("acc_mention_non_renseignee", "BIGINT", "acc_mention_nonrenseignee", "acc_mention_nr",
      stage="admitted", label="Mention non renseignée"),
    F("acc_sansmention", "BIGINT", "acc_sans_mention", stage="admitted", label="Sans mention"),
    F("acc_ab", "BIGINT", stage="admitted", label="Mention Assez bien"),
    F("acc_b", "BIGINT", stage="admitted", label="Mention Bien"),
    F("acc_tb", "BIGINT", stage="admitted", label="Mention Très bien"),
    F("acc_tbf", "BIGINT", stage="admitted", label="Très bien avec félicitations"),
    F("acc_aca_orig", "BIGINT", stage="admitted", label="Admis de la même académie"),
    F("acc_internat", "BIGINT", stage="admitted", label="Admis en internat"),
    # admits with a mention (any: AB, B, TB, TBF) by bac series; SIES publishes no mention x series table
    F("acc_bg_mention", "BIGINT", stage="admitted", label="Admis bac général avec mention"),
    F("acc_bt_mention", "BIGINT", stage="admitted", label="Admis bac technologique avec mention"),
    F("acc_bp_mention", "BIGINT", stage="admitted", label="Admis bac professionnel avec mention"),
    # B4: candidates and proposals by bac series (néo-bacheliers). nb_voe_* count candidates of the
    # formation (one per candidate and formation); prop_tot_* are proposals over all phases
    F("nb_voe_pp_bg", "BIGINT", stage="candidates", label="Candidats bac général (phase principale)"),
    F("nb_voe_pp_bt", "BIGINT", stage="candidates", label="Candidats bac technologique (phase principale)"),
    F("nb_voe_pp_bp", "BIGINT", stage="candidates", label="Candidats bac professionnel (phase principale)"),
    F("nb_voe_pc_bg", "BIGINT", stage="candidates", label="Candidats bac général (phase complémentaire)"),
    F("nb_voe_pc_bt", "BIGINT", stage="candidates", label="Candidats bac technologique (phase complémentaire)"),
    F("nb_voe_pc_bp", "BIGINT", stage="candidates", label="Candidats bac professionnel (phase complémentaire)"),
    F("prop_tot_bg", "BIGINT", stage="ranked_offered", label="Bac général ayant reçu une proposition"),
    F("prop_tot_bt", "BIGINT", stage="ranked_offered", label="Bac technologique ayant reçu une proposition"),
    F("prop_tot_bp", "BIGINT", stage="ranked_offered", label="Bac professionnel ayant reçu une proposition"),
    # offer timing (cumulative): proposal received at the opening of the main phase, before the
    # baccalauréat results, before the end of the main phase
    F("acc_debutpp", "BIGINT", stage="admitted",
      label="Admis ayant reçu leur proposition à l'ouverture de la phase principale"),
    F("acc_datebac", "BIGINT", stage="admitted", label="Admis ayant reçu leur proposition avant le bac"),
    F("acc_finpp", "BIGINT", stage="admitted",
      label="Admis ayant reçu leur proposition avant la fin de la phase principale"),
    F("nb_voe_pp_internat", "BIGINT", stage="candidates", label="Candidatures en phase principale avec internat"),
    F("nb_cla_pp_internat", "BIGINT", stage="ranked_offered", label="Classés en phase principale avec internat"),
    # --- official SIES pre-computed shares / indicators ------------------------
    F("pct_f", "DOUBLE", stage="indicator", label="% d'admises"),
    F("pct_bours", "DOUBLE", "pct_brs", stage="indicator", label="% de boursiers (néo-bacheliers)"),
    F("pct_aca_orig", "DOUBLE", stage="indicator", label="% admis de la même académie"),
    F("pct_etab_orig", "DOUBLE", stage="indicator", label="% admis du même établissement"),
    F("pct_neobac", "DOUBLE", stage="indicator", label="% néo-bacheliers"),
    F("pct_bg", "DOUBLE", stage="indicator", label="% bac général"),
    F("pct_bt", "DOUBLE", stage="indicator", label="% bac technologique"),
    F("pct_bp", "DOUBLE", stage="indicator", label="% bac professionnel"),
    F("pct_mention_non_renseignee", "DOUBLE", "pct_mention_nonrenseignee", stage="indicator",
      label="% mention non renseignée"),
    F("pct_sansmention", "DOUBLE", "pct_sans_mention", stage="indicator", label="% sans mention"),
    F("pct_ab", "DOUBLE", stage="indicator", label="% Assez bien"),
    F("pct_b", "DOUBLE", stage="indicator", label="% Bien"),
    F("pct_tb", "DOUBLE", stage="indicator", label="% Très bien"),
    F("pct_tbf", "DOUBLE", stage="indicator", label="% Très bien félicitations"),
    # careful: SIES divides by all néo-bacheliers admitted (acc_neobac), not by acc_bg
    F("pct_bg_mention", "DOUBLE", stage="indicator",
      label="% d'admis bacheliers généraux avec mention, sur l'ensemble des néo-bacheliers admis"),
    F("pct_acc_debutpp", "DOUBLE", stage="indicator",
      label="% d'admis ayant reçu leur proposition à l'ouverture de la phase principale"),
    F("pct_acc_datebac", "DOUBLE", stage="indicator", label="% d'admis ayant reçu leur proposition avant le bac"),
    F("pct_acc_finpp", "DOUBLE", stage="indicator",
      label="% d'admis ayant reçu leur proposition avant la fin de la phase principale"),
    F("taux_acces_ens", "DOUBLE", "taux_acces", stage="indicator",
      label="Taux d'accès (phase principale)"),
    F("part_terminale_generale_en_position_admis_pp", "DOUBLE", "part_acces_gen", stage="indicator",
      label="Part des terminales générales parmi les candidats en position de recevoir une proposition (PP)"),
    F("part_terminale_techno_en_position_admis_pp", "DOUBLE", "part_acces_tec", stage="indicator",
      label="Part des terminales technologiques parmi les candidats en position de recevoir une proposition (PP)"),
    F("part_terminale_pro_en_position_admis_pp", "DOUBLE", "part_acces_pro", stage="indicator",
      label="Part des terminales professionnelles parmi les candidats en position de recevoir une proposition (PP)"),
)

SERIES_FIELDS = ("acc_bg", "acc_bt", "acc_bp")
MENTION_FIELDS = (
    "acc_sansmention", "acc_ab", "acc_b", "acc_tb", "acc_tbf", "acc_mention_non_renseignee",
)
FIELD_BY_NAME = {f.name: f for f in VOEUX_FIELDS}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def resolve(fields: tuple[Field, ...], available: list[str]) -> dict[str, str | None]:
    """Map canonical field -> upstream column (or None). Each upstream column is used once."""
    by_norm: dict[str, str] = {}
    for col in available:
        by_norm.setdefault(norm(col), col)
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for f in fields:
        hit = None
        for cand in f.candidates:
            col = by_norm.get(norm(cand))
            if col is not None and col not in used:
                hit = col
                break
        if hit:
            used.add(hit)
        out[f.name] = hit
    return out


def resolve_by_keywords(available: list[str], rules: dict[str, list[tuple[str, ...]]]) -> dict[str, str | None]:
    """Resolve columns of loosely documented datasets (specialités, cartographie).

    rules: canonical -> list of keyword tuples; the first column whose normalised
    name contains *all* keywords of a tuple wins. Tuples are tried in order.
    """
    normed = [(norm(c), c) for c in available]
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for canon, alternatives in rules.items():
        out[canon] = None
        for kws in alternatives:
            for n, c in normed:
                if c not in used and all(k in n for k in kws):
                    out[canon] = c
                    used.add(c)
                    break
            if out[canon]:
                break
    return out
