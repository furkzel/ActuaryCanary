# 0016 — Changes to the first parameter sheet

## Context
`synthetic/truth.yaml` (P00) was a list of illustrative inputs. Run through the generator it gave loss ratios the owner would not call a baseline, and some parameters had no counterpart in the version 1.0 input set.

## Decision
- Third-party liability premium per policy 600 → 5,500. At 600 the loss ratio was about 400 per cent before inflation; at 5,500 it starts near 100 per cent and rises with claims inflation, because the premium follows prices but not superimposed inflation or the delay between premium and payment.
- `instalments` removed: the premium feed has no instalment types, so written premium is booked in full at issue.
- Added where the input set needs them: `products`, `causes`, `exposure_units` (persons in a group life policy), `endorsement_probability`, `refund_probability`, `acquisition_share`, `other_share_of_earned` (entity-level expense without segment or line), `max_settlement_days`, `future_annual_rate`, `messiness`, `large_claims`.
- Sizes: `tiny` is 0.2 per cent of the portfolio, accident years 2022–2025, four times the persons per group policy (so deaths occur), fault counts × 0.3; `large` is 55 per cent, which gives just under one million valuation rows. The old `outputs` list is replaced by the fixed set of truth files.

## Consequences
- Anything compared with the old sheet's numbers must use the new premium.
- A different premium level is a one-line override in a scenario file.
