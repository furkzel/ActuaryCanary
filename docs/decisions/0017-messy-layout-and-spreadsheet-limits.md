# 0017 — Messy layout against CV07, and spreadsheet limits

## Context
The work item asks the `messy_headers` scenario for extra title rows. CV07 says "header in the first non-empty row", so a title row above the header contradicts the specification. Separately, a worksheet holds at most 1,048,576 rows, and the `large` size has more policies and premium transactions than that.

## Decision
- The title rows are written as the work item asks (1 to 3 rows, in `messy_headers` only). The row where the header sits is recorded in `truth/layout.csv`. The conflict with CV07 is left for the owner: either CV07 is relaxed (the recogniser looks for the header row) or `title_rows` is set to 0 in `messy_headers.yaml`. No specification was changed.
- Cells that mix real dates and text dates are read by the calamine engine as text for the whole column (a real date arrives as `2022-01-31 00:00:00`). Readers must parse text dates; the formats used are in `truth/date_formats.csv`.
- A feed that does not fit one worksheet is written as parquet only (`canonical/`), the run says so, and `manifest.yaml` lists it under `spreadsheets_skipped`. Baseline `large` writes `claim_valuations` (994,821 rows), `claims`, `expenses` and `market` as spreadsheets; `policies` and `premiums` are parquet only. Nothing is split over several worksheets, because CV07 allows one table per sheet.

## Consequences
- The recognition work item can score header-row detection and date parsing directly from the truth files.
- A reader test of `large` needs the parquet files for two feeds; only the tiny and medium sizes are complete spreadsheet sets.
