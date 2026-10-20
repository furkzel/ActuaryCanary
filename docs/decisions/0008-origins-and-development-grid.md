# 0008 — Origins and the development grid

## Context
Triangles need an origin per claim and comparable development ages. Version 1.0 requires only claim valuations, which carry no occurrence date, and the cut-off is often not a year end.

## Decision
- Default origin axis: accident (claims.occurrence_date). When claims is not loaded, or a claim has no header, the origin is the month of the claim's first valuation, a proxy for the report period, labelled as such. Chosen by the owner on 2026-10-20 over skipping reserving.
- Development is aligned to the cut-off: valuation points are the cut-off and every development length before it. Development age counts the months from the first month of the origin to the valuation month, both included. Origin length must be a whole multiple of development length (CV04).
- The state of a claim at any date is its latest valuation row on or before that date (carry-forward); flows are differences of consecutive rows.

## Consequences
- A first report with only claim valuations still produces triangles and chain ladder, labelled as report-period proxies.
- Bornhuetter–Ferguson, Cape Cod and the expected loss ratio method need accident or underwriting origins and are skipped on proxy origins.
- With a mid-year cut-off, annual triangles show ages 6, 18, 30… months instead of 12, 24, 36…; every origin stays in the triangle.
