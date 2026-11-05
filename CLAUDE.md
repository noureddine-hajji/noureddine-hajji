# SupTracker — project memory for Claude Code

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
  - **Mes vœux (sprint 11):** `voeux.py` (the student's list of up to 10 vœux read for the current profile, `#/voeux`).
  - **Prévision n+1:** `prevision.py` (calibrated next-campaign ranges of every indicator with a history, formation page).
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
     (skip if absent). `python -m pytest -q -n auto --dist loadfile` must pass (pytest-xdist), then `tests/test_analytics.py` alone.
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
  - Apprenticeship is nearly absent from SIES stats after 2022, so there is no filter; show a note.
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
  - CI: push on `main` only, branches through their PR, stale runs cancelled, `pytest -n auto --dist loadfile`, analytics (R16 timing) serial.
  - Monitor: `suptracker-monitor.yml` every 6 h on `vars.SUPTRACKER_URL`, `DNT: 1` + robot UA (never counted).
- **Mes vœux (sprint 11).**
  - Zones come from `journey.stage2(..., only=codes)`: the same row as the full type, hence the zone of "Mon parcours" and
    Plan B (red team V1-V2). Never a frozen zone: the list is re-read for the current profile.
  - The reading only COUNTS zones with fixed rules; an uncertain safety is not sure; never a combined chance of admission.
    Parcoursup vœux are not ranked: no ordering.
  - The list lives in localStorage (codes only, validated, deduplicated, max 10); `/api/voeux` records no analytics event.
- **Prévision n+1 (formation page).**
  - Ranges of published indicators for the campaign after the latest, never a probability; each range is computed apart.
  - The method is the sprint-5 one: predictor chosen on 2024, ranges from 2024 errors, tested on 2025 (coverage printed as
    measured on the range SHOWN, rounded counts included, flagged "moins fiable" below 75 %); served ranges use 2024 + 2025 errors. At least 2 campaigns of history,
    only formations in the latest campaign, only on the latest campaign's page.
  - Rates: errors in points, clipped to [0, 100]. Counts: proportional errors, rounded outwards. Zero-admit campaigns'
    `pct_*` are ignored. The access rate is NOT re-forecast: it is sprint 5's `mart.forecast` range (both pages agree), served only with two
    PUBLISHED rates (sprint 5's n_hist counts campaigns, rate or not).
- **Search.**
  - Gold set and holdouts must stay at 100 %.
  - The tie-break is an attribute-neutral hash.
  - `clean_complement` handles establishment names containing " - ".
- **Analytics.** No IP, user agent or identifier; daily HMAC pseudonym; k = 3; DNT/GPC honoured;
  closed lists; fail-open.
- **Front-end.** Escape every stored string with `esc()`. Async renders must check that their
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
  - sprint 9: removed at the owner's request (2026-11-02); sprint 10 (scale) on the branch; next: sprint 12 (job → formations).
- **Open question for the owner:** the live site looked like it lacked sprint 1 and Plan B. `main`
  is complete (verified in Chromium). Likely cause: a stale Vercel production deployment, possibly
  from Vercel's own branch `vercel/install-and-configure-vercel-w-9i0tca` (PR #9, closed unmerged),
  or a cached `app.js`. The owner was asked to check that Vercel → Deployments → Production comes
  from `main` at the latest commit (the footer shows it).
