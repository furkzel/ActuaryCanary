# 0381 — Recognition of the four feeds: labels of another concept, dominated rivals, the confusion matrix

## Context
F1bc builds the concepts `reinsurance_treaties`, `reinsurance_transactions`, `recoveries` and `ledger` (flags set, their column and value aliases moved from AL03/AL04 into AL01 1.2.0 and AL02 1.2.0: 42 column entries and 8 value entries; the entries of `segment`, `line`, `entity` and `currency` shared with the life concepts stay in AL03/AL04 for those concepts). With the four concepts taking part in concept scoring and the rule of record 0375 unchanged, measured on the 117 sheets of the nine scenarios at size tiny (the later feeds read from `phase2/`; checked 2026-11-11): 101 right, 16 wrong. All 16 were "not recognised" where a concept was expected, none was read as a wrong concept: the reinsurance transactions in all nine scenarios (margin 0.05 clean, 0.12 messy, over `premiums`, which finds all six of its required fields in that sheet) and the recoveries in the seven clean scenarios (margin 0.19 over `premiums`). Premiums, recoveries and reinsurance transactions are all movements with an id, a booking date, an amount, a currency and a type; the premiums sheet itself had fallen to a margin of 0.31 (0.51 before the new concepts existed).

## Decision
No constant of record 0375 changes (`MIN_MARGIN` 0.30, `CLEAR_MARGIN` 0.50, `MIN_REQUIRED_SHARE` 0.80, `MIN_EXPLAINED_SHARE` 0.75) and no rule of it is weakened. Two kinds of evidence are added in `recognition/concepts.py`; both reuse constants that already exist:
1. **Labels of another concept speak against a concept.** A column mapped to a classified field of concept A whose distinct labels A's value aliases recognise by less than `CLASS_SHARE` (0.5, the share `map_columns` already uses to confirm a classified field), while another concept recognises them by at least that share, is *contradicted* for A: the field does not count as found in A's score and the column does not count as explained by A. Labels nobody recognises (a company's own codes) are no evidence either way, so a known sheet with unknown labels scores as before.
2. **A dominated rival is no rival.** When the best concept explains at least `MIN_EXPLAINED_SHARE` (0.75) of the sheet's columns, a concept whose explained columns are a strict subset of the best concept's is left out of the margin. Below that share every concept stays a rival, so a workbook with a dozen unknown columns gains nothing (the case record 0375 was written for). In the same way a complete concept that explains at least 0.75 of the sheet and a strict superset of what the first-ranked concept explains is ranked first (the score favours a concept with few fields, premiums, over one with many optional fields, reinsurance transactions, when both find all their required fields).

Measured after the change, same 117 sheets: **117 right, 0 wrong**. Raw margin (best score minus the next score, as 0375 measured it) and the margin `judge` uses, clean / messy: claim_valuations 0.74 → 1.00; claims 0.59 → 1.00; expenses 0.56 → 0.95; interest_rates 0.32 / 0.42 → 1.00 / 0.87; ledger 0.45 / 0.40 → 0.94 / 0.89; market 0.87–0.97 → 1.00; policies 0.58 → 1.00; premiums 0.44 / 0.45 → 1.00; recoveries 0.34 → 0.94; reinsurance_transactions 0.05 / 0.12 → 1.00; reinsurance_treaties 0.51 / 0.59 → 1.00. A judged margin of 1.00 means every other concept is dominated. Required share 0.83–1.00 and explained share 0.88–1.00 as in 0375. The life feeds: margin 0.00–0.12, required share 0.25–0.50, explained share 0.22–0.43, unchanged by the rule and rejected on all three counts.

## Confusion matrix (sheet → concept found, per scenario, size tiny)
Columns: baseline, demo, high_inflation, large_loss, life_book, messy_headers, messy_incremental, reinsurance_heavy, reserve_bias_change. ✓ = read as its own concept; – = the scenario has no such file.

| Sheet (file) | base | demo | infl | large | life | m_hdr | m_inc | ri | bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claim_valuations | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| claims | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| expenses | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| market | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 | ✓ ×2 |
| policies | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| premiums | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| interest_rates | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ledger | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| recoveries | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| reinsurance_transactions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| reinsurance_treaties | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| fund_flows | – | – | – | – | not recognised | not recognised | not recognised | – | – |
| life_events | – | – | – | – | not recognised | not recognised | not recognised | – | – |
| life_in_force | – | – | – | – | not recognised | not recognised | not recognised | – | – |

"Not recognised" carries its reason in `TableRecognition.rejection`, for example life_in_force: "best guess expenses score 0.41 (required 1/4, optional 3/3; no key in the spec), rejected: margin 0.00 over the next concept is not above 0.3; required fields found 1/4, under 80%; only 4 of 18 columns are explained by the concept, under 75%".

## Consequences
- The six feeds of version 1.0 and the interest rates are recognised as before, with larger margins; the four new feeds are recognised in every scenario, clean and messy; the life feeds stay "not recognised" with a reason.
- A movement table that carries only the shared columns and labels nobody knows (recoveries or claim-level ceded movements, the columns cannot tell) is taken for neither concept; the user chooses on the confirmation screen.
- Tests: `tests/recognition/test_new_feeds.py` (the boundary of each new piece of evidence, the look-alike table, every sheet of baseline, messy_headers, messy_incremental, life_book and reinsurance_heavy); `tests/recognition/test_positive_evidence.py` keeps the 0375 boundaries, its hand-built rival now explains the same columns as the best concept (a rival with no columns would be dominated), and its list of planned feeds holds the life feeds only.
- A data rule whose module impact names a module that is not built (M08, M10) keeps the fields the specification states; the quality engine works out impacts from the built modules only, so such an impact is not listed until the module is built.
