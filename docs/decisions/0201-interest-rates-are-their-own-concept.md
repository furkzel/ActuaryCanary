# 0201 — Interest rates and yield curves are their own concept

## Context
Blueprint 4.3 lists INTEREST_RATE (with tenor) and YIELD_CURVE as classes of the market series, and P20 asks to extend the market concept with them. `market.yaml` is outside the files this item may change, and P21 amends its data rules at the same time. Market rows are keyed by series, kind and date; a curve point also needs a tenor and a rate convention (spot, par or forward; compounding), which FX rates and price indices do not have.

## Decision
Chosen by the owner on 2026-10-23: a new draft concept `interest_rates`, with one rate per curve, date and tenor. Its fields are curve_id, date, tenor_months, rate, rate_type (SPOT, PAR, FORWARD), compounding (ANNUAL, CONTINUOUS, SIMPLE), currency and source, plus rules DV-IRT-01 to 09. A single rate series is a curve with one tenor. CV10 reads only this concept.

## Consequences
- `market` keeps its four kinds; no conflict with P21.
- The file name is `interest_rates.xlsx`. A sheet in `market.xlsx` with curve columns is still recognised by its columns, as any table is.
- Blueprint 4.3 should say that interest rates have their own feed. That is the owner's edit to make; this item does not touch the blueprint.
