# 0321 — The interest rates are read, checked and excluded by the rules of the concept

## Context
`interest_rates` was a draft with ten rules (DV-IRT-01 to -10). A run reads a concept in two ways: rules that decide which rows enter the analyses are applied in `canonical.feeds` and reported as findings; the other rules are checks of the quality report.

## Decision
- DV-IRT-01 to -07 and -10 are applied while the feed is built, in this order, and a row excluded by one is not seen by the next: missing key or value (01), unmapped rate type or compounding (02), tenor not a positive whole number (03), rate outside -0.05 to 2.0 (04), invalid currency or a second currency of the curve (05), duplicate point (06), a curve on a date with two rate types or compoundings (07), PAR or FORWARD at a tenor that is not whole years (10). An empty compounding is ANNUAL.
- The currency of a curve is the one of most of its rows, then of the earliest source row; the rows of the other currency are excluded. Of two rows for one curve, date and tenor the later source row is kept, identical or not (the spec says identical rows are kept once and the later of conflicting ones; keeping the later row does both). The finding lists the rows removed.
- DV-IRT-08 and -09 are checks that need the curve a run names. They are evaluated only when a curve is named and usable; otherwise they are listed as not evaluated with that reason (`quality.engine.CURVE_RULES`). DV-IRT-08 fails once for a curve older than `max_curve_age_days` (the curve is still used) and once when no date lies on or before the discount date (the basis is then unavailable). DV-IRT-09 counts forwards below -0.05 and changes of more than 0.10 between adjacent tenors, INFO, and is a finding of the run.
- `interest_rates` is read in every run that finds a sheet for it, even when no curve is named, so that the quality report and the manifest show the file (the same as the market sheet). Its file is then an input of the run and part of the run id.

## Consequences
- The quality report has one more concept ("not found in the input" when there is no sheet) and ten more rules to list as not evaluated; DQ01 does not move (rules that checked nothing add nothing).
