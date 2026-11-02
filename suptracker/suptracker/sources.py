"""Source register (sprint 3): every dataset the platform uses or plans to use, with how it is
obtained, at what granularity, through which keys, and what it feeds.

`access`:
* "ods"          downloaded by the data workflow from the SIES open-data portal (config.DATASETS);
* "owner_upload" the producer's site rejects automated downloads: the owner commits the file under
                 data/sources/ (matching `file_glob`), the data workflow's fingerprint includes it;
* "planned"      not ingested yet (roadmap); listed so the journey shows what is coming and why.
"""
from __future__ import annotations

LICENCE_OUVERTE = "Licence Ouverte / Open Licence 2.0"

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
     "access": "planned", "granularity": "établissement × diplôme × discipline", "keys": ("uai", "etablissement_id_paysage"),
     "feeds": ("insertion",), "status": "prevu", "sprint": 8, "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/insertion-professionnelle-des-diplomes-des-etablissements-denseignement-superieur-dispositif-insersup"},
    {"key": "inserjeunes", "title": "Inserjeunes : insertion des sortants de la voie professionnelle (BTS inclus)", "producer": "MENJ-DEPP / DARES",
     "access": "planned", "granularity": "établissement × formation", "keys": ("uai",), "feeds": ("insertion",), "status": "prevu",
     "sprint": 8, "licence": LICENCE_OUVERTE,
     "url": "https://www.data.gouv.fr/datasets/inserjeunes-voie-professionnelle-scolaire-par-etablissement-relevant-du-ministere-de-leducation-nationale"},
)

ACCESS = ("ods", "owner_upload", "planned")
STATUS = ("en_ligne", "prevu")


def public_view() -> list[dict]:
    """What the "Sources" page shows: no internal dataset keys."""
    keep = ("key", "title", "producer", "access", "granularity", "feeds", "status", "sprint", "licence", "url")
    return [{k: s.get(k) for k in keep} for s in SOURCES]
