# 0787 — A1c: the golden copies after the bootstrap refit

## Context
`just golden` run once at the end of A1c; the diff of `tests/report/golden/baseline_tiny.json` and `baseline_tiny_tr.json` read leaf by leaf. The first update run reported the run-id test against the stored copy it had just replaced; the plain golden test afterwards: 4 passed.

## What moved, and why
On the tiny baseline the bootstrap does not run (fewer than 5 origin periods, "MT11 bootstrap did not run for 4 of 4 groups"), so no simulated range, percentile, VaR, TVaR, histogram, coefficient of variation or pseudo-triangle share is in the golden copies, and none moved. The moved leaves, the same in both languages:
- Parameters in force: a new entry `MT11 / floor pseudo increments` (4 entries, record 0784); the count of entries 233 → 237 and the total 236 → 240; in the settings, `tier_b.methods.MT11.floor_pseudo_increments = True` (new) and `tier_b.methods.MT11.n_simulations` 10000 → 50000 (record 0785).
- `assumptions.csv` held as SHA-256 and size: 28,395 → 28,939 bytes (the four new rows and the changed `n_simulations` rows and their text).
- Spec versions in the texts: MT11 v1.3.0 → v1.4.0 (headline of the range, the bootstrap line of four method notes), M12 v1.2.0 → v1.3.0 (the ranges note, the section spec, the spec list).
- Run ids: English `bb70e51693706e98` → **`7eaa8477d8aaab61`**, Turkish `b2b6c13bf434be68` → **`89aab15f3692bf8e`** (they move with the settings, the specifications and the outputs).

Nothing else moved: no ultimate, reserve, factor, tail, Mack figure, finding or text outside the spec versions. The note on the pseudo-triangles (changed text, records 0783 and 0784) is on the uncertainty page only where a bootstrap ran, so it is not in the tiny copies; it is in the demo report (record 0786).
