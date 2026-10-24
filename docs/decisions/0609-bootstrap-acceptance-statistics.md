# 0609 — Over-dispersed Poisson bootstrap: acceptance statistics and process error

## Context
Record 0271 froze the bootstrap references with Monte Carlo tolerances. The standard deviation of the total reserve is heavy tailed on RAA (rare simulations with cell means of both signs that cancel in the total but not in the process error; tolerance 0.56), so a 5 per cent standard deviation criterion, as MT11 had it, cannot be met reliably. The reference also draws process error in one form only.

## Decision
Chosen by the owner on 2026-10-24: the acceptance statistics of the benchmark are the median, the 75th and the 95th percentile of the total reserve distribution, each within the Monte Carlo tolerance of its row. The standard deviation is reported, and tested only with the wide tolerance that the benchmark already carries; it is not a pass criterion on its own. Process error is the gamma form of the benchmark script: shape |m| / phi and scale phi for a future increment with mean m, the sign of m kept. MT11 is edited to say so (version 0.2.0, still a draft). The 50th percentile is a new row of the frozen references (`p50` of both simulation quantities, both triangles), produced by the same script with the same seed; no other value moved.

## Consequences
- The mean criterion (within 2 per cent of the chain-ladder reserve) stays as drafted.
- Whether the residual pool is centred (0271) is still open for P26.
- The option `odp` for the process distribution has no reference and stays untested until one is frozen.
