# 0202 — Reinsurance feeds and treaty-level allocation

## Context
Blueprint 4.2 names the treaty and transaction feeds, and 7.3 says how treaty-level ceded amounts are allocated. Several choices are not fixed there.

## Decision (proposed, draft)
- **Treaty grain.** One row per treaty or layer, contract period and line. Each excess-of-loss layer has its own treaty_id. Key: treaty_id, inception_date, line. Empty line, segment or entity means all.
- **Movements.** CEDED_CASE_RESERVE is a change of the ceded reserve, like the claim transactions of blueprint 4.2. The reserve at a date is the sum of the changes booked up to it. Amounts are positive magnitudes per type (CV05).
- **Precedence (CV09).** A ceded amount given per claim is never re-allocated. claim_valuations wins over reinsurance_transactions for claim views, and differences are listed (DV-RTR-09). Ceded premium in the premiums feed and in reinsurance_transactions is compared (DV-RTR-11). The treaty feed serves views by treaty; premiums serves views by policy.
- **Allocation.** Proportional treaties are allocated by gross movement times cession share. Excess of loss applies the layer terms per claim or event, cumulatively at each valuation, and the booked amount is allocated by the change of expected ceded. Without claim-level data, allocation is by gross incurred of line and origin cells, labelled as an approximation.
- **Inuring order.** Surplus, quota share, risk XL, event XL, stop loss; facultative first on its own policies.
- **Index clause.** Approximated with the claim's paid-weighted average payment month. The report states the approximation.

## Consequences
- MT21 uses the same terms and order. Its ground truth is the generator's own ceded amounts (generator item).
- The owner may change the inuring order or the index approximation while reviewing CV09.
