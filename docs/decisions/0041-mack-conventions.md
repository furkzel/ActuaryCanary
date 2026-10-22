# 0041 — Conventions of the Mack standard error (MT06)

## Context
MT06 fixes the formulas but leaves a few cases open: link ratios with a zero denominator, origins with a zero latest value, and which chain ladder the variance belongs to.

## Decision
- Mack always fits its own chain ladder: volume-weighted, all diagonals, no exclusions, no selected factors, tail 1. A different selection gets the Mack CV applied to its reserve, labelled "Mack CV applied to selected reserve" (record 0011).
- sigma²(j) uses the usable link ratios with a positive denominator, and n(j) counts them. Columns with fewer than two are extrapolated in order with Mack's rule, so such a column may use an extrapolated one before it. S(k) sums C(i, k) over the usable origins, zero cells included.
- An origin with a zero latest value has standard error 0 (its ultimate is 0 and MT02 flags it).
- Lognormal quantities are not given where the reserve is not positive or the standard error is 0; where given they are labelled "lognormal approximation with the Mack mean and standard error".

## Consequences
- Standard errors match the frozen chainladder values of raa, genins and clrd_wkcomp to about 1e-14.
- 4 x 4 triangles (the examples) have two estimable columns, so Mack does not run there: "too few link ratios to estimate variance".
