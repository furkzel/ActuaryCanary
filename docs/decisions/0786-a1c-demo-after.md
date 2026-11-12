# 0786 — A1c: the demo after the change, beside record 0780

## Context
`canary demo` on the code of `main` (run id `d0d20f8a23b6482d`, the run of record 0780, 13.1 s) and on the final code of A1c (`f7ef970a4958c6d5`, 14.8 s), both in a scratch folder; every CSV of the two runs compared row by row.

## What did not move
`ultimates.csv`, `chain_ladder.csv`, `factors.csv`, `reserve_range.csv` (Mack and selected), `cash_flows.csv`, `back_test.csv`, `sensitivity.csv`, the tails of MT14 and every other table outside the list below are identical. Selected unpaid of all lines 608,961,788.16 as in 0780. Every non-bootstrap row of `risk_measures.csv` (Mack, expected) is identical.

## Bootstrap, total per line (nominal, seed 1): before (0780) → after
| Line | Mean (m) | p95 (m) | VaR 99.5 % (m) | TVaR 99 % (m) | CV |
| --- | --- | --- | --- | --- | --- |
| GROUP_TERM_LIFE | 69.16 → 69.16 | 90.57 → 90.83 | 104.58 → 106.00 | 105.95 → 107.61 | 0.179 → 0.179 |
| MOTOR_OD | 12.10 → 12.10 | 15.21 → 15.08 | 17.24 → 17.18 | 17.50 → 17.39 | 0.148 → 0.143 |
| MOTOR_TPL | 521.98 → **521.06** | 834.22 → 762.99 | 1,279.37 → 990.20 | 1,570.42 → 1,022.67 | 0.466 → 0.257 |
| PROPERTY | 5.28 → 5.28 | 11.76 → 11.17 | 18.25 → 18.01 | 19.46 → 18.67 | 0.654 → 0.592 |
| All lines | 608.52 → **607.61** | 923.02 → 849.82 | 1,367.08 → 1,074.52 | 1,656.16 → 1,110.27 | 0.400 → 0.222 |

Present value, all lines: mean 334.42 → 348.28 m, VaR 575.38 → 565.62 m, TVaR 607.14 → 578.64 m; MOTOR_TPL mean 260.37 → 274.39 m. The present value is the nominal simulation times the discount ratio of the bootstrap's own simulated cash flows (0780); the rule (no development in column 8) and the floor change that pattern.

## Diagnostics and parameters
- `PSEUDO_*` shares (`tier_b_parameters.csv`): MOTOR_TPL zero denominator 0.14 % → 0, negative cumulative 63.54 % → 0, extreme factor 0.39 % → 0; PROPERTY negative cumulative 73.33 % → 0, extreme factor 0.07 % → 0.036 %. `diagnostics.csv` loses `PSEUDO_NEGATIVE_CUMULATIVE` (MOTOR_TPL, PROPERTY) and PROPERTY's `NEGATIVE_TOTAL_RESERVE` (41 → 38 rows).
- `bias` (raw simulated mean over the bootstrap's own chain reserve, minus 1): LIFE 0.33 % → 1.25 %, MOTOR_OD 0.29 % → 1.89 %, MOTOR_TPL 6.30 % → 0.20 %, PROPERTY 3.53 % → 15.76 % (the floor on PROPERTY's small cells, record 0784; removed by the rescaling).
- `assumptions.csv`: 284 → 288 rows: `n_simulations` 50,000 and the new `floor_pseudo_increments` true per line. `simulations` 10,000 → 50,000 in `tier_b_parameters.csv` and `risk_measures.csv`.

## A mean moved
The nominal bootstrap mean of MOTOR_TPL and of all lines fell by 913,062.22 (origin 2017, record 0783: its paid has only the ruled column 8 ahead, so the simulated unpaid is 0 and cannot be rescaled to its selected 0.913 m; origin 2016 had the same with 0.442 m before). The selected reserve did not move. Stage 4 stopped for the owner's decision; **the owner accepted it** (2026-11-12): the existing note "no simulated unpaid to scale to the selected one" states it, as for origin 2016, and the rescaling stays as it is.
