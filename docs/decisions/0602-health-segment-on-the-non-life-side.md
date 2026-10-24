# 0602 — Health segment on the non-life side

## Context
Blueprint 18.2 asked whether a health segment belongs with life, with non-life, or in a concept of its own. The drafts of `life_in_force` and M11 left it open.

## Decision
Chosen by the owner on 2026-10-24: health is handled on the non-life side. Its feeds are claims-based, its business is short-term, and it has no life-style exposure. Revisit only if the life feed work shows a need.

## Consequences
- `life_in_force` 0.2.0 and M11 0.2.0 do not cover health contracts and drop their `requires_decision` entry on it.
- `HEALTH` stays a segment class of the existing concepts (claims, policies, premiums, expenses, ledger, reinsurance), so health data runs through the non-life modules as it does now.
- No health-specific measure or method is drafted.
