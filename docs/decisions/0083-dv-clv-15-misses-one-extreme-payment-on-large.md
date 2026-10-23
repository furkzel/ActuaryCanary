# 0083 — Why DV-CLV-15 finds 7 of 8 injected extreme payments on `large`

## Context
Record 0080 and the G2 result: on `large` the quality check found every injected fault with the exact count except DV-CLV-15, which found 7 of 8 injected extreme payments (2 of 2 on tiny). The cause was not looked into.

## Finding
Not a bug: the check does what its specification says, and one injected payment does not break that rule.
- The generator adds to a claim's paid amount a spike of 20 to 50 times the median payment of the claim's line (`synthetic/faults.py`). DV-CLV-15 (`spec/data/claim_valuations.yaml`, version 1.1.0) flags a payment above 10 times the claim's own paid plus case reserve at the earlier valuation.
- The two measure different things. If the claim was already large, the spike is below 10 times its earlier amount. The missed payment is claim 00069458 at 2023-07-31 (worksheet row 677783): payment 1,464,093 against an earlier amount of 236,231, ratio 6.2. The other seven injected payments have ratios from 19 to 232.
- Checked by running the rule's expression over `canonical/claim_valuations.parquet` of `large`: seven rows exceed 10 times, all seven injected, none other; the eighth injected row is the one under the line. Quality counts the same seven (894,508 rows checked).
- On a smaller portfolio a chosen claim is less likely to be large already, which is why tiny shows no miss.

## Decision
Nothing is fixed. The rule stays as specified, and the injected fault stays as it is: the payment is a genuine outlier for M06 (MT08), and a data rule that tests a payment against the claim's own earlier amount is right not to call it a data error. Follow-up for the owner, not done: choose the injected rows so that the spike exceeds ten times the claim's earlier amount, or state in the scenario that DV-CLV-15 finds only the outliers on claims not yet large.

## Consequences
- The exact-count test of the injected faults stays on the committed tiny fixtures, where all faults are found.
- "Every injected fault found" in the G2 result reads: all but this one, for the reason above.
