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
python scripts/verify_ground_truth.py --live 25 --strict   # writes data/verification/verification.{md,json}
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
  `/data/verification/verification.md` (shown on the data-quality page).
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

## Search (`suptracker/search.py`)

Students type what they would say out loud: *prépa HEC Lyon*, *BTS NDRC*, *IUT informatique
Toulouse*, *sciences po*, *infirmière Bordeaux*, *kiné*. The engine is an in-memory index over the
latest campaign of every lineage (16k documents, 67 MB). It is built once per warehouse and warmed
in the background when the app loads.

- **Normalisation**, applied to documents and queries alike:
  - accents, case and full-width characters are folded;
  - dotted acronyms are collapsed ("I.U.T" → "iut");
  - "St" and "Ste" become "Saint" and "Sainte";
  - plurals and "-ière" feminines are stemmed.
- **Acronym tags.** About 90 student phrasings (NDRC, GEA, MPSI, hypokhâgne, sciences po, école
  d'ingé, …) map to tags that programmes carry deterministically from their official labels. A few
  English queries (law, nursing, engineering school, …) work too.
- **Place detection.**
  - The longest town, département, académie or region name in the query becomes a filter. Formations
    in the named town rank above the rest of the académie.
  - A single word is only taken as a place if it names more locations than it appears in programme
    labels, so discipline words are never mistaken for places.
  - A word such as "clermont" or "aix" covers every place it names.
- **Ranking.**
  - Weights by field: tag > discipline > establishment > place > complement > broad family.
  - Words are weighted by IDF.
  - Matching tries exact, then prefix, then one or two typos.
  - A programme whose own label contains the word the student typed outranks one that only carries
    the tag ("Parcours Kinésithérapie" before any L.AS).
  - Ties break on the latest campaign, then the student's académie if their profile has one, then a
    deterministic hash. **Never on selectivity, size or name**: alphabetical order would favour "A…"
    establishments, and capacity order favoured large, accessible programmes (Spearman −0.46 against
    access rate, found by the red team).
- **Honest fallbacks.**
  - If no programme matches every word, the least informative free word is dropped and the results are
    flagged *partiels*. Recognised concepts are never dropped first.
  - If most of the query is unknown, the engine returns nothing rather than guessing.
  - Professions with no Parcoursup programme of their own (médecine, kiné, sage-femme, véto) return the
    access programmes with an explanatory note.
- **Disjunctive facets.** Each filter is counted with the other active filters applied, so every
  count shown is exactly what clicking it returns.

### Measured quality (real 2022–2025 warehouse)

A query passes when at least 4 of its top 5 results are relevant, or, when fewer than 5 relevant
formations exist, when all of them come first.

| Set | Queries | Previous search | New search | New, first blind run |
|---|---|---|---|---|
| Gold (`scripts/eval_search.py`) | 46 | 34.8%, 15 empty | **100%**, 0 empty | – (used for tuning) |
| Holdout 1 (`scripts/holdout_search.py`) | 30 | 63.3%, 4 empty | **100%** | 93.3% |
| Holdout 2, harder phrasings (`scripts/holdout2_search.py`) | 20 | 60.0%, 4 empty | **100%** | 90.0% |

Latency in-process: p50 about 3–6 ms, p95 under 15 ms; through the API, about 16 ms median.

**Red team** (`scripts/redteam_search.py`), 13/13 pass:

| # | Attack | Criterion |
|---|---|---|
| R1 | Hostile, malformed and huge inputs | No crash, under 250 ms |
| R2 | Junk words | No confident results |
| R3 | Stop-words only | Nothing returned |
| R4 | SQL, wildcard and regex shapes | Inert |
| R5 | 10 normalisation equivalences | Same top results |
| R6 | 23 discipline words | Never taken as places |
| R7 | Filters, including combined | Exact counts |
| R8 | Pagination | Disjoint and deterministic |
| R9 | Health professions | Access programmes, with a note |
| R10 | Junk next to a real word | Junk dropped and flagged |
| R11 | Ranking vs access rate | \|Spearman\| < 0.3 |
| R12 | Load (1,000 random queries) | p95 under 60 ms |
| R13 | Every echoed string in the UI | Escaped (mutation-tested: removing an `esc()` makes it fail) |

`tests/test_search.py` runs the gold set, both holdouts and the red team against the committed
warehouse on every push.

## Audience measurement & dashboard (`#/stats`)

First-party, privacy-first measurement (`suptracker/analytics.py`). It answers: who comes, from where,
what students search, what they **do not find**, which pages help them, and whether the app breaks.

**What is measured.** Page views by section, distinct visitors, searches (with the masked query),
searches with no result, formations consulted, clicks to the official Parcoursup fiche, use of
"Mon parcours", 👍/👎 feedback with a closed list of reasons, device class, traffic source, and JS
and server errors.

**What is never stored.** No cookie, no identifier, no IP address, no user agent and no free text
other than the search query. A visitor is a daily pseudonym, HMAC(salt, day | IP | browser), that
rotates every day, so the unit is the *visitor-day*. Only aggregated daily counters are kept (400
days). Queries are folded, and emails, URLs and digit runs are masked. A query or a fiche appears on
the dashboard only once **k = 3** distinct visitor-days produced it. Do-Not-Track and GPC are
honoured, and bots are filtered.

**Dashboard.**
- Insights in plain language, each with an action.
- Six KPIs with deltas against the previous period. Counts use an exact-test approximation and
  rates a two-proportion z-test, with a **Holm correction** so noise is not reported as a change.
  Rates carry Wilson 95 % intervals.
- Daily small multiples over the Parcoursup calendar, with crosshair, keyboard reading and a table
  view.
- The student funnel: visit → search → fiche → click to Parcoursup.
- Satisfaction per page with intervals, and feedback reasons.
- The "not found" queries, each linking to its reproduction: they are the next gold-set cases for
  the search engine.
- Top formations, sources and devices.
- A measurement-quality panel, and CSV export.

### Set it up on Vercel (5 minutes)

1. **Storage.** In the Vercel project, go to **Storage** → **Create** → **Upstash for Redis** (free
   tier) and connect it to the project. It injects `KV_REST_API_URL` and `KV_REST_API_TOKEN`
   (`UPSTASH_REDIS_REST_URL`/`_TOKEN` work too). Without it, the counters go to `/tmp`, which is wiped
   on every cold start, and the dashboard says so.
2. **Environment variables** (Settings → Environment Variables):
   - `SUPTRACKER_STATS_TOKEN`: a long random value, at least 16 characters. It opens `#/stats`. Without
     it, the dashboard is disabled.
   - `SUPTRACKER_ANALYTICS_SALT`: another long random value, kept secret. Without it, a visitor can
     be counted once per server instance.
   - Optional: `SUPTRACKER_ANALYTICS=off` disables all measurement.
3. **Redeploy.** Then open `https://<your-site>/#/stats` and paste the token. It stays in the tab
   only (sessionStorage).

Generate the secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

**Docker / local.** Counters go to a SQLite file under the data directory (`$SUPTRACKER_DATA/analytics`, i.e. the `/data` volume in Docker), or `SUPTRACKER_ANALYTICS_DIR`.
`make demo-stats` seeds 90 invented days into `/tmp/st-demo` and serves the dashboard with the
token `demo-token-0123456789`.

### Red team (`scripts/redteam_analytics.py`, run in CI by `tests/test_analytics.py`)

| # | Attack or promise | Result |
|---|---|---|
| R1–R3 | Oversized, malformed, out-of-list or extra-field payloads | 413/422, only an `invalid` counter |
| R4 | PII in queries (email, phone, address, URL), IP and UA | nothing stored (full store dump scanned) |
| R5–R6 | Do-Not-Track / GPC; bots, curl, headless browsers | nothing recorded but a counter |
| R7 | Counter inflation by one client | daily budget per pseudonym |
| R8 | Revealing a rare query by repeating it | k-anonymity counts *distinct* visitors |
| R9 | Dashboard access | 503 without a strong token, 401 otherwise, token never in URL, `no-store` |
| R10–R11 | Cardinality floods (queries, spoofed referrers) | capped per day / closed list of sources |
| R12 | Store down | the app keeps answering (fail-open); dashboard 502 |
| R13–R14 | Pseudonym linkability; ballot stuffing | rotates daily; one vote per page and day |
| R15 | Stored XSS through queries | every stored text is escaped (static check plus mutation test) |
| R16 | Latency overhead on `/api/search` | about +3 ms (median of interleaved pairs) |
| R17 | Redis (Upstash, Lua) path vs SQLite path | identical dashboards (fakeredis + lupa) |
| R18–R20 | Statistics (Wilson, z-test, Holm); empty period; side-effect-free reads | pass |
| R21 | No proxy header (direct uvicorn, Docker) | visitors told apart by socket address, which a client cannot forge |
| R22 | Outbound click with no recorded view (past midnight, lost beacon) | funnel stays nested, rates stay in [0, 1] |

## Offer timing and offer options (A2, A4)

**When do offers arrive? (fiche → "Quand arrivent les propositions ?")**
- **What is shown.** The official SIES shares `pct_acc_debutpp`, `pct_acc_datebac` and `pct_acc_finpp`, shown as they are. They are the share of admits who had their offer at the opening of the main phase, before the baccalauréat results, and before the end of the main phase.
- **How the shares behave.** They are cumulative. Verified on the real 2022–2025 data:
  - 0 non-monotonic rows out of 55,844;
  - every row is consistent with `acc_tot` as the denominator (all admits, complementary phase included).

  The last segment of the bar is therefore "after the main phase".
- **What the student reads.** A 4-year table and a plain sentence: "not having an offer on day one is not a refusal: X % of the admits got theirs later". A low-n warning appears below 10 admits.

**Options ("Bon à savoir", search filters, comparator)**
- **Source.** The latest Parcoursup cartographie listing, decoded from the `int` and `amg` fields: internat (girls and boys / girls / boys), teaching fully or partly at a distance, and arrangements for high-level athletes or artists. The listing session is shown with each item.
- **Phrasing.** "avec internat" in a query becomes the internat filter.
- **Facets.** Option counts are exact: each one is what a click returns, whatever else is active.
- **Not offered: apprenticeship.**
  - **Why.** The SIES statistics stopped listing apprenticeship programmes after 2022: 302, then 12, 5 and 3 in 2025, against about 16,700 in the cartographie. A filter would wrongly suggest that almost none exist.
  - **Instead.** A query mentioning apprenticeship or alternance gets a note that points to Parcoursup's own filter.
  - **What stays.** The badge remains on the few fiches concerned, also read from the SIES label.
- **Not claimed: disability support.** The data has no such field (`amg` covers distance teaching and sport or art arrangements only). The methodology points to the référent handicap listed on each Parcoursup fiche.

**Red team (`scripts/redteam_offer.py`, 18 checks, run in CI by `tests/test_offer.py`).** It covers:
- closed domains;
- parity between the SQL decoder and its Python twin;
- cumulative and bounded timing;
- shares consistent with counts;
- latest listing wins;
- coverage (14,250 of 14,252);
- plausibility (internat: CPGE 78 % vs licence 0 %);
- exact facets in 3 filter contexts;
- filters that never reorder results and combine as AND;
- hostile options refused;
- compatibility with older warehouses;
- no raw or unescaped text;
- no reading as a chance of admission;
- no disability claim;
- no misleading filter;
- student phrasing.

A mutation test seeded 5 bugs in the search filters (apprenticeship filter back, wrong facet count, missing "filles", reordering, an "internat" query losing its filter). All 5 were caught.

## Student positioning journey (`#/parcours`)

This feature takes a general-bac student's Terminale specialty doublette, expected mention, home
académie (optional) and boursier status (optional). It positions them in two separate stages. The two
SIES sources are **never multiplied together**: the specialty table is national and has no mentions,
while the establishment table has mentions only for final admits. Combining them would be ecological
inference.

**Data layer** (`suptracker/journey.py`, built into the warehouse):

- `core.spe_doublette` parses the 77 SIES doublette strings against the 13-specialty vocabulary.
  Several specialty names contain commas, so the strings are never split on ",". The key is an
  unordered pair, e.g. `MATHS+SES`.
- `core.taxonomy_link` / `core.taxonomy_rule` form a deterministic, ordered rule table. It maps each
  formation's `(fili, form_lib_voe_acc, fil_lib_voe_acc)` to one formation type of the specialty
  dataset, with an `exact` / `approx` quality flag. It covers 92% of 2025 formations; the rest are
  certificates and other catch-all formations with no type in the specialty data.
- `mart.spe_filiere` holds doublette × type × year counts, from aggregation levels 0–1 only, with type
  labels normalised across vintages.
- `group_applies` / `student_group` is the parser for `lib_grp1..3`. It selects the calling group that
  applies to a general-bac student and reports its last-called rank (`ran_grp`). It also handles
  specialty-split labels such as "spécialité Maths + une spécialité non scientifique". **Finding:**
  the 2022–2025 SIES exports contain no specialty-split group; their 23 distinct labels are based on
  series, gender, campus or CEP. So on real data the parser applies the series rules.

**Stage 1, national gate** (unit: candidates, confirmed on real data; years 2022–2025 pooled):

- **Offer rate:** candidates of the doublette with at least one proposition in the filière, divided by
  those with at least one wish there. It's compared with the offer rate of all candidates in the same
  filière, because the doublette's national offer rate (95.5% for Maths+SES) is too high to be a
  useful bar.
- **Lift:** the doublette's share of the filière's admits, divided by its share of all admits.
- **Destination share:** the share of the doublette's admitted candidates who accepted this filière.
- **Gates:**
  - *atypique:* the doublette is under 2% of the filière's admits;
  - *prédilection:* lift ≥ 1.5 and relative offer rate ≥ 1;
  - *accessible:* everything else;
  - *insuffisant:* fewer than 100 pooled candidates.

**Stage 2, establishment positioning** (per formation, pooled over its 2022–2025 lineage):

- **CDF:** the share of admitted néo-bacheliers *with a known mention* whose mention is at or below the
  student's. The denominator is the sum of the known mention categories. That matches
  `acc_neobac − acc_mention_non_renseignee` wherever the SIES identity holds, and stays within [0, 1]
  on the 2022 rows where it doesn't. It is never computed against `acc_term`, which is not the mention
  base.
- **Confidence interval:** a 95% Wilson interval. A formation is flagged *uncertain* when a value
  inside that interval would change its zone.
- **Other indicators shown:**
  - the exact-mention share;
  - the official `taux_acces_ens`;
  - the bac-général share. SIES does not cross mentions with bac series, so a formation where fewer
    than 50% of admits are bac général gets a "comparabilité limitée" badge;
  - the scholarship share;
  - home académie, with `pct_aca_orig` for non-selective Licences;
  - fewer than 10 bac-général admits (`acc_bg`).
- **Excluded formations:** those closed to bac général, either because their calling groups exclude it
  or because fewer than 5% of admits are bac général (e.g. CPGE ECT).
- **Zones:**
  - *hors-profil:* CDF < 2%;
  - *ambitieux:* access rate < 30% or CDF < 15%;
  - *sécurité:* access rate ≥ 70% and CDF ≥ 50%;
  - *cible:* everything else.

**UI:** a profile bar, then a matrix of filières, then a positioning scatter (`taux_acces_ens` against
the CDF, with zone shading), then a simulated wish list (stored in the browser) with a balance audit.
The page never shows an individual admission probability.

**Calibration:** `scripts/verify_persona.py` runs the persona *Maths + SES, mention AB*. It runs in the
data workflow with `--strict`, and the app shows its report on the data-quality page. It checks:

- Stage 1 gates: CPGE ECG, éco-gestion, AES, Droit and BUT Service pass; CPGE S, which contains MPSI
  and PCSI, is atypique;
- that the national baseline equals the deduplicated "Ensemble des bacheliers" row;
- CPGE ECG stratification (real data: median CDF 6% in the selective half against 45% in the
  accessible half; Henri IV is hors-profil);
- maths invariants, with the CDF recomputed independently in SQL;
- that Stage 2 results do not depend on the doublette (no ecological inference);
- that no output field is a probability.

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

- the series identity, `acc_bg + acc_bt + acc_bp == acc_neobac`;
- the mention identity, sum of the six mention fields `== acc_neobac`;
- `series + acc_at == acc_tot`.

The first run on the real SIES exports showed that both breakdowns add up to `acc_neobac`
(néo-bacheliers), not to `acc_term`. The series identity holds on 100% of rows in all four years,
against about 1.5% for `acc_term`. The `acc_term` sums are kept as diagnostics.

Every identity is evaluated twice: on the warehouse and on the raw upstream file. A row that
violates it identically in both is an inconsistency inside the SIES export itself, for example a few
hundred 2022 rows whose mention counts are off by up to 12. Those rows are reported as
`upstream_inconsistency` and flagged on the formation page; they do not fail the build. Any
difference the pipeline introduces is a `fail`.

The suite also checks:

- `taux_acces_ens` in the warehouse against the raw upstream Parquet, re-read independently with
  pyarrow;
- `taux_acces_ens` against the live SIES records API on a random sample (`--live N`);
- that bounds hold, keys are unique, links are one-to-one, and every row belongs to exactly one lineage.

It then writes the **longitudinal continuity report**: the share of 2025 formations linked to each of
2024, 2023 and 2022, the share covering the full span (in total and exact-only), and the share with an
inferred link, both overall and by `fili`. Rows with NULL components count as *not evaluable*, never as
passes. `--strict` returns a non-zero exit code on failure.
