# 0783 — A1c: the rule of 0776 inside the bootstrap's refit (remedy a)

## Decision
- `odp_bootstrap(..., min_link_ratios=1)`: a factor column of the (cut) triangle that rests on fewer than `min_link_ratios` finite link ratios takes the factor 1.000 in the refit of every pseudo-triangle. "Rests on" is `ChainLadder.n_ratios` of the bootstrap's own fitted chain ladder (finite link ratios of the observed triangle, a ratio needing a positive base, records 0776 and 0781), counted once, so the column set is the same for every pseudo-triangle. Function default 1 (no rule): the MT11 benchmarks stay as published. The module passes the limit of the selected paid chain ladder (`ChainLadder.min_link_ratios`, i.e. the setting `min_origins_per_factor`, default 2) through `run_tier_b`, the same path the MT02 tail already takes; `reserving.py` is not touched.
- **The fitted model does not use the rule** (decision 5 of the item): the fitted increments μ, the residuals, φ and the pool come from the volume-weighted chain ladder with its averages (on MOTOR_TPL 1.0499 in column 8). Consistency does not need more: μ only centres the pseudo-cells, and the selected reserve the bootstrap is rescaled to already has the rule. Nothing to ask.
- A ruled column's denominator and factor are not counted as `PSEUDO_ZERO_DENOMINATOR` or `PSEUDO_EXTREME_FACTOR`: the refit does not use them. New result fields `min_link_ratios` and `ruled_columns`.
- **Draws.** The rule makes no draw and keeps the order of the calls. The stream after a run is identical with and without the rule when the process step takes a fixed number of draws (test); the gamma sampler rejects a number of candidates that depends on its shape, so with the real process the stream after a run moves whenever a mean moves. That is not a reordering, and the residual indices of every batch are unchanged.
- MT11 1.4.0 (parameter, refit step, outputs). Tests: `tests/methods/test_a1c_bootstrap_refit.py` (3 × 3 hand case, a ruled column is not a defect, setting 1 bit-identical to the A1b refit, draws, RAA moves only column 8 and the fitted model, pool and φ are the plain ones). The wiring test of MT11 in `tests/modules/test_tier_b_wiring.py` compared the module bootstrap with a direct call without the rule; its premise (the module passes the right inputs) is kept and the direct call now passes the setting's limit. The stub refit of the A1b test takes the new argument.

## Seed script, remedy (a) (2026-11-12, demo, seeds 1 to 20, 10,000, 3.3 min)
| Line | VaR 99.5 % mean (m) | VaR spread | TVaR 99 % mean (m) | TVaR spread | 0779 spreads (VaR / TVaR) |
| --- | --- | --- | --- | --- | --- |
| All lines | 1,173.3 | 4.79 % | 1,271.8 | 45.41 % | 15.6 % / 227.7 % |
| GROUP_TERM_LIFE | 105.9 | 3.57 % | 107.6 | 3.59 % | 3.6 % / 3.6 % |
| MOTOR_OD | 17.3 | 2.57 % | 17.5 | 3.10 % | 2.6 % / 3.1 % |
| MOTOR_TPL | 1,085.9 | 5.46 % | 1,184.6 | 48.60 % | 16.0 % / 235.2 % |
| PROPERTY | 18.5 | 8.32 % | 19.4 | 10.77 % | 8.3 % / 10.8 % |

Identical to the scratch proxy of record 0782 and to the scratch experiment of 0779. Only MOTOR_TPL moves (the only triangle with a column on one link ratio after the cut). **Target missed** on all lines: stage 3 follows. Column 7 (two link ratios) still makes the TVaR tail (one seed at 1,791 m).

## A side effect on the bootstrap mean (to be confirmed in the demo, stage 4)
MOTOR_TPL origin 2017 has its latest paid at column 8; under the rule nothing is ahead of it in the bootstrap's paid model, so every simulated value is 0 and the rescaling to its selected unpaid (0.913 m, which comes from the incurred side of the selection) cannot act ("no simulated unpaid to scale to the selected one", as origin 2016 already had with 0.442 m). The simulated mean of MOTOR_TPL goes from 521.98 m to 521.06 m and that of all lines from 608.52 m to 607.61 m (selected 608.96 m). The selected reserves do not move.
