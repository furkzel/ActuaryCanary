# 0306 — Survival analysis: what was measured

## Context
MT19 asks for a hand fixture, two Cox references, a calibration on Weibull data and a comparison with the settlement times of the generator. This record has the numbers (machine in use; run 2026-10-27).

## Decision
Proved against references
- The ten-time Kaplan–Meier fixture: survival, Greenwood sum, standard error and variance equal the hand values to 1e-12 relative, the log-log interval to 1e-9; median 7. A loop written from the formulas equals the code on random samples.
- Cox against R survival 3.8.3 (frozen, `checked_by_owner: true`), Efron and Breslow, ovarian (26 rows) and lung (227 rows, 26 tied times): coefficients and standard errors within 1e-8 relative on ovarian (R's own convergence) and 1e-13 on lung, log-likelihoods and the likelihood-ratio statistic within 1e-14; the tolerance is the specification's 1e-5. The Wald statistics (frozen to four digits) agree to 0.005. Efron and Breslow are equal on ovarian and differ on lung.
- Exact derivatives (gradient and information equal central differences), the likelihood equals a loop of the specification with many ties, the fit does not depend on the time scale, and a binary covariate has the sign of the log-rank observed minus expected; with no covariate effect the Breslow baseline is the Nelson–Aalen hazard and the Kaplan–Meier cumulative hazard is never below it.
- Information only, no R reference: the Grambsch–Therneau test equals a loop on ovarian, passes proportional hazards on simulated data and rejects crossing hazards; the concordance equals the pairwise count.

Calibration (`test_survival_monte_carlo.py`, flag set, the spec's count: 1,000 samples of 2,000 subjects, seed 20261027, Weibull shape 1.5, three binary covariates with coefficients 0.5, -0.3 and 0.8, exponential censoring): coverage of the 95 per cent interval, Efron 0.953, 0.962, 0.958 (17 s); Breslow the same values (19 s; no tied times); Efron with times rounded to two decimals (tied) 0.956, 0.953, 0.970 (16 s). The band is 0.90 to 0.99. Three tests, 53 s.

Ground truth, baseline medium (`test_survival_ground_truth.py`, 11 s with the simulation): Kaplan–Meier median settlement time in days against the median of the simulated times from report to first closing of the same reported claims (including closings after the cut-off), ratio: GROUP_TERM_LIFE 45 against 46 (0.978), MOTOR_OD 62 against 61 (1.016), MOTOR_TPL 411 against 407 (1.010), PROPERTY 159 against 159 (1.000); the tolerance is 10 per cent. Cox on NON_LIFE (15,724 events, covariate line, reference MOTOR_OD): hazard ratio of closing MOTOR_TPL 0.145, PROPERTY 0.352; concordance 0.710 (information). The Grambsch–Therneau test rejects proportional hazards for the lines (global 479, p below 1e-100): the lines have different delay distributions, so a single hazard ratio is an average; the diagnostic NON_PROPORTIONAL_HAZARDS says so. Report years are not flagged (log-rank across ten years p = 0.95 NON_LIFE, 0.35 LIFE). LIFE has one line, so it gets curves and no Cox model (NO_COX_MODEL).

Speed: `run_survival` on the medium baseline 0.5 s (durations of 18,239 claims 0.4 s); the 96 new fast tests take 4.5 s serial, the slowest 0.13 s.

Golden copy and examples: `just golden` and `just examples` changed nothing (MT19 is not called, record 0304).

## Consequences
- The pass criteria of the specification hold. The ground-truth ratios are close because the generator draws first closings from the delay distribution that Kaplan–Meier estimates; the comparison does not test the month-end approximation beyond the 309 of 18,239 durations that use it.
- UNVERIFIED: the Grambsch–Therneau test, the concordance and the baseline against R; behaviour on scenarios other than baseline; the `large` scenario; timings on an idle machine.
