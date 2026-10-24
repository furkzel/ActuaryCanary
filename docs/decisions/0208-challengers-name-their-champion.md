# 0208 — Each challenger names its champion

## Context
Blueprint 9.3 says data science models enter only as challengers beside a classical champion, with both back-test errors shown. P20 asks each tier C spec to name its ground-truth metric and the tier A or B method it is compared with.

## Decision (proposed, draft)
A tier C spec has a `champion` field, and the loader requires it to be a defined tier A or B method:

| Challenger | Champion | Ground-truth metric |
| --- | --- | --- |
| MT23 GLM | MT16 one-way frequency and severity | error of log relativities |
| MT24 individual claim reserving | MT10 selected ultimate | percentage error of total reserve per line |
| MT25 large-loss early warning | MT17 base rate per line | out-of-time AUC |
| MT26 settlement-time prediction | MT19 Kaplan–Meier | integrated Brier score, concordance |
| MT27 count and premium forecasting | MT16 frequency trend (counts) | MASE, interval coverage |
| MT28 segmentation | MT16 grouping by line | adjusted Rand index, deviance explained |
| MT29 explainability | MT16 (with MT23 relativities as reference) | rank of true drivers, PD against true relativities |

AE02 is the common back-test error of every method and challenger.

## Consequences
- Premium forecasting has no tier A or B champion. MT27 compares it with a seasonal naive forecast written inside its own spec.
- MT29 explains models rather than predicting. Its champion entry is formal, and the real reference is MT23. The owner may prefer to exempt it from the champion rule.
