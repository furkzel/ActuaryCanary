# 0326 — M12 writes files of its own and leaves `reserve_range.csv` and `cash_flows.csv` as they are

## Context
The M12 spec lists `reserve_distribution.parquet`, `reserve_range.csv` and `cash_flows.csv`. M04 already writes a `reserve_range.csv` (RS03 per line, with tier A) and a `cash_flows.csv` (MT07), and MT11 writes its distribution per line as `bootstrap_distribution_<segment>_<line>.parquet`. The item may change only outputs it adds.

## Decision
- The files of M12 are `risk_measures.csv` (the Mack lognormal and the bootstrap range of RS03 and RS05, and the expected present value of RS04, per origin, line and all lines, nominal and discounted, with estimator, label and notes), `risk_cash_flows.csv` (expected and simulated cash flows by calendar period, with factors), `risk_distribution.parquet` (the simulated reserve of each line and of all lines, nominal and discounted, one row per simulation; written when a bootstrap ran) and `discount_curve.csv` (the points of the curve used; written when one is). All go through the shared writer (10 significant digits, CV06 1.1.0).
- The M12 spec lists these names (1.1.0). `reserve_range.csv` and `cash_flows.csv` keep their content and name.
- RS04 and RS05 are method outputs through the port (`METHOD_OUTPUTS`), so they reach `measures.csv`, the lineage and `modules.json` like RS03.

## Consequences
- The files of existing runs are unchanged; the golden copy and the examples gain only the new files, the M12 entry and the interest rates in the quality report.
