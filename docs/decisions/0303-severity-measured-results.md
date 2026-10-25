# 0303 — Severity and extremes: what the runs of 2026-10-25 measured

## Context
MT17 and MT18 ask for two kinds of ground-truth check: calibration on samples from the models themselves (behind `ACTUARYCANARY_MONTE_CARLO=1`) and a comparison with the severity truth of the generator on the synthetic scenarios at medium, "as information, no tolerance". This record holds the numbers and says which counts were reduced and which bounds are the tests' own.

## Decision
Calibration on samples from the models (`test_severity_monte_carlo.py`, flag set, 12 tests, 6 min 38 s on a machine in use; seed 20261025):
- MT17, 1,000 samples of 2,000 sizes per family (the spec's count), parameter sets lognormal mu 10 sigma 1.2, gamma shape 2.5 scale 4000, Weibull shape 1.5 scale 8000, Pareto II alpha 3 theta 50000 (those of `tier_b/MT17-severity-fits`). Coverage of the 95 per cent Wald interval: lognormal 0.947 and 0.946, gamma 0.937 and 0.938, Weibull 0.946 and 0.955, Pareto II 0.954 and 0.955 (both parameters). The spec asks for 0.90 to 0.99.
- MT17, true family selected: 200 samples per family (not 1,000) with 100 bootstrap samples inside each, because every sample runs the whole bootstrap: lognormal 1.000, gamma 1.000, Weibull 0.990, Pareto II 1.000. The spec asks for at least 0.80.
- MT18, 1,000 samples of 5,000 sizes (lognormal body, generalised Pareto tail above a known start u0, 10 per cent of sizes above it, scale 20,000), the 95 per cent profile interval for xi at the true threshold: 0.945 for xi 0.3 and 0.945 for xi 0.5. The spec asks for 0.90 to 0.99.
- MT18, the automatic rule: 100 samples (not 1,000) per xi, 100 bootstrap samples inside each; the estimated 99.5th percentile is within 25 per cent of the true one in 100 of 100 samples for xi 0.3 and for xi 0.5. The spec asks for at least 80 per cent.
- Because the counts of the last two are smaller than the spec's, the calibration is not "verified at the spec's counts" for those two; for coverage it is.

Synthetic scenarios at medium (`test_severity_ground_truth.py`, slow, skip when the folder is missing). Baseline, sizes as CV08 gives them (value-date prices), fits take 2 s (MT17) and 10 s (MT18) for the four groups and 18,239 claims:
- MT17 selects: GROUP_TERM_LIFE lognormal, MOTOR_OD lognormal, PROPERTY gamma (each the lowest AIC among the families not rejected), MOTOR_TPL lognormal with the label "no family fits" (every family rejected; the spec expects this where the generator mixes a body, a Pareto tail and litigation).
- Fitted 90th percentile over the true one (price level and superimposed inflation): MOTOR_OD 16.1, MOTOR_TPL 18.3, PROPERTY 14.7. The test requires each to lie within 30 per cent of their geometric mean (the test's own bound).
- Trend of sizes by origin year against the generator's superimposed inflation: MOTOR_OD found 2.96 per cent, truth 3 per cent; MOTOR_TPL found 4.76 per cent, truth 5 per cent. The test requires within 1.5 percentage points (its own bound). MT17 warns of a trend (p below 0.01) on GROUP_TERM_LIFE (-4.3 per cent), MOTOR_OD and MOTOR_TPL, not on PROPERTY (p 0.67).
- MT18, fitted xi (profile interval) against 1/alpha of the generator: MOTOR_OD 0.594 (0.458 to 0.753) against 0.455; MOTOR_TPL 0.683 (0.589 to 0.786) against 0.556; PROPERTY 0.684 (0.413 to 1.089) against 0.667; GROUP_TERM_LIFE 0.178 (the truth file has no row for it). Two of the three intervals do not cover the truth: the generator's tail is a mixture of a body and a Pareto draw with 0.2 to 1 per cent weight, multiplied for litigated claims, with superimposed inflation, which a generalised Pareto above a threshold in the body only approximates. The test requires xi between half and twice the truth (its own bound).
- MT18 selects u at the 0.95 quantile for MOTOR_OD, 0.80 for MOTOR_TPL, 0.90 for PROPERTY and 0.80 for GROUP_TERM_LIFE, all below the 99th-percentile threshold of CV08. Share of claims and of incurred above the MT18 threshold against CV08's: MOTOR_OD 5.0 and 29.9 per cent against 1.0 and 13.5; MOTOR_TPL 20.0 and 75.9 against 1.0 and 27.1; PROPERTY 10.1 and 62.0 against 0.9 and 31.9; GROUP_TERM_LIFE 20.1 and 42.0 against 1.1 and 5.1.
- large_loss at medium (large events outside the severity truth): PROPERTY xi 1.32 (infinite-mean tail: quantiles given, expected shortfall empty, WARNING), MOTOR_TPL 0.79, MOTOR_OD 0.60.
- MT18 finds overdispersed yearly exceedance counts on MOTOR_OD and MOTOR_TPL (dispersion 3.9 and 7.0): the generator's litigation and large-claim waves are not Poisson.

## Consequences
- The "none; information only" rows of MT17 and MT18 now have numbers; the test bounds above are not specification tolerances and are named so in the test file. If the generator or the sizes change they may need to move; the record is the place to say why.
- A ForwardStop threshold would classify 5 to 20 per cent of claims as LARGE where CV08 classes 1 per cent (record 0300).
- UNVERIFIED: timings on an idle machine; MT18 at 1,000 samples for the automatic rule; MT17 selection at 1,000 samples; `large` scenario; scenarios other than baseline and large_loss.
