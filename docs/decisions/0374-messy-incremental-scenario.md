# 0374 — The scenario messy_incremental

## Context
Records 0223 and 0611: the reader accumulates claim amounts written per period, detects them from the values, and the generator has no scenario that writes them. The owner chose a separate scenario so that the bytes of `messy_headers` never change.

## Decision
- `synthetic/scenarios/messy_incremental.yaml` extends `messy_headers` and sets `messiness.amounts: incremental` (new key, default `to_date`).
- In `claim_valuations` the five cumulative fields (`paid_to_date`, `subrogation_to_date`, `salvage_to_date`, `expense_allocated_to_date`, `ceded_paid_to_date`) are written as what each row adds: per claim in date order (ties in row order), each amount minus the last non-empty amount before it. An empty amount stays empty. Reserves are stocks and stay as they are. A row that repeats an earlier row exactly keeps that row's increments, so a repeated row stays an exact duplicate and the reader's duplicate removal still works. A fault that makes a cumulative amount fall appears as a negative increment.
- Everything else is written as in `messy_headers` (same seed, so the same headers, title rows, text dates, labels and personal-data columns). `canonical/claim_valuations.parquet` and the truth hold the cumulative amounts: they are what a reader has to recover.
- `truth/scenario.yaml` leaves the new key out while it is `to_date`, so the dump of every earlier scenario stays byte for byte.

## Consequences
- Against `messy_headers` tiny (measured) only `claim_valuations.xlsx`, `truth/scenario.yaml` (scenario name and the new key) and `manifest.yaml` differ. The existing reader detects per-period amounts on it and, after accumulation, gives the claim amounts of `messy_headers` to within half a cent (test on tiny).
- No change to `io/`, `recognition/amounts.py` or the canonical step was needed.
