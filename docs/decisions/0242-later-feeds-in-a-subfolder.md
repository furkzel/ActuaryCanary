# 0242 — The workbooks of the later feeds go into the subfolder `phase2/`

## Context
A run reads the spreadsheets directly in a folder and recognises each table by its columns. The generator first wrote the new workbooks next to the six. A run of the baseline with `--yes` gave the run id 81049109d876c774 with the six workbooks, and these with one more workbook beside them:

| added workbook | run id |
| --- | --- |
| none | 81049109d876c774 |
| reinsurance_treaties.xlsx | 179ce4c5e4ae5b90 |
| reinsurance_transactions.xlsx | b93e95694308620c |
| recoveries.xlsx | ad0fa9675f495c2f |
| ledger.xlsx | 36415a737250ec20 |
| interest_rates.xlsx | ecf34aa1f4c88e5c |

The specifications of these concepts are drafts, so the product has no concept for them and recognises their tables as tables of the concepts it has: the interest rates arrived as market rows and 1,008 of 6,826 market rows were excluded. Every folder that a test or a user reads would have changed.

## Decision
The workbooks of the later feeds, parts of a split feed included, are written to `<scenario folder>/phase2/`. The canonical parquet files stay in `canonical/`, the logs and the truth in `truth/`. The data checker looks in both places. A test runs the written baseline and a copy that holds the six workbooks only, and asserts equal run ids.

## Consequences
- Nothing that reads a scenario folder today sees a difference (medium and large included).
- The item that builds the reading of a feed (new feeds, life feeds) copies the files beside the others in its tests, or sets `LATER_FOLDER` in `writer.py` to the empty path once the readers exist. The hashes of record 0241 are for the six feeds, which do not move.
- Spreadsheets in a subfolder are not read by `canary run`, which is what keeps them out.
