"""Source register (sprint 3): every dataset the platform uses or plans to use, with how it is
obtained, at what granularity, through which keys, and what it feeds.

`access`:
* "ods"          downloaded by the data workflow from the SIES open-data portal (config.DATASETS);
* "owner_upload" the producer's site rejects automated downloads: the owner commits the file under
                 data/sources/ (matching `file_glob`), the data workflow's fingerprint includes it;
* "planned"      not ingested yet (roadmap); listed so the journey shows what is coming and why.

`status`: "en_ligne" (served), "prevu" (planned, not obtained yet), "depose" (sprint 12: committed by the owner
under data/sources/, NOT ingested yet; `sprint` says which sprint uses it, `role` whether it is a primary source
or only a cross-check). `file_glob` is one pattern or a tuple of patterns.
"""
from __future__ import annotations

LICENCE_OUVERTE = "Licence Ouverte / Open Licence 2.0"
ODBL = "Open Database License (ODbL) 1.0"

SOURCES = (
    {"key": "parcoursup", "title": "Parcoursup 2022-2025 : vœux et réponses des établissements", "producer": "MESR-SIES",
     "access": "ods", "datasets": ("parcoursup_2022", "parcoursup_2023", "parcoursup_2024", "parcoursup_2025"),
     "granularity": "formation", "keys": ("cod_aff_form", "cod_uai", "etablissement_id_paysage"),
     "feeds": ("acces", "profil_admis"), "status": "en_ligne", "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/parcoursup-2025-voeux-de-poursuite-detudes-et-de-reorientation-dans-lenseignement-superieur-et-reponses-des-etablissements"},
    {"key": "specialites", "title": "Parcoursup : enseignements de spécialité des bacheliers généraux", "producer": "MESR-SIES",
     "access": "ods", "datasets": ("specialites_2021_2024", "specialites_2025"), "granularity": "type de formation",
     "keys": ("doublette", "formation"), "feeds": ("acces",), "status": "en_ligne", "licence": LICENCE_OUVERTE, "url": None},
    {"key": "cartographie", "title": "Cartographie des formations Parcoursup", "producer": "MESR-SIES", "access": "ods",
     "datasets": ("cartographie",), "granularity": "formation", "keys": ("code_formation", "etablissement_id_paysage"),
     "feeds": ("offre",), "status": "en_ligne", "licence": LICENCE_OUVERTE, "url": None},
    {"key": "etablissements", "title": "Principaux établissements d'enseignement supérieur", "producer": "MESR",
     "access": "ods", "datasets": ("etablissements",), "granularity": "établissement", "keys": ("etablissement_id_paysage", "uai"),
     "feeds": ("referentiel",), "status": "en_ligne", "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/principaux-etablissements-d-enseignement-superieur-mesr"},
    {"key": "reussite_licence", "title": "Réussite et passage en licence par discipline et établissement (NF 2025-29)",
     "producer": "MESR-SIES", "access": "owner_upload", "file_glob": "sies_reussite_licence*.xlsx",
     "granularity": "université × grande discipline", "keys": ("nom d'établissement SIES", "discipline en L1"),
     "feeds": ("reussite", "passerelles"), "status": "en_ligne", "licence": LICENCE_OUVERTE,
     "url": "https://www.enseignementsup-recherche.gouv.fr/fr/parcours-et-reussite-en-licence-les-resultats-de-la-session-2024-100331"},
    {"key": "reussite_but", "title": "Parcours et réussite en BUT : tableaux par établissement et tableaux nationaux (NF 2025-26)",
     "producer": "MESR-SIES", "access": "owner_upload", "file_glob": "nf-sies-2025-26-*.xlsx",
     "granularity": "université (pas d'IUT ni de spécialité) ; national par spécialité, série et mention",
     "keys": ("nom d'établissement SIES",), "feeds": ("reussite", "poursuite"), "status": "en_ligne", "sprint": 6,
     "licence": LICENCE_OUVERTE,
     "url": "https://www.enseignementsup-recherche.gouv.fr/fr/parcours-et-reussite-en-iut-les-resultats-de-la-session-2024-100265"},
    {"key": "reussite_master", "title": "Parcours et réussite en master à l'université : par discipline et établissement, tableaux nationaux, poursuites d'études (NF 2025-30)",
     "producer": "MESR-SIES", "access": "owner_upload", "file_glob": "nf-sies-2025-30-*.xlsx",
     "granularity": "université × grande discipline de M1 ; national par discipline, type de bac et mention",
     "keys": ("nom d'établissement SIES", "discipline en M1"), "feeds": ("reussite", "poursuite"), "status": "en_ligne", "sprint": 6,
     "licence": LICENCE_OUVERTE,
     "url": "https://www.enseignementsup-recherche.gouv.fr/fr/parcours-et-reussite-en-master-l-universite-les-resultats-de-la-session-2024-100403"},
    # ---------------------------------------------------------------- roadmap (sprints 4-8)
    {"key": "ips_lycees", "title": "Indices de position sociale des lycées (à partir de 2023)", "producer": "MENJ-DEPP",
     "access": "ods", "datasets": ("ips_lycees",), "granularity": "lycée", "keys": ("uai",), "feeds": ("profil_lycee",), "status": "en_ligne", "sprint": 4,
     "licence": LICENCE_OUVERTE, "url": "https://www.data.gouv.fr/datasets/ips-lycees-a-partir-de-2023"},
    {"key": "ival_lycees", "title": "Indicateurs de valeur ajoutée des lycées d'enseignement général et technologique", "producer": "MENJ-DEPP",
     "access": "ods", "datasets": ("ival_lycees_gt",), "granularity": "lycée", "keys": ("uai",), "feeds": ("profil_lycee",), "status": "en_ligne", "sprint": 4,
     "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/indicateurs-de-valeur-ajoutee-des-lycees-denseignement-general-et-technologique-2"},
    {"key": "monmaster", "title": "MonMaster 2023-2025 : vœux et réponses des établissements", "producer": "MESR-SIES",
     "access": "ods", "datasets": ("monmaster_2024_2025", "monmaster_2023"), "granularity": "mention de master × établissement",
     "keys": ("etablissement",), "feeds": ("passerelles",), "status": "en_ligne", "sprint": 7, "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/monmaster-2024-2025-voeux-de-poursuite-detudes-et-de-reorientation-en-master-et-reponses-des-etablissements"},
    {"key": "insersup", "title": "InserSup : insertion professionnelle des diplômés", "producer": "MESR-SIES",
     "access": "ods", "datasets": ("insersup",), "granularity": "établissement × diplôme × discipline",
     "keys": ("uai", "etablissement_id_paysage"), "feeds": ("insertion",), "status": "en_ligne", "sprint": 8,
     "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/insertion-professionnelle-des-diplomes-des-etablissements-denseignement-superieur-dispositif-insersup"},
    {"key": "inserjeunes", "title": "Inserjeunes : insertion des sortants de la voie professionnelle (BTS inclus)", "producer": "MENJ-DEPP / DARES",
     "access": "ods", "datasets": ("inserjeunes_lycee", "inserjeunes_cfa"), "granularity": "établissement × formation",
     "keys": ("uai",), "feeds": ("insertion",), "status": "en_ligne", "sprint": 8, "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/inserjeunes-voie-professionnelle-scolaire-par-etablissement-relevant-du-ministere-de-leducation-nationale-et-formation-fine"},
    {"key": "cereq_generation", "title": "Céreq, enquête Génération 2017 : chiffres clés par diplôme (3 et 6 ans)",
     "producer": "Céreq", "access": "owner_upload", "file_glob": "OpenData_Cereq*.xlsx",
     "granularity": "France entière × groupe de plus haut diplôme (niveau × grand domaine)",
     "keys": ("filière Parcoursup", "domaine NSF du BTS", "discipline B1 de la licence"), "feeds": ("cereq",),
     "status": "en_ligne", "sprint": 8, "licence": LICENCE_OUVERTE,
     "url": "https://www.cereq.fr/datavisualisation/insertion-professionnelle-des-jeunes/les-chiffres-cles-par-diplome"},
    {"key": "onisep", "title": "Onisep : formations initiales, fiches formations et fiches métiers (Idéo)", "producer": "Onisep",
     "access": "owner_upload", "file_glob": "ONISEP-*",
     "granularity": "diplôme (formation) × métier", "keys": ("libelle_diplome",), "feeds": ("metiers",), "status": "en_ligne",
     "sprint": 8, "licence": ODBL, "url": "https://opendata.onisep.fr/2-les-donnees.htm"},
    # ---- Horizon 2030 (sprints 13-16): committed by the owner, not ingested yet (status "depose")
    {"key": "metiers_2030", "title": "Les métiers en 2030 : projections par famille professionnelle (FAP-87)",
     "producer": "France Stratégie / Dares", "access": "owner_upload", "file_glob": "Les métiers en 2030*.xlsx",
     "granularity": "famille professionnelle FAP-2009 (87)", "keys": ("FAP-87",), "feeds": ("emploi_2030",),
     "status": "en_ligne", "sprint": 14, "role": "source", "licence": LICENCE_OUVERTE,
     "url": "https://dares.travail-emploi.gouv.fr/publication/les-metiers-en-2030-le-rapport-national"},
    {"key": "dares_fap", "title": "Familles professionnelles : nomenclature FAP-2021, passages ROME/PCS vers FAP, matrices de bascule FAP-2009 ↔ FAP-2021",
     "producer": "Dares", "access": "owner_upload",
     "file_glob": ("Dares_Table_passage_*", "Dares_Matrices_bascule_*", "Dares_Nomenclature_FAP2021*", "dares_nomenclature_fap2021.csv",
                   "passage_fap2009_romev3.txt", "Table de correspondance PCS-2003, Rome-V3 vers Fap-2009.xls"),
     "granularity": "ROME (+ qualification) / PCS → FAP", "keys": ("ROME", "PCS", "FAP"), "feeds": ("referentiel_metiers",),
     "status": "en_ligne", "sprint": 13, "role": "source", "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/la-nomenclature-des-familles-professionnelles-2021"},
    {"key": "insee_pcs_isco", "title": "PCS 2020 : matrice PCS → ISCO-08, codification des libellés (G44), tables de passage PCS 2003 ↔ 2020",
     "producer": "Insee", "access": "owner_upload",
     "file_glob": ("Matrice_PCS_ISCO_*", "G44_Matrice_codification_ISCO*", "table_passage_20*.xlsx"),
     "granularity": "profession (PCS 2020) / libellé → ISCO-08", "keys": ("PCS", "ISCO-08"), "feeds": ("referentiel_metiers",),
     "status": "en_ligne", "sprint": 13, "role": "source", "licence": LICENCE_OUVERTE, "url": "https://www.insee.fr/fr/information/6205275"},
    {"key": "rome_arbo", "title": "ROME 4.0 : arborescence principale (fiches et appellations de métiers)",
     "producer": "France Travail", "access": "owner_upload", "file_glob": "*rome_arboprincipale*.xlsx",
     "granularity": "appellation de métier → fiche ROME", "keys": ("ROME", "OGR"), "feeds": ("referentiel_metiers",),
     "status": "en_ligne", "sprint": 13, "role": "rattachement par le nom des métiers sans code ROME Onisep",
     "licence": LICENCE_OUVERTE, "url": "https://www.data.gouv.fr/datasets/repertoire-operationnel-des-metiers-et-des-emplois-rome"},
    {"key": "rome_tags", "title": "ROME 4.0 : étiquettes des fiches (transitions écologique, numérique, démographique ; cadre ; réglementé)",
     "producer": "France Travail", "access": "owner_upload", "file_glob": "*fiches-rome*tag*.xlsx",
     "granularity": "fiche ROME", "keys": ("ROME",), "feeds": ("taches_ia",), "status": "en_ligne", "sprint": 15, "role": "source",
     "licence": LICENCE_OUVERTE, "url": "https://www.data.gouv.fr/datasets/repertoire-operationnel-des-metiers-et-des-emplois-rome"},
    {"key": "dares_tensions", "title": "Les tensions sur le marché du travail en 2025 (données et note méthodologique)",
     "producer": "Dares", "access": "owner_upload", "file_glob": ("Dares Résultats_données_Les tensions*", "Note méthodologique sur l'analyse des tensions*"),
     "granularity": "famille professionnelle FAP-2021 (30 métiers les plus en tension seulement)", "keys": ("FAP-228",),
     "feeds": ("emploi_2030",), "status": "depose", "sprint": 14, "role": "contexte", "licence": LICENCE_OUVERTE,
     "url": "https://dares.travail-emploi.gouv.fr/publication/les-tensions-sur-le-marche-du-travail-en-2024"},
    {"key": "bmo", "title": "Besoins en main-d'œuvre 2025-2026 (classeur retravaillé : chiffres BMO ; son passage FAP → ISCO « à dire d'expert » n'est pas utilisé)",
     "producer": "France Travail (retraitement du propriétaire)", "access": "owner_upload", "file_glob": "BMO_*.xlsx",
     "granularity": "métier BMO (FAP-2021)", "keys": ("FAP-228",), "feeds": ("emploi_2030",), "status": "en_ligne", "sprint": 14,
     "role": "contexte court terme (sommes recalculées depuis les bassins)", "licence": LICENCE_OUVERTE, "url": "https://statistiques.francetravail.org/bmo"},
    {"key": "oit_genai", "title": "OIT : exposition des tâches à l'IA générative, indice affiné 2025 (WP 140), par ISCO-08",
     "producer": "Organisation internationale du travail", "access": "owner_upload", "file_glob": "Final_Scores_ISCO08_Gmyrek*.xlsx",
     "granularity": "tâche × ISCO-08 (4 chiffres)", "keys": ("ISCO-08",), "feeds": ("taches_ia",), "status": "en_ligne", "sprint": 15,
     "role": "source", "licence": "CC BY 4.0", "url": "https://github.com/pgmyrek/2025_GenAI_scores_ISCO08"},
    {"key": "onet_complementarite", "title": "O*NET : contexte de travail et Job Zones (complémentarité humaine θ, méthode FMI reconstituée) et guide de calcul",
     "producer": "U.S. Department of Labor / ETA", "access": "owner_upload",
     "file_glob": ("work_context.csv", "job_zones.csv", "Guide_ONET_Work_Context_Job_Zones*.md"),
     "granularity": "profession O*NET-SOC", "keys": ("O*NET-SOC",), "feeds": ("taches_ia",), "status": "en_ligne", "sprint": 15,
     "role": "source (reconstitution, fiabilité C)", "licence": "CC BY 4.0", "url": "https://www.onetcenter.org/database.html"},
    {"key": "felten_aioe", "title": "Felten, Raj et Seamans (2021) : exposition des professions à l'IA (AIOE), annexe de données, par SOC 2010",
     "producer": "Felten, Raj, Seamans (Strategic Management Journal)", "access": "owner_upload", "file_glob": "AIOE_DataAppendix.xlsx",
     "granularity": "profession SOC 2010 (774)", "keys": ("SOC 2010",), "feeds": ("taches_ia",), "status": "depose", "sprint": 15,
     "role": "source (C-AIOE ; indice centré-réduit, échelle à valider)", "licence": "données de recherche publiques",
     "url": "https://github.com/AIOE-Data/AIOE"},
    {"key": "onet_soc2019_soc2018", "title": "Passages O*NET-SOC 2019 → SOC 2018 (O*NET) et SOC 2010 ↔ SOC 2018 (BLS)",
     "producer": "O*NET Resource Center / U.S. Bureau of Labor Statistics", "access": "owner_upload",
     "file_glob": ("2019_to_SOC_Crosswalk.xlsx", "soc_2010_to_2018_crosswalk.xlsx"),
     "granularity": "profession O*NET-SOC 2019 / SOC", "keys": ("O*NET-SOC", "SOC 2018", "SOC 2010"), "feeds": ("taches_ia",),
     "status": "en_ligne", "sprint": 15, "role": "passage", "licence": "CC BY 4.0 / domaine public",
     "url": "https://www.bls.gov/soc/2018/crosswalks_used_by_agencies.htm"},
    {"key": "anthropic_aei", "title": "Anthropic Economic Index (juin 2026) : usage observé de Claude par tâche O*NET (fichiers bruts)",
     "producer": "Anthropic", "access": "owner_upload", "file_glob": "data_documentation_claude_ai.zip",
     "granularity": "tâche O*NET", "keys": ("O*NET-SOC",), "feeds": ("taches_ia",), "status": "depose", "sprint": 15,
     "role": "usage observé d'un seul outil", "licence": "CC BY 4.0", "url": "https://huggingface.co/datasets/Anthropic/EconomicIndex"},
    {"key": "passages_us_isco", "title": "Passages vers ISCO-08 : BLS ISCO-08 ↔ SOC 2010, ESCO ↔ O*NET (et ESCO ↔ NACE, non utilisé)",
     "producer": "BLS / Commission européenne (ESCO)", "access": "owner_upload",
     "file_glob": ("ISCO_SOC_Crosswalk.xls", "ONET_(Occupations)*.csv", "ESCO-NACE*.xlsx"),
     "granularity": "profession", "keys": ("SOC 2010", "O*NET-SOC", "ISCO-08"), "feeds": ("taches_ia",), "status": "en_ligne", "sprint": 15,
     "role": "source", "licence": "domaine public / CC BY 4.0", "url": "https://www.bls.gov/soc/soccrosswalks.htm"},
    {"key": "ia_classeurs_retravailles", "title": "Classeurs IA retravaillés (exposition OIT/FMI, passage Eloundou, AEI par tâche) : contrôle croisé seulement, jamais affichés",
     "producer": "retraitement du propriétaire", "access": "owner_upload",
     "file_glob": ("Exposition_IA_ISCO08_*", "Eloundou_SOC_ISCO08_*", "AEI_2026-06_*", "aei_2026-06-26_*", "README_AI_exposure*"),
     "granularity": "ISCO-08 / tâche O*NET", "keys": ("ISCO-08", "O*NET-SOC"), "feeds": ("taches_ia",), "status": "depose", "sprint": 15,
     "role": "contrôle croisé", "licence": "CC BY 4.0 (sources d'origine)", "url": None},
)

ACCESS = ("ods", "download", "owner_upload", "planned")
STATUS = ("en_ligne", "prevu", "depose")


def globs(s: dict) -> tuple:
    """The file pattern(s) of an owner-uploaded source."""
    g = s.get("file_glob")
    return () if not g else (g,) if isinstance(g, str) else tuple(g)


def public_view() -> list[dict]:
    """What the "Sources" page shows: no internal dataset keys."""
    keep = ("key", "title", "producer", "access", "granularity", "feeds", "status", "sprint", "role", "licence", "url")
    return [{k: s.get(k) for k in keep} for s in SOURCES]
