# 0394 — R11 measured again after the cap (MOTOR_TPL 2025 on the demo)

## Context
Record 0372 measured MOTOR_TPL accident year 2025 of the demo (`demo.yaml`, seed 20261023, size demo, valuation 2025-12-31): incurred 214,988,471 against earned premium 158,120,000 = 135.97 %, of which one nil-closing claim held 66.3 M (31 %).

## Measurement
Generated once outside the repository, in memory, from the generator as changed by 0392 and 0393 (nothing committed). Truth columns `incurred_at_cutoff` and `earned_premium`, both entities summed:

| | before (0372) | after |
|---|---|---|
| incurred | 214,988,471 | 174,859,700 |
| earned premium | 158,120,000 | 158,117,636 |
| ratio | 135.97 % | 110.59 % |
| reserve of the nil-closing claim | 66.3 M (31 % of incurred) | 26.15 M (15.0 % of incurred) |
| largest reserve (claim 1, not nil, 6.68 M cost at base prices) | 81.6 M | 81.64 M (46.7 % of incurred) |

The earned premium differs in the fourth digit from the rounded figure of 0372; the incurred drop of 40.1 M is the nil claim (66.3 M → 26.15 M).

## Reading
The cap works as intended: the reserve of the nil claim is its cap times the price index (500,000 × 19.79 = 9.9 M) times the case reserve bias and noise of the review (1.28 and the noise draw), 2.6 × in all, 26 M. It is now the second largest reserve of the year and 16.5 % of the earned premium, not 42 %. What remains of the ratio is the real tail draw of claim 1 (0372, finding 1: a property of an uncapped alpha 1.8 tail on a portfolio of 0.012 of the baseline); without the two it is the same 42 %. No further change is made here.
