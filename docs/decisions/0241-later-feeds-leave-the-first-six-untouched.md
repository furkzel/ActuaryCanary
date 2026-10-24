# 0241 — The later feeds use random streams of their own and leave every earlier file as it was

## Context
P22 adds eight feeds and several truths to the generator and must not move a byte of what exists. A truth file or log that lists all feeds would change as soon as a feed is added.

## Decision
- **Streams.** Every draw of a later feed comes from a stream whose name starts with `phase2` (`Streams.get("phase2", ...)`). A stream depends only on the seed and its name (record 0015), so adding a stage moves no other draw.
- **Scenario file.** The parameters of the later feeds live under the key `phase2:` (surplus treaties, rate curves, ledger differences, the life book). `truth/scenario.yaml` leaves the key out, so it is what it was. `truth/phase2_scenario.yaml` holds it, with the list of which later work item reads each truth file.
- **Logs.** `layout.csv`, `column_map.csv`, `value_map.csv` and `date_formats.csv` keep the rows of the first six feeds only. The rows of the later feeds are in `layout_phase2.csv`, `column_map_phase2.csv`, `value_map_phase2.csv` and `date_formats_phase2.csv`. The truth tables of the later feeds are separate files, and their money columns are declared in `money_columns_phase2.csv`.
- **Proof.** `tests/fixtures/synthetic/tiny_sha256_v1.yaml` holds the SHA-256 of all 26 files of the tiny baseline and the tiny messy_headers as version 1.0 wrote them. A slow test writes both again and compares every file (equal). The 26 files of the medium baseline were compared before and after by hand: equal. `manifest.yaml` lists the new files too and so changes by design.
- The `messy_headers` scenario now starts from `life_book` instead of `baseline`. The six feeds of the file are unchanged (the hashes above).

## Consequences
- A later item that adds a feed puts its log rows into the `_phase2` files too, or moves them into the main logs on purpose with the hashes updated in the same commit.
- `truth/scenario.yaml` no longer shows the later parameters; `truth/phase2_scenario.yaml` does.
