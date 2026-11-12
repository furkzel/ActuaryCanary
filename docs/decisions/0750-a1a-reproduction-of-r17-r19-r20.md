# 0750 — A1a: what the demo shows of R17, R19 and R20

## Context
Three of the review findings were not code-checked (R17, R19) or worded after the code (R20). A1a stage 1 ran `canary demo` once into a scratch folder outside the repository (run `3d9a27b85fab3a9d`, 2026-11-12) and looked at its report and tables. This record states the result for each finding; the fixes are in 0751 to 0754.

## Decisions
- **R17 reproduced.** `severity_selected.csv` has the row `LIFE, GROUP_TERM_LIFE, lognormal, "no family fits"` (398 claims), and `severity_quantiles.csv` carries the quantiles of that lognormal (0.5 quantile 3,146,681) although the Anderson–Darling test rejects every family for the line. The page prints "no family fits" next to the table. Fix in stage 3: no severity quantiles on the page for a line whose every family is rejected, with the reason; the file stays as it is.
- **R19 reproduced in both parts.** (a) The reserve-range table and chart of a line label their rows `paid` and `incurred`; the rows hold the selected ultimate less the paid (the unpaid) and less the incurred (the IBNR). (b) The appendix "Analyses" lists M01 to M12 all as `ok`; the status is the data status of `quality.json` (a BLOCKING finding or a missing concept makes a module `limited` or `unable`), while the run itself reports M03, M04, M06 and M12 as `limited` (`modules.json`: MT19 without a Cox model for LIFE, MT14 not run for three triangles, MT08 and MT18 limits, the bootstrap cut columns of M12). The table meant the data status and said so nowhere.
- **R20: the finding does not compare twelve months.** KF04 compares the ultimate loss ratio of the latest origin year with that of the origin year before it (facts `loss_ratio_latest`, `loss_ratio_previous`); the review's "last 12 months against the previous year" is the comparison of KF38 and KF39 (expense and commission ratios), whose sentences already say it. The repository wins: KF04 and KF05 now say that only the two latest origin years are compared. No new logic.
- Findings not reproduced: none. R03, R05, R06, R07, R12, R14, R18, R21 are from the consolidated review as written and are fixed as the item names them.

## Consequences
- RP01 1.3.1 (draft, change log entry): KF04 and KF05, English and Turkish.
- The appendix keeps the data status (now headed "Data status") and gains a column "In this run" with the module's state in this run and the reasons (decision 0751).
