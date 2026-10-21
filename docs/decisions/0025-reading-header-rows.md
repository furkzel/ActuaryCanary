# 0025 — Reading sheets with a header row found by content

## Context
P05 reads files whose header is not on row 1 (title, note and blank rows above it, CV07 1.1.0). Blueprint 6.1 defines the header as the first row whose cells are mostly distinct text above rows of typed values. Row numbers must stay true spreadsheet rows, because every finding points back to its source row.

## Decision
- The reader reads each sheet twice on first sight: the first 50 rows as text with nothing skipped (`header_row=None, skip_rows=0`), to find the header; then the sheet with types from that row (`header_row=<0-based row>, skip_rows=0`). With `skip_rows=0` calamine counts from spreadsheet row 1 even when leading rows are blank; checked with a sheet starting at B3.
- Header rule (`io/header.py`): at least half the table width filled and at least 2 cells; at least 80% of cells text (not numbers or dates); at least 90% distinct; the next non-empty row is not another all-text header-like row; a number or date occurs in the next three non-empty rows. Without typed values anywhere, the first wide distinct text row is taken. Every choice carries its evidence.
- `RawTable` records `header_row`, `rows_above` (non-empty rows skipped) and the evidence; the manifest lists them per sheet.
- Cache entries hold the header choice with the parquet; reader version 2. An entry is written into a private temporary folder and renamed into place, so parallel test workers or two runs never read a half-written entry.
- All six messy tiny files: header rows equal `truth/layout.csv`.

## Consequences
- The rule is structural. Recognition (AL01) then confirms the header by the fields it maps; a sheet whose header maps nothing is shown with no concept.
- Pivoted periods as columns (numbers as header cells) are not read yet; such a header fails the 80% text test.
