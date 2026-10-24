# 0222 — A second lineage format: row groups listed once

## Context
`lineage.csv` (format 1) has one line per value, file and sheet, with the spreadsheet rows as ranges (`2-40;45`). On `large` it is 352 MB (1 947 lines, 91.6 million cited rows in 40 million ranges). The work item described it as one row per reference; it already uses ranges, but values that stand on nearly the same rows repeat them: 790 distinct row sets sit behind 1 947 lines, and rows of premiums and valuations belonging to a line are scattered, so ranges alone save little.

## Decision
- **Format 2** cuts the rows of each file and sheet into atoms, the sets of rows cited by exactly the same values. `lineage_atoms.csv` (atom, concept, file, sheet, rows, count) lists each atom once with contiguous row ranges; `lineage.csv` (measure, version, view, row, concept, atoms, count) names, per value, its atoms as ranges of atom numbers. Atom numbers follow concept, file, sheet and first row, so output is deterministic.
- `to_format1` rebuilds format 1 line for line; `read_lineage` reads a run folder in either format (the second file tells them apart). The report appendix and its summary take a `Lineage` of either format.
- Format 2 is the default. `canary run --lineage-format 1` writes the old file. The format is a run setting, so it enters the run id, and the manifest records `lineage_format`.
- Not chosen: one line per range in a long table (about 40 bytes a line against 9 bytes a range in a string, larger than format 1); a stepped notation for alternating rows (smaller, but still scales with the number of values); compression of the file (not plain CSV any more).

## Consequences
Measured 2026-10-23 on `large` (`just bench data/synthetic/baseline/large`, 994,821 valuation rows, 4,305,801 premium rows, same machine, back to back, seconds cold / warm):
- Size: format 1 `lineage.csv` 352.0 MB; format 2 `lineage.csv` 0.2 MB plus `lineage_atoms.csv` 35.2 MB (35.4 MB, one tenth).
- Run time: format 1 86.3 / 64.3, format 2 87.0 / 64.7; writing the tables 19.4 / 18.2 against 24.6 / 23.7 (the atoms cost about 5 s), the rest within noise. Peak memory not measured (UNVERIFIED).
- Format 2 of the same run, rebuilt with `to_format1`, equals its format 1 file for all 1 947 lines.
- Every example run id changes through the new setting; `lineage_atoms.csv` is a fifteenth output file.
