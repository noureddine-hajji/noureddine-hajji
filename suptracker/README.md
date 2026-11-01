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
  - The IUT de Nîmes and the Polynesia antenna carry the id of a university with no BUT row. They stay unlinked rather than guessed.
  - On real data, the B1 name rules and the id agree on all 116 formations where both apply.
- **BUT → specialty.** Every Parcoursup BUT programme (36 labels) maps to one of the 24 SIES specialties. The "parcours …" suffix is dropped, and there are 3 explicit aliases, among them "Science des données", the 2024 name of STID.
- **Licence → master.** The master card uses exactly the B1 link (university, discipline).

**Reliability.**
- **Grades.** Every university figure is an `evidence.maillon` with a new granularity, "l'université, toutes spécialités". The cohorts (2021) are more than 3 years old, so they are graded B at best.
- **National rows.** National rows are references and carry no grade.
- **No multiplication.** No figure is multiplied by another.

**Red team (`scripts/redteam_poursuite.py`, run in CI by `tests/test_poursuite.py`).** On the real data, 10/10 checks pass and 16/16 mutants are caught.
- **P1.** Independent re-read of every cell: 6,637 cells, 0 differ. Masked cells are NULL, never 0. The committed warehouse equals a fresh build.
- **P2.** Every block maps to one B1 university, with no collision inside a table.
- **P3.** Identities:
  - the universities add up to "Inscriptions principales", and disciplines add up to their block;
  - rates equal counts, and VA = observed − simulated;
  - the M1 outcomes partition the entrants (Grenoble listed);
  - BUT graduates equal the BUT successes;
  - the national tables agree with each other.
- **P4.** The masking rule holds at the measured thresholds.
- **P5.** BUT links: truth table of the hard sites, id vs name rules, 100 % of programmes mapped to a specialty, and a specialty truth table.
- **P6.** The licence → master link is B1's for all 3,202 linked licences.
- **P7.** The API blocks match the warehouse, with grades by the fixed rules and the out-of-scope cases handled.
- **P8.** National margins: doublettes use the journey's specialty codes, and the chain is ordered.
- **P9.** The page escapes every stored string, keeps the wording card by card, never multiplies rates, and keeps the profile in the browser with its values validated.
- **P10, mutation test.**
  - Data mutants: "Etudiants" as the reference, masked as 0, an alias collision, discipline rows not grouped by block, a loose IUT rule, a wrong specialty alias, the master block off B1's discipline.
  - UI mutants: escaping (3), wording (2), a multiplied chain, the profile sent to the server, the stored series trusted, the card not wired.

**UI check (Playwright):** light, dark and mobile, including an unlinked IUT. 0 JS errors, no horizontal scroll.

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
