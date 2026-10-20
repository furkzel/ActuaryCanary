# 0012 — Order of operations on the inflation-adjusted basis

## Context
The price index belongs to the reporting currency, while development views convert with one constant exchange rate (CV01). Combined in the wrong order, foreign-currency amounts would be deflated by a domestic index they never experienced. Re-inflating projections needs a future inflation rate the data cannot supply.

## Decision
- On the INFLATION_ADJUSTED basis, each amount is first converted to the reporting currency at its own date's rate (flow or stock rule of CV01), then restated with the index; the constant development rate is not used on this basis (CV02).
- Index values are monthly; a missing month takes the latest earlier month and is flagged.
- Projections on this basis are at value-date prices. Nominal results are produced only with a future inflation assumption from the user, applied at the middle of each future development period (MT07). Without it, only value-date-price results are shown, labelled.

## Consequences
- No invented future inflation enters any figure.
- Nominal and inflation-adjusted development views of foreign-currency business differ by design; the report labels both.
