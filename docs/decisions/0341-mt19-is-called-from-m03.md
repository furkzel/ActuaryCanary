# 0341 — MT19 is called from M03, and MT19 1.1.0 writes down three conventions

## Context
MT19 was built by P25c and called by no module (0304); the only module spec that listed it was M13, a draft for P35. P27 asks to call it from the module that shows settlement speed, M03, and to write the choices of 0305 into MT19.

## Decision
- The pipeline calls `survival_run.run_survival(measure_inputs, settings.assumptions)` after the severity fits. The settings record gains `survival` (`survival_run.settings()`), the nine `survival_*.csv` files go through the shared writer, the diagnostics of MT19 go to `diagnostics.csv`, its register entries to `assumptions.csv`, its refusals (no Cox model, with the reason) to the notes of M03, and MT19 to the specs of the run.
- MT19 1.1.0 adds three sentences to its algorithm, no number changes: the first closing takes the day of `claims.close_date` when the claim was never reopened; under `closed_with_payment` a first closing as CLOSED_NIL is censored at that date; the reference level of a covariate is the level with the most events (then claims, then name), a level without events merged into it. The other proposals of 0305 stay in that record.
- The M03 page gains "Settlement speed": one Kaplan–Meier chart per line (small multiples in the colour of the segment, the log-log interval as a band, so that identity never rests on colour), a table per line with claims, closings, the share still open, the 25th, 50th and 75th percentile with intervals ("beyond observed range" where the curve does not get there) and the month-end dates, the Cox model per segment with hazard ratios and intervals or the reason, the warnings of MT19 (thin evidence, no model, the global proportional-hazards test, cohorts), and, folded, the share censored by report year with the log-rank test. The Grambsch–Therneau test, the concordance and the baseline are labelled "information, no frozen reference yet" (0616); the size class at the cut-off is labelled descriptive.
- The warning that the proportional-hazards test rejects is shown as MT19 raises it; it rests on the information-only test and says so on the page.

## Consequences
- Every run writes nine more files and lists MT19; the tiny examples show survival curves for both segments (LIFE has no Cox model: one line only).
- The R references of the information outputs are still to be frozen by a later item.
