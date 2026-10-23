# 0203 — Recovery transactions win over the to-date fields

## Context
Recoveries can arrive twice: as recovery transactions, and as `subrogation_to_date` and `salvage_to_date` on claim valuations (version 1.0). Blueprint 5 says that when both kinds of fact exist the platform checks they agree and reports every difference. It does not say which one is used.

## Decision (proposed, draft)
- With only the to-date fields, recovery flows are their increments between consecutive valuations (CV04 flow rule). They are booked at the month end of the later valuation and typed RECOVERY_SUBROGATION or RECOVERY_SALVAGE. RECOVERY_OTHER is then unavailable.
- With transactions, the transactions are used. The to-date fields are reconciled against the accumulated transactions at each valuation, and every difference is listed (DV-RCV-08).
- A negative increment is a reversal and is kept.
- M07 runs on either source (required_any recoveries or claim_valuations). Each measure skips with its own reason when neither source has its fields.

## Consequences
- Delays from derived flows are whole months between month ends; RC03 labels them.
- Transactions carry booking dates and RECOVERY_OTHER, so they are the more precise source when present.
