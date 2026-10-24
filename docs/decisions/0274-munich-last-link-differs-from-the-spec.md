# 0274 — Munich chain ladder: the package and the spec text differ

## Context
MT12 estimates lambda as a slope through the origin "over all cells with both residuals". Implemented that way with numpy, the Quarg–Mack sample triangles give lambda paid 0.6130 and incurred 0.4208. The chainladder package gives 0.6360 and 0.4362. The package is reproduced exactly (1e-12) when the last link, which rests on one origin and on an extrapolated variance parameter, is left out of the regressions.

## Decision
The frozen ultimates and lambdas follow the package, because the spec's benchmark is "match the package" (1e-6). Both lambdas are frozen: `lambda_all_links` (spec text) and `lambda_without_last_link` (package). The spec is not changed here (outside the allowed area).

## Consequences
- The owner or P24 decides which rule MT12 states; the likely amendment is "the last link is left out" with the reason above. Until then P24 cannot satisfy both the text and the benchmark.
- Published figures of Quarg and Mack (2004) were not opened (UNVERIFIED).
