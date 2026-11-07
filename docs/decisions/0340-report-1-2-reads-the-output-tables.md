# 0340 — Report 1.2 reads the output tables; the module lists name the methods they run

## Context
P27 asks for the deeper reserving, the uncertainty and the large-loss results on the report, traceable, and for the carry-over of 0622: the module specifications M03, M04 and M06 list neither the tier B methods nor the severity methods that the code already runs and writes.

## Decision
- The new parts of the page are built from the tables the run writes (`tier_b_ultimates.csv`, `tier_b_parameters.csv`, `bootstrap_summary.csv`, `back_test.csv`, `severity_*.csv`, `extreme_*.csv`, `survival_*.csv`, `risk_*.csv`, `discount_curve.csv`, `sensitivity.csv`): the pipeline hands them to the report (`ReportInputs.tables`), so every number on the page is a cell of a named file, rounded per CV06 for the page only. Each block names its files and spec IDs in its footnote.
- Reserving page per line: the tier A table of ultimates gains the tier B columns (MT12 paid and incurred, MT13, MT15, MT16) before the selection, under a "Tier A / Tier B" header row; then the tail fits of MT14 with the tail the run used and the effect of the chosen curve, Munich paid and incurred with the paid over incurred ratios and the lambdas, the MT11 total, the back test (MT22 with AE02; the first three horizons, the file has all) with the range calibration. The diagnostics of each method are listed beside it ("Diagnostics of MT13: ..."); the full diagnostics table stays at the end of the page.
- The large-loss part is on the M06 page (MT17 fits and selection, the CV08 threshold beside the MT18 threshold with the claims and incurred above each, the generalised Pareto fit, tail quantiles, return levels, exceedances per year). The MT18 threshold classes nothing (0601).
- Module specifications: M03 1.1.0 lists MT17 and MT19, M04 1.1.0 lists MT11 to MT16 and MT22, M06 1.2.0 lists MT18 and MT17 (the loader requires it: MT18 uses MT17's fits). Each gains `outputs` and `report_page` and a change-log entry; status stays `reviewed` from 1.0.0 with "the owner has not reviewed this version yet", as P26 did. AE02 stays out of every module list (0622) and is shown through MT22.
- MT17, MT18 and MT19 are added to the methods the methods port reports as built, so the module outcome does not call them "not built yet".

## Consequences
- M03, M04 and M06 change versions, so every run id moves once; the quality report changes on every example because the modules that a finding touches now include the new methods' fields.
- The method notes of the tier B methods (`docs/methods/`) are not in this item's allowed area and are not written; they stay with P37.
