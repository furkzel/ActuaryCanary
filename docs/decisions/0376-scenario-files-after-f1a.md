# 0376 — Scenario files after F1a

## Context
Record 0370 holds the SHA-256 (first 16 hex digits) of the 440 files of the eight scenarios at size tiny before F1a. The same set was written again after stage 3 and compared (checked 2026-11-10).

## Decision / findings
No file disappeared. 73 files are new, 122 moved, every other file (policies, claims, premiums, market, interest rates, the reinsurance and recovery feeds, the life feeds, all reference tables, the other truth files) has the same bytes; the unmoved count per scenario is baseline 37, demo 35, high_inflation 37, large_loss 37, life_book 49, messy_headers 49, reinsurance_heavy 37, reserve_bias_change 37.
- **New, 73.** `truth/claim_size_index.csv` in each of the 8 scenarios (stage 2, record 0373); the 65 files of the new scenario `messy_incremental` (stage 3, record 0374).
- **Moved, in all 8 scenarios, cause stage 2 (group life claims at base-date prices moved by the price index on the loss day, 0373):** `claim_valuations.xlsx` and `canonical/claim_valuations.parquet` (amounts of GROUP_TERM_LIFE claims); `expenses.xlsx` and `canonical/expenses.parquet` (allocated expense is a share of those payments; 25 rows changed in baseline, all ENT_C / GROUP_TERM_LIFE); `phase2/ledger.xlsx`, `canonical/ledger.parquet`, `truth/ledger_differences.csv`, `truth/ledger_gaps.csv` (the ledger is built from claims paid and reserves; 291 baseline rows changed, all ENT_C); `truth/ultimates.csv`, `truth/ibnr_by_valuation.csv`, `truth/frequency_severity.csv` (mean base severity of the line), `truth/inflation.csv` (`claims_index_GROUP_TERM_LIFE` from 1 to CPI / 100); `truth/scenario.yaml` (the key `sum_insured_index` of the line).
- **Moved, in all 8 scenarios, cause stage 1 (0371) and stage 2:** `truth/development_pattern.csv` (two new columns, `paid_share_nominal`, `incurred_share_nominal`; group life values from stage 2).
- **Moved, in demo only:** `truth/injected_faults.csv` and `truth/anomalies.csv`: the extreme payment of claim 00000033 is a multiple of that group life claim's amount (33,171,598.48 became 42,341,507.76); no fault was added, moved or removed (stage 2).
- **Moved, in all 8 scenarios, derived:** `manifest.yaml` (it lists the hashes of the files above).
- **`messy_headers`:** no file of the first six feeds moved except by the group life amounts above; `messy_incremental` differs from the new `messy_headers` in `claim_valuations.xlsx`, `truth/scenario.yaml` and `manifest.yaml` only (0374).

## Consequences
- Nothing moved that is not explained by stages 1 to 3. The committed fixtures under `tests/fixtures/synthetic/` and the files of `examples/` are older than the generator until the gate refreshes them (`tiny_sha256_v1.yaml` stays as it was; its check reads the committed files).
- The slow test that held the 26 files of the tiny `baseline` and `messy_headers` to the version 1.0 hashes (`tests/fixtures/synthetic/tiny_sha256_v1.yaml`, record 0241) had a premise the item changed: 14 of the 26 files of each scenario moved on purpose (stage 2). It is rewritten to hold the same 26 files to `tests/synthetic/tiny_sha256_f1a.yaml`, hashes taken from the run compared above; the version 1.0 file stays as history. The rewritten test was written against the hashes of that run and not run (slow).
