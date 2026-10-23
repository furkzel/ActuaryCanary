# 0081 — `large` policies and premiums as several workbooks

## Context
Decision 0017 wrote a feed that does not fit in one worksheet (1,048,576 rows) as parquet only, so `canary run` on `large` never saw `policies` (1,354,169 rows) and `premiums` (4,305,801 rows). M05, PR02 and MT03–MT05 did not run there, and the two-minute budget of blueprint 14.3 could not be measured on all six feeds (record 0080). The owner decided that `large` gets both feeds in a form the reader opens, split over several sheets or files.

## Decision
- A feed that fits in one worksheet is written as before, `<feed>.xlsx`. A feed that does not is written as `<feed>_part1.xlsx`, `<feed>_part2.xlsx`, ... one workbook per part, nearly equal in size, each with the same sheet name, title rows and header row, and consecutive rows of the table in order. Files, not extra sheets of one workbook: the reader reads files side by side (record 0082), and a part stays small enough to open in Excel. `large` has two parts of `policies` (about 677,000 rows each) and five of `premiums` (about 861,000 rows each).
- The pipeline needed no change to read them: sheets of one concept are already combined (market over several sheets), and the run lists every part in the manifest inputs with its own SHA-256. The run id changes with the files, as always.
- `truth/layout.csv` has a line per part (`file` is the part's file name) and `truth/injected_faults.csv` names the part and the worksheet row of a fault. No fault lands on `policies` or `premiums` in the shipped scenarios; the mapping is general and tested. `manifest.yaml` keeps `spreadsheets_skipped` (now always empty) and `layout.csv` its `written` column (now always true), so the committed tiny fixtures and their hashes stay as they are.
- The synthetic frame check (`synthetic/check.py`) reads the parts of a feed as one table.
- Amends 0017: its third bullet no longer holds. Nothing else in 0017 changes; CV07 (one table per sheet) is met, every part holds one table.

## Consequences
- `just synth baseline large` took 403 s (201 s before, without the two feeds) and writes about 260 MB of spreadsheets; the four other feeds are byte-identical to before (SHA-256 of `claim_valuations.xlsx` unchanged).
- Sums over a split feed add the rows chunk by chunk, so a figure can differ from the one-workbook run in the last digit (tested with a relative tolerance of 1e-9, on `premiums` of tiny split in two). The committed fixtures, the examples and the golden copy are unaffected: none of them is split.
- `large` data is git-ignored; whoever has an older `data/synthetic/baseline/large` must write it again.
