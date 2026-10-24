# 0278 — Cox, survival and severity references: tools and data

## Context
The work item marks the Cox reference as waiting for the statsmodels decision. Record 0600 settled it: no statsmodels, Cox on numpy and scipy, reference values may be computed once with an external tool and stored with its name and version.

## Decision
- Cox: R survival 3.8.3 (R 4.5.1) on the ovarian data (26 rows, no tied event times, so Efron equals Breslow) and on the lung data (227 complete rows, 26 tied event times, so they differ). Coefficients, standard errors, z, partial log-likelihoods, likelihood-ratio and Wald statistics are frozen at 1e-5. A test-side Cox fit written with numpy and scipy reproduces them.
- Kaplan–Meier: a hand fixture of ten times with censoring and ties (exact fractions); R survfit agrees on survival, Greenwood standard error, log-log limits and numbers at risk (1e-16, `check_km_hand_fixture.R`).
- Severity and extremes: scipy 1.16.2 fits with location zero on four samples of 500 sizes (lognormal, gamma, Weibull, Pareto II) and the generalised Pareto above a stated threshold, samples stored as CSV.

## Consequences
- R is not a dependency and no test runs it; `freeze_survival.R` and `check_km_hand_fixture.R` document the calls.
- The ovarian and lung data are public sample data of the R survival package.
