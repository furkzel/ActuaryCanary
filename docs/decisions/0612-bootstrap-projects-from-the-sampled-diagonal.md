# 0612 — Bootstrap: projection from the pseudo-triangle's own latest diagonal, centred residuals

## Context
Record 0271 left open whether the residual pool is centred, and MT11 0.2.0 projected the future incremental means of each origin from the actual latest cumulative C(i, J_i). The reference package projects from the cumulative of the pseudo-triangle on its latest diagonal and centres the pool. The planner's review of the draft found that the choice of the projection base moves the spread of the parameter error and the calibration of the 95th percentile.

## Decision
MT11 0.3.0:
- The future means are projected from C*(i, J_i), the cumulative of the pseudo-triangle on its latest diagonal. This is the forecast of the refitted model: the row parameters are re-estimated on the pseudo-data, so the forecast starts from the refitted level of each origin.
- New parameter `centre_residuals` (default true): the mean of the pool of adjusted residuals is subtracted before resampling, as the package does. This closes the open question of 0271.
- The benchmark criterion "mean within 2 per cent of the chain-ladder reserve" becomes 3 per cent. The frozen package mean is 1.8 per cent above the chain ladder on RAA, so 2 per cent leaves no room for the Monte Carlo error.
- The notes of the `MT11-*` manifests and the README of the references say that the package projects from the sampled diagonal and centres, and that the spec now does too.

Evidence from the planner's probe scripts (UNVERIFIED until the Monte Carlo test of the bootstrap item reproduces it):
- On RAA the standard deviation of the parameter error alone is about 11.0 thousand when projecting from the actual diagonal and about 17.6 thousand when projecting from the sampled diagonal; the frozen package value is 15.9 thousand.
- On triangles drawn from the over-dispersed Poisson model itself (RAA parameters, 400 triangles, 400 simulations each) the true reserve fell below the simulated 95th percentile in 83 per cent of cases with the actual diagonal and in 92 per cent with the sampled diagonal. The calibration band of the spec (90 to 99 per cent) is met only by the sampled-diagonal forecast.

## Consequences
- A bootstrap built to MT11 0.3.0 is comparable with the package in its design; the differences left are the sampler and the process error, covered by the Monte Carlo tolerances.
- Supersedes the projection base of MT11 0.2.0 and the open item of 0271 and 0609; the acceptance statistics of 0609 stand.
- No reference value moved; no `src/` change. MT11 stays a draft.
