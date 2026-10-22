# 0051 — Measure choices the specifications leave open

## Context
Writing the measures showed places where a spec is silent or two of its sentences disagree. None changes a headline number; each is recorded so the owner can overrule it.

## Decision
- **CL07**: the mean and the median are always shown; the 75th, 90th and 95th percentiles (type 7) are hidden below five claims in a group. The spec's edge case says percentiles are hidden below five and its test example shows a median from four claims; this reading satisfies both. A period is "incomplete" when its last occurrence date plus the 95th percentile delay of the mature periods lies after the cut-off (mature: ended at least the all-claims 95th percentile before the cut-off).
- **CL08**: the origin of the summary is the report period (the spec says "summarised by report period"). A derived close date is the last transition into a closed status; a claim open at the cut-off is censored whatever its history.
- **CL04 flows**: "closed" is a transition from a status that is not closed to a closed one, so a first row that is already closed, or follows an UNMAPPED label, counts.
- **CL10**: a column is flagged when the latest diagonal ratio lies outside the range of the earlier ratios of that column (at least two earlier cells); the spec gives no threshold.
- **CL11**: the earlier valuation is the cut-off minus twelve months at the month end unless given. A cohort claim whose last row is on or before it counts as without a later row and is listed.
- **CL05, CL06 and CL12** use the percentile, minimum count and fixed thresholds of CV08 (99th percentile, 100 claims); a fixed threshold per segment and line is an input of the run, not yet read from an assumptions register.
- **EX02, EX03**: an expense row without a value for a requested level (segment, line, entity) is left out of that level and counted in a note; the unlevelled total uses every row.
- **Currency**: specs defined in ORIGINAL only (counts, delays, frequency) ignore the currency view. Claim flows by calendar period are converted at the average rate of the booking month (CV01); cumulative and stock views use the constant development rate, which at the cut-off is the period-end rate. Month ends before the cut-off in a `valuation_date` breakdown use the same constant rate and say so.
- **RI01** shows premium and claims sides apart; a request with a calendar period gets the premium side, with an origin period or class the claims side, with neither both.
- **Missing versus zero**: PR01 gives 0 for a period inside the months the premium file covers and nothing outside; a ratio with a non-positive denominator is a null with a note, never 0.

## Consequences
- Each choice is covered by a test that names the spec ID.
- If the owner reads the specs differently, the change is local to one function and one spec sentence.
