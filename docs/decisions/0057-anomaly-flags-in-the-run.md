# 0057 — Anomaly flags in the run (M06)

## Context
MT08 (robust z-score) and MT09 (isolation forest) exist as methods and produce frames of different shapes. The owner asked for one file with each flag, its reason, its score and its source rows.

## Decision
- `canary run` runs both on the canonical claim valuations and claims with the constant development rates (CV01) and writes `anomalies.csv`: method, claim, segment, line, valuation date, variable, value, score, threshold, reason, file, sheet and spreadsheet rows. MT08 flags are payments or case-reserve movements (value in the reporting currency, score the robust z, one row); MT09 flags are claims (score the isolation score, rows all valuation rows of the claim, as spans such as `9;13;22`).
- Nothing is tuned: thresholds, group sizes, contamination and the seed are P08's (0043) and are written into the manifest settings (`methods`), the seed also under `randomness`.
- What limited the methods goes into the module outcome: values without a development rate, groups with a flag rate above 5 per cent (the group may mix populations), groups too small to score. M06 is then `limited`.
- The flags are leads for a reviewer. On baseline tiny and medium the recall of the injected faults is below the specified tolerance (MT08 0 of 8, MT09 AUC 0.63; expected failures, 0043).

## Consequences
- On baseline tiny MT08 flags 113 values, mostly reserve movements of MOTOR_OD, whose group rate is 40 per cent: the warning says so; the grouping of the specification does not separate case-reserve steps from outliers.
