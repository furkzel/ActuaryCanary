# 0273 — Scope of the reinsurance what-if fixture

## Context
The MT21 spec asks for hand cases of every treaty type, aggregate terms, two reinstatements and an index clause. The work item asks for quota share, surplus and per-risk excess of loss on about a dozen claims.

## Decision
One fixture of twelve claims (amounts in thousands) applies a 30 % quota share with 25 % commission, a surplus with a retained line of 400 and four lines, and a per-risk excess of loss 200 xs 100, each alone on gross and then as a programme in the CV09 inuring order of record 0604. Premium side: ceded premium and commission of the quota share, ceded premium of the surplus, flat excess-of-loss premium. Aggregate deductible and limit, reinstatements with premium, stop loss, event excess of loss and the index clause are not covered.

## Consequences
- Those cases are open items of MT21 in `coverage.yaml`; P30 adds them with the treaty-level allocation of CV09.
- The surplus share is min(max(SI − line, 0), lines × line) / SI; capacity above five lines is not ceded.
