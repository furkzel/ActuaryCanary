# 0426 — The golden copies at the end of F2b

## Context
`just golden` was run once (after the page, the rules and the spec versions). The tiny baseline holds no ledger, so M10 appears there as skipped. The diff was read leaf by leaf.

## What moved, and why
- **Run ids** (cause: spec versions, the settings, the module list): English `fc234ffbb1cfe9c5` to `56dd2aa2f1aae99f`; Turkish `560026422b0dc901` to `7d61b8c43a55fdf8`.
- **Spec versions:** RP01 1.5.0 to 1.6.0 (`findings_spec`, the spec table); M10, FN01 and FN02 0.2.0 are listed as specs of the run (the module list of the catalogue now holds M10 and its two measures; CV12 is not, because the run has no ledger).
- **Settings rows:** `ledger.materiality_amount` 0.0 and `ledger.materiality_ratio` 0.005 (the run setting of record 0422).
- **M10 skipped:** the module state and the reason in `module_runs`, the module table of the appendix, and key finding KF15 ("Modules not run": 2 of 11, M08 and M10).
- **Output hashes:** `quality.json` (the quality report now has a status line for M10) and `modules.json` (M10 is listed) changed in size and SHA-256.
- Nothing else: no estimate, measure, factor, range, ultimate or table value moved; the other output hashes are as before.

## Consequences
- The examples and the committed fixtures are not regenerated (Gate v1.3).
