# SupTracker SIES: longitudinal Parcoursup analytics, 2022–2025

This is an analytical web app built on the official SIES / MESR open data for the last four completed
Parcoursup campaigns: **2022, 2023, 2024 and 2025**. It has three layers:

1. A **DuckDB / Parquet pipeline** that ingests the raw SIES exports and harmonises their schemas.
2. A **longitudinal crosswalk** that links each formation across campaigns, with an explicit confidence flag.
3. **Statistical safeguards** enforced in the data model, the API and the UI.

```
suptracker/
  suptracker/config.py       dataset registry (ODS ids, years, thresholds)
  suptracker/ingest.py       ODS v2.1 Parquet export download + manifest (sha256, rows)
  suptracker/schema.py       canonical schema, alias table, funnel stage of every field
  suptracker/harmonize.py    raw → core.formation_year / core.specialites / core.cartographie
  suptracker/crosswalk.py    entity resolution + continuity report
  suptracker/indicators.py   within-filière peer quantiles
  suptracker/build.py        orchestrator (atomic warehouse swap)
  suptracker/api.py          FastAPI + static SPA (suptracker/static/)
  scripts/verify_ground_truth.py   accounting-identity & fidelity verification suite
  tests/                     pytest suite on a SYNTHETIC fixture (tests/synthetic.py)
```

## Run

```bash
cd suptracker
pip install -r requirements-pipeline.txt
python -m suptracker.ingest            # downloads data/raw/*.parquet from data.enseignementsup-recherche.gouv.fr
python -m suptracker.build             # builds data/suptracker.duckdb
python scripts/verify_ground_truth.py --live 25 --strict   # writes reports/verification.{md,json}
uvicorn suptracker.api:app             # http://127.0.0.1:8000
```

## Deploy on Vercel (serverless)

On Vercel the app runs as a read-only serverless function, so it cannot download or build data at
start-up. The data is built ahead of time instead:

1. **Build the data on GitHub.** The workflow `.github/workflows/suptracker-data.yml` runs on a GitHub
   runner, which can reach SIES. It ingests, builds and verifies the data, then commits
   `suptracker/data/suptracker.duckdb` and `suptracker/data/verification/`. It runs monthly; to run it
   by hand, go to **Actions → suptracker-data → Run workflow**.
2. **Create the Vercel project.** Import the repo with these settings:
   - Root Directory: `suptracker`
   - Application Preset: **FastAPI**
   - Build and Output Settings: leave as is
   - Environment Variables: none needed

   Vercel installs the slim runtime declared in `pyproject.toml` (duckdb, fastapi, uvicorn), and
   `[tool.vercel] entrypoint = "suptracker.api:app"` tells it which app to serve.
3. **Redeploys are automatic.** Every data commit on `main` triggers one. Until the first data commit
   exists, the site loads but the API answers 503.

`requirements.txt` holds only the serving runtime, to fit Vercel's 250 MB function limit. The pipeline
and tests use `requirements-pipeline.txt`. duckdb is pinned exactly (`2.0.0`) because the warehouse
file must be read by the same version that wrote it.

## Deploy with Docker (Render, Fly.io, VPS)

The app is one container: FastAPI + DuckDB, with a persistent volume at `/data`.

```bash
docker build -t suptracker-sies .                          # or: --build-arg PREBUILD=1 to bake data in
docker run -p 8000:8000 -v suptracker-data:/data suptracker-sies
```

- **First start:** if `/data/suptracker.duckdb` is missing, the entrypoint serves right away and then
  downloads the SIES exports and builds the warehouse in the background (a few minutes). During that
  time, `/healthz` returns 200 with `ready: false`, while `/readyz` and the API return 503. The build
  swaps the finished warehouse in atomically. The verification report is written to
  `/data/reports/verification.md`.
- **Hosting:** `render.yaml` (at the repo root) is a ready Render blueprint (web service, Docker, 2 GB disk at `/data`).
  Fly.io, Railway, Cloud Run or a VPS work the same way: build the Dockerfile, mount a volume at
  `/data`, and set `$PORT` if the platform requires it.
- **Environment variables:**

  | variable | default | purpose |
  |---|---|---|
  | `PORT` | `8000` | port the app listens on |
  | `SUPTRACKER_DATA` | `/data` | data directory |
  | `SUPTRACKER_DB` | `$SUPTRACKER_DATA/suptracker.duckdb` | warehouse path |
  | `SUPTRACKER_AUTOBUILD` | `1` | build the warehouse on first start; `0` to turn off |
  | `SIES_ODS_BASE` | SIES v2.1 API | API base URL |

- **Base image:** if Docker Hub rate-limits your builder, pass
  `--build-arg BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim`.
- **Refreshing data:** run `make refresh` (or `python -m suptracker.ingest --force && python -m suptracker.build`)
  inside the container, then restart it. The running process keeps its connection to the previous
  warehouse until it restarts.
- **Network:** the host that builds the data must be able to reach `data.enseignementsup-recherche.gouv.fr`.

## 1. Ingestion and schema harmonisation

| key | ODS dataset id (tried in order) |
|---|---|
| parcoursup_2025 | `fr-esr-parcoursup` |
| parcoursup_2024 / 2023 / 2022 | `fr-esr-parcoursup_2024`, `_2023`, `_2022` |
| specialites_2021_2024 | `fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-2`, then the original id without `-2` |
| specialites_2025 | `fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-3` |
| cartographie | `fr-esr-cartographie_formations_parcoursup` |

SIES re-published the specialty dataset under new ids (`-2` for 2021–2024, `-3` for 2025). The registry
therefore tries the current ids first.

Exports come from `/api/explore/v2.1/catalog/datasets/{id}/exports/parquet` and are stored untouched.
`schema.py` maps every canonical field to its upstream aliases. Matching is case-, accent- and
punctuation-insensitive. Each vintage's mapping is written to `meta.schema_audit` with one of these
statuses: `exact`, `alias`, `missing` or `unmapped_upstream`. A field missing from a vintage is NULL and
is shown on the *Qualité des données* page. It is never imputed and never dropped silently. The
specialty and cartographie datasets have looser layouts, so their columns are resolved by keyword. The
match each one used is audited too.

## 2. Longitudinal entity resolution

| pass | rule | flag |
|---|---|---|
| 1 | same `(cod_uai, cod_aff_form)` in consecutive campaigns | `exact_id_match` |
| 2 | `cod_aff_form` changed: candidates limited to the same `cod_uai` **and** the same `fili`. Score = token-set Jaccard on normalised `form_lib_voe_acc` + `fil_lib_voe_acc` + `lib_comp_voe_ins`. Accepted only if score ≥ 0.60, the pair is **mutually best**, and the margin over the runner-up is ≥ 0.10 | `inferred_uai_track_match` |
| 3 | same `(cod_uai, cod_aff_form)` across a one-campaign gap | `exact_id_match` |

Links are strictly one-to-one, so a lineage is a simple chain anchored on its most recent campaign.
Rejected candidates, whether ambiguous, not mutually best or below the score threshold, go to
`core.crosswalk_audit` and are **never** linked. A missed link only shortens a series, but a wrong link
would merge two programmes. A lineage containing at least one inferred link carries the inferred flag,
and the UI badges it. Missing years appear as gaps in the charts and are never interpolated.

## 3. Methodological rules enforced

- **Funnel stages are kept apart.** Each field records its stage (`candidates`, `ranked_offered`,
  `admitted`). The UI shows the stages side by side without ratios between them.
- **Official indicators are used as published.** `taux_acces_ens` and `part_acces_gen` (exposed as
  `part_terminale_generale_en_position_admis_pp`) are never recomputed. A test fails the build if any
  source file divides `prop_tot` by `voe_tot` or `nb_voe_pp`. Tooltips explain why SIES limits these
  indicators to the phase principale.
- **Sub-wishes (vœux multiples / concours communs) are flagged in two ways.** One is a label rule
  (`concours`, `Puissance Alpha`, `Geipi`, …). The other is a data rule: at least 3 formations with
  identical `voe_tot`, `voe_tot_f`, `nb_voe_pp` and `nb_voe_pc` (with `voe_tot` ≥ 100) form one shared
  pool. Aggregates count each `subwish_group_id` only once.
- **The admitted cohort is decomposed over the 4 years.** It is split by bac series, bac mention,
  scholarship holders, gender, and academic / school origin.
- **Peer quantiles are computed within each `fil_lib_voe_acc` × session.** They give p10, p25, p50, p75,
  p90 and a mid-rank percentile. Formations with `acc_tot < 10` are flagged and are left out of the
  reference distribution for cohort-profile metrics. `taux_acces_ens` rests on the phase-principale
  applicant pool, so it is still ranked for them. Fewer than 5 peers marks the distribution unstable.

## 4. Interface

- **Search** accepts an establishment name, a city, a `cod_uai`, a filière, or a pasted `parcoursup.fr`
  fiche URL. The URL's `g_ta_cod` is extracted by regex and only parcoursup.fr hosts are accepted.
- **Views:** formation profile (with filière benchmarks), multi-formation comparator (up to 6),
  4-year cohort evolution, specialty-doublette matrix, and a data-quality / continuity page.
- **Fiche URL resolution** uses the cartographie dataset first, then `lien_form_psup`, then the canonical
  `g_ta_cod` URL template.

The specialty dataset is published by SIES at national level, by formation type and doublette, not per
formation. The matrix therefore benchmarks types of formation, and its unit is candidates (persons).

## 5. Verification suite

`scripts/verify_ground_truth.py` checks, for every campaign:

- the series identity, `acc_bg + acc_bt + acc_bp == acc_term`;
- the mention identity, sum of the six mention fields `== acc_term`;
- the same two identities against `acc_neobac`, plus `series + acc_at == acc_tot`, as diagnostics. These
  show which denominator SIES actually uses in each vintage;
- `taux_acces_ens` in the warehouse against the raw upstream Parquet, re-read independently with pyarrow;
- `taux_acces_ens` against the live SIES records API on a random sample (`--live N`);
- that bounds hold, keys are unique, links are one-to-one, and every row belongs to exactly one lineage.

It then writes the **longitudinal continuity report**: the share of 2025 formations linked to each of
2024, 2023 and 2022, the share covering the full span (in total and exact-only), and the share with an
inferred link, both overall and by `fili`. Rows with NULL components count as *not evaluable*, never as
passes. `--strict` returns a non-zero exit code on failure.
