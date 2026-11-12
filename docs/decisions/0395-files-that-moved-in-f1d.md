# 0395 — Scenario files that moved in F1d

## Context
Every file of every scenario at tiny was hashed before the item (record 0391) and again after each of the two generator changes.

## Stage 1 (record 0392): premium movements
In every scenario that has treaties: `canonical/premiums.parquet`, `canonical/reinsurance_transactions.parquet`, `premiums.xlsx`, `reinsurance_transactions.xlsx`, `manifest.yaml`, `truth/layout.csv`, `truth/layout_phase2.csv`. In `messy_headers` and `messy_incremental` also `truth/anomalies.csv`, `truth/injected_faults.csv`, `truth/value_map.csv`, `truth/value_map_phase2.csv` (placed on the rows of the premium file). Cause: ceded premium rows booked before the first listed contract period are no longer written. No claims file and no ceded truth file moved.

## Stage 2 (record 0393): nil-closing reserve
Only `demo` moved, with the files that hold case reserves: `canonical/claim_valuations.parquet`, `claim_valuations.xlsx` (case reserve of a nil claim above its cap), `canonical/ledger.parquet`, `ledger.xlsx` (the ledger books the reserves), `truth/ibnr_by_valuation.csv`, `truth/development_pattern.csv` (incurred columns), `truth/ledger_gaps.csv` (derived from the ledger), `manifest.yaml` (digests). Cause: the tiny demo has a nil-closing claim above the MOTOR_TPL tail threshold. Every other scenario at tiny has none above its cap: not a single file moved. `truth/ultimates.csv` did not move at tiny (reserve at cut-off unchanged there).

Nothing else moved; no file outside these causes changed.

## Pins
`tests/synthetic/tiny_sha256_f1a.yaml` (slow test, written, not run) was renewed for the nine digests of `baseline` and `messy_headers` that stage 1 moved.
