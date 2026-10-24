# 0277 — Benktander counting, premium choices and the maturity pattern

## Context
The package counts `n_iters = 1` as Bornhuetter–Ferguson; the spec's k = 0 is Bornhuetter–Ferguson and k = 1 the classical Benktander. The RAA and GenIns samples carry no premium. MT16 says severity is trended from origins with "p_i ≥ 0.9" without naming the pattern p is taken from.

## Decision
- Spec k equals package `n_iters − 1`; the freeze script asserts that the package ultimates equal the spec formulas to 1e-9.
- Constant premium and prior loss ratio are chosen for the test (RAA 30,000 and 0.8; GenIns 6,000,000 and 0.75) and written in the manifest; they are not market figures. The Mack credibility rows are derived by the script, not the package.
- MT16 fixture: p comes from the incurred chain ladder (the severity measure), the trend is fitted on the mature origins, catastrophe claims are absent and amounts are nominal.

## Consequences
- P24 tests the iteration count against the spec definition, not against the package argument.
- A different maturity pattern for MT16 would change which origins are mature; the spec should name it.
