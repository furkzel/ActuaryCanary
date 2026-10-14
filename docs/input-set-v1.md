# Input set for version 1.0

Version 1.0 reads one cumulative spreadsheet per concept. Column names are flexible (they are matched through the alias dictionary), but the content and grain below are fixed. Fields marked * are required for the concept to be built. Only `claim_valuations` is required for a first report; every other file adds analyses.

## claim_valuations.xlsx (required)
One row per claim per valuation date (normally month end). Amounts are cumulative to that date.

| Field | Type | Note |
| --- | --- | --- |
| claim_id* | text | |
| valuation_date* | date | month end |
| paid_to_date* | number | gross, original currency |
| case_reserve* | number | gross outstanding estimate at the valuation date |
| status* | text | OPEN, CLOSED, CLOSED_NIL, REOPENED, LITIGATED (any labels; mapped) |
| currency* | text | ISO 4217 |
| subrogation_to_date | number | recoveries, positive |
| salvage_to_date | number | recoveries, positive |
| expense_allocated_to_date | number | allocated claim expenses |
| ceded_paid_to_date | number | reinsurers' share of paid |
| ceded_reserve | number | reinsurers' share of case reserve |

## claims.xlsx
One row per claim.

| Field | Type | Note |
| --- | --- | --- |
| claim_id* | text | |
| occurrence_date* | date | |
| report_date* | date | |
| segment* | text | NON_LIFE, LIFE, PENSION, HEALTH |
| line* | text | line of business |
| entity | text | company or legal entity |
| policy_id | text | links to policies |
| product | text | |
| partner | text | channel or partner |
| cause | text | |
| close_date | date | |
| event_code | text | catastrophe event |

## policies.xlsx
One row per policy (latest version).

| Field | Type | Note |
| --- | --- | --- |
| policy_id* | text | |
| start_date* | date | |
| end_date* | date | |
| segment* | text | |
| line* | text | |
| currency* | text | |
| entity, product, partner, channel | text | |
| issue_date, cancellation_date | date | |
| sum_insured | number | |
| exposure_units | number | default 1 per policy-year |

## premiums.xlsx
One row per premium transaction, all transactions to date.

| Field | Type | Note |
| --- | --- | --- |
| transaction_id* | text | |
| policy_id* | text | |
| booking_date* | date | |
| amount* | number | |
| currency* | text | |
| type* | text | WRITTEN, ENDORSEMENT, CANCELLATION, REFUND, COMMISSION, CEDED_PREMIUM, RI_COMMISSION |
| effective_date | date | |

## expenses.xlsx
One row per expense booking.

| Field | Type | Note |
| --- | --- | --- |
| period* | date | month end |
| amount* | number | |
| currency* | text | |
| type* | text | ACQUISITION, ADMINISTRATION, CLAIMS_HANDLING_UNALLOCATED, OTHER |
| entity, segment, line | text | |

## market.xlsx
One row per series per date. Sheets may split series (for example `fx`, `cpi`).

| Field | Type | Note |
| --- | --- | --- |
| series_id* | text | e.g. USD/TRY, EUR/TRY, CPI_TR |
| date* | date | |
| value* | number | |
| kind* | text | FX_SPOT, FX_PERIOD_AVERAGE, FX_PERIOD_END, PRICE_INDEX |

## Rules for every file
- One table per sheet, header in the first non-empty row, no merged cells inside the table.
- Dates as real dates; identifiers and codes as text; amounts as numbers in original currency.
- No personal data. Names, national identity numbers, customer numbers, phone numbers and addresses are dropped on load if present.
- Derived columns (quarters, year-month labels, development lags) are ignored and recomputed.
