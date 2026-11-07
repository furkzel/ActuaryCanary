# 0621 — MT17 and MT18 run in the pipeline; the `large_loss` section of project.yaml is read

## Context
P25 built MT17, MT18 and the parser of the `large_loss` section, and left the calls to the integration (0300, 0301). Record 0601 and the reviewed specs CV08 1.1.0, MT18 1.0.0 and M06 1.1.0 decide that the 99th percentile of CV08 is the only large-loss threshold.

## Decision
- `modules.severity_run.run_severity` builds the sizes frame as `size_classes` gives them (gross incurred at the cut-off, reporting currency, value-date prices when the index is loaded), adds segment, line, event code, origin year (the year of the origin period) and the latest status, and runs MT17 and MT18 once per segment and line with the options of `mt17_judged` and `mt18_judged` for the scope `SEGMENT/LINE/severity`. The CV08 threshold of each group goes in as `cv08_thresholds`. The entries in force go to `assumptions.csv`, the manifest and the report appendix; the diagnostics to `diagnostics.csv` (measure `severity`).
- Seed 1 (`SEED`) and the defaults of both methods are part of the settings record (`severity`); the randomness rows are written for the methods that fitted. The defaults are the specifications' (`gof_bootstrap` 200 and 500) and are not changed here (0623).
- Outputs: `severity_*.csv` (nine tables of MT17) and `extreme_*.csv` (ten tables of MT18), one file per table of `SeverityFits` and `ExtremeValues`, empty where no group fitted.
- M06 keeps the CV08 threshold as the only one that classifies. The MT18 threshold is shown next to it from `ExtremeValues.threshold_comparison`: one sentence in the notes of CL12 ("MT18 extreme-value threshold beside the CV08 large-loss threshold (reported, not used to classify claims): ...") and the table `extreme_threshold_comparison.csv`. A test shows that the thresholds that classify are CV08's and that none equals MT18's.
- A group where MT17 or MT18 refuses (fewer than 50 claims; no candidate threshold leaves 50 excesses) is listed in the notes of M03 (MT17) and M06 (MT18) with the reason, and the module is limited.
- `project.yaml` may carry the `large_loss` section (`ProjectMetadata.large_loss`); `parse_large_loss` reads it, an error stops the run before anything is read. Its two fields reach the measure inputs and `manifest_record()` is written under `settings.large_loss`, with the percentile and thresholds in force and their source (`default` or `project.yaml`). A fixed threshold changes the LARGE class and the run id (tested).

## Consequences
- With the default section the thresholds are CV08's as before: CL12 and everything that stands on it are unchanged.
- MT19 (survival) is not built and not called; it keeps `implemented: false` and has its own item.
