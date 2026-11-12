# 0784 — A1c: a floor of the bootstrap's pseudo increments (remedy b)

## Context
After the rule in the refit (0783) the all-lines spreads are 4.79 % (VaR 99.5 %) and 45.41 % (TVaR 99 %): column 7 of MOTOR_TPL, on two link ratios, still has a denominator made of the pseudo cumulatives of the two smallest origins, which reach zero or below (record 0782). The guard of decision 2 (b) must be the smallest correct one that stage 1 supports.

## Decision
- **The guard.** A pseudo increment below its floor is set to the floor; the floor is 0, or the observed increment of the cell where that is negative. `odp_bootstrap(..., floor_pseudo_increments=False)` at function level (the MT11 benchmarks stay as published); tier B parameter `floor_pseudo_increments` of MT11, default **true** (one more row in `assumptions.csv`), passed by `run_tier_b`.
- **Why it is correct.** The over-dispersed Poisson model has no negative increment, and the demo's paid triangles have none (0782). A pseudo value below zero is produced by the resampling (a residual of a large cell put on a small one, `μ + r √μ < 0`), not by the model or the data. With the floor every pseudo cumulative is at or above zero, so a denominator cannot cross zero and the youngest origin no longer starts its projection from a negative value. Where the data itself shows a negative increment (a recovery), the pseudo value may go down to it and no further: the guard never removes what the data shows. No distribution is invented; nothing is drawn; the fitted model, residuals, φ, pool, process and rescaling are untouched.
- **What it costs.** A floor raises the mean of a floored cell (the part below zero is cut). The bootstrap's raw mean rises a little; the rescaling to the selected unpaid (0325) removes that from the published mean per origin. The spread of a thin cell is cut on its lower side only, so the lower percentiles move up slightly and the upper tail loses the outliers that came from near-zero denominators. Measured on the demo triangles, seed 1, raw simulated mean against the chain-ladder reserve of the bootstrap's own fit (no rule, rule, rule + floor): GROUP_TERM_LIFE 74.90 / 74.90 / 75.67 m (chain 74.66, +1.3 % with the floor); MOTOR_OD 14.10 / 14.10 / 14.32 m (chain 14.06, +1.9 %); MOTOR_TPL 319.37 / 290.20 / 301.89 m (chain 300.45; the rule removes column 8's development, the floor adds back about as much); PROPERTY 3.43 / 3.43 / 3.80 m (chain 3.31, +14.8 %: its cut triangle has the smallest cells, 7 to 59 % of them negative before the floor). The 5th percentile rises (PROPERTY 0.55 m to 1.03 m; MOTOR_TPL 182.6 m to 203.3 m). All of this is before the rescaling, which brings every origin's mean back to its selected unpaid. A negative cumulative value no longer occurs on the demo (`PSEUDO_NEGATIVE_CUMULATIVE` was 63.5 % and 73.3 %).
- **Rejected:** a negative cell set to its fitted mean (moves the cell by |value| + μ and removes dispersion; proxy at 50,000: 2.03 % and 1.89 %, a difference to the floor within the noise of 20 seeds).
- **Draws.** The guard makes no draw (test with a process of fixed draw count); where no pseudo cell is below its floor the reserves are bit-identical to stage 2 (test on a smooth triangle). Hand case of the floor in `tests/methods/test_a1c_bootstrap_refit.py`.
- Spec MT11 1.4.0 (parameter, resampling step); `methods/registry.py` follows the spec version (1.3.0 → 1.4.0), a line outside the item's allowed area that the version bump requires.

## Seed script, remedies (a) + (b) (2026-11-12, demo, seeds 1 to 20, 10,000, 3.3 min)
| Line | VaR 99.5 % mean (m) | VaR spread | TVaR 99 % mean (m) | TVaR spread | (a) alone (0783) |
| --- | --- | --- | --- | --- | --- |
| All lines | 1,086.6 | 4.96 % | 1,120.8 | 4.06 % | 4.79 % / 45.41 % |
| GROUP_TERM_LIFE | 106.0 | 2.98 % | 107.6 | 2.55 % | 3.57 % / 3.59 % |
| MOTOR_OD | 17.1 | 2.49 % | 17.3 | 2.23 % | 2.57 % / 3.10 % |
| MOTOR_TPL | 999.4 | 5.65 % | 1,033.4 | 4.56 % | 5.46 % / 48.60 % |
| PROPERTY | 17.9 | 6.17 % | 18.7 | 7.05 % | 8.32 % / 10.77 % |

The TVaR outliers are gone (largest TVaR over the seeds 1,146 m against 1,791 m); what remains falls as 1/√n (proxy and 0785), so it is simulation noise. The floor also acts on LIFE, MOTOR_OD and PROPERTY, whose small cells had negative pseudo values. VaR 99.5 % of all lines (1,087 m) is now near the Mack lognormal VaR of record 0780 (1,140 m) instead of above it (1,327 m in 0779). Target still missed at 10,000: record 0785.
