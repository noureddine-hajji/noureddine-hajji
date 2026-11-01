"""Dataset registry and build settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ODS_BASE = os.environ.get(
    "SIES_ODS_BASE", "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1"
)

YEARS: tuple[int, ...] = (2022, 2023, 2024, 2025)
LATEST_YEAR = max(YEARS)

DATA_DIR = Path(os.environ.get("SUPTRACKER_DATA", Path(__file__).resolve().parents[1] / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "suptracker.duckdb"

LOW_N_THRESHOLD = 10          # acc_tot below this -> low-denominator warning
MIN_PEERS = 5                 # fewer peers than this -> peer quantiles flagged unstable
LINK_MIN_SCORE = 0.60         # label similarity floor for the secondary linker
LINK_MIN_MARGIN = 0.10        # best candidate must beat runner-up by this much


@dataclass(frozen=True)
class Dataset:
    key: str                  # local name (raw/<key>.parquet)
    ods_ids: tuple[str, ...]  # tried in order; SIES has re-published some datasets under new ids
    kind: str                 # "voeux" | "specialites" | "cartographie"
    year: int | None = None


DATASETS: tuple[Dataset, ...] = (
    Dataset("parcoursup_2025", ("fr-esr-parcoursup",), "voeux", 2025),
    Dataset("parcoursup_2024", ("fr-esr-parcoursup_2024",), "voeux", 2024),
    Dataset("parcoursup_2023", ("fr-esr-parcoursup_2023",), "voeux", 2023),
    Dataset("parcoursup_2022", ("fr-esr-parcoursup_2022",), "voeux", 2022),
    # 2021–2024 specialty outcomes. The original id was superseded by "-2" on the SIES portal.
    Dataset(
        "specialites_2021_2024",
        (
            "fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-2",
            "fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux",
        ),
        "specialites",
    ),
    Dataset(
        "specialites_2025",
        ("fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-3",),
        "specialites",
    ),
    Dataset("cartographie", ("fr-esr-cartographie_formations_parcoursup",), "cartographie"),
    # MESR register of the main higher-education establishments (Paysage id, UAI, type, sector)
    Dataset("etablissements", ("fr-esr-principaux-etablissements-enseignement-superieur",), "reference"),
)


def parquet_export_url(ods_id: str) -> str:
    return f"{ODS_BASE}/catalog/datasets/{ods_id}/exports/parquet"


def records_url(ods_id: str) -> str:
    return f"{ODS_BASE}/catalog/datasets/{ods_id}/records"
