# 0220 — DV-MKT-06, DV-MKT-07, DV-MKT-08 and DV-PRM-07 are built

## Context
Version 1.0 left four data rules unevaluated; the quality report listed them as "no check is implemented for this rule yet". Their specifications said what to check but not what is counted, which series a run needs, or how a daily series becomes months.

## Decision
- **Spec first:** `market` 1.1.0 and `premiums` 1.1.0 add the missing detail; no rule changes meaning.
- **DV-MKT-06** counts months: expected from the first to the last month of each series and monthly kind, against months without a value. FX_SPOT is daily and not checked. The listing names the first five missing months; source references point to the row before the gap.
- **DV-MKT-07** needs the reporting currency, the price index and the value basis of the run, so `evaluate` takes them (`Context.reporting_currency`, `price_index`, `adjusted`). Needed: the pair of every currency with amounts (valuations, premiums, expenses), direct or inverse, any FX kind, from the earliest amount to the cut-off month; the price index when the run restates with it or the data holds it. A currency with no series at all fails every month.
- **DV-MKT-08** reduces each series and kind to one value per month (latest date, then latest source row; this includes FX_SPOT) and scores the log change between consecutive months with the MT08 formula and threshold, within the series, with no minimum number of changes.
- **DV-PRM-07** checks the premiums of known policies; an empty effective_date means booking_date; without an effective_date column the rule is not evaluated.
- Severities stay as specified (WARNING, WARNING, INFO, INFO).

## Consequences
- The four rules leave "not evaluated". On `examples/demo` DV-MKT-07 now reports the months before the first market date (the known gap "premium booked before the first market date has no rate") as a WARNING; DQ01 moves by the rules' pass rates, nothing else.
- Run ids change for every example because `market` and `premiums` have new versions.
