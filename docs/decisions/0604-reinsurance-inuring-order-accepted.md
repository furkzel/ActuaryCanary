# 0604 — Reinsurance inuring order accepted as drafted

## Context
Record 0202 proposed an order in which treaties apply to a claim, and the CV09 draft states it: SURPLUS first, then QUOTA_SHARE on the retained part, then risk EXCESS_OF_LOSS, then event EXCESS_OF_LOSS, then STOP_LOSS, each on what the previous ones leave; FACULTATIVE comes before all of them on its own policies.

## Decision
Chosen by the owner on 2026-10-24: the inuring order is accepted as proposed in the spec.

## Consequences
- CV09 0.2.0 notes the acceptance. The rule is unchanged.
- The index-clause approximation of the same spec is not part of this decision and stays open for the owner's review of CV09.
- A programme whose order differs would need a setting; none is specified.
