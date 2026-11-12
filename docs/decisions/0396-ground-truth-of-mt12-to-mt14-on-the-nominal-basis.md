# 0396 — Ground truth of MT12–MT14 judged on the nominal basis

## Context
Record 0371: the methods read nominal triangles and `truth/ultimates.csv` is nominal, but the true tail of MT14 was taken from the inflation-free `paid_share` of `development_pattern.csv`. The owner decided (2026-11-12): the basis is nominal.

## Decision
In `tests/methods/test_tier_b_ground_truth.py` only `_true_tail` changed: it reads `paid_share_nominal` at the last age of the oldest accident year. MT12 and MT13 compare with `ultimates.csv` and were nominal already; MT14 is the only comparison that moved. No tolerance, assertion or structure was changed; deviations outside tolerance on MOTOR_TPL remain information (record 0624). The inflation-free columns stay in the file.

## Numbers that changed
MT14, baseline medium, MOTOR_TPL true tail (ultimate over paid at the last age of 2016): 1.0192 → 1.3907 (the stated 1 / 0.719). Fitted tails: exponential decay 1.0704, inverse power 1.5772. Other lines: true tail 1.0 (GROUP_TERM_LIFE, MOTOR_OD, PROPERTY) as before. The criterion "fitted tail minus 1 within 50 % of the true tail minus 1" for MOTOR_TPL is reported as False (information).

## Spec sentences now inaccurate (not edited)
- `spec/methods/MT14-tail-factor-fitting.yaml`, ground_truth: "about 1.9 per cent of the 2016 ultimate is paid after ten years, decision 0063" is the inflation-free figure; on the nominal basis about 28 % of the 2016 ultimate (1 − 0.719) is paid after the last age, true tail about 1.39.
- `spec/methods/MT15-separation-method.yaml` compares with the true claims inflation (CPI plus superimposed rate), not with a pattern: not affected by the basis.

## Outcome of the ground-truth module (information)
`baseline medium` generated once in the git-ignored `data/synthetic/` (1 min 25 s, generator as changed by 0392 and 0393) and the module run with the slow tests enabled: 7 passed, 9 skipped (`high_inflation` and `reserve_bias_change` medium were not generated: UNVERIFIED). Outside the spec tolerance on baseline, per line and method (printed by the tests, not failures):
- MT12 Munich incurred ultimate over truth: MOTOR_TPL 1.2445 (others 1.0, 1.0012, 1.0053).
- MT13 Benktander over truth: MOTOR_TPL 1.3591 (others 1.011, 0.9915, 0.9576).
- MT14: MOTOR_TPL as above.
- MT15 index growth fitted against true: GROUP_TERM_LIFE 0.2601 vs 0.3065, MOTOR_TPL 0.3074 vs 0.3719.
- MT16 non-nil counts: MOTOR_TPL 1.0357 outside; ultimate at value-date prices within tolerance on all lines.
- MT11 simulated reserve over true: MOTOR_TPL 1.2625; PROPERTY not evaluable (a column sums to zero or less).
Methods were not touched. The ratios are nominal, so the inflation of MOTOR_TPL (tail and index growth) is the likely source on MOTOR_TPL; the cause was not investigated here.
