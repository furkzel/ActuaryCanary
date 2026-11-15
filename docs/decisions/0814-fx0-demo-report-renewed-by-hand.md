# 0814 — Fx0: the demo report renewed from a run with the shipped profile; no run id moved

## Context
The ordering changes of record 0813 move the last digits of three output files of a run with treaties, so the committed report of the demo (its file table and its manifest carry the hashes of the outputs) had to be renewed. The item names `docs/tools/refresh_examples.py --reports-only` for it.

## What happened
- `--reports-only` ran once (43 s). Baseline (`2f208e5a0555408a`) and messy_headers (`6e8aab673878c0cc`) came out unchanged, byte for byte: they have no treaties.
- The demo came out with another run id, `8127158b42157ca3`. Cause: the tool proposes the ledger profile anew and confirms it on the day it runs (`confirm_ledger_profiles(profiles, date.today())`), so the shipped profile got `confirmed_on: 2026-11-15` in place of `2026-11-14`; the hash of the profile is part of the run id. Nothing else of the profile changed.

## Decisions
- **The run id of the demo stays `713ca5af937d4139`.** The version stays 1.3.0 and nothing a person would call a change happened to the demo; a new confirmation date is not a reason to move the id that the guide, the tests and the criteria table name.
- **The tool's result for the demo was discarded** (`git checkout` of `examples/demo/report`), the shipped profile is untouched, and `report.html` and `manifest.json` were taken from `canary run examples/demo --yes --curve TRY_GOV` with the shipped profile in the profiles folder, on the code of commit `8515796`. That is the run `canary demo` makes (record 0812); the slow test of the examples confirms that a run of the demo gives the run id of the committed report.
- **The tool is not changed here.** `docs/tools/` is outside the item's area. Left for the owner: `--reports-only` should read the shipped profile of the demo and confirm a profile only when it writes a new one, otherwise every refresh of the reports moves the demo's run id by the date.

## What moved in the repository
`examples/demo/report/manifest.json`: the hash of `measures.csv`, the hash and size of `report.html`, the hash and size of `reinsurance_reconciliation.csv` (1,337 to 1,339 bytes: one number printed with two more digits). `examples/demo/report/report.html`: one line, the table of file hashes. No run id, no golden entry, no estimate, measure text or finding. KF47's text on the committed demo did not change: the report differs in that one line only.
