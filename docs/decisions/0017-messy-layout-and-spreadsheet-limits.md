# 0017 — Title rows and spreadsheet limits

## Context
The work item asks the `messy_headers` scenario for extra title rows. CV07 first said "header in the first non-empty row"; from version 1.1.0 rows above the header (titles, notes, blank lines) are allowed and the header is the first row that column recognition (AL01) accepts, so there is no conflict. Separately, a worksheet holds at most 1,048,576 rows, and the `large` size has more policies and premium transactions than that.

## Decision
- The title rows are written as the work item asks (1 to 3 rows, in `messy_headers` only). The row where the header sits is recorded in `truth/layout.csv`. CV07 version 1.1.0 allows them; no change to the scenario was needed.
- Cells that mix real dates and text dates are read by the calamine engine as text for the whole column (a real date arrives as `2022-01-31 00:00:00`). Readers must parse text dates; the formats used are in `truth/date_formats.csv`.
- A feed that does not fit one worksheet is written as parquet only (`canonical/`), the run says so, and `manifest.yaml` lists it under `spreadsheets_skipped`. Baseline `large` writes `claim_valuations` (994,821 rows), `claims`, `expenses` and `market` as spreadsheets; `policies` and `premiums` are parquet only. Nothing is split over several worksheets, because CV07 allows one table per sheet. Amended by 0081: a feed that does not fit is written as several workbooks (`<feed>_part1.xlsx`, ...), each with one table, and no feed is parquet only.

## Consequences
- The recognition work item can score header-row detection and date parsing directly from the truth files.
- A reader test of `large` needs the parquet files for two feeds; only the tiny and medium sizes are complete spreadsheet sets.
