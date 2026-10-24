# 0249 — The data checker reads the later feeds; sparse columns need a full scan

## Context
`synthetic/check.py` reads a folder back, undoes the layout with the truth files and lists every violation of the data rules it can decide. Generated files must pass it against the P20 specifications.

## Decision
- `check_folder(folder, later_feeds=True)` also checks DV-RTY, DV-RTR, DV-RCV, DV-LDG, DV-IRT, DV-LIF, DV-LEV and DV-FFL (`check_phase2.py`); the default is unchanged, so the tests of the first six feeds are untouched. Each violation carries the severity of its rule from the specification.
- What the checker finds on the generated files (tests, faults switched off): nothing for the life feeds, treaties and recoveries; in the ledger the missing row (DV-LDG-07, DV-LDG-08) and the suspense account (DV-LDG-09), one each; as INFO: reversals of ceded premium that are negative (DV-RTR-10), the forward-rate jumps of an inflation path that changes (DV-IRT-09); with the injected faults of the heavy scenario also DV-RTR-08 and DV-RTR-09 (the fault that lowers one `paid_to_date`), and in messy_headers DV-RTR-11 (exact duplicates of premium rows).
- DV-LDG-09 reads the mapping profile written to `truth/ledger_mapping_profile.csv`.
- The checker now reads worksheets with `infer_schema_length=None`, as the reader of the product does. With the default of 100 rows, a column that is empty in its first 100 rows (the `fund_value` of term contracts, which come first) is read as text. This is a finding for the items that read these feeds: they must scan all cells, as `io/excel.py` does today.

## Consequences
- The reading items (new feeds, life feeds) can start from `check_phase2.py` for the rules they build.
- The cache key of the checker's parquet cache changed (`-all` suffix), so old cache files are not used.
