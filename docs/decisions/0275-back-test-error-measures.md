# 0275 — Back-test fixture: formulas for bias, MAE and RMSE

## Context
MT22 and AE02 define the error e = (estimate − reference) / reference and say bias, mean absolute error and root mean square error are "weighted by the reference ultimate", but write a formula for the first two only.

## Decision
RMSE is taken as sqrt(Σ w e² / Σ w) with w the reference ultimate, in line with the other two. The fixture has four origins, two methods and two horizons with invented numbers.

## Consequences
- If the owner prefers another RMSE, the fixture changes with the spec.
- The re-run property (a back-test equals a run on truncated input) is a test of P24 and P35, not a reference value.
