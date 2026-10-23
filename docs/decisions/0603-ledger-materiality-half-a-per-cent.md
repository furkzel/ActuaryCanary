# 0603 — Ledger materiality of 0.5 per cent is accepted

## Context
Record 0206 proposed that a ledger gap is material above both 0.5 per cent of the ledger amount and an absolute amount (zero by default), and called the 0.5 per cent a placeholder for the owner to confirm.

## Decision
Chosen by the owner on 2026-10-24: the materiality ratio of 0.5 per cent is accepted as the default and stays configurable, as does the absolute amount.

## Consequences
- CV12 0.2.0 no longer calls the figure a placeholder. The ratio and the amount remain parameters of the ledger reconciliation (FN01, M10).
- The rest of record 0206 (profile file, sign, balance kind, accounts not reconciled) is unchanged and still a draft.
