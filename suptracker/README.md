# SupCompass: longitudinal Parcoursup analytics, 2022–2025

*(Formerly SupTracker. The Python package, folder and environment variables keep the technical name `suptracker`.)*

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

## Which version is live?

- **Footer.** It shows the deployed commit (`VERCEL_GIT_COMMIT_SHA` on Vercel, `SUPTRACKER_COMMIT` in Docker), or the front-end fingerprint when no commit is known.
- **`GET /api/version`.** It returns the commit, the branch, the environment, the asset fingerprint and the list of shipped features. It is never cached.
- **Assets.** `app.js`, `stats.js` and `style.css` are referenced with a content fingerprint (`?v=…`), and the page itself is served `no-cache`. So a browser never keeps an old front-end after a deployment.
- **CI guard.** `tests/test_release.py` fails if any shipped feature loses its entry point in the front-end.

**If the site looks out of date**, compare the footer or `/api/version` with the latest commit of `main`. If they differ, open Vercel → Deployments: the Production deployment must come from branch `main`. Then redeploy it, or promote the latest `main` deployment.

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

**Red team (`scripts/redteam_offer.py`, 20 checks, run in CI by `tests/test_offer.py`).** It covers:
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

O19 suppresses timing for the 617 zero-admit rows that SIES still publishes with 0 % shares. O20 checks that every surface (fiche, search, comparator) receives the options. A mutation test seeded 5 bugs in the search filters (apprenticeship filter back, wrong facet count, missing "filles", reordering, an "internat" query losing its filter). All 5 were caught.

## Mention among bac-général admits (A3, "Mon parcours")

**The problem.** A bac-général student was placed among *all* néo-bacheliers admitted, because SIES publishes the mention ladder for all series combined.

**What SIES publishes, and what it does not.** It never publishes the mention × series table. It publishes only its margins:
- the all-series ladder, from sans mention to TBF, plus "mention not reported";
- how many admits of each series hold *a* mention: `acc_bg_mention`, `acc_bt_mention` and `acc_bp_mention`.

**Partial identification.** The bac-général share is therefore partially identified, and `journey.bg_cdf_bounds` gives its sharp bounds. Let K be the number of bac-général admits with the student's mention or lower:

    max(0, p − U) + max(0, A − om)  ≤  K  ≤  p + min(A, gm)

where:
- p is the number of bac-général admits without a mention;
- U is the number of admits whose mention is not reported;
- A is the number of admits, all series, whose mention runs from AB up to the student's;
- om is the number of admits of the other series holding a mention;
- gm is the number of bac-général admits holding a mention.

**Rules for pooling and consistency.**
- **Pooling.** Bounds are computed **campaign by campaign** and their ends are added. Pooling the margins first would drop each campaign's own constraints; this was found in review. In the random-table red team (M12), the per-campaign intervals are strictly tighter in 11,749 cases and never wider.
- **Consistency.** A campaign whose margins contradict each other is left out, with its admits. Both halves are checked: admits holding a mention, and admits without one.

**What changes for the student.**
- **Display.** "Mon parcours" shows the interval, which collapses to an exact value for cohorts that are all bac général. Each end is widened by Wilson 95 % sampling error.
- **Zone.** The zone uses the all-series share projected into the interval, that is, the closest value consistent with the data. It is flagged *incertain* if any value inside the widened interval would change it.
- **Small cohorts.** Below 10 pooled bac-général admits, the all-series view is kept and labelled as such.

**On real 2022–2025 data, about 27,300 formation × mention readings:**
- the old all-series share was *incompatible* with the bac-général bounds in 30.6 % of them;
- 524 zones change;
- the median interval width is 0.9 point, and 63 % of intervals are at most 5 points wide.

**Red team (`scripts/redteam_mentions.py`, 12 checks, run in CI by `tests/test_mentions.py`):**
- **Validity.** The bounds held on all 30,000 random tables.
- **Sharpness.** Brute force over every consistent table reaches both bounds, on 400 small tables.
- **Degenerate and inconsistent cases.** They are handled, including inconsistent no-mention margins (found in review).
- **Pooling.** Pooled bounds equal the per-campaign reference, and are never wider than pooling the margins (found in review).
- **Zones.** A zone marked certain holds over its whole interval.
- **Monotonicity.** A better mention never ranks lower.
- **Real-data premises.**
  - The by-series mention identity holds on 55,844 of 55,844 rows.
  - `pct_bg_mention` is over `acc_neobac`, not `acc_bg`. This red-team finding corrected a wrong label, and the fixture, which had the same mistake.
- **Display and method.** The interval display and the methodology text are checked.
- **Mutation test.** Four seeded bugs were all caught. A fifth "bug" proved to be an equivalent mutant: a redundant constraint, now removed.
- **Reference persona.** `verify_persona.py` also checks that each zone matches the rules, that the position used lies inside its bounds, and that the margin contains the bounds.

## Plan B: the same programme elsewhere, more accessible (formation page)

Each formation page shows, for the student's profile (series, specialties for bac général, mention, académie, stored with "Mon parcours"), up to 6 formations of the **same detailed programme** that are more accessible for that profile. The engine is the "Mon parcours" one (`journey.stage2`); `suptracker/planb.py` adds the selection rules.

**What counts as more accessible.** A suggestion qualifies in one of two ways:
- it is in a **strictly better zone**, and not uncertain;
- or it is in a zone at least as good, with access **at least 15 points higher** and a mention position that is not worse.

**What is never suggested.**
- **Unreliable readings.** Formations that are closed to the series, fragile or tiny (fewer than 20 series candidates or fewer than 10 admits), or unreadable.
- **The same applicant pool.** Schools of the same concours commun, since they share one pool of candidates.
- **More than 2 per establishment.**
- **Fee-charging private institutions, by default.** "Privé enseignement supérieur" and "privé hors contrat" may charge substantial fees, so they appear only if the student ticks a box, then flagged *frais possibles*. The number hidden is shown. Public and "privé sous contrat d'association" are always eligible.

**Order.** Suggestions come from the student's académie first, then by distance from the target (haversine on the formation coordinates).

**Already accessible.** A target that is already a safe choice gets no plan B, and the page says so.

**Libellés.** `search.clean_complement` stripped nothing when the establishment name itself contains " - " (for example, "Université Lumière - Lyon 2"). This was found while building Plan B and is fixed for search too. Plan B also shows `detail_forma`, which is often the only thing that tells two parcours of one programme apart.

**Red team (`scripts/redteam_planb.py`, run in CI by `tests/test_planb.py`).** It covers:
- independent re-derivation from "Mon parcours" that each suggestion is more accessible;
- same programme;
- no unreadable formation;
- no fee-charging private institution by default, with an exact hidden count;
- never the target or its concours pool, and at most 2 per establishment;
- académie-then-distance order, and determinism;
- safe targets get no plan B;
- API validation;
- no promise wording, and escaping;
- the libellé fix;
- latency;
- usefulness on selective targets;
- no navigation race: a late answer never fills or rebinds another formation's card (found in review).

### "Voir un plan B" in "Mon parcours"

In the positioning table of "Mon parcours", every **ambitious** or **hors profil** row has a *Voir un plan B* button. Rows that are already *cible* or *sécurité* have none, since a plan B is only useful for a hard target.

- **Where it opens.** The plan B opens under the row. It stays pinned to the visible part of the wide table, so it reads on a phone without scrolling sideways. A second click closes it.
- **Profile.** It uses the profile shown on the page, with the series validated, not a stored copy.
- **Pinning.** Each suggestion can be pinned to the simulated wish list directly, and the list audit updates in place.
- **Late answers.** Every request stamps its box. Only the latest request for a box still on the page may fill it, so a late answer, a superseded paid-private toggle or a closed row is dropped (this also fixes the same race on the formation page's toggle).

The red team adds four checks:
- **B15:** the button is only on ambitious rows, uses the page's profile, is escaped and opens and closes under its row.
- **B16:** on real data, the Plan B opened from an ambitious row reads that formation in the **same zone** as the row and never answers "déjà accessible".
- **B14 (updated):** the stamp is set before the request and checked after it.
- **B17, mutation test:** eight seeded UI bugs and two seeded rule bugs (the +15-point threshold dropped, an uncertain zone accepted) must each be caught.

## Success in licence (B1, formation page)

Each **public licence** page shows how the students who entered L1 in the same **university and broad discipline** fared. The source is SIES Note Flash 2025-29, *Tableaux réussite et passage par discipline et établissement*.

**Getting the source.** The ministry site rejects automated downloads, so the owner downloads the Excel file and commits it under `data/sources/sies_reussite_licence*.xlsx`. The warehouse build (`success.attach`) reads it, and the data workflow's fingerprint includes it, so a new file triggers a rebuild. The `suptracker-data` workflow also has a `probe_page` mode, which downloads and commits the files linked from an official page so a new source can be inspected first.

**What SIES publishes (checked on the real file).**
- **Granularity.** 70 universities × 5 broad disciplines: droit and science politique; économie and AES; arts, lettres, langues and SHS; sciences and santé; STAPS. Nothing is published per formation, so the page says the figures cover *all* the university's L1 entrants in that discipline, not this licence alone.
- **Three cohorts:**
  - the year after L1 for 2023 entrants: passage to L2, repeat, reorientation, exit (a partition of the entrants, within 1);
  - licence in 3 years for 2021 entrants;
  - licence in 3 or 4 years for 2020 entrants.
- **Expected rate and value added.** Each indicator has an observed rate, a *simulated* rate (what the entrants' profile would give at national rates) and a *value added* equal to observed minus simulated, exactly.
- **Masks.** Small cohorts are masked (`ns`), and some cells are `nd` or `.`. They are stored as NULL, never 0, and shown as "petit effectif, non publié". Rows under 100 entrants are flagged.
- **Name quirks.**
  - A university's discipline rows can carry a shorter name than its total row: "UNIVERSITE TOULOUSE 1" under "UNIVERSITE TOULOUSE 1 (CAPITOLE)". Rows are therefore grouped by block.
  - Its total row can be named differently in another sheet ("INST NATIONAL UNIVERSITAIRE" for "INU CHAMPOLLION"). These are aliased.
- **National reference.** Of the two national rows, the universities add up to *Inscriptions principales*, not *Etudiants*, so that row is the national reference for the same discipline.

**Linking a Parcoursup licence.**
- **University.** The SIES file has no establishment code, so links are made by name, through one explicit rule per university. A Parcoursup establishment is linked only if exactly one rule matches. The tricky cases are:
  - an Université de Montpellier antenna in Perpignan or Nîmes;
  - Paris 1, 3 and 13, Sorbonne Université, Paris 2's Melun antenna;
  - Lyon 1, 2 and 3; Rennes and Rennes 2; Bordeaux and Bordeaux Montaigne.
  - Paris-Saclay campuses that SIES may count under Évry or Versailles stay **unlinked**, as do INALCO, Sciences Po, lycées and private institutions.
  - Coverage: 97 % of public licences.
- **Discipline.** The licence's programme (`fil_lib_voe_acc`) maps to one of the five disciplines. Double or cross-field licences (MIASHS, droit-économie, sciences sanitaires et sociales…) get no figure rather than a guess.

**What is shown.** For each cohort:
- the university's rate;
- the expected rate with its gap ("écart", in points);
- the national rate for the same discipline;
- a bar of what became of the entrants one year later, for the university and for France.

The page says these are past cohorts, not chances of success, and that the gap to the expected rate does not rank universities.

**Red team (`scripts/redteam_success.py`, run in CI by `tests/test_success.py`).** The workbook is re-read independently and the B1 tables are rebuilt in memory. The checks are:
- **S1.** SIES identities: discipline sums, universities = *Inscriptions principales*, partition, value added = observed − simulated, rate = count / entrants.
- **S2.** Stored = published, cell by cell (8,689 cells), and masked cells stay NULL.
- **S3.** The national reference.
- **S4.** Every university has a rule, a label and all three cohorts.
- **S5.** A truth table of hard names, no double link, only public licences, coverage.
- **S6.** The discipline map.
- **S7.** The page block shows the right university, discipline and national rows; no block for non-licences; private licences are out of scope.
- **S8.** UI escaping and wording.
- **S9.** The methodology text.
- **S10.** The published warehouse equals a fresh rebuild.
- **S11.** A mutation test: 15 seeded bugs, all caught. Among them: `ns` read as 0, `Etudiants` as the national row, rows grouped by their short name, Psychologie filed under droit, an unanchored Perpignan rule, Paris-Saclay taking its Évry campus, a typographic apostrophe dropped before folding.

The red team found two real link bugs while B1 was built, both now fixed:
- "Campus d’Evry" was folded to "devry", so it was linked to Paris-Saclay.
- The Guyancourt campus of Paris-Saclay was linked to UVSQ.

## Data foundation: establishment register, reliability, sources, glossary (sprint 3)

This is the base the next sprints build on: success, gateways and insertion are all keyed by establishment.

**Paysage ids.** SIES publishes, on every Parcoursup campaign, the Paysage id of a formation's parent establishment (the university of a UFR or an antenna) and of its component. `core.formation_year` now carries both. What the data showed:
- **Coverage.** The id is filled for about 96–98 % of public licences, BUT and PASS in 2022–2024. It is rare for lycée formations (BTS, CPGE: 15–25 %).
- **2025 is empty.** The id is **empty in the 2025 export**. `ref.formation_etablissement` fills it from the cartographie, then from the same formation's previous campaign, and records the source of every id.

**Register and successions.**
- **Register.** The MESR register *Principaux établissements d'enseignement supérieur* (245 rows, ingested by the data workflow) gives `ref.etablissement`.
- **Mergers and renamings.** Merged or renamed universities appear in older campaigns under a former id. `ref.succession` derives the successor from the data, in two ways:
  - **transition:** the same formation moves to a register id the next campaign;
  - **UAI vote:** the old id's formations are listed under a UAI that the register gives, as current or former UAI, to one establishment.
- **Rules.** A succession needs 80 % of the evidence and at least 5 formations. A former UAI shared by two establishments names neither, so it is ignored (Antilles-Guyane, and one shared by Polynésie and Nouvelle-Calédonie).
- **Found this way:** Bourgogne → Bourgogne Europe, Franche-Comté → Marie et Louis Pasteur, Brest → Bretagne Occidentale, Montpellier 3 → Paul-Valéry, Saint-Étienne → Jean Monnet, Toulouse III → Université de Toulouse, Rennes 1 → Université de Rennes, Toulouse 1 → Capitole, Nîmes.

**Coverage (2025).** 93 % of public licences and 97 % of public BUT reach the register.

**B1 on ids.** The 70 SIES universities map to Paysage ids (`success.SIES_PAYSAGE`, checked against the register).
- **The id comes first.** On the 2,966 formations that both methods link, the id and the name rules **never disagree**.
- **Ambiguous campuses.** The id settles the Paris-Saclay campuses that the name rules left unlinked: they go to Évry or UVSQ.
- **Fallback.** Formations without any id (new in 2025) keep the name rule, and their figures are graded B.

**Maillon and reliability (`evidence.py`).** Every figure of a journey step travels in one envelope: value, national and expected references, granularity, population, cohort, headcount, source, link method and caveat. Reliability is graded by fixed rules:
- **A:** at least 100 people, a cohort 3 years old at most, an official id;
- **B:** fewer than 100 people, an older cohort, or a link by name;
- **C:** fewer than 30 people;
- **no grade:** a masked value.

The chain is never multiplied into one score: each step describes a different population. B1 shows the grade, with its reasons, under each indicator.

**Source register (`sources.py`).** Every dataset is listed with:
- producer and access (`ods`, `owner_upload` or `planned`);
- granularity, keys and what it feeds;
- status, and the sprint for planned sources.

The *Glossaire* page lists the sources for students, including the planned ones (IPS, IVAL, MonMaster, InserSup, Inserjeunes).

**A5 glossary (V1, `#/glossaire`).** 22 Parcoursup and statistics terms in plain French, searchable. Each term links to the detailed method when there is one.

**Red team (`scripts/redteam_referentiel.py`, run in CI by `tests/test_referentiel.py`).** The links are rebuilt in memory and each rule is re-derived independently in Python. The checks are:
- **F1.** Register integrity; shared UAIs never vote.
- **F2.** SIES's own id kept; the 2025 fill order.
- **F3.** Successions re-derived with the red team's own thresholds.
- **F4.** Succession plausibility by name.
- **F5.** Coverage.
- **F6.** The SIES → Paysage table.
- **F7.** B1 by id vs by name, and link labels.
- **F8.** Grades re-derived everywhere they are served.
- **F9.** Source register ↔ ingested datasets and committed files.
- **F10.** Glossary methods, wording and escaping.
- **F11.** The badge.
- **F12.** The published warehouse equals a fresh rebuild.
- **F14.** Known mergers resolve to the right current establishment.
- **F13, mutation test:** 11 seeded bugs, all caught.

**What it found while being written:**
- the register's shared former UAIs;
- a test blind spot: the red team read the thresholds it was testing from the module itself;
- the Brest label (now *Université de Bretagne Occidentale*).

## The student's lycée (sprint 4, "Mon parcours")

In "Mon parcours", the student can pick their lycée (optional). The page then shows a **"Ton lycée, en contexte"** card, and the académie follows from the lycée. The page says the lycée **does not change the positioning**: no open dataset crosses Parcoursup admissions with the lycée of origin.

**Sources.** Both come from the Education ministry portal and are ingested by the data workflow (`config.Dataset.base`):
- *IPS des lycées*: rentrée 2023 and later;
- *IVAL des lycées GT*.

**What the data showed.**
- **IPS:**
  - one row per lycée and school year (3 rentrées, ~3,650 lycées), with numbers stored as text;
  - the GT-track IPS is empty for vocational lycées;
  - the reference IPS (académie, France) is published per lycée **type** (LEGT, LPO, LP) and **sector**, so the card compares each lycée to the average of its own type and sector.
- **IVAL:**
  - sessions 2012–2025, ~2,300 lycées; the card shows the 3 latest bac sessions of the file;
  - value added is often negative (2,596 rows on 2023–2025);
  - the académie label is **truncated** ("NORMAIE", "CLERMONT-FERRA"), so the académie always comes from the IPS file. It maps to the Parcoursup académie by name, except Saint-Pierre-et-Miquelon and Wallis-et-Futuna, which have no Parcoursup offer.
- **The one lycée effect SIES publishes** is `pct_etab_orig`, the share of a formation's admits who came from that same establishment: 26 % on average for BTS and 10 % for CPGE hosted in lycées. When a formation is in the student's lycée, both "Mon parcours" and the formation page say so, with that official share.

**Maths expertes.** It can be ticked with a maths specialty. The page says Parcoursup data do not publish Terminale options, so the option does not change the positioning.

**Reliability.** The IVAL rows carry the A/B/C grade of `evidence.grade`, computed by the server: headcount present at the bac, session age, official UAI.

**From the search bar.** A search that names a lycée ("lycée valbonne") still lists the formations that lycée hosts, but first asks **"C'est ton lycée ?"** and offers to set it as the profile's lycée in one click. The click keeps the rest of the profile, sets the académie and opens "Mon parcours". The match runs in the browser on the full list, and the suggestion is dropped if the user has navigated away meanwhile. This came from the owner's first test of the feature.

**Privacy.** `/api/lycees` sends the whole list (3,662 lycées, ~170 kB gzipped, cacheable) and takes **no parameter**. The page searches it locally, so the chosen lycée stays in the browser and never reaches the server or the audience measure.

**Red team (`scripts/redteam_lycee.py`, run in CI by `tests/test_lycee.py`).** The checks are:
- **Y1.** Latest school year, values equal to the raw file.
- **Y2.** IPS references of the lycée's own type and sector.
- **Y3.** Académie mapping, with a truth table; IVAL's truncated labels are never used.
- **Y4.** The 3 latest IVAL sessions equal the raw file, and negative value added is kept.
- **Y5.** The list is served whole, without parameter and cacheable, with server-side grades re-derived independently.
- **Y6.** Privacy: no API call or audience event carries the lycée.
- **Y7.** The same-lycée share equals the official field.
- **Y8.** UI escaping and wording; the same-lycée badge appears only for the student's own lycée.
- **Y9.** Methodology and glossary.
- **Y10.** Mutation test: 11 seeded bugs, all caught.

## Next-campaign "repère": calibrated ranges, back-tested (sprint 5, "Mon parcours")

**Why not a probability.** Open data cannot calibrate a chance of admission: SIES publishes the mentions of *admits*, never those of *candidates*. What can be calibrated honestly is how the published indicators move from one campaign to the next. For each formation and the student's mention, the "Mon parcours" table therefore shows a **repère for the next campaign**:
- an 80 % range for the official access rate;
- for bac général, an 80 % range for the share of admits with the student's mention or lower (all series);
- for bac général, how often the row's zone was confirmed the next campaign in comparable cases.

**What the data showed (`suptracker/calibration.py`).**
- **Access rate:** it moves about ±9–10 points a year. 2025 shifted down: a 10th-percentile change of −21 points, against −15 in earlier years.
- **Share of admits:** it is stable in large formations (mean error 4.7 points at 100+ admits) and noisy in small ones (13.8 points under 30). The ranges are therefore set per stratum: selectivity × number of past campaigns for the access rate, admits headcount for the share.

**Method, fixed before looking at the hold-out.**
- **Point forecast of the access rate:** among last campaign, mean of the last two, and mean of all, the predictor with the lowest error on 2024 (mean of the last two; on 2024 it ties with the overall mean).
- **Point forecast of the share:** counts pooled over every campaign, as "Mon parcours" does.
- **Ranges:** the point forecast plus the 10th–90th percentiles of the errors on the 2023 and 2024 transitions.
- **Hold-out:** 2025 is forecast without being seen. **76.6 %** of the 2025 access rates and **76.5 %** of the shares fell in their 80 % range. The page prints these figures as they are, read from the data, never hard-coded.
- **Served ranges:** the ranges served for 2026 use the errors of every transition, 2025 included.

**Zone stability.**
- **How it is measured:** the zone computed from campaigns up to *Y* − 1 is compared with the zone the next campaign alone gives. Both use the reading the page shows for bac général: the all-series share is projected into the bac-général bounds when they are usable (`journey.zone_reading`, shared by stage 2 and `calibration.zone_of`). Formations closed to bac général in practice are left out, like on the page.
- **Results:** zones not flagged *incertain* held 79–81 % of the time (95 % for "hors profil"); zones flagged *incertain* held 53–73 %. This confirms the *incertain* flag after the fact.
- **Scope:** it is shown only for bac général, because bac techno and pro zones use an estimated series access that is not comparable.

**Red team (`scripts/redteam_calibration.py`, run in CI by `tests/test_calibration.py`).** The checks are:
- **K1.** An independent numpy re-implementation of the hold-out gives the published coverage exactly.
- **K2.** The predictor is chosen on 2024 only.
- **K3.** The served ranges stay within bounds and contain the point; their width equals the stratum's error range; only current formations get one.
- **K4.** Pooled shares.
- **K5.** Zone stability is re-derived independently (bac-général bounds summed campaign by campaign) on the next campaign alone; uncertain zones are less stable.
- **K6.** The API attaches the right forecast and stability.
- **K7.** The page reads the coverage from the data, says it is not a chance, and gates the series-specific parts.
- **K8, mutation test:** 10 seeded bugs, all caught: the hold-out leaking into its own history, 90 % quantiles announced as 80 %, the predictor chosen on the hold-out, a same-year "stability", a stability measured on the all-series zone instead of the displayed one, unclipped ranges, and UI bugs.
- **K9.** For every zone stage 2 shows (three formation types, two mentions), the back-test classifier gives the same zone and *incertain* flag.

## Success beyond licence: BUT and master (sprint 6, formation page)

**What the student sees.**
- **On a BUT page, a "Réussite en BUT" card** shows:
  - the share of the university's BUT entrants who got the diploma in 3 years, with the rate expected from their profile and the national rate;
  - what the graduates did the next year: continuation, and the shares in master, business school and engineering school;
  - the national rate of the BUT's specialty;
  - two national rows matching the student's profile, read from the browser: their bac series (with their général doublette when SIES publishes it) and their mention.
- **On a licence page, an "Et après la licence : le master" card** shows:
  - for the same university and discipline as B1: the M1 → M2 transition with the full outcome bar, and the master obtained in 2 or 3 years, each with the expected and national rates;
  - nationally: the share of licence graduates entering master each year from 2021 to 2024, and the 2017 L1 cohort followed to master, by the student's bac type and by their mention.

**Data (`suptracker/poursuite.py`).** Five SIES workbooks that the owner commits under `data/sources/`:
- **The files:**
  - BUT: NF 2025-26, "Tableaux par établissement" and "Tableaux réussite en IUT";
  - master: NF 2025-30, "Réussite et passage par discipline et établissement", "Réussite en master" and "Poursuites d'études en master".
- **Recognition:** each file is recognised by its sheets and table titles, not by its name. The B1 licence workbook is not mistaken for one of them.

Facts checked on the real files before coding:
- **BUT is per university only.** No IUT, no specialty. Success is credited to the university of first enrolment. Nothing is published below 100 entrants.
- **Specialty, series and mention are national.** They are margins: SIES never crosses them, so "MATHS+SES with Assez bien" does not exist. The page shows separate rows and says so.
- **Master is per university × the five B1 disciplines.** The population is every M1 entrant, wherever they come from, not the graduates of this licence. Nothing is published below 50 entrants (measured: the largest masked cohort is 46, the smallest published is 50).
- **National reference.** The universities add up to "Inscriptions principales", which is therefore the reference, exactly as in B1. "Etudiants" counts a person once and does not add up.
- **Names.** The same university is spelled differently from one table to the next ("CY CERGY PARIS UNIVERSITE (EPE)", "CY CERGY UNIVERSITE"). Discipline rows can carry a shorter name than their block. Rows are grouped by block, and every spelling maps to the B1 university through `NAME_ALIASES`.
- **Two published quirks, shown as is.**
  - At Grenoble, the seven M1 outcome shares add up to 99.0 % (alsh) and 99.5 % (all disciplines).
  - The 2017 chain's "master in 5 to 7 years" can exceed "entered master after 3 or 4 years" (L1 SVT: 32.8 vs 32.6), because some students enter master later.
- **Two national sources disagree.** The continuation of licence graduates into master differs between the two national files (droit 2024: 78.3 vs 79.5, different groupings). The page uses the "Réussite en master" table, which has the five B1 disciplines and four years.

**Links.**
- **BUT → university.**
  - The Paysage id comes first: 792 of 820 formations link this way.
  - The IUT de Toulouse has no id in the register; one explicit rule links its 20 formations to Toulouse 3 (grade B).
  - The IUT de Nîmes is a component of the Université de Montpellier (confirmed by the owner), but its formations carry the id of the Université de Nîmes, which has no BUT row. An explicit site override links its 5 formations to Montpellier (grade B). An override is allowed only where the id names a university with no BUT row, and the red team checks this.
  - The Polynesia antenna of the IUT de Bordeaux carries the id of a university with no BUT row and stays unlinked rather than guessed. In total, 817 of 820 formations are linked.
  - On real data, the B1 name rules and the id agree on all 116 formations where both apply.
- **BUT → specialty.** Every Parcoursup BUT programme (36 labels) maps to one of the 24 SIES specialties. The "parcours …" suffix is dropped, and there are 3 explicit aliases, among them "Science des données", the 2024 name of STID.
- **Licence → master.** The master card uses exactly the B1 link (university, discipline).

**Reliability.**
- **Grades.** Every university figure is an `evidence.maillon` with a new granularity, "l'université, toutes spécialités". The cohorts (2021) are more than 3 years old, so they are graded B at best.
- **National rows.** National rows are references and carry no grade.
- **No multiplication.** No figure is multiplied by another.

**Red team (`scripts/redteam_poursuite.py`, run in CI by `tests/test_poursuite.py`).** On the real data, 12/12 checks pass and 25/25 mutants are caught.
- **P1.** Independent re-read of every cell: 6,637 cells, 0 differ. Masked cells are NULL, never 0. The committed warehouse equals a fresh build.
- **P2.** Every block maps to one B1 university, with no collision inside a table.
- **P3.** Identities:
  - the universities add up to "Inscriptions principales", and disciplines add up to their block;
  - rates equal counts, and VA = observed − simulated;
  - the M1 outcomes partition the entrants (Grenoble listed);
  - BUT graduates equal the BUT successes;
  - the national tables agree with each other.
- **P4.** The masking rule holds at the measured thresholds.
- **P5.** BUT links: truth table of the hard sites (Toulouse, Nîmes → Montpellier, Polynesia), no override over a usable id, id vs name rules, 100 % of programmes mapped to a specialty, and a specialty truth table.
- **P6.** The licence → master link is B1's for all 3,202 linked licences.
- **P7.** The API blocks match the warehouse, with grades by the fixed rules and the out-of-scope cases handled.
- **P8.** National margins: doublettes use the journey's specialty codes, and the chain is ordered.
- **P9.** Spellings: each of the 153 SIES spellings (rows and blocks) shares a distinctive word and its numbers with the university it is mapped to (Cergy is not Sorbonne, Paris 1 is not Paris 2). Two explicit exceptions, each with its reason: Chambéry → Savoie Mont Blanc (its seat), "Inst national universitaire" → INU Champollion.
- **P10.** National margins = published: the three national workbooks (BUT by series, doublette, mention and specialty; master continuation by discipline and year; the 2017 chain) are re-read by fixed positions with the red team's own label rules. All 96 rows and 320 values match, with the right code for each label. A SIES specialty code is matched to the journey's code by a word of its label, not by copying the build's table.
- **P11.** The page escapes every stored string, keeps the wording card by card, never multiplies rates, and keeps the profile in the browser with its values validated.
- **P12, mutation test.**
  - Data mutants: "Etudiants" as the reference, masked as 0, an alias collision, discipline rows not grouped by block, a loose IUT rule, the Nîmes override dropped, a wrong specialty alias, the master block off B1's discipline.
  - National mutants: "Très bien" and "Bien" swapped, PHY_CHI read as SVT, bac général and technologique swapped, droit and eco swapped, an L1 discipline mapped to another, the 2nd- and 3rd-year columns swapped, a graduation year shifted, a national row emitted twice (Codex: duplicates are counted on the row list, before the lookup keeps one).
  - The alias collision used to slip through without `--real`: CY Cergy's figures under Sorbonne's name collide with nothing, because Sorbonne has no BUT row. P9 now catches it.
  - UI mutants: escaping (3), wording (2), a multiplied chain, the profile sent to the server, the stored series trusted, the card not wired.

**UI check (Playwright):** light, dark and mobile, including an unlinked IUT. 0 JS errors, no horizontal scroll.

## Gateways: reorientation after L1 and the university's masters (sprint 7, formation page)

**What the student sees.**
- **On a licence page, a "Passerelles" card** shows, for the same university and discipline as B1:
  - **after the L1:** the share of L1 entrants who change course the next year, and where they go: outside the university (BTS in apprenticeship or not, CPGE, business or engineering school) or at the university (BUT, nursing diploma), against France;
  - **after the licence:** the university's masters in this discipline on MonMaster:
    - offers, admitted students and applications (labelled as vœux);
    - the share of admitted students already enrolled at the university, with France as reference;
    - where the admitted students came from;
    - the largest master mentions.
- **On a BUT page, one line:** how many BUT graduates the university's masters admitted, against France.

**Data (`suptracker/passerelles.py`), checked on real data before the design.**
- **Reorientation sheet** (B1 workbook, NF 2025-29, 2023 entrants):
  - every rate is a share of the **L1 entrants**, not of the reoriented students;
  - reoriented = hors université + à l'université, exactly for every university;
  - the published detail is **not exhaustive**, and the page says so; nothing is computed by difference;
  - masked below 100 entrants (largest masked cohort 95, smallest published 101);
  - the universities add up to "Inscriptions principales"; on that national row, hors + université exceeds the total by 1 to 3 students (multiple enrolments);
  - one spelling differs from B1's ("UNIVERSITE PARIS 13 SORBONNE PARIS NORD", explicit alias);
  - where both are published, entrants and reoriented equal B1's "Devenir" table.
- **MonMaster** (SIES open data, ingested by the data workflow):
  - 2024 and 2025 sessions; the 2023 file has another layout and no "admitted from the same establishment" field;
  - one row per offer (`ifc`: programme × site × apprenticeship), unique per session;
  - identities hold on every row: origins add up to the admitted students, main + complementary phase = total, the funnel never grows, published percentages = counts; nothing is masked;
  - **units:** applications summed over programmes are vœux; admitted students are people;
  - **never a chance:** no proposals / applications ratio is shown.
- **Link.**
  - Masters are tied to a licence through B1's university (its Paysage id, 69 of the 70 universities found in MonMaster) and the broad discipline (`MASTER_DISCIPLINE`).
  - MEEF masters (teaching, open to every licence) are kept apart; mixed droit-éco-AES and theology masters get no discipline.

**Red team (`scripts/redteam_passerelles.py`, run in CI by `tests/test_passerelles.py`).** On the real data, 8/8 checks pass and 13/13 mutants are caught.
- **Q1.** The reorientation sheet is re-read cell by cell (5,292 cells, 0 differ). Masked cells are NULL, never 0. The warehouse equals a fresh build.
- **Q2.** Identities, masking at 100, the entrants' sum, the cross-check with the "Devenir" table, and every block a B1 university.
- **Q3.** MonMaster staging: 16,257 offers, totals = raw, origins = admitted students, funnel.
- **Q4.** Every discipline label is mapped explicitly; truth table; MEEF never in a discipline.
- **Q5.** Masters aggregates are re-derived from the raw rows with pandas for every university × discipline pair (295 pairs, 277 with masters).
- **Q6.** The API rows and grades follow the fixed rules; out-of-scope cases are handled; BUT → master counts are re-derived.
- **Q7.** The page escapes stored strings and keeps the wording. It shows no proposal ratio and no remainder by difference.
- **Q8, mutation test.**
  - Data mutants: "Etudiants" as the national row, masked as 0, no block grouping, MEEF in its listed discipline, a mixed master guessed as droit, masters not restricted to the university.
  - UI mutants: escaping (2), the vœux caveat, the incomplete-detail caveat, a proposal ratio, a remainder, the card not wired.

**UI check (Playwright):** light, dark and mobile. 0 JS errors, no horizontal scroll.

## Does the job match the training? (sprint 8 follow-up, Céreq, formation page)

**What the student sees.** A card "Le métier correspond-il à la formation ?" on the formation page. It compares the group of the diploma the formation prepares with all leavers. For a licence, it adds the master of the same field ("si tu poursuis"). The rows:
- the share of the employed who say their job matches their training, 6 and 3 years after leaving;
- the share employed at their skill level (3 years);
- the employment rate (among all leavers);
- open-ended jobs, managers and intermediate professions (among the employed);
- the median monthly income.

Each row states its denominator. A BUT page explains why it has no figure.

**Data (`suptracker/cereq.py`), checked on the real file before the design.**
- **Source.** The Céreq Génération 2017 survey: 746,000 young people who left initial education in 2016-2017, surveyed in 2020 (25,000 respondents) and 2023 (8,750). The file comes from the "chiffres clés par diplôme" data visualisation. A button of an interactive application produces it, so no robot can fetch it: the owner commits it under `data/sources/`, and it is recognised by its content.
- **Granularity.** About twenty groups of HIGHEST diploma, national, nested by level and broad field. Every group adds up to its parent (±1), and every distribution to 100 (±2).
- **The adequacy indicator.** `correspondance_ok` is declared by the employed at 3 and 6 years. `competence_ok` is published at 3 years only.
- **Population.** A national figure for everyone whose highest diploma is in the group, not this formation's students. Someone who goes on studying joins another group, and the page says so.
- **Link: one fixed rule per filière.**
  - **BTS.** Industrial or tertiary by the NSF field of the diploma: digits 7-9 of the Inserjeunes MEFSTAT11 code, digits 4-6 of a CFD code, matched on the same BTS title or its options, in any establishment. NSF 200-255 is industrial, 300-345 tertiary. On real data, 84 % of BTS get a field. The others (renamed BTS such as SIO, CIEL, Banque) get the bac+2 total.
  - **Licence.** The B1 discipline gives humanities-law-management or sciences. The card shows bac+3/4, plus the master of the same field.
  - **Other filières.** IFSI and EFTS map to health and social work. Engineering and business schools map to their own group. Scientific CPGE map to engineering schools, ECG/ECT to business schools.
  - **No figure.** BUT (created in 2021, absent from the 2017 cohort), PASS, literary CPGE and other formations get none.

**Red team (`scripts/redteam_cereq.py`, run in CI by `tests/test_cereq.py`).** On the real data, 6/6 checks pass and 12/12 mutants are caught.
- **C1.** The workbook is re-read cell by cell: 86 rows × 16 indicators, 0 differ.
- **C2.** Hierarchy sums and partitions hold; `competence_ok` is published at 3 years only.
- **C3.** The link of all 14,252 formations of the latest campaign is re-derived with the red team's own rules, plus a truth table of real BTS titles.
- **C4.** The API serves the stored values; the reference is all leavers; "si tu poursuis" appears for licences only.
- **C5.** The page escapes stored strings and states every denominator and caveat; published shares are never summed.
- **C6, mutation test.** NSF read at the wrong digits (a bug made and caught during development), sides swapped, BUT given the old DUT figures, discipline ignored, horizons swapped, a neighbouring column read, an unpublished value stored as 0, and 5 UI mutants.

**UI check (Playwright):** BTS, licence, CPGE, BUT and an unknown-field BTS, in light, dark and mobile. 0 JS errors, no horizontal page scroll.

## Interface for 16-20 year olds, phone first (UI lot 1)

The app was re-read as a student on a phone (iPhone 13): the menu took a quarter of the first screen, the home page
opened on column names (`voe_tot`, `nb_voe_pp`), search filters filled the first screen before any result, the tone
mixed "vous" and "tu", and 83 of 121 controls on a formation page were under 32 px.

**What changed:**
- **Home page with three doors:** "Je cherche une formation", "Je pars d'un métier", "Je veux savoir où je me situe",
  plus example searches. No technical note.
- **Bottom tab bar on a phone:** Chercher, Mon parcours, Métiers, Mes vœux, and "Plus" (Comparateur, Spécialités,
  Qualité des données, Glossaire). The current tab is marked (`aria-current`); counts hide at 0. The top menu stays on wide screens.
- **Vouvoiement everywhere** a student reads (the owner's choice): page, method texts, glossary, server messages; the
  older "tu" texts (lycée, Mes vœux, métiers) now say "vous" too.
- **No column names** in method texts or labels (the formation header says "n° Parcoursup", "code établissement").
- **Touch targets of at least 44 px** on a phone; the small "i" buttons keep their look with a hidden 45 px zone.
- **Search results first:** filters fold under "Filtrer" on a phone (open on wide screens); active filters stay visible
  as removable chips. The first result moved from below the first screen to 242 px.

The honesty rules are unchanged: no chance, no single score, ranges and parts d'admis.

**Red team** (`scripts/redteam_ux.py`, run by `tests/test_ux.py`; `--browser` measures real phone screens with Playwright):
8/8 checks, 14/14 mutants caught.
- **X1.** No "tu / ton / ta / tes / toi / le tien / t'a" or tu-imperative in any student-facing text (the page script
  without comments, the shell, method texts, glossary, server string constants).
- **X2.** No column name in method texts, glossary or the home page.
- **X3.** Navigation: the 4 main pages in the bottom bar, the 4 others under "Plus", every top-menu page reachable, the tab marked.
- **X4.** The 44 px rule in the phone CSS; the "i" zone.
- **X5.** Filters folded on a phone, open on a wide screen, active ones removable and escaped (run with Node).
- **X6.** Home: three doors, escaped examples, no technical note (run with Node).
- **X7.** `--browser`: 12 phone screens (light and dark): 0 JS errors, no horizontal scroll, every control ≥ 44 px,
  the first search result on the first screen, no column name in the visible text.

## Design system and page structure (UI lot 2, Claude design guidelines)

Lot 2 applies the Claude design guidelines to the student pages: a summary before the detail, cards used sparingly,
state shown by form and semantic colour, no emoji as markers, one type scale, self-hosted fonts, reduced motion.

**Measured on a phone (iPhone 13), same formation and job, before → after:**
- formation page (Licence Psychologie, Caen): **31.8 → 9.4 screens**, the summary in the first screen;
- job page (assistant/e en ressources humaines, 37 diplomas, 1 094 formations): **138.6 → 5.8 screens**.

**What changed:**
- **Design tokens** (`style.css`): five font sizes (`--fs-xs` 12 to `--fs-xl` 28 px), three radii (`--r-sm`, `--r-md`,
  `--r-pill`), a "prune" accent with neutrals biased toward it, light and dark. The zone colours are their own tokens
  (`--zone-securite`, `--zone-cible`, `--zone-ambitieux`), never the accent, so a zone never reads as a link.
- **Fonts, self-hosted** (`static/fonts/`, SIL OFL): Bricolage Grotesque for titles and key figures, Figtree for text.
  No request to a font host, so no visitor's address leaves the site. (Atkinson Hyperlegible was tried first and dropped:
  its slashed zero made "2025" read as "2Ø25".)
- **Formation page:** one highlighted card first, **"L'essentiel"**, with four tiles: the official access rate, **your
  zone** (a coloured pill filled from the same Plan B answer as "Mon parcours"; without a profile, a link to it), admits
  and places, and the number of jobs of the Onisep sheet. It says "pas des chances d'admission". Then four tabs named
  after the student's questions: **Y entrer** (indicators, forecast, offer, timing, lycée, Plan B, funnel, position),
  **Réussir et poursuivre** (success, master, gateways, licence → master, BUT), **Emploi et métiers** (insertion, Céreq,
  Onisep jobs), **Historique** (lineage). Inside a tab, sections are plain blocks separated by a rule, not cards. An empty
  tab is not shown. Tabs have ARIA roles and arrow-key navigation; each tile opens its tab.
- **Job page:** a summary (minimum level, number of diplomas and formations, the 2030 reading with sprint 16's fixed rule:
  all read families agree or "Pas de conclusion", the ILO task-score range with "pas un risque de perte d'emploi"), then
  two tabs, **Diplômes et formations** (one folded block per diploma, opened when it holds the formation the student came
  from) and **Avenir du métier** (2030, BMO, AI, codes).
- **Drawn SVG icons** replace the emoji of the home doors and offer options; they are hidden from screen readers.
- **Reduced motion:** `prefers-reduced-motion` turns off animations and transitions.

Every red-team-checked caveat is kept word for word; only new texts follow the plain-language guideline.

**Red team** (`scripts/redteam_ux.py`, X9-X13; 13/13 checks, 13/13 design mutants and 14/14 lot-1 mutants caught):
- **X9.** Tokens: exactly five sizes and three radii, every size and radius in the stylesheet goes through them (chart
  marks of 2-4 px excepted), zone tokens in all three themes and distinct from the accent, reduced motion present.
- **X10.** No font host anywhere (Google Fonts, Typekit, Bunny...), every `@font-face` file shipped, each family with its licence.
- **X11.** No emoji in the page script or shell; offer options and home doors are drawn icons.
- **X12.** Run with Node: the summary has its four tiles and caveat, values escaped, the zone pill from Plan B (neutral zones
  in ink), tabs with roles where only the first panel shows and empty groups are dropped, the summary before the tabs, the
  job page folded by diploma.
- **X7** (`--browser`) now also opens a formation and a job page on a phone: the summary on the first screen, at most 14
  and 9 screens.

## Proposal rates by doublette and by bac route (sprint "Doublettes")

**What the data really holds (checked on the real warehouse first):**
- The SIES specialty files publish, per GROUP of formations (e.g. "Licence Sciences juridiques"), national, bac général
  only, and per doublette: candidates, candidates with at least one proposal, and acceptations.
- **The column named "voeux" counts candidates (people).** Its acceptations equal the formations' bac général admits
  (34 576 vs 34 550 for Licence Sciences juridiques in 2025), while it is 4× smaller than their vœux (90 397 vs 347 976).
  It is now ingested as `n_candidats`, so the data-quality page no longer says "missing".
  The owner's CSV export of the same dataset (`data/sources/fr-esr-parcoursup-enseignements-de-specialite-bacheliers-generaux-2.csv`,
  registered as a cross-check) names the column "Nombre de candidats bacheliers ayant confirmé au moins un vœu"; its
  13 455 rows for 2022-2024 equal the ingested ones, and red team D1 compares them row by row. It also shows that L.AS
  already had about 266 000 "candidates" in 2021, about 70 % of all bac général candidates, which is implausible: this
  supports the counting-break rule below.
- **There is no doublette for bac techno or pro.** Each formation publishes its own counts per series: the per-route
  ("voie") proposal rate of that formation.
- **Counting break.** In three groups (Licence L.AS, Sciences de l'univers, Formation générale aux métiers de
  l'ingénieur), the 2023 and 2024 rows count 2-3× more "candidates" while the proposals stay flat (L.AS: 96 307 →
  272 454 → 262 625 → 103 979 candidates for about 55 000 proposals each year). A fixed rule leaves such campaigns out of
  every rate of the group:
  - it applies to groups with at least 2 000 proposals a year;
  - a campaign is left out when it has more than 2× the smallest candidate count, with proposals under 1.5× the smallest;
  - the page lists the excluded campaigns.
  - in "Mon parcours", a group's left-out campaigns are also left out of its national denominators: the destination
    share and the index compare the same campaigns (Licence L.AS for Maths + SVT: 11.9 %, not 5.8 %).

**What changed (`suptracker/doublettes.py`, `mart.spe_group`, `mart.spe_break`):**
- **Route colours.** General, techno and pro have their own colour tokens (`--voie-bg/bt/bp`, light and dark), far
  from the zone colours and the accent. They always appear with the route's name.
- **Formation page, tab "Y entrer": a "Selon votre bac" block.**
  - The proposal rate of each route for THIS formation, with fewer than 20 candidates flagged.
  - The proposal rate of each doublette in the formation's group, national. The student's doublette comes first, then
    all bac général candidates, the main doublettes and "Autres doublettes".
  - A formation without a group (1 077 of 14 252) says no doublette figure exists.
- **"Autres doublettes"** (owner's rule).
  - In a group, a doublette with fewer than 20 candidates over the campaigns is rare (2 931 of 5 603 group × doublette
    pairs).
  - The rare ones are pooled; the bucket replaces the student's doublette only when that doublette is rare.
  - It is always labelled as an estimation.
- **The student's doublette in THIS formation: an estimate** (owner's request after the preview). No open data
  crosses doublette × establishment: the owner's CSV and the SIES exports stop at the group of formations.
  - The figure is this formation's published bac général proposal rate × the doublette's ratio in its group (doublette
    rate / all bac général candidates of the group, pooled, counting breaks left out), capped at 100.
  - It is the same construction as the site's per-series estimate. Example: Licence Psychologie, Caen, SES + HGGSP:
    45.9 % × 48.8 / 54.6 = 41.0 %.
  - It is always labelled "estimation", with its calculation and the assumption that the national ratio holds in this
    establishment. The national detail of the group stays below it; Mes vœux and the 4-year curve use the same estimate.
- **Évolution sur 4 ans.** Two new charts in the route colours:
  - each route's rate for the formation;
  - the student's doublette (or the bucket) next to all bac général candidates of the group.
- **Mon parcours, step 2.**
  - The doublette's proposal rate comes first, with a bar; rows stack on a phone.
  - A rare doublette no longer leaves an empty list: its filières are shown with each one's "Autres doublettes"
    estimation, and a note explains why.
- **Mes vœux.** Each vœu shows the student's doublette rate in its group (national), or the bucket.
- One figure everywhere: stage 1, the formation page, the vœux list and the curves read the same rows. The profile picks
  the row in the browser; it is never sent with the formation page.

**Red team** (`scripts/redteam_doublettes.py`, run by `tests/test_doublettes.py`): 10/10 checks on real data, 21/21 mutants
caught, built in memory.
- **D1. Units.** On real data: acceptations equal the formations' bac général admits (±5 %) in 80 % of the groups (the
  rest is the group mapping), with candidates below the vœux everywhere they match. The audit maps `voeux` to `n_candidats`.
- **D2. Independent re-derivation.** Every figure of a group is recomputed: each doublette, all candidates, the bucket,
  pooled and per campaign. The break rule is re-implemented, and the build is re-run on a scratch copy with a crafted
  L.AS-like group.
- **D3. Rules.** The threshold of 20 and the bucket, with the Python twin and the page twin compared on crafted cases.
- **D4. Route rates** re-derived from the published counts of each campaign.
- **D5. Colour distances,** by token name, in every theme.
- **D6. One figure everywhere.** Stage 1, the formation page, the vœux list and the curves agree.
- **D7. Wording.**
- **D8. The page run with Node on hostile names,** including a rare doublette in Mon parcours.
- **D10. The per-formation estimate** re-derived with independent arithmetic on real formations, compared with the page
  twin (Node) and the vœux list, and checked for the cap at 100 and its labelling.

**After merging (owner):** nothing to do. The warehouse is rebuilt by the `suptracker-data` workflow on the branch
before the merge.

## The map of formations, coloured by the student's zone (sprint "Carte")

**What the page does (`#/carte`, menu "Carte"; on a phone under "Plus"; from "Mon parcours": "Voir ces formations sur la
carte"):**
- **Choosing, in two levels like the owner asked (2026-11-08):** the TYPE of diploma (BTS - BTSA - BTSM, BUT, Licence, Double licence,
  Licence Accès Santé, PASS, CPGE ECG, CPGE ECT, CPGE scientifique, CPES, DCG, écoles d'ingénieurs...: 34 types covering the
  14 252 formations, each exactly once), then its MENTION (BUT Science des données, CPGE ECG Mathématiques appliquées + ESH,
  Double licence Mathématiques / Informatique...). Both come from the published labels by fixed rules (`carte.diplome_of`).
- **The map.** It is OpenStreetMap (the owner's choice, 2026-11-08: the site's own drawn map was removed).
  - Every formation of the latest campaign is placed on the map.
  - With a profile, it is coloured by the student's zone with the site's zone tokens, and each zone also has its own shape:
    sécurité round, cible square, ambitieux triangle.
  - Without a profile, the points are neutral and the page invites the student to fill "Mon parcours".
  - Close points form a group: a ring split by zone, with its count. Clicking it zooms in. From zoom 16, every formation
    is drawn on its own.
  - Clicking a formation opens a short card: zone, official access rate, "Ajouter à mes vœux", the full page.
- **Filters, inspired by the Parcoursup map** (each option with its count among what the other filters keep): types
  of establishment (public; private under contract / EESC; private, i.e. fee-charging, unticked by default: Plan B's rule),
  boarding (mixed, girls, boys), arrangements (on site, partly or fully at a distance, top-level athletes, confirmed
  artists), others (selective or not), the student's zone; plus name or town, académie and around a town (10 to 200 km;
  the map centres on it); and **Apprentissage** (hors apprentissage / en apprentissage), as on Parcoursup.
- **Apprenticeship offers (owner's request, 2026-11-08).** SIES has published no statistics for apprenticeship offers since
  2022: they have their own codes, absent from the vœux files (3 left in 2025, against 11 251 in the 2026 cartographie). The
  map lists them from the Parcoursup cartographie, latest session:
  - only the offers absent from the latest SIES campaign, each once (`carte.apprentissage`);
  - no zone, no access rate, never "Ajouter à mes vœux" (which reads SIES rows); the card says so and links to the
    offer's Parcoursup page (only a `https://dossierappel.parcoursup.fr/` link is kept);
  - the type of diploma and the mention are those of the SIES formations that carry the same cartographie labels (the
    most frequent reading, `carte.label_votes`); a label no SIES formation carries keeps its published type and mention
    (a list of types, "A,B", takes its first part SIES knows);
  - the académie is that of the establishment (UAI) in SIES, else of its département;
  - a private establishment outside State contract offering apprenticeship gets its own box, "Privés hors contrat, en
    apprentissage (gratuit pour l'apprenti)", ticked by default: apprenticeship training is free for the apprentice (Code
    du travail, art. L6211-1), so Plan B's paid rule does not apply; it is never the "Privés (payants)" box;
  - a formation whose selectivity is not published counts as neither selective nor non-selective.
- **Merged with the initial formation (owner's request, 2026-11-09).** An apprenticeship offer of the SAME establishment (UAI)
  for the same diploma and mention (the same cartographie type and mention labels) as an initial formation of the latest
  campaign is not listed apart: it is attached to that formation, which then carries both labels, "formation initiale" and
  "apprentissage" (the filter's "hors apprentissage" keeps it, and so does "en apprentissage"), and lists the CFA with its
  Parcoursup page, on the map card and in the formation page's "Bon à savoir" card. On real data 2 383 offers are attached
  to 2 387 initial formations (14 offers match two); an offer of another establishment in the same town (2 153) stays apart,
  since it is another school.
- **The list.** It shows the formations in view, plus those without coordinates ("non localisée"), in pages of 20 on a
  phone and 40 on a wide screen. It is sorted by name, or by distance around a town, never by chances.

**Rules:**
- The zones are NOT computed by the map: they are the `/api/journey/stage2` rows, the same as "Mon parcours", Plan B and
  Mes vœux.
- `/api/carte` gives the types of diploma and mentions, `/api/carte/formations` the neutral layer; `/api/carte/zones` asks
  `journey.stage2` on each formation's own type with `only=` its codes (all cacheable).
- The town and the radius stay in the browser: no API call to the site carries a position.
- **OpenStreetMap:**
  - Leaflet 1.9.4 is self-hosted in `static/vendor/leaflet/` (BSD-2 licence) and loaded by the map page only, never by
    the page shell or a CDN.
  - The tiles come from `tile.openstreetmap.org` (one constant, `CARTE_TILES`, to change provider), with the attribution.
  - The page says that OpenStreetMap's servers see the visitor's IP address, and that the profile and filters are not
    sent to them.
  - If the map cannot load, the list still works.
  - OpenStreetMap's tile servers are meant for moderate use. If the audience grows, switch `CARTE_TILES` to a tile
    provider.

**Red team** `scripts/redteam_carte.py` (C1-C10), via `tests/test_carte.py`:
- C1: zones = "Mon parcours", run in Node.
- C2: every drawn formation in exactly one group, and none without coordinates dropped from the list.
- C3: the filters against an independent Python reading.
- C4: the neutral layer by SQL.
- C5: OpenStreetMap hosting, attribution and the IP note.
- C6: hostile data, markers naming their zone, distinct shapes, wording, no position sent.
- C7: the wiring.
- C8: about 30 mutants built in memory, all caught (a mutant is skipped where the data cannot show it: no paid institution, no double licence, no non-Parcoursup link).
- C9: the apprenticeship layer re-derived by SQL (latest offer, not in SIES, once), no figure, status, type and mention vote,
  académie, the Parcoursup link only, and the card on hostile data in Node.
- C10: the merge re-derived by SQL (same UAI, same labels), both labels, the CFA listed on the map and the formation page,
  never apart; the card on hostile data.

## Each formation's own public report: doublettes and what the jury looks at (sprint "Rapports publics")

**What exists, checked before coding:**
- Every Parcoursup formation publishes a "rapport public" of its commission d'examen des vœux (a PDF). It contains tables
  per calling group, per bac type and mention, and per **doublette** (bac général) or specialty (techno, pro). Each table
  gives the candidates who confirmed the vœu, ranked, "en position de recevoir une proposition", and who accepted. The
  report also contains the jury's own texts:
  - its criteria, with their published importance;
  - the specialties it takes into account and their weight;
  - its eliminating criteria;
  - how files were examined;
  - whether an algorithm was used;
  - its advice to candidates.
- The Parcoursup site overwrites the reports at each campaign, and it was in maintenance during the probe. The **Internet
  Archive** keeps them: the archived fiche pages carry the exact report link (`g_ea_cod`, `g_ti_cod`, `c_ja_cod`), and the
  PDFs are archived at that link. The archive sorts query parameters, so the harvest lists them by PATH prefix.
- On the owner's report and on 10 probe reports (24 formations), the candidates who confirmed equal the SIES `nb_voe_pp`
  exactly. In 2025, "en position" also equals `ran_grp` per group. In 2024 it often differs, because the report is
  frozen on 11 July and SIES later. For IUT de Nice 2327 the parser gives 66 / 54 / 52 / 26 % (bac général) and 10 / 14 %
  (bac techno), the figures the owner showed.

**Pipeline:**
- `suptracker-rapports` (GitHub Action, the hosts are blocked in the sandbox) runs `scripts/rapports_harvest.py`:
  - CDX enumeration of every archived `telechargerRapportPublic` PDF (one row per distinct file);
  - download, then parsing by `scripts/rapports_parse.py` (pdfplumber table extraction: continuation pages, repeated
    headers, title rows, masked bac types; the jury's sections by their headings, never the signature);
  - CSVs plus `qualitatif.jsonl.gz` in `data/rapports/harvest/`.
  - `rapports.build` checks each report against SIES. The jury texts of the reports it keeps go to `data/rapport_textes.duckdb`, a
    file beside the warehouse that is built and committed with it. With the live harvest (about 12 000 texts, 19 MB), keeping
    them in the warehouse pushed it over the 95 MB guard.
  - It is resumable: each run stops after its time budget, and pushing `data/rapports/request.json` again continues it.
  - **Repair** (`"mode": "repair"`, `--repair`): the files left unread (a download answering 404, a damaged PDF) are tried
    again on every other capture of the same URL, newest first, as archived then rebuilt by qpdf (pikepdf). A rebuilt file
    is used only when COMPLETE: every page has text and the report's last section (the signature line) is there. Otherwise
    it stays "incomplet" and is never used, since a table cut by the damage could still pass the SIES check. Red team R7.
  - **Coverage.** The archive kept 5 408 distinct PDFs; 4 962 reports are verified after the repair (4 339 of the 14 252 formations of 2025): of the 32 files left
    unread, 7 were read on another capture, 8 rebuilt complete, 6 set aside as cut short, 11 had no readable capture.
    Parcoursup publishes no list of its reports: each one is linked from its formation's fiche, and only during a campaign.
  - **Live harvest** (`scripts/rapports_live.py`, mode `"live"`, and every day at 04:17 UTC on `main`): it reads every fiche
    of the latest cartographie session (about 25 000), follows its report link(s) and parses each PDF into the same harvest
    files (`source` = `live`), so the build verifies them exactly like the archived ones. While the fiches are closed
    (between campaigns), the run stops after three fiches and writes nothing; once they reopen (December), each daily run
    collects for up to 5 h 30 and the next one resumes (`data/rapports/live/fiches.csv`). A PDF the archive already had is
    not stored twice. The page credits the fiche ("lu le … sur la fiche Parcoursup"). Red team R8.
  - **First full live pass (2026-11-08 to 2026-11-10, 2025 reports on dossier.parcoursup.fr, 4 runs).** All 26 509 fiches
    were read:
    - 16 090 link a report;
    - 8 812 link none;
    - 1 607 failed twice.

    The build verifies 13 215 reports (3 785 set aside by the SIES check). In 2025 that is 12 592 of the 14 252 formations
    (4 339 from the archive alone), and 9 776 of them have a per-doublette table.
  - **Not yet cross-checked (the owner's choice, 2026-11-09).** In December 2026 the fiches carry the 2026 reports, and SIES
    has not published 2026. Such a report is shown when it was read on the formation's live fiche, prints the formation's
    code in its tables and its counts hold together (confirmed > 0, en position <= confirmed); it carries the mark "pas encore
    recoupé avec les chiffres de 2026" on the doublette card, the jury card and in Mes vœux. Once SIES publishes 2026, the
    ordinary check applies and a report that does not match is dropped. An archived report is never shown unverified.
    Red team R9.
- `suptracker/rapports.py` (at build) keeps a report only when it is identified and verified:
  - the formation code is the one printed in its tables (2024 on), or the `g_ti_cod` of its link for older reports;
  - its confirmed candidates must equal the SIES `nb_voe_pp` of that code and session;
  - when several captures exist, the latest verified one is kept;
  - everything else is counted in `core.rapport_audit`.

**On the page:**
- **Tab "Y entrer", card "Selon votre bac".** A table "Dans cette formation, par doublette (rapport public SESSION)":
  - one table per bac route, giving the access rate as en_position / confirmed, with the published counts;
  - the student's doublette is highlighted, or the formation's own "Autres doublettes" row when it is not detailed;
  - masked routes are said to be unpublished.
  - This published figure replaces the per-formation ESTIMATE; the estimate stays only when the formation has no report.
- **New tab "Ce que regarde le jury".**
  - The criteria, by field, with an importance badge (a neutral ink scale, never a zone colour).
  - The specialties taken into account, with the student's own ones marked, and their weight.
  - Options and courses the jury names (maths expertes, maths complémentaires, DGEMC, langues anciennes, LV3, sections
    européennes, certifications), shown only as quoted sentences.
  - A student who follows maths expertes is told whether this report names them, never what that means for them.
  - Eliminating criteria, method, algorithm and advice, folded.
  - The source line gives the session, the capture date and a link to the archived PDF.
- **Mes vœux** shows the formation's published figure when its report exists.

**Red team** `scripts/redteam_rapports.py` (R1-R6), via `tests/test_rapports.py`:
- R1: the parser on the committed probe PDFs (SIES identity, a known table read cell by cell, no signature);
- R2: the selection rules on a crafted harvest built from the warehouse (unverified report rejected, wrong `g_ti_cod`
  rejected, latest capture, concours split);
- R3: the figures and the twins;
- R4: a Node render on hostile texts (escaping, labels, estimate replaced only by a published figure, source, caveat);
- R5: the wording and the register;
- R6: 14 mutants built in memory, all caught.

## Found by search engines, and renamed SupCompass (sprint 17)

**The name.** The site is now **SupCompass** ("Sup" of Parcoursup + compass), the owner's choice. Every visible place says
so: page title, header, footer, API title, monitor user agent. The footer adds that the site is independent, not
affiliated with Parcoursup or the ministry. The Python package, folder, workflows and Vercel settings keep the technical
name `suptracker`, so the owner's settings keep working.

**The problem.** Every view lived after a `#` (`#/f/2882`), and search engines do not index those. Only the home page
existed for Google: about 14 000 formations and 1 100 jobs were invisible.

**What changed (`suptracker/seo.py`):**
- **`/formation/<code>` and `/metier/<MET.id>`** are real pages. Each one is the app shell with:
  - in its `<head>`: a title ("Licence - Portail Psychologie à Caen (Université de Caen Normandie) : taux d'accès 2025 | SupCompass"),
    a meta description (official figures and the caveat first), a canonical address, Open Graph tags and schema.org JSON-LD
    (`EducationalOccupationalProgram`, `Occupation`);
  - inside `<main id="view">`: a short server-rendered summary with the published access rate, admits and places (never
    recomputed), the "pas des chances d'admission" caveat, the jobs of the Onisep sheet and the other formations of the
    same filière in the académie, as plain links (they let a crawler move from page to page).
- The app then boots on that address and shows the full page (summary, tabs). Once the visitor navigates, the address
  goes back to `/#/…`, so the app's usual links stay the same.
- **`/sitemap.xml`** lists the 14 252 formations of the latest campaign and the 1 124 jobs (15 376 URLs, under the 50 000 limit).
  **`/robots.txt`** points to it. It keeps crawlers off search, vœux and stats, but leaves open the data the pages are
  rendered from: a crawler that runs the app must be able to load it. If that data cannot be loaded, the server summary
  stays, with the error shown above it, never in its place (Codex finding).
- **Indexing rules.**
  - A formation absent from the latest campaign is served with `noindex`.
  - A Vercel preview deployment is never indexed: `noindex` everywhere, `Disallow: /`, empty sitemap.
  - The canonical origin is the production domain Vercel declares (`VERCEL_PROJECT_PRODUCTION_URL`), never the visitor's `Host`.
- **Unknown addresses** answer an HTML 404 page with `noindex`; the API keeps its JSON errors.
- **Cache.** Pages are kept by the CDN for one deployment (`s-maxage`) and always revalidated by browsers (`max-age=0`),
  because they point to the current asset fingerprint. `HEAD` is answered (crawlers use it).

**Red team** (`scripts/redteam_seo.py`, run by `tests/test_seo.py` on the synthetic and the real warehouse): 11/11 checks.
- **G1.** The sitemap is re-derived from the warehouse: exactly the latest campaign's formations plus every job.
- **G2.** On formation pages, the figures in the title, description and body are the published ones and equal
  `/api/formation`; head tags, canonical and JSON-LD are present.
- **G3.** Job pages list every diploma of `/api/metier`, and their formation links point to real pages.
- **G4.** Hostile names are escaped everywhere, including the JSON-LD (no `</script>` can close it).
- **G5.** Malformed or unknown addresses return a 404 with `noindex`, never cached.
- **G6.** Older formations, previews and the canonical origin follow the indexing rules.
- **G7.** The router maps the two paths to the same views (run with Node) and returns to `/#/…` on navigation. A failed data
  load keeps the server summary.
- **G8.** The SupCompass name and the independence notice are present; "SupTracker" appears nowhere a visitor reads.
- **G9.** The cache policies hold.
- **G10.** 24 mutants are each caught. They are built in memory: the red team never writes a source file, so the
  parallel test workers are safe.
- **G11** (`--browser`). On a phone, light and dark, the app boots on these addresses with 0 JS errors. Without
  JavaScript, and with `/api/` blocked, the server summary stays readable.

**For the owner after the merge:** declare the site in Google Search Console and submit `/sitemap.xml` (steps in the PR).

## The working pages in the same format (UI lot 3)

Lot 3 brings the lot-2 rules (summary first, detail folded, state by form and colour) to the four pages a student uses to
build a list.

**Measured on a phone (iPhone 13), before → after:**

| Page | Before | After |
|---|---|---|
| Recherche (« licence psychologie », 103 results) | 11.1 screens | 5.7 screens (20 results per page on a phone, 40 on a wide screen) |
| Mon parcours, positioning step (Licence Sciences juridiques, 270 formations) | 39.7 screens | 14.5 screens (20 rows first, then « Afficher les … formations ») |
| Mes vœux (4 vœux) | 3.1 screens, the table cut on the right | 3.6 screens, nothing cut, the zone counts first |
| Comparateur (3 formations) | 3.0 screens, labels squeezed | 2.8 screens, the label column stays in place |

**What changed:**
- **Mes vœux:** "Lecture de votre liste" is the summary card: one tile per zone (sécurité, cible, ambitieux) with its count
  and the zone's own colour, plus "Autres". The list becomes one block per vœu on a phone, each figure with its label
  (zone, access rate, "votre mention ou moins", places); the "how to add" note moves to the end.
- **Mon parcours:** once a profile is stored, the form folds under one line ("bac général · SES + HGGSP · mention assez bien
  · académie de Normandie", Modifier). The positioning table shows 20 rows first, one labelled block per formation on a phone.
- **Recherche:** 20 results per page on a phone; the session and number of campaigns become plain text instead of two badges.
- **Comparateur:** the label column is pinned while the formations slide; a one-line hint says so on a phone.

Every caveat and every red-team-checked string is unchanged. Plan B, the pin buttons and "Voir un plan B" work as before
(their red teams pass unchanged).

**Red team** (`scripts/redteam_ux.py`):
- **X14.** Run with Node: the zone tiles use the zone tokens and count each zone, the profile line is escaped, 20/40
  per page. Static: every figure of the stacked tables keeps its label, the profile folds when stored, 20 rows first,
  the comparator column is sticky. The phone CSS hides the header row.
- **X15.** 9 mutants, each caught: accent instead of zone colour, unescaped profile, a lost label, profile never folded,
  every row at once, 40 results on a phone, header row shown, comparator column not pinned.
- **X7** (`--browser`) now fills a profile, a list and a comparator basket, then measures Mes vœux, the comparator and
  Mon parcours on a phone: summary tiles present, profile folded, header rows hidden, search at most 8 screens.

## From the licence to the master, side by side (sprint 16, licence page)

A licence page gets a card **"De la licence au master : chaque master côte à côte"** (`suptracker/licence_master.py`,
tables `core.master_onisep` and `core.metier_axes`). For every master mention of the licence's university in the same
B1 discipline (the sprint-7 link, MonMaster latest session), one row brings together what earlier sprints showed apart:
- **MonMaster:** admits (people) and vœux (applications summed over programmes, not people); never a ratio of the two.
- **InserSup (sprint 8):** the same university's master with the same title, latest national class: salaried employment
  at 18 months among the leavers; pooled classes flagged; a master published in parts gets no figure; "taux non publié"
  when masked.
- **Onisep:** the jobs of the national master sheet with the same title ("master mention X"). The sheet belongs to the
  diploma, not to this university.
- **Sprints 13-15 for those jobs:** the RANGE of the ILO task scores and of θ over every code of every job, and the
  COUNT of jobs per 2030 reading. A job's 2030 class is a fixed rule: every read family says "débutants insuffisants" →
  insuffisants; every one says "débutants nombreux" → nombreux; otherwise incertain; no family read → sans projection.
- **Landmarks** (fixed rules), only when two ranges are DISJOINT: the master's jobs vs the licence's own Onisep jobs
  (ILO all below / all above; θ all above / all below). Overlapping ranges say nothing. Never an average, never a single score.

**What we checked first:**
- MonMaster mention ↔ Onisep sheet by national title: 200 of 315 mentions by exact title, plus 5 with two explicit
  spelling rules ("STAPS:" written out, "(MEEF)" dropped) and 1 recovered by the red team (a curly apostrophe, see below).
  Other mentions (MEEF 2nd degré, LLCER, droit pénal, ...) have no Onisep sheet: "métiers non documentés".
- InserSup ↔ MonMaster at the same university by title: 85 % of the latest class's masters.
- Per-job axes cost 58 ms each: they are computed once at build (`core.metier_axes`, about 1 min); a page answers in ~0.1 s.
- Coverage: 298 of 330 sampled licences get the card; of 5,116 master rows, 81 % have documented jobs, 4,650 an insertion
  figure, 230 a landmark.

**Red team** (`scripts/redteam_licence_master.py`, run by `tests/test_licence_master.py`): 7/7 checks and 16/16 mutants
caught on real data (a crash counts as missed).
- **L1.** Mention → sheet re-derived with an independent normalisation. It caught a real bug: the curly apostrophe of
  "… DE L’ESPACE" was dropped ("lespace"), so the mention lost its sheet; the key now treats it as a separator.
- **L2.** Per-job axes re-derived from the job page for all 1,124 jobs.
- **L3.** Serving re-derived on 114 licence cards (1,864 rows): mentions and counts, insertion, jobs, ranges, counts, landmarks.
- **L4.** Coverage. **L5.** The card run with Node on hostile data (escaping, units, years without a thousands separator,
  "taux non publié", wording). **L6.** Upkeep.
- **L7.** Mutants: apostrophe dropped, spelling rules dropped, fuzzy prefix links, 2030 class from one family, θ range
  cut, ILO range averaged, insertion from another university, landmark on overlapping ranges, and 8 page mutants.
- On a phone the table becomes one block per master (`table.lm`), the column name before each value.

## Generative AI and the job's tasks (sprint 15, job page)

The job page gets a card **"L'IA générative et les tâches du métier"** (`suptracker/ia_exposition.py`, tables
`core.ia_oit_isco` and `core.ia_rome_tag`). It comes from two files committed by the owner:
- **ILO 2025** (Gmyrek, Berg et al., Working Paper 140, CC BY 4.0): 3,265 ISCO-08 tasks of 427 unit groups, each scored
  0-1, and per group the PUBLISHED mean (2 decimals), standard deviation and exposure class (not exposed, minimal
  exposure, exposed gradient 1 to 4);
- **France Travail ROME 4.0 tags**: the "Transition numérique" tag per ROME sheet (Oui 213, Non 1,331, not assessed 379).

**What we checked first:**
- **Published values are served.** The published mean equals the rounded mean of the tasks for 98.8 % of codes (4 ties
  at .005). One real upstream inconsistency: ISCO 7126 (0.18 published, its tasks average 0.15); we serve the published
  value and the red team names it.
- **The classes are not cut-offs of the mean alone.** The ILO class also uses the spread between tasks: the 4 exposed
  gradients are ordered bands of the mean (G1 0.28-0.39 … G4 0.60-0.70), but two close means can get two classes. The
  card says so.
- **Coverage.** 389 of the 397 unit groups our jobs reach have an ILO score (missing: armed forces 0110 / 0210 / 0310,
  1439, 3139, 3435, 5249, 7319). 913 of the 928 jobs with a usable ROME code get at least one score (98.4 %).

**On the page:**
- One row per 4-digit ISCO-08 code of the job (sprint 13, through job titles), main codes first, with the count of job
  titles behind it, the ILO class and the published mean ("0,53"); a code without an ILO score says so.
- The RANGE of the published means ("de 0,43 à 0,60 sur 1"), never an average, never a composite with sprint 14's figures.
- The France Travail tag of each ROME sheet, as a fact.
- The wording: a technical potential of the TASKS, not a forecast of job losses nor a risk for the student; an exposed
  job is more often transformed than replaced.
- **Human complementarity θ** (second part, `core.ia_theta_onet`, `core.ia_theta_lien`): the IMF method (Pizzinelli
  et al. 2023) rebuilt from O*NET 31.0 per the owner's guide. 11 Work Context elements on the CX scale (1-5 → 0-100,
  Degree of Automation reversed), 5 dimension means plus the Job Zone (20 × zone), θ = mean of the 6 dimensions.
  - It is an ADAPTED estimate (reliability C), never the IMF 2023 score: O*NET 31.0 merged Job Zones 1 and 2 (code 2),
    and the outdoor element is the guide's proxy (4.C.2.a.1.c).
  - Data check: 911 occupations with 11/11 CX values, one per occupation × element; the 5 with a suppressed element get
    no θ (906 left). The lowest is 51-9031 Hand Cutters and Trimmers (0.38), the IMF's own lowest occupation (0.31 there).
  - It reaches ISCO-08 only through official tables: O*NET-SOC 2019 → SOC 2018 (O*NET), SOC 2018 → SOC 2010 (BLS,
    November 2017), SOC 2010 → ISCO-08 (BLS). 1,380 links; 2 occupations the BLS maps only to 3-digit groups stay unlinked.
  - 391 of the 397 unit groups our jobs reach get θ. Each code shows the RANGE over its US occupations and their count
    (median width 0.05, at most 0.28), never an average, never combined with the ILO score.
- **C-AIOE is not computed.** The Felten AIOE appendix (SOC 2010, registered) is centred-reduced (values down to −2.67);
  the guide forbids the IMF correction on such a scale.

**Red team** (`scripts/redteam_ia.py`, run by `tests/test_ia_exposition.py`): 9/9 checks and 25/25 mutants caught on real data
(a mutant that crashes counts as missed).
- **I1.** The ILO file re-read with openpyxl: stored mean, sd, class and task count; task means re-derived (only the
  known 7126 differs); exposed gradients are ordered bands.
- **I2.** Tags re-read: stored values equal; only Oui, Non or not assessed.
- **I3.** Serving: exactly the job's 4-digit ISCO codes, published values, min / max range, no average, unscored codes
  listed, main codes first.
- **I4.** Coverage.
- **I5.** The card is run with Node on hostile data: escaped, wording, two decimals, unscored codes, no alarming words.
- **I6.** Upkeep: register, methodology, feature, warehouse size.
- **I7.** Mutation test: re-computed means served, 2023 scores served as 2025, gradient shifted, Transition écologique
  read as the digital tag, partial ISCO codes served, range collapsed to an average; for θ: automation not reversed,
  outdoor element swapped, 12 variables weighted equally, Job Zone read on a 1-5 scale, suppressed elements kept, response
  shares (CXP) read as scores, SOC 2018 code taken as SOC 2010, 3-digit groups padded, θ range collapsed; 10 page mutants.
- **I8.** θ re-derived with the `csv` module from the guide's formula; plausibility against the IMF's lowest occupation.
- **I9.** The official chain re-read with openpyxl and xlrd: stored links equal, 4-digit ISCO only.
- `tests/test_ia_exposition.py` also checks the guide's worked example (θ = 415 / 600).

## Hiring planned in 2026 (BMO, sprint 14 follow-up, job page)

A second card, **"Les recrutements prévus en 2026"** (`suptracker/bmo.py`, table `core.bmo_metier`), gives the
short-term context. It comes from France Travail's "Besoins en main-d'œuvre" survey: employers' declared hiring
INTENTIONS for the year (not job offers, not hires), and how many they expect to be difficult. It says nothing
about 2030.

**What we checked first:**
- **The data's finest level.** The owner's workbook keeps France Travail's open-data base at its finest level: job ×
  employment area (× local committee in 2026), with "*" where a value below 5 is masked.
- **Totals re-summed independently.** The France totals are re-summed here from those 53,786 cells, and equal the
  workbook's own France sheet for all 217 jobs.
- **Codes.** The jobs are FAP-2021 228 codes with the Dares labels, so a job reaches them through sprint 13's
  FAP-2021 families.
- **Masked cells.** 24 % of the 2026 project cells are masked and count as 0. Every total is therefore a floor
  ("au moins"): 2.24 million published projects against about 2.3 million announced. In 2025 the published total
  covers 98.7 % of France Travail's official figure.
- **No 2025 comparison.** In 2026, areas are split into local committees, so more cells are masked and the floors fall
  for that reason alone. A drop would be partly an artefact.

**On the page:**
- One row per FAP-228 family of the job (every family when it depends on the qualification).
- Each row gives "au moins N" projects, the share expected to be difficult and the share seasonal, next to the all-jobs
  shares (43 % and 32 %).
- A share is flagged **fragile** when the masked cells could move it by more than 5 points, if each masked cell held
  up to 4.
- 878 of the 928 jobs with a usable ROME code get figures (94.6 %).

**Red team** (`scripts/redteam_bmo.py`, run by `tests/test_bmo.py`): 7/7 checks and 12/12 mutants caught on real data.
- **B1.** Sums re-derived with openpyxl from the basin cells; they equal both the stored table and the workbook's
  France sheet.
- **B2.** Consistency, codes and labels.
- **B3.** Serving: families, shares, fragility, national reference.
- **B4.** Coverage.
- **B5.** The card is run with Node on hostile data: escaped, wording, floors, fragile badge, no 2025 comparison.
- **B6.** Upkeep.
- **B7.** Mutation test: masked cells counted as 5, 2025 served as 2026, wrong denominator, 341 code instead of its
  228 parent, fragility never flagged, masking bound ignored, and 6 page mutants.

## Employment to 2030 (sprint 14, job page)

The job page gets a card **"L'emploi dans ce métier d'ici 2030"** (`suptracker/emploi2030.py`, table
`core.m2030_famille`). It comes from the Dares / France Stratégie projections "Les métiers en 2030" (2022), annex 4,
synthesis tables A and B, committed by the owner.

**What we checked on the real workbook first:**
- 79 FAP-2009 families at the 87 level. For each: 2019 employment, and over 2019-2030 the net job creations,
  end-of-career departures, positions to fill, young entrants, and the potential imbalance (positions − entrants) in
  the reference scenario and in 4 variants. Every row satisfies creations + departures = positions and
  positions − entrants = imbalance; table B is table A divided by 2019 employment.
- Six worker families are only published inside their domain: D0Z + D3Z and F0Z..F3Z. Their group is the domain
  minus its published families, which adds up on every column; it is shown as **calculated**. Craftsmen (K0Z) are
  mixed with elected officials and clergy in "Autres": no figure.
- There is no figure beyond 2030. No official projection per job exists for 2035, so the page says so and invents none.

**On the page:**
- A job reaches its families through its official codes (sprint 13): ROME → FAP-2009 → 87-group. When the family
  depends on the qualification of the post, every family is shown with its own figures.
- Figures are rounded to the thousand, with signs. The imbalance is shown as the range of the 5 scenarios, with the
  reference value.
- A fixed rule reads the range: positive in all scenarios = "les jeunes débutants ne suffiraient pas"; negative in
  all = "plus de débutants que de postes"; otherwise "on ne peut pas conclure".
- The card states that this is a projection under assumptions, not a forecast or a promise, and that the figures
  belong to the whole family.
- 906 of the 928 jobs with a usable ROME code get figures (97.6 %).

**Red team** (`scripts/redteam_emploi2030.py`, run by `tests/test_emploi2030.py`): 7/7 checks and 15/15 mutants
caught on real data.
- **E1.** Values re-read with pandas; the identities are checked.
- **E2.** The groups are re-derived; K0Z gets no figure.
- **E3.** Serving: the families are exactly the job's 87-groups; the range and the reading rule are checked.
- **E4.** Coverage.
- **E5.** The card is run with Node on hostile data: escaped, wording, readings, rounding, signs, no 2035 figure.
- **E6.** Upkeep.
- **E7.** Mutation test: column order, group base, reference-only range, a single family picked, reading on one
  scenario, unmapped groups, craftsmen given the "Autres" figure, and 8 page mutants.

## The official codes of a job (sprint 13, job page)

Each job page (`#/metiers/<id>`) ends with a card **"Les codes officiels de ce métier"**. It is the job reference
that sprints 14 (employment to 2030) and 15 (AI task exposure) read their figures through. It shows codes, not
figures about the job market.

**Where each link comes from** (`suptracker/nomenclatures.py`, tables `core.nomen_*`, all from files the owner
committed under `data/sources/`):

| Link | Official table | Kind |
| --- | --- | --- |
| job → ROME | Onisep job sheet (every ROME code, sprint 12) | code to code |
| ROME × qualification → FAP-2021 | Dares, `Table_passage_ROME_Qualif_to_FAP2021` | code to code |
| ROME × qualification → FAP-2009 | Dares SAS program `passage_fap2009_romev3.txt` (the Dares xls is the cross-check) | code to code |
| ROME × qualification → ISCO-08 | Dares PCS 2020 job titles joined by title to the Insee ISCO codification (G44) | through job titles |

**What we checked on the real files first:**
- **FAP families.** All 532 ROME codes are in the Dares table. For 282 of them the FAP-2021 family depends on the
  qualification class (0 not specified, 1-3 workers, 4 independent, 5-6 employees, 7 technicians, 8 supervisors,
  9 engineers and executives). Every family is shown with the classes it applies to; none is picked for the student.
- **FAP-2009.** The SAS program and the Dares xls give the same 5,310 (ROME, qualification, family) rows. Their
  qualification classes are France Travail's (4 = highly qualified worker), not the FAP-2021 ones: the page never
  names them with FAP-2021 names.
- **ISCO-08.** 97.1 % of the 107,050 Dares job titles find their Insee code. G44 codes a title per employment
  status; the status follows the qualification class.
  - A ROME code has several possible ISCO codes; each comes with the number of DISTINCT job titles behind it.
    No weight is published along this path, so this count is never shown as a share of jobs.
  - Some titles only allow a partial code (2100 = sub-major group 21). It is shown as `21xx`, with no label invented.
- **Coverage.** Of the 1,124 Onisep jobs, 928 have a known ROME code. Per job, the median is 2 FAP-2021
  families, 1 FAP-2009 family and 4 full ISCO codes. 193 jobs have no ROME code; the page says so.

**Jobs without an Onisep ROME code** (196, owner's choice: link them by their name).
- A job name equal to a Dares job title gives that title's ROME code (30 jobs). Otherwise, a name equal to a France
  Travail appellation (ROME tree, `*rome_arboprincipale*.xlsx`) gives its code (10 more jobs).
- The tree is ROME 4.0 (1,923 sheets): only the 532 codes the Dares tables know are kept. A newer code would have no
  FAP nor ISCO link.
- Homonyms the owner reviewed (`nomenclatures.TITLE_LINK_OVERRIDES`, reason shown on the page): "énergéticien/ne" (a
  boiler-room operator on its Onisep sheet) gets I1308 by its ROME appellations; "secrétaire des Affaires étrangères"
  gets K1405 like "diplomate"; "économe de flux" stays unlinked (its ROME 4.0 sheet has no Dares link). Result: 27 jobs by
  Dares title, 10 by appellation, 2 by reviewed analogy (39).
- The Onisep code always wins; one method per job. These links are less sure and the page says so, with the
  method's check measured at each build on the jobs whose Onisep code is known: Dares titles find a right code for
  356 of 420 jobs, appellations for 341 of 382. Homonyms explain the misses (an "énergéticien" engineer matches the
  well-being title).
- 157 jobs stay unlinked (armed forces, State and Senate bodies, recent jobs whose ROME 4.0 code has no Dares link).

**Red team** (`scripts/redteam_nomenclatures.py`, run by `tests/test_nomenclatures.py`): 8/8 checks and 24/24
mutants caught on real data (N8 re-derives the name links, checks the Onisep code always wins and the page flags them).
Its first runs found two bugs: the Dares CSV files are Windows-1252, not Latin-1 (`’` and `œ`
became invisible control characters), and the curly apostrophe was dropped before the join key was folded. No title in use
carries either today, so the red team checks both with witness inputs.
- **N1.** Every stored table equals the raw file re-read with pandas; FAP-2009 SAS = xls row for row.
- **N2.** ROME → ISCO is re-derived independently (pandas merge, independent status rule): same 57,215 rows.
- **N3.** Cross-check by another official path, ROME → FAP-2021 → PCS 2020 (Dares, probabilistic) → ISCO (Insee
  matrix): the two ISCO sets meet for 97.6 % of ROME codes. The Dares title and ROME tables agree on the family for
  99.8 % of rows.
- **N4.** Serving: the qualification classes are covered exactly once; FAP-2009 classes carry no FAP-2021 name;
  title counts are distinct; partial codes carry no label; odd and unknown codes are handled; each job page carries
  the codes of its own ROME codes.
- **N5.** The card is run with Node on hostile data: everything is escaped, no percentage, the wording is present.
- **N6.** Upkeep: the source register, the methodology, `xlrd` in the pipeline requirements, a safe empty build,
  the warehouse under 95 MB (72.9 MB).
- **N7.** Mutation test: wrong status column, unfolded titles, the qualification-dependent FAP-2009 format ignored,
  every code taken as a full unit group, non-distinct counts, wrong "toutes qualifications", families dropped,
  a Latin-1 reading, a weaker fold, and 8 page mutants.

## From a job to the formations (sprint 12, `#/metiers`)

**What the student sees.** A "Métiers" page in the menu. The student types a job and the matching Onisep jobs appear as they type. Matching is insensitive to accents and case, and works on masculine and feminine forms and on the Onisep synonyms: "infirmière", "gestionnaire de paie", "développeur web" all find a job. When no job contains every word, the closest ones are shown and labelled as such.

A job page lists:
- the diplomas whose Onisep sheet cites the job, from the lowest level to the highest, each flagged "accessible avec ce diplôme" or "après une poursuite d'études";
- under each diploma, the Parcoursup formations of the latest campaign that prepare it, with access rate, places and "Ajouter à mes vœux";
- "Mon académie seulement" as an option: the académie stays in the browser.

From a formation page, each job of the "Les métiers visés" card has a "formations" link. The job page then shows that formation first ("la formation que tu regardais"), even beyond the 40 rows displayed.

**Design (`suptracker/metiers.py`, `GET /api/metiers`, `GET /api/metier/{id}`).**
- **The jobs card read backwards.** Same Onisep sheets, same link (`onisep.match`), same access flag. Both pages always agree; red team M3 checks it both ways.
- **The diploma level now comes from the matched Onisep sheet itself** (`onisep.sheet_level`), not from the filière. The sprint-8 card assumed every BTS was bac+2, but the BTS orthoprothésiste and podo-orthésiste last 3 years ("bac + 3"). On those pages a bac+3 job was wrongly shown "après une poursuite d'études". Fixed for both pages; the filière's usual level is only a fallback.
- **All of a job's codes and labels are kept.** The Onisep parsing keeps every ROME code of a job (34 jobs have several; up to 4) and every masculine, feminine and synonym label: `core.onisep_metier_rome`, `core.onisep_metier_libelle`.
- **Privacy.** The catalogue (1,124 jobs, 51 KB compressed) is sent whole by a route that takes no parameter and is searched in the browser: what a student looks for never reaches the server. Both routes are public and cached by the CDN; no audience event is recorded beyond the page view.
- **Wording.** The list is national: an establishment is listed because it prepares the diploma, not because its students do the job. It is not a promise of a job. Formations are listed by académie and town, never by chances.
- **Coverage on real data.**
  - 981 of the 1,124 jobs are linked to at least one diploma; 331 of them reach Parcoursup formations.
  - The other 650 are reached only through diplomas outside Parcoursup (masters, engineering and other schools, CAP…), and their page says so.
  - 143 jobs have no diploma at all.

**Upkeep.**
- **Source register.** Every file committed for the Horizon 2030 sprints is registered with the new status `depose`, its sprint and its role (source, context, or cross-check only), so red team F9 stays green.
  - The status means "committed, not ingested yet".
  - The sources page shows "déposée, pas encore intégrée · étape N".
  - A pattern that matches no committed file is now caught.
- **Monitor.** It retries twice, 2 s apart, when the CDN is still filling right after a deployment. An answer never served from the cache stays red.
- **Deployment.** `data/sources/` was already outside the Vercel bundle (`.vercelignore`); red team M7 now guards it.

**Red team (`scripts/redteam_metiers.py`, run in CI by `tests/test_metiers.py`).** On the real data, 8/8 checks pass and 16/16 mutants are caught.
- **M1.** The raw XML is re-read: every ROME code and every label.
- **M2.** 97 job pages are re-derived from the raw links: diplomas, formations, flags, status, order.
- **M3.** 322 job ↔ formation pairs are checked both ways.
- **M4.** The page's own JavaScript runs under Node:
  - truth queries, typed with and without accents;
  - accent and case invariance;
  - close matches never outranking full ones;
  - hostile queries.
- **M5.** API: no parameter, cache headers, malformed ids, no audience event.
- **M6.** Page: escaping, noopener, wording, ODbL credit, race guard, the formation the student came from pinned, wiring.
- **M7.** Upkeep.
- **M8, mutation test.**
  - Page: unescaped strings, noopener, the three caveats, the race guard, the pin, the card's link.
  - Search: accents kept, synonyms ignored, an empty query matching everything.
  - Data and deployment: inverted flag, a dropped formation, the filière's level instead of the sheet's, `data/sources` back in the bundle.

The first red-team run found:
- the 3-year BTS level bug;
- the formation a student came from lost at rank 86 of 86;
- an all-words-only search that found nothing for "développeur web";
- a misleading "après le bac+3" for school diplomas such as aide-soignant;
- literal combining characters in the accent-stripping regex, which hid the mutant meant to test it.

**UI check (Playwright):** search and job pages in light, dark and mobile; the link from a formation card; no request carries the query. 0 JS errors, no horizontal page scroll.

## Scale: CDN cache, lighter answers, one CI run, live monitoring (sprint 10)

**Measured first (real warehouse, before the sprint).**
- **Mon parcours.** A type can hold 3,096 formations (BTS services). Its positioning answer weighed 5.9 MB, 634 KB compressed, and took 0.65–1.3 s.
- **Caching.** No answer was cacheable by Vercel's CDN, so every visit ran the Python function again.
- **Assets.** The versioned front-end files (`app.js?v=…`) were re-validated at every visit.
- **CI.** Every push to a pull-request branch ran the 23-minute suite twice (push + pull_request).

**Design.**
- **One cache policy per route (`suptracker/cache.py`, applied by a middleware).**
  - Public data answers (formation pages, lineage, comparator, positioning, Plan B, meta…) are `public, max-age=300, s-maxage=86400, stale-while-revalidate=86400`. The Vercel CDN serves a repeated URL without running the function, and drops its cache at each deployment.
  - **Never shared-cached:** routes that record an audience event (search), personal lists ("Mes vœux"), the beacon, the dashboard, `/api/version`, health checks, every error (non-200) and every unknown route.
  - Versioned assets are `immutable` for a year, but only with the live fingerprint.
- **The "Mon parcours" count moves to the page.** A CDN hit would skip a count made by the server, so the page now sends `journey` (`stage1` / `stage2`) through the beacon, validated on a closed list. The dashboard is unchanged.
- **Lighter positioning answers.** `journey.public_stage2` drops 13 fields the page never reads and rounds numbers to 6 decimals. The rounding is guarded: a value close to a printed half-step keeps its full precision, so no printed number changes. Zones are computed before, on full precision. Plan B and "Mes vœux" use the full rows. Result: −26 % compressed on BTS services (634 → 471 KB).
- **CI.**
  - `main` runs on push; branches run through their pull request. A newer push cancels the older run.
  - The tests run in parallel (`pytest-xdist`, one file per worker), with a pip cache.
  - The red teams that measure time (analytics R16, Plan B B11, search R12) run alone afterwards. The first CI run of this sprint ran Plan B in parallel and its p95 latency rose to 1.26 s; red team S6 now finds every red team that calls the clock and requires its test in the serial step.
- **Live monitoring.** `.github/workflows/suptracker-monitor.yml` runs `scripts/monitor.py` every 6 hours against the repository variable `SUPTRACKER_URL`. It checks:
  - readiness;
  - that the page points to the live assets, and that they are immutable;
  - search;
  - a formation page (shared-cached) and "Mes vœux" (never shared-cached). Each is asked twice and judged on Vercel's client-visible `x-vercel-cache` (HIT/STALE), because Vercel consumes `s-maxage` and strips it from the response (Codex review); off Vercel, the monitor reads `Cache-Control`;
  - the positioning, with time limits.

  The monitor sends `DNT: 1` and a robot user agent, so it is never counted in the audience. A red run makes GitHub e-mail the owner.

**Red team (`scripts/redteam_scale.py`, run in CI by `tests/test_scale.py`).** On the real data, 7/7 checks pass and 14/14 mutants are caught.
- **S1.** Every one of the 25 GET routes has a policy and a working sample request.
- **S2.** Every route is CALLED with the audience recorder patched: the only route that records (search) is never shared-cached, and neither is "Mes vœux".
- **S3.** Headers as served: errors, unknown routes and POST are `no-store`; assets are immutable only with the live fingerprint; no cached answer sets a cookie.
- **S4.** On 13,910 real rows: the dropped fields are never read by the page, no zone changes, and no printed number changes. The printing is reproduced exactly as the browser does it (`toLocaleString` rounds the exact binary value half away from zero).
  - The first version rounded without the guard. The red team found 78 printed numbers that would have changed (74.4 % shown as 74.5 %), which led to the guard.
- **S5.** Plan B and "Mes vœux" keep full rows; the page sends both counts; hostile beacons are rejected; the dashboard key is written; the server no longer records.
- **S6.** Workflows: CI on push only for `main`, stale runs cancelled, every timed red team serial, the monitor scheduled. The monitor passes against the app and behind a simulated Vercel CDN that strips `s-maxage` (the first version failed there, found by Codex), and fails on a site that is down, where Vercel never caches the formation or serves "Mes vœux" from its cache, serves an old front-end, has non-immutable assets or shares "Mes vœux".
- **S7, mutation test.**
  - Cache policy: search or "Mes vœux" shared-cached, a route without a policy, errors cached, assets immutable whatever their version.
  - Lighter answers: a read field dropped, coarse rounding, rounding without the guard.
  - Audience: the page's count rejected.
  - Workflows: CI on every branch push, no cancellation, the analytics or Plan B timing check in parallel, the monitor unscheduled.

**UI check (Playwright):** "Mon parcours" on BTS services with the lighter answer (table, inline Plan B, adding to "Mes vœux"), in light, dark and mobile. 0 JS errors, no horizontal page scroll, and both `journey` beacons sent.

## "Mes vœux": the student's list, read for the current profile (sprint 11, `#/voeux`)

**What the student sees.** A "Mes vœux" page in the menu (with a counter) holds up to 10 formations, as on Parcoursup. A vœu is added from:
- a formation page ("Ajouter à mes vœux");
- the "Mon parcours" table or matrix;
- a plan B.

For the CURRENT profile (series, specialties, mention, académie of "Mon parcours"), each vœu shows:
- its zone;
- the access rate (official for bac général, "accès estimé pour ta série" for techno and pro);
- where the student's mention sits among the admitted;
- the places;
- a "Voir un plan B" button.

A "lecture de ta liste" counts the zones and prints fixed messages:
- no sure safety vœu;
- more than half ambitious or out of profile;
- an out-of-profile vœu;
- a vœu not open to the series;
- vœux that cannot be placed;
- no target vœu;
- otherwise "balanced".

The page says that Parcoursup vœux are not ranked, and that zones never combine into a chance of admission.

**Red-team review of the previous list ("4 · Ma liste de vœux simulée" in "Mon parcours"), which this sprint replaces.**
- Zones were frozen when a vœu was pinned: after a change of mention or specialties, the reading was stale.
- An *uncertain* safety vœu counted as safe, while Plan B rejects it.
- Vœux not open to the series raised no warning.
- Bac techno and pro saw "Taux d'accès" over an estimated rate.
- Vœux could only be added from "Mon parcours".

The old list is migrated once, codes only, and re-read for the current profile.

**Design (`suptracker/voeux.py`, `GET /api/voeux`).**
- **Same zones as everywhere else.** Each vœu is placed by `journey.stage2` restricted to the listed codes (`only=`). Every row is computed from its own lineage, so the row is identical to the full type's row (red team V2) and 30× faster. A zone here is therefore the zone of "Mon parcours" and of Plan B.
- **Coverage.** On real data, 93 % of the 2025 formations can be placed: all CPGE, BUT, IFSI, EFTS, PASS and schools, 99.6 % of BTS, 97.7 % of licences, and 46 % of "Autre formation". The others are "non situés", with the reason given.
- **Counts only.** The reading only counts zones. Nothing is multiplied, and the page never shows a chance of getting at least one vœu: the vœux are not independent, and the zones describe past admitted cohorts. An uncertain safety vœu does not count as sure.
- **Privacy.** The list stays in the browser (`localStorage`, codes only, validated, deduplicated, capped at 10). The page sends the codes and the profile, as "Mon parcours" and Plan B already do. The endpoint records no analytics event; only the page view "voeux" is counted, like any page.

**Red team (`scripts/redteam_voeux.py`, run in CI by `tests/test_voeux.py`).** On the real data, 6/6 checks pass and 18/18 mutants are caught.
- **V1.** 196 vœux × 4 profiles get exactly the full-type stage2 zone, uncertainty, rate and position, and Plan B's target zone.
- **V2.** The `only` restriction changes no row.
- **V3.** The reading is re-derived with the red team's own rules on 400 synthetic lists and the real ones; the counts add up.
- **V4.** The API rejects hostile input: 11 codes, SQL-like or non-numeric codes, missing or equal specialties, an unknown mention or series. Duplicates are kept once, unknown codes are flagged, no analytics event is recorded, and the mention changes the zones.
- **V5.** The page escapes every string and validates the stored list, guards against the navigation race, and has the wording (no chance, no ranking, privacy). It has a message for every rule and the wiring (menu, route, formation-page button, analytics route).
- **V6, mutation test.** An uncertain safety counted as sure, "half" read as "more than half", closed vœux not flagged, the all-series position, duplicates kept, no cap, series ignored, mention frozen, and 10 UI mutants.

**UI check (Playwright):** light, dark and mobile, with the old list migrated (one entry tampered) and vœux added from formation pages, "Mon parcours" and a plan B. 0 JS errors, no horizontal page scroll.

## The jobs a diploma leads to (sprint 8 follow-up, Onisep, formation page)

**What the student sees.** A card "Les métiers visés" on BTS, BUT, licence, IFSI and EFTS pages. It lists the jobs Onisep links to the diploma, each with a link to its Onisep sheet. Each job is flagged "accessible avec ce diplôme" or "après une poursuite d'études", by comparing the job's minimum access level with the diploma's level (BTS bac+2; BUT, licence, IFSI, EFTS bac+3). Jobs with no published level get no flag. The card says that the list is national and belongs to the diploma, not to this establishment, that it is not a promise of a job, and credits "Source : Onisep, Idéo (licence ODbL)". When a diploma has several sheets (BTS options), the card says the jobs come from all of them.

**Data (`suptracker/onisep.py`), checked on the real files before the design.**
- **Source.** Onisep Idéo open data: "Idéo-Fiches formations" (2,397 diploma sheets, 7,040 diploma → job links) and "Idéo-Fiches métiers" (1,124 jobs, with the minimum access level and ROME code). The Onisep site rejects robots, so the owner commits the zips under `data/sources/`. They are recognised by their XML root (`formations`, `metiers`), whatever the file name. The other two files (Métiers CSV, Actions de formation) are not used.
- **Licence.** ODbL: the derived tables are shared under the same licence, with the attribution on the page.
- **Link: by national diploma title, never by establishment.**
  - **BTS.** Same title after normalisation; a BTS published by options takes all its options; a Parcoursup option falls back to the BTS without option.
  - **BUT.** Same specialty, the parcours removed.
  - **Licence.** Same mention, never a licence pro.
  - **IFSI.** The state nursing diploma. **EFTS.** The state diploma named by the formation ("D.E Educateur Spécialisé" → diplôme d'État d'éducateur spécialisé).
  - **Other filières** (CPGE, schools, PASS...) get no card.
  - **Coverage** of the latest campaign: BTS 92.7 %, BUT 100 %, licence 91.3 %, IFSI and EFTS 100 %. A formation without a sheet says so.

**Red team (`scripts/redteam_onisep.py`, run in CI by `tests/test_onisep.py`).** On the real data, 5/5 checks pass and 13/13 mutants are caught.
- **O1.** The XML files are re-read independently: diplomas, links, jobs and access-level ranks.
- **O2.** The link of all 14,252 formations of the latest campaign is re-derived with the red team's own normalisation, plus a truth table of real titles, a same-family check and coverage floors.
- **O3.** The API serves the union of the matched sheets' jobs, and every access flag is re-derived.
- **O4.** The page escapes every Onisep string and URL, external links carry `rel="noopener"`, the caveats and the ODbL credit are present.
- **O5, mutation test.** A BTS borrowing a BUT or licence sheet, a licence pro linked to a licence, BTS options ignored, a BUT parcours kept, a wrong diploma level, "bac ou équivalent" left unparsed, the access flag inverted, and 6 UI mutants. Edge rows are injected so that every link mutant bites on any data.

**UI check (Playwright):** BTS with options, licence, BUT, IFSI, EFTS and a BTS without a sheet, in light, dark and mobile. 0 JS errors, no horizontal page scroll.

## Next-campaign forecast of every indicator (formation page)

**What the student sees.**
- Under the three headline indicators of a formation page, a "Prévision 2026" line:
  - the access rate;
  - the share of terminales générales among the candidates called in the main phase;
  - the number of admits.
- A "Prévision 2026" card lists every forecast indicator in three groups: access and called candidates, volumes (vœux, ranked, proposals, admits, capacity), and the admits' profile. Each row shows:
  - the 2025 published value;
  - the 2026 range at 80 %;
  - the share of 2025 values that fell inside their range when the method was tested.
- An indicator tested below 75 % is flagged "moins fiable".
- A past campaign's page shows no forecast.

**Method (`suptracker/prevision.py`), the sprint-5 "repère" generalised, checked on real data first.**
- **Which formations.** A formation needs at least 2 campaigns with a value. It must be in the latest campaign. For the access rate, the count is of campaigns with a published rate, not sprint 5's campaign count (found by Codex's review).
- **Point forecast.** The last campaign, the mean of the last two, or the mean of all, chosen per indicator on 2024. The mean of the last two wins everywhere, except capacity (the last campaign).
- **80 % range.** The 10th and 90th percentiles of the past errors, per stratum: size of the last campaign × campaigns of history.
  - Rates use errors in points and are clipped to [0, 100].
  - Counts use proportional errors (`log((y + 1) / (hat + 1))`) and are rounded outwards to whole numbers.
- **Hold-out.** The method is set on 2024 and tested on 2025 without seeing it. The served 2026 ranges use the errors of 2024 and 2025.
- **Access rate.** It is not re-forecast: its range is sprint 5's (`mart.forecast`), so "Mon parcours" and the formation page agree.
- **Zero-admit campaigns.** Their admits' shares (`pct_*`) are 0 % by convention. They are ignored, never forecast from or for.
- **What the hold-out showed (2025).**
  - Coverage is measured on the range the page SHOWS: counts are rounded outwards to whole numbers, so they cover more than the nominal 80 %. Admits reach 86 %, admits by bac 92 % and vœux 84 %. The admits' profile is at 78-81 % (found by Codex's review).
  - The share of terminales générales among called candidates reaches only 70 % and is flagged.
  - The ranges are wide for small formations. For the access rate, about ±8 points for 100+ admits and -18/+16 points under 30. For admits, ×0.88-1.08 at 100+ and ×0.67-1.50 under 30.
  - The forecast beats "same as last year" only slightly.
- **Size.** 384,000 rows add 5.5 MB to the warehouse.

**Red team (`scripts/redteam_prevision.py`, run in CI by `tests/test_prevision.py`).** On the real data, 7/7 checks pass and 17/17 mutants are caught.
- **P1.** Independent re-implementation (own SQL loader, numpy quantiles, own strata and bounds). For all 29 indicators, the predictor chosen on 2024 and the 2025 coverage equal the report.
- **P2.** All 383,581 served ranges are re-derived (point, bounds, last value, campaigns). Counts are whole, rates are within [0, 100].
- **P3.** No admits' share is forecast for a zero-admit campaign.
- **P4.** The 13,292 access-rate ranges equal sprint 5's, each with two published rates, and so does its coverage.
- **P5.** The API serves only the latest campaign's page, in order, with the fragile flag.
- **P6.** The page escapes labels, reads every figure from the data, and never says "chance".
- **P7, mutation test.** Two edge formations are injected so every mutant can bite: a zero-admit latest campaign, and a formation that stopped.
  - Data mutants: hold-out leakage, predictor and ranges set on the hold-out, additive count ranges, unclipped rates, one campaign served, strata without size, 90 % instead of 80 %, zero-admit shares used, stopped formations forecast, coverage tested on the unrounded interval.
  - UI mutants: the card not wired, a headline line not wired, an unescaped label, a hard-coded level, the caveat dropped, the flag dropped, a probability wording.

**UI check (Playwright):** light, dark and mobile, plus a past campaign. 0 JS errors, no horizontal page scroll.

## Professional insertion (sprint 8, formation page)

**What the student sees.**
- **On a BTS page, an "Insertion professionnelle" card** for the BTS of this establishment (Inserjeunes):
  - the share of final-year students who continue their studies, who are employed 6 months later and in other situations;
  - the employment rates at 6, 12 and 24 months, among those who left their studies;
  - when Parcoursup groups options that Inserjeunes publishes separately, one row per option, never averaged.
- **On a licence page,** the masters of the same university and discipline as B1 (InserSup): salaried employment in France 18 months after the diploma (among leavers) and stable employment (among those in salaried employment, as SIES publishes it), against all the university's masters and France.
- **On a BUT page,** the same figures for the specialty in the university, all its BUT, and France.

**Data (`suptracker/insertion.py`), checked on real data before the design.**
- **Inserjeunes** (DEPP, lycées and CFA, two datasets): the latest pooled years "cumul 2023-2024".
  - Continuing + employed at 6 months + other = 100 on every published row.
  - The employment rates are among the leavers: `taux_emploi_6 = part_emploi / (100 − poursuite)`, within rounding.
  - The formation code is part of the key (one establishment can publish the same label twice).
  - No headcount is published, so no reliability grade is given.
- **InserSup** (SIES): graduates, every gender, nationality and regime, per establishment (Paysage id) and per diploma (master mention, BUT specialty, LP), plus the total per diploma type.
  - The employment rate is among the graduates who left their studies ("sortants"); the stable-employment rate is among those in salaried employment (stable jobs / salaried, exact on all 24,952 rows with both counts; found by Codex's review). `nd` is NULL, never 0.
  - Fewer than 20 leavers: two classes are pooled (flag `*`).
  - The served horizon is 18 months, the latest published for every recent class; the latest class is served per diploma.
  - **Merged universities.** SIES keeps the former establishments' UAIs with their old classes (Paris Cité 2019 next to 2024). A diploma is therefore keyed by Paysage id, diploma, label and sector, never by UAI.
    - Only diplomas with a class in the latest national year are shown; closed or renamed ones are counted in a note.
    - A diploma or university total published in several parts that year gets no single figure (found by Codex's review).
  - SIES publishes no discipline aggregate per university, so masters are listed one by one.
  - Some stable-employment rates above 100 % exist at 24–30 months (SIES quirk); they are not served.
- **Size.** The full sources weigh about 130 MB. The warehouse stores a column profile (`ref.insertion_profile`) and only the rows a page can use.
- **BTS link.** Same UAI, plus a normalised label (accents, small words, plural, "1re année commune"). Statuses: ok 3,530, options 386, establishment absent 694, not published 247, not found 494.
  - Renamed or new BTS (CIEL, Banque…) have no exit cohort under their new name: no figure rather than the old diploma's.

**Red team (`scripts/redteam_insertion.py`, run in CI by `tests/test_insertion.py`).** On the real data, 9/9 checks pass and 18/18 mutants are caught.
- **I1–I2.** Inserjeunes rows are re-read value by value; masked = NULL; the partition and the leaver identity hold.
- **I3.** BTS link: same establishment only, options apart, renamed BTS never linked, truth table, coverage at least 75 %.
- **I4–I5.** InserSup staging re-derived with the full key (1,516,086 values, 0 differ); identities (employment among leavers, stable jobs among the salaried employed), bounds, ordered quartiles, pooling flag.
- **I6–I7.** Licence and BUT blocks: B1's university and discipline, MEEF apart, latest class per diploma, totals and France. InserSup spells BUT specialties as Parcoursup does ("Science des données", former STID): sprint 6's `SPECIALTY_ALIASES` apply, and all 24 specialties keep their national row (found by Codex's review).
- **I8.** The page escapes stored strings and keeps the wording (leavers, salaried in France, not chances, options apart); nothing is averaged.
- **I9, mutation test.** Oldest class served, a former UAI's old class served, a closed diploma served, BUT aliases ignored, `nd` as 0, masked value as 0, a link across establishments, a renamed BTS key, MEEF in a discipline, the staging filter dropped, and 8 UI mutants (one drops the stable rate's denominator).

**UI check (Playwright):** light, dark and mobile. 0 JS errors, no horizontal scroll.

## Bac technologique and bac professionnel students (B4, "Mon parcours")

"Mon parcours" now serves every series. The student picks *bac général*, *technologique* or *professionnel*; techno and pro students do not pick specialties.

**What SIES allows, and what it does not.**
- **No access rate by series.** `part_terminale_generale/techno/pro` is **not** one. The three add up to 100 % on 99.2 % of rows: each is the series' **share among the candidates in a position to get an offer**. The site used to present the general one as an access rate (fiche, comparator, evolution chart, peer metric). That is fixed everywhere.
- **Official counts by series.** These exist: candidates in the main and complementary phases (`nb_voe_pp_*`, `nb_voe_pc_*`), proposals (`prop_tot_*`) and admits.
- **No detail inside a series.** STMG, STI2D, ST2S and so on are never told apart, and neither are the bac pro specialties. The site says so.

**Stage 1 (which formation types recruit the series).** It counts **admits**, which are people (each néo-bachelier accepts one formation). It never sums candidates across formations, which would count vœux. For each type it shows:
- where the series' admits go;
- the series' share among admits;
- a representation index;
- the median estimated access.

The gates are the same as for bac général.

**Stage 2 (formations of one type).**
- **Estimated access for the series.** The official taux d'accès, scaled by the series' proposal rate relative to all candidates', and capped at 100 %. The raw proposal rate is a different quantity: it counts proposals actually sent, fewer than candidates in a position to get one. It is not comparable with the zone thresholds, so it is shown only as a detail, next to the official rate.
- **Fragile rates.** Below 20 candidates of the series, the zone is *indéterminé*. A techno class with 2 candidates and 2 proposals would otherwise read as "100 %, sécurité".
- **Mention position.** The sharp mention bounds of A3, generalised to every series.
- **Calling groups.** They are read for the student's series, covering all 23 labels of the 2022–2025 exports.
- **No closure by share.** A low share of the series among admits flags the formation as *rare*, never *closed*. A licence de droit stays open to bacs technos, unlike the CPGE ECT rule for bac général.

**Red team (`scripts/redteam_series.py`, 12 checks, run in CI by `tests/test_series.py`).**
- **Group routing.** Every real label is routed correctly for each series. This caught "sauf les Bac technologiques **et** Bac professionnels", which wrongly admitted bacs pros, and a "STI2D" group that wrongly admitted bacs pros.
- **Composition wording.** `part_terminale_*` is never called an access rate again.
- **Counts.** Series counts are consistent.
- **Estimated access.** It is bounded, equals the official rate when the series does as well as everyone, and is monotone.
- **Undefined estimates.** An undefined estimate stays undefined: DuckDB's `least(100, NULL)` returns 100. Found in review: a formation with no proposal at all read as "100 %, sécurité".
- **No zone without a rate.** On real data, 39,525 readings, and none is zoned without a rate.
- **Units.** Stage 1 counts people, not vœux.
- **No false closure.** Licence de droit: 0 of 270 closed. The techno CPGE (TSI, TB, TPC) come out sécurité or cible, and MPSI never does.
- **Fragile rates.** A rate over fewer than 20 candidates never sets a zone.
- **Mention bounds.** They are valid and sharp for bac techno and pro too.
- **Bac général unchanged.** It gives identical results, and the persona check passes.
- **API.** The series is a closed list.
- **Disclosure.** The UI states what is estimated and that STMG, STI2D and ST2S cannot be told apart.
- **Plausibility.** BTS and BUT are predilection types for the series; PASS and L.AS never are for bac pro.

A mutation test seeded 5 bugs, and all 5 were caught.

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


## Comprendre l'appel and Vraie sélectivité (owner's request, 2026-11-09)

The owner shared a UI brief built on students' and teachers' feedback about Parcoursup. SupCompass PREPARES the choice of
vœux: the student has no rank yet, so these pages never ask for one. Three things from the brief can be answered with
published figures only.

**How far the list was called (formation page, tab "Y entrer").**
- **Data check.** The calling groups split the candidates without overlap. So the SUM of the groups' last-called ranks
  (`ran_grp1..3`) is the number of ranked candidates who got an offer in the main phase.
  - In 2025 this sum equals the ranked count (`nb_cla_pp`) for 5 646 formations and exceeds it for 1 of 14 191.
  - In 2022-2024 about one row in ten exceeds it.
- **The card.** For every campaign it shows the candidates, the ranked, each group's last-called rank, the share of the ranked
  who were called (min(1, sum / ranked)) and the places.
  - A sum at or beyond the ranked count reads "toute la liste", never a share above 100 %.
  - Example: BUT Mesures physiques in Le Mans, 2025: 740 + 108 = 848 = every ranked candidate, for 78 places.

**Page "Comprendre l'appel" (`#/comprendre`).**
- It explains three figures not to confuse: the access rate, the last-called rank, and the waiting-list position (which only
  exists after the vœux).
- Per type of diploma (types of at least 20 formations), it gives the median share of the ranked who were called and the share
  of formations that called their whole list.
- It gives the medians of the three published offer-timing shares: from the opening, before the bac results, before the end of
  the main phase. Zero-admit rows are left out.

**Page "Vraie sélectivité" (`#/selectivite/<type>/<mention>`).**
- Each formation of the chosen type (and mention) is placed by two published figures:
  - x: its official access rate;
  - y: the share of its néo-bachelier admits with a "Bien" mention or better (`pct_b + pct_tb + pct_tbf`; the mention shares
    are disjoint and add up to 100 %).
- Formations that cannot be placed are **named** under the graph ("Non placées sur le graphique"), each with its reason and
  its published counts, e.g. "6 admis néo-bacheliers sur 28 admis" (owner, 2026-11-10: the BUT Science des données of
  Carcassonne could not be found, the page only gave a count).
  - This is a quarter of the latest campaign: 3 441 of 14 252 formations in 2025.
  - One reason per formation, the first that applies: no admit (179), fewer than 10 néo-bachelier admits (3 262), access
    rate not published, mention shares not published.
  - The list shows the official access rate and candidates per place; 40 rows first, like the quadrants.
- The quadrant lines are the medians of the selection. The four names (Plus accessible, Très demandée, Admis souvent
  mentionnés, Très sélective) describe a position, never a cause or a chance.
- Each quadrant lists its formations with candidates per place: vœux divided by places, an order of magnitude.

**Not taken from the brief, because nothing published supports it:** the admits' grades (no median /20 exists), the day-by-day
call curve, an "algorithmic score", and rank bonuses for maths expertes, boursier status or the lycée.

**Red team** `scripts/redteam_appel.py` (A1-A7), via `tests/test_appel.py`:
- A1: the depth re-derived by SQL.
- A2: the per-type medians.
- A3: the matrix: placement, exclusions, medians and quadrants; the reason and counts of every formation left out, and
  one crafted formation per reason.
- A4: both pages in Node on hostile data: escaping, labelled cells, "toute la liste", the caveat, no rank input.
- A5: wording.
- A6: wiring.
- A7: 16 in-memory mutants, one skipped where the data cannot show it.

## Profile bar and similar formations (owner's request, 2026-11-10)

**Profile bar (point 4 of the UI brief).**
- What it shows, at the top of every page:
  - the stored profile: bac, doublette, mention, académie;
  - the zone counts of Mes vœux, for example « 3 sécurité · 0 cible · 2 ambitieux ».
- An alert appears when the server's reading of the list says there is no safe vœu (`aucune_securite`), the same message as
  the Mes vœux page.
- It sends the same query as Mes vœux (`vxQuery`), so both always count the same zones.
- Without a profile, it links to Mon parcours. With an empty list, it sends nothing. On a phone it wraps under the search bar.

**Similar formations (`semblables.py`).** When a formation's own public report has no bac général table by doublette, or no
readable jury texts, the page reads the verified reports of the formations of the same diploma and mention: same SIES `fili`
and `fil_lib_voe_acc`, for example every BUT Gestion des entreprises et des administrations, same session.
- **Data check (2026-11-10, 2025 session, a shared report counted in each group it covers):**
  - 7 582 formations have no bac général table of their own. 4 198 of them get similar-formation figures (2 229 for
    Maths + SES).
  - 1 660 formations have no verified report. 1 526 of them get the jury counts of their similar formations.
  - FCIL and "Licence professionnelle" group unrelated formations, so they get none.
- **Doublettes.**
  - For a doublette, the reports that detail it are added up: candidates in position to receive a proposal, out of
    candidates who confirmed. "All bac général" is taken from the same reports.
  - A formation's own "Autres doublettes" row is never pooled.
  - Minimum: 3 reports and 20 candidates. Reports not yet cross-checked are left out, and a concours report counts once in each group of similar formations it covers, read from that group's own formation.
  - The figure for the formation is an estimation: its bac général proposal rate × (doublette / all bac général in those
    reports), capped at 100.
  - It comes before the national group estimate. A figure from the formation's own report is never shown beside it. The
    formation page, the evolution chart and Mes vœux show the same figure.
- **Jury.**
  - Counts of reports per evaluation field and published importance (the highest one when a report rates several rows of the
    field), per specialty and per option cited. Never a mean or a score.
  - The card says it is not this formation's report and that the formation's Parcoursup page prevails.
  - It links the similar formations' own pages, where their texts are shown in full.
- **Build.** The pooled figures are precomputed: `mart.semblable_dbl`, `mart.semblable_jury`.
- **Red team `redteam_semblables.py`:**
  - K1: crafted reports with hand-computed answers.
  - K2: SQL re-derivation, and jury counts with an independent field mapping.
  - K3: the own report is never read through this block.
  - K4: the Python and page twins of the estimate agree.
  - K5: the same figure on every page.
  - K6: rendering on hostile data.
  - K7: the profile bar.
  - K8: wording and wiring.
  - K9: mutation test.

## Faster CI: three runners and one synthetic build per input set (2026-11-10)

PR #41's single CI job took 56 minutes (52 for the parallel step), past the old 60-minute limit once the timed tests ran.

- **Where the time went (measured per file, local run, 4 workers).** The parallel step is 141 CPU-minutes.
  - The real-data red teams weigh the most: carte 15 min, doublettes 10 min.
  - 32 of the 36 test files rebuilt the same synthetic warehouse, 1 to 2 minutes each.
- **Three runners.** `tests/conftest.py` adds `--shard i/n`. It spreads the test files by their measured duration
  (`tests/durations.json`, heaviest first onto the lightest shard). A file missing from the table still runs, with a default weight.
  - The workflow runs shards 1/3, 2/3 and 3/3 side by side.
  - The timed red teams (analytics, Plan B, search) get a runner of their own, so nothing else runs beside them.
  - A final `test` job is green only when every shard and the timed job are green; it keeps the check name the repository knows.
- **One synthetic build per input set.** `tests/synthetic.py` `cached_build` builds once and copies the warehouse to each test.
  - The key covers everything the build reads: the package code, the fixture, the raw files and the argument files (by content),
    the `SUPTRACKER*` environment, and every `data/` file that is not a build output (by size and time).
  - Any change of input is a new build, so a copy is never stale. xdist workers share it through a file lock.
  - `SUPTRACKER_NO_BUILD_CACHE=1` builds every time.
- **Guards.**
  - `tests/test_shards.py` collects each CI shard and checks that every test file runs in exactly one, with no empty shard.
    It also checks that `durations.json` lists exactly the parallel files, and that the build cache key changes with each input.
  - Red team S6 checks that the matrix lists shards 1..n with `--shard=i/n`, and that the `test` job fails when any job fails.
    S7 adds four mutants: a shard left out, another shard count, the timed job ignored, and the gate skipped on a failure.

## Ready for the 2027 campaign (2026-11-10)

The 2027 campaign opens in December (catalogue) and January (vœux). Three things would have gone wrong silently.

- **The SIES rollover.**
  - `fr-esr-parcoursup` always holds the latest campaign. When SIES publishes 2026 (expected early 2027, as 2025 came out
    in March 2026), it moves to 2026, and 2025 gets a frozen `fr-esr-parcoursup_2025`.
  - The registry read `parcoursup_2025` from the rolling id and trusted its own year over the file's. The monthly refresh would
    have loaded 2026 under 2025 and dropped 2025.
  - Now each vœux file is kept only if its own `session` column (SIES alias `annee`) is the registry year
    (`ingest.check_session`). `parcoursup_2025` tries the frozen id first, then the rolling one.
  - If the rolling id already holds 2026 before the frozen copy is out, the refresh stops with an error: it never publishes
    the wrong year.
  - `parcoursup_2026` is an optional slot. When SIES publishes it, the file is ingested and the run shows a warning
    "Nouvelle campagne SIES". The site is not built on it until `config.YEARS` is updated (labels, forecasts, hold-outs).
  - The live check in `verify_ground_truth` reads each campaign from the id it was really ingested from.
- **New reports reached the site only when code changed.**
  - The warehouse fingerprint left out `data/rapports/harvest`, so a day's new reports never published a new warehouse.
    They are now part of the fingerprint.
  - The data workflow also runs after each successful harvest run on `main` (`workflow_run`). It rebuilds only when the
    harvest files differ from those of the last published warehouse (`data/harvest_fingerprint.txt`). While the fiches are
    closed, the harvest writes nothing and no build runs.
  - The scheduled refresh is now weekly (Mondays), so the 2027 cartographie (mid-December) and the SIES 2026 campaign reach
    the site within a week.
- **The live harvest's order.**
  - Formations come first when they have no report of the NEWEST report session read (`max(core.rapport.session)`).
    It used to be the latest SIES session.
  - In January the fiches link 2026 reports while SIES stops at 2025. Under the old rule, every formation already holding a
    2025 report would have waited behind the others.
  - Those 2026 reports stay "pas encore recoupé" until SIES 2026 is built (rule R9), then they are cross-checked or dropped.
- **Tests (`tests/test_campaign.py`).**
  - Today's layout; the rollover; a rollover before the frozen id exists (the refresh stops); the session check on text values.
  - The live harvest's order.
  - The data workflow: the trigger, the harvest in the fingerprint, the gate, the weekly schedule.

## "Compléter ma liste" in Mes vœux (owner's request, 2026-11-10)

When the reading of the list says "aucun vœu de sécurité sûr", the page shows a card of safety vœux in the filières the
student already chose.

- **Rules (`voeux.completer`, `/api/voeux/completer`).** These are Plan B's rules, restricted to a safety read with certainty:
  - for each (type, programme `fil_lib_voe_acc`) of the student's vœux;
  - the formations in the zone "sécurité" without uncertainty, with a solid reading (`planb.usable`);
  - not already listed, and not of the same concours pool as a listed vœu;
  - fee-charging private institutions only on request, then flagged "privé payant";
  - at most 2 per establishment and 3 per filière;
  - the student's académie first, then the distance to the nearest vœu of that filière.
  - A filière with no such formation is said so. With a sure safety in the list, nothing is computed.
- **Data check (real warehouse, bac général MATHS + SES).**
  - For a list of selective formations: 58 safety alternatives in Droit, 25 in Informatique, 2 in BUT GEA, none in some
    Psychologie programmes.
  - It takes about one second per list.
  - "Informatique" is both a licence and a BUT, so each group carries its type.
- **Route and privacy.** The route takes the same inputs as `/api/voeux`. It records no analytics event and is `no-store`.
- **Page.**
  - The card loads only on the `aucune_securite` message, and its render is race-guarded.
  - Each row has "ajouter à mes vœux" (disabled at 10 vœux). A box shows the paid institutions left out.
  - Every figure cell carries its `data-label`.
  - The text says these are zones of past admitted cohorts, "pas des chances d'admission".
  - Playwright: light, dark and phone views, no JS error, no horizontal scroll, and adding a suggestion updates the list.
- **Red team (`redteam_voeux.py`).**
  - V7 re-derives every suggestion independently, with the paid toggle on and off. It also runs with 10 per filière on a
    programme where one establishment has 3 or more safeties, so the cap of 2 shows.
  - V8 checks the route's inputs, the absence of analytics, `no-store`, and the card's escaping, labels, race guard, wording and wiring.
  - V9 is the mutation test: 17 mutants (10 Python, 7 page), all caught on real data.

## The carte red team no longer sets the CI pace (2026-11-10)

On real data, the carte red team took 13 minutes, 12.4 of them in C8, its mutation test.
- `redteam_carte.run` now takes `checks=` and `part=(i, n)`.
- `tests/test_carte.py` runs every check but C8 on real data.
- `tests/test_carte_mutants_{1,2,3}.py` each run every third mutant. They are separate files, so the CI shard planner
  spreads them. Each part must catch all its mutants, and the three parts cover every mutant once.

## Product audit, 2026-11-10: three defects found and fixed

A full walk through the app on a phone, the warehouse and the live monitor's logs found three defects.

- **The Spécialités page was broken.**
  - Opened from the menu, it sent `session=` (empty). The API answers 422, and the page showed "[object Object]".
  - The page now sends only the parameters it has.
  - `apiErrorText` never shows a raw validation error: a FastAPI 422 carries a list of objects.
- **The first search of an instance took about 4 s on the live site** (monitor logs: 4.0 s and 4.1 s; 2 s locally).
  - The index was built at the first search. The background warm-up gets no CPU between requests on a serverless instance.
  - The build now stores the index in `mart.search_index` as compressed JSON (2.3 MB; the warehouse is 85.5 MB), never a
    pickle. Loading it takes 0.3 s.
  - `INDEX_VERSION` is the digest of `search.py`. An index stored by another version of the code is ignored and rebuilt on
    the spot, so a stale index is never served.
  - The documents are read in a fixed order, so the stored index and a rebuilt one are equal.
  - The text functions (`fold`, `stem`, tokens, place keys) are memoised: same results, a rebuild in 1.4 s instead of 2 s.
- **The profile bar told a new visitor "les zones de vos vœux ne peuvent pas être lues"** when they have no vœu yet. With an
  empty list it now says what the profile brings.
- **Measured on the rebuilt warehouse (84.7 MB):** the first search of a fresh process takes 0.37 s instead of 2.06 s.
- **Guard.** A test fails when the committed warehouse carries the index of another version of `search.py`: the warehouse must
  be rebuilt on the branch (data workflow) before such a change is merged.
- **Tests (`tests/test_search.py`).**
  - The stored index equals a rebuilt one and is the one used.
  - Another code version rebuilds it.
  - The blob is JSON.
  - The error text never contains "object".
  - The Spécialités call and API (200 by default, 422 on the old call).

## Qui sont les admis ? Néo-bacheliers and other admits (owner's request, 2026-11-10)

A quarter of the admits are not néo-bacheliers, and a page that reads only the bac mentions hides them. SIES publishes, per
formation and campaign, the admits, the néo-bachelier admits (they passed the bac that year) and the other admits (already
holding the bac or another route: reorientation, return to studies...). SIES does not split the other admits further.

**What the data says (2025).**
- 175 502 of the 660 752 admits are not néo-bacheliers (26.6 %).
- They are the majority in 2 067 formations. The share varies by type: travail social 58 %, IFSI 37 %, licence 35 %, BTS 23 %,
  BUT 17 %, CPGE 6 %.
- The two published counts add up to the total on every row of 2024 and 2025, and on all but 21 (2022) and 15 (2023) rows,
  where they miss it by one or two.

**Formation page.** "L'essentiel" gets a line "Qui sont les admis <session> ?":
- a two-part bar from the published counts, drawn only when they add up to the published total (otherwise the counts are given
  and the page says they do not add up);
- the counts, and the published share of néo-bacheliers;
- a note: the mentions and bac series SIES publishes cover the néo-bacheliers only.

**Lists.** Search, map (list and card), comparator ("Néo-bacheliers / autres admis" row) and Mes vœux carry the label "Majorité
d'admis hors néo-bacheliers" when, in the campaign shown, the counts add up, there are at least 10 admits and the other admits
strictly outnumber the néo-bacheliers (5 220 formation-campaigns, 1 434 in 2025).
- One rule, on the server (`suptracker/admis.py`); the routes add the flag to NEW dicts (search results come from shared index
  documents, which are never modified, so the search index and its version do not change).
- Apprenticeship offers of the map and vœux that are not situated are never labelled.
- Own colour tokens `--adm-neo` / `--adm-autres` in both themes, never a zone's, a route's or the accent; every colour is named
  in text.

**Red team** `scripts/redteam_admis.py` (H1-H6), via `tests/test_admis.py`:
- H1: the rule re-derived in SQL on all 55 844 rows, edge rows, and a crafted warehouse (two campaigns that disagree, a tie,
  counts that miss the total, rows outside the list, untouched inputs).
- H2: every route (search by words and by code, formation, comparator, map, Mes vœux) against SQL; the index documents untouched.
- H3: the page in Node: the bar, its widths and text alternative, the label only from the flag, the comparator cell.
- H4: wording. H5: wiring and design tokens.
- H6: 24 seeded bugs, each caught (on the synthetic and the real warehouse). 11 s on real data.

## Sprint 18: measuring what students do (owner's go, 2026-11-11)

Until now the audience dashboard counted page views, searches, formation pages, clicks to Parcoursup and feedback votes. It
could not tell whether students used the tools that matter. Three actions are now counted, with the same rules as everything else
(no cookie, no identifier, daily pseudonym, Do-Not-Track and GPC honoured, closed lists):
- **vœu added** to the list (counted once it is really added, never an attempt on a full list);
- **Plan B opened** ("Voir un plan B" in Mon parcours and in Mes vœux);
- **a formation-page tab opened** (closed list: Y entrer, jury, réussir, emploi, historique).

**Never the formation concerned**: the list a student considers is not recorded, only that an action happened. The beacon refuses
any other action or tab (422), and a formation code sent with an action is dropped.

Dashboard (`#/stats`): a KPI "Visiteurs ajoutant un vœu" (a rate of visitors, Wilson interval, Holm-corrected with the others), an
"Actions des élèves" table (distinct visitor-days and number of actions) and the tabs opened. Mes vœux gets its "Cette page vous a
aidé ?" box. The Mes vœux privacy sentence now says what is counted: "rien n'en est enregistré sur le serveur. Le site compte
seulement, sans savoir de quelle formation il s'agit, qu'un vœu a été ajouté".

**Red team** `scripts/redteam_analytics.py`: R23 closed list (4 accepted, 6 refused, no code stored), R24 counting (events and
distinct visitors, the KPI a rate in [0, 1], the Mes vœux vote), R25 page wiring (counted after the addition, never a code, fiche
tabs only, both Plan B buttons, the texts), R26 mutation test (11 seeded bugs in the server, the page and the dashboard, each caught).

## Sprint 19: a shorter formation page (2026-11-11)

**Measured before**: on an iPhone 13 the formation page was 17.6 screens long, and its summary ("L'essentiel") started below the
first screen when the profile bar showed an alert.

**Changes**
- "Y entrer" keeps five cards in view: official indicators, your doublette, how far the list was called, Plan B, options and good
  to know. Five are folded under "Plus de chiffres sur l'admission": next-campaign ranges, offer timing, lycées of origin, the
  three-stage funnel and the comparison with the filière (its "P93" percentiles).
- "L'essentiel" links to the jury tab: "Ce que regarde le jury : son rapport public 2025 →", or "Ce que regardent les jurys de
  formations semblables (pas de rapport pour celle-ci) →". The link and the tab come from the same render, so a link never points
  to a missing tab. It is a link, not a checklist (the "projet motivé" feature stays rejected).
- The header has two rows: the establishment code moved to the history tab; the session, evolution, Parcoursup and map links sit
  under the summary.

**Measured after**: 10.3 to 11.7 phone screens instead of 17.6; the summary is in the first screen with the alert shown.

**Red team** `scripts/redteam_ux.py`: X16 (five cards in view, five folded, link and tab from one render, escaped session, compact
header), X17 (6 seeded bugs, each caught); X7's phone limit lowered from 14 to 13 screens.

## Sprint 20: bac techno and bac pro, "votre ligne" in the jury report (owner's go, 2026-11-11)

**Why.** In 2026, 12.5 % of bac pro and 5.6 % of bac techno candidates got no offer, against 1.4 % in bac général. On the site,
"Mon parcours" leaves 25.6 % of formations "indéterminé" for bac techno and 41.4 % for bac pro (bac général: 0.7 %).

**What the data says (verified reports, 2025).**
- The reports print one table per bac route. For bac techno a row is a series with its two terminale specialties
  ("Msgn/ Mercatique & Droit et Economie" is STMG Mercatique); for bac pro it is the specialty. Each table ends with the
  formation's own bucket ("Autres doublettes" / "Autres spécialités").
- 6 195 formations print a bac techno table and 3 144 a bac pro table; the table is not published (small numbers) in 5 791 and
  8 453.
- 13 techno labels (STMG x 4, STI2D, ST2S, STL x 2, STD2A, STAV, STHR spelt two ways, S2TMD music and dance) and 62 bac pro
  specialties. For an STMG Mercatique student: own row in 2 590 formations, the bucket in 3 538.
- The rows count only candidates schooled in terminale in France (about 40 % of the techno vœux SIES counts): said on the card.

**What changes.**
- `suptracker/voies.py`: one explicit rule per techno label (`BT_RULES`); bac pro labels normalised (`bp_key`: accents, case, a
  leading "Bac pro", "opt." = "option", punctuation). A reformed diploma keeps its own key. Every report row gets a `voie` key.
- Profile ("Mon parcours"): bac techno students pick "Série et spécialités", bac pro students their specialty, or "Autre". The
  choices come from the reports (`/api/journey/vocab` → `voies`), with the number of formations printing each row.
- Formation page: "Votre ligne dans cette formation : 36,1 %", the row's name, its counts, the row marked in the table; else the
  formation's bucket ("votre série en fait partie"); "le tableau n'est pas publié" when masked; a prompt when no choice is made.
- Mes vœux: a column "Votre ligne dans le rapport du jury (cette formation)" for bac techno and pro (`/api/voeux?voie=`).
- Mon parcours: "Une part faible veut dire « rare », pas « fermé »", and for bac pro a link to the map's apprenticeship offers.
- The zones are unchanged: this does not reduce the "indéterminé" readings of small formations, and the page never says it does.

**Red team** `scripts/redteam_voies.py` (W1-W8), via `tests/test_voies.py`:
- W1: every printed techno label read twice (rules and an independent keyword reading), no unused rule.
- W2: bac pro format variants merge, different words never do (crafted and warehouse).
- W3: 1 120 picks on the warehouse re-derived by SQL, plus crafted cases (own row, bucket, masked, no choice, bac général).
- W4: the vocabulary (counts re-derived, a crafted warehouse), Mes vœux against SQL, bac général unchanged, hostile values.
- W5: the page in Node (twin of `pick_voie`, one row marked and named, bucket, masked, escaping, profile line, query).
- W6: wording. W7: wiring.
- W8: 19 seeded bugs, each caught, on the synthetic and the real warehouse.

## Sprint 21: "Je me réoriente ou je reprends mes études" (owner's choices, 2026-11-11)

**Why.** About 30 % of Parcoursup candidates are not in terminale (reorientation, return to studies, other routes). SIES
publishes no access rate, no mention and no series for them, so "Mon parcours" had nothing to show them.

**What the data says (SIES exports).**
- SIES publishes, per formation, the "autres candidats" (not in terminale): `nb_voe_pp_at`, `nb_voe_pc_at`, `prop_tot_at`, next to
  the totals and each terminale series. They were not ingested before; they are now (`schema.py`), and used as published.
- Cross-check: the three series plus the others equal the total for the candidates on every row but 2 (2025), for the proposals on
  every row but 64 (2022, where the published figure differs from the difference: the published one is used).
- 44 rows of 2023 and 14 of 2024 publish more proposals than candidates for this group: no figure there.
- 2025: 22.8 % of these vœux got a proposal, against 33.7 % for the néo-bacheliers (CPGE 4.7 vs 31.7; engineering schools 28.2
  vs 49.1; EFTS 36.2 vs 29.1). 12 462 of 14 252 formations have at least 20 such candidates.
- The first version rebuilt the group as total minus the three series; the independent review found the published columns.

**What changes.**
- `suptracker/reorientation.py`: the "accès estimé hors terminale" = official access rate × (the group's proposal rate ÷ all
  candidates' proposal rate), capped at 100 (flagged when capped). It is the series rule of "Mon parcours" applied to this
  group. It is always an estimation, shown with its counts. There is no figure below 20 candidates or when the counts do not hold.
- Home: a fourth door, "Je me réoriente ou je reprends mes études" (`#/reorientation`).
- The page lists every formation of a type of diploma (and mention) of the latest campaign. Each row shows the estimated access,
  the official rate and the share of admits who are not néo-bacheliers (sprint 18's published counts). Filters: type, mention,
  the student's académie, and "admis hors néo-bacheliers majoritaires". Order: the student's académie first, then the name, never
  a figure. The académie never leaves the browser (`/api/reorientation?diplome=&mention=`, shared cache).
- Profile: "Situation: En terminale / Je ne suis plus en terminale" (or "C'est ma situation" on the page). With that status:
  - "Mon parcours" opens this page;
  - the formation page's summary shows "Accès estimé hors terminale" instead of the zone;
  - Plan B is not offered (it compares zones), and the page says why;
  - "Mes vœux" reads `/api/reorientation/voeux` (codes only, `no-store`, no audience event). It shows no zone tiles, no alert,
    no Plan B and no "Compléter ma liste", and says why;
  - the profile bar makes no zone request.
- The old bac series is not asked: SIES does not split this group.

**Red team** `scripts/redteam_reorientation.py` (E1-E8), via `tests/test_reorientation.py`:
- E1: the block re-derived in SQL from the published columns on every row of every campaign (55 844 real rows), the published
  counts measured against the series (above), plus 16 crafted edge rows: threshold, cap, exactly 100, negative or excessive
  counts, a published count that differs from the difference, NULLs, no proposal, admits that miss the total, a tie.
- E2: the listing equals the latest campaign's SIES formations of the type; apprenticeship offers are never listed; each block
  equals E1's; rows carry only the keys the page reads; unknown or hostile types get a 404.
- E3: cache policies, no audience event, hostile or too many codes (a 422, never a 500), formation and Mes vœux blocks.
- E4: the page in Node: escaping, `data-label` on every cell, the reason when there is no estimate, the order (académie, then
  name; shuffled figures give the same order), paging, filters, the situation button, nothing personal sent.
- E5: the profile status (validated, escaped), the profile bar, Mes vœux, Plan B and the "Mon parcours" delegation, in Node.
- E6: the formation summary tile. E7: wording and wiring.
- E8: 49 seeded bugs in the rule, the routes, the page, the profile and the wording, each caught.

**Independent review** (a second agent, not shown the red team's conclusions). Its findings, all fixed:
- the published "autres candidats" columns (above);
- a visitor with no profile who picked an académie got a half-filled terminale profile, with zones: the académie is now kept apart;
- a reorientation profile kept its old bac fields, still read by the map zones, the doublette and jury cards, the evolution chart
  and the BUT rows: every such read goes through `bacProfile()`, which returns nothing outside terminale;
- a late answer could draw the list over another page (marker set before the first await);
- the formation page had the estimate without its counts: a folded card in "Plus de chiffres sur l'admission";
- "0 %" now says "rare cette année-là, pas forcément fermé"; four doors in a 2 x 2 grid; a clear 404 for an unknown mention.
Each gap it found in the red team is now a check and a mutant.

## Sprint 22: accompaniment (owner's go, 2026-11-11)

**Why.** Students choose their vœux with an adult (parents, professeur principal). They also need the campaign's dates, and the
seconde/première students choose specialties before Parcoursup. The product audit found no way to share a list and no calendar.

**What the data says.**
- The 2027 calendar is a PDF on parcoursup.gouv.fr (published October 2026). That host is blocked in the sandbox, so a new
  workflow, `suptracker-calendrier`, fetches it with `scripts/calendrier_fetch.py`, which only accepts parcoursup.gouv.fr
  addresses. It is triggered by a push of `data/calendrier/request.json`.
- The workflow stores three versions of the PDF and their text. The dates agree, but the first version's heading reads
  "samedi 10 juin 2027" where the others read "samedi 10 juillet". 10 June 2027 is a Thursday.
- The seconde/première entry uses the stage-1 figures of "Mon parcours" (share of each doublette among a filière's bac général
  admits, 2022-2025, counting-break campaigns excluded).

**What changes.**
- `suptracker/calendrier.py` reads each official step with one fixed rule anchored on its wording. A date is served only if
  every version prints it identically with its true weekday; otherwise the step says "date à vérifier sur parcoursup.gouv.fr".
  All 9 steps are verified, from the opening of the 2027 formation map (17 December 2026) to the end of the complementary phase
  (9 September 2027).
- Calendar routes and page:
  - `/api/calendrier` and `/api/calendrier.ics` (shared cache; all-day events, the same file for everyone).
  - `#/calendrier`: the next step and its countdown, the three official steps, what to do on SupCompass at each one, and
    "le calendrier officiel fait foi".
- `#/accompagner`, for parents and professeurs principaux: what the figures show, what SupCompass never does (no admission
  prediction, no ranking, no account), how to look at the student's list together, and questions for the conversation.
  The page is printable.
- `#/premiere`: three specialties of première give the three possible terminale doublettes. For each filière, the page shows
  the share of each doublette among the admits. Rows are ordered by where these bacheliers go, never by a chance. The page says
  it is a composition of admits, not advice.
- Mes vœux gets "Partager ou imprimer ma liste":
  - The link is `#/liste/<codes>[/<profile>]`. Everything after "#" stays in the browser, and nothing is stored.
  - The profile (bac, specialties, mention) is in the link only if the student ticks the box. The académie and the lycée are
    never in it.
  - `#/liste` reads zones only with a joined terminale profile, the estimated access outside terminale, and official rates
    otherwise.
  - "Ajouter à ma liste" merges up to 10 vœux. It never replaces the recipient's list or profile.
- Printing hides the menus and buttons and adds the date and "pas des chances d'admission".
- Menus: "Calendrier" and "Accompagner un élève". The home page gets links to seconde/première, the calendar and the adult page.

**Red team** `scripts/redteam_accompagnement.py` (T1-T8), via `tests/test_accompagnement.py`:
- T1: the calendar re-derived independently from every version (each date printed with its true weekday next to its wording;
  the known misprint never read), plus crafted versions: disagreement, wrong weekday, missing step, a range ending before it
  starts, hostile text, no file.
- T2: the .ics parsed independently (CRLF, lines of at most 75 octets, exclusive end, unique ids, escaping, a stable file).
- T3: routes, cache, no audience event, the fetch script refusing foreign hosts, the source register, and the Vercel bundle
  (PDFs out, text in).
- T4: the calendar page at fixed dates (countdown, states, unverified date said, escaping, race).
- T5: seconde/première (pairs, each cell its own share, order, missing and rare doublettes, stored choices validated).
- T6: the shared list (validation, link round trip, profile only on request, reading per profile, merge, race).
- T7: wording and wiring.
- T8: seeded bugs, each caught.

**Independent review** (a second agent, not shown the red team's conclusions). All its findings are fixed:
- The shared list showed the bac techno / pro series ESTIMATE under "Taux d'accès officiel": it now shows the official rate.
- A student with no stored profile could share the page's default profile (MATHS + SES): the box is offered only with a stored
  profile.
- Unread dates: the page said "campagne terminée" and the .ics was an empty file. The page now says the dates must be checked,
  and the .ics answers 404.
- Fetch script:
  - a run that reads no PDF keeps the previous log and fails;
  - a redirect off parcoursup.gouv.fr is refused;
  - the PDFs are no longer committed (their illustrations are not under the Licence Ouverte), only their text and digest;
  - the workflow runs weekly.
- Printing in dark mode gave light text on white paper: the print rules redefine the colour tokens.
- Robustness:
  - a cut link ("%E0%A4%A") no longer breaks the router;
  - races before the page marker are closed;
  - a choice made while the doublettes load is kept;
  - a server failure is no longer said as "absent".
- The shared list hides the recipient's own profile bar and tab.
- "Today" is Paris's date.
- The link no longer carries the bac pro route (data minimisation), and codes are trimmed.
- Wording: official step names, and the complementary phase as the PDF words it.
Each review gap is now a red-team check with a mutant.

## Sprint R1: menus that follow the student's journey, and an explained "Mon profil" (owner's choices, 2026-11-11)

The site was rebuilt around the journey of a student, a parent or a *professeur principal*. The owner chose the four options
recommended in the redesign proposal: one "Explorer", one sourced figure for the profile (R2), the profile sent but never kept
for the zone filter (R3), and navigation + profile first (this sprint).

**Menus.**
- On a phone, the bottom bar is **Explorer · Mon profil · Mes vœux · Calendrier · Plus**. "Plus" holds the comparator,
  Comprendre l'appel, Vraie sélectivité, Spécialités, Qualité des données, Glossaire, and "Parents et professeurs".
- On a wide screen, the top menu has the same four entries, a **Comprendre ▾** menu (the same six reading aids) and
  "Parents et professeurs". On the right, a **profile chip** shows "bac général · MATHS + SES · bien" (or "Créer mon profil")
  and opens the profile page. Both menus open on a click and close on Escape (focus back on their button) or on a click elsewhere.
- **Explorer** is one place with three views of the same offer: **Liste** (search), **Carte** and **Métiers**. The switch sits
  at the top of the home, the search results, the map and the job catalogue. Every formation page counts as Explorer.
- **Mon profil** covers the profile page, "Où je me situe" (the former "Mon parcours", same address `#/parcours`),
  "Je me réoriente" and the seconde/première page. Old addresses keep working.

**"Mon profil" (`#/profil`)** is the one place the profile is edited.
1. *Votre situation*: en terminale, je ne suis plus en terminale (reorientation, sprint 21), or a link for seconde/première.
2. *Votre bac*: series, then the two specialties (bac général) or the series and specialties / bac pro specialty (sprint 20),
   Mathématiques expertes when Maths is chosen.
3. *Votre mention visée*.
4. *Où vous êtes*: académie, lycée (optional), boursier.

Every field says what it is used for, in plain words (no column name). Only the fields of the chosen situation are shown:
outside terminale, the académie alone. The **first save is explicit** ("Enregistrer mon profil": nothing is read for the student
before it); once a profile exists, each change is saved at once. Switching to "Je ne suis plus en terminale" keeps the bac fields
already entered, and switching back restores them. With none stored, the form shows the defaults and asks to save again: a bac
field is never invented. "Effacer mon profil" asks for a confirmation in the page and keeps the vœux list.

The page then lists what the profile changes (formation page, map, Mes vœux, Où je me situe) and what happens to it. It stays
in the browser. To read the zones, the pages send the bac, specialties, mention and académie: answers are not stored and no
audience figure carries them. The lycée is searched in the browser and never sent. A shared list includes the profile only when
the box is ticked. The page itself sends nothing but the vocabulary request.

Every prompt that used to point at "Mon parcours" to fill in a profile now opens "Mon profil". The home page says which profile
the figures are read for, or invites the student to create one.

**Red team** `scripts/redteam_navigation.py` (U1-U8; `tests/test_navigation.py`):
- U1: the menus, and every page reachable from both.
- U2: the route → tab tables and the closed analytics routes.
- U3: the chip, run in Node (escaped, validated, hidden on the stats and on a shared list).
- U4: the form, run in Node (fields per situation, an explanation per field, escaping, explicit first save).
- U5: reading the form (no invented bac field, validated status, a bac techno/pro route kept only with the same bac).
- U6: the browser flow (`--browser`): first save, saving on change, situations, erase, menus, phone screens.
- U7: wording and privacy.
- U8: 27 mutants built in memory.

Red teams that read the old menu or the old form location were updated: ux X3/X6/X12/X14, reorientation E5/E7, lycée Y8,
voies W7/W8, semblables K7/K9, accompagnement T7/T8.

**Independent review (before Codex): seven defects fixed, each now caught by the red team.**
1. "Retirer" (lycée) saved the profile before "Enregistrer".
2. Enter in the lycée box saved it too.
3. A situation switch with no saved profile stored at once and lost the draft. It is now part of the draft, and the bac fields,
   lycée and boursier come back when switching back.
4. "C'est votre lycée ?" from a search stored invented bac fields. Without a profile it now only pre-fills "Mon profil".
5. "Où je me situe" could draw over "Mon profil" after a late answer. It now has a render marker, checked after every await.
6. The chip and the profile bar stayed visible on the stats page: their `display` beat the `hidden` attribute.
7. The focus went back to the first situation radio after a switch.

Smaller fixes from the same review:
- identical specialties are flagged on "Mon profil", and "Où je me situe" links there;
- "Mathématiques expertes" is kept when its box is not drawn;
- a menu closes on a click on one of its links.

## Sprint R2: "Pour votre profil", one sourced figure beside the official access rate (owner's choice, 2026-11-11)

The formation page's summary ("L'essentiel") now shows two rates side by side. First comes the **official access rate**
(all candidates, main phase). Next to it comes **one figure for the student's profile**, with its source in words. The owner
chose this option, "Un seul chiffre sourcé": one figure, never several competing ones.

The figure is the one the "Selon votre bac" card already shows, chosen by the same rules in the same order (`profileRate`).
A published figure replaces an estimate and never sits beside it.

| Profile | Figure, in this order | Shown as |
| --- | --- | --- |
| Bac général | the formation's own report, when it has a bac général table: the student's doublette row, else its "Autres doublettes" line | "publié · rapport du jury 2025" |
| | otherwise, the similar formations' estimate (`estimateSemblable`) | "estimation · rapports de N formations semblables" |
| | otherwise, the national group's estimate (`estimateDoublette`) | "estimation · écart national de votre doublette" |
| | otherwise, the card's "votre bac" row: the formation's bac général proposal rate, from published counts | "taux de proposition de cette formation (effectifs publiés)" |
| Bac techno / pro | the student's line of the report (`pickVoie`, sprint 20) | "publié" |
| | otherwise, the card's "votre bac" row: this formation's proposal rate for the student's route, for the page's own campaign | "taux de proposition de cette formation (effectifs publiés)"; "peu de candidats (n)" below 20, as on the card |
| Not in terminale | the estimated access outside terminale (sprint 21), in its own tile | (no zone tile) |

If the report has a bac général table but no row and no "Autres" line for the student's doublette, the tile says so. No
estimate stands in for it. A report figure is shown with its counts ("7 sur 9 candidats"). A bac général profile without two
distinct specialties gets a link to "Mon profil", never a figure.

A report SIES has not cross-checked yet carries "pas encore recoupé". The tile opens the "Y entrer" tab, where the card gives
the calculation.

The summary has 5 tiles with a terminale profile: official rate, for your profile, zone, admits, jobs. It has 4 without a
profile (one tile invites the student to create one) and 4 outside terminale. On a phone the tiles sit two by two and the fifth
spans the row. The page only rearranges figures it already had: no new request and no new data.

**Two arts specialties (owner's rule, 2026-11-12).** In terminale a student keeps two different specialties of the three of
première, and only one of them can be artistic. The form has a single "Arts" code, and its second list never offers the
specialty picked first. What the form shows is what is stored (Codex): when the first specialty is set to the second one, the
pair is made distinct before it is saved (the former first specialty takes the second place, `spe2Of`). A stored profile with two
identical specialties (an older one) is shown as invalid: "Choisissez" is selected in the second list, with a warning that zones are
not read before, and nothing is replaced until the student picks. The national `ART+ART` rows are not a doublette a student can
hold, so they are never asked for. Red team navigation U4-U6 checks the rule, its wording, the save and the browser (7 mutants).

**Independent review (before Codex).** The first version filled the bac techno / pro fallback from Plan B. That was the latest
campaign's estimated series access, and it caused four problems:
- it ignored the "fewer than 20 candidates" rule;
- it used its own "rare" rule;
- it was unlabelled on an older-session page;
- it was a figure the card does not show.

The tile now shows the card's own "votre bac" row for the page's campaign, with the card's "peu de candidats" flag.

**Codex (PR #54).** The route rate and the estimates carry every campaign of the formation's lineage, and their top-level figure
is the latest one. A 2022 page could therefore show a 2025 rate beside "Taux d'accès 2022". The tile now reads the trend entry
of the page's own campaign; with no entry, it shows no figure. Red team Z1 now also covers about 140 real older pages.

The same independent review led to these wording fixes:
- the rate computed from published counts is no longer called "publié";
- a report figure now carries its counts;
- labels replace raw specialty codes.

**Red team** `scripts/redteam_tauxprofil.py` (Z1-Z6; `tests/test_tauxprofil.py`):
- Z1: the page's figure equals the one re-derived in Python from the modules' twins (`rapports.pick`, `semblables.estimate`,
  `doublettes.estimate`, `voies.pick_voie`).
  - Cases: about 420 real formation × profile pairs, plus crafted report and similar-formation payloads, so every branch is
    tested on the synthetic warehouse too.
- Z2: the card's headline or its "votre bac" row equals the tile, and a published tile never has an estimate beside it.
- Z3: the tile and the summary, run in Node: escaping, sources and counts in words, the "peu de candidats" flag, tile counts and
  order.
- Z4: wiring, layouts, feature and docs.
- Z5: the browser check on real formations (`--real`).
- Z6: 15 mutants, run only on a passing baseline.

The ux (X12, X16) and reorientation (E6) harnesses now load the R2 helpers.

## Sprint R3: advanced filters shared by the search and the map (owner's choices, 2026-11-12)

The search and the map now offer the same filters, cut with the same limits (`suptracker/filtres.py`, served in `/api/meta` as
`filtres` and read by the page):

| Group | Values | What it reads |
| --- | --- | --- |
| Zone pour votre profil | sécurité, cible, ambitieux, autres | the zone of "Où je me situe" for the profile sent with the search (search only; the map already had its zones) |
| Type d'établissement | public, privé sous contrat, privé payant | `contrat_etab` (Plan B's rule for the paid ones) |
| Capacité | < 20, 20-49, 50-99, ≥ 100 places | the published capacity of the formation's own campaign |
| Phase complémentaire | admitted candidates / none | admits in the complementary phase of its own campaign: admits of a past campaign, never places this year (the page says so) |
| Taux d'accès officiel | < 30 %, 30-59 %, 60-89 %, ≥ 90 % | the official rate; a formation without a published rate is in no band |

Each band includes its lower limit and excludes its upper one.

**The data (2025, checked first).** The capacity is published on every row: P25 18 places, median 30, P75 50, P90 110. 6,186 of
14,252 formations admitted candidates in the complementary phase, and 8,009 received complementary vœux. There are 11,108
public formations, 1,938 private under contract and 1,206 fee-charging private ones. 15 rows carry no official rate.

**How the search filters.** `/api/search?avance=true` takes the whole result set of the search, with its own option filters,
and adds the formations' own campaign rows: capacity, complementary admits and status. When a profile is sent (bac, specialties,
mention), it also reads the zones of the latest campaign's results: `journey.stage2` on each formation's own type, with `only` its
codes. These are the zones of "Où je me situe", Mes vœux and the map. A result of an older campaign never takes the zone of
the latest one, even with the same code (red-team finding).

The search's own filters (type, académie, selectivity) are applied on the server too. Every group, the search's own included,
is counted with the other groups applied, so a count is exactly what a click returns. Options stay conjunctive.

The order is the search's relevance order: nothing is sorted by a figure.

Every result set gets its zones: the cost grows with the number of types, from about 1 s for "informatique" (800 results,
23 types) to 1.5–2.5 s for the broadest queries ("lycee", 7,206 results; "universite"). The answers sit in a small in-process
cache, keyed by warehouse, campaign, profile, type and codes, so paging and ticking reuse them.

The independent review found that a first 6,000-result limit made a zone filter silently empty on broad searches, and that the
limit was counted before the student's own filters. The limit is gone. The review's other fixes:
- outside terminale, the zone group says nothing (no invitation to create a profile);
- a zone chip left in a shared link without a profile is dropped.

**Privacy (owner's choice "Profil envoyé, rien gardé").**
- The profile is sent only from a terminale profile with two distinct specialties.
- It is used for this answer only. `/api/search` stays no-store.
- The audience event keeps the query, the total and the refined flag, never the profile or the zone.
- A zone filter without a profile, an unknown key, two identical specialties or an unknown series are refused (422).

**The page.** The groups sit under "Filtrer", with their counts. Every ticked option is a removable chip. Each result shows its
zone pill, its capacity and an "admis en phase complémentaire 2025" badge. Without a profile, the zone group links to "Mon
profil".

**The map.** The map gets the capacity, complementary-phase and official-rate groups, with the same bands, from the payload's
`capa_fin` and `acc_pc`. Apprenticeship offers have no figure and fall in no band.

**Red team** `scripts/redteam_filtres.py` (FI1-FI9; `tests/test_filtres.py`):
- FI1: the bands, Python and page alike.
- FI2: the filtered search re-derived independently on 60 searches (6 queries × 10 filter combinations, 3 profiles): the
  kept list, the total and every facet. The zones come from the FULL type, not the `only=` call.
- FI3: privacy and validation.
- FI4: the order.
- FI5: the page, run in Node.
- FI6: the map payload and the map's filter against a Python filter.
- FI7: the browser check.
- FI8: 15 mutants, on a passing baseline.
- FI9: wording and docs.

## Sprint R4: result cards, zone shapes, charts and colour tokens (owner's go, 2026-11-12)

The last step of the redesign changes no figure. It changes how the figures are drawn. Some ideas come from the design
references in `docs/design-references/`: a single data colour (WattVision), a coloured left edge on cards (Flip7), restraint and
tabular figures (Genesis). The rest comes from the brief in `docs/brief-ui/`: a palette coded twice, with shapes and labels, for
colour-blind readers. The brief's scores and simulated ranks stay out: SupCompass never shows a chance.

**Zones: a colour, a shape and a name, everywhere.**
- One helper, `zoneShape`, draws every zone with the map's shapes: rond = sécurité, carré = cible, triangle = ambitieux, and an
  empty ring for every other reading.
- It draws the map markers, the "Où je me situe" chart, the pills (`zonePillHtml`), the badges (`zoneBadge`), the result cards,
  Plan B, the shared list and the summary tile.
- A zone is never drawn by hand any more. The map card and list used to show a coloured word, and Mes vœux and Plan B a coloured
  border: they now use the same badge.
- Hors-profil, indéterminé and non ouvert have their own readable token, `--zone-autre`. Before, `indéterminé` was drawn in the
  border colour and could not be read on a white card.

**Search result cards (`resultCard`).**
- When the zones are read for the profile, the card takes its zone's token as its left edge, never the accent, and its pill.
- The figure column says what the figure is: "taux d'accès officiel".
- For a bac techno or bac pro profile, the card adds the same stage-2 row's estimated access for the series. This is the
  "Accès estimé" of Mon parcours, said as an estimation, with "peu de candidats" below 20 candidates of the series.
  `filtres.zones` carries it, read from the full type's row.
- Data check (real warehouse, three searches): 358 of the 360 zoned bac techno or pro results have an estimate, and 70 of them
  are fragile. Bac général gets no second figure here: its doublette figure needs the formation page (R2).
- Capacity has a drawn icon, and figures use tabular numbers.

**Charts: colour only where it means something.**
- Two chart colours were the zones' own (`--c1` = cible blue, `--c2` = ambitieux orange), and a third was close to sécurité
  green. The admits-by-mention bars therefore looked like zones.
- The data series now use a neutral ramp (`--c1` darkest to `--c6` lightest, biased like the page's neutrals). It is ordered for
  the mention bars and the offer timing (which was a blue ramp, the cible blue).
- On a line chart, each neutral series also has its own dash pattern, and `lineLegend` draws the same dash.
- Colour stays only for the zones, the bac routes and the accent. The national doublette line no longer borrows the bac techno
  colour.
- Every chart has an accessible name: its series and its years.
- The ⚠ emoji markers became a drawn icon or a text badge (`n<20`, `sous-vœu`), and the "Filtrer" gear became a drawn icon.

**Tokens.**
- `--zone-ambitieux` is darker in the light theme (`#b9460f`). The pill's white text read 4.41:1 on the old orange, below WCAG
  AA; it now reads 5.3:1, while staying far from the bac techno colour.
- Shadows are tokens (`--shadow-tip`, `--shadow-pop`) with a dark-theme value.

**Red team `scripts/redteam_visuel.py` (VI1-VI10), `tests/test_visuel.py`.**
- **VI1, tokens:** no colour literal in a rule or in app.js; the same tokens in the three theme blocks; no emoji as a CSS marker;
  no bac route colour on a doublette line.
- **VI2, data ramp:** neutral, ordered, at least 60 RGB apart from every zone, route and accent colour.
- **VI3, contrast:** text 4.5, pill text 4.5, zone marks 3, in every theme.
- **VI4, zone marks:** shapes, mark and name, escaping, one helper.
- **VI5, the card:** escaping, edge, official rate labelled, estimate only when given (0 % included), no chance wording.
- **VI6, the API:** each estimate re-derived from the full type's stage-2 row.
- **VI7, charts:** names, dashes, the legend's dashes, gaps, no emoji marker.
- **VI8, browser:** light, dark and phone, bac général and techno; card edge colour = pill colour, charts named.
- **VI9, docs.**
- **VI10, mutation test:** 26 mutants, all caught.
- The red teams that drew zones by hand (carte, ux, voeux, admis, filtres) now load the shared helpers.

## Sprint R5: a continuous average inside the mention (owner's choices, 2026-11-12)

The owner asked for a finer profile: six bands and a continuous reading of the student's average, with a normal curve centred on
the middle of each band. The owner chose the honest version: a continuous POSITION among the admits, shown as a range and never as
a chance. SIES publishes how many admits hold each mention, never their marks and never the candidates by mention. An admission
probability per mark therefore has no denominator and cannot be computed.

**Bands.**

| Band | Marks | Centre |
| --- | --- | --- |
| Rattrapage | 8 to 10 | (counted in sans mention) |
| Sans mention | 8 to 12 | 11 |
| Assez bien | 12 to 14 | 13 |
| Bien | 14 to 16 | 15 |
| Très bien | 16 to 18 | 17 |
| TB félicitations | 18 to 20 | 19 |

SIES counts the bac obtained at the rattrapage with "sans mention" and does not publish it apart. The sans mention band is
therefore 8-12, centred on 11 as the owner asked: a rattrapage sits at its bottom, and the position stays continuous at 10 and
never decreases with the average.

**The reading** (`journey.within`, `journey.resolve_mention`, page twins `withinBand`, `positionMoyenne`).
- share of admits below the average = (admits of the lower bands + w × admits of the student's band) / admits with a known mention;
- w is the within-band fraction under a normal curve centred on the band (σ = 1 point, truncated to the band), the reading the
  zone uses;
- the uniform spread gives the other end of the range;
- the published bounds (the band's bottom and top) frame both;
- a zone is "incertain" when the uniform hypothesis gives another zone;
- for bac général, the bounds of the mention × series table are mixed with the same w (`series_position`).

Without an average, the reading stays that of the band's top (w = 1). A regression check compared the new and old stage-2 code
without an average: 5,080 identical rows.

**Data check.** "Assez bien" alone holds a third of the néo-bachelier admits (33 %), and 35 % of the admits of a median formation.
Inside one band, the average moves the position by up to 30 points. Example, a BTS biologie médicale:
- 12.4 → 45 %, 13.0 → 59 %, 13.9 → 79 %;
- the mention alone → 80 %.

**Everywhere a zone is read.**
- "Où je me situe", Mes vœux, Compléter, Plan B, the map and the search zones all take `moyenne` (8-20) and give the same zone.
- A mention that contradicts the average, a rattrapage at 10 or more, and an average out of 8-20 are refused (422).
- An answer read for an average is never shared-cached (`cache.header(..., fine=True)`): the public routes were cacheable for a
  coarse band, while an average to the tenth is a fine profile.
- The repère keeps only the access-rate range with an average: its share ranges and zone stability were measured per band.
- A shared list never carries the average.

**Bug fixed on the way.** The map asked for zones only for the codes `sm/ab/b/tb`, while the profile stores `sansmention`, so a
sans-mention student never saw zones on the map. The page now sends the profile's own codes, and the API still reads the old `sm`
as "sans mention".

**Pages.**
- "Mon profil" lists the six bands with their marks and takes an optional average ("13,4" or "13.4", rounded to the tenth). The
  average sets the band (the list follows it). An invalid average is said, never saved or silently dropped.
- The tables say "admis sous votre moyenne (estimation)" and show the range of the two hypotheses.
- The formation page has a new folded card, "Votre moyenne parmi les admis". Its curve runs from 8 to 20: the published points sit
  at the band edges, with the two hypotheses between them and the student's average marked. It states:
  - the range, said as an estimation;
  - the published bounds;
  - the rattrapage note;
  - a small cohort flagged;
  - all bacs (mentions are not published by series);
  - "des repères, pas des chances".
- New method text "moyenne" and glossary entry. The "mention" entry now lists the six bands.

**Red team `scripts/redteam_moyenne.py` (MO1-MO9), `tests/test_moyenne.py`.**
- MO1, the model: the within-band fraction re-derived by integrating the truncated normal density, every edge, resolve_mention.
- MO2, the Node twins on real mention counts (erf within 1e-6).
- MO3, stage 2 re-derived from independent counts on 12,128 rows: continuity at 6,064 band edges, never decreasing, the band's top
  without an average, uncertain when the hypotheses disagree (with the page's own bac-général reading).
- MO4, the API: same zone on every route, 422 cases, no-store, the old `sm`.
- MO5, the page in Node.
- MO6, wiring.
- MO7, browser.
- MO8, mutation test: 17 mutants, all caught.
- MO9, the method text and glossary.

**Independent review.** It found four defects, all fixed, each with a red-team check.
- Mes vœux printed "mention undefined" for TBF and rattrapage profiles.
- Plan B named the raw stored mention.
- The success-beyond-licence card read the "assez bien" row for TBF (TBF now reads the "très bien" row) and for the rattrapage
  (now the published "passable, 2nd groupe" row).
- A rattrapage profile without an average was told "sous votre moyenne". The routes now echo the student's OWN average, and the
  scatter labels follow the stored profile.

A known limit, said rather than hidden: at exactly 8/20, both hypotheses put the student at the very bottom of "sans mention", so
almost every formation reads "hors profil". The position is a model, and the card shows the published bounds beside it.

## Sprint R6: the average stays in the browser (owner, 2026-11-12)

Since R5, the student's average ("13,4") travelled with every request that reads a zone. Every such answer was then computed on
demand instead of being served by Vercel's cache, and a fine personal figure left the phone. R6 keeps the average in the browser,
as the lycée and the map position already were.

**How.**
- The page sends the mention BAND only (`mentionParams`; a rattrapage is sent as "sans mention", the band SIES publishes it in).
  The answers are the same for every student of a band, so they stay shared-cached.
- Every stage-2 row carries what the reading needs (`lec`): admits with a known mention, admits up to the band, admits in the band,
  and per campaign the series bounds of the band and of the band below; plus the two rules that do not depend on the average
  (closed to the series, fragile series rate). Each trend point carries its own three counts.
- The page reads the zone itself (`relire`, `lire`): the twin of `journey.stage2` with an average (`zone_reading`,
  `series_position`, `wilson`, `classify_zone`, the uniform reading that makes a zone uncertain). `erf` is now a series accurate to
  ~1e-15 (it was Abramowitz-Stegun, 1.5e-7), so the twin agrees with Python's `math.erf`.
- Plan B and Compléter ask with `pool=true`: the server returns every candidate the average-independent rules keep (same filière,
  not the target or a listed vœu, not the same concours pool, not closed, not fragile, not a small cohort, a published rate), with
  its ingredients, exact distance and tie-break. The page applies the zone rules, the paid filter, the order and the caps
  (`planBLocal`, `completerLocal`). Mes vœux re-reads its rows and its list reading (`voeuxLocal`, twin `readList`); the map asks
  `lecture=true` (`carteZonesLocal`).
- Without an average, the pages use the answers as before (no pool, no re-reading).
- The one exception, said in the method text: the search's zone filter is applied by the server on every result, so the search
  still sends the average. The search is never cached and never records the profile.
- The server still reads `moyenne` (unchanged, still never cached). It is the ORACLE the red team compares every twin with.

**Red team `scripts/redteam_lecture.py` (LE1-LE9), `tests/test_lecture.py`.**
- LE1: every row's ingredients re-derived from an independent SQL read of the lineage; invariants.
- LE2: stage 2, the page's reading of the band answer = the server's reading with the average, for 5 types, 3 series and every
  band (edges, rattrapage with and without an average): 15,552 rows, zones and "incertain" exactly, shares, intervals, series
  bounds, positions and trends within 1e-9.
- LE3: Plan B, 126 answers (ok, aucune, déjà accessible), every alternative in order.
- LE4: Mes vœux, 104 lists × averages, every row and the list reading; `readList` = `read_list` on 200 random lists.
- LE5: Compléter asks only when the page's own reading finds no sure safety, then shows the server's suggestions in order.
- LE6: the map (86,128 zones), the cache policy of each answer, the pool answers.
- LE7: wiring and wording (no query carries the average except the search; every zone goes through the twin).
- LE8: browser, no request carrying the average.
- LE9: mutation test.

## Sprint R7: "Construire ma liste", the site in five steps (owner, 2026-11-12)

Everything a student needs already existed. What was missing was the thread for a 17-year-old who lands on the site without
knowing where to start. `#/guide` puts the five steps in one place, in any order the student likes:

| Step | Done when | Its links |
| --- | --- | --- |
| 1. Mon profil | the profile can be read: outside terminale, or a bac, a mention or an average and, for bac général, two different specialties | Mon profil |
| 2. Explorer les formations | a formation page was opened in this browser, or the list has a vœu | search, map, jobs |
| 3. Ajouter des vœux | the list has a vœu (n of 10 said; Parcoursup vœux are not ranked) | Mes vœux |
| 4. Garder au moins un vœu de sécurité sûr | the list's reading counts a sure safety; "sans objet" outside terminale (no zone is published), with a link to "Je me réoriente" | Mes vœux (Compléter ma liste) |
| 5. Partager ma liste | the link was copied or the list printed in this browser | Mes vœux (share card) |

- **Local only.** The guide reads the stored profile, the list and two flags set in this browser (`guideVu` by a formation page,
  `guidePartage` by the share card). It records no event of its own and sends nothing to follow the progress; the page view is
  counted like any other page (closed route list).
- **One reading.** Step 4 reads the list with the profile bar's own query (`vxQuery`) and the R6 twin (`voeuxLocal`), so the
  average stays in the browser. It reuses the bar's reading when it has one. There is no request without a profile, outside
  terminale, or with an empty list. A failed reading is said, and a late answer never draws over another page.
- **Wording.** A sure safety is described with its fixed rule (access rate at least 70 %, at least half of the admits with the
  student's mention or lower, no uncertainty); "des repères, pas des chances d'admission"; vouvoiement.
- **Entry points.** A card on the home page (before the four doors, with the steps done), a link in Mes vœux, the route `#/guide`
  in the "Mes vœux" tab.

**Red team `scripts/redteam_guide.py` (GU1-GU8), `tests/test_guide.py`.**
- GU1: `guideState` against the rules written again in Python, on 3,000 random states (every status seen).
- GU2: the page drawn for 302 states (links, progress ARIA value, the next step highlighted and linked, escaping, wording, the
  drawn check mark).
- GU3: the reading with a fake API (no request in three cases, the bar's query, reuse, failure, race, escaping, and a row the
  server reads "cible" that the browser reads as a sure safety with the average).
- GU4: the flags stay in the browser; GU5: entry points and docs; GU6: a student walks the five steps on a phone (browser);
  GU7: outside terminale; GU8: mutation test, 28/28.

## Sprint R8: accessibility audit, WCAG 2.1 AA (owner, 2026-11-12)

**Audit.** axe-core 4.10 (WCAG 2.1 A and AA rules, plus best practices) on the 21 pages, each on a phone and a wide screen, in light
and dark (84 page-modes), followed by checks no scanner does: keyboard paths, focus after a navigation, page titles, reflow at
320 px, the contrast of every colour token, tooltips. Before the fixes:

| Finding | WCAG | Fix |
| --- | --- | --- |
| `<main>` was a live region: a screen reader read whole pages aloud at every change | 4.1.3 | `<main>` is focusable and silent; one polite status line says "Page : <titre>" |
| every page had the same tab title | 2.4.2 | the title is the page's h1, "<h1> — SupCompass" |
| after a click the focus stayed on a link that no longer existed | 2.4.3 | the focus moves to the new page's heading (never on the first load); a page left before its answer came never takes the focus back (Codex) |
| no way to skip the menus | 2.4.1 | a skip link, the first Tab stop |
| five pages had no h1 (search, comparator, specialties, quality, glossary); a heading skipped a level | 1.3.1 | one h1 per page, headings in order |
| scrolling tables could not be reached with the keyboard | 2.1.1 | each is a focusable region with its own name |
| tooltips: their text never reached screen readers, and Escape did not hide them | 1.3.1, 1.4.13 | the text is the button's name; Escape hides it until the pointer or focus leaves |
| form fields' edges at 1.3:1 | 1.4.11 | `--line-input` at 3.6:1 (light) and 3.6:1 (dark) |
| the specialties page and the evolution charts overflowed a 320 px screen | 1.4.10 | the select and the chart grid shrink |
| the lycée list had no name; empty table headers; the map's attribution link by colour alone | 4.1.2, 1.3.1, 1.4.1 | named list, "Actions" / "Indicateur" headers for screen readers, underlined link |
| an unreadable average was said but not tied to its field | 3.3.1 | `aria-invalid` on the field, removed once valid |

After the fixes: 0 axe violations on the 84 page-modes, 0 JS errors.

**Red team `scripts/redteam_a11y.py` (A1-A6), `tests/test_a11y.py`.**
- A1, the shell: language, skip link first, `<main>` focusable and silent, one status line, search and menu landmarks.
- A2, the page code: tooltips, title + status + focus after every navigation (errors included), reachable and uniquely named
  tables, named lycée list, `aria-invalid`, no empty header.
- A3, contrast with the WCAG formulas on every token, light and dark: text and links >= 4.5:1; field edges, focus ring and zone
  marks >= 3:1.
- A4, browser (`--browser` / `--real`; axe-core when installed, `AXE_CORE_JS` or a global npm install): every page, one h1 and
  its title, no horizontal scroll at 320 px, the skip link, the focus after a click, the menu with the keyboard, Escape on a
  tooltip, the tables.
- A5, mutation test: 24/24. A6, docs.

Still to test by hand with a real screen reader (VoiceOver, NVDA, TalkBack): the map (Leaflet's markers; the list beside it
carries the same information), and the reading order of long tables on a phone.

