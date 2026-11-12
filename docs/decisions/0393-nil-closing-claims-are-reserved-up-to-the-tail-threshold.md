# 0393 — A claim that closes at nil is reserved from its latent cost capped at the tail threshold

## Context
Record 0372: a claim that closes at nil (`nil_close_probability`, drawn independently of size) ends with zero paid, but until it closes its case reserve was built from its latent cost, the same cost a paying claim of that size would have. One such claim made 31 % of the demo's MOTOR_TPL 2025 incurred. The owner decided (2026-11-12): the phenomenon (reserves held on claims that later close at nil) stays; the reserve is capped at the line's tail threshold, so that a single claim can no longer outweigh a line-year.

## Decision
- In the review step of `claims.py`, a nil-closing claim's case reserve estimate is `min(latent cost, cap) × price index at the review day × remaining weight`; the cap is `severity.tail.threshold / fx0` of the claim's line. Everything else of the estimate (the bias rows, the noise, the weights) is untouched. Claims that do not close at nil, the payments, the ultimates and the claims' costs do not change.
- **Price level.** `cost` is at base-date prices in the claim's own currency; the threshold is written in the reporting currency at the same price level, before the line's severity multiplier. So the cap is divided by the exchange rate at the base date (`fx0`, 1 for the reporting currency) and then moves with the same index as the cost: the reserve of a capped claim is `threshold × index(review day) × bias × noise × remaining`. The cap acts on the cost actually drawn (litigation and override multipliers included), not on the body draw.
- **Why this reading of "the line's tail threshold".** The tail model of a line is a Pareto from `threshold`; the threshold is the cost above which the generator calls a claim a tail claim. A reserve for a claim that will pay nothing is thus never larger than the smallest tail claim.
- **Lines without a tail model** (the sum-insured lines such as PROPERTY, and any line without `severity.tail`): no cap. Their cost is bounded by the sum insured, so the artefact cannot arise; a cap there would have no threshold to name.

## Consequences
Case reserves, incurred and the ledger move wherever a nil-closing claim exceeds its cap (record 0395). The truth columns that hold reserves (`case_reserve_at_cutoff`, `incurred_at_cutoff`, `ibnr_at_cutoff`, the reserve-dependent files) move with them; paid, ultimates and development patterns of paid do not.
