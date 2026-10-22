# 0075 — MT06 and MT07: the ground-truth tests move to what the evidence supports

## Context
Records 0062 and 0063 showed that the MT06 coverage miss and the MT07 MOTOR_TPL 2023 miss are properties of the synthetic data, not faults of the code, and proposed changes to the two specifications. The owner approved them. Both tests were strict expected failures until now.

## Decision
- **MT06 1.1.0.** The ground-truth test is a calibration on triangles drawn from Mack's own model: gamma link ratios with mean f(j) C and variance sigma²(j) C, the parameters and the first column fitted to GenIns, 2,000 runs, fixed seed. The true total reserve must fall below the 95th percentile of the lognormal range in 90 to 99 per cent of runs. It is slow and runs only with `ACTUARYCANARY_MONTE_CARLO=1`, as the old test did. The coverage per line on the synthetic baseline (200 runs at 2 per cent of the portfolio) stays as a second test of the same kind; it prints the figures and has no tolerance.
- **MT07 1.1.0.** The ground-truth tolerance is on the total per line, summed over the accident years with at least three years of development: 5 per cent, 10 per cent for MOTOR_TPL, on baseline medium and high_inflation medium. The ratio of each accident year is printed as information. The list of known exceptions is gone.
- The expected-failure marks of both tests are removed. No code and no tolerance was changed to make a test pass.

## Results (2026-10-22)
- MT06 calibration: coverage 0.936 over 2,000 runs (0.939 over 4,000 runs in record 0062).
- MT06 synthetic baseline, information: GROUP_TERM_LIFE 0.81, MOTOR_OD 0.875, MOTOR_TPL 0.65, PROPERTY 0.70, the same as in record 0062.
- MT07 per line, baseline medium: GROUP_TERM_LIFE 1.0000, MOTOR_OD 1.0004, MOTOR_TPL 0.9645, PROPERTY 0.9867. High_inflation medium: 1.0000, 1.0005, 0.9496, 0.9872. All inside their tolerances.
- MT07 per accident year, for information: MOTOR_TPL 2023 is 0.850 (baseline) and 0.829 (high_inflation). High_inflation MOTOR_TPL 2016 is 0.949 (−5.1 %) on the data the test read, not the −2.9 % that record 0063 reported for it. Why the two figures differ is not known (UNVERIFIED); it does not change the outcome, because the per-year tolerance no longer applies.

## Consequences
- The run id changes: MT06 and MT07 are in the specs of every run. The golden copy of the report changed only in the run id and the spec versions.
- The calibration test shows the code is right where Mack's assumptions hold. It says nothing on the width of the range for inflation-driven or long-tailed lines; the report keeps the label "lognormal approximation" and record 0045 still points to the tier B bootstrap.
- The MT07 total per line hides a young origin that misses (TPL 2023 is about −15 %). The per-year ratios stay visible in the test output for that reason.
