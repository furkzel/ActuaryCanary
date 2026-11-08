# 0360 — The severity fits take analytic second derivatives, and the three severity files are hashed again (MT17 1.1.0)

## Context
Records 0626 and 0627 found that `severity_parameters.csv`, `severity_fits.csv` and `severity_plots.csv` differ between platforms in the last digits, and the golden test compared them by tolerance (`TOLERANCE_FILES`). Two causes: the standard errors came from a central-difference Hessian with step 1e-4 of each parameter (one last bit of a log-likelihood of 1.7e3 is 2e-13, divided by the squared step), and a single Pareto II fit stopped where the golden-section search could no longer see the top of a flat profile (the score was left at about 1e-8). 0626 named the cure (way 1) and 0627 deferred it to a hardening item before 1.2.0. This is that item.

## Decision
- **Analytic second derivatives.** `families.observed_information(family, x, a, b, truncation)` gives the Hessian of the negative log-likelihood in (a, b) from closed forms for the lognormal (mu, sigma), gamma (shape, scale), Weibull (shape, scale) and Pareto II (alpha, theta); `gpd.information(y, xi, sigma)` does the same for the generalised Pareto in (xi, sigma). The closed form of the second derivative in xi cancels badly for a small `w = xi y / sigma`; below `|w| < 0.1` it is replaced, element by element, by a series of 18 terms (error below 1e-17), and the two forms were compared on both sides of the switch. The central-difference `numerical_hessian` stays for one term only: with a truncation point, the gamma has no closed form for the derivative of ln P(X > d) in its shape, so that one scalar correction (it does not depend on the sample) is differentiated numerically; the lognormal, Weibull and Pareto II corrections are closed.
- **Tighter convergence where the cause was.** A single Pareto II fit (`mle`, not the bootstrap rows) is finished at the root of the score (`polish=True`, which MT18 already used), and the root tolerance of the polish is `1e-14` of the bracket instead of an absolute `1e-15` on k (which is a relative 1e-10 for k of order 1e-5); the ends of the profile interval are found to `1e-14` in xi (they were `1e-12`). The Newton solutions of the gamma and the Weibull end when the step is below `1e-11` and are quadratic, so they are at rounding level already; the Nelder–Mead search of a truncated fit (`xatol` 1e-11, `fatol` 1e-12, about ten ulps of a log-likelihood of 1e3) is not tightened, since a `fatol` below one ulp could not be met. The bootstrap fits (rows of a matrix) are not polished: their results are Monte Carlo estimates and the budget of the medium run counts (0625).
- **Specification.** MT17 1.1.0: the standard-error step now says "analytic second derivatives" (and names the one numerical term of the truncated gamma) and the change log has an entry. MT18 1.1.0 stays as it is: its text never described the derivative (it says "standard errors" and "profile-likelihood interval"). The tolerances of both are unchanged.
- **Golden test.** `TOLERANCE_FILES` is empty; the golden copy holds the SHA-256 and size of the three files again. The comparison mechanism and its tests stay (they run on an example name through a monkeypatch), so a later platform difference that cannot be removed at its source can use it again with a record.

## Result (ran 2026-11-08)
**Size of the move.** Largest relative change per fit, new against old code, on the frozen benchmark samples (500 sizes per family, `tier_b/MT17-severity-fits`; 3,000 and 400 for MT18), the hand samples of the tests and the example runs. The estimates move only for the Pareto II (the polish) and the generalised Pareto (the root tolerance); the standard errors move for every fit.

| fit | estimates | standard errors |
| --- | --- | --- |
| MT17 lognormal, gamma, Weibull (benchmark and hand) | 0 | 8e-9 to 6.6e-7 (hand, truncated gamma 3.5e-6) |
| MT17 Pareto II on its own sample | 1.4e-7 | 6.8e-6 |
| MT17 Pareto II on the lognormal sample | 2.9e-7 | 2.0e-6 |
| MT18 lognormal sample (xi 0.290, sigma 6.4e4) | 2.0e-11 | 1.3e-6 |
| MT18 generalised Pareto sample | 9.9e-14 | 1.6e-6 |
| MT18 hand samples xi -0.3, 0.4, 1.2 | at most 5e-14 | 7e-7, 7e-7, 2e-7 |
| MT18 hand sample xi near 0 | 4e-13 | 3.4e-5 (the old step was 1e-12 there: the old figure was the less accurate one) |

Log-likelihoods move by at most 3e-16 (rounding), the ends of the profile intervals by at most 1.6e-12. Every benchmark and hand fixture stays inside its tolerance (`tests/methods/severity` and `tests/benchmarks`: 191 passed before the new tests were added). On the example runs, cell by cell against the old code: tiny baseline `severity_parameters.csv` 10 of 48 cells, largest 3.75e-6 (a standard error); `severity_fits.csv` 2 of 72, 4.0e-8 (an Anderson–Darling statistic); `severity_plots.csv` 182 of 2,196, 1.5e-7. Demo: `severity_parameters.csv` 35 of 198, 2.3e-6; `severity_fits.csv` 6 of 306, 1.5e-7; `severity_plots.csv` 1,445 of 22,797, 8.5e-7; `extreme_candidates.csv` 47 of 288, 1.2e-5 (a standard error of xi); `extreme_gpd_fit.csv` 7 of 48, 6.5e-6; `extreme_excess_plot.csv` 10 cells, 8.3e-10; `extreme_return_levels.csv` 2 cells, 3.3e-10; `extreme_tail_quantiles.csv` 3 cells, 6.7e-10. No text cell moved: the selected families, the selected thresholds and the rejections are the same.

**Platforms.** The Linux wheels of `uv.lock` (numpy 2.5.4, scipy 1.18.1, polars 2.0.0) installed with `uv pip install --python-platform x86_64-manylinux_2_28 --target <scratch>` and run by the python3 (3.12.3) of WSL Ubuntu 24.04, against the same code on Windows (the three severity files, tiny baseline and demo):

| file | tiny baseline | demo |
| --- | --- | --- |
| `severity_parameters.csv` | byte equal (largest difference 0) | byte equal (0) |
| `severity_fits.csv` | byte equal (0) | byte equal (0) |
| `severity_plots.csv` | byte equal (0) | byte equal (0) |

(Before: 3.75e-7 on the tiny baseline, 9.6e-6, 1.2e-7 and 4.1e-7 on the demo.) The Windows run was repeated with `OPENBLAS_CORETYPE=Sandybridge` and `Nehalem`: the three files stay byte equal to the default kernel on both runs, which is the nearest stand-in for the other CPU of the CI runner. All three therefore return to hash comparison. The tiny baseline is equal in every output file; the demo differs in `measures.csv` and `reserve_range.csv` (tier A, 3.7e-15, known since 0626 and in no golden) and, **found now and not part of this item**, in one cell of `diagnostics.csv`: the MT19 row `NON_PROPORTIONAL_HAZARDS` carries a p-value (2.1e-12) at 2.2e-14 relative difference between Windows and Linux, because the MT19 rows are not among `ROUNDED_METHODS` of the ten-digit rule (0626) that P27 wired in. The golden baseline is unaffected (the p-value there is not that small); the owner may add MT19 to the rule. UNVERIFIED: the CI runner itself (another CPU and libm than the WSL machine); a cell can still land on the other side of a ten-digit rounding boundary with the odds of 0626.

## Consequences
- Run ids move once (MT17's version is in the specification list): see 0364 for the ids and the diff.
- The golden copy stores hashes for the three files, so a later change of a fit shows as a changed hash and size, not as a changed cell; `just golden` rewrites it, and the diff to read is `tests/report/golden/baseline_tiny.json`.
- New tests: the analytic information against Richardson finite differences of the log-likelihood (all four families, with and without truncation, and seven shapes of the generalised Pareto including 0 and 1e-8), the exponential limit in closed form, the series against the closed form at the switch, a Pareto II information equal to the generalised Pareto one moved by the Jacobian, the single Pareto II fit at the root of its score, and the two standard-error tests tightened from 1e-5 to 1e-10/1e-12.
