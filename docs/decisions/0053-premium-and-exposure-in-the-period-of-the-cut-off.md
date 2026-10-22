# 0053 — Earned premium and exposure in the period that contains the cut-off

## Context
`structures.premium` spread each transaction over the periods of its cover up to the cut-off month, but a period longer than a month that contains the cut-off counted its whole overlap with the cover, including days after the cut-off. With monthly periods nothing was wrong; with yearly periods (the default of the module views) the last year was overstated, and earned plus unearned premium did not equal written premium. The measure tests found it.

## Decision
- The overlap of a period with the cover is clipped at the day after the cut-off. Earned exposure (CV04) uses the same expansion and is clipped the same way.
- The structure gains optional arguments with unchanged defaults: `by` (policy attributes to group by, default segment and line), `row_column` (source rows kept per value, for lineage) and `PremiumSettings.transaction_types` (earn other transaction types such as COMMISSION and RI_COMMISSION like premium, for EX01 and RI02). `booked_transactions` exposes the converted flows for PR01. Its group-bys keep their order, so results are byte-identical between runs.
- `expense_allocated_to_date` joins the flow components and `expense_allocated` the money measures of `convert.bases` (EX03).

## Consequences
- Yearly earned premium and exposure of the last year are lower than before whenever the cut-off is not a year end. On the baseline medium (cut-off 2025-12-31) nothing changes; earned premium by entity, year and currency equals the generator's truth to 1e-11.
