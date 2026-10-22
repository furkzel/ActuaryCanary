# 0042 — Timing of future payments in the inflation-adjusted chain ladder (MT07)

## Context
MT07 re-inflates each future payment from the middle of its development period and says nothing on the payment of a tail factor.

## Decision
- Every origin's latest cell lies at the cut-off (MT01), so future period s of every origin runs from the month end s − 1 development periods after the cut-off (exclusive) to the month end s periods after it. Its middle is the start plus half the days of the period; years are days / 365.25 from the value date.
- With a tail factor other than 1, the tail's payment falls in the period after the last development age.
- Nominal paid at the cut-off comes from the nominal triangle of the same claims (constant development rate); the nominal ultimate is that plus the re-inflated unpaid.
- The adjusted triangle is built by structures on the INFLATION_ADJUSTED basis (CV02, record 0033) and passed to the method as an array. The nominal triangle, when given, only feeds the factor comparison (nominal over adjusted factor per column).

## Consequences
- The 50 per cent inflation fixture gives back its real pattern and the hand-computed nominal unpaid at 30 per cent to 1e-9.
- Cash flows by future calendar period are given on both price bases.
