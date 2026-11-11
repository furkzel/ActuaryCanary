# 0382 — Reinsurance treaties and transactions, recoveries and the ledger leave `phase2/`

## Context
Record 0242 put the workbooks of the feeds added after version 1.0 into the subfolder `phase2/` of a scenario folder, because a run would have taken them for known concepts. Recognition now reads the four feeds as their own concepts and takes nothing else for them (records 0375, 0381).

## Decision
- The generator writes `reinsurance_treaties.xlsx`, `reinsurance_transactions.xlsx`, `recoveries.xlsx` and `ledger.xlsx` into the scenario folder, beside the six feeds, in every scenario (all nine write all four; a feed split over workbooks keeps its `_partN` names). `interest_rates.xlsx` and the life feeds (`life_in_force.xlsx`, `life_events.xlsx`, `fund_flows.xlsx`, written by `life_book` and what starts from it) stay in `phase2/`: `LATER_FOLDER_FEEDS` in `synthetic/writer.py`.
- Nothing else of the generator changes: the bytes of every workbook, the canonical copies (`canonical/<feed>.parquet`) and every truth file are what they were. The truth logs of the later feeds keep their names (`column_map_phase2.csv`, `value_map_phase2.csv`, `date_formats_phase2.csv`, `layout_phase2.csv`, `money_columns_phase2.csv`); they name files without a folder, so they hold for both places. The messy layouts already covered the four feeds (0242) and still do. `manifest.yaml` lists the new paths. The checker (`check.py`, `check_phase2.py`) looks in the folder and in the subfolder, as before.
- `docs/guide.md` section 2 lists the four files.

## The demo scenario
The generated `demo` scenario folder (size `demo`, written 2026-11-11) now holds in its main folder: `ledger.xlsx` 217,049 bytes (3,872 rows), `reinsurance_transactions.xlsx` 78,663 bytes (1,627 rows), `recoveries.xlsx` 14,628 bytes (226 rows), `reinsurance_treaties.xlsx` 7,169 bytes (30 rows), beside the six feeds (6.35 MB together); `interest_rates.xlsx` 88,828 bytes stays in `phase2/`. A run on that folder loads and checks the four feeds, lists them among the inputs, takes the recoveries of M07 from the 226 transactions instead of deriving them, and has another run id than a run on the six files (the inputs and their mappings are part of the id).
The committed `examples/demo` does not change in this item, for two reasons: the examples are regenerated at the gate, and `docs/tools/refresh_examples.py` copies six named feeds and the interest rates only (`FEED_FILES`), so the committed demo gains the four files only when that list is extended. That tool is outside this item; whether the shipped demo should carry the four files (317 kB more) is the owner's choice at the gate. Until then the demo's M07 page shows recoveries derived from the claim valuations and its M09 page the expenses, both from files it already has.

## Consequences
- `canary run` on a generated scenario folder reads ten feeds. The committed fixtures under `tests/fixtures/synthetic/` and `examples/` are older than the generator and still have the four files in `phase2/`; tests that need the new layout write a scenario once per session (`scenario_folder` in `tests/conftest.py`).
- Record 0383 lists every file that moved against record 0380.
