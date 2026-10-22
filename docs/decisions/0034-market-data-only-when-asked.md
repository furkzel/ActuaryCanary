# 0034 — Market data is read only when the run asks for it

## Context
Since P07 the market feed can convert foreign currencies (CV01) and restate to a value date (CV02). The default run of P04 to P06 does not read market data, uses only amounts in the reporting currency and reports the rest apart (0024). Its tests, run ids and manifests describe exactly that.

## Decision
- `canary run --currency TRY` (setting `use_market`) reads the market sheets and converts foreign currencies into the reporting currency with the constant development rate; `--value inflation-adjusted` always reads them. Without either option the run is as before: no market file is opened and foreign-currency amounts are reported apart.
- `--value inflation-adjusted` without a market sheet stops with a message; `--currency` without one converts nothing and reports every foreign amount apart (CV01).
- `--basis gross|ceded|net`, `--origin-axis accident|report|underwriting|first_valuation`, `--value-date` and `--price-index` are options; defaults are GROSS, accident, the cut-off and the project index.
- Policies are read only for the underwriting axis. Premiums, expenses and policies are not read by `canary run` yet: the premium structures (earned and unearned premium, earned exposure) are functions, used by the measures of later items.
- The settings record of the manifest holds the bases and the new settings, which are run id determinants like every setting; the resolved value date and development rate date are recorded next to them, as the cut-off is (0023).

## Consequences
- Nothing in the earlier runs changed except their run ids (new settings fields).
- Making conversion the default when a market file exists is one line in the CLI and a different default in `RunSettings`; the owner decides (see HANDOVER).
