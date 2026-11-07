# 0302 — Severity and extremes: conventions chosen where MT17 and MT18 are silent

## Context
MT17 1.0.0 and MT18 1.0.0 fix the algorithms, parameters and failure modes. Building them meant choosing in a few places where the text leaves room. None of these changes a number the specifications fix; each is tested. The owner may want some of them written into the specifications (listed at the end).

## Decision
Input and groups
- A size comes from `size_classes` of CV08. A claim is non-nil when its status is not CLOSED_NIL and its size is above zero. `closed` keeps status CLOSED; `all_non_nil` keeps every non-nil claim at its incurred. Rows are sorted by claim_id before any draw or fit; groups are segment by line, a missing one is UNKNOWN.
- MT17 drops claims with an event code (default); `exclude_catastrophes` false keeps them as ordinary claims. MT18 replaces the claims of one event (within a group) by one size, their sum, dated in the earliest origin year of the event.

MT17
- Maximum likelihood is exact where it can be: lognormal in closed form, gamma by Newton on the shape, Weibull by Newton on the shape (both safeguarded by a bracket), Pareto II as the generalised Pareto with xi above zero. With a truncation point d the likelihood is conditioned on X above d and maximised numerically; sizes at or below d are left out and the group count is of the sizes above d.
- A Pareto II whose likelihood still rises towards an infinite shape (the sizes are lighter-tailed than any Pareto II; the limit is the exponential) ends at the edge of the search (shape about 1e6): it counts as "did not converge", is left out of selection with a WARNING that says why, and keeps its log-likelihood and AIC in the table. A gamma, Weibull or truncated fit at the edge is treated the same way.
- Goodness of fit: when a group has more than `gof_max_claims`, the subsample is drawn first and its parameters are re-estimated on it, so that the observed D and A^2 are taken against the same kind of fit as the bootstrap statistics (each bootstrap sample is refitted). The likelihood, standard errors, AIC and BIC use all claims. p = (1 + number of bootstrap statistics at or above the observed) / (B + 1); bootstrap samples whose refit fails are dropped and the number used is in the table. A family is rejected when its Anderson–Darling p-value is below `significance`; Kolmogorov–Smirnov is reported and does not reject.
- Ranks by AIC and BIC are given to the families that converged. Quantiles, limited expected values and layer costs are those of the fitted distribution F of all losses; under truncation they are not conditional on X above d.
- `limits`: the sorted limits cut layers from zero; each row gives E[X ^ L] at the upper limit and the cost of the layer from the previous limit, and a last row for the part above the highest limit (its limited-expected-value column is the mean, empty when the mean is infinite).
- Trend of sizes: least squares of ln(size) on the origin year over claims with a year; annual change, standard error, p-value; a WARNING when p is below 0.01, and THIN_EVIDENCE when there are fewer than 8 origin years (as in the triangle methods).

MT18
- Generalised Pareto estimation profiles over k = xi / sigma (closed-form xi for each k), searches a grid and refines by golden section, for all bootstrap samples at once; single fits finish with the root of the score. It reproduces the frozen scipy values within 1e-5 relative and its likelihood is the same or higher.
- Candidates: empirical quantiles of the sizes by linear interpolation; an excess is a size strictly above u; a candidate with fewer than `min_exceedances` excesses is not tried. Candidates whose fit has xi below -0.5 or no interior maximum are skipped, marked and left out of ForwardStop. ForwardStop runs over the tried candidates from the lowest threshold. If k-hat equals the number of candidates (every fit rejected) the highest tried candidate is shown with the WARNING ALL_REJECTED; the spec names no threshold for this case.
- Tail quantiles are NaN for a probability below the exceedance level 1 - N_u/n; return levels are NaN when N_u T / h is below 1; expected shortfall needs xi below 1. h is the span of origin years in the group (last minus first plus one), also those without exceedances; the `years` option replaces it. Without origin years no return level is given (INFO).
- The profile interval of xi is searched outwards from the estimate in steps that double; a side not closed before xi reaches -0.999 or after twelve doublings is NaN.
- Exceedances by year: a chi-square dispersion test of the yearly counts (variance over mean, years minus one degrees of freedom) and the log-linear trend of the excess sizes, both warned at p below 0.01.

Seeds and register
- The run seed is 1 (`SEED`) and is recorded in each result and in `randomness()`. Every group and purpose has its own generator, `SeedSequence([seed, crc32(group key), stream])`, so results do not depend on the order of groups: stream 1 is the MT17 subsample, 10 + family index its bootstrap, 100 + candidate index the MT18 bootstrap.
- The assumptions register takes, for MT17: `claims_used`, `truncation_point`, `exclude_catastrophes`, `significance` and `limit` (one entry per limit, the target being the limit); for MT18: `claims_used`, `fdr_level`, `min_exceedances` (a whole number of at least 10). A user entry keeps its who, when and why; a value the run passes differently from the default is labelled "run settings".

## Consequences
- Proposed additions to the specifications, for the owner to accept in a later amendment: the all-rejected rule of MT18; the definition of h; the NaN rules of the tail quantile and the return level; the refit on the subsample and the p-value formula of MT17; the meaning of `limits` as layers; ground-up quantiles under truncation; a Pareto II at the edge of the search as "did not converge".
- Wiring (P25b) reads the register scope per group and measure and passes the options through `mt17_judged` and `mt18_judged`; the entries in force go to the assumptions register of the report.
