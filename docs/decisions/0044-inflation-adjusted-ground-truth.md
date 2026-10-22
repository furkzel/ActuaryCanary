# 0044 — Ground truth of the inflation-adjusted chain ladder (MT07)

## Context
MT07 asks that the value-date ultimate lie within 5 per cent of "the true ultimate at base-date prices restated to the value date" for accident years with at least three years of development. The truth column `ultimate_base_prices_try` is claim cost before claims inflation at the starting exchange rate; restated with the CPI from 2016-01 to the cut-off it is 0.63 to 6.2 times (baseline) and 0.34 to 9.7 times (high_inflation) the cut-off-price truth per line and accident year, so that reading cannot be the intended one. (The owner was first shown 0.004 for this reading; that figure used the CPI of 2039 and was wrong, the conclusion is the same.)

## Decision
Chosen by the owner on 2026-10-22, after measurement:
- Compared quantity: `ultimate_try_at_cutoff_prices` (every true payment at its spot rate, restated to cut-off prices), summed per line and accident year; accident years with a latest age of 36 months or more; baseline and high_inflation, medium.
- The known effect of the injected amount faults is undone first: each injected spike is subtracted from its row on, and each row with a lowered paid is dropped (carry-forward).
- Named exceptions, tested apart as strict expected failures: MOTOR_TPL 2023 (baseline −15 %, high_inflation −17 %; superimposed inflation of 5 % a year that the CPI misses) and high_inflation MOTOR_TPL 2016 (−5.1 %; payments in the tenth year, tail 1.0). The other 61 accident years are within 5 per cent.

## Consequences
- On high_inflation the nominal chain ladder gives 0.42 to 0.89 of the truth for TPL; the adjusted one 0.95 to 1.02 outside the exceptions.
