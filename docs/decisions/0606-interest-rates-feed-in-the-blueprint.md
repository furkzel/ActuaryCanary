# 0606 — Interest rates are a separate feed in blueprint section 4.3

## Context
Record 0201 made interest rates and yield curves their own concept, `interest_rates`, with one rate per curve, date and tenor, and asked for the blueprint to say so. Blueprint 4.3 still listed INTEREST_RATE and YIELD_CURVE as classes of the market series.

## Decision
Chosen by the owner on 2026-10-24: interest rates are a separate feed. Section 4.3 is edited: the market series keep FX_RATE and PRICE_INDEX, and a new row, Interest rates, gives the grain, key, core fields and classes of the `interest_rates` concept.

## Consequences
- The blueprint now agrees with `spec/data/interest_rates.yaml` and with `market.yaml`, which has four kinds and no rate kinds.
- CV10 reads only `interest_rates`. Section 18.2 and the rest of the blueprint are not changed by this record.
