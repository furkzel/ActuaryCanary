# 0347 — Three finding rules say what their conditions prove (RP01 1.2.1)

## Context
Three rules of RP01 1.2.0 (record 0345) wrote more than their conditions tested. KF28 said the
method "has erred in one direction" on the size of the mean bias alone. KF31 said the fitted tail
"has no finite variance" against a limit that was a configurable fact. KF32 fired on the
significance of a log-rank test, which almost any large portfolio passes.

## Decision
- **KF28:** a new fact `back_test_sign_share`, the share of the back-tested origins (MT10, first
  horizon, the rows of `back_test.csv` that MT22 writes) whose error has the sign of the mean bias;
  an error of zero has no sign. The condition also requires `back_test_sign_share >=
  back_test_sign_share_limit`, a named setting of the rule file, default 0.75. The wording is
  unchanged.
- **KF31:** the limit is the fixed 0.5 in the condition and in the sentence (English `at least
  0.5`, Turkish `en az 0,5`); the fact and placeholder `gpd_shape_limit` are removed. The constant
  `INFINITE_VARIANCE` of the large-loss page stays: the page uses it for its own warning, which
  says the same thing. A test fails if the rule reads a limit other than 0.5 or the templates name
  another number.
- **KF32:** a new fact `cohort_median_ratio`, the largest over the smallest median settlement time
  of the report years that have at least 20 closings (`MIN_EVENTS` of MT19) and a median, read from
  `survival_cohorts.csv` and `survival_time_percentiles.csv`; absent with fewer than two such years.
  The condition also requires `cohort_median_ratio >= cohort_median_ratio_limit`, a named setting,
  default 1.25. The p-value stays in the sentence.
- The rule file gains a `settings` block (name to number) for limits that only rules use. They enter
  the fact sets of every scope as facts of kind factor, so a condition reads them like any other
  fact. The 0.75 and 1.25 are this item's choice, like the levels of 0345.
- RP01 is 1.2.1, status `draft`, change-log entry says the owner has not reviewed it.

## Consequences
- A rule can fire less often than before, never more: each condition only gained a clause.
- Run ids move (the specification version and the findings text where a rule now fires
  differently).
