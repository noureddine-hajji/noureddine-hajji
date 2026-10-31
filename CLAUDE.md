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
    `journey.py` ("Mon parcours"), `planb.py`, `analytics.py`.
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
     (skip if absent). `python -m pytest -q` must pass; it takes about 3–4 min with real data.
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
- **Search.**
  - Gold set and holdouts must stay at 100 %.
  - The tie-break is an attribute-neutral hash.
  - `clean_complement` handles establishment names containing " - ".
- **Analytics.** No IP, user agent or identifier; daily HMAC pseudonym; k = 3; DNT/GPC honoured;
  closed lists; fail-open.
- **Front-end.** Escape every stored string with `esc()`. Async renders must check that their
  target element is still the one on the page (navigation races).

## Status (2026-10-31)
- **Live in `main`:**
  - search 2.0;
  - analytics and the `/#/stats` dashboard;
  - A2 offer timing, A4 offer options, A3 bac-général mention bounds;
  - B4 bac techno and pro journey;
  - Plan B (formation page);
  - release guards (versioned assets, `/api/version`).
- **Next (sprint 2):**
  - **B1, success in first year.** Data.gouv "Parcours et réussite des bacheliers inscrits pour la
    première fois en licence / DUT". Check first whether it is national only, and if so show it as
    "moyenne nationale", never as per-university.
  - **B5, CROUS housing near each formation.** CNOUS "Logements étudiants" dataset on data.gouv.fr.
  - **A5, student mode and glossary.**
  - Optional: a "Voir un plan B" button next to each ambitious formation in "Mon parcours".
- **Later (sprint 3):** B2 InserSup (insertion and salary), A6 shareable wish list.
- **Open question for the owner:** the live site looked like it lacked sprint 1 and Plan B. `main`
  is complete (verified in Chromium). Likely cause: a stale Vercel production deployment, possibly
  from Vercel's own branch `vercel/install-and-configure-vercel-w-9i0tca` (PR #9, closed unmerged),
  or a cached `app.js`. The owner was asked to check that Vercel → Deployments → Production comes
  from `main` at the latest commit (the footer shows it).
