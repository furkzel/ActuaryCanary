# 0389 — Golden after the modules (F1bc, stages 6 to 9)

## Context
Record 0385 holds the golden copies at the seam (the four feeds built, no module added). Stages 6 to 8 build RC03, RC04, EX04, EX05, M07 and M09 and their pages. The golden copies were regenerated once with `just golden` (2026-11-11) and the diff against the seam read key by key, pages compared by module. The golden run reads the committed fixture `tests/fixtures/synthetic/baseline`: it has no recoveries file in its folder, so M07 runs on flows derived from the to-date fields of claim valuations, and M09 runs on its expenses file.

## Changed entries since the seam and their cause (the same in both languages)
- **`run_id`** (cover and reproducibility): English `1ec1597ebf258a17` → `e714ce9617e26f80`, Turkish `d8c5e494fc353104` → `d42fe1b25de13deb`. Cause: the specs of a run are part of its id (six new ones, RP01 1.3.0).
- **Specs of the run:** new M07, RC03, RC04, M09, EX04, EX05 (all 0.1.0); RP01 1.2.1 → 1.3.0 (also in `findings_spec`).
- **Pages:** two new pages, `M07 Recoveries` (state ran, source "derived from the to-date fields of claim valuations", nothing to reconcile) and `M09 Expenses` (state ran), between M06 and M12. The pages of M01, M02, M03, M05, M06 and M12 are equal to the seam, key by key; so are the reserving pages, the tiles, the key findings, the assumptions and the data findings.
- **Figures:** four new ones, `recoveries-recovery_subrogation`, `recoveries-recovery_salvage`, `recoveries-total`, `expenses-by-line`.
- **Further findings:** 4 → 6; KF35 (recoveries to date) and KF41 (unit costs stopped by a month without expense rows) fire. The eight key findings and the four earlier further findings are unchanged.
- **Outputs:** four new files, `recoveries.csv`, `recovery_development.csv`, `recovery_reconciliation.csv`, `expenses_by_period.csv`. New hash and size of `measures.csv`, `lineage.csv`, `lineage_atoms.csv` (the views of RC03, RC04, EX04, EX05 and the monthly and by-line views of EX01 to EX03 that M09 asks), `modules.json` (two more modules) and `quality.json` (their status marks).
- **Lineage summary:** measures traced 32 → 36 (EX04, EX05, RC03, RC04 join the list), lines 679 → 2,188, traced values 547 → 1,200, source rows cited 123,471 → 413,153: the new views, mostly the monthly ones of M09.

Nothing moved that these causes do not explain: no reserve, no ratio of M05, no measure of the earlier modules.

## Consequences
- Final tiny baseline run ids of F1bc: English `e714ce9617e26f80`, Turkish `d42fe1b25de13deb`.
- `test_run_ids_differ_by_language_and_each_is_stable` fails inside the `just golden` call that rewrites the copies (it compares with the copy read before the rewrite) and passes on the next run (4 passed); this is how the recipe behaves on every run-id change.
- The committed examples and fixtures are older than the generator until Gate v1.3 and are not regenerated here.
