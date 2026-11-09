# 0368 — MT15 on GROUP_TERM_LIFE in high_inflation: diagnosis (no change to the method)

## Context
Owner statement 2 of record 0367. A read-only script outside the repository (scratch folder) took the paid triangle and claim counts exactly as `tests/methods/test_tier_b_ground_truth.py` builds them for LIFE / GROUP_TERM_LIFE on `high_inflation/medium`, recomputed the separation method from the MT15 formulas with independent plain-loop code, and compared the effects with the generator's truth files.

## Findings (numbers)
- **Reproduced.** Geometric growth of the fitted calendar index over the ten diagonals: 0.3284 a year (32.8 per cent); true claims inflation of the line (`claims_index_GROUP_TERM_LIFE`) 0.0000.
- **Not a defect (iv rejected).** The independent code and the module agree: largest difference of the pattern 1.1e-16, of the index 0 (growth 0.3284 both).
- **Effects fitted.** Pattern r(j) = 0.7827, 0.2173, then 0 (claims settle within two development years). Index lambda(k) / lambda(0) = 1, 0.857, 0.937, 1.108, 1.310, 1.642, 2.112, 4.037, 8.381, 12.884: it rises most in 2022–2025, the years of the fastest price rise. Claim counts n(i) = 71, 61, 65, 81, 74, 83, 90, 92, 103, 119.6.
- **Generator truth.** Exposure grows 6.3 per cent a year (41,685 to 72,449 exposure years) and counts about 6.0 per cent; both are absorbed by n(i). Earned premium grows 47.0 per cent a year. The mean severity per non-nil claim by accident year is 435,934; 345,767; 456,395; 497,463; 582,845; 768,013; 1,086,453; 2,065,058; 4,034,704; 6,406,866, a growth of 34.8 per cent a year, against CPI (yearly mean) growth of 41.3 per cent; severity over CPI stays between 2,548 and 4,238. The cause is in the generator: the sum insured is drawn at the price level of the policy start (`portfolio.py:142`, `sum_insured * price_factor(start)`) and a claim pays a fixed share of it with no later inflation (`claims.py:370`, "nominal; no inflation"). Claims inflation after the loss is therefore truly 0, as the truth file says, but the size of a claim grows with the origin year.
- **Pattern by origin (ii).** The share paid at lag 1 by accident year is 0.774, 0.783, 0.721, 0.704, 0.716, 0.706, 0.630, 0.648, 0.715, 0.703: it varies in a band of 0.63 to 0.78 without a trend; it cannot produce a steady 33 per cent a year.
- **Decisive test.** Dividing each origin row of the triangle by the true mean severity of that origin and refitting gives an index growth of -0.0129 a year (against a truth of 0); dividing by the CPI of the origin year gives -0.0589. The fitted 32.8 per cent is thus the origin-level growth of claim size (34.8 per cent) carried by the diagonals.

## Diagnosis
Cause (i) in its general form: growth by origin year that the model n(i) r(j) lambda(i + j) has no term for. The term missing is the average claim size by origin, not the volume (volume is counted by n(i) and does not alias). The generator element behind it is the one listed under (iii), the sum insured moving with the price index, but it acts at the policy start, so by origin year, not by calendar year; the truth file `claims_index_*` is correct for what it says (calendar inflation of claims) and is no truth for the index that MT15 estimates on a sum-insured line. It is a documented limit of the separation method (Taylor's model assumes a stable claim size by origin), not an implementation defect.

## Decision
1. Information plus a limitation note: MT15 1.0.1 carries it in `notes` (change log: not reviewed by the owner). The comparison of the MT15 index with `claims_index_*` is not meaningful for a sum-insured line; its tolerance in the ground-truth validation stays as written and the deviation of this line is information.
2. Generator note for item P28: the truth for a sum-insured line has no origin-level severity index. P28 adds one to `truth/inflation.csv` (or a separate truth column: the price factor at policy start by accident year) or restricts the MT15 criterion to lines with a claims index; the scenario files do not need to change, since claims of a sum-insured line carry no inflation by design.
3. No change to MT15 code in this item.

## Report check (work item 3)
The report shows no table of the MT15 calendar index or its implied inflation: the page has the MT15 ultimate column and the method diagnostics; `calendar_index` and `future_growth` are rows of `tier_b_parameters.csv` only, and `inflation_comparison` is not produced. Nothing in the report states the estimate without a caveat, so no caveat or finding rule is added and no number changes.
