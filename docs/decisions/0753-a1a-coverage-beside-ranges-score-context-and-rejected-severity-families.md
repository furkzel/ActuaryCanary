# 0753 — A1a: coverage beside every range, the failed rules beside the score, no quantiles for a rejected severity fit

## Context
R12: the Mack 90 % ranges caught 36 to 67 % of later outcomes in the back-test (record 0062) yet were drawn as the range. R14: DQ01 is a weighted pass rate (99.9 on the demo) and reads as fitness for reserving. R17 (reproduced, 0750): quantiles of a family that the Anderson–Darling test rejects were printed for LIFE.

## Decisions
- **Coverage (R12).** `report/coverage.py` pools the rows `range_calibration` of `back_test.csv` (AE02): inside and origins summed over the horizons of one line (or of all lines for the All lines rows) and one method (MT06 for the Mack range, MT11 for the bootstrap range). The sentence is "90% range; observed coverage in back-test 66.7% (n = 3)", n being the origin and horizon cases tested, or "90% range; no back-test". Placed with the range: under the chart title and in a line under the Mack table of each reserving page; in the "Range from" cell of the headline table, in a new column "Back-test" of the ranges table, and in the row label of the range chart of the uncertainty page. The bootstrap range gets the same sentence beside it, because the comparison is the point. The existing calibration table by horizon stays. Nothing is recalibrated: the ranges are as they were.
- **Score context (R14).** Beside the score: how many rules failed on at least one row, pair or claim and the sum of their failed checks ("7 of 74 rules failed … 73 failed checks in all"; a row failing two rules counts twice, which the sentence says), and one sentence on what the score does not measure (volume, length of history, stability, definitions). Both on the quality appendix and, shortened, in the quality tile of the headline. DQ01 is unchanged; the counts are those of its rule scores.
- **Severity quantiles (R17).** When the selection reason is "no family fits" the page shows no family as selected and no quantiles, and says why in one sentence naming the lowest-AIC family that the files keep. `severity_selected.csv` and `severity_quantiles.csv` are not changed.

## Consequences
- Tests: `tests/report/test_a1a_totals.py` (coverage pooled over horizons and lines with known counts, the Mack, bootstrap and no-test cases on the uncertainty page, the failed-rule counts, the rejected severity fit).
- New texts have Turkish counterparts in `language.yaml`.
