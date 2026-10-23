# 0204 — Discounting conventions

## Context
Blueprint 5.3 and 7.2 name a DISCOUNTED value basis "at a stated curve" for phase 2 and leave the details open: interpolation, cash-flow timing, discount date and the default curve.

## Decision (proposed, draft, CV10)
- **Discount date.** The cut-off by default.
- **Default curve.** None. The user names a curve in the reporting currency in the assumptions register. Without one, DISCOUNTED is unavailable and says so, so no curve is ever invented, just as CV01 never invents an FX rate.
- **Rates.** Every rate type and compounding is turned into continuously compounded zero rates. Par rates are bootstrapped with annual coupons; one-year forwards are accumulated.
- **Interpolation.** Linear in z(t)·t, which gives piecewise-constant forwards and positive discount factors. The curve is flat before its first tenor and holds the last forward flat beyond its last tenor. Smith–Wilson to an ultimate forward rate is not specified.
- **Timing.** Mid-period by default, the convention of MT07 (record 0042). Start or end of period is an option.
- **Inflation.** Only nominal cash flows are discounted. INFLATION_ADJUSTED and DISCOUNTED are not combined, because no real curve is read.
- **Tail cash flows.** They follow the shape of the MT14 curve, or are spread evenly over five years when the tail is only a number.

## Consequences
- Nothing in the past is discounted. RS04 and RS05 are the discounted measures, in reporting currency only.
- In high-rate markets the discount effect is large, so the report always shows it beside the nominal figure.
