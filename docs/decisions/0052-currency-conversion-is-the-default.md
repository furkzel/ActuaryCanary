# 0052 — Currency conversion is the default whenever market data is present

## Context
Decision 0034 made the run read market data only when `--currency` was given, so a default run reported foreign-currency claims apart. The owner asked for conversion to be the default and for `--currency` to remain the way to choose the currency.

## Decision
- This record reverses 0034 on that point. `RunSettings.use_market` defaults to true: when a sheet is recognised as market data, foreign currencies are converted into the reporting currency by CV01 (the constant development rate for triangles and development views; the flow and stock rules for premium, expenses and claim flows).
- `--currency TRY` only chooses the reporting currency (default from `project.yaml`); it no longer switches conversion on. Without a market sheet nothing is converted, amounts in other currencies are reported apart, and the manifest records `currency_conversion: none`.
- The manifest records `currency_conversion: market` only when a market sheet was actually read. The inflation-adjusted basis still needs a market sheet and stops with a message without one.
- The other points of 0034 stand: `--value inflation-adjusted`, `--basis`, `--origin-axis`, `--value-date`, `--price-index`.

## Consequences
- Run ids of earlier runs of folders with a market sheet change (settings and inputs), as expected.
- Premium booked before the first date of the market data has no rate and is left out and listed (CV01); the baseline starts its series in 2016.
