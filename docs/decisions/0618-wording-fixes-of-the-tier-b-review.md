# 0618 — Wording fixes from the review of the tier B drafts

## Context
The planner's review of the tier B drafts found points that need a sentence or a parameter, not a decision of their own.

## Decision
- MT15 0.2.0: the pattern sums to 1 over the observed columns, so the method has no tail; the report says so; a tail from MT14 or an assumed tail factor is applied outside the method, to the ultimates, as selected in the assumptions register, and shown separately. The limitation sentence is in `notes` (method specs have no `interpretation` field).
- MT16 0.2.0: the projected severity from the trend replaces the observed severity of mature origins too (smoothing), with both shown in the diagnostics; the reported share p(i) comes from the chain ladder of the `severity_measure` triangle. No parameter added.
- MT18 0.3.0: limits for xi = 0: x_p = u + sigma ln(N_u / (n (1 - p))), z_T = u + sigma ln(N_u T / h), ES_p = x_p + sigma. The hand fixture `MT18-gpd-closed-forms` already computes with xi = 0; only the notes of its rows changed, no value.
- MT22 0.2.0: parameter `backtest_simulations` (default 1000) for the reruns of MT06 and MT11 at past cut-offs; the bootstrap rerun is optional. AE02 0.2.0: the weighted bias B_m(h) beside the MAE.
- CV10 0.2.0: a SIMPLE point with 1 + r t not above zero is excluded and listed; a par bootstrap that gives D(n) not above zero makes the curve unavailable, with the tenor named; PAR and FORWARD points exist only at whole-year tenors. interest_rates 0.2.0: DV-IRT-08 refers to `max_curve_age_days` of CV10; new DV-IRT-10 (validity, WARNING) for PAR and FORWARD rows with a tenor not divisible by 12.
- RS04 0.2.0: the NET basis discounts the gross cash flows scaled by the origin's net-to-gross unpaid ratio (CV09), at the gross timing, labelled an approximation until treaty-level cash flows exist.

## Consequences
- All specs stay drafts; no number of any reference moved by this record.
