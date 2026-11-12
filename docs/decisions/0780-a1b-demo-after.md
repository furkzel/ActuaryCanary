# 0780 — A1b: the demo after the change, beside record 0775

## Context
Same command as 0775 (`canary demo`, English, 12.7 s), on the changed code: run id `d0d20f8a23b6482d` (before `da2f0f9d044dedb9`; the run id moves with the settings, the specifications and the outputs). Every table of the run was compared with the run before, file by file and row by row.

## Side by side
| Quantity | Before | After | Cause |
| --- | --- | --- | --- |
| Link ratios behind 96-108 and 108-120 | 2 and 1 in all 8 triangles | same | data |
| MOTOR_TPL incurred 108-120 | 0.9300 | 1.0000 (average 0.9300 kept) | rule, one link ratio |
| MOTOR_TPL paid 108-120 | 1.0499 | 1.0000 (average kept) | rule |
| Other lines, 96-108 and 108-120 | 1.0000 (4 decimals) | same, nothing replaced | an average of 1.000 is not replaced |
| Tail factor, all scopes | 1.000, default | same | unchanged |
| Selected unpaid, MOTOR_TPL | 482,641,366.90 | 522,419,480.42 | +39,778,113.52 (+8.24 %), the cumulative factors of the 2016 origin and what follows |
| Selected unpaid, the other three lines | 69,160,632.15 · 12,100,252.97 · 5,281,422.62 | same | none moved |
| **Selected unpaid, all lines** | **569,183,674.63** | **608,961,788.16** | **+39,778,113.52 (+6.99 %)** |
| Selected IBNR, all lines | 254,925,008.61 | 294,703,122.13 | same amount |
| Chain ladder unpaid MOTOR_TPL, paid / incurred | 300,452,853.09 / 625,356,485.08 | 278,102,282.72 / 685,135,926.33 | paid 1.0499 → 1.000 lowers, incurred 0.93 → 1.000 raises |
| MT07 unpaid MOTOR_TPL | 147,063,980.64 | 143,947,044.79 | same paid factor |
| Mack lognormal all lines: mean · VaR 99.5 % · TVaR 99 % | 569.18 m · 1,042.11 m · 1,068.62 m | 608.96 m · 1,139.90 m · 1,170.17 m | selected reserve and its CV |
| Bootstrap all lines, nominal: mean · VaR 99.5 % · TVaR 99 % (seed 1, 10,000) | 568.74 m · 1,264.22 m · 1,523.30 m | 608.52 m · 1,367.08 m · 1,656.16 m | the bootstrap is rescaled to the selected reserve (0325); VaR and TVaR move 8 to 9 %, inside the seed noise of record 0779 |
| Bootstrap all lines, present value: mean · VaR · TVaR | 314.82 m · 544.07 m · 569.36 m | 334.42 m · 575.38 m · 607.14 m | same |
| Expected cash flows, present value, all lines | 319.55 m | 355.36 m | the extra 39.78 m falls in the first periods of the chain-ladder pattern; the bootstrap keeps its own pattern, hence +19.6 m on its present value |
| MOTOR_TPL MT14 paid tails, exponential / inverse power | 1.0288 / 1.2255 | 1.0116 / 1.1529 | the fit reads the selected factors; the 108-120 factor left the fit as 1.000 |
| MOTOR_TPL MT14 incurred tail (exponential) | 1.0902 | 1.0902 | 0.93 was below 1 before and outside the fit as well |
| Sensitivity `tail_fitted`, MOTOR_TPL: selected IBNR with the fitted tails | 214.11 m → 262.85 m (+22.8 %) | 253.89 m → 306.19 m (+20.6 %) | base moved, fits moved |
| Sensitivity `thin_average` (new) | – | MOTOR_TPL 522.42 m → 482.64 m (−7.6 %) | the same 39.78 m seen from the run |
| Diagnostics | 16 `FEW_LINK_RATIOS`, 7 `NEGATIVE_IBNR` | 14 `FEW_LINK_RATIOS`, 2 `THIN_FACTOR`, 2 `PSEUDO_NEGATIVE_CUMULATIVE`, 7 `NEGATIVE_IBNR` | MOTOR_TPL 108-120 (2 triangles) is `THIN_FACTOR`, not also `FEW_LINK_RATIOS`; the bootstrap diagnostics are new (MOTOR_TPL 63.5 %, PROPERTY 73.3 % of pseudo-triangles with a negative cumulative value) |
| `assumptions.csv` | 284 rows with who = default | 282 default rows and 2 rows with who = `rule` | the two replaced factors (MOTOR_TPL 108-120, paid and incurred), each with the average as the default value and the reason in words |
| `tier_b_parameters.csv` | – | 12 new rows `pseudo_*_share` | R04 counts |

## What moved and why
Every quantity that moved is on MOTOR_TPL, in the totals of all lines, or new. R08 explains each: the replaced factor 108-120, the cumulative factors to ultimate of the origin 2016 (and with them the paid and incurred chain ladders, Bornhuetter–Ferguson, Cape Cod, the selection by maturity for 2016, the tier B ultimates), MT07, the Mack range with the selected reserve, the bootstrap rescaled to the selected reserve, the sensitivity base, the fits of MT14 that read the selected factors, and the totals of all lines. Rows of other lines that differ: the all-lines rows of `risk_measures.csv`, and rows that did not exist (the `thin_average` reason rows of the three other lines, the `pseudo_*` rows). Nothing else moved: the other three lines are identical in `ultimates.csv`, `chain_ladder.csv`, `factors.csv`, `reserve_range.csv`, `cash_flows.csv`, `back_test.csv` and `measures.csv`.

The seed noise of the bootstrap (record 0779) is larger than the move of VaR 99.5 % and TVaR 99 %: the +8 to 9 % are not a finding on their own.
