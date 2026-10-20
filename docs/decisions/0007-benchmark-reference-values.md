# 0007 — Benchmark reference values and hand fixtures

## Context
Chain ladder, Bornhuetter–Ferguson, Cape Cod and Mack need fixed reference numbers (blueprint 9.1, 13.2). Tests must not import an external package at run time.

## Decision
- Triangles `raa` and `genins` are exported from the chainladder sample data to `tests/benchmarks/<name>/triangle.csv`; reference values are computed once and frozen in `expected.yaml` with package version and exact calls.
- Mack standard errors use `sigma_interpolation='mack'` (last sigma extrapolated as in Mack 1993), not the package default (log-linear), because the specification follows Mack 1993. Tail factor is 1.0.
- The values are labelled `reference_implementation`. Published figures were not opened in a source, so they are labelled UNVERIFIED. For RAA the total reserve (52,135) and total standard error (26,909) agree with the figures recalled from Mack (1993); this is not a verification.
- Hand fixtures (`tests/fixtures/hand/`) use small round numbers; each result carries a one-line derivation. Bornhuetter–Ferguson uses a stated prior loss ratio of 0.60; Cape Cod has no decay and no trend. Both were cross-checked against chainladder (agreement to 4 decimals).
- `checked_by_owner: false` in every `expected.yaml` until the owner checks the numbers in a spreadsheet.

## Consequences
- Method tests compare against files only; chainladder stays a development tool.
- Changing a convention (tail, averaging, sigma rule) needs a new record and regenerated files.
