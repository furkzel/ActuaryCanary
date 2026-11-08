# 0364 — The golden copy and the examples after the hardening item: every change and its cause

## Context
`just golden` and `just examples` after the analytic Hessian (0360). The rule of the item: if a number outside MT17, MT18 and what they feed moves, stop and report.

## What moved (ran 2026-11-08)
**Run ids.** The only input to the id that changed is the version of MT17 (1.0.0 -> 1.1.0, in the specification list). baseline `bd4528a4bbd8153d` -> `e2621d7cd5037408`, messy_headers `50b4544ddd98dcb8` -> `1b5205ec3ae7d525`, demo `5051bffa374d4614` -> `1b18cc3fa726e09f`. The same ids came from `canary run examples/baseline --yes` and `canary demo --no-open`; the Linux wheels in WSL gave the same baseline and demo ids. The guide names the new ids.

**Golden copy (`tests/report/golden/baseline_tiny.json`).** The run id (two places); the MT17 version in the specification list and in the sentence under the fits table ("MT17 v1.1.0"); `severity_parameters.csv`, `severity_fits.csv` and `severity_plots.csv` are held as SHA-256 and size again (their cells out, `TOLERANCE_FILES` empty). Nothing else: all other outputs keep their hash and size.

**Examples (`manifest.json` and `report.html` of each).**
- baseline and messy_headers (8 fields each): the run id, the MT17 version, and the SHA-256 (and size) of `severity_parameters.csv`, `severity_fits.csv` and `severity_plots.csv`, and of `report.html`. Cause: the standard errors of the severity fits, and the Pareto II estimate and Anderson–Darling statistic through the finished single fit (0360); the page shows these tables.
- demo (17 fields): the same, and the SHA-256 (and size) of `extreme_candidates.csv`, `extreme_excess_plot.csv`, `extreme_gpd_fit.csv`, `extreme_return_levels.csv`, `extreme_tail_quantiles.csv`. Cause: MT18's standard errors, and its estimate of xi and sigma finished to 1e-14 of the bracket (a 2e-11 move that shows in the tenth digit of a few cells).
- Cell by cell against a run of the code at the P27 merge on the same inputs: `severity_parameters.csv` 35 of 198 cells, largest 2.3e-6; `severity_fits.csv` 6 of 306, 1.5e-7; `severity_plots.csv` 1,445 of 22,797, 8.5e-7; `extreme_candidates.csv` 47 of 288, 1.2e-5; `extreme_gpd_fit.csv` 7 of 48, 6.5e-6; `extreme_excess_plot.csv` 10, 8.3e-10; `extreme_return_levels.csv` 2, 3.3e-10; `extreme_tail_quantiles.csv` 3, 6.7e-10. No text cell changed: selected families, thresholds and rejections are as before.
- **Not moved:** every other file of the three runs has the SHA-256 it had: the tier A tables, the tier B tables, `quality.json`, `modules.json`, the survival files, `sensitivity.csv`, the risk files, `lineage*.csv`, `anomalies.csv`, `assumptions.csv`, `diagnostics.csv`, `measures.csv`. This includes the output of the two speed-ups of 0361 and the specification cache of 0362. No number outside MT17, MT18 and the pages and files they feed moved, so the stop rule did not apply.

## Found and not changed
The MT19 rows of `diagnostics.csv` are not among the rounded methods of the ten-digit rule (0626): on the demo, the p-value of `NON_PROPORTIONAL_HAZARDS` of NON_LIFE (2.1e-12) differs between Windows and Linux at 2.2e-14 relative. The golden baseline is unaffected, the demo has no golden hash; adding MT19 to `ROUNDED_METHODS` would move the run ids once more and is not part of this item.
