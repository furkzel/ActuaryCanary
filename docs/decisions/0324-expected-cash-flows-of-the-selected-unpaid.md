# 0324 — The expected cash flows of the selected unpaid

## Context
RS04 discounts "the selected unpaid with the payment pattern of the paid chain ladder, scaled to the selected unpaid of each origin", with tail flows by CV10. The specs leave the arithmetic open.

## Decision
- The pattern of origin i at its latest column J: the paid chain ladder gives the ultimate U = latest x CDF(J) and the cumulative at column k as U / CDF(k); the expected payment of column k is U (1 / CDF(k) - 1 / CDF(k-1)), in future calendar period k - J (the numbering of MT11). The tail U (1 - 1 / CDF(last)) is paid from the period after the last column.
- The tail is spread by the shape of the fitted tail curve when the chain ladder's tail factor is the one MT14 fitted (the `extension_share` of the curve, trailing periods below 1e-9 of the tail folded away); otherwise evenly over `tail_payment_years / development years` periods (at least one). A tail factor of 1 has no tail flows.
- The flows of an origin are scaled by selected unpaid / chain-ladder reserve so that they add to the selected unpaid (selected ultimate minus paid, RS02; without a selection, the chain-ladder reserve). An origin whose chain-ladder reserve is zero but whose selected unpaid is not (an old year with case reserves in the incurred-based selection) has the selected unpaid in period 1, and a note names it. A negative selected unpaid is scaled and discounted like any flow, and a note names it.
- NET basis: the run's own triangles are net, so the pattern, the ultimate and the selected unpaid are net already; RS04's rule of scaling gross flows by a net-to-gross ratio is not needed and not applied (it would be an approximation of something that exists exactly). The port answers RS04 and RS05 on the reinsurance basis of the run only.
- Timing within a period: `DiscountContext.payment_date` (mid period: start plus half the days, rounded down, the MT07 convention); years are days over 365.25 from the discount date; at or before the discount date the factor is 1.

## Consequences
- `risk_cash_flows.csv` has the expected flows by calendar period, their discount factors and the discounted flows; `risk_measures.csv` has the present value, the nominal and the discount effect per origin, line and all lines.
