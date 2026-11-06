# AI exposure and AI usage by occupation: US ↔ Europe data package

This package links two US-based sources on AI and work to the European occupation classification ISCO-08:

- **Eloundou et al. (2024), "GPTs are GPTs"**: *theoretical* exposure of occupations and tasks to large language models.
- **Anthropic Economic Index (release of 26 June 2026)**: *observed* use of Claude, by O*NET task and occupation, for April and May 2026.

Both sources use the US O*NET / SOC classification. European data (EU-LFS, Eurostat, ESCO, national surveys) use ISCO-08. The files below bridge that gap so the three dimensions can be combined on the same ISCO code:

| Dimension | Source | Question answered |
|---|---|---|
| Potential exposure | Eloundou et al. | What share of an occupation's tasks *could* an LLM speed up? |
| Real usage | Anthropic Economic Index | What do people *actually* use Claude for, and how? |
| Employment | Eurostat EU-LFS (not included) | How many workers are in each occupation, by country? |

---

## File overview

| File | Format | Role | Best for |
|---|---|---|---|
| `Eloundou_SOC_ISCO08_passage.xlsx` | Excel | US → Europe crosswalk + exposure scores by ISCO | Exposure indicators for European occupations |
| `AEI_2026-06_taches_ONET.xlsx` | Excel | Anthropic usage data linked to O*NET, ISCO-08 and Eloundou | Comparing real usage with exposure, EU vs US |
| `aei_2026-06-26_taches_onet_synthese.csv` | CSV | One row per task, key indicators | Statistical analysis in R / Python / Stata |
| `aei_2026-06-26_taches_onet_detail.csv` | CSV | Every published metric, by task × source × month | Full-depth analysis, trends, output types |

All four share **O*NET-SOC codes** as their common key. The ISCO-08 codes in the Anthropic files come from the crosswalk in the first file.

---

## 1. `Eloundou_SOC_ISCO08_passage.xlsx`: the crosswalk

### Goal
Make the Eloundou exposure scores, published for 923 O*NET-SOC 2019 occupations, usable with data coded in ISCO-08.

### Why a strict one-to-one mapping is impossible
O*NET has 923 scored occupations; ISCO-08 has 436 unit groups (4-digit). ISCO is coarser, and some ISCO groups (armed forces, pawnbrokers, street sweepers…) have no O*NET counterpart. The workbook therefore provides the closest practical equivalent: **one mapping function in each direction**.

### How the mapping was built
1. **Official chain**: O*NET-SOC 2019 → O*NET-SOC 2010 (O*NET crosswalk) → SOC 2010 → ISCO-08 (BLS ISCO-08 ↔ SOC 2010 crosswalk, 1,131 pairs, via the IBS Stata copy distributed in the R package `iscoCrosswalks`).
2. **Choice of a single ISCO code per occupation**:
   - 692 occupations have only one official candidate: kept as is.
   - For the 231 occupations with several candidates, the candidate whose ISCO definition is textually closest to the O*NET content was selected (TF-IDF similarity on job title, alternate titles and task statements). Every case was then reviewed by hand.
   - 32 choices were corrected among the official candidates.
   - 19 occupations received an adjacent ISCO role outside the official table, because no official candidate was relevant.
3. **Fallbacks**:
   - O*NET occupations created in 2019 are routed via the O*NET 2010 → 2018 SOC table.
   - SOC 29-2055 (Surgical Technologists), missing from the BLS file, is mapped to ISCO 3259.

### Sheets
| Sheet | Content |
|---|---|
| `Lisez-moi` | Method, sources, editable parameters, diagnostics, limits |
| `SOC_vers_ISCO` | 923 rows: each O*NET occupation → one ISCO-08 code, with confidence level, method, justification, official candidates and Eloundou scores |
| `ISCO_vers_SOC` | 436 rows: each ISCO-08 code → one reference O*NET occupation; for the 10 unmatched codes, the nearest role among the 5 closest text neighbours |
| `Detail_liens` | All 1,454 links (1,435 official + 19 adjacent); the aggregate sheets are computed from it by formulas |
| `ISCO_4`, `ISCO_3`, `ISCO_2`, `ISCO_1` | Exposure scores aggregated per ISCO level, with quality indicators |

### Key columns
- **Exposure scores** (from Eloundou `occ_level.csv`):
  - `alpha` = share of directly exposed tasks (E1);
  - `beta` = E1 + 0.5 × E2, the paper's headline measure;
  - `gamma` = E1 + E2.
  - Prefixed `gpt4_` (GPT-4 annotation) or `human_` (human annotators).
- **`_pond_emp` / `_moy_simple`**: mean weighted by US employment (OEWS May 2021) / unweighted mean. Start from `_moy_simple` when you re-weight with European employment.
- **`confiance`**:
  - *Haute*: single official candidate.
  - *Moyenne (validée à la revue)*: algorithmic choice kept after review.
  - *Moyenne (arbitrée)*: manual correction among official candidates.
  - *Faible (rôle adjacent)*: outside the official table.
- **`qualite_passage`** (aggregate sheets): *Bonne / Moyenne / Fragile / Imputée*, based on the share of employment coming from unambiguous links and on score dispersion. Thresholds are editable in `Lisez-moi`.

### Settings
Cell `C4` of `Lisez-moi` switches the aggregation mode:
- `principal`: each occupation counts once, in its main ISCO code (default).
- `réparti`: each occupation is split equally across all its official ISCO codes.

All aggregates recalculate automatically.

### Coverage
- 923 / 923 O*NET occupations mapped.
- 436 / 436 ISCO-08 codes scored, either aggregated or imputed from the reference role.
- For 358 ISCO codes the round trip ISCO → SOC → ISCO returns the same code.

---

## 2. `AEI_2026-06_taches_ONET.xlsx`: observed AI usage

### Goal
Put the Anthropic Economic Index release of 26 June 2026 in one workbook, linked to O*NET tasks, occupations, ISCO-08 and the Eloundou labels.

### Data
- **Periods**: April 2026 and May 2026.
- **Sources**:
  - `claude_ai`: Claude chat and Cowork, Free/Pro/Max plans;
  - `1p_api`: Anthropic first-party API, excluding Claude Code; global level only.
- **Geography**: global, plus the United States, the 27 EU member states and an EU27 aggregate, for task and occupation shares.

### Sheets
| Sheet | Content |
|---|---|
| `Lisez-moi` | Sources, definitions, EU27 method, published-coverage diagnostics |
| `Taches_synthese` | 3,304 rows, one per O*NET task: task statement, O*NET-SOC code, occupation, ISCO-08, Eloundou task label (E0/E1/E2), usage shares (Claude and API, April/May; May for US, EU27, France), key May indicators |
| `Taches_detail` | One row per task × source × month: 19 indicators + 32 output types |
| `Occupations` | 746 occupations: usage shares and indicators, ISCO-08 code, Eloundou occupation scores |
| `Occupations_pays_mai2026` | Share of each occupation in May 2026 Claude usage for the US, the EU27 aggregate and each of the 27 member states |
| `ISCO_4`, `ISCO_2` | Usage shares summed by ISCO code (formulas), EU27/US ratio, mean Eloundou beta, mean automation share |

### Key indicators
| Indicator | Meaning |
|---|---|
| `pct` | Share (%) of the geography's usage classified in this task or occupation |
| `collaboration_bucket_automation_pct` / `_augmentation_pct` | Share of conversations where Claude does the task (automation) vs works alongside the user (augmentation) |
| `ai_autonomy_mean` | Mean degree of AI autonomy, scale 1–5 |
| `human_only_time_mean` | Estimated time for a human alone, in hours |
| `human_with_ai_time_mean` | Estimated time with AI, in minutes |
| `human_education_years_mean` | Estimated years of education the task requires |
| `use_case_work_pct` / `_personal_pct` / `_coursework_pct` | Work, personal or study use (%) |
| `artifact_*_pct` (detail only) | Main output produced: code, report, email, slides, analysis… |

### Methodological notes
- **Missing ≠ zero**: Anthropic does not publish cells below privacy and sample thresholds. An empty cell means "not published".
- **EU27 aggregate**: average of national shares weighted by each country's share of global Claude usage. Unpublished cells in small countries count as zero, so rare tasks are slightly under-estimated for the EU27.
- **Coverage**: at task level, published shares cover about 94% of global usage, 92% for the US and only 73% for the EU27. At occupation level, coverage exceeds 94% everywhere. **For EU vs US comparisons, prefer the occupation and ISCO sheets.** To compare task distributions, divide each share by its column's total (given in `Lisez-moi`).
- **13 tasks** recently added to O*NET have no occupation attached, and therefore no ISCO code.
- Shares describe **what users do with Claude**, not the share of jobs exposed. They are relative to each geography's usage, not its employment.

---

## 3. `aei_2026-06-26_taches_onet_synthese.csv`

### Goal
Same content as the `Taches_synthese` sheet, as a flat file.

### Value
Loads directly into R, Python, Stata or Power BI without Excel parsing. It is the natural input for analyses such as task-level usage vs Eloundou exposure, or joins with your own task or skills data.

```python
import pandas as pd
t = pd.read_csv("aei_2026-06-26_taches_onet_synthese.csv", dtype={"task_id": str, "isco_principal": str})
```

---

## 4. `aei_2026-06-26_taches_onet_detail.csv`

### Goal
Every published global metric for every task, by source (`claude_ai`, `1p_api`) and month (`avr2026`, `mai2026`).

### Value
The most complete version: all collaboration patterns (directive, feedback loop, task iteration, learning, validation) and the 32 output types. Use it to:
- track changes between April and May;
- compare chat and API usage;
- study what kind of output AI produces for each task.

It is long and wide, so it is better handled in code than in Excel.

---

## Typical uses

1. **AI exposure of European employment.** Take `ISCO_2` or `ISCO_3` from the crosswalk (`_moy_simple` columns) and weight by EU-LFS employment by country (Eurostat table `lfsa_egai2d` or microdata).
2. **Potential vs real usage.** In `AEI_2026-06_taches_ONET.xlsx`, sheet `ISCO_2` or `ISCO_4`, compare `eloundou_gpt4_beta_moyen` with usage shares. Occupations with high exposure but low usage, and the reverse, are the interesting cases.
3. **Europe vs United States.** Use the `ratio_UE27_sur_USA` column and the `Occupations_pays_mai2026` sheet to spot occupations where AI is used relatively more or less in Europe.
4. **Task-level research.** Use the synthesis CSV to relate automation/augmentation patterns to task characteristics and to the Eloundou E0/E1/E2 labels.

---

## Limits

- Eloundou scores and the Anthropic data describe **US task content**. Applying them to European jobs assumes comparable task content for the same job title, a standard assumption in OECD and ILO work.
- The crosswalk relies on official tables plus expert judgement. Rows with *Moyenne* or *Faible* confidence deserve a check in your field of interest.
- Armed forces (ISCO 0110, 0210, 0310) have no O*NET equivalent. Their reference roles are civilian proxies and are best excluded from analysis.
- Anthropic data cover only two months and only Claude. They reflect the user base of one AI product, not the whole economy.

---

## Sources and citations

- Eloundou, T., Manning, S., Mishkin, P., Rock, D. (2024). *GPTs are GPTs: Labor market impact potential of LLMs.* Science 384(6702). Data: <https://github.com/openai/GPTs-are-GPTs>
- Massenkoff, M., Lyubich, E., Sacher, S., Hitzig, Z., Zhang, S., Heller, R., McCrory, P. (2026). *Anthropic Economic Index report: Cadences*, 26 June 2026. <https://www.anthropic.com/research/economic-index-june-2026-report>. Data (CC-BY): <https://huggingface.co/datasets/Anthropic/EconomicIndex>
- U.S. Bureau of Labor Statistics, ISCO-08 / 2010 SOC crosswalk. <https://www.bls.gov/soc/>
- Hardy, W., Keister, R., Lewandowski, P. (2018). *Educational upgrading, structural change and the task composition of jobs in Europe.* Economics of Transition 26(2). Crosswalk files via the R package `iscoCrosswalks`.
- O*NET Resource Center, Occupational Listings and crosswalks (2010 → 2019, 2010 → 2018 SOC).
- ISCO-08 labels and definitions: ESCO, European Commission.
