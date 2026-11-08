# 0361 — The medium run: where the time goes, two exact speed-ups, and a reference machine for the budget

## Context
`test_medium_runs_inside_its_budget_cold_and_warm` (45 s cold and 30 s warm, without the import) fails on the owner's laptop: cold 77 to 84 s after P27, 58 s before it (0625, 0346). The budgets stay as they are (0625). This item profiles one medium baseline run, takes the cheap speed-ups that change no number, and gives the budget a reference machine.

## Profile (2026-11-08, medium baseline, 12th Gen i5-12500H laptop, other programs open)
`just bench` before the speed-ups, seconds; the profile below is one warm run under cProfile (60.5 s; polars `collect` is 26 s of it):

| step | cold | warm | where the time goes (warm, cProfile) |
| --- | --- | --- | --- |
| importing the package | 6.6 | 0 | not in the budget |
| reading and recognising spreadsheets | 18.1 | 1.5 | cold: fastexcel reading of five workbooks; warm: parquet cache |
| checking data against the specifications | 1.9 | 1.7 | canonicalise six feeds 1.3 s, quality rules 1.0 s; the specifications are loaded once per run |
| building triangles | 1.6 | 1.7 | |
| reserving methods | 4.1 | 4.2 | `fit_tail` 56 calls, 4.4 s, 3.4 s of it one million-element array built 77 times (the remainder of MT14); tier B inputs 1.1 s |
| claim sizes and extreme values | 16.8 | 17.0 | MT18 bootstrap, `gpd._profile` 9.0 s in 6,778 calls (already reduced by 0625); MT17 goodness of fit 6.1 s (maximum likelihood of the bootstrap rows 2.5 s, `gammaincc` of the statistics 2.3 s) |
| settlement speed (MT19) | 0.9 | 0.9 | nothing repeated |
| reserve ranges, discounted figures | 0.2 | 0.2 | |
| sensitivity reruns | 2.8 | 3.0 | four `run_reserving` reruns; their cost is the same `fit_tail` |
| anomalies | 5.4 | 5.0 | isolation forest 4.4 s (400 tree fits) |
| measures and modules | 11.0 | 10.8 | `earned_premium` built 12 times for 6 distinct requests, the six identical gross ones 2.3 s |
| writing the tables | 10.5 | 12.5 | lineage 10.5 s: `_ranges` 5.8 s in 52 calls, `_atomise` 3.7 s; rounding of the new files 0.9 s |
| writing the report, manifest | 2.8 | 1.7 | |
| **total without the import** | **76.1** | **60.3** | |

## Decision
Two speed-ups, both exact:
1. **MT14 remainder** (`tail._remainder`). The remainder of the tail product ran 1e6 periods or until the increment fell below 1e-12, and built the whole 1e6-element array to find that point. It now takes 4,096 periods at a time and stops at the first increment below the floor; the values, their order and so the sum are the same. Test: 36 combinations of curve, parameters, first period and extension (a few periods to the 1e6 cap), equal to the old whole-range code to the last bit.
2. **Earned premium** (`premium_measures._earned`). The structure is built once per run for each breakdown and set of settings and kept in the per-run cache of the measure inputs (`inputs.cache`, which the claim measures already use). Test: the same request twice builds once, another period builds again.

Not done, and why: the survival step repeats nothing (0.9 s); the sensitivity step repeated only `fit_tail` (cured by 1); validation was not repeated inside a run (the repeated loading of the specifications is in the test suite, 0362); the bootstrap rows of MT17 and MT18 could be split over threads without changing a number, but that is a parallelism decision for the owner (the test workers already use all cores); the lineage (10 s) and the isolation forest (4 s) are single calls of polars and scikit-learn.

## Result (this machine)
- Every output file of the medium baseline (55 files, `report.html` and `manifest.json` included), the tiny baseline (53) and the demo (56) is byte-equal before and after the two speed-ups.
- `just bench`: cold 82.7 -> 70.4 s (76.1 -> 64.8 s without the import), warm 60.3 -> 45.5 s. Per step: reserving methods 4.1 -> 3.3, sensitivity 2.8 -> 1.0, measures and modules 11.0 -> 7.5 (cold); the rest is noise of this machine.
- The budget test alone: cold 67.0 s, warm 48.8 s against 45 and 30: **still failing on this laptop**, now by 22 and 19 s. In `just test-all` (parallel) 64.0 s cold. The run is slower here than on the machine of the earlier records by the ratio seen in 0623 (about 2); what is left is the budget or the machine, not one slow step: reading 17 s cold, severity 14 s, the lineage 11 s, measures and modules 7 s.

## The reference machine
A separate job `budget` in `.github/workflows/ci.yml` (Ubuntu, `continue-on-error: true`, so it cannot fail the workflow): it writes the medium baseline (`just synth baseline medium`, 49 to 87 s), prints the time of each step cold and warm (`just bench`), then runs the budget test alone (`-n0`). **Its numbers are known only after the pull request has run**; read them in the log of that job. Until then the budgets have no reference machine and the question of 0625 (the budget or the machine) stays open.
