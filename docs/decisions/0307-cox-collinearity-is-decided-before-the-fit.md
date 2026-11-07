# 0307 — Cox: collinear covariates are decided before the fit

## Context
The pull request of `s/P25c-survival` failed on Ubuntu and on Windows (run 42371620282) in the same test, `test_collinear_covariates_are_skipped`: the covariates `a` and `2a` were not recognised as collinear. The fit started, the optimiser stopped after 3 iterations with a Newton decrement above the limit, and the method was skipped with "the optimiser did not converge in 3 iterations" instead of a reason that names collinearity. The word "collinear" was only reached when `numpy.linalg.inv` raised on a singular information matrix, which depends on the rounding noise of the platform: an exactly singular matrix is sometimes inverted without an error, to enormous numbers.

## Decision
- `cox_fit` calls `collinear_covariates` before the optimiser. The columns are centred and scaled to unit variance. A column is kept when the number of singular values above `COLLINEARITY_TOLERANCE` times the largest one is equal to the number of kept columns plus it; otherwise it adds no rank and is named. The columns are taken in the order of the names, so for `a` and `2a` it is `b` that is named.
- A constant column (its range at most `COLLINEARITY_TOLERANCE` times its largest absolute value, a column of zeros included) is named too: it cancels out of the partial likelihood.
- `COLLINEARITY_TOLERANCE = 1e-6`, one named constant in `methods/survival/cox.py`. Rounding noise in an exact dependence is of the order 1e-16; below 1e-6 the information matrix, whose condition number is about the square of the ratio of the singular values, is above 1e12 and the standard errors keep fewer than four digits. A real pair of dummy variables that differ in one row of 10,000 has a ratio of about 1e-2, far above the line.
- The reason is "covariates are collinear: <names> add no rank to the others (constant, or a combination of the covariates before them)". The check before the fit does not depend on the optimiser or the BLAS kernel; the singular-matrix branch after the fit stays as a second guard.
- No tolerance of another test was loosened. The Windows job failed in the same test only (1 failed, 1561 passed there and on Ubuntu).

## Consequences
- Tests (`test_mt19_cox.py`): `a` and `2a` (the failing test, now also checks that `b` is named and `a` is not); a pair at a singular-value ratio of half the tolerance (flagged) and of twice the tolerance (not flagged), built from orthogonal columns so the ratio is exact; a check that scale and position of a column do not matter; a constant column and a column of zeros; a well-conditioned pair that still fits.
- The R references (ovarian, lung, Efron and Breslow) are unchanged. The Monte Carlo calibration of record 0306 was not rerun: the fit code is unchanged beyond the check, and its three binary covariates are far from collinear.
- MT19 is not wired (0304), so golden, examples and run ids do not move.
