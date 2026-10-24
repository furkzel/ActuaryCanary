# 0271 — Reference values of the over-dispersed Poisson bootstrap

## Context
MT11 compares against the chainladder sampler. That sampler differs from the spec: it draws parameter error only, centres the residual pool and by default adjusts residuals with the hat matrix. The spec has gamma process error, no centring and the factor sqrt(n/(n−p)).

## Decision
- Deterministic parts (scale parameter, fitted increments, unscaled and adjusted residuals) are computed with numpy from the spec formulas; the scale parameter equals the package's with `hat_adj=False` to 1e-9 (RAA 983.635, GenIns 52,601.36).
- Simulation rows: the package with `hat_adj=False`, seed 42 and 10,000 simulations gives the total reserve without process error. Process error is added by the script (numpy gamma, sign restored) with the same seed; those rows are labelled "derived". An analytic standard deviation sqrt(var + phi × mean) is frozen beside the simulated one.
- The Monte Carlo tolerance of each statistic is three times its relative standard deviation over 30 other seeds of the same size, written in `rel_tol`. On RAA the process-error standard deviation is heavy tailed (cancelling cell means in rare simulations, about one in 100,000) and carries a tolerance of 0.56; compare percentiles there.

## Consequences
- A bootstrap built to the spec will not equal the package row for row; it is tested against the bounds. P26 decides whether the residual pool is centred.
- The GenIns scale parameter 52,601 and the GenIns reserve 18,680,856 agree with figures recalled from the literature; the originals were not opened (UNVERIFIED).
