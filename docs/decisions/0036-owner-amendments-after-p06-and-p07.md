# 0036 — Owner-approved amendments after P06 and P07 (claim_valuations 1.2.0, CV01 1.1.0)

## Context
After P06 and P07 the owner approved three changes to reviewed specifications. Each is a spec change first, then code. The DV-CLV-07 part supersedes the first decision of record 0031; its DV-CLV-15 part stands.

## Decision
- **DV-CLV-07 back to its original wording (claim_valuations 1.2.0):** paid_to_date never decreases between consecutive valuations of a claim; a decrease is kept as given (the increment is negative) and listed. There is no exemption for recoveries, because paid_to_date excludes recoveries by definition (subrogation and salvage are their own fields). The exemption code and its test were removed. DV-CLV-15 is unchanged.
- **DV-CLV-03, action (claim_valuations 1.2.0):** a row with an empty or invalid currency takes the currency of its claim and is flagged when the other rows of that claim that carry a valid currency all carry the same single one. Otherwise it stays UNKNOWN as before. Rows that themselves have an empty or invalid currency do not count as "other rows"; a claim with two empty rows and valid rows of one currency fills both. Two findings of DV-CLV-03 are written, one for the rows that took a currency and one for the rows that became UNKNOWN; both count as failed rows of the rule.
- **CV01, flow derived from two claim valuations (CV01 1.1.0):** when the FX_PERIOD_AVERAGE rate of the booking month is missing, the FX_PERIOD_END rate of the same month is used and flagged (an INFO finding of CV01); when that is missing too, the amount is not converted and is listed, and the claim leaves the inflation-adjusted triangles from that row on, as before.

## Consequences
- On baseline tiny the three decreases found are exactly the three injected faults (rows 37, 272, 1038); no decrease outside the injected faults.
- The four injected empty currencies of baseline tiny now take the currency of their claim; they no longer leave the converted and adjusted triangles. Two tests that encoded the old behaviour were updated (the not-converted currencies of the default run; the MT01 ground-truth effect of a missing currency on baseline medium).
- Record 0033 (formerly numbered 0030 on the P07 branch) said no fallback is invented for a missing average rate; CV01 1.1.0 now names one, and 0033's open question is closed.
