# 0032 — Premium structures and the row rules behind them

## Context
Earned premium, unearned premium and earned exposure (PR02, PR03, CV04) need premium, policy and market rows that obey their data rules. The quality profiler is a later item, so only the rules that change which rows or values enter these structures are applied now.

## Decision
- **Canonical rules applied:** market DV-MKT-01 to 05; premiums DV-PRM-01 to 05 and the sign normalisation of CV05 (DV-PRM-08); policies DV-POL-01 to 08. Each is a finding with its source rows. DV-MKT-06 to 08 (coverage and reasonableness of series), DV-PRM-06, 07, 09 as a feed rule and the profiler's scores are not built; DV-PRM-06 is applied where it matters, in the structure.
- **Earned premium** is built per transaction on the reinsurance basis (GROSS: the four written types of PR01; CEDED: CEDED_PREMIUM; NET: written minus ceded, signed per transaction), converted at the booking-date rate (flow rule of CV01) and, on the adjusted basis, restated from the booking month, then spread by day over [max(effective date, policy start), policy end). Transactions booked after the cut-off are ignored; periods after the cut-off month are not shown.
- **Not earned and listed:** transactions of a policy that is not in policies (DV-PRM-06) or has no cover dates (DV-POL-03). A transaction with no exchange rate, or with no index value at or before its booking month, is left out and listed (CV01, CV02); the original-currency totals of the first kind are returned apart.
- **Unearned premium** exists on the nominal basis only and is converted at the period-end rate of the valuation date (PR03, CV01).
- **Earned exposure** counts days of cover up to the cut-off month end over 365.25 times exposure units; cover ends at the earlier of end date and cancellation date (CV04).
- The original-currency view (no reporting currency) groups by currency and never adds currencies.

## Consequences
- The measures of P08 can read these frames directly; breakdowns beyond segment and line (entity, product, partner, channel) are one more grouping key each.
- Premium data is not yet part of `canary run` or its manifest.
