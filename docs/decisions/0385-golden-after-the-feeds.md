# 0385 — Golden after the feeds (seam of F1bc, stages 1 to 5)

## Context
Stages 1 to 5 of F1bc build the concepts `reinsurance_treaties`, `reinsurance_transactions`, `recoveries` and `ledger` (read, recognised, mapped, typed, checked). The golden copies (`tests/report/golden/baseline_tiny.json`, `baseline_tiny_tr.json`) were regenerated once with `just golden` (4 passed, 2026-11-11) and the diff read. The golden run reads the committed fixture `tests/fixtures/synthetic/baseline`, which is older than the generator and still has the four files in `phase2/`, so the run loads none of them.

## Changed entries and their cause (the same in both languages)
- **`run_id`** (and the run id shown in the report header): English `fe9f94cdf99afc24` → `1ec1597ebf258a17`, Turkish `90b1f5cf4acec843` → `d8c5e494fc353104`. Cause: the versions of AL01 and AL02 are part of the run id.
- **Spec versions AL01 and AL02:** 1.1.0 → 1.2.0 (the aliases of the four concepts moved in, record 0381).
- **Coverage of the quality section:** four new rows, `ledger`, `recoveries`, `reinsurance_transactions`, `reinsurance_treaties`, each "not loaded" (the catalogue of a run now holds eleven data concepts).
- **`quality.json` in the list of outputs:** new hash and size (32,843 → 36,417 bytes): the 40 rules of the four concepts are listed as not evaluated ("<concept> is not loaded") and the four coverage rows are added.

Nothing else moved: no measure, no reserve figure, no finding, no module status, no other output file. M07 and M09 are not in a run yet (they are built in stages 6 and 7), so no module status changed at the seam; the status marks of both modules are tested on the catalogue that holds them (`tests/quality/test_module_status_m07_m09.py`).

## Consequences
- Tiny baseline run ids at the seam: English `1ec1597ebf258a17`, Turkish `d8c5e494fc353104`. Stage 9 records the ids after the modules (record 0389).
- The committed examples and fixtures are not regenerated here (the gate does that).
