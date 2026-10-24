# 0276 — Tail curve references: link number and stopping rule

## Context
The package fits ln(f − 1) against the link number (1 for 12–24 months) for the exponential curve and against its logarithm for the inverse power curve, and multiplies 100 extension periods. The spec uses the age at the start of the link in years, which is the same number for annual data, and stops when f − 1 falls below 1e-4 or after 100 years.

## Decision
For RAA and GenIns both curves are frozen with a, b (spec sign: the inverse power b is minus the package slope), R² on the log scale, the fitted factors, the package tail (100 periods) and the tail by the spec rule computed from a and b. They differ: exponential RAA 1.00944 against 1.00922, inverse power RAA 1.10148 against 1.09914 (68 periods before the stop), exponential GenIns 1.02950 against 1.02934. For the GenIns inverse power curve the 100-period limit comes before 1e-4 and both tails are 1.29243.

## Consequences
- The 1e-6 benchmark of MT14 can be met on the rows `package_100_periods` with a 100-period extension; the stopping rule of the spec is tested on the other row. The owner may prefer to align the spec with the package.
- The fit uses factors above 1.00001 (the package threshold); the spec says "above 1". No sample factor lies between.
