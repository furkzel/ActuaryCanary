# 0206 — Ledger account-mapping profile

## Context
Blueprint 10 makes the account-mapping profile what improves M10, and 4.3 lists the account classes. Charts of accounts differ by company; signs and year-to-date balances differ by system.

## Decision (proposed, draft, CV12)
- **Profile file.** The profile is a data file like the column mapping profiles (record 0028), confirmed once, reused, and part of the run id. Each rule holds an entity, an exact account code or a prefix with `*`, a class, a sign and a balance kind. The longest match wins; two equal-length matches are a profile error.
- **Sign.** Default sign -1 for credit-normal classes (PREMIUM, OUTSTANDING, UPR, RI income) and +1 for debit-normal ones, so ledger amounts become the platform's positive magnitudes (CV05).
- **Balance kind.** Year-to-date income and expense balances are differenced within the fiscal year. Balance-sheet classes are compared at period end.
- **Materiality.** A gap is material above both 0.5 per cent of the ledger amount and an absolute amount, 0 by default. The 0.5 per cent is a placeholder for the owner to confirm.
- **Not reconciled.** INVESTMENT and OTHER. They count as mapped in FN02.

## Consequences
- A ledger outstanding that includes IBNR needs the profile to say so. Otherwise the gap shows the IBNR, and the report names that as a likely cause.
- No account names are used in measures; they are evidence on the mapping screen only.
