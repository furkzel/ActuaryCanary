# 0031 — Payment outlier rule and recorded recoveries (claim_valuations 1.1.0)

## Context
The task asks for "cumulative paid never decreasing except with a recorded reason" and for outlier payments to be found. DV-CLV-07 of claim_valuations 1.0.0 allowed no exception and no rule covered outliers. A robust z-score of the log payment does not separate the injected outliers (20 to 50 times the line median) from the natural tail: their z is 2.6 at most, like genuine large payments, because payment sizes spread widely.

## Decision
- The reviewed specification claim_valuations is changed to 1.1.0 (the owner reviewed 1.0.0; this change needs their review). DV-CLV-07: a decrease is explained when subrogation plus salvage rose by at least the decrease at that valuation; the data has no other field that could record a reason.
- New rule DV-CLV-15 (WARNING, reasonableness): a payment between two valuations of a claim is at most 10 times the claim's paid plus case reserve at the earlier valuation; not evaluated when that amount is zero. On the tiny baseline the two injected outliers have ratios 41 and 22; the next largest genuine ratio is 2.1.
- The multiple 10 is written in the rule text, not a setting.

## Consequences
- A first payment on a claim, or a payment after a zero estimate, cannot be flagged. The ratio rule is not a statistical outlier test; MT08 (robust z-score flags) remains the planned one.
