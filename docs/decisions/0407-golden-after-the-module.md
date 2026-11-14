# 0407 — Golden after the module (seam after stage 4 of F2a)

## Decision
`just golden` ran once (2026-11-14) and the diff was read. The tiny baseline has no treaties, so M08 is skipped; every change follows from that:
- Module status: `M08` skipped with its skip reason, in the module table and the list of modules not run.
- New finding KF15 "Modules not run" (1 of 10, M08 Reinsurance) in both languages: the rule exists already; it fires now because one module is skipped for missing data.
- Specs used: M08, RI03, RI04, RI05 at 0.1.0 join the list.
- Hashes and sizes of `modules.json` and `measures.csv` (the M08 rows); the report hash.
- Run ids: English 4c9ed560ad01f5b8 → beaec8582150a2a3, Turkish 30a766e143fd5cbc → f964565e974e5920.
- No estimate, measure value or existing finding moved.
