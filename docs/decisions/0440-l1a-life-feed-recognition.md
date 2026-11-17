# 0440 — Recognition of the life feeds; AL03 and AL04 emptied

## Context
L1a builds `life_in_force`, `life_events` and `fund_flows`. Their column and value aliases were the last entries of the planned dictionaries AL03 and AL04 (decision 0200). Concept scoring is driven by the dictionary and the data specs; F1bc (0381) added the evidence rules that a fourth group of movement-like feeds needed. The generator (`synthetic/messy.py`) reads `columns-planned.yaml` and `values-planned.yaml` by name and must not change in this item.

## Decision
- The three data specs and CV11 are set `implemented: true` (still `draft`). Every entry of AL03 (27 column entries of the life concepts, the personal-data kinds `beneficiary_name` and `employee_number`) moved to AL01 1.3.0 and every entry of AL04 (8 value entries: segment, status, policy_type, channel, premium_frequency, sex, event_type, flow_type) to AL02 1.3.0, verbatim. No alias was added: the clean and the messy-header sheets of the generator are recognised with the moved lists alone. Since the messy generator draws headers from these lists, adding aliases would also have changed its output.
- AL03 0.4.0 and AL04 0.4.0 stay as empty files (the generator reads them; they keep the place for the next planned concept). The spec models `PlannedColumnAliasSpec` and `PlannedValueAliasSpec` accept empty lists for those two files only; AL01 and AL02 still need entries. This touches `spec/models.py` and `spec/loader.py`, outside the item's listed area: the smallest change that keeps both the generator and the loader as they are.
- No constant of 0375 or 0381 changes.

## Measured (size tiny, generator as of this branch, 2026-11-17)
Every sheet of baseline, messy_headers, messy_incremental, life_book and reinsurance_heavy is read as its own concept (the F1bc test `test_every_sheet_of_a_scenario_is_read_as_its_concept`, its life clause rewritten: the life sheets were expected to be rejected, now to be read as themselves). No sheet of the ten older feeds is taken for a life concept. Life sheets, best score and raw margin over the next concept, clean / messy: life_in_force 1.00, 0.59 / 0.59 (next: expenses); life_events 1.00, 0.58 / 0.58 (next: fund_flows); fund_flows 1.00, 0.67 / 0.54 (next: expenses / life_events). Required fields found 6/6, 4/4, 6/6.

## Consequences
- A run reads the life feeds from the data folder like any other feed; the quality report lists them as loaded or "not found in the input" (14 concepts).
- Personal-data columns named LEHDAR, SİCİL NO and their English forms are now dropped on load in every feed.
- Tests: `tests/recognition/test_new_feeds.py`, `tests/canonical/test_feeds_life.py`, `tests/spec/test_specs.py` and `test_loader_errors.py` (AL03 empty; a stray entry is still caught), `tests/recognition/test_messy.py` (the committed fixtures hold no life feed).
