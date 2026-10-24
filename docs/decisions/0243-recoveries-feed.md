# 0243 — Recoveries feed: one booking per recovery event

## Context
The simulation gives each claim at most one subrogation and one salvage recovery, with the day it is received, and shows them as `subrogation_to_date` and `salvage_to_date`. The recoveries concept (P20) wants bookings.

## Decision
- One row per recovery event received up to the cut-off: type RECOVERY_SUBROGATION or RECOVERY_SALVAGE, a positive amount, the claim's currency, booked on the day it is received. The cumulative bookings of a claim at any valuation date equal the to-date fields at the month end that follows (test, all valuations).
- `counterparty_type`: salvage is SALVAGE_BUYER; subrogation is INSURER for 70 per cent and OTHER_PARTY for 30 per cent, drawn from the stream `phase2/recoveries/counterparty`.
- `expected_amount` is not written. An expectation would need a model of what an insurer expects, and the simulation has none.
- Truth `recoveries_truth.csv`: every recovery of the simulated world, those after the cut-off included, with the days after the last payment of the claim and whether it was booked by the cut-off.

## Consequences
- For the recoveries and expenses item: RC03 (delay) and RC04 (development) can be scored against the truth. The platform's derivation from the to-date fields (record 0203) and the feed give the same flows.
