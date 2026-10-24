# 0245 — Interest-rate curves follow the inflation path of the scenario

## Context
Discounting (CV10) needs curves, and the blueprint asks for curves consistent with each scenario's inflation path.

## Decision
- Three curves, `TRY_GOV`, `USD_TSY` and `EUR_SWAP`: spot rates with annual compounding, tenors 3, 12, 24, 36, 60, 84 and 120 months, at every month end from the first valuation month to the cut-off (1,008 rows at tiny, 2,520 at medium).
- The spot rate to tenor T at the end of month t is the geometric average annual inflation the scenario produces over the T years after t (its own price path for TRY, the constant foreign inflation of the exchange-rate series for USD and EUR; after the last listed year the path continues at the future rate), plus a real rate of 1.5 per cent, plus a term premium of 1 per cent times (1 − exp(−T/5)), plus a first-order autoregressive shock (standard deviation 0.2 per cent, persistence 0.9, a stream of its own) that fades with the tenor. The parts are in `truth/interest_rates_truth.csv` and add up to the rate (test).
- The tenors must include 12 months: the life book credits its funds at the one-year TRY rate less 1 per cent.

## Consequences
- Rates are high when inflation is (TRY above 60 per cent in 2022) and the curve inverts when the path falls, so the forward rates of DV-IRT-09 (an INFO rule: a change of more than 0.10 between adjacent tenors) are flagged on those dates (30 times at tiny). That is the scenario, not a fault.
- Perfect foresight of the inflation path is a simplification. A discounting method must not be scored on the premise that the future is known.
