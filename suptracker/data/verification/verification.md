# SIES ground-truth verification — 2026-11-01T12:59:08+00:00

## Accounting identities

| check | primary | session | evaluable | violations | same rows in raw SIES file | % ok | max abs diff | status |
|---|---|---|---|---|---|---|---|---|
| series_eq_acc_neobac | yes | 2022 | 13644 | 0 | 0 | 100.0 | 0 | pass |
| series_eq_acc_neobac | yes | 2023 | 13869 | 0 | 0 | 100.0 | 0 | pass |
| series_eq_acc_neobac | yes | 2024 | 14079 | 0 | 0 | 100.0 | 0 | pass |
| series_eq_acc_neobac | yes | 2025 | 14252 | 0 | 0 | 100.0 | 0 | pass |
| mentions_eq_acc_neobac | yes | 2022 | 13644 | 356 | 356 | 97.39 | 12 | upstream_inconsistency |
| mentions_eq_acc_neobac | yes | 2023 | 13869 | 0 | 0 | 100.0 | 0 | pass |
| mentions_eq_acc_neobac | yes | 2024 | 14079 | 0 | 0 | 100.0 | 0 | pass |
| mentions_eq_acc_neobac | yes | 2025 | 14252 | 0 | 0 | 100.0 | 0 | pass |
| series_plus_at_eq_acc_tot | yes | 2022 | 13644 | 21 | 21 | 99.85 | 2 | upstream_inconsistency |
| series_plus_at_eq_acc_tot | yes | 2023 | 13869 | 15 | 15 | 99.89 | 1 | upstream_inconsistency |
| series_plus_at_eq_acc_tot | yes | 2024 | 14079 | 0 | 0 | 100.0 | 0 | pass |
| series_plus_at_eq_acc_tot | yes | 2025 | 14252 | 0 | 0 | 100.0 | 0 | pass |
| mention_by_series_eq_acc_neobac | diag | 2022 | 13644 | 356 | 356 | 97.39 | 12 | upstream_inconsistency |
| mention_by_series_eq_acc_neobac | diag | 2023 | 13869 | 0 | 0 | 100.0 | 0 | pass |
| mention_by_series_eq_acc_neobac | diag | 2024 | 14079 | 0 | 0 | 100.0 | 0 | pass |
| mention_by_series_eq_acc_neobac | diag | 2025 | 14252 | 0 | 0 | 100.0 | 0 | pass |
| series_eq_acc_term | diag | 2022 | 6277 | 6187 | 6187 | 1.43 | 236 | upstream_inconsistency |
| series_eq_acc_term | diag | 2023 | 6322 | 6238 | 6238 | 1.33 | 243 | upstream_inconsistency |
| series_eq_acc_term | diag | 2024 | 6327 | 6232 | 6232 | 1.5 | 238 | upstream_inconsistency |
| series_eq_acc_term | diag | 2025 | 6337 | 6243 | 6243 | 1.48 | 239 | upstream_inconsistency |
| mentions_eq_acc_term | diag | 2022 | 6277 | 6186 | 6186 | 1.45 | 236 | upstream_inconsistency |
| mentions_eq_acc_term | diag | 2023 | 6322 | 6238 | 6238 | 1.33 | 243 | upstream_inconsistency |
| mentions_eq_acc_term | diag | 2024 | 6327 | 6232 | 6232 | 1.5 | 238 | upstream_inconsistency |
| mentions_eq_acc_term | diag | 2025 | 6337 | 6243 | 6243 | 1.48 | 239 | upstream_inconsistency |

## taux_acces_ens fidelity (warehouse vs raw upstream Parquet)

| session | upstream rows | mismatches | missing in warehouse | status |
|---|---|---|---|---|
| 2022 | 13644 | 0 | 0 | pass  |
| 2023 | 13869 | 0 | 0 | pass  |
| 2024 | 14079 | 0 | 0 | pass  |
| 2025 | 14252 | 0 | 0 | pass  |

## taux_acces_ens vs live SIES records API (random sample)

| session | sampled | errors | mismatches | status |
|---|---|---|---|---|
| 2022 | 10 | 0 | 0 | pass |
| 2023 | 10 | 0 | 0 | pass |
| 2024 | 10 | 0 | 0 | pass |
| 2025 | 10 | 0 | 0 | pass |

## Bounds

All SIES shares within [0, 100].

## Offer timing (diagnostic)

| session | evaluable | non-monotonic counts | acc_finpp > acc_tot | non-monotonic shares | shares = count / acc_tot (%) | shares = count / acc_pp (%) | acc_finpp = acc_pp | acc_finpp = acc_tot | status |
|---|---|---|---|---|---|---|---|---|---|
| 2022 | 13644 | 0 | 0 | 0 | 100.0 | 51.1 | 3786 | 3670 | pass |
| 2023 | 13869 | 0 | 0 | 0 | 100.0 | 48.2 | 3436 | 3154 | pass |
| 2024 | 14079 | 0 | 0 | 0 | 100.0 | 51.7 | 3534 | 3508 | pass |
| 2025 | 14252 | 0 | 0 | 0 | 100.0 | 56.2 | 4042 | 3866 | pass |

## Offer attributes from the cartographie (diagnostic)

| session | formations | with cartographie | apprentissage | internat | distance | sport HN | art HN |
|---|---|---|---|---|---|---|---|
| 2022 | 13644 | 13639 | 302 | 759 | 990 | 5056 | 3951 |
| 2023 | 13869 | 13786 | 12 | 768 | 1003 | 5164 | 4049 |
| 2024 | 14079 | 14032 | 5 | 768 | 1009 | 5346 | 4231 |
| 2025 | 14252 | 14250 | 3 | 772 | 989 | 5521 | 4407 |

## Structure

- unique_session_cod_aff_form: 0 violation(s)
- every_row_in_a_lineage: 0 violation(s)
- row_in_single_lineage: 0 violation(s)
- links_one_to_one: 0 violation(s)

## Longitudinal continuity — share of 2025 formations linked back

| fili | n_2025 | pct_linked_2022 | pct_linked_2023 | pct_linked_2024 | pct_full_span | pct_full_span_exact | pct_with_inferred_link |
|---|---|---|---|---|---|---|---|
| TOTAL | 14252 | 83.1 | 87.6 | 93.2 | 83.0 | 82.0 | 1.2 |
| BTS | 5351 | 95.3 | 97.2 | 98.6 | 95.3 | 95.1 | 0.1 |
| Licence | 3052 | 70.2 | 75.6 | 87.3 | 70.2 | 67.4 | 3.2 |
| Autre formation | 1815 | 70.9 | 79.6 | 89.4 | 70.4 | 69.5 | 1.0 |
| CPGE | 986 | 96.7 | 97.9 | 99.2 | 96.7 | 96.1 | 0.5 |
| BUT | 820 | 96.5 | 98.8 | 99.4 | 96.3 | 96.3 | 0.0 |
| Ecole d'Ingénieur | 585 | 57.6 | 69.1 | 79.8 | 57.3 | 55.9 | 1.9 |
| Licence_Las | 513 | 71.7 | 79.3 | 88.7 | 71.7 | 68.6 | 3.7 |
| IFSI | 344 | 94.2 | 95.9 | 99.4 | 94.2 | 94.2 | 0.0 |
| PASS | 287 | 61.0 | 72.1 | 80.8 | 61.0 | 60.6 | 0.3 |
| Ecole de Commerce | 256 | 60.2 | 72.3 | 78.9 | 60.2 | 59.0 | 1.6 |
| EFTS | 243 | 86.0 | 93.8 | 96.7 | 85.6 | 85.6 | 1.2 |

**Overall: PASS**
