# SupCompass — project memory for Claude Code

The site's name is **SupCompass** (renamed from SupTracker on 2026-11-07, owner's choice: "Sup" of Parcoursup + compass).
Only the visible brand changed: the package, folder, workflows and env vars keep the technical name `suptracker`
(renaming them would break the owner's Vercel and GitHub settings). Never "Parcoursup" alone as the site's name.

Student-facing web app over the official SIES / Parcoursup open data 2022–2025: search, formation
pages, comparator, "Mon parcours" (positioning by bac series, specialties and mention), Plan B,
audience dashboard. The owner (Noureddine) speaks French: **answer him in French, simply, with
concrete click-by-click steps when Vercel or GitHub settings are involved.** Code, commits, PRs in English.

## Layout (everything under `suptracker/`)
- `suptracker/` package
  - **Pipeline:** `ingest.py` downloads SIES ODS parquet, `harmonize.py` builds `core.formation_year`,
    `core.cartographie` and the specialty tables, `crosswalk.py` builds the lineages, `build.py`
    assembles the warehouse.
  - **Schema:** `schema.py` (VOEUX_FIELDS, aliases, labels; add a field here to ingest it).
  - **Serving and features:** `api.py` (FastAPI + METHODOLOGY texts), `search.py` (search engine),
    `journey.py` ("Mon parcours"), `planb.py`, `analytics.py`, `success.py` (B1).
  - **Foundation (sprint 3):** `referentiel.py` (Paysage ids, register, successions), `evidence.py`
    (maillon + A/B/C reliability), `sources.py` (source register), `glossary.py` (A5).
  - **Lycée (sprint 4):** `lycee.py` (IPS + IVAL from the Education ministry portal, `config.Dataset.base`).
  - **Repère (sprint 5):** `calibration.py` (next-campaign ranges, hold-out 2025, zone stability).
  - **Beyond licence (sprint 6):** `poursuite.py` (BUT per university, master per university × discipline, national margins).
  - **Gateways (sprint 7):** `passerelles.py` (reorientation detail after L1, MonMaster per university × discipline).
  - **Insertion (sprint 8):** `insertion.py` (Inserjeunes BTS per establishment, InserSup per diploma).
  - **Céreq (sprint 8 follow-up):** `cereq.py` (training-job match by highest diploma, national; owner-uploaded workbook).
  - **Onisep (sprint 8 follow-up):** `onisep.py` (jobs a diploma leads to, national, by title; owner-uploaded Idéo XML).
  - **Scale (sprint 10):** `cache.py` (one HTTP cache policy per route), `journey.public_stage2` (lighter answers), `scripts/monitor.py`.
  - **Du métier aux formations (sprint 12):** `metiers.py` (job catalogue searched in the browser, job page = the jobs card read backwards).
  - **Job reference (sprint 13):** `nomenclatures.py` (ROME → FAP-2021 / FAP-2009 → ISCO-08, official Dares and Insee tables, `core.nomen_*`).
  - **Employment to 2030 (sprint 14):** `emploi2030.py` (Métiers 2030 per FAP-87 family, scenario ranges, job page); `bmo.py` (BMO 2026 hiring intentions, short-term context).
  - **AI and tasks (sprint 15):** `ia_exposition.py` (ILO 2025 generative-AI exposure per ISCO-08 unit group, France Travail "transition numérique" tag, IMF human complementarity θ rebuilt from O*NET, job page).
  - **Licence → master (sprint 16):** `licence_master.py` (each master of the licence's university side by side: MonMaster, InserSup, Onisep jobs with sprints 13-15 ranges and counts; `core.metier_axes` precomputed per job).
  - **Indexable pages (sprint 17):** `seo.py` (`/formation/<code>`, `/metier/<id>`, sitemap, robots; the app boots on these paths).
  - **Doublettes:** `doublettes.py` (proposal rates per doublette for a group, national; per bac route for a formation; `mart.spe_group`, `mart.spe_break`).
  - **Mes vœux (sprint 11):** `voeux.py` (the student's list of up to 10 vœux read for the current profile, `#/voeux`).
  - **Prévision n+1:** `prevision.py` (calibrated next-campaign ranges of every indicator with a history, formation page).
  - **Comprendre l'appel / Vraie sélectivité:** `appel.py` (how far each list was called, offer timing per type), `selectivite.py` (access rate x mention matrix).
  - **Formations semblables:** `semblables.py` (pooled doublettes and jury counts from the verified reports of the same diploma and mention).
  - **Qui sont les admis:** `admis.py` (néo-bacheliers vs other admits: formation page bar, list label).
  - **Bac techno / pro row (sprint 20):** `voies.py` (report rows of bac techno and pro keyed to the student's series or specialty).
  - **Je me réoriente (sprint 21):** `reorientation.py` (candidates outside terminale from published counts, estimated access, `#/reorientation`).
  - **Accompaniment (sprint 22):** `calendrier.py` (official Parcoursup calendar read from the PDFs fetched by `suptracker-calendrier`, .ics);
    `#/accompagner`, `#/premiere`, `#/liste` (shared list) in `app.js`.
  - **Plain language (sprint Q4):** `aide.py` (the help page "Se faire aider", served like the legal.py pages).
  - **Front-end:** `static/` with `app.js` (vanilla SPA, hash router), `stats.js` (the dashboard),
    `style.css` and `index.html`.
- `scripts/`
  - `verify_ground_truth.py --strict` (SIES identities) and `verify_persona.py --strict`;
  - search evaluation: `eval_search.py`, `holdout*_search.py`;
  - `redteam_*.py`, one per feature, each runnable with `--real`.
- `tests/`
  - `synthetic.py` (realistic fixture that mirrors SIES quirks), one `test_*.py` per feature;
  - `test_release.py` fails if a shipped feature loses its front-end entry point.
- **Data:** `data/suptracker.duckdb` is built and committed **by the GitHub Action `suptracker-data`**
  (the SIES host is blocked in this sandbox). After changing ingestion, push, then trigger the
  workflow on the branch (`workflow_dispatch`, ref = branch), then `git pull` the "Refresh SIES
  warehouse" commit before working on real data. DuckDB is pinned to `==2.0.0`.

## Deploy
- **Vercel** (FastAPI preset, root `suptracker`, entrypoint `suptracker.api:app`, slim `requirements.txt`).
  The production branch must be `main`.
- **`.vercelignore` is read from the REPOSITORY root:** a pattern with an inner slash must start with `**/` (`data/sources/`
  alone matched nothing and overflowed the 225 MB function limit); red team M7 simulates Vercel's reading.
- **Live version check:** the footer and `GET /api/version` show the commit. Assets carry a
  `?v=<content hash>`.
- **Analytics** use Upstash Redis (`KV_REST_API_URL` / `KV_REST_API_TOKEN`) plus
  `SUPTRACKER_STATS_TOKEN` and `SUPTRACKER_ANALYTICS_SALT`, all set by the owner on Vercel.

## Workflow (how every feature has been shipped)
1. **Branch.** Work on `claude/vigilant-shannon-dqq1iw`; after each merge, `git merge --ff-only origin/main`.
2. **Check the data first.** Before coding, check what SIES really publishes on real data: units,
   denominators, sums, coverage, edge rows. Many features changed design because of this.
3. **Implement**, then write `scripts/redteam_<feature>.py`:
   - independent re-derivation, invariants, hostile inputs, UI escaping, wording;
   - a `--real` mode;
   - a **mutation test**: seed bugs and check each is caught. Strengthen the red team until it is.
4. **Test and look.**
   - `tests/test_<feature>.py` runs the red team on the synthetic fixture and on the real warehouse
     (skip if absent). `python -m pytest -q -n auto --dist loadfile` must pass (pytest-xdist), then the timed tests
     (`tests/test_analytics.py tests/test_planb.py tests/test_search.py`) alone.
   - Check the UI with Playwright (preinstalled; `require('playwright')`): light, dark and mobile,
     0 JS errors, no horizontal scroll. Look at the screenshots.
5. **Ship.**
   - Write a README section for the feature.
   - Commit; the message ends with the Co-Authored-By / Claude-Session lines.
   - Push and open a **draft PR**, then subscribe to its activity.
   - When CI is green, mark it ready; this triggers the Codex review. Fix every valid finding: add a
     red-team check that catches it, reply on the thread with the commit, then resolve it.

## Statistical and product rules (do not regress)
- **Official indicators are never recomputed** (`taux_acces_ens`, `pct_*`). Derived numbers are
  labelled as such ("estimation").
- **Never a probability of admission.** Show "parts d'admis, pas des chances".
- **Units.** Per-formation candidate counts summed across formations are vœux, not people; count
  people with admits.
- **`part_terminale_*` is a COMPOSITION.** Gen + tech + pro = 100 % on 99 % of rows; it is NOT an
  access rate.
- **Offer timing.** `pct_acc_debutpp ≤ datebac ≤ finpp` are cumulative shares of `acc_tot`.
  Zero-admit rows carry 0 % shares: suppress them.
- **Mentions by series are not published.** Only `acc_{bg,bt,bp}_mention` (any mention) exists.
  - `journey.series_cdf_bounds` gives sharp partial-identification bounds, computed **per
    campaign then summed**.
  - A campaign is used only if both margin halves agree.
  - `pct_bg_mention` is over `acc_neobac`.
- **No series access rate exists.**
  - The estimated series access is `taux_acces_ens × (series proposal rate / all proposal rate)`,
    capped at 100. DuckDB `least(100, NULL) = 100`: guard NULLs.
  - Fewer than 20 series candidates means zone "indéterminé".
  - A low share means "rare", never "closed", for bac techno and pro.
- **Calling groups.** All 23 real `lib_grp` labels × 3 series are tested ("sauf … et …", "STI2D",
  "Voie d'accès générale" = ordinary route, not bac général).
- **Cartographie offer attributes.**
  - `amg` is distance teaching or sport/art arrangements, **not disability**.
  - Apprenticeship is nearly absent from SIES stats after 2022, so search has no filter (note). The map lists the cartographie's
    apprenticeship offers apart, with no figure (see Carte).
- **Plan B.**
  - Same `fil_lib_voe_acc`, a strictly better zone or +15 points; no fragile or closed readings;
    no same concours pool (`same_pool`).
  - At most 2 per establishment; académie, then distance.
  - Fee-charging private institutions ("Privé enseignement supérieur" / "hors contrat") only on
    request, flagged.
- **B1 success in licence.**
  - Figures are per university × broad discipline (never per formation), and the page says so.
  - The national reference is the "Inscriptions principales" row, never "Etudiants".
  - Universities are linked by **Paysage id** first (`success.SIES_PAYSAGE`); the name rules (one explicit
    rule per university, an ambiguous site stays unlinked) are only the fallback for formations without an
    id, graded B, and an independent cross-check in the red team.
  - Masked cells (`ns`, `nd`, `.`) are NULL, never 0.
  - The ministry site rejects automated downloads: the owner commits the workbook.
- **Foundation (sprint 3).**
  - Link sources by **Paysage id** (`ref.formation_etablissement.id_resolu`), never by name when an id exists.
    The 2025 SIES export has EMPTY ids: they come from the cartographie, then the previous campaign.
  - Successions are data-derived (transition or UAI vote, ≥ 80 % and ≥ 5 formations); a UAI shared by
    two establishments never votes.
  - Every journey figure is a `evidence.maillon` with a rule-based grade; the chain is never multiplied.
  - Every dataset is in `sources.py` (red team F9 fails otherwise).
- **Lycée profile (sprint 4).**
  - The lycée is CONTEXT only: no open data crosses admissions with the lycée of origin, so it never
    changes a positioning. The one published lycée effect is `pct_etab_orig` (formation in the lycée).
  - IPS references are per lycée type × sector; IVAL's académie label is truncated: use the IPS one.
  - Privacy: `/api/lycees` takes no parameter and is searched in the browser; the lycée is never sent.
- **Repère (sprint 5).**
  - Never a probability: only next-campaign RANGES of published indicators, with the hold-out coverage
    printed as measured (76.6 % / 76.5 % for a nominal 80 %), never hard-coded.
  - The method is fixed before the hold-out: predictor chosen on 2024, ranges from the 2023-2024 errors.
  - Zone stability is shown for bac général only. It is measured with the zone the page shows
    (`calibration.zone_of`, which calls `journey.zone_reading`, also used by stage 2): never the all-series reading.
- **Success beyond licence (sprint 6).**
  - BUT figures are per UNIVERSITY (no IUT, no specialty); specialty, series and mention rates are national margins,
    never crossed. Master figures are per university × B1 discipline and cover every M1 entrant, not this licence's graduates.
  - The reference is "Inscriptions principales" (BUT, master). Masked below 100 (BUT) and 50 (master) entrants.
  - Workbooks are recognised by content (`poursuite.detect`); every SIES spelling maps to a B1 name via `NAME_ALIASES`.
  - IUT links: `BUT_SITE_OVERRIDES` (IUT de Nîmes → Montpellier, owner-confirmed; only over an id with no BUT row), then
    the Paysage id, then `BUT_NAME_RULES` (IUT de Toulouse → Toulouse 3); the Polynesia antenna stays unlinked.
  - The student's profile picks national rows in the browser: it is never sent.
  - Red team P9: every SIES spelling shares a distinctive word and its numbers with its university (explicit exceptions with a reason);
    P10 re-reads the national workbooks with its own label rules (a SIES specialty code -> journey code by a word of its label).
- **Gateways (sprint 7).**
  - Reorientation rates are shares of L1 ENTRANTS; the published destinations are not exhaustive: never compute a
    remainder. Masked below 100 entrants. Link through B1's (university, discipline).
  - MonMaster (2024-2025; 2023 has another layout): applications summed over programmes are vœux, admits are people;
    never show a proposals / applications ratio. MEEF masters are kept apart; mixed droit-éco or theology get no discipline.
- **Insertion (sprint 8).**
  - Inserjeunes (BTS, lycées and CFA, "cumul 2023-2024"): continuing + employed 6 months + other = 100; employment rates are
    among the LEAVERS. A BTS links to its OWN establishment (UAI) and normalised label; options are shown apart, never averaged;
    renamed BTS get no figure. No headcount is published: no reliability grade.
  - InserSup (master, BUT, LP): employment rates among the leavers, the STABLE rate among the salaried employed (say so), `nd` = NULL, pooled classes flagged `*` (< 20 leavers), served at
    18 months, latest class per diploma. No discipline aggregate exists per university: masters are listed one by one.
    A diploma is (Paysage id, diploma, label, sector), NEVER the UAI: merged universities keep their former UAIs with old classes.
    Only the latest national class is served (closed diplomas counted, not shown); several parts that year = no figure.
    InserSup BUT labels go through `poursuite.SPECIALTY_ALIASES` (Parcoursup spellings, Science des données = STID).
  - Only a profile and the usable rows are staged (`insertion.KEEP`): the warehouse must stay under 95 MB.
- **Céreq (sprint 8 follow-up).**
  - Génération 2017, national, by group of HIGHEST diploma (not this formation's students; whoever goes on joins another
    group). `correspondance_ok` (3 and 6 years) and `competence_ok` (3 years only) are among the EMPLOYED and self-declared;
    the employment rate is among ALL leavers. Say each denominator. Never sum the published job categories.
  - The file comes from a button of the Céreq data visualisation: the owner commits it under data/sources/ (detected by content).
  - Link per filière: BTS by the NSF of the diploma (MEFSTAT11 digits 7-9, CFD digits 4-6, same title or its options,
    any establishment); licence by B1 discipline (+ master "si tu poursuis"); IFSI/EFTS health-social; schools; CPGE sci ->
    engineering, ECG/ECT -> business. BUT (absent from the 2017 cohort), PASS, literary CPGE, others: no figure.
- **Onisep jobs (sprint 8 follow-up).**
  - Idéo-Fiches formations + Idéo-Fiches métiers, committed by the owner under data/sources/ (detected by XML root). ODbL:
    credit "Source : Onisep, Idéo (licence ODbL)" on the card.
  - The list is NATIONAL and belongs to the diploma, never to the establishment; never a promise of a job.
  - Link by national title: BTS same title or all its options; BUT specialty without parcours; licence mention (never a
    licence pro); IFSI = DE infirmier; EFTS = the named DE. Other filières: no card.
  - Access flag: job minimum level vs diploma level (BTS 2, BUT/licence/IFSI/EFTS 3); unknown level = no flag.
- **Scale (sprint 10).**
  - Every route has a policy in `cache.py` (red team S1). A route that records an audience event or carries a personal list is
    NEVER shared-cached (`no-store`); only 200 answers are cached; assets are immutable only with the live `?v=` fingerprint.
  - Counts that a CDN hit would skip are sent by the page (`journey` beacon), never by a cacheable endpoint.
  - `journey.public_stage2` drops only fields the page never reads; rounding is guarded so no printed number changes
    (`toLocaleString` rounds the exact double half away from zero). Plan B and Mes vœux use the full `stage2` rows.
  - CI: push on `main` only, branches through their PR, stale runs cancelled. Three shard runners
    (`pytest -n auto --dist loadfile --shard=i/3`, files spread by `tests/durations.json`; a new test file goes in that table, with its
    measured seconds) plus a `timed` runner. Every red team that calls `time.perf_counter()` (analytics, Plan B, search) runs in the
    `timed` job only (red team S6 enforces it). The `test` job gates them all.
  - Carte C8 (mutation test, 12 min on real data) runs in `tests/test_carte_mutants_{1,2,3}.py` (`run(..., checks={"C8"}, part=)`);
    split any red team whose single real-data file grows past ~10 min the same way.
  - Synthetic warehouses come from `synthetic.cached_build` (keyed by every input, shared through a file lock); never call
    `build.build` on `make_raw` output in a new test. `tests/test_shards.py` checks each file runs in exactly one shard.
  - Monitor: `suptracker-monitor.yml` every 6 h on `vars.SUPTRACKER_URL`, `DNT: 1` + robot UA (never counted).
- **Du métier aux formations (sprint 12).**
  - The job page is the formation jobs card read backwards (same sheets, same link, same flag): red team M3 checks both ways.
  - The diploma level is the matched Onisep sheet's (`onisep.sheet_level`; 3-year BTS orthoprothésiste / podo-orthésiste are bac+3);
    the filière's usual level is only a fallback.
  - `/api/metiers` takes no parameter: the search runs in the browser (`metierMatch`, accent/case-insensitive, labels and synonyms;
    a close match is shown as such and never outranks a full one). National list, no promise, no ranking by chances.
- **Job reference (sprint 13).**
  - ROME × qualification → FAP-2021 / FAP-2009 are official Dares code-to-code tables; when the family depends on the
    qualification, every family is shown with its classes, none is picked. FAP-2009 classes are France Travail's
    (4 = highly qualified worker): never named with FAP-2021 names. The SAS program is read; the xls is the cross-check.
  - ROME → ISCO-08 goes through job TITLES (Dares titles × Insee G44, status column from the qualification class): several
    codes per ROME, each with its count of DISTINCT titles, NEVER shown as a share of jobs. Partial codes (2100) show as 21xx.
  - Codes, not figures: no grade, no percentage. Red team N3 cross-checks via PCS (Dares PCS → FAP, Insee PCS → ISCO).
  - Jobs without a usable Onisep ROME code are linked by NAME (Dares title, else France Travail appellation, only ROME codes
    the Dares tables know): the Onisep code always wins, one method per job, flagged "moins sûr" with the method's check
    (right code for n of N jobs whose Onisep code is known) measured at build, never hard-coded. Red team N8.
  - Homonym corrections are owner-confirmed only (`TITLE_LINK_OVERRIDES`: a code by analogy with its reason, or None).
- **Employment to 2030 (sprint 14).**
  - "Les métiers en 2030" annex 4 tables A/B, per FAP-2009 87-group (79 published): values as published, the
    imbalance as the RANGE of the 5 scenarios plus the reference; a fixed sign rule reads it; never a chance or a promise.
  - D0Z+D3Z and F0Z..F3Z are a CALCULATED group (domain minus published families), flagged; K0Z (craftsmen, in "Autres")
    gets no figure. Every family of the job is shown (qualification), none picked; never averaged over a diploma's jobs.
  - No figure beyond 2030: no official per-job projection exists for 2035 (a Cedefop ISCO forecast would need an upload).
- **BMO 2026 (sprint 14 follow-up).**
  - Employers' hiring INTENTIONS for one year, never offers, hires or a 2030 statement. Totals are re-summed from the basin
    cells (masked "*" = 0), so they are FLOORS ("au moins"); a share is fragile when masked cells (each up to 4) could move it
    by > 5 points. Linked through sprint 13's FAP-2021 families (228 parent). No 2025 comparison (2026 adds local committees,
    more masking). The workbook's FAP → ISCO expert table and tension classes are not used.
- **AI exposure (sprint 15).**
  - ILO 2025 (Gmyrek et al., CC BY 4.0): the PUBLISHED mean, sd and class per ISCO-08 unit group are served as they are; the red
    team re-derives the task means (known upstream inconsistency: 7126 only). The class also uses the spread: never re-cut it from the mean.
  - Reached through sprint 13's 4-digit ISCO codes only (partial 21xx codes get no score); every code shown with its titles count;
    the RANGE of the means, never an average, never a composite with sprint 14/BMO figures. A technical potential of TASKS, never
    a forecast of job losses, a risk for the student or a chance.
  - France Travail's "Transition numérique" tag per ROME sheet as a fact (Oui / Non / not assessed); never the ecological column.
  - θ (IMF complementarity, `theta_onet31_adapte`): O*NET 31.0, 11 CX elements -> 0-100, automation reversed, 6 dimensions at equal
    weight, Job Zone x 20 (4 groups, codes 2-5); always "estimation adaptée", reliability C, never the IMF 2023 score. A suppressed or
    missing element = no θ. ISCO only through official tables (O*NET 2019 -> SOC 2018 -> BLS SOC 2010 -> BLS ISCO-08, 4 digits only),
    never by matching codes; per ISCO code the RANGE over its US occupations and their count, never an average, never combined with ILO.
  - C-AIOE is NOT computed: the Felten AIOE appendix is centred-reduced (negative values); needs a validated positive scale first.

- **Licence → master (sprint 16).**
  - Masters = MonMaster mentions of the licence's university (Paysage id) in the same B1 discipline, latest session (sprint 7 link).
    Admits are people, vœux are not; never a ratio. Insertion = same university, same normalised title, latest national class,
    unique (parts = no figure); a masked rate says "taux non publié".
  - Jobs = the national Onisep "master mention X" sheet of the same title (`licence_master.key`: accents off, every other character
    incl. ’ a separator, œ→oe); only two explicit spelling rules (STAPS written out, MEEF dropped); never fuzzy; no sheet = "métiers
    non documentés"; the list belongs to the diploma, not the university.
  - Over the jobs: RANGES of ILO and θ (min/max over every code), COUNTS per 2030 class (fixed rule: all read families agree, else
    incertain); never an average or a single score. Landmarks only when the master's and the licence's ranges are disjoint.
  - Per-job axes are precomputed at build (`core.metier_axes`, from `metiers.detail`): red team L2 re-derives all of them.
- **Sources committed for later sprints.** Status `depose` (owner_upload, `sprint` and `role` required): a file in data/sources is
  registered before any code uses it; processed workbooks (composite indices, expert crosswalks) are `contrôle croisé` only.
- **Mes vœux (sprint 11).**
  - Zones come from `journey.stage2(..., only=codes)`: the same row as the full type, hence the zone of "Mon parcours" and
    Plan B (red team V1-V2). Never a frozen zone: the list is re-read for the current profile.
  - The reading only COUNTS zones with fixed rules; an uncertain safety is not sure; never a combined chance of admission.
    Parcoursup vœux are not ranked: no ordering.
  - The list lives in localStorage (codes only, validated, deduplicated, max 10); `/api/voeux` records no analytics event.
  - "Compléter ma liste" (owner, 2026-11-10): only on `aucune_securite`; Plan B's rules restricted to a SURE safety (same
    `fil_lib_voe_acc` as a listed vœu, `planb.usable`, not listed, no shared concours pool, paid only on request and flagged, 2 per
    establishment, 3 per filière, académie then distance to the nearest vœu of the filière); `/api/voeux/completer` no-store, no
    analytics. Red team V7-V9.
- **Prévision n+1 (formation page).**
  - Ranges of published indicators for the campaign after the latest, never a probability; each range is computed apart.
  - The method is the sprint-5 one: predictor chosen on 2024, ranges from 2024 errors, tested on 2025 (coverage printed as
    measured on the range SHOWN, rounded counts included, flagged "moins fiable" below 75 %); served ranges use 2024 + 2025 errors. At least 2 campaigns of history,
    only formations in the latest campaign, only on the latest campaign's page.
  - Rates: errors in points, clipped to [0, 100]. Counts: proportional errors, rounded outwards. Zero-admit campaigns'
    `pct_*` are ignored. The access rate is NOT re-forecast: it is sprint 5's `mart.forecast` range (both pages agree), served only with two
    PUBLISHED rates (sprint 5's n_hist counts campaigns, rate or not).
- **Campaign rollover (2027 readiness).** `fr-esr-parcoursup` is the LATEST campaign, it moves when SIES publishes the next one:
  every vœux file is kept only if its own `session` column is the registry year (`ingest.check_session`); a year reads its frozen
  `_<year>` id first. `parcoursup_<NEXT_YEAR>` is an optional slot: ingested and flagged ("Nouvelle campagne SIES"), never built
  until `config.YEARS` is updated by hand. The warehouse fingerprint includes `data/rapports/harvest`; the data workflow runs
  weekly and after each successful harvest on main (only when the harvest changed). The live harvest reads first the fiches with no
  report of the newest report session read. Tests: `tests/test_campaign.py`.
- **Search.**
  - The index is stored at build in `mart.search_index` (compressed JSON, never pickle; `INDEX_VERSION` = digest of `search.py`, a
    stale version is rebuilt on the spot). The first search of a serverless instance must never build it (4 s on the live site):
    after ANY change to `search.py`, run the data workflow on the branch (a test fails on a committed warehouse with another version).
  - Gold set and holdouts must stay at 100 %.
  - The tie-break is an attribute-neutral hash.
  - `clean_complement` handles establishment names containing " - ".
- **Analytics.** No IP, user agent or identifier; daily HMAC pseudonym; k = 3; DNT/GPC honoured;
  closed lists; fail-open.
  Sprint 18 (owner, 2026-11-11): three closed actions (`action`: voeu, planb, onglet + a closed tab list), counted as events and
  distinct visitors, NEVER with the formation concerned; Mes vœux has a feedback box and says what is counted. Red team R23-R26.
- **UI for 16-20 year olds (lot 1).** Phone first: bottom tab bar (since R1: Explorer, Mon profil, Mes vœux, Calendrier, Plus), the
  top menu only on wide screens; VOUVOIEMENT in every student-facing text, the owner's choice (no "tu/ton/ta/tes/toi", no tu-imperatives); no column
  name in what a student reads (method texts, glossary, labels); controls ≥ 44 px on a phone; search filters folded under
  "Filtrer" on a phone; home = four doors (sprint 21 added "Je me réoriente ou je reprends mes études"). Red team `redteam_ux.py` (X1-X8; `--browser` measures phone screens).
- **Design (lot 2, Claude design guidelines).** Accent = prune (`#8e2a6b`, dark `#e590c4`), owner-confirmed 2026-11-07. Tokens only: 5 sizes `--fs-*`, 3 radii `--r-*` (chart marks 2-4 px aside); zone
  colours are `--zone-*` tokens, never the accent; fonts self-hosted in `static/fonts/` with their OFL licence (never a font host);
  no emoji as a marker (drawn `ICONS`); `prefers-reduced-motion` honoured. Formation page = "L'essentiel" summary first (the only
  highlighted card; zone from the Plan B answer), then tabs named after student questions; job page = summary + diplomas folded in
  `<details class="dip">`. A new card goes in a tab, never above the summary. Red team X9-X13 (+ X7 page lengths).
  Sprint 19: "Y entrer" shows 5 cards and folds the others under "Plus de chiffres sur l'admission"; the summary links to the jury
  tab from the same render; two-row header. Keep a new admission card folded unless it replaces one of the five. Red team X16-X17.
- **Working pages (lot 3).** Mes vœux opens on `zoneTiles` (zone tokens, counts, never a chance); Mon parcours folds a stored
  profile under `profileLine` (escaped); long tables use `table.stack` + `tr.stack-head` and EVERY figure cell carries `data-label`
  (a stacked cell without a label is a bug); positioning shows 20 rows first; search pages are `searchPage()` (20 phone / 40 wide);
  the comparator is `table.cmp` (sticky label column). Red team X14-X15.
- **Indexable pages (sprint 17).** Page figures are the PUBLISHED ones (same as `/api/formation`), with the "pas des chances" caveat;
  every stored string escaped in HTML, attributes and JSON-LD (`json_ld` escapes `<`, `>`, `&`). Sitemap = latest campaign's
  formations + every job + the five sprint-Q1 pages + the sprint-Q4 help page; an older formation is `noindex`; a preview (`VERCEL_ENV=preview`) is never indexed; the canonical
  origin is `VERCEL_PROJECT_PRODUCTION_URL`, never the visitor's Host. robots.txt never blocks the data the pages render from
  (only search, vœux, stats); a failed load goes through `showError`, which keeps the server summary (Codex). A new public page needs a cache policy and a sitemap
  decision. Red team `redteam_seo.py` (G1-G11; its mutants are built IN MEMORY: never write source files from a test).
- **Doublettes.** The SIES specialty column "voeux" counts CANDIDATES (`n_candidats`; acceptations = formations' bac général
  admits). Doublette figures are per GROUP of formations, national, bac général only, never per establishment; techno and pro
  have only per-formation route rates (`journey.series_rate_sql`). Rare = < 20 candidates over the campaigns; the rare ones are
  pooled into "Autres doublettes", shown only in place of a rare doublette, always "estimation". Counting-break campaigns
  (`BREAK_*`: candidates > 2x the group's minimum with proposals < 1.5x, groups with >= 2 000 proposals) are left out of every
  rate, stage 1 included, and out of that group's NATIONAL denominators too (destination share, index: same campaigns as the
  numerator, red team D11). Mon parcours shows all-"insuffisant" filières only when every one is (a student's filter is honoured);
  it says "rare" only from the rows' `rare` flags. Route colours are `--voie-*` tokens, never a zone's or the accent, always with the route's name.
  Per FORMATION, the doublette figure is an ESTIMATION: the formation's published bac général proposal rate x the doublette's
  pooled ratio in its group (doublette / all bac général), capped at 100, shown with its calculation (`doublettes.estimate`,
  page twin `estimateDoublette`); never presented as a published per-establishment figure.
  Red team `redteam_doublettes.py` (D1-D11).
- **Rapports publics (each formation's own report).**
  - Source: the report PDFs archived by the Internet Archive, harvested by the `suptracker-rapports` workflow (resumable;
    push `data/rapports/request.json` to continue) into `data/rapports/harvest/`. The CDX query is a PATH prefix (the
    archive sorts query parameters).
  - A report is used ONLY when verified: the code printed in its tables, or its link's `g_ti_cod` for older reports, AND
    its confirmed candidates = SIES `nb_voe_pp` for that code and session. One per (code, session), the latest capture.
    Never `ran_grp` as the identity: the report is frozen in July.
  - Rate = en_position / confirmed, the formation's access rate broken down by doublette, computed from published counts
    and shown with them. The table covers only candidates schooled in terminale in France since 2020-2021: say so.
    "Autres doublettes" is the FORMATION's own bucket. A published figure replaces the estimate, never sits beside it.
  - Jury texts live in `data/rapport_textes.duckdb` beside the warehouse (built and committed with it; they alone pushed it over 95 MB),
    read by digest (`rapports.texte`). Jury texts are verbatim and escaped. Options (maths expertes...) are only QUOTED; never infer that an unnamed option
    does not count. The signature (a person's name) is never stored.
  - Credit: session, capture date and archived link on every card. Red team `redteam_rapports.py` (R1-R9).
  - Unread files (`--repair`, request mode "repair"): every other capture of the URL, as archived then rebuilt by qpdf
    (pikepdf); a rebuilt file is `ok_repare` only if COMPLETE (every page has text, the signature line is there), else `incomplet`
    and never used. Coverage is bounded by what the archive kept: the live fiches link the reports only during a campaign.
  - Live harvest (`scripts/rapports_live.py`, mode "live", daily schedule on main): every fiche of the latest cartographie session,
    its report link(s) (relative, `&amp;`-escaped; only parcoursup.fr hosts), each PDF once (archive digest form), rows with
    `source` "live" in the SAME harvest files, hence the SAME verification. A closed site (404 / "indisponible") writes nothing
    (no daily commit). The page credits the fiche ("lu le … sur la fiche Parcoursup"), not the archive. Red team R8.
  - Not yet cross-checked (owner's choice, 2026-11-09): a LIVE report of a session SIES has not published (session > SIES's
    latest), with the formation code printed in its tables and coherent counts (confirmed > 0, en position <= confirmed), is
    kept with `recoupe` = false and marked "pas encore recoupé avec les chiffres de <session>" on both cards and in Mes vœux.
    An archived report, a published session (match or drop), a code SIES lacks in a published session: never. Red team R9.
- **Carte (map of formations).**
  - The zones are the `journey.stage2` rows (`/api/journey/stage2`), never recomputed. With no profile, there are no zones.
  - Two levels: type of diploma, then mention (`carte.diplome_of`, fixed rules on the published labels; every formation in
    exactly one type). Filters follow the Parcoursup map (statut, internat, aménagements, sélectivité, zones), each option
    with its count among what the other groups keep. Paid private institutions: the "Privés (payants)" box is unticked by
    default (Plan B's rule). Zones: `/api/carte/zones` = journey.stage2 per own type, `only=`.
  - Apprenticeship (owner's request, 2026-11-08): the offers of the LATEST cartographie session absent from the latest SIES
    campaign (`carte.apprentissage`, own codes) are LISTED only: no zone, no rate, no paid flag, never "Mes vœux", a link to their
    Parcoursup page (only `https://dossierappel.parcoursup.fr/`). Type and mention = the vote of the SIES formations carrying the
    same cartographie labels (`label_votes`); académie by UAI, else département. A private CFA outside State contract is
    `prive_app` (free for the apprentice, Code du travail L6211-1), ticked by default; never the paid `prive`. Filter
    "Apprentissage" (hors / en). Unknown selectivity is neither sélective nor non sélective. Red team C9.
  - Merge (owner, 2026-11-09): an apprenticeship offer of the SAME establishment (UAI, SIES or cartographie) for the SAME
    cartographie type and mention as an initial formation of the latest SIES campaign is attached to it (`rattachee`), never listed
    apart: the formation carries both labels ("formation initiale" + "apprentissage"; filter "hors" = `initiale`, "en" =
    `apprentissage`) and lists the CFA with its Parcoursup page (map card and formation page, "Bon à savoir"). Another
    establishment of the same town is NOT merged. Red team C10.
  - The town and radius filter runs in the browser: no API call carries a position.
  - Each zone has its colour token AND its shape (rond, carré, triangle); every marker names its zone.
  - The base map is OpenStreetMap (owner's choice, 2026-11-08; the site's own drawn map was removed). Leaflet is self-hosted
    in `static/vendor/leaflet/` and loaded by the map page only (never the page shell, never a CDN); one tile URL
    (`CARTE_TILES`), the attribution, and a note that OpenStreetMap's servers see the IP address. The list works without the map.
  - The list is never sorted by chances. Red team `redteam_carte.py` (C1-C10).
- **Comprendre l'appel and Vraie sélectivité (owner, 2026-11-09).** The app PREPARES the choice of vœux: the student has no rank
  yet, so no page asks for one. Depth of call = SUM of the calling groups' last-called ranks (groups split the candidates) /
  ranked (`nb_cla_pp`), capped: at or beyond the ranked count it reads "toute la liste", never > 100 % (2022-2024: ~10 % of rows
  exceed). Per type: medians (depth; the three published timing shares, zero-admit rows out). Matrix: x = official
  `taux_acces_ens`, y = `pct_b + pct_tb + pct_tbf` (disjoint shares of the néo-bachelier admits); < 10 néo-bachelier admits or
  no rate = not placed; quadrant lines = medians of the selection; names describe a position, never a cause ("élite",
  "auto-censure" banned) or a chance. A formation the matrix cannot place (a quarter of a campaign) is NAMED under the graph
  with its reason (`selectivite.raison`) and its published counts, never only counted. Red team `redteam_appel.py` (A1-A7).
- **Formations semblables (owner, 2026-11-10).**
  - Used ONLY where the formation's own report lacks the part: no own bac général table (doublettes), no readable own texts
    (jury). Similar = same `fili` + `fil_lib_voe_acc`, same session. Verified reports only (`recoupe`); a concours report counts
    once (digest) WITHIN EACH group it covers, read from that group's own formation (Codex). FCIL and "Licence professionnelle" group unrelated formations, so they get none.
  - Doublette k: pooled over the reports that DETAIL k, with "all bac général" taken from the same reports; a formation's own
    "Autres doublettes" is never pooled. Thresholds: 3 reports and 20 candidates.
    The figure for the formation is an ESTIMATION: its bac général proposal rate x (k / all), capped at 100
    (`semblables.estimate`, page twin `estimateSemblable`). It comes before the national group estimate; a published figure is
    never beside it. The formation page, the evolution chart and Mes vœux show the same figure.
  - Jury: COUNTS of reports per field and importance (the field's highest importance in each report), per specialty and per
    option cited; never a mean or a score. The card says "pas le rapport de cette formation", the fiche Parcoursup fait foi, and
    it links the formations' own pages. Precomputed at build (`mart.semblable_dbl`, `mart.semblable_jury`).
    Red team `redteam_semblables.py` (K1-K9).
- **Bac techno and bac pro, "votre ligne" (sprint 20, owner 2026-11-11).** Report rows of bac techno are a series + its two
  specialties, of bac pro the specialty; `voies.BT_RULES` (one explicit rule per printed label) and `voies.bp_key` (format-only
  normalisation; a reformed diploma keeps its own key) give each row a `voie` key. The student's row = own key, else the formation's
  own bucket, else nothing (`pick_voie`, page twin `pickVoie`); masked table = nothing, said. Published counts only, with the
  terminale-en-France caveat; zones unchanged. The choice lives in the stored profile and is sent only to `/api/voeux` (`voie=`).
  Red team `redteam_voies.py` (W1-W8).
- **Je me réoriente ou je reprends mes études (sprint 21, owner 2026-11-11).** The group outside terminale (reorientation,
  return to studies, other routes) is PUBLISHED by SIES ("autres candidats": `nb_voe_pp_at`, `nb_voe_pc_at`, `prop_tot_at`), used as
  published, never rebuilt from the series (review); none when proposals exceed candidates (58 rows of 2023-2024). "Accès estimé hors
  terminale" = `taux_acces_ens` x (group proposal rate / all proposal rate), capped at 100 and flagged, none below 20 candidates:
  always an ESTIMATION with its counts. NO zone (no mention or series is published for them), NO Plan B, NO "Compléter ma liste",
  the old bac series is not asked. Every read of the bac, specialties or mention goes through `bacProfile()` (null outside terminale);
  an académie picked with no profile is kept apart (`reoAcademie`), never a profile without a bac or a status. Profile `statut` ("terminale" / "reorientation", validated in `vxProfile`): Mon parcours opens
  `#/reorientation`, the summary tile shows the estimate instead of the zone, Mes vœux reads `/api/reorientation/voeux` (codes only,
  no-store, no analytics), the profile bar makes no zone request. The list (latest campaign, SIES formations of a cartographie type,
  never apprenticeship offers) is sorted by the student's académie then name, never by a figure; the académie stays in the browser.
  Red team `redteam_reorientation.py` (E1-E8).
- **Accompaniment (sprint 22, owner 2026-11-11).**
  - Calendar: the OFFICIAL PDF only (parcoursup.gouv.fr, fetched by the `suptracker-calendrier` workflow into data/calendrier/, every
    version kept; `calendrier_fetch.py` refuses any other host). One fixed rule per step anchored on its wording; a date is served only
    if every version prints it identically with its TRUE weekday (the first 2027 version's heading says "samedi 10 juin 2027", a
    misprint), else "date à vérifier sur parcoursup.gouv.fr". The step names are official; "Sur SupCompass" is our own text, kept apart;
    "le calendrier officiel fait foi". `/api/calendrier` and `.ics` are shared-cached (no parameter); PDFs are kept out of the Vercel bundle.
  - Seconde / première: three specialties of première -> the three terminale doublettes; each cell is stage 1's `share` of THAT
    doublette in THAT filière (composition of admits), rows ordered by destination share, never a chance or advice.
  - Shared list: `#/liste/<codes>[/<profile>]`, everything after "#" (never sent to a server, nothing stored). Codes as the stored list
    (digits, 1-9, deduplicated, max 10); the profile ONLY if the student ticks the box, whitelisted keys (series, specialties, mention,
    route, statut), never the académie or the lycée; an invalid series or mention = no profile (never a default). Zones only with a joined
    terminale profile, the estimate outside terminale, official rates otherwise. "Ajouter à ma liste" merges up to 10 and never replaces
    the recipient's list or profile. Printing hides menus and buttons and adds the date and the "pas des chances" line.
  - The adult page (`#/accompagner`) addresses parents and teachers, still in vouvoiement. Red team `redteam_accompagnement.py` (T1-T8).
- **Journey menus and "Mon profil" (sprint R1, owner 2026-11-11).** Phone bar: Explorer, Mon profil, Mes vœux, Calendrier + Plus
  (the six reading aids + Parents et professeurs); wide screen: the same four, "Comprendre ▾" (comparator, appel, sélectivité,
  spécialités, qualité, glossaire), Parents et professeurs and the profile chip (escaped, `vxProfile`, hidden on stats and a shared
  list). Explorer = Liste | Carte | Métiers (`explorerViews`) + every formation page; Mon profil = `#/profil`, `#/parcours` (shown as
  "Où je me situe"), `#/reorientation`, `#/premiere`. `#/profil` is the ONE place the profile is edited (`profileForm`, `readForm`):
  situation first, only its fields, each with what it is used for; first save explicit, later changes saved at once; outside
  terminale the stored fields are kept and no bac field is invented; erase asks first. Profile prompts link `#/profil`. A new page
  needs a TAB_OF entry and a closed analytics route. Red team `redteam_navigation.py` (U1-U8).
- **"Pour votre profil" (sprint R2, owner 2026-11-11).** L'essentiel shows the official access rate, then ONE figure for the profile
  with its source in words (`profileRate`, `profileRateTile`): the figure the "Selon votre bac" card shows, same rules, same order:
  bac général = own report row (doublette, else its "Autres" line) when the report has a bac général table (no row = said, never an
  estimate), else similar formations, else national group, else the card's "votre bac" row; bac techno/pro = own report line
  (`pickVoie`), else the card's "votre bac" row (this formation's route proposal rate, the page's campaign, "peu de candidats"
  below 20; never Plan B's latest-campaign estimate: review). Route rates and estimates are read at the PAGE's campaign (their
trend entry; the top-level figure is the lineage's latest: Codex). Report figures carry their counts; no two distinct specialties = a
  link to Mon profil. Outside terminale the estimate keeps its own tile. Published replaces estimate, never beside it. 5 tiles with
  a terminale profile, 4 otherwise. Two DIFFERENT specialties in terminale, one artistic at most (owner, 2026-11-12): the
  form's second list never offers the first; the pair is made distinct BEFORE it is saved (`spe2Of`, a swap), a stored identical
  pair shows "Choisissez" and a warning, never another specialty it does not carry (Codex). Red team
  `redteam_tauxprofil.py` (Z1-Z6).
- **Advanced filters (sprint R3, owner 2026-11-12).** One definition (`filtres.py`, served as META.filtres): capacité (< 20, 20-49,
  50-99, ≥ 100 places, `capa_fin` of the row's campaign), phase complémentaire (`acc_pc` > 0 of the row's campaign: past ADMITS, never
  places this year, said), statut (`carte.statut_of`), taux d'accès officiel (4 bands; no rate = no band), zone (search only: the
  profile sent with `/api/search?avance=true`, zones of the LATEST campaign keyed by (code, campaign), `journey.stage2` per own type
  `only=`, every result set, in-process cache keyed by warehouse + campaign + profile + type + codes; never a partial set). Lower limit in, upper out, twin `filtreBand`. The search's own filters are applied in the same
  pass; every group counted with the others applied; the relevance order is kept (never a sort by a figure). Profile only from a
  terminale profile, never in the audience event, search no-store. The map adds the same three bands. Red team
  `redteam_filtres.py` (FI1-FI9).
- **Visual improvements (sprint R4, owner 2026-11-12).** A zone = its token + its shape + its name, through ONE helper (`zoneShape`,
  `zoneMark`, `zonePillHtml`, `zoneBadge`: rond sécurité, carré cible, triangle ambitieux, an empty ring otherwise, `--zone-autre`);
  never a zone drawn by hand, never the colour alone. Search results are `resultCard`: zone token as the left edge (never the accent),
  the OFFICIAL rate labelled, for bac techno/pro the same stage-2 row's estimated access (`filtres.zones`, said as an estimation,
  "peu de candidats" below 20), none for bac général. Colour means something only for zones, bac routes and the accent: other chart
  series use the neutral ramp `--c1..--c6` (ordered, far from every semantic colour) plus a dash (`seriesDash`, `lineLegend`); every
  chart has an accessible name; no emoji marker (drawn `ICONS`). Pill text >= 4.5:1 on every zone fill. Red team
  `redteam_visuel.py` (VI1-VI10).
- **Continuous average (sprint R5, owner 2026-11-12).** Six bands: rattrapage (8-10, counted in "sans mention" by SIES), sans mention
  (8-12, centre 11), AB 12-14 (13), B 14-16 (15), TB 16-18 (17), TBF 18-20 (19). An optional average (8-20, to the tenth) sets the band
  and places the student INSIDE it: share = (lower bands + w x the band) / known mentions, w = truncated normal (sigma 1) centred on
  the band (the zone's reading), the uniform spread the other end of the range, the band's bottom and top the published bounds; a zone
  is "incertain" when the uniform reading gives another zone; bac général bounds mixed with the same w. No average = the band's top
  (w = 1, the pre-R5 reading, unchanged). Never a chance: SIES publishes no marks and no candidates by mention. Every zone route takes
  `moyenne` (same zone everywhere); a mismatch / rattrapage >= 10 / out of range is a 422; an answer read for an average is never
  shared-cached; the repère keeps only the access-rate range then; a shared list never carries the average. The page sends the
  profile's own codes (`mentionParams`; the map's old `sm` code is read as sans mention). Twins `withinBand`, `positionMoyenne`.
  Red team `redteam_moyenne.py` (MO1-MO9).
- **The average stays in the browser (sprint R6, owner 2026-11-12).** The page sends the BAND only (`mentionParams`, rattrapage ->
  sansmention) and reads the zone itself from each row's `lec` (counts + per-campaign series bounds of the band and the band below +
  `ferme`/`fragile`): twins `lire`/`relire`/`relireVue` of stage 2 with `moyenne`, `planBLocal` / `completerLocal` over `pool=true`
  answers (every candidate the average-independent rules keep, with `dist` and `tb`), `voeuxLocal` + `readList`, `carteZonesLocal`
  (`lecture=true`). No average = the answers as served (no pool). Only the search still sends the average (its zone filter runs on
  the server; `mentionParamsSearch`, said in the method text). The server's `moyenne` reading stays the ORACLE: any change to
  stage 2, Plan B, Mes vœux or Compléter must keep its twin equal. JS `erf` is a ~1e-15 series (never Abramowitz-Stegun again).
  Red team `redteam_lecture.py` (LE1-LE9).
- **"Construire ma liste" (sprint R7, owner 2026-11-12).** `#/guide` (tab "Mes vœux"): five steps (profil, explorer, vœux, a SURE
  safety, partager), statuses from what is in this browser only (profile, list, flags `guideVu` set by `viewFormation`, `guidePartage`
  by the share card); step 4 reads the list with the profile bar's `vxQuery` + `voeuxLocal` (reused when the bar has it; no request
  without a readable profile, outside terminale or with an empty list); outside terminale step 4 is "sans objet" and links
  `#/reorientation`. No event of its own (the page view only, closed route list). Home card before the four doors, link in Mes vœux.
  Red team `redteam_guide.py` (GU1-GU8).
- **Accessibility, WCAG 2.1 AA (sprint R8, owner 2026-11-12).** `<main id="view" tabindex="-1">` is NEVER a live region; one
  `#sr-status` (role status) says "Page : <h1>"; after every navigation (`route` -> `routeView` -> `a11yAfterRoute`, errors included)
  the tab title is "<h1> — SupCompass" and the focus moves to the h1 (not on the first load); a route the student left before it ended (`routeSeq`) never moves the focus,
  announces or shows its error (Codex). Every page has exactly one h1, headings
  in order. A skip link is the first Tab stop. `.scroll` tables become focusable named regions (`a11yScrollRegions`, unique names).
  Tooltips: the text is the button's `aria-label`, Escape hides it. Form fields use `--line-input` (>= 3:1); text and links >= 4.5:1;
  no empty `<th>` (sr-only label); a field error sets `aria-invalid`. Nothing may overflow 320 px. `seo.page` fills the shell's
  `<main id="view" ...>` whatever its attributes (it raises rather than serve a page without content). Red team `redteam_a11y.py` (A1-A6;
  A4 runs axe-core when installed).
- **Searching from the map (sprint R9, owner 2026-11-12).** Wide screen: filters + map left, list middle, chosen formation right;
  several diplomas and mention groups at once (`carteSelection`, stored selection never trusted, one cacheable answer per diploma);
  choosing in the list never moves the map. Mentions grouped by FIXED rules only (`carte.groupe_of`: double licence = unordered pair,
  `DL_DISCIPLINE` with Économie = Économie et gestion, Gestion apart (owner); `FAMILY_RULES` for CUPGE/CPES; licence near-duplicates);
  French order (`sort_key`). Formations with no SIES type are read by stage 2 under `J.SANS_TYPE`, ONLY with `only` codes (map, Mes
  vœux, Plan B and Compléter with the untyped formations of the same filière, search zones). Three figures per formation: official
  rate; the doublette figure from `voeux.figures` (shared with Mes vœux, `/api/carte/chiffres` <= 40 codes, coarse profile; bac
  techno/pro lines picked by the page, the series is never sent); the average's position among the admits as a RANGE from `lec`,
  "estimation", never an access rate or a chance (none is published by mention). Red team `redteam_carterecherche.py` (CR1-CR10).
- **Map page as on Parcoursup (sprint R10, owner 2026-11-13).** Filters left, list middle, map right (sticky); a formation chosen on
  the map is pinned atop the list. Nothing ticked in a group = everything (diplomas included: one cacheable answer each; the layer is
  built ONCE per warehouse, `carte._LAYER`); list first, zones after. Card: statut + selectivity badges, official rate, rate per bac
  route (`carte.bac_lines`: the cross-checked report's en_position / confirmes over the route's lines incl. "Autres", masked = "non
  publié" even when the report prints no line (a report exists apart from its detail rows: Codex); no report = `journey.series_access_sql` estimation, starred and named, fragile < 20), the most represented line among the
  admits (route with the most SIES admits, tie = none; that route's report line with the most `acceptes`, never "Autres"; tie =
  "ex æquo"), profile figures, Mes vœux / Comparer (basket, 6) / Fiche. Sorted stats first then name (punctuation off), never by a
  figure. Red team CR11-CR13 in `redteam_carterecherche.py`.
- **Trust and compliance (sprint Q1, owner 2026-11-13).** Five pages from ONE source (`legal.py`): À propos, Contact, Mentions
  légales, Confidentialité, Accessibilité, served at `/<slug>` (indexable, sitemap, readable without JS) and to the app by
  `/api/page/<slug>` (`#/info/<slug>`); the footer links them on every page. Publisher = "M. N. HAJJI, à titre personnel", also
  publication director (owner's wording; never another name). Legal notice: host Vercel Inc. + postal address, LCEN sentence,
  every `sources.py` source "en_ligne" with its licence (generated). Privacy: every third party a page loads is named (only the
  OSM tile host today; a new external host needs its operator in the page and in red team QC2's OPERATOR table), retentions
  read from the code's constants. Accessibility: "non conforme" until an RGAA audit exists, never "partiellement/totalement
  conforme". The privacy page says every PERSONAL parameter a page sends (série, spécialités, mention band, voie, the
  académie with search/Plan B/stage 2/Mes vœux, the average with the advanced search only, the list's codes; never the lycée):
  red team QC2's PERSONAL table fails on a parameter sent and not said (Codex). Contact form (`contact.py`): closed subjects,
  10-1,000 characters, optional reply address, hidden field, 5 per visitor-day then 300 a day (the visitor's cap checked FIRST:
  a blocked visitor never consumes the global quota; one atomic Lua script in Redis), ONLY the form's fields + day stored (no IP,
  user agent or pseudonym), 12-month TTL per message, fails CLOSED (503 "non envoyé"; on Vercel without Redis the store is
  `Unavailable`, never /tmp), submitted off the event loop (`run_in_threadpool`), read/deleted on `#/stats` with the stats
  token (escaped). Tagline = `legal.TAGLINE`
  everywhere ("les vrais chiffres" is gone). Red team `redteam_conformite.py` (QC1-QC11).
- **Security (sprint Q2, owner 2026-11-13).** ONE definition (`securite.py`), one middleware (`_security` in api.py, the
  outermost): every answer, errors included, carries the CSP (scripts/fonts/data from 'self' only; images 'self', `data:` and
  the map's tile host = `securite.TILE_HOST` = app.js `CARTE_TILES`; inline style attributes allowed, NEVER inline script or
  eval; object-src/frame-ancestors 'none'), nosniff, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy (no
  camera/microphone/geolocation/payment/USB), X-Frame-Options DENY, COOP same-origin, HSTS on HTTPS only; FastAPI's /docs and
  /redoc alone get the wider CDN policy. An unhandled error is logged and answered with a plain 500 (headers, no traceback).
  HEAD = GET without a body on every route, except the search (it records an event). The contact form refuses a cross-site
  post (403: Sec-Fetch-Site cross-site, a foreign or `null` Origin) and a non-JSON body (415). A new external host a page
  loads needs the CSP, the privacy page and red teams QC2 and SE2. Never an inline `on…=` handler, `javascript:` URL or
  `eval` in the page code. Red team `redteam_securite.py` (SE1-SE10, SE4 = 1,827 hostile requests, SE9 browser CSP check).
- **Speed (sprint Q3, owner 2026-11-13).** The map reads ONE compact layer (`carte.couche`, `/api/carte/couche`): rows of values
  under key templates, DICT_KEYS strings sent once, built and gzipped ONCE per warehouse (round-trip checked at build; ETag, 304,
  Vary, public cache); `base` = what the list, the map and the filters read, `details` (`carte.DETAIL_KEYS` = app.js
  `CARTE_DETAIL_KEYS`: bacs, majo, offres_app, fiche) = what only the cards read, loaded after the list ("chargement…", cleared on
  failure). base + details = /api/carte/formations for every diploma (red team VT1, page twin `coucheDec`). The list, the map and
  the filters must never read a detail key. Zones: `journey.stage2(types=…)` reads several types in ONE query (same rows: each
  is read from its own lineage, VT2); `/api/carte/zones?diplome=*` = every diploma at once (the page when nothing is ticked).
  `journey.group_applies` and `_fold` are memoised (pure: never make them depend on mutable state). Budget on an emulated phone
  (Pixel 5, CPU x4, slow 4G): list < 9 s, zones < 15 s (VT6, `--browser`). Red team `redteam_vitesse.py` (VT1-VT8).
- **Plain language and human help (sprint Q4, owner 2026-11-13).** No "doublette" (say « paire de spécialités » / « vos deux
  spécialités »; the official word only as « on dit aussi « doublette » » and in the glossary title), no « en position de recevoir »
  (« classés assez haut pour recevoir une proposition »), no « votre ligne » (« votre bac ») in anything a student reads (page strings,
  method texts, glossary, legal.py pages, module messages). Every computed figure is labelled by `estimTag(detail, block, plain)`
  (same `ESTIM_DEF` explanation; `plain` inside a button), never a hand-written "estimation" badge; a new renderer goes in red team
  LA2's ESTIMATE_RENDERERS. Zone meanings come from `zoneHelp` (written from ZONE_RULES, never a typed threshold); pills and badges
  carry it as a title; the folded `zoneLegend()` sits on every page that shows zones. "Et maintenant ?" (`nextSteps(kind)`): links
  only, no figure, always ending with the help page. Help page `aide.py` (`/aide`, `#/info/aide`): official services and hosts only,
  numbers as the services publish them (red team's own table), never opening hours. Short texts: sentences <= 30 words,
  Kandel-Moles >= 70. Red team `redteam_langage.py` (LA1-LA8; `scripts/jstext.py` reads the page strings).
- **Home and formation page on a phone (sprint Q5, owner 2026-11-13).** The home has ONE main action, `homeCta()` in the hero
  right after the title and its sentence: "Créer mon profil" (#/profil) without a profile, "Voir où je me situe" (#/parcours) with
  one; it is the only filled (accent) control in `<main>`: other calls are outlined buttons or links (the Liste/Carte/Métiers switch
  is an outlined pill). Without a profile, the profile bar is hidden on the home only (the router passes "accueil"). On the
  formation page the main action is "Ajouter à mes vœux" (`voeuButton(cod, true)`, only when it can be added), "Comparer" is
  secondary; the tab bar is sticky (`top: 0`, opaque) and an opened tab shows its panel under it; the tabs start within two
  phone screens. The map is its own stacking context (`.leaflet-container { isolation: isolate }`): it never covers the phone's tab bar. Red team `redteam_mobile.py` (MB1-MB8; MB6 = Chromium's accessibility tree, the README gives the manual
  NVDA/VoiceOver protocol).
- **Evaluation grids of the Parcoursup fiches (owner, 2026-11-13).** Read on the LIVE fiche (`scripts/fiche_parse.py`, harvest
  `scripts/fiches_grilles.py` into data/fiches/, workflow mode "grilles", daily "quotidien" = live + grilles): global view (field
  weights, sum 100, "Au total" 100), detailed view (criterion, elements, importance 1-4 whose label and "n sur 4" agree, captions
  repeating the weight), attendus nationaux / complémentaires, conseils. Any inconsistency rejects the WHOLE fiche (reason kept);
  the build (`grilles.py`) checks again and drops a formation whole, never half shown. Published values verbatim, escaped, never
  merged, averaged or scored, never a chance; the card names the fiche's own campaign, "la fiche fait foi", "lu le …" + link.
  E-mail addresses and phone numbers are masked at reading (the fiches name people). Texts once by digest (`textes.csv.gz`
  members appended; `grille_texte` in rapport_textes.duckdb). The fingerprint takes the content files and the (code, status) of etat.csv, never its dates (Codex); data/fiches
  stays out of the Vercel bundle. Jury tab: the grid first, then the own report (or the similar formations'). Red team
  `redteam_grilles.py` (GR1-GR9; GR1 = an independent BeautifulSoup reading of the saved pages).
- **Qui sont les admis ? (owner, 2026-11-10).** `acc_neobac` (passed the bac that year) and `acc_at` (other admits: SIES does not
  split them) are PUBLISHED counts; they add up to `acc_tot` except on 21 (2022) and 15 (2023) rows. The formation page's bar is drawn
  only when they add up, and says the mention and series shares cover néo-bacheliers only. The list label "Majorité d'admis hors
  néo-bacheliers" = counts add up, >= 10 admits, `acc_at > acc_neobac` (tie = no label), one rule in `admis.py`, added to NEW dicts
  (search results are shared index documents: never modify them). Apprenticeship offers and non-situated vœux are never labelled.
  Own tokens `--adm-*`. Red team `redteam_admis.py` (H1-H6).
- **Profile bar (point 4 of the UI brief).** `#profile-bar` sits in the shell, above `<main>`, on every page except the stats.
  It shows the stored profile (escaped) and the Mes vœux zone COUNTS, read with the same query as the page (`vxQuery`).
  The alert comes only from the server's `aucune_securite` message. There is no request when the list is empty, and a prompt
  when there is no profile. Red team K7.
- **Front-end.** Never send an empty query parameter (`session=` is a 422); errors go through `apiErrorText` (a 422's detail is a
  list: never shown raw). Escape every stored string with `esc()`. Async renders must check that their
  target element is still the one on the page (navigation races).

## Status (2026-11-02)
- **Live in `main`:**
  - search 2.0;
  - analytics and the `/#/stats` dashboard;
  - A2 offer timing, A4 offer options, A3 bac-général mention bounds;
  - B4 bac techno and pro journey;
  - Plan B (formation page) and its "Voir un plan B" button in "Mon parcours";
  - B1 success in licence (formation page), from the SIES workbook in `suptracker/data/sources/`;
  - sprint 3 foundation: Paysage register and successions, reliability grades, source register, glossary;
  - sprint 4 lycée profile: IPS/IVAL context card, académie from the lycée, Maths expertes, same-lycée share,
    "C'est ton lycée ?" from the search bar;
  - sprint 5 repère: calibrated next-campaign ranges and zone stability in "Mon parcours";
  - sprint 6 success beyond licence: BUT card (per university + national margins), "après la licence : le master" card;
  - sprint 7 gateways: reorientation after L1 and the university's masters (MonMaster) on licence pages, BUT → master line;
  - sprint 8 insertion: Inserjeunes on BTS pages, InserSup on licence (masters) and BUT pages;
  - prévision n+1 on the formation page: calibrated 2026 ranges of every indicator with a history;
  - sprint 8 follow-up: Céreq and Onisep cards (Onisep: PR #27);
  - sprint 11 "Mes vœux" (branch, after PR #27);
  - release guards (versioned assets, `/api/version`).
- **Roadmap (decision-support plan, agreed with the owner):**
  - sprint 8 follow-up: Céreq card and Onisep jobs card shipped;
  - sprint 9: removed at the owner's request (2026-11-02); sprints 10-14 done; sprint 15 done (ILO, France Travail tag, θ; C-AIOE awaits a positive AIOE scale); sprint 16 licence → master done.
- **Resolved (2026-11-05):** production serves the latest `main` (the live monitor checks it every 6 hours).
- **Horizon 2030 plan (agreed):** sprint 13 job reference (ROME → FAP 2009 / FAP 2021 → PCS → ISCO-08, official DARES and Insee
  tables), 14 employment to 2030 (DARES Métiers 2030, scenarios as ranges), 15 AI task exposure (OIT 2025 + France Travail tags +
  complementarity θ rebuilt from O*NET per the owner's guide, grade C; Felten AIOE still needed), 16 licence → master.
  Never one composite score, never an average over a diploma's jobs: ranges and counts.
