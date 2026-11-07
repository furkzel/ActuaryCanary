# 0327 — The curve and the discount date are in the manifest and the run id

## Context
The goal: "the curve and the discount date enter the manifest and the run id".

## Decision
- `RunSettings.discount` (curve_id, discount_date, timing, max_curve_age_days, tail_payment_years) is part of the settings record, so of the run id; so is the value basis DISCOUNTED (`bases.value`), and the register entries of CV10 and RS05 (they are in `assumptions`).
- The curve file is an input like any workbook (name, size, SHA-256), so a changed curve gives another run id. The resolved facts follow from inputs and settings and are written next to the settings, not into the id (as `cut_off_used`, 0023): `settings.discount_used` has the curve id and date used, its age in days, currency, rate type, compounding and source, the discount date, the timing and tail years, or the reason there is no curve.
- The specs used by a run list CV10 only when a curve is used; M12, RS04 and RS05 and the concept `interest_rates` are listed with the other built specs.
- Findings of the curve (an old curve, excluded simple points, an odd forward curve) are findings of the run and appear in the report with the others.

## Consequences
- Every run id moves once (new specs and versions, new settings keys). The run ids are in the handover.
