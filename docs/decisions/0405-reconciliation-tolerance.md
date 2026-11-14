# 0405 — Reconciliation of the computed application with the reported ceded amounts

## Context
M08 compares what the treaty table cedes when the platform applies it (MT21) with what the data report as ceded (record 0406). DV-RTR-09 and DV-RTR-11 stay the data rules between feeds; this comparison is the module's own.

## Decisions
- **Sides.** Computed: the application at the cut-off, each claim's latest valuation, summed per treaty and treaty year (section) and converted into the treaty currency at the constant cut-off rate (CV01). Reported: the claim movements of `reinsurance_transactions` booked up to the cut-off, given with a claim_id or allocated per CV09 (claim parts by the claim's section; cell parts by origin year = treaty year), in the same currency.
- **Basis.** Ceded incurred (paid plus case reserve). Paid is shown in `ceded_by_treaty.csv` beside it.
- **Tolerance.** A treaty year differs when |computed − reported| > max(1.00, 1 % of the larger of the two). One per cent leaves room for the rounding of indexed terms to cents and for the cent splits of the allocation, which are far smaller, and still catches a treaty whose terms the data do not follow; 1.00 keeps tiny sections from differing on rounding.
- **Rows on both sides.** `reinsurance_reconciliation.csv` holds one row per treaty year with reported or computed amounts (`level` = treaty year, both sides, the difference and `differs`), then, for a treaty year that differs, every claim whose own difference passes the same tolerance (`level` = claim).
- **Premium** is shown beside claims in the treaty table (computed against booked ceded premium, commission and reinstatement premium) but is not part of the tolerance: the generator cedes quota-share premium on gross premium and excess-of-loss premium on gross written premium, while MT21 cedes on what the inuring treaties leave and rates on GNPI (record 0403), so a premium difference is expected there.

## Consequences
- On the tiny reinsurance_heavy run the reconciliation flags QS_MOTOR_OD 2022 and 2024 (claims with injected extreme payments: the data's gross moved, the reported ceded did not) and the indexed TPL layers (the data follow the occurrence-date clause, the default is payment by payment).
- The finding rule on a treaty that differs uses these rows (stage 5, record 0408).
