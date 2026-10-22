# 0033 — How the bases reach the triangles, and what CV01 and CV02 leave open

## Context
P07 puts every amount on the reinsurance (CV03), currency (CV01) and value (CV02) bases. The specifications fix the rates and the index; they do not say what happens when a rate or an index value is missing at one row of a cumulative series, or how empty cells and mixed currencies behave.

## Decision
- **Nominal basis:** every amount of a triangle is converted with the one constant stock rate of the development rate date per currency (CV01). **Inflation-adjusted basis:** the flow between two consecutive rows of a claim is converted at the FX_PERIOD_AVERAGE rate of the month of the later row and restated with the index of that month; the case reserve is converted at the FX_PERIOD_END rate of its valuation month (FX_SPOT within 7 days, flagged) and restated with the index of that month; paid is the accumulated restated flows and incurred is that plus the restated reserve (CV02). Net is the restated gross minus the restated ceded component, row by row.
- **No average rate for a booking month:** CV01 names no fallback for a derived flow, so none is invented. The flow is not converted; because every later cumulative amount of the claim contains it, the claim is left out of the adjusted triangles from that row on and is listed (finding CV01, and the as-of totals at the cut-off by currency). The same holds for a month with no index value and none earlier (CV02). A row with currency UNKNOWN is such a row.
- **Value date without an index value:** the latest earlier month is used and a CV02 note says so.
- **Empty cells:** an empty ceded field of a present column counts as zero (CV03); for any other amount a row with an empty cell is left out of that measure and the claim's previous row carries forward (0024); a flow is differenced against the last known cumulative value.
- **A claim that changes currency** between two rows: the flow is the difference in original units, converted in the currency of the later row (DV-CLV-12 lists the claim).
- **Measures:** paid, incurred, case_reserve, subrogation, salvage, recoveries (their sum), paid_net_of_recoveries, reported_count, open_count, closed_count. Recoveries exist on the GROSS basis only; asking for them as CEDED or NET is an error that names CV03. A basis whose ceded field is not loaded is an error, never gross (CV03). Counts do not depend on money bases.
- **Underwriting origin:** the start_date of the policy linked through claims.policy_id; a claim whose policy or start date is missing is left out and listed, as for an empty occurrence date.

## Consequences
- With complete market data the adjusted basis loses nothing; with gaps the loss is visible and bounded to the claims concerned.
- If the owner prefers a fallback for a missing average rate (for example the latest earlier month), CV01 changes first, then `convert/currency.py`.
