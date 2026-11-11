# 0383 — Scenario files after the four feeds left `phase2/`

## Context
Record 0380 holds the SHA-256 (first 16 hex digits) of the 513 files of the nine scenarios at size tiny before F1bc. The same set was written again after stage 3 (`just synth all tiny` into an emptied folder) and compared (checked 2026-11-11).

## Findings
513 files before, 513 after. 468 files have the same path and the same bytes. Nothing else moved than:
- **Path change, same bytes, 36 files:** `phase2/reinsurance_treaties.xlsx`, `phase2/reinsurance_transactions.xlsx`, `phase2/recoveries.xlsx` and `phase2/ledger.xlsx` of each of the nine scenarios are now `<scenario>/<file>`; each has the hash it had in 0380 under its old path (36 of 36 compared).
- **Moved, derived, 9 files:** `manifest.yaml` of each scenario (it lists the paths above).
- No canonical copy, no truth file, no file of the six feeds, of the interest rates or of the life feeds moved; nothing is new, nothing disappeared.

New paths and hashes (the hash equals the one in 0380 under `phase2/`):

```
baseline/ledger.xlsx dce9c5b9dd585cd8
baseline/recoveries.xlsx 467b93cc9b0f9462
baseline/reinsurance_transactions.xlsx f53745583cb5fbec
baseline/reinsurance_treaties.xlsx 863925182017d533
demo/ledger.xlsx 320b24a773d65952
demo/recoveries.xlsx 2583b75edbac1318
demo/reinsurance_transactions.xlsx 7d7f7c269b4a496e
demo/reinsurance_treaties.xlsx 777dfd242b13f8fd
high_inflation/ledger.xlsx 6481055432706f47
high_inflation/recoveries.xlsx 62514a0eac04ce43
high_inflation/reinsurance_transactions.xlsx 3dc243c7c5009e77
high_inflation/reinsurance_treaties.xlsx d450e5caecf54a57
large_loss/ledger.xlsx 1d2c13200a58fc56
large_loss/recoveries.xlsx 467b93cc9b0f9462
large_loss/reinsurance_transactions.xlsx f53745583cb5fbec
large_loss/reinsurance_treaties.xlsx 863925182017d533
life_book/ledger.xlsx dce9c5b9dd585cd8
life_book/recoveries.xlsx 467b93cc9b0f9462
life_book/reinsurance_transactions.xlsx f53745583cb5fbec
life_book/reinsurance_treaties.xlsx 863925182017d533
messy_headers/ledger.xlsx 52ea0a53e2315103
messy_headers/recoveries.xlsx ba9d06d59c18fe52
messy_headers/reinsurance_transactions.xlsx e7c70c4ba33fa1a4
messy_headers/reinsurance_treaties.xlsx 7b3db9db45de94a1
messy_incremental/ledger.xlsx 52ea0a53e2315103
messy_incremental/recoveries.xlsx ba9d06d59c18fe52
messy_incremental/reinsurance_transactions.xlsx e7c70c4ba33fa1a4
messy_incremental/reinsurance_treaties.xlsx 7b3db9db45de94a1
reinsurance_heavy/ledger.xlsx 68d1ba7b9eb44e20
reinsurance_heavy/recoveries.xlsx 467b93cc9b0f9462
reinsurance_heavy/reinsurance_transactions.xlsx 4a64a668998106a7
reinsurance_heavy/reinsurance_treaties.xlsx 35ccc80912ec04be
reserve_bias_change/ledger.xlsx b8b32b8bbc147a65
reserve_bias_change/recoveries.xlsx 467b93cc9b0f9462
reserve_bias_change/reinsurance_transactions.xlsx 9dc97ebc53e3d80d
reserve_bias_change/reinsurance_treaties.xlsx 863925182017d533
```

## The frozen-hash test
`tests/synthetic/test_phase2_files.py::test_every_file_of_the_first_six_feeds_is_byte_for_byte_what_it_was_after_f1a` (slow) failed before any change of this item: `tests/synthetic/tiny_sha256_f1a.yaml` held whole-file digests of the twelve workbooks, while the test compares them with `writer.sha256`, which takes a workbook's digest over the uncompressed parts of the archive (so that it does not depend on the compression library). The twelve workbook digests in that file were rewritten in the form the test uses, after checking that the whole-file digest of each generated workbook equals the old entry (the bytes are those of F1a) and that the fourteen parquet digests agree as they are. No tolerance changed and no file was dropped from the list; the test passes (2 passed).

## Consequences
- The move is a path change and nothing else. The golden copy and the committed fixtures are not touched by it (they read `tests/fixtures/synthetic/`, which is older than the generator until the gate).
