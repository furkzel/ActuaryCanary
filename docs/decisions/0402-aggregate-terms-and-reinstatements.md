# 0402 — Aggregate terms and reinstatements: the conventions where CV09 leaves a choice

## Context
CV09 applies the aggregate deductible and limit "per contract period in claim order of booking date; the claim that exhausts or crosses a term gets the part that fits", and gives the reinstatement premium RP = ρ · P · min(mL, C)/L. The order, the basis of the terms, the split into paid and reserve and the premium base are not fixed.

## Decisions
- **Unit order.** The units of a section (claims or events) enter the aggregate in the order of the first valuation date at which their ceded incurred is positive (the booking of their first ceded amount), then their first occurrence date, then their identifier. The order is the same at every date, so a later valuation does not reshuffle what was allocated before.
- **Basis.** The terms apply to the 100 % layer before the placed share, on ceded incurred, at every date: through(t) = min(AAL, max(0, Σ_{units up to u} C_u(t) − AAD)); each unit gets the difference to the units before it. Ceded paid of a unit after the terms is its ceded incurred after the terms times its paid share before them (C_paid/C_incurred), so paid never exceeds incurred and the reserve stays non-negative.
- **Annual limit.** Given `aggregate_limit`, else limit × (1 + reinstatements) when reinstatements is given, else unlimited (treaties spec). Empty `reinstatements` means unlimited free cover: no reinstatement count and no premium.
- **Reinstatements used** = min(m·L, C)/L with C the ceded amount after the aggregate terms at the last valuation; **reinstatement premium** = ρ · π · P · min(m·L, C)/L, pro rata as to amount, not as to time, with P the 100 % deposit premium of the layer (premium_rate × the layer's premium base, built with the premium side) and π the placed share. L is the stated limit (at inception prices); with an index clause C is the nominal ceded amount.
- **Use reported per section**: units hit, units whose ceded amount reached the limit, ceded before and after the aggregate terms, the deductible used, whether the annual limit is exhausted, reinstatements used and their premium (`Application.layer_frame`, the layer table of M08).
- Aggregate terms on a stop loss are not applied (its own retention and limit are already annual); an excess of loss with loss basis AGGREGATE is one unit, so its retention and limit are its aggregate terms.

## Consequences
- Hand cases (fixture MT21): layer 100 xs 50 on five claims, two reinstatements at 100 % with deposit premium 30 (300 ceded, two reinstatements used, premium 60), and an aggregate deductible of 60 with an aggregate limit of 130 crossed by the first and third claims.
- The generator makes no aggregate terms or reinstatements (record 0240): these conventions are proved by hand cases only, not against generated truth.
