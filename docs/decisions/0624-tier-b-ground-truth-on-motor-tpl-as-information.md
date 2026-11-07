# 0624 — Tier B ground-truth comparisons outside their tolerance on MOTOR_TPL, as information

## Context
Record 0285 prints the ground-truth comparisons of the tier B methods on the synthetic medium scenarios and finds that on MOTOR_TPL the truth files of the generator disagree with each other: the incurred chain ladder is 1.06 to 1.56 times `ultimates.csv`, which leaves 28 per cent of the 2016 ultimate unpaid after ten years, while `development_pattern.csv` says 1.9 per cent (0063). The wiring touches neither the generator nor the methods.

## Decision
Recorded as information, from 0285 and the handover of P24 (they ran on 2026-10-25 and were not run again here), estimate over truth, baseline unless named:
- MT12 Munich incurred ultimate, MOTOR_TPL 1.250 (tolerance 10 per cent); reserve_bias_change 1.346, high_inflation 1.640. The other lines are inside.
- MT13 Benktander ultimate, MOTOR_TPL 1.362 (tolerance 10 per cent). The other lines are inside.
- MT14 exponential tail on MOTOR_TPL 1.0704 and inverse power 1.5772 against the true 1.0192 of `development_pattern.csv` (tolerance: 50 per cent of the true tail minus 1).
- MT15 fitted index growth a year on MOTOR_TPL 49.8 per cent against 58.3 per cent on high_inflation (tolerance 5 points).
- MT16 non-nil claim counts on MOTOR_TPL 1.036 (tolerance 3 per cent); its ultimate at value-date prices, 1.045, is inside.
- MT11 runs on MOTOR_TPL only on these scenarios: on the other lines a late column of incremental paid sums to zero, which stops the method by its spec. In the wired demo the same happens (3 of 4 groups).

## Consequences
- Nothing is tuned and the generator is not touched. The owner decides whether the truth of MOTOR_TPL is fixed in the generator (open in the handover).
